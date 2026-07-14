from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping, Sequence

from agent_os.application.services.context_management_profile import (
    ContextMaterializationPlan,
    ContextMaterializedSegment,
)


class AgentRuntimeKind(StrEnum):
    """Stable labels for runtime access contract families."""

    PROVIDER_BACKED_MODEL = "provider_backed_model"
    AGENT_NATIVE_RUNTIME = "agent_native_runtime"
    EXTERNAL_AGENT_BRIDGE = "external_agent_bridge"
    BROWSER_SESSION_RUNTIME = "browser_session_runtime"
    IDE_AGENT_RUNTIME = "ide_agent_runtime"
    RESERVED = "reserved"


class DelegatedContextDeliveryPolicy(StrEnum):
    """How platform-derived context may be exposed to a future runtime."""

    NONE = "none"
    METADATA_REFS_ONLY = "metadata_refs_only"
    BOUNDED_MATERIALIZED_SEGMENTS = "bounded_materialized_segments"
    AGENT_MANAGED_CONTEXT_REF = "agent_managed_context_ref"


class RuntimeToolPermission(StrEnum):
    """Declarative tool permission labels. No tool is executed by this contract."""

    NONE = "none"
    DECLARED_TOOLS_ONLY = "declared_tools_only"
    CONTROLLED_FILE_TOOLS = "controlled_file_tools"
    SKILL_REPOSITORY_READ = "skill_repository_read"
    SKILL_REPOSITORY_EXECUTE = "skill_repository_execute"


class RuntimeFilePermission(StrEnum):
    """Declarative file access permission labels."""

    NONE = "none"
    FILE_REF_METADATA_ONLY = "file_ref_metadata_only"
    CONTROLLED_READ = "controlled_read"
    CONTROLLED_WRITE_REQUEST = "controlled_write_request"


class RuntimeMemoryPolicy(StrEnum):
    """Declarative runtime-local memory policy labels."""

    NONE = "none"
    RUNTIME_LOCAL_EPHEMERAL = "runtime_local_ephemeral"
    RUNTIME_LOCAL_PERSISTENT_RESERVED = "runtime_local_persistent_reserved"


class RuntimeNetworkPolicy(StrEnum):
    """Declarative network policy labels. No network path is opened here."""

    DISABLED = "disabled"
    LOCAL_ONLY_RESERVED = "local_only_reserved"


