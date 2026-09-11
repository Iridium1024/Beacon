from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
import os
import queue
import signal
import subprocess
import threading
import time
from typing import Callable, Mapping, Sequence, TextIO


class CodexAppServerApprovalDecision(StrEnum):
    """Decision used for unattended app-server approval requests."""

    DECLINE = "decline"
    CANCEL = "cancel"
    ACCEPT = "accept"
    ACCEPT_FOR_SESSION = "accept_for_session"


class CodexAppServerRunStatus(StrEnum):
    """Provider-side outcome for one Beacon-owned app-server connection."""

    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    BUSY = "busy"


@dataclass(frozen=True, slots=True)
class CodexAppServerPointReadResult:
    """One bounded thread/read query through a short-lived stdio connection."""

    status: str
    process_started: bool
    initialized: bool = False
    thread_found: bool = False
    native_thread_id: str | None = None
    native_session_id: str | None = None
    thread_status: str | None = None
    active_flags: tuple[str, ...] = ()
    process_exit_code: int | None = None
    failure_category: str | None = None
    failure_reason: str | None = None
    retryable: bool | None = None

    def to_metadata(self) -> Mapping[str, object]:
        result: dict[str, object] = {
            "schema": "codex_app_server_point_read.v1",
            "status": self.status,
            "transport": "stdio",
            "stableApiOnly": True,
            "processStarted": self.process_started,
            "initialized": self.initialized,
            "threadFound": self.thread_found,
            "activeFlags": list(self.active_flags),
        }
        for key, value in (
            ("nativeThreadId", self.native_thread_id),
            ("nativeSessionId", self.native_session_id),
            ("threadStatus", self.thread_status),
            ("processExitCode", self.process_exit_code),
            ("failureCategory", self.failure_category),
            ("failureReason", self.failure_reason),
            ("retryable", self.retryable),
        ):
            if value is not None:
                result[key] = value
        return result


@dataclass(frozen=True, slots=True)
class CodexAppServerRunResult:
    """Bounded, transcript-free result from one app-server turn."""

    status: CodexAppServerRunStatus | str
    process_started: bool
    process_exit_code: int | None = None
    process_timed_out: bool = False
    process_terminated: bool = False
    stdin_closed: bool = False
    initialized: bool = False
    initialize_user_agent: str | None = None
    thread_verified: bool = False
    resume_policy_verified: bool = False
    requested_cwd: str | None = None
    effective_cwd: str | None = None
    requested_sandbox: str | None = None
    effective_sandbox: str | None = None
    effective_network_access: bool | None = None
    requested_approval_policy: str | None = None
    effective_approval_policy: str | None = None
    requested_writable_roots: tuple[str, ...] = ()
    effective_writable_roots: tuple[str, ...] = ()
    native_thread_id: str | None = None
    native_session_id: str | None = None
    native_turn_id: str | None = None
    initial_thread_status: str | None = None
    final_thread_status: str | None = None
    turn_status: str | None = None
    final_response: str | None = None
    response_phase: str | None = None
    notification_methods: tuple[str, ...] = ()
    client_request_methods: tuple[str, ...] = ()
    server_request_methods: tuple[str, ...] = ()
    approval_request_count: int = 0
    server_request_resolved_count: int = 0
    approval_decisions: tuple[str, ...] = ()
    warning_messages: tuple[str, ...] = ()
    protocol_error_count: int = 0
    event_count: int = 0
    stderr_tail: str | None = None
    failure_category: str | None = None
    failure_reason: str | None = None
    retryable: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", CodexAppServerRunStatus(self.status))
        object.__setattr__(
            self,
            "notification_methods",
            tuple(self.notification_methods),
        )
        object.__setattr__(
            self,
            "client_request_methods",
            tuple(self.client_request_methods),
        )
        object.__setattr__(
            self,
            "server_request_methods",
            tuple(self.server_request_methods),
        )
        object.__setattr__(
            self,
            "approval_decisions",
            tuple(self.approval_decisions),
        )
        object.__setattr__(
            self,
            "requested_writable_roots",
            tuple(self.requested_writable_roots),
        )
        object.__setattr__(
            self,
            "effective_writable_roots",
            tuple(self.effective_writable_roots),
        )
        object.__setattr__(self, "warning_messages", tuple(self.warning_messages))

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "schema": "codex_app_server_run.v1",
            "status": self.status.value,
            "transport": "stdio",
            "stableApiOnly": True,
            "experimentalApiEnabled": False,
            "processStarted": self.process_started,
            "processTimedOut": self.process_timed_out,
            "processTerminated": self.process_terminated,
            "stdinClosed": self.stdin_closed,
            "initialized": self.initialized,
            "threadVerified": self.thread_verified,
            "resumePolicyVerified": self.resume_policy_verified,
            "requestedWritableRoots": list(self.requested_writable_roots),
            "effectiveWritableRoots": list(self.effective_writable_roots),
            "approvalRequestCount": self.approval_request_count,
            "serverRequestResolvedCount": self.server_request_resolved_count,
            "approvalDecisions": list(self.approval_decisions),
            "notificationMethods": list(self.notification_methods),
            "clientRequestMethods": list(self.client_request_methods),
            "serverRequestMethods": list(self.server_request_methods),
            "warningMessages": list(self.warning_messages),
            "protocolErrorCount": self.protocol_error_count,
            "eventCount": self.event_count,
            "fullSessionHistoryRead": False,
            "browserOrDesktopInputInjected": False,
            "remoteControlEnabled": False,
        }
        for key, value in (
            ("processExitCode", self.process_exit_code),
            ("initializeUserAgent", self.initialize_user_agent),
            ("requestedCwd", self.requested_cwd),
            ("effectiveCwd", self.effective_cwd),
            ("requestedSandbox", self.requested_sandbox),
            ("effectiveSandbox", self.effective_sandbox),
            ("effectiveNetworkAccess", self.effective_network_access),
            ("requestedApprovalPolicy", self.requested_approval_policy),
            ("effectiveApprovalPolicy", self.effective_approval_policy),
            ("nativeThreadId", self.native_thread_id),
            ("nativeSessionId", self.native_session_id),
            ("nativeTurnId", self.native_turn_id),
            ("initialThreadStatus", self.initial_thread_status),
            ("finalThreadStatus", self.final_thread_status),
            ("turnStatus", self.turn_status),
            ("responsePhase", self.response_phase),
            ("stderrTail", self.stderr_tail),
            ("failureCategory", self.failure_category),
            ("failureReason", self.failure_reason),
            ("retryable", self.retryable),
        ):
            if value is not None:
                metadata[key] = value
        return metadata


def normalize_codex_app_server_approval_decision(
    value: CodexAppServerApprovalDecision | str,
) -> CodexAppServerApprovalDecision:
    if isinstance(value, CodexAppServerApprovalDecision):
        return value
    text = str(value).strip().lower().replace("-", "_")
    aliases = {
        "acceptforsession": CodexAppServerApprovalDecision.ACCEPT_FOR_SESSION,
        "accept_for_session": CodexAppServerApprovalDecision.ACCEPT_FOR_SESSION,
        "accept": CodexAppServerApprovalDecision.ACCEPT,
        "decline": CodexAppServerApprovalDecision.DECLINE,
        "cancel": CodexAppServerApprovalDecision.CANCEL,
    }
    if text not in aliases:
        raise ValueError(
            "codexAppServerApprovalDecision must be one of: "
            "decline, cancel, accept, accept_for_session."
        )
    return aliases[text]


