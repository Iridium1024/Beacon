from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from agent_os.orchestrator.convergence import (
    ConvergenceStatus,
    HeartbeatAgentJudgment,
    HeartbeatAggregateArtifact,
    HeartbeatCheckpointInput,
    HeartbeatDissentItem,
    HeartbeatEvidenceBundle,
    HeartbeatSourceAnchor,
    HeartbeatVoteChoice,
    RejectionDeficiencyCategory,
)
from agent_os.orchestrator.heartbeat_grading import (
    extract_judgment_blocker,
    extract_judgment_severity,
    severity_sort_key,
    summarize_heartbeat_grading,
)
from agent_os.orchestrator.source_anchor_utils import (
    resolve_source_anchors,
    sort_dedup_source_anchors,
    source_anchor_candidates_from_signal_keys,
)


def build_heartbeat_aggregate_artifact(
    *,
    aggregate_result_id: str,
    checkpoint_input: HeartbeatCheckpointInput,
    evidence_bundle: HeartbeatEvidenceBundle | None,
    judgments: Sequence[HeartbeatAgentJudgment],
    final_decision: ConvergenceStatus,
) -> HeartbeatAggregateArtifact:
    """Build a deterministic, report-ready heartbeat aggregate artifact."""

    grouped_judgments = _group_judgments_by_category(judgments)
    all_roles = tuple(sorted({_judgment_role(judgment) for judgment in judgments}))
    items = _prioritize_items(
        _build_dissent_item(
            category=category,
            judgments=category_judgments,
            all_roles=all_roles,
            evidence_bundle=evidence_bundle,
            final_decision=final_decision,
        )
        for category, category_judgments in grouped_judgments
    )
    consensus_items, minority_items = _classify_items(items, final_decision)
    unresolved_items = tuple(
        item
        for item in items
        if item.category != RejectionDeficiencyCategory.SUFFICIENT
        and (item.blocker or final_decision == ConvergenceStatus.CONTINUE)
    )
    approval_count = sum(
        1 for judgment in judgments if judgment.decision == HeartbeatVoteChoice.APPROVE
    )
    evidence_bundle_id = _resolve_evidence_bundle_id(evidence_bundle, judgments)
    grading_summary = summarize_heartbeat_grading(judgments)
    decision_rationale = _build_decision_rationale(
        judgments=judgments,
        approval_count=approval_count,
        final_decision=final_decision,
        grading_summary=grading_summary,
        minority_items=minority_items,
        unresolved_items=unresolved_items,
    )
    recommended_next_actions = _build_recommended_next_actions(
        judgments=judgments,
        final_decision=final_decision,
        grading_summary=grading_summary,
        minority_items=minority_items,
        unresolved_items=unresolved_items,
    )
    return HeartbeatAggregateArtifact(
        aggregate_result_id=aggregate_result_id,
        checkpoint_id=checkpoint_input.checkpoint_id,
        candidate_id=checkpoint_input.frozen_candidate_id,
        evidence_bundle_id=evidence_bundle_id,
        final_decision=final_decision,
        highest_rejection_severity=grading_summary.highest_rejection_severity,
        blocker_count=grading_summary.blocker_count,
        blocker_roles=grading_summary.blocker_roles,
        severity_histogram=grading_summary.severity_histogram,
        consensus_items=consensus_items,
        minority_items=minority_items,
        unresolved_items=unresolved_items,
        decision_rationale=decision_rationale,
        recommended_next_actions=recommended_next_actions,
        metadata={
            "judgment_count": len(judgments),
            "category_count": len(items),
            "final_decision": final_decision.value,
        },
    )


def build_heartbeat_dissent_summary(artifact: HeartbeatAggregateArtifact) -> str | None:
    """Build a concise legacy dissent summary from the aggregate artifact."""

    prioritized_items = _merge_unique_items(artifact.unresolved_items, artifact.minority_items)
    if not prioritized_items:
        return None

    summary_parts = []
    for item in prioritized_items[:3]:
        roles = ", ".join(item.supporting_roles) if item.supporting_roles else "unknown"
        summary_text = item.summary or "No explicit rationale recorded."
        summary_parts.append(f"{item.category.value} [{roles}]: {summary_text}")
    return " | ".join(summary_parts)


