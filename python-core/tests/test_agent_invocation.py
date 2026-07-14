from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.domain.entities.invocation import (
    AgentInvocationRequest,
    AgentInvocationResult,
    AgentInvocationResultStatus,
)
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextUpdateId,
    TaskId,
    WorkspaceId,
)


class AgentInvocationRequestTests(unittest.TestCase):
    def test_create_request_scopes_invocation_to_workspace_agent_and_task(self) -> None:
        timestamp = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)

        request = AgentInvocationRequest.create(
            invocation_id=AgentInvocationId("invoke-1"),
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
            instruction="Review the current project state",
            requested_at=timestamp,
            task_id=TaskId("task-1"),
            requested_capability="review_context",
            context_update_ids=(ContextUpdateId("update-1"),),
            file_references=("docs/state_snapshot_fixture.json",),
            idempotency_key="idem-1",
            correlation_id="corr-1",
            metadata={"source": "test"},
        )

        self.assertEqual(request.invocation_id.value, "invoke-1")
        self.assertEqual(request.workspace_id.value, "workspace-1")
        self.assertEqual(request.agent_id.value, "agent-1")
        self.assertEqual(request.instruction, "Review the current project state")
        self.assertEqual(request.requested_at, timestamp)
        self.assertEqual(request.task_id, TaskId("task-1"))
        self.assertEqual(request.requested_capability, "review_context")
        self.assertEqual(request.context_update_ids, (ContextUpdateId("update-1"),))
        self.assertEqual(request.file_references, ("docs/state_snapshot_fixture.json",))
        self.assertEqual(request.idempotency_key, "idem-1")
        self.assertEqual(request.correlation_id, "corr-1")

    def test_request_reference_updates_return_new_snapshots(self) -> None:
        request = AgentInvocationRequest.create(
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
            instruction="Read bounded context",
        )

        with_update = request.add_context_update(ContextUpdateId("update-1"))
        with_file = with_update.add_file_reference("python-core/src/agent_os/domain/entities/invocation.py")

        self.assertEqual(request.context_update_ids, ())
        self.assertEqual(request.file_references, ())
        self.assertEqual(with_update.context_update_ids, (ContextUpdateId("update-1"),))
        self.assertEqual(
            with_file.file_references,
            ("python-core/src/agent_os/domain/entities/invocation.py",),
        )

    def test_request_rejects_empty_fields_and_duplicate_references(self) -> None:
        with self.assertRaises(ValueError):
            AgentInvocationRequest.create(
                workspace_id=WorkspaceId("workspace-1"),
                agent_id=AgentId("agent-1"),
                instruction=" ",
            )

        request = AgentInvocationRequest.create(
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
            instruction="Read bounded context",
        )

        with self.assertRaises(ValueError):
            request.add_context_update(ContextUpdateId("update-1")).add_context_update(
                ContextUpdateId("update-1")
            )
        with self.assertRaises(ValueError):
            request.add_file_reference("docs/state_snapshot_fixture.json").add_file_reference(
                "docs/state_snapshot_fixture.json"
            )


class AgentInvocationResultTests(unittest.TestCase):
    def test_succeed_links_result_to_request_and_context_updates(self) -> None:
        requested_at = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)
        completed_at = datetime(2026, 6, 2, 10, 1, tzinfo=timezone.utc)
        request = AgentInvocationRequest.create(
            invocation_id=AgentInvocationId("invoke-1"),
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
            instruction="Summarize context",
            requested_at=requested_at,
        )

        result = AgentInvocationResult.succeed(
            request,
            summary="Context summarized",
            completed_at=completed_at,
            output_text="The project is ready for the next domain slice.",
            output_payload={"tokens": 12},
            context_update_ids=(ContextUpdateId("update-1"),),
        )

        self.assertEqual(result.invocation_id, request.invocation_id)
        self.assertEqual(result.workspace_id, request.workspace_id)
        self.assertEqual(result.agent_id, request.agent_id)
        self.assertEqual(result.status, AgentInvocationResultStatus.SUCCEEDED)
        self.assertEqual(result.completed_at, completed_at)
        self.assertEqual(result.output_text, "The project is ready for the next domain slice.")
        self.assertEqual(result.output_payload["tokens"], 12)
        self.assertEqual(result.context_update_ids, (ContextUpdateId("update-1"),))

    def test_fail_requires_error_message(self) -> None:
        request = AgentInvocationRequest.create(
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
            instruction="Summarize context",
        )

        failed = AgentInvocationResult.fail(
            request,
            summary="Provider unavailable",
            error_message="No provider adapter configured",
        )

        self.assertEqual(failed.status, AgentInvocationResultStatus.FAILED)
        self.assertEqual(failed.error_message, "No provider adapter configured")

        with self.assertRaises(ValueError):
            AgentInvocationResult.fail(
                request,
                summary="Provider unavailable",
                error_message=" ",
            )

    def test_result_rejects_empty_summary_and_duplicate_context_updates(self) -> None:
        request = AgentInvocationRequest.create(
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
            instruction="Summarize context",
        )

        with self.assertRaises(ValueError):
            AgentInvocationResult.succeed(
                request,
                summary="",
            )

        with self.assertRaises(ValueError):
            AgentInvocationResult.succeed(
                request,
                summary="Context summarized",
                context_update_ids=(
                    ContextUpdateId("update-1"),
                    ContextUpdateId("update-1"),
                ),
            )


if __name__ == "__main__":
    unittest.main()
