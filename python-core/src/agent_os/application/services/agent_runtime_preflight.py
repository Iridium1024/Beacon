from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from agent_os.application.services.provider_permission_profiles import (
    default_provider_permission_profile_metadata,
)


SUPPORTED_AGENT_RUNTIME_TOOLS = (
    "claude",
    "codex",
    "gemini",
    "hermes",
    "opencode",
    "openclaw",
)

DEFAULT_AGENT_RUNTIME_TOOLS = (
    "claude",
    "codex",
    "gemini",
    "hermes",
)

_VERSION_RE = re.compile(r"\d+\.\d+\.\d+(?:[-+][\w.]+)?")


@dataclass(frozen=True, slots=True)
class AgentRuntimeCandidate:
    path: str
    real_path: str
    source: str
    runnable: bool
    version: str | None = None
    error: str | None = None
    is_path_default: bool = False

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "schema": "agent_runtime_candidate.v1",
            "path": self.path,
            "realPath": self.real_path,
            "source": self.source,
            "runnable": self.runnable,
            "isPathDefault": self.is_path_default,
        }
        if self.version is not None:
            metadata["version"] = self.version
        if self.error is not None:
            metadata["error"] = self.error
        return metadata


@dataclass(frozen=True, slots=True)
class AgentRuntimeToolPreflight:
    tool: str
    env_type: str
    status: str
    activation_ready: bool
    candidates: tuple[AgentRuntimeCandidate, ...]
    recommended_executable: str | None = None
    path_default: str | None = None
    has_conflict: bool = False
    warning: str | None = None

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "schema": "agent_runtime_tool_preflight.v1",
            "tool": self.tool,
            "envType": self.env_type,
            "status": self.status,
            "activationReady": self.activation_ready,
            "hasConflict": self.has_conflict,
            "candidates": [candidate.to_metadata() for candidate in self.candidates],
        }
        if self.recommended_executable is not None:
            metadata["recommendedExecutable"] = self.recommended_executable
        if self.path_default is not None:
            metadata["pathDefault"] = self.path_default
        if self.warning is not None:
            metadata["warning"] = self.warning
        return metadata


def build_agent_runtime_preflight_report(
    *,
    tools: Sequence[str] | None = None,
    timeout_seconds: float = 8.0,
    ticket_path: str | None = None,
    response_path: str | None = None,
) -> Mapping[str, object]:
    normalized_tools = normalize_agent_runtime_tools(tools)
    results = tuple(
        check_agent_runtime_tool(tool, timeout_seconds=timeout_seconds)
        for tool in normalized_tools
    )
    available = sum(1 for result in results if result.status == "available")
    broken = sum(1 for result in results if result.status == "installed_but_broken")
    missing = sum(1 for result in results if result.status == "not_found")
    conflicts = sum(1 for result in results if result.has_conflict)
    activation_ready = sum(1 for result in results if result.activation_ready)
    return {
        "schema": "agent_runtime_preflight_report.v1",
        "readOnly": True,
        "noInstallAttempted": True,
        "noRepairAttempted": True,
        "noCredentialOrConfigWrite": True,
        "tools": [result.to_metadata() for result in results],
        "activationCapabilities": _activation_capability_checks(
            results,
            ticket_path=ticket_path,
            response_path=response_path,
            timeout_seconds=timeout_seconds,
        ),
        "summary": {
            "checked": len(results),
            "available": available,
            "installedButBroken": broken,
            "notFound": missing,
            "conflicts": conflicts,
            "activationReady": activation_ready,
        },
    }


def _activation_capability_checks(
    results: Sequence[AgentRuntimeToolPreflight],
    *,
    ticket_path: str | None,
    response_path: str | None,
    timeout_seconds: float,
) -> Mapping[str, object]:
    provider_permission_profiles = {
        result.tool: default_provider_permission_profile_metadata(result.tool)
        for result in results
    }
    return {
        "schema": "agent_runtime_activation_capabilities.v1",
        "ticketPathReadable": _ticket_path_readable(ticket_path),
        "responsePathWritable": _response_path_writable(response_path),
        "subprocessAllowed": _subprocess_allowed(timeout_seconds),
        "platformCliRunnable": _platform_cli_runnable(timeout_seconds),
        "providerExecutableFound": {
            result.tool: {
                "tool": result.tool,
                "found": result.recommended_executable is not None,
                "activationReady": result.activation_ready,
                "status": result.status,
                "recommendedExecutable": result.recommended_executable,
            }
            for result in results
        },
        "providerPermissionProfiles": provider_permission_profiles,
    }


