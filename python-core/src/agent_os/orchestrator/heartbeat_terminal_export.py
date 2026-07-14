from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from agent_os.protocols.heartbeat_terminal_export_contract import (
    HEARTBEAT_TERMINAL_EXPORT_SCHEMA_ID,
    assert_heartbeat_terminal_export_body_contract,
)
from agent_os.orchestrator.convergence import (
    HeartbeatAggregateArtifact,
    HeartbeatAggregateResult,
)
from agent_os.orchestrator.heartbeat_candidate_presentation import (
    HeartbeatCandidatePresentation,
)
from agent_os.orchestrator.heartbeat_outcome_snapshot import (
    HeartbeatOutcomeRetainedItem,
)
from agent_os.orchestrator.heartbeat_terminal_payload import (
    HeartbeatTerminalDisplaySection,
    HeartbeatTerminalDisplaySectionKind,
    HeartbeatTerminalPayload,
    build_heartbeat_terminal_view,
    validate_heartbeat_terminal_payload,
)

@dataclass(frozen=True, slots=True)
class HeartbeatTerminalExportCandidatePayload:
    """Transport-safe projection of the controlled heartbeat candidate presentation."""

    candidate_id: str
    checkpoint_id: str
    summary: str
    source_round: int | None = None
    supporting_context_refs: tuple[str, ...] = ()
    final_decision: str = "continue"
    semantic_state: str = "continue_due_to_insufficient_support"
    reservation_level: str = "none"
    consumer_readiness: str = "continue_only"
    retained_issue_preview: str | None = None
    next_step_preview: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _normalize_required_text(self.candidate_id))
        object.__setattr__(self, "checkpoint_id", _normalize_required_text(self.checkpoint_id))
        object.__setattr__(self, "summary", _normalize_required_text(self.summary))
        object.__setattr__(
            self,
            "source_round",
            None if self.source_round is None else int(self.source_round),
        )
        object.__setattr__(
            self,
            "supporting_context_refs",
            _normalize_text_sequence(self.supporting_context_refs),
        )
        object.__setattr__(self, "final_decision", _normalize_required_text(self.final_decision))
        object.__setattr__(self, "semantic_state", _normalize_required_text(self.semantic_state))
        object.__setattr__(
            self,
            "reservation_level",
            _normalize_required_text(self.reservation_level),
        )
        object.__setattr__(
            self,
            "consumer_readiness",
            _normalize_required_text(self.consumer_readiness),
        )
        object.__setattr__(
            self,
            "retained_issue_preview",
            _normalize_optional_text(self.retained_issue_preview),
        )
        object.__setattr__(
            self,
            "next_step_preview",
            _normalize_optional_text(self.next_step_preview),
        )


@dataclass(frozen=True, slots=True)
class HeartbeatTerminalExportRetainedItemPayload:
    """Transport-safe projection of one retained terminal item."""

    category: str
    severity: str | None = None
    blocker: bool = False
    priority_rank: int = 0
    supporting_roles: tuple[str, ...] = ()
    summary: str | None = None
    impact_on_decision: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", _normalize_required_text(self.category))
        object.__setattr__(self, "severity", _normalize_optional_text(self.severity))
        object.__setattr__(self, "blocker", bool(self.blocker))
        object.__setattr__(self, "priority_rank", int(self.priority_rank or 0))
        object.__setattr__(
            self,
            "supporting_roles",
            _normalize_text_sequence(self.supporting_roles),
        )
        object.__setattr__(self, "summary", _normalize_optional_text(self.summary))
        object.__setattr__(
            self,
            "impact_on_decision",
            _normalize_optional_text(self.impact_on_decision),
        )


@dataclass(frozen=True, slots=True)
class HeartbeatTerminalExportDisplaySectionPayload:
    """Transport-safe projection of one terminal display section."""

    kind: str
    title: str
    lines: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _normalize_required_text(self.kind))
        object.__setattr__(self, "title", _normalize_required_text(self.title))
        lines = _normalize_text_sequence(self.lines)
        if not lines:
            raise ValueError(
                "Heartbeat terminal export display section requires at least one line."
            )
        object.__setattr__(self, "lines", lines)


