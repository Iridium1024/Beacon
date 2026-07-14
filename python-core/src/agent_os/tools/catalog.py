from __future__ import annotations

from agent_os.tools.code_executor_tool import CodeExecutorTool
from agent_os.tools.file_tool import FileTool
from agent_os.tools.git_tool import GitTool
from agent_os.tools.registry import ToolRegistry


def register_builtin_tools(registry: ToolRegistry) -> ToolRegistry:
    """Register built-in pluggable local tools."""

    registry.register("file", FileTool)
    registry.register("code-executor", CodeExecutorTool)
    registry.register("git", GitTool)
    return registry


def create_default_tool_registry() -> ToolRegistry:
    """Create a registry seeded with the built-in local tools."""

    return register_builtin_tools(ToolRegistry())
