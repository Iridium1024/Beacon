from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import sqlite3
from typing import Mapping, Protocol

from agent_os.domain.entities.file_operation import (
    FileOperationRequest,
    FileOperationResult,
)
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextUpdateId,
    FileOperationId,
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


PLATFORM_FILE_OPERATION_RECORD_TABLES = (
    "platform_file_operation_records",
)


FILE_OPERATION_RECORD_KINDS = (
    "read_file",
    "write_file",
    "list_directory",
)


FILE_OPERATION_RECORD_STATUSES = (
    "requested",
    "succeeded",
    "failed",
    "denied",
)


FILE_OPERATION_RECORD_COLUMNS = (
    "operation_id",
    "workspace_id",
    "source_event_sequence",
    "operation_kind",
    "relative_path",
    "status",
    "requested_by_agent_id",
    "invocation_id",
    "task_id",
    "context_update_id",
    "request_json",
    "result_json",
    "output_payload_json",
    "metadata_json",
    "requested_at",
    "completed_at",
    "bytes_read",
    "bytes_written",
    "error_message",
    "created_at",
    "updated_at",
)


FILE_OPERATION_RECORD_UPSERT_COLUMNS = FILE_OPERATION_RECORD_COLUMNS


FILE_OPERATION_RECORD_SELECT_COLUMNS = FILE_OPERATION_RECORD_COLUMNS


SQLITE_PLATFORM_FILE_OPERATION_RECORD_SCHEMA = """
CREATE TABLE IF NOT EXISTS platform_file_operation_records (
    operation_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    source_event_sequence INTEGER NOT NULL,
    operation_kind TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_by_agent_id TEXT,
    invocation_id TEXT,
    task_id TEXT,
    context_update_id TEXT,
    request_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    output_payload_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    requested_at TEXT NOT NULL,
    completed_at TEXT,
    bytes_read INTEGER,
    bytes_written INTEGER,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (source_event_sequence >= 0),
    CHECK (operation_kind IN ('read_file', 'write_file', 'list_directory')),
    CHECK (status IN ('requested', 'succeeded', 'failed', 'denied')),
    CHECK (
        (status = 'requested' AND completed_at IS NULL)
        OR (status != 'requested' AND completed_at IS NOT NULL)
    ),
    CHECK (bytes_read IS NULL OR bytes_read >= 0),
    CHECK (bytes_written IS NULL OR bytes_written >= 0),
    CHECK (bytes_read IS NULL OR operation_kind = 'read_file'),
    CHECK (bytes_written IS NULL OR operation_kind = 'write_file'),
    CHECK (
        (status IN ('requested', 'succeeded') AND error_message IS NULL)
        OR (status IN ('failed', 'denied') AND error_message IS NOT NULL)
    ),
    FOREIGN KEY (workspace_id)
        REFERENCES platform_workspace_state(workspace_id)
        ON DELETE CASCADE,
    FOREIGN KEY (requested_by_agent_id)
        REFERENCES platform_agent_registration_state(agent_id)
        ON DELETE SET NULL,
    FOREIGN KEY (invocation_id)
        REFERENCES platform_agent_invocation_records(invocation_id)
        ON DELETE SET NULL,
    FOREIGN KEY (task_id)
        REFERENCES platform_task_state(task_id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_platform_file_operation_records_workspace_status
    ON platform_file_operation_records(workspace_id, status);

CREATE INDEX IF NOT EXISTS idx_platform_file_operation_records_workspace_kind
    ON platform_file_operation_records(workspace_id, operation_kind);

CREATE INDEX IF NOT EXISTS idx_platform_file_operation_records_invocation
    ON platform_file_operation_records(invocation_id)
    WHERE invocation_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_platform_file_operation_records_task
    ON platform_file_operation_records(task_id)
    WHERE task_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_platform_file_operation_records_agent
    ON platform_file_operation_records(requested_by_agent_id)
    WHERE requested_by_agent_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_platform_file_operation_records_context_update
    ON platform_file_operation_records(context_update_id)
    WHERE context_update_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_platform_file_operation_records_source_event
    ON platform_file_operation_records(source_event_sequence);
"""


