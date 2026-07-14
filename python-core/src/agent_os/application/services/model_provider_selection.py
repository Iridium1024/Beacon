from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping

from agent_os.application.services.agent_runtime_access import (
    AgentRuntimeAccessProfile,
)
from agent_os.application.services.context_management_profile import (
    ContextManagementProfile,
)
from agent_os.application.services.provider_backed_agent_invocation_adapter import (
    ProviderBackedAgentInvocationAdapter,
)
from agent_os.domain.ports.model_provider import ModelProviderPort


@dataclass(frozen=True, slots=True)
class ModelProviderSelection:
    """Minimal provider/model selection for provider-backed agent invocation."""

    provider_name: str
    model_name: str
    system_prompt: str | None = None
    parameters: Mapping[str, object] = field(default_factory=dict)
    runtime_metadata: Mapping[str, str] = field(default_factory=dict)
    context_management_profile: ContextManagementProfile = field(
        default_factory=ContextManagementProfile.default
    )
    runtime_access_profile: AgentRuntimeAccessProfile = field(
        default_factory=AgentRuntimeAccessProfile.default
    )

    def __post_init__(self) -> None:
        _require_non_empty(self.provider_name, "provider_name")
        _require_non_empty(self.model_name, "model_name")
        if self.system_prompt is not None:
            _require_non_empty(self.system_prompt, "system_prompt")

    def with_parameter_defaults(
        self,
        defaults: Mapping[str, object],
    ) -> "ModelProviderSelection":
        return replace(
            self,
            parameters={
                **dict(defaults),
                **dict(self.parameters),
            },
        )


def build_provider_backed_agent_invocation_adapter(
    *,
    model_provider: ModelProviderPort,
    selection: ModelProviderSelection,
) -> ProviderBackedAgentInvocationAdapter:
    return ProviderBackedAgentInvocationAdapter(
        model_provider=model_provider,
        provider_name=selection.provider_name,
        model_name=selection.model_name,
        system_prompt=selection.system_prompt,
        parameters=dict(selection.parameters),
        runtime_metadata=dict(selection.runtime_metadata),
        context_management_profile=selection.context_management_profile,
        runtime_access_profile=selection.runtime_access_profile,
    )


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
