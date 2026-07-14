from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence
from uuid import UUID


AGENT_SESSION_DISCOVERY_SCHEMA = "agent_session_discovery.v1"
AGENT_SESSION_DISCOVERY_RECORD_SCHEMA = "agent_session_discovery_record.v1"
AGENT_SESSION_DISCOVERY_ERROR_SCHEMA = "agent_session_discovery_error.v1"
AGENT_SESSION_DISCOVERY_DIAGNOSTIC_SCHEMA = (
    "agent_session_discovery_diagnostic.v1"
)
HERMES_SESSION_IDENTITY_SCHEMA = "hermes_session_identity.v1"

AGENT_RUNTIME_CHOICES = ("claude", "codex", "hermes")
AGENT_RUNTIME_ALL = ("claude", "codex", "hermes")
PROVIDER_BY_RUNTIME = {
    "claude": "claude-code",
    "codex": "codex-cli",
    "hermes": "hermes-cli",
}
PROVIDER_SESSION_FIELD_BY_RUNTIME = {
    "claude": "claudeSessionUuid",
    "codex": "codexSessionId",
    "hermes": "hermesSessionId",
}
REGISTER_COMMAND_BY_RUNTIME = {
    "claude": "claude-session-handle-register",
    "codex": "codex-session-handle-register",
    "hermes": "hermes-session-handle-register",
}
REGISTER_SESSION_OPTION_BY_RUNTIME = {
    "claude": "--claude-session-uuid",
    "codex": "--codex-session-id",
    "hermes": "--hermes-session-id",
}

_JSONL_SCAN_LINE_LIMIT = 200
_JSONL_LINE_MAX_BYTES = 1024 * 1024
_JSON_NESTING_MAX_DEPTH = 20
_JSONL_PATH_MAX_DEPTH = 8
_FULL_HISTORY_MAX_MESSAGES = 128
_FULL_HISTORY_MAX_CHARS = 64 * 1024
_TURN_SNIPPET_MAX_CHARS_DEFAULT = 160
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_HERMES_SESSION_ID_RES = (
    re.compile(r"\b\d{8}_\d{6}_[A-Za-z0-9]{4,}\b"),
    _UUID_RE,
    re.compile(r"\b(?:session|sess)[-_][A-Za-z0-9][A-Za-z0-9_.-]{5,}\b"),
)


@dataclass(frozen=True, slots=True)
class _JsonlScanResult:
    records: tuple[Mapping[str, object], ...]
    scanned_line_count: int
    scanned_byte_count: int
    truncated: bool
    truncation_reason: str | None


@dataclass(frozen=True, slots=True)
class AgentSessionDiscoveryRecord:
    agent_runtime: str
    session_id: str
    source_kind: str
    cwd: str | None = None
    source_path: str | None = None
    updated_at: str | None = None
    confidence: str = "medium"
    cwd_source: str | None = None
    current_session_match: bool | None = None
    provider_account_label: str | None = None
    provider_account_source: str | None = None
    vendor_account_label: str | None = None
    vendor_account_source: str | None = None
    relay_account_label: str | None = None
    relay_account_source: str | None = None
    turn_snippet: Mapping[str, object] | None = None
    session_history: Mapping[str, object] | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def to_metadata(self) -> Mapping[str, object]:
        missing_fields = _registration_missing_fields(
            self.agent_runtime,
            self.session_id,
            self.cwd,
        )
        payload: dict[str, object] = {
            "schema": AGENT_SESSION_DISCOVERY_RECORD_SCHEMA,
            "agentRuntime": self.agent_runtime,
            "provider": PROVIDER_BY_RUNTIME[self.agent_runtime],
            "sessionId": self.session_id,
            "providerSessionField": PROVIDER_SESSION_FIELD_BY_RUNTIME[
                self.agent_runtime
            ],
            "sourceKind": self.source_kind,
            "confidence": self.confidence,
            "registrationReady": not missing_fields,
            "missingFields": missing_fields,
            "registrationCommand": {
                "command": REGISTER_COMMAND_BY_RUNTIME[self.agent_runtime],
                "sessionIdOption": REGISTER_SESSION_OPTION_BY_RUNTIME[
                    self.agent_runtime
                ],
            },
            "metadata": dict(self.metadata),
            "providerAccountRead": self.provider_account_label is not None,
            "turnSnippetRead": self.turn_snippet is not None,
            "fullSessionHistoryRead": self.session_history is not None,
            "credentialStored": False,
            "accountLabelBoundary": (
                "Provider/vendor/relay account labels describe provider-side or "
                "relay profile metadata when available; they are not Windows, "
                "macOS, or Linux OS user accounts."
            ),
        }
        if self.current_session_match is not None:
            payload["currentSessionMatch"] = self.current_session_match
        if self.provider_account_label is not None:
            payload["providerAccountLabel"] = self.provider_account_label
        if self.provider_account_source is not None:
            payload["providerAccountSource"] = self.provider_account_source
        account_labels = _account_labels_payload(
            provider_label=self.provider_account_label,
            provider_source=self.provider_account_source,
            vendor_label=self.vendor_account_label,
            vendor_source=self.vendor_account_source,
            relay_label=self.relay_account_label,
            relay_source=self.relay_account_source,
        )
        if account_labels:
            payload["accountLabels"] = account_labels
        if self.vendor_account_label is not None:
            payload["vendorAccountLabel"] = self.vendor_account_label
        if self.vendor_account_source is not None:
            payload["vendorAccountSource"] = self.vendor_account_source
        if self.relay_account_label is not None:
            payload["relayAccountLabel"] = self.relay_account_label
        if self.relay_account_source is not None:
            payload["relayAccountSource"] = self.relay_account_source
        if self.turn_snippet is not None:
            payload["turnSnippet"] = dict(self.turn_snippet)
        if self.session_history is not None:
            payload["sessionHistory"] = dict(self.session_history)
        if self.cwd is not None:
            payload["cwd"] = self.cwd
        if self.cwd_source is not None:
            payload["cwdSource"] = self.cwd_source
        if self.source_path is not None:
            payload["sourcePath"] = self.source_path
        if self.updated_at is not None:
            payload["updatedAt"] = self.updated_at
        provider_session_identity = self.metadata.get("providerSessionIdentity")
        if isinstance(provider_session_identity, Mapping):
            payload["providerSessionIdentity"] = dict(provider_session_identity)
        return payload


