from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping, Sequence


class ContextManagementStrategy(StrEnum):
    """User-selectable context assembly strategy families."""

    PASS_THROUGH = "pass-through"
    RECENT_WINDOW = "recent-window"
    PLATFORM_SUMMARY = "platform-summary"
    PROVIDER_NATIVE = "provider-native"
    EXTERNAL_CONTEXT_ENGINE = "external-context-engine"
    HYBRID = "hybrid"


class ContextOverflowMode(StrEnum):
    """Stable overflow policy labels for context assembly."""

    FAIL_WITH_EXPLANATION = "fail_with_explanation"
    TRIM_TO_BUDGET = "trim_to_budget"
    COMPACT_THEN_RETRY = "compact_then_retry"


class ContextWindowSelectionPolicy(StrEnum):
    """Stable policy labels for source-ref window selection."""

    METADATA_ONLY_AUTHORIZED_REFS = "metadata_only_authorized_refs"


class ContextContentPacketDeliveryMode(StrEnum):
    """Reserved delivery labels for selected-source content packets."""

    AUDIT_ONLY = "audit_only"
    PROVIDER_PROMPT_PACKET = "provider_prompt_packet"
    AGENT_NATIVE_DELEGATED_CONTEXT = "agent_native_delegated_context"


class ContextContentState(StrEnum):
    """Stable content-loading state labels for packet contract items."""

    REF_ONLY = "ref_only"
    NOT_LOADED = "not_loaded"
    ALREADY_IN_USER_MESSAGE = "already_in_user_message"
    LOADER_NOT_CONNECTED = "loader_not_connected"
    RESERVED_SCOPE_NOT_CONNECTED = "reserved_scope_not_connected"
    OMITTED_BY_WINDOW_SELECTION = "omitted_by_window_selection"
    DENIED_BY_AUTHORIZATION = "denied_by_authorization"
    REDACTED = "redacted"
    ERROR = "error"


class ContextContentKind(StrEnum):
    """Stable content kind labels for selected source refs."""

    CURRENT_USER_INSTRUCTION = "current_user_instruction"
    CONVERSATION_REF = "conversation_ref"
    SHARED_CONTEXT_REF = "shared_context_ref"
    TASK_REF = "task_ref"
    FILE_REF = "file_ref"
    AGENT_PRIVATE_MEMORY_REF = "agent_private_memory_ref"
    PROVIDER_NATIVE_SESSION_REF = "provider_native_session_ref"
    EXTERNAL_CONTEXT_ENGINE_REF = "external_context_engine_ref"


class ContextMaterializationLoadState(StrEnum):
    """Stable local materialization state labels."""

    ALREADY_IN_USER_MESSAGE = "already_in_user_message"
    LOADED = "loaded"
    TRUNCATED_TO_BUDGET = "truncated_to_budget"
    LOADER_NOT_CONNECTED = "loader_not_connected"
    DEFERRED_FILE_BODY = "deferred_file_body"
    RESERVED_SCOPE_NOT_CONNECTED = "reserved_scope_not_connected"
    REDACTED = "redacted"
    ERROR = "error"


class ContextMaterializedSegmentKind(StrEnum):
    """Stable labels for bounded local context segments."""

    CURRENT_USER_MESSAGE_MARKER = "current_user_message_marker"
    CONVERSATION_MESSAGE_WINDOW = "conversation_message_window"
    SHARED_CONTEXT_UPDATE_SUMMARY = "shared_context_update_summary"
    TASK_CONTEXT_SUMMARY = "task_context_summary"
    FILE_REF_MARKER = "file_ref_marker"
    RESERVED_SCOPE_MARKER = "reserved_scope_marker"


class ContextAccessScope(StrEnum):
    """Stable pre-invocation context access scope labels."""

    CURRENT_USER_INSTRUCTION = "current_user_instruction"
    RECENT_MESSAGES = "recent_messages"
    PROJECT_SHARED_CONTEXT = "project_shared_context"
    CURRENT_TASK = "current_task"
    REFERENCED_FILES = "referenced_files"
    AGENT_PRIVATE_MEMORY = "agent_private_memory"
    PROVIDER_NATIVE_SESSION_REF = "provider_native_session_ref"
    EXTERNAL_CONTEXT_ENGINE = "external_context_engine"


class ContextAssemblyError(ValueError):
    """Stable error for context assembly boundary failures."""


@dataclass(frozen=True, slots=True)
class AgentPrivateMemoryConfig:
    """Reserved agent-private memory settings; no storage is connected here."""

    enabled: bool = False
    quota_mb: int | None = None
    ttl_seconds: int | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.quota_mb is not None and self.quota_mb <= 0:
            raise ValueError("agentPrivateMemory.quotaMb must be positive.")
        if self.ttl_seconds is not None and self.ttl_seconds <= 0:
            raise ValueError("agentPrivateMemory.ttlSeconds must be positive.")
        _reject_sensitive_config(self.metadata, "agentPrivateMemory.metadata")

    @classmethod
    def from_mapping(
        cls,
        source: Mapping[str, object] | None,
    ) -> "AgentPrivateMemoryConfig":
        if source is None:
            return cls()
        _reject_unknown_keys(
            source,
            {
                "enabled",
                "quota_mb",
                "quotaMb",
                "ttl_seconds",
                "ttlSeconds",
                "metadata",
            },
            "agentPrivateMemory",
        )
        _reject_sensitive_config(source, "agentPrivateMemory")
        return cls(
            enabled=_optional_bool(source, "enabled", default=False),
            quota_mb=_optional_int(source, "quota_mb", "quotaMb"),
            ttl_seconds=_optional_int(source, "ttl_seconds", "ttlSeconds"),
            metadata=dict(_optional_mapping(source, "metadata") or {}),
        )

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {"enabled": self.enabled}
        if self.quota_mb is not None:
            metadata["quota_mb"] = self.quota_mb
        if self.ttl_seconds is not None:
            metadata["ttl_seconds"] = self.ttl_seconds
        if self.metadata:
            metadata["metadata"] = dict(self.metadata)
        return metadata


@dataclass(frozen=True, slots=True)
class ProviderNativeContextConfig:
    """Reserved provider-native context settings; no remote session is opened."""

    session_mode: str | None = None
    compaction_mode: str | None = None
    remote_session_ref_mode: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("providerNative.sessionMode", self.session_mode),
            ("providerNative.compactionMode", self.compaction_mode),
            ("providerNative.remoteSessionRefMode", self.remote_session_ref_mode),
        ):
            if value is not None:
                _require_non_empty(value, field_name)
        _reject_sensitive_config(self.metadata, "providerNative.metadata")

    @classmethod
    def from_mapping(
        cls,
        source: Mapping[str, object] | None,
    ) -> "ProviderNativeContextConfig":
        if source is None:
            return cls()
        _reject_unknown_keys(
            source,
            {
                "session_mode",
                "sessionMode",
                "compaction_mode",
                "compactionMode",
                "remote_session_ref_mode",
                "remoteSessionRefMode",
                "metadata",
            },
            "providerNative",
        )
        _reject_sensitive_config(source, "providerNative")
        return cls(
            session_mode=_optional_text(source, "session_mode", "sessionMode"),
            compaction_mode=_optional_text(
                source,
                "compaction_mode",
                "compactionMode",
            ),
            remote_session_ref_mode=_optional_text(
                source,
                "remote_session_ref_mode",
                "remoteSessionRefMode",
            ),
            metadata=dict(_optional_mapping(source, "metadata") or {}),
        )

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {}
        if self.session_mode is not None:
            metadata["session_mode"] = self.session_mode
        if self.compaction_mode is not None:
            metadata["compaction_mode"] = self.compaction_mode
        if self.remote_session_ref_mode is not None:
            metadata["remote_session_ref_mode"] = self.remote_session_ref_mode
        if self.metadata:
            metadata["metadata"] = dict(self.metadata)
        return metadata


@dataclass(frozen=True, slots=True)
class ExternalContextEngineConfig:
    """Reserved external context-engine settings; no engine is connected."""

    engine_id: str | None = None
    mode: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.engine_id is not None:
            _require_non_empty(self.engine_id, "externalContextEngine.engineId")
        if self.mode is not None:
            _require_non_empty(self.mode, "externalContextEngine.mode")
        _reject_sensitive_config(self.metadata, "externalContextEngine.metadata")

    @classmethod
    def from_mapping(
        cls,
        source: Mapping[str, object] | None,
    ) -> "ExternalContextEngineConfig":
        if source is None:
            return cls()
        _reject_unknown_keys(
            source,
            {"engine_id", "engineId", "mode", "metadata"},
            "externalContextEngine",
        )
        _reject_sensitive_config(source, "externalContextEngine")
        return cls(
            engine_id=_optional_text(source, "engine_id", "engineId"),
            mode=_optional_text(source, "mode"),
            metadata=dict(_optional_mapping(source, "metadata") or {}),
        )

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {}
        if self.engine_id is not None:
            metadata["engine_id"] = self.engine_id
        if self.mode is not None:
            metadata["mode"] = self.mode
        if self.metadata:
            metadata["metadata"] = dict(self.metadata)
        return metadata


