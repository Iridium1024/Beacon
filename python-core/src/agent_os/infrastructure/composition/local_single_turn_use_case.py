from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import Callable

from agent_os.application.services.agent_invocation_request_factory import (
    WorkspaceAgentInvocationRequestFactory,
)
from agent_os.application.services.local_single_turn_platform_use_case import (
    LocalSingleTurnPlatformUseCase,
)
from agent_os.application.services.single_turn_platform_runtime import (
    AgentInvocationAdapterPort,
)
from agent_os.domain.entities.agent import AgentRegistration
from agent_os.domain.entities.context import ProjectSharedContext
from agent_os.domain.entities.workspace import ProjectWorkspace
from agent_os.domain.value_objects.identifiers import AgentId, WorkspaceId
from agent_os.infrastructure.composition.single_turn_runtime import (
    SqliteSingleTurnPlatformRuntimeComponents,
    build_sqlite_single_turn_platform_runtime,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteAgentRegistrationStateStore,
    SqliteContextStateStore,
    SqliteWorkspaceStateStore,
)


@dataclass(frozen=True, slots=True)
class SqliteLocalSingleTurnPlatformUseCaseComponents:
    """Loaded SQLite state and composed services for one local single-turn use case."""

    use_case: LocalSingleTurnPlatformUseCase
    request_factory: WorkspaceAgentInvocationRequestFactory
    runtime_components: SqliteSingleTurnPlatformRuntimeComponents
    workspace: ProjectWorkspace
    context: ProjectSharedContext
    agent_registration: AgentRegistration


def build_sqlite_local_single_turn_platform_use_case(
    connection: sqlite3.Connection,
    *,
    workspace_id: WorkspaceId,
    agent_id: AgentId,
    record_agent_invocations: bool = True,
    agent_invocation_adapter: AgentInvocationAdapterPort | None = None,
    agent_invocation_adapter_factory: (
        Callable[[AgentRegistration], AgentInvocationAdapterPort | None] | None
    ) = None,
) -> SqliteLocalSingleTurnPlatformUseCaseComponents:
    """Load persisted local state and compose a single-turn use-case facade."""

    workspace_record = SqliteWorkspaceStateStore(connection).get_workspace_state(
        workspace_id
    )
    if workspace_record is None:
        raise ValueError("workspace state not found.")

    context_record = SqliteContextStateStore(connection).get_context_state(
        workspace_id
    )
    if context_record is None:
        raise ValueError("context state not found for workspace.")

    agent_registration_record = SqliteAgentRegistrationStateStore(
        connection
    ).get_agent_registration_state(agent_id)
    if agent_registration_record is None:
        raise ValueError("agent registration state not found.")
    resolved_agent_invocation_adapter = (
        agent_invocation_adapter_factory(agent_registration_record.registration)
        if agent_invocation_adapter_factory is not None
        else agent_invocation_adapter
    )

    runtime_components = build_sqlite_single_turn_platform_runtime(
        connection,
        record_agent_invocations=record_agent_invocations,
        agent_invocation_adapter=resolved_agent_invocation_adapter,
    )
    request_factory = WorkspaceAgentInvocationRequestFactory(
        workspace=workspace_record.workspace,
        context=context_record.context,
        agent_registration=agent_registration_record.registration,
    )
    use_case = LocalSingleTurnPlatformUseCase(
        request_factory=request_factory,
        runtime=runtime_components.runtime,
    )
    return SqliteLocalSingleTurnPlatformUseCaseComponents(
        use_case=use_case,
        request_factory=request_factory,
        runtime_components=runtime_components,
        workspace=workspace_record.workspace,
        context=context_record.context,
        agent_registration=agent_registration_record.registration,
    )
