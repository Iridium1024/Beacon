from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from importlib import import_module, metadata
from pathlib import Path
import platform
import re
import sys
import time
from types import ModuleType
from typing import Callable, Mapping, Sequence
from uuid import UUID

from agent_os._version import __version__ as BEACON_VERSION


MINIMUM_CLAUDE_AGENT_SDK_VERSION = "0.2.127"
MAXIMUM_CLAUDE_AGENT_SDK_VERSION_EXCLUSIVE = "0.3.0"
CLAUDE_AGENT_SDK_COMPATIBILITY_AUDIT_VERSION = "0.2.144"
_REQUIRED_SYMBOLS = (
    "AssistantMessage",
    "ClaudeAgentOptions",
    "ClaudeSDKClient",
    "PermissionResultDeny",
    "ResultMessage",
    "SystemMessage",
    "TextBlock",
)
_OPTIONAL_CAPABILITY_NAMES = (
    "conversationResetMessage",
    "resultError",
    "resultMessageOrigin",
)
_SAFE_PERMISSION_MODES = {"acceptEdits", "auto", "default", "dontAsk", "plan"}
_CANCELLED_TERMINAL_REASONS = {"aborted_streaming", "aborted_tools"}
_INCOMPLETE_TERMINAL_REASONS = {
    "blocking_limit",
    "max_budget_usd",
    "max_turns",
}


@dataclass(frozen=True, slots=True)
class ClaudeAgentSdkRuntime:
    status: str
    installed: bool
    compatible: bool
    version: str | None = None
    module: ModuleType | object | None = field(default=None, repr=False, compare=False)
    missing_symbols: tuple[str, ...] = ()
    error: str | None = None
    optional_capabilities: Mapping[str, bool] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )

    def to_metadata(self) -> Mapping[str, object]:
        result: dict[str, object] = {
            "schema": "claude_agent_sdk_preflight.v1",
            "readOnly": True,
            "probeAttempted": True,
            "sessionStarted": False,
            "installed": self.installed,
            "compatible": self.compatible,
            "status": self.status,
            "minimumVersion": MINIMUM_CLAUDE_AGENT_SDK_VERSION,
            "maximumVersionExclusive": MAXIMUM_CLAUDE_AGENT_SDK_VERSION_EXCLUSIVE,
            "compatibilityAuditVersion": CLAUDE_AGENT_SDK_COMPATIBILITY_AUDIT_VERSION,
            "requiredSymbols": list(_REQUIRED_SYMBOLS),
            "missingSymbols": list(self.missing_symbols),
            "optionalCapabilities": _complete_optional_capabilities(
                self.optional_capabilities
            ),
            "defaultCliSource": "sdk_bundled_executable",
            "pythonVersion": platform.python_version(),
            "pythonCompatible": sys.version_info >= (3, 11),
        }
        if self.version is not None:
            result["version"] = self.version
        if self.error is not None:
            result["error"] = _bounded_text(self.error, 1000)
        return result