@dataclass(frozen=True, slots=True)
class ContextManagementProfile:
    """Validated context-management policy configuration."""

    strategy: ContextManagementStrategy = ContextManagementStrategy.PASS_THROUGH
    max_input_tokens: int = 8192
    recent_message_limit: int | None = None
    recent_token_budget: int | None = None
    include_conversation_history: bool = False
    include_shared_context: bool = False
    include_task_context: bool = False
    include_file_references: bool = False
    allowed_context_scopes: tuple[str, ...] = ("current_user_instruction",)
    window_selection_policy: ContextWindowSelectionPolicy = (
        ContextWindowSelectionPolicy.METADATA_ONLY_AUTHORIZED_REFS
    )
    content_packet_delivery_mode: ContextContentPacketDeliveryMode = (
        ContextContentPacketDeliveryMode.AUDIT_ONLY
    )
    agent_private_memory: AgentPrivateMemoryConfig = field(
        default_factory=AgentPrivateMemoryConfig
    )
    provider_native: ProviderNativeContextConfig = field(
        default_factory=ProviderNativeContextConfig
    )
    external_context_engine: ExternalContextEngineConfig = field(
        default_factory=ExternalContextEngineConfig
    )
    on_overflow: ContextOverflowMode = ContextOverflowMode.FAIL_WITH_EXPLANATION
    keep_source_refs: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_input_tokens <= 0:
            raise ValueError("maxInputTokens must be positive.")
        if self.recent_message_limit is not None and self.recent_message_limit < 0:
            raise ValueError("recentMessageLimit must be non-negative.")
        if self.recent_token_budget is not None and self.recent_token_budget <= 0:
            raise ValueError("recentTokenBudget must be positive.")
        object.__setattr__(
            self,
            "allowed_context_scopes",
            _context_scope_tuple(
                self.allowed_context_scopes,
                "allowedContextScopes",
            ),
        )
        object.__setattr__(
            self,
            "window_selection_policy",
            _window_selection_policy_value(self.window_selection_policy),
        )
        object.__setattr__(
            self,
            "content_packet_delivery_mode",
            _content_packet_delivery_mode_value(self.content_packet_delivery_mode),
        )
        _reject_sensitive_config(self.metadata, "contextManagement.metadata")

    @classmethod
    def default(cls) -> "ContextManagementProfile":
        return cls()

    @classmethod
    def from_mapping(
        cls,
        source: Mapping[str, object] | None,
    ) -> "ContextManagementProfile":
        if source is None:
            return cls.default()
        _reject_unknown_keys(
            source,
            {
                "strategy",
                "max_input_tokens",
                "maxInputTokens",
                "recent_message_limit",
                "recentMessageLimit",
                "recent_token_budget",
                "recentTokenBudget",
                "include_conversation_history",
                "includeConversationHistory",
                "include_shared_context",
                "includeSharedContext",
                "include_task_context",
                "includeTaskContext",
                "include_file_references",
                "includeFileReferences",
                "allowed_context_scopes",
                "allowedContextScopes",
                "window_selection_policy",
                "windowSelectionPolicy",
                "content_packet_delivery_mode",
                "contentPacketDeliveryMode",
                "agent_private_memory",
                "agentPrivateMemory",
                "provider_native",
                "providerNative",
                "external_context_engine",
                "externalContextEngine",
                "on_overflow",
                "onOverflow",
                "keep_source_refs",
                "keepSourceRefs",
                "metadata",
            },
            "contextManagement",
        )
        _reject_sensitive_config(source, "contextManagement")
        return cls(
            strategy=_context_strategy(
                _optional_text(source, "strategy")
                or ContextManagementStrategy.PASS_THROUGH.value
            ),
            max_input_tokens=_optional_int(
                source,
                "max_input_tokens",
                "maxInputTokens",
                default=8192,
            ),
            recent_message_limit=_optional_int(
                source,
                "recent_message_limit",
                "recentMessageLimit",
            ),
            recent_token_budget=_optional_int(
                source,
                "recent_token_budget",
                "recentTokenBudget",
            ),
            include_conversation_history=_optional_bool(
                source,
                "include_conversation_history",
                "includeConversationHistory",
                default=False,
            ),
            include_shared_context=_optional_bool(
                source,
                "include_shared_context",
                "includeSharedContext",
                default=False,
            ),
            include_task_context=_optional_bool(
                source,
                "include_task_context",
                "includeTaskContext",
                default=False,
            ),
            include_file_references=_optional_bool(
                source,
                "include_file_references",
                "includeFileReferences",
                default=False,
            ),
            allowed_context_scopes=_optional_string_tuple(
                source,
                "allowed_context_scopes",
                "allowedContextScopes",
                default=("current_user_instruction",),
            ),
            window_selection_policy=_window_selection_policy(
                _optional_text(source, "window_selection_policy", "windowSelectionPolicy")
                or ContextWindowSelectionPolicy.METADATA_ONLY_AUTHORIZED_REFS.value
            ),
            content_packet_delivery_mode=_content_packet_delivery_mode(
                _optional_text(
                    source,
                    "content_packet_delivery_mode",
                    "contentPacketDeliveryMode",
                )
                or ContextContentPacketDeliveryMode.AUDIT_ONLY.value
            ),
            agent_private_memory=AgentPrivateMemoryConfig.from_mapping(
                _optional_mapping(
                    source,
                    "agent_private_memory",
                    "agentPrivateMemory",
                )
            ),
            provider_native=ProviderNativeContextConfig.from_mapping(
                _optional_mapping(source, "provider_native", "providerNative")
            ),
            external_context_engine=ExternalContextEngineConfig.from_mapping(
                _optional_mapping(
                    source,
                    "external_context_engine",
                    "externalContextEngine",
                )
            ),
            on_overflow=_overflow_mode(
                _optional_text(source, "on_overflow", "onOverflow")
                or ContextOverflowMode.FAIL_WITH_EXPLANATION.value
            ),
            keep_source_refs=_optional_bool(
                source,
                "keep_source_refs",
                "keepSourceRefs",
                default=True,
            ),
            metadata=dict(_optional_mapping(source, "metadata") or {}),
        )

    def requested_scopes(self) -> tuple[str, ...]:
        scopes: list[str] = ["current_user_instruction"]
        for enabled, scope in (
            (self.include_conversation_history, "recent_messages"),
            (self.include_shared_context, "project_shared_context"),
            (self.include_task_context, "current_task"),
            (self.include_file_references, "referenced_files"),
            (self.agent_private_memory.enabled, "agent_private_memory"),
        ):
            if enabled and scope not in scopes:
                scopes.append(scope)
        return tuple(scopes)

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "strategy": self.strategy.value,
            "max_input_tokens": self.max_input_tokens,
            "allowed_context_scopes": list(self.allowed_context_scopes),
            "window_selection_policy": self.window_selection_policy.value,
            "content_packet_delivery_mode": self.content_packet_delivery_mode.value,
            "on_overflow": self.on_overflow.value,
            "keep_source_refs": self.keep_source_refs,
            "include_conversation_history": self.include_conversation_history,
            "include_shared_context": self.include_shared_context,
            "include_task_context": self.include_task_context,
            "include_file_references": self.include_file_references,
        }
        if self.recent_message_limit is not None:
            metadata["recent_message_limit"] = self.recent_message_limit
        if self.recent_token_budget is not None:
            metadata["recent_token_budget"] = self.recent_token_budget
        if self.agent_private_memory != AgentPrivateMemoryConfig():
            metadata["agent_private_memory"] = self.agent_private_memory.to_metadata()
        if self.provider_native != ProviderNativeContextConfig():
            metadata["provider_native"] = self.provider_native.to_metadata()
        if self.external_context_engine != ExternalContextEngineConfig():
            metadata["external_context_engine"] = (
                self.external_context_engine.to_metadata()
            )
        if self.metadata:
            metadata["metadata"] = dict(self.metadata)
        return metadata


@dataclass(frozen=True, slots=True)
class ContextProfileResolution:
    """Resolved profile plus the precedence path used to produce it."""

    profile: ContextManagementProfile
    precedence: tuple[str, ...]

    def to_metadata(self) -> Mapping[str, object]:
        return {
            "profile": self.profile.to_metadata(),
            "precedence": list(self.precedence),
        }


class ContextManagementProfileResolver:
    """Merge explicit context profile overrides in documented precedence order."""

    def resolve(
        self,
        *,
        workspace_default: Mapping[str, object] | None = None,
        provider_runtime_default: Mapping[str, object] | None = None,
        agent_profile: Mapping[str, object] | None = None,
        task_conversation_override: Mapping[str, object] | None = None,
        invocation_override: Mapping[str, object] | None = None,
    ) -> ContextProfileResolution:
        merged: dict[str, object] = {}
        precedence: list[str] = []
        for label, config in (
            ("workspace", workspace_default),
            ("provider-runtime", provider_runtime_default),
            ("agent", agent_profile),
            ("task-conversation", task_conversation_override),
            ("invocation", invocation_override),
        ):
            if config is None:
                continue
            merged = _merge_profile_config(merged, dict(config))
            precedence.append(label)
        return ContextProfileResolution(
            profile=ContextManagementProfile.from_mapping(merged or None),
            precedence=tuple(precedence or ("default",)),
        )


@dataclass(frozen=True, slots=True)
class ContextAssemblyRequest:
    """Input boundary for pre-invocation context assembly planning."""

    workspace_id: str
    agent_id: str
    invocation_id: str
    context_id: str
    user_instruction: str
    current_context_update_id: str
    task_id: str | None = None
    conversation_id: str | None = None
    file_references: tuple[str, ...] = ()
    requested_context_scopes: tuple[str, ...] = ()
    conversation_messages: tuple["ContextConversationMessageSnapshot", ...] = ()
    shared_context_updates: tuple["ContextSharedContextUpdateSnapshot", ...] = ()
    task_snapshot: "ContextTaskContextSnapshot | None" = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("workspace_id", self.workspace_id),
            ("agent_id", self.agent_id),
            ("invocation_id", self.invocation_id),
            ("context_id", self.context_id),
            ("user_instruction", self.user_instruction),
            ("current_context_update_id", self.current_context_update_id),
        ):
            _require_non_empty(value, field_name)
        if self.task_id is not None:
            _require_non_empty(self.task_id, "task_id")
        if self.conversation_id is not None:
            _require_non_empty(self.conversation_id, "conversation_id")
        for file_reference in self.file_references:
            _require_non_empty(file_reference, "file_reference")
        for scope in self.requested_context_scopes:
            _require_non_empty(scope, "requested_context_scope")


@dataclass(frozen=True, slots=True)
class ContextConversationMessageSnapshot:
    """Sanitized local conversation message input for bounded materialization."""

    message_id: str
    role: str
    content: str
    sequence: int | None = None
    created_at: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.message_id, "conversationMessage.messageId")
        _require_non_empty(self.role, "conversationMessage.role")
        _require_non_empty(self.content, "conversationMessage.content")
        if self.sequence is not None and self.sequence < 1:
            raise ValueError("conversationMessage.sequence must be positive.")
        if self.created_at is not None:
            _require_non_empty(self.created_at, "conversationMessage.createdAt")
        _reject_sensitive_config(self.metadata, "conversationMessage.metadata")
        _reject_sensitive_text(self.content, "conversationMessage.content")


@dataclass(frozen=True, slots=True)
class ContextSharedContextUpdateSnapshot:
    """Sanitized shared-context update input for bounded materialization."""

    update_id: str
    update_kind: str
    summary: str
    created_at: str | None = None
    source_agent_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.update_id, "sharedContextUpdate.updateId")
        _require_non_empty(self.update_kind, "sharedContextUpdate.updateKind")
        _require_non_empty(self.summary, "sharedContextUpdate.summary")
        if self.created_at is not None:
            _require_non_empty(self.created_at, "sharedContextUpdate.createdAt")
        if self.source_agent_id is not None:
            _require_non_empty(
                self.source_agent_id,
                "sharedContextUpdate.sourceAgentId",
            )
        _reject_sensitive_config(self.metadata, "sharedContextUpdate.metadata")
        _reject_sensitive_text(self.summary, "sharedContextUpdate.summary")


