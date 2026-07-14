from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.file_operation_service import FileOperationService
from agent_os.domain.entities.file_operation import (
    FileOperationKind,
    FileOperationRequest,
    FileOperationResult,
    FileOperationResultStatus,
)
from agent_os.domain.entities.workspace import ProjectWorkspace
from agent_os.domain.value_objects.identifiers import FileOperationId, PlatformEventId, WorkspaceId
from agent_os.infrastructure.adapters.filesystem.workspace_file_operations import (
    WorkspaceFileOperationAdapter,
)
from agent_os.infrastructure.persistence.file_operation_records import (
    SqliteFileOperationRecordStore,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteWorkspaceStateStore,
)
from agent_os.infrastructure.persistence.sqlite_persistence import SqlitePlatformPersistence


class FileOperationServiceTests(unittest.TestCase):
    def test_execute_read_file_records_audit_without_persisting_file_body(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_file(root / "docs" / "note.md", "hello")
            connection = _connection_with_workspace(root)
            store = SqliteFileOperationRecordStore(connection)
            service = FileOperationService(
                executor=WorkspaceFileOperationAdapter(
                    workspace_id=WorkspaceId("workspace-1"),
                    root_path=root,
                ),
                audit_recorder=store,
            )
            request = FileOperationRequest.create(
                operation_id=FileOperationId("file-op-1"),
                workspace_id=WorkspaceId("workspace-1"),
                operation_kind=FileOperationKind.READ_FILE,
                relative_path="docs/note.md",
            )

            recorded = service.execute_and_record(
                request,
                event_id=PlatformEventId("event-1"),
                metadata={"source": "unit-test"},
            )

            record = store.get_file_operation_record(FileOperationId("file-op-1"))
            event_row = connection.execute(
                "SELECT sequence, payload_json, metadata_json FROM platform_events"
            ).fetchone()

        self.assertEqual(recorded.source_event_sequence, 1)
        self.assertEqual(recorded.result.status, FileOperationResultStatus.SUCCEEDED)
        self.assertEqual(recorded.result.output_payload["content"], "hello")
        assert record is not None
        self.assertEqual(record.source_event_sequence, 1)
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(record.bytes_read, 5)
        self.assertNotIn("content", record.output_payload)
        self.assertEqual(record.output_payload["content_persisted"], False)
        self.assertEqual(record.output_payload["content_length"], 5)
        self.assertEqual(record.output_payload["encoding"], "utf-8")
        self.assertEqual(record.metadata["result"]["content_redacted_from_audit"], True)
        self.assertEqual(event_row[0], 1)
        self.assertEqual(json.loads(event_row[1])["status"], "succeeded")
        self.assertEqual(json.loads(event_row[2])["source"], "unit-test")

    def test_execute_write_file_denial_is_recorded_without_changing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_path = root / "docs" / "note.md"
            _write_file(target_path, "old")
            connection = _connection_with_workspace(root)
            store = SqliteFileOperationRecordStore(connection)
            service = FileOperationService(
                executor=WorkspaceFileOperationAdapter(
                    workspace_id=WorkspaceId("workspace-1"),
                    root_path=root,
                ),
                audit_recorder=store,
            )
            request = FileOperationRequest.create(
                operation_id=FileOperationId("file-op-2"),
                workspace_id=WorkspaceId("workspace-1"),
                operation_kind=FileOperationKind.WRITE_FILE,
                relative_path="docs/note.md",
                content="new",
            )

            recorded = service.execute_and_record(request)
            with target_path.open("r", encoding="utf-8") as file_handle:
                content = file_handle.read()
            record = store.get_file_operation_record(FileOperationId("file-op-2"))

        self.assertEqual(recorded.result.status, FileOperationResultStatus.DENIED)
        self.assertEqual(content, "old")
        assert record is not None
        self.assertEqual(record.status, "denied")
        self.assertIn("Write file operations are not enabled", record.error_message or "")
        self.assertEqual(record.request_state["content_present"], True)
        self.assertEqual(record.request_state["content_persisted"], False)

    def test_executor_exception_is_converted_to_audited_failure(self) -> None:
        audit_recorder = _CapturingAuditRecorder()
        service = FileOperationService(
            executor=_FailingExecutor(),
            audit_recorder=audit_recorder,
        )
        request = FileOperationRequest.create(
            workspace_id=WorkspaceId("workspace-1"),
            operation_kind=FileOperationKind.READ_FILE,
            relative_path="docs/note.md",
        )

        recorded = service.execute_and_record(request)

        self.assertEqual(recorded.source_event_sequence, 42)
        self.assertEqual(recorded.result.status, FileOperationResultStatus.FAILED)
        self.assertIn("File operation executor raised RuntimeError", recorded.result.error_message or "")
        assert audit_recorder.result is not None
        self.assertEqual(audit_recorder.result.status, FileOperationResultStatus.FAILED)
        self.assertEqual(audit_recorder.request, request)


class _FailingExecutor:
    def execute_file_operation(self, request: FileOperationRequest) -> FileOperationResult:
        raise RuntimeError("boom")


class _CapturingAuditRecorder:
    def __init__(self) -> None:
        self.request: FileOperationRequest | None = None
        self.result: FileOperationResult | None = None

    def record_file_operation_event(
        self,
        *,
        request: FileOperationRequest,
        result: FileOperationResult | None = None,
        event_id: object | None = None,
        occurred_at: object | None = None,
        session_id: object | None = None,
        metadata: object | None = None,
    ) -> int:
        self.request = request
        self.result = result
        return 42


def _connection_with_workspace(root_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    SqlitePlatformPersistence(connection).initialize()
    workspace = ProjectWorkspace.create(
        workspace_id=WorkspaceId("workspace-1"),
        display_name="Workspace",
        root_path=str(root_path),
    )
    SqliteWorkspaceStateStore(connection).upsert_workspace_state(
        workspace=workspace,
        source_event_sequence=0,
    )
    return connection


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_handle:
        file_handle.write(content)


if __name__ == "__main__":
    unittest.main()
