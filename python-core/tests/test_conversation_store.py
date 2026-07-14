from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
import unittest

from agent_os.domain.entities.agent import AgentCapability, AgentRegistration
from agent_os.domain.entities.conversation import (
    ConversationMessage,
    ConversationMessageRole,
    ConversationSession,
    ConversationStatus,
)
from agent_os.domain.entities.workspace import ProjectWorkspace
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextUpdateId,
    ConversationId,
    ConversationMessageId,
    PlatformRunSessionId,
    WorkspaceId,
)
from agent_os.infrastructure.persistence.conversations import (
    SQLITE_PLATFORM_CONVERSATION_SCHEMA,
    SqliteConversationStore,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteAgentRegistrationStateStore,
    SqliteWorkspaceStateStore,
)
from agent_os.infrastructure.persistence.sqlite_persistence import (
    SQLITE_PLATFORM_PERSISTENCE_SCHEMA,
    SqlitePlatformPersistence,
)


class ConversationSchemaTests(unittest.TestCase):
    def test_combined_schema_includes_conversation_tables(self) -> None:
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS platform_conversation_sessions",
            SQLITE_PLATFORM_PERSISTENCE_SCHEMA,
        )
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS platform_conversation_messages",
            SQLITE_PLATFORM_PERSISTENCE_SCHEMA,
        )

    def test_schema_creates_conversation_tables_and_indexes(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.executescript(SQLITE_PLATFORM_CONVERSATION_SCHEMA)

        table_names = _table_names(connection)
        session_indexes = _table_indexes(connection, "platform_conversation_sessions")
        message_indexes = _table_indexes(connection, "platform_conversation_messages")

        self.assertIn("platform_conversation_sessions", table_names)
        self.assertIn("platform_conversation_messages", table_names)
        self.assertIn(
            "idx_platform_conversation_sessions_workspace_status",
            session_indexes,
        )
        self.assertIn(
            "idx_platform_conversation_messages_conversation_sequence",
            message_indexes,
        )


class SqliteConversationStoreTests(unittest.TestCase):
    def test_upsert_and_list_workspace_conversations(self) -> None:
        connection = _initialized_connection()
        store = SqliteConversationStore(connection)
        first = _conversation(
            conversation_id="conversation-1",
            title="Reviewer thread",
        )
        second = _conversation(
            conversation_id="conversation-2",
            title="Planner thread",
        )

        store.upsert_conversation_session(
            conversation=first,
            source_event_sequence=3,
        )
        store.upsert_conversation_session(
            conversation=second,
            source_event_sequence=4,
        )

        listed = store.list_conversation_sessions_by_workspace(
            WorkspaceId("workspace-1")
        )

        self.assertEqual(
            [record.conversation.conversation_id.value for record in listed],
            ["conversation-1", "conversation-2"],
        )
        self.assertEqual(listed[0].conversation.agent_id, AgentId("agent-1"))
        self.assertEqual(listed[0].source_event_sequence, 3)

    def test_archive_conversation_updates_state(self) -> None:
        connection = _initialized_connection()
        store = SqliteConversationStore(connection)
        conversation = _conversation(conversation_id="conversation-1")
        archived = conversation.archive(
            archived_at=datetime(2026, 6, 12, 2, tzinfo=timezone.utc)
        )

        store.upsert_conversation_session(
            conversation=conversation,
            source_event_sequence=3,
        )
        store.upsert_conversation_session(
            conversation=archived,
            source_event_sequence=5,
        )

        record = store.get_conversation_session(ConversationId("conversation-1"))

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.conversation.status, ConversationStatus.ARCHIVED)
        self.assertEqual(record.source_event_sequence, 5)

    def test_append_and_page_messages_in_stable_sequence_order(self) -> None:
        connection = _initialized_connection()
        store = SqliteConversationStore(connection)
        store.upsert_conversation_session(
            conversation=_conversation(conversation_id="conversation-1"),
            source_event_sequence=3,
        )
        user = _message(
            message_id="message-1",
            sequence=1,
            role=ConversationMessageRole.USER,
            content="Please review this.",
        )
        assistant = _message(
            message_id="message-2",
            sequence=2,
            role=ConversationMessageRole.ASSISTANT,
            content="Review complete.",
            invocation_id=AgentInvocationId("invoke-1"),
            context_update_id=ContextUpdateId("update-1"),
            run_session_id=PlatformRunSessionId("session-1"),
        )

        store.append_conversation_message(message=user, source_event_sequence=6)
        store.append_conversation_message(message=assistant, source_event_sequence=7)

        messages = store.list_conversation_messages(ConversationId("conversation-1"))
        paged = store.list_conversation_messages(
            ConversationId("conversation-1"),
            limit=1,
            offset=1,
        )

        self.assertEqual([record.message.sequence for record in messages], [1, 2])
        self.assertEqual(paged[0].message.message_id, ConversationMessageId("message-2"))
        self.assertEqual(paged[0].message.invocation_id, AgentInvocationId("invoke-1"))
        self.assertEqual(store.next_conversation_message_sequence(ConversationId("conversation-1")), 3)

    def test_rejects_duplicate_message_sequence_and_missing_workspace(self) -> None:
        connection = _initialized_connection()
        store = SqliteConversationStore(connection)
        store.upsert_conversation_session(
            conversation=_conversation(conversation_id="conversation-1"),
            source_event_sequence=3,
        )
        store.append_conversation_message(
            message=_message(message_id="message-1", sequence=1),
            source_event_sequence=4,
        )

        with self.assertRaises(sqlite3.IntegrityError):
            store.append_conversation_message(
                message=_message(message_id="message-2", sequence=1),
                source_event_sequence=5,
            )
        with self.assertRaises(sqlite3.IntegrityError):
            store.upsert_conversation_session(
                conversation=ConversationSession.create(
                    conversation_id=ConversationId("conversation-missing"),
                    workspace_id=WorkspaceId("workspace-missing"),
                    title="Missing",
                ),
                source_event_sequence=6,
            )


