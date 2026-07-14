from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from agent_os.orchestrator.convergence import (
    HeartbeatAggregateArtifact,
    HeartbeatAggregateResult,
    HeartbeatDissentItem,
    HeartbeatSourceAnchor,
)
from agent_os.orchestrator.heartbeat_candidate_presentation import (
    HeartbeatCandidatePresentation,
    assert_heartbeat_candidate_presentation_matches_aggregate,
    assert_matching_heartbeat_candidate_presentations,
)
from agent_os.orchestrator.heartbeat_candidate_snapshot import (
    HeartbeatCandidateSnapshot,
    assert_matching_heartbeat_candidate_snapshots,
)
from agent_os.orchestrator.heartbeat_convergence_profile import (
    HeartbeatConvergenceProfile,
    assert_matching_heartbeat_convergence_profiles,
)
from agent_os.orchestrator.heartbeat_grading_contract import (
    canonicalize_heartbeat_blocker_count,
    canonicalize_heartbeat_blocker_roles,
    canonicalize_heartbeat_severity,
    canonicalize_heartbeat_severity_histogram,
)
from agent_os.orchestrator.heartbeat_terminal_export import (
    HeartbeatTerminalExportCandidatePayload as HeartbeatReportCandidatePresentationPayload,
    HeartbeatTerminalExportDisplaySectionPayload as HeartbeatReportTerminalDisplaySectionPayload,
    HeartbeatTerminalExportPayload as HeartbeatReportTerminalPayload,
    HeartbeatTerminalExportRetainedItemPayload as HeartbeatReportOutcomeRetainedItemPayload,
    project_heartbeat_terminal_candidate,
    project_heartbeat_terminal_payload,
    project_heartbeat_terminal_retained_item,
)
from agent_os.orchestrator.heartbeat_outcome_snapshot import (
    HeartbeatOutcomeSnapshot,
    HeartbeatOutcomeRetainedItem,
    assert_matching_heartbeat_outcome_snapshots,
)
from agent_os.orchestrator.heartbeat_terminal_payload import (
    HeartbeatTerminalPayload,
    assert_heartbeat_terminal_payload_matches_aggregate,
    assert_matching_heartbeat_terminal_payloads,
)


@dataclass(frozen=True, slots=True)
class HeartbeatReportSourceAnchorPayload:
    """Report-facing projection of one traceable heartbeat source anchor."""

    signal_key: str
    signal_family: str
    source_fields: tuple[str, ...] = ()
    matched_refs: tuple[str, ...] = ()
    derived_from_summary: bool = False
    derived_from_structured_content: bool = False
    derived_from_payload: bool = False


@dataclass(frozen=True, slots=True)
class HeartbeatReportCandidateSnapshotPayload:
    """Report-facing projection of the minimal candidate snapshot."""

    candidate_id: str
    checkpoint_id: str
    summary: str
    source_round: int | None = None
    supporting_context_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HeartbeatReportItemPayload:
    """Report-facing projection of one consensus/minority/unresolved heartbeat item."""

    category: str
    severity: str | None = None
    blocker: bool = False
    supporting_roles: tuple[str, ...] = ()
    dissenting_roles: tuple[str, ...] = ()
    judgment_ids: tuple[str, ...] = ()
    priority_rank: int = 0
    used_signal_keys: tuple[str, ...] = ()
    source_anchors: tuple[HeartbeatReportSourceAnchorPayload, ...] = ()
    summary: str | None = None
    impact_on_decision: str | None = None


@dataclass(frozen=True, slots=True)
class HeartbeatReportConvergenceProfilePayload:
    """Report-facing projection of the derived heartbeat convergence profile."""

    final_decision: str
    semantic_state: str
    dominant_reason: str
    has_blocker: bool = False
    highest_rejection_severity: str | None = None
    unresolved_high_priority_count: int = 0
    minority_high_priority_count: int = 0
    reservation_level: str = "none"
    explanation_summary: str = ""
    followup_bias: str = "prepare_terminal_output"


@dataclass(frozen=True, slots=True)
class HeartbeatReportOutcomeSnapshotPayload:
    """Report-facing projection of the derived heartbeat outcome snapshot."""

    final_decision: str
    convergence_profile: HeartbeatReportConvergenceProfilePayload
    candidate_snapshot: HeartbeatReportCandidateSnapshotPayload
    highest_rejection_severity: str | None = None
    blocker_count: int = 0
    reservation_summary: str | None = None
    decision_rationale: tuple[str, ...] = ()
    recommended_next_actions: tuple[str, ...] = ()
    consumer_readiness: str = "continue_only"
    top_retained_items: tuple[HeartbeatReportOutcomeRetainedItemPayload, ...] = ()

    @property
    def candidate_id(self) -> str:
        return self.candidate_snapshot.candidate_id

    @property
    def candidate_summary(self) -> str:
        return self.candidate_snapshot.summary


