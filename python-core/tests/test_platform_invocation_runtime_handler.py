from __future__ import annotations

from datetime import datetime, timezone
import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.platform_invocation_runtime_handler import (
    PLATFORM_INVOCATION_RESPONSE_FIELDS,
    PLATFORM_INVOCATION_RESULT_FIELDS,
    PLATFORM_INVOCATION_USER_CONTEXT_UPDATE_FIELDS,
    SqlitePlatformInvocationRuntimeHandler,
    handle_sqlite_platform_invocation_payload,
)
from agent_os.application.services.provider_backed_agent_invocation_adapter import (
    ProviderBackedAgentInvocationAdapter,
)
from agent_os.domain.entities.conversation import ConversationSession
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextUpdateId,
    ConversationId,
    FileOperationId,
    WorkspaceId,
)
from agent_os.infrastructure.adapters.models import DeterministicModelProvider
from agent_os.infrastructure.persistence.conversations import SqliteConversationStore
from agent_os.infrastructure.persistence.file_operation_records import (
    SqliteFileOperationRecordStore,
)
from agent_os.infrastructure.persistence.invocation_records import (
    SqliteAgentInvocationRecordStore,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteContextStateStore,
)
from support.platform_invocation_fixtures import (
    connect_in_memory_platform,
    platform_event_count,
    seed_minimal_context_state,
    seed_minimal_invocation_platform_state,
    seed_minimal_workspace_state,
)


