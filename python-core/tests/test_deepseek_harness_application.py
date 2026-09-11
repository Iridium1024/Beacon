from __future__ import annotations

import json
import sys
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_os.application.services.local_platform_application import (
    LocalPlatformApplication,
)
from agent_os.infrastructure.config import LocalPlatformSettings


FIXTURE = Path(__file__).parent / "fixtures" / "fake_deepseek_harness_runtime.py"
PREFLIGHT_TARGET = (
    "agent_os.application.services.local_platform_application."
    "preflight_deepseek_harness_runtime"
)


class DeepSeekHarnessApplicationTests(unittest.TestCase):
    def test_join_direct_send_owned_status_and_provider_final_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self._app(root)
            self._seed_source(app, root)
            with patch(PREFLIGHT_TARGET, return_value=self._preflight(root)):
                joined = self._join(
                    app,
                    root,
                    reply_writeback_mode="provider_final_capture",
                )
            handle = joined["deepseekHarnessSessionHandle"]
            try:
                self.assertTrue(joined["dispatchReady"])
                self.assertFalse(joined["existingSessionImport"])
                self.assertFalse(joined["authenticatedRealModelSmokeRun"])
                self.assertEqual(joined["provider"], "deepseek_harness")
                self.assertEqual(
                    joined["providerBackendSelection"]["effectiveBackend"],
                    "deepseek_harness_sdk_stdio",
                )
                self.assertEqual(
                    handle["metadata"]["runtimeBinding"]["continuityScope"],
                    "persistent_native_session",
                )
                self.assertEqual(
                    Path(handle["metadata"]["runtimeBinding"]["sessionRoot"]).name,
                    joined["nativeSessionId"],
                )

                owned_status = app.get_deepseek_harness_runtime_status(
                    workspace_id="workspace-dsh",
                    handle_id=handle["handleId"],
                )
                self.assertEqual(owned_status["statusAuthority"], "owned_live")
                self.assertTrue(owned_status["runtimeStatus"]["runtimeProcessLive"])

                sent = app.send_agent_dispatch(
                    workspace_id="workspace-dsh",
                    dispatch_id="dispatch-dsh-direct",
                    exchange_request_id="request-dsh-direct",
                    from_endpoint_alias="source-codex",
                    to_endpoint_alias="target-dsh",
                    message="fake ordinary Beacon send",
                    delivery_mode="worker_execute",
                    read_live_runtime_status="enabled",
                    activation_timeout_seconds=15,
                )
                self.assertEqual(sent["agentDispatch"]["status"], "completed")
                self.assertTrue(
                    sent["agentDispatch"]["providerRuntimeStateSupported"]
                )
                self.assertTrue(sent["agentDispatch"]["providerRuntimeStatusRead"])
                self.assertEqual(
                    sent["agentExchangeRequest"]["responseSummary"],
                    "turn-1",
                )
                item = sent["workerRun"]["agentDispatches"][0]
                self.assertEqual(
                    item["providerBackendSelection"]["effectiveBackend"],
                    "deepseek_harness_sdk_stdio",
                )
                self.assertTrue(item["activation"]["responseInstanceVerified"])
                self.assertEqual(
                    item["activation"]["responseCaptureStatus"],
                    "recorded",
                )
            finally:
                self._stop_if_live(app, handle)

    def test_explicit_only_queue_then_worker_leaves_response_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self._app(root)
            self._seed_source(app, root)
            with patch(PREFLIGHT_TARGET, return_value=self._preflight(root)):
                joined = self._join(app, root, reply_writeback_mode="explicit_only")
            handle = joined["deepseekHarnessSessionHandle"]
            try:
                queued = app.send_agent_dispatch(
                    workspace_id="workspace-dsh",
                    dispatch_id="dispatch-dsh-queued",
                    exchange_request_id="request-dsh-queued",
                    from_endpoint_alias="source-codex",
                    to_endpoint_alias="target-dsh",
                    message="fake queued Beacon send",
                    delivery_mode="queued",
                )
                self.assertEqual(queued["agentDispatch"]["status"], "queued")
                worker = app.run_agent_dispatch_worker_once(
                    workspace_id="workspace-dsh",
                    dispatch_id="dispatch-dsh-queued",
                    dispatcher_id="dsh-test-worker",
                    limit=1,
                    read_live_runtime_status="enabled",
                    activation_timeout_seconds=15,
                )
                item = worker["agentDispatches"][0]
                self.assertEqual(item["finalStatus"], "waiting_response")
                self.assertEqual(
                    item["activation"]["responseCaptureStatus"],
                    "explicit_only",
                )
                status = app.get_agent_dispatch_status(
                    workspace_id="workspace-dsh",
                    dispatch_id="dispatch-dsh-queued",
                    read_live_runtime_status="enabled",
                )
                self.assertEqual(status["agentExchangeRequest"]["status"], "active")
                self.assertIsNone(
                    status["agentExchangeRequest"].get("responseSummary")
                )
            finally:
                self._stop_if_live(app, handle)

    def test_exact_existing_join_is_idempotent_and_clean_stop_resumes_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self._app(root)
            self._seed_source(app, root)
            with patch(PREFLIGHT_TARGET, return_value=self._preflight(root)):
                joined = self._join(
                    app,
                    root,
                    session_id="fixture-existing-session",
                )
                repeated = self._join(
                    app,
                    root,
                    session_id="fixture-existing-session",
                )
            old = joined["deepseekHarnessSessionHandle"]
            old_binding = old["metadata"]["runtimeBinding"]
            self.assertTrue(joined["existingSessionImport"])
            self.assertEqual(joined["sessionSelection"], "exact_id")
            self.assertTrue(repeated["reused"])
            self.assertEqual(repeated["deepseekHarnessSessionHandle"]["handleId"], old["handleId"])
            for expected, override in (
                ("sessionCompression", {"session_compression": "none"}),
                ("sessionRoot", {"session_root": str(root / "other-sessions")}),
                ("runtimeHome", {"runtime_home": str(root / "other-runtime-home")}),
                ("modelProvider", {"model_provider": "other-model-provider"}),
                ("replyWritebackMode", {"reply_writeback_mode": "provider_final_capture"}),
            ):
                with self.subTest(conflict=expected):
                    with self.assertRaisesRegex(ValueError, expected):
                        self._join(
                            app,
                            root,
                            session_id="fixture-existing-session",
                            **override,
                        )

            stopped = app.stop_deepseek_harness_runtime(
                workspace_id="workspace-dsh",
                handle_id=str(old["handleId"]),
                acknowledge_runtime_stop=True,
                stopped_by="test",
            )
            self.assertFalse(stopped["continuityLost"])
            self.assertTrue(stopped["resumeAvailable"])
            stopped_status = app.get_deepseek_harness_runtime_status(
                workspace_id="workspace-dsh",
                handle_id=str(old["handleId"]),
            )
            self.assertFalse(stopped_status["continuityLost"])
            self.assertTrue(stopped_status["resumeRequired"])
            self.assertTrue(stopped_status["resumeAvailable"])
            self.assertEqual(stopped_status["runtimeStatus"]["status"], "stopped")
            with patch(PREFLIGHT_TARGET, return_value=self._preflight(root)):
                resumed = app.resume_deepseek_harness_runtime(
                    workspace_id="workspace-dsh",
                    handle_id=str(old["handleId"]),
                    resumed_by="test",
                )
            new = resumed["newHandle"]
            new_binding = new["metadata"]["runtimeBinding"]
            try:
                self.assertTrue(resumed["resumed"])
                self.assertTrue(resumed["sameNativeSessionId"])
                self.assertFalse(resumed["requestReplayAttempted"])
                self.assertEqual(new["agentId"], old["agentId"])
                self.assertEqual(
                    new["deepseekHarnessSessionId"],
                    old["deepseekHarnessSessionId"],
                )
                self.assertNotEqual(new["handleId"], old["handleId"])
                self.assertNotEqual(new_binding["runtimeId"], old_binding["runtimeId"])
                self.assertNotEqual(
                    new_binding["generationId"],
                    old_binding["generationId"],
                )
                endpoints = app.list_agent_endpoints(
                    workspace_id="workspace-dsh",
                    include_inactive=False,
                )["agentEndpoints"]
                rebound = next(item for item in endpoints if item["alias"] == "target-dsh")
                self.assertEqual(rebound["providerHandleId"], new["handleId"])
            finally:
                self._stop_if_live(app, new)

    def test_unknown_exact_session_and_persisted_cwd_conflict_fail_before_registration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self._app(root)
            self._seed_source(app, root)
            missing = {
                **self._preflight(root),
                "supported": False,
                "failures": ["exact DSH session was not found"],
                "sessionProbe": {
                    "ok": False,
                    "found": False,
                    "failureCategory": "session_not_found",
                    "fullSessionHistoryRead": False,
                },
            }
            with patch(PREFLIGHT_TARGET, return_value=missing):
                failed = self._join(app, root, session_id="unknown-native-session")
            self.assertFalse(failed["ok"])
            self.assertEqual(failed["failedStage"], "runtimePreflight")
            self.assertFalse(failed["writesApplied"])

            other_cwd = root / "other-cwd"
            other_cwd.mkdir()
            conflict = {
                **self._preflight(root),
                "sessionProbe": {
                    "ok": True,
                    "found": True,
                    "session": {
                        "id": "fixture-existing-session",
                        "cwd": str(other_cwd),
                    },
                    "fullSessionHistoryRead": False,
                },
            }
            with patch(PREFLIGHT_TARGET, return_value=conflict):
                with self.assertRaisesRegex(ValueError, "cwd conflicts"):
                    self._join(
                        app,
                        root,
                        session_id="fixture-existing-session",
                    )
            self.assertIsNone(
                app._find_workspace_agent(
                    workspace_id="workspace-dsh",
                    agent_id="target-dsh",
                )
            )

    def test_ambiguous_previous_delivery_requires_acknowledgement_and_is_not_replayed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self._app(root)
            self._seed_source(app, root)
            with patch(PREFLIGHT_TARGET, return_value=self._preflight(root)):
                joined = self._join(
                    app,
                    root,
                    session_id="fixture-existing-session",
                )
            old = joined["deepseekHarnessSessionHandle"]
            stopped = app.stop_deepseek_harness_runtime(
                workspace_id="workspace-dsh",
                handle_id=str(old["handleId"]),
                acknowledge_runtime_stop=True,
                stopped_by="test",
            )
            state_path = Path(
                old["metadata"]["runtimeBinding"]["runtimeStatePath"]
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["ambiguousDelivery"] = True
            state["continuityLossReason"] = "test_ambiguous_delivery"
            state_path.write_text(
                json.dumps(state, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "ambiguous delivery"):
                app.resume_deepseek_harness_runtime(
                    workspace_id="workspace-dsh",
                    handle_id=str(old["handleId"]),
                )
            with patch(PREFLIGHT_TARGET, return_value=self._preflight(root)):
                resumed = app.resume_deepseek_harness_runtime(
                    workspace_id="workspace-dsh",
                    handle_id=str(old["handleId"]),
                    acknowledge_ambiguous_delivery=True,
                    resumed_by="test",
                )
            self.assertTrue(resumed["ok"], resumed["join"])
            new = resumed["newHandle"]
            self.assertIsInstance(new, dict)
            try:
                self.assertTrue(stopped["resumeRequired"])
                self.assertTrue(resumed["ambiguousDeliveryAcknowledged"])
                self.assertFalse(resumed["requestReplayAttempted"])
            finally:
                self._stop_if_live(app, new)

    def test_preflight_or_initialize_failure_never_registers_visible_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self._app(root)
            self._seed_source(app, root)
            unsupported = {**self._preflight(root), "supported": False, "failures": ["fixture"]}
            with patch(PREFLIGHT_TARGET, return_value=unsupported):
                preflight_failed = self._join(app, root)
            self.assertFalse(preflight_failed["ok"])
            self.assertEqual(preflight_failed["failedStage"], "runtimePreflight")
            self.assertIsNone(
                app._find_workspace_agent(
                    workspace_id="workspace-dsh",
                    agent_id="target-dsh",
                )
            )

            bad_initialize = self._preflight(
                root,
                launch_args=(
                    sys.executable,
                    str(FIXTURE),
                    "--server-version",
                    "0.0.0-test",
                ),
            )
            with patch(PREFLIGHT_TARGET, return_value=bad_initialize):
                initialize_failed = self._join(app, root)
            self.assertFalse(initialize_failed["ok"])
            self.assertEqual(initialize_failed["failedStage"], "runtimeInitialize")
            self.assertFalse(initialize_failed["platformRegistrationWritesApplied"])
            self.assertIsNone(
                app._find_workspace_agent(
                    workspace_id="workspace-dsh",
                    agent_id="target-dsh",
                )
            )
            endpoints = app.list_agent_endpoints(
                workspace_id="workspace-dsh",
                include_inactive=True,
            )["agentEndpoints"]
            self.assertFalse(any(item["alias"] == "target-dsh" for item in endpoints))
            handles = app.list_deepseek_harness_session_handles(
                workspace_id="workspace-dsh",
                include_inactive=True,
            )["deepseekHarnessSessionHandles"]
            self.assertEqual(handles, [])

    def test_explicit_recreate_mints_new_handle_session_runtime_and_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self._app(root)
            self._seed_source(app, root)
            with patch(PREFLIGHT_TARGET, return_value=self._preflight(root)):
                joined = self._join(app, root)
            old = joined["deepseekHarnessSessionHandle"]
            old_binding = old["metadata"]["runtimeBinding"]
            recreated = app.recreate_deepseek_harness_runtime(
                workspace_id="workspace-dsh",
                handle_id=old["handleId"],
                acknowledge_continuity_loss=True,
                recreated_by="test",
            )
            new = recreated["newHandle"]
            new_binding = new["metadata"]["runtimeBinding"]
            try:
                self.assertTrue(recreated["ok"])
                self.assertTrue(recreated["oldSessionTerminal"])
                self.assertFalse(recreated["oldSessionIdReused"])
                self.assertNotEqual(old["handleId"], new["handleId"])
                self.assertNotEqual(
                    old["deepseekHarnessSessionId"],
                    new["deepseekHarnessSessionId"],
                )
                self.assertNotEqual(old_binding["runtimeId"], new_binding["runtimeId"])
                self.assertNotEqual(
                    old_binding["generationId"],
                    new_binding["generationId"],
                )
                old_terminal = app.get_deepseek_harness_session_handle(
                    workspace_id="workspace-dsh",
                    handle_id=old["handleId"],
                )["deepseekHarnessSessionHandle"]
                self.assertEqual(old_terminal["state"], "inactive")
                self.assertEqual(recreated["newEndpoint"]["alias"], "target-dsh")
            finally:
                self._stop_if_live(app, new)

    def test_owned_status_marks_handle_continuity_lost_after_supervisor_crash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self._app(root)
            self._seed_source(app, root)
            with patch(PREFLIGHT_TARGET, return_value=self._preflight(root)):
                joined = self._join(app, root)
            handle = joined["deepseekHarnessSessionHandle"]
            runtime_state = joined["runtime"]
            supervisor_pid = int(runtime_state["supervisorPid"])
            runtime_pid = int(runtime_state["runtimePid"])
            self._terminate_pid(supervisor_pid)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and self._pid_is_live(runtime_pid):
                time.sleep(0.05)
            status = app.get_deepseek_harness_runtime_status(
                workspace_id="workspace-dsh",
                handle_id=str(handle["handleId"]),
            )
            self.assertTrue(status["continuityLost"])
            self.assertTrue(status["resumeRequired"])
            self.assertTrue(status["resumeAvailable"])
            self.assertFalse(status["requiresRecreate"])
            self.assertIsNotNone(status["handleTransition"])
            terminal = app.get_deepseek_harness_session_handle(
                workspace_id="workspace-dsh",
                handle_id=str(handle["handleId"]),
            )["deepseekHarnessSessionHandle"]
            self.assertEqual(terminal["state"], "continuity_lost")
            if self._pid_is_live(runtime_pid):
                self._terminate_pid(runtime_pid)

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
    def _seed_source(app: LocalPlatformApplication, root: Path) -> None:
        app.create_workspace(
            workspace_id="workspace-dsh",
            display_name="DSH Fixture Workspace",
            root_path=str(root),
            agent_id="source-agent",
        )
        app.register_codex_session_handle(
            workspace_id="workspace-dsh",
            agent_id="source-agent",
            handle_id="source-codex-handle",
            codex_session_id="source-codex-session",
            cwd=str(root),
            created_by="test",
            reason="fake source identity only",
        )
        app.login_agent_endpoint(
            workspace_id="workspace-dsh",
            agent_id="source-agent",
            alias="source-codex",
            provider="codex",
            provider_handle_id="source-codex-handle",
            direction="send_only",
            created_by="test",
            reason="fake source endpoint",
        )

    @staticmethod
    def _preflight(
        root: Path,
        *,
        launch_args: tuple[str, ...] | None = None,
    ) -> dict[str, object]:
        return {
            "schema": "deepseek_harness_preflight.v1",
            "supported": True,
            "carrier": "fixture",
            "expectedPackageVersion": "0.1.1-rc.2",
            "auditedCommit": "b150a551b8d465e31e418e1b2eaf5e79bbb7d28e",
            "launchArgs": list(
                launch_args
                or (sys.executable, str(FIXTURE), "--scenario", "normal")
            ),
            "packageRoot": str(root),
            "credentialsRead": False,
            "globalInstallAttempted": False,
            "failures": [],
            "sessionProbe": {
                "schema": "deepseek_harness_session_probe.v1",
                "ok": True,
                "found": True,
                "session": {
                    "id": "fixture-existing-session",
                    "cwd": str(root),
                },
                "fullSessionHistoryRead": False,
            },
        }

    @staticmethod
    def _join(
        app: LocalPlatformApplication,
        root: Path,
        *,
        reply_writeback_mode: str = "explicit_only",
        session_id: str | None = None,
        **overrides: object,
    ) -> dict[str, object]:
        parameters: dict[str, object] = {
            "workspace_id": "workspace-dsh",
            "agent_id": "target-dsh",
            "cwd": str(root),
            "carrier": "fixture",
            "executable_path": sys.executable,
            "package_root": str(root),
            "cordis_config_path": None,
            "runtime_home": str(root / "isolated-runtime-home"),
            "runtime_home_source": "test_fixture",
            "state_root": str(root / "runtime-state"),
            "session_root": str(root / "session-roots"),
            "session_id": session_id,
            "model_provider": "deepseek",
            "model": "deepseek-chat",
            "reply_writeback_mode": reply_writeback_mode,
            "initialize_timeout_seconds": 5,
            "operation_timeout_seconds": 5,
            "shutdown_timeout_seconds": 2,
        }
        parameters.update(overrides)
        return dict(
            app.join_deepseek_harness_agent(**parameters)  # type: ignore[arg-type]
        )

    @staticmethod
    def _stop_if_live(
        app: LocalPlatformApplication,
        handle: dict[str, object] | None,
    ) -> None:
        if handle is None:
            return
        if handle.get("state") != "active":
            return
        try:
            stopped = app.stop_deepseek_harness_runtime(
                workspace_id="workspace-dsh",
                handle_id=str(handle["handleId"]),
                acknowledge_continuity_loss=True,
                stopped_by="test-cleanup",
            )
        except (OSError, ValueError):
            return
        runtime_state = stopped["supervisorResponse"].get("runtimeState") or {}
        owned_pids = {
            int(pid)
            for pid in (
                runtime_state.get("supervisorPid"),
                runtime_state.get("runtimePid"),
            )
            if isinstance(pid, int) and pid > 0
        }
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if not any(
                DeepSeekHarnessApplicationTests._pid_is_live(pid)
                for pid in owned_pids
            ):
                return
            time.sleep(0.05)

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
