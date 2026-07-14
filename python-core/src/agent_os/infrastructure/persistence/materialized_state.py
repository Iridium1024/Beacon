from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import sqlite3
from typing import Mapping, Protocol

from agent_os.domain.entities.agent import (
    AgentCapability,
    AgentRegistration,
    AgentRegistrationStatus,
)
from agent_os.domain.entities.context import ProjectSharedContext
from agent_os.domain.entities.task import (
    IssueContext,
    IssueSeverity,
    IssueStatus,
    TaskContext,
    TaskStatus,
)
from agent_os.domain.entities.workspace import ProjectWorkspace, WorkspaceStatus
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    ContextId,
    ContextUpdateId,
    IssueId,
    TaskId,
    WorkspaceId,
)


PLATFORM_MATERIALIZED_STATE_TABLES = (
    "platform_workspace_state",
    "platform_context_state",
    "platform_task_state",
    "platform_issue_state",
    "platform_agent_registration_state",
)


SQLITE_PLATFORM_MATERIALIZED_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS platform_workspace_state (
    workspace_id TEXT PRIMARY KEY,
    source_event_sequence INTEGER NOT NULL,
    display_name TEXT NOT NULL,
    root_path TEXT NOT NULL,
    status TEXT NOT NULL,
    workspace_json TEXT NOT NULL DEFAULT '{}',
    binding_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (source_event_sequence >= 0)
);

CREATE INDEX IF NOT EXISTS idx_platform_workspace_state_status
    ON platform_workspace_state(status);

