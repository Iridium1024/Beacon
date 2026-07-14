from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping

from agent_os.domain.value_objects.identifiers import AgentId, ContextId, ContextUpdateId, WorkspaceId


class ContextUpdateKind(StrEnum):
    """Platform context event families for auditable shared context."""

    USER_MESSAGE = "user_message"
    AGENT_MESSAGE = "agent_message"
    FILE_REFERENCE = "file_reference"
    TOOL_RESULT = "tool_result"
    DECISION = "decision"
    NOTE = "note"
    ARTIFACT = "artifact"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


@dataclass(frozen=True, slots=True)
class ContextUpdateInfo:
    """Append-only platform context update independent from heartbeat objects."""

    update_id: ContextUpdateId
    workspace_id: WorkspaceId
    update_kind: ContextUpdateKind
    summary: str
    created_at: datetime
    source_agent_id: AgentId | None = None
    payload: Mapping[str, object] = field(default_factory=dict)
    materialized_state_patch: Mapping[str, object] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.update_id.value, "update_id")
        _require_non_empty(self.workspace_id.value, "workspace_id")
        _require_non_empty(self.summary, "summary")
        if self.source_agent_id is not None:
            _require_non_empty(self.source_agent_id.value, "source_agent_id")

    @classmethod
    def create(
        cls,
        *,
        workspace_id: WorkspaceId,
        update_kind: ContextUpdateKind,
        summary: str,
        update_id: ContextUpdateId | None = None,
        created_at: datetime | None = None,
        source_agent_id: AgentId | None = None,
        payload: Mapping[str, object] | None = None,
        materialized_state_patch: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> "ContextUpdateInfo":
        return cls(
            update_id=update_id or ContextUpdateId.new(),
            workspace_id=workspace_id,
            update_kind=update_kind,
            summary=summary,
            created_at=created_at or _utc_now(),
            source_agent_id=source_agent_id,
            payload=dict(payload or {}),
            materialized_state_patch=dict(materialized_state_patch or {}),
            metadata=dict(metadata or {}),
        )


@dataclass(frozen=True, slots=True)
class ProjectSharedContext:
    """Canonical platform shared context with append-only update history."""

    context_id: ContextId
    workspace_id: WorkspaceId
    updates: tuple[ContextUpdateInfo, ...]
    materialized_state: Mapping[str, object]
    created_at: datetime
    updated_at: datetime
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.context_id.value, "context_id")
        _require_non_empty(self.workspace_id.value, "workspace_id")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at.")

        seen_update_ids: set[str] = set()
        for update in self.updates:
            if update.workspace_id != self.workspace_id:
                raise ValueError("context updates must belong to the same workspace.")
            if update.update_id.value in seen_update_ids:
                raise ValueError("context updates must be append-only with unique update ids.")
            seen_update_ids.add(update.update_id.value)

    @classmethod
    def create(
        cls,
        *,
        workspace_id: WorkspaceId,
        context_id: ContextId | None = None,
        created_at: datetime | None = None,
        materialized_state: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> "ProjectSharedContext":
        timestamp = created_at or _utc_now()
        return cls(
            context_id=context_id or ContextId.new(),
            workspace_id=workspace_id,
            updates=(),
            materialized_state=dict(materialized_state or {}),
            created_at=timestamp,
            updated_at=timestamp,
            metadata=dict(metadata or {}),
        )

    def append_update(self, update: ContextUpdateInfo) -> "ProjectSharedContext":
        if update.workspace_id != self.workspace_id:
            raise ValueError("context update workspace_id does not match context workspace_id.")
        if any(existing.update_id == update.update_id for existing in self.updates):
            raise ValueError("context update ids must be unique.")

        return replace(
            self,
            updates=(*self.updates, update),
            materialized_state={
                **dict(self.materialized_state),
                **dict(update.materialized_state_patch),
            },
            updated_at=max(self.updated_at, update.created_at),
        )

    def recent_updates(self, limit: int = 10) -> tuple[ContextUpdateInfo, ...]:
        if limit <= 0:
            return ()
        return self.updates[-limit:]

    def updates_by_kind(self, update_kind: ContextUpdateKind) -> tuple[ContextUpdateInfo, ...]:
        return tuple(
            update
            for update in self.updates
            if update.update_kind == update_kind
        )
