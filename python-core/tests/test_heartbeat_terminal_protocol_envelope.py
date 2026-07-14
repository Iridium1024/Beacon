from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.domain.ports.protocol import ProtocolEnvelope
from agent_os.infrastructure.adapters.protocols import (
    HEARTBEAT_TERMINAL_PROTOCOL_KIND,
    HEARTBEAT_TERMINAL_PROTOCOL_VERSION,
    build_heartbeat_terminal_protocol_envelope,
)
from agent_os.orchestrator.convergence import (
    ConvergenceStatus,
    HeartbeatCheckpointInput,
    ParticipantStatus,
    RejectionDeficiencyCategory,
)
from agent_os.orchestrator.heartbeat_terminal_export import (
    build_heartbeat_terminal_export,
    serialize_heartbeat_terminal_export,
)
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


class HeartbeatTerminalProtocolEnvelopeTests(unittest.TestCase):
    def test_boundary_protocol_builder_requires_terminal_export_payload(self) -> None:
        result = build_attached_result(
            final_decision=ConvergenceStatus.CONVERGED,
            profile=build_profile(
                final_decision=ConvergenceStatus.CONVERGED,
                semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_CLEAN,
                dominant_reason=HeartbeatConvergenceDominantReason.NO_MATERIAL_RESERVATIONS,
                reservation_level=HeartbeatConvergenceReservationLevel.NONE,
                followup_bias=HeartbeatConvergenceFollowupBias.PREPARE_TERMINAL_OUTPUT,
            ),
        )

        with self.assertRaisesRegex(TypeError, "HeartbeatTerminalExportPayload"):
            build_heartbeat_terminal_protocol_envelope(
                result,
                request_id="req-1",
            )
        with self.assertRaisesRegex(TypeError, "HeartbeatTerminalExportPayload"):
            build_heartbeat_terminal_protocol_envelope(
                result.aggregate_artifact,
                request_id="req-1",
            )
        with self.assertRaisesRegex(TypeError, "HeartbeatTerminalExportPayload"):
            build_heartbeat_terminal_protocol_envelope(
                result.terminal_payload,
                request_id="req-1",
            )

        export_payload = build_heartbeat_terminal_export(result)
        envelope = build_heartbeat_terminal_protocol_envelope(
            export_payload,
            request_id="req-1",
        )

        self.assertIsInstance(envelope, ProtocolEnvelope)
        self.assertEqual(envelope.kind, HEARTBEAT_TERMINAL_PROTOCOL_KIND)
        self.assertEqual(envelope.protocol_version, HEARTBEAT_TERMINAL_PROTOCOL_VERSION)

    def test_protocol_envelope_transports_export_payload_without_drift(self) -> None:
        retained_items = (
            build_item(
                category=RejectionDeficiencyCategory.CORRECTNESS_RISK,
                severity="major",
                priority_rank=1,
            ),
            build_item(
                category=RejectionDeficiencyCategory.INCOMPLETENESS,
                severity="major",
                priority_rank=2,
            ),
            build_item(
                category=RejectionDeficiencyCategory.EVIDENCE_GAP,
                severity="major",
                priority_rank=3,
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
        export_payload = build_heartbeat_terminal_export(
            build_attached_result(
                final_decision=ConvergenceStatus.CONVERGED,
                profile=profile,
                candidate_snapshot=build_candidate_snapshot(summary="transport candidate"),
                highest_rejection_severity="major",
                minority_items=retained_items,
                decision_rationale=("rationale-1", "rationale-2", "rationale-3", "rationale-4"),
                recommended_next_actions=("action-1", "action-2", "action-3", "action-4"),
            )
        )

        envelope = build_heartbeat_terminal_protocol_envelope(
            export_payload,
            request_id="req-2",
            metadata={"transport": "cli"},
        )

        self.assertEqual(envelope.metadata, {"transport": "cli"})
        self.assertEqual(envelope.payload, serialize_heartbeat_terminal_export(export_payload))
        self.assertEqual(envelope.payload["schema_id"], export_payload.schema_id)
        self.assertEqual(
            envelope.payload["final_decision"],
            export_payload.final_decision,
        )
        self.assertEqual(
            envelope.payload["consumer_readiness"],
            export_payload.consumer_readiness,
        )
        self.assertEqual(
            envelope.payload["candidate"]["summary"],
            export_payload.candidate.summary,
        )
        self.assertEqual(
            envelope.payload["candidate"]["supporting_context_refs"],
            list(export_payload.candidate.supporting_context_refs),
        )
        self.assertEqual(
            [item["category"] for item in envelope.payload["top_retained_items"]],
            [item.category for item in export_payload.top_retained_items],
        )
        self.assertEqual(
            envelope.payload["decision_rationale"],
            list(export_payload.decision_rationale),
        )
        self.assertEqual(
            envelope.payload["recommended_next_actions"],
            list(export_payload.recommended_next_actions),
        )
        self.assertEqual(
            [section["kind"] for section in envelope.payload["display_sections"]],
            [section.kind for section in export_payload.display_sections],
        )
        self.assertEqual(
            envelope.payload["display_metadata"]["display_section_order"],
            list(export_payload.display_metadata["display_section_order"]),
        )
        self.assertEqual(
            envelope.payload["display_metadata"]["display_omitted_sections"],
            list(export_payload.display_metadata["display_omitted_sections"]),
        )
        self.assertTrue(envelope.payload["display_metadata"]["display_retained_items_truncated"])
        self.assertTrue(
            envelope.payload["display_metadata"]["display_decision_rationale_truncated"]
        )
        self.assertTrue(
            envelope.payload["display_metadata"][
                "display_recommended_next_actions_truncated"
            ]
        )
        json.dumps(envelope.payload)

    def test_protocol_envelope_fails_explicitly_on_export_metadata_drift(self) -> None:
        export_payload = build_heartbeat_terminal_export(
            build_attached_result(
                final_decision=ConvergenceStatus.CONVERGED,
                profile=build_profile(
                    final_decision=ConvergenceStatus.CONVERGED,
                    semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_CLEAN,
                    dominant_reason=HeartbeatConvergenceDominantReason.NO_MATERIAL_RESERVATIONS,
                    reservation_level=HeartbeatConvergenceReservationLevel.NONE,
                    followup_bias=HeartbeatConvergenceFollowupBias.PREPARE_TERMINAL_OUTPUT,
                ),
            )
        )
        object.__setattr__(
            export_payload,
            "display_metadata",
            {
                **dict(export_payload.display_metadata),
                "display_section_count": 999,
            },
        )

        with self.assertRaisesRegex(ValueError, "display_section_count"):
            build_heartbeat_terminal_protocol_envelope(
                export_payload,
                request_id="req-3",
            )

    def test_protocol_envelope_wraps_all_special_paths_after_single_export_seam(self) -> None:
        blocker_item = build_item(
            category=RejectionDeficiencyCategory.INCOMPLETENESS,
            severity="critical",
            blocker=True,
            priority_rank=1,
            role="executor",
        )
        planner = StubAgent(
            summary_text="planner draft",
            self_check_payload={
                "decision": "approve",
                "rationale_text": "Current candidate is sufficient.",
            },
        )
        scheduler = Scheduler(agents={"planner": planner})
        no_eligible_state = ExecutionState(
            workflow_id="wf-1",
            goal="test goal",
            participant_agent_ids=("planner",),
        )
        no_eligible_state.publish_candidate_from_discussion(
            summary_text="candidate summary",
            source_agent_id="planner",
        )
        no_eligible_state.set_participant_status("planner", ParticipantStatus.SLEEPING)
        no_eligible_state.enter_heartbeat_checkpoint()
        no_eligible_checkpoint = no_eligible_state.create_heartbeat_checkpoint_input()
        no_eligible_aggregate = asyncio.run(
            scheduler.evaluate_heartbeat_checkpoint(
                no_eligible_checkpoint,
                no_eligible_state,
            )
        ).aggregate
        forced_continue_aggregate = Scheduler(agents={}).aggregate_heartbeat_judgments(
            HeartbeatCheckpointInput(
                checkpoint_id="checkpoint-1",
                workflow_id="wf-1",
                original_goal="test goal",
                frozen_candidate_id="candidate-1",
                frozen_candidate_summary="candidate summary",
            ),
            (),
            evidence_bundle=None,
        )
        cases = {
            "continue": build_attached_result(
                final_decision=ConvergenceStatus.CONTINUE,
                profile=build_profile(
                    final_decision=ConvergenceStatus.CONTINUE,
                    semantic_state=HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_UNRESOLVED_GAP,
                    dominant_reason=HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP,
                    reservation_level=HeartbeatConvergenceReservationLevel.ELEVATED,
                    followup_bias=HeartbeatConvergenceFollowupBias.CLOSE_UNRESOLVED_GAPS,
                    highest_rejection_severity="major",
                    unresolved_high_priority_count=1,
                    retained_item_count=1,
                    retained_high_priority_count=1,
                ),
                highest_rejection_severity="major",
                unresolved_items=(
                    build_item(
                        category=RejectionDeficiencyCategory.INCOMPLETENESS,
                        severity="major",
                        priority_rank=1,
                    ),
                ),
            ),
            "converged": build_attached_result(
                final_decision=ConvergenceStatus.CONVERGED,
                profile=build_profile(
                    final_decision=ConvergenceStatus.CONVERGED,
                    semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_CLEAN,
                    dominant_reason=HeartbeatConvergenceDominantReason.NO_MATERIAL_RESERVATIONS,
                    reservation_level=HeartbeatConvergenceReservationLevel.NONE,
                    followup_bias=HeartbeatConvergenceFollowupBias.PREPARE_TERMINAL_OUTPUT,
                ),
            ),
            "converged_with_reservations": build_attached_result(
                final_decision=ConvergenceStatus.CONVERGED,
                profile=build_profile(
                    final_decision=ConvergenceStatus.CONVERGED,
                    semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS,
                    dominant_reason=HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP,
                    reservation_level=HeartbeatConvergenceReservationLevel.ELEVATED,
                    followup_bias=HeartbeatConvergenceFollowupBias.CARRY_FORWARD_RESERVATIONS,
                    highest_rejection_severity="major",
                    minority_high_priority_count=1,
                    retained_item_count=1,
                    retained_high_priority_count=1,
                ),
                highest_rejection_severity="major",
                minority_items=(
                    build_item(
                        category=RejectionDeficiencyCategory.CORRECTNESS_RISK,
                        severity="major",
                        priority_rank=1,
                    ),
                ),
            ),
            "blocker_continue": build_attached_result(
                final_decision=ConvergenceStatus.CONTINUE,
                profile=build_profile(
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
                ),
                highest_rejection_severity="critical",
                blocker_count=1,
                unresolved_items=(blocker_item,),
            ),
            "forced_non_terminal_continue": forced_continue_aggregate,
            "no_eligible_participants": no_eligible_aggregate,
        }

        for name, source in cases.items():
            with self.subTest(path=name):
                export_payload = build_heartbeat_terminal_export(source)
                envelope = build_heartbeat_terminal_protocol_envelope(
                    export_payload,
                    request_id=f"req-{name}",
                )
                self.assertEqual(envelope.payload["schema_id"], "heartbeat_terminal_export_v1")
                self.assertEqual(
                    envelope.payload["display_sections"],
                    serialize_heartbeat_terminal_export(export_payload)["display_sections"],
                )


if __name__ == "__main__":
    unittest.main()
