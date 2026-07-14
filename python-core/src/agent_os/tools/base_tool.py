from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from agent_os.tools.logging_hooks import ToolHookRunner, ToolLoggingHook
from agent_os.tools.sandbox import SandboxPolicy
from agent_os.tools.tool_interface import Tool, ToolInvocation, ToolResult, ToolValidation


@dataclass(slots=True, kw_only=True)
class BaseTool(Tool, ABC):
    """Reusable local-tool base with validation, sandboxing, and logging hooks."""

    sandbox: SandboxPolicy
    hooks: tuple[ToolLoggingHook, ...] = ()
    name: str = field(init=False)
    _hook_runner: ToolHookRunner = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.name = self.__class__.__name__
        self._hook_runner = ToolHookRunner(tuple(self.hooks))

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        await self._hook_runner.validation_started(self.name, invocation)
        validation = self.validate(invocation)
        await self._hook_runner.validation_finished(self.name, invocation, validation)

        if not validation.is_valid:
            return ToolResult(
                status="validation_failed",
                output={"errors": validation.errors},
            )

        await self._hook_runner.execution_started(self.name, invocation)
        try:
            result = await self._execute(invocation)
        except Exception as exc:
            await self._hook_runner.execution_failed(self.name, invocation, exc)
            raise

        await self._hook_runner.execution_finished(self.name, invocation, result)
        return result

    def validate(self, invocation: ToolInvocation) -> ToolValidation:
        return self._validate(invocation)

    @abstractmethod
    def _validate(self, invocation: ToolInvocation) -> ToolValidation:
        ...

    @abstractmethod
    async def _execute(self, invocation: ToolInvocation) -> ToolResult:
        ...
