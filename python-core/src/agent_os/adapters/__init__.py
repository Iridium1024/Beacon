"""Adapters module placeholders."""

from agent_os.adapters.catalog import create_default_registry, register_builtin_adapters
from agent_os.adapters.custom_api_adapter import CustomAPIAdapter
from agent_os.adapters.dynamic_loader import DynamicAdapterLoader
from agent_os.adapters.local_llm_adapter import LocalLLMAdapter
from agent_os.adapters.model_adapter import (
    ModelAdapter,
    ModelAdapterMetadata,
    ModelGenerateRequest,
    ModelGenerateResponse,
    ModelInputMessage,
    ModelStreamChunk,
)
from agent_os.adapters.openai_adapter import OpenAIAdapter
from agent_os.adapters.registry import AdapterRegistration, AdapterRegistry

__all__ = [
    "AdapterRegistration",
    "AdapterRegistry",
    "CustomAPIAdapter",
    "DynamicAdapterLoader",
    "LocalLLMAdapter",
    "ModelAdapter",
    "ModelAdapterMetadata",
    "ModelGenerateRequest",
    "ModelGenerateResponse",
    "ModelInputMessage",
    "ModelStreamChunk",
    "OpenAIAdapter",
    "create_default_registry",
    "register_builtin_adapters",
]
