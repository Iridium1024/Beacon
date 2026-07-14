from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping

from agent_os.domain.value_objects.identifiers import AgentId, WorkspaceId


class AgentRegistrationStatus(StrEnum):
    """Lifecycle states for a workspace-scoped platform agent registration."""

    ACTIVE = "active"
    DISABLED = "disabled"
    ARCHIVED = "archived"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


def _validate_capabilities(capabilities: tuple["AgentCapability", ...]) -> None:
    if not capabilities:
        raise ValueError("capabilities must include at least one capability.")

    seen: set[str] = set()
    for capability in capabilities:
        _require_non_empty(capability.name, "capability_name")
        _require_non_empty(capability.description, "capability_description")
        key = capability.name.strip()
        if key in seen:
            raise ValueError("capabilities must not contain duplicate names.")
        seen.add(key)


def _validate_tool_permissions(tool_permissions: tuple[str, ...]) -> None:
    seen: set[str] = set()
    for permission in tool_permissions:
        _require_non_empty(permission, "tool_permission")
        key = permission.strip()
        if key in seen:
            raise ValueError("tool_permissions must not contain duplicate values.")
        seen.add(key)


@dataclass(frozen=True, slots=True)
class AgentCapability:
    """Describes a capability exposed by a registered agent."""

    name: str
    description: str
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """Describes a registered agent without binding it to a specific model vendor."""

    agent_id: AgentId
    name: str
    description: str
    capabilities: tuple[AgentCapability, ...]
    default_model: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentRegistration:
    """Workspace-scoped platform agent registration independent from runtime adapters."""

    agent_id: AgentId
    workspace_id: WorkspaceId
    name: str
    description: str
    capabilities: tuple[AgentCapability, ...]
    status: AgentRegistrationStatus
    created_at: datetime
    updated_at: datetime
    default_model: str | None = None
    tool_permissions: tuple[str, ...] = ()
    runtime_config: Mapping[str, object] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.agent_id.value, "agent_id")
        _require_non_empty(self.workspace_id.value, "workspace_id")
        _require_non_empty(self.name, "name")
        _require_non_empty(self.description, "description")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at.")
        if self.default_model is not None:
            _require_non_empty(self.default_model, "default_model")
        _validate_capabilities(self.capabilities)
        _validate_tool_permissions(self.tool_permissions)

    @classmethod
    def register(
        cls,
        *,
        workspace_id: WorkspaceId,
        name: str,
        description: str,
        capabilities: tuple[AgentCapability, ...],
        agent_id: AgentId | None = None,
        created_at: datetime | None = None,
        default_model: str | None = None,
        tool_permissions: tuple[str, ...] = (),
        runtime_config: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> "AgentRegistration":
        timestamp = created_at or _utc_now()
        return cls(
            agent_id=agent_id or AgentId.new(),
            workspace_id=workspace_id,
            name=name,
            description=description,
            capabilities=tuple(capabilities),
            status=AgentRegistrationStatus.ACTIVE,
            created_at=timestamp,
            updated_at=timestamp,
            default_model=default_model,
            tool_permissions=tuple(tool_permissions),
            runtime_config=dict(runtime_config or {}),
            metadata=dict(metadata or {}),
        )

    def transition(
        self,
        status: AgentRegistrationStatus,
        *,
        updated_at: datetime | None = None,
    ) -> "AgentRegistration":
        return replace(self, status=status, updated_at=updated_at or _utc_now())

    def with_runtime_config(
        self,
        runtime_config: Mapping[str, object],
        *,
        updated_at: datetime | None = None,
    ) -> "AgentRegistration":
        return replace(
            self,
            runtime_config=dict(runtime_config),
            updated_at=updated_at or _utc_now(),
        )

    def with_tool_permissions(
        self,
        tool_permissions: tuple[str, ...],
        *,
        updated_at: datetime | None = None,
    ) -> "AgentRegistration":
        return replace(
            self,
            tool_permissions=tuple(tool_permissions),
            updated_at=updated_at or _utc_now(),
        )

    def has_capability(self, capability_name: str) -> bool:
        _require_non_empty(capability_name, "capability_name")
        return any(
            capability.name == capability_name
            for capability in self.capabilities
        )
