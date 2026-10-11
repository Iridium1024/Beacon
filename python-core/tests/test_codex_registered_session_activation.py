from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from uuid import uuid4


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.codex_registered_session import (
    CodexRegisteredSessionActivationAttempt,
    CodexRegisteredSessionActivationStatus,
    CodexRegisteredSessionHandle,
    build_codex_activation_stdin,
    extract_codex_json_response,
    render_codex_exec_resume_argv,
    resolve_codex_executable,
)
from agent_os.application.services.codex_session_control import (
    CodexAppServerRuntimeRecord,
    CodexReplyWritebackMode,
)
import agent_os.application.services.codex_session_control as codex_session_control_module
from agent_os.application.services.local_platform_operations import (
    LocalPlatformOperationService,
)
from agent_os.local_runtime import (
    _codex_activation_backend,
    _codex_app_server_approval_decision,
    _codex_control_config,
    _codex_git_repo_check_policy,
)
from agent_os.infrastructure.persistence.context_update_events import (
    SqliteContextUpdateEventRecorder,
)
from agent_os.infrastructure.persistence.conversations import SqliteConversationStore
from agent_os.infrastructure.persistence.event_log import SqlitePlatformEventLog
from agent_os.infrastructure.persistence.file_operation_records import (
    SqliteFileOperationRecordStore,
)
from agent_os.infrastructure.persistence.invocation_records import (
    SqliteAgentInvocationRecordStore,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteAgentRegistrationStateStore,
    SqliteContextStateStore,
    SqliteIssueStateStore,
    SqliteTaskStateStore,
    SqliteWorkspaceStateStore,
)
from agent_os.infrastructure.persistence.sqlite_persistence import (
    SqlitePlatformPersistence,
)
from agent_os.domain.value_objects.identifiers import WorkspaceId


