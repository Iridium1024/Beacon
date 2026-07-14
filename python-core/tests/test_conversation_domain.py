from __future__ import annotations

from datetime import datetime, timezone
import unittest

from agent_os.domain.entities.conversation import (
    ConversationMessage,
    ConversationMessageRole,
    ConversationSession,
    ConversationStatus,
)
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextUpdateId,
    ConversationId,
    ConversationMessageId,
    PlatformRunSessionId,
    WorkspaceId,
)


class ConversationSessionTests(unittest.TestCase):
    def test_create_and_archive_conversation_session(self) -> None:
        created_at = datetime(2026, 6, 12, tzinfo=timezone.utc)
        session = ConversationSession.create(
            conversation_id=ConversationId("conversation-1"),
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
            title="Reviewer thread",
            created_at=created_at,
            metadata={"profile_name": "reviewer"},
        )

        archived = session.archive(
            archived_at=datetime(2026, 6, 12, 1, tzinfo=timezone.utc)
        )

        self.assertEqual(session.status, ConversationStatus.ACTIVE)
        self.assertEqual(archived.status, ConversationStatus.ARCHIVED)
        self.assertEqual(archived.agent_id, AgentId("agent-1"))
        self.assertEqual(archived.metadata["profile_name"], "reviewer")

    def test_rejects_invalid_conversation_lifecycle_state(self) -> None:
        with self.assertRaisesRegex(ValueError, "title"):
            ConversationSession.create(
                workspace_id=WorkspaceId("workspace-1"),
                title=" ",
            )
        with self.assertRaisesRegex(ValueError, "archived_at"):
            ConversationSession(
                conversation_id=ConversationId("conversation-1"),
                workspace_id=WorkspaceId("workspace-1"),
                title="Thread",
                status=ConversationStatus.ARCHIVED,
                created_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
                updated_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
            )


class ConversationMessageTests(unittest.TestCase):
    def test_create_message_with_links(self) -> None:
        message = ConversationMessage.create(
            message_id=ConversationMessageId("message-1"),
            conversation_id=ConversationId("conversation-1"),
            workspace_id=WorkspaceId("workspace-1"),
            sequence=1,
            role=ConversationMessageRole.ASSISTANT,
            content="Review complete.",
            created_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
            agent_id=AgentId("agent-1"),
            invocation_id=AgentInvocationId("invoke-1"),
            context_update_id=ContextUpdateId("update-1"),
            run_session_id=PlatformRunSessionId("session-1"),
            metadata={"source": "invocation"},
        )

        self.assertEqual(message.role, ConversationMessageRole.ASSISTANT)
        self.assertEqual(message.sequence, 1)
        self.assertEqual(message.invocation_id, AgentInvocationId("invoke-1"))
        self.assertEqual(message.run_session_id, PlatformRunSessionId("session-1"))

    def test_rejects_invalid_message_sequence_and_content(self) -> None:
        with self.assertRaisesRegex(ValueError, "sequence"):
            ConversationMessage.create(
                conversation_id=ConversationId("conversation-1"),
                workspace_id=WorkspaceId("workspace-1"),
                sequence=0,
                role=ConversationMessageRole.USER,
                content="hello",
            )
        with self.assertRaisesRegex(ValueError, "content"):
            ConversationMessage.create(
                conversation_id=ConversationId("conversation-1"),
                workspace_id=WorkspaceId("workspace-1"),
                sequence=1,
                role=ConversationMessageRole.USER,
                content=" ",
            )


if __name__ == "__main__":
    unittest.main()
