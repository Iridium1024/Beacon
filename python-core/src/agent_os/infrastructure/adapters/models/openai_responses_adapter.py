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


class OpenAIResponsesProviderError(RuntimeError):
    """Stable error for OpenAI Responses provider failures."""


class OpenAIResponsesProviderConfigError(ValueError):
    """Stable error for invalid OpenAI Responses provider configuration."""


@dataclass(slots=True)
class OpenAIResponsesAdapter(ModelProviderPort):
    """Minimal OpenAI Responses text-generation adapter."""

    api_base_url: str
    model_name: str
    provider_name: str = "openai-responses"
    api_key_env_var: str = "AGENT_OS_OPENAI_RESPONSES_API_KEY"
    timeout_seconds: float = 30.0
    default_parameters: Mapping[str, object] = field(default_factory=dict)
    input_mode: str = field(init=False)

    def __post_init__(self) -> None:
        require_non_empty(
            self.provider_name,
            "provider_name",
            OpenAIResponsesProviderConfigError,
        )
        require_non_empty(
            self.model_name,
            "model_name",
            OpenAIResponsesProviderConfigError,
        )
        require_non_empty(
            self.api_key_env_var,
            "api_key_env_var",
            OpenAIResponsesProviderConfigError,
        )
        validate_base_url(
            value=self.api_base_url,
            field_name="api_base_url",
            error_type=OpenAIResponsesProviderConfigError,
        )
        if self.timeout_seconds <= 0:
            raise OpenAIResponsesProviderConfigError(
                "timeout_seconds must be positive."
            )
        self.input_mode = _input_mode(self.default_parameters)

    async def generate(self, request: ModelInvocation) -> ModelOutput:
        return await asyncio.to_thread(self._generate_blocking, request)

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        raise NotImplementedError(
            "OpenAI Responses embeddings are not wired in the local runtime."
        )

    async def list_models(self) -> tuple[str, ...]:
        return (self.model_name,)

    def _generate_blocking(self, request: ModelInvocation) -> ModelOutput:
        self._validate_invocation(request)
        api_key = os.environ.get(self.api_key_env_var)
        if api_key is None or not api_key.strip():
            raise OpenAIResponsesProviderConfigError(
                "OpenAI Responses provider API key environment variable is not set."
            )
        response = post_json(
            url=_responses_url(self.api_base_url),
            payload=self._request_payload(request),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout_seconds=self.timeout_seconds,
            provider_label="OpenAI Responses provider",
            error_type=OpenAIResponsesProviderError,
            user_agent=provider_user_agent(
                self.default_parameters,
                request.parameters,
                OpenAIResponsesProviderConfigError,
            ),
        )
        return self._model_output(request=request, response=response)

    def _validate_invocation(self, request: ModelInvocation) -> None:
        if request.provider_name != self.provider_name:
            raise OpenAIResponsesProviderConfigError(
                "request provider_name does not match this provider."
            )
        if request.model_name != self.model_name:
            raise OpenAIResponsesProviderConfigError(
                "request model_name does not match this provider."
            )

    def _request_payload(self, request: ModelInvocation) -> Mapping[str, object]:
        input_mode = _input_mode(self.default_parameters, request.parameters)
        payload: dict[str, object] = {
            "model": request.model_name,
            "input": _input_payload(request.messages, input_mode),
            **_generation_parameters(self.default_parameters, request.parameters),
        }
        if "max_output_tokens" not in payload:
            payload["max_output_tokens"] = 1024
        if request.system_prompt is not None:
            payload["instructions"] = request.system_prompt
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
            "api_shape": "openai_responses",
        }
        response_id = response.get("id")
        if isinstance(response_id, str):
            metadata["response_id"] = response_id
        status = response.get("status")
        if isinstance(status, str):
            metadata["status"] = status
        metadata.update(_usage_metadata(response.get("usage")))
        return ModelOutput(model_name=model_name, content=content, metadata=metadata)


_DIRECT_GENERATION_PARAMETERS = {
    "temperature",
    "top_p",
    "max_output_tokens",
    "store",
    "user",
    "metadata",
    "include",
    "truncation",
    "service_tier",
}

_INPUT_MODE_STRUCTURED_MESSAGES = "structured_messages"
_INPUT_MODE_PLAIN_TEXT = "plain_text"
_INPUT_MODE_ALIASES = {
    _INPUT_MODE_STRUCTURED_MESSAGES: _INPUT_MODE_STRUCTURED_MESSAGES,
    "structured-messages": _INPUT_MODE_STRUCTURED_MESSAGES,
    "structured": _INPUT_MODE_STRUCTURED_MESSAGES,
    _INPUT_MODE_PLAIN_TEXT: _INPUT_MODE_PLAIN_TEXT,
    "plain-text": _INPUT_MODE_PLAIN_TEXT,
    "text": _INPUT_MODE_PLAIN_TEXT,
}


