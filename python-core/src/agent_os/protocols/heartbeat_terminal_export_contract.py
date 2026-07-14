from __future__ import annotations

from collections.abc import Mapping, Sequence

from agent_os.domain.ports.protocol import ProtocolEnvelope as RuntimeProtocolEnvelope
from agent_os.protocols.heartbeat_terminal_shared_manifest import (
    HEARTBEAT_TERMINAL_DISPLAY_METADATA_NON_OMITTABLE_SECTIONS,
    HEARTBEAT_TERMINAL_DISPLAY_METADATA_OMISSION_METADATA_KEY,
    HEARTBEAT_TERMINAL_DISPLAY_METADATA_OMIT_EMPTY_SECTIONS_KEY,
    HEARTBEAT_TERMINAL_DISPLAY_METADATA_OMIT_EMPTY_SECTIONS_VALUE,
    HEARTBEAT_TERMINAL_DISPLAY_METADATA_POLICY_VERSION_KEY,
    HEARTBEAT_TERMINAL_DISPLAY_METADATA_RETAINED_ITEM_COUNT_KEY,
    HEARTBEAT_TERMINAL_DISPLAY_METADATA_SECTION_COUNT_KEY,
    HEARTBEAT_TERMINAL_DISPLAY_METADATA_SECTION_ORDER_KEY,
    HEARTBEAT_TERMINAL_DISPLAY_METADATA_TRUNCATION_RULES,
    HEARTBEAT_TERMINAL_ENVELOPE_BODY_ATTRIBUTE,
    HEARTBEAT_TERMINAL_EXPORT_BREAKING_CHANGES,
    HEARTBEAT_TERMINAL_EXPORT_CANDIDATE_REQUIRED_FIELDS,
    HEARTBEAT_TERMINAL_EXPORT_COMPATIBLE_ADDITIONS,
    HEARTBEAT_TERMINAL_EXPORT_DISPLAY_METADATA_REQUIRED_FIELDS,
    HEARTBEAT_TERMINAL_EXPORT_REQUIRED_FIELDS,
    HEARTBEAT_TERMINAL_EXPORT_SCHEMA_ID,
    HEARTBEAT_TERMINAL_EXPORT_SECTION_KIND_VOCABULARY,
    HEARTBEAT_TERMINAL_PROTOCOL_KIND,
    HEARTBEAT_TERMINAL_PROTOCOL_VERSION,
)


