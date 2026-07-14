from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from agent_os.orchestrator.convergence import (
    ConvergenceStatus,
    HeartbeatAggregateArtifact,
    HeartbeatAggregateResult,
    HeartbeatDissentItem,
    RejectionDeficiencyCategory,
)
from agent_os.orchestrator.heartbeat_grading_contract import canonicalize_heartbeat_severity

_HIGH_PRIORITY_SEVERITIES = frozenset({"critical", "major"})


class HeartbeatConvergenceSemanticState(StrEnum):
    """Stable semantic labels derived from canonical heartbeat aggregation."""

    BLOCKED_BY_BLOCKER = "blocked_by_blocker"
    CONTINUE_DUE_TO_UNRESOLVED_GAP = "continue_due_to_unresolved_gap"
    CONTINUE_DUE_TO_MULTI_ROLE_DISSENT = "continue_due_to_multi_role_dissent"
    CONTINUE_DUE_TO_VALIDATION_OR_EVIDENCE_GAP = "continue_due_to_validation_or_evidence_gap"
    CONTINUE_DUE_TO_INSUFFICIENT_SUPPORT = "continue_due_to_insufficient_support"
    CONVERGED_CLEAN = "converged_clean"
    CONVERGED_WITH_RESERVATIONS = "converged_with_reservations"
    CONVERGED_WITH_RECORDED_DISSENT = "converged_with_recorded_dissent"


class HeartbeatConvergenceDominantReason(StrEnum):
    """Stable dominant-reason vocabulary for convergence profile consumers."""

    BLOCKER_PRESENT = "blocker_present"
    CRITICAL_OR_MAJOR_GAP = "critical_or_major_gap"
    UNRESOLVED_GAP = "unresolved_gap"
    MULTI_ROLE_DISSENT = "multi_role_dissent"
    EVIDENCE_GAP = "evidence_gap"
    VALIDATION_GAP = "validation_gap"
    MINORITY_DISSENT_RETAINED = "minority_dissent_retained"
    NO_MATERIAL_RESERVATIONS = "no_material_reservations"
    INSUFFICIENT_APPROVAL_SUPPORT = "insufficient_approval_support"


class HeartbeatConvergenceReservationLevel(StrEnum):
    """Compact reservation levels surfaced to higher-layer consumers."""

    NONE = "none"
    RECORDED = "recorded"
    ELEVATED = "elevated"
    BLOCKING = "blocking"