@dataclass(frozen=True, slots=True)
class ClaudeAgentSdkActivationConfig:
    session_id: str
    cwd: str
    add_dirs: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    permission_mode: str | None = None
    settings_path: str | None = None
    cli_path: str | None = None
    max_buffer_size: int = 4 * 1024 * 1024

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", str(UUID(self.session_id)))
        cwd = Path(self.cwd)
        if not cwd.is_absolute() or not cwd.exists() or not cwd.is_dir():
            raise ValueError("Claude Agent SDK cwd must be an existing absolute directory.")
        object.__setattr__(self, "cwd", str(cwd))
        normalized_dirs = _absolute_paths(self.add_dirs, "addDirs")
        object.__setattr__(self, "add_dirs", normalized_dirs)
        object.__setattr__(
            self,
            "allowed_tools",
            _non_empty_texts(self.allowed_tools, "allowedTools"),
        )
        if self.permission_mode is not None:
            mode = _text(self.permission_mode, "permissionMode")
            if mode not in _SAFE_PERMISSION_MODES:
                raise ValueError(
                    "Claude Agent SDK permissionMode must be one of: "
                    + ", ".join(sorted(_SAFE_PERMISSION_MODES))
                    + "."
                )
            object.__setattr__(self, "permission_mode", mode)
        if self.settings_path is not None:
            object.__setattr__(
                self,
                "settings_path",
                _absolute_paths((self.settings_path,), "settingsPath")[0],
            )
        if self.cli_path is not None:
            object.__setattr__(self, "cli_path", _text(self.cli_path, "cliPath"))
        if self.max_buffer_size <= 0:
            raise ValueError("maxBufferSize must be greater than zero.")

    def to_metadata(self) -> Mapping[str, object]:
        return {
            "schema": "claude_agent_sdk_options_summary.v1",
            "resumeSessionId": self.session_id,
            "cwd": self.cwd,
            "addDirs": list(self.add_dirs),
            "allowedTools": list(self.allowed_tools),
            "permissionMode": self.permission_mode,
            "settingsPath": self.settings_path,
            "cliPath": self.cli_path,
            "cliSource": "explicit" if self.cli_path is not None else "sdk_bundled",
            "maxBufferSize": self.max_buffer_size,
            "permissionCallback": "deny_and_interrupt_on_ask",
            "askUserQuestionDisabled": True,
            "fullSessionHistoryRead": False,
        }


@dataclass(frozen=True, slots=True)
class ClaudeAgentSdkRunResult:
    status: str
    sdk_version: str
    provider_command_started: bool
    prompt_submission_attempted: bool
    prompt_submitted: bool
    session_continuity_verified: bool
    event_counts: Mapping[str, int]
    final_response: str | None = None
    final_response_source: str | None = None
    result_subtype: str | None = None
    terminal_reason: str | None = None
    permission_requests: int = 0
    permission_denied: int = 0
    interrupt_attempted: bool = False
    interrupt_status: str = "not_attempted"
    cleanup_status: str = "not_attempted"
    failure_category: str | None = None
    failure_reason: str | None = None
    ambiguous_delivery: bool = False
    requires_user_review: bool = False
    stderr_tail: str | None = None
    diagnostics: tuple[str, ...] = ()
    optional_capabilities: Mapping[str, bool] = field(default_factory=dict)
    conversation_reset_detected: bool = False
    result_origin_kind: str | None = None
    result_origin_trusted: bool | None = None
    result_error_raised: bool = False
    result_error_kind: str | None = None
    result_error_exit_code: int | None = None
    result_error_api_status: int | None = None
    result_error_after_error_result: bool = False

    @property
    def succeeded(self) -> bool:
        return self.status == "completed"

    def to_metadata(self) -> Mapping[str, object]:
        result: dict[str, object] = {
            "schema": "claude_agent_sdk_run.v1",
            "status": self.status,
            "sdkVersion": self.sdk_version,
            "providerCommandStarted": self.provider_command_started,
            "promptSubmissionAttempted": self.prompt_submission_attempted,
            "promptSubmitted": self.prompt_submitted,
            "sessionContinuityVerified": self.session_continuity_verified,
            "eventCounts": dict(self.event_counts),
            "permissionRequests": self.permission_requests,
            "permissionDenied": self.permission_denied,
            "permissionDecision": "deny_on_ask",
            "interruptAttempted": self.interrupt_attempted,
            "interruptStatus": self.interrupt_status,
            "cleanupStatus": self.cleanup_status,
            "ambiguousDelivery": self.ambiguous_delivery,
            "requiresUserReview": self.requires_user_review,
            "diagnostics": list(self.diagnostics),
            "fullSessionHistoryRead": False,
            "compatibilityAuditVersion": CLAUDE_AGENT_SDK_COMPATIBILITY_AUDIT_VERSION,
            "optionalCapabilities": _complete_optional_capabilities(
                self.optional_capabilities
            ),
            "conversationResetDetected": self.conversation_reset_detected,
            "resultErrorRaised": self.result_error_raised,
            "resultErrorAfterErrorResult": self.result_error_after_error_result,
        }
        for key, value in (
            ("finalResponseSource", self.final_response_source),
            ("resultSubtype", self.result_subtype),
            ("terminalReason", self.terminal_reason),
            ("failureCategory", self.failure_category),
            ("failureReason", self.failure_reason),
            ("stderrTail", self.stderr_tail),
            ("resultOriginKind", self.result_origin_kind),
            ("resultErrorKind", self.result_error_kind),
        ):
            if value is not None:
                result[key] = value
        if self.result_origin_trusted is not None:
            result["resultOriginTrusted"] = self.result_origin_trusted
        if self.result_error_exit_code is not None:
            result["resultErrorExitCode"] = self.result_error_exit_code
        if self.result_error_api_status is not None:
            result["resultErrorApiStatus"] = self.result_error_api_status
        return result


