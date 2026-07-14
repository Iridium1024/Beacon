from __future__ import annotations

from agent_os.adapters.custom_api_adapter import CustomAPIAdapter
from agent_os.adapters.local_llm_adapter import LocalLLMAdapter
from agent_os.adapters.openai_adapter import OpenAIAdapter
from agent_os.adapters.registry import AdapterRegistry


def register_builtin_adapters(registry: AdapterRegistry) -> AdapterRegistry:
    """Register the built-in placeholder model adapters."""

    registry.register("openai", OpenAIAdapter)
    registry.register("local-llm", LocalLLMAdapter)
    registry.register("custom-api", CustomAPIAdapter)
    return registry


def create_default_registry() -> AdapterRegistry:
    """Create a registry pre-populated with the built-in placeholder adapters."""

    return register_builtin_adapters(AdapterRegistry())
