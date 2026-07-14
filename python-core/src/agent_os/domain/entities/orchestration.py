from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from agent_os.domain.entities.memory import ContextPacket
from agent_os.domain.entities.message import MessageEnvelope
from agent_os.domain.value_objects.enums import ExecutionMode, WorkflowStatus
from agent_os.domain.value_objects.identifiers import AgentId, WorkflowId


@dataclass(frozen=True, slots=True)
class AgentStep:
    """A single orchestration step assigned to an agent."""

    sequence: int
    agent_id: AgentId
    objective: str
    input_contract: str
    output_contract: str
    depends_on: tuple[int, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WorkflowPlan:
    """A provider-neutral execution plan for a multi-agent workflow."""

    workflow_id: WorkflowId
    execution_mode: ExecutionMode
    goal: str
    steps: tuple[AgentStep, ...]
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WorkflowState:
    """The mutable state snapshot emitted by an orchestrator."""

    workflow_id: WorkflowId
    status: WorkflowStatus
    messages: tuple[MessageEnvelope, ...] = ()
    context_packet: ContextPacket | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    """End-state view returned by the orchestration boundary."""

    plan: WorkflowPlan
    state: WorkflowState
    final_response: str | None = None
