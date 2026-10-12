"""Restricted waiting evidence, read through ports in an already-owned read UoW."""
from __future__ import annotations

from datetime import datetime, timezone
import math

from agent_os.domain.entities.communication import AccessDenied, Caller, CommunicationError, stamp


MAX_CANDIDATES = 100


def _time(value):
    if not isinstance(value, str):
        raise ValueError("missing time")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("time is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _record_time(value):
    parsed = _time(value)
    if stamp(parsed) != value:
        # The existing core compares canonical UTC timestamps when evaluating
        # receipt ordering. Do not silently reinterpret malformed old facts.
        raise ValueError("record time is not canonical UTC")
    return parsed


def summary_for(service, caller, message, now):
    """No observation IDs, tokens, sender capabilities, or provider I/O escape.

    The caller owns the read transaction. A window is the maximum across
    matching pending observations of min(deadline, lease expiry) minus now.
    Floors preserve a lower bound; a0/f0 distinguish sub-second live evidence
    from 0 (no valid evidence). Evidence is a sample, never a future promise.
    """
    message = service._message(caller, message["id"])
    result = {"code": "?", "sampledAt": now, "evidenceWindowSeconds": {}}
    if caller.agent_id not in {message["sender"], message["target"]}:
        return result
    try:
        sampled = _time(now)
        result["sampledAt"] = stamp(sampled)
        if message["workspace_id"] != caller.workspace_id or _record_time(message["created_at"]) > sampled:
            return result
        coordination = service.coordination
        if coordination is None or not coordination.enabled():
            return result
        candidate_reader = getattr(coordination, "waiter_candidates", None)
        if not callable(candidate_reader):
            return result
        try:
            service.directory.require_member(Caller(caller.workspace_id, message["sender"]))
        except AccessDenied:
            return {**result, "code": "0"}
        candidates = candidate_reader(caller.workspace_id, message["id"], limit=MAX_CANDIDATES + 1)
        if len(candidates) > MAX_CANDIDATES:
            return result
        receipts = service.repo.receipts(caller.workspace_id, message["id"])
        if any(_record_time(receipt["created_at"]) > sampled for receipt in receipts):
            return result
        windows = {}
        for waiter in candidates:
            if waiter["state"] != "waiting":
                return result
            if any(waiter[key] != value for key, value in (
                    ("database_id", service.repo.database_id), ("workspace_id", caller.workspace_id),
                    ("message_id", message["id"]), ("observer", message["sender"]))):
                return result
            observation = service.repo.get("observations", caller.workspace_id, waiter["observation_id"])
            if not observation or any(observation[key] != value for key, value in (
                    ("workspace_id", caller.workspace_id), ("id", waiter["observation_id"]),
                    ("message_id", message["id"]), ("observer", message["sender"]),
                    ("target", message["target"]), ("condition", waiter["condition"]),
                    ("deadline", waiter["deadline"]))):
                return result
            condition = observation["condition"]
            if condition not in {"ack", "final"}:
                return result
            created = _record_time(observation["created_at"])
            deadline = _record_time(observation["deadline"])
            heartbeat = _record_time(waiter["heartbeat_at"])
            lease = _record_time(waiter["lease_until"])
            if not created <= heartbeat <= sampled or deadline < created or lease < heartbeat:
                return result
            if not 0 <= (lease - heartbeat).total_seconds() <= 3600:
                return result
            cancelled = observation["cancelled_at"]
            if cancelled is not None and _record_time(cancelled) > sampled:
                return result
            state = service._observation_state(observation, receipts, stamp(sampled))
            if state["state"] != "pending" or lease <= sampled or deadline <= sampled:
                continue
            remaining = (min(deadline, lease) - sampled).total_seconds()
            if not math.isfinite(remaining) or remaining <= 0:
                return result
            windows[condition] = max(windows.get(condition, 0), math.floor(remaining))
        result["evidenceWindowSeconds"] = windows
        result["code"] = ",".join(prefix + str(windows[condition])
                                  for condition, prefix in (("ack", "a"), ("final", "f"))
                                  if condition in windows) or "0"
        return result
    except (CommunicationError, ValueError, TypeError, KeyError, OverflowError):
        # Corrupt associations, missing instrumentation, or clock anomalies do
        # not become authoritative absence or a fabricated waiting condition.
        return result
