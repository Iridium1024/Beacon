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

from agent_os.application.services.file_operation_context_linker import (
    FileOperationContextLinker,
)
from agent_os.domain.entities.context import (
    ContextUpdateInfo,
    ContextUpdateKind,
    ProjectSharedContext,
)
from agent_os.domain.entities.file_operation import (
    FileOperationKind,
    FileOperationRequest,
    FileOperationResult,
)
from agent_os.domain.entities.workspace import ProjectWorkspace
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    ContextId,
    ContextUpdateId,
    FileOperationId,
    PlatformEventId,
    PlatformRunSessionId,
    WorkspaceId,
)
from agent_os.infrastructure.persistence.context_update_events import (
    RecordedContextUpdate,
    SqliteContextUpdateEventRecorder,
    context_update_event_payload,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteContextStateStore,
    SqliteWorkspaceStateStore,
)
from agent_os.infrastructure.persistence.sqlite_persistence import (
    SqlitePlatformPersistence,
)


class ContextUpdateEventPayloadTests(unittest.TestCase):
    def test_context_update_event_payload_serializes_canonical_update(self) -> None:
        update = _note_update()

        payload = context_update_event_payload(update)

        self.assertEqual(payload["update_id"], "update-1")
        self.assertEqual(payload["workspace_id"], "workspace-1")
        self.assertEqual(payload["update_kind"], "note")
        self.assertEqual(payload["summary"], "Captured note")
        self.assertEqual(payload["created_at"], update.created_at.isoformat())
        self.assertEqual(payload["source_agent_id"], "agent-1")
        self.assertEqual(payload["payload"]["note"], "captured")
        self.assertEqual(payload["materialized_state_patch"]["latest_note"], "captured")
        self.assertEqual(payload["update_metadata"]["source"], "unit-test")


