from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from agent_os.orchestrator.convergence import (
    ConvergenceStatus,
    HeartbeatAggregateArtifact,
    HeartbeatAggregateResult,
)
from agent_os.orchestrator.heartbeat_candidate_presentation import (
    HeartbeatCandidatePresentation,
    assert_heartbeat_candidate_presentation_matches_aggregate,
    assert_matching_heartbeat_candidate_presentations,
    validate_heartbeat_candidate_presentation,
)
from agent_os.orchestrator.heartbeat_candidate_snapshot import (
    assert_heartbeat_candidate_snapshot_matches_aggregate,
    assert_matching_heartbeat_candidate_snapshots,
)
from agent_os.orchestrator.heartbeat_convergence_profile import (
    assert_matching_heartbeat_convergence_profiles,
    validate_heartbeat_convergence_profile,
)
from agent_os.orchestrator.heartbeat_outcome_snapshot import (
    HeartbeatOutcomeConsumerReadiness,
    HeartbeatOutcomeRetainedItem,
    HeartbeatOutcomeSnapshot,
    assert_heartbeat_outcome_matches_aggregate,
    assert_matching_heartbeat_outcome_snapshots,
)

_DEFAULT_SECTION_ORDER = (
    "candidate",
    "reservation_summary",
    "top_retained_items",
    "decision_rationale",
    "recommended_next_actions",
)
_DEFAULT_RETAINED_ITEMS_DISPLAY_LIMIT = 2
_DEFAULT_DECISION_RATIONALE_DISPLAY_LIMIT = 3
_DEFAULT_NEXT_ACTIONS_DISPLAY_LIMIT = 3
_DISPLAY_POLICY_VERSION = "terminal_v1"


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized_value = str(value).strip()
    return normalized_value or None


def _normalize_text_sequence(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in values if str(value).strip())


def _coerce_enum(enum_type, value: object, *, field_name: str):
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value))
    except Exception as exc:
        raise ValueError(
            "Heartbeat terminal payload "
            f"{field_name} must use the canonical {enum_type.__name__} vocabulary."
        ) from exc


class HeartbeatTerminalDisplaySectionKind(StrEnum):
    """Stable section identifiers for terminal-facing heartbeat displays."""

    CANDIDATE = "candidate"
    DECISION_RATIONALE = "decision_rationale"
    RESERVATION_SUMMARY = "reservation_summary"
    TOP_RETAINED_ITEMS = "top_retained_items"
    RECOMMENDED_NEXT_ACTIONS = "recommended_next_actions"


@dataclass(frozen=True, slots=True)
class HeartbeatTerminalDisplayPolicy:
    """Deterministic display policy for terminal-facing heartbeat payloads."""

    version: str = _DISPLAY_POLICY_VERSION
    section_order: tuple[HeartbeatTerminalDisplaySectionKind, ...] = tuple(
        HeartbeatTerminalDisplaySectionKind(value) for value in _DEFAULT_SECTION_ORDER
    )
    omit_empty_sections: bool = True
    retained_items_display_limit: int = _DEFAULT_RETAINED_ITEMS_DISPLAY_LIMIT
    decision_rationale_display_limit: int = _DEFAULT_DECISION_RATIONALE_DISPLAY_LIMIT
    recommended_next_actions_display_limit: int = _DEFAULT_NEXT_ACTIONS_DISPLAY_LIMIT

    def __post_init__(self) -> None:
        version = str(self.version).strip()
        if not version:
            raise ValueError("Heartbeat terminal display policy requires a version.")
        order = tuple(
            _coerce_enum(
                HeartbeatTerminalDisplaySectionKind,
                value,
                field_name="section_order",
            )
            for value in self.section_order
        )
        if set(order) != set(HeartbeatTerminalDisplaySectionKind):
            raise ValueError(
                "Heartbeat terminal display policy section_order must cover every section kind exactly once."
            )
        if len(order) != len(set(order)):
            raise ValueError(
                "Heartbeat terminal display policy section_order must not repeat section kinds."
            )
        retained_limit = int(self.retained_items_display_limit)
        rationale_limit = int(self.decision_rationale_display_limit)
        next_actions_limit = int(self.recommended_next_actions_display_limit)
        if min(retained_limit, rationale_limit, next_actions_limit) <= 0:
            raise ValueError(
                "Heartbeat terminal display policy display limits must be positive."
            )
        if not bool(self.omit_empty_sections):
            raise ValueError(
                "Heartbeat terminal display policy currently supports deterministic empty-section omission only."
            )
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "section_order", order)
        object.__setattr__(self, "omit_empty_sections", True)
        object.__setattr__(self, "retained_items_display_limit", retained_limit)
        object.__setattr__(self, "decision_rationale_display_limit", rationale_limit)
        object.__setattr__(
            self,
            "recommended_next_actions_display_limit",
            next_actions_limit,
        )


