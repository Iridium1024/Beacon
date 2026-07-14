from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.domain.entities.agent import (
    AgentCapability,
    AgentRegistration,
    AgentRegistrationStatus,
)
from agent_os.domain.value_objects.identifiers import AgentId, WorkspaceId


class AgentRegistrationTests(unittest.TestCase):
    def test_register_scopes_agent_to_workspace_and_config(self) -> None:
        timestamp = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)

        registration = AgentRegistration.register(
            agent_id=AgentId("agent-1"),
            workspace_id=WorkspaceId("workspace-1"),
            name="Planner",
            description="Plans project tasks",
            capabilities=(
                AgentCapability(
                    name="plan_tasks",
                    description="Breaks project requests into tasks",
                    metadata={"kind": "planning"},
                ),
            ),
            created_at=timestamp,
            default_model="local/planner",
            tool_permissions=("workspace.read",),
            runtime_config={"temperature": 0},
            metadata={"role": "planner"},
        )

        self.assertEqual(registration.agent_id.value, "agent-1")
        self.assertEqual(registration.workspace_id.value, "workspace-1")
        self.assertEqual(registration.status, AgentRegistrationStatus.ACTIVE)
        self.assertEqual(registration.created_at, timestamp)
        self.assertEqual(registration.updated_at, timestamp)
        self.assertEqual(registration.default_model, "local/planner")
        self.assertEqual(registration.tool_permissions, ("workspace.read",))
        self.assertEqual(registration.runtime_config["temperature"], 0)
        self.assertTrue(registration.has_capability("plan_tasks"))
        self.assertFalse(registration.has_capability("write_files"))

    def test_updates_return_new_snapshots(self) -> None:
        created_at = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)
        updated_at = datetime(2026, 6, 2, 10, 5, tzinfo=timezone.utc)
        registration = AgentRegistration.register(
            workspace_id=WorkspaceId("workspace-1"),
            name="Executor",
            description="Executes bounded project tasks",
            capabilities=(
                AgentCapability(
                    name="execute_task",
                    description="Runs a bounded task",
                ),
            ),
            created_at=created_at,
            runtime_config={"profile": "initial"},
            tool_permissions=("workspace.read",),
        )

        configured = registration.with_runtime_config(
            {"profile": "mvp", "max_files": 5},
            updated_at=updated_at,
        )
        permitted = configured.with_tool_permissions(
            ("workspace.read", "workspace.write"),
            updated_at=updated_at,
        )
        disabled = permitted.transition(
            AgentRegistrationStatus.DISABLED,
            updated_at=updated_at,
        )

        self.assertEqual(registration.runtime_config["profile"], "initial")
        self.assertEqual(registration.tool_permissions, ("workspace.read",))
        self.assertEqual(configured.runtime_config["profile"], "mvp")
        self.assertEqual(permitted.tool_permissions, ("workspace.read", "workspace.write"))
        self.assertEqual(disabled.status, AgentRegistrationStatus.DISABLED)
        self.assertEqual(disabled.updated_at, updated_at)

    def test_rejects_empty_required_fields_and_default_model(self) -> None:
        capability = AgentCapability(
            name="plan_tasks",
            description="Breaks project requests into tasks",
        )

        with self.assertRaises(ValueError):
            AgentRegistration.register(
                workspace_id=WorkspaceId("workspace-1"),
                name="",
                description="Plans project tasks",
                capabilities=(capability,),
            )

        with self.assertRaises(ValueError):
            AgentRegistration.register(
                workspace_id=WorkspaceId("workspace-1"),
                name="Planner",
                description=" ",
                capabilities=(capability,),
            )

        with self.assertRaises(ValueError):
            AgentRegistration.register(
                workspace_id=WorkspaceId("workspace-1"),
                name="Planner",
                description="Plans project tasks",
                capabilities=(capability,),
                default_model=" ",
            )

    def test_rejects_missing_or_duplicate_capabilities(self) -> None:
        with self.assertRaises(ValueError):
            AgentRegistration.register(
                workspace_id=WorkspaceId("workspace-1"),
                name="Planner",
                description="Plans project tasks",
                capabilities=(),
            )

        with self.assertRaises(ValueError):
            AgentRegistration.register(
                workspace_id=WorkspaceId("workspace-1"),
                name="Planner",
                description="Plans project tasks",
                capabilities=(
                    AgentCapability(name="plan_tasks", description="Plans tasks"),
                    AgentCapability(name="plan_tasks", description="Duplicate"),
                ),
            )

        with self.assertRaises(ValueError):
            AgentRegistration.register(
                workspace_id=WorkspaceId("workspace-1"),
                name="Planner",
                description="Plans project tasks",
                capabilities=(
                    AgentCapability(name=" ", description="Missing name"),
                ),
            )

    def test_rejects_duplicate_tool_permissions(self) -> None:
        registration = AgentRegistration.register(
            workspace_id=WorkspaceId("workspace-1"),
            name="Executor",
            description="Executes bounded project tasks",
            capabilities=(
                AgentCapability(
                    name="execute_task",
                    description="Runs a bounded task",
                ),
            ),
        )

        with self.assertRaises(ValueError):
            registration.with_tool_permissions(
                ("workspace.read", "workspace.read"),
            )

        with self.assertRaises(ValueError):
            registration.with_tool_permissions((" ",))


if __name__ == "__main__":
    unittest.main()
