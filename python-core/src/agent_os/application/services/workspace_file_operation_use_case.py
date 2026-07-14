from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from agent_os.application.services.file_operation_request_factory import (
    WorkspaceFileOperationRequestFactory,
)
from agent_os.application.services.file_operation_service import (
    FileOperationService,
    RecordedFileOperationResult,
)
from agent_os.domain.entities.file_operation import FileOperationKind
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    FileOperationId,
    PlatformEventId,
    PlatformRunSessionId,
    TaskId,
)


@dataclass(slots=True)
class WorkspaceFileOperationUseCase:
    """Local Python-only facade for policy-checked workspace file operations."""

    request_factory: WorkspaceFileOperationRequestFactory
    operation_service: FileOperationService

    def read_file(
        self,
        *,
        relative_path: str,
        operation_id: FileOperationId | None = None,
        requested_at: datetime | None = None,
        requested_by_agent_id: AgentId | None = None,
        invocation_id: AgentInvocationId | None = None,
        task_id: TaskId | None = None,
        event_id: PlatformEventId | None = None,
        occurred_at: datetime | None = None,
        session_id: PlatformRunSessionId | None = None,
        reason: str | None = None,
        request_metadata: Mapping[str, object] | None = None,
        audit_metadata: Mapping[str, object] | None = None,
    ) -> RecordedFileOperationResult:
        request = self.request_factory.create_request(
            operation_id=operation_id,
            operation_kind=FileOperationKind.READ_FILE,
            relative_path=relative_path,
            requested_at=requested_at,
            requested_by_agent_id=requested_by_agent_id,
            invocation_id=invocation_id,
            task_id=task_id,
            reason=reason,
            metadata=dict(request_metadata or {}),
        )
        return self.operation_service.execute_and_record(
            request,
            event_id=event_id,
            occurred_at=occurred_at,
            session_id=session_id,
            metadata=dict(audit_metadata or {}),
        )

    def list_directory(
        self,
        *,
        relative_path: str = ".",
        recursive: bool = False,
        operation_id: FileOperationId | None = None,
        requested_at: datetime | None = None,
        requested_by_agent_id: AgentId | None = None,
        invocation_id: AgentInvocationId | None = None,
        task_id: TaskId | None = None,
        event_id: PlatformEventId | None = None,
        occurred_at: datetime | None = None,
        session_id: PlatformRunSessionId | None = None,
        reason: str | None = None,
        request_metadata: Mapping[str, object] | None = None,
        audit_metadata: Mapping[str, object] | None = None,
    ) -> RecordedFileOperationResult:
        request = self.request_factory.create_request(
            operation_id=operation_id,
            operation_kind=FileOperationKind.LIST_DIRECTORY,
            relative_path=relative_path,
            requested_at=requested_at,
            requested_by_agent_id=requested_by_agent_id,
            invocation_id=invocation_id,
            task_id=task_id,
            recursive=recursive,
            reason=reason,
            metadata=dict(request_metadata or {}),
        )
        return self.operation_service.execute_and_record(
            request,
            event_id=event_id,
            occurred_at=occurred_at,
            session_id=session_id,
            metadata=dict(audit_metadata or {}),
        )