def _ticket_path_readable(ticket_path: str | None) -> Mapping[str, object]:
    if ticket_path is None or not ticket_path.strip():
        return {
            "configured": False,
            "status": "not_configured",
            "readable": False,
            "path": None,
        }
    path = Path(ticket_path)
    exists = path.exists()
    readable = path.is_file() and os.access(path, os.R_OK)
    return {
        "configured": True,
        "status": "readable" if readable else "not_readable",
        "readable": readable,
        "path": str(path),
        "exists": exists,
        "isFile": path.is_file() if exists else False,
    }


def _response_path_writable(response_path: str | None) -> Mapping[str, object]:
    if response_path is None or not response_path.strip():
        return {
            "configured": False,
            "status": "not_configured",
            "writable": False,
            "path": None,
            "writeProbeAttempted": False,
        }
    path = Path(response_path)
    parent = path.parent if path.parent != Path("") else Path(".")
    parent_exists = parent.exists()
    writable = parent_exists and os.access(parent, os.W_OK)
    return {
        "configured": True,
        "status": "writable_parent" if writable else "parent_not_writable",
        "writable": writable,
        "path": str(path),
        "parent": str(parent),
        "parentExists": parent_exists,
        "writeProbeAttempted": False,
    }


def _subprocess_allowed(timeout_seconds: float) -> Mapping[str, object]:
    try:
        completed = subprocess.run(
            (sys.executable, "-c", "import sys; sys.exit(0)"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            shell=False,
            timeout=min(timeout_seconds, 8.0),
            **_subprocess_platform_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "allowed": False,
            "status": "failed",
            "error": f"{exc.__class__.__name__}: {exc}",
        }
    return {
        "allowed": completed.returncode == 0,
        "status": "passed" if completed.returncode == 0 else "failed",
        "exitCode": completed.returncode,
    }


def _platform_cli_runnable(timeout_seconds: float) -> Mapping[str, object]:
    env = dict(os.environ)
    pythonpath = os.pathsep.join(item for item in sys.path if item)
    if pythonpath:
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            pythonpath
            if not existing_pythonpath
            else os.pathsep.join((pythonpath, existing_pythonpath))
        )
    try:
        completed = subprocess.run(
            (sys.executable, "-m", "agent_os.local_runtime", "--help"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            shell=False,
            timeout=min(timeout_seconds, 8.0),
            env=env,
            **_subprocess_platform_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "runnable": False,
            "status": "failed",
            "commandKind": "python_module_help",
            "error": f"{exc.__class__.__name__}: {exc}",
        }
    return {
        "runnable": completed.returncode == 0,
        "status": "passed" if completed.returncode == 0 else "failed",
        "commandKind": "python_module_help",
        "exitCode": completed.returncode,
        "stderrTail": _last_lines(completed.stderr or "", 4),
    }


def normalize_agent_runtime_tools(tools: Sequence[str] | None = None) -> tuple[str, ...]:
    requested = tuple(tools or DEFAULT_AGENT_RUNTIME_TOOLS)
    normalized: list[str] = []
    for tool in requested:
        value = tool.strip().lower()
        if value not in SUPPORTED_AGENT_RUNTIME_TOOLS:
            raise ValueError(f"unsupported agent runtime tool: {tool}")
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized)


def check_agent_runtime_tool(
    tool: str,
    *,
    timeout_seconds: float = 8.0,
    path_env: str | None = None,
    include_common_search_paths: bool = True,
) -> AgentRuntimeToolPreflight:
    (normalized_tool,) = normalize_agent_runtime_tools((tool,))
    default_path = _resolve_path_default(normalized_tool, path_env)
    default_real = _real_path(default_path) if default_path is not None else None
    candidates = _enumerate_candidates(
        normalized_tool,
        timeout_seconds=timeout_seconds,
        path_env=path_env,
        include_common_search_paths=include_common_search_paths,
        default_real_path=default_real,
    )
    recommended = _recommended_candidate(candidates)
    status = _tool_status(candidates, recommended)
    conflict = _has_conflict(candidates)
    warning = _tool_warning(
        normalized_tool,
        status=status,
        conflict=conflict,
        recommended=recommended,
        path_default=default_path,
    )
    return AgentRuntimeToolPreflight(
        tool=normalized_tool,
        env_type=_env_type(),
        status=status,
        activation_ready=recommended is not None and recommended.runnable,
        candidates=candidates,
        recommended_executable=recommended.path if recommended is not None else None,
        path_default=default_path,
        has_conflict=conflict,
        warning=warning,
    )