class CodexRegisteredSessionContractTests(unittest.TestCase):
    def test_windows_process_liveness_never_uses_os_kill(self) -> None:
        with (
            mock.patch.object(codex_session_control_module, "_IS_WINDOWS", True),
            mock.patch.object(
                codex_session_control_module,
                "_windows_process_is_alive",
                return_value=True,
            ) as windows_probe,
            mock.patch.object(
                codex_session_control_module.os,
                "kill",
                side_effect=AssertionError("os.kill must not run on Windows"),
            ) as os_kill,
        ):
            self.assertTrue(codex_session_control_module.process_is_alive(424242))

        windows_probe.assert_called_once_with(424242)
        os_kill.assert_not_called()

    def test_closed_runtime_does_not_probe_historical_owner_pid(self) -> None:
        runtime = CodexAppServerRuntimeRecord(
            runtime_id="runtime-closed",
            activation_attempt_id="activation-closed",
            workspace_id="workspace-codex",
            agent_id="agent-b",
            handle_id="codex-handle-1",
            native_thread_id="thread-closed",
            native_session_id="thread-closed",
            native_turn_id=None,
            owner_pid=424242,
            transport="stdio",
            beacon_version="0.1.1",
            state="closed",
            started_at="2026-07-18T00:00:00+00:00",
            updated_at="2026-07-18T00:01:00+00:00",
            ended_at="2026-07-18T00:01:00+00:00",
            owner_connection_alive=False,
        )

        with mock.patch.object(
            codex_session_control_module,
            "process_is_alive",
            side_effect=AssertionError("closed runtime must not probe a stale PID"),
        ):
            metadata = runtime.to_metadata()

        self.assertFalse(metadata["ownerProcessAlive"])
        self.assertFalse(metadata["runtimeAlive"])
        self.assertFalse(metadata["canSteer"])

    def test_activation_stdin_matches_reply_writeback_mode(self) -> None:
        common = {
            "ticket_path": "X:/ticket.json",
            "exchange_request_id": "request-1",
            "source_agent_id": "planner",
            "target_agent_id": "reviewer",
            "request_kind": "review",
            "request_summary": "Review the change.",
        }

        explicit = build_codex_activation_stdin(
            **common,
            reply_writeback_mode=CodexReplyWritebackMode.EXPLICIT_ONLY,
        )
        captured = build_codex_activation_stdin(
            **common,
            reply_writeback_mode=CodexReplyWritebackMode.PROVIDER_FINAL_CAPTURE,
        )

        self.assertIn("will not automatically register", explicit)
        self.assertIn("beacon agent-reply", explicit)
        self.assertIn("--request request-1", explicit)
        self.assertIn("--agent reviewer", explicit)
        self.assertIn("intended explicit reply path", explicit)
        self.assertNotIn("capture that final answer", explicit)
        self.assertIn("capture that final answer", captured)
        self.assertNotIn("beacon agent-reply", captured)

    def test_handle_accepts_session_id_but_rejects_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            handle = CodexRegisteredSessionHandle.from_mapping(
                {
                    "workspaceId": "workspace-codex",
                    "agentId": "agent-b",
                    "handleId": "handle-1",
                    "codexSessionId": str(uuid4()),
                    "cwd": directory,
                    "createdBy": "user",
                    "reason": "explicit registration",
                }
            )

            self.assertEqual(handle.provider, "codex-cli")
            self.assertFalse(handle.to_metadata()["credentialStored"])

            with self.assertRaisesRegex(ValueError, "credential"):
                CodexRegisteredSessionHandle.from_mapping(
                    {
                        "workspaceId": "workspace-codex",
                        "agentId": "agent-b",
                        "handleId": "handle-2",
                        "codexSessionId": str(uuid4()),
                        "cwd": directory,
                        "createdBy": "user",
                        "reason": "explicit registration",
                        "metadata": {"token": "secret"},
                    }
                )

    def test_rendered_exec_resume_argv_uses_bounded_official_path_without_default_permission_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_path = root / "last.txt"
            session_id = str(uuid4())
            argv = render_codex_exec_resume_argv(
                session_id,
                codex_executable="codex",
                cwd=str(root),
                add_dirs=(str(root / "platform-workspace"),),
                output_last_message_path=str(output_path),
            )

            self.assertEqual(argv[0], "codex")
            self.assertIn("--cd", argv)
            self.assertIn(str(root), argv)
            self.assertIn("--add-dir", argv)
            self.assertIn(str(root / "platform-workspace"), argv)
            self.assertNotIn("--sandbox", argv)
            self.assertNotIn("--ask-for-approval", argv)
            self.assertIn("exec", argv)
            self.assertIn("resume", argv)
            self.assertIn("--json", argv)
            self.assertIn("--skip-git-repo-check", argv)
            self.assertEqual(
                argv.index("--skip-git-repo-check"),
                argv.index("--json") + 1,
            )
            self.assertIn("--output-last-message", argv)
            self.assertIn(str(output_path), argv)
            self.assertEqual(argv[-2:], (session_id, "-"))
            self.assertNotIn("remote-control", argv)
            self.assertNotIn("cloud", argv)

    def test_rendered_exec_resume_argv_strict_preserves_provider_repo_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            argv = render_codex_exec_resume_argv(
                str(uuid4()),
                cwd=directory,
                git_repo_check_policy="strict",
            )

            self.assertNotIn("--skip-git-repo-check", argv)

    def test_profile_repo_check_policy_is_used_without_cli_override(self) -> None:
        policy, source = _codex_git_repo_check_policy(
            argparse.Namespace(codex_git_repo_check_policy=None),
            {"codexGitRepoCheckPolicy": "strict"},
        )

        self.assertEqual(policy, "strict")
        self.assertEqual(source, "profile")

    def test_backend_and_safe_approval_resolve_explicit_then_profile_then_default(self) -> None:
        explicit_args = argparse.Namespace(
            codex_activation_backend="app_server",
            codex_app_server_approval_decision="accept_for_session",
        )
        self.assertEqual(
            _codex_activation_backend(explicit_args, {}),
            ("app_server", "explicit_cli"),
        )
        self.assertEqual(
            _codex_app_server_approval_decision(explicit_args, {}),
            ("accept_for_session", "explicit_cli"),
        )

        inherited_args = argparse.Namespace(
            codex_activation_backend=None,
            codex_app_server_approval_decision=None,
        )
        self.assertEqual(
            _codex_activation_backend(
                inherited_args,
                {"codexActivationBackend": "app_server"},
            ),
            ("app_server", "profile"),
        )
        self.assertEqual(
            _codex_app_server_approval_decision(inherited_args, {}),
            ("decline", "default"),
        )

    def test_nested_codex_control_config_has_documented_precedence_and_defaults(self) -> None:
        inherited = argparse.Namespace(
            codex_activation_backend=None,
            codex_status_read_mode=None,
            codex_supplement_mode=None,
            codex_busy_delivery_policy=None,
            codex_reply_writeback_mode=None,
        )
        nested = _codex_control_config(
            inherited,
            {
                "codexControl": {
                    "activationBackend": "app_server",
                    "statusReadMode": "app_server_point_read",
                    "supplementMode": "disabled",
                    "busyDeliveryPolicy": "reject",
                    "replyWritebackMode": "provider_final_capture",
                },
                "codexActivationBackend": "exec_resume",
            },
        )

        self.assertEqual(nested.activation_backend.value, "app_server")
        self.assertEqual(
            nested.activation_backend.source,
            "localRuntime.codexControl",
        )
        self.assertEqual(nested.status_read_mode.value, "app_server_point_read")
        self.assertEqual(nested.supplement_mode.value, "disabled")
        self.assertEqual(nested.busy_delivery_policy.value, "reject")
        self.assertEqual(
            nested.reply_writeback_mode.value,
            "provider_final_capture",
        )

        defaults = _codex_control_config(inherited, {})
        self.assertEqual(defaults.activation_backend.value, "exec_resume")
        self.assertEqual(defaults.status_read_mode.value, "beacon_snapshot")
        self.assertEqual(defaults.supplement_mode.value, "turn_steer")
        self.assertEqual(defaults.busy_delivery_policy.value, "queue_next_turn")
        self.assertEqual(defaults.reply_writeback_mode.value, "explicit_only")

        explicit = _codex_control_config(
            argparse.Namespace(
                codex_activation_backend="exec_resume",
                codex_status_read_mode="beacon_snapshot",
                codex_supplement_mode="turn_steer",
                codex_busy_delivery_policy="queue_next_turn",
                codex_reply_writeback_mode="explicit_only",
            ),
            {"codexControl": {"activationBackend": "app_server"}},
        )
        self.assertEqual(explicit.activation_backend.value, "exec_resume")
        self.assertEqual(explicit.activation_backend.source, "explicit_cli")

    def test_rendered_exec_resume_argv_accepts_explicit_permission_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session_id = str(uuid4())
            argv = render_codex_exec_resume_argv(
                session_id,
                codex_executable="codex",
                cwd=str(root),
                sandbox_mode="workspace-write",
                approval_policy="never",
            )

            self.assertIn("--sandbox", argv)
            self.assertIn("workspace-write", argv)
            self.assertIn("--ask-for-approval", argv)
            self.assertIn("never", argv)

    def test_extracts_codex_last_message_before_json_stdout(self) -> None:
        stdout = json.dumps({"type": "result", "result": "stdout response"})

        self.assertEqual(
            extract_codex_json_response(
                stdout,
                last_message_text="last message response",
            ),
            "last message response",
        )
        self.assertEqual(
            extract_codex_json_response(stdout),
            "stdout response",
        )

    def test_extracts_last_explicit_codex_agent_message(self) -> None:
        stdout = "\n".join(
            json.dumps(event)
            for event in (
                {"type": "thread.started", "thread_id": "thread-1"},
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "first answer"},
                },
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "content": [{"type": "text", "text": "final answer"}],
                    },
                },
            )
        )

        self.assertEqual(extract_codex_json_response(stdout), "final answer")

    def test_ignores_codex_error_reconnect_and_unknown_text_events(self) -> None:
        stdout = "\n".join(
            (
                json.dumps(
                    {
                        "type": "error",
                        "message": "Reconnecting... request timed out.",
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "error",
                            "message": "Falling back from WebSockets to HTTPS.",
                        },
                    }
                ),
                json.dumps({"type": "warning", "text": "experimental option"}),
                json.dumps({"type": "unknown", "content": "not an answer"}),
                "{malformed-json",
            )
        )

        self.assertIsNone(extract_codex_json_response(stdout))

    def test_resolves_explicit_codex_executable_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "codex.cmd"
            executable.write_text("@echo off\n", encoding="utf-8")

            resolution = resolve_codex_executable(str(executable))

            self.assertEqual(resolution.requested_executable, str(executable))
            self.assertEqual(resolution.resolved_executable, str(executable))
            self.assertEqual(resolution.resolution_source, "explicit_path_exists")

    def test_resolves_default_codex_executable_through_runtime_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = _fake_version_command(root, "codex", "codex-cli 9.8.7")

            with mock.patch.dict(os.environ, {"PATH": str(root)}, clear=False):
                resolution = resolve_codex_executable("codex")

            self.assertEqual(resolution.requested_executable, "codex")
            self.assertEqual(resolution.resolved_executable, str(executable))
            self.assertEqual(resolution.resolution_source, "agent_runtime_preflight")

    def test_passed_executable_preflight_does_not_inherit_activation_failure(self) -> None:
        attempt = CodexRegisteredSessionActivationAttempt(
            workspace_id="workspace-codex",
            agent_id="agent-b",
            handle_id="codex-handle-1",
            exchange_request_id="req-codex-1",
            thread_id="req-codex-1",
            wake_ticket_id="wake-ticket-1",
            status=CodexRegisteredSessionActivationStatus.FAILED,
            executable_preflight_status="passed",
            failure_category="command_exit_nonzero",
        )

        metadata = attempt.to_metadata()

        self.assertEqual(metadata["failureCategory"], "command_exit_nonzero")
        self.assertIsNone(metadata["executablePreflight"]["failureCategory"])

    def test_legacy_activation_event_defaults_to_exec_resume_backend(self) -> None:
        attempt = CodexRegisteredSessionActivationAttempt.from_mapping(
            {
                "workspaceId": "workspace-codex",
                "agentId": "agent-b",
                "handleId": "codex-handle-1",
                "exchangeRequestId": "req-codex-1",
                "threadId": "req-codex-1",
                "wakeTicketId": "wake-ticket-1",
                "status": "delivered",
            }
        )

        self.assertEqual(attempt.backend.value, "exec_resume")
        self.assertEqual(attempt.to_metadata()["activationBackend"], "exec_resume")
        self.assertNotIn("appServer", attempt.to_metadata())

    def test_fake_app_server_without_capture_path_does_not_write_none_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = _fake_codex_app_server_command(
                root,
                thread_id="test-thread",
                response_text="done",
            )

            subprocess.run(
                [str(command), "--version"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertFalse((root / "None").exists())


class CodexRegisteredSessionOperationTests(unittest.TestCase):
    def test_durable_supplement_is_steered_exactly_once_by_active_runner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "platform.sqlite3"
            bootstrap = sqlite3.connect(database)
            SqlitePlatformPersistence(bootstrap).initialize()
            bootstrap_service = _service(bootstrap)
            _seed_workspace(bootstrap_service)
            session_id = str(uuid4())
            bootstrap_service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                codex_session_id=session_id,
                cwd=directory,
                created_by="user",
                reason="explicit registration",
            )
            bootstrap.close()
            command = _fake_codex_app_server_command(
                root,
                thread_id=session_id,
                response_text="steered response",
                wait_for_steer=True,
            )
            activation_result: dict[str, object] = {}
            activation_error: list[BaseException] = []

            def activate() -> None:
                connection = sqlite3.connect(database)
                try:
                    result = _service(connection).activate_codex_registered_session(
                        "workspace-codex",
                        agent_id="agent-b",
                        handle_id="codex-handle-1",
                        exchange_request_id="req-codex-1",
                        database_path=str(database),
                        workspace_root=str(root / "workspace"),
                        plugins_directory=str(root / "plugins"),
                        handoff_directory=str(root / "handoff"),
                        codex_executable=str(command),
                        activation_backend="app_server",
                        dry_run=False,
                        timeout_seconds=10,
                    )
                    activation_result.update(result)
                except BaseException as exc:  # surfaced in the parent assertion
                    activation_error.append(exc)
                finally:
                    connection.close()

            runner = threading.Thread(target=activate, daemon=True)
            runner.start()
            connection = sqlite3.connect(database)
            service = _service(connection)
            deadline = time.monotonic() + 5
            active_runtime = None
            while time.monotonic() < deadline:
                active_runtime = service._latest_codex_app_server_runtime(
                    WorkspaceId("workspace-codex"),
                    handle_id="codex-handle-1",
                )
                if active_runtime is not None and active_runtime.can_steer:
                    break
                time.sleep(0.05)
            self.assertIsNotNone(active_runtime)
            self.assertTrue(active_runtime.can_steer)

            submission = service.submit_codex_session_supplement(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                message="Preserve the existing public contract.",
                expected_turn_id="turn-1",
                submitted_by="agent-a",
                supplement_id="supplement-live-1",
                wait_once=True,
                wait_timeout_seconds=5,
            )
            runner.join(timeout=8)
            connection.close()

            self.assertFalse(runner.is_alive())
            self.assertEqual(activation_error, [])
            self.assertEqual(
                submission["codexSessionSupplement"]["status"],
                "accepted",
            )
            activation = activation_result["codexRegisteredSessionActivation"]
            self.assertEqual(
                activation["appServerClientRequestMethods"].count("turn/steer"),
                1,
            )

    def test_status_prefers_live_beacon_owned_runtime_and_exposes_can_steer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                codex_session_id=session_id,
                cwd=directory,
                created_by="user",
                reason="explicit registration",
            )
            now = datetime.now(timezone.utc)
            service._append_codex_app_server_runtime(
                WorkspaceId("workspace-codex"),
                runtime=CodexAppServerRuntimeRecord(
                    runtime_id="runtime-1",
                    activation_attempt_id="attempt-1",
                    workspace_id="workspace-codex",
                    agent_id="agent-b",
                    handle_id="codex-handle-1",
                    native_thread_id=session_id,
                    native_session_id=session_id,
                    native_turn_id="turn-1",
                    owner_pid=os.getpid(),
                    transport="stdio",
                    beacon_version="0.1.1",
                    state="active",
                    started_at=now.isoformat(),
                    updated_at=now.isoformat(),
                ),
                action="active",
                occurred_at=now,
            )

            status = service.get_codex_session_status(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                status_read_mode="app_server_point_read",
            )

            self.assertEqual(status["statusSource"], "beacon_runtime_snapshot")
            self.assertEqual(status["runtimeState"], "active")
            self.assertEqual(status["nativeTurnId"], "turn-1")
            self.assertTrue(status["ownedRuntime"])
            self.assertTrue(status["canSteer"])
            self.assertNotIn("appServerPointRead", status)

    def test_point_status_reports_active_unowned_not_found_and_system_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-status-handle",
                codex_session_id=session_id,
                cwd=directory,
                created_by="user",
                reason="status fixture",
            )
            active_command = _fake_codex_app_server_command(
                root,
                thread_id=session_id,
                response_text="unused",
                thread_status="active",
            )
            active = service.get_codex_session_status(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-status-handle",
                status_read_mode="app_server_point_read",
                codex_executable=str(active_command),
            )
            self.assertEqual(active["threadStatus"], "active")
            self.assertEqual(
                active["runtimeOwner"],
                "active_different_or_unowned_runtime",
            )
            self.assertFalse(active["canSteer"])
            self.assertIn("active_different_or_unowned_runtime", active["guidance"])

            not_found_command = _fake_codex_app_server_command(
                root,
                thread_id=session_id,
                response_text="unused",
                thread_status="not_found",
            )
            not_found = service.get_codex_session_status(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-status-handle",
                status_read_mode="app_server_point_read",
                codex_executable=str(not_found_command),
            )
            self.assertFalse(not_found["threadFound"])
            self.assertEqual(
                not_found["failureCategory"],
                "app_server_thread_not_found",
            )
            self.assertIn("CODEX_HOME", not_found["failureGuidance"])

            system_error_command = _fake_codex_app_server_command(
                root,
                thread_id=session_id,
                response_text="unused",
                thread_status="systemError",
            )
            system_error = service.get_codex_session_status(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-status-handle",
                status_read_mode="app_server_point_read",
                codex_executable=str(system_error_command),
            )
            self.assertEqual(system_error["threadStatus"], "systemError")
            self.assertEqual(
                system_error["failureCategory"],
                "app_server_thread_system_error",
            )
            self.assertTrue(system_error["retryable"])

    def test_supplement_submission_is_durable_idempotent_and_does_not_create_turn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                codex_session_id=session_id,
                cwd=directory,
                created_by="user",
                reason="explicit registration",
            )

            first = service.submit_codex_session_supplement(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                message="Do not change the public API.",
                expected_turn_id="turn-1",
                submitted_by="agent-a",
                supplement_id="supplement-idempotent",
            )
            replay = service.submit_codex_session_supplement(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                message="Do not change the public API.",
                expected_turn_id="turn-1",
                submitted_by="agent-a",
                supplement_id="supplement-idempotent",
            )

            self.assertEqual(
                first["codexSessionSupplement"]["status"],
                "no_active_turn",
            )
            self.assertFalse(first["providerTurnCreated"])
            self.assertTrue(replay["idempotentReplay"])
            count = connection.execute(
                "SELECT COUNT(*) FROM platform_events WHERE event_kind = ?",
                ("codex_session_supplement.changed",),
            ).fetchone()[0]
            self.assertEqual(count, 1)

    def test_supplement_disabled_stale_unowned_and_stale_owner_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-control-handle",
                codex_session_id=session_id,
                cwd=directory,
                created_by="user",
                reason="control outcomes fixture",
            )

            disabled = service.submit_codex_session_supplement(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-control-handle",
                message="disabled",
                expected_turn_id="turn-1",
                submitted_by="agent-a",
                supplement_id="supplement-disabled",
                supplement_mode="disabled",
            )
            self.assertEqual(
                disabled["codexSessionSupplement"]["status"],
                "supplement_disabled",
            )

            def append_runtime(
                runtime_id: str,
                *,
                native_turn_id: str | None,
                owner_pid: int = os.getpid(),
            ) -> None:
                now = datetime.now(timezone.utc)
                service._append_codex_app_server_runtime(
                    WorkspaceId("workspace-codex"),
                    runtime=CodexAppServerRuntimeRecord(
                        runtime_id=runtime_id,
                        activation_attempt_id=f"attempt-{runtime_id}",
                        workspace_id="workspace-codex",
                        agent_id="agent-b",
                        handle_id="codex-control-handle",
                        native_thread_id=session_id,
                        native_session_id=session_id,
                        native_turn_id=native_turn_id,
                        owner_pid=owner_pid,
                        transport="stdio",
                        beacon_version="0.1.1",
                        state="active",
                        started_at=now.isoformat(),
                        updated_at=now.isoformat(),
                        metadata={"threadVerified": True},
                    ),
                    action="active",
                    occurred_at=now,
                )

            append_runtime("runtime-unowned", native_turn_id=None)
            unowned = service.submit_codex_session_supplement(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-control-handle",
                message="unowned",
                expected_turn_id="turn-1",
                submitted_by="agent-a",
                supplement_id="supplement-unowned",
            )
            self.assertEqual(
                unowned["codexSessionSupplement"]["status"],
                "runtime_not_owned",
            )

            time.sleep(0.002)
            append_runtime("runtime-stale-turn", native_turn_id="turn-2")
            stale = service.submit_codex_session_supplement(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-control-handle",
                message="stale",
                expected_turn_id="turn-1",
                submitted_by="agent-a",
                supplement_id="supplement-stale",
            )
            self.assertEqual(
                stale["codexSessionSupplement"]["status"],
                "stale_turn",
            )

            time.sleep(0.002)
            append_runtime(
                "runtime-dead-owner",
                native_turn_id="turn-3",
                owner_pid=2_000_000_000,
            )
            status = service.get_codex_session_status(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-control-handle",
            )
            self.assertEqual(status["appServerRuntime"]["state"], "closed")
            self.assertFalse(status["runtimeAlive"])
            self.assertFalse(status["canSteer"])
            self.assertEqual(
                status["appServerRuntime"]["metadata"]["readTimeCorrection"],
                "stale_owner_cleanup",
            )

    def test_dry_run_renders_ticket_and_command_without_provider_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                codex_session_id=session_id,
                cwd=directory,
                created_by="user",
                reason="explicit registration",
            )

            result = service.activate_codex_registered_session(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                exchange_request_id="req-codex-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                dry_run=True,
            )
            activation = result["codexRegisteredSessionActivation"]

            self.assertEqual(activation["status"], "dry_run")
            self.assertFalse(activation["providerCommandStarted"])
            self.assertIn("exec", activation["commandArgvSummary"])
            self.assertIn("resume", activation["commandArgvSummary"])
            self.assertIn(session_id, activation["commandArgvSummary"])
            self.assertIn("--add-dir", activation["commandArgvSummary"])
            self.assertIn(str(root.resolve()), activation["commandArgvSummary"])
            self.assertNotIn("--sandbox", activation["commandArgvSummary"])
            self.assertNotIn("--ask-for-approval", activation["commandArgvSummary"])
            self.assertIn("--skip-git-repo-check", activation["commandArgvSummary"])
            self.assertEqual(activation["gitRepoCheckPolicy"], "skip")
            self.assertEqual(activation["gitRepoCheckPolicySource"], "default")
            self.assertTrue(activation["skipGitRepoCheckRendered"])
            self.assertFalse(activation["gitRepoCheck"]["permissionPostureChanged"])
            self.assertIn(
                "Please review the Codex resume path.",
                result["stdinPreview"],
            )
            self.assertIn("Do not start a shell", result["stdinPreview"])
            self.assertEqual(activation["platformWorkspaceRoot"], str(root.resolve()))
            self.assertEqual(activation["addDirPaths"], [str(root.resolve())])
            self.assertEqual(
                activation["permissionStandardization"]["scope"],
                "platform_workspace",
            )
            profile = activation["providerPermissionProfile"]
            self.assertFalse(profile["selected"])
            self.assertEqual(profile["selectionSource"], "default_no_permission_profile")
            self.assertFalse(profile["permissionPostureChangingArgsInjected"])
            self.assertEqual(_codex_activation_event_count(connection), 1)
            self.assertEqual(_wake_event_count(connection), 0)

    def test_app_server_dry_run_is_complete_alternative_without_cli_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                codex_session_id=session_id,
                cwd=directory,
                created_by="user",
                reason="explicit registration",
            )

            result = service.activate_codex_registered_session(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                exchange_request_id="req-codex-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                activation_backend="app_server",
                dry_run=True,
            )
            activation = result["codexRegisteredSessionActivation"]

            self.assertEqual(activation["status"], "dry_run")
            self.assertEqual(activation["activationBackend"], "app_server")
            self.assertEqual(
                activation["commandArgvSummary"][-2:],
                ["app-server", "--stdio"],
            )
            self.assertNotIn("exec", activation["commandArgvSummary"])
            self.assertNotIn("outputLastMessagePath", activation)
            self.assertFalse(activation["skipGitRepoCheckRendered"])
            self.assertEqual(activation["providerTransport"], "stdio")
            self.assertTrue(activation["appServerStableApiOnly"])
            self.assertFalse(activation["appServer"]["experimentalApiEnabled"])

    def test_app_server_execute_completes_same_beacon_request_and_audit_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                codex_session_id=session_id,
                cwd=directory,
                created_by="user",
                reason="explicit registration",
            )
            command = _fake_codex_app_server_command(
                root,
                thread_id=session_id,
                response_text="app-server completed response",
            )

            result = service.activate_codex_registered_session(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                exchange_request_id="req-codex-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                codex_executable=str(command),
                activation_backend="app_server",
                reply_writeback_mode="provider_final_capture",
                dry_run=False,
            )
            activation = result["codexRegisteredSessionActivation"]
            request = service.get_agent_exchange_request_status(
                "workspace-codex",
                exchange_request_id="req-codex-1",
            )["agentExchangeRequest"]

            self.assertEqual(activation["status"], "delivered")
            self.assertEqual(activation["activationBackend"], "app_server")
            self.assertTrue(activation["providerCommandStarted"])
            self.assertTrue(activation["sessionContinuityVerified"])
            self.assertTrue(activation["targetResponseCompleted"])
            self.assertEqual(activation["responseCaptureStatus"], "recorded")
            self.assertEqual(activation["nativeThreadId"], session_id)
            self.assertEqual(activation["nativeTurnId"], "turn-1")
            self.assertEqual(activation["nativeTurnStatus"], "completed")
            self.assertEqual(activation["responsePhase"], "final_answer")
            self.assertEqual(activation["appServerApprovalDecision"], "decline")
            self.assertTrue(activation["appServerResumePolicyVerified"])
            self.assertEqual(activation["appServerEffectiveCwd"], str(root))
            self.assertEqual(activation["appServerEffectiveSandbox"], "read-only")
            self.assertFalse(activation["appServerEffectiveNetworkAccess"])
            self.assertEqual(
                activation["appServerEffectiveApprovalPolicy"],
                "on-request",
            )
            self.assertEqual(
                activation["appServerClientRequestMethods"],
                ["initialize", "thread/read", "thread/resume", "turn/start"],
            )
            self.assertIn("turn/completed", activation["appServerNotificationMethods"])
            self.assertEqual(request["responseSummary"], "app-server completed response")
            self.assertEqual(request["terminalReason"], "responded")
            self.assertEqual(_codex_activation_event_count(connection), 2)
            self.assertEqual(_wake_event_count(connection), 1)
            runtime_payloads = [
                json.loads(str(row[0]))
                for row in connection.execute(
                    "SELECT payload_json FROM platform_events WHERE event_kind = ? "
                    "ORDER BY sequence",
                    ("codex_app_server_runtime.changed",),
                ).fetchall()
            ]
            self.assertGreaterEqual(len(runtime_payloads), 4)
            runtime_states = [entry["runtime"]["state"] for entry in runtime_payloads]
            self.assertIn("starting", runtime_states)
            self.assertIn("idle", runtime_states)
            self.assertIn("active", runtime_states)
            self.assertIn("completed", runtime_states)
            self.assertEqual(runtime_states[-1], "closed")
            self.assertFalse(runtime_payloads[-1]["runtime"]["canSteer"])
            self.assertNotIn(
                "Please review the Codex resume path.",
                json.dumps(runtime_payloads, ensure_ascii=False),
            )

    def test_app_server_default_explicit_only_does_not_write_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-explicit-only-handle",
                codex_session_id=session_id,
                cwd=directory,
                created_by="user",
                reason="explicit-only fixture",
            )
            command = _fake_codex_app_server_command(
                root,
                thread_id=session_id,
                response_text="provider final text is not an explicit Beacon reply",
            )

            result = service.activate_codex_registered_session(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-explicit-only-handle",
                exchange_request_id="req-codex-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                codex_executable=str(command),
                activation_backend="app_server",
                dry_run=False,
            )
            activation = result["codexRegisteredSessionActivation"]
            request = service.get_agent_exchange_request_status(
                "workspace-codex",
                exchange_request_id="req-codex-1",
            )["agentExchangeRequest"]

            self.assertEqual(activation["status"], "delivered")
            self.assertEqual(activation["replyWritebackMode"], "explicit_only")
            self.assertEqual(
                activation["responseCaptureStatus"],
                "skipped_by_reply_writeback_policy",
            )
            self.assertFalse(activation["targetResponseCompleted"])
            self.assertIsNone(request.get("responseSummary"))
            self.assertIsNone(request.get("terminalReason"))
            summary = service.get_agent_exchange_status_summary(
                "workspace-codex",
                exchange_request_id="req-codex-1",
            )
            provider_events = [
                event
                for event in summary["statusTimeline"]["events"]
                if event.get("subject") == "provider_activation"
            ]
            self.assertTrue(provider_events)
            self.assertEqual(provider_events[-1]["stage"], "delivered")

    def test_registered_codex_home_reaches_point_read_and_app_server(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            custom_home = (root / "custom-codex-home").resolve()
            custom_home.mkdir()
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-custom-home-app-server",
                codex_session_id=session_id,
                cwd=directory,
                created_by="user",
                reason="custom home fixture",
                metadata={
                    "codexSessionIdentity": {
                        "schema": "codex_session_identity.v1",
                        "providerSessionId": session_id,
                        "runtimeHome": str(custom_home),
                        "runtimeHomeSource": "explicit",
                    }
                },
            )
            capture_path = root / "app-server-environment.json"
            command = _fake_codex_app_server_command(
                root,
                thread_id=session_id,
                response_text="done",
                capture_path=capture_path,
            )

            status = service.get_codex_session_status(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-custom-home-app-server",
                status_read_mode="app_server_point_read",
                codex_executable=str(command),
            )
            self.assertEqual(status["runtimeHome"], str(custom_home))
            self.assertEqual(
                json.loads(capture_path.read_text(encoding="utf-8"))["codexHome"],
                str(custom_home),
            )

            result = service.activate_codex_registered_session(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-custom-home-app-server",
                exchange_request_id="req-codex-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                codex_executable=str(command),
                activation_backend="app_server",
                dry_run=False,
            )
            activation = result["codexRegisteredSessionActivation"]
            self.assertEqual(activation["runtimeHome"], str(custom_home))
            self.assertEqual(activation["runtimeHomeSource"], "explicit")
            self.assertEqual(
                json.loads(capture_path.read_text(encoding="utf-8"))["codexHome"],
                str(custom_home),
            )

    def test_registered_codex_home_reaches_exec_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            custom_home = (root / "custom-codex-home").resolve()
            custom_home.mkdir()
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-custom-home-exec",
                codex_session_id=session_id,
                cwd=directory,
                created_by="user",
                reason="custom home exec fixture",
                metadata={
                    "codexSessionIdentity": {
                        "schema": "codex_session_identity.v1",
                        "providerSessionId": session_id,
                        "runtimeHome": str(custom_home),
                        "runtimeHomeSource": "explicit",
                    }
                },
            )
            capture_path = root / "exec-environment.json"
            command = _fake_codex_command(
                root,
                session_id,
                capture_path,
                "done",
            )

            result = service.activate_codex_registered_session(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-custom-home-exec",
                exchange_request_id="req-codex-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                codex_executable=str(command),
                dry_run=False,
            )

            activation = result["codexRegisteredSessionActivation"]
            captured = json.loads(capture_path.read_text(encoding="utf-8"))
            self.assertEqual(captured["codexHome"], str(custom_home))
            self.assertEqual(activation["runtimeHome"], str(custom_home))

    def test_app_server_busy_is_retryable_and_does_not_poison_next_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                codex_session_id=session_id,
                cwd=directory,
                created_by="user",
                reason="explicit registration",
            )
            command = _fake_codex_app_server_command(
                root,
                thread_id=session_id,
                response_text="unused",
                thread_status="active",
            )
            kwargs = {
                "agent_id": "agent-b",
                "handle_id": "codex-handle-1",
                "exchange_request_id": "req-codex-1",
                "database_path": str(root / "platform.sqlite3"),
                "workspace_root": str(root / "workspace"),
                "plugins_directory": str(root / "plugins"),
                "handoff_directory": str(root / "handoff"),
                "codex_executable": str(command),
                "activation_backend": "app_server",
                "dry_run": False,
            }

            first = service.activate_codex_registered_session(
                "workspace-codex",
                **kwargs,
            )["codexRegisteredSessionActivation"]
            second = service.activate_codex_registered_session(
                "workspace-codex",
                **kwargs,
            )["codexRegisteredSessionActivation"]

            self.assertEqual(first["status"], "failed")
            self.assertEqual(second["status"], "failed")
            self.assertNotEqual(second["status"], "skipped")
            self.assertEqual(first["failureCategory"], "app_server_thread_busy")
            self.assertTrue(first["retryable"])
            self.assertFalse(first["targetResponseCompleted"])
            self.assertNotIn("nativeTurnId", first)
            self.assertNotIn("turn/start", first["appServerClientRequestMethods"])

    def test_worker_executes_complete_app_server_backend_and_completes_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            command = _fake_codex_app_server_command(
                root,
                thread_id=session_id,
                response_text="worker app-server response",
            )
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-app-server-worker-handle",
                codex_session_id=session_id,
                cwd=directory,
                created_by="user",
                reason="worker app-server fixture",
            )
            service.create_agent_dispatch(
                "workspace-codex",
                dispatch_id="dispatch-app-server-worker",
                exchange_request_id="req-app-server-worker",
                source_agent_id="agent-a",
                target_agent_id="agent-b",
                target_handle_id="codex-app-server-worker-handle",
                target_provider="codex-cli",
                request_kind="review",
                request_summary="Complete through the app-server worker backend.",
            )

            result = service.run_agent_dispatch_worker_once(
                "workspace-codex",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                codex_executable=str(command),
                codex_activation_backend="app_server",
                codex_reply_writeback_mode="provider_final_capture",
                dry_run=False,
            )
            item = result["agentDispatches"][0]

            self.assertEqual(result["processedCount"], 1)
            self.assertEqual(item["finalStatus"], "completed")
            self.assertEqual(item["agentDispatch"]["status"], "completed")
            self.assertEqual(item["activation"]["activationBackend"], "app_server")
            self.assertTrue(item["activation"]["targetResponseCompleted"])
            self.assertEqual(item["agentDispatchLease"]["state"], "released")

    def test_explicit_permission_profile_is_rendered_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                codex_session_id=session_id,
                cwd=directory,
                created_by="user",
                reason="explicit registration",
            )

            result = service.activate_codex_registered_session(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                exchange_request_id="req-codex-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                sandbox_mode="workspace-write",
                approval_policy="never",
                dry_run=True,
            )
            activation = result["codexRegisteredSessionActivation"]
            profile = activation["providerPermissionProfile"]

            self.assertIn("--sandbox", activation["commandArgvSummary"])
            self.assertIn("workspace-write", activation["commandArgvSummary"])
            self.assertIn("--ask-for-approval", activation["commandArgvSummary"])
            self.assertIn("never", activation["commandArgvSummary"])
            self.assertTrue(profile["selected"])
            self.assertEqual(profile["selectionSource"], "explicit_activation_arguments")
            self.assertTrue(profile["permissionPostureChangingArgsInjected"])
            self.assertEqual(
                activation["permissionStandardization"][
                    "providerPermissionProfileSelectionSource"
                ],
                "explicit_activation_arguments",
            )

    def test_default_ticket_path_uses_short_provider_neutral_components(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace_root = root / ("workspace-" + "r" * 48)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            workspace_id = "workspace-" + "w" * 96
            target_agent_id = "agent-" + "a" * 96
            request_id = "agent-exchange-request-" + "q" * 120
            service.create_workspace(
                workspace_id=workspace_id,
                display_name="Long Id Workspace",
                root_path=str(workspace_root),
                agent_id="agent-source",
                agent_name="Source",
                agent_description="Source agent.",
            )
            service.create_agent_registration(
                workspace_id,
                agent_id=target_agent_id,
                name="Long Target",
                description="Target agent.",
            )
            service.create_agent_exchange_request(
                workspace_id,
                exchange_request_id=request_id,
                source_agent_id="agent-source",
                target_agent_id=target_agent_id,
                request_kind="handoff",
                request_summary="Use default wake ticket path.",
            )
            service.register_codex_session_handle(
                workspace_id,
                agent_id=target_agent_id,
                handle_id="codex-handle-long",
                codex_session_id=str(uuid4()),
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )

            result = service.activate_codex_registered_session(
                workspace_id,
                agent_id=target_agent_id,
                handle_id="codex-handle-long",
                exchange_request_id=request_id,
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(workspace_root),
                plugins_directory=str(root / "plugins"),
                dry_run=True,
            )
            activation = result["codexRegisteredSessionActivation"]
            ticket_path = Path(str(activation["ticketPath"]))

            self.assertEqual(ticket_path.parent.parent.name, "wake_tickets")
            self.assertTrue(ticket_path.parent.name.startswith("ws-"))
            self.assertIn(".agent-", ticket_path.parent.name)
            self.assertTrue(ticket_path.name.startswith("req-"))
            self.assertIn(".wake-", ticket_path.name)
            self.assertLessEqual(len(ticket_path.parent.name), 46)
            self.assertLessEqual(len(ticket_path.name), 48)
            self.assertNotIn(request_id, str(ticket_path))
            self.assertNotIn(target_agent_id, str(ticket_path))

    def test_execute_uses_fake_codex_fixture_and_auto_captures_last_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            capture_path = root / "capture.json"
            response_text = "received smoke ticket from Codex registered session."
            fake_codex = _fake_codex_command(root, session_id, capture_path, response_text)
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                codex_session_id=session_id,
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )

            result = service.activate_codex_registered_session(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                exchange_request_id="req-codex-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                codex_executable=str(fake_codex),
                reply_writeback_mode="provider_final_capture",
                dry_run=False,
            )
            activation = result["codexRegisteredSessionActivation"]
            capture = json.loads(capture_path.read_text(encoding="utf-8"))
            request = service.get_agent_exchange_request_status(
                "workspace-codex",
                exchange_request_id="req-codex-1",
            )["agentExchangeRequest"]
            status = service.get_agent_wake_status(
                "workspace-codex",
                exchange_request_id="req-codex-1",
            )["agentWakeStatus"]

            self.assertEqual(activation["status"], "delivered")
            self.assertEqual(activation["commandExitCode"], 0)
            self.assertTrue(activation["providerCommandStarted"])
            self.assertTrue(activation["sessionContinuityVerified"])
            self.assertTrue(activation["targetResponseCompleted"])
            self.assertEqual(activation["requestedCodexExecutable"], str(fake_codex))
            self.assertEqual(activation["resolvedCodexExecutable"], str(fake_codex))
            self.assertEqual(activation["executablePreflightStatus"], "passed")
            self.assertEqual(activation["executablePreflightExitCode"], 0)
            self.assertIsNone(activation.get("failureCategory"))
            self.assertIn("exec", capture["argv"])
            self.assertIn("resume", capture["argv"])
            self.assertIn(session_id, capture["argv"])
            self.assertNotIn("--sandbox", capture["argv"])
            self.assertNotIn("--ask-for-approval", capture["argv"])
            self.assertIn("Please review the Codex resume path.", capture["stdin"])
            self.assertIn("Do not start a shell", capture["stdin"])
            self.assertEqual(
                activation["responseCaptureMode"],
                "codex_exec_resume_json_last_message",
            )
            self.assertEqual(activation["responseCaptureStatus"], "recorded")
            self.assertEqual(request["terminalReason"], "responded")
            self.assertEqual(request["respondedByAgentId"], "agent-b")
            self.assertEqual(request["responseSummary"], response_text)
            self.assertEqual(
                request["metadata"]["responseSource"],
                "codex_exec_resume_auto_capture",
            )
            self.assertTrue(status["ticketDeliveryOccurred"])
            self.assertTrue(status["providerCommandStarted"])
            self.assertTrue(status["runtimeWakeTriggered"])
            self.assertTrue(status["targetResponseCompleted"])
            self.assertEqual(_codex_activation_event_count(connection), 2)
            self.assertEqual(
                status["codexRegisteredSessionActivationCount"],
                1,
            )
            self.assertEqual(_wake_event_count(connection), 1)

    def test_exec_resume_default_explicit_only_does_not_write_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            fake_codex = _fake_codex_command(
                root,
                session_id,
                root / "explicit-only-capture.json",
                "provider final text is not an explicit Beacon reply",
            )
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-explicit-only-exec",
                codex_session_id=session_id,
                cwd=str(root),
                created_by="user",
                reason="explicit-only exec fixture",
            )

            result = service.activate_codex_registered_session(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-explicit-only-exec",
                exchange_request_id="req-codex-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                codex_executable=str(fake_codex),
                dry_run=False,
            )
            activation = result["codexRegisteredSessionActivation"]
            request = service.get_agent_exchange_request_status(
                "workspace-codex",
                exchange_request_id="req-codex-1",
            )["agentExchangeRequest"]

            self.assertEqual(activation["replyWritebackMode"], "explicit_only")
            self.assertEqual(
                activation["responseCaptureStatus"],
                "skipped_by_reply_writeback_policy",
            )
            self.assertFalse(activation["targetResponseCompleted"])
            self.assertIsNone(request.get("responseSummary"))
            self.assertIsNone(request.get("terminalReason"))

    def test_execute_finishes_wait_once_when_final_message_precedes_process_exit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            response_text = "bounded final response"
            fake_codex = _fake_codex_command(
                root,
                session_id,
                root / "capture.json",
                response_text,
                hang_seconds=30,
            )
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                codex_session_id=session_id,
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )

            started_at = time.monotonic()
            result = service.activate_codex_registered_session(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                exchange_request_id="req-codex-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                codex_executable=str(fake_codex),
                reply_writeback_mode="provider_final_capture",
                dry_run=False,
                timeout_seconds=10,
            )
            elapsed = time.monotonic() - started_at
            activation = result["codexRegisteredSessionActivation"]
            request = service.get_agent_exchange_request_status(
                "workspace-codex",
                exchange_request_id="req-codex-1",
            )["agentExchangeRequest"]
            events = _codex_activation_events(connection)

            self.assertLess(elapsed, 8)
            self.assertEqual(activation["status"], "delivered")
            self.assertTrue(
                activation["providerProcessTerminatedAfterResponseCapture"]
            )
            self.assertFalse(activation["providerProcessTimedOut"])
            self.assertTrue(activation["targetResponseCompleted"])
            self.assertEqual(activation["responseCaptureStatus"], "recorded")
            self.assertEqual(request["responseSummary"], response_text)
            self.assertEqual([event["action"] for event in events], ["started", "delivered"])
            self.assertEqual(
                len({event["activation"]["activationAttemptId"] for event in events}),
                1,
            )

    def test_execute_captures_agent_message_without_diagnostic_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            response_text = "trusted final response"
            fake_codex = _fake_codex_command(
                root,
                session_id,
                root / "capture.json",
                response_text,
                write_last_message=False,
                stdout_events=[
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "error",
                            "message": "respect_system_proxy is under development",
                        },
                    },
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": response_text,
                        },
                    },
                ],
            )
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                codex_session_id=session_id,
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )

            result = service.activate_codex_registered_session(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                exchange_request_id="req-codex-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                codex_executable=str(fake_codex),
                reply_writeback_mode="provider_final_capture",
                dry_run=False,
            )
            activation = result["codexRegisteredSessionActivation"]
            request = service.get_agent_exchange_request_status(
                "workspace-codex",
                exchange_request_id="req-codex-1",
            )["agentExchangeRequest"]

            self.assertEqual(activation["status"], "delivered")
            self.assertTrue(activation["targetResponseCompleted"])
            self.assertEqual(activation["responseCaptureStatus"], "recorded")
            self.assertEqual(request["responseSummary"], response_text)
            self.assertNotIn("under development", request["responseSummary"])

    def test_timeout_with_only_error_events_keeps_request_unanswered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            reconnect_text = "Reconnecting... request timed out."
            fake_codex = _fake_codex_command(
                root,
                session_id,
                root / "capture.json",
                "unused response",
                hang_seconds=30,
                write_last_message=False,
                stdout_events=[
                    {"type": "error", "message": reconnect_text},
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "error",
                            "message": "Falling back from WebSockets to HTTPS.",
                        },
                    },
                ],
            )
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                codex_session_id=session_id,
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )

            result = service.activate_codex_registered_session(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                exchange_request_id="req-codex-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                codex_executable=str(fake_codex),
                reply_writeback_mode="provider_final_capture",
                dry_run=False,
                timeout_seconds=1,
            )
            activation = result["codexRegisteredSessionActivation"]
            request = service.get_agent_exchange_request_status(
                "workspace-codex",
                exchange_request_id="req-codex-1",
            )["agentExchangeRequest"]

            self.assertEqual(activation["status"], "failed")
            self.assertTrue(activation["providerProcessTimedOut"])
            self.assertFalse(activation["targetResponseCompleted"])
            self.assertEqual(
                activation["responseCaptureStatus"],
                "no_response_text_after_command_timeout",
            )
            self.assertEqual(activation["failureCategory"], "command_timeout")
            self.assertIn(reconnect_text, activation["stdoutTail"])
            self.assertNotIn("terminalReason", request)
            self.assertNotIn("responseSummary", request)

    def test_timeout_recovers_trusted_agent_message_for_user_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            response_text = "final response written before timeout"
            fake_codex = _fake_codex_command(
                root,
                session_id,
                root / "capture.json",
                response_text,
                hang_seconds=30,
                write_last_message=False,
                stdout_events=[
                    {"type": "error", "message": "temporary reconnect warning"},
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": response_text,
                        },
                    },
                ],
            )
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                codex_session_id=session_id,
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )

            result = service.activate_codex_registered_session(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                exchange_request_id="req-codex-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                codex_executable=str(fake_codex),
                reply_writeback_mode="provider_final_capture",
                dry_run=False,
                timeout_seconds=1,
            )
            activation = result["codexRegisteredSessionActivation"]
            request = service.get_agent_exchange_request_status(
                "workspace-codex",
                exchange_request_id="req-codex-1",
            )["agentExchangeRequest"]

            self.assertEqual(activation["status"], "failed")
            self.assertTrue(activation["providerProcessTimedOut"])
            self.assertTrue(activation["targetResponseCompleted"])
            self.assertEqual(
                activation["responseCaptureStatus"],
                "recorded_after_command_timeout",
            )
            self.assertEqual(
                activation["failureReason"],
                "command_timeout_after_response_capture",
            )
            self.assertEqual(request["terminalReason"], "responded")
            self.assertTrue(request["requiresUserReview"])
            self.assertEqual(request["responseSummary"], response_text)
            self.assertNotIn("reconnect warning", request["responseSummary"])

    def test_timeout_trusted_message_default_does_not_write_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            response_text = "final provider output before explicit-only timeout"
            fake_codex = _fake_codex_command(
                root,
                session_id,
                root / "capture.json",
                response_text,
                hang_seconds=30,
                write_last_message=False,
                stdout_events=[
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": response_text,
                        },
                    },
                ],
            )
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                codex_session_id=session_id,
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )

            result = service.activate_codex_registered_session(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                exchange_request_id="req-codex-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                codex_executable=str(fake_codex),
                dry_run=False,
                timeout_seconds=1,
            )
            activation = result["codexRegisteredSessionActivation"]
            request = service.get_agent_exchange_request_status(
                "workspace-codex",
                exchange_request_id="req-codex-1",
            )["agentExchangeRequest"]

            self.assertEqual(activation["replyWritebackMode"], "explicit_only")
            self.assertEqual(activation["status"], "failed")
            self.assertTrue(activation["providerProcessTimedOut"])
            self.assertFalse(activation["targetResponseCompleted"])
            self.assertEqual(
                activation["responseCaptureStatus"],
                "skipped_by_reply_writeback_policy",
            )
            self.assertNotIn("terminalReason", request)
            self.assertNotIn("responseSummary", request)

    def test_execute_keeps_repeated_calls_skipped_after_first_provider_start(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            capture_path = root / "capture.json"
            fake_codex = _fake_codex_command(
                root,
                session_id,
                capture_path,
                "first response",
            )
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                codex_session_id=session_id,
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )
            activation_kwargs = {
                "agent_id": "agent-b",
                "handle_id": "codex-handle-1",
                "exchange_request_id": "req-codex-1",
                "database_path": str(root / "platform.sqlite3"),
                "workspace_root": str(root / "workspace"),
                "plugins_directory": str(root / "plugins"),
                "handoff_directory": str(root / "handoff"),
                "codex_executable": str(fake_codex),
                "dry_run": False,
            }

            service.activate_codex_registered_session(
                "workspace-codex",
                **activation_kwargs,
            )
            capture_path.unlink()
            second = service.activate_codex_registered_session(
                "workspace-codex",
                **activation_kwargs,
            )
            third = service.activate_codex_registered_session(
                "workspace-codex",
                **activation_kwargs,
            )

            self.assertEqual(
                second["codexRegisteredSessionActivation"]["status"],
                "skipped",
            )
            self.assertEqual(
                third["codexRegisteredSessionActivation"]["status"],
                "skipped",
            )
            self.assertFalse(capture_path.exists())
            self.assertEqual(_codex_activation_event_count(connection), 4)

    def test_execute_classifies_missing_executable_before_ticket_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                codex_session_id=str(uuid4()),
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )

            result = service.activate_codex_registered_session(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                exchange_request_id="req-codex-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                codex_executable=str(root / "missing-codex.cmd"),
                dry_run=False,
            )
            activation = result["codexRegisteredSessionActivation"]

            self.assertEqual(activation["status"], "failed")
            self.assertFalse(activation["providerCommandStarted"])
            self.assertEqual(activation["executablePreflightStatus"], "failed")
            self.assertEqual(activation["failureCategory"], "executable_not_found")
            self.assertTrue(activation["retryable"])
            self.assertEqual(_codex_activation_event_count(connection), 1)
            self.assertEqual(_wake_event_count(connection), 0)

    def test_local_runtime_cli_registers_lists_and_dry_runs_handle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session_id = str(uuid4())
            created = _run_cli(
                root,
                "workspace-create",
                "--workspace-id",
                "workspace-cli-codex",
                "--agent-id",
                "agent-a",
                "--display-name",
                "CLI Codex Workspace",
                "--root-path",
                str(root),
            )
            agent = _run_cli(
                root,
                "agent-create",
                "--workspace-id",
                "workspace-cli-codex",
                "--agent-id",
                "agent-b",
                "--name",
                "Agent B",
                "--description",
                "Codex target.",
            )
            request = _run_cli(
                root,
                "agent-exchange-request-create",
                "--workspace-id",
                "workspace-cli-codex",
                "--exchange-request-id",
                "req-cli-codex",
                "--source-agent-id",
                "agent-a",
                "--target-agent-id",
                "agent-b",
                "--request-kind",
                "review",
                "--request-summary",
                "Please review via registered Codex session.",
            )
            registered = _run_cli(
                root,
                "codex-session-handle-register",
                "--workspace-id",
                "workspace-cli-codex",
                "--agent-id",
                "agent-b",
                "--handle-id",
                "handle-cli-codex",
                "--codex-session-id",
                session_id,
                "--cwd",
                str(root),
                "--created-by",
                "user",
                "--reason",
                "explicit CLI registration",
            )
            listed = _run_cli(
                root,
                "codex-session-handle-list",
                "--workspace-id",
                "workspace-cli-codex",
                "--agent-id",
                "agent-b",
            )
            activated = _run_cli(
                root,
                "codex-registered-session-activate",
                "--workspace-id",
                "workspace-cli-codex",
                "--agent-id",
                "agent-b",
                "--handle-id",
                "handle-cli-codex",
                "--exchange-request-id",
                "req-cli-codex",
                "--handoff-directory",
                str(root / "handoff"),
                "--codex-path",
                str(root / "codex.cmd"),
                "--codex-git-repo-check-policy",
                "strict",
                "--activation-backend",
                "app_server",
                "--app-server-approval-decision",
                "decline",
                "--dry-run",
            )
            status_result = _run_cli(
                root,
                "codex-session-status",
                "--workspace-id",
                "workspace-cli-codex",
                "--agent-id",
                "agent-b",
                "--handle-id",
                "handle-cli-codex",
            )
            supplement_result = _run_cli(
                root,
                "codex-session-supplement",
                "--workspace-id",
                "workspace-cli-codex",
                "--agent-id",
                "agent-b",
                "--handle-id",
                "handle-cli-codex",
                "--message",
                "Only supplement an active owned turn.",
                "--expected-turn-id",
                "turn-missing",
                "--submitted-by",
                "agent-a",
                "--supplement-id",
                "supplement-cli-no-active",
            )

            for result in (
                created,
                agent,
                request,
                registered,
                listed,
                activated,
                status_result,
                supplement_result,
            ):
                self.assertEqual(result.returncode, 0, result.stderr)

            registered_payload = json.loads(registered.stdout)
            listed_payload = json.loads(listed.stdout)
            activated_payload = json.loads(activated.stdout)
            activation = activated_payload["codexRegisteredSessionActivation"]
            status_payload = json.loads(status_result.stdout)
            supplement_payload = json.loads(supplement_result.stdout)

            self.assertEqual(
                registered_payload["codexSessionHandle"]["codexSessionId"],
                session_id,
            )
            self.assertEqual(len(listed_payload["codexSessionHandles"]), 1)
            self.assertEqual(activation["status"], "dry_run")
            self.assertEqual(activation["activationBackend"], "app_server")
            self.assertEqual(
                activation["commandArgvSummary"][-2:],
                ["app-server", "--stdio"],
            )
            self.assertFalse(activation["providerCommandStarted"])
            self.assertNotIn("--add-dir", activation["commandArgvSummary"])
            self.assertNotIn("--sandbox", activation["commandArgvSummary"])
            self.assertNotIn("--ask-for-approval", activation["commandArgvSummary"])
            self.assertEqual(activation["requestedCodexExecutable"], str(root / "codex.cmd"))
            self.assertEqual(activation["executablePreflightStatus"], "not_run_dry_run")
            self.assertEqual(activation["platformWorkspaceRoot"], str(root.resolve()))
            self.assertTrue(
                activation["permissionStandardization"][
                    "defaultPlatformWorkspaceAddDir"
                ]
            )
            self.assertFalse(activation["providerPermissionProfile"]["selected"])
            self.assertEqual(activation["gitRepoCheckPolicy"], "strict")
            self.assertEqual(activation["gitRepoCheckPolicySource"], "explicit_cli")
            self.assertFalse(activation["skipGitRepoCheckRendered"])
            self.assertNotIn("--skip-git-repo-check", activation["commandArgvSummary"])
            self.assertEqual(
                activated_payload["codexControl"]["activationBackend"],
                {"value": "app_server", "source": "explicit_cli"},
            )
            self.assertEqual(status_payload["schema"], "codex_session_status.v1")
            self.assertEqual(status_payload["statusReadMode"], "beacon_snapshot")
            self.assertFalse(status_payload["canSteer"])
            self.assertEqual(
                supplement_payload["codexSessionSupplement"]["status"],
                "no_active_turn",
            )
            self.assertEqual(
                supplement_payload["deliveryType"],
                "supplement_active_turn",
            )
            self.assertFalse(supplement_payload["providerTurnCreated"])

    def test_execute_strict_classifies_trusted_directory_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            service.register_codex_session_handle(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                codex_session_id=str(uuid4()),
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )

            result = service.activate_codex_registered_session(
                "workspace-codex",
                agent_id="agent-b",
                handle_id="codex-handle-1",
                exchange_request_id="req-codex-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                codex_executable=str(_fake_trusted_directory_failure_command(root)),
                git_repo_check_policy="strict",
                git_repo_check_policy_source="explicit_api",
                dry_run=False,
            )
            activation = result["codexRegisteredSessionActivation"]

            self.assertEqual(activation["status"], "failed")
            self.assertEqual(activation["failureCategory"], "codex_git_repo_check_failed")
            self.assertIn("strict", activation["failureGuidance"])
            self.assertEqual(activation["gitRepoCheckPolicy"], "strict")
            self.assertEqual(activation["gitRepoCheckPolicySource"], "explicit_api")
            self.assertFalse(activation["skipGitRepoCheckRendered"])
            self.assertNotIn("--skip-git-repo-check", activation["commandArgvSummary"])


