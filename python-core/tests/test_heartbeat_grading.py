from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

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
from agent_os.orchestrator.heartbeat_convergence_profile import (
    HeartbeatConvergenceSemanticState,
    build_heartbeat_convergence_profile,
)
from agent_os.orchestrator.heartbeat_grading import (
    derive_heartbeat_grading,
    summarize_heartbeat_grading,
)
from agent_os.orchestrator.heartbeat_report_adapter import build_heartbeat_report_payload


def build_checkpoint_input(
    *,
    original_goal: str,
    summary: str = "candidate summary",
    structured_content: dict[str, object] | None = None,
    payload: dict[str, object] | None = None,
) -> HeartbeatCheckpointInput:
    return HeartbeatCheckpointInput(
        checkpoint_id="checkpoint-1",
        workflow_id="wf-1",
        original_goal=original_goal,
        frozen_candidate_id="candidate-1",
        frozen_candidate_summary=summary,
        frozen_candidate_structured_content=structured_content,
        frozen_candidate_payload=payload,
    )


def build_evidence_bundle(
    *,
    coverage_signals: dict[str, object] | None = None,
    constraint_signals: dict[str, object] | None = None,
    implementation_signals: dict[str, object] | None = None,
    risk_signals: dict[str, object] | None = None,
    evidence_signals: dict[str, object] | None = None,
) -> HeartbeatEvidenceBundle:
    return HeartbeatEvidenceBundle.create(
        checkpoint_id="checkpoint-1",
        candidate_id="candidate-1",
        original_goal="test goal",
        candidate_summary="candidate summary",
        coverage_signals=coverage_signals,
        constraint_signals=constraint_signals,
        implementation_signals=implementation_signals,
        risk_signals=risk_signals,
        evidence_signals=evidence_signals,
        evidence_bundle_id="evidence-1",
    )


def build_anchor(signal_key: str, signal_family: str) -> HeartbeatSourceAnchor:
    return HeartbeatSourceAnchor(
        signal_key=signal_key,
        signal_family=signal_family,
        source_fields=("candidate_summary",),
        derived_from_summary=True,
    )


