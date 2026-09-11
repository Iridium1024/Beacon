from __future__ import annotations

from collections import deque
from collections.abc import Mapping as MappingABC, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import platform
import queue
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import BinaryIO, Mapping
from uuid import uuid4


DEEPSEEK_HARNESS_AUDITED_COMMIT = (
    "b150a551b8d465e31e418e1b2eaf5e79bbb7d28e"
)
DEEPSEEK_HARNESS_NPM_VERSION = "0.1.1-rc.2"
DEEPSEEK_HARNESS_PYPI_VERSION = "0.1.1rc1"
DEEPSEEK_HARNESS_SERVER_NAME = "deepseek-harness-sdk-runtime"
DEEPSEEK_HARNESS_BACKEND_ID = "deepseek_harness_sdk_stdio"

_DSH_NOTIFICATION_METHODS = {
    "session.event",
    "session.status",
    "subagent.started",
    "subagent.finished",
}
_DSH_REQUEST_METHODS = {"initialize", "session/prompt", "shutdown"}
_SUCCESSFUL_TURN_END_KINDS = {"completed"}
_RESET_EVENT_MARKERS = ("reset", "recreate", "generation")
_MAX_IPC_BYTES = 1024 * 1024


class DeepSeekHarnessRuntimeError(RuntimeError):
    """Base failure for the Beacon-owned DSH runtime boundary."""


class DeepSeekHarnessPreflightError(DeepSeekHarnessRuntimeError):
    """The configured carrier does not match the exact audited contract."""


class DeepSeekHarnessProtocolError(DeepSeekHarnessRuntimeError):
    """The DSH peer violated the fixed JSON-RPC/package contract."""


class DeepSeekHarnessContinuityError(DeepSeekHarnessRuntimeError):
    """The owned runtime generation cannot safely continue its session."""


class DeepSeekHarnessDeliveryError(DeepSeekHarnessRuntimeError):
    def __init__(self, message: str, *, ambiguous_delivery: bool) -> None:
        super().__init__(message)
        self.ambiguous_delivery = ambiguous_delivery


@dataclass(frozen=True, slots=True)
class DeepSeekHarnessRuntimePaths:
    state_directory: str
    spec_path: str
    state_path: str
    token_path: str
    owner_lease_path: str
    operation_lease_path: str
    session_owner_lease_path: str

    @classmethod
    def create(
        cls,
        state_root: str | Path,
        runtime_id: str,
        *,
        session_root: str | Path,
        session_id: str,
    ) -> "DeepSeekHarnessRuntimePaths":
        state = Path(state_root).expanduser().resolve(strict=False)
        root = state / runtime_id
        canonical_session_root = os.path.normcase(
            str(Path(session_root).expanduser().resolve(strict=False))
        )
        owner_key = hashlib.sha256(
            (canonical_session_root + "\0" + session_id).encode("utf-8")
        ).hexdigest()
        return cls(
            state_directory=str(root),
            spec_path=str(root / "runtime-spec.json"),
            state_path=str(root / "runtime-state.json"),
            token_path=str(root / "owner-token"),
            owner_lease_path=str(root / "owner.lease"),
            operation_lease_path=str(root / "operation.lease"),
            session_owner_lease_path=str(
                state / "session-owners" / f"{owner_key}.lease"
            ),
        )

    def to_metadata(self) -> Mapping[str, object]:
        return {
            "stateDirectory": self.state_directory,
            "specPath": self.spec_path,
            "statePath": self.state_path,
            "tokenPath": self.token_path,
            "ownerLeasePath": self.owner_lease_path,
            "operationLeasePath": self.operation_lease_path,
            "sessionOwnerLeasePath": self.session_owner_lease_path,
        }


