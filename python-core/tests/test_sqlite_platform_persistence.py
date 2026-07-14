from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.infrastructure.persistence.sqlite_persistence import (
    SQLITE_PLATFORM_PERSISTENCE_SCHEMA,
    SqlitePlatformPersistence,
    configure_sqlite_platform_connection,
)


class SqlitePlatformPersistenceTests(unittest.TestCase):
    def test_initialize_creates_event_log_and_materialized_state_tables(self) -> None:
        persistence = SqlitePlatformPersistence(sqlite3.connect(":memory:"))

        persistence.initialize()

        table_names = _table_names(persistence.connection)
        self.assertIn("platform_events", table_names)
        self.assertIn("platform_workspace_state", table_names)
        self.assertIn("platform_context_state", table_names)
        self.assertIn("platform_task_state", table_names)
        self.assertIn("platform_issue_state", table_names)
        self.assertIn("platform_agent_registration_state", table_names)
        self.assertIn("platform_conversation_sessions", table_names)
        self.assertIn("platform_conversation_messages", table_names)
        self.assertIn("platform_agent_invocation_records", table_names)
        self.assertIn("platform_file_operation_records", table_names)

    def test_initialize_is_idempotent(self) -> None:
        persistence = SqlitePlatformPersistence(sqlite3.connect(":memory:"))

        persistence.initialize()
        persistence.initialize()

        table_names = _table_names(persistence.connection)
        self.assertEqual(
            {
                "platform_events",
                "platform_workspace_state",
                "platform_context_state",
                "platform_task_state",
                "platform_issue_state",
                "platform_agent_registration_state",
                "platform_conversation_sessions",
                "platform_conversation_messages",
                "platform_agent_invocation_records",
                "platform_file_operation_records",
                "sqlite_sequence",
            },
            table_names,
        )

    def test_initialize_enables_foreign_keys_for_connection(self) -> None:
        persistence = SqlitePlatformPersistence(sqlite3.connect(":memory:"))

        persistence.initialize()
        enabled = persistence.connection.execute("PRAGMA foreign_keys").fetchone()[0]

        self.assertEqual(enabled, 1)

    def test_configure_enables_foreign_keys_without_schema_initialization(self) -> None:
        connection = configure_sqlite_platform_connection(sqlite3.connect(":memory:"))

        enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        connection.close()

        self.assertEqual(enabled, 1)

    def test_connect_enables_foreign_keys_before_initialization(self) -> None:
        persistence = SqlitePlatformPersistence.connect(":memory:")

        enabled = persistence.connection.execute("PRAGMA foreign_keys").fetchone()[0]
        persistence.connection.close()

        self.assertEqual(enabled, 1)

    def test_connect_initializes_file_backed_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            database_path = Path(temp_directory) / "platform.sqlite"
            persistence = SqlitePlatformPersistence.connect(database_path)
            persistence.initialize()
            persistence.connection.close()

            reopened = sqlite3.connect(database_path)
            table_names = _table_names(reopened)
            reopened.close()

        self.assertIn("platform_events", table_names)
        self.assertIn("platform_workspace_state", table_names)
        self.assertIn("platform_context_state", table_names)
        self.assertIn("platform_task_state", table_names)
        self.assertIn("platform_issue_state", table_names)
        self.assertIn("platform_agent_registration_state", table_names)
        self.assertIn("platform_conversation_sessions", table_names)
        self.assertIn("platform_conversation_messages", table_names)
        self.assertIn("platform_agent_invocation_records", table_names)
        self.assertIn("platform_file_operation_records", table_names)

    def test_combined_schema_contains_event_and_current_state_contracts(self) -> None:
        self.assertIn("CREATE TABLE IF NOT EXISTS platform_events", SQLITE_PLATFORM_PERSISTENCE_SCHEMA)
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS platform_workspace_state",
            SQLITE_PLATFORM_PERSISTENCE_SCHEMA,
        )
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS platform_context_state",
            SQLITE_PLATFORM_PERSISTENCE_SCHEMA,
        )
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS platform_task_state",
            SQLITE_PLATFORM_PERSISTENCE_SCHEMA,
        )
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS platform_issue_state",
            SQLITE_PLATFORM_PERSISTENCE_SCHEMA,
        )
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS platform_agent_registration_state",
            SQLITE_PLATFORM_PERSISTENCE_SCHEMA,
        )
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS platform_conversation_sessions",
            SQLITE_PLATFORM_PERSISTENCE_SCHEMA,
        )
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS platform_conversation_messages",
            SQLITE_PLATFORM_PERSISTENCE_SCHEMA,
        )
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS platform_agent_invocation_records",
            SQLITE_PLATFORM_PERSISTENCE_SCHEMA,
        )
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS platform_file_operation_records",
            SQLITE_PLATFORM_PERSISTENCE_SCHEMA,
        )


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


if __name__ == "__main__":
    unittest.main()
