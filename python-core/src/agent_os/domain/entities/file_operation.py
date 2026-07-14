from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Mapping, Protocol

from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextUpdateId,
    FileOperationId,
    TaskId,
    WorkspaceId,
)


class _Identifier(Protocol):
    value: str


class FileOperationKind(StrEnum):
    """Workspace-bound file operation families for platform audit records."""

    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    LIST_DIRECTORY = "list_directory"


class FileOperationResultStatus(StrEnum):
    """Terminal states for a platform file operation result."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


def _validate_id(value: _Identifier | None, field_name: str) -> None:
    if value is not None:
        _require_non_empty(value.value, field_name)


def _validate_workspace_relative_path(relative_path: str, operation_kind: FileOperationKind) -> None:
    _require_non_empty(relative_path, "relative_path")
    if PurePosixPath(relative_path).is_absolute() or PureWindowsPath(relative_path).is_absolute():
        raise ValueError("relative_path must be workspace-relative.")

    normalized = relative_path.replace("\\", "/")
    if normalized == ".":
        if operation_kind != FileOperationKind.LIST_DIRECTORY:
            raise ValueError("workspace root path is only valid for directory listing.")
        return

    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("relative_path must not contain empty, current, or parent segments.")


def _validate_context_update_id(context_update_id: ContextUpdateId | None) -> None:
    if context_update_id is not None:
        _require_non_empty(context_update_id.value, "context_update_id")


@dataclass(frozen=True, slots=True)
class FileOperationRequest:
    """Controlled workspace file operation request before execution."""

    operation_id: FileOperationId
    workspace_id: WorkspaceId
    operation_kind: FileOperationKind
    relative_path: str
    requested_at: datetime
    requested_by_agent_id: AgentId | None = None
    invocation_id: AgentInvocationId | None = None
    task_id: TaskId | None = None
    content: str | None = None
    create_parents: bool = False
    recursive: bool = False
    reason: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.operation_id.value, "operation_id")
        _require_non_empty(self.workspace_id.value, "workspace_id")
        _validate_workspace_relative_path(self.relative_path, self.operation_kind)
        _validate_id(self.requested_by_agent_id, "requested_by_agent_id")
        _validate_id(self.invocation_id, "invocation_id")
        _validate_id(self.task_id, "task_id")
        if self.reason is not None:
            _require_non_empty(self.reason, "reason")

        if self.operation_kind == FileOperationKind.WRITE_FILE:
            if self.content is None:
                raise ValueError("write file requests must include content.")
        elif self.content is not None:
            raise ValueError("content is only valid for write file requests.")

        if self.create_parents and self.operation_kind != FileOperationKind.WRITE_FILE:
            raise ValueError("create_parents is only valid for write file requests.")
        if self.recursive and self.operation_kind != FileOperationKind.LIST_DIRECTORY:
            raise ValueError("recursive is only valid for directory listing requests.")

    @classmethod
    def create(
        cls,
        *,
        workspace_id: WorkspaceId,
        operation_kind: FileOperationKind,
        relative_path: str,
        operation_id: FileOperationId | None = None,
        requested_at: datetime | None = None,
        requested_by_agent_id: AgentId | None = None,
        invocation_id: AgentInvocationId | None = None,
        task_id: TaskId | None = None,
        content: str | None = None,
        create_parents: bool = False,
        recursive: bool = False,
        reason: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> "FileOperationRequest":
        return cls(
            operation_id=operation_id or FileOperationId.new(),
            workspace_id=workspace_id,
            operation_kind=operation_kind,
            relative_path=relative_path,
            requested_at=requested_at or _utc_now(),
            requested_by_agent_id=requested_by_agent_id,
            invocation_id=invocation_id,
            task_id=task_id,
            content=content,
            create_parents=create_parents,
            recursive=recursive,
            reason=reason,
            metadata=dict(metadata or {}),
        )


@dataclass(frozen=True, slots=True)
class FileOperationResult:
    """Auditable result for one controlled workspace file operation."""

    operation_id: FileOperationId
    workspace_id: WorkspaceId
    operation_kind: FileOperationKind
    relative_path: str
    status: FileOperationResultStatus
    completed_at: datetime
    requested_by_agent_id: AgentId | None = None
    invocation_id: AgentInvocationId | None = None
    task_id: TaskId | None = None
    context_update_id: ContextUpdateId | None = None
    bytes_read: int | None = None
    bytes_written: int | None = None
    output_payload: Mapping[str, object] = field(default_factory=dict)
    error_message: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.operation_id.value, "operation_id")
        _require_non_empty(self.workspace_id.value, "workspace_id")
        _validate_workspace_relative_path(self.relative_path, self.operation_kind)
        _validate_id(self.requested_by_agent_id, "requested_by_agent_id")
        _validate_id(self.invocation_id, "invocation_id")
        _validate_id(self.task_id, "task_id")
        _validate_context_update_id(self.context_update_id)

        if self.bytes_read is not None and self.bytes_read < 0:
            raise ValueError("bytes_read must not be negative.")
        if self.bytes_written is not None and self.bytes_written < 0:
            raise ValueError("bytes_written must not be negative.")
        if self.bytes_read is not None and self.operation_kind != FileOperationKind.READ_FILE:
            raise ValueError("bytes_read is only valid for read file results.")
        if self.bytes_written is not None and self.operation_kind != FileOperationKind.WRITE_FILE:
            raise ValueError("bytes_written is only valid for write file results.")

        if self.status == FileOperationResultStatus.SUCCEEDED:
            if self.error_message is not None:
                raise ValueError("successful file operation results must not include an error_message.")
        elif self.error_message is None:
            raise ValueError("failed or denied file operation results must include an error_message.")
        else:
            _require_non_empty(self.error_message, "error_message")

    @classmethod
    def succeed(
        cls,
        request: FileOperationRequest,
        *,
        completed_at: datetime | None = None,
        context_update_id: ContextUpdateId | None = None,
        bytes_read: int | None = None,
        bytes_written: int | None = None,
        output_payload: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> "FileOperationResult":
        return cls(
            operation_id=request.operation_id,
            workspace_id=request.workspace_id,
            operation_kind=request.operation_kind,
            relative_path=request.relative_path,
            status=FileOperationResultStatus.SUCCEEDED,
            completed_at=completed_at or _utc_now(),
            requested_by_agent_id=request.requested_by_agent_id,
            invocation_id=request.invocation_id,
            task_id=request.task_id,
            context_update_id=context_update_id,
            bytes_read=bytes_read,
            bytes_written=bytes_written,
            output_payload=dict(output_payload or {}),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def fail(
        cls,
        request: FileOperationRequest,
        *,
        error_message: str,
        completed_at: datetime | None = None,
        output_payload: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> "FileOperationResult":
        return cls(
            operation_id=request.operation_id,
            workspace_id=request.workspace_id,
            operation_kind=request.operation_kind,
            relative_path=request.relative_path,
            status=FileOperationResultStatus.FAILED,
            completed_at=completed_at or _utc_now(),
            requested_by_agent_id=request.requested_by_agent_id,
            invocation_id=request.invocation_id,
            task_id=request.task_id,
            output_payload=dict(output_payload or {}),
            error_message=error_message,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def deny(
        cls,
        request: FileOperationRequest,
        *,
        error_message: str,
        completed_at: datetime | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> "FileOperationResult":
        return cls(
            operation_id=request.operation_id,
            workspace_id=request.workspace_id,
            operation_kind=request.operation_kind,
            relative_path=request.relative_path,
            status=FileOperationResultStatus.DENIED,
            completed_at=completed_at or _utc_now(),
            requested_by_agent_id=request.requested_by_agent_id,
            invocation_id=request.invocation_id,
            task_id=request.task_id,
            error_message=error_message,
            metadata=dict(metadata or {}),
        )
