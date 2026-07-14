from __future__ import annotations

from dataclasses import dataclass

from agent_os.domain.entities.agent import AgentDefinition
from agent_os.domain.entities.message import MessageEnvelope
from agent_os.domain.entities.orchestration import OrchestrationResult, WorkflowPlan
from agent_os.domain.ports.agent_registry import AgentRegistryPort
from agent_os.domain.ports.model_provider import ModelProviderPort
from agent_os.domain.ports.orchestrator import OrchestratorPort
from agent_os.domain.ports.plugin_runtime import PluginRuntimePort
from agent_os.domain.ports.vector_memory import VectorMemoryPort
from agent_os.domain.value_objects.enums import ExecutionMode


@dataclass(slots=True)
class SequentialOrchestrator(OrchestratorPort):
    """Sequential-first orchestration shell for future concrete implementation."""

    agent_registry: AgentRegistryPort
    model_provider: ModelProviderPort
    plugin_runtime: PluginRuntimePort
    vector_memory: VectorMemoryPort

    async def build_plan(
        self,
        goal: str,
        available_agents: tuple[AgentDefinition, ...],
        execution_mode: ExecutionMode = ExecutionMode.SEQUENTIAL,
    ) -> WorkflowPlan:
        raise NotImplementedError("Sequential planning is intentionally undefined in this scaffold.")

    async def execute_plan(
        self,
        plan: WorkflowPlan,
        initial_messages: tuple[MessageEnvelope, ...] = (),
    ) -> OrchestrationResult:
        raise NotImplementedError("Sequential execution is intentionally undefined in this scaffold.")
