from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.infrastructure.composition.local_platform import (
    LocalPlatformRuntimeComponents,
    build_local_platform_operation_service,
    build_local_platform_runtime,
    connect_local_platform_database,
)
from agent_os.infrastructure.composition.local_platform_initialization import (
    LocalPlatformInitialState,
)
from agent_os.infrastructure.config import (
    LocalAgentInvocationAdapterMode,
    LocalPlatformSettings,
)
from agent_os.domain.entities.file_operation import FileOperationResultStatus
from agent_os.domain.entities.context import ContextUpdateKind
from agent_os.domain.value_objects.identifiers import (
    AgentInvocationId,
    ContextUpdateId,
    FileOperationId,
    WorkspaceId,
)
from agent_os.infrastructure.persistence.file_operation_records import (
    SqliteFileOperationRecordStore,
)
from agent_os.infrastructure.persistence.invocation_records import (
    SqliteAgentInvocationRecordStore,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteContextStateStore,
)
from agent_os.infrastructure.persistence.sqlite_persistence import (
    SqlitePlatformPersistence,
)
from support.platform_invocation_fixtures import (
    platform_event_count,
    seed_minimal_invocation_platform_state,
)


class LocalPlatformCompositionTests(unittest.TestCase):
    def test_build_initializes_sqlite_and_composes_runtime_handler(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "platform.sqlite3"
            settings = LocalPlatformSettings(
                database=str(database),
                workspace_root=str(Path(temporary_directory) / "workspace"),
                plugins_directory=str(Path(temporary_directory) / "plugins"),
            )

            components = build_local_platform_runtime(settings)
            try:
                self.assertIsInstance(components, LocalPlatformRuntimeComponents)
                self.assertEqual(components.settings, settings)
                table = components.connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'platform_events'"
                ).fetchone()
                self.assertEqual(table, ("platform_events",))
            finally:
                components.close()

    def test_build_rejects_database_with_missing_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings = LocalPlatformSettings(
                database=str(
                    Path(temporary_directory) / "missing" / "platform.sqlite3"
                ),
                workspace_root=str(Path(temporary_directory) / "workspace"),
                plugins_directory=str(Path(temporary_directory) / "plugins"),
            )

            with self.assertRaisesRegex(ValueError, "database parent directory"):
                build_local_platform_runtime(settings)

    def test_connect_local_platform_database_enables_foreign_keys(self) -> None:
        connection = connect_local_platform_database(":memory:")
        try:
            enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        finally:
            connection.close()

        self.assertEqual(enabled, 1)

    def test_build_closes_connection_when_initialization_fails(self) -> None:
        connection = _TrackedConnection()
        settings = LocalPlatformSettings(
            database=":memory:",
            workspace_root="workspace",
            plugins_directory="plugins",
        )
        initial_state = LocalPlatformInitialState(
            workspace_id="workspace-failed-1",
            context_id="context-failed-1",
            agent_id="agent-failed-1",
            workspace_display_name=" ",
            workspace_root="workspace",
            agent_name="Runtime Agent",
            agent_description="Handles runtime requests",
            agent_capability_name="single-turn-status",
            agent_capability_description="Captures runtime requests",
        )

        with patch(
            "agent_os.infrastructure.composition.local_platform."
            "connect_local_platform_database",
            return_value=connection,
        ):
            with self.assertRaisesRegex(ValueError, "display_name"):
                build_local_platform_runtime(settings, initial_state=initial_state)

        self.assertTrue(connection.closed)

    def test_empty_local_state_fails_without_writing_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "platform.sqlite3"
            settings = LocalPlatformSettings(
                database=str(database),
                workspace_root=str(Path(temporary_directory) / "workspace"),
                plugins_directory=str(Path(temporary_directory) / "plugins"),
            )
            components = build_local_platform_runtime(settings)
            try:
                with self.assertRaisesRegex(ValueError, "workspace state not found"):
                    components.handle_payload(
                        {
                            "workspaceId": "workspace-1",
                            "agentId": "agent-1",
                            "instruction": "Run without initialized state.",
                            "invocationId": "invoke-empty-local-state-1",
                            "requestedAt": "2026-06-04T23:03:00Z",
                        }
                    )

                self.assertEqual(platform_event_count(components.connection), 0)
            finally:
                components.close()

    def test_build_can_enable_deterministic_provider_backed_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "platform.sqlite3"
            settings = LocalPlatformSettings(
                database=str(database),
                workspace_root=str(Path(temporary_directory) / "workspace"),
                plugins_directory=str(Path(temporary_directory) / "plugins"),
                agent_invocation_adapter_mode=(
                    LocalAgentInvocationAdapterMode.DETERMINISTIC_PROVIDER
                ),
            )
            components = build_local_platform_runtime(settings)
            try:
                seed_minimal_invocation_platform_state(components.connection)

                response = components.handle_payload(
                    {
                        "workspaceId": "workspace-1",
                        "agentId": "agent-1",
                        "instruction": "Run with settings provider mode.",
                        "invocationId": "invoke-local-composition-provider-1",
                        "requestedAt": "2026-06-04T22:59:00Z",
                        "userContextUpdateId": (
                            "update-local-composition-provider-1"
                        ),
                        "contextEventId": (
                            "event-context-local-composition-provider-1"
                        ),
                        "agentInvocationEventId": (
                            "event-invoke-local-composition-provider-1"
                        ),
                    }
                )

                self.assertIsNotNone(components.agent_invocation_adapter)
                self.assertTrue(response["modelInvoked"])
                self.assertFalse(response["deterministicPlaceholder"])
                self.assertEqual(
                    response["invocationResult"]["outputText"],
                    "Deterministic model response: Run with settings provider mode.",
                )
            finally:
                components.close()

    def test_build_can_initialize_minimal_local_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "platform.sqlite3"
            settings = LocalPlatformSettings(
                database=str(database),
                workspace_root=str(Path(temporary_directory) / "workspace"),
                plugins_directory=str(Path(temporary_directory) / "plugins"),
            )
            initial_state = LocalPlatformInitialState(
                workspace_id="workspace-init-run-1",
                context_id="context-init-run-1",
                agent_id="agent-init-run-1",
                workspace_display_name="Initialized Runtime Workspace",
                workspace_root=str(Path(temporary_directory) / "workspace"),
                agent_name="Initialized Runtime Agent",
                agent_description="Handles initialized runtime requests",
                agent_capability_name="single-turn-status",
                agent_capability_description="Captures initialized runtime requests",
            )

            components = build_local_platform_runtime(
                settings,
                initial_state=initial_state,
            )
            try:
                self.assertIsNotNone(components.initialized_state)
                assert components.initialized_state is not None
                self.assertFalse(components.initialized_state.platform_event_recorded)

                response = components.handle_payload(
                    {
                        "workspaceId": "workspace-init-run-1",
                        "agentId": "agent-init-run-1",
                        "instruction": "Run after local initialization.",
                        "invocationId": "invoke-local-initialized-1",
                        "requestedAt": "2026-06-04T23:01:30Z",
                        "userContextUpdateId": "update-local-initialized-1",
                        "contextEventId": "event-context-local-initialized-1",
                        "agentInvocationEventId": (
                            "event-invoke-local-initialized-1"
                        ),
                    }
                )

                self.assertEqual(response["workspaceId"], "workspace-init-run-1")
                self.assertEqual(response["contextId"], "context-init-run-1")
                self.assertFalse(response["modelInvoked"])
                self.assertTrue(response["deterministicPlaceholder"])
            finally:
                components.close()

    def test_components_provide_controlled_file_operation_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace_root = Path(temporary_directory) / "workspace"
            _write_file(workspace_root / "docs" / "status.md", "ready")
            database = Path(temporary_directory) / "platform.sqlite3"
            settings = LocalPlatformSettings(
                database=str(database),
                workspace_root=str(workspace_root),
                plugins_directory=str(Path(temporary_directory) / "plugins"),
            )
            initial_state = LocalPlatformInitialState(
                workspace_id="workspace-file-runtime-1",
                context_id="context-file-runtime-1",
                agent_id="agent-file-runtime-1",
                workspace_display_name="File Runtime Workspace",
                workspace_root=str(workspace_root),
                agent_name="File Runtime Agent",
                agent_description="Handles initialized runtime requests",
                agent_capability_name="single-turn-status",
                agent_capability_description="Captures initialized runtime requests",
            )

            components = build_local_platform_runtime(
                settings,
                initial_state=initial_state,
            )
            try:
                use_case = components.workspace_file_operations(
                    "workspace-file-runtime-1"
                )

                recorded = use_case.read_file(
                    operation_id=FileOperationId("file-op-local-runtime-1"),
                    relative_path="docs/status.md",
                )

                record = SqliteFileOperationRecordStore(
                    components.connection
                ).get_file_operation_record(
                    FileOperationId("file-op-local-runtime-1")
                )
            finally:
                components.close()

        self.assertEqual(recorded.result.status, FileOperationResultStatus.SUCCEEDED)
        self.assertEqual(recorded.result.output_payload["content"], "ready")
        self.assertEqual(recorded.source_event_sequence, 1)
        assert record is not None
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(record.source_event_sequence, 1)
        self.assertNotIn("content", record.output_payload)

    def test_components_expose_local_operation_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "platform.sqlite3"
            settings = LocalPlatformSettings(
                database=str(database),
                workspace_root=str(Path(temporary_directory) / "workspace"),
                plugins_directory=str(Path(temporary_directory) / "plugins"),
            )
            initial_state = LocalPlatformInitialState(
                workspace_id="workspace-ops-1",
                context_id="context-ops-1",
                agent_id="agent-ops-1",
                workspace_display_name="Operations Workspace",
                workspace_root=str(Path(temporary_directory) / "workspace"),
                agent_name="Operations Agent",
                agent_description="Handles local operation requests",
                agent_capability_name="single-turn-status",
                agent_capability_description="Captures initialized runtime requests",
            )
            components = build_local_platform_runtime(
                settings,
                initial_state=initial_state,
            )
            try:
                service = components.operations()

                workspaces = service.list_workspaces()
                agents = service.list_agent_registrations("workspace-ops-1")
                appended = service.append_context_update(
                    "workspace-ops-1",
                    update_kind=ContextUpdateKind.NOTE,
                    summary="Captured local operation note",
                    update_id="update-ops-note-1",
                    materialized_state_patch={"latest_note": "operation"},
                    event_id="event-ops-note-1",
                )
                context_state = SqliteContextStateStore(
                    components.connection
                ).get_context_state(WorkspaceId("workspace-ops-1"))
                event_count = platform_event_count(components.connection)
            finally:
                components.close()

        self.assertEqual(
            workspaces["workspaces"][0]["workspaceId"],
            "workspace-ops-1",
        )
        self.assertEqual(agents["agents"][0]["agentId"], "agent-ops-1")
        self.assertEqual(appended["contextUpdate"]["updateId"], "update-ops-note-1")
        self.assertEqual(appended["context"]["updateCount"], 1)
        self.assertEqual(appended["sourceEventSequence"], 1)
        self.assertEqual(event_count, 1)
        assert context_state is not None
        self.assertEqual(context_state.update_count, 1)
        self.assertEqual(
            context_state.context.materialized_state["latest_note"],
            "operation",
        )

    def test_components_operation_service_creates_invocation_ready_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace_root = Path(temporary_directory) / "workspace"
            database = Path(temporary_directory) / "platform.sqlite3"
            settings = LocalPlatformSettings(
                database=str(database),
                workspace_root=str(workspace_root),
                plugins_directory=str(Path(temporary_directory) / "plugins"),
            )
            components = build_local_platform_runtime(settings)
            try:
                service = components.operations()

                created = service.create_workspace(
                    workspace_id="workspace-lifecycle-1",
                    display_name="Lifecycle Workspace",
                    root_path=str(workspace_root),
                    workspace_event_id="event-workspace-lifecycle-create-1",
                    agent_event_id="event-agent-lifecycle-create-1",
                )
                response = components.handle_payload(
                    {
                        "workspaceId": "workspace-lifecycle-1",
                        "agentId": "agent-workspace-lifecycle-1",
                        "instruction": "Run after lifecycle create.",
                        "invocationId": "invoke-lifecycle-1",
                        "requestedAt": "2026-06-05T09:30:00Z",
                        "userContextUpdateId": "update-lifecycle-user-1",
                        "contextEventId": "event-context-lifecycle-user-1",
                        "agentInvocationEventId": "event-invoke-lifecycle-1",
                    }
                )
                context_state = SqliteContextStateStore(
                    components.connection
                ).get_context_state(WorkspaceId("workspace-lifecycle-1"))
            finally:
                components.close()

        self.assertTrue(created["created"])
        self.assertEqual(
            created["baseline"]["agents"][0]["agentId"],
            "agent-workspace-lifecycle-1",
        )
        self.assertEqual(response["workspaceId"], "workspace-lifecycle-1")
        self.assertEqual(response["contextId"], "context-workspace-lifecycle-1")
        self.assertTrue(response["deterministicPlaceholder"])
        assert context_state is not None
        self.assertEqual(context_state.update_count, 1)

    def test_build_local_platform_operation_service_uses_existing_connection(self) -> None:
        connection = connect_local_platform_database(":memory:")
        try:
            SqlitePlatformPersistence(connection).initialize()
            service = build_local_platform_operation_service(connection)

            self.assertEqual(service.list_workspaces()["workspaces"], [])
        finally:
            connection.close()

    def test_handle_payload_executes_explicit_file_operation_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace_root = Path(temporary_directory) / "workspace"
            _write_file(workspace_root / "docs" / "status.md", "ready")
            database = Path(temporary_directory) / "platform.sqlite3"
            settings = LocalPlatformSettings(
                database=str(database),
                workspace_root=str(workspace_root),
                plugins_directory=str(Path(temporary_directory) / "plugins"),
            )
            initial_state = LocalPlatformInitialState(
                workspace_id="workspace-file-payload-1",
                context_id="context-file-payload-1",
                agent_id="agent-file-payload-1",
                workspace_display_name="File Payload Workspace",
                workspace_root=str(workspace_root),
                agent_name="File Payload Agent",
                agent_description="Handles initialized runtime requests",
                agent_capability_name="single-turn-status",
                agent_capability_description="Captures initialized runtime requests",
            )

            components = build_local_platform_runtime(
                settings,
                initial_state=initial_state,
            )
            try:
                response = components.handle_payload(
                    {
                        "workspaceId": "workspace-file-payload-1",
                        "agentId": "agent-file-payload-1",
                        "instruction": "Run with explicit file operation.",
                        "invocationId": "invoke-file-payload-1",
                        "requestedAt": "2026-06-04T23:20:00Z",
                        "userContextUpdateId": "update-file-payload-1",
                        "contextEventId": "event-context-file-payload-1",
                        "agentInvocationEventId": "event-invoke-file-payload-1",
                        "fileOperations": [
                            {
                                "operationKind": "read_file",
                                "relativePath": "docs/status.md",
                                "operationId": "file-op-payload-1",
                                "eventId": "event-file-payload-1",
                                "contextUpdateId": "update-file-reference-1",
                                "contextEventId": "event-file-reference-1",
                                "requestMetadata": {"source": "payload-test"},
                                "auditMetadata": {"phase": "file"},
                            }
                        ],
                    }
                )
                record = SqliteFileOperationRecordStore(
                    components.connection
                ).get_file_operation_record(FileOperationId("file-op-payload-1"))
                invocation_record = SqliteAgentInvocationRecordStore(
                    components.connection
                ).get_agent_invocation_record(
                    AgentInvocationId("invoke-file-payload-1")
                )
                event_rows = components.connection.execute(
                    """
                    SELECT sequence, event_kind, aggregate_id, metadata_json
                    FROM platform_events
                    ORDER BY sequence
                    """
                ).fetchall()
            finally:
                components.close()

        self.assertEqual(response["sourceEventSequence"], 3)
        self.assertEqual(response["agentInvocationEventSequence"], 5)
        self.assertTrue(response["toolInvoked"])
        self.assertEqual(
            response["fileOperations"][0]["operationId"],
            "file-op-payload-1",
        )
        self.assertEqual(
            response["fileOperations"][0]["contextUpdateId"],
            "update-file-reference-1",
        )
        self.assertNotIn("content", response["fileOperations"][0]["outputPayload"])
        self.assertEqual(
            response["fileOperations"][0]["outputPayload"]["content_length"],
            5,
        )
        self.assertTrue(
            response["invocationResult"]["outputPayload"]["tool_invoked"]
        )
        self.assertEqual(
            response["invocationResult"]["contextUpdateIds"],
            ["update-file-payload-1"],
        )
        self.assertEqual(
            response["materializedState"]["last_file_operation"]["operation_id"],
            "file-op-payload-1",
        )
        self.assertEqual(
            response["materializedState"]["last_file_operation"]["source_event_sequence"],
            1,
        )
        assert record is not None
        self.assertEqual(record.status, "succeeded")
        self.assertIsNone(record.invocation_id)
        self.assertEqual(record.request_state["metadata"]["source"], "payload-test")
        self.assertEqual(
            record.request_state["metadata"]["invocation_id"],
            "invoke-file-payload-1",
        )
        self.assertNotIn("content", record.output_payload)
        self.assertEqual(
            tuple(row[1] for row in event_rows),
            (
                "file_operation.recorded",
                "context.update_appended",
                "context.update_appended",
                "agent_invocation.recorded",
                "agent_invocation.recorded",
            ),
        )
        self.assertEqual(event_rows[0][2], "file-op-payload-1")
        self.assertEqual(json.loads(event_rows[0][3])["phase"], "file")
        self.assertEqual(event_rows[1][2], "update-file-reference-1")
        assert invocation_record is not None
        self.assertEqual(
            invocation_record.context_update_ids,
            (
                ContextUpdateId("update-file-reference-1"),
                ContextUpdateId("update-file-payload-1"),
            ),
        )
        self.assertEqual(
            invocation_record.request_state["metadata"]["file_operation_ids"],
            ["file-op-payload-1"],
        )

    def test_handle_payload_rejects_malformed_file_operations_before_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "platform.sqlite3"
            settings = LocalPlatformSettings(
                database=str(database),
                workspace_root=str(Path(temporary_directory) / "workspace"),
                plugins_directory=str(Path(temporary_directory) / "plugins"),
            )
            initial_state = LocalPlatformInitialState(
                workspace_id="workspace-file-malformed-1",
                context_id="context-file-malformed-1",
                agent_id="agent-file-malformed-1",
                workspace_display_name="File Malformed Workspace",
                workspace_root=str(Path(temporary_directory) / "workspace"),
                agent_name="File Malformed Agent",
                agent_description="Handles initialized runtime requests",
                agent_capability_name="single-turn-status",
                agent_capability_description="Captures initialized runtime requests",
            )

            components = build_local_platform_runtime(
                settings,
                initial_state=initial_state,
            )
            try:
                with self.assertRaisesRegex(ValueError, "file_operations"):
                    components.handle_payload(
                        {
                            "workspaceId": "workspace-file-malformed-1",
                            "agentId": "agent-file-malformed-1",
                            "instruction": "Run with malformed file operation.",
                            "fileOperations": "docs/status.md",
                        }
                    )

                self.assertEqual(platform_event_count(components.connection), 0)
            finally:
                components.close()

    def test_handle_payload_failed_file_operation_does_not_write_context_update(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace_root = Path(temporary_directory) / "workspace"
            workspace_root.mkdir(parents=True)
            database = Path(temporary_directory) / "platform.sqlite3"
            settings = LocalPlatformSettings(
                database=str(database),
                workspace_root=str(workspace_root),
                plugins_directory=str(Path(temporary_directory) / "plugins"),
            )
            initial_state = LocalPlatformInitialState(
                workspace_id="workspace-file-fail-1",
                context_id="context-file-fail-1",
                agent_id="agent-file-fail-1",
                workspace_display_name="File Fail Workspace",
                workspace_root=str(workspace_root),
                agent_name="File Fail Agent",
                agent_description="Handles initialized runtime requests",
                agent_capability_name="single-turn-status",
                agent_capability_description="Captures initialized runtime requests",
            )

            components = build_local_platform_runtime(
                settings,
                initial_state=initial_state,
            )
            try:
                with self.assertRaisesRegex(ValueError, "file operation failed"):
                    components.handle_payload(
                        {
                            "workspaceId": "workspace-file-fail-1",
                            "agentId": "agent-file-fail-1",
                            "instruction": "Run with missing file.",
                            "invocationId": "invoke-file-fail-1",
                            "fileOperations": [
                                {
                                    "operationKind": "read_file",
                                    "relativePath": "docs/missing.md",
                                    "operationId": "file-op-fail-1",
                                }
                            ],
                        }
                    )

                record = SqliteFileOperationRecordStore(
                    components.connection
                ).get_file_operation_record(FileOperationId("file-op-fail-1"))
                context_state = SqliteContextStateStore(
                    components.connection
                ).get_context_state(WorkspaceId("workspace-file-fail-1"))
                event_rows = components.connection.execute(
                    "SELECT event_kind FROM platform_events ORDER BY sequence"
                ).fetchall()
            finally:
                components.close()

        assert record is not None
        self.assertEqual(record.status, "failed")
        self.assertEqual(tuple(row[0] for row in event_rows), ("file_operation.recorded",))
        assert context_state is not None
        self.assertEqual(context_state.update_count, 0)
        self.assertNotIn(
            "last_file_operation",
            context_state.context.materialized_state,
        )

    def test_handle_payload_rejects_unregistered_capability_before_file_operation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace_root = Path(temporary_directory) / "workspace"
            _write_file(workspace_root / "docs" / "status.md", "ready")
            database = Path(temporary_directory) / "platform.sqlite3"
            settings = LocalPlatformSettings(
                database=str(database),
                workspace_root=str(workspace_root),
                plugins_directory=str(Path(temporary_directory) / "plugins"),
            )
            initial_state = LocalPlatformInitialState(
                workspace_id="workspace-file-preflight-1",
                context_id="context-file-preflight-1",
                agent_id="agent-file-preflight-1",
                workspace_display_name="File Preflight Workspace",
                workspace_root=str(workspace_root),
                agent_name="File Preflight Agent",
                agent_description="Handles initialized runtime requests",
                agent_capability_name="single-turn-status",
                agent_capability_description="Captures initialized runtime requests",
            )

            components = build_local_platform_runtime(
                settings,
                initial_state=initial_state,
            )
            try:
                with self.assertRaisesRegex(ValueError, "requested_capability"):
                    components.handle_payload(
                        {
                            "workspaceId": "workspace-file-preflight-1",
                            "agentId": "agent-file-preflight-1",
                            "instruction": "Run with unsupported capability.",
                            "invocationId": "invoke-file-preflight-1",
                            "requestedCapability": "unsupported",
                            "fileOperations": [
                                {
                                    "operationKind": "read_file",
                                    "relativePath": "docs/status.md",
                                    "operationId": "file-op-preflight-1",
                                }
                            ],
                        }
                    )

                file_record = SqliteFileOperationRecordStore(
                    components.connection
                ).get_file_operation_record(FileOperationId("file-op-preflight-1"))
                context_state = SqliteContextStateStore(
                    components.connection
                ).get_context_state(WorkspaceId("workspace-file-preflight-1"))
                event_count = platform_event_count(components.connection)
            finally:
                components.close()

        self.assertIsNone(file_record)
        self.assertEqual(event_count, 0)
        assert context_state is not None
        self.assertEqual(context_state.update_count, 0)

    def test_handle_payload_rejects_write_file_operation_before_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "platform.sqlite3"
            settings = LocalPlatformSettings(
                database=str(database),
                workspace_root=str(Path(temporary_directory) / "workspace"),
                plugins_directory=str(Path(temporary_directory) / "plugins"),
            )
            initial_state = LocalPlatformInitialState(
                workspace_id="workspace-file-write-1",
                context_id="context-file-write-1",
                agent_id="agent-file-write-1",
                workspace_display_name="File Write Workspace",
                workspace_root=str(Path(temporary_directory) / "workspace"),
                agent_name="File Write Agent",
                agent_description="Handles initialized runtime requests",
                agent_capability_name="single-turn-status",
                agent_capability_description="Captures initialized runtime requests",
            )

            components = build_local_platform_runtime(
                settings,
                initial_state=initial_state,
            )
            try:
                with self.assertRaisesRegex(ValueError, "read_file and list_directory"):
                    components.handle_payload(
                        {
                            "workspaceId": "workspace-file-write-1",
                            "agentId": "agent-file-write-1",
                            "instruction": "Run with write file operation.",
                            "fileOperations": [
                                {
                                    "operationKind": "write_file",
                                    "relativePath": "docs/status.md",
                                }
                            ],
                        }
                    )

                self.assertEqual(platform_event_count(components.connection), 0)
            finally:
                components.close()

    def test_handle_payload_path_escape_rejects_before_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace_root = Path(temporary_directory) / "workspace"
            workspace_root.mkdir(parents=True)
            database = Path(temporary_directory) / "platform.sqlite3"
            settings = LocalPlatformSettings(
                database=str(database),
                workspace_root=str(workspace_root),
                plugins_directory=str(Path(temporary_directory) / "plugins"),
            )
            initial_state = LocalPlatformInitialState(
                workspace_id="workspace-file-deny-1",
                context_id="context-file-deny-1",
                agent_id="agent-file-deny-1",
                workspace_display_name="File Deny Workspace",
                workspace_root=str(workspace_root),
                agent_name="File Deny Agent",
                agent_description="Handles initialized runtime requests",
                agent_capability_name="single-turn-status",
                agent_capability_description="Captures initialized runtime requests",
            )

            components = build_local_platform_runtime(
                settings,
                initial_state=initial_state,
            )
            try:
                with self.assertRaisesRegex(ValueError, "relative_path"):
                    components.handle_payload(
                        {
                            "workspaceId": "workspace-file-deny-1",
                            "agentId": "agent-file-deny-1",
                            "instruction": "Run with path escape.",
                            "invocationId": "invoke-file-deny-1",
                            "fileOperations": [
                                {
                                    "operationKind": "read_file",
                                    "relativePath": "../outside.txt",
                                    "operationId": "file-op-deny-1",
                                }
                            ],
                        }
                    )

                record = SqliteFileOperationRecordStore(
                    components.connection
                ).get_file_operation_record(FileOperationId("file-op-deny-1"))
                context_state = SqliteContextStateStore(
                    components.connection
                ).get_context_state(WorkspaceId("workspace-file-deny-1"))
                event_count = platform_event_count(components.connection)
            finally:
                components.close()

        self.assertIsNone(record)
        self.assertEqual(event_count, 0)
        assert context_state is not None
        self.assertEqual(context_state.update_count, 0)
        self.assertNotIn(
            "last_file_operation",
            context_state.context.materialized_state,
        )

    def test_duplicate_idempotency_rejects_before_second_file_operation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace_root = Path(temporary_directory) / "workspace"
            _write_file(workspace_root / "docs" / "status.md", "ready")
            database = Path(temporary_directory) / "platform.sqlite3"
            settings = LocalPlatformSettings(
                database=str(database),
                workspace_root=str(workspace_root),
                plugins_directory=str(Path(temporary_directory) / "plugins"),
            )
            initial_state = LocalPlatformInitialState(
                workspace_id="workspace-file-idem-1",
                context_id="context-file-idem-1",
                agent_id="agent-file-idem-1",
                workspace_display_name="File Idempotency Workspace",
                workspace_root=str(workspace_root),
                agent_name="File Idempotency Agent",
                agent_description="Handles initialized runtime requests",
                agent_capability_name="single-turn-status",
                agent_capability_description="Captures initialized runtime requests",
            )

            components = build_local_platform_runtime(
                settings,
                initial_state=initial_state,
            )
            try:
                components.handle_payload(
                    {
                        "workspaceId": "workspace-file-idem-1",
                        "agentId": "agent-file-idem-1",
                        "instruction": "Run first idempotent request.",
                        "invocationId": "invoke-file-idem-1",
                        "idempotencyKey": "idem-file-1",
                        "userContextUpdateId": "update-file-idem-user-1",
                        "fileOperations": [
                            {
                                "operationKind": "read_file",
                                "relativePath": "docs/status.md",
                                "operationId": "file-op-idem-1",
                                "contextUpdateId": "update-file-idem-ref-1",
                            }
                        ],
                    }
                )

                with self.assertRaisesRegex(ValueError, "idempotency_key"):
                    components.handle_payload(
                        {
                            "workspaceId": "workspace-file-idem-1",
                            "agentId": "agent-file-idem-1",
                            "instruction": "Run duplicate idempotent request.",
                            "invocationId": "invoke-file-idem-2",
                            "idempotencyKey": "idem-file-1",
                            "fileOperations": [
                                {
                                    "operationKind": "read_file",
                                    "relativePath": "docs/status.md",
                                    "operationId": "file-op-idem-2",
                                }
                            ],
                        }
                    )

                duplicate_file_record = SqliteFileOperationRecordStore(
                    components.connection
                ).get_file_operation_record(FileOperationId("file-op-idem-2"))
                event_count = platform_event_count(components.connection)
            finally:
                components.close()

        self.assertEqual(event_count, 5)
        self.assertIsNone(duplicate_file_record)

    def test_build_keeps_default_placeholder_invocation_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "platform.sqlite3"
            settings = LocalPlatformSettings(
                database=str(database),
                workspace_root=str(Path(temporary_directory) / "workspace"),
                plugins_directory=str(Path(temporary_directory) / "plugins"),
            )
            components = build_local_platform_runtime(settings)
            try:
                seed_minimal_invocation_platform_state(components.connection)

                response = components.handle_payload(
                    {
                        "workspaceId": "workspace-1",
                        "agentId": "agent-1",
                        "instruction": "Run through local composition.",
                        "invocationId": "invoke-local-composition-1",
                        "requestedAt": "2026-06-04T22:55:00Z",
                        "userContextUpdateId": "update-local-composition-1",
                        "contextEventId": "event-context-local-composition-1",
                        "agentInvocationEventId": (
                            "event-invoke-local-composition-1"
                        ),
                    }
                )

                self.assertTrue(response["runtimeLoaded"])
                self.assertFalse(response["modelInvoked"])
                self.assertTrue(response["deterministicPlaceholder"])
                self.assertEqual(
                    response["invocationResult"]["metadata"]["source"],
                    "deterministic_agent_invocation_adapter",
                )
            finally:
                components.close()


class _TrackedConnection:
    def __init__(self) -> None:
        self._connection = sqlite3.connect(":memory:")
        self.closed = False

    def close(self) -> None:
        self.closed = True
        self._connection.close()

    def __getattr__(self, name: str):
        return getattr(self._connection, name)


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_handle:
        file_handle.write(content)


if __name__ == "__main__":
    unittest.main()
