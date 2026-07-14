from __future__ import annotations

from datetime import datetime, timezone
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.platform_invocation_gateway_bridge import (
    PLATFORM_SINGLE_TURN_INVOCATION_COMPLETED_KIND,
    SqlitePlatformInvocationGatewayRuntimeBridge,
)
from agent_os.application.services.platform_invocation_gateway_entrypoint import (
    handle_platform_invocation_gateway_envelope,
)
from agent_os.application.services.platform_invocation_gateway_handler import (
    PLATFORM_SINGLE_TURN_INVOCATION_KIND,
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
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteAgentRegistrationStateStore,
    SqliteContextStateStore,
    SqliteWorkspaceStateStore,
)
from support.platform_invocation_fixtures import (
    connect_in_memory_platform,
    platform_event_count,
    seed_minimal_invocation_platform_state,
)


class SqlitePlatformInvocationGatewayRuntimeBridgeTests(unittest.TestCase):
    def test_entrypoint_can_dispatch_gateway_envelope_to_sqlite_runtime(self) -> None:
        connection = connect_in_memory_platform()
        seed_minimal_invocation_platform_state(connection)
        bridge = SqlitePlatformInvocationGatewayRuntimeBridge(connection)

        response = handle_platform_invocation_gateway_envelope(
            {
                "protocolVersion": "1.0",
                "requestId": "request-1",
                "kind": PLATFORM_SINGLE_TURN_INVOCATION_KIND,
                "payload": {
                    "workspaceId": "workspace-1",
                    "agentId": "agent-1",
                    "instruction": "Capture this task.",
                    "invocationId": "invoke-1",
                    "requestedAt": "2026-06-04T05:05:44Z",
                    "userContextUpdateId": "update-user-1",
                },
                "metadata": {"correlation_id": "corr-1"},
            },
            adapter=bridge,
        )

        self.assertEqual(response["protocolVersion"], "1.0")
        self.assertEqual(response["requestId"], "request-1")
        self.assertEqual(response["kind"], PLATFORM_SINGLE_TURN_INVOCATION_COMPLETED_KIND)
        self.assertEqual(response["metadata"]["correlation_id"], "corr-1")
        self.assertEqual(
            response["metadata"]["handler"],
            "platform_invocation_gateway_runtime_bridge",
        )
        self.assertEqual(response["metadata"]["platform_runtime_wired"], "true")

        payload = response["payload"]
        self.assertEqual(payload["workspaceId"], "workspace-1")
        self.assertEqual(payload["agentId"], "agent-1")
        self.assertEqual(payload["contextId"], "context-1")
        self.assertTrue(payload["runtimeLoaded"])
        self.assertFalse(payload["modelInvoked"])
        self.assertEqual(payload["sourceEventSequence"], 1)
        self.assertEqual(payload["agentInvocationEventSequence"], 3)
        self.assertEqual(
            payload["materializedState"]["last_user_instruction"]["invocation_id"],
            "invoke-1",
        )

        record = SqliteAgentInvocationRecordStore(
            connection
        ).get_agent_invocation_record(AgentInvocationId("invoke-1"))
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(platform_event_count(connection), 3)

    def test_bridge_dispatches_explicit_file_operation_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "workspace"
            _write_file(root / "docs" / "status.md", "ready")
            connection = connect_in_memory_platform()
            _seed_invocation_state(connection, root)
            bridge = SqlitePlatformInvocationGatewayRuntimeBridge(connection)

            response = handle_platform_invocation_gateway_envelope(
                {
                    "protocolVersion": "1.0",
                    "requestId": "request-file-1",
                    "kind": PLATFORM_SINGLE_TURN_INVOCATION_KIND,
                    "payload": {
                        "workspaceId": "workspace-1",
                        "agentId": "agent-1",
                        "instruction": "Capture this task with file context.",
                        "invocationId": "invoke-file-bridge-1",
                        "requestedAt": "2026-06-05T00:40:00Z",
                        "userContextUpdateId": "update-file-bridge-user-1",
                        "fileOperations": [
                            {
                                "operationKind": "read_file",
                                "relativePath": "docs/status.md",
                                "operationId": "file-op-bridge-1",
                                "contextUpdateId": "update-file-bridge-ref-1",
                            }
                        ],
                    },
                    "metadata": {"correlation_id": "corr-file-1"},
                },
                adapter=bridge,
            )

            file_record = SqliteFileOperationRecordStore(
                connection
            ).get_file_operation_record(FileOperationId("file-op-bridge-1"))
            invocation_record = SqliteAgentInvocationRecordStore(
                connection
            ).get_agent_invocation_record(AgentInvocationId("invoke-file-bridge-1"))
            context = SqliteContextStateStore(connection).get_context_state(
                WorkspaceId("workspace-1")
            )

        self.assertEqual(response["kind"], PLATFORM_SINGLE_TURN_INVOCATION_COMPLETED_KIND)
        self.assertEqual(response["metadata"]["correlation_id"], "corr-file-1")
        payload = response["payload"]
        self.assertTrue(payload["toolInvoked"])
        self.assertEqual(payload["sourceEventSequence"], 3)
        self.assertEqual(payload["agentInvocationEventSequence"], 5)
        self.assertEqual(
            payload["fileOperations"][0]["operationId"],
            "file-op-bridge-1",
        )
        self.assertNotIn("content", payload["fileOperations"][0]["outputPayload"])
        self.assertEqual(
            payload["invocationResult"]["contextUpdateIds"],
            ["update-file-bridge-user-1"],
        )
        assert file_record is not None
        self.assertEqual(file_record.status, "succeeded")
        assert invocation_record is not None
        self.assertEqual(invocation_record.status, "succeeded")
        assert context is not None
        self.assertEqual(context.update_count, 2)
        self.assertEqual(platform_event_count(connection), 5)

    def test_bridge_rejects_unsupported_kind_before_runtime_write(self) -> None:
        connection = connect_in_memory_platform()
        seed_minimal_invocation_platform_state(connection)

        with self.assertRaisesRegex(ValueError, "unsupported platform invocation envelope kind"):
            SqlitePlatformInvocationGatewayRuntimeBridge(connection).handle_gateway_envelope(
                {
                    "protocolVersion": "1.0",
                    "requestId": "request-2",
                    "kind": "task.submit",
                    "payload": {
                        "workspaceId": "workspace-1",
                        "agentId": "agent-1",
                        "instruction": "Capture this task.",
                    },
                    "metadata": {},
                }
            )

        self.assertEqual(platform_event_count(connection), 0)


def _seed_invocation_state(connection, root: Path) -> None:
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
            created_at=datetime(2026, 6, 5, 0, 40, tzinfo=timezone.utc),
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