@dataclass(frozen=True, slots=True)
class DeepSeekHarnessRuntimeSpec:
    runtime_id: str
    generation_id: str
    owner_nonce: str
    workspace_id: str
    agent_id: str
    handle_id: str
    dsh_session_id: str
    session_start_mode: str
    session_compression: str
    cwd: str
    session_root: str
    runtime_home: str
    runtime_home_source: str
    carrier: str
    executable_path: str
    launch_args: tuple[str, ...]
    cordis_config_path: str | None
    package_root: str
    package_version: str
    package_commit: str
    expected_server_version: str
    model_provider: str
    model: str
    paths: DeepSeekHarnessRuntimePaths
    initialize_timeout_seconds: float = 30.0
    operation_timeout_seconds: float = 120.0
    shutdown_timeout_seconds: float = 5.0
    max_line_bytes: int = 1024 * 1024
    max_total_output_bytes: int = 32 * 1024 * 1024
    max_stderr_bytes: int = 64 * 1024
    reply_writeback_mode: str = "explicit_only"
    created_at: str = field(default_factory=lambda: _utc_now().isoformat())

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, object],
    ) -> "DeepSeekHarnessRuntimeSpec":
        dsh_session_id = _required_text(value, "dshSessionId", "dsh_session_id")
        session_root = _required_text(value, "sessionRoot", "session_root")
        paths_value = value.get("paths")
        if not isinstance(paths_value, MappingABC):
            raise ValueError("DeepSeek Harness runtime spec paths are required.")
        state_directory = _required_text(
            paths_value, "state_directory", "stateDirectory"
        )
        session_owner_lease_path = _optional_text(
            paths_value, "session_owner_lease_path", "sessionOwnerLeasePath"
        )
        if session_owner_lease_path is None:
            state_root = Path(state_directory).parent
            session_owner_lease_path = DeepSeekHarnessRuntimePaths.create(
                state_root,
                _required_text(value, "runtimeId", "runtime_id"),
                session_root=session_root,
                session_id=dsh_session_id,
            ).session_owner_lease_path
        paths = DeepSeekHarnessRuntimePaths(
            state_directory=state_directory,
            spec_path=_required_text(paths_value, "spec_path", "specPath"),
            state_path=_required_text(paths_value, "state_path", "statePath"),
            token_path=_required_text(paths_value, "token_path", "tokenPath"),
            owner_lease_path=_required_text(
                paths_value,
                "owner_lease_path",
                "ownerLeasePath",
            ),
            operation_lease_path=_required_text(
                paths_value,
                "operation_lease_path",
                "operationLeasePath",
            ),
            session_owner_lease_path=session_owner_lease_path,
        )
        launch_args = value.get("launchArgs", value.get("launch_args"))
        if not isinstance(launch_args, Sequence) or isinstance(
            launch_args,
            (str, bytes),
        ):
            raise ValueError("DeepSeek Harness launchArgs must be a JSON array.")
        return cls(
            runtime_id=_required_text(value, "runtimeId", "runtime_id"),
            generation_id=_required_text(value, "generationId", "generation_id"),
            owner_nonce=_required_text(value, "ownerNonce", "owner_nonce"),
            workspace_id=_required_text(value, "workspaceId", "workspace_id"),
            agent_id=_required_text(value, "agentId", "agent_id"),
            handle_id=_required_text(value, "handleId", "handle_id"),
            dsh_session_id=dsh_session_id,
            session_start_mode=str(
                value.get("sessionStartMode", value.get("session_start_mode", "create"))
            ),
            session_compression=str(
                value.get("sessionCompression", value.get("session_compression", "zstd"))
            ),
            cwd=_required_text(value, "cwd"),
            session_root=session_root,
            runtime_home=_required_text(value, "runtimeHome", "runtime_home"),
            runtime_home_source=_required_text(
                value,
                "runtimeHomeSource",
                "runtime_home_source",
            ),
            carrier=_required_text(value, "carrier"),
            executable_path=_required_text(
                value,
                "executablePath",
                "executable_path",
            ),
            launch_args=tuple(_require_argv(launch_args)),
            cordis_config_path=(
                str(value["cordisConfigPath"]).strip()
                if isinstance(value.get("cordisConfigPath"), str)
                and str(value["cordisConfigPath"]).strip()
                else None
            ),
            package_root=_required_text(value, "packageRoot", "package_root"),
            package_version=_required_text(
                value,
                "packageVersion",
                "package_version",
            ),
            package_commit=_required_text(
                value,
                "packageCommit",
                "package_commit",
            ),
            expected_server_version=_required_text(
                value,
                "expectedServerVersion",
                "expected_server_version",
            ),
            model_provider=_required_text(value, "modelProvider", "model_provider"),
            model=_required_text(value, "model"),
            paths=paths,
            initialize_timeout_seconds=_positive_float(
                value.get("initializeTimeoutSeconds", 30.0),
                "initializeTimeoutSeconds",
            ),
            operation_timeout_seconds=_positive_float(
                value.get("operationTimeoutSeconds", 120.0),
                "operationTimeoutSeconds",
            ),
            shutdown_timeout_seconds=_positive_float(
                value.get("shutdownTimeoutSeconds", 5.0),
                "shutdownTimeoutSeconds",
            ),
            max_line_bytes=_positive_int(
                value.get("maxLineBytes", 1024 * 1024),
                "maxLineBytes",
            ),
            max_total_output_bytes=_positive_int(
                value.get("maxTotalOutputBytes", 32 * 1024 * 1024),
                "maxTotalOutputBytes",
            ),
            max_stderr_bytes=_positive_int(
                value.get("maxStderrBytes", 64 * 1024),
                "maxStderrBytes",
            ),
            reply_writeback_mode=_reply_mode(
                value.get("replyWritebackMode", "explicit_only")
            ),
            created_at=_required_text(value, "createdAt", "created_at"),
        )

    def __post_init__(self) -> None:
        for logical_name, value in (
            ("runtimeId", self.runtime_id),
            ("generationId", self.generation_id),
            ("ownerNonce", self.owner_nonce),
            ("workspaceId", self.workspace_id),
            ("agentId", self.agent_id),
            ("handleId", self.handle_id),
            ("dshSessionId", self.dsh_session_id),
        ):
            _validate_identity_text(value, logical_name)
        if self.carrier not in {"node", "python", "fixture"}:
            raise ValueError("carrier must be one of: node, python, fixture.")
        if self.session_start_mode not in {"create", "resume"}:
            raise ValueError("sessionStartMode must be create or resume.")
        if self.session_compression not in {"zstd", "none"}:
            raise ValueError("sessionCompression must be zstd or none.")
        if self.reply_writeback_mode not in {
            "explicit_only",
            "provider_final_capture",
        }:
            raise ValueError(
                "replyWritebackMode must be explicit_only or provider_final_capture."
            )
        if not self.launch_args:
            raise ValueError("launchArgs must not be empty.")
        if Path(self.executable_path).resolve(strict=False) != Path(
            self.launch_args[0]
        ).resolve(strict=False):
            raise ValueError("executablePath must match launchArgs[0].")
        for logical_name, raw_path in (
            ("cwd", self.cwd),
            ("sessionRoot", self.session_root),
            ("runtimeHome", self.runtime_home),
            ("packageRoot", self.package_root),
        ):
            if not Path(raw_path).is_absolute():
                raise ValueError(f"{logical_name} must be an absolute path.")
        if self.cordis_config_path is not None and not Path(
            self.cordis_config_path
        ).is_absolute():
            raise ValueError("cordisConfigPath must be an absolute path.")

    def to_mapping(self) -> Mapping[str, object]:
        return {
            "schema": "deepseek_harness_runtime_spec.v1",
            "runtimeId": self.runtime_id,
            "generationId": self.generation_id,
            "ownerNonce": self.owner_nonce,
            "workspaceId": self.workspace_id,
            "agentId": self.agent_id,
            "handleId": self.handle_id,
            "dshSessionId": self.dsh_session_id,
            "sessionStartMode": self.session_start_mode,
            "sessionCompression": self.session_compression,
            "cwd": self.cwd,
            "sessionRoot": self.session_root,
            "runtimeHome": self.runtime_home,
            "runtimeHomeSource": self.runtime_home_source,
            "carrier": self.carrier,
            "executablePath": self.executable_path,
            "launchArgs": list(self.launch_args),
            "cordisConfigPath": self.cordis_config_path,
            "packageRoot": self.package_root,
            "packageVersion": self.package_version,
            "packageCommit": self.package_commit,
            "expectedServerVersion": self.expected_server_version,
            "modelProvider": self.model_provider,
            "model": self.model,
            "paths": {
                "stateDirectory": self.paths.state_directory,
                "specPath": self.paths.spec_path,
                "statePath": self.paths.state_path,
                "tokenPath": self.paths.token_path,
                "ownerLeasePath": self.paths.owner_lease_path,
                "operationLeasePath": self.paths.operation_lease_path,
                "sessionOwnerLeasePath": self.paths.session_owner_lease_path,
            },
            "initializeTimeoutSeconds": self.initialize_timeout_seconds,
            "operationTimeoutSeconds": self.operation_timeout_seconds,
            "shutdownTimeoutSeconds": self.shutdown_timeout_seconds,
            "maxLineBytes": self.max_line_bytes,
            "maxTotalOutputBytes": self.max_total_output_bytes,
            "maxStderrBytes": self.max_stderr_bytes,
            "replyWritebackMode": self.reply_writeback_mode,
            "createdAt": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class DeepSeekHarnessOperationResult:
    operation_id: str
    message_id: str
    final_response: str
    finish_reason: str
    final_classification: str
    trusted_final: bool
    receipt_watermark: int
    final_watermark: int
    idle_watermark: int
    notification_count: int
    descendant_notification_count: int
    pre_prompt_status: str

    def to_metadata(self, *, include_response: bool = True) -> Mapping[str, object]:
        result: dict[str, object] = {
            "schema": "deepseek_harness_operation_result.v1",
            "operationId": self.operation_id,
            "messageId": self.message_id,
            "finishReason": self.finish_reason,
            "finalClassification": self.final_classification,
            "trustedFinal": self.trusted_final,
            "receiptWatermark": self.receipt_watermark,
            "finalWatermark": self.final_watermark,
            "idleWatermark": self.idle_watermark,
            "notificationCount": self.notification_count,
            "descendantNotificationCount": self.descendant_notification_count,
            "prePromptStatus": self.pre_prompt_status,
        }
        if include_response:
            result["finalResponse"] = self.final_response
        return result


@dataclass(frozen=True, slots=True)
class _WireNotification:
    watermark: int
    method: str
    params: Mapping[str, object]


@dataclass(slots=True)
class _PendingResponse:
    result: "queue.Queue[object]" = field(default_factory=lambda: queue.Queue(maxsize=1))


class DeepSeekHarnessJsonRpcTransport:
    """Strict, bounded adapter for the public DSH SDK JSONL protocol.

    The official TypeScript transport intentionally ignores malformed and
    unknown frames. Beacon owns a long-lived runtime, so this adapter fails
    closed instead and binds the process to an exact audited package build.
    """

    def __init__(self, spec: DeepSeekHarnessRuntimeSpec) -> None:
        self.spec = spec
        self._proc: subprocess.Popen[bytes] | None = None
        self._pending: dict[int, _PendingResponse] = {}
        self._completed_ids: deque[int] = deque(maxlen=1024)
        self._completed_id_set: set[int] = set()
        self._next_request_id = 1
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._notifications: "queue.Queue[_WireNotification | BaseException]" = queue.Queue()
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._stderr_bytes = 0
        self._stderr_truncated = False
        self._total_output_bytes = 0
        self._watermark = 0
        self._fatal_error: BaseException | None = None
        self._initialized = False
        self._initialize_request_id: int | None = None
        self._initialize_response_seen = False
        self._last_status: dict[str, str] = {}
        self._started_at: float | None = None

    @property
    def process_id(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    @property
    def process(self) -> subprocess.Popen[bytes] | None:
        return self._proc

    @property
    def watermark(self) -> int:
        with self._lock:
            return self._watermark

    @property
    def stderr_bytes_observed(self) -> int:
        return self._stderr_bytes

    @property
    def stderr_truncated(self) -> bool:
        return self._stderr_truncated

    def last_status(self, session_id: str) -> str:
        with self._lock:
            return self._last_status.get(session_id, "unknown")

    def is_alive(self) -> bool:
        proc = self._proc
        return proc is not None and proc.poll() is None and self._fatal_error is None

    def start(self) -> Mapping[str, object]:
        if self._proc is not None:
            raise DeepSeekHarnessProtocolError("DSH transport start is single-use.")
        env = os.environ.copy()
        env["DSH_CWD"] = self.spec.cwd
        env["DSH_SESSION_ROOT"] = self.spec.session_root
        env["DSH_HOME"] = self.spec.runtime_home
        env["DSH_SESSION_ID"] = self.spec.dsh_session_id
        env["DSH_SESSION_START_MODE"] = self.spec.session_start_mode
        if self.spec.session_compression == "none":
            env["DSH_SNAPSHOT"] = "none"
        else:
            env.pop("DSH_SNAPSHOT", None)
        if self.spec.cordis_config_path is not None:
            env["DSH_CORDIS_CONFIG"] = self.spec.cordis_config_path
        creationflags = 0
        start_new_session = False
        if os.name == "nt":
            creationflags = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
        else:
            start_new_session = True
        try:
            self._proc = subprocess.Popen(
                list(self.spec.launch_args),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.spec.cwd,
                env=env,
                shell=False,
                creationflags=creationflags,
                start_new_session=start_new_session,
            )
        except OSError as exc:
            raise DeepSeekHarnessContinuityError(
                f"failed to start the configured DSH runtime: {exc.__class__.__name__}: {exc}"
            ) from exc
        self._started_at = time.time()
        self._reader = threading.Thread(
            target=self._reader_loop,
            name=f"beacon-dsh-reader-{self.spec.generation_id}",
            daemon=True,
        )
        self._stderr_reader = threading.Thread(
            target=self._stderr_loop,
            name=f"beacon-dsh-stderr-{self.spec.generation_id}",
            daemon=True,
        )
        self._reader.start()
        self._stderr_reader.start()
        try:
            result = self.request(
                "initialize",
                {
                    "cwd": self.spec.cwd,
                    "provider": self.spec.model_provider,
                    "model": self.spec.model,
                },
                timeout_seconds=self.spec.initialize_timeout_seconds,
            )
            if not isinstance(result, MappingABC):
                raise DeepSeekHarnessProtocolError(
                    "initialize result must be a JSON object."
                )
            server_info = result.get("serverInfo")
            if not isinstance(server_info, MappingABC):
                raise DeepSeekHarnessProtocolError(
                    "initialize result requires serverInfo."
                )
            server_name = server_info.get("name")
            server_version = server_info.get("version")
            if server_name != DEEPSEEK_HARNESS_SERVER_NAME:
                raise DeepSeekHarnessProtocolError(
                    "initialize serverInfo.name does not match the DSH SDK runtime."
                )
            if server_version != self.spec.expected_server_version:
                raise DeepSeekHarnessProtocolError(
                    "initialize serverInfo.version does not match the exact configured package."
                )
            with self._lock:
                self._initialized = True
            return {
                "serverName": server_name,
                "serverVersion": server_version,
                "processId": self.process_id,
                "processStartedAt": self._started_at,
            }
        except BaseException:
            self.force_terminate()
            raise

    def request(
        self,
        method: str,
        params: Mapping[str, object] | None,
        *,
        timeout_seconds: float,
    ) -> object:
        if method not in _DSH_REQUEST_METHODS:
            raise DeepSeekHarnessProtocolError(f"unsupported DSH request method: {method}")
        with self._lock:
            if self._fatal_error is not None:
                raise DeepSeekHarnessContinuityError(str(self._fatal_error))
            request_id = self._next_request_id
            self._next_request_id += 1
            pending = _PendingResponse()
            self._pending[request_id] = pending
            if method == "initialize":
                self._initialize_request_id = request_id
        frame: dict[str, object] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            frame["params"] = dict(params)
        sent = False
        try:
            self._write_frame(frame)
            sent = True
            item = pending.result.get(timeout=timeout_seconds)
        except queue.Empty as exc:
            with self._lock:
                self._pending.pop(request_id, None)
            raise DeepSeekHarnessDeliveryError(
                f"{method} timed out waiting for the DSH runtime.",
                ambiguous_delivery=method == "session/prompt" and sent,
            ) from exc
        except BaseException as exc:
            with self._lock:
                self._pending.pop(request_id, None)
            if isinstance(exc, DeepSeekHarnessRuntimeError):
                raise
            raise DeepSeekHarnessDeliveryError(
                f"{method} failed while writing to the DSH runtime: {exc}",
                ambiguous_delivery=method == "session/prompt" and sent,
            ) from exc
        if isinstance(item, BaseException):
            if method == "session/prompt":
                raise DeepSeekHarnessDeliveryError(
                    f"session/prompt transport failed: {item}",
                    ambiguous_delivery=sent,
                ) from item
            raise item
        if not isinstance(item, MappingABC):
            raise DeepSeekHarnessProtocolError(
                f"{method} response must be a JSON object."
            )
        if "error" in item:
            error = item.get("error")
            raise DeepSeekHarnessProtocolError(
                f"{method} returned JSON-RPC error: {_json_error_summary(error)}"
            )
        if "result" not in item:
            raise DeepSeekHarnessProtocolError(
                f"{method} response omitted result."
            )
        return item.get("result")

    def run_operation(
        self,
        *,
        operation_id: str,
        session_id: str,
        message: str,
        timeout_seconds: float | None = None,
    ) -> DeepSeekHarnessOperationResult:
        if not message.strip():
            raise ValueError("DSH prompt message is required.")
        if len(message.encode("utf-8")) > self.spec.max_line_bytes // 2:
            raise ValueError("DSH prompt exceeds the configured bounded input size.")
        with self._lock:
            if not self._initialized:
                raise DeepSeekHarnessContinuityError("DSH runtime is not initialized.")
            baseline = self._watermark
            pre_status = self._last_status.get(session_id, "unknown")
        result = self.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "contentBlocks": [{"type": "text", "text": message}],
            },
            timeout_seconds=min(
                timeout_seconds or self.spec.operation_timeout_seconds,
                self.spec.operation_timeout_seconds,
            ),
        )
        if not isinstance(result, MappingABC):
            raise DeepSeekHarnessProtocolError(
                "session/prompt result must be a JSON object."
            )
        message_id = result.get("messageId")
        if not isinstance(message_id, str) or not message_id.strip():
            raise DeepSeekHarnessProtocolError(
                "session/prompt result requires a durable messageId receipt."
            )
        deadline = time.monotonic() + (
            timeout_seconds or self.spec.operation_timeout_seconds
        )
        receipt_watermark = 0
        final_watermark = 0
        idle_watermark = 0
        notification_count = 0
        descendant_count = 0
        receipt_seen = False
        turn_end_kind: str | None = None
        turn_end_seen = False
        assistant_candidates: list[tuple[str, str, int]] = []
        assistant_ids: set[str] = set()
        descendant_sessions: set[str] = set()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DeepSeekHarnessContinuityError(
                    "DSH operation timed out after prompt receipt; delivery is ambiguous and continuity is lost."
                )
            try:
                item = self._notifications.get(timeout=remaining)
            except queue.Empty as exc:
                raise DeepSeekHarnessContinuityError(
                    "DSH operation timed out waiting for receipt-to-idle evidence."
                ) from exc
            if isinstance(item, BaseException):
                raise DeepSeekHarnessContinuityError(str(item)) from item
            if item.watermark <= baseline:
                continue
            notification_count += 1
            method = item.method
            params = item.params
            if method == "subagent.started":
                parent = params.get("parentSessionId")
                child = params.get("childSessionId")
                if parent == session_id and isinstance(child, str):
                    descendant_sessions.add(child)
                descendant_count += 1
                continue
            if method == "subagent.finished":
                descendant_count += 1
                continue
            notification_session = params.get("sessionId")
            if notification_session != session_id:
                if notification_session in descendant_sessions:
                    descendant_count += 1
                continue
            if method == "session.status":
                status = params.get("status")
                if status not in {"idle", "running"}:
                    raise DeepSeekHarnessProtocolError(
                        "session.status contains an unknown lifecycle value."
                    )
                if status != "idle":
                    continue
                idle_watermark = item.watermark
                if not receipt_seen:
                    raise DeepSeekHarnessProtocolError("idle_before_receipt")
                if not assistant_candidates:
                    raise DeepSeekHarnessProtocolError("idle_before_final")
                if not turn_end_seen:
                    raise DeepSeekHarnessProtocolError("idle_before_turn_end")
                if turn_end_kind not in _SUCCESSFUL_TURN_END_KINDS:
                    raise DeepSeekHarnessProtocolError(
                        f"unsuccessful_turn_end:{turn_end_kind or 'missing'}"
                    )
                final_id, final_text, final_watermark = assistant_candidates[-1]
                if not final_text:
                    raise DeepSeekHarnessProtocolError("root_final_empty")
                return DeepSeekHarnessOperationResult(
                    operation_id=operation_id,
                    message_id=message_id,
                    final_response=final_text,
                    finish_reason=turn_end_kind,
                    final_classification="trusted_root_final",
                    trusted_final=True,
                    receipt_watermark=receipt_watermark,
                    final_watermark=final_watermark,
                    idle_watermark=idle_watermark,
                    notification_count=notification_count,
                    descendant_notification_count=descendant_count,
                    pre_prompt_status=pre_status,
                )
            if method != "session.event":
                raise DeepSeekHarnessProtocolError(
                    f"unexpected DSH notification during operation: {method}"
                )
            event = params.get("event")
            if not isinstance(event, MappingABC):
                raise DeepSeekHarnessProtocolError(
                    "session.event requires an event object."
                )
            event_type = event.get("type")
            if not isinstance(event_type, str) or not event_type:
                raise DeepSeekHarnessProtocolError("session.event type is required.")
            normalized_event_type = event_type.lower()
            if any(marker in normalized_event_type for marker in _RESET_EVENT_MARKERS):
                raise DeepSeekHarnessProtocolError("runtime_reset_during_operation")
            if event_type == "agent/inbox/spliced":
                inserted_ids = _inbox_inserted_message_ids(event)
                if message_id in inserted_ids:
                    if receipt_seen:
                        raise DeepSeekHarnessProtocolError("duplicate_prompt_receipt")
                    if len(inserted_ids) != 1:
                        raise DeepSeekHarnessProtocolError("unknown_queued_work")
                    receipt_seen = True
                    receipt_watermark = item.watermark
                    continue
                if receipt_seen and inserted_ids:
                    raise DeepSeekHarnessProtocolError("unknown_queued_work")
                if not receipt_seen:
                    raise DeepSeekHarnessProtocolError("root_event_before_receipt")
                continue
            if not receipt_seen:
                raise DeepSeekHarnessProtocolError("root_event_before_receipt")
            if event_type == "assistant/message":
                if turn_end_seen:
                    raise DeepSeekHarnessProtocolError("final_after_turn_end")
                assistant_id, assistant_text = _assistant_message(event)
                if assistant_id in assistant_ids:
                    raise DeepSeekHarnessProtocolError("duplicate_root_final")
                assistant_ids.add(assistant_id)
                assistant_candidates.append(
                    (assistant_id, assistant_text, item.watermark)
                )
                continue
            if event_type == "turn/end":
                if turn_end_seen:
                    raise DeepSeekHarnessProtocolError("duplicate_turn_end")
                if not assistant_candidates:
                    raise DeepSeekHarnessProtocolError("turn_end_before_final")
                turn_end_kind = _turn_end_kind(event)
                turn_end_seen = True
                continue

    def graceful_shutdown(self) -> Mapping[str, object]:
        proc = self._proc
        if proc is None:
            return {"shutdown": "not_started", "exitCode": None}
        shutdown_result = "shutdown_acknowledged"
        try:
            self.request(
                "shutdown",
                None,
                timeout_seconds=self.spec.shutdown_timeout_seconds,
            )
        except BaseException:
            shutdown_result = "shutdown_unconfirmed"
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except OSError:
                shutdown_result = "shutdown_unconfirmed"
        try:
            exit_code = proc.wait(timeout=self.spec.shutdown_timeout_seconds)
        except subprocess.TimeoutExpired:
            self.force_terminate()
            return {"shutdown": "forced_after_grace_timeout", "exitCode": proc.poll()}
        self._close_process_streams()
        return {"shutdown": shutdown_result, "exitCode": exit_code}

    def force_terminate(self) -> None:
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is not None:
            self._close_process_streams()
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=max(self.spec.shutdown_timeout_seconds, 1.0),
                    shell=False,
                )
            else:
                os.killpg(proc.pid, 15)
        except (OSError, subprocess.SubprocessError):
            try:
                proc.kill()
            except OSError:
                return
        try:
            proc.wait(timeout=max(self.spec.shutdown_timeout_seconds, 1.0))
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass
        self._close_process_streams()

    def _close_process_streams(self) -> None:
        proc = self._proc
        if proc is None:
            return
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is None:
                continue
            try:
                stream.close()
            except OSError:
                pass
        current = threading.current_thread()
        for thread in (self._reader, self._stderr_reader):
            if thread is not None and thread is not current:
                thread.join(timeout=1.0)

    def _write_frame(self, frame: Mapping[str, object]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            raise DeepSeekHarnessContinuityError("DSH runtime stdin is unavailable.")
        payload = json.dumps(
            dict(frame),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        if len(payload) > self.spec.max_line_bytes:
            raise DeepSeekHarnessProtocolError("outbound DSH JSONL frame is oversized.")
        try:
            with self._write_lock:
                proc.stdin.write(payload)
                proc.stdin.flush()
        except OSError as exc:
            raise DeepSeekHarnessContinuityError(
                "DSH runtime stdin closed while sending a request."
            ) from exc

    def _reader_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            while True:
                line = proc.stdout.readline(self.spec.max_line_bytes + 1)
                if not line:
                    raise DeepSeekHarnessContinuityError(
                        "DSH runtime stdout closed unexpectedly."
                    )
                if len(line) > self.spec.max_line_bytes:
                    raise DeepSeekHarnessProtocolError(
                        "DSH runtime emitted an oversized JSONL frame."
                    )
                with self._lock:
                    self._total_output_bytes += len(line)
                    if self._total_output_bytes > self.spec.max_total_output_bytes:
                        raise DeepSeekHarnessProtocolError(
                            "DSH runtime exceeded the bounded total output limit."
                        )
                if not line.endswith(b"\n"):
                    raise DeepSeekHarnessProtocolError(
                        "DSH runtime emitted an unterminated JSONL frame."
                    )
                try:
                    decoded = line.decode("utf-8", errors="strict").strip()
                except UnicodeDecodeError as exc:
                    raise DeepSeekHarnessProtocolError(
                        "DSH runtime emitted non-UTF-8 protocol bytes."
                    ) from exc
                if not decoded:
                    continue
                try:
                    message = json.loads(decoded)
                except json.JSONDecodeError as exc:
                    raise DeepSeekHarnessProtocolError(
                        "DSH runtime emitted malformed JSON."
                    ) from exc
                self._handle_frame(message)
        except BaseException as exc:
            self._fail_transport(exc)

    def _stderr_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            while True:
                chunk = proc.stderr.read(4096)
                if not chunk:
                    return
                with self._lock:
                    remaining = max(self.spec.max_stderr_bytes - self._stderr_bytes, 0)
                    self._stderr_bytes += min(len(chunk), remaining)
                    if len(chunk) > remaining:
                        self._stderr_truncated = True
        except OSError:
            return

    def _handle_frame(self, message: object) -> None:
        if not isinstance(message, MappingABC):
            raise DeepSeekHarnessProtocolError("DSH JSON-RPC frame must be an object.")
        if message.get("jsonrpc") != "2.0":
            raise DeepSeekHarnessProtocolError("DSH JSON-RPC version must be 2.0.")
        msg_id = message.get("id")
        method = message.get("method")
        if isinstance(msg_id, (str, int)) and isinstance(method, str):
            raise DeepSeekHarnessProtocolError(
                "DSH runtime sent an unsupported reverse request."
            )
        if isinstance(msg_id, bool):
            raise DeepSeekHarnessProtocolError("DSH response id must not be boolean.")
        if isinstance(msg_id, int):
            with self._lock:
                pending = self._pending.pop(msg_id, None)
                duplicate = msg_id in self._completed_id_set
                if pending is None:
                    raise DeepSeekHarnessProtocolError(
                        "duplicate DSH response id."
                        if duplicate
                        else "unknown DSH response id."
                    )
                if len(self._completed_ids) == self._completed_ids.maxlen:
                    removed = self._completed_ids.popleft()
                    self._completed_id_set.discard(removed)
                self._completed_ids.append(msg_id)
                self._completed_id_set.add(msg_id)
                if msg_id == self._initialize_request_id:
                    self._initialize_response_seen = True
            pending.result.put(dict(message))
            return
        if msg_id is not None:
            raise DeepSeekHarnessProtocolError(
                "DSH response id must be a monotonic integer."
            )
        if not isinstance(method, str):
            raise DeepSeekHarnessProtocolError(
                "DSH frame is neither a response nor notification."
            )
        if method not in _DSH_NOTIFICATION_METHODS:
            raise DeepSeekHarnessProtocolError(
                f"unknown DSH notification method: {method}"
            )
        with self._lock:
            if not self._initialized and not self._initialize_response_seen:
                raise DeepSeekHarnessProtocolError(
                    "DSH business notification arrived before initialize completed."
                )
            self._watermark += 1
            watermark = self._watermark
        params = message.get("params")
        if not isinstance(params, MappingABC):
            raise DeepSeekHarnessProtocolError(
                f"{method} notification params must be an object."
            )
        if method == "session.status":
            session_id = params.get("sessionId")
            status = params.get("status")
            if not isinstance(session_id, str) or status not in {"running", "idle"}:
                raise DeepSeekHarnessProtocolError(
                    "session.status notification has an invalid payload."
                )
            with self._lock:
                self._last_status[session_id] = str(status)
        self._notifications.put(
            _WireNotification(
                watermark=watermark,
                method=method,
                params=dict(params),
            )
        )

    def _fail_transport(self, exc: BaseException) -> None:
        if not isinstance(exc, DeepSeekHarnessRuntimeError):
            exc = DeepSeekHarnessContinuityError(f"DSH reader failed: {exc}")
        with self._lock:
            if self._fatal_error is not None:
                return
            self._fatal_error = exc
            pending = list(self._pending.values())
            self._pending.clear()
        for waiter in pending:
            waiter.result.put(exc)
        self._notifications.put(exc)


def build_deepseek_harness_runtime_spec(
    *,
    workspace_id: str,
    agent_id: str,
    handle_id: str,
    dsh_session_id: str,
    cwd: str,
    session_root: str,
    runtime_home: str,
    runtime_home_source: str,
    carrier: str,
    executable_path: str,
    launch_args: Sequence[str],
    cordis_config_path: str | None = None,
    package_root: str,
    package_version: str,
    expected_server_version: str,
    model_provider: str,
    model: str,
    state_root: str,
    session_start_mode: str = "create",
    session_compression: str = "zstd",
    reply_writeback_mode: str = "explicit_only",
    initialize_timeout_seconds: float = 30.0,
    operation_timeout_seconds: float = 120.0,
    shutdown_timeout_seconds: float = 5.0,
    max_line_bytes: int = 1024 * 1024,
    max_total_output_bytes: int = 32 * 1024 * 1024,
    max_stderr_bytes: int = 64 * 1024,
) -> DeepSeekHarnessRuntimeSpec:
    runtime_id = f"dsh-runtime-{uuid4()}"
    generation_id = f"dsh-generation-{uuid4()}"
    resolved_session_root = str(
        Path(session_root).expanduser().resolve(strict=False)
    )
    return DeepSeekHarnessRuntimeSpec(
        runtime_id=runtime_id,
        generation_id=generation_id,
        owner_nonce=secrets.token_hex(24),
        workspace_id=workspace_id,
        agent_id=agent_id,
        handle_id=handle_id,
        dsh_session_id=dsh_session_id,
        session_start_mode=session_start_mode,
        session_compression=session_compression,
        cwd=str(Path(cwd).expanduser().resolve()),
        session_root=resolved_session_root,
        runtime_home=str(Path(runtime_home).expanduser().resolve(strict=False)),
        runtime_home_source=runtime_home_source,
        carrier=carrier,
        executable_path=str(Path(executable_path).expanduser().resolve()),
        launch_args=tuple(str(item) for item in launch_args),
        cordis_config_path=(
            str(Path(cordis_config_path).expanduser().resolve(strict=False))
            if cordis_config_path is not None
            else None
        ),
        package_root=str(Path(package_root).expanduser().resolve(strict=False)),
        package_version=package_version,
        package_commit=DEEPSEEK_HARNESS_AUDITED_COMMIT,
        expected_server_version=expected_server_version,
        model_provider=model_provider,
        model=model,
        paths=DeepSeekHarnessRuntimePaths.create(
            state_root,
            runtime_id,
            session_root=resolved_session_root,
            session_id=dsh_session_id,
        ),
        initialize_timeout_seconds=initialize_timeout_seconds,
        operation_timeout_seconds=operation_timeout_seconds,
        shutdown_timeout_seconds=shutdown_timeout_seconds,
        max_line_bytes=max_line_bytes,
        max_total_output_bytes=max_total_output_bytes,
        max_stderr_bytes=max_stderr_bytes,
        reply_writeback_mode=_reply_mode(reply_writeback_mode),
    )


def probe_deepseek_harness_session(
    *,
    executable_path: str,
    package_root: str,
    session_root: str,
    session_id: str,
    session_compression: str = "zstd",
    environment: Mapping[str, str] | None = None,
    timeout_seconds: float = 30.0,
) -> Mapping[str, object]:
    """Locate one persisted DSH session through the official header-only API."""

    package = Path(package_root).expanduser().resolve(strict=False)
    probe_entry = package / "session-probe.mjs"
    argv = (
        str(Path(executable_path).expanduser().resolve(strict=False)),
        str(probe_entry),
        "--root",
        str(Path(session_root).expanduser().resolve(strict=False)),
        "--session",
        session_id,
        "--compression",
        session_compression,
    )
    if not probe_entry.is_file():
        return {
            "schema": "deepseek_harness_session_probe.v1",
            "ok": False,
            "found": False,
            "failureCategory": "session_probe_entry_missing",
            "failureReason": "the Beacon DSH session probe entry is missing",
            "fullSessionHistoryRead": False,
        }
    try:
        completed = subprocess.run(
            list(argv),
            cwd=str(package),
            env=dict(environment or os.environ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "schema": "deepseek_harness_session_probe.v1",
            "ok": False,
            "found": False,
            "failureCategory": "session_probe_process_failed",
            "failureReason": f"{exc.__class__.__name__}: {exc}",
            "fullSessionHistoryRead": False,
        }
    try:
        decoded = json.loads(completed.stdout)
    except json.JSONDecodeError:
        decoded = None
    if not isinstance(decoded, MappingABC):
        return {
            "schema": "deepseek_harness_session_probe.v1",
            "ok": False,
            "found": False,
            "failureCategory": "session_probe_output_invalid",
            "failureReason": (
                "the official persistence probe did not return one JSON object"
            ),
            "processReturnCode": completed.returncode,
            "fullSessionHistoryRead": False,
        }
    return {
        **dict(decoded),
        "processReturnCode": completed.returncode,
        "fullSessionHistoryRead": False,
    }


def preflight_deepseek_harness_runtime(
    *,
    carrier: str,
    executable_path: str,
    package_root: str,
    cordis_config_path: str | None = None,
    runtime_home: str | None = None,
    state_root: str | None = None,
    session_root: str | None = None,
    session_id: str | None = None,
    session_start_mode: str = "create",
    session_compression: str = "zstd",
    expected_package_version: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> Mapping[str, object]:
    normalized_carrier = carrier.strip().lower().replace("-", "_")
    os_name = platform.system().lower()
    architecture = platform.machine().lower()
    executable = Path(executable_path).expanduser().resolve(strict=False)
    package = Path(package_root).expanduser().resolve(strict=False)
    expected_version = expected_package_version or (
        DEEPSEEK_HARNESS_NPM_VERSION
        if normalized_carrier == "node"
        else DEEPSEEK_HARNESS_PYPI_VERSION
    )
    expected_server_version = (
        "0.0.1"
        if normalized_carrier == "node"
        else expected_version.replace("rc", "-rc")
    )
    checks: list[Mapping[str, object]] = []
    failures: list[str] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})
        if not ok:
            failures.append(detail)

    record(
        "executable",
        executable.is_file(),
        "configured executable exists" if executable.is_file() else "configured executable is missing",
    )
    record(
        "package_root",
        package.is_dir(),
        "package root exists" if package.is_dir() else "package root is missing",
    )
    launch_args: tuple[str, ...] = ()
    runtime_entry: Path | None = None
    package_evidence: list[Mapping[str, object]] = []
    platform_supported = False
    platform_reason = "unsupported carrier"
    if normalized_carrier == "node":
        platform_supported = True
        platform_reason = "official Node/TypeScript SDK runtime route"
        if executable.is_file():
            try:
                completed = subprocess.run(
                    [str(executable), "--version"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                    check=False,
                    shell=False,
                    env=dict(environment or os.environ),
                )
                version_text = completed.stdout.strip().lstrip("v")
                version_parts = tuple(
                    int(part) for part in version_text.split(".")[:3]
                )
                record(
                    "node_version",
                    completed.returncode == 0 and version_parts >= (22, 19, 0),
                    f"Node {version_text or 'unknown'} (requires >=22.19)",
                )
            except (OSError, subprocess.SubprocessError, ValueError) as exc:
                record("node_version", False, f"Node version probe failed: {exc}")
        required_packages = {
            "@deepseek-ai/dsh": "@deepseek-ai/dsh/package.json",
            "@deepseek-ai/dsh-agent-spine-demo": "@deepseek-ai/dsh-agent-spine-demo/package.json",
            "@deepseek-ai/dsh-bash-local": "@deepseek-ai/dsh-bash-local/package.json",
            "@deepseek-ai/dsh-sdk-client": "@deepseek-ai/dsh-sdk-client/package.json",
            "@deepseek-ai/dsh-sdk-protocol": "@deepseek-ai/dsh-sdk-protocol/package.json",
            "@deepseek-ai/dsh-sdk-jsonrpc-server": "@deepseek-ai/dsh-sdk-jsonrpc-server/package.json",
            "@deepseek-ai/dsh-sdk-jsonrpc-demo": "@deepseek-ai/dsh-sdk-jsonrpc-demo/package.json",
            "@deepseek-ai/dsh-session": "@deepseek-ai/dsh-session/package.json",
            "@deepseek-ai/dsh-session-persistence-jsonl": "@deepseek-ai/dsh-session-persistence-jsonl/package.json",
        }
        for package_name, relative in required_packages.items():
            package_json = package / "node_modules" / Path(relative)
            actual_version: str | None = None
            if package_json.is_file():
                try:
                    raw = json.loads(package_json.read_text(encoding="utf-8"))
                    if isinstance(raw, MappingABC) and isinstance(raw.get("version"), str):
                        actual_version = str(raw["version"])
                except (OSError, json.JSONDecodeError):
                    actual_version = None
            ok = actual_version == expected_version
            package_evidence.append(
                {
                    "package": package_name,
                    "expectedVersion": expected_version,
                    "actualVersion": actual_version,
                    "packageJson": str(package_json),
                    "ok": ok,
                }
            )
            record(
                f"package:{package_name}",
                ok,
                f"{package_name}={actual_version or 'missing'} (expected {expected_version})",
            )
        for package_name in (
            "dsh-sdk-client",
            "dsh-sdk-protocol",
            "dsh-sdk-jsonrpc-server",
        ):
            public_entry = (
                package / "node_modules" / "@deepseek-ai" / package_name / "lib" / "index.js"
            )
            record(
                f"public_entry:@deepseek-ai/{package_name}",
                public_entry.is_file(),
                f"@deepseek-ai/{package_name} public entry "
                + ("exists" if public_entry.is_file() else "is missing"),
            )
        runtime_entry = (
            package
            / "node_modules"
            / "@deepseek-ai"
            / "dsh-sdk-jsonrpc-demo"
            / "lib"
            / "bin.js"
        )
        record(
            "runtime_entry",
            runtime_entry.is_file(),
            "official JSON-RPC runtime entry exists"
            if runtime_entry.is_file()
            else "official JSON-RPC runtime entry is missing",
        )
        beacon_adapter = package / "beacon-sdk-jsonrpc-server.mjs"
        session_probe_entry = package / "session-probe.mjs"
        record(
            "beacon_resume_adapter",
            beacon_adapter.is_file(),
            "Beacon create/resume SDK adapter exists"
            if beacon_adapter.is_file()
            else "Beacon create/resume SDK adapter is missing",
        )
        record(
            "session_probe_entry",
            session_probe_entry.is_file(),
            "official JSONL header probe entry exists"
            if session_probe_entry.is_file()
            else "official JSONL header probe entry is missing",
        )
        if cordis_config_path is None:
            record("cordis_config", False, "Node carrier requires an explicit Cordis config")
        else:
            cordis = Path(cordis_config_path).expanduser().resolve(strict=False)
            cordis_config_path = str(cordis)
            record(
                "cordis_config",
                cordis.is_file(),
                "Cordis config exists" if cordis.is_file() else "Cordis config is missing",
            )
            try:
                cordis_text = cordis.read_text(encoding="utf-8")
            except OSError:
                cordis_text = ""
            adapter_configured = (
                cordis.is_file()
                and "./beacon-sdk-jsonrpc-server.mjs" in cordis_text
            )
            record(
                "beacon_resume_adapter_configured",
                adapter_configured,
                "Cordis config selects the Beacon create/resume SDK adapter"
                if adapter_configured
                else "Cordis config must select ./beacon-sdk-jsonrpc-server.mjs",
            )
            launch_args = (str(executable), str(runtime_entry), str(cordis))
    elif normalized_carrier == "python":
        platform_supported = (
            (os_name == "linux" and architecture in {"x86_64", "amd64", "aarch64", "arm64"})
            or (os_name == "darwin" and architecture in {"arm64", "aarch64"})
        )
        platform_reason = (
            "official PyPI runtime wheel platform"
            if platform_supported
            else "official PyPI runtime wheels do not support this OS/architecture"
        )
        record("platform_support", platform_supported, platform_reason)
        probe_script = (
            "import importlib.metadata as m,json,sys;"
            "import deepseek_harness as sdk;"
            "import deepseek_harness_runtime as rt;"
            "print(json.dumps({'sdkVersion':m.version('deepseek-harness-sdk'),"
            "'runtimeVersion':m.version('deepseek-harness-runtime-bin'),"
            "'sysPrefix':sys.prefix,'sdkModule':sdk.__file__,"
            "'runtimeModule':rt.__file__,"
            "'sdkSymbols':{n:hasattr(sdk,n) for n in "
            "('HarnessClient','HarnessConfig','DeepSeekHarness')},"
            "'runtimeSymbols':{n:hasattr(rt,n) for n in "
            "('resolve_bundled_launch_args','bundled_default_config_path')},"
            "'launchArgs':list(rt.resolve_bundled_launch_args()),"
            "'defaultConfigPath':str(rt.bundled_default_config_path())}))"
        )
        python_probe: Mapping[str, object] = {}
        if executable.is_file():
            try:
                completed = subprocess.run(
                    [str(executable), "-c", probe_script],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15,
                    check=False,
                    shell=False,
                    env=dict(environment or os.environ),
                )
                decoded = (
                    json.loads(completed.stdout)
                    if completed.stdout.strip()
                    else {}
                )
                if isinstance(decoded, MappingABC):
                    python_probe = dict(decoded)
            except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
                python_probe = {}
        sdk_version = python_probe.get("sdkVersion")
        runtime_version = python_probe.get("runtimeVersion")
        record(
            "python_sdk_version",
            sdk_version == expected_version,
            f"deepseek-harness-sdk={sdk_version or 'missing'} (expected {expected_version})",
        )
        record(
            "python_runtime_version",
            runtime_version == expected_version,
            f"deepseek-harness-runtime-bin={runtime_version or 'missing'} (expected {expected_version})",
        )
        installation_matches = (
            isinstance(python_probe.get("sysPrefix"), str)
            and Path(str(python_probe["sysPrefix"])).resolve(strict=False) == package
        )
        record(
            "python_installation_root",
            installation_matches,
            "configured package root matches interpreter sys.prefix"
            if installation_matches
            else "configured package root does not match interpreter sys.prefix",
        )
        sdk_symbols = python_probe.get("sdkSymbols")
        runtime_symbols = python_probe.get("runtimeSymbols")
        symbols_ok = (
            isinstance(sdk_symbols, MappingABC)
            and all(
                sdk_symbols.get(name) is True
                for name in ("HarnessClient", "HarnessConfig")
            )
            and isinstance(runtime_symbols, MappingABC)
            and all(
                runtime_symbols.get(name) is True
                for name in (
                    "resolve_bundled_launch_args",
                    "bundled_default_config_path",
                )
            )
        )
        record(
            "python_public_symbols",
            symbols_ok,
            "required Python SDK/runtime resolver symbols are present"
            if symbols_ok
            else "required Python SDK/runtime resolver symbols are missing",
        )
        raw_launch_args = python_probe.get("launchArgs")
        if isinstance(raw_launch_args, Sequence) and not isinstance(
            raw_launch_args,
            (str, bytes),
        ):
            try:
                launch_args = _require_argv(raw_launch_args)
            except ValueError:
                launch_args = ()
        runtime_entry = Path(launch_args[0]) if launch_args else None
        runtime_entry_ok = runtime_entry is not None and runtime_entry.is_file()
        record(
            "runtime_entry",
            runtime_entry_ok,
            "bundled Python runtime executable exists"
            if runtime_entry_ok
            else "bundled Python runtime executable is missing",
        )
        default_config = python_probe.get("defaultConfigPath")
        resolved_config = (
            Path(cordis_config_path).expanduser().resolve(strict=False)
            if cordis_config_path is not None
            else Path(str(default_config)).resolve(strict=False)
            if isinstance(default_config, str) and default_config
            else None
        )
        config_ok = resolved_config is not None and resolved_config.is_file()
        record(
            "cordis_config",
            config_ok,
            "Python runtime Cordis config exists"
            if config_ok
            else "Python runtime Cordis config is missing",
        )
        cordis_config_path = (
            str(resolved_config) if resolved_config is not None else None
        )
        package_evidence.extend(
            (
                {
                    "package": "deepseek-harness-sdk",
                    "expectedVersion": expected_version,
                    "actualVersion": sdk_version,
                    "modulePath": python_probe.get("sdkModule"),
                    "ok": sdk_version == expected_version,
                },
                {
                    "package": "deepseek-harness-runtime-bin",
                    "expectedVersion": expected_version,
                    "actualVersion": runtime_version,
                    "modulePath": python_probe.get("runtimeModule"),
                    "ok": runtime_version == expected_version,
                },
            )
        )
    else:
        record("carrier", False, "carrier must be node or python")
    if session_start_mode not in {"create", "resume"}:
        record(
            "session_start_mode",
            False,
            "sessionStartMode must be create or resume",
        )
    if session_compression not in {"zstd", "none"}:
        record(
            "session_compression",
            False,
            "sessionCompression must be zstd or none",
        )
    runtime_home_path = (
        Path(runtime_home).expanduser().resolve(strict=False)
        if runtime_home is not None
        else package / ".dsh-home"
    )
    state_root_path = (
        Path(state_root).expanduser().resolve(strict=False)
        if state_root is not None
        else None
    )
    session_root_path = (
        Path(session_root).expanduser().resolve(strict=False)
        if session_root is not None
        else None
    )
    runtime_home_status = _path_access_status(
        runtime_home_path,
        source=("configured_runtime_home" if runtime_home is not None else "package_default"),
    )
    state_root_status = (
        _path_access_status(state_root_path, source="configured_state_root")
        if state_root_path is not None
        else None
    )
    session_root_status = (
        _path_access_status(session_root_path, source="configured_session_root")
        if session_root_path is not None
        else None
    )
    for name, status in (
        ("runtime_home_access", runtime_home_status),
        ("state_root_access", state_root_status),
        ("session_root_access", session_root_status),
    ):
        if status is not None:
            record(
                name,
                bool(status.get("writable")),
                (
                    f"{name} is writable"
                    if status.get("writable")
                    else f"{name} is not writable"
                ),
            )
    runtime_inventory = _owned_runtime_inventory(state_root_path)
    session_probe: Mapping[str, object] | None = None
    if session_start_mode == "resume":
        if not isinstance(session_id, str) or not session_id.strip():
            record(
                "existing_session_id",
                False,
                "resume requires an exact existing session id",
            )
        elif normalized_carrier != "node":
            record(
                "existing_session_resume_carrier",
                False,
                "existing-session resume currently requires the audited Node carrier",
            )
        elif session_root_path is None:
            record(
                "existing_session_root",
                False,
                "resume requires an explicit session root",
            )
        elif executable.is_file() and package.is_dir():
            session_probe = probe_deepseek_harness_session(
                executable_path=str(executable),
                package_root=str(package),
                session_root=str(session_root_path),
                session_id=session_id.strip(),
                session_compression=session_compression,
                environment=environment,
            )
            record(
                "existing_session_exact_match",
                session_probe.get("ok") is True,
                (
                    "exact persisted session header found"
                    if session_probe.get("ok") is True
                    else str(
                        session_probe.get("failureReason")
                        or session_probe.get("failureCategory")
                        or "existing session probe failed"
                    )
                ),
            )
    state = {
        "schema": "deepseek_harness_preflight.v1",
        "supported": not failures and platform_supported,
        "carrier": normalized_carrier,
        "os": platform.system(),
        "architecture": platform.machine(),
        "platformSupported": platform_supported,
        "platformReason": platform_reason,
        "executablePath": str(executable),
        "packageRoot": str(package),
        "expectedPackageVersion": expected_version,
        "expectedServerVersion": expected_server_version,
        "auditedCommit": DEEPSEEK_HARNESS_AUDITED_COMMIT,
        "runtimeEntry": str(runtime_entry) if runtime_entry is not None else None,
        "runtimeExecutablePath": (
            str(Path(launch_args[0]).resolve(strict=False)) if launch_args else None
        ),
        "runtimeConfigPath": cordis_config_path,
        "launchArgs": list(launch_args),
        "packageEvidence": package_evidence,
        "publicSdkSymbols": {
            "client": (
                ["DeepSeekHarness", "HarnessClient", "HarnessSession"]
                if normalized_carrier == "node"
                else ["DeepSeekHarness", "HarnessClient", "HarnessConfig"]
            ),
            "server": ["HarnessSdkJsonRpcServer"],
            "protocol": [
                "JsonRpcLineTransport",
                "HarnessSdkRequestMap",
                "HarnessSdkNotificationMap",
            ],
            "evidence": "exact_package_and_audited_public_export_contract",
        },
        "requiredMethods": sorted(_DSH_REQUEST_METHODS),
        "requiredNotifications": sorted(_DSH_NOTIFICATION_METHODS),
        "protocolVersionNegotiation": False,
        "runtimeHomeStatus": runtime_home_status,
        "stateRootStatus": state_root_status,
        "sessionRootStatus": session_root_status,
        "sessionStartMode": session_start_mode,
        "sessionCompression": session_compression,
        "sessionProbe": session_probe,
        "existingOwnedRuntimeInventory": runtime_inventory,
        "supervisorCapability": {
            "localLoopbackIpc": True,
            "ownerToken": True,
            "ownerFileLease": True,
            "crossProcessOperationLease": True,
            "coldResume": normalized_carrier == "node",
        },
        "checks": checks,
        "failures": failures,
        "credentialsRead": False,
        "globalInstallAttempted": False,
    }
    return state


def write_runtime_bootstrap(spec: DeepSeekHarnessRuntimeSpec) -> str:
    paths = spec.paths
    state_directory = Path(paths.state_directory)
    state_directory.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(48)
    _atomic_write_json(Path(paths.spec_path), spec.to_mapping(), mode=0o600)
    _atomic_write_text(Path(paths.token_path), token, mode=0o600)
    _atomic_write_json(
        Path(paths.state_path),
        _initial_runtime_state(spec),
        mode=0o600,
    )
    return token


def launch_deepseek_harness_supervisor(
    spec: DeepSeekHarnessRuntimeSpec,
    *,
    startup_timeout_seconds: float | None = None,
) -> Mapping[str, object]:
    state_path = Path(spec.paths.state_path)
    if state_path.exists():
        existing = read_runtime_state(state_path)
        if existing.get("generationId") != spec.generation_id:
            raise DeepSeekHarnessContinuityError(
                "runtime state path already belongs to a different generation."
            )
        if existing.get("lifecycle") not in {"starting", "start_failed"}:
            raise DeepSeekHarnessContinuityError(
                "runtime generation already has terminal or active state; use recreate for a new session."
            )
    else:
        write_runtime_bootstrap(spec)
    env = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[3])
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        source_root
        if not existing_pythonpath
        else os.pathsep.join((source_root, existing_pythonpath))
    )
    argv = (
        str(Path(sys.executable).resolve()),
        "-m",
        "agent_os.deepseek_harness_supervisor",
        "--spec",
        spec.paths.spec_path,
    )
    kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "cwd": spec.cwd,
        "env": env,
        "shell": False,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    else:
        kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(list(argv), **kwargs)
    except OSError as exc:
        raise DeepSeekHarnessContinuityError(
            f"failed to launch DSH supervisor: {exc.__class__.__name__}: {exc}"
        ) from exc
    process_pid = process.pid
    deadline = time.monotonic() + (
        startup_timeout_seconds or spec.initialize_timeout_seconds + 5.0
    )
    last_state: Mapping[str, object] = _initial_runtime_state(spec)
    while time.monotonic() < deadline:
        if state_path.is_file():
            try:
                last_state = read_runtime_state(state_path)
            except (OSError, ValueError, json.JSONDecodeError):
                time.sleep(0.05)
                continue
            lifecycle = last_state.get("lifecycle")
            if lifecycle == "ready":
                result = {
                    "schema": "deepseek_harness_supervisor_start.v1",
                    "started": True,
                    "supervisorLauncherPid": process_pid,
                    "runtimeState": dict(last_state),
                }
                _detach_popen_handle(process)
                return result
            if lifecycle in {"start_failed", "continuity_lost"}:
                result = {
                    "schema": "deepseek_harness_supervisor_start.v1",
                    "started": False,
                    "supervisorLauncherPid": process_pid,
                    "runtimeState": dict(last_state),
                }
                process.wait(timeout=2)
                return result
        if process.poll() is not None:
            break
        time.sleep(0.05)
    result = {
        "schema": "deepseek_harness_supervisor_start.v1",
        "started": False,
        "supervisorLauncherPid": process_pid,
        "runtimeState": dict(last_state),
        "failureCategory": "supervisor_start_timeout",
    }
    if process.poll() is None:
        _detach_popen_handle(process)
    return result


def read_runtime_state(path: str | Path) -> Mapping[str, object]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, MappingABC):
        raise ValueError("DSH runtime state must be a JSON object.")
    return dict(raw)


