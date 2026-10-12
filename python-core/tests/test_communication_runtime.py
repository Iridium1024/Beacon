"""Real SQLite coordination/fence tests using a deterministic clock."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import asdict
import sqlite3
import threading
import unittest

import test_communication_core as fixtures
from agent_os.application.services.communication_core import CommunicationService
from agent_os.domain.entities.communication import Claim, CommunicationError, Conflict, StaleAttempt
from agent_os.infrastructure.composition.local_platform import build_communication_directory
from agent_os.infrastructure.persistence.communication_runtime_store import SqliteRuntimeCoordination
from agent_os.infrastructure.persistence.communication_store import SqliteCommunicationRepository


class CommunicationRuntimeTests(unittest.TestCase):
    def setUp(self):
        fixtures.CommunicationCoreTests.setUp(self)
        self.runtime = SqliteRuntimeCoordination(self.connection, database_id=self.repo.database_id)
        self.service.coordination = self.runtime

    def owner(self, *, ttl=20):
        self.runtime.initialize()
        return self.runtime.acquire("w", pid=123, start_id="synthetic-start", now=self.service._now(), ttl=ttl)

    def send(self, **kwargs):
        return fixtures.CommunicationCoreTests.send(self, **kwargs)

    def test_status_is_read_only_and_initialization_is_explicit(self):
        before = self.connection.execute("SELECT name FROM sqlite_master").fetchall()
        self.assertEqual(self.runtime.consumer_status("w", self.service._now())["state"], "not_enabled")
        self.assertEqual(self.runtime.waiters("w", "missing", self.service._now()), [])
        self.assertEqual(self.connection.execute("SELECT name FROM sqlite_master").fetchall(), before)
        with self.assertRaises(CommunicationError):
            self.runtime.acquire("w", pid=1, start_id="s", now=self.service._now(), ttl=10)
        self.runtime.initialize()
        self.assertEqual(self.runtime.initialize()["version"], 1)
        self.connection.execute("UPDATE communication_runtime_schema SET version=999")
        self.connection.commit()
        with self.assertRaises(CommunicationError):
            self.runtime.initialize()

    def test_duplicate_start_atomic_takeover_and_database_scope(self):
        owner = self.owner(ttl=2)
        with self.assertRaises(Conflict):
            self.runtime.acquire("w", pid=2, start_id="s2", now=self.service._now(), ttl=2)
        with self.assertRaises(StaleAttempt):
            self.runtime.require_owner({**owner, "database_id": "other"}, self.service._now())
        self.clock.advance(2)
        barrier = threading.Barrier(2)
        def acquire(index):
            with closing(sqlite3.connect(self.path)) as connection:
                runtime = SqliteRuntimeCoordination(connection, database_id=self.repo.database_id)
                barrier.wait(timeout=3)
                try:
                    return runtime.acquire("w", pid=index, start_id=str(index), now=self.service._now(), ttl=10)
                except Conflict:
                    return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(acquire, (11, 22)))
        self.assertEqual(sum(item is not None for item in outcomes), 1)
        self.assertEqual(next(item for item in outcomes if item)["generation"], 2)
        with self.assertRaises(StaleAttempt):
            self.runtime.heartbeat(owner, now=self.service._now(), ttl=10)

    def test_generation_is_checked_inside_claim_start_renew_and_complete(self):
        owner = self.owner(ttl=2)
        message = self.send()
        result = self.service.claim("w", message["id"], owner="child", consumer=owner, lease_seconds=30)
        claim = Claim(**result["claim"])
        self.clock.advance(2)
        with self.assertRaises(StaleAttempt):
            self.service.mark_started(claim)
        with self.assertRaises(StaleAttempt):
            self.service.renew_lease(claim, lease_seconds=30)
        self.assertEqual(self.repo.get("attempts", "w", claim.attempt_id)["phase"], "claimed")
        owner2 = self.runtime.acquire("w", pid=2, start_id="s2", now=self.service._now(), ttl=10)
        with self.assertRaises(StaleAttempt):
            self.service.claim("w", self.send(target="c")["id"], owner="old", consumer=owner)
        self.assertEqual(owner2["generation"], 2)

    def test_fenced_final_evidence_is_retained_but_not_a_business_receipt(self):
        owner = self.owner(ttl=2)
        message = self.send(capture="provider_final_capture")
        claim = Claim(**self.service.claim("w", message["id"], owner="child", consumer=owner, lease_seconds=3)["claim"])
        self.runtime.register_activation(owner, claim.to_dict(), nonce="private-child", now=self.service._now())
        self.service.mark_started(claim)
        evidence = fixtures.CommunicationCoreTests.evidence(self, claim, accepted=True, stopped=True,
                                                          trusted_final=True, final="synthetic final")
        self.clock.advance(2)
        self.runtime.stage_evidence("w", claim.attempt_id, "private-child", asdict(evidence), self.service._now())
        with self.assertRaises(StaleAttempt):
            self.service.complete(claim, evidence)
        self.assertEqual(self.repo.receipts("w", message["id"]), [])
        self.clock.advance(1)
        self.service.recover_expired_slots("w", owner="recovery")
        self.assertEqual(self.service.status(self.a, message["id"])["delivery"]["schedule"], "unknown")
        self.service.reconcile(claim, evidence)
        self.assertEqual(self.service.status(self.a, message["id"])["reply"], "final")
        with self.assertRaises(Conflict):
            self.runtime.stage_evidence("w", claim.attempt_id, "private-child", {**asdict(evidence), "evidence_ref":"other"}, self.service._now())

    def test_send_and_dirty_intent_rollback_and_versioned_drain(self):
        owner = self.owner()
        first = self.send()
        session = self.service.status(self.a, first["id"])["delivery"]["session_key"]
        intent = self.runtime.intent("w", session)
        second = self.send()
        self.assertFalse(self.runtime.drain_intent(owner, session, intent["version"], now=self.service._now(), delay=1))
        self.assertEqual(self.runtime.intent("w", session)["dirty"], 1)
        self.assertNotEqual(first['id'],second['id'])
        for message,body in ((first,'first result'),(second,'second result')):
            self.service.ack(self.b,message['id'],key='ack-'+message['id'])
            self.service.reply(self.b,message['id'],body=body,key='reply-'+message['id'])
            self.assertEqual([r['kind'] for r in self.repo.receipts('w',message['id'])],['ack','final'])
            self.assertEqual(self.repo.receipts('w',message['id'])[-1]['body'],body)
        count = self.repo.high_water()
        self.repo.fault = lambda where: (_ for _ in ()).throw(RuntimeError("injected")) if where == "before_commit" else None
        with self.assertRaises(RuntimeError):
            self.send()
        self.repo.fault = lambda where: None
        self.assertEqual(self.repo.high_water(), count)
        self.assertEqual(self.runtime.intent("w", session)["version"], 2)

    def test_required_consumer_is_new_send_guard_not_idempotent_recovery_guard(self):
        with self.assertRaises(CommunicationError):
            self.send(key="once", require_consumer=True)
        self.assertEqual(self.repo.high_water(), 0)
        owner = self.owner()
        first = self.send(key="once", require_consumer=True)
        self.runtime.finish(owner, self.service._now())
        self.assertEqual(self.send(key="once", require_consumer=True), first)
        with self.assertRaises(CommunicationError):
            self.send(key="new", require_consumer=True)

    def test_native_target_paging_sees_other_target_after_large_a_queue(self):
        self.owner()
        for _ in range(105):
            self.send()
        other = self.send(target="c")
        rows = self.repo.due_targets("w", self.service._now(), limit=20)
        self.assertEqual(len(rows), 2)
        self.assertIn(other["id"], [r["message_id"] for r in rows])
        first = self.repo.due_targets("w", self.service._now(), limit=1)
        second = self.repo.due_targets("w", self.service._now(), after=first[0]["session_key"], limit=1)
        self.assertEqual(len(second), 1)
        self.assertNotEqual(first[0]["session_key"], second[0]["session_key"])

    def test_operational_heartbeat_does_not_append_business_events(self):
        owner = self.owner()
        count = self.repo.high_water()
        for _ in range(20):
            self.clock.advance(.1)
            self.runtime.heartbeat(owner, now=self.service._now(), ttl=20)
        self.assertEqual(self.repo.high_water(), count)

    def test_bounded_cleanup_preserves_unknown_evidence_and_business_history(self):
        owner = self.owner(ttl=3600)
        message = self.send()
        claim = Claim(**self.service.claim('w',message['id'],owner='child',consumer=owner,
            activation_nonce='child',lease_seconds=3)['claim'])
        self.service.mark_started(claim)
        obs = self.service.observe(self.a,message['id'],condition='final',
            deadline=self.clock.now + __import__('datetime').timedelta(seconds=10),key='cleanup-observation')
        self.runtime.waiter_open(obs,now=self.service._now(),ttl=1)
        safe = self.send(target='c')
        safe_claim=Claim(**self.service.claim('w',safe['id'],owner='child-c',consumer=owner,
            activation_nonce='child-c',lease_seconds=3)['claim'])
        self.service.release(safe_claim)
        self.clock.advance(4)
        self.service.recover_expired_slots('w',owner='recovery')
        before = self.repo.high_water()
        self.clock.advance(3601)
        self.assertEqual(self.runtime.cleanup(self.service._now(),limit=1),2)
        self.assertIsNotNone(self.runtime.staged('w',claim.attempt_id))
        self.assertIsNone(self.runtime.staged('w',safe_claim.attempt_id))
        self.assertEqual(self.service.status(self.a,message['id'])['delivery']['schedule'],'unknown')
        self.assertEqual(self.repo.high_water(),before)

    def test_runtime_init_fault_rolls_back_tables_and_marker(self):
        self.connection.execute('CREATE TABLE communication_consumers (incompatible TEXT)')
        self.connection.commit()
        # Force a schema statement failure after BEGIN without changing business tables.
        from unittest.mock import patch
        import agent_os.infrastructure.persistence.communication_runtime_store as store
        with patch.object(store,'SCHEMA',store.SCHEMA+'\nTHIS IS INVALID;'):
            with self.assertRaises(sqlite3.OperationalError):self.runtime.initialize()
        self.assertFalse(self.runtime.enabled())
        self.assertFalse(self.connection.execute("SELECT name FROM sqlite_master WHERE name='communication_waiters'").fetchone())


if __name__ == "__main__":
    unittest.main()
