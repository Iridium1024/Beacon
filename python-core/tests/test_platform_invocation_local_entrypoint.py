from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.platform_invocation_local_entrypoint import (
    LocalPlatformInvocationEntrypoint,
    handle_local_platform_invocation_payload,
)
from agent_os.application.services.provider_backed_agent_invocation_adapter import (
    ProviderBackedAgentInvocationAdapter,
)
from agent_os.domain.entities.agent import AgentCapability, AgentRegistration
from agent_os.domain.entities.context import ProjectSharedContext
from agent_os.domain.entities.workspace import ProjectWorkspace
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextId,
    FileOperationId,
    WorkspaceId,
)
from agent_os.infrastructure.persistence.file_operation_records import (
    SqliteFileOperationRecordStore,
)
from agent_os.infrastructure.persistence.invocation_records import (
    SqliteAgentInvocationRecordStore,
)
from agent_os.infrastructure.adapters.models import DeterministicModelProvider
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteAgentRegistrationStateStore,
    SqliteContextStateStore,
    SqliteWorkspaceStateStore,
)
from agent_os.infrastructure.persistence.sqlite_persistence import (
    SqlitePlatformPersistence,
)
from support.platform_invocation_fixtures import (
    platform_event_count,
    seed_minimal_invocation_platform_database,
)


