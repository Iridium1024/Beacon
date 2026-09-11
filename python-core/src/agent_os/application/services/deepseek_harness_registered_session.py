from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Mapping


class DeepSeekHarnessRegisteredSessionHandleState(StrEnum):
    """Lifecycle of one Beacon-managed DSH runtime-generation binding."""

    ACTIVE = "active"
    CONTINUITY_LOST = "continuity_lost"
    INACTIVE = "inactive"


@dataclass(frozen=True, slots=True)
class DeepSeekHarnessRegisteredSessionHandle:
    """One Beacon binding from a persistent DSH session to a runtime generation."""

    workspace_id: str
    agent_id: str
    handle_id: str
    deepseek_harness_session_id: str
    cwd: str
    created_by: str
    reason: str
    provider: str = "deepseek-harness"
    state: DeepSeekHarnessRegisteredSessionHandleState | str = (
        DeepSeekHarnessRegisteredSessionHandleState.ACTIVE
    )
    metadata: Mapping[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    deactivated_by: str | None = None
    deactivation_reason: str | None = None
    source_event_sequence: int | None = None

    @classmethod
    def from_mapping(
        cls,
        source: Mapping[str, object],
    ) -> "DeepSeekHarnessRegisteredSessionHandle":
        config = dict(source)
        _reject_sensitive_config(config, "deepseekHarnessSessionHandle")
        created_at = _optional_datetime(config, "created_at", "createdAt") or _utc_now()
        return cls(
            workspace_id=_required_text(config, "workspace_id", "workspaceId"),
            agent_id=_required_text(config, "agent_id", "agentId"),
            handle_id=_required_text(config, "handle_id", "handleId"),
            deepseek_harness_session_id=_required_text(
                config,
                "deepseek_harness_session_id",
                "deepseekHarnessSessionId",
            ),
            cwd=_required_text(config, "cwd"),
            created_by=_required_text(config, "created_by", "createdBy"),
            reason=_required_text(config, "reason"),
            provider=_optional_text(config, "provider") or "deepseek-harness",
            state=(
                _optional_text(config, "state")
                or DeepSeekHarnessRegisteredSessionHandleState.ACTIVE.value
            ),
            metadata=dict(_optional_mapping(config, "metadata") or {}),
            created_at=created_at,
            updated_at=(
                _optional_datetime(config, "updated_at", "updatedAt") or created_at
            ),
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
            ("agentId", self.agent_id),
            ("handleId", self.handle_id),
            ("deepseekHarnessSessionId", self.deepseek_harness_session_id),
            ("createdBy", self.created_by),
            ("reason", self.reason),
        ):
            _validate_text(value, logical_name)
        cwd = Path(self.cwd).expanduser().resolve()
        if not cwd.is_dir():
            raise ValueError("cwd must be an existing directory.")
        if self.provider != "deepseek-harness":
            raise ValueError("provider must be deepseek-harness.")
        try:
            state = DeepSeekHarnessRegisteredSessionHandleState(str(self.state))
        except ValueError as exc:
            raise ValueError(
                "state must be active, continuity_lost, or inactive."
            ) from exc
        _require_utc_aware(self.created_at, "createdAt")
        _require_utc_aware(self.updated_at, "updatedAt")
        _reject_sensitive_config(dict(self.metadata), "metadata")
        object.__setattr__(self, "cwd", str(cwd))
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "metadata", dict(self.metadata))

    def terminal_copy(
        self,
        *,
        state: DeepSeekHarnessRegisteredSessionHandleState | str,
        changed_by: str,
        reason: str,
        changed_at: datetime | None = None,
    ) -> "DeepSeekHarnessRegisteredSessionHandle":
        timestamp = changed_at or _utc_now()
        return DeepSeekHarnessRegisteredSessionHandle.from_mapping(
            {
                **self.to_metadata(),
                "state": DeepSeekHarnessRegisteredSessionHandleState(state).value,
                "deactivatedBy": changed_by,
                "deactivationReason": reason,
                "updatedAt": timestamp.isoformat(),
            }
        )

    def to_metadata(self) -> Mapping[str, object]:
        runtime_binding = self.metadata.get("runtimeBinding")
        binding = runtime_binding if isinstance(runtime_binding, Mapping) else {}
        existing_session_import = binding.get("sessionStartMode") == "resume"
        result: dict[str, object] = {
            "schema": "deepseek_harness_registered_session_handle.v1",
            "workspaceId": self.workspace_id,
            "agentId": self.agent_id,
            "handleId": self.handle_id,
            "provider": self.provider,
            "deepseekHarnessSessionId": self.deepseek_harness_session_id,
            "cwd": self.cwd,
            "createdBy": self.created_by,
            "reason": self.reason,
            "state": self.state.value,
            "metadata": dict(self.metadata),
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
            "credentialStored": False,
            "existingSessionImport": existing_session_import,
            "coldResume": existing_session_import,
            "canResumeAcrossRuntimeRestart": True,
            "fullSessionHistoryRead": False,
        }
        for key, value in (
            ("deactivatedBy", self.deactivated_by),
            ("deactivationReason", self.deactivation_reason),
            ("sourceEventSequence", self.source_event_sequence),
        ):
            if value is not None:
                result[key] = value
        return result


def _reject_sensitive_config(value: Mapping[str, object], field_name: str) -> None:
    exact_sensitive = {
        "token",
        "credential",
        "credentials",
        "password",
        "secret",
        "api_key",
        "apikey",
        "auth",
        "cookie",
        "prompt",
        "transcript",
        "tool_output",
    }
    for key, item in value.items():
        normalized = str(key).lower().replace("-", "_")
        compact = normalized.replace("_", "")
        path_reference = normalized.endswith("path") or normalized.endswith("_path")
        sensitive_field = (
            normalized in exact_sensitive
            or compact in {"apikey", "tooloutput"}
            or compact.endswith(
                (
                    "token",
                    "credential",
                    "credentials",
                    "password",
                    "secret",
                    "apikey",
                    "cookie",
                    "prompt",
                    "transcript",
                    "tooloutput",
                )
            )
        )
        if sensitive_field and not path_reference:
            raise ValueError(f"{field_name} must not contain sensitive field {key}.")
        if isinstance(item, Mapping):
            _reject_sensitive_config(item, field_name)


def _required_text(config: Mapping[str, object], *keys: str) -> str:
    value = _optional_text(config, *keys)
    if value is None:
        raise ValueError(f"{keys[-1]} is required.")
    return value


def _optional_text(config: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        value = config.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string.")
        stripped = value.strip()
        return stripped or None
    return None


def _optional_mapping(
    config: Mapping[str, object],
    key: str,
) -> Mapping[str, object] | None:
    value = config.get(key)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be an object.")
    return value


def _optional_int(config: Mapping[str, object], *keys: str) -> int | None:
    for key in keys:
        value = config.get(key)
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{key} must be an integer.")
        return value
    return None


def _optional_datetime(
    config: Mapping[str, object],
    *keys: str,
) -> datetime | None:
    value = _optional_text(config, *keys)
    return datetime.fromisoformat(value) if value is not None else None


def _validate_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{field_name} must be non-empty text without null bytes.")


def _require_utc_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