def render_codex_app_server_argv(
    *,
    codex_executable: str = "codex",
) -> tuple[str, ...]:
    executable = _non_empty_text(codex_executable, "codexExecutable")
    return (executable, "app-server", "--stdio")


def build_codex_app_server_resume_params(
    *,
    thread_id: str,
    cwd: str,
    add_dirs: Sequence[str] = (),
    sandbox_mode: str | None = None,
    approval_policy: str | None = None,
) -> Mapping[str, object]:
    """Render stable thread/resume overrides without changing permission posture."""

    params: dict[str, object] = {
        "threadId": _non_empty_text(thread_id, "threadId"),
        "cwd": _non_empty_text(cwd, "cwd"),
    }
    if sandbox_mode is not None:
        params["sandbox"] = _sandbox_mode(sandbox_mode)
    if approval_policy is not None:
        params["approvalPolicy"] = _approval_policy(approval_policy)
    normalized_add_dirs = _unique_non_empty_paths(add_dirs)
    if normalized_add_dirs:
        params["config"] = {
            "sandbox_workspace_write": {
                "writable_roots": list(normalized_add_dirs),
            }
        }
    return params


def run_codex_app_server_activation(
    argv: Sequence[str],
    *,
    cwd: str,
    thread_id: str,
    input_text: str,
    add_dirs: Sequence[str] = (),
    sandbox_mode: str | None = None,
    approval_policy: str | None = None,
    approval_decision: CodexAppServerApprovalDecision | str = (
        CodexAppServerApprovalDecision.DECLINE
    ),
    timeout_seconds: int = 120,
    client_version: str = "0.1.1",
    environment: Mapping[str, str] | None = None,
    on_started: Callable[[], None] | None = None,
    on_runtime_event: Callable[[Mapping[str, object]], None] | None = None,
    load_pending_supplements: (
        Callable[[str, str], Sequence[Mapping[str, object]]] | None
    ) = None,
    on_supplement_outcome: (
        Callable[[Mapping[str, object]], None] | None
    ) = None,
) -> CodexAppServerRunResult:
    """Run a complete stored-thread turn through a Beacon-owned stdio server."""

    command = tuple(_non_empty_text(item, "argv") for item in argv)
    if not command:
        raise ValueError("argv must not be empty.")
    resolved_cwd = _non_empty_text(cwd, "cwd")
    requested_thread_id = _non_empty_text(thread_id, "threadId")
    prompt = _non_empty_text(input_text, "inputText")
    if timeout_seconds <= 0:
        raise ValueError("timeoutSeconds must be greater than 0.")
    decision = normalize_codex_app_server_approval_decision(approval_decision)
    resume_params = build_codex_app_server_resume_params(
        thread_id=requested_thread_id,
        cwd=resolved_cwd,
        add_dirs=add_dirs,
        sandbox_mode=sandbox_mode,
        approval_policy=approval_policy,
    )
    state = _CodexAppServerState(
        requested_thread_id=requested_thread_id,
        approval_decision=decision,
        requested_cwd=resolved_cwd,
        requested_sandbox=(
            str(resume_params["sandbox"])
            if resume_params.get("sandbox") is not None
            else None
        ),
        requested_approval_policy=(
            str(resume_params["approvalPolicy"])
            if resume_params.get("approvalPolicy") is not None
            else None
        ),
        requested_writable_roots=_unique_non_empty_paths(add_dirs),
    )
    process: subprocess.Popen[str] | None = None
    transport: _CodexAppServerTransport | None = None
    process_started = False
    process_timed_out = False
    process_terminated = False
    stdin_closed = False
    failure_category: str | None = None
    failure_reason: str | None = None
    retryable: bool | None = None
    status = CodexAppServerRunStatus.FAILED
    deadline = time.monotonic() + timeout_seconds

    try:
        process = subprocess.Popen(
            list(command),
            cwd=resolved_cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
            env=(dict(environment) if environment is not None else None),
            **({"start_new_session": True} if os.name != "nt" else {}),
        )
        process_started = True
        transport = _CodexAppServerTransport(
            process,
            state=state,
            on_runtime_event=on_runtime_event,
        )
        _emit_callback(
            on_runtime_event,
            {
                "state": "starting",
                "nativeThreadId": requested_thread_id,
                "threadVerified": False,
                "ownerConnectionAlive": True,
            },
            state=state,
        )
        if on_started is not None:
            on_started()
        initialize = transport.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "beacon",
                    "title": "Beacon",
                    "version": _non_empty_text(client_version, "clientVersion"),
                }
            },
            deadline=deadline,
        )
        state.initialized = True
        if isinstance(initialize, Mapping):
            user_agent = initialize.get("userAgent")
            if isinstance(user_agent, str) and user_agent.strip():
                state.initialize_user_agent = user_agent.strip()
        transport.notify("initialized", {})
        state.protocol_ready = True

        read_result = transport.request(
            "thread/read",
            {"threadId": requested_thread_id, "includeTurns": False},
            deadline=deadline,
        )
        thread = _result_object(read_result, "thread", "thread/read")
        native_thread_id = _mapping_text(thread, "id")
        if native_thread_id != requested_thread_id:
            raise _CodexAppServerFailure(
                "app_server_thread_mismatch",
                "thread/read returned a different thread id.",
                retryable=False,
            )
        state.thread_verified = True
        state.native_thread_id = native_thread_id
        state.native_session_id = _mapping_optional_text(thread, "sessionId")
        state.initial_thread_status = _thread_status_type(thread.get("status"))
        state.final_thread_status = state.initial_thread_status
        _emit_callback(
            on_runtime_event,
            {
                "state": (
                    "active" if state.initial_thread_status == "active" else "idle"
                ),
                "nativeThreadId": state.native_thread_id,
                "nativeSessionId": state.native_session_id,
                "threadVerified": True,
                "ownerConnectionAlive": True,
            },
            state=state,
        )
        if state.initial_thread_status == "active":
            status = CodexAppServerRunStatus.BUSY
            failure_category = "app_server_thread_busy"
            failure_reason = "Codex thread is already active; Beacon did not start a second turn."
            retryable = True
        elif state.initial_thread_status == "systemError":
            raise _CodexAppServerFailure(
                "app_server_thread_system_error",
                "Codex reported a system error for the stored thread.",
                retryable=True,
            )
        else:
            resumed = transport.request(
                "thread/resume",
                resume_params,
                deadline=deadline,
            )
            resumed_thread = _result_object(resumed, "thread", "thread/resume")
            resumed_thread_id = _mapping_text(resumed_thread, "id")
            if resumed_thread_id != requested_thread_id:
                raise _CodexAppServerFailure(
                    "app_server_resume_thread_mismatch",
                    "thread/resume returned a different thread id.",
                    retryable=False,
                )
            _verify_codex_app_server_resume_policy(
                resumed,
                state=state,
            )
            state.native_session_id = (
                _mapping_optional_text(resumed_thread, "sessionId")
                or state.native_session_id
            )
            turn_result = transport.request(
                "turn/start",
                {
                    "threadId": requested_thread_id,
                    "input": [{"type": "text", "text": prompt}],
                },
                deadline=deadline,
            )
            turn = _result_object(turn_result, "turn", "turn/start")
            state.native_turn_id = _mapping_text(turn, "id")
            state.turn_status = _mapping_optional_text(turn, "status")
            _emit_callback(
                on_runtime_event,
                {
                    "state": "active",
                    "nativeThreadId": state.native_thread_id,
                    "nativeSessionId": state.native_session_id,
                    "nativeTurnId": state.native_turn_id,
                    "threadVerified": True,
                    "ownerConnectionAlive": True,
                },
                state=state,
            )
            transport.wait_for_turn_completion(
                deadline=deadline,
                load_pending_supplements=load_pending_supplements,
                on_supplement_outcome=on_supplement_outcome,
            )
            if state.turn_status == "completed":
                status = CodexAppServerRunStatus.COMPLETED
                retryable = None
            elif state.turn_status == "interrupted":
                status = CodexAppServerRunStatus.INTERRUPTED
                failure_category = "app_server_turn_interrupted"
                failure_reason = "Codex app-server reported an interrupted turn."
                retryable = False
            else:
                status = CodexAppServerRunStatus.FAILED
                failure_category = "app_server_turn_failed"
                failure_reason = state.turn_error or "Codex app-server turn failed."
                retryable = _retryable_text(failure_reason)
            _emit_callback(
                on_runtime_event,
                {
                    "state": (
                        "completed"
                        if status is CodexAppServerRunStatus.COMPLETED
                        else "interrupted"
                        if status is CodexAppServerRunStatus.INTERRUPTED
                        else "failed"
                    ),
                    "nativeThreadId": state.native_thread_id,
                    "nativeSessionId": state.native_session_id,
                    "nativeTurnId": state.native_turn_id,
                    "threadVerified": True,
                    "ownerConnectionAlive": True,
                },
                state=state,
            )
    except TimeoutError as exc:
        process_timed_out = True
        status = CodexAppServerRunStatus.FAILED
        failure_category = "app_server_timeout"
        failure_reason = str(exc)
        retryable = True
        if transport is not None and state.native_turn_id is not None:
            try:
                transport.request(
                    "turn/interrupt",
                    {
                        "threadId": requested_thread_id,
                        "turnId": state.native_turn_id,
                    },
                    deadline=time.monotonic() + 2,
                )
            except (OSError, TimeoutError, _CodexAppServerFailure):
                pass
        _emit_callback(
            on_runtime_event,
            {
                "state": "failed",
                "nativeThreadId": state.native_thread_id or requested_thread_id,
                "nativeSessionId": state.native_session_id,
                "nativeTurnId": state.native_turn_id,
                "threadVerified": state.thread_verified,
                "ownerConnectionAlive": True,
            },
            state=state,
        )
    except _CodexAppServerFailure as exc:
        status = CodexAppServerRunStatus.FAILED
        failure_category = exc.category
        failure_reason = str(exc)
        retryable = exc.retryable
        _emit_callback(
            on_runtime_event,
            {
                "state": "failed",
                "nativeThreadId": state.native_thread_id or requested_thread_id,
                "nativeSessionId": state.native_session_id,
                "nativeTurnId": state.native_turn_id,
                "threadVerified": state.thread_verified,
                "ownerConnectionAlive": True,
            },
            state=state,
        )
    except (OSError, ValueError) as exc:
        status = CodexAppServerRunStatus.FAILED
        failure_category = _classify_process_exception(exc)
        failure_reason = f"{exc.__class__.__name__}: {exc}"
        retryable = failure_category not in {
            "app_server_executable_not_found",
            "app_server_permission_denied",
            "app_server_invalid_protocol",
        }
        _emit_callback(
            on_runtime_event,
            {
                "state": "failed",
                "nativeThreadId": state.native_thread_id or requested_thread_id,
                "nativeSessionId": state.native_session_id,
                "nativeTurnId": state.native_turn_id,
                "threadVerified": state.thread_verified,
                "ownerConnectionAlive": transport is not None,
            },
            state=state,
        )
    finally:
        if transport is not None:
            transport.settle_pending_supplements(
                load_pending_supplements=load_pending_supplements,
                on_supplement_outcome=on_supplement_outcome,
            )
        if transport is not None:
            stdin_closed = transport.close_stdin()
        if process is not None:
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process_terminated = True
                _terminate_process_tree(process)
            if transport is not None:
                transport.join_readers(timeout=1)
                transport.close_output_pipes()
        _emit_callback(
            on_runtime_event,
            {
                "state": "closed",
                "nativeThreadId": state.native_thread_id or requested_thread_id,
                "nativeSessionId": state.native_session_id,
                "nativeTurnId": state.native_turn_id,
                "threadVerified": state.thread_verified,
                "ownerConnectionAlive": False,
            },
            state=state,
        )

    process_exit_code = process.poll() if process is not None else None
    stderr_tail = transport.stderr_tail() if transport is not None else None
    if (
        status is CodexAppServerRunStatus.COMPLETED
        and process_exit_code not in {0, None}
    ):
        status = CodexAppServerRunStatus.FAILED
        failure_category = "app_server_process_exit_failed"
        failure_reason = f"app-server exited with code {process_exit_code}."
        retryable = True
    return CodexAppServerRunResult(
        status=status,
        process_started=process_started,
        process_exit_code=process_exit_code,
        process_timed_out=process_timed_out,
        process_terminated=process_terminated,
        stdin_closed=stdin_closed,
        initialized=state.initialized,
        initialize_user_agent=state.initialize_user_agent,
        thread_verified=state.thread_verified,
        resume_policy_verified=state.resume_policy_verified,
        requested_cwd=state.requested_cwd,
        effective_cwd=state.effective_cwd,
        requested_sandbox=state.requested_sandbox,
        effective_sandbox=state.effective_sandbox,
        effective_network_access=state.effective_network_access,
        requested_approval_policy=state.requested_approval_policy,
        effective_approval_policy=state.effective_approval_policy,
        requested_writable_roots=tuple(state.requested_writable_roots),
        effective_writable_roots=tuple(state.effective_writable_roots),
        native_thread_id=state.native_thread_id,
        native_session_id=state.native_session_id,
        native_turn_id=state.native_turn_id,
        initial_thread_status=state.initial_thread_status,
        final_thread_status=state.final_thread_status,
        turn_status=state.turn_status,
        final_response=state.final_response(),
        response_phase=state.response_phase(),
        notification_methods=tuple(state.notification_methods),
        client_request_methods=tuple(state.client_request_methods),
        server_request_methods=tuple(state.server_request_methods),
        approval_request_count=state.approval_request_count,
        server_request_resolved_count=state.server_request_resolved_count,
        approval_decisions=tuple(state.approval_decisions),
        warning_messages=tuple(state.warning_messages),
        protocol_error_count=state.protocol_error_count,
        event_count=state.event_count,
        stderr_tail=stderr_tail,
        failure_category=failure_category,
        failure_reason=failure_reason,
        retryable=retryable,
    )


