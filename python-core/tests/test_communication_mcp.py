"""Bound application and optional transport tests; synthetic registrations only."""
import asyncio
import ast
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
import json
import math
from pathlib import Path
import sys
from threading import Event, Thread
import time
import unittest
from unittest import mock
from uuid import uuid4

import test_communication_integration as fixtures
from agent_os.domain.entities.communication import AccessDenied, Caller, CommunicationError, Conflict
from agent_os.infrastructure.composition.communication_agent import bind_communication, load_bound_settings
from agent_os.infrastructure.composition.communication_runtime import prepared_runtime, initialize_runtime
from agent_os.infrastructure.config import LocalPlatformSettings


class BoundAgentTests(unittest.TestCase):
    def setUp(self):
        fixtures.CommunicationCliIntegrationTests.setUp(self)
        for agent in ("a", "c"):
            self.platform.register_codex_session_handle("w", agent_id=agent, handle_id="h-"+agent,
                codex_session_id=str(uuid4()), cwd=self.temp.name, created_by="fixture", reason="fixture")
            self.platform.login_agent_endpoint("w", agent_id=agent, alias=agent, provider="codex",
                                               provider_handle_id="h-"+agent)
        fixtures.CommunicationCliIntegrationTests.migrate_request(self)
        self.settings = LocalPlatformSettings(str(self.path), self.temp.name, self.temp.name, initialize_schema=False)
        self.a = bind_communication(self.settings, "w", "a")
        self.b = bind_communication(self.settings, "w", "b")
        self.c = bind_communication(self.settings, "w", "c")

    def runtime(self):
        initialize_runtime(self.settings, "w")
        with prepared_runtime(self.settings, "w") as (_, service):
            return service.coordination.acquire("w", pid=123, start_id="synthetic", now=service._now(), ttl=30)

    def send(self, **options):
        return self.a.send(to="b", body="合成消息", key=str(uuid4()), delivery="store", **options)

    def test_stored_send_idempotency_inbox_ack_reply_and_metadata(self):
        args=dict(to="b", body="合成消息", key="stable", delivery="store", expectation="final")
        first=self.a.send(**args)
        self.assertEqual(first["messageId"], self.a.send(**args)["messageId"])
        self.assertEqual(first["schedule"], "none")
        self.assertEqual(first["capture"], "explicit_only")
        self.assertEqual(first["authority"], "agent")
        with self.assertRaises(Conflict):
            self.a.send(**{**args, "body":"different"})
        inbox=self.b.inbox(include_bodies=True)
        self.assertEqual(next(row["body"] for row in inbox["items"] if row["message_id"]==first["messageId"]), "合成消息")
        compact=self.a.status(message_id=first["messageId"])
        self.assertNotIn("body",compact["message"])
        self.assertEqual(compact["delivery"]["id"],first["deliveryId"])
        ack=self.b.receipt(message_id=first["messageId"],key="ack")
        self.assertEqual(ack,self.b.receipt(message_id=first["messageId"],key="ack"))
        self.b.receipt(message_id=first["messageId"],key="final",kind="final",body="处理完成")
        full=self.a.status(message_id=first["messageId"],include_bodies=True)
        self.assertEqual(full["reply"],"final")
        self.assertEqual(full["receipts"][-1]["body"],"处理完成")
        self.assertNotIn("body",self.a.status(message_id=first["messageId"])["receipts"][-1])

    def test_queued_consumer_guard_is_atomic_and_retry_recovers_after_consumer_stops(self):
        before=self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0]
        with self.assertRaisesRegex(CommunicationError,"consumer_unavailable"):
            self.a.send(to="b",body="queue",key="q")
        self.assertEqual(before,self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0])
        self.runtime()
        first=self.a.send(to="b",body="queue",key="q")
        with prepared_runtime(self.settings,"w") as (_,service):
            service.coordination.request_stop("w",service._now())
        self.assertEqual(self.a.send(to="b",body="queue",key="q")["messageId"],first["messageId"])

    def test_caller_binding_and_private_visibility_cannot_be_forged(self):
        with self.assertRaises(AccessDenied):
            bind_communication(self.settings,"w","a",alias="b")
        message=self.send()
        with self.a.service() as service:
            service.change_thread_visibility(Caller("w","a"),message["threadId"],"participants_only")
        with self.assertRaises(AccessDenied):
            self.c.status(message_id=message["messageId"])
        with self.assertRaises(AccessDenied):
            self.c.receipt(message_id=message["messageId"],key="wrong")
        self.runtime()
        with self.assertRaises(AccessDenied):
            self.c.wait(message_id=message["messageId"],timeout=.01)

    def test_budget_and_subrequest_policy_are_shared_with_existing_cli(self):
        self.platform.update_agent_exchange_request_policy("w",max_turns=-1)
        with self.assertRaisesRegex(ValueError,"disables request"):
            self.send()

    def test_followup_goes_through_compatible_parent_mapping(self):
        first=self.send()
        follow=self.send(reply_to=first["messageId"])
        self.assertEqual(follow["threadId"],first["threadId"])
        with self.a.service() as service:
            row=service.get(Caller("w","a"),follow["messageId"])
            self.assertIsNotNone(row["legacy_parent_request_id"])
        self.platform.update_agent_exchange_request_policy("w",sub_request_policy="disabled")
        with self.assertRaisesRegex(ValueError,"sub request"):
            self.send(reply_to=first["messageId"])

    def test_ack_wait_returns_without_final_and_closes_lease(self):
        self.runtime()
        message=self.send()
        self.b.receipt(message_id=message["messageId"],key="ack")
        waited=self.a.wait(message_id=message["messageId"],condition="ack",timeout=.1)
        self.assertEqual(waited["state"],"satisfied")
        self.assertEqual(self.a.status(message_id=message["messageId"])["reply"],"none")

    def test_thread_cancellation_closes_waiter_without_execution_cancel(self):
        self.runtime()
        message=self.send()
        cancelled=Event()
        output=[]
        thread=Thread(target=lambda:output.append(self.a.wait(message_id=message["messageId"],timeout=5,
                                                              cancelled=cancelled.is_set)))
        thread.start()
        try:
            end=time.monotonic()+3
            while time.monotonic()<end and not self.a.status(message_id=message["messageId"])["ownWaits"]:
                time.sleep(.02)
            cancelled.set()
            thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(output[0]["state"],"cancelled")
            with self.a.service() as service:
                self.assertFalse(service.status(Caller("w","a"),message["messageId"])["active_waiter_verified"])
            self.b.receipt(message_id=message["messageId"],key="f",kind="final",body="continued")
        finally:
            cancelled.set()
            thread.join(3)

    def test_invalid_wait_values_and_unavailable_consumer(self):
        message=self.send()
        for value in (True,0,-1,float('nan'),float('inf'),121,"1"):
            with self.subTest(value=value),self.assertRaises(CommunicationError):
                self.a.wait(message_id=message["messageId"],timeout=value)
        initialize_runtime(self.settings,"w")
        # Observe availability before the observation deadline can expire on
        # SQLite creation/read I/O. Deadline precedence has separate coverage.
        self.assertEqual(self.a.wait(message_id=message["messageId"],timeout=1)["state"],"consumer_unavailable")

    def test_peers_is_bounded_and_status_excludes_native_configuration(self):
        page=self.a.peers(limit=1)
        self.assertTrue(page["hasMore"])
        self.assertEqual(self.a.peers(after=page["nextAfter"],limit=1)["peers"][0]["alias"],"c")
        self.assertNotIn("native",json.dumps(self.a.self_info()))
        self.assertNotIn(str(self.path),json.dumps(self.a.self_info()))

    def test_no_compatibility_adapter_fails_closed(self):
        from agent_os.application.services.communication_agent import AgentCommunication
        @contextmanager
        def opened():
            with self.a.service() as service:
                service.send_compatibility=None
                yield service
        app=AgentCommunication(self.a.binding,opened,backend_policy=lambda p:(None,"explicit_only"))
        with self.assertRaisesRegex(CommunicationError,"compatibility"):
            app.send(to="b",body="not bypassed",key="x",delivery="store")

    def test_profile_scope_conflict_and_missing_database_do_not_create_files(self):
        selected,workspace=load_bound_settings(profile=str(self.profile),start=self.temp.name)
        self.assertEqual(workspace,"w")
        with self.assertRaisesRegex(CommunicationError,"conflict"):
            load_bound_settings(profile=str(self.profile),start=self.temp.name,workspace_id="other")
        marker=Path(self.temp.name)/".beacon"/"workspace.json"
        marker.parent.mkdir()
        marker.write_text(json.dumps({"schema":"beacon_project_workspace.v1",
            "workspaceId":"w","profilePath":str(self.profile)}),encoding="utf-8")
        discovered,workspace=load_bound_settings(start=self.temp.name)
        self.assertEqual(discovered.database,selected.database)
        self.assertEqual(workspace,"w")
        with self.assertRaisesRegex(ValueError,"workspace_scope_conflict"):
            load_bound_settings(profile=str(Path(self.temp.name)/"other.json"),start=self.temp.name)
        marker.write_text(json.dumps({"schema":"beacon_project_workspace.v1",
            "workspaceId":"foreign","profilePath":str(self.profile)}),encoding="utf-8")
        with self.assertRaisesRegex(CommunicationError,"conflict"):
            load_bound_settings(start=self.temp.name)
        missing=Path(self.temp.name)/"missing.sqlite3"
        with self.assertRaisesRegex(CommunicationError,"does not exist"):
            bind_communication(replace(selected,database=str(missing)),"w","a")
        self.assertFalse(missing.exists())

    def test_revoked_endpoint_and_cross_workspace_binding_fail_closed(self):
        self.platform.deactivate_agent_endpoint("w",alias="a",deactivated_by="fixture",reason="revoked")
        with self.assertRaises(AccessDenied):
            self.a.self_info()
        with self.assertRaisesRegex(CommunicationError,"migrated core workspace"):
            bind_communication(self.settings,"foreign","a")

    def test_delegated_policy_and_response_budget_cannot_be_bypassed(self):
        self.platform.update_agent_exchange_request_policy("w",max_response_length=5)
        sent=self.send()
        with self.assertRaisesRegex(CommunicationError,"maximum response"):
            self.b.receipt(message_id=sent["messageId"],key="too-long",kind="final",body="too long")
        self.platform.update_agent_exchange_request_policy("w",authorization_mode="delegated_grant_required")
        with self.assertRaises((AccessDenied,ValueError)):
            self.send()
        with self.assertRaises((AccessDenied,ValueError)):
            self.send(grant_id="invented-grant")

    def test_permission_revocation_during_wait_closes_capability_owned_lease(self):
        from agent_os.infrastructure.adapters.communication_reader import LegacyCommunicationReader
        self.runtime()
        mid=self.send()["messageId"]
        withdrawn=Event();output=[]
        original=LegacyCommunicationReader.member_active
        def active(reader,caller):
            return False if withdrawn.is_set() and caller.agent_id=="a" else original(reader,caller)
        def run():
            try:self.a.wait(message_id=mid,condition="final",timeout=3)
            except Exception as exc:output.append(exc)
        with mock.patch.object(LegacyCommunicationReader,"member_active",active):
            thread=Thread(target=run);thread.start()
            try:
                end=time.monotonic()+2
                while time.monotonic()<end and not self.a.status(message_id=mid).get("activeWaiterVerified"):
                    time.sleep(.02)
                self.assertTrue(self.a.status(message_id=mid)["activeWaiterVerified"])
                withdrawn.set();thread.join(3)
                self.assertFalse(thread.is_alive())
                self.assertIsInstance(output[0],AccessDenied)
            finally:
                withdrawn.set();thread.join(3)
        self.assertFalse(self.a.status(message_id=mid)["activeWaiterVerified"])

    def test_new_application_and_transport_preserve_dependency_boundaries(self):
        src=Path(__file__).resolve().parents[1]/"src/agent_os"
        for relative in ("application/services/communication_agent.py","application/services/communication_wait.py"):
            tree=ast.parse((src/relative).read_text(encoding="utf-8"))
            imports=[n.module or "" for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
            imports += [alias.name for n in ast.walk(tree) if isinstance(n,ast.Import) for alias in n.names]
            self.assertFalse(any(name.startswith(("mcp","sqlite3","agent_os.infrastructure","agent_os.local_runtime")) for name in imports))
        text=(src/"communication_mcp.py").read_text(encoding="utf-8")
        self.assertNotIn("sqlite3",text)
        self.assertNotIn("subprocess",text)


if __name__ == "__main__":
    unittest.main()
