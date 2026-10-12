"""Real optional SDK stdio connections, synthetic database and sibling consumer.

Without the optional extra only these integration tests are skipped. C2-A
acceptance explicitly requires an SDK-installed run with zero skips.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from uuid import uuid4

import test_communication_mcp as bound_tests
from agent_os.infrastructure.composition.communication_runtime import initialize_runtime, stop_runtime

SDK_AVAILABLE = importlib.util.find_spec("mcp") is not None
SRC = Path(__file__).resolve().parents[1]/"src"


@unittest.skipUnless(SDK_AVAILABLE, "optional MCP extra absent; not a C2-A acceptance run")
class McpStdioTests(unittest.IsolatedAsyncioTestCase):
    setUp = bound_tests.BoundAgentTests.setUp
    runtime = bound_tests.BoundAgentTests.runtime

    @asynccontextmanager
    async def client(self, agent="a", mode="auto", module="agent_os.communication_mcp", extra=(), extra_env=None):
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters
        env={k:v for k,v in os.environ.items() if k.upper() in {"PATH","SYSTEMROOT","WINDIR","TEMP","TMP","COMSPEC"}}
        env.update(PYTHONPATH=str(SRC)+os.pathsep+str(Path(__file__).parent),
                   PYTHONDONTWRITEBYTECODE="1",PYTHONIOENCODING="utf-8")
        env.update(extra_env or {})
        args=["-B","-m",module,"--profile",str(self.profile),"--agent",agent,*extra]
        # Explicit SDK stdio-client process launch includes its real Windows Job
        # Object ownership. Consumer is created by the test parent, not server.
        async with Client(StdioServerParameters(command=sys.executable,args=args,env=env,cwd=self.temp.name),
                          mode=mode,read_timeout_seconds=12) as connected:
            yield connected

    async def call(self, client, name, args=None, error=False):
        result=await client.call_tool(name,args or {})
        self.assertEqual(result.is_error,error,str(result.content))
        self.assertIsNotNone(result.structured_content)
        if error:
            return result.structured_content["error"]
        self.assertEqual(result.structured_content["schema"],"beacon.communication.mcp.v1")
        return result.structured_content["data"]

    async def poll(self, read, predicate, timeout=8):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            value=await read()
            if predicate(value):return value
            await asyncio.sleep(.03)
        self.fail("bounded synthetic poll timed out")

    def process_fact(self, role, pid, state, exit_code=None):
        evidence=os.environ.get("BEACON_TEST_PROCESS_EVIDENCE")
        if evidence:
            with Path(evidence).open("a",encoding="utf-8") as output:
                output.write(json.dumps({"test":self.id(),"role":role,"pid":pid,
                    "state":state,"exitCode":exit_code})+"\n")

    async def own_receiver_handle(self):
        async def trace():
            return json.loads(self.trace.read_text(encoding="utf-8")) if self.trace.exists() else {}
        row=await self.poll(trace,lambda value:value.get("state")=="acked")
        pid=row["pid"]
        self.process_fact("receiver",pid,"gated")
        if os.name!="nt":
            return
        import ctypes
        kernel=ctypes.windll.kernel32
        kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes=(ctypes.c_void_p,ctypes.c_uint)
        kernel.GetExitCodeProcess.argtypes=(ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint))
        kernel.CloseHandle.argtypes=(ctypes.c_void_p,)
        handle=kernel.OpenProcess(0x00101000,False,pid)
        self.assertTrue(handle)
        def cleanup():
            self.gate.touch()
            try:
                self.assertEqual(kernel.WaitForSingleObject(handle,6000),0,"owned receiver still alive")
                code=ctypes.c_uint()
                self.assertTrue(kernel.GetExitCodeProcess(handle,ctypes.byref(code)))
                self.assertEqual(code.value,0)
                self.process_fact("receiver",pid,"terminal",code.value)
            finally:
                kernel.CloseHandle(handle)
        self.addCleanup(cleanup)

    async def test_current_discovery_and_legacy_initialize_list_and_call(self):
        for mode,expected in (("auto","2026-07-28"),("legacy","2025-11-25")):
            async with self.client(mode=mode) as a:
                self.assertEqual(a.protocol_version,expected)
                tools=await a.list_tools()
                self.assertEqual({t.name for t in tools.tools},
                    {"self","peers","send","inbox","ack","reply","status","wait","cancel_wait",
                     "explain","resolve","session","compact"})
                self.assertTrue(all(t.input_schema.get("additionalProperties") is False for t in tools.tools))
                own=await self.call(a,"self")
                self.assertEqual(own["agentId"],"a")
                self.assertNotIn(str(self.path),json.dumps(own))
                peers=await self.call(a,"peers",{"limit":1})
                self.assertEqual(len(peers["peers"]),1)
                self.assertTrue(peers["hasMore"])

    async def test_two_agents_utf8_receipts_and_restart_retry(self):
        args={"to":"b","body":"跨 stdio 中文：请核查","key":"wire-stable","delivery":"store","expectation":"final"}
        async with self.client() as a, self.client("b") as b:
            first=await self.call(a,"send",args)
            mid=first["messageId"]
            inbox=await self.call(b,"inbox",{"include_bodies":True})
            self.assertEqual(next(x["body"] for x in inbox["items"] if x["message_id"]==mid),args["body"])
            before=await self.call(a,"status",{"message_id":mid})
            self.assertEqual(before["delivery"]["id"],first["deliveryId"])
            self.assertFalse(before["acknowledged"])
            ack=await self.call(b,"ack",{"message_id":mid,"key":"ack-wire"})
            self.assertEqual(ack,await self.call(b,"ack",{"message_id":mid,"key":"ack-wire"}))
            await self.call(b,"reply",{"message_id":mid,"key":"progress-wire","body":"checking","kind":"progress"})
            await self.call(b,"reply",{"message_id":mid,"key":"final-wire","body":"已完成"})
            status=await self.call(a,"status",{"message_id":mid,"include_bodies":True})
            self.assertEqual(status["receipts"][-1]["body"],"已完成")
            self.runtime()
            rejected=(await self.call(a,"send",{**args,"key":"wire-reject"}))["messageId"]
            await self.call(b,"reply",{"message_id":rejected,"body":"declined","key":"reject-wire","kind":"reject"})
            self.assertEqual((await self.call(a,"wait",{"message_id":rejected,"condition":"final","timeout":1}))["state"],"rejected")
        async with self.client() as again:
            self.assertEqual((await self.call(again,"send",args))["messageId"],mid)
            denied=await self.call(again,"send",{**args,"body":"changed"},error=True)
            self.assertEqual(denied["code"],"conflict")

    async def test_validation_authority_and_consumer_errors_do_not_write(self):
        async with self.client() as a:
            before=self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0]
            error=await self.call(a,"send",{"to":"b","body":"x","key":"bad","origin":"user"},error=True)
            self.assertEqual(error["code"],"invalid_argument")
            unavailable=await self.call(a,"send",{"to":"b","body":"x","key":"absent"},error=True)
            self.assertEqual(unavailable["code"],"consumer_unavailable")
            for timeout in (True,-1,121):
                result=await a.call_tool("wait",{"message_id":"x","timeout":timeout})
                self.assertTrue(result.is_error)
            self.assertEqual(before,self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0])
            for field,value in (("sender","b"),("workspace_id","foreign"),("capture","provider_final_capture"),
                                ("provider_executable","unexpected")):
                await self.call(a,"send",{"to":"b","body":"x","key":"bad-"+field,field:value},error=True)

    async def test_result_size_limit_preserves_full_body_on_smaller_page(self):
        self.platform.update_agent_exchange_request_policy("w",max_request_length=16000)
        for i in range(3):
            self.a.send(to="b",body="中"*16000,key="big"+str(i),delivery="store")
        async with self.client("b") as b:
            error=await self.call(b,"inbox",{"limit":20,"include_bodies":True},error=True)
            self.assertEqual(error["code"],"result_too_large")
            row=await self.call(b,"inbox",{"limit":1,"include_bodies":True})
            # First fixture message also occupies the inbox; advance its cursor.
            row=await self.call(b,"inbox",{"limit":1,"include_bodies":True,"cursor":row["cursor"]})
            self.assertEqual(row["items"][0]["body"],"中"*16000)

    async def test_wait_concurrency_explicit_cancel_and_rpc_cancel_release_leases(self):
        self.runtime()
        message=self.a.send(to="b",body="wait",key="w",delivery="store")
        mid=message["messageId"]
        async with self.client() as a:
            waiting=asyncio.create_task(self.call(a,"wait",{"message_id":mid,"condition":"final","timeout":5}))
            status=await self.poll(lambda:self.call(a,"status",{"message_id":mid}),
                lambda x:x.get("activeWaiterVerified"))
            obs=status["ownWaits"][0]["observationId"]
            cancelled=await self.call(a,"cancel_wait",{"observation_id":obs,"key":"cancel"})
            self.assertFalse(cancelled["executionCancelled"])
            self.assertEqual((await waiting)["state"],"cancelled")
            pending=asyncio.create_task(a.call_tool("wait",{"message_id":mid,"condition":"final","timeout":5}))
            await self.poll(lambda:self.call(a,"status",{"message_id":mid}),lambda x:x.get("activeWaiterVerified"))
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):await pending
            await self.poll(lambda:self.call(a,"status",{"message_id":mid}),lambda x:not x.get("activeWaiterVerified"))
            self.assertEqual((await self.call(a,"self"))["agentId"],"a")
        self.b.receipt(message_id=mid,key="after-cancel",kind="final",body="receiver remains independent")

    async def test_bounded_wait_pool_preserves_queries(self):
        self.runtime()
        mid=self.a.send(to="b",body="capacity",key="cap",delivery="store")["messageId"]
        async with self.client() as a:
            tasks=[asyncio.create_task(a.call_tool("wait",{"message_id":mid,"condition":"final","timeout":3})) for _ in range(2)]
            try:
                await self.poll(lambda:self.call(a,"status",{"message_id":mid}),
                    lambda x:len(x.get("verifiedWaiters",[]))==2)
                error=await self.call(a,"wait",{"message_id":mid,"condition":"final","timeout":3},error=True)
                self.assertEqual(error["code"],"busy")
                await self.call(a,"inbox")
                for obs in (await self.call(a,"status",{"message_id":mid}))["ownWaits"]:
                    await self.call(a,"cancel_wait",{"observation_id":obs["observationId"],"key":"cap-"+obs["observationId"]})
                for result in await asyncio.gather(*tasks):self.assertFalse(result.is_error)
            finally:
                for task in tasks:
                    if not task.done():task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)

    async def test_sdk_stdout_protection_handles_noisy_handler(self):
        async with self.client(module="fixtures.mcp_noise_entry") as a:
            self.assertEqual((await self.call(a,"self"))["agentId"],"a")
            self.assertEqual((await self.call(a,"self"))["agentId"],"a")

    async def start_consumer(self):
        initialize_runtime(self.settings,"w")
        self.trace=Path(self.temp.name)/"mcp-receiver-trace.json"
        self.gate=Path(self.temp.name)/"mcp-receiver-gate"
        self.platform.register_claude_session_handle("w",agent_id="c",handle_id="h-c-sdk",
            claude_session_uuid=str(uuid4()),cwd=self.temp.name,created_by="fixture",reason="fixture")
        self.platform.login_agent_endpoint("w",agent_id="c",alias="c-sdk",provider="claude",provider_handle_id="h-c-sdk")
        env={k:v for k,v in os.environ.items() if k.upper() in {"PATH","SYSTEMROOT","WINDIR","TEMP","TMP","COMSPEC"}}
        env.update(PYTHONPATH=str(SRC)+os.pathsep+str(Path(__file__).parent),PYTHONDONTWRITEBYTECODE="1",
            PYTHONIOENCODING="utf-8",BEACON_TEST_TRACE=str(self.trace),BEACON_TEST_GATE=str(self.gate))
        settings={**asdict(self.settings),"profile_path":str(self.profile)}
        proc=subprocess.Popen([sys.executable,"-B","-m","fixtures.runtime_supervisor_entry","--settings",json.dumps(settings)],
            cwd=self.temp.name,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        self.process_fact("consumer",proc.pid,"started")
        def cleanup():
            self.gate.touch()
            stop_runtime(self.settings,"w")
            try:proc.communicate(timeout=6)
            except subprocess.TimeoutExpired:
                proc.terminate();proc.communicate(timeout=5)
            self.assertIsNotNone(proc.poll())
            self.assertEqual(proc.returncode,0)
            self.process_fact("consumer",proc.pid,"terminal",proc.returncode)
        self.addCleanup(cleanup)
        async def query():return self.a.self_info()
        await self.poll(query,lambda x:x["consumer"]["state"]=="running")
        return proc

    async def test_real_sdk_job_cleanup_after_ack_preserves_sibling_execution(self):
        consumer=await self.start_consumer()
        async with self.client(extra=("--claude-backend","agent_sdk")) as a:
            sent=await self.call(a,"send",{"to":"c-sdk","body":"synthetic gated work","key":"life","expectation":"final"})
            mid=sent["messageId"]
            ack=await self.call(a,"wait",{"message_id":mid,"condition":"ack","timeout":10})
            self.assertEqual(ack["state"],"satisfied")
            await self.own_receiver_handle()
            self.assertEqual((await self.call(a,"status",{"message_id":mid}))["reply"],"none")
        self.assertIsNone(consumer.poll())
        self.gate.touch()
        async def query():return self.a.status(message_id=mid,include_bodies=True)
        final=await self.poll(query,lambda x:x.get("reply")=="final",timeout=10)
        self.assertEqual(final["receipts"][-1]["body"],"synthetic gated final")
        await self.poll(query,lambda x:x["delivery"]["execution"]=="finished",timeout=10)

    async def test_disconnect_during_final_wait_cleans_waiter_and_receiver_completes(self):
        from mcp import MCPError
        consumer=await self.start_consumer()
        async with self.client(extra=("--claude-backend","agent_sdk")) as a:
            mid=(await self.call(a,"send",{"to":"c-sdk","body":"disconnect pending","key":"disc"}))["messageId"]
            waiting=asyncio.create_task(a.call_tool("wait",{"message_id":mid,"condition":"final","timeout":10}))
            await self.poll(lambda:self.call(a,"status",{"message_id":mid}),lambda x:x.get("activeWaiterVerified"))
            await self.own_receiver_handle()
        try:
            result=await asyncio.wait_for(waiting,3)
            self.assertTrue(result.is_error)
        except MCPError:pass
        self.assertIsNone(consumer.poll())
        async def query():return self.a.status(message_id=mid)
        await self.poll(query,lambda x:not x["activeWaiterVerified"])
        self.gate.touch()
        await self.poll(query,lambda x:x["reply"]=="final" and x["delivery"]["execution"]=="finished",timeout=10)

    async def test_force_kill_uses_lease_expiry_and_preserves_receiver(self):
        from datetime import datetime,timedelta,timezone
        from mcp import MCPError
        from agent_os.domain.entities.communication import stamp
        await self.start_consumer()
        pidfile=Path(self.temp.name)/"mcp-owned-pid.json"
        async with self.client(module="fixtures.mcp_noise_entry",extra=("--claude-backend","agent_sdk"),
                               extra_env={"BEACON_TEST_MCP_PIDFILE":str(pidfile)}) as a:
            mid=(await self.call(a,"send",{"to":"c-sdk","body":"kill pending","key":"kill"}))["messageId"]
            waiting=asyncio.create_task(a.call_tool("wait",{"message_id":mid,"condition":"final","timeout":10}))
            await self.poll(lambda:self.call(a,"status",{"message_id":mid}),lambda x:x.get("activeWaiterVerified"))
            await self.own_receiver_handle()
            pid=json.loads(pidfile.read_text(encoding="utf-8"))["pid"]
            self.process_fact("mcp_server",pid,"started")
            if os.name=="nt":
                import ctypes
                kernel=ctypes.windll.kernel32
                kernel.OpenProcess.restype=ctypes.c_void_p
                handle=kernel.OpenProcess(0x00100001,False,pid)
                self.assertTrue(handle)
                kernel.TerminateProcess.argtypes=(ctypes.c_void_p,ctypes.c_uint)
                kernel.WaitForSingleObject.argtypes=(ctypes.c_void_p,ctypes.c_uint)
                kernel.CloseHandle.argtypes=(ctypes.c_void_p,)
                try:
                    self.assertTrue(kernel.TerminateProcess(handle,1))
                    self.assertEqual(kernel.WaitForSingleObject(handle,3000),0)
                    self.process_fact("mcp_server",pid,"terminal",1)
                finally:kernel.CloseHandle(handle)
            else:
                import signal
                os.kill(pid,signal.SIGKILL)
            try:
                result=await waiting
                self.assertTrue(result.is_error)
            except MCPError:pass
        with self.a.service() as service:
            future=stamp(datetime.now(timezone.utc)+timedelta(seconds=20))
            stale=service.coordination.waiters("w",mid,future)
            self.assertTrue(stale)
            self.assertTrue(all(row["state"]!="active" for row in stale))
        self.gate.touch()
        async def query():return self.a.status(message_id=mid)
        await self.poll(query,lambda x:x["reply"]=="final" and x["delivery"]["execution"]=="finished",timeout=10)


if __name__ == "__main__":unittest.main()