DEFAULT_HEARTBEAT_TERMINAL_DISPLAY_POLICY = HeartbeatTerminalDisplayPolicy()


@dataclass(frozen=True, slots=True)
class HeartbeatTerminalDisplaySection:
    """One terminal-facing display section built from already-attached objects."""

    kind: HeartbeatTerminalDisplaySectionKind
    title: str
    lines: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            _coerce_enum(
                HeartbeatTerminalDisplaySectionKind,
                self.kind,
                field_name="kind",
            ),
        )
        title = str(self.title).strip()
        if not title:
            raise ValueError("Heartbeat terminal display section requires a non-empty title.")
        lines = tuple(_normalize_text_sequence(self.lines))
        if not lines:
            raise ValueError("Heartbeat terminal display section requires at least one line.")
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "lines", lines)


@dataclass(frozen=True, slots=True)
class HeartbeatTerminalPayload:
    """Terminal-consumption heartbeat contract layered on explicit heartbeat objects."""

    final_decision: ConvergenceStatus
    consumer_readiness: HeartbeatOutcomeConsumerReadiness
    candidate: HeartbeatCandidatePresentation
    decision_rationale: tuple[str, ...] = ()
    recommended_next_actions: tuple[str, ...] = ()
    top_retained_items: tuple[HeartbeatOutcomeRetainedItem, ...] = ()
    reservation_summary: str | None = None
    display_sections: tuple[HeartbeatTerminalDisplaySection, ...] = ()
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
            "decision_rationale",
            tuple(_normalize_text_sequence(self.decision_rationale)),
        )
        object.__setattr__(
            self,
            "recommended_next_actions",
            tuple(_normalize_text_sequence(self.recommended_next_actions)),
        )
        object.__setattr__(
            self,
            "reservation_summary",
            _normalize_optional_text(self.reservation_summary),
        )
        object.__setattr__(self, "top_retained_items", tuple(self.top_retained_items))
        object.__setattr__(self, "display_sections", tuple(self.display_sections))
        validate_heartbeat_candidate_presentation(self.candidate)
        validate_heartbeat_terminal_payload(self)


