from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path

HEARTBEAT_TERMINAL_SHARED_MANIFEST_PATH = (
    Path(__file__).resolve().parents[4]
    / "contracts"
    / "heartbeat-terminal-export.manifest.json"
)


def _manifest_mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Heartbeat terminal shared manifest {field_name} must be a mapping.")
    return value


def _manifest_text(value: object, *, field_name: str) -> str:
    normalized_value = str(value).strip()
    if not normalized_value:
        raise ValueError(
            f"Heartbeat terminal shared manifest {field_name} must be non-empty text."
        )
    return normalized_value


def _manifest_text_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(
            f"Heartbeat terminal shared manifest {field_name} must be a text sequence."
        )
    normalized_values = tuple(
        _manifest_text(item, field_name=f"{field_name}[]") for item in value
    )
    if not normalized_values:
        raise ValueError(
            f"Heartbeat terminal shared manifest {field_name} must not be empty."
        )
    return normalized_values


def _manifest_bool(value: object, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(
            f"Heartbeat terminal shared manifest {field_name} must be a boolean."
        )
    return value


@lru_cache(maxsize=1)
def load_heartbeat_terminal_shared_manifest() -> Mapping[str, object]:
    """Load the shared machine-readable heartbeat terminal export contract manifest."""

    raw_manifest = json.loads(
        HEARTBEAT_TERMINAL_SHARED_MANIFEST_PATH.read_text(encoding="utf-8")
    )
    manifest = _manifest_mapping(raw_manifest, field_name="manifest")
    _manifest_text(manifest.get("contract_name"), field_name="manifest.contract_name")
    _manifest_text(manifest.get("schema_id"), field_name="manifest.schema_id")
    envelope = _manifest_mapping(manifest.get("envelope"), field_name="manifest.envelope")
    _manifest_text(envelope.get("kind"), field_name="manifest.envelope.kind")
    _manifest_text(
        envelope.get("protocol_version"),
        field_name="manifest.envelope.protocol_version",
    )
    _manifest_text(
        envelope.get("body_location"),
        field_name="manifest.envelope.body_location",
    )
    payload = _manifest_mapping(manifest.get("payload"), field_name="manifest.payload")
    _manifest_text_tuple(
        payload.get("required_fields"),
        field_name="manifest.payload.required_fields",
    )
    candidate = _manifest_mapping(
        payload.get("candidate"),
        field_name="manifest.payload.candidate",
    )
    _manifest_text_tuple(
        candidate.get("required_fields"),
        field_name="manifest.payload.candidate.required_fields",
    )
    _manifest_text_tuple(
        payload.get("section_vocabulary"),
        field_name="manifest.payload.section_vocabulary",
    )
    display_metadata = _manifest_mapping(
        payload.get("display_metadata"),
        field_name="manifest.payload.display_metadata",
    )
    _manifest_text_tuple(
        display_metadata.get("required_keys"),
        field_name="manifest.payload.display_metadata.required_keys",
    )
    _manifest_text(
        display_metadata.get("display_policy_version_key"),
        field_name="manifest.payload.display_metadata.display_policy_version_key",
    )
    _manifest_text(
        display_metadata.get("display_section_order_key"),
        field_name="manifest.payload.display_metadata.display_section_order_key",
    )
    _manifest_text(
        display_metadata.get("display_omit_empty_sections_key"),
        field_name="manifest.payload.display_metadata.display_omit_empty_sections_key",
    )
    _manifest_bool(
        display_metadata.get("display_omit_empty_sections_value"),
        field_name="manifest.payload.display_metadata.display_omit_empty_sections_value",
    )
    _manifest_text(
        display_metadata.get("display_section_count_key"),
        field_name="manifest.payload.display_metadata.display_section_count_key",
    )
    _manifest_text(
        display_metadata.get("retained_item_count_key"),
        field_name="manifest.payload.display_metadata.retained_item_count_key",
    )
    omission_rules = _manifest_mapping(
        display_metadata.get("omission_rules"),
        field_name="manifest.payload.display_metadata.omission_rules",
    )
    _manifest_text(
        omission_rules.get("metadata_key"),
        field_name="manifest.payload.display_metadata.omission_rules.metadata_key",
    )
    _manifest_text_tuple(
        omission_rules.get("non_omittable_sections"),
        field_name=(
            "manifest.payload.display_metadata.omission_rules.non_omittable_sections"
        ),
    )
    truncation_rules = _manifest_mapping(
        display_metadata.get("truncation_rules"),
        field_name="manifest.payload.display_metadata.truncation_rules",
    )
    for rule_name, rule_value in truncation_rules.items():
        rule_mapping = _manifest_mapping(
            rule_value,
            field_name=(
                "manifest.payload.display_metadata.truncation_rules."
                f"{str(rule_name).strip()}"
            ),
        )
        _manifest_text(
            rule_mapping.get("count_key"),
            field_name=f"manifest.truncation_rules.{rule_name}.count_key",
        )
        _manifest_text(
            rule_mapping.get("collection_field"),
            field_name=f"manifest.truncation_rules.{rule_name}.collection_field",
        )
        _manifest_text(
            rule_mapping.get("limit_key"),
            field_name=f"manifest.truncation_rules.{rule_name}.limit_key",
        )
        _manifest_text(
            rule_mapping.get("section_kind"),
            field_name=f"manifest.truncation_rules.{rule_name}.section_kind",
        )
    compatibility = _manifest_mapping(
        manifest.get("compatibility"),
        field_name="manifest.compatibility",
    )
    _manifest_text_tuple(
        compatibility.get("compatible_additions"),
        field_name="manifest.compatibility.compatible_additions",
    )
    _manifest_text_tuple(
        compatibility.get("breaking_changes"),
        field_name="manifest.compatibility.breaking_changes",
    )
    return manifest


HEARTBEAT_TERMINAL_SHARED_MANIFEST = load_heartbeat_terminal_shared_manifest()
_ENVELOPE_MANIFEST = _manifest_mapping(
    HEARTBEAT_TERMINAL_SHARED_MANIFEST.get("envelope"),
    field_name="manifest.envelope",
)
_PAYLOAD_MANIFEST = _manifest_mapping(
    HEARTBEAT_TERMINAL_SHARED_MANIFEST.get("payload"),
    field_name="manifest.payload",
)
_PAYLOAD_CANDIDATE_MANIFEST = _manifest_mapping(
    _PAYLOAD_MANIFEST.get("candidate"),
    field_name="manifest.payload.candidate",
)
_DISPLAY_METADATA_MANIFEST = _manifest_mapping(
    _PAYLOAD_MANIFEST.get("display_metadata"),
    field_name="manifest.payload.display_metadata",
)
_DISPLAY_METADATA_OMISSION_RULES = _manifest_mapping(
    _DISPLAY_METADATA_MANIFEST.get("omission_rules"),
    field_name="manifest.payload.display_metadata.omission_rules",
)
_DISPLAY_METADATA_TRUNCATION_RULES = _manifest_mapping(
    _DISPLAY_METADATA_MANIFEST.get("truncation_rules"),
    field_name="manifest.payload.display_metadata.truncation_rules",
)
_COMPATIBILITY_MANIFEST = _manifest_mapping(
    HEARTBEAT_TERMINAL_SHARED_MANIFEST.get("compatibility"),
    field_name="manifest.compatibility",
)

HEARTBEAT_TERMINAL_EXPORT_SCHEMA_ID = _manifest_text(
    HEARTBEAT_TERMINAL_SHARED_MANIFEST.get("schema_id"),
    field_name="manifest.schema_id",
)
HEARTBEAT_TERMINAL_PROTOCOL_KIND = _manifest_text(
    _ENVELOPE_MANIFEST.get("kind"),
    field_name="manifest.envelope.kind",
)
HEARTBEAT_TERMINAL_PROTOCOL_VERSION = _manifest_text(
    _ENVELOPE_MANIFEST.get("protocol_version"),
    field_name="manifest.envelope.protocol_version",
)
HEARTBEAT_TERMINAL_ENVELOPE_BODY_ATTRIBUTE = _manifest_text(
    _ENVELOPE_MANIFEST.get("body_location"),
    field_name="manifest.envelope.body_location",
)
HEARTBEAT_TERMINAL_EXPORT_REQUIRED_FIELDS = _manifest_text_tuple(
    _PAYLOAD_MANIFEST.get("required_fields"),
    field_name="manifest.payload.required_fields",
)
HEARTBEAT_TERMINAL_EXPORT_CANDIDATE_REQUIRED_FIELDS = _manifest_text_tuple(
    _PAYLOAD_CANDIDATE_MANIFEST.get("required_fields"),
    field_name="manifest.payload.candidate.required_fields",
)
HEARTBEAT_TERMINAL_EXPORT_SECTION_KIND_VOCABULARY = _manifest_text_tuple(
    _PAYLOAD_MANIFEST.get("section_vocabulary"),
    field_name="manifest.payload.section_vocabulary",
)
HEARTBEAT_TERMINAL_EXPORT_DISPLAY_METADATA_REQUIRED_FIELDS = _manifest_text_tuple(
    _DISPLAY_METADATA_MANIFEST.get("required_keys"),
    field_name="manifest.payload.display_metadata.required_keys",
)
HEARTBEAT_TERMINAL_DISPLAY_METADATA_POLICY_VERSION_KEY = _manifest_text(
    _DISPLAY_METADATA_MANIFEST.get("display_policy_version_key"),
    field_name="manifest.payload.display_metadata.display_policy_version_key",
)
HEARTBEAT_TERMINAL_DISPLAY_METADATA_SECTION_ORDER_KEY = _manifest_text(
    _DISPLAY_METADATA_MANIFEST.get("display_section_order_key"),
    field_name="manifest.payload.display_metadata.display_section_order_key",
)
HEARTBEAT_TERMINAL_DISPLAY_METADATA_OMIT_EMPTY_SECTIONS_KEY = _manifest_text(
    _DISPLAY_METADATA_MANIFEST.get("display_omit_empty_sections_key"),
    field_name="manifest.payload.display_metadata.display_omit_empty_sections_key",
)
HEARTBEAT_TERMINAL_DISPLAY_METADATA_OMIT_EMPTY_SECTIONS_VALUE = _manifest_bool(
    _DISPLAY_METADATA_MANIFEST.get("display_omit_empty_sections_value"),
    field_name="manifest.payload.display_metadata.display_omit_empty_sections_value",
)
HEARTBEAT_TERMINAL_DISPLAY_METADATA_SECTION_COUNT_KEY = _manifest_text(
    _DISPLAY_METADATA_MANIFEST.get("display_section_count_key"),
    field_name="manifest.payload.display_metadata.display_section_count_key",
)
HEARTBEAT_TERMINAL_DISPLAY_METADATA_RETAINED_ITEM_COUNT_KEY = _manifest_text(
    _DISPLAY_METADATA_MANIFEST.get("retained_item_count_key"),
    field_name="manifest.payload.display_metadata.retained_item_count_key",
)
HEARTBEAT_TERMINAL_DISPLAY_METADATA_OMISSION_METADATA_KEY = _manifest_text(
    _DISPLAY_METADATA_OMISSION_RULES.get("metadata_key"),
    field_name="manifest.payload.display_metadata.omission_rules.metadata_key",
)
HEARTBEAT_TERMINAL_DISPLAY_METADATA_NON_OMITTABLE_SECTIONS = _manifest_text_tuple(
    _DISPLAY_METADATA_OMISSION_RULES.get("non_omittable_sections"),
    field_name="manifest.payload.display_metadata.omission_rules.non_omittable_sections",
)
HEARTBEAT_TERMINAL_DISPLAY_METADATA_TRUNCATION_RULES = {
    rule_name: {
        "count_key": _manifest_text(
            rule_value.get("count_key"),
            field_name=f"manifest.truncation_rules.{rule_name}.count_key",
        ),
        "collection_field": _manifest_text(
            rule_value.get("collection_field"),
            field_name=f"manifest.truncation_rules.{rule_name}.collection_field",
        ),
        "limit_key": _manifest_text(
            rule_value.get("limit_key"),
            field_name=f"manifest.truncation_rules.{rule_name}.limit_key",
        ),
        "section_kind": _manifest_text(
            rule_value.get("section_kind"),
            field_name=f"manifest.truncation_rules.{rule_name}.section_kind",
        ),
    }
    for rule_name, rule_value in _DISPLAY_METADATA_TRUNCATION_RULES.items()
}
HEARTBEAT_TERMINAL_EXPORT_COMPATIBLE_ADDITIONS = _manifest_text_tuple(
    _COMPATIBILITY_MANIFEST.get("compatible_additions"),
    field_name="manifest.compatibility.compatible_additions",
)
HEARTBEAT_TERMINAL_EXPORT_BREAKING_CHANGES = _manifest_text_tuple(
    _COMPATIBILITY_MANIFEST.get("breaking_changes"),
    field_name="manifest.compatibility.breaking_changes",
)
