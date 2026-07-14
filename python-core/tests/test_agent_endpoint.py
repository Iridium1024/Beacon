from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"

if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.local_platform_application import (
    LocalPlatformApplication,
)
from agent_os.application.services.agent_provider_runtime_status import (
    build_agent_provider_runtime_status,
)
from agent_os.infrastructure.config import LocalPlatformSettings


class AgentEndpointApplicationTests(unittest.TestCase):
    def test_endpoint_login_binds_active_provider_handle_and_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = _app(root)
            _seed_workspace(app, root)
            app.register_codex_session_handle(
                workspace_id="workspace-endpoint",
                agent_id="agent-a",
                handle_id="codex-handle-1",
                codex_session_id="codex-session-1",
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )

            result = app.login_agent_endpoint(
                workspace_id="workspace-endpoint",
                agent_id="agent-a",
                endpoint_id="endpoint-codex-main",
                alias="Codex-Main",
                provider="codex-cli",
                provider_handle_id="codex-handle-1",
                direction="send_receive",
                created_by="user",
                reason="current Codex test endpoint",
            )

            endpoint = result["agentEndpoint"]
            self.assertTrue(result["loggedIn"])
            self.assertEqual(endpoint["schema"], "agent_endpoint.v1")
            self.assertEqual(endpoint["endpointId"], "endpoint-codex-main")
            self.assertEqual(endpoint["alias"], "codex-main")
            self.assertEqual(endpoint["agentId"], "agent-a")
            self.assertEqual(endpoint["provider"], "codex")
            self.assertEqual(endpoint["providerHandleId"], "codex-handle-1")
            self.assertEqual(endpoint["defaultReplyPolicy"], "source_handle_required")
            self.assertTrue(endpoint["providerSessionHandleBound"])
            self.assertFalse(endpoint["credentialStored"])
            self.assertFalse(endpoint["realRuntimePresenceRead"])
            self.assertEqual(result["providerHandle"]["handleId"], "codex-handle-1")
            self.assertEqual(
                result["endpointSemantics"]["providerHandleId"],
                "codex-handle-1",
            )
            self.assertTrue(result["endpointSemantics"]["providerSessionHandleBound"])
            self.assertFalse(result["endpointSemantics"]["credentialStored"])
            self.assertFalse(
                result["endpointSemantics"]["providerAccountAuthenticated"]
            )

            listed = app.list_agent_endpoints(workspace_id="workspace-endpoint")
            self.assertEqual(listed["count"], 1)
            self.assertEqual(listed["agentEndpoints"][0]["alias"], "codex-main")
            fetched = app.get_agent_endpoint(
                workspace_id="workspace-endpoint",
                alias="codex-main",
            )
            self.assertEqual(
                fetched["agentEndpoint"]["endpointId"],
                "endpoint-codex-main",
            )

            with self.assertRaisesRegex(ValueError, "alias is already active"):
                app.login_agent_endpoint(
                    workspace_id="workspace-endpoint",
                    agent_id="agent-a",
                    alias="codex-main",
                    provider="codex",
                    provider_handle_id="codex-handle-1",
                    created_by="user",
                    reason="duplicate alias",
                )

            deactivated = app.deactivate_agent_endpoint(
                workspace_id="workspace-endpoint",
                alias="codex-main",
                deactivated_by="user",
                reason="test cleanup",
            )
            self.assertTrue(deactivated["deactivated"])
            self.assertEqual(deactivated["agentEndpoint"]["state"], "inactive")
            self.assertEqual(
                app.list_agent_endpoints(workspace_id="workspace-endpoint")["count"],
                0,
            )
            self.assertEqual(
                app.list_agent_endpoints(
                    workspace_id="workspace-endpoint",
                    include_inactive=True,
                )["count"],
                1,
            )

    def test_endpoint_login_requires_active_matching_provider_handle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = _app(root)
            _seed_workspace(app, root)
            app.create_agent(
                workspace_id="workspace-endpoint",
                agent_id="agent-b",
                name="Agent B",
                description="Other agent.",
            )
            app.register_codex_session_handle(
                workspace_id="workspace-endpoint",
                agent_id="agent-a",
                handle_id="codex-handle-1",
                codex_session_id="codex-session-1",
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )

            with self.assertRaisesRegex(ValueError, "agentId does not match"):
                app.login_agent_endpoint(
                    workspace_id="workspace-endpoint",
                    agent_id="agent-b",
                    alias="codex-main",
                    provider="codex",
                    provider_handle_id="codex-handle-1",
                    created_by="user",
                    reason="wrong agent",
                )

            app.deactivate_codex_session_handle(
                workspace_id="workspace-endpoint",
                handle_id="codex-handle-1",
                deactivated_by="user",
                reason="test inactive handle",
            )
            with self.assertRaisesRegex(ValueError, "provider handle is not active"):
                app.login_agent_endpoint(
                    workspace_id="workspace-endpoint",
                    agent_id="agent-a",
                    alias="codex-main",
                    provider="codex",
                    provider_handle_id="codex-handle-1",
                    created_by="user",
                    reason="inactive handle",
                )

    def test_endpoint_status_summarizes_inbox_outbox_and_reply_reachability(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = _app(root)
            _seed_workspace(app, root)
            app.create_agent(
                workspace_id="workspace-endpoint",
                agent_id="agent-b",
                name="Agent B",
                description="Target agent.",
            )
            app.register_codex_session_handle(
                workspace_id="workspace-endpoint",
                agent_id="agent-a",
                handle_id="codex-source-handle",
                codex_session_id="codex-source-session",
                cwd=str(root),
                created_by="user",
                reason="source endpoint fixture",
            )
            app.register_hermes_session_handle(
                workspace_id="workspace-endpoint",
                agent_id="agent-b",
                handle_id="hermes-target-handle",
                hermes_session_id="hermes-target-session",
                cwd=str(root),
                created_by="user",
                reason="target endpoint fixture",
            )
            app.login_agent_endpoint(
                workspace_id="workspace-endpoint",
                agent_id="agent-a",
                alias="codex-source",
                provider="codex",
                provider_handle_id="codex-source-handle",
                direction="send_only",
                default_reply_policy="source_handle_required",
                created_by="user",
                reason="source endpoint login",
            )
            app.login_agent_endpoint(
                workspace_id="workspace-endpoint",
                agent_id="agent-b",
                alias="hermes-target",
                provider="hermes",
                provider_handle_id="hermes-target-handle",
                direction="receive_only",
                created_by="user",
                reason="target endpoint login",
            )

            sent = app.send_agent_dispatch(
                workspace_id="workspace-endpoint",
                dispatch_id="dispatch-endpoint-status",
                exchange_request_id="req-endpoint-status",
                from_endpoint_alias="codex-source",
                to_endpoint_alias="hermes-target",
                request_kind="review",
                request_summary="Review endpoint status.",
            )
            app.record_agent_dispatch_daemon_liveness(
                workspace_id="workspace-endpoint",
                dispatcher_id="agent-dispatch-daemon",
                state="running",
                profile_path=str(root / "agent os profile.json"),
                pid=8765,
                started_at="2026-07-01T00:00:00+00:00",
                last_heartbeat_at="2026-07-01T00:00:01+00:00",
                last_poll_at="2026-07-01T00:00:01+00:00",
            )

            source_status = app.get_agent_endpoint_status(
                workspace_id="workspace-endpoint",
                alias="codex-source",
            )
            target_status = app.get_agent_endpoint_status(
                workspace_id="workspace-endpoint",
                alias="hermes-target",
            )

            self.assertEqual(source_status["schema"], "agent_endpoint_status.v1")
            self.assertEqual(
                source_status["endpointSemantics"]["endpointAlias"],
                "codex-source",
            )
            self.assertEqual(
                source_status["endpointSemantics"]["providerHandleId"],
                "codex-source-handle",
            )
            self.assertIn(
                "not a provider account authentication",
                source_status["endpointSemantics"]["endpointLoginMeaning"],
            )
            self.assertFalse(source_status["endpointSemantics"]["credentialStored"])
            self.assertFalse(
                source_status["endpointSemantics"]["runtimeProbe"][
                    "readLiveRuntimeStatusRequested"
                ]
            )
            self.assertTrue(source_status["replyReachability"]["canSend"])
            self.assertFalse(source_status["replyReachability"]["canReceive"])
            self.assertEqual(source_status["summary"]["outboxTotal"], 1)
            self.assertEqual(source_status["summary"]["inboxTotal"], 0)
            self.assertEqual(source_status["outbox"]["count"], 1)
            self.assertEqual(
                source_status["outbox"]["agentDispatches"][0]["agentDispatch"][
                    "dispatchId"
                ],
                sent["agentDispatch"]["dispatchId"],
            )
            self.assertEqual(target_status["summary"]["inboxTotal"], 1)
            self.assertEqual(target_status["summary"]["outboxTotal"], 0)
            self.assertFalse(target_status["replyReachability"]["canSend"])
            self.assertTrue(target_status["replyReachability"]["canReceive"])
            self.assertEqual(
                target_status["inbox"]["agentDispatches"][0]["wakeStatus"][
                    "ticketDeliveryOccurred"
                ],
                False,
            )
            self.assertTrue(
                target_status["respondPermissionProfile"]["canReadIncomingRequests"]
            )
            self.assertTrue(
                target_status["respondPermissionProfile"]["canWritePlatformResponse"]
            )
            self.assertTrue(target_status["dispatcherRunning"])
            self.assertEqual(target_status["dispatcherStatus"]["state"], "running")
            self.assertEqual(target_status["dispatcherLiveness"]["pid"], 8765)

    def test_provider_runtime_status_normalizes_snapshot_and_platform_busy(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = _app(root)
            _seed_workspace(app, root)
            app.create_agent(
                workspace_id="workspace-endpoint",
                agent_id="agent-b",
                name="Agent B",
                description="Target agent.",
            )
            app.register_codex_session_handle(
                workspace_id="workspace-endpoint",
                agent_id="agent-a",
                handle_id="codex-source-handle",
                codex_session_id="codex-source-session",
                cwd=str(root),
                created_by="user",
                reason="source endpoint fixture",
            )
            app.register_codex_session_handle(
                workspace_id="workspace-endpoint",
                agent_id="agent-b",
                handle_id="codex-target-handle",
                codex_session_id="codex-target-session",
                cwd=str(root),
                created_by="user",
                reason="target endpoint fixture",
                metadata={
                    "providerRuntimeStatus": {
                        "threadStatus": "idle",
                        "threadId": "codex-thread-target",
                    }
                },
            )
            app.login_agent_endpoint(
                workspace_id="workspace-endpoint",
                agent_id="agent-a",
                alias="codex-source",
                provider="codex",
                provider_handle_id="codex-source-handle",
                direction="send_only",
                default_reply_policy="source_handle_required",
                created_by="user",
                reason="source endpoint login",
            )
            app.login_agent_endpoint(
                workspace_id="workspace-endpoint",
                agent_id="agent-b",
                alias="codex-target",
                provider="codex",
                provider_handle_id="codex-target-handle",
                direction="receive_only",
                created_by="user",
                reason="target endpoint login",
            )

            runtime_status = app.get_agent_provider_runtime_status(
                workspace_id="workspace-endpoint",
                alias="codex-target",
            )["providerRuntimeStatus"]
            self.assertEqual(runtime_status["runtimeState"], "idle")
            self.assertEqual(runtime_status["providerRuntimeState"], "idle")
            self.assertTrue(runtime_status["providerRuntimeStatusRead"])
            self.assertEqual(
                runtime_status["providerStatusAdapter"]["adapterKind"],
                "codex_app_server_thread_status",
            )

            sent = app.send_agent_dispatch(
                workspace_id="workspace-endpoint",
                dispatch_id="dispatch-runtime-status",
                exchange_request_id="req-runtime-status",
                from_endpoint_alias="codex-source",
                to_endpoint_alias="codex-target",
                request_kind="review",
                request_summary="Review runtime status.",
            )
            app.acquire_agent_dispatch_lease(
                workspace_id="workspace-endpoint",
                dispatch_id=sent["agentDispatch"]["dispatchId"],
                acquired_by="test-worker",
            )

            endpoint_status = app.get_agent_endpoint_status(
                workspace_id="workspace-endpoint",
                alias="codex-target",
            )
            self.assertEqual(endpoint_status["providerRuntimeState"], "busy")
            self.assertEqual(
                endpoint_status["providerRuntimeStateSource"],
                "platform_dispatch_lease",
            )
            self.assertTrue(
                endpoint_status["providerRuntimeStatus"]["platformDispatchBusy"],
            )
            self.assertEqual(
                endpoint_status["providerRuntimeStatus"]["providerRuntimeState"],
                "idle",
            )

    def test_provider_runtime_status_auto_reads_configured_probe_and_can_disable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = _app(root)
            _seed_workspace(app, root)
            app.create_agent(
                workspace_id="workspace-endpoint",
                agent_id="agent-b",
                name="Agent B",
                description="Target agent.",
            )
            probe_payload = json.dumps({"runStatus": "running", "runId": "run-1"})
            app.register_hermes_session_handle(
                workspace_id="workspace-endpoint",
                agent_id="agent-b",
                handle_id="hermes-live-handle",
                hermes_session_id="hermes-session-live",
                cwd=str(root),
                created_by="user",
                reason="live probe fixture",
                metadata={
                    "providerRuntimeStatusProbe": {
                        "mode": "local_command_json",
                        "argv": [
                            sys.executable,
                            "-c",
                            f"print({probe_payload!r})",
                        ],
                        "timeoutSeconds": 5,
                    },
                    "respondPermissionProfile": {
                        "platformCliRespondAllowed": True,
                    },
                },
            )
            app.login_agent_endpoint(
                workspace_id="workspace-endpoint",
                agent_id="agent-b",
                alias="hermes-live",
                provider="hermes",
                provider_handle_id="hermes-live-handle",
                direction="receive_only",
                created_by="user",
                reason="target endpoint login",
            )

            automatic = app.get_agent_provider_runtime_status(
                workspace_id="workspace-endpoint",
                alias="hermes-live",
            )["providerRuntimeStatus"]
            self.assertEqual(automatic["runtimeState"], "busy")
            self.assertEqual(
                automatic["providerStatusAdapter"][
                    "directProviderRuntimeReadStatus"
                ],
                "read",
            )
            self.assertTrue(automatic["providerRuntimeStatusRead"])
            self.assertEqual(automatic["runtimeStatusPolicy"], "auto")

            with patch(
                "agent_os.application.services.local_platform_operations.subprocess.run"
            ) as run_probe:
                disabled = app.get_agent_provider_runtime_status(
                    workspace_id="workspace-endpoint",
                    alias="hermes-live",
                    read_live_runtime_status="disabled",
                )["providerRuntimeStatus"]
            run_probe.assert_not_called()
            self.assertEqual(disabled["runtimeState"], "unknown")
            self.assertEqual(disabled["runtimeStatusPolicy"], "disabled")
            self.assertEqual(
                disabled["providerRuntimeStatusProbe"]["status"],
                "disabled",
            )
            self.assertFalse(disabled["providerRuntimeStatusRead"])

            live = app.get_agent_provider_runtime_status(
                workspace_id="workspace-endpoint",
                alias="hermes-live",
                read_live_runtime_status=True,
            )["providerRuntimeStatus"]
            self.assertEqual(live["runtimeState"], "busy")
            self.assertEqual(live["providerRuntimeState"], "busy")
            self.assertTrue(live["providerRuntimeStatusRead"])
            self.assertEqual(
                live["providerRuntimeStatusReadMode"],
                "local_command_probe",
            )
            self.assertEqual(live["providerRuntimeStatusProbe"]["status"], "read")
            self.assertEqual(live["runtimeStatusPolicy"], "enabled")
            self.assertTrue(
                live["providerStatusAdapter"]["directProviderRuntimeReadConfigured"]
            )

            endpoint_status = app.get_agent_endpoint_status(
                workspace_id="workspace-endpoint",
                alias="hermes-live",
                read_live_runtime_status=True,
            )
            self.assertEqual(endpoint_status["providerRuntimeState"], "busy")
            self.assertTrue(
                endpoint_status["respondPermissionProfile"][
                    "platformCliRespondAllowedDeclared"
                ]
            )
            self.assertTrue(
                endpoint_status["respondPermissionProfile"][
                    "canReadIncomingRequests"
                ]
            )

    def test_provider_runtime_status_waiting_normalization_is_conservative(
        self,
    ) -> None:
        expected = {
            "waiting_for_input": "idle",
            "waiting_for_user_input": "idle",
            "waiting_for_response": "blocked",
            "waiting_external": "blocked",
            "waiting_for_agent": "blocked",
            "waiting": "unknown",
        }
        for raw_state, canonical_state in expected.items():
            with self.subTest(raw_state=raw_state):
                status = build_agent_provider_runtime_status(
                    provider="codex",
                    provider_handle_id="codex-waiting-handle",
                    provider_handle={
                        "handleId": "codex-waiting-handle",
                        "agentId": "agent-a",
                        "state": "active",
                    },
                    live_status_snapshot={"threadStatus": raw_state},
                    live_status_probe={
                        "configured": True,
                        "status": "read",
                        "runtimeStatusPolicy": "auto",
                    },
                )
                self.assertEqual(status["runtimeState"], canonical_state)

    def test_runtime_status_auto_without_probe_never_starts_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = _app(root)
            _seed_workspace(app, root)
            app.register_codex_session_handle(
                workspace_id="workspace-endpoint",
                agent_id="agent-a",
                handle_id="codex-no-probe-handle",
                codex_session_id="codex-no-probe-session",
                cwd=str(root),
                created_by="user",
                reason="no probe fixture",
            )
            with patch(
                "agent_os.application.services.local_platform_operations.subprocess.run"
            ) as run_probe:
                status = app.get_agent_provider_runtime_status(
                    workspace_id="workspace-endpoint",
                    provider="codex",
                    provider_handle_id="codex-no-probe-handle",
                )["providerRuntimeStatus"]
            run_probe.assert_not_called()
            self.assertEqual(status["runtimeState"], "unknown")
            self.assertEqual(
                status["providerRuntimeStatusProbe"]["status"],
                "not_configured",
            )

    def test_runtime_status_auto_probe_failure_is_observable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = _app(root)
            _seed_workspace(app, root)
            app.register_codex_session_handle(
                workspace_id="workspace-endpoint",
                agent_id="agent-a",
                handle_id="codex-failed-probe-handle",
                codex_session_id="codex-failed-probe-session",
                cwd=str(root),
                created_by="user",
                reason="failed probe fixture",
                metadata={
                    "providerRuntimeStatusProbe": {
                        "mode": "local_command_json",
                        "argv": [sys.executable, "-c", "raise SystemExit(7)"],
                    }
                },
            )

            status = app.get_agent_provider_runtime_status(
                workspace_id="workspace-endpoint",
                provider="codex",
                provider_handle_id="codex-failed-probe-handle",
            )["providerRuntimeStatus"]

            self.assertEqual(status["runtimeState"], "unknown")
            self.assertEqual(
                status["stateSource"],
                "provider_runtime_status_probe_failed",
            )
            self.assertEqual(
                status["providerRuntimeStatusProbe"]["status"],
                "exit_nonzero",
            )
            self.assertIn(
                "failureReason",
                status["providerRuntimeStatusProbe"],
            )


def _app(root: Path) -> LocalPlatformApplication:
    return LocalPlatformApplication(
        LocalPlatformSettings(
            database=str(root / "platform.sqlite3"),
            workspace_root=str(root / "workspace"),
            plugins_directory=str(root / "plugins"),
        )
    )


def _seed_workspace(app: LocalPlatformApplication, root: Path) -> None:
    app.create_workspace(
        workspace_id="workspace-endpoint",
        display_name="Endpoint Workspace",
        root_path=str(root),
        agent_id="agent-a",
    )


if __name__ == "__main__":
    unittest.main()