def assert_heartbeat_terminal_export_body_contract(payload: Mapping[str, object]) -> None:
    """Validate the serialized heartbeat terminal export contract for external consumers."""

    payload_mapping = _require_mapping(payload, field_name="payload")
    _require_fields(
        payload_mapping,
        HEARTBEAT_TERMINAL_EXPORT_REQUIRED_FIELDS,
        field_name="payload",
    )
    if payload_mapping["schema_id"] != HEARTBEAT_TERMINAL_EXPORT_SCHEMA_ID:
        raise ValueError(
            "Heartbeat terminal export payload schema_id is incompatible with the current "
            "contract baseline."
        )
    final_decision = _require_non_empty_text(
        payload_mapping["final_decision"],
        field_name="payload.final_decision",
    )
    consumer_readiness = _require_non_empty_text(
        payload_mapping["consumer_readiness"],
        field_name="payload.consumer_readiness",
    )
    candidate = _require_mapping(payload_mapping["candidate"], field_name="payload.candidate")
    _require_fields(
        candidate,
        HEARTBEAT_TERMINAL_EXPORT_CANDIDATE_REQUIRED_FIELDS,
        field_name="payload.candidate",
    )
    if (
        _require_non_empty_text(
            candidate["final_decision"],
            field_name="payload.candidate.final_decision",
        )
        != final_decision
    ):
        raise ValueError(
            "Heartbeat terminal export payload.candidate.final_decision must match "
            "payload.final_decision."
        )
    if (
        _require_non_empty_text(
            candidate["consumer_readiness"],
            field_name="payload.candidate.consumer_readiness",
        )
        != consumer_readiness
    ):
        raise ValueError(
            "Heartbeat terminal export payload.candidate.consumer_readiness must match "
            "payload.consumer_readiness."
        )
    _require_non_empty_text(candidate["candidate_id"], field_name="payload.candidate.candidate_id")
    _require_non_empty_text(candidate["checkpoint_id"], field_name="payload.candidate.checkpoint_id")
    _require_non_empty_text(candidate["summary"], field_name="payload.candidate.summary")
    _require_non_empty_text(
        candidate["semantic_state"],
        field_name="payload.candidate.semantic_state",
    )
    _require_non_empty_text(
        candidate["reservation_level"],
        field_name="payload.candidate.reservation_level",
    )
    _require_optional_int(candidate["source_round"], field_name="payload.candidate.source_round")
    _require_text_sequence(
        candidate["supporting_context_refs"],
        field_name="payload.candidate.supporting_context_refs",
    )
    _require_optional_text(
        candidate["retained_issue_preview"],
        field_name="payload.candidate.retained_issue_preview",
    )
    _require_optional_text(
        candidate["next_step_preview"],
        field_name="payload.candidate.next_step_preview",
    )
    decision_rationale = _require_text_sequence(
        payload_mapping["decision_rationale"],
        field_name="payload.decision_rationale",
    )
    recommended_next_actions = _require_text_sequence(
        payload_mapping["recommended_next_actions"],
        field_name="payload.recommended_next_actions",
    )
    top_retained_items = _require_sequence_of_mappings(
        payload_mapping["top_retained_items"],
        field_name="payload.top_retained_items",
    )
    for index, item in enumerate(top_retained_items):
        _require_non_empty_text(
            item.get("category"),
            field_name=f"payload.top_retained_items[{index}].category",
        )
        _require_optional_text(
            item.get("severity"),
            field_name=f"payload.top_retained_items[{index}].severity",
        )
        _require_bool(item.get("blocker"), field_name=f"payload.top_retained_items[{index}].blocker")
        _require_int(
            item.get("priority_rank"),
            field_name=f"payload.top_retained_items[{index}].priority_rank",
        )
        _require_text_sequence(
            item.get("supporting_roles", ()),
            field_name=f"payload.top_retained_items[{index}].supporting_roles",
        )
        _require_optional_text(
            item.get("summary"),
            field_name=f"payload.top_retained_items[{index}].summary",
        )
        _require_optional_text(
            item.get("impact_on_decision"),
            field_name=f"payload.top_retained_items[{index}].impact_on_decision",
        )
    _require_optional_text(
        payload_mapping["reservation_summary"],
        field_name="payload.reservation_summary",
    )
    display_sections = _require_sequence_of_mappings(
        payload_mapping["display_sections"],
        field_name="payload.display_sections",
    )
    if not display_sections:
        raise ValueError("Heartbeat terminal export payload.display_sections must not be empty.")
    actual_section_kinds: list[str] = []
    for index, section in enumerate(display_sections):
        kind = _require_non_empty_text(
            section.get("kind"),
            field_name=f"payload.display_sections[{index}].kind",
        )
        _require_non_empty_text(
            section.get("title"),
            field_name=f"payload.display_sections[{index}].title",
        )
        lines = _require_text_sequence(
            section.get("lines", ()),
            field_name=f"payload.display_sections[{index}].lines",
        )
        if not lines:
            raise ValueError(
                f"Heartbeat terminal export payload.display_sections[{index}].lines must not be empty."
            )
        actual_section_kinds.append(kind)
    if len(actual_section_kinds) != len(set(actual_section_kinds)):
        raise ValueError(
            "Heartbeat terminal export payload.display_sections must not repeat section kinds."
        )
    metadata = _require_mapping(
        payload_mapping["display_metadata"],
        field_name="payload.display_metadata",
    )
    _require_fields(
        metadata,
        HEARTBEAT_TERMINAL_EXPORT_DISPLAY_METADATA_REQUIRED_FIELDS,
        field_name="payload.display_metadata",
    )
    _require_non_empty_text(
        metadata[HEARTBEAT_TERMINAL_DISPLAY_METADATA_POLICY_VERSION_KEY],
        field_name=(
            "payload.display_metadata."
            f"{HEARTBEAT_TERMINAL_DISPLAY_METADATA_POLICY_VERSION_KEY}"
        ),
    )
    if (
        metadata[HEARTBEAT_TERMINAL_DISPLAY_METADATA_OMIT_EMPTY_SECTIONS_KEY]
        is not HEARTBEAT_TERMINAL_DISPLAY_METADATA_OMIT_EMPTY_SECTIONS_VALUE
    ):
        raise ValueError(
            "Heartbeat terminal export display contract requires "
            f"{HEARTBEAT_TERMINAL_DISPLAY_METADATA_OMIT_EMPTY_SECTIONS_KEY}="
            f"{HEARTBEAT_TERMINAL_DISPLAY_METADATA_OMIT_EMPTY_SECTIONS_VALUE!s}."
        )
    display_section_order = _require_text_sequence(
        metadata[HEARTBEAT_TERMINAL_DISPLAY_METADATA_SECTION_ORDER_KEY],
        field_name=(
            "payload.display_metadata."
            f"{HEARTBEAT_TERMINAL_DISPLAY_METADATA_SECTION_ORDER_KEY}"
        ),
    )
    if set(display_section_order) != set(HEARTBEAT_TERMINAL_EXPORT_SECTION_KIND_VOCABULARY):
        raise ValueError(
            "Heartbeat terminal export display_section_order must cover the full section vocabulary."
        )
    if len(display_section_order) != len(set(display_section_order)):
        raise ValueError(
            "Heartbeat terminal export display_section_order must not repeat section kinds."
        )
    display_omitted_sections = _require_text_sequence(
        metadata[HEARTBEAT_TERMINAL_DISPLAY_METADATA_OMISSION_METADATA_KEY],
        field_name=(
            "payload.display_metadata."
            f"{HEARTBEAT_TERMINAL_DISPLAY_METADATA_OMISSION_METADATA_KEY}"
        ),
    )
    omitted_non_omittable_sections = tuple(
        section
        for section in HEARTBEAT_TERMINAL_DISPLAY_METADATA_NON_OMITTABLE_SECTIONS
        if section in display_omitted_sections
    )
    if omitted_non_omittable_sections:
        raise ValueError(
            "Heartbeat terminal export display_omitted_sections must not omit "
            + ", ".join(omitted_non_omittable_sections)
            + "."
        )
    if not set(display_omitted_sections).issubset(
        set(HEARTBEAT_TERMINAL_EXPORT_SECTION_KIND_VOCABULARY)
    ):
        raise ValueError(
            "Heartbeat terminal export display_omitted_sections contains unknown section kinds."
        )
    expected_omitted_sections = [
        kind
        for kind in HEARTBEAT_TERMINAL_EXPORT_SECTION_KIND_VOCABULARY
        if kind not in actual_section_kinds
    ]
    if list(display_omitted_sections) != expected_omitted_sections:
        raise ValueError(
            "Heartbeat terminal export display_omitted_sections must exactly match the omitted "
            "section vocabulary order."
        )
    expected_rendered_order = [
        kind for kind in display_section_order if kind not in display_omitted_sections
    ]
    if list(actual_section_kinds) != expected_rendered_order:
        raise ValueError(
            "Heartbeat terminal export display_sections must preserve display_section_order after "
            "omitting empty sections."
        )
    collection_values = {
        "top_retained_items": top_retained_items,
        "decision_rationale": decision_rationale,
        "recommended_next_actions": recommended_next_actions,
    }
    expected_values = {
        HEARTBEAT_TERMINAL_DISPLAY_METADATA_SECTION_COUNT_KEY: len(display_sections),
        HEARTBEAT_TERMINAL_DISPLAY_METADATA_RETAINED_ITEM_COUNT_KEY: len(top_retained_items),
        HEARTBEAT_TERMINAL_DISPLAY_METADATA_OMISSION_METADATA_KEY: expected_omitted_sections,
    }
    for truncation_key, truncation_rule in HEARTBEAT_TERMINAL_DISPLAY_METADATA_TRUNCATION_RULES.items():
        limit_value = _require_positive_int(
            metadata[truncation_rule["limit_key"]],
            field_name=f"payload.display_metadata.{truncation_rule['limit_key']}",
        )
        collection_items = collection_values[truncation_rule["collection_field"]]
        expected_values[truncation_rule["count_key"]] = _serialized_section_line_count(
            display_sections,
            truncation_rule["section_kind"],
        )
        expected_values[truncation_key] = len(collection_items) > limit_value
    for key, expected_value in expected_values.items():
        if metadata[key] != expected_value:
            raise ValueError(
                f"Heartbeat terminal export display_metadata.{key} must match the serialized "
                "preview contract."
            )


