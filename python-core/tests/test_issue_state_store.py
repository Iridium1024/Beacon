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

from agent_os.domain.entities.task import IssueContext, IssueSeverity, IssueStatus
from agent_os.domain.entities.workspace import ProjectWorkspace
from agent_os.domain.value_objects.identifiers import (
    ContextUpdateId,
    IssueId,
    TaskId,
    WorkspaceId,
)
from agent_os.infrastructure.persistence.materialized_state import (
    ISSUE_STATE_SELECT_COLUMNS,
    ISSUE_STATE_UPSERT_COLUMNS,
    IssueStateRecord,
    SqliteIssueStateStore,
    SqliteWorkspaceStateStore,
    issue_state_upsert_row,
)
from agent_os.infrastructure.persistence.sqlite_persistence import SqlitePlatformPersistence


class IssueStateUpsertRowTests(unittest.TestCase):
    def test_issue_state_upsert_row_serializes_domain_object(self) -> None:
        created_at = datetime(2026, 6, 3, 6, 0, tzinfo=timezone.utc)
        issue = IssueContext.create(
            issue_id=IssueId("issue-1"),
            workspace_id=WorkspaceId("workspace-1"),
            title="Track issue persistence",
            created_at=created_at,
            severity=IssueSeverity.HIGH,
            description="Persist current issue state",
            linked_task_id=TaskId("task-1"),
            context_update_ids=(ContextUpdateId("update-1"),),
            linked_file_paths=("docs/state_snapshot_fixture.json",),
            metadata={"owner": "test"},
        ).transition(
            IssueStatus.TRIAGED,
            updated_at=datetime(2026, 6, 3, 6, 5, tzinfo=timezone.utc),
        )

        row = issue_state_upsert_row(
            issue=issue,
            source_event_sequence=13,
        )

        self.assertEqual(tuple(row.keys()), ISSUE_STATE_UPSERT_COLUMNS)
        self.assertEqual(row["issue_id"], "issue-1")
        self.assertEqual(row["workspace_id"], "workspace-1")
        self.assertEqual(row["source_event_sequence"], 13)
        self.assertEqual(row["title"], "Track issue persistence")
        self.assertEqual(row["status"], "triaged")
        self.assertEqual(row["severity"], "high")
        self.assertEqual(row["linked_task_id"], "task-1")
        self.assertEqual(json.loads(str(row["context_update_ids_json"])), ["update-1"])
        self.assertEqual(
            json.loads(str(row["linked_file_paths_json"])),
            ["docs/state_snapshot_fixture.json"],
        )
        self.assertEqual(json.loads(str(row["issue_json"]))["description"], "Persist current issue state")
        self.assertEqual(json.loads(str(row["metadata_json"]))["owner"], "test")

    def test_issue_state_upsert_row_rejects_negative_source_sequence(self) -> None:
        issue = IssueContext.create(
            issue_id=IssueId("issue-1"),
            workspace_id=WorkspaceId("workspace-1"),
            title="Track issue persistence",
        )

        with self.assertRaises(ValueError):
            issue_state_upsert_row(
                issue=issue,
                source_event_sequence=-1,
            )


