from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.agent_dispatch import (
    AgentDispatchRecord,
)
from agent_os.application.services.local_platform_operations import (
    LocalPlatformOperationService,
)
from agent_os.application.services.local_platform_application import (
    LocalPlatformApplication,
)
from agent_os.infrastructure.config import LocalPlatformSettings
from agent_os.infrastructure.persistence.context_update_events import (
    SqliteContextUpdateEventRecorder,
)
from agent_os.infrastructure.persistence.conversations import SqliteConversationStore
from agent_os.infrastructure.persistence.event_log import SqlitePlatformEventLog
from agent_os.infrastructure.persistence.file_operation_records import (
    SqliteFileOperationRecordStore,
)
from agent_os.infrastructure.persistence.invocation_records import (
    SqliteAgentInvocationRecordStore,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteAgentRegistrationStateStore,
    SqliteContextStateStore,
    SqliteIssueStateStore,
    SqliteTaskStateStore,
    SqliteWorkspaceStateStore,
)
from agent_os.infrastructure.persistence.sqlite_persistence import (
    SqlitePlatformPersistence,
)


class AgentDispatchContractTests(unittest.TestCase):
    def test_dispatch_record_requires_source_handle_when_reply_policy_requires_it(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "sourceHandleId is required"):
            AgentDispatchRecord.from_mapping(
                {
                    "workspaceId": "workspace-dispatch",
                    "dispatchId": "dispatch-1",
                    "exchangeRequestId": "req-1",
                    "sourceAgentId": "agent-a",
                    "targetAgentId": "agent-b",
                    "replyPolicy": "source_handle_required",
                }
            )

    def test_dispatch_record_rejects_credential_metadata(self) -> None:
        with self.assertRaisesRegex(ValueError, "credential"):
            AgentDispatchRecord.from_mapping(
                {
                    "workspaceId": "workspace-dispatch",
                    "dispatchId": "dispatch-1",
                    "exchangeRequestId": "req-1",
                    "sourceAgentId": "agent-a",
                    "targetAgentId": "agent-b",
                    "metadata": {"token": "secret"},
                }
            )

    def test_dispatch_record_tracks_provider_activation_boundary(self) -> None:
        record = AgentDispatchRecord.from_mapping(
            {
                "workspaceId": "workspace-dispatch",
                "dispatchId": "dispatch-1",
                "exchangeRequestId": "req-1",
                "sourceAgentId": "agent-a",
                "targetAgentId": "agent-b",
                "providerActivationExecuted": True,
            }
        )

        metadata = record.to_metadata()

        self.assertTrue(metadata["providerActivationExecuted"])
        self.assertFalse(metadata["activationAutomationBoundary"]["platformQueueOnly"])
        self.assertTrue(
            metadata["activationAutomationBoundary"]["providerActivationExecuted"]
        )


