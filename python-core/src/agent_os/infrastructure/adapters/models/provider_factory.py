from __future__ import annotations

from agent_os.domain.ports.model_provider import ModelProviderPort
from agent_os.infrastructure.adapters.models.anthropic_adapter import (
    AnthropicMessagesAdapter,
)
from agent_os.infrastructure.adapters.models.gemini_adapter import (
    GeminiGenerateContentAdapter,
)
from agent_os.infrastructure.adapters.models.ollama_adapter import OllamaChatAdapter
from agent_os.infrastructure.adapters.models.openai_adapter import OpenAIAdapter
from agent_os.infrastructure.adapters.models.openai_responses_adapter import (
    OpenAIResponsesAdapter,
)
from agent_os.domain.entities.provider_connection import (
    ProviderApiShape,
    ProviderConnectionConfigError,
    ProviderConnectionSpec,
)


class ProviderAdapterUnsupportedError(NotImplementedError):
    """Raised when a provider API shape has no executable adapter yet."""


def build_model_provider_from_connection_spec(
    spec: ProviderConnectionSpec,
) -> ModelProviderPort:
    """Build an executable model provider from a credential-safe connection spec."""

    if spec.api_shape is ProviderApiShape.OPENAI_CHAT_COMPLETIONS:
        credential_env_var = _credential_env_var_or_raise(spec)
        return OpenAIAdapter(
            api_base_url=spec.base_url,
            provider_name=spec.provider_name,
            model_name=spec.model_name,
            api_key_env_var=credential_env_var,
            timeout_seconds=spec.timeout_seconds,
            default_parameters=spec.parameters,
        )
    if spec.api_shape is ProviderApiShape.OPENAI_RESPONSES:
        credential_env_var = _credential_env_var_or_raise(spec)
        return OpenAIResponsesAdapter(
            api_base_url=spec.base_url,
            provider_name=spec.provider_name,
            model_name=spec.model_name,
            api_key_env_var=credential_env_var,
            timeout_seconds=spec.timeout_seconds,
            default_parameters=spec.parameters,
        )
    if spec.api_shape is ProviderApiShape.ANTHROPIC_MESSAGES:
        credential_env_var = _credential_env_var_or_raise(spec)
        return AnthropicMessagesAdapter(
            api_base_url=spec.base_url,
            provider_name=spec.provider_name,
            model_name=spec.model_name,
            api_key_env_var=credential_env_var,
            timeout_seconds=spec.timeout_seconds,
            default_parameters=spec.parameters,
        )
    if spec.api_shape is ProviderApiShape.GEMINI_GENERATE_CONTENT:
        credential_env_var = _credential_env_var_or_raise(spec)
        return GeminiGenerateContentAdapter(
            api_base_url=spec.base_url,
            provider_name=spec.provider_name,
            model_name=spec.model_name,
            api_key_env_var=credential_env_var,
            timeout_seconds=spec.timeout_seconds,
            default_parameters=spec.parameters,
        )
    if spec.api_shape is ProviderApiShape.OLLAMA_CHAT:
        return OllamaChatAdapter(
            api_base_url=spec.base_url,
            provider_name=spec.provider_name,
            model_name=spec.model_name,
            timeout_seconds=spec.timeout_seconds,
            default_parameters=spec.parameters,
        )
    raise ProviderAdapterUnsupportedError(
        "provider api shape is not executable in the local runtime: "
        f"{spec.api_shape.value}."
    )


def _credential_env_var_or_raise(spec: ProviderConnectionSpec) -> str:
    if spec.credential_env_var is None or not spec.credential_env_var.strip():
        raise ProviderConnectionConfigError(
            "credential_env_var must be set for this provider api shape."
        )
    return spec.credential_env_var