def discover_agent_sessions(
    *,
    provider: str,
    limit: int = 20,
    cwd: str | None = None,
    claude_home: str | None = None,
    codex_home: str | None = None,
    hermes_home: str | None = None,
    hermes_executable: str = "hermes",
    hermes_source: str | None = None,
    hermes_timeout_seconds: float = 15.0,
    current_session_id: str | None = None,
    include_turn_snippets: bool = False,
    include_full_session_history: bool = False,
    snippet_turn_index: int | None = None,
    snippet_max_chars: int = _TURN_SNIPPET_MAX_CHARS_DEFAULT,
    provider_account_label: str | None = None,
    vendor_account_label: str | None = None,
    relay_account_label: str | None = None,
) -> Mapping[str, object]:
    normalized_provider = _normalize_discovery_provider(provider)
    providers = AGENT_RUNTIME_ALL if normalized_provider == "all" else (normalized_provider,)
    resolved_limit = _positive_limit(limit)
    fallback_cwd = _resolved_cwd(cwd)
    resolved_current_session_id = _as_text(current_session_id)
    resolved_snippet_turn_index = _optional_positive_int(
        snippet_turn_index,
        "snippetTurnIndex",
    )
    resolved_snippet_max_chars = _positive_limit(snippet_max_chars)
    account_filter = _account_label_filter(
        provider_account_label=provider_account_label,
        vendor_account_label=vendor_account_label,
        relay_account_label=relay_account_label,
    )
    records: list[AgentSessionDiscoveryRecord] = []
    errors: list[Mapping[str, object]] = []
    diagnostics: list[Mapping[str, object]] = []
    provider_discovery: dict[str, object] = {}

    for runtime in providers:
        try:
            if runtime == "claude":
                records.extend(
                    _discover_claude_sessions(
                        claude_home=claude_home,
                        fallback_cwd=fallback_cwd,
                        limit=resolved_limit,
                        current_session_id=resolved_current_session_id,
                        include_turn_snippets=include_turn_snippets,
                        include_full_session_history=include_full_session_history,
                        snippet_turn_index=resolved_snippet_turn_index,
                        snippet_max_chars=resolved_snippet_max_chars,
                    )
                )
            elif runtime == "codex":
                records.extend(
                    _discover_codex_sessions(
                        codex_home=codex_home,
                        fallback_cwd=fallback_cwd,
                        limit=resolved_limit,
                        current_session_id=resolved_current_session_id,
                        include_turn_snippets=include_turn_snippets,
                        include_full_session_history=include_full_session_history,
                        snippet_turn_index=resolved_snippet_turn_index,
                        snippet_max_chars=resolved_snippet_max_chars,
                    )
                )
            elif runtime == "hermes":
                (
                    discovered,
                    runtime_errors,
                    runtime_diagnostics,
                    runtime_context,
                ) = _discover_hermes_sessions(
                    hermes_executable=hermes_executable,
                    hermes_home=hermes_home,
                    hermes_source=hermes_source,
                    fallback_cwd=fallback_cwd,
                    limit=resolved_limit,
                    timeout_seconds=hermes_timeout_seconds,
                    current_session_id=resolved_current_session_id,
                )
                records.extend(discovered)
                errors.extend(runtime_errors)
                diagnostics.extend(runtime_diagnostics)
                provider_discovery["hermes"] = dict(runtime_context)
        except OSError as exc:
            errors.append(_discovery_error(runtime, "filesystem_error", str(exc)))

    deduped_records = [
        record for record in _dedupe_records(records)
        if _record_matches_account_filter(record, account_filter)
    ]
    sorted_records = sorted(
        deduped_records,
        key=lambda item: (item.updated_at or "", item.agent_runtime, item.session_id),
        reverse=True,
    )[:resolved_limit]
    agent_sessions = [record.to_metadata() for record in sorted_records]
    return {
        "agentSessionDiscovery": {
            "schema": AGENT_SESSION_DISCOVERY_SCHEMA,
            "provider": normalized_provider,
            "providers": list(providers),
            "limit": resolved_limit,
            "cwd": fallback_cwd,
            "currentSessionIdProvided": resolved_current_session_id is not None,
            "includeTurnSnippets": include_turn_snippets,
            "includeFullSessionHistory": include_full_session_history,
            "fullSessionHistoryReadDefault": False,
            "fullSessionHistoryReadRequiresExplicitOptIn": True,
            "snippetTurnIndex": resolved_snippet_turn_index,
            "snippetMaxChars": resolved_snippet_max_chars,
            "accountLabelFilter": account_filter,
            "accountLabelBoundary": (
                "Provider/vendor/relay account filters match provider-side or "
                "relay metadata labels. They do not filter local OS accounts."
            ),
            "agentSessions": agent_sessions,
            "discoveryErrors": list(errors),
            "discoveryDiagnostics": list(diagnostics),
            "providerDiscovery": provider_discovery,
            "count": len(agent_sessions),
            "currentSessionMatchCount": sum(
                1 for record in agent_sessions if record.get("currentSessionMatch")
            ),
        },
        "agentSessions": agent_sessions,
        "discoveryErrors": list(errors),
        "discoveryDiagnostics": list(diagnostics),
        "providerDiscovery": provider_discovery,
        "count": len(agent_sessions),
    }


def find_discovered_agent_session(
    discovery: Mapping[str, object],
    *,
    provider: str,
    session_id: str,
) -> Mapping[str, object]:
    normalized_provider = _normalize_agent_runtime(provider)
    wanted_session_id = _required_text(session_id, "sessionId")
    for record in discovery.get("agentSessions", ()):
        if not isinstance(record, Mapping):
            continue
        if (
            record.get("agentRuntime") == normalized_provider
            and record.get("sessionId") == wanted_session_id
        ):
            return dict(record)
    raise ValueError("discovered agent session not found.")


