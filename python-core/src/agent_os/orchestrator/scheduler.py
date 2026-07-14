from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from agent_os.orchestrator.constraint_hooks import ConstraintHook, ConstraintHookRunner
from agent_os.orchestrator.convergence import (
    CheckpointTriggerConfiguration,
    ConvergenceThresholdProfile,
    ConvergenceStatus,
    CoordinationPhase,
    EvaluationStage,
    FrozenDiscussionResult,
    HeartbeatAgentJudgment,
    HeartbeatAggregateResult,
    HeartbeatCheckpointAssessment,
    HeartbeatCheckpointDefinition,
    HeartbeatEvidenceBundle,
    HeartbeatCheckpointInput,
    HeartbeatResourceStatus,
    HeartbeatResolution,
    HeartbeatVoteChoice,
    RejectionDeficiencyCategory,
    Trigger,
    TriggerEvaluationResult,
    TriggerScope,
    TriggerType,
    VotingAssessment,
    VotingMode,
)
from agent_os.orchestrator.execution_loop import ExecutionReport, RoutingStrategy, SequentialExecutionLoop
from agent_os.orchestrator.heartbeat_aggregate_artifact_builder import (
    build_heartbeat_aggregate_artifact,
    build_heartbeat_dissent_summary,
)
from agent_os.orchestrator.heartbeat_candidate_presentation import (
    build_heartbeat_candidate_presentation,
)
from agent_os.orchestrator.heartbeat_candidate_snapshot import (
    build_heartbeat_candidate_snapshot,
)
from agent_os.orchestrator.heartbeat_convergence_profile import (
    build_heartbeat_convergence_profile,
)
from agent_os.orchestrator.heartbeat_grading import (
    canonicalize_severity_label,
    derive_heartbeat_grading,
    summarize_heartbeat_grading,
)
from agent_os.orchestrator.heartbeat_outcome_snapshot import (
    build_heartbeat_outcome_snapshot,
)
from agent_os.orchestrator.heartbeat_terminal_payload import (
    build_heartbeat_terminal_payload,
)
from agent_os.orchestrator.orchestrator_interface import (
    AgentDescriptor,
    OrchestrationConstraint,
    Orchestrator,
    SchedulePlan,
    StepResult,
    WorkflowStep,
)
from agent_os.orchestrator.runtime_state import ExecutionState
from agent_os.protocols.communication_protocol import CommunicationMessage
from agent_os.protocols.final_answer_candidate import FinalAnswerCandidateStatus

if TYPE_CHECKING:
    from agent_os.agents.agent_interface import Agent


@dataclass(frozen=True, slots=True)
class SchedulerOptions:
    """Runtime options for the orchestrator skeleton."""

    enable_parallel_execution: bool = False
    enable_dynamic_routing: bool = False
    thresholds: ConvergenceThresholdProfile = field(default_factory=ConvergenceThresholdProfile)
    heartbeat_checkpoint: HeartbeatCheckpointDefinition = field(
        default_factory=HeartbeatCheckpointDefinition
    )
    heartbeat_context_ref_limit: int = 5


