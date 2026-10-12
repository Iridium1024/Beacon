"""Synthetic compact handoffs at the actual provider and process boundaries."""
from __future__ import annotations

import json
import os
import io
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4
import zipfile

from agent_os.application.services.communication_compact_delivery import render_provider_message
from agent_os.application.services.communication_envelope import BOUNDARY
from agent_os.application.services.communication_provider_adapter import CoreProviderAdapter
from agent_os.application.services.communication_worker import CoreCommunicationWorker
from agent_os.application.services.communication_short_refs import ShortReferences
from agent_os.application.services.local_platform_application import LocalPlatformApplication
from agent_os.domain.entities.communication import CommunicationError
from agent_os.infrastructure.adapters.communication_process import activation_payload
from agent_os.infrastructure.config import LocalPlatformSettings
import test_communication_integration as legacy
import test_dsh_communication_parity as dsh_parity


def native_hermes(root, native, capture):
    """A real direct launcher, bypassing cmd.exe rather than mocking Popen."""
    command = legacy._fake_hermes_command(root, native, capture, "Hermes execution only")
    if os.name != "nt":
        return command
    from pip._vendor.distlib.scripts import ScriptMaker
    script = (root / "fake_hermes.py").read_text(encoding="utf-8").replace(
        "import json, os, pathlib, sys", "import json, os, pathlib, sys\nos.environ['FAKE_HERMES_CAPTURE']=" + repr(str(capture)))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("__main__.py", script)
    executable = root / "fake_hermes_native.exe"
    maker = ScriptMaker(None, str(root))
    interpreter = ('"' + sys.executable + '"').encode("utf-8")
    executable.write_bytes(maker._get_launcher("t") + maker._build_shebang(interpreter, b"") + archive.getvalue())
    return executable


