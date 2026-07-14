from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Callable, Mapping

from agent_os.application.services.file_operation_request_factory import (
    WorkspaceFileOperationPolicy,
    WorkspaceFileOperationRequestFactory,
)
from agent_os.application.services.agent_runtime_profile import (
    AgentRuntimeProfile,
)
from agent_os.application.services.file_operation_service import FileOperationService
from agent_os.application.services.local_platform_operations import (
    LocalPlatformOperationService,
)
from agent_os.application.services.platform_invocation_runtime_handler import (
    SqlitePlatformInvocationRuntimeHandler,
)
from agent_os.application.services.model_provider_selection import (
    ModelProviderSelection,
    build_provider_backed_agent_invocation_adapter,
)
from agent_os.application.services.single_turn_platform_runtime import (
    AgentInvocationAdapterPort,
)
from agent_os.application.services.workspace_file_operation_use_case import (
    WorkspaceFileOperationUseCase,
)
from agent_os.domain.entities.workspace import ProjectBinding
from agent_os.domain.entities.agent import AgentRegistration
from agent_os.domain.value_objects.identifiers import WorkspaceId
from agent_os.infrastructure.adapters.filesystem.workspace_file_operations import (
    WorkspaceFileOperationAdapter,
)
from agent_os.infrastructure.adapters.models import DeterministicModelProvider
from agent_os.infrastructure.adapters.models.provider_factory import (
    build_model_provider_from_connection_spec,
)
from agent_os.infrastructure.config import (
    LocalAgentInvocationAdapterMode,
    LocalPlatformSettings,
)
from agent_os.infrastructure.composition.local_platform_initialization import (
    LocalPlatformInitializedState,
    LocalPlatformInitialState,
    initialize_local_platform_state,
)
from agent_os.infrastructure.persistence.sqlite_persistence import (
    SqlitePlatformPersistence,
    configure_sqlite_platform_connection,
)
from agent_os.infrastructure.persistence.file_operation_records import (
    SqliteFileOperationRecordStore,
)
from agent_os.infrastructure.persistence.event_log import (
    SqlitePlatformEventLog,
)
from agent_os.infrastructure.persistence.invocation_records import (
    SqliteAgentInvocationRecordStore,
)
from agent_os.infrastructure.persistence.context_update_events import (
    SqliteContextUpdateEventRecorder,
)
from agent_os.infrastructure.persistence.conversations import SqliteConversationStore
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteAgentRegistrationStateStore,
    SqliteContextStateStore,
    SqliteIssueStateStore,
    SqliteTaskStateStore,
    SqliteWorkspaceStateStore,
)


