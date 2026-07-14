from __future__ import annotations

import argparse
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import tempfile
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
    extract_codex_json_response,
    render_codex_exec_resume_argv,
    resolve_codex_executable,
)
from agent_os.application.services.local_platform_operations import (
    LocalPlatformOperationService,
)
from agent_os.local_runtime import _codex_git_repo_check_policy
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


class CodexRegisteredSessionContractTests(unittest.TestCase):
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


class CodexRegisteredSessionOperationTests(unittest.TestCase):
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
                "--dry-run",
            )

            for result in (created, agent, request, registered, listed, activated):
                self.assertEqual(result.returncode, 0, result.stderr)

            registered_payload = json.loads(registered.stdout)
            listed_payload = json.loads(listed.stdout)
            activated_payload = json.loads(activated.stdout)
            activation = activated_payload["codexRegisteredSessionActivation"]

            self.assertEqual(
                registered_payload["codexSessionHandle"]["codexSessionId"],
                session_id,
            )
            self.assertEqual(len(listed_payload["codexSessionHandles"]), 1)
            self.assertEqual(activation["status"], "dry_run")
            self.assertFalse(activation["providerCommandStarted"])
            self.assertIn("--add-dir", activation["commandArgvSummary"])
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
