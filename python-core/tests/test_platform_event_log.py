from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.domain.value_objects.identifiers import (
    PlatformEventId,
    PlatformRunSessionId,
    WorkspaceId,
)
from agent_os.infrastructure.persistence.event_log import (
    PLATFORM_EVENT_INSERT_COLUMNS,
    SQLITE_PLATFORM_EVENT_LOG_SCHEMA,
    PlatformEventLogEntry,
    PlatformEventKind,
    PlatformEventRecord,
    SqlitePlatformEventLog,
)


class PlatformEventLogSchemaTests(unittest.TestCase):
    def test_schema_creates_append_only_event_table_and_indexes(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.executescript(SQLITE_PLATFORM_EVENT_LOG_SCHEMA)

        columns = {
            row[1]: row[2]
            for row in connection.execute("PRAGMA table_info(platform_events)")
        }
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(platform_events)")
        }

        self.assertEqual(columns["sequence"].upper(), "INTEGER")
        self.assertEqual(columns["event_id"].upper(), "TEXT")
        self.assertEqual(columns["workspace_id"].upper(), "TEXT")
        self.assertEqual(columns["event_kind"].upper(), "TEXT")
        self.assertEqual(columns["payload_json"].upper(), "TEXT")
        self.assertIn("idx_platform_events_workspace_sequence", indexes)
        self.assertIn("idx_platform_events_session_sequence", indexes)
        self.assertIn("idx_platform_events_aggregate_sequence", indexes)

    def test_record_rows_insert_with_monotonic_sequence(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.executescript(SQLITE_PLATFORM_EVENT_LOG_SCHEMA)
        first = PlatformEventRecord.create(
            event_id=PlatformEventId("event-1"),
            workspace_id=WorkspaceId("workspace-1"),
            event_kind=PlatformEventKind.CONTEXT_UPDATE_APPENDED,
            aggregate_type="context_update",
            aggregate_id="update-1",
            occurred_at=datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc),
        )
        second = PlatformEventRecord.create(
            event_id=PlatformEventId("event-2"),
            workspace_id=WorkspaceId("workspace-1"),
            event_kind=PlatformEventKind.RUN_SESSION_CHANGED,
            aggregate_type="run_session",
            aggregate_id="session-1",
            occurred_at=datetime(2026, 6, 2, 10, 1, tzinfo=timezone.utc),
        )

        insert_sql = _insert_sql()
        connection.execute(insert_sql, first.to_sqlite_row())
        connection.execute(insert_sql, second.to_sqlite_row())
        sequences = tuple(
            row[0]
            for row in connection.execute(
                "SELECT sequence FROM platform_events ORDER BY sequence"
            )
        )

        self.assertEqual(sequences, (1, 2))


class PlatformEventRecordTests(unittest.TestCase):
    def test_create_event_record_serializes_sqlite_row(self) -> None:
        timestamp = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)

        record = PlatformEventRecord.create(
            event_id=PlatformEventId("event-1"),
            workspace_id=WorkspaceId("workspace-1"),
            session_id=PlatformRunSessionId("session-1"),
            event_kind=PlatformEventKind.AGENT_INVOCATION_RECORDED,
            aggregate_type="agent_invocation",
            aggregate_id="invoke-1",
            occurred_at=timestamp,
            correlation_id="corr-1",
            idempotency_key="idem-1",
            payload={"status": "succeeded"},
            metadata={"source": "test"},
        )

        row = record.to_sqlite_row()

        self.assertEqual(tuple(row.keys()), PLATFORM_EVENT_INSERT_COLUMNS)
        self.assertEqual(row["event_id"], "event-1")
        self.assertEqual(row["workspace_id"], "workspace-1")
        self.assertEqual(row["session_id"], "session-1")
        self.assertEqual(row["event_kind"], "agent_invocation.recorded")
        self.assertEqual(row["aggregate_type"], "agent_invocation")
        self.assertEqual(row["aggregate_id"], "invoke-1")
        self.assertEqual(row["occurred_at"], timestamp.isoformat())
        self.assertEqual(json.loads(str(row["payload_json"]))["status"], "succeeded")
        self.assertEqual(json.loads(str(row["metadata_json"]))["source"], "test")

    def test_event_record_rejects_empty_fields_and_naive_time(self) -> None:
        with self.assertRaises(ValueError):
            PlatformEventRecord.create(
                event_id=PlatformEventId("event-1"),
                workspace_id=WorkspaceId("workspace-1"),
                event_kind=PlatformEventKind.WORKSPACE_CHANGED,
                aggregate_type=" ",
                aggregate_id="workspace-1",
            )

        with self.assertRaises(ValueError):
            PlatformEventRecord.create(
                event_id=PlatformEventId("event-1"),
                workspace_id=WorkspaceId("workspace-1"),
                event_kind=PlatformEventKind.WORKSPACE_CHANGED,
                aggregate_type="workspace",
                aggregate_id="workspace-1",
                occurred_at=datetime(2026, 6, 2, 10, 0),
            )

    def test_event_record_rejects_non_json_payloads(self) -> None:
        with self.assertRaises(TypeError):
            PlatformEventRecord.create(
                event_id=PlatformEventId("event-1"),
                workspace_id=WorkspaceId("workspace-1"),
                event_kind=PlatformEventKind.WORKSPACE_CHANGED,
                aggregate_type="workspace",
                aggregate_id="workspace-1",
                payload={"bad": object()},
            )