class LocalPlatformInvocationEntrypointTests(unittest.TestCase):
    def test_handle_local_payload_executes_seeded_sqlite_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "platform.sqlite3"
            seed_minimal_invocation_platform_database(database)

            response = handle_local_platform_invocation_payload(
                database,
                {
                    "workspaceId": "workspace-1",
                    "agentId": "agent-1",
                    "instruction": "Capture this local task.",
                    "invocationId": "invoke-local-1",
                    "requestedAt": "2026-06-04T06:30:00Z",
                    "userContextUpdateId": "update-local-1",
                },
            )

            self.assertEqual(response["workspaceId"], "workspace-1")
            self.assertEqual(response["contextId"], "context-1")
            self.assertTrue(response["runtimeLoaded"])
            self.assertFalse(response["modelInvoked"])
            self.assertEqual(response["sourceEventSequence"], 1)
            self.assertEqual(response["agentInvocationEventSequence"], 3)

            with closing(sqlite3.connect(database)) as connection:
                record = SqliteAgentInvocationRecordStore(
                    connection
                ).get_agent_invocation_record(AgentInvocationId("invoke-local-1"))
                context = SqliteContextStateStore(connection).get_context_state(
                    WorkspaceId("workspace-1")
                )

            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record.status, "succeeded")
            self.assertIsNotNone(context)
            assert context is not None
            self.assertEqual(context.update_count, 1)

    def test_handle_local_payload_executes_explicit_file_operation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "workspace"
            _write_file(root / "docs" / "status.md", "ready")
            database = Path(directory) / "platform.sqlite3"
            _seed_invocation_database(database, root)

            response = handle_local_platform_invocation_payload(
                database,
                {
                    "workspaceId": "workspace-1",
                    "agentId": "agent-1",
                    "instruction": "Capture this local task with file context.",
                    "invocationId": "invoke-local-file-1",
                    "requestedAt": "2026-06-05T00:30:00Z",
                    "userContextUpdateId": "update-local-file-user-1",
                    "fileOperations": [
                        {
                            "operationKind": "read_file",
                            "relativePath": "docs/status.md",
                            "operationId": "file-op-local-entrypoint-1",
                            "contextUpdateId": "update-local-file-ref-1",
                        }
                    ],
                },
            )

            with closing(sqlite3.connect(database)) as connection:
                file_record = SqliteFileOperationRecordStore(
                    connection
                ).get_file_operation_record(
                    FileOperationId("file-op-local-entrypoint-1")
                )
                invocation_record = SqliteAgentInvocationRecordStore(
                    connection
                ).get_agent_invocation_record(
                    AgentInvocationId("invoke-local-file-1")
                )
                context = SqliteContextStateStore(connection).get_context_state(
                    WorkspaceId("workspace-1")
                )
                event_count = platform_event_count(connection)

        self.assertTrue(response["toolInvoked"])
        self.assertEqual(
            response["fileOperations"][0]["operationId"],
            "file-op-local-entrypoint-1",
        )
        self.assertEqual(
            response["fileOperations"][0]["contextUpdateId"],
            "update-local-file-ref-1",
        )
        self.assertEqual(response["sourceEventSequence"], 3)
        self.assertEqual(response["agentInvocationEventSequence"], 5)
        self.assertEqual(
            response["invocationResult"]["contextUpdateIds"],
            ["update-local-file-user-1"],
        )
        assert file_record is not None
        self.assertEqual(file_record.status, "succeeded")
        self.assertNotIn("content", file_record.output_payload)
        assert invocation_record is not None
        self.assertEqual(invocation_record.status, "succeeded")
        assert context is not None
        self.assertEqual(context.update_count, 2)
        self.assertEqual(event_count, 5)

    def test_handle_local_payload_failed_file_operation_does_not_write_context_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "workspace"
            root.mkdir(parents=True)
            database = Path(directory) / "platform.sqlite3"
            _seed_invocation_database(database, root)

            with self.assertRaisesRegex(ValueError, "file operation failed"):
                handle_local_platform_invocation_payload(
                    database,
                    {
                        "workspaceId": "workspace-1",
                        "agentId": "agent-1",
                        "instruction": "Capture this local task with a missing file.",
                        "invocationId": "invoke-local-file-fail-1",
                        "requestedAt": "2026-06-05T00:31:00Z",
                        "fileOperations": [
                            {
                                "operationKind": "read_file",
                                "relativePath": "docs/missing.md",
                                "operationId": "file-op-local-entrypoint-fail-1",
                            }
                        ],
                    },
                )

            with closing(sqlite3.connect(database)) as connection:
                file_record = SqliteFileOperationRecordStore(
                    connection
                ).get_file_operation_record(
                    FileOperationId("file-op-local-entrypoint-fail-1")
                )
                invocation_record = SqliteAgentInvocationRecordStore(
                    connection
                ).get_agent_invocation_record(
                    AgentInvocationId("invoke-local-file-fail-1")
                )
                context = SqliteContextStateStore(connection).get_context_state(
                    WorkspaceId("workspace-1")
                )
                event_count = platform_event_count(connection)

        assert file_record is not None
        self.assertEqual(file_record.status, "failed")
        self.assertIsNone(invocation_record)
        assert context is not None
        self.assertEqual(context.update_count, 0)
        self.assertEqual(event_count, 1)

    def test_entrypoint_object_delegates_to_local_payload_handler(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "platform.sqlite3"
            seed_minimal_invocation_platform_database(database)

            response = LocalPlatformInvocationEntrypoint(database).handle_payload(
                {
                    "workspaceId": "workspace-1",
                    "agentId": "agent-1",
                    "instruction": "Capture this local task.",
                    "invocationId": "invoke-local-2",
                    "requestedAt": "2026-06-04T06:31:00Z",
                    "userContextUpdateId": "update-local-2",
                }
            )

            self.assertEqual(response["invocationResult"]["invocationId"], "invoke-local-2")
            self.assertEqual(response["userContextUpdate"]["updateId"], "update-local-2")

    def test_entrypoint_accepts_explicit_provider_backed_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "platform.sqlite3"
            seed_minimal_invocation_platform_database(database)
            adapter = ProviderBackedAgentInvocationAdapter(
                model_provider=DeterministicModelProvider(),
                provider_name="deterministic",
                model_name="deterministic-text",
            )

            response = LocalPlatformInvocationEntrypoint(
                database,
                agent_invocation_adapter=adapter,
            ).handle_payload(
                {
                    "workspaceId": "workspace-1",
                    "agentId": "agent-1",
                    "instruction": "Use entrypoint provider adapter.",
                    "invocationId": "invoke-local-provider-1",
                    "requestedAt": "2026-06-04T22:58:30Z",
                    "userContextUpdateId": "update-local-provider-1",
                }
            )

            self.assertTrue(response["modelInvoked"])
            self.assertFalse(response["deterministicPlaceholder"])
            self.assertEqual(
                response["invocationResult"]["outputText"],
                "Deterministic model response: Use entrypoint provider adapter.",
            )


def _seed_invocation_database(database: Path, root: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        SqlitePlatformPersistence(connection).initialize()
        SqliteWorkspaceStateStore(connection).upsert_workspace_state(
            workspace=ProjectWorkspace.create(
                workspace_id=WorkspaceId("workspace-1"),
                display_name="Workspace",
                root_path=str(root),
            ),
            source_event_sequence=0,
        )
        SqliteContextStateStore(connection).upsert_context_state(
            context=ProjectSharedContext.create(
                context_id=ContextId("context-1"),
                workspace_id=WorkspaceId("workspace-1"),
                materialized_state={"status": "open"},
            ),
            source_event_sequence=0,
        )
        SqliteAgentRegistrationStateStore(connection).upsert_agent_registration_state(
            registration=AgentRegistration.register(
                agent_id=AgentId("agent-1"),
                workspace_id=WorkspaceId("workspace-1"),
                name="Runtime Agent",
                description="Handles single-turn status requests",
                capabilities=(
                    AgentCapability(
                        name="single-turn-status",
                        description="Captures single-turn status requests",
                    ),
                ),
                created_at=datetime(2026, 6, 5, 0, 30, tzinfo=timezone.utc),
                default_model="deterministic-placeholder",
            ),
            source_event_sequence=0,
        )


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_handle:
        file_handle.write(content)


if __name__ == "__main__":
    unittest.main()
