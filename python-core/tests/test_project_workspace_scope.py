from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.project_workspace_scope import (
    project_workspace_marker_payload,
    read_project_workspace_scope,
    write_project_workspace_marker_atomic,
)


class ProjectWorkspaceScopeTests(unittest.TestCase):
    def test_concurrent_different_marker_bindings_do_not_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / ".beacon" / "workspace.json"
            barrier = threading.Barrier(2)
            successes: list[str] = []
            failures: list[str] = []

            def write_binding(workspace_id: str) -> None:
                profile = root / f"{workspace_id}.json"
                payload = project_workspace_marker_payload(
                    project_root=root,
                    workspace_id=workspace_id,
                    profile_path=profile,
                )
                barrier.wait()
                try:
                    write_project_workspace_marker_atomic(
                        marker,
                        workspace_id=workspace_id,
                        profile_path=profile,
                        payload=payload,
                    )
                except ValueError as exc:
                    failures.append(str(exc))
                else:
                    successes.append(workspace_id)

            threads = [
                threading.Thread(target=write_binding, args=(workspace_id,))
                for workspace_id in ("workspace-a", "workspace-b")
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(len(successes), 1)
            self.assertEqual(len(failures), 1)
            self.assertIn("workspace_scope_conflict", failures[0])
            scope = read_project_workspace_scope(marker)
            self.assertEqual(scope.workspace_id, successes[0])
            self.assertEqual(
                json.loads(marker.read_text(encoding="utf-8"))["workspaceId"],
                successes[0],
            )


if __name__ == "__main__":
    unittest.main()