def write_runtime_state(
    path: str | Path,
    value: Mapping[str, object],
) -> None:
    _atomic_write_json(Path(path), value, mode=0o600)


def request_deepseek_harness_supervisor(
    *,
    state_path: str | Path,
    token_path: str | Path,
    method: str,
    workspace_id: str,
    agent_id: str,
    handle_id: str,
    runtime_id: str,
    generation_id: str,
    payload: Mapping[str, object] | None = None,
    timeout_seconds: float = 10.0,
) -> Mapping[str, object]:
    state = read_runtime_state(state_path)
    endpoint = state.get("ipcEndpoint")
    if not isinstance(endpoint, MappingABC):
        return _lost_runtime_response(
            state,
            "supervisor_endpoint_missing",
        )
    host = endpoint.get("host")
    port = endpoint.get("port")
    if host != "127.0.0.1" or not isinstance(port, int):
        return _lost_runtime_response(state, "supervisor_endpoint_invalid")
    token = Path(token_path).read_text(encoding="utf-8").strip()
    request = {
        "schema": "deepseek_harness_supervisor_request.v1",
        "requestId": f"dsh-ipc-{uuid4()}",
        "method": method,
        "ownerToken": token,
        "workspaceId": workspace_id,
        "agentId": agent_id,
        "handleId": handle_id,
        "runtimeId": runtime_id,
        "generationId": generation_id,
        "payload": dict(payload or {}),
    }
    encoded = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    ) + b"\n"
    if len(encoded) > _MAX_IPC_BYTES:
        raise ValueError("DSH supervisor IPC request is oversized.")
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds) as connection:
            connection.settimeout(timeout_seconds)
            connection.sendall(encoded)
            with connection.makefile("rb") as reader:
                line = reader.readline(_MAX_IPC_BYTES + 1)
    except (OSError, TimeoutError) as exc:
        return _lost_runtime_response(
            state,
            "supervisor_unreachable",
            failure=f"{exc.__class__.__name__}: {exc}",
        )
    if len(line) > _MAX_IPC_BYTES:
        raise DeepSeekHarnessProtocolError("DSH supervisor IPC response is oversized.")
    try:
        decoded = line.decode("utf-8", errors="strict")
        response = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeepSeekHarnessProtocolError(
            "DSH supervisor returned malformed IPC JSON."
        ) from exc
    if not isinstance(response, MappingABC):
        raise DeepSeekHarnessProtocolError(
            "DSH supervisor IPC response must be an object."
        )
    return dict(response)


