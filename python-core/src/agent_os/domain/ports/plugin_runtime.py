from __future__ import annotations

from typing import Mapping, Protocol

from agent_os.domain.entities.plugin import PluginExecutionContext, PluginManifest


class PluginRuntimePort(Protocol):
    """Contract for plugin discovery and hook execution."""

    async def discover(self) -> tuple[PluginManifest, ...]:
        ...

    async def invoke(self, context: PluginExecutionContext) -> Mapping[str, object]:
        ...
