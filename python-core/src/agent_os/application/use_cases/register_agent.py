from __future__ import annotations

from dataclasses import dataclass

from agent_os.application.dto.requests import AgentRegistrationInput
from agent_os.domain.ports.agent_registry import AgentRegistryPort


@dataclass(slots=True)
class RegisterAgent:
    """Use-case shell for adding agents to the registry."""

    agent_registry: AgentRegistryPort

    async def execute(self, request: AgentRegistrationInput) -> None:
        raise NotImplementedError("Agent registration is intentionally undefined in this scaffold.")