def build_heartbeat_terminal_payload(
    aggregate: HeartbeatAggregateResult | HeartbeatAggregateArtifact,
    *,
    candidate_presentation: HeartbeatCandidatePresentation | None = None,
    outcome_snapshot: HeartbeatOutcomeSnapshot | None = None,
    display_policy: HeartbeatTerminalDisplayPolicy = DEFAULT_HEARTBEAT_TERMINAL_DISPLAY_POLICY,
) -> HeartbeatTerminalPayload:
    """Build one terminal payload by organizing already-derived heartbeat objects."""

    artifact, aggregate_result = _resolve_aggregate_inputs(aggregate)
    _assert_explicit_object_reuse(
        explicit_object=candidate_presentation,
        artifact_object=artifact.candidate_presentation,
        result_object=aggregate_result.candidate_presentation if aggregate_result is not None else None,
        object_label="candidate_presentation",
    )
    _assert_explicit_object_reuse(
        explicit_object=outcome_snapshot,
        artifact_object=artifact.outcome_snapshot,
        result_object=aggregate_result.outcome_snapshot if aggregate_result is not None else None,
        object_label="outcome_snapshot",
    )
    resolved_candidate_presentation = assert_matching_heartbeat_candidate_presentations(
        candidate_presentation,
        artifact.candidate_presentation,
        aggregate_result.candidate_presentation if aggregate_result is not None else None,
    )
    if resolved_candidate_presentation is None:
        raise ValueError(
            "Heartbeat terminal payload requires candidate_presentation from explicit input "
            "or an attached aggregate object."
        )
    resolved_outcome_snapshot = assert_matching_heartbeat_outcome_snapshots(
        outcome_snapshot,
        artifact.outcome_snapshot,
        aggregate_result.outcome_snapshot if aggregate_result is not None else None,
    )
    if resolved_outcome_snapshot is None:
        raise ValueError(
            "Heartbeat terminal payload requires outcome_snapshot from explicit input "
            "or an attached aggregate object."
        )
    display_policy = _coerce_display_policy(display_policy)
    display_sections = _build_display_sections(
        candidate_presentation=resolved_candidate_presentation,
        decision_rationale=artifact.decision_rationale,
        recommended_next_actions=artifact.recommended_next_actions,
        reservation_summary=resolved_outcome_snapshot.reservation_summary,
        top_retained_items=resolved_outcome_snapshot.top_retained_items,
        display_policy=display_policy,
    )
    payload = HeartbeatTerminalPayload(
        final_decision=resolved_outcome_snapshot.final_decision,
        consumer_readiness=resolved_outcome_snapshot.consumer_readiness,
        candidate=resolved_candidate_presentation,
        decision_rationale=artifact.decision_rationale,
        recommended_next_actions=artifact.recommended_next_actions,
        top_retained_items=resolved_outcome_snapshot.top_retained_items,
        reservation_summary=resolved_outcome_snapshot.reservation_summary,
        display_sections=display_sections,
        metadata={
            "display_policy_version": display_policy.version,
            "display_section_order": tuple(
                kind.value for kind in display_policy.section_order
            ),
            "display_omit_empty_sections": display_policy.omit_empty_sections,
            "display_retained_items_limit": display_policy.retained_items_display_limit,
            "display_decision_rationale_limit": (
                display_policy.decision_rationale_display_limit
            ),
            "display_recommended_next_actions_limit": (
                display_policy.recommended_next_actions_display_limit
            ),
            "display_section_count": len(display_sections),
            "retained_item_count": len(resolved_outcome_snapshot.top_retained_items),
            "display_retained_items_count": _section_line_count(
                display_sections,
                HeartbeatTerminalDisplaySectionKind.TOP_RETAINED_ITEMS,
            ),
            "display_retained_items_truncated": (
                len(resolved_outcome_snapshot.top_retained_items)
                > display_policy.retained_items_display_limit
            ),
            "display_decision_rationale_count": _section_line_count(
                display_sections,
                HeartbeatTerminalDisplaySectionKind.DECISION_RATIONALE,
            ),
            "display_decision_rationale_truncated": (
                len(artifact.decision_rationale)
                > display_policy.decision_rationale_display_limit
            ),
            "display_recommended_next_actions_count": _section_line_count(
                display_sections,
                HeartbeatTerminalDisplaySectionKind.RECOMMENDED_NEXT_ACTIONS,
            ),
            "display_recommended_next_actions_truncated": (
                len(artifact.recommended_next_actions)
                > display_policy.recommended_next_actions_display_limit
            ),
            "display_omitted_sections": tuple(
                kind.value
                for kind in HeartbeatTerminalDisplaySectionKind
                if kind not in {section.kind for section in display_sections}
            ),
        },
    )
    assert_heartbeat_terminal_payload_matches_aggregate(
        payload=payload,
        artifact=artifact,
        aggregate_result=aggregate_result,
    )
    return payload


