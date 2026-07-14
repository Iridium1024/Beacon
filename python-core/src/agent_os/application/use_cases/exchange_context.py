from __future__ import annotations

from dataclasses import dataclass

from agent_os.application.dto.requests import ContextExchangeInput
from agent_os.domain.entities.memory import ContextPacket
from agent_os.domain.ports.vector_memory import VectorMemoryPort


@dataclass(slots=True)
class ExchangeContext:
    """Use-case shell for compressed cross-agent context handoff."""

    vector_memory: VectorMemoryPort

    async def execute(self, request: ContextExchangeInput) -> ContextPacket:
        raise NotImplementedError("Context exchange is intentionally undefined in this scaffold.")
