from __future__ import annotations

import sqlite3
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.single_turn_platform_runtime import (
    DeterministicAgentInvocationAdapter,
    SingleTurnPlatformRuntime,
)
from agent_os.domain.entities.agent import AgentCapability, AgentRegistration
from agent_os.domain.entities.context import ProjectSharedContext
from agent_os.domain.entities.invocation import AgentInvocationRequest
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
from agent_os.infrastructure.composition.single_turn_runtime import (
    SqliteSingleTurnPlatformRuntimeComponents,
    build_sqlite_single_turn_platform_runtime,
)
from agent_os.infrastructure.persistence.context_update_events import (
    SqliteContextUpdateEventRecorder,
)
from agent_os.infrastructure.persistence.invocation_records import (
    SqliteAgentInvocationRecordStore,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteAgentRegistrationStateStore,
    SqliteContextStateStore,
    SqliteWorkspaceStateStore,
)
from agent_os.infrastructure.persistence.sqlite_persistence import SqlitePlatformPersistence


class SqliteSingleTurnPlatformRuntimeCompositionTests(unittest.TestCase):
    def test_build_sqlite_single_turn_platform_runtime_wires_default_components(
        self,
    ) -> None:
        connection = self._connection()

        components = build_sqlite_single_turn_platform_runtime(connection)

        self.assertIsInstance(components, SqliteSingleTurnPlatformRuntimeComponents)
        self.assertIsInstance(components.runtime, SingleTurnPlatformRuntime)
        self.assertIsInstance(
            components.context_update_recorder,
            SqliteContextUpdateEventRecorder,
        )
        self.assertIsInstance(
            components.agent_invocation_recorder,
            SqliteAgentInvocationRecordStore,
        )
        self.assertIsInstance(
            components.agent_invocation_adapter,
            DeterministicAgentInvocationAdapter,
        )
        self.assertIs(
            components.runtime.context_update_recorder,
            components.context_update_recorder,
        )
        self.assertIs(
            components.runtime.agent_invocation_recorder,
            components.agent_invocation_recorder,
        )
        self.assertIs(
            components.runtime.run_session_lifecycle_recorder,
            components.run_session_lifecycle_recorder,
        )
        self.assertIs(
            components.runtime.agent_invocation_adapter,
            components.agent_invocation_adapter,
        )

    def test_composed_runtime_records_context_and_invocation_audit(self) -> None:
        connection = self._connection()
        context = self._context(connection)
        self._insert_agent_registration(connection)
        components = build_sqlite_single_turn_platform_runtime(connection)
        request = AgentInvocationRequest.create(
            invocation_id=AgentInvocationId("invoke-1"),
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
            instruction="Run composed single-turn runtime.",
            requested_at=datetime(2026, 6, 4, 5, 30, tzinfo=timezone.utc),
            requested_capability="single-turn-status",
            idempotency_key="idem-1",
            correlation_id="corr-1",
            metadata={"source": "unit-test"},
        )

        result = components.runtime.run_single_turn(
            context=context,
            invocation_request=request,
            update_id=ContextUpdateId("update-user-1"),
            event_id=PlatformEventId("event-context-1"),
            invocation_event_id=PlatformEventId("event-invoke-1"),
            session_id=PlatformRunSessionId("session-1"),
        )

        stored_context = SqliteContextStateStore(connection).get_context_state(
            WorkspaceId("workspace-1")
        )
        assert components.agent_invocation_recorder is not None
        record = components.agent_invocation_recorder.get_agent_invocation_record(
            AgentInvocationId("invoke-1")
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
        self.assertEqual(record.result_state["summary"], result.invocation_result.summary)
        self.assertEqual(
            tuple(update_id.value for update_id in record.context_update_ids),
            ("update-user-1",),
        )

    def test_build_can_disable_invocation_audit_recorder(self) -> None:
        connection = self._connection()

        components = build_sqlite_single_turn_platform_runtime(
            connection,
            record_agent_invocations=False,
        )

        self.assertIsNone(components.agent_invocation_recorder)
        self.assertIsNone(components.runtime.agent_invocation_recorder)
        self.assertIsInstance(
            components.agent_invocation_adapter,
            DeterministicAgentInvocationAdapter,
        )

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        return connection

    def _context(self, connection: sqlite3.Connection) -> ProjectSharedContext:
        workspace = ProjectWorkspace.create(
            workspace_id=WorkspaceId("workspace-1"),
            display_name="Workspace 1",
            root_path="/tmp/workspace-1",
        )
        SqliteWorkspaceStateStore(connection).upsert_workspace_state(
            workspace=workspace,
            source_event_sequence=0,
        )
        return ProjectSharedContext.create(
            context_id=ContextId("context-1"),
            workspace_id=WorkspaceId("workspace-1"),
            materialized_state={"status": "open"},
        )

    def _insert_agent_registration(self, connection: sqlite3.Connection) -> None:
        registration = AgentRegistration.register(
            agent_id=AgentId("agent-1"),
            workspace_id=WorkspaceId("workspace-1"),
            name="Local Runtime Agent",
            description="Handles deterministic single-turn runtime tests",
            capabilities=(
                AgentCapability(
                    name="single-turn-status",
                    description="Captures single-turn status requests",
                ),
            ),
            created_at=datetime(2026, 6, 4, 5, 0, tzinfo=timezone.utc),
            default_model="deterministic-placeholder",
        )
        SqliteAgentRegistrationStateStore(connection).upsert_agent_registration_state(
            registration=registration,
            source_event_sequence=0,
        )


if __name__ == "__main__":
    unittest.main()
