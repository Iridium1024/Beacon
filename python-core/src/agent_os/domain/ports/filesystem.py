from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class FileReadRequest:
    """A sandbox-aware file read request."""

    path: str


@dataclass(frozen=True, slots=True)
class FileWriteRequest:
    """A sandbox-aware file write request."""

    path: str
    content: str
    create_parents: bool = False


@dataclass(frozen=True, slots=True)
class DirectoryListRequest:
    """A sandbox-aware directory listing request."""

    path: str
    recursive: bool = False


@dataclass(frozen=True, slots=True)
class PathEntry:
    """Metadata returned for sandbox-visible files and directories."""

    path: str
    is_directory: bool


class FilesystemPort(Protocol):
    """Contract for sandboxed local filesystem access."""

    async def read_text(self, request: FileReadRequest) -> str:
        ...

    async def write_text(self, request: FileWriteRequest) -> None:
        ...

    async def list_directory(self, request: DirectoryListRequest) -> tuple[PathEntry, ...]:
        ...
