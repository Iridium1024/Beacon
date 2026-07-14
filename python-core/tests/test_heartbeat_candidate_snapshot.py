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
    HeartbeatCheckpointInput,
    RejectionDeficiencyCategory,
)
from agent_os.orchestrator.heartbeat_candidate_snapshot import (
    HeartbeatCandidateSnapshot,
    assert_matching_heartbeat_candidate_snapshots,
    build_heartbeat_candidate_snapshot,
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


def build_checkpoint_input(
    *,
    checkpoint_id: str = "checkpoint-1",
    candidate_id: str = "candidate-1",
    summary: str = "candidate summary",
    source_round: int | None = 1,
    relevant_context_refs: tuple[str, ...] = ("ctx-1", "ctx-1", " ", "ctx-2"),
) -> HeartbeatCheckpointInput:
    return HeartbeatCheckpointInput(
        checkpoint_id=checkpoint_id,
        workflow_id="wf-1",
        original_goal="test goal",
        frozen_candidate_id=candidate_id,
        frozen_candidate_summary=summary,
        source_round=source_round,
        relevant_context_refs=relevant_context_refs,
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
    candidate_snapshot: HeartbeatCandidateSnapshot | None = None,
    convergence_profile: HeartbeatConvergenceProfile | None = None,
    outcome_snapshot: HeartbeatOutcomeSnapshot | None = None,
) -> HeartbeatAggregateArtifact:
    candidate_id = candidate_snapshot.candidate_id if candidate_snapshot is not None else "candidate-1"
    checkpoint_id = (
        candidate_snapshot.checkpoint_id if candidate_snapshot is not None else "checkpoint-1"
    )
    return HeartbeatAggregateArtifact(
        aggregate_result_id="aggregate-1",
        checkpoint_id=checkpoint_id,
        candidate_id=candidate_id,
        final_decision=final_decision,
        candidate_snapshot=candidate_snapshot,
        convergence_profile=convergence_profile,
        outcome_snapshot=outcome_snapshot,
        decision_rationale=("rationale-1",),
        recommended_next_actions=("action-1",),
    )


def build_result(
    *,
    artifact: HeartbeatAggregateArtifact,
    recommended_outcome: ConvergenceStatus,
    candidate_snapshot: HeartbeatCandidateSnapshot | None = None,
    convergence_profile: HeartbeatConvergenceProfile | None = None,
    outcome_snapshot: HeartbeatOutcomeSnapshot | None = None,
) -> HeartbeatAggregateResult:
    return HeartbeatAggregateResult(
        aggregate_result_id=artifact.aggregate_result_id,
        checkpoint_id=artifact.checkpoint_id,
        total_judgments=2,
        approval_count=2 if recommended_outcome == ConvergenceStatus.CONVERGED else 1,
        rejection_count=0,
        approval_ratio=1.0 if recommended_outcome == ConvergenceStatus.CONVERGED else 0.5,
        rejection_ratio=0.0,
        recommended_outcome=recommended_outcome,
        aggregate_artifact=artifact,
        candidate_snapshot=candidate_snapshot,
        convergence_profile=convergence_profile,
        outcome_snapshot=outcome_snapshot,
    )


class HeartbeatCandidateSnapshotTests(unittest.TestCase):
    def test_builds_candidate_snapshot_from_checkpoint_input(self) -> None:
        checkpoint_input = build_checkpoint_input()

        snapshot = build_heartbeat_candidate_snapshot(checkpoint_input)

        self.assertEqual(snapshot.candidate_id, "candidate-1")
        self.assertEqual(snapshot.checkpoint_id, "checkpoint-1")
        self.assertEqual(snapshot.summary, "candidate summary")
        self.assertEqual(snapshot.source_round, 1)
        self.assertEqual(snapshot.supporting_context_refs, ("ctx-1", "ctx-2"))

    def test_candidate_snapshot_rejects_missing_summary(self) -> None:
        with self.assertRaises(ValueError):
            HeartbeatCandidateSnapshot(
                candidate_id="candidate-1",
                checkpoint_id="checkpoint-1",
                summary="   ",
            )

    def test_matching_snapshot_helper_rejects_partial_presence(self) -> None:
        snapshot = build_heartbeat_candidate_snapshot(build_checkpoint_input())

        with self.assertRaises(ValueError):
            assert_matching_heartbeat_candidate_snapshots(
                snapshot,
                None,
                require_all_or_none=True,
            )

    def test_outcome_reuses_candidate_snapshot(self) -> None:
        candidate_snapshot = build_heartbeat_candidate_snapshot(
            build_checkpoint_input(summary="stable candidate")
        )
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

        self.assertIs(outcome.candidate_snapshot, candidate_snapshot)
        self.assertEqual(outcome.candidate_summary, "stable candidate")

    def test_adapter_reuses_one_projected_candidate_snapshot(self) -> None:
        candidate_snapshot = build_heartbeat_candidate_snapshot(
            build_checkpoint_input(summary="adapter candidate")
        )
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
        result = build_result(
            artifact=artifact,
            recommended_outcome=ConvergenceStatus.CONVERGED,
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome,
        )

        payload = build_heartbeat_report_payload(result)

        self.assertIsNotNone(payload.candidate_snapshot)
        self.assertIsNotNone(payload.outcome_snapshot)
        self.assertIs(payload.candidate_snapshot, payload.outcome_snapshot.candidate_snapshot)
        self.assertEqual(payload.candidate_snapshot.summary, "adapter candidate")
        self.assertEqual(payload.outcome_snapshot.candidate_summary, "adapter candidate")

    def test_artifact_rejects_outcome_candidate_snapshot_mismatch(self) -> None:
        profile = build_profile(
            final_decision=ConvergenceStatus.CONVERGED,
            semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_CLEAN,
            dominant_reason=HeartbeatConvergenceDominantReason.NO_MATERIAL_RESERVATIONS,
            reservation_level=HeartbeatConvergenceReservationLevel.NONE,
            followup_bias=HeartbeatConvergenceFollowupBias.PREPARE_TERMINAL_OUTPUT,
        )
        snapshot_a = build_heartbeat_candidate_snapshot(build_checkpoint_input(summary="candidate a"))
        snapshot_b = build_heartbeat_candidate_snapshot(
            build_checkpoint_input(candidate_id="candidate-1", checkpoint_id="checkpoint-1", summary="candidate b")
        )
        outcome = HeartbeatOutcomeSnapshot(
            final_decision=ConvergenceStatus.CONVERGED,
            convergence_profile=profile,
            candidate_snapshot=snapshot_b,
            consumer_readiness=HeartbeatOutcomeConsumerReadiness.TERMINAL_READY,
        )

        with self.assertRaises(ValueError):
            build_artifact(
                final_decision=ConvergenceStatus.CONVERGED,
                candidate_snapshot=snapshot_a,
                convergence_profile=profile,
                outcome_snapshot=outcome,
            )

    def test_result_rejects_candidate_snapshot_presence_mismatch(self) -> None:
        candidate_snapshot = build_heartbeat_candidate_snapshot(build_checkpoint_input())
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

        with self.assertRaises(ValueError):
            build_result(
                artifact=artifact,
                recommended_outcome=ConvergenceStatus.CONVERGED,
                convergence_profile=profile,
            )

    def test_report_adapter_rejects_inconsistent_candidate_snapshot_references(self) -> None:
        candidate_snapshot = build_heartbeat_candidate_snapshot(build_checkpoint_input())
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
        result = build_result(
            artifact=artifact,
            recommended_outcome=ConvergenceStatus.CONVERGED,
            candidate_snapshot=candidate_snapshot,
            convergence_profile=profile,
            outcome_snapshot=outcome,
        )
        object.__setattr__(
            result,
            "candidate_snapshot",
            HeartbeatCandidateSnapshot(
                candidate_id="candidate-1",
                checkpoint_id="checkpoint-1",
                summary="mutated candidate",
            ),
        )

        with self.assertRaises(ValueError):
            build_heartbeat_report_payload(result)


if __name__ == "__main__":
    unittest.main()
