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

from agent_os.application.services.claude_registered_session import (
    ClaudeRegisteredSessionActivationAttempt,
    ClaudeRegisteredSessionActivationStatus,
    ClaudeRegisteredSessionHandle,
    extract_claude_stream_json_response,
    render_claude_resume_argv,
    resolve_claude_executable,
    truncate_auto_captured_response,
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


class ClaudeRegisteredSessionContractTests(unittest.TestCase):
    def test_handle_accepts_claude_uuid_but_rejects_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            handle = ClaudeRegisteredSessionHandle.from_mapping(
                {
                    "workspaceId": "workspace-claude",
                    "agentId": "agent-b",
                    "handleId": "handle-1",
                    "claudeSessionUuid": str(uuid4()),
                    "cwd": directory,
                    "createdBy": "user",
                    "reason": "explicit registration",
                }
            )

            self.assertEqual(handle.provider, "claude-code")
            self.assertFalse(handle.to_metadata()["credentialStored"])

            with self.assertRaisesRegex(ValueError, "credential"):
                ClaudeRegisteredSessionHandle.from_mapping(
                    {
                        "workspaceId": "workspace-claude",
                        "agentId": "agent-b",
                        "handleId": "handle-2",
                        "claudeSessionUuid": str(uuid4()),
                        "cwd": directory,
                        "createdBy": "user",
                        "reason": "explicit registration",
                        "metadata": {"token": "secret"},
                    }
                )

    def test_rendered_resume_argv_uses_official_resume_without_forbidden_flags(self) -> None:
        session_uuid = str(uuid4())
        argv = render_claude_resume_argv(session_uuid, claude_executable="claude")

        self.assertEqual(
            argv,
            (
                "claude",
                "--resume",
                session_uuid,
                "--print",
                "--output-format",
                "stream-json",
                "--verbose",
            ),
        )
        self.assertNotIn("--fork-session", argv)
        self.assertNotIn("--no-session-persistence", argv)
        self.assertNotIn("--remote-control", argv)
        self.assertNotIn("--tmux", argv)

    def test_rendered_resume_argv_accepts_scoped_permission_options(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session_uuid = str(uuid4())
            settings_path = root / "claude-settings.json"
            settings_path.write_text("{}", encoding="utf-8")

            argv = render_claude_resume_argv(
                session_uuid,
                claude_executable="claude",
                add_dirs=(str(root),),
                allowed_tools=("Bash", "Write"),
                permission_mode="acceptEdits",
                settings_path=str(settings_path),
            )

            self.assertIn("--add-dir", argv)
            self.assertIn(str(root), argv)
            self.assertIn("--allowedTools", argv)
            self.assertIn("Bash", argv)
            self.assertIn("Write", argv)
            self.assertIn("--permission-mode", argv)
            self.assertIn("acceptEdits", argv)
            self.assertIn("--settings", argv)
            self.assertIn(str(settings_path), argv)

            with self.assertRaisesRegex(ValueError, "bypass"):
                render_claude_resume_argv(
                    session_uuid,
                    claude_executable="claude",
                    permission_mode="bypassPermissions",
                )

    def test_activation_metadata_marks_explicit_permission_profile_source(self) -> None:
        attempt = ClaudeRegisteredSessionActivationAttempt(
            workspace_id="workspace-claude",
            agent_id="agent-b",
            handle_id="claude-handle-1",
            exchange_request_id="req-claude-1",
            thread_id="req-claude-1",
            wake_ticket_id="wake-ticket-1",
            status=ClaudeRegisteredSessionActivationStatus.DRY_RUN,
            add_dir_paths=("X:/fixture/beacon-project",),
            allowed_tools=("Bash",),
            permission_mode="acceptEdits",
        )

        metadata = attempt.to_metadata()
        profile = metadata["providerPermissionProfile"]

        self.assertTrue(profile["selected"])
        self.assertEqual(profile["selectionSource"], "explicit_activation_arguments")
        self.assertTrue(profile["permissionPostureChangingArgsInjected"])
        self.assertEqual(
            metadata["permissionStandardization"][
                "providerPermissionProfileSelectionSource"
            ],
            "explicit_activation_arguments",
        )

    def test_extracts_claude_stream_json_response_text(self) -> None:
        stdout = "\n".join(
            [
                json.dumps({"type": "system", "subtype": "init"}),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "intermediate response",
                                }
                            ],
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "result",
                        "session_id": str(uuid4()),
                        "result": "final captured response",
                    }
                ),
            ]
        )

        self.assertEqual(
            extract_claude_stream_json_response(stdout),
            "final captured response",
        )
        self.assertEqual(
            truncate_auto_captured_response("abcdef", max_chars=3),
            "abc",
        )

    def test_resolves_default_claude_executable_through_runtime_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = _fake_version_command(root, "claude", "claude 9.8.7")

            with mock.patch.dict(os.environ, {"PATH": str(root)}, clear=False):
                resolution = resolve_claude_executable("claude")

            self.assertEqual(resolution.requested_executable, "claude")
            self.assertEqual(resolution.resolved_executable, str(executable))
            self.assertEqual(resolution.resolution_source, "agent_runtime_preflight")


