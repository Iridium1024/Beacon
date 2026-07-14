from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from agent_os.application.services.agent_runtime_access import (
    AgentRuntimeAccessPlanner,
    AgentRuntimeAccessProfile,
)
from agent_os.application.services.context_management_profile import (
    ContextAssemblyPlanner,
    ContextAssemblyRequest,
    ContextSharedContextUpdateSnapshot,
    ContextManagementProfile,
)
from agent_os.application.services.single_turn_platform_runtime import (
    AgentInvocationAdapterPort,
)
from agent_os.domain.entities.context import (
    ContextUpdateInfo,
    ProjectSharedContext,
)
from agent_os.domain.entities.invocation import (
    AgentInvocationRequest,
    AgentInvocationResult,
)
from agent_os.domain.entities.model import ModelInvocation, ModelMessage, ModelOutput
from agent_os.domain.ports.model_provider import ModelProviderPort
from agent_os.domain.value_objects.enums import MessageRole


@dataclass(frozen=True, slots=True)
class ProviderBackedAgentInvocationAdapter(AgentInvocationAdapterPort):
    """Agent invocation adapter backed by a provider-neutral model provider."""

    model_provider: ModelProviderPort
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

    def invoke(
        self,
        *,
        request: AgentInvocationRequest,
        context: ProjectSharedContext,
        user_context_update: ContextUpdateInfo,
        completed_at: datetime,
    ) -> AgentInvocationResult:
        model_invocation = self.build_model_invocation(
            request=request,
            context=context,
            user_context_update=user_context_update,
        )
        try:
            output = _generate_sync(self.model_provider, model_invocation)
        except Exception as exc:
            return self._failed_result(
                request=request,
                user_context_update=user_context_update,
                completed_at=completed_at,
                error=exc,
            )
        return self._succeeded_result(
            request=request,
            context=context,
            user_context_update=user_context_update,
            completed_at=completed_at,
            output=output,
        )

    def build_model_invocation(
        self,
        *,
        request: AgentInvocationRequest,
        context: ProjectSharedContext,
        user_context_update: ContextUpdateInfo,
    ) -> ModelInvocation:
        context_plan = ContextAssemblyPlanner().plan(
            profile=self.context_management_profile,
            request=ContextAssemblyRequest(
                workspace_id=request.workspace_id.value,
                agent_id=request.agent_id.value,
                invocation_id=request.invocation_id.value,
                context_id=context.context_id.value,
                user_instruction=request.instruction,
                current_context_update_id=user_context_update.update_id.value,
                task_id=(
                    request.task_id.value
                    if request.task_id is not None
                    else None
                ),
                conversation_id=_conversation_id_from_metadata(request.metadata),
                file_references=tuple(request.file_references),
                shared_context_updates=_shared_context_update_snapshots(context),
            ),
        )
        runtime_access = AgentRuntimeAccessPlanner().plan(
            access_profile=self.runtime_access_profile,
            agent_id=request.agent_id.value,
            invocation_id=request.invocation_id.value,
            materialization=context_plan.materialization,
        )
        return ModelInvocation(
            provider_name=self.provider_name,
            model_name=self.model_name,
            system_prompt=self.system_prompt,
            messages=(
                ModelMessage(
                    role=MessageRole.USER,
                    content=request.instruction,
                ),
            ),
            parameters={
                **dict(self.parameters),
                "workspace_id": request.workspace_id.value,
                "agent_id": request.agent_id.value,
                "context_id": context.context_id.value,
                "context_update_id": user_context_update.update_id.value,
                "context_management": context_plan.to_metadata(),
                "runtime_access": runtime_access.to_metadata(),
                "request_metadata": dict(request.metadata),
            },
        )

    def _succeeded_result(
        self,
        *,
        request: AgentInvocationRequest,
        context: ProjectSharedContext,
        user_context_update: ContextUpdateInfo,
        completed_at: datetime,
        output: ModelOutput,
    ) -> AgentInvocationResult:
        return AgentInvocationResult.succeed(
            request,
            summary="Provider-backed model invocation completed.",
            completed_at=completed_at,
            output_text=output.content,
            output_payload={
                "model_invoked": True,
                "tool_invoked": False,
                "provider_name": self.provider_name,
                "model_name": output.model_name,
                "context_id": context.context_id.value,
                "context_update_id": user_context_update.update_id.value,
                "model_metadata": dict(output.metadata),
                "runtime_profile": dict(self.runtime_metadata),
            },
            context_update_ids=(user_context_update.update_id,),
            metadata={
                "source": "provider_backed_agent_invocation_adapter",
                "provider_name": self.provider_name,
                "model_name": output.model_name,
                "provider_backed": "true",
                **_runtime_metadata_fields(self.runtime_metadata),
            },
        )

    def _failed_result(
        self,
        *,
        request: AgentInvocationRequest,
        user_context_update: ContextUpdateInfo,
        completed_at: datetime,
        error: Exception,
    ) -> AgentInvocationResult:
        return AgentInvocationResult.fail(
            request,
            summary="Provider-backed model invocation failed.",
            error_message=str(error),
            completed_at=completed_at,
            output_payload={
                "model_invoked": False,
                "tool_invoked": False,
                "provider_name": self.provider_name,
                "model_name": self.model_name,
                "context_update_id": user_context_update.update_id.value,
                "runtime_profile": dict(self.runtime_metadata),
            },
            context_update_ids=(user_context_update.update_id,),
            metadata={
                "source": "provider_backed_agent_invocation_adapter",
                "provider_name": self.provider_name,
                "model_name": self.model_name,
                "provider_backed": "true",
                "provider_failed": "true",
                **_runtime_metadata_fields(self.runtime_metadata),
            },
        )


def _generate_sync(
    model_provider: ModelProviderPort,
    model_invocation: ModelInvocation,
) -> ModelOutput:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(model_provider.generate(model_invocation))
    raise RuntimeError(
        "ProviderBackedAgentInvocationAdapter requires a synchronous runtime boundary."
    )


def _runtime_metadata_fields(metadata: Mapping[str, str]) -> Mapping[str, str]:
    return {
        f"runtime_{key}": value
        for key, value in metadata.items()
        if key in {"profile_name", "role_name", "runtime_kind", "binding_id"}
    }


def _conversation_id_from_metadata(metadata: Mapping[str, object]) -> str | None:
    for key in ("conversation_id", "conversationId"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _shared_context_update_snapshots(
    context: ProjectSharedContext,
) -> tuple[ContextSharedContextUpdateSnapshot, ...]:
    return tuple(
        ContextSharedContextUpdateSnapshot(
            update_id=update.update_id.value,
            update_kind=update.update_kind.value,
            summary=update.summary,
            created_at=update.created_at.isoformat(),
            source_agent_id=(
                update.source_agent_id.value
                if update.source_agent_id is not None
                else None
            ),
        )
        for update in context.recent_updates(limit=10)
    )
