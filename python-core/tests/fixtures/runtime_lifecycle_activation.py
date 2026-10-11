"""Explicit offline composition for real process death/fence/gate tests."""
import argparse
from dataclasses import asdict
from datetime import datetime
import json
import os
from pathlib import Path
import time

from agent_os.application.services.communication_wait import CommunicationWait
from agent_os.application.services.communication_worker import CoreCommunicationWorker
from agent_os.domain.entities.communication import Caller, Claim, ProviderEvidence
from agent_os.infrastructure.composition.communication_runtime import prepared_runtime
from agent_os.infrastructure.config import LocalPlatformSettings


def run(payload):
    claim = Claim(**payload['claim'])
    root = Path(payload['test']['root'])
    gate = root / (claim.message_id + '.gate')
    trace = root / (claim.message_id + '.trace')
    mode = payload['test']['mode']
    with prepared_runtime(LocalPlatformSettings(**payload['settings']), claim.workspace_id) as (_, service):
        service.clock = lambda: datetime.fromisoformat(payload['test']['clock'])
        def note(state, **extra):
            temp = trace.with_suffix('.tmp')
            temp.write_text(json.dumps({'pid': os.getpid(), 'nonce': payload['nonce'], 'state': state, **extra}), encoding='utf-8')
            temp.replace(trace)
        def gated(state):
            note(state)
            end = time.monotonic() + 8
            while not gate.exists():
                if time.monotonic() > end:
                    raise TimeoutError('offline gate')
                time.sleep(.01)
        if mode == 'before':
            gated('before_start')
            os._exit(9)
        def provider(message, binding, attempt, timeout):
            if mode == 'noisy':
                import sys
                print('synthetic output ' * 50000,flush=True)
                print('synthetic diagnostic ' * 50000,file=sys.stderr,flush=True)
            service.ack(Caller('w', message['target']), message['id'], key='fixture-ack-'+message['id'])
            if mode in ('after', 'final_crash'):
                if mode == 'final_crash':
                    service.reply(Caller('w', message['target']), message['id'], body='explicit before crash', key='fixture-final-'+message['id'])
                note(mode)
                os._exit(9)
            if mode == 'cycle':
                peer = 'c' if message['target'] == 'b' else 'b'
                directed = service.send(Caller('w', message['target']), target_alias=peer,
                    body='cycle followup', key='cycle-' + message['id'], expectation='final')
                result = CommunicationWait(service, service.coordination).wait(Caller('w', message['target']),
                    directed['id'], condition='final', timeout=.3, poll_interval=.02,
                    heartbeat_interval=.05, lease_seconds=.2)
                note('cycle_timed_out', waitState=result['state'])
            else:
                gated('acked')
            return ProviderEvidence(binding['provider'], binding['native_session_id'], 'finished',
                'synthetic-owned-process:'+attempt.attempt_id, generation=binding['generation'], accepted=True, stopped=True,
                final='synthetic lifecycle final', trusted_final=True, provider_command_started=True)
        worker = CoreCommunicationWorker(service, provider,
            preflight=(lambda m,b: {'runtimeState': 'busy'}) if mode == 'busy' else None,
            evidence_sink=lambda c,e: service.coordination.stage_evidence('w', c.attempt_id,
                payload['nonce'], asdict(e), service._now()))
        result = worker.execute_claim(claim)
        if mode == 'busy':
            note('busy')
        elif mode != 'cycle':
            note(result['outcome'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--launch-json', required=True)
    run(json.loads(parser.parse_args().launch_json))
