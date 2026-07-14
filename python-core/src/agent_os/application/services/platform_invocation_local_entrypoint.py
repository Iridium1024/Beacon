from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Mapping

from agent_os.application.services.platform_invocation_runtime_handler import (
    handle_sqlite_platform_invocation_payload,
)
from agent_os.application.services.single_turn_platform_runtime import (
    AgentInvocationAdapterPort,
)
from agent_os.infrastructure.persistence.sqlite_persistence import (
    SqlitePlatformPersistence,
)


@dataclass(frozen=True, slots=True)
class LocalPlatformInvocationEntrypoint:
    """Path-based local entrypoint for executing one platform invocation payload."""

    database: str | Path
    initialize_schema: bool = True
    record_agent_invocations: bool = True
    agent_invocation_adapter: AgentInvocationAdapterPort | None = None

    def handle_payload(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        return handle_local_platform_invocation_payload(
            self.database,
            payload,
            initialize_schema=self.initialize_schema,
            record_agent_invocations=self.record_agent_invocations,
            agent_invocation_adapter=self.agent_invocation_adapter,
        )


def handle_local_platform_invocation_payload(
    database: str | Path,
    payload: Mapping[str, object],
    *,
    initialize_schema: bool = True,
    record_agent_invocations: bool = True,
    agent_invocation_adapter: AgentInvocationAdapterPort | None = None,
) -> Mapping[str, object]:
    from agent_os.infrastructure.composition.local_platform import (
        connect_local_platform_database,
    )

    with closing(connect_local_platform_database(database)) as connection:
        if initialize_schema:
            SqlitePlatformPersistence(connection).initialize()
        return dict(
            handle_sqlite_platform_invocation_payload(
                connection,
                payload,
                record_agent_invocations=record_agent_invocations,
                agent_invocation_adapter=agent_invocation_adapter,
                file_operation_use_case_factory=(
                    _local_file_operation_use_case_factory(connection)
                ),
            )
        )


def _local_file_operation_use_case_factory(connection: sqlite3.Connection):
    def factory(workspace_id):
        from agent_os.infrastructure.composition.local_platform import (
            build_local_workspace_file_operation_use_case,
        )

        return build_local_workspace_file_operation_use_case(
            connection,
            workspace_id=workspace_id,
        )

    return factory