def load_claude_agent_sdk_runtime(
    *,
    version_getter: Callable[[str], str] = metadata.version,
    module_loader: Callable[[str], ModuleType] = import_module,
) -> ClaudeAgentSdkRuntime:
    try:
        version = version_getter("claude-agent-sdk")
    except metadata.PackageNotFoundError:
        return ClaudeAgentSdkRuntime(
            status="not_installed",
            installed=False,
            compatible=False,
            error=(
                "Optional package claude-agent-sdk is not installed. Install the "
                "Beacon claude-agent-sdk extra before selecting agent_sdk."
            ),
        )
    except Exception as exc:
        return ClaudeAgentSdkRuntime(
            status="version_probe_failed",
            installed=False,
            compatible=False,
            error=f"{exc.__class__.__name__}: {exc}",
        )

    parsed = _version_tuple(version)
    if parsed is None:
        return ClaudeAgentSdkRuntime(
            status="unsupported_version",
            installed=True,
            compatible=False,
            version=version,
            error="Claude Agent SDK version is not a supported semantic version.",
        )
    if not (
        _version_tuple(MINIMUM_CLAUDE_AGENT_SDK_VERSION) <= parsed
        < _version_tuple(MAXIMUM_CLAUDE_AGENT_SDK_VERSION_EXCLUSIVE)
    ):
        return ClaudeAgentSdkRuntime(
            status="unsupported_version",
            installed=True,
            compatible=False,
            version=version,
            error=(
                "Claude Agent SDK version must be >= "
                f"{MINIMUM_CLAUDE_AGENT_SDK_VERSION} and < "
                f"{MAXIMUM_CLAUDE_AGENT_SDK_VERSION_EXCLUSIVE}."
            ),
        )
    try:
        module = module_loader("claude_agent_sdk")
    except Exception as exc:
        return ClaudeAgentSdkRuntime(
            status="import_failed",
            installed=True,
            compatible=False,
            version=version,
            error=f"{exc.__class__.__name__}: {exc}",
        )
    missing = tuple(symbol for symbol in _REQUIRED_SYMBOLS if not hasattr(module, symbol))
    optional_capabilities = _detect_optional_capabilities(module)
    return ClaudeAgentSdkRuntime(
        status="available" if not missing else "missing_required_surface",
        installed=True,
        compatible=not missing,
        version=version,
        module=module,
        missing_symbols=missing,
        optional_capabilities=optional_capabilities,
        error=(
            None
            if not missing
            else "Claude Agent SDK is missing required public symbols: "
            + ", ".join(missing)
        ),
    )


def probe_claude_agent_sdk_runtime() -> Mapping[str, object]:
    return load_claude_agent_sdk_runtime().to_metadata()


