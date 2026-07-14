from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.domain.entities.file_operation import (
    FileOperationKind,
    FileOperationRequest,
    FileOperationResult,
    FileOperationResultStatus,
)
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextUpdateId,
    FileOperationId,
    TaskId,
    WorkspaceId,
)


class FileOperationRequestTests(unittest.TestCase):
    def test_create_read_request_scopes_operation_to_workspace_and_invocation(self) -> None:
        timestamp = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)

        request = FileOperationRequest.create(
            operation_id=FileOperationId("file-op-1"),
            workspace_id=WorkspaceId("workspace-1"),
            operation_kind=FileOperationKind.READ_FILE,
            relative_path="docs/state_snapshot_fixture.json",
            requested_at=timestamp,
            requested_by_agent_id=AgentId("agent-1"),
            invocation_id=AgentInvocationId("invoke-1"),
            task_id=TaskId("task-1"),
            reason="Read current migration state",
            metadata={"source": "test"},
        )

        self.assertEqual(request.operation_id.value, "file-op-1")
        self.assertEqual(request.workspace_id.value, "workspace-1")
        self.assertEqual(request.operation_kind, FileOperationKind.READ_FILE)
        self.assertEqual(request.relative_path, "docs/state_snapshot_fixture.json")
        self.assertEqual(request.requested_at, timestamp)
        self.assertEqual(request.requested_by_agent_id, AgentId("agent-1"))
        self.assertEqual(request.invocation_id, AgentInvocationId("invoke-1"))
        self.assertEqual(request.task_id, TaskId("task-1"))
        self.assertFalse(hasattr(request, "final_answer_candidate"))

    def test_write_request_requires_content_and_allows_empty_file_body(self) -> None:
        request = FileOperationRequest.create(
            workspace_id=WorkspaceId("workspace-1"),
            operation_kind=FileOperationKind.WRITE_FILE,
            relative_path="docs/new-note.md",
            content="",
            create_parents=True,
        )

        self.assertEqual(request.content, "")
        self.assertTrue(request.create_parents)

        with self.assertRaises(ValueError):
            FileOperationRequest.create(
                workspace_id=WorkspaceId("workspace-1"),
                operation_kind=FileOperationKind.WRITE_FILE,
                relative_path="docs/new-note.md",
            )

    def test_request_rejects_unsafe_paths_and_wrong_option_pairs(self) -> None:
        with self.assertRaises(ValueError):
            FileOperationRequest.create(
                workspace_id=WorkspaceId("workspace-1"),
                operation_kind=FileOperationKind.READ_FILE,
                relative_path="../secrets.txt",
            )

        with self.assertRaises(ValueError):
            FileOperationRequest.create(
                workspace_id=WorkspaceId("workspace-1"),
                operation_kind=FileOperationKind.READ_FILE,
                relative_path=r"C:\outside.txt",
            )

        with self.assertRaises(ValueError):
            FileOperationRequest.create(
                workspace_id=WorkspaceId("workspace-1"),
                operation_kind=FileOperationKind.READ_FILE,
                relative_path="docs/state_snapshot_fixture.json",
                content="unexpected",
            )

        with self.assertRaises(ValueError):
            FileOperationRequest.create(
                workspace_id=WorkspaceId("workspace-1"),
                operation_kind=FileOperationKind.READ_FILE,
                relative_path="docs/state_snapshot_fixture.json",
                create_parents=True,
            )

        root_listing = FileOperationRequest.create(
            workspace_id=WorkspaceId("workspace-1"),
            operation_kind=FileOperationKind.LIST_DIRECTORY,
            relative_path=".",
            recursive=True,
        )
        self.assertTrue(root_listing.recursive)


class FileOperationResultTests(unittest.TestCase):
    def test_succeed_read_result_links_request_and_context_update(self) -> None:
        completed_at = datetime(2026, 6, 2, 10, 1, tzinfo=timezone.utc)
        request = FileOperationRequest.create(
            operation_id=FileOperationId("file-op-1"),
            workspace_id=WorkspaceId("workspace-1"),
            operation_kind=FileOperationKind.READ_FILE,
            relative_path="docs/state_snapshot_fixture.json",
            requested_by_agent_id=AgentId("agent-1"),
            invocation_id=AgentInvocationId("invoke-1"),
        )

        result = FileOperationResult.succeed(
            request,
            completed_at=completed_at,
            context_update_id=ContextUpdateId("update-1"),
            bytes_read=128,
            output_payload={"sha256": "abc123"},
        )

        self.assertEqual(result.operation_id, request.operation_id)
        self.assertEqual(result.workspace_id, request.workspace_id)
        self.assertEqual(result.operation_kind, FileOperationKind.READ_FILE)
        self.assertEqual(result.status, FileOperationResultStatus.SUCCEEDED)
        self.assertEqual(result.completed_at, completed_at)
        self.assertEqual(result.requested_by_agent_id, AgentId("agent-1"))
        self.assertEqual(result.invocation_id, AgentInvocationId("invoke-1"))
        self.assertEqual(result.context_update_id, ContextUpdateId("update-1"))
        self.assertEqual(result.bytes_read, 128)
        self.assertEqual(result.output_payload["sha256"], "abc123")

    def test_succeed_write_result_tracks_bytes_written(self) -> None:
        request = FileOperationRequest.create(
            workspace_id=WorkspaceId("workspace-1"),
            operation_kind=FileOperationKind.WRITE_FILE,
            relative_path="docs/new-note.md",
            content="note",
        )

        result = FileOperationResult.succeed(
            request,
            context_update_id=ContextUpdateId("update-1"),
            bytes_written=4,
        )

        self.assertEqual(result.status, FileOperationResultStatus.SUCCEEDED)
        self.assertEqual(result.bytes_written, 4)
        self.assertEqual(result.context_update_id, ContextUpdateId("update-1"))

    def test_fail_and_deny_results_require_error_messages(self) -> None:
        request = FileOperationRequest.create(
            workspace_id=WorkspaceId("workspace-1"),
            operation_kind=FileOperationKind.READ_FILE,
            relative_path="docs/missing.md",
        )

        failed = FileOperationResult.fail(
            request,
            error_message="File not found",
        )
        denied = FileOperationResult.deny(
            request,
            error_message="Workspace is read-only",
        )

        self.assertEqual(failed.status, FileOperationResultStatus.FAILED)
        self.assertEqual(failed.error_message, "File not found")
        self.assertEqual(denied.status, FileOperationResultStatus.DENIED)
        self.assertEqual(denied.error_message, "Workspace is read-only")

        with self.assertRaises(ValueError):
            FileOperationResult.fail(request, error_message=" ")

    def test_result_rejects_wrong_byte_counters(self) -> None:
        read_request = FileOperationRequest.create(
            workspace_id=WorkspaceId("workspace-1"),
            operation_kind=FileOperationKind.READ_FILE,
            relative_path="docs/state_snapshot_fixture.json",
        )
        write_request = FileOperationRequest.create(
            workspace_id=WorkspaceId("workspace-1"),
            operation_kind=FileOperationKind.WRITE_FILE,
            relative_path="docs/new-note.md",
            content="note",
        )

        with self.assertRaises(ValueError):
            FileOperationResult.succeed(read_request, bytes_written=4)

        with self.assertRaises(ValueError):
            FileOperationResult.succeed(write_request, bytes_read=4)

        with self.assertRaises(ValueError):
            FileOperationResult.succeed(read_request, bytes_read=-1)


if __name__ == "__main__":
    unittest.main()