def discovery_registration_metadata(
    record: Mapping[str, object],
    *,
    metadata: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    safe_record = {
        "schema": record.get("schema"),
        "agentRuntime": record.get("agentRuntime"),
        "provider": record.get("provider"),
        "sourceKind": record.get("sourceKind"),
        "sourcePath": record.get("sourcePath"),
        "updatedAt": record.get("updatedAt"),
        "confidence": record.get("confidence"),
        "cwdSource": record.get("cwdSource"),
        "fullSessionHistoryRead": False,
        "credentialStored": False,
    }
    result: dict[str, object] = {
        **dict(metadata or {}),
        "registeredFromDiscovery": {
            key: value for key, value in safe_record.items() if value is not None
        },
    }
    provider_identity = record.get("providerSessionIdentity")
    if isinstance(provider_identity, Mapping):
        result["hermesSessionIdentity"] = dict(provider_identity)
    return result


def _discover_claude_sessions(
    *,
    claude_home: str | None,
    fallback_cwd: str | None,
    limit: int,
    current_session_id: str | None,
    include_turn_snippets: bool,
    include_full_session_history: bool,
    snippet_turn_index: int | None,
    snippet_max_chars: int,
) -> list[AgentSessionDiscoveryRecord]:
    root = _home_path(claude_home, ".claude")
    candidates = [
        *(_jsonl_files(root / "projects")),
        *(_jsonl_files(root / "sessions")),
    ]
    records: list[AgentSessionDiscoveryRecord] = []
    for path in _newest_files(candidates):
        values = _read_jsonl_session_values(
            path,
            include_turn_snippets=include_turn_snippets,
            include_full_session_history=include_full_session_history,
            snippet_turn_index=snippet_turn_index,
            snippet_max_chars=snippet_max_chars,
        )
        session_id = values.get("session_id") or _session_id_from_filename(path)
        if not session_id:
            continue
        cwd, cwd_source = _resolved_record_cwd(values.get("cwd"), fallback_cwd)
        records.append(
            AgentSessionDiscoveryRecord(
                agent_runtime="claude",
                session_id=session_id,
                cwd=cwd,
                cwd_source=cwd_source,
                source_path=str(path),
                source_kind="claude_projects_jsonl",
                updated_at=_path_updated_at(path),
                confidence="high" if values.get("session_id") else "low",
                current_session_match=(
                    session_id == current_session_id
                    if current_session_id is not None
                    else None
                ),
                provider_account_label=values.get("provider_account_label"),
                provider_account_source=values.get("provider_account_source"),
                vendor_account_label=values.get("vendor_account_label"),
                vendor_account_source=values.get("vendor_account_source"),
                relay_account_label=values.get("relay_account_label"),
                relay_account_source=values.get("relay_account_source"),
                turn_snippet=_json_object_from_values(values, "turn_snippet"),
                session_history=_json_object_from_values(values, "session_history"),
                metadata={
                    "recordSource": "jsonl_keys",
                    "jsonlScan": _json_object_from_values(values, "jsonl_scan"),
                },
            )
        )
        if len(records) >= limit:
            break
    return records


def _discover_codex_sessions(
    *,
    codex_home: str | None,
    fallback_cwd: str | None,
    limit: int,
    current_session_id: str | None,
    include_turn_snippets: bool,
    include_full_session_history: bool,
    snippet_turn_index: int | None,
    snippet_max_chars: int,
) -> list[AgentSessionDiscoveryRecord]:
    root = _home_path(codex_home, ".codex")
    records: list[AgentSessionDiscoveryRecord] = []
    for path in _newest_files(_jsonl_files(root / "sessions")):
        values = _read_jsonl_session_values(
            path,
            include_turn_snippets=include_turn_snippets,
            include_full_session_history=include_full_session_history,
            snippet_turn_index=snippet_turn_index,
            snippet_max_chars=snippet_max_chars,
        )
        session_id = values.get("session_id") or _session_id_from_filename(path)
        if not session_id:
            continue
        cwd, cwd_source = _resolved_record_cwd(values.get("cwd"), fallback_cwd)
        records.append(
            AgentSessionDiscoveryRecord(
                agent_runtime="codex",
                session_id=session_id,
                cwd=cwd,
                cwd_source=cwd_source,
                source_path=str(path),
                source_kind="codex_sessions_jsonl",
                updated_at=values.get("updated_at") or _path_updated_at(path),
                confidence="high" if values.get("session_id") else "medium",
                current_session_match=(
                    session_id == current_session_id
                    if current_session_id is not None
                    else None
                ),
                provider_account_label=values.get("provider_account_label"),
                provider_account_source=values.get("provider_account_source"),
                vendor_account_label=values.get("vendor_account_label"),
                vendor_account_source=values.get("vendor_account_source"),
                relay_account_label=values.get("relay_account_label"),
                relay_account_source=values.get("relay_account_source"),
                turn_snippet=_json_object_from_values(values, "turn_snippet"),
                session_history=_json_object_from_values(values, "session_history"),
                metadata={
                    "recordSource": "jsonl_keys",
                    "jsonlScan": _json_object_from_values(values, "jsonl_scan"),
                },
            )
        )
        if len(records) >= limit:
            break

    if len(records) < limit:
        index = root / "session_index.jsonl"
        if index.exists():
            for record in _discover_codex_index_sessions(
                index,
                fallback_cwd=fallback_cwd,
                remaining=limit - len(records),
                current_session_id=current_session_id,
            ):
                records.append(record)
                if len(records) >= limit:
                    break
    return records


def _discover_codex_index_sessions(
    index_path: Path,
    *,
    fallback_cwd: str | None,
    remaining: int,
    current_session_id: str | None,
) -> list[AgentSessionDiscoveryRecord]:
    records: list[AgentSessionDiscoveryRecord] = []
    for payload in _iter_jsonl_objects(index_path, limit=max(remaining * 4, 20)):
        session_id = _first_text(payload, ("session_id", "sessionId", "id"))
        if not session_id:
            continue
        cwd, cwd_source = _resolved_record_cwd(None, fallback_cwd)
        labels = _account_labels(payload)
        records.append(
            AgentSessionDiscoveryRecord(
                agent_runtime="codex",
                session_id=session_id,
                cwd=cwd,
                cwd_source=cwd_source,
                source_path=str(index_path),
                source_kind="codex_session_index_jsonl",
                updated_at=_first_text(payload, ("updated_at", "updatedAt"))
                or _path_updated_at(index_path),
                confidence="medium",
                current_session_match=(
                    session_id == current_session_id
                    if current_session_id is not None
                    else None
                ),
                provider_account_label=labels.get("providerLabel"),
                provider_account_source=labels.get("providerSource"),
                vendor_account_label=labels.get("vendorLabel"),
                vendor_account_source=labels.get("vendorSource"),
                relay_account_label=labels.get("relayLabel"),
                relay_account_source=labels.get("relaySource"),
                metadata={"recordSource": "session_index_keys"},
            )
        )
        if len(records) >= remaining:
            break
    return records


def _discover_hermes_sessions(
    *,
    hermes_executable: str,
    hermes_home: str | None,
    hermes_source: str | None,
    fallback_cwd: str | None,
    limit: int,
    timeout_seconds: float,
    current_session_id: str | None,
) -> tuple[
    list[AgentSessionDiscoveryRecord],
    list[Mapping[str, object]],
    list[Mapping[str, object]],
    Mapping[str, object],
]:
    runtime_home, runtime_home_source = _resolve_hermes_runtime_home(
        hermes_home,
        hermes_executable=hermes_executable,
    )
    context: dict[str, object] = {
        "schema": "hermes_session_discovery_context.v1",
        "runtimeHome": str(runtime_home) if runtime_home is not None else None,
        "runtimeHomeSource": runtime_home_source,
        "sourceFilter": _as_text(hermes_source),
        "inventoryMode": "hermes_sessions_cli",
        "fullSessionHistoryRead": False,
    }
    if runtime_home is not None:
        state_db = runtime_home / "state.db"
        if state_db.is_file():
            try:
                records, diagnostics = _discover_hermes_sessions_from_state_db(
                    state_db,
                    runtime_home=runtime_home,
                    runtime_home_source=runtime_home_source,
                    hermes_source=hermes_source,
                    fallback_cwd=fallback_cwd,
                    limit=limit,
                    current_session_id=current_session_id,
                )
            except (OSError, sqlite3.Error) as exc:
                return [], [
                    _discovery_error(
                        "hermes",
                        "structured_store_failed",
                        f"Hermes structured session store could not be read: {exc}",
                    )
                ], [], {
                    **context,
                    "inventoryMode": "hermes_state_db_metadata",
                    "stateDatabase": str(state_db),
                }
            return records, [], diagnostics, {
                **context,
                "inventoryMode": "hermes_state_db_metadata",
                "stateDatabase": str(state_db),
            }

    command = [
        _required_text(hermes_executable, "hermesExecutable"),
        "sessions",
        "list",
        "--limit",
        str(limit),
    ]
    if hermes_source:
        command.extend(("--source", hermes_source))
    environment = os.environ.copy()
    if runtime_home is not None:
        environment["HERMES_HOME"] = str(runtime_home)
    try:
        completed = subprocess.run(
            command,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError:
        return [], [
            _discovery_error(
                "hermes",
                "executable_not_found",
                f"Hermes executable not found: {hermes_executable}",
                command_argv=command,
            )
        ], [], context
    except subprocess.TimeoutExpired:
        return [], [
            _discovery_error(
                "hermes",
                "command_timeout",
                "Hermes session discovery command timed out.",
                command_argv=command,
            )
        ], [], context
    if completed.returncode != 0:
        return [], [
            _discovery_error(
                "hermes",
                "command_failed",
                "Hermes session discovery command exited non-zero.",
                command_argv=command,
                command_exit_code=completed.returncode,
                stdout_tail=_tail_text(completed.stdout),
                stderr_tail=_tail_text(completed.stderr),
            )
        ], [], context
    records = _parse_hermes_sessions_output(
        completed.stdout,
        fallback_cwd=fallback_cwd,
        limit=limit,
        current_session_id=current_session_id,
        runtime_home=runtime_home,
        runtime_home_source=runtime_home_source,
        source_filter=hermes_source,
    )
    diagnostics: list[Mapping[str, object]] = []
    if not records:
        diagnostics.append(
            _hermes_discovery_diagnostic(
                "no_sessions",
                "Hermes discovery completed but returned no sessions.",
                runtime_home=runtime_home,
                runtime_home_source=runtime_home_source,
                source_filter=hermes_source,
            )
        )
        if current_session_id is not None and runtime_home is not None:
            diagnostics.append(
                _hermes_discovery_diagnostic(
                    "runtime_home_mismatch",
                    "The expected Hermes session was not found in the selected runtime home.",
                    runtime_home=runtime_home,
                    runtime_home_source=runtime_home_source,
                    source_filter=hermes_source,
                    expected_session_id=current_session_id,
                )
            )
    return (
        records,
        [],
        diagnostics,
        context,
    )


def _resolve_hermes_runtime_home(
    configured_home: str | None,
    *,
    hermes_executable: str,
) -> tuple[Path | None, str]:
    explicit = _as_text(configured_home)
    if explicit is not None:
        return Path(explicit).expanduser().resolve(strict=False), "explicit"
    executable = _required_text(hermes_executable, "hermesExecutable")
    if not any(separator in executable for separator in ("/", "\\")):
        environment_home = _as_text(os.environ.get("HERMES_HOME"))
        if environment_home is not None:
            return (
                Path(environment_home).expanduser().resolve(strict=False),
                "process_environment",
            )
    return None, "provider_default_unknown"


def _discover_hermes_sessions_from_state_db(
    state_db: Path,
    *,
    runtime_home: Path,
    runtime_home_source: str,
    hermes_source: str | None,
    fallback_cwd: str | None,
    limit: int,
    current_session_id: str | None,
) -> tuple[
    list[AgentSessionDiscoveryRecord],
    list[Mapping[str, object]],
]:
    source_filter = _as_text(hermes_source)
    connection = sqlite3.connect(f"{state_db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(sessions)").fetchall()
        }
        if not {"id", "source"}.issubset(columns):
            raise sqlite3.DatabaseError(
                "Hermes sessions table is missing required id/source columns."
            )
        selected_columns = ["id", "source"]
        selected_columns.extend(
            column
            for column in ("cwd", "ended_at", "started_at")
            if column in columns
        )
        order_expression = (
            "COALESCE(ended_at, started_at)"
            if {"ended_at", "started_at"}.issubset(columns)
            else next(
                (
                    column
                    for column in ("ended_at", "started_at", "id")
                    if column in columns
                ),
                "id",
            )
        )
        select_clause = f"SELECT {', '.join(selected_columns)} FROM sessions"
        if source_filter is None:
            rows = connection.execute(
                f"{select_clause} ORDER BY {order_expression} DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = connection.execute(
                f"{select_clause} WHERE source = ? "
                f"ORDER BY {order_expression} DESC LIMIT ?",
                (source_filter, limit),
            ).fetchall()
        has_sessions = connection.execute(
            "SELECT 1 FROM sessions LIMIT 1"
        ).fetchone() is not None
        expected_row = (
            connection.execute(
                f"{select_clause} WHERE id = ? LIMIT 1",
                (current_session_id,),
            ).fetchone()
            if current_session_id is not None
            else None
        )
    finally:
        connection.close()

    selected = [dict(zip(selected_columns, row, strict=True)) for row in rows]
    diagnostics: list[Mapping[str, object]] = []
    expected = (
        dict(zip(selected_columns, expected_row, strict=True))
        if expected_row is not None
        else None
    )
    if not selected:
        diagnostics.append(
            _hermes_discovery_diagnostic(
                "no_sessions",
                "Hermes structured session inventory returned no matching sessions.",
                runtime_home=runtime_home,
                runtime_home_source=runtime_home_source,
                source_filter=source_filter,
                expected_session_id=current_session_id,
            )
        )
    if source_filter is not None and has_sessions and not selected:
        diagnostics.append(
            _hermes_discovery_diagnostic(
                "source_filter_mismatch",
                "Hermes sessions exist in this runtime home, but none match the selected source filter.",
                runtime_home=runtime_home,
                runtime_home_source=runtime_home_source,
                source_filter=source_filter,
                expected_session_id=current_session_id,
                observed_session_source=(
                    _as_text(expected.get("source")) if expected is not None else None
                ),
            )
        )
    if current_session_id is not None and expected is None:
        diagnostics.append(
            _hermes_discovery_diagnostic(
                "runtime_home_mismatch",
                "The expected Hermes session is absent from the selected runtime home.",
                runtime_home=runtime_home,
                runtime_home_source=runtime_home_source,
                source_filter=source_filter,
                expected_session_id=current_session_id,
            )
        )
    elif (
        expected is not None
        and source_filter is not None
        and _as_text(expected.get("source")) != source_filter
    ):
        diagnostics.append(
            _hermes_discovery_diagnostic(
                "source_filter_mismatch",
                "The expected Hermes session exists, but under a different source tag.",
                runtime_home=runtime_home,
                runtime_home_source=runtime_home_source,
                source_filter=source_filter,
                expected_session_id=current_session_id,
                observed_session_source=_as_text(expected.get("source")),
            )
        )

    records: list[AgentSessionDiscoveryRecord] = []
    for value in selected:
        session_id = _as_text(value.get("id"))
        if session_id is None:
            continue
        session_source = _as_text(value.get("source"))
        cwd, cwd_source = _resolved_record_cwd(
            _as_text(value.get("cwd")),
            fallback_cwd,
        )
        updated_at = _hermes_unix_timestamp(
            value.get("ended_at") or value.get("started_at")
        )
        records.append(
            AgentSessionDiscoveryRecord(
                agent_runtime="hermes",
                session_id=session_id,
                cwd=cwd,
                cwd_source=cwd_source,
                source_path=str(state_db),
                source_kind="hermes_state_db_metadata",
                updated_at=updated_at,
                confidence="high",
                current_session_match=(
                    session_id == current_session_id
                    if current_session_id is not None
                    else None
                ),
                metadata={
                    "recordSource": "hermes_state_db_sessions_table",
                    "providerSessionIdentity": _hermes_session_identity(
                        session_id=session_id,
                        discovery_source="hermes_state_db_metadata",
                        runtime_home=runtime_home,
                        runtime_home_source=runtime_home_source,
                        session_source=session_source,
                        source_filter=source_filter,
                    ),
                },
            )
        )
    return records, _dedupe_diagnostics(diagnostics)


def _hermes_session_identity(
    *,
    session_id: str,
    discovery_source: str,
    runtime_home: Path | None,
    runtime_home_source: str,
    session_source: str | None,
    source_filter: str | None,
) -> Mapping[str, object]:
    return {
        key: value
        for key, value in {
            "schema": HERMES_SESSION_IDENTITY_SCHEMA,
            "providerSessionId": session_id,
            "discoverySource": discovery_source,
            "runtimeHome": str(runtime_home) if runtime_home is not None else None,
            "runtimeHomeSource": runtime_home_source,
            "sessionSource": _as_text(session_source),
            "sourceFilter": _as_text(source_filter),
            "fullSessionHistoryRead": False,
        }.items()
        if value is not None
    }


def _hermes_unix_timestamp(value: object) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _hermes_discovery_diagnostic(
    category: str,
    message: str,
    *,
    runtime_home: Path | None,
    runtime_home_source: str,
    source_filter: str | None,
    expected_session_id: str | None = None,
    observed_session_source: str | None = None,
) -> Mapping[str, object]:
    return {
        key: value
        for key, value in {
            "schema": AGENT_SESSION_DISCOVERY_DIAGNOSTIC_SCHEMA,
            "agentRuntime": "hermes",
            "provider": "hermes-cli",
            "diagnosticCategory": category,
            "message": message,
            "runtimeHome": str(runtime_home) if runtime_home is not None else None,
            "runtimeHomeSource": runtime_home_source,
            "sourceFilter": _as_text(source_filter),
            "expectedSessionId": _as_text(expected_session_id),
            "observedSessionSource": _as_text(observed_session_source),
            "fullSessionHistoryRead": False,
        }.items()
        if value is not None
    }


def _dedupe_diagnostics(
    diagnostics: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    deduped: dict[tuple[object, object, object], Mapping[str, object]] = {}
    for diagnostic in diagnostics:
        key = (
            diagnostic.get("diagnosticCategory"),
            diagnostic.get("expectedSessionId"),
            diagnostic.get("observedSessionSource"),
        )
        deduped.setdefault(key, diagnostic)
    return list(deduped.values())


def _parse_hermes_sessions_output(
    output: str,
    *,
    fallback_cwd: str | None,
    limit: int,
    current_session_id: str | None,
    runtime_home: Path | None = None,
    runtime_home_source: str = "provider_default_unknown",
    source_filter: str | None = None,
) -> list[AgentSessionDiscoveryRecord]:
    stripped = output.strip()
    if not stripped or "No sessions found" in stripped:
        return []
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None:
            return _hermes_records_from_json(
                parsed,
                fallback_cwd=fallback_cwd,
                limit=limit,
                current_session_id=current_session_id,
                runtime_home=runtime_home,
                runtime_home_source=runtime_home_source,
                source_filter=source_filter,
            )
    return _hermes_records_from_text(
        stripped,
        fallback_cwd=fallback_cwd,
        limit=limit,
        current_session_id=current_session_id,
        runtime_home=runtime_home,
        runtime_home_source=runtime_home_source,
        source_filter=source_filter,
    )


def _hermes_records_from_json(
    parsed: object,
    *,
    fallback_cwd: str | None,
    limit: int,
    current_session_id: str | None,
    runtime_home: Path | None = None,
    runtime_home_source: str = "provider_default_unknown",
    source_filter: str | None = None,
) -> list[AgentSessionDiscoveryRecord]:
    items = parsed if isinstance(parsed, list) else [parsed]
    records: list[AgentSessionDiscoveryRecord] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        session_id = _first_text(item, ("session_id", "sessionId", "id"))
        if not session_id:
            continue
        cwd, cwd_source = _resolved_record_cwd(
            _first_text(item, ("cwd", "workdir", "workspaceRoot", "projectDir")),
            fallback_cwd,
        )
        labels = _account_labels(item)
        records.append(
            AgentSessionDiscoveryRecord(
                agent_runtime="hermes",
                session_id=session_id,
                cwd=cwd,
                cwd_source=cwd_source,
                source_path=None,
                source_kind="hermes_sessions_cli_json",
                updated_at=_first_text(item, ("updated_at", "updatedAt", "lastActiveAt")),
                confidence="high",
                current_session_match=(
                    session_id == current_session_id
                    if current_session_id is not None
                    else None
                ),
                provider_account_label=labels.get("providerLabel"),
                provider_account_source=labels.get("providerSource"),
                vendor_account_label=labels.get("vendorLabel"),
                vendor_account_source=labels.get("vendorSource"),
                relay_account_label=labels.get("relayLabel"),
                relay_account_source=labels.get("relaySource"),
                metadata={
                    "recordSource": "hermes_sessions_list_json",
                    "providerSessionIdentity": _hermes_session_identity(
                        session_id=session_id,
                        discovery_source="hermes_sessions_cli_json",
                        runtime_home=runtime_home,
                        runtime_home_source=runtime_home_source,
                        session_source=_first_text(item, ("source",)) or source_filter,
                        source_filter=source_filter,
                    ),
                },
            )
        )
        if len(records) >= limit:
            break
    return records


def _hermes_records_from_text(
    output: str,
    *,
    fallback_cwd: str | None,
    limit: int,
    current_session_id: str | None,
    runtime_home: Path | None = None,
    runtime_home_source: str = "provider_default_unknown",
    source_filter: str | None = None,
) -> list[AgentSessionDiscoveryRecord]:
    records: list[AgentSessionDiscoveryRecord] = []
    seen: set[str] = set()
    for line in output.splitlines():
        for pattern in _HERMES_SESSION_ID_RES:
            match = pattern.search(line)
            if match is None:
                continue
            session_id = match.group(0)
            if session_id in seen:
                continue
            seen.add(session_id)
            cwd, cwd_source = _resolved_record_cwd(_cwd_from_text(line), fallback_cwd)
            records.append(
                AgentSessionDiscoveryRecord(
                    agent_runtime="hermes",
                    session_id=session_id,
                    cwd=cwd,
                    cwd_source=cwd_source,
                    source_path=None,
                    source_kind="hermes_sessions_cli_text",
                    updated_at=None,
                    confidence="medium",
                    current_session_match=(
                        session_id == current_session_id
                        if current_session_id is not None
                        else None
                    ),
                    metadata={
                        "recordSource": "hermes_sessions_list_text",
                        "providerSessionIdentity": _hermes_session_identity(
                            session_id=session_id,
                            discovery_source="hermes_sessions_cli_text",
                            runtime_home=runtime_home,
                            runtime_home_source=runtime_home_source,
                            session_source=source_filter,
                            source_filter=source_filter,
                        ),
                    },
                )
            )
            break
        if len(records) >= limit:
            break
    return records


def _read_jsonl_session_values(
    path: Path,
    *,
    include_turn_snippets: bool,
    include_full_session_history: bool,
    snippet_turn_index: int | None,
    snippet_max_chars: int,
) -> dict[str, object]:
    session_id: str | None = None
    cwd: str | None = None
    updated_at: str | None = None
    provider_account_label: str | None = None
    provider_account_source: str | None = None
    vendor_account_label: str | None = None
    vendor_account_source: str | None = None
    relay_account_label: str | None = None
    relay_account_source: str | None = None
    messages: list[Mapping[str, object]] = []
    full_history_messages: list[Mapping[str, object]] = []
    full_history_char_count = 0
    full_history_truncation_reason: str | None = None
    scan = _scan_jsonl_objects(path, limit=_JSONL_SCAN_LINE_LIMIT)
    for payload in scan.records:
        session_id = session_id or _first_text(
            payload,
            (
                "session_id",
                "sessionId",
                "claudeSessionUuid",
                "codexSessionId",
                "hermesSessionId",
                "id",
            ),
        )
        cwd = cwd or _first_text(
            payload,
            ("cwd", "workdir", "workspaceRoot", "projectDir", "projectCwd"),
        )
        updated_at = updated_at or _first_text(
            payload,
            ("updated_at", "updatedAt", "timestamp", "createdAt"),
        )
        labels = _account_labels(payload)
        if provider_account_label is None and labels.get("providerLabel") is not None:
            provider_account_label = str(labels["providerLabel"])
            provider_account_source = str(labels["providerSource"])
        if vendor_account_label is None and labels.get("vendorLabel") is not None:
            vendor_account_label = str(labels["vendorLabel"])
            vendor_account_source = str(labels["vendorSource"])
        if relay_account_label is None and labels.get("relayLabel") is not None:
            relay_account_label = str(labels["relayLabel"])
            relay_account_source = str(labels["relaySource"])
        if include_turn_snippets or include_full_session_history:
            role, content = _message_role_and_content(payload)
            if role is not None and content is not None:
                if include_turn_snippets:
                    messages.append(
                        _bounded_message(
                            role=role,
                            content=content,
                            max_chars=snippet_max_chars,
                        )
                    )
                if include_full_session_history:
                    if len(full_history_messages) >= _FULL_HISTORY_MAX_MESSAGES:
                        full_history_truncation_reason = (
                            full_history_truncation_reason
                            or "full_history_message_limit"
                        )
                    else:
                        remaining_chars = (
                            _FULL_HISTORY_MAX_CHARS - full_history_char_count
                        )
                        if remaining_chars <= 0:
                            full_history_truncation_reason = (
                                full_history_truncation_reason
                                or "full_history_character_limit"
                            )
                        else:
                            bounded_content = content[:remaining_chars]
                            message: dict[str, object] = {
                                "role": role,
                                "text": bounded_content,
                                "charCount": len(bounded_content),
                            }
                            if len(bounded_content) < len(content):
                                message.update(
                                    {
                                        "truncated": True,
                                        "originalCharCount": len(content),
                                    }
                                )
                                full_history_truncation_reason = (
                                    full_history_truncation_reason
                                    or "full_history_character_limit"
                                )
                            full_history_messages.append(message)
                            full_history_char_count += len(bounded_content)
        if (
            session_id
            and cwd
            and provider_account_label is not None
            and vendor_account_label is not None
            and relay_account_label is not None
            and not include_turn_snippets
            and not include_full_session_history
        ):
            break
    turn_snippet = (
        _turn_snippet(
            messages,
            snippet_turn_index=snippet_turn_index,
            snippet_max_chars=snippet_max_chars,
        )
        if include_turn_snippets
        else None
    )
    session_history = (
        _session_history(
            full_history_messages,
            scan=scan,
            history_truncation_reason=full_history_truncation_reason,
        )
        if include_full_session_history
        else None
    )
    return {
        key: value
        for key, value in (
            ("session_id", session_id),
            ("cwd", cwd),
            ("updated_at", updated_at),
            ("provider_account_label", provider_account_label),
            ("provider_account_source", provider_account_source),
            ("vendor_account_label", vendor_account_label),
            ("vendor_account_source", vendor_account_source),
            ("relay_account_label", relay_account_label),
            ("relay_account_source", relay_account_source),
            ("turn_snippet", turn_snippet),
            ("session_history", session_history),
            (
                "jsonl_scan",
                {
                    "scannedLineCount": scan.scanned_line_count,
                    "scannedByteCount": scan.scanned_byte_count,
                    "truncated": scan.truncated,
                    "truncationReason": scan.truncation_reason,
                    "lineMaxBytes": _JSONL_LINE_MAX_BYTES,
                    "nestingMaxDepth": _JSON_NESTING_MAX_DEPTH,
                },
            ),
        )
        if value is not None
    }


def _iter_jsonl_objects(path: Path, *, limit: int) -> Sequence[Mapping[str, object]]:
    return _scan_jsonl_objects(path, limit=limit).records


def _scan_jsonl_objects(path: Path, *, limit: int) -> _JsonlScanResult:
    records: list[Mapping[str, object]] = []
    scanned_line_count = 0
    scanned_byte_count = 0
    truncated = False
    truncation_reason: str | None = None
    with path.open("rb") as stream:
        while scanned_line_count < limit:
            raw_line = stream.readline(_JSONL_LINE_MAX_BYTES + 1)
            if not raw_line:
                break
            scanned_line_count += 1
            scanned_byte_count += len(raw_line)
            if len(raw_line) > _JSONL_LINE_MAX_BYTES:
                truncated = True
                truncation_reason = truncation_reason or "jsonl_line_byte_limit"
                while raw_line and not raw_line.endswith(b"\n"):
                    raw_line = stream.readline(_JSONL_LINE_MAX_BYTES + 1)
                    scanned_byte_count += len(raw_line)
                continue
            try:
                payload = json.loads(raw_line.decode("utf-8", errors="replace"))
            except (json.JSONDecodeError, RecursionError):
                continue
            if isinstance(payload, Mapping):
                records.append(payload)
        if scanned_line_count >= limit and stream.read(1):
            truncated = True
            truncation_reason = truncation_reason or "jsonl_scan_line_limit"
    return _JsonlScanResult(
        records=tuple(records),
        scanned_line_count=scanned_line_count,
        scanned_byte_count=scanned_byte_count,
        truncated=truncated,
        truncation_reason=truncation_reason,
    )


def _first_text(
    value: object,
    keys: tuple[str, ...],
    *,
    depth: int = 0,
) -> str | None:
    if depth >= _JSON_NESTING_MAX_DEPTH:
        return None
    if isinstance(value, Mapping):
        for key in keys:
            candidate = _as_text(value.get(key))
            if candidate:
                return candidate
        for nested in value.values():
            candidate = _first_text(nested, keys, depth=depth + 1)
            if candidate:
                return candidate
    if isinstance(value, list):
        for nested in value:
            candidate = _first_text(nested, keys, depth=depth + 1)
            if candidate:
                return candidate
    return None


def _account_labels(value: object) -> dict[str, str]:
    provider_label, provider_source = _label_from_keys(
        value,
        (
            "providerAccountLabel",
            "providerAccountId",
            "accountLabel",
            "accountName",
            "profileName",
            "profile",
            "account",
        ),
    )
    vendor_label, vendor_source = _label_from_keys(
        value,
        (
            "vendorAccountLabel",
            "vendorAccountId",
            "vendorAccount",
            "organization",
            "organizationId",
            "orgId",
            "orgName",
            "workspaceAccountLabel",
        ),
    )
    relay_label, relay_source = _label_from_keys(
        value,
        (
            "relayAccountLabel",
            "relayAccountId",
            "relayAccount",
            "relayProfile",
            "gatewayProfile",
            "proxyProfile",
            "sourceTag",
        ),
    )
    return {
        key: label
        for key, label in (
            ("providerLabel", provider_label),
            ("providerSource", provider_source),
            ("vendorLabel", vendor_label),
            ("vendorSource", vendor_source),
            ("relayLabel", relay_label),
            ("relaySource", relay_source),
        )
        if label is not None
    }


def _label_from_keys(
    value: object,
    keys: tuple[str, ...],
    *,
    depth: int = 0,
) -> tuple[str | None, str | None]:
    if depth >= _JSON_NESTING_MAX_DEPTH or not isinstance(value, Mapping):
        return None, None
    for key in keys:
        candidate = _as_text(value.get(key))
        if candidate:
            return _truncate(candidate, 96), key
    for nested in value.values():
        label, source = _label_from_keys(nested, keys, depth=depth + 1)
        if label is not None:
            return label, source
    return None, None


def _account_labels_payload(
    *,
    provider_label: str | None,
    provider_source: str | None,
    vendor_label: str | None,
    vendor_source: str | None,
    relay_label: str | None,
    relay_source: str | None,
) -> Mapping[str, object]:
    payload: dict[str, object] = {}
    for key, label, source in (
        ("provider", provider_label, provider_source),
        ("vendor", vendor_label, vendor_source),
        ("relay", relay_label, relay_source),
    ):
        if label is not None:
            payload[key] = {
                "label": label,
                "source": source,
                "accountType": f"{key}_account",
            }
    return payload


def _message_role_and_content(value: object) -> tuple[str | None, str | None]:
    if not isinstance(value, Mapping):
        return None, None
    role = _message_role(value)
    content = _message_content_text(value)
    if role is None or content is None:
        return None, None
    return role, content


def _message_role(
    value: Mapping[str, object],
    *,
    depth: int = 0,
) -> str | None:
    if depth >= _JSON_NESTING_MAX_DEPTH:
        return None
    for key in ("role", "type"):
        candidate = _as_text(value.get(key))
        if candidate in ("user", "assistant"):
            return candidate
    message = value.get("message")
    if isinstance(message, Mapping):
        candidate = _as_text(message.get("role"))
        if candidate in ("user", "assistant"):
            return candidate
    payload = value.get("payload")
    if isinstance(payload, Mapping):
        candidate = _message_role(payload, depth=depth + 1)
        if candidate is not None:
            return candidate
    return None


def _message_content_text(value: object, *, depth: int = 0) -> str | None:
    if depth >= _JSON_NESTING_MAX_DEPTH:
        return None
    if isinstance(value, str):
        return _as_text(value)
    if isinstance(value, Mapping):
        for key in ("content", "text", "outputText", "output_text"):
            candidate = _message_content_text(value.get(key), depth=depth + 1)
            if candidate is not None:
                return candidate
        for key in ("message", "payload"):
            candidate = _message_content_text(value.get(key), depth=depth + 1)
            if candidate is not None:
                return candidate
    if isinstance(value, list):
        parts = [
            part
            for item in value
            if (part := _message_content_text(item, depth=depth + 1)) is not None
        ]
        if parts:
            return "\n".join(parts)
    return None


def _bounded_message(
    *,
    role: str,
    content: str,
    max_chars: int,
) -> Mapping[str, object]:
    bounded = _truncate(content, max_chars)
    return {
        "role": role,
        "text": bounded,
        "maxChars": max_chars,
        "truncated": len(bounded) < len(content),
        "originalCharCount": len(content),
    }


def _turn_snippet(
    messages: Sequence[Mapping[str, object]],
    *,
    snippet_turn_index: int | None,
    snippet_max_chars: int,
) -> Mapping[str, object] | None:
    turns: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for message in messages:
        role = _as_text(message.get("role"))
        content = _as_text(message.get("text"))
        if role is None or content is None:
            continue
        bounded = dict(message)
        if role == "user":
            current = {
                "turnIndex": len(turns) + 1,
                "messages": [bounded],
                "user": content,
            }
            turns.append(current)
            continue
        if role == "assistant":
            if current is None:
                current = {"turnIndex": len(turns) + 1, "messages": []}
                turns.append(current)
            current_messages = current.setdefault("messages", [])
            if isinstance(current_messages, list):
                current_messages.append(bounded)
            current["assistant"] = content
    if not turns:
        return None
    selected = (
        next(
            (
                turn
                for turn in turns
                if turn.get("turnIndex") == snippet_turn_index
            ),
            None,
        )
        if snippet_turn_index is not None
        else turns[-1]
    )
    if selected is None:
        return {
            "schema": "agent_session_turn_snippet.v1",
            "available": False,
            "requestedTurnIndex": snippet_turn_index,
            "observedTurnCount": len(turns),
            "snippetMaxChars": snippet_max_chars,
        }
    return {
        "schema": "agent_session_turn_snippet.v1",
        "available": True,
        "selection": "explicit_turn_index"
        if snippet_turn_index is not None
        else "latest_observed_turn",
        "observedTurnCount": len(turns),
        "snippetMaxChars": snippet_max_chars,
        **dict(selected),
    }


def _session_history(
    messages: Sequence[Mapping[str, object]],
    *,
    scan: _JsonlScanResult,
    history_truncation_reason: str | None,
) -> Mapping[str, object]:
    reasons = tuple(
        dict.fromkeys(
            reason
            for reason in (scan.truncation_reason, history_truncation_reason)
            if reason is not None
        )
    )
    return {
        "schema": "agent_session_history.v1",
        "readMode": "explicit_opt_in",
        "boundedByJsonlScanLineLimit": _JSONL_SCAN_LINE_LIMIT,
        "maxMessageCount": _FULL_HISTORY_MAX_MESSAGES,
        "maxCharacterCount": _FULL_HISTORY_MAX_CHARS,
        "messageCount": len(messages),
        "characterCount": sum(
            int(message.get("charCount", 0)) for message in messages
        ),
        "scannedLineCount": scan.scanned_line_count,
        "scannedByteCount": scan.scanned_byte_count,
        "truncated": bool(reasons),
        "truncationReason": ",".join(reasons) if reasons else None,
        "messages": [dict(message) for message in messages],
    }


def _json_object_from_values(
    values: Mapping[str, object],
    key: str,
) -> Mapping[str, object] | None:
    value = values.get(key)
    return value if isinstance(value, Mapping) else None


def _jsonl_files(root: Path) -> Sequence[Path]:
    if not root.exists():
        return ()
    paths: list[Path] = []
    for current_root, directory_names, file_names in os.walk(root):
        current = Path(current_root)
        depth = len(current.relative_to(root).parts)
        if depth >= _JSONL_PATH_MAX_DEPTH:
            directory_names[:] = []
        paths.extend(
            current / file_name
            for file_name in file_names
            if file_name.endswith(".jsonl")
        )
    return tuple(paths)


def _newest_files(paths: Sequence[Path]) -> Sequence[Path]:
    return tuple(sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True))


def _home_path(configured_home: str | None, default_leaf: str) -> Path:
    if configured_home:
        return Path(configured_home)
    return Path.home() / default_leaf


def _session_id_from_filename(path: Path) -> str | None:
    uuid_match = _UUID_RE.search(path.stem)
    if uuid_match is not None:
        return uuid_match.group(0)
    if path.stem.strip():
        return path.stem.strip()
    return None


def _cwd_from_text(line: str) -> str | None:
    for token in re.split(r"\s{2,}|\t|\|", line):
        stripped = token.strip()
        if not stripped:
            continue
        if Path(stripped).is_dir():
            return str(Path(stripped))
    return None


def _resolved_record_cwd(
    discovered_cwd: str | None,
    fallback_cwd: str | None,
) -> tuple[str | None, str | None]:
    resolved = _resolved_cwd(discovered_cwd)
    if resolved is not None:
        return resolved, "discovered"
    if fallback_cwd is not None:
        return fallback_cwd, "fallback"
    return None, None


def _resolved_cwd(cwd: str | None) -> str | None:
    candidate = _as_text(cwd)
    if not candidate:
        return None
    return str(Path(candidate))


def _registration_missing_fields(
    agent_runtime: str,
    session_id: str | None,
    cwd: str | None,
) -> list[str]:
    missing: list[str] = []
    if not _as_text(session_id):
        missing.append(PROVIDER_SESSION_FIELD_BY_RUNTIME[agent_runtime])
    elif agent_runtime == "claude" and not _is_uuid(session_id):
        missing.append("claudeSessionUuid.uuid")
    if not _as_text(cwd):
        missing.append("cwd")
    elif not Path(str(cwd)).is_dir():
        missing.append("cwd.existingDirectory")
    return missing


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except (TypeError, ValueError):
        return False
    return True


def _dedupe_records(
    records: Sequence[AgentSessionDiscoveryRecord],
) -> list[AgentSessionDiscoveryRecord]:
    deduped: dict[tuple[str, str], AgentSessionDiscoveryRecord] = {}
    for record in records:
        key = (record.agent_runtime, record.session_id)
        previous = deduped.get(key)
        if previous is None or _record_score(record) > _record_score(previous):
            deduped[key] = record
    return list(deduped.values())


def _account_label_filter(
    *,
    provider_account_label: str | None,
    vendor_account_label: str | None,
    relay_account_label: str | None,
) -> Mapping[str, object]:
    filters = {
        key: value
        for key, value in (
            ("provider", _as_text(provider_account_label)),
            ("vendor", _as_text(vendor_account_label)),
            ("relay", _as_text(relay_account_label)),
        )
        if value is not None
    }
    return {
        "active": bool(filters),
        "labels": filters,
        "matchMode": "case_insensitive_exact",
        "accountLabelBoundary": (
            "Filters match provider-side, vendor-side, or relay profile labels "
            "only. They never inspect local OS user account names."
        ),
    }


def _record_matches_account_filter(
    record: AgentSessionDiscoveryRecord,
    account_filter: Mapping[str, object],
) -> bool:
    labels = account_filter.get("labels")
    if not isinstance(labels, Mapping) or not labels:
        return True
    record_labels = {
        "provider": record.provider_account_label,
        "vendor": record.vendor_account_label,
        "relay": record.relay_account_label,
    }
    for key, wanted in labels.items():
        candidate = record_labels.get(str(key))
        if candidate is None:
            return False
        if candidate.casefold() != str(wanted).casefold():
            return False
    return True


def _record_score(record: AgentSessionDiscoveryRecord) -> tuple[int, str]:
    ready_score = int(not _registration_missing_fields(
        record.agent_runtime,
        record.session_id,
        record.cwd,
    ))
    confidence_score = {"high": 3, "medium": 2, "low": 1}.get(record.confidence, 0)
    return (ready_score + confidence_score, record.updated_at or "")


def _path_updated_at(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def _normalize_discovery_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized == "all":
        return normalized
    return _normalize_agent_runtime(normalized)


def _normalize_agent_runtime(provider: str) -> str:
    normalized = provider.strip().lower()
    aliases = {
        "claude": "claude",
        "claude-code": "claude",
        "codex": "codex",
        "codex-cli": "codex",
        "hermes": "hermes",
        "hermes-cli": "hermes",
    }
    if normalized not in aliases:
        raise ValueError(
            "provider must be one of: all, claude, codex, hermes."
        )
    return aliases[normalized]


def _positive_limit(limit: int) -> int:
    if limit <= 0:
        raise ValueError("limit must be greater than zero.")
    return limit


def _optional_positive_int(value: int | None, logical_name: str) -> int | None:
    if value is None:
        return None
    if value <= 0:
        raise ValueError(f"{logical_name} must be greater than zero.")
    return value


def _required_text(value: str, logical_name: str) -> str:
    cleaned = _as_text(value)
    if cleaned is None:
        raise ValueError(f"{logical_name} is required.")
    return cleaned


def _as_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: max(limit - 3, 0)] + "..."


def _tail_text(value: str, limit: int = 1200) -> str | None:
    if not value:
        return None
    return value[-limit:]


def _discovery_error(
    provider: str,
    category: str,
    message: str,
    *,
    command_argv: Sequence[str] | None = None,
    command_exit_code: int | None = None,
    stdout_tail: str | None = None,
    stderr_tail: str | None = None,
) -> Mapping[str, object]:
    payload: dict[str, object] = {
        "schema": AGENT_SESSION_DISCOVERY_ERROR_SCHEMA,
        "agentRuntime": provider,
        "provider": PROVIDER_BY_RUNTIME.get(provider, provider),
        "failureCategory": category,
        "message": message,
    }
    if command_argv is not None:
        payload["commandArgvSummary"] = list(command_argv)
    if command_exit_code is not None:
        payload["commandExitCode"] = command_exit_code
    if stdout_tail is not None:
        payload["stdoutTail"] = stdout_tail
    if stderr_tail is not None:
        payload["stderrTail"] = stderr_tail
    return payload