def run_claude_agent_sdk_activation(
    config: ClaudeAgentSdkActivationConfig,
    *,
    runtime: ClaudeAgentSdkRuntime,
    prompt: str,
    timeout_seconds: float,
    max_response_chars: int,
    cleanup_timeout_seconds: float = 5.0,
    client_factory: Callable[[object], object] | None = None,
) -> ClaudeAgentSdkRunResult:
    if not runtime.compatible or runtime.module is None or runtime.version is None:
        raise ValueError("Claude Agent SDK runtime preflight is not compatible.")
    if timeout_seconds <= 0:
        raise ValueError("timeoutSeconds must be greater than zero.")
    if cleanup_timeout_seconds <= 0:
        raise ValueError("cleanupTimeoutSeconds must be greater than zero.")
    if max_response_chars <= 0:
        raise ValueError("maxResponseChars must be greater than zero.")
    _text(prompt, "prompt")
    return asyncio.run(
        _run_claude_agent_sdk_activation(
            config,
            runtime=runtime,
            prompt=prompt,
            timeout_seconds=timeout_seconds,
            max_response_chars=max_response_chars,
            cleanup_timeout_seconds=cleanup_timeout_seconds,
            client_factory=client_factory,
        )
    )


async def _run_claude_agent_sdk_activation(
    config: ClaudeAgentSdkActivationConfig,
    *,
    runtime: ClaudeAgentSdkRuntime,
    prompt: str,
    timeout_seconds: float,
    max_response_chars: int,
    cleanup_timeout_seconds: float,
    client_factory: Callable[[object], object] | None,
) -> ClaudeAgentSdkRunResult:
    module = runtime.module
    assert module is not None
    assert runtime.version is not None
    permission_requests = 0
    permission_denied = 0
    stderr_lines: list[str] = []
    diagnostics: list[str] = []
    event_counts = {
        "assistant": 0,
        "system": 0,
        "result": 0,
        "task": 0,
        "user": 0,
        "unknown": 0,
        "conversation_reset": 0,
    }
    optional_capabilities = _detect_optional_capabilities(module)
    conversation_reset_type = (
        getattr(module, "ConversationResetMessage", None)
        if optional_capabilities["conversationResetMessage"]
        else None
    )
    result_error_type = (
        getattr(module, "ResultError", None)
        if optional_capabilities["resultError"]
        else None
    )
    assistant_candidates: list[str] = []
    result_message: object | None = None
    continuity_mismatch: str | None = None
    provider_command_started = False
    prompt_submission_attempted = False
    prompt_submitted = False
    interrupt_attempted = False
    interrupt_status = "not_attempted"
    cleanup_status = "not_attempted"
    failure_category: str | None = None
    failure_reason: str | None = None
    timed_out = False
    conversation_reset_detected = False
    result_error_raised = False
    result_error_subtype: str | None = None
    result_error_terminal_reason: str | None = None
    result_error_exit_code: int | None = None
    result_error_api_status: int | None = None
    result_error_session_id: str | None = None
    result_error_after_error_result = False
    client: object | None = None
    response_task: asyncio.Task[None] | None = None
    started = time.monotonic()

    async def deny_permission(
        tool_name: str,
        tool_input: dict[str, object],
        context: object,
    ) -> object:
        del tool_name, tool_input, context
        nonlocal permission_requests, permission_denied
        permission_requests += 1
        permission_denied += 1
        return module.PermissionResultDeny(
            message="Beacon denied an unattended Claude Agent SDK permission request.",
            interrupt=True,
        )

    def capture_stderr(line: str) -> None:
        if len(stderr_lines) >= 20:
            return
        text = _bounded_text(str(line).strip(), 500)
        if text:
            stderr_lines.append(text)

    options = module.ClaudeAgentOptions(
        resume=config.session_id,
        cwd=config.cwd,
        add_dirs=list(config.add_dirs),
        allowed_tools=list(config.allowed_tools),
        permission_mode=config.permission_mode,
        settings=config.settings_path,
        cli_path=config.cli_path,
        can_use_tool=deny_permission,
        disallowed_tools=["AskUserQuestion"],
        max_buffer_size=config.max_buffer_size,
        stderr=capture_stderr,
        env={"CLAUDE_AGENT_SDK_CLIENT_APP": f"beacon/{BEACON_VERSION}"},
    )
    factory = client_factory or module.ClaudeSDKClient

    async def attempt_interrupt() -> None:
        nonlocal interrupt_attempted, interrupt_status
        if client is None or interrupt_attempted:
            return
        interrupt_attempted = True
        try:
            await asyncio.wait_for(
                client.interrupt(),
                timeout=cleanup_timeout_seconds,
            )
            interrupt_status = "accepted"
        except Exception as exc:
            interrupt_status = "failed"
            diagnostics.append(
                _bounded_text(
                    f"interrupt_failed:{exc.__class__.__name__}:{exc}",
                    500,
                )
            )

    def event_kind(message: object) -> str:
        if isinstance(message, module.AssistantMessage):
            return "assistant"
        if isinstance(message, module.SystemMessage):
            return "system"
        if isinstance(message, module.ResultMessage):
            return "result"
        if message.__class__.__name__.startswith("Task"):
            return "task"
        if message.__class__.__name__ == "UserMessage":
            return "user"
        return "unknown"

    async def collect_response() -> None:
        nonlocal result_message, continuity_mismatch, conversation_reset_detected
        assert client is not None
        async for message in client.receive_response():
            if _optional_isinstance(message, conversation_reset_type):
                event_counts["conversation_reset"] += 1
                if conversation_reset_detected:
                    diagnostics.append("duplicate_conversation_reset_message")
                else:
                    conversation_reset_detected = True
                    diagnostics.append("conversation_reset_detected")
                    await attempt_interrupt()
                continue
            kind = event_kind(message)
            event_counts[kind] += 1
            if conversation_reset_detected:
                diagnostics.append(
                    f"event_after_conversation_reset_ignored:{message.__class__.__name__}"
                )
                continue
            message_session_id = _message_session_id(message, module)
            if (
                message_session_id is not None
                and message_session_id != config.session_id
            ):
                continuity_mismatch = message_session_id
                raise RuntimeError(
                    "Claude Agent SDK returned a different session id than registered."
                )
            if result_message is not None:
                if isinstance(message, module.ResultMessage):
                    diagnostics.append("duplicate_result_message_ignored")
                else:
                    diagnostics.append(
                        f"event_after_result_ignored:{message.__class__.__name__}"
                    )
                continue
            if isinstance(message, module.AssistantMessage):
                candidate = _assistant_text(message, module, max_response_chars)
                if candidate:
                    assistant_candidates.append(candidate)
            elif isinstance(message, module.SystemMessage):
                pass
            elif isinstance(message, module.ResultMessage):
                result_message = message

    try:
        client = factory(options)
        provider_command_started = True
        await asyncio.wait_for(
            client.connect(),
            timeout=_remaining_timeout(started, timeout_seconds),
        )
        prompt_submission_attempted = True
        await asyncio.wait_for(
            client.query(prompt),
            timeout=_remaining_timeout(started, timeout_seconds),
        )
        prompt_submitted = True
        response_task = asyncio.create_task(collect_response())
        done, _ = await asyncio.wait(
            (response_task,),
            timeout=_remaining_timeout(started, timeout_seconds),
        )
        if response_task not in done:
            timed_out = True
            failure_category = "sdk_response_timeout"
            failure_reason = (
                f"Claude Agent SDK response exceeded {timeout_seconds} seconds."
            )
            await attempt_interrupt()
            try:
                await asyncio.wait_for(response_task, timeout=cleanup_timeout_seconds)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                response_task.cancel()
                try:
                    await response_task
                except (asyncio.CancelledError, Exception):
                    pass
            except Exception as exc:
                diagnostics.append(
                    _bounded_text(f"post_interrupt_receive:{exc.__class__.__name__}:{exc}", 500)
                )
        else:
            await response_task
    except asyncio.TimeoutError:
        timed_out = True
        failure_category = "sdk_operation_timeout"
        failure_reason = f"Claude Agent SDK operation exceeded {timeout_seconds} seconds."
        if client is not None:
            await attempt_interrupt()
    except Exception as exc:
        if _optional_isinstance(exc, result_error_type):
            result_error_raised = True
            result_error_subtype = _optional_attr_audit_token(exc, "subtype")
            result_error_terminal_reason = _optional_attr_audit_token(
                exc,
                "terminal_reason",
            )
            result_error_exit_code = _optional_attr_int(exc, "exit_code")
            result_error_api_status = _optional_attr_int(exc, "api_error_status")
            result_error_session_id = _optional_attr_text(exc, "session_id")
            result_error_after_error_result = bool(
                result_message is not None
                and bool(getattr(result_message, "is_error", False))
            )
            result_error_kind = (
                result_error_terminal_reason
                or result_error_subtype
                or "result_error"
            )
            failure_category = "sdk_result_error"
            failure_reason = _result_error_failure_reason(
                result_error_kind,
                result_error_exit_code,
                result_error_api_status,
            )
        else:
            failure_category = (
                "sdk_session_mismatch"
                if continuity_mismatch is not None
                else "sdk_operation_failed"
            )
            failure_reason = _bounded_text(f"{exc.__class__.__name__}: {exc}", 1000)
            if prompt_submitted and client is not None:
                await attempt_interrupt()
    finally:
        if response_task is not None and not response_task.done():
            response_task.cancel()
            try:
                await response_task
            except (asyncio.CancelledError, Exception):
                pass
        if client is not None:
            try:
                await asyncio.wait_for(
                    client.disconnect(),
                    timeout=cleanup_timeout_seconds,
                )
                cleanup_status = "completed"
            except Exception as exc:
                cleanup_status = "failed"
                diagnostics.append(
                    _bounded_text(f"disconnect_failed:{exc.__class__.__name__}:{exc}", 500)
                )

    result_subtype = _optional_attr_text(result_message, "subtype")
    terminal_reason = (
        _optional_attr_text(result_message, "terminal_reason")
        or result_error_terminal_reason
    )
    result_session_id = _optional_attr_text(result_message, "session_id")
    continuity_verified = (
        result_session_id == config.session_id
        and continuity_mismatch is None
        and not conversation_reset_detected
    )
    if result_message is None and result_error_session_id is not None:
        continuity_verified = (
            result_error_session_id == config.session_id
            and continuity_mismatch is None
            and not conversation_reset_detected
        )
    result_origin_kind, result_origin_trusted = _result_origin_trust(
        result_message,
        supported=optional_capabilities["resultMessageOrigin"],
    )
    result_is_error = bool(getattr(result_message, "is_error", True))
    terminal_cancelled = terminal_reason in _CANCELLED_TERMINAL_REASONS
    terminal_incomplete = terminal_reason in _INCOMPLETE_TERMINAL_REASONS
    successful_result = (
        result_message is not None
        and result_subtype == "success"
        and not result_is_error
        and not terminal_cancelled
        and not terminal_incomplete
        and continuity_verified
        and permission_denied == 0
        and not timed_out
        and failure_category is None
        and result_origin_trusted is not False
        and not result_error_raised
        and not conversation_reset_detected
    )
    final_response: str | None = None
    final_response_source: str | None = None
    if successful_result:
        direct_result = _optional_attr_text(result_message, "result")
        if direct_result:
            final_response = _bounded_text(direct_result, max_response_chars)
            final_response_source = "result_message"
        elif assistant_candidates:
            final_response = assistant_candidates[-1]
            final_response_source = "assistant_message_before_success_result"
    if conversation_reset_detected:
        failure_category = "sdk_conversation_reset"
        failure_reason = (
            "Claude Agent SDK reset the conversation; exact registered-session "
            "continuity can no longer be verified."
        )
    elif permission_denied and failure_category is None:
        failure_category = "sdk_permission_denied"
        failure_reason = (
            "Claude Agent SDK requested an unattended permission and Beacon denied it."
        )
    elif terminal_cancelled and failure_category is None:
        failure_category = "sdk_interrupted"
        failure_reason = f"Claude Agent SDK terminated with {terminal_reason}."
    elif terminal_incomplete and failure_category is None:
        failure_category = "sdk_incomplete_result"
        failure_reason = f"Claude Agent SDK terminated with {terminal_reason}."
    elif result_message is None and failure_category is None:
        failure_category = "sdk_result_missing"
        failure_reason = "Claude Agent SDK stream ended without a ResultMessage."
    elif result_is_error and failure_category is None:
        failure_category = "sdk_result_error"
        failure_reason = "Claude Agent SDK returned an error ResultMessage."
    elif not continuity_verified and failure_category is None:
        failure_category = "sdk_session_mismatch"
        failure_reason = "Claude Agent SDK result did not verify the registered session id."
    elif result_origin_trusted is False and failure_category is None:
        failure_category = "sdk_untrusted_result_origin"
        failure_reason = (
            "Claude Agent SDK returned a result for a non-human or unknown origin."
        )

    status = "completed" if successful_result else "failed"
    ambiguous_delivery = bool(
        prompt_submission_attempted
        and not successful_result
        and (prompt_submitted or failure_category == "sdk_operation_failed")
        and not result_error_raised
        and not conversation_reset_detected
        and failure_category != "sdk_untrusted_result_origin"
    )
    requires_user_review = bool(
        ambiguous_delivery
        or permission_denied
        or cleanup_status == "failed"
        or interrupt_status == "failed"
    )
    return ClaudeAgentSdkRunResult(
        status=status,
        sdk_version=runtime.version,
        provider_command_started=provider_command_started,
        prompt_submission_attempted=prompt_submission_attempted,
        prompt_submitted=prompt_submitted,
        session_continuity_verified=continuity_verified,
        event_counts=event_counts,
        final_response=final_response,
        final_response_source=final_response_source,
        result_subtype=result_subtype,
        terminal_reason=terminal_reason,
        permission_requests=permission_requests,
        permission_denied=permission_denied,
        interrupt_attempted=interrupt_attempted,
        interrupt_status=interrupt_status,
        cleanup_status=cleanup_status,
        failure_category=failure_category,
        failure_reason=failure_reason,
        ambiguous_delivery=ambiguous_delivery,
        requires_user_review=requires_user_review,
        stderr_tail=_bounded_text("\n".join(stderr_lines), 2000) or None,
        diagnostics=tuple(diagnostics[:20]),
        optional_capabilities=optional_capabilities,
        conversation_reset_detected=conversation_reset_detected,
        result_origin_kind=result_origin_kind,
        result_origin_trusted=result_origin_trusted,
        result_error_raised=result_error_raised,
        result_error_kind=(
            result_error_terminal_reason
            or result_error_subtype
            or ("result_error" if result_error_raised else None)
        ),
        result_error_exit_code=result_error_exit_code,
        result_error_api_status=result_error_api_status,
        result_error_after_error_result=result_error_after_error_result,
    )


