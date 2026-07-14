from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from agent_os.orchestrator.convergence import (
    ConvergenceStatus,
    HeartbeatAggregateArtifact,
    HeartbeatAggregateResult,
)
from agent_os.orchestrator.heartbeat_candidate_snapshot import (
    HeartbeatCandidateSnapshot,
    assert_heartbeat_candidate_snapshot_matches_aggregate,
    assert_matching_heartbeat_candidate_snapshots,
)
from agent_os.orchestrator.heartbeat_convergence_profile import (
    HeartbeatConvergenceProfile,
    HeartbeatConvergenceReservationLevel,
    HeartbeatConvergenceSemanticState,
    assert_matching_heartbeat_convergence_profiles,
)
from agent_os.orchestrator.heartbeat_outcome_snapshot import (
    HeartbeatOutcomeConsumerReadiness,
    HeartbeatOutcomeSnapshot,
    assert_heartbeat_outcome_matches_aggregate,
    assert_matching_heartbeat_outcome_snapshots,
)

_CONTINUE_STATES = frozenset(
    {
        HeartbeatConvergenceSemanticState.BLOCKED_BY_BLOCKER,
        HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_UNRESOLVED_GAP,
        HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_MULTI_ROLE_DISSENT,
        HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_VALIDATION_OR_EVIDENCE_GAP,
        HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_INSUFFICIENT_SUPPORT,
    }
)
_CONVERGED_STATES = frozenset(
    {
        HeartbeatConvergenceSemanticState.CONVERGED_CLEAN,
        HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS,
        HeartbeatConvergenceSemanticState.CONVERGED_WITH_RECORDED_DISSENT,
    }
)


@dataclass(frozen=True, slots=True)
class HeartbeatCandidatePresentation:
    """Stable human-consumption view layered on top of explicit heartbeat objects."""

    candidate_id: str
    checkpoint_id: str
    summary: str
    source_round: int | None = None
    supporting_context_refs: tuple[str, ...] = ()
    final_decision: ConvergenceStatus = ConvergenceStatus.CONTINUE
    semantic_state: HeartbeatConvergenceSemanticState = (
        HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_INSUFFICIENT_SUPPORT
    )
    reservation_level: HeartbeatConvergenceReservationLevel = (
        HeartbeatConvergenceReservationLevel.NONE
    )
    consumer_readiness: HeartbeatOutcomeConsumerReadiness = (
        HeartbeatOutcomeConsumerReadiness.CONTINUE_ONLY
    )
    retained_issue_preview: str | None = None
    next_step_preview: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        candidate_id = str(self.candidate_id).strip()
        if not candidate_id:
            raise ValueError("Heartbeat candidate presentation requires candidate_id.")
        checkpoint_id = str(self.checkpoint_id).strip()
        if not checkpoint_id:
            raise ValueError("Heartbeat candidate presentation requires checkpoint_id.")
        summary = str(self.summary).strip()
        if not summary:
            raise ValueError("Heartbeat candidate presentation requires a non-empty summary.")
        source_round = None if self.source_round is None else int(self.source_round)
        retained_issue_preview = _normalize_optional_text(self.retained_issue_preview)
        next_step_preview = _normalize_optional_text(self.next_step_preview)
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "checkpoint_id", checkpoint_id)
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "source_round", source_round)
        object.__setattr__(
            self,
            "supporting_context_refs",
            _normalize_context_refs(self.supporting_context_refs),
        )
        object.__setattr__(
            self,
            "final_decision",
            _coerce_enum(
                ConvergenceStatus,
                self.final_decision,
                field_name="final_decision",
            ),
        )
        object.__setattr__(
            self,
            "semantic_state",
            _coerce_enum(
                HeartbeatConvergenceSemanticState,
                self.semantic_state,
                field_name="semantic_state",
            ),
        )
        object.__setattr__(
            self,
            "reservation_level",
            _coerce_enum(
                HeartbeatConvergenceReservationLevel,
                self.reservation_level,
                field_name="reservation_level",
            ),
        )
        object.__setattr__(
            self,
            "consumer_readiness",
            _coerce_enum(
                HeartbeatOutcomeConsumerReadiness,
                self.consumer_readiness,
                field_name="consumer_readiness",
            ),
        )
        object.__setattr__(self, "retained_issue_preview", retained_issue_preview)
        object.__setattr__(self, "next_step_preview", next_step_preview)
        validate_heartbeat_candidate_presentation(self)


