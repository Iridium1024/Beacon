"""Finite reply wait: caller owns only its waiter, never receiver execution."""
from __future__ import annotations

from datetime import timedelta
import math
import time
from uuid import uuid4

from agent_os.domain.entities.communication import CommunicationError
from agent_os.domain.ports.communication_runtime import RuntimeCoordination


class CommunicationWait:
    def __init__(self, service, coordination: RuntimeCoordination, *, monotonic=time.monotonic, sleep=time.sleep):
        self.service = service
        self.coordination = coordination
        self.monotonic = monotonic
        self.sleep = sleep

    @staticmethod
    def validate(timeout, poll_interval, heartbeat_interval, lease_seconds):
        for name, value in (("timeout", timeout), ("poll", poll_interval),
                            ("heartbeat", heartbeat_interval), ("lease", lease_seconds)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 3600:
                raise CommunicationError(f"wait {name} must be finite and within 0..3600 seconds")
        if lease_seconds < heartbeat_interval * 3 or poll_interval > heartbeat_interval:
            raise CommunicationError("wait lease needs three heartbeat intervals; poll must not exceed heartbeat")

    def wait(self, caller, message_id, *, condition="ack", timeout=120,
             key=None, poll_interval=.1, heartbeat_interval=2, lease_seconds=15,
             include_bodies=False, cancelled=None):
        self.validate(timeout, poll_interval, heartbeat_interval, lease_seconds)
        if not self.coordination.enabled():
            raise CommunicationError("run communication-runtime-init before waiting")
        observation = self.service.observe(caller, message_id, condition=condition,
            deadline=self.service.clock() + timedelta(seconds=timeout), key=key or str(uuid4()))
        return self.wait_observation(caller, observation["id"], timeout=timeout,
            poll_interval=poll_interval, heartbeat_interval=heartbeat_interval,
            lease_seconds=lease_seconds, include_bodies=include_bodies, cancelled=cancelled)

    def _result(self, caller, status, state, *, include_bodies):
        observation = status["observation"]
        facts = self.service.status(caller, observation["message_id"])
        now = self.service._now()
        result = {"schema": "communication_wait.v1", "messageId": observation["message_id"],
                  "observationId": observation["id"], "state": state, "observationState": status["state"],
                  "receiptId": status["receipt_id"], "condition": observation["condition"],
                  "deadline": observation["deadline"], "sampledAt": now,
                  "deliveryState": facts["delivery"]["delivery"], "executionState": facts["delivery"]["execution"],
                  "consumer": self.coordination.consumer_status(caller.workspace_id, now),
                  "recheck": "agent-message-status / agent-message-wait using messageId"}
        if include_bodies and status["receipt_id"]:
            result["reply"] = next(r["body"] for r in facts["receipts"] if r["id"] == status["receipt_id"])
        return result

    def wait_observation(self, caller, observation_id, *, timeout=120, poll_interval=.1,
                         heartbeat_interval=2, lease_seconds=15, include_bodies=False, cancelled=None):
        self.validate(timeout, poll_interval, heartbeat_interval, lease_seconds)
        start = self.monotonic()
        next_heartbeat = start
        token = None
        try:
            while True:
                status = self.service.observation_status(caller, observation_id)
                # Native receipts outrank a simultaneously expired consumer.
                if status["state"] != "pending":
                    return self._result(caller, status, status["state"], include_bodies=include_bodies)
                if cancelled is not None and cancelled():
                    self.service.cancel_observation(caller, observation_id, key=str(uuid4()))
                    status = self.service.observation_status(caller, observation_id)
                    return self._result(caller, status, status["state"], include_bodies=include_bodies)
                now = self.service._now()
                consumer = self.coordination.consumer_status(caller.workspace_id, now)
                if consumer["state"] not in {"running", "draining"}:
                    return self._result(caller, status, "consumer_unavailable", include_bodies=include_bodies)
                tick = self.monotonic()
                if tick - start >= timeout:
                    return self._result(caller, status, "timed_out", include_bodies=include_bodies)
                if token is None:
                    token = self.coordination.waiter_open(status["observation"], now=now, ttl=lease_seconds)
                    next_heartbeat = tick + heartbeat_interval
                elif tick >= next_heartbeat:
                    self.coordination.waiter_renew(token, now=now, ttl=lease_seconds)
                    next_heartbeat = tick + heartbeat_interval
                self.sleep(min(poll_interval, timeout - (tick - start)))
        finally:
            if token is not None:
                self.coordination.waiter_close(token, self.service._now())