@dataclass(frozen=True, slots=True)
class AgentRuntimeAccessProfile:
    """User-selected permission contract for a model or agent runtime."""

    runtime_kind: AgentRuntimeKind | str = AgentRuntimeKind.PROVIDER_BACKED_MODEL
    delegated_context_delivery: DelegatedContextDeliveryPolicy | str = (
        DelegatedContextDeliveryPolicy.NONE
    )
    tool_permissions: tuple[RuntimeToolPermission | str, ...] = (
        RuntimeToolPermission.NONE,
    )
    file_permission: RuntimeFilePermission | str = (
        RuntimeFilePermission.FILE_REF_METADATA_ONLY
    )
    memory_policy: RuntimeMemoryPolicy | str = RuntimeMemoryPolicy.NONE
    network_policy: RuntimeNetworkPolicy | str = RuntimeNetworkPolicy.DISABLED
    allowed_tool_names: tuple[str, ...] = ()
    allowed_skill_refs: tuple[str, ...] = ()
    memory_namespace: str | None = None
    memory_quota_mb: int | None = None
    runtime_connection_ref: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def default(cls) -> "AgentRuntimeAccessProfile":
        return cls()

    @classmethod
    def from_mapping(
        cls,
        source: Mapping[str, object] | None,
        *,
        runtime_kind: str | None = None,
    ) -> "AgentRuntimeAccessProfile":
        config = dict(source or {})
        _reject_sensitive_config(config, "runtimeAccess")
        inherited_runtime_kind = (
            _agent_runtime_kind_value(runtime_kind)
            if runtime_kind is not None
            else AgentRuntimeKind.PROVIDER_BACKED_MODEL
        )
        configured_runtime_kind = _optional_value(
            config,
            "runtime_kind",
            "runtimeKind",
            "kind",
        )
        if configured_runtime_kind is not None:
            parsed_runtime_kind = _agent_runtime_kind_value(configured_runtime_kind)
            if runtime_kind is not None and parsed_runtime_kind is not inherited_runtime_kind:
                raise ValueError("runtimeAccess.runtimeKind must match runtimeKind.")
            inherited_runtime_kind = parsed_runtime_kind

        return cls(
            runtime_kind=inherited_runtime_kind,
            delegated_context_delivery=_optional_value(
                config,
                "delegated_context_delivery",
                "delegatedContextDelivery",
            )
            or DelegatedContextDeliveryPolicy.NONE,
            tool_permissions=_tool_permission_tuple(
                _optional_value(config, "tool_permissions", "toolPermissions")
            ),
            file_permission=_optional_value(
                config,
                "file_permission",
                "filePermission",
            )
            or RuntimeFilePermission.FILE_REF_METADATA_ONLY,
            memory_policy=_optional_value(config, "memory_policy", "memoryPolicy")
            or RuntimeMemoryPolicy.NONE,
            network_policy=_optional_value(config, "network_policy", "networkPolicy")
            or RuntimeNetworkPolicy.DISABLED,
            allowed_tool_names=_text_tuple(
                _optional_value(config, "allowed_tool_names", "allowedToolNames"),
                "allowedToolNames",
            ),
            allowed_skill_refs=_text_tuple(
                _optional_value(config, "allowed_skill_refs", "allowedSkillRefs"),
                "allowedSkillRefs",
            ),
            memory_namespace=_optional_text(
                config,
                "memory_namespace",
                "memoryNamespace",
            ),
            memory_quota_mb=_optional_positive_int(
                config,
                "memory_quota_mb",
                "memoryQuotaMb",
            ),
            runtime_connection_ref=_optional_text(
                config,
                "runtime_connection_ref",
                "runtimeConnectionRef",
                "connectionRef",
            ),
            metadata=dict(_optional_mapping(config, "metadata") or {}),
        )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "runtime_kind",
            _agent_runtime_kind_value(self.runtime_kind),
        )
        object.__setattr__(
            self,
            "delegated_context_delivery",
            _delegated_context_delivery_policy_value(
                self.delegated_context_delivery
            ),
        )
        object.__setattr__(
            self,
            "tool_permissions",
            tuple(_runtime_tool_permission_value(item) for item in self.tool_permissions),
        )
        object.__setattr__(
            self,
            "file_permission",
            _runtime_file_permission_value(self.file_permission),
        )
        object.__setattr__(
            self,
            "memory_policy",
            _runtime_memory_policy_value(self.memory_policy),
        )
        object.__setattr__(
            self,
            "network_policy",
            _runtime_network_policy_value(self.network_policy),
        )
        _validate_unique_enum_tuple(self.tool_permissions, "toolPermissions")
        _validate_none_is_exclusive(self.tool_permissions, "toolPermissions")
        _validate_text_tuple(self.allowed_tool_names, "allowedToolNames")
        _validate_text_tuple(self.allowed_skill_refs, "allowedSkillRefs")
        if self.memory_namespace is not None:
            _require_non_empty(self.memory_namespace, "memoryNamespace")
            _reject_transport_uri(self.memory_namespace, "memoryNamespace")
        if self.memory_quota_mb is not None and self.memory_quota_mb < 1:
            raise ValueError("memoryQuotaMb must be positive.")
        if self.runtime_connection_ref is not None:
            _require_non_empty(self.runtime_connection_ref, "runtimeConnectionRef")
            _reject_transport_uri(
                self.runtime_connection_ref,
                "runtimeConnectionRef",
            )
        _reject_sensitive_config(self.metadata, "runtimeAccess.metadata")
        _reject_transport_config(self.metadata, "runtimeAccess.metadata")
        self._validate_runtime_kind_permissions()

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "runtime_kind": self.runtime_kind.value,
            "delegated_context_delivery": self.delegated_context_delivery.value,
            "tool_permissions": [item.value for item in self.tool_permissions],
            "file_permission": self.file_permission.value,
            "memory_policy": self.memory_policy.value,
            "network_policy": self.network_policy.value,
            "real_runtime_connected": False,
            "websocket_transport_connected": False,
            "credential_store_connected": False,
        }
        if self.allowed_tool_names:
            metadata["allowed_tool_names"] = list(self.allowed_tool_names)
        if self.allowed_skill_refs:
            metadata["allowed_skill_refs"] = list(self.allowed_skill_refs)
        if self.memory_namespace is not None:
            metadata["memory_namespace"] = self.memory_namespace
        if self.memory_quota_mb is not None:
            metadata["memory_quota_mb"] = self.memory_quota_mb
        if self.runtime_connection_ref is not None:
            metadata["runtime_connection_ref"] = self.runtime_connection_ref
        if self.metadata:
            metadata["metadata"] = dict(self.metadata)
        return metadata

    def _validate_runtime_kind_permissions(self) -> None:
        if self.runtime_kind is not AgentRuntimeKind.PROVIDER_BACKED_MODEL:
            return
        if self.delegated_context_delivery not in {
            DelegatedContextDeliveryPolicy.NONE,
            DelegatedContextDeliveryPolicy.METADATA_REFS_ONLY,
        }:
            raise ValueError(
                "provider-backed runtime cannot receive materialized delegated context."
            )
        if self.tool_permissions != (RuntimeToolPermission.NONE,):
            raise ValueError(
                "provider-backed runtime must not declare agent-native tool permissions."
            )
        if self.memory_policy is not RuntimeMemoryPolicy.NONE:
            raise ValueError(
                "provider-backed runtime must not declare runtime-local memory."
            )
        if self.network_policy is not RuntimeNetworkPolicy.DISABLED:
            raise ValueError("provider-backed runtime network policy must be disabled.")


