from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.agent_exchange import (
    AgentExchangeAttribution,
    AgentExchangeAuthorType,
    AgentExchangeContributionKind,
    AgentExchangeInstructionAuthority,
    AgentExchangeSourceType,
    agent_exchange_interface_metadata,
)


class AgentExchangeContractTests(unittest.TestCase):
    def test_agent_exchange_attribution_serializes_stable_metadata(self) -> None:
        attribution = AgentExchangeAttribution.from_mapping(
            {
                "sourceType": "agent_context_update",
                "authorType": "agent",
                "contributionKind": "proposal",
                "authorAgentId": "agent-reviewer",
                "authorDisplayName": "Reviewer",
                "sourceChannel": "local_runtime_cli",
                "linkedConversationId": "conversation-1",
                "linkedActivationId": "activation-1",
                "sourceConfidence": "medium",
            }
        )

        metadata = attribution.to_metadata()

        self.assertEqual(metadata["schema"], "agent_exchange_attribution.v1")
        self.assertEqual(metadata["sourceType"], "agent_context_update")
        self.assertEqual(metadata["authorType"], "agent")
        self.assertEqual(metadata["contributionKind"], "proposal")
        self.assertEqual(metadata["instructionAuthority"], "agent_suggestion")
        self.assertFalse(metadata["agentOutputMayIssueUserDirective"])
        self.assertFalse(metadata["autoPromoteToDecision"])
        self.assertFalse(metadata["realRuntimeConnected"])
        self.assertFalse(metadata["providerPromptInjected"])
        self.assertFalse(metadata["fileBodiesIncluded"])
        self.assertEqual(metadata["linkedActivationId"], "activation-1")

    def test_non_user_contribution_cannot_claim_user_directive(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be user directives"):
            AgentExchangeAttribution(
                source_type=AgentExchangeSourceType.AGENT_MESSAGE,
                author_type=AgentExchangeAuthorType.AGENT,
                contribution_kind=AgentExchangeContributionKind.PROPOSAL,
                instruction_authority=(
                    AgentExchangeInstructionAuthority.USER_DIRECTIVE
                ),
            )

    def test_agent_authored_decision_requires_user_confirmed_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "require user_confirmed"):
            AgentExchangeAttribution(
                source_type=AgentExchangeSourceType.AGENT_CONTEXT_UPDATE,
                author_type=AgentExchangeAuthorType.AGENT,
                contribution_kind=AgentExchangeContributionKind.DECISION,
                author_agent_id="agent-reviewer",
            )

        accepted = AgentExchangeAttribution(
            source_type=AgentExchangeSourceType.AGENT_CONTEXT_UPDATE,
            author_type=AgentExchangeAuthorType.AGENT,
            contribution_kind=AgentExchangeContributionKind.DECISION,
            source_confidence="user_confirmed",
            author_agent_id="agent-reviewer",
        )
        self.assertEqual(
            accepted.to_metadata()["contributionKind"],
            "decision",
        )

    def test_conflict_notes_default_to_user_review(self) -> None:
        attribution = AgentExchangeAttribution(
            source_type=AgentExchangeSourceType.AGENT_MESSAGE,
            author_type=AgentExchangeAuthorType.AGENT,
            contribution_kind=AgentExchangeContributionKind.CONFLICT_NOTE,
            conflict_with=("context-update-1",),
        )

        metadata = attribution.to_metadata()

        self.assertTrue(metadata["requiresUserReview"])
        self.assertEqual(metadata["conflictWith"], ["context-update-1"])

    def test_credential_looking_metadata_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "credential values"):
            AgentExchangeAttribution.from_mapping(
                {
                    "sourceType": "external_import",
                    "authorType": "external",
                    "contributionKind": "observation",
                    "metadata": {"Authorization": "Bearer sk-example-token-value"},
                }
            )

    def test_interface_metadata_is_agent_facing_and_metadata_only(self) -> None:
        payload = agent_exchange_interface_metadata(workspace_id="workspace-1")
        interface = payload["agentExchangeInterface"]

        self.assertEqual(interface["schema"], "agent_exchange_interface.v1")
        self.assertEqual(interface["workspaceId"], "workspace-1")
        self.assertIn("agent_message", interface["sourceTypes"])
        self.assertIn("agent", interface["authorTypes"])
        self.assertIn("proposal", interface["contributionKinds"])
        self.assertFalse(interface["realRuntimeConnected"])
        self.assertFalse(interface["backgroundLoopEnabled"])
        self.assertFalse(interface["agentAutoWakeEnabled"])
        self.assertFalse(interface["fileBodiesReadableThroughExchange"])


if __name__ == "__main__":
    unittest.main()
