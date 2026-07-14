from __future__ import annotations

from datetime import datetime, timezone
import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.agent_activation import (
    AgentActivationGrant,
    AgentActivationMode,
    AgentActivationState,
    AgentStopReason,
    agent_activation_interface_metadata,
)


class AgentActivationContractTests(unittest.TestCase):
    def test_manual_wake_grant_serializes_safe_mode_budget(self) -> None:
        grant = AgentActivationGrant.from_mapping(
            {
                "activationId": "activation-1",
                "workspaceId": "workspace-1",
                "agentId": "agent-1",
                "createdBy": "user",
                "reason": "Review the shared context handoff.",
                "createdAt": "2026-06-18T01:00:00+00:00",
                "connectionSurface": "desktop_app_cli_capable",
                "budget": {
                    "ttlSeconds": 120,
                    "maxOperations": 2,
                    "maxWrites": 1,
                    "maxAgentToAgentTurns": 0,
                    "maxContextReads": 3,
                },
            }
        )

        metadata = grant.to_metadata()

        self.assertEqual(metadata["schema"], "agent_activation_grant.v1")
        self.assertEqual(metadata["state"], AgentActivationState.AWAKENED.value)
        self.assertEqual(metadata["mode"], AgentActivationMode.MANUAL_WAKE_SAFE_MODE.value)
        self.assertEqual(metadata["connectionSurface"], "desktop_app_cli_capable")
        self.assertTrue(metadata["requiresManualUserWake"])
        self.assertFalse(metadata["realRuntimeConnected"])
        self.assertFalse(metadata["agentAutoWakeEnabled"])
        self.assertFalse(metadata["providerPromptInjected"])
        self.assertFalse(metadata["fileBodiesReadableThroughActivation"])
        self.assertEqual(metadata["budget"]["maxWrites"], 1)
        self.assertEqual(metadata["budget"]["maxAgentToAgentTurns"], 0)

    def test_revoked_or_expired_grant_rejects_writes(self) -> None:
        grant = AgentActivationGrant.from_mapping(
            {
                "activationId": "activation-2",
                "workspaceId": "workspace-1",
                "agentId": "agent-1",
                "createdBy": "user",
                "reason": "Short review.",
                "createdAt": "2026-06-18T01:00:00+00:00",
                "budget": {
                    "ttlSeconds": 1,
                    "expiresAt": "2026-06-18T01:00:01+00:00",
                },
            }
        )
        expired = grant.expired_copy(
            checked_at=datetime(2026, 6, 18, 1, 1, tzinfo=timezone.utc)
        )
        revoked = grant.revoked_copy(
            revoked_by="user",
            reason="Stop the handoff.",
            revoked_at=datetime(2026, 6, 18, 1, 2, tzinfo=timezone.utc),
        )

        self.assertEqual(expired.state, AgentActivationState.EXPIRED)
        self.assertEqual(revoked.stop_reason, AgentStopReason.REVOKED)
        self.assertEqual(
            expired.is_write_allowed(contribution_kind="proposal"),
            (False, "expired"),
        )
        self.assertEqual(
            revoked.is_write_allowed(contribution_kind="proposal"),
            (False, "revoked"),
        )

    def test_interface_is_contract_only(self) -> None:
        interface = agent_activation_interface_metadata(
            workspace_id="workspace-1"
        )["agentActivationInterface"]

        self.assertEqual(interface["schema"], "agent_activation_interface.v1")
        self.assertIn("manual_wake_safe_mode", interface["activationModes"])
        self.assertIn("cli", interface["connectionSurfaces"])
        self.assertFalse(interface["safeModeDefaults"]["realRuntimeConnected"])
        self.assertFalse(interface["safeModeDefaults"]["agentAutoWakeEnabled"])
        self.assertEqual(interface["exchangeLinkKey"], "linkedActivationId")


if __name__ == "__main__":
    unittest.main()
