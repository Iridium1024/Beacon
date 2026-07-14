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
class LocalLLMAdapter(ModelAdapter):
    """Placeholder adapter for locally hosted LLM runtimes."""

    runtime_name: str = "local-runtime"
    default_model_name: str = "local-llm-placeholder"

    async def generate(self, request: ModelGenerateRequest) -> ModelGenerateResponse:
        return ModelGenerateResponse(
            model_name=request.model_name or self.default_model_name,
            content="",
            metadata={
                "status": "placeholder",
                "adapter": "local-llm",
                "runtime_name": self.runtime_name,
            },
        )

    async def stream(self, request: ModelGenerateRequest) -> AsyncIterator[ModelStreamChunk]:
        yield ModelStreamChunk(
            delta="",
            is_terminal=True,
            metadata={
                "status": "placeholder",
                "adapter": "local-llm",
                "model_name": request.model_name or self.default_model_name,
            },
        )

    def metadata(self) -> ModelAdapterMetadata:
        return ModelAdapterMetadata(
            adapter_name=self.__class__.__name__,
            provider_name="local",
            supported_models=(self.default_model_name,),
            capabilities={"streaming": True, "network_calls": False},
        )
