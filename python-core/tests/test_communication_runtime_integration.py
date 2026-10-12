"""Real independent sender/consumer/receiver processes; isolated provider fixtures."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from uuid import uuid4

import test_communication_integration as fixtures
from agent_os.infrastructure.config import LocalPlatformSettings
from test_codex_registered_session_activation import _fake_codex_command


class CommunicationRuntimeIntegrationTests(unittest.TestCase):
    def setUp(self):
        fixtures.CommunicationCliIntegrationTests.setUp(self)
        self.profile.write_text(json.dumps({"localRuntime": {"workspaceId": "w", "databasePath": str(self.path),
            "workspaceRoot": self.temp.name, "pluginsDirectory": self.temp.name}}), encoding="utf-8")
        fixtures.CommunicationCliIntegrationTests.migrate_request(self)
        self.env = {key: value for key, value in os.environ.items()
                    if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC"}}
        test_path = Path(__file__).parent
        self.env.update(PYTHONPATH=str(fixtures.SRC) + os.pathsep + str(test_path),
                        PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8",
                        CODEX_HOME=self.temp.name, HOME=self.temp.name, USERPROFILE=self.temp.name)
        self.trace = Path(self.temp.name)/"receiver-trace.json"
        self.gate = Path(self.temp.name)/"receiver-gate"
        self.children = []
        self.addCleanup(self.clean_processes)

    def cli(self, *args, success=True):
        return fixtures.CommunicationCliIntegrationTests.cli(self, *args, success=success)

    def poll(self, read, predicate, timeout=12):
        end = time.monotonic() + timeout
        last = None
        while time.monotonic() < end:
            last = read()
            if predicate(last):
                return last
            time.sleep(.03)
        self.fail(f"bounded poll timed out: {last}")

    def spawn(self, argv):
        process = subprocess.Popen(argv, cwd=self.temp.name, env=self.env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        self.children.append(process)
        return process

    def clean_processes(self):
        self.gate.touch()
        for process in self.children:
            if process.poll() is None:
                # Let the consumer drain known activations before terminating
                # its root handle. This never targets any user's runtime.
                try:self.cli('communication-runtime-stop','--workspace-id','w')
                except Exception:pass
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.communicate(timeout=5)
        from fixtures.runtime_audit import record
        record(self,self.children)

    def command(self, *args):
        return [sys.executable, "-B", "-m", "agent_os.local_runtime", "--profile", str(self.profile), *args]

    def status(self, message_id):
        return self.cli("agent-message-status", "--workspace-id", "w", "--agent-id", "a", "--message-id", message_id)

    def consumer(self, *, sdk=False):
        self.cli("communication-runtime-init", "--workspace-id", "w")
        if sdk:
            self.env.update(BEACON_TEST_TRACE=str(self.trace), BEACON_TEST_GATE=str(self.gate))
            settings = {"database": str(self.path), "workspace_root": self.temp.name,
                        "plugins_directory": self.temp.name, "profile_path": str(self.profile), "initialize_schema": False}
            child = self.spawn([sys.executable,"-B","-m","fixtures.runtime_supervisor_entry","--settings",json.dumps(settings)])
        else:
            command = _fake_codex_command(Path(self.temp.name), str(uuid4()), Path(self.temp.name)/"unused", "fake")
            if os.name == "nt":
                command.write_text(command.read_text(encoding="utf-8").replace("@echo off", "@echo off\nchcp 65001 >nul"), encoding="utf-8")
            script = Path(self.temp.name)/"fake_codex.py"
            script.write_text("import sys\nsys.path.insert(0," + repr(str(Path(__file__).parent)) + ")\n"
                "from fixtures.fake_runtime_receiver import main\nmain("+repr(str(self.trace))+","+repr(str(self.gate))+")\n", encoding="utf-8")
            child = self.spawn([sys.executable,"-B","-m","agent_os.agent_dispatch_daemon","--profile",str(self.profile),
                "--workspace-id","w","--ignore-busy-target","--codex-executable",str(command),
                "--poll-interval-ms","50","--heartbeat-interval-ms","100","--consumer-lease-seconds","5",
                "--lease-ttl-seconds","3","--activation-timeout-seconds","15","--shutdown-timeout-seconds","2"])
        self.poll(lambda:self.cli("communication-runtime-status","--workspace-id","w"), lambda row:row["state"] == "running")
        return child

    def assert_ack_exit_then_final(self, *, target="b", backend_args=()):
        sender = self.spawn(self.command("agent-dispatch-send","--workspace-id","w","--source-agent-id","a",
            "--target-agent-id",target,"--reply-policy","message_only","--message","synthetic gated work",
            "--wait","ack","--wait-timeout-seconds","10",*backend_args))
        stdout, stderr = sender.communicate(timeout=12)
        self.assertEqual(sender.returncode,0,stderr)
        result = json.loads(stdout)
        self.assertEqual(result["state"],"satisfied",result)
        identity = result["messageId"]
        self.assertEqual(self.status(identity)["reply"],"none")
        self.poll(lambda:json.loads(self.trace.read_text(encoding='utf-8')) if self.trace.exists() else None,
            lambda row:row is not None and row['state']=='acked')
        self.gate.touch()
        final = self.poll(lambda:self.status(identity),lambda row:row["reply"] == "final")
        self.assertEqual(final["receipts"][-1]["body"],"synthetic gated final")
        self.assertEqual(self.poll(lambda:self.status(identity),lambda row:row["delivery"]["execution"] == "finished")["delivery"]["schedule"],"done")
        return identity

    def test_sender_ack_returns_and_exits_while_cli_receiver_continues_final(self):
        consumer = self.consumer()
        self.assert_ack_exit_then_final()
        self.cli("communication-runtime-stop","--workspace-id","w")
        stdout, stderr = consumer.communicate(timeout=6)
        self.assertEqual(consumer.returncode,0,stderr)

    def test_child_sdk_fixture_is_assembled_after_spawn_and_continues_after_sender_exit(self):
        self.platform.register_claude_session_handle("w",agent_id="c",handle_id="h-c-sdk",
            claude_session_uuid=str(uuid4()),cwd=self.temp.name,created_by="fixture",reason="fixture")
        self.platform.login_agent_endpoint("w",agent_id="c",alias="c",provider="claude",provider_handle_id="h-c-sdk")
        consumer = self.consumer(sdk=True)
        self.assert_ack_exit_then_final(target="c",backend_args=("--claude-activation-backend","agent_sdk"))
        self.cli("communication-runtime-stop","--workspace-id","w")
        _, stderr = consumer.communicate(timeout=6)
        self.assertEqual(consumer.returncode,0,stderr)

    def test_new_wait_without_consumer_has_no_message_or_runtime_initialization(self):
        before = self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0]
        error = self.cli("agent-dispatch-send","--workspace-id","w","--source-agent-id","a",
            "--target-agent-id","b","--reply-policy","message_only","--message","synthetic",
            "--wait","ack",success=False)
        self.assertIn("consumer_unavailable",str(error))
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0],before)
        self.assertFalse(self.connection.execute("SELECT name FROM sqlite_master WHERE name='communication_runtime_schema'").fetchone())

    def test_consumer_process_death_restart_keeps_old_live_child_fenced_and_queryable(self):
        self.platform.register_claude_session_handle('w',agent_id='c',handle_id='h-c-sdk',
            claude_session_uuid=str(uuid4()),cwd=self.temp.name,created_by='fixture',reason='fixture')
        self.platform.login_agent_endpoint('w',agent_id='c',alias='c',provider='claude',provider_handle_id='h-c-sdk')
        first = self.consumer(sdk=True)
        sender = self.spawn(self.command('agent-dispatch-send','--workspace-id','w','--source-agent-id','a',
            '--target-agent-id','c','--reply-policy','message_only','--message','synthetic restart',
            '--wait','ack','--wait-timeout-seconds','10','--claude-activation-backend','agent_sdk'))
        out,err=sender.communicate(timeout=12)
        self.assertEqual(sender.returncode,0,err)
        message=json.loads(out)['messageId']
        identity=json.loads(self.connection.execute('SELECT data FROM communication_activations').fetchone()[0])
        # Retain an exact OS handle while its known child is still live, so
        # cleanup cannot accidentally act on a recycled PID.
        if os.name=='nt':
            import ctypes
            kernel=ctypes.windll.kernel32
            kernel.OpenProcess.restype=ctypes.c_void_p
            handle=kernel.OpenProcess(0x00100001,False,identity['pid'])
            self.assertTrue(handle)
            kernel.WaitForSingleObject.argtypes=(ctypes.c_void_p,ctypes.c_ulong)
            kernel.CloseHandle.argtypes=(ctypes.c_void_p,)
            def cleanup_handle():
                if kernel.WaitForSingleObject(handle,0)!=0:
                    kernel.TerminateProcess.argtypes=(ctypes.c_void_p,ctypes.c_uint)
                    kernel.TerminateProcess(handle,1)
                kernel.CloseHandle(handle)
            self.addCleanup(cleanup_handle)
        first.kill();first.communicate(timeout=2)
        self.poll(lambda:self.cli('communication-runtime-status','--workspace-id','w'),lambda row:row['state']=='expired')
        second=self.consumer(sdk=True)
        self.assertEqual(self.cli('communication-runtime-status','--workspace-id','w')['generation'],2)
        state=self.status(message)
        self.assertEqual(state['delivery']['attempt_count'],1)
        self.assertEqual(state['delivery']['schedule'],'unknown')
        self.gate.touch()
        self.poll(lambda:self.status(message),lambda row:row['reply']=='final')
        self.assertEqual(self.status(message)['delivery']['execution'],'unknown')
        if os.name=='nt':self.assertEqual(kernel.WaitForSingleObject(handle,5000),0)
        self.cli('communication-runtime-stop','--workspace-id','w')
        second.communicate(timeout=5)
        self.assertEqual(second.returncode,0)

    def test_cli_discovers_and_cancels_only_wait_final_receiver_continues(self):
        consumer=self.consumer()
        sent=self.cli('agent-dispatch-send','--workspace-id','w','--source-agent-id','a','--target-agent-id','b',
            '--reply-policy','message_only','--message','synthetic cancellation','--queued')
        message=sent['agentDispatch']['messageId']
        waiter=self.spawn(self.command('agent-message-wait','--workspace-id','w','--agent-id','a',
            '--message-id',message,'--condition','final','--timeout-seconds','10'))
        self.poll(lambda:self.cli('agent-message-wait-status','--workspace-id','w','--agent-id','a','--message-id',message),
            lambda row:bool(row['waits']))
        self.poll(lambda:self.status(message),lambda row:row['active_waiter_verified'] and row['acknowledged'])
        waits=self.cli('agent-message-wait-status','--workspace-id','w','--agent-id','a','--message-id',message)['waits']
        self.assertEqual(len(waits),1)
        self.cli('agent-message-cancel-wait','--workspace-id','w','--agent-id','a','--observation-id',waits[0]['observationId'])
        out,err=waiter.communicate(timeout=3)
        self.assertEqual(waiter.returncode,0,err)
        self.assertEqual(json.loads(out)['state'],'cancelled')
        self.assertEqual(self.status(message)['reply'],'none')
        self.gate.touch()
        self.poll(lambda:self.status(message),lambda row:row['delivery']['execution']=='finished')
        self.cli('communication-runtime-stop','--workspace-id','w')
        consumer.communicate(timeout=5)

    def test_ack_retry_recovers_same_message_after_consumer_stopped_without_new_turn(self):
        consumer=self.consumer()
        args=('agent-dispatch-send','--workspace-id','w','--source-agent-id','a','--target-agent-id','b',
            '--reply-policy','message_only','--message','synthetic idempotent wait','--idempotency-key','stable-wait',
            '--wait','ack','--wait-timeout-seconds','10')
        first=self.cli(*args)
        self.assertEqual(first['state'],'satisfied')
        self.gate.touch()
        self.poll(lambda:self.status(first['messageId']),lambda row:row['delivery']['execution']=='finished')
        self.cli('communication-runtime-stop','--workspace-id','w')
        consumer.communicate(timeout=5)
        before=self.connection.execute('SELECT COUNT(*) FROM communication_messages').fetchone()[0]
        second=self.cli(*args)
        self.assertEqual(second['state'],'satisfied')
        self.assertEqual(second['messageId'],first['messageId'])
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM communication_messages').fetchone()[0],before)
        self.assertEqual(self.status(first['messageId'])['delivery']['attempt_count'],1)

    def test_wait_dry_run_requires_no_consumer_creates_no_message_observation_or_schema(self):
        tables=self.connection.execute('SELECT name FROM sqlite_master').fetchall()
        before=self.connection.execute('SELECT COUNT(*) FROM communication_messages').fetchone()[0]
        preview=self.cli('agent-dispatch-send','--workspace-id','w','--source-agent-id','a','--target-agent-id','b',
            '--reply-policy','message_only','--message','synthetic preview','--wait','final','--dry-run')
        self.assertTrue(preview['dryRun'])
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM communication_messages').fetchone()[0],before)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM communication_observations').fetchone()[0],0)
        self.assertEqual(self.connection.execute('SELECT name FROM sqlite_master').fetchall(),tables)

    def test_stop_request_drains_to_bound_then_stops_owned_gated_receiver(self):
        consumer=self.consumer()
        sent=self.cli('agent-dispatch-send','--workspace-id','w','--source-agent-id','a','--target-agent-id','b',
            '--reply-policy','message_only','--message','synthetic stop budget','--wait','ack','--wait-timeout-seconds','10')
        self.assertEqual(sent['state'],'satisfied')
        self.poll(lambda:json.loads(self.trace.read_text(encoding='utf-8')) if self.trace.exists() else None,
            lambda row:row is not None and row['state']=='acked')
        start=time.monotonic()
        self.cli('communication-runtime-stop','--workspace-id','w')
        out,err=consumer.communicate(timeout=8)
        self.assertEqual(consumer.returncode,0,err)
        self.assertLess(time.monotonic()-start,8)
        self.assertEqual(json.loads(out)['state'],'stopped')
        self.assertEqual(self.status(sent['messageId'])['reply'],'none')
        self.assertEqual(self.status(sent['messageId'])['delivery']['schedule'],'unknown')


if __name__ == "__main__":
    unittest.main()
