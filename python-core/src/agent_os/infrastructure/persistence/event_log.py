from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import json
import sqlite3
from pathlib import Path
from typing import Mapping, Protocol, Self

from agent_os.domain.value_objects.identifiers import (
    PlatformEventId,
    PlatformRunSessionId,
    WorkspaceId,
)


class PlatformEventKind(StrEnum):
    """Append-only platform event families persisted to the local event log."""

    WORKSPACE_CHANGED = "workspace.changed"
    CONTEXT_UPDATE_APPENDED = "context.update_appended"
    TASK_CHANGED = "task.changed"
    ISSUE_CHANGED = "issue.changed"
    AGENT_REGISTRATION_CHANGED = "agent_registration.changed"
    AGENT_INVOCATION_RECORDED = "agent_invocation.recorded"
    FILE_OPERATION_RECORDED = "file_operation.recorded"
    RUN_SESSION_CHANGED = "run_session.changed"
    CONVERSATION_CHANGED = "conversation.changed"
    CONVERSATION_MESSAGE_APPENDED = "conversation.message_appended"
    AGENT_ACTIVATION_CHANGED = "agent_activation.changed"
    DELEGATED_WAKE_GRANT_CHANGED = "delegated_wake_grant.changed"
    PROJECT_DIRECTORY_COORDINATION_CHANGED = "project_directory_coordination.changed"
    AGENT_EXCHANGE_REQUEST_CHANGED = "agent_exchange_request.changed"
    AGENT_EXCHANGE_THREAD_CHANGED = "agent_exchange_thread.changed"
    AGENT_EXCHANGE_REQUEST_POLICY_CHANGED = "agent_exchange_request_policy.changed"
    AGENT_WAKE_DELIVERY_RECORDED = "agent_wake.delivery_recorded"
    AGENT_ENDPOINT_CHANGED = "agent_endpoint.changed"
    AGENT_DISPATCH_CHANGED = "agent_dispatch.changed"
    AGENT_DISPATCH_LEASE_CHANGED = "agent_dispatch_lease.changed"
    AGENT_DISPATCH_DAEMON_LIVENESS_CHANGED = (
        "agent_dispatch_daemon_liveness.changed"
    )
    CLAUDE_REGISTERED_SESSION_HANDLE_CHANGED = (
        "claude_registered_session_handle.changed"
    )
    CLAUDE_REGISTERED_SESSION_ACTIVATION_RECORDED = (
        "claude_registered_session_activation.recorded"
    )
    CODEX_REGISTERED_SESSION_HANDLE_CHANGED = (
        "codex_registered_session_handle.changed"
    )
    CODEX_REGISTERED_SESSION_ACTIVATION_RECORDED = (
        "codex_registered_session_activation.recorded"
    )
    HERMES_REGISTERED_SESSION_HANDLE_CHANGED = (
        "hermes_registered_session_handle.changed"
    )
    HERMES_REGISTERED_SESSION_ACTIVATION_RECORDED = (
        "hermes_registered_session_activation.recorded"
    )


SQLITE_PLATFORM_EVENT_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS platform_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    workspace_id TEXT NOT NULL,
    session_id TEXT,
    event_kind TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    correlation_id TEXT,
    idempotency_key TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_platform_events_workspace_sequence
    ON platform_events(workspace_id, sequence);

CREATE INDEX IF NOT EXISTS idx_platform_events_session_sequence
    ON platform_events(session_id, sequence)
    WHERE session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_platform_events_aggregate_sequence
    ON platform_events(aggregate_type, aggregate_id, sequence);
