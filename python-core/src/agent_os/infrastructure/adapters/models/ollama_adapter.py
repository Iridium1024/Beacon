from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
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


class OllamaChatProviderError(RuntimeError):
    """Stable error for Ollama native chat provider failures."""


class OllamaChatProviderConfigError(ValueError):
    """Stable error for invalid Ollama native chat provider configuration."""


@dataclass(slots=True)
class OllamaChatAdapter(ModelProviderPort):
    """Minimal Ollama native /api/chat text-generation adapter."""

    api_base_url: str = "http://localhost:11434"
    model_name: str = "llama3"
    provider_name: str = "ollama"
    timeout_seconds: float = 30.0
    default_parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_non_empty(
            self.provider_name,
            "provider_name",
            OllamaChatProviderConfigError,
        )
        require_non_empty(
            self.model_name,
            "model_name",
            OllamaChatProviderConfigError,
        )
        validate_base_url(
            value=self.api_base_url,
            field_name="api_base_url",
            error_type=OllamaChatProviderConfigError,
        )
        if self.timeout_seconds <= 0:
            raise OllamaChatProviderConfigError("timeout_seconds must be positive.")

    async def generate(self, request: ModelInvocation) -> ModelOutput:
        return await asyncio.to_thread(self._generate_blocking, request)

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        raise NotImplementedError(
            "Ollama native embeddings are not wired in the local runtime."
        )

    async def list_models(self) -> tuple[str, ...]:
        return (self.model_name,)

    def _generate_blocking(self, request: ModelInvocation) -> ModelOutput:
        self._validate_invocation(request)
        response = post_json(
            url=_chat_url(self.api_base_url),
            payload=self._request_payload(request),
            headers={},
            timeout_seconds=self.timeout_seconds,
            provider_label="Ollama native chat provider",
            error_type=OllamaChatProviderError,
            user_agent=provider_user_agent(
                self.default_parameters,
                request.parameters,
                OllamaChatProviderConfigError,
            ),
        )
        return self._model_output(request=request, response=response)

    def _validate_invocation(self, request: ModelInvocation) -> None:
        if request.provider_name != self.provider_name:
            raise OllamaChatProviderConfigError(
                "request provider_name does not match this provider."
            )
        if request.model_name != self.model_name:
            raise OllamaChatProviderConfigError(
                "request model_name does not match this provider."
            )

    def _request_payload(self, request: ModelInvocation) -> Mapping[str, object]:
        messages = []
        if request.system_prompt is not None:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.extend(_message_payload(message) for message in request.messages)
        payload: dict[str, object] = {
            "model": request.model_name,
            "messages": messages,
            "stream": False,
        }
        options = _options(self.default_parameters, request.parameters)
        if options:
            payload["options"] = options
        return payload

    def _model_output(
        self,
        *,
        request: ModelInvocation,
        response: Mapping[str, object],
    ) -> ModelOutput:
        message = response.get("message")
        if not isinstance(message, Mapping):
            raise OllamaChatProviderError(
                "Ollama native chat provider response did not include a message."
            )
        content = message.get("content")
        if not isinstance(content, str):
            raise OllamaChatProviderError(
                "Ollama native chat provider message content was not text."
            )
        response_model = response.get("model")
        model_name = response_model if isinstance(response_model, str) else request.model_name
        metadata: dict[str, str] = {
            "provider_name": self.provider_name,
            "model_name": model_name,
            "api_shape": "ollama_chat",
        }
        done_reason = response.get("done_reason")
        if isinstance(done_reason, str):
            metadata["done_reason"] = done_reason
        return ModelOutput(model_name=model_name, content=content, metadata=metadata)


def _options(
    defaults: Mapping[str, object],
    request_parameters: Mapping[str, object],
) -> Mapping[str, object]:
    result: dict[str, object] = {}
    for source in (defaults, request_parameters):
        for key, value in source.items():
            if value is None:
                continue
            if key in {"temperature", "top_p"}:
                result[key] = value
            elif key == "max_tokens":
                result["num_predict"] = value
            elif key == "num_predict":
                result["num_predict"] = value
    return result


def _message_payload(message: ModelMessage) -> Mapping[str, str]:
    return {
        "role": _message_role(message.role),
        "content": message.content,
    }


def _message_role(role: MessageRole) -> str:
    if role is MessageRole.AGENT:
        return "assistant"
    if role is MessageRole.SYSTEM:
        return "system"
    if role is MessageRole.USER:
        return "user"
    return "user"


def _chat_url(base_url: str) -> str:
    normalized = base_url.rstrip("/") + "/"
    if normalized.rstrip("/").endswith("/api"):
        return urljoin(normalized, "chat")
    return urljoin(normalized, "api/chat")