def runtime_handle_metadata(spec: DeepSeekHarnessRuntimeSpec) -> Mapping[str, object]:
    return {
        "schema": "deepseek_harness_runtime_binding.v1",
        "runtimeId": spec.runtime_id,
        "generationId": spec.generation_id,
        "ownerNonce": spec.owner_nonce,
        "dshSessionId": spec.dsh_session_id,
        "sessionStartMode": spec.session_start_mode,
        "sessionCompression": spec.session_compression,
        "continuityScope": "persistent_native_session",
        "runtimeStatePath": spec.paths.state_path,
        "runtimeTokenPath": spec.paths.token_path,
        "runtimeSpecPath": spec.paths.spec_path,
        "runtimeHome": spec.runtime_home,
        "runtimeHomeSource": spec.runtime_home_source,
        "sessionRoot": spec.session_root,
        "carrier": spec.carrier,
        "cordisConfigPath": spec.cordis_config_path,
        "packageVersion": spec.package_version,
        "packageCommit": spec.package_commit,
        "replyWritebackMode": spec.reply_writeback_mode,
        "sessionOwnerLeasePath": spec.paths.session_owner_lease_path,
        "existingSessionImport": spec.session_start_mode == "resume",
        "canResumeAcrossRuntimeRestart": True,
    }


