from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import sqlite3
from typing import Mapping, Protocol

from agent_os.domain.entities.invocation import (
    AgentInvocationRequest,
    AgentInvocationResult,
)
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextUpdateId,
    PlatformEventId,
    PlatformRunSessionId,
    TaskId,
    WorkspaceId,
)
from agent_os.infrastructure.persistence.event_log import (
    SQLITE_PLATFORM_EVENT_INSERT_SQL,
    PlatformEventKind,
    PlatformEventRecord,
)


PLATFORM_AGENT_INVOCATION_RECORD_TABLES = (
    "platform_agent_invocation_records",
)


AGENT_INVOCATION_RECORD_STATUSES = (
    "requested",
    "succeeded",
    "failed",
    "cancelled",
)


AGENT_INVOCATION_RECORD_COLUMNS = (
    "invocation_id",
    "workspace_id",
    "agent_id",
    "task_id",
    "source_event_sequence",
    "status",
    "instruction",
    "requested_capability",
    "idempotency_key",
    "correlation_id",
    "request_json",
    "result_json",
    "context_update_ids_json",
    "file_references_json",
    "metadata_json",
    "requested_at",
    "completed_at",
    "created_at",
    "updated_at",
)


AGENT_INVOCATION_RECORD_UPSERT_COLUMNS = AGENT_INVOCATION_RECORD_COLUMNS


AGENT_INVOCATION_RECORD_SELECT_COLUMNS = AGENT_INVOCATION_RECORD_COLUMNS


SQLITE_PLATFORM_AGENT_INVOCATION_RECORD_SCHEMA = """
CREATE TABLE IF NOT EXISTS platform_agent_invocation_records (
    invocation_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    task_id TEXT,
    source_event_sequence INTEGER NOT NULL,
    status TEXT NOT NULL,
    instruction TEXT NOT NULL,
    requested_capability TEXT,
    idempotency_key TEXT,
    correlation_id TEXT,
    request_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    context_update_ids_json TEXT NOT NULL DEFAULT '[]',
    file_references_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    requested_at TEXT NOT NULL,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (source_event_sequence >= 0),
    CHECK (status IN ('requested', 'succeeded', 'failed', 'cancelled')),
    CHECK (
        (status = 'requested' AND completed_at IS NULL)
        OR (status != 'requested' AND completed_at IS NOT NULL)
    ),
    FOREIGN KEY (workspace_id)
        REFERENCES platform_workspace_state(workspace_id)
        ON DELETE CASCADE,
    FOREIGN KEY (agent_id)
        REFERENCES platform_agent_registration_state(agent_id)
        ON DELETE CASCADE,
    FOREIGN KEY (task_id)
        REFERENCES platform_task_state(task_id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_platform_agent_invocation_records_workspace_status
    ON platform_agent_invocation_records(workspace_id, status);

CREATE INDEX IF NOT EXISTS idx_platform_agent_invocation_records_agent_status
    ON platform_agent_invocation_records(agent_id, status);

CREATE INDEX IF NOT EXISTS idx_platform_agent_invocation_records_task
    ON platform_agent_invocation_records(task_id)
    WHERE task_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_platform_agent_invocation_records_source_event
    ON platform_agent_invocation_records(source_event_sequence);

CREATE INDEX IF NOT EXISTS idx_platform_agent_invocation_records_correlation
    ON platform_agent_invocation_records(correlation_id)
    WHERE correlation_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_platform_agent_invocation_records_idempotency
    ON platform_agent_invocation_records(workspace_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
"""


SQLITE_AGENT_INVOCATION_RECORD_GET_SQL = (
    f"SELECT {', '.join(AGENT_INVOCATION_RECORD_SELECT_COLUMNS)} "
    "FROM platform_agent_invocation_records WHERE invocation_id = ?"
)


SQLITE_AGENT_INVOCATION_RECORD_GET_BY_WORKSPACE_IDEMPOTENCY_SQL = (
    f"SELECT {', '.join(AGENT_INVOCATION_RECORD_SELECT_COLUMNS)} "
    "FROM platform_agent_invocation_records "
    "WHERE workspace_id = ? AND idempotency_key = ?"
)


