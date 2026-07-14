from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from agent_os.domain.entities.context import (
    ContextUpdateInfo,
    ContextUpdateKind,
    ProjectSharedContext,
)
from agent_os.domain.entities.file_operation import (
    FileOperationKind,
    FileOperationResult,
    FileOperationResultStatus,
)
from agent_os.domain.value_objects.identifiers import ContextUpdateId


@dataclass(frozen=True, slots=True)
class FileOperationContextLinker:
    """Builds context updates from successful file-operation results."""

    def build_update(
        self,
        *,
        result: FileOperationResult,
        source_event_sequence: int,
        update_id: ContextUpdateId | None = None,
        created_at: datetime | None = None,
        summary: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> ContextUpdateInfo:
        if source_event_sequence < 1:
            raise ValueError("source_event_sequence must be a positive integer.")
        if result.status != FileOperationResultStatus.SUCCEEDED:
            raise ValueError("only successful file operation results can become context file references.")
        if update_id is not None and result.context_update_id is not None:
            if update_id != result.context_update_id:
                raise ValueError("update_id must match result context_update_id when both are provided.")

        resolved_update_id = update_id or result.context_update_id or ContextUpdateId.new()
        file_operation_state = _file_operation_state(
            result,
            source_event_sequence=source_event_sequence,
        )
        return ContextUpdateInfo.create(
            update_id=resolved_update_id,
            workspace_id=result.workspace_id,
            update_kind=ContextUpdateKind.FILE_REFERENCE,
            summary=summary or _default_summary(result),
            created_at=created_at or result.completed_at,
            source_agent_id=result.requested_by_agent_id,
            payload={
                "file_operation": file_operation_state,
            },
            materialized_state_patch={
                "last_file_operation": {
                    "operation_id": result.operation_id.value,
                    "operation_kind": result.operation_kind.value,
                    "relative_path": result.relative_path,
                    "status": result.status.value,
                    "source_event_sequence": source_event_sequence,
                },
            },
            metadata={
                "source": "file_operation_result",
                "content_redacted_from_context": True,
                **dict(metadata or {}),
            },
        )

    def append_result(
        self,
        *,
        context: ProjectSharedContext,
        result: FileOperationResult,
        source_event_sequence: int,
        update_id: ContextUpdateId | None = None,
        created_at: datetime | None = None,
        summary: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> ProjectSharedContext:
        update = self.build_update(
            result=result,
            source_event_sequence=source_event_sequence,
            update_id=update_id,
            created_at=created_at,
            summary=summary,
            metadata=metadata,
        )
        return context.append_update(update)


def _default_summary(result: FileOperationResult) -> str:
    if result.operation_kind == FileOperationKind.READ_FILE:
        return f"Read workspace file: {result.relative_path}"
    if result.operation_kind == FileOperationKind.LIST_DIRECTORY:
        return f"Listed workspace directory: {result.relative_path}"
    if result.operation_kind == FileOperationKind.WRITE_FILE:
        return f"Wrote workspace file: {result.relative_path}"
    return f"Recorded workspace file operation: {result.relative_path}"


def _file_operation_state(
    result: FileOperationResult,
    *,
    source_event_sequence: int,
) -> Mapping[str, object | None]:
    return {
        "operation_id": result.operation_id.value,
        "workspace_id": result.workspace_id.value,
        "operation_kind": result.operation_kind.value,
        "relative_path": result.relative_path,
        "status": result.status.value,
        "source_event_sequence": source_event_sequence,
        "requested_by_agent_id": (
            result.requested_by_agent_id.value
            if result.requested_by_agent_id is not None
            else None
        ),
        "invocation_id": (
            result.invocation_id.value
            if result.invocation_id is not None
            else None
        ),
        "task_id": result.task_id.value if result.task_id is not None else None,
        "bytes_read": result.bytes_read,
        "bytes_written": result.bytes_written,
        "output_payload": _redacted_output_payload(result.output_payload),
    }


def _redacted_output_payload(output_payload: Mapping[str, object]) -> Mapping[str, object]:
    redacted: dict[str, object] = {}
    for key, value in output_payload.items():
        if key == "content":
            redacted["content_persisted"] = False
            redacted["content_length"] = len(value) if isinstance(value, str) else None
            continue
        redacted[key] = value
    return redacted