class SqliteContextUpdateEventRecorderTests(unittest.TestCase):
    def test_record_context_update_event_appends_event_and_updates_context_state(self) -> None:
        connection = _connection()
        context = _context()
        update = _note_update()
        recorder = SqliteContextUpdateEventRecorder(connection)

        recorded = recorder.record_context_update_event(
            context=context,
            update=update,
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
        state = SqliteContextStateStore(connection).get_context_state(
            WorkspaceId("workspace-1")
        )

        self.assertIsInstance(recorded, RecordedContextUpdate)
        self.assertEqual(recorded.source_event_sequence, 1)
        self.assertEqual(recorded.context.context_id, ContextId("context-1"))
        self.assertEqual(recorded.context.updates[0].update_id, ContextUpdateId("update-1"))
        self.assertEqual(recorded.context.materialized_state["latest_note"], "captured")
        self.assertEqual(event_row[0], 1)
        self.assertEqual(event_row[1], "event-1")
        self.assertEqual(event_row[2], "workspace-1")
        self.assertEqual(event_row[3], "session-1")
        self.assertEqual(event_row[4], "context.update_appended")
        self.assertEqual(event_row[5], "context_update")
        self.assertEqual(event_row[6], "update-1")
        self.assertEqual(event_row[7], update.created_at.isoformat())
        self.assertEqual(json.loads(event_row[8])["payload"]["note"], "captured")
        self.assertEqual(json.loads(event_row[9])["source"], "unit-test")
        assert state is not None
        self.assertEqual(state.source_event_sequence, 1)
        self.assertEqual(state.update_count, 1)
        self.assertEqual(state.context.materialized_state["status"], "open")
        self.assertEqual(state.context.materialized_state["latest_note"], "captured")

    def test_record_file_operation_context_update_persists_redacted_payload(self) -> None:
        connection = _connection()
        context = _context()
        request = FileOperationRequest.create(
            operation_id=FileOperationId("file-op-1"),
            workspace_id=WorkspaceId("workspace-1"),
            operation_kind=FileOperationKind.READ_FILE,
            relative_path="docs/note.md",
            requested_by_agent_id=AgentId("agent-1"),
        )
        result = FileOperationResult.succeed(
            request,
            context_update_id=ContextUpdateId("update-file-1"),
            bytes_read=5,
            output_payload={"content": "hello", "encoding": "utf-8"},
        )
        update = FileOperationContextLinker().build_update(
            result=result,
            source_event_sequence=7,
        )

        recorded = SqliteContextUpdateEventRecorder(connection).record_context_update_event(
            context=context,
            update=update,
            event_id=PlatformEventId("event-file-1"),
        )

        payload_json = connection.execute(
            "SELECT payload_json FROM platform_events WHERE event_id = ?",
            ("event-file-1",),
        ).fetchone()[0]
        event_payload = json.loads(payload_json)
        output_payload = event_payload["payload"]["file_operation"]["output_payload"]
        state = SqliteContextStateStore(connection).get_context_state(
            WorkspaceId("workspace-1")
        )

        self.assertEqual(recorded.source_event_sequence, 1)
        self.assertNotIn("content", output_payload)
        self.assertEqual(output_payload["content_persisted"], False)
        self.assertEqual(output_payload["content_length"], 5)
        self.assertEqual(output_payload["encoding"], "utf-8")
        self.assertEqual(event_payload["update_metadata"]["content_redacted_from_context"], True)
        assert state is not None
        self.assertEqual(
            state.context.materialized_state["last_file_operation"]["operation_id"],
            "file-op-1",
        )
        self.assertEqual(
            state.context.materialized_state["last_file_operation"]["source_event_sequence"],
            7,
        )

    def test_record_context_update_event_can_preserve_persisted_update_count(self) -> None:
        connection = _connection()
        context = _context()

        recorded = SqliteContextUpdateEventRecorder(connection).record_context_update_event(
            context=context,
            update=_note_update(),
            event_id=PlatformEventId("event-count-1"),
            base_update_count=4,
        )

        state = SqliteContextStateStore(connection).get_context_state(
            WorkspaceId("workspace-1")
        )

        self.assertEqual(recorded.source_event_sequence, 1)
        assert state is not None
        self.assertEqual(state.update_count, 5)

    def test_record_context_update_event_rejects_cross_workspace_update_before_insert(self) -> None:
        connection = _connection()
        context = _context()
        update = ContextUpdateInfo.create(
            update_id=ContextUpdateId("update-foreign"),
            workspace_id=WorkspaceId("workspace-2"),
            update_kind=ContextUpdateKind.NOTE,
            summary="Foreign note",
        )

        with self.assertRaisesRegex(ValueError, "workspace_id"):
            SqliteContextUpdateEventRecorder(connection).record_context_update_event(
                context=context,
                update=update,
                event_id=PlatformEventId("event-foreign"),
            )

        self.assertEqual(_count(connection, "platform_events"), 0)
        self.assertEqual(_count(connection, "platform_context_state"), 0)

    def test_record_context_update_event_rolls_back_when_state_upsert_fails(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        context = _context()

        with self.assertRaises(sqlite3.IntegrityError):
            SqliteContextUpdateEventRecorder(connection).record_context_update_event(
                context=context,
                update=_note_update(),
                event_id=PlatformEventId("event-rollback"),
            )

        self.assertEqual(_count(connection, "platform_events"), 0)
        self.assertEqual(_count(connection, "platform_context_state"), 0)


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    SqlitePlatformPersistence(connection).initialize()
    workspace = ProjectWorkspace.create(
        workspace_id=WorkspaceId("workspace-1"),
        display_name="Workspace",
        root_path="X:/fixture/workspace",
    )
    SqliteWorkspaceStateStore(connection).upsert_workspace_state(
        workspace=workspace,
        source_event_sequence=0,
    )
    return connection


def _context() -> ProjectSharedContext:
    return ProjectSharedContext.create(
        context_id=ContextId("context-1"),
        workspace_id=WorkspaceId("workspace-1"),
        created_at=datetime(2026, 6, 4, 2, 30, tzinfo=timezone.utc),
        materialized_state={"status": "open"},
    )


def _note_update() -> ContextUpdateInfo:
    return ContextUpdateInfo.create(
        update_id=ContextUpdateId("update-1"),
        workspace_id=WorkspaceId("workspace-1"),
        update_kind=ContextUpdateKind.NOTE,
        summary="Captured note",
        created_at=datetime(2026, 6, 4, 2, 35, tzinfo=timezone.utc),
        source_agent_id=AgentId("agent-1"),
        payload={"note": "captured"},
        materialized_state_patch={"latest_note": "captured"},
        metadata={"source": "unit-test"},
    )


def _count(connection: sqlite3.Connection, table_name: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