class HeartbeatConvergenceFollowupBias(StrEnum):
    """Small follow-up bias vocabulary derived from aggregate semantics."""

    RESOLVE_BLOCKERS = "resolve_blockers"
    CLOSE_UNRESOLVED_GAPS = "close_unresolved_gaps"
    COLLECT_VALIDATION_EVIDENCE = "collect_validation_evidence"
    CARRY_FORWARD_RESERVATIONS = "carry_forward_reservations"
    PREPARE_TERMINAL_OUTPUT = "prepare_terminal_output"
    COLLECT_FRESH_JUDGMENTS = "collect_fresh_judgments"


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
_STATE_ALLOWED_REASONS = {
    HeartbeatConvergenceSemanticState.BLOCKED_BY_BLOCKER: frozenset(
        {HeartbeatConvergenceDominantReason.BLOCKER_PRESENT}
    ),
    HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_UNRESOLVED_GAP: frozenset(
        {
            HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP,
            HeartbeatConvergenceDominantReason.UNRESOLVED_GAP,
        }
    ),
    HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_MULTI_ROLE_DISSENT: frozenset(
        {HeartbeatConvergenceDominantReason.MULTI_ROLE_DISSENT}
    ),
    HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_VALIDATION_OR_EVIDENCE_GAP: frozenset(
        {
            HeartbeatConvergenceDominantReason.EVIDENCE_GAP,
            HeartbeatConvergenceDominantReason.VALIDATION_GAP,
        }
    ),
    HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_INSUFFICIENT_SUPPORT: frozenset(
        {HeartbeatConvergenceDominantReason.INSUFFICIENT_APPROVAL_SUPPORT}
    ),
    HeartbeatConvergenceSemanticState.CONVERGED_CLEAN: frozenset(
        {HeartbeatConvergenceDominantReason.NO_MATERIAL_RESERVATIONS}
    ),
    HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS: frozenset(
        {
            HeartbeatConvergenceDominantReason.BLOCKER_PRESENT,
            HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP,
            HeartbeatConvergenceDominantReason.EVIDENCE_GAP,
            HeartbeatConvergenceDominantReason.VALIDATION_GAP,
        }
    ),
    HeartbeatConvergenceSemanticState.CONVERGED_WITH_RECORDED_DISSENT: frozenset(
        {HeartbeatConvergenceDominantReason.MINORITY_DISSENT_RETAINED}
    ),
}
_STATE_ALLOWED_RESERVATION_LEVELS = {
    HeartbeatConvergenceSemanticState.BLOCKED_BY_BLOCKER: frozenset(
        {HeartbeatConvergenceReservationLevel.BLOCKING}
    ),
    HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_UNRESOLVED_GAP: frozenset(
        {
            HeartbeatConvergenceReservationLevel.RECORDED,
            HeartbeatConvergenceReservationLevel.ELEVATED,
        }
    ),
    HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_MULTI_ROLE_DISSENT: frozenset(
        {
            HeartbeatConvergenceReservationLevel.RECORDED,
            HeartbeatConvergenceReservationLevel.ELEVATED,
        }
    ),
    HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_VALIDATION_OR_EVIDENCE_GAP: frozenset(
        {
            HeartbeatConvergenceReservationLevel.RECORDED,
            HeartbeatConvergenceReservationLevel.ELEVATED,
        }
    ),
    HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_INSUFFICIENT_SUPPORT: frozenset(
        {HeartbeatConvergenceReservationLevel.NONE}
    ),
    HeartbeatConvergenceSemanticState.CONVERGED_CLEAN: frozenset(
        {HeartbeatConvergenceReservationLevel.NONE}
    ),
    HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS: frozenset(
        {
            HeartbeatConvergenceReservationLevel.ELEVATED,
            HeartbeatConvergenceReservationLevel.BLOCKING,
        }
    ),
    HeartbeatConvergenceSemanticState.CONVERGED_WITH_RECORDED_DISSENT: frozenset(
        {HeartbeatConvergenceReservationLevel.RECORDED}
    ),
}
_STATE_ALLOWED_FOLLOWUP_BIASES = {
    HeartbeatConvergenceSemanticState.BLOCKED_BY_BLOCKER: frozenset(
        {HeartbeatConvergenceFollowupBias.RESOLVE_BLOCKERS}
    ),
    HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_UNRESOLVED_GAP: frozenset(
        {HeartbeatConvergenceFollowupBias.CLOSE_UNRESOLVED_GAPS}
    ),
    HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_MULTI_ROLE_DISSENT: frozenset(
        {HeartbeatConvergenceFollowupBias.CLOSE_UNRESOLVED_GAPS}
    ),
    HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_VALIDATION_OR_EVIDENCE_GAP: frozenset(
        {HeartbeatConvergenceFollowupBias.COLLECT_VALIDATION_EVIDENCE}
    ),
    HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_INSUFFICIENT_SUPPORT: frozenset(
        {HeartbeatConvergenceFollowupBias.COLLECT_FRESH_JUDGMENTS}
    ),
    HeartbeatConvergenceSemanticState.CONVERGED_CLEAN: frozenset(
        {HeartbeatConvergenceFollowupBias.PREPARE_TERMINAL_OUTPUT}
    ),
    HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS: frozenset(
        {HeartbeatConvergenceFollowupBias.CARRY_FORWARD_RESERVATIONS}
    ),
    HeartbeatConvergenceSemanticState.CONVERGED_WITH_RECORDED_DISSENT: frozenset(
        {HeartbeatConvergenceFollowupBias.CARRY_FORWARD_RESERVATIONS}
    ),
}


