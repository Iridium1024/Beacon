from __future__ import annotations

import sqlite3
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.agent_exchange_request import (
    AgentExchangeRequest,
    AgentExchangeRequestPolicy,
    AgentExchangeThread,
)
from agent_os.application.services.local_platform_operations import (
    LocalPlatformOperationService,
)
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


class AgentExchangeRequestContractTests(unittest.TestCase):
    def test_request_and_policy_metadata_are_stable_and_guarded(self) -> None:
        policy = AgentExchangeRequestPolicy.from_mapping({"workspaceId": "workspace-req"})
        request = AgentExchangeRequest.from_mapping(
            {
                "exchangeRequestId": "req-1",
                "workspaceId": "workspace-req",
                "sourceAgentId": "agent-a",
                "targetAgentId": "agent-b",
                "requestKind": "review",
                "requestSummary": "Check the implementation summary.",
                "detailRefs": ["docs/status.md"],
                "rootRequestId": "req-1",
                "threadId": "req-1",
            }
        )

        self.assertEqual(policy.to_metadata()["authorizationMode"], "direct_allowed")
        self.assertEqual(policy.to_metadata()["subRequestPolicy"], "allowed")
        self.assertFalse(
            policy.to_metadata()["autoAppendExchangeResultToSharedContext"]
        )
        metadata = request.to_metadata()
        self.assertEqual(metadata["requestKind"], "review")
        self.assertEqual(metadata["status"], "active")
        self.assertEqual(metadata["detailRefs"], ["docs/status.md"])
        self.assertTrue(metadata["singleTargetOnly"])
        self.assertTrue(metadata["multiRequestConcurrencyAllowed"])
        self.assertFalse(metadata["autoSharedContextAppendExecuted"])
        self.assertFalse(metadata["realRuntimeConnected"])
        thread = AgentExchangeThread.from_mapping(
            {
                "exchangeThreadId": "thread-1",
                "workspaceId": "workspace-req",
                "rootRequestId": "req-1",
                "createdByAgentId": "agent-a",
                "participantAgentIds": ["agent-a", "agent-b"],
                "sourceAgentId": "agent-a",
                "targetAgentId": "agent-b",
                "visibility": "workspace_readable",
            }
        )

        thread_metadata = thread.to_metadata()
        self.assertEqual(thread_metadata["schema"], "agent_exchange_thread.v1")
        self.assertEqual(thread_metadata["maxTurns"], 5)
        self.assertEqual(thread_metadata["completedTurnCount"], 0)
        self.assertEqual(thread_metadata["activeRequestCount"], 0)
        self.assertEqual(thread_metadata["followUpPolicy"], "single_target_chain")
        self.assertTrue(thread_metadata["localInteractionContextOnly"])
        self.assertFalse(thread_metadata["workspaceScopeInherited"])
        self.assertFalse(thread_metadata["autoSharedContextAppendExecuted"])

        with self.assertRaisesRegex(ValueError, "requestKind"):
            AgentExchangeRequest.from_mapping(
                {
                    "workspaceId": "workspace-req",
                    "sourceAgentId": "agent-a",
                    "targetAgentId": "agent-b",
                    "requestKind": "unknown",
                    "requestSummary": "Invalid kind.",
                }
            )
        with self.assertRaisesRegex(ValueError, "maxRequestLength"):
            AgentExchangeRequest.from_mapping(
                {
                    "workspaceId": "workspace-req",
                    "sourceAgentId": "agent-a",
                    "targetAgentId": "agent-b",
                    "requestKind": "review",
                    "requestSummary": "too long",
                    "maxRequestLength": 3,
                }
            )
        with self.assertRaisesRegex(ValueError, "credential values"):
            AgentExchangeRequest.from_mapping(
                {
                    "workspaceId": "workspace-req",
                    "sourceAgentId": "agent-a",
                    "targetAgentId": "agent-b",
                    "requestKind": "review",
                    "requestSummary": "Do not store secrets.",
                    "metadata": {"Authorization": "Bearer placeholder-token"},
                }
            )
        with self.assertRaisesRegex(ValueError, "credential values"):
            AgentExchangeThread.from_mapping(
                {
                    "exchangeThreadId": "thread-secret",
                    "workspaceId": "workspace-req",
                    "rootRequestId": "req-1",
                    "createdByAgentId": "agent-a",
                    "participantAgentIds": ["agent-a", "agent-b"],
                    "sourceAgentId": "agent-a",
                    "targetAgentId": "agent-b",
                    "metadata": {"Cookie": "leaked"},
                }
            )


