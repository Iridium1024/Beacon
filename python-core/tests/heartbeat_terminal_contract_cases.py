from __future__ import annotations

import asyncio
from collections.abc import Mapping

from agent_os.infrastructure.adapters.protocols import (
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


def build_heartbeat_terminal_contract_case_payloads() -> Mapping[str, Mapping[str, object]]:
    """Build stable serialized export and envelope payloads for cross-runtime contract tests."""

    cases = _build_heartbeat_terminal_contract_case_sources()
    rendered_cases: dict[str, Mapping[str, object]] = {}
    for case_name, source in cases.items():
        export_payload = build_heartbeat_terminal_export(source)
        envelope = build_heartbeat_terminal_protocol_envelope(
            export_payload,
            request_id=f"fixture-{case_name}",
        )
        rendered_cases[case_name] = {
            "export": serialize_heartbeat_terminal_export(export_payload),
            "envelope": {
                "protocol_version": envelope.protocol_version,
                "request_id": envelope.request_id,
                "kind": envelope.kind,
                "payload": dict(envelope.payload),
                "metadata": dict(envelope.metadata),
            },
        }
    return rendered_cases


def _build_heartbeat_terminal_contract_case_sources() -> Mapping[str, object]:
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
    no_eligible_candidate = no_eligible_state.get_current_candidate()
    object.__setattr__(no_eligible_candidate, "candidate_id", "candidate-no-eligible")
    no_eligible_state.shared_context.current_final_answer_candidate_id = "candidate-no-eligible"
    no_eligible_state.shared_context.values["current_final_answer_candidate_id"] = (
        "candidate-no-eligible"
    )
    no_eligible_state.shared_context.values["frozen_final_answer_candidate_id"] = (
        "candidate-no-eligible"
    )
    object.__setattr__(no_eligible_checkpoint, "checkpoint_id", "checkpoint-no-eligible")
    object.__setattr__(no_eligible_checkpoint, "frozen_candidate_id", "candidate-no-eligible")
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
    return {
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
            candidate_snapshot=build_candidate_snapshot(summary="clean converged candidate"),
        ),
        "no_eligible_participants": no_eligible_aggregate,
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
        "blocker_driven_continue": build_attached_result(
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
    }
