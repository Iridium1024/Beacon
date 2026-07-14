from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from agent_os.memory.memory_interface import EmbeddingVector


@dataclass(frozen=True, slots=True)
class EmbeddingMetadata:
    """Describes the embedding provider exposed to session memory."""

    provider_name: str
    model_name: str
    dimensions: int | None = None
    capabilities: Mapping[str, object] = field(default_factory=dict)


class EmbeddingInterface(ABC):
    """Abstract embedding contract used by vector-backed memory services."""

    @abstractmethod
    async def embed(self, inputs: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        ...

    @abstractmethod
    def metadata(self) -> EmbeddingMetadata:
        ...
