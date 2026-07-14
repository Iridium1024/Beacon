from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

EmbeddingVector = tuple[float, ...]


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """A semantic record stored by a memory subsystem."""

    record_id: str
    namespace: str
    content: str
    embedding: EmbeddingVector | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    """Lookup contract for memory retrieval."""

    namespace: str
    text: str | None = None
    vector: EmbeddingVector | None = None
    top_k: int = 5
    filters: Mapping[str, object] = field(default_factory=dict)


class Memory(ABC):
    """Abstract contract for persistent and vector-aware memory."""

    @abstractmethod
    async def store(self, record: MemoryRecord) -> None:
        ...

    @abstractmethod
    async def retrieve(self, query: MemoryQuery) -> tuple[MemoryRecord, ...]:
        ...

    @abstractmethod
    async def embed(self, inputs: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        ...