class ClaudeRegisteredSessionOperationTests(unittest.TestCase):
    def test_dry_run_renders_ticket_and_command_without_provider_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_uuid = str(uuid4())
            service.register_claude_session_handle(
                "workspace-claude",
                agent_id="agent-b",
                handle_id="claude-handle-1",
                claude_session_uuid=session_uuid,
                cwd=directory,
                created_by="user",
                reason="explicit registration",
            )

            result = service.activate_claude_registered_session(
                "workspace-claude",
                agent_id="agent-b",
                handle_id="claude-handle-1",
                exchange_request_id="req-claude-1",
                database_path=str(Path(directory) / "platform.sqlite3"),
                workspace_root=str(Path(directory) / "workspace"),
                plugins_directory=str(Path(directory) / "plugins"),
                handoff_directory=str(Path(directory) / "handoff"),
                dry_run=True,
            )
            activation = result["claudeRegisteredSessionActivation"]
            argv = " ".join(activation["commandArgvSummary"])

            self.assertEqual(activation["status"], "dry_run")
            self.assertFalse(activation["providerCommandStarted"])
            self.assertIn("--resume", activation["commandArgvSummary"])
            self.assertIn(session_uuid, activation["commandArgvSummary"])
            self.assertIn("--add-dir", activation["commandArgvSummary"])
            self.assertIn(str(root.resolve()), activation["commandArgvSummary"])
            self.assertNotIn("--allowedTools", activation["commandArgvSummary"])
            self.assertNotIn("--permission-mode", activation["commandArgvSummary"])
            self.assertNotIn("Please review the Claude resume path", argv)
            self.assertIn("Read the wake ticket JSON at:", result["stdinPreview"])
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
            self.assertEqual(_activation_event_count(connection), 1)
            self.assertEqual(_wake_event_count(connection), 0)

    def test_execute_uses_fake_claude_fixture_and_records_activation_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_uuid = str(uuid4())
            capture_path = root / "capture.json"
            fake_claude = _fake_claude_command(root, session_uuid, capture_path)
            service.register_claude_session_handle(
                "workspace-claude",
                agent_id="agent-b",
                handle_id="claude-handle-1",
                claude_session_uuid=session_uuid,
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )

            result = service.activate_claude_registered_session(
                "workspace-claude",
                agent_id="agent-b",
                handle_id="claude-handle-1",
                exchange_request_id="req-claude-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                claude_executable=str(fake_claude),
                dry_run=False,
            )
            activation = result["claudeRegisteredSessionActivation"]
            capture = json.loads(capture_path.read_text(encoding="utf-8"))
            status = service.get_agent_wake_status(
                "workspace-claude",
                exchange_request_id="req-claude-1",
            )["agentWakeStatus"]

            self.assertEqual(activation["status"], "delivered")
            self.assertEqual(activation["commandExitCode"], 0)
            self.assertTrue(activation["providerCommandStarted"])
            self.assertTrue(activation["sessionContinuityVerified"])
            self.assertFalse(activation["targetResponseCompleted"])
            self.assertEqual(capture["argv"][0], "--resume")
            self.assertEqual(capture["argv"][1], session_uuid)
            self.assertIn("Read the wake ticket JSON at:", capture["stdin"])
            self.assertNotIn("Please review the Claude resume path", " ".join(capture["argv"]))
            self.assertTrue(Path(result["ticket"]["wakeTicketId"]))
            self.assertTrue(status["ticketDeliveryOccurred"])
            self.assertTrue(status["providerCommandStarted"])
            self.assertTrue(status["runtimeWakeTriggered"])
            self.assertFalse(status["targetResponseCompleted"])
            self.assertEqual(_activation_event_count(connection), 1)
            self.assertEqual(_wake_event_count(connection), 1)
            service.respond_agent_exchange_request(
                "workspace-claude",
                exchange_request_id="req-claude-1",
                responding_agent_id="agent-b",
                response_summary="Reviewed from registered Claude session.",
            )
            responded_status = service.get_agent_wake_status(
                "workspace-claude",
                exchange_request_id="req-claude-1",
            )["agentWakeStatus"]

            self.assertTrue(responded_status["targetResponseCompleted"])

            skipped = service.activate_claude_registered_session(
                "workspace-claude",
                agent_id="agent-b",
                handle_id="claude-handle-1",
                exchange_request_id="req-claude-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                claude_executable=str(fake_claude),
                dry_run=False,
            )["claudeRegisteredSessionActivation"]

            self.assertEqual(skipped["status"], "skipped")
            self.assertEqual(skipped["skipReason"], "already_started_for_request_and_handle")

    def test_execute_auto_captures_claude_stdout_as_request_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_uuid = str(uuid4())
            capture_path = root / "capture.json"
            response_text = "received smoke ticket from Claude registered session."
            fake_claude = _fake_claude_command(
                root,
                session_uuid,
                capture_path,
                result_text=response_text,
            )
            service.register_claude_session_handle(
                "workspace-claude",
                agent_id="agent-b",
                handle_id="claude-handle-1",
                claude_session_uuid=session_uuid,
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )

            result = service.activate_claude_registered_session(
                "workspace-claude",
                agent_id="agent-b",
                handle_id="claude-handle-1",
                exchange_request_id="req-claude-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                claude_executable=str(fake_claude),
                dry_run=False,
            )
            activation = result["claudeRegisteredSessionActivation"]
            request = service.get_agent_exchange_request_status(
                "workspace-claude",
                exchange_request_id="req-claude-1",
            )["agentExchangeRequest"]
            status = service.get_agent_wake_status(
                "workspace-claude",
                exchange_request_id="req-claude-1",
            )["agentWakeStatus"]

            self.assertEqual(activation["status"], "delivered")
            self.assertTrue(activation["targetResponseCompleted"])
            self.assertEqual(
                activation["responseCaptureMode"],
                "claude_stdout_stream_json",
            )
            self.assertEqual(activation["responseCaptureStatus"], "recorded")
            self.assertIn("autoCapturedResponseSourceEventSequence", activation)
            self.assertEqual(request["terminalReason"], "responded")
            self.assertEqual(request["respondedByAgentId"], "agent-b")
            self.assertEqual(request["responseSummary"], response_text)
            self.assertEqual(
                request["metadata"]["responseSource"],
                "claude_stdout_auto_capture",
            )
            self.assertTrue(status["targetResponseCompleted"])

    def test_ticket_write_failure_records_activation_failure_without_provider_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_uuid = str(uuid4())
            blocked_handoff = root / "not-a-directory"
            blocked_handoff.write_text("file blocks directory creation", encoding="utf-8")
            service.register_claude_session_handle(
                "workspace-claude",
                agent_id="agent-b",
                handle_id="claude-handle-1",
                claude_session_uuid=session_uuid,
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )

            result = service.activate_claude_registered_session(
                "workspace-claude",
                agent_id="agent-b",
                handle_id="claude-handle-1",
                exchange_request_id="req-claude-1",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(blocked_handoff),
                claude_executable=str(root / "missing-claude.cmd"),
                dry_run=False,
            )
            activation = result["claudeRegisteredSessionActivation"]

            self.assertEqual(activation["status"], "failed")
            self.assertFalse(activation["providerCommandStarted"])
            self.assertIn("FileExistsError", activation["failureReason"])
            self.assertEqual(_activation_event_count(connection), 1)
            self.assertEqual(_wake_event_count(connection), 0)

    def test_local_runtime_cli_registers_lists_and_dry_runs_handle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session_uuid = str(uuid4())
            created = _run_cli(
                root,
                "workspace-create",
                "--workspace-id",
                "workspace-cli-claude",
                "--agent-id",
                "agent-a",
                "--display-name",
                "CLI Claude Workspace",
                "--root-path",
                str(root),
            )
            agent = _run_cli(
                root,
                "agent-create",
                "--workspace-id",
                "workspace-cli-claude",
                "--agent-id",
                "agent-b",
                "--name",
                "Agent B",
                "--description",
                "Claude target.",
            )
            request = _run_cli(
                root,
                "agent-exchange-request-create",
                "--workspace-id",
                "workspace-cli-claude",
                "--exchange-request-id",
                "req-cli-claude",
                "--source-agent-id",
                "agent-a",
                "--target-agent-id",
                "agent-b",
                "--request-kind",
                "review",
                "--request-summary",
                "Please review via registered Claude session.",
            )
            registered = _run_cli(
                root,
                "claude-session-handle-register",
                "--workspace-id",
                "workspace-cli-claude",
                "--agent-id",
                "agent-b",
                "--handle-id",
                "handle-cli-claude",
                "--claude-session-uuid",
                session_uuid,
                "--cwd",
                str(root),
                "--created-by",
                "user",
                "--reason",
                "explicit CLI registration",
            )
            listed = _run_cli(
                root,
                "claude-session-handle-list",
                "--workspace-id",
                "workspace-cli-claude",
                "--agent-id",
                "agent-b",
            )
            activated = _run_cli(
                root,
                "claude-registered-session-activate",
                "--workspace-id",
                "workspace-cli-claude",
                "--agent-id",
                "agent-b",
                "--handle-id",
                "handle-cli-claude",
                "--exchange-request-id",
                "req-cli-claude",
                "--handoff-directory",
                str(root / "handoff"),
                "--dry-run",
            )

            for result in (created, agent, request, registered, listed, activated):
                self.assertEqual(result.returncode, 0, result.stderr)

            registered_payload = json.loads(registered.stdout)
            listed_payload = json.loads(listed.stdout)
            activated_payload = json.loads(activated.stdout)
            activation = activated_payload["claudeRegisteredSessionActivation"]

            self.assertEqual(
                registered_payload["claudeSessionHandle"]["claudeSessionUuid"],
                session_uuid,
            )
            self.assertEqual(len(listed_payload["claudeSessionHandles"]), 1)
            self.assertEqual(activation["status"], "dry_run")
            self.assertFalse(activation["providerCommandStarted"])
            self.assertIn("--add-dir", activation["commandArgvSummary"])
            self.assertEqual(activation["platformWorkspaceRoot"], str(root.resolve()))
            self.assertTrue(
                activation["permissionStandardization"][
                    "defaultPlatformWorkspaceAddDir"
                ]
            )
            self.assertFalse(activation["providerPermissionProfile"]["selected"])