@dataclass(frozen=True, slots=True)
class AgentRuntimeDeliverySegmentRef:
    """Metadata-only reference to a future deliverable materialized segment."""

    segment_id: str
    source_packet_item_id: str
    segment_kind: str
    load_state: str
    content_loaded: bool

    @classmethod
    def from_segment(
        cls,
        segment: ContextMaterializedSegment,
    ) -> "AgentRuntimeDeliverySegmentRef":
        return cls(
            segment_id=segment.segment_id,
            source_packet_item_id=segment.source_packet_item_id,
            segment_kind=segment.segment_kind.value,
            load_state=segment.load_state.value,
            content_loaded=segment.content_loaded,
        )

    def to_metadata(self) -> Mapping[str, object]:
        return {
            "segment_id": self.segment_id,
            "source_packet_item_id": self.source_packet_item_id,
            "segment_kind": self.segment_kind,
            "load_state": self.load_state,
            "content_loaded": self.content_loaded,
            "text_included": False,
        }


@dataclass(frozen=True, slots=True)
class AgentRuntimeDeliveryDeniedRef:
    """Records why a materialized segment is not deliverable to a runtime."""

    segment_id: str
    source_packet_item_id: str
    reason: str

    def to_metadata(self) -> Mapping[str, object]:
        return {
            "segment_id": self.segment_id,
            "source_packet_item_id": self.source_packet_item_id,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class AgentRuntimeDeliveryPlan:
    """Metadata-only delivery plan for future agent/runtime adapters."""

    delivery_plan_id: str
    runtime_kind: AgentRuntimeKind | str
    delegated_context_delivery: DelegatedContextDeliveryPolicy | str
    materialization_id: str | None = None
    source_packet_id: str | None = None
    deliverable_segments: tuple[AgentRuntimeDeliverySegmentRef, ...] = ()
    denied_segments: tuple[AgentRuntimeDeliveryDeniedRef, ...] = ()
    delegated_context_delivered: bool = False
    real_runtime_connected: bool = False
    provider_prompt_injected: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.delivery_plan_id, "deliveryPlanId")
        object.__setattr__(
            self,
            "runtime_kind",
            _agent_runtime_kind_value(self.runtime_kind),
        )
        object.__setattr__(
            self,
            "delegated_context_delivery",
            _delegated_context_delivery_policy_value(
                self.delegated_context_delivery
            ),
        )
        if self.delegated_context_delivered:
            raise ValueError("delegatedContextDelivered must remain false.")
        if self.real_runtime_connected:
            raise ValueError("realRuntimeConnected must remain false.")
        if self.provider_prompt_injected:
            raise ValueError("providerPromptInjected must remain false.")
        _reject_sensitive_config(self.metadata, "runtimeDelivery.metadata")
        _reject_transport_config(self.metadata, "runtimeDelivery.metadata")

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "delivery_plan_id": self.delivery_plan_id,
            "runtime_kind": self.runtime_kind.value,
            "delegated_context_delivery": self.delegated_context_delivery.value,
            "deliverable_segments": [
                segment.to_metadata() for segment in self.deliverable_segments
            ],
            "denied_segments": [
                segment.to_metadata() for segment in self.denied_segments
            ],
            "delegated_context_delivered": self.delegated_context_delivered,
            "real_runtime_connected": self.real_runtime_connected,
            "provider_prompt_injected": self.provider_prompt_injected,
            "materialized_text_included": False,
            "file_bodies_included": False,
            "websocket_transport_connected": False,
        }
        if self.materialization_id is not None:
            metadata["materialization_id"] = self.materialization_id
        if self.source_packet_id is not None:
            metadata["source_packet_id"] = self.source_packet_id
        if self.metadata:
            metadata["metadata"] = dict(self.metadata)
        return metadata


