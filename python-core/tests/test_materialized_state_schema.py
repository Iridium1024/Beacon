from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.infrastructure.persistence.materialized_state import (
    PLATFORM_MATERIALIZED_STATE_TABLES,
    SQLITE_PLATFORM_MATERIALIZED_STATE_SCHEMA,
)


class PlatformMaterializedStateSchemaTests(unittest.TestCase):
    def test_schema_creates_workspace_context_task_issue_and_agent_state_tables(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.executescript(SQLITE_PLATFORM_MATERIALIZED_STATE_SCHEMA)

        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        workspace_columns = _table_columns(connection, "platform_workspace_state")
        context_columns = _table_columns(connection, "platform_context_state")
        task_columns = _table_columns(connection, "platform_task_state")
        issue_columns = _table_columns(connection, "platform_issue_state")
        agent_columns = _table_columns(connection, "platform_agent_registration_state")

        self.assertEqual(set(PLATFORM_MATERIALIZED_STATE_TABLES), table_names)
        self.assertIn("workspace_id", workspace_columns)
        self.assertIn("source_event_sequence", workspace_columns)
        self.assertIn("workspace_json", workspace_columns)
        self.assertIn("binding_json", workspace_columns)
        self.assertIn("workspace_id", context_columns)
        self.assertIn("context_id", context_columns)
        self.assertIn("update_count", context_columns)
        self.assertIn("materialized_state_json", context_columns)
        self.assertIn("task_id", task_columns)
        self.assertIn("workspace_id", task_columns)
        self.assertIn("source_event_sequence", task_columns)
        self.assertIn("title", task_columns)
        self.assertIn("status", task_columns)
        self.assertIn("assignee_agent_id", task_columns)
        self.assertIn("context_update_ids_json", task_columns)
        self.assertIn("linked_file_paths_json", task_columns)
        self.assertIn("task_json", task_columns)
        self.assertIn("metadata_json", task_columns)
        self.assertIn("issue_id", issue_columns)
        self.assertIn("workspace_id", issue_columns)
        self.assertIn("source_event_sequence", issue_columns)
        self.assertIn("title", issue_columns)
        self.assertIn("status", issue_columns)
        self.assertIn("severity", issue_columns)
        self.assertIn("linked_task_id", issue_columns)
        self.assertIn("context_update_ids_json", issue_columns)
        self.assertIn("linked_file_paths_json", issue_columns)
        self.assertIn("issue_json", issue_columns)
        self.assertIn("metadata_json", issue_columns)
        self.assertIn("agent_id", agent_columns)
        self.assertIn("workspace_id", agent_columns)
        self.assertIn("source_event_sequence", agent_columns)
        self.assertIn("name", agent_columns)
        self.assertIn("description", agent_columns)
        self.assertIn("status", agent_columns)
        self.assertIn("default_model", agent_columns)
        self.assertIn("capabilities_json", agent_columns)
        self.assertIn("tool_permissions_json", agent_columns)
        self.assertIn("runtime_config_json", agent_columns)
        self.assertIn("registration_json", agent_columns)
        self.assertIn("metadata_json", agent_columns)

    def test_schema_creates_query_indexes(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.executescript(SQLITE_PLATFORM_MATERIALIZED_STATE_SCHEMA)

        workspace_indexes = _table_indexes(connection, "platform_workspace_state")
        context_indexes = _table_indexes(connection, "platform_context_state")
        task_indexes = _table_indexes(connection, "platform_task_state")
        issue_indexes = _table_indexes(connection, "platform_issue_state")
        agent_indexes = _table_indexes(connection, "platform_agent_registration_state")

        self.assertIn("idx_platform_workspace_state_status", workspace_indexes)
        self.assertIn("idx_platform_context_state_source_event", context_indexes)
        self.assertIn("idx_platform_task_state_workspace_status", task_indexes)
        self.assertIn("idx_platform_task_state_source_event", task_indexes)
        self.assertIn("idx_platform_task_state_assignee", task_indexes)
        self.assertIn("idx_platform_issue_state_workspace_status", issue_indexes)
        self.assertIn("idx_platform_issue_state_source_event", issue_indexes)
        self.assertIn("idx_platform_issue_state_severity", issue_indexes)
        self.assertIn("idx_platform_issue_state_linked_task", issue_indexes)
        self.assertIn("idx_platform_agent_registration_state_workspace_status", agent_indexes)
        self.assertIn("idx_platform_agent_registration_state_source_event", agent_indexes)
        self.assertIn("idx_platform_agent_registration_state_default_model", agent_indexes)

    def test_workspace_state_rejects_negative_source_event_sequence(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.executescript(SQLITE_PLATFORM_MATERIALIZED_STATE_SCHEMA)

        with self.assertRaises(sqlite3.IntegrityError):
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
                    -1,
                    "Workspace",
                    "X:/fixture/workspace",
                    "active",
                    "2026-06-03T00:00:00+00:00",
                    "2026-06-03T00:00:00+00:00",
                ),
            )

    def test_task_state_requires_workspace_and_non_negative_source_sequence(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SQLITE_PLATFORM_MATERIALIZED_STATE_SCHEMA)

        with self.assertRaises(sqlite3.IntegrityError):
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
                    "workspace-missing",
                    0,
                    "Define task persistence",
                    "open",
                    "2026-06-03T00:00:00+00:00",
                    "2026-06-03T00:00:00+00:00",
                ),
            )

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

        with self.assertRaises(sqlite3.IntegrityError):
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
                    -1,
                    "Define task persistence",
                    "open",
                    "2026-06-03T00:00:00+00:00",
                    "2026-06-03T00:00:00+00:00",
                ),
            )

    def test_context_state_requires_workspace_and_non_negative_update_count(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SQLITE_PLATFORM_MATERIALIZED_STATE_SCHEMA)

        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO platform_context_state (
                    workspace_id,
                    context_id,
                    source_event_sequence,
                    update_count,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "workspace-missing",
                    "context-1",
                    0,
                    0,
                    "2026-06-03T00:00:00+00:00",
                    "2026-06-03T00:00:00+00:00",
                ),
            )

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

        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO platform_context_state (
                    workspace_id,
                    context_id,
                    source_event_sequence,
                    update_count,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "workspace-1",
                    "context-1",
                    0,
                    -1,
                    "2026-06-03T00:00:00+00:00",
                    "2026-06-03T00:00:00+00:00",
                ),
            )

    def test_issue_state_requires_workspace_and_non_negative_source_sequence(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SQLITE_PLATFORM_MATERIALIZED_STATE_SCHEMA)

        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO platform_issue_state (
                    issue_id,
                    workspace_id,
                    source_event_sequence,
                    title,
                    status,
                    severity,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "issue-1",
                    "workspace-missing",
                    0,
                    "Track issue persistence",
                    "open",
                    "medium",
                    "2026-06-03T00:00:00+00:00",
                    "2026-06-03T00:00:00+00:00",
                ),
            )

        _insert_workspace_state(connection)

        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO platform_issue_state (
                    issue_id,
                    workspace_id,
                    source_event_sequence,
                    title,
                    status,
                    severity,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "issue-1",
                    "workspace-1",
                    -1,
                    "Track issue persistence",
                    "open",
                    "medium",
                    "2026-06-03T00:00:00+00:00",
                    "2026-06-03T00:00:00+00:00",
                ),
            )

    def test_agent_registration_state_requires_workspace_and_non_negative_source_sequence(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SQLITE_PLATFORM_MATERIALIZED_STATE_SCHEMA)

        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO platform_agent_registration_state (
                    agent_id,
                    workspace_id,
                    source_event_sequence,
                    name,
                    description,
                    status,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "agent-1",
                    "workspace-missing",
                    0,
                    "Planner",
                    "Plans project tasks",
                    "active",
                    "2026-06-03T00:00:00+00:00",
                    "2026-06-03T00:00:00+00:00",
                ),
            )

        _insert_workspace_state(connection)

        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO platform_agent_registration_state (
                    agent_id,
                    workspace_id,
                    source_event_sequence,
                    name,
                    description,
                    status,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "agent-1",
                    "workspace-1",
                    -1,
                    "Planner",
                    "Plans project tasks",
                    "active",
                    "2026-06-03T00:00:00+00:00",
                    "2026-06-03T00:00:00+00:00",
                ),
            )


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


if __name__ == "__main__":
    unittest.main()