@dataclass(frozen=True, slots=True)
class HeartbeatReportPayload:
    """Lightweight report adapter output projected from aggregate heartbeat objects."""

    aggregate_result_id: str
    checkpoint_id: str
    candidate_id: str
    evidence_bundle_id: str | None = None
    final_decision: str = "continue"
    total_judgments: int | None = None
    approval_count: int | None = None
    rejection_count: int | None = None
    approval_ratio: float | None = None
    rejection_ratio: float | None = None
    dominant_deficiency_categories: tuple[str, ...] = ()
    highest_rejection_severity: str | None = None
    blocker_count: int = 0
    blocker_roles: tuple[str, ...] = ()
    severity_histogram: Mapping[str, int] = field(default_factory=dict)
    dissent_summary: str | None = None
    consensus_items: tuple[HeartbeatReportItemPayload, ...] = ()
    minority_items: tuple[HeartbeatReportItemPayload, ...] = ()
    unresolved_items: tuple[HeartbeatReportItemPayload, ...] = ()
    decision_rationale: tuple[str, ...] = ()
    recommended_next_actions: tuple[str, ...] = ()
    candidate_snapshot: HeartbeatReportCandidateSnapshotPayload | None = None
    convergence_profile: HeartbeatReportConvergenceProfilePayload | None = None
    outcome_snapshot: HeartbeatReportOutcomeSnapshotPayload | None = None
    candidate_presentation: HeartbeatReportCandidatePresentationPayload | None = None
    terminal_payload: HeartbeatReportTerminalPayload | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


def build_heartbeat_report_payload(
    aggregate: HeartbeatAggregateResult | HeartbeatAggregateArtifact,
) -> HeartbeatReportPayload:
    """Project an aggregate heartbeat object into a report-facing payload."""

    if isinstance(aggregate, HeartbeatAggregateResult):
        if aggregate.aggregate_artifact is None:
            raise ValueError(
                "Heartbeat report payload requires aggregate_result.aggregate_artifact."
            )
        return _build_payload(
            artifact=aggregate.aggregate_artifact,
            aggregate_result=aggregate,
        )
    if isinstance(aggregate, HeartbeatAggregateArtifact):
        return _build_payload(
            artifact=aggregate,
            aggregate_result=None,
        )
    raise TypeError(
        "Heartbeat report payload input must be HeartbeatAggregateResult "
        "or HeartbeatAggregateArtifact."
    )


def _build_payload(
    *,
    artifact: HeartbeatAggregateArtifact,
    aggregate_result: HeartbeatAggregateResult | None,
) -> HeartbeatReportPayload:
    resolved_candidate_presentation = _resolve_projectable_candidate_presentation(
        artifact=artifact,
        aggregate_result=aggregate_result,
    )
    if resolved_candidate_presentation is not None:
        assert_heartbeat_candidate_presentation_matches_aggregate(
            presentation=resolved_candidate_presentation,
            artifact=artifact,
            aggregate_result=aggregate_result,
        )
    resolved_terminal_payload = _resolve_projectable_terminal_payload(
        artifact=artifact,
        aggregate_result=aggregate_result,
    )
    if resolved_terminal_payload is not None:
        assert_heartbeat_terminal_payload_matches_aggregate(
            payload=resolved_terminal_payload,
            artifact=artifact,
            aggregate_result=aggregate_result,
        )
    projected_candidate_snapshot = _project_candidate_snapshot(
        _resolve_projectable_candidate_snapshot(
            artifact=artifact,
            aggregate_result=aggregate_result,
        )
    )
    projected_candidate_presentation = _project_candidate_presentation(
        resolved_candidate_presentation
    )
    return HeartbeatReportPayload(
        aggregate_result_id=artifact.aggregate_result_id,
        checkpoint_id=artifact.checkpoint_id,
        candidate_id=artifact.candidate_id,
        evidence_bundle_id=artifact.evidence_bundle_id,
        final_decision=artifact.final_decision.value,
        total_judgments=aggregate_result.total_judgments if aggregate_result is not None else None,
        approval_count=aggregate_result.approval_count if aggregate_result is not None else None,
        rejection_count=aggregate_result.rejection_count if aggregate_result is not None else None,
        approval_ratio=aggregate_result.approval_ratio if aggregate_result is not None else None,
        rejection_ratio=aggregate_result.rejection_ratio if aggregate_result is not None else None,
        dominant_deficiency_categories=(
            tuple(category.value for category in aggregate_result.dominant_deficiency_categories)
            if aggregate_result is not None
            else ()
        ),
        highest_rejection_severity=canonicalize_heartbeat_severity(
            aggregate_result.highest_rejection_severity
            if aggregate_result is not None
            else artifact.highest_rejection_severity
        ),
        blocker_count=canonicalize_heartbeat_blocker_count(
            aggregate_result.blocker_count if aggregate_result is not None else artifact.blocker_count
        ),
        blocker_roles=canonicalize_heartbeat_blocker_roles(
            aggregate_result.blocker_roles if aggregate_result is not None else artifact.blocker_roles
        ),
        severity_histogram=canonicalize_heartbeat_severity_histogram(
            aggregate_result.severity_histogram if aggregate_result is not None else artifact.severity_histogram
        ),
        dissent_summary=aggregate_result.dissent_summary if aggregate_result is not None else None,
        consensus_items=_project_items(artifact.consensus_items),
        minority_items=_project_items(artifact.minority_items),
        unresolved_items=_project_items(artifact.unresolved_items),
        decision_rationale=artifact.decision_rationale,
        recommended_next_actions=artifact.recommended_next_actions,
        candidate_snapshot=projected_candidate_snapshot,
        convergence_profile=_project_convergence_profile(
            _resolve_projectable_convergence_profile(
                artifact=artifact,
                aggregate_result=aggregate_result,
            )
        ),
        outcome_snapshot=_project_outcome_snapshot(
            _resolve_projectable_outcome_snapshot(
                artifact=artifact,
                aggregate_result=aggregate_result,
            ),
            projected_candidate_snapshot=projected_candidate_snapshot,
        ),
        candidate_presentation=projected_candidate_presentation,
        terminal_payload=_project_terminal_payload(
            resolved_terminal_payload,
            projected_candidate_presentation=projected_candidate_presentation,
        ),
        metadata={
            "input_kind": "aggregate_result" if aggregate_result is not None else "aggregate_artifact",
        },
    )


