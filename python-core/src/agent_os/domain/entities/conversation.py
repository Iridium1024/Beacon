from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping

from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextUpdateId,
    ConversationId,
    ConversationMessageId,
    PlatformRunSessionId,
    WorkspaceId,
)


class ConversationStatus(StrEnum):
    """Lifecycle states for a local user-visible conversation thread."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class ConversationMessageRole(StrEnum):
    """Provider-neutral roles for stored local conversation messages."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"
    NOTE = "note"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


def _require_utc_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class ConversationSession:
    """Workspace-scoped local conversation thread, distinct from run sessions."""

    conversation_id: ConversationId
    workspace_id: WorkspaceId
    title: str
    status: ConversationStatus
    created_at: datetime
    updated_at: datetime
    agent_id: AgentId | None = None
    archived_at: datetime | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.conversation_id.value, "conversation_id")
        _require_non_empty(self.workspace_id.value, "workspace_id")
        _require_non_empty(self.title, "title")
        _require_utc_aware(self.created_at, "created_at")
        _require_utc_aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at.")
        if self.agent_id is not None:
            _require_non_empty(self.agent_id.value, "agent_id")
        if self.archived_at is not None:
            _require_utc_aware(self.archived_at, "archived_at")
            if self.archived_at < self.created_at:
                raise ValueError("archived_at must not be earlier than created_at.")
        if self.status is ConversationStatus.ACTIVE and self.archived_at is not None:
            raise ValueError("active conversations must not include archived_at.")
        if self.status is ConversationStatus.ARCHIVED and self.archived_at is None:
            raise ValueError("archived conversations must include archived_at.")

    @classmethod
    def create(
        cls,
        *,
        workspace_id: WorkspaceId,
        title: str,
        conversation_id: ConversationId | None = None,
        agent_id: AgentId | None = None,
        created_at: datetime | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> "ConversationSession":
        timestamp = created_at or _utc_now()
        return cls(
            conversation_id=conversation_id or ConversationId.new(),
            workspace_id=workspace_id,
            title=title,
            status=ConversationStatus.ACTIVE,
            created_at=timestamp,
            updated_at=timestamp,
            agent_id=agent_id,
            metadata=dict(metadata or {}),
        )

    def archive(
        self,
        *,
        archived_at: datetime | None = None,
    ) -> "ConversationSession":
        if self.status is ConversationStatus.ARCHIVED:
            return self
        timestamp = archived_at or _utc_now()
        return replace(
            self,
            status=ConversationStatus.ARCHIVED,
            archived_at=timestamp,
            updated_at=timestamp,
        )


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    """Append-only message inside a local conversation thread."""

    message_id: ConversationMessageId
    conversation_id: ConversationId
    workspace_id: WorkspaceId
    sequence: int
    role: ConversationMessageRole
    content: str
    created_at: datetime
    agent_id: AgentId | None = None
    invocation_id: AgentInvocationId | None = None
    context_update_id: ContextUpdateId | None = None
    run_session_id: PlatformRunSessionId | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.message_id.value, "message_id")
        _require_non_empty(self.conversation_id.value, "conversation_id")
        _require_non_empty(self.workspace_id.value, "workspace_id")
        if self.sequence < 1:
            raise ValueError("sequence must be a positive integer.")
        _require_non_empty(self.content, "content")
        _require_utc_aware(self.created_at, "created_at")
        if self.agent_id is not None:
            _require_non_empty(self.agent_id.value, "agent_id")
        if self.invocation_id is not None:
            _require_non_empty(self.invocation_id.value, "invocation_id")
        if self.context_update_id is not None:
            _require_non_empty(self.context_update_id.value, "context_update_id")
        if self.run_session_id is not None:
            _require_non_empty(self.run_session_id.value, "run_session_id")

    @classmethod
    def create(
        cls,
        *,
        conversation_id: ConversationId,
        workspace_id: WorkspaceId,
        sequence: int,
        role: ConversationMessageRole,
        content: str,
        message_id: ConversationMessageId | None = None,
        created_at: datetime | None = None,
        agent_id: AgentId | None = None,
        invocation_id: AgentInvocationId | None = None,
        context_update_id: ContextUpdateId | None = None,
        run_session_id: PlatformRunSessionId | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> "ConversationMessage":
        return cls(
            message_id=message_id or ConversationMessageId.new(),
            conversation_id=conversation_id,
            workspace_id=workspace_id,
            sequence=sequence,
            role=role,
            content=content,
            created_at=created_at or _utc_now(),
            agent_id=agent_id,
            invocation_id=invocation_id,
            context_update_id=context_update_id,
            run_session_id=run_session_id,
            metadata=dict(metadata or {}),
        )