def validate_heartbeat_terminal_payload(payload: HeartbeatTerminalPayload) -> None:
    """Validate one terminal payload contract."""

    if not isinstance(payload, HeartbeatTerminalPayload):
        raise TypeError(
            "Heartbeat terminal payload validation requires HeartbeatTerminalPayload."
        )
    if payload.final_decision != payload.candidate.final_decision:
        raise ValueError(
            "Heartbeat terminal payload final_decision must mirror candidate.final_decision."
        )
    if payload.consumer_readiness != payload.candidate.consumer_readiness:
        raise ValueError(
            "Heartbeat terminal payload consumer_readiness must mirror candidate.consumer_readiness."
        )
    if payload.final_decision == ConvergenceStatus.CONTINUE and payload.consumer_readiness not in {
        HeartbeatOutcomeConsumerReadiness.CONTINUE_ONLY,
        HeartbeatOutcomeConsumerReadiness.REMEDIATION_REQUIRED,
    }:
        raise ValueError(
            "Continue heartbeat terminal payloads must use a non-terminal consumer_readiness."
        )
    if payload.final_decision == ConvergenceStatus.CONVERGED and payload.consumer_readiness not in {
        HeartbeatOutcomeConsumerReadiness.TERMINAL_READY,
        HeartbeatOutcomeConsumerReadiness.TERMINAL_READY_WITH_RESERVATIONS,
    }:
        raise ValueError(
            "Converged heartbeat terminal payloads must use a terminal consumer_readiness."
        )
    if (
        payload.consumer_readiness == HeartbeatOutcomeConsumerReadiness.TERMINAL_READY
        and payload.reservation_summary is not None
    ):
        raise ValueError(
            "terminal_ready heartbeat terminal payloads must not expose reservation_summary."
        )
    if (
        payload.consumer_readiness == HeartbeatOutcomeConsumerReadiness.TERMINAL_READY
        and payload.top_retained_items
    ):
        raise ValueError(
            "terminal_ready heartbeat terminal payloads must not expose top_retained_items."
        )
    if (
        payload.consumer_readiness
        != HeartbeatOutcomeConsumerReadiness.TERMINAL_READY
        and payload.reservation_summary is None
    ):
        raise ValueError(
            "Non-clean heartbeat terminal payloads must expose reservation_summary."
        )
    seen_kinds: set[HeartbeatTerminalDisplaySectionKind] = set()
    for section in payload.display_sections:
        if section.kind in seen_kinds:
            raise ValueError(
                "Heartbeat terminal payload display_sections must not repeat section kinds."
            )
        seen_kinds.add(section.kind)
    if not payload.display_sections:
        raise ValueError("Heartbeat terminal payload requires at least one display section.")
    display_policy = _resolve_display_policy_from_metadata(payload.metadata)
    expected_sections = _build_display_sections(
        candidate_presentation=payload.candidate,
        decision_rationale=payload.decision_rationale,
        recommended_next_actions=payload.recommended_next_actions,
        reservation_summary=payload.reservation_summary,
        top_retained_items=payload.top_retained_items,
        display_policy=display_policy,
    )
    if payload.display_sections != expected_sections:
        raise ValueError(
            "Heartbeat terminal payload display_sections must match the controlled display policy."
        )
    _validate_display_metadata(payload, display_policy)


def assert_matching_heartbeat_terminal_payloads(
    *payloads: HeartbeatTerminalPayload | None,
    require_all_or_none: bool = False,
) -> HeartbeatTerminalPayload | None:
    """Validate and reconcile terminal payload references that should agree."""

    present_payloads = tuple(payload for payload in payloads if payload is not None)
    if require_all_or_none and present_payloads and len(present_payloads) != len(payloads):
        raise ValueError(
            "Heartbeat terminal payload references must either all be present or all be absent."
        )
    if not present_payloads:
        return None

    canonical_payload = present_payloads[0]
    validate_heartbeat_terminal_payload(canonical_payload)
    for payload in present_payloads[1:]:
        validate_heartbeat_terminal_payload(payload)
        if payload is not canonical_payload:
            raise ValueError(
                "Heartbeat terminal payload references must reuse the same object instance."
            )
        if payload != canonical_payload:
            raise ValueError("Heartbeat terminal payload references must agree exactly.")
    return canonical_payload


