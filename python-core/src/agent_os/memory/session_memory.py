from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from uuid import uuid4

from agent_os.memory.embedding_interface import EmbeddingInterface
from agent_os.memory.memory_interface import Memory, MemoryQuery, MemoryRecord
from agent_os.memory.vector_store import ContextRequest, ContextWindow, SimilarityMatch, VectorStore


@dataclass(slots=True)
class SessionMemory(Memory):
    """Session-scoped memory service built on a vector store and embedder."""

    vector_store: VectorStore
    embedder: EmbeddingInterface
    default_namespace: str = "default"
    context_limit: int = 10
    session_metadata_key: str = "session_id"

    async def store(self, record: MemoryRecord) -> None:
        stored_record = record
        if record.embedding is None:
            vectors = await self.embed((record.content,))
            stored_record = replace(record, embedding=vectors[0])

        await self.vector_store.upsert(stored_record)

    async def retrieve(self, query: MemoryQuery) -> tuple[MemoryRecord, ...]:
        matches = await self.similarity_search(query)
        return tuple(match.record for match in matches)

    async def embed(self, inputs: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return await self.embedder.embed(tuple(inputs))

    async def similarity_search(self, query: MemoryQuery) -> tuple[SimilarityMatch, ...]:
        resolved_query = query
        if query.vector is None and query.text:
            vectors = await self.embed((query.text,))
            resolved_query = MemoryQuery(
                namespace=query.namespace,
                text=query.text,
                vector=vectors[0],
                top_k=query.top_k,
                filters=query.filters,
            )

        return await self.vector_store.similarity_search(resolved_query)

    async def retrieve_context(
        self,
        session_id: str,
        *,
        namespace: str | None = None,
        limit: int | None = None,
        metadata_filters: dict[str, object] | None = None,
    ) -> ContextWindow:
        return await self.vector_store.retrieve_context(
            ContextRequest(
                namespace=namespace or self.default_namespace,
                session_id=session_id,
                limit=limit or self.context_limit,
                metadata_filters=dict(metadata_filters or {}),
            )
        )

    async def remember(
        self,
        session_id: str,
        content: str,
        *,
        namespace: str | None = None,
        metadata: dict[str, object] | None = None,
        record_id: str | None = None,
    ) -> MemoryRecord:
        record_metadata = dict(metadata or {})
        record_metadata[self.session_metadata_key] = session_id

        record = MemoryRecord(
            record_id=record_id or str(uuid4()),
            namespace=namespace or self.default_namespace,
            content=content,
            metadata=record_metadata,
        )
        await self.store(record)
        stored_records = await self.vector_store.get_many((record.record_id,))
        return stored_records[0] if stored_records else record
