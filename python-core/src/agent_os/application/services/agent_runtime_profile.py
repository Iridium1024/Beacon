from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from agent_os.application.services.agent_runtime_access import (
    AgentRuntimeAccessProfile,
)
from agent_os.application.services.context_management_profile import (
    ContextManagementProfile,
    context_management_config_from_runtime_config,
)
from agent_os.application.services.model_provider_selection import (
    ModelProviderSelection,
)
from agent_os.domain.entities.agent import AgentRegistration
from agent_os.domain.entities.model import (
    ModelGenerationOptions,
    ModelReasoningOptions,
    ModelRuntimeConstraints,
)


@dataclass(frozen=True, slots=True)
class AgentRuntimeProfile:
    """Runtime-facing profile parsed from an agent registration."""

    agent_id: str
    profile_name: str
    role_name: str
    system_prompt: str | None = None
    provider_name: str | None = None
    model_name: str | None = None
    generation_options: ModelGenerationOptions = field(
        default_factory=ModelGenerationOptions
    )
    reasoning_options: ModelReasoningOptions = field(
        default_factory=ModelReasoningOptions
    )
    runtime_constraints: ModelRuntimeConstraints = field(
        default_factory=ModelRuntimeConstraints
    )
    runtime_kind: str | None = None
    binding_id: str | None = None
    connection_id: str | None = None
    context_management_profile: ContextManagementProfile = field(
        default_factory=ContextManagementProfile.default
    )
    runtime_access_profile: AgentRuntimeAccessProfile = field(
        default_factory=AgentRuntimeAccessProfile.default
    )
    metadata: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_registration(
        cls,
        registration: AgentRegistration,
    ) -> "AgentRuntimeProfile":
        runtime_config = dict(registration.runtime_config)
        _reject_sensitive_config(runtime_config)
        profile_config = _optional_mapping(runtime_config, "profile") or runtime_config
        _reject_sensitive_config(profile_config)

        model_name = _optional_text(profile_config, "model_name", "modelName")
        if model_name is None and _profile_usable_default_model(
            registration.default_model
        ):
            model_name = registration.default_model

        runtime_kind = _optional_text(
            profile_config,
            "runtime_kind",
            "runtimeKind",
        )
        return cls(
            agent_id=registration.agent_id.value,
            profile_name=(
                _optional_text(
                    profile_config,
                    "profile_name",
                    "profileName",
                    "name",
                )
                or registration.name
            ),
            role_name=(
                _optional_text(profile_config, "role_name", "roleName")
                or registration.name
            ),
            system_prompt=_optional_text(
                profile_config,
                "system_prompt",
                "systemPrompt",
            ),
            provider_name=_optional_text(
                profile_config,
                "provider_name",
                "providerName",
            ),
            model_name=model_name,
            generation_options=ModelGenerationOptions.from_mapping(
                _optional_mapping(
                    profile_config,
                    "generation_options",
                    "generationOptions",
                )
            ),
            reasoning_options=ModelReasoningOptions.from_mapping(
                _optional_mapping(
                    profile_config,
                    "reasoning_options",
                    "reasoningOptions",
                )
            ),
            runtime_constraints=ModelRuntimeConstraints.from_mapping(
                _optional_mapping(
                    profile_config,
                    "runtime_constraints",
                    "runtimeConstraints",
                )
            ),
            runtime_kind=runtime_kind,
            binding_id=_optional_text(profile_config, "binding_id", "bindingId"),
            connection_id=_optional_text(
                profile_config,
                "connection_id",
                "connectionId",
            ),
            context_management_profile=ContextManagementProfile.from_mapping(
                context_management_config_from_runtime_config(runtime_config)
            ),
            runtime_access_profile=AgentRuntimeAccessProfile.from_mapping(
                _runtime_access_config_from_runtime_config(runtime_config),
                runtime_kind=runtime_kind,
            ),
            metadata=dict(_optional_mapping(profile_config, "metadata") or {}),
        )

    def provider_selection(
        self,
        default_selection: ModelProviderSelection,
    ) -> ModelProviderSelection:
        provider_name = self.provider_name or default_selection.provider_name
        model_name = self.model_name or default_selection.model_name
        parameters = {
            **dict(default_selection.parameters),
            **dict(self.generation_options.to_parameters()),
        }
        return ModelProviderSelection(
            provider_name=provider_name,
            model_name=model_name,
            system_prompt=self.system_prompt or default_selection.system_prompt,
            parameters=parameters,
            runtime_metadata=self.runtime_metadata(),
            context_management_profile=self.context_management_profile,
            runtime_access_profile=self.runtime_access_profile,
        )

    def runtime_metadata(self) -> Mapping[str, str]:
        metadata: dict[str, str] = {
            "agent_id": self.agent_id,
            "profile_name": self.profile_name,
            "role_name": self.role_name,
        }
        for key, value in (
            ("runtime_kind", self.runtime_kind),
            ("binding_id", self.binding_id),
            ("connection_id", self.connection_id),
        ):
            if value is not None:
                metadata[key] = value
        if self.reasoning_options.to_metadata():
            metadata["reasoning_options_reserved"] = "true"
        if self.runtime_constraints.to_metadata():
            metadata["runtime_constraints_reserved"] = "true"
        metadata["context_management_strategy"] = (
            self.context_management_profile.strategy.value
        )
        if self.context_management_profile != ContextManagementProfile.default():
            metadata["context_management_profile_reserved"] = "true"
        metadata["runtime_access_kind"] = self.runtime_access_profile.runtime_kind.value
        metadata["runtime_access_delegated_context"] = (
            self.runtime_access_profile.delegated_context_delivery.value
        )
        if self.runtime_access_profile != AgentRuntimeAccessProfile.default():
            metadata["runtime_access_profile_reserved"] = "true"
        return metadata


def _profile_usable_default_model(value: str | None) -> bool:
    if value is None:
        return False
    return value not in {
        "deterministic-placeholder",
        "deterministic/local",
    }


def _optional_mapping(
    source: Mapping[str, object],
    *keys: str,
) -> Mapping[str, object] | None:
    value = _optional_value(source, *keys)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"{keys[0]} must be an object.")
    return dict(value)


def _optional_text(source: Mapping[str, object], *keys: str) -> str | None:
    value = _optional_value(source, *keys)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{keys[0]} must be a non-empty string.")
    return value.strip()


def _optional_value(source: Mapping[str, object], *keys: str) -> object | None:
    for key in keys:
        if key in source:
            return source[key]
    return None


def _runtime_access_config_from_runtime_config(
    runtime_config: Mapping[str, object],
) -> Mapping[str, object] | None:
    profile_config = _optional_mapping(runtime_config, "profile")
    if profile_config is not None:
        nested = _optional_mapping(
            profile_config,
            "runtime_access",
            "runtimeAccess",
        )
        if nested is not None:
            return nested
    return _optional_mapping(runtime_config, "runtime_access", "runtimeAccess")


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


def _reject_sensitive_config(source: Mapping[str, object]) -> None:
    for key, value in source.items():
        normalized = _normalized_key(key)
        if normalized in _SENSITIVE_KEYS:
            raise ValueError(
                f"agent runtime profile field '{key}' must not contain credential values."
            )
        if isinstance(value, Mapping):
            if normalized in _REFERENCE_KEYS:
                continue
            _reject_sensitive_config(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, Mapping):
                    _reject_sensitive_config(item)


def _normalized_key(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())
