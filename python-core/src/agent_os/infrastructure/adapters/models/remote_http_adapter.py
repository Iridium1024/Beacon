from __future__ import annotations

from dataclasses import dataclass

from agent_os.domain.entities.model import EmbeddingRequest, EmbeddingResult, ModelInvocation, ModelOutput
from agent_os.domain.ports.model_provider import ModelProviderPort


@dataclass(slots=True)
class RemoteHttpModelAdapter(ModelProviderPort):
    """Placeholder adapter for arbitrary HTTP-based model providers."""

    endpoint_url: str

    async def generate(self, request: ModelInvocation) -> ModelOutput:
        raise NotImplementedError("Remote HTTP generation is intentionally undefined in this scaffold.")

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        raise NotImplementedError("Remote HTTP embeddings are intentionally undefined in this scaffold.")

    async def list_models(self) -> tuple[str, ...]:
        raise NotImplementedError("Remote HTTP model discovery is intentionally undefined in this scaffold.")
