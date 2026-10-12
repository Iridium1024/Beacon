"""Explicit, same-database operational leases and bounded coordination hints.

These rows are not a second delivery state machine. Generation checks invoked
by the core run inside its existing transaction on this very connection.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
import json
from uuid import uuid4

from agent_os.domain.entities.communication import CommunicationError, Conflict, StaleAttempt, stamp

VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS communication_runtime_schema (singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL, database_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS communication_consumers (workspace_id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS communication_activations (workspace_id TEXT NOT NULL, attempt_id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(workspace_id,attempt_id));
CREATE TABLE IF NOT EXISTS communication_waiters (workspace_id TEXT NOT NULL, id TEXT NOT NULL, message_id TEXT NOT NULL, observation_id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(workspace_id,id));
CREATE INDEX IF NOT EXISTS communication_waiters_message ON communication_waiters(workspace_id,message_id);
CREATE TABLE IF NOT EXISTS communication_wake_intents (workspace_id TEXT NOT NULL, session_key TEXT NOT NULL, version INTEGER NOT NULL, dirty INTEGER NOT NULL, next_check TEXT NOT NULL, PRIMARY KEY(workspace_id,session_key));
CREATE INDEX IF NOT EXISTS communication_due_native ON communication_deliveries(workspace_id,schedule,session_key,source_sequence);
CREATE TABLE IF NOT EXISTS communication_runtime_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL, kind TEXT NOT NULL, occurred_at TEXT NOT NULL, generation INTEGER);
"""


def until(now: str, ttl: float) -> str:
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not 0 < ttl <= 3600:
        raise CommunicationError("runtime TTL must be finite and within 0..3600 seconds")
    return stamp(datetime.fromisoformat(now) + timedelta(seconds=ttl))