def read_codex_app_server_thread(
    argv: Sequence[str],
    *,
    cwd: str,
    thread_id: str,
    timeout_seconds: int = 20,
    client_version: str = "0.1.1",
    environment: Mapping[str, str] | None = None,
) -> CodexAppServerPointReadResult:
    """Read one stored thread without resuming it or starting a turn."""

    command = tuple(_non_empty_text(item, "argv") for item in argv)
    if not command:
        raise ValueError("argv must not be empty.")
    resolved_cwd = _non_empty_text(cwd, "cwd")
    requested_thread_id = _non_empty_text(thread_id, "threadId")
    if timeout_seconds <= 0:
        raise ValueError("timeoutSeconds must be greater than 0.")
    state = _CodexAppServerState(
        requested_thread_id=requested_thread_id,
        approval_decision=CodexAppServerApprovalDecision.DECLINE,
    )
    process: subprocess.Popen[str] | None = None
    transport: _CodexAppServerTransport | None = None
    initialized = False
    thread_found = False
    native_thread_id: str | None = None
    native_session_id: str | None = None
    thread_status: str | None = None
    active_flags: tuple[str, ...] = ()
    failure_category: str | None = None
    failure_reason: str | None = None
    retryable: bool | None = None
    status = "failed"
    deadline = time.monotonic() + timeout_seconds
    try:
        process = subprocess.Popen(
            list(command),
            cwd=resolved_cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
            env=(dict(environment) if environment is not None else None),
            **({"start_new_session": True} if os.name != "nt" else {}),
        )
        transport = _CodexAppServerTransport(process, state=state)
        transport.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "beacon",
                    "title": "Beacon",
                    "version": _non_empty_text(client_version, "clientVersion"),
                }
            },
            deadline=deadline,
        )
        initialized = True
        state.initialized = True
        transport.notify("initialized", {})
        state.protocol_ready = True
        result = transport.request(
            "thread/read",
            {"threadId": requested_thread_id, "includeTurns": False},
            deadline=deadline,
        )
        thread = _result_object(result, "thread", "thread/read")
        native_thread_id = _mapping_text(thread, "id")
        if native_thread_id != requested_thread_id:
            raise _CodexAppServerFailure(
                "app_server_thread_mismatch",
                "thread/read returned a different thread id.",
                retryable=False,
            )
        native_session_id = _mapping_optional_text(thread, "sessionId")
        status_object = thread.get("status")
        thread_status = _thread_status_type(status_object)
        if isinstance(status_object, Mapping):
            flags = status_object.get("activeFlags")
            if isinstance(flags, Sequence) and not isinstance(flags, (str, bytes)):
                active_flags = tuple(str(flag) for flag in flags)
        thread_found = True
        status = "ok"
    except _CodexAppServerFailure as exc:
        failure_category = exc.category
        failure_reason = str(exc)
        retryable = exc.retryable
        status = "not_found" if exc.category == "app_server_thread_not_found" else "failed"
    except (OSError, ValueError, TimeoutError) as exc:
        failure_category = (
            "app_server_timeout"
            if isinstance(exc, TimeoutError)
            else _classify_process_exception(exc)
        )
        failure_reason = f"{exc.__class__.__name__}: {exc}"
        retryable = failure_category not in {
            "app_server_executable_not_found",
            "app_server_permission_denied",
            "app_server_invalid_protocol",
        }
    finally:
        if transport is not None:
            transport.close_stdin()
        if process is not None:
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                _terminate_process_tree(process)
            if transport is not None:
                transport.join_readers(timeout=1)
                transport.close_output_pipes()
    return CodexAppServerPointReadResult(
        status=status,
        process_started=process is not None,
        initialized=initialized,
        thread_found=thread_found,
        native_thread_id=native_thread_id,
        native_session_id=native_session_id,
        thread_status=thread_status,
        active_flags=active_flags,
        process_exit_code=process.poll() if process is not None else None,
        failure_category=failure_category,
        failure_reason=failure_reason,
        retryable=retryable,
    )


