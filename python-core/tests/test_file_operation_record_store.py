from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.domain.entities.agent import AgentCapability, AgentRegistration
from agent_os.domain.entities.file_operation import (
    FileOperationKind,
    FileOperationRequest,
    FileOperationResult,
    FileOperationResultStatus,
)
from agent_os.domain.entities.invocation import AgentInvocationRequest
from agent_os.domain.entities.task import TaskContext
from agent_os.domain.entities.workspace import ProjectWorkspace
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextUpdateId,
    FileOperationId,
    PlatformEventId,
    PlatformRunSessionId,
    TaskId,
    WorkspaceId,
)
from agent_os.infrastructure.persistence.file_operation_records import (
    FILE_OPERATION_RECORD_SELECT_COLUMNS,
    FILE_OPERATION_RECORD_UPSERT_COLUMNS,
    FileOperationRecordEntry,
    SqliteFileOperationRecordStore,
    file_operation_record_upsert_row,
)
from agent_os.infrastructure.persistence.invocation_records import (
    SqliteAgentInvocationRecordStore,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteAgentRegistrationStateStore,
    SqliteTaskStateStore,
    SqliteWorkspaceStateStore,
)
from agent_os.infrastructure.persistence.sqlite_persistence import SqlitePlatformPersistence


class FileOperationRecordUpsertRowTests(unittest.TestCase):
    def test_file_operation_record_upsert_row_serializes_requested_request(self) -> None:
        request = _request()

        row = file_operation_record_upsert_row(
            request=request,
            source_event_sequence=21,
        )

        self.assertEqual(tuple(row.keys()), FILE_OPERATION_RECORD_UPSERT_COLUMNS)
        self.assertEqual(row["operation_id"], "file-op-1")
        self.assertEqual(row["workspace_id"], "workspace-1")
        self.assertEqual(row["source_event_sequence"], 21)
        self.assertEqual(row["operation_kind"], "write_file")
        self.assertEqual(row["relative_path"], "docs/status.md")
        self.assertEqual(row["status"], "requested")
        self.assertEqual(row["requested_by_agent_id"], "agent-1")
        self.assertEqual(row["invocation_id"], "invoke-1")
        self.assertEqual(row["task_id"], "task-1")
        self.assertEqual(row["context_update_id"], None)
        self.assertEqual(row["completed_at"], None)
        self.assertEqual(json.loads(str(row["result_json"])), {})
        self.assertEqual(json.loads(str(row["output_payload_json"])), {})

        request_state = json.loads(str(row["request_json"]))
        self.assertEqual(request_state["operation_id"], "file-op-1")
        self.assertEqual(request_state["content_present"], True)
        self.assertEqual(request_state["content_persisted"], False)
        self.assertEqual(request_state["content_length"], len("updated status"))
        self.assertNotIn("content", request_state)
        self.assertEqual(json.loads(str(row["metadata_json"]))["request"]["source"], "test")

    def test_file_operation_record_upsert_row_serializes_terminal_result(self) -> None:
        request = _request()
        result = _result(request)

        row = file_operation_record_upsert_row(
            request=request,
            source_event_sequence=22,
            result=result,
        )

        self.assertEqual(row["status"], "succeeded")
        self.assertEqual(row["context_update_id"], "context-update-1")
        self.assertEqual(row["completed_at"], result.completed_at.isoformat())
        self.assertEqual(row["updated_at"], result.completed_at.isoformat())
        self.assertEqual(row["bytes_written"], len("updated status"))
        self.assertEqual(json.loads(str(row["result_json"]))["status"], "succeeded")
        self.assertEqual(json.loads(str(row["output_payload_json"]))["sha256"], "abc123")
        self.assertEqual(json.loads(str(row["metadata_json"]))["result"]["verified"], True)

    def test_file_operation_record_upsert_row_rejects_negative_source_sequence(self) -> None:
        with self.assertRaises(ValueError):
            file_operation_record_upsert_row(
                request=_request(),
                source_event_sequence=-1,
            )

    def test_file_operation_record_upsert_row_rejects_mismatched_result_identity(self) -> None:
        request = _request()
        other_request = _request(operation_id=FileOperationId("file-op-2"))

        with self.assertRaises(ValueError):
            file_operation_record_upsert_row(
                request=request,
                source_event_sequence=22,
                result=_result(other_request),
            )


