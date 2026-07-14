"""Local single-turn platform runtime skeleton."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping, Protocol

from agent_os.domain.entities.context import (
    ContextUpdateInfo,
    ContextUpdateKind,
    ProjectSharedContext,
)
from agent_os.domain.entities.invocation import (
    AgentInvocationRequest,
    AgentInvocationResult,
)
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextUpdateId,
    PlatformEventId,
    PlatformRunSessionId,
    WorkspaceId,
)


class RecordedContextUpdateView(Protocol):
    """Recorded context update view returned by a recorder port."""

    context: ProjectSharedContext
    source_event_sequence: int


class ContextUpdateRecorderPort(Protocol):
    """Recorder boundary for appending a context update to canonical state."""

    def record_context_update_event(
        self,
        *,
        context: ProjectSharedContext,
        update: ContextUpdateInfo,
        event_id: PlatformEventId | None = None,
        occurred_at: datetime | None = None,
        session_id: PlatformRunSessionId | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> RecordedContextUpdateView:
        """Append a context update and return the materialized context view."""
        ...


class AgentInvocationRecorderPort(Protocol):
    """Recorder boundary for persisting an agent invocation audit record."""

    def record_agent_invocation_event(
        self,
        *,
        request: AgentInvocationRequest,
        result: AgentInvocationResult | None = None,
        event_id: PlatformEventId | None = None,
        occurred_at: datetime | None = None,
        session_id: PlatformRunSessionId | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> int:
        """Append an invocation audit event and return its event sequence."""
        ...


class RunSessionLifecycleRecorderPort(Protocol):
    """Recorder boundary for recoverable run-session lifecycle events."""

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
        metadata: Mapping[str, object] | None = None,
    ) -> int:
        """Append a run-session lifecycle event and return its event sequence."""
        ...


class AgentInvocationAdapterPort(Protocol):
    """Replaceable boundary for producing one agent invocation result."""

    def invoke(
        self,
        *,
        request: AgentInvocationRequest,
        context: ProjectSharedContext,
        user_context_update: ContextUpdateInfo,
        completed_at: datetime,
    ) -> AgentInvocationResult:
        """Produce a result for one single-turn platform invocation."""
        ...


@dataclass(frozen=True, slots=True)
class DeterministicAgentInvocationAdapter:
    """Local deterministic adapter used until a real model adapter is wired."""

    summary: str = "Recorded single-turn platform instruction."
    output_text: str = "Deterministic placeholder response. Model invocation is not wired."

    def invoke(
        self,
        *,
        request: AgentInvocationRequest,
        context: ProjectSharedContext,
        user_context_update: ContextUpdateInfo,
        completed_at: datetime,
    ) -> AgentInvocationResult:
        return AgentInvocationResult.succeed(
            request,
            summary=self.summary,
            completed_at=completed_at,
            output_text=self.output_text,
            output_payload={
                "model_invoked": False,
                "tool_invoked": False,
                "context_id": context.context_id.value,
                "context_update_id": user_context_update.update_id.value,
            },
            context_update_ids=(user_context_update.update_id,),
            metadata={
                "source": "deterministic_agent_invocation_adapter",
                "deterministic_placeholder": True,
            },
        )


@dataclass(frozen=True, slots=True)
class SingleTurnPlatformRunResult:
    """Result produced by the deterministic single-turn runtime skeleton."""

    context: ProjectSharedContext
    user_context_update: ContextUpdateInfo
    recorded_context_update: RecordedContextUpdateView
    invocation_result: AgentInvocationResult
    agent_invocation_requested_event_sequence: int | None = None
    agent_invocation_event_sequence: int | None = None
    run_session_started_event_sequence: int | None = None
    run_session_terminal_event_sequence: int | None = None


@dataclass(slots=True)
class SingleTurnPlatformRuntime:
    """Record a user instruction and return a deterministic invocation result."""

    context_update_recorder: ContextUpdateRecorderPort
    agent_invocation_recorder: AgentInvocationRecorderPort | None = None
    run_session_lifecycle_recorder: RunSessionLifecycleRecorderPort | None = None
    agent_invocation_adapter: AgentInvocationAdapterPort = field(
        default_factory=DeterministicAgentInvocationAdapter
    )

    def run_single_turn(
        self,
        *,
        context: ProjectSharedContext,
        invocation_request: AgentInvocationRequest,
        update_id: ContextUpdateId | None = None,
        created_at: datetime | None = None,
        event_id: PlatformEventId | None = None,
        invocation_event_id: PlatformEventId | None = None,
        session_id: PlatformRunSessionId | None = None,
        context_metadata: Mapping[str, object] | None = None,
        event_metadata: Mapping[str, object] | None = None,
        invocation_event_metadata: Mapping[str, object] | None = None,
    ) -> SingleTurnPlatformRunResult:
        """Append the user instruction to shared context and return a placeholder result."""

        if invocation_request.workspace_id != context.workspace_id:
            raise ValueError(
                "invocation_request.workspace_id must match context.workspace_id"
            )

        run_session_started_event_sequence = self._record_run_session_lifecycle(
            request=invocation_request,
            session_id=session_id,
            status="running",
            phase="started",
            occurred_at=invocation_request.requested_at,
            metadata=invocation_event_metadata,
        )
        try:
            update_created_at = created_at or invocation_request.requested_at
            user_update = self.build_user_context_update(
                invocation_request=invocation_request,
                update_id=update_id,
                created_at=update_created_at,
                metadata=context_metadata,
            )
            recorded_update = self.context_update_recorder.record_context_update_event(
                context=context,
                update=user_update,
                event_id=event_id,
                occurred_at=update_created_at,
                session_id=session_id,
                metadata=self._event_metadata(event_metadata),
            )
            agent_invocation_requested_event_sequence = self._record_agent_invocation(
                request=invocation_request,
                result=None,
                event_id=None,
                session_id=session_id,
                metadata=invocation_event_metadata,
                phase="requested",
            )
            try:
                invocation_result = self.agent_invocation_adapter.invoke(
                    request=invocation_request,
                    context=recorded_update.context,
                    user_context_update=user_update,
                    completed_at=update_created_at,
                )
            except Exception as exc:
                invocation_result = self._adapter_failure_result(
                    request=invocation_request,
                    user_context_update=user_update,
                    completed_at=update_created_at,
                    error=exc,
                )
            self._validate_invocation_result(
                request=invocation_request,
                result=invocation_result,
            )
            agent_invocation_event_sequence = self._record_agent_invocation(
                request=invocation_request,
                result=invocation_result,
                event_id=invocation_event_id,
                session_id=session_id,
                metadata=invocation_event_metadata,
                phase="terminal",
            )
            run_session_terminal_event_sequence = self._record_run_session_lifecycle(
                request=invocation_request,
                session_id=session_id,
                status=_run_session_terminal_status(invocation_result),
                phase="terminal",
                occurred_at=invocation_result.completed_at,
                metadata=invocation_event_metadata,
            )
        except Exception as exc:
            self._record_failed_run_session_lifecycle_after_exception(
                request=invocation_request,
                session_id=session_id,
                metadata=invocation_event_metadata,
                error=exc,
            )
            raise
        return SingleTurnPlatformRunResult(
            context=recorded_update.context,
            user_context_update=user_update,
            recorded_context_update=recorded_update,
            invocation_result=invocation_result,
            agent_invocation_requested_event_sequence=(
                agent_invocation_requested_event_sequence
            ),
            agent_invocation_event_sequence=agent_invocation_event_sequence,
            run_session_started_event_sequence=run_session_started_event_sequence,
            run_session_terminal_event_sequence=run_session_terminal_event_sequence,
        )

    def build_user_context_update(
        self,
        *,
        invocation_request: AgentInvocationRequest,
        update_id: ContextUpdateId | None = None,
        created_at: datetime | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> ContextUpdateInfo:
        """Build the canonical user-message context update for a request."""

        update_created_at = created_at or invocation_request.requested_at
        return ContextUpdateInfo.create(
            update_id=update_id,
            workspace_id=invocation_request.workspace_id,
            update_kind=ContextUpdateKind.USER_MESSAGE,
            summary="User instruction captured for single-turn platform run.",
            payload=self._user_instruction_payload(invocation_request),
            materialized_state_patch=self._last_user_instruction_patch(
                invocation_request,
                update_id=update_id,
            ),
            created_at=update_created_at,
            metadata=self._context_metadata(metadata),
        )

    def _user_instruction_payload(
        self,
        invocation_request: AgentInvocationRequest,
    ) -> Mapping[str, object]:
        return {
            "invocation_id": invocation_request.invocation_id.value,
            "agent_id": invocation_request.agent_id.value,
            "instruction": invocation_request.instruction,
            "requested_at": invocation_request.requested_at.isoformat(),
            "task_id": (
                invocation_request.task_id.value
                if invocation_request.task_id is not None
                else None
            ),
            "requested_capability": invocation_request.requested_capability,
            "context_update_ids": [
                context_update_id.value
                for context_update_id in invocation_request.context_update_ids
            ],
            "file_references": list(invocation_request.file_references),
            "idempotency_key": invocation_request.idempotency_key,
            "correlation_id": invocation_request.correlation_id,
            "request_metadata": dict(invocation_request.metadata),
        }

    def _last_user_instruction_patch(
        self,
        invocation_request: AgentInvocationRequest,
        *,
        update_id: ContextUpdateId | None,
    ) -> Mapping[str, object]:
        last_user_instruction: dict[str, object] = {
            "invocation_id": invocation_request.invocation_id.value,
            "agent_id": invocation_request.agent_id.value,
            "instruction": invocation_request.instruction,
            "requested_at": invocation_request.requested_at.isoformat(),
        }
        if update_id is not None:
            last_user_instruction["context_update_id"] = update_id.value
        return {"last_user_instruction": last_user_instruction}

    def _context_metadata(
        self,
        metadata: Mapping[str, object] | None,
    ) -> Mapping[str, object]:
        merged = dict(metadata or {})
        merged.update(
            {
                "source": "single_turn_platform_runtime",
                "model_invoked": False,
                "tool_invoked": False,
            }
        )
        return merged

    def _event_metadata(
        self,
        metadata: Mapping[str, object] | None,
    ) -> Mapping[str, object]:
        merged = dict(metadata or {})
        merged["source"] = "single_turn_platform_runtime"
        return merged

    def _validate_invocation_result(
        self,
        *,
        request: AgentInvocationRequest,
        result: AgentInvocationResult,
    ) -> None:
        if result.invocation_id != request.invocation_id:
            raise ValueError("invocation result invocation_id must match request.")
        if result.workspace_id != request.workspace_id:
            raise ValueError("invocation result workspace_id must match request.")
        if result.agent_id != request.agent_id:
            raise ValueError("invocation result agent_id must match request.")

    def _adapter_failure_result(
        self,
        *,
        request: AgentInvocationRequest,
        user_context_update: ContextUpdateInfo,
        completed_at: datetime,
        error: Exception,
    ) -> AgentInvocationResult:
        return AgentInvocationResult.fail(
            request,
            summary="Agent invocation adapter failed.",
            error_message=str(error),
            completed_at=completed_at,
            output_payload={
                "model_invoked": False,
                "tool_invoked": False,
                "context_update_id": user_context_update.update_id.value,
                "adapter_exception_type": type(error).__name__,
            },
            context_update_ids=(user_context_update.update_id,),
            metadata={
                "source": "single_turn_platform_runtime",
                "adapter_failed": "true",
                "adapter_exception_type": type(error).__name__,
            },
        )

    def _record_agent_invocation(
        self,
        *,
        request: AgentInvocationRequest,
        result: AgentInvocationResult | None,
        event_id: PlatformEventId | None,
        session_id: PlatformRunSessionId | None,
        metadata: Mapping[str, object] | None,
        phase: str,
    ) -> int | None:
        if self.agent_invocation_recorder is None:
            return None
        return self.agent_invocation_recorder.record_agent_invocation_event(
            request=request,
            result=result,
            event_id=event_id,
            occurred_at=(
                result.completed_at if result is not None else request.requested_at
            ),
            session_id=session_id,
            metadata=self._invocation_event_metadata(metadata, phase=phase),
        )

    def _invocation_event_metadata(
        self,
        metadata: Mapping[str, object] | None,
        *,
        phase: str,
    ) -> Mapping[str, object]:
        merged = dict(metadata or {})
        merged["source"] = "single_turn_platform_runtime"
        merged["phase"] = phase
        return merged

    def _record_run_session_lifecycle(
        self,
        *,
        request: AgentInvocationRequest,
        session_id: PlatformRunSessionId | None,
        status: str,
        phase: str,
        occurred_at: datetime,
        metadata: Mapping[str, object] | None,
    ) -> int | None:
        if self.run_session_lifecycle_recorder is None or session_id is None:
            return None
        return self.run_session_lifecycle_recorder.record_run_session_event(
            workspace_id=request.workspace_id,
            session_id=session_id,
            status=status,
            occurred_at=occurred_at,
            agent_id=request.agent_id,
            invocation_id=request.invocation_id,
            correlation_id=request.correlation_id,
            metadata=self._run_session_event_metadata(metadata, phase=phase),
        )

    def _run_session_event_metadata(
        self,
        metadata: Mapping[str, object] | None,
        *,
        phase: str,
    ) -> Mapping[str, object]:
        merged = dict(metadata or {})
        merged["source"] = "single_turn_platform_runtime"
        merged["phase"] = phase
        return merged

    def _record_failed_run_session_lifecycle_after_exception(
        self,
        *,
        request: AgentInvocationRequest,
        session_id: PlatformRunSessionId | None,
        metadata: Mapping[str, object] | None,
        error: Exception,
    ) -> None:
        failure_metadata = dict(metadata or {})
        failure_metadata["failure_phase"] = "single_turn_runtime"
        failure_metadata["exception_type"] = type(error).__name__
        try:
            self._record_run_session_lifecycle(
                request=request,
                session_id=session_id,
                status="failed",
                phase="terminal",
                occurred_at=datetime.now(timezone.utc),
                metadata=failure_metadata,
            )
        except Exception:
            return None


def _run_session_terminal_status(result: AgentInvocationResult) -> str:
    if result.status.value == "failed":
        return "failed"
    if result.status.value == "cancelled":
        return "cancelled"
    return "completed"