SQLITE_AGENT_INVOCATION_RECORD_LIST_BY_WORKSPACE_SQL = (
    f"SELECT {', '.join(AGENT_INVOCATION_RECORD_SELECT_COLUMNS)} "
    "FROM platform_agent_invocation_records "
    "WHERE workspace_id = ? "
    "AND (? IS NULL OR status = ?) "
    "AND (? IS NULL OR agent_id = ?) "
    "AND (? IS NULL OR task_id = ?) "
    "AND (? IS NULL OR idempotency_key = ?) "
    "ORDER BY source_event_sequence, invocation_id"
)


SQLITE_AGENT_INVOCATION_RECORD_UPSERT_SQL = f"""
INSERT INTO platform_agent_invocation_records ({", ".join(AGENT_INVOCATION_RECORD_UPSERT_COLUMNS)})
VALUES ({", ".join(f":{column}" for column in AGENT_INVOCATION_RECORD_UPSERT_COLUMNS)})
ON CONFLICT(invocation_id) DO UPDATE SET
    workspace_id = excluded.workspace_id,
    agent_id = excluded.agent_id,
    task_id = excluded.task_id,
    source_event_sequence = excluded.source_event_sequence,
    status = excluded.status,
    instruction = excluded.instruction,
    requested_capability = excluded.requested_capability,
    idempotency_key = excluded.idempotency_key,
    correlation_id = excluded.correlation_id,
    request_json = excluded.request_json,
    result_json = excluded.result_json,
    context_update_ids_json = excluded.context_update_ids_json,
    file_references_json = excluded.file_references_json,
    metadata_json = excluded.metadata_json,
    requested_at = excluded.requested_at,
    completed_at = excluded.completed_at,
    created_at = platform_agent_invocation_records.created_at,
    updated_at = excluded.updated_at;
"""


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


def _stable_json(value: Mapping[str, object]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _stable_json_list(value: tuple[object, ...]) -> str:
    return json.dumps(list(value), ensure_ascii=False, separators=(",", ":"))


def _load_mapping_json(value: object, field_name: str) -> Mapping[str, object]:
    loaded = json.loads(str(value))
    if not isinstance(loaded, dict):
        raise ValueError(f"{field_name} must decode to a JSON object.")
    return loaded


def _load_text_list_json(value: object, field_name: str) -> tuple[str, ...]:
    loaded = json.loads(str(value))
    if not isinstance(loaded, list):
        raise ValueError(f"{field_name} must decode to a JSON array.")
    for item in loaded:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} must contain only strings.")
    return tuple(loaded)


def _datetime_text(value: datetime) -> str:
    return value.isoformat()


def _merged_context_update_ids(
    request: AgentInvocationRequest,
    result: AgentInvocationResult | None,
) -> tuple[str, ...]:
    update_ids = [update_id.value for update_id in request.context_update_ids]
    if result is not None:
        for update_id in result.context_update_ids:
            if update_id.value not in update_ids:
                update_ids.append(update_id.value)
    return tuple(update_ids)


def _request_state(request: AgentInvocationRequest) -> Mapping[str, object]:
    return {
        "invocation_id": request.invocation_id.value,
        "workspace_id": request.workspace_id.value,
        "agent_id": request.agent_id.value,
        "instruction": request.instruction,
        "requested_at": _datetime_text(request.requested_at),
        "task_id": request.task_id.value if request.task_id is not None else None,
        "requested_capability": request.requested_capability,
        "context_update_ids": [
            update_id.value for update_id in request.context_update_ids
        ],
        "file_references": list(request.file_references),
        "idempotency_key": request.idempotency_key,
        "correlation_id": request.correlation_id,
        "metadata": dict(request.metadata),
    }


def _result_state(result: AgentInvocationResult | None) -> Mapping[str, object]:
    if result is None:
        return {}
    return {
        "invocation_id": result.invocation_id.value,
        "workspace_id": result.workspace_id.value,
        "agent_id": result.agent_id.value,
        "status": result.status.value,
        "summary": result.summary,
        "completed_at": _datetime_text(result.completed_at),
        "output_text": result.output_text,
        "error_message": result.error_message,
        "output_payload": dict(result.output_payload),
        "context_update_ids": [
            update_id.value for update_id in result.context_update_ids
        ],
        "metadata": dict(result.metadata),
    }


