from __future__ import annotations

import json
import base64
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from agent_os.application.services.local_platform_application import LocalPlatformApplication
from agent_os.application.services.agent_communication_context import build_agent_cli_actions, cli_shell_examples
from agent_os.application.services.project_workspace_scope import project_workspace_marker_payload, write_project_workspace_marker_atomic
from agent_os.infrastructure.config import LocalPlatformSettings
from agent_os.local_runtime import _build_parser, _agent_help
from tests import test_deepseek_harness_application as dsh_fixture
from tests.test_deepseek_harness_application import PREFLIGHT_TARGET, FIXTURE

FAKE_AGENT = Path(__file__).parent / "fixtures" / "fake_communication_agent.py"
SOURCE = str(Path(__file__).resolve().parents[1] / "src")
WORKSPACE = "workspace-dsh"


class DshCommunicationParityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="beacon-parity-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / "project 空格 'quoted' $literal &"
        self.project.mkdir()
        self.profile = self.root / "profile 空格 'quoted' $.json"
        runtime = {"workspaceId": WORKSPACE, "databasePath": str(self.root / "platform.sqlite3"),
                   "workspaceRoot": str(self.root / "workspace"), "pluginsDirectory": str(self.root / "plugins"),
                   "providerSessionRegistry": str(self.root / "registry.json")}
        self.profile.write_text(json.dumps({"localRuntime": runtime}), encoding="utf-8")
        write_project_workspace_marker_atomic(self.project / ".beacon" / "workspace.json",
            workspace_id=WORKSPACE, profile_path=self.profile,
            payload=project_workspace_marker_payload(project_root=self.project, workspace_id=WORKSPACE, profile_path=self.profile))
        self.app = LocalPlatformApplication(LocalPlatformSettings(
            database=runtime["databasePath"], workspace_root=runtime["workspaceRoot"],
            plugins_directory=runtime["pluginsDirectory"], profile_path=str(self.profile),
            provider_session_registry=runtime["providerSessionRegistry"]))
        self.app.create_workspace(workspace_id=WORKSPACE, display_name="Fake parity", root_path=str(self.project), agent_id="codex-peer")
        for provider in ("codex", "claude", "hermes"):
            agent = provider + "-peer"
            if provider != "codex":
                self.app.create_agent(workspace_id=WORKSPACE, agent_id=agent, name=agent, description="fake")
            native = str(uuid4())
            kwargs = {"workspace_id": WORKSPACE, "agent_id": agent, "handle_id": provider + "-handle",
                      "cwd": str(self.project), "created_by": "fixture", "reason": "isolated fake"}
            kwargs[{"codex": "codex_session_id", "claude": "claude_session_uuid", "hermes": "hermes_session_id"}[provider]] = native
            if provider == "codex":
                kwargs["metadata"] = {"codexSessionIdentity": {"runtimeHome": str(self.root / "fake-codex-home")}}
            elif provider == "hermes":
                kwargs["metadata"] = {"hermesSessionIdentity": {"runtimeHome": str(self.root / "fake-hermes-home")}}
                (self.root / "fake-hermes-home").mkdir()
            getattr(self.app, "register_" + provider + "_session_handle")(**kwargs)
            self.app.login_agent_endpoint(workspace_id=WORKSPACE, agent_id=agent, alias=agent, provider=provider,
                provider_handle_id=provider + "-handle", direction="send_receive", created_by="fixture", reason="fake")

    def join(self, agent="target-dsh", *, policy="reply", peers=()):
        trace = self.root / (agent + "-trace.json")
        launch = [sys.executable, str(FIXTURE), "--communication-trace", str(trace), "--communication-policy", policy]
        for peer in peers:
            launch.extend(["--peer", peer])
        with patch(PREFLIGHT_TARGET, return_value=dsh_fixture.DeepSeekHarnessApplicationTests._preflight(self.root, launch_args=tuple(launch))):
            result = self.app.join_deepseek_harness_agent(
                workspace_id=WORKSPACE, agent_id=agent, cwd=str(self.project), carrier="fixture", executable_path=sys.executable,
                package_root=str(self.root), cordis_config_path=None, runtime_home=str(self.root / "fake-home"),
                runtime_home_source="fixture", state_root=str(self.root / "state"), session_root=str(self.root / "sessions"),
                model_provider="fake", model="fake", initialize_timeout_seconds=5,
                operation_timeout_seconds=30, shutdown_timeout_seconds=2)
        self.assertTrue(result["ok"], result)
        handle = result["deepseekHarnessSessionHandle"]
        self.addCleanup(dsh_fixture.DeepSeekHarnessApplicationTests._stop_if_live, self.app, handle)
        return handle, trace

    def cli(self, *args, marker=False, expected=0):
        argv = [sys.executable, "-m", "agent_os.local_runtime"]
        if not marker:
            argv.extend(["--profile", str(self.profile)])
        result = subprocess.run([*argv, *args], cwd=self.project if marker else self.root,
                                env={**os.environ, "PYTHONPATH": SOURCE, "PYTHONIOENCODING": "utf-8"},
                                capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout) if expected == 0 else result

    def test_registered_inventory_exact_alias_scope_and_terminal_state(self):
        handle, _ = self.join()
        args = ("agent-onboarding-status", "--provider", "dsh", "--native-session-id", handle["deepseekHarnessSessionId"])
        outside = self.cli(*args)
        inside = self.cli(*args, marker=True)
        self.assertEqual(outside["runtime"]["databasePath"], inside["runtime"]["databasePath"])
        self.assertEqual(outside["nativeSessionResolution"]["status"], "matched")
        self.assertEqual(outside["providerSessionHandles"]["handles"][0]["handleId"], handle["handleId"])
        self.assertEqual(outside["agents"]["count"], 1)
        pretty = subprocess.run([sys.executable, "-m", "agent_os.local_runtime", "--profile", str(self.profile),
            *args, "--format", "pretty"], cwd=self.root,
            env={**os.environ, "PYTHONPATH": SOURCE, "PYTHONIOENCODING": "utf-8"},
            capture_output=True, encoding="utf-8", timeout=20)
        self.assertEqual(pretty.returncode, 0, pretty.stderr)
        self.assertIn("nativeSessionResolution: matched", pretty.stdout)
        self.assertIn(handle["handleId"], pretty.stdout)
        self.assertNotIn("sessionDiscover", outside["commands"])
        self.assertNotIn("registerDiscoveredHandle", outside["commands"])
        self.assertEqual(outside["commands"]["agentJoin"]["argv"][0], str(Path(sys.executable).resolve()))
        alias = self.cli("agent-onboarding-status", "--alias", "target-dsh", "--provider", "deepseek_harness")
        self.assertEqual(alias["providerSessionHandles"]["count"], 1)
        self.assertTrue(alias["ready"])
        missing = self.cli("agent-onboarding-status", "--provider", "dsh", "--native-session-id", "missing")
        self.assertEqual(missing["nativeSessionResolution"]["status"], "missing")
        self.assertFalse(missing["ready"])
        with self.app._components() as components:
            components.operations().register_deepseek_harness_session_handle(WORKSPACE,
                agent_id="target-dsh", handle_id="ambiguous-handle", deepseek_harness_session_id=handle["deepseekHarnessSessionId"],
                cwd=str(self.project), created_by="fixture", reason="ambiguous historical registration")
        ambiguous = self.cli(*args)
        self.assertEqual(ambiguous["nativeSessionResolution"]["status"], "ambiguous")
        self.assertFalse(ambiguous["ready"])
        self.app.stop_deepseek_harness_runtime(workspace_id=WORKSPACE, handle_id=handle["handleId"], acknowledge_continuity_loss=True)
        inactive = self.cli("agent-onboarding-status", "--provider", "dsh", "--alias", "target-dsh", "--native-session-id", handle["deepseekHarnessSessionId"])
        self.assertEqual(inactive["nativeSessionResolution"]["status"], "inactive")
        self.assertFalse(inactive["ready"])
        other = self.cli("agent-onboarding-status", "--workspace-id", "other", "--provider", "dsh")
        self.assertFalse(other["workspace"]["exists"])
        self.assertFalse(other["ready"])
        self.assertEqual(other["providerSessionHandles"]["count"], 0)
        # The same native identifier in another workspace must never affect
        # this workspace's mapping, even with identical visible aliases.
        self.app.create_workspace(workspace_id="other", display_name="Other fake scope",
            root_path=str(self.root), agent_id="other-dsh-agent")
        self.app.register_deepseek_harness_session_handle(workspace_id="other", agent_id="other-dsh-agent",
            handle_id="other-handle", deepseek_harness_session_id=handle["deepseekHarnessSessionId"],
            cwd=str(self.root), created_by="fixture", reason="isolated identity collision")
        self.app.login_agent_endpoint(workspace_id="other", agent_id="other-dsh-agent", alias="target-dsh",
            provider="deepseek_harness", provider_handle_id="other-handle")
        other_mapping = self.cli("agent-onboarding-status", "--workspace-id", "other", *args[1:])
        self.assertEqual(other_mapping["nativeSessionResolution"]["status"], "matched")
        self.assertEqual(other_mapping["providerSessionHandles"]["handles"][0]["handleId"], "other-handle")

    def fake_provider_command(self, provider):
        trace = self.root / (provider + "-trace.json")
        command = self.root / (provider + (".cmd" if os.name == "nt" else "-fake"))
        argv = [sys.executable, str(FAKE_AGENT), provider, str(trace)]
        command.write_text("@echo off\n" + subprocess.list2cmdline(argv) + " %*\n" if os.name == "nt"
                           else "#!/bin/sh\nexec " + shlex.join(argv) + ' "$@"\n', encoding="utf-8")
        if os.name != "nt":
            command.chmod(0o755)
        return str(command), trace

    def test_actual_fake_cli_receiver_and_sender_all_bidirectional_routes(self):
        peers = ("codex-peer", "claude-peer", "hermes-peer", "dsh-peer")
        handle, trace_path = self.join(peers=peers)
        self.join("dsh-peer")
        inbound_ids = set()
        # All four inbound directions traverse the real DSH supervisor/runtime.
        for source in peers:
            result = self.app.send_agent_dispatch(workspace_id=WORKSPACE, from_endpoint_alias=source,
                to_endpoint_alias="target-dsh", message="协作 input ' $() & — decide freely", delivery_mode="worker_execute",
                activation_timeout_seconds=40)
            if result["agentDispatch"]["status"] != "completed":
                trace_text = trace_path.read_text(encoding="utf-8") if trace_path.exists() else "no fake CLI trace"
                error_path = Path(str(trace_path) + ".error")
                if error_path.exists():
                    trace_text += error_path.read_text(encoding="utf-8")
                self.fail(str(result["workerRun"]["agentDispatches"][0].get("activation")) + "\n" + trace_text[-4500:])
            self.assertEqual(result["agentExchangeRequest"]["responseSummary"], "Explicit fake reply from target-dsh")
            inbound_ids.add(result["agentExchangeRequest"]["exchangeRequestId"])
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            self.assertEqual(trace["sourceAgentId"], source)
            self.assertEqual(trace["context"]["handleId"], handle["handleId"])
            self.assertEqual(trace["context"]["nativeSessionId"], handle["deepseekHarnessSessionId"])
            self.assertTrue(all(call["exitCode"] == 0 for call in trace["calls"]))
        # The fake DSH subprocess independently queried members and sent these
        # requests via CLI during its first turn; the parent only consumes queue.
        options = {}
        traces = {}
        for provider in ("codex", "claude", "hermes"):
            command, path = self.fake_provider_command(provider)
            options[provider + "_executable"] = command
            traces[provider] = path
        worker = self.app.run_agent_dispatch_worker_once(workspace_id=WORKSPACE, dispatcher_id="confirmed-fixture-worker",
            limit=8, activation_timeout_seconds=40, **options)
        rows = worker["agentDispatches"]
        self.assertEqual(len(rows), 4, str(worker)[-3000:])
        self.assertTrue(inbound_ids.isdisjoint({row["exchangeRequestId"] for row in rows}))
        self.assertTrue(all(row["finalStatus"] == "completed" for row in rows),
                        str([(r.get("provider"), r.get("finalStatus"), r.get("activation"), r.get("failureReason")) for r in rows])
                        + "\n" + "\n".join(p.read_text(encoding="utf-8")[-2000:] for p in self.root.glob("*.error")))
        for provider, path in traces.items():
            trace = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(trace["sourceAgentId"], "target-dsh")
            self.assertEqual(trace["targetAgentId"], provider + "-peer")
            self.assertTrue(any("agent-reply" in call["argv"] for call in trace["calls"]))
            self.assertNotEqual(trace["requestId"], trace["context"].get("parentRequestId"))
        # All replies are standard explicit CLI responses, never final capture.
        for request in self.app.list_agent_exchange_requests(workspace_id=WORKSPACE)["agentExchangeRequests"]:
            self.assertEqual(request["terminalReason"], "responded")
            self.assertTrue(request["responseSummary"].startswith("Explicit fake reply from "))

    def test_no_reply_final_remains_separate(self):
        self.join(policy="silent")
        sent = self.app.send_agent_dispatch(workspace_id=WORKSPACE, from_endpoint_alias="codex-peer", to_endpoint_alias="target-dsh",
                                            message="No reply required", delivery_mode="worker_execute")
        self.assertEqual(sent["agentDispatch"]["status"], "waiting_response")
        self.assertIsNone(sent["agentExchangeRequest"].get("responseSummary"))
        self.assertFalse(sent["workerRun"]["agentDispatches"][0]["activation"]["targetResponseCompleted"])

    def test_shell_examples_execute_literal_unicode_paths_and_reply_text(self):
        shells = [("powershell", shutil.which("powershell")),
                  ("bash", shutil.which("bash") or ("C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else None))]
        for shell, executable in shells:
            if not executable or not Path(executable).is_file():
                self.fail("Required shell unavailable for quoting gate: " + shell)
            with self.subTest(shell=shell):
                request_id = "shell-" + shell
                self.app.create_agent_exchange_request(workspace_id=WORKSPACE, source_agent_id="codex-peer",
                    target_agent_id="claude-peer", request_kind="question", request_summary="literal shell proof",
                    exchange_request_id=request_id)
                actions = build_agent_cli_actions(database_path=self.app.settings.database,
                    workspace_root=self.app.settings.workspace_root, plugins_directory=self.app.settings.plugins_directory,
                    profile_path=str(self.profile), workspace_id=WORKSPACE, exchange_request_id=request_id,
                    target_agent_id="claude-peer")
                literal = "回复 'quotes' \"double\" $literal $(echo injected) `echo nope` & ;\nnext line"
                actions["respondArgvTemplate"][-1] = literal
                examples = cli_shell_examples(actions)
                env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
                env.pop("VIRTUAL_ENV", None)
                for key in ("selfArgv", "inspectArgv", "respondArgvTemplate"):
                    script = examples[key][shell]
                    if shell == "powershell":
                        script = "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); " + script
                        argv = [executable, "-NoProfile", "-NonInteractive", "-EncodedCommand",
                                base64.b64encode(script.encode("utf-16-le")).decode("ascii")]
                    else:
                        argv = [executable, "--noprofile", "--norc", "-c", script]
                    result = subprocess.run(argv, cwd=self.root, env=env, capture_output=True, encoding="utf-8", timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIsInstance(json.loads(result.stdout), dict)
                request = self.app.get_agent_exchange_request_status(workspace_id=WORKSPACE, exchange_request_id=request_id)
                self.assertEqual(request["agentExchangeRequest"]["responseSummary"], literal)

    def test_cli_reply_rejects_wrong_duplicate_expired_and_closed_requests(self):
        self.join(policy="silent")
        for kind in ("normal", "expired", "closed"):
            request_id = "reply-" + kind
            self.app.create_agent_exchange_request(workspace_id=WORKSPACE, source_agent_id="codex-peer",
                target_agent_id="target-dsh", request_kind="question", request_summary="reply guard",
                exchange_request_id=request_id,
                expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat() if kind == "expired" else None)
            if kind == "closed":
                self.app.close_agent_exchange_request(workspace_id=WORKSPACE, exchange_request_id=request_id)
            if kind == "normal":
                self.cli("agent-reply", "--request", request_id, "--agent", "hermes-peer", "--message", "wrong", expected=1)
                self.cli("agent-reply", "--request", request_id, "--agent", "target-dsh", "--message", "selected")
            self.cli("agent-reply", "--request", request_id, "--agent", "target-dsh", "--message", "overwrite", expected=1)
            status = self.app.get_agent_exchange_request_status(workspace_id=WORKSPACE, exchange_request_id=request_id)
            self.assertEqual(status["agentExchangeRequest"].get("responseSummary"), "selected" if kind == "normal" else None)

    def test_dsh_thread_visibility_is_agent_scoped(self):
        _, trace_path = self.join()
        sent = self.app.send_agent_dispatch(workspace_id=WORKSPACE, from_endpoint_alias="codex-peer",
            to_endpoint_alias="target-dsh", message="private thread", delivery_mode="queued", detail_refs=("docs/fake-note.md",))
        request = sent["agentExchangeRequest"]
        self.app.update_agent_exchange_thread_visibility(workspace_id=WORKSPACE, thread_id=request["threadId"],
            updated_by_agent_id="codex-peer", visibility="participants_only")
        self.cli("agent-exchange-thread-get", "--thread-id", request["threadId"], "--requesting-agent-id", "hermes-peer", expected=1)
        worker = self.app.run_agent_dispatch_worker_once(workspace_id=WORKSPACE, dispatcher_id="fake-thread-worker", limit=1)
        self.assertEqual(worker["agentDispatches"][0]["finalStatus"], "completed")
        context = json.loads(trace_path.read_text(encoding="utf-8"))["context"]
        self.assertEqual(context["threadId"], request["threadId"])
        self.assertEqual(context["detailRefs"], ["docs/fake-note.md"])
        self.assertEqual(context["instructionAuthority"], "agent_suggestion")
        self.assertIn("--requesting-agent-id", context["actions"]["threadArgv"])
        self.assertEqual(set(context["actions"]["runtimeEnvironment"]), {"PYTHONPATH"})

    def test_busy_decision_explicit_worker_and_runtime_loss_do_not_replay(self):
        handle, trace = self.join()
        pending = self.app.send_agent_dispatch(workspace_id=WORKSPACE, from_endpoint_alias="codex-peer",
            to_endpoint_alias="target-dsh", message="queued only", delivery_mode="queued")
        self.assertFalse(trace.exists())
        self.app.acquire_agent_dispatch_lease(workspace_id=WORKSPACE,
            dispatch_id=pending["agentDispatch"]["dispatchId"], lease_id="busy-fixture-lease",
            acquired_by="confirmed-fake-owner", lease_ttl_seconds=300)
        busy = self.app.send_agent_dispatch(workspace_id=WORKSPACE, from_endpoint_alias="claude-peer",
            to_endpoint_alias="target-dsh", message="caller must decide")
        self.assertEqual(busy["deliveryDecision"]["outcome"], "busy_returned")
        self.assertFalse(busy["deliveryDecision"]["providerCommandStarted"])
        self.assertFalse(trace.exists())
        self.app.release_agent_dispatch_lease(workspace_id=WORKSPACE, lease_id="busy-fixture-lease",
            released_by="confirmed-fake-owner")
        worker = self.app.run_agent_dispatch_worker_once(workspace_id=WORKSPACE, dispatcher_id="confirmed-worker", limit=1)
        self.assertEqual(worker["agentDispatches"][0]["finalStatus"], "completed")
        before = trace.read_bytes()
        second = self.app.run_agent_dispatch_worker_once(workspace_id=WORKSPACE, dispatcher_id="confirmed-worker", limit=2)
        self.assertEqual(second["processedCount"], 0)
        self.assertEqual(trace.read_bytes(), before)
        self.app.stop_deepseek_harness_runtime(workspace_id=WORKSPACE, handle_id=handle["handleId"], acknowledge_continuity_loss=True)
        with self.assertRaisesRegex(ValueError, "active"):
            self.app.send_agent_dispatch(workspace_id=WORKSPACE, from_endpoint_alias="codex-peer",
                to_endpoint_alias="target-dsh", message="must not resurrect")
        self.assertEqual(trace.read_bytes(), before)

    def test_profile_conflict_and_missing_provider_do_not_guess(self):
        self.cli("agent-onboarding-status", "--native-session-id", "unqualified", expected=1)
        conflicting = self.root / "conflicting-profile.json"
        conflicting.write_text(json.dumps({"localRuntime": {"databasePath": str(self.root / "other.sqlite3"),
            "workspaceRoot": str(self.root / "other-root"), "pluginsDirectory": str(self.root / "other-plugins")}}), encoding="utf-8")
        result = subprocess.run([sys.executable, "-m", "agent_os.local_runtime", "--profile", str(conflicting),
            "agent-onboarding-status", "--provider", "dsh"], cwd=self.project,
            env={**os.environ, "PYTHONPATH": SOURCE, "PYTHONIOENCODING": "utf-8"},
            capture_output=True, encoding="utf-8", timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "other.sqlite3").exists())

    def test_cli_unavailable_fails_before_dsh_submit(self):
        _, trace = self.join()
        with patch("agent_os.application.services.agent_communication_context.sys.executable", str(self.root / "missing-python.exe")):
            sent = self.app.send_agent_dispatch(workspace_id=WORKSPACE, from_endpoint_alias="codex-peer",
                to_endpoint_alias="target-dsh", message="unavailable command")
        self.assertNotEqual(sent["agentDispatch"]["status"], "completed")
        self.assertIn("beacon_cli_unavailable", str(sent))
        self.assertIsNone(sent["agentExchangeRequest"].get("responseSummary"))
        self.assertFalse(trace.exists())

    def test_ambiguous_sending_alias_and_blocked_contact_are_not_ready_guesses(self):
        handle, trace = self.join()
        self.app.login_agent_endpoint(workspace_id=WORKSPACE, agent_id="target-dsh", alias="second-dsh-alias",
            provider="deepseek_harness", provider_handle_id=handle["handleId"])
        self.app.login_agent_endpoint(workspace_id=WORKSPACE, agent_id="target-dsh", alias="blocked-dsh-alias",
            provider="deepseek_harness", provider_handle_id=handle["handleId"], direction="receive_only", contact_policy="block_all")
        blocked = self.cli("agent-onboarding-status", "--provider", "dsh", "--alias", "blocked-dsh-alias")
        self.assertFalse(blocked["ready"])
        self.assertIn("contact_policy_blocks_all", blocked["endpointAliases"]["endpoints"][0]["notReadyReasons"])
        with patch.dict(os.environ, {"BEACON_PARITY_SECRET": "fake-secret-must-not-be-delivered"}):
            sent = self.app.send_agent_dispatch(workspace_id=WORKSPACE, from_endpoint_alias="codex-peer",
                to_endpoint_alias="target-dsh", message="identity and environment guard")
        self.assertEqual(sent["agentDispatch"]["status"], "completed")
        context = json.loads(trace.read_text(encoding="utf-8"))["context"]
        self.assertEqual(context["sendingAliasResolution"], "ambiguous")
        self.assertIsNone(context["targetAlias"])
        self.assertIn("<confirmed-source-alias>", context["actions"]["sendArgvTemplate"])
        self.assertNotIn("fake-secret-must-not-be-delivered", json.dumps(context))
        self.assertEqual(set(context["actions"]["runtimeEnvironment"]), {"PYTHONPATH"})

    def test_dsh_documented_commands_and_grouped_help_match_parser(self):
        guide = Path(__file__).resolve().parents[2] / "docs" / "providers" / "deepseek_harness_managed_runtime.md"
        examples = [
            line
            for line in guide.read_text(encoding="utf-8").splitlines()
            if line.startswith("beacon ") and not line.endswith("`")
        ]
        self.assertEqual(len(examples), 10)
        parser = _build_parser()
        for example in examples:
            argv = shlex.split(example)[1:]
            # CLI main resolves this default from the explicit profile before
            # its final parse; test the same post-resolution argument shape.
            if "--workspace-id" not in argv:
                argv.extend(["--workspace-id", WORKSPACE])
            parser.parse_args(argv)
        help_text = json.dumps(_agent_help("session"))
        self.assertIn("--native-session-id", help_text)
        self.assertIn("exact header-only", help_text)
        self.assertIn("stop/resume/recreate", help_text)
        native = parser.parse_args(["agent-onboarding-status", "--workspace-id", WORKSPACE, "--provider", "dsh", "--native-session-id", "exact", "--format", "pretty"])
        self.assertEqual(native.native_session_id, "exact")


if __name__ == "__main__":
    unittest.main()
