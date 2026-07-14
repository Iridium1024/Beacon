from __future__ import annotations

from dataclasses import dataclass

from agent_os.domain.ports.protocol import ProtocolAdapter, ProtocolEnvelope
from agent_os.domain.value_objects.enums import ProtocolKind


@dataclass(slots=True)
class JsonRpcProtocolAdapter(ProtocolAdapter):
    """Placeholder adapter for JSON-RPC serialization."""

    protocol_version: str = "1.0"

    @property
    def kind(self) -> ProtocolKind:
        return ProtocolKind.JSON_RPC

    def encode(self, envelope: ProtocolEnvelope) -> str:
        raise NotImplementedError("JSON-RPC encoding is intentionally undefined in this scaffold.")

    def decode(self, raw_message: str) -> ProtocolEnvelope:
        raise NotImplementedError("JSON-RPC decoding is intentionally undefined in this scaffold.")