@dataclass(slots=True)
class _CodexAppServerState:
    requested_thread_id: str
    approval_decision: CodexAppServerApprovalDecision
    requested_cwd: str | None = None
    requested_sandbox: str | None = None
    requested_approval_policy: str | None = None
    requested_writable_roots: tuple[str, ...] = ()
    initialized: bool = False
    protocol_ready: bool = False
    initialize_user_agent: str | None = None
    thread_verified: bool = False
    resume_policy_verified: bool = False
    effective_cwd: str | None = None
    effective_sandbox: str | None = None
    effective_network_access: bool | None = None
    effective_approval_policy: str | None = None
    effective_writable_roots: tuple[str, ...] = ()
    native_thread_id: str | None = None
    native_session_id: str | None = None
    native_turn_id: str | None = None
    initial_thread_status: str | None = None
    final_thread_status: str | None = None
    turn_status: str | None = None
    turn_error: str | None = None
    notification_methods: list[str] = field(default_factory=list)
    client_request_methods: list[str] = field(default_factory=list)
    server_request_methods: list[str] = field(default_factory=list)
    approval_request_count: int = 0
    server_request_resolved_count: int = 0
    handled_server_request_ids: set[object] = field(default_factory=set)
    approval_decisions: list[str] = field(default_factory=list)
    warning_messages: list[str] = field(default_factory=list)
    protocol_error_count: int = 0
    event_count: int = 0
    agent_messages: list[tuple[str | None, str]] = field(default_factory=list)

    def final_response(self) -> str | None:
        for phase, text in reversed(self.agent_messages):
            if phase == "final_answer":
                return text
        for phase, text in reversed(self.agent_messages):
            if phase != "commentary":
                return text
        return None

    def response_phase(self) -> str | None:
        response = self.final_response()
        if response is None:
            return None
        for phase, text in reversed(self.agent_messages):
            if text == response:
                return phase or "unknown"
        return None


