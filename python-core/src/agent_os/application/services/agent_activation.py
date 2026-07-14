from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import re
from typing import Mapping, Sequence
from uuid import uuid4


class AgentActivationState(StrEnum):
    """Lifecycle states for manually woken advanced-agent access."""

    DORMANT = "dormant"
    AWAKENED = "awakened"
    ACTIVE_TASK_BOUND = "active_task_bound"
    AWAITING_USER_REVIEW = "awaiting_user_review"
    REVOKED = "revoked"
    EXPIRED = "expired"


class AgentActivationMode(StrEnum):
    """Supported activation modes for agent exchange access."""

    MANUAL_WAKE_SAFE_MODE = "manual_wake_safe_mode"
    TASK_BOUND_MANUAL = "task_bound_manual"
    REVIEW_ONLY = "review_only"
    RESERVED_AUTOMATIC = "reserved_automatic"


class AgentConnectionSurface(StrEnum):
    """Metadata-only labels for how a user expects an agent to connect."""

    CLI = "cli"
    DESKTOP_APP_CLI_CAPABLE = "desktop_app_cli_capable"
    IDE_CLI_CAPABLE = "ide_cli_capable"
    RESERVED_BROWSER_SESSION = "reserved_browser_session"


class AgentStopReason(StrEnum):
    """Reasons that stop or block a manually activated agent."""

    BUDGET_EXHAUSTED = "budget_exhausted"
    REQUIRES_USER_REVIEW = "requires_user_review"
    CONFLICT_DETECTED = "conflict_detected"
    PERMISSION_DENIED = "permission_denied"
    DUPLICATE_ACTIVITY = "duplicate_activity"
    AGENT_WAKE_DENIED = "agent_wake_denied"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class AgentActivityBudget:
    """Bounded activity budget attached to a manual wake grant."""

    ttl_seconds: int = 3600
    max_operations: int = 1
    max_writes: int = 1
    max_agent_to_agent_turns: int = 0
    max_context_reads: int = 5
    max_estimated_tokens: int | None = None
    expires_at: datetime | None = None

    @classmethod
    def from_mapping(
        cls,
        source: Mapping[str, object] | None,
        *,
        created_at: datetime,
    ) -> "AgentActivityBudget":
        config = dict(source or {})
        _reject_sensitive_config(config, "agentActivation.budget")
        ttl_seconds = _optional_int(config, "ttl_seconds", "ttlSeconds")
        expires_at = _optional_datetime(config, "expires_at", "expiresAt")
        max_operations = _optional_int(config, "max_operations", "maxOperations")
        max_writes = _optional_int(config, "max_writes", "maxWrites")
        max_agent_turns = _optional_int(
            config,
            "max_agent_to_agent_turns",
            "maxAgentToAgentTurns",
        )
        max_context_reads = _optional_int(
            config,
            "max_context_reads",
            "maxContextReads",
        )
        return cls(
            ttl_seconds=ttl_seconds if ttl_seconds is not None else 3600,
            max_operations=max_operations if max_operations is not None else 1,
            max_writes=max_writes if max_writes is not None else 1,
            max_agent_to_agent_turns=(
                max_agent_turns
                if max_agent_turns is not None
                else 0
            ),
            max_context_reads=(
                max_context_reads
                if max_context_reads is not None
                else 5
            ),
            max_estimated_tokens=_optional_int(
                config,
                "max_estimated_tokens",
                "maxEstimatedTokens",
            ),
            expires_at=expires_at
            or created_at + timedelta(seconds=ttl_seconds if ttl_seconds is not None else 3600),
        )

    def __post_init__(self) -> None:
        for field_name, value in (
            ("ttlSeconds", self.ttl_seconds),
            ("maxOperations", self.max_operations),
            ("maxWrites", self.max_writes),
            ("maxAgentToAgentTurns", self.max_agent_to_agent_turns),
            ("maxContextReads", self.max_context_reads),
        ):
            if value < 0:
                raise ValueError(f"{field_name} must be greater than or equal to zero.")
        if self.max_estimated_tokens is not None and self.max_estimated_tokens < 0:
            raise ValueError("maxEstimatedTokens must be greater than or equal to zero.")
        if self.expires_at is not None:
            _require_utc_aware(self.expires_at, "expiresAt")

    def to_metadata(self) -> Mapping[str, object]:
        return {
            "ttlSeconds": self.ttl_seconds,
            "maxOperations": self.max_operations,
            "maxWrites": self.max_writes,
            "maxAgentToAgentTurns": self.max_agent_to_agent_turns,
            "maxContextReads": self.max_context_reads,
            "maxEstimatedTokens": self.max_estimated_tokens,
            "expiresAt": (
                self.expires_at.isoformat()
                if self.expires_at is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class AgentActivationGrant:
    """Metadata-only manual wake grant for advanced-agent exchange access."""

    workspace_id: str
    agent_id: str
    created_by: str
    reason: str
    activation_id: str = field(default_factory=lambda: f"activation-{uuid4()}")
    state: AgentActivationState | str = AgentActivationState.AWAKENED
    mode: AgentActivationMode | str = AgentActivationMode.MANUAL_WAKE_SAFE_MODE
    connection_surface: AgentConnectionSurface | str = AgentConnectionSurface.CLI
    budget: AgentActivityBudget | Mapping[str, object] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    task_id: str | None = None
    conversation_id: str | None = None
    allowed_contribution_kinds: tuple[str, ...] = (
        "observation",
        "proposal",
        "completed_result",
        "blocked_issue",
        "conflict_note",
        "handoff_note",
        "question_for_user",
    )
    safe_mode: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)
    stop_reason: AgentStopReason | str | None = None
    revoked_at: datetime | None = None
    revoked_by: str | None = None
    revoke_reason: str | None = None
    source_event_sequence: int | None = None

    @classmethod
    def from_mapping(cls, source: Mapping[str, object]) -> "AgentActivationGrant":
        config = dict(source)
        _reject_sensitive_config(config, "agentActivation")
        created_at = _optional_datetime(config, "created_at", "createdAt") or _utc_now()
        return cls(
            workspace_id=_required_text(config, "workspace_id", "workspaceId"),
            agent_id=_required_text(config, "agent_id", "agentId"),
            created_by=_required_text(config, "created_by", "createdBy"),
            reason=_required_text(config, "reason"),
            activation_id=(
                _optional_text(config, "activation_id", "activationId")
                or f"activation-{uuid4()}"
            ),
            state=_optional_text(config, "state") or AgentActivationState.AWAKENED,
            mode=_optional_text(config, "mode") or AgentActivationMode.MANUAL_WAKE_SAFE_MODE,
            connection_surface=(
                _optional_text(config, "connection_surface", "connectionSurface")
                or AgentConnectionSurface.CLI
            ),
            budget=AgentActivityBudget.from_mapping(
                _optional_mapping(config, "budget"),
                created_at=created_at,
            ),
            created_at=created_at,
            task_id=_optional_text(config, "task_id", "taskId"),
            conversation_id=_optional_text(config, "conversation_id", "conversationId"),
            allowed_contribution_kinds=_text_tuple(
                _optional_value(
                    config,
                    "allowed_contribution_kinds",
                    "allowedContributionKinds",
                ),
                "allowedContributionKinds",
            )
            or (
                "observation",
                "proposal",
                "completed_result",
                "blocked_issue",
                "conflict_note",
                "handoff_note",
                "question_for_user",
            ),
            safe_mode=_optional_bool(config, "safe_mode", "safeMode", default=True),
            metadata=dict(_optional_mapping(config, "metadata") or {}),
            stop_reason=_optional_text(config, "stop_reason", "stopReason"),
            revoked_at=_optional_datetime(config, "revoked_at", "revokedAt"),
            revoked_by=_optional_text(config, "revoked_by", "revokedBy"),
            revoke_reason=_optional_text(config, "revoke_reason", "revokeReason"),
            source_event_sequence=_optional_int(
                config,
                "source_event_sequence",
                "sourceEventSequence",
            ),
        )

    def __post_init__(self) -> None:
        _validate_text(self.workspace_id, "workspaceId")
        _validate_text(self.agent_id, "agentId")
        _validate_text(self.activation_id, "activationId")
        _validate_text(self.created_by, "createdBy")
        _validate_text(self.reason, "reason")
        _validate_optional_text(self.task_id, "taskId")
        _validate_optional_text(self.conversation_id, "conversationId")
        _require_utc_aware(self.created_at, "createdAt")
        if self.revoked_at is not None:
            _require_utc_aware(self.revoked_at, "revokedAt")
        _reject_sensitive_config(dict(self.metadata), "agentActivation.metadata")

        state = _enum_value(AgentActivationState, self.state, "state")
        mode = _enum_value(AgentActivationMode, self.mode, "mode")
        surface = _enum_value(
            AgentConnectionSurface,
            self.connection_surface,
            "connectionSurface",
        )
        stop_reason = (
            _enum_value(AgentStopReason, self.stop_reason, "stopReason")
            if self.stop_reason is not None
            else None
        )
        budget = (
            self.budget
            if isinstance(self.budget, AgentActivityBudget)
            else AgentActivityBudget.from_mapping(
                self.budget,
                created_at=self.created_at,
            )
        )
        if mode is AgentActivationMode.RESERVED_AUTOMATIC:
            state = AgentActivationState.DORMANT
            stop_reason = AgentStopReason.AGENT_WAKE_DENIED
        if state is AgentActivationState.REVOKED and self.revoked_at is None:
            raise ValueError("revoked agent activation requires revokedAt.")
        if not self.allowed_contribution_kinds:
            raise ValueError("allowedContributionKinds must not be empty.")
        _validate_text_tuple(self.allowed_contribution_kinds, "allowedContributionKinds")

        object.__setattr__(self, "state", state)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "connection_surface", surface)
        object.__setattr__(self, "stop_reason", stop_reason)
        object.__setattr__(self, "budget", budget)
        object.__setattr__(
            self,
            "allowed_contribution_kinds",
            tuple(self.allowed_contribution_kinds),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))

    def expired_copy(self, *, checked_at: datetime | None = None) -> "AgentActivationGrant":
        return AgentActivationGrant.from_mapping(
            {
                **self.to_metadata(),
                "state": AgentActivationState.EXPIRED.value,
                "stopReason": AgentStopReason.EXPIRED.value,
                "metadata": {
                    **dict(self.metadata),
                    "expiredCheckedAt": (checked_at or _utc_now()).isoformat(),
                },
            }
        )

    def revoked_copy(
        self,
        *,
        revoked_by: str,
        reason: str,
        revoked_at: datetime | None = None,
    ) -> "AgentActivationGrant":
        return AgentActivationGrant.from_mapping(
            {
                **self.to_metadata(),
                "state": AgentActivationState.REVOKED.value,
                "stopReason": AgentStopReason.REVOKED.value,
                "revokedBy": revoked_by,
                "revokeReason": reason,
                "revokedAt": (revoked_at or _utc_now()).isoformat(),
            }
        )

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "schema": "agent_activation_grant.v1",
            "activationId": self.activation_id,
            "workspaceId": self.workspace_id,
            "agentId": self.agent_id,
            "state": self.state.value,
            "mode": self.mode.value,
            "connectionSurface": self.connection_surface.value,
            "createdAt": self.created_at.isoformat(),
            "createdBy": self.created_by,
            "reason": self.reason,
            "safeMode": self.safe_mode,
            "budget": self.budget.to_metadata(),
            "allowedContributionKinds": list(self.allowed_contribution_kinds),
            "realRuntimeConnected": False,
            "backgroundLoopEnabled": False,
            "agentAutoWakeEnabled": False,
            "providerPromptInjected": False,
            "fileBodiesReadableThroughActivation": False,
            "requiresManualUserWake": True,
            "highRiskWritesRequireReview": True,
        }
        for key, value in (
            ("taskId", self.task_id),
            ("conversationId", self.conversation_id),
            ("stopReason", self.stop_reason.value if self.stop_reason else None),
            ("revokedAt", self.revoked_at.isoformat() if self.revoked_at else None),
            ("revokedBy", self.revoked_by),
            ("revokeReason", self.revoke_reason),
            ("sourceEventSequence", self.source_event_sequence),
        ):
            if value is not None:
                metadata[key] = value
        if self.metadata:
            metadata["metadata"] = dict(self.metadata)
        return metadata

    def is_write_allowed(
        self,
        *,
        contribution_kind: str,
        checked_at: datetime | None = None,
    ) -> tuple[bool, str | None]:
        current = self
        if self.state is not AgentActivationState.REVOKED and self.is_expired(checked_at):
            current = self.expired_copy(checked_at=checked_at)
        if current.state in {
            AgentActivationState.DORMANT,
            AgentActivationState.REVOKED,
            AgentActivationState.EXPIRED,
            AgentActivationState.AWAITING_USER_REVIEW,
        }:
            return False, current.stop_reason.value if current.stop_reason else current.state.value
        if contribution_kind not in set(current.allowed_contribution_kinds):
            return False, AgentStopReason.PERMISSION_DENIED.value
        return True, None

    def is_expired(self, checked_at: datetime | None = None) -> bool:
        expires_at = self.budget.expires_at
        if expires_at is None:
            return False
        return expires_at <= (checked_at or _utc_now())


