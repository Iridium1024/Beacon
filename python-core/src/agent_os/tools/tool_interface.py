from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    """A decoupled tool invocation contract."""

    tool_name: str
    arguments: Mapping[str, object] = field(default_factory=dict)
    context: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolValidation:
    """Validation outcome for a tool invocation."""

    is_valid: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Result contract emitted by a tool execution."""

    status: str
    output: Mapping[str, object] = field(default_factory=dict)


class Tool(ABC):
    """Abstract contract for agent-callable tools."""

    @abstractmethod
    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        ...

    @abstractmethod
    def validate(self, invocation: ToolInvocation) -> ToolValidation:
        ...