@dataclass(frozen=True, slots=True)
class ContextTaskContextSnapshot:
    """Sanitized task-context input for bounded materialization."""

    task_id: str
    title: str
    status: str
    description: str | None = None
    updated_at: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.task_id, "taskContext.taskId")
        _require_non_empty(self.title, "taskContext.title")
        _require_non_empty(self.status, "taskContext.status")
        if self.description is not None:
            _require_non_empty(self.description, "taskContext.description")
            _reject_sensitive_text(self.description, "taskContext.description")
        if self.updated_at is not None:
            _require_non_empty(self.updated_at, "taskContext.updatedAt")
        _reject_sensitive_config(self.metadata, "taskContext.metadata")
        _reject_sensitive_text(self.title, "taskContext.title")


@dataclass(frozen=True, slots=True)
class ContextSourceRef:
    """Audit reference to an authorized context source, without copying content."""

    scope: ContextAccessScope | str
    ref_type: str
    ref_id: str
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scope",
            _context_access_scope(self.scope, "sourceRef.scope"),
        )
        _require_non_empty(self.ref_type, "sourceRef.refType")
        _require_non_empty(self.ref_id, "sourceRef.refId")
        _reject_sensitive_config(self.metadata, "sourceRef.metadata")

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "scope": self.scope.value,
            "ref_type": self.ref_type,
            "ref_id": self.ref_id,
        }
        if self.metadata:
            metadata["metadata"] = dict(self.metadata)
        return metadata


@dataclass(frozen=True, slots=True)
class ContextDeniedScope:
    """Stable denial record for a requested context access scope."""

    scope: ContextAccessScope | str
    reason: str
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scope",
            _context_access_scope(self.scope, "deniedScope.scope"),
        )
        _require_non_empty(self.reason, "deniedScope.reason")
        _reject_sensitive_config(self.metadata, "deniedScope.metadata")

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "scope": self.scope.value,
            "reason": self.reason,
        }
        if self.metadata:
            metadata["metadata"] = dict(self.metadata)
        return metadata


@dataclass(frozen=True, slots=True)
class ContextAccessAuthorization:
    """Auditable authorization result for one context assembly request."""

    requested_scopes: tuple[str, ...]
    allowed_profile_scopes: tuple[str, ...]
    authorized_scopes: tuple[str, ...]
    denied_scopes: tuple[ContextDeniedScope, ...] = ()
    source_refs: tuple[ContextSourceRef, ...] = ()
    policy_mode: str = "local_profile_scope_boundary"
    authorization_metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "requested_scopes",
            _context_scope_tuple(self.requested_scopes, "requestedScopes"),
        )
        object.__setattr__(
            self,
            "allowed_profile_scopes",
            _context_scope_tuple(self.allowed_profile_scopes, "allowedProfileScopes"),
        )
        object.__setattr__(
            self,
            "authorized_scopes",
            _context_scope_tuple(
                self.authorized_scopes,
                "authorizedScopes",
                allow_empty=True,
            ),
        )
        _require_non_empty(self.policy_mode, "policyMode")
        _reject_sensitive_config(
            self.authorization_metadata,
            "authorizationMetadata",
        )

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "requested_context_scopes": list(self.requested_scopes),
            "allowed_profile_scopes": list(self.allowed_profile_scopes),
            "authorized_context_scopes": list(self.authorized_scopes),
            "denied_context_scopes": [
                denied.to_metadata() for denied in self.denied_scopes
            ],
            "source_refs": [source_ref.to_metadata() for source_ref in self.source_refs],
            "policy_mode": self.policy_mode,
        }
        if self.authorization_metadata:
            metadata["authorization_metadata"] = dict(self.authorization_metadata)
        return metadata


@dataclass(frozen=True, slots=True)
class ContextOmittedSourceRef:
    """Stable omission record for an authorized source ref outside the window."""

    source_ref: ContextSourceRef
    reason: str
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.reason, "omittedSourceRef.reason")
        _reject_sensitive_config(self.metadata, "omittedSourceRef.metadata")

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "source_ref": self.source_ref.to_metadata(),
            "reason": self.reason,
        }
        if self.metadata:
            metadata["metadata"] = dict(self.metadata)
        return metadata


@dataclass(frozen=True, slots=True)
class ContextWindowSelectionPlan:
    """Auditable source-ref selection plan without loading context bodies."""

    requested_source_refs: tuple[ContextSourceRef, ...]
    selected_source_refs: tuple[ContextSourceRef, ...]
    omitted_source_refs: tuple[ContextOmittedSourceRef, ...]
    denied_scopes_excluded: tuple[ContextDeniedScope, ...]
    selection_order: tuple[str, ...]
    window_budget: Mapping[str, object]
    policy_mode: str = "local_window_selection_metadata_only"
    content_loaded: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.policy_mode, "windowSelection.policyMode")
        _reject_sensitive_config(self.window_budget, "windowSelection.windowBudget")
        _reject_sensitive_config(self.metadata, "windowSelection.metadata")
        if self.content_loaded:
            raise ValueError("windowSelection.contentLoaded must be false.")

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "policy_mode": self.policy_mode,
            "requested_source_refs": [
                source_ref.to_metadata() for source_ref in self.requested_source_refs
            ],
            "selected_source_refs": [
                source_ref.to_metadata() for source_ref in self.selected_source_refs
            ],
            "omitted_source_refs": [
                omitted.to_metadata() for omitted in self.omitted_source_refs
            ],
            "denied_scopes_excluded": [
                denied.to_metadata() for denied in self.denied_scopes_excluded
            ],
            "selection_order": list(self.selection_order),
            "window_budget": dict(self.window_budget),
            "content_loaded": self.content_loaded,
        }
        if self.metadata:
            metadata["metadata"] = dict(self.metadata)
        return metadata


@dataclass(frozen=True, slots=True)
class ContextContentPacketItem:
    """Contract item for one selected source ref, without copied body content."""

    item_id: str
    source_ref: ContextSourceRef
    content_state: ContextContentState | str
    content_kind: ContextContentKind | str
    estimated_tokens: int = 0
    content_loaded: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.item_id, "contentPacketItem.itemId")
        object.__setattr__(
            self,
            "content_state",
            _content_state_value(self.content_state),
        )
        object.__setattr__(
            self,
            "content_kind",
            _content_kind_value(self.content_kind),
        )
        if self.estimated_tokens < 0:
            raise ValueError("contentPacketItem.estimatedTokens must be non-negative.")
        if self.content_loaded:
            raise ValueError("contentPacketItem.contentLoaded must be false.")
        _reject_sensitive_config(self.metadata, "contentPacketItem.metadata")

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "item_id": self.item_id,
            "source_ref": self.source_ref.to_metadata(),
            "content_state": self.content_state.value,
            "content_kind": self.content_kind.value,
            "estimated_tokens": self.estimated_tokens,
            "content_loaded": self.content_loaded,
        }
        if self.metadata:
            metadata["metadata"] = dict(self.metadata)
        return metadata


@dataclass(frozen=True, slots=True)
class ContextExcludedContentRef:
    """Denied or omitted source record excluded from packet items."""

    reason: str
    content_state: ContextContentState | str
    source_ref: ContextSourceRef | None = None
    scope: ContextAccessScope | str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.reason, "excludedContentRef.reason")
        object.__setattr__(
            self,
            "content_state",
            _content_state_value(self.content_state),
        )
        if self.scope is not None:
            object.__setattr__(
                self,
                "scope",
                _context_access_scope(self.scope, "excludedContentRef.scope"),
            )
        if self.source_ref is None and self.scope is None:
            raise ValueError("excludedContentRef requires a sourceRef or scope.")
        _reject_sensitive_config(self.metadata, "excludedContentRef.metadata")

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "reason": self.reason,
            "content_state": self.content_state.value,
        }
        if self.source_ref is not None:
            metadata["source_ref"] = self.source_ref.to_metadata()
        if self.scope is not None:
            metadata["scope"] = self.scope.value
        if self.metadata:
            metadata["metadata"] = dict(self.metadata)
        return metadata


@dataclass(frozen=True, slots=True)
class ContextContentPacketPlan:
    """Auditable contract for future content assembly over selected refs."""

    packet_id: str
    selected_source_refs: tuple[ContextSourceRef, ...]
    packet_items: tuple[ContextContentPacketItem, ...]
    excluded_refs: tuple[ContextExcludedContentRef, ...]
    budget_metadata: Mapping[str, object]
    redaction_metadata: Mapping[str, object]
    policy_mode: str = "metadata_only_content_packet_contract"
    delivery_mode: ContextContentPacketDeliveryMode | str = (
        ContextContentPacketDeliveryMode.AUDIT_ONLY
    )
    provider_payload_required: bool = False
    content_loaded: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.packet_id, "contentPacket.packetId")
        _require_non_empty(self.policy_mode, "contentPacket.policyMode")
        object.__setattr__(
            self,
            "delivery_mode",
            _content_packet_delivery_mode_value(self.delivery_mode),
        )
        if self.provider_payload_required:
            raise ValueError("contentPacket.providerPayloadRequired must be false.")
        if self.content_loaded:
            raise ValueError("contentPacket.contentLoaded must be false.")
        _reject_sensitive_config(self.budget_metadata, "contentPacket.budgetMetadata")
        _reject_sensitive_config(
            self.redaction_metadata,
            "contentPacket.redactionMetadata",
        )
        _reject_sensitive_config(self.metadata, "contentPacket.metadata")
        selected_keys = {_source_ref_key(source_ref) for source_ref in self.selected_source_refs}
        item_keys: set[tuple[str, str, str]] = set()
        for item in self.packet_items:
            item_key = _source_ref_key(item.source_ref)
            if item_key not in selected_keys:
                raise ValueError(
                    "contentPacket.packetItems must be derived from selected source refs."
                )
            if item_key in item_keys:
                raise ValueError("contentPacket.packetItems must not contain duplicates.")
            item_keys.add(item_key)

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "packet_id": self.packet_id,
            "policy_mode": self.policy_mode,
            "delivery_mode": self.delivery_mode.value,
            "provider_payload_required": self.provider_payload_required,
            "selected_source_refs": [
                source_ref.to_metadata() for source_ref in self.selected_source_refs
            ],
            "packet_items": [item.to_metadata() for item in self.packet_items],
            "excluded_refs": [
                excluded.to_metadata() for excluded in self.excluded_refs
            ],
            "estimated_tokens": sum(item.estimated_tokens for item in self.packet_items),
            "budget_metadata": dict(self.budget_metadata),
            "redaction_metadata": dict(self.redaction_metadata),
            "content_loaded": self.content_loaded,
        }
        if self.metadata:
            metadata["metadata"] = dict(self.metadata)
        return metadata


