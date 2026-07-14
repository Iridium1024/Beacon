from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

EmbeddingVector = tuple[float, ...]


class DeliveryMode(StrEnum):
    """Addressing modes supported by the communication contract."""

    DIRECT = "direct"
    BROADCAST = "broadcast"
    MULTICAST = "multicast"


@dataclass(frozen=True, slots=True)
class CommunicationMessage:
    """Canonical semantic object for discussion-round shared-context updates.

    `summary_text` is the explicit semantic payload used by both humans and
    orchestration logic. `embedding_vector` is optional auxiliary
    representation only. It may support retrieval, compression, clustering, or
    similarity lookup, but it is not the authoritative control surface for
    checkpoint, freeze, voting, or reporting.
    """

    id: str
    sender: str
    summary_text: str = field(metadata={"canonical_semantic_payload": True})
    receiver: str | None = field(default=None, metadata={"deprecated": True})
    receivers: list[str] | None = None
    embedding_vector: EmbeddingVector | None = field(
        default=None,
        metadata={"auxiliary_representation": True},
    )
    metadata: Mapping[str, object] = field(default_factory=dict)
    delivery_mode: DeliveryMode = DeliveryMode.BROADCAST

    @property
    def is_canonical_semantic_object(self) -> bool:
        """Whether this object is the canonical semantic unit for discussion state."""

        return True

    @property
    def message_id(self) -> str:
        """Backward-compatible alias for legacy message identifiers."""

        return self.id

    @property
    def sender_id(self) -> str:
        """Backward-compatible alias for legacy sender naming."""

        return self.sender

    @property
    def recipient_id(self) -> str | None:
        """Deprecated alias for legacy point-to-point receiver naming."""

        return self.receiver

    @property
    def has_summary_channel(self) -> bool:
        """Whether the canonical semantic summary channel is present."""

        return bool(self.summary_text)

    @property
    def has_semantic_channel(self) -> bool:
        """Whether an auxiliary semantic embedding payload is present."""

        return self.embedding_vector is not None
