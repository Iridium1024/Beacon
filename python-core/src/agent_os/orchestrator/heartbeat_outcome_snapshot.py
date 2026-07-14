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
from agent_os.orchestrator.heartbeat_candidate_snapshot import (
    HeartbeatCandidateSnapshot,
    assert_heartbeat_candidate_snapshot_matches_aggregate,
    assert_matching_heartbeat_candidate_snapshots,
    validate_heartbeat_candidate_snapshot,
)
from agent_os.orchestrator.heartbeat_convergence_profile import (
    HeartbeatConvergenceProfile,
    HeartbeatConvergenceSemanticState,
    assert_matching_heartbeat_convergence_profiles,
    validate_heartbeat_convergence_profile,
)
from agent_os.orchestrator.heartbeat_grading_contract import (
    canonicalize_heartbeat_blocker_count,
    canonicalize_heartbeat_severity,
)

_TOP_RETAINED_ITEM_LIMIT = 3


class HeartbeatOutcomeConsumerReadiness(StrEnum):
    """Stable readiness vocabulary for upper-layer heartbeat consumers."""

    CONTINUE_ONLY = "continue_only"
    REMEDIATION_REQUIRED = "remediation_required"
    TERMINAL_READY = "terminal_ready"
    TERMINAL_READY_WITH_RESERVATIONS = "terminal_ready_with_reservations"


@dataclass(frozen=True, slots=True)
class HeartbeatOutcomeRetainedItem:
    """Minimal, stable retained-item view exposed by the outcome snapshot."""

    category: RejectionDeficiencyCategory
    severity: str | None = None
    blocker: bool = False
    priority_rank: int = 0
    supporting_roles: tuple[str, ...] = ()
    summary: str | None = None
    impact_on_decision: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "severity", canonicalize_heartbeat_severity(self.severity))
        object.__setattr__(self, "blocker", bool(self.blocker))
        normalized_priority_rank = int(self.priority_rank or 0)
        if normalized_priority_rank < 0:
            raise ValueError("Heartbeat outcome retained item priority_rank must be non-negative.")
        object.__setattr__(self, "priority_rank", normalized_priority_rank)


@dataclass(frozen=True, slots=True)
class HeartbeatOutcomeSnapshot:
    """Single upper-layer consumption snapshot derived from canonical heartbeat outputs."""

    final_decision: ConvergenceStatus
    convergence_profile: HeartbeatConvergenceProfile
    candidate_snapshot: HeartbeatCandidateSnapshot
    highest_rejection_severity: str | None = None
    blocker_count: int = 0
    reservation_summary: str | None = None
    decision_rationale: tuple[str, ...] = ()
    recommended_next_actions: tuple[str, ...] = ()
    consumer_readiness: HeartbeatOutcomeConsumerReadiness = (
        HeartbeatOutcomeConsumerReadiness.CONTINUE_ONLY
    )
    top_retained_items: tuple[HeartbeatOutcomeRetainedItem, ...] = ()
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
            "consumer_readiness",
            _coerce_enum(
                HeartbeatOutcomeConsumerReadiness,
                self.consumer_readiness,
                field_name="consumer_readiness",
            ),
        )
        object.__setattr__(
            self,
            "highest_rejection_severity",
            canonicalize_heartbeat_severity(self.highest_rejection_severity),
        )
        object.__setattr__(self, "blocker_count", canonicalize_heartbeat_blocker_count(self.blocker_count))
        object.__setattr__(
            self,
            "decision_rationale",
            tuple(_normalize_text_sequence(self.decision_rationale)),
        )
        object.__setattr__(
            self,
            "recommended_next_actions",
            tuple(_normalize_text_sequence(self.recommended_next_actions)),
        )
        reservation_summary = None if self.reservation_summary is None else str(self.reservation_summary).strip()
        object.__setattr__(self, "reservation_summary", reservation_summary or None)
        object.__setattr__(
            self,
            "top_retained_items",
            tuple(self.top_retained_items),
        )
        validate_heartbeat_candidate_snapshot(self.candidate_snapshot)
        validate_heartbeat_convergence_profile(self.convergence_profile)
        validate_heartbeat_outcome_snapshot(self)

    @property
    def candidate_id(self) -> str:
        """Backward-compatible scalar projection of the attached candidate snapshot."""

        return self.candidate_snapshot.candidate_id

    @property
    def candidate_summary(self) -> str:
        """Backward-compatible scalar projection of the attached candidate snapshot."""

        return self.candidate_snapshot.summary


