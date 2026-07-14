from __future__ import annotations

from dataclasses import dataclass

from agent_os.tools.base_tool import BaseTool
from agent_os.tools.tool_interface import ToolInvocation, ToolResult, ToolValidation


@dataclass(slots=True, kw_only=True)
class GitTool(BaseTool):
    """Placeholder Git tool reserved for future local repository integration."""

    def _validate(self, invocation: ToolInvocation) -> ToolValidation:
        errors: list[str] = []
        action = invocation.arguments.get("action")
        workdir = invocation.arguments.get("workdir", ".")

        if not self.sandbox.allow_git_operations:
            errors.append("Git operations are disabled by sandbox policy.")

        if not isinstance(action, str) or not action:
            errors.append("Argument 'action' must be a non-empty string.")

        if not isinstance(workdir, str) or not workdir:
            errors.append("Argument 'workdir' must be a non-empty string when provided.")
        else:
            try:
                self.sandbox.resolve_path(workdir)
            except ValueError as exc:
                errors.append(str(exc))

        return ToolValidation(is_valid=not errors, errors=tuple(errors))

    async def _execute(self, invocation: ToolInvocation) -> ToolResult:
        return ToolResult(
            status="not_implemented",
            output={
                "action": invocation.arguments.get("action"),
                "workdir": str(self.sandbox.resolve_path(str(invocation.arguments.get("workdir", ".")))),
            },
        )
