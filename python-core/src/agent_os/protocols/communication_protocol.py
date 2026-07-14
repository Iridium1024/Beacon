"""Backward-compatible re-exports for the communication protocol layer."""

from agent_os.protocols.final_answer_candidate import (
    FinalAnswerCandidate,
    FinalAnswerCandidateStatus,
)
from agent_os.protocols.message import CommunicationMessage, DeliveryMode, EmbeddingVector
from agent_os.protocols.protocol import CommunicationProtocol, ProtocolCapabilities, ProtocolEnvelope
from agent_os.protocols.shared_context import ContextPartition, ContextSnapshot, SharedContext

__all__ = [
    "CommunicationMessage",
    "CommunicationProtocol",
    "ContextPartition",
    "ContextSnapshot",
    "DeliveryMode",
    "EmbeddingVector",
    "FinalAnswerCandidate",
    "FinalAnswerCandidateStatus",
    "ProtocolCapabilities",
    "ProtocolEnvelope",
    "SharedContext",
]
