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

from agent_os.domain.entities.task import TaskContext, TaskStatus
from agent_os.domain.entities.workspace import ProjectWorkspace
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    ContextUpdateId,
    TaskId,
    WorkspaceId,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteTaskStateStore,
    SqliteWorkspaceStateStore,
    TASK_STATE_SELECT_COLUMNS,
    TASK_STATE_UPSERT_COLUMNS,
    TaskStateRecord,
    task_state_upsert_row,
)
from agent_os.infrastructure.persistence.sqlite_persistence import SqlitePlatformPersistence


class TaskStateUpsertRowTests(unittest.TestCase):
    def test_task_state_upsert_row_serializes_domain_object(self) -> None:
        created_at = datetime(2026, 6, 3, 4, 0, tzinfo=timezone.utc)
        task = TaskContext.create(
            task_id=TaskId("task-1"),
            workspace_id=WorkspaceId("workspace-1"),
            title="Define task persistence",
            created_at=created_at,
            description="Persist current task state",
            assignee_agent_id=AgentId("agent-1"),
            context_update_ids=(ContextUpdateId("update-1"),),
            linked_file_paths=("docs/state_snapshot_fixture.json",),
            metadata={"owner": "test"},
        ).transition(
            TaskStatus.IN_PROGRESS,
            updated_at=datetime(2026, 6, 3, 4, 5, tzinfo=timezone.utc),
        )

        row = task_state_upsert_row(
            task=task,
            source_event_sequence=11,
        )

        self.assertEqual(tuple(row.keys()), TASK_STATE_UPSERT_COLUMNS)
        self.assertEqual(row["task_id"], "task-1")
        self.assertEqual(row["workspace_id"], "workspace-1")
        self.assertEqual(row["source_event_sequence"], 11)
        self.assertEqual(row["title"], "Define task persistence")
        self.assertEqual(row["status"], "in_progress")
        self.assertEqual(row["assignee_agent_id"], "agent-1")
        self.assertEqual(json.loads(str(row["context_update_ids_json"])), ["update-1"])
        self.assertEqual(
            json.loads(str(row["linked_file_paths_json"])),
            ["docs/state_snapshot_fixture.json"],
        )
        self.assertEqual(json.loads(str(row["task_json"]))["description"], "Persist current task state")
        self.assertEqual(json.loads(str(row["metadata_json"]))["owner"], "test")

    def test_task_state_upsert_row_rejects_negative_source_sequence(self) -> None:
        task = TaskContext.create(
            task_id=TaskId("task-1"),
            workspace_id=WorkspaceId("workspace-1"),
            title="Define task persistence",
        )

        with self.assertRaises(ValueError):
            task_state_upsert_row(
                task=task,
                source_event_sequence=-1,
            )


