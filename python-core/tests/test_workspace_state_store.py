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

from agent_os.domain.entities.workspace import ProjectWorkspace
from agent_os.domain.value_objects.identifiers import WorkspaceId
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteWorkspaceStateStore,
    WORKSPACE_STATE_SELECT_COLUMNS,
    WORKSPACE_STATE_UPSERT_COLUMNS,
    WorkspaceStateRecord,
    workspace_state_upsert_row,
)
from agent_os.infrastructure.persistence.sqlite_persistence import SqlitePlatformPersistence


class WorkspaceStateUpsertRowTests(unittest.TestCase):
    def test_workspace_state_upsert_row_serializes_domain_object(self) -> None:
        created_at = datetime(2026, 6, 3, 1, 0, tzinfo=timezone.utc)
        workspace = ProjectWorkspace.create(
            workspace_id=WorkspaceId("workspace-1"),
            display_name="Workspace",
            root_path="X:/fixture/workspace",
            created_at=created_at,
            metadata={"owner": "test"},
        )

        row = workspace_state_upsert_row(
            workspace=workspace,
            source_event_sequence=7,
        )

        self.assertEqual(tuple(row.keys()), WORKSPACE_STATE_UPSERT_COLUMNS)
        self.assertEqual(row["workspace_id"], "workspace-1")
        self.assertEqual(row["source_event_sequence"], 7)
        self.assertEqual(row["display_name"], "Workspace")
        self.assertEqual(row["status"], "active")
        self.assertEqual(json.loads(str(row["workspace_json"]))["metadata"]["owner"], "test")
        self.assertEqual(json.loads(str(row["metadata_json"]))["owner"], "test")

    def test_workspace_state_upsert_row_rejects_negative_source_sequence(self) -> None:
        workspace = ProjectWorkspace.create(
            workspace_id=WorkspaceId("workspace-1"),
            display_name="Workspace",
            root_path="X:/fixture/workspace",
        )

        with self.assertRaises(ValueError):
            workspace_state_upsert_row(
                workspace=workspace,
                source_event_sequence=-1,
            )


