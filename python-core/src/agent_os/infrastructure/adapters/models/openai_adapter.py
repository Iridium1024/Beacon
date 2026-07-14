from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import os
from typing import Mapping
from urllib.parse import urljoin, urlparse

from agent_os.domain.entities.model import (
    EmbeddingRequest,
    EmbeddingResult,
    ModelInvocation,
    ModelMessage,
    ModelOutput,
)
from agent_os.domain.ports.model_provider import ModelProviderPort
from agent_os.domain.value_objects.enums import MessageRole
from agent_os.infrastructure.adapters.models.http_json import (
    post_json,
    provider_user_agent,
)


class OpenAICompatibleProviderError(RuntimeError):
    """Stable error for OpenAI-compatible provider failures."""


class OpenAICompatibleProviderConfigError(ValueError):
    """Stable error for invalid OpenAI-compatible provider configuration."""


@dataclass(slots=True)
class OpenAIAdapter(ModelProviderPort):
    """Minimal OpenAI-compatible chat-completions provider adapter."""

    api_base_url: str
    model_name: str
    provider_name: str = "openai-compatible"
    api_key_env_var: str = "AGENT_OS_OPENAI_COMPAT_API_KEY"
    timeout_seconds: float = 30.0
    default_parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.provider_name, "provider_name")
        _require_non_empty(self.model_name, "model_name")
        _require_non_empty(self.api_key_env_var, "api_key_env_var")
        _validate_base_url(self.api_base_url)
        if self.timeout_seconds <= 0:
            raise OpenAICompatibleProviderConfigError(
                "timeout_seconds must be positive."
            )

    async def generate(self, request: ModelInvocation) -> ModelOutput:
        return await asyncio.to_thread(self._generate_blocking, request)

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        raise NotImplementedError(
            "OpenAI-compatible embeddings are not wired in the local runtime."
        )

    async def list_models(self) -> tuple[str, ...]:
        return (self.model_name,)

    def _generate_blocking(self, request: ModelInvocation) -> ModelOutput:
        self._validate_invocation(request)
        api_key = os.environ.get(self.api_key_env_var)
        if api_key is None or not api_key.strip():
            raise OpenAICompatibleProviderConfigError(
                "OpenAI-compatible provider API key environment variable is not set."
            )
        payload = self._request_payload(request)
        response = self._post_chat_completions(
            api_key=api_key,
            payload=payload,
            user_agent=provider_user_agent(
                self.default_parameters,
                request.parameters,
                OpenAICompatibleProviderConfigError,
            ),
        )
        return self._model_output(request=request, response=response)

    def _validate_invocation(self, request: ModelInvocation) -> None:
        if request.provider_name != self.provider_name:
            raise OpenAICompatibleProviderConfigError(
                "request provider_name does not match this provider."
            )
        if request.model_name != self.model_name:
            raise OpenAICompatibleProviderConfigError(
                "request model_name does not match this provider."
            )

    def _request_payload(self, request: ModelInvocation) -> Mapping[str, object]:
        messages = []
        if request.system_prompt is not None:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.extend(_message_payload(message) for message in request.messages)
        return {
            "model": request.model_name,
            "messages": messages,
            **_generation_parameters(
                self.default_parameters,
                request.parameters,
            ),
        }

    def _post_chat_completions(
        self,
        *,
        api_key: str,
        payload: Mapping[str, object],
        user_agent: str | None,
    ) -> Mapping[str, object]:
        url = urljoin(self.api_base_url.rstrip("/") + "/", "chat/completions")
        return post_json(
            url=url,
            payload=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
            },
            timeout_seconds=self.timeout_seconds,
            provider_label="OpenAI-compatible provider",
            error_type=OpenAICompatibleProviderError,
            user_agent=user_agent,
        )

    def _model_output(
        self,
        *,
        request: ModelInvocation,
        response: Mapping[str, object],
    ) -> ModelOutput:
        content, finish_reason = _first_choice_content(response)
        response_model = response.get("model")
        model_name = response_model if isinstance(response_model, str) else request.model_name
        metadata: dict[str, str] = {
            "provider_name": self.provider_name,
            "model_name": model_name,
            "openai_compatible": "true",
        }
        if finish_reason is not None:
            metadata["finish_reason"] = finish_reason
        metadata.update(_usage_metadata(response.get("usage")))
        return ModelOutput(
            model_name=model_name,
            content=content,
            metadata=metadata,
        )


_ALLOWED_GENERATION_PARAMETERS = {
    "temperature",
    "max_tokens",
    "top_p",
    "presence_penalty",
    "frequency_penalty",
    "reasoning_effort",
    "stop",
    "thinking",
}


def _generation_parameters(
    defaults: Mapping[str, object],
    request_parameters: Mapping[str, object],
) -> Mapping[str, object]:
    result: dict[str, object] = {}
    for source in (defaults, request_parameters):
        for key, value in source.items():
            if key in _ALLOWED_GENERATION_PARAMETERS and value is not None:
                result[key] = value
    return result


def _message_payload(message: ModelMessage) -> Mapping[str, str]:
    return {
        "role": _message_role(message.role),
        "content": message.content,
    }


def _message_role(role: MessageRole) -> str:
    if role is MessageRole.AGENT:
        return "assistant"
    if role is MessageRole.TOOL:
        return "tool"
    return role.value


def _first_choice_content(
    response: Mapping[str, object],
) -> tuple[str, str | None]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise OpenAICompatibleProviderError(
            "OpenAI-compatible provider response did not include a model choice."
        )
    first_choice = choices[0]
    if not isinstance(first_choice, Mapping):
        raise OpenAICompatibleProviderError(
            "OpenAI-compatible provider returned an invalid choice shape."
        )
    message = first_choice.get("message")
    if not isinstance(message, Mapping):
        raise OpenAICompatibleProviderError(
            "OpenAI-compatible provider choice did not include a message."
        )
    content = message.get("content")
    if not isinstance(content, str):
        raise OpenAICompatibleProviderError(
            "OpenAI-compatible provider message content was not text."
        )
    finish_reason = first_choice.get("finish_reason")
    return content, finish_reason if isinstance(finish_reason, str) else None


def _usage_metadata(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        item = value.get(key)
        if isinstance(item, int):
            result[key] = str(item)
    return result


def _validate_base_url(value: str) -> None:
    _require_non_empty(value, "api_base_url")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OpenAICompatibleProviderConfigError(
            "api_base_url must be an absolute http or https URL."
        )


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise OpenAICompatibleProviderConfigError(
            f"{field_name} must be a non-empty string."
        )
