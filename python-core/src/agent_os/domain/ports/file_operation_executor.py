from __future__ import annotations

from typing import Protocol

from agent_os.domain.entities.file_operation import FileOperationRequest, FileOperationResult


class FileOperationExecutorPort(Protocol):
    """Contract for controlled workspace file operation execution."""

    def execute_file_operation(self, request: FileOperationRequest) -> FileOperationResult:
        ...
