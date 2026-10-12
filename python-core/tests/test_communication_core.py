"""Real SQLite tests of communication invariants; no real provider/session I/O."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from uuid import uuid4

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_os.application.services.communication_core import CommunicationService
from agent_os.application.services.communication_worker import CoreCommunicationWorker
from agent_os.domain.entities.communication import (
    AccessDenied, Caller, Claim, CommunicationError, Conflict, ProviderEvidence,
    StaleAttempt, delivery_identity,
)
from agent_os.infrastructure.composition.local_platform import build_communication_directory as PlatformCommunicationDirectory
from agent_os.infrastructure.composition.local_platform import build_local_platform_operation_service
from agent_os.infrastructure.persistence.communication_store import SqliteCommunicationRepository
from agent_os.infrastructure.persistence.sqlite_persistence import SqlitePlatformPersistence


class Clock:
    def __init__(self):
        self.now = datetime(2026, 9, 28, 8, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class CommunicationCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "platform.sqlite3"
        self.connection = sqlite3.connect(self.path)
        self.addCleanup(self.connection.close)
        SqlitePlatformPersistence(self.connection).initialize()
        self.platform = build_local_platform_operation_service(self.connection)
        self.platform.create_workspace(workspace_id="w", display_name="Test", root_path=self.temp.name,
                                       agent_id="a", agent_name="A", agent_description="Synthetic sender")
        for agent in ("b", "c", "d"):
            self.platform.create_agent_registration("w", agent_id=agent, name=agent, description="Synthetic recipient")
        for agent in ("b", "c"):
            self.platform.register_codex_session_handle("w", agent_id=agent, handle_id="handle-" + agent,
                codex_session_id=str(uuid4()), cwd=self.temp.name, created_by="fixture", reason="offline fixture")
            self.platform.login_agent_endpoint("w", agent_id=agent, alias=agent, provider="codex", provider_handle_id="handle-" + agent)
        self.platform.login_agent_endpoint("w", agent_id="b", alias="b-alt", provider="codex", provider_handle_id="handle-b")
        self.clock = Clock()
        self.repo = SqliteCommunicationRepository(self.connection)
        self.repo.initialize()
        self.directory = PlatformCommunicationDirectory(self.connection)
        self.service = CommunicationService(self.repo, self.directory, clock=self.clock)
        self.a, self.b, self.c, self.d = (Caller("w", a) for a in ("a", "b", "c", "d"))

    def send(self, *, target="b", key=None, **kwargs):
        return self.service.send(self.a, target_alias=target, body="Synthetic work", key=key or str(uuid4()), **kwargs)

    def claim(self, message, **kwargs):
        result = self.service.claim("w", message["id"], owner="fake-worker", **kwargs)
        self.assertEqual(result["outcome"], "claimed")
        return Claim(**result["claim"])

    def evidence(self, claim, **kwargs):
        binding = self.repo.get("attempts", "w", claim.attempt_id)["binding"]
        return ProviderEvidence(binding["provider"], binding["native_session_id"],
                                kwargs.pop("outcome", "finished"), "synthetic:completed-turn",
                                generation=binding["generation"], **kwargs)

    def parallel(self, action, count=2):
        barrier = threading.Barrier(count)
        def run(index):
            connection = sqlite3.connect(self.path)
            try:
                repo = SqliteCommunicationRepository(connection)
                service = CommunicationService(repo, PlatformCommunicationDirectory(connection), clock=self.clock)
                barrier.wait(timeout=5)
                try:
                    return action(service, index)
                except CommunicationError as exc:
                    return exc
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=count) as pool:
            return list(pool.map(run, range(count)))

    def test_schema_is_opt_in_and_legacy_events_remain_independent(self):
        c = sqlite3.connect(":memory:")
        self.addCleanup(c.close)
        SqlitePlatformPersistence(c).initialize()
        self.assertFalse(c.execute("SELECT name FROM sqlite_master WHERE name LIKE 'communication_%'").fetchall())
        before = self.connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0]
        self.send()
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0], before)
        self.repo.initialize()
        self.assertEqual(self.repo.high_water(), 1)

    def test_ack_progress_final_are_distinct_and_no_reverse_dispatch(self):
        message = self.send(expectation="final")
        identity = message["id"]
        ack = self.service.ack(self.b, identity, key="ack")
        self.assertEqual(self.service.ack(self.b, identity, key="other-ack"), ack)
        self.service.reply(self.b, identity, body="Working", kind="progress", key="progress")
        final = self.service.reply(self.b, identity, body="Done", key="final")
        self.assertEqual(self.service.reply(self.b, identity, body="Done", key="final"), final)
        for kwargs in ({"body": "Changed", "key": "final"}, {"body": "Done", "key": "different-key"}):
            with self.assertRaises(Conflict):
                self.service.reply(self.b, identity, **kwargs)
        state = self.service.status(self.a, identity)
        self.assertTrue(state["acknowledged"])
        self.assertEqual(state["reply"], "final")
        self.assertEqual([r["kind"] for r in state["receipts"]], ["ack", "progress", "final"])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_deliveries").fetchone()[0], 1)
        self.assertEqual(self.service.claim("w", identity, owner="worker")["outcome"], "already_replied")
        self.assertEqual([i["kind"] for i in self.service.inbox(self.a)["items"]], ["ack", "progress", "final"])
        message["body"] = "Client mutation"
        self.assertEqual(self.service.get(self.a, identity)["body"], "Synthetic work")

    def test_reject_ends_wait_without_fabricating_an_ack(self):
        message = self.send()
        observation = self.service.observe(self.a, message["id"], condition="ack", deadline=self.clock.now + timedelta(seconds=10), key="wait")
        self.service.reply(self.b, message["id"], body="Outside scope", kind="reject", key="reject")
        self.assertEqual(self.service.observation_status(self.a, observation["id"])["state"], "rejected")
        self.assertFalse(self.service.status(self.a, message["id"])["acknowledged"])

    def test_atomic_send_faults_roll_back_every_projection_and_idempotency(self):
        baseline = self.repo.projection_snapshot()
        for stage in ("after_event", "after_threads", "after_messages", "after_deliveries", "after_projection", "before_commit"):
            with self.subTest(stage=stage):
                def fail(current):
                    if current == stage:
                        raise RuntimeError("injected failure")
                self.repo.fault = fail
                with self.assertRaisesRegex(RuntimeError, "injected"):
                    self.send(key="atomic")
                self.repo.fault = lambda _: None
                self.assertEqual(self.repo.high_water(), 0)
                self.assertEqual(self.repo.projection_snapshot(), baseline)
                self.assertFalse(self.connection.in_transaction)
        self.send(key="atomic")
        self.assertEqual(self.repo.high_water(), 1)

    def test_process_exit_before_commit_rolls_back_durable_database(self):
        script = """