def _assistant_text(message: object, module: object, max_chars: int) -> str | None:
    parts: list[str] = []
    for block in getattr(message, "content", ()):
        if isinstance(block, module.TextBlock):
            text = _optional_attr_text(block, "text")
            if text:
                parts.append(text)
    joined = "\n".join(parts).strip()
    return _bounded_text(joined, max_chars) or None


def _message_session_id(message: object, module: object) -> str | None:
    direct = _optional_attr_text(message, "session_id")
    if direct is not None:
        return direct
    if isinstance(message, module.SystemMessage):
        data = getattr(message, "data", None)
        if isinstance(data, Mapping):
            value = data.get("session_id", data.get("sessionId"))
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _remaining_timeout(started: float, timeout_seconds: float) -> float:
    remaining = timeout_seconds - (time.monotonic() - started)
    if remaining <= 0:
        raise asyncio.TimeoutError
    return remaining


def _optional_attr_text(value: object | None, name: str) -> str | None:
    if value is None:
        return None
    candidate = getattr(value, name, None)
    if not isinstance(candidate, str) or not candidate.strip():
        return None
    return candidate.strip()


def _optional_attr_int(value: object | None, name: str) -> int | None:
    if value is None:
        return None
    candidate = getattr(value, name, None)
    if isinstance(candidate, bool) or not isinstance(candidate, int):
        return None
    return candidate


