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
    HeartbeatVoteChoice,
    RejectionDeficiencyCategory,
)
from agent_os.orchestrator.heartbeat_convergence_profile import (
    HeartbeatConvergenceDominantReason,
    HeartbeatConvergenceFollowupBias,
    HeartbeatConvergenceProfile,
    HeartbeatConvergenceReservationLevel,
    HeartbeatConvergenceSemanticState,
    assert_matching_heartbeat_convergence_profiles,
    build_heartbeat_convergence_profile,
)
from agent_os.orchestrator.heartbeat_report_adapter import build_heartbeat_report_payload


def build_item(
    *,
    category: RejectionDeficiencyCategory,
    severity: str | None = None,
    blocker: bool = False,
    role: str = "reviewer",
    judgment_id: str = "judgment-1",
    priority_rank: int = 1,
    used_signal_keys: tuple[str, ...] = (),
) -> HeartbeatDissentItem:
    return HeartbeatDissentItem(
        category=category,
        severity=severity,
        blocker=blocker,
        supporting_roles=(role,),
        dissenting_roles=("planner",) if role != "planner" else ("reviewer",),
        judgment_ids=(judgment_id,),
        priority_rank=priority_rank,
        used_signal_keys=used_signal_keys,
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
    convergence_profile: HeartbeatConvergenceProfile | None = None,
    metadata: dict[str, object] | None = None,
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
        convergence_profile=convergence_profile,
        metadata={"judgment_count": 3, **(metadata or {})},
    )


def build_result(
    *,
    artifact: HeartbeatAggregateArtifact,
    recommended_outcome: ConvergenceStatus,
    highest_rejection_severity: str | None = None,
    blocker_count: int = 0,
    blocker_roles: tuple[str, ...] = (),
    convergence_profile: HeartbeatConvergenceProfile | None = None,
) -> HeartbeatAggregateResult:
    return HeartbeatAggregateResult(
        aggregate_result_id=artifact.aggregate_result_id,
        checkpoint_id=artifact.checkpoint_id,
        total_judgments=3,
        approval_count=2 if recommended_outcome == ConvergenceStatus.CONVERGED else 1,
        rejection_count=1 if highest_rejection_severity is not None else 0,
        approval_ratio=2 / 3 if recommended_outcome == ConvergenceStatus.CONVERGED else 1 / 2,
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
        convergence_profile=convergence_profile,
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
    metadata: dict[str, object] | None = None,
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
        explanation_summary="summary",
        followup_bias=followup_bias,
        metadata=metadata or {},
    )


