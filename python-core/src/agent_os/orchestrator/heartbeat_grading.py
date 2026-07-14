from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import re

from agent_os.orchestrator.convergence import (
    HeartbeatAgentJudgment,
    HeartbeatCheckpointInput,
    HeartbeatEvidenceBundle,
    HeartbeatSourceAnchor,
    HeartbeatVoteChoice,
    RejectionDeficiencyCategory,
)
from agent_os.orchestrator.heartbeat_grading_contract import (
    canonicalize_heartbeat_severity,
    heartbeat_severity_sort_key,
)
from agent_os.orchestrator.source_anchor_utils import normalize_source_anchors

_HARD_REQUIREMENT_TERMS = (
    "must",
    "required",
    "requirement",
    "mandatory",
    "hard constraint",
    "constraints",
    "constraint",
    "cannot",
    "can't",
    "forbid",
    "forbidden",
    "non-negotiable",
)
_PLAN_TERMS = (
    "plan",
    "steps",
    "step",
    "workflow",
    "phase",
    "phases",
    "task",
    "tasks",
)
_IMPLEMENTATION_TERMS = (
    "implement",
    "implementation",
    "execute",
    "execution",
    "apply",
    "patch",
    "code",
    "workspace",
    "file",
    "files",
    "interface",
    "interfaces",
    "dependency",
    "dependencies",
    "api",
    "endpoint",
)
_VALIDATION_TERMS = (
    "validate",
    "validation",
    "verify",
    "verification",
    "tests",
    "evidence",
    "proof",
    "correctness",
    "correct",
)
_DELIVERABLE_TERMS = (
    "deliver",
    "deliverable",
    "output",
    "report",
    "summary",
    "artifact",
    "file",
    "files",
    "plan",
    "tests",
)
_HIGH_IMPACT_RISK_TERMS = (
    "risk",
    "bug",
    "incorrect",
    "failure",
    "conflict",
    "unsafe",
)


@dataclass(frozen=True, slots=True)
class HeartbeatGradingResult:
    """Canonical severity/blocker decision derived from explicit heartbeat inputs."""

    severity: str | None = None
    blocker: bool = False
    policy_basis: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HeartbeatGradingSummary:
    """Lightweight grading summary retained for aggregate and report passthrough."""

    highest_rejection_severity: str | None = None
    blocker_count: int = 0
    blocker_roles: tuple[str, ...] = ()
    severity_histogram: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _GradingContext:
    decision: HeartbeatVoteChoice
    category: RejectionDeficiencyCategory | None
    agent_role: str
    used_signal_keys: tuple[str, ...]
    source_anchors: tuple[HeartbeatSourceAnchor, ...]
    goal_text: str
    candidate_text: str
    hard_requirement_requested: bool
    required_deliverable_requested: bool
    goal_requires_plan: bool
    goal_requires_implementation: bool
    goal_requires_validation: bool
    goal_mentions_interface: bool
    high_impact_risk_language: bool
    has_grounded_anchor: bool
    has_supporting_material: bool
    has_validation_signal: bool
    has_evidence_gap: bool
    context_ref_count: int


def canonicalize_severity_label(value: object) -> str | None:
    """Normalize legacy and new severity labels into the canonical four-level scale."""

    return canonicalize_heartbeat_severity(value)


def severity_sort_key(severity: str | None) -> tuple[int, str]:
    return heartbeat_severity_sort_key(severity)


def extract_judgment_severity(judgment: HeartbeatAgentJudgment) -> str | None:
    """Return the canonical severity stored on a judgment or in compatibility metadata."""

    if judgment.severity is not None:
        return canonicalize_severity_label(judgment.severity)
    metadata = judgment.metadata if isinstance(judgment.metadata, Mapping) else {}
    for key in ("severity", "deficiency_severity"):
        value = metadata.get(key)
        normalized = canonicalize_severity_label(value)
        if normalized is not None:
            return normalized
    return None