class AgentExchangeRequestOperationTests(unittest.TestCase):
    def test_create_list_respond_and_no_shared_context_auto_append(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_request_workspace(service)

        first = service.create_agent_exchange_request(
            "workspace-req",
            exchange_request_id="req-1",
            source_agent_id="agent-a",
            target_agent_id="agent-b",
            request_kind="review",
            request_summary="Please review the current implementation summary.",
            detail_refs=("docs/status.md",),
        )
        second = service.create_agent_exchange_request(
            "workspace-req",
            exchange_request_id="req-2",
            source_agent_id="agent-a",
            target_agent_id="agent-b",
            request_kind="question",
            request_summary="What open question remains?",
        )
        listed = service.list_agent_exchange_requests("workspace-req")[
            "agentExchangeRequests"
        ]
        before_respond_events = dict(
            connection.execute(
                "SELECT event_kind, COUNT(*) FROM platform_events GROUP BY event_kind"
            ).fetchall()
        )
        responded = service.respond_agent_exchange_request(
            "workspace-req",
            exchange_request_id="req-1",
            responding_agent_id="agent-b",
            response_summary="The implementation summary is consistent.",
        )["agentExchangeRequest"]
        after_respond_events = dict(
            connection.execute(
                "SELECT event_kind, COUNT(*) FROM platform_events GROUP BY event_kind"
            ).fetchall()
        )
        context = service.get_context("workspace-req")["context"]
        context_events = connection.execute(
            "SELECT COUNT(*) FROM platform_events WHERE event_kind = ?",
            ("context.update_appended",),
        ).fetchone()[0]

        self.assertTrue(first["created"])
        self.assertEqual(first["apiLayer"], "state-only")
        self.assertFalse(first["requestApiLayer"]["deliveryOrWakeAttempted"])
        self.assertFalse(first["requestApiLayer"]["dispatchQueueEntryCreated"])
        self.assertTrue(second["created"])
        self.assertEqual(
            [item["exchangeRequestId"] for item in listed],
            ["req-1", "req-2"],
        )
        self.assertEqual(responded["status"], "terminal")
        self.assertEqual(responded["terminalReason"], "responded")
        self.assertEqual(responded["respondedByAgentId"], "agent-b")
        self.assertFalse(responded["autoSharedContextAppendExecuted"])
        self.assertEqual(context["updateCount"], 0)
        self.assertEqual(context_events, 0)
        for event_kind in (
            "agent_dispatch.changed",
            "agent_dispatch_lease.changed",
            "agent_wake.delivery_recorded",
            "claude_registered_session_activation.recorded",
            "codex_registered_session_activation.recorded",
            "hermes_registered_session_activation.recorded",
        ):
            self.assertEqual(
                before_respond_events.get(event_kind, 0),
                after_respond_events.get(event_kind, 0),
            )
        self.assertEqual(
            after_respond_events["agent_exchange_request.changed"],
            before_respond_events["agent_exchange_request.changed"] + 1,
        )
        self.assertEqual(
            after_respond_events["agent_exchange_thread.changed"],
            before_respond_events["agent_exchange_thread.changed"] + 1,
        )

        thread = service.get_agent_exchange_thread_status(
            "workspace-req",
            thread_id="req-1",
        )["agentExchangeThread"]
        self.assertEqual(thread["threadStatus"], "active")
        self.assertEqual(thread["completedTurnCount"], 1)
        self.assertEqual(thread["activeRequestCount"], 0)
        self.assertEqual(thread["visibility"], "workspace_readable")
        self.assertFalse(thread["runtimeWakeTriggered"])

        summary = service.get_agent_exchange_status_summary(
            "workspace-req",
            exchange_request_id="req-1",
        )
        self.assertEqual(summary["schema"], "agent_exchange_status_summary.v1")
        self.assertIsNone(summary["agentDispatch"])
        self.assertFalse(summary["dispatchStatusBoundary"]["dispatchLinked"])
        self.assertEqual(
            summary["responseSourceStatus"]["responseSource"],
            "standard_respond",
        )
        self.assertTrue(summary["responseSourceStatus"]["standardResponded"])
        self.assertFalse(summary["responseSourceStatus"]["stdoutFallbackCaptured"])
        self.assertEqual(summary["workspace"]["workspaceId"], "workspace-req")
        self.assertEqual(summary["context"]["updateCount"], 0)
        self.assertIn(
            "responded",
            [event["stage"] for event in summary["statusTimeline"]["events"]],
        )

    def test_thread_visibility_uses_agent_config_and_can_be_updated(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_request_workspace(service)
        service.create_agent_registration(
            "workspace-req",
            agent_id="agent-d",
            name="Agent D",
            description="Unrelated workspace observer.",
        )
        service.create_agent_registration(
            "workspace-req",
            agent_id="agent-private",
            name="Private Agent",
            description="Opts out of workspace-readable threads.",
            runtime_config={
                "agentExchange": {
                    "threadWorkspaceVisible": False,
                }
            },
        )

        created = service.create_agent_exchange_request(
            "workspace-req",
            exchange_request_id="req-private-thread",
            source_agent_id="agent-a",
            target_agent_id="agent-private",
            request_kind="review",
            request_summary="Review a participant-only thread.",
        )
        listed_for_observer = service.list_agent_exchange_threads(
            "workspace-req",
            requesting_agent_id="agent-d",
        )["agentExchangeThreads"]

        self.assertEqual(
            created["agentExchangeThread"]["visibility"],
            "participants_only",
        )
        self.assertEqual(listed_for_observer, [])
        with self.assertRaisesRegex(ValueError, "not visible"):
            service.get_agent_exchange_thread_status(
                "workspace-req",
                thread_id="req-private-thread",
                requesting_agent_id="agent-d",
            )

        updated = service.update_agent_exchange_thread_visibility(
            "workspace-req",
            thread_id="req-private-thread",
            updated_by_agent_id="agent-a",
            visibility="workspace_readable",
        )["agentExchangeThread"]
        opened = service.get_agent_exchange_thread_status(
            "workspace-req",
            thread_id="req-private-thread",
            requesting_agent_id="agent-d",
        )["agentExchangeThread"]

        self.assertEqual(updated["visibility"], "workspace_readable")
        self.assertEqual(updated["visibilityUpdatedByAgentId"], "agent-a")
        self.assertEqual(opened["exchangeThreadId"], "req-private-thread")

    def test_authorization_modes_and_length_limits_are_enforced(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_request_workspace(service)

        service.update_agent_exchange_request_policy(
            "workspace-req",
            authorization_mode="disabled",
        )
        with self.assertRaisesRegex(ValueError, "disabled"):
            service.create_agent_exchange_request(
                "workspace-req",
                source_agent_id="agent-a",
                target_agent_id="agent-b",
                request_kind="review",
                request_summary="Should be blocked.",
            )

        service.update_agent_exchange_request_policy(
            "workspace-req",
            authorization_mode="direct_allowed",
            max_request_length=10,
        )
        with self.assertRaisesRegex(ValueError, "maxRequestLength"):
            service.create_agent_exchange_request(
                "workspace-req",
                source_agent_id="agent-a",
                target_agent_id="agent-b",
                request_kind="review",
                request_summary="This request is too long.",
            )

        service.update_agent_exchange_request_policy(
            "workspace-req",
            authorization_mode="delegated_grant_required",
            max_request_length=10,
        )
        with self.assertRaisesRegex(ValueError, "linkedDelegatedWakeGrantId"):
            service.create_agent_exchange_request(
                "workspace-req",
                source_agent_id="agent-a",
                target_agent_id="agent-b",
                request_kind="review",
                request_summary="Short.",
            )

        future = datetime.now(timezone.utc) + timedelta(hours=1)
        service.create_delegated_wake_grant(
            "workspace-req",
            source_agent_id="agent-a",
            target_agent_id="agent-b",
            created_by="user",
            reason="Allow one request linkage.",
            delegated_wake_grant_id="dw-req-1",
            expires_at=future,
        )
        created = service.create_agent_exchange_request(
            "workspace-req",
            exchange_request_id="req-linked",
            source_agent_id="agent-a",
            target_agent_id="agent-b",
            request_kind="review",
            request_summary="Short.",
            linked_delegated_wake_grant_id="dw-req-1",
        )["agentExchangeRequest"]

        self.assertEqual(created["authorizationMode"], "delegated_grant_required")
        self.assertEqual(created["linkedDelegatedWakeGrantId"], "dw-req-1")
        self.assertFalse(created["runtimeWakeTriggered"])

    def test_thread_turn_budget_and_follow_up_are_enforced(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_request_workspace(service)

        service.update_agent_exchange_request_policy(
            "workspace-req",
            max_turns=1,
        )
        service.create_agent_exchange_request(
            "workspace-req",
            exchange_request_id="req-budget-root",
            source_agent_id="agent-a",
            target_agent_id="agent-b",
            request_kind="question",
            request_summary="First bounded turn.",
        )
        with self.assertRaisesRegex(ValueError, "maxTurns"):
            service.create_agent_exchange_thread_follow_up(
                "workspace-req",
                thread_id="req-budget-root",
                source_agent_id="agent-a",
                target_agent_id="agent-b",
                request_kind="question",
                request_summary="Pending active request should consume budget.",
            )
        service.respond_agent_exchange_request(
            "workspace-req",
            exchange_request_id="req-budget-root",
            responding_agent_id="agent-b",
            response_summary="Budgeted answer.",
        )
        with self.assertRaisesRegex(ValueError, "maxTurns"):
            service.create_agent_exchange_thread_follow_up(
                "workspace-req",
                thread_id="req-budget-root",
                source_agent_id="agent-a",
                target_agent_id="agent-b",
                request_kind="question",
                request_summary="Completed interaction should consume budget.",
            )

        service.update_agent_exchange_request_policy(
            "workspace-req",
            max_turns=0,
        )
        service.create_agent_exchange_request(
            "workspace-req",
            exchange_request_id="req-unlimited-root",
            source_agent_id="agent-a",
            target_agent_id="agent-b",
            request_kind="question",
            request_summary="Unlimited root turn.",
        )
        service.respond_agent_exchange_request(
            "workspace-req",
            exchange_request_id="req-unlimited-root",
            responding_agent_id="agent-b",
            response_summary="Unlimited answer.",
        )
        follow_up = service.create_agent_exchange_thread_follow_up(
            "workspace-req",
            thread_id="req-unlimited-root",
            exchange_request_id="req-unlimited-follow-up",
            source_agent_id="agent-a",
            target_agent_id="agent-b",
            request_kind="question",
            request_summary="Unlimited follow-up.",
        )["agentExchangeRequest"]

        self.assertEqual(follow_up["parentRequestId"], "req-unlimited-root")
        self.assertEqual(follow_up["threadId"], "req-unlimited-root")
        self.assertEqual(follow_up["maxTurns"], 0)

        service.update_agent_exchange_request_policy(
            "workspace-req",
            max_turns=-1,
        )
        with self.assertRaisesRegex(ValueError, "maxTurns=-1"):
            service.create_agent_exchange_request(
                "workspace-req",
                source_agent_id="agent-a",
                target_agent_id="agent-b",
                request_kind="question",
                request_summary="Disabled by max turns.",
            )

    def test_sub_request_policy_preserves_parent_thread_metadata(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_request_workspace(service)

        parent = service.create_agent_exchange_request(
            "workspace-req",
            exchange_request_id="req-parent",
            source_agent_id="agent-a",
            target_agent_id="agent-b",
            request_kind="handoff",
            request_summary="Split this follow-up.",
        )["agentExchangeRequest"]
        child = service.create_agent_exchange_request(
            "workspace-req",
            exchange_request_id="req-child",
            source_agent_id="agent-b",
            target_agent_id="agent-c",
            request_kind="question",
            request_summary="Please answer the delegated question.",
            parent_request_id="req-parent",
        )["agentExchangeRequest"]

        self.assertEqual(parent["rootRequestId"], "req-parent")
        self.assertEqual(child["parentRequestId"], "req-parent")
        self.assertEqual(child["rootRequestId"], "req-parent")
        self.assertEqual(child["threadId"], "req-parent")
        self.assertEqual(child["turnIndex"], 1)
        self.assertEqual(child["subRequestPolicy"], "allowed")

        service.update_agent_exchange_request_policy(
            "workspace-req",
            sub_request_policy="disabled",
        )
        with self.assertRaisesRegex(ValueError, "sub request creation is disabled"):
            service.create_agent_exchange_request(
                "workspace-req",
                source_agent_id="agent-b",
                target_agent_id="agent-c",
                request_kind="question",
                request_summary="This child should be rejected.",
                parent_request_id="req-parent",
            )

        service.update_agent_exchange_request_policy(
            "workspace-req",
            sub_request_policy="allowed_for_configured_agents",
            allowed_sub_request_agent_ids=("agent-b",),
        )
        allowed = service.create_agent_exchange_request(
            "workspace-req",
            exchange_request_id="req-child-allowed",
            source_agent_id="agent-b",
            target_agent_id="agent-c",
            request_kind="sync",
            request_summary="Configured sub request source.",
            parent_request_id="req-parent",
        )["agentExchangeRequest"]

        self.assertEqual(allowed["subRequestPolicy"], "allowed_for_configured_agents")


def _seed_request_workspace(service: LocalPlatformOperationService) -> None:
    service.create_workspace(
        workspace_id="workspace-req",
        display_name="Request Workspace",
        root_path="X:/fixture/workspace-req",
        agent_id="agent-a",
        agent_name="Agent A",
        agent_description="Source agent.",
    )
    service.create_agent_registration(
        "workspace-req",
        agent_id="agent-b",
        name="Agent B",
        description="Target agent.",
    )
    service.create_agent_registration(
        "workspace-req",
        agent_id="agent-c",
        name="Agent C",
        description="Secondary target agent.",
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


if __name__ == "__main__":
    unittest.main()
