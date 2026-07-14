from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.orchestrator.convergence import (
    ConvergenceStatus,
    HeartbeatAggregateArtifact,
    HeartbeatAggregateResult,
    HeartbeatDissentItem,
    RejectionDeficiencyCategory,
)
from agent_os.orchestrator.heartbeat_candidate_presentation import (
    HeartbeatCandidatePresentation,
    build_heartbeat_candidate_presentation,
)
from agent_os.orchestrator.heartbeat_candidate_snapshot import (
    HeartbeatCandidateSnapshot,
)
from agent_os.orchestrator.heartbeat_convergence_profile import (
    HeartbeatConvergenceDominantReason,
    HeartbeatConvergenceFollowupBias,
    HeartbeatConvergenceProfile,
    HeartbeatConvergenceReservationLevel,
    HeartbeatConvergenceSemanticState,
)
from agent_os.orchestrator.heartbeat_outcome_snapshot import (
    HeartbeatOutcomeConsumerReadiness,
    HeartbeatOutcomeSnapshot,
    build_heartbeat_outcome_snapshot,
)
from agent_os.orchestrator.heartbeat_report_adapter import build_heartbeat_report_payload
from agent_os.orchestrator.heartbeat_terminal_payload import (
    HeartbeatTerminalDisplayPolicy,
    HeartbeatTerminalDisplaySection,
    HeartbeatTerminalDisplaySectionKind,
    HeartbeatTerminalPayload,
    build_heartbeat_terminal_payload,
    build_heartbeat_terminal_view,
)


def build_item(
    *,
    category: RejectionDeficiencyCategory,
    severity: str | None = None,
    blocker: bool = False,
    priority_rank: int = 1,
    role: str = "reviewer",
    judgment_id: str = "judgment-1",
) -> HeartbeatDissentItem:
    return HeartbeatDissentItem(
        category=category,
        severity=severity,
        blocker=blocker,
        supporting_roles=(role,),
        dissenting_roles=("planner",) if role != "planner" else ("reviewer",),
        judgment_ids=(judgment_id,),
        priority_rank=priority_rank,
        summary=f"{category.value} summary",
        impact_on_decision=f"{category.value} impact",
    )


def build_candidate_snapshot(
    *,
    summary: str = "candidate summary",
    source_round: int | None = 4,
) -> HeartbeatCandidateSnapshot:
    return HeartbeatCandidateSnapshot(
        candidate_id="candidate-1",
        checkpoint_id="checkpoint-1",
        summary=summary,
        source_round=source_round,
        supporting_context_refs=("ctx-1", "ctx-2"),
    )


def build_profile(
    *,
    final_decision: ConvergenceStatus,
    semantic_state: HeartbeatConvergenceSemanticState,
    dominant_reason: HeartbeatConvergenceDominantReason,
    reservation_level: HeartbeatConvergenceReservationLevel,
    followup_bias: HeartbeatConvergenceFollowupBias,
    has_blocker: bool = False,
    highest_rejection_severity: str | None = None,
    unresolved_high_priority_count: int = 0,
    minority_high_priority_count: int = 0,
    retained_item_count: int = 0,
    retained_high_priority_count: int = 0,
) -> HeartbeatConvergenceProfile:
    return HeartbeatConvergenceProfile(
        final_decision=final_decision,
        semantic_state=semantic_state,
        dominant_reason=dominant_reason,
        has_blocker=has_blocker,
        highest_rejection_severity=highest_rejection_severity,
        unresolved_high_priority_count=unresolved_high_priority_count,
        minority_high_priority_count=minority_high_priority_count,
        reservation_level=reservation_level,
        explanation_summary="profile summary",
        followup_bias=followup_bias,
        metadata={
            "retained_item_count": retained_item_count,
            "retained_high_priority_count": retained_high_priority_count,
        },
    )


