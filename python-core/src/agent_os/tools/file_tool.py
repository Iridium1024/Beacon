from __future__ import annotations

from dataclasses import dataclass

from agent_os.domain.ports.filesystem import FileReadRequest, FileWriteRequest, FilesystemPort
from agent_os.tools.base_tool import BaseTool
from agent_os.tools.tool_interface import ToolInvocation, ToolResult, ToolValidation


@dataclass(slots=True, kw_only=True)
class FileTool(BaseTool):
    """Sandboxed local file read/write tool."""

    filesystem: FilesystemPort

    def _validate(self, invocation: ToolInvocation) -> ToolValidation:
        errors: list[str] = []
        operation = invocation.arguments.get("operation")
        path = invocation.arguments.get("path")

        if operation not in {"read", "write"}:
            errors.append("Argument 'operation' must be 'read' or 'write'.")

        if not isinstance(path, str) or not path:
            errors.append("Argument 'path' must be a non-empty string.")
        else:
            try:
                self.sandbox.resolve_path(path)
            except ValueError as exc:
                errors.append(str(exc))

        if operation == "write":
            if not self.sandbox.writable:
                errors.append("Sandbox is read-only.")
            if not isinstance(invocation.arguments.get("content"), str):
                errors.append("Argument 'content' must be a string for write operations.")

        create_parents = invocation.arguments.get("create_parents", False)
        if not isinstance(create_parents, bool):
            errors.append("Argument 'create_parents' must be a boolean when provided.")

        return ToolValidation(is_valid=not errors, errors=tuple(errors))

    async def _execute(self, invocation: ToolInvocation) -> ToolResult:
        operation = str(invocation.arguments["operation"])
        path = str(self.sandbox.resolve_path(str(invocation.arguments["path"])))

        if operation == "read":
            content = await self.filesystem.read_text(FileReadRequest(path=path))
            return ToolResult(
                status="success",
                output={"operation": "read", "path": path, "content": content},
            )

        await self.filesystem.write_text(
            FileWriteRequest(
                path=path,
                content=str(invocation.arguments["content"]),
                create_parents=bool(invocation.arguments.get("create_parents", False)),
            )
        )
        return ToolResult(
            status="success",
            output={"operation": "write", "path": path},
        )
