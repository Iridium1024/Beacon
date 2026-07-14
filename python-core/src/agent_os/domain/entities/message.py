from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from agent_os.domain.value_objects.enums import MessageRole
from agent_os.domain.value_objects.identifiers import AgentId, MemoryId, MessageId


@dataclass(frozen=True, slots=True)
class MessageReference:
    """Links a message payload to supporting memory records."""

    memory_id: MemoryId
    similarity: float | None = None


@dataclass(frozen=True, slots=True)
class MessageEnvelope:
    """Canonical message exchanged between humans, agents, and orchestration services."""

    message_id: MessageId
    sender: AgentId | None
    recipient: AgentId | None
    role: MessageRole
    content: str
    related_memories: tuple[MessageReference, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)
