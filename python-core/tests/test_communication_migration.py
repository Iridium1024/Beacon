"""Explicit cutover tests use only temporary SQLite and synthetic legacy events."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import unittest
from uuid import uuid4

from agent_os.application.services.local_platform_application import LocalPlatformApplication
from agent_os.application.services.communication_core import CommunicationService
from agent_os.application.services.communication_migration import CommunicationMigration
from agent_os.domain.entities.communication import AccessDenied, Caller, CommunicationError, Conflict
from agent_os.infrastructure.composition.local_platform import build_communication_directory as PlatformCommunicationDirectory
from agent_os.infrastructure.composition.local_platform import build_local_platform_operation_service
from agent_os.infrastructure.composition.local_platform import LocalPlatformRuntimeComponents
from agent_os.infrastructure.persistence.communication_store import SqliteCommunicationRepository
from agent_os.infrastructure.persistence.sqlite_persistence import SqlitePlatformPersistence
from agent_os.infrastructure.persistence.event_log import (
    PlatformEventKind, PlatformEventRecord, SqlitePlatformEventLog,
)
from agent_os.domain.value_objects.identifiers import WorkspaceId


class CommunicationMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "migration.sqlite3"
        self.connection = sqlite3.connect(self.path)
        self.addCleanup(self.connection.close)
        SqlitePlatformPersistence(self.connection).initialize()
        self.platform = build_local_platform_operation_service(self.connection)
        self.platform.create_workspace(workspace_id="w", display_name="Synthetic", root_path=self.temp.name,
                                       agent_id="a", agent_name="A", agent_description="fixture")
        for agent in ("b", "c"):
            self.platform.create_agent_registration("w", agent_id=agent, name=agent, description="fixture")
        self.platform.register_codex_session_handle("w", agent_id="b", handle_id="h-b",
            codex_session_id=str(uuid4()), cwd=self.temp.name, created_by="fixture", reason="fixture")
        self.platform.login_agent_endpoint("w", agent_id="b", alias="b", provider="codex", provider_handle_id="h-b")
        self.repo = SqliteCommunicationRepository(self.connection)
        self.directory = PlatformCommunicationDirectory(self.connection)
        self.migration = CommunicationMigration(self.connection, directory=self.directory, repository=self.repo)

    def request(self, *, request_id=None):
        result = self.platform.create_agent_exchange_request("w", source_agent_id="a", target_agent_id="b",
            request_kind="question", request_summary="Synthetic legacy message", exchange_request_id=request_id)
        return result["agentExchangeRequest"]

    def test_preview_does_not_initialize_or_mutate_and_import_is_idempotent(self):
        request = self.request()
        legacy_count = self.connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0]
        self.assertEqual(self.migration.preview("w")["engine"], "legacy")
        self.assertFalse(self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='communication_schema'"
        ).fetchone())
        with self.assertRaises(CommunicationError):
            self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=False)
        self.platform.respond_agent_exchange_request("w", exchange_request_id=request["exchangeRequestId"],
            responding_agent_id="b", response_summary="Synthetic answer")
        before = self.connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0]
        result = self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)
        self.assertTrue(result["created"])
        self.assertEqual(self.repo.mode("w"), "core")
        self.assertEqual(self.migration.preview("w")["blockers"], [])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0], before)
        self.assertGreater(before, legacy_count)
        new_id = self.migration.legacy_message_id("w", kind="request", legacy_id=request["exchangeRequestId"])
        service = CommunicationService(self.repo, self.directory)
        self.assertEqual(service.status(Caller("w", "a"), new_id)["reply"], "final")
        self.assertEqual(service.inbox(Caller("w", "b"))["items"][0]["message_id"], new_id)
        snapshot = self.repo.projection_snapshot()
        self.repo.rebuild()
        self.assertEqual(self.repo.projection_snapshot(), snapshot)
        self.assertFalse(self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)["created"])
        self.assertEqual(self.repo.high_water(), 1)

    def test_composition_selector_is_read_only_and_requires_cutover_marker(self):
        components = LocalPlatformRuntimeComponents(
            settings=None, connection=self.connection, agent_invocation_adapter=None,
            agent_invocation_adapter_factory=None, runtime_handler=None)
        self.assertEqual(components.communication_mode("w"), "legacy")
        self.assertIsNone(components.communication("w"))
        self.assertFalse(self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='communication_schema'").fetchone())
        self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)
        self.assertEqual(components.communication_mode("w"), "core")
        self.assertIsInstance(components.communication("w"), CommunicationService)

    def test_cutover_fault_rolls_back_marker_history_and_mappings(self):
        self.request()
        for stage in ("after_messages", "after_mappings", "after_modes", "before_commit"):
            with self.subTest(stage=stage):
                self.repo.fault = lambda actual, wanted=stage: (_ for _ in ()).throw(RuntimeError("fault")) if actual == wanted else None
                with self.assertRaisesRegex(RuntimeError, "fault"):
                    self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)
                self.repo.fault = lambda _: None
                self.assertEqual(self.repo.mode("w"), "legacy")
                self.assertEqual(self.repo.high_water(), 0)
                self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0], 0)
                self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_mappings").fetchone()[0], 0)
        self.assertTrue(self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)["created"])

    def test_closed_private_thread_and_missing_historical_binding_remain_readable(self):
        request = self.request()
        thread = request["threadId"]
        self.platform.update_agent_exchange_thread_visibility("w", thread_id=thread,
            updated_by_agent_id="a", visibility="participants_only")
        self.platform.close_agent_exchange_thread("w", thread_id=thread, closed_by_agent_id="a")
        self.platform.deactivate_agent_endpoint("w", alias="b", deactivated_by="fixture", reason="migration test")
        self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)
        new_id = self.migration.legacy_message_id("w", kind="request", legacy_id=request["exchangeRequestId"])
        service = CommunicationService(self.repo, self.directory)
        self.assertEqual(service.get(Caller("w", "a"), new_id)["body"], "Synthetic legacy message")
        self.assertEqual(service.get(Caller("w", "b"), new_id)["body"], "Synthetic legacy message")
        with self.assertRaises(AccessDenied):
            service.get(Caller("w", "c"), new_id)
        self.assertIsNone(service.status(Caller("w", "a"), new_id)["delivery"]["binding"])
        self.assertEqual(service.claim("w", new_id, owner="worker")["outcome"], "not_pending")
        with self.assertRaises(AccessDenied):
            service.send(Caller("w", "a"), target_alias="b", body="New", key="new", thread_id=thread)

    def test_blocked_and_expired_historical_requests_keep_terminal_reason_without_tasks(self):
        ids = {}
        for reason in ("blocked", "expired"):
            created = self.platform.create_agent_dispatch("w", source_agent_id="a",
                target_agent_id="b", request_kind="question",
                request_summary=f"Synthetic {reason} history", target_handle_id="h-b",
                target_provider="codex", reply_policy="message_only",
                metadata={"replyWritebackMode": "explicit_only"})
            request_id = created["agentExchangeRequest"]["exchangeRequestId"]
            self.platform.close_agent_exchange_request("w", exchange_request_id=request_id,
                                                       terminal_reason=reason)
            ids[reason] = request_id
        self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)
        service = CommunicationService(self.repo, self.directory)
        for reason, request_id in ids.items():
            with self.subTest(reason=reason):
                identity = self.migration.legacy_message_id("w", kind="request",
                                                            legacy_id=request_id)
                state = service.status(Caller("w", "a"), identity)
                self.assertEqual(state["message"]["legacy_terminal_reason"], reason)
                self.assertEqual(state["delivery"]["schedule"], "none")
                self.assertIsNotNone(state["delivery"]["closed_at"])
                self.assertEqual(service.claim("w", identity, owner="fake")["outcome"],
                                 "not_pending")

    def test_proven_queued_dispatch_resumes_only_with_exact_binding_and_policy(self):
        result = self.platform.create_agent_dispatch("w", source_agent_id="a", target_agent_id="b",
            request_kind="question", request_summary="Synthetic queued", target_handle_id="h-b",
            target_provider="codex", reply_policy="message_only",
            metadata={"replyWritebackMode": "explicit_only"})
        request_id = result["agentExchangeRequest"]["exchangeRequestId"]
        self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)
        new_id = self.migration.legacy_message_id("w", kind="request", legacy_id=request_id)
        state = CommunicationService(self.repo, self.directory).status(Caller("w", "a"), new_id)
        self.assertEqual(state["delivery"]["schedule"], "pending")
        self.assertEqual(state["delivery"]["legacy_dispatch_status"], "queued")
        self.assertEqual(CommunicationService(self.repo, self.directory).claim("w", new_id, owner="fake")["outcome"], "claimed")
        self.assertEqual(len(self.repo.mappings_for_legacy("w", "dispatch", result["agentDispatch"]["dispatchId"])), 1)

    def test_ambiguous_queued_policy_and_multiple_dispatches_fail_closed(self):
        result = self.platform.create_agent_dispatch("w", source_agent_id="a", target_agent_id="b",
            request_kind="question", request_summary="Synthetic queued", target_handle_id="h-b", target_provider="codex")
        request_id = result["agentExchangeRequest"]["exchangeRequestId"]
        self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)
        new_id = self.migration.legacy_message_id("w", kind="request", legacy_id=request_id)
        state = CommunicationService(self.repo, self.directory).status(Caller("w", "a"), new_id)
        self.assertEqual(state["delivery"]["schedule"], "unknown")
        self.assertIsNone(state["delivery"]["binding"])
        self.assertEqual(CommunicationService(self.repo, self.directory).claim("w", new_id, owner="fake")["outcome"], "not_pending")

    def test_waiting_response_history_is_imported_unknown_not_replayed(self):
        result = self.platform.create_agent_dispatch("w", source_agent_id="a",
            target_agent_id="b", request_kind="question", request_summary="Previously sent",
            target_handle_id="h-b", target_provider="codex", reply_policy="message_only",
            metadata={"replyWritebackMode": "explicit_only"})
        dispatch_id = result["agentDispatch"]["dispatchId"]
        old = self.connection.execute("SELECT event_kind,occurred_at,payload_json "
            "FROM platform_events WHERE workspace_id='w' AND aggregate_type='agent_dispatch' "
            "AND aggregate_id=? ORDER BY sequence DESC LIMIT 1", (dispatch_id,)).fetchone()
        payload = json.loads(old[2])
        payload["dispatch"].update(status="waiting_response", attemptCount=1,
                                   providerActivationExecuted=True,
                                   providerRuntimeState="unknown")
        self.connection.execute("INSERT INTO platform_events(event_id,workspace_id,event_kind,"
            "aggregate_type,aggregate_id,occurred_at,payload_json,metadata_json) "
            "VALUES(?,?,?,?,?,?,?,?)", (str(uuid4()), "w", old[0], "agent_dispatch",
                dispatch_id, old[1], json.dumps(payload), "{}"))
        self.connection.commit()
        self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)
        identity = self.migration.legacy_message_id("w", kind="request",
            legacy_id=result["agentExchangeRequest"]["exchangeRequestId"])
        service = CommunicationService(self.repo, self.directory)
        state = service.status(Caller("w", "a"), identity)
        self.assertEqual(state["delivery"]["schedule"], "unknown")
        self.assertTrue(state["delivery"]["legacy_provider_activation_executed"])
        self.assertEqual(service.claim("w", identity, owner="fake")["outcome"],
                         "not_pending")

    def test_unreconciled_legacy_dispatch_lease_blocks_cutover(self):
        result = self.platform.create_agent_dispatch("w", source_agent_id="a", target_agent_id="b",
            request_kind="question", request_summary="In flight", target_handle_id="h-b",
            target_provider="codex", reply_policy="message_only")
        dispatch_id = result["agentDispatch"]["dispatchId"]
        self.platform.acquire_agent_dispatch_lease("w", dispatch_id=dispatch_id,
            acquired_by="synthetic-worker", lease_ttl_seconds=300)
        preview = self.migration.preview("w")
        self.assertIn({"reason": "unreconciled_dispatch_lease", "ids": [dispatch_id]}, preview["blockers"])
        with self.assertRaises(Conflict):
            self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)
        self.assertEqual(self.repo.mode("w"), "legacy")

    def test_reused_legacy_request_id_blocks_switch_with_specific_report(self):
        first = self.request(request_id="reused")
        self.platform.respond_agent_exchange_request("w", exchange_request_id=first["exchangeRequestId"],
            responding_agent_id="b", response_summary="First")
        self.request(request_id="reused")
        preview = self.migration.preview("w")
        self.assertEqual(preview["blockers"][0]["reason"], "reused_request_id")
        with self.assertRaises(Conflict):
            self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)
        self.assertEqual(self.repo.mode("w"), "legacy")

    def test_multiple_dispatches_for_one_request_block_cutover(self):
        self.platform.create_agent_dispatch("w", source_agent_id="a", target_agent_id="b",
            request_kind="question", request_summary="Synthetic", target_handle_id="h-b",
            target_provider="codex", reply_policy="message_only")
        old = self.connection.execute(
            "SELECT event_kind,occurred_at,payload_json FROM platform_events "
            "WHERE workspace_id='w' AND aggregate_type='agent_dispatch' LIMIT 1").fetchone()
        payload = json.loads(old[2])
        payload["dispatch"]["dispatchId"] = "second-synthetic-dispatch"
        self.connection.execute(
            "INSERT INTO platform_events(event_id,workspace_id,event_kind,aggregate_type,aggregate_id,"
            "occurred_at,payload_json,metadata_json) VALUES(?,?,?,?,?,?,?,?)",
            (str(uuid4()), "w", old[0], "agent_dispatch", "second-synthetic-dispatch",
             old[1], json.dumps(payload), "{}"))
        self.connection.commit()
        reasons = [item["reason"] for item in self.migration.preview("w")["blockers"]]
        self.assertIn("multiple_dispatches_for_request", reasons)
        with self.assertRaises(Conflict):
            self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)

    def test_legacy_writer_after_cutover_is_reported_not_ignored(self):
        self.request()
        self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)
        with self.assertRaisesRegex(ValueError, "fenced"):
            self.request()
        old = self.connection.execute(
            "SELECT event_kind,aggregate_id,occurred_at,payload_json FROM platform_events "
            "WHERE workspace_id='w' AND aggregate_type='agent_exchange_request' LIMIT 1").fetchone()
        old_payload = json.loads(old[3])
        old_payload["action"] = "updated"
        self.connection.execute(
            "INSERT INTO platform_events(event_id,workspace_id,event_kind,aggregate_type,aggregate_id,"
            "occurred_at,payload_json,metadata_json) VALUES(?,?,?,?,?,?,?,?)",
            (str(uuid4()), "w", old[0], "agent_exchange_request", old[1], old[2],
             json.dumps(old_payload), "{}"))
        self.connection.commit()
        blockers = self.migration.preview("w")["blockers"]
        self.assertEqual(blockers[0]["reason"], "legacy_write_after_cutover")
        with self.assertRaises(Conflict):
            self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)
        self.assertEqual(self.repo.mode("w"), "core")

    def test_unrelated_platform_fact_after_cutover_does_not_look_like_legacy_writer(self):
        self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)
        self.platform.create_agent_registration("w", agent_id="d", name="D", description="unrelated")
        self.assertEqual(self.migration.preview("w")["blockers"], [])
        self.assertFalse(self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)["created"])

    def test_transactional_platform_append_rolls_back_with_core_uow(self):
        self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)
        old_count = self.connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0]
        new_count = self.repo.high_water()
        event = PlatformEventRecord.create(workspace_id=WorkspaceId("w"),
            event_kind=PlatformEventKind.DELEGATED_WAKE_GRANT_CHANGED,
            aggregate_type="synthetic_atomic_fact", aggregate_id="fixture",
            payload={"action": "fixture"})
        log = SqlitePlatformEventLog(self.connection)
        with self.assertRaisesRegex(RuntimeError, "active caller transaction"):
            log.append_in_transaction(event)
        self.repo.fault = lambda stage: (_ for _ in ()).throw(RuntimeError("fail commit")) if stage == "before_commit" else None
        with self.assertRaisesRegex(RuntimeError, "fail commit"):
            with self.repo.transaction():
                log.append_in_transaction(event)
                self.repo.append("w", "fixture", "synthetic_atomic_write",
                    datetime.now(timezone.utc).isoformat(), {})
        self.repo.fault = lambda _: None
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0], old_count)
        self.assertEqual(self.repo.high_water(), new_count)

    def test_parallel_cutover_writes_one_marker(self):
        self.request()
        barrier = threading.Barrier(2)
        def run(_):
            c = sqlite3.connect(self.path)
            try:
                migration = CommunicationMigration(c, directory=PlatformCommunicationDirectory(c))
                barrier.wait(timeout=5)
                return migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)
            finally:
                c.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, range(2)))
        self.assertCountEqual([r["created"] for r in results], [True, False])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_modes").fetchone()[0], 1)
        self.assertEqual(self.repo.high_water(), 1)

    def test_schema_v1_upgrade_requires_explicit_initialize_and_preserves_id(self):
        self.repo.initialize()
        identity = self.repo.database_id
        self.connection.execute("DROP TABLE communication_mappings")
        self.connection.execute("DROP TABLE communication_modes")
        self.connection.execute("UPDATE communication_schema SET version=1")
        self.connection.commit()
        old = SqliteCommunicationRepository(self.connection)
        self.assertEqual(old.mode("w"), "legacy")
        with self.assertRaises(CommunicationError):
            with old.transaction():
                pass
        old.initialize()
        self.assertEqual(old.database_id, identity)
        self.assertEqual(old.schema_version, 2)

    def test_new_writes_refuse_automatic_downgrade_and_preserve_events(self):
        self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)
        no_write = self.migration.downgrade_advice("w")
        self.assertFalse(no_write["automatic_downgrade"])
        self.assertFalse(no_write["new_semantic_writes"])
        with self.repo.transaction():
            self.repo.append("unrelated-workspace", "fixture", "synthetic_other_workspace",
                datetime.now(timezone.utc).isoformat(), {})
        self.assertFalse(self.migration.downgrade_advice("w")["new_semantic_writes"])
        service = CommunicationService(self.repo, self.directory)
        message = service.send(Caller("w", "a"), target_alias="b", body="New fact", key="new")
        report = self.migration.downgrade_advice("w")
        self.assertFalse(report["automatic_downgrade"])
        self.assertTrue(report["new_semantic_writes"])
        self.assertEqual(self.repo.mode("w"), "core")
        self.assertEqual(service.get(Caller("w", "a"), message["id"])["body"], "New fact")

    def test_synthetic_backup_and_manual_restore_before_new_writes(self):
        request = self.request()
        backup_path = Path(self.temp.name) / "before-cutover.sqlite3"
        report = self.migration.backup(str(backup_path))
        self.assertEqual(report["path"], str(backup_path.resolve()))
        self.assertGreater(report["bytes"], 0)
        with self.assertRaisesRegex(CommunicationError, "already exists"):
            self.migration.backup(str(backup_path))
        self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)
        self.assertEqual(self.repo.mode("w"), "core")
        restored_path = Path(self.temp.name) / "manual-restored-copy.sqlite3"
        shutil.copyfile(backup_path, restored_path)
        with closing(sqlite3.connect(restored_path)) as restored:
            self.assertEqual(restored.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertFalse(restored.execute("SELECT 1 FROM sqlite_master "
                "WHERE name='communication_schema'").fetchone())
            old_request = restored.execute("SELECT COUNT(*) FROM platform_events "
                "WHERE aggregate_type='agent_exchange_request' AND aggregate_id=?",
                (request["exchangeRequestId"],)).fetchone()[0]
            self.assertGreater(old_request, 0)
        self.assertEqual(self.repo.mode("w"), "core")

    def test_unknown_schema_version_fails_closed_without_changing_marker(self):
        self.migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)
        self.connection.execute("UPDATE communication_schema SET version=999")
        self.connection.commit()
        with self.assertRaisesRegex(CommunicationError, "unsupported communication schema"):
            SqliteCommunicationRepository(self.connection)
        self.assertEqual(self.connection.execute("SELECT mode FROM communication_modes "
            "WHERE workspace_id='w'").fetchone()[0], "core")


if __name__ == "__main__":
    unittest.main()
