from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping, TypeVar

from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextUpdateId,
    TaskId,
    WorkspaceId,
)


T = TypeVar("T")


class AgentInvocationResultStatus(StrEnum):
    """Terminal states for a platform agent invocation result."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


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


def _validate_file_references(file_references: tuple[str, ...]) -> None:
    seen: set[str] = set()
    for file_reference in file_references:
        _require_non_empty(file_reference, "file_reference")
        if file_reference in seen:
            raise ValueError("file_references must not contain duplicate values.")
        seen.add(file_reference)


@dataclass(frozen=True, slots=True)
class AgentInvocationRequest:
    """Single-turn platform request addressed to one registered agent."""

    invocation_id: AgentInvocationId
    workspace_id: WorkspaceId
    agent_id: AgentId
    instruction: str
    requested_at: datetime
    task_id: TaskId | None = None
    requested_capability: str | None = None
    context_update_ids: tuple[ContextUpdateId, ...] = ()
    file_references: tuple[str, ...] = ()
    idempotency_key: str | None = None
    correlation_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.invocation_id.value, "invocation_id")
        _require_non_empty(self.workspace_id.value, "workspace_id")
        _require_non_empty(self.agent_id.value, "agent_id")
        _require_non_empty(self.instruction, "instruction")
        if self.task_id is not None:
            _require_non_empty(self.task_id.value, "task_id")
        if self.requested_capability is not None:
            _require_non_empty(self.requested_capability, "requested_capability")
        if self.idempotency_key is not None:
            _require_non_empty(self.idempotency_key, "idempotency_key")
        if self.correlation_id is not None:
            _require_non_empty(self.correlation_id, "correlation_id")
        _validate_context_update_ids(self.context_update_ids)
        _validate_file_references(self.file_references)

    @classmethod
    def create(
        cls,
        *,
        workspace_id: WorkspaceId,
        agent_id: AgentId,
        instruction: str,
        invocation_id: AgentInvocationId | None = None,
        requested_at: datetime | None = None,
        task_id: TaskId | None = None,
        requested_capability: str | None = None,
        context_update_ids: tuple[ContextUpdateId, ...] = (),
        file_references: tuple[str, ...] = (),
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> "AgentInvocationRequest":
        return cls(
            invocation_id=invocation_id or AgentInvocationId.new(),
            workspace_id=workspace_id,
            agent_id=agent_id,
            instruction=instruction,
            requested_at=requested_at or _utc_now(),
            task_id=task_id,
            requested_capability=requested_capability,
            context_update_ids=tuple(context_update_ids),
            file_references=tuple(file_references),
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            metadata=dict(metadata or {}),
        )

    def add_context_update(self, update_id: ContextUpdateId) -> "AgentInvocationRequest":
        return replace(
            self,
            context_update_ids=_append_unique(
                self.context_update_ids,
                update_id,
                "context_update_ids",
            ),
        )

    def add_file_reference(self, file_reference: str) -> "AgentInvocationRequest":
        _require_non_empty(file_reference, "file_reference")
        return replace(
            self,
            file_references=_append_unique(
                self.file_references,
                file_reference,
                "file_references",
            ),
        )


@dataclass(frozen=True, slots=True)
class AgentInvocationResult:
    """Structured result for one platform agent invocation."""

    invocation_id: AgentInvocationId
    workspace_id: WorkspaceId
    agent_id: AgentId
    status: AgentInvocationResultStatus
    summary: str
    completed_at: datetime
    output_text: str | None = None
    error_message: str | None = None
    output_payload: Mapping[str, object] = field(default_factory=dict)
    context_update_ids: tuple[ContextUpdateId, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.invocation_id.value, "invocation_id")
        _require_non_empty(self.workspace_id.value, "workspace_id")
        _require_non_empty(self.agent_id.value, "agent_id")
        _require_non_empty(self.summary, "summary")
        if self.output_text is not None:
            _require_non_empty(self.output_text, "output_text")
        if self.error_message is not None:
            _require_non_empty(self.error_message, "error_message")
        if self.status == AgentInvocationResultStatus.FAILED and self.error_message is None:
            raise ValueError("failed invocation results must include an error_message.")
        _validate_context_update_ids(self.context_update_ids)

    @classmethod
    def succeed(
        cls,
        request: AgentInvocationRequest,
        *,
        summary: str,
        completed_at: datetime | None = None,
        output_text: str | None = None,
        output_payload: Mapping[str, object] | None = None,
        context_update_ids: tuple[ContextUpdateId, ...] = (),
        metadata: Mapping[str, object] | None = None,
    ) -> "AgentInvocationResult":
        return cls(
            invocation_id=request.invocation_id,
            workspace_id=request.workspace_id,
            agent_id=request.agent_id,
            status=AgentInvocationResultStatus.SUCCEEDED,
            summary=summary,
            completed_at=completed_at or _utc_now(),
            output_text=output_text,
            output_payload=dict(output_payload or {}),
            context_update_ids=tuple(context_update_ids),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def fail(
        cls,
        request: AgentInvocationRequest,
        *,
        summary: str,
        error_message: str,
        completed_at: datetime | None = None,
        output_payload: Mapping[str, object] | None = None,
        context_update_ids: tuple[ContextUpdateId, ...] = (),
        metadata: Mapping[str, object] | None = None,
    ) -> "AgentInvocationResult":
        return cls(
            invocation_id=request.invocation_id,
            workspace_id=request.workspace_id,
            agent_id=request.agent_id,
            status=AgentInvocationResultStatus.FAILED,
            summary=summary,
            completed_at=completed_at or _utc_now(),
            error_message=error_message,
            output_payload=dict(output_payload or {}),
            context_update_ids=tuple(context_update_ids),
            metadata=dict(metadata or {}),
        )