@dataclass(frozen=True, slots=True)
class HeartbeatConvergenceProfile:
    """Derived semantic profile layered on top of canonical aggregate objects."""

    final_decision: ConvergenceStatus
    semantic_state: HeartbeatConvergenceSemanticState
    dominant_reason: HeartbeatConvergenceDominantReason
    has_blocker: bool = False
    highest_rejection_severity: str | None = None
    unresolved_high_priority_count: int = 0
    minority_high_priority_count: int = 0
    reservation_level: HeartbeatConvergenceReservationLevel = (
        HeartbeatConvergenceReservationLevel.NONE
    )
    explanation_summary: str = ""
    followup_bias: HeartbeatConvergenceFollowupBias = (
        HeartbeatConvergenceFollowupBias.PREPARE_TERMINAL_OUTPUT
    )
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
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
            "dominant_reason",
            _coerce_enum(
                HeartbeatConvergenceDominantReason,
                self.dominant_reason,
                field_name="dominant_reason",
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
            "followup_bias",
            _coerce_enum(
                HeartbeatConvergenceFollowupBias,
                self.followup_bias,
                field_name="followup_bias",
            ),
        )
        object.__setattr__(
            self,
            "highest_rejection_severity",
            canonicalize_heartbeat_severity(self.highest_rejection_severity),
        )
        object.__setattr__(self, "has_blocker", bool(self.has_blocker))
        unresolved_count = int(self.unresolved_high_priority_count or 0)
        minority_count = int(self.minority_high_priority_count or 0)
        if unresolved_count < 0 or minority_count < 0:
            raise ValueError("Heartbeat convergence profile counts must be non-negative.")
        object.__setattr__(self, "unresolved_high_priority_count", unresolved_count)
        object.__setattr__(self, "minority_high_priority_count", minority_count)
        validate_heartbeat_convergence_profile(self)


