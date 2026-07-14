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

from agent_os.domain.entities.agent import (
    AgentCapability,
    AgentRegistration,
    AgentRegistrationStatus,
)
from agent_os.domain.entities.workspace import ProjectWorkspace
from agent_os.domain.value_objects.identifiers import AgentId, WorkspaceId
from agent_os.infrastructure.persistence.materialized_state import (
    AGENT_REGISTRATION_STATE_SELECT_COLUMNS,
    AGENT_REGISTRATION_STATE_UPSERT_COLUMNS,
    AgentRegistrationStateRecord,
    SqliteAgentRegistrationStateStore,
    SqliteWorkspaceStateStore,
    agent_registration_state_upsert_row,
)
from agent_os.infrastructure.persistence.sqlite_persistence import SqlitePlatformPersistence


class AgentRegistrationStateUpsertRowTests(unittest.TestCase):
    def test_agent_registration_state_upsert_row_serializes_domain_object(self) -> None:
        created_at = datetime(2026, 6, 3, 10, 0, tzinfo=timezone.utc)
        registration = AgentRegistration.register(
            agent_id=AgentId("agent-1"),
            workspace_id=WorkspaceId("workspace-1"),
            name="Planner",
            description="Plans bounded project work",
            capabilities=(
                AgentCapability(
                    name="plan_tasks",
                    description="Breaks project requests into tasks",
                    metadata={"kind": "planning"},
                ),
            ),
            created_at=created_at,
            default_model="local/planner",
            tool_permissions=("workspace.read",),
            runtime_config={"temperature": 0},
            metadata={"role": "planner"},
        )

        row = agent_registration_state_upsert_row(
            registration=registration,
            source_event_sequence=17,
        )

        self.assertEqual(tuple(row.keys()), AGENT_REGISTRATION_STATE_UPSERT_COLUMNS)
        self.assertEqual(row["agent_id"], "agent-1")
        self.assertEqual(row["workspace_id"], "workspace-1")
        self.assertEqual(row["source_event_sequence"], 17)
        self.assertEqual(row["name"], "Planner")
        self.assertEqual(row["description"], "Plans bounded project work")
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["default_model"], "local/planner")
        self.assertEqual(
            json.loads(str(row["capabilities_json"]))[0]["name"],
            "plan_tasks",
        )
        self.assertEqual(
            json.loads(str(row["capabilities_json"]))[0]["metadata"]["kind"],
            "planning",
        )
        self.assertEqual(
            json.loads(str(row["tool_permissions_json"])),
            ["workspace.read"],
        )
        self.assertEqual(json.loads(str(row["runtime_config_json"]))["temperature"], 0)
        self.assertEqual(json.loads(str(row["registration_json"]))["agent_id"], "agent-1")
        self.assertEqual(json.loads(str(row["metadata_json"]))["role"], "planner")

    def test_agent_registration_state_upsert_row_rejects_negative_source_sequence(self) -> None:
        registration = _registration()

        with self.assertRaises(ValueError):
            agent_registration_state_upsert_row(
                registration=registration,
                source_event_sequence=-1,
            )


