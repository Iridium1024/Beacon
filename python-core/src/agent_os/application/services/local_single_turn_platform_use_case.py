from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from agent_os.application.services.agent_invocation_request_factory import (
    WorkspaceAgentInvocationRequestFactory,
)
from agent_os.application.services.single_turn_platform_runtime import (
    SingleTurnPlatformRunResult,
    SingleTurnPlatformRuntime,
)
from agent_os.domain.entities.context import ProjectSharedContext
from agent_os.domain.value_objects.identifiers import (
    AgentInvocationId,
    ContextUpdateId,
    PlatformEventId,
    PlatformRunSessionId,
    TaskId,
)


@dataclass(slots=True)
class LocalSingleTurnPlatformUseCase:
    """Local facade for one already-loaded single-turn platform invocation."""

    request_factory: WorkspaceAgentInvocationRequestFactory
    runtime: SingleTurnPlatformRuntime

    def run(
        self,
        *,
        instruction: str,
        invocation_id: AgentInvocationId | None = None,
        requested_at: datetime | None = None,
        task_id: TaskId | None = None,
        requested_capability: str | None = None,
        context_update_ids: tuple[ContextUpdateId, ...] = (),
        file_references: tuple[str, ...] = (),
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        request_metadata: Mapping[str, object] | None = None,
        update_id: ContextUpdateId | None = None,
        created_at: datetime | None = None,
        event_id: PlatformEventId | None = None,
        invocation_event_id: PlatformEventId | None = None,
        session_id: PlatformRunSessionId | None = None,
        context_metadata: Mapping[str, object] | None = None,
        event_metadata: Mapping[str, object] | None = None,
        invocation_event_metadata: Mapping[str, object] | None = None,
        context: ProjectSharedContext | None = None,
    ) -> SingleTurnPlatformRunResult:
        runtime_context = context or self.request_factory.context
        if runtime_context.workspace_id != self.request_factory.context.workspace_id:
            raise ValueError("context override must belong to the request workspace.")

        invocation_request = self.request_factory.create_request(
            invocation_id=invocation_id,
            instruction=instruction,
            requested_at=requested_at,
            task_id=task_id,
            requested_capability=requested_capability,
            context_update_ids=tuple(context_update_ids),
            file_references=tuple(file_references),
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            metadata=dict(request_metadata or {}),
        )
        return self.runtime.run_single_turn(
            context=runtime_context,
            invocation_request=invocation_request,
            update_id=update_id,
            created_at=created_at,
            event_id=event_id,
            invocation_event_id=invocation_event_id,
            session_id=session_id,
            context_metadata=dict(context_metadata or {}),
            event_metadata=dict(event_metadata or {}),
            invocation_event_metadata=dict(invocation_event_metadata or {}),
        )
