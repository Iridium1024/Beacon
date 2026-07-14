from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.file_operation_context_linker import (
    FileOperationContextLinker,
)
from agent_os.domain.entities.context import ContextUpdateKind, ProjectSharedContext
from agent_os.domain.entities.file_operation import (
    FileOperationKind,
    FileOperationRequest,
    FileOperationResult,
)
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    ContextUpdateId,
    FileOperationId,
    WorkspaceId,
)


class FileOperationContextLinkerTests(unittest.TestCase):
    def test_build_update_redacts_read_content_from_context_payload(self) -> None:
        completed_at = datetime(2026, 6, 4, 2, 0, tzinfo=timezone.utc)
        result = FileOperationResult.succeed(
            _request(
                operation_id=FileOperationId("file-op-1"),
                requested_by_agent_id=AgentId("agent-1"),
            ),
            completed_at=completed_at,
            bytes_read=5,
            output_payload={
                "content": "hello",
                "encoding": "utf-8",
            },
        )

        update = FileOperationContextLinker().build_update(
            result=result,
            source_event_sequence=12,
            update_id=ContextUpdateId("update-1"),
            metadata={"source_test": "read"},
        )

        operation = update.payload["file_operation"]
        self.assertEqual(update.update_id, ContextUpdateId("update-1"))
        self.assertEqual(update.workspace_id, WorkspaceId("workspace-1"))
        self.assertEqual(update.update_kind, ContextUpdateKind.FILE_REFERENCE)
        self.assertEqual(update.summary, "Read workspace file: docs/note.md")
        self.assertEqual(update.created_at, completed_at)
        self.assertEqual(update.source_agent_id, AgentId("agent-1"))
        self.assertNotIn("content", operation["output_payload"])
        self.assertEqual(operation["output_payload"]["content_persisted"], False)
        self.assertEqual(operation["output_payload"]["content_length"], 5)
        self.assertEqual(operation["output_payload"]["encoding"], "utf-8")
        self.assertEqual(operation["source_event_sequence"], 12)
        self.assertEqual(update.metadata["content_redacted_from_context"], True)
        self.assertEqual(update.metadata["source_test"], "read")

    def test_append_result_adds_file_reference_to_project_context(self) -> None:
        context = ProjectSharedContext.create(
            workspace_id=WorkspaceId("workspace-1"),
            materialized_state={"status": "open"},
        )
        result = FileOperationResult.succeed(
            _request(operation_id=FileOperationId("file-op-2")),
            output_payload={"entries": ({"name": "note.md", "kind": "file"},)},
        )

        updated_context = FileOperationContextLinker().append_result(
            context=context,
            result=result,
            source_event_sequence=13,
            update_id=ContextUpdateId("update-2"),
        )

        self.assertEqual(context.updates, ())
        self.assertEqual(len(updated_context.updates), 1)
        self.assertEqual(updated_context.updates[0].update_id, ContextUpdateId("update-2"))
        self.assertEqual(
            updated_context.materialized_state["last_file_operation"]["operation_id"],
            "file-op-2",
        )
        self.assertEqual(
            updated_context.materialized_state["last_file_operation"]["source_event_sequence"],
            13,
        )

    def test_build_update_reuses_result_context_update_id_when_present(self) -> None:
        request = _request(operation_id=FileOperationId("file-op-3"))
        result = FileOperationResult.succeed(
            request,
            context_update_id=ContextUpdateId("update-3"),
            output_payload={"encoding": "utf-8"},
        )

        update = FileOperationContextLinker().build_update(
            result=result,
            source_event_sequence=14,
        )

        self.assertEqual(update.update_id, ContextUpdateId("update-3"))

    def test_build_update_rejects_mismatched_result_context_update_id(self) -> None:
        result = FileOperationResult.succeed(
            _request(operation_id=FileOperationId("file-op-4")),
            context_update_id=ContextUpdateId("update-4"),
        )

        with self.assertRaisesRegex(ValueError, "context_update_id"):
            FileOperationContextLinker().build_update(
                result=result,
                source_event_sequence=15,
                update_id=ContextUpdateId("different-update"),
            )

    def test_build_update_rejects_failed_or_unrecorded_results(self) -> None:
        request = _request(operation_id=FileOperationId("file-op-5"))
        failed = FileOperationResult.fail(request, error_message="missing")

        with self.assertRaisesRegex(ValueError, "successful file operation"):
            FileOperationContextLinker().build_update(
                result=failed,
                source_event_sequence=16,
            )

        succeeded = FileOperationResult.succeed(request)
        with self.assertRaisesRegex(ValueError, "positive integer"):
            FileOperationContextLinker().build_update(
                result=succeeded,
                source_event_sequence=0,
            )


def _request(
    *,
    operation_id: FileOperationId,
    requested_by_agent_id: AgentId | None = None,
) -> FileOperationRequest:
    return FileOperationRequest.create(
        operation_id=operation_id,
        workspace_id=WorkspaceId("workspace-1"),
        operation_kind=FileOperationKind.READ_FILE,
        relative_path="docs/note.md",
        requested_by_agent_id=requested_by_agent_id,
    )


if __name__ == "__main__":
    unittest.main()