@dataclass(frozen=True, slots=True)
class HeartbeatTerminalExportPayload:
    """Stable transport-safe heartbeat terminal export contract."""

    final_decision: str
    consumer_readiness: str
    candidate: HeartbeatTerminalExportCandidatePayload
    decision_rationale: tuple[str, ...] = ()
    recommended_next_actions: tuple[str, ...] = ()
    top_retained_items: tuple[HeartbeatTerminalExportRetainedItemPayload, ...] = ()
    reservation_summary: str | None = None
    display_sections: tuple[HeartbeatTerminalExportDisplaySectionPayload, ...] = ()
    display_metadata: Mapping[str, object] = field(default_factory=dict)
    schema_id: str = HEARTBEAT_TERMINAL_EXPORT_SCHEMA_ID

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, HeartbeatTerminalExportCandidatePayload):
            raise TypeError(
                "Heartbeat terminal export payload requires HeartbeatTerminalExportCandidatePayload."
            )
        object.__setattr__(self, "final_decision", _normalize_required_text(self.final_decision))
        object.__setattr__(
            self,
            "consumer_readiness",
            _normalize_required_text(self.consumer_readiness),
        )
        object.__setattr__(
            self,
            "decision_rationale",
            _normalize_text_sequence(self.decision_rationale),
        )
        object.__setattr__(
            self,
            "recommended_next_actions",
            _normalize_text_sequence(self.recommended_next_actions),
        )
        object.__setattr__(self, "top_retained_items", tuple(self.top_retained_items))
        object.__setattr__(
            self,
            "reservation_summary",
            _normalize_optional_text(self.reservation_summary),
        )
        object.__setattr__(self, "display_sections", tuple(self.display_sections))
        object.__setattr__(
            self,
            "display_metadata",
            _normalize_transport_mapping(self.display_metadata),
        )
        object.__setattr__(self, "schema_id", _normalize_required_text(self.schema_id))
        validate_heartbeat_terminal_export_payload(self)


def build_heartbeat_terminal_export(
    source: HeartbeatTerminalPayload | HeartbeatAggregateResult | HeartbeatAggregateArtifact,
) -> HeartbeatTerminalExportPayload:
    """Build the single transport-safe heartbeat terminal export for boundary consumers."""

    return project_heartbeat_terminal_payload(_resolve_terminal_export_source(source))


def validate_heartbeat_terminal_export_payload(
    payload: HeartbeatTerminalExportPayload,
) -> None:
    """Validate one transport-safe export payload without reintroducing new semantics."""

    if not isinstance(payload, HeartbeatTerminalExportPayload):
        raise TypeError(
            "Heartbeat terminal export validation requires HeartbeatTerminalExportPayload."
        )
    if payload.final_decision != payload.candidate.final_decision:
        raise ValueError(
            "Heartbeat terminal export final_decision must match candidate.final_decision."
        )
    if payload.consumer_readiness != payload.candidate.consumer_readiness:
        raise ValueError(
            "Heartbeat terminal export consumer_readiness must match candidate.consumer_readiness."
        )
    for item in payload.top_retained_items:
        if not isinstance(item, HeartbeatTerminalExportRetainedItemPayload):
            raise TypeError(
                "Heartbeat terminal export top_retained_items must use "
                "HeartbeatTerminalExportRetainedItemPayload."
            )
    section_kinds: list[str] = []
    for section in payload.display_sections:
        if not isinstance(section, HeartbeatTerminalExportDisplaySectionPayload):
            raise TypeError(
                "Heartbeat terminal export display_sections must use "
                "HeartbeatTerminalExportDisplaySectionPayload."
            )
        section_kinds.append(section.kind)
    if not section_kinds:
        raise ValueError("Heartbeat terminal export requires at least one display section.")
    if len(section_kinds) != len(set(section_kinds)):
        raise ValueError(
            "Heartbeat terminal export display_sections must not repeat section kinds."
        )
    _validate_terminal_export_display_metadata(payload)


