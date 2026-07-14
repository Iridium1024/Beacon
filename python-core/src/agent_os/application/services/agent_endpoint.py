from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import re
from typing import Mapping, Sequence
from uuid import uuid4

from agent_os.application.services.agent_dispatch import AgentDispatchReplyPolicy


class AgentEndpointDirection(StrEnum):
    """Declared sender/receiver role for a platform-local agent endpoint."""

    SEND_ONLY = "send_only"
    RECEIVE_ONLY = "receive_only"
    SEND_RECEIVE = "send_receive"


class AgentEndpointContactPolicy(StrEnum):
    """Contact policy advertised by an endpoint.

    Enforcement is layered on in later hardening steps; 27.5 records the policy
    so dispatch alias resolution can make conservative choices later.
    """

    OPEN = "open"
    CONTACTS_ONLY = "contacts_only"
    BLOCK_ALL = "block_all"


class AgentEndpointState(StrEnum):
    """Lifecycle state for a provider-neutral endpoint alias."""

    ACTIVE = "active"
    INACTIVE = "inactive"


@dataclass(frozen=True, slots=True)
class AgentEndpointRecord:
    """Provider-neutral address book entry for a local agent session handle."""

    workspace_id: str
    endpoint_id: str
    alias: str
    agent_id: str
    provider: str
    provider_handle_id: str
    direction: AgentEndpointDirection | str = AgentEndpointDirection.SEND_RECEIVE
    default_reply_policy: AgentDispatchReplyPolicy | str = (
        AgentDispatchReplyPolicy.SOURCE_HANDLE_REQUIRED
    )
    contact_policy: AgentEndpointContactPolicy | str = AgentEndpointContactPolicy.OPEN
    state: AgentEndpointState | str = AgentEndpointState.ACTIVE
    created_by: str = "user"
    reason: str = "endpoint login"
    metadata: Mapping[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    deactivated_by: str | None = None
    deactivation_reason: str | None = None
    source_event_sequence: int | None = None

    @classmethod
    def from_mapping(cls, source: Mapping[str, object]) -> "AgentEndpointRecord":
        config = dict(source)
        _reject_sensitive_config(config, "agentEndpoint")
        created_at = _optional_datetime(config, "created_at", "createdAt") or _utc_now()
        return cls(
            workspace_id=_required_text(config, "workspace_id", "workspaceId"),
            endpoint_id=(
                _optional_text(config, "endpoint_id", "endpointId")
                or f"agent-endpoint-{uuid4()}"
            ),
            alias=_required_text(config, "alias"),
            agent_id=_required_text(config, "agent_id", "agentId"),
            provider=_required_text(config, "provider"),
            provider_handle_id=_required_text(
                config,
                "provider_handle_id",
                "providerHandleId",
            ),
            direction=(
                _optional_text(config, "direction")
                or AgentEndpointDirection.SEND_RECEIVE.value
            ),
            default_reply_policy=(
                _optional_text(
                    config,
                    "default_reply_policy",
                    "defaultReplyPolicy",
                )
                or AgentDispatchReplyPolicy.SOURCE_HANDLE_REQUIRED.value
            ),
            contact_policy=(
                _optional_text(config, "contact_policy", "contactPolicy")
                or AgentEndpointContactPolicy.OPEN.value
            ),
            state=_optional_text(config, "state") or AgentEndpointState.ACTIVE.value,
            created_by=_optional_text(config, "created_by", "createdBy") or "user",
            reason=_optional_text(config, "reason") or "endpoint login",
            metadata=_metadata(config.get("metadata")),
            created_at=created_at,
            updated_at=_optional_datetime(config, "updated_at", "updatedAt")
            or created_at,
            deactivated_by=_optional_text(config, "deactivated_by", "deactivatedBy"),
            deactivation_reason=_optional_text(
                config,
                "deactivation_reason",
                "deactivationReason",
            ),
            source_event_sequence=_optional_int(
                config,
                "source_event_sequence",
                "sourceEventSequence",
            ),
        )

    def __post_init__(self) -> None:
        for logical_name, value in (
            ("workspaceId", self.workspace_id),
            ("endpointId", self.endpoint_id),
            ("agentId", self.agent_id),
            ("providerHandleId", self.provider_handle_id),
            ("createdBy", self.created_by),
            ("reason", self.reason),
        ):
            _validate_text(value, logical_name)
        alias = normalize_agent_endpoint_alias(self.alias)
        provider = normalize_agent_endpoint_provider(self.provider)
        if provider is None:
            raise ValueError("provider must be one of: claude, codex, hermes.")
        direction = _enum_value(
            AgentEndpointDirection,
            _normalize_enum_text(str(self.direction)),
            "direction",
        )
        default_reply_policy = _enum_value(
            AgentDispatchReplyPolicy,
            _normalize_enum_text(str(self.default_reply_policy)),
            "defaultReplyPolicy",
        )
        contact_policy = _enum_value(
            AgentEndpointContactPolicy,
            _normalize_enum_text(str(self.contact_policy)),
            "contactPolicy",
        )
        state = _enum_value(
            AgentEndpointState,
            _normalize_enum_text(str(self.state)),
            "state",
        )
        _require_utc_aware(self.created_at, "createdAt")
        _require_utc_aware(self.updated_at, "updatedAt")
        _validate_optional_text(self.deactivated_by, "deactivatedBy")
        _validate_optional_text(self.deactivation_reason, "deactivationReason")
        _reject_sensitive_config(dict(self.metadata), "metadata")
        object.__setattr__(self, "alias", alias)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "default_reply_policy", default_reply_policy)
        object.__setattr__(self, "contact_policy", contact_policy)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "metadata", dict(self.metadata))

    def inactive_copy(
        self,
        *,
        deactivated_by: str,
        reason: str,
        deactivated_at: datetime | None = None,
    ) -> "AgentEndpointRecord":
        timestamp = deactivated_at or _utc_now()
        return AgentEndpointRecord.from_mapping(
            {
                **self.to_metadata(),
                "state": AgentEndpointState.INACTIVE.value,
                "deactivatedBy": deactivated_by,
                "deactivationReason": reason,
                "updatedAt": timestamp.isoformat(),
            }
        )

    def to_metadata(self) -> dict[str, object]:
        metadata: dict[str, object] = {
            "schema": "agent_endpoint.v1",
            "workspaceId": self.workspace_id,
            "endpointId": self.endpoint_id,
            "alias": self.alias,
            "agentId": self.agent_id,
            "provider": self.provider,
            "providerHandleId": self.provider_handle_id,
            "direction": self.direction.value,
            "defaultReplyPolicy": self.default_reply_policy.value,
            "contactPolicy": self.contact_policy.value,
            "state": self.state.value,
            "createdBy": self.created_by,
            "reason": self.reason,
            "metadata": dict(self.metadata),
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
            "credentialStored": False,
            "providerAccountAuthenticated": False,
            "providerSessionHandleBound": True,
            "realRuntimePresenceRead": False,
            "backgroundDaemonAttached": False,
            "browserOrDesktopInputInjected": False,
        }
        for key, value in (
            ("deactivatedBy", self.deactivated_by),
            ("deactivationReason", self.deactivation_reason),
            ("sourceEventSequence", self.source_event_sequence),
        ):
            if value is not None:
                metadata[key] = value
        return metadata


