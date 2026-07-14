from __future__ import annotations

import unittest

from agent_os.application.services.platform_invocation_gateway_handler import (
    PLATFORM_SINGLE_TURN_INVOCATION_KIND,
    PLATFORM_SINGLE_TURN_INVOCATION_NOT_WIRED_KIND,
    PlatformInvocationGatewayHandler,
    SingleTurnPlatformInvocationPayloadDraft,
)
from agent_os.domain.ports.protocol import ProtocolEnvelope


class PlatformInvocationGatewayHandlerTest(unittest.TestCase):
    def test_payload_draft_normalizes_gateway_request_shape(self) -> None:
        draft = SingleTurnPlatformInvocationPayloadDraft.from_payload(
            {
                "workspaceId": " workspace-1 ",
                "agentId": "agent-1",
                "instruction": " Summarize the current task. ",
                "invocationId": "invoke-1",
                "requestedAt": "2026-06-04T05:05:44Z",
                "taskId": "task-1",
                "requestedCapability": "single-turn-status",
                "contextUpdateIds": [" update-1 ", "update-2"],
                "fileReferences": [" docs/status.md "],
                "idempotencyKey": "idem-1",
                "correlationId": "corr-1",
                "requestMetadata": {"source": "gateway"},
            }
        )

        self.assertEqual(draft.workspace_id, "workspace-1")
        self.assertEqual(draft.agent_id, "agent-1")
        self.assertEqual(draft.instruction, "Summarize the current task.")
        self.assertEqual(draft.invocation_id, "invoke-1")
        self.assertEqual(draft.requested_at, "2026-06-04T05:05:44Z")
        self.assertEqual(draft.task_id, "task-1")
        self.assertEqual(draft.requested_capability, "single-turn-status")
        self.assertEqual(draft.context_update_ids, ("update-1", "update-2"))
        self.assertEqual(draft.file_references, ("docs/status.md",))
        self.assertEqual(draft.idempotency_key, "idem-1")
        self.assertEqual(draft.correlation_id, "corr-1")
        self.assertEqual(draft.request_metadata["source"], "gateway")

    def test_payload_draft_rejects_malformed_optional_shapes(self) -> None:
        base_payload = {
            "workspaceId": "workspace-1",
            "agentId": "agent-1",
            "instruction": "Summarize the current task.",
        }

        with self.assertRaisesRegex(ValueError, "context_update_ids"):
            SingleTurnPlatformInvocationPayloadDraft.from_payload(
                {
                    **base_payload,
                    "contextUpdateIds": ["update-1", ""],
                }
            )

        with self.assertRaisesRegex(ValueError, "file_references"):
            SingleTurnPlatformInvocationPayloadDraft.from_payload(
                {
                    **base_payload,
                    "fileReferences": "docs/status.md",
                }
            )

        with self.assertRaisesRegex(ValueError, "request_metadata"):
            SingleTurnPlatformInvocationPayloadDraft.from_payload(
                {
                    **base_payload,
                    "requestMetadata": "metadata",
                }
            )

    def test_returns_not_wired_envelope_without_loading_runtime(self) -> None:
        envelope = ProtocolEnvelope(
            protocol_version="1.0",
            request_id="request-1",
            kind=PLATFORM_SINGLE_TURN_INVOCATION_KIND,
            payload={
                "workspaceId": "workspace-1",
                "agentId": "agent-1",
                "instruction": "Summarize the current task.",
            },
            metadata={"correlation_id": "correlation-1"},
        )

        response = PlatformInvocationGatewayHandler().handle(envelope)

        self.assertEqual(response.protocol_version, "1.0")
        self.assertEqual(response.request_id, "request-1")
        self.assertEqual(response.kind, PLATFORM_SINGLE_TURN_INVOCATION_NOT_WIRED_KIND)
        self.assertEqual(response.payload["status"], "not_wired")
        self.assertEqual(response.payload["accepted_kind"], PLATFORM_SINGLE_TURN_INVOCATION_KIND)
        self.assertFalse(response.payload["runtime_loaded"])
        self.assertEqual(response.payload["workspace_id"], "workspace-1")
        self.assertEqual(response.payload["agent_id"], "agent-1")
        self.assertEqual(response.metadata["correlation_id"], "correlation-1")
        self.assertEqual(response.metadata["platform_runtime_wired"], "false")

    def test_supports_snake_case_payload_ids_from_python_callers(self) -> None:
        envelope = ProtocolEnvelope(
            protocol_version="1.0",
            request_id="request-2",
            kind=PLATFORM_SINGLE_TURN_INVOCATION_KIND,
            payload={
                "workspace_id": "workspace-2",
                "agent_id": "agent-2",
                "instruction": "Capture this task.",
            },
        )

        response = PlatformInvocationGatewayHandler().handle(envelope)

        self.assertEqual(response.payload["workspace_id"], "workspace-2")
        self.assertEqual(response.payload["agent_id"], "agent-2")

    def test_rejects_single_turn_payload_without_required_fields(self) -> None:
        handler = PlatformInvocationGatewayHandler()
        cases = (
            (
                "workspace_id",
                {
                    "agentId": "agent-1",
                    "instruction": "Capture this task.",
                },
            ),
            (
                "agent_id",
                {
                    "workspaceId": "workspace-1",
                    "instruction": "Capture this task.",
                },
            ),
            (
                "instruction",
                {
                    "workspaceId": "workspace-1",
                    "agentId": "agent-1",
                    "instruction": " ",
                },
            ),
        )

        for field_name, payload in cases:
            with self.subTest(field_name=field_name):
                envelope = ProtocolEnvelope(
                    protocol_version="1.0",
                    request_id=f"request-missing-{field_name}",
                    kind=PLATFORM_SINGLE_TURN_INVOCATION_KIND,
                    payload=payload,
                )

                with self.assertRaisesRegex(ValueError, field_name):
                    handler.handle(envelope)

    def test_rejects_unsupported_envelope_kind(self) -> None:
        envelope = ProtocolEnvelope(
            protocol_version="1.0",
            request_id="request-3",
            kind="task.submit",
            payload={"goal": "legacy workflow"},
        )

        handler = PlatformInvocationGatewayHandler()

        self.assertFalse(handler.can_handle(envelope))
        with self.assertRaisesRegex(ValueError, "unsupported platform invocation envelope kind"):
            handler.handle(envelope)


if __name__ == "__main__":
    unittest.main()
