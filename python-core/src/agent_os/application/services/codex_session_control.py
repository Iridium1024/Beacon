from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import os
from typing import Mapping, Sequence
from uuid import uuid4


_IS_WINDOWS = os.name == "nt"


class CodexStatusReadMode(StrEnum):
    BEACON_SNAPSHOT = "beacon_snapshot"
    APP_SERVER_POINT_READ = "app_server_point_read"


class CodexSupplementMode(StrEnum):
    TURN_STEER = "turn_steer"
    DISABLED = "disabled"


class CodexBusyDeliveryPolicy(StrEnum):
    QUEUE_NEXT_TURN = "queue_next_turn"
    REJECT = "reject"


class CodexReplyWritebackMode(StrEnum):
    EXPLICIT_ONLY = "explicit_only"
    PROVIDER_FINAL_CAPTURE = "provider_final_capture"


class CodexRuntimeState(StrEnum):
    STARTING = "starting"
    IDLE = "idle"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CLOSED = "closed"


class CodexSupplementStatus(StrEnum):
    QUEUED = "queued"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    STALE_TURN = "stale_turn"
    NO_ACTIVE_TURN = "no_active_turn"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    RUNTIME_NOT_OWNED = "runtime_not_owned"
    SUPPLEMENT_DISABLED = "supplement_disabled"
    DELIVERY_UNKNOWN = "delivery_unknown"


_TERMINAL_RUNTIME_STATES = {
    CodexRuntimeState.COMPLETED,
    CodexRuntimeState.FAILED,
    CodexRuntimeState.INTERRUPTED,
    CodexRuntimeState.CLOSED,
}

_TERMINAL_SUPPLEMENT_STATES = {
    CodexSupplementStatus.ACCEPTED,
    CodexSupplementStatus.REJECTED,
    CodexSupplementStatus.STALE_TURN,
    CodexSupplementStatus.NO_ACTIVE_TURN,
    CodexSupplementStatus.RUNTIME_UNAVAILABLE,
    CodexSupplementStatus.RUNTIME_NOT_OWNED,
    CodexSupplementStatus.SUPPLEMENT_DISABLED,
    CodexSupplementStatus.DELIVERY_UNKNOWN,
}


@dataclass(frozen=True, slots=True)
class CodexControlSelection:
    value: str
    source: str
    legacy_alias: str | None = None

    def to_metadata(self) -> Mapping[str, object]:
        result: dict[str, object] = {
            "value": self.value,
            "source": self.source,
        }
        if self.legacy_alias is not None:
            result["legacyAlias"] = self.legacy_alias
        return result


@dataclass(frozen=True, slots=True)
class CodexControlConfig:
    activation_backend: CodexControlSelection
    status_read_mode: CodexControlSelection
    supplement_mode: CodexControlSelection
    busy_delivery_policy: CodexControlSelection
    reply_writeback_mode: CodexControlSelection

    def to_metadata(self) -> Mapping[str, object]:
        return {
            "schema": "codex_control_config.v1",
            "activationBackend": self.activation_backend.to_metadata(),
            "statusReadMode": self.status_read_mode.to_metadata(),
            "supplementMode": self.supplement_mode.to_metadata(),
            "busyDeliveryPolicy": self.busy_delivery_policy.to_metadata(),
            "replyWritebackMode": self.reply_writeback_mode.to_metadata(),
            "precedence": [
                "explicit_cli",
                "localRuntime.codexControl",
                "profile (legacy flat alias reported separately)",
                "default",
            ],
        }


