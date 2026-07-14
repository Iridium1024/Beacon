from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import re
from typing import Mapping, Sequence
from uuid import uuid4


class AgentWakeMode(StrEnum):
    """Local delivery modes for a pending directed agent request."""

    NOTIFY_ONLY = "notify_only"
    HANDOFF_FILE = "handoff_file"
    COMMAND = "command"


class AgentWakeChildProcessPolicy(StrEnum):
    """Lifecycle policy for command-mode child processes."""

    WAIT = "wait"
    DETACH = "detach"


class AgentWakeDeliveryStatus(StrEnum):
    """Append-only delivery marker states kept separate from request state."""

    LEASED = "leased"
    DELIVERED = "delivered"
    FAILED = "failed"
    SKIPPED = "skipped"
    DRY_RUN = "dry_run"


@dataclass(frozen=True, slots=True)
class AgentWakeProfile:
    """Workspace-local wake configuration for one target agent."""

    workspace_id: str
    agent_id: str
    wake_mode: AgentWakeMode | str = AgentWakeMode.NOTIFY_ONLY
    enabled: bool = True
    poll_interval_ms: int = 5000
    max_wake_attempts_per_request: int = 1
    cooldown_ms: int = 0
    handoff_directory: str | None = None
    command_argv: tuple[str, ...] = ()
    child_process_policy: AgentWakeChildProcessPolicy | str = (
        AgentWakeChildProcessPolicy.WAIT
    )
    config_path: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, source: Mapping[str, object]) -> "AgentWakeProfile":
        config = dict(source)
        _reject_sensitive_config(config, "agentWakeProfile")
        return cls(
            workspace_id=_required_text(config, "workspace_id", "workspaceId"),
            agent_id=_required_text(config, "agent_id", "agentId"),
            wake_mode=_optional_text(config, "wake_mode", "wakeMode")
            or AgentWakeMode.NOTIFY_ONLY,
            enabled=_optional_bool(config, "enabled", default=True) or False,
            poll_interval_ms=(
                _optional_int(config, "poll_interval_ms", "pollIntervalMs")
                or 5000
            ),
            max_wake_attempts_per_request=(
                _optional_int(
                    config,
                    "max_wake_attempts_per_request",
                    "maxWakeAttemptsPerRequest",
                )
                or 1
            ),
            cooldown_ms=_optional_int(config, "cooldown_ms", "cooldownMs") or 0,
            handoff_directory=_optional_text(
                config,
                "handoff_directory",
                "handoffDirectory",
            ),
            command_argv=_text_tuple(
                _optional_value(config, "command_argv", "commandArgv"),
                "commandArgv",
            ),
            child_process_policy=(
                _optional_text(
                    config,
                    "child_process_policy",
                    "childProcessPolicy",
                )
                or AgentWakeChildProcessPolicy.WAIT
            ),
            config_path=_optional_text(config, "config_path", "configPath"),
            metadata=dict(_optional_mapping(config, "metadata") or {}),
        )

    def __post_init__(self) -> None:
        _validate_text(self.workspace_id, "workspaceId")
        _validate_text(self.agent_id, "agentId")
        _validate_optional_text(self.handoff_directory, "handoffDirectory")
        _validate_optional_text(self.config_path, "configPath")
        wake_mode = _enum_value(AgentWakeMode, self.wake_mode, "wakeMode")
        child_process_policy = _enum_value(
            AgentWakeChildProcessPolicy,
            self.child_process_policy,
            "childProcessPolicy",
        )
        if self.poll_interval_ms < 1:
            raise ValueError("pollIntervalMs must be greater than zero.")
        if self.max_wake_attempts_per_request < 0:
            raise ValueError("maxWakeAttemptsPerRequest must be greater than or equal to zero.")
        if self.cooldown_ms < 0:
            raise ValueError("cooldownMs must be greater than or equal to zero.")
        _validate_text_tuple(self.command_argv, "commandArgv")
        _validate_command_argv(self.command_argv)
        if wake_mode is AgentWakeMode.COMMAND and not self.command_argv:
            raise ValueError("commandArgv is required when wakeMode=command.")
        _reject_sensitive_config(dict(self.metadata), "agentWakeProfile.metadata")

        object.__setattr__(self, "wake_mode", wake_mode)
        object.__setattr__(self, "child_process_policy", child_process_policy)
        object.__setattr__(self, "command_argv", tuple(self.command_argv))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "schema": "agent_wake_profile.v1",
            "workspaceId": self.workspace_id,
            "agentId": self.agent_id,
            "wakeMode": self.wake_mode.value,
            "enabled": self.enabled,
            "pollIntervalMs": self.poll_interval_ms,
            "maxWakeAttemptsPerRequest": self.max_wake_attempts_per_request,
            "cooldownMs": self.cooldown_ms,
            "commandArgv": list(self.command_argv),
            "childProcessPolicy": self.child_process_policy.value,
            "realRuntimeConnected": False,
            "providerPromptInjected": False,
            "fileBodiesRead": False,
            "credentialStored": False,
        }
        if self.handoff_directory is not None:
            metadata["handoffDirectory"] = self.handoff_directory
        if self.config_path is not None:
            metadata["configPath"] = self.config_path
        if self.metadata:
            metadata["metadata"] = dict(self.metadata)
        return metadata