def build_artifact(
    *,
    final_decision: ConvergenceStatus,
    highest_rejection_severity: str | None = None,
    blocker_count: int = 0,
    candidate_snapshot: HeartbeatCandidateSnapshot | None = None,
    convergence_profile: HeartbeatConvergenceProfile | None = None,
    outcome_snapshot: HeartbeatOutcomeSnapshot | None = None,
    candidate_presentation: HeartbeatCandidatePresentation | None = None,
    terminal_payload: HeartbeatTerminalPayload | None = None,
    consensus_items: tuple[HeartbeatDissentItem, ...] = (),
    minority_items: tuple[HeartbeatDissentItem, ...] = (),
    unresolved_items: tuple[HeartbeatDissentItem, ...] = (),
    decision_rationale: tuple[str, ...] = ("rationale-1", "rationale-2"),
    recommended_next_actions: tuple[str, ...] = ("action-1", "action-2"),
) -> HeartbeatAggregateArtifact:
    return HeartbeatAggregateArtifact(
        aggregate_result_id="aggregate-1",
        checkpoint_id="checkpoint-1",
        candidate_id="candidate-1",
        final_decision=final_decision,
        highest_rejection_severity=highest_rejection_severity,
        blocker_count=blocker_count,
        severity_histogram=(
            {highest_rejection_severity: 1}
            if highest_rejection_severity is not None
            else {}
        ),
        candidate_snapshot=candidate_snapshot,
        convergence_profile=convergence_profile,
        outcome_snapshot=outcome_snapshot,
        candidate_presentation=candidate_presentation,
        terminal_payload=terminal_payload,
        consensus_items=consensus_items,
        minority_items=minority_items,
        unresolved_items=unresolved_items,
        decision_rationale=decision_rationale,
        recommended_next_actions=recommended_next_actions,
    )


def build_result(
    *,
    artifact: HeartbeatAggregateArtifact,
    recommended_outcome: ConvergenceStatus,
    highest_rejection_severity: str | None = None,
    blocker_count: int = 0,
    candidate_snapshot: HeartbeatCandidateSnapshot | None = None,
    convergence_profile: HeartbeatConvergenceProfile | None = None,
    outcome_snapshot: HeartbeatOutcomeSnapshot | None = None,
    candidate_presentation: HeartbeatCandidatePresentation | None = None,
    terminal_payload: HeartbeatTerminalPayload | None = None,
) -> HeartbeatAggregateResult:
    return HeartbeatAggregateResult(
        aggregate_result_id=artifact.aggregate_result_id,
        checkpoint_id=artifact.checkpoint_id,
        total_judgments=3,
        approval_count=2 if recommended_outcome == ConvergenceStatus.CONVERGED else 1,
        rejection_count=1 if highest_rejection_severity is not None else 0,
        approval_ratio=2 / 3 if recommended_outcome == ConvergenceStatus.CONVERGED else 1 / 3,
        rejection_ratio=1 / 3 if highest_rejection_severity is not None else 0.0,
        recommended_outcome=recommended_outcome,
        highest_rejection_severity=highest_rejection_severity,
        blocker_count=blocker_count,
        severity_histogram=(
            {highest_rejection_severity: 1}
            if highest_rejection_severity is not None
            else {}
        ),
        aggregate_artifact=artifact,
        candidate_snapshot=candidate_snapshot,
        convergence_profile=convergence_profile,
        outcome_snapshot=outcome_snapshot,
        candidate_presentation=candidate_presentation,
        terminal_payload=terminal_payload,
    )


