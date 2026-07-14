from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agent_os.orchestrator.constraint_hooks import ConstraintHookRunner
from agent_os.orchestrator.orchestrator_interface import SchedulePlan, StepResult, WorkflowStep
from agent_os.orchestrator.runtime_state import ExecutionState
from agent_os.protocols.communication_protocol import CommunicationMessage

if TYPE_CHECKING:
    from agent_os.agents.agent_interface import Agent


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    """Final execution snapshot including shared-context state updates."""

    plan: SchedulePlan
    state: ExecutionState
    outputs: tuple[CommunicationMessage, ...] = ()


class RoutingStrategy(ABC):
    """Extension seam for future dynamic routing."""

    @abstractmethod
    async def route(self, step: WorkflowStep, state: ExecutionState) -> WorkflowStep:
        ...


@dataclass(slots=True)
class SequentialExecutionLoop:
    """Sequential execution loop that preserves a shared blackboard across steps."""

    agents: Mapping[str, Agent]
    hooks: ConstraintHookRunner = field(default_factory=ConstraintHookRunner)
    routing_strategy: RoutingStrategy | None = None
    post_step_handler: Callable[[ExecutionState], Awaitable[bool]] | None = None

    async def run(
        self,
        plan: SchedulePlan,
        state: ExecutionState,
        step_executor: Callable[[WorkflowStep], Awaitable[StepResult]],
    ) -> ExecutionReport:
        outputs: list[CommunicationMessage] = []

        for step in plan.steps:
            routed_step = await self._route_step(step, state)
            await self.hooks.before_step(routed_step, state)
            result = await step_executor(routed_step)
            self._apply_step_result(routed_step, result, state, outputs)
            await self.hooks.after_step(routed_step, result, state)
            should_continue = await self._run_post_step_handler(state)
            if not should_continue:
                break

        await self.hooks.on_complete(plan, state)
        return ExecutionReport(plan=plan, state=state, outputs=tuple(outputs))

    async def _route_step(self, step: WorkflowStep, state: ExecutionState) -> WorkflowStep:
        if self.routing_strategy is None:
            return step
        return await self.routing_strategy.route(step, state)

    def _apply_step_result(
        self,
        step: WorkflowStep,
        result: StepResult,
        state: ExecutionState,
        outputs: list[CommunicationMessage],
    ) -> None:
        state.current_step_id = step.step_id
        state.iteration_count += 1
        state.completed_steps.append(step.step_id)
        state.shared_context.message_history.extend(result.outputs)
        outputs.extend(result.outputs)

        state.shared_context.values["last_step_id"] = step.step_id
        state.shared_context.values["last_agent_id"] = step.agent_id
        # Vector-memory synchronization remains a future concern of the shared context.

        # Placeholder accounting until real provider telemetry is available.
        state.token_usage.register_mock_usage(prompt_tokens=0, completion_tokens=0)

    async def _run_post_step_handler(self, state: ExecutionState) -> bool:
        """Run optional scheduler-owned phase transitions after each discussion step."""

        if self.post_step_handler is None:
            return True
        return await self.post_step_handler(state)
