from __future__ import annotations

import sqlite3
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.agent_invocation_request_factory import (
    WorkspaceAgentInvocationRequestFactory,
)
from agent_os.application.services.local_single_turn_platform_use_case import (
    LocalSingleTurnPlatformUseCase,
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
from agent_os.infrastructure.composition.single_turn_runtime import (
    build_sqlite_single_turn_platform_runtime,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteAgentRegistrationStateStore,
    SqliteContextStateStore,
    SqliteWorkspaceStateStore,
)
from agent_os.infrastructure.persistence.sqlite_persistence import SqlitePlatformPersistence


class LocalSingleTurnPlatformUseCaseTests(unittest.TestCase):
    def test_run_creates_request_and_records_single_turn_result(self) -> None:
        connection = self._connection()
        workspace = _workspace()
        context = _context()
        agent_registration = _agent_registration()
        self._store_workspace_and_agent(connection, workspace, agent_registration)
        components = build_sqlite_single_turn_platform_runtime(connection)
        use_case = LocalSingleTurnPlatformUseCase(
            request_factory=WorkspaceAgentInvocationRequestFactory(
                workspace=workspace,
                context=context,
                agent_registration=agent_registration,
            ),
            runtime=components.runtime,
        )

        result = use_case.run(
            invocation_id=AgentInvocationId("invoke-1"),
            instruction="Summarize the current platform status.",
            requested_at=datetime(2026, 6, 4, 6, 40, tzinfo=timezone.utc),
            requested_capability="single-turn-status",
            file_references=("docs/state_snapshot_fixture.json",),
            idempotency_key="idem-1",
            correlation_id="corr-1",
            request_metadata={"phase": "use-case-test"},
            update_id=ContextUpdateId("update-user-1"),
            event_id=PlatformEventId("event-context-1"),
            invocation_event_id=PlatformEventId("event-invoke-1"),
            session_id=PlatformRunSessionId("session-1"),
            context_metadata={"context_phase": "capture"},
            event_metadata={"event_phase": "context"},
            invocation_event_metadata={"event_phase": "invocation"},
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
        self.assertEqual(result.user_context_update.update_id, ContextUpdateId("update-user-1"))
        self.assertEqual(
            result.user_context_update.payload["instruction"],
            "Summarize the current platform status.",
        )
        self.assertEqual(
            result.user_context_update.payload["file_references"],
            ["docs/state_snapshot_fixture.json"],
        )
        self.assertEqual(
            result.user_context_update.payload["request_metadata"]["context_id"],
            "context-1",
        )
        self.assertEqual(
            result.user_context_update.payload["request_metadata"]["source"],
            "workspace_agent_invocation_request_factory",
        )
        self.assertEqual(
            result.user_context_update.metadata["context_phase"],
            "capture",
        )
        self.assertIsNotNone(stored_context)
        assert stored_context is not None
        self.assertEqual(stored_context.update_count, 1)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.status, "succeeded")
        self.assertIsNone(record.task_id)
        self.assertEqual(record.result_state["summary"], result.invocation_result.summary)

    def test_run_rejects_unregistered_capability_before_recording(self) -> None:
        connection = self._connection()
        workspace = _workspace()
        context = _context()
        agent_registration = _agent_registration()
        self._store_workspace_and_agent(connection, workspace, agent_registration)
        components = build_sqlite_single_turn_platform_runtime(connection)
        use_case = LocalSingleTurnPlatformUseCase(
            request_factory=WorkspaceAgentInvocationRequestFactory(
                workspace=workspace,
                context=context,
                agent_registration=agent_registration,
            ),
            runtime=components.runtime,
        )

        with self.assertRaisesRegex(ValueError, "requested_capability"):
            use_case.run(
                instruction="Run unsupported request.",
                requested_capability="unsupported",
                event_id=PlatformEventId("event-context-1"),
            )

        self.assertEqual(
            connection.execute("SELECT count(*) FROM platform_events").fetchone()[0],
            0,
        )

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        return connection

    def _store_workspace_and_agent(
        self,
        connection: sqlite3.Connection,
        workspace: ProjectWorkspace,
        agent_registration: AgentRegistration,
    ) -> None:
        SqliteWorkspaceStateStore(connection).upsert_workspace_state(
            workspace=workspace,
            source_event_sequence=0,
        )
        SqliteAgentRegistrationStateStore(connection).upsert_agent_registration_state(
            registration=agent_registration,
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
        created_at=datetime(2026, 6, 4, 6, 30, tzinfo=timezone.utc),
        default_model="deterministic-placeholder",
    )


if __name__ == "__main__":
    unittest.main()