def _project_items(
    items: tuple[HeartbeatDissentItem, ...],
) -> tuple[HeartbeatReportItemPayload, ...]:
    return tuple(_project_item(item) for item in items)


def _project_item(item: HeartbeatDissentItem) -> HeartbeatReportItemPayload:
    return HeartbeatReportItemPayload(
        category=item.category.value,
        severity=canonicalize_heartbeat_severity(item.severity),
        blocker=item.blocker,
        supporting_roles=item.supporting_roles,
        dissenting_roles=item.dissenting_roles,
        judgment_ids=item.judgment_ids,
        priority_rank=item.priority_rank,
        used_signal_keys=item.used_signal_keys,
        source_anchors=tuple(_project_source_anchor(anchor) for anchor in item.source_anchors),
        summary=item.summary,
        impact_on_decision=item.impact_on_decision,
    )


def _project_source_anchor(
    anchor: HeartbeatSourceAnchor,
) -> HeartbeatReportSourceAnchorPayload:
    return HeartbeatReportSourceAnchorPayload(
        signal_key=anchor.signal_key,
        signal_family=anchor.signal_family,
        source_fields=anchor.source_fields,
        matched_refs=anchor.matched_refs,
        derived_from_summary=anchor.derived_from_summary,
        derived_from_structured_content=anchor.derived_from_structured_content,
        derived_from_payload=anchor.derived_from_payload,
    )


def _resolve_projectable_convergence_profile(
    *,
    artifact: HeartbeatAggregateArtifact,
    aggregate_result: HeartbeatAggregateResult | None,
) -> HeartbeatConvergenceProfile | None:
    artifact_profile = artifact.convergence_profile
    result_profile = aggregate_result.convergence_profile if aggregate_result is not None else None
    return assert_matching_heartbeat_convergence_profiles(
        artifact_profile,
        result_profile,
        require_all_or_none=aggregate_result is not None,
    )


def _resolve_projectable_candidate_snapshot(
    *,
    artifact: HeartbeatAggregateArtifact,
    aggregate_result: HeartbeatAggregateResult | None,
) -> HeartbeatCandidateSnapshot | None:
    artifact_snapshot = artifact.candidate_snapshot
    result_snapshot = aggregate_result.candidate_snapshot if aggregate_result is not None else None
    return assert_matching_heartbeat_candidate_snapshots(
        artifact_snapshot,
        result_snapshot,
        require_all_or_none=aggregate_result is not None,
    )


def _project_candidate_snapshot(
    snapshot: HeartbeatCandidateSnapshot | None,
) -> HeartbeatReportCandidateSnapshotPayload | None:
    if snapshot is None:
        return None
    return HeartbeatReportCandidateSnapshotPayload(
        candidate_id=snapshot.candidate_id,
        checkpoint_id=snapshot.checkpoint_id,
        summary=snapshot.summary,
        source_round=snapshot.source_round,
        supporting_context_refs=snapshot.supporting_context_refs,
    )


