"""Composition root contracts for the Agent OS Python core."""

from __future__ import annotations

from dataclasses import dataclass

from agent_os.domain.ports.agent_registry import AgentRegistryPort
from agent_os.domain.ports.filesystem import FilesystemPort
from agent_os.domain.ports.model_provider import ModelProviderPort
from agent_os.domain.ports.orchestrator import OrchestratorPort
from agent_os.domain.ports.plugin_runtime import PluginRuntimePort
from agent_os.domain.ports.protocol import ProtocolAdapter
from agent_os.domain.ports.vector_memory import VectorMemoryPort


@dataclass(frozen=True, slots=True)
class CoreDependencies:
    """Container describing the replaceable runtime dependencies."""

    agent_registry: AgentRegistryPort
    filesystem: FilesystemPort
    model_provider: ModelProviderPort
    orchestrator: OrchestratorPort
    plugin_runtime: PluginRuntimePort
    protocol_adapter: ProtocolAdapter
    vector_memory: VectorMemoryPort


def build_core() -> CoreDependencies:
    """Wire concrete adapters into the orchestration core."""

    raise NotImplementedError("Core composition is intentionally undefined in this scaffold.")