def build_heartbeat_outcome_snapshot(
    aggregate: HeartbeatAggregateResult | HeartbeatAggregateArtifact,
    *,
    convergence_profile: HeartbeatConvergenceProfile | None = None,
    candidate_snapshot: HeartbeatCandidateSnapshot | None = None,
    retained_item_limit: int = _TOP_RETAINED_ITEM_LIMIT,
) -> HeartbeatOutcomeSnapshot:
    """Build one stable upper-layer consumption snapshot from canonical heartbeat outputs."""

    artifact, aggregate_result = _resolve_aggregate_inputs(aggregate)
    profile = assert_matching_heartbeat_convergence_profiles(
        convergence_profile,
        artifact.convergence_profile,
        aggregate_result.convergence_profile if aggregate_result is not None else None,
    )
    if profile is None:
        raise ValueError(
            "Heartbeat outcome snapshot requires an explicit convergence_profile "
            "or an aggregate object that already carries one."
        )
    resolved_candidate_snapshot = assert_matching_heartbeat_candidate_snapshots(
        candidate_snapshot,
        artifact.candidate_snapshot,
        aggregate_result.candidate_snapshot if aggregate_result is not None else None,
        require_all_or_none=False,
    )
    if resolved_candidate_snapshot is None:
        raise ValueError(
            "Heartbeat outcome snapshot requires an explicit candidate_snapshot "
            "or an aggregate object that already carries one."
        )
    retained_item_limit = int(retained_item_limit)
    if retained_item_limit < 0:
        raise ValueError("Heartbeat outcome snapshot retained_item_limit must be non-negative.")
    top_retained_items = _project_top_retained_items(artifact, limit=retained_item_limit)
    final_decision = (
        aggregate_result.recommended_outcome if aggregate_result is not None else artifact.final_decision
    )
    highest_rejection_severity = canonicalize_heartbeat_severity(
        aggregate_result.highest_rejection_severity
        if aggregate_result is not None
        else artifact.highest_rejection_severity
    )
    blocker_count = canonicalize_heartbeat_blocker_count(
        aggregate_result.blocker_count if aggregate_result is not None else artifact.blocker_count
    )
    consumer_readiness = _derive_consumer_readiness(
        final_decision=final_decision,
        convergence_profile=profile,
        blocker_count=blocker_count,
    )
    reservation_summary = _build_reservation_summary(
        consumer_readiness=consumer_readiness,
        convergence_profile=profile,
        top_retained_items=top_retained_items,
    )
    snapshot = HeartbeatOutcomeSnapshot(
        final_decision=final_decision,
        convergence_profile=profile,
        candidate_snapshot=resolved_candidate_snapshot,
        highest_rejection_severity=highest_rejection_severity,
        blocker_count=blocker_count,
        reservation_summary=reservation_summary,
        decision_rationale=artifact.decision_rationale,
        recommended_next_actions=artifact.recommended_next_actions,
        consumer_readiness=consumer_readiness,
        top_retained_items=top_retained_items,
        metadata={
            "retained_items_view_kind": "priority_slice_deduped",
            "top_retained_items_limit": retained_item_limit,
            "top_retained_items_truncated": len(_merge_unique_retained_items(artifact)) > retained_item_limit,
            "top_retained_items_count": len(top_retained_items),
        },
    )
    assert_heartbeat_outcome_matches_aggregate(
        snapshot=snapshot,
        artifact=artifact,
        aggregate_result=aggregate_result,
    )
    return snapshot


