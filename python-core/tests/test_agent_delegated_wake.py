from __future__ import annotations

from datetime import datetime, timezone, timedelta
import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.agent_activation import AgentActivationMode
from agent_os.application.services.agent_delegated_wake import (
    DelegatedWakeDenyReason,
    DelegatedWakeGrant,
    DelegatedWakeGrantMode,
    DelegatedWakeGrantState,
    delegated_wake_interface_metadata,
)


def _future_iso() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


def _past_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


class DelegatedWakeGrantContractTests(unittest.TestCase):
    def test_pending_grant_defaults_to_single_use_non_delegatable(self) -> None:
        grant = DelegatedWakeGrant.from_mapping(
            {
                "delegatedWakeGrantId": "dw-1",
                "workspaceId": "workspace-1",
                "sourceAgentId": "agent-src",
                "targetAgentId": "agent-tgt",
                "createdBy": "user",
                "reason": "Allow one bounded handoff.",
                "createdAt": "2026-06-18T01:00:00+00:00",
                "expiresAt": _future_iso(),
            }
        )

        metadata = grant.to_metadata()

        self.assertEqual(metadata["schema"], "delegated_wake_grant.v1")
        self.assertEqual(metadata["state"], DelegatedWakeGrantState.PENDING.value)
        self.assertEqual(
            metadata["mode"],
            DelegatedWakeGrantMode.USER_AUTHORIZED_ONE_TIME.value,
        )
        self.assertEqual(metadata["maxUses"], 1)
        self.assertEqual(metadata["usesConsumed"], 0)
        self.assertFalse(metadata["canDelegateFurther"])
        self.assertTrue(metadata["userAuthorizedDelegatedWake"])
        self.assertFalse(metadata["realRuntimeConnected"])
        self.assertFalse(metadata["backgroundLoopEnabled"])
        self.assertFalse(metadata["agentAutoWakeEnabled"])
        self.assertFalse(metadata["providerPromptInjected"])
        self.assertFalse(metadata["fileBodiesReadableThroughGrant"])
        self.assertFalse(metadata["grantsRuntimePermissions"])
        self.assertEqual(
            metadata["targetActivationMode"],
            AgentActivationMode.MANUAL_WAKE_SAFE_MODE.value,
        )

    def test_consume_allowed_only_for_matching_source_agent(self) -> None:
        grant = DelegatedWakeGrant.from_mapping(
            {
                "delegatedWakeGrantId": "dw-2",
                "workspaceId": "workspace-1",
                "sourceAgentId": "agent-src",
                "targetAgentId": "agent-tgt",
                "createdBy": "user",
                "reason": "handoff",
                "expiresAt": _future_iso(),
            }
        )

        ok, _ = grant.is_consume_allowed(
            consuming_agent_id="agent-src",
            target_agent_exists=True,
        )
        self.assertTrue(ok)

        ok, reason = grant.is_consume_allowed(
            consuming_agent_id="agent-other",
            target_agent_exists=True,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, DelegatedWakeDenyReason.SOURCE_AGENT_MISMATCH)

    def test_missing_expires_at_defaults_to_bounded_one_hour_ttl(self) -> None:
        created_at = datetime(2026, 6, 18, 1, 0, tzinfo=timezone.utc)
        grant = DelegatedWakeGrant.from_mapping(
            {
                "delegatedWakeGrantId": "dw-2-default-expiry",
                "workspaceId": "workspace-1",
                "sourceAgentId": "agent-src",
                "targetAgentId": "agent-tgt",
                "createdBy": "user",
                "reason": "handoff",
                "createdAt": created_at.isoformat(),
            }
        )

        self.assertEqual(grant.expires_at, created_at + timedelta(hours=1))
        self.assertEqual(
            grant.to_metadata()["expiresAt"],
            (created_at + timedelta(hours=1)).isoformat(),
        )

    def test_explicit_target_agent_mismatch_is_denied(self) -> None:
        grant = DelegatedWakeGrant.from_mapping(
            {
                "delegatedWakeGrantId": "dw-2-target-mismatch",
                "workspaceId": "workspace-1",
                "sourceAgentId": "agent-src",
                "targetAgentId": "agent-tgt",
                "createdBy": "user",
                "reason": "handoff",
                "expiresAt": _future_iso(),
            }
        )

        ok, reason = grant.is_consume_allowed(
            consuming_agent_id="agent-src",
            target_agent_exists=True,
            target_agent_id="agent-other",
        )

        self.assertFalse(ok)
        self.assertEqual(reason, DelegatedWakeDenyReason.TARGET_AGENT_MISMATCH)

    def test_missing_target_agent_is_denied(self) -> None:
        grant = DelegatedWakeGrant.from_mapping(
            {
                "delegatedWakeGrantId": "dw-3",
                "workspaceId": "workspace-1",
                "sourceAgentId": "agent-src",
                "targetAgentId": "agent-tgt",
                "createdBy": "user",
                "reason": "handoff",
                "expiresAt": _future_iso(),
            }
        )

        ok, reason = grant.is_consume_allowed(
            consuming_agent_id="agent-src",
            target_agent_exists=False,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, DelegatedWakeDenyReason.TARGET_AGENT_NOT_FOUND)

    def test_revoked_and_expired_grants_cannot_be_consumed(self) -> None:
        grant = DelegatedWakeGrant.from_mapping(
            {
                "delegatedWakeGrantId": "dw-4",
                "workspaceId": "workspace-1",
                "sourceAgentId": "agent-src",
                "targetAgentId": "agent-tgt",
                "createdBy": "user",
                "reason": "handoff",
                "expiresAt": _future_iso(),
            }
        )
        revoked = grant.revoked_copy(
            revoked_by="user",
            reason="Stop the handoff.",
            revoked_at=datetime(2026, 6, 18, 1, 30, tzinfo=timezone.utc),
        )
        ok, reason = revoked.is_consume_allowed(
            consuming_agent_id="agent-src",
            target_agent_exists=True,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, DelegatedWakeDenyReason.GRANT_REVOKED)

        expired = DelegatedWakeGrant.from_mapping(
            {
                "delegatedWakeGrantId": "dw-5",
                "workspaceId": "workspace-1",
                "sourceAgentId": "agent-src",
                "targetAgentId": "agent-tgt",
                "createdBy": "user",
                "reason": "handoff",
                "expiresAt": _past_iso(),
            }
        )
        ok, reason = expired.is_consume_allowed(
            consuming_agent_id="agent-src",
            target_agent_exists=True,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, DelegatedWakeDenyReason.GRANT_EXPIRED)
        self.assertEqual(expired.expired_copy().state, DelegatedWakeGrantState.EXPIRED)

    def test_consumed_grant_records_target_activation_and_blocks_reuse(self) -> None:
        grant = DelegatedWakeGrant.from_mapping(
            {
                "delegatedWakeGrantId": "dw-6",
                "workspaceId": "workspace-1",
                "sourceAgentId": "agent-src",
                "targetAgentId": "agent-tgt",
                "createdBy": "user",
                "reason": "handoff",
                "expiresAt": _future_iso(),
            }
        )
        consumed = grant.consumed_copy(
            consumed_by_agent_id="agent-src",
            target_activation_id="activation-target-1",
            consumed_at=datetime(2026, 6, 18, 2, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(consumed.state, DelegatedWakeGrantState.CONSUMED)
        self.assertEqual(consumed.uses_consumed, 1)
        self.assertEqual(consumed.target_activation_id, "activation-target-1")
        self.assertEqual(consumed.consumed_by_agent_id, "agent-src")

        ok, reason = consumed.is_consume_allowed(
            consuming_agent_id="agent-src",
            target_agent_exists=True,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, DelegatedWakeDenyReason.GRANT_ALREADY_CONSUMED)

    def test_automatic_wake_mode_is_permanently_denied(self) -> None:
        grant = DelegatedWakeGrant.from_mapping(
            {
                "delegatedWakeGrantId": "dw-7",
                "workspaceId": "workspace-1",
                "sourceAgentId": "agent-src",
                "targetAgentId": "agent-tgt",
                "createdBy": "user",
                "reason": "auto",
                "mode": DelegatedWakeGrantMode.RESERVED_AUTOMATIC_DENIED.value,
                "expiresAt": _future_iso(),
            }
        )

        self.assertEqual(grant.state, DelegatedWakeGrantState.DENIED)
        self.assertEqual(grant.deny_reason, DelegatedWakeDenyReason.AUTOMATIC_WAKE_DENIED)
        ok, reason = grant.is_consume_allowed(
            consuming_agent_id="agent-src",
            target_agent_exists=True,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, DelegatedWakeDenyReason.AUTOMATIC_WAKE_DENIED)

    def test_grant_rejects_same_source_and_target_agent(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be the same agent"):
            DelegatedWakeGrant.from_mapping(
                {
                    "workspaceId": "workspace-1",
                    "sourceAgentId": "agent-x",
                    "targetAgentId": "agent-x",
                    "createdBy": "user",
                    "reason": "self",
                }
            )

    def test_grant_enforces_one_time_max_uses(self) -> None:
        with self.assertRaisesRegex(ValueError, "maxUses must be 1"):
            DelegatedWakeGrant.from_mapping(
                {
                    "workspaceId": "workspace-1",
                    "sourceAgentId": "agent-src",
                    "targetAgentId": "agent-tgt",
                    "createdBy": "user",
                    "reason": "multi",
                    "maxUses": 3,
                }
            )

    def test_grant_rejects_credential_looking_metadata(self) -> None:
        with self.assertRaisesRegex(ValueError, "credential values"):
            DelegatedWakeGrant.from_mapping(
                {
                    "workspaceId": "workspace-1",
                    "sourceAgentId": "agent-src",
                    "targetAgentId": "agent-tgt",
                    "createdBy": "user",
                    "reason": "leak",
                    "metadata": {"apiKey": "sk-fixture-not-a-real-token"},
                }
            )

    def test_denied_copy_preserves_state_for_audit(self) -> None:
        grant = DelegatedWakeGrant.from_mapping(
            {
                "delegatedWakeGrantId": "dw-8",
                "workspaceId": "workspace-1",
                "sourceAgentId": "agent-src",
                "targetAgentId": "agent-tgt",
                "createdBy": "user",
                "reason": "handoff",
                "expiresAt": _future_iso(),
            }
        )
        denied = grant.denied_copy(
            deny_reason=DelegatedWakeDenyReason.SOURCE_AGENT_MISMATCH,
            denied_by_agent_id="agent-other",
        )
        self.assertEqual(denied.state, DelegatedWakeGrantState.PENDING)
        self.assertEqual(denied.deny_reason, DelegatedWakeDenyReason.SOURCE_AGENT_MISMATCH)
        # A denied audit copy of a still-pending grant remains consumable by the correct source.
        ok, _ = denied.is_consume_allowed(
            consuming_agent_id="agent-src",
            target_agent_exists=True,
        )
        self.assertTrue(ok)

    def test_interface_is_contract_only(self) -> None:
        interface = delegated_wake_interface_metadata(
            workspace_id="workspace-1"
        )["delegatedWakeInterface"]

        self.assertEqual(interface["schema"], "delegated_wake_interface.v1")
        self.assertIn("user_authorized_one_time", interface["grantModes"])
        self.assertIn("source_agent_mismatch", interface["denyReasons"])
        self.assertFalse(interface["defaults"]["realRuntimeConnected"])
        self.assertFalse(interface["defaults"]["agentAutoWakeEnabled"])
        self.assertFalse(interface["defaults"]["canDelegateFurther"])
        self.assertTrue(interface["defaults"]["userAuthorizedDelegatedWake"])
        self.assertFalse(interface["defaults"]["grantsRuntimePermissions"])
        self.assertEqual(
            interface["localRuntimeCommands"]["consume"],
            "agent-delegated-wake-grant-consume",
        )


if __name__ == "__main__":
    unittest.main()
