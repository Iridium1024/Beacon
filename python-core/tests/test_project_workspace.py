from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.domain.entities.workspace import (
    ProjectBinding,
    ProjectWorkspace,
    WorkspaceStatus,
)
from agent_os.domain.value_objects.identifiers import WorkspaceId


class ProjectWorkspaceTests(unittest.TestCase):
    def test_create_workspace_uses_platform_fields_only(self) -> None:
        timestamp = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)
        workspace_id = WorkspaceId("workspace-1")

        workspace = ProjectWorkspace.create(
            workspace_id=workspace_id,
            display_name="Agent Chat",
            root_path="X:/fixture/beacon-project",
            created_at=timestamp,
            metadata={"source": "test"},
        )

        self.assertEqual(workspace.workspace_id, workspace_id)
        self.assertEqual(workspace.display_name, "Agent Chat")
        self.assertEqual(workspace.root_path, "X:/fixture/beacon-project")
        self.assertEqual(workspace.status, WorkspaceStatus.ACTIVE)
        self.assertEqual(workspace.created_at, timestamp)
        self.assertEqual(workspace.updated_at, timestamp)
        self.assertEqual(workspace.metadata["source"], "test")
        self.assertFalse(hasattr(workspace, "final_answer_candidates"))

    def test_workspace_lifecycle_updates_return_new_snapshots(self) -> None:
        created_at = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)
        updated_at = datetime(2026, 6, 2, 10, 5, tzinfo=timezone.utc)
        archived_at = datetime(2026, 6, 2, 10, 10, tzinfo=timezone.utc)

        workspace = ProjectWorkspace.create(
            display_name="Agent Chat",
            root_path="workspace",
            created_at=created_at,
        )
        renamed = workspace.rename("Agent Chat MVP", updated_at=updated_at)
        archived = renamed.archive(archived_at=archived_at)

        self.assertEqual(workspace.display_name, "Agent Chat")
        self.assertEqual(renamed.display_name, "Agent Chat MVP")
        self.assertEqual(renamed.updated_at, updated_at)
        self.assertEqual(archived.status, WorkspaceStatus.ARCHIVED)
        self.assertEqual(archived.updated_at, archived_at)

    def test_workspace_rejects_empty_required_fields(self) -> None:
        with self.assertRaises(ValueError):
            ProjectWorkspace.create(display_name="", root_path="workspace")

        with self.assertRaises(ValueError):
            ProjectWorkspace.create(display_name="Agent Chat", root_path=" ")


class ProjectBindingTests(unittest.TestCase):
    def test_binding_links_workspace_to_local_root_and_runtime_config(self) -> None:
        timestamp = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)
        workspace_id = WorkspaceId("workspace-1")

        binding = ProjectBinding.bind(
            workspace_id=workspace_id,
            local_root_path="X:/fixture/beacon-project",
            runtime_config={"profile": "mvp"},
            writable=False,
            created_at=timestamp,
        )

        self.assertEqual(binding.workspace_id, workspace_id)
        self.assertEqual(binding.local_root_path, "X:/fixture/beacon-project")
        self.assertEqual(binding.runtime_config["profile"], "mvp")
        self.assertFalse(binding.writable)
        self.assertEqual(binding.created_at, timestamp)
        self.assertEqual(binding.updated_at, timestamp)

    def test_binding_runtime_config_update_returns_new_snapshot(self) -> None:
        created_at = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)
        updated_at = datetime(2026, 6, 2, 10, 5, tzinfo=timezone.utc)

        binding = ProjectBinding.bind(
            workspace_id=WorkspaceId("workspace-1"),
            local_root_path="workspace",
            runtime_config={"profile": "initial"},
            created_at=created_at,
        )

        updated = binding.with_runtime_config(
            {"profile": "mvp", "mode": "single-turn"},
            updated_at=updated_at,
        )

        self.assertEqual(binding.runtime_config["profile"], "initial")
        self.assertEqual(updated.runtime_config["profile"], "mvp")
        self.assertEqual(updated.runtime_config["mode"], "single-turn")
        self.assertEqual(updated.updated_at, updated_at)

    def test_binding_rejects_empty_local_root(self) -> None:
        with self.assertRaises(ValueError):
            ProjectBinding.bind(
                workspace_id=WorkspaceId("workspace-1"),
                local_root_path="",
            )


if __name__ == "__main__":
    unittest.main()