def resolve_codex_control_config(
    profile: Mapping[str, object],
    *,
    activation_backend: object | None = None,
    status_read_mode: object | None = None,
    supplement_mode: object | None = None,
    busy_delivery_policy: object | None = None,
    reply_writeback_mode: object | None = None,
) -> CodexControlConfig:
    nested = profile.get("codexControl")
    if nested is None:
        nested_mapping: Mapping[str, object] = {}
    elif isinstance(nested, Mapping):
        nested_mapping = nested
    else:
        raise ValueError("localRuntime.codexControl must be a JSON object.")

    return CodexControlConfig(
        activation_backend=_resolve_selection(
            explicit=activation_backend,
            nested=nested_mapping,
            nested_keys=("activationBackend", "activation_backend"),
            profile=profile,
            legacy_keys=("codexActivationBackend", "codex_activation_backend"),
            allowed=("exec_resume", "app_server"),
            default="exec_resume",
            field_name="activationBackend",
        ),
        status_read_mode=_resolve_selection(
            explicit=status_read_mode,
            nested=nested_mapping,
            nested_keys=("statusReadMode", "status_read_mode"),
            profile=profile,
            legacy_keys=("codexStatusReadMode", "codex_status_read_mode"),
            allowed=tuple(item.value for item in CodexStatusReadMode),
            default=CodexStatusReadMode.BEACON_SNAPSHOT.value,
            field_name="statusReadMode",
        ),
        supplement_mode=_resolve_selection(
            explicit=supplement_mode,
            nested=nested_mapping,
            nested_keys=("supplementMode", "supplement_mode"),
            profile=profile,
            legacy_keys=("codexSupplementMode", "codex_supplement_mode"),
            allowed=tuple(item.value for item in CodexSupplementMode),
            default=CodexSupplementMode.TURN_STEER.value,
            field_name="supplementMode",
        ),
        busy_delivery_policy=_resolve_selection(
            explicit=busy_delivery_policy,
            nested=nested_mapping,
            nested_keys=("busyDeliveryPolicy", "busy_delivery_policy"),
            profile=profile,
            legacy_keys=(
                "codexBusyDeliveryPolicy",
                "codex_busy_delivery_policy",
            ),
            allowed=tuple(item.value for item in CodexBusyDeliveryPolicy),
            default=CodexBusyDeliveryPolicy.QUEUE_NEXT_TURN.value,
            field_name="busyDeliveryPolicy",
        ),
        reply_writeback_mode=_resolve_selection(
            explicit=reply_writeback_mode,
            nested=nested_mapping,
            nested_keys=("replyWritebackMode", "reply_writeback_mode"),
            profile=profile,
            legacy_keys=(
                "codexReplyWritebackMode",
                "codex_reply_writeback_mode",
            ),
            allowed=tuple(item.value for item in CodexReplyWritebackMode),
            default=CodexReplyWritebackMode.EXPLICIT_ONLY.value,
            field_name="replyWritebackMode",
        ),
    )


def _resolve_selection(
    *,
    explicit: object | None,
    nested: Mapping[str, object],
    nested_keys: Sequence[str],
    profile: Mapping[str, object],
    legacy_keys: Sequence[str],
    allowed: Sequence[str],
    default: str,
    field_name: str,
) -> CodexControlSelection:
    if explicit is not None:
        return CodexControlSelection(
            value=_validated_choice(explicit, allowed, field_name),
            source="explicit_cli",
        )
    for key in nested_keys:
        if nested.get(key) is not None:
            return CodexControlSelection(
                value=_validated_choice(nested[key], allowed, field_name),
                source="localRuntime.codexControl",
            )
    for key in legacy_keys:
        if profile.get(key) is not None:
            return CodexControlSelection(
                value=_validated_choice(profile[key], allowed, field_name),
                source="profile",
                legacy_alias=key,
            )
    return CodexControlSelection(value=default, source="default")


def _validated_choice(value: object, allowed: Sequence[str], field_name: str) -> str:
    if not isinstance(value, str) or value.strip() not in allowed:
        raise ValueError(
            f"{field_name} must be one of: {', '.join(allowed)}."
        )
    return value.strip()


def process_is_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if _IS_WINDOWS:
        return _windows_process_is_alive(pid)
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError, PermissionError):
        return False
    return True


def _windows_process_is_alive(pid: int) -> bool:
    """Query a Windows process without sending it a signal.

    ``os.kill(pid, 0)`` is a POSIX liveness probe, but on Windows non-console
    signals are implemented with ``TerminateProcess``. A status read must never
    mutate the process it observes, especially when a historical PID may have
    been reused by an unrelated process.
    """

    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    synchronize = 0x00100000
    wait_timeout = 0x00000102

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    )
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(
        process_query_limited_information | synchronize,
        False,
        pid,
    )
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
    finally:
        kernel32.CloseHandle(handle)