def assert_heartbeat_terminal_payload_matches_aggregate(
    *,
    payload: HeartbeatTerminalPayload,
    artifact: HeartbeatAggregateArtifact,
    aggregate_result: HeartbeatAggregateResult | None = None,
) -> None:
    """Assert that one terminal payload matches the canonical aggregate objects."""

    validate_heartbeat_terminal_payload(payload)
    attached_payload = assert_matching_heartbeat_terminal_payloads(
        artifact.terminal_payload,
        aggregate_result.terminal_payload if aggregate_result is not None else None,
        require_all_or_none=aggregate_result is not None,
    )
    if attached_payload is not None and attached_payload is not payload:
        raise ValueError(
            "Heartbeat terminal payload must match the attached aggregate terminal_payload."
        )
    resolved_candidate_presentation = assert_matching_heartbeat_candidate_presentations(
        artifact.candidate_presentation,
        aggregate_result.candidate_presentation if aggregate_result is not None else None,
        require_all_or_none=aggregate_result is not None,
    )
    resolved_outcome_snapshot = assert_matching_heartbeat_outcome_snapshots(
        artifact.outcome_snapshot,
        aggregate_result.outcome_snapshot if aggregate_result is not None else None,
        require_all_or_none=aggregate_result is not None,
    )
    if resolved_candidate_presentation is None:
        raise ValueError(
            "Heartbeat terminal payload requires aggregate candidate_presentation."
        )
    if resolved_outcome_snapshot is None:
        raise ValueError("Heartbeat terminal payload requires aggregate outcome_snapshot.")
    assert_heartbeat_candidate_presentation_matches_aggregate(
        presentation=resolved_candidate_presentation,
        artifact=artifact,
        aggregate_result=aggregate_result,
    )
    assert_heartbeat_outcome_matches_aggregate(
        snapshot=resolved_outcome_snapshot,
        artifact=artifact,
        aggregate_result=aggregate_result,
    )
    if payload.final_decision != resolved_outcome_snapshot.final_decision:
        raise ValueError(
            "Heartbeat terminal payload final_decision must reuse outcome_snapshot."
        )
    if payload.final_decision != artifact.final_decision:
        raise ValueError(
            "Heartbeat terminal payload final_decision must match aggregate artifact."
        )
    if (
        aggregate_result is not None
        and payload.final_decision != aggregate_result.recommended_outcome
    ):
        raise ValueError(
            "Heartbeat terminal payload final_decision must match aggregate result."
        )
    if payload.consumer_readiness != resolved_outcome_snapshot.consumer_readiness:
        raise ValueError(
            "Heartbeat terminal payload consumer_readiness must reuse outcome_snapshot."
        )
    if payload.candidate is not resolved_candidate_presentation:
        raise ValueError(
            "Heartbeat terminal payload candidate must reuse the attached candidate_presentation object."
        )
    if payload.candidate != resolved_candidate_presentation:
        raise ValueError(
            "Heartbeat terminal payload candidate must reuse candidate_presentation."
        )
    if payload.decision_rationale != artifact.decision_rationale:
        raise ValueError(
            "Heartbeat terminal payload decision_rationale must mirror aggregate artifact."
        )
    if payload.recommended_next_actions != artifact.recommended_next_actions:
        raise ValueError(
            "Heartbeat terminal payload recommended_next_actions must mirror aggregate artifact."
        )
    if payload.top_retained_items != resolved_outcome_snapshot.top_retained_items:
        raise ValueError(
            "Heartbeat terminal payload top_retained_items must reuse outcome_snapshot."
        )
    if payload.reservation_summary != resolved_outcome_snapshot.reservation_summary:
        raise ValueError(
            "Heartbeat terminal payload reservation_summary must reuse outcome_snapshot."
        )
    expected_sections = _build_display_sections(
        candidate_presentation=resolved_candidate_presentation,
        decision_rationale=artifact.decision_rationale,
        recommended_next_actions=artifact.recommended_next_actions,
        reservation_summary=resolved_outcome_snapshot.reservation_summary,
        top_retained_items=resolved_outcome_snapshot.top_retained_items,
        display_policy=_resolve_display_policy_from_metadata(payload.metadata),
    )
    if payload.display_sections != expected_sections:
        raise ValueError(
            "Heartbeat terminal payload display_sections must match the controlled display projection."
        )