def extract_judgment_blocker(judgment: HeartbeatAgentJudgment) -> bool:
    """Return the explicit blocker bit from a judgment or compatibility metadata."""

    if judgment.decision != HeartbeatVoteChoice.REJECT:
        return False
    if judgment.blocker is not None:
        return judgment.blocker
    metadata = judgment.metadata if isinstance(judgment.metadata, Mapping) else {}
    for key in ("blocker", "is_blocker", "blocking", "is_blocking"):
        value = metadata.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y", "blocker", "blocking"}:
                return True
            if normalized in {"false", "0", "no", "n"}:
                return False
    return False


def summarize_heartbeat_grading(
    judgments: Sequence[HeartbeatAgentJudgment],
) -> HeartbeatGradingSummary:
    """Summarize rejection grading for lightweight aggregate/report passthrough."""

    histogram_counter: Counter[str] = Counter()
    blocker_roles: set[str] = set()
    blocker_count = 0
    highest_severity: str | None = None
    for judgment in judgments:
        if judgment.decision != HeartbeatVoteChoice.REJECT:
            continue
        severity = extract_judgment_severity(judgment)
        if severity is not None:
            histogram_counter[severity] += 1
            if highest_severity is None or severity_sort_key(severity) > severity_sort_key(
                highest_severity
            ):
                highest_severity = severity
        if extract_judgment_blocker(judgment):
            blocker_count += 1
            blocker_roles.add(_judgment_role(judgment))

    histogram = dict(
        sorted(
            histogram_counter.items(),
            key=lambda item: (severity_sort_key(item[0])[0], item[0]),
            reverse=True,
        )
    )
    return HeartbeatGradingSummary(
        highest_rejection_severity=highest_severity,
        blocker_count=blocker_count,
        blocker_roles=tuple(sorted(blocker_roles)),
        severity_histogram=histogram,
    )


def derive_heartbeat_grading(
    *,
    decision: HeartbeatVoteChoice,
    deficiency_category: RejectionDeficiencyCategory | None,
    used_signal_keys: Sequence[str] = (),
    source_anchors: object = (),
    checkpoint_input: HeartbeatCheckpointInput,
    evidence_bundle: HeartbeatEvidenceBundle | None,
    agent_role: str | None = None,
) -> HeartbeatGradingResult:
    """Derive canonical severity and blocker from explicit heartbeat evidence inputs."""

    context = _build_context(
        decision=decision,
        deficiency_category=deficiency_category,
        used_signal_keys=used_signal_keys,
        source_anchors=source_anchors,
        checkpoint_input=checkpoint_input,
        evidence_bundle=evidence_bundle,
        agent_role=agent_role,
    )
    if (
        context.decision != HeartbeatVoteChoice.REJECT
        or context.category is None
        or context.category == RejectionDeficiencyCategory.SUFFICIENT
    ):
        return HeartbeatGradingResult(severity=None, blocker=False, policy_basis=("approve",))

    if context.category == RejectionDeficiencyCategory.CONSTRAINT_VIOLATION:
        if context.hard_requirement_requested or context.required_deliverable_requested:
            return _result("critical", True, "constraint.hard_requirement")
        return _result("major", False, "constraint.default_major")

    if context.category == RejectionDeficiencyCategory.GOAL_MISALIGNMENT:
        if _touches_core_goal(context):
            return _result("major", True, "coverage.core_goal_blocker")
        return _result("major", False, "coverage.default_major")

    if context.category == RejectionDeficiencyCategory.INCOMPLETENESS:
        if _is_implementation_break(context):
            if _candidate_is_not_executable(context):
                return _result("critical", True, "implementation.not_executable")
            return _result("major", True, "implementation.blocking_gap")
        if _is_plan_or_coverage_gap(context):
            if _touches_core_goal(context):
                return _result("major", True, "coverage.core_deliverable_gap")
            return _result("moderate", False, "coverage.default_gap")
        if context.required_deliverable_requested:
            return _result("major", True, "deliverable.required_gap")
        return _result("moderate", False, "incompleteness.default")

    if context.category == RejectionDeficiencyCategory.EVIDENCE_GAP:
        if _is_core_evidence_gap(context):
            return _result("major", False, "evidence.core_gap")
        return _result("moderate", False, "evidence.default_gap")

    if context.category == RejectionDeficiencyCategory.CORRECTNESS_RISK:
        if _has_high_impact_acceptability_risk(context):
            return _result("major", True, "risk.acceptability_blocker")
        return _result("moderate", False, "risk.default_moderate")

    if context.category == RejectionDeficiencyCategory.CLARITY_GAP:
        if "risk.has_gap_marker" in context.used_signal_keys:
            return _result("moderate", False, "clarity.implementation_gap_marker")
        if "risk.has_clarity_marker" in context.used_signal_keys and _has_high_impact_acceptability_risk(
            context
        ):
            return _result("major", True, "clarity.high_impact_blocker")
        if _touches_core_goal(context) and _is_implementation_break(context):
            return _result("major", False, "clarity.core_implementation_gap")
        if context.used_signal_keys:
            return _result("moderate", False, "clarity.default_moderate")
        return _result("minor", False, "clarity.default_minor")

    return _result("moderate", False, "fallback.default")


