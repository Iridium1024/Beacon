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
    candidate_id: str = "candidate-1",
    checkpoint_id: str = "checkpoint-1",
    summary: str = "candidate summary",
    source_round: int | None = 3,
    supporting_context_refs: tuple[str, ...] = ("ctx-1", "ctx-2"),
) -> HeartbeatCandidateSnapshot:
    return HeartbeatCandidateSnapshot(
        candidate_id=candidate_id,
        checkpoint_id=checkpoint_id,
        summary=summary,
        source_round=source_round,
        supporting_context_refs=supporting_context_refs,
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
    candidate_snapshot: HeartbeatCandidateSnapshot | None = None,
    convergence_profile: HeartbeatConvergenceProfile | None = None,
    outcome_snapshot: HeartbeatOutcomeSnapshot | None = None,
    candidate_presentation: HeartbeatCandidatePresentation | None = None,
    consensus_items: tuple[HeartbeatDissentItem, ...] = (),
    minority_items: tuple[HeartbeatDissentItem, ...] = (),
    unresolved_items: tuple[HeartbeatDissentItem, ...] = (),
) -> HeartbeatAggregateArtifact:
    return HeartbeatAggregateArtifact(
        aggregate_result_id="aggregate-1",
        checkpoint_id="checkpoint-1",
        candidate_id="candidate-1",
        final_decision=final_decision,
        highest_rejection_severity=highest_rejection_severity,
        severity_histogram=(
            {highest_rejection_severity: 1}
            if highest_rejection_severity is not None
            else {}
        ),
        candidate_snapshot=candidate_snapshot,
        convergence_profile=convergence_profile,
        outcome_snapshot=outcome_snapshot,
        candidate_presentation=candidate_presentation,
        consensus_items=consensus_items,
        minority_items=minority_items,
        unresolved_items=unresolved_items,
        decision_rationale=("rationale-1", "rationale-2"),
        recommended_next_actions=("action-1", "action-2"),
    )


def build_result(
    *,
    artifact: HeartbeatAggregateArtifact,
    recommended_outcome: ConvergenceStatus,
    highest_rejection_severity: str | None = None,
    candidate_snapshot: HeartbeatCandidateSnapshot | None = None,
    convergence_profile: HeartbeatConvergenceProfile | None = None,
    outcome_snapshot: HeartbeatOutcomeSnapshot | None = None,
    candidate_presentation: HeartbeatCandidatePresentation | None = None,
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
    )


