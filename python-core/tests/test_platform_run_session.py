from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.domain.entities.run_session import (
    PlatformRunSession,
    PlatformRunSessionStatus,
)
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextUpdateId,
    FileOperationId,
    PlatformRunSessionId,
    TaskId,
    WorkspaceId,
)


class PlatformRunSessionTests(unittest.TestCase):
    def test_open_session_scopes_state_to_workspace(self) -> None:
        timestamp = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)

        session = PlatformRunSession.open(
            session_id=PlatformRunSessionId("session-1"),
            workspace_id=WorkspaceId("workspace-1"),
            created_at=timestamp,
            metadata={"source": "test"},
        )

        self.assertEqual(session.session_id.value, "session-1")
        self.assertEqual(session.workspace_id.value, "workspace-1")
        self.assertEqual(session.status, PlatformRunSessionStatus.OPEN)
        self.assertEqual(session.created_at, timestamp)
        self.assertEqual(session.updated_at, timestamp)
        self.assertIsNone(session.started_at)
        self.assertIsNone(session.ended_at)
        self.assertEqual(session.active_agent_ids, ())
        self.assertEqual(session.metadata["source"], "test")

    def test_lifecycle_transitions_return_new_snapshots(self) -> None:
        created_at = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)
        started_at = datetime(2026, 6, 2, 10, 1, tzinfo=timezone.utc)
        paused_at = datetime(2026, 6, 2, 10, 2, tzinfo=timezone.utc)
        resumed_at = datetime(2026, 6, 2, 10, 3, tzinfo=timezone.utc)
        completed_at = datetime(2026, 6, 2, 10, 4, tzinfo=timezone.utc)
        session = PlatformRunSession.open(
            workspace_id=WorkspaceId("workspace-1"),
            created_at=created_at,
        )

        running = session.start(started_at=started_at)
        paused = running.pause(paused_at=paused_at)
        resumed = paused.resume(resumed_at=resumed_at)
        completed = resumed.complete(completed_at=completed_at)

        self.assertEqual(session.status, PlatformRunSessionStatus.OPEN)
        self.assertEqual(running.status, PlatformRunSessionStatus.RUNNING)
        self.assertEqual(running.started_at, started_at)
        self.assertEqual(paused.status, PlatformRunSessionStatus.PAUSED)
        self.assertEqual(paused.updated_at, paused_at)
        self.assertEqual(resumed.status, PlatformRunSessionStatus.RUNNING)
        self.assertEqual(resumed.updated_at, resumed_at)
        self.assertEqual(completed.status, PlatformRunSessionStatus.COMPLETED)
        self.assertEqual(completed.ended_at, completed_at)

    def test_session_tracks_related_platform_ids(self) -> None:
        created_at = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)
        updated_at = datetime(2026, 6, 2, 10, 1, tzinfo=timezone.utc)
        session = PlatformRunSession.open(
            workspace_id=WorkspaceId("workspace-1"),
            created_at=created_at,
        )

        tracked = (
            session.add_agent(AgentId("agent-1"), updated_at=updated_at)
            .add_task(TaskId("task-1"), updated_at=updated_at)
            .add_invocation(AgentInvocationId("invoke-1"), updated_at=updated_at)
            .add_context_update(ContextUpdateId("update-1"), updated_at=updated_at)
            .add_file_operation(FileOperationId("file-op-1"), updated_at=updated_at)
        )

        self.assertEqual(session.active_agent_ids, ())
        self.assertEqual(tracked.active_agent_ids, (AgentId("agent-1"),))
        self.assertEqual(tracked.task_ids, (TaskId("task-1"),))
        self.assertEqual(tracked.invocation_ids, (AgentInvocationId("invoke-1"),))
        self.assertEqual(tracked.context_update_ids, (ContextUpdateId("update-1"),))
        self.assertEqual(tracked.file_operation_ids, (FileOperationId("file-op-1"),))
        self.assertEqual(tracked.updated_at, updated_at)

    def test_session_rejects_duplicate_related_ids(self) -> None:
        session = PlatformRunSession.open(workspace_id=WorkspaceId("workspace-1"))

        with self.assertRaises(ValueError):
            session.add_agent(AgentId("agent-1")).add_agent(AgentId("agent-1"))

        with self.assertRaises(ValueError):
            session.add_invocation(AgentInvocationId("invoke-1")).add_invocation(
                AgentInvocationId("invoke-1")
            )

    def test_fail_and_cancel_create_terminal_snapshots(self) -> None:
        created_at = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)
        started_at = datetime(2026, 6, 2, 10, 1, tzinfo=timezone.utc)
        failed_at = datetime(2026, 6, 2, 10, 5, tzinfo=timezone.utc)
        cancelled_at = datetime(2026, 6, 2, 10, 6, tzinfo=timezone.utc)
        session = PlatformRunSession.open(
            workspace_id=WorkspaceId("workspace-1"),
            created_at=created_at,
        ).start(started_at=started_at)

        failed = session.fail("Provider unavailable", failed_at=failed_at)
        cancelled = session.cancel(cancelled_at=cancelled_at)

        self.assertEqual(failed.status, PlatformRunSessionStatus.FAILED)
        self.assertEqual(failed.error_message, "Provider unavailable")
        self.assertEqual(failed.ended_at, failed_at)
        self.assertEqual(cancelled.status, PlatformRunSessionStatus.CANCELLED)
        self.assertIsNone(cancelled.error_message)
        self.assertEqual(cancelled.ended_at, cancelled_at)

        with self.assertRaises(ValueError):
            session.fail(" ")

    def test_terminal_session_rejects_lifecycle_and_tracking_changes(self) -> None:
        created_at = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)
        started_at = datetime(2026, 6, 2, 10, 1, tzinfo=timezone.utc)
        completed_at = datetime(2026, 6, 2, 10, 2, tzinfo=timezone.utc)
        completed = (
            PlatformRunSession.open(
                workspace_id=WorkspaceId("workspace-1"),
                created_at=created_at,
            )
            .start(started_at=started_at)
            .complete(completed_at=completed_at)
        )

        with self.assertRaisesRegex(ValueError, "terminal sessions cannot be modified"):
            completed.start()

        with self.assertRaisesRegex(ValueError, "terminal sessions cannot be modified"):
            completed.fail("Provider unavailable")

        with self.assertRaisesRegex(ValueError, "terminal sessions cannot be modified"):
            completed.add_agent(AgentId("agent-1"))

        with self.assertRaisesRegex(ValueError, "terminal sessions cannot be modified"):
            completed.add_invocation(AgentInvocationId("invoke-1"))

    def test_session_rejects_invalid_direct_state(self) -> None:
        created_at = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)
        started_at = datetime(2026, 6, 2, 10, 1, tzinfo=timezone.utc)

        with self.assertRaises(ValueError):
            PlatformRunSession(
                session_id=PlatformRunSessionId("session-1"),
                workspace_id=WorkspaceId("workspace-1"),
                status=PlatformRunSessionStatus.RUNNING,
                created_at=created_at,
                updated_at=created_at,
            )

        with self.assertRaises(ValueError):
            PlatformRunSession(
                session_id=PlatformRunSessionId("session-1"),
                workspace_id=WorkspaceId("workspace-1"),
                status=PlatformRunSessionStatus.FAILED,
                created_at=created_at,
                updated_at=started_at,
                started_at=started_at,
                ended_at=started_at,
            )

        with self.assertRaises(ValueError):
            PlatformRunSession(
                session_id=PlatformRunSessionId("session-1"),
                workspace_id=WorkspaceId("workspace-1"),
                status=PlatformRunSessionStatus.OPEN,
                created_at=created_at,
                updated_at=created_at,
                ended_at=started_at,
            )


if __name__ == "__main__":
    unittest.main()
