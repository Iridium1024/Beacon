from __future__ import annotations

import asyncio
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from uuid import uuid4

from agent_os.application.services.claude_agent_sdk_backend import (
    ClaudeAgentSdkActivationConfig,
    ClaudeAgentSdkRuntime,
    load_claude_agent_sdk_runtime,
    run_claude_agent_sdk_activation,
)


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _AssistantMessage:
    def __init__(self, content: list[object], session_id: str | None = None) -> None:
        self.content = content
        self.session_id = session_id


class _SystemMessage:
    def __init__(self, data: dict[str, object]) -> None:
        self.data = data


class _ResultMessage:
    def __init__(
        self,
        *,
        session_id: str,
        result: str | None = None,
        subtype: str = "success",
        is_error: bool = False,
        terminal_reason: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.result = result
        self.subtype = subtype
        self.is_error = is_error
        self.terminal_reason = terminal_reason


class _OriginResultMessage(_ResultMessage):
    origin: object | None

    def __init__(self, *, origin: object | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.origin = origin


class _ConversationResetMessage:
    def __init__(self, *, session_id: str, new_conversation_id: str = "fresh") -> None:
        self.session_id = session_id
        self.new_conversation_id = new_conversation_id


class _ResultError(Exception):
    def __init__(
        self,
        message: str,
        *,
        subtype: str | None = None,
        terminal_reason: str | None = None,
        session_id: str | None = None,
        exit_code: int | None = None,
        api_error_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.subtype = subtype
        self.terminal_reason = terminal_reason
        self.session_id = session_id
        self.exit_code = exit_code
        self.api_error_status = api_error_status


class _PermissionResultDeny:
    def __init__(self, *, message: str, interrupt: bool) -> None:
        self.message = message
        self.interrupt = interrupt


class TaskStartedMessage:
    pass


class UserMessage:
    pass


class UnknownMessage:
    pass


class _Options:
    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


class _FakeClient:
    def __init__(
        self,
        options: object,
        *,
        events: tuple[object, ...] = (),
        connect_error: Exception | None = None,
        query_error: Exception | None = None,
        receive_error: Exception | None = None,
        receive_error_after_events: Exception | None = None,
        hang: bool = False,
        permission_request: bool = False,
        interrupt_error: Exception | None = None,
        disconnect_error: Exception | None = None,
    ) -> None:
        self.options = options
        self.events = events
        self.connect_error = connect_error
        self.query_error = query_error
        self.receive_error = receive_error
        self.receive_error_after_events = receive_error_after_events
        self.hang = hang
        self.permission_request = permission_request
        self.interrupt_error = interrupt_error
        self.disconnect_error = disconnect_error
        self.connected = False
        self.queries: list[str] = []
        self.interrupted = False
        self.disconnected = False

    async def connect(self) -> None:
        self.connected = True
        if self.connect_error is not None:
            raise self.connect_error

    async def query(self, prompt: str) -> None:
        self.queries.append(prompt)
        if self.query_error is not None:
            raise self.query_error
        if self.permission_request:
            await self.options.can_use_tool("Bash", {"command": "unsafe"}, object())

    async def receive_response(self):
        if self.receive_error is not None:
            raise self.receive_error
        if self.hang:
            await asyncio.Event().wait()
        for event in self.events:
            yield event
        if self.receive_error_after_events is not None:
            raise self.receive_error_after_events

    async def interrupt(self) -> None:
        self.interrupted = True
        if self.interrupt_error is not None:
            raise self.interrupt_error

    async def disconnect(self) -> None:
        self.disconnected = True
        if self.disconnect_error is not None:
            raise self.disconnect_error


def _fake_module(*, new_surface: bool = False) -> object:
    module = SimpleNamespace(
        AssistantMessage=_AssistantMessage,
        ClaudeAgentOptions=_Options,
        ClaudeSDKClient=_FakeClient,
        PermissionResultDeny=_PermissionResultDeny,
        ResultMessage=_ResultMessage,
        SystemMessage=_SystemMessage,
        TextBlock=_TextBlock,
    )
    if new_surface:
        module.ResultMessage = _OriginResultMessage
        module.ConversationResetMessage = _ConversationResetMessage
        module.ResultError = _ResultError
    return module


class ClaudeAgentSdkBackendTests(unittest.TestCase):
    def test_runtime_loader_reports_compatible_missing_and_unsupported(self) -> None:
        module = _fake_module()
        compatible = load_claude_agent_sdk_runtime(
            version_getter=lambda _: "0.2.129",
            module_loader=lambda _: module,
        )
        missing = load_claude_agent_sdk_runtime(
            version_getter=lambda _: "0.2.129",
            module_loader=lambda _: SimpleNamespace(),
        )
        unsupported = load_claude_agent_sdk_runtime(
            version_getter=lambda _: "0.3.0",
            module_loader=lambda _: module,
        )

        self.assertTrue(compatible.compatible)
        self.assertEqual(compatible.status, "available")
        self.assertEqual(missing.status, "missing_required_surface")
        self.assertTrue(missing.missing_symbols)
        self.assertEqual(unsupported.status, "unsupported_version")
        self.assertFalse(unsupported.compatible)
        self.assertEqual(
            compatible.to_metadata()["optionalCapabilities"],
            {
                "conversationResetMessage": False,
                "resultError": False,
                "resultMessageOrigin": False,
            },
        )

        refreshed = load_claude_agent_sdk_runtime(
            version_getter=lambda _: "0.2.144",
            module_loader=lambda _: _fake_module(new_surface=True),
        )
        self.assertTrue(refreshed.compatible)
        self.assertEqual(
            refreshed.to_metadata()["optionalCapabilities"],
            {
                "conversationResetMessage": True,
                "resultError": True,
                "resultMessageOrigin": True,
            },
        )
        self.assertEqual(
            refreshed.to_metadata()["compatibilityAuditVersion"],
            "0.2.144",
        )

    def test_runtime_loader_reports_optional_package_absent(self) -> None:
        def missing(_: str) -> str:
            raise metadata.PackageNotFoundError("claude-agent-sdk")

        runtime = load_claude_agent_sdk_runtime(version_getter=missing)

        self.assertEqual(runtime.status, "not_installed")
        self.assertFalse(runtime.installed)
        self.assertFalse(runtime.compatible)
        self.assertFalse(runtime.to_metadata()["sessionStarted"])
        self.assertTrue(runtime.to_metadata()["pythonCompatible"])

    def test_config_requires_registered_uuid_and_absolute_existing_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session_id = str(uuid4())
            config = ClaudeAgentSdkActivationConfig(
                session_id=session_id,
                cwd=directory,
                add_dirs=(directory, directory),
                allowed_tools=("Read", "Read"),
                permission_mode="default",
            )
            self.assertEqual(config.session_id, session_id)
            self.assertEqual(config.add_dirs, (str(Path(directory)),))
            self.assertEqual(config.allowed_tools, ("Read",))
            self.assertEqual(config.to_metadata()["cliSource"], "sdk_bundled")
            with self.assertRaises(ValueError):
                ClaudeAgentSdkActivationConfig(session_id="not-a-uuid", cwd=directory)
            with self.assertRaisesRegex(ValueError, "permissionMode"):
                ClaudeAgentSdkActivationConfig(
                    session_id=session_id,
                    cwd=directory,
                    permission_mode="bypassPermissions",
                )

    def test_success_uses_result_and_preserves_exact_options(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session_id = str(uuid4())
            module = _fake_module()
            runtime = _runtime(module)
            holder: list[_FakeClient] = []

            def factory(options: object) -> _FakeClient:
                client = _FakeClient(
                    options,
                    events=(
                        _SystemMessage({"session_id": session_id}),
                        TaskStartedMessage(),
                        UserMessage(),
                        UnknownMessage(),
                        _AssistantMessage([_TextBlock("assistant fallback")], session_id),
                        _ResultMessage(session_id=session_id, result="final result"),
                        _ResultMessage(session_id=session_id, result="duplicate"),
                        _AssistantMessage([_TextBlock("late")], session_id),
                    ),
                )
                holder.append(client)
                return client

            config = ClaudeAgentSdkActivationConfig(
                session_id=session_id,
                cwd=directory,
                add_dirs=(directory,),
                allowed_tools=("Read",),
                permission_mode="default",
                settings_path=str(Path(directory) / "settings.json"),
            )
            result = run_claude_agent_sdk_activation(
                config,
                runtime=runtime,
                prompt="do work",
                timeout_seconds=1,
                max_response_chars=1000,
                client_factory=factory,
            )

            self.assertTrue(result.succeeded)
            self.assertEqual(result.final_response, "final result")
            self.assertEqual(result.final_response_source, "result_message")
            self.assertTrue(result.session_continuity_verified)
            self.assertEqual(result.event_counts["result"], 2)
            self.assertEqual(result.event_counts["task"], 1)
            self.assertEqual(result.event_counts["user"], 1)
            self.assertEqual(result.event_counts["unknown"], 1)
            self.assertIn("duplicate_result_message_ignored", result.diagnostics)
            self.assertIn("event_after_result_ignored:_AssistantMessage", result.diagnostics)
            self.assertEqual(holder[0].options.resume, session_id)
            self.assertEqual(holder[0].options.cwd, directory)
            self.assertEqual(holder[0].options.add_dirs, [directory])
            self.assertEqual(holder[0].options.allowed_tools, ["Read"])
            self.assertIsNone(holder[0].options.cli_path)
            self.assertEqual(holder[0].queries, ["do work"])
            self.assertTrue(holder[0].disconnected)

    def test_success_without_final_is_completed_without_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session_id = str(uuid4())
            result = _run(
                directory,
                session_id,
                events=(_ResultMessage(session_id=session_id),),
            )

            self.assertTrue(result.succeeded)
            self.assertIsNone(result.final_response)
            self.assertIsNone(result.final_response_source)

    def test_origin_none_and_human_are_trusted_on_new_surface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session_id = str(uuid4())
            module = _fake_module(new_surface=True)
            for origin in (None, {"kind": "human"}):
                with self.subTest(origin=origin):
                    result = _run(
                        directory,
                        session_id,
                        module=module,
                        events=(
                            _OriginResultMessage(
                                session_id=session_id,
                                result="trusted",
                                origin=origin,
                            ),
                        ),
                    )
                    self.assertTrue(result.succeeded)
                    self.assertEqual(result.final_response, "trusted")
                    self.assertTrue(result.result_origin_trusted)
                    self.assertEqual(
                        result.result_origin_kind,
                        None if origin is None else "human",
                    )

    def test_non_human_and_unknown_origins_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session_id = str(uuid4())
            module = _fake_module(new_surface=True)
            for origin_kind in (
                "task-notification",
                "observer-activity",
                "future injected/source",
            ):
                with self.subTest(origin_kind=origin_kind):
                    result = _run(
                        directory,
                        session_id,
                        module=module,
                        events=(
                            _OriginResultMessage(
                                session_id=session_id,
                                result="must not capture",
                                origin={"kind": origin_kind},
                            ),
                        ),
                    )
                    self.assertFalse(result.succeeded)
                    self.assertEqual(
                        result.failure_category,
                        "sdk_untrusted_result_origin",
                    )
                    self.assertFalse(result.result_origin_trusted)
                    self.assertIsNone(result.final_response)
                    self.assertFalse(result.ambiguous_delivery)

    def test_conversation_reset_rejects_later_success_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session_id = str(uuid4())
            module = _fake_module(new_surface=True)
            holder: list[_FakeClient] = []
            result = _run(
                directory,
                session_id,
                module=module,
                events=(
                    _ConversationResetMessage(session_id=session_id),
                    _OriginResultMessage(
                        session_id=str(uuid4()),
                        result="must not capture",
                        origin={"kind": "human"},
                    ),
                ),
                holder=holder,
            )

            self.assertEqual(result.failure_category, "sdk_conversation_reset")
            self.assertTrue(result.conversation_reset_detected)
            self.assertEqual(result.event_counts["conversation_reset"], 1)
            self.assertEqual(result.event_counts["result"], 1)
            self.assertFalse(result.session_continuity_verified)
            self.assertIsNone(result.final_response)
            self.assertTrue(holder[0].interrupted)
            self.assertFalse(result.ambiguous_delivery)

    def test_reset_after_result_duplicate_and_cleanup_error_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session_id = str(uuid4())
            module = _fake_module(new_surface=True)
            result = _run(
                directory,
                session_id,
                module=module,
                events=(
                    _OriginResultMessage(
                        session_id=session_id,
                        result="invalidated",
                        origin={"kind": "human"},
                    ),
                    _ConversationResetMessage(session_id=session_id),
                    _ConversationResetMessage(session_id=session_id),
                    _AssistantMessage([_TextBlock("late")], str(uuid4())),
                    _OriginResultMessage(
                        session_id=str(uuid4()),
                        result="late",
                        origin={"kind": "human"},
                    ),
                ),
                disconnect_error=RuntimeError("disconnect unavailable"),
            )

            self.assertEqual(result.failure_category, "sdk_conversation_reset")
            self.assertEqual(result.event_counts["conversation_reset"], 2)
            self.assertEqual(result.event_counts["result"], 2)
            self.assertIn("duplicate_conversation_reset_message", result.diagnostics)
            self.assertEqual(result.cleanup_status, "failed")
            self.assertTrue(result.requires_user_review)
            self.assertIsNone(result.final_response)

    def test_error_result_then_result_error_is_correlated_and_not_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session_id = str(uuid4())
            module = _fake_module(new_surface=True)
            error = _ResultError(
                "do not expose this result body",
                subtype="error_during_execution",
                terminal_reason="api_error",
                session_id=session_id,
                exit_code=1,
                api_error_status=529,
            )
            result = _run(
                directory,
                session_id,
                module=module,
                events=(
                    _OriginResultMessage(
                        session_id=session_id,
                        subtype="error_during_execution",
                        is_error=True,
                        terminal_reason="api_error",
                        origin={"kind": "human"},
                    ),
                ),
                receive_error_after_events=error,
            )

            self.assertEqual(result.failure_category, "sdk_result_error")
            self.assertTrue(result.result_error_raised)
            self.assertTrue(result.result_error_after_error_result)
            self.assertEqual(result.result_error_kind, "api_error")
            self.assertEqual(result.result_error_exit_code, 1)
            self.assertEqual(result.result_error_api_status, 529)
            self.assertEqual(result.terminal_reason, "api_error")
            self.assertFalse(result.ambiguous_delivery)
            self.assertNotIn("do not expose", result.failure_reason or "")
            self.assertIsNone(result.final_response)

    def test_result_error_without_prior_result_is_structured_and_failed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session_id = str(uuid4())
            module = _fake_module(new_surface=True)
            result = _run(
                directory,
                session_id,
                module=module,
                events=(),
                receive_error=_ResultError(
                    "sensitive provider prose",
                    subtype="error_max_turns",
                    terminal_reason="max_turns",
                    session_id=session_id,
                    exit_code=1,
                ),
            )

            self.assertEqual(result.failure_category, "sdk_result_error")
            self.assertTrue(result.result_error_raised)
            self.assertFalse(result.result_error_after_error_result)
            self.assertEqual(result.result_error_kind, "max_turns")
            self.assertFalse(result.ambiguous_delivery)
            self.assertIsNone(result.final_response)

    def test_error_cancelled_and_session_mismatch_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session_id = str(uuid4())
            error = _run(
                directory,
                session_id,
                events=(
                    _ResultMessage(
                        session_id=session_id,
                        subtype="error",
                        is_error=True,
                    ),
                ),
            )
            cancelled = _run(
                directory,
                session_id,
                events=(
                    _ResultMessage(
                        session_id=session_id,
                        terminal_reason="aborted_tools",
                    ),
                ),
            )
            mismatch = _run(
                directory,
                session_id,
                events=(_ResultMessage(session_id=str(uuid4()), result="wrong"),),
            )

            self.assertEqual(error.failure_category, "sdk_result_error")
            self.assertEqual(cancelled.failure_category, "sdk_interrupted")
            self.assertEqual(mismatch.failure_category, "sdk_session_mismatch")
            self.assertTrue(mismatch.interrupt_attempted)
            self.assertTrue(mismatch.ambiguous_delivery)
            self.assertIsNone(mismatch.final_response)

    def test_timeout_interrupts_and_disconnects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session_id = str(uuid4())
            holder: list[_FakeClient] = []
            result = _run(
                directory,
                session_id,
                events=(),
                hang=True,
                holder=holder,
                timeout_seconds=0.02,
            )

            self.assertEqual(result.failure_category, "sdk_response_timeout")
            self.assertTrue(result.interrupt_attempted)
            self.assertEqual(result.interrupt_status, "accepted")
            self.assertTrue(holder[0].interrupted)
            self.assertTrue(holder[0].disconnected)

    def test_permission_request_is_denied_even_if_result_claims_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session_id = str(uuid4())
            result = _run(
                directory,
                session_id,
                events=(_ResultMessage(session_id=session_id, result="must not capture"),),
                permission_request=True,
            )

            self.assertFalse(result.succeeded)
            self.assertEqual(result.permission_requests, 1)
            self.assertEqual(result.permission_denied, 1)
            self.assertEqual(result.failure_category, "sdk_permission_denied")
            self.assertTrue(result.requires_user_review)
            self.assertIsNone(result.final_response)

    def test_interrupt_and_cleanup_failures_require_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session_id = str(uuid4())
            result = _run(
                directory,
                session_id,
                events=(_ResultMessage(session_id=str(uuid4())),),
                interrupt_error=RuntimeError("interrupt unavailable"),
                disconnect_error=RuntimeError("disconnect unavailable"),
            )

            self.assertEqual(result.interrupt_status, "failed")
            self.assertEqual(result.cleanup_status, "failed")
            self.assertTrue(result.requires_user_review)

    def test_connect_query_and_receive_exceptions_are_bounded_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session_id = str(uuid4())
            connect, connect_client = _run_failure_stage(
                directory,
                session_id,
                connect_error=RuntimeError("connect failed"),
            )
            query, query_client = _run_failure_stage(
                directory,
                session_id,
                query_error=RuntimeError("query failed"),
            )
            receive, receive_client = _run_failure_stage(
                directory,
                session_id,
                receive_error=RuntimeError("receive failed"),
            )

            self.assertEqual(connect.failure_category, "sdk_operation_failed")
            self.assertFalse(connect.prompt_submission_attempted)
            self.assertFalse(connect.interrupt_attempted)
            self.assertTrue(connect_client.disconnected)

            self.assertEqual(query.failure_category, "sdk_operation_failed")
            self.assertTrue(query.prompt_submission_attempted)
            self.assertFalse(query.prompt_submitted)
            self.assertFalse(query.interrupt_attempted)
            self.assertTrue(query.ambiguous_delivery)
            self.assertTrue(query_client.disconnected)

            self.assertEqual(receive.failure_category, "sdk_operation_failed")
            self.assertTrue(receive.prompt_submitted)
            self.assertTrue(receive.interrupt_attempted)
            self.assertEqual(receive.interrupt_status, "accepted")
            self.assertTrue(receive_client.disconnected)


def _runtime(module: object) -> ClaudeAgentSdkRuntime:
    return ClaudeAgentSdkRuntime(
        status="available",
        installed=True,
        compatible=True,
        version="0.2.129",
        module=module,
    )


def _run(
    directory: str,
    session_id: str,
    *,
    events: tuple[object, ...],
    module: object | None = None,
    hang: bool = False,
    permission_request: bool = False,
    interrupt_error: Exception | None = None,
    disconnect_error: Exception | None = None,
    receive_error: Exception | None = None,
    receive_error_after_events: Exception | None = None,
    holder: list[_FakeClient] | None = None,
    timeout_seconds: float = 1,
):
    resolved_module = module or _fake_module()
    clients = holder if holder is not None else []

    def factory(options: object) -> _FakeClient:
        client = _FakeClient(
            options,
            events=events,
            hang=hang,
            permission_request=permission_request,
            interrupt_error=interrupt_error,
            disconnect_error=disconnect_error,
            receive_error=receive_error,
            receive_error_after_events=receive_error_after_events,
        )
        clients.append(client)
        return client

    return run_claude_agent_sdk_activation(
        ClaudeAgentSdkActivationConfig(session_id=session_id, cwd=directory),
        runtime=_runtime(resolved_module),
        prompt="prompt",
        timeout_seconds=timeout_seconds,
        max_response_chars=1000,
        cleanup_timeout_seconds=0.02,
        client_factory=factory,
    )


def _run_failure_stage(
    directory: str,
    session_id: str,
    *,
    connect_error: Exception | None = None,
    query_error: Exception | None = None,
    receive_error: Exception | None = None,
) -> tuple[object, _FakeClient]:
    module = _fake_module()
    clients: list[_FakeClient] = []

    def factory(options: object) -> _FakeClient:
        client = _FakeClient(
            options,
            connect_error=connect_error,
            query_error=query_error,
            receive_error=receive_error,
        )
        clients.append(client)
        return client

    result = run_claude_agent_sdk_activation(
        ClaudeAgentSdkActivationConfig(session_id=session_id, cwd=directory),
        runtime=_runtime(module),
        prompt="prompt",
        timeout_seconds=1,
        max_response_chars=1000,
        cleanup_timeout_seconds=0.02,
        client_factory=factory,
    )
    return result, clients[0]


if __name__ == "__main__":
    unittest.main()