class ContextContentPacketBuilder:
    """Build contract-only content packets from selected source refs."""

    def build(
        self,
        *,
        profile: ContextManagementProfile,
        request: ContextAssemblyRequest,
        window_selection: ContextWindowSelectionPlan,
    ) -> ContextContentPacketPlan:
        items = tuple(
            ContextContentPacketItem(
                item_id=_content_packet_item_id(source_ref, index),
                source_ref=source_ref,
                content_state=_content_state_for_source_ref(source_ref),
                content_kind=_content_kind_for_source_ref(source_ref),
                estimated_tokens=0,
                metadata=_content_item_metadata(source_ref),
            )
            for index, source_ref in enumerate(window_selection.selected_source_refs)
        )
        excluded_refs: list[ContextExcludedContentRef] = []
        for omitted in window_selection.omitted_source_refs:
            excluded_refs.append(
                ContextExcludedContentRef(
                    reason=omitted.reason,
                    content_state=ContextContentState.OMITTED_BY_WINDOW_SELECTION,
                    source_ref=omitted.source_ref,
                    metadata={
                        "excluded_by": "window_selection",
                        "content_item_created": False,
                    },
                )
            )
        for denied in window_selection.denied_scopes_excluded:
            excluded_refs.append(
                ContextExcludedContentRef(
                    reason=denied.reason,
                    content_state=ContextContentState.DENIED_BY_AUTHORIZATION,
                    scope=denied.scope,
                    metadata={
                        "excluded_by": "authorization",
                        "content_item_created": False,
                    },
                )
            )
        delivery_mode = profile.content_packet_delivery_mode
        return ContextContentPacketPlan(
            packet_id=f"context-packet-{request.invocation_id}",
            selected_source_refs=window_selection.selected_source_refs,
            packet_items=items,
            excluded_refs=tuple(excluded_refs),
            budget_metadata=_content_packet_budget_metadata(
                profile=profile,
                window_selection=window_selection,
                item_count=len(items),
            ),
            redaction_metadata=_content_packet_redaction_metadata(delivery_mode),
            delivery_mode=delivery_mode,
            provider_payload_required=False,
            metadata={
                "source_policy": "selected_source_refs_only",
                "content_policy": "contract_only_no_body_load",
                "delivery_mode_reserved": (
                    delivery_mode is not ContextContentPacketDeliveryMode.AUDIT_ONLY
                ),
                "agent_native_context_delegated": (
                    delivery_mode
                    is ContextContentPacketDeliveryMode.AGENT_NATIVE_DELEGATED_CONTEXT
                ),
            },
        )


@dataclass(frozen=True, slots=True)
class ContextMaterializedSegment:
    """Bounded derived context segment produced from one selected packet item."""

    segment_id: str
    source_packet_item_id: str
    source_ref: ContextSourceRef
    segment_kind: ContextMaterializedSegmentKind | str
    load_state: ContextMaterializationLoadState | str
    estimated_tokens: int = 0
    text: str | None = None
    content_loaded: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.segment_id, "materializedSegment.segmentId")
        _require_non_empty(
            self.source_packet_item_id,
            "materializedSegment.sourcePacketItemId",
        )
        object.__setattr__(
            self,
            "segment_kind",
            _materialized_segment_kind_value(self.segment_kind),
        )
        object.__setattr__(
            self,
            "load_state",
            _materialization_load_state_value(self.load_state),
        )
        if self.estimated_tokens < 0:
            raise ValueError("materializedSegment.estimatedTokens must be non-negative.")
        if self.text is not None:
            _require_non_empty(self.text, "materializedSegment.text")
            _reject_sensitive_text(self.text, "materializedSegment.text")
        if self.content_loaded and self.text is None:
            raise ValueError("materializedSegment.contentLoaded requires text.")
        if not self.content_loaded and self.text is not None:
            raise ValueError("materializedSegment.text requires contentLoaded.")
        _reject_sensitive_config(self.metadata, "materializedSegment.metadata")

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "segment_id": self.segment_id,
            "source_packet_item_id": self.source_packet_item_id,
            "source_ref": self.source_ref.to_metadata(),
            "segment_kind": self.segment_kind.value,
            "load_state": self.load_state.value,
            "estimated_tokens": self.estimated_tokens,
            "content_loaded": self.content_loaded,
        }
        if self.text is not None:
            metadata["text"] = self.text
        if self.metadata:
            metadata["metadata"] = dict(self.metadata)
        return metadata


@dataclass(frozen=True, slots=True)
class ContextMaterializationPlan:
    """Auditable local materialization plan after content packet selection."""

    materialization_id: str
    source_packet_id: str
    source_packet_item_ids: tuple[str, ...]
    materialized_segments: tuple[ContextMaterializedSegment, ...]
    budget_metadata: Mapping[str, object]
    redaction_metadata: Mapping[str, object]
    delivery_metadata: Mapping[str, object]
    policy_mode: str = "bounded_local_context_materialization"
    content_loaded: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.materialization_id, "materialization.materializationId")
        _require_non_empty(self.source_packet_id, "materialization.sourcePacketId")
        _require_non_empty(self.policy_mode, "materialization.policyMode")
        source_ids = set(self.source_packet_item_ids)
        if len(source_ids) != len(self.source_packet_item_ids):
            raise ValueError("materialization.sourcePacketItemIds must be unique.")
        segment_ids: set[str] = set()
        segment_source_ids: set[str] = set()
        for segment in self.materialized_segments:
            if segment.source_packet_item_id not in source_ids:
                raise ValueError(
                    "materializedSegments must be derived from selected packet items."
                )
            if segment.segment_id in segment_ids:
                raise ValueError("materializedSegments must not contain duplicates.")
            segment_ids.add(segment.segment_id)
            if segment.source_packet_item_id in segment_source_ids:
                raise ValueError(
                    "materializedSegments must not duplicate packet item sources."
                )
            segment_source_ids.add(segment.source_packet_item_id)
        if self.content_loaded != any(
            segment.content_loaded for segment in self.materialized_segments
        ):
            raise ValueError(
                "materialization.contentLoaded must reflect loaded segments."
            )
        _reject_sensitive_config(self.budget_metadata, "materialization.budgetMetadata")
        _reject_sensitive_config(
            self.redaction_metadata,
            "materialization.redactionMetadata",
        )
        _reject_sensitive_config(
            self.delivery_metadata,
            "materialization.deliveryMetadata",
        )
        _reject_sensitive_config(self.metadata, "materialization.metadata")

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "materialization_id": self.materialization_id,
            "source_packet_id": self.source_packet_id,
            "source_packet_item_ids": list(self.source_packet_item_ids),
            "policy_mode": self.policy_mode,
            "materialized_segments": [
                segment.to_metadata() for segment in self.materialized_segments
            ],
            "estimated_tokens": sum(
                segment.estimated_tokens for segment in self.materialized_segments
            ),
            "budget_metadata": dict(self.budget_metadata),
            "redaction_metadata": dict(self.redaction_metadata),
            "delivery_metadata": dict(self.delivery_metadata),
            "content_loaded": self.content_loaded,
        }
        if self.metadata:
            metadata["metadata"] = dict(self.metadata)
        return metadata


