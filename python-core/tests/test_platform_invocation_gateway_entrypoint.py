from __future__ import annotations

import unittest
from typing import Mapping

from agent_os.application.services.platform_invocation_gateway_entrypoint import (
    handle_platform_invocation_gateway_envelope,
)
from agent_os.application.services.platform_invocation_gateway_handler import (
    PLATFORM_SINGLE_TURN_INVOCATION_KIND,
    PLATFORM_SINGLE_TURN_INVOCATION_NOT_WIRED_KIND,
)


class RecordingGatewayEnvelopeAdapter:
    def __init__(self) -> None:
        self.last_envelope: Mapping[str, object] | None = None

    def handle_gateway_envelope(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        self.last_envelope = envelope
        return {
            "protocolVersion": "test",
            "requestId": "delegated",
            "kind": "delegated",
            "payload": {"delegated": True},
            "metadata": {},
        }


class PlatformInvocationGatewayEntrypointTest(unittest.TestCase):
    def test_default_entrypoint_returns_not_wired_response(self) -> None:
        response = handle_platform_invocation_gateway_envelope(
            {
                "protocolVersion": "1.0",
                "requestId": "request-1",
                "kind": PLATFORM_SINGLE_TURN_INVOCATION_KIND,
                "payload": {
                    "workspaceId": "workspace-1",
                    "agentId": "agent-1",
                    "instruction": "Capture status.",
                },
            }
        )

        self.assertEqual(response["protocolVersion"], "1.0")
        self.assertEqual(response["requestId"], "request-1")
        self.assertEqual(response["kind"], PLATFORM_SINGLE_TURN_INVOCATION_NOT_WIRED_KIND)
        payload = response["payload"]
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["status"], "not_wired")
        self.assertFalse(payload["runtime_loaded"])

    def test_entrypoint_allows_injected_adapter_for_future_bridge_tests(self) -> None:
        adapter = RecordingGatewayEnvelopeAdapter()
        envelope = {
            "protocolVersion": "1.0",
            "requestId": "request-2",
            "kind": PLATFORM_SINGLE_TURN_INVOCATION_KIND,
            "payload": {},
        }

        response = handle_platform_invocation_gateway_envelope(envelope, adapter=adapter)

        self.assertIs(adapter.last_envelope, envelope)
        self.assertEqual(response["requestId"], "delegated")
        self.assertEqual(response["payload"], {"delegated": True})

    def test_entrypoint_keeps_unsupported_kind_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported platform invocation envelope kind"):
            handle_platform_invocation_gateway_envelope(
                {
                    "protocolVersion": "1.0",
                    "requestId": "request-3",
                    "kind": "task.submit",
                    "payload": {"goal": "legacy workflow"},
                }
            )


if __name__ == "__main__":
    unittest.main()
