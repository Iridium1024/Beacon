from __future__ import annotations

from collections.abc import Mapping as MappingABC
from datetime import datetime, timezone
from typing import Mapping

from agent_os.application.services.agent_endpoint import (
    normalize_agent_endpoint_provider,
)


CANONICAL_PROVIDER_RUNTIME_STATES = {
    "idle",
    "busy",
    "blocked",
    "unknown",
    "unavailable",
}

PROVIDER_RUNTIME_STATUS_READ_POLICIES = {
    "auto",
    "enabled",
    "disabled",
}


def normalize_provider_runtime_status_read_policy(
    value: bool | str | None,
) -> str:
    if value is None:
        return "auto"
    if isinstance(value, bool):
        return "enabled" if value else "disabled"
    normalized = value.strip().lower().replace("-", "_")
    aliases = {
        "true": "enabled",
        "on": "enabled",
        "false": "disabled",
        "off": "disabled",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in PROVIDER_RUNTIME_STATUS_READ_POLICIES:
        raise ValueError(
            "runtimeStatusPolicy must be one of: auto, enabled, disabled."
        )
    return normalized


def build_agent_provider_runtime_status(
    *,
    provider: str,
    provider_handle_id: str,
    provider_handle: Mapping[str, object] | None,
    endpoint: Mapping[str, object] | None = None,
    active_lease: Mapping[str, object] | None = None,
    live_status_snapshot: Mapping[str, object] | None = None,
    live_status_probe: Mapping[str, object] | None = None,
    checked_at: datetime | None = None,
) -> Mapping[str, object]:
    normalized_provider = normalize_agent_endpoint_provider(provider)
    if normalized_provider is None:
        raise ValueError("provider must be one of: claude, codex, hermes.")
    timestamp = checked_at or datetime.now(timezone.utc)
    handle_found = isinstance(provider_handle, MappingABC)
    handle_state = _optional_text(provider_handle.get("state")) if handle_found else None
    handle_active = handle_state == "active"
    metadata_snapshot = _runtime_status_snapshot(provider_handle) if handle_found else None
    live_status_read = isinstance(live_status_snapshot, MappingABC)
    snapshot_status = (
        _provider_snapshot_status(
            normalized_provider,
            live_status_snapshot,
            read_mode="local_command_probe",
        )
        if live_status_read
        else _provider_snapshot_status(
            normalized_provider,
            metadata_snapshot,
            read_mode="metadata_snapshot",
        )
    )
    platform_dispatch_busy = isinstance(active_lease, MappingABC)
    runtime_status_policy = (
        _optional_text(live_status_probe.get("runtimeStatusPolicy"))
        if isinstance(live_status_probe, MappingABC)
        else None
    ) or "auto"

    if not handle_found:
        runtime_state = "unavailable"
        state_source = "provider_handle_missing"
        reason = "provider handle was not found."
    elif not handle_active:
        runtime_state = "unavailable"
        state_source = "provider_handle_inactive"
        reason = "provider handle is not active."
    elif platform_dispatch_busy:
        runtime_state = "busy"
        state_source = "platform_dispatch_lease"
        reason = "platform dispatch lease is active for this target handle."
    elif snapshot_status["providerRuntimeStatusRead"]:
        runtime_state = str(snapshot_status["providerRuntimeState"])
        state_source = str(snapshot_status["providerRuntimeStateSource"])
        reason = str(snapshot_status["reason"])
    elif _probe_status(live_status_probe) == "not_requested":
        runtime_state = "unknown"
        state_source = "provider_runtime_status_probe_not_requested"
        reason = "provider runtime status probe is configured but live read was not requested."
    elif _probe_status(live_status_probe) == "disabled":
        runtime_state = "unknown"
        state_source = "provider_runtime_status_probe_disabled"
        reason = "provider runtime status probe was disabled by policy."
    elif _probe_was_attempted(live_status_probe):
        runtime_state = "unknown"
        state_source = "provider_runtime_status_probe_failed"
        reason = "provider runtime status probe did not return a readable state."
    else:
        runtime_state = "unknown"
        state_source = "provider_runtime_status_not_configured"
        reason = "no provider runtime status adapter or snapshot is configured."

    return {
        "schema": "agent_provider_runtime_status.v1",
        "provider": normalized_provider,
        "providerHandleId": provider_handle_id,
        "agentId": (
            provider_handle.get("agentId")
            if isinstance(provider_handle, MappingABC)
            else None
        ),
        "endpointId": (
            endpoint.get("endpointId") if isinstance(endpoint, MappingABC) else None
        ),
        "endpointAlias": (
            endpoint.get("alias") if isinstance(endpoint, MappingABC) else None
        ),
        "runtimeState": runtime_state,
        "stateSource": state_source,
        "reason": reason,
        "providerRuntimeState": snapshot_status["providerRuntimeState"],
        "providerRuntimeStateSource": snapshot_status["providerRuntimeStateSource"],
        "providerRuntimeStateSupported": snapshot_status[
            "providerRuntimeStateSupported"
        ],
        "providerRuntimeStatusRead": snapshot_status["providerRuntimeStatusRead"],
        "providerRuntimeStatusReadMode": snapshot_status[
            "providerRuntimeStatusReadMode"
        ],
        "rawProviderRuntimeState": snapshot_status["rawProviderRuntimeState"],
        "providerStatusAdapter": _provider_status_adapter_metadata(
            normalized_provider,
            snapshot_status,
            live_status_probe,
        ),
        "providerRuntimeStatusProbe": dict(live_status_probe or {}),
        "runtimeStatusPolicy": runtime_status_policy,
        "providerHandleFound": handle_found,
        "providerHandleActive": handle_active,
        "platformDispatchBusy": platform_dispatch_busy,
        "activeDispatchLease": dict(active_lease or {}),
        "realRuntimePresenceRead": snapshot_status["providerRuntimeStatusRead"],
        "checkedAt": timestamp.isoformat(),
    }


def _provider_snapshot_status(
    provider: str,
    snapshot: Mapping[str, object] | None,
    *,
    read_mode: str,
) -> Mapping[str, object]:
    if not isinstance(snapshot, MappingABC):
        return {
            "providerRuntimeState": "unknown",
            "providerRuntimeStateSource": "provider_runtime_status_not_configured",
            "providerRuntimeStateSupported": False,
            "providerRuntimeStatusRead": False,
            "providerRuntimeStatusReadMode": "not_configured",
            "rawProviderRuntimeState": None,
            "reason": "no provider runtime status snapshot is configured.",
        }
    raw_state = _snapshot_state_text(provider, snapshot)
    canonical_state = _canonical_runtime_state(raw_state)
    source = (
        _optional_text(snapshot.get("source"))
        or _optional_text(snapshot.get("stateSource"))
        or _optional_text(snapshot.get("providerStateSource"))
        or _default_provider_state_source(provider, read_mode)
    )
    return {
        "providerRuntimeState": canonical_state,
        "providerRuntimeStateSource": source,
        "providerRuntimeStateSupported": True,
        "providerRuntimeStatusRead": True,
        "providerRuntimeStatusReadMode": read_mode,
        "rawProviderRuntimeState": raw_state,
        "reason": (
            "provider runtime status was normalized."
            if raw_state is not None
            else "provider runtime status did not include a state."
        ),
    }


def _runtime_status_snapshot(
    provider_handle: Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    if not isinstance(provider_handle, MappingABC):
        return None
    metadata = provider_handle.get("metadata")
    if not isinstance(metadata, MappingABC):
        return None
    for key in (
        "providerRuntimeStatus",
        "providerRuntimeStatusSnapshot",
        "runtimeStatus",
        "runtimeStatusSnapshot",
    ):
        value = metadata.get(key)
        if isinstance(value, MappingABC):
            return dict(value)
    return None


def _snapshot_state_text(
    provider: str,
    snapshot: Mapping[str, object],
) -> str | None:
    provider_keys = {
        "codex": ("threadStatus", "codexThreadStatus", "appServerThreadStatus"),
        "hermes": ("runStatus", "hermesRunStatus"),
        "claude": ("streamStatus", "sdkSessionStatus", "claudeStreamStatus"),
    }
    for key in (
        "canonicalState",
        "runtimeState",
        "providerRuntimeState",
        "state",
        "status",
        *provider_keys.get(provider, ()),
    ):
        value = _optional_text(snapshot.get(key))
        if value is not None:
            return value
    return None


def _canonical_runtime_state(value: str | None) -> str:
    if value is None:
        return "unknown"
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in CANONICAL_PROVIDER_RUNTIME_STATES:
        return normalized
    if normalized in {
        "queued",
        "running",
        "in_progress",
        "processing",
        "streaming",
        "active",
        "starting",
        "stopping",
        "leased",
    }:
        return "busy"
    if normalized in {
        "blocked",
        "waiting_for_response",
        "waiting_response",
        "waiting_external",
        "waiting_for_external",
        "waiting_for_external_response",
        "waiting_for_agent",
        "waiting_agent",
        "awaiting_external",
        "awaiting_agent",
        "awaiting_approval",
        "approval_required",
    }:
        return "blocked"
    if normalized in {
        "idle",
        "ready",
        "completed",
        "complete",
        "succeeded",
        "success",
        "failed",
        "error",
        "cancelled",
        "canceled",
        "stopped",
        "waiting_for_input",
        "waiting_input",
        "waiting_for_user_input",
        "waiting_user_input",
        "result",
    }:
        return "idle"
    if normalized == "waiting":
        return "unknown"
    if normalized in {
        "unavailable",
        "offline",
        "disconnected",
        "not_found",
        "missing",
        "missing_session",
        "unauthorized",
    }:
        return "unavailable"
    return "unknown"


def _provider_status_adapter_metadata(
    provider: str,
    snapshot_status: Mapping[str, object],
    live_status_probe: Mapping[str, object] | None,
) -> Mapping[str, object]:
    adapter_kind = {
        "codex": "codex_app_server_thread_status",
        "hermes": "hermes_run_status",
        "claude": "claude_sdk_owned_session_status",
    }.get(provider, "provider_runtime_status")
    probe_configured = _probe_was_configured(live_status_probe)
    probe_status = (
        _optional_text(live_status_probe.get("status"))
        if isinstance(live_status_probe, MappingABC)
        else None
    )
    return {
        "schema": "agent_provider_runtime_status_adapter.v1",
        "provider": provider,
        "adapterKind": adapter_kind,
        "directProviderRuntimeReadConfigured": probe_configured,
        "directProviderRuntimeRead": (
            snapshot_status.get("providerRuntimeStatusReadMode")
            == "local_command_probe"
        ),
        "directProviderRuntimeReadStatus": probe_status,
        "metadataSnapshotSupported": True,
        "metadataSnapshotRead": bool(
            snapshot_status.get("providerRuntimeStatusRead")
            and snapshot_status.get("providerRuntimeStatusReadMode")
            == "metadata_snapshot"
        ),
    }


def _default_provider_state_source(provider: str, read_mode: str) -> str:
    if read_mode == "local_command_probe":
        return {
            "codex": "codex_app_server_thread_status_probe",
            "hermes": "hermes_run_status_probe",
            "claude": "claude_sdk_owned_session_status_probe",
        }.get(provider, "provider_runtime_status_probe")
    return {
        "codex": "codex_app_server_thread_status_snapshot",
        "hermes": "hermes_run_status_snapshot",
        "claude": "claude_sdk_owned_session_status_snapshot",
    }.get(provider, "provider_runtime_status_snapshot")


def _probe_was_configured(value: Mapping[str, object] | None) -> bool:
    return isinstance(value, MappingABC) and bool(value.get("configured"))


def _probe_was_attempted(value: Mapping[str, object] | None) -> bool:
    status = _probe_status(value)
    return _probe_was_configured(value) and status not in {
        None,
        "not_requested",
        "not_configured",
    }


def _probe_status(value: Mapping[str, object] | None) -> str | None:
    if not isinstance(value, MappingABC):
        return None
    return _optional_text(value.get("status"))


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