SQLITE_FILE_OPERATION_RECORD_UPSERT_SQL = f"""
INSERT INTO platform_file_operation_records ({", ".join(FILE_OPERATION_RECORD_UPSERT_COLUMNS)})
VALUES ({", ".join(f":{column}" for column in FILE_OPERATION_RECORD_UPSERT_COLUMNS)})
ON CONFLICT(operation_id) DO UPDATE SET
    workspace_id = excluded.workspace_id,
    source_event_sequence = excluded.source_event_sequence,
    operation_kind = excluded.operation_kind,
    relative_path = excluded.relative_path,
    status = excluded.status,
    requested_by_agent_id = excluded.requested_by_agent_id,
    invocation_id = excluded.invocation_id,
    task_id = excluded.task_id,
    context_update_id = excluded.context_update_id,
    request_json = excluded.request_json,
    result_json = excluded.result_json,
    output_payload_json = excluded.output_payload_json,
    metadata_json = excluded.metadata_json,
    requested_at = excluded.requested_at,
    completed_at = excluded.completed_at,
    bytes_read = excluded.bytes_read,
    bytes_written = excluded.bytes_written,
    error_message = excluded.error_message,
    created_at = platform_file_operation_records.created_at,
    updated_at = excluded.updated_at;
"""


SQLITE_FILE_OPERATION_RECORD_GET_SQL = (
    f"SELECT {', '.join(FILE_OPERATION_RECORD_SELECT_COLUMNS)} "
    "FROM platform_file_operation_records WHERE operation_id = ?"
)


SQLITE_FILE_OPERATION_RECORD_LIST_BY_WORKSPACE_SQL = (
    f"SELECT {', '.join(FILE_OPERATION_RECORD_SELECT_COLUMNS)} "
    "FROM platform_file_operation_records "
    "WHERE workspace_id = ? "
    "AND (? IS NULL OR status = ?) "
    "AND (? IS NULL OR operation_kind = ?) "
    "AND (? IS NULL OR invocation_id = ?) "
    "AND (? IS NULL OR task_id = ?) "
    "AND (? IS NULL OR requested_by_agent_id = ?) "
    "ORDER BY source_event_sequence, operation_id"
)


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