class SqliteRuntimeCoordination:
    def __init__(self, connection, *, database_id: str | None):
        self.connection = connection
        self.database_id = database_id

    def enabled(self) -> bool:
        exists = self.connection.execute("SELECT 1 FROM sqlite_master WHERE name='communication_runtime_schema'").fetchone()
        if not exists:
            return False
        row = self.connection.execute("SELECT version,database_id FROM communication_runtime_schema WHERE singleton=1").fetchone()
        if row != (VERSION, self.database_id) or not self.database_id:
            raise CommunicationError("unsupported communication runtime schema/database identity")
        return True

    def initialize(self) -> dict:
        if self.connection.in_transaction:
            raise CommunicationError("runtime initialization cannot join a caller transaction")
        if not self.database_id:
            raise CommunicationError("initialize communication core first")
        if self.enabled():
            return {"initialized": True, "version": VERSION}
        try:
            # executescript has an implicit pre-commit; never use it in core UoW.
            self.connection.executescript("BEGIN IMMEDIATE;\n" + SCHEMA)
            self.connection.execute("INSERT INTO communication_runtime_schema VALUES(1,?,?)", (VERSION, self.database_id))
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise
        return {"initialized": True, "version": VERSION}

    @contextmanager
    def transaction(self):
        if not self.enabled():
            raise CommunicationError("run communication-runtime-init before starting a consumer/waiter")
        joined = self.connection.in_transaction
        if not joined:
            self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            if not joined:
                self.connection.commit()
        except BaseException:
            if not joined:
                self.connection.rollback()
            raise

    def _consumer(self, workspace_id):
        row = self.connection.execute("SELECT data FROM communication_consumers WHERE workspace_id=?", (workspace_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def _save_consumer(self, item):
        self.connection.execute("INSERT INTO communication_consumers VALUES(?,?) ON CONFLICT(workspace_id) DO UPDATE SET data=excluded.data",
                                (item["workspace_id"], json.dumps(item)))

    def _audit(self, workspace_id, kind, now, generation=None):
        self.connection.execute("INSERT INTO communication_runtime_audit(workspace_id,kind,occurred_at,generation) VALUES(?,?,?,?)", (workspace_id, kind, now, generation))
        self.connection.execute("DELETE FROM communication_runtime_audit WHERE workspace_id=? AND id NOT IN (SELECT id FROM communication_runtime_audit WHERE workspace_id=? ORDER BY id DESC LIMIT 500)", (workspace_id, workspace_id))

    def consumer_status(self, workspace_id, now):
        if not self.enabled():
            return {"state": "not_enabled", "sampledAt": now, "leaseUntil": None}
        item = self._consumer(workspace_id)
        if not item:
            return {"state": "absent", "sampledAt": now, "leaseUntil": None}
        state = item["state"] if item["state"] == "stopped" or item["lease_until"] > now else "expired"
        if item["stop_requested"] and state == "running":
            state = "draining"
        return {"state": state, "sampledAt": now, "leaseUntil": item["lease_until"],
                "heartbeatAt": item["heartbeat_at"], "generation": item["generation"], "pid": item["pid"], "startId": item["start_id"]}

    def acquire(self, workspace_id, *, pid, start_id, now, ttl):
        lease = until(now, ttl)
        with self.transaction():
            old = self._consumer(workspace_id)
            if old and old["state"] in {"running", "draining"} and old["lease_until"] > now:
                raise Conflict("workspace already has a live communication consumer")
            item = {"database_id": self.database_id, "workspace_id": workspace_id,
                    "generation": (old["generation"] if old else 0) + 1, "nonce": str(uuid4()),
                    "pid": pid, "start_id": start_id, "state": "running", "lease_until": lease,
                    "heartbeat_at": now, "stop_requested": False}
            self._save_consumer(item)
            self._audit(workspace_id, "consumer_acquired", now, item["generation"])
            return {k: item[k] for k in ("database_id", "workspace_id", "generation", "nonce")}

    def require_owner(self, token, now, *, allow_draining=False):
        if not self.enabled():
            raise StaleAttempt("consumer coordination is unavailable")
        item = self._consumer(token["workspace_id"])
        if (not item or any(item.get(k) != token.get(k) for k in ("database_id", "workspace_id", "generation", "nonce"))
                or item["lease_until"] <= now or (not allow_draining and item["stop_requested"])
                or item["state"] not in ({"running", "draining"} if allow_draining else {"running"})):
            raise StaleAttempt("consumer generation/lease is stale")
        return item

    def heartbeat(self, token, *, now, ttl, draining=False):
        with self.transaction():
            item = self.require_owner(token, now, allow_draining=True)
            item.update(heartbeat_at=now, lease_until=until(now, ttl))
            if draining or item["stop_requested"]:
                if item["state"] != "draining":
                    self._audit(item["workspace_id"], "consumer_draining", now, item["generation"])
                item["state"] = "draining"
            self._save_consumer(item)
            return {"state": item["state"]}

    def request_stop(self, workspace_id, now):
        with self.transaction():
            item = self._consumer(workspace_id)
            if item and item["lease_until"] > now:
                item["stop_requested"] = True
                self._save_consumer(item)
            return self.consumer_status(workspace_id, now)

    def finish(self, token, now):
        with self.transaction():
            item = self.require_owner(token, now, allow_draining=True)
            item.update(state="stopped", lease_until=now)
            self._save_consumer(item)
            self._audit(item["workspace_id"], "consumer_stopped", now, item["generation"])

    def notice(self, workspace_id, deliveries, now):
        if not self.enabled():
            return
        # Called by send inside the core transaction: hints cannot outlive rollback.
        if not self.connection.in_transaction:
            raise CommunicationError("wake intent must join the message transaction")
        for item in deliveries:
            if item["schedule"] == "pending":
                self.connection.execute("INSERT INTO communication_wake_intents VALUES(?,?,1,1,?) ON CONFLICT(workspace_id,session_key) DO UPDATE SET version=version+1,dirty=1,next_check=excluded.next_check",
                                        (workspace_id, item["session_key"], now))

    def intent(self, workspace_id, session_key):
        if not self.enabled():
            return None
        row = self.connection.execute("SELECT version,dirty,next_check FROM communication_wake_intents WHERE workspace_id=? AND session_key=?", (workspace_id, session_key)).fetchone()
        return dict(zip(("version", "dirty", "next_check"), row)) if row else None

    def drain_intent(self, token, session_key, version, *, now, delay):
        with self.transaction():
            self.require_owner(token, now, allow_draining=True)
            if version == 0:
                return self.connection.execute("INSERT OR IGNORE INTO communication_wake_intents VALUES(?,?,0,0,?)", (token["workspace_id"], session_key, until(now, delay))).rowcount == 1
            return self.connection.execute("UPDATE communication_wake_intents SET dirty=0,next_check=? WHERE workspace_id=? AND session_key=? AND version=?", (until(now, delay), token["workspace_id"], session_key, version)).rowcount == 1

    def register_activation(self, token, claim, *, nonce, now):
        with self.transaction():
            self.require_owner(token, now)
            item = {"claim": claim, "consumer": token, "nonce": nonce, "registered_at": now,
                    "pid": None, "start_id": None, "evidence": None}
            self.connection.execute("INSERT INTO communication_activations VALUES(?,?,?)", (token["workspace_id"], claim["attempt_id"], json.dumps(item)))

    def _activation(self, workspace_id, attempt_id):
        row = self.connection.execute("SELECT data FROM communication_activations WHERE workspace_id=? AND attempt_id=?", (workspace_id, attempt_id)).fetchone()
        return json.loads(row[0]) if row else None

    def _save_activation(self, workspace_id, attempt_id, item):
        self.connection.execute("UPDATE communication_activations SET data=? WHERE workspace_id=? AND attempt_id=?", (json.dumps(item), workspace_id, attempt_id))

    def attach_process(self, token, attempt_id, *, pid, start_id, now):
        with self.transaction():
            self.require_owner(token, now, allow_draining=True)
            item = self._activation(token["workspace_id"], attempt_id)
            if not item or item["consumer"] != token:
                raise StaleAttempt("activation belongs to another consumer")
            item.update(pid=pid, start_id=start_id)
            self._save_activation(token["workspace_id"], attempt_id, item)

    def stage_evidence(self, workspace_id, attempt_id, nonce, evidence, now):
        # This is internal evidence retention, NOT an authoritative completion.
        # A fenced child can preserve its correlated native evidence for review.
        with self.transaction():
            item = self._activation(workspace_id, attempt_id)
            if not item or item["nonce"] != nonce:
                raise StaleAttempt("activation evidence token is stale")
            if item["evidence"] is not None and item["evidence"] != evidence:
                raise Conflict("activation evidence cannot be overwritten")
            item.update(evidence=evidence, evidence_at=now)
            self._save_activation(workspace_id, attempt_id, item)

    def staged(self, workspace_id, attempt_id):
        if not self.enabled():
            return None
        return self._activation(workspace_id, attempt_id)

    def waiter_open(self, observation, *, now, ttl):
        with self.transaction():
            token = {"database_id": self.database_id, "workspace_id": observation["workspace_id"],
                     "id": str(uuid4()), "nonce": str(uuid4())}
            item = {**token, "message_id": observation["message_id"], "observation_id": observation["id"],
                    "observer": observation["observer"], "condition": observation["condition"],
                    "deadline": observation["deadline"], "lease_until": min(until(now, ttl), observation["deadline"]),
                    "heartbeat_at": now, "state": "waiting"}
            self.connection.execute("INSERT INTO communication_waiters VALUES(?,?,?,?,?)", (item["workspace_id"], item["id"], item["message_id"], item["observation_id"], json.dumps(item)))
            return token

    def _waiter(self, token):
        row = self.connection.execute("SELECT data FROM communication_waiters WHERE workspace_id=? AND id=?", (token["workspace_id"], token["id"])).fetchone()
        item = json.loads(row[0]) if row else None
        if not item or any(item.get(k) != token.get(k) for k in ("database_id", "workspace_id", "id", "nonce")):
            raise StaleAttempt("waiter token is stale")
        return item

    def waiter_renew(self, token, *, now, ttl):
        with self.transaction():
            item = self._waiter(token)
            if item["state"] != "waiting" or item["lease_until"] <= now:
                raise StaleAttempt("expired waiter cannot regain ownership")
            item.update(heartbeat_at=now, lease_until=min(until(now, ttl), item["deadline"]))
            self.connection.execute("UPDATE communication_waiters SET data=? WHERE workspace_id=? AND id=?", (json.dumps(item), item["workspace_id"], item["id"]))

    def waiter_close(self, token, now):
        # Capability-scoped cleanup never reloads message bodies or current policy.
        with self.transaction():
            item = self._waiter(token)
            item.update(state="closed", lease_until=min(now, item["lease_until"]))
            self.connection.execute("UPDATE communication_waiters SET data=? WHERE workspace_id=? AND id=?", (json.dumps(item), item["workspace_id"], item["id"]))

    def waiters(self, workspace_id, message_id, now):
        if not self.enabled():
            return []
        output = []
        for (raw,) in self.connection.execute("SELECT data FROM communication_waiters WHERE workspace_id=? AND message_id=? ORDER BY id", (workspace_id, message_id)):
            item = json.loads(raw)
            output.append({"state": "active" if item["state"] == "waiting" and item["lease_until"] > now else "expired" if item["state"] == "waiting" else "closed",
                           "condition": item["condition"], "deadline": item["deadline"], "sampledAt": now,
                           "leaseUntil": item["lease_until"]})
        return output

    def waiter_candidates(self, workspace_id, message_id, *, limit=101):
        """Internal, bounded facts for observation-aware summaries; never capabilities."""
        if type(limit) is not int or not 1 <= limit <= 1001:
            raise CommunicationError("waiter candidate limit must be 1..1001")
        if not self.enabled():
            return []
        fields = ("database_id", "workspace_id", "message_id", "observation_id",
                  "observer", "condition", "deadline", "lease_until", "heartbeat_at", "state")
        output = []
        for identity, observation_id, raw in self.connection.execute(
                "SELECT id,observation_id,data FROM communication_waiters "
                "WHERE workspace_id=? AND message_id=? "
                "AND CASE WHEN json_valid(data) THEN COALESCE(json_extract(data,'$.state'),'unknown') "
                "ELSE 'unknown' END!='closed' "
                "ORDER BY rowid DESC LIMIT ?", (workspace_id, message_id, limit)):
            try:
                item = json.loads(raw)
            except json.JSONDecodeError as error:
                raise CommunicationError("invalid waiter association") from error
            if not isinstance(item, dict) or any(item.get(key) != value for key, value in (
                    ("id", identity), ("workspace_id", workspace_id),
                    ("message_id", message_id), ("observation_id", observation_id))):
                raise CommunicationError("inconsistent waiter association")
            output.append({key: item.get(key) for key in fields})
        return output

    def cleanup(self, now, *, limit=100):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise CommunicationError("cleanup limit must be 1..1000")
        with self.transaction():
            # Retain recent expired samples for diagnostics, but bound abandoned rows.
            cutoff = stamp(datetime.fromisoformat(now) - timedelta(hours=1))
            count = self.connection.execute("DELETE FROM communication_waiters WHERE rowid IN (SELECT rowid FROM communication_waiters WHERE json_extract(data,'$.lease_until')<? ORDER BY rowid LIMIT ?)", (cutoff, limit)).rowcount
            # Keep unknown/unfinished evidence for reconciliation. Delete only
            # old, settled operational associations; business history is untouched.
            count += self.connection.execute("DELETE FROM communication_activations WHERE rowid IN (SELECT a.rowid FROM communication_activations a JOIN communication_attempts t ON t.workspace_id=a.workspace_id AND t.id=a.attempt_id WHERE json_extract(a.data,'$.registered_at')<? AND json_extract(t.data,'$.phase') IN ('finished','failed','released_before_start','expired_before_start') LIMIT ?)", (cutoff, limit)).rowcount
            count += self.connection.execute("DELETE FROM communication_wake_intents WHERE rowid IN (SELECT i.rowid FROM communication_wake_intents i WHERE dirty=0 AND next_check<? AND NOT EXISTS(SELECT 1 FROM communication_deliveries d WHERE d.workspace_id=i.workspace_id AND d.session_key=i.session_key AND d.schedule IN ('pending','leased','unknown')) LIMIT ?)", (cutoff, limit)).rowcount
            return count