def _validate_display_metadata(
    payload: HeartbeatTerminalPayload,
    display_policy: HeartbeatTerminalDisplayPolicy,
) -> None:
    metadata = payload.metadata if isinstance(payload.metadata, Mapping) else {}
    expected_omitted_sections = tuple(
        kind.value
        for kind in HeartbeatTerminalDisplaySectionKind
        if kind not in {section.kind for section in payload.display_sections}
    )
    expected_values = {
        "display_policy_version": display_policy.version,
        "display_section_order": tuple(kind.value for kind in display_policy.section_order),
        "display_omit_empty_sections": display_policy.omit_empty_sections,
        "display_retained_items_limit": display_policy.retained_items_display_limit,
        "display_decision_rationale_limit": display_policy.decision_rationale_display_limit,
        "display_recommended_next_actions_limit": (
            display_policy.recommended_next_actions_display_limit
        ),
        "display_section_count": len(payload.display_sections),
        "retained_item_count": len(payload.top_retained_items),
        "display_retained_items_count": _section_line_count(
            payload.display_sections,
            HeartbeatTerminalDisplaySectionKind.TOP_RETAINED_ITEMS,
        ),
        "display_retained_items_truncated": (
            len(payload.top_retained_items) > display_policy.retained_items_display_limit
        ),
        "display_decision_rationale_count": _section_line_count(
            payload.display_sections,
            HeartbeatTerminalDisplaySectionKind.DECISION_RATIONALE,
        ),
        "display_decision_rationale_truncated": (
            len(payload.decision_rationale) > display_policy.decision_rationale_display_limit
        ),
        "display_recommended_next_actions_count": _section_line_count(
            payload.display_sections,
            HeartbeatTerminalDisplaySectionKind.RECOMMENDED_NEXT_ACTIONS,
        ),
        "display_recommended_next_actions_truncated": (
            len(payload.recommended_next_actions)
            > display_policy.recommended_next_actions_display_limit
        ),
        "display_omitted_sections": expected_omitted_sections,
    }
    for key, expected_value in expected_values.items():
        if metadata.get(key) != expected_value:
            raise ValueError(
                "Heartbeat terminal payload metadata must match the controlled display projection "
                f"for {key}."
            )


def build_heartbeat_terminal_view(
    aggregate: HeartbeatAggregateResult | HeartbeatAggregateArtifact,
) -> HeartbeatTerminalPayload:
    """Resolve the single attached terminal-consumption payload for consumers."""

    return assert_heartbeat_terminal_consumption_attached(aggregate)


def assert_heartbeat_terminal_consumption_attached(
    aggregate: HeartbeatAggregateResult | HeartbeatAggregateArtifact,
) -> HeartbeatTerminalPayload:
    """Assert that the full terminal-consumption object chain is attached and aligned."""

    artifact, aggregate_result = _resolve_aggregate_inputs(aggregate)
    require_all_or_none = aggregate_result is not None
    candidate_snapshot = assert_matching_heartbeat_candidate_snapshots(
        artifact.candidate_snapshot,
        aggregate_result.candidate_snapshot if aggregate_result is not None else None,
        require_all_or_none=require_all_or_none,
    )
    convergence_profile = assert_matching_heartbeat_convergence_profiles(
        artifact.convergence_profile,
        aggregate_result.convergence_profile if aggregate_result is not None else None,
        require_all_or_none=require_all_or_none,
    )
    outcome_snapshot = assert_matching_heartbeat_outcome_snapshots(
        artifact.outcome_snapshot,
        aggregate_result.outcome_snapshot if aggregate_result is not None else None,
        require_all_or_none=require_all_or_none,
    )
    candidate_presentation = assert_matching_heartbeat_candidate_presentations(
        artifact.candidate_presentation,
        aggregate_result.candidate_presentation if aggregate_result is not None else None,
        require_all_or_none=require_all_or_none,
    )
    terminal_payload = assert_matching_heartbeat_terminal_payloads(
        artifact.terminal_payload,
        aggregate_result.terminal_payload if aggregate_result is not None else None,
        require_all_or_none=require_all_or_none,
    )
    missing_labels = [
        label
        for label, value in (
            ("candidate_snapshot", candidate_snapshot),
            ("convergence_profile", convergence_profile),
            ("outcome_snapshot", outcome_snapshot),
            ("candidate_presentation", candidate_presentation),
            ("terminal_payload", terminal_payload),
        )
        if value is None
    ]
    if missing_labels:
        raise ValueError(
            "Heartbeat terminal view requires fully attached terminal consumption objects: "
            + ", ".join(missing_labels)
            + "."
        )
    validate_heartbeat_convergence_profile(convergence_profile)
    assert_heartbeat_candidate_snapshot_matches_aggregate(
        snapshot=candidate_snapshot,
        artifact=artifact,
        aggregate_result=aggregate_result,
    )
    assert_heartbeat_outcome_matches_aggregate(
        snapshot=outcome_snapshot,
        artifact=artifact,
        aggregate_result=aggregate_result,
    )
    assert_heartbeat_candidate_presentation_matches_aggregate(
        presentation=candidate_presentation,
        artifact=artifact,
        aggregate_result=aggregate_result,
    )
    assert_heartbeat_terminal_payload_matches_aggregate(
        payload=terminal_payload,
        artifact=artifact,
        aggregate_result=aggregate_result,
    )
    return terminal_payload


