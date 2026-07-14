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

from agent_os.application.services.file_operation_request_factory import (
    WorkspaceFileOperationRequestFactory,
)
from agent_os.application.services.file_operation_context_linker import (
    FileOperationContextLinker,
)
from agent_os.application.services.file_operation_service import FileOperationService
from agent_os.application.services.workspace_file_operation_use_case import (
    WorkspaceFileOperationUseCase,
)
from agent_os.domain.entities.context import ProjectSharedContext
from agent_os.domain.entities.file_operation import FileOperationResultStatus
from agent_os.domain.entities.workspace import ProjectBinding, ProjectWorkspace
from agent_os.domain.value_objects.identifiers import (
    ContextId,
    ContextUpdateId,
    FileOperationId,
    PlatformEventId,
    WorkspaceId,
)
from agent_os.infrastructure.adapters.filesystem.workspace_file_operations import (
    WorkspaceFileOperationAdapter,
)
from agent_os.infrastructure.persistence.context_update_events import (
    SqliteContextUpdateEventRecorder,
)
from agent_os.infrastructure.persistence.file_operation_records import (
    SqliteFileOperationRecordStore,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteContextStateStore,
    SqliteWorkspaceStateStore,
)
from agent_os.infrastructure.persistence.sqlite_persistence import SqlitePlatformPersistence