class _CodexAppServerTransport:
    def __init__(
        self,
        process: subprocess.Popen[str],
        *,
        state: _CodexAppServerState,
        on_runtime_event: Callable[[Mapping[str, object]], None] | None = None,
    ) -> None:
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise OSError("app-server stdio pipes were not created.")
        self.process = process
        self.state = state
        self.on_runtime_event = on_runtime_event
        self.stdin: TextIO = process.stdin
        self.stdout: TextIO = process.stdout
        self.stderr: TextIO = process.stderr
        self.messages: queue.Queue[tuple[str, str | None]] = queue.Queue()
        self.pending_responses: dict[object, Mapping[str, object]] = {}
        self.completed_response_ids: set[object] = set()
        self.stderr_lines: list[str] = []
        self.next_request_id = 1
        self.stdout_thread = threading.Thread(
            target=self._read_stdout,
            name="beacon-codex-app-server-stdout",
            daemon=True,
        )
        self.stderr_thread = threading.Thread(
            target=self._read_stderr,
            name="beacon-codex-app-server-stderr",
            daemon=True,
        )
        self.stdout_thread.start()
        self.stderr_thread.start()

    def _read_stdout(self) -> None:
        try:
            for line in self.stdout:
                self.messages.put(("stdout", line))
        finally:
            self.messages.put(("stdout_eof", None))

    def _read_stderr(self) -> None:
        try:
            for line in self.stderr:
                self.stderr_lines.append(line.rstrip())
                if len(self.stderr_lines) > 100:
                    del self.stderr_lines[:50]
        finally:
            self.messages.put(("stderr_eof", None))

    def notify(self, method: str, params: Mapping[str, object]) -> None:
        self._send({"method": method, "params": dict(params)})

    def request(
        self,
        method: str,
        params: Mapping[str, object],
        *,
        deadline: float,
    ) -> Mapping[str, object]:
        self.state.client_request_methods.append(method)
        request_id = self.next_request_id
        self.next_request_id += 1
        self._send({"method": method, "id": request_id, "params": dict(params)})
        while True:
            pending = self.pending_responses.pop(request_id, None)
            if pending is not None:
                self.completed_response_ids.add(request_id)
                return self._response_result(method, pending)
            message = self._next_protocol_message(deadline)
            if _is_server_request(message):
                self._handle_server_request(message)
                continue
            if _is_notification(message):
                self._handle_notification(message)
                continue
            response_id = message.get("id")
            if response_id in self.completed_response_ids:
                self.state.protocol_error_count += 1
                raise _CodexAppServerFailure(
                    "app_server_duplicate_response",
                    "Codex app-server repeated a completed response id.",
                    retryable=False,
                )
            if response_id == request_id:
                self.completed_response_ids.add(request_id)
                return self._response_result(method, message)
            if response_id is not None:
                if response_id in self.pending_responses:
                    self.state.protocol_error_count += 1
                    raise _CodexAppServerFailure(
                        "app_server_duplicate_response",
                        "Codex app-server repeated a pending response id.",
                        retryable=False,
                    )
                self.pending_responses[response_id] = message

    def wait_for_turn_completion(
        self,
        *,
        deadline: float,
        load_pending_supplements: (
            Callable[[str, str], Sequence[Mapping[str, object]]] | None
        ) = None,
        on_supplement_outcome: (
            Callable[[Mapping[str, object]], None] | None
        ) = None,
    ) -> None:
        while self.state.turn_status not in {"completed", "failed", "interrupted"}:
            self._drain_pending_supplements(
                deadline=deadline,
                load_pending_supplements=load_pending_supplements,
                on_supplement_outcome=on_supplement_outcome,
            )
            message = self._next_protocol_message(
                deadline,
                on_idle=lambda: self._drain_pending_supplements(
                    deadline=deadline,
                    load_pending_supplements=load_pending_supplements,
                    on_supplement_outcome=on_supplement_outcome,
                ),
            )
            if _is_server_request(message):
                self._handle_server_request(message)
            elif _is_notification(message):
                self._handle_notification(message)
            elif message.get("id") is not None:
                response_id = message["id"]
                if (
                    response_id in self.completed_response_ids
                    or response_id in self.pending_responses
                ):
                    self.state.protocol_error_count += 1
                    raise _CodexAppServerFailure(
                        "app_server_duplicate_response",
                        "Codex app-server repeated a response id.",
                        retryable=False,
                    )
                self.pending_responses[response_id] = message

    def _drain_pending_supplements(
        self,
        *,
        deadline: float,
        load_pending_supplements: (
            Callable[[str, str], Sequence[Mapping[str, object]]] | None
        ),
        on_supplement_outcome: (
            Callable[[Mapping[str, object]], None] | None
        ),
    ) -> None:
        turn_id = self.state.native_turn_id
        thread_id = self.state.native_thread_id
        if (
            load_pending_supplements is None
            or on_supplement_outcome is None
            or turn_id is None
            or thread_id is None
        ):
            return
        try:
            pending = tuple(load_pending_supplements(thread_id, turn_id))
        except Exception as exc:  # callback failures must not abort the provider turn
            self.state.warning_messages.append(
                _truncate_text(f"supplement inbox read failed: {exc}", 500)
            )
            return
        for supplement in pending:
            supplement_id = _mapping_optional_text(supplement, "supplementId")
            expected_turn_id = _mapping_optional_text(supplement, "expectedTurnId")
            message = _mapping_optional_text(supplement, "message")
            if supplement_id is None:
                continue
            if expected_turn_id != turn_id:
                _emit_callback(
                    on_supplement_outcome,
                    {
                        "supplementId": supplement_id,
                        "status": "stale_turn",
                        "actualTurnId": turn_id,
                        "reason": "expectedTurnId does not match the active turn.",
                    },
                    state=self.state,
                )
                continue
            if message is None:
                _emit_callback(
                    on_supplement_outcome,
                    {
                        "supplementId": supplement_id,
                        "status": "rejected",
                        "actualTurnId": turn_id,
                        "reason": "queued supplement is missing its delivery message.",
                    },
                    state=self.state,
                )
                continue
            if not _emit_required_callback(
                on_supplement_outcome,
                {
                    "supplementId": supplement_id,
                    "status": "delivery_unknown",
                    "actualTurnId": turn_id,
                    "requiresUserReview": True,
                    "reason": (
                        "Beacon marked delivery ambiguous before writing turn/steer; "
                        "it will not automatically resend after a crash or disconnect."
                    ),
                },
                state=self.state,
            ):
                continue
            try:
                result = self.request(
                    "turn/steer",
                    {
                        "threadId": thread_id,
                        "expectedTurnId": turn_id,
                        "input": [{"type": "text", "text": message}],
                    },
                    deadline=deadline,
                )
                response_turn_id = _mapping_text(result, "turnId")
                if response_turn_id != turn_id:
                    raise _CodexAppServerFailure(
                        "app_server_steer_turn_mismatch",
                        "turn/steer returned a different turn id.",
                        retryable=False,
                    )
            except _CodexAppServerFailure as exc:
                if exc.category == "app_server_method_not_supported":
                    outcome = "rejected"
                    outcome_failure_category = (
                        "app_server_steer_method_not_supported"
                    )
                elif exc.category in {
                    "app_server_steer_stale_turn",
                    "app_server_steer_turn_mismatch",
                }:
                    outcome = "stale_turn"
                    outcome_failure_category = exc.category
                elif exc.category == "app_server_steer_no_active_turn":
                    outcome = "no_active_turn"
                    outcome_failure_category = exc.category
                else:
                    # The pre-write delivery_unknown record is intentionally left
                    # terminal for transport/protocol ambiguity.
                    self.state.warning_messages.append(
                        _truncate_text(f"turn/steer delivery ambiguous: {exc}", 500)
                    )
                    continue
                _emit_callback(
                    on_supplement_outcome,
                    {
                        "supplementId": supplement_id,
                        "status": outcome,
                        "actualTurnId": turn_id,
                        "requiresUserReview": False,
                        "failureCategory": outcome_failure_category,
                        "reason": str(exc),
                    },
                    state=self.state,
                )
            except (OSError, TimeoutError) as exc:
                self.state.warning_messages.append(
                    _truncate_text(f"turn/steer transport ambiguity: {exc}", 500)
                )
            else:
                _emit_callback(
                    on_supplement_outcome,
                    {
                        "supplementId": supplement_id,
                        "status": "accepted",
                        "actualTurnId": turn_id,
                        "requiresUserReview": False,
                    },
                    state=self.state,
                )

    def settle_pending_supplements(
        self,
        *,
        load_pending_supplements: (
            Callable[[str, str], Sequence[Mapping[str, object]]] | None
        ),
        on_supplement_outcome: (
            Callable[[Mapping[str, object]], None] | None
        ),
    ) -> None:
        thread_id = self.state.native_thread_id
        turn_id = self.state.native_turn_id
        if (
            load_pending_supplements is None
            or on_supplement_outcome is None
            or thread_id is None
            or turn_id is None
        ):
            return
        try:
            pending = tuple(load_pending_supplements(thread_id, turn_id))
        except Exception as exc:
            self.state.warning_messages.append(
                _truncate_text(f"supplement final inbox read failed: {exc}", 500)
            )
            return
        for supplement in pending:
            supplement_id = _mapping_optional_text(supplement, "supplementId")
            if supplement_id is None:
                continue
            _emit_callback(
                on_supplement_outcome,
                {
                    "supplementId": supplement_id,
                    "status": "no_active_turn",
                    "actualTurnId": turn_id,
                    "reason": "The owning turn ended before this supplement was written.",
                },
                state=self.state,
            )

    def _response_result(
        self,
        method: str,
        message: Mapping[str, object],
    ) -> Mapping[str, object]:
        error = message.get("error")
        if isinstance(error, Mapping):
            code = error.get("code")
            detail = error.get("message")
            error_text = str(detail or "unknown app-server error")
            category = _request_error_category(method, code, error_text)
            raise _CodexAppServerFailure(
                category,
                f"{method} failed: {error_text}",
                retryable=_retryable_text(error_text),
            )
        result = message.get("result")
        if not isinstance(result, Mapping):
            raise _CodexAppServerFailure(
                "app_server_invalid_protocol",
                f"{method} returned a non-object result.",
                retryable=False,
            )
        return dict(result)

    def _next_protocol_message(
        self,
        deadline: float,
        *,
        on_idle: Callable[[], None] | None = None,
    ) -> Mapping[str, object]:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Codex app-server activation timed out.")
            try:
                kind, line = self.messages.get(timeout=min(remaining, 0.25))
            except queue.Empty:
                if self.process.poll() is not None:
                    raise _CodexAppServerFailure(
                        "app_server_early_exit",
                        "Codex app-server exited before completing the protocol.",
                        retryable=True,
                    )
                if on_idle is not None:
                    on_idle()
                continue
            if kind == "stderr_eof":
                continue
            if kind == "stdout_eof":
                raise _CodexAppServerFailure(
                    "app_server_early_eof",
                    "Codex app-server closed stdout before completing the protocol.",
                    retryable=True,
                )
            if line is None or not line.strip():
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                self.state.protocol_error_count += 1
                raise _CodexAppServerFailure(
                    "app_server_invalid_json",
                    f"Codex app-server emitted invalid JSONL: {exc}",
                    retryable=False,
                ) from exc
            if not isinstance(message, Mapping):
                self.state.protocol_error_count += 1
                raise _CodexAppServerFailure(
                    "app_server_invalid_protocol",
                    "Codex app-server emitted a non-object JSON message.",
                    retryable=False,
                )
            self.state.event_count += 1
            return dict(message)

    def _handle_notification(self, message: Mapping[str, object]) -> None:
        method = str(message.get("method") or "")
        params = message.get("params")
        if not self.state.protocol_ready:
            self.state.protocol_error_count += 1
            raise _CodexAppServerFailure(
                "app_server_notification_before_initialize",
                "Codex app-server emitted a notification before the initialize handshake completed.",
                retryable=False,
            )
        self.state.notification_methods.append(method)
        if not isinstance(params, Mapping):
            return
        if method == "serverRequest/resolved":
            if params.get("threadId") == self.state.requested_thread_id:
                self.state.server_request_resolved_count += 1
            return
        if method == "thread/status/changed":
            if params.get("threadId") == self.state.requested_thread_id:
                self.state.final_thread_status = _thread_status_type(
                    params.get("status")
                )
                status_payload = params.get("status")
                active_flags: list[str] = []
                if isinstance(status_payload, Mapping):
                    flags = status_payload.get("activeFlags")
                    if isinstance(flags, Sequence) and not isinstance(
                        flags, (str, bytes)
                    ):
                        active_flags = [str(flag) for flag in flags]
                runtime_state = {
                    "notLoaded": "idle",
                    "idle": "idle",
                    "active": "active",
                    "systemError": "failed",
                }.get(self.state.final_thread_status or "", "idle")
                _emit_callback(
                    self.on_runtime_event,
                    {
                        "state": runtime_state,
                        "nativeThreadId": self.state.native_thread_id,
                        "nativeSessionId": self.state.native_session_id,
                        "nativeTurnId": self.state.native_turn_id,
                        "threadVerified": self.state.thread_verified,
                        "activeFlags": active_flags,
                        "ownerConnectionAlive": True,
                    },
                    state=self.state,
                )
            return
        if method == "item/completed":
            if (
                params.get("threadId") == self.state.requested_thread_id
                and params.get("turnId") == self.state.native_turn_id
            ):
                self._record_agent_message(params.get("item"))
            return
        if method == "turn/completed":
            if params.get("threadId") != self.state.requested_thread_id:
                return
            turn = params.get("turn")
            if not isinstance(turn, Mapping):
                return
            turn_id = turn.get("id")
            if self.state.native_turn_id is not None and turn_id != self.state.native_turn_id:
                return
            self.state.turn_status = _mapping_optional_text(turn, "status")
            error = turn.get("error")
            if isinstance(error, Mapping):
                self.state.turn_error = _mapping_optional_text(error, "message")
            items = turn.get("items")
            if isinstance(items, Sequence) and not isinstance(items, (str, bytes)):
                for item in items:
                    self._record_agent_message(item)
            runtime_state = {
                "completed": "completed",
                "interrupted": "interrupted",
                "failed": "failed",
            }.get(self.state.turn_status or "", "failed")
            _emit_callback(
                self.on_runtime_event,
                {
                    "state": runtime_state,
                    "nativeThreadId": self.state.native_thread_id,
                    "nativeSessionId": self.state.native_session_id,
                    "nativeTurnId": self.state.native_turn_id,
                    "threadVerified": self.state.thread_verified,
                    "ownerConnectionAlive": True,
                },
                state=self.state,
            )
            return
        diagnostic = _notification_diagnostic(method, params)
        if diagnostic:
            self.state.warning_messages.append(_truncate_text(diagnostic, 500))

    def _record_agent_message(self, item: object) -> None:
        if not isinstance(item, Mapping) or item.get("type") != "agentMessage":
            return
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            return
        phase = item.get("phase")
        normalized_phase = phase if isinstance(phase, str) else None
        candidate = (normalized_phase, text.strip())
        if not self.state.agent_messages or self.state.agent_messages[-1] != candidate:
            self.state.agent_messages.append(candidate)

    def _handle_server_request(self, message: Mapping[str, object]) -> None:
        method = str(message.get("method") or "")
        request_id = message.get("id")
        params = message.get("params")
        request_params = dict(params) if isinstance(params, Mapping) else {}
        if not self.state.protocol_ready:
            self.state.protocol_error_count += 1
            raise _CodexAppServerFailure(
                "app_server_request_before_initialize",
                "Codex app-server emitted a server request before the initialize handshake completed.",
                retryable=False,
            )
        self.state.server_request_methods.append(method)
        if not _valid_server_request_id(request_id):
            self._reject_server_request(
                request_id,
                code=-32600,
                message="Codex app-server emitted an invalid server request id.",
            )
            return
        if request_id in self.state.handled_server_request_ids:
            self._reject_server_request(
                request_id,
                code=-32600,
                message="Codex app-server repeated a server request id.",
            )
            return
        self.state.handled_server_request_ids.add(request_id)
        known_method = method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
            "item/permissions/requestApproval",
            "mcpServer/elicitation/request",
            "item/tool/requestUserInput",
        }
        if not known_method:
            self._reject_server_request(
                request_id,
                code=-32601,
                message=f"Beacon does not support server request method {method}.",
            )
            return
        correlation_error = _server_request_correlation_error(
            method,
            request_params,
            state=self.state,
        )
        if correlation_error is not None:
            self._reject_server_request(
                request_id,
                code=-32602,
                message=correlation_error,
            )
            return
        if method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
        }:
            self.state.approval_request_count += 1
            wire_decision = _approval_wire_value(self.state.approval_decision)
            self.state.approval_decisions.append(str(wire_decision))
            self._send({"id": request_id, "result": {"decision": wire_decision}})
            return
        if method == "item/permissions/requestApproval":
            self.state.approval_request_count += 1
            if self.state.approval_decision in {
                CodexAppServerApprovalDecision.ACCEPT,
                CodexAppServerApprovalDecision.ACCEPT_FOR_SESSION,
            }:
                permissions = request_params.get("permissions")
                granted = dict(permissions) if isinstance(permissions, Mapping) else {}
            else:
                granted = {}
            scope = (
                "session"
                if self.state.approval_decision
                is CodexAppServerApprovalDecision.ACCEPT_FOR_SESSION
                else "turn"
            )
            decision_text = "grant_requested" if granted else "grant_none"
            self.state.approval_decisions.append(decision_text)
            self._send(
                {
                    "id": request_id,
                    "result": {"permissions": granted, "scope": scope},
                }
            )
            return
        if method == "mcpServer/elicitation/request":
            action = (
                "cancel"
                if self.state.approval_decision is CodexAppServerApprovalDecision.CANCEL
                else "decline"
            )
            self.state.approval_decisions.append(f"mcp:{action}")
            self._send(
                {"id": request_id, "result": {"action": action, "content": None}}
            )
            return
        if method == "item/tool/requestUserInput":
            answers: dict[str, object] = {}
            questions = request_params.get("questions")
            if isinstance(questions, Sequence) and not isinstance(
                questions, (str, bytes)
            ):
                for question in questions:
                    if isinstance(question, Mapping):
                        question_id = question.get("id")
                        if isinstance(question_id, str) and question_id:
                            answers[question_id] = {"answers": []}
            self.state.approval_decisions.append("user_input:empty")
            self._send({"id": request_id, "result": {"answers": answers}})
            return

    def _reject_server_request(
        self,
        request_id: object,
        *,
        code: int,
        message: str,
    ) -> None:
        self.state.protocol_error_count += 1
        self._send(
            {
                "id": request_id,
                "error": {
                    "code": code,
                    "message": message,
                },
            }
        )

    def _send(self, message: Mapping[str, object]) -> None:
        if self.stdin.closed:
            raise OSError("app-server stdin is closed.")
        self.stdin.write(json.dumps(dict(message), separators=(",", ":")) + "\n")
        self.stdin.flush()

    def close_stdin(self) -> bool:
        if self.stdin.closed:
            return True
        try:
            self.stdin.close()
        except OSError:
            return False
        return True

    def join_readers(self, *, timeout: float) -> None:
        self.stdout_thread.join(timeout=timeout)
        self.stderr_thread.join(timeout=timeout)

    def close_output_pipes(self) -> None:
        for pipe in (self.stdout, self.stderr):
            try:
                pipe.close()
            except OSError:
                pass

    def stderr_tail(self, *, max_chars: int = 2000) -> str | None:
        text = "\n".join(self.stderr_lines).strip()
        if not text:
            return None
        return _truncate_text(text, max_chars)