def _fake_codex_command(
    root: Path,
    session_id: str,
    capture_path: Path,
    response_text: str,
    *,
    hang_seconds: int = 0,
    write_last_message: bool = True,
    stdout_events: list[dict[str, object]] | None = None,
) -> Path:
    script = root / "fake_codex.py"
    command = root / ("fake_codex.cmd" if os.name == "nt" else "fake_codex")
    script.write_text(
        "\n".join(
            [
                "import json, os, pathlib, sys, time",
                f"SESSION_ID = {session_id!r}",
                f"RESPONSE_TEXT = {response_text!r}",
                f"CAPTURE_PATH = pathlib.Path({str(capture_path)!r})",
                f"HANG_SECONDS = {hang_seconds!r}",
                f"WRITE_LAST_MESSAGE = {write_last_message!r}",
                f"STDOUT_EVENTS = {stdout_events!r}",
                "if '--version' in sys.argv[1:]:",
                "    print('codex-cli fake')",
                "    raise SystemExit(0)",
                "stdin = sys.stdin.read()",
                "argv = sys.argv[1:]",
                "output_path = None",
                "for index, item in enumerate(argv):",
                "    if item in {'--output-last-message', '-o'} and index + 1 < len(argv):",
                "        output_path = pathlib.Path(argv[index + 1])",
                "if output_path is not None and WRITE_LAST_MESSAGE:",
                "    output_path.parent.mkdir(parents=True, exist_ok=True)",
                "    output_path.write_text(RESPONSE_TEXT, encoding='utf-8')",
                "CAPTURE_PATH.write_text(json.dumps({",
                "  'argv': argv,",
                "  'cwd': os.getcwd(),",
                "  'stdin': stdin,",
                "  'codexHome': os.environ.get('CODEX_HOME'),",
                "}, sort_keys=True), encoding='utf-8')",
                "events = STDOUT_EVENTS or [{'type': 'result', 'session_id': SESSION_ID, 'result': RESPONSE_TEXT}]",
                "for event in events:",
                "    print(json.dumps(event), flush=True)",
                "if HANG_SECONDS:",
                "    time.sleep(HANG_SECONDS)",
            ]
        ),
        encoding="utf-8",
    )
    if os.name == "nt":
        command.write_text(
            "\n".join(["@echo off", f'"{sys.executable}" "{script}" %*']),
            encoding="utf-8",
        )
    else:
        command.write_text(
            "\n".join(
                [
                    "#!/bin/sh",
                    f"exec {shlex.quote(sys.executable)} {shlex.quote(str(script))} \"$@\"",
                ]
            ),
            encoding="utf-8",
        )
        command.chmod(0o755)
    return command


