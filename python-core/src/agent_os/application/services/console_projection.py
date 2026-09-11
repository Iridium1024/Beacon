from __future__ import annotations

from collections.abc import Mapping as MappingABC
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePath, PureWindowsPath
from typing import Mapping, Protocol, Sequence

from agent_os.application.services.provider_backend_control import (
    provider_backend_registry,
)
from agent_os.infrastructure.persistence.event_log import (
    PlatformEventLogEntry,
    PlatformEventLogPort,
)
from agent_os.domain.value_objects.identifiers import WorkspaceId


CONSOLE_SCHEMA = "beacon.console.v1"
CONSOLE_SCHEMA_MAJOR = 1
DEFAULT_TIMELINE_LIMIT = 50
MAX_TIMELINE_LIMIT = 200

_PROVIDERS = ("claude", "codex", "hermes", "deepseek_harness")
_SESSION_COLLECTIONS = {
    "claude": ("claudeSessionHandles", "claudeSessionUuid"),
    "codex": ("codexSessionHandles", "codexSessionId"),
    "hermes": ("hermesSessionHandles", "hermesSessionId"),
    "deepseek_harness": (
        "deepseekHarnessSessionHandles",
        "deepseekHarnessSessionId",
    ),
}
_OFFICIAL_INTERFACES = {
    "claude_cli": "Claude Code CLI",
    "claude_agent_sdk": "Claude Agent SDK",
    "codex_exec_resume": "Codex CLI exec resume",
    "codex_app_server_stdio": "Codex app-server stdio",
    "hermes_cli": "Hermes CLI",
    "hermes_tui_gateway_stdio": "Hermes TUI gateway stdio",
    "deepseek_harness_sdk_stdio": "DeepSeek Harness SDK JSON-RPC stdio",
}
_EVENT_CATEGORY_PREFIXES = (
    ("agent_dispatch", "dispatch"),
    ("agent_exchange", "dispatch"),
    ("agent_endpoint", "identity"),
    ("agent_registration", "identity"),
    ("claude_registered_session", "session"),
    ("codex_registered_session", "session"),
    ("hermes_registered_session", "session"),
    ("deepseek_harness_registered_session", "session"),
    ("deepseek_harness_runtime", "runtime"),
    ("run_session", "lifecycle"),
    ("workspace", "workspace"),
)
_KNOWN_SESSION_STATES = {
    "active",
    "inactive",
    "continuity_lost",
    "completed",
    "failed",
    "unknown",
}
_KNOWN_DISPATCH_STATES = {
    "queued",
    "leased",
    "running",
    "waiting_response",
    "completed",
    "failed",
    "cancelled",
    "expired",
    "dry_run",
    "unknown",
}