def build_heartbeat_candidate_presentation(
    aggregate: HeartbeatAggregateResult | HeartbeatAggregateArtifact,
    *,
    candidate_snapshot: HeartbeatCandidateSnapshot | None = None,
    convergence_profile: HeartbeatConvergenceProfile | None = None,
    outcome_snapshot: HeartbeatOutcomeSnapshot | None = None,
) -> HeartbeatCandidatePresentation:
    """Build one controlled candidate presentation from attached heartbeat objects."""

    artifact, aggregate_result = _resolve_aggregate_inputs(aggregate)
    _assert_explicit_object_reuse(
        explicit_object=candidate_snapshot,
        artifact_object=artifact.candidate_snapshot,
        result_object=aggregate_result.candidate_snapshot if aggregate_result is not None else None,
        object_label="candidate_snapshot",
    )
    _assert_explicit_object_reuse(
        explicit_object=convergence_profile,
        artifact_object=artifact.convergence_profile,
        result_object=aggregate_result.convergence_profile if aggregate_result is not None else None,
        object_label="convergence_profile",
    )
    _assert_explicit_object_reuse(
        explicit_object=outcome_snapshot,
        artifact_object=artifact.outcome_snapshot,
        result_object=aggregate_result.outcome_snapshot if aggregate_result is not None else None,
        object_label="outcome_snapshot",
    )
    resolved_candidate_snapshot = assert_matching_heartbeat_candidate_snapshots(
        candidate_snapshot,
        artifact.candidate_snapshot,
        aggregate_result.candidate_snapshot if aggregate_result is not None else None,
    )
    if resolved_candidate_snapshot is None:
        raise ValueError(
            "Heartbeat candidate presentation requires candidate_snapshot from explicit input "
            "or an attached aggregate object."
        )
    resolved_profile = assert_matching_heartbeat_convergence_profiles(
        convergence_profile,
        artifact.convergence_profile,
        aggregate_result.convergence_profile if aggregate_result is not None else None,
    )
    if resolved_profile is None:
        raise ValueError(
            "Heartbeat candidate presentation requires convergence_profile from explicit input "
            "or an attached aggregate object."
        )
    resolved_outcome = assert_matching_heartbeat_outcome_snapshots(
        outcome_snapshot,
        artifact.outcome_snapshot,
        aggregate_result.outcome_snapshot if aggregate_result is not None else None,
    )
    if resolved_outcome is None:
        raise ValueError(
            "Heartbeat candidate presentation requires outcome_snapshot from explicit input "
            "or an attached aggregate object."
        )
    presentation = HeartbeatCandidatePresentation(
        candidate_id=resolved_candidate_snapshot.candidate_id,
        checkpoint_id=resolved_candidate_snapshot.checkpoint_id,
        summary=resolved_candidate_snapshot.summary,
        source_round=resolved_candidate_snapshot.source_round,
        supporting_context_refs=resolved_candidate_snapshot.supporting_context_refs,
        final_decision=resolved_outcome.final_decision,
        semantic_state=resolved_profile.semantic_state,
        reservation_level=resolved_profile.reservation_level,
        consumer_readiness=resolved_outcome.consumer_readiness,
        retained_issue_preview=_build_retained_issue_preview(resolved_outcome),
        next_step_preview=_build_next_step_preview(artifact),
        metadata={
            "source_view_kind": "heartbeat_candidate_snapshot",
            "supporting_context_ref_count": len(
                resolved_candidate_snapshot.supporting_context_refs
            ),
            "decision_rationale_count": len(artifact.decision_rationale),
            "recommended_next_action_count": len(artifact.recommended_next_actions),
        },
    )
    assert_heartbeat_candidate_presentation_matches_aggregate(
        presentation=presentation,
        artifact=artifact,
        aggregate_result=aggregate_result,
    )
    return presentation


def validate_heartbeat_candidate_presentation(
    presentation: HeartbeatCandidatePresentation,
) -> None:
    """Validate one candidate presentation contract."""

    if not isinstance(presentation, HeartbeatCandidatePresentation):
        raise TypeError(
            "Heartbeat candidate presentation validation requires "
            "HeartbeatCandidatePresentation."
        )
    if presentation.final_decision == ConvergenceStatus.CONTINUE:
        if presentation.semantic_state not in _CONTINUE_STATES:
            raise ValueError(
                "Continue candidate presentations must use a continue semantic_state."
            )
        if presentation.consumer_readiness not in {
            HeartbeatOutcomeConsumerReadiness.CONTINUE_ONLY,
            HeartbeatOutcomeConsumerReadiness.REMEDIATION_REQUIRED,
        }:
            raise ValueError(
                "Continue candidate presentations must use a non-terminal consumer_readiness."
            )
    elif presentation.final_decision == ConvergenceStatus.CONVERGED:
        if presentation.semantic_state not in _CONVERGED_STATES:
            raise ValueError(
                "Converged candidate presentations must use a converged semantic_state."
            )
        if presentation.consumer_readiness not in {
            HeartbeatOutcomeConsumerReadiness.TERMINAL_READY,
            HeartbeatOutcomeConsumerReadiness.TERMINAL_READY_WITH_RESERVATIONS,
        }:
            raise ValueError(
                "Converged candidate presentations must use a terminal consumer_readiness."
            )
    if (
        presentation.consumer_readiness
        == HeartbeatOutcomeConsumerReadiness.TERMINAL_READY
        and presentation.semantic_state
        != HeartbeatConvergenceSemanticState.CONVERGED_CLEAN
    ):
        raise ValueError(
            "terminal_ready candidate presentations must use converged_clean semantics."
        )
    if (
        presentation.consumer_readiness
        == HeartbeatOutcomeConsumerReadiness.TERMINAL_READY
        and presentation.retained_issue_preview is not None
    ):
        raise ValueError(
            "terminal_ready candidate presentations must not expose retained_issue_preview."
        )
    if (
        presentation.consumer_readiness
        != HeartbeatOutcomeConsumerReadiness.TERMINAL_READY
        and presentation.retained_issue_preview is None
    ):
        raise ValueError(
            "Non-clean candidate presentations must expose retained_issue_preview."
        )