def _fake_version_command(root: Path, tool: str, version_line: str) -> Path:
    if os.name == "nt":
        command = root / f"{tool}.cmd"
        command.write_text(
            "\n".join(["@echo off", f"echo {version_line}"]),
            encoding="utf-8",
        )
        return command
    command = root / tool
    command.write_text(
        "\n".join(["#!/bin/sh", f"echo {version_line}"]),
        encoding="utf-8",
    )
    command.chmod(0o755)
    return command


def _fake_codex_app_server_command(
    root: Path,
    *,
    thread_id: str,
    response_text: str,
    thread_status: str = "idle",
    wait_for_steer: bool = False,
    capture_path: Path | None = None,
) -> Path:
    script = root / "fake_codex_app_server.py"
    command = root / (
        "fake_codex_app_server.cmd" if os.name == "nt" else "fake_codex_app_server"
    )
    script.write_text(
        "\n".join(
            [
                "import json, os, pathlib, sys",
                f"THREAD_ID = {thread_id!r}",
                f"RESPONSE_TEXT = {response_text!r}",
                f"THREAD_STATUS = {thread_status!r}",
                f"WAIT_FOR_STEER = {wait_for_steer!r}",
                f"CAPTURE_PATH = {(str(capture_path) if capture_path is not None else None)!r}",
                "if CAPTURE_PATH:",
                "    pathlib.Path(CAPTURE_PATH).write_text(json.dumps({'codexHome': os.environ.get('CODEX_HOME')}), encoding='utf-8')",
                "if '--version' in sys.argv[1:]:",
                "    print('codex-cli fake-app-server')",
                "    raise SystemExit(0)",
                "def send(value):",
                "    print(json.dumps(value), flush=True)",
                "for line in sys.stdin:",
                "    message = json.loads(line)",
                "    method = message.get('method')",
                "    request_id = message.get('id')",
                "    if request_id is None:",
                "        continue",
                "    if method == 'initialize':",
                "        send({'id': request_id, 'result': {'userAgent': 'fake-codex/1'}})",
                "    elif method == 'thread/read':",
                "        if THREAD_STATUS == 'not_found':",
                "            send({'id': request_id, 'error': {'code': -32000, 'message': 'thread not found'}})",
                "        else:",
                "            send({'id': request_id, 'result': {'thread': {'id': THREAD_ID, 'sessionId': THREAD_ID, 'status': {'type': THREAD_STATUS}}}})",
                "    elif method == 'thread/resume':",
                "        params = message.get('params', {})",
                "        sandbox = params.get('sandbox', 'read-only')",
                "        if sandbox == 'workspace-write':",
                "            extra = params.get('config', {}).get('sandbox_workspace_write', {}).get('writable_roots', [])",
                "            policy = {'type': 'workspaceWrite', 'writableRoots': [params.get('cwd'), *extra], 'networkAccess': False}",
                "        elif sandbox == 'danger-full-access':",
                "            policy = {'type': 'dangerFullAccess'}",
                "        else:",
                "            policy = {'type': 'readOnly', 'networkAccess': False}",
                "        send({'id': request_id, 'result': {'thread': {'id': THREAD_ID, 'sessionId': THREAD_ID, 'status': {'type': 'idle'}}, 'cwd': params.get('cwd'), 'sandbox': policy, 'approvalPolicy': params.get('approvalPolicy', 'on-request'), 'approvalsReviewer': 'user', 'model': 'fake', 'modelProvider': 'fake'}})",
                "    elif method == 'turn/start':",
                "        send({'id': request_id, 'result': {'turn': {'id': 'turn-1', 'status': 'inProgress'}}})",
                "        if not WAIT_FOR_STEER:",
                "            send({'method': 'item/completed', 'params': {'threadId': THREAD_ID, 'turnId': 'turn-1', 'item': {'type': 'agentMessage', 'id': 'item-1', 'text': RESPONSE_TEXT, 'phase': 'final_answer'}}})",
                "            send({'method': 'turn/completed', 'params': {'threadId': THREAD_ID, 'turn': {'id': 'turn-1', 'status': 'completed'}}})",
                "    elif method == 'turn/steer':",
                "        send({'id': request_id, 'result': {'turnId': 'turn-1'}})",
                "        send({'method': 'item/completed', 'params': {'threadId': THREAD_ID, 'turnId': 'turn-1', 'item': {'type': 'agentMessage', 'id': 'item-1', 'text': RESPONSE_TEXT, 'phase': 'final_answer'}}})",
                "        send({'method': 'turn/completed', 'params': {'threadId': THREAD_ID, 'turn': {'id': 'turn-1', 'status': 'completed'}}})",
                "    elif method == 'turn/interrupt':",
                "        send({'id': request_id, 'result': {}})",
                "    else:",
                "        send({'id': request_id, 'error': {'code': -32601, 'message': 'unknown method'}})",
            ]
        ),
        encoding="utf-8",
    )
    if os.name == "nt":
        command.write_text(
            "\n".join(["@echo off", f'"{sys.executable}" "{script}" %*']),
            encoding="utf-8",
        )
    else:
        command.write_text(
            "\n".join(
                [
                    "#!/bin/sh",
                    f"exec {shlex.quote(sys.executable)} {shlex.quote(str(script))} \"$@\"",
                ]
            ),
            encoding="utf-8",
        )
        command.chmod(0o755)
    return command


