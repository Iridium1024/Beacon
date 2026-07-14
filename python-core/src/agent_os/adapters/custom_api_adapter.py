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
class CustomAPIAdapter(ModelAdapter):
    """Placeholder adapter for arbitrary external model APIs."""

    endpoint_url: str = "https://placeholder.invalid/api"
    protocol_name: str = "http-json"
    default_model_name: str = "custom-api-placeholder"

    async def generate(self, request: ModelGenerateRequest) -> ModelGenerateResponse:
        return ModelGenerateResponse(
            model_name=request.model_name or self.default_model_name,
            content="",
            metadata={
                "status": "placeholder",
                "adapter": "custom-api",
                "endpoint_url": self.endpoint_url,
                "protocol_name": self.protocol_name,
            },
        )

    async def stream(self, request: ModelGenerateRequest) -> AsyncIterator[ModelStreamChunk]:
        yield ModelStreamChunk(
            delta="",
            is_terminal=True,
            metadata={
                "status": "placeholder",
                "adapter": "custom-api",
                "model_name": request.model_name or self.default_model_name,
            },
        )

    def metadata(self) -> ModelAdapterMetadata:
        return ModelAdapterMetadata(
            adapter_name=self.__class__.__name__,
            provider_name="custom-api",
            supported_models=(self.default_model_name,),
            capabilities={"streaming": True, "network_calls": False},
        )