def _group_judgments_by_category(
    judgments: Sequence[HeartbeatAgentJudgment],
) -> tuple[tuple[RejectionDeficiencyCategory, tuple[HeartbeatAgentJudgment, ...]], ...]:
    grouped: dict[RejectionDeficiencyCategory, list[HeartbeatAgentJudgment]] = {}
    for judgment in judgments:
        category = _judgment_category(judgment)
        grouped.setdefault(category, []).append(judgment)
    return tuple(
        (category, _sort_judgments_by_priority(category_judgments))
        for category, category_judgments in sorted(grouped.items(), key=lambda item: item[0].value)
    )


def _build_dissent_item(
    *,
    category: RejectionDeficiencyCategory,
    judgments: Sequence[HeartbeatAgentJudgment],
    all_roles: Sequence[str],
    evidence_bundle: HeartbeatEvidenceBundle | None,
    final_decision: ConvergenceStatus,
) -> HeartbeatDissentItem:
    ordered_judgments = _sort_judgments_by_priority(judgments)
    supporting_roles = tuple(sorted({_judgment_role(judgment) for judgment in ordered_judgments}))
    dissenting_roles = tuple(role for role in all_roles if role not in supporting_roles)
    used_signal_keys = _collect_used_signal_keys(ordered_judgments)
    source_anchors = _resolve_source_anchors(ordered_judgments, used_signal_keys, evidence_bundle)
    severity = _merge_severity(ordered_judgments)
    blocker = any(extract_judgment_blocker(judgment) for judgment in ordered_judgments)
    judgment_ids = tuple(
        judgment.judgment_id for judgment in ordered_judgments if judgment.judgment_id
    )
    return HeartbeatDissentItem(
        category=category,
        severity=severity,
        blocker=blocker,
        supporting_roles=supporting_roles,
        dissenting_roles=dissenting_roles,
        judgment_ids=judgment_ids,
        used_signal_keys=used_signal_keys,
        source_anchors=source_anchors,
        summary=_build_item_summary(ordered_judgments),
        impact_on_decision=_build_item_impact(
            category=category,
            severity=severity,
            blocker=blocker,
            final_decision=final_decision,
        ),
        metadata={
            "support_count": len(supporting_roles),
            "judgment_count": len(judgment_ids),
        },
    )


def _collect_used_signal_keys(
    judgments: Sequence[HeartbeatAgentJudgment],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(signal_key).strip()
                for judgment in judgments
                for signal_key in _judgment_used_signal_keys(judgment)
                if str(signal_key).strip()
            }
        )
    )


def _resolve_source_anchors(
    judgments: Sequence[HeartbeatAgentJudgment],
    used_signal_keys: Sequence[str],
    evidence_bundle: HeartbeatEvidenceBundle | None,
) -> tuple[HeartbeatSourceAnchor, ...]:
    formal_or_legacy_anchors = _collect_judgment_source_anchors(judgments)
    if formal_or_legacy_anchors:
        return formal_or_legacy_anchors
    return _build_source_anchors_from_evidence(used_signal_keys, evidence_bundle)


def _build_source_anchors(
    used_signal_keys: Sequence[str],
    evidence_bundle: HeartbeatEvidenceBundle | None,
) -> tuple[HeartbeatSourceAnchor, ...]:
    return _build_source_anchors_from_evidence(used_signal_keys, evidence_bundle)


def _build_source_anchors_from_evidence(
    used_signal_keys: Sequence[str],
    evidence_bundle: HeartbeatEvidenceBundle | None,
) -> tuple[HeartbeatSourceAnchor, ...]:
    return sort_dedup_source_anchors(
        source_anchor_candidates_from_signal_keys(used_signal_keys, evidence_bundle)
    )


def _build_item_summary(judgments: Sequence[HeartbeatAgentJudgment]) -> str | None:
    summary_parts: list[str] = []
    seen_parts: set[str] = set()
    for judgment in judgments:
        rationale_text = judgment.rationale_text.strip()
        if not rationale_text:
            continue
        summary_part = f"{_judgment_role(judgment)}: {rationale_text}"
        if summary_part in seen_parts:
            continue
        seen_parts.add(summary_part)
        summary_parts.append(summary_part)
    if not summary_parts:
        return None
    return " | ".join(summary_parts)


def _build_item_impact(
    *,
    category: RejectionDeficiencyCategory,
    severity: str | None,
    blocker: bool,
    final_decision: ConvergenceStatus,
) -> str:
    if category == RejectionDeficiencyCategory.SUFFICIENT:
        if final_decision == ConvergenceStatus.CONVERGED:
            return "Supports the converged decision."
        return "Approval signal was retained but did not satisfy the checkpoint threshold."
    if blocker:
        if severity is not None:
            return f"Blocks convergence as a {severity} deficiency until the issue is resolved."
        return "Blocks convergence until the deficiency is resolved."
    if final_decision == ConvergenceStatus.CONTINUE:
        if severity is not None:
            return f"Keeps the frozen candidate in the continue path with {severity} severity."
        return "Keeps the frozen candidate in the continue path."
    if severity is not None:
        return f"Retained as {severity} minority dissent against the converged decision."
    return "Retained as minority dissent against the converged decision."


