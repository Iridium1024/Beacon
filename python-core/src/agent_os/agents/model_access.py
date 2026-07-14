from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field

from agent_os.adapters.model_adapter import (
    ModelAdapter,
    ModelAdapterMetadata,
    ModelGenerateRequest,
    ModelGenerateResponse,
    ModelInputMessage,
    ModelStreamChunk,
)


@dataclass(slots=True)
class ModelAccess:
    """Agent-facing wrapper that keeps role logic decoupled from adapter details."""

    adapter: ModelAdapter
    model_name: str
    default_parameters: Mapping[str, object] = field(default_factory=dict)

    def metadata(self) -> ModelAdapterMetadata:
        return self.adapter.metadata()

    def build_request(
        self,
        messages: Sequence[ModelInputMessage],
        *,
        system_prompt: str | None = None,
        parameters: Mapping[str, object] | None = None,
    ) -> ModelGenerateRequest:
        merged_parameters = dict(self.default_parameters)
        if parameters is not None:
            merged_parameters.update(parameters)

        return ModelGenerateRequest(
            model_name=self.model_name,
            messages=tuple(messages),
            system_prompt=system_prompt,
            parameters=merged_parameters,
        )

    async def generate(
        self,
        messages: Sequence[ModelInputMessage],
        *,
        system_prompt: str | None = None,
        parameters: Mapping[str, object] | None = None,
    ) -> ModelGenerateResponse:
        request = self.build_request(messages, system_prompt=system_prompt, parameters=parameters)
        return await self.adapter.generate(request)

    async def stream(
        self,
        messages: Sequence[ModelInputMessage],
        *,
        system_prompt: str | None = None,
        parameters: Mapping[str, object] | None = None,
    ) -> AsyncIterator[ModelStreamChunk]:
        request = self.build_request(messages, system_prompt=system_prompt, parameters=parameters)
        async for chunk in self.adapter.stream(request):
            yield chunk