def _initialized_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    SqlitePlatformPersistence(connection).initialize()
    workspace = ProjectWorkspace.create(
        workspace_id=WorkspaceId("workspace-1"),
        display_name="Workspace",
        root_path="X:/fixture/workspace",
    )
    SqliteWorkspaceStateStore(connection).upsert_workspace_state(
        workspace=workspace,
        source_event_sequence=1,
    )
    registration = AgentRegistration.register(
        agent_id=AgentId("agent-1"),
        workspace_id=WorkspaceId("workspace-1"),
        name="Reviewer",
        description="Reviews local work.",
        capabilities=(
            AgentCapability(
                name="review",
                description="Reviews local work.",
            ),
        ),
        created_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
    )
    SqliteAgentRegistrationStateStore(connection).upsert_agent_registration_state(
        registration=registration,
        source_event_sequence=2,
    )
    return connection


def _conversation(
    *,
    conversation_id: str,
    title: str = "Thread",
) -> ConversationSession:
    return ConversationSession.create(
        conversation_id=ConversationId(conversation_id),
        workspace_id=WorkspaceId("workspace-1"),
        agent_id=AgentId("agent-1"),
        title=title,
        created_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
        metadata={"profile_name": "reviewer"},
    )


def _message(
    *,
    message_id: str,
    sequence: int,
    role: ConversationMessageRole = ConversationMessageRole.USER,
    content: str = "Hello.",
    invocation_id: AgentInvocationId | None = None,
    context_update_id: ContextUpdateId | None = None,
    run_session_id: PlatformRunSessionId | None = None,
) -> ConversationMessage:
    return ConversationMessage.create(
        message_id=ConversationMessageId(message_id),
        conversation_id=ConversationId("conversation-1"),
        workspace_id=WorkspaceId("workspace-1"),
        sequence=sequence,
        role=role,
        content=content,
        created_at=datetime(2026, 6, 12, 1, tzinfo=timezone.utc),
        agent_id=AgentId("agent-1"),
        invocation_id=invocation_id,
        context_update_id=context_update_id,
        run_session_id=run_session_id,
    )


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def _table_indexes(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        row[1]
        for row in connection.execute(f"PRAGMA index_list('{table_name}')")
    }


if __name__ == "__main__":
    unittest.main()