class _CodexAppServerFailure(RuntimeError):
    def __init__(self, category: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable


def _verify_codex_app_server_resume_policy(
    result: Mapping[str, object],
    *,
    state: _CodexAppServerState,
) -> None:
    """Fail before turn/start unless resume proves it did not widen access."""

    try:
        if result.get("activePermissionProfile") is not None:
            raise ValueError(
                "thread/resume exposed an activePermissionProfile that Beacon "
                "does not yet safely compare"
            )
        effective_cwd = _mapping_text(result, "cwd")
        sandbox = result.get("sandbox")
        if not isinstance(sandbox, Mapping):
            raise ValueError("thread/resume result is missing object sandbox evidence")
        sandbox_type = _mapping_text(sandbox, "type")
        effective_sandbox = {
            "readOnly": "read-only",
            "workspaceWrite": "workspace-write",
            "dangerFullAccess": "danger-full-access",
        }.get(sandbox_type)
        if effective_sandbox is None:
            raise ValueError(
                f"thread/resume returned unsupported sandbox type {sandbox_type!r}"
            )
        network_access_value = sandbox.get("networkAccess", False)
        if not isinstance(network_access_value, bool):
            raise ValueError("thread/resume sandbox networkAccess is not boolean")
        effective_network_access = (
            True
            if effective_sandbox == "danger-full-access"
            else network_access_value
        )
        approval = result.get("approvalPolicy")
        if not isinstance(approval, str) or approval not in {
            "untrusted",
            "on-request",
            "never",
        }:
            raise ValueError(
                "thread/resume returned an unsupported or granular approvalPolicy"
            )
        effective_roots = _effective_workspace_roots(sandbox)
    except (ValueError, _CodexAppServerFailure) as exc:
        raise _CodexAppServerFailure(
            "app_server_resume_policy_unverified",
            f"Beacon could not verify the effective resume policy: {exc}",
            retryable=False,
        ) from exc

    state.effective_cwd = effective_cwd
    state.effective_sandbox = effective_sandbox
    state.effective_network_access = effective_network_access
    state.effective_approval_policy = approval
    state.effective_writable_roots = effective_roots

    requested_cwd = state.requested_cwd
    if requested_cwd is None or not _same_path(effective_cwd, requested_cwd):
        raise _CodexAppServerFailure(
            "app_server_resume_policy_expanded",
            "thread/resume returned an effective cwd different from Beacon's registered cwd.",
            retryable=False,
        )

    requested_sandbox = state.requested_sandbox
    allowed_sandbox = {
        None: {"read-only", "workspace-write"},
        "read-only": {"read-only"},
        "workspace-write": {"read-only", "workspace-write"},
        "danger-full-access": {
            "read-only",
            "workspace-write",
            "danger-full-access",
        },
    }[requested_sandbox]
    if effective_sandbox not in allowed_sandbox:
        raise _CodexAppServerFailure(
            "app_server_resume_policy_expanded",
            "thread/resume widened the effective sandbox beyond Beacon's requested policy.",
            retryable=False,
        )

    if effective_network_access and requested_sandbox != "danger-full-access":
        raise _CodexAppServerFailure(
            "app_server_resume_policy_expanded",
            "thread/resume enabled network access that Beacon did not request.",
            retryable=False,
        )

    requested_approval = state.requested_approval_policy
    approval_is_safe = (
        approval in {"untrusted", "on-request"}
        if requested_approval is None
        else approval == requested_approval
        if requested_approval in {"untrusted", "on-request"}
        else approval in {"untrusted", "on-request", "never"}
    )
    if not approval_is_safe:
        raise _CodexAppServerFailure(
            "app_server_resume_policy_expanded",
            "thread/resume widened the effective approval policy beyond Beacon's requested policy.",
            retryable=False,
        )

    if effective_sandbox == "workspace-write":
        allowed_roots = (requested_cwd, *state.requested_writable_roots)
        normalized_allowed = {
            _normalized_path(path, base_cwd=requested_cwd)
            for path in allowed_roots
        }
        unexpected = [
            path
            for path in effective_roots
            if _normalized_path(path, base_cwd=effective_cwd)
            not in normalized_allowed
        ]
        if unexpected:
            raise _CodexAppServerFailure(
                "app_server_resume_policy_expanded",
                "thread/resume returned writable roots outside Beacon's cwd and allowlist.",
                retryable=False,
            )

    state.resume_policy_verified = True


def _effective_workspace_roots(sandbox: Mapping[str, object]) -> tuple[str, ...]:
    if sandbox.get("type") != "workspaceWrite":
        return ()
    roots = sandbox.get("writableRoots")
    if not isinstance(roots, Sequence) or isinstance(roots, (str, bytes)):
        raise ValueError("workspaceWrite sandbox is missing writableRoots")
    if any(not isinstance(root, str) for root in roots):
        raise ValueError("workspaceWrite sandbox contains a non-string writable root")
    return _unique_non_empty_paths(tuple(roots))


def _server_request_correlation_error(
    method: str,
    params: Mapping[str, object],
    *,
    state: _CodexAppServerState,
) -> str | None:
    if params.get("threadId") != state.requested_thread_id:
        return "Beacon rejected a server request for another thread."
    if not state.thread_verified or state.native_turn_id is None:
        return "Beacon rejected a server request before the target turn was verified."
    turn_id = params.get("turnId")
    if method != "mcpServer/elicitation/request" or turn_id is not None:
        if turn_id != state.native_turn_id:
            return "Beacon rejected a stale or mismatched server request turn."
    if method in {
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
        "item/permissions/requestApproval",
        "item/tool/requestUserInput",
    }:
        item_id = params.get("itemId")
        if not isinstance(item_id, str) or not item_id.strip():
            return "Beacon rejected a server request without a valid itemId."
    return None


def _valid_server_request_id(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, str) and bool(value.strip())


def _normalized_path(value: str, *, base_cwd: str | None = None) -> str:
    path = os.path.normpath(value)
    if base_cwd is not None and not os.path.isabs(path):
        path = os.path.join(base_cwd, path)
    return os.path.normcase(os.path.abspath(path))


def _same_path(left: str, right: str) -> bool:
    return _normalized_path(left) == _normalized_path(right)


def _is_server_request(message: Mapping[str, object]) -> bool:
    return "method" in message and "id" in message


def _is_notification(message: Mapping[str, object]) -> bool:
    return "method" in message and "id" not in message


def _result_object(
    result: Mapping[str, object],
    key: str,
    method: str,
) -> Mapping[str, object]:
    value = result.get(key)
    if not isinstance(value, Mapping):
        raise _CodexAppServerFailure(
            "app_server_invalid_protocol",
            f"{method} result is missing {key}.",
            retryable=False,
        )
    return dict(value)


def _mapping_text(source: Mapping[str, object], key: str) -> str:
    value = _mapping_optional_text(source, key)
    if value is None:
        raise _CodexAppServerFailure(
            "app_server_invalid_protocol",
            f"app-server payload is missing {key}.",
            retryable=False,
        )
    return value


def _mapping_optional_text(source: Mapping[str, object], key: str) -> str | None:
    value = source.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _notification_diagnostic(
    method: str,
    params: Mapping[str, object],
) -> str | None:
    if method in {"warning", "configWarning"}:
        return _mapping_optional_text(params, "message") or _mapping_optional_text(
            params, "summary"
        )
    if method == "deprecationNotice":
        summary = _mapping_optional_text(params, "summary")
        details = _mapping_optional_text(params, "details")
        if summary and details and details != summary:
            return f"{summary} — {details}"
        return summary or details
    if method != "error":
        return None

    nested_error = params.get("error")
    error = nested_error if isinstance(nested_error, Mapping) else {}
    message = (
        _mapping_optional_text(params, "message")
        or _mapping_optional_text(params, "summary")
        or _mapping_optional_text(error, "message")
    )
    details: list[str] = []
    will_retry = params.get("willRetry")
    if isinstance(will_retry, bool):
        details.append(f"willRetry={str(will_retry).lower()}")
    for key in ("codexErrorInfo", "additionalDetails"):
        rendered = _render_diagnostic_value(error.get(key))
        if rendered is not None:
            details.append(f"{key}={rendered}")
    if message and details:
        return f"{message} ({'; '.join(details)})"
    if message:
        return message
    if details:
        return "; ".join(details)
    return None


def _render_diagnostic_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (Mapping, Sequence)) and not isinstance(value, (str, bytes)):
        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            return None
    if isinstance(value, (bool, int, float)):
        return json.dumps(value, separators=(",", ":"))
    return None