def _build_context(
    *,
    decision: HeartbeatVoteChoice,
    deficiency_category: RejectionDeficiencyCategory | None,
    used_signal_keys: Sequence[str],
    source_anchors: object,
    checkpoint_input: HeartbeatCheckpointInput,
    evidence_bundle: HeartbeatEvidenceBundle | None,
    agent_role: str | None,
) -> _GradingContext:
    normalized_signal_keys = tuple(
        dict.fromkeys(str(key).strip() for key in used_signal_keys if str(key).strip())
    )
    normalized_source_anchors = normalize_source_anchors(source_anchors)
    goal_text = _flatten_text(
        (
            checkpoint_input.original_goal,
            checkpoint_input.metadata,
        )
    )
    candidate_text = _flatten_text(
        (
            checkpoint_input.frozen_candidate_summary,
            checkpoint_input.frozen_candidate_structured_content,
            checkpoint_input.frozen_candidate_payload,
            evidence_bundle.structured_content_summary if evidence_bundle is not None else None,
            evidence_bundle.payload_summary if evidence_bundle is not None else None,
        )
    )
    evidence_signals = evidence_bundle.evidence_signals if evidence_bundle is not None else {}
    has_supporting_material = bool(
        checkpoint_input.frozen_candidate_structured_content
        or checkpoint_input.frozen_candidate_payload
        or (evidence_bundle is not None and evidence_bundle.relevant_context_refs)
    )
    return _GradingContext(
        decision=decision,
        category=deficiency_category,
        agent_role=(agent_role or "").strip().lower(),
        used_signal_keys=normalized_signal_keys,
        source_anchors=normalized_source_anchors,
        goal_text=goal_text,
        candidate_text=candidate_text,
        hard_requirement_requested=_contains_any(goal_text, _HARD_REQUIREMENT_TERMS),
        required_deliverable_requested=_contains_any(goal_text, _DELIVERABLE_TERMS),
        goal_requires_plan=_contains_any(goal_text, _PLAN_TERMS),
        goal_requires_implementation=_contains_any(goal_text, _IMPLEMENTATION_TERMS),
        goal_requires_validation=_contains_any(goal_text, _VALIDATION_TERMS),
        goal_mentions_interface=_contains_any(
            goal_text,
            ("interface", "interfaces", "dependency", "dependencies", "api", "endpoint"),
        ),
        high_impact_risk_language=_contains_any(goal_text, _HIGH_IMPACT_RISK_TERMS),
        has_grounded_anchor=any(
            anchor.derived_from_summary
            or anchor.derived_from_structured_content
            or anchor.derived_from_payload
            or bool(anchor.matched_refs)
            for anchor in normalized_source_anchors
        ),
        has_supporting_material=has_supporting_material,
        has_validation_signal=bool(evidence_signals.get("has_validation_signal", False)),
        has_evidence_gap=bool(evidence_signals.get("has_evidence_gap", False)),
        context_ref_count=int(evidence_signals.get("context_ref_count", 0) or 0),
    )