class SqliteTaskStateStoreTests(unittest.TestCase):
    def test_get_task_state_returns_current_task_record(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteTaskStateStore(connection)
        created_at = datetime(2026, 6, 3, 4, 0, tzinfo=timezone.utc)
        task = TaskContext.create(
            task_id=TaskId("task-1"),
            workspace_id=WorkspaceId("workspace-1"),
            title="Define task persistence",
            created_at=created_at,
            description="Persist current task state",
            assignee_agent_id=AgentId("agent-1"),
            context_update_ids=(ContextUpdateId("update-1"),),
            linked_file_paths=("docs/state_snapshot_fixture.json",),
            metadata={"owner": "test"},
        ).transition(
            TaskStatus.IN_PROGRESS,
            updated_at=datetime(2026, 6, 3, 4, 5, tzinfo=timezone.utc),
        )
        store.upsert_task_state(
            task=task,
            source_event_sequence=7,
        )

        record = store.get_task_state(TaskId("task-1"))

        self.assertIsInstance(record, TaskStateRecord)
        assert record is not None
        self.assertEqual(record.source_event_sequence, 7)
        self.assertEqual(record.task.task_id.value, "task-1")
        self.assertEqual(record.task.workspace_id.value, "workspace-1")
        self.assertEqual(record.task.title, "Define task persistence")
        self.assertEqual(record.task.status, TaskStatus.IN_PROGRESS)
        self.assertEqual(record.task.description, "Persist current task state")
        self.assertEqual(record.task.assignee_agent_id, AgentId("agent-1"))
        self.assertEqual(record.task.context_update_ids, (ContextUpdateId("update-1"),))
        self.assertEqual(record.task.linked_file_paths, ("docs/state_snapshot_fixture.json",))
        self.assertEqual(record.task.created_at, created_at)
        self.assertEqual(record.task.updated_at, task.updated_at)
        self.assertEqual(record.task.metadata["owner"], "test")
        self.assertEqual(record.task_state["task_id"], "task-1")
        self.assertEqual(record.metadata["owner"], "test")

    def test_get_task_state_returns_none_for_unknown_task(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteTaskStateStore(connection)

        self.assertIsNone(store.get_task_state(TaskId("task-missing")))

    def test_list_task_states_by_workspace_filters_and_orders(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        _insert_workspace_state(connection, workspace_id="workspace-2")
        store = SqliteTaskStateStore(connection)
        store.upsert_task_state(
            task=_task(task_id="task-b"),
            source_event_sequence=2,
        )
        store.upsert_task_state(
            task=_task(task_id="task-a"),
            source_event_sequence=1,
        )
        store.upsert_task_state(
            task=_task(task_id="task-other", workspace_id="workspace-2"),
            source_event_sequence=3,
        )

        records = store.list_task_states_by_workspace(WorkspaceId("workspace-1"))

        self.assertEqual(
            tuple(record.task.task_id.value for record in records),
            ("task-a", "task-b"),
        )
        self.assertTrue(
            all(record.task.workspace_id == WorkspaceId("workspace-1") for record in records)
        )

    def test_list_task_states_by_workspace_returns_empty_tuple(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteTaskStateStore(connection)

        self.assertEqual(
            store.list_task_states_by_workspace(WorkspaceId("workspace-missing")),
            (),
        )

    def test_list_task_states_by_workspace_rejects_empty_workspace_id(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteTaskStateStore(connection)

        with self.assertRaises(ValueError):
            store.list_task_states_by_workspace(WorkspaceId(" "))

    def test_get_task_state_rejects_empty_task_id(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteTaskStateStore(connection)

        with self.assertRaises(ValueError):
            store.get_task_state(TaskId(" "))

    def test_upsert_task_state_inserts_current_task_row(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteTaskStateStore(connection)
        task = TaskContext.create(
            task_id=TaskId("task-1"),
            workspace_id=WorkspaceId("workspace-1"),
            title="Define task persistence",
            assignee_agent_id=AgentId("agent-1"),
            context_update_ids=(ContextUpdateId("update-1"),),
            linked_file_paths=("docs/state_snapshot_fixture.json",),
            metadata={"owner": "test"},
        )

        store.upsert_task_state(
            task=task,
            source_event_sequence=1,
        )

        row = connection.execute(
            """
            SELECT task_id, workspace_id, source_event_sequence, title, status,
                   assignee_agent_id, context_update_ids_json,
                   linked_file_paths_json, task_json, metadata_json
            FROM platform_task_state
            """
        ).fetchone()

        self.assertEqual(row[0], "task-1")
        self.assertEqual(row[1], "workspace-1")
        self.assertEqual(row[2], 1)
        self.assertEqual(row[3], "Define task persistence")
        self.assertEqual(row[4], "open")
        self.assertEqual(row[5], "agent-1")
        self.assertEqual(json.loads(row[6]), ["update-1"])
        self.assertEqual(json.loads(row[7]), ["docs/state_snapshot_fixture.json"])
        self.assertEqual(json.loads(row[8])["task_id"], "task-1")
        self.assertEqual(json.loads(row[9])["owner"], "test")

    def test_task_state_record_rehydrates_from_select_row(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteTaskStateStore(connection)
        task = TaskContext.create(
            task_id=TaskId("task-1"),
            workspace_id=WorkspaceId("workspace-1"),
            title="Define task persistence",
            description="Persist current task state",
            assignee_agent_id=AgentId("agent-1"),
            context_update_ids=(ContextUpdateId("update-1"),),
            linked_file_paths=("docs/state_snapshot_fixture.json",),
            metadata={"owner": "test"},
        )
        store.upsert_task_state(
            task=task,
            source_event_sequence=5,
        )
        row = connection.execute(
            f"""
            SELECT {", ".join(TASK_STATE_SELECT_COLUMNS)}
            FROM platform_task_state
            WHERE task_id = ?
            """,
            ("task-1",),
        ).fetchone()

        record = TaskStateRecord.from_sqlite_row(
            dict(zip(TASK_STATE_SELECT_COLUMNS, row, strict=True))
        )

        self.assertEqual(record.source_event_sequence, 5)
        self.assertEqual(record.task.task_id.value, "task-1")
        self.assertEqual(record.task.description, "Persist current task state")
        self.assertEqual(record.task.assignee_agent_id, AgentId("agent-1"))
        self.assertEqual(record.task.context_update_ids, (ContextUpdateId("update-1"),))
        self.assertEqual(record.task.linked_file_paths, ("docs/state_snapshot_fixture.json",))
        self.assertEqual(record.metadata["owner"], "test")

    def test_upsert_task_state_updates_existing_task_row(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteTaskStateStore(connection)
        task = TaskContext.create(
            task_id=TaskId("task-1"),
            workspace_id=WorkspaceId("workspace-1"),
            title="Define task persistence",
            created_at=datetime(2026, 6, 3, 4, 0, tzinfo=timezone.utc),
        )
        updated = task.assign(
            AgentId("agent-1"),
            updated_at=datetime(2026, 6, 3, 4, 5, tzinfo=timezone.utc),
        ).transition(
            TaskStatus.IN_PROGRESS,
            updated_at=datetime(2026, 6, 3, 4, 10, tzinfo=timezone.utc),
        ).add_context_update(
            ContextUpdateId("update-1"),
            updated_at=datetime(2026, 6, 3, 4, 15, tzinfo=timezone.utc),
        )

        store.upsert_task_state(
            task=task,
            source_event_sequence=1,
        )
        store.upsert_task_state(
            task=updated,
            source_event_sequence=2,
        )

        row = connection.execute(
            """
            SELECT source_event_sequence, status, assignee_agent_id,
                   context_update_ids_json, updated_at
            FROM platform_task_state
            WHERE task_id = ?
            """,
            ("task-1",),
        ).fetchone()
        count = connection.execute(
            "SELECT COUNT(*) FROM platform_task_state"
        ).fetchone()[0]

        self.assertEqual(count, 1)
        self.assertEqual(row[0], 2)
        self.assertEqual(row[1], "in_progress")
        self.assertEqual(row[2], "agent-1")
        self.assertEqual(json.loads(row[3]), ["update-1"])
        self.assertEqual(row[4], updated.updated_at.isoformat())

    def test_upsert_task_state_rejects_negative_source_sequence(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteTaskStateStore(connection)
        task = TaskContext.create(
            task_id=TaskId("task-1"),
            workspace_id=WorkspaceId("workspace-1"),
            title="Define task persistence",
        )

        with self.assertRaises(ValueError):
            store.upsert_task_state(
                task=task,
                source_event_sequence=-1,
            )


def _task(
    *,
    task_id: str = "task-1",
    workspace_id: str = "workspace-1",
) -> TaskContext:
    return TaskContext.create(
        task_id=TaskId(task_id),
        workspace_id=WorkspaceId(workspace_id),
        title="Define task persistence",
    )


def _insert_workspace_state(
    connection: sqlite3.Connection,
    *,
    workspace_id: str = "workspace-1",
) -> None:
    workspace = ProjectWorkspace.create(
        workspace_id=WorkspaceId(workspace_id),
        display_name="Workspace",
        root_path=f"X:/fixture/{workspace_id}",
    )
    SqliteWorkspaceStateStore(connection).upsert_workspace_state(
        workspace=workspace,
        source_event_sequence=0,
    )


if __name__ == "__main__":
    unittest.main()