def _classify_items(
    items: Sequence[HeartbeatDissentItem],
    final_decision: ConvergenceStatus,
) -> tuple[tuple[HeartbeatDissentItem, ...], tuple[HeartbeatDissentItem, ...]]:
    aligned_items = tuple(
        item for item in items if _item_supports_final_decision(item, final_decision)
    )
    if aligned_items:
        max_support = max(_item_support_count(item) for item in aligned_items)
        consensus_categories = {
            item.category for item in aligned_items if _item_support_count(item) == max_support
        }
    else:
        consensus_categories = set()

    consensus_items = tuple(item for item in items if item.category in consensus_categories)
    minority_items = tuple(item for item in items if item.category not in consensus_categories)
    return consensus_items, minority_items


def _item_supports_final_decision(
    item: HeartbeatDissentItem,
    final_decision: ConvergenceStatus,
) -> bool:
    if final_decision == ConvergenceStatus.CONVERGED:
        return item.category == RejectionDeficiencyCategory.SUFFICIENT
    return item.category != RejectionDeficiencyCategory.SUFFICIENT


def _build_decision_rationale(
    *,
    judgments: Sequence[HeartbeatAgentJudgment],
    approval_count: int,
    final_decision: ConvergenceStatus,
    grading_summary,
    minority_items: Sequence[HeartbeatDissentItem],
    unresolved_items: Sequence[HeartbeatDissentItem],
) -> tuple[str, ...]:
    rationale: list[str] = []
    total_judgments = len(judgments)
    if total_judgments == 0:
        rationale.append("No eligible heartbeat judgments were available, so discussion remains active.")
    elif final_decision == ConvergenceStatus.CONVERGED:
        rationale.append(
            f"Approval threshold was met with {approval_count} of {total_judgments} approval judgments."
        )
    else:
        rationale.append(
            f"Approval threshold was not met with {approval_count} of {total_judgments} approval judgments."
        )

    blocker_items = tuple(item for item in unresolved_items if item.blocker)
    if final_decision == ConvergenceStatus.CONTINUE and blocker_items:
        rationale.append(
            "Continue remains active because prioritized blocker deficiencies remain unresolved: "
            + _format_item_list(blocker_items)
            + "."
        )
        rationale.append(
            "Blocker deficiencies were flagged in priority order: "
            + _format_item_list(blocker_items)
            + "."
        )
    elif final_decision == ConvergenceStatus.CONTINUE and unresolved_items:
        rationale.append(
            "Continue remains active with unresolved non-blocking deficiencies led by: "
            + _format_item_list(unresolved_items)
            + "."
        )

    if final_decision == ConvergenceStatus.CONVERGED:
        reject_count = sum(
            1 for judgment in judgments if judgment.decision == HeartbeatVoteChoice.REJECT
        )
        if blocker_items:
            rationale.append(
                "Convergence threshold was met under current voting semantics even though "
                "blocker-marked dissent remains: "
                + _format_item_list(blocker_items)
                + "."
            )
            rationale.append(
                "Blocker deficiencies were flagged in priority order: "
                + _format_item_list(blocker_items)
                + "."
            )
        elif reject_count > 0 and grading_summary.highest_rejection_severity is not None:
            rationale.append(
                "Reject judgments were retained as dissent, but none were blocker-marked; "
                f"highest rejection severity was {grading_summary.highest_rejection_severity}."
            )
        elif reject_count == 0:
            rationale.append("No reject-side deficiencies remained in the aggregate view.")
    elif (
        grading_summary.highest_rejection_severity is not None
        and grading_summary.blocker_count == 0
        and unresolved_items
    ):
        rationale.append(
            "Canonical grading summary for the unresolved items remained non-blocking with "
            f"highest rejection severity {grading_summary.highest_rejection_severity}."
        )

    if minority_items:
        rationale.append(
            "Minority views were retained in priority order: "
            + _format_item_list(minority_items)
            + "."
        )
    return tuple(rationale)


