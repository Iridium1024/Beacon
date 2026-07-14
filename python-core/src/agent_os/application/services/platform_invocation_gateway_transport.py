from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from agent_os.application.services.platform_invocation_gateway_handler import (
    PlatformInvocationGatewayHandler,
)
from agent_os.domain.ports.protocol import ProtocolEnvelope


@dataclass(frozen=True, slots=True)
class PlatformInvocationGatewayTransportAdapter:
    """Dict-level adapter for Gateway-style platform invocation envelopes."""

    handler: PlatformInvocationGatewayHandler = field(
        default_factory=PlatformInvocationGatewayHandler
    )

    def handle_gateway_envelope(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        response = self.handler.handle(self.parse_gateway_envelope(envelope))
        return self.serialize_gateway_envelope(response)

    def parse_gateway_envelope(self, envelope: Mapping[str, object]) -> ProtocolEnvelope:
        return ProtocolEnvelope(
            protocol_version=_required_text(envelope, "protocolVersion"),
            request_id=_required_text(envelope, "requestId"),
            kind=_required_text(envelope, "kind"),
            payload=_required_mapping(envelope, "payload"),
            metadata=_optional_string_mapping(envelope, "metadata"),
        )

    def serialize_gateway_envelope(self, envelope: ProtocolEnvelope) -> Mapping[str, object]:
        return {
            "protocolVersion": envelope.protocol_version,
            "requestId": envelope.request_id,
            "kind": envelope.kind,
            "payload": dict(envelope.payload),
            "metadata": dict(envelope.metadata),
        }


def _required_text(envelope: Mapping[str, object], field_name: str) -> str:
    value = envelope.get(field_name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"gateway envelope field '{field_name}' must be a non-empty string.")
    return value


def _required_mapping(
    envelope: Mapping[str, object], field_name: str
) -> Mapping[str, object]:
    value = envelope.get(field_name)
    if not isinstance(value, Mapping):
        raise ValueError(f"gateway envelope field '{field_name}' must be an object.")
    return dict(value)


def _optional_string_mapping(
    envelope: Mapping[str, object], field_name: str
) -> Mapping[str, str]:
    value = envelope.get(field_name, {})
    if not isinstance(value, Mapping):
        raise ValueError(f"gateway envelope field '{field_name}' must be an object.")

    metadata: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ValueError(
                f"gateway envelope field '{field_name}' must contain string keys and values."
            )
        metadata[key] = item
    return metadata
