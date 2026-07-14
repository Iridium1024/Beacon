from __future__ import annotations

from collections.abc import Mapping

from agent_os.domain.ports.protocol import ProtocolEnvelope
from agent_os.protocols.heartbeat_terminal_export_contract import (
    HEARTBEAT_TERMINAL_PROTOCOL_KIND,
    HEARTBEAT_TERMINAL_PROTOCOL_VERSION,
    assert_heartbeat_terminal_protocol_envelope_contract,
)
from agent_os.orchestrator.heartbeat_terminal_export import (
    HeartbeatTerminalExportPayload,
    serialize_heartbeat_terminal_export,
    validate_heartbeat_terminal_export_payload,
)


def build_heartbeat_terminal_protocol_envelope(
    export_payload: HeartbeatTerminalExportPayload,
    *,
    request_id: str,
    kind: str = HEARTBEAT_TERMINAL_PROTOCOL_KIND,
    protocol_version: str = HEARTBEAT_TERMINAL_PROTOCOL_VERSION,
    metadata: Mapping[str, str] | None = None,
) -> ProtocolEnvelope:
    """Wrap one canonical heartbeat terminal export in the transport-neutral protocol envelope."""

    if not isinstance(export_payload, HeartbeatTerminalExportPayload):
        raise TypeError(
            "Heartbeat terminal protocol envelope requires HeartbeatTerminalExportPayload. "
            "Boundary consumers must use build_heartbeat_terminal_export(...) before transport."
        )
    validate_heartbeat_terminal_export_payload(export_payload)
    envelope = ProtocolEnvelope(
        protocol_version=_normalize_required_text(protocol_version, field_name="protocol_version"),
        request_id=_normalize_required_text(request_id, field_name="request_id"),
        kind=_normalize_required_text(kind, field_name="kind"),
        payload=serialize_heartbeat_terminal_export(export_payload),
        metadata=_normalize_string_mapping(metadata),
    )
    assert_heartbeat_terminal_protocol_envelope_contract(envelope)
    return envelope


def _normalize_required_text(value: object, *, field_name: str) -> str:
    normalized_value = str(value).strip()
    if not normalized_value:
        raise ValueError(
            f"Heartbeat terminal protocol envelope requires non-empty {field_name}."
        )
    return normalized_value


def _normalize_string_mapping(metadata: Mapping[str, str] | None) -> Mapping[str, str]:
    if metadata is None:
        return {}
    normalized_metadata: dict[str, str] = {}
    for key, value in metadata.items():
        normalized_key = str(key).strip()
        if not normalized_key:
            raise ValueError(
                "Heartbeat terminal protocol envelope metadata keys must be non-empty strings."
            )
        normalized_metadata[normalized_key] = str(value)
    return normalized_metadata
