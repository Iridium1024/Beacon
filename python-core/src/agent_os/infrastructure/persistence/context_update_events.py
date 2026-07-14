from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import sqlite3
from typing import Mapping, Protocol

from agent_os.domain.entities.context import ContextUpdateInfo, ProjectSharedContext
from agent_os.domain.value_objects.identifiers import (
    PlatformEventId,
    PlatformRunSessionId,
)
from agent_os.infrastructure.persistence.event_log import (
    SQLITE_PLATFORM_EVENT_INSERT_SQL,
    PlatformEventKind,
    PlatformEventRecord,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SQLITE_CONTEXT_STATE_UPSERT_SQL,
    context_state_upsert_row,
)


@dataclass(frozen=True, slots=True)
class RecordedContextUpdate:
    """Result of appending a context update to the event log and current state."""

    context: ProjectSharedContext
    source_event_sequence: int

    def __post_init__(self) -> None:
        if self.source_event_sequence < 1:
            raise ValueError("source_event_sequence must be a positive integer.")


class ContextUpdateEventRecorderPort(Protocol):
    """Event-linked write boundary for canonical project shared-context updates."""

    def record_context_update_event(
        self,
        *,
        context: ProjectSharedContext,
        update: ContextUpdateInfo,
        event_id: PlatformEventId | None = None,
        occurred_at: datetime | None = None,
        session_id: PlatformRunSessionId | None = None,
        metadata: Mapping[str, object] | None = None,
        base_update_count: int | None = None,
    ) -> RecordedContextUpdate:
        ...


@dataclass(slots=True)
class SqliteContextUpdateEventRecorder(ContextUpdateEventRecorderPort):
    """SQLite-backed recorder for context updates and materialized context state."""

    connection: sqlite3.Connection

    def record_context_update_event(
        self,
        *,
        context: ProjectSharedContext,
        update: ContextUpdateInfo,
        event_id: PlatformEventId | None = None,
        occurred_at: datetime | None = None,
        session_id: PlatformRunSessionId | None = None,
        metadata: Mapping[str, object] | None = None,
        base_update_count: int | None = None,
    ) -> RecordedContextUpdate:
        if update.workspace_id != context.workspace_id:
            raise ValueError("context update workspace_id does not match context workspace_id.")
        if base_update_count is not None:
            if base_update_count < 0:
                raise ValueError("base_update_count must be a non-negative integer.")
            if base_update_count < len(context.updates):
                raise ValueError("base_update_count must not be lower than existing updates.")

        updated_context = context.append_update(update)
        update_count = (
            len(updated_context.updates)
            if base_update_count is None
            else base_update_count + 1
        )
        event_record = PlatformEventRecord.create(
            event_id=event_id,
            workspace_id=update.workspace_id,
            session_id=session_id,
            event_kind=PlatformEventKind.CONTEXT_UPDATE_APPENDED,
            aggregate_type="context_update",
            aggregate_id=update.update_id.value,
            occurred_at=occurred_at or update.created_at,
            payload=context_update_event_payload(update),
            metadata=dict(metadata or {}),
        )

        try:
            cursor = self.connection.execute(
                SQLITE_PLATFORM_EVENT_INSERT_SQL,
                event_record.to_sqlite_row(),
            )
            sequence = cursor.lastrowid
            if sequence is None:
                raise RuntimeError("SQLite did not return a platform event sequence.")
            context_row = dict(
                context_state_upsert_row(
                    context=updated_context,
                    source_event_sequence=int(sequence),
                )
            )
            context_row["update_count"] = update_count
            self.connection.execute(
                SQLITE_CONTEXT_STATE_UPSERT_SQL,
                context_row,
            )
        except Exception:
            self.connection.rollback()
            raise

        self.connection.commit()
        return RecordedContextUpdate(
            context=updated_context,
            source_event_sequence=int(sequence),
        )


def context_update_event_payload(update: ContextUpdateInfo) -> Mapping[str, object]:
    """Return the event payload for one canonical context update."""

    payload: dict[str, object] = {
        "update_id": update.update_id.value,
        "workspace_id": update.workspace_id.value,
        "update_kind": update.update_kind.value,
        "summary": update.summary,
        "created_at": update.created_at.isoformat(),
        "source_agent_id": (
            update.source_agent_id.value
            if update.source_agent_id is not None
            else None
        ),
        "payload": dict(update.payload),
        "materialized_state_patch": dict(update.materialized_state_patch),
        "update_metadata": dict(update.metadata),
    }
    return payload
