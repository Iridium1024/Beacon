from __future__ import annotations

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
from agent_os.orchestrator.convergence import ConvergenceStatus
from agent_os.orchestrator.heartbeat_terminal_export import build_heartbeat_terminal_export
from agent_os.orchestrator.heartbeat_terminal_payload import (
    HeartbeatTerminalDisplaySectionKind,
)
from agent_os.protocols.heartbeat_terminal_export_contract import (
    HEARTBEAT_TERMINAL_ENVELOPE_BODY_ATTRIBUTE,
    HEARTBEAT_TERMINAL_EXPORT_CANDIDATE_REQUIRED_FIELDS,
    HEARTBEAT_TERMINAL_EXPORT_DISPLAY_METADATA_REQUIRED_FIELDS,
    HEARTBEAT_TERMINAL_EXPORT_REQUIRED_FIELDS,
    HEARTBEAT_TERMINAL_EXPORT_SCHEMA_ID,
    HEARTBEAT_TERMINAL_EXPORT_SECTION_KIND_VOCABULARY,
    assert_heartbeat_terminal_export_body_contract,
    assert_heartbeat_terminal_protocol_envelope_contract,
)
from agent_os.protocols.heartbeat_terminal_shared_manifest import (
    HEARTBEAT_TERMINAL_DISPLAY_METADATA_NON_OMITTABLE_SECTIONS,
    HEARTBEAT_TERMINAL_DISPLAY_METADATA_OMISSION_METADATA_KEY,
    HEARTBEAT_TERMINAL_DISPLAY_METADATA_OMIT_EMPTY_SECTIONS_KEY,
    HEARTBEAT_TERMINAL_DISPLAY_METADATA_OMIT_EMPTY_SECTIONS_VALUE,
    HEARTBEAT_TERMINAL_DISPLAY_METADATA_POLICY_VERSION_KEY,
    HEARTBEAT_TERMINAL_DISPLAY_METADATA_RETAINED_ITEM_COUNT_KEY,
    HEARTBEAT_TERMINAL_DISPLAY_METADATA_SECTION_COUNT_KEY,
    HEARTBEAT_TERMINAL_DISPLAY_METADATA_SECTION_ORDER_KEY,
    HEARTBEAT_TERMINAL_DISPLAY_METADATA_TRUNCATION_RULES,
    HEARTBEAT_TERMINAL_EXPORT_BREAKING_CHANGES,
    HEARTBEAT_TERMINAL_EXPORT_COMPATIBLE_ADDITIONS,
    HEARTBEAT_TERMINAL_SHARED_MANIFEST,
    HEARTBEAT_TERMINAL_SHARED_MANIFEST_PATH,
)
from heartbeat_terminal_contract_cases import (
    build_heartbeat_terminal_contract_case_payloads,
)
from test_heartbeat_terminal_payload import build_attached_result, build_profile
from agent_os.orchestrator.heartbeat_convergence_profile import (
    HeartbeatConvergenceDominantReason,
    HeartbeatConvergenceFollowupBias,
    HeartbeatConvergenceReservationLevel,
    HeartbeatConvergenceSemanticState,
)