class SqliteWorkspaceStateStoreTests(unittest.TestCase):
    def test_get_workspace_state_returns_current_workspace_record(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteWorkspaceStateStore(connection)
        created_at = datetime(2026, 6, 3, 1, 0, tzinfo=timezone.utc)
        workspace = ProjectWorkspace.create(
            workspace_id=WorkspaceId("workspace-1"),
            display_name="Workspace",
            root_path="X:/fixture/workspace",
            created_at=created_at,
            metadata={"owner": "test"},
        )

        store.upsert_workspace_state(
            workspace=workspace,
            source_event_sequence=3,
        )

        record = store.get_workspace_state(WorkspaceId("workspace-1"))

        self.assertIsInstance(record, WorkspaceStateRecord)
        assert record is not None
        self.assertEqual(record.source_event_sequence, 3)
        self.assertEqual(record.workspace.workspace_id.value, "workspace-1")
        self.assertEqual(record.workspace.display_name, "Workspace")
        self.assertEqual(record.workspace.root_path, "X:/fixture/workspace")
        self.assertEqual(record.workspace.status.value, "active")
        self.assertEqual(record.workspace.created_at, created_at)
        self.assertEqual(record.workspace.metadata["owner"], "test")
        self.assertEqual(record.workspace_state["workspace_id"], "workspace-1")
        self.assertEqual(record.binding_state, {})
        self.assertEqual(record.metadata["owner"], "test")

    def test_get_workspace_state_returns_none_for_unknown_workspace(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteWorkspaceStateStore(connection)

        self.assertIsNone(store.get_workspace_state(WorkspaceId("workspace-missing")))

    def test_list_workspace_states_returns_all_workspaces_in_id_order(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteWorkspaceStateStore(connection)
        workspace_b = ProjectWorkspace.create(
            workspace_id=WorkspaceId("workspace-b"),
            display_name="Workspace B",
            root_path="X:/fixture/workspace-b",
        )
        workspace_a = ProjectWorkspace.create(
            workspace_id=WorkspaceId("workspace-a"),
            display_name="Workspace A",
            root_path="X:/fixture/workspace-a",
        )

        store.upsert_workspace_state(
            workspace=workspace_b,
            source_event_sequence=2,
        )
        store.upsert_workspace_state(
            workspace=workspace_a,
            source_event_sequence=1,
        )

        records = store.list_workspace_states()

        self.assertEqual(
            tuple(record.workspace.workspace_id.value for record in records),
            ("workspace-a", "workspace-b"),
        )
        self.assertEqual(records[0].workspace.display_name, "Workspace A")
        self.assertEqual(records[1].source_event_sequence, 2)

    def test_list_workspace_states_returns_empty_tuple_without_workspaces(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteWorkspaceStateStore(connection)

        self.assertEqual(store.list_workspace_states(), ())

    def test_get_workspace_state_rejects_empty_workspace_id(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteWorkspaceStateStore(connection)

        with self.assertRaises(ValueError):
            store.get_workspace_state(WorkspaceId(" "))

    def test_upsert_workspace_state_inserts_current_workspace_row(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteWorkspaceStateStore(connection)
        workspace = ProjectWorkspace.create(
            workspace_id=WorkspaceId("workspace-1"),
            display_name="Workspace",
            root_path="X:/fixture/workspace",
            metadata={"owner": "test"},
        )

        store.upsert_workspace_state(
            workspace=workspace,
            source_event_sequence=1,
        )

        row = connection.execute(
            """
            SELECT workspace_id, source_event_sequence, display_name, root_path,
                   status, workspace_json, binding_json, metadata_json
            FROM platform_workspace_state
            """
        ).fetchone()

        self.assertEqual(row[0], "workspace-1")
        self.assertEqual(row[1], 1)
        self.assertEqual(row[2], "Workspace")
        self.assertEqual(row[3], "X:/fixture/workspace")
        self.assertEqual(row[4], "active")
        self.assertEqual(json.loads(row[5])["workspace_id"], "workspace-1")
        self.assertEqual(json.loads(row[6]), {})
        self.assertEqual(json.loads(row[7])["owner"], "test")

    def test_workspace_state_record_rehydrates_from_select_row(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteWorkspaceStateStore(connection)
        workspace = ProjectWorkspace.create(
            workspace_id=WorkspaceId("workspace-1"),
            display_name="Workspace",
            root_path="X:/fixture/workspace",
            metadata={"owner": "test"},
        )
        store.upsert_workspace_state(
            workspace=workspace,
            source_event_sequence=5,
        )
        row = connection.execute(
            f"""
            SELECT {", ".join(WORKSPACE_STATE_SELECT_COLUMNS)}
            FROM platform_workspace_state
            WHERE workspace_id = ?
            """,
            ("workspace-1",),
        ).fetchone()

        record = WorkspaceStateRecord.from_sqlite_row(
            dict(zip(WORKSPACE_STATE_SELECT_COLUMNS, row, strict=True))
        )

        self.assertEqual(record.source_event_sequence, 5)
        self.assertEqual(record.workspace.workspace_id.value, "workspace-1")
        self.assertEqual(record.workspace.metadata["owner"], "test")

    def test_upsert_workspace_state_updates_existing_workspace_row(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteWorkspaceStateStore(connection)
        created_at = datetime(2026, 6, 3, 1, 0, tzinfo=timezone.utc)
        workspace = ProjectWorkspace.create(
            workspace_id=WorkspaceId("workspace-1"),
            display_name="Workspace",
            root_path="X:/fixture/workspace",
            created_at=created_at,
        )
        renamed = workspace.rename(
            "Renamed Workspace",
            updated_at=datetime(2026, 6, 3, 2, 0, tzinfo=timezone.utc),
        )

        store.upsert_workspace_state(
            workspace=workspace,
            source_event_sequence=1,
        )
        store.upsert_workspace_state(
            workspace=renamed,
            source_event_sequence=2,
        )

        row = connection.execute(
            """
            SELECT source_event_sequence, display_name, updated_at
            FROM platform_workspace_state
            WHERE workspace_id = ?
            """,
            ("workspace-1",),
        ).fetchone()
        count = connection.execute(
            "SELECT COUNT(*) FROM platform_workspace_state"
        ).fetchone()[0]

        self.assertEqual(count, 1)
        self.assertEqual(row[0], 2)
        self.assertEqual(row[1], "Renamed Workspace")
        self.assertEqual(row[2], renamed.updated_at.isoformat())

    def test_upsert_workspace_state_rejects_negative_source_sequence(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteWorkspaceStateStore(connection)
        workspace = ProjectWorkspace.create(
            workspace_id=WorkspaceId("workspace-1"),
            display_name="Workspace",
            root_path="X:/fixture/workspace",
        )

        with self.assertRaises(ValueError):
            store.upsert_workspace_state(
                workspace=workspace,
                source_event_sequence=-1,
            )


if __name__ == "__main__":
    unittest.main()