@dataclass(slots=True)
class Scheduler(Orchestrator):
    """Minimal orchestration skeleton for sequential multi-agent execution."""

    agents: Mapping[str, Agent]
    hooks: Sequence[ConstraintHook] = ()
    routing_strategy: RoutingStrategy | None = None
    options: SchedulerOptions = field(default_factory=SchedulerOptions)
    _active_state: ExecutionState | None = field(default=None, init=False, repr=False)

    async def schedule(
        self,
        goal: str,
        available_agents: Sequence[AgentDescriptor],
        constraints: Sequence[OrchestrationConstraint] = (),
    ) -> SchedulePlan:
        hook_runner = ConstraintHookRunner(tuple(self.hooks))
        await hook_runner.before_schedule(goal, available_agents, constraints)

        steps = tuple(
            WorkflowStep(
                step_id=f"step-{index}",
                agent_id=agent.agent_id,
                objective=goal,
            )
            for index, agent in enumerate(available_agents, start=1)
        )
        plan = SchedulePlan(
            workflow_id="workflow-placeholder",
            steps=steps,
            constraints=tuple(constraints),
            metadata={"execution_mode": "sequential"},
        )

        constrained_plan = await self.enforce_constraints(plan, constraints)
        await hook_runner.after_schedule(constrained_plan)
        return constrained_plan

    async def run_step(self, step: WorkflowStep) -> StepResult:
        if self._active_state is None:
            raise RuntimeError("Execution state is not initialized. Call execute() before run_step().")

        agent = self.agents[step.agent_id]
        inbound_message = self._build_step_update(step, self._active_state)
        perception = await agent.perceive(self._active_state.shared_context, inbound_message)
        thought = await agent.think(perception)
        action = await agent.act(thought)
        summary = await agent.summarize(self._active_state.shared_context)
        # Discussion emits a canonical semantic message and also derives a
        # separate final-answer candidate for later checkpoint evaluation.
        candidate_metadata = {
            **dict(summary.metadata),
            "step_id": step.step_id,
            "action_type": action.action_type,
            "message_type": "final_answer_candidate",
        }
        candidate = self._active_state.publish_candidate_from_discussion(
            summary_text=summary.summary,
            source_agent_id=step.agent_id,
            source_round=self._active_state.iteration_count + 1,
            metadata=candidate_metadata,
        )

        outbound_message = CommunicationMessage(
            id=f"{step.step_id}:summary",
            sender=step.agent_id,
            summary_text=summary.summary,
            embedding_vector=None,
            metadata={
                "action_type": action.action_type,
                "message_type": "agent.summary",
                "final_answer_candidate_id": candidate.candidate_id,
                "shared_context_update": True,
            },
        )
        return StepResult(
            step_id=step.step_id,
            outputs=(outbound_message,),
            metadata={"status": "placeholder"},
        )

    async def enforce_constraints(
        self,
        plan: SchedulePlan,
        constraints: Sequence[OrchestrationConstraint],
    ) -> SchedulePlan:
        return SchedulePlan(
            workflow_id=plan.workflow_id,
            steps=plan.steps,
            constraints=tuple(constraints),
            metadata=dict(plan.metadata),
        )

    async def execute(
        self,
        goal: str,
        available_agents: Sequence[AgentDescriptor],
        initial_messages: Sequence[CommunicationMessage] = (),
        constraints: Sequence[OrchestrationConstraint] = (),
    ) -> ExecutionReport:
        plan = await self.schedule(goal, available_agents, constraints)
        state = ExecutionState(
            workflow_id=plan.workflow_id,
            goal=goal,
            participant_agent_ids=tuple(agent.agent_id for agent in available_agents),
        )
        state.shared_context.message_history.extend(initial_messages)

        self._active_state = state
        loop = SequentialExecutionLoop(
            agents=self.agents,
            hooks=ConstraintHookRunner(tuple(self.hooks)),
            routing_strategy=self.routing_strategy if self.options.enable_dynamic_routing else None,
            post_step_handler=self._handle_post_step_transitions,
        )

        try:
            if self.options.enable_parallel_execution:
                return await self._execute_parallel(plan, state)
            return await loop.run(plan=plan, state=state, step_executor=self.run_step)
        finally:
            self._active_state = None

    async def _execute_parallel(self, plan: SchedulePlan, state: ExecutionState) -> ExecutionReport:
        raise NotImplementedError("Parallel execution is reserved for a future orchestrator implementation.")

    async def evaluate_checkpoint_triggers(self, state: ExecutionState) -> TriggerEvaluationResult:
        """Evaluate configured checkpoint triggers with OR semantics."""

        configuration = self.options.heartbeat_checkpoint.entry_triggers
        fired_trigger_ids = tuple(
            trigger.id
            for trigger in self._iter_configured_triggers(configuration)
            if self._trigger_fires(trigger, state)
        )
        return TriggerEvaluationResult(
            fires_checkpoint=bool(fired_trigger_ids),
            aggregation_mode=configuration.semantics.aggregation_mode,
            target_phase=configuration.semantics.enter_phase_on_fire,
            fired_trigger_ids=fired_trigger_ids,
            metadata={
                "iteration_count": state.iteration_count,
                "current_phase": state.current_phase.value,
            },
        )

    async def evaluate_heartbeat_checkpoint(
        self,
        checkpoint_input: HeartbeatCheckpointInput,
        state: ExecutionState,
        *,
        evidence_bundle: HeartbeatEvidenceBundle | None = None,
    ) -> HeartbeatCheckpointAssessment:
        """Run the minimal explicit heartbeat judgment chain.

        The chain is:
        frozen candidate -> canonical checkpoint input -> structured evidence ->
        per-agent judgment -> dispatcher aggregate -> continue/converged phase outcome.
        """

        evidence_bundle = state.resolve_heartbeat_evidence_bundle(
            checkpoint_input,
            evidence_bundle=evidence_bundle,
        )
        participant_ids = self._resolve_heartbeat_participant_ids(state)
        if not participant_ids:
            return self._build_empty_participant_assessment(checkpoint_input, evidence_bundle)

        # Heartbeat self-checks are currently executed serially. Parallel
        # heartbeat remains intentionally reserved for a future runtime.
        judgments = tuple(
            [
                await self.generate_self_check_judgment(
                    agent_id,
                    checkpoint_input,
                    evidence_bundle,
                    state,
                )
                for agent_id in participant_ids
            ]
        )
        aggregate = self.aggregate_heartbeat_judgments(
            checkpoint_input,
            judgments,
            evidence_bundle=evidence_bundle,
        )
        threshold_reached = aggregate.recommended_outcome == ConvergenceStatus.CONVERGED
        resolution = (
            HeartbeatResolution.STOP_AND_OUTPUT
            if threshold_reached
            else HeartbeatResolution.RESUME_DISCUSSION
        )
        frozen_result = FrozenDiscussionResult(
            discussion_message_ids=checkpoint_input.relevant_context_refs,
            result_summary_text=checkpoint_input.frozen_candidate_summary,
            original_task_goal=checkpoint_input.original_goal,
            metadata={
                "checkpoint_id": checkpoint_input.checkpoint_id,
                "candidate_id": checkpoint_input.frozen_candidate_id,
                "source_round": checkpoint_input.source_round,
            },
        )
        return HeartbeatCheckpointAssessment(
            checkpoint_input=checkpoint_input,
            evidence_bundle=evidence_bundle,
            judgments=judgments,
            aggregate=aggregate,
            approval_threshold_reached=threshold_reached,
            resolution=resolution,
            frozen_result=frozen_result,
            metadata={
                "checkpoint_id": checkpoint_input.checkpoint_id,
                "judgment_count": len(judgments),
            },
        )

    async def generate_self_check_judgment(
        self,
        agent_id: str,
        checkpoint_input: HeartbeatCheckpointInput,
        evidence_bundle: HeartbeatEvidenceBundle,
        state: ExecutionState,
    ) -> HeartbeatAgentJudgment:
        """Generate one canonical heartbeat judgment for a participating agent."""

        self._ensure_heartbeat_judgment_phase(state)
        agent = self.agents[agent_id]
        try:
            raw_result = await agent.self_check(checkpoint_input, evidence_bundle)
            return self._normalize_self_check_judgment(
                raw_result=raw_result,
                agent_id=agent_id,
                checkpoint_input=checkpoint_input,
                evidence_bundle=evidence_bundle,
            )
        except Exception as exc:
            return self._build_invalid_self_check_judgment(
                agent_id=agent_id,
                checkpoint_input=checkpoint_input,
                evidence_bundle=evidence_bundle,
                error_message=str(exc),
            )

    def aggregate_heartbeat_judgments(
        self,
        checkpoint_input: HeartbeatCheckpointInput,
        judgments: Sequence[HeartbeatAgentJudgment],
        *,
        evidence_bundle: HeartbeatEvidenceBundle | None = None,
    ) -> HeartbeatAggregateResult:
        """Aggregate explicit heartbeat judgments without reinterpretation."""

        self._validate_aggregate_input(checkpoint_input, judgments)
        judgments = self._stabilize_aggregate_judgments(
            checkpoint_input=checkpoint_input,
            judgments=judgments,
            evidence_bundle=evidence_bundle,
        )

        total_judgments = len(judgments)
        approval_count = sum(
            1 for judgment in judgments if judgment.decision == HeartbeatVoteChoice.APPROVE
        )
        rejection_count = sum(
            1 for judgment in judgments if judgment.decision == HeartbeatVoteChoice.REJECT
        )
        approval_ratio = approval_count / total_judgments if total_judgments else 0.0
        rejection_ratio = rejection_count / total_judgments if total_judgments else 0.0
        threshold_met = self._heartbeat_threshold_met(
            approval_count=approval_count,
            approval_ratio=approval_ratio,
        )
        recommended_outcome = (
            ConvergenceStatus.CONVERGED if threshold_met else ConvergenceStatus.CONTINUE
        )
        aggregate_result_id = self._build_aggregate_result_id(checkpoint_input)
        aggregate_artifact = build_heartbeat_aggregate_artifact(
            aggregate_result_id=aggregate_result_id,
            checkpoint_input=checkpoint_input,
            evidence_bundle=evidence_bundle,
            judgments=judgments,
            final_decision=recommended_outcome,
        )
        grading_summary = summarize_heartbeat_grading(judgments)
        dissent_summary = build_heartbeat_dissent_summary(aggregate_artifact)
        dominant_categories = self._dominant_deficiency_categories(judgments)
        voting = VotingAssessment(
            stage=EvaluationStage.HEARTBEAT_CHECKPOINT,
            mode=self.options.thresholds.voting.mode,
            stage_permitted=True,
            threshold_met=threshold_met,
            approval_count=approval_count,
            support_ratio=approval_ratio,
            support_count=approval_count,
            approval_ratio=approval_ratio,
            rejection_count=rejection_count,
            rejection_ratio=rejection_ratio,
            vote_distribution={
                HeartbeatVoteChoice.APPROVE.value: approval_count,
                HeartbeatVoteChoice.REJECT.value: rejection_count,
            },
            metadata={"checkpoint_id": checkpoint_input.checkpoint_id},
        )
        preliminary_result = HeartbeatAggregateResult(
            aggregate_result_id=aggregate_result_id,
            checkpoint_id=checkpoint_input.checkpoint_id,
            total_judgments=total_judgments,
            approval_count=approval_count,
            rejection_count=rejection_count,
            approval_ratio=approval_ratio,
            rejection_ratio=rejection_ratio,
            dissent_summary=dissent_summary,
            dominant_deficiency_categories=dominant_categories,
            recommended_outcome=recommended_outcome,
            highest_rejection_severity=grading_summary.highest_rejection_severity,
            blocker_count=grading_summary.blocker_count,
            blocker_roles=grading_summary.blocker_roles,
            severity_histogram=grading_summary.severity_histogram,
            voting=voting,
            aggregate_artifact=aggregate_artifact,
            metadata={
                "aggregate_result_id": aggregate_result_id,
                "threshold_met": threshold_met,
                "candidate_id": checkpoint_input.frozen_candidate_id,
                "evidence_bundle_id": aggregate_artifact.evidence_bundle_id,
            },
        )
        return self._attach_heartbeat_consumption_contracts(
            checkpoint_input=checkpoint_input,
            aggregate_result=preliminary_result,
        )

    def _attach_heartbeat_consumption_contracts(
        self,
        *,
        checkpoint_input: HeartbeatCheckpointInput,
        aggregate_result: HeartbeatAggregateResult,
    ) -> HeartbeatAggregateResult:
        """Attach derived consumption contracts without altering aggregate semantics."""

        if aggregate_result.aggregate_artifact is None:
            raise ValueError(
                "Heartbeat consumption contract attachment requires aggregate_artifact."
            )
        candidate_snapshot = build_heartbeat_candidate_snapshot(checkpoint_input)
        convergence_profile = build_heartbeat_convergence_profile(aggregate_result)
        outcome_snapshot = build_heartbeat_outcome_snapshot(
            aggregate_result,
            convergence_profile=convergence_profile,
            candidate_snapshot=candidate_snapshot,
        )
        aggregate_artifact = replace(
            aggregate_result.aggregate_artifact,
            candidate_snapshot=candidate_snapshot,
            convergence_profile=convergence_profile,
            outcome_snapshot=outcome_snapshot,
        )
        attached_result = replace(
            aggregate_result,
            aggregate_artifact=aggregate_artifact,
            candidate_snapshot=candidate_snapshot,
            convergence_profile=convergence_profile,
            outcome_snapshot=outcome_snapshot,
        )
        candidate_presentation = build_heartbeat_candidate_presentation(attached_result)
        aggregate_artifact = replace(
            attached_result.aggregate_artifact,
            candidate_presentation=candidate_presentation,
        )
        attached_result = replace(
            attached_result,
            aggregate_artifact=aggregate_artifact,
            candidate_presentation=candidate_presentation,
        )
        terminal_payload = build_heartbeat_terminal_payload(attached_result)
        aggregate_artifact = replace(
            attached_result.aggregate_artifact,
            terminal_payload=terminal_payload,
        )
        return replace(
            attached_result,
            aggregate_artifact=aggregate_artifact,
            terminal_payload=terminal_payload,
        )

    def _build_step_update(self, step: WorkflowStep, state: ExecutionState) -> CommunicationMessage:
        return CommunicationMessage(
            id=f"{step.step_id}:input",
            sender="orchestrator",
            summary_text=step.objective,
            embedding_vector=None,
            metadata={
                "message_type": "workflow.step",
                "workflow_id": state.workflow_id,
                "iteration_count": state.iteration_count,
                "selected_agent_id": step.agent_id,
                "shared_context_update": True,
            },
        )

    async def _handle_post_step_transitions(self, state: ExecutionState) -> bool:
        """Run minimal discussion -> heartbeat -> discussion/terminal transitions."""

        if state.is_terminal:
            return False
        if state.current_phase != CoordinationPhase.DISCUSSION_ROUND:
            return not state.is_terminal

        trigger_result = await self.evaluate_checkpoint_triggers(state)
        if not trigger_result.fires_checkpoint:
            return True

        state.enter_heartbeat_checkpoint()
        state.shared_context.values["last_checkpoint_trigger_ids"] = trigger_result.fired_trigger_ids
        checkpoint_input = state.create_heartbeat_checkpoint_input(
            trigger_ids=trigger_result.fired_trigger_ids,
            relevant_context_limit=self.options.heartbeat_context_ref_limit,
            metadata={"target_phase": trigger_result.target_phase.value},
        )
        assessment = await self.evaluate_heartbeat_checkpoint(checkpoint_input, state)
        return self._apply_heartbeat_assessment(state, assessment)

    def _apply_heartbeat_assessment(
        self,
        state: ExecutionState,
        assessment: HeartbeatCheckpointAssessment,
    ) -> bool:
        """Apply the explicit heartbeat outcome without allowing new proposals."""

        state.shared_context.values["last_heartbeat_checkpoint_id"] = (
            assessment.checkpoint_input.checkpoint_id
        )
        if assessment.evidence_bundle is not None:
            state.shared_context.values["last_heartbeat_evidence_bundle"] = (
                assessment.evidence_bundle
            )
            state.shared_context.values["last_heartbeat_evidence_bundle_id"] = (
                assessment.evidence_bundle.evidence_bundle_id
            )
        state.shared_context.values["last_heartbeat_judgment_ids"] = tuple(
            judgment.judgment_id for judgment in assessment.judgments
        )
        state.shared_context.values["last_heartbeat_resolution"] = assessment.resolution.value
        if assessment.aggregate is not None:
            state.shared_context.values["last_heartbeat_aggregate_result_id"] = (
                assessment.aggregate.aggregate_result_id
            )
            state.shared_context.values["last_heartbeat_threshold_met"] = (
                assessment.aggregate.voting.threshold_met
                if assessment.aggregate.voting is not None
                else None
            )
            state.shared_context.values["last_heartbeat_recommended_outcome"] = (
                assessment.aggregate.recommended_outcome.value
            )
            state.shared_context.values["last_heartbeat_dissent_summary"] = (
                assessment.aggregate.dissent_summary
            )
            state.shared_context.values["last_heartbeat_dominant_deficiency_categories"] = tuple(
                category.value for category in assessment.aggregate.dominant_deficiency_categories
            )
            state.shared_context.values["last_heartbeat_aggregate_artifact"] = (
                assessment.aggregate.aggregate_artifact
            )

        if assessment.resolution == HeartbeatResolution.STOP_AND_OUTPUT:
            state.mark_terminal(
                ConvergenceStatus.CONVERGED,
                reason="heartbeat checkpoint accepted the frozen final-answer candidate",
            )
            return False

        if assessment.resolution == HeartbeatResolution.DEFER_TO_EXISTING_FALLBACK:
            state.mark_terminal(
                ConvergenceStatus.FORCED_STOP,
                reason="heartbeat checkpoint deferred to an existing fallback path",
            )
            return False

        state.resume_discussion_round()
        return True

    def _iter_configured_triggers(
        self,
        configuration: CheckpointTriggerConfiguration,
    ) -> tuple[Trigger, ...]:
        """Flatten layered trigger configuration in the declared resolution order."""

        layers_by_scope = {
            TriggerScope.GLOBAL_DEFAULT: configuration.global_defaults,
            TriggerScope.PROJECT_OVERRIDE: configuration.project_overrides,
            TriggerScope.RUNTIME_ADJUSTMENT: configuration.runtime_adjustments,
        }
        triggers: list[Trigger] = []
        for scope in configuration.resolution_order:
            layer = layers_by_scope[scope]
            triggers.extend(layer.triggers)
        return tuple(triggers)

    def _trigger_fires(self, trigger: Trigger, state: ExecutionState) -> bool:
        """Evaluate the trigger types currently wired into the minimal runtime."""

        if not trigger.enabled:
            return False
        if trigger.trigger_type == TriggerType.ROUND_BASED:
            return self._round_trigger_fires(trigger, state)
        return False

    def _round_trigger_fires(self, trigger: Trigger, state: ExecutionState) -> bool:
        """Evaluate a user-configured round-based heartbeat trigger."""

        interval_rounds = self._coerce_positive_int(trigger.parameters.get("interval_rounds"))
        if interval_rounds is None:
            return False

        start_round = self._coerce_positive_int(trigger.parameters.get("start_round"))
        effective_start_round = start_round if start_round is not None else interval_rounds
        if state.iteration_count < effective_start_round:
            return False
        return (state.iteration_count - effective_start_round) % interval_rounds == 0

    def _coerce_positive_int(self, value: object) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value > 0 else None
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                parsed = int(stripped)
            except ValueError:
                return None
            return parsed if parsed > 0 else None
        return None

    def _resolve_heartbeat_participant_ids(self, state: ExecutionState) -> tuple[str, ...]:
        participant_ids = state.eligible_heartbeat_participant_ids()
        if not participant_ids and not state.participant_agent_ids:
            participant_ids = tuple(self.agents.keys())
        return tuple(
            agent_id
            for agent_id in participant_ids
            if agent_id in self.agents and self.agents[agent_id].supports_role_specific_self_check
        )

    def _ensure_heartbeat_judgment_phase(self, state: ExecutionState) -> None:
        if state.current_phase != CoordinationPhase.HEARTBEAT_CHECKPOINT:
            raise RuntimeError(
                "Heartbeat judgments may only be generated during heartbeat_checkpoint."
            )
        current_candidate = state.get_current_candidate()
        if current_candidate is None or current_candidate.status != FinalAnswerCandidateStatus.FROZEN:
            raise RuntimeError(
                "Heartbeat judgments require the current final-answer candidate to remain frozen."
            )

    def _build_invalid_self_check_judgment(
        self,
        *,
        agent_id: str,
        checkpoint_input: HeartbeatCheckpointInput,
        evidence_bundle: HeartbeatEvidenceBundle,
        error_message: str,
    ) -> HeartbeatAgentJudgment:
        """Standardize invalid heartbeat outputs into explicit reject judgments."""

        normalized_error = error_message.strip() or "invalid self-check output"
        return HeartbeatAgentJudgment.create(
            checkpoint_id=checkpoint_input.checkpoint_id,
            agent_id=agent_id,
            candidate_id=checkpoint_input.frozen_candidate_id,
            evidence_bundle_id=evidence_bundle.evidence_bundle_id,
            decision=HeartbeatVoteChoice.REJECT,
            rationale_text=f"Invalid self-check output: {normalized_error}.",
            deficiency_category=RejectionDeficiencyCategory.OTHER,
            used_signal_keys=(),
            resource_status=HeartbeatResourceStatus.UNKNOWN,
            metadata={
                "standardized_invalid_output": True,
                "validation_error": normalized_error,
            },
        )

    def _build_empty_participant_assessment(
        self,
        checkpoint_input: HeartbeatCheckpointInput,
        evidence_bundle: HeartbeatEvidenceBundle,
    ) -> HeartbeatCheckpointAssessment:
        """Return the minimal compatible heartbeat outcome when no agents are eligible."""

        aggregate_result_id = self._build_aggregate_result_id(checkpoint_input)
        aggregate = HeartbeatAggregateResult(
            aggregate_result_id=aggregate_result_id,
            checkpoint_id=checkpoint_input.checkpoint_id,
            total_judgments=0,
            approval_count=0,
            rejection_count=0,
            approval_ratio=0.0,
            rejection_ratio=0.0,
            dissent_summary=None,
            dominant_deficiency_categories=(),
            recommended_outcome=ConvergenceStatus.CONTINUE,
            highest_rejection_severity=None,
            blocker_count=0,
            blocker_roles=(),
            severity_histogram={},
            voting=VotingAssessment(
                stage=EvaluationStage.HEARTBEAT_CHECKPOINT,
                mode=self.options.thresholds.voting.mode,
                stage_permitted=True,
                threshold_met=False,
                approval_count=0,
                support_ratio=0.0,
                support_count=0,
                approval_ratio=0.0,
                rejection_count=0,
                rejection_ratio=0.0,
                vote_distribution={
                    HeartbeatVoteChoice.APPROVE.value: 0,
                    HeartbeatVoteChoice.REJECT.value: 0,
                },
                metadata={
                    "checkpoint_id": checkpoint_input.checkpoint_id,
                    "evidence_bundle_id": evidence_bundle.evidence_bundle_id,
                    "no_eligible_participants": True,
                },
            ),
            aggregate_artifact=build_heartbeat_aggregate_artifact(
                aggregate_result_id=aggregate_result_id,
                checkpoint_input=checkpoint_input,
                evidence_bundle=evidence_bundle,
                judgments=(),
                final_decision=ConvergenceStatus.CONTINUE,
            ),
            metadata={
                "aggregate_result_id": aggregate_result_id,
                "no_eligible_participants": True,
                "evidence_bundle_id": evidence_bundle.evidence_bundle_id,
            },
        )
        aggregate = self._attach_heartbeat_consumption_contracts(
            checkpoint_input=checkpoint_input,
            aggregate_result=aggregate,
        )
        frozen_result = FrozenDiscussionResult(
            discussion_message_ids=checkpoint_input.relevant_context_refs,
            result_summary_text=checkpoint_input.frozen_candidate_summary,
            original_task_goal=checkpoint_input.original_goal,
            metadata={
                "checkpoint_id": checkpoint_input.checkpoint_id,
                "candidate_id": checkpoint_input.frozen_candidate_id,
                "source_round": checkpoint_input.source_round,
            },
        )
        return HeartbeatCheckpointAssessment(
            checkpoint_input=checkpoint_input,
            evidence_bundle=evidence_bundle,
            judgments=(),
            aggregate=aggregate,
            approval_threshold_reached=False,
            resolution=HeartbeatResolution.RESUME_DISCUSSION,
            frozen_result=frozen_result,
            metadata={
                "checkpoint_id": checkpoint_input.checkpoint_id,
                "judgment_count": 0,
                "evidence_bundle_id": evidence_bundle.evidence_bundle_id,
                "no_eligible_participants": True,
            },
        )

    def _normalize_self_check_judgment(
        self,
        *,
        raw_result: object,
        agent_id: str,
        checkpoint_input: HeartbeatCheckpointInput,
        evidence_bundle: HeartbeatEvidenceBundle,
    ) -> HeartbeatAgentJudgment:
        if isinstance(raw_result, HeartbeatAgentJudgment):
            if raw_result.agent_id != agent_id:
                raise ValueError("Heartbeat judgment agent_id does not match the requested agent.")
            if raw_result.checkpoint_id != checkpoint_input.checkpoint_id:
                raise ValueError("Heartbeat judgment checkpoint_id does not match the active checkpoint.")
            if raw_result.candidate_id != checkpoint_input.frozen_candidate_id:
                raise ValueError("Heartbeat judgment candidate_id does not match the frozen candidate.")
            if (
                raw_result.evidence_bundle_id is not None
                and raw_result.evidence_bundle_id != evidence_bundle.evidence_bundle_id
            ):
                raise ValueError(
                    "Heartbeat judgment evidence_bundle_id does not match the active evidence bundle."
                )
            if self._contains_proposal_bearing_content(raw_result.rationale_text):
                raise ValueError(
                    "Heartbeat judgment rationale contains proposal-bearing content."
                )
            used_signal_keys = raw_result.used_signal_keys or self._coerce_signal_keys(
                self._coalesce_legacy_metadata_value(
                    raw_result.metadata,
                    "used_signal_keys",
                )
            )
            source_anchors = raw_result.source_anchors or self._coalesce_legacy_metadata_value(
                raw_result.metadata,
                "source_anchors",
            )
            severity = raw_result.severity
            if severity is None:
                severity = self._coalesce_legacy_metadata_value(
                    raw_result.metadata,
                    "severity",
                    "deficiency_severity",
                )
            blocker = raw_result.blocker
            if blocker is None:
                blocker = self._coalesce_legacy_metadata_value(
                    raw_result.metadata,
                    "blocker",
                    "is_blocker",
                    "blocking",
                    "is_blocking",
                )
            resolved_severity, resolved_blocker = self._resolve_grading_fields(
                decision=raw_result.decision,
                deficiency_category=raw_result.deficiency_category,
                severity=severity,
                blocker=blocker,
                used_signal_keys=used_signal_keys,
                source_anchors=source_anchors,
                checkpoint_input=checkpoint_input,
                evidence_bundle=evidence_bundle,
                agent_role=self._resolve_agent_role(agent_id, raw_result.metadata),
            )
            return HeartbeatAgentJudgment.create(
                judgment_id=raw_result.judgment_id,
                checkpoint_id=raw_result.checkpoint_id,
                agent_id=raw_result.agent_id,
                candidate_id=raw_result.candidate_id,
                evidence_bundle_id=raw_result.evidence_bundle_id or evidence_bundle.evidence_bundle_id,
                decision=raw_result.decision,
                rationale_text=raw_result.rationale_text,
                deficiency_category=raw_result.deficiency_category,
                severity=resolved_severity,
                blocker=resolved_blocker,
                used_signal_keys=used_signal_keys,
                source_anchors=source_anchors,
                resource_status=raw_result.resource_status,
                metadata=raw_result.metadata,
                proposed_new_solution_content=raw_result.proposed_new_solution_content,
            )

        if not isinstance(raw_result, Mapping):
            raise TypeError("Heartbeat self-check output must be a judgment object or mapping.")

        raw_agent_id = raw_result.get("agent_id")
        if raw_agent_id is not None and raw_agent_id != agent_id:
            raise ValueError("Heartbeat self-check output agent_id does not match the requested agent.")
        raw_checkpoint_id = raw_result.get("checkpoint_id")
        if raw_checkpoint_id is not None and raw_checkpoint_id != checkpoint_input.checkpoint_id:
            raise ValueError(
                "Heartbeat self-check output checkpoint_id does not match the active checkpoint."
            )
        raw_candidate_id = raw_result.get("candidate_id")
        if raw_candidate_id is not None and raw_candidate_id != checkpoint_input.frozen_candidate_id:
            raise ValueError(
                "Heartbeat self-check output candidate_id does not match the frozen candidate."
            )
        raw_evidence_bundle_id = raw_result.get("evidence_bundle_id")
        if (
            raw_evidence_bundle_id is not None
            and raw_evidence_bundle_id != evidence_bundle.evidence_bundle_id
        ):
            raise ValueError(
                "Heartbeat self-check output evidence_bundle_id does not match the active bundle."
            )

        decision = self._coerce_vote_choice(raw_result.get("decision", raw_result.get("vote")))
        rationale_text = self._coerce_rationale_text(
            raw_result.get("rationale_text", raw_result.get("rationale"))
        )
        if self._contains_proposal_bearing_content(rationale_text):
            raise ValueError("Heartbeat judgment rationale contains proposal-bearing content.")
        deficiency_category = self._coerce_deficiency_category(
            raw_result.get(
                "deficiency_category",
                raw_result.get("rejection_deficiency_category"),
            ),
            decision,
        )
        resource_status = self._coerce_resource_status(raw_result.get("resource_status"))
        proposed_new_solution_content = bool(
            raw_result.get(
                "proposed_new_solution_content",
                raw_result.get("contains_new_solution_proposal", False),
            )
        )
        metadata = raw_result.get("metadata")
        if metadata is not None and not isinstance(metadata, Mapping):
            raise TypeError("Heartbeat self-check metadata must be a mapping when provided.")
        normalized_metadata = dict(metadata or {})
        used_signal_keys = self._coerce_signal_keys(
            self._coalesce_mapping_value(
                raw_result,
                normalized_metadata,
                "used_signal_keys",
            )
        )
        severity = self._coalesce_mapping_value(
            raw_result,
            normalized_metadata,
            "severity",
            "deficiency_severity",
        )
        blocker = self._coalesce_mapping_value(
            raw_result,
            normalized_metadata,
            "blocker",
            "is_blocker",
            "blocking",
            "is_blocking",
        )
        source_anchors = self._coalesce_mapping_value(
            raw_result,
            normalized_metadata,
            "source_anchors",
        )
        resolved_severity, resolved_blocker = self._resolve_grading_fields(
            decision=decision,
            deficiency_category=deficiency_category,
            severity=severity,
            blocker=blocker,
            used_signal_keys=used_signal_keys,
            source_anchors=source_anchors,
            checkpoint_input=checkpoint_input,
            evidence_bundle=evidence_bundle,
            agent_role=self._resolve_agent_role(agent_id, normalized_metadata),
        )

        return HeartbeatAgentJudgment.create(
            judgment_id=self._coerce_optional_string(raw_result.get("judgment_id")),
            checkpoint_id=checkpoint_input.checkpoint_id,
            agent_id=agent_id,
            candidate_id=checkpoint_input.frozen_candidate_id,
            evidence_bundle_id=evidence_bundle.evidence_bundle_id,
            decision=decision,
            rationale_text=rationale_text,
            deficiency_category=deficiency_category,
            severity=resolved_severity,
            blocker=resolved_blocker,
            used_signal_keys=used_signal_keys,
            source_anchors=source_anchors,
            resource_status=resource_status,
            metadata=normalized_metadata,
            proposed_new_solution_content=proposed_new_solution_content,
        )

    def _validate_aggregate_input(
        self,
        checkpoint_input: HeartbeatCheckpointInput,
        judgments: Sequence[HeartbeatAgentJudgment],
    ) -> None:
        for judgment in judgments:
            if judgment.checkpoint_id != checkpoint_input.checkpoint_id:
                raise ValueError("Dispatcher received a judgment for a different checkpoint.")
            if judgment.candidate_id != checkpoint_input.frozen_candidate_id:
                raise ValueError("Dispatcher received a judgment for a different candidate.")
            if not judgment.evidence_bundle_id:
                raise ValueError("Dispatcher received a judgment without evidence_bundle_id.")
            if not judgment.rationale_text.strip():
                raise ValueError("Dispatcher received a judgment without rationale_text.")
            if (
                judgment.decision == HeartbeatVoteChoice.REJECT
                and judgment.deficiency_category is None
            ):
                raise ValueError("Reject judgments must provide a deficiency category.")

    def _heartbeat_threshold_met(self, *, approval_count: int, approval_ratio: float) -> bool:
        voting_thresholds = self.options.thresholds.voting
        if approval_count <= 0:
            return False
        if approval_ratio < voting_thresholds.support_ratio_threshold:
            return False
        if (
            voting_thresholds.minimum_support_count is not None
            and approval_count < voting_thresholds.minimum_support_count
        ):
            return False
        return True

    def _build_aggregate_result_id(self, checkpoint_input: HeartbeatCheckpointInput) -> str:
        return f"{checkpoint_input.checkpoint_id}:aggregate"

    def _dominant_deficiency_categories(
        self,
        judgments: Sequence[HeartbeatAgentJudgment],
    ) -> tuple[RejectionDeficiencyCategory, ...]:
        counter: Counter[RejectionDeficiencyCategory] = Counter(
            judgment.deficiency_category
            for judgment in judgments
            if (
                judgment.decision == HeartbeatVoteChoice.REJECT
                and judgment.deficiency_category is not None
                and judgment.deficiency_category != RejectionDeficiencyCategory.SUFFICIENT
            )
        )
        if not counter:
            return ()

        highest_count = max(counter.values())
        dominant = sorted(
            category
            for category, count in counter.items()
            if count == highest_count
        )
        return tuple(dominant)

    def _contains_proposal_bearing_content(self, rationale_text: str) -> bool:
        """Apply a minimal structural guard against new proposals in heartbeat rationale."""

        normalized = rationale_text.strip().lower()
        proposal_markers = (
            "proposed answer:",
            "new solution:",
            "rewrite to",
            "replace with",
            "instead answer",
        )
        return any(marker in normalized for marker in proposal_markers)

    def _coerce_vote_choice(self, value: object) -> HeartbeatVoteChoice:
        if isinstance(value, HeartbeatVoteChoice):
            return value
        if isinstance(value, str):
            return HeartbeatVoteChoice(value.strip().lower())
        raise ValueError("Heartbeat judgment requires a decision of approve or reject.")

    def _coerce_rationale_text(self, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("Heartbeat judgment requires a non-empty rationale_text.")
        normalized = value.strip()
        if not normalized:
            raise ValueError("Heartbeat judgment requires a non-empty rationale_text.")
        return normalized

    def _coerce_deficiency_category(
        self,
        value: object,
        decision: HeartbeatVoteChoice,
    ) -> RejectionDeficiencyCategory:
        if isinstance(value, RejectionDeficiencyCategory):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized:
                return RejectionDeficiencyCategory(normalized)
        if decision == HeartbeatVoteChoice.APPROVE:
            return RejectionDeficiencyCategory.SUFFICIENT
        return RejectionDeficiencyCategory.OTHER

    def _coerce_resource_status(self, value: object) -> HeartbeatResourceStatus:
        if isinstance(value, HeartbeatResourceStatus):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized:
                return HeartbeatResourceStatus(normalized)
        return HeartbeatResourceStatus.UNKNOWN

    def _coerce_signal_keys(self, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            normalized = value.strip()
            return (normalized,) if normalized else ()
        if isinstance(value, (list, tuple, set)):
            normalized_keys = tuple(str(item).strip() for item in value if str(item).strip())
            return normalized_keys
        raise ValueError("Expected used_signal_keys to be a string sequence when provided.")

    def _coalesce_mapping_value(
        self,
        raw_result: Mapping[str, object],
        metadata: Mapping[str, object],
        *keys: str,
    ) -> object:
        for key in keys:
            if key in raw_result and raw_result.get(key) is not None:
                return raw_result.get(key)
        return self._coalesce_legacy_metadata_value(metadata, *keys)

    def _coalesce_legacy_metadata_value(
        self,
        metadata: Mapping[str, object],
        *keys: str,
    ) -> object:
        for key in keys:
            if key in metadata and metadata.get(key) is not None:
                return metadata.get(key)
        return None

    def _resolve_grading_fields(
        self,
        *,
        decision: HeartbeatVoteChoice,
        deficiency_category: RejectionDeficiencyCategory | None,
        severity: object,
        blocker: object,
        used_signal_keys: Sequence[str],
        source_anchors: object,
        checkpoint_input: HeartbeatCheckpointInput,
        evidence_bundle: HeartbeatEvidenceBundle | None,
        agent_role: str,
    ) -> tuple[str | None, bool | None]:
        normalized_severity = canonicalize_severity_label(severity)
        normalized_blocker = blocker
        if normalized_severity is None or normalized_blocker is None:
            grading = derive_heartbeat_grading(
                decision=decision,
                deficiency_category=deficiency_category,
                used_signal_keys=used_signal_keys,
                source_anchors=source_anchors,
                checkpoint_input=checkpoint_input,
                evidence_bundle=evidence_bundle,
                agent_role=agent_role,
            )
            if normalized_severity is None:
                normalized_severity = grading.severity
            normalized_blocker = grading.blocker
        return normalized_severity, normalized_blocker

    def _stabilize_aggregate_judgments(
        self,
        *,
        checkpoint_input: HeartbeatCheckpointInput,
        judgments: Sequence[HeartbeatAgentJudgment],
        evidence_bundle: HeartbeatEvidenceBundle | None,
    ) -> tuple[HeartbeatAgentJudgment, ...]:
        if not judgments:
            return ()
        return tuple(
            self._stabilize_single_aggregate_judgment(
                judgment=judgment,
                checkpoint_input=checkpoint_input,
                evidence_bundle=evidence_bundle,
            )
            for judgment in judgments
        )

    def _stabilize_single_aggregate_judgment(
        self,
        *,
        judgment: HeartbeatAgentJudgment,
        checkpoint_input: HeartbeatCheckpointInput,
        evidence_bundle: HeartbeatEvidenceBundle | None,
    ) -> HeartbeatAgentJudgment:
        metadata = judgment.metadata if isinstance(judgment.metadata, Mapping) else {}
        used_signal_keys = judgment.used_signal_keys or self._coerce_signal_keys(
            self._coalesce_legacy_metadata_value(metadata, "used_signal_keys")
        )
        source_anchors = judgment.source_anchors or self._coalesce_legacy_metadata_value(
            metadata,
            "source_anchors",
        )
        severity_value = judgment.severity
        if severity_value is None:
            severity_value = self._coalesce_legacy_metadata_value(
                metadata,
                "severity",
                "deficiency_severity",
            )
        blocker_value = judgment.blocker
        if blocker_value is None:
            blocker_value = self._coalesce_legacy_metadata_value(
                metadata,
                "blocker",
                "is_blocker",
                "blocking",
                "is_blocking",
            )
        resolved_severity, resolved_blocker = self._resolve_grading_fields(
            decision=judgment.decision,
            deficiency_category=judgment.deficiency_category,
            severity=severity_value,
            blocker=blocker_value,
            used_signal_keys=used_signal_keys,
            source_anchors=source_anchors,
            checkpoint_input=checkpoint_input,
            evidence_bundle=evidence_bundle,
            agent_role=self._resolve_agent_role(judgment.agent_id, metadata),
        )
        return HeartbeatAgentJudgment.create(
            judgment_id=judgment.judgment_id,
            checkpoint_id=judgment.checkpoint_id,
            agent_id=judgment.agent_id,
            candidate_id=judgment.candidate_id,
            evidence_bundle_id=judgment.evidence_bundle_id,
            decision=judgment.decision,
            rationale_text=judgment.rationale_text,
            deficiency_category=judgment.deficiency_category,
            severity=resolved_severity,
            blocker=resolved_blocker,
            used_signal_keys=used_signal_keys,
            source_anchors=source_anchors,
            resource_status=judgment.resource_status,
            metadata=metadata,
            proposed_new_solution_content=judgment.proposed_new_solution_content,
        )

    def _resolve_agent_role(self, agent_id: str, metadata: Mapping[str, object]) -> str:
        role = metadata.get("agent_role")
        if isinstance(role, str):
            normalized_role = role.strip()
            if normalized_role:
                return normalized_role
        agent = self.agents.get(agent_id)
        if agent is not None:
            role_name = getattr(agent, "role_name", None)
            if isinstance(role_name, str):
                normalized_role = role_name.strip()
                if normalized_role:
                    return normalized_role
        return agent_id

    def _coerce_optional_string(self, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Expected an optional string identifier for heartbeat judgment.")
        normalized = value.strip()
        return normalized or None
