from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import re
from typing import Mapping, Sequence
from uuid import uuid4

from agent_os.application.services.agent_activation import (
    AgentActivationMode,
    AgentActivityBudget,
)


class DelegatedWakeGrantState(StrEnum):
    """Lifecycle states for a user-authorized delegated one-time wake grant."""

    PENDING = "pending"
    CONSUMED = "consumed"
    REVOKED = "revoked"
    EXPIRED = "expired"
    DENIED = "denied"


class DelegatedWakeGrantMode(StrEnum):
    """Supported modes for a delegated wake grant.

    Only ``user_authorized_one_time`` is an executable single-use grant.
    ``review_only`` records a grant that still requires an explicit user wake.
    ``reserved_automatic_denied`` is the stable label for any automatic
    agent-to-agent wake attempt; those grants are always created in the
    ``denied`` state and can never be consumed.
    """

    USER_AUTHORIZED_ONE_TIME = "user_authorized_one_time"
    REVIEW_ONLY = "review_only"
    RESERVED_AUTOMATIC_DENIED = "reserved_automatic_denied"


class DelegatedWakeDenyReason(StrEnum):
    """Stable deny reasons for delegated wake grant consume attempts."""

    SOURCE_AGENT_MISMATCH = "source_agent_mismatch"
    TARGET_AGENT_MISMATCH = "target_agent_mismatch"
    GRANT_EXPIRED = "grant_expired"
    GRANT_REVOKED = "grant_revoked"
    GRANT_ALREADY_CONSUMED = "grant_already_consumed"
    PERMISSION_DENIED = "permission_denied"
    TARGET_AGENT_NOT_FOUND = "target_agent_not_found"
    AUTOMATIC_WAKE_DENIED = "automatic_wake_denied"