class ContextLocalContentMaterializer:
    """Materialize bounded local segments from selected packet items only."""

    def build(
        self,
        *,
        profile: ContextManagementProfile,
        request: ContextAssemblyRequest,
        content_packet: ContextContentPacketPlan,
    ) -> ContextMaterializationPlan:
        budget = _materialization_budget(profile, request)
        remaining_budget = budget
        segments: list[ContextMaterializedSegment] = []

        for index, packet_item in enumerate(content_packet.packet_items):
            segment, remaining_budget = self._segment_for_packet_item(
                profile=profile,
                request=request,
                packet_item=packet_item,
                index=index,
                remaining_budget=remaining_budget,
            )
            segments.append(segment)

        loaded_tokens = sum(segment.estimated_tokens for segment in segments)
        return ContextMaterializationPlan(
            materialization_id=f"context-materialization-{request.invocation_id}",
            source_packet_id=content_packet.packet_id,
            source_packet_item_ids=tuple(
                item.item_id for item in content_packet.packet_items
            ),
            materialized_segments=tuple(segments),
            budget_metadata=_materialization_budget_metadata(
                profile=profile,
                request=request,
                initial_budget=budget,
                remaining_budget=remaining_budget,
                segment_count=len(segments),
                loaded_tokens=loaded_tokens,
            ),
            redaction_metadata=_materialization_redaction_metadata(segments),
            delivery_metadata=_materialization_delivery_metadata(),
            content_loaded=any(segment.content_loaded for segment in segments),
            metadata={
                "source_policy": "selected_packet_items_only",
                "context_policy": "derived_local_materialization",
                "compression_policy": "deterministic_selection_truncation_only",
            },
        )

    def _segment_for_packet_item(
        self,
        *,
        profile: ContextManagementProfile,
        request: ContextAssemblyRequest,
        packet_item: ContextContentPacketItem,
        index: int,
        remaining_budget: int,
    ) -> tuple[ContextMaterializedSegment, int]:
        source_ref = packet_item.source_ref
        segment_id = _materialization_segment_id(packet_item, index)
        if source_ref.scope is ContextAccessScope.CURRENT_USER_INSTRUCTION:
            return (
                ContextMaterializedSegment(
                    segment_id=segment_id,
                    source_packet_item_id=packet_item.item_id,
                    source_ref=source_ref,
                    segment_kind=(
                        ContextMaterializedSegmentKind.CURRENT_USER_MESSAGE_MARKER
                    ),
                    load_state=(
                        ContextMaterializationLoadState.ALREADY_IN_USER_MESSAGE
                    ),
                    metadata={
                        "provider_user_message_already_exists": True,
                        "current_user_instruction_copied": False,
                    },
                ),
                remaining_budget,
            )
        if source_ref.scope is ContextAccessScope.RECENT_MESSAGES:
            if not request.conversation_messages:
                return (
                    ContextMaterializedSegment(
                        segment_id=segment_id,
                        source_packet_item_id=packet_item.item_id,
                        source_ref=source_ref,
                        segment_kind=(
                            ContextMaterializedSegmentKind.CONVERSATION_MESSAGE_WINDOW
                        ),
                        load_state=(
                            ContextMaterializationLoadState.LOADER_NOT_CONNECTED
                        ),
                        metadata={
                            "conversation_reader_connected": False,
                            "conversation_messages_loaded": False,
                        },
                    ),
                    remaining_budget,
                )
            text = _conversation_window_text(profile, request.conversation_messages)
            return _loaded_segment(
                segment_id=segment_id,
                source_packet_item_id=packet_item.item_id,
                source_ref=source_ref,
                segment_kind=ContextMaterializedSegmentKind.CONVERSATION_MESSAGE_WINDOW,
                text=text,
                remaining_budget=remaining_budget,
                metadata={
                    "conversation_reader_connected": True,
                    "message_count": len(request.conversation_messages),
                    "recent_message_limit": profile.recent_message_limit,
                },
            )
        if source_ref.scope is ContextAccessScope.PROJECT_SHARED_CONTEXT:
            if not request.shared_context_updates:
                return (
                    ContextMaterializedSegment(
                        segment_id=segment_id,
                        source_packet_item_id=packet_item.item_id,
                        source_ref=source_ref,
                        segment_kind=(
                            ContextMaterializedSegmentKind.SHARED_CONTEXT_UPDATE_SUMMARY
                        ),
                        load_state=(
                            ContextMaterializationLoadState.LOADER_NOT_CONNECTED
                        ),
                        metadata={
                            "shared_context_reader_connected": False,
                            "shared_context_payload_loaded": False,
                            "materialized_state_loaded": False,
                        },
                    ),
                    remaining_budget,
                )
            text = _shared_context_update_text(request.shared_context_updates)
            return _loaded_segment(
                segment_id=segment_id,
                source_packet_item_id=packet_item.item_id,
                source_ref=source_ref,
                segment_kind=(
                    ContextMaterializedSegmentKind.SHARED_CONTEXT_UPDATE_SUMMARY
                ),
                text=text,
                remaining_budget=remaining_budget,
                metadata={
                    "shared_context_reader_connected": True,
                    "update_count": len(request.shared_context_updates),
                    "shared_context_payload_loaded": False,
                    "materialized_state_loaded": False,
                },
            )
        if source_ref.scope is ContextAccessScope.CURRENT_TASK:
            if request.task_snapshot is None:
                return (
                    ContextMaterializedSegment(
                        segment_id=segment_id,
                        source_packet_item_id=packet_item.item_id,
                        source_ref=source_ref,
                        segment_kind=ContextMaterializedSegmentKind.TASK_CONTEXT_SUMMARY,
                        load_state=(
                            ContextMaterializationLoadState.LOADER_NOT_CONNECTED
                        ),
                        metadata={"task_reader_connected": False},
                    ),
                    remaining_budget,
                )
            text = _task_context_text(request.task_snapshot)
            return _loaded_segment(
                segment_id=segment_id,
                source_packet_item_id=packet_item.item_id,
                source_ref=source_ref,
                segment_kind=ContextMaterializedSegmentKind.TASK_CONTEXT_SUMMARY,
                text=text,
                remaining_budget=remaining_budget,
                metadata={"task_reader_connected": True},
            )
        if source_ref.scope is ContextAccessScope.REFERENCED_FILES:
            return (
                ContextMaterializedSegment(
                    segment_id=segment_id,
                    source_packet_item_id=packet_item.item_id,
                    source_ref=source_ref,
                    segment_kind=ContextMaterializedSegmentKind.FILE_REF_MARKER,
                    load_state=ContextMaterializationLoadState.DEFERRED_FILE_BODY,
                    metadata={
                        "file_ref": source_ref.ref_id,
                        "file_body_loaded": False,
                    },
                ),
                remaining_budget,
            )
        return (
            ContextMaterializedSegment(
                segment_id=segment_id,
                source_packet_item_id=packet_item.item_id,
                source_ref=source_ref,
                segment_kind=ContextMaterializedSegmentKind.RESERVED_SCOPE_MARKER,
                load_state=(
                    ContextMaterializationLoadState.RESERVED_SCOPE_NOT_CONNECTED
                ),
                metadata={"reserved_scope_connected": False},
            ),
            remaining_budget,
        )


class ContextWindowSelector:
    """Select a metadata-only window from already authorized source refs."""

    def select(
        self,
        *,
        profile: ContextManagementProfile,
        authorization: ContextAccessAuthorization,
    ) -> ContextWindowSelectionPlan:
        if (
            profile.window_selection_policy
            is not ContextWindowSelectionPolicy.METADATA_ONLY_AUTHORIZED_REFS
        ):
            raise ContextAssemblyError(
                "windowSelectionPolicy is reserved for this baseline."
            )

        selected: list[ContextSourceRef] = []
        omitted: list[ContextOmittedSourceRef] = []
        seen: set[tuple[str, str, str]] = set()

        for source_ref in authorization.source_refs:
            key = _source_ref_key(source_ref)
            if key in seen:
                omitted.append(
                    ContextOmittedSourceRef(
                        source_ref=source_ref,
                        reason="duplicate_source_ref",
                    )
                )
                continue
            seen.add(key)

            if (
                profile.strategy is ContextManagementStrategy.PASS_THROUGH
                and source_ref.scope is not ContextAccessScope.CURRENT_USER_INSTRUCTION
            ):
                omitted.append(
                    ContextOmittedSourceRef(
                        source_ref=source_ref,
                        reason="not_selected_by_policy",
                    )
                )
                continue

            selected.append(source_ref)

        return ContextWindowSelectionPlan(
            requested_source_refs=authorization.source_refs,
            selected_source_refs=tuple(selected),
            omitted_source_refs=tuple(omitted),
            denied_scopes_excluded=authorization.denied_scopes,
            selection_order=tuple(_selection_order_label(ref) for ref in selected),
            window_budget=_window_budget_metadata(profile),
            metadata={
                "selection_policy": profile.window_selection_policy.value,
                "source_policy": "authorized_refs_only",
                "content_policy": "source_refs_only",
            },
        )


class ContextAccessAuthorizer:
    """Authorize context access scopes without reading or assembling content bodies."""

    def authorize(
        self,
        *,
        profile: ContextManagementProfile,
        request: ContextAssemblyRequest,
        requested_scopes: Sequence[str],
    ) -> ContextAccessAuthorization:
        requested = _context_scope_tuple(
            _with_current_user_instruction(requested_scopes),
            "requested_context_scopes",
        )
        allowed_profile_scopes = _context_scope_tuple(
            profile.allowed_context_scopes,
            "allowedContextScopes",
        )
        allowed = set(allowed_profile_scopes)
        authorized: list[str] = []
        denied: list[ContextDeniedScope] = []
        source_refs: list[ContextSourceRef] = []

        for scope_label in requested:
            scope = ContextAccessScope(scope_label)
            if scope_label not in allowed:
                denied.append(
                    ContextDeniedScope(
                        scope=scope,
                        reason="not_allowed_by_profile",
                    )
                )
                continue

            refs, denial_reason = self._authorize_source_boundary(
                scope=scope,
                request=request,
            )
            if denial_reason is not None:
                denied.append(ContextDeniedScope(scope=scope, reason=denial_reason))
                continue

            authorized.append(scope.value)
            source_refs.extend(refs)

        return ContextAccessAuthorization(
            requested_scopes=requested,
            allowed_profile_scopes=allowed_profile_scopes,
            authorized_scopes=tuple(authorized),
            denied_scopes=tuple(denied),
            source_refs=tuple(source_refs),
            authorization_metadata={
                "content_policy": "source_refs_only",
                "content_loaded": False,
            },
        )

    def _authorize_source_boundary(
        self,
        *,
        scope: ContextAccessScope,
        request: ContextAssemblyRequest,
    ) -> tuple[tuple[ContextSourceRef, ...], str | None]:
        if scope is ContextAccessScope.CURRENT_USER_INSTRUCTION:
            return (
                (
                    ContextSourceRef(
                        scope=scope,
                        ref_type="context_update",
                        ref_id=request.current_context_update_id,
                    ),
                ),
                None,
            )
        if scope is ContextAccessScope.RECENT_MESSAGES:
            if request.conversation_id is None:
                return (), "conversation_id_required"
            return (
                (
                    ContextSourceRef(
                        scope=scope,
                        ref_type="conversation",
                        ref_id=request.conversation_id,
                        metadata={"content_loaded": False},
                    ),
                ),
                None,
            )
        if scope is ContextAccessScope.PROJECT_SHARED_CONTEXT:
            return (
                (
                    ContextSourceRef(
                        scope=scope,
                        ref_type="project_shared_context",
                        ref_id=request.context_id,
                    ),
                ),
                None,
            )
        if scope is ContextAccessScope.CURRENT_TASK:
            if request.task_id is None:
                return (), "task_id_required"
            return (
                (
                    ContextSourceRef(
                        scope=scope,
                        ref_type="task",
                        ref_id=request.task_id,
                    ),
                ),
                None,
            )
        if scope is ContextAccessScope.REFERENCED_FILES:
            if not request.file_references:
                return (), "file_reference_required"
            return (
                tuple(
                    ContextSourceRef(
                        scope=scope,
                        ref_type="file_reference",
                        ref_id=file_reference,
                        metadata={"content_loaded": False},
                    )
                    for file_reference in request.file_references
                ),
                None,
            )
        if scope in {
            ContextAccessScope.AGENT_PRIVATE_MEMORY,
            ContextAccessScope.PROVIDER_NATIVE_SESSION_REF,
            ContextAccessScope.EXTERNAL_CONTEXT_ENGINE,
        }:
            return (), "reserved_scope_not_connected"
        raise AssertionError(f"Unhandled context access scope: {scope.value}")


