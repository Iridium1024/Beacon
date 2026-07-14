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
from agent_os.domain.entities.invocation import (
    AgentInvocationRequest,
    AgentInvocationResult,
)
from agent_os.domain.entities.task import TaskContext
from agent_os.domain.entities.workspace import ProjectWorkspace
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextUpdateId,
    PlatformEventId,
    PlatformRunSessionId,
    TaskId,
    WorkspaceId,
)
from agent_os.infrastructure.persistence.invocation_records import (
    AGENT_INVOCATION_RECORD_SELECT_COLUMNS,
    AGENT_INVOCATION_RECORD_UPSERT_COLUMNS,
    AgentInvocationRecordEntry,
    SqliteAgentInvocationRecordStore,
    agent_invocation_record_upsert_row,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteAgentRegistrationStateStore,
    SqliteTaskStateStore,
    SqliteWorkspaceStateStore,
)
from agent_os.infrastructure.persistence.sqlite_persistence import SqlitePlatformPersistence


class AgentInvocationRecordUpsertRowTests(unittest.TestCase):
    def test_agent_invocation_record_upsert_row_serializes_requested_request(self) -> None:
        request = _request()

        row = agent_invocation_record_upsert_row(
            request=request,
            source_event_sequence=11,
        )

        self.assertEqual(tuple(row.keys()), AGENT_INVOCATION_RECORD_UPSERT_COLUMNS)
        self.assertEqual(row["invocation_id"], "invoke-1")
        self.assertEqual(row["workspace_id"], "workspace-1")
        self.assertEqual(row["agent_id"], "agent-1")
        self.assertEqual(row["source_event_sequence"], 11)
        self.assertEqual(row["status"], "requested")
        self.assertEqual(row["instruction"], "Summarize current task state")
        self.assertEqual(row["requested_capability"], "plan_tasks")
        self.assertEqual(row["idempotency_key"], "request-1")
        self.assertEqual(row["correlation_id"], "corr-1")
        self.assertEqual(row["completed_at"], None)
        self.assertEqual(json.loads(str(row["result_json"])), {})
        self.assertEqual(
            json.loads(str(row["context_update_ids_json"])),
            ["context-update-1"],
        )
        self.assertEqual(json.loads(str(row["file_references_json"])), ["README.md"])
        self.assertEqual(json.loads(str(row["request_json"]))["invocation_id"], "invoke-1")
        self.assertEqual(json.loads(str(row["metadata_json"]))["request"]["source"], "test")

    def test_agent_invocation_record_upsert_row_serializes_terminal_result(self) -> None:
        request = _request()
        result = _result(request)

        row = agent_invocation_record_upsert_row(
            request=request,
            source_event_sequence=12,
            result=result,
        )

        self.assertEqual(row["status"], "succeeded")
        self.assertEqual(row["completed_at"], result.completed_at.isoformat())
        self.assertEqual(row["updated_at"], result.completed_at.isoformat())
        self.assertEqual(json.loads(str(row["result_json"]))["summary"], "Task summarized")
        self.assertEqual(
            json.loads(str(row["context_update_ids_json"])),
            ["context-update-1", "context-update-2"],
        )
        self.assertEqual(json.loads(str(row["metadata_json"]))["result"]["tokens"], 12)

    def test_agent_invocation_record_upsert_row_rejects_negative_source_sequence(self) -> None:
        with self.assertRaises(ValueError):
            agent_invocation_record_upsert_row(
                request=_request(),
                source_event_sequence=-1,
            )

    def test_agent_invocation_record_upsert_row_rejects_mismatched_result_identity(self) -> None:
        request = _request()
        other_request = AgentInvocationRequest.create(
            invocation_id=AgentInvocationId("invoke-2"),
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
            instruction="Summarize current task state",
            requested_at=datetime(2026, 6, 3, 11, 0, tzinfo=timezone.utc),
        )

        with self.assertRaises(ValueError):
            agent_invocation_record_upsert_row(
                request=request,
                source_event_sequence=12,
                result=_result(other_request),
            )