_DEFAULT_ALLOWED_CONTRIBUTION_KINDS: tuple[str, ...] = (
    "observation",
    "proposal",
    "completed_result",
    "blocked_issue",
    "conflict_note",
    "handoff_note",
    "question_for_user",
)
_DEFAULT_GRANT_TTL_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class DelegatedWakeGrant:
    """User-authorized, single-use, non-delegatable wake grant contract.

    A delegated wake grant lets a user pre-authorize one ``sourceAgentId`` to
    create a single bounded ``AgentActivationGrant`` for one ``targetAgentId``
    inside a workspace/task/conversation scope. The grant is local audit
    metadata only: consuming it never connects, wakes, hosts, or controls a
    real external agent runtime, and it grants no tool/file/memory/network
    permission beyond what the existing runtime-access contract allows.
    """

    workspace_id: str
    source_agent_id: str
    target_agent_id: str
    created_by: str
    reason: str
    delegated_wake_grant_id: str = field(
        default_factory=lambda: f"delegated-wake-{uuid4()}"
    )
    state: DelegatedWakeGrantState | str = DelegatedWakeGrantState.PENDING
    mode: DelegatedWakeGrantMode | str = (
        DelegatedWakeGrantMode.USER_AUTHORIZED_ONE_TIME
    )
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    max_uses: int = 1
    uses_consumed: int = 0
    can_delegate_further: bool = False
    task_id: str | None = None
    conversation_id: str | None = None
    target_activation_mode: AgentActivationMode | str = (
        AgentActivationMode.MANUAL_WAKE_SAFE_MODE
    )
    target_activation_budget: AgentActivityBudget | Mapping[str, object] | None = None
    allowed_contribution_kinds: tuple[str, ...] = _DEFAULT_ALLOWED_CONTRIBUTION_KINDS
    revoked_by: str | None = None
    revocation_reason: str | None = None
    revoked_at: datetime | None = None
    consumed_by_agent_id: str | None = None
    consumed_at: datetime | None = None
    target_activation_id: str | None = None
    deny_reason: DelegatedWakeDenyReason | str | None = None
    denied_at: datetime | None = None
    denied_by_agent_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)
    source_event_sequence: int | None = None

    @classmethod
    def from_mapping(cls, source: Mapping[str, object]) -> "DelegatedWakeGrant":
        config = dict(source)
        _reject_sensitive_config(config, "delegatedWakeGrant")
        created_at = _optional_datetime(config, "created_at", "createdAt") or _utc_now()
        expires_at = _optional_datetime(config, "expires_at", "expiresAt") or (
            created_at + timedelta(seconds=_DEFAULT_GRANT_TTL_SECONDS)
        )
        return cls(
            workspace_id=_required_text(config, "workspace_id", "workspaceId"),
            source_agent_id=_required_text(
                config, "source_agent_id", "sourceAgentId"
            ),
            target_agent_id=_required_text(
                config, "target_agent_id", "targetAgentId"
            ),
            created_by=_required_text(config, "created_by", "createdBy"),
            reason=_required_text(config, "reason"),
            delegated_wake_grant_id=(
                _optional_text(
                    config, "delegated_wake_grant_id", "delegatedWakeGrantId"
                )
                or f"delegated-wake-{uuid4()}"
            ),
            state=_optional_text(config, "state") or DelegatedWakeGrantState.PENDING,
            mode=(
                _optional_text(config, "mode")
                or DelegatedWakeGrantMode.USER_AUTHORIZED_ONE_TIME
            ),
            created_at=created_at,
            expires_at=expires_at,
            max_uses=(
                _optional_int(config, "max_uses", "maxUses")
                if _optional_int(config, "max_uses", "maxUses") is not None
                else 1
            ),
            uses_consumed=(
                _optional_int(config, "uses_consumed", "usesConsumed") or 0
            ),
            can_delegate_further=_optional_bool(
                config, "can_delegate_further", "canDelegateFurther", default=False
            )
            or False,
            task_id=_optional_text(config, "task_id", "taskId"),
            conversation_id=_optional_text(config, "conversation_id", "conversationId"),
            target_activation_mode=(
                _optional_text(config, "target_activation_mode", "targetActivationMode")
                or AgentActivationMode.MANUAL_WAKE_SAFE_MODE
            ),
            target_activation_budget=AgentActivityBudget.from_mapping(
                _optional_mapping(config, "target_activation_budget", "targetActivationBudget"),
                created_at=created_at,
            ),
            allowed_contribution_kinds=_text_tuple(
                _optional_value(
                    config,
                    "allowed_contribution_kinds",
                    "allowedContributionKinds",
                ),
                "allowedContributionKinds",
            )
            or _DEFAULT_ALLOWED_CONTRIBUTION_KINDS,
            revoked_by=_optional_text(config, "revoked_by", "revokedBy"),
            revocation_reason=_optional_text(
                config, "revocation_reason", "revocationReason"
            ),
            revoked_at=_optional_datetime(config, "revoked_at", "revokedAt"),
            consumed_by_agent_id=_optional_text(
                config, "consumed_by_agent_id", "consumedByAgentId"
            ),
            consumed_at=_optional_datetime(config, "consumed_at", "consumedAt"),
            target_activation_id=_optional_text(
                config, "target_activation_id", "targetActivationId"
            ),
            deny_reason=_optional_text(config, "deny_reason", "denyReason"),
            denied_at=_optional_datetime(config, "denied_at", "deniedAt"),
            denied_by_agent_id=_optional_text(
                config, "denied_by_agent_id", "deniedByAgentId"
            ),
            metadata=dict(_optional_mapping(config, "metadata") or {}),
            source_event_sequence=_optional_int(
                config, "source_event_sequence", "sourceEventSequence"
            ),
        )

    def __post_init__(self) -> None:
        _validate_text(self.workspace_id, "workspaceId")
        _validate_text(self.source_agent_id, "sourceAgentId")
        _validate_text(self.target_agent_id, "targetAgentId")
        if self.source_agent_id == self.target_agent_id:
            raise ValueError(
                "sourceAgentId and targetAgentId must not be the same agent."
            )
        _validate_text(self.delegated_wake_grant_id, "delegatedWakeGrantId")
        _validate_text(self.created_by, "createdBy")
        _validate_text(self.reason, "reason")
        _validate_optional_text(self.task_id, "taskId")
        _validate_optional_text(self.conversation_id, "conversationId")
        _validate_optional_text(self.revoked_by, "revokedBy")
        _validate_optional_text(self.revocation_reason, "revocationReason")
        _validate_optional_text(self.consumed_by_agent_id, "consumedByAgentId")
        _validate_optional_text(self.target_activation_id, "targetActivationId")
        _validate_optional_text(self.denied_by_agent_id, "deniedByAgentId")
        _require_utc_aware(self.created_at, "createdAt")
        if self.expires_at is not None:
            _require_utc_aware(self.expires_at, "expiresAt")
        if self.revoked_at is not None:
            _require_utc_aware(self.revoked_at, "revokedAt")
        if self.consumed_at is not None:
            _require_utc_aware(self.consumed_at, "consumedAt")
        if self.denied_at is not None:
            _require_utc_aware(self.denied_at, "deniedAt")
        _reject_sensitive_config(dict(self.metadata), "delegatedWakeGrant.metadata")

        if self.max_uses != 1:
            raise ValueError(
                "maxUses must be 1 for a one-time delegated wake grant."
            )
        if self.uses_consumed < 0:
            raise ValueError("usesConsumed must be greater than or equal to zero.")
        if self.uses_consumed > self.max_uses:
            raise ValueError("usesConsumed must not exceed maxUses.")

        state = _enum_value(DelegatedWakeGrantState, self.state, "state")
        mode = _enum_value(DelegatedWakeGrantMode, self.mode, "mode")
        target_mode = _enum_value(
            AgentActivationMode, self.target_activation_mode, "targetActivationMode"
        )
        deny_reason = (
            _enum_value(DelegatedWakeDenyReason, self.deny_reason, "denyReason")
            if self.deny_reason is not None
            else None
        )
        budget = (
            self.target_activation_budget
            if isinstance(self.target_activation_budget, AgentActivityBudget)
            else AgentActivityBudget.from_mapping(
                self.target_activation_budget,
                created_at=self.created_at,
            )
        )

        # A delegated wake grant can never enable further delegation.
        can_delegate_further = False

        if mode is DelegatedWakeGrantMode.RESERVED_AUTOMATIC_DENIED:
            state = DelegatedWakeGrantState.DENIED
            deny_reason = DelegatedWakeDenyReason.AUTOMATIC_WAKE_DENIED
        if state is DelegatedWakeGrantState.REVOKED and self.revoked_at is None:
            raise ValueError("revoked delegated wake grant requires revokedAt.")
        if state is DelegatedWakeGrantState.CONSUMED and self.consumed_at is None:
            raise ValueError("consumed delegated wake grant requires consumedAt.")
        if not self.allowed_contribution_kinds:
            raise ValueError("allowedContributionKinds must not be empty.")
        _validate_text_tuple(self.allowed_contribution_kinds, "allowedContributionKinds")

        object.__setattr__(self, "state", state)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "target_activation_mode", target_mode)
        object.__setattr__(self, "deny_reason", deny_reason)
        object.__setattr__(
            self, "target_activation_budget", budget
        )
        object.__setattr__(self, "can_delegate_further", can_delegate_further)
        object.__setattr__(
            self,
            "allowed_contribution_kinds",
            tuple(self.allowed_contribution_kinds),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))

    def is_expired(self, checked_at: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at <= (checked_at or _utc_now())

    def expired_copy(self, *, checked_at: datetime | None = None) -> "DelegatedWakeGrant":
        return DelegatedWakeGrant.from_mapping(
            {
                **self.to_metadata(),
                "state": DelegatedWakeGrantState.EXPIRED.value,
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
    ) -> "DelegatedWakeGrant":
        return DelegatedWakeGrant.from_mapping(
            {
                **self.to_metadata(),
                "state": DelegatedWakeGrantState.REVOKED.value,
                "revokedBy": revoked_by,
                "revocationReason": reason,
                "revokedAt": (revoked_at or _utc_now()).isoformat(),
            }
        )

    def consumed_copy(
        self,
        *,
        consumed_by_agent_id: str,
        target_activation_id: str,
        consumed_at: datetime | None = None,
    ) -> "DelegatedWakeGrant":
        timestamp = consumed_at or _utc_now()
        return DelegatedWakeGrant.from_mapping(
            {
                **self.to_metadata(),
                "state": DelegatedWakeGrantState.CONSUMED.value,
                "usesConsumed": self.uses_consumed + 1,
                "consumedByAgentId": consumed_by_agent_id,
                "consumedAt": timestamp.isoformat(),
                "targetActivationId": target_activation_id,
            }
        )

    def denied_copy(
        self,
        *,
        deny_reason: DelegatedWakeDenyReason | str,
        denied_by_agent_id: str | None = None,
        denied_at: datetime | None = None,
    ) -> "DelegatedWakeGrant":
        """Return an audit copy recording a consume denial.

        The grant state is preserved; only the deny audit metadata is added so
        the rejection stays auditable without making a still-pending grant
        permanently unusable by the correct source agent.
        """

        return DelegatedWakeGrant.from_mapping(
            {
                **self.to_metadata(),
                "denyReason": _enum_value(
                    DelegatedWakeDenyReason, deny_reason, "denyReason"
                ).value,
                "deniedAt": (denied_at or _utc_now()).isoformat(),
                "deniedByAgentId": denied_by_agent_id,
            }
        )

    def is_consume_allowed(
        self,
        *,
        consuming_agent_id: str,
        target_agent_exists: bool,
        target_agent_id: str | None = None,
        checked_at: datetime | None = None,
    ) -> tuple[bool, DelegatedWakeDenyReason | str | None]:
        current = self
        if (
            current.state is not DelegatedWakeGrantState.REVOKED
            and current.state is not DelegatedWakeGrantState.CONSUMED
            and current.state is not DelegatedWakeGrantState.DENIED
            and current.is_expired(checked_at)
        ):
            current = current.expired_copy(checked_at=checked_at)
        if current.state is DelegatedWakeGrantState.EXPIRED:
            return False, DelegatedWakeDenyReason.GRANT_EXPIRED
        if current.state is DelegatedWakeGrantState.REVOKED:
            return False, DelegatedWakeDenyReason.GRANT_REVOKED
        if current.state is DelegatedWakeGrantState.DENIED:
            return False, current.deny_reason or DelegatedWakeDenyReason.AUTOMATIC_WAKE_DENIED
        if current.state is DelegatedWakeGrantState.CONSUMED:
            return False, DelegatedWakeDenyReason.GRANT_ALREADY_CONSUMED
        if current.mode is DelegatedWakeGrantMode.RESERVED_AUTOMATIC_DENIED:
            return False, DelegatedWakeDenyReason.AUTOMATIC_WAKE_DENIED
        if current.source_agent_id != consuming_agent_id:
            return False, DelegatedWakeDenyReason.SOURCE_AGENT_MISMATCH
        if target_agent_id is not None and current.target_agent_id != target_agent_id:
            return False, DelegatedWakeDenyReason.TARGET_AGENT_MISMATCH
        if not target_agent_exists:
            return False, DelegatedWakeDenyReason.TARGET_AGENT_NOT_FOUND
        if current.uses_consumed >= current.max_uses:
            return False, DelegatedWakeDenyReason.GRANT_ALREADY_CONSUMED
        return True, None

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "schema": "delegated_wake_grant.v1",
            "delegatedWakeGrantId": self.delegated_wake_grant_id,
            "workspaceId": self.workspace_id,
            "sourceAgentId": self.source_agent_id,
            "targetAgentId": self.target_agent_id,
            "state": self.state.value,
            "mode": self.mode.value,
            "createdAt": self.created_at.isoformat(),
            "createdBy": self.created_by,
            "reason": self.reason,
            "maxUses": self.max_uses,
            "usesConsumed": self.uses_consumed,
            "canDelegateFurther": self.can_delegate_further,
            "targetActivationMode": self.target_activation_mode.value,
            "targetActivationBudget": self.target_activation_budget.to_metadata(),
            "allowedContributionKinds": list(self.allowed_contribution_kinds),
            "realRuntimeConnected": False,
            "backgroundLoopEnabled": False,
            "agentAutoWakeEnabled": False,
            "userAuthorizedDelegatedWake": (
                self.mode is DelegatedWakeGrantMode.USER_AUTHORIZED_ONE_TIME
            ),
            "providerPromptInjected": False,
            "fileBodiesReadableThroughGrant": False,
            "grantsRuntimePermissions": False,
        }
        for key, value in (
            ("expiresAt", self.expires_at.isoformat() if self.expires_at else None),
            ("taskId", self.task_id),
            ("conversationId", self.conversation_id),
            ("revokedBy", self.revoked_by),
            ("revocationReason", self.revocation_reason),
            ("revokedAt", self.revoked_at.isoformat() if self.revoked_at else None),
            ("consumedByAgentId", self.consumed_by_agent_id),
            ("consumedAt", self.consumed_at.isoformat() if self.consumed_at else None),
            ("targetActivationId", self.target_activation_id),
            ("denyReason", self.deny_reason.value if self.deny_reason else None),
            ("deniedAt", self.denied_at.isoformat() if self.denied_at else None),
            ("deniedByAgentId", self.denied_by_agent_id),
            ("sourceEventSequence", self.source_event_sequence),
        ):
            if value is not None:
                metadata[key] = value
        if self.metadata:
            metadata["metadata"] = dict(self.metadata)
        return metadata


def delegated_wake_interface_metadata(
    *,
    workspace_id: str | None = None,
) -> Mapping[str, object]:
    """Agent-facing contract for user-authorized delegated one-time wake."""

    return {
        "delegatedWakeInterface": {
            "schema": "delegated_wake_interface.v1",
            "workspaceId": workspace_id,
            "status": "contract_only",
            "grantStates": [item.value for item in DelegatedWakeGrantState],
            "grantModes": [item.value for item in DelegatedWakeGrantMode],
            "denyReasons": [item.value for item in DelegatedWakeDenyReason],
            "metadataKey": "delegatedWakeGrant",
            "defaults": {
                "maxUses": 1,
                "ttlSeconds": _DEFAULT_GRANT_TTL_SECONDS,
                "canDelegateFurther": False,
                "userAuthorizedDelegatedWake": True,
                "agentAutoWakeEnabled": False,
                "agentToAgentAutoWakeAllowed": False,
                "realRuntimeConnected": False,
                "backgroundLoopEnabled": False,
                "providerPromptInjected": False,
                "fileBodiesReadableThroughGrant": False,
                "grantsRuntimePermissions": False,
            },
            "rules": [
                "agents must not wake other agents automatically",
                "only a user-created delegated wake grant may let a source agent create one target activation",
                "a grant is single-use: maxUses defaults to 1 and cannot be raised to allow repeated consumption",
                "a grant can never be re-delegated: canDelegateFurther is always false",
                "consuming a grant creates a bounded target activation but does not connect or control a real runtime",
                "the target agent is not woken; it must still read platform state through its own CLI/API surface",
                "a grant grants no tool, file, memory, network, provider prompt, or runtime-control permission",
                "all writes under the target activation must still use agentExchange and linkedActivationId",
            ],
            "localRuntimeCommands": {
                "instructions": "agent-delegated-wake-grant-instructions",
                "create": "agent-delegated-wake-grant-create",
                "status": "agent-delegated-wake-grant-status",
                "consume": "agent-delegated-wake-grant-consume",
                "revoke": "agent-delegated-wake-grant-revoke",
            },
        }
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
