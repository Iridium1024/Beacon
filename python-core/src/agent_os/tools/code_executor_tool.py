from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

from agent_os.tools.base_tool import BaseTool
from agent_os.tools.tool_interface import ToolInvocation, ToolResult, ToolValidation


@dataclass(slots=True, kw_only=True)
class CodeExecutorTool(BaseTool):
    """Sandboxed local code execution tool with command allow-list validation."""

    async def _execute(self, invocation: ToolInvocation) -> ToolResult:
        command = [str(part) for part in invocation.arguments["command"]]
        workdir = self._resolve_workdir(invocation)
        timeout_seconds = float(invocation.arguments.get("timeout_seconds", 30))
        env = self._validated_env(invocation)

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(workdir),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
        except TimeoutError:
            process.kill()
            await process.communicate()
            return ToolResult(
                status="timeout",
                output={
                    "command": tuple(command),
                    "workdir": str(workdir),
                    "timeout_seconds": timeout_seconds,
                },
            )

        return ToolResult(
            status="success" if process.returncode == 0 else "failed",
            output={
                "command": tuple(command),
                "workdir": str(workdir),
                "returncode": process.returncode,
                "stdout": stdout_bytes.decode("utf-8", errors="replace"),
                "stderr": stderr_bytes.decode("utf-8", errors="replace"),
            },
        )

    def _validate(self, invocation: ToolInvocation) -> ToolValidation:
        errors: list[str] = []
        command = invocation.arguments.get("command")
        workdir = invocation.arguments.get("workdir", ".")
        timeout_seconds = invocation.arguments.get("timeout_seconds", 30)
        env = invocation.arguments.get("env", {})

        if not isinstance(command, (list, tuple)) or not command:
            errors.append("Argument 'command' must be a non-empty sequence of strings.")
        else:
            for part in command:
                if not isinstance(part, str) or not part:
                    errors.append("Argument 'command' must only contain non-empty strings.")
                    break

            if not errors and not self.sandbox.is_command_allowed(str(command[0])):
                errors.append(f"Command '{command[0]}' is not allowed by sandbox policy.")

        if not isinstance(workdir, str) or not workdir:
            errors.append("Argument 'workdir' must be a non-empty string when provided.")
        else:
            try:
                self.sandbox.resolve_path(workdir)
            except ValueError as exc:
                errors.append(str(exc))

        if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            errors.append("Argument 'timeout_seconds' must be a positive number when provided.")

        if not isinstance(env, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()):
            errors.append("Argument 'env' must be a mapping of string keys to string values.")

        return ToolValidation(is_valid=not errors, errors=tuple(errors))

    def _resolve_workdir(self, invocation: ToolInvocation) -> Path:
        workdir = str(invocation.arguments.get("workdir", "."))
        return self.sandbox.resolve_path(workdir)

    def _validated_env(self, invocation: ToolInvocation) -> dict[str, str]:
        env = dict(os.environ)
        for key, value in dict(invocation.arguments.get("env", {})).items():
            env[str(key)] = str(value)
        return env