@dataclass(frozen=True, slots=True)
class AgentRuntimeAccessGrant:
    """Auditable runtime access authorization result."""

    grant_id: str
    agent_id: str
    invocation_id: str
    access_profile: AgentRuntimeAccessProfile
    delivery_plan: AgentRuntimeDeliveryPlan
    allowed_permissions: tuple[str, ...]
    denied_permissions: tuple[str, ...]
    revoked: bool = False
    expires_at: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.grant_id, "runtimeAccessGrant.grantId")
        _require_non_empty(self.agent_id, "runtimeAccessGrant.agentId")
        _require_non_empty(self.invocation_id, "runtimeAccessGrant.invocationId")
        _validate_text_tuple(self.allowed_permissions, "allowedPermissions")
        _validate_text_tuple(self.denied_permissions, "deniedPermissions")
        if self.expires_at is not None:
            _require_non_empty(self.expires_at, "runtimeAccessGrant.expiresAt")
        _reject_sensitive_config(self.metadata, "runtimeAccessGrant.metadata")
        _reject_transport_config(self.metadata, "runtimeAccessGrant.metadata")

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "grant_id": self.grant_id,
            "agent_id": self.agent_id,
            "invocation_id": self.invocation_id,
            "runtime_kind": self.access_profile.runtime_kind.value,
            "access_profile": self.access_profile.to_metadata(),
            "delivery_plan": self.delivery_plan.to_metadata(),
            "allowed_permissions": list(self.allowed_permissions),
            "denied_permissions": list(self.denied_permissions),
            "revoked": self.revoked,
            "real_runtime_connected": False,
            "credential_store_connected": False,
        }
        if self.expires_at is not None:
            metadata["expires_at"] = self.expires_at
        if self.metadata:
            metadata["metadata"] = dict(self.metadata)
        return metadata


class AgentRuntimeAccessPlanner:
    """Build a metadata-only runtime access grant from an access profile."""

    def plan(
        self,
        *,
        access_profile: AgentRuntimeAccessProfile,
        agent_id: str,
        invocation_id: str,
        materialization: ContextMaterializationPlan | None = None,
    ) -> AgentRuntimeAccessGrant:
        _require_non_empty(agent_id, "agent_id")
        _require_non_empty(invocation_id, "invocation_id")
        delivery_plan = _delivery_plan(
            access_profile=access_profile,
            invocation_id=invocation_id,
            materialization=materialization,
        )
        return AgentRuntimeAccessGrant(
            grant_id=f"runtime-access-{invocation_id}",
            agent_id=agent_id,
            invocation_id=invocation_id,
            access_profile=access_profile,
            delivery_plan=delivery_plan,
            allowed_permissions=_allowed_permissions(access_profile),
            denied_permissions=_denied_permissions(access_profile),
            metadata={
                "policy_mode": "metadata_only_runtime_access_contract",
                "prompt_delivery_deferred": True,
                "runtime_connector_deferred": True,
            },
        )


