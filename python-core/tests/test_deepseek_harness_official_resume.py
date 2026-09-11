from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

from agent_os.application.services.deepseek_harness_managed_runtime import (
    DeepSeekHarnessJsonRpcTransport,
    build_deepseek_harness_runtime_spec,
    preflight_deepseek_harness_runtime,
)
from agent_os.application.services.local_platform_application import (
    LocalPlatformApplication,
)
from agent_os.infrastructure.config import LocalPlatformSettings


BEACON_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = BEACON_ROOT / "integrations" / "deepseek-harness-node"
OFFLINE_CONFIG = PACKAGE_ROOT / "cordis.offline-test.yml"
RUNTIME_ENTRY = (
    PACKAGE_ROOT
    / "node_modules"
    / "@deepseek-ai"
    / "dsh-sdk-jsonrpc-demo"
    / "lib"
    / "bin.js"
)
PINNED_PACKAGE = (
    PACKAGE_ROOT / "node_modules" / "@deepseek-ai" / "dsh" / "package.json"
)


class DeepSeekHarnessOfficialResumeTests(unittest.TestCase):
    def test_exact_join_and_second_process_receive_real_persisted_history(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable for the official offline DSH integration")
        if not all(
            path.is_file()
            for path in (OFFLINE_CONFIG, RUNTIME_ENTRY, PINNED_PACKAGE)
        ):
            self.skipTest("the locked optional DSH carrier is not installed")
        package_version = json.loads(PINNED_PACKAGE.read_text(encoding="utf-8"))[
            "version"
        ]
        if package_version != "0.1.1-rc.2":
            self.skipTest("the installed DSH carrier does not match the audited pin")

        with tempfile.TemporaryDirectory(prefix="beacon-dsh-official-") as temporary:
            root = Path(temporary)
            project = root / "project with spaces"
            project.mkdir()
            session_root = root / "native-session-store"
            session_root.mkdir()
            native_session_id = "official-existing-session"

            # Establish a native persisted session before any Beacon workspace,
            # Agent, handle, or endpoint exists.
            external_spec = self._spec(
                node=node,
                root=root,
                project=project,
                session_root=session_root,
                session_id=native_session_id,
                start_mode="create",
                state_root=root / "external-transport-state",
                handle_id="external-unregistered-handle",
            )
            external = DeepSeekHarnessJsonRpcTransport(external_spec)
            external.start()
            try:
                first = external.run_operation(
                    operation_id="external-history-turn",
                    session_id=native_session_id,
                    message="OFFICIAL_ALPHA_HISTORY_MARKER",
                )
                first_payload = json.loads(first.final_response)
                self.assertIn(
                    "OFFICIAL_ALPHA_HISTORY_MARKER",
                    self._history_markers(first_payload),
                )
            finally:
                external.graceful_shutdown()

            probe = preflight_deepseek_harness_runtime(
                carrier="node",
                executable_path=node,
                package_root=str(PACKAGE_ROOT),
                cordis_config_path=str(OFFLINE_CONFIG),
                runtime_home=str(root / "runtime-home"),
                state_root=str(root / "managed-state"),
                session_root=str(session_root),
                session_id=native_session_id,
                session_start_mode="resume",
                session_compression="none",
            )
            self.assertTrue(probe["supported"], probe)
            self.assertTrue(probe["sessionProbe"]["found"])
            self.assertEqual(
                probe["sessionProbe"]["session"]["id"],
                native_session_id,
            )
            self.assertFalse(probe["sessionProbe"]["fullSessionHistoryRead"])

            app = self._app(root)
            self._seed_workspace(app, project)
            current_handle: dict[str, object] | None = None
            try:
                joined = app.join_deepseek_harness_agent(
                    workspace_id="workspace-official-resume",
                    agent_id="existing-dsh-agent",
                    cwd=str(project),
                    carrier="node",
                    executable_path=node,
                    package_root=str(PACKAGE_ROOT),
                    cordis_config_path=str(OFFLINE_CONFIG),
                    runtime_home=str(root / "runtime-home"),
                    runtime_home_source="isolated_offline_test",
                    state_root=str(root / "managed-state"),
                    session_root=str(session_root),
                    session_id=native_session_id,
                    session_compression="none",
                    model_provider="beacon-offline",
                    model="deterministic-history-echo",
                    reply_writeback_mode="provider_final_capture",
                    initialize_timeout_seconds=20,
                    operation_timeout_seconds=20,
                    shutdown_timeout_seconds=5,
                )
                self.assertTrue(joined["ok"], joined)
                self.assertTrue(joined["existingSessionImport"])
                current_handle = dict(joined["deepseekHarnessSessionHandle"])
                first_binding = current_handle["metadata"]["runtimeBinding"]

                beta = app.send_agent_dispatch(
                    workspace_id="workspace-official-resume",
                    dispatch_id="dispatch-official-beta",
                    exchange_request_id="request-official-beta",
                    from_endpoint_alias="source-codex",
                    to_endpoint_alias="existing-dsh-agent",
                    message="OFFICIAL_BETA_JOIN_MARKER",
                    delivery_mode="worker_execute",
                    read_live_runtime_status="enabled",
                    activation_timeout_seconds=30,
                )
                beta_final = beta["agentExchangeRequest"]["responseSummary"]
                beta_payload = json.loads(beta_final)
                beta_markers = self._history_markers(beta_payload)
                self.assertIn("OFFICIAL_ALPHA_HISTORY_MARKER", beta_markers)
                self.assertIn("OFFICIAL_BETA_JOIN_MARKER", beta_markers)
                self.assertIn(
                    "assistant",
                    self._marker_roles(
                        beta_payload,
                        "OFFICIAL_ALPHA_HISTORY_MARKER",
                    ),
                )

                stopped = app.stop_deepseek_harness_runtime(
                    workspace_id="workspace-official-resume",
                    handle_id=str(current_handle["handleId"]),
                    acknowledge_runtime_stop=True,
                    stopped_by="offline-integration-test",
                )
                self.assertFalse(stopped["continuityLost"])
                self.assertTrue(stopped["resumeAvailable"])
                self._wait_for_owned_processes(stopped)

                resumed = app.resume_deepseek_harness_runtime(
                    workspace_id="workspace-official-resume",
                    handle_id=str(current_handle["handleId"]),
                    resumed_by="offline-integration-test",
                )
                self.assertTrue(resumed["resumed"], resumed)
                self.assertFalse(resumed["requestReplayAttempted"])
                second_handle = dict(resumed["newHandle"])
                second_binding = second_handle["metadata"]["runtimeBinding"]
                self.assertEqual(
                    second_handle["deepseekHarnessSessionId"],
                    native_session_id,
                )
                self.assertEqual(second_handle["agentId"], "existing-dsh-agent")
                self.assertNotEqual(
                    second_handle["handleId"], current_handle["handleId"]
                )
                self.assertNotEqual(
                    second_binding["runtimeId"], first_binding["runtimeId"]
                )
                self.assertNotEqual(
                    second_binding["generationId"], first_binding["generationId"]
                )
                current_handle = second_handle

                gamma = app.send_agent_dispatch(
                    workspace_id="workspace-official-resume",
                    dispatch_id="dispatch-official-gamma",
                    exchange_request_id="request-official-gamma",
                    from_endpoint_alias="source-codex",
                    to_endpoint_alias="existing-dsh-agent",
                    message="OFFICIAL_GAMMA_RESUME_MARKER",
                    delivery_mode="worker_execute",
                    read_live_runtime_status="enabled",
                    activation_timeout_seconds=30,
                )
                gamma_payload = json.loads(
                    gamma["agentExchangeRequest"]["responseSummary"]
                )
                gamma_markers = self._history_markers(gamma_payload)
                self.assertIn("OFFICIAL_ALPHA_HISTORY_MARKER", gamma_markers)
                self.assertIn("OFFICIAL_BETA_JOIN_MARKER", gamma_markers)
                self.assertIn("OFFICIAL_GAMMA_RESUME_MARKER", gamma_markers)
                self.assertIn(
                    "assistant",
                    self._marker_roles(
                        gamma_payload,
                        "OFFICIAL_BETA_JOIN_MARKER",
                    ),
                )
                active_endpoints = app.list_agent_endpoints(
                    workspace_id="workspace-official-resume",
                    include_inactive=False,
                )["agentEndpoints"]
                endpoint = next(
                    item
                    for item in active_endpoints
                    if item["alias"] == "existing-dsh-agent"
                )
                self.assertEqual(endpoint["providerHandleId"], second_handle["handleId"])
            finally:
                if current_handle is not None:
                    self._stop_if_live(app, current_handle)

    @staticmethod
    def _spec(
        *,
        node: str,
        root: Path,
        project: Path,
        session_root: Path,
        session_id: str,
        start_mode: str,
        state_root: Path,
        handle_id: str,
    ):
        return build_deepseek_harness_runtime_spec(
            workspace_id="unregistered-external-workspace",
            agent_id="unregistered-external-agent",
            handle_id=handle_id,
            dsh_session_id=session_id,
            session_start_mode=start_mode,
            session_compression="none",
            cwd=str(project),
            session_root=str(session_root),
            runtime_home=str(root / "external-runtime-home"),
            runtime_home_source="isolated_offline_test",
            carrier="node",
            executable_path=node,
            launch_args=(node, str(RUNTIME_ENTRY), str(OFFLINE_CONFIG)),
            cordis_config_path=str(OFFLINE_CONFIG),
            package_root=str(PACKAGE_ROOT),
            package_version="0.1.1-rc.2",
            expected_server_version="0.0.1",
            model_provider="beacon-offline",
            model="deterministic-history-echo",
            state_root=str(state_root),
            initialize_timeout_seconds=20,
            operation_timeout_seconds=20,
            shutdown_timeout_seconds=5,
        )

    @staticmethod
    def _history(payload: dict[str, object]) -> list[dict[str, object]]:
        history = payload.get("history")
        if not isinstance(history, list):
            raise AssertionError(f"offline adapter response omitted history: {payload!r}")
        return [item for item in history if isinstance(item, dict)]

    @classmethod
    def _history_markers(cls, payload: dict[str, object]) -> set[str]:
        return {
            str(marker)
            for item in cls._history(payload)
            for marker in item.get("markers", [])
            if isinstance(marker, str)
        }

    @classmethod
    def _marker_roles(
        cls,
        payload: dict[str, object],
        marker: str,
    ) -> set[str]:
        return {
            str(item.get("role"))
            for item in cls._history(payload)
            if marker in item.get("markers", [])
        }

    @staticmethod
    def _app(root: Path) -> LocalPlatformApplication:
        return LocalPlatformApplication(
            LocalPlatformSettings(
                database=str(root / "platform.sqlite3"),
                workspace_root=str(root / "platform-workspace"),
                plugins_directory=str(root / "plugins"),
            )
        )

    @staticmethod
    def _seed_workspace(app: LocalPlatformApplication, project: Path) -> None:
        app.create_workspace(
            workspace_id="workspace-official-resume",
            display_name="Official offline DSH resume",
            root_path=str(project),
            agent_id="source-agent",
        )
        app.register_codex_session_handle(
            workspace_id="workspace-official-resume",
            agent_id="source-agent",
            handle_id="source-codex-handle",
            codex_session_id="source-codex-session",
            cwd=str(project),
            created_by="test",
            reason="offline identity source",
        )
        app.login_agent_endpoint(
            workspace_id="workspace-official-resume",
            agent_id="source-agent",
            alias="source-codex",
            provider="codex",
            provider_handle_id="source-codex-handle",
            direction="send_only",
            created_by="test",
            reason="offline identity source",
        )

    def _stop_if_live(
        self,
        app: LocalPlatformApplication,
        handle: dict[str, object],
    ) -> None:
        latest = app.get_deepseek_harness_session_handle(
            workspace_id="workspace-official-resume",
            handle_id=str(handle["handleId"]),
        )["deepseekHarnessSessionHandle"]
        if latest.get("state") != "active":
            return
        stopped = app.stop_deepseek_harness_runtime(
            workspace_id="workspace-official-resume",
            handle_id=str(handle["handleId"]),
            acknowledge_runtime_stop=True,
            stopped_by="offline-integration-cleanup",
        )
        self._wait_for_owned_processes(stopped)

    def _wait_for_owned_processes(self, stopped: dict[str, object]) -> None:
        state = stopped.get("supervisorResponse", {}).get("runtimeState", {})
        pids = {
            int(pid)
            for pid in (state.get("supervisorPid"), state.get("runtimePid"))
            if isinstance(pid, int) and pid > 0
        }
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if not any(self._pid_is_live(pid) for pid in pids):
                return
            time.sleep(0.05)
        self.fail(f"owned DSH processes did not exit: {sorted(pids)}")

    @staticmethod
    def _pid_is_live(pid: int) -> bool:
        if os.name == "nt":
            completed = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
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


if __name__ == "__main__":
    unittest.main()