def validate_heartbeat_convergence_profile(profile: HeartbeatConvergenceProfile) -> None:
    """Validate the stable contract for one derived convergence profile."""

    if profile.final_decision == ConvergenceStatus.CONTINUE:
        if profile.semantic_state not in _CONTINUE_STATES:
            raise ValueError("Continue profiles must use a continue semantic_state.")
    elif profile.final_decision == ConvergenceStatus.CONVERGED:
        if profile.semantic_state not in _CONVERGED_STATES:
            raise ValueError("Converged profiles must use a converged semantic_state.")

    allowed_reasons = _STATE_ALLOWED_REASONS[profile.semantic_state]
    if profile.dominant_reason not in allowed_reasons:
        raise ValueError(
            "Heartbeat convergence profile dominant_reason must be compatible with "
            "semantic_state."
        )
    allowed_reservation_levels = _STATE_ALLOWED_RESERVATION_LEVELS[profile.semantic_state]
    if profile.reservation_level not in allowed_reservation_levels:
        raise ValueError(
            "Heartbeat convergence profile reservation_level must be compatible with "
            "semantic_state."
        )
    allowed_followup_biases = _STATE_ALLOWED_FOLLOWUP_BIASES[profile.semantic_state]
    if profile.followup_bias not in allowed_followup_biases:
        raise ValueError(
            "Heartbeat convergence profile followup_bias must be compatible with "
            "semantic_state."
        )

    retained_high_priority_count = _profile_retained_high_priority_count(profile)
    retained_item_count = _profile_metadata_count(profile, "retained_item_count")
    retained_high_priority_hint = _profile_metadata_count(profile, "retained_high_priority_count")
    if (
        retained_high_priority_hint is not None
        and retained_high_priority_hint < retained_high_priority_count
    ):
        raise ValueError(
            "Heartbeat convergence profile retained_high_priority_count metadata must not "
            "undercount explicit high-priority item counts."
        )

    if profile.semantic_state == HeartbeatConvergenceSemanticState.BLOCKED_BY_BLOCKER:
        if not profile.has_blocker:
            raise ValueError("blocked_by_blocker profiles must declare has_blocker=True.")
        if profile.unresolved_high_priority_count <= 0:
            raise ValueError(
                "blocked_by_blocker profiles must retain at least one unresolved high-priority item."
            )

    if profile.semantic_state == HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_INSUFFICIENT_SUPPORT:
        if profile.has_blocker:
            raise ValueError(
                "continue_due_to_insufficient_support profiles must not carry blocker semantics."
            )
        if retained_high_priority_count != 0:
            raise ValueError(
                "continue_due_to_insufficient_support profiles must not retain high-priority items."
            )
        if retained_item_count not in {None, 0}:
            raise ValueError(
                "continue_due_to_insufficient_support profiles must not report retained items."
            )

    if (
        profile.semantic_state
        == HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_VALIDATION_OR_EVIDENCE_GAP
        and profile.dominant_reason
        not in {
            HeartbeatConvergenceDominantReason.EVIDENCE_GAP,
            HeartbeatConvergenceDominantReason.VALIDATION_GAP,
        }
    ):
        raise ValueError(
            "continue_due_to_validation_or_evidence_gap profiles must use an evidence- or "
            "validation-gap dominant_reason."
        )

    if profile.semantic_state in {
        HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_UNRESOLVED_GAP,
        HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_MULTI_ROLE_DISSENT,
        HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_VALIDATION_OR_EVIDENCE_GAP,
    } and profile.has_blocker:
        raise ValueError(
            "Non-blocker continue profile states must not declare has_blocker=True."
        )

    if profile.semantic_state == HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_UNRESOLVED_GAP:
        if (
            profile.dominant_reason
            == HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP
            and profile.unresolved_high_priority_count <= 0
        ):
            raise ValueError(
                "continue_due_to_unresolved_gap with critical_or_major_gap must retain "
                "an unresolved high-priority item."
            )
        if (
            profile.dominant_reason == HeartbeatConvergenceDominantReason.UNRESOLVED_GAP
            and profile.unresolved_high_priority_count != 0
        ):
            raise ValueError(
                "continue_due_to_unresolved_gap with unresolved_gap must not claim unresolved "
                "high-priority items."
            )

    if profile.semantic_state == HeartbeatConvergenceSemanticState.CONVERGED_CLEAN:
        if profile.has_blocker or retained_high_priority_count != 0:
            raise ValueError(
                "converged_clean profiles must not retain blocker semantics or high-priority items."
            )
        if retained_item_count not in {None, 0}:
            raise ValueError("converged_clean profiles must not report retained items.")

    if profile.semantic_state == HeartbeatConvergenceSemanticState.CONVERGED_WITH_RECORDED_DISSENT:
        if profile.has_blocker or retained_high_priority_count != 0:
            raise ValueError(
                "converged_with_recorded_dissent profiles must not retain blocker or high-priority semantics."
            )
        if retained_item_count == 0:
            raise ValueError(
                "converged_with_recorded_dissent profiles must report retained dissent."
            )

    if profile.semantic_state == HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS:
        if not profile.has_blocker and retained_high_priority_count == 0:
            raise ValueError(
                "converged_with_reservations profiles must retain blocker or high-priority reservations."
            )
        if (
            profile.dominant_reason == HeartbeatConvergenceDominantReason.BLOCKER_PRESENT
            and not profile.has_blocker
        ):
            raise ValueError(
                "converged_with_reservations with blocker_present must declare has_blocker=True."
            )
        if (
            profile.dominant_reason
            != HeartbeatConvergenceDominantReason.BLOCKER_PRESENT
            and retained_high_priority_count == 0
        ):
            raise ValueError(
                "converged_with_reservations without blocker_present must retain high-priority reservations."
            )


