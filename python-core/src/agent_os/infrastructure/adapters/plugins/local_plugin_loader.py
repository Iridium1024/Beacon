from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from agent_os.domain.entities.plugin import PluginExecutionContext, PluginManifest
from agent_os.domain.ports.plugin_runtime import PluginRuntimePort


@dataclass(slots=True)
class LocalPluginLoader(PluginRuntimePort):
    """Placeholder adapter for local plugin discovery and execution."""

    plugins_directory: str

    async def discover(self) -> tuple[PluginManifest, ...]:
        raise NotImplementedError("Plugin discovery is intentionally undefined in this scaffold.")

    async def invoke(self, context: PluginExecutionContext) -> Mapping[str, object]:
        raise NotImplementedError("Plugin hook execution is intentionally undefined in this scaffold.")
