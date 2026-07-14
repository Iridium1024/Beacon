from __future__ import annotations

from typing import Protocol

from agent_os.domain.entities.memory import ContextPacket, MemoryQuery, MemoryRecord


class VectorMemoryPort(Protocol):
    """Contract for vector-backed memory and compressed context generation."""

    async def store(self, record: MemoryRecord) -> None:
        ...

    async def search(self, query: MemoryQuery) -> tuple[MemoryRecord, ...]:
        ...

    async def build_context_packet(self, records: tuple[MemoryRecord, ...]) -> ContextPacket:
        ...
