from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping, Protocol, TypeVar

from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextUpdateId,
    FileOperationId,
    PlatformRunSessionId,
    TaskId,
    WorkspaceId,
)


T = TypeVar("T")


class _Identifier(Protocol):
    value: str


class PlatformRunSessionStatus(StrEnum):
    """Lifecycle states for a platform run session."""

    OPEN = "open"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset(
    {
        PlatformRunSessionStatus.COMPLETED,
        PlatformRunSessionStatus.FAILED,
        PlatformRunSessionStatus.CANCELLED,
    }
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


def _append_unique(items: tuple[T, ...], item: T, field_name: str) -> tuple[T, ...]:
    if item in items:
        raise ValueError(f"{field_name} must not contain duplicate values.")
    return (*items, item)


def _validate_unique_ids(ids: tuple[_Identifier, ...], field_name: str) -> None:
    seen: set[str] = set()
    for identifier in ids:
        _require_non_empty(identifier.value, field_name)
        if identifier.value in seen:
            raise ValueError(f"{field_name} must not contain duplicate values.")
        seen.add(identifier.value)


@dataclass(frozen=True, slots=True)
class PlatformRunSession:
    """Recoverable platform run session state independent from runtime orchestration."""

    session_id: PlatformRunSessionId
    workspace_id: WorkspaceId
    status: PlatformRunSessionStatus
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    active_agent_ids: tuple[AgentId, ...] = ()
    task_ids: tuple[TaskId, ...] = ()
    invocation_ids: tuple[AgentInvocationId, ...] = ()
    context_update_ids: tuple[ContextUpdateId, ...] = ()
    file_operation_ids: tuple[FileOperationId, ...] = ()
    error_message: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.session_id.value, "session_id")
        _require_non_empty(self.workspace_id.value, "workspace_id")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at.")
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("started_at must not be earlier than created_at.")
        if self.ended_at is not None and self.ended_at < self.created_at:
            raise ValueError("ended_at must not be earlier than created_at.")
        if self.started_at is not None and self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at must not be earlier than started_at.")

        _validate_unique_ids(self.active_agent_ids, "active_agent_ids")
        _validate_unique_ids(self.task_ids, "task_ids")
        _validate_unique_ids(self.invocation_ids, "invocation_ids")
        _validate_unique_ids(self.context_update_ids, "context_update_ids")
        _validate_unique_ids(self.file_operation_ids, "file_operation_ids")

        if self.status in {PlatformRunSessionStatus.RUNNING, PlatformRunSessionStatus.PAUSED}:
            if self.started_at is None:
                raise ValueError("running or paused sessions must include started_at.")
            if self.ended_at is not None:
                raise ValueError("running or paused sessions must not include ended_at.")
        if self.status in TERMINAL_STATUSES and self.ended_at is None:
            raise ValueError("terminal sessions must include ended_at.")
        if self.status == PlatformRunSessionStatus.OPEN and self.ended_at is not None:
            raise ValueError("open sessions must not include ended_at.")

        if self.status == PlatformRunSessionStatus.FAILED:
            if self.error_message is None:
                raise ValueError("failed sessions must include an error_message.")
            _require_non_empty(self.error_message, "error_message")
        elif self.error_message is not None:
            raise ValueError("error_message is only valid for failed sessions.")

    @classmethod
    def open(
        cls,
        *,
        workspace_id: WorkspaceId,
        session_id: PlatformRunSessionId | None = None,
        created_at: datetime | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> "PlatformRunSession":
        timestamp = created_at or _utc_now()
        return cls(
            session_id=session_id or PlatformRunSessionId.new(),
            workspace_id=workspace_id,
            status=PlatformRunSessionStatus.OPEN,
            created_at=timestamp,
            updated_at=timestamp,
            metadata=dict(metadata or {}),
        )

    def start(self, *, started_at: datetime | None = None) -> "PlatformRunSession":
        self._require_mutable()
        timestamp = started_at or _utc_now()
        return replace(
            self,
            status=PlatformRunSessionStatus.RUNNING,
            started_at=timestamp,
            ended_at=None,
            updated_at=timestamp,
        )

    def pause(self, *, paused_at: datetime | None = None) -> "PlatformRunSession":
        self._require_mutable()
        return replace(
            self,
            status=PlatformRunSessionStatus.PAUSED,
            updated_at=paused_at or _utc_now(),
        )

    def resume(self, *, resumed_at: datetime | None = None) -> "PlatformRunSession":
        self._require_mutable()
        return replace(
            self,
            status=PlatformRunSessionStatus.RUNNING,
            updated_at=resumed_at or _utc_now(),
        )

    def complete(self, *, completed_at: datetime | None = None) -> "PlatformRunSession":
        self._require_mutable()
        timestamp = completed_at or _utc_now()
        return replace(
            self,
            status=PlatformRunSessionStatus.COMPLETED,
            ended_at=timestamp,
            updated_at=timestamp,
            error_message=None,
        )

    def fail(
        self,
        error_message: str,
        *,
        failed_at: datetime | None = None,
    ) -> "PlatformRunSession":
        self._require_mutable()
        _require_non_empty(error_message, "error_message")
        timestamp = failed_at or _utc_now()
        return replace(
            self,
            status=PlatformRunSessionStatus.FAILED,
            ended_at=timestamp,
            updated_at=timestamp,
            error_message=error_message,
        )

    def cancel(self, *, cancelled_at: datetime | None = None) -> "PlatformRunSession":
        self._require_mutable()
        timestamp = cancelled_at or _utc_now()
        return replace(
            self,
            status=PlatformRunSessionStatus.CANCELLED,
            ended_at=timestamp,
            updated_at=timestamp,
            error_message=None,
        )

    def add_agent(self, agent_id: AgentId, *, updated_at: datetime | None = None) -> "PlatformRunSession":
        self._require_mutable()
        return replace(
            self,
            active_agent_ids=_append_unique(self.active_agent_ids, agent_id, "active_agent_ids"),
            updated_at=updated_at or _utc_now(),
        )

    def add_task(self, task_id: TaskId, *, updated_at: datetime | None = None) -> "PlatformRunSession":
        self._require_mutable()
        return replace(
            self,
            task_ids=_append_unique(self.task_ids, task_id, "task_ids"),
            updated_at=updated_at or _utc_now(),
        )

    def add_invocation(
        self,
        invocation_id: AgentInvocationId,
        *,
        updated_at: datetime | None = None,
    ) -> "PlatformRunSession":
        self._require_mutable()
        return replace(
            self,
            invocation_ids=_append_unique(
                self.invocation_ids,
                invocation_id,
                "invocation_ids",
            ),
            updated_at=updated_at or _utc_now(),
        )

    def add_context_update(
        self,
        update_id: ContextUpdateId,
        *,
        updated_at: datetime | None = None,
    ) -> "PlatformRunSession":
        self._require_mutable()
        return replace(
            self,
            context_update_ids=_append_unique(
                self.context_update_ids,
                update_id,
                "context_update_ids",
            ),
            updated_at=updated_at or _utc_now(),
        )

    def add_file_operation(
        self,
        operation_id: FileOperationId,
        *,
        updated_at: datetime | None = None,
    ) -> "PlatformRunSession":
        self._require_mutable()
        return replace(
            self,
            file_operation_ids=_append_unique(
                self.file_operation_ids,
                operation_id,
                "file_operation_ids",
            ),
            updated_at=updated_at or _utc_now(),
        )

    def _require_mutable(self) -> None:
        if self.status in TERMINAL_STATUSES:
            raise ValueError("terminal sessions cannot be modified.")
