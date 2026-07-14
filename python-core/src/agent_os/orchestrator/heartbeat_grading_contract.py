from __future__ import annotations

from collections.abc import Mapping, Sequence

CANONICAL_HEARTBEAT_SEVERITIES: tuple[str, ...] = (
    "minor",
    "moderate",
    "major",
    "critical",
)

LEGACY_TO_CANONICAL_HEARTBEAT_SEVERITY = {
    "blocker": "critical",
    "critical": "critical",
    "high": "major",
    "major": "major",
    "medium": "moderate",
    "moderate": "moderate",
    "low": "minor",
    "info": "minor",
    "minor": "minor",
}

_SEVERITY_ORDER = {
    severity: index for index, severity in enumerate(CANONICAL_HEARTBEAT_SEVERITIES, start=1)
}


def canonicalize_heartbeat_severity(value: object) -> str | None:
    """Normalize one severity label into the canonical heartbeat vocabulary."""

    if value is None:
        return None
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    canonical = LEGACY_TO_CANONICAL_HEARTBEAT_SEVERITY.get(normalized, normalized)
    if canonical not in CANONICAL_HEARTBEAT_SEVERITIES:
        raise ValueError(
            "Heartbeat severity must use the canonical vocabulary "
            f"{CANONICAL_HEARTBEAT_SEVERITIES} or a supported legacy alias."
        )
    return canonical


def heartbeat_severity_sort_key(severity: str | None) -> tuple[int, str]:
    canonical = canonicalize_heartbeat_severity(severity)
    if canonical is None:
        return (0, "")
    return (_SEVERITY_ORDER[canonical], canonical)


def normalize_heartbeat_blocker(value: object) -> bool | None:
    """Normalize one optional blocker flag into the canonical boolean form."""

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "blocker", "blocking"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    raise TypeError("Heartbeat judgment blocker must be a boolean when provided.")


def canonicalize_heartbeat_severity_histogram(
    histogram: Mapping[str, object] | None,
) -> dict[str, int]:
    """Normalize summary histograms so only canonical severity keys are exposed."""

    normalized_histogram: dict[str, int] = {}
    if histogram is None:
        return normalized_histogram
    for severity, count in histogram.items():
        canonical_severity = canonicalize_heartbeat_severity(severity)
        if canonical_severity is None:
            continue
        normalized_count = int(count)
        if normalized_count < 0:
            raise ValueError("Heartbeat severity histogram counts must be non-negative.")
        normalized_histogram[canonical_severity] = (
            normalized_histogram.get(canonical_severity, 0) + normalized_count
        )
    return dict(
        sorted(
            normalized_histogram.items(),
            key=lambda item: heartbeat_severity_sort_key(item[0]),
            reverse=True,
        )
    )


def canonicalize_heartbeat_blocker_roles(value: Sequence[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(sorted({str(role).strip() for role in value if str(role).strip()}))


def canonicalize_heartbeat_blocker_count(value: object) -> int:
    normalized = int(value or 0)
    if normalized < 0:
        raise ValueError("Heartbeat blocker_count must be non-negative.")
    return normalized


def validate_heartbeat_judgment_grading(
    *,
    decision: object,
    deficiency_category: object,
    severity: object,
    blocker: object,
) -> tuple[str | None, bool | None]:
    """Validate approve/reject grading combinations and return canonical values."""

    decision_label = _normalize_enum_like(decision)
    category_label = _normalize_enum_like(deficiency_category)
    canonical_severity = canonicalize_heartbeat_severity(severity)
    canonical_blocker = normalize_heartbeat_blocker(blocker)

    if decision_label == "approve":
        if category_label not in {"", "sufficient"}:
            raise ValueError("Approve judgments must use the sufficient deficiency category.")
        if canonical_blocker:
            raise ValueError("Approve judgments must not be blocker=true.")
    elif decision_label == "reject":
        if category_label == "sufficient":
            raise ValueError("Reject judgments must not use the sufficient deficiency category.")
        if canonical_blocker:
            if category_label in {"", "other"}:
                raise ValueError(
                    "Blocker reject judgments require an explicit non-ambiguous deficiency category."
                )
            if canonical_severity is None:
                raise ValueError("Blocker reject judgments must declare a severity.")

    return canonical_severity, canonical_blocker


def normalize_enum_like(value: object) -> str:
    return _normalize_enum_like(value)


def _normalize_enum_like(value: object) -> str:
    if value is None:
        return ""
    raw = getattr(value, "value", value)
    return str(raw).strip().lower()