def _fake_trusted_directory_failure_command(root: Path) -> Path:
    script = root / "fake_codex_trusted_directory_failure.py"
    command = root / (
        "fake_codex_trusted_directory_failure.cmd"
        if os.name == "nt"
        else "fake_codex_trusted_directory_failure"
    )
    script.write_text(
        "\n".join(
            [
                "import sys",
                "if '--version' in sys.argv:",
                "    print('codex-cli 9.8.7')",
                "    raise SystemExit(0)",
                "print('Not inside a trusted directory and --skip-git-repo-check was not specified.', file=sys.stderr)",
                "raise SystemExit(1)",
            ]
        ),
        encoding="utf-8",
    )
    if os.name == "nt":
        command.write_text(
            "\n".join(["@echo off", f'"{sys.executable}" "{script}" %*']),
            encoding="utf-8",
        )
    else:
        command.write_text(
            "\n".join(
                [
                    "#!/bin/sh",
                    f"exec {shlex.quote(sys.executable)} {shlex.quote(str(script))} \"$@\"",
                ]
            ),
            encoding="utf-8",
        )
        command.chmod(0o755)
    return command


def _run_cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_SRC)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_os.local_runtime",
            "--database",
            str(root / "platform.sqlite3"),
            "--workspace-root",
            str(root),
            "--plugins-directory",
            str(root / "plugins"),
            *args,
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _seed_workspace(service: LocalPlatformOperationService) -> None:
    service.create_workspace(
        workspace_id="workspace-codex",
        display_name="Codex Workspace",
        root_path="X:/fixture/beacon-project",
        agent_id="agent-a",
        agent_name="Agent A",
        agent_description="Source agent.",
    )
    service.create_agent_registration(
        "workspace-codex",
        agent_id="agent-b",
        name="Agent B",
        description="Codex target agent.",
    )
    service.create_agent_exchange_request(
        "workspace-codex",
        exchange_request_id="req-codex-1",
        source_agent_id="agent-a",
        target_agent_id="agent-b",
        request_kind="review",
        request_summary="Please review the Codex resume path.",
    )


