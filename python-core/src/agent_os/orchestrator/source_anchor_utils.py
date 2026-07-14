from __future__ import annotations

from collections.abc import Mapping, Sequence

from agent_os.orchestrator.convergence import HeartbeatEvidenceBundle, HeartbeatSourceAnchor

_SIGNAL_FAMILY_TO_ATTRIBUTE = {
    "constraint": "constraint_signals",
    "coverage": "coverage_signals",
    "implementation": "implementation_signals",
    "risk": "risk_signals",
    "evidence": "evidence_signals",
}


def resolve_source_anchors(
    *,
    formal_source_anchors: object = (),
    legacy_source_anchors: object = None,
    sort_result: bool = False,
) -> tuple[HeartbeatSourceAnchor, ...]:
    """Prefer formal source anchors and fall back to legacy raw anchor payloads."""

    anchors = normalize_source_anchors(formal_source_anchors)
    if not anchors:
        anchors = normalize_source_anchors(legacy_source_anchors)
    if sort_result:
        return sort_dedup_source_anchors(anchors)
    return anchors


def source_anchor_candidates_from_signal_keys(
    used_signal_keys: Sequence[str],
    evidence_bundle: HeartbeatEvidenceBundle | None,
) -> tuple[HeartbeatSourceAnchor, ...]:
    """Build source anchors from one signal-key sequence and evidence bundle."""

    anchors = []
    for signal_key in dict.fromkeys(
        str(key).strip() for key in used_signal_keys if str(key).strip()
    ):
        anchor = source_anchor_from_signal_key(signal_key, evidence_bundle)
        if anchor is not None:
            anchors.append(anchor)
    return dedup_source_anchors(anchors)


def source_anchor_from_signal_key(
    signal_key: str,
    evidence_bundle: HeartbeatEvidenceBundle | None,
) -> HeartbeatSourceAnchor | None:
    """Build one source anchor from one used signal key."""

    normalized_signal_key = str(signal_key).strip()
    if not normalized_signal_key:
        return None

    signal_family = normalized_signal_key.split(".", maxsplit=1)[0].strip().lower()
    signal_mapping = _signal_mapping(signal_family, evidence_bundle)
    return HeartbeatSourceAnchor(
        signal_key=normalized_signal_key,
        signal_family=signal_family,
        source_fields=_normalize_string_tuple(signal_mapping.get("source_fields")),
        matched_refs=_normalize_string_tuple(signal_mapping.get("matched_refs")),
        derived_from_summary=bool(signal_mapping.get("derived_from_summary", False)),
        derived_from_structured_content=bool(
            signal_mapping.get("derived_from_structured_content", False)
        ),
        derived_from_payload=bool(signal_mapping.get("derived_from_payload", False)),
    )


def normalize_source_anchors(value: object) -> tuple[HeartbeatSourceAnchor, ...]:
    """Normalize one or many source-anchor payloads while preserving first-seen order."""

    normalized: list[HeartbeatSourceAnchor] = []
    for item in _iter_source_anchor_values(value):
        anchor = normalize_source_anchor(item)
        if anchor is not None:
            normalized.append(anchor)
    return dedup_source_anchors(normalized)


def normalize_source_anchor(value: object) -> HeartbeatSourceAnchor | None:
    """Normalize one source-anchor payload into the canonical schema."""

    if isinstance(value, HeartbeatSourceAnchor):
        return value
    if not isinstance(value, Mapping):
        return None

    signal_key = str(value.get("signal_key", "")).strip()
    if not signal_key:
        return None

    signal_family = str(value.get("signal_family", "")).strip().lower() or signal_key.split(
        ".",
        maxsplit=1,
    )[0].strip().lower()
    metadata = value.get("metadata")
    if metadata is not None and not isinstance(metadata, Mapping):
        return None

    return HeartbeatSourceAnchor(
        signal_key=signal_key,
        signal_family=signal_family,
        source_fields=_normalize_string_tuple(value.get("source_fields")),
        matched_refs=_normalize_string_tuple(value.get("matched_refs")),
        derived_from_summary=bool(value.get("derived_from_summary", False)),
        derived_from_structured_content=bool(value.get("derived_from_structured_content", False)),
        derived_from_payload=bool(value.get("derived_from_payload", False)),
        metadata=dict(metadata or {}),
    )


def dedup_source_anchors(
    anchors: Sequence[HeartbeatSourceAnchor | Mapping[str, object]],
) -> tuple[HeartbeatSourceAnchor, ...]:
    """Deduplicate normalized anchors while preserving first-seen order."""

    anchors_by_key: dict[
        tuple[str, str, tuple[str, ...], tuple[str, ...], bool, bool, bool],
        HeartbeatSourceAnchor,
    ] = {}
    for value in anchors:
        anchor = normalize_source_anchor(value)
        if anchor is None:
            continue
        key = source_anchor_identity(anchor)
        if key not in anchors_by_key:
            anchors_by_key[key] = anchor
    return tuple(anchors_by_key.values())


def sort_dedup_source_anchors(
    anchors: Sequence[HeartbeatSourceAnchor | Mapping[str, object]],
) -> tuple[HeartbeatSourceAnchor, ...]:
    """Deduplicate anchors and return them in deterministic key order."""

    anchors_by_key = {
        source_anchor_identity(anchor): anchor
        for anchor in dedup_source_anchors(anchors)
    }
    return tuple(anchor for _, anchor in sorted(anchors_by_key.items(), key=lambda item: item[0]))


def source_anchor_identity(
    anchor: HeartbeatSourceAnchor,
) -> tuple[str, str, tuple[str, ...], tuple[str, ...], bool, bool, bool]:
    """Return the deterministic identity key used for dedupe and sorting."""

    return (
        anchor.signal_key,
        anchor.signal_family,
        anchor.source_fields,
        anchor.matched_refs,
        anchor.derived_from_summary,
        anchor.derived_from_structured_content,
        anchor.derived_from_payload,
    )


def _iter_source_anchor_values(value: object) -> tuple[object, ...]:
    if value is None:
        return ()
    if isinstance(value, (HeartbeatSourceAnchor, Mapping)):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, str):
        return tuple(value)
    return ()


def _signal_mapping(
    signal_family: str,
    evidence_bundle: HeartbeatEvidenceBundle | None,
) -> Mapping[str, object]:
    if evidence_bundle is None:
        return {}
    attribute_name = _SIGNAL_FAMILY_TO_ATTRIBUTE.get(signal_family)
    if attribute_name is None:
        return {}
    raw_mapping = getattr(evidence_bundle, attribute_name, None)
    return raw_mapping if isinstance(raw_mapping, Mapping) else {}


def _normalize_string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        normalized = value.strip()
        return (normalized,) if normalized else ()
    if isinstance(value, Sequence):
        return tuple(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
    return ()