def serialize_heartbeat_terminal_export(
    payload: HeartbeatTerminalExportPayload,
) -> Mapping[str, object]:
    """Serialize one validated export payload into a JSON-safe boundary mapping."""

    validate_heartbeat_terminal_export_payload(payload)
    serialized_payload = {
        "schema_id": payload.schema_id,
        "final_decision": payload.final_decision,
        "consumer_readiness": payload.consumer_readiness,
        "candidate": _serialize_heartbeat_terminal_candidate(payload.candidate),
        "decision_rationale": list(payload.decision_rationale),
        "recommended_next_actions": list(payload.recommended_next_actions),
        "top_retained_items": [
            _serialize_heartbeat_terminal_retained_item(item)
            for item in payload.top_retained_items
        ],
        "reservation_summary": payload.reservation_summary,
        "display_sections": [
            _serialize_heartbeat_terminal_display_section(section)
            for section in payload.display_sections
        ],
        "display_metadata": _serialize_transport_mapping(payload.display_metadata),
    }
    assert_heartbeat_terminal_export_body_contract(serialized_payload)
    return serialized_payload


def project_heartbeat_terminal_payload(
    payload: HeartbeatTerminalPayload,
    *,
    projected_candidate: HeartbeatTerminalExportCandidatePayload | None = None,
) -> HeartbeatTerminalExportPayload:
    """Project one validated terminal payload into a transport-safe export payload."""

    if not isinstance(payload, HeartbeatTerminalPayload):
        raise TypeError(
            "Heartbeat terminal export projection requires HeartbeatTerminalPayload."
        )
    validate_heartbeat_terminal_payload(payload)
    canonical_candidate = project_heartbeat_terminal_candidate(payload.candidate)
    if projected_candidate is None:
        projected_candidate = canonical_candidate
    elif projected_candidate != canonical_candidate:
        raise ValueError(
            "Heartbeat terminal export candidate projection must match terminal_payload.candidate."
        )
    return HeartbeatTerminalExportPayload(
        final_decision=payload.final_decision.value,
        consumer_readiness=payload.consumer_readiness.value,
        candidate=projected_candidate,
        decision_rationale=payload.decision_rationale,
        recommended_next_actions=payload.recommended_next_actions,
        top_retained_items=tuple(
            project_heartbeat_terminal_retained_item(item)
            for item in payload.top_retained_items
        ),
        reservation_summary=payload.reservation_summary,
        display_sections=tuple(
            project_heartbeat_terminal_display_section(section)
            for section in payload.display_sections
        ),
        display_metadata=payload.metadata,
    )


def project_heartbeat_terminal_candidate(
    presentation: HeartbeatCandidatePresentation | None,
) -> HeartbeatTerminalExportCandidatePayload | None:
    """Project one controlled candidate presentation into a transport-safe payload."""

    if presentation is None:
        return None
    if not isinstance(presentation, HeartbeatCandidatePresentation):
        raise TypeError(
            "Heartbeat terminal export candidate projection requires "
            "HeartbeatCandidatePresentation."
        )
    return HeartbeatTerminalExportCandidatePayload(
        candidate_id=presentation.candidate_id,
        checkpoint_id=presentation.checkpoint_id,
        summary=presentation.summary,
        source_round=presentation.source_round,
        supporting_context_refs=presentation.supporting_context_refs,
        final_decision=presentation.final_decision.value,
        semantic_state=presentation.semantic_state.value,
        reservation_level=presentation.reservation_level.value,
        consumer_readiness=presentation.consumer_readiness.value,
        retained_issue_preview=presentation.retained_issue_preview,
        next_step_preview=presentation.next_step_preview,
    )


def project_heartbeat_terminal_retained_item(
    item: HeartbeatOutcomeRetainedItem,
) -> HeartbeatTerminalExportRetainedItemPayload:
    """Project one retained item into a transport-safe payload."""

    return HeartbeatTerminalExportRetainedItemPayload(
        category=item.category.value,
        severity=item.severity,
        blocker=item.blocker,
        priority_rank=item.priority_rank,
        supporting_roles=item.supporting_roles,
        summary=item.summary,
        impact_on_decision=item.impact_on_decision,
    )


def project_heartbeat_terminal_display_section(
    section: HeartbeatTerminalDisplaySection,
) -> HeartbeatTerminalExportDisplaySectionPayload:
    """Project one display section into a transport-safe payload."""

    return HeartbeatTerminalExportDisplaySectionPayload(
        kind=section.kind.value,
        title=section.title,
        lines=section.lines,
    )


