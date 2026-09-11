"""Executable, scoped CLI instructions shared by wake tickets and DSH messages.

Only the Beacon interpreter/source path is supplied as execution context. Never
snapshot the caller's environment or interpolate agent-authored text into shell
code. Argv is canonical; shell examples quote every argument as literal data.
"""
from __future__ import annotations

from pathlib import Path
import shlex
import subprocess
import sys
from typing import Mapping


def build_beacon_cli_invocation(
    *, database_path: str, workspace_root: str, plugins_directory: str,
    profile_path: str | None,
) -> tuple[list[str], dict[str, str]]:
    source_root = str(Path(__file__).resolve().parents[3])
    interpreter = str(Path(sys.executable).resolve())
    if not Path(interpreter).is_file() or not Path(source_root, "agent_os", "local_runtime.py").is_file():
        raise ValueError("beacon_cli_unavailable: Beacon interpreter or CLI module is unavailable.")
    common = [interpreter, "-m", "agent_os.local_runtime"]
    if profile_path is not None:
        common.extend(["--profile", profile_path])
    else:
        common.extend(["--database", database_path, "--workspace-root", workspace_root,
                       "--plugins-directory", plugins_directory])
    return common, {"PYTHONPATH": source_root}


def build_agent_cli_actions(
    *, database_path: str, workspace_root: str, plugins_directory: str,
    profile_path: str | None, workspace_id: str, exchange_request_id: str,
    target_agent_id: str,
) -> dict[str, object]:
    common, environment = build_beacon_cli_invocation(
        database_path=database_path, workspace_root=workspace_root,
        plugins_directory=plugins_directory, profile_path=profile_path,
    )
    scope = ["--workspace-id", workspace_id]
    return {
        "schema": "agent_wake_action.v1",
        "runtimeConfigSource": "profile" if profile_path is not None else "explicit_args",
        **({"profilePath": profile_path} if profile_path is not None else {}),
        "runtimeEnvironment": environment,
        "inspectArgv": [*common, "agent-exchange-status", *scope,
                        "--exchange-request-id", exchange_request_id, "--format", "compact"],
        "respondArgvTemplate": [*common, "agent-reply", *scope, "--request", exchange_request_id,
                                "--agent", target_agent_id, "--message", "<short target-agent response>"],
        "selfArgv": [*common, "agent-onboarding-status", *scope, "--agent-id", target_agent_id],
        "membersArgv": [*common, "agent-onboarding-status", *scope],
        "inboxArgv": [*common, "agent-exchange-request-list", *scope,
                      "--target-agent-id", target_agent_id, "--status", "active"],
        "sendArgvTemplate": [*common, "agent-dispatch-send", *scope,
                             "--as", "<confirmed-source-alias>", "--to", "<target-alias>",
                             "--message", "<new request>"],
    }


def cli_shell_examples(actions: Mapping[str, object]) -> Mapping[str, object]:
    """Bash (including Git Bash) and PowerShell: no cmd.exe nesting or eval."""
    env = actions["runtimeEnvironment"]
    source = str(env["PYTHONPATH"])
    def ps(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"
    def powershell(argv: list[str]) -> str:
        # Windows PowerShell 5.1's native binder drops embedded double quotes
        # even inside single-quoted arguments. Bypass that binder entirely;
        # .NET starts the executable directly with a CRT-quoted argument string.
        return (
            "$beaconStartInfo = [System.Diagnostics.ProcessStartInfo]::new(); "
            "$beaconStartInfo.UseShellExecute = $false; "
            "$beaconStartInfo.FileName = " + ps(argv[0]) + "; "
            "$beaconStartInfo.Arguments = " + ps(subprocess.list2cmdline(argv[1:])) + "; "
            "$beaconStartInfo.EnvironmentVariables['PYTHONPATH'] = " + ps(source) + "; "
            "$beaconProcess = [System.Diagnostics.Process]::Start($beaconStartInfo); "
            "$beaconProcess.WaitForExit(); $beaconExitCode = $beaconProcess.ExitCode; "
            "$beaconProcess.Dispose(); if ($beaconExitCode -ne 0) { "
            "throw ('Beacon CLI failed with exit code ' + $beaconExitCode) }"
        )
    return {
        key: {
            "bash": "PYTHONPATH=" + shlex.quote(source) + " " + shlex.join(argv),
            "powershell": powershell(argv),
        }
        for key, argv in actions.items()
        if key.endswith(("Argv", "ArgvTemplate")) and isinstance(argv, list)
    }