class SqliteAgentInvocationRecordStoreTests(unittest.TestCase):
    def test_record_agent_invocation_event_appends_event_and_upserts_record(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_and_agent_state(connection)
        store = SqliteAgentInvocationRecordStore(connection)
        request = _request()
        result = _result(request)

        sequence = store.record_agent_invocation_event(
            request=request,
            result=result,
            event_id=PlatformEventId("event-1"),
            session_id=PlatformRunSessionId("session-1"),
            metadata={"source": "unit-test"},
        )

        event_row = connection.execute(
            """
            SELECT sequence, event_id, workspace_id, session_id, event_kind,
                   aggregate_type, aggregate_id, occurred_at, correlation_id,
                   idempotency_key, payload_json, metadata_json
            FROM platform_events
            """
        ).fetchone()
        record = store.get_agent_invocation_record(AgentInvocationId("invoke-1"))

        self.assertEqual(sequence, 1)
        self.assertEqual(event_row[0], 1)
        self.assertEqual(event_row[1], "event-1")
        self.assertEqual(event_row[2], "workspace-1")
        self.assertEqual(event_row[3], "session-1")
        self.assertEqual(event_row[4], "agent_invocation.recorded")
        self.assertEqual(event_row[5], "agent_invocation")
        self.assertEqual(event_row[6], "invoke-1")
        self.assertEqual(event_row[7], result.completed_at.isoformat())
        self.assertEqual(event_row[8], "corr-1")
        self.assertEqual(event_row[9], "request-1")
        self.assertEqual(json.loads(event_row[10])["status"], "succeeded")
        self.assertEqual(json.loads(event_row[10])["agent_id"], "agent-1")
        self.assertEqual(json.loads(event_row[10])["has_result"], True)
        self.assertEqual(json.loads(event_row[11])["source"], "unit-test")
        assert record is not None
        self.assertEqual(record.source_event_sequence, 1)
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(record.result_state["summary"], "Task summarized")

    def test_record_agent_invocation_event_rolls_back_when_record_upsert_fails(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteAgentInvocationRecordStore(connection)

        with self.assertRaises(sqlite3.IntegrityError):
            store.record_agent_invocation_event(
                request=_request(),
                event_id=PlatformEventId("event-1"),
            )

        event_count = connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0]
        record_count = connection.execute(
            "SELECT COUNT(*) FROM platform_agent_invocation_records"
        ).fetchone()[0]
        self.assertEqual(event_count, 0)
        self.assertEqual(record_count, 0)

    def test_get_agent_invocation_record_returns_terminal_record(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_and_agent_state(connection)
        store = SqliteAgentInvocationRecordStore(connection)
        request = _request()
        result = _result(request)

        store.upsert_agent_invocation_record(
            request=request,
            source_event_sequence=11,
        )
        store.upsert_agent_invocation_record(
            request=request,
            source_event_sequence=12,
            result=result,
        )

        record = store.get_agent_invocation_record(AgentInvocationId("invoke-1"))

        self.assertIsInstance(record, AgentInvocationRecordEntry)
        assert record is not None
        self.assertEqual(record.invocation_id.value, "invoke-1")
        self.assertEqual(record.workspace_id.value, "workspace-1")
        self.assertEqual(record.agent_id.value, "agent-1")
        self.assertEqual(record.source_event_sequence, 12)
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(record.instruction, "Summarize current task state")
        self.assertEqual(record.requested_capability, "plan_tasks")
        self.assertEqual(record.idempotency_key, "request-1")
        self.assertEqual(record.correlation_id, "corr-1")
        self.assertEqual(record.request_state["invocation_id"], "invoke-1")
        self.assertEqual(record.result_state["summary"], "Task summarized")
        self.assertEqual(
            tuple(update_id.value for update_id in record.context_update_ids),
            ("context-update-1", "context-update-2"),
        )
        self.assertEqual(record.file_references, ("README.md",))
        self.assertEqual(record.metadata["request"]["source"], "test")
        self.assertEqual(record.metadata["result"]["tokens"], 12)
        self.assertEqual(record.completed_at, result.completed_at)
        self.assertEqual(record.created_at, request.requested_at)
        self.assertEqual(record.updated_at, result.completed_at)

    def test_get_agent_invocation_record_returns_none_for_unknown_invocation(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteAgentInvocationRecordStore(connection)

        self.assertIsNone(
            store.get_agent_invocation_record(AgentInvocationId("missing-invocation"))
        )

    def test_get_agent_invocation_record_rejects_empty_invocation_id(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteAgentInvocationRecordStore(connection)

        with self.assertRaises(ValueError):
            store.get_agent_invocation_record(AgentInvocationId(" "))

    def test_list_agent_invocation_records_by_workspace_filters_records(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_and_agent_state(connection)
        store = SqliteAgentInvocationRecordStore(connection)
        first_request = _request(task_id=TaskId("task-1"))
        first_result = _result(first_request)
        second_request = _request(
            invocation_id=AgentInvocationId("invoke-2"),
            idempotency_key="request-2",
            requested_at=datetime(2026, 6, 3, 11, 10, tzinfo=timezone.utc),
            task_id=TaskId("task-1"),
        )

        store.upsert_agent_invocation_record(
            request=first_request,
            source_event_sequence=11,
        )
        store.upsert_agent_invocation_record(
            request=first_request,
            source_event_sequence=12,
            result=first_result,
        )
        store.upsert_agent_invocation_record(
            request=second_request,
            source_event_sequence=13,
        )

        all_records = store.list_agent_invocation_records_by_workspace(
            WorkspaceId("workspace-1")
        )
        requested_records = store.list_agent_invocation_records_by_workspace(
            WorkspaceId("workspace-1"),
            status="requested",
        )
        succeeded_records = store.list_agent_invocation_records_by_workspace(
            WorkspaceId("workspace-1"),
            status="succeeded",
            agent_id=AgentId("agent-1"),
            task_id=TaskId("task-1"),
            idempotency_key="request-1",
        )

        self.assertEqual(
            tuple(record.invocation_id.value for record in all_records),
            ("invoke-1", "invoke-2"),
        )
        self.assertEqual(
            tuple(record.status for record in all_records),
            ("succeeded", "requested"),
        )
        self.assertEqual(
            tuple(record.invocation_id.value for record in requested_records),
            ("invoke-2",),
        )
        self.assertEqual(
            tuple(record.invocation_id.value for record in succeeded_records),
            ("invoke-1",),
        )

    def test_list_agent_invocation_records_by_workspace_rejects_invalid_filter(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteAgentInvocationRecordStore(connection)

        with self.assertRaisesRegex(ValueError, "status"):
            store.list_agent_invocation_records_by_workspace(
                WorkspaceId("workspace-1"),
                status="unknown",
            )

    def test_upsert_agent_invocation_record_inserts_requested_row(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_and_agent_state(connection)
        store = SqliteAgentInvocationRecordStore(connection)

        store.upsert_agent_invocation_record(
            request=_request(),
            source_event_sequence=11,
        )

        row = connection.execute(
            """
            SELECT invocation_id, workspace_id, agent_id, source_event_sequence,
                   status, instruction, request_json, result_json,
                   context_update_ids_json, file_references_json, completed_at
            FROM platform_agent_invocation_records
            WHERE invocation_id = ?
            """,
            ("invoke-1",),
        ).fetchone()

        self.assertEqual(row[0], "invoke-1")
        self.assertEqual(row[1], "workspace-1")
        self.assertEqual(row[2], "agent-1")
        self.assertEqual(row[3], 11)
        self.assertEqual(row[4], "requested")
        self.assertEqual(row[5], "Summarize current task state")
        self.assertEqual(json.loads(row[6])["idempotency_key"], "request-1")
        self.assertEqual(json.loads(row[7]), {})
        self.assertEqual(json.loads(row[8]), ["context-update-1"])
        self.assertEqual(json.loads(row[9]), ["README.md"])
        self.assertIsNone(row[10])

    def test_upsert_agent_invocation_record_updates_terminal_result(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_and_agent_state(connection)
        store = SqliteAgentInvocationRecordStore(connection)
        request = _request()
        result = _result(request)

        store.upsert_agent_invocation_record(
            request=request,
            source_event_sequence=11,
        )
        store.upsert_agent_invocation_record(
            request=request,
            source_event_sequence=12,
            result=result,
        )

        row = connection.execute(
            """
            SELECT source_event_sequence, status, result_json,
                   context_update_ids_json, completed_at, created_at, updated_at
            FROM platform_agent_invocation_records
            WHERE invocation_id = ?
            """,
            ("invoke-1",),
        ).fetchone()
        count = connection.execute(
            "SELECT COUNT(*) FROM platform_agent_invocation_records"
        ).fetchone()[0]

        self.assertEqual(count, 1)
        self.assertEqual(row[0], 12)
        self.assertEqual(row[1], "succeeded")
        self.assertEqual(json.loads(row[2])["output_text"], "Done")
        self.assertEqual(json.loads(row[3]), ["context-update-1", "context-update-2"])
        self.assertEqual(row[4], result.completed_at.isoformat())
        self.assertEqual(row[5], request.requested_at.isoformat())
        self.assertEqual(row[6], result.completed_at.isoformat())

    def test_upsert_agent_invocation_record_rejects_negative_source_sequence(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_and_agent_state(connection)
        store = SqliteAgentInvocationRecordStore(connection)

        with self.assertRaises(ValueError):
            store.upsert_agent_invocation_record(
                request=_request(),
                source_event_sequence=-1,
            )
        count = connection.execute(
            "SELECT COUNT(*) FROM platform_agent_invocation_records"
        ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_agent_invocation_record_entry_rehydrates_from_select_row(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_and_agent_state(connection)
        store = SqliteAgentInvocationRecordStore(connection)
        request = _request()
        result = _result(request)
        store.upsert_agent_invocation_record(
            request=request,
            source_event_sequence=13,
            result=result,
        )
        row = connection.execute(
            f"""
            SELECT {', '.join(AGENT_INVOCATION_RECORD_SELECT_COLUMNS)}
            FROM platform_agent_invocation_records
            WHERE invocation_id = ?
            """,
            ("invoke-1",),
        ).fetchone()

        record = AgentInvocationRecordEntry.from_sqlite_row(
            dict(zip(AGENT_INVOCATION_RECORD_SELECT_COLUMNS, row, strict=True))
        )

        self.assertEqual(record.invocation_id.value, "invoke-1")
        self.assertEqual(record.source_event_sequence, 13)
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(record.result_state["output_text"], "Done")
        self.assertEqual(record.metadata["result"]["tokens"], 12)


def _request(
    *,
    invocation_id: AgentInvocationId = AgentInvocationId("invoke-1"),
    idempotency_key: str = "request-1",
    requested_at: datetime = datetime(2026, 6, 3, 11, 0, tzinfo=timezone.utc),
    task_id: TaskId | None = None,
) -> AgentInvocationRequest:
    return AgentInvocationRequest.create(
        invocation_id=invocation_id,
        workspace_id=WorkspaceId("workspace-1"),
        agent_id=AgentId("agent-1"),
        task_id=task_id,
        instruction="Summarize current task state",
        requested_at=requested_at,
        requested_capability="plan_tasks",
        context_update_ids=(ContextUpdateId("context-update-1"),),
        file_references=("README.md",),
        idempotency_key=idempotency_key,
        correlation_id="corr-1",
        metadata={"source": "test"},
    )


def _result(request: AgentInvocationRequest) -> AgentInvocationResult:
    return AgentInvocationResult.succeed(
        request,
        summary="Task summarized",
        completed_at=datetime(2026, 6, 3, 11, 5, tzinfo=timezone.utc),
        output_text="Done",
        output_payload={"kind": "summary"},
        context_update_ids=(ContextUpdateId("context-update-2"),),
        metadata={"tokens": 12},
    )


def _insert_workspace_and_agent_state(connection: sqlite3.Connection) -> None:
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
        created_at=datetime(2026, 6, 3, 10, 0, tzinfo=timezone.utc),
        default_model="local/planner",
    )
    SqliteAgentRegistrationStateStore(connection).upsert_agent_registration_state(
        registration=registration,
        source_event_sequence=1,
    )
    task = TaskContext.create(
        task_id=TaskId("task-1"),
        workspace_id=WorkspaceId("workspace-1"),
        title="Summarize current task state",
        created_at=datetime(2026, 6, 3, 10, 30, tzinfo=timezone.utc),
    )
    SqliteTaskStateStore(connection).upsert_task_state(
        task=task,
        source_event_sequence=2,
    )


if __name__ == "__main__":
    unittest.main()