class HeartbeatGradingTests(unittest.TestCase):
    def test_hard_constraint_gap_becomes_critical_blocker(self) -> None:
        checkpoint_input = build_checkpoint_input(
            original_goal="deliver sandboxed multi-agent plan with explicit constraints",
            summary="The plan covers the goal and steps.",
        )
        evidence_bundle = build_evidence_bundle(
            constraint_signals={
                "has_constraints": False,
                "source_fields": ("candidate_summary",),
                "derived_from_summary": True,
            }
        )

        grading = derive_heartbeat_grading(
            decision=HeartbeatVoteChoice.REJECT,
            deficiency_category=RejectionDeficiencyCategory.CONSTRAINT_VIOLATION,
            used_signal_keys=("constraint.has_constraints",),
            source_anchors=(build_anchor("constraint.has_constraints", "constraint"),),
            checkpoint_input=checkpoint_input,
            evidence_bundle=evidence_bundle,
            agent_role="planner",
        )

        self.assertEqual(grading.severity, "critical")
        self.assertTrue(grading.blocker)

    def test_implementation_break_becomes_blocker(self) -> None:
        checkpoint_input = build_checkpoint_input(
            original_goal="apply the implementation path to the workspace",
            summary="Dependencies are unresolved.",
            structured_content={"files": ("scheduler.py",)},
        )
        evidence_bundle = build_evidence_bundle(
            implementation_signals={
                "has_execution_path": False,
                "source_fields": ("candidate_summary", "structured_content"),
                "derived_from_summary": True,
                "derived_from_structured_content": True,
            }
        )

        grading = derive_heartbeat_grading(
            decision=HeartbeatVoteChoice.REJECT,
            deficiency_category=RejectionDeficiencyCategory.INCOMPLETENESS,
            used_signal_keys=("implementation.has_execution_path",),
            source_anchors=(build_anchor("implementation.has_execution_path", "implementation"),),
            checkpoint_input=checkpoint_input,
            evidence_bundle=evidence_bundle,
            agent_role="executor",
        )

        self.assertEqual(grading.severity, "critical")
        self.assertTrue(grading.blocker)

    def test_core_evidence_gap_is_major_but_not_blocking(self) -> None:
        checkpoint_input = build_checkpoint_input(
            original_goal="validate the frozen candidate for correctness and evidence",
            summary="This candidate is unsupported and missing evidence.",
        )
        evidence_bundle = build_evidence_bundle(
            evidence_signals={
                "has_evidence_gap": True,
                "has_validation_signal": False,
                "context_ref_count": 0,
                "source_fields": ("candidate_summary",),
                "derived_from_summary": True,
            }
        )

        grading = derive_heartbeat_grading(
            decision=HeartbeatVoteChoice.REJECT,
            deficiency_category=RejectionDeficiencyCategory.EVIDENCE_GAP,
            used_signal_keys=("evidence.has_evidence_gap",),
            source_anchors=(build_anchor("evidence.has_evidence_gap", "evidence"),),
            checkpoint_input=checkpoint_input,
            evidence_bundle=evidence_bundle,
            agent_role="reviewer",
        )

        self.assertEqual(grading.severity, "major")
        self.assertFalse(grading.blocker)

    def test_clarity_gap_stays_non_blocking(self) -> None:
        checkpoint_input = build_checkpoint_input(
            original_goal="review a short status update",
            summary="The current draft is ambiguous but otherwise aligned.",
            payload={"notes": "ambiguous"},
        )
        evidence_bundle = build_evidence_bundle(
            risk_signals={
                "has_clarity_marker": True,
                "source_fields": ("candidate_summary", "payload"),
                "derived_from_summary": True,
                "derived_from_payload": True,
            }
        )

        grading = derive_heartbeat_grading(
            decision=HeartbeatVoteChoice.REJECT,
            deficiency_category=RejectionDeficiencyCategory.CLARITY_GAP,
            used_signal_keys=("risk.has_clarity_marker",),
            source_anchors=(build_anchor("risk.has_clarity_marker", "risk"),),
            checkpoint_input=checkpoint_input,
            evidence_bundle=evidence_bundle,
            agent_role="reviewer",
        )

        self.assertEqual(grading.severity, "moderate")
        self.assertFalse(grading.blocker)

    def test_grading_summary_canonicalizes_legacy_severity_and_counts_blockers(self) -> None:
        judgments = (
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-reviewer",
                checkpoint_id="checkpoint-1",
                agent_id="reviewer",
                candidate_id="candidate-1",
                evidence_bundle_id="evidence-1",
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Validation evidence is not explicit.",
                deficiency_category=RejectionDeficiencyCategory.EVIDENCE_GAP,
                severity="high",
                blocker=True,
                metadata={"agent_role": "reviewer"},
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-planner",
                checkpoint_id="checkpoint-1",
                agent_id="planner",
                candidate_id="candidate-1",
                evidence_bundle_id="evidence-1",
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Plan closure is not explicit.",
                deficiency_category=RejectionDeficiencyCategory.INCOMPLETENESS,
                severity="moderate",
                blocker=False,
                metadata={"agent_role": "planner"},
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-executor",
                checkpoint_id="checkpoint-1",
                agent_id="executor",
                candidate_id="candidate-1",
                evidence_bundle_id="evidence-1",
                decision=HeartbeatVoteChoice.APPROVE,
                rationale_text="Execution path is grounded.",
            ),
        )

        summary = summarize_heartbeat_grading(judgments)

        self.assertEqual(summary.highest_rejection_severity, "major")
        self.assertEqual(summary.blocker_count, 1)
        self.assertEqual(summary.blocker_roles, ("reviewer",))
        self.assertEqual(summary.severity_histogram, {"major": 1, "moderate": 1})

    def test_judgment_create_rejects_approve_blocker_true(self) -> None:
        with self.assertRaises(ValueError):
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-approve-invalid",
                checkpoint_id="checkpoint-1",
                agent_id="reviewer",
                candidate_id="candidate-1",
                evidence_bundle_id="evidence-1",
                decision=HeartbeatVoteChoice.APPROVE,
                rationale_text="Looks sufficient.",
                blocker=True,
            )

    def test_judgment_create_rejects_blocker_other_category(self) -> None:
        with self.assertRaises(ValueError):
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-reject-invalid",
                checkpoint_id="checkpoint-1",
                agent_id="reviewer",
                candidate_id="candidate-1",
                evidence_bundle_id="evidence-1",
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="This cannot proceed.",
                deficiency_category=RejectionDeficiencyCategory.OTHER,
                severity="major",
                blocker=True,
            )

    def test_judgment_create_rejects_unknown_severity_vocabulary(self) -> None:
        with self.assertRaises(ValueError):
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-reject-invalid-severity",
                checkpoint_id="checkpoint-1",
                agent_id="reviewer",
                candidate_id="candidate-1",
                evidence_bundle_id="evidence-1",
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="This cannot proceed.",
                deficiency_category=RejectionDeficiencyCategory.EVIDENCE_GAP,
                severity="severe",
            )

    def test_report_payload_only_exposes_canonical_severity_vocabulary(self) -> None:
        artifact = HeartbeatAggregateArtifact(
            aggregate_result_id="aggregate-1",
            checkpoint_id="checkpoint-1",
            candidate_id="candidate-1",
            final_decision=ConvergenceStatus.CONTINUE,
            highest_rejection_severity="high",
            blocker_count=1,
            blocker_roles=("reviewer", "reviewer"),
            severity_histogram={"high": 1, "low": 2},
            consensus_items=(
                HeartbeatDissentItem(
                    category=RejectionDeficiencyCategory.EVIDENCE_GAP,
                    severity="high",
                    blocker=True,
                    supporting_roles=("reviewer",),
                    judgment_ids=("judgment-2", "judgment-1"),
                    priority_rank=7,
                ),
                HeartbeatDissentItem(
                    category=RejectionDeficiencyCategory.CLARITY_GAP,
                    severity="low",
                    blocker=False,
                    supporting_roles=("planner",),
                    judgment_ids=("judgment-3",),
                    priority_rank=8,
                ),
            ),
        )

        payload = build_heartbeat_report_payload(artifact)

        self.assertEqual(payload.highest_rejection_severity, "major")
        self.assertEqual(payload.blocker_count, 1)
        self.assertEqual(payload.blocker_roles, ("reviewer",))
        self.assertEqual(payload.severity_histogram, {"major": 1, "minor": 2})
        self.assertEqual(
            {item.category: item.severity for item in payload.consensus_items},
            {
                "evidence_gap": "major",
                "clarity_gap": "minor",
            },
        )
        self.assertEqual(payload.consensus_items[0].priority_rank, 7)
        self.assertEqual(payload.consensus_items[0].judgment_ids, ("judgment-2", "judgment-1"))

    def test_convergence_profile_only_exposes_canonical_severity_vocabulary(self) -> None:
        artifact = HeartbeatAggregateArtifact(
            aggregate_result_id="aggregate-1",
            checkpoint_id="checkpoint-1",
            candidate_id="candidate-1",
            final_decision=ConvergenceStatus.CONVERGED,
            highest_rejection_severity="high",
            blocker_count=0,
            severity_histogram={"high": 1, "low": 1},
            minority_items=(
                HeartbeatDissentItem(
                    category=RejectionDeficiencyCategory.EVIDENCE_GAP,
                    severity="high",
                    blocker=False,
                    supporting_roles=("reviewer",),
                    judgment_ids=("judgment-1",),
                    priority_rank=1,
                    used_signal_keys=("evidence.has_evidence_gap",),
                ),
            ),
            metadata={"judgment_count": 3},
        )

        profile = build_heartbeat_convergence_profile(artifact)

        self.assertEqual(profile.highest_rejection_severity, "major")
        self.assertEqual(
            profile.semantic_state,
            HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS,
        )


if __name__ == "__main__":
    unittest.main()
