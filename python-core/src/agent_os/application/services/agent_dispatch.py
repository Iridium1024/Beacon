from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping
from uuid import uuid4


class AgentDispatchStatus(StrEnum):
    """Platform-side dispatch queue state, not provider runtime state."""

    DRY_RUN = "dry_run"
    QUEUED = "queued"
    LEASED = "leased"
    WAITING_RESPONSE = "waiting_response"
    RETRY_SCHEDULED = "retry_scheduled"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"


class AgentDispatchReplyPolicy(StrEnum):
    """How the source side expects follow-up delivery to work."""

    MESSAGE_ONLY = "message_only"
    SOURCE_HANDLE_OPTIONAL = "source_handle_optional"
    SOURCE_HANDLE_REQUIRED = "source_handle_required"


class AgentDispatchLeaseState(StrEnum):
    """Minimal per-target dispatch lease state."""

    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class AgentDispatchRecord:
    """Append-only queue record for high-level agent-to-agent dispatch.

    The record intentionally describes platform dispatch state only. Provider
    runtime presence/status adapters are layered on top in later hardening steps.
    """

    workspace_id: str
    dispatch_id: str
    exchange_request_id: str
    source_agent_id: str
    target_agent_id: str
    status: AgentDispatchStatus | str = AgentDispatchStatus.QUEUED
    thread_id: str | None = None
    source_handle_id: str | None = None
    target_handle_id: str | None = None
    target_provider: str | None = None
    reply_policy: AgentDispatchReplyPolicy | str = (
        AgentDispatchReplyPolicy.SOURCE_HANDLE_OPTIONAL
    )
    lease_id: str | None = None
    lease_expires_at: datetime | None = None
    next_attempt_after: datetime | None = None
    attempt_count: int = 0
    busy_skip_count: int = 0
    last_busy_skip_at: datetime | None = None
    busy_retry_delay_seconds: int | None = None
    dispatcher_required: bool = True
    provider_runtime_state_supported: bool = False
    provider_runtime_state: str = "unknown"
    provider_state_source: str = "platform_dispatch_queue"
    provider_activation_executed: bool = False
    provider_runtime_status_read: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, object] = field(default_factory=dict)
    source_event_sequence: int | None = None

    @classmethod
    def from_mapping(cls, source: Mapping[str, object]) -> "AgentDispatchRecord":
        config = dict(source)
        _reject_sensitive_config(config, "agentDispatch")
        status = _enum_value(
            AgentDispatchStatus,
            _optional_text(config, "status") or AgentDispatchStatus.QUEUED.value,
            "status",
        )
        reply_policy = _enum_value(
            AgentDispatchReplyPolicy,
            _optional_text(config, "reply_policy", "replyPolicy")
            or AgentDispatchReplyPolicy.SOURCE_HANDLE_OPTIONAL.value,
            "replyPolicy",
        )
        source_handle_id = _optional_text(
            config,
            "source_handle_id",
            "sourceHandleId",
        )
        if (
            reply_policy is AgentDispatchReplyPolicy.SOURCE_HANDLE_REQUIRED
            and source_handle_id is None
        ):
            raise ValueError("sourceHandleId is required by replyPolicy.")
        activation_boundary = _metadata(config.get("activationAutomationBoundary"))
        provider_activation_executed = _optional_bool(
            config,
            "provider_activation_executed",
            "providerActivationExecuted",
        )
        provider_runtime_status_read = _optional_bool(
            config,
            "provider_runtime_status_read",
            "providerRuntimeStatusRead",
        )
        return cls(
            workspace_id=_required_text(config, "workspace_id", "workspaceId"),
            dispatch_id=(
                _optional_text(config, "dispatch_id", "dispatchId")
                or f"agent-dispatch-{uuid4()}"
            ),
            exchange_request_id=_required_text(
                config,
                "exchange_request_id",
                "exchangeRequestId",
            ),
            source_agent_id=_required_text(
                config,
                "source_agent_id",
                "sourceAgentId",
            ),
            target_agent_id=_required_text(
                config,
                "target_agent_id",
                "targetAgentId",
            ),
            status=status,
            thread_id=_optional_text(config, "thread_id", "threadId"),
            source_handle_id=source_handle_id,
            target_handle_id=_optional_text(
                config,
                "target_handle_id",
                "targetHandleId",
            ),
            target_provider=_optional_text(config, "target_provider", "targetProvider"),
            reply_policy=reply_policy,
            lease_id=_optional_text(config, "lease_id", "leaseId"),
            lease_expires_at=_optional_datetime(
                config,
                "lease_expires_at",
                "leaseExpiresAt",
            ),
            next_attempt_after=_optional_datetime(
                config,
                "next_attempt_after",
                "nextAttemptAfter",
            ),
            attempt_count=_optional_int(config, "attempt_count", "attemptCount") or 0,
            busy_skip_count=(
                _optional_int(config, "busy_skip_count", "busySkipCount") or 0
            ),
            last_busy_skip_at=_optional_datetime(
                config,
                "last_busy_skip_at",
                "lastBusySkipAt",
            ),
            busy_retry_delay_seconds=_optional_int(
                config,
                "busy_retry_delay_seconds",
                "busyRetryDelaySeconds",
            ),
            dispatcher_required=_optional_bool(
                config,
                "dispatcher_required",
                "dispatcherRequired",
                default=True,
            )
            or False,
            provider_runtime_state_supported=_optional_bool(
                config,
                "provider_runtime_state_supported",
                "providerRuntimeStateSupported",
                default=False,
            )
            or False,
            provider_runtime_state=(
                _optional_text(
                    config,
                    "provider_runtime_state",
                    "providerRuntimeState",
                )
                or "unknown"
            ),
            provider_state_source=(
                _optional_text(config, "provider_state_source", "providerStateSource")
                or "platform_dispatch_queue"
            ),
            provider_activation_executed=(
                provider_activation_executed
                if provider_activation_executed is not None
                else (
                    _optional_bool(
                        activation_boundary,
                        "providerActivationExecuted",
                        default=False,
                    )
                    or False
                )
            ),
            provider_runtime_status_read=(
                provider_runtime_status_read
                if provider_runtime_status_read is not None
                else (
                    _optional_bool(
                        activation_boundary,
                        "providerRuntimeStatusRead",
                        default=False,
                    )
                    or False
                )
            ),
            created_at=(
                _optional_datetime(config, "created_at", "createdAt")
                or datetime.now(timezone.utc)
            ),
            updated_at=(
                _optional_datetime(config, "updated_at", "updatedAt")
                or datetime.now(timezone.utc)
            ),
            metadata=_metadata(config.get("metadata")),
            source_event_sequence=_optional_int(
                config,
                "source_event_sequence",
                "sourceEventSequence",
            ),
        )

    def active_copy(
        self,
        *,
        status: AgentDispatchStatus | str,
        updated_at: datetime,
        lease_id: str | None = None,
        lease_expires_at: datetime | None = None,
        clear_lease: bool = False,
        next_attempt_after: datetime | None = None,
        clear_next_attempt_after: bool = False,
        attempt_count: int | None = None,
        busy_skip_count: int | None = None,
        last_busy_skip_at: datetime | None = None,
        busy_retry_delay_seconds: int | None = None,
        clear_busy_retry_delay: bool = False,
        provider_runtime_state_supported: bool | None = None,
        provider_runtime_state: str | None = None,
        provider_state_source: str | None = None,
        provider_activation_executed: bool | None = None,
        provider_runtime_status_read: bool | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> "AgentDispatchRecord":
        return AgentDispatchRecord.from_mapping(
            {
                **self.to_metadata(),
                "status": status.value if isinstance(status, AgentDispatchStatus) else status,
                "leaseId": (
                    None
                    if clear_lease
                    else (lease_id if lease_id is not None else self.lease_id)
                ),
                "leaseExpiresAt": (
                    None
                    if clear_lease
                    else (
                        lease_expires_at.isoformat()
                        if lease_expires_at is not None
                        else (
                            self.lease_expires_at.isoformat()
                            if self.lease_expires_at is not None
                            else None
                        )
                    )
                ),
                "nextAttemptAfter": (
                    None
                    if clear_next_attempt_after
                    else (
                        next_attempt_after.isoformat()
                        if next_attempt_after is not None
                        else (
                            self.next_attempt_after.isoformat()
                            if self.next_attempt_after is not None
                            else None
                        )
                    )
                ),
                "attemptCount": (
                    self.attempt_count if attempt_count is None else attempt_count
                ),
                "busySkipCount": (
                    self.busy_skip_count
                    if busy_skip_count is None
                    else busy_skip_count
                ),
                "lastBusySkipAt": (
                    last_busy_skip_at.isoformat()
                    if last_busy_skip_at is not None
                    else (
                        self.last_busy_skip_at.isoformat()
                        if self.last_busy_skip_at is not None
                        else None
                    )
                ),
                "busyRetryDelaySeconds": (
                    None
                    if clear_busy_retry_delay
                    else (
                        busy_retry_delay_seconds
                        if busy_retry_delay_seconds is not None
                        else self.busy_retry_delay_seconds
                    )
                ),
                "providerRuntimeStateSupported": (
                    self.provider_runtime_state_supported
                    if provider_runtime_state_supported is None
                    else provider_runtime_state_supported
                ),
                "providerRuntimeState": (
                    self.provider_runtime_state
                    if provider_runtime_state is None
                    else provider_runtime_state
                ),
                "providerStateSource": (
                    self.provider_state_source
                    if provider_state_source is None
                    else provider_state_source
                ),
                "providerActivationExecuted": (
                    self.provider_activation_executed
                    if provider_activation_executed is None
                    else provider_activation_executed
                ),
                "providerRuntimeStatusRead": (
                    self.provider_runtime_status_read
                    if provider_runtime_status_read is None
                    else provider_runtime_status_read
                ),
                "updatedAt": updated_at.isoformat(),
                "metadata": {**dict(self.metadata), **dict(metadata or {})},
            }
        )

    def to_metadata(self) -> dict[str, object]:
        status = _enum_value(AgentDispatchStatus, self.status, "status")
        reply_policy = _enum_value(
            AgentDispatchReplyPolicy,
            self.reply_policy,
            "replyPolicy",
        )
        metadata: dict[str, object] = {
            "schema": "agent_dispatch.v1",
            "workspaceId": self.workspace_id,
            "dispatchId": self.dispatch_id,
            "exchangeRequestId": self.exchange_request_id,
            "threadId": self.thread_id,
            "sourceAgentId": self.source_agent_id,
            "targetAgentId": self.target_agent_id,
            "sourceHandleId": self.source_handle_id,
            "targetHandleId": self.target_handle_id,
            "targetProvider": self.target_provider,
            "status": status.value,
            "replyPolicy": reply_policy.value,
            "leaseId": self.lease_id,
            "leaseExpiresAt": (
                self.lease_expires_at.isoformat()
                if self.lease_expires_at is not None
                else None
            ),
            "nextAttemptAfter": (
                self.next_attempt_after.isoformat()
                if self.next_attempt_after is not None
                else None
            ),
            "attemptCount": self.attempt_count,
            "busySkipCount": self.busy_skip_count,
            "lastBusySkipAt": (
                self.last_busy_skip_at.isoformat()
                if self.last_busy_skip_at is not None
                else None
            ),
            "busyRetryDelaySeconds": self.busy_retry_delay_seconds,
            "busyBackoffActive": (
                self.next_attempt_after is not None
                and self.busy_retry_delay_seconds is not None
            ),
            "dispatcherRequired": self.dispatcher_required,
            "providerRuntimeStateSupported": self.provider_runtime_state_supported,
            "providerRuntimeState": self.provider_runtime_state,
            "providerStateSource": self.provider_state_source,
            "providerActivationExecuted": self.provider_activation_executed,
            "providerRuntimeStatusRead": self.provider_runtime_status_read,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
            "metadata": dict(self.metadata),
            "activationAutomationBoundary": {
                "schema": "agent_dispatch_boundary.v1",
                "platformQueueOnly": not self.provider_activation_executed,
                "providerActivationExecuted": self.provider_activation_executed,
                "providerRuntimeStatusRead": self.provider_runtime_status_read,
                "desktopOrTuiInputInjected": False,
            },
        }
        if self.source_event_sequence is not None:
            metadata["sourceEventSequence"] = self.source_event_sequence
        return metadata


@dataclass(frozen=True, slots=True)
class AgentDispatchLeaseRecord:
    """Append-only active/released lease for one target handle or agent."""

    workspace_id: str
    lease_id: str
    dispatch_id: str
    exchange_request_id: str
    target_agent_id: str
    state: AgentDispatchLeaseState | str = AgentDispatchLeaseState.ACTIVE
    target_handle_id: str | None = None
    acquired_by: str | None = None
    expires_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, object] = field(default_factory=dict)
    source_event_sequence: int | None = None

    @classmethod
    def from_mapping(cls, source: Mapping[str, object]) -> "AgentDispatchLeaseRecord":
        config = dict(source)
        _reject_sensitive_config(config, "agentDispatchLease")
        return cls(
            workspace_id=_required_text(config, "workspace_id", "workspaceId"),
            lease_id=(
                _optional_text(config, "lease_id", "leaseId")
                or f"agent-dispatch-lease-{uuid4()}"
            ),
            dispatch_id=_required_text(config, "dispatch_id", "dispatchId"),
            exchange_request_id=_required_text(
                config,
                "exchange_request_id",
                "exchangeRequestId",
            ),
            target_agent_id=_required_text(
                config,
                "target_agent_id",
                "targetAgentId",
            ),
            state=_enum_value(
                AgentDispatchLeaseState,
                _optional_text(config, "state")
                or AgentDispatchLeaseState.ACTIVE.value,
                "state",
            ),
            target_handle_id=_optional_text(
                config,
                "target_handle_id",
                "targetHandleId",
            ),
            acquired_by=_optional_text(config, "acquired_by", "acquiredBy"),
            expires_at=_optional_datetime(config, "expires_at", "expiresAt"),
            created_at=(
                _optional_datetime(config, "created_at", "createdAt")
                or datetime.now(timezone.utc)
            ),
            updated_at=(
                _optional_datetime(config, "updated_at", "updatedAt")
                or datetime.now(timezone.utc)
            ),
            metadata=_metadata(config.get("metadata")),
            source_event_sequence=_optional_int(
                config,
                "source_event_sequence",
                "sourceEventSequence",
            ),
        )

    def to_metadata(self) -> dict[str, object]:
        state = _enum_value(AgentDispatchLeaseState, self.state, "state")
        metadata: dict[str, object] = {
            "schema": "agent_dispatch_lease.v1",
            "workspaceId": self.workspace_id,
            "leaseId": self.lease_id,
            "dispatchId": self.dispatch_id,
            "exchangeRequestId": self.exchange_request_id,
            "targetAgentId": self.target_agent_id,
            "targetHandleId": self.target_handle_id,
            "state": state.value,
            "acquiredBy": self.acquired_by,
            "expiresAt": (
                self.expires_at.isoformat() if self.expires_at is not None else None
            ),
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
            "metadata": dict(self.metadata),
        }
        if self.source_event_sequence is not None:
            metadata["sourceEventSequence"] = self.source_event_sequence
        return metadata