def _optional_attr_audit_token(value: object | None, name: str) -> str | None:
    return _audit_token(_optional_attr_text(value, name))


def _audit_token(value: str | None, *, max_chars: int = 80) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[^a-z0-9._-]+", "_", value.strip().lower()).strip("_")
    if not normalized:
        return "unknown"
    return normalized[:max_chars]


def _result_origin_trust(
    result_message: object | None,
    *,
    supported: bool,
) -> tuple[str | None, bool | None]:
    if not supported:
        return None, None
    if result_message is None or not hasattr(result_message, "origin"):
        return None, True
    origin = getattr(result_message, "origin", None)
    if origin is None:
        return None, True
    if isinstance(origin, Mapping):
        raw_kind = origin.get("kind")
        if isinstance(raw_kind, str) and raw_kind.strip():
            kind = _audit_token(raw_kind)
            return kind, kind == "human"
    return "invalid", False


def _result_error_failure_reason(
    kind: str,
    exit_code: int | None,
    api_status: int | None,
) -> str:
    context = [f"kind={kind}"]
    if exit_code is not None:
        context.append(f"exitCode={exit_code}")
    if api_status is not None:
        context.append(f"apiStatus={api_status}")
    return _bounded_text(
        "Claude Agent SDK raised a structured ResultError ("
        + ", ".join(context)
        + ").",
        500,
    )