def _delivery_plan(
    *,
    access_profile: AgentRuntimeAccessProfile,
    invocation_id: str,
    materialization: ContextMaterializationPlan | None,
) -> AgentRuntimeDeliveryPlan:
    materialized_segments = (
        materialization.materialized_segments if materialization is not None else ()
    )
    if (
        access_profile.delegated_context_delivery
        is DelegatedContextDeliveryPolicy.BOUNDED_MATERIALIZED_SEGMENTS
    ):
        deliverable = tuple(
            AgentRuntimeDeliverySegmentRef.from_segment(segment)
            for segment in materialized_segments
        )
        denied: tuple[AgentRuntimeDeliveryDeniedRef, ...] = ()
        reason = "bounded_materialized_segment_refs_allowed"
    elif (
        access_profile.delegated_context_delivery
        is DelegatedContextDeliveryPolicy.METADATA_REFS_ONLY
    ):
        deliverable = tuple(
            AgentRuntimeDeliverySegmentRef.from_segment(segment)
            for segment in materialized_segments
        )
        denied = ()
        reason = "metadata_refs_only"
    else:
        deliverable = ()
        denied = tuple(
            AgentRuntimeDeliveryDeniedRef(
                segment_id=segment.segment_id,
                source_packet_item_id=segment.source_packet_item_id,
                reason="delegated_context_delivery_disabled",
            )
            for segment in materialized_segments
        )
        reason = "delegated_context_delivery_disabled"

    return AgentRuntimeDeliveryPlan(
        delivery_plan_id=f"runtime-delivery-{invocation_id}",
        runtime_kind=access_profile.runtime_kind,
        delegated_context_delivery=access_profile.delegated_context_delivery,
        materialization_id=(
            materialization.materialization_id if materialization is not None else None
        ),
        source_packet_id=(
            materialization.source_packet_id if materialization is not None else None
        ),
        deliverable_segments=deliverable,
        denied_segments=denied,
        metadata={
            "delivery_reason": reason,
            "source_policy": "selected_materialized_segments_only",
            "text_delivery_deferred": True,
        },
    )


def _allowed_permissions(profile: AgentRuntimeAccessProfile) -> tuple[str, ...]:
    permissions = [
        f"runtime_kind:{profile.runtime_kind.value}",
        f"delegated_context:{profile.delegated_context_delivery.value}",
        f"file:{profile.file_permission.value}",
        f"memory:{profile.memory_policy.value}",
        f"network:{profile.network_policy.value}",
    ]
    permissions.extend(f"tool:{permission.value}" for permission in profile.tool_permissions)
    if profile.allowed_tool_names:
        permissions.append("tool_names:declared")
    if profile.allowed_skill_refs:
        permissions.append("skill_refs:declared")
    return tuple(permissions)


def _denied_permissions(profile: AgentRuntimeAccessProfile) -> tuple[str, ...]:
    denied = [
        "real_runtime_connection",
        "credential_store",
        "websocket_transport",
        "file_body_read",
        "provider_prompt_injection",
    ]
    if profile.network_policy is RuntimeNetworkPolicy.DISABLED:
        denied.append("network")
    if profile.memory_policy is RuntimeMemoryPolicy.NONE:
        denied.append("runtime_local_memory")
    if profile.tool_permissions == (RuntimeToolPermission.NONE,):
        denied.append("tool_execution")
    return tuple(denied)


def _agent_runtime_kind_value(value: AgentRuntimeKind | str) -> AgentRuntimeKind:
    if isinstance(value, AgentRuntimeKind):
        return value
    normalized = _normalized_label_value(value, "runtimeKind")
    aliases = {
        "provider_backed_model": AgentRuntimeKind.PROVIDER_BACKED_MODEL,
        "provider_backed": AgentRuntimeKind.PROVIDER_BACKED_MODEL,
        "provider_model": AgentRuntimeKind.PROVIDER_BACKED_MODEL,
        "provider_connection": AgentRuntimeKind.PROVIDER_BACKED_MODEL,
        "agent_native_runtime": AgentRuntimeKind.AGENT_NATIVE_RUNTIME,
        "agent_native": AgentRuntimeKind.AGENT_NATIVE_RUNTIME,
        "external_agent_bridge": AgentRuntimeKind.EXTERNAL_AGENT_BRIDGE,
        "external_agent": AgentRuntimeKind.EXTERNAL_AGENT_BRIDGE,
        "browser_session_runtime": AgentRuntimeKind.BROWSER_SESSION_RUNTIME,
        "browser_runtime": AgentRuntimeKind.BROWSER_SESSION_RUNTIME,
        "web_session_runtime": AgentRuntimeKind.BROWSER_SESSION_RUNTIME,
        "ide_agent_runtime": AgentRuntimeKind.IDE_AGENT_RUNTIME,
        "ide_runtime": AgentRuntimeKind.IDE_AGENT_RUNTIME,
        "reserved": AgentRuntimeKind.RESERVED,
    }
    if normalized in aliases:
        return aliases[normalized]
    valid = ", ".join(kind.value for kind in AgentRuntimeKind)
    raise ValueError(f"runtimeKind must be one of: {valid}.")


