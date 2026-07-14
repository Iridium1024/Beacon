from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping

from agent_os.domain.value_objects.identifiers import WorkspaceId


class WorkspaceStatus(StrEnum):
    """Lifecycle states for a project workspace."""

    ACTIVE = "active"
    ARCHIVED = "archived"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


@dataclass(frozen=True, slots=True)
class ProjectWorkspace:
    """Canonical platform workspace object independent from discussion state."""

    workspace_id: WorkspaceId
    display_name: str
    root_path: str
    status: WorkspaceStatus
    created_at: datetime
    updated_at: datetime
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.workspace_id.value, "workspace_id")
        _require_non_empty(self.display_name, "display_name")
        _require_non_empty(self.root_path, "root_path")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at.")

    @classmethod
    def create(
        cls,
        *,
        display_name: str,
        root_path: str,
        workspace_id: WorkspaceId | None = None,
        created_at: datetime | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> "ProjectWorkspace":
        timestamp = created_at or _utc_now()
        return cls(
            workspace_id=workspace_id or WorkspaceId.new(),
            display_name=display_name,
            root_path=root_path,
            status=WorkspaceStatus.ACTIVE,
            created_at=timestamp,
            updated_at=timestamp,
            metadata=dict(metadata or {}),
        )

    def rename(self, display_name: str, *, updated_at: datetime | None = None) -> "ProjectWorkspace":
        return replace(
            self,
            display_name=display_name,
            updated_at=updated_at or _utc_now(),
        )

    def archive(self, *, archived_at: datetime | None = None) -> "ProjectWorkspace":
        return replace(
            self,
            status=WorkspaceStatus.ARCHIVED,
            updated_at=archived_at or _utc_now(),
        )


@dataclass(frozen=True, slots=True)
class ProjectBinding:
    """Binds a project workspace to a controlled local directory and runtime config."""

    workspace_id: WorkspaceId
    local_root_path: str
    runtime_config: Mapping[str, object] = field(default_factory=dict)
    writable: bool = True
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.workspace_id.value, "workspace_id")
        _require_non_empty(self.local_root_path, "local_root_path")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at.")

    @classmethod
    def bind(
        cls,
        *,
        workspace_id: WorkspaceId,
        local_root_path: str,
        runtime_config: Mapping[str, object] | None = None,
        writable: bool = True,
        created_at: datetime | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> "ProjectBinding":
        timestamp = created_at or _utc_now()
        return cls(
            workspace_id=workspace_id,
            local_root_path=local_root_path,
            runtime_config=dict(runtime_config or {}),
            writable=writable,
            created_at=timestamp,
            updated_at=timestamp,
            metadata=dict(metadata or {}),
        )

    def with_runtime_config(
        self,
        runtime_config: Mapping[str, object],
        *,
        updated_at: datetime | None = None,
    ) -> "ProjectBinding":
        return replace(
            self,
            runtime_config=dict(runtime_config),
            updated_at=updated_at or _utc_now(),
        )
