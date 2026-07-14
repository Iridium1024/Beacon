from __future__ import annotations

from dataclasses import dataclass
import hashlib

from agent_os.domain.entities.model import (
    EmbeddingRequest,
    EmbeddingResult,
    ModelInvocation,
    ModelOutput,
)
from agent_os.domain.ports.model_provider import ModelProviderPort
from agent_os.domain.value_objects.enums import MessageRole


@dataclass(frozen=True, slots=True)
class DeterministicModelProvider(ModelProviderPort):
    """Deterministic provider for local tests and model-neutral runtime wiring."""

    provider_name: str = "deterministic"
    generation_models: tuple[str, ...] = ("deterministic-text",)
    embedding_models: tuple[str, ...] = ("deterministic-embedding",)
    response_prefix: str = "Deterministic model response"
    vector_dimensions: int = 4

    def __post_init__(self) -> None:
        if not self.provider_name.strip():
            raise ValueError("provider_name must be a non-empty string.")
        if not self.generation_models:
            raise ValueError("generation_models must include at least one model.")
        if not self.embedding_models:
            raise ValueError("embedding_models must include at least one model.")
        if self.vector_dimensions <= 0:
            raise ValueError("vector_dimensions must be positive.")
        for model_name in (*self.generation_models, *self.embedding_models):
            if not model_name.strip():
                raise ValueError("model names must be non-empty strings.")

    async def generate(self, request: ModelInvocation) -> ModelOutput:
        self._require_provider(request.provider_name)
        if request.model_name not in self.generation_models:
            raise ValueError("generation model is not available for this provider.")

        prompt = self._last_user_message(request)
        return ModelOutput(
            model_name=request.model_name,
            content=f"{self.response_prefix}: {prompt}",
            metadata={
                "provider_name": self.provider_name,
                "model_name": request.model_name,
                "deterministic": "true",
            },
        )

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        self._require_provider(request.provider_name)
        if request.model_name not in self.embedding_models:
            raise ValueError("embedding model is not available for this provider.")
        return EmbeddingResult(
            model_name=request.model_name,
            vectors=tuple(self._vector_for_text(item) for item in request.inputs),
        )

    async def list_models(self) -> tuple[str, ...]:
        return (*self.generation_models, *self.embedding_models)

    def _require_provider(self, provider_name: str) -> None:
        if provider_name != self.provider_name:
            raise ValueError("request provider_name does not match this provider.")

    def _last_user_message(self, request: ModelInvocation) -> str:
        for message in reversed(request.messages):
            if message.role == MessageRole.USER:
                return message.content
        if request.messages:
            return request.messages[-1].content
        return ""

    def _vector_for_text(self, text: str) -> tuple[float, ...]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return tuple(
            round(digest[index] / 255.0, 6)
            for index in range(self.vector_dimensions)
        )
