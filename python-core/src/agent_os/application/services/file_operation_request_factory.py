from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from agent_os.domain.entities.file_operation import FileOperationKind, FileOperationRequest
from agent_os.domain.entities.workspace import ProjectBinding, ProjectWorkspace, WorkspaceStatus
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    FileOperationId,
    TaskId,
)


@dataclass(frozen=True, slots=True)
class WorkspaceFileOperationPolicy:
    """Policy for workspace-bound file operation request creation."""

    allow_read_file: bool = True
    allow_list_directory: bool = True
    allow_recursive_listing: bool = False
    allow_write_file: bool = False

    def validate(self, binding: ProjectBinding, operation_kind: FileOperationKind, *, recursive: bool) -> None:
        if operation_kind == FileOperationKind.READ_FILE:
            if not self.allow_read_file:
                raise ValueError("read file operations are not allowed by workspace policy.")
            return

        if operation_kind == FileOperationKind.LIST_DIRECTORY:
            if not self.allow_list_directory:
                raise ValueError("directory listing operations are not allowed by workspace policy.")
            if recursive and not self.allow_recursive_listing:
                raise ValueError("recursive directory listing is not allowed by workspace policy.")
            return

        if operation_kind == FileOperationKind.WRITE_FILE:
            if not binding.writable:
                raise ValueError("write file operations are not allowed for a read-only workspace binding.")
            if not self.allow_write_file:
                raise ValueError("write file operations are not allowed by workspace policy.")
            return

        raise ValueError("unsupported file operation kind.")


@dataclass(frozen=True, slots=True)
class WorkspaceFileOperationRequestFactory:
    """Creates policy-checked file operation requests for one workspace binding."""

    workspace: ProjectWorkspace
    binding: ProjectBinding
    policy: WorkspaceFileOperationPolicy = field(default_factory=WorkspaceFileOperationPolicy)

    def __post_init__(self) -> None:
        if self.workspace.workspace_id != self.binding.workspace_id:
            raise ValueError("workspace and binding must target the same workspace_id.")
        if self.workspace.status != WorkspaceStatus.ACTIVE:
            raise ValueError("file operation requests require an active workspace.")

    def create_request(
        self,
        *,
        operation_kind: FileOperationKind,
        relative_path: str,
        operation_id: FileOperationId | None = None,
        requested_at: datetime | None = None,
        requested_by_agent_id: AgentId | None = None,
        invocation_id: AgentInvocationId | None = None,
        task_id: TaskId | None = None,
        content: str | None = None,
        create_parents: bool = False,
        recursive: bool = False,
        reason: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> FileOperationRequest:
        self.policy.validate(self.binding, operation_kind, recursive=recursive)
        return FileOperationRequest.create(
            operation_id=operation_id,
            workspace_id=self.workspace.workspace_id,
            operation_kind=operation_kind,
            relative_path=relative_path,
            requested_at=requested_at,
            requested_by_agent_id=requested_by_agent_id,
            invocation_id=invocation_id,
            task_id=task_id,
            content=content,
            create_parents=create_parents,
            recursive=recursive,
            reason=reason,
            metadata=dict(metadata or {}),
        )
