"""Real owned activation processes plus deterministic SQLite ownership time."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from agent_os.application.services.communication_runtime import CommunicationSupervisor, RuntimeConfig
from agent_os.domain.entities.communication import Caller, Claim, StaleAttempt
from agent_os.infrastructure.adapters.communication_process import SubprocessActivation
from agent_os.infrastructure.composition.communication_runtime import prepared_runtime
from agent_os.infrastructure.config import LocalPlatformSettings
import test_communication_runtime_integration as fixtures


class FixtureProcess(SubprocessActivation):
    def __init__(self, *args, root, clock, **kwargs):
        super().__init__(*args, **kwargs)
        self.root, self.clock, self.modes, self.handles = root, clock, {}, []
    def argv(self, payload):
        payload['test'] = {'root': str(self.root), 'clock': self.clock().isoformat(),
                           'mode': self.modes.get(payload['claim']['message_id'], 'gate')}
        return [sys.executable, '-B', '-m', 'fixtures.runtime_lifecycle_activation', '--launch-json', json.dumps(payload)]
    def start(self, *args):
        child = super().start(*args)
        self.handles.append(child)
        return child


class CommunicationProcessLifecycleTests(unittest.TestCase):
    def setUp(self):
        fixtures.CommunicationRuntimeIntegrationTests.setUp(self)
        # Discovery changes sys.path only; all fixture children also need it.
        child_environment = patch.dict(os.environ, {'PYTHONPATH': self.env['PYTHONPATH']})
        child_environment.start()
        self.addCleanup(child_environment.stop)
        self.settings = LocalPlatformSettings(database=str(self.path), workspace_root=self.temp.name,
            plugins_directory=self.temp.name, profile_path=str(self.profile), initialize_schema=False)
        self.context = prepared_runtime(self.settings, 'w')
        _, self.service = self.context.__enter__()
        self.addCleanup(lambda: self.context.__exit__(None,None,None))
        self.now = datetime.now(timezone.utc)
        self.service.clock = lambda: self.now
        self.service.coordination.initialize()
        self.processes = FixtureProcess(self.settings, {}, root=Path(self.temp.name), clock=lambda:self.now,
            provider_for=lambda c:'codex', preflight=False)
        self.config = RuntimeConfig(poll_interval=.01, heartbeat_interval=.1, consumer_lease=2,
            attempt_lease=3, provider_timeout=8, shutdown_timeout=.15, backoff=.1)
        self.tick_time = 0.0
        self.supervisor = CommunicationSupervisor(self.service, self.service.coordination, self.processes,
            config=self.config, monotonic=lambda:self.tick_time)
        self.supervisor.start('w', pid=os.getpid(), start_id='isolated-parent-test')
        self.addCleanup(self.cleanup_owned)

    cli = fixtures.CommunicationRuntimeIntegrationTests.cli
    spawn = fixtures.CommunicationRuntimeIntegrationTests.spawn
    clean_processes = fixtures.CommunicationRuntimeIntegrationTests.clean_processes

    def cleanup_owned(self):
        for child in self.processes.handles:
            self.processes.stop(child)
            self.processes.close(child)
        self.supervisor.children.clear()
        self.supervisor.shutdown()
        self.assertTrue(all(c.poll() is not None for c in self.processes.handles))
        from fixtures.runtime_audit import record
        record(self,self.processes.handles)

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)
        self.tick_time += seconds

    def message(self, target='b', mode='gate'):
        message = self.service.send(Caller('w','a'), target_alias=target, body='synthetic '+mode,
            key=str(__import__('uuid').uuid4()), capture='provider_final_capture', expectation='final')
        self.processes.modes[message['id']] = mode
        return message

    def status(self, message):
        return self.service.status(Caller('w','a'), message['id'])

    def trace_of(self, message):
        path = Path(self.temp.name)/(message['id']+'.trace')
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

    def open_gate(self, message):
        (Path(self.temp.name)/(message['id']+'.gate')).touch()

    def poll(self, predicate, *, tick=True):
        end = time.monotonic()+5
        while time.monotonic()<end:
            if tick:self.supervisor.tick()
            if predicate():return
            time.sleep(.01)
        self.fail('bounded process gate poll failed')

    def test_parallel_native_alias_exclusion_large_queue_busy_and_unknown_fairness(self):
        busy = self.message(mode='busy')
        for _ in range(105):self.message(target='b')
        # A second handle/alias for the same registered native session uses one slot.
        original = self.service.directory.resolve('w','b')
        self.platform.register_codex_session_handle('w',agent_id='b',handle_id='h-b-copy',
            codex_session_id=original.native_session_id,cwd=self.temp.name,created_by='fixture',reason='fixture')
        self.platform.login_agent_endpoint('w', agent_id='b', alias='b-alt', provider='codex', provider_handle_id='h-b-copy')
        alias = self.message(target='b-alt')
        self.platform.register_codex_session_handle('w', agent_id='c', handle_id='h-c', codex_session_id=str(__import__('uuid').uuid4()),cwd=self.temp.name,created_by='fixture',reason='fixture')
        self.platform.login_agent_endpoint('w', agent_id='c', alias='c', provider='codex',provider_handle_id='h-c')
        other = self.message(target='c')
        self.poll(lambda:self.trace_of(busy) and self.trace_of(other))
        self.assertEqual(self.trace_of(busy)['state'],'busy')
        self.assertEqual(self.trace_of(other)['state'],'acked')
        self.processes.modes[busy['id']] = 'gate'
        self.poll(lambda:all(x['claim'].message_id != busy['id'] for x in self.supervisor.children.values()))
        self.assertIsNone(self.trace_of(alias))
        self.assertLessEqual(len(self.supervisor.children),2)
        self.advance(.2)
        self.poll(lambda:any(x['claim'].target=='b' and self.trace_of({'id':x['claim'].message_id})
            for x in self.supervisor.children.values()))
        self.assertEqual(len(self.supervisor.children),2)
        self.advance(1)
        self.supervisor.tick()
        self.assertEqual(self.service.coordination.consumer_status('w',self.service._now())['state'],'running')
        self.assertTrue(all(self.service.attempt_status(x['claim'])['lease_until']>self.service._now() for x in self.supervisor.children.values()))
        # An unknown A keeps its native slot, but does not prevent C completion.
        a = next(x for x in self.supervisor.children.values() if x['claim'].target=='b')
        a['process'].kill();a['process'].wait(timeout=2)
        self.supervisor.tick()
        self.open_gate(other)
        self.poll(lambda:self.status(other)['delivery']['execution']=='finished')
        self.assertIsNone(self.trace_of(alias))

    def test_claimed_child_death_retries_after_start_death_never_replays(self):
        before = self.message(mode='before')
        self.poll(lambda:self.trace_of(before) is not None)
        process = next(iter(self.supervisor.children.values()))['process']
        process.kill();process.wait(timeout=2)
        self.supervisor.tick()
        self.assertEqual(self.status(before)['delivery']['schedule'],'pending')
        self.processes.modes[before['id']] = 'after'
        self.advance(.2)
        self.poll(lambda:self.status(before)['delivery']['schedule']=='unknown')
        count = self.status(before)['delivery']['attempt_count']
        self.advance(1)
        for _ in range(4):self.supervisor.tick()
        self.assertEqual(self.status(before)['delivery']['attempt_count'],count)
        self.assertEqual(self.status(before)['reply'],'none')

    def test_final_before_complete_crash_is_reply_success_with_execution_unknown(self):
        message = self.message(mode='final_crash')
        self.poll(lambda:self.status(message)['delivery']['schedule']=='unknown')
        self.assertEqual(self.status(message)['reply'],'final')
        self.assertEqual(self.status(message)['delivery']['execution'],'unknown')
        self.assertEqual(self.status(message)['delivery']['attempt_count'],1)
        for _ in range(3):self.supervisor.tick()
        self.assertEqual(self.status(message)['delivery']['attempt_count'],1)

    def test_takeover_blocks_old_child_complete_retains_evidence_for_reconcile(self):
        message = self.message(mode='late')
        self.poll(lambda:self.trace_of(message) is not None)
        child = next(iter(self.supervisor.children.values()))
        self.advance(3)
        replacement = CommunicationSupervisor(self.service,self.service.coordination,self.processes,
            config=self.config,monotonic=lambda:self.tick_time)
        owner2 = replacement.start('w',pid=os.getpid(),start_id='takeover')
        replacement.tick()
        self.assertEqual(self.status(message)['delivery']['attempt_count'],1)
        self.assertIsNone(child['process'].poll())
        self.open_gate(message)
        self.poll(lambda:child['process'].poll() is not None,tick=False)
        self.assertEqual(self.status(message)['reply'],'none')
        staged = self.service.coordination.staged('w',child['claim'].attempt_id)
        self.assertTrue(staged['evidence']['stopped'])
        from agent_os.domain.entities.communication import ProviderEvidence
        self.service.reconcile(child['claim'],ProviderEvidence(**staged['evidence']))
        self.assertEqual(self.status(message)['reply'],'final')
        with self.assertRaises(StaleAttempt):self.service.renew_lease(child['claim'],lease_seconds=3)
        self.assertEqual(owner2['generation'],2)

    def test_renewals_leave_provider_deadline_fixed_and_timeout_stops_owned_child(self):
        message = self.message()
        self.poll(lambda:self.trace_of(message) is not None)
        child = next(iter(self.supervisor.children.values()))
        deadline = self.service.attempt_status(child['claim'])['provider_deadline']
        for _ in range(7):
            self.advance(1)
            self.supervisor.tick()
            self.assertEqual(self.service.attempt_status(child['claim'])['provider_deadline'],deadline)
            self.assertIsNone(child['process'].poll())
        self.advance(1)
        self.supervisor.tick()
        self.assertIsNotNone(child['process'].poll())
        self.assertEqual(self.status(message)['delivery']['schedule'],'unknown')

    def test_waiter_death_expires_only_waiter_receiver_continues(self):
        from agent_os.application.services.communication_envelope import CompactHeader, CommunicationEnvelope
        from agent_os.application.services.communication_short_refs import ShortReferences
        # Prepare the optional representation before restarting this isolated
        # consumer; no active writer is present during its explicit upgrade.
        self.supervisor.shutdown()
        self.platform.register_codex_session_handle('w', agent_id='a', handle_id='h-a',
            codex_session_id=str(__import__('uuid').uuid4()), cwd=self.temp.name,
            created_by='fixture', reason='synthetic compact sender')
        self.platform.login_agent_endpoint('w', agent_id='a', alias='a', provider='codex', provider_handle_id='h-a')
        ShortReferences(self.service).initialize('w', operator='synthetic-admin', stopped_writers_confirmed=True)
        self.supervisor = CommunicationSupervisor(self.service, self.service.coordination, self.processes,
            config=self.config, monotonic=lambda:self.tick_time)
        self.supervisor.start('w', pid=os.getpid(), start_id='compact-waiter-death')
        message = self.service.send(Caller('w','a'), target_alias='b', body='synthetic gate',
            key=str(__import__('uuid').uuid4()), capture='provider_final_capture', expectation='final',
            source_alias='a', source_handle_id='h-a', reply_policy='message_only', delivery_path='queued')
        self.processes.modes[message['id']] = 'gate'
        envelope = CommunicationEnvelope(self.service)
        self.assertNotEqual(envelope.summary(Caller('w','b'), message['id'])['fromRef'], '?')
        self.poll(lambda:self.trace_of(message) is not None)
        waiter = self.spawn([sys.executable,'-B','-m','fixtures.runtime_wait_entry','--settings',json.dumps(asdict(self.settings)),
            '--message',message['id'],'--clock',self.now.isoformat()])
        self.poll(lambda:any(w['state']=='active' for w in self.status(message)['waiters']))
        before = CompactHeader.decode(envelope.summary(Caller('w','b'), message['id'])['header'])
        self.assertTrue(before.wait.startswith('f'))
        waiter.kill();waiter.communicate(timeout=2)
        self.advance(.21)
        self.assertFalse(self.status(message)['active_waiter_verified'])
        after = CompactHeader.decode(envelope.summary(Caller('w','b'), message['id'])['header'])
        self.assertEqual(after.wait, '0')
        self.assertEqual(after.via, 'q')
        self.assertEqual(self.status(message)['reply'],'none')
        self.open_gate(message)
        self.poll(lambda:self.status(message)['delivery']['execution']=='finished')
        self.assertEqual(self.status(message)['reply'],'final')

    def test_graceful_drain_stops_claims_forced_cleanup_preserves_foreign_runtime(self):
        message = self.message()
        self.poll(lambda:self.trace_of(message) is not None)
        queued = self.message()
        self.service.coordination.request_stop('w',self.service._now())
        self.supervisor.tick()
        self.assertTrue(self.supervisor.draining)
        self.open_gate(message)
        self.poll(lambda:not self.supervisor.children)
        self.assertEqual(self.status(queued)['delivery']['attempt_count'],0)
        self.supervisor.shutdown()
        self.assertEqual(self.service.coordination.consumer_status('w',self.service._now())['state'],'stopped')
        # A separate long-lived runtime is never a child handle of this consumer.
        foreign = self.spawn([sys.executable,'-B','-c','import time;time.sleep(20)'])
        self.supervisor = CommunicationSupervisor(self.service,self.service.coordination,self.processes,
            config=self.config)
        self.supervisor.start('w',pid=os.getpid(),start_id='forced-test')
        self.poll(lambda:self.trace_of(queued) is not None)
        self.supervisor.shutdown()
        self.assertIsNone(foreign.poll())
        self.assertEqual(self.status(queued)['delivery']['schedule'],'unknown')
        foreign.terminate();foreign.communicate(timeout=2)

    def test_cyclic_two_active_receivers_finite_waits_release_slots(self):
        self.platform.register_codex_session_handle('w', agent_id='c', handle_id='h-c', codex_session_id=str(__import__('uuid').uuid4()),cwd=self.temp.name,created_by='fixture',reason='fixture')
        self.platform.login_agent_endpoint('w',agent_id='c',alias='c',provider='codex',provider_handle_id='h-c')
        b,c = self.message('b','cycle'),self.message('c','cycle')
        self.poll(lambda:self.trace_of(b) and self.trace_of(c))
        self.assertEqual(self.trace_of(b)['waitState'],'timed_out')
        self.assertEqual(self.trace_of(c)['waitState'],'timed_out')
        self.poll(lambda:self.status(b)['delivery']['execution']=='finished' and self.status(c)['delivery']['execution']=='finished')
        self.assertEqual(self.status(b)['reply'],'final')
        self.assertEqual(self.status(c)['reply'],'final')

    def test_dsh_stop_only_owned_activation_handle_retains_managed_runtime(self):
        trace=Path(self.temp.name)/'synthetic-managed-runtime.json'
        class DshParent(SubprocessActivation):
            def argv(self,payload):
                return [sys.executable,'-B','-m','fixtures.runtime_dsh_parent',str(trace)]
        processes=DshParent(self.settings,{},provider_for=lambda claim:'deepseek_harness')
        child=processes.start({'message_id':'synthetic-dsh'}, {}, 'synthetic-start')
        self.processes.handles.append(child)
        self.addCleanup(lambda:processes.close(child))
        self.poll(lambda:trace.exists(),tick=False)
        pid=json.loads(trace.read_text(encoding='utf-8'))['pid']
        if os.name=='nt':
            import ctypes
            kernel=ctypes.windll.kernel32
            kernel.OpenProcess.restype=ctypes.c_void_p
            handle=kernel.OpenProcess(0x00100001,False,pid)
            self.assertTrue(handle)
            kernel.WaitForSingleObject.argtypes=(ctypes.c_void_p,ctypes.c_ulong)
            kernel.TerminateProcess.argtypes=(ctypes.c_void_p,ctypes.c_uint)
            kernel.CloseHandle.argtypes=(ctypes.c_void_p,)
            self.addCleanup(lambda:(kernel.TerminateProcess(handle,1),kernel.WaitForSingleObject(handle,2000),kernel.CloseHandle(handle)))
            processes.stop(child)
            self.assertIsNotNone(child.poll())
            self.assertEqual(kernel.WaitForSingleObject(handle,0),258)
        else:
            self.addCleanup(lambda:os.kill(pid,__import__('signal').SIGTERM))
            processes.stop(child)
            os.kill(pid,0)

    def test_long_noisy_child_does_not_block_heartbeat_or_append_heartbeat_ledger(self):
        message=self.message(mode='noisy')
        self.poll(lambda:self.trace_of(message) is not None)
        high_water=self.service.repo.high_water()
        before=self.service.coordination.consumer_status('w',self.service._now())['heartbeatAt']
        for _ in range(10):
            self.advance(.1)
            self.supervisor.tick()
        after=self.service.coordination.consumer_status('w',self.service._now())
        self.assertGreater(after['heartbeatAt'],before)
        self.assertEqual(self.service.repo.high_water(),high_water)
        self.open_gate(message)
        self.poll(lambda:self.status(message)['delivery']['execution']=='finished')

    def test_db_contention_is_bounded_and_cannot_revive_or_extend_failed_lease(self):
        before=self.service.coordination.consumer_status('w',self.service._now())['leaseUntil']
        blocker=sqlite3.connect(self.path)
        try:
            blocker.execute('BEGIN IMMEDIATE')
            start=time.monotonic()
            with self.assertRaises(sqlite3.OperationalError):
                self.service.coordination.heartbeat(self.supervisor.owner,now=self.service._now(),ttl=2)
            self.assertLess(time.monotonic()-start,.5)
            self.assertEqual(self.service.coordination.consumer_status('w',self.service._now())['leaseUntil'],before)
        finally:blocker.rollback();blocker.close()
        self.advance(.2)
        self.supervisor.tick()
        self.assertEqual(self.service.coordination.consumer_status('w',self.service._now())['state'],'running')

    def test_restart_bounded_sweep_recovers_missing_hint_without_merging_messages(self):
        first,second=self.message(),self.message()
        self.service.repo.connection.execute('DELETE FROM communication_wake_intents')
        self.service.repo.connection.commit()
        self.service.coordination.finish(self.supervisor.owner,self.service._now())
        self.supervisor=CommunicationSupervisor(self.service,self.service.coordination,self.processes,
            config=self.config,monotonic=lambda:self.tick_time)
        owner=self.supervisor.start('w',pid=os.getpid(),start_id='restart-sweep')
        self.assertEqual(owner['generation'],2)
        self.poll(lambda:self.trace_of(first) is not None)
        self.assertIsNone(self.trace_of(second))
        self.open_gate(first)
        self.poll(lambda:self.status(first)['delivery']['execution']=='finished')
        self.advance(.2)
        self.poll(lambda:self.trace_of(second) is not None)
        self.open_gate(second)
        self.poll(lambda:self.status(second)['delivery']['execution']=='finished')
        self.assertNotEqual(self.status(first)['receipts'][-1]['id'],self.status(second)['receipts'][-1]['id'])
        self.assertEqual(self.status(first)['delivery']['attempt_count'],1)
        self.assertEqual(self.status(second)['delivery']['attempt_count'],1)

    def test_revoked_target_route_does_not_stop_other_native_keys(self):
        blocked=self.message()
        self.platform.register_codex_session_handle('w',agent_id='c',handle_id='h-c',
            codex_session_id=str(__import__('uuid').uuid4()),cwd=self.temp.name,created_by='fixture',reason='fixture')
        self.platform.login_agent_endpoint('w',agent_id='c',alias='c',provider='codex',provider_handle_id='h-c')
        other=self.message('c')
        self.platform.deactivate_agent_endpoint('w',alias='b',deactivated_by='fixture',reason='policy revocation fixture')
        self.platform.login_agent_endpoint('w',agent_id='b',alias='b',provider='codex',provider_handle_id='h-b',contact_policy='block_all')
        self.poll(lambda:self.trace_of(other) is not None)
        self.assertIsNone(self.trace_of(blocked))
        self.assertEqual(self.status(blocked)['delivery']['attempt_count'],0)
        self.assertEqual(self.service.coordination.consumer_status('w',self.service._now())['state'],'running')
        self.open_gate(other)
        self.poll(lambda:self.status(other)['delivery']['execution']=='finished')


if __name__ == '__main__':unittest.main()
