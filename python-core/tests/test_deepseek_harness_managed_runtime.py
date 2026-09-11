from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from agent_os.application.services.deepseek_harness_managed_runtime import (
    DEEPSEEK_HARNESS_AUDITED_COMMIT,
    DeepSeekHarnessContinuityError,
    DeepSeekHarnessDeliveryError,
    DeepSeekHarnessJsonRpcTransport,
    DeepSeekHarnessProtocolError,
    DeepSeekHarnessRuntimePaths,
    build_deepseek_harness_runtime_spec,
    launch_deepseek_harness_supervisor,
    preflight_deepseek_harness_runtime,
    read_runtime_state,
    request_deepseek_harness_supervisor,
    runtime_handle_metadata,
    write_runtime_bootstrap,
)


FIXTURE = Path(__file__).parent / "fixtures" / "fake_deepseek_harness_runtime.py"


class DeepSeekHarnessManagedRuntimeTests(unittest.TestCase):
    def test_session_owner_key_uses_platform_canonical_path_case(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_root = root / "Mixed-Case-Sessions"
            original = DeepSeekHarnessRuntimePaths.create(
                root / "state",
                "runtime-one",
                session_root=session_root,
                session_id="native-session",
            ).session_owner_lease_path
            case_variant = DeepSeekHarnessRuntimePaths.create(
                root / "state",
                "runtime-two",
                session_root=str(session_root).swapcase(),
                session_id="native-session",
            ).session_owner_lease_path
            if os.name == "nt":
                self.assertEqual(original, case_variant)
            else:
                self.assertNotEqual(original, case_variant)

    def _spec(
        self,
        root: Path,
        *,
        scenario: str = "normal",
        handle: str = "handle-1",
        dsh_session_id: str | None = None,
        session_root: Path | None = None,
        state_root: Path | None = None,
        reply_writeback_mode: str = "explicit_only",
        max_line_bytes: int = 1024 * 1024,
    ):
        workspace = root / "workspace"
        sessions = session_root or root / "sessions"
        runtime_home = root / "runtime-home"
        runtime_state_root = state_root or root / "state"
        for path in (workspace, sessions, runtime_home, runtime_state_root):
            path.mkdir(parents=True, exist_ok=True)
        return build_deepseek_harness_runtime_spec(
            workspace_id="workspace-1",
            agent_id=f"agent-{handle}",
            handle_id=handle,
            dsh_session_id=dsh_session_id or f"dsh-session-{handle}",
            cwd=str(workspace),
            session_root=str(sessions),
            runtime_home=str(runtime_home),
            runtime_home_source="test_fixture",
            carrier="fixture",
            executable_path=sys.executable,
            launch_args=(sys.executable, str(FIXTURE), "--scenario", scenario),
            package_root=str(root),
            package_version="0.1.1-rc.2",
            expected_server_version="0.1.1-rc.2",
            model_provider="fake-provider",
            model="fake-model",
            state_root=str(runtime_state_root),
            reply_writeback_mode=reply_writeback_mode,
            operation_timeout_seconds=5,
            initialize_timeout_seconds=5,
            shutdown_timeout_seconds=2,
            max_line_bytes=max_line_bytes,
        )

    def test_transport_reuses_one_process_and_session_for_two_turns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            spec = self._spec(Path(temporary))
            transport = DeepSeekHarnessJsonRpcTransport(spec)
            evidence = transport.start()
            pid = evidence["processId"]
            first = transport.run_operation(
                operation_id="operation-1",
                session_id=spec.dsh_session_id,
                message="fake first turn",
            )
            second = transport.run_operation(
                operation_id="operation-2",
                session_id=spec.dsh_session_id,
                message="fake second turn",
            )

            self.assertEqual(transport.process_id, pid)
            self.assertEqual(first.final_response, "turn-1")
            self.assertEqual(second.final_response, "turn-2; observed=turn-1")
            self.assertTrue(first.trusted_final)
            self.assertLess(first.receipt_watermark, first.final_watermark)
            self.assertLess(first.final_watermark, first.idle_watermark)
            self.assertEqual(transport.graceful_shutdown()["exitCode"], 0)

    def test_notification_after_initialize_response_is_not_misclassified_by_race(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            spec = self._spec(
                Path(temporary),
                scenario="notification-after-initialize-response",
            )
            transport = DeepSeekHarnessJsonRpcTransport(spec)
            evidence = transport.start()
            self.assertEqual(evidence["serverVersion"], "0.1.1-rc.2")
            result = transport.run_operation(
                operation_id="operation-after-init",
                session_id=spec.dsh_session_id,
                message="fake prompt",
            )
            self.assertEqual(result.final_response, "turn-1")
            transport.graceful_shutdown()

    def test_transport_fails_closed_on_causal_and_wire_violations(self) -> None:
        scenarios = {
            "descendant-only-final": "idle_before_final",
            "unknown-queued-work": "unknown_queued_work",
            "idle-before-final": "idle_before_final",
            "no-final": "turn_end_before_final",
            "duplicate-final": "duplicate_root_final",
            "final-after-turn-end": "final_after_turn_end",
            "malformed-json": "malformed JSON",
            "unknown-response": "unknown DSH response id",
            "duplicate-response": "duplicate DSH response id",
        }
        for scenario, expected in scenarios.items():
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                spec = self._spec(Path(temporary), scenario=scenario)
                transport = DeepSeekHarnessJsonRpcTransport(spec)
                transport.start()
                with self.assertRaisesRegex(
                    (DeepSeekHarnessProtocolError, DeepSeekHarnessContinuityError),
                    expected,
                ):
                    transport.run_operation(
                        operation_id="operation-fail",
                        session_id=spec.dsh_session_id,
                        message="fake failure turn",
                    )
                transport.force_terminate()

    def test_root_final_ignores_descendant_other_session_tool_and_stderr_noise(self) -> None:
        for scenario in ("causal-noise", "stderr-noise"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                spec = self._spec(Path(temporary), scenario=scenario)
                transport = DeepSeekHarnessJsonRpcTransport(spec)
                transport.start()
                try:
                    result = transport.run_operation(
                        operation_id="operation-noise",
                        session_id=spec.dsh_session_id,
                        message="fake causal turn",
                    )
                    self.assertEqual(result.final_response, "turn-1")
                    self.assertTrue(result.trusted_final)
                    if scenario == "causal-noise":
                        self.assertGreaterEqual(result.descendant_notification_count, 1)
                finally:
                    transport.graceful_shutdown()
                if scenario == "stderr-noise":
                    self.assertGreater(transport.stderr_bytes_observed, 0)

    def test_prompt_disconnect_classification_is_ambiguous_and_never_retried(self) -> None:
        for scenario in ("prompt-eof-before-response", "receipt-then-eof", "nonzero-exit"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                spec = self._spec(Path(temporary), scenario=scenario)
                transport = DeepSeekHarnessJsonRpcTransport(spec)
                transport.start()
                if scenario == "prompt-eof-before-response":
                    with self.assertRaises(DeepSeekHarnessDeliveryError) as raised:
                        transport.run_operation(
                            operation_id="operation-disconnect",
                            session_id=spec.dsh_session_id,
                            message="single fake prompt",
                        )
                    self.assertTrue(raised.exception.ambiguous_delivery)
                else:
                    with self.assertRaises(DeepSeekHarnessContinuityError):
                        transport.run_operation(
                            operation_id="operation-disconnect",
                            session_id=spec.dsh_session_id,
                            message="single fake prompt",
                        )
                self.assertFalse(transport.is_alive())
                transport.force_terminate()

    def test_oversized_json_frame_is_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            spec = self._spec(
                Path(temporary),
                scenario="oversized-json",
                max_line_bytes=1024,
            )
            transport = DeepSeekHarnessJsonRpcTransport(spec)
            transport.start()
            with self.assertRaisesRegex(DeepSeekHarnessContinuityError, "oversized"):
                transport.run_operation(
                    operation_id="operation-oversized",
                    session_id=spec.dsh_session_id,
                    message="bounded fake prompt",
                )
            transport.force_terminate()

    def test_two_independent_clients_share_supervisor_generation_and_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec = self._spec(root)
            write_runtime_bootstrap(spec)
            started = launch_deepseek_harness_supervisor(spec)
            self.assertTrue(started["started"], started)
            state = started["runtimeState"]
            supervisor_pid = state["supervisorPid"]

            first = self._request(spec, "submit", {"message": "fake first"})
            self.assertTrue(first["ok"], first)
            second = self._subprocess_request(spec, "fake second")
            self.assertTrue(second["ok"], second)
            status = self._request(spec, "status", {})

            self.assertEqual(first["generationId"], spec.generation_id)
            self.assertEqual(second["generationId"], spec.generation_id)
            self.assertEqual(first["dshSessionId"], spec.dsh_session_id)
            self.assertEqual(second["dshSessionId"], spec.dsh_session_id)
            self.assertEqual(first["operation"]["finalResponse"], "turn-1")
            self.assertEqual(
                second["operation"]["finalResponse"],
                "turn-2; observed=turn-1",
            )
            self.assertEqual(status["runtimeState"]["supervisorPid"], supervisor_pid)
            self.assertEqual(status["statusAuthority"], "owned_live")

            stopped = self._request(
                spec,
                "stop",
                {"acknowledgeRuntimeStop": True},
            )
            self.assertFalse(stopped["continuityLost"])
            self.assertTrue(stopped["resumeRequired"])
            self.assertTrue(stopped["resumeAvailable"])
            self.assertFalse(stopped["requiresRecreate"])
            self._wait_for_supervisor_exit(spec)
            final_state = read_runtime_state(spec.paths.state_path)
            self.assertIn(final_state["lifecycle"], {"stopped", "continuity_lost"})
            with self.assertRaises(DeepSeekHarnessContinuityError):
                launch_deepseek_harness_supervisor(spec, startup_timeout_seconds=1)

    def test_different_handles_same_cwd_do_not_cross(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_spec = self._spec(root / "first", handle="one")
            second_spec = self._spec(root / "second", handle="two")
            write_runtime_bootstrap(first_spec)
            write_runtime_bootstrap(second_spec)
            self.assertTrue(launch_deepseek_harness_supervisor(first_spec)["started"])
            self.assertTrue(launch_deepseek_harness_supervisor(second_spec)["started"])
            try:
                first = self._request(first_spec, "submit", {"message": "fake"})
                second = self._request(second_spec, "submit", {"message": "fake"})
                self.assertNotEqual(first["runtimeId"], second["runtimeId"])
                self.assertNotEqual(first["dshSessionId"], second["dshSessionId"])
                self.assertEqual(first["operation"]["finalResponse"], "turn-1")
                self.assertEqual(second["operation"]["finalResponse"], "turn-1")
            finally:
                self._request(
                    first_spec,
                    "stop",
                    {"acknowledgeContinuityLoss": True},
                )
                self._wait_for_supervisor_exit(first_spec)
                self._request(
                    second_spec,
                    "stop",
                    {"acknowledgeContinuityLoss": True},
                )
                self._wait_for_supervisor_exit(second_spec)

    def test_same_persistent_session_rejects_a_second_live_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sessions = root / "shared-sessions"
            state = root / "shared-state"
            first_spec = self._spec(
                root / "first",
                handle="owner-one",
                dsh_session_id="shared-native-session",
                session_root=sessions,
                state_root=state,
            )
            second_spec = self._spec(
                root / "second",
                handle="owner-two",
                dsh_session_id="shared-native-session",
                session_root=sessions,
                state_root=state,
            )
            write_runtime_bootstrap(first_spec)
            write_runtime_bootstrap(second_spec)
            self.assertTrue(launch_deepseek_harness_supervisor(first_spec)["started"])
            try:
                rejected = launch_deepseek_harness_supervisor(
                    second_spec,
                    startup_timeout_seconds=3,
                )
                self.assertFalse(rejected["started"])
                self.assertEqual(
                    rejected["runtimeState"]["failureCategory"],
                    "session_owner_conflict",
                )
                self.assertTrue(self._request(first_spec, "status", {})["ok"])
            finally:
                self._request(
                    first_spec,
                    "stop",
                    {"acknowledgeRuntimeStop": True},
                )
                self._wait_for_supervisor_exit(first_spec)

    def test_busy_second_client_does_not_send_a_second_wire_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            spec = self._spec(Path(temporary), scenario="slow-operation")
            write_runtime_bootstrap(spec)
            self.assertTrue(launch_deepseek_harness_supervisor(spec)["started"])
            first_result: dict[str, object] = {}

            def first_submit() -> None:
                first_result.update(
                    self._request(spec, "submit", {"message": "fake first"})
                )

            thread = threading.Thread(target=first_submit)
            thread.start()
            self._wait_for_runtime_state(spec, "busy")
            second = self._request(spec, "submit", {"message": "must stay unwired"})
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
            self.assertEqual(second["failureCategory"], "target_runtime_busy")
            self.assertFalse(second["ambiguousDelivery"])
            self.assertTrue(first_result["ok"])
            third = self._request(spec, "submit", {"message": "fake next"})
            self.assertEqual(
                third["operation"]["finalResponse"],
                "turn-2; observed=turn-1",
            )
            self._request(spec, "stop", {"acknowledgeContinuityLoss": True})
            self._wait_for_supervisor_exit(spec)

    def test_owner_token_generation_and_duplicate_supervisor_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            spec = self._spec(Path(temporary))
            write_runtime_bootstrap(spec)
            self.assertTrue(launch_deepseek_harness_supervisor(spec)["started"])
            with self.assertRaises(DeepSeekHarnessContinuityError):
                launch_deepseek_harness_supervisor(spec, startup_timeout_seconds=1)

            wrong_generation = request_deepseek_harness_supervisor(
                state_path=spec.paths.state_path,
                token_path=spec.paths.token_path,
                method="status",
                workspace_id=spec.workspace_id,
                agent_id=spec.agent_id,
                handle_id=spec.handle_id,
                runtime_id=spec.runtime_id,
                generation_id="stale-generation",
                payload={},
            )
            self.assertEqual(
                wrong_generation["failureCategory"],
                "ipc_runtime_identity_rejected",
            )
            token_path = Path(spec.paths.token_path)
            owner_token = token_path.read_text(encoding="utf-8")
            token_path.write_text("stale-owner-token", encoding="utf-8")
            try:
                rejected = self._request(spec, "status", {})
                self.assertEqual(rejected["failureCategory"], "ipc_owner_token_rejected")
            finally:
                token_path.write_text(owner_token, encoding="utf-8")
            self._request(spec, "stop", {"acknowledgeContinuityLoss": True})
            self._wait_for_supervisor_exit(spec)
            stale = self._request(spec, "status", {})
            self.assertEqual(stale["failureCategory"], "runtime_stopped")
            self.assertTrue(stale["resumeAvailable"])

    def test_stale_operation_lease_marks_generation_continuity_lost(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            spec = self._spec(Path(temporary))
            write_runtime_bootstrap(spec)
            Path(spec.paths.operation_lease_path).write_text(
                '{"stale":true}',
                encoding="utf-8",
            )
            started = launch_deepseek_harness_supervisor(spec)
            self.assertFalse(started["started"])
            self.assertEqual(started["runtimeState"]["lifecycle"], "continuity_lost")
            self.assertEqual(
                started["runtimeState"]["failureCategory"],
                "stale_operation_lease",
            )

    def test_supervisor_crash_closes_runtime_and_same_generation_cannot_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            spec = self._spec(Path(temporary))
            write_runtime_bootstrap(spec)
            started = launch_deepseek_harness_supervisor(spec)
            self.assertTrue(started["started"])
            supervisor_pid = int(started["runtimeState"]["supervisorPid"])
            runtime_pid = int(started["runtimeState"]["runtimePid"])
            try:
                self._terminate_pid(supervisor_pid)
                deadline = time.monotonic() + 10
                lost: dict[str, object] = {}
                while time.monotonic() < deadline:
                    lost = dict(self._request(spec, "status", {}))
                    if (
                        lost.get("failureCategory") == "supervisor_unreachable"
                        and not self._pid_is_live(supervisor_pid)
                        and not self._pid_is_live(runtime_pid)
                    ):
                        break
                    time.sleep(0.05)
                self.assertEqual(lost["failureCategory"], "supervisor_unreachable")
                self.assertFalse(self._pid_is_live(runtime_pid))
                with self.assertRaises(DeepSeekHarnessContinuityError):
                    launch_deepseek_harness_supervisor(
                        spec,
                        startup_timeout_seconds=1,
                    )
            finally:
                if self._pid_is_live(runtime_pid):
                    self._terminate_pid(runtime_pid)

    def test_active_stop_marks_delivery_ambiguous_and_requires_acknowledged_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            spec = self._spec(Path(temporary), scenario="slow-operation")
            write_runtime_bootstrap(spec)
            self.assertTrue(launch_deepseek_harness_supervisor(spec)["started"])
            submit_result: dict[str, object] = {}

            def submit() -> None:
                submit_result.update(
                    self._request(spec, "submit", {"message": "fake active"})
                )

            thread = threading.Thread(target=submit)
            thread.start()
            self._wait_for_runtime_state(spec, "busy")
            rejected = self._request(spec, "stop", {"acknowledgeRuntimeStop": False})
            self.assertEqual(
                rejected["failureCategory"],
                "runtime_stop_acknowledgement_required",
            )
            stopped = self._request(
                spec,
                "stop",
                {"acknowledgeRuntimeStop": True},
            )
            self.assertEqual(stopped["stopMode"], "active_forced_termination")
            self.assertTrue(stopped["continuityLost"])
            self.assertTrue(stopped["ambiguousDelivery"])
            self.assertFalse(stopped["resumeAvailable"])
            self.assertTrue(
                stopped["resumeRequiresAmbiguousDeliveryAcknowledgement"]
            )
            self.assertFalse(stopped["requiresRecreate"])
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
            self._wait_for_supervisor_exit(spec)

    def test_runtime_state_and_handle_metadata_exclude_token_prompt_and_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            spec = self._spec(Path(temporary))
            token = write_runtime_bootstrap(spec)
            serialized_state = Path(spec.paths.state_path).read_text(encoding="utf-8")
            serialized_spec = Path(spec.paths.spec_path).read_text(encoding="utf-8")
            serialized_binding = json.dumps(runtime_handle_metadata(spec))
            for serialized in (serialized_state, serialized_spec, serialized_binding):
                self.assertNotIn(token, serialized)
                self.assertNotIn("fake first turn", serialized)
                self.assertNotIn("turn-1", serialized)
            self.assertFalse(json.loads(serialized_state)["credentialStored"])
            self.assertFalse(json.loads(serialized_state)["promptStored"])

    def test_exact_node_preflight_and_windows_python_route(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable for the optional carrier preflight fixture")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            versions = (
                "dsh",
                "dsh-agent-spine-demo",
                "dsh-bash-local",
                "dsh-session",
                "dsh-session-persistence-jsonl",
                "dsh-sdk-client",
                "dsh-sdk-protocol",
                "dsh-sdk-jsonrpc-server",
                "dsh-sdk-jsonrpc-demo",
            )
            for name in versions:
                package = root / "node_modules" / "@deepseek-ai" / name
                package.mkdir(parents=True, exist_ok=True)
                (package / "package.json").write_text(
                    json.dumps({"name": f"@deepseek-ai/{name}", "version": "0.1.1-rc.2"}),
                    encoding="utf-8",
                )
                if name in {
                    "dsh-sdk-client",
                    "dsh-sdk-protocol",
                    "dsh-sdk-jsonrpc-server",
                }:
                    public_entry = package / "lib" / "index.js"
                    public_entry.parent.mkdir(parents=True, exist_ok=True)
                    public_entry.write_text("export {};\n", encoding="utf-8")
            runtime_entry = (
                root
                / "node_modules"
                / "@deepseek-ai"
                / "dsh-sdk-jsonrpc-demo"
                / "lib"
                / "bin.js"
            )
            runtime_entry.parent.mkdir(parents=True, exist_ok=True)
            runtime_entry.write_text("// fake exact-version entry\n", encoding="utf-8")
            cordis = root / "cordis.yml"
            (root / "beacon-sdk-jsonrpc-server.mjs").write_text(
                "// preflight fixture only\n",
                encoding="utf-8",
            )
            (root / "session-probe.mjs").write_text(
                "// preflight fixture only\n",
                encoding="utf-8",
            )
            cordis.write_text(
                "- id: sdk-jsonrpc-server\n"
                "  name: './beacon-sdk-jsonrpc-server.mjs'\n",
                encoding="utf-8",
            )
            exact = preflight_deepseek_harness_runtime(
                carrier="node",
                executable_path=node,
                package_root=str(root),
                cordis_config_path=str(cordis),
            )
            self.assertTrue(exact["supported"], exact)
            self.assertEqual(exact["expectedPackageVersion"], "0.1.1-rc.2")
            self.assertEqual(exact["expectedServerVersion"], "0.0.1")
            self.assertEqual(exact["auditedCommit"], DEEPSEEK_HARNESS_AUDITED_COMMIT)
            mismatch_package = (
                root / "node_modules" / "@deepseek-ai" / "dsh" / "package.json"
            )
            mismatch_package.write_text(
                json.dumps({"name": "@deepseek-ai/dsh", "version": "0.1.1-rc.1"}),
                encoding="utf-8",
            )
            mismatch = preflight_deepseek_harness_runtime(
                carrier="node",
                executable_path=node,
                package_root=str(root),
                cordis_config_path=str(cordis),
            )
            self.assertFalse(mismatch["supported"])

            python_route = preflight_deepseek_harness_runtime(
                carrier="python",
                executable_path=sys.executable,
                package_root=str(root),
            )
            self.assertFalse(python_route["supported"])
            if os.name == "nt":
                self.assertFalse(python_route["platformSupported"])
                self.assertIn("do not support", python_route["platformReason"])

    def _request(self, spec, method: str, payload: dict[str, object]):
        return request_deepseek_harness_supervisor(
            state_path=spec.paths.state_path,
            token_path=spec.paths.token_path,
            method=method,
            workspace_id=spec.workspace_id,
            agent_id=spec.agent_id,
            handle_id=spec.handle_id,
            runtime_id=spec.runtime_id,
            generation_id=spec.generation_id,
            payload=payload,
            timeout_seconds=10,
        )

    def _subprocess_request(self, spec, message: str):
        script = (
            "import json,sys;"
            "from agent_os.application.services.deepseek_harness_managed_runtime "
            "import request_deepseek_harness_supervisor as r;"
            "print(json.dumps(r(state_path=sys.argv[1],token_path=sys.argv[2],"
            "method='submit',workspace_id=sys.argv[3],agent_id=sys.argv[4],"
            "handle_id=sys.argv[5],runtime_id=sys.argv[6],generation_id=sys.argv[7],"
            "payload={'message':sys.argv[8]},timeout_seconds=10)))"
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                spec.paths.state_path,
                spec.paths.token_path,
                spec.workspace_id,
                spec.agent_id,
                spec.handle_id,
                spec.runtime_id,
                spec.generation_id,
                message,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def _wait_for_supervisor_exit(self, spec) -> None:
        state = read_runtime_state(spec.paths.state_path)
        owned_pids = {
            int(pid)
            for pid in (state.get("supervisorPid"), state.get("runtimePid"))
            if isinstance(pid, int) and pid > 0
        }
        deadline = time.monotonic() + 10
        endpoint_released = False
        while time.monotonic() < deadline:
            result = self._request(spec, "status", {})
            if result.get("failureCategory") in {
                "runtime_stopped",
                "supervisor_unreachable",
            }:
                endpoint_released = True
            live_pids = {pid for pid in owned_pids if self._pid_is_live(pid)}
            if endpoint_released and not live_pids:
                return
            time.sleep(0.05)
        self.fail("DSH supervisor did not release its endpoint/processes after stop")

    def _wait_for_runtime_state(self, spec, expected: str) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            response = self._request(spec, "status", {})
            if response.get("status") == expected:
                return
            time.sleep(0.025)
        self.fail(f"DSH runtime did not reach {expected}")

    @staticmethod
    def _pid_is_live(pid: int) -> bool:
        if os.name == "nt":
            completed = subprocess.run(
                [
                    "tasklist",
                    "/FI",
                    f"PID eq {pid}",
                    "/FO",
                    "CSV",
                    "/NH",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            return completed.returncode == 0 and f'"{pid}"' in completed.stdout
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @staticmethod
    def _terminate_pid(pid: int) -> None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
            )
            return
        os.kill(pid, 9)


if __name__ == "__main__":
    unittest.main()
