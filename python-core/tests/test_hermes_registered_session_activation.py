from __future__ import annotations

import json
import os
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from uuid import uuid4


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.hermes_registered_session import (
    HermesRegisteredSessionActivationAttempt,
    HermesRegisteredSessionActivationStatus,
    HermesRegisteredSessionHandle,
    evaluate_hermes_session_continuity,
    extract_hermes_chat_response,
    render_hermes_chat_resume_argv,
    resolve_hermes_executable,
)
from agent_os.application.services.local_platform_operations import (
    LocalPlatformOperationService,
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


class HermesRegisteredSessionContractTests(unittest.TestCase):
    def test_handle_accepts_session_id_but_rejects_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            handle = HermesRegisteredSessionHandle.from_mapping(
                {
                    "workspaceId": "workspace-hermes",
                    "agentId": "agent-b",
                    "handleId": "handle-1",
                    "hermesSessionId": str(uuid4()),
                    "cwd": directory,
                    "createdBy": "user",
                    "reason": "explicit registration",
                }
            )

            self.assertEqual(handle.provider, "hermes-cli")
            self.assertFalse(handle.to_metadata()["credentialStored"])

            with self.assertRaisesRegex(ValueError, "credential"):
                HermesRegisteredSessionHandle.from_mapping(
                    {
                        "workspaceId": "workspace-hermes",
                        "agentId": "agent-b",
                        "handleId": "handle-2",
                        "hermesSessionId": str(uuid4()),
                        "cwd": directory,
                        "createdBy": "user",
                        "reason": "explicit registration",
                        "metadata": {"token": "secret"},
                    }
                )

    def test_rendered_chat_resume_argv_uses_bounded_official_path(self) -> None:
        session_id = str(uuid4())
        argv = render_hermes_chat_resume_argv(
            session_id,
            hermes_executable="hermes",
            query="Read the wake ticket JSON.",
            source_tag="agent-os",
            max_turns=3,
        )

        self.assertEqual(argv[0], "hermes")
        self.assertIn("chat", argv)
        self.assertIn("--query", argv)
        self.assertIn("Read the wake ticket JSON.", argv)
        self.assertIn("--quiet", argv)
        self.assertIn("--resume", argv)
        self.assertIn(session_id, argv)
        self.assertIn("--source", argv)
        self.assertIn("agent-os", argv)
        self.assertIn("--max-turns", argv)
        self.assertIn("3", argv)
        self.assertNotIn("--yolo", argv)
        self.assertNotIn("gateway", argv)
        self.assertNotIn("desktop", argv)

    def test_activation_metadata_marks_default_permission_profile_unselected(self) -> None:
        attempt = HermesRegisteredSessionActivationAttempt(
            workspace_id="workspace-hermes",
            agent_id="agent-b",
            handle_id="hermes-handle-1",
            exchange_request_id="req-hermes-1",
            thread_id="req-hermes-1",
            wake_ticket_id="wake-ticket-1",
            status=HermesRegisteredSessionActivationStatus.DRY_RUN,
        )

        profile = attempt.to_metadata()["providerPermissionProfile"]

        self.assertFalse(profile["selected"])
        self.assertEqual(profile["selectionSource"], "default_no_permission_profile")
        self.assertFalse(profile["permissionPostureChangingArgsInjected"])
        self.assertIn("--yolo", profile["dangerousBypassArgs"])

    def test_extracts_stdout_response_text(self) -> None:
        self.assertEqual(
            extract_hermes_chat_response("\nfinal captured response\n"),
            "final captured response",
        )
        self.assertIsNone(extract_hermes_chat_response("   "))

    def test_continuity_requires_provider_resume_evidence(self) -> None:
        expected = "20260710_120000_expected"

        reflected = evaluate_hermes_session_continuity(
            f"answer\nsession_id={expected}\n",
            "",
            expected,
        )
        resumed = evaluate_hermes_session_continuity(
            "answer",
            f"\x1b[36m↻ Resumed session {expected}\x1b[0m",
            expected,
        )

        self.assertEqual(reflected.verification, "unverified")
        self.assertFalse(reflected.verified)
        self.assertEqual(resumed.verification, "verified")
        self.assertTrue(resumed.verified)

    def test_resolves_default_hermes_executable_through_runtime_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = _fake_version_command(root, "hermes", "Hermes Agent v9.8.7")

            with mock.patch.dict(os.environ, {"PATH": str(root)}, clear=False):
                resolution = resolve_hermes_executable("hermes")

            self.assertEqual(resolution.requested_executable, "hermes")
            self.assertEqual(resolution.resolved_executable, str(executable))
            self.assertEqual(resolution.resolution_source, "agent_runtime_preflight")

    def test_passed_executable_preflight_does_not_inherit_activation_failure(self) -> None:
        attempt = HermesRegisteredSessionActivationAttempt(
            workspace_id="workspace-hermes",
            agent_id="agent-b",
            handle_id="hermes-handle-1",
            exchange_request_id="req-hermes-1",
            thread_id="req-hermes-1",
            wake_ticket_id="wake-ticket-1",
            status=HermesRegisteredSessionActivationStatus.FAILED,
            executable_preflight_status="passed",
            failure_category="command_timeout",
        )

        metadata = attempt.to_metadata()

        self.assertEqual(metadata["failureCategory"], "command_timeout")
        self.assertIsNone(metadata["executablePreflight"]["failureCategory"])


class HermesRegisteredSessionOperationTests(unittest.TestCase):
    def test_dry_run_renders_ticket_and_command_without_provider_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            service.register_hermes_session_handle(
                "workspace-hermes",
                agent_id="agent-b",
                handle_id="hermes-handle-1",
                hermes_session_id=session_id,
                cwd=directory,
                created_by="user",
                reason="explicit registration",
                metadata={
                    "hermesSessionIdentity": {
                        "schema": "hermes_session_identity.v1",
                        "providerSessionId": session_id,
                        "runtimeHome": str(root),
                        "runtimeHomeSource": "explicit",
                        "sessionSource": "cli",
                        "fullSessionHistoryRead": False,
                    }
                },
            )

            result = service.activate_hermes_registered_session(
                "workspace-hermes",
                agent_id="agent-b",
                handle_id="hermes-handle-1",
                exchange_request_id="req-hermes-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                dry_run=True,
            )
            activation = result["hermesRegisteredSessionActivation"]

            self.assertEqual(activation["status"], "dry_run")
            self.assertFalse(activation["providerCommandStarted"])
            self.assertIn("chat", activation["commandArgvSummary"])
            self.assertIn("--query", activation["commandArgvSummary"])
            self.assertIn("--resume", activation["commandArgvSummary"])
            self.assertIn(session_id, activation["commandArgvSummary"])
            self.assertIn("Read the wake ticket JSON at:", result["queryPreview"])
            self.assertEqual(activation["platformWorkspaceRoot"], str(root.resolve()))
            self.assertEqual(activation["sourceTag"], "agent-os")
            self.assertFalse(activation["activationBoundary"]["desktopSessionTakeover"])
            profile = activation["providerPermissionProfile"]
            self.assertFalse(profile["selected"])
            self.assertEqual(profile["selectionSource"], "default_no_permission_profile")
            self.assertEqual(_hermes_activation_event_count(connection), 1)
            self.assertEqual(_wake_event_count(connection), 0)

    def test_execute_uses_fake_hermes_fixture_and_auto_captures_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            capture_path = root / "capture.json"
            response_text = "received smoke ticket from Hermes registered session."
            fake_hermes = _fake_hermes_command(root, session_id, capture_path, response_text)
            service.register_hermes_session_handle(
                "workspace-hermes",
                agent_id="agent-b",
                handle_id="hermes-handle-1",
                hermes_session_id=session_id,
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
                metadata={
                    "hermesSessionIdentity": {
                        "schema": "hermes_session_identity.v1",
                        "providerSessionId": session_id,
                        "runtimeHome": str(root),
                        "runtimeHomeSource": "explicit",
                        "sessionSource": "cli",
                        "fullSessionHistoryRead": False,
                    }
                },
            )

            result = service.activate_hermes_registered_session(
                "workspace-hermes",
                agent_id="agent-b",
                handle_id="hermes-handle-1",
                exchange_request_id="req-hermes-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                hermes_executable=str(fake_hermes),
                dry_run=False,
            )
            activation = result["hermesRegisteredSessionActivation"]
            capture = json.loads(capture_path.read_text(encoding="utf-8"))
            request = service.get_agent_exchange_request_status(
                "workspace-hermes",
                exchange_request_id="req-hermes-1",
            )["agentExchangeRequest"]
            status = service.get_agent_wake_status(
                "workspace-hermes",
                exchange_request_id="req-hermes-1",
            )["agentWakeStatus"]

            self.assertEqual(activation["status"], "delivered")
            self.assertEqual(activation["commandExitCode"], 0)
            self.assertTrue(activation["providerCommandStarted"])
            self.assertTrue(activation["sessionContinuityVerified"])
            self.assertEqual(activation["expectedSessionVerification"], "verified")
            self.assertTrue(activation["responseInstanceVerified"])
            self.assertFalse(activation["responseRequiresUserReview"])
            self.assertTrue(activation["targetResponseCompleted"])
            self.assertEqual(activation["requestedHermesExecutable"], str(fake_hermes))
            self.assertEqual(activation["resolvedHermesExecutable"], str(fake_hermes))
            self.assertEqual(activation["executablePreflightStatus"], "passed")
            self.assertEqual(activation["runtimeHome"], str(root.resolve()))
            self.assertEqual(
                activation["runtimeHomeSource"],
                "registered_session_identity",
            )
            self.assertEqual(activation["registeredSessionSource"], "cli")
            self.assertEqual(capture["hermesHome"], str(root.resolve()))
            self.assertIn("chat", capture["argv"])
            self.assertIn("--query", capture["argv"])
            self.assertIn("--resume", capture["argv"])
            self.assertIn(session_id, capture["argv"])
            query = capture["argv"][capture["argv"].index("--query") + 1]
            self.assertIn("Read the wake ticket JSON at:", query)
            self.assertEqual(
                activation["responseCaptureMode"],
                "hermes_chat_query_stdout",
            )
            self.assertEqual(activation["responseCaptureStatus"], "recorded")
            self.assertEqual(request["terminalReason"], "responded")
            self.assertEqual(request["respondedByAgentId"], "agent-b")
            self.assertEqual(request["responseSummary"], response_text)
            self.assertEqual(
                request["metadata"]["responseSource"],
                "hermes_chat_query_auto_capture",
            )
            self.assertTrue(status["ticketDeliveryOccurred"])
            self.assertTrue(status["providerCommandStarted"])
            self.assertTrue(status["runtimeWakeTriggered"])
            self.assertTrue(status["targetResponseCompleted"])
            self.assertTrue(status["hermesRegisteredSessionActivationOccurred"])
            self.assertEqual(_hermes_activation_event_count(connection), 1)
            self.assertEqual(_wake_event_count(connection), 1)

    def test_execute_rejects_response_from_mismatched_resumed_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = "20260710_120000_expected"
            fake_hermes = _fake_hermes_command(
                root,
                session_id,
                root / "capture.json",
                "response from the wrong Hermes instance",
                resume_session_id="20260710_120001_wrong",
            )
            service.register_hermes_session_handle(
                "workspace-hermes",
                agent_id="agent-b",
                handle_id="hermes-handle-1",
                hermes_session_id=session_id,
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )

            result = service.activate_hermes_registered_session(
                "workspace-hermes",
                agent_id="agent-b",
                handle_id="hermes-handle-1",
                exchange_request_id="req-hermes-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                hermes_executable=str(fake_hermes),
                dry_run=False,
            )
            activation = result["hermesRegisteredSessionActivation"]
            request = service.get_agent_exchange_request_status(
                "workspace-hermes",
                exchange_request_id="req-hermes-1",
            )["agentExchangeRequest"]

            self.assertEqual(activation["status"], "failed")
            self.assertEqual(activation["expectedSessionVerification"], "mismatch")
            self.assertFalse(activation["expectedSessionVerified"])
            self.assertEqual(
                activation["failureCategory"],
                "hermes_expected_session_mismatch",
            )
            self.assertEqual(
                activation["responseCaptureStatus"],
                "rejected_expected_session_mismatch",
            )
            self.assertNotEqual(request.get("terminalReason"), "responded")

    def test_execute_marks_unverified_stdout_capture_for_user_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = "20260710_120000_unverified"
            fake_hermes = _fake_hermes_command(
                root,
                session_id,
                root / "capture.json",
                "stdout-only Hermes response",
                emit_resume_banner=False,
            )
            service.register_hermes_session_handle(
                "workspace-hermes",
                agent_id="agent-b",
                handle_id="hermes-handle-1",
                hermes_session_id=session_id,
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )

            result = service.activate_hermes_registered_session(
                "workspace-hermes",
                agent_id="agent-b",
                handle_id="hermes-handle-1",
                exchange_request_id="req-hermes-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                hermes_executable=str(fake_hermes),
                dry_run=False,
            )
            activation = result["hermesRegisteredSessionActivation"]
            request = service.get_agent_exchange_request_status(
                "workspace-hermes",
                exchange_request_id="req-hermes-1",
            )["agentExchangeRequest"]

            self.assertEqual(activation["status"], "delivered")
            self.assertEqual(activation["expectedSessionVerification"], "unverified")
            self.assertFalse(activation["expectedSessionVerified"])
            self.assertTrue(activation["responseRequiresUserReview"])
            self.assertEqual(
                activation["responseCaptureStatus"],
                "recorded_unverified_session",
            )
            self.assertEqual(request["terminalReason"], "responded")
            self.assertTrue(request["requiresUserReview"])
            self.assertEqual(
                request["metadata"]["responseSource"],
                "hermes_chat_query_auto_capture",
            )
            self.assertFalse(request["metadata"]["responseInstanceVerified"])

    def test_execute_classifies_missing_executable_before_ticket_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            service.register_hermes_session_handle(
                "workspace-hermes",
                agent_id="agent-b",
                handle_id="hermes-handle-1",
                hermes_session_id=str(uuid4()),
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )

            result = service.activate_hermes_registered_session(
                "workspace-hermes",
                agent_id="agent-b",
                handle_id="hermes-handle-1",
                exchange_request_id="req-hermes-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                hermes_executable=str(root / "missing-hermes.cmd"),
                dry_run=False,
            )
            activation = result["hermesRegisteredSessionActivation"]

            self.assertEqual(activation["status"], "failed")
            self.assertFalse(activation["providerCommandStarted"])
            self.assertEqual(activation["executablePreflightStatus"], "failed")
            self.assertEqual(activation["failureCategory"], "executable_not_found")
            self.assertTrue(activation["retryable"])
            self.assertEqual(_hermes_activation_event_count(connection), 1)
            self.assertEqual(_wake_event_count(connection), 0)

    def test_execute_replaces_invalid_utf8_provider_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            fake_hermes = _fake_hermes_invalid_utf8_command(root)
            service.register_hermes_session_handle(
                "workspace-hermes",
                agent_id="agent-b",
                handle_id="hermes-handle-1",
                hermes_session_id=session_id,
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )

            result = service.activate_hermes_registered_session(
                "workspace-hermes",
                agent_id="agent-b",
                handle_id="hermes-handle-1",
                exchange_request_id="req-hermes-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                hermes_executable=str(fake_hermes),
                dry_run=False,
            )
            activation = result["hermesRegisteredSessionActivation"]

            self.assertEqual(activation["status"], "failed")
            self.assertTrue(activation["providerCommandStarted"])
            self.assertEqual(activation["commandExitCode"], 7)
            self.assertIn("\ufffd", activation["stdoutTail"])

    def test_local_runtime_cli_registers_lists_and_dry_runs_handle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session_id = str(uuid4())
            created = _run_cli(
                root,
                "workspace-create",
                "--workspace-id",
                "workspace-cli-hermes",
                "--agent-id",
                "agent-a",
                "--display-name",
                "CLI Hermes Workspace",
                "--root-path",
                str(root),
            )
            agent = _run_cli(
                root,
                "agent-create",
                "--workspace-id",
                "workspace-cli-hermes",
                "--agent-id",
                "agent-b",
                "--name",
                "Agent B",
                "--description",
                "Hermes target.",
            )
            request = _run_cli(
                root,
                "agent-exchange-request-create",
                "--workspace-id",
                "workspace-cli-hermes",
                "--exchange-request-id",
                "req-cli-hermes",
                "--source-agent-id",
                "agent-a",
                "--target-agent-id",
                "agent-b",
                "--request-kind",
                "review",
                "--request-summary",
                "Please review via registered Hermes session.",
            )
            registered = _run_cli(
                root,
                "hermes-session-handle-register",
                "--workspace-id",
                "workspace-cli-hermes",
                "--agent-id",
                "agent-b",
                "--handle-id",
                "handle-cli-hermes",
                "--hermes-session-id",
                session_id,
                "--cwd",
                str(root),
                "--hermes-home",
                str(root),
                "--hermes-session-source",
                "cli",
                "--created-by",
                "user",
                "--reason",
                "explicit CLI registration",
            )
            listed = _run_cli(
                root,
                "hermes-session-handle-list",
                "--workspace-id",
                "workspace-cli-hermes",
                "--agent-id",
                "agent-b",
            )
            activated = _run_cli(
                root,
                "hermes-registered-session-activate",
                "--workspace-id",
                "workspace-cli-hermes",
                "--agent-id",
                "agent-b",
                "--handle-id",
                "handle-cli-hermes",
                "--exchange-request-id",
                "req-cli-hermes",
                "--handoff-directory",
                str(root / "handoff"),
                "--hermes-path",
                str(root / "hermes.cmd"),
                "--hermes-home",
                str(root),
                "--dry-run",
            )

            for result in (created, agent, request, registered, listed, activated):
                self.assertEqual(result.returncode, 0, result.stderr)

            registered_payload = json.loads(registered.stdout)
            listed_payload = json.loads(listed.stdout)
            activated_payload = json.loads(activated.stdout)
            activation = activated_payload["hermesRegisteredSessionActivation"]

            self.assertEqual(
                registered_payload["hermesSessionHandle"]["hermesSessionId"],
                session_id,
            )
            self.assertEqual(len(listed_payload["hermesSessionHandles"]), 1)
            self.assertEqual(activation["status"], "dry_run")
            self.assertFalse(activation["providerCommandStarted"])
            self.assertIn("--query", activation["commandArgvSummary"])
            self.assertEqual(activation["requestedHermesExecutable"], str(root / "hermes.cmd"))
            self.assertEqual(activation["executablePreflightStatus"], "not_run_dry_run")
            self.assertEqual(activation["platformWorkspaceRoot"], str(root.resolve()))
            self.assertEqual(activation["runtimeHome"], str(root.resolve()))
            self.assertEqual(activation["runtimeHomeSource"], "explicit")
            self.assertEqual(activation["registeredSessionSource"], "cli")
            self.assertFalse(activation["providerPermissionProfile"]["selected"])


def _fake_hermes_command(
    root: Path,
    session_id: str,
    capture_path: Path,
    response_text: str,
    *,
    resume_session_id: str | None = None,
    emit_resume_banner: bool = True,
) -> Path:
    script = root / "fake_hermes.py"
    command = root / ("fake_hermes.cmd" if os.name == "nt" else "fake_hermes")
    script.write_text(
        "\n".join(
            [
                "import json, os, pathlib, sys",
                f"SESSION_ID = {session_id!r}",
                f"RESUME_SESSION_ID = {(resume_session_id or session_id)!r}",
                f"EMIT_RESUME_BANNER = {emit_resume_banner!r}",
                f"RESPONSE_TEXT = {response_text!r}",
                "argv = sys.argv[1:]",
                "if argv in (['--version'], ['--help']):",
                "    print('Hermes Agent v9.8.7')",
                "    raise SystemExit(0)",
                "path = pathlib.Path(os.environ['FAKE_HERMES_CAPTURE'])",
                "path.write_text(json.dumps({",
                "  'argv': argv,",
                "  'cwd': os.getcwd(),",
                "  'hermesHome': os.environ.get('HERMES_HOME'),",
                "}, sort_keys=True), encoding='utf-8')",
                "print(RESPONSE_TEXT)",
                "print('session_id=' + SESSION_ID)",
                "if EMIT_RESUME_BANNER:",
                "    print('↻ Resumed session ' + RESUME_SESSION_ID, file=sys.stderr)",
            ]
        ),
        encoding="utf-8",
    )
    if os.name == "nt":
        command.write_text(
            "\n".join(
                [
                    "@echo off",
                    f"set FAKE_HERMES_CAPTURE={capture_path}",
                    f'"{sys.executable}" "{script}" %*',
                ]
            ),
            encoding="utf-8",
        )
    else:
        command.write_text(
            "\n".join(
                [
                    "#!/bin/sh",
                    f"export FAKE_HERMES_CAPTURE={shlex.quote(str(capture_path))}",
                    f"exec {shlex.quote(sys.executable)} {shlex.quote(str(script))} \"$@\"",
                ]
            ),
            encoding="utf-8",
        )
        command.chmod(0o755)
    return command


def _fake_hermes_invalid_utf8_command(root: Path) -> Path:
    script = root / "fake_hermes_invalid_utf8.py"
    command = root / (
        "fake_hermes_invalid_utf8.cmd"
        if os.name == "nt"
        else "fake_hermes_invalid_utf8"
    )
    script.write_text(
        "\n".join(
            [
                "import sys",
                "if sys.argv[1:] in (['--version'], ['--help']):",
                "    print('Hermes Agent v9.8.7')",
                "    raise SystemExit(0)",
                "sys.stdout.buffer.write(b'\\xff\\xfe\\xfa')",
                "sys.stderr.buffer.write('错误'.encode('utf-8'))",
                "raise SystemExit(7)",
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
        workspace_id="workspace-hermes",
        display_name="Hermes Workspace",
        root_path="X:/fixture/beacon-project",
        agent_id="agent-a",
        agent_name="Agent A",
        agent_description="Source agent.",
    )
    service.create_agent_registration(
        "workspace-hermes",
        agent_id="agent-b",
        name="Agent B",
        description="Hermes target agent.",
    )
    service.create_agent_exchange_request(
        "workspace-hermes",
        exchange_request_id="req-hermes-1",
        source_agent_id="agent-a",
        target_agent_id="agent-b",
        request_kind="review",
        request_summary="Please review the Hermes resume path.",
    )


def _hermes_activation_event_count(connection: sqlite3.Connection) -> int:
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM platform_events WHERE event_kind = ?",
            ("hermes_registered_session_activation.recorded",),
        ).fetchone()[0]
    )


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