def agent_activation_interface_metadata(
    *,
    workspace_id: str | None = None,
) -> Mapping[str, object]:
    """Agent-facing contract for manual wake and safe-mode budgets."""

    return {
        "agentActivationInterface": {
            "schema": "agent_activation_interface.v1",
            "workspaceId": workspace_id,
            "status": "contract_only",
            "activationStates": [item.value for item in AgentActivationState],
            "activationModes": [item.value for item in AgentActivationMode],
            "connectionSurfaces": [item.value for item in AgentConnectionSurface],
            "stopReasons": [item.value for item in AgentStopReason],
            "metadataKey": "agentActivation",
            "exchangeLinkKey": "linkedActivationId",
            "safeModeDefaults": {
                "requiresManualUserWake": True,
                "agentAutoWakeEnabled": False,
                "agentToAgentAutoWakeAllowed": False,
                "highRiskWritesRequireReview": True,
                "realRuntimeConnected": False,
                "providerPromptInjected": False,
                "fileBodiesReadableThroughActivation": False,
            },
            "defaultBudget": AgentActivityBudget.from_mapping(
                None,
                created_at=_utc_now(),
            ).to_metadata(),
            "localRuntimeCommands": {
                "instructions": "agent-activation-instructions",
                "wake": "agent-activation-wake",
                "status": "agent-activation-status",
                "revoke": "agent-activation-revoke",
                "appendContextWithActivation": (
                    "context-append --exchange-attribution-json "
                    "{\"linkedActivationId\":\"...\"}"
                ),
                "appendConversationWithActivation": (
                    "conversation-message-append --exchange-attribution-json "
                    "{\"linkedActivationId\":\"...\"}"
                ),
            },
        }
    }