def validate_heartbeat_outcome_snapshot(snapshot: HeartbeatOutcomeSnapshot) -> None:
    """Validate the stable contract for one heartbeat outcome snapshot."""

    if snapshot.final_decision != snapshot.convergence_profile.final_decision:
        raise ValueError(
            "Heartbeat outcome snapshot final_decision must mirror convergence_profile.final_decision."
        )

    readiness = snapshot.consumer_readiness
    semantic_state = snapshot.convergence_profile.semantic_state
    has_blocker = snapshot.convergence_profile.has_blocker or snapshot.blocker_count > 0
    has_retained_items = bool(snapshot.top_retained_items)

    if readiness == HeartbeatOutcomeConsumerReadiness.CONTINUE_ONLY:
        if snapshot.final_decision != ConvergenceStatus.CONTINUE:
            raise ValueError("continue_only outcomes must keep final_decision=continue.")
        if has_blocker:
            raise ValueError("continue_only outcomes must not carry blocker semantics.")
        if semantic_state == HeartbeatConvergenceSemanticState.BLOCKED_BY_BLOCKER:
            raise ValueError("continue_only outcomes must not use blocker profile semantics.")

    if readiness == HeartbeatOutcomeConsumerReadiness.REMEDIATION_REQUIRED:
        if snapshot.final_decision != ConvergenceStatus.CONTINUE:
            raise ValueError("remediation_required outcomes must keep final_decision=continue.")
        if not has_blocker:
            raise ValueError("remediation_required outcomes must carry blocker semantics.")

    if readiness == HeartbeatOutcomeConsumerReadiness.TERMINAL_READY:
        if snapshot.final_decision != ConvergenceStatus.CONVERGED:
            raise ValueError("terminal_ready outcomes must keep final_decision=converged.")
        if semantic_state != HeartbeatConvergenceSemanticState.CONVERGED_CLEAN:
            raise ValueError("terminal_ready outcomes require converged_clean profile semantics.")
        if has_retained_items:
            raise ValueError("terminal_ready outcomes must not expose retained items.")
        if snapshot.reservation_summary is not None:
            raise ValueError("terminal_ready outcomes must not expose reservation_summary.")

    if readiness == HeartbeatOutcomeConsumerReadiness.TERMINAL_READY_WITH_RESERVATIONS:
        if snapshot.final_decision != ConvergenceStatus.CONVERGED:
            raise ValueError(
                "terminal_ready_with_reservations outcomes must keep final_decision=converged."
            )
        if semantic_state == HeartbeatConvergenceSemanticState.CONVERGED_CLEAN:
            raise ValueError(
                "terminal_ready_with_reservations outcomes must not use converged_clean semantics."
            )

    if readiness != HeartbeatOutcomeConsumerReadiness.TERMINAL_READY:
        if snapshot.reservation_summary is None:
            raise ValueError(
                "Non-clean heartbeat outcomes must expose a minimal reservation_summary."
            )

    if snapshot.top_retained_items and readiness in {
        HeartbeatOutcomeConsumerReadiness.CONTINUE_ONLY,
        HeartbeatOutcomeConsumerReadiness.REMEDIATION_REQUIRED,
        HeartbeatOutcomeConsumerReadiness.TERMINAL_READY_WITH_RESERVATIONS,
    }:
        if any(item.category == RejectionDeficiencyCategory.SUFFICIENT for item in snapshot.top_retained_items):
            raise ValueError("Heartbeat outcome top_retained_items must not include sufficient items.")


def assert_matching_heartbeat_outcome_snapshots(
    *snapshots: HeartbeatOutcomeSnapshot | None,
    require_all_or_none: bool = False,
) -> HeartbeatOutcomeSnapshot | None:
    """Validate and reconcile one or more snapshot references that should agree."""

    present_snapshots = tuple(snapshot for snapshot in snapshots if snapshot is not None)
    if require_all_or_none and present_snapshots and len(present_snapshots) != len(snapshots):
        raise ValueError(
            "Heartbeat outcome snapshot references must either all be present or all be absent."
        )
    if not present_snapshots:
        return None

    canonical_snapshot = present_snapshots[0]
    validate_heartbeat_outcome_snapshot(canonical_snapshot)
    for snapshot in present_snapshots[1:]:
        validate_heartbeat_outcome_snapshot(snapshot)
        if snapshot is not canonical_snapshot:
            raise ValueError(
                "Heartbeat outcome snapshot references must reuse the same object instance."
            )
        if snapshot != canonical_snapshot:
            raise ValueError("Heartbeat outcome snapshot references must agree exactly.")
    return canonical_snapshot


