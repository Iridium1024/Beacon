from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.domain.entities.file_operation import (
    FileOperationKind,
    FileOperationRequest,
    FileOperationResultStatus,
)
from agent_os.domain.value_objects.identifiers import WorkspaceId
from agent_os.infrastructure.adapters.filesystem.workspace_file_operations import (
    WorkspaceFileOperationAdapter,
    WorkspacePathViolation,
    resolve_workspace_relative_path,
)


class WorkspaceFileOperationAdapterTests(unittest.TestCase):
    def test_read_file_returns_content_inside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_file(root / "docs" / "note.md", "hello")
            adapter = WorkspaceFileOperationAdapter(
                workspace_id=WorkspaceId("workspace-1"),
                root_path=root,
            )
            request = FileOperationRequest.create(
                workspace_id=WorkspaceId("workspace-1"),
                operation_kind=FileOperationKind.READ_FILE,
                relative_path="docs/note.md",
            )

            result = adapter.execute_file_operation(request)

        self.assertEqual(result.status, FileOperationResultStatus.SUCCEEDED)
        self.assertEqual(result.output_payload["content"], "hello")
        self.assertEqual(result.output_payload["encoding"], "utf-8")
        self.assertEqual(result.bytes_read, 5)

    def test_list_directory_returns_non_recursive_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_file(root / "docs" / "a.txt", "a")
            _write_file(root / "docs" / "nested" / "b.txt", "b")
            adapter = WorkspaceFileOperationAdapter(
                workspace_id=WorkspaceId("workspace-1"),
                root_path=root,
            )
            request = FileOperationRequest.create(
                workspace_id=WorkspaceId("workspace-1"),
                operation_kind=FileOperationKind.LIST_DIRECTORY,
                relative_path="docs",
            )

            result = adapter.execute_file_operation(request)

        self.assertEqual(result.status, FileOperationResultStatus.SUCCEEDED)
        self.assertEqual(
            result.output_payload["entries"],
            (
                {
                    "name": "a.txt",
                    "relative_path": "docs/a.txt",
                    "kind": "file",
                    "size_bytes": 1,
                },
                {
                    "name": "nested",
                    "relative_path": "docs/nested",
                    "kind": "directory",
                },
            ),
        )

    def test_write_file_is_denied_and_does_not_change_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_path = root / "docs" / "note.md"
            _write_file(target_path, "old")
            adapter = WorkspaceFileOperationAdapter(
                workspace_id=WorkspaceId("workspace-1"),
                root_path=root,
            )
            request = FileOperationRequest.create(
                workspace_id=WorkspaceId("workspace-1"),
                operation_kind=FileOperationKind.WRITE_FILE,
                relative_path="docs/note.md",
                content="new",
            )

            result = adapter.execute_file_operation(request)
            with target_path.open("r", encoding="utf-8") as file_handle:
                content = file_handle.read()

        self.assertEqual(result.status, FileOperationResultStatus.DENIED)
        self.assertEqual(content, "old")
        self.assertIn("Write file operations are not enabled", result.error_message or "")

    def test_workspace_mismatch_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_file(root / "docs" / "note.md", "hello")
            adapter = WorkspaceFileOperationAdapter(
                workspace_id=WorkspaceId("workspace-1"),
                root_path=root,
            )
            request = FileOperationRequest.create(
                workspace_id=WorkspaceId("workspace-2"),
                operation_kind=FileOperationKind.READ_FILE,
                relative_path="docs/note.md",
            )

            result = adapter.execute_file_operation(request)

        self.assertEqual(result.status, FileOperationResultStatus.DENIED)
        self.assertIn("different workspace", result.error_message or "")

    def test_recursive_directory_listing_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_file(root / "docs" / "nested" / "b.txt", "b")
            adapter = WorkspaceFileOperationAdapter(
                workspace_id=WorkspaceId("workspace-1"),
                root_path=root,
            )
            request = FileOperationRequest.create(
                workspace_id=WorkspaceId("workspace-1"),
                operation_kind=FileOperationKind.LIST_DIRECTORY,
                relative_path="docs",
                recursive=True,
            )

            result = adapter.execute_file_operation(request)

        self.assertEqual(result.status, FileOperationResultStatus.DENIED)
        self.assertIn("Recursive directory listing is not enabled", result.error_message or "")

    def test_missing_read_target_fails_without_leaving_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = WorkspaceFileOperationAdapter(
                workspace_id=WorkspaceId("workspace-1"),
                root_path=Path(temp_dir),
            )
            request = FileOperationRequest.create(
                workspace_id=WorkspaceId("workspace-1"),
                operation_kind=FileOperationKind.READ_FILE,
                relative_path="docs/missing.md",
            )

            result = adapter.execute_file_operation(request)

        self.assertEqual(result.status, FileOperationResultStatus.FAILED)
        self.assertIn("does not exist", result.error_message or "")

    def test_path_resolution_rejects_escape_and_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaises(WorkspacePathViolation):
                resolve_workspace_relative_path(root, "../outside.txt")
            with self.assertRaises(WorkspacePathViolation):
                resolve_workspace_relative_path(root, str(root / "outside.txt"))


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_handle:
        file_handle.write(content)


if __name__ == "__main__":
    unittest.main()