class SqliteAgentRegistrationStateStoreTests(unittest.TestCase):
    def test_upsert_agent_registration_state_inserts_current_registration_row(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteAgentRegistrationStateStore(connection)
        registration = _registration()

        store.upsert_agent_registration_state(
            registration=registration,
            source_event_sequence=1,
        )

        row = connection.execute(
            """
            SELECT agent_id, workspace_id, source_event_sequence, name,
                   description, status, default_model, capabilities_json,
                   tool_permissions_json, runtime_config_json,
                   registration_json, metadata_json
            FROM platform_agent_registration_state
            """
        ).fetchone()

        self.assertEqual(row[0], "agent-1")
        self.assertEqual(row[1], "workspace-1")
        self.assertEqual(row[2], 1)
        self.assertEqual(row[3], "Planner")
        self.assertEqual(row[4], "Plans bounded project work")
        self.assertEqual(row[5], "active")
        self.assertEqual(row[6], "local/planner")
        self.assertEqual(json.loads(row[7])[0]["name"], "plan_tasks")
        self.assertEqual(json.loads(row[8]), ["workspace.read"])
        self.assertEqual(json.loads(row[9])["temperature"], 0)
        self.assertEqual(json.loads(row[10])["agent_id"], "agent-1")
        self.assertEqual(json.loads(row[11])["role"], "planner")

    def test_upsert_agent_registration_state_updates_existing_registration_row(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteAgentRegistrationStateStore(connection)
        registration = _registration()
        updated = registration.with_runtime_config(
            {"temperature": 0, "profile": "disabled"},
            updated_at=datetime(2026, 6, 3, 10, 5, tzinfo=timezone.utc),
        ).with_tool_permissions(
            ("workspace.read", "workspace.write"),
            updated_at=datetime(2026, 6, 3, 10, 10, tzinfo=timezone.utc),
        ).transition(
            AgentRegistrationStatus.DISABLED,
            updated_at=datetime(2026, 6, 3, 10, 15, tzinfo=timezone.utc),
        )

        store.upsert_agent_registration_state(
            registration=registration,
            source_event_sequence=1,
        )
        store.upsert_agent_registration_state(
            registration=updated,
            source_event_sequence=2,
        )

        row = connection.execute(
            """
            SELECT source_event_sequence, status, tool_permissions_json,
                   runtime_config_json, updated_at
            FROM platform_agent_registration_state
            WHERE agent_id = ?
            """,
            ("agent-1",),
        ).fetchone()
        count = connection.execute(
            "SELECT COUNT(*) FROM platform_agent_registration_state"
        ).fetchone()[0]

        self.assertEqual(count, 1)
        self.assertEqual(row[0], 2)
        self.assertEqual(row[1], "disabled")
        self.assertEqual(json.loads(row[2]), ["workspace.read", "workspace.write"])
        self.assertEqual(json.loads(row[3])["profile"], "disabled")
        self.assertEqual(row[4], updated.updated_at.isoformat())

    def test_get_agent_registration_state_returns_current_registration_record(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteAgentRegistrationStateStore(connection)
        updated = _updated_registration()

        store.upsert_agent_registration_state(
            registration=updated,
            source_event_sequence=7,
        )

        record = store.get_agent_registration_state(AgentId("agent-1"))

        self.assertIsInstance(record, AgentRegistrationStateRecord)
        self.assertEqual(record.source_event_sequence, 7)
        self.assertEqual(record.registration.agent_id.value, "agent-1")
        self.assertEqual(record.registration.workspace_id.value, "workspace-1")
        self.assertEqual(record.registration.name, "Planner")
        self.assertEqual(record.registration.status, AgentRegistrationStatus.DISABLED)
        self.assertEqual(record.registration.default_model, "local/planner")
        self.assertEqual(record.registration.capabilities[0].name, "plan_tasks")
        self.assertEqual(
            record.registration.capabilities[0].metadata["kind"],
            "planning",
        )
        self.assertEqual(
            record.registration.tool_permissions,
            ("workspace.read", "workspace.write"),
        )
        self.assertEqual(record.registration.runtime_config["profile"], "disabled")
        self.assertEqual(record.registration.metadata["role"], "planner")
        self.assertEqual(record.registration_state["agent_id"], "agent-1")
        self.assertEqual(record.metadata["role"], "planner")
        self.assertEqual(record.registration.created_at, updated.created_at)
        self.assertEqual(record.registration.updated_at, updated.updated_at)

    def test_get_agent_registration_state_returns_none_for_unknown_agent(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteAgentRegistrationStateStore(connection)

        record = store.get_agent_registration_state(AgentId("missing-agent"))

        self.assertIsNone(record)

    def test_list_agent_registration_states_by_workspace_filters_and_orders(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        _insert_workspace_state(connection, workspace_id="workspace-2")
        store = SqliteAgentRegistrationStateStore(connection)
        store.upsert_agent_registration_state(
            registration=_registration(agent_id="agent-b"),
            source_event_sequence=2,
        )
        store.upsert_agent_registration_state(
            registration=_registration(agent_id="agent-a"),
            source_event_sequence=1,
        )
        store.upsert_agent_registration_state(
            registration=_registration(
                agent_id="agent-other",
                workspace_id="workspace-2",
            ),
            source_event_sequence=3,
        )

        records = store.list_agent_registration_states_by_workspace(
            WorkspaceId("workspace-1")
        )

        self.assertEqual(
            tuple(record.registration.agent_id.value for record in records),
            ("agent-a", "agent-b"),
        )
        self.assertTrue(
            all(
                record.registration.workspace_id == WorkspaceId("workspace-1")
                for record in records
            )
        )

    def test_list_agent_registration_states_by_workspace_returns_empty_tuple(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteAgentRegistrationStateStore(connection)

        records = store.list_agent_registration_states_by_workspace(
            WorkspaceId("workspace-missing")
        )

        self.assertEqual(records, ())

    def test_list_agent_registration_states_by_workspace_rejects_empty_workspace_id(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteAgentRegistrationStateStore(connection)

        with self.assertRaises(ValueError):
            store.list_agent_registration_states_by_workspace(WorkspaceId(" "))

    def test_get_agent_registration_state_rejects_empty_agent_id(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        store = SqliteAgentRegistrationStateStore(connection)

        with self.assertRaises(ValueError):
            store.get_agent_registration_state(AgentId(" "))

    def test_agent_registration_state_record_rehydrates_from_select_row(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteAgentRegistrationStateStore(connection)
        updated = _updated_registration()
        store.upsert_agent_registration_state(
            registration=updated,
            source_event_sequence=8,
        )
        row = connection.execute(
            f"""
            SELECT {', '.join(AGENT_REGISTRATION_STATE_SELECT_COLUMNS)}
            FROM platform_agent_registration_state
            WHERE agent_id = ?
            """,
            ("agent-1",),
        ).fetchone()

        record = AgentRegistrationStateRecord.from_sqlite_row(
            dict(zip(AGENT_REGISTRATION_STATE_SELECT_COLUMNS, row, strict=True))
        )

        self.assertEqual(record.source_event_sequence, 8)
        self.assertEqual(record.registration.agent_id.value, "agent-1")
        self.assertEqual(record.registration.status, AgentRegistrationStatus.DISABLED)
        self.assertEqual(
            record.registration.tool_permissions,
            ("workspace.read", "workspace.write"),
        )
        self.assertEqual(record.registration.runtime_config["profile"], "disabled")
        self.assertEqual(record.registration_state["runtime_config"]["profile"], "disabled")

    def test_upsert_agent_registration_state_rejects_negative_source_sequence(self) -> None:
        connection = sqlite3.connect(":memory:")
        SqlitePlatformPersistence(connection).initialize()
        _insert_workspace_state(connection)
        store = SqliteAgentRegistrationStateStore(connection)

        with self.assertRaises(ValueError):
            store.upsert_agent_registration_state(
                registration=_registration(),
                source_event_sequence=-1,
            )
        count = connection.execute(
            "SELECT COUNT(*) FROM platform_agent_registration_state"
        ).fetchone()[0]
        self.assertEqual(count, 0)


def _registration(
    *,
    agent_id: str = "agent-1",
    workspace_id: str = "workspace-1",
) -> AgentRegistration:
    return AgentRegistration.register(
        agent_id=AgentId(agent_id),
        workspace_id=WorkspaceId(workspace_id),
        name="Planner",
        description="Plans bounded project work",
        capabilities=(
            AgentCapability(
                name="plan_tasks",
                description="Breaks project requests into tasks",
                metadata={"kind": "planning"},
            ),
        ),
        created_at=datetime(2026, 6, 3, 10, 0, tzinfo=timezone.utc),
        default_model="local/planner",
        tool_permissions=("workspace.read",),
        runtime_config={"temperature": 0},
        metadata={"role": "planner"},
    )


def _updated_registration() -> AgentRegistration:
    return _registration().with_runtime_config(
        {"temperature": 0, "profile": "disabled"},
        updated_at=datetime(2026, 6, 3, 10, 5, tzinfo=timezone.utc),
    ).with_tool_permissions(
        ("workspace.read", "workspace.write"),
        updated_at=datetime(2026, 6, 3, 10, 10, tzinfo=timezone.utc),
    ).transition(
        AgentRegistrationStatus.DISABLED,
        updated_at=datetime(2026, 6, 3, 10, 15, tzinfo=timezone.utc),
    )


def _insert_workspace_state(
    connection: sqlite3.Connection,
    *,
    workspace_id: str = "workspace-1",
) -> None:
    workspace = ProjectWorkspace.create(
        workspace_id=WorkspaceId(workspace_id),
        display_name="Workspace",
        root_path=f"X:/fixture/{workspace_id}",
    )
    SqliteWorkspaceStateStore(connection).upsert_workspace_state(
        workspace=workspace,
        source_event_sequence=0,
    )


if __name__ == "__main__":
    unittest.main()