def _resolve_terminal_export_source(
    source: HeartbeatTerminalPayload | HeartbeatAggregateResult | HeartbeatAggregateArtifact,
) -> HeartbeatTerminalPayload:
    if isinstance(source, HeartbeatTerminalPayload):
        validate_heartbeat_terminal_payload(source)
        return source
    if isinstance(source, (HeartbeatAggregateResult, HeartbeatAggregateArtifact)):
        return build_heartbeat_terminal_view(source)
    raise TypeError(
        "Heartbeat terminal export input must be HeartbeatTerminalPayload, "
        "HeartbeatAggregateResult, or HeartbeatAggregateArtifact."
    )


def _validate_terminal_export_display_metadata(
    payload: HeartbeatTerminalExportPayload,
) -> None:
    metadata = payload.display_metadata if isinstance(payload.display_metadata, Mapping) else {}
    required_keys = (
        "display_policy_version",
        "display_section_order",
        "display_omit_empty_sections",
        "display_retained_items_limit",
        "display_decision_rationale_limit",
        "display_recommended_next_actions_limit",
        "display_section_count",
        "retained_item_count",
        "display_retained_items_count",
        "display_retained_items_truncated",
        "display_decision_rationale_count",
        "display_decision_rationale_truncated",
        "display_recommended_next_actions_count",
        "display_recommended_next_actions_truncated",
        "display_omitted_sections",
    )
    missing_keys = tuple(key for key in required_keys if key not in metadata)
    if missing_keys:
        raise ValueError(
            "Heartbeat terminal export display_metadata is missing required keys: "
            + ", ".join(missing_keys)
        )
    section_order_values = metadata.get("display_section_order")
    if not isinstance(section_order_values, Sequence) or isinstance(section_order_values, str):
        raise ValueError(
            "Heartbeat terminal export display_metadata.display_section_order must be a sequence."
        )
    normalized_section_order = tuple(str(value) for value in section_order_values)
    known_section_kinds = tuple(
        kind.value for kind in HeartbeatTerminalDisplaySectionKind
    )
    if set(normalized_section_order) != set(known_section_kinds):
        raise ValueError(
            "Heartbeat terminal export display_metadata.display_section_order must cover every "
            "known display section kind exactly once."
        )
    if len(normalized_section_order) != len(set(normalized_section_order)):
        raise ValueError(
            "Heartbeat terminal export display_metadata.display_section_order must not repeat "
            "section kinds."
        )
    display_policy_version = str(metadata.get("display_policy_version", "")).strip()
    if not display_policy_version:
        raise ValueError(
            "Heartbeat terminal export display_metadata.display_policy_version must be present."
        )
    if metadata.get("display_omit_empty_sections") is not True:
        raise ValueError(
            "Heartbeat terminal export display_metadata.display_omit_empty_sections must be True."
        )
    retained_limit = int(metadata.get("display_retained_items_limit"))
    rationale_limit = int(metadata.get("display_decision_rationale_limit"))
    next_actions_limit = int(metadata.get("display_recommended_next_actions_limit"))
    if min(retained_limit, rationale_limit, next_actions_limit) <= 0:
        raise ValueError(
            "Heartbeat terminal export display limits must remain positive integers."
        )
    actual_section_kinds = tuple(section.kind for section in payload.display_sections)
    expected_omitted_sections = tuple(
        kind for kind in known_section_kinds if kind not in actual_section_kinds
    )
    expected_rendered_sections = tuple(
        kind for kind in normalized_section_order if kind not in expected_omitted_sections
    )
    if actual_section_kinds != expected_rendered_sections:
        raise ValueError(
            "Heartbeat terminal export display_sections must preserve the declared section order."
        )
    expected_values = {
        "display_section_count": len(payload.display_sections),
        "retained_item_count": len(payload.top_retained_items),
        "display_retained_items_count": _section_line_count(
            payload.display_sections,
            HeartbeatTerminalDisplaySectionKind.TOP_RETAINED_ITEMS.value,
        ),
        "display_retained_items_truncated": len(payload.top_retained_items) > retained_limit,
        "display_decision_rationale_count": _section_line_count(
            payload.display_sections,
            HeartbeatTerminalDisplaySectionKind.DECISION_RATIONALE.value,
        ),
        "display_decision_rationale_truncated": (
            len(payload.decision_rationale) > rationale_limit
        ),
        "display_recommended_next_actions_count": _section_line_count(
            payload.display_sections,
            HeartbeatTerminalDisplaySectionKind.RECOMMENDED_NEXT_ACTIONS.value,
        ),
        "display_recommended_next_actions_truncated": (
            len(payload.recommended_next_actions) > next_actions_limit
        ),
        "display_omitted_sections": expected_omitted_sections,
    }
    for key, expected_value in expected_values.items():
        if metadata.get(key) != expected_value:
            raise ValueError(
                "Heartbeat terminal export display_metadata "
                f"{key} must match the rendered terminal export projection."
            )


