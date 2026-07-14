from __future__ import annotations

import sqlite3
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.local_platform_operations import (
    LocalPlatformOperationService,
)
from agent_os.domain.entities.agent import AgentCapability, AgentRegistration
from agent_os.domain.entities.context import ContextUpdateKind, ProjectSharedContext
from agent_os.domain.entities.file_operation import (
    FileOperationKind,
    FileOperationRequest,
    FileOperationResult,
    FileOperationResultStatus,
)
from agent_os.domain.entities.invocation import (
    AgentInvocationRequest,
    AgentInvocationResult,
)
from agent_os.domain.entities.task import IssueContext, IssueSeverity, TaskContext
from agent_os.domain.entities.workspace import ProjectWorkspace
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextId,
    ContextUpdateId,
    FileOperationId,
    IssueId,
    PlatformEventId,
    PlatformRunSessionId,
    TaskId,
    WorkspaceId,
)
from agent_os.infrastructure.persistence.event_log import (
    PlatformEventKind,
    PlatformEventRecord,
    SqlitePlatformEventLog,
)
from agent_os.infrastructure.persistence.file_operation_records import (
    SqliteFileOperationRecordStore,
)
from agent_os.infrastructure.persistence.invocation_records import (
    SqliteAgentInvocationRecordStore,
)
from agent_os.infrastructure.persistence.materialized_state import (
    ContextStateRecord,
    SqliteAgentRegistrationStateStore,
    SqliteContextStateStore,
    SqliteIssueStateStore,
    SqliteTaskStateStore,
    SqliteWorkspaceStateStore,
)
from agent_os.infrastructure.persistence.context_update_events import (
    SqliteContextUpdateEventRecorder,
)
from agent_os.infrastructure.persistence.conversations import SqliteConversationStore
from agent_os.infrastructure.persistence.sqlite_persistence import (
    SqlitePlatformPersistence,
)


