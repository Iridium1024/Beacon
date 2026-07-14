from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from agent_os.domain.ports.protocol import ProtocolEnvelope


PLATFORM_SINGLE_TURN_INVOCATION_KIND = "platform.invocation.single_turn"
PLATFORM_SINGLE_TURN_INVOCATION_NOT_WIRED_KIND = "platform.invocation.single_turn.not_wired"


@dataclass(frozen=True, slots=True)
class SingleTurnPlatformInvocationPayloadDraft:
    """Normalized Gateway payload shape before runtime request construction."""

    workspace_id: str
    agent_id: str
    instruction: str
    invocation_id: str | None = None
    requested_at: str | None = None
    task_id: str | None = None
    requested_capability: str | None = None
    context_update_ids: tuple[str, ...] = ()
    file_references: tuple[str, ...] = ()
    idempotency_key: str | None = None
    correlation_id: str | None = None
    request_metadata: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, object]
    ) -> "SingleTurnPlatformInvocationPayloadDraft":
        return cls(
            workspace_id=_required_payload_text(
                payload, "workspace_id", "workspaceId", "workspace_id"
            ),
            agent_id=_required_payload_text(payload, "agent_id", "agentId", "agent_id"),
            instruction=_required_payload_text(payload, "instruction", "instruction"),
            invocation_id=_optional_payload_text(
                payload, "invocation_id", "invocationId", "invocation_id"
            ),
            requested_at=_optional_payload_text(payload, "requested_at", "requestedAt", "requested_at"),
            task_id=_optional_payload_text(payload, "task_id", "taskId", "task_id"),
            requested_capability=_optional_payload_text(
                payload,
                "requested_capability",
                "requestedCapability",
                "requested_capability",
            ),
            context_update_ids=_optional_payload_text_tuple(
                payload,
                "context_update_ids",
                "contextUpdateIds",
                "context_update_ids",
            ),
            file_references=_optional_payload_text_tuple(
                payload,
                "file_references",
                "fileReferences",
                "file_references",
            ),
            idempotency_key=_optional_payload_text(
                payload, "idempotency_key", "idempotencyKey", "idempotency_key"
            ),
            correlation_id=_optional_payload_text(
                payload, "correlation_id", "correlationId", "correlation_id"
            ),
            request_metadata=_optional_payload_mapping(
                payload, "request_metadata", "requestMetadata", "request_metadata"
            ),
        )


@dataclass(frozen=True, slots=True)
class PlatformInvocationGatewayHandler:
    """Minimal platform Gateway envelope handler before runtime wiring."""

    def can_handle(self, envelope: ProtocolEnvelope) -> bool:
        return envelope.kind == PLATFORM_SINGLE_TURN_INVOCATION_KIND

    def handle(self, envelope: ProtocolEnvelope) -> ProtocolEnvelope:
        if not self.can_handle(envelope):
            raise ValueError("unsupported platform invocation envelope kind.")

        return ProtocolEnvelope(
            protocol_version=envelope.protocol_version,
            request_id=envelope.request_id,
            kind=PLATFORM_SINGLE_TURN_INVOCATION_NOT_WIRED_KIND,
            payload=self._not_wired_payload(envelope.payload),
            metadata={
                **dict(envelope.metadata),
                "handler": "platform_invocation_gateway_handler",
                "platform_runtime_wired": "false",
            },
        )

    def _not_wired_payload(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        draft = SingleTurnPlatformInvocationPayloadDraft.from_payload(payload)
        return {
            "status": "not_wired",
            "message": "Single-turn platform invocation is not wired to the Python runtime yet.",
            "accepted_kind": PLATFORM_SINGLE_TURN_INVOCATION_KIND,
            "runtime_loaded": False,
            "workspace_id": draft.workspace_id,
            "agent_id": draft.agent_id,
        }


def _required_payload_text(
    payload: Mapping[str, object],
    logical_name: str,
    *field_names: str,
) -> str:
    value = _optional_payload_text(payload, logical_name, *field_names)
    if value is None:
        raise ValueError(
            f"platform invocation payload field '{logical_name}' must be a non-empty string."
        )
    return value


def _optional_payload_text(
    payload: Mapping[str, object],
    logical_name: str,
    *field_names: str,
) -> str | None:
    for field_name in field_names:
        if field_name not in payload:
            continue
        value = payload[field_name]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"platform invocation payload field '{logical_name}' must be a non-empty string."
            )
        return value.strip()
    return None


def _optional_payload_text_tuple(
    payload: Mapping[str, object],
    logical_name: str,
    *field_names: str,
) -> tuple[str, ...]:
    for field_name in field_names:
        if field_name not in payload:
            continue
        value = payload[field_name]
        if not isinstance(value, (list, tuple)):
            raise ValueError(
                f"platform invocation payload field '{logical_name}' must be an array of non-empty strings."
            )
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(
                    f"platform invocation payload field '{logical_name}' must be an array of non-empty strings."
                )
            normalized.append(item.strip())
        return tuple(normalized)
    return ()


def _optional_payload_mapping(
    payload: Mapping[str, object],
    logical_name: str,
    *field_names: str,
) -> Mapping[str, object]:
    for field_name in field_names:
        if field_name not in payload:
            continue
        value = payload[field_name]
        if not isinstance(value, Mapping):
            raise ValueError(
                f"platform invocation payload field '{logical_name}' must be an object."
            )
        return dict(value)
    return {}
