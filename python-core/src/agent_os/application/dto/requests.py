from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from agent_os.domain.value_objects.enums import ExecutionMode
from agent_os.domain.value_objects.identifiers import AgentId, WorkflowId


@dataclass(frozen=True, slots=True)
class WorkflowSubmission:
    """Input DTO for submitting a new workflow request."""

    goal: str
    execution_mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    entry_agent_id: AgentId | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentRegistrationInput:
    """Input DTO for adding an agent to the registry."""

    agent_id: AgentId
    name: str
    description: str
    capabilities: tuple[str, ...]
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ContextExchangeInput:
    """Input DTO for generating a compressed handoff packet."""

    workflow_id: WorkflowId
    from_agent_id: AgentId
    to_agent_id: AgentId
    objective: str
