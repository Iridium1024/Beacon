from __future__ import annotations

from typing import Protocol

from agent_os.domain.entities.agent import AgentDefinition
from agent_os.domain.value_objects.identifiers import AgentId


class AgentRegistryPort(Protocol):
    """Repository-like contract for agent registration and lookup."""

    async def register(self, agent: AgentDefinition) -> None:
        ...

    async def get(self, agent_id: AgentId) -> AgentDefinition | None:
        ...

    async def list(self) -> tuple[AgentDefinition, ...]:
        ...

    async def find_by_capability(self, capability_name: str) -> tuple[AgentDefinition, ...]:
        ...