"""


PLATFORM_EVENT_INSERT_COLUMNS = (
    "event_id",
    "workspace_id",
    "session_id",
    "event_kind",
    "aggregate_type",
    "aggregate_id",
    "occurred_at",
    "correlation_id",
    "idempotency_key",
    "payload_json",
    "metadata_json",
)


PLATFORM_EVENT_SELECT_COLUMNS = ("sequence", *PLATFORM_EVENT_INSERT_COLUMNS)


SQLITE_PLATFORM_EVENT_INSERT_SQL = (
    f"INSERT INTO platform_events ({', '.join(PLATFORM_EVENT_INSERT_COLUMNS)}) "
    f"VALUES ({', '.join(f':{column}' for column in PLATFORM_EVENT_INSERT_COLUMNS)})"
)


SQLITE_PLATFORM_EVENT_LIST_WORKSPACE_SQL = (
    f"SELECT {', '.join(PLATFORM_EVENT_SELECT_COLUMNS)} "
    "FROM platform_events WHERE workspace_id = ? ORDER BY sequence"
)


SQLITE_PLATFORM_EVENT_LIST_SESSION_SQL = (
    f"SELECT {', '.join(PLATFORM_EVENT_SELECT_COLUMNS)} "
    "FROM platform_events "
    "WHERE workspace_id = ? AND session_id = ? "
    "ORDER BY sequence"
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


def _require_utc_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")


def _stable_json(value: Mapping[str, object]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _load_mapping_json(value: object, field_name: str) -> Mapping[str, object]:
    loaded = json.loads(str(value))
    if not isinstance(loaded, dict):
        raise ValueError(f"{field_name} must decode to a JSON object.")
    return loaded


@dataclass(frozen=True, slots=True)
class PlatformEventRecord:
    """Record contract for append-only platform events before SQLite insertion."""

    event_id: PlatformEventId
    workspace_id: WorkspaceId
    event_kind: PlatformEventKind
    aggregate_type: str
    aggregate_id: str
    occurred_at: datetime
    session_id: PlatformRunSessionId | None = None
    correlation_id: str | None = None
    idempotency_key: str | None = None
    payload: Mapping[str, object] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.event_id.value, "event_id")
        _require_non_empty(self.workspace_id.value, "workspace_id")
        _require_non_empty(self.aggregate_type, "aggregate_type")
        _require_non_empty(self.aggregate_id, "aggregate_id")
        _require_utc_aware(self.occurred_at, "occurred_at")

        if self.session_id is not None:
            _require_non_empty(self.session_id.value, "session_id")
        if self.correlation_id is not None:
            _require_non_empty(self.correlation_id, "correlation_id")
        if self.idempotency_key is not None:
            _require_non_empty(self.idempotency_key, "idempotency_key")

        _stable_json(self.payload)
        _stable_json(self.metadata)

    @classmethod
    def create(
        cls,
        *,
        workspace_id: WorkspaceId,
        event_kind: PlatformEventKind,
        aggregate_type: str,
        aggregate_id: str,
        event_id: PlatformEventId | None = None,
        occurred_at: datetime | None = None,
        session_id: PlatformRunSessionId | None = None,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
        payload: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> "PlatformEventRecord":
        return cls(
            event_id=event_id or PlatformEventId.new(),
            workspace_id=workspace_id,
            event_kind=event_kind,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            occurred_at=occurred_at or _utc_now(),
            session_id=session_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload=dict(payload or {}),
            metadata=dict(metadata or {}),
        )

    def to_sqlite_row(self) -> Mapping[str, object | None]:
        """Return the non-sequence columns for insertion into `platform_events`."""

        return {
            "event_id": self.event_id.value,
            "workspace_id": self.workspace_id.value,
            "session_id": self.session_id.value if self.session_id is not None else None,
            "event_kind": self.event_kind.value,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "occurred_at": self.occurred_at.isoformat(),
            "correlation_id": self.correlation_id,
            "idempotency_key": self.idempotency_key,
            "payload_json": _stable_json(self.payload),
            "metadata_json": _stable_json(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class PlatformEventLogEntry:
    """Persisted platform event row with its SQLite sequence."""

    sequence: int
    record: PlatformEventRecord

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("sequence must be a positive integer.")

    @classmethod
    def from_sqlite_row(cls, row: Mapping[str, object | None]) -> "PlatformEventLogEntry":
        session_id = row["session_id"]
        return cls(
            sequence=int(row["sequence"] or 0),
            record=PlatformEventRecord.create(
                event_id=PlatformEventId(str(row["event_id"])),
                workspace_id=WorkspaceId(str(row["workspace_id"])),
                session_id=(
                    PlatformRunSessionId(str(session_id))
                    if session_id is not None
                    else None
                ),
                event_kind=PlatformEventKind(str(row["event_kind"])),
                aggregate_type=str(row["aggregate_type"]),
                aggregate_id=str(row["aggregate_id"]),
                occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
                correlation_id=(
                    str(row["correlation_id"])
                    if row["correlation_id"] is not None
                    else None
                ),
                idempotency_key=(
                    str(row["idempotency_key"])
                    if row["idempotency_key"] is not None
                    else None
                ),
                payload=_load_mapping_json(row["payload_json"], "payload_json"),
                metadata=_load_mapping_json(row["metadata_json"], "metadata_json"),
            ),
        )


class PlatformEventLogPort(Protocol):
    """Minimal append-only persistence boundary for platform events."""

    def initialize(self) -> None:
        ...

    def append(self, record: PlatformEventRecord) -> int:
        ...

    def list_workspace_events(self, workspace_id: WorkspaceId) -> tuple[PlatformEventLogEntry, ...]:
        ...

    def list_session_events(
        self,
        *,
        workspace_id: WorkspaceId,
        session_id: PlatformRunSessionId,
    ) -> tuple[PlatformEventLogEntry, ...]:
        ...


@dataclass(slots=True)
class SqlitePlatformEventLog(PlatformEventLogPort):
    """SQLite-backed append-only platform event log."""

    connection: sqlite3.Connection

    @classmethod
    def connect(cls, database: str | Path) -> Self:
        return cls(sqlite3.connect(database))

    def initialize(self) -> None:
        self.connection.executescript(SQLITE_PLATFORM_EVENT_LOG_SCHEMA)
        self.connection.commit()

    def append(self, record: PlatformEventRecord) -> int:
        cursor = self.connection.execute(
            SQLITE_PLATFORM_EVENT_INSERT_SQL,
            record.to_sqlite_row(),
        )
        self.connection.commit()
        sequence = cursor.lastrowid
        if sequence is None:
            raise RuntimeError("SQLite did not return a platform event sequence.")
        return int(sequence)

    def list_workspace_events(self, workspace_id: WorkspaceId) -> tuple[PlatformEventLogEntry, ...]:
        _require_non_empty(workspace_id.value, "workspace_id")
        rows = self.connection.execute(
            SQLITE_PLATFORM_EVENT_LIST_WORKSPACE_SQL,
            (workspace_id.value,),
        ).fetchall()
        return tuple(
            PlatformEventLogEntry.from_sqlite_row(
                dict(zip(PLATFORM_EVENT_SELECT_COLUMNS, row, strict=True))
            )
            for row in rows
        )

    def list_session_events(
        self,
        *,
        workspace_id: WorkspaceId,
        session_id: PlatformRunSessionId,
    ) -> tuple[PlatformEventLogEntry, ...]:
        _require_non_empty(workspace_id.value, "workspace_id")
        _require_non_empty(session_id.value, "session_id")
        rows = self.connection.execute(
            SQLITE_PLATFORM_EVENT_LIST_SESSION_SQL,
            (workspace_id.value, session_id.value),
        ).fetchall()
        return tuple(
            PlatformEventLogEntry.from_sqlite_row(
                dict(zip(PLATFORM_EVENT_SELECT_COLUMNS, row, strict=True))
            )
            for row in rows
        )
