from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from agent_os.domain.value_objects.enums import PluginHookName
from agent_os.domain.value_objects.identifiers import AgentId, PluginId, WorkflowId


@dataclass(frozen=True, slots=True)
class PluginManifest:
    """Describes a plugin package and the hooks it exposes."""

    plugin_id: PluginId
    name: str
    version: str
    entrypoint: str
    hooks: tuple[PluginHookName, ...]
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PluginExecutionContext:
    """Context passed into plugin hook execution."""

    hook: PluginHookName
    workflow_id: WorkflowId | None = None
    agent_id: AgentId | None = None
    payload: Mapping[str, object] = field(default_factory=dict)
