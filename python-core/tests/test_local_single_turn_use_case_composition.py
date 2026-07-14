from __future__ import annotations

import sqlite3
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.local_single_turn_platform_use_case import (
    LocalSingleTurnPlatformUseCase,
)
from agent_os.application.services.provider_backed_agent_invocation_adapter import (
    ProviderBackedAgentInvocationAdapter,
)
from agent_os.domain.entities.agent import AgentCapability, AgentRegistration
from agent_os.domain.entities.context import ProjectSharedContext
from agent_os.domain.entities.workspace import ProjectWorkspace
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextId,
    ContextUpdateId,
    PlatformEventId,
    PlatformRunSessionId,
    WorkspaceId,
)
from agent_os.infrastructure.composition.local_single_turn_use_case import (
    SqliteLocalSingleTurnPlatformUseCaseComponents,
    build_sqlite_local_single_turn_platform_use_case,
)
from agent_os.infrastructure.adapters.models import DeterministicModelProvider
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteAgentRegistrationStateStore,
    SqliteContextStateStore,
    SqliteWorkspaceStateStore,
)
from agent_os.infrastructure.persistence.sqlite_persistence import SqlitePlatformPersistence


class SqliteLocalSingleTurnPlatformUseCaseCompositionTests(unittest.TestCase):
    def test_build_loads_persisted_state_and_runs_use_case(self) -> None:
        connection = self._connection()
        self._store_workspace_context_and_agent(connection)

        components = build_sqlite_local_single_turn_platform_use_case(
            connection,
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
        )

        self.assertIsInstance(
            components,
            SqliteLocalSingleTurnPlatformUseCaseComponents,
        )
        self.assertIsInstance(components.use_case, LocalSingleTurnPlatformUseCase)
        self.assertEqual(components.workspace.workspace_id, WorkspaceId("workspace-1"))
        self.assertEqual(components.context.context_id, ContextId("context-1"))
        self.assertEqual(components.agent_registration.agent_id, AgentId("agent-1"))
        self.assertIs(
            components.use_case.runtime,
            components.runtime_components.runtime,
        )
        self.assertIs(
            components.use_case.request_factory,
            components.request_factory,
        )

        result = components.use_case.run(
            invocation_id=AgentInvocationId("invoke-1"),
            instruction="Run local composed single-turn use case.",
            requested_at=datetime(2026, 6, 4, 7, 15, tzinfo=timezone.utc),
            requested_capability="single-turn-status",
            update_id=ContextUpdateId("update-user-1"),
            event_id=PlatformEventId("event-context-1"),
            invocation_event_id=PlatformEventId("event-invoke-1"),
            session_id=PlatformRunSessionId("session-1"),
        )

        stored_context = SqliteContextStateStore(connection).get_context_state(
            WorkspaceId("workspace-1")
        )
        assert components.runtime_components.agent_invocation_recorder is not None
        record = (
            components.runtime_components.agent_invocation_recorder
            .get_agent_invocation_record(AgentInvocationId("invoke-1"))
        )

        self.assertEqual(result.run_session_started_event_sequence, 1)
        self.assertEqual(result.recorded_context_update.source_event_sequence, 2)
        self.assertEqual(result.agent_invocation_requested_event_sequence, 3)
        self.assertEqual(result.agent_invocation_event_sequence, 4)
        self.assertEqual(result.run_session_terminal_event_sequence, 5)
        self.assertIsNotNone(stored_context)
        assert stored_context is not None
        self.assertEqual(stored_context.update_count, 1)
        self.assertEqual(
            stored_context.context.materialized_state["last_user_instruction"][
                "invocation_id"
            ],
            "invoke-1",
        )
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(record.source_event_sequence, 4)
        self.assertFalse(result.invocation_result.output_payload["model_invoked"])
        self.assertEqual(
            result.invocation_result.metadata["source"],
            "deterministic_agent_invocation_adapter",
        )

    def test_build_accepts_provider_backed_agent_invocation_adapter(self) -> None:
        connection = self._connection()
        self._store_workspace_context_and_agent(connection)
        adapter = ProviderBackedAgentInvocationAdapter(
            model_provider=DeterministicModelProvider(),
            provider_name="deterministic",
            model_name="deterministic-text",
        )

        components = build_sqlite_local_single_turn_platform_use_case(
            connection,
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
            agent_invocation_adapter=adapter,
        )
        result = components.use_case.run(
            invocation_id=AgentInvocationId("invoke-provider-1"),
            instruction="Run with provider-backed adapter.",
            requested_at=datetime(2026, 6, 4, 7, 20, tzinfo=timezone.utc),
            requested_capability="single-turn-status",
            update_id=ContextUpdateId("update-provider-1"),
            event_id=PlatformEventId("event-context-provider-1"),
            invocation_event_id=PlatformEventId("event-invoke-provider-1"),
        )

        self.assertTrue(result.invocation_result.output_payload["model_invoked"])
        self.assertFalse(result.invocation_result.output_payload["tool_invoked"])
        self.assertEqual(
            result.invocation_result.output_text,
            "Deterministic model response: Run with provider-backed adapter.",
        )
        self.assertEqual(
            result.invocation_result.metadata["source"],
            "provider_backed_agent_invocation_adapter",
        )
        assert components.runtime_components.agent_invocation_recorder is not None
        record = (
            components.runtime_components.agent_invocation_recorder
            .get_agent_invocation_record(AgentInvocationId("invoke-provider-1"))
        )
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.status, "succeeded")

    def test_build_rejects_missing_workspace_state(self) -> None:
        connection = self._connection()

        with self.assertRaisesRegex(ValueError, "workspace state not found"):
            build_sqlite_local_single_turn_platform_use_case(
                connection,
                workspace_id=WorkspaceId("workspace-1"),
                agent_id=AgentId("agent-1"),
            )

    def test_build_rejects_missing_context_state(self) -> None:
        connection = self._connection()
        SqliteWorkspaceStateStore(connection).upsert_workspace_state(
            workspace=_workspace(),
            source_event_sequence=0,
        )

        with self.assertRaisesRegex(ValueError, "context state not found"):
            build_sqlite_local_single_turn_platform_use_case(
                connection,
                workspace_id=WorkspaceId("workspace-1"),
                agent_id=AgentId("agent-1"),
            )

    def test_build_rejects_missing_agent_registration_state(self) -> None:
        connection = self._connection()
        workspace = _workspace()
        SqliteWorkspaceStateStore(connection).upsert_workspace_state(
            workspace=workspace,
            source_event_sequence=0,
        )
        SqliteContextStateStore(connection).upsert_context_state(
            context=_context(),
            source_event_sequence=0,
        )

        with self.assertRaisesRegex(ValueError, "agent registration state not found"):
            build_sqlite_local_single_turn_platform_use_case(
                connection,
                workspace_id=WorkspaceId("workspace-1"),
                agent_id=AgentId("agent-1"),
            )

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        return connection

    def _store_workspace_context_and_agent(self, connection: sqlite3.Connection) -> None:
        SqliteWorkspaceStateStore(connection).upsert_workspace_state(
            workspace=_workspace(),
            source_event_sequence=0,
        )
        SqliteContextStateStore(connection).upsert_context_state(
            context=_context(),
            source_event_sequence=0,
        )
        SqliteAgentRegistrationStateStore(connection).upsert_agent_registration_state(
            registration=_agent_registration(),
            source_event_sequence=0,
        )


def _workspace() -> ProjectWorkspace:
    return ProjectWorkspace.create(
        workspace_id=WorkspaceId("workspace-1"),
        display_name="Workspace",
        root_path="X:/fixture/workspace",
    )


def _context() -> ProjectSharedContext:
    return ProjectSharedContext.create(
        context_id=ContextId("context-1"),
        workspace_id=WorkspaceId("workspace-1"),
        materialized_state={"status": "open"},
    )


def _agent_registration() -> AgentRegistration:
    return AgentRegistration.register(
        agent_id=AgentId("agent-1"),
        workspace_id=WorkspaceId("workspace-1"),
        name="Runtime Agent",
        description="Handles single-turn status requests",
        capabilities=(
            AgentCapability(
                name="single-turn-status",
                description="Captures single-turn status requests",
            ),
        ),
        created_at=datetime(2026, 6, 4, 7, 0, tzinfo=timezone.utc),
        default_model="deterministic-placeholder",
    )


if __name__ == "__main__":
    unittest.main()
