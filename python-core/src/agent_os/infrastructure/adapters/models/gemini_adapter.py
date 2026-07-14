from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import os
from typing import Mapping
from urllib.parse import quote, urljoin

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


class GeminiGenerateContentProviderError(RuntimeError):
    """Stable error for Gemini generateContent provider failures."""


class GeminiGenerateContentProviderConfigError(ValueError):
    """Stable error for invalid Gemini generateContent provider configuration."""


@dataclass(slots=True)
class GeminiGenerateContentAdapter(ModelProviderPort):
    """Minimal Gemini generateContent text-generation adapter."""

    api_base_url: str
    model_name: str
    provider_name: str = "gemini"
    api_key_env_var: str = "AGENT_OS_GEMINI_API_KEY"
    timeout_seconds: float = 30.0
    default_parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_non_empty(
            self.provider_name,
            "provider_name",
            GeminiGenerateContentProviderConfigError,
        )
        require_non_empty(
            self.model_name,
            "model_name",
            GeminiGenerateContentProviderConfigError,
        )
        require_non_empty(
            self.api_key_env_var,
            "api_key_env_var",
            GeminiGenerateContentProviderConfigError,
        )
        validate_base_url(
            value=self.api_base_url,
            field_name="api_base_url",
            error_type=GeminiGenerateContentProviderConfigError,
        )
        if self.timeout_seconds <= 0:
            raise GeminiGenerateContentProviderConfigError(
                "timeout_seconds must be positive."
            )

    async def generate(self, request: ModelInvocation) -> ModelOutput:
        return await asyncio.to_thread(self._generate_blocking, request)

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        raise NotImplementedError(
            "Gemini generateContent embeddings are not wired in the local runtime."
        )

    async def list_models(self) -> tuple[str, ...]:
        return (self.model_name,)

    def _generate_blocking(self, request: ModelInvocation) -> ModelOutput:
        self._validate_invocation(request)
        api_key = os.environ.get(self.api_key_env_var)
        if api_key is None or not api_key.strip():
            raise GeminiGenerateContentProviderConfigError(
                "Gemini generateContent provider API key environment variable is not set."
            )
        response = post_json(
            url=_generate_content_url(self.api_base_url, request.model_name),
            payload=self._request_payload(request),
            headers={"x-goog-api-key": api_key},
            timeout_seconds=self.timeout_seconds,
            provider_label="Gemini generateContent provider",
            error_type=GeminiGenerateContentProviderError,
            user_agent=provider_user_agent(
                self.default_parameters,
                request.parameters,
                GeminiGenerateContentProviderConfigError,
            ),
        )
        return self._model_output(request=request, response=response)

    def _validate_invocation(self, request: ModelInvocation) -> None:
        if request.provider_name != self.provider_name:
            raise GeminiGenerateContentProviderConfigError(
                "request provider_name does not match this provider."
            )
        if request.model_name != self.model_name:
            raise GeminiGenerateContentProviderConfigError(
                "request model_name does not match this provider."
            )

    def _request_payload(self, request: ModelInvocation) -> Mapping[str, object]:
        payload: dict[str, object] = {
            "contents": [_content_payload(message) for message in request.messages],
        }
        generation_config = _generation_config(
            self.default_parameters,
            request.parameters,
        )
        if generation_config:
            payload["generationConfig"] = generation_config
        if request.system_prompt is not None:
            payload["systemInstruction"] = {
                "parts": [{"text": request.system_prompt}],
            }
        return payload

    def _model_output(
        self,
        *,
        request: ModelInvocation,
        response: Mapping[str, object],
    ) -> ModelOutput:
        content, finish_reason = _candidate_text(response)
        metadata: dict[str, str] = {
            "provider_name": self.provider_name,
            "model_name": request.model_name,
            "api_shape": "gemini_generate_content",
        }
        if finish_reason is not None:
            metadata["finish_reason"] = finish_reason
        metadata.update(_usage_metadata(response.get("usageMetadata")))
        return ModelOutput(
            model_name=request.model_name,
            content=content,
            metadata=metadata,
        )


def _generation_config(
    defaults: Mapping[str, object],
    request_parameters: Mapping[str, object],
) -> Mapping[str, object]:
    result: dict[str, object] = {}
    for source in (defaults, request_parameters):
        for key, value in source.items():
            if value is None:
                continue
            if key == "temperature":
                result["temperature"] = value
            elif key == "max_tokens":
                result["maxOutputTokens"] = value
            elif key == "top_p":
                result["topP"] = value
            elif key == "stop":
                result["stopSequences"] = value
    return result


def _content_payload(message: ModelMessage) -> Mapping[str, object]:
    return {
        "role": _message_role(message.role),
        "parts": [{"text": message.content}],
    }


def _message_role(role: MessageRole) -> str:
    if role is MessageRole.AGENT:
        return "model"
    return "user"


def _candidate_text(response: Mapping[str, object]) -> tuple[str, str | None]:
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise GeminiGenerateContentProviderError(
            "Gemini generateContent provider response did not include a candidate."
        )
    first = candidates[0]
    if not isinstance(first, Mapping):
        raise GeminiGenerateContentProviderError(
            "Gemini generateContent provider returned an invalid candidate shape."
        )
    content = first.get("content")
    if not isinstance(content, Mapping):
        raise GeminiGenerateContentProviderError(
            "Gemini generateContent provider candidate did not include content."
        )
    parts = content.get("parts")
    if not isinstance(parts, list):
        raise GeminiGenerateContentProviderError(
            "Gemini generateContent provider content did not include text parts."
        )
    text_parts: list[str] = []
    for part in parts:
        if isinstance(part, Mapping):
            text = part.get("text")
            if isinstance(text, str):
                text_parts.append(text)
    if not text_parts:
        raise GeminiGenerateContentProviderError(
            "Gemini generateContent provider text content was empty."
        )
    finish_reason = first.get("finishReason")
    return "".join(text_parts), finish_reason if isinstance(finish_reason, str) else None


def _usage_metadata(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for source, target in (
        ("promptTokenCount", "prompt_tokens"),
        ("candidatesTokenCount", "completion_tokens"),
        ("totalTokenCount", "total_tokens"),
    ):
        item = value.get(source)
        if isinstance(item, int):
            result[target] = str(item)
    return result


def _generate_content_url(base_url: str, model_name: str) -> str:
    normalized = base_url.rstrip("/") + "/"
    model = model_name.removeprefix("models/")
    suffix = f"models/{quote(model, safe='')}:generateContent"
    if normalized.rstrip("/").endswith("/v1beta"):
        return urljoin(normalized, suffix)
    return urljoin(normalized, "v1beta/" + suffix)
