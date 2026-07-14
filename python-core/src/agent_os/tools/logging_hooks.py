from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from agent_os.tools.tool_interface import ToolInvocation, ToolResult, ToolValidation


@dataclass(frozen=True, slots=True)
class ToolLogEvent:
    """Structured log event emitted around tool lifecycle phases."""

    tool_name: str
    phase: str
    invocation: ToolInvocation
    payload: dict[str, Any] = field(default_factory=dict)


class ToolLoggingHook(ABC):
    """Hook contract for observing tool lifecycle events."""

    @abstractmethod
    async def emit(self, event: ToolLogEvent) -> None:
        ...


@dataclass(slots=True)
class ToolHookRunner:
    """Sequential dispatcher for registered tool logging hooks."""

    hooks: tuple[ToolLoggingHook, ...] = ()

    async def validation_started(self, tool_name: str, invocation: ToolInvocation) -> None:
        await self._emit(ToolLogEvent(tool_name=tool_name, phase="validation_started", invocation=invocation))

    async def validation_finished(
        self,
        tool_name: str,
        invocation: ToolInvocation,
        validation: ToolValidation,
    ) -> None:
        await self._emit(
            ToolLogEvent(
                tool_name=tool_name,
                phase="validation_finished",
                invocation=invocation,
                payload={"is_valid": validation.is_valid, "errors": validation.errors},
            )
        )

    async def execution_started(self, tool_name: str, invocation: ToolInvocation) -> None:
        await self._emit(ToolLogEvent(tool_name=tool_name, phase="execution_started", invocation=invocation))

    async def execution_finished(
        self,
        tool_name: str,
        invocation: ToolInvocation,
        result: ToolResult,
    ) -> None:
        await self._emit(
            ToolLogEvent(
                tool_name=tool_name,
                phase="execution_finished",
                invocation=invocation,
                payload={"status": result.status, "output": dict(result.output)},
            )
        )

    async def execution_failed(
        self,
        tool_name: str,
        invocation: ToolInvocation,
        error: Exception,
    ) -> None:
        await self._emit(
            ToolLogEvent(
                tool_name=tool_name,
                phase="execution_failed",
                invocation=invocation,
                payload={"error_type": type(error).__name__, "error_message": str(error)},
            )
        )

    async def _emit(self, event: ToolLogEvent) -> None:
        for hook in self.hooks:
            await hook.emit(event)
