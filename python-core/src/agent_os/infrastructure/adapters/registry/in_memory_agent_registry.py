from __future__ import annotations

from dataclasses import dataclass

from agent_os.domain.entities.agent import AgentDefinition
from agent_os.domain.ports.agent_registry import AgentRegistryPort
from agent_os.domain.value_objects.identifiers import AgentId


@dataclass(slots=True)
class InMemoryAgentRegistry(AgentRegistryPort):
    """Placeholder adapter for a runtime-local agent registry."""

    namespace: str = "default"

    async def register(self, agent: AgentDefinition) -> None:
        raise NotImplementedError("Agent registration storage is intentionally undefined in this scaffold.")

    async def get(self, agent_id: AgentId) -> AgentDefinition | None:
        raise NotImplementedError("Agent lookup is intentionally undefined in this scaffold.")

    async def list(self) -> tuple[AgentDefinition, ...]:
        raise NotImplementedError("Agent listing is intentionally undefined in this scaffold.")

    async def find_by_capability(self, capability_name: str) -> tuple[AgentDefinition, ...]:
        raise NotImplementedError("Capability lookup is intentionally undefined in this scaffold.")
