from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from agent_os.protocols.communication_protocol import CommunicationMessage


@dataclass(frozen=True, slots=True)
class AgentDescriptor:
    """A transport-safe view of an agent made available to the orchestrator."""

    agent_id: str
    capabilities: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OrchestrationConstraint:
    """A generic constraint the orchestrator must preserve."""

    name: str
    value: object
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    """A single scheduled unit of work."""

    step_id: str
    agent_id: str
    objective: str
    inputs: tuple[CommunicationMessage, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SchedulePlan:
    """An ordered plan produced by the orchestrator."""

    workflow_id: str
    steps: tuple[WorkflowStep, ...]
    constraints: tuple[OrchestrationConstraint, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StepResult:
    """Result contract returned after one scheduled step runs."""

    step_id: str
    outputs: tuple[CommunicationMessage, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


class Orchestrator(ABC):
    """Abstract contract for workflow planning and control."""

    @abstractmethod
    async def schedule(
        self,
        goal: str,
        available_agents: Sequence[AgentDescriptor],
        constraints: Sequence[OrchestrationConstraint] = (),
    ) -> SchedulePlan:
        ...

    @abstractmethod
    async def run_step(self, step: WorkflowStep) -> StepResult:
        ...

    @abstractmethod
    async def enforce_constraints(
        self,
        plan: SchedulePlan,
        constraints: Sequence[OrchestrationConstraint],
    ) -> SchedulePlan:
        ...
