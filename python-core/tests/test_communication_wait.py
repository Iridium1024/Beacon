"""Independent observations, lease facts and cancellation boundaries."""
from datetime import timedelta
import unittest

import test_communication_core as fixtures
from agent_os.application.services.communication_wait import CommunicationWait
from agent_os.domain.entities.communication import AccessDenied, StaleAttempt
from agent_os.infrastructure.persistence.communication_runtime_store import SqliteRuntimeCoordination


class CommunicationWaitTests(unittest.TestCase):
    def setUp(self):
        fixtures.CommunicationCoreTests.setUp(self)
        self.runtime = SqliteRuntimeCoordination(self.connection, database_id=self.repo.database_id)
        self.runtime.initialize()
        self.service.coordination = self.runtime
        self.owner = self.runtime.acquire("w", pid=1, start_id="fixture", now=self.service._now(), ttl=30)
        self.message = fixtures.CommunicationCoreTests.send(self, expectation="final")

    def observation(self, condition="ack", key="obs"):
        return self.service.observe(self.a, self.message["id"], condition=condition,
            deadline=self.clock.now + timedelta(seconds=10), key=key)

    def loop(self, step):
        elapsed = [0.0]
        def sleep(seconds):
            elapsed[0] += seconds
            self.clock.advance(seconds)
            step(elapsed[0])
        return CommunicationWait(self.service, self.runtime, monotonic=lambda: elapsed[0], sleep=sleep)

    def test_ack_returns_without_final_and_closes_only_own_waiter(self):
        obs = self.observation()
        other = self.observation(key="other")
        other_token = self.runtime.waiter_open(other, now=self.service._now(), ttl=5)
        snapshots = []
        def step(tick):
            facts = self.service.status(self.b, self.message["id"])
            snapshots.append(facts["active_waiter_verified"])
            self.service.ack(self.b, self.message["id"], key="ack")
        result = self.loop(step).wait_observation(self.a, obs["id"])
        self.assertEqual(result["state"], "satisfied")
        self.assertNotIn("reply", result)
        self.assertTrue(all(snapshots))
        self.assertEqual(self.service.status(self.a, self.message["id"])["reply"], "none")
        self.assertEqual(sum(w["state"] == "active" for w in self.runtime.waiters("w", self.message["id"], self.service._now())), 1)
        self.runtime.waiter_close(other_token, self.service._now())

    def test_final_wait_ignores_ack_progress_and_returns_opt_in_body(self):
        obs = self.observation("final")
        ticks = []
        def step(tick):
            ticks.append(tick)
            if len(ticks) == 1:
                self.service.ack(self.b, self.message["id"], key="ack")
                self.service.reply(self.b, self.message["id"], body="working", kind="progress", key="progress")
            else:
                self.service.reply(self.b, self.message["id"], body="synthetic done", key="final")
        result = self.loop(step).wait_observation(self.a, obs["id"], include_bodies=True)
        self.assertEqual(len(ticks), 2)
        self.assertEqual(result["reply"], "synthetic done")

    def test_preexisting_final_outranks_consumer_unavailable(self):
        self.service.reply(self.b, self.message["id"], body="done", key="final")
        self.runtime.finish(self.owner, self.service._now())
        result = self.loop(lambda t: self.fail("already satisfied wait slept")).wait(self.a, self.message["id"])
        self.assertEqual(result["state"], "satisfied")
        self.assertEqual(result["consumer"]["state"], "stopped")

    def test_reject_and_cancel_are_distinct_from_success(self):
        obs = self.observation()
        self.service.cancel_observation(self.a, obs["id"], key="cancel")
        self.service.ack(self.b, self.message["id"], key="late")
        self.assertEqual(self.loop(lambda t: None).wait_observation(self.a, obs["id"])["state"], "cancelled")
        second = fixtures.CommunicationCoreTests.send(self)
        self.service.reply(self.b, second["id"], body="cannot", kind="reject", key="reject")
        self.assertEqual(self.loop(lambda t: None).wait(self.a, second["id"])["state"], "rejected")

    def test_deadline_equality_does_not_cancel_execution(self):
        obs = self.observation("final")
        def step(tick):
            if tick >= 10:
                self.service.reply(self.b, self.message["id"], body="same time", key="equal")
        result = self.loop(step).wait_observation(self.a, obs["id"], timeout=10, poll_interval=1,
                                                heartbeat_interval=1, lease_seconds=4)
        self.assertEqual(result["state"], "timed_out")
        self.assertEqual(self.service.status(self.a, self.message["id"])["reply"], "final")

    def test_recent_waiter_is_scoped_and_expiry_cannot_be_renewed(self):
        token = self.runtime.waiter_open(self.observation(), now=self.service._now(), ttl=1)
        target = self.service.status(self.b, self.message["id"])
        self.assertTrue(target["active_waiter_verified"])
        self.assertNotIn("nonce", str(target["waiters"]))
        self.assertNotIn("observation_id", str(target["waiters"]))
        self.assertFalse(self.service.status(self.c, self.message["id"])["active_waiter_verified"])
        self.clock.advance(1)
        self.assertFalse(self.service.status(self.b, self.message["id"])["active_waiter_verified"])
        with self.assertRaises(StaleAttempt):
            self.runtime.waiter_renew(token, now=self.service._now(), ttl=10)

    def test_wait_discovery_lists_only_observations_owned_by_caller(self):
        own=self.observation()
        with self.assertRaises(AccessDenied):
            self.service.observe(self.b,self.message['id'],condition='final',deadline=self.clock.now+timedelta(seconds=10),key='target-observer')
        self.assertEqual([w['observationId'] for w in self.service.own_waits(self.a,self.message['id'])],[own['id']])
        self.assertEqual(self.service.own_waits(self.c,self.message['id']),[])

    def test_revoked_visibility_does_not_prevent_capability_cleanup(self):
        obs = self.observation()
        def step(tick):
            self.directory.reader.member_active = lambda caller: False
        with self.assertRaises(AccessDenied):
            self.loop(step).wait_observation(self.a, obs["id"])
        self.assertTrue(all(w["state"] == "closed" for w in self.runtime.waiters("w", self.message["id"], self.service._now())))

    def test_local_monotonic_timeout_ends_wait_even_after_wall_clock_rollback(self):
        obs = self.observation("final")
        def step(tick):
            self.clock.advance(-.1)
        result = self.loop(step).wait_observation(self.a, obs["id"], timeout=.2)
        self.assertEqual(result["state"], "timed_out")
        self.assertEqual(result["observationState"], "pending")
        self.assertEqual(self.service.status(self.a, self.message["id"])["delivery"]["schedule"], "pending")


if __name__ == "__main__":
    unittest.main()
