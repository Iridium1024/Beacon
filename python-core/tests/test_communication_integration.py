"""Real CLI subprocesses against synthetic SQLite; no provider or user profile."""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

from agent_os.application.services.local_platform_application import LocalPlatformApplication
from agent_os.application.services.communication_migration import CommunicationMigration
from agent_os.application.services.communication_core import CommunicationService
from agent_os.application.services.communication_compatibility import LegacyExchangeSendCompatibility
from agent_os.application.services.communication_provider_scope import CoreProviderScope, core_provider_scope
from agent_os.application.services.communication_provider_adapter import CoreProviderAdapter
from agent_os.domain.entities.communication import Caller, Claim, ProviderEvidence
from agent_os.domain.value_objects.identifiers import WorkspaceId
from agent_os.infrastructure.composition.local_platform import build_communication_directory as PlatformCommunicationDirectory
from agent_os.infrastructure.composition.local_platform import build_local_platform_operation_service
from agent_os.application.services.local_platform_operations import LocalPlatformOperationService
from agent_os.application.services.hermes_tui_gateway_backend import (
    HermesTuiGatewayRunResult, HermesTuiGatewayRuntime,
)
from agent_os.infrastructure.persistence.sqlite_persistence import SqlitePlatformPersistence
from agent_os.infrastructure.persistence.communication_store import SqliteCommunicationRepository
from agent_os.infrastructure.config import LocalPlatformSettings
from test_codex_registered_session_activation import _fake_codex_command, _fake_codex_app_server_command
from test_claude_registered_session_activation import _fake_claude_command
from test_claude_registered_session_activation import _sdk_runtime, _sdk_result
from test_hermes_registered_session_activation import _fake_hermes_command


SRC = Path(__file__).resolve().parents[1] / "src"


class CommunicationCliIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="beacon cli 中文 ")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.path = root / "platform.sqlite3"
        self.profile = root / "agent os profile.json"
        self.profile.write_text(json.dumps({"localRuntime": {
            "workspaceId": "w", "databasePath": str(self.path),
            "workspaceRoot": str(root / "workspace root"),
            "pluginsDirectory": str(root / "plugins directory")}}), encoding="utf-8")
        self.connection = sqlite3.connect(self.path)
        self.addCleanup(self.connection.close)
        SqlitePlatformPersistence(self.connection).initialize()
        self.platform = build_local_platform_operation_service(self.connection)
        self.platform.create_workspace(workspace_id="w", display_name="Synthetic", root_path=self.temp.name,
            agent_id="a", agent_name="A", agent_description="fixture")
        for agent in ("b", "c"):
            self.platform.create_agent_registration("w", agent_id=agent, name=agent, description="fixture")
        self.platform.register_codex_session_handle("w", agent_id="b", handle_id="h-b",
            codex_session_id=str(uuid4()), cwd=self.temp.name, created_by="fixture", reason="fixture")
        self.platform.login_agent_endpoint("w", agent_id="b", alias="b", provider="codex",
                                           provider_handle_id="h-b")

    def cli(self, *args: str, success=True):
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC"}}
        env.update(PYTHONPATH=str(SRC), PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        result = subprocess.run([sys.executable, "-B", "-m", "agent_os.local_runtime",
            "--profile", str(self.profile), *args], cwd=self.temp.name, env=env,
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
            timeout=30)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        return json.loads(result.stderr)

    def migrate_request(self):
        created = self.platform.create_agent_exchange_request("w", source_agent_id="a",
            target_agent_id="b", request_kind="question", request_summary="请核对这条合成消息")
        old_id = created["agentExchangeRequest"]["exchangeRequestId"]
        migration = CommunicationMigration(self.connection, directory=PlatformCommunicationDirectory(self.connection))
        migration.migrate("w", operator="fixture", stopped_writers_confirmed=True)
        return old_id, migration.legacy_message_id("w", kind="request", legacy_id=old_id)

    def test_explicit_cli_migration_previews_backs_up_and_cuts_over_synthetic_workspace(self):
        created = self.platform.create_agent_exchange_request("w", source_agent_id="a",
            target_agent_id="b", request_kind="question", request_summary="CLI migration fixture")
        old_id = created["agentExchangeRequest"]["exchangeRequestId"]
        preview = self.cli("communication-migrate-preview", "--workspace-id", "w")
        self.assertEqual(preview["engine"], "legacy")
        self.assertEqual(preview["request_count"], 1)
        self.assertFalse(self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='communication_schema'").fetchone())
        backup_path = Path(self.temp.name) / "before-cutover.sqlite3"
        migrated = self.cli("communication-migrate", "--workspace-id", "w",
            "--operator", "fixture", "--backup-path", str(backup_path),
            "--confirm-stopped-writers")
        self.assertTrue(migrated["migration"]["created"])
        self.assertEqual(migrated["postMigrationPreview"]["engine"], "core")
        self.assertTrue(Path(migrated["backup"]["path"]).samefile(backup_path))
        with closing(sqlite3.connect(backup_path)) as backup:
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0],
                             self.connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0])
            self.assertFalse(backup.execute(
                "SELECT 1 FROM sqlite_master WHERE name='communication_schema'").fetchone())
        self.assertEqual(self.cli("agent-exchange-request-get", "--workspace-id", "w",
            "--exchange-request-id", old_id, "--agent-id", "b")
            ["agentExchangeRequest"]["requestSummary"], "CLI migration fixture")

    def test_legacy_workspace_new_commands_fail_without_schema_creation(self):
        error = self.cli("agent-message-inbox", "--workspace-id", "w", "--agent-id", "b", success=False)
        self.assertIn("not explicitly switched", error["error"]["message"])
        self.assertFalse(self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='communication_schema'").fetchone())

    def test_cross_process_inbox_ack_progress_and_legacy_final(self):
        old_id, message_id = self.migrate_request()
        received = self.cli("agent-message-inbox", "--workspace-id", "w", "--agent-id", "b")
        self.assertEqual(received["engine"], "core")
        self.assertEqual(received["items"][0]["message_id"], message_id)
        self.assertNotIn("body", received["items"][0])
        full = self.cli("agent-message-get", "--workspace-id", "w", "--agent-id", "b",
                        "--message-id", old_id)
        self.assertEqual(full["message"]["body"], "请核对这条合成消息")
        old_get = self.cli("agent-exchange-request-get", "--workspace-id", "w",
            "--exchange-request-id", old_id, "--agent-id", "b")
        self.assertEqual(old_get["agentExchangeRequest"]["messageId"], message_id)
        compact = self.cli("agent-exchange-status", "--workspace-id", "w",
            "--exchange-request-id", old_id, "--agent-id", "a", "--format", "compact")
        self.assertEqual(compact["schema"], "agent_exchange_compact_status.core.v1")
        self.assertEqual(compact["sourceEventSequence"], None)
        bad = self.cli("agent-message-ack", "--workspace-id", "w", "--agent-id", "c",
                       "--message-id", old_id, success=False)
        self.assertIn("intended recipient", bad["error"]["message"])
        ack = self.cli("agent-message-ack", "--workspace-id", "w", "--agent-id", "b",
                       "--message-id", old_id, "--idempotency-key", "ack-1")
        same = self.cli("agent-message-ack", "--workspace-id", "w", "--agent-id", "b",
                        "--message-id", old_id, "--idempotency-key", "ack-1")
        self.assertEqual(ack["receipt"]["id"], same["receipt"]["id"])
        progress = self.cli("agent-message-reply", "--workspace-id", "w", "--agent-id", "b",
                            "--message-id", old_id, "--message", "正在处理", "--kind", "progress")
        self.assertEqual(progress["receipt"]["kind"], "progress")
        status = self.cli("agent-message-status", "--workspace-id", "w", "--agent-id", "a",
                          "--message-id", old_id)
        self.assertTrue(status["acknowledged"])
        self.assertEqual(status["reply"], "none")
        final = self.cli("agent-reply", "--workspace-id", "w", "--request", old_id,
                         "--agent", "b", "--message", "处理完成", "--idempotency-key", "final-1")
        self.assertEqual(final["engine"], "core")
        self.assertEqual(final["agentExchangeRequest"]["messageId"], message_id)
        self.assertIsNone(final["sourceEventSequence"])
        self.assertGreater(final["communicationLedgerSequence"], 0)
        again = self.cli("agent-reply", "--workspace-id", "w", "--request", old_id,
                         "--agent", "b", "--message", "处理完成", "--idempotency-key", "final-1")
        self.assertEqual(again["communicationLedgerSequence"], final["communicationLedgerSequence"])
        duplicate = self.cli("agent-reply", "--workspace-id", "w", "--request", old_id,
                             "--agent", "b", "--message", "处理完成", success=False)
        self.assertIn("terminal reply", duplicate["error"]["message"])
        wrong = self.cli("agent-reply", "--workspace-id", "w", "--request", old_id,
                         "--agent", "c", "--message", "wrong", success=False)
        self.assertIn("intended recipient", wrong["error"]["message"])
        first_page = self.cli("agent-message-inbox", "--workspace-id", "w", "--agent-id", "a",
                              "--limit", "1", "--include-bodies")
        self.assertTrue(first_page["has_more"])
        second_page = self.cli("agent-message-inbox", "--workspace-id", "w", "--agent-id", "a",
                               "--cursor", first_page["cursor"], "--limit", "10", "--include-bodies")
        self.assertEqual([item["kind"] for item in first_page["items"] + second_page["items"]],
                         ["ack", "progress", "final"])
        self.assertEqual(second_page["items"][-1]["body"], "处理完成")
        app = LocalPlatformApplication(LocalPlatformSettings(database=str(self.path),
            workspace_root=self.temp.name, plugins_directory=self.temp.name,
            profile_path=str(self.profile)))
        communication = app.get_console_workspace_view(workspace_id="w")["communicationLedger"]
        self.assertEqual([kind for event in communication["events"]
            for kind in event["receiptKinds"]], ["ack", "progress", "final"])
        self.assertNotIn("处理完成", json.dumps(communication, ensure_ascii=False))
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM platform_events WHERE workspace_id='w' AND aggregate_type='agent_exchange_request'"
        ).fetchone()[0], 1)

    def test_old_reply_rejects_closed_and_expired_imports(self):
        closed = self.platform.create_agent_exchange_request("w", source_agent_id="a",
            target_agent_id="b", request_kind="question", request_summary="closed")
        closed_id = closed["agentExchangeRequest"]["exchangeRequestId"]
        self.platform.close_agent_exchange_request("w", exchange_request_id=closed_id)
        expired = self.platform.create_agent_exchange_request("w", source_agent_id="a",
            target_agent_id="b", request_kind="question", request_summary="expired",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        expired_id = expired["agentExchangeRequest"]["exchangeRequestId"]
        CommunicationMigration(self.connection, directory=PlatformCommunicationDirectory(self.connection)).migrate(
            "w", operator="fixture", stopped_writers_confirmed=True)
        for identity in (closed_id, expired_id):
            error = self.cli("agent-reply", "--workspace-id", "w", "--request", identity,
                             "--agent", "b", "--message", "late", success=False)
            self.assertIn("closed or expired", error["error"]["message"])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_receipts").fetchone()[0], 0)

    def test_old_status_requires_identity_and_preserves_private_visibility(self):
        created = self.platform.create_agent_exchange_request("w", source_agent_id="a",
            target_agent_id="b", request_kind="question", request_summary="private")
        old_id = created["agentExchangeRequest"]["exchangeRequestId"]
        self.platform.update_agent_exchange_thread_visibility("w", thread_id=created["agentExchangeRequest"]["threadId"],
            updated_by_agent_id="a", visibility="participants_only")
        CommunicationMigration(self.connection, directory=PlatformCommunicationDirectory(self.connection)).migrate(
            "w", operator="fixture", stopped_writers_confirmed=True)
        no_identity = self.cli("agent-exchange-request-get", "--workspace-id", "w",
            "--exchange-request-id", old_id, success=False)
        self.assertIn("explicit requesting agent", no_identity["error"]["message"])
        denied = self.cli("agent-exchange-request-get", "--workspace-id", "w",
            "--exchange-request-id", old_id, "--agent-id", "c", success=False)
        self.assertIn("not visible", denied["error"]["message"])
        allowed = self.cli("agent-exchange-request-get", "--workspace-id", "w",
            "--exchange-request-id", old_id, "--agent-id", "b")
        self.assertEqual(allowed["agentExchangeRequest"]["requestSummary"], "private")
        wake_denied = self.cli("agent-wake-status", "--workspace-id", "w",
            "--exchange-request-id", old_id, "--agent-id", "c", success=False)
        self.assertIn("not visible", wake_denied["error"]["message"])

    def test_agent_reply_cannot_self_assert_provider_authority(self):
        old_id, _ = self.migrate_request()
        error = self.cli("agent-exchange-request-respond", "--workspace-id", "w",
            "--exchange-request-id", old_id, "--responding-agent-id", "b",
            "--response-summary", "untrusted", "--response-source", "provider_final_capture",
            success=False)
        self.assertIn("cannot assert provider response authority", error["error"]["message"])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_receipts").fetchone()[0], 0)

    def test_old_close_uses_core_and_rejects_wrong_actor_or_duplicate(self):
        old_id, message_id = self.migrate_request()
        wrong = self.cli("agent-exchange-request-close", "--workspace-id", "w",
            "--exchange-request-id", old_id, "--agent-id", "c", success=False)
        self.assertIn("only sender", wrong["error"]["message"])
        closed = self.cli("agent-exchange-request-close", "--workspace-id", "w",
            "--exchange-request-id", old_id, "--agent-id", "a",
            "--terminal-reason", "revoked", "--idempotency-key", "close-1")
        self.assertEqual(closed["engine"], "core")
        self.assertEqual(closed["agentExchangeRequest"]["messageId"], message_id)
        self.assertEqual(closed["agentExchangeRequest"]["terminalReason"], "revoked")
        repeat = self.cli("agent-exchange-request-close", "--workspace-id", "w",
            "--exchange-request-id", old_id, "--agent-id", "a",
            "--terminal-reason", "revoked", "--idempotency-key", "close-1")
        self.assertEqual(repeat["communicationLedgerSequence"], closed["communicationLedgerSequence"])
        duplicate = self.cli("agent-exchange-request-close", "--workspace-id", "w",
            "--exchange-request-id", old_id, "--agent-id", "a", success=False)
        self.assertIn("already terminal", duplicate["error"]["message"])
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM platform_events WHERE workspace_id='w' AND aggregate_type='agent_exchange_request'"
        ).fetchone()[0], 1)

    def test_queued_old_send_maps_atomically_and_unwired_writers_remain_fenced(self):
        self.migrate_request()
        before = self.connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0]
        sent = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b",
            "--target-provider", "codex", "--reply-policy", "message_only",
            "--message", "queued synthetic", "--queued")
        self.assertEqual(sent["engine"], "core")
        self.assertTrue(sent["queuedDispatchCreated"])
        message_id = sent["agentDispatch"]["messageId"]
        self.assertEqual(self.cli("agent-message-get", "--workspace-id", "w",
            "--agent-id", "b", "--message-id", sent["agentDispatch"]["exchangeRequestId"]
            )["message"]["id"], message_id)
        status = self.cli("agent-dispatch-status", "--workspace-id", "w",
            "--dispatch-id", sent["agentDispatch"]["dispatchId"], "--agent-id", "a")
        self.assertEqual(status["agentDispatch"]["messageId"], message_id)
        self.assertEqual(status["agentDispatch"]["status"], "pending")
        denied = self.cli("agent-dispatch-status", "--workspace-id", "w",
            "--dispatch-id", sent["agentDispatch"]["dispatchId"], success=False)
        self.assertIn("explicit requesting agent", denied["error"]["message"])
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM communication_mappings WHERE workspace_id='w' "
            "AND legacy_sequence=0").fetchone()[0], 2)
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM communication_deliveries WHERE workspace_id='w' "
            "AND schedule='pending'").fetchone()[0], 1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0], before)
        app = LocalPlatformApplication(LocalPlatformSettings(database=str(self.path),
            workspace_root=self.temp.name, plugins_directory=self.temp.name,
            profile_path=str(self.profile)))
        created = app.create_agent_dispatch(workspace_id="w", source_agent_id="a", target_agent_id="b",
            request_kind="question", request_summary="core direct create", reply_policy="message_only")
        self.assertEqual(created["engine"], "core")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0], before)
        preview = self.cli("agent-dispatch-worker-run-once", "--workspace-id", "w",
            "--dispatch-id", sent["agentDispatch"]["dispatchId"], "--dry-run")
        self.assertEqual(preview["engine"], "core")
        self.assertEqual(preview["candidateCount"], 1)
        self.assertEqual(preview["processedCount"], 0)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0], before)

    def test_core_queued_send_enforces_thread_budget_and_policy(self):
        self.migrate_request()
        self.platform.update_agent_exchange_request_policy("w", max_turns=1)
        first = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b",
            "--reply-policy", "message_only", "--message", "first", "--queued")
        thread_id = first["agentExchangeRequest"]["threadId"]
        before = self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0]
        rejected = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b",
            "--reply-policy", "message_only", "--message", "second",
            "--thread-id", thread_id, "--queued", success=False)
        self.assertIn("maxTurns", rejected["error"]["message"])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0], before)
        self.platform.update_agent_exchange_request_policy("w", authorization_mode="disabled")
        rejected = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b",
            "--reply-policy", "message_only", "--message", "blocked", "--queued", success=False)
        self.assertIn("disabled", rejected["error"]["message"])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0], before)

    def test_core_handoff_argv_reads_acks_and_replies_in_independent_processes(self):
        self.migrate_request()
        sent = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b",
            "--reply-policy", "message_only", "--message", "中文 handoff", "--queued")
        actions = sent["targetHandoff"]
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC"}}
        env.update(PYTHONPATH=actions["runtimeEnvironment"]["PYTHONPATH"],
                   PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        def invoke(argv):
            result = subprocess.run(argv, cwd=self.temp.name, env=env,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        request_id = sent["agentDispatch"]["exchangeRequestId"]
        self.assertEqual(invoke(actions["messageGetArgv"])["message"]["body"], "中文 handoff")
        self.assertEqual(invoke(actions["ackArgv"])["receipt"]["kind"], "ack")
        response = ["合成处理完成" if item == "<short target-agent response>" else item
                    for item in actions["respondArgvTemplate"]]
        self.assertEqual(invoke(response)["agentExchangeRequest"]["exchangeRequestId"], request_id)
        self.assertEqual(self.cli("agent-message-status", "--workspace-id", "w",
            "--agent-id", "a", "--message-id", request_id)["reply"], "final")

    def test_new_core_message_reply_keeps_legacy_response_length_bound(self):
        self.migrate_request()
        sent = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b",
            "--reply-policy", "message_only", "--message", "bounded", "--queued")
        rejected = self.cli("agent-message-reply", "--workspace-id", "w",
            "--agent-id", "b", "--message-id", sent["agentDispatch"]["messageId"],
            "--message", "x" * 2001, success=False)
        self.assertIn("maximum response length", rejected["error"]["message"])

    def test_core_queued_send_freezes_seven_existing_backend_capture_defaults(self):
        self.platform.register_claude_session_handle("w", agent_id="c", handle_id="h-c",
            claude_session_uuid=str(uuid4()), cwd=self.temp.name,
            created_by="fixture", reason="fixture")
        self.platform.login_agent_endpoint("w", agent_id="c", alias="c", provider="claude",
                                           provider_handle_id="h-c")
        self.platform.create_agent_registration("w", agent_id="d", name="d", description="fixture")
        self.platform.register_hermes_session_handle("w", agent_id="d", handle_id="h-d",
            hermes_session_id=str(uuid4()), cwd=self.temp.name,
            created_by="fixture", reason="fixture")
        self.platform.login_agent_endpoint("w", agent_id="d", alias="d", provider="hermes",
                                           provider_handle_id="h-d")
        self.platform.create_agent_registration("w", agent_id="e", name="e", description="fixture")
        self.platform.register_deepseek_harness_session_handle("w", agent_id="e", handle_id="h-e",
            deepseek_harness_session_id=str(uuid4()), cwd=self.temp.name,
            created_by="fixture", reason="fixture")
        self.platform.login_agent_endpoint("w", agent_id="e", alias="e", provider="deepseek_harness",
                                           provider_handle_id="h-e")
        self.migrate_request()
        cases = (
            ("b", "codex", "--codex-activation-backend", "exec_resume", "explicit_only"),
            ("b", "codex", "--codex-activation-backend", "app_server", "explicit_only"),
            ("c", "claude", "--claude-activation-backend", "cli", "provider_final_capture"),
            ("c", "claude", "--claude-activation-backend", "agent_sdk", "explicit_only"),
            ("d", "hermes", "--hermes-activation-backend", "cli", "provider_final_capture"),
            ("d", "hermes", "--hermes-activation-backend", "tui_gateway", "explicit_only"),
            ("e", "deepseek_harness", "--request-kind", "question", "provider_final_capture"),
        )
        for target, provider, option, backend, capture in cases:
            with self.subTest(provider=provider, backend=backend):
                sent = self.cli("agent-dispatch-send", "--workspace-id", "w",
                    "--source-agent-id", "a", "--target-agent-id", target,
                    "--target-provider", provider, "--reply-policy", "message_only",
                    "--message", f"synthetic {provider} {backend}", "--queued", option, backend)
                self.assertEqual(sent["providerBackend"], "sdk_stdio" if provider == "deepseek_harness" else backend)
                self.assertEqual(sent["capturePolicy"], capture)
                row = self.connection.execute("SELECT data FROM communication_deliveries "
                    "WHERE message_id=?", (sent["agentDispatch"]["messageId"],)).fetchone()
                self.assertEqual(json.loads(row[0])["capture"], capture)

    def test_core_queued_send_uses_existing_grant_reference_without_consuming_it(self):
        self.migrate_request()
        grant = self.platform.create_delegated_wake_grant("w", source_agent_id="a",
            target_agent_id="b", created_by="fixture-user", reason="synthetic grant",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1))
        grant_id = grant["delegatedWakeGrant"]["delegatedWakeGrantId"]
        self.platform.update_agent_exchange_request_policy("w",
            authorization_mode="delegated_grant_required")
        base = ("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b",
            "--reply-policy", "message_only", "--queued")
        missing = self.cli(*base, "--message", "missing grant", success=False)
        self.assertIn("linkedDelegatedWakeGrantId", missing["error"]["message"])
        first = self.cli(*base, "--message", "pending grant",
            "--linked-delegated-wake-grant-id", grant_id)
        self.assertEqual(first["engine"], "core")
        self.assertEqual(self.platform.get_delegated_wake_grant_status("w",
            delegated_wake_grant_id=grant_id)["delegatedWakeGrant"]["state"], "pending")
        self.platform.consume_delegated_wake_grant("w", delegated_wake_grant_id=grant_id,
                                                   consuming_agent_id="a")
        second = self.cli(*base, "--message", "consumed reference",
            "--linked-delegated-wake-grant-id", grant_id)
        self.assertEqual(second["engine"], "core")
        self.assertEqual(self.platform.get_delegated_wake_grant_status("w",
            delegated_wake_grant_id=grant_id)["delegatedWakeGrant"]["state"], "consumed")

    def test_parallel_cli_senders_cannot_exceed_one_remaining_thread_turn(self):
        self.migrate_request()
        self.platform.update_agent_exchange_request_policy("w", max_turns=2)
        root = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b",
            "--reply-policy", "message_only", "--message", "root", "--queued")
        thread_id = root["agentExchangeRequest"]["threadId"]
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC"}}
        env.update(PYTHONPATH=str(SRC), PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        def send(index):
            result = subprocess.run([sys.executable, "-B", "-m", "agent_os.local_runtime",
                "--profile", str(self.profile), "agent-dispatch-send", "--workspace-id", "w",
                "--source-agent-id", "a", "--target-agent-id", "b",
                "--reply-policy", "message_only", "--message", f"parallel {index}",
                "--thread-id", thread_id, "--queued"], cwd=self.temp.name, env=env,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            return result.returncode, json.loads(result.stdout if result.returncode == 0 else result.stderr)
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(send, (1, 2)))
        self.assertEqual(sorted(code for code, _ in outcomes), [0, 1])
        self.assertIn("maxTurns", next(payload["error"]["message"] for code, payload in outcomes if code))
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM communication_messages WHERE thread_id=?", (thread_id,)).fetchone()[0], 2)

    def test_core_send_fault_rolls_back_message_budget_and_both_mappings(self):
        self.migrate_request()
        repo = SqliteCommunicationRepository(self.connection,
            fault=lambda phase: (_ for _ in ()).throw(RuntimeError("injected"))
            if phase == "after_mappings" else None)
        service = CommunicationService(repo,
            PlatformCommunicationDirectory(self.connection, platform=self.platform),
            send_compatibility=LegacyExchangeSendCompatibility(repo, self.platform))
        before = {table: self.connection.execute(f"SELECT COUNT(*) FROM communication_{table}").fetchone()[0]
                  for table in ("messages", "threads", "deliveries", "mappings", "idempotency")}
        with self.assertRaisesRegex(RuntimeError, "injected"):
            service.send(Caller("w", "a"), target_alias="b", body="rollback synthetic", key="d-fault",
                reply_policy="message_only", legacy_context={"request_id": "r-fault",
                    "dispatch_id": "d-fault", "request_kind": "question"})
        after = {table: self.connection.execute(f"SELECT COUNT(*) FROM communication_{table}").fetchone()[0]
                 for table in before}
        self.assertEqual(after, before)

    def test_owned_provider_scope_defers_final_until_single_core_evidence_write(self):
        self.migrate_request()
        sent = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b",
            "--reply-policy", "message_only", "--message", "capture fixture",
            "--queued", "--codex-reply-writeback-mode", "provider_final_capture")
        request_id = sent["agentDispatch"]["exchangeRequestId"]
        message_id = sent["agentDispatch"]["messageId"]
        repo = SqliteCommunicationRepository(self.connection)
        service = CommunicationService(repo,
            PlatformCommunicationDirectory(self.connection, platform=self.platform))
        claim = Claim(**service.claim("w", message_id, owner="synthetic-provider")["claim"])
        service.mark_started(claim)
        scope = CoreProviderScope(service, claim)
        before = self.connection.execute("SELECT COUNT(*) FROM communication_receipts").fetchone()[0]
        with core_provider_scope(scope):
            projected = self.platform._latest_agent_exchange_request_by_id(WorkspaceId("w"), request_id)
            self.assertTrue(projected.is_active())
            deferred = self.platform._record_provider_final("w", exchange_request_id=request_id,
                responding_agent_id="b", response_summary="trusted synthetic final",
                metadata={"responseSource": "codex_exec_resume_auto_capture"})
            self.assertTrue(deferred["coreFinalDeferred"])
            self.assertEqual(self.platform._latest_agent_exchange_request_by_id(
                WorkspaceId("w"), request_id).response_summary, "trusted synthetic final")
            self.assertEqual(self.connection.execute(
                "SELECT COUNT(*) FROM communication_receipts").fetchone()[0], before)
        binding = repo.get("attempts", "w", claim.attempt_id)["binding"]
        service.complete(claim, ProviderEvidence(binding["provider"], binding["native_session_id"],
            "finished", "synthetic:owned-capture", accepted=True, stopped=True,
            final=scope.final, trusted_final=True, generation=binding["generation"]))
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM communication_receipts").fetchone()[0], before + 1)
        self.assertEqual(service.status(Caller("w", "a"), message_id)["reply"], "final")

    def test_core_provider_adapter_maps_correlated_fake_final_to_one_evidence_write(self):
        self.migrate_request()
        sent = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b",
            "--reply-policy", "message_only", "--message", "adapter fixture",
            "--queued", "--codex-reply-writeback-mode", "provider_final_capture")
        identity = sent["agentDispatch"]["messageId"]
        repo = SqliteCommunicationRepository(self.connection)
        service = CommunicationService(repo,
            PlatformCommunicationDirectory(self.connection, platform=self.platform))
        claim = Claim(**service.claim("w", identity, owner="fake-adapter")["claim"])
        service.mark_started(claim)
        class FakeBackend:
            def _activate_agent_dispatch_provider(self, workspace_id, *, dispatch, provider, **options):
                from agent_os.application.services.communication_provider_scope import current_core_provider_scope
                active = current_core_provider_scope()
                active.record_final(workspace_id=workspace_id.value,
                    exchange_request_id=dispatch.exchange_request_id,
                    responding_agent_id=dispatch.target_agent_id,
                    response_summary="fake verified final",
                    metadata={"responseSource": "codex_exec_resume_auto_capture"},
                    requires_user_review=False)
                return {"codexRegisteredSessionActivation": {"status": "delivered",
                    "providerCommandStarted": True, "sourceEventSequence": 123,
                    "activationAttemptId": "fake-native-turn"}}
        binding = repo.get("attempts", "w", claim.attempt_id)["binding"]
        evidence = CoreProviderAdapter(service, FakeBackend(), {})(
            repo.get("messages", "w", identity), binding, claim, 120)
        self.assertEqual(evidence.final, "fake verified final")
        self.assertEqual(evidence.evidence_ref, "platform-event:123")
        self.assertEqual(repo.receipts("w", identity), [])
        service.complete(claim, evidence)
        self.assertEqual(service.status(Caller("w", "a"), identity)["reply"], "final")

    def test_provider_delivered_label_without_start_evidence_stays_unknown(self):
        self.migrate_request()
        sent = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b",
            "--reply-policy", "message_only", "--message", "unproven start", "--queued")
        identity = sent["agentDispatch"]["messageId"]
        repo = SqliteCommunicationRepository(self.connection)
        service = CommunicationService(repo,
            PlatformCommunicationDirectory(self.connection, platform=self.platform))
        claim = Claim(**service.claim("w", identity, owner="fake-adapter")["claim"])
        service.mark_started(claim)
        class TicketOnly:
            def _activate_agent_dispatch_provider(self, workspace_id, *, dispatch, provider, **options):
                return {"codexRegisteredSessionActivation": {"status": "delivered",
                    "providerCommandStarted": False, "activationAttemptId": "ticket-only"}}
        binding = repo.get("attempts", "w", claim.attempt_id)["binding"]
        evidence = CoreProviderAdapter(service, TicketOnly(), {})(
            repo.get("messages", "w", identity), binding, claim, 120)
        self.assertEqual(evidence.outcome, "unknown")
        self.assertFalse(evidence.accepted)
        self.assertFalse(evidence.stopped)

    def test_normal_app_one_shot_worker_uses_fake_backend_and_core_final(self):
        self.migrate_request()
        sent = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b",
            "--reply-policy", "message_only", "--message", "fake worker fixture",
            "--queued", "--codex-reply-writeback-mode", "provider_final_capture")
        app = LocalPlatformApplication(LocalPlatformSettings(database=str(self.path),
            workspace_root=self.temp.name, plugins_directory=self.temp.name,
            profile_path=str(self.profile)))
        before = self.connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0]
        def fake_backend(platform, workspace_id, *, dispatch, provider, **options):
            self.assertEqual(provider, "codex")
            self.assertEqual(options["codex_reply_writeback_mode"], "provider_final_capture")
            platform._record_provider_final(workspace_id,
                exchange_request_id=dispatch.exchange_request_id,
                responding_agent_id=dispatch.target_agent_id,
                response_summary="fake worker final",
                metadata={"responseSource": "codex_exec_resume_auto_capture"})
            return {"codexRegisteredSessionActivation": {"status": "delivered",
                "providerCommandStarted": True, "activationAttemptId": "fake-exec-resume"}}
        with mock.patch.object(LocalPlatformOperationService,
                               "_activate_agent_dispatch_provider", fake_backend):
            result = app.run_agent_dispatch_worker_once(workspace_id="w",
                dispatch_id=sent["agentDispatch"]["dispatchId"],
                skip_busy_target=False, dry_run=False)
        self.assertEqual(result["engine"], "core")
        self.assertEqual(result["processedCount"], 1)
        self.assertEqual(self.cli("agent-message-status", "--workspace-id", "w",
            "--agent-id", "a", "--message-id", sent["agentDispatch"]["messageId"])["reply"], "final")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0], before)

    def test_core_native_message_without_legacy_request_id_reaches_provider_scope(self):
        self.migrate_request()
        repo = SqliteCommunicationRepository(self.connection)
        service = CommunicationService(repo,
            PlatformCommunicationDirectory(self.connection, platform=self.platform))
        message = service.send(Caller("w", "a"), target_alias="b", body="native core send",
            key="native-core-send", wake="when_available", capture="provider_final_capture")
        self.assertNotIn("legacy_request_id", message)
        app = LocalPlatformApplication(LocalPlatformSettings(database=str(self.path),
            workspace_root=self.temp.name, plugins_directory=self.temp.name,
            profile_path=str(self.profile)))
        def fake_backend(platform, workspace_id, *, dispatch, provider, **options):
            self.assertEqual(dispatch.exchange_request_id, message["id"])
            platform._record_provider_final(workspace_id,
                exchange_request_id=dispatch.exchange_request_id,
                responding_agent_id=dispatch.target_agent_id,
                response_summary="native core final",
                metadata={"responseSource": "codex_exec_resume_auto_capture"})
            return {"codexRegisteredSessionActivation": {"status": "delivered",
                "providerCommandStarted": True, "activationAttemptId": "fake-native-core"}}
        with mock.patch.object(LocalPlatformOperationService,
                               "_activate_agent_dispatch_provider", fake_backend):
            result = app.run_agent_dispatch_worker_once(workspace_id="w", limit=1,
                skip_busy_target=False, dry_run=False)
        self.assertEqual(result["processedCount"], 1)
        self.assertEqual(service.status(Caller("w", "a"), message["id"])["reply"], "final")

    def test_cli_worker_executes_fake_codex_resume_without_real_provider(self):
        self.migrate_request()
        sent = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b",
            "--reply-policy", "message_only", "--message", "real CLI fake backend",
            "--queued", "--codex-reply-writeback-mode", "provider_final_capture")
        handle = self.platform.get_codex_session_handle("w", handle_id="h-b")["codexSessionHandle"]
        capture_path = Path(self.temp.name) / "fake-codex-capture.json"
        fake = _fake_codex_command(Path(self.temp.name), handle["codexSessionId"],
                                   capture_path, "fake codex result")
        run = self.cli("agent-dispatch-worker-run-once", "--workspace-id", "w",
            "--dispatch-id", sent["agentDispatch"]["dispatchId"], "--execute",
            "--codex-executable", str(fake), "--ignore-busy-target")
        self.assertEqual(run["engine"], "core")
        self.assertEqual(run["processedCount"], 1)
        self.assertEqual(self.cli("agent-message-status", "--workspace-id", "w",
            "--agent-id", "a", "--message-id", sent["agentDispatch"]["messageId"])["reply"], "final")
        self.assertTrue(capture_path.is_file())
        self.assertIn("real CLI fake backend", capture_path.read_text(encoding="utf-8"))
        wake = self.cli("agent-wake-status", "--workspace-id", "w",
            "--exchange-request-id", sent["agentDispatch"]["exchangeRequestId"],
            "--agent-id", "a")
        self.assertEqual(wake["agentWakeStatus"]["coreExecution"], "finished")
        self.assertTrue(wake["agentWakeStatus"]["providerCommandStarted"])
        deliveries = self.cli("agent-wake-delivery-list", "--workspace-id", "w",
            "--agent-id", "b")
        self.assertIn(sent["agentDispatch"]["messageId"],
            [item["messageId"] for item in deliveries["agentWakeDeliveries"]])
        ticket = self.cli("agent-wake-ticket-get", "--workspace-id", "w",
            "--exchange-request-id", sent["agentDispatch"]["exchangeRequestId"],
            "--agent-id", "b")
        self.assertEqual(ticket["agentWakeTicket"]["status"], "found")

    def test_cli_worker_executes_fake_codex_app_server_backend(self):
        self.migrate_request()
        sent = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b", "--reply-policy", "message_only",
            "--message", "app server fake", "--queued",
            "--codex-activation-backend", "app_server",
            "--codex-reply-writeback-mode", "provider_final_capture")
        handle = self.platform.get_codex_session_handle("w", handle_id="h-b")["codexSessionHandle"]
        fake = _fake_codex_app_server_command(Path(self.temp.name),
            thread_id=handle["codexSessionId"], response_text="app server fake final")
        run = self.cli("agent-dispatch-worker-run-once", "--workspace-id", "w",
            "--dispatch-id", sent["agentDispatch"]["dispatchId"], "--execute",
            "--codex-executable", str(fake), "--ignore-busy-target")
        self.assertEqual(run["agentDispatches"][0]["outcome"], "finished", run)
        status = self.cli("agent-message-status", "--workspace-id", "w", "--agent-id", "a",
            "--message-id", sent["agentDispatch"]["messageId"])
        self.assertEqual(status["reply"], "final")

    def test_cli_worker_executes_fake_claude_cli_without_real_provider(self):
        self.migrate_request()
        session_id = str(uuid4())
        self.platform.register_claude_session_handle("w", agent_id="c", handle_id="h-c-claude",
            claude_session_uuid=session_id, cwd=self.temp.name, created_by="fixture", reason="fixture")
        self.platform.login_agent_endpoint("w", agent_id="c", alias="c", provider="claude",
                                           provider_handle_id="h-c-claude")
        sent = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "c",
            "--reply-policy", "message_only", "--message", "fake Claude delivery", "--queued")
        capture_path = Path(self.temp.name) / "fake-claude-capture.json"
        fake = _fake_claude_command(Path(self.temp.name), session_id, capture_path)
        run = self.cli("agent-dispatch-worker-run-once", "--workspace-id", "w",
            "--dispatch-id", sent["agentDispatch"]["dispatchId"], "--execute",
            "--claude-executable", str(fake), "--ignore-busy-target")
        self.assertEqual(run["processedCount"], 1)
        self.assertEqual(self.cli("agent-message-status", "--workspace-id", "w",
            "--agent-id", "a", "--message-id", sent["agentDispatch"]["messageId"])["reply"], "none")
        self.assertIn("Read the wake ticket JSON at:", capture_path.read_text(encoding="utf-8"))
        tickets = list(Path(self.temp.name).rglob("*.wake-*.json"))
        self.assertEqual(len(tickets), 1)
        self.assertIn(sent["agentDispatch"]["exchangeRequestId"],
                      tickets[0].read_text(encoding="utf-8"))

    def test_codex_claude_hermes_fake_backends_exchange_cli_receipts(self):
        self.migrate_request()
        claude_native = str(uuid4())
        self.platform.register_claude_session_handle("w", agent_id="c", handle_id="h-c-claude",
            claude_session_uuid=claude_native, cwd=self.temp.name,
            created_by="fixture", reason="fixture")
        self.platform.login_agent_endpoint("w", agent_id="c", alias="c", provider="claude",
                                           provider_handle_id="h-c-claude")
        self.platform.create_agent_registration("w", agent_id="d", name="d", description="fixture")
        hermes_native = str(uuid4())
        self.platform.register_hermes_session_handle("w", agent_id="d", handle_id="h-d-hermes",
            hermes_session_id=hermes_native, cwd=self.temp.name,
            created_by="fixture", reason="fixture")
        self.platform.login_agent_endpoint("w", agent_id="d", alias="d", provider="hermes",
                                           provider_handle_id="h-d-hermes")
        codex_native = self.platform.get_codex_session_handle("w", handle_id="h-b")[
            "codexSessionHandle"]["codexSessionId"]
        routes = (("c", "b", "codex", codex_native),
                  ("b", "c", "claude", claude_native),
                  ("c", "d", "hermes", hermes_native))
        for source, target, provider, native in routes:
            with self.subTest(provider=provider):
                sent = self.cli("agent-dispatch-send", "--workspace-id", "w",
                    "--from", source, "--to", target,
                    "--reply-policy", "message_only",
                    "--message", f"{provider} two-way synthetic", "--queued",
                    "--codex-reply-writeback-mode", "explicit_only",
                    "--claude-reply-writeback-mode", "explicit_only",
                    "--hermes-reply-writeback-mode", "explicit_only")
                message_id = sent["agentDispatch"]["messageId"]
                capture = Path(self.temp.name) / f"{provider}-two-way-capture.json"
                if provider == "codex":
                    fake = _fake_codex_command(Path(self.temp.name), native,
                                               capture, "ignored explicit-only capture")
                    command = ("--codex-executable", str(fake))
                elif provider == "claude":
                    fake = _fake_claude_command(Path(self.temp.name), native, capture)
                    command = ("--claude-executable", str(fake))
                else:
                    fake = _fake_hermes_command(Path(self.temp.name), native,
                                                capture, "ignored explicit-only capture")
                    command = ("--hermes-executable", str(fake))
                run = self.cli("agent-dispatch-worker-run-once", "--workspace-id", "w",
                    "--dispatch-id", sent["agentDispatch"]["dispatchId"], "--execute",
                    "--ignore-busy-target", *command)
                self.assertEqual(run["processedCount"], 1, run)
                self.assertEqual(self.cli("agent-message-status", "--workspace-id", "w",
                    "--agent-id", source, "--message-id", message_id)["reply"], "none")
                self.cli("agent-message-ack", "--workspace-id", "w", "--agent-id", target,
                         "--message-id", message_id)
                self.cli("agent-message-reply", "--workspace-id", "w", "--agent-id", target,
                         "--message-id", message_id, "--kind", "progress", "--message", "处理中")
                self.cli("agent-message-reply", "--workspace-id", "w", "--agent-id", target,
                         "--message-id", message_id, "--message", "独立进程完成")
                first = self.cli("agent-message-inbox", "--workspace-id", "w",
                                 "--agent-id", source, "--limit", "1")
                second = self.cli("agent-message-inbox", "--workspace-id", "w",
                    "--agent-id", source, "--cursor", first["cursor"], "--limit", "10")
                kinds = [item["kind"] for item in first["items"] + second["items"]
                         if item["message_id"] == message_id]
                self.assertEqual(kinds, ["ack", "progress", "final"])
                self.assertEqual(self.cli("agent-message-status", "--workspace-id", "w",
                    "--agent-id", source, "--message-id", message_id)["reply"], "final")

    def test_core_worker_uses_existing_claude_sdk_adapter_with_fake_sdk_port(self):
        from agent_os.infrastructure.composition import local_platform as composition
        session_id = str(uuid4())
        self.platform.register_claude_session_handle("w", agent_id="c", handle_id="h-c-sdk",
            claude_session_uuid=session_id, cwd=self.temp.name, created_by="fixture", reason="fixture")
        self.platform.login_agent_endpoint("w", agent_id="c", alias="c", provider="claude",
                                           provider_handle_id="h-c-sdk")
        self.migrate_request()
        sent = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "c",
            "--reply-policy", "message_only", "--message", "fake SDK message",
            "--queued", "--claude-activation-backend", "agent_sdk")
        app = LocalPlatformApplication(LocalPlatformSettings(database=str(self.path),
            workspace_root=self.temp.name, plugins_directory=self.temp.name,
            profile_path=str(self.profile)))
        original = composition.build_local_platform_operation_service
        def fake_sdk_operations(connection):
            operations = original(connection)
            operations.claude_agent_sdk_runtime_loader = lambda: _sdk_runtime(compatible=True)
            operations.claude_agent_sdk_runner = lambda *args, **kwargs: _sdk_result(
                final_response="SDK fixture final")
            return operations
        with mock.patch.object(composition, "build_local_platform_operation_service",
                               side_effect=fake_sdk_operations):
            run = app.run_agent_dispatch_worker_once(workspace_id="w",
                dispatch_id=sent["agentDispatch"]["dispatchId"], skip_busy_target=False)
        self.assertEqual(run["agentDispatches"][0]["outcome"], "finished", run)
        status = self.cli("agent-message-status", "--workspace-id", "w", "--agent-id", "a",
            "--message-id", sent["agentDispatch"]["messageId"])
        self.assertEqual(status["reply"], "none")
        self.assertEqual(status["delivery"]["execution"], "finished")

    def test_cli_worker_executes_fake_hermes_cli_without_real_provider(self):
        self.migrate_request()
        session_id = str(uuid4())
        self.platform.register_hermes_session_handle("w", agent_id="c", handle_id="h-c-hermes",
            hermes_session_id=session_id, cwd=self.temp.name, created_by="fixture", reason="fixture",
            metadata={"hermesSessionIdentity": {"schema": "hermes_session_identity.v1",
                "providerSessionId": session_id, "runtimeHome": self.temp.name,
                "runtimeHomeSource": "explicit", "sessionSource": "cli",
                "fullSessionHistoryRead": False}})
        self.platform.login_agent_endpoint("w", agent_id="c", alias="c", provider="hermes",
                                           provider_handle_id="h-c-hermes")
        sent = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "c",
            "--reply-policy", "message_only", "--message", "fake Hermes delivery", "--queued")
        capture_path = Path(self.temp.name) / "fake-hermes-capture.json"
        fake = _fake_hermes_command(Path(self.temp.name), session_id, capture_path,
                                     "fake Hermes final")
        run = self.cli("agent-dispatch-worker-run-once", "--workspace-id", "w",
            "--dispatch-id", sent["agentDispatch"]["dispatchId"], "--execute",
            "--hermes-executable", str(fake), "--hermes-home", self.temp.name,
            "--ignore-busy-target")
        self.assertEqual(run["processedCount"], 1)
        self.assertEqual(self.cli("agent-message-status", "--workspace-id", "w",
            "--agent-id", "a", "--message-id", sent["agentDispatch"]["messageId"])["reply"], "final")
        self.assertIn("Read the wake ticket JSON at:", capture_path.read_text(encoding="utf-8"))
        tickets = list(Path(self.temp.name).rglob("*.wake-*.json"))
        self.assertEqual(len(tickets), 1)
        self.assertIn(sent["agentDispatch"]["exchangeRequestId"],
                      tickets[0].read_text(encoding="utf-8"))

    def test_core_worker_uses_existing_hermes_tui_adapter_with_fake_gateway_port(self):
        session_id = str(uuid4())
        self.platform.register_hermes_session_handle("w", agent_id="c", handle_id="h-c-tui",
            hermes_session_id=session_id, cwd=self.temp.name, created_by="fixture", reason="fixture",
            metadata={"hermesSessionIdentity": {"schema": "hermes_session_identity.v1",
                "providerSessionId": session_id, "runtimeHome": self.temp.name,
                "runtimeHomeSource": "explicit", "sessionSource": "cli",
                "fullSessionHistoryRead": False}})
        self.platform.login_agent_endpoint("w", agent_id="c", alias="c", provider="hermes",
                                           provider_handle_id="h-c-tui")
        self.migrate_request()
        sent = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "c",
            "--reply-policy", "message_only", "--message", "fake TUI request",
            "--queued", "--hermes-activation-backend", "tui_gateway")
        runtime = HermesTuiGatewayRuntime(status="available", compatible=True,
            python_executable="fake-python", package_version="0.19.0",
            package_location=self.temp.name,
            gateway_entry_location=str(Path(self.temp.name) / "entry.py"),
            server_location=str(Path(self.temp.name) / "server.py"),
            launch_argv=("fake-python", "-u", "-m", "tui_gateway.entry"),
            methods={"session.resume": True}, events={"gateway.ready": True},
            capabilities={"version": "0.19.0"})
        gateway_result = HermesTuiGatewayRunResult(status="completed", package_version="0.19.0",
            provider_command_started=True, prompt_submission_attempted=True,
            prompt_submitted=True, session_continuity_verified=True,
            persistent_session_id=session_id, runtime_session_id="fake-runtime",
            event_counts={"gateway.ready": 1, "message.complete": 1},
            identity_evidence={"sessionListSourceVerified": True,
                "resumePersistentIdVerified": True, "cwdVerification": "verified"},
            final_response="fake gateway final", final_response_source="gateway_event.message.complete",
            terminal_status="complete", cleanup_status="terminated", exit_code=0,
            wire_methods=("session.list", "session.resume", "prompt.submit"))
        app = LocalPlatformApplication(LocalPlatformSettings(database=str(self.path),
            workspace_root=self.temp.name, plugins_directory=self.temp.name,
            profile_path=str(self.profile)))
        with mock.patch("agent_os.application.services.local_platform_operations."
                        "load_hermes_tui_gateway_runtime", return_value=runtime), mock.patch(
                        "agent_os.application.services.local_platform_operations."
                        "run_hermes_tui_gateway_activation", return_value=gateway_result):
            run = app.run_agent_dispatch_worker_once(workspace_id="w",
                dispatch_id=sent["agentDispatch"]["dispatchId"], skip_busy_target=False)
        self.assertEqual(run["agentDispatches"][0]["outcome"], "finished", run)
        status = self.cli("agent-message-status", "--workspace-id", "w", "--agent-id", "a",
            "--message-id", sent["agentDispatch"]["messageId"])
        self.assertEqual(status["reply"], "none")

    def test_default_inline_send_executes_fake_backend_and_dry_run_has_no_write(self):
        self.migrate_request()
        handle = self.platform.get_codex_session_handle("w", handle_id="h-b")["codexSessionHandle"]
        fake = _fake_codex_command(Path(self.temp.name), handle["codexSessionId"],
            Path(self.temp.name) / "inline-capture.json", "inline fake result")
        before = self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0]
        preview = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b", "--reply-policy", "message_only",
            "--message", "preview only", "--dry-run", "--ignore-busy-target")
        self.assertTrue(preview["dryRun"])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0], before)
        sent = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b", "--reply-policy", "message_only",
            "--message", "inline fake send", "--codex-executable", str(fake),
            "--ignore-busy-target", "--codex-reply-writeback-mode", "provider_final_capture")
        self.assertEqual(sent["deliveryMode"], "worker_execute")
        self.assertTrue(sent["workerExecuted"])
        self.assertEqual(sent["workerRun"]["processedCount"], 1)
        self.assertEqual(self.cli("agent-message-status", "--workspace-id", "w",
            "--agent-id", "a", "--message-id", sent["agentDispatch"]["messageId"])["reply"], "final")

    def test_default_inline_busy_return_cancels_pending_intent(self):
        self.migrate_request()
        first = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b", "--reply-policy", "message_only",
            "--message", "in-flight synthetic", "--queued")
        repo = SqliteCommunicationRepository(self.connection)
        service = CommunicationService(repo,
            PlatformCommunicationDirectory(self.connection, platform=self.platform))
        claim = Claim(**service.claim("w", first["agentDispatch"]["messageId"],
            owner="already-running", lease_seconds=300)["claim"])
        service.mark_started(claim)
        sent = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b", "--reply-policy", "message_only",
            "--message", "busy inline", "--ignore-busy-target")
        self.assertEqual(sent["workerRun"]["agentDispatches"][0]["outcome"], "busy")
        self.assertFalse(sent["queuedDispatchCreated"])
        status = self.cli("agent-message-status", "--workspace-id", "w", "--agent-id", "a",
            "--message-id", sent["agentDispatch"]["messageId"])
        self.assertEqual(status["delivery"]["schedule"], "cancelled")
        self.assertEqual(self.cli("agent-dispatch-worker-run-once", "--workspace-id", "w",
            "--dispatch-id", sent["agentDispatch"]["dispatchId"], "--dry-run")["candidateCount"], 0)

    def test_core_old_lists_are_viewer_scoped_and_read_from_ledger(self):
        self.migrate_request()
        sent = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b", "--reply-policy", "message_only",
            "--message", "listed core only", "--queued")
        self.assertIn("explicit requesting agent", self.cli("agent-exchange-request-list",
            "--workspace-id", "w", success=False)["error"]["message"])
        listed = self.cli("agent-exchange-request-list", "--workspace-id", "w",
            "--agent-id", "a", "--source-agent-id", "a")
        self.assertIn(sent["agentDispatch"]["exchangeRequestId"],
            [item["exchangeRequestId"] for item in listed["agentExchangeRequests"]])
        dispatches = self.cli("agent-dispatch-list", "--workspace-id", "w",
            "--agent-id", "b", "--target-agent-id", "b")
        self.assertIn(sent["agentDispatch"]["dispatchId"],
            [item["dispatchId"] for item in dispatches["agentDispatches"]])
        thread_id = sent["agentExchangeRequest"]["threadId"]
        thread = self.cli("agent-exchange-thread-get", "--workspace-id", "w",
            "--thread-id", thread_id, "--requesting-agent-id", "a")
        self.assertEqual(thread["agentExchangeThread"]["threadStatus"], "active")
        threads = self.cli("agent-exchange-thread-list", "--workspace-id", "w",
            "--requesting-agent-id", "a")
        self.assertIn(thread_id, [item["threadId"] for item in threads["agentExchangeThreads"]])
        requests = self.cli("agent-exchange-thread-requests", "--workspace-id", "w",
            "--thread-id", thread_id, "--requesting-agent-id", "b")
        self.assertEqual(requests["agentExchangeRequests"][0]["requestSummary"], "listed core only")
        self.cli("agent-exchange-thread-visibility-update", "--workspace-id", "w",
            "--thread-id", thread_id, "--updated-by-agent-id", "a",
            "--visibility", "participants_only")
        invisible = self.cli("agent-exchange-thread-get", "--workspace-id", "w",
            "--thread-id", thread_id, "--requesting-agent-id", "c", success=False)
        self.assertIn("not visible", invisible["error"]["message"])
        self.assertNotIn(thread_id, [item["threadId"] for item in self.cli(
            "agent-exchange-thread-list", "--workspace-id", "w", "--requesting-agent-id", "c")
            ["agentExchangeThreads"]])
        closed = self.cli("agent-exchange-thread-close", "--workspace-id", "w",
            "--thread-id", thread_id, "--closed-by-agent-id", "a")
        self.assertEqual(closed["agentExchangeThread"]["threadStatus"], "terminal")

    def test_old_request_create_uses_core_without_schedulable_dispatch(self):
        self.migrate_request()
        before = self.connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0]
        created = self.cli("agent-exchange-request-create", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b", "--request-kind", "question",
            "--request-summary", "core request without wake")
        self.assertEqual(created["engine"], "core")
        identity = created["agentExchangeRequest"]["exchangeRequestId"]
        self.assertEqual(self.cli("agent-message-get", "--workspace-id", "w",
            "--agent-id", "b", "--message-id", identity)["message"]["body"],
            "core request without wake")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_mappings "
            "WHERE workspace_id='w' AND legacy_id=?", (identity,)).fetchone()[0], 1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_deliveries "
            "WHERE schedule='pending'").fetchone()[0], 0)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0], before)
        self.platform.update_agent_exchange_request_policy("w", max_turns=3,
            follow_up_policy="single_target_chain")
        follow = self.cli("agent-exchange-thread-follow-up-create", "--workspace-id", "w",
            "--thread-id", created["agentExchangeRequest"]["threadId"],
            "--source-agent-id", "a", "--target-agent-id", "b", "--request-kind", "question",
            "--request-summary", "follow-up core")
        self.assertEqual(follow["engine"], "core")
        self.assertEqual(follow["agentExchangeRequest"]["threadId"],
            created["agentExchangeRequest"]["threadId"])
        self.assertEqual(len(self.cli("agent-exchange-thread-requests", "--workspace-id", "w",
            "--thread-id", created["agentExchangeRequest"]["threadId"],
            "--requesting-agent-id", "a")["agentExchangeRequests"]), 2)

    def test_console_shared_read_shows_core_dispatch_without_message_body(self):
        self.migrate_request()
        sent = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b",
            "--reply-policy", "message_only", "--message", "secret synthetic body",
            "--queued")
        app = LocalPlatformApplication(LocalPlatformSettings(database=str(self.path),
            workspace_root=self.temp.name, plugins_directory=self.temp.name,
            profile_path=str(self.profile)))
        view = app.get_console_workspace_view(workspace_id="w")
        dispatch = next(item for item in view["dispatches"]
            if item["dispatchId"] == sent["agentDispatch"]["dispatchId"])
        self.assertEqual(dispatch["status"], "queued")
        self.assertNotIn("secret synthetic body", json.dumps(view, ensure_ascii=False))
        first = app.get_console_workspace_view(workspace_id="w", limit=1)
        self.assertTrue(first["communicationLedger"]["hasMore"])
        ledger_cursor = first["communicationLedger"]["nextCursor"]
        second = app.get_console_workspace_view(workspace_id="w", limit=1,
            communication_cursor=ledger_cursor)
        self.assertGreater(second["communicationLedger"]["events"][0]
            ["communicationLedgerSequence"], first["communicationLedger"]["events"][0]
            ["communicationLedgerSequence"])
        self.assertNotIn("secret synthetic body", json.dumps(second, ensure_ascii=False))
        cli_page = self.cli("console-workspace-view", "--workspace-id", "w",
            "--communication-cursor", ledger_cursor, "--limit", "1")
        self.assertEqual(cli_page["communicationLedger"]["events"],
                         second["communicationLedger"]["events"])
        with self.assertRaisesRegex(ValueError, "ledger:<sequence>"):
            app.get_console_workspace_view(workspace_id="w", communication_cursor="ord:1")
        with self.assertRaisesRegex(Exception, "ahead of this workspace"):
            app.get_console_workspace_view(workspace_id="w", communication_cursor="ledger:999999")

    def test_two_cli_processes_share_one_core_send_idempotency_result(self):
        self.migrate_request()
        before = self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0]
        args = ("agent-dispatch-send", "--workspace-id", "w", "--source-agent-id", "a",
            "--target-agent-id", "b", "--reply-policy", "message_only",
            "--message", "same idempotent content", "--queued",
            "--idempotency-key", "same-send-key")
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(lambda _: self.cli(*args), range(2)))
        self.assertEqual(first["agentDispatch"]["messageId"], second["agentDispatch"]["messageId"])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0],
                         before + 1)
        conflict = self.cli(*(args[:-5] + ("--message", "different content", "--queued",
            "--idempotency-key", "same-send-key")), success=False)
        self.assertIn("idempotency key", conflict["error"]["message"])
        other_actor = self.cli("agent-dispatch-send", "--workspace-id", "w", "--source-agent-id", "c",
            "--target-agent-id", "b", "--reply-policy", "message_only",
            "--message", "other actor", "--queued", "--idempotency-key", "same-send-key")
        self.assertNotEqual(other_actor["agentDispatch"]["messageId"],
                            first["agentDispatch"]["messageId"])

    def test_grant_activation_and_consumption_rollback_together_on_fault(self):
        self.platform.create_delegated_wake_grant("w", source_agent_id="a",
            target_agent_id="b", created_by="user", reason="synthetic bounded grant",
            delegated_wake_grant_id="grant-fault",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=20))
        log = self.platform.event_log_reader
        original = log.append_in_transaction
        calls = 0
        def fault_on_second(record):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("synthetic consume write failure")
            return original(record)
        before = self.connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0]
        with mock.patch.object(log, "append_in_transaction", side_effect=fault_on_second):
            with self.assertRaisesRegex(RuntimeError, "synthetic consume write failure"):
                self.platform.consume_delegated_wake_grant("w",
                    delegated_wake_grant_id="grant-fault", consuming_agent_id="a")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0], before)
        self.assertEqual(self.platform.get_delegated_wake_grant_status("w",
            delegated_wake_grant_id="grant-fault")["delegatedWakeGrant"]["state"], "pending")

    def test_two_cli_grant_consumers_create_one_activation(self):
        self.platform.create_delegated_wake_grant("w", source_agent_id="a",
            target_agent_id="b", created_by="user", reason="synthetic bounded grant",
            delegated_wake_grant_id="grant-concurrent",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=20))
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC"}}
        env.update(PYTHONPATH=str(SRC), PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        argv = [sys.executable, "-B", "-m", "agent_os.local_runtime", "--profile", str(self.profile),
            "agent-delegated-wake-grant-consume", "--workspace-id", "w",
            "--delegated-wake-grant-id", "grant-concurrent", "--consuming-agent-id", "a"]
        def consume(_):
            return subprocess.run(argv, cwd=self.temp.name, env=env, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=30)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(consume, range(2)))
        self.assertEqual(sorted(item.returncode for item in results), [0, 1],
                         [(item.stdout, item.stderr) for item in results])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM platform_events "
            "WHERE event_kind='agent_activation.changed'").fetchone()[0], 1)

    def test_existing_daemon_once_uses_core_worker_in_synthetic_dry_run(self):
        self.migrate_request()
        sent = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b",
            "--reply-policy", "message_only", "--message", "daemon candidate", "--queued")
        before = self.connection.execute("SELECT COUNT(*) FROM communication_attempts").fetchone()[0]
        run = self.cli("agent-dispatch-daemon-start", "--workspace-id", "w",
            "--dispatch-id", sent["agentDispatch"]["dispatchId"],
            "--once", "--wait", "--dry-run")
        self.assertEqual(run["processExitCode"], 0)
        self.assertIn('"engine": "core"', run["stdout"])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_attempts").fetchone()[0],
                         before)

    def test_existing_daemon_once_executes_fake_codex_through_core(self):
        self.migrate_request()
        sent = self.cli("agent-dispatch-send", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b",
            "--reply-policy", "message_only", "--message", "daemon fake execution",
            "--queued", "--codex-reply-writeback-mode", "provider_final_capture")
        handle = self.platform.get_codex_session_handle("w", handle_id="h-b")["codexSessionHandle"]
        fake = _fake_codex_command(Path(self.temp.name), handle["codexSessionId"],
            Path(self.temp.name) / "daemon-capture.json", "daemon fake final")
        run = self.cli("agent-dispatch-daemon-start", "--workspace-id", "w",
            "--dispatch-id", sent["agentDispatch"]["dispatchId"],
            "--once", "--wait", "--codex-executable", str(fake), "--ignore-busy-target")
        self.assertEqual(run["processExitCode"], 0)
        self.assertIn('"processedCount": 1', run["stdout"])
        self.assertEqual(self.cli("agent-message-status", "--workspace-id", "w",
            "--agent-id", "a", "--message-id", sent["agentDispatch"]["messageId"])["reply"], "final")

    def test_direct_registered_codex_activation_arms_existing_core_request(self):
        self.migrate_request()
        created = self.cli("agent-exchange-request-create", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "b", "--request-kind", "question",
            "--request-summary", "direct core activation")
        request_id = created["agentExchangeRequest"]["exchangeRequestId"]
        before = self.connection.execute("SELECT COUNT(*) FROM communication_mappings").fetchone()[0]
        preview = self.cli("codex-registered-session-activate", "--workspace-id", "w",
            "--agent-id", "b", "--handle-id", "h-b", "--exchange-request-id", request_id,
            "--dry-run")
        self.assertTrue(preview["dryRun"])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_mappings").fetchone()[0], before)
        handle = self.platform.get_codex_session_handle("w", handle_id="h-b")["codexSessionHandle"]
        fake = _fake_codex_command(Path(self.temp.name), handle["codexSessionId"],
            Path(self.temp.name) / "direct-codex-capture.json", "direct fake result")
        run = self.cli("codex-registered-session-activate", "--workspace-id", "w",
            "--agent-id", "b", "--handle-id", "h-b", "--exchange-request-id", request_id,
            "--execute", "--codex-executable", str(fake))
        self.assertEqual(run["engine"], "core")
        self.assertTrue(run["workerExecuted"])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0], 2)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_mappings").fetchone()[0], before + 1)

    def test_direct_registered_claude_activation_uses_core_request(self):
        session_id = str(uuid4())
        self.platform.register_claude_session_handle("w", agent_id="c", handle_id="h-c-claude",
            claude_session_uuid=session_id, cwd=self.temp.name, created_by="fixture", reason="fixture")
        self.platform.login_agent_endpoint("w", agent_id="c", alias="c", provider="claude",
                                           provider_handle_id="h-c-claude")
        self.migrate_request()
        created = self.cli("agent-exchange-request-create", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "c", "--request-kind", "question",
            "--request-summary", "direct Claude core")
        capture = Path(self.temp.name) / "direct-claude-capture.json"
        fake = _fake_claude_command(Path(self.temp.name), session_id, capture)
        run = self.cli("claude-registered-session-activate", "--workspace-id", "w",
            "--agent-id", "c", "--handle-id", "h-c-claude",
            "--exchange-request-id", created["agentExchangeRequest"]["exchangeRequestId"],
            "--execute", "--claude-executable", str(fake))
        self.assertTrue(run["workerExecuted"])
        self.assertTrue(capture.is_file())

    def test_direct_registered_hermes_activation_uses_core_request(self):
        session_id = str(uuid4())
        self.platform.register_hermes_session_handle("w", agent_id="c", handle_id="h-c-hermes",
            hermes_session_id=session_id, cwd=self.temp.name, created_by="fixture", reason="fixture",
            metadata={"hermesSessionIdentity": {"schema": "hermes_session_identity.v1",
                "providerSessionId": session_id, "runtimeHome": self.temp.name,
                "runtimeHomeSource": "explicit", "sessionSource": "cli",
                "fullSessionHistoryRead": False}})
        self.platform.login_agent_endpoint("w", agent_id="c", alias="c", provider="hermes",
                                           provider_handle_id="h-c-hermes")
        self.migrate_request()
        created = self.cli("agent-exchange-request-create", "--workspace-id", "w",
            "--source-agent-id", "a", "--target-agent-id", "c", "--request-kind", "question",
            "--request-summary", "direct Hermes core")
        capture = Path(self.temp.name) / "direct-hermes-capture.json"
        fake = _fake_hermes_command(Path(self.temp.name), session_id, capture, "Hermes direct final")
        run = self.cli("hermes-registered-session-activate", "--workspace-id", "w",
            "--agent-id", "c", "--handle-id", "h-c-hermes",
            "--exchange-request-id", created["agentExchangeRequest"]["exchangeRequestId"],
            "--execute", "--hermes-executable", str(fake), "--hermes-home", self.temp.name)
        self.assertTrue(run["workerExecuted"])
        self.assertTrue(capture.is_file())


if __name__ == "__main__":
    unittest.main()