class SqlitePlatformEventLogTests(unittest.TestCase):
    def test_initialize_and_append_persists_event_with_sequence(self) -> None:
        event_log = SqlitePlatformEventLog(sqlite3.connect(":memory:"))
        event_log.initialize()

        sequence = event_log.append(
            PlatformEventRecord.create(
                event_id=PlatformEventId("event-1"),
                workspace_id=WorkspaceId("workspace-1"),
                event_kind=PlatformEventKind.CONTEXT_UPDATE_APPENDED,
                aggregate_type="context_update",
                aggregate_id="update-1",
                occurred_at=datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc),
                payload={"body": "stored"},
            )
        )

        row = event_log.connection.execute(
            "SELECT sequence, event_id, workspace_id, event_kind, payload_json "
            "FROM platform_events"
        ).fetchone()

        self.assertEqual(sequence, 1)
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], "event-1")
        self.assertEqual(row[2], "workspace-1")
        self.assertEqual(row[3], "context.update_appended")
        self.assertEqual(json.loads(row[4])["body"], "stored")

    def test_append_returns_monotonic_sequences(self) -> None:
        event_log = SqlitePlatformEventLog(sqlite3.connect(":memory:"))
        event_log.initialize()

        first_sequence = event_log.append(
            PlatformEventRecord.create(
                event_id=PlatformEventId("event-1"),
                workspace_id=WorkspaceId("workspace-1"),
                event_kind=PlatformEventKind.WORKSPACE_CHANGED,
                aggregate_type="workspace",
                aggregate_id="workspace-1",
            )
        )
        second_sequence = event_log.append(
            PlatformEventRecord.create(
                event_id=PlatformEventId("event-2"),
                workspace_id=WorkspaceId("workspace-1"),
                event_kind=PlatformEventKind.RUN_SESSION_CHANGED,
                aggregate_type="run_session",
                aggregate_id="session-1",
            )
        )

        self.assertEqual((first_sequence, second_sequence), (1, 2))

    def test_connect_initializes_file_backed_event_log(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as temp_directory:
            database_path = Path(temp_directory) / "events.sqlite"
            event_log = SqlitePlatformEventLog.connect(database_path)
            event_log.initialize()
            sequence = event_log.append(
                PlatformEventRecord.create(
                    event_id=PlatformEventId("event-1"),
                    workspace_id=WorkspaceId("workspace-1"),
                    event_kind=PlatformEventKind.FILE_OPERATION_RECORDED,
                    aggregate_type="file_operation",
                    aggregate_id="file-operation-1",
                )
            )
            event_log.connection.close()

            reopened = sqlite3.connect(database_path)
            count = reopened.execute("SELECT COUNT(*) FROM platform_events").fetchone()[0]
            reopened.close()

        self.assertEqual(sequence, 1)
        self.assertEqual(count, 1)

    def test_list_workspace_events_returns_requested_workspace_in_sequence_order(self) -> None:
        event_log = SqlitePlatformEventLog(sqlite3.connect(":memory:"))
        event_log.initialize()
        workspace = WorkspaceId("workspace-1")

        event_log.append(
            PlatformEventRecord.create(
                event_id=PlatformEventId("event-1"),
                workspace_id=workspace,
                event_kind=PlatformEventKind.WORKSPACE_CHANGED,
                aggregate_type="workspace",
                aggregate_id="workspace-1",
                payload={"position": 1},
            )
        )
        event_log.append(
            PlatformEventRecord.create(
                event_id=PlatformEventId("event-2"),
                workspace_id=WorkspaceId("workspace-2"),
                event_kind=PlatformEventKind.WORKSPACE_CHANGED,
                aggregate_type="workspace",
                aggregate_id="workspace-2",
                payload={"position": 2},
            )
        )
        event_log.append(
            PlatformEventRecord.create(
                event_id=PlatformEventId("event-3"),
                workspace_id=workspace,
                event_kind=PlatformEventKind.CONTEXT_UPDATE_APPENDED,
                aggregate_type="context_update",
                aggregate_id="update-1",
                payload={"position": 3},
            )
        )

        entries = event_log.list_workspace_events(workspace)

        self.assertEqual(tuple(entry.sequence for entry in entries), (1, 3))
        self.assertEqual(
            tuple(entry.record.event_id.value for entry in entries),
            ("event-1", "event-3"),
        )
        self.assertEqual(entries[1].record.payload["position"], 3)

    def test_list_workspace_events_rehydrates_optional_fields_and_json(self) -> None:
        event_log = SqlitePlatformEventLog(sqlite3.connect(":memory:"))
        event_log.initialize()
        timestamp = datetime(2026, 6, 2, 14, 0, tzinfo=timezone.utc)

        event_log.append(
            PlatformEventRecord.create(
                event_id=PlatformEventId("event-1"),
                workspace_id=WorkspaceId("workspace-1"),
                session_id=PlatformRunSessionId("session-1"),
                event_kind=PlatformEventKind.AGENT_INVOCATION_RECORDED,
                aggregate_type="agent_invocation",
                aggregate_id="invoke-1",
                occurred_at=timestamp,
                correlation_id="corr-1",
                idempotency_key="idem-1",
                payload={"status": "succeeded"},
                metadata={"source": "unit-test"},
            )
        )

        (entry,) = event_log.list_workspace_events(WorkspaceId("workspace-1"))
        record = entry.record

        self.assertEqual(entry.sequence, 1)
        self.assertEqual(record.session_id.value, "session-1")
        self.assertEqual(record.event_kind, PlatformEventKind.AGENT_INVOCATION_RECORDED)
        self.assertEqual(record.occurred_at, timestamp)
        self.assertEqual(record.correlation_id, "corr-1")
        self.assertEqual(record.idempotency_key, "idem-1")
        self.assertEqual(record.payload["status"], "succeeded")
        self.assertEqual(record.metadata["source"], "unit-test")

    def test_list_workspace_events_returns_empty_tuple_for_unknown_workspace(self) -> None:
        event_log = SqlitePlatformEventLog(sqlite3.connect(":memory:"))
        event_log.initialize()
        event_log.append(
            PlatformEventRecord.create(
                event_id=PlatformEventId("event-1"),
                workspace_id=WorkspaceId("workspace-1"),
                event_kind=PlatformEventKind.WORKSPACE_CHANGED,
                aggregate_type="workspace",
                aggregate_id="workspace-1",
            )
        )

        self.assertEqual(
            event_log.list_workspace_events(WorkspaceId("workspace-missing")),
            (),
        )

    def test_list_session_events_returns_requested_session_in_sequence_order(self) -> None:
        event_log = SqlitePlatformEventLog(sqlite3.connect(":memory:"))
        event_log.initialize()
        workspace = WorkspaceId("workspace-1")
        session = PlatformRunSessionId("session-1")

        event_log.append(
            PlatformEventRecord.create(
                event_id=PlatformEventId("event-1"),
                workspace_id=workspace,
                session_id=session,
                event_kind=PlatformEventKind.RUN_SESSION_CHANGED,
                aggregate_type="run_session",
                aggregate_id="session-1",
                payload={"status": "running"},
            )
        )
        event_log.append(
            PlatformEventRecord.create(
                event_id=PlatformEventId("event-2"),
                workspace_id=workspace,
                session_id=PlatformRunSessionId("session-2"),
                event_kind=PlatformEventKind.AGENT_INVOCATION_RECORDED,
                aggregate_type="agent_invocation",
                aggregate_id="invoke-2",
            )
        )
        event_log.append(
            PlatformEventRecord.create(
                event_id=PlatformEventId("event-3"),
                workspace_id=workspace,
                session_id=session,
                event_kind=PlatformEventKind.CONTEXT_UPDATE_APPENDED,
                aggregate_type="context_update",
                aggregate_id="update-1",
            )
        )

        entries = event_log.list_session_events(
            workspace_id=workspace,
            session_id=session,
        )

        self.assertEqual(tuple(entry.sequence for entry in entries), (1, 3))
        self.assertEqual(
            tuple(entry.record.event_id.value for entry in entries),
            ("event-1", "event-3"),
        )
        self.assertEqual(entries[0].record.payload["status"], "running")

    def test_list_session_events_returns_empty_tuple_for_unknown_session(self) -> None:
        event_log = SqlitePlatformEventLog(sqlite3.connect(":memory:"))
        event_log.initialize()
        event_log.append(
            PlatformEventRecord.create(
                event_id=PlatformEventId("event-1"),
                workspace_id=WorkspaceId("workspace-1"),
                session_id=PlatformRunSessionId("session-1"),
                event_kind=PlatformEventKind.RUN_SESSION_CHANGED,
                aggregate_type="run_session",
                aggregate_id="session-1",
            )
        )

        self.assertEqual(
            event_log.list_session_events(
                workspace_id=WorkspaceId("workspace-1"),
                session_id=PlatformRunSessionId("session-missing"),
            ),
            (),
        )


class PlatformEventLogEntryTests(unittest.TestCase):
    def test_entry_rejects_non_positive_sequence(self) -> None:
        record = PlatformEventRecord.create(
            event_id=PlatformEventId("event-1"),
            workspace_id=WorkspaceId("workspace-1"),
            event_kind=PlatformEventKind.WORKSPACE_CHANGED,
            aggregate_type="workspace",
            aggregate_id="workspace-1",
        )

        with self.assertRaises(ValueError):
            PlatformEventLogEntry(sequence=0, record=record)


def _insert_sql() -> str:
    columns = ", ".join(PLATFORM_EVENT_INSERT_COLUMNS)
    parameters = ", ".join(f":{column}" for column in PLATFORM_EVENT_INSERT_COLUMNS)
    return f"INSERT INTO platform_events ({columns}) VALUES ({parameters})"


if __name__ == "__main__":
    unittest.main()
