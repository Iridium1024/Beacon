from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from agent_os.domain.entities.agent import (
    AgentRegistration,
    AgentRegistrationStatus,
)
from agent_os.domain.entities.context import ProjectSharedContext
from agent_os.domain.entities.invocation import AgentInvocationRequest
from agent_os.domain.entities.workspace import ProjectWorkspace, WorkspaceStatus
from agent_os.domain.value_objects.identifiers import (
    AgentInvocationId,
    ContextUpdateId,
    TaskId,
)


@dataclass(frozen=True, slots=True)
class WorkspaceAgentInvocationRequestFactory:
    """Creates workspace-scoped single-turn agent invocation requests."""

    workspace: ProjectWorkspace
    context: ProjectSharedContext
    agent_registration: AgentRegistration

    def __post_init__(self) -> None:
        if self.workspace.status != WorkspaceStatus.ACTIVE:
            raise ValueError("agent invocation requests require an active workspace.")
        if self.context.workspace_id != self.workspace.workspace_id:
            raise ValueError("context must belong to the workspace.")
        if self.agent_registration.workspace_id != self.workspace.workspace_id:
            raise ValueError("agent registration must belong to the workspace.")
        if self.agent_registration.status != AgentRegistrationStatus.ACTIVE:
            raise ValueError("agent invocation requests require an active agent registration.")

    def create_request(
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
        metadata: Mapping[str, object] | None = None,
    ) -> AgentInvocationRequest:
        self._validate_requested_capability(requested_capability)
        request_metadata = dict(metadata or {})
        request_metadata.setdefault("context_id", self.context.context_id.value)
        request_metadata.setdefault(
            "source",
            "workspace_agent_invocation_request_factory",
        )
        return AgentInvocationRequest.create(
            invocation_id=invocation_id,
            workspace_id=self.workspace.workspace_id,
            agent_id=self.agent_registration.agent_id,
            instruction=instruction,
            requested_at=requested_at,
            task_id=task_id,
            requested_capability=requested_capability,
            context_update_ids=tuple(context_update_ids),
            file_references=tuple(file_references),
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            metadata=request_metadata,
        )

    def _validate_requested_capability(self, requested_capability: str | None) -> None:
        if requested_capability is None:
            return
        if not self.agent_registration.has_capability(requested_capability):
            raise ValueError("requested_capability is not registered for this agent.")
