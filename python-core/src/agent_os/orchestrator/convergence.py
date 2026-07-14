from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import uuid4

from agent_os.orchestrator.heartbeat_grading_contract import (
    canonicalize_heartbeat_blocker_count,
    canonicalize_heartbeat_blocker_roles,
    canonicalize_heartbeat_severity,
    canonicalize_heartbeat_severity_histogram,
    heartbeat_severity_sort_key,
    normalize_heartbeat_blocker,
    validate_heartbeat_judgment_grading,
)
from agent_os.protocols.final_answer_candidate import FinalAnswerCandidate
from agent_os.protocols.message import CommunicationMessage

if TYPE_CHECKING:
    from agent_os.orchestrator.heartbeat_candidate_presentation import (
        HeartbeatCandidatePresentation,
    )
    from agent_os.orchestrator.heartbeat_candidate_snapshot import (
        HeartbeatCandidateSnapshot,
    )
    from agent_os.orchestrator.heartbeat_convergence_profile import (
        HeartbeatConvergenceProfile,
    )
    from agent_os.orchestrator.heartbeat_outcome_snapshot import (
        HeartbeatOutcomeSnapshot,
    )
    from agent_os.orchestrator.heartbeat_terminal_payload import (
        HeartbeatTerminalPayload,
    )
    from agent_os.orchestrator.runtime_state import ExecutionState


class CoordinationPhase(StrEnum):
    """High-level phases in the convergence cycle."""

    DISCUSSION_ROUND = "discussion_round"
    HEARTBEAT_CHECKPOINT = "heartbeat_checkpoint"
    TERMINATION_EXTENSION_HANDLING = "termination_extension_handling"


class EvaluationStage(StrEnum):
    """Stage boundaries used by the debate evaluation subsystem."""

    DISCUSSION_ROUND = "discussion_round"
    HEARTBEAT_CHECKPOINT = "heartbeat_checkpoint"
    FINAL_ANSWER_EVALUATION = "final_answer_evaluation"
    EXTENSION_HANDLING = "extension_handling"


class ConvergenceStatus(StrEnum):
    """Control outcomes emitted by the convergence evaluation layer."""

    CONTINUE = "continue"
    CONVERGED = "converged"
    FORCED_STOP = "forced_stop"


class VotingMode(StrEnum):
    """Fallback decision modes available when voting is permitted."""

    MAJORITY = "majority"
    JUDGE_AGENT = "judge_agent"


class ParticipantStatus(StrEnum):
    """Participation states for agents within the convergence mechanism."""

    ACTIVE = "active"
    SLEEPING = "sleeping"
    STOPPED = "stopped"


class RecorderRole(StrEnum):
    """Recorder assignments supported by the mechanism."""

    PRIMARY = "primary"
    BACKUP = "backup"


class HeartbeatAction(StrEnum):
    """Actions permitted during heartbeat checkpoints."""

    SELF_CHECK = "self_check"
    RESOURCE_CHECK = "resource_check"
    SLEEP_DECISION = "sleep_decision"
    RECORDER_SUMMARY = "recorder_summary"


class HeartbeatVoteChoice(StrEnum):
    """Vote choices available during heartbeat self-check."""

    APPROVE = "approve"
    REJECT = "reject"


class HeartbeatResolution(StrEnum):
    """Stage outcomes available after dispatcher aggregation."""

    STOP_AND_OUTPUT = "stop_and_output"
    RESUME_DISCUSSION = "resume_discussion"
    DEFER_TO_EXISTING_FALLBACK = "defer_to_existing_fallback"


class FinalContributionStatus(StrEnum):
    """Final contribution outcomes recorded per agent."""

    ADOPTED = "adopted"
    PARTIALLY_ADOPTED = "partially_adopted"
    MINORITY_VIEW_VISIBLE = "minority_view_visible"
    NOT_ADOPTED = "not_adopted"
    NOT_EVALUATED = "not_evaluated"


class NextRoundInclusionSignal(StrEnum):
    """Advisory signals shown to the user for the next discussion round."""

    RETAIN = "retain"
    REVIEW = "review"
    OPTIONAL = "optional"


class RejectionDeficiencyCategory(StrEnum):
    """High-level deficiency categories used in heartbeat judgments."""

    SUFFICIENT = "sufficient"

    GOAL_MISALIGNMENT = "goal_misalignment"
    INCOMPLETENESS = "incompleteness"
    CORRECTNESS_RISK = "correctness_risk"
    EVIDENCE_GAP = "evidence_gap"
    CONSTRAINT_VIOLATION = "constraint_violation"
    CLARITY_GAP = "clarity_gap"
    OTHER = "other"


class TriggerType(StrEnum):
    """Generic trigger kinds supported for checkpoint entry."""

    ROUND_BASED = "round_based"
    TIME_BASED = "time_based"


class TriggerScope(StrEnum):
    """Configuration scopes for checkpoint trigger definitions."""

    GLOBAL_DEFAULT = "global_default"
    PROJECT_OVERRIDE = "project_override"
    RUNTIME_ADJUSTMENT = "runtime_adjustment"


class TriggerAggregationMode(StrEnum):
    """Aggregation semantics for multiple checkpoint triggers."""

    ANY = "any"


class HeartbeatResourceStatus(StrEnum):
    """Lightweight resource state attached to a checkpoint judgment."""

    UNKNOWN = "unknown"
    NOMINAL = "nominal"
    LIMITED = "limited"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True, slots=True)
