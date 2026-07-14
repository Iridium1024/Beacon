from __future__ import annotations

from dataclasses import dataclass

from agent_os.domain.ports.filesystem import (
    DirectoryListRequest,
    FileReadRequest,
    FileWriteRequest,
    FilesystemPort,
    PathEntry,
)


@dataclass(slots=True)
class SandboxedFilesystemAdapter(FilesystemPort):
    """Placeholder adapter for bounded local filesystem access."""

    sandbox_root: str

    async def read_text(self, request: FileReadRequest) -> str:
        raise NotImplementedError("Sandboxed reads are intentionally undefined in this scaffold.")

    async def write_text(self, request: FileWriteRequest) -> None:
        raise NotImplementedError("Sandboxed writes are intentionally undefined in this scaffold.")

    async def list_directory(self, request: DirectoryListRequest) -> tuple[PathEntry, ...]:
        raise NotImplementedError("Sandboxed listing is intentionally undefined in this scaffold.")
