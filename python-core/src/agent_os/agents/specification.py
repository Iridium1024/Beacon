from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from agent_os.memory.memory_interface import Memory
from agent_os.tools.tool_interface import Tool


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Transport-safe configuration used to instantiate an agent."""

    agent_id: str
    role: str
    name: str
    model_name: str
    model_adapter_alias: str
    memory_namespace: str
    description: str = ""
    tool_names: tuple[str, ...] = ()
    parent_agent_id: str | None = None
    child_agent_ids: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentConfigBundle:
    """Container for one or more agent configurations."""

    agents: tuple[AgentConfig, ...]
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentDependencies:
    """Per-agent dependency bundle injected at construction time."""

    memory: Memory
    tools: Mapping[str, Tool]
    model_access: "ModelAccess"


AgentFactory = Callable[[AgentConfig, AgentDependencies], "BaseAgent"]