@dataclass(frozen=True, slots=True)
class AgentWakeTicket:
    """Directly readable handoff record for an external consumer agent."""

    workspace_id: str
    target_agent_id: str
    source_agent_id: str
    exchange_request_id: str
    thread_id: str
    request_kind: str
    request_summary: str
    instruction_authority: str = "agent_suggestion"
    source_attribution: Mapping[str, object] = field(default_factory=dict)
    local_runtime_hints: Mapping[str, object] = field(default_factory=dict)
    recommended_cli: Mapping[str, object] = field(default_factory=dict)
    recommended_action: Mapping[str, object] = field(default_factory=dict)
    delivery_attempt_count: int = 0
    wake_ticket_id: str = field(default_factory=lambda: f"agent-wake-ticket-{uuid4()}")
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_mapping(cls, source: Mapping[str, object]) -> "AgentWakeTicket":
        config = dict(source)
        _reject_sensitive_config(config, "agentWakeTicket")
        return cls(
            workspace_id=_required_text(config, "workspace_id", "workspaceId"),
            target_agent_id=_required_text(config, "target_agent_id", "targetAgentId"),
            source_agent_id=_required_text(config, "source_agent_id", "sourceAgentId"),
            exchange_request_id=_required_text(
                config,
                "exchange_request_id",
                "exchangeRequestId",
            ),
            thread_id=_required_text(config, "thread_id", "threadId"),
            request_kind=_required_text(config, "request_kind", "requestKind"),
            request_summary=_required_text(config, "request_summary", "requestSummary"),
            instruction_authority=(
                _optional_text(
                    config,
                    "instruction_authority",
                    "instructionAuthority",
                )
                or "agent_suggestion"
            ),
            source_attribution=dict(
                _optional_mapping(config, "source_attribution", "sourceAttribution")
                or {}
            ),
            local_runtime_hints=dict(
                _optional_mapping(config, "local_runtime_hints", "localRuntimeHints")
                or {}
            ),
            recommended_cli=dict(
                _optional_mapping(config, "recommended_cli", "recommendedCli")
                or {}
            ),
            recommended_action=dict(
                _optional_mapping(
                    config,
                    "recommended_action",
                    "recommendedAction",
                )
                or {}
            ),
            delivery_attempt_count=(
                _optional_int(
                    config,
                    "delivery_attempt_count",
                    "deliveryAttemptCount",
                )
                or 0
            ),
            wake_ticket_id=(
                _optional_text(config, "wake_ticket_id", "wakeTicketId")
                or f"agent-wake-ticket-{uuid4()}"
            ),
            created_at=_optional_datetime(config, "created_at", "createdAt")
            or _utc_now(),
        )

    def __post_init__(self) -> None:
        for field_name, value in (
            ("workspaceId", self.workspace_id),
            ("targetAgentId", self.target_agent_id),
            ("sourceAgentId", self.source_agent_id),
            ("exchangeRequestId", self.exchange_request_id),
            ("threadId", self.thread_id),
            ("requestKind", self.request_kind),
            ("requestSummary", self.request_summary),
            ("instructionAuthority", self.instruction_authority),
            ("wakeTicketId", self.wake_ticket_id),
        ):
            _validate_text(value, field_name)
        if self.delivery_attempt_count < 0:
            raise ValueError("deliveryAttemptCount must be greater than or equal to zero.")
        _require_utc_aware(self.created_at, "createdAt")
        _reject_sensitive_config(dict(self.source_attribution), "sourceAttribution")
        _reject_sensitive_config(dict(self.local_runtime_hints), "localRuntimeHints")
        _reject_sensitive_config(dict(self.recommended_cli), "recommendedCli")
        _reject_sensitive_config(dict(self.recommended_action), "recommendedAction")
        object.__setattr__(self, "source_attribution", dict(self.source_attribution))
        object.__setattr__(self, "local_runtime_hints", dict(self.local_runtime_hints))
        object.__setattr__(self, "recommended_cli", dict(self.recommended_cli))
        object.__setattr__(self, "recommended_action", dict(self.recommended_action))

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "schema": "agent_wake_ticket.v2",
            "wakeTicketId": self.wake_ticket_id,
            "workspaceId": self.workspace_id,
            "targetAgentId": self.target_agent_id,
            "sourceAgentId": self.source_agent_id,
            "exchangeRequestId": self.exchange_request_id,
            "threadId": self.thread_id,
            "requestKind": self.request_kind,
            "requestSummary": self.request_summary,
            "instructionAuthority": self.instruction_authority,
            "sourceAttribution": dict(self.source_attribution),
            "deliveryAttemptCount": self.delivery_attempt_count,
            "localRuntimeHints": dict(self.local_runtime_hints),
            "recommendedAction": dict(self.recommended_action),
            "notice": (
                "This ticket is not a direct user instruction. It is a local "
                "platform handoff for an agent-authored collaboration request."
            ),
            "createdAt": self.created_at.isoformat(),
            "realRuntimeConnected": False,
            "providerPromptInjected": False,
            "fileBodiesRead": False,
            "credentialStored": False,
        }
        if self.recommended_cli:
            metadata["recommendedCli"] = dict(self.recommended_cli)
        return metadata