def _thread_status_type(value: object) -> str | None:
    if isinstance(value, Mapping):
        status_type = value.get("type")
        if isinstance(status_type, str) and status_type.strip():
            return status_type.strip()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _approval_wire_value(
    decision: CodexAppServerApprovalDecision,
) -> str:
    if decision is CodexAppServerApprovalDecision.ACCEPT_FOR_SESSION:
        return "acceptForSession"
    return decision.value


def _request_error_category(method: str, code: object, message: str) -> str:
    lowered = message.lower()
    if method == "thread/read" and any(
        token in lowered for token in ("not found", "missing", "no rollout")
    ):
        return "app_server_thread_not_found"
    if "not initialized" in lowered:
        return "app_server_not_initialized"
    if code == -32601 or "method not found" in lowered:
        return "app_server_method_not_supported"
    if method == "turn/steer":
        if any(token in lowered for token in ("expected turn", "turn mismatch", "stale")):
            return "app_server_steer_stale_turn"
        if any(token in lowered for token in ("no active turn", "not active", "no turn")):
            return "app_server_steer_no_active_turn"
    if "overloaded" in lowered:
        return "app_server_overloaded"
    return "app_server_request_failed"


def _emit_callback(
    callback: Callable[[Mapping[str, object]], None] | None,
    payload: Mapping[str, object],
    *,
    state: _CodexAppServerState,
) -> None:
    if callback is None:
        return
    try:
        callback(dict(payload))
    except Exception as exc:  # persistence observers must not corrupt protocol flow
        state.warning_messages.append(
            _truncate_text(f"Beacon callback failed: {exc}", 500)
        )