def _enumerate_candidates(
    tool: str,
    *,
    timeout_seconds: float,
    path_env: str | None,
    include_common_search_paths: bool,
    default_real_path: str | None,
) -> tuple[AgentRuntimeCandidate, ...]:
    seen: set[str] = set()
    candidates: list[AgentRuntimeCandidate] = []
    for directory in _build_search_paths(
        tool,
        path_env=path_env,
        include_common_search_paths=include_common_search_paths,
    ):
        for candidate_path in _tool_executable_candidates(tool, directory):
            if not candidate_path.exists():
                continue
            real_path = _real_path(str(candidate_path))
            if real_path in seen:
                continue
            seen.add(real_path)
            version, error = _probe_version(
                tool,
                str(candidate_path),
                timeout_seconds,
            )
            candidates.append(
                AgentRuntimeCandidate(
                    path=str(candidate_path),
                    real_path=real_path,
                    source=_infer_install_source(candidate_path),
                    runnable=version is not None,
                    version=version,
                    error=error,
                    is_path_default=(
                        default_real_path is not None and real_path == default_real_path
                    ),
                )
            )
    return tuple(sorted(candidates, key=lambda item: not item.is_path_default))


def _build_search_paths(
    tool: str,
    *,
    path_env: str | None,
    include_common_search_paths: bool,
) -> tuple[Path, ...]:
    paths: list[Path] = []
    if include_common_search_paths:
        _extend_common_search_paths(paths, tool)
    raw_path = path_env if path_env is not None else os.environ.get("PATH", "")
    for value in raw_path.split(os.pathsep):
        if value:
            _push_unique_path(paths, Path(value))
    return tuple(paths)


def _extend_common_search_paths(paths: list[Path], tool: str) -> None:
    home = Path.home()
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            _push_unique_path(paths, Path(appdata) / "npm")
            if tool == "hermes":
                _extend_python_scripts(paths, Path(appdata) / "Python")
        localappdata = os.environ.get("LOCALAPPDATA")
        if localappdata:
            _push_unique_path(paths, Path(localappdata) / "pnpm")
            _push_unique_path(paths, Path(localappdata) / "Volta" / "bin")
            if tool == "hermes":
                _push_unique_path(
                    paths,
                    Path(localappdata)
                    / "hermes"
                    / "hermes-agent"
                    / "venv"
                    / "Scripts",
                )
                _extend_python_scripts(
                    paths,
                    Path(localappdata) / "Programs" / "Python",
                )
        program_files = os.environ.get("ProgramFiles")
        if program_files:
            _push_unique_path(paths, Path(program_files) / "nodejs")
        _push_env_path(paths, "PNPM_HOME")
        _push_env_child_path(paths, "VOLTA_HOME", "bin")
        _push_env_path(paths, "NVM_SYMLINK")
        _push_env_child_path(paths, "SCOOP", "shims")
        _push_env_child_path(paths, "SCOOP_GLOBAL", "shims")
        nvm_home = os.environ.get("NVM_HOME")
        if nvm_home:
            base = Path(nvm_home)
            _push_unique_path(paths, base)
            _extend_existing_children(paths, base)
        _push_unique_path(paths, home / "scoop" / "shims")
        return

    _push_unique_path(paths, home / ".local" / "bin")
    _push_unique_path(paths, home / ".npm-global" / "bin")
    _push_unique_path(paths, home / "n" / "bin")
    _push_unique_path(paths, home / ".volta" / "bin")
    _push_unique_path(paths, Path("/opt/homebrew/bin"))
    _push_unique_path(paths, Path("/usr/local/bin"))
    _push_unique_path(paths, Path("/usr/bin"))
    _extend_existing_children(paths, home / ".nvm" / "versions" / "node", "bin")
    _extend_existing_children(paths, home / ".local" / "state" / "fnm_multishells", "bin")
    if tool == "opencode":
        _push_unique_path(paths, home / ".opencode" / "bin")
        _push_unique_path(paths, home / ".bun" / "bin")
        _push_unique_path(paths, home / "go" / "bin")


def _tool_executable_candidates(tool: str, directory: Path) -> tuple[Path, ...]:
    if os.name == "nt":
        return (
            directory / f"{tool}.cmd",
            directory / f"{tool}.exe",
            directory / tool,
        )
    return (directory / tool,)


def _probe_version(
    tool: str,
    path: str,
    timeout_seconds: float,
) -> tuple[str | None, str | None]:
    probe_args = (path, "--help") if tool == "hermes" else (path, "--version")
    try:
        completed = subprocess.run(
            probe_args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            shell=False,
            timeout=timeout_seconds,
            **_subprocess_platform_kwargs(),
        )
    except subprocess.TimeoutExpired as exc:
        return None, f"TimeoutExpired: executable probe exceeded {exc.timeout} seconds"
    except OSError as exc:
        return None, f"{exc.__class__.__name__}: {exc}"
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    raw = stdout or stderr
    if completed.returncode == 0 and tool == "hermes":
        return "help_probe_passed", None
    if completed.returncode == 0 and raw:
        return _extract_version(raw), None
    if completed.returncode == 0 and not raw:
        return "unknown", None
    detail = _last_lines(stderr or stdout or f"exit code {completed.returncode}", 4)
    return None, detail