def assert_heartbeat_terminal_protocol_envelope_contract(
    envelope: RuntimeProtocolEnvelope,
) -> None:
    """Validate the boundary envelope contract that carries one terminal export body."""

    if not isinstance(envelope, RuntimeProtocolEnvelope):
        raise TypeError(
            "Heartbeat terminal protocol contract requires domain ProtocolEnvelope."
        )
    _require_non_empty_text(
        envelope.request_id,
        field_name="envelope.request_id",
    )
    if envelope.protocol_version != HEARTBEAT_TERMINAL_PROTOCOL_VERSION:
        raise ValueError(
            "Heartbeat terminal protocol envelope protocol_version is incompatible with the "
            "current contract baseline."
        )
    if envelope.kind != HEARTBEAT_TERMINAL_PROTOCOL_KIND:
        raise ValueError(
            "Heartbeat terminal protocol envelope kind must remain stable for the current "
            "contract baseline."
        )
    if not isinstance(envelope.metadata, Mapping):
        raise TypeError("Heartbeat terminal protocol envelope.metadata must be a mapping.")
    for key, value in envelope.metadata.items():
        _require_non_empty_text(key, field_name="envelope.metadata key")
        if not isinstance(value, str):
            raise TypeError(
                "Heartbeat terminal protocol envelope.metadata values must be strings."
            )
    assert_heartbeat_terminal_export_body_contract(
        extract_heartbeat_terminal_export_body(envelope)
    )


