from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import sqlite3
from typing import Mapping, Protocol

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


SQLITE_PLATFORM_CONVERSATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS platform_conversation_sessions (
    conversation_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    agent_id TEXT,
    source_event_sequence INTEGER NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT,
    CHECK (source_event_sequence >= 0),
    FOREIGN KEY (workspace_id)
        REFERENCES platform_workspace_state(workspace_id)
        ON DELETE CASCADE,
    FOREIGN KEY (agent_id)
        REFERENCES platform_agent_registration_state(agent_id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_platform_conversation_sessions_workspace_status
    ON platform_conversation_sessions(workspace_id, status);

CREATE INDEX IF NOT EXISTS idx_platform_conversation_sessions_agent
    ON platform_conversation_sessions(agent_id)
    WHERE agent_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS platform_conversation_messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    source_event_sequence INTEGER NOT NULL,
    sequence INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    agent_id TEXT,
    invocation_id TEXT,
    context_update_id TEXT,
    run_session_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    CHECK (source_event_sequence >= 0),
    CHECK (sequence >= 1),
    UNIQUE (conversation_id, sequence),
    FOREIGN KEY (conversation_id)
        REFERENCES platform_conversation_sessions(conversation_id)
        ON DELETE CASCADE,
    FOREIGN KEY (workspace_id)
        REFERENCES platform_workspace_state(workspace_id)
        ON DELETE CASCADE,
    FOREIGN KEY (agent_id)
        REFERENCES platform_agent_registration_state(agent_id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_platform_conversation_messages_conversation_sequence
    ON platform_conversation_messages(conversation_id, sequence);

CREATE INDEX IF NOT EXISTS idx_platform_conversation_messages_workspace_created
    ON platform_conversation_messages(workspace_id, created_at);

CREATE INDEX IF NOT EXISTS idx_platform_conversation_messages_invocation
    ON platform_conversation_messages(invocation_id)
    WHERE invocation_id IS NOT NULL;
"""


CONVERSATION_SESSION_COLUMNS = (
    "conversation_id",
    "workspace_id",
    "agent_id",
    "source_event_sequence",
    "title",
    "status",
    "metadata_json",
    "created_at",
    "updated_at",
    "archived_at",
)


CONVERSATION_MESSAGE_COLUMNS = (
    "message_id",
    "conversation_id",
    "workspace_id",
    "source_event_sequence",
    "sequence",
    "role",
    "content",
    "agent_id",
    "invocation_id",
    "context_update_id",
    "run_session_id",
    "metadata_json",
    "created_at",
)


CONVERSATION_SESSION_UPSERT_SQL = (
    f"INSERT INTO platform_conversation_sessions ({', '.join(CONVERSATION_SESSION_COLUMNS)}) "
    f"VALUES ({', '.join(f':{column}' for column in CONVERSATION_SESSION_COLUMNS)}) "
    "ON CONFLICT(conversation_id) DO UPDATE SET "
    "workspace_id = excluded.workspace_id, "
    "agent_id = excluded.agent_id, "
    "source_event_sequence = excluded.source_event_sequence, "
    "title = excluded.title, "
    "status = excluded.status, "
    "metadata_json = excluded.metadata_json, "
    "created_at = excluded.created_at, "
    "updated_at = excluded.updated_at, "
    "archived_at = excluded.archived_at"
)


CONVERSATION_MESSAGE_INSERT_SQL = (
    f"INSERT INTO platform_conversation_messages ({', '.join(CONVERSATION_MESSAGE_COLUMNS)}) "
    f"VALUES ({', '.join(f':{column}' for column in CONVERSATION_MESSAGE_COLUMNS)})"
)


def _stable_json(value: Mapping[str, object]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _load_mapping_json(value: object, field_name: str) -> Mapping[str, object]:
    loaded = json.loads(str(value))
    if not isinstance(loaded, dict):
        raise ValueError(f"{field_name} must decode to a JSON object.")
    return loaded


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


@dataclass(frozen=True, slots=True)
class ConversationSessionRecord:
    conversation: ConversationSession
    source_event_sequence: int

    def __post_init__(self) -> None:
        if self.source_event_sequence < 0:
            raise ValueError("source_event_sequence must be non-negative.")

    @classmethod
    def from_sqlite_row(
        cls,
        row: Mapping[str, object | None],
    ) -> "ConversationSessionRecord":
        agent_id = row["agent_id"]
        archived_at = row["archived_at"]
        return cls(
            conversation=ConversationSession(
                conversation_id=ConversationId(str(row["conversation_id"])),
                workspace_id=WorkspaceId(str(row["workspace_id"])),
                agent_id=AgentId(str(agent_id)) if agent_id is not None else None,
                title=str(row["title"]),
                status=ConversationStatus(str(row["status"])),
                created_at=datetime.fromisoformat(str(row["created_at"])),
                updated_at=datetime.fromisoformat(str(row["updated_at"])),
                archived_at=(
                    datetime.fromisoformat(str(archived_at))
                    if archived_at is not None
                    else None
                ),
                metadata=_load_mapping_json(row["metadata_json"], "metadata_json"),
            ),
            source_event_sequence=int(row["source_event_sequence"] or 0),
        )

    def to_sqlite_row(self) -> Mapping[str, object | None]:
        conversation = self.conversation
        return {
            "conversation_id": conversation.conversation_id.value,
            "workspace_id": conversation.workspace_id.value,
            "agent_id": (
                conversation.agent_id.value
                if conversation.agent_id is not None
                else None
            ),
            "source_event_sequence": self.source_event_sequence,
            "title": conversation.title,
            "status": conversation.status.value,
            "metadata_json": _stable_json(conversation.metadata),
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
            "archived_at": (
                conversation.archived_at.isoformat()
                if conversation.archived_at is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class ConversationMessageRecord:
    message: ConversationMessage
    source_event_sequence: int

    def __post_init__(self) -> None:
        if self.source_event_sequence < 0:
            raise ValueError("source_event_sequence must be non-negative.")

    @classmethod
    def from_sqlite_row(
        cls,
        row: Mapping[str, object | None],
    ) -> "ConversationMessageRecord":
        agent_id = row["agent_id"]
        invocation_id = row["invocation_id"]
        context_update_id = row["context_update_id"]
        run_session_id = row["run_session_id"]
        return cls(
            message=ConversationMessage(
                message_id=ConversationMessageId(str(row["message_id"])),
                conversation_id=ConversationId(str(row["conversation_id"])),
                workspace_id=WorkspaceId(str(row["workspace_id"])),
                sequence=int(row["sequence"] or 0),
                role=ConversationMessageRole(str(row["role"])),
                content=str(row["content"]),
                created_at=datetime.fromisoformat(str(row["created_at"])),
                agent_id=AgentId(str(agent_id)) if agent_id is not None else None,
                invocation_id=(
                    AgentInvocationId(str(invocation_id))
                    if invocation_id is not None
                    else None
                ),
                context_update_id=(
                    ContextUpdateId(str(context_update_id))
                    if context_update_id is not None
                    else None
                ),
                run_session_id=(
                    PlatformRunSessionId(str(run_session_id))
                    if run_session_id is not None
                    else None
                ),
                metadata=_load_mapping_json(row["metadata_json"], "metadata_json"),
            ),
            source_event_sequence=int(row["source_event_sequence"] or 0),
        )

    def to_sqlite_row(self) -> Mapping[str, object | None]:
        message = self.message
        return {
            "message_id": message.message_id.value,
            "conversation_id": message.conversation_id.value,
            "workspace_id": message.workspace_id.value,
            "source_event_sequence": self.source_event_sequence,
            "sequence": message.sequence,
            "role": message.role.value,
            "content": message.content,
            "agent_id": message.agent_id.value if message.agent_id is not None else None,
            "invocation_id": (
                message.invocation_id.value
                if message.invocation_id is not None
                else None
            ),
            "context_update_id": (
                message.context_update_id.value
                if message.context_update_id is not None
                else None
            ),
            "run_session_id": (
                message.run_session_id.value
                if message.run_session_id is not None
                else None
            ),
            "metadata_json": _stable_json(message.metadata),
            "created_at": message.created_at.isoformat(),
        }


class ConversationSessionReaderPort(Protocol):
    def get_conversation_session(
        self,
        conversation_id: ConversationId,
    ) -> ConversationSessionRecord | None:
        ...

    def list_conversation_sessions_by_workspace(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[ConversationSessionRecord, ...]:
        ...


class ConversationSessionWriterPort(Protocol):
    def upsert_conversation_session(
        self,
        *,
        conversation: ConversationSession,
        source_event_sequence: int,
    ) -> None:
        ...


class ConversationMessageReaderPort(Protocol):
    def get_conversation_message(
        self,
        message_id: ConversationMessageId,
    ) -> ConversationMessageRecord | None:
        ...

    def list_conversation_messages(
        self,
        conversation_id: ConversationId,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[ConversationMessageRecord, ...]:
        ...

    def next_conversation_message_sequence(
        self,
        conversation_id: ConversationId,
    ) -> int:
        ...


class ConversationMessageWriterPort(Protocol):
    def append_conversation_message(
        self,
        *,
        message: ConversationMessage,
        source_event_sequence: int,
    ) -> None:
        ...


@dataclass(slots=True)
class SqliteConversationStore(
    ConversationSessionReaderPort,
    ConversationSessionWriterPort,
    ConversationMessageReaderPort,
    ConversationMessageWriterPort,
):
    connection: sqlite3.Connection

    def initialize(self) -> None:
        self.connection.executescript(SQLITE_PLATFORM_CONVERSATION_SCHEMA)
        self.connection.commit()

    def upsert_conversation_session(
        self,
        *,
        conversation: ConversationSession,
        source_event_sequence: int,
    ) -> None:
        record = ConversationSessionRecord(
            conversation=conversation,
            source_event_sequence=source_event_sequence,
        )
        self.connection.execute(CONVERSATION_SESSION_UPSERT_SQL, record.to_sqlite_row())
        self.connection.commit()

    def get_conversation_session(
        self,
        conversation_id: ConversationId,
    ) -> ConversationSessionRecord | None:
        _require_non_empty(conversation_id.value, "conversation_id")
        row = self.connection.execute(
            f"SELECT {', '.join(CONVERSATION_SESSION_COLUMNS)} "
            "FROM platform_conversation_sessions WHERE conversation_id = ?",
            (conversation_id.value,),
        ).fetchone()
        if row is None:
            return None
        return ConversationSessionRecord.from_sqlite_row(
            dict(zip(CONVERSATION_SESSION_COLUMNS, row, strict=True))
        )

    def list_conversation_sessions_by_workspace(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[ConversationSessionRecord, ...]:
        _require_non_empty(workspace_id.value, "workspace_id")
        rows = self.connection.execute(
            f"SELECT {', '.join(CONVERSATION_SESSION_COLUMNS)} "
            "FROM platform_conversation_sessions "
            "WHERE workspace_id = ? "
            "ORDER BY created_at, conversation_id",
            (workspace_id.value,),
        ).fetchall()
        return tuple(
            ConversationSessionRecord.from_sqlite_row(
                dict(zip(CONVERSATION_SESSION_COLUMNS, row, strict=True))
            )
            for row in rows
        )

    def append_conversation_message(
        self,
        *,
        message: ConversationMessage,
        source_event_sequence: int,
    ) -> None:
        record = ConversationMessageRecord(
            message=message,
            source_event_sequence=source_event_sequence,
        )
        self.connection.execute(CONVERSATION_MESSAGE_INSERT_SQL, record.to_sqlite_row())
        self.connection.commit()

    def get_conversation_message(
        self,
        message_id: ConversationMessageId,
    ) -> ConversationMessageRecord | None:
        _require_non_empty(message_id.value, "message_id")
        row = self.connection.execute(
            f"SELECT {', '.join(CONVERSATION_MESSAGE_COLUMNS)} "
            "FROM platform_conversation_messages WHERE message_id = ?",
            (message_id.value,),
        ).fetchone()
        if row is None:
            return None
        return ConversationMessageRecord.from_sqlite_row(
            dict(zip(CONVERSATION_MESSAGE_COLUMNS, row, strict=True))
        )

    def list_conversation_messages(
        self,
        conversation_id: ConversationId,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[ConversationMessageRecord, ...]:
        _require_non_empty(conversation_id.value, "conversation_id")
        if offset < 0:
            raise ValueError("offset must be non-negative.")
        if limit is not None and limit < 1:
            raise ValueError("limit must be a positive integer.")
        sql = (
            f"SELECT {', '.join(CONVERSATION_MESSAGE_COLUMNS)} "
            "FROM platform_conversation_messages "
            "WHERE conversation_id = ? "
            "ORDER BY sequence"
        )
        params: list[object] = [conversation_id.value]
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        elif offset:
            sql += " LIMIT -1 OFFSET ?"
            params.append(offset)
        rows = self.connection.execute(sql, tuple(params)).fetchall()
        return tuple(
            ConversationMessageRecord.from_sqlite_row(
                dict(zip(CONVERSATION_MESSAGE_COLUMNS, row, strict=True))
            )
            for row in rows
        )

    def next_conversation_message_sequence(
        self,
        conversation_id: ConversationId,
    ) -> int:
        _require_non_empty(conversation_id.value, "conversation_id")
        row = self.connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 "
            "FROM platform_conversation_messages WHERE conversation_id = ?",
            (conversation_id.value,),
        ).fetchone()
        return int(row[0])