def normalize_agent_endpoint_provider(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip().lower().replace("_", "-")
    if normalized in {"claude", "claude-cli", "claude-code"}:
        return "claude"
    if normalized in {"codex", "codex-cli"}:
        return "codex"
    if normalized in {"hermes", "hermes-cli", "hermes-desktop"}:
        return "hermes"
    return None


def normalize_agent_endpoint_alias(value: str) -> str:
    alias = value.strip().lower()
    if not alias:
        raise ValueError("alias is required.")
    if len(alias) > 128:
        raise ValueError("alias must be at most 128 characters.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", alias):
        raise ValueError(
            "alias must start with a letter or digit and contain only "
            "letters, digits, dots, underscores, or hyphens."
        )
    return alias


def _normalize_enum_text(value: str) -> str:
    return value.strip().lower().replace("-", "_")


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


def _optional_datetime(config: Mapping[str, object], *keys: str) -> datetime | None:
    for key in keys:
        value = config.get(key)
        if value is None:
            continue
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"{key} must be an ISO datetime string.") from exc
        else:
            raise ValueError(f"{key} must be an ISO datetime string.")
        if parsed.tzinfo is None or parsed.utcoffset() is None:
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


def _validate_text(value: str, logical_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{logical_name} is required.")
    if "\x00" in value:
        raise ValueError(f"{logical_name} must not contain null bytes.")


def _validate_optional_text(value: str | None, logical_name: str) -> None:
    if value is not None:
        _validate_text(value, logical_name)


def _require_utc_aware(value: datetime, logical_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{logical_name} must be timezone-aware.")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _reject_sensitive_config(config: Mapping[str, object], logical_name: str) -> None:
    for key, value in config.items():
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
