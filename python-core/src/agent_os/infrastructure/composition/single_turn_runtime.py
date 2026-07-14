from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import sqlite3
from typing import Mapping

from agent_os.application.services.single_turn_platform_runtime import (
    AgentInvocationAdapterPort,
    DeterministicAgentInvocationAdapter,
    SingleTurnPlatformRuntime,
)
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    PlatformRunSessionId,
    WorkspaceId,
)
from agent_os.infrastructure.persistence.context_update_events import (
    SqliteContextUpdateEventRecorder,
)
from agent_os.infrastructure.persistence.event_log import (
    PlatformEventKind,
    PlatformEventRecord,
    SqlitePlatformEventLog,
)
from agent_os.infrastructure.persistence.invocation_records import (
    SqliteAgentInvocationRecordStore,
)


@dataclass(frozen=True, slots=True)
class SqliteSingleTurnPlatformRuntimeComponents:
    """Concrete SQLite-backed components for the single-turn platform runtime."""

    runtime: SingleTurnPlatformRuntime
    context_update_recorder: SqliteContextUpdateEventRecorder
    agent_invocation_adapter: AgentInvocationAdapterPort
    agent_invocation_recorder: SqliteAgentInvocationRecordStore | None = None
    run_session_lifecycle_recorder: "SqliteRunSessionLifecycleRecorder | None" = None


@dataclass(frozen=True, slots=True)
class SqliteRunSessionLifecycleRecorder:
    """SQLite event-log-backed recorder for local run-session lifecycle events."""

    event_log: SqlitePlatformEventLog

    def record_run_session_event(
        self,
        *,
        workspace_id: WorkspaceId,
        session_id: PlatformRunSessionId,
        status: str,
        occurred_at: datetime,
        agent_id: AgentId | None = None,
        invocation_id: AgentInvocationId | None = None,
        correlation_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> int:
        return self.event_log.append(
            PlatformEventRecord.create(
                workspace_id=workspace_id,
                session_id=session_id,
                event_kind=PlatformEventKind.RUN_SESSION_CHANGED,
                aggregate_type="run_session",
                aggregate_id=session_id.value,
                occurred_at=occurred_at,
                correlation_id=correlation_id,
                payload={
                    "workspace_id": workspace_id.value,
                    "session_id": session_id.value,
                    "status": status,
                    "agent_id": (
                        agent_id.value
                        if agent_id is not None
                        else None
                    ),
                    "invocation_id": (
                        invocation_id.value
                        if invocation_id is not None
                        else None
                    ),
                },
                metadata={
                    "source": "sqlite_run_session_lifecycle_recorder",
                    **dict(metadata or {}),
                },
            )
        )


def build_sqlite_single_turn_platform_runtime(
    connection: sqlite3.Connection,
    *,
    record_agent_invocations: bool = True,
    agent_invocation_adapter: AgentInvocationAdapterPort | None = None,
) -> SqliteSingleTurnPlatformRuntimeComponents:
    """Build a local SQLite-backed single-turn runtime from an existing connection."""

    context_update_recorder = SqliteContextUpdateEventRecorder(connection)
    invocation_recorder = (
        SqliteAgentInvocationRecordStore(connection)
        if record_agent_invocations
        else None
    )
    run_session_lifecycle_recorder = SqliteRunSessionLifecycleRecorder(
        SqlitePlatformEventLog(connection)
    )
    resolved_adapter = agent_invocation_adapter or DeterministicAgentInvocationAdapter()
    runtime = SingleTurnPlatformRuntime(
        context_update_recorder=context_update_recorder,
        agent_invocation_recorder=invocation_recorder,
        run_session_lifecycle_recorder=run_session_lifecycle_recorder,
        agent_invocation_adapter=resolved_adapter,
    )
    return SqliteSingleTurnPlatformRuntimeComponents(
        runtime=runtime,
        context_update_recorder=context_update_recorder,
        agent_invocation_recorder=invocation_recorder,
        run_session_lifecycle_recorder=run_session_lifecycle_recorder,
        agent_invocation_adapter=resolved_adapter,
    )