class LocalPlatformOperationServiceTests(unittest.TestCase):
    def test_create_workspace_creates_context_default_agent_and_events(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)

        created = service.create_workspace(
            workspace_id="workspace-created-1",
            context_id="context-created-1",
            agent_id="agent-created-1",
            display_name="Created Workspace",
            root_path="X:/fixture/workspace-created-1",
            agent_name="Created Agent",
            agent_description="Handles created workspace requests",
            agent_capability_name="single-turn-status",
            agent_capability_description="Captures created workspace requests",
            created_at=datetime(2026, 6, 5, 8, 0, tzinfo=timezone.utc),
            workspace_event_id="event-workspace-created-1",
            agent_event_id="event-agent-created-1",
        )
        opened = service.open_workspace("workspace-created-1")
        events = connection.execute(
            """
            SELECT sequence, event_kind, aggregate_id, payload_json
            FROM platform_events
            ORDER BY sequence
            """
        ).fetchall()

        self.assertTrue(created["created"])
        self.assertEqual(created["workspaceSourceEventSequence"], 1)
        self.assertTrue(created["baseline"]["contextCreated"])
        self.assertTrue(created["baseline"]["agentCreated"])
        self.assertEqual(
            created["workspace"]["workspace"]["workspaceId"],
            "workspace-created-1",
        )
        self.assertEqual(opened["context"]["contextId"], "context-created-1")
        self.assertEqual(opened["context"]["materializedState"]["status"], "open")
        self.assertEqual([agent["agentId"] for agent in opened["agents"]], ["agent-created-1"])
        self.assertEqual(opened["agents"][0]["defaultModel"], "deterministic-placeholder")
        self.assertEqual(opened["agents"][0]["toolPermissions"], ["workspace.read"])
        self.assertEqual(
            tuple(row[1] for row in events),
            ("workspace.changed", "agent_registration.changed"),
        )
        self.assertEqual(events[0][2], "workspace-created-1")
        self.assertEqual(events[1][2], "agent-created-1")

    def test_create_workspace_rejects_duplicate_workspace_and_invalid_root(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        service.create_workspace(
            workspace_id="workspace-duplicate-1",
            display_name="Duplicate Workspace",
            root_path="X:/fixture/workspace-duplicate-1",
        )

        with self.assertRaisesRegex(ValueError, "already exists"):
            service.create_workspace(
                workspace_id="workspace-duplicate-1",
                display_name="Duplicate Workspace",
                root_path="X:/fixture/workspace-duplicate-1",
            )
        with self.assertRaisesRegex(ValueError, "root_path"):
            service.create_workspace(
                workspace_id="workspace-invalid-root-1",
                display_name="Invalid Root Workspace",
                root_path=" ",
            )

    def test_open_workspace_rejects_missing_and_archived_workspace(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        service.create_workspace(
            workspace_id="workspace-open-1",
            display_name="Open Workspace",
            root_path="X:/fixture/workspace-open-1",
        )

        with self.assertRaisesRegex(ValueError, "workspace state not found"):
            service.open_workspace("workspace-missing")

        service.archive_workspace("workspace-open-1")

        with self.assertRaisesRegex(ValueError, "archived"):
            service.open_workspace("workspace-open-1")

    def test_archive_workspace_marks_state_and_is_idempotent(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        service.create_workspace(
            workspace_id="workspace-archive-1",
            display_name="Archive Workspace",
            root_path="X:/fixture/workspace-archive-1",
            created_at=datetime(2026, 6, 5, 8, 0, tzinfo=timezone.utc),
            workspace_event_id="event-workspace-archive-create-1",
            agent_event_id="event-workspace-archive-agent-1",
        )

        archived = service.archive_workspace(
            "workspace-archive-1",
            archived_at=datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc),
            event_id="event-workspace-archive-1",
        )
        archived_again = service.archive_workspace("workspace-archive-1")
        listed = service.list_workspaces()
        events = connection.execute(
            "SELECT event_kind, aggregate_id FROM platform_events ORDER BY sequence"
        ).fetchall()

        self.assertTrue(archived["archived"])
        self.assertFalse(archived_again["archived"])
        self.assertEqual(archived["workspace"]["workspace"]["status"], "archived")
        self.assertEqual(
            listed["workspaces"][0]["status"],
            "archived",
        )
        self.assertEqual(
            tuple(row[0] for row in events),
            (
                "workspace.changed",
                "agent_registration.changed",
                "workspace.changed",
            ),
        )

    def test_ensure_workspace_baseline_is_explicit_and_idempotent(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        workspace_store = SqliteWorkspaceStateStore(connection)
        workspace_store.upsert_workspace_state(
            workspace=ProjectWorkspace.create(
                workspace_id=WorkspaceId("workspace-baseline-1"),
                display_name="Baseline Workspace",
                root_path="X:/fixture/workspace-baseline-1",
            ),
            source_event_sequence=0,
        )
        service = _service(connection)

        first = service.ensure_workspace_baseline(
            "workspace-baseline-1",
            context_id="context-baseline-1",
            agent_id="agent-baseline-1",
            agent_name="Baseline Agent",
            agent_description="Handles baseline requests",
            agent_capability_name="single-turn-status",
            agent_capability_description="Captures baseline requests",
            agent_event_id="event-agent-baseline-1",
        )
        second = service.ensure_workspace_baseline(
            "workspace-baseline-1",
            context_id="context-baseline-1",
            agent_id="agent-baseline-1",
        )
        context = service.get_context("workspace-baseline-1")["context"]
        agents = service.list_agent_registrations("workspace-baseline-1")["agents"]
        events = connection.execute(
            "SELECT event_kind, aggregate_id FROM platform_events ORDER BY sequence"
        ).fetchall()

        self.assertTrue(first["baseline"]["contextCreated"])
        self.assertTrue(first["baseline"]["agentCreated"])
        self.assertFalse(second["baseline"]["contextCreated"])
        self.assertFalse(second["baseline"]["agentCreated"])
        self.assertEqual(context["contextId"], "context-baseline-1")
        self.assertEqual([agent["agentId"] for agent in agents], ["agent-baseline-1"])
        self.assertEqual(events, [("agent_registration.changed", "agent-baseline-1")])

    def test_create_agent_registration_adds_workspace_scoped_runtime_profile(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        service.create_workspace(
            workspace_id="workspace-profile-1",
            display_name="Profile Workspace",
            root_path="X:/fixture/workspace-profile-1",
        )

        reviewer = service.create_agent_registration(
            "workspace-profile-1",
            agent_id="agent-reviewer-1",
            name="Reviewer",
            description="Reviews candidate responses.",
            capabilities=(
                {
                    "name": "review",
                    "description": "Reviews responses.",
                    "metadata": {"kind": "quality"},
                },
            ),
            default_model="fake-chat-model",
            runtime_config={
                "profile": {
                    "profileName": "reviewer-profile",
                    "roleName": "reviewer",
                    "systemPrompt": "Review the candidate answer.",
                    "providerName": "openai-compatible",
                    "modelName": "fake-chat-model",
                    "generationOptions": {"temperature": 0, "maxTokens": 32},
                    "runtimeKind": "provider_connection",
                    "bindingId": "binding-reviewer",
                    "connectionId": "connection-shared",
                },
            },
        )
        planner = service.create_agent_registration(
            "workspace-profile-1",
            agent_id="agent-planner-1",
            name="Planner",
            description="Plans next tasks.",
            capabilities=(
                {
                    "name": "plan",
                    "description": "Plans next tasks.",
                },
            ),
            default_model="fake-chat-model",
            runtime_config={
                "profile": {
                    "profileName": "planner-profile",
                    "roleName": "planner",
                    "systemPrompt": "Plan the next task.",
                    "providerName": "openai-compatible",
                    "modelName": "fake-chat-model",
                    "generationOptions": {"temperature": 0.5, "maxTokens": 64},
                    "runtimeKind": "provider_connection",
                    "bindingId": "binding-planner",
                    "connectionId": "connection-shared",
                },
            },
        )
        listed = service.list_agent_registrations("workspace-profile-1")["agents"]

        self.assertTrue(reviewer["created"])
        self.assertTrue(planner["created"])
        self.assertEqual(reviewer["agent"]["runtimeConfig"]["profile"]["roleName"], "reviewer")
        self.assertEqual(planner["agent"]["runtimeConfig"]["profile"]["roleName"], "planner")
        self.assertEqual(
            [agent["agentId"] for agent in listed],
            [
                "agent-planner-1",
                "agent-reviewer-1",
                "agent-workspace-profile-1",
            ],
        )
        with self.assertRaisesRegex(ValueError, "already exists"):
            service.create_agent_registration(
                "workspace-profile-1",
                agent_id="agent-reviewer-1",
                name="Duplicate",
                description="Duplicate profile.",
            )

    def test_create_agent_registration_rejects_archived_workspace_and_secret_values(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        service.create_workspace(
            workspace_id="workspace-profile-guard-1",
            display_name="Profile Guard Workspace",
            root_path="X:/fixture/workspace-profile-guard-1",
        )

        with self.assertRaisesRegex(ValueError, "credential values"):
            service.create_agent_registration(
                "workspace-profile-guard-1",
                agent_id="agent-secret-1",
                name="Secret Agent",
                description="Should be rejected.",
                runtime_config={
                    "profile": {
                        "providerName": "openai-compatible",
                        "modelName": "fake-chat-model",
                        "apiKey": "must-not-be-stored",
                    },
                },
            )

        service.archive_workspace("workspace-profile-guard-1")
        with self.assertRaisesRegex(ValueError, "archived"):
            service.create_agent_registration(
                "workspace-profile-guard-1",
                agent_id="agent-after-archive-1",
                name="After Archive",
                description="Should be rejected.",
            )

    def test_runtime_permission_read_model_is_read_only_and_metadata_only(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        service.create_workspace(
            workspace_id="workspace-runtime-permission-1",
            agent_id="agent-default-runtime-1",
            display_name="Runtime Permission Workspace",
            root_path="X:/fixture/workspace-runtime-permission-1",
        )
        service.create_agent_registration(
            "workspace-runtime-permission-1",
            agent_id="agent-native-runtime-1",
            name="Native Runtime",
            description="Declares future native runtime access.",
            runtime_config={
                "profile": {
                    "profileName": "native-runtime",
                    "roleName": "native",
                    "runtimeKind": "agent-native-runtime",
                    "runtimeAccess": {
                        "delegatedContextDelivery": (
                            "bounded_materialized_segments"
                        ),
                        "toolPermissions": ["declared_tools_only"],
                        "allowedToolNames": ["context_reader"],
                        "allowedSkillRefs": ["skill://review"],
                        "filePermission": "file_ref_metadata_only",
                        "memoryPolicy": "runtime_local_ephemeral",
                        "memoryNamespace": "native-runtime",
                        "memoryQuotaMb": 8,
                        "networkPolicy": "disabled",
                    },
                },
            },
        )

        listed = service.list_agent_runtime_permissions(
            "workspace-runtime-permission-1"
        )
        native = service.get_agent_runtime_permissions(
            "workspace-runtime-permission-1",
            "agent-native-runtime-1",
        )["runtimePermission"]
        events = connection.execute(
            "SELECT event_kind FROM platform_events ORDER BY sequence"
        ).fetchall()
        invocations = connection.execute(
            "SELECT COUNT(*) FROM platform_agent_invocation_records"
        ).fetchone()[0]

        self.assertEqual(len(listed["runtimePermissions"]), 2)
        self.assertEqual(native["runtimeKind"], "agent_native_runtime")
        self.assertTrue(native["readModelOnly"])
        self.assertFalse(native["runtimeConnected"])
        self.assertEqual(
            native["configuredProfile"]["delegated_context_delivery"],
            "bounded_materialized_segments",
        )
        self.assertEqual(
            native["configuredProfile"]["allowed_tool_names"],
            ["context_reader"],
        )
        self.assertEqual(native["configuredProfile"]["memory_quota_mb"], 8)
        self.assertFalse(
            native["capabilities"]["flags"]["real_runtime_connection_allowed"]
        )
        self.assertFalse(
            native["capabilities"]["flags"]["credential_store_allowed"]
        )
        self.assertFalse(
            native["capabilities"]["flags"]["websocket_transport_allowed"]
        )
        self.assertFalse(
            native["capabilities"]["flags"]["file_body_read_allowed"]
        )
        self.assertFalse(
            native["deliveryPlan"]["materialized_text_included"]
        )
        self.assertFalse(native["deliveryPlan"]["file_bodies_included"])
        self.assertFalse(native["deliveryPlan"]["real_runtime_connected"])
        self.assertFalse(native["boundary"]["invocation_created"])
        self.assertFalse(native["boundary"]["model_provider_invoked"])
        self.assertFalse(native["boundary"]["provider_prompt_injected"])
        self.assertEqual(invocations, 0)
        self.assertEqual(
            tuple(row[0] for row in events),
            (
                "workspace.changed",
                "agent_registration.changed",
                "agent_registration.changed",
            ),
        )
        with self.assertRaisesRegex(ValueError, "agent registration state not found"):
            service.get_agent_runtime_permissions(
                "workspace-runtime-permission-1",
                "agent-missing",
            )

    def test_agent_exchange_instructions_are_metadata_only(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        service.create_workspace(
            workspace_id="workspace-agent-exchange-1",
            display_name="Agent Exchange Workspace",
            root_path="X:/fixture/workspace-agent-exchange-1",
            agent_id="agent-agent-exchange-1",
        )

        result = service.agent_exchange_instructions("workspace-agent-exchange-1")
        interface = result["agentExchangeInterface"]

        self.assertEqual(interface["schema"], "agent_exchange_interface.v1")
        self.assertEqual(interface["workspaceId"], "workspace-agent-exchange-1")
        self.assertFalse(interface["realRuntimeConnected"])
        self.assertFalse(interface["backgroundLoopEnabled"])
        self.assertFalse(interface["agentAutoWakeEnabled"])
        self.assertIn("agent_context_update", interface["sourceTypes"])
        with self.assertRaisesRegex(ValueError, "workspace state not found"):
            service.agent_exchange_instructions("workspace-missing")

    def test_conversation_operations_create_append_list_and_archive(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        service.create_workspace(
            workspace_id="workspace-conversation-1",
            display_name="Conversation Workspace",
            root_path="X:/fixture/workspace-conversation-1",
            agent_id="agent-conversation-1",
        )

        created = service.create_conversation(
            "workspace-conversation-1",
            conversation_id="conversation-1",
            agent_id="agent-conversation-1",
            title="Reviewer thread",
            created_at=datetime(2026, 6, 12, 8, 0, tzinfo=timezone.utc),
            event_id="event-conversation-created-1",
            metadata={"profile_name": "reviewer"},
        )
        user_message = service.append_conversation_message(
            "workspace-conversation-1",
            "conversation-1",
            message_id="message-user-1",
            role="user",
            content="Please review this.",
            run_session_id="session-conversation-1",
            created_at=datetime(2026, 6, 12, 8, 1, tzinfo=timezone.utc),
            event_id="event-message-user-1",
        )
        assistant_message = service.append_conversation_message(
            "workspace-conversation-1",
            "conversation-1",
            message_id="message-assistant-1",
            role="assistant",
            content="Review complete.",
            agent_id="agent-conversation-1",
            invocation_id="invoke-conversation-1",
            context_update_id="update-conversation-1",
            run_session_id="session-conversation-1",
            created_at=datetime(2026, 6, 12, 8, 2, tzinfo=timezone.utc),
            event_id="event-message-assistant-1",
        )
        listed = service.list_conversations("workspace-conversation-1")
        messages = service.list_conversation_messages(
            "workspace-conversation-1",
            "conversation-1",
        )
        archived = service.archive_conversation(
            "workspace-conversation-1",
            "conversation-1",
            archived_at=datetime(2026, 6, 12, 8, 3, tzinfo=timezone.utc),
            event_id="event-conversation-archived-1",
        )

        self.assertTrue(created["created"])
        self.assertEqual(created["conversation"]["agentId"], "agent-conversation-1")
        self.assertEqual(created["conversation"]["metadata"]["profile_name"], "reviewer")
        self.assertEqual(user_message["message"]["sequence"], 1)
        self.assertEqual(assistant_message["message"]["sequence"], 2)
        self.assertEqual(assistant_message["message"]["invocationId"], "invoke-conversation-1")
        self.assertEqual(
            [item["conversationId"] for item in listed["conversations"]],
            ["conversation-1"],
        )
        self.assertEqual(
            [item["messageId"] for item in messages["messages"]],
            ["message-user-1", "message-assistant-1"],
        )
        self.assertTrue(archived["archived"])
        with self.assertRaisesRegex(ValueError, "conversation is archived"):
            service.append_conversation_message(
                "workspace-conversation-1",
                "conversation-1",
                role="user",
                content="Should fail.",
            )

    def test_conversation_message_can_carry_agent_exchange_attribution(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        service.create_workspace(
            workspace_id="workspace-conversation-exchange-1",
            display_name="Conversation Exchange Workspace",
            root_path="X:/fixture/workspace-conversation-exchange-1",
            agent_id="agent-conversation-exchange-1",
        )
        service.create_conversation(
            "workspace-conversation-exchange-1",
            conversation_id="conversation-exchange-1",
            agent_id="agent-conversation-exchange-1",
            title="Exchange thread",
        )

        appended = service.append_conversation_message(
            "workspace-conversation-exchange-1",
            "conversation-exchange-1",
            message_id="message-exchange-1",
            role="assistant",
            content="I found a possible implementation path.",
            agent_id="agent-conversation-exchange-1",
            exchange_attribution={
                "sourceType": "agent_message",
                "authorType": "agent",
                "contributionKind": "proposal",
                "authorAgentId": "agent-conversation-exchange-1",
                "sourceConfidence": "medium",
                "linkedConversationId": "conversation-exchange-1",
            },
        )
        messages = service.list_conversation_messages(
            "workspace-conversation-exchange-1",
            "conversation-exchange-1",
        )

        exchange = appended["message"]["metadata"]["agentExchange"]
        self.assertEqual(exchange["sourceType"], "agent_message")
        self.assertEqual(exchange["instructionAuthority"], "agent_suggestion")
        self.assertFalse(exchange["agentOutputMayIssueUserDirective"])
        self.assertEqual(
            messages["messages"][0]["metadata"]["agentExchange"]["authorAgentId"],
            "agent-conversation-exchange-1",
        )

    def test_conversation_operations_validate_workspace_and_agent_boundaries(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        service.create_workspace(
            workspace_id="workspace-conversation-a",
            display_name="Conversation Workspace A",
            root_path="X:/fixture/workspace-conversation-a",
            agent_id="agent-conversation-a",
        )
        service.create_workspace(
            workspace_id="workspace-conversation-b",
            display_name="Conversation Workspace B",
            root_path="X:/fixture/workspace-conversation-b",
            agent_id="agent-conversation-b",
        )
        service.create_conversation(
            "workspace-conversation-a",
            conversation_id="conversation-a",
            agent_id="agent-conversation-a",
            title="Thread A",
        )

        with self.assertRaisesRegex(ValueError, "agent registration workspace_id"):
            service.create_conversation(
                "workspace-conversation-a",
                conversation_id="conversation-cross-agent",
                agent_id="agent-conversation-b",
                title="Invalid",
            )
        with self.assertRaisesRegex(ValueError, "conversation workspace_id"):
            service.get_conversation(
                "workspace-conversation-b",
                "conversation-a",
            )
        service.archive_workspace("workspace-conversation-a")
        with self.assertRaisesRegex(ValueError, "workspace is archived"):
            service.create_conversation(
                "workspace-conversation-a",
                conversation_id="conversation-after-archive",
                title="After archive",
            )

    def test_service_lists_and_gets_current_state_payloads(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _seed_current_state(connection)
        service = _service(connection)

        workspaces = service.list_workspaces()
        workspace = service.get_workspace("workspace-1")
        context = service.get_context("workspace-1")
        agents = service.list_agent_registrations("workspace-1")
        agent = service.get_agent_registration("agent-1")
        tasks = service.list_tasks("workspace-1")
        task = service.get_task("task-1")
        issues = service.list_issues("workspace-1")
        issue = service.get_issue("issue-1")

        self.assertEqual(
            [item["workspaceId"] for item in workspaces["workspaces"]],
            ["workspace-1", "workspace-2"],
        )
        self.assertEqual(workspace["workspace"]["displayName"], "Workspace 1")
        self.assertEqual(context["context"]["contextId"], "context-1")
        self.assertEqual(context["context"]["materializedState"]["status"], "open")
        self.assertEqual([item["agentId"] for item in agents["agents"]], ["agent-1"])
        self.assertEqual(agent["agent"]["capabilities"][0]["name"], "single-turn")
        self.assertEqual([item["taskId"] for item in tasks["tasks"]], ["task-1"])
        self.assertEqual(task["task"]["assigneeAgentId"], "agent-1")
        self.assertEqual([item["issueId"] for item in issues["issues"]], ["issue-1"])
        self.assertEqual(issue["issue"]["severity"], "high")

    def test_service_returns_none_or_empty_collections_for_missing_state(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _seed_current_state(connection)
        service = _service(connection)

        self.assertEqual(service.get_workspace("missing")["workspace"], None)
        self.assertEqual(service.get_context("missing")["context"], None)
        self.assertEqual(service.get_agent_registration("missing")["agent"], None)
        self.assertEqual(service.get_task("missing")["task"], None)
        self.assertEqual(service.get_issue("missing")["issue"], None)
        self.assertEqual(service.list_agent_registrations("missing")["agents"], [])
        self.assertEqual(service.list_tasks("missing")["tasks"], [])
        self.assertEqual(service.list_issues("missing")["issues"], [])

    def test_service_rejects_empty_identifiers_through_readers(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)

        with self.assertRaises(ValueError):
            service.get_workspace(" ")
        with self.assertRaises(ValueError):
            service.list_agent_registrations(" ")
        with self.assertRaises(ValueError):
            service.get_task(" ")

    def test_append_context_update_records_event_and_updates_materialized_state(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _seed_current_state(connection)
        service = _service(connection)

        first = service.append_context_update(
            "workspace-1",
            update_kind=ContextUpdateKind.NOTE,
            summary="Captured note",
            update_id="update-note-1",
            payload={"note": "captured"},
            materialized_state_patch={"latest_note": "captured"},
            event_id="event-note-1",
            event_metadata={"source": "unit-test"},
        )
        second = service.append_context_update(
            "workspace-1",
            update_kind="decision",
            summary="Captured decision",
            update_id="update-decision-1",
            materialized_state_patch={"decision": "accepted"},
            event_id="event-decision-1",
        )
        stored_context = SqliteContextStateStore(connection).get_context_state(
            WorkspaceId("workspace-1")
        )

        self.assertEqual(first["sourceEventSequence"], 1)
        self.assertEqual(first["contextUpdate"]["updateKind"], "note")
        self.assertEqual(first["context"]["updateCount"], 1)
        self.assertEqual(first["context"]["materializedState"]["latest_note"], "captured")
        self.assertEqual(second["sourceEventSequence"], 2)
        self.assertEqual(second["contextUpdate"]["updateId"], "update-decision-1")
        self.assertEqual(second["context"]["updateCount"], 2)
        self.assertEqual(second["context"]["materializedState"]["decision"], "accepted")
        assert stored_context is not None
        self.assertEqual(stored_context.source_event_sequence, 2)
        self.assertEqual(stored_context.update_count, 2)
        self.assertEqual(stored_context.context.materialized_state["latest_note"], "captured")
        self.assertEqual(stored_context.context.materialized_state["decision"], "accepted")

    def test_list_and_get_context_updates_return_update_bodies(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _seed_current_state(connection)
        service = _service(connection)

        service.append_context_update(
            "workspace-1",
            update_kind="note",
            summary="First shared result",
            update_id="update-first-1",
            payload={"body": "first"},
            materialized_state_patch={"first": True},
        )
        service.append_context_update(
            "workspace-1",
            update_kind="agent_message",
            summary="Second shared result",
            update_id="update-second-1",
            payload={"body": "second"},
        )

        listed = service.list_context_updates("workspace-1")
        filtered = service.list_context_updates(
            "workspace-1",
            update_kind="note",
        )
        fetched = service.get_context_update(
            "workspace-1",
            update_id="update-first-1",
        )

        self.assertEqual(listed["order"], "newest_first")
        self.assertEqual(listed["count"], 2)
        self.assertEqual(listed["totalCount"], 2)
        self.assertEqual(listed["contextUpdates"][0]["updateId"], "update-second-1")
        self.assertEqual(listed["contextUpdates"][0]["payload"]["body"], "second")
        self.assertEqual(filtered["count"], 1)
        self.assertEqual(filtered["contextUpdates"][0]["updateId"], "update-first-1")
        self.assertEqual(fetched["contextUpdate"]["appendIndex"], 0)
        self.assertEqual(fetched["contextUpdate"]["payload"]["body"], "first")
        self.assertEqual(
            fetched["contextUpdate"]["materializedStatePatch"]["first"],
            True,
        )

    def test_list_context_updates_validates_paging(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _seed_current_state(connection)
        service = _service(connection)

        with self.assertRaisesRegex(ValueError, "limit"):
            service.list_context_updates("workspace-1", limit=-1)
        with self.assertRaisesRegex(ValueError, "offset"):
            service.list_context_updates("workspace-1", offset=-1)

    def test_context_update_can_carry_agent_exchange_attribution(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _seed_current_state(connection)
        service = _service(connection)

        result = service.append_context_update(
            "workspace-1",
            update_kind="agent_message",
            summary="Reviewer agent proposes a bounded exchange contract.",
            update_id="update-agent-exchange-1",
            source_agent_id="agent-1",
            exchange_attribution={
                "sourceType": "agent_context_update",
                "authorType": "agent",
                "contributionKind": "proposal",
                "authorAgentId": "agent-1",
                "sourceConfidence": "medium",
            },
        )

        exchange = result["contextUpdate"]["metadata"]["agentExchange"]
        self.assertEqual(exchange["schema"], "agent_exchange_attribution.v1")
        self.assertEqual(exchange["sourceType"], "agent_context_update")
        self.assertEqual(exchange["authorType"], "agent")
        self.assertEqual(exchange["contributionKind"], "proposal")
        self.assertEqual(exchange["instructionAuthority"], "agent_suggestion")
        self.assertFalse(exchange["autoPromoteToDecision"])
        self.assertFalse(exchange["providerPromptInjected"])

    def test_agent_exchange_metadata_rejects_agent_as_user_directive(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _seed_current_state(connection)
        service = _service(connection)

        with self.assertRaisesRegex(ValueError, "must not be user directives"):
            service.append_context_update(
                "workspace-1",
                update_kind="agent_message",
                summary="Unsafe directive claim.",
                exchange_attribution={
                    "sourceType": "agent_context_update",
                    "authorType": "agent",
                    "contributionKind": "proposal",
                    "instructionAuthority": "user_directive",
                },
            )

    def test_manual_wake_activation_allows_and_revocation_blocks_exchange_write(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _seed_current_state(connection)
        service = _service(connection)

        instructions = service.agent_activation_instructions("workspace-1")
        wake = service.wake_agent_activation(
            "workspace-1",
            agent_id="agent-1",
            activation_id="activation-service-1",
            created_by="user",
            reason="Allow one bounded reviewer handoff.",
            budget={
                "ttlSeconds": 3600,
                "maxWrites": 1,
                "maxAgentToAgentTurns": 0,
            },
        )
        accepted = service.append_context_update(
            "workspace-1",
            update_kind="agent_message",
            summary="Reviewer proposes a bounded follow-up.",
            source_agent_id="agent-1",
            exchange_attribution={
                "sourceType": "agent_context_update",
                "authorType": "agent",
                "contributionKind": "proposal",
                "authorAgentId": "agent-1",
                "linkedActivationId": "activation-service-1",
            },
        )
        self.assertEqual(
            instructions["agentActivationInterface"]["schema"],
            "agent_activation_interface.v1",
        )
        self.assertEqual(wake["agentActivation"]["state"], "awakened")
        self.assertFalse(wake["agentActivation"]["realRuntimeConnected"])
        self.assertEqual(
            accepted["contextUpdate"]["metadata"]["agentExchange"]["linkedActivationId"],
            "activation-service-1",
        )
        with self.assertRaisesRegex(ValueError, "budget_exhausted"):
            service.append_context_update(
                "workspace-1",
                update_kind="agent_message",
                summary="This write should exhaust the activation budget.",
                source_agent_id="agent-1",
                exchange_attribution={
                    "sourceType": "agent_context_update",
                    "authorType": "agent",
                    "contributionKind": "proposal",
                    "authorAgentId": "agent-1",
                    "linkedActivationId": "activation-service-1",
                },
            )
        revoked = service.revoke_agent_activation(
            "workspace-1",
            agent_id="agent-1",
            activation_id="activation-service-1",
            revoked_by="user",
            reason="End reviewer access.",
        )
        self.assertEqual(revoked["agentActivation"]["state"], "revoked")
        with self.assertRaisesRegex(ValueError, "agent activation is not active"):
            service.append_context_update(
                "workspace-1",
                update_kind="agent_message",
                summary="This write should be blocked.",
                source_agent_id="agent-1",
                exchange_attribution={
                    "sourceType": "agent_context_update",
                    "authorType": "agent",
                    "contributionKind": "proposal",
                    "authorAgentId": "agent-1",
                    "linkedActivationId": "activation-service-1",
                },
            )

    def test_manual_wake_activation_rejects_agent_identity_mismatch(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        service.create_workspace(
            workspace_id="workspace-activation-mismatch-1",
            display_name="Activation Mismatch",
            root_path="X:/fixture/workspace-activation-mismatch-1",
            agent_id="agent-activation-a",
        )
        service.create_agent_registration(
            "workspace-activation-mismatch-1",
            agent_id="agent-activation-b",
            name="Second Agent",
            description="Different author",
        )
        service.wake_agent_activation(
            "workspace-activation-mismatch-1",
            agent_id="agent-activation-a",
            activation_id="activation-mismatch-1",
            created_by="user",
            reason="Wake first agent.",
        )

        with self.assertRaisesRegex(ValueError, "does not match authorAgentId"):
            service.append_context_update(
                "workspace-activation-mismatch-1",
                update_kind="agent_message",
                summary="Wrong agent tries to use the activation.",
                source_agent_id="agent-activation-b",
                exchange_attribution={
                    "sourceType": "agent_context_update",
                    "authorType": "agent",
                    "contributionKind": "proposal",
                    "authorAgentId": "agent-activation-b",
                    "linkedActivationId": "activation-mismatch-1",
                },
            )

    def test_append_context_update_rejects_missing_context(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _seed_current_state(connection)
        service = _service(connection)

        with self.assertRaisesRegex(ValueError, "context state not found"):
            service.append_context_update(
                "workspace-missing",
                update_kind=ContextUpdateKind.NOTE,
                summary="Missing context note",
            )

    def test_append_context_update_rejects_context_workspace_mismatch(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _seed_current_state(connection)
        service = LocalPlatformOperationService(
            workspace_reader=SqliteWorkspaceStateStore(connection),
            context_reader=_MismatchedContextReader(),
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

        with self.assertRaisesRegex(ValueError, "workspace_id"):
            service.append_context_update(
                "workspace-1",
                update_kind=ContextUpdateKind.NOTE,
                summary="Mismatched context note",
            )

    def test_get_run_session_timeline_returns_session_events_in_sequence_order(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _seed_current_state(connection)
        event_log = SqlitePlatformEventLog(connection)
        service = _service(connection)

        _append_event(
            event_log,
            event_id="event-session-running-1",
            session_id="session-1",
            event_kind=PlatformEventKind.RUN_SESSION_CHANGED,
            aggregate_type="run_session",
            aggregate_id="session-1",
            occurred_at=datetime(2026, 6, 5, 2, 0, tzinfo=timezone.utc),
            payload={"status": "running"},
        )
        _append_event(
            event_log,
            event_id="event-session-other-1",
            session_id="session-other",
            event_kind=PlatformEventKind.AGENT_INVOCATION_RECORDED,
            aggregate_type="agent_invocation",
            aggregate_id="invoke-other",
            occurred_at=datetime(2026, 6, 5, 2, 1, tzinfo=timezone.utc),
        )
        _append_event(
            event_log,
            event_id="event-session-context-1",
            session_id="session-1",
            event_kind=PlatformEventKind.CONTEXT_UPDATE_APPENDED,
            aggregate_type="context_update",
            aggregate_id="update-1",
            occurred_at=datetime(2026, 6, 5, 2, 2, tzinfo=timezone.utc),
            payload={"update_id": "update-1"},
        )
        _append_event(
            event_log,
            event_id="event-session-completed-1",
            session_id="session-1",
            event_kind=PlatformEventKind.RUN_SESSION_CHANGED,
            aggregate_type="run_session",
            aggregate_id="session-1",
            occurred_at=datetime(2026, 6, 5, 2, 3, tzinfo=timezone.utc),
            payload={"status": "completed"},
        )

        timeline = service.get_run_session_timeline("workspace-1", "session-1")

        self.assertEqual(timeline["session"]["workspaceId"], "workspace-1")
        self.assertEqual(timeline["session"]["sessionId"], "session-1")
        self.assertEqual(timeline["session"]["status"], "completed")
        self.assertEqual(timeline["session"]["eventCount"], 3)
        self.assertEqual(timeline["session"]["firstSequence"], 1)
        self.assertEqual(timeline["session"]["lastSequence"], 4)
        self.assertTrue(
            timeline["session"]["lifecycle"]["hasExplicitLifecycleEvents"]
        )
        self.assertEqual(
            timeline["session"]["lifecycle"]["statusSource"],
            "run_session_event",
        )
        self.assertEqual(
            timeline["session"]["lifecycle"]["recoveryState"],
            "closed",
        )
        self.assertEqual(timeline["session"]["lifecycle"]["startedSequence"], 1)
        self.assertEqual(timeline["session"]["lifecycle"]["terminalSequence"], 4)
        self.assertEqual(timeline["session"]["lifecycle"]["contextUpdateEventCount"], 1)
        self.assertEqual(
            [event["sequence"] for event in timeline["events"]],
            [1, 3, 4],
        )
        self.assertEqual(
            [event["eventKind"] for event in timeline["events"]],
            [
                "run_session.changed",
                "context.update_appended",
                "run_session.changed",
            ],
        )
        self.assertEqual(timeline["events"][0]["payload"]["status"], "running")
        self.assertEqual(timeline["events"][1]["payload"]["update_id"], "update-1")

    def test_get_run_session_timeline_returns_empty_unknown_session(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)

        timeline = service.get_run_session_timeline(
            "workspace-1",
            "session-missing",
        )

        self.assertEqual(timeline["session"]["workspaceId"], "workspace-1")
        self.assertEqual(timeline["session"]["sessionId"], "session-missing")
        self.assertEqual(timeline["session"]["status"], "unknown")
        self.assertEqual(timeline["session"]["eventCount"], 0)
        self.assertEqual(timeline["session"]["firstSequence"], None)
        self.assertEqual(timeline["session"]["lastSequence"], None)
        self.assertEqual(
            timeline["session"]["lifecycle"]["recoveryState"],
            "missing",
        )
        self.assertFalse(
            timeline["session"]["lifecycle"]["hasExplicitLifecycleEvents"]
        )
        self.assertEqual(timeline["events"], [])

    def test_get_run_session_timeline_rejects_empty_session_id(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)

        with self.assertRaises(ValueError):
            service.get_run_session_timeline("workspace-1", " ")

    def test_service_queries_agent_invocation_records(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _seed_current_state(connection)
        store = SqliteAgentInvocationRecordStore(connection)
        service = _service(connection)
        first_request = _invocation_request(
            invocation_id="invoke-1",
            idempotency_key="idem-1",
            requested_at=datetime(2026, 6, 5, 3, 0, tzinfo=timezone.utc),
        )
        second_request = _invocation_request(
            invocation_id="invoke-2",
            idempotency_key="idem-2",
            requested_at=datetime(2026, 6, 5, 3, 10, tzinfo=timezone.utc),
        )
        first_result = AgentInvocationResult.succeed(
            first_request,
            summary="Invocation completed",
            completed_at=datetime(2026, 6, 5, 3, 5, tzinfo=timezone.utc),
            output_text="Done",
            output_payload={"kind": "summary"},
            context_update_ids=(ContextUpdateId("update-result-1"),),
        )

        store.upsert_agent_invocation_record(
            request=first_request,
            source_event_sequence=11,
        )
        store.upsert_agent_invocation_record(
            request=first_request,
            source_event_sequence=12,
            result=first_result,
        )
        store.upsert_agent_invocation_record(
            request=second_request,
            source_event_sequence=13,
        )

        all_invocations = service.list_agent_invocation_records("workspace-1")
        requested = service.list_agent_invocation_records(
            "workspace-1",
            status="requested",
        )
        by_id = service.get_agent_invocation_record("invoke-1")
        by_idempotency = service.get_agent_invocation_record_by_idempotency_key(
            "workspace-1",
            "idem-1",
        )

        self.assertEqual(
            [item["invocationId"] for item in all_invocations["invocations"]],
            ["invoke-1", "invoke-2"],
        )
        self.assertEqual(
            [item["status"] for item in all_invocations["invocations"]],
            ["succeeded", "requested"],
        )
        self.assertEqual(
            [item["invocationId"] for item in requested["invocations"]],
            ["invoke-2"],
        )
        self.assertEqual(by_id["invocation"]["status"], "succeeded")
        self.assertEqual(by_id["invocation"]["sourceEventSequence"], 12)
        self.assertEqual(by_id["invocation"]["taskId"], "task-1")
        self.assertEqual(
            by_id["invocation"]["contextUpdateIds"],
            ["update-request-1", "update-result-1"],
        )
        self.assertEqual(
            by_idempotency["invocation"]["invocationId"],
            "invoke-1",
        )

    def test_service_returns_none_or_empty_invocation_queries(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)

        self.assertEqual(
            service.get_agent_invocation_record("missing")["invocation"],
            None,
        )
        self.assertEqual(
            service.get_agent_invocation_record_by_idempotency_key(
                "workspace-1",
                "missing-idem",
            )["invocation"],
            None,
        )
        self.assertEqual(
            service.list_agent_invocation_records("workspace-1")["invocations"],
            [],
        )

    def test_service_queries_file_operation_records_without_file_content(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _seed_current_state(connection)
        invocation_store = SqliteAgentInvocationRecordStore(connection)
        file_store = SqliteFileOperationRecordStore(connection)
        service = _service(connection)
        invocation_request = _invocation_request(
            invocation_id="invoke-file-1",
            idempotency_key="idem-file-1",
            requested_at=datetime(2026, 6, 5, 4, 0, tzinfo=timezone.utc),
        )
        file_request = _file_operation_request(
            operation_id="file-op-read-1",
            operation_kind=FileOperationKind.READ_FILE,
            relative_path="docs/status.md",
            invocation_id="invoke-file-1",
            requested_at=datetime(2026, 6, 5, 4, 1, tzinfo=timezone.utc),
        )
        unsafe_result = FileOperationResult.succeed(
            file_request,
            completed_at=datetime(2026, 6, 5, 4, 2, tzinfo=timezone.utc),
            context_update_id=ContextUpdateId("update-file-read-1"),
            bytes_read=6,
            output_payload={"content": "secret", "encoding": "utf-8"},
            metadata={"source": "unsafe-fixture"},
        )
        denied_request = _file_operation_request(
            operation_id="file-op-denied-1",
            operation_kind=FileOperationKind.READ_FILE,
            relative_path="docs/denied.md",
            invocation_id="invoke-file-1",
            requested_at=datetime(2026, 6, 5, 4, 3, tzinfo=timezone.utc),
        )
        denied_result = FileOperationResult(
            operation_id=denied_request.operation_id,
            workspace_id=denied_request.workspace_id,
            operation_kind=denied_request.operation_kind,
            relative_path=denied_request.relative_path,
            status=FileOperationResultStatus.DENIED,
            completed_at=datetime(2026, 6, 5, 4, 4, tzinfo=timezone.utc),
            requested_by_agent_id=denied_request.requested_by_agent_id,
            invocation_id=denied_request.invocation_id,
            task_id=denied_request.task_id,
            error_message="Denied by policy.",
        )

        invocation_store.upsert_agent_invocation_record(
            request=invocation_request,
            source_event_sequence=20,
        )
        file_store.upsert_file_operation_record(
            request=file_request,
            source_event_sequence=21,
            result=unsafe_result,
        )
        file_store.upsert_file_operation_record(
            request=denied_request,
            source_event_sequence=22,
            result=denied_result,
        )

        all_records = service.list_file_operation_records("workspace-1")
        denied_records = service.list_file_operation_records(
            "workspace-1",
            status="denied",
        )
        by_id = service.get_file_operation_record("file-op-read-1")

        self.assertEqual(
            [item["operationId"] for item in all_records["fileOperations"]],
            ["file-op-read-1", "file-op-denied-1"],
        )
        self.assertEqual(
            [item["operationId"] for item in denied_records["fileOperations"]],
            ["file-op-denied-1"],
        )
        self.assertEqual(by_id["fileOperation"]["status"], "succeeded")
        self.assertEqual(by_id["fileOperation"]["operationKind"], "read_file")
        self.assertEqual(by_id["fileOperation"]["invocationId"], "invoke-file-1")
        self.assertEqual(by_id["fileOperation"]["taskId"], "task-1")
        self.assertNotIn("content", by_id["fileOperation"]["outputPayload"])
        self.assertNotIn(
            "content",
            by_id["fileOperation"]["resultState"]["output_payload"],
        )
        self.assertEqual(
            by_id["fileOperation"]["outputPayload"]["encoding"],
            "utf-8",
        )

    def test_service_returns_none_or_empty_file_operation_queries(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)

        self.assertEqual(
            service.get_file_operation_record("missing")["fileOperation"],
            None,
        )
        self.assertEqual(
            service.list_file_operation_records("workspace-1")["fileOperations"],
            [],
        )


class DelegatedWakeGrantServiceTests(unittest.TestCase):
    def test_create_pending_grant_and_consume_creates_target_activation(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_delegated_wake_workspace(connection, service)

        future = (
            datetime.now(timezone.utc) + timedelta(hours=1)
        ).isoformat()
        created = service.create_delegated_wake_grant(
            "workspace-dw",
            source_agent_id="agent-src",
            target_agent_id="agent-tgt",
            created_by="user",
            reason="Allow one bounded handoff.",
            delegated_wake_grant_id="dw-1",
            expires_at=datetime.fromisoformat(future),
            target_activation_budget={"maxWrites": 1, "ttlSeconds": 120},
        )

        grant = created["delegatedWakeGrant"]
        self.assertTrue(created["created"])
        self.assertEqual(grant["state"], "pending")
        self.assertEqual(grant["maxUses"], 1)
        self.assertFalse(grant["canDelegateFurther"])
        self.assertEqual(grant["targetActivationBudget"]["maxWrites"], 1)

        consumed = service.consume_delegated_wake_grant(
            "workspace-dw",
            delegated_wake_grant_id="dw-1",
            consuming_agent_id="agent-src",
        )

        self.assertTrue(consumed["consumed"])
        self.assertEqual(consumed["delegatedWakeGrant"]["state"], "consumed")
        self.assertEqual(
            consumed["delegatedWakeGrant"]["targetActivationId"],
            consumed["targetActivation"]["activationId"],
        )
        self.assertEqual(
            consumed["targetActivation"]["metadata"]["delegatedWakeGrantId"],
            "dw-1",
        )
        self.assertEqual(
            consumed["targetActivation"]["metadata"]["sourceAgentId"],
            "agent-src",
        )
        self.assertEqual(
            consumed["targetActivation"]["metadata"]["delegatedByUser"],
            "user",
        )

    def test_create_grant_without_expires_at_uses_bounded_default(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_delegated_wake_workspace(connection, service)
        created_at = datetime(2026, 6, 18, 3, 0, tzinfo=timezone.utc)

        created = service.create_delegated_wake_grant(
            "workspace-dw",
            source_agent_id="agent-src",
            target_agent_id="agent-tgt",
            created_by="user",
            reason="Allow one bounded handoff.",
            delegated_wake_grant_id="dw-default-expiry",
            created_at=created_at,
        )

        self.assertEqual(
            created["delegatedWakeGrant"]["expiresAt"],
            (created_at + timedelta(hours=1)).isoformat(),
        )

    def test_second_consume_and_wrong_source_are_denied(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_delegated_wake_workspace(connection, service)
        future = (
            datetime.now(timezone.utc) + timedelta(hours=1)
        ).isoformat()
        service.create_delegated_wake_grant(
            "workspace-dw",
            source_agent_id="agent-src",
            target_agent_id="agent-tgt",
            created_by="user",
            reason="handoff",
            delegated_wake_grant_id="dw-1",
            expires_at=datetime.fromisoformat(future),
        )

        with self.assertRaisesRegex(ValueError, "source_agent_mismatch"):
            service.consume_delegated_wake_grant(
                "workspace-dw",
                delegated_wake_grant_id="dw-1",
                consuming_agent_id="agent-tgt",
            )

        service.consume_delegated_wake_grant(
            "workspace-dw",
            delegated_wake_grant_id="dw-1",
            consuming_agent_id="agent-src",
        )
        with self.assertRaisesRegex(ValueError, "grant_already_consumed"):
            service.consume_delegated_wake_grant(
                "workspace-dw",
                delegated_wake_grant_id="dw-1",
                consuming_agent_id="agent-src",
            )

    def test_revoked_and_expired_grants_cannot_be_consumed(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_delegated_wake_workspace(connection, service)
        past = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat()
        future = (
            datetime.now(timezone.utc) + timedelta(hours=1)
        ).isoformat()
        service.create_delegated_wake_grant(
            "workspace-dw",
            source_agent_id="agent-src",
            target_agent_id="agent-tgt",
            created_by="user",
            reason="expired",
            delegated_wake_grant_id="dw-expired",
            expires_at=datetime.fromisoformat(past),
        )
        with self.assertRaisesRegex(ValueError, "grant_expired"):
            service.consume_delegated_wake_grant(
                "workspace-dw",
                delegated_wake_grant_id="dw-expired",
                consuming_agent_id="agent-src",
            )

        service.create_delegated_wake_grant(
            "workspace-dw",
            source_agent_id="agent-src",
            target_agent_id="agent-tgt",
            created_by="user",
            reason="revoked",
            delegated_wake_grant_id="dw-revoked",
            expires_at=datetime.fromisoformat(future),
        )
        service.revoke_delegated_wake_grant(
            "workspace-dw",
            delegated_wake_grant_id="dw-revoked",
            revoked_by="user",
            reason="Cancel the handoff.",
        )
        with self.assertRaisesRegex(ValueError, "grant_revoked"):
            service.consume_delegated_wake_grant(
                "workspace-dw",
                delegated_wake_grant_id="dw-revoked",
                consuming_agent_id="agent-src",
            )

    def test_target_activation_still_bound_by_22_2_budget_and_linked_writes(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_delegated_wake_workspace(connection, service)
        future = (
            datetime.now(timezone.utc) + timedelta(hours=1)
        ).isoformat()
        service.create_delegated_wake_grant(
            "workspace-dw",
            source_agent_id="agent-src",
            target_agent_id="agent-tgt",
            created_by="user",
            reason="handoff",
            delegated_wake_grant_id="dw-1",
            expires_at=datetime.fromisoformat(future),
            target_activation_budget={"maxWrites": 1, "ttlSeconds": 120},
        )
        consumed = service.consume_delegated_wake_grant(
            "workspace-dw",
            delegated_wake_grant_id="dw-1",
            consuming_agent_id="agent-src",
        )
        target_activation_id = consumed["targetActivation"]["activationId"]

        service.append_context_update(
            "workspace-dw",
            update_kind=ContextUpdateKind.NOTE,
            summary="linked write under target activation",
            exchange_attribution={
                "sourceType": "agent_context_update",
                "authorType": "agent",
                "contributionKind": "observation",
                "authorAgentId": "agent-tgt",
                "linkedActivationId": target_activation_id,
            },
        )
        with self.assertRaisesRegex(ValueError, "budget_exhausted"):
            service.append_context_update(
                "workspace-dw",
                update_kind=ContextUpdateKind.NOTE,
                summary="second write should be blocked",
                exchange_attribution={
                    "sourceType": "agent_context_update",
                    "authorType": "agent",
                    "contributionKind": "observation",
                    "authorAgentId": "agent-tgt",
                    "linkedActivationId": target_activation_id,
                },
            )

    def test_grant_rejects_credential_metadata_and_same_agent_pair(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_delegated_wake_workspace(connection, service)

        with self.assertRaisesRegex(ValueError, "credential values"):
            service.create_delegated_wake_grant(
                "workspace-dw",
                source_agent_id="agent-src",
                target_agent_id="agent-tgt",
                created_by="user",
                reason="leak",
                metadata={"apiKey": "sk-fixture-not-a-real-token"},
            )
        with self.assertRaisesRegex(ValueError, "must not be the same agent"):
            service.create_delegated_wake_grant(
                "workspace-dw",
                source_agent_id="agent-src",
                target_agent_id="agent-src",
                created_by="user",
                reason="self",
            )

    def test_instructions_status_and_list_return_contract_state(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_delegated_wake_workspace(connection, service)

        instructions = service.delegated_wake_instructions("workspace-dw")[
            "delegatedWakeInterface"
        ]
        self.assertEqual(instructions["schema"], "delegated_wake_interface.v1")
        self.assertFalse(instructions["defaults"]["realRuntimeConnected"])

        status = service.get_delegated_wake_grant_status(
            "workspace-dw",
            delegated_wake_grant_id="missing",
        )["delegatedWakeGrant"]
        self.assertIsNone(status["delegatedWakeGrantId"])

        future = (
            datetime.now(timezone.utc) + timedelta(hours=1)
        ).isoformat()
        service.create_delegated_wake_grant(
            "workspace-dw",
            source_agent_id="agent-src",
            target_agent_id="agent-tgt",
            created_by="user",
            reason="handoff",
            delegated_wake_grant_id="dw-1",
            expires_at=datetime.fromisoformat(future),
        )
        listed = service.list_delegated_wake_grants("workspace-dw")[
            "delegatedWakeGrants"
        ]
        self.assertEqual([item["delegatedWakeGrantId"] for item in listed], ["dw-1"])
        self.assertEqual(listed[0]["state"], "pending")


class ProjectDirectoryCoordinationServiceTests(unittest.TestCase):
    def test_declare_and_list_directory_coordination_records_overlap(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_delegated_wake_workspace(connection, service)

        first = service.declare_project_directory_coordination(
            "workspace-dw",
            directory_coordination_id="coord-src",
            declared_agent_id="agent-src",
            project_root="X:/fixture/workspace-dw",
            git_repository_id="repo-dw",
            declared_path_scopes=("docs",),
            directory_access_intent="editing",
            last_known_git_head="abc123",
            last_known_branch="main",
            dirty_state="dirty_reported",
            uncommitted_change_summary="Editing docs.",
        )
        second = service.declare_project_directory_coordination(
            "workspace-dw",
            directory_coordination_id="coord-tgt",
            declared_agent_id="agent-tgt",
            project_root="X:/fixture/workspace-dw",
            git_repository_id="repo-dw",
            declared_path_scopes=("docs/api",),
            directory_access_intent="read_only",
        )
        listed = service.list_project_directory_coordination("workspace-dw")[
            "projectDirectoryCoordinations"
        ]

        self.assertTrue(first["declared"])
        self.assertTrue(second["declared"])
        self.assertEqual(second["projectDirectoryCoordination"]["overlapStatus"], "shared_write_risk")
        self.assertEqual(
            second["projectDirectoryCoordination"]["overlappingCoordinationIds"],
            ["coord-src"],
        )
        self.assertEqual(
            [item["directoryCoordinationId"] for item in listed],
            ["coord-src", "coord-tgt"],
        )
        self.assertEqual(listed[0]["overlapStatus"], "shared_write_risk")
        self.assertTrue(listed[0]["notSecurityBoundary"])
        self.assertTrue(listed[0]["advisoryOnly"])
        self.assertFalse(listed[0]["fileBodiesRead"])
        self.assertFalse(listed[0]["gitOperationExecuted"])
        self.assertFalse(listed[0]["realRuntimeConnected"])

    def test_complete_record_removes_active_overlap_without_git_operations(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_delegated_wake_workspace(connection, service)

        service.declare_project_directory_coordination(
            "workspace-dw",
            directory_coordination_id="coord-src",
            declared_agent_id="agent-src",
            project_root="X:/fixture/workspace-dw",
            declared_path_scopes=("src",),
            directory_access_intent="editing",
        )
        service.declare_project_directory_coordination(
            "workspace-dw",
            directory_coordination_id="coord-tgt",
            declared_agent_id="agent-tgt",
            project_root="X:/fixture/workspace-dw",
            declared_path_scopes=("src/agent_os",),
            directory_access_intent="editing",
        )
        completed = service.complete_project_directory_coordination(
            "workspace-dw",
            directory_coordination_id="coord-src",
            dirty_state="clean",
            test_summary="Focused tests passed.",
            handoff_note="Committed by external agent.",
        )
        target_status = service.get_project_directory_coordination_status(
            "workspace-dw",
            directory_coordination_id="coord-tgt",
        )["projectDirectoryCoordination"]

        self.assertTrue(completed["updated"])
        self.assertEqual(
            completed["projectDirectoryCoordination"]["directoryAccessIntent"],
            "done_reported",
        )
        self.assertFalse(
            completed["projectDirectoryCoordination"]["gitOperationExecuted"]
        )
        self.assertEqual(target_status["overlapStatus"], "none")

    def test_directory_coordination_rejects_secret_metadata_and_missing_status(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        service = _service(connection)
        _seed_delegated_wake_workspace(connection, service)

        with self.assertRaisesRegex(ValueError, "credential values"):
            service.declare_project_directory_coordination(
                "workspace-dw",
                directory_coordination_id="coord-secret",
                declared_agent_id="agent-src",
                project_root="X:/fixture/workspace-dw",
                metadata={"Authorization": "Bearer sk-example-token-value"},
            )

        missing = service.get_project_directory_coordination_status(
            "workspace-dw",
            directory_coordination_id="missing",
        )["projectDirectoryCoordination"]

        self.assertEqual(missing["state"], "missing")
        self.assertTrue(missing["notSecurityBoundary"])
        self.assertFalse(missing["gitOperationExecuted"])


def _seed_delegated_wake_workspace(
    connection: sqlite3.Connection,
    service: LocalPlatformOperationService,
) -> None:
    service.create_workspace(
        workspace_id="workspace-dw",
        display_name="Delegated Wake Workspace",
        root_path="X:/fixture/workspace-dw",
        agent_id="agent-src",
        agent_name="Source Agent",
        agent_description="Source agent for delegated wake.",
    )
    service.create_agent_registration(
        "workspace-dw",
        agent_id="agent-tgt",
        name="Target Agent",
        description="Target agent for delegated wake.",
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


def _seed_current_state(connection: sqlite3.Connection) -> None:
    workspace_store = SqliteWorkspaceStateStore(connection)
    context_store = SqliteContextStateStore(connection)
    agent_store = SqliteAgentRegistrationStateStore(connection)
    task_store = SqliteTaskStateStore(connection)
    issue_store = SqliteIssueStateStore(connection)

    workspace_store.upsert_workspace_state(
        workspace=ProjectWorkspace.create(
            workspace_id=WorkspaceId("workspace-2"),
            display_name="Workspace 2",
            root_path="X:/fixture/workspace-2",
        ),
        source_event_sequence=2,
    )
    workspace_store.upsert_workspace_state(
        workspace=ProjectWorkspace.create(
            workspace_id=WorkspaceId("workspace-1"),
            display_name="Workspace 1",
            root_path="X:/fixture/workspace-1",
        ),
        source_event_sequence=1,
    )
    context_store.upsert_context_state(
        context=ProjectSharedContext.create(
            context_id=ContextId("context-1"),
            workspace_id=WorkspaceId("workspace-1"),
            materialized_state={"status": "open"},
        ),
        source_event_sequence=3,
    )
    agent_store.upsert_agent_registration_state(
        registration=AgentRegistration.register(
            agent_id=AgentId("agent-1"),
            workspace_id=WorkspaceId("workspace-1"),
            name="Runtime Agent",
            description="Handles local requests",
            capabilities=(
                AgentCapability(
                    name="single-turn",
                    description="Captures single-turn requests",
                ),
            ),
            created_at=datetime(2026, 6, 5, 1, 0, tzinfo=timezone.utc),
            default_model="deterministic/local",
            tool_permissions=("workspace.read",),
            runtime_config={"mode": "deterministic"},
        ),
        source_event_sequence=4,
    )
    task_store.upsert_task_state(
        task=TaskContext.create(
            task_id=TaskId("task-1"),
            workspace_id=WorkspaceId("workspace-1"),
            title="Wire local operation service",
            assignee_agent_id=AgentId("agent-1"),
        ),
        source_event_sequence=5,
    )
    issue_store.upsert_issue_state(
        issue=IssueContext.create(
            issue_id=IssueId("issue-1"),
            workspace_id=WorkspaceId("workspace-1"),
            title="Track operation surface gap",
            severity=IssueSeverity.HIGH,
        ),
        source_event_sequence=6,
    )


def _append_event(
    event_log: SqlitePlatformEventLog,
    *,
    event_id: str,
    session_id: str,
    event_kind: PlatformEventKind,
    aggregate_type: str,
    aggregate_id: str,
    occurred_at: datetime,
    payload: dict[str, object] | None = None,
) -> int:
    return event_log.append(
        PlatformEventRecord.create(
            event_id=PlatformEventId(event_id),
            workspace_id=WorkspaceId("workspace-1"),
            session_id=PlatformRunSessionId(session_id),
            event_kind=event_kind,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            occurred_at=occurred_at,
            payload=payload or {},
        )
    )


def _invocation_request(
    *,
    invocation_id: str,
    idempotency_key: str,
    requested_at: datetime,
) -> AgentInvocationRequest:
    return AgentInvocationRequest.create(
        invocation_id=AgentInvocationId(invocation_id),
        workspace_id=WorkspaceId("workspace-1"),
        agent_id=AgentId("agent-1"),
        task_id=TaskId("task-1"),
        instruction="Summarize current task state",
        requested_at=requested_at,
        requested_capability="single-turn",
        context_update_ids=(ContextUpdateId("update-request-1"),),
        file_references=("docs/status.md",),
        idempotency_key=idempotency_key,
        correlation_id=f"corr-{invocation_id}",
        metadata={"source": "local-operation-test"},
    )


def _file_operation_request(
    *,
    operation_id: str,
    operation_kind: FileOperationKind,
    relative_path: str,
    invocation_id: str,
    requested_at: datetime,
) -> FileOperationRequest:
    return FileOperationRequest.create(
        operation_id=FileOperationId(operation_id),
        workspace_id=WorkspaceId("workspace-1"),
        operation_kind=operation_kind,
        relative_path=relative_path,
        requested_at=requested_at,
        requested_by_agent_id=AgentId("agent-1"),
        invocation_id=AgentInvocationId(invocation_id),
        task_id=TaskId("task-1"),
        reason="Query local file operation records",
        metadata={"source": "local-operation-test"},
    )


class _MismatchedContextReader:
    def get_context_state(
        self,
        workspace_id: WorkspaceId,
    ) -> ContextStateRecord | None:
        return ContextStateRecord(
            source_event_sequence=1,
            update_count=0,
            context=ProjectSharedContext.create(
                context_id=ContextId("context-other"),
                workspace_id=WorkspaceId("workspace-other"),
            ),
        )


if __name__ == "__main__":
    unittest.main()