CREATE TABLE IF NOT EXISTS platform_context_state (
    workspace_id TEXT PRIMARY KEY,
    context_id TEXT NOT NULL UNIQUE,
    source_event_sequence INTEGER NOT NULL,
    update_count INTEGER NOT NULL DEFAULT 0,
    materialized_state_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (source_event_sequence >= 0),
    CHECK (update_count >= 0),
    FOREIGN KEY (workspace_id)
        REFERENCES platform_workspace_state(workspace_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_platform_context_state_source_event
    ON platform_context_state(source_event_sequence);

CREATE TABLE IF NOT EXISTS platform_task_state (
    task_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    source_event_sequence INTEGER NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    assignee_agent_id TEXT,
    context_update_ids_json TEXT NOT NULL DEFAULT '[]',
    linked_file_paths_json TEXT NOT NULL DEFAULT '[]',
    task_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (source_event_sequence >= 0),
    FOREIGN KEY (workspace_id)
        REFERENCES platform_workspace_state(workspace_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_platform_task_state_workspace_status
    ON platform_task_state(workspace_id, status);

CREATE INDEX IF NOT EXISTS idx_platform_task_state_source_event
    ON platform_task_state(source_event_sequence);

CREATE INDEX IF NOT EXISTS idx_platform_task_state_assignee
    ON platform_task_state(assignee_agent_id)
    WHERE assignee_agent_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS platform_issue_state (
    issue_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    source_event_sequence INTEGER NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    severity TEXT NOT NULL,
    linked_task_id TEXT,
    context_update_ids_json TEXT NOT NULL DEFAULT '[]',
    linked_file_paths_json TEXT NOT NULL DEFAULT '[]',
    issue_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (source_event_sequence >= 0),
    FOREIGN KEY (workspace_id)
        REFERENCES platform_workspace_state(workspace_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_platform_issue_state_workspace_status
    ON platform_issue_state(workspace_id, status);

CREATE INDEX IF NOT EXISTS idx_platform_issue_state_source_event
    ON platform_issue_state(source_event_sequence);

CREATE INDEX IF NOT EXISTS idx_platform_issue_state_severity
    ON platform_issue_state(severity);

CREATE INDEX IF NOT EXISTS idx_platform_issue_state_linked_task
    ON platform_issue_state(linked_task_id)
    WHERE linked_task_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS platform_agent_registration_state (
    agent_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    source_event_sequence INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    default_model TEXT,
    capabilities_json TEXT NOT NULL DEFAULT '[]',
    tool_permissions_json TEXT NOT NULL DEFAULT '[]',
    runtime_config_json TEXT NOT NULL DEFAULT '{}',
    registration_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (source_event_sequence >= 0),
    FOREIGN KEY (workspace_id)
        REFERENCES platform_workspace_state(workspace_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_platform_agent_registration_state_workspace_status
    ON platform_agent_registration_state(workspace_id, status);

CREATE INDEX IF NOT EXISTS idx_platform_agent_registration_state_source_event
    ON platform_agent_registration_state(source_event_sequence);

CREATE INDEX IF NOT EXISTS idx_platform_agent_registration_state_default_model
    ON platform_agent_registration_state(default_model)
    WHERE default_model IS NOT NULL;
"""


WORKSPACE_STATE_UPSERT_COLUMNS = (
    "workspace_id",
    "source_event_sequence",
    "display_name",
    "root_path",
    "status",
    "workspace_json",
    "binding_json",
    "metadata_json",
    "created_at",
    "updated_at",
)


WORKSPACE_STATE_SELECT_COLUMNS = WORKSPACE_STATE_UPSERT_COLUMNS


CONTEXT_STATE_UPSERT_COLUMNS = (
    "workspace_id",
    "context_id",
    "source_event_sequence",
    "update_count",
    "materialized_state_json",
    "metadata_json",
    "created_at",
    "updated_at",
)


CONTEXT_STATE_SELECT_COLUMNS = CONTEXT_STATE_UPSERT_COLUMNS


TASK_STATE_UPSERT_COLUMNS = (
    "task_id",
    "workspace_id",
    "source_event_sequence",
    "title",
    "status",
    "assignee_agent_id",
    "context_update_ids_json",
    "linked_file_paths_json",
    "task_json",
    "metadata_json",
    "created_at",
    "updated_at",
)


TASK_STATE_SELECT_COLUMNS = TASK_STATE_UPSERT_COLUMNS


ISSUE_STATE_UPSERT_COLUMNS = (
    "issue_id",
    "workspace_id",
    "source_event_sequence",
    "title",
    "status",
    "severity",
    "linked_task_id",
    "context_update_ids_json",
    "linked_file_paths_json",
    "issue_json",
    "metadata_json",
    "created_at",
    "updated_at",
)


ISSUE_STATE_SELECT_COLUMNS = ISSUE_STATE_UPSERT_COLUMNS


AGENT_REGISTRATION_STATE_UPSERT_COLUMNS = (
    "agent_id",
    "workspace_id",
    "source_event_sequence",
    "name",
    "description",
    "status",
    "default_model",
    "capabilities_json",
    "tool_permissions_json",
    "runtime_config_json",
    "registration_json",
    "metadata_json",
    "created_at",
    "updated_at",
)


AGENT_REGISTRATION_STATE_SELECT_COLUMNS = AGENT_REGISTRATION_STATE_UPSERT_COLUMNS


SQLITE_WORKSPACE_STATE_UPSERT_SQL = f"""
INSERT INTO platform_workspace_state ({", ".join(WORKSPACE_STATE_UPSERT_COLUMNS)})
VALUES ({", ".join(f":{column}" for column in WORKSPACE_STATE_UPSERT_COLUMNS)})
ON CONFLICT(workspace_id) DO UPDATE SET
    source_event_sequence = excluded.source_event_sequence,
    display_name = excluded.display_name,
    root_path = excluded.root_path,
    status = excluded.status,
    workspace_json = excluded.workspace_json,
    binding_json = excluded.binding_json,
    metadata_json = excluded.metadata_json,
    created_at = excluded.created_at,
    updated_at = excluded.updated_at;
"""


SQLITE_CONTEXT_STATE_UPSERT_SQL = f"""
INSERT INTO platform_context_state ({", ".join(CONTEXT_STATE_UPSERT_COLUMNS)})
VALUES ({", ".join(f":{column}" for column in CONTEXT_STATE_UPSERT_COLUMNS)})
ON CONFLICT(workspace_id) DO UPDATE SET
    context_id = excluded.context_id,
    source_event_sequence = excluded.source_event_sequence,
    update_count = excluded.update_count,
    materialized_state_json = excluded.materialized_state_json,
    metadata_json = excluded.metadata_json,
    created_at = excluded.created_at,
    updated_at = excluded.updated_at;
"""


SQLITE_TASK_STATE_UPSERT_SQL = f"""
INSERT INTO platform_task_state ({", ".join(TASK_STATE_UPSERT_COLUMNS)})
VALUES ({", ".join(f":{column}" for column in TASK_STATE_UPSERT_COLUMNS)})
ON CONFLICT(task_id) DO UPDATE SET
    workspace_id = excluded.workspace_id,
    source_event_sequence = excluded.source_event_sequence,
    title = excluded.title,
    status = excluded.status,
    assignee_agent_id = excluded.assignee_agent_id,
    context_update_ids_json = excluded.context_update_ids_json,
    linked_file_paths_json = excluded.linked_file_paths_json,
    task_json = excluded.task_json,
    metadata_json = excluded.metadata_json,
    created_at = excluded.created_at,
    updated_at = excluded.updated_at;
"""


SQLITE_ISSUE_STATE_UPSERT_SQL = f"""
INSERT INTO platform_issue_state ({", ".join(ISSUE_STATE_UPSERT_COLUMNS)})
VALUES ({", ".join(f":{column}" for column in ISSUE_STATE_UPSERT_COLUMNS)})
ON CONFLICT(issue_id) DO UPDATE SET
    workspace_id = excluded.workspace_id,
    source_event_sequence = excluded.source_event_sequence,
    title = excluded.title,
    status = excluded.status,
    severity = excluded.severity,
    linked_task_id = excluded.linked_task_id,
    context_update_ids_json = excluded.context_update_ids_json,
    linked_file_paths_json = excluded.linked_file_paths_json,
    issue_json = excluded.issue_json,
    metadata_json = excluded.metadata_json,
    created_at = excluded.created_at,
    updated_at = excluded.updated_at;
"""


SQLITE_AGENT_REGISTRATION_STATE_UPSERT_SQL = f"""
INSERT INTO platform_agent_registration_state ({", ".join(AGENT_REGISTRATION_STATE_UPSERT_COLUMNS)})
VALUES ({", ".join(f":{column}" for column in AGENT_REGISTRATION_STATE_UPSERT_COLUMNS)})
ON CONFLICT(agent_id) DO UPDATE SET
    workspace_id = excluded.workspace_id,
    source_event_sequence = excluded.source_event_sequence,
    name = excluded.name,
    description = excluded.description,
    status = excluded.status,
    default_model = excluded.default_model,
    capabilities_json = excluded.capabilities_json,
    tool_permissions_json = excluded.tool_permissions_json,
    runtime_config_json = excluded.runtime_config_json,
    registration_json = excluded.registration_json,
    metadata_json = excluded.metadata_json,
    created_at = excluded.created_at,
    updated_at = excluded.updated_at;
"""


SQLITE_CONTEXT_STATE_GET_SQL = (
    f"SELECT {', '.join(CONTEXT_STATE_SELECT_COLUMNS)} "
    "FROM platform_context_state WHERE workspace_id = ?"
)


SQLITE_WORKSPACE_STATE_GET_SQL = (
    f"SELECT {', '.join(WORKSPACE_STATE_SELECT_COLUMNS)} "
    "FROM platform_workspace_state WHERE workspace_id = ?"
)


SQLITE_WORKSPACE_STATE_LIST_SQL = (
    f"SELECT {', '.join(WORKSPACE_STATE_SELECT_COLUMNS)} "
    "FROM platform_workspace_state ORDER BY workspace_id"
)


SQLITE_TASK_STATE_GET_SQL = (
    f"SELECT {', '.join(TASK_STATE_SELECT_COLUMNS)} "
    "FROM platform_task_state WHERE task_id = ?"
)


SQLITE_TASK_STATE_LIST_BY_WORKSPACE_SQL = (
    f"SELECT {', '.join(TASK_STATE_SELECT_COLUMNS)} "
    "FROM platform_task_state WHERE workspace_id = ? ORDER BY task_id"
)


SQLITE_ISSUE_STATE_GET_SQL = (
    f"SELECT {', '.join(ISSUE_STATE_SELECT_COLUMNS)} "
    "FROM platform_issue_state WHERE issue_id = ?"
)


SQLITE_ISSUE_STATE_LIST_BY_WORKSPACE_SQL = (
    f"SELECT {', '.join(ISSUE_STATE_SELECT_COLUMNS)} "
    "FROM platform_issue_state WHERE workspace_id = ? ORDER BY issue_id"
)


SQLITE_AGENT_REGISTRATION_STATE_GET_SQL = (
    f"SELECT {', '.join(AGENT_REGISTRATION_STATE_SELECT_COLUMNS)} "
    "FROM platform_agent_registration_state WHERE agent_id = ?"
)


SQLITE_AGENT_REGISTRATION_STATE_LIST_BY_WORKSPACE_SQL = (
    f"SELECT {', '.join(AGENT_REGISTRATION_STATE_SELECT_COLUMNS)} "
    "FROM platform_agent_registration_state WHERE workspace_id = ? ORDER BY agent_id"
)


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


def _stable_json(value: Mapping[str, object]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _stable_json_list(value: tuple[object, ...]) -> str:
    return json.dumps(list(value), ensure_ascii=False, separators=(",", ":"))


def _load_mapping_json(value: object, field_name: str) -> Mapping[str, object]:
    loaded = json.loads(str(value))
    if not isinstance(loaded, dict):
        raise ValueError(f"{field_name} must decode to a JSON object.")
    return loaded


def _load_text_list_json(value: object, field_name: str) -> tuple[str, ...]:
    loaded = json.loads(str(value))
    if not isinstance(loaded, list):
        raise ValueError(f"{field_name} must decode to a JSON array.")
    for item in loaded:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} must contain only strings.")
    return tuple(loaded)


def _load_agent_capabilities_json(
    value: object,
    field_name: str,
) -> tuple[AgentCapability, ...]:
    loaded = json.loads(str(value))
    if not isinstance(loaded, list):
        raise ValueError(f"{field_name} must decode to a JSON array.")

    capabilities: list[AgentCapability] = []
    for item in loaded:
        if not isinstance(item, dict):
            raise ValueError(f"{field_name} must contain only JSON objects.")
        name = item.get("name")
        description = item.get("description")
        metadata = item.get("metadata", {})
        if not isinstance(name, str):
            raise ValueError(f"{field_name} capability name must be a string.")
        if not isinstance(description, str):
            raise ValueError(
                f"{field_name} capability description must be a string."
            )
        if not isinstance(metadata, dict):
            raise ValueError(f"{field_name} capability metadata must be an object.")
        for key, metadata_value in metadata.items():
            if not isinstance(key, str) or not isinstance(metadata_value, str):
                raise ValueError(
                    f"{field_name} capability metadata must contain string values."
                )
        capabilities.append(
            AgentCapability(
                name=name,
                description=description,
                metadata=metadata,
            )
        )
    return tuple(capabilities)


def _datetime_text(value: datetime) -> str:
    return value.isoformat()


def workspace_state_upsert_row(
    *,
    workspace: ProjectWorkspace,
    source_event_sequence: int,
) -> Mapping[str, object]:
    if source_event_sequence < 0:
        raise ValueError("source_event_sequence must be a non-negative integer.")

    workspace_json = {
        "workspace_id": workspace.workspace_id.value,
        "display_name": workspace.display_name,
        "root_path": workspace.root_path,
        "status": workspace.status.value,
        "created_at": _datetime_text(workspace.created_at),
        "updated_at": _datetime_text(workspace.updated_at),
        "metadata": dict(workspace.metadata),
    }

    return {
        "workspace_id": workspace.workspace_id.value,
        "source_event_sequence": source_event_sequence,
        "display_name": workspace.display_name,
        "root_path": workspace.root_path,
        "status": workspace.status.value,
        "workspace_json": _stable_json(workspace_json),
        "binding_json": "{}",
        "metadata_json": _stable_json(workspace.metadata),
        "created_at": _datetime_text(workspace.created_at),
        "updated_at": _datetime_text(workspace.updated_at),
    }


def context_state_upsert_row(
    *,
    context: ProjectSharedContext,
    source_event_sequence: int,
) -> Mapping[str, object]:
    if source_event_sequence < 0:
        raise ValueError("source_event_sequence must be a non-negative integer.")

    return {
        "workspace_id": context.workspace_id.value,
        "context_id": context.context_id.value,
        "source_event_sequence": source_event_sequence,
        "update_count": len(context.updates),
        "materialized_state_json": _stable_json(context.materialized_state),
        "metadata_json": _stable_json(context.metadata),
        "created_at": _datetime_text(context.created_at),
        "updated_at": _datetime_text(context.updated_at),
    }


def task_state_upsert_row(
    *,
    task: TaskContext,
    source_event_sequence: int,
) -> Mapping[str, object | None]:
    if source_event_sequence < 0:
        raise ValueError("source_event_sequence must be a non-negative integer.")

    context_update_ids = tuple(update_id.value for update_id in task.context_update_ids)
    task_json = {
        "task_id": task.task_id.value,
        "workspace_id": task.workspace_id.value,
        "title": task.title,
        "status": task.status.value,
        "description": task.description,
        "assignee_agent_id": (
            task.assignee_agent_id.value
            if task.assignee_agent_id is not None
            else None
        ),
        "context_update_ids": list(context_update_ids),
        "linked_file_paths": list(task.linked_file_paths),
        "created_at": _datetime_text(task.created_at),
        "updated_at": _datetime_text(task.updated_at),
        "metadata": dict(task.metadata),
    }

    return {
        "task_id": task.task_id.value,
        "workspace_id": task.workspace_id.value,
        "source_event_sequence": source_event_sequence,
        "title": task.title,
        "status": task.status.value,
        "assignee_agent_id": (
            task.assignee_agent_id.value
            if task.assignee_agent_id is not None
            else None
        ),
        "context_update_ids_json": _stable_json_list(context_update_ids),
        "linked_file_paths_json": _stable_json_list(task.linked_file_paths),
        "task_json": _stable_json(task_json),
        "metadata_json": _stable_json(task.metadata),
        "created_at": _datetime_text(task.created_at),
        "updated_at": _datetime_text(task.updated_at),
    }


def issue_state_upsert_row(
    *,
    issue: IssueContext,
    source_event_sequence: int,
) -> Mapping[str, object | None]:
    if source_event_sequence < 0:
        raise ValueError("source_event_sequence must be a non-negative integer.")

    context_update_ids = tuple(update_id.value for update_id in issue.context_update_ids)
    linked_task_id = (
        issue.linked_task_id.value
        if issue.linked_task_id is not None
        else None
    )
    issue_json = {
        "issue_id": issue.issue_id.value,
        "workspace_id": issue.workspace_id.value,
        "title": issue.title,
        "status": issue.status.value,
        "severity": issue.severity.value,
        "description": issue.description,
        "linked_task_id": linked_task_id,
        "context_update_ids": list(context_update_ids),
        "linked_file_paths": list(issue.linked_file_paths),
        "created_at": _datetime_text(issue.created_at),
        "updated_at": _datetime_text(issue.updated_at),
        "metadata": dict(issue.metadata),
    }

    return {
        "issue_id": issue.issue_id.value,
        "workspace_id": issue.workspace_id.value,
        "source_event_sequence": source_event_sequence,
        "title": issue.title,
        "status": issue.status.value,
        "severity": issue.severity.value,
        "linked_task_id": linked_task_id,
        "context_update_ids_json": _stable_json_list(context_update_ids),
        "linked_file_paths_json": _stable_json_list(issue.linked_file_paths),
        "issue_json": _stable_json(issue_json),
        "metadata_json": _stable_json(issue.metadata),
        "created_at": _datetime_text(issue.created_at),
        "updated_at": _datetime_text(issue.updated_at),
    }


def agent_registration_state_upsert_row(
    *,
    registration: AgentRegistration,
    source_event_sequence: int,
) -> Mapping[str, object | None]:
    if source_event_sequence < 0:
        raise ValueError("source_event_sequence must be a non-negative integer.")

    capabilities = tuple(
        {
            "name": capability.name,
            "description": capability.description,
            "metadata": dict(capability.metadata),
        }
        for capability in registration.capabilities
    )
    registration_json = {
        "agent_id": registration.agent_id.value,
        "workspace_id": registration.workspace_id.value,
        "name": registration.name,
        "description": registration.description,
        "status": registration.status.value,
        "default_model": registration.default_model,
        "capabilities": list(capabilities),
        "tool_permissions": list(registration.tool_permissions),
        "runtime_config": dict(registration.runtime_config),
        "created_at": _datetime_text(registration.created_at),
        "updated_at": _datetime_text(registration.updated_at),
        "metadata": dict(registration.metadata),
    }

    return {
        "agent_id": registration.agent_id.value,
        "workspace_id": registration.workspace_id.value,
        "source_event_sequence": source_event_sequence,
        "name": registration.name,
        "description": registration.description,
        "status": registration.status.value,
        "default_model": registration.default_model,
        "capabilities_json": _stable_json_list(capabilities),
        "tool_permissions_json": _stable_json_list(registration.tool_permissions),
        "runtime_config_json": _stable_json(registration.runtime_config),
        "registration_json": _stable_json(registration_json),
        "metadata_json": _stable_json(registration.metadata),
        "created_at": _datetime_text(registration.created_at),
        "updated_at": _datetime_text(registration.updated_at),
    }


@dataclass(frozen=True, slots=True)
class WorkspaceStateRecord:
    """Persisted materialized current state for one project workspace."""

    source_event_sequence: int
    workspace: ProjectWorkspace
    workspace_state: Mapping[str, object] = field(default_factory=dict)
    binding_state: Mapping[str, object] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_event_sequence < 0:
            raise ValueError("source_event_sequence must be a non-negative integer.")

    @classmethod
    def from_sqlite_row(cls, row: Mapping[str, object]) -> "WorkspaceStateRecord":
        metadata = _load_mapping_json(row["metadata_json"], "metadata_json")
        return cls(
            source_event_sequence=int(row["source_event_sequence"]),
            workspace=ProjectWorkspace(
                workspace_id=WorkspaceId(str(row["workspace_id"])),
                display_name=str(row["display_name"]),
                root_path=str(row["root_path"]),
                status=WorkspaceStatus(str(row["status"])),
                created_at=datetime.fromisoformat(str(row["created_at"])),
                updated_at=datetime.fromisoformat(str(row["updated_at"])),
                metadata=metadata,
            ),
            workspace_state=_load_mapping_json(row["workspace_json"], "workspace_json"),
            binding_state=_load_mapping_json(row["binding_json"], "binding_json"),
            metadata=metadata,
        )


@dataclass(frozen=True, slots=True)
class ContextStateRecord:
    """Persisted materialized current state for one project shared context."""

    source_event_sequence: int
    update_count: int
    context: ProjectSharedContext
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_event_sequence < 0:
            raise ValueError("source_event_sequence must be a non-negative integer.")
        if self.update_count < 0:
            raise ValueError("update_count must be a non-negative integer.")

    @classmethod
    def from_sqlite_row(cls, row: Mapping[str, object]) -> "ContextStateRecord":
        metadata = _load_mapping_json(row["metadata_json"], "metadata_json")
        return cls(
            source_event_sequence=int(row["source_event_sequence"]),
            update_count=int(row["update_count"]),
            context=ProjectSharedContext(
                context_id=ContextId(str(row["context_id"])),
                workspace_id=WorkspaceId(str(row["workspace_id"])),
                updates=(),
                materialized_state=_load_mapping_json(
                    row["materialized_state_json"],
                    "materialized_state_json",
                ),
                created_at=datetime.fromisoformat(str(row["created_at"])),
                updated_at=datetime.fromisoformat(str(row["updated_at"])),
                metadata=metadata,
            ),
            metadata=metadata,
        )


@dataclass(frozen=True, slots=True)
class TaskStateRecord:
    """Persisted materialized current state for one platform task."""

    source_event_sequence: int
    task: TaskContext
    task_state: Mapping[str, object] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_event_sequence < 0:
            raise ValueError("source_event_sequence must be a non-negative integer.")

    @classmethod
    def from_sqlite_row(cls, row: Mapping[str, object]) -> "TaskStateRecord":
        task_state = _load_mapping_json(row["task_json"], "task_json")
        metadata = _load_mapping_json(row["metadata_json"], "metadata_json")
        assignee_agent_id = row["assignee_agent_id"]
        return cls(
            source_event_sequence=int(row["source_event_sequence"]),
            task=TaskContext(
                task_id=TaskId(str(row["task_id"])),
                workspace_id=WorkspaceId(str(row["workspace_id"])),
                title=str(row["title"]),
                status=TaskStatus(str(row["status"])),
                created_at=datetime.fromisoformat(str(row["created_at"])),
                updated_at=datetime.fromisoformat(str(row["updated_at"])),
                description=(
                    str(task_state["description"])
                    if task_state.get("description") is not None
                    else None
                ),
                assignee_agent_id=(
                    AgentId(str(assignee_agent_id))
                    if assignee_agent_id is not None
                    else None
                ),
                context_update_ids=tuple(
                    ContextUpdateId(update_id)
                    for update_id in _load_text_list_json(
                        row["context_update_ids_json"],
                        "context_update_ids_json",
                    )
                ),
                linked_file_paths=_load_text_list_json(
                    row["linked_file_paths_json"],
                    "linked_file_paths_json",
                ),
                metadata=metadata,
            ),
            task_state=task_state,
            metadata=metadata,
        )


@dataclass(frozen=True, slots=True)
class IssueStateRecord:
    """Persisted materialized current state for one platform issue."""

    source_event_sequence: int
    issue: IssueContext
    issue_state: Mapping[str, object] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_event_sequence < 0:
            raise ValueError("source_event_sequence must be a non-negative integer.")

    @classmethod
    def from_sqlite_row(cls, row: Mapping[str, object]) -> "IssueStateRecord":
        issue_state = _load_mapping_json(row["issue_json"], "issue_json")
        metadata = _load_mapping_json(row["metadata_json"], "metadata_json")
        linked_task_id = row["linked_task_id"]
        return cls(
            source_event_sequence=int(row["source_event_sequence"]),
            issue=IssueContext(
                issue_id=IssueId(str(row["issue_id"])),
                workspace_id=WorkspaceId(str(row["workspace_id"])),
                title=str(row["title"]),
                status=IssueStatus(str(row["status"])),
                severity=IssueSeverity(str(row["severity"])),
                created_at=datetime.fromisoformat(str(row["created_at"])),
                updated_at=datetime.fromisoformat(str(row["updated_at"])),
                description=(
                    str(issue_state["description"])
                    if issue_state.get("description") is not None
                    else None
                ),
                linked_task_id=(
                    TaskId(str(linked_task_id))
                    if linked_task_id is not None
                    else None
                ),
                context_update_ids=tuple(
                    ContextUpdateId(update_id)
                    for update_id in _load_text_list_json(
                        row["context_update_ids_json"],
                        "context_update_ids_json",
                    )
                ),
                linked_file_paths=_load_text_list_json(
                    row["linked_file_paths_json"],
                    "linked_file_paths_json",
                ),
                metadata=metadata,
            ),
            issue_state=issue_state,
            metadata=metadata,
        )


@dataclass(frozen=True, slots=True)
class AgentRegistrationStateRecord:
    """Persisted materialized current state for one platform agent registration."""

    source_event_sequence: int
    registration: AgentRegistration
    registration_state: Mapping[str, object] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_event_sequence < 0:
            raise ValueError("source_event_sequence must be a non-negative integer.")

    @classmethod
    def from_sqlite_row(
        cls,
        row: Mapping[str, object],
    ) -> "AgentRegistrationStateRecord":
        registration_state = _load_mapping_json(
            row["registration_json"],
            "registration_json",
        )
        metadata = _load_mapping_json(row["metadata_json"], "metadata_json")
        default_model = row["default_model"]
        return cls(
            source_event_sequence=int(row["source_event_sequence"]),
            registration=AgentRegistration(
                agent_id=AgentId(str(row["agent_id"])),
                workspace_id=WorkspaceId(str(row["workspace_id"])),
                name=str(row["name"]),
                description=str(row["description"]),
                capabilities=_load_agent_capabilities_json(
                    row["capabilities_json"],
                    "capabilities_json",
                ),
                status=AgentRegistrationStatus(str(row["status"])),
                created_at=datetime.fromisoformat(str(row["created_at"])),
                updated_at=datetime.fromisoformat(str(row["updated_at"])),
                default_model=(
                    str(default_model)
                    if default_model is not None
                    else None
                ),
                tool_permissions=_load_text_list_json(
                    row["tool_permissions_json"],
                    "tool_permissions_json",
                ),
                runtime_config=_load_mapping_json(
                    row["runtime_config_json"],
                    "runtime_config_json",
                ),
                metadata=metadata,
            ),
            registration_state=registration_state,
            metadata=metadata,
        )


class WorkspaceStateReaderPort(Protocol):
    """Minimal read boundary for workspace current state."""

    def get_workspace_state(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceStateRecord | None:
        ...

    def list_workspace_states(self) -> tuple[WorkspaceStateRecord, ...]:
        ...


class ContextStateReaderPort(Protocol):
    """Minimal read boundary for context current state."""

    def get_context_state(
        self,
        workspace_id: WorkspaceId,
    ) -> ContextStateRecord | None:
        ...


class TaskStateReaderPort(Protocol):
    """Minimal read boundary for task current state."""

    def get_task_state(
        self,
        task_id: TaskId,
    ) -> TaskStateRecord | None:
        ...

    def list_task_states_by_workspace(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[TaskStateRecord, ...]:
        ...


class IssueStateReaderPort(Protocol):
    """Minimal read boundary for issue current state."""

    def get_issue_state(
        self,
        issue_id: IssueId,
    ) -> IssueStateRecord | None:
        ...

    def list_issue_states_by_workspace(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[IssueStateRecord, ...]:
        ...


class AgentRegistrationStateReaderPort(Protocol):
    """Minimal read boundary for agent registration current state."""

    def get_agent_registration_state(
        self,
        agent_id: AgentId,
    ) -> AgentRegistrationStateRecord | None:
        ...

    def list_agent_registration_states_by_workspace(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[AgentRegistrationStateRecord, ...]:
        ...


class WorkspaceStateWriterPort(Protocol):
    """Minimal write boundary for workspace current state."""

    def upsert_workspace_state(
        self,
        *,
        workspace: ProjectWorkspace,
        source_event_sequence: int,
    ) -> None:
        ...


class ContextStateWriterPort(Protocol):
    """Minimal write boundary for context current state."""

    def upsert_context_state(
        self,
        *,
        context: ProjectSharedContext,
        source_event_sequence: int,
    ) -> None:
        ...


class TaskStateWriterPort(Protocol):
    """Minimal write boundary for task current state."""

    def upsert_task_state(
        self,
        *,
        task: TaskContext,
        source_event_sequence: int,
    ) -> None:
        ...


class IssueStateWriterPort(Protocol):
    """Minimal write boundary for issue current state."""

    def upsert_issue_state(
        self,
        *,
        issue: IssueContext,
        source_event_sequence: int,
    ) -> None:
        ...


class AgentRegistrationStateWriterPort(Protocol):
    """Minimal write boundary for agent registration current state."""

    def upsert_agent_registration_state(
        self,
        *,
        registration: AgentRegistration,
        source_event_sequence: int,
    ) -> None:
        ...


@dataclass(slots=True)
class SqliteTaskStateStore(TaskStateReaderPort, TaskStateWriterPort):
    """SQLite-backed reader/writer for current task state."""

    connection: sqlite3.Connection

    def get_task_state(
        self,
        task_id: TaskId,
    ) -> TaskStateRecord | None:
        _require_non_empty(task_id.value, "task_id")
        row = self.connection.execute(
            SQLITE_TASK_STATE_GET_SQL,
            (task_id.value,),
        ).fetchone()
        if row is None:
            return None
        return TaskStateRecord.from_sqlite_row(
            dict(zip(TASK_STATE_SELECT_COLUMNS, row, strict=True))
        )

    def list_task_states_by_workspace(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[TaskStateRecord, ...]:
        _require_non_empty(workspace_id.value, "workspace_id")
        rows = self.connection.execute(
            SQLITE_TASK_STATE_LIST_BY_WORKSPACE_SQL,
            (workspace_id.value,),
        ).fetchall()
        return tuple(
            TaskStateRecord.from_sqlite_row(
                dict(zip(TASK_STATE_SELECT_COLUMNS, row, strict=True))
            )
            for row in rows
        )

    def upsert_task_state(
        self,
        *,
        task: TaskContext,
        source_event_sequence: int,
    ) -> None:
        self.connection.execute(
            SQLITE_TASK_STATE_UPSERT_SQL,
            task_state_upsert_row(
                task=task,
                source_event_sequence=source_event_sequence,
            ),
        )
        self.connection.commit()


@dataclass(slots=True)
class SqliteAgentRegistrationStateStore(
    AgentRegistrationStateReaderPort,
    AgentRegistrationStateWriterPort,
):
    """SQLite-backed reader/writer for current agent registration state."""

    connection: sqlite3.Connection

    def get_agent_registration_state(
        self,
        agent_id: AgentId,
    ) -> AgentRegistrationStateRecord | None:
        _require_non_empty(agent_id.value, "agent_id")
        row = self.connection.execute(
            SQLITE_AGENT_REGISTRATION_STATE_GET_SQL,
            (agent_id.value,),
        ).fetchone()
        if row is None:
            return None
        return AgentRegistrationStateRecord.from_sqlite_row(
            dict(zip(AGENT_REGISTRATION_STATE_SELECT_COLUMNS, row, strict=True))
        )

    def list_agent_registration_states_by_workspace(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[AgentRegistrationStateRecord, ...]:
        _require_non_empty(workspace_id.value, "workspace_id")
        rows = self.connection.execute(
            SQLITE_AGENT_REGISTRATION_STATE_LIST_BY_WORKSPACE_SQL,
            (workspace_id.value,),
        ).fetchall()
        return tuple(
            AgentRegistrationStateRecord.from_sqlite_row(
                dict(zip(AGENT_REGISTRATION_STATE_SELECT_COLUMNS, row, strict=True))
            )
            for row in rows
        )

    def upsert_agent_registration_state(
        self,
        *,
        registration: AgentRegistration,
        source_event_sequence: int,
    ) -> None:
        self.connection.execute(
            SQLITE_AGENT_REGISTRATION_STATE_UPSERT_SQL,
            agent_registration_state_upsert_row(
                registration=registration,
                source_event_sequence=source_event_sequence,
            ),
        )
        self.connection.commit()


@dataclass(slots=True)
class SqliteIssueStateStore(IssueStateReaderPort, IssueStateWriterPort):
    """SQLite-backed reader/writer for current issue state."""

    connection: sqlite3.Connection

    def get_issue_state(
        self,
        issue_id: IssueId,
    ) -> IssueStateRecord | None:
        _require_non_empty(issue_id.value, "issue_id")
        row = self.connection.execute(
            SQLITE_ISSUE_STATE_GET_SQL,
            (issue_id.value,),
        ).fetchone()
        if row is None:
            return None
        return IssueStateRecord.from_sqlite_row(
            dict(zip(ISSUE_STATE_SELECT_COLUMNS, row, strict=True))
        )

    def list_issue_states_by_workspace(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[IssueStateRecord, ...]:
        _require_non_empty(workspace_id.value, "workspace_id")
        rows = self.connection.execute(
            SQLITE_ISSUE_STATE_LIST_BY_WORKSPACE_SQL,
            (workspace_id.value,),
        ).fetchall()
        return tuple(
            IssueStateRecord.from_sqlite_row(
                dict(zip(ISSUE_STATE_SELECT_COLUMNS, row, strict=True))
            )
            for row in rows
        )

    def upsert_issue_state(
        self,
        *,
        issue: IssueContext,
        source_event_sequence: int,
    ) -> None:
        self.connection.execute(
            SQLITE_ISSUE_STATE_UPSERT_SQL,
            issue_state_upsert_row(
                issue=issue,
                source_event_sequence=source_event_sequence,
            ),
        )
        self.connection.commit()


@dataclass(slots=True)
class SqliteContextStateStore(ContextStateReaderPort, ContextStateWriterPort):
    """SQLite-backed reader/writer for current shared-context state."""

    connection: sqlite3.Connection

    def get_context_state(
        self,
        workspace_id: WorkspaceId,
    ) -> ContextStateRecord | None:
        _require_non_empty(workspace_id.value, "workspace_id")
        row = self.connection.execute(
            SQLITE_CONTEXT_STATE_GET_SQL,
            (workspace_id.value,),
        ).fetchone()
        if row is None:
            return None
        return ContextStateRecord.from_sqlite_row(
            dict(zip(CONTEXT_STATE_SELECT_COLUMNS, row, strict=True))
        )

    def upsert_context_state(
        self,
        *,
        context: ProjectSharedContext,
        source_event_sequence: int,
    ) -> None:
        self.connection.execute(
            SQLITE_CONTEXT_STATE_UPSERT_SQL,
            context_state_upsert_row(
                context=context,
                source_event_sequence=source_event_sequence,
            ),
        )
        self.connection.commit()


@dataclass(slots=True)
class SqliteWorkspaceStateStore(WorkspaceStateReaderPort, WorkspaceStateWriterPort):
    """SQLite-backed reader/writer for current workspace state."""

    connection: sqlite3.Connection

    def get_workspace_state(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceStateRecord | None:
        _require_non_empty(workspace_id.value, "workspace_id")
        row = self.connection.execute(
            SQLITE_WORKSPACE_STATE_GET_SQL,
            (workspace_id.value,),
        ).fetchone()
        if row is None:
            return None
        return WorkspaceStateRecord.from_sqlite_row(
            dict(zip(WORKSPACE_STATE_SELECT_COLUMNS, row, strict=True))
        )

    def list_workspace_states(self) -> tuple[WorkspaceStateRecord, ...]:
        rows = self.connection.execute(SQLITE_WORKSPACE_STATE_LIST_SQL).fetchall()
        return tuple(
            WorkspaceStateRecord.from_sqlite_row(
                dict(zip(WORKSPACE_STATE_SELECT_COLUMNS, row, strict=True))
            )
            for row in rows
        )

    def upsert_workspace_state(
        self,
        *,
        workspace: ProjectWorkspace,
        source_event_sequence: int,
    ) -> None:
        self.connection.execute(
            SQLITE_WORKSPACE_STATE_UPSERT_SQL,
            workspace_state_upsert_row(
                workspace=workspace,
                source_event_sequence=source_event_sequence,
            ),
        )
        self.connection.commit()