def dormant_agent_activation_metadata(
    *,
    workspace_id: str,
    agent_id: str | None = None,
) -> Mapping[str, object]:
    return {
        "schema": "agent_activation_grant.v1",
        "activationId": None,
        "workspaceId": workspace_id,
        "agentId": agent_id,
        "state": AgentActivationState.DORMANT.value,
        "mode": AgentActivationMode.MANUAL_WAKE_SAFE_MODE.value,
        "safeMode": True,
        "realRuntimeConnected": False,
        "backgroundLoopEnabled": False,
        "agentAutoWakeEnabled": False,
        "providerPromptInjected": False,
        "fileBodiesReadableThroughActivation": False,
        "requiresManualUserWake": True,
        "highRiskWritesRequireReview": True,
    }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _required_text(source: Mapping[str, object], *keys: str) -> str:
    value = _optional_text(source, *keys)
    if value is None:
        raise ValueError(f"{keys[0]} is required.")
    return value


def _optional_text(source: Mapping[str, object], *keys: str) -> str | None:
    value = _optional_value(source, *keys)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{keys[0]} must be a non-empty string.")
    return value.strip()


def _optional_int(source: Mapping[str, object], *keys: str) -> int | None:
    value = _optional_value(source, *keys)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{keys[0]} must be an integer.")
    return value


