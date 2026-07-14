from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from agent_os.domain.entities.file_operation import (
    FileOperationKind,
    FileOperationRequest,
    FileOperationResult,
)
from agent_os.domain.ports.file_operation_executor import FileOperationExecutorPort
from agent_os.domain.value_objects.identifiers import WorkspaceId


class WorkspacePathViolation(ValueError):
    """Raised when a requested workspace-relative path escapes the workspace root."""


def resolve_workspace_relative_path(
    root_path: Path | str,
    relative_path: str,
    *,
    allow_root: bool = False,
) -> Path:
    """Resolve a workspace-relative path while enforcing the workspace root boundary."""

    if not relative_path.strip():
        raise WorkspacePathViolation("relative_path must be a non-empty workspace-relative path.")

    normalized = relative_path.replace("\\", "/")
    if normalized == ".":
        if allow_root:
            return Path(root_path).resolve(strict=False)
        raise WorkspacePathViolation("workspace root path is only allowed for directory listing.")

    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise WorkspacePathViolation("relative_path must be workspace-relative.")

    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise WorkspacePathViolation("relative_path must not contain empty, current, or parent segments.")

    root = Path(root_path).resolve(strict=False)
    resolved = (root / Path(*parts)).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise WorkspacePathViolation("relative_path escapes the workspace root.") from exc

    return resolved


@dataclass(frozen=True, slots=True)
class WorkspaceFileOperationAdapter(FileOperationExecutorPort):
    """Read/list-only adapter for executing platform file operation requests."""

    workspace_id: WorkspaceId
    root_path: Path | str
    encoding: str = "utf-8"

    def __post_init__(self) -> None:
        object.__setattr__(self, "root_path", Path(self.root_path).resolve(strict=False))

    def execute_file_operation(self, request: FileOperationRequest) -> FileOperationResult:
        if request.workspace_id != self.workspace_id:
            return FileOperationResult.deny(
                request,
                error_message="File operation request targets a different workspace.",
            )

        if request.operation_kind == FileOperationKind.READ_FILE:
            return self._read_file(request)
        if request.operation_kind == FileOperationKind.LIST_DIRECTORY:
            return self._list_directory(request)
        if request.operation_kind == FileOperationKind.WRITE_FILE:
            return FileOperationResult.deny(
                request,
                error_message="Write file operations are not enabled in this adapter.",
            )

        return FileOperationResult.deny(
            request,
            error_message="Unsupported file operation kind.",
        )

    def _read_file(self, request: FileOperationRequest) -> FileOperationResult:
        try:
            target_path = resolve_workspace_relative_path(self.root_path, request.relative_path)
        except WorkspacePathViolation as exc:
            return FileOperationResult.deny(request, error_message=str(exc))

        if not target_path.exists():
            return FileOperationResult.fail(request, error_message="Requested file does not exist.")
        if not target_path.is_file():
            return FileOperationResult.fail(request, error_message="Requested path is not a file.")

        try:
            with target_path.open("r", encoding=self.encoding) as file_handle:
                content = file_handle.read()
        except OSError as exc:
            return FileOperationResult.fail(request, error_message=f"Unable to read requested file: {exc}.")
        except UnicodeDecodeError as exc:
            return FileOperationResult.fail(request, error_message=f"Unable to decode requested file: {exc}.")

        return FileOperationResult.succeed(
            request,
            bytes_read=len(content.encode(self.encoding)),
            output_payload={
                "content": content,
                "encoding": self.encoding,
            },
        )

    def _list_directory(self, request: FileOperationRequest) -> FileOperationResult:
        if request.recursive:
            return FileOperationResult.deny(
                request,
                error_message="Recursive directory listing is not enabled in this adapter.",
            )

        try:
            target_path = resolve_workspace_relative_path(
                self.root_path,
                request.relative_path,
                allow_root=True,
            )
        except WorkspacePathViolation as exc:
            return FileOperationResult.deny(request, error_message=str(exc))

        if not target_path.exists():
            return FileOperationResult.fail(request, error_message="Requested directory does not exist.")
        if not target_path.is_dir():
            return FileOperationResult.fail(request, error_message="Requested path is not a directory.")

        try:
            entries = tuple(self._path_entry(child) for child in sorted(target_path.iterdir(), key=_sort_key))
        except OSError as exc:
            return FileOperationResult.fail(request, error_message=f"Unable to list requested directory: {exc}.")

        visible_entries = tuple(entry for entry in entries if entry is not None)
        return FileOperationResult.succeed(
            request,
            output_payload={
                "entries": visible_entries,
            },
        )

    def _path_entry(self, path: Path) -> Mapping[str, object] | None:
        root = Path(self.root_path)
        resolved_path = path.resolve(strict=False)
        try:
            relative_path = resolved_path.relative_to(root).as_posix()
        except ValueError:
            return None

        entry: dict[str, object] = {
            "name": path.name,
            "relative_path": relative_path,
            "kind": "directory" if path.is_dir() else "file",
        }
        if path.is_file():
            entry["size_bytes"] = path.stat().st_size
        return entry


def _sort_key(path: Path) -> tuple[str, str]:
    return (path.name.casefold(), path.name)