def _build_recommended_next_actions(
    *,
    judgments: Sequence[HeartbeatAgentJudgment],
    final_decision: ConvergenceStatus,
    grading_summary,
    minority_items: Sequence[HeartbeatDissentItem],
    unresolved_items: Sequence[HeartbeatDissentItem],
) -> tuple[str, ...]:
    actions: list[str] = []
    if not judgments:
        actions.append("Resume discussion and collect fresh role-specific heartbeat judgments.")
        return tuple(actions)

    follow_up_items = tuple(
        item
        for item in _merge_unique_items(unresolved_items, minority_items)
        if item.category != RejectionDeficiencyCategory.SUFFICIENT
    )

    if final_decision == ConvergenceStatus.CONVERGED:
        actions.extend(
            _build_item_follow_up_actions(
                follow_up_items,
                final_decision=final_decision,
                limit=2,
            )
        )
        actions.append("Prepare terminal reporting from the frozen candidate and aggregate artifact.")
        if minority_items and grading_summary.highest_rejection_severity is not None:
            actions.append(
                "Carry retained dissent into downstream reporting in the same priority order."
            )
        return tuple(dict.fromkeys(actions))

    actions.extend(
        _build_item_follow_up_actions(
            follow_up_items,
            final_decision=final_decision,
            limit=3,
        )
    )
    if unresolved_items:
        actions.append("Resume discussion with the prioritized unresolved items before the next heartbeat.")
    else:
        actions.append("Resume discussion and collect fresh role-specific heartbeat judgments.")
    if minority_items:
        actions.append("Preserve minority items for downstream reporting and replay in priority order.")
    return tuple(dict.fromkeys(actions))


def _merge_severity(judgments: Sequence[HeartbeatAgentJudgment]) -> str | None:
    severities = tuple(
        sorted(
            {
                severity
                for judgment in judgments
                if (severity := extract_judgment_severity(judgment)) is not None
            },
            key=severity_sort_key,
            reverse=True,
        )
    )
    if not severities:
        return None
    return severities[0]


def _judgment_used_signal_keys(judgment: HeartbeatAgentJudgment) -> tuple[str, ...]:
    if judgment.used_signal_keys:
        return judgment.used_signal_keys
    metadata = judgment.metadata if isinstance(judgment.metadata, Mapping) else {}
    value = metadata.get("used_signal_keys")
    if value is None:
        return ()
    if isinstance(value, str):
        normalized = value.strip()
        return (normalized,) if normalized else ()
    if isinstance(value, Sequence):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _collect_judgment_source_anchors(
    judgments: Sequence[HeartbeatAgentJudgment],
) -> tuple[HeartbeatSourceAnchor, ...]:
    return sort_dedup_source_anchors(
        tuple(
            anchor
            for judgment in judgments
            for anchor in _judgment_source_anchors(judgment)
        )
    )


def _judgment_source_anchors(
    judgment: HeartbeatAgentJudgment,
) -> tuple[HeartbeatSourceAnchor, ...]:
    metadata = judgment.metadata if isinstance(judgment.metadata, Mapping) else {}
    return resolve_source_anchors(
        formal_source_anchors=judgment.source_anchors,
        legacy_source_anchors=metadata.get("source_anchors"),
        sort_result=False,
    )


def _resolve_evidence_bundle_id(
    evidence_bundle: HeartbeatEvidenceBundle | None,
    judgments: Sequence[HeartbeatAgentJudgment],
) -> str | None:
    if evidence_bundle is not None:
        return evidence_bundle.evidence_bundle_id
    evidence_bundle_ids = sorted(
        {judgment.evidence_bundle_id for judgment in judgments if judgment.evidence_bundle_id}
    )
    if not evidence_bundle_ids:
        return None
    return evidence_bundle_ids[0]


def _judgment_category(judgment: HeartbeatAgentJudgment) -> RejectionDeficiencyCategory:
    if judgment.deficiency_category is not None:
        return judgment.deficiency_category
    if judgment.decision == HeartbeatVoteChoice.APPROVE:
        return RejectionDeficiencyCategory.SUFFICIENT
    return RejectionDeficiencyCategory.OTHER


def _judgment_role(judgment: HeartbeatAgentJudgment) -> str:
    metadata = judgment.metadata if isinstance(judgment.metadata, Mapping) else {}
    role = metadata.get("agent_role")
    if isinstance(role, str):
        normalized = role.strip()
        if normalized:
            return normalized
    return judgment.agent_id

def _judgment_priority_sort_key(
    judgment: HeartbeatAgentJudgment,
) -> tuple[int, int, str, str, str]:
    return (
        0 if extract_judgment_blocker(judgment) else 1,
        -severity_sort_key(extract_judgment_severity(judgment))[0],
        _judgment_role(judgment),
        judgment.agent_id,
        judgment.judgment_id,
    )