def extract_heartbeat_terminal_export_body(
    envelope: RuntimeProtocolEnvelope,
) -> Mapping[str, object]:
    """Return the stable envelope body location for the heartbeat terminal export contract."""

    if not isinstance(envelope, RuntimeProtocolEnvelope):
        raise TypeError(
            "Heartbeat terminal export extraction requires domain ProtocolEnvelope."
        )
    return _require_mapping(
        getattr(envelope, HEARTBEAT_TERMINAL_ENVELOPE_BODY_ATTRIBUTE, None),
        field_name=f"envelope.{HEARTBEAT_TERMINAL_ENVELOPE_BODY_ATTRIBUTE}",
    )


def _require_fields(
    mapping: Mapping[str, object],
    required_fields: Sequence[str],
    *,
    field_name: str,
) -> None:
    missing_fields = tuple(field for field in required_fields if field not in mapping)
    if missing_fields:
        raise ValueError(
            f"Heartbeat terminal export {field_name} is missing required fields: "
            + ", ".join(missing_fields)
        )


def _require_mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"Heartbeat terminal export {field_name} must be a mapping.")
    return value


def _require_sequence(value: object, *, field_name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"Heartbeat terminal export {field_name} must be a sequence.")
    return value


def _require_text_sequence(value: object, *, field_name: str) -> list[str]:
    return [
        _require_non_empty_text(item, field_name=f"{field_name}[]")
        for item in _require_sequence(value, field_name=field_name)
    ]


def _require_sequence_of_mappings(
    value: object,
    *,
    field_name: str,
) -> list[Mapping[str, object]]:
    return [
        _require_mapping(item, field_name=f"{field_name}[]")
        for item in _require_sequence(value, field_name=field_name)
    ]


def _require_non_empty_text(value: object, *, field_name: str) -> str:
    normalized_value = str(value).strip()
    if not normalized_value:
        raise ValueError(f"Heartbeat terminal export {field_name} must be non-empty text.")
    return normalized_value


def _require_optional_text(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_non_empty_text(value, field_name=field_name)


def _require_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"Heartbeat terminal export {field_name} must be an integer.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"Heartbeat terminal export {field_name} must be an integer."
        ) from exc


def _require_optional_int(value: object, *, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, field_name=field_name)


def _require_positive_int(value: object, *, field_name: str) -> int:
    normalized_value = _require_int(value, field_name=field_name)
    if normalized_value <= 0:
        raise ValueError(
            f"Heartbeat terminal export {field_name} must be a positive integer."
        )
    return normalized_value


def _require_bool(value: object, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"Heartbeat terminal export {field_name} must be a boolean.")
    return value


def _serialized_section_line_count(
    sections: Sequence[Mapping[str, object]],
    kind: str,
) -> int:
    for section in sections:
        if section.get("kind") == kind:
            return len(_require_text_sequence(section.get("lines", ()), field_name=f"{kind}.lines"))
    return 0