class AgentDispatchOperationTests(unittest.TestCase):
    def test_dry_run_dispatch_does_not_write_request_or_dispatch_events(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_workspace(service)

        result = service.create_agent_dispatch(
            "workspace-dispatch",
            dispatch_id="dispatch-dry",
            exchange_request_id="req-dry",
            source_agent_id="agent-a",
            target_agent_id="agent-b",
            request_kind="review",
            request_summary="Review this dispatch plan.",
            source_handle_id="source-handle",
            reply_policy="source_handle_required",
            dry_run=True,
        )

        self.assertTrue(result["dryRun"])
        self.assertFalse(result["queued"])
        self.assertEqual(result["agentDispatch"]["status"], "dry_run")
        self.assertEqual(_event_count(connection, "agent_dispatch.changed"), 0)
        self.assertEqual(_event_count(connection, "agent_exchange_request.changed"), 0)

    def test_queued_dispatch_creates_request_and_status_projection(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_workspace(service)

        result = service.create_agent_dispatch(
            "workspace-dispatch",
            dispatch_id="dispatch-1",
            exchange_request_id="req-1",
            source_agent_id="agent-a",
            target_agent_id="agent-b",
            target_handle_id="target-handle",
            target_provider="codex-cli",
            request_kind="review",
            request_summary="Review this queued dispatch.",
            detail_refs=("docs/status.md",),
        )

        self.assertEqual(result["apiLayer"], "delivery-oriented")
        self.assertEqual(result["dispatchApiLayer"]["apiLayer"], "delivery-oriented")
        self.assertTrue(result["queued"])
        self.assertFalse(result["dispatcherRunning"])
        self.assertEqual(result["agentDispatch"]["status"], "queued")
        self.assertEqual(result["agentExchangeRequest"]["exchangeRequestId"], "req-1")
        self.assertEqual(_event_count(connection, "agent_dispatch.changed"), 1)
        self.assertEqual(_event_count(connection, "agent_exchange_request.changed"), 1)

        status = service.get_agent_dispatch_status(
            "workspace-dispatch",
            dispatch_id="dispatch-1",
        )
        self.assertEqual(status["agentDispatch"]["dispatchId"], "dispatch-1")
        self.assertEqual(status["agentExchangeRequest"]["status"], "active")
        self.assertFalse(status["wakeStatus"]["ticketDeliveryOccurred"])
        self.assertFalse(status["providerRuntimeStateSupported"])
        self.assertEqual(status["providerRuntimeStatus"]["runtimeState"], "unavailable")
        self.assertFalse(status["providerRuntimeStatusRead"])

        listed = service.list_agent_dispatches(
            "workspace-dispatch",
            status="queued",
        )
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["agentDispatches"][0]["exchangeRequestId"], "req-1")

    def test_dispatch_status_reads_persisted_daemon_liveness(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_workspace(service)
        service.create_agent_dispatch(
            "workspace-dispatch",
            dispatch_id="dispatch-liveness",
            exchange_request_id="req-liveness",
            source_agent_id="agent-a",
            target_agent_id="agent-b",
            target_handle_id="target-handle",
            target_provider="codex-cli",
            request_kind="review",
            request_summary="Review daemon liveness.",
        )

        initial = service.get_agent_dispatch_status(
            "workspace-dispatch",
            dispatch_id="dispatch-liveness",
        )
        self.assertFalse(initial["dispatcherRunning"])
        self.assertEqual(initial["dispatcherStatus"]["state"], "not_running")

        started_at = datetime(2026, 7, 1, 1, 2, 3)
        service.record_agent_dispatch_daemon_liveness(
            "workspace-dispatch",
            dispatcher_id="agent-dispatch-daemon",
            state="running",
            profile_path="X:/fixture/beacon-project/profile.json",
            pid=4321,
            process_hint={"argv": ["python", "-m", "agent_os.agent_dispatch_daemon"]},
            started_at=started_at,
            last_heartbeat_at=started_at,
            last_poll_at=started_at,
        )

        running = service.get_agent_dispatch_status(
            "workspace-dispatch",
            dispatch_id="dispatch-liveness",
        )
        self.assertTrue(running["dispatcherRunning"])
        self.assertEqual(running["dispatcherStatus"]["state"], "running")
        self.assertEqual(running["dispatcherLiveness"]["pid"], 4321)
        self.assertEqual(
            running["dispatcherLiveness"]["profilePath"],
            "X:/fixture/beacon-project/profile.json",
        )
        self.assertEqual(
            running["dispatcherLiveness"]["lastPollAt"],
            started_at.isoformat(),
        )

        exited_at = datetime(2026, 7, 1, 1, 3, 3)
        service.record_agent_dispatch_daemon_liveness(
            "workspace-dispatch",
            dispatcher_id="agent-dispatch-daemon",
            state="exited",
            last_exit_at=exited_at,
            last_exit_reason="once_completed",
        )
        exited = service.get_agent_dispatch_daemon_status("workspace-dispatch")
        self.assertFalse(exited["dispatcherRunning"])
        self.assertEqual(exited["state"], "exited")
        self.assertEqual(
            exited["daemonLiveness"]["lastExitReason"],
            "once_completed",
        )
        self.assertEqual(exited["daemonLiveness"]["lastPollAt"], started_at.isoformat())

        failed_at = datetime(2026, 7, 1, 1, 4, 3)
        service.record_agent_dispatch_daemon_liveness(
            "workspace-dispatch",
            dispatcher_id="agent-dispatch-daemon",
            state="failed",
            last_error_at=failed_at,
            last_exit_at=failed_at,
            last_exit_reason="startup_failed",
            error_summary="FileNotFoundError: missing python",
        )
        failed = service.get_agent_dispatch_daemon_status("workspace-dispatch")
        self.assertEqual(failed["state"], "failed")
        self.assertFalse(failed["dispatcherRunning"])
        self.assertEqual(
            failed["daemonLiveness"]["errorSummary"],
            "FileNotFoundError: missing python",
        )
        self.assertEqual(
            _event_count(
                connection,
                "agent_dispatch_daemon_liveness.changed",
            ),
            3,
        )

    def test_lease_blocks_same_target_handle_until_released(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_workspace(service)
        service.create_agent_dispatch(
            "workspace-dispatch",
            dispatch_id="dispatch-1",
            exchange_request_id="req-1",
            source_agent_id="agent-a",
            target_agent_id="agent-b",
            target_handle_id="target-handle",
            request_kind="review",
            request_summary="First dispatch.",
        )
        service.create_agent_dispatch(
            "workspace-dispatch",
            dispatch_id="dispatch-2",
            exchange_request_id="req-2",
            source_agent_id="agent-a",
            target_agent_id="agent-b",
            target_handle_id="target-handle",
            request_kind="review",
            request_summary="Second dispatch.",
        )

        leased = service.acquire_agent_dispatch_lease(
            "workspace-dispatch",
            dispatch_id="dispatch-1",
            lease_id="lease-1",
            acquired_by="dispatcher-test",
            lease_ttl_seconds=60,
        )
        self.assertTrue(leased["leased"])
        self.assertEqual(leased["agentDispatch"]["status"], "leased")

        with self.assertRaisesRegex(ValueError, "already active"):
            service.acquire_agent_dispatch_lease(
                "workspace-dispatch",
                dispatch_id="dispatch-2",
                lease_id="lease-2",
                acquired_by="dispatcher-test",
            )

        released = service.release_agent_dispatch_lease(
            "workspace-dispatch",
            lease_id="lease-1",
            released_by="dispatcher-test",
        )
        self.assertTrue(released["released"])
        self.assertEqual(released["agentDispatchLease"]["state"], "released")
        self.assertIsNone(released["agentDispatch"]["leaseId"])

        second = service.acquire_agent_dispatch_lease(
            "workspace-dispatch",
            dispatch_id="dispatch-2",
            lease_id="lease-2",
            acquired_by="dispatcher-test",
        )
        self.assertEqual(second["agentDispatchLease"]["leaseId"], "lease-2")

    def test_worker_recovers_expired_orphan_lease_and_retries_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = "hermes-orphan-retry-session"
            capture_path = root / "hermes-orphan-retry.json"
            service.register_hermes_session_handle(
                "workspace-dispatch",
                agent_id="agent-b",
                handle_id="hermes-orphan-handle",
                hermes_session_id=session_id,
                cwd=str(root),
                created_by="tester",
                reason="orphan lease recovery fixture",
            )
            started_at = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
            service.create_agent_dispatch(
                "workspace-dispatch",
                dispatch_id="dispatch-orphan-expired",
                exchange_request_id="req-orphan-expired",
                source_agent_id="agent-a",
                target_agent_id="agent-b",
                target_handle_id="hermes-orphan-handle",
                target_provider="hermes-cli",
                request_kind="review",
                request_summary="Recover this expired orphan lease.",
                occurred_at=started_at,
            )
            service.acquire_agent_dispatch_lease(
                "workspace-dispatch",
                dispatch_id="dispatch-orphan-expired",
                lease_id="lease-orphan-expired",
                acquired_by="worker-that-disappeared",
                lease_ttl_seconds=10,
                metadata={"workerRunId": "worker-run-orphaned"},
                occurred_at=started_at,
            )

            result = service.run_agent_dispatch_worker_once(
                "workspace-dispatch",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                hermes_executable=str(
                    _fake_hermes_command(
                        root,
                        session_id,
                        capture_path,
                        "Recovered orphan dispatch completed.",
                    )
                ),
                dry_run=False,
                occurred_at=started_at + timedelta(seconds=11),
            )

            reconciliation = result["leaseReconciliation"]
            self.assertEqual(reconciliation["recoveredCount"], 1)
            entry = reconciliation["entries"][0]
            self.assertEqual(entry["leaseId"], "lease-orphan-expired")
            self.assertEqual(
                entry["recoveryReason"],
                "expired_orphan_lease_active_request",
            )
            self.assertEqual(entry["resultDispatchStatus"], "retry_scheduled")
            self.assertEqual(entry["attemptCountBefore"], 0)
            self.assertEqual(entry["attemptCountAfter"], 0)
            self.assertFalse(entry["automaticProviderActivationTriggered"])
            self.assertEqual(result["processedCount"], 1)
            dispatch = result["agentDispatches"][0]["agentDispatch"]
            self.assertEqual(dispatch["status"], "completed")
            self.assertEqual(dispatch["attemptCount"], 1)
            self.assertTrue(capture_path.exists())
            status = service.get_agent_dispatch_status(
                "workspace-dispatch",
                dispatch_id="dispatch-orphan-expired",
            )
            self.assertTrue(status["leaseRecoveryStatus"]["recovered"])
            self.assertEqual(
                status["readableStatusReason"]["reasonCode"],
                "completed",
            )
            self.assertEqual(
                status["leaseRecoveryStatus"]["originalWorkerRunId"],
                "worker-run-orphaned",
            )
            self.assertIn(
                "lease_recovered",
                [event["stage"] for event in status["statusTimeline"]["events"]],
            )

    def test_worker_recovers_responded_orphan_without_reactivation(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_workspace(service)
        started_at = datetime(2026, 7, 10, 13, 0, tzinfo=timezone.utc)
        service.create_agent_dispatch(
            "workspace-dispatch",
            dispatch_id="dispatch-orphan-responded",
            exchange_request_id="req-orphan-responded",
            source_agent_id="agent-a",
            target_agent_id="agent-b",
            target_handle_id="target-handle",
            target_provider="hermes-cli",
            request_kind="review",
            request_summary="Response arrives before worker process disappears.",
            occurred_at=started_at,
        )
        service.acquire_agent_dispatch_lease(
            "workspace-dispatch",
            dispatch_id="dispatch-orphan-responded",
            lease_id="lease-orphan-responded",
            acquired_by="worker-that-disappeared",
            lease_ttl_seconds=300,
            metadata={"workerRunId": "worker-run-response-lost"},
            occurred_at=started_at,
        )
        service.respond_agent_exchange_request(
            "workspace-dispatch",
            exchange_request_id="req-orphan-responded",
            responding_agent_id="agent-b",
            response_summary="Durable response survived caller timeout.",
            responded_at=started_at + timedelta(seconds=28),
        )

        result = service.run_agent_dispatch_worker_once(
            "workspace-dispatch",
            database_path="unused.sqlite3",
            workspace_root="unused-workspace",
            plugins_directory="unused-plugins",
            hermes_executable="missing-hermes",
            dry_run=False,
            occurred_at=started_at + timedelta(seconds=30),
        )

        reconciliation = result["leaseReconciliation"]
        self.assertEqual(reconciliation["recoveredCount"], 1)
        self.assertEqual(result["candidateCount"], 0)
        self.assertEqual(result["processedCount"], 0)
        self.assertEqual(
            reconciliation["entries"][0]["recoveryReason"],
            "request_responded_orphan_lease",
        )
        status = service.get_agent_dispatch_status(
            "workspace-dispatch",
            dispatch_id="dispatch-orphan-responded",
        )
        self.assertEqual(status["agentDispatch"]["status"], "completed")
        self.assertEqual(status["agentDispatch"]["attemptCount"], 0)
        self.assertEqual(
            status["readableStatusReason"]["reasonCode"],
            "orphan_lease_recovered",
        )
        self.assertEqual(status["latestLease"]["state"], "released")
        self.assertEqual(
            status["agentExchangeRequest"]["responseSummary"],
            "Durable response survived caller timeout.",
        )
        self.assertEqual(
            _event_count(connection, "hermes_registered_session_activation.recorded"),
            0,
        )
        before_repeat = (
            _event_count(connection, "agent_dispatch.changed"),
            _event_count(connection, "agent_dispatch_lease.changed"),
        )
        repeated = service.reconcile_agent_dispatch_leases(
            "workspace-dispatch",
            occurred_at=started_at + timedelta(seconds=31),
        )
        after_repeat = (
            _event_count(connection, "agent_dispatch.changed"),
            _event_count(connection, "agent_dispatch_lease.changed"),
        )
        self.assertEqual(repeated["recoveredCount"], 0)
        self.assertEqual(repeated["scannedActiveLeaseCount"], 0)
        self.assertEqual(before_repeat, after_repeat)

    def test_worker_preserves_unexpired_lease_and_reports_platform_busy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            service.register_codex_session_handle(
                "workspace-dispatch",
                agent_id="agent-b",
                handle_id="codex-lease-handle",
                codex_session_id="codex-valid-lease-session",
                cwd=str(root),
                created_by="tester",
                reason="valid lease fixture",
            )
            started_at = datetime.now(timezone.utc)
            for suffix in ("owner", "waiting"):
                service.create_agent_dispatch(
                    "workspace-dispatch",
                    dispatch_id=f"dispatch-valid-lease-{suffix}",
                    exchange_request_id=f"req-valid-lease-{suffix}",
                    source_agent_id="agent-a",
                    target_agent_id="agent-b",
                    target_handle_id="codex-lease-handle",
                    target_provider="codex-cli",
                    request_kind="review",
                    request_summary=f"Valid lease {suffix} dispatch.",
                    occurred_at=started_at,
                )
            service.acquire_agent_dispatch_lease(
                "workspace-dispatch",
                dispatch_id="dispatch-valid-lease-owner",
                lease_id="lease-valid-owner",
                acquired_by="still-possible-worker",
                lease_ttl_seconds=300,
                metadata={"workerRunId": "worker-run-valid"},
                occurred_at=started_at,
            )

            result = service.run_agent_dispatch_worker_once(
                "workspace-dispatch",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                codex_executable=str(root / "must-not-run.cmd"),
                dry_run=False,
                occurred_at=started_at + timedelta(seconds=30),
            )

            reconciliation = result["leaseReconciliation"]
            self.assertEqual(reconciliation["recoveredCount"], 0)
            self.assertEqual(reconciliation["preservedCount"], 1)
            self.assertEqual(
                reconciliation["entries"][0]["recoveryReason"],
                "valid_active_lease",
            )
            self.assertTrue(reconciliation["entries"][0]["ownerMayBeLive"])
            self.assertEqual(result["processedCount"], 0)
            self.assertEqual(result["skippedCount"], 1)
            item = result["agentDispatches"][0]
            self.assertEqual(item["skipReason"], "valid_platform_lease")
            self.assertEqual(
                item["providerRuntimeStatus"]["stateSource"],
                "platform_dispatch_lease",
            )
            status = service.get_agent_dispatch_status(
                "workspace-dispatch",
                dispatch_id="dispatch-valid-lease-waiting",
            )
            self.assertEqual(status["agentDispatch"]["status"], "queued")
            self.assertEqual(status["agentDispatch"]["attemptCount"], 0)
            self.assertTrue(status["providerRuntimeStatus"]["platformDispatchBusy"])

    def test_reconcile_maps_nonresponse_terminal_request_to_cancelled(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_workspace(service)
        started_at = datetime(2026, 7, 10, 15, 0, tzinfo=timezone.utc)
        service.create_agent_dispatch(
            "workspace-dispatch",
            dispatch_id="dispatch-orphan-revoked",
            exchange_request_id="req-orphan-revoked",
            source_agent_id="agent-a",
            target_agent_id="agent-b",
            target_handle_id="target-handle",
            request_kind="review",
            request_summary="Revoked request should cancel dispatch.",
            occurred_at=started_at,
        )
        service.acquire_agent_dispatch_lease(
            "workspace-dispatch",
            dispatch_id="dispatch-orphan-revoked",
            lease_id="lease-orphan-revoked",
            acquired_by="worker-that-disappeared",
            lease_ttl_seconds=300,
            occurred_at=started_at,
        )
        service.close_agent_exchange_request(
            "workspace-dispatch",
            exchange_request_id="req-orphan-revoked",
            terminal_reason="revoked",
            closed_at=started_at + timedelta(seconds=5),
        )

        recovered = service.reconcile_agent_dispatch_leases(
            "workspace-dispatch",
            occurred_at=started_at + timedelta(seconds=6),
        )

        self.assertEqual(recovered["recoveredCount"], 1)
        self.assertEqual(
            recovered["entries"][0]["recoveryReason"],
            "request_revoked_orphan_lease",
        )
        status = service.get_agent_dispatch_status(
            "workspace-dispatch",
            dispatch_id="dispatch-orphan-revoked",
        )
        self.assertEqual(status["agentDispatch"]["status"], "cancelled")
        self.assertEqual(status["agentDispatch"]["attemptCount"], 0)

    def test_worker_executes_hermes_dispatch_and_marks_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            response_text = "worker captured Hermes dispatch response."
            capture_path = root / "hermes-capture.json"
            fake_hermes = _fake_hermes_command(
                root,
                session_id,
                capture_path,
                response_text,
            )
            service.register_hermes_session_handle(
                "workspace-dispatch",
                agent_id="agent-b",
                handle_id="hermes-handle-1",
                hermes_session_id=session_id,
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )
            service.create_agent_dispatch(
                "workspace-dispatch",
                dispatch_id="dispatch-hermes-1",
                exchange_request_id="req-hermes-dispatch-1",
                source_agent_id="agent-a",
                target_agent_id="agent-b",
                target_handle_id="hermes-handle-1",
                target_provider="hermes-cli",
                request_kind="review",
                request_summary="Review via worker-triggered Hermes dispatch.",
            )

            result = service.run_agent_dispatch_worker_once(
                "workspace-dispatch",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                hermes_executable=str(fake_hermes),
                dry_run=False,
            )

            self.assertEqual(result["processedCount"], 1)
            item = result["agentDispatches"][0]
            self.assertEqual(item["finalStatus"], "completed")
            dispatch = item["agentDispatch"]
            self.assertEqual(dispatch["status"], "completed")
            self.assertEqual(dispatch["attemptCount"], 1)
            self.assertTrue(dispatch["providerActivationExecuted"])
            self.assertFalse(dispatch["providerRuntimeStatusRead"])
            self.assertFalse(
                dispatch["activationAutomationBoundary"]["platformQueueOnly"]
            )
            self.assertEqual(
                dispatch["metadata"]["providerActivation"]["provider"],
                "hermes",
            )
            self.assertTrue(item["activation"]["targetResponseCompleted"])
            self.assertEqual(
                item["activation"]["expectedSessionVerification"],
                "verified",
            )
            self.assertTrue(item["activation"]["expectedSessionVerified"])
            self.assertFalse(item["activation"]["responseRequiresUserReview"])
            self.assertEqual(item["agentDispatchLease"]["state"], "released")
            self.assertTrue(capture_path.exists())
            request = service.get_agent_exchange_request_status(
                "workspace-dispatch",
                exchange_request_id="req-hermes-dispatch-1",
            )["agentExchangeRequest"]
            self.assertEqual(request["terminalReason"], "responded")
            self.assertEqual(request["responseSummary"], response_text)
            self.assertEqual(
                request["responseSourceStatus"]["responseSource"],
                "stdout_auto_capture",
            )
            self.assertEqual(
                request["responseSourceStatus"]["rawResponseSource"],
                "hermes_chat_query_auto_capture",
            )
            self.assertTrue(
                request["responseSourceStatus"]["stdoutFallbackCaptured"]
            )
            self.assertFalse(request["responseSourceStatus"]["standardResponded"])

            status = service.get_agent_dispatch_status(
                "workspace-dispatch",
                dispatch_id="dispatch-hermes-1",
            )
            self.assertEqual(
                status["responseSourceStatus"]["responseSource"],
                "stdout_auto_capture",
            )
            timeline = status["statusTimeline"]["events"]
            stages = [event["stage"] for event in timeline]
            for stage in (
                "created",
                "queued",
                "leased",
                "provider_started",
                "stdout_captured",
                "released",
                "completed",
            ):
                self.assertIn(stage, stages)
            stdout_events = [
                event for event in timeline if event["stage"] == "stdout_captured"
            ]
            self.assertTrue(stdout_events)
            self.assertTrue(
                any(
                    event.get("responseSource") == "stdout_auto_capture"
                    for event in stdout_events
                )
            )
            self.assertTrue(
                all(event["privateReasoningRead"] is False for event in stdout_events)
            )
            self.assertIn(
                "not private reasoning",
                status["responseSourceStatus"]["stdoutFallbackMeaning"],
            )

    def test_worker_schedules_retry_for_retryable_activation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            service.register_hermes_session_handle(
                "workspace-dispatch",
                agent_id="agent-b",
                handle_id="hermes-handle-1",
                hermes_session_id=session_id,
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )
            service.create_agent_dispatch(
                "workspace-dispatch",
                dispatch_id="dispatch-hermes-missing-exe",
                exchange_request_id="req-hermes-missing-exe",
                source_agent_id="agent-a",
                target_agent_id="agent-b",
                target_handle_id="hermes-handle-1",
                target_provider="hermes-cli",
                request_kind="review",
                request_summary="Review via missing Hermes executable.",
            )

            result = service.run_agent_dispatch_worker_once(
                "workspace-dispatch",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                hermes_executable=str(root / "missing-hermes.cmd"),
                retry_delay_seconds=60,
                dry_run=False,
            )

            dispatch = result["agentDispatches"][0]["agentDispatch"]
            self.assertEqual(dispatch["status"], "retry_scheduled")
            self.assertEqual(dispatch["attemptCount"], 1)
            self.assertIsNotNone(dispatch["nextAttemptAfter"])
            self.assertTrue(dispatch["providerActivationExecuted"])
            self.assertEqual(
                dispatch["providerRuntimeState"],
                "activation_retry_scheduled",
            )
            self.assertEqual(
                dispatch["metadata"]["failureCategory"],
                "executable_not_found",
            )
            self.assertTrue(dispatch["metadata"]["retryable"])
            retry_status = service.get_agent_dispatch_status(
                "workspace-dispatch",
                dispatch_id="dispatch-hermes-missing-exe",
            )
            self.assertTrue(
                retry_status["retryActorStatus"]["workerRetryScheduled"]
            )
            self.assertFalse(
                retry_status["retryActorStatus"]["platformAutomaticRetry"]
            )
            self.assertEqual(
                retry_status["readableStatusReason"]["reasonCode"],
                "retry_scheduled",
            )
            self.assertIn(
                "retry",
                retry_status["readableStatusReason"]["message"].lower(),
            )

            retry_after = datetime.fromisoformat(str(dispatch["nextAttemptAfter"]))
            capture_path = root / "hermes-retry-capture.json"
            response_text = "worker completed retry dispatch."
            fake_hermes = _fake_hermes_command(
                root,
                session_id,
                capture_path,
                response_text,
            )
            retry_result = service.run_agent_dispatch_worker_once(
                "workspace-dispatch",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                handoff_directory=str(root / "handoff"),
                hermes_executable=str(fake_hermes),
                dry_run=False,
                occurred_at=retry_after + timedelta(seconds=1),
            )

            retried_dispatch = retry_result["agentDispatches"][0]["agentDispatch"]
            self.assertEqual(retried_dispatch["status"], "completed")
            self.assertEqual(retried_dispatch["attemptCount"], 2)
            self.assertIsNone(retried_dispatch["nextAttemptAfter"])
            self.assertEqual(
                retried_dispatch["metadata"]["providerActivation"]["status"],
                "delivered",
            )
            manual_retry = service.create_agent_dispatch(
                "workspace-dispatch",
                dispatch_id="dispatch-hermes-manual-retry",
                exchange_request_id="req-hermes-manual-retry",
                source_agent_id="agent-a",
                target_agent_id="agent-b",
                target_handle_id="hermes-handle-1",
                target_provider="hermes-cli",
                request_kind="review",
                request_summary="Manual retry as a new dispatch.",
                metadata={"manualRetryOfDispatchId": "dispatch-hermes-missing-exe"},
            )["agentDispatch"]
            manual_status = service.get_agent_exchange_status_summary(
                "workspace-dispatch",
                dispatch_id=manual_retry["dispatchId"],
            )
            self.assertTrue(
                manual_status["retryActorStatus"]["senderCreatedNewDispatch"]
            )
            self.assertFalse(
                manual_status["retryActorStatus"]["platformAutomaticRetry"]
            )
            self.assertEqual(
                manual_status["retryActorStatus"]["manualRetryOf"],
                "dispatch-hermes-missing-exe",
            )

    def test_worker_skips_busy_target_runtime_without_activation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            service.register_codex_session_handle(
                "workspace-dispatch",
                agent_id="agent-b",
                handle_id="codex-busy-handle",
                codex_session_id="codex-busy-session",
                cwd=str(root),
                created_by="user",
                reason="busy target fixture",
                metadata={
                    "providerRuntimeStatus": {
                        "threadStatus": "running",
                        "threadId": "codex-thread-busy",
                    }
                },
            )
            service.create_agent_dispatch(
                "workspace-dispatch",
                dispatch_id="dispatch-busy-target",
                exchange_request_id="req-busy-target",
                source_agent_id="agent-a",
                target_agent_id="agent-b",
                target_handle_id="codex-busy-handle",
                target_provider="codex-cli",
                request_kind="review",
                request_summary="Wait until target is idle.",
            )

            result = service.run_agent_dispatch_worker_once(
                "workspace-dispatch",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                codex_executable=str(root / "missing-codex.cmd"),
                dry_run=False,
            )

            self.assertEqual(result["processedCount"], 0)
            self.assertEqual(result["skippedCount"], 1)
            item = result["agentDispatches"][0]
            self.assertEqual(item["skipReason"], "target_runtime_busy")
            self.assertEqual(item["providerRuntimeStatus"]["runtimeState"], "busy")
            self.assertEqual(item["busyBackoff"]["busySkipCount"], 1)
            self.assertEqual(item["busyBackoff"]["busyRetryDelaySeconds"], 5)
            status = service.get_agent_dispatch_status(
                "workspace-dispatch",
                dispatch_id="dispatch-busy-target",
            )
            self.assertEqual(status["agentDispatch"]["status"], "queued")
            self.assertEqual(status["agentDispatch"]["attemptCount"], 0)
            self.assertEqual(status["agentDispatch"]["busySkipCount"], 1)
            self.assertEqual(status["agentDispatch"]["busyRetryDelaySeconds"], 5)
            self.assertIsNotNone(status["agentDispatch"]["nextAttemptAfter"])
            self.assertEqual(
                status["readableStatusReason"]["reasonCode"],
                "target_runtime_busy",
            )
            self.assertIn(
                "skipped",
                status["readableStatusReason"]["message"].lower(),
            )
            self.assertIn(
                "skipped",
                [event["stage"] for event in status["statusTimeline"]["events"]],
            )
            next_attempt = datetime.fromisoformat(
                str(status["agentDispatch"]["nextAttemptAfter"])
            )
            immediate = service.run_agent_dispatch_worker_once(
                "workspace-dispatch",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                dry_run=False,
                occurred_at=next_attempt - timedelta(seconds=1),
            )
            self.assertEqual(immediate["candidateCount"], 0)
            self.assertEqual(immediate["selectedCount"], 0)
            observed_delays = [5]
            retry_at = next_attempt
            for expected_delay in (15, 30, 60, 60):
                retried = service.run_agent_dispatch_worker_once(
                    "workspace-dispatch",
                    database_path=str(root / "platform.sqlite3"),
                    workspace_root=str(root / "workspace"),
                    plugins_directory=str(root / "plugins"),
                    dry_run=False,
                    occurred_at=retry_at,
                )
                backoff = retried["agentDispatches"][0]["busyBackoff"]
                observed_delays.append(backoff["busyRetryDelaySeconds"])
                retry_at = datetime.fromisoformat(str(backoff["nextAttemptAfter"]))
                self.assertEqual(backoff["busyRetryDelaySeconds"], expected_delay)
            self.assertEqual(observed_delays, [5, 15, 30, 60, 60])

    def test_worker_skips_live_probe_busy_target_runtime_without_activation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            probe_payload = json.dumps(
                {"threadStatus": "running", "threadId": "codex-thread-live-busy"}
            )
            service.register_codex_session_handle(
                "workspace-dispatch",
                agent_id="agent-b",
                handle_id="codex-live-busy-handle",
                codex_session_id="codex-live-busy-session",
                cwd=str(root),
                created_by="user",
                reason="live busy target fixture",
                metadata={
                    "providerRuntimeStatusProbe": {
                        "mode": "local_command_json",
                        "argv": [
                            sys.executable,
                            "-c",
                            f"print({probe_payload!r})",
                        ],
                    },
                },
            )
            service.create_agent_dispatch(
                "workspace-dispatch",
                dispatch_id="dispatch-live-busy-target",
                exchange_request_id="req-live-busy-target",
                source_agent_id="agent-a",
                target_agent_id="agent-b",
                target_handle_id="codex-live-busy-handle",
                target_provider="codex-cli",
                request_kind="review",
                request_summary="Wait until live target is idle.",
            )

            result = service.run_agent_dispatch_worker_once(
                "workspace-dispatch",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                codex_executable=str(root / "missing-codex.cmd"),
                dry_run=False,
            )

            self.assertEqual(result["processedCount"], 0)
            self.assertEqual(result["skippedCount"], 1)
            item = result["agentDispatches"][0]
            self.assertEqual(item["skipReason"], "target_runtime_busy")
            self.assertEqual(item["providerRuntimeStatus"]["runtimeState"], "busy")
            self.assertEqual(
                item["providerRuntimeStatus"]["providerRuntimeStatusReadMode"],
                "local_command_probe",
            )
            self.assertEqual(
                item["providerRuntimeStatus"]["runtimeStatusPolicy"],
                "auto",
            )
            status = service.get_agent_dispatch_status(
                "workspace-dispatch",
                dispatch_id="dispatch-live-busy-target",
            )
            self.assertEqual(status["agentDispatch"]["status"], "queued")
            self.assertEqual(status["agentDispatch"]["attemptCount"], 0)

    def test_worker_blocks_waiting_for_agent_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            service.register_codex_session_handle(
                "workspace-dispatch",
                agent_id="agent-b",
                handle_id="codex-blocked-handle",
                codex_session_id="codex-blocked-session",
                cwd=str(root),
                created_by="user",
                reason="blocked target fixture",
                metadata={
                    "providerRuntimeStatus": {
                        "threadStatus": "waiting_for_agent",
                    }
                },
            )
            service.create_agent_dispatch(
                "workspace-dispatch",
                dispatch_id="dispatch-blocked-target",
                exchange_request_id="req-blocked-target",
                source_agent_id="agent-a",
                target_agent_id="agent-b",
                target_handle_id="codex-blocked-handle",
                target_provider="codex-cli",
                request_kind="review",
                request_summary="Do not reactivate a blocked target.",
            )

            result = service.run_agent_dispatch_worker_once(
                "workspace-dispatch",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                codex_executable=str(root / "missing-codex.cmd"),
                dry_run=False,
            )

            self.assertEqual(result["processedCount"], 0)
            self.assertEqual(result["skippedCount"], 1)
            item = result["agentDispatches"][0]
            self.assertEqual(item["skipReason"], "target_runtime_blocked")
            self.assertEqual(item["providerRuntimeStatus"]["runtimeState"], "blocked")
            self.assertFalse(item["agentDispatch"]["providerActivationExecuted"])

    def test_worker_timeline_distinguishes_runtime_probe_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            service.register_codex_session_handle(
                "workspace-dispatch",
                agent_id="agent-b",
                handle_id="codex-probe-failure",
                codex_session_id="codex-probe-failure-session",
                cwd=str(root),
                created_by="user",
                reason="probe failure timeline fixture",
                metadata={
                    "providerRuntimeStatusProbe": {
                        "mode": "local_command_json",
                        "argv": [sys.executable, "-c", "raise SystemExit(4)"],
                    }
                },
            )
            service.create_agent_dispatch(
                "workspace-dispatch",
                dispatch_id="dispatch-probe-failure",
                exchange_request_id="req-probe-failure",
                source_agent_id="agent-a",
                target_agent_id="agent-b",
                target_handle_id="codex-probe-failure",
                target_provider="codex",
                request_kind="review",
                request_summary="Expose failed runtime probe separately.",
            )

            service.run_agent_dispatch_worker_once(
                "workspace-dispatch",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                codex_executable=str(root / "missing-codex.cmd"),
                dry_run=False,
            )
            status = service.get_agent_dispatch_status(
                "workspace-dispatch",
                dispatch_id="dispatch-probe-failure",
                read_live_runtime_status="disabled",
            )

            self.assertIn(
                "probe_failed",
                [event["stage"] for event in status["statusTimeline"]["events"]],
            )
            precheck = status["agentDispatch"]["metadata"][
                "providerRuntimePrecheck"
            ]
            self.assertTrue(precheck["probeFailed"])
            self.assertEqual(precheck["reasonCode"], "probe_failed")

    def test_busy_candidate_does_not_consume_activation_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            capture_path = root / "hermes-after-busy.json"
            fake_hermes = _fake_hermes_command(
                root,
                session_id,
                capture_path,
                "Second target completed after busy skip.",
            )
            service.register_codex_session_handle(
                "workspace-dispatch",
                agent_id="agent-b",
                handle_id="codex-first-busy",
                codex_session_id="codex-first-busy-session",
                cwd=str(root),
                created_by="user",
                reason="first busy candidate",
                metadata={"providerRuntimeStatus": {"threadStatus": "running"}},
            )
            service.register_hermes_session_handle(
                "workspace-dispatch",
                agent_id="agent-b",
                handle_id="hermes-second-idle",
                hermes_session_id=session_id,
                cwd=str(root),
                created_by="user",
                reason="second executable candidate",
                metadata={"providerRuntimeStatus": {"runStatus": "idle"}},
            )
            created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
            service.create_agent_dispatch(
                "workspace-dispatch",
                dispatch_id="dispatch-first-busy",
                exchange_request_id="req-first-busy",
                source_agent_id="agent-a",
                target_agent_id="agent-b",
                target_handle_id="codex-first-busy",
                target_provider="codex",
                request_kind="review",
                request_summary="Busy candidate should back off.",
                occurred_at=created_at,
            )
            service.create_agent_dispatch(
                "workspace-dispatch",
                dispatch_id="dispatch-second-idle",
                exchange_request_id="req-second-idle",
                source_agent_id="agent-a",
                target_agent_id="agent-b",
                target_handle_id="hermes-second-idle",
                target_provider="hermes",
                request_kind="review",
                request_summary="Executable candidate should not starve.",
                occurred_at=created_at + timedelta(seconds=1),
            )

            result = service.run_agent_dispatch_worker_once(
                "workspace-dispatch",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                hermes_executable=str(fake_hermes),
                limit=1,
                dry_run=False,
            )

            self.assertEqual(result["selectedCount"], 2)
            self.assertEqual(result["activationSelectedCount"], 1)
            self.assertEqual(result["skippedCount"], 1)
            self.assertEqual(result["processedCount"], 1)
            self.assertEqual(
                [item.get("skipReason") for item in result["agentDispatches"]],
                ["target_runtime_busy", None],
            )
            self.assertEqual(
                result["agentDispatches"][1]["finalStatus"],
                "completed",
            )
            self.assertTrue(capture_path.exists())

    def test_busy_backoff_clears_current_delay_after_target_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            SqlitePlatformPersistence(connection).initialize()
            service = _service(connection)
            _seed_workspace(service)
            session_id = str(uuid4())
            state_path = root / "runtime-state.json"
            state_path.write_text(json.dumps({"runStatus": "running"}), encoding="utf-8")
            probe_code = (
                "import pathlib; print(pathlib.Path(" + repr(str(state_path)) + ").read_text(encoding='utf-8'))"
            )
            capture_path = root / "hermes-recovered.json"
            fake_hermes = _fake_hermes_command(
                root,
                session_id,
                capture_path,
                "Recovered target completed.",
            )
            service.register_hermes_session_handle(
                "workspace-dispatch",
                agent_id="agent-b",
                handle_id="hermes-backoff-recovery",
                hermes_session_id=session_id,
                cwd=str(root),
                created_by="user",
                reason="busy recovery fixture",
                metadata={
                    "providerRuntimeStatusProbe": {
                        "mode": "local_command_json",
                        "argv": [sys.executable, "-c", probe_code],
                    }
                },
            )
            service.create_agent_dispatch(
                "workspace-dispatch",
                dispatch_id="dispatch-backoff-recovery",
                exchange_request_id="req-backoff-recovery",
                source_agent_id="agent-a",
                target_agent_id="agent-b",
                target_handle_id="hermes-backoff-recovery",
                target_provider="hermes",
                request_kind="review",
                request_summary="Resume after target becomes idle.",
            )
            first_at = datetime.now(timezone.utc) - timedelta(seconds=6)
            first = service.run_agent_dispatch_worker_once(
                "workspace-dispatch",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                hermes_executable=str(fake_hermes),
                dry_run=False,
                occurred_at=first_at,
            )
            self.assertEqual(first["skippedCount"], 1)
            state_path.write_text(json.dumps({"runStatus": "idle"}), encoding="utf-8")

            recovered = service.run_agent_dispatch_worker_once(
                "workspace-dispatch",
                database_path=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
                hermes_executable=str(fake_hermes),
                dry_run=False,
                occurred_at=first_at + timedelta(seconds=5),
            )

            dispatch = recovered["agentDispatches"][0]["agentDispatch"]
            self.assertEqual(dispatch["status"], "completed")
            self.assertEqual(dispatch["busySkipCount"], 1)
            self.assertIsNotNone(dispatch["lastBusySkipAt"])
            self.assertIsNone(dispatch["busyRetryDelaySeconds"])
            self.assertIsNone(dispatch["nextAttemptAfter"])
            self.assertFalse(dispatch["busyBackoffActive"])

    def test_waiting_response_aging_warns_without_reactivation(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_workspace(service)
        old = datetime.now(timezone.utc) - timedelta(seconds=700)
        service.create_agent_dispatch(
            "workspace-dispatch",
            dispatch_id="dispatch-waiting-stale",
            exchange_request_id="req-waiting-stale",
            source_agent_id="agent-a",
            target_agent_id="agent-b",
            target_handle_id="missing-waiting-handle",
            target_provider="codex",
            request_kind="review",
            request_summary="Wait without automatic reactivation.",
            occurred_at=old,
        )
        lease = service.acquire_agent_dispatch_lease(
            "workspace-dispatch",
            dispatch_id="dispatch-waiting-stale",
            acquired_by="test-worker",
            occurred_at=old + timedelta(seconds=1),
        )["agentDispatchLease"]
        service.release_agent_dispatch_lease(
            "workspace-dispatch",
            lease_id=str(lease["leaseId"]),
            final_dispatch_status="waiting_response",
            provider_activation_executed=True,
            occurred_at=old + timedelta(seconds=2),
        )

        status = service.get_agent_exchange_status_summary(
            "workspace-dispatch",
            dispatch_id="dispatch-waiting-stale",
            waiting_response_stale_threshold_seconds=300,
        )
        waiting = status["waitingResponseStatus"]
        self.assertGreaterEqual(waiting["waitingResponseAgeSeconds"], 698)
        self.assertTrue(waiting["waitingResponseStale"])
        self.assertEqual(waiting["recommendedAction"], "manual_review")
        self.assertEqual(
            {item["action"] for item in waiting["manualActions"]},
            {"close_as_expired", "create_retry_dispatch"},
        )
        self.assertFalse(waiting["automaticRetryScheduled"])
        self.assertFalse(waiting["providerActivationTriggered"])
        self.assertIn(
            "waiting_response_stale",
            [event["stage"] for event in status["statusTimeline"]["events"]],
        )
        worker = service.run_agent_dispatch_worker_once(
            "workspace-dispatch",
            database_path="X:/fixture/workspace-dispatch/platform.sqlite3",
            workspace_root="X:/fixture/workspace-dispatch",
            plugins_directory="X:/fixture/workspace-dispatch/plugins",
            dry_run=False,
        )
        self.assertEqual(worker["candidateCount"], 0)
        self.assertEqual(worker["processedCount"], 0)

    def test_worker_fails_dispatch_without_target_handle_before_activation(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_workspace(service)
        service.create_agent_dispatch(
            "workspace-dispatch",
            dispatch_id="dispatch-no-handle",
            exchange_request_id="req-no-handle",
            source_agent_id="agent-a",
            target_agent_id="agent-b",
            target_provider="codex-cli",
            request_kind="review",
            request_summary="Review without a registered target handle.",
        )

        result = service.run_agent_dispatch_worker_once(
            "workspace-dispatch",
            database_path="X:/fixture/workspace-dispatch/platform.sqlite3",
            workspace_root="X:/fixture/workspace-dispatch",
            plugins_directory="X:/fixture/workspace-dispatch/plugins",
            dry_run=False,
        )

        dispatch = result["agentDispatches"][0]["agentDispatch"]
        self.assertEqual(dispatch["status"], "failed")
        self.assertEqual(dispatch["attemptCount"], 1)
        self.assertFalse(dispatch["providerActivationExecuted"])
        self.assertEqual(
            dispatch["metadata"]["failureCategory"],
            "missing_target_handle",
        )


class AgentDispatchApplicationTests(unittest.TestCase):
    def test_send_dispatch_resolves_endpoint_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = LocalPlatformApplication(
                LocalPlatformSettings(
                    database=str(root / "platform.sqlite3"),
                    workspace_root=str(root / "workspace"),
                    plugins_directory=str(root / "plugins"),
                )
            )
            app.create_workspace(
                workspace_id="workspace-dispatch-app",
                display_name="Dispatch App Workspace",
                root_path=str(root),
                agent_id="agent-a",
            )
            app.create_agent(
                workspace_id="workspace-dispatch-app",
                agent_id="agent-b",
                name="Agent B",
                description="Target agent.",
            )
            app.register_codex_session_handle(
                workspace_id="workspace-dispatch-app",
                agent_id="agent-a",
                handle_id="codex-source-handle",
                codex_session_id="codex-source-session",
                cwd=str(root),
                created_by="user",
                reason="source endpoint fixture",
            )
            app.register_hermes_session_handle(
                workspace_id="workspace-dispatch-app",
                agent_id="agent-b",
                handle_id="hermes-target-handle",
                hermes_session_id="hermes-target-session",
                cwd=str(root),
                created_by="user",
                reason="target endpoint fixture",
            )
            app.login_agent_endpoint(
                workspace_id="workspace-dispatch-app",
                agent_id="agent-a",
                alias="Codex-Source",
                provider="codex",
                provider_handle_id="codex-source-handle",
                direction="send_only",
                default_reply_policy="source_handle_required",
                created_by="user",
                reason="source endpoint login",
            )
            app.login_agent_endpoint(
                workspace_id="workspace-dispatch-app",
                agent_id="agent-b",
                alias="Hermes-Target",
                provider="hermes-desktop",
                provider_handle_id="hermes-target-handle",
                direction="receive_only",
                created_by="user",
                reason="target endpoint login",
            )

            result = app.send_agent_dispatch(
                workspace_id="workspace-dispatch-app",
                dispatch_id="dispatch-alias-send",
                exchange_request_id="req-alias-send",
                from_endpoint_alias="codex-source",
                to_endpoint_alias="hermes-target",
                message="Review via endpoint aliases.",
            )

            dispatch = result["agentDispatch"]
            self.assertEqual(result["apiLayer"], "delivery-oriented")
            self.assertEqual(result["dispatchApiLayer"]["apiLayer"], "delivery-oriented")
            self.assertEqual(result["sendModeSummary"]["deliveryMode"], "queued")
            self.assertTrue(result["sendModeSummary"]["senderCanExitAfterQueue"])
            self.assertEqual(dispatch["sourceAgentId"], "agent-a")
            self.assertEqual(dispatch["targetAgentId"], "agent-b")
            self.assertEqual(dispatch["sourceHandleId"], "codex-source-handle")
            self.assertEqual(dispatch["targetHandleId"], "hermes-target-handle")
            self.assertEqual(dispatch["targetProvider"], "hermes")
            self.assertEqual(dispatch["replyPolicy"], "source_handle_required")
            resolution = result["endpointAliasResolution"]
            self.assertTrue(resolution["sourceEndpointAliasResolved"])
            self.assertTrue(resolution["targetEndpointAliasResolved"])
            self.assertEqual(
                resolution["sourceEndpoint"]["alias"],
                "codex-source",
            )
            self.assertEqual(
                resolution["targetEndpoint"]["provider"],
                "hermes",
            )
            self.assertEqual(
                resolution["replyPolicySource"],
                "source_endpoint_default",
            )
            self.assertTrue(
                resolution["replyReachability"]["replyReachable"],
            )
            self.assertEqual(
                resolution["contactPolicyDecision"]["decision"],
                "allowed",
            )
            self.assertEqual(
                dispatch["metadata"]["agentDispatchSend"][
                    "endpointAliasResolution"
                ]["targetEndpoint"]["alias"],
                "hermes-target",
            )
            self.assertEqual(
                result["agentExchangeRequest"]["sourceAgentId"],
                "agent-a",
            )
            self.assertEqual(
                result["agentExchangeRequest"]["targetAgentId"],
                "agent-b",
            )
            self.assertEqual(
                result["agentExchangeRequest"]["requestKind"],
                "sync",
            )
            self.assertEqual(
                result["agentExchangeRequest"]["requestSummary"],
                "Review via endpoint aliases.",
            )

    def test_send_dispatch_rejects_endpoint_alias_conflicts_and_wrong_direction(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = LocalPlatformApplication(
                LocalPlatformSettings(
                    database=str(root / "platform.sqlite3"),
                    workspace_root=str(root / "workspace"),
                    plugins_directory=str(root / "plugins"),
                )
            )
            app.create_workspace(
                workspace_id="workspace-dispatch-app",
                display_name="Dispatch App Workspace",
                root_path=str(root),
                agent_id="agent-a",
            )
            app.create_agent(
                workspace_id="workspace-dispatch-app",
                agent_id="agent-b",
                name="Agent B",
                description="Target agent.",
            )
            app.register_codex_session_handle(
                workspace_id="workspace-dispatch-app",
                agent_id="agent-a",
                handle_id="codex-source-handle",
                codex_session_id="codex-source-session",
                cwd=str(root),
                created_by="user",
                reason="source endpoint fixture",
            )
            app.register_hermes_session_handle(
                workspace_id="workspace-dispatch-app",
                agent_id="agent-b",
                handle_id="hermes-target-handle",
                hermes_session_id="hermes-target-session",
                cwd=str(root),
                created_by="user",
                reason="target endpoint fixture",
            )
            app.login_agent_endpoint(
                workspace_id="workspace-dispatch-app",
                agent_id="agent-a",
                alias="Codex-Receive-Only",
                provider="codex",
                provider_handle_id="codex-source-handle",
                direction="receive_only",
                created_by="user",
                reason="wrong direction source endpoint",
            )
            app.login_agent_endpoint(
                workspace_id="workspace-dispatch-app",
                agent_id="agent-b",
                alias="Hermes-Target",
                provider="hermes",
                provider_handle_id="hermes-target-handle",
                direction="receive_only",
                created_by="user",
                reason="target endpoint login",
            )

            with self.assertRaisesRegex(
                ValueError,
                "source endpoint direction does not allow sending",
            ):
                app.send_agent_dispatch(
                    workspace_id="workspace-dispatch-app",
                    from_endpoint_alias="codex-receive-only",
                    to_endpoint_alias="hermes-target",
                    request_kind="review",
                    request_summary="Rejected by source direction.",
                )

            with self.assertRaisesRegex(
                ValueError,
                "target endpoint targetAgentId conflicts",
            ):
                app.send_agent_dispatch(
                    workspace_id="workspace-dispatch-app",
                    source_agent_id="agent-a",
                    target_agent_id="agent-a",
                    to_endpoint_alias="hermes-target",
                    request_kind="review",
                    request_summary="Rejected by explicit target conflict.",
                )

            app.deactivate_hermes_session_handle(
                workspace_id="workspace-dispatch-app",
                handle_id="hermes-target-handle",
                deactivated_by="user",
                reason="target handle retired",
            )
            with self.assertRaisesRegex(
                ValueError,
                "target endpoint provider handle is not active",
            ):
                app.send_agent_dispatch(
                    workspace_id="workspace-dispatch-app",
                    source_agent_id="agent-a",
                    to_endpoint_alias="hermes-target",
                    request_kind="review",
                    request_summary="Rejected by inactive target handle.",
                )

    def test_send_dispatch_enforces_reply_reachability_and_contact_policy(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = LocalPlatformApplication(
                LocalPlatformSettings(
                    database=str(root / "platform.sqlite3"),
                    workspace_root=str(root / "workspace"),
                    plugins_directory=str(root / "plugins"),
                )
            )
            app.create_workspace(
                workspace_id="workspace-dispatch-policy",
                display_name="Dispatch Policy Workspace",
                root_path=str(root),
                agent_id="agent-a",
            )
            app.create_agent(
                workspace_id="workspace-dispatch-policy",
                agent_id="agent-b",
                name="Agent B",
                description="Target agent.",
            )
            app.register_codex_session_handle(
                workspace_id="workspace-dispatch-policy",
                agent_id="agent-a",
                handle_id="codex-source-handle",
                codex_session_id="codex-source-session",
                cwd=str(root),
                created_by="user",
                reason="source endpoint fixture",
            )
            app.register_hermes_session_handle(
                workspace_id="workspace-dispatch-policy",
                agent_id="agent-b",
                handle_id="hermes-target-handle",
                hermes_session_id="hermes-target-session",
                cwd=str(root),
                created_by="user",
                reason="target endpoint fixture",
            )
            app.login_agent_endpoint(
                workspace_id="workspace-dispatch-policy",
                agent_id="agent-a",
                alias="Codex-Source",
                provider="codex",
                provider_handle_id="codex-source-handle",
                direction="send_only",
                default_reply_policy="source_handle_required",
                created_by="user",
                reason="source endpoint login",
            )
            for alias, contact_policy in (
                ("Hermes-Open", "open"),
                ("Hermes-Contacts", "contacts_only"),
                ("Hermes-Blocked", "block_all"),
            ):
                app.login_agent_endpoint(
                    workspace_id="workspace-dispatch-policy",
                    agent_id="agent-b",
                    alias=alias,
                    provider="hermes",
                    provider_handle_id="hermes-target-handle",
                    direction="receive_only",
                    contact_policy=contact_policy,
                    created_by="user",
                    reason=f"{contact_policy} target endpoint login",
                )

            with self.assertRaisesRegex(
                ValueError,
                "source endpoint alias is required for reply-reachable",
            ):
                app.send_agent_dispatch(
                    workspace_id="workspace-dispatch-policy",
                    source_agent_id="agent-a",
                    to_endpoint_alias="hermes-open",
                    request_kind="review",
                    request_summary="Missing source endpoint.",
                )

            message_only = app.send_agent_dispatch(
                workspace_id="workspace-dispatch-policy",
                dispatch_id="dispatch-message-only",
                exchange_request_id="req-message-only",
                source_agent_id="agent-a",
                to_endpoint_alias="hermes-open",
                reply_policy="message_only",
                request_kind="review",
                request_summary="Message-only dispatch.",
            )
            self.assertFalse(
                message_only["endpointAliasResolution"]["replyReachability"][
                    "replyRequired"
                ],
            )

            with self.assertRaisesRegex(
                ValueError,
                "contactPolicy=contacts_only requires a source endpoint alias",
            ):
                app.send_agent_dispatch(
                    workspace_id="workspace-dispatch-policy",
                    source_agent_id="agent-a",
                    to_endpoint_alias="hermes-contacts",
                    reply_policy="message_only",
                    request_kind="review",
                    request_summary="Contacts-only without source endpoint.",
                )

            with self.assertRaisesRegex(
                ValueError,
                "contactPolicy blocks incoming dispatch",
            ):
                app.send_agent_dispatch(
                    workspace_id="workspace-dispatch-policy",
                    from_endpoint_alias="codex-source",
                    to_endpoint_alias="hermes-blocked",
                    request_kind="review",
                    request_summary="Blocked by target endpoint.",
                )

            contacts_allowed = app.send_agent_dispatch(
                workspace_id="workspace-dispatch-policy",
                dispatch_id="dispatch-contacts-allowed",
                exchange_request_id="req-contacts-allowed",
                from_endpoint_alias="codex-source",
                to_endpoint_alias="hermes-contacts",
                request_kind="review",
                request_summary="Contacts-only with source endpoint.",
            )
            self.assertEqual(
                contacts_allowed["endpointAliasResolution"][
                    "contactPolicyDecision"
                ]["decision"],
                "allowed",
            )

    def test_send_dispatch_enforces_contact_allowlist_and_blocklist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = LocalPlatformApplication(
                LocalPlatformSettings(
                    database=str(root / "platform.sqlite3"),
                    workspace_root=str(root / "workspace"),
                    plugins_directory=str(root / "plugins"),
                )
            )
            app.create_workspace(
                workspace_id="workspace-contact-lists",
                display_name="Contact List Workspace",
                root_path=str(root),
                agent_id="agent-a",
            )
            app.create_agent(
                workspace_id="workspace-contact-lists",
                agent_id="agent-b",
                name="Agent B",
                description="Target agent.",
            )
            app.create_agent(
                workspace_id="workspace-contact-lists",
                agent_id="agent-c",
                name="Agent C",
                description="Unlisted source agent.",
            )
            for agent_id, handle_id, session_id in (
                ("agent-a", "codex-source-handle", "codex-source-session"),
                ("agent-c", "codex-other-handle", "codex-other-session"),
            ):
                app.register_codex_session_handle(
                    workspace_id="workspace-contact-lists",
                    agent_id=agent_id,
                    handle_id=handle_id,
                    codex_session_id=session_id,
                    cwd=str(root),
                    created_by="user",
                    reason="source endpoint fixture",
                )
            app.register_hermes_session_handle(
                workspace_id="workspace-contact-lists",
                agent_id="agent-b",
                handle_id="hermes-target-handle",
                hermes_session_id="hermes-target-session",
                cwd=str(root),
                created_by="user",
                reason="target endpoint fixture",
            )
            app.login_agent_endpoint(
                workspace_id="workspace-contact-lists",
                agent_id="agent-a",
                alias="codex-source",
                provider="codex",
                provider_handle_id="codex-source-handle",
                direction="send_only",
                created_by="user",
                reason="allowed source endpoint login",
            )
            app.login_agent_endpoint(
                workspace_id="workspace-contact-lists",
                agent_id="agent-c",
                alias="codex-other",
                provider="codex",
                provider_handle_id="codex-other-handle",
                direction="send_only",
                created_by="user",
                reason="blocked source endpoint login",
            )
            app.login_agent_endpoint(
                workspace_id="workspace-contact-lists",
                agent_id="agent-b",
                alias="hermes-contacts-listed",
                provider="hermes",
                provider_handle_id="hermes-target-handle",
                direction="receive_only",
                contact_policy="contacts_only",
                allow_source_endpoint_aliases=("codex-source",),
                created_by="user",
                reason="contacts only target endpoint login",
            )
            app.login_agent_endpoint(
                workspace_id="workspace-contact-lists",
                agent_id="agent-b",
                alias="hermes-open-blocked",
                provider="hermes",
                provider_handle_id="hermes-target-handle",
                direction="receive_only",
                contact_policy="open",
                block_source_endpoint_aliases=("codex-other",),
                created_by="user",
                reason="open target endpoint with blocklist login",
            )

            allowed = app.send_agent_dispatch(
                workspace_id="workspace-contact-lists",
                dispatch_id="dispatch-contact-allowed",
                exchange_request_id="req-contact-allowed",
                from_endpoint_alias="codex-source",
                to_endpoint_alias="hermes-contacts-listed",
                request_kind="review",
                request_summary="Allowed by contact allowlist.",
            )

            decision = allowed["endpointAliasResolution"]["contactPolicyDecision"]
            self.assertTrue(decision["allowlistConfigured"])
            self.assertEqual(
                decision["matchedAllowlistRules"][0]["value"],
                "codex-source",
            )

            with self.assertRaisesRegex(ValueError, "does not allow source endpoint"):
                app.send_agent_dispatch(
                    workspace_id="workspace-contact-lists",
                    from_endpoint_alias="codex-other",
                    to_endpoint_alias="hermes-contacts-listed",
                    request_kind="review",
                    request_summary="Rejected by missing contact allowlist entry.",
                )

            with self.assertRaisesRegex(ValueError, "blocks source endpoint"):
                app.send_agent_dispatch(
                    workspace_id="workspace-contact-lists",
                    from_endpoint_alias="codex-other",
                    to_endpoint_alias="hermes-open-blocked",
                    request_kind="review",
                    request_summary="Rejected by explicit blocklist.",
                )

    def test_send_dispatch_executes_hermes_worker_in_one_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = LocalPlatformApplication(
                LocalPlatformSettings(
                    database=str(root / "platform.sqlite3"),
                    workspace_root=str(root / "workspace"),
                    plugins_directory=str(root / "plugins"),
                )
            )
            app.create_workspace(
                workspace_id="workspace-dispatch-app",
                display_name="Dispatch App Workspace",
                root_path=str(root),
                agent_id="agent-a",
            )
            app.create_agent(
                workspace_id="workspace-dispatch-app",
                agent_id="agent-b",
                name="Agent B",
                description="Target agent.",
            )
            session_id = str(uuid4())
            response_text = "send captured Hermes dispatch response."
            capture_path = root / "hermes-send-capture.json"
            fake_hermes = _fake_hermes_command(
                root,
                session_id,
                capture_path,
                response_text,
            )
            app.register_hermes_session_handle(
                workspace_id="workspace-dispatch-app",
                agent_id="agent-b",
                handle_id="hermes-handle-send",
                hermes_session_id=session_id,
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )

            result = app.send_agent_dispatch(
                workspace_id="workspace-dispatch-app",
                dispatch_id="dispatch-hermes-send",
                exchange_request_id="req-hermes-send",
                source_agent_id="agent-a",
                target_agent_id="agent-b",
                target_handle_id="hermes-handle-send",
                target_provider="hermes-cli",
                request_kind="review",
                request_summary="Review via high-level dispatch send.",
                delivery_mode="worker_execute",
                handoff_directory=str(root / "handoff"),
                hermes_executable=str(fake_hermes),
                activation_timeout_seconds=30,
            )

            self.assertEqual(result["schema"], "agent_dispatch_send.v1")
            self.assertEqual(result["apiLayer"], "delivery-oriented")
            self.assertEqual(result["deliveryMode"], "worker_execute")
            self.assertEqual(result["sendModeSummary"]["waitMode"], "once")
            self.assertFalse(result["sendModeSummary"]["senderCanExitAfterQueue"])
            self.assertTrue(result["queuedDispatchCreated"])
            self.assertTrue(result["workerRunRequested"])
            self.assertTrue(result["workerExecuted"])
            self.assertEqual(result["agentDispatch"]["status"], "completed")
            self.assertEqual(result["agentDispatch"]["attemptCount"], 1)
            self.assertTrue(result["agentDispatch"]["providerActivationExecuted"])
            self.assertEqual(
                result["agentDispatch"]["metadata"]["agentDispatchSend"][
                    "deliveryMode"
                ],
                "worker_execute",
            )
            self.assertTrue(
                result["agentDispatch"]["metadata"]["agentDispatchSend"][
                    "highLevelDispatchApi"
                ]
            )
            self.assertEqual(result["agentExchangeRequest"]["status"], "terminal")
            self.assertEqual(
                result["agentExchangeRequest"]["responseSummary"],
                response_text,
            )
            self.assertEqual(result["workerRun"]["processedCount"], 1)
            self.assertTrue(capture_path.exists())

    def test_send_wait_once_forwards_default_codex_repo_check_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = LocalPlatformApplication(
                LocalPlatformSettings(
                    database=str(root / "platform.sqlite3"),
                    workspace_root=str(root / "workspace"),
                    plugins_directory=str(root / "plugins"),
                )
            )
            app.create_workspace(
                workspace_id="workspace-dispatch-codex",
                display_name="Dispatch Codex Workspace",
                root_path=str(root),
                agent_id="agent-a",
            )
            app.create_agent(
                workspace_id="workspace-dispatch-codex",
                agent_id="agent-b",
                name="Agent B",
                description="Target agent.",
            )
            session_id = str(uuid4())
            capture_path = root / "codex-send-capture.json"
            app.register_codex_session_handle(
                workspace_id="workspace-dispatch-codex",
                agent_id="agent-b",
                handle_id="codex-handle-send",
                codex_session_id=session_id,
                cwd=str(root),
                created_by="user",
                reason="explicit registration",
            )

            result = app.send_agent_dispatch(
                workspace_id="workspace-dispatch-codex",
                dispatch_id="dispatch-codex-send",
                exchange_request_id="req-codex-send",
                source_agent_id="agent-a",
                target_agent_id="agent-b",
                target_handle_id="codex-handle-send",
                target_provider="codex-cli",
                request_kind="review",
                request_summary="Review via high-level Codex dispatch send.",
                delivery_mode="worker_execute",
                handoff_directory=str(root / "handoff"),
                codex_executable=str(
                    _fake_codex_command(root, session_id, capture_path)
                ),
                activation_timeout_seconds=30,
            )

            activation = result["workerRun"]["agentDispatches"][0]["activation"]
            captured = json.loads(capture_path.read_text(encoding="utf-8"))
            self.assertEqual(result["deliveryMode"], "worker_execute")
            self.assertEqual(result["sendModeSummary"]["waitMode"], "once")
            self.assertEqual(activation["gitRepoCheckPolicy"], "skip")
            self.assertEqual(activation["gitRepoCheckPolicySource"], "default")
            self.assertIn("--skip-git-repo-check", captured["argv"])


def _seed_workspace(service: LocalPlatformOperationService) -> None:
    service.create_workspace(
        workspace_id="workspace-dispatch",
        display_name="Dispatch Workspace",
        root_path="X:/fixture/workspace-dispatch",
        agent_id="agent-a",
        agent_name="Agent A",
        agent_description="Source agent.",
    )
    service.create_agent_registration(
        "workspace-dispatch",
        agent_id="agent-b",
        name="Agent B",
        description="Target agent.",
    )


def _service(connection: sqlite3.Connection) -> LocalPlatformOperationService:
    return LocalPlatformOperationService(
        workspace_reader=SqliteWorkspaceStateStore(connection),
        context_reader=SqliteContextStateStore(connection),
        context_update_recorder=SqliteContextUpdateEventRecorder(connection),
        event_log_reader=SqlitePlatformEventLog(connection),
        agent_invocation_reader=SqliteAgentInvocationRecordStore(connection),
        file_operation_reader=SqliteFileOperationRecordStore(connection),
        conversation_session_reader=SqliteConversationStore(connection),
        conversation_message_reader=SqliteConversationStore(connection),
        agent_registration_reader=SqliteAgentRegistrationStateStore(connection),
        task_reader=SqliteTaskStateStore(connection),
        issue_reader=SqliteIssueStateStore(connection),
        workspace_writer=SqliteWorkspaceStateStore(connection),
        context_writer=SqliteContextStateStore(connection),
        agent_registration_writer=SqliteAgentRegistrationStateStore(connection),
        conversation_session_writer=SqliteConversationStore(connection),
        conversation_message_writer=SqliteConversationStore(connection),
    )


def _event_count(connection: sqlite3.Connection, event_kind: str) -> int:
    return int(
        connection.execute(
            "select count(*) from platform_events where event_kind = ?",
            (event_kind,),
        ).fetchone()[0]
    )


def _fake_hermes_command(
    root: Path,
    session_id: str,
    capture_path: Path,
    response_text: str,
) -> Path:
    script = root / "fake_hermes.py"
    if os.name == "nt":
        command = root / "fake_hermes.cmd"
    else:
        command = root / "fake_hermes"
    script.write_text(
        "\n".join(
            [
                "import json, os, pathlib, sys",
                f"SESSION_ID = {session_id!r}",
                f"RESPONSE_TEXT = {response_text!r}",
                "argv = sys.argv[1:]",
                "if argv in (['--version'], ['--help']):",
                "    print('Hermes Agent v9.8.7')",
                "    raise SystemExit(0)",
                "path = pathlib.Path(os.environ['FAKE_HERMES_CAPTURE'])",
                "path.write_text(json.dumps({",
                "  'argv': argv,",
                "  'cwd': os.getcwd(),",
                "}, sort_keys=True), encoding='utf-8')",
                "print(RESPONSE_TEXT)",
                "print('session_id=' + SESSION_ID)",
                "print('↻ Resumed session ' + SESSION_ID, file=sys.stderr)",
            ]
        ),
        encoding="utf-8",
    )
    if os.name == "nt":
        command.write_text(
            "\n".join(
                [
                    "@echo off",
                    f"set FAKE_HERMES_CAPTURE={capture_path}",
                    f'"{sys.executable}" "{script}" %*',
                ]
            ),
            encoding="utf-8",
        )
    else:
        command.write_text(
            "\n".join(
                [
                    "#!/bin/sh",
                    f"FAKE_HERMES_CAPTURE={capture_path!s} "
                    f"'{sys.executable}' '{script}' \"$@\"",
                ]
            ),
            encoding="utf-8",
        )
        command.chmod(0o755)
    return command


def _fake_codex_command(root: Path, session_id: str, capture_path: Path) -> Path:
    script = root / "fake_codex.py"
    command = root / ("fake_codex.cmd" if os.name == "nt" else "fake_codex")
    script.write_text(
        "\n".join(
            [
                "import json, os, pathlib, sys",
                f"SESSION_ID = {session_id!r}",
                "argv = sys.argv[1:]",
                "if argv == ['--version']:",
                "    print('codex-cli 9.8.7')",
                "    raise SystemExit(0)",
                "for index, item in enumerate(argv):",
                "    if item == '--output-last-message' and index + 1 < len(argv):",
                "        output = pathlib.Path(argv[index + 1])",
                "        output.parent.mkdir(parents=True, exist_ok=True)",
                "        output.write_text('Codex dispatch response.', encoding='utf-8')",
                "pathlib.Path(os.environ['FAKE_CODEX_CAPTURE']).write_text(json.dumps({'argv': argv}), encoding='utf-8')",
                "print(json.dumps({'type': 'result', 'session_id': SESSION_ID, 'result': 'Codex dispatch response.'}))",
            ]
        ),
        encoding="utf-8",
    )
    if os.name == "nt":
        command.write_text(
            "\n".join(
                [
                    "@echo off",
                    f"set FAKE_CODEX_CAPTURE={capture_path}",
                    f'"{sys.executable}" "{script}" %*',
                ]
            ),
            encoding="utf-8",
        )
    else:
        command.write_text(
            "\n".join(
                [
                    "#!/bin/sh",
                    f"FAKE_CODEX_CAPTURE='{capture_path}' '{sys.executable}' '{script}' \"$@\"",
                ]
            ),
            encoding="utf-8",
        )
        command.chmod(0o755)
    return command


if __name__ == "__main__":
    unittest.main()