def _sort_judgments_by_priority(
    judgments: Sequence[HeartbeatAgentJudgment],
) -> tuple[HeartbeatAgentJudgment, ...]:
    return tuple(sorted(judgments, key=_judgment_priority_sort_key))


def _prioritize_items(
    items: Sequence[HeartbeatDissentItem],
) -> tuple[HeartbeatDissentItem, ...]:
    prioritized_items = _items_in_priority_order(items)
    return tuple(
        replace(item, priority_rank=index)
        for index, item in enumerate(prioritized_items, start=1)
    )


def _items_in_priority_order(
    items: Sequence[HeartbeatDissentItem],
) -> tuple[HeartbeatDissentItem, ...]:
    return tuple(sorted(items, key=_item_priority_sort_key))


def _item_priority_sort_key(
    item: HeartbeatDissentItem,
) -> tuple[int, int, int, int, int, int, str]:
    if item.priority_rank > 0:
        return (0, item.priority_rank, 0, 0, 0, 0, item.category.value)
    return (
        1,
        0 if item.blocker else 1,
        0 if item.category != RejectionDeficiencyCategory.SUFFICIENT else 1,
        -severity_sort_key(item.severity)[0],
        -_item_support_count(item),
        -_item_judgment_count(item),
        item.category.value,
    )


def _item_support_count(item: HeartbeatDissentItem) -> int:
    return len(item.supporting_roles)


def _item_judgment_count(item: HeartbeatDissentItem) -> int:
    return len(item.judgment_ids)


def _format_item_list(
    items: Sequence[HeartbeatDissentItem],
    *,
    limit: int = 3,
) -> str:
    return ", ".join(_format_item_reference(item) for item in items[:limit])


def _format_item_reference(item: HeartbeatDissentItem) -> str:
    annotations: list[str] = []
    if item.severity is not None:
        annotations.append(item.severity)
    if item.blocker:
        annotations.append("blocker")
    if item.supporting_roles:
        annotations.append("supported by " + ", ".join(item.supporting_roles))
    if not annotations:
        return item.category.value
    return f"{item.category.value} ({'; '.join(annotations)})"


def _build_item_follow_up_actions(
    items: Sequence[HeartbeatDissentItem],
    *,
    final_decision: ConvergenceStatus,
    limit: int,
) -> tuple[str, ...]:
    actions: list[str] = []
    for item in items:
        if len(actions) >= limit:
            break
        action = _build_item_follow_up_action(item, final_decision=final_decision)
        if action is None or action in actions:
            continue
        actions.append(action)
    return tuple(actions)


def _build_item_follow_up_action(
    item: HeartbeatDissentItem,
    *,
    final_decision: ConvergenceStatus,
) -> str | None:
    if item.category == RejectionDeficiencyCategory.SUFFICIENT:
        return None

    severity_label = item.severity or "unspecified"
    roles_label = ", ".join(item.supporting_roles) if item.supporting_roles else "unknown roles"
    if final_decision == ConvergenceStatus.CONVERGED:
        if item.blocker:
            return (
                f"Surface retained blocker dissent for {item.category.value} ({severity_label}) "
                f"before presenting the final output; supported by {roles_label}."
            )
        if item.severity in {"critical", "major"}:
            return (
                f"Call out retained high-severity dissent for {item.category.value} "
                f"({severity_label}) in downstream reporting; supported by {roles_label}."
            )
        return (
            f"Carry retained dissent for {item.category.value} ({severity_label}) into "
            f"downstream reporting; supported by {roles_label}."
        )

    if item.blocker:
        return (
            f"Resolve blocker {item.category.value} ({severity_label}) before the next "
            f"heartbeat; supported by {roles_label}."
        )
    if item.severity in {"critical", "major"}:
        return (
            f"Address high-severity {item.category.value} ({severity_label}) before the next "
            f"heartbeat; supported by {roles_label}."
        )
    return (
        f"Tighten {item.category.value} ({severity_label}) in the next discussion round; "
        f"supported by {roles_label}."
    )


def _merge_unique_items(
    *item_groups: Sequence[HeartbeatDissentItem],
) -> tuple[HeartbeatDissentItem, ...]:
    items_by_category: dict[RejectionDeficiencyCategory, HeartbeatDissentItem] = {}
    for group in item_groups:
        for item in group:
            items_by_category.setdefault(item.category, item)
    return _items_in_priority_order(tuple(items_by_category.values()))
