from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    """Shared sandbox policy for local tool execution."""

    root_path: Path | str
    allowed_commands: tuple[str, ...] = ()
    allow_git_operations: bool = False
    writable: bool = True
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "root_path", Path(self.root_path).resolve(strict=False))

    def resolve_path(self, candidate: str) -> Path:
        base_path = self.root_path
        candidate_path = Path(candidate)
        resolved = (
            candidate_path.resolve(strict=False)
            if candidate_path.is_absolute()
            else (base_path / candidate_path).resolve(strict=False)
        )

        if not self.is_within_root(resolved):
            raise ValueError(f"Path '{candidate}' escapes sandbox root '{base_path}'.")

        return resolved

    def is_within_root(self, candidate: Path | str) -> bool:
        resolved = Path(candidate).resolve(strict=False)
        try:
            resolved.relative_to(self.root_path)
            return True
        except ValueError:
            return False

    def is_command_allowed(self, command_name: str) -> bool:
        if not self.allowed_commands:
            return False

        normalized = Path(command_name).name.lower()
        return normalized in {command.lower() for command in self.allowed_commands}