def assert_matching_heartbeat_candidate_presentations(
    *presentations: HeartbeatCandidatePresentation | None,
    require_all_or_none: bool = False,
) -> HeartbeatCandidatePresentation | None:
    """Validate and reconcile candidate presentation references that should agree."""

    present_presentations = tuple(
        presentation for presentation in presentations if presentation is not None
    )
    if (
        require_all_or_none
        and present_presentations
        and len(present_presentations) != len(presentations)
    ):
        raise ValueError(
            "Heartbeat candidate presentation references must either all be present or all be absent."
        )
    if not present_presentations:
        return None

    canonical_presentation = present_presentations[0]
    validate_heartbeat_candidate_presentation(canonical_presentation)
    for presentation in present_presentations[1:]:
        validate_heartbeat_candidate_presentation(presentation)
        if presentation is not canonical_presentation:
            raise ValueError(
                "Heartbeat candidate presentation references must reuse the same object instance."
            )
        if presentation != canonical_presentation:
            raise ValueError(
                "Heartbeat candidate presentation references must agree exactly."
            )
    return canonical_presentation


def assert_heartbeat_candidate_presentation_matches_aggregate(
    *,
    presentation: HeartbeatCandidatePresentation,
    artifact: HeartbeatAggregateArtifact,
    aggregate_result: HeartbeatAggregateResult | None = None,
) -> None:
    """Assert that one candidate presentation matches the canonical aggregate objects."""

    validate_heartbeat_candidate_presentation(presentation)
    attached_presentation = assert_matching_heartbeat_candidate_presentations(
        artifact.candidate_presentation,
        aggregate_result.candidate_presentation if aggregate_result is not None else None,
        require_all_or_none=aggregate_result is not None,
    )
    if attached_presentation is not None and attached_presentation is not presentation:
        raise ValueError(
            "Heartbeat candidate presentation must match the attached aggregate candidate_presentation."
        )
    resolved_candidate_snapshot = assert_matching_heartbeat_candidate_snapshots(
        artifact.candidate_snapshot,
        aggregate_result.candidate_snapshot if aggregate_result is not None else None,
        require_all_or_none=aggregate_result is not None,
    )
    resolved_profile = assert_matching_heartbeat_convergence_profiles(
        artifact.convergence_profile,
        aggregate_result.convergence_profile if aggregate_result is not None else None,
        require_all_or_none=aggregate_result is not None,
    )
    resolved_outcome = assert_matching_heartbeat_outcome_snapshots(
        artifact.outcome_snapshot,
        aggregate_result.outcome_snapshot if aggregate_result is not None else None,
        require_all_or_none=aggregate_result is not None,
    )
    if resolved_candidate_snapshot is None:
        raise ValueError(
            "Heartbeat candidate presentation requires aggregate candidate_snapshot."
        )
    if resolved_profile is None:
        raise ValueError(
            "Heartbeat candidate presentation requires aggregate convergence_profile."
        )
    if resolved_outcome is None:
        raise ValueError(
            "Heartbeat candidate presentation requires aggregate outcome_snapshot."
        )
    assert_heartbeat_candidate_snapshot_matches_aggregate(
        snapshot=resolved_candidate_snapshot,
        artifact=artifact,
        aggregate_result=aggregate_result,
    )
    assert_heartbeat_outcome_matches_aggregate(
        snapshot=resolved_outcome,
        artifact=artifact,
        aggregate_result=aggregate_result,
    )
    if presentation.candidate_id != resolved_candidate_snapshot.candidate_id:
        raise ValueError(
            "Heartbeat candidate presentation candidate_id must reuse candidate_snapshot."
        )
    if presentation.checkpoint_id != resolved_candidate_snapshot.checkpoint_id:
        raise ValueError(
            "Heartbeat candidate presentation checkpoint_id must reuse candidate_snapshot."
        )
    if presentation.summary != resolved_candidate_snapshot.summary:
        raise ValueError(
            "Heartbeat candidate presentation summary must reuse candidate_snapshot."
        )
    if presentation.source_round != resolved_candidate_snapshot.source_round:
        raise ValueError(
            "Heartbeat candidate presentation source_round must reuse candidate_snapshot."
        )
    if (
        presentation.supporting_context_refs
        != resolved_candidate_snapshot.supporting_context_refs
    ):
        raise ValueError(
            "Heartbeat candidate presentation supporting_context_refs must reuse candidate_snapshot."
        )
    if presentation.final_decision != resolved_outcome.final_decision:
        raise ValueError(
            "Heartbeat candidate presentation final_decision must reuse outcome_snapshot."
        )
    if presentation.final_decision != artifact.final_decision:
        raise ValueError(
            "Heartbeat candidate presentation final_decision must match aggregate artifact."
        )
    if (
        aggregate_result is not None
        and presentation.final_decision != aggregate_result.recommended_outcome
    ):
        raise ValueError(
            "Heartbeat candidate presentation final_decision must match aggregate result."
        )
    if presentation.semantic_state != resolved_profile.semantic_state:
        raise ValueError(
            "Heartbeat candidate presentation semantic_state must reuse convergence_profile."
        )
    if presentation.reservation_level != resolved_profile.reservation_level:
        raise ValueError(
            "Heartbeat candidate presentation reservation_level must reuse convergence_profile."
        )
    if presentation.consumer_readiness != resolved_outcome.consumer_readiness:
        raise ValueError(
            "Heartbeat candidate presentation consumer_readiness must reuse outcome_snapshot."
        )
    expected_retained_issue_preview = _build_retained_issue_preview(resolved_outcome)
    if presentation.retained_issue_preview != expected_retained_issue_preview:
        raise ValueError(
            "Heartbeat candidate presentation retained_issue_preview must match the controlled retained-item preview."
        )
    expected_next_step_preview = _build_next_step_preview(artifact)
    if presentation.next_step_preview != expected_next_step_preview:
        raise ValueError(
            "Heartbeat candidate presentation next_step_preview must match the aggregate next-action projection."
        )


