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


def build_profile(
    *,
    final_decision: ConvergenceStatus,
    semantic_state: HeartbeatConvergenceSemanticState,
    dominant_reason: HeartbeatConvergenceDominantReason,
    has_blocker: bool = False,
    highest_rejection_severity: str | None = None,
    unresolved_high_priority_count: int = 0,
    minority_high_priority_count: int = 0,
    reservation_level: HeartbeatConvergenceReservationLevel,
    followup_bias: HeartbeatConvergenceFollowupBias,
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


def build_candidate_snapshot(
    *,
    candidate_id: str = "candidate-1",
    checkpoint_id: str = "checkpoint-1",
    summary: str = "candidate summary",
    supporting_context_refs: tuple[str, ...] = (),
) -> HeartbeatCandidateSnapshot:
    return HeartbeatCandidateSnapshot(
        candidate_id=candidate_id,
        checkpoint_id=checkpoint_id,
        summary=summary,
        supporting_context_refs=supporting_context_refs,
    )


def build_artifact(
    *,
    final_decision: ConvergenceStatus,
    highest_rejection_severity: str | None = None,
    blocker_count: int = 0,
    blocker_roles: tuple[str, ...] = (),
    consensus_items: tuple[HeartbeatDissentItem, ...] = (),
    minority_items: tuple[HeartbeatDissentItem, ...] = (),
    unresolved_items: tuple[HeartbeatDissentItem, ...] = (),
    candidate_snapshot: HeartbeatCandidateSnapshot | None = None,
    convergence_profile: HeartbeatConvergenceProfile | None = None,
    outcome_snapshot: HeartbeatOutcomeSnapshot | None = None,
) -> HeartbeatAggregateArtifact:
    return HeartbeatAggregateArtifact(
        aggregate_result_id="aggregate-1",
        checkpoint_id="checkpoint-1",
        candidate_id="candidate-1",
        final_decision=final_decision,
        highest_rejection_severity=highest_rejection_severity,
        blocker_count=blocker_count,
        blocker_roles=blocker_roles,
        severity_histogram=(
            {highest_rejection_severity: 1}
            if highest_rejection_severity is not None
            else {}
        ),
        consensus_items=consensus_items,
        minority_items=minority_items,
        unresolved_items=unresolved_items,
        decision_rationale=("rationale-1", "rationale-2"),
        recommended_next_actions=("action-1", "action-2"),
        candidate_snapshot=candidate_snapshot,
        convergence_profile=convergence_profile,
        outcome_snapshot=outcome_snapshot,
        metadata={"judgment_count": 3},
    )


def build_result(
    *,
    artifact: HeartbeatAggregateArtifact,
    recommended_outcome: ConvergenceStatus,
    highest_rejection_severity: str | None = None,
    blocker_count: int = 0,
    blocker_roles: tuple[str, ...] = (),
    candidate_snapshot: HeartbeatCandidateSnapshot | None = None,
    convergence_profile: HeartbeatConvergenceProfile | None = None,
    outcome_snapshot: HeartbeatOutcomeSnapshot | None = None,
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
        blocker_roles=blocker_roles,
        severity_histogram=(
            {highest_rejection_severity: 1}
            if highest_rejection_severity is not None
            else {}
        ),
        aggregate_artifact=artifact,
        candidate_snapshot=candidate_snapshot,
        convergence_profile=convergence_profile,
        outcome_snapshot=outcome_snapshot,
    )


class HeartbeatOutcomeSnapshotTests(unittest.TestCase):
    def test_continue_with_blocker_is_remediation_required(self) -> None:
        blocker_item = build_item(
            category=RejectionDeficiencyCategory.INCOMPLETENESS,
            severity="critical",
            blocker=True,
            priority_rank=1,
            role="executor",
            judgment_id="judgment-executor",
        )
        profile = build_profile(
            final_decision=ConvergenceStatus.CONTINUE,
            semantic_state=HeartbeatConvergenceSemanticState.BLOCKED_BY_BLOCKER,
            dominant_reason=HeartbeatConvergenceDominantReason.BLOCKER_PRESENT,
            has_blocker=True,
            highest_rejection_severity="critical",
            unresolved_high_priority_count=1,
            reservation_level=HeartbeatConvergenceReservationLevel.BLOCKING,
            followup_bias=HeartbeatConvergenceFollowupBias.RESOLVE_BLOCKERS,
            retained_item_count=1,
            retained_high_priority_count=1,
        )
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONTINUE,
            highest_rejection_severity="critical",
            blocker_count=1,
            blocker_roles=("executor",),
            consensus_items=(blocker_item,),
            unresolved_items=(blocker_item,),
            candidate_snapshot=build_candidate_snapshot(summary="candidate summary"),
            convergence_profile=profile,
        )

        outcome = build_heartbeat_outcome_snapshot(
            artifact,
        )

        self.assertEqual(outcome.final_decision, ConvergenceStatus.CONTINUE)
        self.assertEqual(
            outcome.consumer_readiness,
            HeartbeatOutcomeConsumerReadiness.REMEDIATION_REQUIRED,
        )
        self.assertEqual(outcome.candidate_id, "candidate-1")
        self.assertEqual(outcome.candidate_summary, "candidate summary")
        self.assertIsNotNone(outcome.reservation_summary)
        self.assertNotEqual(
            outcome.consumer_readiness,
            HeartbeatOutcomeConsumerReadiness.TERMINAL_READY,
        )

    def test_continue_without_blocker_stays_continue_only(self) -> None:
        retained_item = build_item(
            category=RejectionDeficiencyCategory.INCOMPLETENESS,
            severity="major",
            blocker=False,
            priority_rank=1,
            role="executor",
        )
        profile = build_profile(
            final_decision=ConvergenceStatus.CONTINUE,
            semantic_state=HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_UNRESOLVED_GAP,
            dominant_reason=HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP,
            highest_rejection_severity="major",
            unresolved_high_priority_count=1,
            reservation_level=HeartbeatConvergenceReservationLevel.ELEVATED,
            followup_bias=HeartbeatConvergenceFollowupBias.CLOSE_UNRESOLVED_GAPS,
            retained_item_count=1,
            retained_high_priority_count=1,
        )
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONTINUE,
            highest_rejection_severity="major",
            consensus_items=(retained_item,),
            unresolved_items=(retained_item,),
            candidate_snapshot=build_candidate_snapshot(),
            convergence_profile=profile,
        )

        outcome = build_heartbeat_outcome_snapshot(artifact)

        self.assertEqual(
            outcome.consumer_readiness,
            HeartbeatOutcomeConsumerReadiness.CONTINUE_ONLY,
        )
        self.assertFalse(outcome.convergence_profile.has_blocker)
        self.assertEqual(outcome.recommended_next_actions, artifact.recommended_next_actions)
        self.assertIsNotNone(outcome.reservation_summary)

    def test_converged_clean_is_terminal_ready(self) -> None:
        profile = build_profile(
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_CLEAN,
            dominant_reason=HeartbeatConvergenceDominantReason.NO_MATERIAL_RESERVATIONS,
            reservation_level=HeartbeatConvergenceReservationLevel.NONE,
            followup_bias=HeartbeatConvergenceFollowupBias.PREPARE_TERMINAL_OUTPUT,
        )
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
            candidate_snapshot=build_candidate_snapshot(summary="clean candidate"),
            convergence_profile=profile,
        )
        result = build_result(
            artifact=artifact,
            recommended_outcome=ConvergenceStatus.CONVERGED,
            candidate_snapshot=artifact.candidate_snapshot,
            convergence_profile=profile,
        )

        outcome = build_heartbeat_outcome_snapshot(result)

        self.assertEqual(
            outcome.consumer_readiness,
            HeartbeatOutcomeConsumerReadiness.TERMINAL_READY,
        )
        self.assertEqual(outcome.top_retained_items, ())
        self.assertIsNone(outcome.reservation_summary)
        self.assertEqual(outcome.candidate_summary, "clean candidate")

    def test_converged_with_recorded_dissent_is_terminal_ready_with_reservations(self) -> None:
        retained_item = build_item(
            category=RejectionDeficiencyCategory.CLARITY_GAP,
            severity="moderate",
            blocker=False,
            priority_rank=2,
            role="reviewer",
        )
        profile = build_profile(
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_WITH_RECORDED_DISSENT,
            dominant_reason=HeartbeatConvergenceDominantReason.MINORITY_DISSENT_RETAINED,
            highest_rejection_severity="moderate",
            reservation_level=HeartbeatConvergenceReservationLevel.RECORDED,
            followup_bias=HeartbeatConvergenceFollowupBias.CARRY_FORWARD_RESERVATIONS,
            retained_item_count=1,
            retained_high_priority_count=0,
        )
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
            highest_rejection_severity="moderate",
            consensus_items=(build_item(category=RejectionDeficiencyCategory.SUFFICIENT),),
            minority_items=(retained_item,),
            candidate_snapshot=build_candidate_snapshot(),
            convergence_profile=profile,
        )

        outcome = build_heartbeat_outcome_snapshot(artifact)

        self.assertEqual(outcome.final_decision, ConvergenceStatus.CONVERGED)
        self.assertEqual(
            outcome.consumer_readiness,
            HeartbeatOutcomeConsumerReadiness.TERMINAL_READY_WITH_RESERVATIONS,
        )
        self.assertEqual(outcome.top_retained_items[0].category, RejectionDeficiencyCategory.CLARITY_GAP)
        self.assertIsNotNone(outcome.reservation_summary)

    def test_converged_with_reservations_keeps_stable_top_retained_items(self) -> None:
        major_item = build_item(
            category=RejectionDeficiencyCategory.EVIDENCE_GAP,
            severity="high",
            priority_rank=1,
            role="reviewer",
            judgment_id="judgment-reviewer",
        )
        moderate_item = build_item(
            category=RejectionDeficiencyCategory.CLARITY_GAP,
            severity="moderate",
            priority_rank=2,
            role="planner",
            judgment_id="judgment-planner",
        )
        low_item = build_item(
            category=RejectionDeficiencyCategory.OTHER,
            severity="minor",
            priority_rank=3,
            role="executor",
            judgment_id="judgment-executor",
        )
        profile = build_profile(
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS,
            dominant_reason=HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP,
            highest_rejection_severity="high",
            unresolved_high_priority_count=1,
            minority_high_priority_count=1,
            reservation_level=HeartbeatConvergenceReservationLevel.ELEVATED,
            followup_bias=HeartbeatConvergenceFollowupBias.CARRY_FORWARD_RESERVATIONS,
            retained_item_count=3,
            retained_high_priority_count=1,
        )
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
            highest_rejection_severity="high",
            consensus_items=(build_item(category=RejectionDeficiencyCategory.SUFFICIENT),),
            minority_items=(major_item, moderate_item),
            unresolved_items=(major_item, low_item),
            candidate_snapshot=build_candidate_snapshot(),
            convergence_profile=profile,
        )

        outcome = build_heartbeat_outcome_snapshot(artifact)

        self.assertEqual(
            outcome.consumer_readiness,
            HeartbeatOutcomeConsumerReadiness.TERMINAL_READY_WITH_RESERVATIONS,
        )
        self.assertEqual(
            tuple(item.category for item in outcome.top_retained_items),
            (
                RejectionDeficiencyCategory.EVIDENCE_GAP,
                RejectionDeficiencyCategory.OTHER,
                RejectionDeficiencyCategory.CLARITY_GAP,
            ),
        )
        self.assertEqual(outcome.highest_rejection_severity, "major")
        self.assertTrue(outcome.metadata["top_retained_items_truncated"] is False)

    def test_artifact_profile_outcome_mismatch_fails_explicitly(self) -> None:
        profile = build_profile(
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_CLEAN,
            dominant_reason=HeartbeatConvergenceDominantReason.NO_MATERIAL_RESERVATIONS,
            reservation_level=HeartbeatConvergenceReservationLevel.NONE,
            followup_bias=HeartbeatConvergenceFollowupBias.PREPARE_TERMINAL_OUTPUT,
        )
        inconsistent_outcome = HeartbeatOutcomeSnapshot(
            final_decision=ConvergenceStatus.CONVERGED,
            convergence_profile=profile,
            candidate_snapshot=build_candidate_snapshot(),
            consumer_readiness=HeartbeatOutcomeConsumerReadiness.TERMINAL_READY,
        )

        with self.assertRaises(ValueError):
            build_artifact(
                final_decision=ConvergenceStatus.CONVERGED,
                highest_rejection_severity="major",
                minority_items=(
                    build_item(
                        category=RejectionDeficiencyCategory.CORRECTNESS_RISK,
                        severity="major",
                    ),
                ),
                convergence_profile=profile,
                outcome_snapshot=inconsistent_outcome,
            )

    def test_adapter_projects_attached_outcome_without_recomputing(self) -> None:
        retained_item = build_item(
            category=RejectionDeficiencyCategory.CORRECTNESS_RISK,
            severity="major",
            priority_rank=1,
        )
        profile = build_profile(
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS,
            dominant_reason=HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP,
            highest_rejection_severity="major",
            minority_high_priority_count=1,
            reservation_level=HeartbeatConvergenceReservationLevel.ELEVATED,
            followup_bias=HeartbeatConvergenceFollowupBias.CARRY_FORWARD_RESERVATIONS,
            retained_item_count=1,
            retained_high_priority_count=1,
        )
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
            highest_rejection_severity="major",
            consensus_items=(build_item(category=RejectionDeficiencyCategory.SUFFICIENT),),
            minority_items=(retained_item,),
            candidate_snapshot=build_candidate_snapshot(summary="retained caution candidate"),
            convergence_profile=profile,
        )
        outcome = build_heartbeat_outcome_snapshot(
            artifact,
        )
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
            highest_rejection_severity="major",
            consensus_items=(build_item(category=RejectionDeficiencyCategory.SUFFICIENT),),
            minority_items=(retained_item,),
            candidate_snapshot=artifact.candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome,
        )
        result = build_result(
            artifact=artifact,
            recommended_outcome=ConvergenceStatus.CONVERGED,
            highest_rejection_severity="major",
            candidate_snapshot=artifact.candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome,
        )

        payload = build_heartbeat_report_payload(result)

        self.assertIsNotNone(payload.outcome_snapshot)
        self.assertEqual(payload.outcome_snapshot.final_decision, "converged")
        self.assertEqual(
            payload.outcome_snapshot.consumer_readiness,
            outcome.consumer_readiness.value,
        )
        self.assertEqual(
            payload.outcome_snapshot.candidate_summary,
            "retained caution candidate",
        )
        self.assertEqual(
            tuple(item.category for item in payload.outcome_snapshot.top_retained_items),
            ("correctness_risk",),
        )

    def test_adapter_rejects_inconsistent_outcome_references(self) -> None:
        profile = build_profile(
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_CLEAN,
            dominant_reason=HeartbeatConvergenceDominantReason.NO_MATERIAL_RESERVATIONS,
            reservation_level=HeartbeatConvergenceReservationLevel.NONE,
            followup_bias=HeartbeatConvergenceFollowupBias.PREPARE_TERMINAL_OUTPUT,
        )
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
            candidate_snapshot=build_candidate_snapshot(summary="candidate a"),
            convergence_profile=profile,
        )
        outcome_a = build_heartbeat_outcome_snapshot(artifact)
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
            candidate_snapshot=artifact.candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome_a,
        )
        result = build_result(
            artifact=artifact,
            recommended_outcome=ConvergenceStatus.CONVERGED,
            candidate_snapshot=artifact.candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome_a,
        )
        outcome_b = HeartbeatOutcomeSnapshot(
            final_decision=ConvergenceStatus.CONVERGED,
            convergence_profile=profile,
            candidate_snapshot=build_candidate_snapshot(summary="candidate b"),
            consumer_readiness=HeartbeatOutcomeConsumerReadiness.TERMINAL_READY,
        )
        object.__setattr__(result, "outcome_snapshot", outcome_b)

        with self.assertRaises(ValueError):
            build_heartbeat_report_payload(result)


if __name__ == "__main__":
    unittest.main()