def build_attached_result(
    *,
    final_decision: ConvergenceStatus,
    profile: HeartbeatConvergenceProfile,
    candidate_snapshot: HeartbeatCandidateSnapshot | None = None,
    highest_rejection_severity: str | None = None,
    blocker_count: int = 0,
    consensus_items: tuple[HeartbeatDissentItem, ...] = (),
    minority_items: tuple[HeartbeatDissentItem, ...] = (),
    unresolved_items: tuple[HeartbeatDissentItem, ...] = (),
    decision_rationale: tuple[str, ...] = ("rationale-1", "rationale-2"),
    recommended_next_actions: tuple[str, ...] = ("action-1", "action-2"),
) -> HeartbeatAggregateResult:
    candidate_snapshot = candidate_snapshot or build_candidate_snapshot()
    artifact = build_artifact(
        final_decision=final_decision,
        highest_rejection_severity=highest_rejection_severity,
        blocker_count=blocker_count,
        candidate_snapshot=candidate_snapshot,
        convergence_profile=profile,
        consensus_items=consensus_items,
        minority_items=minority_items,
        unresolved_items=unresolved_items,
        decision_rationale=decision_rationale,
        recommended_next_actions=recommended_next_actions,
    )
    outcome = build_heartbeat_outcome_snapshot(artifact)
    artifact = build_artifact(
        final_decision=final_decision,
        highest_rejection_severity=highest_rejection_severity,
        blocker_count=blocker_count,
        candidate_snapshot=candidate_snapshot,
        convergence_profile=profile,
        outcome_snapshot=outcome,
        consensus_items=consensus_items,
        minority_items=minority_items,
        unresolved_items=unresolved_items,
        decision_rationale=decision_rationale,
        recommended_next_actions=recommended_next_actions,
    )
    candidate_presentation = build_heartbeat_candidate_presentation(artifact)
    artifact = build_artifact(
        final_decision=final_decision,
        highest_rejection_severity=highest_rejection_severity,
        blocker_count=blocker_count,
        candidate_snapshot=candidate_snapshot,
        convergence_profile=profile,
        outcome_snapshot=outcome,
        candidate_presentation=candidate_presentation,
        consensus_items=consensus_items,
        minority_items=minority_items,
        unresolved_items=unresolved_items,
        decision_rationale=decision_rationale,
        recommended_next_actions=recommended_next_actions,
    )
    terminal_payload = build_heartbeat_terminal_payload(artifact)
    artifact = build_artifact(
        final_decision=final_decision,
        highest_rejection_severity=highest_rejection_severity,
        blocker_count=blocker_count,
        candidate_snapshot=candidate_snapshot,
        convergence_profile=profile,
        outcome_snapshot=outcome,
        candidate_presentation=candidate_presentation,
        terminal_payload=terminal_payload,
        consensus_items=consensus_items,
        minority_items=minority_items,
        unresolved_items=unresolved_items,
        decision_rationale=decision_rationale,
        recommended_next_actions=recommended_next_actions,
    )
    return build_result(
        artifact=artifact,
        recommended_outcome=final_decision,
        highest_rejection_severity=highest_rejection_severity,
        blocker_count=blocker_count,
        candidate_snapshot=candidate_snapshot,
        convergence_profile=profile,
        outcome_snapshot=outcome,
        candidate_presentation=candidate_presentation,
        terminal_payload=terminal_payload,
    )


def get_section(
    payload: HeartbeatTerminalPayload,
    kind: HeartbeatTerminalDisplaySectionKind,
) -> HeartbeatTerminalDisplaySection:
    for section in payload.display_sections:
        if section.kind == kind:
            return section
    raise AssertionError(f"Expected display section for {kind.value}.")


