from __future__ import annotations

from typing import Protocol

from agent_os.domain.entities.model import EmbeddingRequest, EmbeddingResult, ModelInvocation, ModelOutput


class ModelProviderPort(Protocol):
    """Vendor-neutral contract for generation and embedding adapters."""

    async def generate(self, request: ModelInvocation) -> ModelOutput:
        ...

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        ...

    async def list_models(self) -> tuple[str, ...]:
        ...