class ConsoleOperationReader(Protocol):
    def list_workspaces(self) -> Mapping[str, object]: ...

    def list_agent_registrations(
        self,
        workspace_id: WorkspaceId | str,
    ) -> Mapping[str, object]: ...

    def list_agent_dispatches(
        self,
        workspace_id: WorkspaceId | str,
        *,
        limit: int = 20,
    ) -> Mapping[str, object]: ...

    def list_claude_session_handles(
        self,
        workspace_id: WorkspaceId | str,
        *,
        include_inactive: bool = False,
    ) -> Mapping[str, object]: ...

    def list_codex_session_handles(
        self,
        workspace_id: WorkspaceId | str,
        *,
        include_inactive: bool = False,
    ) -> Mapping[str, object]: ...

    def list_hermes_session_handles(
        self,
        workspace_id: WorkspaceId | str,
        *,
        include_inactive: bool = False,
    ) -> Mapping[str, object]: ...

    def list_deepseek_harness_session_handles(
        self,
        workspace_id: WorkspaceId | str,
        *,
        include_inactive: bool = False,
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class ConsoleProjectionService:
    """Redacted, deterministic read model for the local observation console."""

    operations: ConsoleOperationReader
    event_log: PlatformEventLogPort

    def list_workspaces(self) -> Mapping[str, object]:
        workspaces = self.operations.list_workspaces().get("workspaces", [])
        items = [
            _workspace_summary(item)
            for item in _mapping_items(workspaces)
        ]
        items.sort(key=lambda item: (str(item["displayName"]).lower(), item["workspaceId"]))
        return {
            "schema": CONSOLE_SCHEMA,
            "schemaMajor": CONSOLE_SCHEMA_MAJOR,
            "authority": "beacon",
            "displayShell": "beacon_read_only_projection",
            "readOnly": True,
            "items": items,
            "count": len(items),
            "sort": "displayName_asc_workspaceId_asc",
        }

    def provider_backends(self) -> Mapping[str, object]:
        descriptors = provider_backend_registry()
        items: list[Mapping[str, object]] = []
        for backend_id in sorted(descriptors):
            descriptor = descriptors[backend_id]
            provider = str(descriptor["provider"])
            capabilities = _mapping(descriptor.get("capabilities"))
            can_resume_across_process = bool(
                descriptor.get("canResumeAcrossRuntimeRestart")
            )
            items.append(
                {
                    "schema": "provider_backend_view.v1",
                    "provider": provider,
                    "backendId": backend_id,
                    "officialInterface": _OFFICIAL_INTERFACES.get(
                        backend_id,
                        "Unknown official interface",
                    ),
                    "beaconImplementation": str(
                        descriptor.get("currentImplementation", "unknown")
                    ),
                    "lifecycle": _enum_value(
                        descriptor.get("lifecycle"),
                        {
                            "short_lived_operation",
                            "managed_runtime",
                        },
                    ),
                    "runtimeOwnership": _enum_value(
                        descriptor.get("runtimeOwnership"),
                        {"none", "operation_owned", "persistent_owned"},
                    ),
                    "statusAuthority": _enum_value(
                        descriptor.get("statusAuthority"),
                        {"unsupported", "snapshot", "point_read", "owned_live"},
                    ),
                    "capabilities": {
                        "canSend": bool(capabilities.get("canExecuteInline")),
                        "canResume": True,
                        "canReadStatus": bool(capabilities.get("canReadStatus")),
                        "canReadOwnedLiveStatus": bool(
                            capabilities.get("canReadOwnedLiveStatus")
                        ),
                        "canSupplementActiveTurn": bool(
                            capabilities.get("canSupplementActiveTurn")
                        ),
                        "canCancel": bool(capabilities.get("canCancel")),
                        "canHandleApprovalRequests": (
                            backend_id == "codex_app_server_stdio"
                        ),
                        "canReadHistory": False,
                        "canCaptureFinalMessage": bool(
                            capabilities.get("canCaptureFinalMessage")
                        ),
                        "canResumeAcrossProcess": can_resume_across_process,
                        "canOwnRuntime": bool(capabilities.get("canOwnRuntime")),
                        "canManageMultipleThreads": bool(
                            capabilities.get("canManageMultipleThreads")
                        ),
                    },
                    "continuityScope": descriptor.get("continuityScope"),
                    "canResumeAcrossRuntimeRestart": descriptor.get(
                        "canResumeAcrossRuntimeRestart"
                    ),
                    "maxConcurrentOperations": descriptor.get(
                        "maxConcurrentOperations"
                    ),
                    "existingSessionImport": descriptor.get(
                        "existingSessionImport"
                    ),
                }
            )
        return {
            "schema": CONSOLE_SCHEMA,
            "schemaMajor": CONSOLE_SCHEMA_MAJOR,
            "authority": "beacon",
            "readOnly": True,
            "items": items,
            "count": len(items),
            "sort": "backendId_asc",
        }

    def workspace_view(
        self,
        workspace_id: str,
        *,
        cursor: str | None = None,
        limit: int = DEFAULT_TIMELINE_LIMIT,
    ) -> Mapping[str, object]:
        if not workspace_id.strip():
            raise ValueError("workspaceId must be a non-empty string.")
        if limit <= 0 or limit > MAX_TIMELINE_LIMIT:
            raise ValueError(
                f"limit must be between 1 and {MAX_TIMELINE_LIMIT}."
            )
        workspace = self._workspace(workspace_id)
        if workspace is None:
            raise ValueError("workspace not found.")

        agents = self._agents(workspace_id)
        sessions = self._sessions(workspace_id)
        dispatches = self._dispatches(workspace_id)
        timeline = self._timeline(
            workspace_id,
            cursor=cursor,
            limit=limit,
        )
        return {
            "schema": CONSOLE_SCHEMA,
            "schemaMajor": CONSOLE_SCHEMA_MAJOR,
            "authority": "beacon",
            "displayShell": "beacon_read_only_projection",
            "readOnly": True,
            "workspace": _workspace_summary(workspace),
            "agents": agents,
            "sessions": sessions,
            "providerBackends": self.provider_backends()["items"],
            "dispatches": dispatches,
            "timeline": timeline,
            "limitations": [
                "No prompt, transcript, provider database, credential, or raw event payload is exposed.",
                "No prompt, resume, cancel, steer, supplement, approval, reply, queue, config, or provider tool method exists.",
                "Presentation hosts do not own foreign Provider sessions or Provider-native identities.",
                "Loopback host checks are not authentication.",
            ],
        }

    def _workspace(self, workspace_id: str) -> Mapping[str, object] | None:
        workspaces = self.operations.list_workspaces().get("workspaces", [])
        return next(
            (
                item
                for item in _mapping_items(workspaces)
                if str(item.get("workspaceId")) == workspace_id
            ),
            None,
        )

    def _agents(self, workspace_id: str) -> list[Mapping[str, object]]:
        response = self.operations.list_agent_registrations(workspace_id)
        agents = []
        for item in _mapping_items(response.get("agents", [])):
            capability_names = [
                str(capability.get("name"))
                for capability in _mapping_items(item.get("capabilities", []))
                if capability.get("name") is not None
            ]
            agents.append(
                {
                    "schema": "console_agent_view.v1",
                    "workspaceId": workspace_id,
                    "agentId": str(item.get("agentId", "")),
                    "displayName": str(item.get("name", "Unnamed agent")),
                    "status": _enum_value(
                        item.get("status"),
                        {"active", "inactive", "archived", "unknown"},
                    ),
                    "capabilityNames": sorted(set(capability_names)),
                    "sourceEventSequence": _optional_int(
                        item.get("sourceEventSequence")
                    ),
                }
            )
        agents.sort(key=lambda item: (str(item["displayName"]).lower(), item["agentId"]))
        return agents

    def _sessions(self, workspace_id: str) -> list[Mapping[str, object]]:
        responses = {
            "claude": self.operations.list_claude_session_handles(
                workspace_id,
                include_inactive=True,
            ),
            "codex": self.operations.list_codex_session_handles(
                workspace_id,
                include_inactive=True,
            ),
            "hermes": self.operations.list_hermes_session_handles(
                workspace_id,
                include_inactive=True,
            ),
            "deepseek_harness": (
                self.operations.list_deepseek_harness_session_handles(
                    workspace_id,
                    include_inactive=True,
                )
            ),
        }
        sessions: list[Mapping[str, object]] = []
        for provider in _PROVIDERS:
            collection, native_id_field = _SESSION_COLLECTIONS[provider]
            for item in _mapping_items(responses[provider].get(collection, [])):
                state = _enum_value(item.get("state"), _KNOWN_SESSION_STATES)
                sessions.append(
                    {
                        "schema": "foreign_session_ref.v1",
                        "identity": {
                            "provider": provider,
                            "nativeSessionId": str(
                                item.get(native_id_field, "")
                            ),
                        },
                        "workspaceId": workspace_id,
                        "agentId": str(item.get("agentId", "")),
                        "handleId": str(item.get("handleId", "")),
                        "state": state,
                        "cwdSummary": _safe_path_summary(item.get("cwd")),
                        "updatedAt": _optional_text(item.get("updatedAt")),
                        "sourceEventSequence": _optional_int(
                            item.get("sourceEventSequence")
                        ),
                        "nativeDshSession": provider == "deepseek_harness",
                        "foreignProjectionOnly": provider != "deepseek_harness",
                        "continuity": _session_continuity(provider, state),
                    }
                )
        sessions.sort(
            key=lambda item: (
                str(_mapping(item["identity"])["provider"]),
                str(_mapping(item["identity"])["nativeSessionId"]),
                str(item["handleId"]),
            )
        )
        return sessions

    def _dispatches(self, workspace_id: str) -> list[Mapping[str, object]]:
        response = self.operations.list_agent_dispatches(
            workspace_id,
            limit=MAX_TIMELINE_LIMIT,
        )
        items: list[Mapping[str, object]] = []
        for dispatch in _mapping_items(response.get("agentDispatches", [])):
            effective = dispatch.get("effectiveStatus", dispatch.get("status"))
            items.append(
                {
                    "schema": "dispatch_projection.v1",
                    "workspaceId": workspace_id,
                    "dispatchId": str(dispatch.get("dispatchId", "")),
                    "exchangeRequestId": str(
                        dispatch.get("exchangeRequestId", "")
                    ),
                    "sourceAgentId": str(dispatch.get("sourceAgentId", "")),
                    "targetAgentId": str(dispatch.get("targetAgentId", "")),
                    "targetProvider": _optional_text(
                        dispatch.get("targetProvider")
                    ),
                    "targetHandleId": _optional_text(
                        dispatch.get("targetHandleId")
                    ),
                    "status": _enum_value(effective, _KNOWN_DISPATCH_STATES),
                    "apiLayer": "delivery-oriented",
                    "updatedAt": _optional_text(dispatch.get("updatedAt")),
                }
            )
        items.sort(
            key=lambda item: (
                str(item.get("updatedAt") or ""),
                str(item["dispatchId"]),
            ),
            reverse=True,
        )
        return items

    def _timeline(
        self,
        workspace_id: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> Mapping[str, object]:
        after_ordinal = _parse_cursor(cursor)
        entries = self.event_log.list_workspace_events(WorkspaceId(workspace_id))
        unique_entries = _deduplicate_entries(entries)
        cursor_out_of_range = after_ordinal > len(unique_entries)
        start = after_ordinal if not cursor_out_of_range else 0
        indexed = list(enumerate(unique_entries, start=1))
        selected = indexed[start : start + limit]
        has_more = start + len(selected) < len(indexed)
        events = [
            _timeline_event(entry, workspace_ordinal=ordinal)
            for ordinal, entry in selected
        ]
        next_ordinal = selected[-1][0] if selected else start
        first_anchor = (
            f"{unique_entries[0].sequence}:{unique_entries[0].record.event_id.value}"
            if unique_entries
            else "empty"
        )
        rebuild_token = sha256(
            f"{CONSOLE_SCHEMA}:{workspace_id}:{first_anchor}".encode("utf-8")
        ).hexdigest()[:24]
        return {
            "schema": "console_timeline_page.v1",
            "events": events,
            "page": {
                "cursor": cursor,
                "nextCursor": f"ord:{next_ordinal}",
                "limit": limit,
                "returned": len(events),
                "total": len(indexed),
                "hasMore": has_more,
                "truncated": has_more,
                "cursorOutOfRange": cursor_out_of_range,
                "rebuildRequired": cursor_out_of_range,
            },
            "replay": {
                "order": "workspaceOrdinal_asc_eventId_asc",
                "duplicateEventIdPolicy": "first_sequence_wins",
                "reconnect": "resume_from_nextCursor_or_rebuild_on_token_change",
                "rebuildToken": rebuild_token,
                "deterministicRebuild": True,
                "polling": "bounded_get_polling_no_stream_claim",
            },
        }


def _mapping(value: object) -> Mapping[str, object]:
    return dict(value) if isinstance(value, MappingABC) else {}


def _mapping_items(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [dict(item) for item in value if isinstance(item, MappingABC)]


def _workspace_summary(item: Mapping[str, object]) -> Mapping[str, object]:
    return {
        "schema": "console_workspace_view.v1",
        "workspaceId": str(item.get("workspaceId", "")),
        "displayName": str(item.get("displayName", "Unnamed workspace")),
        "rootSummary": _safe_path_summary(item.get("rootPath")),
        "status": _enum_value(
            item.get("status"),
            {"active", "archived", "unknown"},
        ),
        "updatedAt": _optional_text(item.get("updatedAt")),
        "sourceEventSequence": _optional_int(item.get("sourceEventSequence")),
    }


def _safe_path_summary(value: object) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    path = PureWindowsPath(text) if "\\" in text or ":" in text else PurePath(text)
    parts = [part for part in path.parts if part not in {path.anchor, "/", "\\"}]
    tail = parts[-2:]
    is_absolute = path.is_absolute() or bool(path.drive) or text.startswith("/")
    if len(parts) <= 2 and not is_absolute:
        return str(path)
    separator = "\\" if isinstance(path, PureWindowsPath) else "/"
    return f"…{separator}{separator.join(tail)}"


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _enum_value(value: object, known: set[str]) -> Mapping[str, object]:
    raw = str(value or "unknown").strip().lower() or "unknown"
    return {
        "value": raw if raw in known else "unknown",
        "rawValue": raw,
        "known": raw in known,
    }


def _session_continuity(
    provider: str,
    state: Mapping[str, object],
) -> Mapping[str, object]:
    raw_state = str(state["rawValue"])
    if provider != "deepseek_harness":
        return {
            "scope": "registered_provider_session",
            "state": "observed",
            "resumeAcrossRuntimeRestart": None,
        }
    return {
        "scope": "persistent_native_session",
        "state": (
            "resume_required"
            if raw_state in {"continuity_lost", "inactive"}
            else "native_session_available"
        ),
        "resumeAcrossRuntimeRestart": True,
    }


def _parse_cursor(cursor: str | None) -> int:
    if cursor is None or cursor == "":
        return 0
    if not cursor.startswith("ord:"):
        raise ValueError("cursor must use the opaque ord:<non-negative-int> form.")
    try:
        value = int(cursor[4:])
    except ValueError as exc:
        raise ValueError(
            "cursor must use the opaque ord:<non-negative-int> form."
        ) from exc
    if value < 0:
        raise ValueError("cursor ordinal must be non-negative.")
    return value


def _deduplicate_entries(
    entries: Sequence[PlatformEventLogEntry],
) -> tuple[PlatformEventLogEntry, ...]:
    by_event_id: dict[str, PlatformEventLogEntry] = {}
    for entry in sorted(
        entries,
        key=lambda item: (item.sequence, item.record.event_id.value),
    ):
        by_event_id.setdefault(entry.record.event_id.value, entry)
    return tuple(
        sorted(
            by_event_id.values(),
            key=lambda item: (item.sequence, item.record.event_id.value),
        )
    )


def _timeline_event(
    entry: PlatformEventLogEntry,
    *,
    workspace_ordinal: int,
) -> Mapping[str, object]:
    kind = entry.record.event_kind.value
    category = next(
        (
            mapped
            for prefix, mapped in _EVENT_CATEGORY_PREFIXES
            if kind.startswith(prefix)
        ),
        "unknown",
    )
    return {
        "schema": "console_timeline_event.v1",
        "eventId": entry.record.event_id.value,
        "workspaceOrdinal": workspace_ordinal,
        "sourceEventSequence": entry.sequence,
        "occurredAt": entry.record.occurred_at.isoformat(),
        "category": _enum_value(
            category,
            {"identity", "session", "dispatch", "runtime", "lifecycle", "workspace"},
        ),
        "eventKind": kind,
        "aggregateType": entry.record.aggregate_type,
        "aggregateId": entry.record.aggregate_id,
        "summary": _event_summary(kind),
        "presentationNodeKey": (
            "beacon.console.timeline-event.v1/"
            f"{entry.record.event_id.value}"
        ),
    }


def _event_summary(kind: str) -> str:
    summaries = {
        "workspace.changed": "Workspace state changed",
        "agent_registration.changed": "Agent registration changed",
        "agent_endpoint.changed": "Agent endpoint identity changed",
        "agent_dispatch.changed": "Dispatch projection changed",
        "agent_dispatch_lease.changed": "Dispatch lease changed",
        "agent_dispatch_daemon_liveness.changed": "Dispatch daemon liveness changed",
        "claude_registered_session_handle.changed": "Claude session handle changed",
        "codex_registered_session_handle.changed": "Codex session handle changed",
        "hermes_registered_session_handle.changed": "Hermes session handle changed",
        "deepseek_harness_registered_session_handle.changed": "DSH session handle changed",
        "deepseek_harness_runtime_lifecycle.recorded": "DSH runtime lifecycle changed",
        "run_session.changed": "Run-session lifecycle changed",
    }
    return summaries.get(kind, "Platform event observed")