def _serialize_heartbeat_terminal_candidate(
    candidate: HeartbeatTerminalExportCandidatePayload,
) -> Mapping[str, object]:
    return {
        "candidate_id": candidate.candidate_id,
        "checkpoint_id": candidate.checkpoint_id,
        "summary": candidate.summary,
        "source_round": candidate.source_round,
        "supporting_context_refs": list(candidate.supporting_context_refs),
        "final_decision": candidate.final_decision,
        "semantic_state": candidate.semantic_state,
        "reservation_level": candidate.reservation_level,
        "consumer_readiness": candidate.consumer_readiness,
        "retained_issue_preview": candidate.retained_issue_preview,
        "next_step_preview": candidate.next_step_preview,
    }


def _serialize_heartbeat_terminal_retained_item(
    item: HeartbeatTerminalExportRetainedItemPayload,
) -> Mapping[str, object]:
    return {
        "category": item.category,
        "severity": item.severity,
        "blocker": item.blocker,
        "priority_rank": item.priority_rank,
        "supporting_roles": list(item.supporting_roles),
        "summary": item.summary,
        "impact_on_decision": item.impact_on_decision,
    }


def _serialize_heartbeat_terminal_display_section(
    section: HeartbeatTerminalExportDisplaySectionPayload,
) -> Mapping[str, object]:
    return {
        "kind": section.kind,
        "title": section.title,
        "lines": list(section.lines),
    }


def _normalize_required_text(value: object) -> str:
    normalized_value = str(value).strip()
    if not normalized_value:
        raise ValueError("Heartbeat terminal export requires non-empty text fields.")
    return normalized_value


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized_value = str(value).strip()
    return normalized_value or None


def _normalize_text_sequence(values: Sequence[object]) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in values if str(value).strip())


def _normalize_transport_mapping(metadata: Mapping[str, object] | object) -> Mapping[str, object]:
    if not isinstance(metadata, Mapping):
        return {}
    return {
        str(key): _normalize_transport_value(value)
        for key, value in metadata.items()
    }


def _serialize_transport_mapping(metadata: Mapping[str, object] | object) -> Mapping[str, object]:
    if not isinstance(metadata, Mapping):
        return {}
    return {
        str(key): _serialize_transport_value(value)
        for key, value in metadata.items()
    }


def _normalize_transport_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    enum_value = getattr(value, "value", None)
    if enum_value is not None and isinstance(enum_value, (str, int, float, bool)):
        return enum_value
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_transport_value(nested_value)
            for key, nested_value in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_normalize_transport_value(item) for item in value)
    raise TypeError(
        "Heartbeat terminal export metadata must use transport-safe scalar, sequence, or mapping values."
    )


def _serialize_transport_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _serialize_transport_value(nested_value)
            for key, nested_value in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_serialize_transport_value(item) for item in value]
    enum_value = getattr(value, "value", None)
    if enum_value is not None and isinstance(enum_value, (str, int, float, bool)):
        return enum_value
    raise TypeError(
        "Heartbeat terminal export serialization requires JSON-safe scalar, sequence, or mapping values."
    )


def _section_line_count(
    sections: Sequence[HeartbeatTerminalExportDisplaySectionPayload],
    kind: str,
) -> int:
    for section in sections:
        if section.kind == kind:
            return len(section.lines)
    return 0