def provider_sample(backend, old, new, body, root, *, via="queued"):
    """Save only synthetic model-visible inputs using deterministic substitutions."""
    destination = os.environ.get("BEACON_C2B_PROVIDER_SAMPLES")
    if not destination:
        return
    identities = {}
    def normalize(text):
        for original, substitute in ((str(root), "C:/synthetic/beacon"),
                (str(Path(__file__).resolve().parents[1] / "src"), "C:/synthetic/beacon-src"),
                (sys.executable, "C:/synthetic/python.exe")):
            text = text.replace(json.dumps(original, ensure_ascii=False)[1:-1], substitute)
            text = text.replace(json.dumps(original)[1:-1], substitute).replace(original, substitute)
        def identity(match):
            raw = match.group(0)
            identities.setdefault(raw, "00000000-0000-4000-8000-" + str(len(identities) + 1).zfill(12))
            return identities[raw]
        text = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", identity, text, flags=re.I)
        text = re.sub(r"(req|wake)-[0-9a-f]{16}", lambda match: match.group(1) + "-0000000000000000", text)
        return re.sub(r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|\+00:00)", "2026-10-06T00:00:00Z", text)
    path = Path(destination)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "schema": "beacon.c2b.provider_samples.v1", "method": {
            "source": "actual fake-provider input captured at each production backend boundary",
            "normalization": "replace temp root, project source and interpreter paths with fixed synthetic paths; map UUIDs by first appearance; fix opaque req/wake filename hashes by role and ISO UTC timestamps; preserve all body text",
            "legacyBodyRetrieval": "Claude/Hermes legacy wrappers require a ticket/message read; body is recorded separately and must be charged by a complete-flow benchmark",
            "realProviders": False}, "samples": []}
    data["method"]["normalization"] = "replace raw and JSON-escaped temp root, project source and interpreter paths with fixed synthetic paths; map UUIDs by first appearance; fix opaque req/wake filename hashes by role and ISO UTC timestamps; preserve all body text"
    def required_reads(text):
        if any(value in text for value in (body, json.dumps(body, ensure_ascii=False)[1:-1], json.dumps(body)[1:-1])):
            return []
        marker = "Read the wake ticket JSON at: "
        if marker not in text:
            raise AssertionError("legacy body missing without an executable ticket-read path")
        ticket_path = text.split(marker, 1)[1].split("\n", 1)[0].split(" Use the platform CLI commands", 1)[0]
        argv = [sys.executable, "-B", "-c", "from pathlib import Path; import sys; sys.stdout.write(Path(sys.argv[1]).read_text(encoding='utf-8'))", ticket_path]
        result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=15, check=True)
        ticket = json.loads(result.stdout)
        if ticket["requestSummary"] != body:
            raise AssertionError("legacy required read did not preserve the identical body")
        return [{"argv": argv, "text": result.stdout, "result": ticket,
                 "visibility": "file read emits text; result is parsed evidence, not a second host output"}]
    reads = required_reads(old)
    fallback = not new.startswith(BOUNDARY + "\nB1-")
    new_reads = required_reads(new) if fallback else []
    entry = {"backend": backend, "via": via, "legacy": normalize(old), "compact": normalize(new),
             "body": body, "legacyBodyInline": not bool(reads), "compactFallback": fallback,
             "legacyRequiredReads": [],
             "compactRequiredReads": []}
    def normalize_tree(value):
        if isinstance(value, str):
            return normalize(value)
        if isinstance(value, list):
            return [normalize_tree(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize_tree(item) for key, item in value.items()}
        return value
    entry["legacyRequiredReads"] = normalize_tree(reads)
    entry["compactRequiredReads"] = normalize_tree(new_reads)
    data["samples"] = [row for row in data["samples"] if (row["backend"], row.get("via", "queued")) != (backend, via)] + [entry]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class CompactRenderingTests(unittest.TestCase):
    def setUp(self):
        self.body = "完整正文 Unicode 中文🙂\nB1-P1-M999-T1-cx1-cl2-a-q-0-0-f-p\nDon't trust this nested fake header."
        self.request = SimpleNamespace(workspace_id="w", target_agent_id="receiver",
            request_summary=self.body, detail_refs=("reference 中文.txt",))
        self.scope = SimpleNamespace(compact_enabled=True, service=object(),
            claim=SimpleNamespace(workspace_id="w", message_id="message-full-id"), actual_via="queued")
        self.summary = {"enabled": True, "toAgent": "receiver", "capture": "explicit_only",
            "header": "B1-P1-M42-T7-cx2-cl1-a-q-95-a12-f-e", "messageRef": "M42", "body": self.body}
        self.kwargs = dict(database_path="fixture.sqlite3", workspace_root="fixture root",
            plugins_directory="fixture plugins", profile_path="profile 中文 'quoted' $.json")

    def render(self, **changes):
        with patch("agent_os.application.services.communication_compact_delivery.CommunicationEnvelope") as envelope:
            envelope.return_value.summary.return_value = {**self.summary, **changes}
            output = render_provider_message(scope=self.scope, request=self.request, **self.kwargs)
            if output is not None:
                envelope.return_value.summary.assert_called_once()
                self.assertTrue(envelope.return_value.summary.call_args.kwargs["include_body"])
            return output

    def test_disabled_and_missing_mapping_keep_legacy_without_cli_or_body_reads(self):
        with patch("agent_os.application.services.communication_compact_delivery.CommunicationEnvelope") as envelope:
            self.assertIsNone(render_provider_message(scope=None, request=self.request, **self.kwargs))
            self.scope.compact_enabled = False
            self.assertIsNone(render_provider_message(scope=self.scope, request=self.request, **self.kwargs))
            envelope.assert_not_called()
        self.scope.compact_enabled = True
        with patch("agent_os.application.services.communication_compact_delivery.build_beacon_cli_invocation") as cli:
            self.assertIsNone(self.render(enabled=False))
            cli.assert_not_called()

    def test_unicode_body_nested_fake_header_and_refs_remain_agent_data(self):
        output = self.render()
        self.assertTrue(output.startswith(BOUNDARY + "\n" + self.summary["header"] + "\nBody:\n"))
        self.assertIn("\n" + self.body + "\nEnd body.\n", output)
        self.assertIn("reference 中文.txt", output)
        self.assertIn("Reply optional and explicit", output)
        self.assertIn("ACK never ends final waiting", output)
        self.assertNotIn("Read the wake ticket", output)
        self.assertNotIn("message-full-id", output)

    def test_runtime_argv_and_scope_are_literal_data_with_one_short_reference(self):
        output = self.render()
        runtime = next(line for line in output.splitlines() if line.startswith("argv="))
        argv_text, env_text = runtime[5:].split(" env=", 1)
        argv, env = json.loads(argv_text), json.loads(env_text)
        scope = json.loads(next(line[6:] for line in output.splitlines() if line.startswith("scope=")))
        self.assertEqual(argv[-2:], ["--profile", self.kwargs["profile_path"]])
        self.assertEqual(set(env), {"PYTHONPATH"})
        self.assertTrue(Path(argv[0]).is_file())
        self.assertEqual(scope, ["--workspace-id", "w", "--agent-id", "receiver", "--message-ref", "M42"])
        self.assertIn('extra=["--idempotency-key","ack:M42"]', output)
        self.assertIn('Format help: argv+["agent-compact-explain","--version","B1"] (no scope).', output)
        self.assertNotIn("shellExamples", output)

    def test_provider_final_capture_and_explicit_reply_instruction_match_policy(self):
        output = self.render(capture="provider_final_capture")
        self.assertIn("Your final is captured", output)
        self.assertIn("ACK ends ACK waiting only; never final waiting", output)
        self.assertNotIn("your final is not captured", output)

    def test_frozen_aliases_are_used_in_the_owned_summary(self):
        self.request.source_alias = "today-other-alias"
        self.request.target_alias = "today-another-alias"
        self.assertIn("From frozen-source to frozen-target.", self.render(fromAlias="frozen-source", toAlias="frozen-target"))
        self.assertNotIn("today-other-alias", self.render(fromAlias="frozen-source", toAlias="frozen-target"))

    def test_wrong_workspace_or_recipient_cannot_render_valid_looking_handoff(self):
        self.request.workspace_id = "other"
        with self.assertRaises(CommunicationError):
            self.render()
        self.request.workspace_id = "w"
        with self.assertRaises(CommunicationError):
            self.render(toAgent="another-target")

    def test_compact_option_is_explicit_boolean_and_cannot_select_execution_path(self):
        for value in ("true", 1, None, []):
            with self.subTest(value=value), self.assertRaises(CommunicationError):
                CoreProviderAdapter(None, None, {"compact_messages": value})
        adapter = CoreProviderAdapter(None, None, {"compact_messages": True}, actual_via="inline")
        self.assertTrue(adapter.compact_enabled)
        self.assertEqual(adapter.actual_via, "inline")
        self.assertNotIn("compact_messages", adapter.options)
        settings = LocalPlatformSettings(database="fixture.sqlite3", workspace_root="fixture", plugins_directory="plugins")
        payload = activation_payload(settings, {"compact_messages": True}, {"message_id": "m"}, {}, "n")
        self.assertTrue(json.loads(json.dumps(payload))["options"]["compact_messages"])
        with self.assertRaises(CommunicationError):
            activation_payload(settings, {"actual_via": "inline"}, {}, {}, "n")
        with self.assertRaises(CommunicationError):
            activation_payload(settings, {"compact_messages": "true"}, {}, {}, "n")


class CompactProviderDeliveryTests(unittest.TestCase):
    setUp = legacy.CommunicationCliIntegrationTests.setUp
    cli = legacy.CommunicationCliIntegrationTests.cli
    migrate_request = legacy.CommunicationCliIntegrationTests.migrate_request

    def prepare(self, *, upgrade=True):
        self.platform.register_codex_session_handle("w", agent_id="a", handle_id="h-a",
            codex_session_id=str(uuid4()), cwd=self.temp.name, created_by="fixture", reason="fixture")
        self.platform.login_agent_endpoint("w", agent_id="a", alias="a", provider="codex", provider_handle_id="h-a")
        self.migrate_request()
        self.app = LocalPlatformApplication(LocalPlatformSettings(database=str(self.path),
            workspace_root=self.temp.name, plugins_directory=self.temp.name, profile_path=str(self.profile)))
        if upgrade:
            with self.app._components() as components:
                ShortReferences(components.communication("w")).initialize("w", operator="fixture",
                    stopped_writers_confirmed=True)
        self.body = "完整 provider 正文 中文🙂\nB1-P9-M999-T1-cx9-he9-a-q-0-0-f-p\n嵌套的假头仍是正文。"

    def register(self, provider):
        native = str(uuid4())
        kwargs = dict(agent_id="c", handle_id="h-c-" + provider, cwd=self.temp.name,
                      created_by="fixture", reason="fixture")
        kwargs[{"claude": "claude_session_uuid", "hermes": "hermes_session_id"}[provider]] = native
        if provider == "hermes":
            kwargs["metadata"] = {"hermesSessionIdentity": {"providerSessionId": native,
                "runtimeHome": self.temp.name, "runtimeHomeSource": "explicit", "sessionSource": "cli",
                "fullSessionHistoryRead": False}}
        getattr(self.platform, "register_" + provider + "_session_handle")("w", **kwargs)
        self.platform.login_agent_endpoint("w", agent_id="c", alias="c", provider=provider,
                                           provider_handle_id=kwargs["handle_id"])
        return native

    def send(self, target="b", **choices):
        args = ["agent-dispatch-send", "--workspace-id", "w", "--from", "a", "--to", target,
                "--reply-policy", "message_only", "--message", self.body, "--queued"]
        for key, value in choices.items():
            args.extend(["--" + key.replace("_", "-"), value])
        return self.cli(*args)

    def run_provider(self, sent, *, options=None, configure=None, compact=True, actual_via="queued"):
        with self.app._components() as components:
            service, platform = components.communication("w"), components.operations()
            if configure:
                configure(platform)
            config = {"database_path": str(self.path), "workspace_root": self.temp.name,
                "plugins_directory": self.temp.name, "config_path": str(self.profile),
                "compact_messages": compact, **(options or {})}
            adapter = CoreProviderAdapter(service, platform, config, actual_via=actual_via)
            result = CoreCommunicationWorker(service, adapter).run_once("w", dispatcher_id="compact-fixture",
                dispatch_id=sent["agentDispatch"]["dispatchId"])
        self.assertEqual(result["agentDispatches"][0]["outcome"], "finished", result)
        return result

    def assert_handoff(self, text, sent, *, capture="explicit_only", via="q"):
        self.assertTrue(text.startswith(BOUNDARY + "\nB1-"), text[:160])
        self.assertIn("\nBody:\n" + self.body + "\nEnd body.\n", text)
        header = text.splitlines()[1]
        self.assertEqual(header.split("-")[7], via)
        self.assertNotIn("Read the wake ticket", text)
        self.assertNotIn("shellExamples", text)
        self.assertNotIn(sent["agentDispatch"]["messageId"], text)
        self.assertIn("--message-ref", text)
        self.assertIn("Your final is captured" if capture == "provider_final_capture"
                      else "your final is not captured", text)

    def delivered_action(self, text, action, extra=()):
        runtime = next(line for line in text.splitlines() if line.startswith("argv="))
        argv_text, env_text = runtime[5:].split(" env=", 1)
        argv, environment = json.loads(argv_text), json.loads(env_text)
        scope = json.loads(next(line[6:] for line in text.splitlines() if line.startswith("scope=")))
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC"}}
        env.update(environment, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([*argv, action, *scope, *extra], cwd=self.temp.name, env=env,
            capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_codex_exec_actual_stdin_and_short_ack_reply_status_execute_without_ticket_read(self):
        self.prepare()
        sent = self.send()
        native = self.platform.get_codex_session_handle("w", handle_id="h-b")["codexSessionHandle"]["codexSessionId"]
        capture = Path(self.temp.name) / "codex-compact.json"
        executable = legacy._fake_codex_command(Path(self.temp.name), native, capture, "execution only")
        self.run_provider(sent, options={"codex_executable": str(executable)})
        text = json.loads(capture.read_text(encoding="utf-8"))["stdin"]
        self.assert_handoff(text, sent)
        self.delivered_action(text, "agent-message-status")
        first = self.delivered_action(text, "agent-message-ack", ["--idempotency-key", "delivered-ack"])
        retry = self.delivered_action(text, "agent-message-ack", ["--idempotency-key", "delivered-ack"])
        self.assertEqual(first["receipt"]["id"], retry["receipt"]["id"])
        self.delivered_action(text, "agent-message-reply",
            ["--message", "真实的合成处理结果🙂", "--idempotency-key", "delivered-final"])
        self.assertEqual(self.delivered_action(text, "agent-message-status")["reply"], "final")
        if os.environ.get("BEACON_C2B_PROVIDER_SAMPLES"):
            self.run_provider(self.send(), options={"codex_executable": str(executable)}, compact=False)
            provider_sample("codex.exec_resume", json.loads(capture.read_text(encoding="utf-8"))["stdin"], text, self.body, self.temp.name)

    def test_codex_app_server_actual_turn_start_text_has_compact_envelope(self):
        self.prepare()
        sent = self.send(codex_activation_backend="app_server", codex_reply_writeback_mode="provider_final_capture")
        native = self.platform.get_codex_session_handle("w", handle_id="h-b")["codexSessionHandle"]["codexSessionId"]
        capture = Path(self.temp.name) / "app-start-input.json"
        executable = legacy._fake_codex_app_server_command(Path(self.temp.name), thread_id=native,
                                                          response_text="app final")
        script = Path(self.temp.name) / "fake_codex_app_server.py"
        script.write_text(script.read_text(encoding="utf-8").replace("elif method == 'turn/start':",
            "elif method == 'turn/start':\n        pathlib.Path(" + repr(str(capture)) + ").write_text(json.dumps(message['params']['input']), encoding='utf-8')"), encoding="utf-8")
        self.run_provider(sent, options={"codex_executable": str(executable)})
        text = json.loads(capture.read_text(encoding="utf-8"))[0]["text"]
        self.assert_handoff(text, sent, capture="provider_final_capture")
        if os.environ.get("BEACON_C2B_PROVIDER_SAMPLES"):
            old = self.send(codex_activation_backend="app_server", codex_reply_writeback_mode="provider_final_capture")
            self.run_provider(old, options={"codex_executable": str(executable)}, compact=False)
            provider_sample("codex.app_server", json.loads(capture.read_text(encoding="utf-8"))[0]["text"], text, self.body, self.temp.name)

    def test_claude_cli_actual_stdin_carries_body_and_compact_capture_semantics(self):
        self.prepare()
        native = self.register("claude")
        sent = self.send("c", claude_reply_writeback_mode="explicit_only")
        capture = Path(self.temp.name) / "claude-compact.json"
        executable = legacy._fake_claude_command(Path(self.temp.name), native, capture)
        self.run_provider(sent, options={"claude_executable": str(executable)})
        text = json.loads(capture.read_text(encoding="utf-8"))["stdin"]
        self.assert_handoff(text, sent)
        if os.environ.get("BEACON_C2B_PROVIDER_SAMPLES"):
            self.run_provider(self.send("c", claude_reply_writeback_mode="explicit_only"), options={"claude_executable": str(executable)}, compact=False)
            provider_sample("claude.cli", json.loads(capture.read_text(encoding="utf-8"))["stdin"], text, self.body, self.temp.name)

    def test_claude_sdk_actual_prompt_and_owned_scope_are_compact(self):
        self.prepare()
        self.register("claude")
        sent = self.send("c", claude_activation_backend="agent_sdk")
        prompts = []
        def configure(platform):
            platform.claude_agent_sdk_runtime_loader = lambda: legacy._sdk_runtime(compatible=True)
            def runner(*args, **kwargs):
                prompts.append(kwargs["prompt"])
                return legacy._sdk_result(final_response="SDK execution only")
            platform.claude_agent_sdk_runner = runner
        self.run_provider(sent, configure=configure)
        self.assertEqual(len(prompts), 1)
        self.assert_handoff(prompts[0], sent)
        if os.environ.get("BEACON_C2B_PROVIDER_SAMPLES"):
            self.run_provider(self.send("c", claude_activation_backend="agent_sdk"), configure=configure, compact=False)
            provider_sample("claude.agent_sdk", prompts[1], prompts[0], self.body, self.temp.name)

    def test_hermes_cli_actual_query_carries_body_without_ticket_read(self):
        self.prepare()
        native = self.register("hermes")
        sent = self.send("c", hermes_reply_writeback_mode="explicit_only")
        capture = Path(self.temp.name) / "hermes-compact.json"
        executable = native_hermes(Path(self.temp.name), native, capture)
        self.run_provider(sent, options={"hermes_executable": str(executable), "hermes_home": self.temp.name})
        argv = json.loads(capture.read_text(encoding="utf-8"))["argv"]
        text = argv[argv.index("--query") + 1]
        self.assert_handoff(text, sent)
        if os.environ.get("BEACON_C2B_PROVIDER_SAMPLES"):
            self.run_provider(self.send("c", hermes_reply_writeback_mode="explicit_only"), options={"hermes_executable": str(executable), "hermes_home": self.temp.name}, compact=False)
            old_argv = json.loads(capture.read_text(encoding="utf-8"))["argv"]
            provider_sample("hermes.cli", old_argv[old_argv.index("--query") + 1], text, self.body, self.temp.name)

    def test_hermes_batch_actual_truncation_is_avoided_by_legacy_fallback(self):
        self.prepare()
        native = self.register("hermes")
        sent = self.send("c", hermes_reply_writeback_mode="explicit_only")
        capture = Path(self.temp.name) / "hermes-batch.json"
        executable = legacy._fake_hermes_command(Path(self.temp.name), native, capture, "batch result")
        self.run_provider(sent, options={"hermes_executable": str(executable), "hermes_home": self.temp.name})
        argv = json.loads(capture.read_text(encoding="utf-8"))["argv"]
        query = argv[argv.index("--query") + 1]
        if os.name == "nt":
            self.assertIn("Read the wake ticket JSON", query)
            self.assertNotIn("\n", query)
            self.assertNotIn("--message-ref", query)
            if os.environ.get("BEACON_C2B_PROVIDER_SAMPLES"):
                self.run_provider(self.send("c", hermes_reply_writeback_mode="explicit_only"),
                    options={"hermes_executable": str(executable), "hermes_home": self.temp.name}, compact=False)
                old_argv = json.loads(capture.read_text(encoding="utf-8"))["argv"]
                old_query = old_argv[old_argv.index("--query") + 1]
                provider_sample("hermes.cli.batch_fallback", old_query, query, self.body, self.temp.name)
            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            # Reproduce the actual shim failure without provider/network calls.
            subprocess.run([str(executable), "chat", "--query", "line one\nline two\nline three"],
                env=env, capture_output=True, timeout=15)
            broken = json.loads(capture.read_text(encoding="utf-8"))["argv"]
            self.assertNotEqual(broken[broken.index("--query") + 1], "line one\nline two\nline three")
        else:
            self.assert_handoff(query, sent)

    def test_hermes_gateway_actual_prompt_uses_same_compact_renderer(self):
        self.prepare()
        native = self.register("hermes")
        sent = self.send("c", hermes_activation_backend="tui_gateway")
        fixture = Path(__file__).parent / "fixtures/fake_hermes_tui_gateway.py"
        wire = Path(self.temp.name) / "gateway-wire.jsonl"
        runtime = legacy.HermesTuiGatewayRuntime(status="available", compatible=True,
            python_executable=sys.executable, package_version="0.19.0", package_location=self.temp.name,
            gateway_entry_location=str(fixture),
            server_location=str(fixture), launch_argv=(sys.executable, "-u", str(fixture)),
            methods={"session.resume": True}, events={"gateway.ready": True}, capabilities={"version": "0.19.0"})
        environment = {"FAKE_HERMES_SCENARIO": "success", "FAKE_HERMES_PERSISTENT": native,
            "FAKE_HERMES_RUNTIME": "runtime-compact", "FAKE_HERMES_SOURCE": "cli",
            "FAKE_HERMES_CWD": self.temp.name, "FAKE_HERMES_LOG": str(wire)}
        def latest_prompt():
            frames = [json.loads(line) for line in wire.read_text(encoding="utf-8").splitlines()]
            return [frame["params"]["text"] for frame in frames if frame["method"] == "prompt.submit"][-1]
        with patch("agent_os.application.services.local_platform_operations.load_hermes_tui_gateway_runtime", return_value=runtime), patch.dict(os.environ, environment):
            self.run_provider(sent)
            text = latest_prompt()
            self.assert_handoff(text, sent)
            if os.environ.get("BEACON_C2B_PROVIDER_SAMPLES"):
                self.run_provider(self.send("c", hermes_activation_backend="tui_gateway"), compact=False)
                provider_sample("hermes.tui_gateway", latest_prompt(), text, self.body, self.temp.name)

    def test_default_and_missing_upgrade_fall_back_to_original_provider_text(self):
        self.prepare(upgrade=False)
        sent = self.send()
        native = self.platform.get_codex_session_handle("w", handle_id="h-b")["codexSessionHandle"]["codexSessionId"]
        capture = Path(self.temp.name) / "fallback.json"
        executable = legacy._fake_codex_command(Path(self.temp.name), native, capture, "legacy output")
        self.run_provider(sent, options={"codex_executable": str(executable)}, compact=True)
        text = json.loads(capture.read_text(encoding="utf-8"))["stdin"]
        self.assertTrue(text.startswith("You are receiving an agent-authored Beacon collaboration request."))
        self.assertIn(self.body, text)
        self.assertNotIn("--message-ref", text)

    def test_actual_inline_application_path_has_inline_header_and_legacy_pair(self):
        self.prepare()
        native = self.platform.get_codex_session_handle("w", handle_id="h-b")["codexSessionHandle"]["codexSessionId"]
        capture = Path(self.temp.name) / "inline-codex.json"
        executable = legacy._fake_codex_command(Path(self.temp.name), native, capture, "inline execution")
        inputs = []
        for enabled in (True, False):
            result = self.app.send_agent_dispatch(workspace_id="w", acting_endpoint_alias="a",
                to_endpoint_alias="b", message=self.body, reply_policy="message_only",
                compact_messages=enabled, codex_executable=str(executable),
                delivery_mode="worker_execute", read_live_runtime_status=False)
            self.assertTrue(result["workerExecuted"], result)
            text = json.loads(capture.read_text(encoding="utf-8"))["stdin"]
            inputs.append(text)
            if enabled:
                self.assert_handoff(text, result, via="i")
        self.assertIn(self.body, inputs[1])
        provider_sample("codex.exec_resume", inputs[1], inputs[0], self.body, self.temp.name, via="inline")


class CompactDshDeliveryTests(unittest.TestCase):
    setUp = dsh_parity.DshCommunicationParityTests.setUp
    cli = dsh_parity.DshCommunicationParityTests.cli
    join = dsh_parity.DshCommunicationParityTests.join

    def test_owned_dsh_actual_submit_carries_compact_text_without_actions_dump(self):
        workspace = dsh_parity.WORKSPACE
        self.cli("communication-migrate", "--workspace-id", workspace, "--operator", "fixture",
            "--backup-path", str(self.root / "pre-core.sqlite3"), "--confirm-stopped-writers")
        with self.app._components() as components:
            ShortReferences(components.communication(workspace)).initialize(workspace, operator="fixture",
                stopped_writers_confirmed=True)
        # This fake server still executes the actual native stdio exchange; only
        # the legacy-only context parser is disabled in its private temp copy.
        fixture = self.root / "fake_compact_dsh.py"
        fixture.write_text(dsh_parity.FIXTURE.read_text(encoding="utf-8").replace(
            "if args.communication_trace:", "if False and args.communication_trace:"), encoding="utf-8")
        with patch.object(dsh_parity, "FIXTURE", fixture):
            self.join(policy="silent")
        body = "DSH 完整合成正文🙂\nB1-P8-M999-T1-cx1-ds1-a-q-0-0-f-p"
        sent = self.cli("agent-dispatch-send", "--workspace-id", workspace,
            "--from", "codex-peer", "--to", "target-dsh", "--message", body, "--queued")
        from agent_os.application.services import local_platform_operations as operations
        original = operations.request_deepseek_harness_supervisor
        prompts = []
        def capture(**kwargs):
            if kwargs["method"] == "submit":
                prompts.append(kwargs["payload"]["message"])
            return original(**kwargs)
        with patch.object(operations, "request_deepseek_harness_supervisor", side_effect=capture):
            with self.app._components() as components:
                service = components.communication(workspace)
                adapter = CoreProviderAdapter(service, components.operations(), {
                    "database_path": self.app.settings.database,
                    "workspace_root": self.app.settings.workspace_root,
                    "plugins_directory": self.app.settings.plugins_directory,
                    "config_path": self.app.settings.profile_path, "compact_messages": True})
                run = CoreCommunicationWorker(service, adapter).run_once(workspace,
                    dispatcher_id="compact-dsh", dispatch_id=sent["agentDispatch"]["dispatchId"])
            if os.environ.get("BEACON_C2B_PROVIDER_SAMPLES"):
                old = self.cli("agent-dispatch-send", "--workspace-id", workspace,
                    "--from", "codex-peer", "--to", "target-dsh", "--message", body, "--queued")
                with self.app._components() as components:
                    service = components.communication(workspace)
                    adapter = CoreProviderAdapter(service, components.operations(), {
                        "database_path": self.app.settings.database,
                        "workspace_root": self.app.settings.workspace_root,
                        "plugins_directory": self.app.settings.plugins_directory,
                        "config_path": self.app.settings.profile_path, "compact_messages": False})
                    old_run = CoreCommunicationWorker(service, adapter).run_once(workspace,
                        dispatcher_id="legacy-dsh", dispatch_id=old["agentDispatch"]["dispatchId"])
                self.assertEqual(old_run["agentDispatches"][0]["outcome"], "finished", old_run)
                provider_sample("dsh.sdk_stdio", prompts[1], prompts[0], body, self.root)
        self.assertEqual(run["agentDispatches"][0]["outcome"], "finished", run)
        self.assertEqual(len(prompts), 2 if os.environ.get("BEACON_C2B_PROVIDER_SAMPLES") else 1)
        self.assertTrue(prompts[0].startswith(BOUNDARY + "\nB1-"))
        self.assertIn("\nBody:\n" + body + "\nEnd body.\n", prompts[0])
        self.assertIn("Your final is captured", prompts[0])
        self.assertNotIn("shellExamples", prompts[0])
        self.assertNotIn('"actions"', prompts[0])


if __name__ == "__main__":
    unittest.main()
