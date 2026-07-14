"""Model adapter placeholders and deterministic test providers."""

from agent_os.infrastructure.adapters.models.anthropic_adapter import (
    AnthropicMessagesAdapter,
)
from agent_os.infrastructure.adapters.models.deterministic_provider import (
    DeterministicModelProvider,
)
from agent_os.infrastructure.adapters.models.gemini_adapter import (
    GeminiGenerateContentAdapter,
)
from agent_os.infrastructure.adapters.models.local_model_adapter import LocalModelAdapter
from agent_os.infrastructure.adapters.models.ollama_adapter import OllamaChatAdapter
from agent_os.infrastructure.adapters.models.openai_adapter import OpenAIAdapter
from agent_os.infrastructure.adapters.models.openai_responses_adapter import (
    OpenAIResponsesAdapter,
)
from agent_os.infrastructure.adapters.models.remote_http_adapter import (
    RemoteHttpModelAdapter,
)

__all__ = (
    "AnthropicMessagesAdapter",
    "DeterministicModelProvider",
    "GeminiGenerateContentAdapter",
    "LocalModelAdapter",
    "OllamaChatAdapter",
    "OpenAIAdapter",
    "OpenAIResponsesAdapter",
    "RemoteHttpModelAdapter",
)