def _resolve_aggregate_inputs(
    aggregate: HeartbeatAggregateResult | HeartbeatAggregateArtifact,
) -> tuple[HeartbeatAggregateArtifact, HeartbeatAggregateResult | None]:
    if isinstance(aggregate, HeartbeatAggregateResult):
        if aggregate.aggregate_artifact is None:
            raise ValueError(
                "Heartbeat terminal payload requires aggregate_result.aggregate_artifact."
            )
        return aggregate.aggregate_artifact, aggregate
    if isinstance(aggregate, HeartbeatAggregateArtifact):
        return aggregate, None
    raise TypeError(
        "Heartbeat terminal payload input must be HeartbeatAggregateResult "
        "or HeartbeatAggregateArtifact."
    )


def _build_display_sections(
    *,
    candidate_presentation: HeartbeatCandidatePresentation,
    decision_rationale: Sequence[str],
    recommended_next_actions: Sequence[str],
    reservation_summary: str | None,
    top_retained_items: Sequence[HeartbeatOutcomeRetainedItem],
    display_policy: HeartbeatTerminalDisplayPolicy,
) -> tuple[HeartbeatTerminalDisplaySection, ...]:
    candidate_lines = _build_candidate_section_lines(candidate_presentation)
    section_lines_by_kind = {
        HeartbeatTerminalDisplaySectionKind.CANDIDATE: candidate_lines,
        HeartbeatTerminalDisplaySectionKind.RESERVATION_SUMMARY: (
            (reservation_summary,) if reservation_summary is not None else ()
        ),
        HeartbeatTerminalDisplaySectionKind.TOP_RETAINED_ITEMS: tuple(
            _format_retained_item_line(item)
            for item in top_retained_items[: display_policy.retained_items_display_limit]
        ),
        HeartbeatTerminalDisplaySectionKind.DECISION_RATIONALE: tuple(
            _normalize_text_sequence(
                decision_rationale[: display_policy.decision_rationale_display_limit]
            )
        ),
        HeartbeatTerminalDisplaySectionKind.RECOMMENDED_NEXT_ACTIONS: tuple(
            _normalize_text_sequence(
                recommended_next_actions[
                    : display_policy.recommended_next_actions_display_limit
                ]
            )
        ),
    }
    section_titles = {
        HeartbeatTerminalDisplaySectionKind.CANDIDATE: "Candidate",
        HeartbeatTerminalDisplaySectionKind.RESERVATION_SUMMARY: "Reservation Summary",
        HeartbeatTerminalDisplaySectionKind.TOP_RETAINED_ITEMS: "Top Retained Items",
        HeartbeatTerminalDisplaySectionKind.DECISION_RATIONALE: "Decision Rationale",
        HeartbeatTerminalDisplaySectionKind.RECOMMENDED_NEXT_ACTIONS: "Recommended Next Actions",
    }
    sections: list[HeartbeatTerminalDisplaySection] = []
    for kind in display_policy.section_order:
        lines = section_lines_by_kind[kind]
        if display_policy.omit_empty_sections and not lines:
            continue
        sections.append(
            HeartbeatTerminalDisplaySection(
                kind=kind,
                title=section_titles[kind],
                lines=lines,
            )
        )
    return tuple(sections)