class SqliteFileOperationRecordStoreTests(unittest.TestCase):
    def test_record_file_operation_event_appends_event_and_upserts_record(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_agent_task_and_invocation_state(connection)
        store = SqliteFileOperationRecordStore(connection)
        request = _request()
        result = _result(request)

        sequence = store.record_file_operation_event(
            request=request,
            result=result,
            event_id=PlatformEventId("event-1"),
            session_id=PlatformRunSessionId("session-1"),
            metadata={"source": "unit-test"},
        )

        event_row = connection.execute(
            """
            SELECT sequence, event_id, workspace_id, session_id, event_kind,
                   aggregate_type, aggregate_id, occurred_at, payload_json,
                   metadata_json
            FROM platform_events
            """
        ).fetchone()
        record = store.get_file_operation_record(FileOperationId("file-op-1"))

        self.assertEqual(sequence, 1)
        self.assertEqual(event_row[0], 1)
        self.assertEqual(event_row[1], "event-1")
        self.assertEqual(event_row[2], "workspace-1")
        self.assertEqual(event_row[3], "session-1")
        self.assertEqual(event_row[4], "file_operation.recorded")
        self.assertEqual(event_row[5], "file_operation")
        self.assertEqual(event_row[6], "file-op-1")
        self.assertEqual(event_row[7], result.completed_at.isoformat())
        self.assertEqual(json.loads(event_row[8])["status"], "succeeded")
        self.assertEqual(json.loads(event_row[8])["operation_kind"], "write_file")
        self.assertEqual(json.loads(event_row[8])["has_result"], True)
        self.assertEqual(json.loads(event_row[9])["source"], "unit-test")
        assert record is not None
        self.assertEqual(record.source_event_sequence, 1)
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(record.output_payload["sha256"], "abc123")

    def test_record_file_operation_event_rolls_back_when_record_upsert_fails(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteFileOperationRecordStore(connection)

        with self.assertRaises(sqlite3.IntegrityError):
            store.record_file_operation_event(
                request=_request(),
                event_id=PlatformEventId("event-1"),
            )

        event_count = connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0]
        record_count = connection.execute(
            "SELECT COUNT(*) FROM platform_file_operation_records"
        ).fetchone()[0]
        self.assertEqual(event_count, 0)
        self.assertEqual(record_count, 0)

    def test_get_file_operation_record_returns_terminal_record(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_agent_task_and_invocation_state(connection)
        store = SqliteFileOperationRecordStore(connection)
        request = _request()
        result = _result(request)

        store.upsert_file_operation_record(
            request=request,
            source_event_sequence=21,
        )
        store.upsert_file_operation_record(
            request=request,
            source_event_sequence=22,
            result=result,
        )

        record = store.get_file_operation_record(FileOperationId("file-op-1"))

        self.assertIsInstance(record, FileOperationRecordEntry)
        assert record is not None
        self.assertEqual(record.operation_id.value, "file-op-1")
        self.assertEqual(record.workspace_id.value, "workspace-1")
        self.assertEqual(record.source_event_sequence, 22)
        self.assertEqual(record.operation_kind, "write_file")
        self.assertEqual(record.relative_path, "docs/status.md")
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(record.requested_by_agent_id, AgentId("agent-1"))
        self.assertEqual(record.invocation_id, AgentInvocationId("invoke-1"))
        self.assertEqual(record.task_id, TaskId("task-1"))
        self.assertEqual(record.context_update_id, ContextUpdateId("context-update-1"))
        self.assertEqual(record.request_state["content_persisted"], False)
        self.assertEqual(record.result_state["bytes_written"], len("updated status"))
        self.assertEqual(record.output_payload["sha256"], "abc123")
        self.assertEqual(record.metadata["request"]["source"], "test")
        self.assertEqual(record.metadata["result"]["verified"], True)
        self.assertEqual(record.completed_at, result.completed_at)
        self.assertEqual(record.created_at, request.requested_at)
        self.assertEqual(record.updated_at, result.completed_at)

    def test_get_file_operation_record_returns_none_for_unknown_operation(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteFileOperationRecordStore(connection)

        self.assertIsNone(
            store.get_file_operation_record(FileOperationId("missing-file-op"))
        )

    def test_get_file_operation_record_rejects_empty_operation_id(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteFileOperationRecordStore(connection)

        with self.assertRaises(ValueError):
            store.get_file_operation_record(FileOperationId(" "))

    def test_list_file_operation_records_by_workspace_filters_records(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_agent_task_and_invocation_state(connection)
        store = SqliteFileOperationRecordStore(connection)
        first_request = _request()
        first_result = _result(first_request)
        second_request = _request(operation_id=FileOperationId("file-op-2"))
        second_result = FileOperationResult(
            operation_id=second_request.operation_id,
            workspace_id=second_request.workspace_id,
            operation_kind=second_request.operation_kind,
            relative_path=second_request.relative_path,
            status=FileOperationResultStatus.DENIED,
            completed_at=datetime(2026, 6, 3, 12, 10, tzinfo=timezone.utc),
            requested_by_agent_id=second_request.requested_by_agent_id,
            invocation_id=second_request.invocation_id,
            task_id=second_request.task_id,
            error_message="Write denied by policy.",
        )

        store.upsert_file_operation_record(
            request=first_request,
            source_event_sequence=21,
        )
        store.upsert_file_operation_record(
            request=first_request,
            source_event_sequence=22,
            result=first_result,
        )
        store.upsert_file_operation_record(
            request=second_request,
            source_event_sequence=23,
            result=second_result,
        )

        all_records = store.list_file_operation_records_by_workspace(
            WorkspaceId("workspace-1")
        )
        denied_records = store.list_file_operation_records_by_workspace(
            WorkspaceId("workspace-1"),
            status="denied",
        )
        succeeded_records = store.list_file_operation_records_by_workspace(
            WorkspaceId("workspace-1"),
            status="succeeded",
            operation_kind="write_file",
            invocation_id=AgentInvocationId("invoke-1"),
            task_id=TaskId("task-1"),
            requested_by_agent_id=AgentId("agent-1"),
        )

        self.assertEqual(
            tuple(record.operation_id.value for record in all_records),
            ("file-op-1", "file-op-2"),
        )
        self.assertEqual(
            tuple(record.status for record in all_records),
            ("succeeded", "denied"),
        )
        self.assertEqual(
            tuple(record.operation_id.value for record in denied_records),
            ("file-op-2",),
        )
        self.assertEqual(
            tuple(record.operation_id.value for record in succeeded_records),
            ("file-op-1",),
        )

    def test_list_file_operation_records_by_workspace_rejects_invalid_filter(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteFileOperationRecordStore(connection)

        with self.assertRaisesRegex(ValueError, "status"):
            store.list_file_operation_records_by_workspace(
                WorkspaceId("workspace-1"),
                status="unknown",
            )

        with self.assertRaisesRegex(ValueError, "operation_kind"):
            store.list_file_operation_records_by_workspace(
                WorkspaceId("workspace-1"),
                operation_kind="unknown",
            )

    def test_upsert_file_operation_record_inserts_requested_row(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_agent_task_and_invocation_state(connection)
        store = SqliteFileOperationRecordStore(connection)

        store.upsert_file_operation_record(
            request=_request(),
            source_event_sequence=21,
        )

        row = connection.execute(
            """
            SELECT operation_id, workspace_id, source_event_sequence,
                   operation_kind, relative_path, status,
                   requested_by_agent_id, invocation_id, task_id,
                   request_json, result_json, output_payload_json, completed_at
            FROM platform_file_operation_records
            WHERE operation_id = ?
            """,
            ("file-op-1",),
        ).fetchone()

        self.assertEqual(row[0], "file-op-1")
        self.assertEqual(row[1], "workspace-1")
        self.assertEqual(row[2], 21)
        self.assertEqual(row[3], "write_file")
        self.assertEqual(row[4], "docs/status.md")
        self.assertEqual(row[5], "requested")
        self.assertEqual(row[6], "agent-1")
        self.assertEqual(row[7], "invoke-1")
        self.assertEqual(row[8], "task-1")
        self.assertEqual(json.loads(row[9])["content_persisted"], False)
        self.assertEqual(json.loads(row[10]), {})
        self.assertEqual(json.loads(row[11]), {})
        self.assertIsNone(row[12])

    def test_upsert_file_operation_record_updates_terminal_result(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_agent_task_and_invocation_state(connection)
        store = SqliteFileOperationRecordStore(connection)
        request = _request()
        result = _result(request)

        store.upsert_file_operation_record(
            request=request,
            source_event_sequence=21,
        )
        store.upsert_file_operation_record(
            request=request,
            source_event_sequence=22,
            result=result,
        )

        row = connection.execute(
            """
            SELECT source_event_sequence, status, context_update_id,
                   result_json, output_payload_json, bytes_written,
                   completed_at, created_at, updated_at
            FROM platform_file_operation_records
            WHERE operation_id = ?
            """,
            ("file-op-1",),
        ).fetchone()
        count = connection.execute(
            "SELECT COUNT(*) FROM platform_file_operation_records"
        ).fetchone()[0]

        self.assertEqual(count, 1)
        self.assertEqual(row[0], 22)
        self.assertEqual(row[1], "succeeded")
        self.assertEqual(row[2], "context-update-1")
        self.assertEqual(json.loads(row[3])["bytes_written"], len("updated status"))
        self.assertEqual(json.loads(row[4])["sha256"], "abc123")
        self.assertEqual(row[5], len("updated status"))
        self.assertEqual(row[6], result.completed_at.isoformat())
        self.assertEqual(row[7], request.requested_at.isoformat())
        self.assertEqual(row[8], result.completed_at.isoformat())

    def test_upsert_file_operation_record_rejects_negative_source_sequence(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_agent_task_and_invocation_state(connection)
        store = SqliteFileOperationRecordStore(connection)

        with self.assertRaises(ValueError):
            store.upsert_file_operation_record(
                request=_request(),
                source_event_sequence=-1,
            )
        count = connection.execute(
            "SELECT COUNT(*) FROM platform_file_operation_records"
        ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_file_operation_record_entry_rehydrates_from_select_row(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_agent_task_and_invocation_state(connection)
        store = SqliteFileOperationRecordStore(connection)
        request = _request()
        result = _result(request)
        store.upsert_file_operation_record(
            request=request,
            source_event_sequence=23,
            result=result,
        )
        row = connection.execute(
            f"""
            SELECT {", ".join(FILE_OPERATION_RECORD_SELECT_COLUMNS)}
            FROM platform_file_operation_records
            WHERE operation_id = ?
            """,
            ("file-op-1",),
        ).fetchone()

        record = FileOperationRecordEntry.from_sqlite_row(
            dict(zip(FILE_OPERATION_RECORD_SELECT_COLUMNS, row, strict=True))
        )

        self.assertEqual(record.operation_id.value, "file-op-1")
        self.assertEqual(record.source_event_sequence, 23)
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(record.request_state["content_present"], True)
        self.assertEqual(record.request_state["content_persisted"], False)
        self.assertEqual(record.output_payload["sha256"], "abc123")
        self.assertEqual(record.bytes_written, len("updated status"))


def _request(
    *,
    operation_id: FileOperationId = FileOperationId("file-op-1"),
) -> FileOperationRequest:
    return FileOperationRequest.create(
        operation_id=operation_id,
        workspace_id=WorkspaceId("workspace-1"),
        operation_kind=FileOperationKind.WRITE_FILE,
        relative_path="docs/status.md",
        requested_at=datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc),
        requested_by_agent_id=AgentId("agent-1"),
        invocation_id=AgentInvocationId("invoke-1"),
        task_id=TaskId("task-1"),
        content="updated status",
        create_parents=True,
        reason="Persist bounded task status",
        metadata={"source": "test"},
    )


def _result(request: FileOperationRequest) -> FileOperationResult:
    return FileOperationResult.succeed(
        request,
        completed_at=datetime(2026, 6, 3, 12, 5, tzinfo=timezone.utc),
        context_update_id=ContextUpdateId("context-update-1"),
        bytes_written=len("updated status"),
        output_payload={"sha256": "abc123"},
        metadata={"verified": True},
    )


def _insert_workspace_agent_task_and_invocation_state(
    connection: sqlite3.Connection,
) -> None:
    workspace = ProjectWorkspace.create(
        workspace_id=WorkspaceId("workspace-1"),
        display_name="Workspace",
        root_path="X:/fixture/workspace",
    )
    SqliteWorkspaceStateStore(connection).upsert_workspace_state(
        workspace=workspace,
        source_event_sequence=0,
    )
    registration = AgentRegistration.register(
        agent_id=AgentId("agent-1"),
        workspace_id=WorkspaceId("workspace-1"),
        name="Planner",
        description="Plans bounded project work",
        capabilities=(
            AgentCapability(
                name="plan_tasks",
                description="Breaks project requests into tasks",
            ),
        ),
        created_at=datetime(2026, 6, 3, 11, 0, tzinfo=timezone.utc),
        default_model="local/planner",
    )
    SqliteAgentRegistrationStateStore(connection).upsert_agent_registration_state(
        registration=registration,
        source_event_sequence=1,
    )
    task = TaskContext.create(
        task_id=TaskId("task-1"),
        workspace_id=WorkspaceId("workspace-1"),
        title="Persist bounded task status",
        created_at=datetime(2026, 6, 3, 11, 30, tzinfo=timezone.utc),
    )
    SqliteTaskStateStore(connection).upsert_task_state(
        task=task,
        source_event_sequence=2,
    )
    invocation = AgentInvocationRequest.create(
        invocation_id=AgentInvocationId("invoke-1"),
        workspace_id=WorkspaceId("workspace-1"),
        agent_id=AgentId("agent-1"),
        task_id=TaskId("task-1"),
        instruction="Persist bounded task status",
        requested_at=datetime(2026, 6, 3, 11, 45, tzinfo=timezone.utc),
    )
    SqliteAgentInvocationRecordStore(connection).upsert_agent_invocation_record(
        request=invocation,
        source_event_sequence=3,
    )


if __name__ == "__main__":
    unittest.main()
