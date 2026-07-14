from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ModelInputMessage:
    """Provider-neutral input message for generation requests."""

    role: str
    content: str
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelGenerateRequest:
    """Provider-neutral generation request contract."""

    model_name: str
    messages: Sequence[ModelInputMessage]
    system_prompt: str | None = None
    parameters: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelGenerateResponse:
    """Provider-neutral generation response contract."""

    model_name: str
    content: str
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelStreamChunk:
    """A single streamed generation fragment."""

    delta: str
    is_terminal: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelAdapterMetadata:
    """Static or runtime metadata describing the adapter."""

    adapter_name: str
    provider_name: str
    supported_models: Sequence[str] = ()
    capabilities: Mapping[str, object] = field(default_factory=dict)


class ModelAdapter(ABC):
    """Abstract contract for any model provider integration."""

    @abstractmethod
    async def generate(self, request: ModelGenerateRequest) -> ModelGenerateResponse:
        ...

    @abstractmethod
    async def stream(self, request: ModelGenerateRequest) -> AsyncIterator[ModelStreamChunk]:
        ...

    @abstractmethod
    def metadata(self) -> ModelAdapterMetadata:
        ...