def assert_matching_heartbeat_convergence_profiles(
    *profiles: HeartbeatConvergenceProfile | None,
    require_all_or_none: bool = False,
) -> HeartbeatConvergenceProfile | None:
    """Validate and reconcile one or more profile references that should agree."""

    present_profiles = tuple(profile for profile in profiles if profile is not None)
    if require_all_or_none and present_profiles and len(present_profiles) != len(profiles):
        raise ValueError(
            "Heartbeat convergence profile references must either all be present or all be absent."
        )
    if not present_profiles:
        return None

    canonical_profile = present_profiles[0]
    validate_heartbeat_convergence_profile(canonical_profile)
    for profile in present_profiles[1:]:
        validate_heartbeat_convergence_profile(profile)
        if profile is not canonical_profile:
            raise ValueError(
                "Heartbeat convergence profile references must reuse the same object instance."
            )
        if profile != canonical_profile:
            raise ValueError("Heartbeat convergence profile references must agree exactly.")
    return canonical_profile


def build_heartbeat_convergence_profile(
    aggregate: HeartbeatAggregateResult | HeartbeatAggregateArtifact,
) -> HeartbeatConvergenceProfile:
    """Build a stable semantic convergence profile from canonical aggregate outputs."""

    artifact, aggregate_result = _resolve_aggregate_inputs(aggregate)
    total_judgments = _resolve_total_judgments(artifact, aggregate_result)
    final_decision = (
        aggregate_result.recommended_outcome if aggregate_result is not None else artifact.final_decision
    )
    highest_rejection_severity = canonicalize_heartbeat_severity(
        aggregate_result.highest_rejection_severity
        if aggregate_result is not None
        else artifact.highest_rejection_severity
    )
    unresolved_items = _filter_non_sufficient_items(artifact.unresolved_items)
    minority_items = _filter_non_sufficient_items(artifact.minority_items)
    unresolved_high_priority_items = tuple(
        item for item in unresolved_items if _item_is_high_priority(item)
    )
    minority_high_priority_items = tuple(item for item in minority_items if _item_is_high_priority(item))
    retained_items = _merge_unique_items(unresolved_items, minority_items)
    retained_high_priority_items = _merge_unique_items(
        unresolved_high_priority_items,
        minority_high_priority_items,
    )
    has_blocker = bool(artifact.blocker_count) or any(item.blocker for item in retained_items)
    evidence_or_validation_reason = _resolve_evidence_or_validation_reason(
        unresolved_items,
        minority_items,
    )
    has_multi_role_dissent = _has_multi_role_dissent(unresolved_items)
    semantic_state, dominant_reason = _derive_semantics(
        final_decision=final_decision,
        total_judgments=total_judgments,
        has_blocker=has_blocker,
        unresolved_items=unresolved_items,
        unresolved_high_priority_items=unresolved_high_priority_items,
        retained_items=retained_items,
        retained_high_priority_items=retained_high_priority_items,
        evidence_or_validation_reason=evidence_or_validation_reason,
        has_multi_role_dissent=has_multi_role_dissent,
    )
    reservation_level = _derive_reservation_level(
        has_blocker=has_blocker,
        retained_items=retained_items,
        retained_high_priority_items=retained_high_priority_items,
    )
    followup_bias = _derive_followup_bias(
        final_decision=final_decision,
        total_judgments=total_judgments,
        has_blocker=has_blocker,
        unresolved_items=unresolved_items,
        retained_items=retained_items,
        dominant_reason=dominant_reason,
    )
    explanation_summary = _build_explanation_summary(
        final_decision=final_decision,
        semantic_state=semantic_state,
        dominant_reason=dominant_reason,
        has_blocker=has_blocker,
        highest_rejection_severity=highest_rejection_severity,
        total_judgments=total_judgments,
        unresolved_high_priority_count=len(unresolved_high_priority_items),
        minority_high_priority_count=len(minority_high_priority_items),
        retained_high_priority_count=len(retained_high_priority_items),
    )
    return HeartbeatConvergenceProfile(
        final_decision=final_decision,
        semantic_state=semantic_state,
        dominant_reason=dominant_reason,
        has_blocker=has_blocker,
        highest_rejection_severity=highest_rejection_severity,
        unresolved_high_priority_count=len(unresolved_high_priority_items),
        minority_high_priority_count=len(minority_high_priority_items),
        reservation_level=reservation_level,
        explanation_summary=explanation_summary,
        followup_bias=followup_bias,
        metadata={
            "total_judgments": total_judgments,
            "retained_item_count": len(retained_items),
            "retained_high_priority_count": len(retained_high_priority_items),
        },
    )


