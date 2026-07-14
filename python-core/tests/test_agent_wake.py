from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.agent_wake import AgentWakeProfile
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


class AgentWakeContractTests(unittest.TestCase):
    def test_profile_rejects_agent_free_text_placeholders_in_command_argv(self) -> None:
        with self.assertRaisesRegex(ValueError, "platform-generated safe values"):
            AgentWakeProfile.from_mapping(
                {
                    "workspaceId": "workspace-wake",
                    "agentId": "agent-b",
                    "wakeMode": "command",
                    "commandArgv": ["tool", "{request_summary}"],
                }
            )


class AgentWakeOperationTests(unittest.TestCase):
    def test_dry_run_builds_directly_readable_ticket_without_audit_marker(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_wake_workspace(service)

        result = service.run_agent_wake_once(
            "workspace-wake",
            agent_id="agent-b",
            profile={"wakeMode": "notify_only"},
            database_path="X:/fixture/beacon-project/.smoke/wake.sqlite",
            workspace_root="X:/fixture/beacon-project",
            plugins_directory="X:/fixture/beacon-project/.smoke/plugins",
            dry_run=True,
        )["agentWakeRun"]
        events = _wake_event_count(connection)

        self.assertEqual(result["pendingRequestCount"], 1)
        self.assertEqual(result["attempts"][0]["status"], "dry_run")
        ticket = result["attempts"][0]["ticket"]
        self.assertEqual(ticket["schema"], "agent_wake_ticket.v2")
        self.assertEqual(ticket["exchangeRequestId"], "req-wake-1")
        self.assertEqual(ticket["threadId"], "req-wake-1")
        self.assertEqual(ticket["requestSummary"], "Please review the wake path.")
        self.assertEqual(
            ticket["localRuntimeHints"]["runtimeConfigSource"],
            "explicit_args",
        )
        action = ticket["recommendedAction"]
        self.assertEqual(action["schema"], "agent_wake_action.v1")
        self.assertIn("inspectArgv", action)
        self.assertIn("respondArgvTemplate", action)
        self.assertIn("PYTHONPATH", action["runtimeEnvironment"])
        self.assertNotIn("recommendedCli", ticket)
        self.assertNotIn("requestGet", action)
        self.assertNotIn("threadGet", action)
        self.assertFalse(ticket["realRuntimeConnected"])
        self.assertFalse(ticket["providerPromptInjected"])
        self.assertFalse(ticket["fileBodiesRead"])
        self.assertEqual(events, 0)

    def test_handoff_file_records_ticket_and_skips_duplicate_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_wake_workspace(service)
            handoff_dir = Path(directory) / "handoff files"

            first = service.run_agent_wake_once(
                "workspace-wake",
                agent_id="agent-b",
                profile={
                    "wakeMode": "handoff_file",
                    "handoffDirectory": str(handoff_dir),
                },
                database_path=str(Path(directory) / "platform.sqlite3"),
                workspace_root=str(Path(directory) / "workspace root"),
                plugins_directory=str(Path(directory) / "plugins"),
            )["agentWakeRun"]
            ticket_path = Path(first["attempts"][0]["ticketPath"])
            ticket = json.loads(ticket_path.read_text(encoding="utf-8"))
            second = service.run_agent_wake_once(
                "workspace-wake",
                agent_id="agent-b",
                profile={
                    "wakeMode": "handoff_file",
                    "handoffDirectory": str(handoff_dir),
                },
                database_path=str(Path(directory) / "platform.sqlite3"),
                workspace_root=str(Path(directory) / "workspace root"),
                plugins_directory=str(Path(directory) / "plugins"),
            )["agentWakeRun"]

            self.assertEqual(first["deliveredCount"], 1)
            self.assertTrue(ticket_path.exists())
            self.assertEqual(ticket["exchangeRequestId"], "req-wake-1")
            self.assertEqual(ticket["targetAgentId"], "agent-b")
            inspect_argv = ticket["recommendedAction"]["inspectArgv"]
            workspace_root_index = inspect_argv.index("--workspace-root")
            self.assertIn("workspace root", inspect_argv[workspace_root_index + 1])
            self.assertEqual(_wake_event_count(connection), 2)
            self.assertEqual(second["deliveredCount"], 0)
            self.assertEqual(second["skippedCount"], 1)
            self.assertEqual(
                second["attempts"][0]["skipReason"],
                "already_delivered_or_leased",
            )
            self.assertEqual(_wake_event_count(connection), 2)

            deliveries = service.list_agent_wake_deliveries(
                "workspace-wake",
                agent_id="agent-b",
                exchange_request_id="req-wake-1",
            )["agentWakeDeliveries"]
            status = service.get_agent_wake_status(
                "workspace-wake",
                exchange_request_id="req-wake-1",
            )["agentWakeStatus"]
            ticket_read = service.get_agent_wake_ticket(
                "workspace-wake",
                exchange_request_id="req-wake-1",
            )["agentWakeTicket"]
            request_status = service.get_agent_exchange_request_status(
                "workspace-wake",
                exchange_request_id="req-wake-1",
            )["agentExchangeRequest"]

            self.assertEqual(len(deliveries), 2)
            self.assertEqual(deliveries[0]["delivery"]["status"], "delivered")
            self.assertTrue(status["ticketDeliveryOccurred"])
            self.assertFalse(status["realRuntimeConnected"])
            self.assertIn("does not mean ticket delivery failed", status["realRuntimeControlMeaning"])
            self.assertEqual(ticket_read["exchangeRequestId"], "req-wake-1")
            self.assertEqual(ticket_read["delivery"]["ticketPath"], str(ticket_path))
            self.assertTrue(
                request_status["wakeDeliverySummary"]["ticketDeliveryOccurred"]
            )
            self.assertFalse(request_status["wakeDeliverySummary"]["runtimeWakeTriggered"])

    def test_command_mode_starts_dummy_fixture_with_ticket_path_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_wake_workspace(service)
            script = Path(directory) / "dummy_responder.py"
            output = Path(directory) / "dummy-output.json"
            script.write_text(
                "\n".join(
                    [
                        "import json, pathlib, sys",
                        "ticket_path = pathlib.Path(sys.argv[1])",
                        "output_path = pathlib.Path(sys.argv[2])",
                        "ticket = json.loads(ticket_path.read_text(encoding='utf-8'))",
                        "output_path.write_text(json.dumps({",
                        "  'ticketPath': str(ticket_path),",
                        "  'exchangeRequestId': ticket['exchangeRequestId'],",
                        "  'threadId': ticket['threadId'],",
                        "}, sort_keys=True), encoding='utf-8')",
                    ]
                ),
                encoding="utf-8",
            )

            result = service.run_agent_wake_once(
                "workspace-wake",
                agent_id="agent-b",
                profile={
                    "wakeMode": "command",
                    "handoffDirectory": str(Path(directory) / "handoffs"),
                    "commandArgv": [
                        sys.executable,
                        str(script),
                        "{ticket_path}",
                        str(output),
                    ],
                    "childProcessPolicy": "wait",
                },
                database_path=str(Path(directory) / "platform.sqlite3"),
                workspace_root=str(Path(directory) / "workspace"),
                plugins_directory=str(Path(directory) / "plugins"),
            )["agentWakeRun"]
            dummy_output = json.loads(output.read_text(encoding="utf-8"))
            attempt = result["attempts"][0]
            argv_summary = " ".join(attempt["commandArgvSummary"])

            self.assertEqual(result["deliveredCount"], 1)
            self.assertEqual(attempt["status"], "delivered")
            self.assertEqual(attempt["commandExitCode"], 0)
            self.assertEqual(dummy_output["exchangeRequestId"], "req-wake-1")
            self.assertEqual(dummy_output["threadId"], "req-wake-1")
            self.assertTrue(Path(dummy_output["ticketPath"]).exists())
            self.assertNotIn("Please review the wake path", argv_summary)

    def test_terminal_request_is_not_woken(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_wake_workspace(service)
        service.respond_agent_exchange_request(
            "workspace-wake",
            exchange_request_id="req-wake-1",
            responding_agent_id="agent-b",
            response_summary="Reviewed.",
        )

        result = service.run_agent_wake_once(
            "workspace-wake",
            agent_id="agent-b",
            profile={"wakeMode": "notify_only"},
            database_path="X:/fixture/wake.sqlite",
            workspace_root="X:/fixture/workspace",
            plugins_directory="X:/fixture/plugins",
        )["agentWakeRun"]

        self.assertEqual(result["pendingRequestCount"], 0)
        self.assertEqual(result["attempts"], [])
        self.assertEqual(_wake_event_count(connection), 0)

    def test_crash_after_lease_marker_does_not_duplicate_on_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_wake_workspace(service)

            with self.assertRaisesRegex(RuntimeError, "simulated crash"):
                service.run_agent_wake_once(
                    "workspace-wake",
                    agent_id="agent-b",
                    profile={
                        "wakeMode": "handoff_file",
                        "handoffDirectory": str(Path(directory) / "handoffs"),
                    },
                    database_path=str(Path(directory) / "platform.sqlite3"),
                    workspace_root=str(Path(directory) / "workspace"),
                    plugins_directory=str(Path(directory) / "plugins"),
                    occurred_at=datetime(2026, 6, 21, 8, 0, tzinfo=timezone.utc),
                    simulate_crash_after_marker=True,
                )
            restarted = service.run_agent_wake_once(
                "workspace-wake",
                agent_id="agent-b",
                profile={
                    "wakeMode": "handoff_file",
                    "handoffDirectory": str(Path(directory) / "handoffs"),
                },
                database_path=str(Path(directory) / "platform.sqlite3"),
                workspace_root=str(Path(directory) / "workspace"),
                plugins_directory=str(Path(directory) / "plugins"),
            )["agentWakeRun"]

            self.assertEqual(_wake_event_count(connection), 1)
            self.assertEqual(restarted["deliveredCount"], 0)
            self.assertEqual(restarted["skippedCount"], 1)
            self.assertEqual(
                restarted["attempts"][0]["skipReason"],
                "already_delivered_or_leased",
            )


def _seed_wake_workspace(service: LocalPlatformOperationService) -> None:
    service.create_workspace(
        workspace_id="workspace-wake",
        display_name="Wake Workspace",
        root_path="X:/fixture/beacon-project",
        agent_id="agent-a",
        agent_name="Agent A",
        agent_description="Source agent.",
    )
    service.create_agent_registration(
        "workspace-wake",
        agent_id="agent-b",
        name="Agent B",
        description="Target agent.",
    )
    service.create_agent_exchange_request(
        "workspace-wake",
        exchange_request_id="req-wake-1",
        source_agent_id="agent-a",
        target_agent_id="agent-b",
        request_kind="review",
        request_summary="Please review the wake path.",
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