def _generation_parameters(
    defaults: Mapping[str, object],
    request_parameters: Mapping[str, object],
) -> Mapping[str, object]:
    result: dict[str, object] = {}
    for source in (defaults, request_parameters):
        max_tokens = None
        max_output_tokens = None
        reasoning_effort = None
        reasoning = None
        verbosity = None
        text = None
        for key, value in source.items():
            if value is None:
                continue
            if key == "max_tokens":
                max_tokens = value
            elif key == "max_output_tokens":
                max_output_tokens = value
            elif key == "reasoning_effort":
                reasoning_effort = value
            elif key == "reasoning" and isinstance(value, Mapping):
                reasoning = dict(value)
            elif key == "verbosity":
                verbosity = value
            elif key == "text" and isinstance(value, Mapping):
                text = dict(value)
            elif key in _DIRECT_GENERATION_PARAMETERS:
                result[key] = value
        if max_tokens is not None:
            result["max_output_tokens"] = max_tokens
        if max_output_tokens is not None:
            result["max_output_tokens"] = max_output_tokens
        if reasoning_effort is not None:
            result["reasoning"] = {"effort": reasoning_effort}
        if reasoning is not None:
            result["reasoning"] = reasoning
        if verbosity is not None:
            result["text"] = {"verbosity": verbosity}
        if text is not None:
            result["text"] = text
    return result


def _message_payload(message: ModelMessage) -> Mapping[str, object]:
    return {
        "role": _message_role(message.role),
        "content": [{"type": "input_text", "text": message.content}],
    }


def _input_payload(
    messages: tuple[ModelMessage, ...],
    input_mode: str,
) -> object:
    if input_mode == _INPUT_MODE_PLAIN_TEXT:
        return _plain_text_input(messages)
    return [_message_payload(message) for message in messages]


def _plain_text_input(messages: tuple[ModelMessage, ...]) -> str:
    if len(messages) == 1:
        return messages[0].content
    return "\n".join(
        f"{_message_role(message.role)}: {message.content}" for message in messages
    )


def _input_mode(
    defaults: Mapping[str, object],
    request_parameters: Mapping[str, object] | None = None,
) -> str:
    selected: object | None = None
    for source in (defaults, request_parameters or {}):
        for key in ("responses_input_mode", "input_mode"):
            value = source.get(key)
            if value is not None:
                selected = value
    if selected is None:
        return _INPUT_MODE_STRUCTURED_MESSAGES
    if not isinstance(selected, str):
        raise OpenAIResponsesProviderConfigError(
            "OpenAI Responses input_mode must be a string."
        )
    normalized = selected.strip().lower()
    input_mode = _INPUT_MODE_ALIASES.get(normalized)
    if input_mode is None:
        raise OpenAIResponsesProviderConfigError(
            "OpenAI Responses input_mode must be one of: structured_messages, plain_text."
        )
    return input_mode


def _message_role(role: MessageRole) -> str:
    if role is MessageRole.AGENT:
        return "assistant"
    if role is MessageRole.USER:
        return "user"
    return "user"


def _text_content(response: Mapping[str, object]) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text:
        return output_text

    text_parts: list[str] = []
    output = response.get("output")
    if isinstance(output, list):
        for item in output:
            if isinstance(item, Mapping):
                _collect_output_text(item, text_parts)
    if text_parts:
        return "".join(text_parts)
    raise OpenAIResponsesProviderError(
        "OpenAI Responses provider response did not include text output."
    )


def _collect_output_text(value: object, text_parts: list[str]) -> None:
    if isinstance(value, Mapping):
        text = value.get("text")
        value_type = value.get("type")
        if isinstance(text, str) and value_type in {"output_text", "text"}:
            text_parts.append(text)
        content = value.get("content")
        if content is not value:
            _collect_output_text(content, text_parts)
    elif isinstance(value, list):
        for item in value:
            _collect_output_text(item, text_parts)


def _usage_metadata(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for source, target in (
        ("input_tokens", "prompt_tokens"),
        ("output_tokens", "completion_tokens"),
        ("total_tokens", "total_tokens"),
    ):
        item = value.get(source)
        if isinstance(item, int):
            result[target] = str(item)
    if "total_tokens" not in result:
        prompt_tokens = result.get("prompt_tokens")
        completion_tokens = result.get("completion_tokens")
        if prompt_tokens is not None and completion_tokens is not None:
            result["total_tokens"] = str(int(prompt_tokens) + int(completion_tokens))
    return result


def _responses_url(base_url: str) -> str:
    normalized = base_url.rstrip("/") + "/"
    if normalized.rstrip("/").endswith("/v1"):
        return urljoin(normalized, "responses")
    return urljoin(normalized, "v1/responses")