def _resolve_aggregate_inputs(
    aggregate: HeartbeatAggregateResult | HeartbeatAggregateArtifact,
) -> tuple[HeartbeatAggregateArtifact, HeartbeatAggregateResult | None]:
    if isinstance(aggregate, HeartbeatAggregateResult):
        if aggregate.aggregate_artifact is None:
            raise ValueError(
                "Heartbeat convergence profile requires aggregate_result.aggregate_artifact."
            )
        return aggregate.aggregate_artifact, aggregate
    if isinstance(aggregate, HeartbeatAggregateArtifact):
        return aggregate, None
    raise TypeError(
        "Heartbeat convergence profile input must be HeartbeatAggregateResult "
        "or HeartbeatAggregateArtifact."
    )


def _resolve_total_judgments(
    artifact: HeartbeatAggregateArtifact,
    aggregate_result: HeartbeatAggregateResult | None,
) -> int:
    if aggregate_result is not None:
        return int(aggregate_result.total_judgments)
    metadata = artifact.metadata if isinstance(artifact.metadata, Mapping) else {}
    return int(metadata.get("judgment_count", 0) or 0)


def _filter_non_sufficient_items(
    items: Sequence[HeartbeatDissentItem],
) -> tuple[HeartbeatDissentItem, ...]:
    return tuple(item for item in items if item.category != RejectionDeficiencyCategory.SUFFICIENT)


def _merge_unique_items(
    *groups: Sequence[HeartbeatDissentItem],
) -> tuple[HeartbeatDissentItem, ...]:
    merged: list[HeartbeatDissentItem] = []
    seen: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()
    for group in groups:
        for item in group:
            identity = (
                item.category.value,
                item.judgment_ids,
                item.supporting_roles,
            )
            if identity in seen:
                continue
            seen.add(identity)
            merged.append(item)
    return tuple(merged)


def _coerce_enum(enum_type, value: object, *, field_name: str):
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value))
    except Exception as exc:
        raise ValueError(
            f"Heartbeat convergence profile {field_name} must use the canonical {enum_type.__name__} vocabulary."
        ) from exc


def _profile_retained_high_priority_count(profile: HeartbeatConvergenceProfile) -> int:
    return max(
        profile.unresolved_high_priority_count,
        profile.minority_high_priority_count,
    )


def _profile_metadata_count(
    profile: HeartbeatConvergenceProfile,
    key: str,
) -> int | None:
    metadata = profile.metadata if isinstance(profile.metadata, Mapping) else {}
    if key not in metadata or metadata.get(key) is None:
        return None
    count = int(metadata[key])
    if count < 0:
        raise ValueError(
            f"Heartbeat convergence profile metadata[{key!r}] must be non-negative when provided."
        )
    return count


def _item_is_high_priority(item: HeartbeatDissentItem) -> bool:
    return item.blocker or item.severity in _HIGH_PRIORITY_SEVERITIES