@dataclass(frozen=True, slots=True)
class CodexAppServerRuntimeRecord:
    runtime_id: str
    activation_attempt_id: str
    workspace_id: str
    agent_id: str
    handle_id: str
    native_thread_id: str
    native_session_id: str | None
    native_turn_id: str | None
    owner_pid: int
    transport: str
    beacon_version: str
    state: CodexRuntimeState | str
    started_at: str
    updated_at: str
    ended_at: str | None = None
    owner_connection_alive: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", CodexRuntimeState(self.state))

    @property
    def can_steer(self) -> bool:
        return (
            self.state is CodexRuntimeState.ACTIVE
            and self.native_turn_id is not None
            and self.owner_connection_alive
            and process_is_alive(self.owner_pid)
        )

    @property
    def terminal(self) -> bool:
        return self.state in _TERMINAL_RUNTIME_STATES

    def to_metadata(self) -> Mapping[str, object]:
        owner_process_alive = bool(
            self.owner_connection_alive
            and not self.terminal
            and process_is_alive(self.owner_pid)
        )
        result: dict[str, object] = {
            "schema": "codex_app_server_runtime.v1",
            "runtimeId": self.runtime_id,
            "activationAttemptId": self.activation_attempt_id,
            "workspaceId": self.workspace_id,
            "agentId": self.agent_id,
            "handleId": self.handle_id,
            "nativeThreadId": self.native_thread_id,
            "ownerPid": self.owner_pid,
            "transport": self.transport,
            "runtimeOwner": "beacon",
            "beaconVersion": self.beacon_version,
            "state": self.state.value,
            "canSteer": (
                self.state is CodexRuntimeState.ACTIVE
                and self.native_turn_id is not None
                and owner_process_alive
            ),
            "ownerConnectionAlive": self.owner_connection_alive,
            "ownerProcessAlive": owner_process_alive,
            "runtimeAlive": owner_process_alive,
            "startedAt": self.started_at,
            "updatedAt": self.updated_at,
            "lastObservedAt": self.updated_at,
            "terminal": self.terminal,
            "metadata": dict(self.metadata),
        }
        if self.native_session_id is not None:
            result["nativeSessionId"] = self.native_session_id
        if self.native_turn_id is not None:
            result["nativeTurnId"] = self.native_turn_id
        if self.ended_at is not None:
            result["endedAt"] = self.ended_at
            result["closedAt"] = self.ended_at
        return result

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> CodexAppServerRuntimeRecord:
        return cls(
            runtime_id=str(value["runtimeId"]),
            activation_attempt_id=str(value["activationAttemptId"]),
            workspace_id=str(value["workspaceId"]),
            agent_id=str(value["agentId"]),
            handle_id=str(value["handleId"]),
            native_thread_id=str(value["nativeThreadId"]),
            native_session_id=_optional_text(value.get("nativeSessionId")),
            native_turn_id=_optional_text(value.get("nativeTurnId")),
            owner_pid=int(value["ownerPid"]),
            transport=str(value.get("transport", "stdio")),
            beacon_version=str(value.get("beaconVersion", "unknown")),
            state=str(value["state"]),
            started_at=str(value["startedAt"]),
            updated_at=str(value["updatedAt"]),
            ended_at=_optional_text(value.get("endedAt")),
            owner_connection_alive=bool(value.get("ownerConnectionAlive", False)),
            metadata=(
                value.get("metadata", {})
                if isinstance(value.get("metadata"), Mapping)
                else {}
            ),
        )


