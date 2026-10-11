"""Stable short identity representations in synthetic SQLite workspaces."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
from pathlib import Path
import sqlite3
import threading
import unittest
from unittest import mock
from uuid import uuid4

import test_communication_core as fixtures
from agent_os.application.services.communication_core import CommunicationService
from agent_os.application.services.communication_short_refs import ShortReferences, facts_from_handle, logical_identity
from agent_os.domain.entities.communication import AccessDenied, Caller, CommunicationError, Conflict, stamp
from agent_os.infrastructure.composition.local_platform import build_communication_directory, build_local_platform_operation_service
from agent_os.infrastructure.persistence.communication_store import SqliteCommunicationRepository


class ShortReferenceTests(unittest.TestCase):
    def setUp(self):
        fixtures.CommunicationCoreTests.setUp(self)
        self.native_a = str(uuid4())
        self.platform.register_codex_session_handle("w", agent_id="a", handle_id="handle-a",
            codex_session_id=self.native_a, cwd=self.temp.name, created_by="fixture", reason="offline")
        self.platform.login_agent_endpoint("w", agent_id="a", alias="a", provider="codex", provider_handle_id="handle-a")
        self.refs = ShortReferences(self.service)

    def enable(self):
        return self.refs.initialize("w", operator="synthetic-admin", stopped_writers_confirmed=True)

    def sync(self):
        with self.repo.transaction():
            return self.refs.sync_registration_history("w", "fixture", self.service._now())

    def source(self):
        result = self.directory.reader.endpoint("w", "a")
        return {**facts_from_handle(result["providerHandle"], "codex"), "alias": "a"}

    def send(self, *, body="合成消息", target="b", key=None, **options):
        options.setdefault("source_alias", "a")
        options.setdefault("source_handle_id", "handle-a")
        options.setdefault("reply_policy", "message_only")
        options.setdefault("delivery_path", "store" if options.get("wake") == "none" else "queued")
        return self.service.send(self.a, target_alias=target, body=body, key=key or str(uuid4()), **options)

    def session(self, alias):
        result = self.directory.reader.endpoint("w", alias)
        facts = facts_from_handle(result["providerHandle"], result["agentEndpoint"]["provider"])
        return self.repo.short_ref("w", "session", object_id=logical_identity(facts)["key"])

    def test_disabled_extension_preserves_core_schema_and_read_only_queries(self):
        before = self.repo.projection_snapshot()
        self.assertEqual(self.repo.schema_version, 2)
        self.assertFalse(self.refs.enabled("w"))
        self.assertIsNone(self.refs.context("w", "missing"))
        with self.assertRaises(CommunicationError):
            self.refs.resolve(self.a, "message", "M1")
        self.assertEqual(before, self.repo.projection_snapshot())
        self.assertFalse(self.connection.execute("SELECT 1 FROM sqlite_master WHERE name='communication_short_schema'").fetchone())
        self.send()
        self.assertFalse(self.refs.enabled("w"))

    def test_explicit_upgrade_confirmation_backup_and_repeat(self):
        with self.assertRaises(CommunicationError):
            self.refs.initialize("w", operator="fixture", stopped_writers_confirmed=False)
        self.assertFalse(self.refs.enabled("w"))
        backup = Path(self.temp.name) / "before.sqlite3"
        result = self.refs.initialize("w", operator="fixture", stopped_writers_confirmed=True, backup_path=str(backup))
        self.assertTrue(result["created"])
        self.assertTrue(backup.is_file())
        self.assertGreater(result["backup"]["bytes"], 0)
        with closing(sqlite3.connect(backup)) as restored:
            self.assertFalse(SqliteCommunicationRepository(restored).short_extension())
        snapshot, high = self.repo.projection_snapshot(), self.repo.high_water()
        self.assertFalse(self.refs.initialize("w", operator="fixture", stopped_writers_confirmed=True,
                                              backup_path=str(backup))["created"])
        self.assertEqual(snapshot, self.repo.projection_snapshot())
        self.assertEqual(high, self.repo.high_water())

    def test_restart_rebuild_and_post_upgrade_backup_restore_keep_numbers(self):
        self.enable()
        message = self.send(wake="none")
        context = self.refs.context("w", message["id"])
        snapshot = self.repo.projection_snapshot()
        self.repo.rebuild()
        self.assertEqual(snapshot, self.repo.projection_snapshot())
        backup = Path(self.temp.name) / "after.sqlite3"
        self.repo.short_reference_backup(str(backup))
        for path in (self.path, backup):
            with closing(sqlite3.connect(path)) as connection:
                service = CommunicationService(SqliteCommunicationRepository(connection), build_communication_directory(connection))
                refs = ShortReferences(service)
                self.assertEqual(context, refs.context("w", message["id"]))
                self.assertEqual(message["id"], refs.resolve(self.a, "message", context["message_ref"]))

    def test_trusted_registration_order_and_responsibility_distinguish_shared_native(self):
        native_b = self.directory.resolve("w", "b").native_session_id
        self.platform.register_codex_session_handle("w", agent_id="c", handle_id="shared-native",
            codex_session_id=native_b, cwd=self.temp.name, created_by="fixture", reason="separate responsibility")
        self.enable()
        rows = self.repo.workspace_items("short_refs", "w")
        sessions = sorted((row for row in rows if row["kind"] == "session"), key=lambda row: row["number"])
        self.assertEqual([row["provenance"]["sequence"] for row in sessions], sorted(row["provenance"]["sequence"] for row in sessions))
        matching = [row for row in sessions if row["identity"]["native_session_id"] == native_b]
        self.assertEqual({row["identity"]["agent_id"] for row in matching}, {"b", "c"})
        self.assertEqual(len({row["code"] for row in matching}), 2)
        self.assertEqual(self.session("b")["code"], "cx1")

    def test_alias_multiple_handles_and_generation_do_not_renumber(self):
        self.enable()
        original = self.session("a")["code"]
        self.platform.register_codex_session_handle("w", agent_id="a", handle_id="second-a",
            codex_session_id=self.native_a, cwd=self.temp.name, created_by="fixture", reason="same native",
            metadata={"runtimeBinding": {"generationId": "generation-2"}})
        self.platform.login_agent_endpoint("w", agent_id="a", alias="renamed-a", provider="codex", provider_handle_id="second-a")
        self.sync()
        self.assertEqual(self.session("renamed-a")["code"], original)
        self.assertEqual(self.session("a")["code"], original)
        lookup = self.refs.lookup_session(self.b, original, include_native=True)
        self.assertEqual(lookup["nativeSessionId"], self.native_a)
        self.assertEqual({row["alias"] for row in lookup["bindings"]}, {"a", "renamed-a"})
        self.assertEqual(next(row["generation"] for row in lookup["bindings"] if row["alias"] == "renamed-a"), "generation-2")

    def test_deactivation_reentry_and_native_replacement_keep_tombstones(self):
        self.enable()
        original = self.session("a")["code"]
        self.platform.deactivate_codex_session_handle("w", handle_id="handle-a", deactivated_by="fixture", reason="logout")
        self.sync()
        self.assertEqual(self.refs.lookup_session(self.b, original)["registration"], "tombstone")
        self.platform.register_codex_session_handle("w", agent_id="a", handle_id="handle-a",
            codex_session_id=self.native_a, cwd=self.temp.name, created_by="fixture", reason="same session reentry")
        self.sync()
        self.assertEqual(self.session("a")["code"], original)
        self.platform.deactivate_codex_session_handle("w", handle_id="handle-a", deactivated_by="fixture", reason="replace")
        self.platform.register_codex_session_handle("w", agent_id="a", handle_id="handle-a",
            codex_session_id=str(uuid4()), cwd=self.temp.name, created_by="fixture", reason="different session")
        self.sync()
        replacement = self.session("a")["code"]
        self.assertNotEqual(replacement, original)
        self.assertEqual(self.refs.lookup_session(self.b, original)["registration"], "tombstone")

    def test_native_scope_and_unknown_scope_are_distinct_without_environment_reads(self):
        homes = [str(Path(self.temp.name) / name) for name in ("home-one", "home-two")]
        for index, home in enumerate(homes):
            self.platform.register_hermes_session_handle("w", agent_id="d", handle_id=f"hermes-{index}",
                hermes_session_id="same-native", cwd=self.temp.name, created_by="fixture", reason="scoped native",
                metadata={"hermesSessionIdentity": {"runtimeHome": home}})
        self.platform.register_hermes_session_handle("w", agent_id="d", handle_id="hermes-unknown",
            hermes_session_id="same-native", cwd=self.temp.name, created_by="fixture", reason="missing scope")
        self.enable()
        rows = [row for row in self.repo.workspace_items("short_refs", "w") if row.get("identity", {}).get("provider") == "hermes"]
        self.assertEqual(len(rows), 3)
        self.assertEqual({row["code"] for row in rows}, {"he1", "he2", "he3"})
        self.assertIn(None, {row["identity"]["native_scope"] for row in rows})

    def test_windows_stored_scope_normalizes_but_native_id_remains_opaque(self):
        facts = {"agent_id": "a", "provider": "hermes", "native_session_id": "Native-ID", "native_scope": r"C:\HOME\folder\..\session"}
        second = {**facts, "native_scope": r"c:\home\session", "handle_id": "other", "generation": "next", "alias": "changed"}
        self.assertEqual(logical_identity(facts), logical_identity(second))
        self.assertNotEqual(logical_identity(facts), logical_identity({**second, "native_session_id": "native-id"}))
        self.assertNotEqual(logical_identity(facts), logical_identity({**second, "agent_id": "b"}))

    def test_existing_messages_backfill_source_unknown_without_current_alias_inference(self):
        first, second = self.send(wake="none"), self.send(wake="none")
        self.enable()
        contexts = [self.refs.context("w", message["id"]) for message in (first, second)]
        self.assertEqual([row["message_ref"] for row in contexts], ["M1", "M2"])
        self.assertTrue(all(row["from_ref"] is None and row["from_identity"] is None for row in contexts))
        target_before = contexts[0]["to_identity"]
        self.platform.deactivate_codex_session_handle("w", handle_id="handle-b", deactivated_by="fixture", reason="replace")
        self.platform.register_codex_session_handle("w", agent_id="b", handle_id="handle-b",
            codex_session_id=str(uuid4()), cwd=self.temp.name, created_by="fixture", reason="new native")
        self.sync()
        self.assertEqual(target_before, self.refs.context("w", first["id"])["to_identity"])

    def test_wrong_source_or_target_facts_cannot_become_context(self):
        self.enable()
        message = self.send(wake="none")
        clone = {**message, "id": "synthetic-uncommitted-message"}
        delivery = self.service._delivery(message)
        with self.assertRaises(AccessDenied), self.repo.transaction():
            self.refs.for_send(clone, delivery, {**self.source(), "agent_id": "c"}, via="store")
        self.assertIsNone(self.refs.context("w", clone["id"]))
        with self.assertRaises(AccessDenied), self.repo.transaction():
            bad = {**delivery, "binding": {**delivery["binding"], "agent_id": "c", "alias": None}}
            self.refs.for_send(clone, bad, self.source(), via="store")

    def test_concurrent_registration_sync_follows_actual_platform_sequence(self):
        self.enable()
        barrier = threading.Barrier(2)
        def register(index):
            connection = sqlite3.connect(self.path)
            try:
                platform = build_local_platform_operation_service(connection)
                platform.register_codex_session_handle("w", agent_id="d", handle_id=f"concurrent-{index}",
                    codex_session_id=f"concurrent-native-{index}", cwd=self.temp.name,
                    created_by="fixture", reason="concurrent fixture")
                barrier.wait(timeout=5)
                service = CommunicationService(SqliteCommunicationRepository(connection), build_communication_directory(connection))
                with service.repo.transaction():
                    ShortReferences(service).sync_registration_history("w", "fixture")
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(register, range(2)))
        rows = [row for row in self.repo.workspace_items("short_refs", "w") if row.get("identity", {}).get("agent_id") == "d"]
        self.assertEqual(len(rows), 2)
        rows.sort(key=lambda row: row["number"])
        self.assertLess(rows[0]["provenance"]["sequence"], rows[1]["provenance"]["sequence"])
        before = self.repo.projection_snapshot()
        self.sync()
        self.assertEqual(before, self.repo.projection_snapshot())

    def test_upgrade_and_context_faults_roll_back_every_projection(self):
        before = self.repo.projection_snapshot()
        self.repo.fault = lambda stage: (_ for _ in ()).throw(RuntimeError("synthetic failure")) if stage == "after_short_schema" else None
        with self.assertRaises(RuntimeError):
            self.enable()
        self.repo.fault = lambda stage: None
        self.assertFalse(self.repo.short_extension())
        self.assertEqual(before, self.repo.projection_snapshot())
        self.enable()
        message = self.send(wake="none")
        clone = {**message, "id": "rollback-message"}
        for fault in ("after_short_refs", "after_message_contexts", "before_commit"):
            before = self.repo.projection_snapshot()
            self.repo.fault = lambda stage, selected=fault: (_ for _ in ()).throw(RuntimeError("synthetic failure")) if stage == selected else None
            with self.assertRaises(RuntimeError), self.repo.transaction():
                changes = self.refs.for_send(clone, self.service._delivery(message), self.source(), via="store")
                self.repo.append("w", "a", "test_context", self.service._now(), changes)
            self.repo.fault = lambda stage: None
            self.assertEqual(before, self.repo.projection_snapshot())

    def test_projection_never_overwrites_short_identity_or_frozen_context(self):
        self.enable()
        message = self.send(wake="none")
        context = self.refs.context("w", message["id"])
        before = self.repo.projection_snapshot()
        with self.assertRaises(sqlite3.IntegrityError), self.repo.transaction():
            self.repo.append("w", "a", "test_overwrite", self.service._now(),
                             {"message_contexts": [{**context, "from_ref": "cx999"}]})
        self.assertEqual(before, self.repo.projection_snapshot())
        row = self.session("a")
        with self.assertRaises(sqlite3.IntegrityError), self.repo.transaction():
            self.repo.append("w", "a", "test_overwrite", self.service._now(),
                             {"short_refs": [{**row, "object_id": "different responsibility"}]})
        self.assertEqual(before, self.repo.projection_snapshot())

    def test_short_operations_keep_private_visibility_membership_and_wrong_recipient_rules(self):
        self.enable()
        message = self.send(wake="none", visibility="participants_only")
        code = self.refs.context("w", message["id"])["message_ref"]
        self.assertEqual(self.refs.resolve(self.a, "message", code), message["id"])
        self.assertEqual(self.refs.resolve(self.b, "message", code), message["id"])
        with self.assertRaises(AccessDenied):
            self.refs.resolve(self.c, "message", code)
        with self.assertRaises(AccessDenied):
            self.service.ack(self.c, message["id"], key="wrong-recipient")
        with mock.patch.object(self.directory.reader, "member_active", return_value=False):
            with self.assertRaises(AccessDenied):
                self.refs.resolve(self.a, "message", code)
            with self.assertRaises(AccessDenied):
                self.refs.lookup_session(self.a, self.session("b")["code"])

    def test_workspace_scope_and_native_visibility_are_bound_and_minimal(self):
        self.platform.create_workspace(workspace_id="other", display_name="Synthetic other", root_path=self.temp.name,
                                       agent_id="other-agent", agent_name="other", agent_description="fixture")
        self.enable()
        self.assertEqual(self.refs.resolve(self.a, "workspace", "P1"), "w")
        with self.assertRaises(AccessDenied):
            self.refs.resolve(self.a, "workspace", "P2")
        self.assertEqual(self.repo.short_ref("other", "workspace", object_id="other")["code"], "P2")
        code = self.session("b")["code"]
        normal = self.refs.lookup_session(self.a, code)
        full = self.refs.lookup_session(self.a, code, include_native=True)
        self.assertNotIn("nativeSessionId", normal)
        self.assertIn("nativeSessionId", full)
        self.assertNotIn("native_scope", full)
        self.assertNotIn("metadata", full)
        with self.assertRaises(CommunicationError):
            self.refs.lookup_session(Caller("other", "other-agent"), code)

    def test_invalid_reference_and_kind_are_rejected_without_guessing_alias(self):
        self.enable()
        for code in ("M0", "M01", "M-1", "M1-extra", "M1000000000000000", "M1' OR 1=1", "cx1", "T1"):
            with self.subTest(code=code), self.assertRaises(CommunicationError):
                self.refs.resolve(self.a, "message", code)
        with self.assertRaises(AccessDenied):
            self.refs.resolve(self.a, "message", "M999")
        with self.assertRaises(CommunicationError):
            self.refs.resolve(self.a, "session", "cx1")
        # An alias that resembles a short code remains ordinary directory input.
        self.platform.login_agent_endpoint("w", agent_id="b", alias="cx2", provider="codex", provider_handle_id="handle-b")
        self.assertEqual(self.directory.resolve("w", "cx2").agent_id, "b")

    def test_unknown_extension_version_fails_closed_without_mutation(self):
        self.enable()
        self.connection.execute("UPDATE communication_short_schema SET version=999")
        self.connection.commit()
        before = self.repo.high_water()
        with self.assertRaises(CommunicationError):
            self.refs.enabled("w")
        self.assertEqual(before, self.repo.high_water())

    def test_source_scope_generation_and_route_are_frozen_for_new_context(self):
        self.enable()
        message = self.send(wake="none")
        context = self.refs.context("w", message["id"])
        self.assertIsNotNone(context["from_ref"])
        self.assertEqual(context["from_binding"]["handle_id"], "handle-a")
        self.assertEqual(context["to_binding"]["handle_id"], "handle-b")
        self.assertEqual(context["from_identity"]["native_session_id"], self.native_a)
        self.assertEqual(context["via"], "store")
        self.assertEqual(self.service.get(self.a, message["id"])["body"], "合成消息")
        self.sync()
        self.assertEqual(context, self.refs.context("w", message["id"]))

    def test_unique_receiver_short_route_rejects_alias_ambiguity_and_tombstones(self):
        self.enable()
        own = self.session("a")["code"]
        self.assertEqual(self.refs.target_alias(self.b, own), "a")
        with self.assertRaises(Conflict):
            self.refs.target_alias(self.a, self.session("b")["code"])
        self.platform.deactivate_codex_session_handle("w", handle_id="handle-a", deactivated_by="fixture", reason="logout")
        self.sync()
        with self.assertRaises(Conflict):
            self.refs.target_alias(self.b, own)
        with self.assertRaises(AccessDenied):
            self.refs.target_alias(Caller("w", "unregistered"), own)

    def test_sender_only_short_identity_is_not_a_receiver_route(self):
        self.platform.register_codex_session_handle("w", agent_id="d", handle_id="sender-only",
            codex_session_id="sender-only-native", cwd=self.temp.name, created_by="fixture", reason="fixture")
        self.platform.login_agent_endpoint("w", agent_id="d", alias="sender-only", provider="codex",
                                           provider_handle_id="sender-only", direction="send_only")
        self.enable()
        code = self.session("sender-only")["code"]
        self.assertEqual(self.refs.lookup_session(self.a, code)["registration"], "active")
        with self.assertRaises(Conflict):
            self.refs.target_alias(self.a, code)

    def test_missing_registration_action_uses_marked_deterministic_fallback(self):
        history = self.directory.reader.registration_history("w")
        incomplete = [{**row, "action": None, "sequence": None} for row in reversed(history)]
        with mock.patch.object(self.directory.reader, "registration_history", return_value=incomplete):
            self.enable()
        sessions = sorted((row for row in self.repo.workspace_items("short_refs", "w") if row["kind"] == "session"),
                          key=lambda row: row["number"])
        self.assertEqual([row["object_id"] for row in sessions], sorted(row["object_id"] for row in sessions))
        self.assertTrue(all(row["provenance"]["order"] == "deterministic_identity_fallback" for row in sessions))
        original = {row["object_id"]: row["code"] for row in sessions}
        self.sync()
        self.assertEqual(original, {row["object_id"]: row["code"] for row in self.repo.workspace_items("short_refs", "w") if row["kind"] == "session"})

    def test_parallel_explicit_upgrade_has_one_effective_enable_event(self):
        barrier = threading.Barrier(2)
        def initialize(index):
            with closing(sqlite3.connect(self.path)) as connection:
                service = CommunicationService(SqliteCommunicationRepository(connection), build_communication_directory(connection))
                barrier.wait(timeout=5)
                return ShortReferences(service).initialize("w", operator=f"synthetic-{index}", stopped_writers_confirmed=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(initialize, range(2)))
        self.assertEqual(sum(row["created"] for row in results), 1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_events WHERE kind='short_references_enabled'").fetchone()[0], 1)
        self.assertEqual(len([row for row in self.repo.workspace_items("short_refs", "w") if row["kind"] == "session"]), 3)

    def test_all_provider_prefixes_and_dsh_generation_keep_persistent_identity(self):
        for handle_id, generation in (("dsh-one", "g1"), ("dsh-two", "g2")):
            self.platform.register_deepseek_harness_session_handle("w", agent_id="d", handle_id=handle_id,
                deepseek_harness_session_id="synthetic-persistent", cwd=self.temp.name, created_by="fixture", reason="fixture",
                metadata={"runtimeBinding": {"dshSessionId": "synthetic-persistent", "sessionRoot": self.temp.name,
                                             "generationId": generation, "runtimeId": "runtime-" + generation}})
            self.platform.login_agent_endpoint("w", agent_id="d", alias=handle_id, provider="deepseek_harness", provider_handle_id=handle_id)
        self.platform.register_claude_session_handle("w", agent_id="d", handle_id="claude-one", claude_session_uuid=str(uuid4()),
            cwd=self.temp.name, created_by="fixture", reason="fixture")
        self.platform.login_agent_endpoint("w", agent_id="d", alias="claude-one", provider="claude", provider_handle_id="claude-one")
        self.platform.register_hermes_session_handle("w", agent_id="d", handle_id="hermes-one", hermes_session_id="synthetic-hermes",
            cwd=self.temp.name, created_by="fixture", reason="fixture")
        self.platform.login_agent_endpoint("w", agent_id="d", alias="hermes-one", provider="hermes", provider_handle_id="hermes-one")
        self.enable()
        self.assertEqual(self.session("dsh-one")["code"], "ds1")
        self.assertEqual(self.session("dsh-two")["code"], "ds1")
        self.assertEqual(self.session("claude-one")["code"], "cl1")
        self.assertEqual(self.session("hermes-one")["code"], "he1")
        self.assertEqual(self.session("b")["code"], "cx1")
        lookup = self.refs.lookup_session(self.a, "ds1", include_native=True)
        self.assertEqual({row["generation"] for row in lookup["bindings"]}, {"g1", "g2"})
        self.assertEqual(lookup["nativeSessionId"], "synthetic-persistent")

    def test_owned_write_is_required_even_for_no_change_sync_and_target_assertion(self):
        self.enable()
        with self.assertRaises(CommunicationError):
            self.refs.sync_registration_history("w", "fixture")
        binding = self.directory.resolve("w", "a").to_dict()
        code = self.session("a")["code"]
        with self.assertRaises(CommunicationError):
            self.refs.assert_target_binding(self.b, code, binding)
        with self.repo.transaction():
            self.refs.assert_target_binding(self.b, code, binding)

    def test_full_and_short_same_key_retry_preserves_one_message_but_rebinding_is_rejected(self):
        self.enable()
        # a has one receiving alias; b intentionally has b and b-alt and cannot
        # be used as an unambiguous short target.
        code = self.session("a")["code"]
        arguments = dict(target_alias="a", body="stable body", key="stable-short-key", wake="none",
                         source_alias="b", source_handle_id="handle-b", target_handle_id="handle-a", reply_policy="message_only")
        first = self.service.send(self.b, **arguments)
        same = self.service.send(self.b, **arguments, target_session_ref=code)
        self.assertEqual(first["id"], same["id"])
        count = self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0]
        self.platform.deactivate_codex_session_handle("w", handle_id="handle-a", deactivated_by="fixture", reason="replace")
        self.platform.register_codex_session_handle("w", agent_id="a", handle_id="handle-a", codex_session_id=str(uuid4()),
            cwd=self.temp.name, created_by="fixture", reason="new native under same alias and handle")
        with self.assertRaises(Conflict):
            self.service.send(self.b, **arguments, target_session_ref=code)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0], count)

    def test_final_owned_send_rejects_alias_added_after_short_route_resolution(self):
        self.enable()
        code = self.session("a")["code"]
        selected = self.refs.target_alias(self.b, code)
        self.assertEqual(selected, "a")
        self.platform.login_agent_endpoint("w", agent_id="a", alias="a-new",
                                           provider="codex", provider_handle_id="handle-a")
        before = self.repo.projection_snapshot()
        with self.assertRaises(Conflict):
            self.service.send(self.b, target_alias=selected, target_session_ref=code,
                              body="must not route ambiguously", key="changed-alias", wake="none",
                              source_alias="b", source_handle_id="handle-b", reply_policy="message_only")
        self.assertEqual(before, self.repo.projection_snapshot())

    def test_owned_retry_rejects_new_alias_even_when_original_key_exists(self):
        self.enable()
        code = self.session("a")["code"]
        arguments = dict(target_alias="a", target_session_ref=code, body="stable",
                         key="existing-key", wake="none", source_alias="b", reply_policy="message_only")
        self.service.send(self.b, **arguments)
        self.platform.login_agent_endpoint("w", agent_id="a", alias="a-new", provider="codex",
                                           provider_handle_id="handle-a")
        before = self.repo.projection_snapshot()
        with self.assertRaises(Conflict):
            self.service.send(self.b, **arguments)
        self.assertEqual(before, self.repo.projection_snapshot())

    def test_new_source_without_explicit_alias_is_unknown_despite_current_handle(self):
        self.enable()
        message = self.service.send(self.a, target_alias="b", body="no source evidence",
                                    key="no-source", wake="none", delivery_path="store")
        context = self.refs.context("w", message["id"])
        self.assertIsNone(context["from_ref"])
        self.assertIsNone(context["from_identity"])
        self.assertIsNone(context["from_binding"])
        self.assertEqual(context["to_ref"], self.session("b")["code"])

    def historical_scoped_message(self):
        self.platform.deactivate_codex_session_handle("w", handle_id="handle-b", deactivated_by="fixture", reason="scope fixture")
        scope = str(Path(self.temp.name) / "historical-home")
        self.platform.register_codex_session_handle("w", agent_id="b", handle_id="handle-b",
            codex_session_id="scoped-native", cwd=self.temp.name, created_by="fixture", reason="scoped fixture",
            metadata={"codexSessionIdentity": {"runtimeHome": scope}})
        before = stamp(self.clock.now - timedelta(seconds=60))
        self.connection.execute("UPDATE platform_events SET occurred_at=?", (before,))
        self.connection.commit()
        return self.send(wake="none"), scope

    def test_historical_scope_uses_preexisting_registration_and_reuses_session_code(self):
        message, scope = self.historical_scoped_message()
        self.enable()
        context = self.refs.context("w", message["id"])
        self.assertEqual(context["to_identity"]["native_scope"], logical_identity({**self.source(), "native_scope": scope})["native_scope"])
        self.assertEqual(context["to_ref"], self.session("b")["code"])
        self.assertIsNone(context["from_ref"])
        matching = [row for row in self.repo.workspace_items("short_refs", "w") if row.get("identity", {}).get("native_session_id") == "scoped-native"]
        self.assertEqual(len(matching), 1)

    def test_later_registration_cannot_supply_missing_historical_scope(self):
        message, _ = self.historical_scoped_message()
        after = stamp(self.clock.now + timedelta(seconds=1))
        self.connection.execute("UPDATE platform_events SET occurred_at=? WHERE aggregate_type='codex_registered_session_handle'", (after,))
        self.connection.commit()
        self.enable()
        context = self.refs.context("w", message["id"])
        self.assertIsNone(context["to_identity"])
        self.assertIsNone(context["to_ref"])
        self.assertIsNotNone(self.session("b"))

    def test_missing_or_conflicting_history_is_unknown_not_current_alias_reinterpretation(self):
        message, scope = self.historical_scoped_message()
        history = self.directory.reader.registration_history("w")
        matching = [row for row in history if row.get("native_session_id") == "scoped-native" and row.get("action") == "registered"]
        self.assertEqual(len(matching), 1)
        row = matching[0]
        for replacement in (
            [{**row, "occurred_at": None}],
            [{**row, "sequence": None}],
            [row, {**row, "sequence": row["sequence"] + 100, "native_scope": scope + "-different"}],
        ):
            with self.subTest(history=replacement), mock.patch.object(self.directory.reader, "registration_history", return_value=replacement):
                self.assertIsNone(self.refs._historical_facts(self.service._delivery(message)["binding"], message))

    def test_foreign_database_codes_are_local_namespaces_not_global_identifiers(self):
        self.enable()
        local = self.send(wake="none")
        other = ShortReferenceTests()
        other.setUp()
        try:
            other.enable()
            foreign = other.send(wake="none")
            self.assertNotEqual(self.repo.database_id, other.repo.database_id)
            self.assertEqual(self.refs.context("w", local["id"])["message_ref"], "M1")
            self.assertEqual(other.refs.context("w", foreign["id"])["message_ref"], "M1")
            self.assertEqual(self.refs.resolve(self.a, "message", "M1"), local["id"])
            self.assertEqual(other.refs.resolve(other.a, "message", "M1"), foreign["id"])
            with self.assertRaises(AccessDenied):
                self.service.get(self.a, foreign["id"])
        finally:
            other.doCleanups()


if __name__ == "__main__":
    unittest.main()
