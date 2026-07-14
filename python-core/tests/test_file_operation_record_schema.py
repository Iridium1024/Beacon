from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.infrastructure.persistence.file_operation_records import (
    FILE_OPERATION_RECORD_COLUMNS,
    FILE_OPERATION_RECORD_KINDS,
    FILE_OPERATION_RECORD_STATUSES,
    PLATFORM_FILE_OPERATION_RECORD_TABLES,
    SQLITE_PLATFORM_FILE_OPERATION_RECORD_SCHEMA,
)
from agent_os.infrastructure.persistence.invocation_records import (
    SQLITE_PLATFORM_AGENT_INVOCATION_RECORD_SCHEMA,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SQLITE_PLATFORM_MATERIALIZED_STATE_SCHEMA,
)


SCHEMA = "\n".join(
    (
        SQLITE_PLATFORM_MATERIALIZED_STATE_SCHEMA,
        SQLITE_PLATFORM_AGENT_INVOCATION_RECORD_SCHEMA,
        SQLITE_PLATFORM_FILE_OPERATION_RECORD_SCHEMA,
    )
)


class FileOperationRecordSchemaTests(unittest.TestCase):
    def test_schema_creates_file_operation_record_table(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.executescript(SCHEMA)

        table_names = _table_names(connection)
        file_operation_columns = _table_columns(
            connection,
            "platform_file_operation_records",
        )

        self.assertEqual(
            set(PLATFORM_FILE_OPERATION_RECORD_TABLES),
            table_names
            - _materialized_table_names()
            - {"platform_agent_invocation_records"},
        )
        self.assertEqual(set(FILE_OPERATION_RECORD_COLUMNS), file_operation_columns)

    def test_schema_creates_file_operation_query_indexes(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.executescript(SCHEMA)

        indexes = _table_indexes(connection, "platform_file_operation_records")

        self.assertIn(
            "idx_platform_file_operation_records_workspace_status",
            indexes,
        )
        self.assertIn(
            "idx_platform_file_operation_records_workspace_kind",
            indexes,
        )
        self.assertIn("idx_platform_file_operation_records_invocation", indexes)
        self.assertIn("idx_platform_file_operation_records_task", indexes)
        self.assertIn("idx_platform_file_operation_records_agent", indexes)
        self.assertIn("idx_platform_file_operation_records_context_update", indexes)
        self.assertIn("idx_platform_file_operation_records_source_event", indexes)

    def test_schema_defines_allowed_file_operation_kinds_and_statuses(self) -> None:
        self.assertEqual(
            FILE_OPERATION_RECORD_KINDS,
            ("read_file", "write_file", "list_directory"),
        )
        self.assertEqual(
            FILE_OPERATION_RECORD_STATUSES,
            ("requested", "succeeded", "failed", "denied"),
        )

    def test_file_operation_record_requires_workspace(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)

        with self.assertRaises(sqlite3.IntegrityError):
            _insert_file_operation_record(connection)

        _insert_workspace_state(connection)
        _insert_file_operation_record(connection)

        count = connection.execute(
            "SELECT COUNT(*) FROM platform_file_operation_records"
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_file_operation_record_rejects_invalid_sequence_kind_and_status_shape(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        _insert_workspace_state(connection)

        with self.assertRaises(sqlite3.IntegrityError):
            _insert_file_operation_record(
                connection,
                operation_id="file-op-negative-sequence",
                source_event_sequence=-1,
            )

        with self.assertRaises(sqlite3.IntegrityError):
            _insert_file_operation_record(
                connection,
                operation_id="file-op-bad-kind",
                operation_kind="delete_file",
            )

        with self.assertRaises(sqlite3.IntegrityError):
            _insert_file_operation_record(
                connection,
                operation_id="file-op-bad-status",
                status="running",
            )

        with self.assertRaises(sqlite3.IntegrityError):
            _insert_file_operation_record(
                connection,
                operation_id="file-op-terminal-without-completed-at",
                status="succeeded",
            )

        with self.assertRaises(sqlite3.IntegrityError):
            _insert_file_operation_record(
                connection,
                operation_id="file-op-requested-with-completed-at",
                completed_at="2026-06-03T00:01:00+00:00",
            )

    def test_file_operation_record_rejects_invalid_byte_and_error_shapes(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        _insert_workspace_state(connection)

        with self.assertRaises(sqlite3.IntegrityError):
            _insert_file_operation_record(
                connection,
                operation_id="file-op-negative-bytes-read",
                status="succeeded",
                completed_at="2026-06-03T00:01:00+00:00",
                bytes_read=-1,
            )

        with self.assertRaises(sqlite3.IntegrityError):
            _insert_file_operation_record(
                connection,
                operation_id="file-op-write-with-bytes-read",
                operation_kind="write_file",
                status="succeeded",
                completed_at="2026-06-03T00:01:00+00:00",
                bytes_read=4,
            )

        with self.assertRaises(sqlite3.IntegrityError):
            _insert_file_operation_record(
                connection,
                operation_id="file-op-read-with-bytes-written",
                status="succeeded",
                completed_at="2026-06-03T00:01:00+00:00",
                bytes_written=4,
            )

        with self.assertRaises(sqlite3.IntegrityError):
            _insert_file_operation_record(
                connection,
                operation_id="file-op-failed-without-error",
                status="failed",
                completed_at="2026-06-03T00:01:00+00:00",
            )

        with self.assertRaises(sqlite3.IntegrityError):
            _insert_file_operation_record(
                connection,
                operation_id="file-op-succeeded-with-error",
                status="succeeded",
                completed_at="2026-06-03T00:01:00+00:00",
                error_message="unexpected",
            )

    def test_file_operation_record_allows_optional_agent_invocation_and_task_links(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        _insert_workspace_state(connection)
        _insert_task_state(connection)
        _insert_agent_registration_state(connection)
        _insert_invocation_record(connection)

        _insert_file_operation_record(
            connection,
            requested_by_agent_id="agent-1",
            invocation_id="invoke-1",
            task_id="task-1",
            context_update_id="context-update-1",
        )

        row = connection.execute(
            """
            SELECT requested_by_agent_id, invocation_id, task_id, context_update_id
            FROM platform_file_operation_records
            WHERE operation_id = ?
            """,
            ("file-op-1",),
        ).fetchone()

        self.assertEqual(row, ("agent-1", "invoke-1", "task-1", "context-update-1"))


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


def _insert_task_state(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO platform_task_state (
            task_id,
            workspace_id,
            source_event_sequence,
            title,
            status,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "task-1",
            "workspace-1",
            1,
            "Inspect workspace file",
            "open",
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


def _insert_invocation_record(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO platform_agent_invocation_records (
            invocation_id,
            workspace_id,
            agent_id,
            source_event_sequence,
            status,
            instruction,
            requested_at,
            completed_at,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "invoke-1",
            "workspace-1",
            "agent-1",
            2,
            "requested",
            "Inspect workspace file",
            "2026-06-03T00:00:00+00:00",
            None,
            "2026-06-03T00:00:00+00:00",
            "2026-06-03T00:00:00+00:00",
        ),
    )


def _insert_file_operation_record(
    connection: sqlite3.Connection,
    *,
    operation_id: str = "file-op-1",
    source_event_sequence: int = 3,
    operation_kind: str = "read_file",
    status: str = "requested",
    requested_by_agent_id: str | None = None,
    invocation_id: str | None = None,
    task_id: str | None = None,
    context_update_id: str | None = None,
    completed_at: str | None = None,
    bytes_read: int | None = None,
    bytes_written: int | None = None,
    error_message: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO platform_file_operation_records (
            operation_id,
            workspace_id,
            source_event_sequence,
            operation_kind,
            relative_path,
            status,
            requested_by_agent_id,
            invocation_id,
            task_id,
            context_update_id,
            requested_at,
            completed_at,
            bytes_read,
            bytes_written,
            error_message,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            operation_id,
            "workspace-1",
            source_event_sequence,
            operation_kind,
            "docs/state_snapshot_fixture.json",
            status,
            requested_by_agent_id,
            invocation_id,
            task_id,
            context_update_id,
            "2026-06-03T00:00:00+00:00",
            completed_at,
            bytes_read,
            bytes_written,
            error_message,
            "2026-06-03T00:00:00+00:00",
            "2026-06-03T00:00:00+00:00",
        ),
    )


if __name__ == "__main__":
    unittest.main()
