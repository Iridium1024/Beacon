from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from math import sqrt

from agent_os.memory.memory_interface import EmbeddingVector, MemoryQuery, MemoryRecord


@dataclass(frozen=True, slots=True)
class SimilarityMatch:
    """A scored result returned from vector similarity search."""

    record: MemoryRecord
    score: float


@dataclass(frozen=True, slots=True)
class ContextRequest:
    """Request for session-scoped context retrieval."""

    namespace: str
    session_id: str
    limit: int = 10
    metadata_filters: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ContextWindow:
    """Session-scoped memory window used for context reconstruction."""

    session_id: str
    records: tuple[MemoryRecord, ...]
    metadata: Mapping[str, object] = field(default_factory=dict)


class VectorStore(ABC):
    """Abstract vector-store contract with similarity search and context retrieval."""

    @abstractmethod
    async def upsert(self, record: MemoryRecord) -> None:
        ...

    @abstractmethod
    async def get_many(self, record_ids: Sequence[str]) -> tuple[MemoryRecord, ...]:
        ...

    @abstractmethod
    async def similarity_search(self, query: MemoryQuery) -> tuple[SimilarityMatch, ...]:
        ...

    @abstractmethod
    async def retrieve_context(self, request: ContextRequest) -> ContextWindow:
        ...


@dataclass(slots=True)
class InMemoryVectorStore(VectorStore):
    """Local in-memory vector store placeholder with no external DB dependency."""

    records: dict[str, MemoryRecord] = field(default_factory=dict)
    session_index: dict[tuple[str, str], list[str]] = field(default_factory=dict)

    async def upsert(self, record: MemoryRecord) -> None:
        self.records[record.record_id] = record

        session_id = record.metadata.get("session_id")
        if isinstance(session_id, str) and session_id:
            key = (record.namespace, session_id)
            bucket = self.session_index.setdefault(key, [])
            if record.record_id in bucket:
                bucket.remove(record.record_id)
            bucket.append(record.record_id)

    async def get_many(self, record_ids: Sequence[str]) -> tuple[MemoryRecord, ...]:
        return tuple(
            self.records[record_id]
            for record_id in record_ids
            if record_id in self.records
        )

    async def similarity_search(self, query: MemoryQuery) -> tuple[SimilarityMatch, ...]:
        if query.vector is None:
            return ()

        matches: list[SimilarityMatch] = []
        for record in self.records.values():
            if record.namespace != query.namespace:
                continue
            if record.embedding is None:
                continue
            if not self._matches_filters(record, query.filters):
                continue

            score = self._cosine_similarity(record.embedding, query.vector)
            matches.append(SimilarityMatch(record=record, score=score))

        matches.sort(key=lambda match: match.score, reverse=True)
        return tuple(matches[: query.top_k])

    async def retrieve_context(self, request: ContextRequest) -> ContextWindow:
        key = (request.namespace, request.session_id)
        record_ids = self.session_index.get(key, [])
        recent_ids = record_ids[-request.limit :]
        records = tuple(
            record
            for record in await self.get_many(recent_ids)
            if self._matches_filters(record, request.metadata_filters)
        )

        return ContextWindow(
            session_id=request.session_id,
            records=records,
            metadata={
                "namespace": request.namespace,
                "record_count": len(records),
            },
        )

    def _matches_filters(self, record: MemoryRecord, filters: Mapping[str, object]) -> bool:
        for key, expected in filters.items():
            if record.metadata.get(key) != expected:
                return False
        return True

    def _cosine_similarity(self, left: EmbeddingVector, right: EmbeddingVector) -> float:
        if len(left) != len(right) or not left:
            return 0.0

        left_norm = sqrt(sum(value * value for value in left))
        right_norm = sqrt(sum(value * value for value in right))
        if left_norm == 0.0 or right_norm == 0.0:
            return 0.0

        dot_product = sum(l_value * r_value for l_value, r_value in zip(left, right))
        return dot_product / (left_norm * right_norm)