def _fake_claude_command(
    root: Path,
    session_uuid: str,
    capture_path: Path,
    *,
    result_text: str | None = None,
) -> Path:
    script = root / "fake_claude.py"
    command = root / ("fake_claude.cmd" if os.name == "nt" else "fake_claude")
    result_literal = repr(result_text)
    script.write_text(
        "\n".join(
            [
                "import json, os, pathlib, sys",
                f"RESULT_TEXT = {result_literal}",
                "stdin = sys.stdin.read()",
                "path = pathlib.Path(os.environ['FAKE_CLAUDE_CAPTURE'])",
                "path.write_text(json.dumps({",
                "  'argv': sys.argv[1:],",
                "  'cwd': os.getcwd(),",
                "  'stdin': stdin,",
                "}, sort_keys=True), encoding='utf-8')",
                "if RESULT_TEXT:",
                "    print(json.dumps({",
                "        'type': 'assistant',",
                "        'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': RESULT_TEXT}]},",
                f"        'session_id': '{session_uuid}',",
                "    }))",
                "    print(json.dumps({",
                "        'type': 'result',",
                f"        'session_id': '{session_uuid}',",
                "        'result': RESULT_TEXT,",
                "    }))",
                "else:",
                f"    print(json.dumps({{'type': 'result', 'session_id': '{session_uuid}'}}))",
            ]
        ),
        encoding="utf-8",
    )
    if os.name == "nt":
        command.write_text(
            "\n".join(
                [
                    "@echo off",
                    f"set FAKE_CLAUDE_CAPTURE={capture_path}",
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
                    f"export FAKE_CLAUDE_CAPTURE={shlex.quote(str(capture_path))}",
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
        workspace_id="workspace-claude",
        display_name="Claude Workspace",
        root_path="X:/fixture/beacon-project",
        agent_id="agent-a",
        agent_name="Agent A",
        agent_description="Source agent.",
    )
    service.create_agent_registration(
        "workspace-claude",
        agent_id="agent-b",
        name="Agent B",
        description="Claude target agent.",
    )
    service.create_agent_exchange_request(
        "workspace-claude",
        exchange_request_id="req-claude-1",
        source_agent_id="agent-a",
        target_agent_id="agent-b",
        request_kind="review",
        request_summary="Please review the Claude resume path.",
    )


def _activation_event_count(connection: sqlite3.Connection) -> int:
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM platform_events WHERE event_kind = ?",
            ("claude_registered_session_activation.recorded",),
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
