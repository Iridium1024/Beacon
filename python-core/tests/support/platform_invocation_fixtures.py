from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Mapping

from agent_os.domain.entities.agent import AgentCapability, AgentRegistration
from agent_os.domain.entities.context import ProjectSharedContext
from agent_os.domain.entities.workspace import ProjectWorkspace
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    ContextId,
    WorkspaceId,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteAgentRegistrationStateStore,
    SqliteContextStateStore,
    SqliteWorkspaceStateStore,
)
from agent_os.infrastructure.persistence.sqlite_persistence import (
    SqlitePlatformPersistence,
)


MINIMAL_WORKSPACE_ID = WorkspaceId("workspace-1")
MINIMAL_CONTEXT_ID = ContextId("context-1")
MINIMAL_AGENT_ID = AgentId("agent-1")
MINIMAL_AGENT_CAPABILITY = "single-turn-status"


def connect_in_memory_platform() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    SqlitePlatformPersistence(connection).initialize()
    return connection


def seed_minimal_invocation_platform_state(
    connection: sqlite3.Connection,
    *,
    materialized_state: Mapping[str, object] | None = None,
) -> None:
    seed_minimal_workspace_state(connection)
    seed_minimal_context_state(
        connection,
        materialized_state=materialized_state,
    )
    seed_minimal_agent_registration_state(connection)


def seed_minimal_workspace_state(connection: sqlite3.Connection) -> None:
    SqliteWorkspaceStateStore(connection).upsert_workspace_state(
        workspace=ProjectWorkspace.create(
            workspace_id=MINIMAL_WORKSPACE_ID,
            display_name="Workspace",
            root_path="X:/fixture/workspace",
        ),
        source_event_sequence=0,
    )


def seed_minimal_context_state(
    connection: sqlite3.Connection,
    *,
    materialized_state: Mapping[str, object] | None = None,
) -> None:
    SqliteContextStateStore(connection).upsert_context_state(
        context=ProjectSharedContext.create(
            context_id=MINIMAL_CONTEXT_ID,
            workspace_id=MINIMAL_WORKSPACE_ID,
            materialized_state=dict(materialized_state or {"status": "open"}),
        ),
        source_event_sequence=0,
    )


def seed_minimal_agent_registration_state(connection: sqlite3.Connection) -> None:
    SqliteAgentRegistrationStateStore(connection).upsert_agent_registration_state(
        registration=AgentRegistration.register(
            agent_id=MINIMAL_AGENT_ID,
            workspace_id=MINIMAL_WORKSPACE_ID,
            name="Runtime Agent",
            description="Handles single-turn status requests",
            capabilities=(
                AgentCapability(
                    name=MINIMAL_AGENT_CAPABILITY,
                    description="Captures single-turn status requests",
                ),
            ),
            created_at=datetime(2026, 6, 4, 7, 0, tzinfo=timezone.utc),
            default_model="deterministic-placeholder",
        ),
        source_event_sequence=0,
    )


def seed_minimal_invocation_platform_database(database: str | Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        SqlitePlatformPersistence(connection).initialize()
        seed_minimal_invocation_platform_state(connection)


def platform_event_count(connection: sqlite3.Connection) -> int:
    value = connection.execute("SELECT COUNT(*) FROM platform_events").fetchone()
    assert value is not None
    return int(value[0])
