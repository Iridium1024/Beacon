from __future__ import annotations

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
from agent_os.domain.entities.agent import (
    AgentCapability,
    AgentRegistration,
    AgentRegistrationStatus,
)
from agent_os.domain.entities.context import ProjectSharedContext
from agent_os.domain.entities.workspace import ProjectWorkspace
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextId,
    ContextUpdateId,
    TaskId,
    WorkspaceId,
)


class WorkspaceAgentInvocationRequestFactoryTests(unittest.TestCase):
    def test_create_request_uses_workspace_context_and_agent_scope(self) -> None:
        requested_at = datetime(2026, 6, 4, 6, 5, tzinfo=timezone.utc)
        factory = WorkspaceAgentInvocationRequestFactory(
            workspace=_workspace(),
            context=_context(),
            agent_registration=_agent_registration(),
        )

        request = factory.create_request(
            invocation_id=AgentInvocationId("invoke-1"),
            instruction="Summarize the current platform status.",
            requested_at=requested_at,
            task_id=TaskId("task-1"),
            requested_capability="single-turn-status",
            context_update_ids=(ContextUpdateId("context-update-1"),),
            file_references=("docs/status.md",),
            idempotency_key="idem-1",
            correlation_id="corr-1",
            metadata={"phase": "request-factory-test"},
        )

        self.assertEqual(request.invocation_id, AgentInvocationId("invoke-1"))
        self.assertEqual(request.workspace_id, WorkspaceId("workspace-1"))
        self.assertEqual(request.agent_id, AgentId("agent-1"))
        self.assertEqual(request.instruction, "Summarize the current platform status.")
        self.assertEqual(request.requested_at, requested_at)
        self.assertEqual(request.task_id, TaskId("task-1"))
        self.assertEqual(request.requested_capability, "single-turn-status")
        self.assertEqual(
            request.context_update_ids,
            (ContextUpdateId("context-update-1"),),
        )
        self.assertEqual(request.file_references, ("docs/status.md",))
        self.assertEqual(request.idempotency_key, "idem-1")
        self.assertEqual(request.correlation_id, "corr-1")
        self.assertEqual(request.metadata["context_id"], "context-1")
        self.assertEqual(
            request.metadata["source"],
            "workspace_agent_invocation_request_factory",
        )
        self.assertEqual(request.metadata["phase"], "request-factory-test")

    def test_factory_rejects_context_workspace_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "context must belong"):
            WorkspaceAgentInvocationRequestFactory(
                workspace=_workspace(),
                context=_context(workspace_id=WorkspaceId("workspace-2")),
                agent_registration=_agent_registration(),
            )

    def test_factory_rejects_agent_workspace_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "agent registration must belong"):
            WorkspaceAgentInvocationRequestFactory(
                workspace=_workspace(),
                context=_context(),
                agent_registration=_agent_registration(
                    workspace_id=WorkspaceId("workspace-2")
                ),
            )

    def test_factory_rejects_archived_workspace(self) -> None:
        with self.assertRaisesRegex(ValueError, "active workspace"):
            WorkspaceAgentInvocationRequestFactory(
                workspace=_workspace().archive(),
                context=_context(),
                agent_registration=_agent_registration(),
            )

    def test_factory_rejects_inactive_agent_registration(self) -> None:
        with self.assertRaisesRegex(ValueError, "active agent registration"):
            WorkspaceAgentInvocationRequestFactory(
                workspace=_workspace(),
                context=_context(),
                agent_registration=_agent_registration().transition(
                    AgentRegistrationStatus.DISABLED,
                    updated_at=datetime(2026, 6, 4, 6, 10, tzinfo=timezone.utc),
                ),
            )

    def test_create_request_rejects_unregistered_capability(self) -> None:
        factory = WorkspaceAgentInvocationRequestFactory(
            workspace=_workspace(),
            context=_context(),
            agent_registration=_agent_registration(),
        )

        with self.assertRaisesRegex(ValueError, "requested_capability"):
            factory.create_request(
                instruction="Run unsupported request.",
                requested_capability="unsupported",
            )


def _workspace() -> ProjectWorkspace:
    return ProjectWorkspace.create(
        workspace_id=WorkspaceId("workspace-1"),
        display_name="Workspace",
        root_path="X:/fixture/workspace",
    )


def _context(
    *,
    workspace_id: WorkspaceId = WorkspaceId("workspace-1"),
) -> ProjectSharedContext:
    return ProjectSharedContext.create(
        context_id=ContextId("context-1"),
        workspace_id=workspace_id,
    )


def _agent_registration(
    *,
    workspace_id: WorkspaceId = WorkspaceId("workspace-1"),
) -> AgentRegistration:
    return AgentRegistration.register(
        agent_id=AgentId("agent-1"),
        workspace_id=workspace_id,
        name="Runtime Agent",
        description="Handles single-turn status requests",
        capabilities=(
            AgentCapability(
                name="single-turn-status",
                description="Captures single-turn status requests",
            ),
        ),
        created_at=datetime(2026, 6, 4, 6, 0, tzinfo=timezone.utc),
    )


if __name__ == "__main__":
    unittest.main()