def _result(severity: str, blocker: bool, *policy_basis: str) -> HeartbeatGradingResult:
    return HeartbeatGradingResult(
        severity=canonicalize_severity_label(severity),
        blocker=blocker,
        policy_basis=tuple(policy_basis),
    )


def _touches_core_goal(context: _GradingContext) -> bool:
    return (
        context.goal_requires_plan
        or context.goal_requires_implementation
        or context.goal_requires_validation
        or context.required_deliverable_requested
        or context.hard_requirement_requested
    )


def _is_plan_or_coverage_gap(context: _GradingContext) -> bool:
    return bool(
        context.category == RejectionDeficiencyCategory.GOAL_MISALIGNMENT
        or any(key.startswith("coverage.") for key in context.used_signal_keys)
        or context.agent_role == "planner"
    )


def _is_implementation_break(context: _GradingContext) -> bool:
    return bool(
        any(key.startswith("implementation.") for key in context.used_signal_keys)
        or (
            context.agent_role == "executor"
            and "risk.has_gap_marker" not in context.used_signal_keys
        )
    )


def _candidate_is_not_executable(context: _GradingContext) -> bool:
    if "implementation.has_execution_path" in context.used_signal_keys:
        return True
    if "implementation.has_interface_closure" in context.used_signal_keys and (
        context.goal_requires_implementation
        or context.goal_mentions_interface
        or context.has_grounded_anchor
    ):
        return True
    return False


def _is_core_evidence_gap(context: _GradingContext) -> bool:
    if "evidence.has_evidence_gap" in context.used_signal_keys or context.has_evidence_gap:
        return True
    if (
        "evidence.has_validation_signal" in context.used_signal_keys
        and context.goal_requires_validation
        and not context.has_validation_signal
        and not context.has_supporting_material
        and context.context_ref_count == 0
    ):
        return True
    return False


def _has_high_impact_acceptability_risk(context: _GradingContext) -> bool:
    return bool(
        context.goal_requires_validation
        or context.goal_requires_implementation
        or context.high_impact_risk_language
        or context.hard_requirement_requested
    ) and context.has_grounded_anchor


def _judgment_role(judgment: HeartbeatAgentJudgment) -> str:
    metadata = judgment.metadata if isinstance(judgment.metadata, Mapping) else {}
    role = metadata.get("agent_role")
    if isinstance(role, str):
        normalized = role.strip()
        if normalized:
            return normalized
    return judgment.agent_id


def _contains_any(text: str, terms: Sequence[str]) -> bool:
    normalized = text.strip().lower()
    if not normalized:
        return False
    return any(_contains_term(normalized, term) for term in terms)


def _contains_term(text: str, term: str) -> bool:
    normalized_term = term.strip().lower()
    if not normalized_term:
        return False
    pattern = r"(?<!\w)" + re.escape(normalized_term) + r"(?!\w)"
    return re.search(pattern, text) is not None


def _flatten_text(value: object) -> str:
    fragments = tuple(_iter_text_fragments(value))
    normalized = " ".join(fragment for fragment in fragments if fragment).strip().lower()
    return re.sub(r"\s+", " ", normalized)


def _iter_text_fragments(value: object) -> Sequence[str]:
    if value is None:
        return ()
    if isinstance(value, str):
        normalized = value.strip()
        return (normalized,) if normalized else ()
    if isinstance(value, Mapping):
        fragments: list[str] = []
        for key, item in value.items():
            fragments.extend(_iter_text_fragments(key))
            fragments.extend(_iter_text_fragments(item))
        return tuple(fragments)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        fragments = []
        for item in value:
            fragments.extend(_iter_text_fragments(item))
        return tuple(fragments)
    return (str(value).strip(),) if str(value).strip() else ()
