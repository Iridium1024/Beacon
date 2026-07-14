from __future__ import annotations

from dataclasses import dataclass

from agent_os.application.dto.requests import WorkflowSubmission
from agent_os.domain.entities.orchestration import OrchestrationResult
from agent_os.domain.ports.agent_registry import AgentRegistryPort
from agent_os.domain.ports.orchestrator import OrchestratorPort


@dataclass(slots=True)
class OrchestrateWorkflow:
    """Use-case shell for submitting and executing a workflow."""

    agent_registry: AgentRegistryPort
    orchestrator: OrchestratorPort

    async def execute(self, submission: WorkflowSubmission) -> OrchestrationResult:
        raise NotImplementedError("Workflow orchestration is intentionally undefined in this scaffold.")
