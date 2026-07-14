from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.file_operation_request_factory import (
    WorkspaceFileOperationPolicy,
    WorkspaceFileOperationRequestFactory,
)
from agent_os.domain.entities.file_operation import FileOperationKind
from agent_os.domain.entities.workspace import ProjectBinding, ProjectWorkspace
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    FileOperationId,
    TaskId,
    WorkspaceId,
)


class WorkspaceFileOperationRequestFactoryTests(unittest.TestCase):
    def test_create_read_request_uses_workspace_binding_scope(self) -> None:
        requested_at = datetime(2026, 6, 4, 0, 50, tzinfo=timezone.utc)
        factory = WorkspaceFileOperationRequestFactory(
            workspace=_workspace(),
            binding=_binding(),
        )

        request = factory.create_request(
            operation_id=FileOperationId("file-op-1"),
            operation_kind=FileOperationKind.READ_FILE,
            relative_path="docs/status.md",
            requested_at=requested_at,
            requested_by_agent_id=AgentId("agent-1"),
            invocation_id=AgentInvocationId("invoke-1"),
            task_id=TaskId("task-1"),
            reason="Read bounded task status",
            metadata={"source": "factory-test"},
        )

        self.assertEqual(request.operation_id.value, "file-op-1")
        self.assertEqual(request.workspace_id, WorkspaceId("workspace-1"))
        self.assertEqual(request.operation_kind, FileOperationKind.READ_FILE)
        self.assertEqual(request.relative_path, "docs/status.md")
        self.assertEqual(request.requested_at, requested_at)
        self.assertEqual(request.requested_by_agent_id, AgentId("agent-1"))
        self.assertEqual(request.invocation_id, AgentInvocationId("invoke-1"))
        self.assertEqual(request.task_id, TaskId("task-1"))
        self.assertEqual(request.metadata["source"], "factory-test")

    def test_create_list_directory_request_allows_non_recursive_root_listing(self) -> None:
        factory = WorkspaceFileOperationRequestFactory(
            workspace=_workspace(),
            binding=_binding(),
        )

        request = factory.create_request(
            operation_kind=FileOperationKind.LIST_DIRECTORY,
            relative_path=".",
        )

        self.assertEqual(request.workspace_id, WorkspaceId("workspace-1"))
        self.assertEqual(request.operation_kind, FileOperationKind.LIST_DIRECTORY)
        self.assertEqual(request.relative_path, ".")
        self.assertFalse(request.recursive)

    def test_default_policy_denies_write_even_for_writable_binding(self) -> None:
        factory = WorkspaceFileOperationRequestFactory(
            workspace=_workspace(),
            binding=_binding(writable=True),
        )

        with self.assertRaisesRegex(ValueError, "write file operations are not allowed by workspace policy"):
            factory.create_request(
                operation_kind=FileOperationKind.WRITE_FILE,
                relative_path="docs/status.md",
                content="new",
            )

    def test_read_only_binding_denies_write_even_when_policy_allows_write(self) -> None:
        factory = WorkspaceFileOperationRequestFactory(
            workspace=_workspace(),
            binding=_binding(writable=False),
            policy=WorkspaceFileOperationPolicy(allow_write_file=True),
        )

        with self.assertRaisesRegex(ValueError, "read-only workspace binding"):
            factory.create_request(
                operation_kind=FileOperationKind.WRITE_FILE,
                relative_path="docs/status.md",
                content="new",
            )

    def test_default_policy_denies_recursive_listing(self) -> None:
        factory = WorkspaceFileOperationRequestFactory(
            workspace=_workspace(),
            binding=_binding(),
        )

        with self.assertRaisesRegex(ValueError, "recursive directory listing"):
            factory.create_request(
                operation_kind=FileOperationKind.LIST_DIRECTORY,
                relative_path="docs",
                recursive=True,
            )

    def test_factory_rejects_workspace_binding_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "same workspace_id"):
            WorkspaceFileOperationRequestFactory(
                workspace=_workspace(),
                binding=_binding(workspace_id=WorkspaceId("workspace-2")),
            )

    def test_factory_rejects_archived_workspace(self) -> None:
        with self.assertRaisesRegex(ValueError, "active workspace"):
            WorkspaceFileOperationRequestFactory(
                workspace=_workspace().archive(),
                binding=_binding(),
            )


def _workspace() -> ProjectWorkspace:
    return ProjectWorkspace.create(
        workspace_id=WorkspaceId("workspace-1"),
        display_name="Workspace",
        root_path="X:/fixture/workspace",
    )


def _binding(
    *,
    workspace_id: WorkspaceId = WorkspaceId("workspace-1"),
    writable: bool = True,
) -> ProjectBinding:
    return ProjectBinding.bind(
        workspace_id=workspace_id,
        local_root_path="X:/fixture/workspace",
        writable=writable,
    )


if __name__ == "__main__":
    unittest.main()