def assert_heartbeat_outcome_matches_aggregate(
    *,
    snapshot: HeartbeatOutcomeSnapshot,
    artifact: HeartbeatAggregateArtifact,
    aggregate_result: HeartbeatAggregateResult | None = None,
) -> None:
    """Assert that one outcome snapshot really matches the canonical aggregate objects."""

    validate_heartbeat_outcome_snapshot(snapshot)
    attached_snapshot = assert_matching_heartbeat_outcome_snapshots(
        artifact.outcome_snapshot,
        aggregate_result.outcome_snapshot if aggregate_result is not None else None,
        require_all_or_none=aggregate_result is not None,
    )
    if attached_snapshot is not None and attached_snapshot is not snapshot:
        raise ValueError(
            "Heartbeat outcome snapshot must match the attached aggregate outcome_snapshot."
        )
    attached_profile = assert_matching_heartbeat_convergence_profiles(
        artifact.convergence_profile,
        aggregate_result.convergence_profile if aggregate_result is not None else None,
        require_all_or_none=aggregate_result is not None,
    )
    if attached_profile is not None and snapshot.convergence_profile is not attached_profile:
        raise ValueError(
            "Heartbeat outcome snapshot convergence_profile must match the attached aggregate profile."
        )
    if snapshot.final_decision != artifact.final_decision:
        raise ValueError(
            "Heartbeat outcome snapshot final_decision must match aggregate artifact final_decision."
        )
    if aggregate_result is not None and snapshot.final_decision != aggregate_result.recommended_outcome:
        raise ValueError(
            "Heartbeat outcome snapshot final_decision must match aggregate result recommended_outcome."
        )
    if snapshot.candidate_id != artifact.candidate_id:
        raise ValueError("Heartbeat outcome snapshot candidate_id must match aggregate artifact.")
    assert_heartbeat_candidate_snapshot_matches_aggregate(
        snapshot=snapshot.candidate_snapshot,
        artifact=artifact,
        aggregate_result=aggregate_result,
    )
    expected_highest_rejection_severity = canonicalize_heartbeat_severity(
        aggregate_result.highest_rejection_severity
        if aggregate_result is not None
        else artifact.highest_rejection_severity
    )
    if snapshot.highest_rejection_severity != expected_highest_rejection_severity:
        raise ValueError(
            "Heartbeat outcome snapshot highest_rejection_severity must match canonical aggregate output."
        )
    expected_blocker_count = canonicalize_heartbeat_blocker_count(
        aggregate_result.blocker_count if aggregate_result is not None else artifact.blocker_count
    )
    if snapshot.blocker_count != expected_blocker_count:
        raise ValueError(
            "Heartbeat outcome snapshot blocker_count must match canonical aggregate output."
        )
    if snapshot.decision_rationale != artifact.decision_rationale:
        raise ValueError(
            "Heartbeat outcome snapshot decision_rationale must mirror aggregate artifact."
        )
    if snapshot.recommended_next_actions != artifact.recommended_next_actions:
        raise ValueError(
            "Heartbeat outcome snapshot recommended_next_actions must mirror aggregate artifact."
        )
    expected_top_retained_items = _project_top_retained_items(
        artifact,
        limit=_resolve_top_retained_item_limit(snapshot),
    )
    if snapshot.top_retained_items != expected_top_retained_items:
        raise ValueError(
            "Heartbeat outcome snapshot top_retained_items must match the aggregate priority-slice view."
        )


def _resolve_aggregate_inputs(
    aggregate: HeartbeatAggregateResult | HeartbeatAggregateArtifact,
) -> tuple[HeartbeatAggregateArtifact, HeartbeatAggregateResult | None]:
    if isinstance(aggregate, HeartbeatAggregateResult):
        if aggregate.aggregate_artifact is None:
            raise ValueError(
                "Heartbeat outcome snapshot requires aggregate_result.aggregate_artifact."
            )
        return aggregate.aggregate_artifact, aggregate
    if isinstance(aggregate, HeartbeatAggregateArtifact):
        return aggregate, None
    raise TypeError(
        "Heartbeat outcome snapshot input must be HeartbeatAggregateResult "
        "or HeartbeatAggregateArtifact."
    )