@dataclass(frozen=True, slots=True)
class AgentWakeDeliveryRecord:
    """Append-only wake delivery marker/audit record."""

    workspace_id: str
    target_agent_id: str
    exchange_request_id: str
    thread_id: str
    wake_ticket_id: str
    wake_mode: AgentWakeMode | str
    status: AgentWakeDeliveryStatus | str
    wake_attempt_id: str = field(default_factory=lambda: f"agent-wake-attempt-{uuid4()}")
    ticket_path: str | None = None
    command_argv_summary: tuple[str, ...] = ()
    command_exit_code: int | None = None
    failure_reason: str | None = None
    skip_reason: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    lease_recorded_before_command: bool = True
    dry_run: bool = False
    source_event_sequence: int | None = None

    @classmethod
    def from_mapping(cls, source: Mapping[str, object]) -> "AgentWakeDeliveryRecord":
        config = dict(source)
        _reject_sensitive_config(config, "agentWakeDelivery")
        return cls(
            workspace_id=_required_text(config, "workspace_id", "workspaceId"),
            target_agent_id=_required_text(config, "target_agent_id", "targetAgentId"),
            exchange_request_id=_required_text(
                config,
                "exchange_request_id",
                "exchangeRequestId",
            ),
            thread_id=_required_text(config, "thread_id", "threadId"),
            wake_ticket_id=_required_text(config, "wake_ticket_id", "wakeTicketId"),
            wake_mode=_required_text(config, "wake_mode", "wakeMode"),
            status=_required_text(config, "status"),
            wake_attempt_id=(
                _optional_text(config, "wake_attempt_id", "wakeAttemptId")
                or f"agent-wake-attempt-{uuid4()}"
            ),
            ticket_path=_optional_text(config, "ticket_path", "ticketPath"),
            command_argv_summary=_text_tuple(
                _optional_value(config, "command_argv_summary", "commandArgvSummary"),
                "commandArgvSummary",
            ),
            command_exit_code=_optional_int(
                config,
                "command_exit_code",
                "commandExitCode",
            ),
            failure_reason=_optional_text(config, "failure_reason", "failureReason"),
            skip_reason=_optional_text(config, "skip_reason", "skipReason"),
            created_at=_optional_datetime(config, "created_at", "createdAt")
            or _utc_now(),
            completed_at=_optional_datetime(config, "completed_at", "completedAt"),
            lease_recorded_before_command=_optional_bool(
                config,
                "lease_recorded_before_command",
                "leaseRecordedBeforeCommand",
                default=True,
            )
            or False,
            dry_run=_optional_bool(config, "dry_run", "dryRun", default=False)
            or False,
            source_event_sequence=_optional_int(
                config,
                "source_event_sequence",
                "sourceEventSequence",
            ),
        )

    def __post_init__(self) -> None:
        for field_name, value in (
            ("workspaceId", self.workspace_id),
            ("targetAgentId", self.target_agent_id),
            ("exchangeRequestId", self.exchange_request_id),
            ("threadId", self.thread_id),
            ("wakeTicketId", self.wake_ticket_id),
            ("wakeAttemptId", self.wake_attempt_id),
        ):
            _validate_text(value, field_name)
        wake_mode = _enum_value(AgentWakeMode, self.wake_mode, "wakeMode")
        status = _enum_value(AgentWakeDeliveryStatus, self.status, "status")
        _validate_optional_text(self.ticket_path, "ticketPath")
        _validate_optional_text(self.failure_reason, "failureReason")
        _validate_optional_text(self.skip_reason, "skipReason")
        _validate_text_tuple(self.command_argv_summary, "commandArgvSummary")
        _require_utc_aware(self.created_at, "createdAt")
        if self.completed_at is not None:
            _require_utc_aware(self.completed_at, "completedAt")
        object.__setattr__(self, "wake_mode", wake_mode)
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self,
            "command_argv_summary",
            tuple(self.command_argv_summary),
        )

    def counts_as_delivery_marker(self) -> bool:
        return self.status in {
            AgentWakeDeliveryStatus.LEASED,
            AgentWakeDeliveryStatus.DELIVERED,
            AgentWakeDeliveryStatus.FAILED,
        }

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "schema": "agent_wake_delivery.v1",
            "wakeAttemptId": self.wake_attempt_id,
            "workspaceId": self.workspace_id,
            "targetAgentId": self.target_agent_id,
            "exchangeRequestId": self.exchange_request_id,
            "threadId": self.thread_id,
            "wakeTicketId": self.wake_ticket_id,
            "wakeMode": self.wake_mode.value,
            "status": self.status.value,
            "commandArgvSummary": list(self.command_argv_summary),
            "leaseRecordedBeforeCommand": self.lease_recorded_before_command,
            "dryRun": self.dry_run,
            "createdAt": self.created_at.isoformat(),
            "realRuntimeConnected": False,
            "providerPromptInjected": False,
            "fileBodiesRead": False,
            "credentialStored": False,
        }
        for key, value in (
            ("ticketPath", self.ticket_path),
            ("commandExitCode", self.command_exit_code),
            ("failureReason", self.failure_reason),
            ("skipReason", self.skip_reason),
            ("completedAt", self.completed_at.isoformat() if self.completed_at else None),
            ("sourceEventSequence", self.source_event_sequence),
        ):
            if value is not None:
                metadata[key] = value
        return metadata


