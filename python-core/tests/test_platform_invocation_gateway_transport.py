from __future__ import annotations

import unittest

from agent_os.application.services.platform_invocation_gateway_handler import (
    PLATFORM_SINGLE_TURN_INVOCATION_KIND,
    PLATFORM_SINGLE_TURN_INVOCATION_NOT_WIRED_KIND,
)
from agent_os.application.services.platform_invocation_gateway_transport import (
    PlatformInvocationGatewayTransportAdapter,
)


class PlatformInvocationGatewayTransportAdapterTest(unittest.TestCase):
    def test_dispatches_gateway_dict_and_returns_not_wired_gateway_dict(self) -> None:
        response = PlatformInvocationGatewayTransportAdapter().handle_gateway_envelope(
            {
                "protocolVersion": "1.0",
                "requestId": "request-1",
                "kind": PLATFORM_SINGLE_TURN_INVOCATION_KIND,
                "payload": {
                    "workspaceId": "workspace-1",
                    "agentId": "agent-1",
                    "instruction": "Summarize the workspace.",
                },
                "metadata": {"correlation_id": "correlation-1"},
            }
        )

        self.assertEqual(response["protocolVersion"], "1.0")
        self.assertEqual(response["requestId"], "request-1")
        self.assertEqual(response["kind"], PLATFORM_SINGLE_TURN_INVOCATION_NOT_WIRED_KIND)

        payload = response["payload"]
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["status"], "not_wired")
        self.assertFalse(payload["runtime_loaded"])
        self.assertEqual(payload["workspace_id"], "workspace-1")
        self.assertEqual(payload["agent_id"], "agent-1")

        metadata = response["metadata"]
        self.assertIsInstance(metadata, dict)
        self.assertEqual(metadata["correlation_id"], "correlation-1")
        self.assertEqual(metadata["platform_runtime_wired"], "false")

    def test_parse_gateway_envelope_requires_gateway_shape(self) -> None:
        adapter = PlatformInvocationGatewayTransportAdapter()

        with self.assertRaisesRegex(ValueError, "protocolVersion"):
            adapter.parse_gateway_envelope(
                {
                    "requestId": "request-2",
                    "kind": PLATFORM_SINGLE_TURN_INVOCATION_KIND,
                    "payload": {},
                }
            )

        with self.assertRaisesRegex(ValueError, "payload"):
            adapter.parse_gateway_envelope(
                {
                    "protocolVersion": "1.0",
                    "requestId": "request-3",
                    "kind": PLATFORM_SINGLE_TURN_INVOCATION_KIND,
                    "payload": "not-an-object",
                }
            )

        with self.assertRaisesRegex(ValueError, "metadata"):
            adapter.parse_gateway_envelope(
                {
                    "protocolVersion": "1.0",
                    "requestId": "request-4",
                    "kind": PLATFORM_SINGLE_TURN_INVOCATION_KIND,
                    "payload": {},
                    "metadata": {"attempt": 1},
                }
            )

    def test_rejects_unsupported_kind_without_runtime_dispatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported platform invocation envelope kind"):
            PlatformInvocationGatewayTransportAdapter().handle_gateway_envelope(
                {
                    "protocolVersion": "1.0",
                    "requestId": "request-5",
                    "kind": "task.submit",
                    "payload": {"goal": "legacy workflow"},
                }
            )


if __name__ == "__main__":
    unittest.main()
