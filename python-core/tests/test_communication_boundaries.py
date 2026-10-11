"""Executable dependency rules and storage/process substitution seams."""
import ast
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from agent_os.application.services.communication_runtime import CommunicationSupervisor, RuntimeConfig
from agent_os.application.services.communication_wait import CommunicationWait
from agent_os.domain.entities.communication import Caller, Claim, StaleAttempt
from agent_os.infrastructure.adapters.communication_directory import PlatformCommunicationDirectory
from agent_os.infrastructure.adapters.communication_process import activation_payload
from agent_os.infrastructure.config import LocalPlatformSettings
import agent_os.application.services.communication_policy as policy
import agent_os.application.services.local_platform_application as facade
from agent_os.application.services.communication_provider_adapter import CoreProviderAdapter


class CommunicationBoundaryTests(unittest.TestCase):
    def test_core_runtime_wait_policy_and_directory_have_no_reverse_assembly_imports(self):
        root = Path(__file__).resolve().parents[1]/'src'/'agent_os'
        service_paths = ['communication_core.py','communication_runtime.py','communication_wait.py','communication_policy.py']
        for path in service_paths:
            source = root/'application'/'services'/path
            imports = [n.module or '' for n in ast.walk(ast.parse(source.read_text(encoding='utf-8'))) if isinstance(n,ast.ImportFrom)]
            imports += [a.name for n in ast.walk(ast.parse(source.read_text(encoding='utf-8'))) if isinstance(n,ast.Import) for a in n.names]
            self.assertFalse(any('infrastructure' in x or 'local_platform' in x or 'local_runtime' in x or x=='sqlite3' for x in imports), (path,imports))
        tree = ast.parse((root/'infrastructure'/'adapters'/'communication_directory.py').read_text(encoding='utf-8'))
        imports = [n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        self.assertFalse(any('composition' in x or 'local_platform' in x for x in imports))
        self.assertIs(facade._dispatch_contact_policy_decision,policy._dispatch_contact_policy_decision)
        self.assertIs(facade._dispatch_reply_reachability,policy._dispatch_reply_reachability)

    def test_directory_substitution_never_constructs_platform(self):
        reader = SimpleNamespace(member_active=lambda caller:True)
        directory = PlatformCommunicationDirectory(reader=reader)
        directory.require_member(Caller('offline','a'))
        self.assertIs(directory.reader,reader)
        with self.assertRaises(ValueError):PlatformCommunicationDirectory()

    def test_supervisor_substitutes_coordination_and_process_ports(self):
        calls=[]
        owner={'workspace_id':'offline','generation':1}
        now=datetime.now(timezone.utc)
        coord=SimpleNamespace(acquire=lambda *a,**k:owner, require_owner=lambda *a,**k:{'stop_requested':False},
            heartbeat=lambda *a,**k:{'state':'running'}, finish=lambda *a:calls.append('finish'))
        service=SimpleNamespace(_now=lambda:now.isoformat(), clock=lambda:now,
            recover_expired_slots=lambda *a,**k:None, due_targets=lambda *a,**k:[])
        processes=SimpleNamespace(start=lambda *a:self.fail('no due target may start'),poll=lambda c:None,
            stop=lambda c:calls.append('stop'),close=lambda c:calls.append('close'))
        supervisor=CommunicationSupervisor(service,coord,processes)
        supervisor.start('offline',pid=1,start_id='fake')
        supervisor.tick()
        service.due_targets=lambda *a,**k:[{'session_key':'s','message_id':'m'}]
        coord.intent=lambda *a:None
        def stale_claim(*args,**kwargs):raise StaleAttempt('generation invalidated inside claim')
        service.claim=stale_claim
        with self.assertRaises(StaleAttempt):supervisor.tick()
        supervisor.shutdown()
        self.assertEqual(calls,['finish'])

    def test_wait_substitutes_services_and_does_not_touch_execution_port(self):
        now=datetime.now(timezone.utc).isoformat()
        obs={'id':'o','message_id':'m','condition':'ack','deadline':now,'workspace_id':'offline','observer':'a'}
        facts={'observation':obs,'state':'satisfied','receipt_id':'r'}
        service=SimpleNamespace(observation_status=lambda *a:facts,_now=lambda:now,
            status=lambda *a:{'delivery':{'delivery':'accepted','execution':'unknown'}})
        coord=SimpleNamespace(consumer_status=lambda *a:{'state':'expired'},
            waiter_open=lambda *a,**k:self.fail('already received ACK must not create a lease'))
        result=CommunicationWait(service,coord).wait_observation(Caller('offline','a'),'o')
        self.assertEqual(result['state'],'satisfied')
        self.assertEqual(result['executionState'],'unknown')

    def test_seven_backend_child_configuration_roundtrip_preserves_capture_and_permissions(self):
        settings=LocalPlatformSettings(database='prepared.sqlite',workspace_root='offline',plugins_directory='offline',initialize_schema=False)
        backends=[('codex','exec_resume','explicit_only'),('codex','app_server','provider_final_capture'),
            ('claude','cli','provider_final_capture'),('claude','agent_sdk','explicit_only'),
            ('hermes','cli','provider_final_capture'),('hermes','tui_gateway','explicit_only'),
            ('deepseek_harness','sdk_stdio','explicit_only')]
        for provider,backend,capture in backends:
            with self.subTest(provider=provider,backend=backend):
                options={'database_path':'prepared.sqlite','workspace_root':'offline','plugins_directory':'offline',
                    'codex_add_dirs':['explicit path'],'codex_sandbox_mode':'workspace-write','codex_approval_policy':'on-request',
                    'claude_allowed_tools':['Read'],'claude_permission_mode':'default','claude_settings_path':'explicit.json',
                    'hermes_home':'isolated-home','hermes_gateway_python':'isolated-python'}
                if provider!='deepseek_harness':
                    options[provider+'_activation_backend']=backend
                    options[provider+'_reply_writeback_mode']=capture
                payload=json.loads(json.dumps(activation_payload(settings,options,{'message_id':'m'},{'generation':1},'nonce')))
                adapter=CoreProviderAdapter(None,None,payload['options'])
                self.assertFalse(payload['settings']['initialize_schema'])
                for key,value in options.items():self.assertEqual(adapter.options[key],value)
                binding={'provider':provider,'native_session_id':'native','generation':None,'agent_id':'b','handle_id':'handle'}
                delivery={'capture':capture,'provider_backend':backend,'routing':{'reply_policy':'message_only'}}
                service=SimpleNamespace(repo=SimpleNamespace(get=lambda *a:delivery,receipts=lambda *a:[]),
                                        record_execution_path=lambda claim, via: None)
                observed={}
                activation_key={'codex':'codexRegisteredSessionActivation','claude':'claudeRegisteredSessionActivation',
                    'hermes':'hermesRegisteredSessionActivation','deepseek_harness':'deepseekHarnessRegisteredSessionActivation'}[provider]
                def activate(workspace,**kwargs):
                    observed.update(kwargs)
                    return {activation_key:{'status':'delivered','providerCommandStarted':True}}
                platform=SimpleNamespace(_activate_agent_dispatch_provider=activate)
                message={'id':'m','workspace_id':'offline','sender':'a','target':'b','thread_id':'t',
                    'legacy_provider_backend':backend,'legacy_capture_policy':capture}
                evidence=CoreProviderAdapter(service,platform,payload['options'])(message,binding,
                    Claim('offline','m','b','session','attempt',1,'owner'),2)
                self.assertTrue(evidence.stopped)
                self.assertEqual(evidence.outcome,'finished')
                if provider!='deepseek_harness':
                    self.assertEqual(observed[provider+'_activation_backend'],backend)
                    self.assertEqual(observed[provider+'_reply_writeback_mode'],capture)
                self.assertEqual(observed['activation_timeout_seconds'],2)
                self.assertNotIn('environment',payload)
                self.assertNotIn('body',payload)
        with self.assertRaises(Exception):activation_payload(settings,{'fixture_module':'arbitrary'}, {}, {}, 'nonce')


if __name__ == '__main__':unittest.main()