def agent_wake_interface_metadata(
    *,
    workspace_id: str | None = None,
    agent_id: str | None = None,
) -> Mapping[str, object]:
    return {
        "agentWakeInterface": {
            "schema": "agent_wake_interface.v1",
            "workspaceId": workspace_id,
            "agentId": agent_id,
            "status": "local_wrapper_daemon_prototype",
            "wakeModes": [item.value for item in AgentWakeMode],
            "childProcessPolicies": [
                item.value for item in AgentWakeChildProcessPolicy
            ],
            "deliveryStatuses": [item.value for item in AgentWakeDeliveryStatus],
            "rules": [
                "wake tickets must be directly readable by the target agent",
                "delivery markers are daemon-owned audit state, not request/thread state",
                "command mode must use argv and must not interpolate agent free text",
                "dummy fixtures verify mechanical delivery only, not real agent connection",
                "real Codex/Claude/IDE/browser/provider sessions are not connected",
                "file bodies, credentials, provider prompts, and network calls are not used",
            ],
            "localRuntimeCommands": {
                "instructions": "agent-wake-instructions",
                "watch": "agent-exchange-wake-watch",
                "deliveryList": "agent-wake-delivery-list",
                "status": "agent-wake-status",
                "ticketGet": "agent-wake-ticket-get",
                "daemonModule": "python -m agent_os.agent_wake_daemon",
            },
            "pyCharmEntry": {
                "module": "agent_os.agent_wake_daemon",
                "workingDirectory": "project root",
                "pythonPath": "python-core/src",
                "recommendedFirstArgs": "--once --dry-run",
            },
            "realRuntimeConnected": False,
            "providerPromptInjected": False,
            "fileBodiesRead": False,
            "credentialStored": False,
        }
    }