class SqlitePlatformInvocationRuntimeHandlerTests(unittest.TestCase):
    def test_handle_payload_runs_local_runtime_and_persists_records(self) -> None:
        connection = connect_in_memory_platform()
        seed_minimal_invocation_platform_state(connection)

        response = handle_sqlite_platform_invocation_payload(
            connection,
            {
                "workspaceId": "workspace-1",
                "agentId": "agent-1",
                "instruction": "Summarize the current task.",
                "invocationId": "invoke-1",
                "requestedAt": "2026-06-04T05:05:44Z",
                "requestedCapability": "single-turn-status",
                "contextUpdateIds": ["prior-update-1"],
                "fileReferences": ["docs/status.md"],
                "idempotencyKey": "idem-1",
                "correlationId": "corr-1",
                "requestMetadata": {"surface": "gateway"},
                "userContextUpdateId": "update-user-1",
                "userContextCreatedAt": "2026-06-04T05:06:00Z",
                "contextEventId": "event-context-1",
                "agentInvocationEventId": "event-invoke-1",
                "sessionId": "session-1",
                "contextMetadata": {"surface": "test"},
                "contextEventMetadata": {"phase": "context"},
                "agentInvocationEventMetadata": {"phase": "invoke"},
            },
        )

        self.assertEqual(set(response), set(PLATFORM_INVOCATION_RESPONSE_FIELDS))
        self.assertEqual(
            set(response["userContextUpdate"]),
            set(PLATFORM_INVOCATION_USER_CONTEXT_UPDATE_FIELDS),
        )
        self.assertEqual(
            set(response["invocationResult"]),
            set(PLATFORM_INVOCATION_RESULT_FIELDS),
        )
        self.assertEqual(response["workspaceId"], "workspace-1")
        self.assertEqual(response["agentId"], "agent-1")
        self.assertEqual(response["contextId"], "context-1")
        self.assertTrue(response["runtimeLoaded"])
        self.assertFalse(response["modelInvoked"])
        self.assertFalse(response["toolInvoked"])
        self.assertTrue(response["deterministicPlaceholder"])
        self.assertEqual(response["sourceEventSequence"], 2)
        self.assertEqual(response["agentInvocationEventSequence"], 4)
        self.assertEqual(
            response["runSessionEventSequences"],
            {"started": 1, "terminal": 5},
        )
        self.assertEqual(
            response["materializedState"]["last_user_instruction"]["invocation_id"],
            "invoke-1",
        )
        self.assertEqual(
            response["userContextUpdate"]["payload"]["instruction"],
            "Summarize the current task.",
        )
        self.assertEqual(response["userContextUpdate"]["updateId"], "update-user-1")
        self.assertEqual(response["invocationResult"]["status"], "succeeded")
        self.assertNotIn("provider", response["invocationResult"]["outputPayload"])
        self.assertFalse(response["invocationResult"]["outputPayload"]["model_invoked"])
        self.assertFalse(response["invocationResult"]["outputPayload"]["tool_invoked"])
        self.assertEqual(
            response["invocationResult"]["contextUpdateIds"],
            ["update-user-1"],
        )

        stored_context = SqliteContextStateStore(connection).get_context_state(
            WorkspaceId("workspace-1")
        )
        record = SqliteAgentInvocationRecordStore(
            connection
        ).get_agent_invocation_record(AgentInvocationId("invoke-1"))

        self.assertIsNotNone(stored_context)
        assert stored_context is not None
        self.assertEqual(stored_context.update_count, 1)
        self.assertEqual(stored_context.source_event_sequence, 2)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(record.source_event_sequence, 4)
        self.assertEqual(
            record.context_update_ids,
            (
                ContextUpdateId("prior-update-1"),
                ContextUpdateId("update-user-1"),
            ),
        )
        self.assertEqual(record.request_state["requested_capability"], "single-turn-status")
        self.assertEqual(platform_event_count(connection), 5)

    def test_handle_payload_links_invocation_to_conversation_messages(self) -> None:
        connection = connect_in_memory_platform()
        seed_minimal_invocation_platform_state(connection)
        conversation_store = SqliteConversationStore(connection)
        conversation = ConversationSession.create(
            conversation_id=ConversationId("conversation-invoke-1"),
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
            title="Invocation thread",
            created_at=datetime(2026, 6, 12, 9, 30, tzinfo=timezone.utc),
            metadata={"profile_name": "runtime"},
        )
        conversation_store.upsert_conversation_session(
            conversation=conversation,
            source_event_sequence=0,
        )

        response = handle_sqlite_platform_invocation_payload(
            connection,
            {
                "workspaceId": "workspace-1",
                "agentId": "agent-1",
                "instruction": "Keep this turn in conversation history.",
                "invocationId": "invoke-conversation-1",
                "requestedAt": "2026-06-12T09:31:00Z",
                "sessionId": "session-conversation-1",
                "conversationId": "conversation-invoke-1",
            },
        )

        self.assertEqual(
            response["conversation"]["conversationId"],
            "conversation-invoke-1",
        )
        self.assertEqual(
            [message["role"] for message in response["conversationMessages"]],
            ["user", "assistant"],
        )
        self.assertEqual(
            response["conversationMessages"][0]["content"],
            "Keep this turn in conversation history.",
        )
        self.assertEqual(
            response["conversationMessages"][0]["contextUpdateId"],
            response["userContextUpdate"]["updateId"],
        )
        self.assertEqual(
            response["conversationMessages"][1]["content"],
            response["invocationResult"]["outputText"],
        )
        self.assertEqual(
            [message["invocationId"] for message in response["conversationMessages"]],
            ["invoke-conversation-1", "invoke-conversation-1"],
        )
        self.assertEqual(
            [message["runSessionId"] for message in response["conversationMessages"]],
            ["session-conversation-1", "session-conversation-1"],
        )

        stored_messages = conversation_store.list_conversation_messages(
            ConversationId("conversation-invoke-1")
        )
        self.assertEqual(
            [record.message.role.value for record in stored_messages],
            ["user", "assistant"],
        )
        self.assertEqual(
            [record.source_event_sequence for record in stored_messages],
            [6, 7],
        )
        self.assertEqual(platform_event_count(connection), 7)

    def test_handle_payload_rejects_archived_conversation_before_events(self) -> None:
        connection = connect_in_memory_platform()
        seed_minimal_invocation_platform_state(connection)
        conversation_store = SqliteConversationStore(connection)
        conversation = ConversationSession.create(
            conversation_id=ConversationId("conversation-archived-1"),
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
            title="Archived thread",
            created_at=datetime(2026, 6, 12, 9, 35, tzinfo=timezone.utc),
        ).archive(archived_at=datetime(2026, 6, 12, 9, 36, tzinfo=timezone.utc))
        conversation_store.upsert_conversation_session(
            conversation=conversation,
            source_event_sequence=0,
        )

        with self.assertRaisesRegex(ValueError, "conversation is archived"):
            handle_sqlite_platform_invocation_payload(
                connection,
                {
                    "workspaceId": "workspace-1",
                    "agentId": "agent-1",
                    "instruction": "Should not write events.",
                    "conversationId": "conversation-archived-1",
                },
            )

        self.assertEqual(platform_event_count(connection), 0)

    def test_handle_payload_accepts_explicit_provider_backed_adapter(self) -> None:
        connection = connect_in_memory_platform()
        seed_minimal_invocation_platform_state(connection)
        adapter = ProviderBackedAgentInvocationAdapter(
            model_provider=DeterministicModelProvider(),
            provider_name="deterministic",
            model_name="deterministic-text",
        )

        response = handle_sqlite_platform_invocation_payload(
            connection,
            {
                "workspaceId": "workspace-1",
                "agentId": "agent-1",
                "instruction": "Use explicit provider adapter.",
                "invocationId": "invoke-provider-handler-1",
                "requestedAt": "2026-06-04T22:58:00Z",
                "userContextUpdateId": "update-provider-handler-1",
                "contextEventId": "event-context-provider-handler-1",
                "agentInvocationEventId": "event-invoke-provider-handler-1",
            },
            agent_invocation_adapter=adapter,
        )

        self.assertTrue(response["modelInvoked"])
        self.assertFalse(response["toolInvoked"])
        self.assertFalse(response["deterministicPlaceholder"])
        self.assertEqual(
            response["invocationResult"]["outputText"],
            "Deterministic model response: Use explicit provider adapter.",
        )
        self.assertEqual(
            response["invocationResult"]["metadata"]["source"],
            "provider_backed_agent_invocation_adapter",
        )
        self.assertEqual(
            response["invocationResult"]["outputPayload"]["provider_name"],
            "deterministic",
        )

    def test_handle_payload_rejects_missing_workspace_without_writing_events(self) -> None:
        connection = connect_in_memory_platform()

        with self.assertRaisesRegex(ValueError, "workspace state not found"):
            SqlitePlatformInvocationRuntimeHandler(connection).handle_payload(
                {
                    "workspaceId": "workspace-1",
                    "agentId": "agent-1",
                    "instruction": "Capture this task.",
                }
            )

        self.assertEqual(platform_event_count(connection), 0)

    def test_handle_payload_rejects_missing_context_without_writing_events(self) -> None:
        connection = connect_in_memory_platform()
        seed_minimal_workspace_state(connection)

        with self.assertRaisesRegex(ValueError, "context state not found"):
            SqlitePlatformInvocationRuntimeHandler(connection).handle_payload(
                {
                    "workspaceId": "workspace-1",
                    "agentId": "agent-1",
                    "instruction": "Capture this task.",
                }
            )

        self.assertEqual(platform_event_count(connection), 0)

    def test_file_operation_payload_rejects_missing_context_before_file_operation(self) -> None:
        connection = connect_in_memory_platform()
        seed_minimal_workspace_state(connection)

        with self.assertRaisesRegex(ValueError, "context state not found"):
            SqlitePlatformInvocationRuntimeHandler(connection).handle_payload(
                {
                    "workspaceId": "workspace-1",
                    "agentId": "agent-1",
                    "instruction": "Capture this task with file context.",
                    "invocationId": "invoke-missing-context-file-1",
                    "fileOperations": [
                        {
                            "operationKind": "read_file",
                            "relativePath": "docs/status.md",
                            "operationId": "file-op-missing-context-1",
                        }
                    ],
                }
            )

        record = SqliteFileOperationRecordStore(connection).get_file_operation_record(
            FileOperationId("file-op-missing-context-1")
        )
        self.assertIsNone(record)
        self.assertEqual(platform_event_count(connection), 0)

    def test_handle_payload_rejects_missing_agent_without_writing_events(self) -> None:
        connection = connect_in_memory_platform()
        seed_minimal_workspace_state(connection)
        seed_minimal_context_state(connection)

        with self.assertRaisesRegex(ValueError, "agent registration state not found"):
            SqlitePlatformInvocationRuntimeHandler(connection).handle_payload(
                {
                    "workspaceId": "workspace-1",
                    "agentId": "agent-1",
                    "instruction": "Capture this task.",
                }
            )

        self.assertEqual(platform_event_count(connection), 0)

    def test_duplicate_idempotency_key_rejects_before_context_write(self) -> None:
        connection = connect_in_memory_platform()
        seed_minimal_invocation_platform_state(connection)
        handler = SqlitePlatformInvocationRuntimeHandler(connection)

        handler.handle_payload(
            {
                "workspaceId": "workspace-1",
                "agentId": "agent-1",
                "instruction": "Capture this task.",
                "invocationId": "invoke-idem-1",
                "requestedAt": "2026-06-04T06:20:00Z",
                "userContextUpdateId": "update-idem-1",
                "idempotencyKey": "idem-1",
            }
        )

        with self.assertRaisesRegex(ValueError, "idempotency_key"):
            handler.handle_payload(
                {
                    "workspaceId": "workspace-1",
                    "agentId": "agent-1",
                    "instruction": "Capture this task again.",
                    "invocationId": "invoke-idem-2",
                    "requestedAt": "2026-06-04T06:21:00Z",
                    "userContextUpdateId": "update-idem-2",
                    "idempotencyKey": "idem-1",
                }
            )

        self.assertEqual(platform_event_count(connection), 3)
        stored_context = SqliteContextStateStore(connection).get_context_state(
            WorkspaceId("workspace-1")
        )
        self.assertIsNotNone(stored_context)
        assert stored_context is not None
        self.assertEqual(stored_context.update_count, 1)
        record = SqliteAgentInvocationRecordStore(
            connection
        ).get_agent_invocation_record(AgentInvocationId("invoke-idem-2"))
        self.assertIsNone(record)

    def test_response_contract_allows_null_agent_event_sequence(self) -> None:
        connection = connect_in_memory_platform()
        seed_minimal_invocation_platform_state(connection)

        response = SqlitePlatformInvocationRuntimeHandler(
            connection,
            record_agent_invocations=False,
        ).handle_payload(
            {
                "workspaceId": "workspace-1",
                "agentId": "agent-1",
                "instruction": "Capture this task.",
                "invocationId": "invoke-no-record-1",
                "requestedAt": "2026-06-04T06:10:00Z",
                "userContextUpdateId": "update-no-record-1",
            }
        )

        self.assertEqual(set(response), set(PLATFORM_INVOCATION_RESPONSE_FIELDS))
        self.assertIsNone(response["agentInvocationEventSequence"])
        self.assertEqual(response["sourceEventSequence"], 1)
        self.assertEqual(platform_event_count(connection), 1)
        record = SqliteAgentInvocationRecordStore(
            connection
        ).get_agent_invocation_record(AgentInvocationId("invoke-no-record-1"))
        self.assertIsNone(record)

    def test_idempotency_key_requires_invocation_recording_before_side_effects(self) -> None:
        connection = connect_in_memory_platform()
        seed_minimal_invocation_platform_state(connection)

        with self.assertRaisesRegex(ValueError, "idempotency_key"):
            SqlitePlatformInvocationRuntimeHandler(
                connection,
                record_agent_invocations=False,
            ).handle_payload(
                {
                    "workspaceId": "workspace-1",
                    "agentId": "agent-1",
                    "instruction": "Capture this task.",
                    "invocationId": "invoke-no-record-idem-1",
                    "requestedAt": "2026-06-04T06:11:00Z",
                    "userContextUpdateId": "update-no-record-idem-1",
                    "idempotencyKey": "idem-no-record-1",
                    "fileOperations": [
                        {
                            "operationKind": "read_file",
                            "relativePath": "docs/status.md",
                            "operationId": "file-op-no-record-idem-1",
                        }
                    ],
                }
            )

        self.assertEqual(platform_event_count(connection), 0)
        file_record = SqliteFileOperationRecordStore(
            connection
        ).get_file_operation_record(FileOperationId("file-op-no-record-idem-1"))
        self.assertIsNone(file_record)
        invocation_record = SqliteAgentInvocationRecordStore(
            connection
        ).get_agent_invocation_record(
            AgentInvocationId("invoke-no-record-idem-1")
        )
        self.assertIsNone(invocation_record)

    def test_handle_payload_supports_snake_case_callers(self) -> None:
        connection = connect_in_memory_platform()
        seed_minimal_invocation_platform_state(connection)

        response = SqlitePlatformInvocationRuntimeHandler(connection).handle_payload(
            {
                "workspace_id": "workspace-1",
                "agent_id": "agent-1",
                "instruction": "Capture this task.",
                "invocation_id": "invoke-snake-1",
                "requested_at": "2026-06-04T06:00:00+00:00",
                "user_context_update_id": "update-snake-1",
            }
        )

        self.assertEqual(response["workspaceId"], "workspace-1")
        self.assertEqual(response["invocationResult"]["invocationId"], "invoke-snake-1")
        self.assertEqual(response["userContextUpdate"]["updateId"], "update-snake-1")
        self.assertEqual(platform_event_count(connection), 3)

    def test_file_operation_payload_rejects_malformed_context_metadata_before_events(self) -> None:
        connection = connect_in_memory_platform()
        seed_minimal_invocation_platform_state(connection)

        with self.assertRaisesRegex(ValueError, "context_metadata"):
            SqlitePlatformInvocationRuntimeHandler(connection).handle_payload(
                {
                    "workspaceId": "workspace-1",
                    "agentId": "agent-1",
                    "instruction": "Capture this task with malformed metadata.",
                    "invocationId": "invoke-malformed-context-metadata-file-1",
                    "contextMetadata": "metadata",
                    "fileOperations": [
                        {
                            "operationKind": "read_file",
                            "relativePath": "docs/status.md",
                            "operationId": "file-op-malformed-context-metadata-1",
                        }
                    ],
                }
            )

        record = SqliteFileOperationRecordStore(connection).get_file_operation_record(
            FileOperationId("file-op-malformed-context-metadata-1")
        )
        self.assertIsNone(record)
        self.assertEqual(platform_event_count(connection), 0)

    def test_file_operation_payload_rejects_duplicate_operation_ids_before_events(self) -> None:
        connection = connect_in_memory_platform()
        seed_minimal_invocation_platform_state(connection)

        with self.assertRaisesRegex(ValueError, "operation_id"):
            SqlitePlatformInvocationRuntimeHandler(connection).handle_payload(
                {
                    "workspaceId": "workspace-1",
                    "agentId": "agent-1",
                    "instruction": "Capture this task with duplicate file operation ids.",
                    "invocationId": "invoke-duplicate-file-ops-1",
                    "fileOperations": [
                        {
                            "operationKind": "read_file",
                            "relativePath": "docs/status.md",
                            "operationId": "file-op-duplicate-1",
                        },
                        {
                            "operationKind": "list_directory",
                            "relativePath": ".",
                            "operationId": "file-op-duplicate-1",
                        },
                    ],
                }
            )

        record = SqliteFileOperationRecordStore(connection).get_file_operation_record(
            FileOperationId("file-op-duplicate-1")
        )
        self.assertIsNone(record)
        self.assertEqual(platform_event_count(connection), 0)

    def test_handle_payload_rejects_malformed_runtime_fields(self) -> None:
        connection = connect_in_memory_platform()
        seed_minimal_invocation_platform_state(connection)
        base_payload = {
            "workspaceId": "workspace-1",
            "agentId": "agent-1",
            "instruction": "Capture this task.",
        }

        with self.assertRaisesRegex(ValueError, "context_update_ids"):
            SqlitePlatformInvocationRuntimeHandler(connection).handle_payload(
                {
                    **base_payload,
                    "contextUpdateIds": ["update-1", 2],
                }
            )

        with self.assertRaisesRegex(ValueError, "context_metadata"):
            SqlitePlatformInvocationRuntimeHandler(connection).handle_payload(
                {
                    **base_payload,
                    "contextMetadata": "metadata",
                }
            )

        with self.assertRaisesRegex(ValueError, "requested_at"):
            SqlitePlatformInvocationRuntimeHandler(connection).handle_payload(
                {
                    **base_payload,
                    "requestedAt": "not-a-datetime",
                }
            )


if __name__ == "__main__":
    unittest.main()
