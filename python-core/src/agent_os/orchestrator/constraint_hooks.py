from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field

from agent_os.orchestrator.orchestrator_interface import (
    AgentDescriptor,
    OrchestrationConstraint,
    SchedulePlan,
    StepResult,
    WorkflowStep,
)
from agent_os.orchestrator.runtime_state import ExecutionState


class ConstraintHook(ABC):
    """Hook contract for policy checks around orchestration lifecycle events."""

    @abstractmethod
    async def before_schedule(
        self,
        goal: str,
        available_agents: Sequence[AgentDescriptor],
        constraints: Sequence[OrchestrationConstraint],
    ) -> None:
        ...

    @abstractmethod
    async def after_schedule(self, plan: SchedulePlan) -> None:
        ...

    @abstractmethod
    async def before_step(self, step: WorkflowStep, state: ExecutionState) -> None:
        ...

    @abstractmethod
    async def after_step(self, step: WorkflowStep, result: StepResult, state: ExecutionState) -> None:
        ...

    @abstractmethod
    async def on_complete(self, plan: SchedulePlan, state: ExecutionState) -> None:
        ...


@dataclass(slots=True)
class ConstraintHookRunner:
    """Sequential dispatcher for registered constraint hooks."""

    hooks: tuple[ConstraintHook, ...] = field(default_factory=tuple)

    async def before_schedule(
        self,
        goal: str,
        available_agents: Sequence[AgentDescriptor],
        constraints: Sequence[OrchestrationConstraint],
    ) -> None:
        for hook in self.hooks:
            await hook.before_schedule(goal, available_agents, constraints)

    async def after_schedule(self, plan: SchedulePlan) -> None:
        for hook in self.hooks:
            await hook.after_schedule(plan)

    async def before_step(self, step: WorkflowStep, state: ExecutionState) -> None:
        for hook in self.hooks:
            await hook.before_step(step, state)

    async def after_step(self, step: WorkflowStep, result: StepResult, state: ExecutionState) -> None:
        for hook in self.hooks:
            await hook.after_step(step, result, state)

    async def on_complete(self, plan: SchedulePlan, state: ExecutionState) -> None:
        for hook in self.hooks:
            await hook.on_complete(plan, state)
