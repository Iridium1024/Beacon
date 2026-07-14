from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Self

from agent_os.infrastructure.persistence.event_log import SQLITE_PLATFORM_EVENT_LOG_SCHEMA
from agent_os.infrastructure.persistence.conversations import (
    SQLITE_PLATFORM_CONVERSATION_SCHEMA,
)
from agent_os.infrastructure.persistence.file_operation_records import (
    SQLITE_PLATFORM_FILE_OPERATION_RECORD_SCHEMA,
)
from agent_os.infrastructure.persistence.invocation_records import (
    SQLITE_PLATFORM_AGENT_INVOCATION_RECORD_SCHEMA,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SQLITE_PLATFORM_MATERIALIZED_STATE_SCHEMA,
)


SQLITE_PLATFORM_PERSISTENCE_SCHEMA = "\n".join(
    (
        SQLITE_PLATFORM_EVENT_LOG_SCHEMA,
        SQLITE_PLATFORM_MATERIALIZED_STATE_SCHEMA,
        SQLITE_PLATFORM_CONVERSATION_SCHEMA,
        SQLITE_PLATFORM_AGENT_INVOCATION_RECORD_SCHEMA,
        SQLITE_PLATFORM_FILE_OPERATION_RECORD_SCHEMA,
    )
)


def configure_sqlite_platform_connection(
    connection: sqlite3.Connection,
) -> sqlite3.Connection:
    """Apply platform-required connection-level SQLite settings."""

    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@dataclass(slots=True)
class SqlitePlatformPersistence:
    """Initializes the SQLite persistence schema for platform storage."""

    connection: sqlite3.Connection

    @classmethod
    def connect(cls, database: str | Path) -> Self:
        return cls(configure_sqlite_platform_connection(sqlite3.connect(database)))

    def initialize(self) -> None:
        configure_sqlite_platform_connection(self.connection)
        self.connection.executescript(SQLITE_PLATFORM_PERSISTENCE_SCHEMA)
        self.connection.commit()
