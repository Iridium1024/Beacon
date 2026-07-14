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

from agent_os.domain.entities.context import (
    ContextUpdateInfo,
    ContextUpdateKind,
    ProjectSharedContext,
)
from agent_os.domain.entities.workspace import ProjectWorkspace
from agent_os.domain.value_objects.identifiers import (
    ContextId,
    ContextUpdateId,
    WorkspaceId,
)
from agent_os.infrastructure.persistence.materialized_state import (
    CONTEXT_STATE_SELECT_COLUMNS,
    CONTEXT_STATE_UPSERT_COLUMNS,
    ContextStateRecord,
    SqliteContextStateStore,
    SqliteWorkspaceStateStore,
    context_state_upsert_row,
)
from agent_os.infrastructure.persistence.sqlite_persistence import SqlitePlatformPersistence


class ContextStateUpsertRowTests(unittest.TestCase):
    def test_context_state_upsert_row_serializes_domain_object(self) -> None:
        created_at = datetime(2026, 6, 3, 2, 0, tzinfo=timezone.utc)
        workspace_id = WorkspaceId("workspace-1")
        context = ProjectSharedContext.create(
            context_id=ContextId("context-1"),
            workspace_id=workspace_id,
            created_at=created_at,
            materialized_state={"status": "open"},
            metadata={"source": "unit-test"},
        ).append_update(
            ContextUpdateInfo.create(
                update_id=ContextUpdateId("update-1"),
                workspace_id=workspace_id,
                update_kind=ContextUpdateKind.NOTE,
                summary="Captured note",
                created_at=datetime(2026, 6, 3, 2, 5, tzinfo=timezone.utc),
                materialized_state_patch={"latest_note": "captured"},
            )
        )

        row = context_state_upsert_row(
            context=context,
            source_event_sequence=9,
        )

        self.assertEqual(tuple(row.keys()), CONTEXT_STATE_UPSERT_COLUMNS)
        self.assertEqual(row["workspace_id"], "workspace-1")
        self.assertEqual(row["context_id"], "context-1")
        self.assertEqual(row["source_event_sequence"], 9)
        self.assertEqual(row["update_count"], 1)
        self.assertEqual(json.loads(str(row["materialized_state_json"]))["status"], "open")
        self.assertEqual(
            json.loads(str(row["materialized_state_json"]))["latest_note"],
            "captured",
        )
        self.assertEqual(json.loads(str(row["metadata_json"]))["source"], "unit-test")

    def test_context_state_upsert_row_rejects_negative_source_sequence(self) -> None:
        context = ProjectSharedContext.create(workspace_id=WorkspaceId("workspace-1"))

        with self.assertRaises(ValueError):
            context_state_upsert_row(
                context=context,
                source_event_sequence=-1,
            )


