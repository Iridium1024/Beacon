"""Synthetic evidence for restricted, observation-aware ACK/final summaries."""
from datetime import timedelta
import json
from types import SimpleNamespace
import unittest
from uuid import uuid4

import test_communication_core as fixtures
from agent_os.application.services.communication_wait_summary import summary_for
from agent_os.domain.entities.communication import AccessDenied, Caller, CommunicationError, stamp
from agent_os.infrastructure.persistence.communication_runtime_store import SqliteRuntimeCoordination


class CommunicationWaitSummaryTests(unittest.TestCase):
    def setUp(self):
        fixtures.CommunicationCoreTests.setUp(self)
        self.runtime = SqliteRuntimeCoordination(self.connection, database_id=self.repo.database_id)
        self.runtime.initialize()
        self.service.coordination = self.runtime
        self.message = fixtures.CommunicationCoreTests.send(self, expectation="final")

    def observation(self, condition="ack", *, seconds=10):
        return self.service.observe(self.a, self.message["id"], condition=condition,
                                    deadline=self.clock.now + timedelta(seconds=seconds), key=str(uuid4()))

    def waiting(self, condition="ack", *, seconds=10, ttl=5):
        observation = self.observation(condition, seconds=seconds)
        token = self.runtime.waiter_open(observation, now=self.service._now(), ttl=ttl)
        return observation, token

    def summary(self, caller=None, *, now=None):
        with self.repo.transaction(write=False):
            return summary_for(self.service, caller or self.b, self.message, now or self.service._now())

    def mutate_waiter(self, token, **changes):
        raw = self.connection.execute("SELECT data FROM communication_waiters WHERE id=?", (token["id"],)).fetchone()[0]
        item = {**json.loads(raw), **changes}
        self.connection.execute("UPDATE communication_waiters SET data=? WHERE id=?", (json.dumps(item), token["id"]))
        self.connection.commit()

    def mutate_observation(self, observation, **changes):
        raw = self.connection.execute("SELECT data FROM communication_observations WHERE id=?", (observation["id"],)).fetchone()[0]
        self.connection.execute("UPDATE communication_observations SET data=? WHERE id=?",
                                (json.dumps({**json.loads(raw), **changes}), observation["id"]))
        self.connection.commit()

    def test_expectation_and_pending_observation_are_not_wait_evidence(self):
        self.assertEqual(self.summary()["code"], "0")
        self.observation("final")
        self.assertEqual(self.summary()["code"], "0")

    def test_active_ack_and_final_have_distinct_fields(self):
        self.waiting("final", ttl=7)
        self.waiting("ack", ttl=3)
        result = self.summary()
        self.assertEqual(result["code"], "a3,f7")
        self.assertEqual(result["evidenceWindowSeconds"], {"ack": 3, "final": 7})
        self.assertEqual(self.summary(self.a), result)

    def test_single_condition_and_subsecond_evidence(self):
        self.waiting(ttl=.5)
        self.assertEqual(self.summary()["code"], "a0")
        self.clock.advance(.5)
        self.assertEqual(self.summary()["code"], "0")

    def test_same_condition_aggregates_maximum_of_deadline_and_lease_minimum(self):
        self.waiting("final", seconds=2, ttl=20)
        long, token = self.waiting("final", seconds=10, ttl=7)
        self.runtime.waiter_open(long, now=self.service._now(), ttl=3)
        self.assertEqual(self.summary()["code"], "f7")
        self.runtime.waiter_close(token, self.service._now())
        self.assertEqual(self.summary()["code"], "f3")

    def test_ack_satisfies_ack_while_final_lease_stays_open(self):
        self.waiting("ack")
        self.waiting("final")
        self.service.ack(self.b, self.message["id"], key="ack")
        self.assertTrue(all(w["state"] == "active" for w in self.runtime.waiters("w", self.message["id"], self.service._now())))
        self.assertEqual(self.summary()["code"], "f5")

    def test_progress_does_not_satisfy_final_wait(self):
        self.waiting("final")
        self.service.reply(self.b, self.message["id"], kind="progress", body="working", key="progress")
        self.service.ack(self.b, self.message["id"], key="ack")
        self.assertEqual(self.summary()["code"], "f5")

    def test_final_satisfies_both_classes_before_waiters_close(self):
        self.waiting("ack")
        self.waiting("final")
        self.service.reply(self.b, self.message["id"], body="done", key="final")
        self.assertEqual(self.summary()["code"], "0")

    def test_reject_satisfies_both_classes_without_claiming_success(self):
        ack, _ = self.waiting("ack")
        final, _ = self.waiting("final")
        self.service.reply(self.b, self.message["id"], kind="reject", body="cannot", key="reject")
        self.assertEqual(self.summary()["code"], "0")
        self.assertEqual(self.service.observation_status(self.a, ack["id"])["state"], "rejected")
        self.assertEqual(self.service.observation_status(self.a, final["id"])["state"], "rejected")

    def test_cancelled_observation_does_not_count_before_lease_close(self):
        observation, _ = self.waiting("final")
        self.service.cancel_observation(self.a, observation["id"], key="cancel")
        self.assertEqual(self.summary()["code"], "0")

    def test_deadline_equality_and_abandoned_lease_expiry_are_inactive(self):
        self.waiting("final", seconds=1, ttl=10)
        self.clock.advance(1)
        self.assertEqual(self.summary()["code"], "0")
        self.waiting("ack", seconds=10, ttl=1)
        self.clock.advance(1)
        self.assertEqual(self.summary()["code"], "0")

    def test_cancel_then_same_timestamp_final_keeps_existing_event_order(self):
        observation, _ = self.waiting("final")
        self.service.cancel_observation(self.a, observation["id"], key="cancel")
        self.service.reply(self.b, self.message["id"], body="same time", key="final")
        self.assertEqual(self.summary()["code"], "0")
        self.assertEqual(self.service.observation_status(self.a, observation["id"])["state"], "cancelled")

    def test_closed_waiter_and_no_runtime_instrumentation_are_distinct(self):
        _, token = self.waiting()
        self.runtime.waiter_close(token, self.service._now())
        self.assertEqual(self.summary()["code"], "0")
        self.service.coordination = None
        self.assertEqual(self.summary()["code"], "?")
        self.service.coordination = SimpleNamespace(enabled=lambda: True)
        self.assertEqual(self.summary()["code"], "?")
        self.service.coordination = SimpleNamespace(enabled=lambda: False)
        self.assertEqual(self.summary()["code"], "?")

    def test_missing_observation_cannot_become_valid_wait(self):
        observation, _ = self.waiting()
        fake = {**observation, "id": "not-an-observation"}
        self.runtime.waiter_open(fake, now=self.service._now(), ttl=5)
        self.assertEqual(self.summary()["code"], "?")

    def test_inconsistent_owner_database_and_target_are_unknown(self):
        for changes in ({"observer": "c"}, {"database_id": "other-database"}):
            with self.subTest(changes=changes):
                _, token = self.waiting()
                self.mutate_waiter(token, **changes)
                self.assertEqual(self.summary()["code"], "?")
                self.connection.execute("DELETE FROM communication_waiters WHERE id=?", (token["id"],))
                self.connection.commit()
        observation, _ = self.waiting()
        self.mutate_observation(observation, target="c")
        self.assertEqual(self.summary()["code"], "?")

    def test_physical_row_association_mismatch_is_unknown(self):
        _, token = self.waiting()
        self.mutate_waiter(token, observation_id="different")
        self.assertEqual(self.summary()["code"], "?")

    def test_condition_and_deadline_mismatch_are_unknown(self):
        _, token = self.waiting()
        self.mutate_waiter(token, condition="final")
        self.assertEqual(self.summary()["code"], "?")
        self.mutate_waiter(token, condition="ack", deadline=stamp(self.clock.now + timedelta(seconds=3)))
        self.assertEqual(self.summary()["code"], "?")

    def test_malformed_naive_and_noncanonical_times_are_unknown(self):
        _, token = self.waiting()
        for value in (None, "yesterday", "2026-09-28T08:00:00", "2026-09-28T09:00:00.000000+01:00"):
            with self.subTest(value=value):
                self.mutate_waiter(token, heartbeat_at=value)
                self.assertEqual(self.summary()["code"], "?")

    def test_clock_rollback_and_future_cancellation_are_unknown(self):
        observation, _ = self.waiting()
        self.clock.advance(-1)
        self.assertEqual(self.summary()["code"], "?")
        self.clock.advance(3)
        self.service.cancel_observation(self.a, observation["id"], key="cancel")
        self.clock.advance(-1)
        self.assertEqual(self.summary()["code"], "?")

    def test_future_heartbeat_is_unknown_without_resetting_sample_age(self):
        _, token = self.waiting()
        self.mutate_waiter(token, heartbeat_at=stamp(self.clock.now + timedelta(seconds=1)))
        result = self.summary()
        self.assertEqual(result["code"], "?")
        self.assertEqual(result["sampledAt"], self.service._now())

    def test_future_receipt_after_clock_rollback_is_unknown(self):
        self.waiting("final")
        self.clock.advance(2)
        self.service.reply(self.b, self.message["id"], kind="progress", body="working", key="future-progress")
        self.clock.advance(-1)
        self.assertEqual(self.summary()["code"], "?")

    def test_impossible_lease_and_unknown_waiter_state_are_unknown(self):
        _, token = self.waiting()
        self.mutate_waiter(token, lease_until=stamp(self.clock.now - timedelta(seconds=1)))
        self.assertEqual(self.summary()["code"], "?")
        self.mutate_waiter(token, lease_until=stamp(self.clock.now + timedelta(seconds=5)), state="unverified")
        self.assertEqual(self.summary()["code"], "?")

    def test_corrupt_json_is_unknown_and_candidate_limit_is_validated(self):
        _, token = self.waiting()
        self.connection.execute("UPDATE communication_waiters SET data='{' WHERE id=?", (token["id"],))
        self.connection.commit()
        self.assertEqual(self.summary()["code"], "?")
        for limit in (0, 1002, True):
            with self.assertRaises(CommunicationError):
                self.runtime.waiter_candidates("w", self.message["id"], limit=limit)

    def test_candidate_overflow_is_unknown_instead_of_truncated_absence(self):
        observation = self.observation()
        for _ in range(101):
            self.runtime.waiter_open(observation, now=self.service._now(), ttl=5)
        self.assertEqual(self.summary()["code"], "?")

    def test_nonendpoint_reader_sees_unknown_and_private_reader_is_denied(self):
        self.waiting()
        self.assertEqual(self.summary(self.c)["code"], "?")
        self.service.change_thread_visibility(self.a, self.message["thread_id"], "participants_only")
        with self.assertRaises(AccessDenied):
            self.summary(self.c)
        with self.assertRaises(AccessDenied):
            self.summary(Caller("other-workspace", "b"))

    def test_receiver_never_gets_sender_observation_operations_or_tokens(self):
        observation, token = self.waiting()
        result = self.summary()
        self.assertEqual(set(result), {"code", "sampledAt", "evidenceWindowSeconds"})
        self.assertNotIn(observation["id"], str(result))
        self.assertNotIn(token["nonce"], str(result))
        with self.assertRaises(AccessDenied):
            self.service.cancel_observation(self.b, observation["id"], key="target-cannot-cancel")

    def test_sender_revocation_removes_valid_evidence_receiver_revocation_denies_read(self):
        self.waiting()
        original = self.directory.reader.member_active
        self.directory.reader.member_active = lambda caller: caller.agent_id != "a" and original(caller)
        self.assertEqual(self.summary()["code"], "0")
        self.directory.reader.member_active = lambda caller: False
        with self.assertRaises(AccessDenied):
            self.summary()

    def test_read_uses_existing_transaction_single_sample_and_makes_no_writes(self):
        self.waiting()
        sequence = self.repo.high_water()
        rows = self.connection.execute("SELECT data FROM communication_waiters ORDER BY id").fetchall()
        sampled = self.service._now()
        with self.repo.transaction(write=False):
            result = summary_for(self.service, self.b, self.message, sampled)
            self.assertTrue(self.connection.in_transaction)
            self.assertEqual(result["sampledAt"], sampled)
        self.assertEqual(self.repo.high_water(), sequence)
        self.assertEqual(self.connection.execute("SELECT data FROM communication_waiters ORDER BY id").fetchall(), rows)


if __name__ == "__main__":
    unittest.main()
