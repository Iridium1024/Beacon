from __future__ import annotations

import unittest

from agent_os.application.services.agent_dispatch_control import (
    AgentDispatchControlSelection,
    agent_dispatch_semantic_mapping,
    effective_agent_dispatch_semantic_mapping,
    resolve_agent_dispatch_control_config,
    resolve_agent_dispatch_delivery_mode,
)
from agent_os.application.services.local_platform_application import (
    _agent_dispatch_delivery_decision,
)


class AgentDispatchControlTests(unittest.TestCase):
    def test_legacy_modes_map_to_stable_external_and_internal_semantics(self) -> None:
        inline = agent_dispatch_semantic_mapping("worker_execute")
        queued = agent_dispatch_semantic_mapping("queued")
        dry_run = agent_dispatch_semantic_mapping("worker_dry_run")

        self.assertEqual(inline.external_operation.value, "send")
        self.assertEqual(inline.execution_strategy.value, "inline")
        self.assertEqual(queued.external_operation.value, "queue")
        self.assertEqual(queued.execution_strategy.value, "queue")
        self.assertEqual(dry_run.execution_strategy.value, "dry_run")
        self.assertTrue(inline.compatibility_alias)

    def test_cli_alias_resolution_uses_the_canonical_mapping(self) -> None:
        default = AgentDispatchControlSelection(
            value="worker_execute",
            source="default",
        )
        wait_once = resolve_agent_dispatch_delivery_mode(
            delivery_mode=None,
            wait_mode="once",
            queued=False,
            default_selection=default,
        )
        queued = resolve_agent_dispatch_delivery_mode(
            delivery_mode=None,
            wait_mode=None,
            queued=True,
            default_selection=default,
        )
        dry_run = effective_agent_dispatch_semantic_mapping(
            "worker_execute",
            dry_run=True,
        )

        self.assertEqual(wait_once.value, "worker_execute")
        self.assertEqual(wait_once.source, "explicit_cli")
        self.assertEqual(queued.value, "queued")
        self.assertEqual(dry_run.execution_strategy.value, "dry_run")
        self.assertEqual(dry_run.legacy_delivery_mode, "worker_execute")

    def test_defaults_select_bounded_worker_and_return_busy_to_sender(self) -> None:
        config = resolve_agent_dispatch_control_config({})

        self.assertEqual(config.default_delivery_mode.value, "worker_execute")
        self.assertEqual(config.default_delivery_mode.source, "default")
        self.assertEqual(config.immediate_busy_policy.value, "return_to_sender")
        self.assertEqual(config.immediate_busy_policy.source, "default")

    def test_profile_and_explicit_cli_follow_fixed_precedence(self) -> None:
        profile = {
            "dispatchControl": {
                "defaultDeliveryMode": "queued",
                "immediateBusyPolicy": "queue_next_turn",
            }
        }
        profile_config = resolve_agent_dispatch_control_config(profile)
        explicit_config = resolve_agent_dispatch_control_config(
            profile,
            immediate_busy_policy="return_to_sender",
        )

        self.assertEqual(profile_config.default_delivery_mode.value, "queued")
        self.assertEqual(
            profile_config.default_delivery_mode.source,
            "localRuntime.dispatchControl",
        )
        self.assertEqual(profile_config.immediate_busy_policy.value, "queue_next_turn")
        self.assertEqual(explicit_config.immediate_busy_policy.value, "return_to_sender")
        self.assertEqual(explicit_config.immediate_busy_policy.source, "explicit_cli")

    def test_invalid_nested_configuration_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "dispatchControl"):
            resolve_agent_dispatch_control_config({"dispatchControl": []})
        with self.assertRaisesRegex(ValueError, "defaultDeliveryMode"):
            resolve_agent_dispatch_control_config(
                {"dispatchControl": {"defaultDeliveryMode": "automatic"}}
            )

    def test_busy_actions_offer_supplement_only_for_owned_steerable_codex(self) -> None:
        worker = {
            "workerStarted": True,
            "agentDispatches": [
                {
                    "failureCategory": "target_busy_requires_sender_decision",
                    "providerRuntimeStatus": {
                        "runtimeState": "busy",
                        "stateSource": "codex_beacon_owned_runtime",
                        "canSteer": True,
                    },
                }
            ],
        }
        status = {
            "agentDispatch": {"status": "failed"},
            "agentExchangeRequest": {"status": "active"},
        }

        codex = _agent_dispatch_delivery_decision(
            delivery_mode="worker_execute",
            delivery_mode_source="default",
            immediate_busy_policy="return_to_sender",
            immediate_busy_policy_source="default",
            dry_run=False,
            worker_run=worker,
            status=status,
            target_provider="codex",
        )
        claude = _agent_dispatch_delivery_decision(
            delivery_mode="worker_execute",
            delivery_mode_source="default",
            immediate_busy_policy="return_to_sender",
            immediate_busy_policy_source="default",
            dry_run=False,
            worker_run=worker,
            status=status,
            target_provider="claude",
        )

        self.assertEqual(
            codex["availableActions"],
            ["supplement_active_turn", "queue_next_turn", "cancel"],
        )
        self.assertEqual(claude["availableActions"], ["queue_next_turn", "cancel"])

    def test_execution_completion_does_not_require_a_recorded_reply(self) -> None:
        decision = _agent_dispatch_delivery_decision(
            delivery_mode="worker_execute",
            delivery_mode_source="default",
            immediate_busy_policy="return_to_sender",
            immediate_busy_policy_source="default",
            dry_run=False,
            worker_run={
                "workerStarted": True,
                "agentDispatches": [
                    {
                        "activation": {
                            "status": "delivered",
                            "providerCommandStarted": True,
                        }
                    }
                ],
            },
            status={
                "agentDispatch": {"status": "waiting_response"},
                "agentExchangeRequest": {"status": "active"},
            },
            target_provider="codex",
        )

        self.assertEqual(decision["deliveryState"], "accepted")
        self.assertEqual(decision["executionState"], "completed")
        self.assertEqual(decision["replyState"], "none")
        self.assertEqual(decision["replyExpectation"], "unspecified")
        self.assertFalse(decision["responseAvailable"])

    def test_provider_process_start_does_not_overclaim_delivery_or_completion(
        self,
    ) -> None:
        decision = _agent_dispatch_delivery_decision(
            delivery_mode="worker_execute",
            delivery_mode_source="default",
            immediate_busy_policy="return_to_sender",
            immediate_busy_policy_source="default",
            dry_run=False,
            worker_run={
                "workerStarted": True,
                "agentDispatches": [
                    {"activation": {"providerCommandStarted": True}}
                ],
            },
            status={
                "agentDispatch": {"status": "waiting_response"},
                "agentExchangeRequest": {"status": "active"},
            },
            target_provider="claude",
        )

        self.assertEqual(decision["deliveryState"], "unknown")
        self.assertEqual(decision["executionState"], "active")
        self.assertFalse(decision["completionObserved"])


if __name__ == "__main__":
    unittest.main()