def _build_candidate_section_lines(
    candidate_presentation: HeartbeatCandidatePresentation,
) -> tuple[str, ...]:
    lines = [candidate_presentation.summary]
    if candidate_presentation.source_round is not None:
        lines.append(f"Source round: {candidate_presentation.source_round}")
    if candidate_presentation.supporting_context_refs:
        lines.append(
            "Supporting refs: "
            + ", ".join(candidate_presentation.supporting_context_refs)
        )
    if candidate_presentation.retained_issue_preview is not None:
        lines.append(
            "Retained issue preview: " + candidate_presentation.retained_issue_preview
        )
    if candidate_presentation.next_step_preview is not None:
        lines.append("Next step preview: " + candidate_presentation.next_step_preview)
    return tuple(lines)


def _format_retained_item_line(item: HeartbeatOutcomeRetainedItem) -> str:
    if item.summary:
        return item.summary
    severity_label = item.severity or "unspecified"
    blocker_label = ", blocker" if item.blocker else ""
    return f"{item.category.value} ({severity_label}{blocker_label})"


def _section_line_count(
    sections: Sequence[HeartbeatTerminalDisplaySection],
    kind: HeartbeatTerminalDisplaySectionKind,
) -> int:
    for section in sections:
        if section.kind == kind:
            return len(section.lines)
    return 0


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
                "Heartbeat terminal payload explicit "
                f"{object_label} must reuse the attached aggregate object."
            )


def _coerce_display_policy(
    display_policy: HeartbeatTerminalDisplayPolicy,
) -> HeartbeatTerminalDisplayPolicy:
    if isinstance(display_policy, HeartbeatTerminalDisplayPolicy):
        return display_policy
    raise TypeError(
        "Heartbeat terminal payload display_policy must be HeartbeatTerminalDisplayPolicy."
    )


def _resolve_display_policy_from_metadata(
    metadata: Mapping[str, object] | object,
) -> HeartbeatTerminalDisplayPolicy:
    metadata_mapping = metadata if isinstance(metadata, Mapping) else {}
    section_order_values = metadata_mapping.get("display_section_order")
    if isinstance(section_order_values, Sequence) and not isinstance(section_order_values, str):
        section_order = tuple(
            HeartbeatTerminalDisplaySectionKind(str(value)) for value in section_order_values
        )
    else:
        section_order = DEFAULT_HEARTBEAT_TERMINAL_DISPLAY_POLICY.section_order
    return HeartbeatTerminalDisplayPolicy(
        version=str(
            metadata_mapping.get(
                "display_policy_version",
                DEFAULT_HEARTBEAT_TERMINAL_DISPLAY_POLICY.version,
            )
        ),
        section_order=section_order,
        omit_empty_sections=bool(
            metadata_mapping.get(
                "display_omit_empty_sections",
                DEFAULT_HEARTBEAT_TERMINAL_DISPLAY_POLICY.omit_empty_sections,
            )
        ),
        retained_items_display_limit=int(
            metadata_mapping.get(
                "display_retained_items_limit",
                DEFAULT_HEARTBEAT_TERMINAL_DISPLAY_POLICY.retained_items_display_limit,
            )
        ),
        decision_rationale_display_limit=int(
            metadata_mapping.get(
                "display_decision_rationale_limit",
                DEFAULT_HEARTBEAT_TERMINAL_DISPLAY_POLICY.decision_rationale_display_limit,
            )
        ),
        recommended_next_actions_display_limit=int(
            metadata_mapping.get(
                "display_recommended_next_actions_limit",
                DEFAULT_HEARTBEAT_TERMINAL_DISPLAY_POLICY.recommended_next_actions_display_limit,
            )
        ),
    )
