from __future__ import annotations

from dataclasses import dataclass

from agent_os.domain.entities.model import EmbeddingRequest, EmbeddingResult, ModelInvocation, ModelOutput
from agent_os.domain.ports.model_provider import ModelProviderPort


@dataclass(slots=True)
class LocalModelAdapter(ModelProviderPort):
    """Placeholder adapter for locally hosted model runtimes."""

    runtime_name: str

    async def generate(self, request: ModelInvocation) -> ModelOutput:
        raise NotImplementedError("Local generation is intentionally undefined in this scaffold.")

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        raise NotImplementedError("Local embeddings are intentionally undefined in this scaffold.")

    async def list_models(self) -> tuple[str, ...]:
        raise NotImplementedError("Local model discovery is intentionally undefined in this scaffold.")
