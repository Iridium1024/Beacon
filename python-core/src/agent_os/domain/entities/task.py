from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping, TypeVar

from agent_os.domain.value_objects.identifiers import (
    AgentId,
    ContextUpdateId,
    IssueId,
    TaskId,
    WorkspaceId,
)


T = TypeVar("T")


class TaskStatus(StrEnum):
    """Lifecycle states for platform task context."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class IssueStatus(StrEnum):
    """Lifecycle states for platform issue context."""

    OPEN = "open"
    TRIAGED = "triaged"
    RESOLVED = "resolved"
    ARCHIVED = "archived"


class IssueSeverity(StrEnum):
    """Issue severity labels for task and context routing."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


def _append_unique(items: tuple[T, ...], item: T, field_name: str) -> tuple[T, ...]:
    if item in items:
        raise ValueError(f"{field_name} must not contain duplicate values.")
    return (*items, item)


def _validate_context_update_ids(context_update_ids: tuple[ContextUpdateId, ...]) -> None:
    seen: set[str] = set()
    for update_id in context_update_ids:
        _require_non_empty(update_id.value, "context_update_id")
        if update_id.value in seen:
            raise ValueError("context_update_ids must not contain duplicate values.")
        seen.add(update_id.value)


def _validate_linked_file_paths(linked_file_paths: tuple[str, ...]) -> None:
    seen: set[str] = set()
    for path in linked_file_paths:
        _require_non_empty(path, "linked_file_path")
        if path in seen:
            raise ValueError("linked_file_paths must not contain duplicate values.")
        seen.add(path)


@dataclass(frozen=True, slots=True)
class TaskContext:
    """Task-scoped platform context under a project workspace."""

    task_id: TaskId
    workspace_id: WorkspaceId
    title: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    description: str | None = None
    assignee_agent_id: AgentId | None = None
    context_update_ids: tuple[ContextUpdateId, ...] = ()
    linked_file_paths: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.task_id.value, "task_id")
        _require_non_empty(self.workspace_id.value, "workspace_id")
        _require_non_empty(self.title, "title")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at.")
        if self.assignee_agent_id is not None:
            _require_non_empty(self.assignee_agent_id.value, "assignee_agent_id")
        _validate_context_update_ids(self.context_update_ids)
        _validate_linked_file_paths(self.linked_file_paths)

    @classmethod
    def create(
        cls,
        *,
        workspace_id: WorkspaceId,
        title: str,
        task_id: TaskId | None = None,
        created_at: datetime | None = None,
        description: str | None = None,
        assignee_agent_id: AgentId | None = None,
        context_update_ids: tuple[ContextUpdateId, ...] = (),
        linked_file_paths: tuple[str, ...] = (),
        metadata: Mapping[str, object] | None = None,
    ) -> "TaskContext":
        timestamp = created_at or _utc_now()
        return cls(
            task_id=task_id or TaskId.new(),
            workspace_id=workspace_id,
            title=title,
            status=TaskStatus.OPEN,
            created_at=timestamp,
            updated_at=timestamp,
            description=description,
            assignee_agent_id=assignee_agent_id,
            context_update_ids=tuple(context_update_ids),
            linked_file_paths=tuple(linked_file_paths),
            metadata=dict(metadata or {}),
        )

    def transition(self, status: TaskStatus, *, updated_at: datetime | None = None) -> "TaskContext":
        return replace(self, status=status, updated_at=updated_at or _utc_now())

    def assign(self, assignee_agent_id: AgentId, *, updated_at: datetime | None = None) -> "TaskContext":
        return replace(
            self,
            assignee_agent_id=assignee_agent_id,
            updated_at=updated_at or _utc_now(),
        )

    def add_context_update(
        self,
        update_id: ContextUpdateId,
        *,
        updated_at: datetime | None = None,
    ) -> "TaskContext":
        return replace(
            self,
            context_update_ids=_append_unique(
                self.context_update_ids,
                update_id,
                "context_update_ids",
            ),
            updated_at=updated_at or _utc_now(),
        )

    def link_file(self, file_path: str, *, updated_at: datetime | None = None) -> "TaskContext":
        _require_non_empty(file_path, "linked_file_path")
        return replace(
            self,
            linked_file_paths=_append_unique(
                self.linked_file_paths,
                file_path,
                "linked_file_paths",
            ),
            updated_at=updated_at or _utc_now(),
        )


@dataclass(frozen=True, slots=True)
class IssueContext:
    """Issue-scoped platform context under a project workspace."""

    issue_id: IssueId
    workspace_id: WorkspaceId
    title: str
    status: IssueStatus
    severity: IssueSeverity
    created_at: datetime
    updated_at: datetime
    description: str | None = None
    linked_task_id: TaskId | None = None
    context_update_ids: tuple[ContextUpdateId, ...] = ()
    linked_file_paths: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.issue_id.value, "issue_id")
        _require_non_empty(self.workspace_id.value, "workspace_id")
        _require_non_empty(self.title, "title")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at.")
        if self.linked_task_id is not None:
            _require_non_empty(self.linked_task_id.value, "linked_task_id")
        _validate_context_update_ids(self.context_update_ids)
        _validate_linked_file_paths(self.linked_file_paths)

    @classmethod
    def create(
        cls,
        *,
        workspace_id: WorkspaceId,
        title: str,
        issue_id: IssueId | None = None,
        created_at: datetime | None = None,
        severity: IssueSeverity = IssueSeverity.MEDIUM,
        description: str | None = None,
        linked_task_id: TaskId | None = None,
        context_update_ids: tuple[ContextUpdateId, ...] = (),
        linked_file_paths: tuple[str, ...] = (),
        metadata: Mapping[str, object] | None = None,
    ) -> "IssueContext":
        timestamp = created_at or _utc_now()
        return cls(
            issue_id=issue_id or IssueId.new(),
            workspace_id=workspace_id,
            title=title,
            status=IssueStatus.OPEN,
            severity=severity,
            created_at=timestamp,
            updated_at=timestamp,
            description=description,
            linked_task_id=linked_task_id,
            context_update_ids=tuple(context_update_ids),
            linked_file_paths=tuple(linked_file_paths),
            metadata=dict(metadata or {}),
        )

    def transition(self, status: IssueStatus, *, updated_at: datetime | None = None) -> "IssueContext":
        return replace(self, status=status, updated_at=updated_at or _utc_now())

    def link_task(self, task_id: TaskId, *, updated_at: datetime | None = None) -> "IssueContext":
        return replace(self, linked_task_id=task_id, updated_at=updated_at or _utc_now())

    def add_context_update(
        self,
        update_id: ContextUpdateId,
        *,
        updated_at: datetime | None = None,
    ) -> "IssueContext":
        return replace(
            self,
            context_update_ids=_append_unique(
                self.context_update_ids,
                update_id,
                "context_update_ids",
            ),
            updated_at=updated_at or _utc_now(),
        )

    def link_file(self, file_path: str, *, updated_at: datetime | None = None) -> "IssueContext":
        _require_non_empty(file_path, "linked_file_path")
        return replace(
            self,
            linked_file_paths=_append_unique(
                self.linked_file_paths,
                file_path,
                "linked_file_paths",
            ),
            updated_at=updated_at or _utc_now(),
        )