def _initial_runtime_state(spec: DeepSeekHarnessRuntimeSpec) -> Mapping[str, object]:
    return {
        "schema": "deepseek_harness_runtime_state.v1",
        "runtimeId": spec.runtime_id,
        "generationId": spec.generation_id,
        "ownerNonce": spec.owner_nonce,
        "workspaceId": spec.workspace_id,
        "agentId": spec.agent_id,
        "handleId": spec.handle_id,
        "provider": "deepseek_harness",
        "backendId": DEEPSEEK_HARNESS_BACKEND_ID,
        "dshSessionId": spec.dsh_session_id,
        "sessionStartMode": spec.session_start_mode,
        "sessionCompression": spec.session_compression,
        "cwd": spec.cwd,
        "sessionRoot": spec.session_root,
        "runtimeHome": spec.runtime_home,
        "runtimeHomeSource": spec.runtime_home_source,
        "executablePath": spec.executable_path,
        "packageRoot": spec.package_root,
        "packageVersion": spec.package_version,
        "packageCommit": spec.package_commit,
        "carrier": spec.carrier,
        "cordisConfigPath": spec.cordis_config_path,
        "continuityScope": "persistent_native_session",
        "lifecycle": "starting",
        "runtimeState": "starting",
        "supervisorInstanceId": None,
        "supervisorPid": None,
        "supervisorProcessStartedAt": None,
        "runtimePid": None,
        "runtimeProcessStartedAt": None,
        "ipcEndpoint": None,
        "activeOperationId": None,
        "lastAcceptedMessageId": None,
        "durableEventWatermark": 0,
        "lastStatus": "unknown",
        "startedAt": None,
        "heartbeatAt": None,
        "lastSeenAt": None,
        "continuityLostAt": None,
        "continuityLossReason": None,
        "replyWritebackMode": spec.reply_writeback_mode,
        "credentialStored": False,
        "promptStored": False,
        "transcriptStored": False,
    }


def _lost_runtime_response(
    state: Mapping[str, object],
    reason: str,
    *,
    failure: str | None = None,
) -> Mapping[str, object]:
    ambiguous_delivery = state.get("ambiguousDelivery") is True
    cleanly_stopped = state.get("lifecycle") == "stopped"
    return {
        "schema": "deepseek_harness_supervisor_response.v1",
        "ok": False,
        "status": "stopped" if cleanly_stopped else "continuity_lost",
        "failureCategory": "runtime_stopped" if cleanly_stopped else reason,
        "failureReason": (
            "the runtime generation is cleanly stopped and may be resumed"
            if cleanly_stopped
            else failure or reason
        ),
        "ambiguousDelivery": ambiguous_delivery,
        "resumeAvailable": not ambiguous_delivery,
        "resumeRequiresAmbiguousDeliveryAcknowledgement": ambiguous_delivery,
        "runtimeState": {
            **dict(state),
            "lifecycle": "stopped" if cleanly_stopped else "continuity_lost",
            "runtimeState": "unavailable",
            "continuityLossReason": (
                state.get("continuityLossReason") if cleanly_stopped else reason
            ),
        },
    }


def _detach_popen_handle(process: subprocess.Popen[object]) -> None:
    """Release only the launcher's OS handle; the detached child keeps running."""
    handle = getattr(process, "_handle", None)
    if handle is not None:
        try:
            handle.Close()
        except (AttributeError, OSError):
            pass
    process.returncode = 0


def _inbox_inserted_message_ids(event: Mapping[str, object]) -> set[str]:
    data = event.get("data")
    inserted = data.get("inserted") if isinstance(data, MappingABC) else None
    if not isinstance(inserted, Sequence) or isinstance(inserted, (str, bytes)):
        return set()
    return {
        str(item["id"])
        for item in inserted
        if isinstance(item, MappingABC)
        and isinstance(item.get("id"), str)
        and str(item["id"]).strip()
    }


def _assistant_message(event: Mapping[str, object]) -> tuple[str, str]:
    data = event.get("data")
    if not isinstance(data, MappingABC):
        raise DeepSeekHarnessProtocolError("assistant/message requires data.")
    message = data.get("message")
    owner = message if isinstance(message, MappingABC) else data
    message_id = owner.get("id")
    if not isinstance(message_id, str) or not message_id.strip():
        raise DeepSeekHarnessProtocolError(
            "assistant/message requires a durable message id."
        )
    content = owner.get("content")
    if not isinstance(content, Sequence) or isinstance(content, (str, bytes)):
        raise DeepSeekHarnessProtocolError(
            "assistant/message content must be an array."
        )
    text_parts = [
        str(block.get("text") or "")
        for block in content
        if isinstance(block, MappingABC) and block.get("type") == "text"
    ]
    return message_id, "".join(text_parts)


