from __future__ import annotations

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
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    ContextId,
    ContextUpdateId,
    WorkspaceId,
)


class ContextUpdateInfoTests(unittest.TestCase):
    def test_create_context_update_uses_platform_event_fields_only(self) -> None:
        timestamp = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)

        update = ContextUpdateInfo.create(
            update_id=ContextUpdateId("update-1"),
            workspace_id=WorkspaceId("workspace-1"),
            update_kind=ContextUpdateKind.NOTE,
            summary="Captured initial project note",
            created_at=timestamp,
            source_agent_id=AgentId("agent-1"),
            payload={"note": "initial"},
            materialized_state_patch={"latest_note": "initial"},
        )

        self.assertEqual(update.update_id.value, "update-1")
        self.assertEqual(update.workspace_id.value, "workspace-1")
        self.assertEqual(update.update_kind, ContextUpdateKind.NOTE)
        self.assertEqual(update.summary, "Captured initial project note")
        self.assertEqual(update.created_at, timestamp)
        self.assertEqual(update.source_agent_id, AgentId("agent-1"))
        self.assertEqual(update.payload["note"], "initial")
        self.assertEqual(update.materialized_state_patch["latest_note"], "initial")
        self.assertFalse(hasattr(update, "final_answer_candidate"))

    def test_context_update_rejects_empty_summary(self) -> None:
        with self.assertRaises(ValueError):
            ContextUpdateInfo.create(
                workspace_id=WorkspaceId("workspace-1"),
                update_kind=ContextUpdateKind.NOTE,
                summary="",
            )


class ProjectSharedContextTests(unittest.TestCase):
    def test_create_context_starts_with_empty_append_only_history(self) -> None:
        timestamp = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)

        context = ProjectSharedContext.create(
            context_id=ContextId("context-1"),
            workspace_id=WorkspaceId("workspace-1"),
            created_at=timestamp,
            materialized_state={"status": "open"},
        )

        self.assertEqual(context.context_id.value, "context-1")
        self.assertEqual(context.workspace_id.value, "workspace-1")
        self.assertEqual(context.updates, ())
        self.assertEqual(context.materialized_state["status"], "open")
        self.assertEqual(context.created_at, timestamp)
        self.assertEqual(context.updated_at, timestamp)
        self.assertFalse(hasattr(context, "final_answer_candidates"))

    def test_append_update_returns_new_context_and_materialized_state(self) -> None:
        created_at = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)
        updated_at = datetime(2026, 6, 2, 10, 5, tzinfo=timezone.utc)
        workspace_id = WorkspaceId("workspace-1")
        context = ProjectSharedContext.create(
            workspace_id=workspace_id,
            created_at=created_at,
            materialized_state={"status": "open"},
        )
        update = ContextUpdateInfo.create(
            update_id=ContextUpdateId("update-1"),
            workspace_id=workspace_id,
            update_kind=ContextUpdateKind.USER_MESSAGE,
            summary="User requested initial setup",
            created_at=updated_at,
            materialized_state_patch={"latest_user_message": "initial setup"},
        )

        updated_context = context.append_update(update)

        self.assertEqual(context.updates, ())
        self.assertEqual(context.materialized_state["status"], "open")
        self.assertEqual(updated_context.updates, (update,))
        self.assertEqual(updated_context.materialized_state["status"], "open")
        self.assertEqual(
            updated_context.materialized_state["latest_user_message"],
            "initial setup",
        )
        self.assertEqual(updated_context.updated_at, updated_at)

    def test_context_rejects_cross_workspace_update(self) -> None:
        context = ProjectSharedContext.create(workspace_id=WorkspaceId("workspace-1"))
        update = ContextUpdateInfo.create(
            workspace_id=WorkspaceId("workspace-2"),
            update_kind=ContextUpdateKind.NOTE,
            summary="Wrong workspace",
        )

        with self.assertRaises(ValueError):
            context.append_update(update)

    def test_context_rejects_duplicate_update_ids(self) -> None:
        workspace_id = WorkspaceId("workspace-1")
        context = ProjectSharedContext.create(workspace_id=workspace_id)
        first = ContextUpdateInfo.create(
            update_id=ContextUpdateId("update-1"),
            workspace_id=workspace_id,
            update_kind=ContextUpdateKind.NOTE,
            summary="First update",
        )
        duplicate = ContextUpdateInfo.create(
            update_id=ContextUpdateId("update-1"),
            workspace_id=workspace_id,
            update_kind=ContextUpdateKind.DECISION,
            summary="Duplicate id",
        )

        with self.assertRaises(ValueError):
            context.append_update(first).append_update(duplicate)

    def test_recent_updates_and_kind_filtering(self) -> None:
        workspace_id = WorkspaceId("workspace-1")
        context = ProjectSharedContext.create(workspace_id=workspace_id)
        note = ContextUpdateInfo.create(
            update_id=ContextUpdateId("update-1"),
            workspace_id=workspace_id,
            update_kind=ContextUpdateKind.NOTE,
            summary="Note",
        )
        decision = ContextUpdateInfo.create(
            update_id=ContextUpdateId("update-2"),
            workspace_id=workspace_id,
            update_kind=ContextUpdateKind.DECISION,
            summary="Decision",
        )

        updated_context = context.append_update(note).append_update(decision)

        self.assertEqual(updated_context.recent_updates(limit=1), (decision,))
        self.assertEqual(updated_context.updates_by_kind(ContextUpdateKind.NOTE), (note,))
        self.assertEqual(updated_context.recent_updates(limit=0), ())


if __name__ == "__main__":
    unittest.main()