class SqliteIssueStateStoreTests(unittest.TestCase):
    def test_get_issue_state_returns_current_issue_record(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteIssueStateStore(connection)
        created_at = datetime(2026, 6, 3, 6, 0, tzinfo=timezone.utc)
        issue = IssueContext.create(
            issue_id=IssueId("issue-1"),
            workspace_id=WorkspaceId("workspace-1"),
            title="Track issue persistence",
            created_at=created_at,
            severity=IssueSeverity.HIGH,
            description="Persist current issue state",
            linked_task_id=TaskId("task-1"),
            context_update_ids=(ContextUpdateId("update-1"),),
            linked_file_paths=("docs/state_snapshot_fixture.json",),
            metadata={"owner": "test"},
        ).transition(
            IssueStatus.TRIAGED,
            updated_at=datetime(2026, 6, 3, 6, 5, tzinfo=timezone.utc),
        )
        store.upsert_issue_state(
            issue=issue,
            source_event_sequence=7,
        )

        record = store.get_issue_state(IssueId("issue-1"))

        self.assertIsInstance(record, IssueStateRecord)
        assert record is not None
        self.assertEqual(record.source_event_sequence, 7)
        self.assertEqual(record.issue.issue_id.value, "issue-1")
        self.assertEqual(record.issue.workspace_id.value, "workspace-1")
        self.assertEqual(record.issue.title, "Track issue persistence")
        self.assertEqual(record.issue.status, IssueStatus.TRIAGED)
        self.assertEqual(record.issue.severity, IssueSeverity.HIGH)
        self.assertEqual(record.issue.description, "Persist current issue state")
        self.assertEqual(record.issue.linked_task_id, TaskId("task-1"))
        self.assertEqual(record.issue.context_update_ids, (ContextUpdateId("update-1"),))
        self.assertEqual(record.issue.linked_file_paths, ("docs/state_snapshot_fixture.json",))
        self.assertEqual(record.issue.created_at, created_at)
        self.assertEqual(record.issue.updated_at, issue.updated_at)
        self.assertEqual(record.issue.metadata["owner"], "test")
        self.assertEqual(record.issue_state["issue_id"], "issue-1")
        self.assertEqual(record.metadata["owner"], "test")

    def test_get_issue_state_returns_none_for_unknown_issue(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteIssueStateStore(connection)

        self.assertIsNone(store.get_issue_state(IssueId("issue-missing")))

    def test_list_issue_states_by_workspace_filters_and_orders(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        _insert_workspace_state(connection, workspace_id="workspace-2")
        store = SqliteIssueStateStore(connection)
        store.upsert_issue_state(
            issue=_issue(issue_id="issue-b"),
            source_event_sequence=2,
        )
        store.upsert_issue_state(
            issue=_issue(issue_id="issue-a"),
            source_event_sequence=1,
        )
        store.upsert_issue_state(
            issue=_issue(issue_id="issue-other", workspace_id="workspace-2"),
            source_event_sequence=3,
        )

        records = store.list_issue_states_by_workspace(WorkspaceId("workspace-1"))

        self.assertEqual(
            tuple(record.issue.issue_id.value for record in records),
            ("issue-a", "issue-b"),
        )
        self.assertTrue(
            all(record.issue.workspace_id == WorkspaceId("workspace-1") for record in records)
        )

    def test_list_issue_states_by_workspace_returns_empty_tuple(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteIssueStateStore(connection)

        self.assertEqual(
            store.list_issue_states_by_workspace(WorkspaceId("workspace-missing")),
            (),
        )

    def test_list_issue_states_by_workspace_rejects_empty_workspace_id(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteIssueStateStore(connection)

        with self.assertRaises(ValueError):
            store.list_issue_states_by_workspace(WorkspaceId(" "))

    def test_get_issue_state_rejects_empty_issue_id(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteIssueStateStore(connection)

        with self.assertRaises(ValueError):
            store.get_issue_state(IssueId(" "))

    def test_upsert_issue_state_inserts_current_issue_row(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteIssueStateStore(connection)
        issue = IssueContext.create(
            issue_id=IssueId("issue-1"),
            workspace_id=WorkspaceId("workspace-1"),
            title="Track issue persistence",
            severity=IssueSeverity.HIGH,
            linked_task_id=TaskId("task-1"),
            context_update_ids=(ContextUpdateId("update-1"),),
            linked_file_paths=("docs/state_snapshot_fixture.json",),
            metadata={"owner": "test"},
        )

        store.upsert_issue_state(
            issue=issue,
            source_event_sequence=1,
        )

        row = connection.execute(
            """
            SELECT issue_id, workspace_id, source_event_sequence, title, status,
                   severity, linked_task_id, context_update_ids_json,
                   linked_file_paths_json, issue_json, metadata_json
            FROM platform_issue_state
            """
        ).fetchone()

        self.assertEqual(row[0], "issue-1")
        self.assertEqual(row[1], "workspace-1")
        self.assertEqual(row[2], 1)
        self.assertEqual(row[3], "Track issue persistence")
        self.assertEqual(row[4], "open")
        self.assertEqual(row[5], "high")
        self.assertEqual(row[6], "task-1")
        self.assertEqual(json.loads(row[7]), ["update-1"])
        self.assertEqual(json.loads(row[8]), ["docs/state_snapshot_fixture.json"])
        self.assertEqual(json.loads(row[9])["issue_id"], "issue-1")
        self.assertEqual(json.loads(row[10])["owner"], "test")

    def test_issue_state_record_rehydrates_from_select_row(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteIssueStateStore(connection)
        issue = IssueContext.create(
            issue_id=IssueId("issue-1"),
            workspace_id=WorkspaceId("workspace-1"),
            title="Track issue persistence",
            description="Persist current issue state",
            severity=IssueSeverity.CRITICAL,
            linked_task_id=TaskId("task-1"),
            context_update_ids=(ContextUpdateId("update-1"),),
            linked_file_paths=("docs/state_snapshot_fixture.json",),
            metadata={"owner": "test"},
        )
        store.upsert_issue_state(
            issue=issue,
            source_event_sequence=5,
        )
        row = connection.execute(
            f"""
            SELECT {", ".join(ISSUE_STATE_SELECT_COLUMNS)}
            FROM platform_issue_state
            WHERE issue_id = ?
            """,
            ("issue-1",),
        ).fetchone()

        record = IssueStateRecord.from_sqlite_row(
            dict(zip(ISSUE_STATE_SELECT_COLUMNS, row, strict=True))
        )

        self.assertEqual(record.source_event_sequence, 5)
        self.assertEqual(record.issue.issue_id.value, "issue-1")
        self.assertEqual(record.issue.description, "Persist current issue state")
        self.assertEqual(record.issue.severity, IssueSeverity.CRITICAL)
        self.assertEqual(record.issue.linked_task_id, TaskId("task-1"))
        self.assertEqual(record.issue.context_update_ids, (ContextUpdateId("update-1"),))
        self.assertEqual(record.issue.linked_file_paths, ("docs/state_snapshot_fixture.json",))
        self.assertEqual(record.metadata["owner"], "test")

    def test_upsert_issue_state_updates_existing_issue_row(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteIssueStateStore(connection)
        issue = IssueContext.create(
            issue_id=IssueId("issue-1"),
            workspace_id=WorkspaceId("workspace-1"),
            title="Track issue persistence",
            created_at=datetime(2026, 6, 3, 6, 0, tzinfo=timezone.utc),
        )
        updated = issue.link_task(
            TaskId("task-1"),
            updated_at=datetime(2026, 6, 3, 6, 5, tzinfo=timezone.utc),
        ).transition(
            IssueStatus.RESOLVED,
            updated_at=datetime(2026, 6, 3, 6, 10, tzinfo=timezone.utc),
        ).add_context_update(
            ContextUpdateId("update-1"),
            updated_at=datetime(2026, 6, 3, 6, 15, tzinfo=timezone.utc),
        ).link_file(
            "docs/state_snapshot_fixture.json",
            updated_at=datetime(2026, 6, 3, 6, 20, tzinfo=timezone.utc),
        )

        store.upsert_issue_state(
            issue=issue,
            source_event_sequence=1,
        )
        store.upsert_issue_state(
            issue=updated,
            source_event_sequence=2,
        )

        row = connection.execute(
            """
            SELECT source_event_sequence, status, linked_task_id,
                   context_update_ids_json, linked_file_paths_json, updated_at
            FROM platform_issue_state
            WHERE issue_id = ?
            """,
            ("issue-1",),
        ).fetchone()
        count = connection.execute(
            "SELECT COUNT(*) FROM platform_issue_state"
        ).fetchone()[0]

        self.assertEqual(count, 1)
        self.assertEqual(row[0], 2)
        self.assertEqual(row[1], "resolved")
        self.assertEqual(row[2], "task-1")
        self.assertEqual(json.loads(row[3]), ["update-1"])
        self.assertEqual(json.loads(row[4]), ["docs/state_snapshot_fixture.json"])
        self.assertEqual(row[5], updated.updated_at.isoformat())

    def test_upsert_issue_state_rejects_negative_source_sequence(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteIssueStateStore(connection)
        issue = IssueContext.create(
            issue_id=IssueId("issue-1"),
            workspace_id=WorkspaceId("workspace-1"),
            title="Track issue persistence",
        )

        with self.assertRaises(ValueError):
            store.upsert_issue_state(
                issue=issue,
                source_event_sequence=-1,
            )
        count = connection.execute(
            "SELECT COUNT(*) FROM platform_issue_state"
        ).fetchone()[0]
        self.assertEqual(count, 0)


def _issue(
    *,
    issue_id: str = "issue-1",
    workspace_id: str = "workspace-1",
) -> IssueContext:
    return IssueContext.create(
        issue_id=IssueId(issue_id),
        workspace_id=WorkspaceId(workspace_id),
        title="Track issue persistence",
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
