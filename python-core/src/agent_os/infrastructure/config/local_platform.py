from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import os
from typing import Mapping

from agent_os.application.services.model_provider_selection import (
    ModelProviderSelection,
)
from agent_os.domain.entities.provider_connection import (
    ProviderApiShape,
    ProviderConnectionSpec,
    normalize_provider_api_shape,
)


class LocalAgentInvocationAdapterMode(StrEnum):
    """Selectable local agent invocation adapter modes."""

    DETERMINISTIC_PLACEHOLDER = "deterministic-placeholder"
    DETERMINISTIC_PROVIDER = "deterministic-provider"
    OPENAI_COMPATIBLE_PROVIDER = "openai-compatible-provider"
    PROVIDER_API_SHAPE = "provider-api-shape"


@dataclass(frozen=True, slots=True)
class OpenAICompatibleProviderSettings:
    """Explicit opt-in settings for an OpenAI-compatible provider adapter."""

    base_url: str
    model_name: str
    provider_name: str = "openai-compatible"
    api_key_env_var: str = "AGENT_OS_OPENAI_COMPAT_API_KEY"
    timeout_seconds: float = 30.0
    parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.base_url, "base_url")
        _require_non_empty(self.model_name, "model_name")
        _require_non_empty(self.provider_name, "provider_name")
        _require_non_empty(self.api_key_env_var, "api_key_env_var")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")

    def model_selection(self) -> ModelProviderSelection:
        return ModelProviderSelection(
            provider_name=self.provider_name,
            model_name=self.model_name,
            parameters=dict(self.parameters),
        )

    def connection_spec(self) -> ProviderConnectionSpec:
        return ProviderConnectionSpec(
            provider_name=self.provider_name,
            api_shape=ProviderApiShape.OPENAI_CHAT_COMPLETIONS,
            base_url=self.base_url,
            model_name=self.model_name,
            credential_env_var=self.api_key_env_var,
            timeout_seconds=self.timeout_seconds,
            parameters=dict(self.parameters),
        )


