"""Real CLI processes for explicit, scoped short references; synthetic data only."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from uuid import uuid4

import test_communication_integration as fixtures
from agent_os.application.services.communication_core import CommunicationService
from agent_os.application.services.local_platform_application import LocalPlatformApplication
from agent_os.application.services.project_workspace_scope import (
    project_workspace_marker_payload,
    write_project_workspace_marker_atomic,
)
from agent_os.domain.entities.communication import Caller
from agent_os.infrastructure.composition.local_platform import build_communication_directory
from agent_os.infrastructure.config import LocalPlatformSettings
from agent_os.infrastructure.persistence.communication_runtime_store import SqliteRuntimeCoordination
from agent_os.infrastructure.persistence.communication_store import SqliteCommunicationRepository
from agent_os.local_runtime import _agent_dispatch_daemon_argv, _build_parser


class CommunicationCompactCliTests(unittest.TestCase):
    def setUp(self):
        fixtures.CommunicationCliIntegrationTests.setUp(self)
        for agent in ("a", "c"):
            self.platform.register_codex_session_handle("w", agent_id=agent, handle_id="h-" + agent,
                codex_session_id=str(uuid4()), cwd=self.temp.name, created_by="fixture", reason="synthetic")
            self.platform.login_agent_endpoint("w", agent_id=agent, alias=agent, provider="codex",
                                               provider_handle_id="h-" + agent)
        self.old_id, self.message_id = fixtures.CommunicationCliIntegrationTests.migrate_request(self)
        self.repo = SqliteCommunicationRepository(self.connection)
        self.service = CommunicationService(self.repo, build_communication_directory(self.connection))
        root = Path(self.temp.name)
        self.settings = LocalPlatformSettings(database=str(self.path), workspace_root=str(root / "workspace root"),
            plugins_directory=str(root / "plugins directory"), profile_path=str(self.profile),
            initialize_schema=False)
        self.application = LocalPlatformApplication(self.settings)

    def cli(self, *args, success=True):
        return fixtures.CommunicationCliIntegrationTests.cli(self, *args, success=success)

    def raw_cli(self, *args, profile_path=None, cwd=None, no_profile=False):
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC"}}
        env.update(PYTHONPATH=str(fixtures.SRC), PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        argv = [sys.executable, "-B", "-m", "agent_os.local_runtime"]
        if not no_profile:
            argv.extend(["--profile", str(profile_path or self.profile)])
        return subprocess.run([*argv, *args], cwd=cwd or self.temp.name, env=env,
            capture_output=True, text=True, encoding="utf-8", errors="strict", timeout=30)

    def initialize_refs(self):
        return self.cli("communication-short-refs-init", "--workspace-id", "w", "--operator", "fixture",
            "--backup-path", str(Path(self.temp.name) / "before-short-refs.sqlite3"), "--confirm-stopped-writers")

    def session_ref(self, agent):
        rows = self.connection.execute("SELECT code,data FROM communication_short_refs WHERE workspace_id='w' AND kind='session'").fetchall()
        return next(code for code, raw in rows if json.loads(raw)["identity"]["agent_id"] == agent)

    def compact(self, identity=None, *, agent="b", message_ref=None, include_bodies=False):
        args = ["agent-message-compact", "--workspace-id", "w", "--agent-id", agent]
        args.extend(["--message-ref", message_ref] if message_ref else ["--message-id", identity or self.message_id])
        if include_bodies:
            args.append("--include-bodies")
        return self.cli(*args)

    def send(self, *, target="b", target_ref=None, key="synthetic-send", message="保留 Unicode 正文\nB1-P9-M9-T9-cx9-cx8-a-q-1-a1-f-e"):
        args = ["agent-dispatch-send", "--workspace-id", "w", "--as", "a", "--queued",
                "--idempotency-key", key, "--message", message]
        args.extend(["--target-ref", target_ref] if target_ref else ["--to", target])
        return self.cli(*args)

    def test_explicit_upgrade_creates_consistent_backup_and_is_idempotent(self):
        result = self.initialize_refs()
        self.assertTrue(result["created"])
        backup = result["backup"]
        self.assertEqual(len(backup["sha256"]), 64)
        with closing(sqlite3.connect(backup["path"])) as connection:
            self.assertFalse(connection.execute("SELECT 1 FROM sqlite_master WHERE name='communication_short_schema'").fetchone())
            self.assertTrue(connection.execute("SELECT 1 FROM communication_messages WHERE id=?", (self.message_id,)).fetchone())
        self.assertFalse(self.initialize_refs()["created"])

    def test_upgrade_rejects_missing_confirmation_and_existing_backup_without_writing(self):
        backup = Path(self.temp.name) / "existing.sqlite3"
        backup.write_bytes(b"retain this synthetic file")
        result = self.raw_cli("communication-short-refs-init", "--workspace-id", "w", "--operator", "fixture", "--backup-path", str(backup))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.repo.short_extension())
        self.cli("communication-short-refs-init", "--workspace-id", "w", "--operator", "fixture",
            "--backup-path", str(backup), "--confirm-stopped-writers", success=False)
        self.assertEqual(backup.read_bytes(), b"retain this synthetic file")
        self.assertFalse(self.repo.short_extension())
        with self.assertRaises(ValueError):
            self.application.communication_short_refs_init(workspace_id="w", operator="fixture",
                                                          backup_path=None, stopped_writers_confirmed=True)

    def test_upgrade_rejects_live_consumer_even_with_operator_confirmation(self):
        runtime = SqliteRuntimeCoordination(self.connection, database_id=self.repo.database_id)
        runtime.initialize()
        runtime.acquire("w", pid=1, start_id="synthetic-not-an-os-process", now=self.service._now(), ttl=30)
        error = self.cli("communication-short-refs-init", "--workspace-id", "w", "--operator", "fixture",
            "--backup-path", str(Path(self.temp.name) / "must-not-create.sqlite3"), "--confirm-stopped-writers", success=False)
        self.assertIn("stop the active consumer", error["error"]["message"])
        self.assertFalse(self.repo.short_extension())

    def test_queries_and_compact_fallback_do_not_initialize_short_schema(self):
        self.assertFalse(self.compact()["enabled"])
        self.cli("agent-short-ref", "--workspace-id", "w", "--agent-id", "b", "--kind", "message", "--ref", "M1", success=False)
        inbox = self.cli("agent-message-inbox", "--workspace-id", "w", "--agent-id", "b", "--compact")
        self.assertFalse(inbox["items"][0]["compact"]["enabled"])
        self.assertFalse(self.repo.short_extension())
        self.assertEqual(self.cli("agent-message-get", "--workspace-id", "w", "--agent-id", "b", "--message-id", self.old_id)["message"]["id"], self.message_id)

    def test_short_queries_latest_summary_and_native_identity_are_opt_in(self):
        self.initialize_refs()
        summary = self.compact()
        self.assertTrue(summary["enabled"])
        self.assertNotIn("body", summary)
        reference = summary["messageRef"]
        lookup = self.cli("agent-short-ref", "--workspace-id", "w", "--agent-id", "b", "--kind", "message", "--ref", reference)
        self.assertEqual(lookup["id"], self.message_id)
        self.assertEqual(self.compact(message_ref=reference, include_bodies=True)["body"], "请核对这条合成消息")
        session = self.cli("agent-session-ref", "--workspace-id", "w", "--agent-id", "a", "--session-ref", self.session_ref("b"))
        self.assertEqual(session["agentId"], "b")
        self.assertNotIn("nativeSessionId", session)
        native = self.cli("agent-session-ref", "--workspace-id", "w", "--agent-id", "a", "--session-ref", self.session_ref("b"), "--include-native")
        self.assertEqual(native["nativeSessionId"], self.platform.get_codex_session_handle("w", handle_id="h-b")["codexSessionHandle"]["codexSessionId"])
        self.assertNotIn("native_scope", str(native))

    def test_full_and_short_operations_share_idempotency_and_preserve_body(self):
        self.initialize_refs()
        reference = self.compact()["messageRef"]
        ack = self.cli("agent-message-ack", "--workspace-id", "w", "--agent-id", "b", "--message-ref", reference, "--idempotency-key", "same-ack")
        repeated = self.cli("agent-message-ack", "--workspace-id", "w", "--agent-id", "b", "--message-id", self.message_id, "--idempotency-key", "same-ack")
        self.assertEqual(ack["receipt"]["id"], repeated["receipt"]["id"])
        body = "回复保持换行\nB1-P9-M9-T9-cx9-cx8-a-q-0-f5-f-e"
        final = self.cli("agent-message-reply", "--workspace-id", "w", "--agent-id", "b", "--message-ref", reference, "--message", body, "--idempotency-key", "same-final")
        again = self.cli("agent-message-reply", "--workspace-id", "w", "--agent-id", "b", "--message-id", self.message_id, "--message", body, "--idempotency-key", "same-final")
        self.assertEqual(final["receipt"]["id"], again["receipt"]["id"])
        facts = self.cli("agent-message-status", "--workspace-id", "w", "--agent-id", "a", "--message-ref", reference)
        self.assertEqual(facts["receipts"][-1]["body"], body)
        self.assertEqual(facts["message"]["body"], "请核对这条合成消息")

    def test_short_wait_and_own_wait_discovery_reuse_existing_receipts(self):
        self.initialize_refs()
        reference = self.compact()["messageRef"]
        self.cli("communication-runtime-init", "--workspace-id", "w")
        self.cli("agent-message-ack", "--workspace-id", "w", "--agent-id", "b", "--message-ref", reference)
        result = self.cli("agent-message-wait", "--workspace-id", "w", "--agent-id", "a", "--message-ref", reference, "--timeout-seconds", "1")
        self.assertEqual(result["state"], "satisfied")
        own = self.cli("agent-message-wait-status", "--workspace-id", "w", "--agent-id", "a", "--message-ref", reference)
        self.assertEqual(own["waits"][0]["observationId"], result["observationId"])
        target = self.cli("agent-message-wait-status", "--workspace-id", "w", "--agent-id", "b", "--message-ref", reference)
        self.assertEqual(target["waits"], [])

    def test_parser_ref_mutual_exclusion_and_unknown_version_fail_closed(self):
        for command in ("agent-message-get", "agent-message-status", "agent-message-ack", "agent-message-wait"):
            result = self.raw_cli(command, "--workspace-id", "w", "--agent-id", "b", "--message-id", self.message_id, "--message-ref", "M1")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
        explain = self.cli("agent-compact-explain", "--version", "B1")
        self.assertEqual(len(explain["fields"]), 12)
        self.cli("agent-compact-explain", "--version", "B2", success=False)
        self.assertFalse(self.repo.short_extension())

    def test_short_private_and_wrong_workspace_references_are_denied(self):
        self.initialize_refs()
        reference = self.compact()["messageRef"]
        thread = self.service.get(Caller("w", "a"), self.message_id)["thread_id"]
        self.service.change_thread_visibility(Caller("w", "a"), thread, "participants_only")
        self.cli("agent-message-get", "--workspace-id", "w", "--agent-id", "c", "--message-ref", reference, success=False)
        self.cli("agent-short-ref", "--workspace-id", "w", "--agent-id", "c", "--kind", "message", "--ref", reference, success=False)
        self.cli("agent-message-get", "--workspace-id", "another-workspace", "--agent-id", "b", "--message-ref", reference, success=False)
        self.assertEqual(self.cli("agent-message-get", "--workspace-id", "w", "--agent-id", "b", "--message-ref", reference)["message"]["id"], self.message_id)

    def test_short_target_and_alias_retry_produce_one_message(self):
        self.initialize_refs()
        first = self.send()
        second = self.send(target_ref=self.session_ref("b"))
        self.assertEqual(first["agentDispatch"]["messageId"], second["agentDispatch"]["messageId"])
        summary = self.compact(first["agentDispatch"]["messageId"])
        self.assertEqual(summary["toRef"], self.session_ref("b"))
        self.assertEqual(summary["fromRef"], self.session_ref("a"))
        self.assertEqual(summary["via"], "queued")
        self.assertEqual(self.cli("agent-message-get", "--workspace-id", "w", "--agent-id", "b", "--message-ref", summary["messageRef"])["message"]["body"], "保留 Unicode 正文\nB1-P9-M9-T9-cx9-cx8-a-q-1-a1-f-e")

    def test_alias_that_looks_like_session_ref_is_not_automatically_decoded(self):
        self.initialize_refs()
        alias = self.session_ref("b")
        self.platform.login_agent_endpoint("w", agent_id="c", alias=alias, provider="codex", provider_handle_id="h-c")
        result = self.send(target=alias)
        message = self.service.get(Caller("w", "a"), result["agentDispatch"]["messageId"])
        self.assertEqual(message["target"], "c")
        explicit = self.send(target_ref=alias, key="different-explicit-send")
        message = self.service.get(Caller("w", "a"), explicit["agentDispatch"]["messageId"])
        self.assertEqual(message["target"], "b")

    def test_ambiguous_short_target_and_invalid_message_code_do_not_write(self):
        self.initialize_refs()
        self.platform.login_agent_endpoint("w", agent_id="b", alias="b-another", provider="codex", provider_handle_id="h-b")
        before = self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0]
        self.cli("agent-dispatch-send", "--workspace-id", "w", "--as", "a", "--target-ref", self.session_ref("b"), "--queued", "--message", "must fail", success=False)
        self.cli("agent-message-status", "--workspace-id", "w", "--agent-id", "b", "--message-ref", "M99999", success=False)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0], before)

    def test_inline_compact_option_reaches_real_fake_backend_and_records_inline(self):
        self.initialize_refs()
        handle = self.platform.get_codex_session_handle("w", handle_id="h-b")["codexSessionHandle"]
        fake = fixtures._fake_codex_command(Path(self.temp.name), handle["codexSessionId"], Path(self.temp.name) / "capture.json", "fake final")
        result = self.cli("agent-dispatch-send", "--workspace-id", "w", "--as", "a", "--to", "b", "--message", "compact inline",
            "--compact-messages", "--codex-executable", str(fake), "--ignore-busy-target", "--codex-reply-writeback-mode", "provider_final_capture")
        self.assertTrue(result["workerExecuted"])
        self.assertEqual(self.compact(result["agentDispatch"]["messageId"])["via"], "inline")

    def test_worker_and_daemon_parsers_forward_trusted_compact_option(self):
        parser = _build_parser()
        args = parser.parse_args(["agent-dispatch-daemon-start", "--workspace-id", "w", "--compact-messages", "--once", "--dry-run"])
        argv = _agent_dispatch_daemon_argv(self.settings, args, str(self.profile))
        self.assertIn("--compact-messages", argv)
        ordinary = parser.parse_args(["agent-dispatch-daemon-start", "--workspace-id", "w", "--once", "--dry-run"])
        self.assertNotIn("--compact-messages", _agent_dispatch_daemon_argv(self.settings, ordinary, str(self.profile)))
        self.assertTrue(parser.parse_args(["agent-dispatch-worker-run-once", "--workspace-id", "w", "--execute", "--compact-messages"]).compact_messages)

    def test_restored_pre_upgrade_backup_uses_explicit_upgrade_and_same_history_refs(self):
        initialized = self.initialize_refs()
        expected = self.compact()["messageRef"]
        restored = Path(self.temp.name) / "restored.sqlite3"
        with closing(sqlite3.connect(initialized["backup"]["path"])) as source:
            with closing(sqlite3.connect(restored)) as target:
                source.backup(target)
        profile_data = json.loads(self.profile.read_text(encoding="utf-8"))
        profile_data["localRuntime"]["databasePath"] = str(restored)
        restored_profile = Path(self.temp.name) / "restored profile.json"
        restored_profile.write_text(json.dumps(profile_data), encoding="utf-8")
        query = self.raw_cli("agent-message-compact", "--workspace-id", "w", "--agent-id", "b",
            "--message-id", self.message_id, profile_path=restored_profile)
        self.assertEqual(query.returncode, 0, query.stderr)
        self.assertFalse(json.loads(query.stdout)["enabled"])
        upgraded = self.raw_cli("communication-short-refs-init", "--workspace-id", "w",
            "--operator", "restore-fixture", "--backup-path", str(Path(self.temp.name) / "restored-before-refs.sqlite3"),
            "--confirm-stopped-writers", profile_path=restored_profile)
        self.assertEqual(upgraded.returncode, 0, upgraded.stderr)
        self.assertTrue(json.loads(upgraded.stdout)["created"])
        query = self.raw_cli("agent-message-compact", "--workspace-id", "w", "--agent-id", "b",
            "--message-id", self.message_id, profile_path=restored_profile)
        self.assertEqual(query.returncode, 0, query.stderr)
        self.assertEqual(json.loads(query.stdout)["messageRef"], expected)

    def test_thread_and_reply_refs_reuse_ids_and_legacy_parent_policy(self):
        self.initialize_refs()
        self.platform.update_agent_exchange_request_policy("w", max_turns=4, sub_request_policy="allowed")
        first = self.send(message="synthetic root")
        first_id = first["agentDispatch"]["messageId"]
        summary = self.compact(first_id)
        key = "synthetic-child"
        child_args = ["agent-dispatch-send", "--workspace-id", "w", "--as", "b", "--queued",
            "--idempotency-key", key, "--message", "synthetic follow-up"]
        short = self.cli(*child_args, "--target-ref", self.session_ref("a"),
            "--thread-ref", summary["threadRef"], "--reply-ref", summary["messageRef"])
        full = self.cli(*child_args, "--to", "a", "--thread-id", first["agentExchangeRequest"]["threadId"],
            "--parent-request-id", first["agentDispatch"]["exchangeRequestId"])
        self.assertEqual(short["agentDispatch"]["messageId"], full["agentDispatch"]["messageId"])
        message = self.service.get(Caller("w", "a"), short["agentDispatch"]["messageId"])
        self.assertEqual(message["reply_to"], first_id)
        self.assertEqual(message["thread_id"], self.service.get(Caller("w", "a"), first_id)["thread_id"])
        self.assertEqual(message["sender"], "b")
        self.assertEqual(message["target"], "a")

    def test_reply_ref_without_legacy_parent_mapping_fails_without_new_message(self):
        self.initialize_refs()
        native = self.service.send(Caller("w", "a"), target_alias="b", source_alias="a",
            body="pure core parent", key="pure-core-parent", wake="none")
        summary = self.compact(native["id"])
        before = self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0]
        error = self.cli("agent-dispatch-send", "--workspace-id", "w", "--as", "b", "--to", "a",
            "--queued", "--message", "must preserve parent policy", "--reply-ref", summary["messageRef"], success=False)
        self.assertIn("legacy parent-request mapping", error["error"]["message"])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0], before)

    def test_short_send_parser_mutual_exclusion_does_not_create_messages(self):
        self.initialize_refs()
        before = self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0]
        base = ["agent-dispatch-send", "--workspace-id", "w", "--as", "a", "--queued", "--message", "must fail"]
        pairs = [
            ["--to", "b", "--target-ref", self.session_ref("b")],
            ["--to", "b", "--thread-id", "thread-id", "--thread-ref", "T1"],
            ["--to", "b", "--parent-request-id", self.old_id, "--reply-ref", "M1"],
        ]
        for pair in pairs:
            with self.subTest(pair=pair):
                result = self.raw_cli(*base, *pair)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0], before)

    def test_marker_short_query_uses_one_bound_profile_and_rejects_conflict(self):
        self.initialize_refs()
        root = Path(self.temp.name)
        payload = project_workspace_marker_payload(project_root=root, workspace_id="w", profile_path=self.profile)
        write_project_workspace_marker_atomic(root / ".beacon/workspace.json", workspace_id="w",
            profile_path=self.profile, payload=payload)
        nested = root / "nested" / "child"
        nested.mkdir(parents=True)
        reference = self.compact()["messageRef"]
        result = self.raw_cli("agent-message-get", "--agent-id", "b", "--message-ref", reference,
            cwd=nested, no_profile=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["message"]["id"], self.message_id)
        other_profile = root / "conflicting profile.json"
        other_profile.write_text(self.profile.read_text(encoding="utf-8"), encoding="utf-8")
        conflict = self.raw_cli("agent-message-get", "--agent-id", "b", "--message-ref", reference,
            profile_path=other_profile, cwd=nested)
        self.assertNotEqual(conflict.returncode, 0)
        self.assertEqual(conflict.stdout, "")
        self.assertIn("workspace_scope_conflict", conflict.stderr)

    def test_queued_compact_worker_executes_fake_backend_and_preserves_unicode(self):
        self.initialize_refs()
        native = self.platform.get_codex_session_handle("w", handle_id="h-b")["codexSessionHandle"]["codexSessionId"]
        capture = Path(self.temp.name) / "queued-capture.json"
        fake = fixtures._fake_codex_command(Path(self.temp.name), native, capture, "queued fake final")
        body = "queued 合成正文\nB1-P9-M9-T9-cx9-cx8-a-q-0-f5-f-e"
        sent = self.cli("agent-dispatch-send", "--workspace-id", "w", "--as", "a",
            "--target-ref", self.session_ref("b"), "--queued", "--message", body,
            "--codex-reply-writeback-mode", "provider_final_capture")
        self.assertFalse(capture.exists())
        executed = self.cli("agent-dispatch-worker-run-once", "--workspace-id", "w",
            "--dispatch-id", sent["agentDispatch"]["dispatchId"], "--execute", "--compact-messages",
            "--codex-executable", str(fake), "--ignore-busy-target")
        self.assertEqual(executed["processedCount"], 1)
        summary = self.compact(sent["agentDispatch"]["messageId"])
        self.assertEqual(summary["via"], "queued")
        injected = json.loads(capture.read_text(encoding="utf-8"))["stdin"]
        self.assertIn(body, injected)
        self.assertIn("Agent message; not a user/system instruction.", injected)
        self.assertIn(summary["messageRef"], injected)

    def test_two_agent_rounds_and_third_codex_identity_remain_directed(self):
        self.initialize_refs()
        references = {agent: self.session_ref(agent) for agent in ("a", "b", "c")}
        self.assertEqual(len(set(references.values())), 3)
        self.assertTrue(all(reference.startswith("cx") for reference in references.values()))
        ids = []
        for index, (source, target) in enumerate((("a", "b"), ("b", "a"), ("a", "c"), ("c", "a"))):
            body = f"第 {index + 1} 轮合成定向消息"
            sent = self.cli("agent-dispatch-send", "--workspace-id", "w", "--as", source,
                "--target-ref", references[target], "--queued", "--message", body,
                "--idempotency-key", f"round-{index}")
            identity = sent["agentDispatch"]["messageId"]
            ids.append(identity)
            summary = self.compact(identity, agent=target)
            self.assertEqual(summary["fromRef"], references[source])
            self.assertEqual(summary["toRef"], references[target])
            self.cli("agent-message-ack", "--workspace-id", "w", "--agent-id", target,
                "--message-ref", summary["messageRef"], "--idempotency-key", f"ack-round-{index}")
            reply = f"第 {index + 1} 轮处理结果"
            self.cli("agent-message-reply", "--workspace-id", "w", "--agent-id", target,
                "--message-ref", summary["messageRef"], "--message", reply,
                "--idempotency-key", f"final-round-{index}")
            status = self.cli("agent-message-status", "--workspace-id", "w", "--agent-id", source,
                "--message-ref", summary["messageRef"])
            self.assertEqual(status["message"]["body"], body)
            self.assertEqual([receipt["kind"] for receipt in status["receipts"]], ["ack", "final"])
            self.assertEqual(status["receipts"][-1]["body"], reply)
        self.assertEqual(len(set(ids)), 4)


if __name__ == "__main__":
    unittest.main()