def _subprocess_platform_kwargs() -> Mapping[str, object]:
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def _resolve_path_default(tool: str, path_env: str | None) -> str | None:
    return shutil.which(tool, path=path_env)


def _recommended_candidate(
    candidates: Sequence[AgentRuntimeCandidate],
) -> AgentRuntimeCandidate | None:
    for candidate in candidates:
        if candidate.is_path_default and candidate.runnable:
            return candidate
    for candidate in candidates:
        if candidate.runnable:
            return candidate
    return candidates[0] if candidates else None


def _tool_status(
    candidates: Sequence[AgentRuntimeCandidate],
    recommended: AgentRuntimeCandidate | None,
) -> str:
    if not candidates:
        return "not_found"
    if recommended is not None and recommended.runnable:
        return "available"
    return "installed_but_broken"


def _has_conflict(candidates: Sequence[AgentRuntimeCandidate]) -> bool:
    if len(candidates) < 2:
        return False
    runnable_states = {candidate.runnable for candidate in candidates}
    versions = {
        candidate.version
        for candidate in candidates
        if candidate.runnable and candidate.version is not None
    }
    return len(runnable_states) > 1 or len(versions) > 1


def _tool_warning(
    tool: str,
    *,
    status: str,
    conflict: bool,
    recommended: AgentRuntimeCandidate | None,
    path_default: str | None,
) -> str | None:
    if status == "not_found":
        return f"{tool} executable was not found on PATH or common install paths."
    if status == "installed_but_broken":
        return f"{tool} executable exists but no candidate passed the executable probe."
    if recommended is not None and _looks_like_windowsapps_path(recommended.path):
        return "WindowsApps launcher may fail for background subprocess activation."
    if conflict:
        return "Multiple installations differ or include broken candidates; use an explicit executable path."
    if recommended is not None and path_default is None:
        return "Executable is available from a common install path but not from PATH."
    return None


def _infer_install_source(path: Path) -> str:
    normalized = str(path).replace("\\", "/").lower()
    if "/windowsapps/" in normalized:
        return "windowsapps"
    if "/npm/" in normalized or normalized.endswith("/npm"):
        return "npm"
    if "/pnpm/" in normalized:
        return "pnpm"
    if "/volta/" in normalized or "/.volta/" in normalized:
        return "volta"
    if "/scoop/" in normalized:
        return "scoop"
    if "/.nvm/" in normalized:
        return "nvm"
    if "fnm_multishells" in normalized:
        return "fnm"
    if "/mise/" in normalized:
        return "mise"
    if "/homebrew/" in normalized or "/cellar/" in normalized:
        return "homebrew"
    if "/.bun/" in normalized:
        return "bun"
    if "/python" in normalized or "/scripts/" in normalized or "/site-packages/" in normalized:
        return "pip"
    return "system"


def _extract_version(raw: str) -> str:
    match = _VERSION_RE.search(raw)
    if match is not None:
        return match.group(0)
    first_line = raw.splitlines()[0].strip()
    return first_line[:120] if first_line else "unknown"


def _env_type() -> str:
    if os.name == "nt":
        return "windows"
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    if system == "linux":
        return "linux"
    return system or "unknown"


def _real_path(path: str | None) -> str:
    if path is None:
        return ""
    try:
        return str(Path(path).resolve())
    except OSError:
        return str(Path(path))


def _looks_like_windowsapps_path(path: str) -> bool:
    normalized = path.replace("/", "\\").lower()
    return "\\windowsapps\\" in normalized


def _push_unique_path(paths: list[Path], path: Path) -> None:
    value = Path(path)
    if not str(value):
        return
    if value not in paths:
        paths.append(value)


def _push_env_path(paths: list[Path], name: str) -> None:
    value = os.environ.get(name)
    if value:
        _push_unique_path(paths, Path(value))


def _push_env_child_path(paths: list[Path], name: str, child: str) -> None:
    value = os.environ.get(name)
    if value:
        _push_unique_path(paths, Path(value) / child)


def _extend_existing_children(
    paths: list[Path],
    base: Path,
    suffix: str | None = None,
) -> None:
    if not base.exists() or not base.is_dir():
        return
    try:
        children = tuple(base.iterdir())
    except OSError:
        return
    for child in children:
        candidate = child / suffix if suffix is not None else child
        if candidate.exists():
            _push_unique_path(paths, candidate)


def _extend_python_scripts(paths: list[Path], base: Path) -> None:
    _extend_existing_children(paths, base, "Scripts")


def _last_lines(text: str, count: int) -> str:
    lines = text.strip().splitlines()
    return "\n".join(lines[-count:])