def _delegated_context_delivery_policy_value(
    value: DelegatedContextDeliveryPolicy | str,
) -> DelegatedContextDeliveryPolicy:
    if isinstance(value, DelegatedContextDeliveryPolicy):
        return value
    normalized = _normalized_label_value(value, "delegatedContextDelivery")
    aliases = {
        "none": DelegatedContextDeliveryPolicy.NONE,
        "metadata_refs_only": DelegatedContextDeliveryPolicy.METADATA_REFS_ONLY,
        "metadata_only": DelegatedContextDeliveryPolicy.METADATA_REFS_ONLY,
        "bounded_materialized_segments": (
            DelegatedContextDeliveryPolicy.BOUNDED_MATERIALIZED_SEGMENTS
        ),
        "materialized_segments": (
            DelegatedContextDeliveryPolicy.BOUNDED_MATERIALIZED_SEGMENTS
        ),
        "agent_managed_context_ref": (
            DelegatedContextDeliveryPolicy.AGENT_MANAGED_CONTEXT_REF
        ),
    }
    if normalized in aliases:
        return aliases[normalized]
    valid = ", ".join(policy.value for policy in DelegatedContextDeliveryPolicy)
    raise ValueError(f"delegatedContextDelivery must be one of: {valid}.")


def _runtime_tool_permission_value(
    value: RuntimeToolPermission | str,
) -> RuntimeToolPermission:
    if isinstance(value, RuntimeToolPermission):
        return value
    normalized = _normalized_label_value(value, "toolPermission")
    aliases = {
        "none": RuntimeToolPermission.NONE,
        "declared_tools_only": RuntimeToolPermission.DECLARED_TOOLS_ONLY,
        "controlled_file_tools": RuntimeToolPermission.CONTROLLED_FILE_TOOLS,
        "skill_repository_read": RuntimeToolPermission.SKILL_REPOSITORY_READ,
        "skill_repository_execute": RuntimeToolPermission.SKILL_REPOSITORY_EXECUTE,
    }
    if normalized in aliases:
        return aliases[normalized]
    valid = ", ".join(permission.value for permission in RuntimeToolPermission)
    raise ValueError(f"toolPermission must be one of: {valid}.")


def _runtime_file_permission_value(
    value: RuntimeFilePermission | str,
) -> RuntimeFilePermission:
    if isinstance(value, RuntimeFilePermission):
        return value
    normalized = _normalized_label_value(value, "filePermission")
    aliases = {
        "none": RuntimeFilePermission.NONE,
        "file_ref_metadata_only": RuntimeFilePermission.FILE_REF_METADATA_ONLY,
        "metadata_only": RuntimeFilePermission.FILE_REF_METADATA_ONLY,
        "controlled_read": RuntimeFilePermission.CONTROLLED_READ,
        "controlled_write_request": RuntimeFilePermission.CONTROLLED_WRITE_REQUEST,
    }
    if normalized in aliases:
        return aliases[normalized]
    valid = ", ".join(permission.value for permission in RuntimeFilePermission)
    raise ValueError(f"filePermission must be one of: {valid}.")


def _runtime_memory_policy_value(
    value: RuntimeMemoryPolicy | str,
) -> RuntimeMemoryPolicy:
    if isinstance(value, RuntimeMemoryPolicy):
        return value
    normalized = _normalized_label_value(value, "memoryPolicy")
    aliases = {
        "none": RuntimeMemoryPolicy.NONE,
        "runtime_local_ephemeral": RuntimeMemoryPolicy.RUNTIME_LOCAL_EPHEMERAL,
        "ephemeral": RuntimeMemoryPolicy.RUNTIME_LOCAL_EPHEMERAL,
        "runtime_local_persistent_reserved": (
            RuntimeMemoryPolicy.RUNTIME_LOCAL_PERSISTENT_RESERVED
        ),
        "persistent_reserved": RuntimeMemoryPolicy.RUNTIME_LOCAL_PERSISTENT_RESERVED,
    }
    if normalized in aliases:
        return aliases[normalized]
    valid = ", ".join(policy.value for policy in RuntimeMemoryPolicy)
    raise ValueError(f"memoryPolicy must be one of: {valid}.")


