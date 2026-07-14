from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol

from agent_os.domain.entities.file_operation import (
    FileOperationKind,
    FileOperationRequest,
    FileOperationResult,
)
from agent_os.domain.ports.file_operation_executor import FileOperationExecutorPort
from agent_os.domain.value_objects.identifiers import PlatformEventId, PlatformRunSessionId


class FileOperationAuditRecorderPort(Protocol):
    """Audit boundary for recorded file operation results."""

    def record_file_operation_event(
        self,
        *,
        request: FileOperationRequest,
        result: FileOperationResult | None = None,
        event_id: PlatformEventId | None = None,
        occurred_at: datetime | None = None,
        session_id: PlatformRunSessionId | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> int:
        ...


@dataclass(frozen=True, slots=True)
class RecordedFileOperationResult:
    """Application-level result after execution and audit recording."""

    result: FileOperationResult
    source_event_sequence: int


@dataclass(slots=True)
class FileOperationService:
    """Executes platform file operations and records their audit event."""

    executor: FileOperationExecutorPort
    audit_recorder: FileOperationAuditRecorderPort

    def execute_and_record(
        self,
        request: FileOperationRequest,
        *,
        event_id: PlatformEventId | None = None,
        occurred_at: datetime | None = None,
        session_id: PlatformRunSessionId | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> RecordedFileOperationResult:
        try:
            result = self.executor.execute_file_operation(request)
        except Exception as exc:
            result = FileOperationResult.fail(
                request,
                error_message=f"File operation executor raised {type(exc).__name__}: {exc}.",
                metadata={"executor_exception_type": type(exc).__name__},
            )

        audit_result = audit_safe_file_operation_result(result)
        source_event_sequence = self.audit_recorder.record_file_operation_event(
            request=request,
            result=audit_result,
            event_id=event_id,
            occurred_at=occurred_at,
            session_id=session_id,
            metadata=metadata,
        )
        return RecordedFileOperationResult(
            result=result,
            source_event_sequence=source_event_sequence,
        )


def audit_safe_file_operation_result(result: FileOperationResult) -> FileOperationResult:
    """Return a result suitable for persistence without storing full read bodies."""

    output_payload = dict(result.output_payload)
    metadata = dict(result.metadata)

    if result.operation_kind == FileOperationKind.READ_FILE and "content" in output_payload:
        content = output_payload.pop("content")
        output_payload["content_persisted"] = False
        output_payload["content_length"] = len(content) if isinstance(content, str) else None
        metadata["content_redacted_from_audit"] = True

    if output_payload == result.output_payload and metadata == result.metadata:
        return result

    return FileOperationResult(
        operation_id=result.operation_id,
        workspace_id=result.workspace_id,
        operation_kind=result.operation_kind,
        relative_path=result.relative_path,
        status=result.status,
        completed_at=result.completed_at,
        requested_by_agent_id=result.requested_by_agent_id,
        invocation_id=result.invocation_id,
        task_id=result.task_id,
        context_update_id=result.context_update_id,
        bytes_read=result.bytes_read,
        bytes_written=result.bytes_written,
        output_payload=output_payload,
        error_message=result.error_message,
        metadata=metadata,
    )