def _optional_isinstance(value: object, expected_type: object | None) -> bool:
    return isinstance(expected_type, type) and isinstance(value, expected_type)


def _detect_optional_capabilities(module: object) -> Mapping[str, bool]:
    result_message_type = getattr(module, "ResultMessage", None)
    return {
        "conversationResetMessage": isinstance(
            getattr(module, "ConversationResetMessage", None),
            type,
        ),
        "resultError": isinstance(getattr(module, "ResultError", None), type),
        "resultMessageOrigin": _type_declares_field(result_message_type, "origin"),
    }


def _type_declares_field(value: object, field_name: str) -> bool:
    if not isinstance(value, type):
        return False
    for candidate in value.__mro__:
        annotations = getattr(candidate, "__annotations__", {})
        if isinstance(annotations, Mapping) and field_name in annotations:
            return True
        dataclass_fields = getattr(candidate, "__dataclass_fields__", {})
        if isinstance(dataclass_fields, Mapping) and field_name in dataclass_fields:
            return True
    return False


def _complete_optional_capabilities(values: Mapping[str, bool]) -> Mapping[str, bool]:
    return {name: bool(values.get(name, False)) for name in _OPTIONAL_CAPABILITY_NAMES}


def _absolute_paths(values: Sequence[str], logical_name: str) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        path = Path(_text(value, logical_name))
        if not path.is_absolute():
            raise ValueError(f"{logical_name} must contain absolute paths.")
        text = str(path)
        if text not in result:
            result.append(text)
    return tuple(result)


def _non_empty_texts(values: Sequence[str], logical_name: str) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        text = _text(value, logical_name)
        if "\r" in text or "\n" in text:
            raise ValueError(f"{logical_name} must not contain newlines.")
        if text not in result:
            result.append(text)
    return tuple(result)


def _text(value: str, logical_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{logical_name} must be a non-empty string.")
    if "\x00" in value:
        raise ValueError(f"{logical_name} must not contain null bytes.")
    return value.strip()


def _bounded_text(value: str, max_chars: int) -> str:
    text = value.strip()
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", value.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())