class HeartbeatTerminalPayloadTests(unittest.TestCase):
    def test_builds_terminal_payload_from_attached_objects(self) -> None:
        retained_item = build_item(
            category=RejectionDeficiencyCategory.CORRECTNESS_RISK,
            severity="major",
            priority_rank=1,
            role="reviewer",
        )
        candidate_snapshot = build_candidate_snapshot(summary="terminal candidate")
        profile = build_profile(
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS,
            dominant_reason=HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP,
            reservation_level=HeartbeatConvergenceReservationLevel.ELEVATED,
            followup_bias=HeartbeatConvergenceFollowupBias.CARRY_FORWARD_RESERVATIONS,
            highest_rejection_severity="major",
            minority_high_priority_count=1,
            retained_item_count=1,
            retained_high_priority_count=1,
        )
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
            highest_rejection_severity="major",
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            consensus_items=(build_item(category=RejectionDeficiencyCategory.SUFFICIENT),),
            minority_items=(retained_item,),
        )
        outcome = build_heartbeat_outcome_snapshot(artifact)
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
            highest_rejection_severity="major",
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome,
            consensus_items=artifact.consensus_items,
            minority_items=artifact.minority_items,
        )
        candidate_presentation = build_heartbeat_candidate_presentation(artifact)
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
            highest_rejection_severity="major",
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome,
            candidate_presentation=candidate_presentation,
            consensus_items=artifact.consensus_items,
            minority_items=artifact.minority_items,
        )
        result = build_result(
            artifact=artifact,
            recommended_outcome=ConvergenceStatus.CONVERGED,
            highest_rejection_severity="major",
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome,
            candidate_presentation=candidate_presentation,
        )

        terminal_payload = build_heartbeat_terminal_payload(result)

        self.assertEqual(terminal_payload.final_decision, ConvergenceStatus.CONVERGED)
        self.assertEqual(
            terminal_payload.consumer_readiness,
            HeartbeatOutcomeConsumerReadiness.TERMINAL_READY_WITH_RESERVATIONS,
        )
        self.assertIs(terminal_payload.candidate, candidate_presentation)
        self.assertEqual(terminal_payload.decision_rationale, artifact.decision_rationale)
        self.assertEqual(
            terminal_payload.recommended_next_actions,
            artifact.recommended_next_actions,
        )
        self.assertEqual(terminal_payload.top_retained_items, outcome.top_retained_items)
        self.assertEqual(terminal_payload.reservation_summary, outcome.reservation_summary)
        self.assertEqual(
            tuple(section.kind for section in terminal_payload.display_sections),
            (
                HeartbeatTerminalDisplaySectionKind.CANDIDATE,
                HeartbeatTerminalDisplaySectionKind.RESERVATION_SUMMARY,
                HeartbeatTerminalDisplaySectionKind.TOP_RETAINED_ITEMS,
                HeartbeatTerminalDisplaySectionKind.DECISION_RATIONALE,
                HeartbeatTerminalDisplaySectionKind.RECOMMENDED_NEXT_ACTIONS,
            ),
        )

    def test_artifact_rejects_terminal_payload_without_candidate_presentation(self) -> None:
        candidate_snapshot = build_candidate_snapshot()
        profile = build_profile(
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_CLEAN,
            dominant_reason=HeartbeatConvergenceDominantReason.NO_MATERIAL_RESERVATIONS,
            reservation_level=HeartbeatConvergenceReservationLevel.NONE,
            followup_bias=HeartbeatConvergenceFollowupBias.PREPARE_TERMINAL_OUTPUT,
        )
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
        )
        outcome = build_heartbeat_outcome_snapshot(artifact)
        terminal_payload = HeartbeatTerminalPayload(
            final_decision=ConvergenceStatus.CONVERGED,
            consumer_readiness=HeartbeatOutcomeConsumerReadiness.TERMINAL_READY,
            candidate=HeartbeatCandidatePresentation(
                candidate_id="candidate-1",
                checkpoint_id="checkpoint-1",
                summary="candidate summary",
                final_decision=ConvergenceStatus.CONVERGED,
                semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_CLEAN,
                reservation_level=HeartbeatConvergenceReservationLevel.NONE,
                consumer_readiness=HeartbeatOutcomeConsumerReadiness.TERMINAL_READY,
            ),
            decision_rationale=("rationale-1",),
            recommended_next_actions=("action-1",),
            display_sections=(
                HeartbeatTerminalDisplaySection(
                    kind=HeartbeatTerminalDisplaySectionKind.CANDIDATE,
                    title="Candidate",
                    lines=("candidate summary",),
                ),
                HeartbeatTerminalDisplaySection(
                    kind=HeartbeatTerminalDisplaySectionKind.DECISION_RATIONALE,
                    title="Decision Rationale",
                    lines=("rationale-1",),
                ),
                HeartbeatTerminalDisplaySection(
                    kind=HeartbeatTerminalDisplaySectionKind.RECOMMENDED_NEXT_ACTIONS,
                    title="Recommended Next Actions",
                    lines=("action-1",),
                ),
            ),
            metadata={
                "display_policy_version": "terminal_v1",
                "display_section_order": (
                    "candidate",
                    "reservation_summary",
                    "top_retained_items",
                    "decision_rationale",
                    "recommended_next_actions",
                ),
                "display_omit_empty_sections": True,
                "display_retained_items_limit": 2,
                "display_decision_rationale_limit": 3,
                "display_recommended_next_actions_limit": 3,
                "display_section_count": 3,
                "retained_item_count": 0,
                "display_retained_items_count": 0,
                "display_retained_items_truncated": False,
                "display_decision_rationale_count": 1,
                "display_decision_rationale_truncated": False,
                "display_recommended_next_actions_count": 1,
                "display_recommended_next_actions_truncated": False,
                "display_omitted_sections": ("reservation_summary", "top_retained_items"),
            },
        )

        with self.assertRaises(ValueError):
            build_artifact(
                final_decision=ConvergenceStatus.CONVERGED,
                candidate_snapshot=candidate_snapshot,
                convergence_profile=profile,
                outcome_snapshot=outcome,
                terminal_payload=terminal_payload,
            )

    def test_adapter_projects_attached_terminal_payload(self) -> None:
        retained_item = build_item(
            category=RejectionDeficiencyCategory.INCOMPLETENESS,
            severity="critical",
            blocker=True,
            priority_rank=1,
            role="executor",
        )
        candidate_snapshot = build_candidate_snapshot(summary="payload candidate")
        profile = build_profile(
            final_decision=ConvergenceStatus.CONTINUE,
            semantic_state=HeartbeatConvergenceSemanticState.BLOCKED_BY_BLOCKER,
            dominant_reason=HeartbeatConvergenceDominantReason.BLOCKER_PRESENT,
            reservation_level=HeartbeatConvergenceReservationLevel.BLOCKING,
            followup_bias=HeartbeatConvergenceFollowupBias.RESOLVE_BLOCKERS,
            has_blocker=True,
            highest_rejection_severity="critical",
            unresolved_high_priority_count=1,
            retained_item_count=1,
            retained_high_priority_count=1,
        )
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONTINUE,
            highest_rejection_severity="critical",
            blocker_count=1,
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            consensus_items=(retained_item,),
            unresolved_items=(retained_item,),
        )
        outcome = build_heartbeat_outcome_snapshot(artifact)
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONTINUE,
            highest_rejection_severity="critical",
            blocker_count=1,
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome,
            consensus_items=artifact.consensus_items,
            unresolved_items=artifact.unresolved_items,
        )
        candidate_presentation = build_heartbeat_candidate_presentation(artifact)
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONTINUE,
            highest_rejection_severity="critical",
            blocker_count=1,
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome,
            candidate_presentation=candidate_presentation,
            consensus_items=artifact.consensus_items,
            unresolved_items=artifact.unresolved_items,
        )
        terminal_payload = build_heartbeat_terminal_payload(artifact)
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONTINUE,
            highest_rejection_severity="critical",
            blocker_count=1,
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome,
            candidate_presentation=candidate_presentation,
            terminal_payload=terminal_payload,
            consensus_items=artifact.consensus_items,
            unresolved_items=artifact.unresolved_items,
        )
        result = build_result(
            artifact=artifact,
            recommended_outcome=ConvergenceStatus.CONTINUE,
            highest_rejection_severity="critical",
            blocker_count=1,
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome,
            candidate_presentation=candidate_presentation,
            terminal_payload=terminal_payload,
        )

        payload = build_heartbeat_report_payload(result)

        self.assertIsNotNone(payload.terminal_payload)
        self.assertIsNotNone(payload.candidate_presentation)
        self.assertIs(payload.terminal_payload.candidate, payload.candidate_presentation)
        self.assertEqual(payload.terminal_payload.final_decision, "continue")
        self.assertEqual(
            payload.terminal_payload.consumer_readiness,
            HeartbeatOutcomeConsumerReadiness.REMEDIATION_REQUIRED.value,
        )
        self.assertEqual(
            tuple(section.kind for section in payload.terminal_payload.display_sections),
            (
                "candidate",
                "reservation_summary",
                "top_retained_items",
                "decision_rationale",
                "recommended_next_actions",
            ),
        )

    def test_adapter_rejects_inconsistent_terminal_payload_references(self) -> None:
        candidate_snapshot = build_candidate_snapshot()
        profile = build_profile(
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_CLEAN,
            dominant_reason=HeartbeatConvergenceDominantReason.NO_MATERIAL_RESERVATIONS,
            reservation_level=HeartbeatConvergenceReservationLevel.NONE,
            followup_bias=HeartbeatConvergenceFollowupBias.PREPARE_TERMINAL_OUTPUT,
        )
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
        )
        outcome = build_heartbeat_outcome_snapshot(artifact)
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome,
        )
        candidate_presentation = build_heartbeat_candidate_presentation(artifact)
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome,
            candidate_presentation=candidate_presentation,
        )
        terminal_payload = build_heartbeat_terminal_payload(artifact)
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome,
            candidate_presentation=candidate_presentation,
            terminal_payload=terminal_payload,
        )
        result = build_result(
            artifact=artifact,
            recommended_outcome=ConvergenceStatus.CONVERGED,
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome,
            candidate_presentation=candidate_presentation,
            terminal_payload=terminal_payload,
        )
        object.__setattr__(
            result,
            "terminal_payload",
            HeartbeatTerminalPayload(
                final_decision=ConvergenceStatus.CONVERGED,
                consumer_readiness=HeartbeatOutcomeConsumerReadiness.TERMINAL_READY,
                candidate=candidate_presentation,
                decision_rationale=("mutated rationale",),
                recommended_next_actions=("action-1",),
                display_sections=(
                    HeartbeatTerminalDisplaySection(
                        kind=HeartbeatTerminalDisplaySectionKind.CANDIDATE,
                        title="Candidate",
                        lines=terminal_payload.display_sections[0].lines,
                    ),
                    HeartbeatTerminalDisplaySection(
                        kind=HeartbeatTerminalDisplaySectionKind.DECISION_RATIONALE,
                        title="Decision Rationale",
                        lines=("mutated rationale",),
                    ),
                    HeartbeatTerminalDisplaySection(
                        kind=HeartbeatTerminalDisplaySectionKind.RECOMMENDED_NEXT_ACTIONS,
                        title="Recommended Next Actions",
                        lines=("action-1",),
                    ),
                ),
                metadata={
                    "display_policy_version": "terminal_v1",
                    "display_section_order": (
                        "candidate",
                        "reservation_summary",
                        "top_retained_items",
                        "decision_rationale",
                        "recommended_next_actions",
                    ),
                    "display_omit_empty_sections": True,
                    "display_retained_items_limit": 2,
                    "display_decision_rationale_limit": 3,
                    "display_recommended_next_actions_limit": 3,
                    "display_section_count": 3,
                    "retained_item_count": 0,
                    "display_retained_items_count": 0,
                    "display_retained_items_truncated": False,
                    "display_decision_rationale_count": 1,
                    "display_decision_rationale_truncated": False,
                    "display_recommended_next_actions_count": 1,
                    "display_recommended_next_actions_truncated": False,
                    "display_omitted_sections": ("reservation_summary", "top_retained_items"),
                },
            ),
        )

        with self.assertRaises(ValueError):
            build_heartbeat_report_payload(result)

    def test_build_heartbeat_terminal_view_reuses_attached_payload(self) -> None:
        retained_item = build_item(
            category=RejectionDeficiencyCategory.CORRECTNESS_RISK,
            severity="major",
            priority_rank=1,
            role="reviewer",
        )
        profile = build_profile(
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS,
            dominant_reason=HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP,
            reservation_level=HeartbeatConvergenceReservationLevel.ELEVATED,
            followup_bias=HeartbeatConvergenceFollowupBias.CARRY_FORWARD_RESERVATIONS,
            highest_rejection_severity="major",
            minority_high_priority_count=1,
            retained_item_count=1,
            retained_high_priority_count=1,
        )
        result = build_attached_result(
            final_decision=ConvergenceStatus.CONVERGED,
            profile=profile,
            highest_rejection_severity="major",
            minority_items=(retained_item,),
        )

        terminal_view = build_heartbeat_terminal_view(result)
        artifact_view = build_heartbeat_terminal_view(result.aggregate_artifact)

        self.assertIs(terminal_view, result.terminal_payload)
        self.assertIs(artifact_view, result.terminal_payload)
        self.assertIs(terminal_view, result.aggregate_artifact.terminal_payload)
        self.assertIs(terminal_view.candidate, result.candidate_presentation)
        self.assertIs(terminal_view.candidate, result.aggregate_artifact.candidate_presentation)

    def test_build_heartbeat_terminal_view_rejects_incomplete_attachment(self) -> None:
        profile = build_profile(
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_CLEAN,
            dominant_reason=HeartbeatConvergenceDominantReason.NO_MATERIAL_RESERVATIONS,
            reservation_level=HeartbeatConvergenceReservationLevel.NONE,
            followup_bias=HeartbeatConvergenceFollowupBias.PREPARE_TERMINAL_OUTPUT,
        )
        result = build_attached_result(
            final_decision=ConvergenceStatus.CONVERGED,
            profile=profile,
        )
        object.__setattr__(result, "terminal_payload", None)
        object.__setattr__(result.aggregate_artifact, "terminal_payload", None)

        with self.assertRaisesRegex(ValueError, "terminal_payload"):
            build_heartbeat_terminal_view(result)

    def test_build_heartbeat_terminal_view_rejects_equal_but_distinct_outcome_snapshot(self) -> None:
        retained_item = build_item(
            category=RejectionDeficiencyCategory.CORRECTNESS_RISK,
            severity="major",
            priority_rank=1,
            role="reviewer",
        )
        profile = build_profile(
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS,
            dominant_reason=HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP,
            reservation_level=HeartbeatConvergenceReservationLevel.ELEVATED,
            followup_bias=HeartbeatConvergenceFollowupBias.CARRY_FORWARD_RESERVATIONS,
            highest_rejection_severity="major",
            minority_high_priority_count=1,
            retained_item_count=1,
            retained_high_priority_count=1,
        )
        result = build_attached_result(
            final_decision=ConvergenceStatus.CONVERGED,
            profile=profile,
            highest_rejection_severity="major",
            minority_items=(retained_item,),
        )
        original_outcome = result.outcome_snapshot
        self.assertIsNotNone(original_outcome)
        cloned_outcome = HeartbeatOutcomeSnapshot(
            final_decision=original_outcome.final_decision,
            convergence_profile=original_outcome.convergence_profile,
            candidate_snapshot=original_outcome.candidate_snapshot,
            highest_rejection_severity=original_outcome.highest_rejection_severity,
            blocker_count=original_outcome.blocker_count,
            reservation_summary=original_outcome.reservation_summary,
            decision_rationale=original_outcome.decision_rationale,
            recommended_next_actions=original_outcome.recommended_next_actions,
            consumer_readiness=original_outcome.consumer_readiness,
            top_retained_items=original_outcome.top_retained_items,
            metadata=dict(original_outcome.metadata),
        )
        object.__setattr__(result, "outcome_snapshot", cloned_outcome)

        with self.assertRaisesRegex(ValueError, "same object instance"):
            build_heartbeat_terminal_view(result)

    def test_display_policy_omits_empty_sections_deterministically(self) -> None:
        profile = build_profile(
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_CLEAN,
            dominant_reason=HeartbeatConvergenceDominantReason.NO_MATERIAL_RESERVATIONS,
            reservation_level=HeartbeatConvergenceReservationLevel.NONE,
            followup_bias=HeartbeatConvergenceFollowupBias.PREPARE_TERMINAL_OUTPUT,
        )
        result = build_attached_result(
            final_decision=ConvergenceStatus.CONVERGED,
            profile=profile,
        )

        payload = build_heartbeat_terminal_view(result)

        self.assertEqual(
            tuple(section.kind for section in payload.display_sections),
            (
                HeartbeatTerminalDisplaySectionKind.CANDIDATE,
                HeartbeatTerminalDisplaySectionKind.DECISION_RATIONALE,
                HeartbeatTerminalDisplaySectionKind.RECOMMENDED_NEXT_ACTIONS,
            ),
        )
        self.assertEqual(payload.metadata["display_section_count"], 3)
        self.assertEqual(
            payload.metadata["display_omitted_sections"],
            ("reservation_summary", "top_retained_items"),
        )

    def test_display_policy_caps_retained_items_and_budgets_deterministically(self) -> None:
        retained_items = (
            build_item(
                category=RejectionDeficiencyCategory.CORRECTNESS_RISK,
                severity="major",
                priority_rank=1,
                judgment_id="judgment-1",
            ),
            build_item(
                category=RejectionDeficiencyCategory.INCOMPLETENESS,
                severity="major",
                priority_rank=2,
                judgment_id="judgment-2",
            ),
            build_item(
                category=RejectionDeficiencyCategory.EVIDENCE_GAP,
                severity="major",
                priority_rank=3,
                judgment_id="judgment-3",
            ),
        )
        profile = build_profile(
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS,
            dominant_reason=HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP,
            reservation_level=HeartbeatConvergenceReservationLevel.ELEVATED,
            followup_bias=HeartbeatConvergenceFollowupBias.CARRY_FORWARD_RESERVATIONS,
            highest_rejection_severity="major",
            minority_high_priority_count=3,
            retained_item_count=3,
            retained_high_priority_count=3,
        )
        result = build_attached_result(
            final_decision=ConvergenceStatus.CONVERGED,
            profile=profile,
            highest_rejection_severity="major",
            minority_items=retained_items,
            decision_rationale=("rationale-1", "rationale-2", "rationale-3", "rationale-4"),
            recommended_next_actions=("action-1", "action-2", "action-3", "action-4"),
        )

        payload = build_heartbeat_terminal_view(result)
        retained_section = get_section(payload, HeartbeatTerminalDisplaySectionKind.TOP_RETAINED_ITEMS)
        rationale_section = get_section(
            payload,
            HeartbeatTerminalDisplaySectionKind.DECISION_RATIONALE,
        )
        actions_section = get_section(
            payload,
            HeartbeatTerminalDisplaySectionKind.RECOMMENDED_NEXT_ACTIONS,
        )

        self.assertEqual(len(payload.top_retained_items), 3)
        self.assertEqual(len(retained_section.lines), 2)
        self.assertEqual(rationale_section.lines, ("rationale-1", "rationale-2", "rationale-3"))
        self.assertEqual(actions_section.lines, ("action-1", "action-2", "action-3"))
        self.assertTrue(payload.metadata["display_retained_items_truncated"])
        self.assertTrue(payload.metadata["display_decision_rationale_truncated"])
        self.assertTrue(payload.metadata["display_recommended_next_actions_truncated"])
        self.assertEqual(payload.metadata["display_retained_items_count"], 2)
        self.assertEqual(payload.metadata["display_decision_rationale_count"], 3)
        self.assertEqual(payload.metadata["display_recommended_next_actions_count"], 3)

    def test_terminal_payload_rejects_unsupported_empty_section_retention_policy(self) -> None:
        with self.assertRaisesRegex(ValueError, "empty-section omission only"):
            HeartbeatTerminalDisplayPolicy(omit_empty_sections=False)


if __name__ == "__main__":
    unittest.main()
