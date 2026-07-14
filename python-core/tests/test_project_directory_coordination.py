from __future__ import annotations

from datetime import datetime, timezone
import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.project_directory_coordination import (
    ProjectDirectoryAccessIntent,
    ProjectDirectoryCoordinationRecord,
    ProjectDirectoryOverlapStatus,
    calculate_project_directory_overlap,
    project_directory_coordination_interface_metadata,
)


class ProjectDirectoryCoordinationContractTests(unittest.TestCase):
    def test_record_serializes_advisory_only_boundary(self) -> None:
        record = ProjectDirectoryCoordinationRecord.from_mapping(
            {
                "directoryCoordinationId": "coord-1",
                "workspaceId": "workspace-1",
                "declaredAgentId": "agent-1",
                "projectRoot": "X:/fixture/workspace",
                "gitRepositoryId": "repo-1",
                "declaredPathScopes": ["src", "tests"],
                "directoryAccessIntent": "editing",
                "lastKnownGitHead": "abc123",
                "lastKnownBranch": "main",
                "dirtyState": "dirty_reported",
                "uncommittedChangeSummary": "Changed coordination tests.",
                "testSummary": "Not run.",
                "handoffNote": "Ready for review.",
                "createdAt": "2026-06-18T06:00:00+00:00",
            }
        )

        metadata = record.to_metadata()

        self.assertEqual(metadata["schema"], "project_directory_coordination.v1")
        self.assertEqual(metadata["directoryAccessIntent"], "editing")
        self.assertEqual(metadata["declaredPathScopes"], ["src", "tests"])
        self.assertEqual(metadata["coordinationStrength"], "advisory_only")
        self.assertTrue(metadata["notSecurityBoundary"])
        self.assertTrue(metadata["advisoryOnly"])
        self.assertFalse(metadata["fileBodiesRead"])
        self.assertFalse(metadata["recursiveFileScanExecuted"])
        self.assertFalse(metadata["gitOperationExecuted"])
        self.assertFalse(metadata["destructiveGitOperationExecuted"])
        self.assertFalse(metadata["realRuntimeConnected"])

    def test_path_scope_overlap_is_conservative_and_intent_aware(self) -> None:
        reader = ProjectDirectoryCoordinationRecord.from_mapping(
            {
                "directoryCoordinationId": "coord-reader",
                "workspaceId": "workspace-1",
                "declaredAgentId": "agent-reader",
                "projectRoot": "X:/fixture/workspace",
                "declaredPathScopes": ["docs"],
                "directoryAccessIntent": "read_only",
            }
        )
        writer = ProjectDirectoryCoordinationRecord.from_mapping(
            {
                "directoryCoordinationId": "coord-writer",
                "workspaceId": "workspace-1",
                "declaredAgentId": "agent-writer",
                "projectRoot": "X:/fixture/workspace",
                "declaredPathScopes": ["docs/api"],
                "directoryAccessIntent": "editing",
            }
        )
        disjoint = ProjectDirectoryCoordinationRecord.from_mapping(
            {
                "directoryCoordinationId": "coord-disjoint",
                "workspaceId": "workspace-1",
                "declaredAgentId": "agent-other",
                "projectRoot": "X:/fixture/workspace",
                "declaredPathScopes": ["gateway"],
                "directoryAccessIntent": "editing",
            }
        )

        status, overlapping_ids = calculate_project_directory_overlap(
            writer,
            (reader, disjoint),
        )

        self.assertEqual(status, ProjectDirectoryOverlapStatus.SHARED_WRITE_RISK)
        self.assertEqual(overlapping_ids, ("coord-reader",))

    def test_done_reported_record_is_not_active_overlap(self) -> None:
        done = ProjectDirectoryCoordinationRecord.from_mapping(
            {
                "directoryCoordinationId": "coord-done",
                "workspaceId": "workspace-1",
                "declaredAgentId": "agent-done",
                "projectRoot": "X:/fixture/workspace",
                "declaredPathScopes": ["src"],
                "directoryAccessIntent": "done_reported",
                "updatedAt": datetime(2026, 6, 18, 7, 0, tzinfo=timezone.utc),
            }
        )
        active = ProjectDirectoryCoordinationRecord.from_mapping(
            {
                "directoryCoordinationId": "coord-active",
                "workspaceId": "workspace-1",
                "declaredAgentId": "agent-active",
                "projectRoot": "X:/fixture/workspace",
                "declaredPathScopes": ["src"],
                "directoryAccessIntent": ProjectDirectoryAccessIntent.EDITING,
            }
        )

        status, overlapping_ids = calculate_project_directory_overlap(
            active,
            (done,),
        )

        self.assertEqual(status, ProjectDirectoryOverlapStatus.NONE)
        self.assertEqual(overlapping_ids, ())

    def test_record_rejects_parent_traversal_and_credential_metadata(self) -> None:
        with self.assertRaisesRegex(ValueError, "parent traversal"):
            ProjectDirectoryCoordinationRecord.from_mapping(
                {
                    "workspaceId": "workspace-1",
                    "declaredAgentId": "agent-1",
                    "projectRoot": "X:/fixture/workspace",
                    "declaredPathScopes": ["../outside"],
                }
            )
        with self.assertRaisesRegex(ValueError, "credential values"):
            ProjectDirectoryCoordinationRecord.from_mapping(
                {
                    "workspaceId": "workspace-1",
                    "declaredAgentId": "agent-1",
                    "projectRoot": "X:/fixture/workspace",
                    "metadata": {"apiKey": "sk-fixture-not-a-real-token"},
                }
            )

    def test_interface_is_contract_only(self) -> None:
        interface = project_directory_coordination_interface_metadata(
            workspace_id="workspace-1"
        )["projectDirectoryCoordinationInterface"]

        self.assertEqual(
            interface["schema"],
            "project_directory_coordination_interface.v1",
        )
        self.assertIn("editing", interface["accessIntents"])
        self.assertIn("shared_write_risk", interface["overlapStatuses"])
        self.assertTrue(interface["defaults"]["notSecurityBoundary"])
        self.assertTrue(interface["defaults"]["advisoryOnly"])
        self.assertFalse(interface["defaults"]["gitOperationExecuted"])
        self.assertEqual(
            interface["localRuntimeCommands"]["declare"],
            "project-directory-coordination-declare",
        )


if __name__ == "__main__":
    unittest.main()