class HeartbeatCandidatePresentationTests(unittest.TestCase):
    def test_builds_candidate_presentation_from_attached_objects(self) -> None:
        retained_item = build_item(
            category=RejectionDeficiencyCategory.EVIDENCE_GAP,
            severity="major",
            priority_rank=1,
            role="reviewer",
        )
        candidate_snapshot = build_candidate_snapshot(summary="stable candidate")
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
        result = build_result(
            artifact=artifact,
            recommended_outcome=ConvergenceStatus.CONVERGED,
            highest_rejection_severity="major",
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome,
        )

        presentation = build_heartbeat_candidate_presentation(result)

        self.assertEqual(presentation.candidate_id, "candidate-1")
        self.assertEqual(presentation.checkpoint_id, "checkpoint-1")
        self.assertEqual(presentation.summary, "stable candidate")
        self.assertEqual(presentation.source_round, 3)
        self.assertEqual(presentation.supporting_context_refs, ("ctx-1", "ctx-2"))
        self.assertEqual(presentation.final_decision, ConvergenceStatus.CONVERGED)
        self.assertEqual(
            presentation.semantic_state,
            HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS,
        )
        self.assertEqual(
            presentation.reservation_level,
            HeartbeatConvergenceReservationLevel.ELEVATED,
        )
        self.assertEqual(
            presentation.consumer_readiness,
            HeartbeatOutcomeConsumerReadiness.TERMINAL_READY_WITH_RESERVATIONS,
        )
        self.assertEqual(presentation.retained_issue_preview, "evidence_gap summary")
        self.assertEqual(presentation.next_step_preview, "action-1")

    def test_converged_clean_presentation_omits_retained_issue_preview(self) -> None:
        candidate_snapshot = build_candidate_snapshot(summary="clean candidate")
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

        presentation = build_heartbeat_candidate_presentation(artifact)

        self.assertEqual(
            presentation.consumer_readiness,
            HeartbeatOutcomeConsumerReadiness.TERMINAL_READY,
        )
        self.assertIsNone(presentation.retained_issue_preview)

    def test_artifact_rejects_candidate_presentation_without_outcome_snapshot(self) -> None:
        candidate_snapshot = build_candidate_snapshot()
        profile = build_profile(
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_CLEAN,
            dominant_reason=HeartbeatConvergenceDominantReason.NO_MATERIAL_RESERVATIONS,
            reservation_level=HeartbeatConvergenceReservationLevel.NONE,
            followup_bias=HeartbeatConvergenceFollowupBias.PREPARE_TERMINAL_OUTPUT,
        )
        candidate_presentation = HeartbeatCandidatePresentation(
            candidate_id="candidate-1",
            checkpoint_id="checkpoint-1",
            summary="candidate summary",
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_CLEAN,
            reservation_level=HeartbeatConvergenceReservationLevel.NONE,
            consumer_readiness=HeartbeatOutcomeConsumerReadiness.TERMINAL_READY,
        )

        with self.assertRaises(ValueError):
            build_artifact(
                final_decision=ConvergenceStatus.CONVERGED,
                candidate_snapshot=candidate_snapshot,
                convergence_profile=profile,
                candidate_presentation=candidate_presentation,
            )

    def test_adapter_projects_attached_candidate_presentation(self) -> None:
        retained_item = build_item(
            category=RejectionDeficiencyCategory.CLARITY_GAP,
            severity="moderate",
            priority_rank=1,
            role="planner",
        )
        candidate_snapshot = build_candidate_snapshot(summary="adapter candidate")
        profile = build_profile(
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_WITH_RECORDED_DISSENT,
            dominant_reason=HeartbeatConvergenceDominantReason.MINORITY_DISSENT_RETAINED,
            reservation_level=HeartbeatConvergenceReservationLevel.RECORDED,
            followup_bias=HeartbeatConvergenceFollowupBias.CARRY_FORWARD_RESERVATIONS,
            highest_rejection_severity="moderate",
            retained_item_count=1,
        )
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
            highest_rejection_severity="moderate",
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            consensus_items=(build_item(category=RejectionDeficiencyCategory.SUFFICIENT),),
            minority_items=(retained_item,),
        )
        outcome = build_heartbeat_outcome_snapshot(artifact)
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
            highest_rejection_severity="moderate",
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome,
            consensus_items=artifact.consensus_items,
            minority_items=artifact.minority_items,
        )
        presentation = build_heartbeat_candidate_presentation(artifact)
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
            highest_rejection_severity="moderate",
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome,
            candidate_presentation=presentation,
            consensus_items=artifact.consensus_items,
            minority_items=artifact.minority_items,
        )
        result = build_result(
            artifact=artifact,
            recommended_outcome=ConvergenceStatus.CONVERGED,
            highest_rejection_severity="moderate",
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome,
            candidate_presentation=presentation,
        )

        payload = build_heartbeat_report_payload(result)

        self.assertIsNotNone(payload.candidate_presentation)
        self.assertEqual(payload.candidate_presentation.summary, "adapter candidate")
        self.assertEqual(payload.candidate_presentation.semantic_state, profile.semantic_state.value)
        self.assertEqual(
            payload.candidate_presentation.consumer_readiness,
            outcome.consumer_readiness.value,
        )

    def test_adapter_rejects_inconsistent_candidate_presentation_references(self) -> None:
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
        presentation = build_heartbeat_candidate_presentation(artifact)
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome,
            candidate_presentation=presentation,
        )
        result = build_result(
            artifact=artifact,
            recommended_outcome=ConvergenceStatus.CONVERGED,
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome,
            candidate_presentation=presentation,
        )
        object.__setattr__(
            result,
            "candidate_presentation",
            HeartbeatCandidatePresentation(
                candidate_id="candidate-1",
                checkpoint_id="checkpoint-1",
                summary="mutated presentation",
                final_decision=ConvergenceStatus.CONVERGED,
                semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_CLEAN,
                reservation_level=HeartbeatConvergenceReservationLevel.NONE,
                consumer_readiness=HeartbeatOutcomeConsumerReadiness.TERMINAL_READY,
            ),
        )

        with self.assertRaises(ValueError):
            build_heartbeat_report_payload(result)


if __name__ == "__main__":
    unittest.main()