def _runtime_network_policy_value(
    value: RuntimeNetworkPolicy | str,
) -> RuntimeNetworkPolicy:
    if isinstance(value, RuntimeNetworkPolicy):
        return value
    normalized = _normalized_label_value(value, "networkPolicy")
    aliases = {
        "disabled": RuntimeNetworkPolicy.DISABLED,
        "none": RuntimeNetworkPolicy.DISABLED,
        "local_only_reserved": RuntimeNetworkPolicy.LOCAL_ONLY_RESERVED,
        "local_only": RuntimeNetworkPolicy.LOCAL_ONLY_RESERVED,
    }
    if normalized in aliases:
        return aliases[normalized]
    valid = ", ".join(policy.value for policy in RuntimeNetworkPolicy)
    raise ValueError(f"networkPolicy must be one of: {valid}.")


def _tool_permission_tuple(value: object | None) -> tuple[RuntimeToolPermission, ...]:
    if value is None:
        return (RuntimeToolPermission.NONE,)
    if isinstance(value, str):
        return (_runtime_tool_permission_value(value),)
    if isinstance(value, Sequence):
        return tuple(_runtime_tool_permission_value(item) for item in value)
    raise ValueError("toolPermissions must be a string or list.")


def _text_tuple(value: object | None, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (_require_text(value, field_name),)
    if isinstance(value, Sequence):
        return tuple(_require_text(item, field_name) for item in value)
    raise ValueError(f"{field_name} must be a string or list.")


def _validate_text_tuple(values: tuple[str, ...], field_name: str) -> None:
    seen: set[str] = set()
    for value in values:
        _require_non_empty(value, field_name)
        _reject_transport_uri(value, field_name)
        if value in seen:
            raise ValueError(f"{field_name} must not contain duplicate values.")
        seen.add(value)


def _validate_unique_enum_tuple(values: tuple[StrEnum, ...], field_name: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicate values.")


def _validate_none_is_exclusive(values: tuple[StrEnum, ...], field_name: str) -> None:
    if any(value.value == "none" for value in values) and len(values) > 1:
        raise ValueError(f"{field_name} cannot combine none with other values.")


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
    return _require_text(value, keys[0])


def _optional_positive_int(source: Mapping[str, object], *keys: str) -> int | None:
    value = _optional_value(source, *keys)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{keys[0]} must be a positive integer.")
    return value


def _optional_value(source: Mapping[str, object], *keys: str) -> object | None:
    for key in keys:
        if key in source:
            return source[key]
    return None


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


def _normalized_label_value(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip().lower().replace("-", "_")


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

_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9]{20,}|Bearer\s+sk-|Authorization:\s*Bearer|Cookie:)",
    re.IGNORECASE,
)

_TRANSPORT_URI_PATTERN = re.compile(r"\b(?:ws|wss)://", re.IGNORECASE)


def _reject_sensitive_config(source: Mapping[str, object], logical_name: str) -> None:
    for key, value in source.items():
        normalized = _normalized_key(key)
        if normalized in _SENSITIVE_KEYS:
            raise ValueError(f"{logical_name}.{key} must not contain credential values.")
        if isinstance(value, str) and _SENSITIVE_TEXT_PATTERN.search(value):
            raise ValueError(f"{logical_name}.{key} must not contain credential values.")
        if isinstance(value, Mapping):
            if normalized in _REFERENCE_KEYS:
                continue
            _reject_sensitive_config(value, f"{logical_name}.{key}")
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, Mapping):
                    _reject_sensitive_config(item, f"{logical_name}.{key}")
                elif isinstance(item, str) and _SENSITIVE_TEXT_PATTERN.search(item):
                    raise ValueError(
                        f"{logical_name}.{key} must not contain credential values."
                    )


def _reject_transport_config(source: Mapping[str, object], logical_name: str) -> None:
    for key, value in source.items():
        current_name = f"{logical_name}.{key}"
        if isinstance(value, str):
            _reject_transport_uri(value, current_name)
        elif isinstance(value, Mapping):
            _reject_transport_config(value, current_name)
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str):
                    _reject_transport_uri(item, current_name)
                elif isinstance(item, Mapping):
                    _reject_transport_config(item, current_name)


def _reject_transport_uri(value: str, logical_name: str) -> None:
    if _TRANSPORT_URI_PATTERN.search(value):
        raise ValueError(f"{logical_name} must not contain WebSocket transport URIs.")


def _normalized_key(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())
