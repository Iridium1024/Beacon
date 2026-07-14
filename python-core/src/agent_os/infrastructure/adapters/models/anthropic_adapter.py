from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import os
from typing import Mapping
from urllib.parse import urljoin

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
    require_non_empty,
    validate_base_url,
)


class AnthropicMessagesProviderError(RuntimeError):
    """Stable error for Anthropic Messages provider failures."""


class AnthropicMessagesProviderConfigError(ValueError):
    """Stable error for invalid Anthropic Messages provider configuration."""


@dataclass(slots=True)
class AnthropicMessagesAdapter(ModelProviderPort):
    """Minimal Anthropic Messages text-generation adapter."""

    api_base_url: str
    model_name: str
    provider_name: str = "anthropic"
    api_key_env_var: str = "AGENT_OS_ANTHROPIC_API_KEY"
    timeout_seconds: float = 30.0
    default_parameters: Mapping[str, object] = field(default_factory=dict)
    anthropic_version: str = "2023-06-01"

    def __post_init__(self) -> None:
        require_non_empty(
            self.provider_name,
            "provider_name",
            AnthropicMessagesProviderConfigError,
        )
        require_non_empty(
            self.model_name,
            "model_name",
            AnthropicMessagesProviderConfigError,
        )
        require_non_empty(
            self.api_key_env_var,
            "api_key_env_var",
            AnthropicMessagesProviderConfigError,
        )
        require_non_empty(
            self.anthropic_version,
            "anthropic_version",
            AnthropicMessagesProviderConfigError,
        )
        validate_base_url(
            value=self.api_base_url,
            field_name="api_base_url",
            error_type=AnthropicMessagesProviderConfigError,
        )
        if self.timeout_seconds <= 0:
            raise AnthropicMessagesProviderConfigError(
                "timeout_seconds must be positive."
            )

    async def generate(self, request: ModelInvocation) -> ModelOutput:
        return await asyncio.to_thread(self._generate_blocking, request)

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        raise NotImplementedError(
            "Anthropic Messages embeddings are not wired in the local runtime."
        )

    async def list_models(self) -> tuple[str, ...]:
        return (self.model_name,)

    def _generate_blocking(self, request: ModelInvocation) -> ModelOutput:
        self._validate_invocation(request)
        api_key = os.environ.get(self.api_key_env_var)
        if api_key is None or not api_key.strip():
            raise AnthropicMessagesProviderConfigError(
                "Anthropic Messages provider API key environment variable is not set."
            )
        response = post_json(
            url=_messages_url(self.api_base_url),
            payload=self._request_payload(request),
            headers={
                "x-api-key": api_key,
                "anthropic-version": self.anthropic_version,
            },
            timeout_seconds=self.timeout_seconds,
            provider_label="Anthropic Messages provider",
            error_type=AnthropicMessagesProviderError,
            user_agent=provider_user_agent(
                self.default_parameters,
                request.parameters,
                AnthropicMessagesProviderConfigError,
            ),
        )
        return self._model_output(request=request, response=response)

    def _validate_invocation(self, request: ModelInvocation) -> None:
        if request.provider_name != self.provider_name:
            raise AnthropicMessagesProviderConfigError(
                "request provider_name does not match this provider."
            )
        if request.model_name != self.model_name:
            raise AnthropicMessagesProviderConfigError(
                "request model_name does not match this provider."
            )

    def _request_payload(self, request: ModelInvocation) -> Mapping[str, object]:
        payload: dict[str, object] = {
            "model": request.model_name,
            "messages": [_message_payload(message) for message in request.messages],
            **_generation_parameters(self.default_parameters, request.parameters),
        }
        if "max_tokens" not in payload:
            payload["max_tokens"] = 1024
        if request.system_prompt is not None:
            payload["system"] = request.system_prompt
        return payload

    def _model_output(
        self,
        *,
        request: ModelInvocation,
        response: Mapping[str, object],
    ) -> ModelOutput:
        content = _text_content(response)
        response_model = response.get("model")
        model_name = response_model if isinstance(response_model, str) else request.model_name
        metadata: dict[str, str] = {
            "provider_name": self.provider_name,
            "model_name": model_name,
            "api_shape": "anthropic_messages",
        }
        stop_reason = response.get("stop_reason")
        if isinstance(stop_reason, str):
            metadata["stop_reason"] = stop_reason
        metadata.update(_usage_metadata(response.get("usage")))
        return ModelOutput(model_name=model_name, content=content, metadata=metadata)


_ALLOWED_GENERATION_PARAMETERS = {
    "temperature",
    "max_tokens",
    "top_p",
    "stop_sequences",
}


def _generation_parameters(
    defaults: Mapping[str, object],
    request_parameters: Mapping[str, object],
) -> Mapping[str, object]:
    result: dict[str, object] = {}
    for source in (defaults, request_parameters):
        for key, value in source.items():
            if key == "stop":
                key = "stop_sequences"
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
    if role is MessageRole.USER:
        return "user"
    return "user"


def _text_content(response: Mapping[str, object]) -> str:
    content = response.get("content")
    if not isinstance(content, list) or not content:
        raise AnthropicMessagesProviderError(
            "Anthropic Messages provider response did not include text content."
        )
    text_parts: list[str] = []
    for part in content:
        if isinstance(part, Mapping) and part.get("type") == "text":
            text = part.get("text")
            if isinstance(text, str):
                text_parts.append(text)
    if not text_parts:
        raise AnthropicMessagesProviderError(
            "Anthropic Messages provider response text content was empty."
        )
    return "".join(text_parts)


def _usage_metadata(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for source, target in (
        ("input_tokens", "prompt_tokens"),
        ("output_tokens", "completion_tokens"),
    ):
        item = value.get(source)
        if isinstance(item, int):
            result[target] = str(item)
    if "prompt_tokens" in result and "completion_tokens" in result:
        result["total_tokens"] = str(
            int(result["prompt_tokens"]) + int(result["completion_tokens"])
        )
    return result


def _messages_url(base_url: str) -> str:
    normalized = base_url.rstrip("/") + "/"
    if normalized.rstrip("/").endswith("/v1"):
        return urljoin(normalized, "messages")
    return urljoin(normalized, "v1/messages")