class WorkspaceFileOperationUseCaseTests(unittest.TestCase):
    def test_read_file_uses_factory_service_adapter_and_sqlite_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_file(root / "docs" / "note.md", "hello")
            connection = _connection_with_workspace(root)
            record_store = SqliteFileOperationRecordStore(connection)
            use_case = _use_case(root, record_store)

            recorded = use_case.read_file(
                operation_id=FileOperationId("file-op-1"),
                event_id=PlatformEventId("event-1"),
                relative_path="docs/note.md",
                request_metadata={"source": "use-case-test"},
                audit_metadata={"path": "read"},
            )

            record = record_store.get_file_operation_record(FileOperationId("file-op-1"))
            event_row = connection.execute(
                "SELECT sequence, payload_json, metadata_json FROM platform_events"
            ).fetchone()

        self.assertEqual(recorded.source_event_sequence, 1)
        self.assertEqual(recorded.result.status, FileOperationResultStatus.SUCCEEDED)
        self.assertEqual(recorded.result.output_payload["content"], "hello")
        assert record is not None
        self.assertEqual(record.source_event_sequence, 1)
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(record.request_state["metadata"]["source"], "use-case-test")
        self.assertNotIn("content", record.output_payload)
        self.assertEqual(record.output_payload["content_persisted"], False)
        self.assertEqual(record.output_payload["content_length"], 5)
        self.assertEqual(json.loads(event_row[1])["status"], "succeeded")
        self.assertEqual(json.loads(event_row[2])["path"], "read")

    def test_read_file_result_links_to_context_event_without_persisting_body(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_file(root / "docs" / "note.md", "hello")
            connection = _connection_with_workspace(root)
            record_store = SqliteFileOperationRecordStore(connection)
            use_case = _use_case(root, record_store)
            context = ProjectSharedContext.create(
                context_id=ContextId("context-1"),
                workspace_id=WorkspaceId("workspace-1"),
                materialized_state={"status": "open"},
            )

            file_recorded = use_case.read_file(
                operation_id=FileOperationId("file-op-context-1"),
                event_id=PlatformEventId("file-event-1"),
                relative_path="docs/note.md",
            )
            update = FileOperationContextLinker().build_update(
                result=file_recorded.result,
                source_event_sequence=file_recorded.source_event_sequence,
                update_id=ContextUpdateId("context-update-1"),
            )
            context_recorded = SqliteContextUpdateEventRecorder(
                connection
            ).record_context_update_event(
                context=context,
                update=update,
                event_id=PlatformEventId("context-event-1"),
            )

            file_record = record_store.get_file_operation_record(
                FileOperationId("file-op-context-1")
            )
            event_rows = connection.execute(
                """
                SELECT sequence, event_kind, aggregate_type, aggregate_id, payload_json
                FROM platform_events
                ORDER BY sequence
                """
            ).fetchall()
            context_state = SqliteContextStateStore(connection).get_context_state(
                WorkspaceId("workspace-1")
            )

        self.assertEqual(file_recorded.source_event_sequence, 1)
        self.assertEqual(context_recorded.source_event_sequence, 2)
        self.assertEqual(file_recorded.result.output_payload["content"], "hello")
        assert file_record is not None
        self.assertNotIn("content", file_record.output_payload)
        self.assertEqual(file_record.output_payload["content_persisted"], False)
        self.assertEqual(file_record.output_payload["content_length"], 5)
        self.assertEqual(tuple(row[1] for row in event_rows), ("file_operation.recorded", "context.update_appended"))
        self.assertEqual(event_rows[0][2], "file_operation")
        self.assertEqual(event_rows[0][3], "file-op-context-1")
        self.assertEqual(event_rows[1][2], "context_update")
        self.assertEqual(event_rows[1][3], "context-update-1")
        context_payload = json.loads(event_rows[1][4])
        output_payload = context_payload["payload"]["file_operation"]["output_payload"]
        self.assertNotIn("content", output_payload)
        self.assertEqual(output_payload["content_persisted"], False)
        self.assertEqual(output_payload["content_length"], 5)
        self.assertEqual(output_payload["encoding"], "utf-8")
        self.assertEqual(
            context_payload["payload"]["file_operation"]["source_event_sequence"],
            1,
        )
        assert context_state is not None
        self.assertEqual(context_state.source_event_sequence, 2)
        self.assertEqual(context_state.update_count, 1)
        self.assertEqual(
            context_state.context.materialized_state["last_file_operation"]["operation_id"],
            "file-op-context-1",
        )
        self.assertEqual(
            context_state.context.materialized_state["last_file_operation"]["source_event_sequence"],
            1,
        )

    def test_list_directory_uses_same_local_audited_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_file(root / "docs" / "a.txt", "a")
            _write_file(root / "docs" / "nested" / "b.txt", "b")
            connection = _connection_with_workspace(root)
            record_store = SqliteFileOperationRecordStore(connection)
            use_case = _use_case(root, record_store)

            recorded = use_case.list_directory(
                operation_id=FileOperationId("file-op-2"),
                relative_path="docs",
            )

            record = record_store.get_file_operation_record(FileOperationId("file-op-2"))

        self.assertEqual(recorded.source_event_sequence, 1)
        self.assertEqual(recorded.result.status, FileOperationResultStatus.SUCCEEDED)
        self.assertEqual(
            recorded.result.output_payload["entries"],
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
        assert record is not None
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(record.operation_kind, "list_directory")

    def test_recursive_listing_is_rejected_before_audit_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_file(root / "docs" / "nested" / "b.txt", "b")
            connection = _connection_with_workspace(root)
            record_store = SqliteFileOperationRecordStore(connection)
            use_case = _use_case(root, record_store)

            with self.assertRaisesRegex(ValueError, "recursive directory listing"):
                use_case.list_directory(
                    operation_id=FileOperationId("file-op-3"),
                    relative_path="docs",
                    recursive=True,
                )

            event_count = connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0]
            record = record_store.get_file_operation_record(FileOperationId("file-op-3"))

        self.assertEqual(event_count, 0)
        self.assertIsNone(record)


def _use_case(
    root: Path,
    record_store: SqliteFileOperationRecordStore,
) -> WorkspaceFileOperationUseCase:
    workspace = ProjectWorkspace.create(
        workspace_id=WorkspaceId("workspace-1"),
        display_name="Workspace",
        root_path=str(root),
    )
    binding = ProjectBinding.bind(
        workspace_id=workspace.workspace_id,
        local_root_path=str(root),
        writable=False,
    )
    return WorkspaceFileOperationUseCase(
        request_factory=WorkspaceFileOperationRequestFactory(
            workspace=workspace,
            binding=binding,
        ),
        operation_service=FileOperationService(
            executor=WorkspaceFileOperationAdapter(
                workspace_id=workspace.workspace_id,
                root_path=binding.local_root_path,
            ),
            audit_recorder=record_store,
        ),
    )


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
