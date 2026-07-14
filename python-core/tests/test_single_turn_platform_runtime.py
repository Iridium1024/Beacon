from __future__ import annotations

import sqlite3
import sys
import unittest
import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.single_turn_platform_runtime import (
    SingleTurnPlatformRuntime,
)
from agent_os.domain.entities.agent import AgentCapability, AgentRegistration
from agent_os.domain.entities.context import (
    ContextUpdateInfo,
    ContextUpdateKind,
    ProjectSharedContext,
)
from agent_os.domain.entities.invocation import (
    AgentInvocationRequest,
    AgentInvocationResult,
    AgentInvocationResultStatus,
)
from agent_os.domain.entities.workspace import ProjectWorkspace
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextId,
    ContextUpdateId,
    PlatformEventId,
    PlatformRunSessionId,
    WorkspaceId,
)
from agent_os.infrastructure.persistence.context_update_events import (
    SqliteContextUpdateEventRecorder,
)
from agent_os.infrastructure.persistence.invocation_records import (
    SqliteAgentInvocationRecordStore,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteAgentRegistrationStateStore,
    SqliteContextStateStore,
    SqliteWorkspaceStateStore,
)
from agent_os.infrastructure.persistence.sqlite_persistence import SqlitePlatformPersistence


class SingleTurnPlatformRuntimeTests(unittest.TestCase):
    def test_run_single_turn_records_user_context_and_returns_placeholder_result(
        self,
    ) -> None:
        connection = self._connection()
        context = self._context(connection)
        requested_at = datetime(2026, 6, 4, 3, 45, tzinfo=timezone.utc)
        request = AgentInvocationRequest.create(
            invocation_id=AgentInvocationId("invoke-1"),
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
            instruction="Summarize the current MVP platform status.",
            requested_at=requested_at,
            requested_capability="single-turn-status",
            file_references=("docs/state_snapshot_fixture.json",),
            idempotency_key="idem-1",
            correlation_id="corr-1",
            metadata={"source": "unit-test"},
        )

        result = SingleTurnPlatformRuntime(
            context_update_recorder=SqliteContextUpdateEventRecorder(connection)
        ).run_single_turn(
            context=context,
            invocation_request=request,
            update_id=ContextUpdateId("update-user-1"),
            event_id=PlatformEventId("event-user-1"),
            session_id=PlatformRunSessionId("session-1"),
            context_metadata={"test_case": "single-turn"},
            event_metadata={"phase": "request-capture"},
        )

        self.assertEqual(
            result.user_context_update.update_kind,
            ContextUpdateKind.USER_MESSAGE,
        )
        self.assertEqual(
            result.user_context_update.payload["instruction"],
            "Summarize the current MVP platform status.",
        )
        self.assertEqual(
            result.user_context_update.payload["file_references"],
            ["docs/state_snapshot_fixture.json"],
        )
        self.assertEqual(
            result.user_context_update.metadata["source"],
            "single_turn_platform_runtime",
        )
        self.assertFalse(result.user_context_update.metadata["model_invoked"])
        self.assertFalse(result.user_context_update.metadata["tool_invoked"])

        self.assertEqual(result.recorded_context_update.source_event_sequence, 1)
        self.assertEqual(len(result.context.updates), 1)
        self.assertEqual(
            result.context.materialized_state["last_user_instruction"]["invocation_id"],
            "invoke-1",
        )
        self.assertEqual(
            result.context.materialized_state["last_user_instruction"][
                "context_update_id"
            ],
            "update-user-1",
        )

        self.assertEqual(
            result.invocation_result.status,
            AgentInvocationResultStatus.SUCCEEDED,
        )
        self.assertEqual(
            tuple(result.invocation_result.context_update_ids),
            (ContextUpdateId("update-user-1"),),
        )
        self.assertFalse(result.invocation_result.output_payload["model_invoked"])
        self.assertFalse(result.invocation_result.output_payload["tool_invoked"])
        self.assertEqual(
            result.invocation_result.metadata["source"],
            "deterministic_agent_invocation_adapter",
        )
        self.assertIsNone(result.agent_invocation_event_sequence)

        event_row = connection.execute(
            """
            SELECT event_id, event_kind, aggregate_id, session_id, metadata_json
            FROM platform_events
            """
        ).fetchone()
        self.assertEqual(
            event_row,
            (
                "event-user-1",
                "context.update_appended",
                "update-user-1",
                "session-1",
                '{"phase":"request-capture","source":"single_turn_platform_runtime"}',
            ),
        )

        stored_context = SqliteContextStateStore(connection).get_context_state(
            WorkspaceId("workspace-1")
        )
        self.assertIsNotNone(stored_context)
        assert stored_context is not None
        self.assertEqual(stored_context.update_count, 1)
        self.assertEqual(
            stored_context.context.materialized_state["last_user_instruction"]["agent_id"],
            "agent-1",
        )
        self.assertEqual(
            connection.execute(
                "SELECT count(*) FROM platform_agent_invocation_records"
            ).fetchone()[0],
            0,
        )

    def test_run_single_turn_uses_agent_invocation_adapter_for_result(self) -> None:
        connection = self._connection()
        context = self._context(connection)
        adapter = RecordingAgentInvocationAdapter()
        request = AgentInvocationRequest.create(
            invocation_id=AgentInvocationId("invoke-1"),
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
            instruction="Use the adapter boundary.",
            requested_at=datetime(2026, 6, 4, 4, 55, tzinfo=timezone.utc),
        )

        result = SingleTurnPlatformRuntime(
            context_update_recorder=SqliteContextUpdateEventRecorder(connection),
            agent_invocation_adapter=adapter,
        ).run_single_turn(
            context=context,
            invocation_request=request,
            update_id=ContextUpdateId("update-user-1"),
            event_id=PlatformEventId("event-context-1"),
        )

        self.assertEqual(
            adapter.calls,
            [("invoke-1", "context-1", "update-user-1", 1)],
        )
        self.assertEqual(result.invocation_result.summary, "Adapter result")
        self.assertEqual(result.invocation_result.output_text, "Adapter output")
        self.assertEqual(result.invocation_result.output_payload["adapter"], "custom")
        self.assertEqual(result.invocation_result.metadata["source"], "test-adapter")
        self.assertEqual(
            tuple(result.invocation_result.context_update_ids),
            (ContextUpdateId("update-user-1"),),
        )

    def test_run_single_turn_can_persist_agent_invocation_audit_record(self) -> None:
        connection = self._connection()
        context = self._context(connection)
        self._insert_agent_registration(connection)
        invocation_store = SqliteAgentInvocationRecordStore(connection)
        request = AgentInvocationRequest.create(
            invocation_id=AgentInvocationId("invoke-1"),
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
            instruction="Capture a recoverable single-turn audit record.",
            requested_at=datetime(2026, 6, 4, 4, 20, tzinfo=timezone.utc),
            requested_capability="single-turn-status",
            idempotency_key="idem-1",
            correlation_id="corr-1",
            metadata={"source": "unit-test"},
        )

        result = SingleTurnPlatformRuntime(
            context_update_recorder=SqliteContextUpdateEventRecorder(connection),
            agent_invocation_recorder=invocation_store,
        ).run_single_turn(
            context=context,
            invocation_request=request,
            update_id=ContextUpdateId("update-user-1"),
            event_id=PlatformEventId("event-context-1"),
            invocation_event_id=PlatformEventId("event-invoke-1"),
            session_id=PlatformRunSessionId("session-1"),
            invocation_event_metadata={"phase": "audit"},
        )

        record = invocation_store.get_agent_invocation_record(
            AgentInvocationId("invoke-1")
        )
        event_rows = connection.execute(
            """
            SELECT sequence, event_kind, aggregate_id, session_id,
                   metadata_json, payload_json
            FROM platform_events
            ORDER BY sequence
            """
        ).fetchall()

        self.assertEqual(result.agent_invocation_requested_event_sequence, 2)
        self.assertEqual(result.agent_invocation_event_sequence, 3)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(record.source_event_sequence, 3)
        self.assertEqual(record.request_state["instruction"], request.instruction)
        self.assertEqual(record.result_state["summary"], result.invocation_result.summary)
        self.assertEqual(
            tuple(update_id.value for update_id in record.context_update_ids),
            ("update-user-1",),
        )
        self.assertEqual(
            tuple(row[:4] for row in event_rows),
            (
                (1, "context.update_appended", "update-user-1", "session-1"),
                (2, "agent_invocation.recorded", "invoke-1", "session-1"),
                (3, "agent_invocation.recorded", "invoke-1", "session-1"),
            ),
        )
        self.assertEqual(
            json.loads(event_rows[1][4]),
            {"phase": "requested", "source": "single_turn_platform_runtime"},
        )
        self.assertEqual(
            json.loads(event_rows[1][5])["status"],
            "requested",
        )
        self.assertEqual(
            json.loads(event_rows[2][4]),
            {"phase": "terminal", "source": "single_turn_platform_runtime"},
        )
        self.assertEqual(json.loads(event_rows[2][5])["status"], "succeeded")

    def test_adapter_exception_records_failed_invocation_after_request_state(
        self,
    ) -> None:
        connection = self._connection()
        context = self._context(connection)
        self._insert_agent_registration(connection)
        invocation_store = SqliteAgentInvocationRecordStore(connection)
        request = AgentInvocationRequest.create(
            invocation_id=AgentInvocationId("invoke-adapter-fail-1"),
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
            instruction="Use an adapter that raises.",
            requested_at=datetime(2026, 6, 4, 4, 25, tzinfo=timezone.utc),
            requested_capability="single-turn-status",
        )

        result = SingleTurnPlatformRuntime(
            context_update_recorder=SqliteContextUpdateEventRecorder(connection),
            agent_invocation_recorder=invocation_store,
            agent_invocation_adapter=RaisingAgentInvocationAdapter(),
        ).run_single_turn(
            context=context,
            invocation_request=request,
            update_id=ContextUpdateId("update-adapter-fail-1"),
            event_id=PlatformEventId("event-context-adapter-fail-1"),
            invocation_event_id=PlatformEventId("event-invoke-adapter-fail-1"),
            session_id=PlatformRunSessionId("session-adapter-fail-1"),
        )

        self.assertEqual(result.recorded_context_update.source_event_sequence, 1)
        self.assertEqual(result.agent_invocation_requested_event_sequence, 2)
        self.assertEqual(result.agent_invocation_event_sequence, 3)
        self.assertEqual(result.invocation_result.status, AgentInvocationResultStatus.FAILED)
        self.assertEqual(result.invocation_result.error_message, "adapter unavailable")
        self.assertEqual(
            result.invocation_result.metadata["adapter_exception_type"],
            "RuntimeError",
        )
        record = invocation_store.get_agent_invocation_record(
            AgentInvocationId("invoke-adapter-fail-1")
        )
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.status, "failed")
        self.assertEqual(record.source_event_sequence, 3)
        self.assertEqual(
            connection.execute(
                "SELECT event_kind FROM platform_events ORDER BY sequence"
            ).fetchall(),
            [
                ("context.update_appended",),
                ("agent_invocation.recorded",),
                ("agent_invocation.recorded",),
            ],
        )

    def test_run_single_turn_records_failed_lifecycle_when_started_run_fails(
        self,
    ) -> None:
        context = ProjectSharedContext.create(
            context_id=ContextId("context-1"),
            workspace_id=WorkspaceId("workspace-1"),
        )
        lifecycle_recorder = RecordingRunSessionLifecycleRecorder()
        request = AgentInvocationRequest.create(
            invocation_id=AgentInvocationId("invoke-context-fail-1"),
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
            instruction="This fails after the run session starts.",
            requested_at=datetime(2026, 6, 4, 4, 35, tzinfo=timezone.utc),
            correlation_id="corr-context-fail-1",
        )

        with self.assertRaisesRegex(RuntimeError, "context recorder unavailable"):
            SingleTurnPlatformRuntime(
                context_update_recorder=FailingContextUpdateRecorder(),
                run_session_lifecycle_recorder=lifecycle_recorder,
            ).run_single_turn(
                context=context,
                invocation_request=request,
                session_id=PlatformRunSessionId("session-context-fail-1"),
                invocation_event_metadata={"surface": "unit-test"},
            )

        self.assertEqual(
            [call["status"] for call in lifecycle_recorder.calls],
            ["running", "failed"],
        )
        self.assertEqual(
            [call["metadata"]["phase"] for call in lifecycle_recorder.calls],
            ["started", "terminal"],
        )
        self.assertEqual(
            lifecycle_recorder.calls[1]["metadata"]["exception_type"],
            "RuntimeError",
        )
        self.assertEqual(
            lifecycle_recorder.calls[1]["metadata"]["failure_phase"],
            "single_turn_runtime",
        )

    def test_run_single_turn_rejects_workspace_mismatch_before_recording(self) -> None:
        connection = self._connection()
        context = self._context(connection)
        request = AgentInvocationRequest.create(
            workspace_id=WorkspaceId("workspace-2"),
            agent_id=AgentId("agent-1"),
            instruction="This should not be recorded.",
        )

        with self.assertRaisesRegex(ValueError, "workspace_id"):
            SingleTurnPlatformRuntime(
                context_update_recorder=SqliteContextUpdateEventRecorder(connection)
            ).run_single_turn(context=context, invocation_request=request)

        self.assertEqual(
            connection.execute("SELECT count(*) FROM platform_events").fetchone()[0],
            0,
        )
        stored_context = SqliteContextStateStore(connection).get_context_state(
            WorkspaceId("workspace-1")
        )
        self.assertIsNone(stored_context)

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        return connection

    def _context(self, connection: sqlite3.Connection) -> ProjectSharedContext:
        workspace = ProjectWorkspace.create(
            workspace_id=WorkspaceId("workspace-1"),
            display_name="Workspace 1",
            root_path="/tmp/workspace-1",
        )
        SqliteWorkspaceStateStore(connection).upsert_workspace_state(
            workspace=workspace,
            source_event_sequence=0,
        )
        return ProjectSharedContext.create(
            context_id=ContextId("context-1"),
            workspace_id=WorkspaceId("workspace-1"),
            materialized_state={"status": "open"},
        )

    def _insert_agent_registration(self, connection: sqlite3.Connection) -> None:
        registration = AgentRegistration.register(
            agent_id=AgentId("agent-1"),
            workspace_id=WorkspaceId("workspace-1"),
            name="Local Runtime Agent",
            description="Handles deterministic single-turn runtime tests",
            capabilities=(
                AgentCapability(
                    name="single-turn-status",
                    description="Captures single-turn status requests",
                ),
            ),
            created_at=datetime(2026, 6, 4, 4, 0, tzinfo=timezone.utc),
            default_model="deterministic-placeholder",
        )
        SqliteAgentRegistrationStateStore(connection).upsert_agent_registration_state(
            registration=registration,
            source_event_sequence=0,
        )


class RecordingAgentInvocationAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, int]] = []

    def invoke(
        self,
        *,
        request: AgentInvocationRequest,
        context: ProjectSharedContext,
        user_context_update: ContextUpdateInfo,
        completed_at: datetime,
    ) -> AgentInvocationResult:
        self.calls.append(
            (
                request.invocation_id.value,
                context.context_id.value,
                user_context_update.update_id.value,
                len(context.updates),
            )
        )
        return AgentInvocationResult.succeed(
            request=request,
            summary="Adapter result",
            completed_at=completed_at,
            output_text="Adapter output",
            output_payload={
                "adapter": "custom",
                "context_update_id": user_context_update.update_id.value,
            },
            context_update_ids=(user_context_update.update_id,),
            metadata={"source": "test-adapter"},
        )


class RaisingAgentInvocationAdapter:
    def invoke(
        self,
        *,
        request: AgentInvocationRequest,
        context: ProjectSharedContext,
        user_context_update: ContextUpdateInfo,
        completed_at: datetime,
    ) -> AgentInvocationResult:
        raise RuntimeError("adapter unavailable")


class FailingContextUpdateRecorder:
    def record_context_update_event(self, **_kwargs: object) -> object:
        raise RuntimeError("context recorder unavailable")


class RecordingRunSessionLifecycleRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def record_run_session_event(
        self,
        *,
        workspace_id: WorkspaceId,
        session_id: PlatformRunSessionId,
        status: str,
        occurred_at: datetime,
        agent_id: AgentId | None = None,
        invocation_id: AgentInvocationId | None = None,
        correlation_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> int:
        self.calls.append(
            {
                "workspace_id": workspace_id.value,
                "session_id": session_id.value,
                "status": status,
                "occurred_at": occurred_at,
                "agent_id": agent_id.value if agent_id is not None else None,
                "invocation_id": (
                    invocation_id.value
                    if invocation_id is not None
                    else None
                ),
                "correlation_id": correlation_id,
                "metadata": dict(metadata or {}),
            }
        )
        return len(self.calls)


if __name__ == "__main__":
    unittest.main()
