from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping
from urllib.parse import urlparse


class ProviderConnectionConfigError(ValueError):
    """Stable error for provider connection shape/config failures."""


class ProviderApiShape(StrEnum):
    """Supported provider API shape labels at the runtime boundary."""

    OPENAI_CHAT_COMPLETIONS = "openai_chat_completions"
    OPENAI_RESPONSES = "openai_responses"
    ANTHROPIC_MESSAGES = "anthropic_messages"
    GEMINI_GENERATE_CONTENT = "gemini_generate_content"
    OLLAMA_CHAT = "ollama_chat"
    AZURE_OPENAI = "azure_openai"


@dataclass(frozen=True, slots=True)
class ProviderConnectionSpec:
    """Credential-safe configured provider connection.

    The spec stores only endpoint metadata and credential references. It must
    never contain credential values.
    """

    provider_name: str
    api_shape: ProviderApiShape | str
    base_url: str
    model_name: str
    credential_env_var: str | None = None
    timeout_seconds: float = 30.0
    parameters: Mapping[str, object] = field(default_factory=dict)
    static_models: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.provider_name, "provider_name")
        _validate_base_url(self.base_url)
        _require_non_empty(self.model_name, "model_name")
        if self.credential_env_var is not None:
            _require_non_empty(self.credential_env_var, "credential_env_var")
        if self.timeout_seconds <= 0:
            raise ProviderConnectionConfigError("timeout_seconds must be positive.")
        shape = normalize_provider_api_shape(self.api_shape)
        object.__setattr__(self, "api_shape", shape)
        object.__setattr__(
            self,
            "static_models",
            _validated_string_tuple(self.static_models, "static_models"),
        )
        _reject_sensitive_mapping(self.parameters, "parameters")
        _reject_sensitive_mapping(self.metadata, "metadata")

    def configured_models(self) -> tuple[str, ...]:
        """Return configured/static models without remote model discovery."""

        if self.static_models:
            return self.static_models
        return (self.model_name,)


@dataclass(frozen=True, slots=True)
class ProviderPreset:
    """Static provider preset that can be converted into a connection spec."""

    preset_id: str
    display_name: str
    connection: ProviderConnectionSpec

    def __post_init__(self) -> None:
        _require_non_empty(self.preset_id, "preset_id")
        _require_non_empty(self.display_name, "display_name")


def normalize_provider_api_shape(value: ProviderApiShape | str) -> ProviderApiShape:
    if isinstance(value, ProviderApiShape):
        return value
    normalized = value.strip().lower().replace("-", "_")
    if normalized in _PROVIDER_API_SHAPE_ALIASES:
        return _PROVIDER_API_SHAPE_ALIASES[normalized]
    try:
        return ProviderApiShape(normalized)
    except ValueError as exc:
        valid = ", ".join(shape.value for shape in ProviderApiShape)
        raise ProviderConnectionConfigError(
            "provider api shape must be one of: " f"{valid}."
        ) from exc


def deepseek_provider_preset(
    *,
    credential_env_var: str = "AGENT_OS_OPENAI_COMPAT_API_KEY",
) -> ProviderPreset:
    """Return the current DeepSeek preset over OpenAI-compatible chat."""

    return ProviderPreset(
        preset_id="deepseek",
        display_name="DeepSeek",
        connection=ProviderConnectionSpec(
            provider_name="deepseek",
            api_shape=ProviderApiShape.OPENAI_CHAT_COMPLETIONS,
            base_url="https://api.deepseek.com",
            model_name="deepseek-v4-flash",
            credential_env_var=credential_env_var,
            static_models=("deepseek-v4-flash", "deepseek-v4-pro"),
            metadata={
                "official_openai_compatible": "true",
                "anthropic_compatible_endpoint_reserved": (
                    "https://api.deepseek.com/anthropic"
                ),
                "legacy_models_deprecated_on": "2026-07-24",
                "legacy_models": "deepseek-chat,deepseek-reasoner,deepseek-ocr",
                "thinking_parameter": "thinking",
                "reasoning_effort_values": "high,max",
                "reasoning_effort_compatibility_aliases": "low,medium=>high;xhigh=>max",
            },
        ),
    )


_PROVIDER_API_SHAPE_ALIASES = {
    "openai": ProviderApiShape.OPENAI_CHAT_COMPLETIONS,
    "openai_compatible": ProviderApiShape.OPENAI_CHAT_COMPLETIONS,
    "openai_chat": ProviderApiShape.OPENAI_CHAT_COMPLETIONS,
    "openai_chat_completions": ProviderApiShape.OPENAI_CHAT_COMPLETIONS,
    "chat_completions": ProviderApiShape.OPENAI_CHAT_COMPLETIONS,
    "openai_response": ProviderApiShape.OPENAI_RESPONSES,
    "openai_responses": ProviderApiShape.OPENAI_RESPONSES,
    "responses": ProviderApiShape.OPENAI_RESPONSES,
    "anthropic": ProviderApiShape.ANTHROPIC_MESSAGES,
    "anthropic_messages": ProviderApiShape.ANTHROPIC_MESSAGES,
    "gemini": ProviderApiShape.GEMINI_GENERATE_CONTENT,
    "gemini_generate_content": ProviderApiShape.GEMINI_GENERATE_CONTENT,
    "ollama": ProviderApiShape.OLLAMA_CHAT,
    "ollama_chat": ProviderApiShape.OLLAMA_CHAT,
    "azure_openai": ProviderApiShape.AZURE_OPENAI,
}


_SENSITIVE_KEYS = {
    "apikey",
    "authorization",
    "bearertoken",
    "cookie",
    "password",
    "secret",
    "sessiontoken",
    "token",
}

_REFERENCE_KEYS = {
    "apikeyenvvar",
    "credentialenvvar",
    "credentialreference",
    "credentialref",
}


def _validate_base_url(value: str) -> None:
    _require_non_empty(value, "base_url")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProviderConnectionConfigError(
            "base_url must be an absolute http or https URL."
        )


def _validated_string_tuple(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        _require_non_empty(value, field_name)
        stripped = value.strip()
        if stripped in seen:
            raise ProviderConnectionConfigError(
                f"{field_name} must not contain duplicate values."
            )
        seen.add(stripped)
        result.append(stripped)
    return tuple(result)


def _reject_sensitive_mapping(source: Mapping[str, object], logical_name: str) -> None:
    for key, value in source.items():
        normalized = _normalized_key(key)
        if normalized in _SENSITIVE_KEYS:
            raise ProviderConnectionConfigError(
                f"{logical_name} field '{key}' must not contain credential values."
            )
        if isinstance(value, Mapping):
            if normalized in _REFERENCE_KEYS:
                continue
            _reject_sensitive_mapping(value, f"{logical_name}.{key}")
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, Mapping):
                    _reject_sensitive_mapping(item, f"{logical_name}.{key}")


def _normalized_key(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ProviderConnectionConfigError(f"{field_name} must be a non-empty string.")