def _optional_bool(
    source: Mapping[str, object],
    *keys: str,
    default: bool | None = None,
) -> bool | None:
    value = _optional_value(source, *keys)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{keys[0]} must be a boolean.")
    return value


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


def _optional_value(source: Mapping[str, object], *keys: str) -> object | None:
    for key in keys:
        if key in source:
            return source[key]
    return None


def _optional_datetime(source: Mapping[str, object], *keys: str) -> datetime | None:
    value = _optional_value(source, *keys)
    if value is None:
        return None
    if isinstance(value, datetime):
        _require_utc_aware(value, keys[0])
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{keys[0]} must be an ISO datetime string.")
    parsed = datetime.fromisoformat(value.strip())
    _require_utc_aware(parsed, keys[0])
    return parsed


def _text_tuple(value: object | None, logical_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (_require_text_value(value, logical_name),)
    if not isinstance(value, Sequence):
        raise ValueError(f"{logical_name} must be a string or array of strings.")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{logical_name} must contain non-empty strings.")
        result.append(item.strip())
    return tuple(result)


def _require_text_value(value: str, logical_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{logical_name} must be a non-empty string.")
    return value.strip()


def _validate_text(value: str, logical_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{logical_name} must be a non-empty string.")


def _validate_optional_text(value: str | None, logical_name: str) -> None:
    if value is not None and not value.strip():
        raise ValueError(f"{logical_name} must be a non-empty string.")


def _validate_text_tuple(values: tuple[str, ...], logical_name: str) -> None:
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{logical_name} must contain non-empty strings.")
        if value in seen:
            raise ValueError(f"{logical_name} must not contain duplicate values.")
        seen.add(value)


def _require_utc_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")


def _enum_value(enum_type, value, logical_name: str):
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{logical_name} must be a non-empty string.")
    normalized = value.strip().lower().replace("-", "_")
    try:
        return enum_type(normalized)
    except ValueError as exc:
        valid = ", ".join(item.value for item in enum_type)
        raise ValueError(f"{logical_name} must be one of: {valid}.") from exc


_SENSITIVE_KEYS = {
    "apikey",
    "authorization",
    "bearertoken",
    "cookie",
    "credential",
    "credentialenvvar",
    "credentialref",
    "credentialreference",
    "password",
    "secret",
    "sessiontoken",
    "token",
}

_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9]{20,}|Bearer\s+sk-|Authorization:\s*Bearer|Cookie:)",
    re.IGNORECASE,
)


def _reject_sensitive_config(source: Mapping[str, object], logical_name: str) -> None:
    for key, value in source.items():
        normalized_key = re.sub(r"[^a-zA-Z0-9]", "", str(key)).lower()
        if normalized_key in _SENSITIVE_KEYS:
            raise ValueError(f"{logical_name}.{key} must not contain credential values.")
        if isinstance(value, str) and _SENSITIVE_TEXT_PATTERN.search(value):
            raise ValueError(f"{logical_name}.{key} must not contain credential values.")
        if isinstance(value, Mapping):
            _reject_sensitive_config(value, f"{logical_name}.{key}")
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for index, item in enumerate(value):
                if isinstance(item, Mapping):
                    _reject_sensitive_config(item, f"{logical_name}.{key}[{index}]")
                elif isinstance(item, str) and _SENSITIVE_TEXT_PATTERN.search(item):
                    raise ValueError(
                        f"{logical_name}.{key}[{index}] must not contain credential values."
                    )