import os, sqlite3, sys
from agent_os.application.services.communication_core import CommunicationService
from agent_os.domain.entities.communication import Caller
from agent_os.infrastructure.persistence.communication_store import SqliteCommunicationRepository
from agent_os.infrastructure.composition.local_platform import build_communication_directory as PlatformCommunicationDirectory
c=sqlite3.connect(sys.argv[1])
def fault(stage):
    if stage == 'after_deliveries': os._exit(73)
r=SqliteCommunicationRepository(c,fault=fault)
CommunicationService(r,PlatformCommunicationDirectory(c)).send(Caller('w','a'),target_alias='b',body='synthetic',key='crash')
"""
        env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR") if k in os.environ}
        env.update(PYTHONPATH=str(SRC), PYTHONDONTWRITEBYTECODE="1", TEMP=self.temp.name, TMP=self.temp.name)
        result = subprocess.run([sys.executable, "-B", "-c", script, str(self.path)], env=env, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 73, result.stderr.decode(errors="replace"))
        self.assertEqual(self.repo.high_water(), 0)
        self.assertEqual(self.connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.send(key="crash")
        self.assertEqual(self.repo.high_water(), 1)

    def test_atomic_ack_and_final_faults_leave_no_receipt_or_inbox_event(self):
        message = self.send()
        for kind in ("ack", "final"):
            baseline = self.repo.projection_snapshot()
            sequence = self.repo.high_water()
            for stage in ("after_receipts", "before_commit"):
                self.repo.fault = lambda actual, wanted=stage: (_ for _ in ()).throw(RuntimeError("receipt fault")) if actual == wanted else None
                with self.assertRaises(RuntimeError):
                    self.service.reply(self.b, message["id"], kind=kind, body="" if kind == "ack" else "Done", key=kind)
                self.repo.fault = lambda _: None
                self.assertEqual(self.repo.high_water(), sequence)
                self.assertEqual(self.repo.projection_snapshot(), baseline)
            self.service.reply(self.b, message["id"], kind=kind, body="" if kind == "ack" else "Done", key=kind)

    def test_concurrent_identical_send_has_one_business_result(self):
        results = self.parallel(lambda s, _: s.send(self.a, target_alias="b", body="Same", key="concurrent"))
        self.assertTrue(all(isinstance(r, dict) for r in results), results)
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0], 1)
        self.assertEqual(self.repo.high_water(), 1)

    def test_concurrent_conflicting_send_rejects_one_payload(self):
        results = self.parallel(lambda s, i: s.send(self.a, target_alias="b", body=str(i), key="conflict"))
        self.assertEqual(sum(isinstance(r, Conflict) for r in results), 1, results)
        self.assertEqual(self.repo.high_water(), 1)

    def test_concurrent_final_and_ack_are_unique(self):
        message = self.send()
        acks = self.parallel(lambda s, i: s.ack(self.b, message["id"], key=f"ack-{i}"))
        self.assertEqual(acks[0], acks[1])
        finals = self.parallel(lambda s, i: s.reply(self.b, message["id"], body=str(i), key=f"final-{i}"))
        self.assertEqual(sum(isinstance(r, Conflict) for r in finals), 1)
        self.assertEqual(len(self.repo.receipts("w", message["id"])), 2)

    def test_same_native_session_aliases_contend_but_different_sessions_do_not(self):
        first, second = self.send(), self.send(target="b-alt")
        messages = [first, second]
        results = self.parallel(lambda s, i: s.claim("w", messages[i]["id"], owner=f"worker-{i}"))
        self.assertCountEqual([r["outcome"] for r in results], ["claimed", "busy"])
        other = self.send(target="c")
        self.claim(other)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_attempts").fetchone()[0], 2)

    def test_expired_unstarted_claim_can_be_reclaimed_and_old_owner_is_fenced(self):
        message = self.send()
        old = self.claim(message, lease_seconds=5)
        self.clock.advance(6)
        new = self.claim(message)
        self.assertGreater(new.fence, old.fence)
        for call in (lambda: self.service.mark_started(old), lambda: self.service.release(old),
                     lambda: self.service.complete(old, self.evidence(old, stopped=True))):
            with self.assertRaises(StaleAttempt):
                call()
        self.service.mark_started(new)

    def test_expired_started_attempt_stays_unknown_until_explicit_reconciliation(self):
        first = self.send()
        old = self.claim(first, lease_seconds=5)
        self.service.mark_started(old)
        self.clock.advance(6)
        second = self.send(target="b-alt")
        self.assertEqual(self.service.claim("w", second["id"], owner="second")["outcome"], "reconcile_required")
        self.assertEqual(self.service.status(self.a, first["id"])["delivery"]["schedule"], "unknown")
        with self.assertRaises(StaleAttempt):
            self.service.complete(old, self.evidence(old, accepted=True, stopped=True))
        self.service.reconcile(old, self.evidence(old, outcome="not_delivered", stopped=True))
        new = self.claim(first)
        self.assertGreater(new.fence, old.fence)
        with self.assertRaises(StaleAttempt):
            self.service.reconcile(old, self.evidence(old, stopped=True))

    def test_release_after_start_is_unknown_and_before_start_is_safe(self):
        message = self.send()
        claim = self.claim(message)
        self.service.release(claim)
        claim = self.claim(message)
        self.service.mark_started(claim)
        self.service.release(claim)
        self.assertEqual(self.service.claim("w", message["id"], owner="other")["outcome"], "reconcile_required")

    def test_four_fake_provider_evidence_shapes_do_not_invent_replies(self):
        for provider in ("codex", "claude", "hermes", "deepseek_harness"):
            with self.subTest(provider=provider):
                original = self.directory.resolve
                self.directory.resolve = lambda w, alias, p=provider, resolve=original: replace(resolve(w, alias), provider=p)
                try:
                    message = self.send(expectation="none")
                    claim = self.claim(message)
                    self.service.mark_started(claim)
                    self.service.complete(claim, self.evidence(claim, accepted=True, stopped=True))
                    state = self.service.status(self.a, message["id"])
                    self.assertEqual(state["delivery"]["schedule"], "done")
                    self.assertEqual(state["delivery"]["execution"], "finished")
                    self.assertEqual(state["reply"], "none")
                    self.assertFalse(state["acknowledged"])
                finally:
                    self.directory.resolve = original

    def test_one_shot_core_worker_claims_after_dry_run_and_preserves_explicit_final(self):
        message = self.send(capture="provider_final_capture")
        calls = []
        def provider(actual, binding, claim, timeout):
            self.assertEqual(timeout, 120)
            calls.append(claim.attempt_id)
            self.assertEqual(actual["id"], message["id"])
            self.service.reply(self.b, message["id"], body="recipient final", key="recipient-final")
            return ProviderEvidence(binding["provider"], binding["native_session_id"],
                "finished", "synthetic:trusted-final", accepted=True, stopped=True,
                final="provider final", trusted_final=True, generation=binding["generation"])
        worker = CoreCommunicationWorker(self.service, provider)
        before = self.repo.high_water()
        preview = worker.run_once("w", dispatcher_id="fake", dry_run=True)
        self.assertEqual(preview["candidateCount"], 1)
        self.assertEqual(self.repo.high_water(), before)
        self.assertEqual(calls, [])
        result = worker.run_once("w", dispatcher_id="fake")
        self.assertEqual(result["processedCount"], 1)
        self.assertEqual(len(calls), 1)
        status = self.service.status(self.a, message["id"])
        self.assertEqual(status["reply"], "final")
        self.assertEqual(next(r for r in status["receipts"] if r["kind"] == "final")["body"],
                         "recipient final")
        self.assertEqual(status["delivery"]["execution"], "finished")

    def test_one_shot_worker_provider_exception_is_unknown_and_never_replayed(self):
        message = self.send()
        def broken(*_):
            raise RuntimeError("synthetic provider crashed after possible start")
        worker = CoreCommunicationWorker(self.service, broken)
        first = worker.run_once("w", dispatcher_id="fake")
        self.assertEqual(first["agentDispatches"][0]["outcome"], "unknown")
        self.assertEqual(self.service.status(self.a, message["id"])["delivery"]["schedule"], "unknown")
        self.assertEqual(worker.run_once("w", dispatcher_id="fake")["candidateCount"], 0)

    def test_one_shot_worker_leaves_explicit_queue_pending_when_native_target_busy(self):
        message = self.send()
        worker = CoreCommunicationWorker(self.service,
            lambda *_: (_ for _ in ()).throw(AssertionError("provider must not start")),
            preflight=lambda *_: {"runtimeState": "busy", "source": "synthetic"})
        result = worker.run_once("w", dispatcher_id="fake")
        self.assertEqual(result["agentDispatches"][0]["outcome"], "target_busy")
        self.assertEqual(self.service.status(self.a, message["id"])["delivery"]["schedule"], "pending")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_attempts").fetchone()[0], 0)

    def test_one_shot_worker_lost_lease_cannot_write_late_evidence(self):
        message = self.send()
        def late(actual, binding, claim, timeout):
            self.clock.advance(301)
            return ProviderEvidence(binding["provider"], binding["native_session_id"],
                "finished", "synthetic:late", accepted=True, stopped=True,
                generation=binding["generation"])
        worker = CoreCommunicationWorker(self.service, late)
        result = worker.run_once("w", dispatcher_id="fake")
        self.assertEqual(result["agentDispatches"][0]["outcome"],
                         "ownership_lost_reconcile_required")
        self.assertEqual(self.service.claim("w", message["id"], owner="next")["outcome"],
                         "reconcile_required")

    def test_one_shot_worker_recovers_unstarted_lease_but_not_started_call(self):
        safe = self.send()
        old = self.claim(safe, lease_seconds=10)
        self.clock.advance(11)
        called = []
        def provider(actual, binding, claim, timeout):
            called.append(actual["id"])
            return ProviderEvidence(binding["provider"], binding["native_session_id"],
                "not_delivered", "synthetic:not-delivered", stopped=True,
                generation=binding["generation"])
        worker = CoreCommunicationWorker(self.service, provider)
        run = worker.run_once("w", dispatcher_id="next", dispatch_id=None)
        self.assertEqual(run["leaseReconciliation"]["retryable_before_start"], 1)
        self.assertEqual(called, [safe["id"]])
        with self.assertRaises(StaleAttempt):
            self.service.mark_started(old)
        started = self.send()
        claim = self.claim(started, lease_seconds=10)
        self.service.mark_started(claim)
        self.clock.advance(11)
        run = worker.run_once("w", dispatcher_id="next")
        self.assertEqual(run["leaseReconciliation"]["reconcile_required"], 1)
        self.assertNotIn(started["id"], called)

    def test_capture_needs_policy_correlated_trusted_evidence_and_preserves_explicit_reply(self):
        message = self.send()
        claim = self.claim(message)
        self.service.mark_started(claim)
        with self.assertRaises(AccessDenied):
            self.service.complete(claim, self.evidence(claim, accepted=True, stopped=True, final="No", trusted_final=True))
        wrong = replace(self.evidence(claim, stopped=True), native_session_id="wrong")
        with self.assertRaises(Conflict):
            self.service.complete(claim, wrong)
        with self.assertRaises(CommunicationError):
            self.evidence(claim, stopped=True, final="Untrusted")
        self.service.complete(claim, self.evidence(claim, accepted=True, stopped=True))
        message = self.send(capture="provider_final_capture")
        claim = self.claim(message)
        self.service.mark_started(claim)
        chosen = self.service.reply(self.b, message["id"], body="Chosen answer", key="explicit")
        result = self.service.complete(claim, self.evidence(claim, accepted=True, stopped=True, final="Execution output", trusted_final=True))
        self.assertEqual(result["attempt"]["capture_result"], "existing_reply_preserved")
        self.assertEqual(self.repo.receipts("w", message["id"]), [chosen])
        message = self.send(capture="provider_final_capture")
        claim = self.claim(message)
        self.service.mark_started(claim)
        self.service.complete(claim, self.evidence(claim, accepted=True, stopped=True, final="Captured", trusted_final=True))
        receipt = self.repo.receipts("w", message["id"])[0]
        self.assertEqual(receipt["source"], "provider_final_capture")
        self.assertEqual(receipt["attempt_id"], claim.attempt_id)

    def test_execution_without_acceptance_is_unknown_not_retryable(self):
        message = self.send()
        claim = self.claim(message)
        self.service.mark_started(claim)
        self.service.complete(claim, self.evidence(claim, stopped=True))
        self.assertEqual(self.service.status(self.a, message["id"])["delivery"]["delivery"], "unknown")
        self.assertEqual(self.service.claim("w", message["id"], owner="other")["outcome"], "not_pending")

    def test_acl_cross_workspace_recipient_and_user_origin(self):
        message = self.send(visibility="participants_only")
        for action in (lambda: self.service.get(self.c, message["id"]),
                       lambda: self.service.reply(self.a, message["id"], body="Wrong", key="wrong"),
                       lambda: self.service.get(Caller("other", "a"), message["id"]),
                       lambda: self.service.send(self.a, target_alias="b", body="Wrong", key="user", origin="user"),
                       lambda: self.service.send(self.c, target_alias="b", body="Wrong", key="thread", thread_id=message["thread_id"])):
            with self.assertRaises(AccessDenied):
                action()
        self.assertEqual(self.repo.high_water(), 1)
        public = self.send(visibility="workspace_readable")
        self.assertEqual(self.service.get(self.c, public["id"])["id"], public["id"])
        with self.assertRaises(AccessDenied):
            self.service.reply(self.c, public["id"], body="Wrong recipient", key="wrong")

    def test_real_legacy_thread_visibility_is_checked_on_import(self):
        request = self.platform.create_agent_exchange_request("w", source_agent_id="a", target_agent_id="b",
            request_kind="question", request_summary="Synthetic legacy request")
        thread_id = request["agentExchangeThread"]["exchangeThreadId"]
        message = self.send(thread_id=thread_id)
        self.assertEqual(message["thread_id"], thread_id)
        self.assertTrue(self.repo.get("threads", "w", thread_id)["legacy"])

    def test_expiry_close_and_late_final_are_evidence_not_a_successful_wait(self):
        message = self.send(expires_at=self.clock.now + timedelta(seconds=5))
        observation = self.service.observe(self.a, message["id"], condition="final", deadline=self.clock.now + timedelta(seconds=10), key="wait")
        self.clock.advance(6)
        with self.assertRaises(Conflict):
            self.service.ack(self.b, message["id"], key="late-ack")
        receipt = self.service.reply(self.b, message["id"], body="Late result", key="late-final")
        self.assertTrue(receipt["late"])
        self.clock.advance(5)
        self.assertEqual(self.service.observation_status(self.a, observation["id"])["state"], "timed_out")
        self.assertEqual(self.service.claim("w", message["id"], owner="worker")["outcome"], "closed_or_expired")
        other = self.send()
        self.service.close(self.a, other["id"], key="close")
        with self.assertRaises(Conflict):
            self.service.reply(self.b, other["id"], body="Progress", kind="progress", key="progress")
        self.assertTrue(self.service.reply(self.b, other["id"], body="After close", key="late")["late"])

    def test_waits_before_during_and_after_receipts_and_independent_cancellation(self):
        message = self.send()
        deadline = self.clock.now + timedelta(seconds=10)
        first = self.service.observe(self.a, message["id"], condition="ack", deadline=deadline, key="one")
        second = self.service.observe(self.a, message["id"], condition="final", deadline=deadline, key="two")
        third = self.service.observe(self.a, message["id"], condition="final", deadline=deadline, key="three")
        self.service.cancel_observation(self.a, third["id"], key="cancel")
        self.clock.advance(1)
        self.service.reply(self.b, message["id"], body="Done", key="final")
        for observation in (first, second):
            state = self.service.observation_status(self.a, observation["id"])
            self.assertEqual(state["state"], "satisfied")
            self.assertFalse(state["active_waiter_verified"])
        self.assertEqual(self.service.observation_status(self.a, third["id"])["state"], "cancelled")
        after = self.service.observe(self.a, message["id"], condition="ack", deadline=deadline, key="after")
        self.assertEqual(self.service.observation_status(self.a, after["id"])["state"], "satisfied")
        self.assertFalse(self.service.status(self.a, message["id"])["acknowledged"])

    def test_wait_timeout_does_not_cancel_message_and_late_result_survives_reopen(self):
        message = self.send()
        obs = self.service.observe(self.a, message["id"], condition="final", deadline=self.clock.now + timedelta(seconds=2), key="wait")
        self.clock.advance(3)
        self.assertEqual(self.service.observation_status(self.a, obs["id"])["state"], "timed_out")
        claim = self.claim(message, lease_seconds=10, provider_timeout_seconds=30)
        self.service.mark_started(claim)
        self.service.reply(self.b, message["id"], body="Later", key="later")
        connection = sqlite3.connect(self.path)
        self.addCleanup(connection.close)
        service = CommunicationService(SqliteCommunicationRepository(connection), PlatformCommunicationDirectory(connection), clock=self.clock)
        self.assertEqual(service.observation_status(self.a, obs["id"])["state"], "timed_out")
        self.assertEqual(service.inbox(self.a, include_bodies=True)["items"][0]["body"], "Later")
        attempt = self.repo.get("attempts", "w", claim.attempt_id)
        slot = self.repo.get("slots", "w", claim.session_key)
        self.assertNotEqual(attempt["provider_deadline"], slot["lease_until"])
        self.assertIsNone(self.service.status(self.a, message["id"])["delivery"]["closed_at"])

    def test_cursor_pages_new_receipts_and_is_bound_to_database_workspace_and_viewer(self):
        messages = [self.send() for _ in range(3)]
        first = self.service.inbox(self.b, limit=1)
        self.assertTrue(first["has_more"])
        fourth = self.send()
        second = self.service.inbox(self.b, cursor=first["cursor"], limit=1)
        third = self.service.inbox(self.b, cursor=second["cursor"], limit=1)
        self.assertFalse(third["has_more"])
        next_page = self.service.inbox(self.b, cursor=third["cursor"])
        self.assertEqual(next_page["items"][0]["message_id"], fourth["id"])
        self.assertEqual(self.service.inbox(self.b, cursor=first["cursor"], limit=1), second)
        self.assertNotIn("body", first["items"][0])
        empty = self.service.inbox(self.a)
        self.service.ack(self.b, messages[0]["id"], key="ack")
        later = self.service.inbox(self.a, cursor=empty["cursor"])
        self.assertEqual(later["items"][0]["kind"], "ack")
        self.service.reply(self.b, messages[0]["id"], body="Done", key="final")
        self.assertEqual(self.service.inbox(self.a, cursor=later["cursor"])["items"][0]["kind"], "final")
        reopened = sqlite3.connect(self.path)
        self.addCleanup(reopened.close)
        resumed = CommunicationService(SqliteCommunicationRepository(reopened), PlatformCommunicationDirectory(reopened), clock=self.clock)
        self.assertEqual(resumed.inbox(self.a, cursor=later["cursor"]), self.service.inbox(self.a, cursor=later["cursor"]))
        with self.assertRaises(CommunicationError):
            self.service.inbox(self.c, cursor=first["cursor"])
        with self.assertRaises(CommunicationError):
            self.service.inbox(self.b, cursor="malformed")

    def test_projection_rebuild_including_claims_receipts_observations_and_idempotency(self):
        message = self.send(key="stable")
        claim = self.claim(message)
        self.service.mark_started(claim)
        self.service.ack(self.b, message["id"], key="ack")
        self.service.observe(self.a, message["id"], condition="final", deadline=self.clock.now + timedelta(seconds=5), key="wait")
        self.service.reply(self.b, message["id"], body="Done", key="final")
        self.service.complete(claim, self.evidence(claim, accepted=True, stopped=True))
        snapshot = self.repo.projection_snapshot()
        self.repo.rebuild()
        self.assertEqual(self.repo.projection_snapshot(), snapshot)
        self.assertEqual(self.send(key="stable"), message)
        self.assertEqual(self.connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_repository_rejects_accidental_nested_and_unowned_transactions(self):
        self.connection.execute("BEGIN")
        with self.assertRaises(CommunicationError):
            self.repo.initialize()
        with self.assertRaises(CommunicationError):
            self.repo.append("w", "a", "wrong", "now", {})
        with self.assertRaises(CommunicationError):
            self.send()
        self.assertTrue(self.connection.in_transaction)
        self.connection.rollback()

    def test_cancel_then_final_at_same_timestamp_respects_event_order(self):
        message = self.send()
        obs = self.service.observe(self.a, message["id"], condition="final", deadline=self.clock.now + timedelta(seconds=10), key="wait")
        self.service.cancel_observation(self.a, obs["id"], key="cancel")
        self.service.reply(self.b, message["id"], body="Done at same clock tick", key="final")
        self.assertEqual(self.service.observation_status(self.a, obs["id"])["state"], "cancelled")

    def test_receipt_exactly_at_deadline_cannot_revive_timed_out_observation(self):
        message = self.send()
        obs = self.service.observe(self.a, message["id"], condition="final", deadline=self.clock.now + timedelta(seconds=1), key="wait")
        self.clock.advance(1)
        self.assertEqual(self.service.observation_status(self.a, obs["id"])["state"], "timed_out")
        self.service.reply(self.b, message["id"], body="At deadline", key="final")
        self.assertEqual(self.service.observation_status(self.a, obs["id"])["state"], "timed_out")

    def test_mark_started_is_not_provider_acceptance_and_retry_limit_is_durable(self):
        message = self.send(max_attempts=1)
        claim = self.claim(message)
        self.service.mark_started(claim)
        state = self.service.status(self.a, message["id"])
        self.assertEqual(state["delivery"]["delivery"], "stored")
        self.assertEqual(state["delivery"]["execution"], "unknown")
        self.service.complete(claim, self.evidence(claim, outcome="not_delivered", stopped=True))
        self.assertEqual(self.service.claim("w", message["id"], owner="again")["outcome"], "attempt_limit")
        self.assertEqual(self.service.status(self.a, message["id"])["delivery"]["schedule"], "failed")

    def test_same_native_session_across_different_handles_and_agents_is_serialized(self):
        native = self.directory.resolve("w", "b").native_session_id
        self.platform.register_codex_session_handle("w", agent_id="d", handle_id="handle-d",
            codex_session_id=native, cwd=self.temp.name, created_by="fixture", reason="explicit shared-session fixture")
        self.platform.login_agent_endpoint("w", agent_id="d", alias="d", provider="codex", provider_handle_id="handle-d")
        messages = [self.send(), self.send(target="d")]
        outcomes = self.parallel(lambda s, i: s.claim("w", messages[i]["id"], owner=f"worker-{i}"))
        self.assertCountEqual([r["outcome"] for r in outcomes], ["claimed", "busy"])

    def test_running_evidence_is_not_final_and_acceptance_cannot_be_retracted(self):
        message = self.send()
        claim = self.claim(message)
        self.service.mark_started(claim)
        self.service.complete(claim, self.evidence(claim, outcome="running", accepted=True))
        state = self.service.status(self.a, message["id"])
        self.assertEqual(state["delivery"]["execution"], "running")
        self.assertEqual(state["reply"], "none")
        with self.assertRaises(Conflict):
            self.service.complete(claim, self.evidence(claim, outcome="not_delivered", stopped=True))
        self.service.complete(claim, self.evidence(claim, outcome="failed", stopped=True))
        self.assertEqual(self.service.status(self.a, message["id"])["delivery"]["delivery"], "accepted")

    def test_message_expiry_during_execution_retains_late_captured_result(self):
        message = self.send(expires_at=self.clock.now + timedelta(seconds=2), capture="provider_final_capture")
        claim = self.claim(message, lease_seconds=20)
        self.service.mark_started(claim)
        self.clock.advance(3)
        self.service.complete(claim, self.evidence(claim, accepted=True, stopped=True, trusted_final=True, final="Late capture"))
        state = self.service.status(self.a, message["id"])
        self.assertEqual(state["delivery"]["execution"], "finished")
        self.assertTrue(state["receipts"][0]["late"])
        self.assertEqual(state["reply"], "none")

    def test_contact_policy_and_binding_changes_are_enforced(self):
        self.platform.login_agent_endpoint("w", agent_id="b", alias="blocked", provider="codex",
            provider_handle_id="handle-b", contact_policy="block_all")
        with self.assertRaises(AccessDenied):
            self.send(target="blocked")
        message = self.send()
        original = self.directory.resolve
        self.directory.resolve = lambda w, a: replace(original(w, a), handle_id="changed-handle")
        with self.assertRaises(Conflict):
            self.claim(message)
        self.directory.resolve = lambda w, a: replace(original(w, a), automatic_activation_allowed=False)
        manual = self.send()
        with self.assertRaises(AccessDenied):
            self.claim(manual)

    def test_inbox_is_read_only_indexed_and_hides_other_recipients(self):
        message = self.send()
        self.send(target="c")
        before = self.repo.projection_snapshot()
        statements = []
        self.connection.set_trace_callback(statements.append)
        result = self.service.inbox(self.b, include_bodies=True)
        self.connection.set_trace_callback(None)
        self.assertEqual([i["message_id"] for i in result["items"]], [message["id"]])
        self.assertEqual(self.repo.projection_snapshot(), before)
        self.assertFalse(any("payload_json FROM communication_events" in s for s in statements))
        plan = self.connection.execute(
            "EXPLAIN QUERY PLAN SELECT sequence FROM communication_inbox WHERE workspace_id=? AND viewer=? AND sequence>? AND sequence<=? ORDER BY sequence LIMIT ?",
            ("w", "b", 0, 100, 20),
        ).fetchall()
        self.assertTrue(any("communication_inbox_cursor" in r[-1] for r in plan), plan)

    def test_schema_version_and_foreign_database_cursor_are_rejected(self):
        cursor = self.service.inbox(self.b)["cursor"]
        other = sqlite3.connect(":memory:")
        self.addCleanup(other.close)
        SqlitePlatformPersistence(other).initialize()
        repo = SqliteCommunicationRepository(other)
        repo.initialize()
        # Directory remains the synthetic fixture; cursor validation must also
        # check the DB identity rather than only caller identity.
        service = CommunicationService(repo, self.directory, clock=self.clock)
        with self.assertRaises(CommunicationError):
            service.inbox(self.b, cursor=cursor)
        other.execute("UPDATE communication_schema SET version=99")
        other.commit()
        with self.assertRaises(CommunicationError):
            SqliteCommunicationRepository(other)

    def test_imported_legacy_private_thread_never_creates_an_unreadable_delivery(self):
        request = self.platform.create_agent_exchange_request("w", source_agent_id="a", target_agent_id="b",
            request_kind="question", request_summary="Synthetic private legacy request")
        thread = request["agentExchangeThread"]["exchangeThreadId"]
        imported = self.send(thread_id=thread)
        self.assertEqual(self.service.get(self.c, imported["id"])["id"], imported["id"])
        self.platform.update_agent_exchange_thread_visibility("w", thread_id=thread, updated_by_agent_id="a", visibility="participants_only")
        with self.assertRaises(AccessDenied):
            self.service.get(self.c, imported["id"])
        with self.assertRaises(AccessDenied):
            self.send(target="c", thread_id=thread)
        with self.assertRaises(AccessDenied):
            self.service.send(self.c, target_alias="b", body="No access", key="private", thread_id=thread)
        self.assertEqual(self.repo.high_water(), 1)

    def test_existing_workspace_authorization_is_not_bypassed(self):
        for mode in ("disabled", "delegated_grant_required"):
            self.platform.update_agent_exchange_request_policy("w", authorization_mode=mode)
            with self.assertRaises(AccessDenied):
                self.send()
        self.assertEqual(self.repo.high_water(), 0)

    def test_inbox_cannot_advance_over_uncommitted_projection(self):
        reader = sqlite3.connect(self.path)
        self.addCleanup(reader.close)
        observer = CommunicationService(SqliteCommunicationRepository(reader), PlatformCommunicationDirectory(reader), clock=self.clock)
        reads = []
        def observe_uncommitted(stage):
            if stage in {"after_event", "after_projection"}:
                reads.append(observer.inbox(self.b))
        self.repo.fault = observe_uncommitted
        message = self.send()
        self.repo.fault = lambda _: None
        self.assertEqual(len(reads), 2)
        for observed in reads:
            self.assertEqual(observed["items"], [])
            self.assertEqual(observed["upper"], 0)
            resumed = observer.inbox(self.b, cursor=observed["cursor"])
            self.assertEqual(resumed["items"][0]["message_id"], message["id"])

    def test_idempotency_scopes_separate_agents_and_operations(self):
        message = self.send(key="shared-key")
        other = self.service.send(self.c, target_alias="b", body="Different sender", key="shared-key")
        self.assertNotEqual(message["id"], other["id"])
        self.service.ack(self.b, message["id"], key="shared-key")
        self.service.close(self.a, message["id"], key="shared-key")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_idempotency").fetchone()[0], 4)

    def test_failed_rebuild_rolls_back_existing_views_and_keeps_ledger(self):
        message = self.send()
        self.service.ack(self.b, message["id"], key="ack")
        before = self.repo.projection_snapshot()
        high = self.repo.high_water()
        self.repo.fault = lambda s: (_ for _ in ()).throw(RuntimeError("rebuild fault")) if s == "after_messages" else None
        with self.assertRaises(RuntimeError):
            self.repo.rebuild()
        self.repo.fault = lambda _: None
        self.assertEqual(self.repo.projection_snapshot(), before)
        self.assertEqual(self.repo.high_water(), high)

    def test_sql_constraints_reject_cross_workspace_receipt(self):
        message = self.send()
        receipt = {"workspace_id": "other", "id": "bad-receipt", "message_id": message["id"],
                   "target": "b", "kind": "final"}
        with self.assertRaises(sqlite3.IntegrityError):
            with self.repo.transaction():
                self.repo.append("other", "b", "invalid", "synthetic", {"receipts": [receipt]})
        self.assertEqual(self.repo.high_water(), 1)

    def test_managed_runtime_generation_is_part_of_evidence_correlation(self):
        original = self.directory.resolve
        self.directory.resolve = lambda w, a: replace(original(w, a), provider="deepseek_harness", generation="synthetic-generation-1")
        message = self.send(capture="provider_final_capture")
        claim = self.claim(message)
        self.service.mark_started(claim)
        evidence = self.evidence(claim, accepted=True, stopped=True, trusted_final=True, final="Owned root final")
        with self.assertRaises(Conflict):
            self.service.complete(claim, replace(evidence, generation="synthetic-generation-2"))
        self.assertEqual(self.service.status(self.a, message["id"])["reply"], "none")
        self.service.complete(claim, evidence)
        self.assertEqual(self.service.status(self.a, message["id"])["reply"], "final")

    def test_inbox_routes_receipts_from_recipient_back_to_sender(self):
        message = self.send()
        received = self.service.inbox(self.b)["items"][0]
        self.assertEqual((received["from"], received["to"]), ("a", "b"))
        self.service.ack(self.b, message["id"], key="ack")
        self.service.reply(self.b, message["id"], body="Done", key="final")
        replies = self.service.inbox(self.a, include_bodies=True)["items"]
        self.assertEqual([(r["from"], r["to"]) for r in replies], [("b", "a"), ("b", "a")])
        self.assertEqual([r["body"] for r in replies], ["", "Done"])
        self.assertTrue(all(r["message_id"] == message["id"] for r in replies))
        self.service.close(self.a, message["id"], key="close")
        notice = self.service.inbox(self.b)["items"][-1]
        self.assertEqual((notice["kind"], notice["from"], notice["to"]), ("closed", "a", "b"))

    def test_non_delivery_recovery_does_not_requeue_ineligible_messages(self):
        for transition in ("release", "expire_lease", "not_delivered"):
            for ending, expected in (("close", "cancelled"), ("final", "done"), ("expiry", "expired")):
                with self.subTest(transition=transition, ending=ending):
                    message = self.send(expires_at=self.clock.now + timedelta(seconds=2) if ending == "expiry" else None)
                    claim = self.claim(message, lease_seconds=5)
                    if transition == "not_delivered":
                        self.service.mark_started(claim)
                    if ending == "close":
                        self.service.close(self.a, message["id"], key=str(uuid4()))
                    elif ending == "final":
                        self.service.reply(self.b, message["id"], body="Done", key=str(uuid4()))
                    else:
                        self.clock.advance(3)
                    if transition == "release":
                        self.service.release(claim)
                    elif transition == "not_delivered":
                        self.service.complete(claim, self.evidence(claim, outcome="not_delivered", stopped=True))
                    else:
                        self.clock.advance(6)
                        # A different queued message discovers and retires the old lease.
                        successor = self.send()
                        next_claim = self.claim(successor)
                        self.service.close(self.a, successor["id"], key=str(uuid4()))
                        self.service.release(next_claim)
                    self.assertEqual(self.service.status(self.a, message["id"])["delivery"]["schedule"], expected)
                    self.assertEqual(self.repo.get("slots", "w", claim.session_key)["state"], "free")

    def test_activation_revalidates_permissions_and_binding_before_io(self):
        message = self.send()
        claim = self.claim(message)
        before = self.repo.high_water()
        original = self.directory.resolve
        self.directory.resolve = lambda w, a: replace(original(w, a), handle_id="new-binding")
        with self.assertRaises(Conflict):
            self.service.mark_started(claim)
        self.directory.resolve = original
        self.platform.update_agent_exchange_request_policy("w", authorization_mode="disabled")
        with self.assertRaises(AccessDenied):
            self.service.mark_started(claim)
        self.assertEqual(self.repo.high_water(), before)
        self.assertEqual(self.repo.get("attempts", "w", claim.attempt_id)["phase"], "claimed")
        self.service.release(claim)
        with self.assertRaises(AccessDenied):
            self.claim(message)

    def test_idempotent_retry_rechecks_current_thread_visibility(self):
        request = self.platform.create_agent_exchange_request("w", source_agent_id="a", target_agent_id="b",
            request_kind="question", request_summary="Synthetic legacy thread")
        thread = request["agentExchangeThread"]["exchangeThreadId"]
        kwargs = dict(target_alias="b", body="Visible at send time", key="retry", thread_id=thread)
        message = self.service.send(self.c, **kwargs)
        self.assertEqual(self.service.send(self.c, **kwargs), message)
        self.platform.update_agent_exchange_thread_visibility("w", thread_id=thread, updated_by_agent_id="a", visibility="participants_only")
        before = self.repo.high_water()
        with self.assertRaises(AccessDenied):
            self.service.send(self.c, **kwargs)
        self.assertEqual(self.repo.high_water(), before)

    def test_ack_before_during_and_after_observation_deadline(self):
        for phase in ("before", "during", "after"):
            with self.subTest(phase=phase):
                message = self.send(expectation="ack")
                if phase == "before":
                    self.service.ack(self.b, message["id"], key=str(uuid4()))
                observation = self.service.observe(self.a, message["id"], condition="ack",
                    deadline=self.clock.now + timedelta(seconds=2), key=str(uuid4()))
                if phase != "before":
                    self.clock.advance(1 if phase == "during" else 3)
                    if phase == "after":
                        self.assertEqual(self.service.observation_status(self.a, observation["id"])["state"], "timed_out")
                    self.service.ack(self.b, message["id"], key=str(uuid4()))
                state = self.service.observation_status(self.a, observation["id"])
                self.assertEqual(state["state"], "timed_out" if phase == "after" else "satisfied")
                self.assertFalse(state["active_waiter_verified"])
                status = self.service.status(self.a, message["id"])
                self.assertTrue(status["acknowledged"])
                self.assertEqual(status["reply"], "none")
                self.assertEqual(status["delivery"]["schedule"], "pending")

    def test_failed_execution_may_preserve_trusted_final_for_review(self):
        message = self.send(capture="provider_final_capture")
        claim = self.claim(message)
        self.service.mark_started(claim)
        with self.assertRaises(CommunicationError):
            self.evidence(claim, outcome="failed", accepted=True, stopped=True,
                          trusted_final=True, final="Partial answer")
        failed = self.evidence(claim, outcome="failed", accepted=True, stopped=True,
                               trusted_final=True, final="Partial answer", requires_user_review=True)
        result = self.service.complete(claim, failed)
        self.assertEqual(result["delivery"]["execution"], "failed")
        status = self.service.status(self.a, message["id"])
        self.assertEqual(status["reply"], "final")
        self.assertTrue(status["receipts"][0]["requires_user_review"])
        self.assertEqual(status["receipts"][0]["source"], "provider_final_capture")
        self.assertEqual(self.service.claim("w", message["id"], owner="another")["outcome"], "already_replied")

    def test_live_owner_can_renew_lease_but_expired_owner_cannot(self):
        message = self.send()
        claim = self.claim(message, lease_seconds=5)
        self.service.mark_started(claim)
        self.clock.advance(4)
        renewed = self.service.renew_lease(claim, lease_seconds=5)
        self.assertEqual(renewed["claim"], claim.to_dict())
        self.clock.advance(2)
        self.service.complete(claim, self.evidence(claim, accepted=True, stopped=True))
        self.assertEqual(self.service.status(self.a, message["id"])["delivery"]["execution"], "finished")
        with self.assertRaises(StaleAttempt):
            self.service.renew_lease(claim, lease_seconds=5)
        other = self.send()
        stale = self.claim(other, lease_seconds=5)
        self.clock.advance(6)
        with self.assertRaises(StaleAttempt):
            self.service.renew_lease(stale, lease_seconds=5)
        self.assertEqual(self.service.claim("w", other["id"], owner="new")["outcome"], "claimed")


    def test_due_query_and_claim_respect_deferred_delivery(self):
        message = self.send()
        delivery = self.repo.get("deliveries", "w", delivery_identity(message["id"], "b"))
        delivery["eligible_after"] = (self.clock.now + timedelta(seconds=30)).isoformat()
        with self.repo.transaction():
            self.repo.append("w", "fixture", "defer_for_test", self.clock.now.isoformat(),
                             {"deliveries": [delivery]})
        self.assertEqual(self.repo.due("w", self.clock.now.isoformat(), limit=10), [])
        self.assertEqual(self.service.claim("w", message["id"], owner="fake")["outcome"], "not_due")
        self.clock.advance(31)
        self.assertEqual(len(self.repo.due("w", self.clock.now.isoformat(), limit=10)), 1)
        self.assertEqual(self.service.claim("w", message["id"], owner="fake")["outcome"], "claimed")

    def test_explicit_source_route_is_fenced_again_at_claim(self):
        self.platform.register_codex_session_handle("w", agent_id="a", handle_id="handle-a",
            codex_session_id=str(uuid4()), cwd=self.temp.name, created_by="fixture", reason="route")
        self.platform.login_agent_endpoint("w", agent_id="a", alias="a-send", provider="codex",
                                           provider_handle_id="handle-a")
        with self.assertRaises(AccessDenied):
            self.send(source_alias="b", reply_policy="source_handle_required")
        with self.assertRaises(AccessDenied):
            self.send(source_alias="a-send", source_handle_id="wrong",
                      reply_policy="source_handle_required")
        message = self.send(source_alias="a-send", source_handle_id="handle-a",
                            target_handle_id="handle-b", reply_policy="source_handle_required")
        self.assertEqual(self.repo.get("deliveries", "w", delivery_identity(message["id"], "b"))
                         ["routing"]["source_alias"], "a-send")
        self.platform.deactivate_agent_endpoint("w", alias="a-send", deactivated_by="fixture", reason="route changed")
        with self.assertRaises(AccessDenied):
            self.service.claim("w", message["id"], owner="worker")

    def test_delegated_grant_reference_is_validated_but_not_consumed_by_send(self):
        grant = self.platform.create_delegated_wake_grant("w", source_agent_id="a",
            target_agent_id="b", created_by="fixture-user", reason="bounded handoff",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1))
        grant_id = grant["delegatedWakeGrant"]["delegatedWakeGrantId"]
        self.platform.update_agent_exchange_request_policy("w",
            authorization_mode="delegated_grant_required")
        with self.assertRaises(AccessDenied):
            self.send(reply_policy="message_only")
        with self.assertRaises(AccessDenied):
            self.send(reply_policy="message_only", linked_delegated_wake_grant_id="missing")
        message = self.send(reply_policy="message_only", linked_delegated_wake_grant_id=grant_id)
        self.assertEqual(self.platform.get_delegated_wake_grant_status("w",
            delegated_wake_grant_id=grant_id)["delegatedWakeGrant"]["state"], "pending")
        self.platform.consume_delegated_wake_grant("w", delegated_wake_grant_id=grant_id,
                                                   consuming_agent_id="a")
        self.assertEqual(self.service.claim("w", message["id"], owner="worker")["outcome"], "claimed")


if __name__ == "__main__":
    unittest.main()
