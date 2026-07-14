from __future__ import annotations

from dataclasses import dataclass

from agent_os.domain.entities.memory import ContextPacket, MemoryQuery, MemoryRecord
from agent_os.domain.ports.vector_memory import VectorMemoryPort


@dataclass(slots=True)
class VectorStoreAdapter(VectorMemoryPort):
    """Placeholder adapter for a vector-capable memory backend."""

    backend_name: str

    async def store(self, record: MemoryRecord) -> None:
        raise NotImplementedError("Vector storage is intentionally undefined in this scaffold.")

    async def search(self, query: MemoryQuery) -> tuple[MemoryRecord, ...]:
        raise NotImplementedError("Vector search is intentionally undefined in this scaffold.")

    async def build_context_packet(self, records: tuple[MemoryRecord, ...]) -> ContextPacket:
        raise NotImplementedError("Context compression is intentionally undefined in this scaffold.")
