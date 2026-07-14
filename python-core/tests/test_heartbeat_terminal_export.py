from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.orchestrator.convergence import (
    ConvergenceStatus,
    HeartbeatCheckpointInput,
    ParticipantStatus,
    RejectionDeficiencyCategory,
)
from agent_os.orchestrator.heartbeat_report_adapter import build_heartbeat_report_payload
from agent_os.orchestrator.heartbeat_terminal_export import (
    HeartbeatTerminalExportPayload,
    build_heartbeat_terminal_export,
)
from agent_os.orchestrator.heartbeat_terminal_payload import HeartbeatTerminalPayload
from agent_os.orchestrator.runtime_state import ExecutionState
from agent_os.orchestrator.scheduler import Scheduler
from test_checkpoint_phase_flow import StubAgent
from test_heartbeat_terminal_payload import (
    build_attached_result,
    build_candidate_snapshot,
    build_item,
    build_profile,
)
from agent_os.orchestrator.heartbeat_convergence_profile import (
    HeartbeatConvergenceDominantReason,
    HeartbeatConvergenceFollowupBias,
    HeartbeatConvergenceReservationLevel,
    HeartbeatConvergenceSemanticState,
)


class HeartbeatTerminalExportTests(unittest.TestCase):
    def test_export_payload_matches_terminal_payload_fields_and_display_metadata(self) -> None:
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
        payload = result.terminal_payload
        self.assertIsNotNone(payload)

        export_payload = build_heartbeat_terminal_export(result)

        self.assertIsInstance(export_payload, HeartbeatTerminalExportPayload)
        self.assertEqual(export_payload.schema_id, "heartbeat_terminal_export_v1")
        self.assertEqual(export_payload.final_decision, payload.final_decision.value)
        self.assertEqual(
            export_payload.consumer_readiness,
            payload.consumer_readiness.value,
        )
        self.assertEqual(export_payload.reservation_summary, payload.reservation_summary)
        self.assertEqual(export_payload.decision_rationale, payload.decision_rationale)
        self.assertEqual(
            export_payload.recommended_next_actions,
            payload.recommended_next_actions,
        )
        self.assertEqual(export_payload.display_metadata, payload.metadata)
        self.assertEqual(
            tuple(item.category for item in export_payload.top_retained_items),
            tuple(item.category.value for item in payload.top_retained_items),
        )
        self.assertEqual(
            tuple(section.kind for section in export_payload.display_sections),
            tuple(section.kind.value for section in payload.display_sections),
        )
        self.assertEqual(
            tuple(section.lines for section in export_payload.display_sections),
            tuple(section.lines for section in payload.display_sections),
        )
        self.assertEqual(export_payload.candidate.candidate_id, payload.candidate.candidate_id)
        self.assertEqual(export_payload.candidate.checkpoint_id, payload.candidate.checkpoint_id)
        self.assertEqual(export_payload.candidate.summary, payload.candidate.summary)
        self.assertEqual(
            export_payload.candidate.supporting_context_refs,
            payload.candidate.supporting_context_refs,
        )
        self.assertEqual(
            export_payload.candidate.final_decision,
            payload.candidate.final_decision.value,
        )
        self.assertEqual(
            export_payload.candidate.consumer_readiness,
            payload.candidate.consumer_readiness.value,
        )

    def test_outbound_seam_uses_attached_terminal_payload_without_recomputing(self) -> None:
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
            candidate_snapshot=build_candidate_snapshot(summary="clean candidate"),
        )

        export_from_result = build_heartbeat_terminal_export(result)
        export_from_artifact = build_heartbeat_terminal_export(result.aggregate_artifact)
        export_from_payload = build_heartbeat_terminal_export(result.terminal_payload)
        report_payload = build_heartbeat_report_payload(result)

        self.assertEqual(export_from_result, export_from_payload)
        self.assertEqual(export_from_result, export_from_artifact)
        self.assertEqual(report_payload.terminal_payload, export_from_result)
        self.assertEqual(report_payload.candidate_presentation, export_from_result.candidate)
        self.assertIs(report_payload.terminal_payload.candidate, report_payload.candidate_presentation)

    def test_equal_but_distinct_attached_terminal_payload_fails_explicitly(self) -> None:
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
        payload = result.terminal_payload
        self.assertIsNotNone(payload)
        cloned_payload = HeartbeatTerminalPayload(
            final_decision=payload.final_decision,
            consumer_readiness=payload.consumer_readiness,
            candidate=payload.candidate,
            decision_rationale=payload.decision_rationale,
            recommended_next_actions=payload.recommended_next_actions,
            top_retained_items=payload.top_retained_items,
            reservation_summary=payload.reservation_summary,
            display_sections=payload.display_sections,
            metadata=dict(payload.metadata),
        )
        object.__setattr__(result, "terminal_payload", cloned_payload)

        with self.assertRaisesRegex(ValueError, "same object instance"):
            build_heartbeat_terminal_export(result)

    def test_export_builds_for_continue_path(self) -> None:
        profile = build_profile(
            final_decision=ConvergenceStatus.CONTINUE,
            semantic_state=HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_UNRESOLVED_GAP,
            dominant_reason=HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP,
            reservation_level=HeartbeatConvergenceReservationLevel.ELEVATED,
            followup_bias=HeartbeatConvergenceFollowupBias.CLOSE_UNRESOLVED_GAPS,
            highest_rejection_severity="major",
            unresolved_high_priority_count=1,
            retained_item_count=1,
            retained_high_priority_count=1,
        )
        result = build_attached_result(
            final_decision=ConvergenceStatus.CONTINUE,
            profile=profile,
            highest_rejection_severity="major",
            unresolved_items=(
                build_item(
                    category=RejectionDeficiencyCategory.INCOMPLETENESS,
                    severity="major",
                    priority_rank=1,
                ),
            ),
        )

        export_payload = build_heartbeat_terminal_export(result)

        self.assertEqual(export_payload.final_decision, "continue")
        self.assertEqual(export_payload.consumer_readiness, "continue_only")

    def test_export_builds_for_converged_path(self) -> None:
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

        export_payload = build_heartbeat_terminal_export(result)

        self.assertEqual(export_payload.final_decision, "converged")
        self.assertEqual(export_payload.consumer_readiness, "terminal_ready")
        self.assertEqual(
            tuple(section.kind for section in export_payload.display_sections),
            ("candidate", "decision_rationale", "recommended_next_actions"),
        )

    def test_export_builds_for_converged_with_reservations_path(self) -> None:
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
            minority_items=(
                build_item(
                    category=RejectionDeficiencyCategory.CORRECTNESS_RISK,
                    severity="major",
                    priority_rank=1,
                ),
            ),
        )

        export_payload = build_heartbeat_terminal_export(result)

        self.assertEqual(export_payload.final_decision, "converged")
        self.assertEqual(
            export_payload.consumer_readiness,
            "terminal_ready_with_reservations",
        )
        self.assertIsNotNone(export_payload.reservation_summary)

    def test_export_builds_for_blocker_driven_continue_path(self) -> None:
        blocker_item = build_item(
            category=RejectionDeficiencyCategory.INCOMPLETENESS,
            severity="critical",
            blocker=True,
            priority_rank=1,
            role="executor",
        )
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
        result = build_attached_result(
            final_decision=ConvergenceStatus.CONTINUE,
            profile=profile,
            highest_rejection_severity="critical",
            blocker_count=1,
            unresolved_items=(blocker_item,),
        )

        export_payload = build_heartbeat_terminal_export(result)

        self.assertEqual(export_payload.final_decision, "continue")
        self.assertEqual(export_payload.consumer_readiness, "remediation_required")

    def test_export_builds_for_forced_non_terminal_continue_path(self) -> None:
        scheduler = Scheduler(agents={})
        checkpoint_input = HeartbeatCheckpointInput(
            checkpoint_id="checkpoint-1",
            workflow_id="wf-1",
            original_goal="test goal",
            frozen_candidate_id="candidate-1",
            frozen_candidate_summary="candidate summary",
        )
        aggregate = scheduler.aggregate_heartbeat_judgments(
            checkpoint_input,
            (),
            evidence_bundle=None,
        )

        export_payload = build_heartbeat_terminal_export(aggregate)

        self.assertEqual(export_payload.final_decision, "continue")
        self.assertEqual(export_payload.consumer_readiness, "continue_only")
        self.assertIsNotNone(export_payload.reservation_summary)

    def test_export_builds_for_no_eligible_participants_path(self) -> None:
        planner = StubAgent(
            summary_text="planner draft",
            self_check_payload={
                "decision": "approve",
                "rationale_text": "Current candidate is sufficient.",
            },
        )
        scheduler = Scheduler(agents={"planner": planner})
        state = ExecutionState(
            workflow_id="wf-1",
            goal="test goal",
            participant_agent_ids=("planner",),
        )
        state.publish_candidate_from_discussion(
            summary_text="candidate summary",
            source_agent_id="planner",
        )
        state.set_participant_status("planner", ParticipantStatus.SLEEPING)
        state.enter_heartbeat_checkpoint()
        checkpoint_input = state.create_heartbeat_checkpoint_input()

        assessment = asyncio.run(
            scheduler.evaluate_heartbeat_checkpoint(checkpoint_input, state)
        )
        export_payload = build_heartbeat_terminal_export(assessment.aggregate)

        self.assertEqual(export_payload.final_decision, "continue")
        self.assertEqual(export_payload.consumer_readiness, "continue_only")
        self.assertEqual(export_payload.candidate.summary, "candidate summary")


if __name__ == "__main__":
    unittest.main()