@dataclass(frozen=True, slots=True)
class LocalPlatformSettings:
    """Minimal local settings for composing the executable platform path."""

    database: str
    workspace_root: str
    plugins_directory: str
    profile_path: str | None = None
    provider_session_registry: str | None = None
    provider_session_registry_source: str | None = None
    provider_session_registry_source_key: str | None = None
    agent_invocation_adapter_mode: LocalAgentInvocationAdapterMode | str = (
        LocalAgentInvocationAdapterMode.DETERMINISTIC_PLACEHOLDER
    )
    provider_selection: ModelProviderSelection | None = None
    openai_compatible_provider: OpenAICompatibleProviderSettings | None = None
    provider_connection: ProviderConnectionSpec | None = None
    initialize_schema: bool = True
    record_agent_invocations: bool = True

    def __post_init__(self) -> None:
        _require_non_empty(self.database, "database")
        _require_non_empty(self.workspace_root, "workspace_root")
        _require_non_empty(self.plugins_directory, "plugins_directory")
        if self.profile_path is not None:
            _require_non_empty(self.profile_path, "profile_path")
        if self.provider_session_registry is not None:
            _require_non_empty(
                self.provider_session_registry,
                "provider_session_registry",
            )
        if self.provider_session_registry_source is not None:
            _require_non_empty(
                self.provider_session_registry_source,
                "provider_session_registry_source",
            )
        if self.provider_session_registry_source_key is not None:
            _require_non_empty(
                self.provider_session_registry_source_key,
                "provider_session_registry_source_key",
            )
        mode = normalize_local_agent_invocation_adapter_mode(
            self.agent_invocation_adapter_mode
        )
        object.__setattr__(self, "agent_invocation_adapter_mode", mode)
        if (
            mode is LocalAgentInvocationAdapterMode.DETERMINISTIC_PLACEHOLDER
            and self.provider_selection is not None
        ):
            raise ValueError(
                "provider_selection requires deterministic-provider mode."
            )
        if (
            mode is not LocalAgentInvocationAdapterMode.OPENAI_COMPATIBLE_PROVIDER
            and self.openai_compatible_provider is not None
        ):
            raise ValueError(
                "openai_compatible_provider requires openai-compatible-provider mode."
            )
        if (
            mode is not LocalAgentInvocationAdapterMode.PROVIDER_API_SHAPE
            and self.provider_connection is not None
        ):
            raise ValueError(
                "provider_connection requires provider-api-shape mode."
            )
        if (
            mode is LocalAgentInvocationAdapterMode.OPENAI_COMPATIBLE_PROVIDER
            and self.openai_compatible_provider is None
        ):
            raise ValueError(
                "openai-compatible-provider mode requires openai_compatible_provider."
            )
        if (
            mode is LocalAgentInvocationAdapterMode.OPENAI_COMPATIBLE_PROVIDER
            and self.provider_selection is not None
        ):
            raise ValueError(
                "provider_selection is reserved for deterministic-provider mode."
            )
        if (
            mode is LocalAgentInvocationAdapterMode.PROVIDER_API_SHAPE
            and self.provider_connection is None
        ):
            raise ValueError(
                "provider-api-shape mode requires provider_connection."
            )
        if (
            mode is LocalAgentInvocationAdapterMode.PROVIDER_API_SHAPE
            and self.provider_selection is not None
        ):
            raise ValueError(
                "provider_selection is reserved for deterministic-provider mode."
            )

    def provider_selection_or_default(self) -> ModelProviderSelection:
        if (
            self.agent_invocation_adapter_mode
            is not LocalAgentInvocationAdapterMode.DETERMINISTIC_PROVIDER
        ):
            raise ValueError(
                "provider selection is only available in deterministic-provider mode."
            )
        return self.provider_selection or default_deterministic_provider_selection()

    def openai_compatible_provider_or_raise(
        self,
    ) -> OpenAICompatibleProviderSettings:
        if (
            self.agent_invocation_adapter_mode
            is not LocalAgentInvocationAdapterMode.OPENAI_COMPATIBLE_PROVIDER
        ):
            raise ValueError(
                "OpenAI-compatible provider settings are only available in "
                "openai-compatible-provider mode."
            )
        assert self.openai_compatible_provider is not None
        return self.openai_compatible_provider

    def provider_connection_or_raise(self) -> ProviderConnectionSpec:
        if (
            self.agent_invocation_adapter_mode
            is not LocalAgentInvocationAdapterMode.PROVIDER_API_SHAPE
        ):
            raise ValueError(
                "Provider connection settings are only available in "
                "provider-api-shape mode."
            )
        assert self.provider_connection is not None
        return self.provider_connection


def default_deterministic_provider_selection(
    *,
    parameters: Mapping[str, object] | None = None,
) -> ModelProviderSelection:
    return ModelProviderSelection(
        provider_name="deterministic",
        model_name="deterministic-text",
        parameters=dict(parameters or {}),
    )


def openai_compatible_provider_settings_from_env(
    env: Mapping[str, str] | None = None,
    *,
    parameters: Mapping[str, object] | None = None,
) -> OpenAICompatibleProviderSettings:
    source = env or os.environ
    base_url = _env_value(source, "AGENT_OS_OPENAI_COMPAT_BASE_URL")
    model = _env_value(source, "AGENT_OS_OPENAI_COMPAT_MODEL")
    if base_url is None:
        raise ValueError("AGENT_OS_OPENAI_COMPAT_BASE_URL must be set.")
    if model is None:
        raise ValueError("AGENT_OS_OPENAI_COMPAT_MODEL must be set.")
    timeout_seconds = _env_float(
        source,
        "AGENT_OS_OPENAI_COMPAT_TIMEOUT_SECONDS",
        default=30.0,
    )
    return OpenAICompatibleProviderSettings(
        base_url=base_url,
        model_name=model,
        provider_name=(
            _env_value(source, "AGENT_OS_OPENAI_COMPAT_PROVIDER_NAME")
            or "openai-compatible"
        ),
        api_key_env_var=(
            _env_value(source, "AGENT_OS_OPENAI_COMPAT_API_KEY_ENV_VAR")
            or "AGENT_OS_OPENAI_COMPAT_API_KEY"
        ),
        timeout_seconds=timeout_seconds,
        parameters=dict(parameters or {}),
    )


