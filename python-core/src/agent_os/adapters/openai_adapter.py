from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from agent_os.adapters.model_adapter import (
    ModelAdapter,
    ModelAdapterMetadata,
    ModelGenerateRequest,
    ModelGenerateResponse,
    ModelStreamChunk,
)


@dataclass(slots=True)
class OpenAIAdapter(ModelAdapter):
    """Placeholder adapter for OpenAI-compatible APIs."""

    api_base_url: str = "https://placeholder.invalid/v1"
    default_model_name: str = "openai-placeholder"

    async def generate(self, request: ModelGenerateRequest) -> ModelGenerateResponse:
        return ModelGenerateResponse(
            model_name=request.model_name or self.default_model_name,
            content="",
            metadata={
                "status": "placeholder",
                "adapter": "openai",
                "api_base_url": self.api_base_url,
            },
        )

    async def stream(self, request: ModelGenerateRequest) -> AsyncIterator[ModelStreamChunk]:
        yield ModelStreamChunk(
            delta="",
            is_terminal=True,
            metadata={
                "status": "placeholder",
                "adapter": "openai",
                "model_name": request.model_name or self.default_model_name,
            },
        )

    def metadata(self) -> ModelAdapterMetadata:
        return ModelAdapterMetadata(
            adapter_name=self.__class__.__name__,
            provider_name="openai",
            supported_models=(self.default_model_name,),
            capabilities={"streaming": True, "network_calls": False},
        )