class HeartbeatConvergenceProfileContractTests(unittest.TestCase):
    def test_builder_outputs_valid_blocker_continue_profile(self) -> None:
        blocker_item = build_item(
            category=RejectionDeficiencyCategory.INCOMPLETENESS,
            severity="critical",
            blocker=True,
            role="executor",
            judgment_id="judgment-executor",
            priority_rank=1,
            used_signal_keys=("implementation.has_execution_path",),
        )
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONTINUE,
            highest_rejection_severity="critical",
            blocker_count=1,
            blocker_roles=("executor",),
            consensus_items=(blocker_item,),
            unresolved_items=(blocker_item,),
            minority_items=(build_item(category=RejectionDeficiencyCategory.SUFFICIENT),),
            metadata={"judgment_count": 2},
        )

        profile = build_heartbeat_convergence_profile(artifact)

        self.assertEqual(profile.semantic_state, HeartbeatConvergenceSemanticState.BLOCKED_BY_BLOCKER)
        self.assertEqual(profile.dominant_reason, HeartbeatConvergenceDominantReason.BLOCKER_PRESENT)
        self.assertTrue(profile.has_blocker)
        self.assertEqual(profile.reservation_level, HeartbeatConvergenceReservationLevel.BLOCKING)
        self.assertEqual(profile.followup_bias, HeartbeatConvergenceFollowupBias.RESOLVE_BLOCKERS)

    def test_builder_outputs_insufficient_support_without_blocker_semantics(self) -> None:
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONTINUE,
            metadata={"judgment_count": 0, "retained_item_count": 0, "retained_high_priority_count": 0},
        )

        profile = build_heartbeat_convergence_profile(artifact)

        self.assertEqual(
            profile.semantic_state,
            HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_INSUFFICIENT_SUPPORT,
        )
        self.assertEqual(
            profile.dominant_reason,
            HeartbeatConvergenceDominantReason.INSUFFICIENT_APPROVAL_SUPPORT,
        )
        self.assertFalse(profile.has_blocker)
        self.assertEqual(profile.reservation_level, HeartbeatConvergenceReservationLevel.NONE)
        self.assertEqual(profile.followup_bias, HeartbeatConvergenceFollowupBias.COLLECT_FRESH_JUDGMENTS)

    def test_blocker_continue_with_non_blocker_reason_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_profile(
                final_decision=ConvergenceStatus.CONTINUE,
                semantic_state=HeartbeatConvergenceSemanticState.BLOCKED_BY_BLOCKER,
                dominant_reason=HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP,
                has_blocker=True,
                highest_rejection_severity="critical",
                unresolved_high_priority_count=1,
                reservation_level=HeartbeatConvergenceReservationLevel.BLOCKING,
                followup_bias=HeartbeatConvergenceFollowupBias.RESOLVE_BLOCKERS,
            )

    def test_converged_clean_with_retained_high_priority_item_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_profile(
                final_decision=ConvergenceStatus.CONVERGED,
                semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_CLEAN,
                dominant_reason=HeartbeatConvergenceDominantReason.NO_MATERIAL_RESERVATIONS,
                highest_rejection_severity="major",
                unresolved_high_priority_count=1,
                reservation_level=HeartbeatConvergenceReservationLevel.NONE,
                followup_bias=HeartbeatConvergenceFollowupBias.PREPARE_TERMINAL_OUTPUT,
            )

    def test_converged_with_recorded_dissent_and_blocker_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_profile(
                final_decision=ConvergenceStatus.CONVERGED,
                semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_WITH_RECORDED_DISSENT,
                dominant_reason=HeartbeatConvergenceDominantReason.MINORITY_DISSENT_RETAINED,
                has_blocker=True,
                highest_rejection_severity="major",
                unresolved_high_priority_count=1,
                reservation_level=HeartbeatConvergenceReservationLevel.RECORDED,
                followup_bias=HeartbeatConvergenceFollowupBias.CARRY_FORWARD_RESERVATIONS,
                metadata={"retained_item_count": 1, "retained_high_priority_count": 1},
            )

    def test_continue_due_to_insufficient_support_rejects_blocker_and_critical_gap_semantics(self) -> None:
        with self.assertRaises(ValueError):
            build_profile(
                final_decision=ConvergenceStatus.CONTINUE,
                semantic_state=HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_INSUFFICIENT_SUPPORT,
                dominant_reason=HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP,
                highest_rejection_severity="major",
                reservation_level=HeartbeatConvergenceReservationLevel.NONE,
                followup_bias=HeartbeatConvergenceFollowupBias.COLLECT_FRESH_JUDGMENTS,
            )

    def test_converged_with_reservations_requires_actual_reservations(self) -> None:
        with self.assertRaises(ValueError):
            build_profile(
                final_decision=ConvergenceStatus.CONVERGED,
                semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS,
                dominant_reason=HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP,
                highest_rejection_severity="major",
                reservation_level=HeartbeatConvergenceReservationLevel.ELEVATED,
                followup_bias=HeartbeatConvergenceFollowupBias.CARRY_FORWARD_RESERVATIONS,
            )

    def test_matching_profile_helper_rejects_partial_presence(self) -> None:
        profile = build_profile(
            final_decision=ConvergenceStatus.CONTINUE,
            semantic_state=HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_INSUFFICIENT_SUPPORT,
            dominant_reason=HeartbeatConvergenceDominantReason.INSUFFICIENT_APPROVAL_SUPPORT,
            reservation_level=HeartbeatConvergenceReservationLevel.NONE,
            followup_bias=HeartbeatConvergenceFollowupBias.COLLECT_FRESH_JUDGMENTS,
        )

        with self.assertRaises(ValueError):
            assert_matching_heartbeat_convergence_profiles(
                profile,
                None,
                require_all_or_none=True,
            )

    def test_builder_only_exposes_canonical_severity(self) -> None:
        retained_item = build_item(
            category=RejectionDeficiencyCategory.EVIDENCE_GAP,
            severity="high",
            blocker=False,
            used_signal_keys=("evidence.has_evidence_gap",),
        )
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
            highest_rejection_severity="high",
            consensus_items=(build_item(category=RejectionDeficiencyCategory.SUFFICIENT),),
            minority_items=(retained_item,),
            metadata={"retained_item_count": 1, "retained_high_priority_count": 1},
        )

        profile = build_heartbeat_convergence_profile(artifact)

        self.assertEqual(profile.highest_rejection_severity, "major")
        self.assertEqual(
            profile.semantic_state,
            HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS,
        )

    def test_aggregate_artifact_rejects_profile_count_mismatch(self) -> None:
        retained_item = build_item(
            category=RejectionDeficiencyCategory.EVIDENCE_GAP,
            severity="moderate",
            used_signal_keys=("evidence.has_evidence_gap",),
        )
        profile = build_profile(
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS,
            dominant_reason=HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP,
            highest_rejection_severity="major",
            minority_high_priority_count=1,
            reservation_level=HeartbeatConvergenceReservationLevel.ELEVATED,
            followup_bias=HeartbeatConvergenceFollowupBias.CARRY_FORWARD_RESERVATIONS,
            metadata={"retained_item_count": 1, "retained_high_priority_count": 1},
        )

        with self.assertRaises(ValueError):
            build_artifact(
                final_decision=ConvergenceStatus.CONVERGED,
                highest_rejection_severity="major",
                consensus_items=(build_item(category=RejectionDeficiencyCategory.SUFFICIENT),),
                minority_items=(retained_item,),
                convergence_profile=profile,
                metadata={"retained_item_count": 1, "retained_high_priority_count": 1},
            )

    def test_aggregate_result_rejects_profile_presence_mismatch(self) -> None:
        profile = build_profile(
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_CLEAN,
            dominant_reason=HeartbeatConvergenceDominantReason.NO_MATERIAL_RESERVATIONS,
            reservation_level=HeartbeatConvergenceReservationLevel.NONE,
            followup_bias=HeartbeatConvergenceFollowupBias.PREPARE_TERMINAL_OUTPUT,
        )
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
        )

        with self.assertRaises(ValueError):
            build_result(
                artifact=artifact,
                recommended_outcome=ConvergenceStatus.CONVERGED,
                convergence_profile=profile,
            )

    def test_report_adapter_rejects_inconsistent_profile_projection(self) -> None:
        profile_a = build_profile(
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_CLEAN,
            dominant_reason=HeartbeatConvergenceDominantReason.NO_MATERIAL_RESERVATIONS,
            reservation_level=HeartbeatConvergenceReservationLevel.NONE,
            followup_bias=HeartbeatConvergenceFollowupBias.PREPARE_TERMINAL_OUTPUT,
        )
        retained_item = build_item(
            category=RejectionDeficiencyCategory.CLARITY_GAP,
            severity="moderate",
        )
        artifact = build_artifact(
            final_decision=ConvergenceStatus.CONVERGED,
            consensus_items=(build_item(category=RejectionDeficiencyCategory.SUFFICIENT),),
            minority_items=(retained_item,),
            convergence_profile=profile_a,
            metadata={"retained_item_count": 1, "retained_high_priority_count": 0},
        )
        result = build_result(
            artifact=artifact,
            recommended_outcome=ConvergenceStatus.CONVERGED,
            convergence_profile=profile_a,
        )
        profile_b = build_profile(
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_WITH_RECORDED_DISSENT,
            dominant_reason=HeartbeatConvergenceDominantReason.MINORITY_DISSENT_RETAINED,
            reservation_level=HeartbeatConvergenceReservationLevel.RECORDED,
            followup_bias=HeartbeatConvergenceFollowupBias.CARRY_FORWARD_RESERVATIONS,
            metadata={"retained_item_count": 1, "retained_high_priority_count": 0},
        )
        object.__setattr__(result, "convergence_profile", profile_b)

        with self.assertRaises(ValueError):
            build_heartbeat_report_payload(result)


if __name__ == "__main__":
    unittest.main()