@dataclass(frozen=True, slots=True)
class ContextAssemblyPlan:
    """Auditable no-op context packet plan for the current baseline."""

    profile: ContextManagementProfile
    exposed_context_scopes: tuple[str, ...]
    authorization: ContextAccessAuthorization
    window_selection: ContextWindowSelectionPlan
    content_packet: ContextContentPacketPlan
    materialization: ContextMaterializationPlan
    estimated_input_tokens: int
    within_budget: bool
    requires_compaction: bool = False
    pass_through: bool = True
    overflow_action: ContextOverflowMode = ContextOverflowMode.FAIL_WITH_EXPLANATION

    def to_metadata(self) -> Mapping[str, object]:
        authorization = self.authorization.to_metadata()
        window_selection = self.window_selection.to_metadata()
        content_packet = self.content_packet.to_metadata()
        materialization = self.materialization.to_metadata()
        return {
            "strategy": self.profile.strategy.value,
            "pass_through": self.pass_through,
            "max_input_tokens": self.profile.max_input_tokens,
            "estimated_input_tokens": self.estimated_input_tokens,
            "within_budget": self.within_budget,
            "requires_compaction": self.requires_compaction,
            "overflow_action": self.overflow_action.value,
            "exposed_context_scopes": list(self.exposed_context_scopes),
            "requested_context_scopes": authorization["requested_context_scopes"],
            "allowed_profile_scopes": authorization["allowed_profile_scopes"],
            "authorized_context_scopes": authorization["authorized_context_scopes"],
            "denied_context_scopes": authorization["denied_context_scopes"],
            "source_refs": authorization["source_refs"],
            "policy_mode": authorization["policy_mode"],
            "authorization": authorization,
            "window_selection": window_selection,
            "selected_source_refs": window_selection["selected_source_refs"],
            "omitted_source_refs": window_selection["omitted_source_refs"],
            "window_policy_mode": window_selection["policy_mode"],
            "window_budget": window_selection["window_budget"],
            "content_packet": content_packet,
            "content_packet_items": content_packet["packet_items"],
            "excluded_content_refs": content_packet["excluded_refs"],
            "content_packet_policy_mode": content_packet["policy_mode"],
            "content_packet_delivery_mode": content_packet["delivery_mode"],
            "materialization": materialization,
            "materialized_segments": materialization["materialized_segments"],
            "materialization_policy_mode": materialization["policy_mode"],
            "materialization_content_loaded": materialization["content_loaded"],
            "provider_prompt_injected": materialization["delivery_metadata"][
                "provider_prompt_injected"
            ],
            "agent_native_runtime_connected": materialization["delivery_metadata"][
                "agent_native_runtime_connected"
            ],
            "provider_payload_required": content_packet["provider_payload_required"],
            "content_loaded": content_packet["content_loaded"],
            "keep_source_refs": self.profile.keep_source_refs,
        }


class ContextAssemblyPlanner:
    """Build a replaceable context assembly plan without changing prompts."""

    def plan(
        self,
        *,
        profile: ContextManagementProfile,
        request: ContextAssemblyRequest,
    ) -> ContextAssemblyPlan:
        requested_scopes = (
            request.requested_context_scopes
            if request.requested_context_scopes
            else profile.requested_scopes()
        )
        try:
            authorization = ContextAccessAuthorizer().authorize(
                profile=profile,
                request=request,
                requested_scopes=requested_scopes,
            )
        except ValueError as exc:
            raise ContextAssemblyError(str(exc)) from exc
        window_selection = ContextWindowSelector().select(
            profile=profile,
            authorization=authorization,
        )
        content_packet = ContextContentPacketBuilder().build(
            profile=profile,
            request=request,
            window_selection=window_selection,
        )
        materialization = ContextLocalContentMaterializer().build(
            profile=profile,
            request=request,
            content_packet=content_packet,
        )
        estimated_tokens = _estimate_tokens(request.user_instruction)
        if estimated_tokens > profile.max_input_tokens:
            if profile.on_overflow is ContextOverflowMode.FAIL_WITH_EXPLANATION:
                raise ContextAssemblyError("context assembly exceeds maxInputTokens.")
            if profile.on_overflow is ContextOverflowMode.COMPACT_THEN_RETRY:
                raise ContextAssemblyError(
                    "compact_then_retry overflow mode is reserved in this baseline."
                )
            return ContextAssemblyPlan(
                profile=profile,
                exposed_context_scopes=authorization.authorized_scopes,
                authorization=authorization,
                window_selection=window_selection,
                content_packet=content_packet,
                materialization=materialization,
                estimated_input_tokens=estimated_tokens,
                within_budget=False,
                overflow_action=profile.on_overflow,
                requires_compaction=False,
                pass_through=_is_pass_through(profile),
            )
        return ContextAssemblyPlan(
            profile=profile,
            exposed_context_scopes=authorization.authorized_scopes,
            authorization=authorization,
            window_selection=window_selection,
            content_packet=content_packet,
            materialization=materialization,
            estimated_input_tokens=estimated_tokens,
            within_budget=True,
            requires_compaction=_requires_compaction(profile),
            overflow_action=profile.on_overflow,
            pass_through=_is_pass_through(profile),
        )


def context_management_config_from_runtime_config(
    runtime_config: Mapping[str, object],
) -> Mapping[str, object] | None:
    profile_config = _optional_mapping(runtime_config, "profile")
    if profile_config is not None:
        value = _optional_mapping(
            profile_config,
            "context_management",
            "contextManagement",
        )
        if value is not None:
            return value
    return _optional_mapping(
        runtime_config,
        "context_management",
        "contextManagement",
    )


def _merge_profile_config(
    base: Mapping[str, object],
    override: Mapping[str, object],
) -> dict[str, object]:
    merged = dict(base)
    for key, value in override.items():
        if (
            isinstance(value, Mapping)
            and isinstance(merged.get(key), Mapping)
            and key
            in {
                "agent_private_memory",
                "agentPrivateMemory",
                "provider_native",
                "providerNative",
                "external_context_engine",
                "externalContextEngine",
                "metadata",
            }
        ):
            merged[key] = _merge_profile_config(
                merged[key],  # type: ignore[arg-type]
                value,
            )
        else:
            merged[key] = value
    return merged


def _context_access_scope(
    value: ContextAccessScope | str,
    field_name: str,
) -> ContextAccessScope:
    if isinstance(value, ContextAccessScope):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    _require_non_empty(value, field_name)
    normalized = _normalized_label(value)
    aliases = {
        "current-user-instruction": ContextAccessScope.CURRENT_USER_INSTRUCTION,
        "user-instruction": ContextAccessScope.CURRENT_USER_INSTRUCTION,
        "recent-messages": ContextAccessScope.RECENT_MESSAGES,
        "conversation-history": ContextAccessScope.RECENT_MESSAGES,
        "project-shared-context": ContextAccessScope.PROJECT_SHARED_CONTEXT,
        "project-summary": ContextAccessScope.PROJECT_SHARED_CONTEXT,
        "shared-context": ContextAccessScope.PROJECT_SHARED_CONTEXT,
        "current-task": ContextAccessScope.CURRENT_TASK,
        "task-context": ContextAccessScope.CURRENT_TASK,
        "referenced-files": ContextAccessScope.REFERENCED_FILES,
        "file-references": ContextAccessScope.REFERENCED_FILES,
        "agent-private-memory": ContextAccessScope.AGENT_PRIVATE_MEMORY,
        "provider-native-session-ref": ContextAccessScope.PROVIDER_NATIVE_SESSION_REF,
        "provider-native": ContextAccessScope.PROVIDER_NATIVE_SESSION_REF,
        "external-context-engine": ContextAccessScope.EXTERNAL_CONTEXT_ENGINE,
        "external-engine": ContextAccessScope.EXTERNAL_CONTEXT_ENGINE,
    }
    if normalized in aliases:
        return aliases[normalized]
    valid = ", ".join(scope.value for scope in ContextAccessScope)
    raise ValueError(f"{field_name} must be one of: {valid}.")


