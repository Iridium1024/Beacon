from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.infrastructure.persistence.invocation_records import (
    AGENT_INVOCATION_RECORD_COLUMNS,
    AGENT_INVOCATION_RECORD_STATUSES,
    PLATFORM_AGENT_INVOCATION_RECORD_TABLES,
    SQLITE_PLATFORM_AGENT_INVOCATION_RECORD_SCHEMA,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SQLITE_PLATFORM_MATERIALIZED_STATE_SCHEMA,
)


SCHEMA = "\n".join(
    (
        SQLITE_PLATFORM_MATERIALIZED_STATE_SCHEMA,
        SQLITE_PLATFORM_AGENT_INVOCATION_RECORD_SCHEMA,
    )
)


class AgentInvocationRecordSchemaTests(unittest.TestCase):
    def test_schema_creates_agent_invocation_record_table(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.executescript(SCHEMA)

        table_names = _table_names(connection)
        invocation_columns = _table_columns(
            connection,
            "platform_agent_invocation_records",
        )

        self.assertEqual(
            set(PLATFORM_AGENT_INVOCATION_RECORD_TABLES),
            table_names - _materialized_table_names(),
        )
        self.assertEqual(set(AGENT_INVOCATION_RECORD_COLUMNS), invocation_columns)

    def test_schema_creates_agent_invocation_query_indexes(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.executescript(SCHEMA)

        indexes = _table_indexes(connection, "platform_agent_invocation_records")

        self.assertIn(
            "idx_platform_agent_invocation_records_workspace_status",
            indexes,
        )
        self.assertIn("idx_platform_agent_invocation_records_agent_status", indexes)
        self.assertIn("idx_platform_agent_invocation_records_task", indexes)
        self.assertIn("idx_platform_agent_invocation_records_source_event", indexes)
        self.assertIn("idx_platform_agent_invocation_records_correlation", indexes)
        self.assertIn("idx_platform_agent_invocation_records_idempotency", indexes)

    def test_schema_defines_allowed_invocation_record_statuses(self) -> None:
        self.assertEqual(
            AGENT_INVOCATION_RECORD_STATUSES,
            ("requested", "succeeded", "failed", "cancelled"),
        )

    def test_invocation_record_requires_workspace_and_agent(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)

        with self.assertRaises(sqlite3.IntegrityError):
            _insert_invocation_record(connection)

        _insert_workspace_state(connection)

        with self.assertRaises(sqlite3.IntegrityError):
            _insert_invocation_record(connection)

        _insert_agent_registration_state(connection)
        _insert_invocation_record(connection)

        count = connection.execute(
            "SELECT COUNT(*) FROM platform_agent_invocation_records"
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_invocation_record_rejects_invalid_source_sequence_and_status_shape(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        _insert_workspace_state(connection)
        _insert_agent_registration_state(connection)

        with self.assertRaises(sqlite3.IntegrityError):
            _insert_invocation_record(
                connection,
                invocation_id="invoke-negative",
                source_event_sequence=-1,
            )

        with self.assertRaises(sqlite3.IntegrityError):
            _insert_invocation_record(
                connection,
                invocation_id="invoke-invalid-status",
                status="running",
            )

        with self.assertRaises(sqlite3.IntegrityError):
            _insert_invocation_record(
                connection,
                invocation_id="invoke-terminal-without-completed-at",
                status="succeeded",
            )

        with self.assertRaises(sqlite3.IntegrityError):
            _insert_invocation_record(
                connection,
                invocation_id="invoke-requested-with-completed-at",
                completed_at="2026-06-03T00:01:00+00:00",
            )

    def test_invocation_record_enforces_workspace_scoped_idempotency_key(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        _insert_workspace_state(connection)
        _insert_agent_registration_state(connection)

        _insert_invocation_record(
            connection,
            invocation_id="invoke-1",
            idempotency_key="request-1",
        )

        with self.assertRaises(sqlite3.IntegrityError):
            _insert_invocation_record(
                connection,
                invocation_id="invoke-2",
                idempotency_key="request-1",
            )


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({table_name})")
    }


def _table_indexes(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        row[1]
        for row in connection.execute(f"PRAGMA index_list({table_name})")
    }


def _materialized_table_names() -> set[str]:
    return {
        "platform_workspace_state",
        "platform_context_state",
        "platform_task_state",
        "platform_issue_state",
        "platform_agent_registration_state",
    }


def _insert_workspace_state(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO platform_workspace_state (
            workspace_id,
            source_event_sequence,
            display_name,
            root_path,
            status,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "workspace-1",
            0,
            "Workspace",
            "X:/fixture/workspace",
            "active",
            "2026-06-03T00:00:00+00:00",
            "2026-06-03T00:00:00+00:00",
        ),
    )


def _insert_agent_registration_state(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO platform_agent_registration_state (
            agent_id,
            workspace_id,
            source_event_sequence,
            name,
            description,
            status,
            capabilities_json,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "agent-1",
            "workspace-1",
            1,
            "Planner",
            "Plans project tasks",
            "active",
            '[{"name":"plan_tasks","description":"Plans tasks","metadata":{}}]',
            "2026-06-03T00:00:00+00:00",
            "2026-06-03T00:00:00+00:00",
        ),
    )


def _insert_invocation_record(
    connection: sqlite3.Connection,
    *,
    invocation_id: str = "invoke-1",
    source_event_sequence: int = 2,
    status: str = "requested",
    idempotency_key: str | None = None,
    completed_at: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO platform_agent_invocation_records (
            invocation_id,
            workspace_id,
            agent_id,
            source_event_sequence,
            status,
            instruction,
            idempotency_key,
            requested_at,
            completed_at,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            invocation_id,
            "workspace-1",
            "agent-1",
            source_event_sequence,
            status,
            "Summarize current task state",
            idempotency_key,
            "2026-06-03T00:00:00+00:00",
            completed_at,
            "2026-06-03T00:00:00+00:00",
            "2026-06-03T00:00:00+00:00",
        ),
    )


if __name__ == "__main__":
    unittest.main()