def _agent_invocation_event_payload(
    request: AgentInvocationRequest,
    result: AgentInvocationResult | None,
) -> Mapping[str, object]:
    status = result.status.value if result is not None else "requested"
    payload: dict[str, object] = {
        "invocation_id": request.invocation_id.value,
        "workspace_id": request.workspace_id.value,
        "agent_id": request.agent_id.value,
        "status": status,
        "has_result": result is not None,
    }
    if request.task_id is not None:
        payload["task_id"] = request.task_id.value
    if request.requested_capability is not None:
        payload["requested_capability"] = request.requested_capability
    return payload


def _validate_result_matches_request(
    request: AgentInvocationRequest,
    result: AgentInvocationResult,
) -> None:
    if result.invocation_id != request.invocation_id:
        raise ValueError("result invocation_id must match request invocation_id.")
    if result.workspace_id != request.workspace_id:
        raise ValueError("result workspace_id must match request workspace_id.")
    if result.agent_id != request.agent_id:
        raise ValueError("result agent_id must match request agent_id.")


def agent_invocation_record_upsert_row(
    *,
    request: AgentInvocationRequest,
    source_event_sequence: int,
    result: AgentInvocationResult | None = None,
) -> Mapping[str, object | None]:
    if source_event_sequence < 0:
        raise ValueError("source_event_sequence must be a non-negative integer.")
    if result is not None:
        _validate_result_matches_request(request, result)

    result_state = _result_state(result)
    status = result.status.value if result is not None else "requested"
    completed_at = (
        _datetime_text(result.completed_at)
        if result is not None
        else None
    )
    updated_at = result.completed_at if result is not None else request.requested_at
    metadata = {"request": dict(request.metadata)}
    if result is not None:
        metadata["result"] = dict(result.metadata)

    return {
        "invocation_id": request.invocation_id.value,
        "workspace_id": request.workspace_id.value,
        "agent_id": request.agent_id.value,
        "task_id": request.task_id.value if request.task_id is not None else None,
        "source_event_sequence": source_event_sequence,
        "status": status,
        "instruction": request.instruction,
        "requested_capability": request.requested_capability,
        "idempotency_key": request.idempotency_key,
        "correlation_id": request.correlation_id,
        "request_json": _stable_json(_request_state(request)),
        "result_json": _stable_json(result_state),
        "context_update_ids_json": _stable_json_list(
            _merged_context_update_ids(request, result)
        ),
        "file_references_json": _stable_json_list(request.file_references),
        "metadata_json": _stable_json(metadata),
        "requested_at": _datetime_text(request.requested_at),
        "completed_at": completed_at,
        "created_at": _datetime_text(request.requested_at),
        "updated_at": _datetime_text(updated_at),
    }