def _context_scope_tuple(
    values: Sequence[str],
    field_name: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not values:
        if allow_empty:
            return ()
        raise ValueError(f"{field_name} must include at least one value.")
    scopes: list[str] = []
    seen: set[str] = set()
    for value in values:
        scope = _context_access_scope(value, field_name)
        if scope.value in seen:
            raise ValueError(f"{field_name} must not contain duplicate values.")
        scopes.append(scope.value)
        seen.add(scope.value)
    return tuple(scopes)


def _with_current_user_instruction(scopes: Sequence[str]) -> tuple[str, ...]:
    labels = list(scopes)
    current_scope = ContextAccessScope.CURRENT_USER_INSTRUCTION.value
    if current_scope not in (
        _context_access_scope(scope, "requested_context_scopes").value
        for scope in labels
    ):
        labels.insert(0, current_scope)
    return tuple(labels)


def _context_strategy(value: str) -> ContextManagementStrategy:
    normalized = _normalized_label(value)
    aliases = {
        "none": ContextManagementStrategy.PASS_THROUGH,
        "pass-through": ContextManagementStrategy.PASS_THROUGH,
        "passthrough": ContextManagementStrategy.PASS_THROUGH,
        "recent-window": ContextManagementStrategy.RECENT_WINDOW,
        "platform-summary": ContextManagementStrategy.PLATFORM_SUMMARY,
        "provider-native": ContextManagementStrategy.PROVIDER_NATIVE,
        "external-context-engine": ContextManagementStrategy.EXTERNAL_CONTEXT_ENGINE,
        "hybrid": ContextManagementStrategy.HYBRID,
    }
    if normalized in aliases:
        return aliases[normalized]
    valid = ", ".join(strategy.value for strategy in ContextManagementStrategy)
    raise ValueError(f"contextManagement.strategy must be one of: {valid}.")


def _overflow_mode(value: str) -> ContextOverflowMode:
    normalized = _normalized_label(value).replace("-", "_")
    aliases = {
        "fail_with_explanation": ContextOverflowMode.FAIL_WITH_EXPLANATION,
        "trim_to_budget": ContextOverflowMode.TRIM_TO_BUDGET,
        "compact_then_retry": ContextOverflowMode.COMPACT_THEN_RETRY,
    }
    if normalized in aliases:
        return aliases[normalized]
    valid = ", ".join(mode.value for mode in ContextOverflowMode)
    raise ValueError(f"contextManagement.onOverflow must be one of: {valid}.")


def _window_selection_policy_value(
    value: ContextWindowSelectionPolicy | str,
) -> ContextWindowSelectionPolicy:
    if isinstance(value, ContextWindowSelectionPolicy):
        return value
    if not isinstance(value, str):
        raise ValueError("contextManagement.windowSelectionPolicy must be a string.")
    return _window_selection_policy(value)


def _window_selection_policy(value: str) -> ContextWindowSelectionPolicy:
    normalized = _normalized_label(value).replace("-", "_")
    aliases = {
        "metadata_only_authorized_refs": (
            ContextWindowSelectionPolicy.METADATA_ONLY_AUTHORIZED_REFS
        ),
        "authorized_refs_metadata_only": (
            ContextWindowSelectionPolicy.METADATA_ONLY_AUTHORIZED_REFS
        ),
        "local_window_selection_metadata_only": (
            ContextWindowSelectionPolicy.METADATA_ONLY_AUTHORIZED_REFS
        ),
    }
    if normalized in aliases:
        return aliases[normalized]
    valid = ", ".join(policy.value for policy in ContextWindowSelectionPolicy)
    raise ValueError(f"contextManagement.windowSelectionPolicy must be one of: {valid}.")


def _content_packet_delivery_mode_value(
    value: ContextContentPacketDeliveryMode | str,
) -> ContextContentPacketDeliveryMode:
    if isinstance(value, ContextContentPacketDeliveryMode):
        return value
    if not isinstance(value, str):
        raise ValueError("contextManagement.contentPacketDeliveryMode must be a string.")
    return _content_packet_delivery_mode(value)


def _content_packet_delivery_mode(value: str) -> ContextContentPacketDeliveryMode:
    normalized = _normalized_label(value).replace("-", "_")
    aliases = {
        "audit_only": ContextContentPacketDeliveryMode.AUDIT_ONLY,
        "metadata_only": ContextContentPacketDeliveryMode.AUDIT_ONLY,
        "provider_prompt_packet": (
            ContextContentPacketDeliveryMode.PROVIDER_PROMPT_PACKET
        ),
        "prompt_packet": ContextContentPacketDeliveryMode.PROVIDER_PROMPT_PACKET,
        "agent_native_delegated_context": (
            ContextContentPacketDeliveryMode.AGENT_NATIVE_DELEGATED_CONTEXT
        ),
        "agent_native_context_delegated": (
            ContextContentPacketDeliveryMode.AGENT_NATIVE_DELEGATED_CONTEXT
        ),
        "delegated_context_management": (
            ContextContentPacketDeliveryMode.AGENT_NATIVE_DELEGATED_CONTEXT
        ),
    }
    if normalized in aliases:
        return aliases[normalized]
    valid = ", ".join(mode.value for mode in ContextContentPacketDeliveryMode)
    raise ValueError(
        f"contextManagement.contentPacketDeliveryMode must be one of: {valid}."
    )


def _content_state_value(value: ContextContentState | str) -> ContextContentState:
    if isinstance(value, ContextContentState):
        return value
    if not isinstance(value, str):
        raise ValueError("contentState must be a string.")
    normalized = _normalized_label(value).replace("-", "_")
    aliases = {
        "ref_only": ContextContentState.REF_ONLY,
        "not_loaded": ContextContentState.NOT_LOADED,
        "already_in_user_message": ContextContentState.ALREADY_IN_USER_MESSAGE,
        "loader_not_connected": ContextContentState.LOADER_NOT_CONNECTED,
        "reserved_scope_not_connected": (
            ContextContentState.RESERVED_SCOPE_NOT_CONNECTED
        ),
        "reserved_not_connected": ContextContentState.RESERVED_SCOPE_NOT_CONNECTED,
        "omitted_by_window_selection": (
            ContextContentState.OMITTED_BY_WINDOW_SELECTION
        ),
        "denied_by_authorization": ContextContentState.DENIED_BY_AUTHORIZATION,
        "redacted": ContextContentState.REDACTED,
        "error": ContextContentState.ERROR,
    }
    if normalized in aliases:
        return aliases[normalized]
    valid = ", ".join(state.value for state in ContextContentState)
    raise ValueError(f"contentState must be one of: {valid}.")


def _content_kind_value(value: ContextContentKind | str) -> ContextContentKind:
    if isinstance(value, ContextContentKind):
        return value
    if not isinstance(value, str):
        raise ValueError("contentKind must be a string.")
    normalized = _normalized_label(value).replace("-", "_")
    aliases = {
        "current_user_instruction": ContextContentKind.CURRENT_USER_INSTRUCTION,
        "conversation_ref": ContextContentKind.CONVERSATION_REF,
        "recent_messages": ContextContentKind.CONVERSATION_REF,
        "shared_context_ref": ContextContentKind.SHARED_CONTEXT_REF,
        "project_shared_context": ContextContentKind.SHARED_CONTEXT_REF,
        "task_ref": ContextContentKind.TASK_REF,
        "current_task": ContextContentKind.TASK_REF,
        "file_ref": ContextContentKind.FILE_REF,
        "referenced_files": ContextContentKind.FILE_REF,
        "agent_private_memory_ref": ContextContentKind.AGENT_PRIVATE_MEMORY_REF,
        "provider_native_session_ref": (
            ContextContentKind.PROVIDER_NATIVE_SESSION_REF
        ),
        "external_context_engine_ref": (
            ContextContentKind.EXTERNAL_CONTEXT_ENGINE_REF
        ),
    }
    if normalized in aliases:
        return aliases[normalized]
    valid = ", ".join(kind.value for kind in ContextContentKind)
    raise ValueError(f"contentKind must be one of: {valid}.")


def _materialization_load_state_value(
    value: ContextMaterializationLoadState | str,
) -> ContextMaterializationLoadState:
    if isinstance(value, ContextMaterializationLoadState):
        return value
    if not isinstance(value, str):
        raise ValueError("materialization loadState must be a string.")
    normalized = _normalized_label(value).replace("-", "_")
    aliases = {
        "already_in_user_message": (
            ContextMaterializationLoadState.ALREADY_IN_USER_MESSAGE
        ),
        "loaded": ContextMaterializationLoadState.LOADED,
        "truncated_to_budget": ContextMaterializationLoadState.TRUNCATED_TO_BUDGET,
        "loader_not_connected": ContextMaterializationLoadState.LOADER_NOT_CONNECTED,
        "deferred_file_body": ContextMaterializationLoadState.DEFERRED_FILE_BODY,
        "reserved_scope_not_connected": (
            ContextMaterializationLoadState.RESERVED_SCOPE_NOT_CONNECTED
        ),
        "redacted": ContextMaterializationLoadState.REDACTED,
        "error": ContextMaterializationLoadState.ERROR,
    }
    if normalized in aliases:
        return aliases[normalized]
    valid = ", ".join(state.value for state in ContextMaterializationLoadState)
    raise ValueError(f"materialization loadState must be one of: {valid}.")


def _materialized_segment_kind_value(
    value: ContextMaterializedSegmentKind | str,
) -> ContextMaterializedSegmentKind:
    if isinstance(value, ContextMaterializedSegmentKind):
        return value
    if not isinstance(value, str):
        raise ValueError("materializedSegment.segmentKind must be a string.")
    normalized = _normalized_label(value).replace("-", "_")
    aliases = {
        "current_user_message_marker": (
            ContextMaterializedSegmentKind.CURRENT_USER_MESSAGE_MARKER
        ),
        "conversation_message_window": (
            ContextMaterializedSegmentKind.CONVERSATION_MESSAGE_WINDOW
        ),
        "shared_context_update_summary": (
            ContextMaterializedSegmentKind.SHARED_CONTEXT_UPDATE_SUMMARY
        ),
        "task_context_summary": ContextMaterializedSegmentKind.TASK_CONTEXT_SUMMARY,
        "file_ref_marker": ContextMaterializedSegmentKind.FILE_REF_MARKER,
        "reserved_scope_marker": ContextMaterializedSegmentKind.RESERVED_SCOPE_MARKER,
    }
    if normalized in aliases:
        return aliases[normalized]
    valid = ", ".join(kind.value for kind in ContextMaterializedSegmentKind)
    raise ValueError(f"materializedSegment.segmentKind must be one of: {valid}.")


def _source_ref_key(source_ref: ContextSourceRef) -> tuple[str, str, str]:
    return (source_ref.scope.value, source_ref.ref_type, source_ref.ref_id)


def _selection_order_label(source_ref: ContextSourceRef) -> str:
    scope, ref_type, ref_id = _source_ref_key(source_ref)
    return f"{scope}:{ref_type}:{ref_id}"


def _window_budget_metadata(profile: ContextManagementProfile) -> Mapping[str, object]:
    metadata: dict[str, object] = {
        "max_input_tokens": profile.max_input_tokens,
        "strategy": profile.strategy.value,
        "selection_policy": profile.window_selection_policy.value,
        "content_token_budget_reserved": True,
    }
    if profile.recent_message_limit is not None:
        metadata["recent_message_limit"] = profile.recent_message_limit
    if profile.recent_token_budget is not None:
        metadata["recent_token_budget"] = profile.recent_token_budget
    return metadata


def _content_packet_item_id(source_ref: ContextSourceRef, index: int) -> str:
    scope, ref_type, ref_id = _source_ref_key(source_ref)
    return (
        f"item-{index + 1}-"
        f"{_safe_packet_label(scope)}-"
        f"{_safe_packet_label(ref_type)}-"
        f"{_safe_packet_label(ref_id)}"
    )


def _content_kind_for_source_ref(source_ref: ContextSourceRef) -> ContextContentKind:
    if source_ref.scope is ContextAccessScope.CURRENT_USER_INSTRUCTION:
        return ContextContentKind.CURRENT_USER_INSTRUCTION
    if source_ref.scope is ContextAccessScope.RECENT_MESSAGES:
        return ContextContentKind.CONVERSATION_REF
    if source_ref.scope is ContextAccessScope.PROJECT_SHARED_CONTEXT:
        return ContextContentKind.SHARED_CONTEXT_REF
    if source_ref.scope is ContextAccessScope.CURRENT_TASK:
        return ContextContentKind.TASK_REF
    if source_ref.scope is ContextAccessScope.REFERENCED_FILES:
        return ContextContentKind.FILE_REF
    if source_ref.scope is ContextAccessScope.AGENT_PRIVATE_MEMORY:
        return ContextContentKind.AGENT_PRIVATE_MEMORY_REF
    if source_ref.scope is ContextAccessScope.PROVIDER_NATIVE_SESSION_REF:
        return ContextContentKind.PROVIDER_NATIVE_SESSION_REF
    if source_ref.scope is ContextAccessScope.EXTERNAL_CONTEXT_ENGINE:
        return ContextContentKind.EXTERNAL_CONTEXT_ENGINE_REF
    raise AssertionError(f"Unhandled content source scope: {source_ref.scope.value}")


def _content_state_for_source_ref(source_ref: ContextSourceRef) -> ContextContentState:
    if source_ref.scope is ContextAccessScope.CURRENT_USER_INSTRUCTION:
        return ContextContentState.ALREADY_IN_USER_MESSAGE
    if source_ref.scope in {
        ContextAccessScope.AGENT_PRIVATE_MEMORY,
        ContextAccessScope.PROVIDER_NATIVE_SESSION_REF,
        ContextAccessScope.EXTERNAL_CONTEXT_ENGINE,
    }:
        return ContextContentState.RESERVED_SCOPE_NOT_CONNECTED
    return ContextContentState.NOT_LOADED


def _content_item_metadata(source_ref: ContextSourceRef) -> Mapping[str, object]:
    metadata: dict[str, object] = {
        "source_ref_only": True,
        "content_text_included": False,
        "content_loaded": False,
    }
    if source_ref.scope is ContextAccessScope.CURRENT_USER_INSTRUCTION:
        metadata["already_in_user_message"] = True
        return metadata
    metadata["loader_connected"] = False
    if source_ref.scope is ContextAccessScope.RECENT_MESSAGES:
        metadata["conversation_messages_loaded"] = False
    elif source_ref.scope is ContextAccessScope.PROJECT_SHARED_CONTEXT:
        metadata["shared_context_loaded"] = False
    elif source_ref.scope is ContextAccessScope.CURRENT_TASK:
        metadata["task_body_loaded"] = False
    elif source_ref.scope is ContextAccessScope.REFERENCED_FILES:
        metadata["file_body_loaded"] = False
    else:
        metadata["reserved_scope_connected"] = False
    return metadata


def _content_packet_budget_metadata(
    *,
    profile: ContextManagementProfile,
    window_selection: ContextWindowSelectionPlan,
    item_count: int,
) -> Mapping[str, object]:
    metadata = dict(window_selection.window_budget)
    metadata.update(
        {
            "content_packet_item_count": item_count,
            "content_packet_estimated_tokens": 0,
            "provider_payload_required": False,
            "delivery_mode": profile.content_packet_delivery_mode.value,
        }
    )
    return metadata


def _content_packet_redaction_metadata(
    delivery_mode: ContextContentPacketDeliveryMode,
) -> Mapping[str, object]:
    return {
        "content_loaded": False,
        "current_user_instruction_copied": False,
        "conversation_messages_loaded": False,
        "shared_context_loaded": False,
        "task_body_loaded": False,
        "file_bodies_loaded": False,
        "agent_private_memory_loaded": False,
        "provider_native_session_loaded": False,
        "external_context_engine_loaded": False,
        "agent_native_runtime_connected": False,
        "provider_prompt_modified": False,
        "provider_payload_required": False,
        "delivery_mode": delivery_mode.value,
    }


def _materialization_segment_id(
    packet_item: ContextContentPacketItem,
    index: int,
) -> str:
    return f"segment-{index + 1}-{_safe_packet_label(packet_item.item_id)}"


def _materialization_budget(
    profile: ContextManagementProfile,
    request: ContextAssemblyRequest,
) -> int:
    if profile.recent_token_budget is not None:
        return profile.recent_token_budget
    return max(0, profile.max_input_tokens - _estimate_tokens(request.user_instruction))


def _conversation_window_text(
    profile: ContextManagementProfile,
    messages: tuple[ContextConversationMessageSnapshot, ...],
) -> str:
    limit = profile.recent_message_limit
    selected = messages if limit is None else messages[-limit:] if limit > 0 else ()
    if not selected:
        return "No recent conversation messages selected by the current budget."
    return "\n".join(
        f"{message.role}: {message.content}" for message in selected
    )


def _shared_context_update_text(
    updates: tuple[ContextSharedContextUpdateSnapshot, ...],
) -> str:
    return "\n".join(
        f"{update.update_kind} {update.update_id}: {update.summary}"
        for update in updates
    )


def _task_context_text(task: ContextTaskContextSnapshot) -> str:
    parts = [
        f"Task {task.task_id}: {task.title}",
        f"Status: {task.status}",
    ]
    if task.description is not None:
        parts.append(f"Description: {task.description}")
    return "\n".join(parts)


def _loaded_segment(
    *,
    segment_id: str,
    source_packet_item_id: str,
    source_ref: ContextSourceRef,
    segment_kind: ContextMaterializedSegmentKind,
    text: str,
    remaining_budget: int,
    metadata: Mapping[str, object],
) -> tuple[ContextMaterializedSegment, int]:
    if remaining_budget <= 0:
        return (
            ContextMaterializedSegment(
                segment_id=segment_id,
                source_packet_item_id=source_packet_item_id,
                source_ref=source_ref,
                segment_kind=segment_kind,
                load_state=ContextMaterializationLoadState.TRUNCATED_TO_BUDGET,
                metadata={
                    **dict(metadata),
                    "budget_exhausted": True,
                    "text_omitted_by_budget": True,
                },
            ),
            0,
        )
    bounded_text, estimated_tokens, truncated = _bounded_text(
        text,
        remaining_budget,
    )
    state = (
        ContextMaterializationLoadState.TRUNCATED_TO_BUDGET
        if truncated
        else ContextMaterializationLoadState.LOADED
    )
    return (
        ContextMaterializedSegment(
            segment_id=segment_id,
            source_packet_item_id=source_packet_item_id,
            source_ref=source_ref,
            segment_kind=segment_kind,
            load_state=state,
            estimated_tokens=estimated_tokens,
            text=bounded_text,
            content_loaded=True,
            metadata={
                **dict(metadata),
                "truncated_to_budget": truncated,
            },
        ),
        max(0, remaining_budget - estimated_tokens),
    )


def _bounded_text(text: str, token_budget: int) -> tuple[str, int, bool]:
    estimated = _estimate_tokens(text)
    if estimated <= token_budget:
        return text, estimated, False
    character_budget = max(1, token_budget * 4)
    suffix = "..."
    if character_budget > len(suffix):
        bounded = text[: character_budget - len(suffix)].rstrip() + suffix
    else:
        bounded = text[:character_budget]
    return bounded, _estimate_tokens(bounded), True


def _materialization_budget_metadata(
    *,
    profile: ContextManagementProfile,
    request: ContextAssemblyRequest,
    initial_budget: int,
    remaining_budget: int,
    segment_count: int,
    loaded_tokens: int,
) -> Mapping[str, object]:
    metadata: dict[str, object] = {
        "max_input_tokens": profile.max_input_tokens,
        "estimated_input_tokens": _estimate_tokens(request.user_instruction),
        "materialization_token_budget": initial_budget,
        "remaining_materialization_tokens": remaining_budget,
        "estimated_materialized_tokens": loaded_tokens,
        "segment_count": segment_count,
        "compression_policy": "deterministic_selection_truncation_only",
    }
    if profile.recent_message_limit is not None:
        metadata["recent_message_limit"] = profile.recent_message_limit
    if profile.recent_token_budget is not None:
        metadata["recent_token_budget"] = profile.recent_token_budget
    return metadata


def _materialization_redaction_metadata(
    segments: Sequence[ContextMaterializedSegment],
) -> Mapping[str, object]:
    return {
        "current_user_instruction_copied": False,
        "conversation_messages_loaded": any(
            segment.segment_kind
            is ContextMaterializedSegmentKind.CONVERSATION_MESSAGE_WINDOW
            and segment.content_loaded
            for segment in segments
        ),
        "shared_context_summaries_loaded": any(
            segment.segment_kind
            is ContextMaterializedSegmentKind.SHARED_CONTEXT_UPDATE_SUMMARY
            and segment.content_loaded
            for segment in segments
        ),
        "shared_context_payload_loaded": False,
        "materialized_state_loaded": False,
        "task_summary_loaded": any(
            segment.segment_kind is ContextMaterializedSegmentKind.TASK_CONTEXT_SUMMARY
            and segment.content_loaded
            for segment in segments
        ),
        "file_bodies_loaded": False,
        "agent_private_memory_loaded": False,
        "provider_native_session_loaded": False,
        "external_context_engine_loaded": False,
    }


def _materialization_delivery_metadata() -> Mapping[str, object]:
    return {
        "provider_prompt_injected": False,
        "provider_payload_required": False,
        "agent_native_runtime_connected": False,
    }


def _safe_packet_label(value: str) -> str:
    return "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in value.strip()
    )


