from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.local_platform_application import (
    LocalPlatformApplication,
)
from agent_os.infrastructure.config import LocalPlatformSettings


class LocalPlatformApplicationTests(unittest.TestCase):
    def test_application_runs_empty_database_smoke_flow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "workspace"
            database = Path(directory) / "platform.sqlite3"
            application = LocalPlatformApplication(
                LocalPlatformSettings(
                    database=str(database),
                    workspace_root=str(root),
                    plugins_directory=str(Path(directory) / "plugins"),
                )
            )

            smoke = application.run_smoke(
                workspace_id="workspace-app-smoke-1",
                invocation_id="invoke-app-smoke-1",
                session_id="session-app-smoke-1",
            )

            self.assertTrue(smoke["ok"])
            self.assertEqual(smoke["workspaceId"], "workspace-app-smoke-1")
            self.assertEqual(smoke["agentId"], "agent-workspace-app-smoke-1")
            self.assertTrue(all(smoke["steps"].values()))
            self.assertEqual(smoke["workspace"]["status"], "active")
            self.assertEqual(smoke["context"]["updateCount"], 1)
            self.assertEqual(
                smoke["invocation"]["invocationResult"]["invocationId"],
                "invoke-app-smoke-1",
            )
            self.assertEqual(len(smoke["invocationRecords"]), 1)
            self.assertEqual(smoke["fileOperationRecords"], [])
            self.assertEqual(smoke["session"]["sessionId"], "session-app-smoke-1")
            self.assertGreaterEqual(smoke["session"]["eventCount"], 1)

    def test_application_exposes_context_append_and_records_queries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            application = _application(directory)
            application.create_workspace(
                workspace_id="workspace-app-1",
                display_name="Application Workspace",
            )

            appended = application.append_context_update(
                workspace_id="workspace-app-1",
                update_id="update-app-note-1",
                summary="Application note",
                materialized_state_patch={"note": "captured"},
                payload={"source": "application-test"},
            )
            context = application.get_context("workspace-app-1")
            invocations = application.list_invocation_records("workspace-app-1")
            file_operations = application.list_file_operation_records(
                "workspace-app-1"
            )

            self.assertEqual(
                appended["contextUpdate"]["updateId"],
                "update-app-note-1",
            )
            self.assertEqual(context["context"]["materializedState"]["note"], "captured")
            self.assertEqual(invocations["invocations"], [])
            self.assertEqual(file_operations["fileOperations"], [])

    def test_application_rejects_missing_and_archived_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            application = _application(directory)

            with self.assertRaisesRegex(ValueError, "workspace state not found"):
                application.open_workspace("workspace-missing")

            application.create_workspace(
                workspace_id="workspace-app-archive-1",
                display_name="Application Archive Workspace",
            )
            archived = application.archive_workspace("workspace-app-archive-1")

            self.assertTrue(archived["archived"])
            with self.assertRaisesRegex(ValueError, "archived"):
                application.open_workspace("workspace-app-archive-1")

    def test_application_maps_invalid_invocation_to_stable_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            application = _application(directory)

            with self.assertRaisesRegex(ValueError, "workspace state not found"):
                application.invoke_deterministic(
                    workspace_id="workspace-missing",
                    instruction="Run without workspace.",
                    invocation_id="invoke-missing-workspace-1",
                )


def _application(directory: str) -> LocalPlatformApplication:
    root = Path(directory) / "workspace"
    return LocalPlatformApplication(
        LocalPlatformSettings(
            database=str(Path(directory) / "platform.sqlite3"),
            workspace_root=str(root),
            plugins_directory=str(Path(directory) / "plugins"),
        )
    )


if __name__ == "__main__":
    unittest.main()
