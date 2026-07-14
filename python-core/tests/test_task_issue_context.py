from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.domain.entities.task import (
    IssueContext,
    IssueSeverity,
    IssueStatus,
    TaskContext,
    TaskStatus,
)
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    ContextUpdateId,
    IssueId,
    TaskId,
    WorkspaceId,
)


class TaskContextTests(unittest.TestCase):
    def test_create_task_context_scopes_task_to_workspace(self) -> None:
        timestamp = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)

        task = TaskContext.create(
            task_id=TaskId("task-1"),
            workspace_id=WorkspaceId("workspace-1"),
            title="Define platform domain",
            created_at=timestamp,
            description="Initial task context",
            context_update_ids=(ContextUpdateId("update-1"),),
            linked_file_paths=("docs/state_snapshot_fixture.json",),
        )

        self.assertEqual(task.task_id.value, "task-1")
        self.assertEqual(task.workspace_id.value, "workspace-1")
        self.assertEqual(task.status, TaskStatus.OPEN)
        self.assertEqual(task.created_at, timestamp)
        self.assertEqual(task.updated_at, timestamp)
        self.assertEqual(task.context_update_ids[0].value, "update-1")
        self.assertEqual(task.linked_file_paths, ("docs/state_snapshot_fixture.json",))
        self.assertFalse(hasattr(task, "final_answer_candidate"))

    def test_task_updates_return_new_snapshots(self) -> None:
        created_at = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)
        updated_at = datetime(2026, 6, 2, 10, 5, tzinfo=timezone.utc)
        task = TaskContext.create(
            workspace_id=WorkspaceId("workspace-1"),
            title="Define platform domain",
            created_at=created_at,
        )

        assigned = task.assign(AgentId("agent-1"), updated_at=updated_at)
        progressed = assigned.transition(TaskStatus.IN_PROGRESS, updated_at=updated_at)
        linked = progressed.add_context_update(
            ContextUpdateId("update-1"),
            updated_at=updated_at,
        ).link_file("python-core/src/agent_os/domain/entities/task.py", updated_at=updated_at)

        self.assertIsNone(task.assignee_agent_id)
        self.assertEqual(assigned.assignee_agent_id, AgentId("agent-1"))
        self.assertEqual(progressed.status, TaskStatus.IN_PROGRESS)
        self.assertEqual(linked.context_update_ids, (ContextUpdateId("update-1"),))
        self.assertEqual(
            linked.linked_file_paths,
            ("python-core/src/agent_os/domain/entities/task.py",),
        )
        self.assertEqual(linked.updated_at, updated_at)

    def test_task_rejects_empty_title_and_duplicate_links(self) -> None:
        with self.assertRaises(ValueError):
            TaskContext.create(
                workspace_id=WorkspaceId("workspace-1"),
                title=" ",
            )

        task = TaskContext.create(
            workspace_id=WorkspaceId("workspace-1"),
            title="Define platform domain",
        )
        with self.assertRaises(ValueError):
            task.add_context_update(ContextUpdateId("update-1")).add_context_update(
                ContextUpdateId("update-1")
            )
        with self.assertRaises(ValueError):
            task.link_file("docs/state_snapshot_fixture.json").link_file("docs/state_snapshot_fixture.json")


class IssueContextTests(unittest.TestCase):
    def test_create_issue_context_scopes_issue_to_workspace(self) -> None:
        timestamp = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)

        issue = IssueContext.create(
            issue_id=IssueId("issue-1"),
            workspace_id=WorkspaceId("workspace-1"),
            title="Missing task model",
            severity=IssueSeverity.HIGH,
            created_at=timestamp,
            context_update_ids=(ContextUpdateId("update-1"),),
            linked_file_paths=("docs/migration_handoff.md",),
        )

        self.assertEqual(issue.issue_id.value, "issue-1")
        self.assertEqual(issue.workspace_id.value, "workspace-1")
        self.assertEqual(issue.status, IssueStatus.OPEN)
        self.assertEqual(issue.severity, IssueSeverity.HIGH)
        self.assertEqual(issue.created_at, timestamp)
        self.assertEqual(issue.updated_at, timestamp)
        self.assertEqual(issue.context_update_ids, (ContextUpdateId("update-1"),))
        self.assertEqual(issue.linked_file_paths, ("docs/migration_handoff.md",))
        self.assertFalse(hasattr(issue, "final_answer_candidate"))

    def test_issue_updates_return_new_snapshots(self) -> None:
        created_at = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)
        updated_at = datetime(2026, 6, 2, 10, 5, tzinfo=timezone.utc)
        issue = IssueContext.create(
            workspace_id=WorkspaceId("workspace-1"),
            title="Missing task model",
            created_at=created_at,
        )

        linked = issue.link_task(TaskId("task-1"), updated_at=updated_at)
        triaged = linked.transition(IssueStatus.TRIAGED, updated_at=updated_at)
        updated = triaged.add_context_update(
            ContextUpdateId("update-1"),
            updated_at=updated_at,
        ).link_file("python-core/src/agent_os/domain/entities/task.py", updated_at=updated_at)

        self.assertIsNone(issue.linked_task_id)
        self.assertEqual(linked.linked_task_id, TaskId("task-1"))
        self.assertEqual(triaged.status, IssueStatus.TRIAGED)
        self.assertEqual(updated.context_update_ids, (ContextUpdateId("update-1"),))
        self.assertEqual(
            updated.linked_file_paths,
            ("python-core/src/agent_os/domain/entities/task.py",),
        )
        self.assertEqual(updated.updated_at, updated_at)

    def test_issue_rejects_empty_title_and_duplicate_links(self) -> None:
        with self.assertRaises(ValueError):
            IssueContext.create(
                workspace_id=WorkspaceId("workspace-1"),
                title="",
            )

        issue = IssueContext.create(
            workspace_id=WorkspaceId("workspace-1"),
            title="Missing task model",
        )
        with self.assertRaises(ValueError):
            issue.add_context_update(ContextUpdateId("update-1")).add_context_update(
                ContextUpdateId("update-1")
            )
        with self.assertRaises(ValueError):
            issue.link_file("docs/state_snapshot_fixture.json").link_file("docs/state_snapshot_fixture.json")


if __name__ == "__main__":
    unittest.main()