def _is_pass_through(profile: ContextManagementProfile) -> bool:
    return profile.strategy is ContextManagementStrategy.PASS_THROUGH


def _requires_compaction(profile: ContextManagementProfile) -> bool:
    return profile.strategy in {
        ContextManagementStrategy.PLATFORM_SUMMARY,
        ContextManagementStrategy.PROVIDER_NATIVE,
        ContextManagementStrategy.EXTERNAL_CONTEXT_ENGINE,
        ContextManagementStrategy.HYBRID,
    }


def _estimate_tokens(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    return max(1, (len(stripped) + 3) // 4)


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


def _optional_int(
    source: Mapping[str, object],
    *keys: str,
    default: int | None = None,
) -> int | None:
    value = _optional_value(source, *keys)
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{keys[0]} must be an integer.")
    return value


def _optional_bool(
    source: Mapping[str, object],
    *keys: str,
    default: bool,
) -> bool:
    value = _optional_value(source, *keys)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{keys[0]} must be a boolean.")
    return value


def _optional_string_tuple(
    source: Mapping[str, object],
    *keys: str,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    value = _optional_value(source, *keys)
    if value is None:
        return default
    if isinstance(value, str):
        return (value.strip(),)
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{keys[0]} must be a string or list of strings.")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{keys[0]} must be a string or list of strings.")
    return tuple(item.strip() for item in value)


def _optional_value(source: Mapping[str, object], *keys: str) -> object | None:
    for key in keys:
        if key in source:
            return source[key]
    return None


def _validate_unique_non_empty(values: tuple[str, ...], field_name: str) -> None:
    if not values:
        raise ValueError(f"{field_name} must include at least one value.")
    seen: set[str] = set()
    for value in values:
        _require_non_empty(value, field_name)
        if value in seen:
            raise ValueError(f"{field_name} must not contain duplicate values.")
        seen.add(value)


def _reject_unknown_keys(
    source: Mapping[str, object],
    allowed: set[str],
    logical_name: str,
) -> None:
    unknown = sorted(key for key in source if key not in allowed)
    if unknown:
        raise ValueError(f"{logical_name} contains unsupported field: {unknown[0]}.")


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


def _reject_sensitive_config(source: Mapping[str, object], logical_name: str) -> None:
    for key, value in source.items():
        normalized = _normalized_key(key)
        if normalized in _SENSITIVE_KEYS:
            raise ValueError(
                f"{logical_name} field '{key}' must not contain credential values."
            )
        if isinstance(value, Mapping):
            if normalized in _REFERENCE_KEYS:
                continue
            _reject_sensitive_config(value, f"{logical_name}.{key}")
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, Mapping):
                    _reject_sensitive_config(item, f"{logical_name}.{key}")


def _reject_sensitive_text(value: str, logical_name: str) -> None:
    if _SENSITIVE_TEXT_PATTERN.search(value):
        raise ValueError(f"{logical_name} must not contain credential values.")


def _normalized_key(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())


def _normalized_label(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
