from __future__ import annotations

from typing import Protocol

from agent_os.domain.entities.agent import AgentDefinition
from agent_os.domain.entities.message import MessageEnvelope
from agent_os.domain.entities.orchestration import OrchestrationResult, WorkflowPlan
from agent_os.domain.value_objects.enums import ExecutionMode


class OrchestratorPort(Protocol):
    """Strategy contract for workflow planning and execution."""

    async def build_plan(
        self,
        goal: str,
        available_agents: tuple[AgentDefinition, ...],
        execution_mode: ExecutionMode = ExecutionMode.SEQUENTIAL,
    ) -> WorkflowPlan:
        ...

    async def execute_plan(
        self,
        plan: WorkflowPlan,
        initial_messages: tuple[MessageEnvelope, ...] = (),
    ) -> OrchestrationResult:
        ...