@dataclass(frozen=True, slots=True)
class CodexSessionSupplementRecord:
    supplement_id: str
    workspace_id: str
    agent_id: str
    handle_id: str
    native_thread_id: str
    expected_turn_id: str
    submitted_by: str
    message_hash: str
    status: CodexSupplementStatus | str
    created_at: str
    updated_at: str
    runtime_id: str | None = None
    activation_attempt_id: str | None = None
    actual_turn_id: str | None = None
    requires_user_review: bool = False
    reason: str | None = None
    guidance: str | None = None
    failure_category: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", CodexSupplementStatus(self.status))

    @property
    def terminal(self) -> bool:
        return self.status in _TERMINAL_SUPPLEMENT_STATES

    def to_metadata(self) -> Mapping[str, object]:
        result: dict[str, object] = {
            "schema": "codex_session_supplement.v1",
            "supplementId": self.supplement_id,
            "workspaceId": self.workspace_id,
            "agentId": self.agent_id,
            "handleId": self.handle_id,
            "nativeThreadId": self.native_thread_id,
            "expectedTurnId": self.expected_turn_id,
            "submittedBy": self.submitted_by,
            "messageHash": self.message_hash,
            "status": self.status.value,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "requiresUserReview": self.requires_user_review,
            "terminal": self.terminal,
            "deliveryType": "supplement_active_turn",
        }
        for key, value in (
            ("runtimeId", self.runtime_id),
            ("activationAttemptId", self.activation_attempt_id),
            ("actualTurnId", self.actual_turn_id),
            ("reason", self.reason),
            ("guidance", self.guidance),
        ):
            if value is not None:
                result[key] = value
        if self.status is CodexSupplementStatus.ACCEPTED:
            result["acceptedAt"] = self.updated_at
            if self.actual_turn_id is not None:
                result["acceptedTurnId"] = self.actual_turn_id
        elif self.terminal:
            result["rejectedAt"] = self.updated_at
        if self.status not in {
            CodexSupplementStatus.QUEUED,
            CodexSupplementStatus.ACCEPTED,
        }:
            result["failureCategory"] = self.failure_category or self.status.value
            if self.reason is not None:
                result["failureReason"] = self.reason
        return result

    @classmethod
    def create(
        cls,
        *,
        workspace_id: str,
        agent_id: str,
        handle_id: str,
        native_thread_id: str,
        expected_turn_id: str,
        submitted_by: str,
        message: str,
        status: CodexSupplementStatus | str,
        supplement_id: str | None = None,
        runtime_id: str | None = None,
        activation_attempt_id: str | None = None,
        reason: str | None = None,
        guidance: str | None = None,
        failure_category: str | None = None,
        now: datetime | None = None,
    ) -> CodexSessionSupplementRecord:
        timestamp = (now or datetime.now(timezone.utc)).isoformat()
        return cls(
            supplement_id=supplement_id or f"codex-supplement-{uuid4()}",
            workspace_id=workspace_id,
            agent_id=agent_id,
            handle_id=handle_id,
            native_thread_id=native_thread_id,
            expected_turn_id=expected_turn_id,
            submitted_by=submitted_by,
            message_hash=hashlib.sha256(message.encode("utf-8")).hexdigest(),
            status=status,
            created_at=timestamp,
            updated_at=timestamp,
            runtime_id=runtime_id,
            activation_attempt_id=activation_attempt_id,
            reason=reason,
            guidance=guidance,
            failure_category=failure_category,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> CodexSessionSupplementRecord:
        return cls(
            supplement_id=str(value["supplementId"]),
            workspace_id=str(value["workspaceId"]),
            agent_id=str(value["agentId"]),
            handle_id=str(value["handleId"]),
            native_thread_id=str(value["nativeThreadId"]),
            expected_turn_id=str(value["expectedTurnId"]),
            submitted_by=str(value["submittedBy"]),
            message_hash=str(value["messageHash"]),
            status=str(value["status"]),
            created_at=str(value["createdAt"]),
            updated_at=str(value["updatedAt"]),
            runtime_id=_optional_text(value.get("runtimeId")),
            activation_attempt_id=_optional_text(value.get("activationAttemptId")),
            actual_turn_id=_optional_text(value.get("actualTurnId")),
            requires_user_review=bool(value.get("requiresUserReview", False)),
            reason=_optional_text(value.get("reason")),
            guidance=_optional_text(value.get("guidance")),
            failure_category=_optional_text(value.get("failureCategory")),
        )


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