class SqliteContextStateStoreTests(unittest.TestCase):
    def test_get_context_state_returns_current_context_record(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteContextStateStore(connection)
        workspace_id = WorkspaceId("workspace-1")
        created_at = datetime(2026, 6, 3, 2, 0, tzinfo=timezone.utc)
        updated = ProjectSharedContext.create(
            context_id=ContextId("context-1"),
            workspace_id=workspace_id,
            created_at=created_at,
            materialized_state={"status": "open"},
            metadata={"owner": "test"},
        ).append_update(
            ContextUpdateInfo.create(
                update_id=ContextUpdateId("update-1"),
                workspace_id=workspace_id,
                update_kind=ContextUpdateKind.NOTE,
                summary="Captured note",
                created_at=datetime(2026, 6, 3, 2, 5, tzinfo=timezone.utc),
                materialized_state_patch={"latest_note": "captured"},
            )
        )
        store.upsert_context_state(
            context=updated,
            source_event_sequence=4,
        )

        record = store.get_context_state(WorkspaceId("workspace-1"))

        self.assertIsInstance(record, ContextStateRecord)
        assert record is not None
        self.assertEqual(record.source_event_sequence, 4)
        self.assertEqual(record.update_count, 1)
        self.assertEqual(record.context.context_id.value, "context-1")
        self.assertEqual(record.context.workspace_id.value, "workspace-1")
        self.assertEqual(record.context.updates, ())
        self.assertEqual(record.context.materialized_state["status"], "open")
        self.assertEqual(record.context.materialized_state["latest_note"], "captured")
        self.assertEqual(record.context.created_at, created_at)
        self.assertEqual(record.context.updated_at, updated.updated_at)
        self.assertEqual(record.context.metadata["owner"], "test")
        self.assertEqual(record.metadata["owner"], "test")

    def test_get_context_state_returns_none_for_unknown_workspace(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteContextStateStore(connection)

        self.assertIsNone(store.get_context_state(WorkspaceId("workspace-missing")))

    def test_get_context_state_rejects_empty_workspace_id(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteContextStateStore(connection)

        with self.assertRaises(ValueError):
            store.get_context_state(WorkspaceId(" "))

    def test_upsert_context_state_inserts_current_context_row(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteContextStateStore(connection)
        context = ProjectSharedContext.create(
            context_id=ContextId("context-1"),
            workspace_id=WorkspaceId("workspace-1"),
            materialized_state={"status": "open"},
            metadata={"owner": "test"},
        )

        store.upsert_context_state(
            context=context,
            source_event_sequence=1,
        )

        row = connection.execute(
            """
            SELECT workspace_id, context_id, source_event_sequence, update_count,
                   materialized_state_json, metadata_json
            FROM platform_context_state
            """
        ).fetchone()

        self.assertEqual(row[0], "workspace-1")
        self.assertEqual(row[1], "context-1")
        self.assertEqual(row[2], 1)
        self.assertEqual(row[3], 0)
        self.assertEqual(json.loads(row[4])["status"], "open")
        self.assertEqual(json.loads(row[5])["owner"], "test")

    def test_context_state_record_rehydrates_from_select_row(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteContextStateStore(connection)
        context = ProjectSharedContext.create(
            context_id=ContextId("context-1"),
            workspace_id=WorkspaceId("workspace-1"),
            materialized_state={"status": "open"},
            metadata={"owner": "test"},
        )
        store.upsert_context_state(
            context=context,
            source_event_sequence=5,
        )
        row = connection.execute(
            f"""
            SELECT {", ".join(CONTEXT_STATE_SELECT_COLUMNS)}
            FROM platform_context_state
            WHERE workspace_id = ?
            """,
            ("workspace-1",),
        ).fetchone()

        record = ContextStateRecord.from_sqlite_row(
            dict(zip(CONTEXT_STATE_SELECT_COLUMNS, row, strict=True))
        )

        self.assertEqual(record.source_event_sequence, 5)
        self.assertEqual(record.update_count, 0)
        self.assertEqual(record.context.context_id.value, "context-1")
        self.assertEqual(record.context.materialized_state["status"], "open")
        self.assertEqual(record.metadata["owner"], "test")

    def test_upsert_context_state_updates_existing_context_row(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteContextStateStore(connection)
        workspace_id = WorkspaceId("workspace-1")
        context = ProjectSharedContext.create(
            context_id=ContextId("context-1"),
            workspace_id=workspace_id,
            created_at=datetime(2026, 6, 3, 2, 0, tzinfo=timezone.utc),
            materialized_state={"status": "open"},
        )
        updated = context.append_update(
            ContextUpdateInfo.create(
                update_id=ContextUpdateId("update-1"),
                workspace_id=workspace_id,
                update_kind=ContextUpdateKind.DECISION,
                summary="Decision captured",
                created_at=datetime(2026, 6, 3, 2, 10, tzinfo=timezone.utc),
                materialized_state_patch={"decision": "accepted"},
            )
        )

        store.upsert_context_state(
            context=context,
            source_event_sequence=1,
        )
        store.upsert_context_state(
            context=updated,
            source_event_sequence=2,
        )

        row = connection.execute(
            """
            SELECT source_event_sequence, update_count, materialized_state_json, updated_at
            FROM platform_context_state
            WHERE workspace_id = ?
            """,
            ("workspace-1",),
        ).fetchone()
        count = connection.execute(
            "SELECT COUNT(*) FROM platform_context_state"
        ).fetchone()[0]

        self.assertEqual(count, 1)
        self.assertEqual(row[0], 2)
        self.assertEqual(row[1], 1)
        self.assertEqual(json.loads(row[2])["decision"], "accepted")
        self.assertEqual(row[3], updated.updated_at.isoformat())

    def test_upsert_context_state_rejects_negative_source_sequence(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteContextStateStore(connection)
        context = ProjectSharedContext.create(workspace_id=WorkspaceId("workspace-1"))

        with self.assertRaises(ValueError):
            store.upsert_context_state(
                context=context,
                source_event_sequence=-1,
            )


def _insert_workspace_state(connection: sqlite3.Connection) -> None:
    workspace = ProjectWorkspace.create(
        workspace_id=WorkspaceId("workspace-1"),
        display_name="Workspace",
        root_path="X:/fixture/workspace",
    )
    SqliteWorkspaceStateStore(connection).upsert_workspace_state(
        workspace=workspace,
        source_event_sequence=0,
    )


if __name__ == "__main__":
    unittest.main()
