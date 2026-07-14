from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from agent_os.domain.value_objects.identifiers import MemoryId

EmbeddingVector = tuple[float, ...]


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """A stored semantic memory unit for later retrieval or compression."""

    memory_id: MemoryId
    namespace: str
    content: str
    embedding: EmbeddingVector | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    """A semantic lookup request against a vector memory namespace."""

    namespace: str
    query_text: str
    limit: int = 5
    metadata_filters: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ContextPacket:
    """Compressed handoff payload passed between agents or workflow stages."""

    summary: str
    memory_ids: tuple[MemoryId, ...]
    relevance_hints: Mapping[str, str] = field(default_factory=dict)