def provider_connection_spec_from_env(
    env: Mapping[str, str] | None = None,
    *,
    parameters: Mapping[str, object] | None = None,
) -> ProviderConnectionSpec:
    source = env or os.environ
    shape_text = _env_value(source, "AGENT_OS_PROVIDER_API_SHAPE")
    base_url = _env_value(source, "AGENT_OS_PROVIDER_BASE_URL")
    model = _env_value(source, "AGENT_OS_PROVIDER_MODEL")
    if shape_text is None:
        raise ValueError("AGENT_OS_PROVIDER_API_SHAPE must be set.")
    if base_url is None:
        raise ValueError("AGENT_OS_PROVIDER_BASE_URL must be set.")
    if model is None:
        raise ValueError("AGENT_OS_PROVIDER_MODEL must be set.")
    shape = normalize_provider_api_shape(shape_text)
    timeout_seconds = _env_float(
        source,
        "AGENT_OS_PROVIDER_TIMEOUT_SECONDS",
        default=30.0,
    )
    credential_env_var = (
        _env_value(source, "AGENT_OS_PROVIDER_API_KEY_ENV_VAR")
        or _default_credential_env_var(shape)
    )
    return ProviderConnectionSpec(
        provider_name=_env_value(source, "AGENT_OS_PROVIDER_NAME")
        or _default_provider_name(shape),
        api_shape=shape,
        base_url=base_url,
        model_name=model,
        credential_env_var=credential_env_var,
        timeout_seconds=timeout_seconds,
        parameters=dict(parameters or {}),
    )


def normalize_local_agent_invocation_adapter_mode(
    value: LocalAgentInvocationAdapterMode | str,
) -> LocalAgentInvocationAdapterMode:
    if isinstance(value, LocalAgentInvocationAdapterMode):
        return value
    try:
        return LocalAgentInvocationAdapterMode(value)
    except ValueError as exc:
        valid_modes = ", ".join(mode.value for mode in LocalAgentInvocationAdapterMode)
        raise ValueError(
            "agent_invocation_adapter_mode must be one of: "
            f"{valid_modes}."
        ) from exc


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


def _env_value(env: Mapping[str, str], key: str) -> str | None:
    value = env.get(key)
    if value is None or not value.strip():
        return None
    return value.strip()


def _default_provider_name(shape: ProviderApiShape) -> str:
    if shape is ProviderApiShape.OPENAI_CHAT_COMPLETIONS:
        return "openai-compatible"
    if shape is ProviderApiShape.OPENAI_RESPONSES:
        return "openai-responses"
    if shape is ProviderApiShape.ANTHROPIC_MESSAGES:
        return "anthropic"
    if shape is ProviderApiShape.GEMINI_GENERATE_CONTENT:
        return "gemini"
    if shape is ProviderApiShape.OLLAMA_CHAT:
        return "ollama"
    if shape is ProviderApiShape.AZURE_OPENAI:
        return "azure-openai"
    return shape.value


def _default_credential_env_var(shape: ProviderApiShape) -> str | None:
    if shape is ProviderApiShape.OLLAMA_CHAT:
        return None
    if shape is ProviderApiShape.OPENAI_CHAT_COMPLETIONS:
        return "AGENT_OS_OPENAI_COMPAT_API_KEY"
    if shape is ProviderApiShape.OPENAI_RESPONSES:
        return "AGENT_OS_OPENAI_RESPONSES_API_KEY"
    if shape is ProviderApiShape.ANTHROPIC_MESSAGES:
        return "AGENT_OS_ANTHROPIC_API_KEY"
    if shape is ProviderApiShape.GEMINI_GENERATE_CONTENT:
        return "AGENT_OS_GEMINI_API_KEY"
    return "AGENT_OS_PROVIDER_API_KEY"


def _env_float(
    env: Mapping[str, str],
    key: str,
    *,
    default: float,
) -> float:
    value = _env_value(env, key)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{key} must be a number.") from exc
    if parsed <= 0:
        raise ValueError(f"{key} must be positive.")
    return parsed