def _emit_required_callback(
    callback: Callable[[Mapping[str, object]], None],
    payload: Mapping[str, object],
    *,
    state: _CodexAppServerState,
) -> bool:
    try:
        callback(dict(payload))
    except Exception as exc:
        state.warning_messages.append(
            _truncate_text(
                f"Required Beacon persistence callback failed; provider write "
                f"was not attempted: {exc}",
                500,
            )
        )
        return False
    return True


def _retryable_text(value: str) -> bool:
    lowered = value.lower()
    return any(
        token in lowered
        for token in (
            "retry",
            "overload",
            "temporar",
            "timeout",
            "timed out",
            "connection",
            "disconnect",
            "server error",
            "system error",
        )
    )


def _classify_process_exception(exc: BaseException) -> str:
    if isinstance(exc, FileNotFoundError):
        return "app_server_executable_not_found"
    if isinstance(exc, PermissionError):
        return "app_server_permission_denied"
    if isinstance(exc, ValueError):
        return "app_server_invalid_protocol"
    return "app_server_process_start_failed"


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                shell=False,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except OSError:
            pass
    if process.poll() is None:
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except OSError:
                    process.kill()


def _sandbox_mode(value: str) -> str:
    text = _non_empty_text(value, "sandboxMode")
    allowed = {"read-only", "workspace-write", "danger-full-access"}
    if text not in allowed:
        raise ValueError("sandboxMode must be one of: danger-full-access, read-only, workspace-write.")
    return text


def _approval_policy(value: str) -> str:
    text = _non_empty_text(value, "approvalPolicy")
    allowed = {"untrusted", "on-request", "never"}
    if text not in allowed:
        raise ValueError("approvalPolicy must be one of: never, on-request, untrusted.")
    return text


def _unique_non_empty_paths(values: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _non_empty_text(value, "addDirs")
        if text not in seen:
            seen.add(text)
            result.append(text)
    return tuple(result)


def _non_empty_text(value: object, logical_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{logical_name} must be a non-empty string.")
    if "\x00" in value:
        raise ValueError(f"{logical_name} must not contain null bytes.")
    return value.strip()


def _truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[-max_chars:]