def _required_text(config: Mapping[str, object], *keys: str) -> str:
    value = _optional_text(config, *keys)
    logical_name = keys[-1] if keys else "value"
    if value is None:
        raise ValueError(f"{logical_name} is required.")
    return value


def _optional_text(config: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        value = config.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string.")
        if not value.strip():
            return None
        if "\x00" in value:
            raise ValueError(f"{key} must not contain null bytes.")
        return value.strip()
    return None


def _optional_int(config: Mapping[str, object], *keys: str) -> int | None:
    for key in keys:
        value = config.get(key)
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{key} must be an integer.")
        return value
    return None


def _optional_bool(
    config: Mapping[str, object],
    *keys: str,
    default: bool | None = None,
) -> bool | None:
    for key in keys:
        value = config.get(key)
        if value is None:
            continue
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be a boolean.")
        return value
    return default


def _optional_datetime(config: Mapping[str, object], *keys: str) -> datetime | None:
    for key in keys:
        value = config.get(key)
        if value is None:
            continue
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str):
            raise ValueError(f"{key} must be an ISO datetime string.")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{key} must be an ISO datetime string.") from exc
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _enum_value(enum_cls: type[StrEnum], value: StrEnum | str, field_name: str):
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(str(value))
    except ValueError as exc:
        valid = ", ".join(item.value for item in enum_cls)
        raise ValueError(f"{field_name} must be one of: {valid}.") from exc


def _metadata(value: object) -> Mapping[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("metadata must be a JSON object.")
    _reject_sensitive_config(value, "metadata")
    return dict(value)


def _reject_sensitive_config(config: Mapping[str, object], logical_name: str) -> None:
    sensitive_fragments = (
        "api_key",
        "apikey",
        "authorization",
        "bearer",
        "cookie",
        "credential",
        "password",
        "secret",
        "token",
    )
    for key, value in config.items():
        lowered = str(key).lower()
        if any(fragment in lowered for fragment in sensitive_fragments):
            raise ValueError(f"{logical_name} must not contain credential values.")
        if isinstance(value, Mapping):
            _reject_sensitive_config(value, f"{logical_name}.{key}")