class Trigger:
    """Generic checkpoint trigger definition configured by users.

    The system treats all checkpoint intervals as generic triggers and only
    evaluates them. Expected parameter examples:
    - `round_based`: `interval_rounds`, optional `start_round`
    - `time_based`: `interval_seconds`, optional `start_at`
    """

    id: str
    trigger_type: TriggerType
    parameters: Mapping[str, object] = field(default_factory=dict)
    scope: TriggerScope = TriggerScope.GLOBAL_DEFAULT
    enabled: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CheckpointTriggerSemantics:
    """Execution semantics for checkpoint trigger evaluation."""

    aggregation_mode: TriggerAggregationMode = TriggerAggregationMode.ANY
    enter_phase_on_fire: CoordinationPhase = CoordinationPhase.HEARTBEAT_CHECKPOINT
    users_define_parameters: bool = True
    system_execution_only: bool = True
    adaptive_optimization_enabled: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CheckpointTriggerResponsibilities:
    """Responsibility boundaries for trigger definition and execution."""

    users_define_trigger_parameters: bool = True
    users_select_scope_overrides: bool = True
    system_evaluates_trigger_firing: bool = True
    system_applies_heartbeat_transition: bool = True
    system_does_not_invent_parameters: bool = True
    system_does_not_optimize_triggers: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TriggerConfigurationLayer:
    """One configuration layer for generic checkpoint triggers."""

    scope: TriggerScope
    triggers: tuple[Trigger, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CheckpointTriggerConfiguration:
    """Layered checkpoint trigger configuration with OR semantics."""

    semantics: CheckpointTriggerSemantics = field(default_factory=CheckpointTriggerSemantics)
    responsibilities: CheckpointTriggerResponsibilities = field(
        default_factory=CheckpointTriggerResponsibilities
    )
    resolution_order: tuple[TriggerScope, ...] = (
        TriggerScope.GLOBAL_DEFAULT,
        TriggerScope.PROJECT_OVERRIDE,
        TriggerScope.RUNTIME_ADJUSTMENT,
    )
    global_defaults: TriggerConfigurationLayer = field(
        default_factory=lambda: TriggerConfigurationLayer(scope=TriggerScope.GLOBAL_DEFAULT)
    )
    project_overrides: TriggerConfigurationLayer = field(
        default_factory=lambda: TriggerConfigurationLayer(scope=TriggerScope.PROJECT_OVERRIDE)
    )
    runtime_adjustments: TriggerConfigurationLayer = field(
        default_factory=lambda: TriggerConfigurationLayer(scope=TriggerScope.RUNTIME_ADJUSTMENT)
    )
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FrozenDiscussionResult:
    """Compatibility snapshot of discussion trace frozen at checkpoint entry.

    This structure remains available as auxiliary checkpoint trace. The
    canonical heartbeat input is `HeartbeatCheckpointInput`.
    """

    discussion_message_ids: tuple[str, ...] = ()
    result_summary_text: str | None = None
    original_task_goal: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HeartbeatCheckpointInput:
    """Canonical heartbeat input built from a frozen final-answer candidate."""

    checkpoint_id: str
    workflow_id: str
    original_goal: str
    frozen_candidate_id: str
    frozen_candidate_summary: str
    frozen_candidate_payload: Mapping[str, object] | None = None
    frozen_candidate_structured_content: Mapping[str, object] | None = None
    source_round: int | None = None
    relevant_context_refs: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_candidate(
        cls,
        *,
        workflow_id: str,
        original_goal: str,
        candidate: FinalAnswerCandidate,
        relevant_context_refs: Sequence[str] = (),
        checkpoint_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> HeartbeatCheckpointInput:
        """Build the canonical checkpoint input from a frozen candidate."""

        return cls(
            checkpoint_id=checkpoint_id or f"checkpoint-{uuid4()}",
            workflow_id=workflow_id,
            original_goal=original_goal,
            frozen_candidate_id=candidate.candidate_id,
            frozen_candidate_summary=candidate.summary_text,
            frozen_candidate_payload=candidate.payload,
            frozen_candidate_structured_content=candidate.structured_content,
            source_round=candidate.source_round,
            relevant_context_refs=tuple(relevant_context_refs),
            metadata={
                "candidate_status": candidate.status.value,
                **dict(metadata or {}),
            },
        )


@dataclass(frozen=True, slots=True)
class HeartbeatEvidenceBundle:
    """Canonical structured evidence input derived from a frozen candidate.

    The evidence bundle does not replace `FinalAnswerCandidate`. The frozen
    candidate remains the canonical evaluation object; this bundle only
    provides a stable, structured evidence surface for role-specific heartbeat
    judgments and later reporting/audit reuse.
    """

    evidence_bundle_id: str
    checkpoint_id: str
    candidate_id: str
    original_goal: str
    candidate_summary: str
    structured_content_summary: Mapping[str, object] | None = None
    payload_summary: Mapping[str, object] | None = None
    source_round: int | None = None
    relevant_context_refs: tuple[str, ...] = ()
    constraint_signals: Mapping[str, object] = field(default_factory=dict)
    coverage_signals: Mapping[str, object] = field(default_factory=dict)
    implementation_signals: Mapping[str, object] = field(default_factory=dict)
    risk_signals: Mapping[str, object] = field(default_factory=dict)
    evidence_signals: Mapping[str, object] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def is_canonical_evidence_input(self) -> bool:
        """Whether this bundle is the structured evidence input for heartbeat."""

        return True

    @classmethod
    def create(
        cls,
        *,
        checkpoint_id: str,
        candidate_id: str,
        original_goal: str,
        candidate_summary: str,
        structured_content_summary: Mapping[str, object] | None = None,
        payload_summary: Mapping[str, object] | None = None,
        source_round: int | None = None,
        relevant_context_refs: Sequence[str] = (),
        constraint_signals: Mapping[str, object] | None = None,
        coverage_signals: Mapping[str, object] | None = None,
        implementation_signals: Mapping[str, object] | None = None,
        risk_signals: Mapping[str, object] | None = None,
        evidence_signals: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
        evidence_bundle_id: str | None = None,
    ) -> HeartbeatEvidenceBundle:
        """Create a normalized structured evidence bundle for heartbeat self-check."""

        return cls(
            evidence_bundle_id=evidence_bundle_id or f"evidence-{uuid4()}",
            checkpoint_id=checkpoint_id,
            candidate_id=candidate_id,
            original_goal=original_goal,
            candidate_summary=candidate_summary,
            structured_content_summary=dict(structured_content_summary or {})
            if structured_content_summary is not None
            else None,
            payload_summary=dict(payload_summary or {}) if payload_summary is not None else None,
            source_round=source_round,
            relevant_context_refs=tuple(relevant_context_refs),
            constraint_signals=dict(constraint_signals or {}),
            coverage_signals=dict(coverage_signals or {}),
            implementation_signals=dict(implementation_signals or {}),
            risk_signals=dict(risk_signals or {}),
            evidence_signals=dict(evidence_signals or {}),
            metadata=dict(metadata or {}),
        )


@dataclass(frozen=True, slots=True)
class HeartbeatSelfCheckSemantics:
    """Behavioral contract for agent self-checks during heartbeat.

    The current runtime executes heartbeat self-checks sequentially. Parallel
    heartbeat remains a reserved future capability rather than active behavior.
    """

    non_discussion_phase: bool = True
    freeze_current_result_on_entry: bool = True
    run_non_sleeping_agents_only: bool = True
    run_in_parallel: bool = False
    run_independently: bool = True
    compare_against_original_task_goal: bool = True
    vote_on_final_answer: bool = True
    binary_voting_only: bool = True
    supports_abstain: bool = False
    require_rationale_for_all_votes: bool = True
    discourages_low_effort_agreement: bool = True
    approval_rationale_explains_sufficiency: bool = True
    rejection_rationale_explains_main_deficiency_category: bool = True
    rationale_must_be_concise: bool = True
    rationale_must_be_diagnostic: bool = True
    allow_short_dissent_reasons: bool = True
    allow_empty_approval: bool = False
    allow_empty_rejection: bool = False
    allow_solution_rewrite_in_rationale: bool = False
    allow_new_solution_content: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HeartbeatDispatcherSemantics:
    """Dispatcher boundaries for heartbeat aggregation."""

    aggregate_only: bool = True
    reinterprets_agent_judgments: bool = False
    overrides_agent_judgments: bool = False
    outputs_approval_counts_and_ratios: bool = True
    outputs_rejection_counts_and_ratios: bool = True
    outputs_concise_dissent_summary: bool = True
    threshold_not_met_allows_resume_discussion: bool = True
    threshold_not_met_allows_existing_fallbacks: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DiscussionRoundDefinition:
    """Definition of a proposal-bearing discussion round."""

    phase: CoordinationPhase = CoordinationPhase.DISCUSSION_ROUND
    counts_toward_discussion_rounds: bool = True
    allows_new_solution_proposals: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HeartbeatCheckpointDefinition:
    """Definition of a non-proposal checkpoint between discussion rounds.

    Heartbeat entry is controlled by generic triggers. If any enabled trigger
    fires under the configured aggregation semantics, the system enters the
    heartbeat checkpoint.
    """

    phase: CoordinationPhase = CoordinationPhase.HEARTBEAT_CHECKPOINT
    counts_toward_discussion_rounds: bool = False
    allows_new_solution_proposals: bool = False
    freeze_current_result_on_entry: bool = True
    entry_triggers: CheckpointTriggerConfiguration = field(
        default_factory=CheckpointTriggerConfiguration
    )
    self_check: HeartbeatSelfCheckSemantics = field(default_factory=HeartbeatSelfCheckSemantics)
    dispatcher: HeartbeatDispatcherSemantics = field(default_factory=HeartbeatDispatcherSemantics)
    allowed_actions: tuple[HeartbeatAction, ...] = (
        HeartbeatAction.SELF_CHECK,
        HeartbeatAction.RESOURCE_CHECK,
        HeartbeatAction.SLEEP_DECISION,
        HeartbeatAction.RECORDER_SUMMARY,
    )
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TerminationExtensionDefinition:
    """Definition of the phase that resolves termination or extension only."""

    phase: CoordinationPhase = CoordinationPhase.TERMINATION_EXTENSION_HANDLING
    counts_toward_discussion_rounds: bool = False
    allows_new_solution_proposals: bool = False
    evaluates_termination: bool = True
    evaluates_extension_requests: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvaluationStageBoundary:
    """Boundary contract for a debate-evaluation stage."""

    stage: EvaluationStage
    phase: CoordinationPhase
    allows_new_solution_proposals: bool
    voting_permitted: bool
    updates_agent_metrics: bool
    produces_final_report: bool
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DebateEvaluationBoundaries:
    """Stage boundaries for discussion, heartbeat, and final evaluation."""

    discussion_round: EvaluationStageBoundary = field(
        default_factory=lambda: EvaluationStageBoundary(
            stage=EvaluationStage.DISCUSSION_ROUND,
            phase=CoordinationPhase.DISCUSSION_ROUND,
            allows_new_solution_proposals=True,
            voting_permitted=False,
            updates_agent_metrics=False,
            produces_final_report=False,
        )
    )
    heartbeat_checkpoint: EvaluationStageBoundary = field(
        default_factory=lambda: EvaluationStageBoundary(
            stage=EvaluationStage.HEARTBEAT_CHECKPOINT,
            phase=CoordinationPhase.HEARTBEAT_CHECKPOINT,
            allows_new_solution_proposals=False,
            voting_permitted=True,
            updates_agent_metrics=True,
            produces_final_report=False,
        )
    )
    final_answer_evaluation: EvaluationStageBoundary = field(
        default_factory=lambda: EvaluationStageBoundary(
            stage=EvaluationStage.FINAL_ANSWER_EVALUATION,
            phase=CoordinationPhase.TERMINATION_EXTENSION_HANDLING,
            allows_new_solution_proposals=False,
            voting_permitted=True,
            updates_agent_metrics=True,
            produces_final_report=True,
        )
    )
    extension_handling: EvaluationStageBoundary = field(
        default_factory=lambda: EvaluationStageBoundary(
            stage=EvaluationStage.EXTENSION_HANDLING,
            phase=CoordinationPhase.TERMINATION_EXTENSION_HANDLING,
            allows_new_solution_proposals=False,
            voting_permitted=False,
            updates_agent_metrics=False,
            produces_final_report=False,
        )
    )
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConvergenceCycleDefinition:
    """Mechanism-level description of the three-phase convergence cycle."""

    discussion_round: DiscussionRoundDefinition = field(default_factory=DiscussionRoundDefinition)
    heartbeat_checkpoint: HeartbeatCheckpointDefinition = field(
        default_factory=HeartbeatCheckpointDefinition
    )
    termination_extension_handling: TerminationExtensionDefinition = field(
        default_factory=TerminationExtensionDefinition
    )
    evaluation_boundaries: DebateEvaluationBoundaries = field(
        default_factory=DebateEvaluationBoundaries
    )
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConsensusThresholds:
    """Thresholds for semantic agreement across discussion outputs."""

    agreement_threshold: float = 0.85
    minimum_participants: int = 2
    require_embeddings: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GoalSatisfactionThresholds:
    """Thresholds for determining whether the shared goal is satisfied."""

    satisfaction_threshold: float = 0.85
    require_recorder_summary: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StagnationThresholds:
    """Thresholds for minimal-improvement detection across recent rounds."""

    window_size: int = 3
    embedding_distance_threshold: float = 0.05
    diff_score_threshold: float | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConstraintThresholds:
    """Thresholds for forced-stop checks against orchestration state."""

    max_iterations: int | None = None
    max_total_tokens: int | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VotingThresholds:
    """Thresholds for majority support or judge-agent fallback decisions."""

    mode: VotingMode = VotingMode.MAJORITY
    support_ratio_threshold: float = 0.5
    minimum_support_count: int | None = None
    judge_agent_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConvergenceThresholdProfile:
    """Threshold bundle passed into evaluators and tuning strategies."""

    consensus: ConsensusThresholds = field(default_factory=ConsensusThresholds)
    goal_satisfaction: GoalSatisfactionThresholds = field(
        default_factory=GoalSatisfactionThresholds
    )
    stagnation: StagnationThresholds = field(default_factory=StagnationThresholds)
    constraints: ConstraintThresholds = field(default_factory=ConstraintThresholds)
    voting: VotingThresholds = field(default_factory=VotingThresholds)
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VotingPolicy:
    """Structural policy for when voting is permitted."""

    per_response_voting_enabled: bool = False
    binary_only: bool = True
    supports_abstain_as_standard_option: bool = False
    requires_non_empty_rationale: bool = True
    allowed_stages: tuple[EvaluationStage, ...] = (
        EvaluationStage.HEARTBEAT_CHECKPOINT,
        EvaluationStage.FINAL_ANSWER_EVALUATION,
    )
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SleepPolicy:
    """Structural rules for agent sleep behavior during checkpoints."""

    requires_explicit_wake: bool = True
    allows_automatic_rejoin: bool = False
    quality_based_forced_sleep_enabled: bool = False
    standardized_sleep_reply: str = "STATUS: SLEEPING"
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExtensionRequestConditions:
    """Structural conditions that gate whether an extension may be requested."""

    allowed_phase: CoordinationPhase = CoordinationPhase.TERMINATION_EXTENSION_HANDLING
    allowed_stage: EvaluationStage = EvaluationStage.EXTENSION_HANDLING
    requires_goal_not_satisfied: bool = True
    requires_actionable_next_step: bool = True
    requires_remaining_iteration_budget: bool = True
    requires_remaining_token_budget: bool = True
    requires_recorder_summary: bool = True
    requires_voting_support: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RecorderSummaryPolicy:
    """Structural requirements for recorder output."""

    concise: bool = True
    qualitative: bool = True
    user_facing: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RecorderAssignments:
    """Recorder assignments for the current convergence cycle."""

    primary_recorder_id: str | None = None
    backup_recorder_id: str | None = None
    summary_policy: RecorderSummaryPolicy = field(default_factory=RecorderSummaryPolicy)
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DiversityPreservationPolicy:
    """Structural guarantees that keep low-support views visible."""

    low_approval_does_not_imply_removal: bool = True
    minority_opinions_must_remain_visible: bool = True
    next_round_guidance_is_advisory_only: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParticipantStateDefinition:
    """State definition for an agent's participation in a convergence cycle."""

    agent_id: str
    status: ParticipantStatus = ParticipantStatus.ACTIVE
    recorder_role: RecorderRole | None = None
    sleep_reply: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConvergencePolicy:
    """Top-level convergence configuration and reporting semantics."""

    cycle: ConvergenceCycleDefinition = field(default_factory=ConvergenceCycleDefinition)
    thresholds: ConvergenceThresholdProfile = field(default_factory=ConvergenceThresholdProfile)
    voting: VotingPolicy = field(default_factory=VotingPolicy)
    sleep: SleepPolicy = field(default_factory=SleepPolicy)
    extension_conditions: ExtensionRequestConditions = field(
        default_factory=ExtensionRequestConditions
    )
    recorders: RecorderAssignments = field(default_factory=RecorderAssignments)
    diversity: DiversityPreservationPolicy = field(default_factory=DiversityPreservationPolicy)
    enable_dynamic_threshold_tuning: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GoalSatisfactionAssessment:
    """Structure returned by goal-satisfaction evaluation."""

    satisfied: bool
    satisfaction_score: float | None = None
    satisfaction_threshold: float | None = None
    supporting_agent_ids: tuple[str, ...] = ()
    supporting_message_ids: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConsensusAssessment:
    """Structure returned by semantic agreement evaluation."""

    agreed: bool
    agreement_score: float | None = None
    agreement_threshold: float | None = None
    compared_agent_ids: tuple[str, ...] = ()
    compared_message_ids: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StagnationAssessment:
    """Structure returned by minimal-improvement detection."""

    stagnant: bool
    window_size: int
    embedding_distance: float | None = None
    diff_score: float | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConstraintAssessment:
    """Structure returned by state-based forced-stop checks."""

    allowed_to_continue: bool
    triggered_constraints: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TriggerEvaluationResult:
    """Result of evaluating layered checkpoint triggers."""

    fires_checkpoint: bool | None = None
    aggregation_mode: TriggerAggregationMode = TriggerAggregationMode.ANY
    target_phase: CoordinationPhase = CoordinationPhase.HEARTBEAT_CHECKPOINT
    fired_trigger_ids: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HeartbeatAgentJudgment:
    """Canonical per-agent heartbeat self-check output with evidence linkage."""

    judgment_id: str
    checkpoint_id: str
    agent_id: str
    candidate_id: str
    decision: HeartbeatVoteChoice
    rationale_text: str
    evidence_bundle_id: str | None = None
    deficiency_category: RejectionDeficiencyCategory | None = None
    severity: str | None = None
    blocker: bool | None = None
    used_signal_keys: tuple[str, ...] = ()
    source_anchors: tuple[HeartbeatSourceAnchor, ...] = ()
    resource_status: HeartbeatResourceStatus = HeartbeatResourceStatus.UNKNOWN
    compared_against_original_task_goal: bool = True
    rationale_is_concise: bool = True
    rationale_is_diagnostic: bool = True
    rationale_contains_solution_rewrite: bool = False
    proposed_new_solution_content: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        checkpoint_id: str,
        agent_id: str,
        candidate_id: str,
        evidence_bundle_id: str | None = None,
        decision: HeartbeatVoteChoice,
        rationale_text: str,
        deficiency_category: RejectionDeficiencyCategory | None = None,
        severity: str | None = None,
        blocker: bool | None = None,
        used_signal_keys: Sequence[str] = (),
        source_anchors: Sequence[HeartbeatSourceAnchor | Mapping[str, object]] = (),
        resource_status: HeartbeatResourceStatus = HeartbeatResourceStatus.UNKNOWN,
        metadata: Mapping[str, object] | None = None,
        judgment_id: str | None = None,
        proposed_new_solution_content: bool = False,
    ) -> HeartbeatAgentJudgment:
        """Create and minimally validate a canonical heartbeat judgment."""

        normalized_rationale = rationale_text.strip()
        if not normalized_rationale:
            raise ValueError("Heartbeat judgment requires a non-empty rationale_text.")
        if proposed_new_solution_content:
            raise ValueError("Heartbeat judgments must not contain new solution proposals.")

        normalized_category = deficiency_category
        if decision == HeartbeatVoteChoice.APPROVE and normalized_category is None:
            normalized_category = RejectionDeficiencyCategory.SUFFICIENT
        if decision == HeartbeatVoteChoice.REJECT and normalized_category is None:
            normalized_category = RejectionDeficiencyCategory.OTHER
        normalized_severity, normalized_blocker = validate_heartbeat_judgment_grading(
            decision=decision,
            deficiency_category=normalized_category,
            severity=severity,
            blocker=blocker,
        )
        normalized_signal_keys = tuple(str(key).strip() for key in used_signal_keys if str(key).strip())
        normalized_source_anchors = cls._normalize_source_anchors(source_anchors)

        return cls(
            judgment_id=judgment_id or f"judgment-{uuid4()}",
            checkpoint_id=checkpoint_id,
            agent_id=agent_id,
            candidate_id=candidate_id,
            evidence_bundle_id=evidence_bundle_id,
            decision=decision,
            rationale_text=normalized_rationale,
            deficiency_category=normalized_category,
            severity=normalized_severity,
            blocker=normalized_blocker,
            used_signal_keys=normalized_signal_keys,
            source_anchors=normalized_source_anchors,
            resource_status=resource_status,
            proposed_new_solution_content=proposed_new_solution_content,
            metadata=dict(metadata or {}),
        )

    @staticmethod
    def _normalize_optional_label(value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        return normalized or None

    @staticmethod
    def _normalize_optional_bool(value: object) -> bool | None:
        return normalize_heartbeat_blocker(value)

    @classmethod
    def _normalize_source_anchors(
        cls,
        value: object,
    ) -> tuple[HeartbeatSourceAnchor, ...]:
        if value is None:
            return ()
        if isinstance(value, (HeartbeatSourceAnchor, Mapping)):
            normalized_values = (value,)
        elif isinstance(value, (list, tuple, set)):
            normalized_values = tuple(value)
        else:
            raise TypeError(
                "Heartbeat judgment source_anchors must be a source anchor or a sequence of anchors."
            )
        return tuple(cls._normalize_source_anchor(item) for item in normalized_values)

    @classmethod
    def _normalize_source_anchor(
        cls,
        value: HeartbeatSourceAnchor | Mapping[str, object],
    ) -> HeartbeatSourceAnchor:
        if isinstance(value, HeartbeatSourceAnchor):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("Heartbeat source anchor entries must be mappings or HeartbeatSourceAnchor.")

        signal_key = cls._normalize_required_string(value.get("signal_key"), "signal_key")
        signal_family = cls._normalize_optional_label(value.get("signal_family"))
        if signal_family is None:
            signal_family = signal_key.split(".", maxsplit=1)[0].strip().lower()
        metadata = value.get("metadata")
        if metadata is not None and not isinstance(metadata, Mapping):
            raise TypeError("Heartbeat source anchor metadata must be a mapping when provided.")
        return HeartbeatSourceAnchor(
            signal_key=signal_key,
            signal_family=signal_family,
            source_fields=cls._normalize_string_tuple(value.get("source_fields")),
            matched_refs=cls._normalize_string_tuple(value.get("matched_refs")),
            derived_from_summary=bool(value.get("derived_from_summary", False)),
            derived_from_structured_content=bool(
                value.get("derived_from_structured_content", False)
            ),
            derived_from_payload=bool(value.get("derived_from_payload", False)),
            metadata=dict(metadata or {}),
        )

    @staticmethod
    def _normalize_required_string(value: object, field_name: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"Heartbeat {field_name} must be a non-empty string.")
        normalized = value.strip()
        if not normalized:
            raise TypeError(f"Heartbeat {field_name} must be a non-empty string.")
        return normalized

    @staticmethod
    def _normalize_string_tuple(value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            normalized = value.strip()
            return (normalized,) if normalized else ()
        if isinstance(value, (list, tuple, set)):
            return tuple(str(item).strip() for item in value if str(item).strip())
        raise TypeError("Heartbeat source anchor string collections must be sequences of strings.")

    @property
    def vote(self) -> HeartbeatVoteChoice:
        """Backward-compatible alias for legacy heartbeat vote naming."""

        return self.decision

    @property
    def rationale(self) -> str:
        """Backward-compatible alias for legacy heartbeat rationale naming."""

        return self.rationale_text

    @property
    def rejection_deficiency_category(self) -> RejectionDeficiencyCategory | None:
        """Backward-compatible alias for the normalized deficiency category."""

        return self.deficiency_category

    @property
    def approval_explains_sufficiency(self) -> bool:
        """Whether an approval judgment carries a sufficiency rationale."""

        return self.decision == HeartbeatVoteChoice.APPROVE and bool(self.rationale_text)

    @property
    def rejection_explains_main_deficiency(self) -> bool:
        """Whether a reject judgment names a deficiency category."""

        return self.decision == HeartbeatVoteChoice.REJECT and self.deficiency_category is not None

    @property
    def dissent_reason(self) -> str | None:
        """Short reject-side rationale preserved for dispatcher summaries."""

        if self.decision != HeartbeatVoteChoice.REJECT:
            return None
        return self.rationale_text


@dataclass(frozen=True, slots=True)
class HeartbeatSourceAnchor:
    """Traceable evidence anchor attached to one used heartbeat signal."""

    signal_key: str
    signal_family: str
    source_fields: tuple[str, ...] = ()
    matched_refs: tuple[str, ...] = ()
    derived_from_summary: bool = False
    derived_from_structured_content: bool = False
    derived_from_payload: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HeartbeatDissentItem:
    """Deterministic per-category dispatcher view retained for later reporting."""

    category: RejectionDeficiencyCategory
    severity: str | None = None
    blocker: bool = False
    supporting_roles: tuple[str, ...] = ()
    dissenting_roles: tuple[str, ...] = ()
    judgment_ids: tuple[str, ...] = ()
    priority_rank: int = 0
    used_signal_keys: tuple[str, ...] = ()
    source_anchors: tuple[HeartbeatSourceAnchor, ...] = ()
    summary: str | None = None
    impact_on_decision: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "severity", canonicalize_heartbeat_severity(self.severity))
        object.__setattr__(self, "blocker", bool(self.blocker))
        normalized_priority_rank = int(self.priority_rank or 0)
        if normalized_priority_rank < 0:
            raise ValueError("Heartbeat dissent item priority_rank must be non-negative.")
        object.__setattr__(self, "priority_rank", normalized_priority_rank)
        if self.category == RejectionDeficiencyCategory.SUFFICIENT and self.blocker:
            raise ValueError("Sufficient aggregate items must not be blocker=true.")


def _heartbeat_profile_high_priority_item_count(
    items: Sequence[HeartbeatDissentItem],
) -> int:
    return sum(
        1
        for item in items
        if item.blocker or item.severity in {"critical", "major"}
    )


def _heartbeat_profile_has_blocker_signal(
    *,
    blocker_count: int,
    items: Sequence[HeartbeatDissentItem],
) -> bool:
    return bool(blocker_count) or any(item.blocker for item in items)


@dataclass(frozen=True, slots=True)
class HeartbeatAggregateArtifact:
    """Report-ready heartbeat aggregate object built from explicit judgments."""

    aggregate_result_id: str
    checkpoint_id: str
    candidate_id: str
    evidence_bundle_id: str | None = None
    final_decision: ConvergenceStatus = ConvergenceStatus.CONTINUE
    highest_rejection_severity: str | None = None
    blocker_count: int = 0
    blocker_roles: tuple[str, ...] = ()
    severity_histogram: Mapping[str, int] = field(default_factory=dict)
    consensus_items: tuple[HeartbeatDissentItem, ...] = ()
    minority_items: tuple[HeartbeatDissentItem, ...] = ()
    unresolved_items: tuple[HeartbeatDissentItem, ...] = ()
    decision_rationale: tuple[str, ...] = ()
    recommended_next_actions: tuple[str, ...] = ()
    candidate_snapshot: HeartbeatCandidateSnapshot | None = None
    convergence_profile: HeartbeatConvergenceProfile | None = None
    outcome_snapshot: HeartbeatOutcomeSnapshot | None = None
    candidate_presentation: HeartbeatCandidatePresentation | None = None
    terminal_payload: HeartbeatTerminalPayload | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_histogram = canonicalize_heartbeat_severity_histogram(self.severity_histogram)
        normalized_highest = canonicalize_heartbeat_severity(self.highest_rejection_severity)
        if normalized_histogram:
            histogram_highest = max(normalized_histogram, key=heartbeat_severity_sort_key)
            normalized_highest = histogram_highest
        normalized_blocker_roles = canonicalize_heartbeat_blocker_roles(self.blocker_roles)
        normalized_blocker_count = max(
            canonicalize_heartbeat_blocker_count(self.blocker_count),
            len(normalized_blocker_roles),
        )
        object.__setattr__(self, "highest_rejection_severity", normalized_highest)
        object.__setattr__(self, "blocker_roles", normalized_blocker_roles)
        object.__setattr__(self, "blocker_count", normalized_blocker_count)
        object.__setattr__(self, "severity_histogram", normalized_histogram)
        if self.candidate_snapshot is not None:
            if self.candidate_snapshot.candidate_id != self.candidate_id:
                raise ValueError(
                    "Heartbeat aggregate artifact candidate_snapshot.candidate_id must "
                    "match candidate_id."
                )
            if self.candidate_snapshot.checkpoint_id != self.checkpoint_id:
                raise ValueError(
                    "Heartbeat aggregate artifact candidate_snapshot.checkpoint_id must "
                    "match checkpoint_id."
                )
        if (
            self.convergence_profile is not None
            and self.convergence_profile.final_decision != self.final_decision
        ):
            raise ValueError(
                "Heartbeat aggregate artifact convergence_profile must mirror final_decision."
            )
        if (
            self.outcome_snapshot is not None
            and self.outcome_snapshot.final_decision != self.final_decision
        ):
            raise ValueError(
                "Heartbeat aggregate artifact outcome_snapshot must mirror final_decision."
            )
        if (
            self.candidate_presentation is not None
            and self.candidate_presentation.final_decision != self.final_decision
        ):
            raise ValueError(
                "Heartbeat aggregate artifact candidate_presentation must mirror final_decision."
            )
        if (
            self.terminal_payload is not None
            and self.terminal_payload.final_decision != self.final_decision
        ):
            raise ValueError(
                "Heartbeat aggregate artifact terminal_payload must mirror final_decision."
            )
        if self.convergence_profile is not None:
            derived_has_blocker = _heartbeat_profile_has_blocker_signal(
                blocker_count=normalized_blocker_count,
                items=self.consensus_items + self.minority_items + self.unresolved_items,
            )
            if self.convergence_profile.has_blocker != derived_has_blocker:
                raise ValueError(
                    "Heartbeat aggregate artifact convergence_profile.has_blocker must "
                    "match canonical aggregate blocker semantics."
                )
            if self.convergence_profile.highest_rejection_severity != normalized_highest:
                raise ValueError(
                    "Heartbeat aggregate artifact convergence_profile.highest_rejection_severity "
                    "must match the canonical aggregate summary."
                )
            if (
                self.convergence_profile.unresolved_high_priority_count
                != _heartbeat_profile_high_priority_item_count(self.unresolved_items)
            ):
                raise ValueError(
                    "Heartbeat aggregate artifact convergence_profile.unresolved_high_priority_count "
                    "must match the aggregate artifact unresolved_items view."
                )
            if (
                self.convergence_profile.minority_high_priority_count
                != _heartbeat_profile_high_priority_item_count(self.minority_items)
            ):
                raise ValueError(
                    "Heartbeat aggregate artifact convergence_profile.minority_high_priority_count "
                    "must match the aggregate artifact minority_items view."
                )
        if self.outcome_snapshot is not None:
            if self.candidate_snapshot is None:
                raise ValueError(
                    "Heartbeat aggregate artifact outcome_snapshot requires candidate_snapshot."
                )
            if self.convergence_profile is None:
                raise ValueError(
                    "Heartbeat aggregate artifact outcome_snapshot requires convergence_profile."
                )
            if self.outcome_snapshot.candidate_snapshot != self.candidate_snapshot:
                raise ValueError(
                    "Heartbeat aggregate artifact outcome_snapshot must reuse the attached "
                    "candidate_snapshot."
                )
            if self.outcome_snapshot.convergence_profile != self.convergence_profile:
                raise ValueError(
                    "Heartbeat aggregate artifact outcome_snapshot must reuse the attached "
                    "convergence_profile."
                )
            from agent_os.orchestrator.heartbeat_candidate_snapshot import (
                assert_heartbeat_candidate_snapshot_matches_aggregate,
            )
            from agent_os.orchestrator.heartbeat_outcome_snapshot import (
                assert_heartbeat_outcome_matches_aggregate,
            )

            assert_heartbeat_candidate_snapshot_matches_aggregate(
                snapshot=self.candidate_snapshot,
                artifact=self,
                aggregate_result=None,
            )
            assert_heartbeat_outcome_matches_aggregate(
                snapshot=self.outcome_snapshot,
                artifact=self,
                aggregate_result=None,
            )
        elif self.candidate_snapshot is not None:
            from agent_os.orchestrator.heartbeat_candidate_snapshot import (
                assert_heartbeat_candidate_snapshot_matches_aggregate,
            )

            assert_heartbeat_candidate_snapshot_matches_aggregate(
                snapshot=self.candidate_snapshot,
                artifact=self,
                aggregate_result=None,
            )
        if self.candidate_presentation is not None:
            if self.candidate_snapshot is None:
                raise ValueError(
                    "Heartbeat aggregate artifact candidate_presentation requires candidate_snapshot."
                )
            if self.convergence_profile is None:
                raise ValueError(
                    "Heartbeat aggregate artifact candidate_presentation requires convergence_profile."
                )
            if self.outcome_snapshot is None:
                raise ValueError(
                    "Heartbeat aggregate artifact candidate_presentation requires outcome_snapshot."
                )
            from agent_os.orchestrator.heartbeat_candidate_presentation import (
                assert_heartbeat_candidate_presentation_matches_aggregate,
            )

            assert_heartbeat_candidate_presentation_matches_aggregate(
                presentation=self.candidate_presentation,
                artifact=self,
                aggregate_result=None,
            )
        if self.terminal_payload is not None:
            if self.candidate_presentation is None:
                raise ValueError(
                    "Heartbeat aggregate artifact terminal_payload requires candidate_presentation."
                )
            if self.outcome_snapshot is None:
                raise ValueError(
                    "Heartbeat aggregate artifact terminal_payload requires outcome_snapshot."
                )
            from agent_os.orchestrator.heartbeat_terminal_payload import (
                assert_heartbeat_terminal_payload_matches_aggregate,
            )

            assert_heartbeat_terminal_payload_matches_aggregate(
                payload=self.terminal_payload,
                artifact=self,
                aggregate_result=None,
            )


@dataclass(frozen=True, slots=True)
class VotingAssessment:
    """Structure returned when voting is evaluated in an allowed stage."""

    stage: EvaluationStage
    mode: VotingMode
    stage_permitted: bool | None = None
    threshold_met: bool | None = None
    approval_count: int | None = None
    support_ratio: float | None = None
    support_count: int | None = None
    approval_ratio: float | None = None
    rejection_count: int | None = None
    rejection_ratio: float | None = None
    selected_message_id: str | None = None
    selected_agent_id: str | None = None
    vote_distribution: Mapping[str, int] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HeartbeatAggregateResult:
    """Dispatcher aggregate result computed from explicit heartbeat judgments."""

    aggregate_result_id: str
    checkpoint_id: str
    total_judgments: int
    approval_count: int
    rejection_count: int
    approval_ratio: float
    rejection_ratio: float
    dissent_summary: str | None = None
    dominant_deficiency_categories: tuple[RejectionDeficiencyCategory, ...] = ()
    recommended_outcome: ConvergenceStatus = ConvergenceStatus.CONTINUE
    highest_rejection_severity: str | None = None
    blocker_count: int = 0
    blocker_roles: tuple[str, ...] = ()
    severity_histogram: Mapping[str, int] = field(default_factory=dict)
    voting: VotingAssessment | None = None
    aggregate_artifact: HeartbeatAggregateArtifact | None = None
    candidate_snapshot: HeartbeatCandidateSnapshot | None = None
    convergence_profile: HeartbeatConvergenceProfile | None = None
    outcome_snapshot: HeartbeatOutcomeSnapshot | None = None
    candidate_presentation: HeartbeatCandidatePresentation | None = None
    terminal_payload: HeartbeatTerminalPayload | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_histogram = canonicalize_heartbeat_severity_histogram(self.severity_histogram)
        normalized_highest = canonicalize_heartbeat_severity(self.highest_rejection_severity)
        if normalized_histogram:
            histogram_highest = max(normalized_histogram, key=heartbeat_severity_sort_key)
            normalized_highest = histogram_highest
        normalized_blocker_roles = canonicalize_heartbeat_blocker_roles(self.blocker_roles)
        normalized_blocker_count = max(
            canonicalize_heartbeat_blocker_count(self.blocker_count),
            len(normalized_blocker_roles),
        )
        object.__setattr__(self, "highest_rejection_severity", normalized_highest)
        object.__setattr__(self, "blocker_roles", normalized_blocker_roles)
        object.__setattr__(self, "blocker_count", normalized_blocker_count)
        object.__setattr__(self, "severity_histogram", normalized_histogram)
        if (
            self.convergence_profile is not None
            and self.convergence_profile.final_decision != self.recommended_outcome
        ):
            raise ValueError(
                "Heartbeat aggregate result convergence_profile must mirror recommended_outcome."
            )
        if (
            self.outcome_snapshot is not None
            and self.outcome_snapshot.final_decision != self.recommended_outcome
        ):
            raise ValueError(
                "Heartbeat aggregate result outcome_snapshot must mirror recommended_outcome."
            )
        if (
            self.candidate_presentation is not None
            and self.candidate_presentation.final_decision != self.recommended_outcome
        ):
            raise ValueError(
                "Heartbeat aggregate result candidate_presentation must mirror recommended_outcome."
            )
        if (
            self.terminal_payload is not None
            and self.terminal_payload.final_decision != self.recommended_outcome
        ):
            raise ValueError(
                "Heartbeat aggregate result terminal_payload must mirror recommended_outcome."
            )
        if self.convergence_profile is not None and self.aggregate_artifact is None:
            raise ValueError(
                "Heartbeat aggregate result convergence_profile requires aggregate_artifact "
                "for item-level consistency."
            )
        if self.outcome_snapshot is not None and self.aggregate_artifact is None:
            raise ValueError(
                "Heartbeat aggregate result outcome_snapshot requires aggregate_artifact "
                "for projection consistency."
            )
        if self.candidate_snapshot is not None and self.aggregate_artifact is None:
            raise ValueError(
                "Heartbeat aggregate result candidate_snapshot requires aggregate_artifact "
                "for projection consistency."
            )
        if self.candidate_presentation is not None and self.aggregate_artifact is None:
            raise ValueError(
                "Heartbeat aggregate result candidate_presentation requires aggregate_artifact "
                "for projection consistency."
            )
        if self.terminal_payload is not None and self.aggregate_artifact is None:
            raise ValueError(
                "Heartbeat aggregate result terminal_payload requires aggregate_artifact "
                "for projection consistency."
            )
        if (
            self.aggregate_artifact is not None
            and self.aggregate_artifact.convergence_profile is not None
            and self.convergence_profile is not None
            and self.aggregate_artifact.convergence_profile != self.convergence_profile
        ):
            raise ValueError(
                "Heartbeat aggregate result and aggregate artifact must not disagree on "
                "convergence_profile."
            )
        if self.aggregate_artifact is not None:
            artifact_has_profile = self.aggregate_artifact.convergence_profile is not None
            result_has_profile = self.convergence_profile is not None
            if artifact_has_profile != result_has_profile:
                raise ValueError(
                    "Heartbeat aggregate result and aggregate artifact must either both expose "
                    "convergence_profile or both omit it."
                )
            artifact_has_outcome = self.aggregate_artifact.outcome_snapshot is not None
            result_has_outcome = self.outcome_snapshot is not None
            if artifact_has_outcome != result_has_outcome:
                raise ValueError(
                    "Heartbeat aggregate result and aggregate artifact must either both expose "
                    "outcome_snapshot or both omit it."
                )
            artifact_has_candidate_snapshot = self.aggregate_artifact.candidate_snapshot is not None
            result_has_candidate_snapshot = self.candidate_snapshot is not None
            if artifact_has_candidate_snapshot != result_has_candidate_snapshot:
                raise ValueError(
                    "Heartbeat aggregate result and aggregate artifact must either both expose "
                    "candidate_snapshot or both omit it."
                )
            artifact_has_candidate_presentation = (
                self.aggregate_artifact.candidate_presentation is not None
            )
            result_has_candidate_presentation = self.candidate_presentation is not None
            if artifact_has_candidate_presentation != result_has_candidate_presentation:
                raise ValueError(
                    "Heartbeat aggregate result and aggregate artifact must either both expose "
                    "candidate_presentation or both omit it."
                )
            artifact_has_terminal_payload = self.aggregate_artifact.terminal_payload is not None
            result_has_terminal_payload = self.terminal_payload is not None
            if artifact_has_terminal_payload != result_has_terminal_payload:
                raise ValueError(
                    "Heartbeat aggregate result and aggregate artifact must either both expose "
                    "terminal_payload or both omit it."
                )
        if self.convergence_profile is not None:
            derived_has_blocker = _heartbeat_profile_has_blocker_signal(
                blocker_count=normalized_blocker_count,
                items=(
                    self.aggregate_artifact.consensus_items
                    + self.aggregate_artifact.minority_items
                    + self.aggregate_artifact.unresolved_items
                ),
            )
            if self.convergence_profile.has_blocker != derived_has_blocker:
                raise ValueError(
                    "Heartbeat aggregate result convergence_profile.has_blocker must match "
                    "canonical aggregate blocker semantics."
                )
            if self.convergence_profile.highest_rejection_severity != normalized_highest:
                raise ValueError(
                    "Heartbeat aggregate result convergence_profile.highest_rejection_severity "
                    "must match the canonical aggregate summary."
                )
        if (
            self.outcome_snapshot is not None
            and self.convergence_profile is not None
            and self.outcome_snapshot.convergence_profile != self.convergence_profile
        ):
            raise ValueError(
                "Heartbeat aggregate result outcome_snapshot must reuse the attached "
                "convergence_profile."
            )
        if (
            self.outcome_snapshot is not None
            and self.candidate_snapshot is not None
            and self.outcome_snapshot.candidate_snapshot != self.candidate_snapshot
        ):
            raise ValueError(
                "Heartbeat aggregate result outcome_snapshot must reuse the attached "
                "candidate_snapshot."
            )
        if (
            self.candidate_snapshot is not None
            and self.aggregate_artifact is not None
            and self.aggregate_artifact.candidate_snapshot is not None
            and self.aggregate_artifact.candidate_snapshot != self.candidate_snapshot
        ):
            raise ValueError(
                "Heartbeat aggregate result and aggregate artifact must not disagree on "
                "candidate_snapshot."
            )
        if (
            self.outcome_snapshot is not None
            and self.aggregate_artifact is not None
            and self.aggregate_artifact.outcome_snapshot is not None
            and self.aggregate_artifact.outcome_snapshot != self.outcome_snapshot
        ):
            raise ValueError(
                "Heartbeat aggregate result and aggregate artifact must not disagree on "
                "outcome_snapshot."
            )
        if (
            self.candidate_presentation is not None
            and self.candidate_snapshot is not None
            and self.candidate_presentation.candidate_id != self.candidate_snapshot.candidate_id
        ):
            raise ValueError(
                "Heartbeat aggregate result candidate_presentation must reuse the attached "
                "candidate_snapshot."
            )
        if (
            self.candidate_presentation is not None
            and self.outcome_snapshot is not None
            and self.candidate_presentation.consumer_readiness
            != self.outcome_snapshot.consumer_readiness
        ):
            raise ValueError(
                "Heartbeat aggregate result candidate_presentation must reuse the attached "
                "outcome_snapshot."
            )
        if (
            self.candidate_presentation is not None
            and self.aggregate_artifact is not None
            and self.aggregate_artifact.candidate_presentation is not None
            and self.aggregate_artifact.candidate_presentation != self.candidate_presentation
        ):
            raise ValueError(
                "Heartbeat aggregate result and aggregate artifact must not disagree on "
                "candidate_presentation."
            )
        if (
            self.terminal_payload is not None
            and self.candidate_presentation is not None
            and self.terminal_payload.candidate != self.candidate_presentation
        ):
            raise ValueError(
                "Heartbeat aggregate result terminal_payload must reuse the attached "
                "candidate_presentation."
            )
        if (
            self.terminal_payload is not None
            and self.outcome_snapshot is not None
            and self.terminal_payload.consumer_readiness
            != self.outcome_snapshot.consumer_readiness
        ):
            raise ValueError(
                "Heartbeat aggregate result terminal_payload must reuse the attached "
                "outcome_snapshot."
            )
        if (
            self.terminal_payload is not None
            and self.aggregate_artifact is not None
            and self.aggregate_artifact.terminal_payload is not None
            and self.aggregate_artifact.terminal_payload != self.terminal_payload
        ):
            raise ValueError(
                "Heartbeat aggregate result and aggregate artifact must not disagree on "
                "terminal_payload."
            )
        if self.outcome_snapshot is not None and self.aggregate_artifact is not None:
            from agent_os.orchestrator.heartbeat_candidate_snapshot import (
                assert_heartbeat_candidate_snapshot_matches_aggregate,
            )
            from agent_os.orchestrator.heartbeat_outcome_snapshot import (
                assert_heartbeat_outcome_matches_aggregate,
            )

            if self.candidate_snapshot is None:
                raise ValueError(
                    "Heartbeat aggregate result outcome_snapshot requires candidate_snapshot."
                )
            assert_heartbeat_candidate_snapshot_matches_aggregate(
                snapshot=self.candidate_snapshot,
                artifact=self.aggregate_artifact,
                aggregate_result=self,
            )
        if self.candidate_presentation is not None and self.aggregate_artifact is not None:
            from agent_os.orchestrator.heartbeat_candidate_presentation import (
                assert_heartbeat_candidate_presentation_matches_aggregate,
            )

            assert_heartbeat_candidate_presentation_matches_aggregate(
                presentation=self.candidate_presentation,
                artifact=self.aggregate_artifact,
                aggregate_result=self,
            )
        if self.terminal_payload is not None and self.aggregate_artifact is not None:
            from agent_os.orchestrator.heartbeat_terminal_payload import (
                assert_heartbeat_terminal_payload_matches_aggregate,
            )

            assert_heartbeat_terminal_payload_matches_aggregate(
                payload=self.terminal_payload,
                artifact=self.aggregate_artifact,
                aggregate_result=self,
            )
            assert_heartbeat_outcome_matches_aggregate(
                snapshot=self.outcome_snapshot,
                artifact=self.aggregate_artifact,
                aggregate_result=self,
            )
        elif self.candidate_snapshot is not None and self.aggregate_artifact is not None:
            from agent_os.orchestrator.heartbeat_candidate_snapshot import (
                assert_heartbeat_candidate_snapshot_matches_aggregate,
            )

            assert_heartbeat_candidate_snapshot_matches_aggregate(
                snapshot=self.candidate_snapshot,
                artifact=self.aggregate_artifact,
                aggregate_result=self,
            )


@dataclass(frozen=True, slots=True)
class HeartbeatCheckpointAssessment:
    """Composite assessment for a non-discussion heartbeat checkpoint."""

    checkpoint_input: HeartbeatCheckpointInput
    evidence_bundle: HeartbeatEvidenceBundle | None = None
    judgments: tuple[HeartbeatAgentJudgment, ...] = ()
    aggregate: HeartbeatAggregateResult | None = None
    approval_threshold_reached: bool | None = None
    resolution: HeartbeatResolution = HeartbeatResolution.RESUME_DISCUSSION
    stop_outputs_frozen_result: bool = True
    stop_outputs_dissent_summary: bool = True
    resume_phase: CoordinationPhase = CoordinationPhase.DISCUSSION_ROUND
    fallback_phase: CoordinationPhase | None = None
    frozen_result: FrozenDiscussionResult | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExtensionEligibility:
    """Structure returned by extension-eligibility evaluation."""

    eligible: bool | None = None
    conditions: ExtensionRequestConditions = field(default_factory=ExtensionRequestConditions)
    reason: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentEvaluationMetrics:
    """Per-agent report metrics emitted in the final evaluation report."""

    agent_id: str
    vote_approval_rate: float | None = None
    rejection_rate: float | None = None
    adoption_rate: float | None = None
    rationale_history_summary: str | None = None
    final_contribution_status: FinalContributionStatus = FinalContributionStatus.NOT_EVALUATED
    next_round_inclusion_signal: NextRoundInclusionSignal = NextRoundInclusionSignal.REVIEW
    next_round_inclusion_note: str | None = None
    requires_user_decision: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MinorityOpinionRecord:
    """Visible record of a non-dominant view retained in the final report."""

    agent_id: str
    message_ids: tuple[str, ...] = ()
    summary_text: str | None = None
    visible_in_report: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DebateEvaluationReport:
    """Final evaluation report emitted whether convergence succeeds or fails."""

    phase: CoordinationPhase
    stage: EvaluationStage
    status: ConvergenceStatus
    goal_satisfaction: GoalSatisfactionAssessment
    stagnation: StagnationAssessment
    voting: VotingAssessment | None = None
    constraints: ConstraintAssessment | None = None
    per_agent_metrics: tuple[AgentEvaluationMetrics, ...] = ()
    minority_opinions: tuple[MinorityOpinionRecord, ...] = ()
    user_guidance_summary: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConvergenceDecision:
    """Composite evaluator result with the current phase, stage, and outcome."""

    phase: CoordinationPhase
    stage: EvaluationStage
    status: ConvergenceStatus
    goal_satisfaction: GoalSatisfactionAssessment
    stagnation: StagnationAssessment
    voting: VotingAssessment | None = None
    heartbeat: HeartbeatCheckpointAssessment | None = None
    constraints: ConstraintAssessment | None = None
    consensus: ConsensusAssessment | None = None
    extension: ExtensionEligibility | None = None
    final_report: DebateEvaluationReport | None = None
    reason: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


class GoalSatisfactionStrategy(ABC):
    """Pluggable strategy for goal-satisfaction checks."""

    @abstractmethod
    async def evaluate(
        self,
        messages: Sequence[CommunicationMessage],
        thresholds: GoalSatisfactionThresholds,
    ) -> GoalSatisfactionAssessment:
        """Assess whether the shared goal has been satisfied."""


class ConsensusStrategy(ABC):
    """Pluggable strategy for semantic agreement during discussion rounds."""

    @abstractmethod
    async def evaluate(
        self,
        messages: Sequence[CommunicationMessage],
        thresholds: ConsensusThresholds,
    ) -> ConsensusAssessment:
        """Compare agent outputs semantically and report agreement."""


class StagnationStrategy(ABC):
    """Pluggable strategy for minimal-improvement detection."""

    @abstractmethod
    async def evaluate(
        self,
        history: Sequence[CommunicationMessage],
        thresholds: StagnationThresholds,
    ) -> StagnationAssessment:
        """Assess whether recent rounds show material improvement."""


class ConstraintEvaluationStrategy(ABC):
    """Pluggable strategy for state-based forced-stop evaluation."""

    @abstractmethod
    async def evaluate(
        self,
        state: ExecutionState,
        thresholds: ConstraintThresholds,
    ) -> ConstraintAssessment:
        """Evaluate iteration, token, or future policy constraints from state."""


class TriggerEvaluationStrategy(ABC):
    """Pluggable strategy for evaluating checkpoint trigger configurations."""

    @abstractmethod
    async def evaluate(
        self,
        configuration: CheckpointTriggerConfiguration,
        state: ExecutionState,
    ) -> TriggerEvaluationResult:
        """Evaluate user-defined triggers and decide whether heartbeat should start."""


class HeartbeatSelfCheckStrategy(ABC):
    """Pluggable strategy for agent self-check execution during heartbeat."""

    @abstractmethod
    async def evaluate(
        self,
        checkpoint_input: HeartbeatCheckpointInput,
        evidence_bundle: HeartbeatEvidenceBundle,
        state: ExecutionState,
    ) -> Sequence[HeartbeatAgentJudgment]:
        """Return independent self-check judgments from non-sleeping agents only."""


class HeartbeatDispatcherStrategy(ABC):
    """Pluggable strategy for aggregation-only heartbeat dispatch."""

    @abstractmethod
    async def evaluate(
        self,
        checkpoint_input: HeartbeatCheckpointInput,
        judgments: Sequence[HeartbeatAgentJudgment],
        thresholds: VotingThresholds,
    ) -> HeartbeatAggregateResult:
        """Aggregate judgments without reinterpretation or override."""


class VotingFallbackStrategy(ABC):
    """Pluggable strategy for checkpoint or final-answer voting evaluation."""

    @abstractmethod
    async def evaluate(
        self,
        messages: Sequence[CommunicationMessage],
        state: ExecutionState | None,
        stage: EvaluationStage,
        policy: VotingPolicy,
        thresholds: VotingThresholds,
    ) -> VotingAssessment:
        """Resolve voting structure only for allowed evaluation stages."""


class ExtensionEligibilityStrategy(ABC):
    """Pluggable strategy for extension-eligibility evaluation."""

    @abstractmethod
    async def evaluate(
        self,
        state: ExecutionState,
        conditions: ExtensionRequestConditions,
    ) -> ExtensionEligibility:
        """Assess whether an extension may be requested structurally."""


class AgentMetricsStrategy(ABC):
    """Pluggable strategy for final per-agent evaluation metrics."""

    @abstractmethod
    async def evaluate(
        self,
        history: Sequence[CommunicationMessage],
        stage: EvaluationStage,
    ) -> Sequence[AgentEvaluationMetrics]:
        """Return approval, rejection, adoption, and rationale-summary metrics."""


class ReportStrategy(ABC):
    """Pluggable strategy for final user-facing debate evaluation reports."""

    @abstractmethod
    async def build(
        self,
        decision: ConvergenceDecision,
        per_agent_metrics: Sequence[AgentEvaluationMetrics],
        minority_opinions: Sequence[MinorityOpinionRecord],
    ) -> DebateEvaluationReport:
        """Build a report that preserves diversity and summarizes vote rationales."""


class ThresholdTuningStrategy(ABC):
    """Pluggable strategy for dynamic convergence-threshold tuning."""

    @abstractmethod
    async def tune(
        self,
        profile: ConvergenceThresholdProfile,
        history: Sequence[CommunicationMessage],
        state: ExecutionState | None = None,
    ) -> ConvergenceThresholdProfile:
        """Return a tuned threshold profile for subsequent evaluation rounds."""


class ConvergenceEvaluator(ABC):
    """Abstract convergence evaluator for phased multi-agent orchestration.

    The debate evaluation mechanism distinguishes these boundaries:
    - discussion rounds: no per-response voting by default
    - heartbeat checkpoints: frozen-result self-check only, no new proposals
    - final answer evaluation: voting may occur and the final report is emitted
    - extension handling: structural extension review only

    Heartbeat entry is controlled by generic checkpoint triggers. Multiple
    triggers may coexist and use OR semantics, so any firing trigger is
    sufficient to move the system into a heartbeat checkpoint.

    During heartbeat:
    - the current discussion result is frozen before evaluation begins
    - non-sleeping agents run self-checks in parallel and independently
    - agents compare the frozen result against the original task goal
    - agents vote using binary approve or reject judgments only
    - every vote includes a short, diagnostic rationale
    - approve rationale explains why the current result is sufficient
    - reject rationale identifies the main deficiency category
    - agents must not propose new solution content
    - the dispatcher aggregates only and does not reinterpret judgments

    Convergence is defined structurally as a combination of:
    - goal satisfaction
    - improvement stagnation
    - voting-threshold outcome in stages where voting is permitted

    Final reports are expected whether convergence succeeds or fails. They must
    include per-agent approval rate, rejection rate, and concise rationale
    history summaries while preserving minority opinions for the user.
    """

    @abstractmethod
    async def evaluate_goal_satisfaction(
        self,
        messages: Sequence[CommunicationMessage],
    ) -> GoalSatisfactionAssessment:
        """Evaluate whether current outputs satisfy the shared goal."""

    @abstractmethod
    async def evaluate_consensus(
        self,
        messages: Sequence[CommunicationMessage],
    ) -> ConsensusAssessment:
        """Evaluate semantic agreement across the provided outputs."""

    @abstractmethod
    async def evaluate_stagnation(
        self,
        history: Sequence[CommunicationMessage],
    ) -> StagnationAssessment:
        """Evaluate whether recent rounds have materially improved."""

    @abstractmethod
    async def evaluate_constraints(
        self,
        state: ExecutionState,
    ) -> ConstraintAssessment:
        """Evaluate whether orchestration state requires a forced stop."""

    @abstractmethod
    async def evaluate_checkpoint_triggers(
        self,
        state: ExecutionState,
    ) -> TriggerEvaluationResult:
        """Evaluate configured triggers and decide whether heartbeat should start."""

    @abstractmethod
    async def evaluate_heartbeat_checkpoint(
        self,
        checkpoint_input: HeartbeatCheckpointInput,
        evidence_bundle: HeartbeatEvidenceBundle,
        state: ExecutionState,
    ) -> HeartbeatCheckpointAssessment:
        """Evaluate the frozen result through heartbeat self-check and aggregation."""

    @abstractmethod
    async def evaluate_voting(
        self,
        messages: Sequence[CommunicationMessage],
        stage: EvaluationStage,
        state: ExecutionState | None = None,
    ) -> VotingAssessment:
        """Evaluate voting only in the configured checkpoint or final stage."""

    @abstractmethod
    async def evaluate_extension_eligibility(
        self,
        state: ExecutionState,
    ) -> ExtensionEligibility:
        """Evaluate whether an extension may be requested structurally."""

    @abstractmethod
    async def build_final_report(
        self,
        decision: ConvergenceDecision,
        per_agent_metrics: Sequence[AgentEvaluationMetrics],
        minority_opinions: Sequence[MinorityOpinionRecord],
    ) -> DebateEvaluationReport:
        """Build the final report for the user regardless of outcome."""

    @abstractmethod
    async def evaluate(
        self,
        messages: Sequence[CommunicationMessage],
        history: Sequence[CommunicationMessage],
        state: ExecutionState,
        phase: CoordinationPhase = CoordinationPhase.TERMINATION_EXTENSION_HANDLING,
        stage: EvaluationStage = EvaluationStage.FINAL_ANSWER_EVALUATION,
    ) -> ConvergenceDecision:
        """Return continue, converged, or forced_stop for the current stage."""
