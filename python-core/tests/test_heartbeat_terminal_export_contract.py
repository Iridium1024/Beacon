from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.domain.ports.protocol import ProtocolEnvelope
from agent_os.protocols import (
    HEARTBEAT_TERMINAL_ENVELOPE_BODY_ATTRIBUTE,
    HEARTBEAT_TERMINAL_EXPORT_REQUIRED_FIELDS,
    HEARTBEAT_TERMINAL_EXPORT_SCHEMA_ID,
    HEARTBEAT_TERMINAL_PROTOCOL_KIND,
    HEARTBEAT_TERMINAL_PROTOCOL_VERSION,
    assert_heartbeat_terminal_export_body_contract,
    assert_heartbeat_terminal_protocol_envelope_contract,
    extract_heartbeat_terminal_export_body,
)
from agent_os.infrastructure.adapters.protocols import (
    build_heartbeat_terminal_protocol_envelope,
)
from agent_os.orchestrator.convergence import ConvergenceStatus, RejectionDeficiencyCategory
from agent_os.orchestrator.heartbeat_terminal_export import build_heartbeat_terminal_export
from heartbeat_terminal_contract_cases import (
    build_heartbeat_terminal_contract_case_payloads,
)
from test_heartbeat_terminal_payload import (
    build_attached_result,
    build_item,
    build_profile,
)
from agent_os.orchestrator.heartbeat_convergence_profile import (
    HeartbeatConvergenceDominantReason,
    HeartbeatConvergenceFollowupBias,
    HeartbeatConvergenceReservationLevel,
    HeartbeatConvergenceSemanticState,
)


FIXTURE_DIR = Path(__file__).resolve().parent / "golden" / "heartbeat_terminal_contract"


class HeartbeatTerminalExportContractTests(unittest.TestCase):
    def test_contract_rejects_missing_required_fields(self) -> None:
        payload = build_heartbeat_terminal_contract_case_payloads()["converged"]["export"]
        for field_name in HEARTBEAT_TERMINAL_EXPORT_REQUIRED_FIELDS:
            with self.subTest(field=field_name):
                invalid_payload = dict(payload)
                invalid_payload.pop(field_name)
                with self.assertRaisesRegex(ValueError, field_name):
                    assert_heartbeat_terminal_export_body_contract(invalid_payload)

    def test_contract_rejects_missing_or_incompatible_schema_id(self) -> None:
        payload = build_heartbeat_terminal_contract_case_payloads()["continue"]["export"]
        invalid_payload = dict(payload)
        invalid_payload["schema_id"] = ""
        with self.assertRaisesRegex(ValueError, "schema_id"):
            assert_heartbeat_terminal_export_body_contract(invalid_payload)

        incompatible_payload = dict(payload)
        incompatible_payload["schema_id"] = "heartbeat_terminal_export_v2"
        with self.assertRaisesRegex(ValueError, "schema_id"):
            assert_heartbeat_terminal_export_body_contract(incompatible_payload)

    def test_contract_enforces_omission_and_truncation_semantics(self) -> None:
        converged_payload = build_heartbeat_terminal_contract_case_payloads()["converged"]["export"]
        assert_heartbeat_terminal_export_body_contract(converged_payload)
        invalid_omission_payload = dict(converged_payload)
        invalid_metadata = dict(converged_payload["display_metadata"])
        invalid_metadata["display_omitted_sections"] = ["candidate"]
        invalid_omission_payload["display_metadata"] = invalid_metadata
        with self.assertRaisesRegex(ValueError, "must not omit candidate"):
            assert_heartbeat_terminal_export_body_contract(invalid_omission_payload)

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
        truncated_payload = build_heartbeat_terminal_export(
            build_attached_result(
                final_decision=ConvergenceStatus.CONVERGED,
                profile=build_profile(
                    final_decision=ConvergenceStatus.CONVERGED,
                    semantic_state=HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS,
                    dominant_reason=HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP,
                    reservation_level=HeartbeatConvergenceReservationLevel.ELEVATED,
                    followup_bias=HeartbeatConvergenceFollowupBias.CARRY_FORWARD_RESERVATIONS,
                    highest_rejection_severity="major",
                    minority_high_priority_count=3,
                    retained_item_count=3,
                    retained_high_priority_count=3,
                ),
                highest_rejection_severity="major",
                minority_items=retained_items,
                decision_rationale=("rationale-1", "rationale-2", "rationale-3", "rationale-4"),
                recommended_next_actions=("action-1", "action-2", "action-3", "action-4"),
            )
        )
        serialized_payload = build_heartbeat_terminal_protocol_envelope(
            truncated_payload,
            request_id="contract-truncation",
        ).payload
        assert_heartbeat_terminal_export_body_contract(serialized_payload)
        invalid_truncation_payload = dict(serialized_payload)
        invalid_truncation_metadata = dict(serialized_payload["display_metadata"])
        invalid_truncation_metadata["display_decision_rationale_truncated"] = False
        invalid_truncation_payload["display_metadata"] = invalid_truncation_metadata
        with self.assertRaisesRegex(ValueError, "display_decision_rationale_truncated"):
            assert_heartbeat_terminal_export_body_contract(invalid_truncation_payload)

    def test_contract_exposes_stable_envelope_body_location(self) -> None:
        rendered_case = build_heartbeat_terminal_contract_case_payloads()["blocker_driven_continue"]
        envelope_payload = rendered_case["envelope"]
        envelope = ProtocolEnvelope(
            protocol_version=envelope_payload["protocol_version"],
            request_id=envelope_payload["request_id"],
            kind=envelope_payload["kind"],
            payload=envelope_payload[HEARTBEAT_TERMINAL_ENVELOPE_BODY_ATTRIBUTE],
            metadata=envelope_payload["metadata"],
        )

        self.assertEqual(HEARTBEAT_TERMINAL_ENVELOPE_BODY_ATTRIBUTE, "payload")
        self.assertEqual(
            extract_heartbeat_terminal_export_body(envelope),
            envelope.payload,
        )
        assert_heartbeat_terminal_protocol_envelope_contract(envelope)

        invalid_envelope = ProtocolEnvelope(
            protocol_version=HEARTBEAT_TERMINAL_PROTOCOL_VERSION,
            request_id="bad-kind",
            kind="heartbeat.other",
            payload=envelope.payload,
            metadata={},
        )
        with self.assertRaisesRegex(ValueError, "kind"):
            assert_heartbeat_terminal_protocol_envelope_contract(invalid_envelope)

    def test_golden_fixtures_match_all_cases(self) -> None:
        rendered_cases = build_heartbeat_terminal_contract_case_payloads()
        self.assertEqual(
            set(rendered_cases),
            {
                "continue",
                "converged",
                "no_eligible_participants",
                "converged_with_reservations",
                "blocker_driven_continue",
                "forced_non_terminal_continue",
            },
        )
        self.assertEqual(HEARTBEAT_TERMINAL_EXPORT_SCHEMA_ID, "heartbeat_terminal_export_v1")
        self.assertEqual(HEARTBEAT_TERMINAL_PROTOCOL_KIND, "heartbeat.terminal.export")
        self.assertEqual(HEARTBEAT_TERMINAL_PROTOCOL_VERSION, "1.0")
        for case_name, actual_payload in rendered_cases.items():
            with self.subTest(case=case_name):
                fixture_path = FIXTURE_DIR / f"{case_name}.json"
                expected_payload = json.loads(fixture_path.read_text(encoding="utf-8"))
                self.assertEqual(actual_payload, expected_payload)


if __name__ == "__main__":
    unittest.main()