def _project_convergence_profile(
    profile: HeartbeatConvergenceProfile | None,
) -> HeartbeatReportConvergenceProfilePayload | None:
    if profile is None:
        return None
    return HeartbeatReportConvergenceProfilePayload(
        final_decision=profile.final_decision.value,
        semantic_state=profile.semantic_state.value,
        dominant_reason=profile.dominant_reason.value,
        has_blocker=profile.has_blocker,
        highest_rejection_severity=canonicalize_heartbeat_severity(
            profile.highest_rejection_severity
        ),
        unresolved_high_priority_count=profile.unresolved_high_priority_count,
        minority_high_priority_count=profile.minority_high_priority_count,
        reservation_level=profile.reservation_level.value,
        explanation_summary=profile.explanation_summary,
        followup_bias=profile.followup_bias.value,
    )


def _resolve_projectable_candidate_presentation(
    *,
    artifact: HeartbeatAggregateArtifact,
    aggregate_result: HeartbeatAggregateResult | None,
) -> HeartbeatCandidatePresentation | None:
    artifact_presentation = artifact.candidate_presentation
    result_presentation = (
        aggregate_result.candidate_presentation if aggregate_result is not None else None
    )
    return assert_matching_heartbeat_candidate_presentations(
        artifact_presentation,
        result_presentation,
        require_all_or_none=aggregate_result is not None,
    )


def _project_candidate_presentation(
    presentation: HeartbeatCandidatePresentation | None,
) -> HeartbeatReportCandidatePresentationPayload | None:
    return project_heartbeat_terminal_candidate(presentation)


def _resolve_projectable_outcome_snapshot(
    *,
    artifact: HeartbeatAggregateArtifact,
    aggregate_result: HeartbeatAggregateResult | None,
) -> HeartbeatOutcomeSnapshot | None:
    artifact_snapshot = artifact.outcome_snapshot
    result_snapshot = aggregate_result.outcome_snapshot if aggregate_result is not None else None
    return assert_matching_heartbeat_outcome_snapshots(
        artifact_snapshot,
        result_snapshot,
        require_all_or_none=aggregate_result is not None,
    )


def _project_outcome_snapshot(
    snapshot: HeartbeatOutcomeSnapshot | None,
    *,
    projected_candidate_snapshot: HeartbeatReportCandidateSnapshotPayload | None = None,
) -> HeartbeatReportOutcomeSnapshotPayload | None:
    if snapshot is None:
        return None
    projected_profile = _project_convergence_profile(snapshot.convergence_profile)
    if projected_profile is None:
        raise ValueError("Heartbeat report outcome snapshot projection requires convergence_profile.")
    if projected_candidate_snapshot is None:
        projected_candidate_snapshot = _project_candidate_snapshot(snapshot.candidate_snapshot)
    if projected_candidate_snapshot is None:
        raise ValueError("Heartbeat report outcome snapshot projection requires candidate_snapshot.")
    return HeartbeatReportOutcomeSnapshotPayload(
        final_decision=snapshot.final_decision.value,
        convergence_profile=projected_profile,
        candidate_snapshot=projected_candidate_snapshot,
        highest_rejection_severity=canonicalize_heartbeat_severity(
            snapshot.highest_rejection_severity
        ),
        blocker_count=canonicalize_heartbeat_blocker_count(snapshot.blocker_count),
        reservation_summary=snapshot.reservation_summary,
        decision_rationale=snapshot.decision_rationale,
        recommended_next_actions=snapshot.recommended_next_actions,
        consumer_readiness=snapshot.consumer_readiness.value,
        top_retained_items=tuple(
            _project_outcome_retained_item(item) for item in snapshot.top_retained_items
        ),
    )


def _project_outcome_retained_item(
    item: HeartbeatOutcomeRetainedItem,
) -> HeartbeatReportOutcomeRetainedItemPayload:
    return project_heartbeat_terminal_retained_item(item)


def _resolve_projectable_terminal_payload(
    *,
    artifact: HeartbeatAggregateArtifact,
    aggregate_result: HeartbeatAggregateResult | None,
) -> HeartbeatTerminalPayload | None:
    artifact_payload = artifact.terminal_payload
    result_payload = aggregate_result.terminal_payload if aggregate_result is not None else None
    return assert_matching_heartbeat_terminal_payloads(
        artifact_payload,
        result_payload,
        require_all_or_none=aggregate_result is not None,
    )


def _project_terminal_payload(
    payload: HeartbeatTerminalPayload | None,
    *,
    projected_candidate_presentation: HeartbeatReportCandidatePresentationPayload | None = None,
) -> HeartbeatReportTerminalPayload | None:
    if payload is None:
        return None
    return project_heartbeat_terminal_payload(
        payload,
        projected_candidate=projected_candidate_presentation,
    )
