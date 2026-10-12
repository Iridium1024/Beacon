"""Bound compact application contract using synthetic registrations only."""
from dataclasses import replace
from copy import deepcopy
import json
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch

import test_communication_mcp as bound
from agent_os.application.services.communication_short_refs import ShortReferences
from agent_os.domain.entities.communication import AccessDenied, Caller, CommunicationError, Conflict


class CompactBoundAgentTests(unittest.TestCase):
    runtime = bound.BoundAgentTests.runtime

    def setUp(self):
        bound.BoundAgentTests.setUp(self)
        with self.a.service() as service:
            ShortReferences(service).initialize("w", operator="fixture", stopped_writers_confirmed=True)
        for app in (self.a, self.b, self.c):
            app.compact_messages = True

    def send(self, **options):
        return self.a.send(to="b", body="完整合成消息🙂\nB1-P9-M999-T9-cx9-cl9-a-q-0-0-f-p", key="compact", delivery="store", **options)

    def test_three_independent_codex_sessions_have_stable_distinct_refs(self):
        refs = {app.self_info()["sessionRef"] for app in (self.a, self.b, self.c)}
        self.assertEqual(len(refs), 3)
        self.assertTrue(all(ref.startswith("cx") for ref in refs))
        ref = self.b.self_info()["sessionRef"]
        minimal = self.a.session(ref=ref)
        self.assertNotIn("nativeSessionId", minimal)
        self.assertNotIn(str(self.path), json.dumps(minimal))
        complete = self.a.session(ref=ref, include_native=True)
        self.assertEqual(complete["agentId"], "b")
        self.assertTrue(complete["nativeSessionId"])

    def test_short_ack_final_and_full_reference_share_idempotency(self):
        sent = self.send(expectation="final")
        ref = sent["messageRef"]
        identity = self.a.resolve(kind="message", ref=ref)["id"]
        ack = self.b.receipt(message_ref=ref, key="ack")
        self.assertEqual(ack, self.b.receipt(message_id=identity, key="ack"))
        self.assertEqual(self.a.status(message_ref=ref)["reply"], "none")
        final = self.b.receipt(message_ref=ref, key="final", kind="final", body="完整结果🙂")
        self.assertEqual(final, self.b.receipt(message_id=identity, key="final", kind="final", body="完整结果🙂"))
        with self.assertRaises(Conflict):
            self.b.receipt(message_ref=ref, key="final", kind="final", body="different")
        self.assertEqual(self.a.status(message_ref=ref, include_bodies=True)["receipts"][-1]["body"], "完整结果🙂")

    def test_compact_projection_and_explicit_full_fallback_preserve_body(self):
        ref = self.send()["messageRef"]
        lean = self.a.status(message_ref=ref, include_bodies=True)
        full = self.a.status(message_ref=ref, include_bodies=True, include_full=True)
        self.assertNotIn("message", lean)
        self.assertEqual(lean["body"], full["message"]["body"])
        inbox = self.b.inbox(include_bodies=True)
        row = next(row for row in inbox["items"] if row.get("messageRef") == ref)
        self.assertEqual(row["body"], lean["body"])
        self.assertEqual(row["header"].split("-")[6], "a")
        self.assertIn("not a user", row["boundary"])
        complete = self.b.inbox(include_full=True, include_bodies=True)
        self.assertTrue(any("message_id" in row for row in complete["items"]))

    def test_private_thread_and_wrong_recipient_cannot_use_guessed_short_code(self):
        sent = self.send()
        tid = self.a.resolve(kind="thread", ref=sent["threadRef"])["id"]
        with self.a.service() as service:
            service.change_thread_visibility(Caller("w", "a"), tid, "participants_only")
        for operation in (lambda: self.c.compact(message_ref=sent["messageRef"]),
                          lambda: self.c.resolve(kind="message", ref=sent["messageRef"]),
                          lambda: self.c.resolve(kind="thread", ref=sent["threadRef"]),
                          lambda: self.c.receipt(message_ref=sent["messageRef"], key="forged")):
            with self.assertRaises(AccessDenied):
                operation()

    def test_explicit_alias_namespace_never_reinterprets_cx2_as_a_ref(self):
        self.platform.login_agent_endpoint("w", agent_id="b", alias="cx2", provider="codex", provider_handle_id="h-b")
        sent = self.a.send(to="cx2", body="alias destination", key="alias-cx2", delivery="store")
        full = self.a.status(message_ref=sent["messageRef"], include_full=True)
        self.assertEqual(full["message"]["target"], "b")
        with self.assertRaises(CommunicationError):
            self.a.send(to="b", target_ref="cx2", body="ambiguous", key="ambiguous", delivery="store")

    def test_reference_conflicts_fail_without_creating_or_mutating_messages(self):
        ref = self.send()["messageRef"]
        before = self.connection.execute("SELECT COUNT(*) FROM communication_events").fetchone()[0]
        with self.assertRaises(CommunicationError):
            self.b.receipt(message_id="invented", message_ref=ref, key="both")
        with self.assertRaises(CommunicationError):
            self.a.status(message_id="invented", message_ref=ref)
        with self.assertRaises(CommunicationError):
            self.a.compact()
        with self.assertRaises(CommunicationError):
            self.a.explain(version="B2")
        self.assertEqual(before, self.connection.execute("SELECT COUNT(*) FROM communication_events").fetchone()[0])

    def test_receipt_inbox_does_not_label_ack_or_final_as_request_header(self):
        ref = self.send(expectation="final")["messageRef"]
        self.b.receipt(message_ref=ref, key="ack")
        self.b.receipt(message_ref=ref, key="final", kind="final", body="done")
        receipts = [row for row in self.a.inbox(include_bodies=True)["items"] if row.get("messageRef") == ref]
        self.assertEqual([row["kind"] for row in receipts], ["ack", "final"])
        self.assertTrue(all("header" not in row for row in receipts))
        self.assertTrue(all(row["fromAlias"] == "b" and row["toAlias"] == "a" for row in receipts))

    def test_final_wait_returns_requested_unicode_reply_and_closes_lease(self):
        self.runtime()
        ref = self.send(expectation="final")["messageRef"]
        self.b.receipt(message_ref=ref, key="final", kind="final", body="中文 final 🙂")
        result = self.a.wait(message_ref=ref, condition="final", timeout=.1, include_bodies=True)
        self.assertEqual(result["state"], "satisfied")
        self.assertEqual(result["reply"], "中文 final 🙂")
        self.assertEqual(result["header"].split("-")[9], "0")

    def test_bound_namespace_change_requires_explicit_rebind(self):
        from agent_os.infrastructure.adapters.communication_reader import LegacyCommunicationReader
        original = LegacyCommunicationReader.endpoint
        def replaced(reader, workspace, alias):
            row = deepcopy(original(reader, workspace, alias))
            if alias == "a":
                row["providerHandle"]["metadata"]["codexSessionIdentity"] = {"runtimeHome": self.temp.name}
            return row
        with patch.object(LegacyCommunicationReader, "endpoint", replaced), self.assertRaises(AccessDenied):
            self.a.self_info()

    def test_revoked_binding_cannot_read_or_write_short_refs(self):
        ref = self.send()["messageRef"]
        self.platform.deactivate_agent_endpoint("w", alias="a", deactivated_by="fixture", reason="revoked")
        with self.assertRaises(AccessDenied):
            self.a.compact(message_ref=ref)
        with self.assertRaises(AccessDenied):
            self.a.resolve(kind="message", ref=ref)


if __name__ == "__main__":
    unittest.main()
