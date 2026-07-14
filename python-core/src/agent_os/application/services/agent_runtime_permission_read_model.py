from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from agent_os.application.services.agent_runtime_access import (
    AgentRuntimeAccessGrant,
    AgentRuntimeAccessPlanner,
    AgentRuntimeAccessProfile,
)
from agent_os.application.services.agent_runtime_profile import AgentRuntimeProfile
from agent_os.domain.entities.agent import AgentRegistration


@dataclass(frozen=True, slots=True)
class RuntimePermissionCapabilityView:
    """Read-only allowed/denied runtime capability projection."""

    allowed: tuple[str, ...]
    denied: tuple[str, ...]

    @classmethod
    def from_grant(
        cls,
        grant: AgentRuntimeAccessGrant,
    ) -> "RuntimePermissionCapabilityView":
        return cls(
            allowed=tuple(grant.allowed_permissions),
            denied=tuple(grant.denied_permissions),
        )

    def to_metadata(self) -> Mapping[str, object]:
        denied = set(self.denied)
        allowed = set(self.allowed)
        return {
            "allowed": list(self.allowed),
            "denied": list(self.denied),
            "flags": {
                "real_runtime_connection_allowed": (
                    "real_runtime_connection" not in denied
                ),
                "credential_store_allowed": "credential_store" not in denied,
                "websocket_transport_allowed": "websocket_transport" not in denied,
                "file_body_read_allowed": "file_body_read" not in denied,
                "provider_prompt_injection_allowed": (
                    "provider_prompt_injection" not in denied
                ),
                "tool_execution_allowed": "tool_execution" not in denied,
                "runtime_local_memory_allowed": (
                    "runtime_local_memory" not in denied
                ),
                "network_allowed": "network" not in denied,
                "declared_tool_names_present": "tool_names:declared" in allowed,
                "declared_skill_refs_present": "skill_refs:declared" in allowed,
            },
        }


@dataclass(frozen=True, slots=True)
class RuntimeDeliveryPlanView:
    """Read-only audit projection of a runtime delivery plan."""

    delivery_plan: Mapping[str, object]

    @classmethod
    def from_grant(cls, grant: AgentRuntimeAccessGrant) -> "RuntimeDeliveryPlanView":
        return cls(delivery_plan=dict(grant.delivery_plan.to_metadata()))

    def to_metadata(self) -> Mapping[str, object]:
        return {
            "delivery_plan_id": self.delivery_plan["delivery_plan_id"],
            "runtime_kind": self.delivery_plan["runtime_kind"],
            "delegated_context_delivery": (
                self.delivery_plan["delegated_context_delivery"]
            ),
            "deliverable_segment_count": len(
                self.delivery_plan["deliverable_segments"]
            ),
            "denied_segment_count": len(self.delivery_plan["denied_segments"]),
            "delegated_context_delivered": (
                self.delivery_plan["delegated_context_delivered"]
            ),
            "real_runtime_connected": self.delivery_plan["real_runtime_connected"],
            "provider_prompt_injected": (
                self.delivery_plan["provider_prompt_injected"]
            ),
            "materialized_text_included": (
                self.delivery_plan["materialized_text_included"]
            ),
            "file_bodies_included": self.delivery_plan["file_bodies_included"],
            "websocket_transport_connected": (
                self.delivery_plan["websocket_transport_connected"]
            ),
            "metadata": dict(self.delivery_plan.get("metadata", {})),
        }


@dataclass(frozen=True, slots=True)
class RuntimeAccessGrantView:
    """Read-only audit projection of a runtime access grant."""

    grant: AgentRuntimeAccessGrant

    def to_metadata(self) -> Mapping[str, object]:
        grant_metadata = self.grant.to_metadata()
        return {
            "grant_id": grant_metadata["grant_id"],
            "agent_id": grant_metadata["agent_id"],
            "invocation_id": grant_metadata["invocation_id"],
            "runtime_kind": grant_metadata["runtime_kind"],
            "allowed_permissions": list(grant_metadata["allowed_permissions"]),
            "denied_permissions": list(grant_metadata["denied_permissions"]),
            "revoked": grant_metadata["revoked"],
            "expires_at": grant_metadata.get("expires_at"),
            "real_runtime_connected": grant_metadata["real_runtime_connected"],
            "credential_store_connected": (
                grant_metadata["credential_store_connected"]
            ),
            "metadata": dict(grant_metadata.get("metadata", {})),
        }


@dataclass(frozen=True, slots=True)
class AgentRuntimePermissionView:
    """Workspace-scoped read-only runtime permission summary for one agent."""

    registration: AgentRegistration
    profile: AgentRuntimeProfile
    grant: AgentRuntimeAccessGrant

    @classmethod
    def from_registration(
        cls,
        registration: AgentRegistration,
    ) -> "AgentRuntimePermissionView":
        profile = AgentRuntimeProfile.from_registration(registration)
        grant = AgentRuntimeAccessPlanner().plan(
            access_profile=profile.runtime_access_profile,
            agent_id=registration.agent_id.value,
            invocation_id=f"runtime-permission-preview-{registration.agent_id.value}",
        )
        return cls(
            registration=registration,
            profile=profile,
            grant=grant,
        )

    def to_metadata(self) -> Mapping[str, object]:
        access_profile = self.profile.runtime_access_profile
        return {
            "workspaceId": self.registration.workspace_id.value,
            "agentId": self.registration.agent_id.value,
            "profileName": self.profile.profile_name,
            "roleName": self.profile.role_name,
            "runtimeKind": access_profile.runtime_kind.value,
            "providerBackedModel": (
                access_profile.runtime_kind.value == "provider_backed_model"
            ),
            "runtimeConnected": False,
            "readModelOnly": True,
            "configuredProfile": _access_profile_summary(access_profile),
            "capabilities": RuntimePermissionCapabilityView.from_grant(
                self.grant
            ).to_metadata(),
            "grant": RuntimeAccessGrantView(self.grant).to_metadata(),
            "deliveryPlan": RuntimeDeliveryPlanView.from_grant(
                self.grant
            ).to_metadata(),
            "boundary": {
                "source": "agent_registration_runtime_access_profile",
                "policy_mode": "read_only_runtime_permission_view",
                "invocation_created": False,
                "model_provider_invoked": False,
                "real_runtime_connected": False,
                "websocket_transport_connected": False,
                "credential_store_connected": False,
                "file_bodies_read": False,
                "provider_prompt_injected": False,
                "provider_payload_modified": False,
                "context_authorization_bypassed": False,
                "materialization_bypassed": False,
            },
        }


def _access_profile_summary(
    access_profile: AgentRuntimeAccessProfile,
) -> Mapping[str, object]:
    metadata = access_profile.to_metadata()
    summary = {
        "runtime_kind": metadata["runtime_kind"],
        "delegated_context_delivery": metadata["delegated_context_delivery"],
        "tool_permissions": list(metadata["tool_permissions"]),
        "file_permission": metadata["file_permission"],
        "memory_policy": metadata["memory_policy"],
        "network_policy": metadata["network_policy"],
        "real_runtime_connected": metadata["real_runtime_connected"],
        "websocket_transport_connected": metadata[
            "websocket_transport_connected"
        ],
        "credential_store_connected": metadata["credential_store_connected"],
    }
    for key in (
        "allowed_tool_names",
        "allowed_skill_refs",
        "memory_namespace",
        "memory_quota_mb",
        "runtime_connection_ref",
        "metadata",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary
