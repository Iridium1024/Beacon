from __future__ import annotations

import codecs
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
from typing import BinaryIO, Callable, Mapping, Protocol, Sequence


HERMES_TUI_GATEWAY_SUPPORTED_VERSION = "0.19.0"
HERMES_TUI_GATEWAY_MAIN_ADVISORY_VERSION = "0.20.5"
HERMES_TUI_GATEWAY_MODULE = "tui_gateway.entry"
_REQUIRED_METHODS_0190 = (
    "session.list",
    "session.resume",
    "session.status",
    "session.history",
    "session.interrupt",
    "prompt.submit",
    "approval.respond",
    "clarify.respond",
    "sudo.respond",
    "secret.respond",
)
_REQUIRED_EVENTS_0190 = (
    "gateway.ready",
    "message.delta",
    "message.complete",
    "tool.start",
    "tool.complete",
    "status.update",
    "error",
    "approval.request",
    "clarify.request",
    "sudo.request",
    "sudo.expire",
    "secret.request",
    "secret.expire",
)
_FORBIDDEN_PROMPT_FIELDS = frozenset(
    {
        "truncate_before_user_ordinal",
        "truncate_before_row_id",
        "confirm_truncate",
        "confirm_empty_truncate",
        "survivor_user_row_ids",
    }
)


class GatewayProcess(Protocol):
    stdin: BinaryIO | None
    stdout: BinaryIO | None
    stderr: BinaryIO | None
    pid: int

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


ProcessFactory = Callable[
    [Sequence[str], str, Mapping[str, str]], GatewayProcess
]


@dataclass(frozen=True, slots=True)
class HermesTuiGatewayRuntime:
    status: str
    compatible: bool
    python_executable: str
    package_version: str | None = None
    package_location: str | None = None
    gateway_entry_location: str | None = None
    server_location: str | None = None
    launch_argv: tuple[str, ...] = ()
    methods: Mapping[str, bool] = field(default_factory=dict)
    events: Mapping[str, bool] = field(default_factory=dict)
    capabilities: Mapping[str, object] = field(default_factory=dict)
    error: str | None = None

    def to_metadata(self) -> Mapping[str, object]:
        result: dict[str, object] = {
            "schema": "hermes_tui_gateway_preflight.v1",
            "readOnly": True,
            "probeAttempted": True,
            "sessionStarted": False,
            "status": self.status,
            "compatible": self.compatible,
            "pythonExecutable": self.python_executable,
            "supportedVersion": HERMES_TUI_GATEWAY_SUPPORTED_VERSION,
            "mainAdvisoryVersion": HERMES_TUI_GATEWAY_MAIN_ADVISORY_VERSION,
            "launchModule": HERMES_TUI_GATEWAY_MODULE,
            "launchArgv": list(self.launch_argv),
            "consoleScriptExpected": False,
            "methods": dict(self.methods),
            "events": dict(self.events),
            "capabilities": dict(self.capabilities),
            "mainAdvisoryCapabilities": dict(_capabilities_main_advisory()),
        }
        for key, value in (
            ("packageVersion", self.package_version),
            ("packageLocation", self.package_location),
            ("gatewayEntryLocation", self.gateway_entry_location),
            ("serverLocation", self.server_location),
            ("error", self.error),
        ):
            if value is not None:
                result[key] = value
        return result


@dataclass(frozen=True, slots=True)
class HermesTuiGatewayActivationConfig:
    persistent_session_id: str
    registered_source: str
    cwd: str
    runtime_home: str | None
    source_tag: str
    ready_timeout_seconds: float = 10.0
    request_timeout_seconds: float = 15.0
    cleanup_timeout_seconds: float = 5.0
    max_line_bytes: int = 1024 * 1024
    max_total_bytes: int = 8 * 1024 * 1024
    max_diagnostic_chars: int = 4000

    def __post_init__(self) -> None:
        for name, value in (
            ("persistentSessionId", self.persistent_session_id),
            ("registeredSource", self.registered_source),
            ("sourceTag", self.source_tag),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty text.")
        cwd = Path(self.cwd)
        if not cwd.is_absolute() or not cwd.exists() or not cwd.is_dir():
            raise ValueError("Hermes TUI Gateway cwd must be an existing absolute directory.")
        object.__setattr__(self, "cwd", str(cwd.resolve(strict=True)))
        if self.runtime_home is not None:
            home = Path(self.runtime_home)
            if not home.is_absolute() or not home.exists() or not home.is_dir():
                raise ValueError(
                    "Hermes TUI Gateway runtimeHome must be an existing absolute directory."
                )
            object.__setattr__(self, "runtime_home", str(home.resolve(strict=True)))
        for name, value in (
            ("readyTimeoutSeconds", self.ready_timeout_seconds),
            ("requestTimeoutSeconds", self.request_timeout_seconds),
            ("cleanupTimeoutSeconds", self.cleanup_timeout_seconds),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero.")
        for name, value in (
            ("maxLineBytes", self.max_line_bytes),
            ("maxTotalBytes", self.max_total_bytes),
            ("maxDiagnosticChars", self.max_diagnostic_chars),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero.")


@dataclass(frozen=True, slots=True)
class HermesTuiGatewayRunResult:
    status: str
    package_version: str
    provider_command_started: bool
    prompt_submission_attempted: bool
    prompt_submitted: bool
    session_continuity_verified: bool
    persistent_session_id: str
    runtime_session_id: str | None
    event_counts: Mapping[str, int]
    identity_evidence: Mapping[str, object]
    final_response: str | None = None
    final_response_source: str | None = None
    terminal_status: str | None = None
    interaction_requests: int = 0
    interaction_responses: int = 0
    interaction_denied: int = 0
    interrupt_attempted: bool = False
    interrupt_status: str = "not_attempted"
    cleanup_status: str = "not_attempted"
    exit_code: int | None = None
    failure_category: str | None = None
    failure_reason: str | None = None
    ambiguous_delivery: bool = False
    requires_user_review: bool = False
    stderr_tail: str | None = None
    diagnostics: tuple[str, ...] = ()
    wire_methods: tuple[str, ...] = ()

    @property
    def succeeded(self) -> bool:
        return self.status == "completed"

    def to_metadata(self) -> Mapping[str, object]:
        result: dict[str, object] = {
            "schema": "hermes_tui_gateway_run.v1",
            "status": self.status,
            "packageVersion": self.package_version,
            "providerCommandStarted": self.provider_command_started,
            "promptSubmissionAttempted": self.prompt_submission_attempted,
            "promptSubmitted": self.prompt_submitted,
            "sessionContinuityVerified": self.session_continuity_verified,
            "persistentSessionId": self.persistent_session_id,
            "runtimeSessionId": self.runtime_session_id,
            "runtimeSessionIdEqualsPersistent": (
                self.runtime_session_id == self.persistent_session_id
                if self.runtime_session_id is not None
                else None
            ),
            "eventCounts": dict(self.event_counts),
            "identityEvidence": dict(self.identity_evidence),
            "interactionRequests": self.interaction_requests,
            "interactionResponses": self.interaction_responses,
            "interactionDenied": self.interaction_denied,
            "interactionPolicy": "deny_or_empty_response_fail_closed",
            "interruptAttempted": self.interrupt_attempted,
            "interruptStatus": self.interrupt_status,
            "cleanupStatus": self.cleanup_status,
            "ambiguousDelivery": self.ambiguous_delivery,
            "requiresUserReview": self.requires_user_review,
            "diagnostics": list(self.diagnostics),
            "wireMethods": list(self.wire_methods),
            "initializeSent": False,
            "fullSessionHistoryRead": False,
            "persistentRegistryIdentityUpdated": False,
            "ordinaryPromptTruncationFieldsSent": False,
        }
        for key, value in (
            ("finalResponseSource", self.final_response_source),
            ("terminalStatus", self.terminal_status),
            ("exitCode", self.exit_code),
            ("failureCategory", self.failure_category),
            ("failureReason", self.failure_reason),
            ("stderrTail", self.stderr_tail),
        ):
            if value is not None:
                result[key] = value
        return result


class HermesTuiGatewayProtocolError(RuntimeError):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


def load_hermes_tui_gateway_runtime(
    python_executable: str | None = None,
    *,
    timeout_seconds: float = 15.0,
) -> HermesTuiGatewayRuntime:
    executable = str(python_executable or sys.executable).strip()
    if not executable:
        raise ValueError("gatewayPython must be non-empty text.")
    probe = r'''
import importlib.metadata as metadata
import importlib.util
import json
from pathlib import Path

result = {"package": "hermes-agent"}
try:
    result["version"] = metadata.version("hermes-agent")
    distribution = metadata.distribution("hermes-agent")
    result["package_location"] = str(Path(distribution.locate_file(".")).resolve())
except Exception as exc:
    result["error"] = f"{exc.__class__.__name__}: {exc}"
    print(json.dumps(result))
    raise SystemExit(0)
for name, key in (("tui_gateway.entry", "entry_location"), ("tui_gateway.server", "server_location")):
    try:
        spec = importlib.util.find_spec(name)
        result[key] = str(Path(spec.origin).resolve()) if spec and spec.origin else None
    except Exception as exc:
        result[key] = None
        result.setdefault("probe_errors", []).append(f"{name}: {exc.__class__.__name__}: {exc}")
server = result.get("server_location")
text = Path(server).read_text(encoding="utf-8") if server else ""
methods = %s
events = %s
result["methods"] = {item: (f'@method("{item}")' in text) for item in methods}
result["events"] = {item: (f'"{item}"' in text) for item in events}
entry = result.get("entry_location")
entry_text = Path(entry).read_text(encoding="utf-8") if entry else ""
result["events"]["gateway.ready"] = '"gateway.ready"' in entry_text
result["no_initialize_handler"] = '@method("initialize")' not in text
print(json.dumps(result))
''' % (repr(_REQUIRED_METHODS_0190), repr(_REQUIRED_EVENTS_0190))
    try:
        completed = subprocess.run(
            (executable, "-I", "-c", probe),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            check=False,
            shell=False,
            timeout=max(1.0, timeout_seconds),
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        return HermesTuiGatewayRuntime(
            status="probe_failed",
            compatible=False,
            python_executable=executable,
            error=f"{exc.__class__.__name__}: {exc}",
        )
    if completed.returncode != 0:
        return HermesTuiGatewayRuntime(
            status="probe_failed",
            compatible=False,
            python_executable=executable,
            error=_bounded_text(completed.stderr or completed.stdout, 1000),
        )
    try:
        payload = json.loads(completed.stdout.strip())
    except (json.JSONDecodeError, UnicodeError) as exc:
        return HermesTuiGatewayRuntime(
            status="probe_malformed",
            compatible=False,
            python_executable=executable,
            error=f"{exc.__class__.__name__}: {exc}",
        )
    if not isinstance(payload, dict):
        return HermesTuiGatewayRuntime(
            status="probe_malformed",
            compatible=False,
            python_executable=executable,
            error="Hermes gateway probe did not return a JSON object.",
        )
    version = _optional_text(payload.get("version"))
    methods = _bool_mapping(payload.get("methods"), _REQUIRED_METHODS_0190)
    events = _bool_mapping(payload.get("events"), _REQUIRED_EVENTS_0190)
    present = bool(payload.get("entry_location")) and bool(payload.get("server_location"))
    exact = version == HERMES_TUI_GATEWAY_SUPPORTED_VERSION
    surface = all(methods.values()) and all(events.values())
    no_initialize = payload.get("no_initialize_handler") is True
    compatible = exact and present and surface and no_initialize
    if not exact:
        status = "unsupported_version"
        error = (
            "Hermes TUI Gateway requires exact audited hermes-agent version "
            f"{HERMES_TUI_GATEWAY_SUPPORTED_VERSION}; found {version or 'unknown'}."
        )
    elif not present:
        status = "gateway_module_missing"
        error = "tui_gateway.entry or tui_gateway.server is not present."
    elif not surface or not no_initialize:
        status = "unsupported_gateway_surface"
        error = "The exact-version gateway is missing the audited method/event surface."
    else:
        status = "available"
        error = None
    return HermesTuiGatewayRuntime(
        status=status,
        compatible=compatible,
        python_executable=executable,
        package_version=version,
        package_location=_optional_text(payload.get("package_location")),
        gateway_entry_location=_optional_text(payload.get("entry_location")),
        server_location=_optional_text(payload.get("server_location")),
        launch_argv=(executable, "-u", "-m", HERMES_TUI_GATEWAY_MODULE),
        methods=methods,
        events=events,
        capabilities=_capabilities_0190(),
        error=error or _optional_text(payload.get("error")),
    )


def run_hermes_tui_gateway_activation(
    config: HermesTuiGatewayActivationConfig,
    *,
    runtime: HermesTuiGatewayRuntime,
    prompt: str,
    timeout_seconds: float,
    max_response_chars: int,
    process_factory: ProcessFactory | None = None,
) -> HermesTuiGatewayRunResult:
    if not runtime.compatible or runtime.package_version is None:
        raise ValueError("Hermes TUI Gateway runtime preflight is not compatible.")
    if timeout_seconds <= 0:
        raise ValueError("timeoutSeconds must be greater than zero.")
    if max_response_chars <= 0:
        raise ValueError("maxResponseChars must be greater than zero.")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be non-empty text.")
    driver = _GatewayDriver(
        config=config,
        runtime=runtime,
        prompt=prompt,
        timeout_seconds=timeout_seconds,
        max_response_chars=max_response_chars,
        process_factory=process_factory or _start_gateway_process,
    )
    return driver.run()


class _GatewayDriver:
    def __init__(
        self,
        *,
        config: HermesTuiGatewayActivationConfig,
        runtime: HermesTuiGatewayRuntime,
        prompt: str,
        timeout_seconds: float,
        max_response_chars: int,
        process_factory: ProcessFactory,
    ) -> None:
        self.config = config
        self.runtime = runtime
        self.prompt = prompt
        self.timeout_seconds = timeout_seconds
        self.max_response_chars = max_response_chars
        self.process_factory = process_factory
        self.process: GatewayProcess | None = None
        self.frames: queue.Queue[tuple[str, object]] = queue.Queue()
        self.stop = threading.Event()
        self.reader_threads: list[threading.Thread] = []
        self.request_id = 0
        self.pending: set[int] = set()
        self.completed: set[int] = set()
        self.responses: dict[int, object] = {}
        self.event_counts: dict[str, int] = {}
        self.wire_methods: list[str] = []
        self.diagnostics: list[str] = []
        self.stderr_parts: list[str] = []
        self.ready_seen = False
        self.prompt_started = False
        self.prompt_submitted = False
        self.runtime_session_id: str | None = None
        self.final_response: str | None = None
        self.final_response_source: str | None = None
        self.terminal_status: str | None = None
        self.interaction_requests = 0
        self.interaction_responses = 0
        self.interaction_denied = 0
        self.interaction_ids: set[str] = set()
        self.expired_ids: set[str] = set()
        self.interaction_responded_ids: set[str] = set()
        self.identity_evidence: dict[str, object] = {
            "persistentSessionId": config.persistent_session_id,
            "registeredSource": config.registered_source,
            "registeredCwd": config.cwd,
            "registeredRuntimeHome": config.runtime_home,
            "sessionListMatchCount": 0,
            "sessionListSourceVerified": False,
            "resumePersistentIdVerified": False,
            "runtimeSessionId": None,
            "cwdVerification": "unverified",
            "runtimeHomeVerification": "registered_source_evidence_only",
            "sourceVerification": "session_list",
        }
        self.interrupt_attempted = False
        self.interrupt_status = "not_attempted"
        self.cleanup_status = "not_attempted"
        self.failure_category: str | None = None
        self.failure_reason: str | None = None
        self.ambiguous_delivery = False

    def run(self) -> HermesTuiGatewayRunResult:
        started = time.monotonic()
        status = "failed"
        try:
            environment = os.environ.copy()
            if self.config.runtime_home is not None:
                environment["HERMES_HOME"] = self.config.runtime_home
            self.process = self.process_factory(
                self.runtime.launch_argv,
                self.config.cwd,
                environment,
            )
            self._start_readers()
            self._wait_ready()
            listed = self._request("session.list", {})
            self._verify_list(listed)
            resumed = self._request(
                "session.resume",
                {
                    "session_id": self.config.persistent_session_id,
                    "source": self.config.source_tag,
                },
            )
            self._verify_resume(resumed)
            self.prompt_started = True
            submitted = self._request(
                "prompt.submit",
                {"session_id": self.runtime_session_id, "text": self.prompt},
            )
            if not isinstance(submitted, dict) or submitted.get("status") != "streaming":
                raise HermesTuiGatewayProtocolError(
                    "prompt_submit_rejected",
                    "prompt.submit did not return the audited streaming status.",
                )
            self.prompt_submitted = True
            deadline = started + self.timeout_seconds
            while self.terminal_status is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Hermes TUI Gateway activation timed out.")
                self._consume_one(min(remaining, self.config.request_timeout_seconds))
            self._drain_after_terminal()
            if self.terminal_status != "complete":
                raise HermesTuiGatewayProtocolError(
                    "provider_terminal_failure",
                    f"Hermes terminal status was {self.terminal_status!r}.",
                )
            if not self.final_response:
                raise HermesTuiGatewayProtocolError(
                    "provider_final_missing",
                    "Hermes emitted no non-empty terminal assistant response.",
                )
            status = "completed"
        except TimeoutError as exc:
            self.failure_category = "activation_timeout"
            self.failure_reason = str(exc)
            self.ambiguous_delivery = self.prompt_started
            self._interrupt_once()
            status = "failed"
        except HermesTuiGatewayProtocolError as exc:
            self.failure_category = exc.category
            self.failure_reason = str(exc)
            self.ambiguous_delivery = self.prompt_started and not self.prompt_submitted
            if self.prompt_started and self.runtime_session_id:
                self._interrupt_once()
            status = "failed"
        except (OSError, UnicodeError, ValueError, queue.Empty) as exc:
            self.failure_category = "gateway_transport_failure"
            self.failure_reason = f"{exc.__class__.__name__}: {exc}"
            self.ambiguous_delivery = self.prompt_started
            if self.prompt_started and self.runtime_session_id:
                self._interrupt_once()
            status = "failed"
        finally:
            exit_code = self._cleanup()
        return HermesTuiGatewayRunResult(
            status=status,
            package_version=self.runtime.package_version or "unknown",
            provider_command_started=self.process is not None,
            prompt_submission_attempted=self.prompt_started,
            prompt_submitted=self.prompt_submitted,
            session_continuity_verified=bool(
                self.identity_evidence.get("sessionListSourceVerified")
                and self.identity_evidence.get("resumePersistentIdVerified")
                and self.identity_evidence.get("cwdVerification") == "verified"
            ),
            persistent_session_id=self.config.persistent_session_id,
            runtime_session_id=self.runtime_session_id,
            event_counts=dict(sorted(self.event_counts.items())),
            identity_evidence=dict(self.identity_evidence),
            final_response=self.final_response,
            final_response_source=self.final_response_source,
            terminal_status=self.terminal_status,
            interaction_requests=self.interaction_requests,
            interaction_responses=self.interaction_responses,
            interaction_denied=self.interaction_denied,
            interrupt_attempted=self.interrupt_attempted,
            interrupt_status=self.interrupt_status,
            cleanup_status=self.cleanup_status,
            exit_code=exit_code,
            failure_category=self.failure_category,
            failure_reason=self.failure_reason,
            ambiguous_delivery=self.ambiguous_delivery,
            requires_user_review=status != "completed" or self.interaction_requests > 0,
            stderr_tail=_bounded_text("".join(self.stderr_parts), self.config.max_diagnostic_chars)
            or None,
            diagnostics=tuple(self.diagnostics),
            wire_methods=tuple(self.wire_methods),
        )

    def _start_readers(self) -> None:
        assert self.process is not None
        if self.process.stdin is None or self.process.stdout is None or self.process.stderr is None:
            raise HermesTuiGatewayProtocolError(
                "gateway_pipe_missing", "Gateway process did not expose all stdio pipes."
            )
        stdout_thread = threading.Thread(
            target=self._read_stdout,
            args=(self.process.stdout,),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._read_stderr,
            args=(self.process.stderr,),
            daemon=True,
        )
        self.reader_threads.extend((stdout_thread, stderr_thread))
        stdout_thread.start()
        stderr_thread.start()

    def _read_stdout(self, stream: BinaryIO) -> None:
        total = 0
        buffer = bytearray()
        try:
            while not self.stop.is_set():
                chunk = _read_pipe_chunk(stream)
                if not chunk:
                    if buffer:
                        raise HermesTuiGatewayProtocolError(
                            "unexpected_eof", "Gateway stdout ended with an unterminated frame."
                        )
                    self.frames.put(("eof", None))
                    return
                total += len(chunk)
                if total > self.config.max_total_bytes:
                    raise HermesTuiGatewayProtocolError(
                        "gateway_output_oversized", "Gateway stdout exceeded maxTotalBytes."
                    )
                buffer.extend(chunk)
                while b"\n" in buffer:
                    raw, _, rest = buffer.partition(b"\n")
                    buffer = bytearray(rest)
                    if len(raw) > self.config.max_line_bytes:
                        raise HermesTuiGatewayProtocolError(
                            "gateway_frame_oversized", "Gateway JSONL frame exceeded maxLineBytes."
                        )
                    text = raw.decode("utf-8", errors="strict")
                    try:
                        frame = json.loads(text)
                    except json.JSONDecodeError as exc:
                        raise HermesTuiGatewayProtocolError(
                            "gateway_json_malformed", f"Malformed gateway JSONL frame: {exc}"
                        ) from exc
                    if not isinstance(frame, dict):
                        raise HermesTuiGatewayProtocolError(
                            "gateway_frame_invalid", "Gateway frame must be a JSON object."
                        )
                    self.frames.put(("frame", frame))
                if len(buffer) > self.config.max_line_bytes:
                    raise HermesTuiGatewayProtocolError(
                        "gateway_frame_oversized", "Gateway JSONL frame exceeded maxLineBytes."
                    )
        except (UnicodeError, OSError, HermesTuiGatewayProtocolError) as exc:
            category = (
                exc.category
                if isinstance(exc, HermesTuiGatewayProtocolError)
                else "gateway_utf8_invalid" if isinstance(exc, UnicodeError)
                else "gateway_read_failed"
            )
            self.frames.put(("reader_error", (category, str(exc))))

    def _read_stderr(self, stream: BinaryIO) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        total = 0
        try:
            while not self.stop.is_set():
                chunk = _read_pipe_chunk(stream)
                if not chunk:
                    tail = decoder.decode(b"", final=True)
                    if tail:
                        self.stderr_parts.append(tail)
                    return
                total += len(chunk)
                if total > self.config.max_total_bytes:
                    self.frames.put(
                        (
                            "reader_error",
                            ("gateway_stderr_oversized", "Gateway stderr exceeded maxTotalBytes."),
                        )
                    )
                    return
                text = decoder.decode(chunk)
                if text:
                    self.stderr_parts.append(text)
                    joined = "".join(self.stderr_parts)
                    if len(joined) > self.config.max_diagnostic_chars:
                        self.stderr_parts[:] = [joined[-self.config.max_diagnostic_chars :]]
        except (UnicodeError, OSError) as exc:
            category = (
                "gateway_stderr_utf8_invalid"
                if isinstance(exc, UnicodeError)
                else "gateway_stderr_read_failed"
            )
            self.frames.put(("reader_error", (category, str(exc))))

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + self.config.ready_timeout_seconds
        while not self.ready_seen:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HermesTuiGatewayProtocolError(
                    "gateway_ready_timeout", "gateway.ready was not received in time."
                )
            try:
                self._consume_one(remaining)
            except TimeoutError as exc:
                raise HermesTuiGatewayProtocolError(
                    "gateway_ready_timeout", "gateway.ready was not received in time."
                ) from exc

    def _request(self, method: str, params: Mapping[str, object]) -> object:
        if method == "initialize":
            raise HermesTuiGatewayProtocolError(
                "initialize_forbidden", "Hermes TUI Gateway has no initialize RPC."
            )
        if method == "prompt.submit" and _FORBIDDEN_PROMPT_FIELDS.intersection(params):
            raise HermesTuiGatewayProtocolError(
                "prompt_truncation_forbidden",
                "Ordinary prompt.submit may not contain rewind/truncation fields.",
            )
        assert self.process is not None and self.process.stdin is not None
        self.request_id += 1
        rid = self.request_id
        self.pending.add(rid)
        self.wire_methods.append(method)
        frame = {"jsonrpc": "2.0", "id": rid, "method": method, "params": dict(params)}
        raw = (json.dumps(frame, separators=(",", ":"), ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
        if len(raw) > self.config.max_line_bytes:
            raise HermesTuiGatewayProtocolError(
                "request_frame_oversized", "Gateway request exceeded maxLineBytes."
            )
        try:
            self.process.stdin.write(raw)
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self.pending.discard(rid)
            raise HermesTuiGatewayProtocolError(
                "gateway_send_failed", f"Gateway request send failed: {exc}"
            ) from exc
        deadline = time.monotonic() + self.config.request_timeout_seconds
        while True:
            if rid in self.responses:
                result = self.responses.pop(rid)
                self.pending.remove(rid)
                self.completed.add(rid)
                return result
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.pending.discard(rid)
                raise HermesTuiGatewayProtocolError(
                    "gateway_request_timeout", f"{method} response timed out."
                )
            try:
                item = self.frames.get(timeout=remaining)
            except queue.Empty as exc:
                self.pending.discard(rid)
                raise HermesTuiGatewayProtocolError(
                    "gateway_request_timeout", f"{method} response timed out."
                ) from exc
            kind, payload = item
            if kind != "frame":
                self._raise_transport_item(kind, payload)
            assert isinstance(payload, dict)
            response = self._classify_frame(payload)
            if response is None:
                continue
            response_id, result = response
            if response_id != rid:
                self.responses[response_id] = result
                continue
            self.pending.remove(rid)
            self.completed.add(rid)
            return result

    def _consume_one(self, timeout: float) -> None:
        try:
            kind, payload = self.frames.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError("Gateway event wait timed out.") from exc
        if kind != "frame":
            self._raise_transport_item(kind, payload)
        assert isinstance(payload, dict)
        response = self._classify_frame(payload)
        if response is not None:
            response_id, _ = response
            raise HermesTuiGatewayProtocolError(
                "unknown_response_id",
                f"Unexpected gateway response id {response_id!r} outside a request.",
            )

    def _drain_after_terminal(self) -> None:
        deadline = time.monotonic() + 0.05
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            try:
                kind, payload = self.frames.get(timeout=remaining)
            except queue.Empty:
                return
            if kind == "eof":
                return
            if kind != "frame":
                self._raise_transport_item(kind, payload)
            assert isinstance(payload, dict)
            response = self._classify_frame(payload)
            if response is not None:
                response_id, _ = response
                raise HermesTuiGatewayProtocolError(
                    "unknown_response_id",
                    f"Unexpected gateway response id {response_id!r} after terminal event.",
                )

    def _raise_transport_item(self, kind: str, payload: object) -> None:
        if kind == "eof":
            code = self.process.poll() if self.process is not None else None
            raise HermesTuiGatewayProtocolError(
                "unexpected_eof", f"Gateway stdout reached EOF before completion (exit={code})."
            )
        if kind == "reader_error" and isinstance(payload, tuple):
            raise HermesTuiGatewayProtocolError(str(payload[0]), str(payload[1]))
        raise HermesTuiGatewayProtocolError(
            "gateway_transport_failure", f"Unexpected gateway transport item {kind!r}."
        )

    def _classify_frame(self, frame: Mapping[str, object]) -> tuple[int, object] | None:
        if frame.get("jsonrpc") != "2.0":
            raise HermesTuiGatewayProtocolError(
                "gateway_jsonrpc_invalid", "Gateway frame jsonrpc must equal '2.0'."
            )
        if "id" in frame:
            rid = frame.get("id")
            if not isinstance(rid, int):
                raise HermesTuiGatewayProtocolError(
                    "gateway_response_id_invalid", "Gateway response id must be an integer."
                )
            if rid in self.completed:
                raise HermesTuiGatewayProtocolError(
                    "duplicate_response", f"Gateway duplicated response id {rid}."
                )
            if rid in self.responses:
                raise HermesTuiGatewayProtocolError(
                    "duplicate_response", f"Gateway duplicated pending response id {rid}."
                )
            if rid not in self.pending:
                raise HermesTuiGatewayProtocolError(
                    "unknown_response_id", f"Gateway returned unknown response id {rid}."
                )
            if "result" in frame and "error" in frame:
                raise HermesTuiGatewayProtocolError(
                    "gateway_response_invalid", "Gateway response contains result and error."
                )
            if "error" in frame:
                error = frame.get("error")
                message = (
                    str(error.get("message"))
                    if isinstance(error, Mapping) and error.get("message") is not None
                    else str(error)
                )
                raise HermesTuiGatewayProtocolError(
                    "gateway_rpc_error", f"Gateway RPC {rid} failed: {message}"
                )
            if "result" not in frame:
                raise HermesTuiGatewayProtocolError(
                    "gateway_response_invalid", "Gateway response contains no result."
                )
            return rid, frame.get("result")
        method = frame.get("method")
        if method != "event":
            raise HermesTuiGatewayProtocolError(
                "unexpected_reverse_request",
                "Gateway sent a non-event notification/reverse request.",
            )
        params = frame.get("params")
        if not isinstance(params, Mapping):
            raise HermesTuiGatewayProtocolError(
                "gateway_event_invalid", "Gateway event params must be an object."
            )
        self._handle_event(params)
        return None

    def _handle_event(self, params: Mapping[str, object]) -> None:
        event_type = _optional_text(params.get("type"))
        if event_type is None:
            raise HermesTuiGatewayProtocolError(
                "gateway_event_invalid", "Gateway event type is required."
            )
        self.event_counts[event_type] = self.event_counts.get(event_type, 0) + 1
        if event_type == "gateway.ready":
            if self.ready_seen:
                raise HermesTuiGatewayProtocolError(
                    "gateway_ready_duplicate", "gateway.ready was emitted more than once."
                )
            if self.request_id != 0:
                raise HermesTuiGatewayProtocolError(
                    "gateway_ready_out_of_order", "gateway.ready arrived after RPC traffic began."
                )
            self.ready_seen = True
            return
        if not self.ready_seen:
            raise HermesTuiGatewayProtocolError(
                "gateway_ready_missing", "Gateway emitted an event before gateway.ready."
            )
        if self.runtime_session_id is None:
            raise HermesTuiGatewayProtocolError(
                "session_event_before_resume",
                f"Gateway emitted session event {event_type!r} before resume completed.",
            )
        sid = _optional_text(params.get("session_id"))
        if self.runtime_session_id is not None and sid != self.runtime_session_id:
            raise HermesTuiGatewayProtocolError(
                "cross_session_event",
                f"Gateway event {event_type!r} belongs to runtime session {sid!r}.",
            )
        payload = params.get("payload")
        body = dict(payload) if isinstance(payload, Mapping) else {}
        if event_type in {
            "approval.request",
            "clarify.request",
            "sudo.request",
            "secret.request",
        }:
            self._handle_interaction(event_type, sid, body)
            return
        if event_type in {"sudo.expire", "secret.expire"}:
            request_id = _optional_text(body.get("request_id"))
            if request_id is None:
                raise HermesTuiGatewayProtocolError(
                    "interaction_expiry_invalid", f"{event_type} lacks request_id."
                )
            if (
                request_id in self.expired_ids
                or request_id in self.interaction_responded_ids
                or request_id not in self.interaction_ids
            ):
                raise HermesTuiGatewayProtocolError(
                    "interaction_expiry_unknown",
                    f"{event_type} references unknown or duplicate request_id {request_id!r}.",
                )
            self.expired_ids.add(request_id)
            return
        if event_type == "error":
            message = _optional_text(body.get("message")) or "Hermes gateway error event"
            raise HermesTuiGatewayProtocolError("provider_error_event", message)
        if event_type == "message.complete":
            if not self.prompt_submitted:
                raise HermesTuiGatewayProtocolError(
                    "terminal_event_out_of_order",
                    "message.complete arrived before prompt.submit was acknowledged.",
                )
            if self.terminal_status is not None:
                raise HermesTuiGatewayProtocolError(
                    "duplicate_terminal_event", "Hermes emitted duplicate message.complete events."
                )
            status = _optional_text(body.get("status")) or "complete"
            self.terminal_status = status
            text = _optional_text(body.get("text"))
            if status == "complete" and text:
                self.final_response = text[: self.max_response_chars]
                self.final_response_source = "gateway_event.message.complete"

    def _handle_interaction(
        self,
        event_type: str,
        sid: str | None,
        payload: Mapping[str, object],
    ) -> None:
        if not self.prompt_started or sid != self.runtime_session_id:
            raise HermesTuiGatewayProtocolError(
                "interaction_out_of_scope", f"{event_type} is not scoped to the current submit."
            )
        self.interaction_requests += 1
        if event_type == "approval.request":
            result = self._request(
                "approval.respond",
                {"session_id": self.runtime_session_id, "choice": "deny", "all": False},
            )
        else:
            request_id = _optional_text(payload.get("request_id"))
            if request_id is None:
                raise HermesTuiGatewayProtocolError(
                    "interaction_request_id_missing", f"{event_type} lacks request_id."
                )
            if request_id in self.interaction_ids or request_id in self.expired_ids:
                raise HermesTuiGatewayProtocolError(
                    "interaction_request_duplicate",
                    f"{event_type} reused request_id {request_id!r}.",
                )
            self.interaction_ids.add(request_id)
            method, field_name = {
                "clarify.request": ("clarify.respond", "answer"),
                "sudo.request": ("sudo.respond", "password"),
                "secret.request": ("secret.respond", "value"),
            }[event_type]
            result = self._request(method, {"request_id": request_id, field_name: ""})
            self.interaction_responded_ids.add(request_id)
        if not isinstance(result, Mapping):
            raise HermesTuiGatewayProtocolError(
                "interaction_response_invalid", f"{event_type} response was not an object."
            )
        response_status = _optional_text(result.get("status"))
        if response_status not in {None, "ok", "expired"} and "resolved" not in result:
            raise HermesTuiGatewayProtocolError(
                "interaction_response_rejected",
                f"{event_type} denial response was rejected: {response_status!r}.",
            )
        self.interaction_responses += 1
        self.interaction_denied += 1

    def _verify_list(self, result: object) -> None:
        if not isinstance(result, Mapping) or not isinstance(result.get("sessions"), list):
            raise HermesTuiGatewayProtocolError(
                "session_list_invalid", "session.list result lacks sessions."
            )
        matches = [
            item
            for item in result["sessions"]
            if isinstance(item, Mapping)
            and item.get("id") == self.config.persistent_session_id
            and item.get("source") == self.config.registered_source
        ]
        same_id = [
            item
            for item in result["sessions"]
            if isinstance(item, Mapping) and item.get("id") == self.config.persistent_session_id
        ]
        self.identity_evidence["sessionListMatchCount"] = len(matches)
        if len(matches) == 0:
            category = "session_source_mismatch" if same_id else "session_list_missing"
            raise HermesTuiGatewayProtocolError(
                category,
                "session.list did not contain exactly the registered persistent id/source pair.",
            )
        if len(matches) != 1 or len(same_id) != 1:
            raise HermesTuiGatewayProtocolError(
                "session_list_duplicate",
                "session.list contained duplicate rows for the registered persistent id.",
            )
        self.identity_evidence["sessionListSourceVerified"] = True

    def _verify_resume(self, result: object) -> None:
        if not isinstance(result, Mapping):
            raise HermesTuiGatewayProtocolError(
                "session_resume_invalid", "session.resume result must be an object."
            )
        persistent_values = {
            str(value)
            for value in (result.get("resumed"), result.get("session_key"))
            if value is not None
        }
        if persistent_values != {self.config.persistent_session_id}:
            raise HermesTuiGatewayProtocolError(
                "session_resume_persistent_mismatch",
                "session.resume did not confirm the registered persistent session id.",
            )
        runtime_id = _optional_text(result.get("session_id"))
        if runtime_id is None:
            raise HermesTuiGatewayProtocolError(
                "runtime_session_id_missing", "session.resume returned no runtime session id."
            )
        self.runtime_session_id = runtime_id
        self.identity_evidence["resumePersistentIdVerified"] = True
        self.identity_evidence["runtimeSessionId"] = runtime_id
        self.identity_evidence["runtimeSessionIdEqualsPersistent"] = (
            runtime_id == self.config.persistent_session_id
        )
        info = result.get("info")
        if not isinstance(info, Mapping):
            raise HermesTuiGatewayProtocolError(
                "session_resume_info_missing", "session.resume returned no stable info object."
            )
        returned_cwd = _optional_text(info.get("cwd"))
        if returned_cwd is None:
            raise HermesTuiGatewayProtocolError(
                "session_cwd_unverified", "session.resume info did not expose cwd."
            )
        expected = os.path.normcase(str(Path(self.config.cwd).resolve(strict=False)))
        actual = os.path.normcase(str(Path(returned_cwd).resolve(strict=False)))
        if expected != actual:
            raise HermesTuiGatewayProtocolError(
                "session_cwd_mismatch",
                f"session.resume cwd {returned_cwd!r} does not match registered cwd.",
            )
        self.identity_evidence["cwdVerification"] = "verified"
        self.identity_evidence["gatewayReportedCwd"] = returned_cwd
        for field_name, expected_value, evidence_key in (
            ("source", self.config.registered_source, "gatewayReportedSource"),
            ("runtime_home", self.config.runtime_home, "gatewayReportedRuntimeHome"),
        ):
            value = _optional_text(info.get(field_name))
            if value is None:
                continue
            self.identity_evidence[evidence_key] = value
            if expected_value is not None and os.path.normcase(value) != os.path.normcase(
                expected_value
            ):
                raise HermesTuiGatewayProtocolError(
                    "session_identity_mismatch",
                    f"session.resume info field {field_name!r} mismatched registered identity.",
                )

    def _interrupt_once(self) -> None:
        if self.interrupt_attempted or self.runtime_session_id is None:
            return
        self.interrupt_attempted = True
        try:
            result = self._request(
                "session.interrupt", {"session_id": self.runtime_session_id}
            )
        except Exception as exc:
            self.interrupt_status = f"failed:{exc.__class__.__name__}"
            self.diagnostics.append(f"interrupt failed: {exc}")
        else:
            self.interrupt_status = (
                str(result.get("status") or "completed")
                if isinstance(result, Mapping)
                else "completed"
            )

    def _cleanup(self) -> int | None:
        process = self.process
        if process is None:
            self.cleanup_status = "not_started"
            return None
        self.stop.set()
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        try:
            code = process.wait(timeout=self.config.cleanup_timeout_seconds)
            self.cleanup_status = "exited"
            return self._finish_cleanup(code)
        except subprocess.TimeoutExpired:
            pass
        try:
            _terminate_gateway_process(process, force=False)
            code = process.wait(timeout=self.config.cleanup_timeout_seconds)
            self.cleanup_status = "terminated"
            return self._finish_cleanup(code)
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            _terminate_gateway_process(process, force=True)
            code = process.wait(timeout=self.config.cleanup_timeout_seconds)
            self.cleanup_status = "killed"
            return self._finish_cleanup(code)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.cleanup_status = "failed"
            self.diagnostics.append(f"cleanup failed: {exc}")
            return self._finish_cleanup(process.poll())

    def _finish_cleanup(self, exit_code: int | None) -> int | None:
        process = self.process
        if process is None:
            return exit_code
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        for thread in self.reader_threads:
            thread.join(timeout=self.config.cleanup_timeout_seconds)
        return exit_code


def _start_gateway_process(
    argv: Sequence[str], cwd: str, environment: Mapping[str, str]
) -> GatewayProcess:
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    return subprocess.Popen(
        tuple(argv),
        cwd=cwd,
        env=dict(environment),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        text=False,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )


def _read_pipe_chunk(stream: BinaryIO) -> bytes:
    read1 = getattr(stream, "read1", None)
    if callable(read1):
        return read1(4096)
    return stream.read(4096)


def _terminate_gateway_process(process: GatewayProcess, *, force: bool) -> None:
    """Terminate the bounded gateway operation and its isolated process tree."""

    if not isinstance(process, subprocess.Popen):
        if force:
            process.kill()
        else:
            process.terminate()
        return
    if os.name == "nt":
        if not force:
            process.terminate()
            return
        completed = subprocess.run(
            ("taskkill.exe", "/PID", str(process.pid), "/T", "/F"),
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5.0,
        )
        if completed.returncode != 0 and process.poll() is None:
            process.kill()
        return
    try:
        os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        if force:
            process.kill()
        else:
            process.terminate()


def _capabilities_0190() -> Mapping[str, object]:
    return {
        "schema": "hermes_tui_gateway_capabilities.v1",
        "version": HERMES_TUI_GATEWAY_SUPPORTED_VERSION,
        "transport": "stdio_jsonrpc_2_jsonl",
        "readyHandshake": "event.gateway.ready",
        "initializeRpc": False,
        "persistentAndRuntimeSessionIdsDistinct": True,
        "sessionListIncludesSource": True,
        "sessionListIncludesCwd": False,
        "resumeInfoIncludesCwd": True,
        "approvalCorrelation": "runtime_session_id",
        "clarifyCorrelation": "request_id",
        "sudoCorrelation": "request_id",
        "secretCorrelation": "request_id",
        "toolProgressEvent": False,
        "rewindFieldsForbiddenForOrdinarySubmit": True,
    }


def _capabilities_main_advisory() -> Mapping[str, object]:
    """Document audited main drift without making that version executable."""

    return {
        "version": HERMES_TUI_GATEWAY_MAIN_ADVISORY_VERSION,
        "supported": False,
        "selectionPolicy": "advisory_only_exact_stable_preflight_rejects",
        "approvalCorrelation": "request_id",
        "clarifyCorrelation": "request_id_and_optional_question_id",
        "sudoCorrelation": "request_id",
        "secretCorrelation": "request_id",
        "rewindFieldsPresentUpstream": True,
    }


def _bool_mapping(value: object, keys: Sequence[str]) -> Mapping[str, bool]:
    source = value if isinstance(value, Mapping) else {}
    return {key: source.get(key) is True for key in keys}


def _optional_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _bounded_text(value: str | None, max_chars: int) -> str:
    text = (value or "").strip()
    return text if len(text) <= max_chars else text[-max_chars:]