def _resolve_evidence_or_validation_reason(
    unresolved_items: Sequence[HeartbeatDissentItem],
    minority_items: Sequence[HeartbeatDissentItem],
) -> HeartbeatConvergenceDominantReason | None:
    for item in _merge_unique_items(unresolved_items, minority_items):
        if item.category != RejectionDeficiencyCategory.EVIDENCE_GAP:
            continue
        if any("validation" in signal_key for signal_key in item.used_signal_keys):
            return HeartbeatConvergenceDominantReason.VALIDATION_GAP
        return HeartbeatConvergenceDominantReason.EVIDENCE_GAP
    return None


def _has_multi_role_dissent(items: Sequence[HeartbeatDissentItem]) -> bool:
    if any(len(item.supporting_roles) >= 2 for item in items):
        return True
    supporting_roles = {role for item in items for role in item.supporting_roles}
    return len(supporting_roles) >= 2 and len(items) >= 2


def _derive_semantics(
    *,
    final_decision: ConvergenceStatus,
    total_judgments: int,
    has_blocker: bool,
    unresolved_items: Sequence[HeartbeatDissentItem],
    unresolved_high_priority_items: Sequence[HeartbeatDissentItem],
    retained_items: Sequence[HeartbeatDissentItem],
    retained_high_priority_items: Sequence[HeartbeatDissentItem],
    evidence_or_validation_reason: HeartbeatConvergenceDominantReason | None,
    has_multi_role_dissent: bool,
) -> tuple[HeartbeatConvergenceSemanticState, HeartbeatConvergenceDominantReason]:
    if final_decision == ConvergenceStatus.CONTINUE:
        if has_blocker:
            return (
                HeartbeatConvergenceSemanticState.BLOCKED_BY_BLOCKER,
                HeartbeatConvergenceDominantReason.BLOCKER_PRESENT,
            )
        if total_judgments == 0 or not unresolved_items:
            return (
                HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_INSUFFICIENT_SUPPORT,
                HeartbeatConvergenceDominantReason.INSUFFICIENT_APPROVAL_SUPPORT,
            )
        if evidence_or_validation_reason is not None:
            return (
                HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_VALIDATION_OR_EVIDENCE_GAP,
                evidence_or_validation_reason,
            )
        if has_multi_role_dissent:
            return (
                HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_MULTI_ROLE_DISSENT,
                HeartbeatConvergenceDominantReason.MULTI_ROLE_DISSENT,
            )
        if unresolved_high_priority_items:
            return (
                HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_UNRESOLVED_GAP,
                HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP,
            )
        return (
            HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_UNRESOLVED_GAP,
            HeartbeatConvergenceDominantReason.UNRESOLVED_GAP,
        )

    if not retained_items and not has_blocker:
        return (
            HeartbeatConvergenceSemanticState.CONVERGED_CLEAN,
            HeartbeatConvergenceDominantReason.NO_MATERIAL_RESERVATIONS,
        )
    if has_blocker:
        return (
            HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS,
            HeartbeatConvergenceDominantReason.BLOCKER_PRESENT,
        )
    if evidence_or_validation_reason is not None and retained_high_priority_items:
        return (
            HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS,
            evidence_or_validation_reason,
        )
    if retained_high_priority_items or unresolved_items:
        return (
            HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS,
            HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP,
        )
    return (
        HeartbeatConvergenceSemanticState.CONVERGED_WITH_RECORDED_DISSENT,
        HeartbeatConvergenceDominantReason.MINORITY_DISSENT_RETAINED,
    )


def _derive_reservation_level(
    *,
    has_blocker: bool,
    retained_items: Sequence[HeartbeatDissentItem],
    retained_high_priority_items: Sequence[HeartbeatDissentItem],
) -> HeartbeatConvergenceReservationLevel:
    if has_blocker:
        return HeartbeatConvergenceReservationLevel.BLOCKING
    if retained_high_priority_items:
        return HeartbeatConvergenceReservationLevel.ELEVATED
    if retained_items:
        return HeartbeatConvergenceReservationLevel.RECORDED
    return HeartbeatConvergenceReservationLevel.NONE


