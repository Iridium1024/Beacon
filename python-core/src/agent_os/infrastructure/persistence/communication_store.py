"""Opt-in communication ledger and projections in the existing workspace SQLite.

Nothing imports or initializes this from production composition in C1-A.
The ledger owns its commits; legacy platform_events append semantics stay intact.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from hashlib import sha256
import json
import sqlite3
from typing import Callable
from uuid import uuid4

from agent_os.domain.entities.communication import CommunicationError, canonical


SCHEMA_VERSION = 2
SCHEMA = """
CREATE TABLE IF NOT EXISTS communication_schema (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL,
    database_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS communication_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL,
    actor TEXT NOT NULL, kind TEXT NOT NULL, occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS communication_events_workspace ON communication_events(workspace_id, sequence);
CREATE TABLE IF NOT EXISTS communication_threads (
    workspace_id TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL, source_sequence INTEGER NOT NULL,
    PRIMARY KEY(workspace_id,id)
);
CREATE TABLE IF NOT EXISTS communication_messages (
    workspace_id TEXT NOT NULL, id TEXT NOT NULL, thread_id TEXT NOT NULL,
    data TEXT NOT NULL, source_sequence INTEGER NOT NULL,
    PRIMARY KEY(workspace_id,id),
    FOREIGN KEY(workspace_id,thread_id) REFERENCES communication_threads(workspace_id,id)
);
CREATE INDEX IF NOT EXISTS communication_messages_thread
    ON communication_messages(workspace_id,thread_id,source_sequence,id);
CREATE INDEX IF NOT EXISTS communication_messages_parent
    ON communication_messages(workspace_id,json_extract(data,'$.legacy_parent_request_id'));
CREATE TABLE IF NOT EXISTS communication_deliveries (
    workspace_id TEXT NOT NULL, id TEXT NOT NULL, message_id TEXT NOT NULL, target TEXT NOT NULL, session_key TEXT NOT NULL,
    schedule TEXT NOT NULL, data TEXT NOT NULL, source_sequence INTEGER NOT NULL,
    PRIMARY KEY(workspace_id,id), UNIQUE(workspace_id,message_id,target),
    FOREIGN KEY(workspace_id,message_id) REFERENCES communication_messages(workspace_id,id)
);
CREATE INDEX IF NOT EXISTS communication_pending ON communication_deliveries(workspace_id,schedule,source_sequence);
CREATE INDEX IF NOT EXISTS communication_pending_target
    ON communication_deliveries(workspace_id,schedule,target,source_sequence);
CREATE TABLE IF NOT EXISTS communication_receipts (
    workspace_id TEXT NOT NULL, id TEXT NOT NULL, message_id TEXT NOT NULL,
    target TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL, source_sequence INTEGER NOT NULL,
    PRIMARY KEY(workspace_id,id),
    FOREIGN KEY(workspace_id,message_id,target) REFERENCES communication_deliveries(workspace_id,message_id,target)
);
CREATE INDEX IF NOT EXISTS communication_receipts_message ON communication_receipts(workspace_id,message_id,source_sequence);
CREATE UNIQUE INDEX IF NOT EXISTS communication_one_ack ON communication_receipts(workspace_id,message_id,target) WHERE kind='ack';
CREATE UNIQUE INDEX IF NOT EXISTS communication_one_final ON communication_receipts(workspace_id,message_id,target) WHERE kind IN ('final','reject');
CREATE TABLE IF NOT EXISTS communication_attempts (
    workspace_id TEXT NOT NULL, id TEXT NOT NULL, message_id TEXT NOT NULL,
    data TEXT NOT NULL, source_sequence INTEGER NOT NULL,
    PRIMARY KEY(workspace_id,id),
    FOREIGN KEY(workspace_id,message_id) REFERENCES communication_messages(workspace_id,id)
);
CREATE TABLE IF NOT EXISTS communication_slots (
    workspace_id TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL, source_sequence INTEGER NOT NULL,
    PRIMARY KEY(workspace_id,id)
);
CREATE TABLE IF NOT EXISTS communication_observations (
    workspace_id TEXT NOT NULL, id TEXT NOT NULL, message_id TEXT NOT NULL,
    data TEXT NOT NULL, source_sequence INTEGER NOT NULL,
    PRIMARY KEY(workspace_id,id),
    FOREIGN KEY(workspace_id,message_id) REFERENCES communication_messages(workspace_id,id)
);
CREATE TABLE IF NOT EXISTS communication_idempotency (
    workspace_id TEXT NOT NULL, actor TEXT NOT NULL, operation TEXT NOT NULL, key TEXT NOT NULL,
    data TEXT NOT NULL, source_sequence INTEGER NOT NULL,
    PRIMARY KEY(workspace_id,actor,operation,key)
);
CREATE TABLE IF NOT EXISTS communication_inbox (
    sequence INTEGER NOT NULL, workspace_id TEXT NOT NULL, viewer TEXT NOT NULL,
    message_id TEXT NOT NULL, kind TEXT NOT NULL, receipt_id TEXT,
    PRIMARY KEY(sequence,viewer,message_id,kind),
    FOREIGN KEY(workspace_id,message_id) REFERENCES communication_messages(workspace_id,id)
);
CREATE INDEX IF NOT EXISTS communication_inbox_cursor ON communication_inbox(workspace_id,viewer,sequence);
CREATE TABLE IF NOT EXISTS communication_modes (
    workspace_id TEXT NOT NULL, id TEXT NOT NULL, mode TEXT NOT NULL CHECK(mode='core'),
    data TEXT NOT NULL, source_sequence INTEGER NOT NULL, PRIMARY KEY(workspace_id,id)
);
CREATE TABLE IF NOT EXISTS communication_mappings (
    workspace_id TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL,
    legacy_id TEXT NOT NULL, legacy_sequence INTEGER NOT NULL,
    data TEXT NOT NULL, source_sequence INTEGER NOT NULL,
    PRIMARY KEY(workspace_id,id), UNIQUE(workspace_id,kind,legacy_id,legacy_sequence)
);
CREATE INDEX IF NOT EXISTS communication_mapping_lookup
    ON communication_mappings(workspace_id,kind,legacy_id);
CREATE INDEX IF NOT EXISTS communication_slots_expiry
    ON communication_slots(workspace_id,json_extract(data,'$.state'),json_extract(data,'$.lease_until'));
"""

ENTITIES = {
    "threads": (), "messages": ("thread_id",),
    "deliveries": ("message_id", "target", "session_key", "schedule"),
    "receipts": ("message_id", "target", "kind"),
    "attempts": ("message_id",), "slots": (), "observations": ("message_id",),
    "modes": ("mode",), "mappings": ("kind", "legacy_id", "legacy_sequence"),
}

# An explicitly enabled, optional representation extension. Core schema 2 and
# its default read/write behavior remain valid without these tables.
SHORT_ENTITIES = {
    "short_refs": ("kind", "code", "object_id", "number"),
    "message_contexts": (), "ref_modes": (),
}
SHORT_SCHEMA_VERSION = 1
SHORT_SCHEMA = """
CREATE TABLE IF NOT EXISTS communication_short_schema (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS communication_short_refs (
    workspace_id TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL,
    code TEXT NOT NULL, object_id TEXT NOT NULL, number INTEGER NOT NULL CHECK(number>0),
    data TEXT NOT NULL, source_sequence INTEGER NOT NULL,
    PRIMARY KEY(workspace_id,id), UNIQUE(workspace_id,kind,code),
    UNIQUE(workspace_id,kind,object_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS communication_workspace_short_code
    ON communication_short_refs(code) WHERE kind='workspace';
CREATE TABLE IF NOT EXISTS communication_message_contexts (
    workspace_id TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL,
    source_sequence INTEGER NOT NULL, PRIMARY KEY(workspace_id,id)
);
CREATE TABLE IF NOT EXISTS communication_ref_modes (
    workspace_id TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL,
    source_sequence INTEGER NOT NULL, PRIMARY KEY(workspace_id,id)
);
"""


class SqliteCommunicationRepository:
    def __init__(self, connection: sqlite3.Connection, *, fault: Callable[[str], None] | None = None):
        if connection.in_transaction:
            raise CommunicationError("repository requires a connection without an active transaction")
        self.connection = connection
        self.connection.execute("PRAGMA foreign_keys=ON")
        # Respect the connection owner's configured wait bound. sqlite3's
        # default remains 5s; operational runtime connections explicitly use
        # 100ms. A read-only repository assembly must not reset that policy.
        self.fault = fault or (lambda _: None)
        self._owns_write = False
        self.database_id = ""
        self.schema_version = 0
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='communication_schema'"
        ).fetchone()
        if row:
            self._load_version()

    def _load_version(self) -> None:
        row = self.connection.execute("SELECT version,database_id FROM communication_schema WHERE singleton=1").fetchone()
        if row is None or row[0] not in {1, SCHEMA_VERSION}:
            raise CommunicationError("unsupported communication schema version")
        self.schema_version = row[0]
        self.database_id = row[1]

    def initialize(self) -> None:
        """Explicit opt-in only; caller supplies an existing platform database."""
        if self.connection.in_transaction:
            raise CommunicationError("initialize cannot commit a caller transaction")
        if not self.connection.execute("SELECT 1 FROM sqlite_master WHERE name='platform_workspace_state'").fetchone():
            raise CommunicationError("initialize requires the existing platform schema")
        if self.database_id and self.schema_version == SCHEMA_VERSION:
            self._load_version()
            self.connection.execute("CREATE INDEX IF NOT EXISTS communication_messages_thread "
                                    "ON communication_messages(workspace_id,thread_id,source_sequence,id)")
            self.connection.execute("CREATE INDEX IF NOT EXISTS communication_messages_parent "
                                    "ON communication_messages(workspace_id,json_extract(data,'$.legacy_parent_request_id'))")
            self.connection.execute("CREATE INDEX IF NOT EXISTS communication_pending_target "
                                    "ON communication_deliveries(workspace_id,schedule,target,source_sequence)")
            return
        # executescript can commit an existing transaction: reject it above and
        # place BEGIN/COMMIT inside the script, including version initialization.
        identity = str(uuid4())
        try:
            self.connection.executescript(
                "BEGIN IMMEDIATE;\n" + SCHEMA +
                f"\nINSERT OR IGNORE INTO communication_schema VALUES(1,{SCHEMA_VERSION},'{identity}');"
                f"\nUPDATE communication_schema SET version={SCHEMA_VERSION} WHERE singleton=1;\nCOMMIT;"
            )
        except BaseException:
            self.connection.rollback()
            raise
        self._load_version()

    @contextmanager
    def transaction(self, *, write: bool = True):
        if not self.database_id or self.schema_version != SCHEMA_VERSION:
            raise CommunicationError("communication schema has not been explicitly initialized")
        if self.connection.in_transaction:
            raise CommunicationError("nested/caller transaction is not owned by communication UoW")
        self.connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        self._owns_write = write
        try:
            yield self
            if not self.connection.in_transaction:
                raise CommunicationError("transaction was committed outside communication UoW")
            if write:
                self.fault("before_commit")
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise
        finally:
            self._owns_write = False

    def get(self, entity: str, workspace_id: str, identity: str) -> dict | None:
        if entity not in {*ENTITIES, *SHORT_ENTITIES}:
            raise CommunicationError("unknown entity")
        if entity in SHORT_ENTITIES and not self.short_extension():
            return None
        row = self.connection.execute(
            f"SELECT data FROM communication_{entity} WHERE workspace_id=? AND id=?",
            (workspace_id, identity),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def receipts(self, workspace_id: str, message_id: str) -> list[dict]:
        return [json.loads(r[0]) for r in self.connection.execute(
            "SELECT data FROM communication_receipts WHERE workspace_id=? AND message_id=? ORDER BY source_sequence",
            (workspace_id, message_id),
        )]

    def sequence(self, entity: str, workspace_id: str, identity: str) -> int:
        if entity not in {*ENTITIES, *SHORT_ENTITIES}:
            raise CommunicationError("unknown entity")
        row = self.connection.execute(
            f"SELECT source_sequence FROM communication_{entity} WHERE workspace_id=? AND id=?",
            (workspace_id, identity),
        ).fetchone()
        if row is None:
            raise CommunicationError("missing projection sequence")
        return row[0]

    def idempotency(self, workspace_id: str, actor: str, operation: str, key: str) -> dict | None:
        row = self.connection.execute(
            "SELECT data FROM communication_idempotency WHERE workspace_id=? AND actor=? AND operation=? AND key=?",
            (workspace_id, actor, operation, key),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def append(self, workspace_id: str, actor: str, kind: str, at: str,
               changes: dict, notices: tuple[dict, ...] = ()) -> int:
        if not self._owns_write or not self.connection.in_transaction:
            raise CommunicationError("append requires an owned transaction")
        payload = {"changes": changes, "notices": notices}
        sequence = self.connection.execute(
            "INSERT INTO communication_events(workspace_id,actor,kind,occurred_at,payload_json) VALUES(?,?,?,?,?)",
            (workspace_id, actor, kind, at, canonical(payload)),
        ).lastrowid
        self.fault("after_event")
        self._project(workspace_id, sequence, payload)
        self.fault("after_projection")
        return sequence

    def _project(self, workspace_id: str, sequence: int, payload: dict) -> None:
        changes = payload["changes"]
        if set(changes) - {*ENTITIES, *SHORT_ENTITIES, "idempotency"}:
            raise CommunicationError("unknown event projection")
        if set(changes) & SHORT_ENTITIES.keys() and not self.short_extension():
            raise CommunicationError("short reference extension has not been explicitly initialized")
        for entity, extra in {**ENTITIES, **SHORT_ENTITIES}.items():
            for obj in changes.get(entity, ()):
                if obj["workspace_id"] != workspace_id:
                    raise CommunicationError("cross-workspace event projection")
                columns = ["workspace_id", "id", *extra, "data", "source_sequence"]
                values = [workspace_id, obj["id"], *(obj[k] for k in extra), canonical(obj), sequence]
                sql = f"INSERT INTO communication_{entity}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})"
                if entity not in {"messages", "receipts", "short_refs", "message_contexts"}:
                    sql += " ON CONFLICT(workspace_id,id) DO UPDATE SET " + ",".join(
                        f"{c}=excluded.{c}" for c in columns[2:]
                    )
                self.connection.execute(sql, values)
                self.fault("after_" + entity)
        for obj in changes.get("idempotency", ()):
            self.connection.execute(
                "INSERT INTO communication_idempotency VALUES(?,?,?,?,?,?)",
                (workspace_id, obj["actor"], obj["operation"], obj["key"], canonical(obj), sequence),
            )
        for notice in payload["notices"]:
            self.connection.execute(
                "INSERT INTO communication_inbox VALUES(?,?,?,?,?,?)",
                (sequence, workspace_id, notice["viewer"], notice["message_id"], notice["kind"], notice.get("receipt_id")),
            )

    def high_water(self) -> int:
        return self.connection.execute("SELECT COALESCE(MAX(sequence),0) FROM communication_events").fetchone()[0]

    def workspace_high_water(self, workspace_id: str) -> int:
        return self.connection.execute(
            "SELECT COALESCE(MAX(sequence),0) FROM communication_events WHERE workspace_id=?",
            (workspace_id,)
        ).fetchone()[0]

    def mode(self, workspace_id: str) -> str:
        """A missing marker remains legacy; this read never initializes or migrates."""
        if self.schema_version < 2:
            return "legacy"
        row = self.connection.execute(
            "SELECT mode FROM communication_modes WHERE workspace_id=? AND id=?", (workspace_id, workspace_id)
        ).fetchone()
        return row[0] if row else "legacy"

    def mappings_for_legacy(self, workspace_id: str, kind: str, legacy_id: str) -> list[dict]:
        if self.schema_version < 2:
            return []
        return [json.loads(row[0]) for row in self.connection.execute(
            "SELECT data FROM communication_mappings WHERE workspace_id=? AND kind=? AND legacy_id=? "
            "ORDER BY legacy_sequence", (workspace_id, kind, legacy_id)
        )]

    def thread_messages(self, workspace_id: str, thread_id: str) -> list[dict]:
        return [json.loads(row[0]) for row in self.connection.execute(
            "SELECT data FROM communication_messages WHERE workspace_id=? AND thread_id=? "
            "ORDER BY source_sequence,id", (workspace_id, thread_id)
        )]

    def workspace_items(self, entity: str, workspace_id: str) -> list[dict]:
        if entity not in {"messages", "threads", "deliveries", "attempts", *SHORT_ENTITIES}:
            raise CommunicationError("unsupported communication list projection")
        if entity in SHORT_ENTITIES and not self.short_extension():
            return []
        return [json.loads(row[0]) for row in self.connection.execute(
            f"SELECT data FROM communication_{entity} WHERE workspace_id=? "
            "ORDER BY source_sequence,id", (workspace_id,)
        )]

    def short_extension(self) -> bool:
        """Capability read only: never create tables or upgrade a database."""
        if not self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='communication_short_schema'"
        ).fetchone():
            return False
        row = self.connection.execute(
            "SELECT version FROM communication_short_schema WHERE singleton=1"
        ).fetchone()
        if row is None or row[0] != SHORT_SCHEMA_VERSION:
            raise CommunicationError("unsupported short reference schema version")
        return True

    def initialize_short_extension(self) -> None:
        """DDL belongs to an explicitly requested, owned write transaction."""
        if not self._owns_write or not self.connection.in_transaction:
            raise CommunicationError("short reference initialization requires an owned write")
        if self.short_extension():
            return
        # executescript would commit the UoW. These statements have no triggers
        # or embedded semicolons, so execute each within the current transaction.
        for statement in SHORT_SCHEMA.split(";"):
            if statement.strip():
                self.connection.execute(statement)
        self.connection.execute("INSERT INTO communication_short_schema VALUES(1,?)", (SHORT_SCHEMA_VERSION,))
        self.fault("after_short_schema")

    def short_ref(self, workspace_id: str, kind: str, *, code: str | None = None,
                  object_id: str | None = None) -> dict | None:
        if not self.short_extension():
            return None
        if (code is None) == (object_id is None):
            raise CommunicationError("provide one short code or full object identity")
        field, value = ("code", code) if code is not None else ("object_id", object_id)
        row = self.connection.execute(
            f"SELECT data FROM communication_short_refs WHERE workspace_id=? AND kind=? AND {field}=?",
            (workspace_id, kind, value)).fetchone()
        return json.loads(row[0]) if row else None

    def next_short_number(self, workspace_id: str, kind: str, prefix: str) -> int:
        if not self._owns_write or not self.connection.in_transaction or not self.short_extension():
            raise CommunicationError("short number allocation requires an owned initialized write")
        if kind == "workspace":
            query, params = "SELECT COALESCE(MAX(number),0)+1 FROM communication_short_refs WHERE kind='workspace'", ()
        else:
            query = ("SELECT COALESCE(MAX(number),0)+1 FROM communication_short_refs "
                     "WHERE workspace_id=? AND kind=? AND code GLOB ?")
            params = (workspace_id, kind, prefix + "[0-9]*")
        return self.connection.execute(query, params).fetchone()[0]

    def require_short_write(self) -> None:
        if not self._owns_write or not self.connection.in_transaction or not self.short_extension():
            raise CommunicationError("short reference mutation/check requires an owned initialized write")

    def short_reference_backup(self, destination: str) -> dict:
        """Explicit, consistent SQLite backup; no caller transaction is committed."""
        if self.connection.in_transaction:
            raise CommunicationError("backup requires a connection outside a transaction")
        target = Path(destination).expanduser().resolve()
        source = self.connection.execute("PRAGMA database_list").fetchone()[2]
        if source and target == Path(source).resolve():
            raise CommunicationError("backup path must differ from the source database")
        if target.exists() or not target.parent.is_dir():
            raise CommunicationError("backup requires a new file in an existing directory")
        target.touch(exist_ok=False)
        try:
            backup = sqlite3.connect(target)
            try:
                self.connection.backup(backup)
            finally:
                backup.close()
            return {"path": str(target), "sha256": sha256(target.read_bytes()).hexdigest(),
                    "bytes": target.stat().st_size}
        except BaseException:
            target.unlink(missing_ok=True)
            raise

    def creation_sequence(self, entity: str, workspace_id: str, identity: str) -> int:
        if entity not in {*ENTITIES, *SHORT_ENTITIES}:
            raise CommunicationError("unknown entity")
        row = self.connection.execute(
            "SELECT MIN(e.sequence) FROM communication_events e, json_each(e.payload_json,?) item "
            "WHERE e.workspace_id=? AND json_extract(item.value,'$.id')=?",
            ("$.changes." + entity, workspace_id, identity)).fetchone()
        return row[0] or 0

    def console_events(self, workspace_id: str, *, after: int, limit: int) -> dict:
        """Read a bounded, body-free ledger page for the workspace console.

        This cursor is deliberately separate from the legacy platform-event
        ordinal and from the agent-scoped communication inbox cursor.
        """
        if after < 0 or limit < 1 or limit > 200:
            raise CommunicationError("invalid communication console page")
        with self.transaction(write=False):
            upper = self.connection.execute(
                "SELECT COALESCE(MAX(sequence),0) FROM communication_events "
                "WHERE workspace_id=?", (workspace_id,)
            ).fetchone()[0]
            if after > upper:
                raise CommunicationError("communication console cursor is ahead of this workspace")
            rows = self.connection.execute(
                "SELECT sequence,kind,occurred_at,payload_json FROM communication_events "
                "WHERE workspace_id=? AND sequence>? AND sequence<=? "
                "ORDER BY sequence LIMIT ?", (workspace_id, after, upper, limit + 1)
            ).fetchall()
            more = len(rows) > limit
            selected = rows[:limit]
            end = selected[-1][0] if more else upper
            events = []
            for sequence, kind, occurred_at, payload_json in selected:
                changes = json.loads(payload_json).get("changes", {})
                events.append({"communicationLedgerSequence": sequence,
                               "kind": kind, "occurredAt": occurred_at,
                               "messageCount": len(changes.get("messages", ())),
                               "receiptKinds": [receipt["kind"] for receipt in
                                                changes.get("receipts", ())]})
            return {"events": events,
                    "nextCursor": f"ledger:{end}", "hasMore": more,
                    "upper": upper}

    def child_messages(self, workspace_id: str, parent_request_id: str) -> list[dict]:
        return [json.loads(row[0]) for row in self.connection.execute(
            "SELECT data FROM communication_messages WHERE workspace_id=? "
            "AND json_extract(data,'$.legacy_parent_request_id')=? ORDER BY source_sequence,id",
            (workspace_id, parent_request_id)
        )]

    def pending(self, workspace_id: str, *, limit: int) -> list[dict]:
        return [json.loads(row[0]) for row in self.connection.execute(
            "SELECT data FROM communication_deliveries WHERE workspace_id=? AND schedule='pending' "
            "ORDER BY source_sequence LIMIT ?", (workspace_id, limit)
        )]

    def due(self, workspace_id: str, now: str, *, limit: int,
            target_agent_id: str | None = None) -> list[dict]:
        """Indexed, read-only candidate discovery; claim remains the authority."""
        target_filter = " AND target=?" if target_agent_id is not None else ""
        args = (workspace_id, target_agent_id, now, limit) if target_agent_id is not None else (workspace_id, now, limit)
        return [json.loads(row[0]) for row in self.connection.execute(
            "SELECT data FROM communication_deliveries WHERE workspace_id=? AND schedule='pending' "
            + target_filter + " AND (json_extract(data,'$.eligible_after') IS NULL "
            "OR json_extract(data,'$.eligible_after')<=?) "
            "ORDER BY source_sequence LIMIT ?", args
        )]

    def own_observations(self, workspace_id, message_id, observer, *, limit):
        return [json.loads(row[0]) for row in self.connection.execute(
            "SELECT data FROM communication_observations WHERE workspace_id=? AND message_id=? "
            "AND json_extract(data,'$.observer')=? ORDER BY source_sequence DESC LIMIT ?",
            (workspace_id,message_id,observer,limit))]

    def due_targets(self, workspace_id: str, now: str, *, after: str = "", limit: int = 20,
                    target_agent_id: str | None = None) -> list[dict]:
        """One eligible item per native key, keyset pagination avoids A-prefix starvation."""
        target = " AND target=?" if target_agent_id is not None else ""
        args = [workspace_id, after, now]
        if target_agent_id is not None:
            args.append(target_agent_id)
        args.append(limit)
        targets = self.connection.execute(
            "SELECT session_key FROM communication_deliveries "
            "WHERE workspace_id=? AND schedule='pending' AND session_key>? "
            "AND (json_extract(data,'$.eligible_after') IS NULL OR json_extract(data,'$.eligible_after')<=?)"
            + target + " GROUP BY session_key ORDER BY session_key LIMIT ?", args).fetchall()
        result = []
        for (session_key,) in targets:
            row = self.connection.execute(
                "SELECT data FROM communication_deliveries WHERE workspace_id=? AND session_key=? AND schedule='pending' "
                "AND (json_extract(data,'$.eligible_after') IS NULL OR json_extract(data,'$.eligible_after')<=?)"
                + target + " ORDER BY source_sequence,id LIMIT 1",
                [workspace_id, session_key, now, *([target_agent_id] if target_agent_id is not None else [])]).fetchone()
            if row:
                result.append(json.loads(row[0]))
        return result

    def expired_slots(self, workspace_id: str, now: str, *, limit: int) -> list[dict]:
        return [json.loads(row[0]) for row in self.connection.execute(
            "SELECT data FROM communication_slots WHERE workspace_id=? "
            "AND json_extract(data,'$.state')='active' AND json_extract(data,'$.lease_until')<=? "
            "ORDER BY json_extract(data,'$.lease_until') LIMIT ?", (workspace_id, now, limit)
        )]

    def inbox(self, workspace_id: str, agent_id: str, after: int, upper: int, limit: int) -> list[dict]:
        columns = ("sequence", "message_id", "kind", "receipt_id")
        return [dict(zip(columns, row)) for row in self.connection.execute(
            "SELECT sequence,message_id,kind,receipt_id FROM communication_inbox "
            "WHERE workspace_id=? AND viewer=? AND sequence>? AND sequence<=? ORDER BY sequence LIMIT ?",
            (workspace_id, agent_id, after, upper, limit),
        )]

    def rebuild(self) -> None:
        """Explicit maintenance while no live provider is owned; never called by reads."""
        with self.transaction():
            events = self.connection.execute(
                "SELECT sequence,workspace_id,payload_json FROM communication_events ORDER BY sequence"
            ).fetchall()
            tables = ("inbox", "idempotency", "observations", "slots", "attempts", "receipts", "deliveries", "messages", "threads", "mappings", "modes")
            if self.short_extension():
                tables += tuple(SHORT_ENTITIES)
            for table in tables:
                self.connection.execute(f"DELETE FROM communication_{table}")
            for sequence, workspace, payload in events:
                self._project(workspace, sequence, json.loads(payload))

    def projection_snapshot(self) -> dict:
        entities = (*ENTITIES, *SHORT_ENTITIES) if self.short_extension() else tuple(ENTITIES)
        return {entity: self.connection.execute(
            f"SELECT * FROM communication_{entity} ORDER BY 1,2"
        ).fetchall() for entity in (*entities, "idempotency", "inbox")}
