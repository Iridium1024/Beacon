from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field

from agent_os.protocols.final_answer_candidate import FinalAnswerCandidate
from agent_os.protocols.message import CommunicationMessage
from agent_os.protocols.shared_context import SharedContext


@dataclass(frozen=True, slots=True)
class ProtocolCapabilities:
    """Describes blackboard-oriented capabilities exposed by a communication protocol."""

    supports_direct_communication: bool = True
    supports_broadcast_mode: bool = True
    supports_multicast_mode: bool = False
    supports_shared_context: bool = True
    supports_canonical_discussion_messages: bool = True
    supports_canonical_final_answer_candidates: bool = True
    supports_summary_channel: bool = True
    supports_semantic_channel: bool = True
    treats_vectors_as_auxiliary_representation: bool = True


@dataclass(frozen=True, slots=True)
class ProtocolEnvelope:
    """Transport-neutral wrapper for canonical discussion state updates.

    This envelope carries explicit semantic objects across runtime boundaries.
    Vector or embedding fields remain supplemental when present.
    """

    protocol_name: str
    protocol_version: str
    message: CommunicationMessage
    metadata: Mapping[str, object] = field(default_factory=dict)


class CommunicationProtocol(ABC):
    """Abstract protocol for serializing shared state updates in a blackboard model.

    This protocol abstraction is not responsible for routing messages between agents.
    Its role is limited to validating, encoding, and decoding explicit
    shared-context updates, where broadcast is the primary communication mode
    and direct delivery remains available only for compatibility and future
    extension.

    Canonical semantic objects:
    - `CommunicationMessage` for discussion-round state updates
    - `FinalAnswerCandidate` for checkpoint / heartbeat evaluation surfaces

    Auxiliary representations:
    - `embedding_vector` on messages
    - vector-memory implementations attached to shared context

    Auxiliary vector representations may assist retrieval or similarity
    operations, but checkpoint, freeze, self-check, voting, dispatcher, and
    report flows must consume explicit semantic objects directly.
    """

    @property
    @abstractmethod
    def protocol_name(self) -> str:
        ...

    @property
    @abstractmethod
    def protocol_version(self) -> str:
        ...

    @property
    def message_schema(self) -> type[CommunicationMessage]:
        return CommunicationMessage

    @property
    def checkpoint_object_schema(self) -> type[FinalAnswerCandidate]:
        """Canonical schema for checkpoint evaluation objects."""

        return FinalAnswerCandidate

    @property
    def shared_context_schema(self) -> type[SharedContext]:
        return SharedContext

    @property
    @abstractmethod
    def capabilities(self) -> ProtocolCapabilities:
        """Feature flags describing how the protocol represents shared-context updates."""
        ...

    @abstractmethod
    def validate(self, message: CommunicationMessage) -> None:
        """Validate a shared-context state update before serialization or acceptance."""
        ...

    @abstractmethod
    def encode(self, message: CommunicationMessage) -> ProtocolEnvelope:
        """Encode a shared-context state update into a transport-neutral envelope."""
        ...

    @abstractmethod
    def decode(self, envelope: ProtocolEnvelope) -> CommunicationMessage:
        """Decode a transport envelope back into a shared-context state update."""
        ...
