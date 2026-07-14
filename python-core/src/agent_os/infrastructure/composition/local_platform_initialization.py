from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import sqlite3
from typing import Mapping

from agent_os.domain.entities.agent import AgentCapability, AgentRegistration
from agent_os.domain.entities.context import ProjectSharedContext
from agent_os.domain.entities.workspace import ProjectWorkspace
from agent_os.domain.value_objects.identifiers import AgentId, ContextId, WorkspaceId
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteAgentRegistrationStateStore,
    SqliteContextStateStore,
    SqliteWorkspaceStateStore,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class LocalPlatformInitialState:
    """Explicit minimal state required for one local platform invocation."""

    workspace_id: str
    context_id: str
    agent_id: str
    workspace_display_name: str
    workspace_root: str
    agent_name: str
    agent_description: str
    agent_capability_name: str
    agent_capability_description: str
    context_materialized_state: Mapping[str, object] = field(
        default_factory=lambda: {"status": "open"}
    )
    default_model: str = "deterministic-placeholder"
    created_at: datetime | None = None
    workspace_metadata: Mapping[str, object] = field(default_factory=dict)
    context_metadata: Mapping[str, object] = field(default_factory=dict)
    agent_runtime_config: Mapping[str, object] = field(default_factory=dict)
    agent_metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LocalPlatformInitializedState:
    """Objects stored by local platform initialization."""

    workspace: ProjectWorkspace
    context: ProjectSharedContext
    agent_registration: AgentRegistration
    source_event_sequence: int = 0
    platform_event_recorded: bool = False


def initialize_local_platform_state(
    connection: sqlite3.Connection,
    initial_state: LocalPlatformInitialState,
    *,
    source_event_sequence: int = 0,
) -> LocalPlatformInitializedState:
    """Store seed baseline state for local runs.

    This initializer intentionally writes materialized state with source event
    sequence 0. It does not append replayable platform events.
    """

    if source_event_sequence != 0:
        raise ValueError(
            "local platform initialization currently supports only seed baseline "
            "state with source_event_sequence 0."
        )
    created_at = initial_state.created_at or _utc_now()
    workspace_id = WorkspaceId(initial_state.workspace_id)
    workspace = ProjectWorkspace.create(
        workspace_id=workspace_id,
        display_name=initial_state.workspace_display_name,
        root_path=initial_state.workspace_root,
        created_at=created_at,
        metadata=dict(initial_state.workspace_metadata),
    )
    context = ProjectSharedContext.create(
        context_id=ContextId(initial_state.context_id),
        workspace_id=workspace_id,
        created_at=created_at,
        materialized_state=dict(initial_state.context_materialized_state),
        metadata=dict(initial_state.context_metadata),
    )
    agent_registration = AgentRegistration.register(
        agent_id=AgentId(initial_state.agent_id),
        workspace_id=workspace_id,
        name=initial_state.agent_name,
        description=initial_state.agent_description,
        capabilities=(
            AgentCapability(
                name=initial_state.agent_capability_name,
                description=initial_state.agent_capability_description,
            ),
        ),
        created_at=created_at,
        default_model=initial_state.default_model,
        runtime_config=dict(initial_state.agent_runtime_config),
        metadata=dict(initial_state.agent_metadata),
    )

    SqliteWorkspaceStateStore(connection).upsert_workspace_state(
        workspace=workspace,
        source_event_sequence=source_event_sequence,
    )
    SqliteContextStateStore(connection).upsert_context_state(
        context=context,
        source_event_sequence=source_event_sequence,
    )
    SqliteAgentRegistrationStateStore(connection).upsert_agent_registration_state(
        registration=agent_registration,
        source_event_sequence=source_event_sequence,
    )
    return LocalPlatformInitializedState(
        workspace=workspace,
        context=context,
        agent_registration=agent_registration,
        source_event_sequence=source_event_sequence,
        platform_event_recorded=False,
    )