def _turn_end_kind(event: Mapping[str, object]) -> str:
    data = event.get("data")
    reason = data.get("reason") if isinstance(data, MappingABC) else None
    kind = reason.get("kind") if isinstance(reason, MappingABC) else None
    if not isinstance(kind, str) or not kind.strip():
        raise DeepSeekHarnessProtocolError(
            "turn/end requires a string data.reason.kind."
        )
    return kind


def _json_error_summary(value: object) -> str:
    if not isinstance(value, MappingABC):
        return "unknown JSON-RPC error"
    code = value.get("code")
    message = value.get("message")
    return f"code={code!r}, message={message!r}"


def _path_access_status(path: Path, *, source: str) -> Mapping[str, object]:
    writable_ancestor = path if path.exists() else path.parent
    while not writable_ancestor.exists() and writable_ancestor != writable_ancestor.parent:
        writable_ancestor = writable_ancestor.parent
    return {
        "path": str(path),
        "source": source,
        "exists": path.exists(),
        "readable": path.exists() and os.access(path, os.R_OK),
        "writable": (
            os.access(path, os.W_OK)
            if path.exists()
            else writable_ancestor.is_dir() and os.access(writable_ancestor, os.W_OK)
        ),
        "nearestExistingAncestor": str(writable_ancestor),
        "secretsRead": False,
    }


def _owned_runtime_inventory(state_root: Path | None) -> Mapping[str, object]:
    items: list[Mapping[str, object]] = []
    if state_root is not None and state_root.is_dir():
        for directory in sorted(state_root.glob("dsh-runtime-*")):
            if not directory.is_dir():
                continue
            state_path = directory / "runtime-state.json"
            lifecycle: object = "unreadable"
            generation_id: object = None
            runtime_id: object = directory.name
            session_id: object = None
            session_root: object = None
            session_start_mode: object = None
            if state_path.is_file():
                try:
                    raw = json.loads(state_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    raw = None
                if isinstance(raw, MappingABC):
                    lifecycle = raw.get("lifecycle", "unknown")
                    generation_id = raw.get("generationId")
                    runtime_id = raw.get("runtimeId", runtime_id)
                    session_id = raw.get("dshSessionId")
                    session_root = raw.get("sessionRoot")
                    session_start_mode = raw.get("sessionStartMode")
            items.append(
                {
                    "runtimeId": runtime_id,
                    "generationId": generation_id,
                    "lifecycle": lifecycle,
                    "dshSessionId": session_id,
                    "sessionRoot": session_root,
                    "sessionStartMode": session_start_mode,
                    "ownerLeaseFilePresent": (directory / "owner.lease").exists(),
                    "operationLeaseFilePresent": (directory / "operation.lease").exists(),
                    "requiresExplicitStatusOrResume": lifecycle
                    not in {"stopped", "continuity_lost", "start_failed"},
                }
            )
    return {
        "stateRootConfigured": state_root is not None,
        "runtimeCount": len(items),
        "leaseFilePresentCount": sum(
            1
            for item in items
            if item["ownerLeaseFilePresent"] or item["operationLeaseFilePresent"]
        ),
        "ownerOrOperationLeaseConflictCount": None,
        "livenessInferredFromLeaseFiles": False,
        "items": items,
        "credentialsRead": False,
        "fullSessionLogsScanned": False,
    }


def _atomic_write_json(path: Path, value: Mapping[str, object], *, mode: int) -> None:
    _atomic_write_text(
        path,
        json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        mode=mode,
    )


def _atomic_write_text(path: Path, value: str, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=False,
    )
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            os.chmod(path, mode)
        except OSError:
            pass
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def _required_text(value: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
    logical_name = keys[0] if keys else "value"
    raise ValueError(f"{logical_name} is required.")


def _optional_text(value: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        item = value.get(key)
        if item is None:
            continue
        if not isinstance(item, str):
            raise ValueError(f"{key} must be a string.")
        stripped = item.strip()
        return stripped or None
    return None


def _require_argv(value: Sequence[object]) -> tuple[str, ...]:
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError("launchArgs items must be non-empty strings.")
        if "\x00" in item:
            raise ValueError("launchArgs items must not contain null bytes.")
        result.append(item)
    if not result:
        raise ValueError("launchArgs must not be empty.")
    return tuple(result)


def _positive_float(value: object, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be a number.")
    result = float(value)
    if result <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return result


def _positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return value


def _reply_mode(value: object) -> str:
    normalized = str(value).strip().lower().replace("-", "_")
    if normalized not in {"explicit_only", "provider_final_capture"}:
        raise ValueError(
            "replyWritebackMode must be explicit_only or provider_final_capture."
        )
    return normalized


def _validate_identity_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required.")
    if "\x00" in value or len(value) > 512:
        raise ValueError(f"{name} is invalid.")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "DEEPSEEK_HARNESS_AUDITED_COMMIT",
    "DEEPSEEK_HARNESS_BACKEND_ID",
    "DEEPSEEK_HARNESS_NPM_VERSION",
    "DEEPSEEK_HARNESS_PYPI_VERSION",
    "DeepSeekHarnessContinuityError",
    "DeepSeekHarnessDeliveryError",
    "DeepSeekHarnessJsonRpcTransport",
    "DeepSeekHarnessOperationResult",
    "DeepSeekHarnessPreflightError",
    "DeepSeekHarnessProtocolError",
    "DeepSeekHarnessRuntimeError",
    "DeepSeekHarnessRuntimePaths",
    "DeepSeekHarnessRuntimeSpec",
    "build_deepseek_harness_runtime_spec",
    "launch_deepseek_harness_supervisor",
    "preflight_deepseek_harness_runtime",
    "probe_deepseek_harness_session",
    "read_runtime_state",
    "request_deepseek_harness_supervisor",
    "runtime_handle_metadata",
    "write_runtime_state",
    "write_runtime_bootstrap",
]
