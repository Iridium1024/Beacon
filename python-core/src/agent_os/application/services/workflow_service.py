from __future__ import annotations

from typing import Protocol

from agent_os.application.dto.requests import AgentRegistrationInput, ContextExchangeInput, WorkflowSubmission
from agent_os.domain.entities.memory import ContextPacket
from agent_os.domain.entities.orchestration import OrchestrationResult


class WorkflowService(Protocol):
    """Application boundary used by transport layers and composition roots."""

    async def submit(self, submission: WorkflowSubmission) -> OrchestrationResult:
        ...

    async def register_agent(self, request: AgentRegistrationInput) -> None:
        ...

    async def exchange_context(self, request: ContextExchangeInput) -> ContextPacket:
        ...
