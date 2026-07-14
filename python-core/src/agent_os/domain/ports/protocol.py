from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol

from agent_os.domain.value_objects.enums import ProtocolKind


@dataclass(frozen=True, slots=True)
class ProtocolEnvelope:
    """Transport-neutral envelope exchanged across runtime boundaries."""

    protocol_version: str
    request_id: str
    kind: str
    payload: Mapping[str, object]
    metadata: Mapping[str, str] = field(default_factory=dict)


class ProtocolAdapter(Protocol):
    """Contract for translating envelopes to and from concrete transport formats."""

    @property
    def kind(self) -> ProtocolKind:
        ...

    def encode(self, envelope: ProtocolEnvelope) -> str:
        ...

    def decode(self, raw_message: str) -> ProtocolEnvelope:
        ...