def _resolve_aggregate_inputs(
    aggregate: HeartbeatAggregateResult | HeartbeatAggregateArtifact,
) -> tuple[HeartbeatAggregateArtifact, HeartbeatAggregateResult | None]:
    if isinstance(aggregate, HeartbeatAggregateResult):
        if aggregate.aggregate_artifact is None:
            raise ValueError(
                "Heartbeat candidate presentation requires aggregate_result.aggregate_artifact."
            )
        return aggregate.aggregate_artifact, aggregate
    if isinstance(aggregate, HeartbeatAggregateArtifact):
        return aggregate, None
    raise TypeError(
        "Heartbeat candidate presentation input must be HeartbeatAggregateResult "
        "or HeartbeatAggregateArtifact."
    )


def _build_retained_issue_preview(outcome_snapshot: HeartbeatOutcomeSnapshot) -> str | None:
    if outcome_snapshot.top_retained_items:
        top_item = outcome_snapshot.top_retained_items[0]
        if top_item.summary:
            return top_item.summary
        severity_label = top_item.severity or "unspecified"
        blocker_label = " blocker" if top_item.blocker else ""
        return f"{top_item.category.value} ({severity_label}{blocker_label})"
    return outcome_snapshot.reservation_summary


def _build_next_step_preview(artifact: HeartbeatAggregateArtifact) -> str | None:
    if not artifact.recommended_next_actions:
        return None
    return _normalize_optional_text(artifact.recommended_next_actions[0])


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized_value = str(value).strip()
    return normalized_value or None


def _normalize_context_refs(values: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized_value = str(value).strip()
        if not normalized_value or normalized_value in seen:
            continue
        seen.add(normalized_value)
        normalized.append(normalized_value)
    return tuple(normalized)


def _assert_explicit_object_reuse(
    *,
    explicit_object: object | None,
    artifact_object: object | None,
    result_object: object | None,
    object_label: str,
) -> None:
    if explicit_object is None:
        return
    for attached_object in (artifact_object, result_object):
        if attached_object is None:
            continue
        if explicit_object is not attached_object:
            raise ValueError(
                "Heartbeat candidate presentation explicit "
                f"{object_label} must reuse the attached aggregate object."
            )


def _coerce_enum(enum_type, value: object, *, field_name: str):
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value))
    except Exception as exc:
        raise ValueError(
            "Heartbeat candidate presentation "
            f"{field_name} must use the canonical {enum_type.__name__} vocabulary."
        ) from exc