def _derive_consumer_readiness(
    *,
    final_decision: ConvergenceStatus,
    convergence_profile: HeartbeatConvergenceProfile,
    blocker_count: int,
) -> HeartbeatOutcomeConsumerReadiness:
    if final_decision == ConvergenceStatus.CONTINUE:
        if convergence_profile.has_blocker or blocker_count > 0:
            return HeartbeatOutcomeConsumerReadiness.REMEDIATION_REQUIRED
        return HeartbeatOutcomeConsumerReadiness.CONTINUE_ONLY
    if convergence_profile.semantic_state == HeartbeatConvergenceSemanticState.CONVERGED_CLEAN:
        return HeartbeatOutcomeConsumerReadiness.TERMINAL_READY
    return HeartbeatOutcomeConsumerReadiness.TERMINAL_READY_WITH_RESERVATIONS


def _build_reservation_summary(
    *,
    consumer_readiness: HeartbeatOutcomeConsumerReadiness,
    convergence_profile: HeartbeatConvergenceProfile,
    top_retained_items: Sequence[HeartbeatOutcomeRetainedItem],
) -> str | None:
    if consumer_readiness == HeartbeatOutcomeConsumerReadiness.TERMINAL_READY:
        return None
    if consumer_readiness == HeartbeatOutcomeConsumerReadiness.REMEDIATION_REQUIRED:
        return (
            "Blocker-marked retained items require remediation before the next heartbeat."
        )
    if consumer_readiness == HeartbeatOutcomeConsumerReadiness.CONTINUE_ONLY:
        if (
            convergence_profile.semantic_state
            == HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_INSUFFICIENT_SUPPORT
        ):
            return (
                "Approval support remained insufficient; collect stronger support before the next heartbeat."
            )
        return "Unresolved retained items remain in the continue path and should be handled in priority order."
    if (
        convergence_profile.semantic_state
        == HeartbeatConvergenceSemanticState.CONVERGED_WITH_RECORDED_DISSENT
    ):
        return (
            "Converged with recorded non-blocking dissent; downstream consumers should carry the retained caution items."
        )
    if top_retained_items:
        return (
            "Converged with retained reservations; downstream consumers should surface caution alongside the top retained items."
        )
    return (
        "Converged with retained reservations; downstream consumers should preserve explicit caution."
    )


def _project_top_retained_items(
    artifact: HeartbeatAggregateArtifact,
    *,
    limit: int,
) -> tuple[HeartbeatOutcomeRetainedItem, ...]:
    return tuple(
        _project_retained_item(item)
        for item in _merge_unique_retained_items(artifact)[:limit]
    )


def _project_retained_item(item: HeartbeatDissentItem) -> HeartbeatOutcomeRetainedItem:
    return HeartbeatOutcomeRetainedItem(
        category=item.category,
        severity=item.severity,
        blocker=item.blocker,
        priority_rank=item.priority_rank,
        supporting_roles=item.supporting_roles,
        summary=item.summary,
        impact_on_decision=item.impact_on_decision,
    )


def _merge_unique_retained_items(
    artifact: HeartbeatAggregateArtifact,
) -> tuple[HeartbeatDissentItem, ...]:
    retained_items: list[HeartbeatDissentItem] = []
    seen: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()
    for group in (artifact.unresolved_items, artifact.minority_items):
        for item in group:
            if item.category == RejectionDeficiencyCategory.SUFFICIENT:
                continue
            identity = (
                item.category.value,
                item.judgment_ids,
                item.supporting_roles,
            )
            if identity in seen:
                continue
            seen.add(identity)
            retained_items.append(item)
    return tuple(retained_items)


def _resolve_top_retained_item_limit(snapshot: HeartbeatOutcomeSnapshot) -> int:
    metadata = snapshot.metadata if isinstance(snapshot.metadata, Mapping) else {}
    limit = int(metadata.get("top_retained_items_limit", len(snapshot.top_retained_items)))
    if limit < 0:
        raise ValueError(
            "Heartbeat outcome snapshot metadata['top_retained_items_limit'] must be non-negative."
        )
    return limit


def _normalize_text_sequence(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in values if str(value).strip())


def _coerce_enum(enum_type, value: object, *, field_name: str):
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value))
    except Exception as exc:
        raise ValueError(
            f"Heartbeat outcome snapshot {field_name} must use the canonical {enum_type.__name__} vocabulary."
        ) from exc