def _codex_activation_event_count(connection: sqlite3.Connection) -> int:
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM platform_events WHERE event_kind = ?",
            ("codex_registered_session_activation.recorded",),
        ).fetchone()[0]
    )


def _codex_activation_events(connection: sqlite3.Connection) -> list[dict[str, object]]:
    rows = connection.execute(
        "SELECT payload_json FROM platform_events WHERE event_kind = ? ORDER BY sequence",
        ("codex_registered_session_activation.recorded",),
    ).fetchall()
    return [json.loads(str(row[0])) for row in rows]


def _wake_event_count(connection: sqlite3.Connection) -> int:
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM platform_events WHERE event_kind = ?",
            ("agent_wake.delivery_recorded",),
        ).fetchone()[0]
    )


def _service(connection: sqlite3.Connection) -> LocalPlatformOperationService:
    return LocalPlatformOperationService(
        workspace_reader=SqliteWorkspaceStateStore(connection),
        context_reader=SqliteContextStateStore(connection),
        context_update_recorder=SqliteContextUpdateEventRecorder(connection),
        event_log_reader=SqlitePlatformEventLog(connection),
        agent_invocation_reader=SqliteAgentInvocationRecordStore(connection),
        file_operation_reader=SqliteFileOperationRecordStore(connection),
        conversation_session_reader=SqliteConversationStore(connection),
        conversation_message_reader=SqliteConversationStore(connection),
        agent_registration_reader=SqliteAgentRegistrationStateStore(connection),
        task_reader=SqliteTaskStateStore(connection),
        issue_reader=SqliteIssueStateStore(connection),
        workspace_writer=SqliteWorkspaceStateStore(connection),
        context_writer=SqliteContextStateStore(connection),
        agent_registration_writer=SqliteAgentRegistrationStateStore(connection),
        conversation_session_writer=SqliteConversationStore(connection),
        conversation_message_writer=SqliteConversationStore(connection),
    )


if __name__ == "__main__":
    unittest.main()