def _stable_json(value: Mapping[str, object]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _load_mapping_json(value: object, field_name: str) -> Mapping[str, object]:
    loaded = json.loads(str(value))
    if not isinstance(loaded, dict):
        raise ValueError(f"{field_name} must decode to a JSON object.")
    return loaded


def _datetime_text(value: datetime) -> str:
    return value.isoformat()


def _optional_identifier(value: object | None) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value"))


def _request_state(request: FileOperationRequest) -> Mapping[str, object]:
    content_length = len(request.content) if request.content is not None else None
    return {
        "operation_id": request.operation_id.value,
        "workspace_id": request.workspace_id.value,
        "operation_kind": request.operation_kind.value,
        "relative_path": request.relative_path,
        "requested_at": _datetime_text(request.requested_at),
        "requested_by_agent_id": _optional_identifier(request.requested_by_agent_id),
        "invocation_id": _optional_identifier(request.invocation_id),
        "task_id": _optional_identifier(request.task_id),
        "content_present": request.content is not None,
        "content_persisted": False,
        "content_length": content_length,
        "create_parents": request.create_parents,
        "recursive": request.recursive,
        "reason": request.reason,
        "metadata": dict(request.metadata),
    }


def _result_state(result: FileOperationResult | None) -> Mapping[str, object]:
    if result is None:
        return {}
    return {
        "operation_id": result.operation_id.value,
        "workspace_id": result.workspace_id.value,
        "operation_kind": result.operation_kind.value,
        "relative_path": result.relative_path,
        "status": result.status.value,
        "completed_at": _datetime_text(result.completed_at),
        "requested_by_agent_id": _optional_identifier(result.requested_by_agent_id),
        "invocation_id": _optional_identifier(result.invocation_id),
        "task_id": _optional_identifier(result.task_id),
        "context_update_id": _optional_identifier(result.context_update_id),
        "bytes_read": result.bytes_read,
        "bytes_written": result.bytes_written,
        "output_payload": dict(result.output_payload),
        "error_message": result.error_message,
        "metadata": dict(result.metadata),
    }


def _validate_result_matches_request(
    request: FileOperationRequest,
    result: FileOperationResult,
) -> None:
    if result.operation_id != request.operation_id:
        raise ValueError("result operation_id must match request operation_id.")
    if result.workspace_id != request.workspace_id:
        raise ValueError("result workspace_id must match request workspace_id.")
    if result.operation_kind != request.operation_kind:
        raise ValueError("result operation_kind must match request operation_kind.")
    if result.relative_path != request.relative_path:
        raise ValueError("result relative_path must match request relative_path.")
    if result.requested_by_agent_id != request.requested_by_agent_id:
        raise ValueError("result requested_by_agent_id must match request requested_by_agent_id.")
    if result.invocation_id != request.invocation_id:
        raise ValueError("result invocation_id must match request invocation_id.")
    if result.task_id != request.task_id:
        raise ValueError("result task_id must match request task_id.")


def _file_operation_event_payload(
    request: FileOperationRequest,
    result: FileOperationResult | None,
) -> Mapping[str, object]:
    status = result.status.value if result is not None else "requested"
    payload: dict[str, object] = {
        "operation_id": request.operation_id.value,
        "workspace_id": request.workspace_id.value,
        "operation_kind": request.operation_kind.value,
        "relative_path": request.relative_path,
        "status": status,
        "has_result": result is not None,
    }
    if request.requested_by_agent_id is not None:
        payload["requested_by_agent_id"] = request.requested_by_agent_id.value
    if request.invocation_id is not None:
        payload["invocation_id"] = request.invocation_id.value
    if request.task_id is not None:
        payload["task_id"] = request.task_id.value
    if result is not None and result.context_update_id is not None:
        payload["context_update_id"] = result.context_update_id.value
    return payload


def file_operation_record_upsert_row(
    *,
    request: FileOperationRequest,
    source_event_sequence: int,
    result: FileOperationResult | None = None,
) -> Mapping[str, object | None]:
    if source_event_sequence < 0:
        raise ValueError("source_event_sequence must be a non-negative integer.")
    if result is not None:
        _validate_result_matches_request(request, result)

    result_state = _result_state(result)
    status = result.status.value if result is not None else "requested"
    completed_at = _datetime_text(result.completed_at) if result is not None else None
    updated_at = result.completed_at if result is not None else request.requested_at
    metadata = {"request": dict(request.metadata)}
    if result is not None:
        metadata["result"] = dict(result.metadata)

    return {
        "operation_id": request.operation_id.value,
        "workspace_id": request.workspace_id.value,
        "source_event_sequence": source_event_sequence,
        "operation_kind": request.operation_kind.value,
        "relative_path": request.relative_path,
        "status": status,
        "requested_by_agent_id": _optional_identifier(request.requested_by_agent_id),
        "invocation_id": _optional_identifier(request.invocation_id),
        "task_id": _optional_identifier(request.task_id),
        "context_update_id": (
            _optional_identifier(result.context_update_id)
            if result is not None
            else None
        ),
        "request_json": _stable_json(_request_state(request)),
        "result_json": _stable_json(result_state),
        "output_payload_json": _stable_json(
            result.output_payload if result is not None else {}
        ),
        "metadata_json": _stable_json(metadata),
        "requested_at": _datetime_text(request.requested_at),
        "completed_at": completed_at,
        "bytes_read": result.bytes_read if result is not None else None,
        "bytes_written": result.bytes_written if result is not None else None,
        "error_message": result.error_message if result is not None else None,
        "created_at": _datetime_text(request.requested_at),
        "updated_at": _datetime_text(updated_at),
    }


@dataclass(frozen=True, slots=True)
class FileOperationRecordEntry:
    """Persisted audit row for one file operation request/result pair."""

    operation_id: FileOperationId
    workspace_id: WorkspaceId
    source_event_sequence: int
    operation_kind: str
    relative_path: str
    status: str
    requested_at: datetime
    created_at: datetime
    updated_at: datetime
    requested_by_agent_id: AgentId | None = None
    invocation_id: AgentInvocationId | None = None
    task_id: TaskId | None = None
    context_update_id: ContextUpdateId | None = None
    request_state: Mapping[str, object] = field(default_factory=dict)
    result_state: Mapping[str, object] = field(default_factory=dict)
    output_payload: Mapping[str, object] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)
    completed_at: datetime | None = None
    bytes_read: int | None = None
    bytes_written: int | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.operation_id.value, "operation_id")
        _require_non_empty(self.workspace_id.value, "workspace_id")
        _require_non_empty(self.relative_path, "relative_path")
        if self.source_event_sequence < 0:
            raise ValueError("source_event_sequence must be a non-negative integer.")
        if self.operation_kind not in FILE_OPERATION_RECORD_KINDS:
            raise ValueError("operation_kind must be a file operation record kind.")
        if self.status not in FILE_OPERATION_RECORD_STATUSES:
            raise ValueError("status must be a file operation record status.")
        if self.status == "requested" and self.completed_at is not None:
            raise ValueError("requested records must not have completed_at.")
        if self.status != "requested" and self.completed_at is None:
            raise ValueError("terminal records must have completed_at.")
        if self.bytes_read is not None and self.bytes_read < 0:
            raise ValueError("bytes_read must not be negative.")
        if self.bytes_written is not None and self.bytes_written < 0:
            raise ValueError("bytes_written must not be negative.")
        if self.bytes_read is not None and self.operation_kind != "read_file":
            raise ValueError("bytes_read is only valid for read file records.")
        if self.bytes_written is not None and self.operation_kind != "write_file":
            raise ValueError("bytes_written is only valid for write file records.")
        if self.status in {"failed", "denied"} and self.error_message is None:
            raise ValueError("failed or denied records must include error_message.")
        if self.status in {"requested", "succeeded"} and self.error_message is not None:
            raise ValueError("requested or succeeded records must not include error_message.")

    @classmethod
    def from_sqlite_row(
        cls,
        row: Mapping[str, object | None],
    ) -> "FileOperationRecordEntry":
        requested_by_agent_id = row["requested_by_agent_id"]
        invocation_id = row["invocation_id"]
        task_id = row["task_id"]
        context_update_id = row["context_update_id"]
        completed_at = row["completed_at"]
        return cls(
            operation_id=FileOperationId(str(row["operation_id"])),
            workspace_id=WorkspaceId(str(row["workspace_id"])),
            source_event_sequence=int(row["source_event_sequence"] or 0),
            operation_kind=str(row["operation_kind"]),
            relative_path=str(row["relative_path"]),
            status=str(row["status"]),
            requested_by_agent_id=(
                AgentId(str(requested_by_agent_id))
                if requested_by_agent_id is not None
                else None
            ),
            invocation_id=(
                AgentInvocationId(str(invocation_id))
                if invocation_id is not None
                else None
            ),
            task_id=TaskId(str(task_id)) if task_id is not None else None,
            context_update_id=(
                ContextUpdateId(str(context_update_id))
                if context_update_id is not None
                else None
            ),
            request_state=_load_mapping_json(row["request_json"], "request_json"),
            result_state=_load_mapping_json(row["result_json"], "result_json"),
            output_payload=_load_mapping_json(
                row["output_payload_json"],
                "output_payload_json",
            ),
            metadata=_load_mapping_json(row["metadata_json"], "metadata_json"),
            requested_at=datetime.fromisoformat(str(row["requested_at"])),
            completed_at=(
                datetime.fromisoformat(str(completed_at))
                if completed_at is not None
                else None
            ),
            bytes_read=(
                int(row["bytes_read"])
                if row["bytes_read"] is not None
                else None
            ),
            bytes_written=(
                int(row["bytes_written"])
                if row["bytes_written"] is not None
                else None
            ),
            error_message=(
                str(row["error_message"])
                if row["error_message"] is not None
                else None
            ),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )


