"""One workspace supervisor; bounded native-key scheduling and owned child lifetime."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
import time
from uuid import uuid4

from agent_os.domain.entities.communication import AccessDenied, Claim, CommunicationError, Conflict, StaleAttempt
from agent_os.domain.ports.communication_runtime import ActivationProcessPort, RuntimeCoordination


@dataclass(frozen=True)
class RuntimeConfig:
    concurrency: int = 2
    poll_interval: float = .2
    heartbeat_interval: float = 2
    consumer_lease: float = 30
    attempt_lease: int = 30
    provider_timeout: int = 120
    shutdown_timeout: float = 10
    backoff: float = 2
    page_size: int = 20

    def __post_init__(self):
        for name, low, high in (("concurrency", 1, 16), ("attempt_lease", 1, 3600),
                                ("provider_timeout", 1, 3570), ("page_size", 1, 100)):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise CommunicationError(f"runtime {name} must be {low}..{high}")
        for name in ("poll_interval", "heartbeat_interval", "consumer_lease", "shutdown_timeout", "backoff"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not .01 <= value <= 3600:
                raise CommunicationError(f"runtime {name} must be finite and within .01..3600 seconds")
        if self.poll_interval > self.heartbeat_interval or self.consumer_lease < 3 * self.heartbeat_interval:
            raise CommunicationError("consumer lease needs three heartbeat intervals; poll must not exceed heartbeat")


class CommunicationSupervisor:
    def __init__(self, service, coordination: RuntimeCoordination, processes: ActivationProcessPort,
                 *, config=None, monotonic=time.monotonic, sleep=time.sleep):
        self.service = service
        self.coordination = coordination
        self.processes = processes
        self.config = config or RuntimeConfig()
        self.monotonic, self.sleep = monotonic, sleep
        self.children = {}
        self.cursor = ""
        self.owner = None
        self.last_heartbeat = None
        self.draining = False
        self.last_cleanup = None

    def start(self, workspace_id, *, pid, start_id):
        self.owner = self.coordination.acquire(workspace_id, pid=pid, start_id=start_id,
                                              now=self.service._now(), ttl=self.config.consumer_lease)
        self.last_heartbeat = self.monotonic()
        self.last_cleanup = self.last_heartbeat
        return self.owner

    def _renew_or_reap(self):
        for identity, child in list(self.children.items()):
            claim, process = child["claim"], child["process"]
            status = self.service.attempt_status(claim)
            terminal = status["phase"] not in {"claimed", "started", "running"}
            if self.processes.poll(process) is not None:
                if not terminal:
                    try:
                        # Before start is provable non-I/O; after start stays unknown.
                        self.service.release(claim)
                    except StaleAttempt:
                        pass
                self.processes.close(process)
                del self.children[identity]
                continue
            deadline = status["provider_deadline"]
            # Bound preflight as well as execution. Heartbeats never extend timeout.
            overdue = (deadline is not None and self.service._now() >= deadline) or (
                deadline is None and self.monotonic() - child["launched"] >= self.config.provider_timeout)
            if overdue:
                self.processes.stop(process)
                try:
                    self.service.release(claim)
                except StaleAttempt:
                    pass
                continue
            if not terminal and status["lease_until"] is not None:
                remaining = (datetime.fromisoformat(status["lease_until"]) - self.service.clock()).total_seconds()
                if remaining <= self.config.attempt_lease / 2:
                    self.service.renew_lease(claim, lease_seconds=self.config.attempt_lease)

    def tick(self, *, target_agent_id=None):
        if self.owner is None:
            raise CommunicationError("supervisor has not acquired ownership")
        tick = self.monotonic()
        current = self.coordination.require_owner(self.owner, self.service._now(), allow_draining=True)
        self.draining = self.draining or current["stop_requested"]
        if tick - self.last_heartbeat >= self.config.heartbeat_interval or self.draining:
            heartbeat = self.coordination.heartbeat(self.owner, now=self.service._now(),
                ttl=self.config.consumer_lease, draining=self.draining)
            self.draining = heartbeat["state"] == "draining"
            self.last_heartbeat = tick
        self.coordination.require_owner(self.owner, self.service._now(), allow_draining=True)
        self._renew_or_reap()
        if tick - self.last_cleanup >= 60:
            self.coordination.cleanup(self.service._now(), limit=self.config.page_size)
            self.last_cleanup = tick
        self.service.recover_expired_slots(self.owner["workspace_id"], owner="runtime-recovery", limit=self.config.page_size)
        if self.draining or len(self.children) >= self.config.concurrency:
            return
        rows = self.service.due_targets(self.owner["workspace_id"], after=self.cursor,
                                       limit=self.config.page_size, target_agent_id=target_agent_id)
        if not rows:
            self.cursor = ""
            return
        for delivery in rows:
            if len(self.children) >= self.config.concurrency:
                break
            self.cursor = delivery["session_key"]
            intent = self.coordination.intent(self.owner["workspace_id"], self.cursor)
            now = self.service._now()
            if intent and intent["next_check"] > now:
                continue
            nonce = str(uuid4())
            try:
                result = self.service.claim(self.owner["workspace_id"], delivery["message_id"],
                    owner="activation-" + nonce, consumer=self.owner, activation_nonce=nonce,
                    lease_seconds=self.config.attempt_lease, provider_timeout_seconds=self.config.provider_timeout)
            except StaleAttempt:
                raise
            except (AccessDenied, Conflict):
                # A revoked/rebound route must not stop unrelated eligible keys.
                # The core transaction rolled back; no activation is authorized.
                result = {"outcome": "route_unavailable"}
            self.coordination.drain_intent(self.owner, self.cursor, intent["version"] if intent else 0,
                                           now=self.service._now(), delay=self.config.backoff)
            if result["outcome"] != "claimed":
                continue
            claim = Claim(**result["claim"])
            try:
                process = self.processes.start(claim.to_dict(), self.owner, nonce)
            except (OSError, ValueError):
                self.service.release(claim)
                continue
            self.children[claim.attempt_id] = {"claim": claim, "process": process, "launched": self.monotonic()}
            self.coordination.attach_process(self.owner, claim.attempt_id, pid=process.pid,
                                             start_id=nonce, now=self.service._now())

    def shutdown(self):
        self.draining = True
        end = self.monotonic() + self.config.shutdown_timeout
        try:
            while self.children and self.monotonic() < end:
                self.tick()
                remaining = end - self.monotonic()
                if remaining > 0:
                    self.sleep(min(self.config.poll_interval, remaining))
        except StaleAttempt:
            pass
        finally:
            for child in self.children.values():
                process, claim = child["process"], child["claim"]
                try:
                    self.processes.stop(process)
                    self.service.release(claim)
                except Exception:
                    # Contention/fencing cannot prevent cleanup of other owned
                    # handles; business state remains unknown until recovery.
                    pass
                finally:
                    try:
                        self.processes.close(process)
                    except Exception:
                        pass
            self.children.clear()
            if self.owner is not None:
                try:
                    self.coordination.finish(self.owner, self.service._now())
                except Exception:
                    pass

    def run(self, workspace_id, *, pid, start_id, target_agent_id=None):
        self.start(workspace_id, pid=pid, start_id=start_id)
        try:
            while True:
                self.tick(target_agent_id=target_agent_id)
                if self.draining:
                    return {"state": "stopped", "generation": self.owner["generation"]}
                self.sleep(self.config.poll_interval)
        finally:
            self.shutdown()