def _derive_followup_bias(
    *,
    final_decision: ConvergenceStatus,
    total_judgments: int,
    has_blocker: bool,
    unresolved_items: Sequence[HeartbeatDissentItem],
    retained_items: Sequence[HeartbeatDissentItem],
    dominant_reason: HeartbeatConvergenceDominantReason,
) -> HeartbeatConvergenceFollowupBias:
    if final_decision == ConvergenceStatus.CONVERGED:
        if retained_items or has_blocker:
            return HeartbeatConvergenceFollowupBias.CARRY_FORWARD_RESERVATIONS
        return HeartbeatConvergenceFollowupBias.PREPARE_TERMINAL_OUTPUT
    if has_blocker:
        return HeartbeatConvergenceFollowupBias.RESOLVE_BLOCKERS
    if total_judgments == 0 or not unresolved_items:
        return HeartbeatConvergenceFollowupBias.COLLECT_FRESH_JUDGMENTS
    if dominant_reason in {
        HeartbeatConvergenceDominantReason.EVIDENCE_GAP,
        HeartbeatConvergenceDominantReason.VALIDATION_GAP,
    }:
        return HeartbeatConvergenceFollowupBias.COLLECT_VALIDATION_EVIDENCE
    return HeartbeatConvergenceFollowupBias.CLOSE_UNRESOLVED_GAPS


def _build_explanation_summary(
    *,
    final_decision: ConvergenceStatus,
    semantic_state: HeartbeatConvergenceSemanticState,
    dominant_reason: HeartbeatConvergenceDominantReason,
    has_blocker: bool,
    highest_rejection_severity: str | None,
    total_judgments: int,
    unresolved_high_priority_count: int,
    minority_high_priority_count: int,
    retained_high_priority_count: int,
) -> str:
    severity_suffix = ""
    if highest_rejection_severity is not None:
        severity_suffix = f" Highest rejection severity was {highest_rejection_severity}."

    if final_decision == ConvergenceStatus.CONTINUE:
        if semantic_state == HeartbeatConvergenceSemanticState.BLOCKED_BY_BLOCKER:
            return (
                "Continue is dominated by blocker-marked unresolved deficiencies."
                + severity_suffix
            )
        if semantic_state == HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_INSUFFICIENT_SUPPORT:
            return (
                "Continue remains active because approval support was insufficient for convergence."
                f" Eligible heartbeat judgments: {total_judgments}."
            )
        if (
            semantic_state
            == HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_VALIDATION_OR_EVIDENCE_GAP
        ):
            gap_label = "validation" if dominant_reason == HeartbeatConvergenceDominantReason.VALIDATION_GAP else "evidence"
            return (
                "Continue is driven by unresolved "
                f"{gap_label} gaps with {unresolved_high_priority_count} high-priority item(s)."
                + severity_suffix
            )
        if semantic_state == HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_MULTI_ROLE_DISSENT:
            return (
                "Continue is driven by multi-role unresolved dissent without blocker-marked items."
                + severity_suffix
            )
        return (
            "Continue remains active because unresolved deficiencies still lead the aggregate view."
            f" High-priority unresolved items: {unresolved_high_priority_count}."
            + severity_suffix
        )

    if semantic_state == HeartbeatConvergenceSemanticState.CONVERGED_CLEAN:
        return "Converged cleanly with no retained high-priority dissent or blocker-marked reservations."
    if semantic_state == HeartbeatConvergenceSemanticState.CONVERGED_WITH_RECORDED_DISSENT:
        return (
            "Converged with recorded non-blocking dissent and no retained high-priority reservations."
        )
    blocker_phrase = " blocker-marked" if has_blocker else ""
    return (
        "Converged under current voting semantics while retaining"
        f" {retained_high_priority_count} high-priority{blocker_phrase} reservation(s)."
        f" Minority high-priority items: {minority_high_priority_count}."
        + severity_suffix
    )
