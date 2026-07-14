from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.domain.value_objects.identifiers import AgentId, WorkspaceId
from agent_os.infrastructure.composition.local_platform_initialization import (
    LocalPlatformInitialState,
    initialize_local_platform_state,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteAgentRegistrationStateStore,
    SqliteContextStateStore,
    SqliteWorkspaceStateStore,
)
from agent_os.infrastructure.persistence.sqlite_persistence import (
    SqlitePlatformPersistence,
)


class LocalPlatformInitializationTests(unittest.TestCase):
    def test_initialize_stores_minimal_workspace_context_and_agent(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        initial_state = _initial_state()

        initialized = initialize_local_platform_state(connection, initial_state)

        workspace = SqliteWorkspaceStateStore(connection).get_workspace_state(
            WorkspaceId("workspace-init-1")
        )
        context = SqliteContextStateStore(connection).get_context_state(
            WorkspaceId("workspace-init-1")
        )
        agent = SqliteAgentRegistrationStateStore(
            connection
        ).get_agent_registration_state(AgentId("agent-init-1"))
        self.assertIsNotNone(workspace)
        self.assertIsNotNone(context)
        self.assertIsNotNone(agent)
        assert workspace is not None
        assert context is not None
        assert agent is not None
        self.assertEqual(initialized.workspace, workspace.workspace)
        self.assertEqual(initialized.context, context.context)
        self.assertEqual(
            initialized.agent_registration,
            agent.registration,
        )
        self.assertEqual(workspace.source_event_sequence, 0)
        self.assertEqual(context.context.materialized_state["status"], "ready")
        self.assertEqual(agent.registration.default_model, "deterministic-placeholder")
        self.assertTrue(agent.registration.has_capability("single-turn-status"))
        self.assertEqual(initialized.source_event_sequence, 0)
        self.assertFalse(initialized.platform_event_recorded)
        event_count = connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()
        assert event_count is not None
        self.assertEqual(event_count[0], 0)

    def test_initialize_rejects_non_seed_source_event_sequence(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()

        with self.assertRaisesRegex(ValueError, "seed baseline"):
            initialize_local_platform_state(
                connection,
                _initial_state(),
                source_event_sequence=1,
            )


def _initial_state() -> LocalPlatformInitialState:
    return LocalPlatformInitialState(
        workspace_id="workspace-init-1",
        context_id="context-init-1",
        agent_id="agent-init-1",
        workspace_display_name="Initialized Workspace",
        workspace_root="X:/fixture/workspace-init",
        agent_name="Initialized Agent",
        agent_description="Handles initialized local requests",
        agent_capability_name="single-turn-status",
        agent_capability_description="Captures initialized single-turn requests",
        context_materialized_state={"status": "ready"},
        created_at=datetime(2026, 6, 4, 23, 1, tzinfo=timezone.utc),
    )


if __name__ == "__main__":
    unittest.main()