class FileOperationRecordReaderPort(Protocol):
    """Minimal read boundary for file operation audit records."""

    def get_file_operation_record(
        self,
        operation_id: FileOperationId,
    ) -> FileOperationRecordEntry | None:
        ...

    def list_file_operation_records_by_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        status: str | None = None,
        operation_kind: str | None = None,
        invocation_id: AgentInvocationId | None = None,
        task_id: TaskId | None = None,
        requested_by_agent_id: AgentId | None = None,
    ) -> tuple[FileOperationRecordEntry, ...]:
        ...


class FileOperationRecordEventPort(Protocol):
    """Minimal event-linked write boundary for file operation audit records."""

    def record_file_operation_event(
        self,
        *,
        request: FileOperationRequest,
        result: FileOperationResult | None = None,
        event_id: PlatformEventId | None = None,
        occurred_at: datetime | None = None,
        session_id: PlatformRunSessionId | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> int:
        ...


class FileOperationRecordWriterPort(Protocol):
    """Minimal write boundary for file operation audit records."""

    def upsert_file_operation_record(
        self,
        *,
        request: FileOperationRequest,
        source_event_sequence: int,
        result: FileOperationResult | None = None,
    ) -> None:
        ...


@dataclass(slots=True)
class SqliteFileOperationRecordStore(
    FileOperationRecordEventPort,
    FileOperationRecordReaderPort,
    FileOperationRecordWriterPort,
):
    """SQLite-backed reader/writer for file operation audit records."""

    connection: sqlite3.Connection

    def get_file_operation_record(
        self,
        operation_id: FileOperationId,
    ) -> FileOperationRecordEntry | None:
        _require_non_empty(operation_id.value, "operation_id")
        row = self.connection.execute(
            SQLITE_FILE_OPERATION_RECORD_GET_SQL,
            (operation_id.value,),
        ).fetchone()
        if row is None:
            return None
        return FileOperationRecordEntry.from_sqlite_row(
            dict(zip(FILE_OPERATION_RECORD_SELECT_COLUMNS, row, strict=True))
        )

    def list_file_operation_records_by_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        status: str | None = None,
        operation_kind: str | None = None,
        invocation_id: AgentInvocationId | None = None,
        task_id: TaskId | None = None,
        requested_by_agent_id: AgentId | None = None,
    ) -> tuple[FileOperationRecordEntry, ...]:
        _require_non_empty(workspace_id.value, "workspace_id")
        if status is not None:
            _require_non_empty(status, "status")
            if status not in FILE_OPERATION_RECORD_STATUSES:
                raise ValueError("status must be a file operation record status.")
        if operation_kind is not None:
            _require_non_empty(operation_kind, "operation_kind")
            if operation_kind not in FILE_OPERATION_RECORD_KINDS:
                raise ValueError("operation_kind must be a file operation record kind.")
        if invocation_id is not None:
            _require_non_empty(invocation_id.value, "invocation_id")
        if task_id is not None:
            _require_non_empty(task_id.value, "task_id")
        if requested_by_agent_id is not None:
            _require_non_empty(requested_by_agent_id.value, "requested_by_agent_id")

        rows = self.connection.execute(
            SQLITE_FILE_OPERATION_RECORD_LIST_BY_WORKSPACE_SQL,
            (
                workspace_id.value,
                status,
                status,
                operation_kind,
                operation_kind,
                invocation_id.value if invocation_id is not None else None,
                invocation_id.value if invocation_id is not None else None,
                task_id.value if task_id is not None else None,
                task_id.value if task_id is not None else None,
                (
                    requested_by_agent_id.value
                    if requested_by_agent_id is not None
                    else None
                ),
                (
                    requested_by_agent_id.value
                    if requested_by_agent_id is not None
                    else None
                ),
            ),
        ).fetchall()
        return tuple(
            FileOperationRecordEntry.from_sqlite_row(
                dict(zip(FILE_OPERATION_RECORD_SELECT_COLUMNS, row, strict=True))
            )
            for row in rows
        )

    def record_file_operation_event(
        self,
        *,
        request: FileOperationRequest,
        result: FileOperationResult | None = None,
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
            event_kind=PlatformEventKind.FILE_OPERATION_RECORDED,
            aggregate_type="file_operation",
            aggregate_id=request.operation_id.value,
            occurred_at=(
                occurred_at
                or (result.completed_at if result is not None else request.requested_at)
            ),
            payload=_file_operation_event_payload(request, result),
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
                SQLITE_FILE_OPERATION_RECORD_UPSERT_SQL,
                file_operation_record_upsert_row(
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

    def upsert_file_operation_record(
        self,
        *,
        request: FileOperationRequest,
        source_event_sequence: int,
        result: FileOperationResult | None = None,
    ) -> None:
        self.connection.execute(
            SQLITE_FILE_OPERATION_RECORD_UPSERT_SQL,
            file_operation_record_upsert_row(
                request=request,
                source_event_sequence=source_event_sequence,
                result=result,
            ),
        )
        self.connection.commit()