@dataclass(frozen=True, slots=True)
class AgentInvocationRecordEntry:
    """Persisted audit row for one agent invocation request/result pair."""

    invocation_id: AgentInvocationId
    workspace_id: WorkspaceId
    agent_id: AgentId
    source_event_sequence: int
    status: str
    instruction: str
    requested_at: datetime
    created_at: datetime
    updated_at: datetime
    task_id: TaskId | None = None
    requested_capability: str | None = None
    idempotency_key: str | None = None
    correlation_id: str | None = None
    request_state: Mapping[str, object] = field(default_factory=dict)
    result_state: Mapping[str, object] = field(default_factory=dict)
    context_update_ids: tuple[ContextUpdateId, ...] = ()
    file_references: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.invocation_id.value, "invocation_id")
        _require_non_empty(self.workspace_id.value, "workspace_id")
        _require_non_empty(self.agent_id.value, "agent_id")
        _require_non_empty(self.instruction, "instruction")
        if self.source_event_sequence < 0:
            raise ValueError("source_event_sequence must be a non-negative integer.")
        if self.status not in AGENT_INVOCATION_RECORD_STATUSES:
            raise ValueError("status must be an agent invocation record status.")
        if self.status == "requested" and self.completed_at is not None:
            raise ValueError("requested records must not have completed_at.")
        if self.status != "requested" and self.completed_at is None:
            raise ValueError("terminal records must have completed_at.")

    @classmethod
    def from_sqlite_row(
        cls,
        row: Mapping[str, object | None],
    ) -> "AgentInvocationRecordEntry":
        task_id = row["task_id"]
        requested_capability = row["requested_capability"]
        idempotency_key = row["idempotency_key"]
        correlation_id = row["correlation_id"]
        completed_at = row["completed_at"]
        return cls(
            invocation_id=AgentInvocationId(str(row["invocation_id"])),
            workspace_id=WorkspaceId(str(row["workspace_id"])),
            agent_id=AgentId(str(row["agent_id"])),
            task_id=TaskId(str(task_id)) if task_id is not None else None,
            source_event_sequence=int(row["source_event_sequence"] or 0),
            status=str(row["status"]),
            instruction=str(row["instruction"]),
            requested_capability=(
                str(requested_capability)
                if requested_capability is not None
                else None
            ),
            idempotency_key=(
                str(idempotency_key)
                if idempotency_key is not None
                else None
            ),
            correlation_id=(
                str(correlation_id)
                if correlation_id is not None
                else None
            ),
            request_state=_load_mapping_json(row["request_json"], "request_json"),
            result_state=_load_mapping_json(row["result_json"], "result_json"),
            context_update_ids=tuple(
                ContextUpdateId(update_id)
                for update_id in _load_text_list_json(
                    row["context_update_ids_json"],
                    "context_update_ids_json",
                )
            ),
            file_references=_load_text_list_json(
                row["file_references_json"],
                "file_references_json",
            ),
            metadata=_load_mapping_json(row["metadata_json"], "metadata_json"),
            requested_at=datetime.fromisoformat(str(row["requested_at"])),
            completed_at=(
                datetime.fromisoformat(str(completed_at))
                if completed_at is not None
                else None
            ),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )


class AgentInvocationRecordReaderPort(Protocol):
    """Minimal read boundary for agent invocation audit records."""

    def get_agent_invocation_record(
        self,
        invocation_id: AgentInvocationId,
    ) -> AgentInvocationRecordEntry | None:
        ...

    def get_agent_invocation_record_by_idempotency_key(
        self,
        *,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> AgentInvocationRecordEntry | None:
        ...

    def list_agent_invocation_records_by_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        status: str | None = None,
        agent_id: AgentId | None = None,
        task_id: TaskId | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[AgentInvocationRecordEntry, ...]:
        ...


class AgentInvocationRecordEventPort(Protocol):
    """Minimal event-linked write boundary for agent invocation audit records."""

    def record_agent_invocation_event(
        self,
        *,
        request: AgentInvocationRequest,
        result: AgentInvocationResult | None = None,
        event_id: PlatformEventId | None = None,
        occurred_at: datetime | None = None,
        session_id: PlatformRunSessionId | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> int:
        ...


class AgentInvocationRecordWriterPort(Protocol):
    """Minimal write boundary for agent invocation audit records."""

    def upsert_agent_invocation_record(
        self,
        *,
        request: AgentInvocationRequest,
        source_event_sequence: int,
        result: AgentInvocationResult | None = None,
    ) -> None:
        ...


@dataclass(slots=True)
class SqliteAgentInvocationRecordStore(
    AgentInvocationRecordEventPort,
    AgentInvocationRecordReaderPort,
    AgentInvocationRecordWriterPort,
):
    """SQLite-backed reader/writer for agent invocation audit records."""

    connection: sqlite3.Connection

    def get_agent_invocation_record(
        self,
        invocation_id: AgentInvocationId,
    ) -> AgentInvocationRecordEntry | None:
        _require_non_empty(invocation_id.value, "invocation_id")
        row = self.connection.execute(
            SQLITE_AGENT_INVOCATION_RECORD_GET_SQL,
            (invocation_id.value,),
        ).fetchone()
        if row is None:
            return None
        return AgentInvocationRecordEntry.from_sqlite_row(
            dict(zip(AGENT_INVOCATION_RECORD_SELECT_COLUMNS, row, strict=True))
        )

    def get_agent_invocation_record_by_idempotency_key(
        self,
        *,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> AgentInvocationRecordEntry | None:
        _require_non_empty(workspace_id.value, "workspace_id")
        _require_non_empty(idempotency_key, "idempotency_key")
        row = self.connection.execute(
            SQLITE_AGENT_INVOCATION_RECORD_GET_BY_WORKSPACE_IDEMPOTENCY_SQL,
            (workspace_id.value, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        return AgentInvocationRecordEntry.from_sqlite_row(
            dict(zip(AGENT_INVOCATION_RECORD_SELECT_COLUMNS, row, strict=True))
        )

    def list_agent_invocation_records_by_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        status: str | None = None,
        agent_id: AgentId | None = None,
        task_id: TaskId | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[AgentInvocationRecordEntry, ...]:
        _require_non_empty(workspace_id.value, "workspace_id")
        if status is not None:
            _require_non_empty(status, "status")
            if status not in AGENT_INVOCATION_RECORD_STATUSES:
                raise ValueError("status must be an agent invocation record status.")
        if agent_id is not None:
            _require_non_empty(agent_id.value, "agent_id")
        if task_id is not None:
            _require_non_empty(task_id.value, "task_id")
        if idempotency_key is not None:
            _require_non_empty(idempotency_key, "idempotency_key")

        rows = self.connection.execute(
            SQLITE_AGENT_INVOCATION_RECORD_LIST_BY_WORKSPACE_SQL,
            (
                workspace_id.value,
                status,
                status,
                agent_id.value if agent_id is not None else None,
                agent_id.value if agent_id is not None else None,
                task_id.value if task_id is not None else None,
                task_id.value if task_id is not None else None,
                idempotency_key,
                idempotency_key,
            ),
        ).fetchall()
        return tuple(
            AgentInvocationRecordEntry.from_sqlite_row(
                dict(zip(AGENT_INVOCATION_RECORD_SELECT_COLUMNS, row, strict=True))
            )
            for row in rows
        )

    def record_agent_invocation_event(
        self,
        *,
        request: AgentInvocationRequest,
        result: AgentInvocationResult | None = None,
        event_id: PlatformEventId | None = None,
        occurred_at: datetime | None = None,
        session_id: PlatformRunSessionId | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> int:
        if result is not None:
            _validate_result_matches_request(request, result)
        event_record = PlatformEventRecord.create(
            event_id=event_id,
            workspace_id=request.workspace_id,
            session_id=session_id,
            event_kind=PlatformEventKind.AGENT_INVOCATION_RECORDED,
            aggregate_type="agent_invocation",
            aggregate_id=request.invocation_id.value,
            occurred_at=(
                occurred_at
                or (result.completed_at if result is not None else request.requested_at)
            ),
            correlation_id=request.correlation_id,
            idempotency_key=request.idempotency_key,
            payload=_agent_invocation_event_payload(request, result),
            metadata=dict(metadata or {}),
        )
        try:
            cursor = self.connection.execute(
                SQLITE_PLATFORM_EVENT_INSERT_SQL,
                event_record.to_sqlite_row(),
            )
            sequence = cursor.lastrowid
            if sequence is None:
                raise RuntimeError("SQLite did not return a platform event sequence.")
            self.connection.execute(
                SQLITE_AGENT_INVOCATION_RECORD_UPSERT_SQL,
                agent_invocation_record_upsert_row(
                    request=request,
                    source_event_sequence=int(sequence),
                    result=result,
                ),
            )
        except Exception:
            self.connection.rollback()
            raise
        self.connection.commit()
        return int(sequence)

    def upsert_agent_invocation_record(
        self,
        *,
        request: AgentInvocationRequest,
        source_event_sequence: int,
        result: AgentInvocationResult | None = None,
    ) -> None:
        self.connection.execute(
            SQLITE_AGENT_INVOCATION_RECORD_UPSERT_SQL,
            agent_invocation_record_upsert_row(
                request=request,
                source_event_sequence=source_event_sequence,
                result=result,
            ),
        )
        self.connection.commit()