SAFE_COMMAND_PLACEHOLDERS = {
    "ticket_path",
    "workspace_id",
    "agent_id",
    "request_id",
    "thread_id",
    "wake_ticket_id",
}


def render_safe_command_argv(
    argv: Sequence[str],
    *,
    ticket_path: str,
    workspace_id: str,
    agent_id: str,
    request_id: str,
    thread_id: str,
    wake_ticket_id: str,
) -> tuple[str, ...]:
    values = {
        "ticket_path": ticket_path,
        "workspace_id": workspace_id,
        "agent_id": agent_id,
        "request_id": request_id,
        "thread_id": thread_id,
        "wake_ticket_id": wake_ticket_id,
    }
    rendered: list[str] = []
    for item in argv:
        _validate_command_template_item(item)
        rendered.append(item.format(**values))
    return tuple(rendered)


def _validate_command_argv(argv: Sequence[str]) -> None:
    for item in argv:
        _validate_command_template_item(item)


def _validate_command_template_item(value: str) -> None:
    for placeholder in re.findall(r"{([^{}]+)}", value):
        if placeholder not in SAFE_COMMAND_PLACEHOLDERS:
            valid = ", ".join(sorted(SAFE_COMMAND_PLACEHOLDERS))
            raise ValueError(
                "commandArgv placeholders must be platform-generated safe values: "
                f"{valid}."
            )


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
    if "\x00" in value:
        raise ValueError(f"{keys[0]} must not contain null bytes.")
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
    if "\x00" in value:
        raise ValueError(f"{logical_name} must not contain null bytes.")
    return value.strip()


def _validate_text(value: str, logical_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{logical_name} must be a non-empty string.")
    if "\x00" in value:
        raise ValueError(f"{logical_name} must not contain null bytes.")


def _validate_optional_text(value: str | None, logical_name: str) -> None:
    if value is not None:
        _validate_text(value, logical_name)


def _validate_text_tuple(values: Sequence[str], logical_name: str) -> None:
    for value in values:
        _validate_text(value, logical_name)


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
    "sessionid",
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