class HeartbeatTerminalSharedManifestTests(unittest.TestCase):
    def test_shared_manifest_matches_python_contract_constants(self) -> None:
        payload_manifest = HEARTBEAT_TERMINAL_SHARED_MANIFEST["payload"]
        candidate_manifest = payload_manifest["candidate"]
        display_metadata_manifest = payload_manifest["display_metadata"]
        omission_rules = display_metadata_manifest["omission_rules"]
        compatibility_manifest = HEARTBEAT_TERMINAL_SHARED_MANIFEST["compatibility"]

        self.assertTrue(HEARTBEAT_TERMINAL_SHARED_MANIFEST_PATH.exists())
        self.assertEqual(
            HEARTBEAT_TERMINAL_EXPORT_SCHEMA_ID,
            HEARTBEAT_TERMINAL_SHARED_MANIFEST["schema_id"],
        )
        self.assertEqual(
            HEARTBEAT_TERMINAL_PROTOCOL_KIND,
            HEARTBEAT_TERMINAL_SHARED_MANIFEST["envelope"]["kind"],
        )
        self.assertEqual(
            HEARTBEAT_TERMINAL_PROTOCOL_VERSION,
            HEARTBEAT_TERMINAL_SHARED_MANIFEST["envelope"]["protocol_version"],
        )
        self.assertEqual(
            HEARTBEAT_TERMINAL_ENVELOPE_BODY_ATTRIBUTE,
            HEARTBEAT_TERMINAL_SHARED_MANIFEST["envelope"]["body_location"],
        )
        self.assertEqual(
            HEARTBEAT_TERMINAL_EXPORT_REQUIRED_FIELDS,
            tuple(payload_manifest["required_fields"]),
        )
        self.assertEqual(
            HEARTBEAT_TERMINAL_EXPORT_CANDIDATE_REQUIRED_FIELDS,
            tuple(candidate_manifest["required_fields"]),
        )
        self.assertEqual(
            HEARTBEAT_TERMINAL_EXPORT_DISPLAY_METADATA_REQUIRED_FIELDS,
            tuple(display_metadata_manifest["required_keys"]),
        )
        self.assertEqual(
            HEARTBEAT_TERMINAL_EXPORT_SECTION_KIND_VOCABULARY,
            tuple(payload_manifest["section_vocabulary"]),
        )
        self.assertEqual(
            HEARTBEAT_TERMINAL_DISPLAY_METADATA_POLICY_VERSION_KEY,
            display_metadata_manifest["display_policy_version_key"],
        )
        self.assertEqual(
            HEARTBEAT_TERMINAL_DISPLAY_METADATA_SECTION_ORDER_KEY,
            display_metadata_manifest["display_section_order_key"],
        )
        self.assertEqual(
            HEARTBEAT_TERMINAL_DISPLAY_METADATA_OMIT_EMPTY_SECTIONS_KEY,
            display_metadata_manifest["display_omit_empty_sections_key"],
        )
        self.assertEqual(
            HEARTBEAT_TERMINAL_DISPLAY_METADATA_OMIT_EMPTY_SECTIONS_VALUE,
            display_metadata_manifest["display_omit_empty_sections_value"],
        )
        self.assertEqual(
            HEARTBEAT_TERMINAL_DISPLAY_METADATA_SECTION_COUNT_KEY,
            display_metadata_manifest["display_section_count_key"],
        )
        self.assertEqual(
            HEARTBEAT_TERMINAL_DISPLAY_METADATA_RETAINED_ITEM_COUNT_KEY,
            display_metadata_manifest["retained_item_count_key"],
        )
        self.assertEqual(
            HEARTBEAT_TERMINAL_DISPLAY_METADATA_OMISSION_METADATA_KEY,
            omission_rules["metadata_key"],
        )
        self.assertEqual(
            HEARTBEAT_TERMINAL_DISPLAY_METADATA_NON_OMITTABLE_SECTIONS,
            tuple(omission_rules["non_omittable_sections"]),
        )
        self.assertEqual(
            HEARTBEAT_TERMINAL_EXPORT_COMPATIBLE_ADDITIONS,
            tuple(compatibility_manifest["compatible_additions"]),
        )
        self.assertEqual(
            HEARTBEAT_TERMINAL_EXPORT_BREAKING_CHANGES,
            tuple(compatibility_manifest["breaking_changes"]),
        )

    def test_shared_manifest_matches_display_section_and_metadata_contract(self) -> None:
        self.assertEqual(
            HEARTBEAT_TERMINAL_EXPORT_SECTION_KIND_VOCABULARY,
            tuple(kind.value for kind in HeartbeatTerminalDisplaySectionKind),
        )
        self.assertIn(
            HEARTBEAT_TERMINAL_DISPLAY_METADATA_POLICY_VERSION_KEY,
            HEARTBEAT_TERMINAL_EXPORT_DISPLAY_METADATA_REQUIRED_FIELDS,
        )
        self.assertIn(
            HEARTBEAT_TERMINAL_DISPLAY_METADATA_SECTION_ORDER_KEY,
            HEARTBEAT_TERMINAL_EXPORT_DISPLAY_METADATA_REQUIRED_FIELDS,
        )
        self.assertIn(
            HEARTBEAT_TERMINAL_DISPLAY_METADATA_OMIT_EMPTY_SECTIONS_KEY,
            HEARTBEAT_TERMINAL_EXPORT_DISPLAY_METADATA_REQUIRED_FIELDS,
        )
        self.assertIn(
            HEARTBEAT_TERMINAL_DISPLAY_METADATA_SECTION_COUNT_KEY,
            HEARTBEAT_TERMINAL_EXPORT_DISPLAY_METADATA_REQUIRED_FIELDS,
        )
        self.assertIn(
            HEARTBEAT_TERMINAL_DISPLAY_METADATA_RETAINED_ITEM_COUNT_KEY,
            HEARTBEAT_TERMINAL_EXPORT_DISPLAY_METADATA_REQUIRED_FIELDS,
        )
        self.assertIn(
            HEARTBEAT_TERMINAL_DISPLAY_METADATA_OMISSION_METADATA_KEY,
            HEARTBEAT_TERMINAL_EXPORT_DISPLAY_METADATA_REQUIRED_FIELDS,
        )
        for truncation_key, truncation_rule in HEARTBEAT_TERMINAL_DISPLAY_METADATA_TRUNCATION_RULES.items():
            self.assertIn(
                truncation_key,
                HEARTBEAT_TERMINAL_EXPORT_DISPLAY_METADATA_REQUIRED_FIELDS,
            )
            self.assertIn(
                truncation_rule["count_key"],
                HEARTBEAT_TERMINAL_EXPORT_DISPLAY_METADATA_REQUIRED_FIELDS,
            )
            self.assertIn(
                truncation_rule["section_kind"],
                HEARTBEAT_TERMINAL_EXPORT_SECTION_KIND_VOCABULARY,
            )

    def test_shared_manifest_matches_export_and_envelope_builders(self) -> None:
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

        export_payload = build_heartbeat_terminal_export(result)
        envelope = build_heartbeat_terminal_protocol_envelope(
            export_payload,
            request_id="manifest-check",
        )

        self.assertEqual(export_payload.schema_id, HEARTBEAT_TERMINAL_EXPORT_SCHEMA_ID)
        self.assertEqual(envelope.kind, HEARTBEAT_TERMINAL_PROTOCOL_KIND)
        self.assertEqual(envelope.protocol_version, HEARTBEAT_TERMINAL_PROTOCOL_VERSION)
        self.assertIsInstance(
            getattr(envelope, HEARTBEAT_TERMINAL_ENVELOPE_BODY_ATTRIBUTE),
            dict,
        )
        assert_heartbeat_terminal_export_body_contract(envelope.payload)
        assert_heartbeat_terminal_protocol_envelope_contract(envelope)

    def test_golden_fixtures_satisfy_shared_manifest_contract(self) -> None:
        fixture_dir = Path(__file__).resolve().parent / "golden" / "heartbeat_terminal_contract"
        rendered_cases = build_heartbeat_terminal_contract_case_payloads()

        for fixture_path in sorted(fixture_dir.glob("*.json")):
            with self.subTest(fixture=fixture_path.name):
                payload = json.loads(fixture_path.read_text(encoding="utf-8"))
                assert_heartbeat_terminal_export_body_contract(payload["export"])
                envelope = ProtocolEnvelope(
                    protocol_version=payload["envelope"]["protocol_version"],
                    request_id=payload["envelope"]["request_id"],
                    kind=payload["envelope"]["kind"],
                    payload=payload["envelope"][HEARTBEAT_TERMINAL_ENVELOPE_BODY_ATTRIBUTE],
                    metadata=payload["envelope"]["metadata"],
                )
                assert_heartbeat_terminal_protocol_envelope_contract(envelope)
                self.assertEqual(payload, rendered_cases[fixture_path.stem])

    def test_gateway_ts_contract_reads_shared_manifest(self) -> None:
        gateway_contract_path = (
            PROJECT_SRC.parents[1]
            / "gateway"
            / "src"
            / "domain"
            / "contracts"
            / "heartbeat-terminal-export.ts"
        )
        gateway_contract_source = gateway_contract_path.read_text(encoding="utf-8")

        self.assertIn("heartbeat-terminal-export.manifest.json", gateway_contract_source)
        self.assertIn(
            "HEARTBEAT_TERMINAL_SHARED_MANIFEST",
            gateway_contract_source,
        )


if __name__ == "__main__":
    unittest.main()