@dataclass(slots=True)
class LocalPlatformRuntimeComponents:
    """Narrow local composition for the executable invocation path."""

    settings: LocalPlatformSettings
    connection: sqlite3.Connection
    agent_invocation_adapter: AgentInvocationAdapterPort | None
    agent_invocation_adapter_factory: Callable[
        [AgentRegistration],
        AgentInvocationAdapterPort | None,
    ] | None
    runtime_handler: SqlitePlatformInvocationRuntimeHandler
    initialized_state: LocalPlatformInitializedState | None = None

    def handle_payload(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        return self.runtime_handler.handle_payload(payload)

    def workspace_file_operations(
        self,
        workspace_id: WorkspaceId | str,
        *,
        policy: WorkspaceFileOperationPolicy | None = None,
    ) -> WorkspaceFileOperationUseCase:
        return build_local_workspace_file_operation_use_case(
            self.connection,
            workspace_id=workspace_id,
            policy=policy,
        )

    def operations(self) -> LocalPlatformOperationService:
        return build_local_platform_operation_service(self.connection)

    def close(self) -> None:
        self.connection.close()


def build_local_platform_runtime(
    settings: LocalPlatformSettings,
    *,
    initial_state: LocalPlatformInitialState | None = None,
) -> LocalPlatformRuntimeComponents:
    """Open local persistence and compose the current invocation handler."""

    connection = connect_local_platform_database(settings.database)
    try:
        if settings.initialize_schema:
            SqlitePlatformPersistence(connection).initialize()
        initialized_state = (
            initialize_local_platform_state(connection, initial_state)
            if initial_state is not None
            else None
        )
        agent_invocation_adapter = build_local_agent_invocation_adapter(settings)
        agent_invocation_adapter_factory = build_local_agent_invocation_adapter_factory(
            settings
        )
        runtime_handler = SqlitePlatformInvocationRuntimeHandler(
            connection=connection,
            record_agent_invocations=settings.record_agent_invocations,
            agent_invocation_adapter=agent_invocation_adapter,
            agent_invocation_adapter_factory=agent_invocation_adapter_factory,
            file_operation_use_case_factory=(
                lambda workspace_id: build_local_workspace_file_operation_use_case(
                    connection,
                    workspace_id=workspace_id,
                )
            ),
        )
        return LocalPlatformRuntimeComponents(
            settings=settings,
            connection=connection,
            agent_invocation_adapter=agent_invocation_adapter,
            agent_invocation_adapter_factory=agent_invocation_adapter_factory,
            runtime_handler=runtime_handler,
            initialized_state=initialized_state,
        )
    except Exception:
        connection.close()
        raise


def build_local_agent_invocation_adapter(
    settings: LocalPlatformSettings,
) -> AgentInvocationAdapterPort | None:
    """Build the explicitly configured local agent adapter, if any."""

    return _build_local_agent_invocation_adapter_for_selection(
        settings,
        _default_model_provider_selection(settings),
    )


def build_local_agent_invocation_adapter_factory(
    settings: LocalPlatformSettings,
) -> Callable[[AgentRegistration], AgentInvocationAdapterPort | None] | None:
    """Build a per-agent adapter factory that applies runtime profiles."""

    default_selection = _default_model_provider_selection(settings)
    if default_selection is None:
        return None

    def build_for_agent(
        registration: AgentRegistration,
    ) -> AgentInvocationAdapterPort | None:
        profile = AgentRuntimeProfile.from_registration(registration)
        selection = profile.provider_selection(default_selection)
        _require_selection_matches_configured_provider(
            configured=default_selection,
            selection=selection,
        )
        return _build_local_agent_invocation_adapter_for_selection(
            settings,
            selection,
        )

    return build_for_agent


def _default_model_provider_selection(
    settings: LocalPlatformSettings,
):
    if (
        settings.agent_invocation_adapter_mode
        is LocalAgentInvocationAdapterMode.DETERMINISTIC_PLACEHOLDER
    ):
        return None
    if (
        settings.agent_invocation_adapter_mode
        is LocalAgentInvocationAdapterMode.DETERMINISTIC_PROVIDER
    ):
        return settings.provider_selection_or_default()
    if (
        settings.agent_invocation_adapter_mode
        is LocalAgentInvocationAdapterMode.OPENAI_COMPATIBLE_PROVIDER
    ):
        return settings.openai_compatible_provider_or_raise().model_selection()
    provider_connection = settings.provider_connection_or_raise()
    return ModelProviderSelection(
        provider_name=provider_connection.provider_name,
        model_name=provider_connection.model_name,
        parameters=dict(provider_connection.parameters),
    )


def _build_local_agent_invocation_adapter_for_selection(
    settings: LocalPlatformSettings,
    selection,
) -> AgentInvocationAdapterPort | None:
    if selection is None:
        return None
    if (
        settings.agent_invocation_adapter_mode
        is LocalAgentInvocationAdapterMode.DETERMINISTIC_PROVIDER
    ):
        return build_provider_backed_agent_invocation_adapter(
            model_provider=DeterministicModelProvider(),
            selection=selection,
        )
    provider_connection = _configured_provider_connection(settings)
    return build_provider_backed_agent_invocation_adapter(
        model_provider=build_model_provider_from_connection_spec(
            provider_connection,
        ),
        selection=selection,
    )


def _configured_provider_connection(settings: LocalPlatformSettings):
    if (
        settings.agent_invocation_adapter_mode
        is LocalAgentInvocationAdapterMode.OPENAI_COMPATIBLE_PROVIDER
    ):
        return settings.openai_compatible_provider_or_raise().connection_spec()
    return settings.provider_connection_or_raise()


def _require_selection_matches_configured_provider(
    *,
    configured,
    selection,
) -> None:
    if selection.provider_name != configured.provider_name:
        raise ValueError(
            "agent runtime profile provider_name must match the configured "
            "local provider mode."
        )
    if selection.model_name != configured.model_name:
        raise ValueError(
            "agent runtime profile model_name must match the configured "
            "local provider mode."
        )


def build_local_workspace_file_operation_use_case(
    connection: sqlite3.Connection,
    *,
    workspace_id: WorkspaceId | str,
    policy: WorkspaceFileOperationPolicy | None = None,
) -> WorkspaceFileOperationUseCase:
    """Compose controlled, audited workspace file operations for local runtime."""

    resolved_workspace_id = _workspace_id(workspace_id)
    workspace_record = SqliteWorkspaceStateStore(connection).get_workspace_state(
        resolved_workspace_id
    )
    if workspace_record is None:
        raise ValueError("workspace state not found.")

    workspace = workspace_record.workspace
    binding = ProjectBinding.bind(
        workspace_id=workspace.workspace_id,
        local_root_path=workspace.root_path,
        writable=False,
    )
    return WorkspaceFileOperationUseCase(
        request_factory=WorkspaceFileOperationRequestFactory(
            workspace=workspace,
            binding=binding,
            policy=policy or WorkspaceFileOperationPolicy(),
        ),
        operation_service=FileOperationService(
            executor=WorkspaceFileOperationAdapter(
                workspace_id=workspace.workspace_id,
                root_path=binding.local_root_path,
            ),
            audit_recorder=SqliteFileOperationRecordStore(connection),
        ),
    )


def build_local_platform_operation_service(
    connection: sqlite3.Connection,
) -> LocalPlatformOperationService:
    """Compose local API-wrap-ready platform operations over current state."""

    return LocalPlatformOperationService(
        workspace_reader=SqliteWorkspaceStateStore(connection),
        context_reader=SqliteContextStateStore(connection),
        context_update_recorder=SqliteContextUpdateEventRecorder(connection),
        event_log_reader=SqlitePlatformEventLog(connection),
        agent_invocation_reader=SqliteAgentInvocationRecordStore(connection),
        file_operation_reader=SqliteFileOperationRecordStore(connection),
        conversation_session_reader=SqliteConversationStore(connection),
        conversation_message_reader=SqliteConversationStore(connection),
        agent_registration_reader=SqliteAgentRegistrationStateStore(connection),
        task_reader=SqliteTaskStateStore(connection),
        issue_reader=SqliteIssueStateStore(connection),
        workspace_writer=SqliteWorkspaceStateStore(connection),
        context_writer=SqliteContextStateStore(connection),
        agent_registration_writer=SqliteAgentRegistrationStateStore(connection),
        conversation_session_writer=SqliteConversationStore(connection),
        conversation_message_writer=SqliteConversationStore(connection),
    )


def connect_local_platform_database(database: str | Path) -> sqlite3.Connection:
    if database != ":memory:":
        database_path = Path(database)
        parent = database_path.parent
        if parent != Path(".") and not parent.exists():
            raise ValueError("database parent directory does not exist.")
    return configure_sqlite_platform_connection(sqlite3.connect(database))


def _workspace_id(value: WorkspaceId | str) -> WorkspaceId:
    return value if isinstance(value, WorkspaceId) else WorkspaceId(value)
