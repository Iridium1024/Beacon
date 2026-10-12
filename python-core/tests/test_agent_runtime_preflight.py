from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.agent_runtime_preflight import (
    build_agent_runtime_preflight_report,
    check_agent_runtime_tool,
    probe_codex_app_server_surface,
)


class AgentRuntimePreflightTests(unittest.TestCase):
    def test_detects_runnable_path_default_and_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bin_dir = Path(directory)
            fake = _write_fake_tool(bin_dir, "claude", version="9.8.7")

            result = check_agent_runtime_tool(
                "claude",
                path_env=str(bin_dir),
                include_common_search_paths=False,
            )

            self.assertEqual(result.status, "available")
            self.assertTrue(result.activation_ready)
            self.assertEqual(result.recommended_executable, str(fake))
            self.assertEqual(result.candidates[0].version, "9.8.7")
            self.assertTrue(result.candidates[0].is_path_default)

    def test_reports_installed_but_broken_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bin_dir = Path(directory)
            _write_fake_tool(bin_dir, "codex", version="broken", exit_code=7)

            result = check_agent_runtime_tool(
                "codex",
                path_env=str(bin_dir),
                include_common_search_paths=False,
            )

            self.assertEqual(result.status, "installed_but_broken")
            self.assertFalse(result.activation_ready)
            self.assertIn("broken", result.candidates[0].error or "")

    def test_flags_multiple_installation_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first"
            second = Path(directory) / "second"
            first.mkdir()
            second.mkdir()
            first_tool = _write_fake_tool(first, "gemini", version="1.0.0")
            _write_fake_tool(second, "gemini", version="2.0.0")

            result = check_agent_runtime_tool(
                "gemini",
                path_env=os.pathsep.join((str(first), str(second))),
                include_common_search_paths=False,
            )

            self.assertEqual(result.status, "available")
            self.assertTrue(result.has_conflict)
            self.assertEqual(result.recommended_executable, str(first_tool))
            self.assertEqual(len(result.candidates), 2)

    def test_report_summary_is_read_only_and_deduplicated(self) -> None:
        report = build_agent_runtime_preflight_report(
            tools=("hermes", "hermes"),
            timeout_seconds=0.5,
        )

        self.assertTrue(report["readOnly"])
        self.assertTrue(report["noInstallAttempted"])
        self.assertTrue(report["noRepairAttempted"])
        self.assertEqual(report["summary"]["checked"], 1)
        self.assertEqual(report["tools"][0]["tool"], "hermes")

    def test_report_splits_activation_capability_checks_and_permission_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ticket_path = root / "wake-ticket.json"
            ticket_path.write_text("{}", encoding="utf-8")
            response_path = root / "responses" / "response.json"
            response_path.parent.mkdir()

            report = build_agent_runtime_preflight_report(
                tools=("codex",),
                timeout_seconds=5.0,
                ticket_path=str(ticket_path),
                response_path=str(response_path),
            )
            capabilities = report["activationCapabilities"]
            profile = capabilities["providerPermissionProfiles"]["codex"]

            self.assertEqual(
                capabilities["schema"],
                "agent_runtime_activation_capabilities.v1",
            )
            self.assertTrue(capabilities["ticketPathReadable"]["readable"])
            self.assertTrue(capabilities["responsePathWritable"]["writable"])
            self.assertTrue(capabilities["subprocessAllowed"]["allowed"])
            self.assertTrue(capabilities["platformCliRunnable"]["runnable"])
            self.assertIn("codex", capabilities["providerExecutableFound"])
            self.assertEqual(
                capabilities["providerProtocolChecks"]["codexAppServer"]["schema"],
                "codex_app_server_preflight.v1",
            )
            claude_sdk = capabilities["providerProtocolChecks"]["claudeAgentSdk"]
            self.assertEqual(claude_sdk["schema"], "claude_agent_sdk_preflight.v1")
            self.assertEqual(claude_sdk["status"], "not_requested")
            self.assertFalse(claude_sdk["sessionStarted"])
            self.assertFalse(profile["selected"])
            self.assertEqual(profile["selectionSource"], "default_no_permission_profile")
            self.assertFalse(profile["permissionPostureChangingArgsInjected"])
            self.assertIn("--sandbox", profile["retainedDefaultDisabledArgs"])
            self.assertIn(
                "--dangerously-bypass-approvals-and-sandbox",
                profile["dangerousBypassArgs"],
            )

    def test_codex_app_server_surface_probe_reports_required_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            command = _write_fake_app_server_probe(
                Path(directory),
                help_lines=(
                    "Usage: codex app-server [OPTIONS] [COMMAND]",
                    "generate-json-schema  Generate JSON Schema",
                    "--listen <URL>  stdio:// (default)",
                ),
            )

            result = probe_codex_app_server_surface(
                str(command),
                version="0.146.0",
            )

            self.assertEqual(result["status"], "available")
            self.assertTrue(result["compatible"])
            self.assertTrue(result["stdioTransportAvailable"])
            self.assertTrue(result["jsonSchemaGenerationAvailable"])
            self.assertEqual(result["version"], "0.146.0")

    def test_codex_app_server_surface_probe_reports_missing_surface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            command = _write_fake_app_server_probe(
                Path(directory),
                help_lines=("Usage: codex app-server [OPTIONS]",),
            )

            result = probe_codex_app_server_surface(str(command))

            self.assertEqual(result["status"], "missing_required_surface")
            self.assertFalse(result["compatible"])
            self.assertFalse(result["stdioTransportAvailable"])
            self.assertFalse(result["jsonSchemaGenerationAvailable"])
            self.assertIn("warning", result)

    def test_codex_app_server_surface_probe_failure_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            command = _write_fake_app_server_probe(
                Path(directory),
                help_lines=("app-server unavailable",),
                exit_code=7,
            )

            result = probe_codex_app_server_surface(str(command))

            self.assertEqual(result["status"], "probe_failed")
            self.assertFalse(result["compatible"])
            self.assertEqual(result["exitCode"], 7)
            self.assertIn("app-server unavailable", result["error"])

    def test_detects_hermes_windows_localappdata_install_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            localappdata = Path(directory) / "LocalAppData"
            scripts = localappdata / "hermes" / "hermes-agent" / "venv" / "Scripts"
            scripts.mkdir(parents=True)
            fake = _write_fake_tool(scripts, "hermes", version="Hermes Agent v9.8.7")

            with mock.patch.dict(
                os.environ,
                {"LOCALAPPDATA": str(localappdata)},
                clear=False,
            ):
                result = check_agent_runtime_tool(
                    "hermes",
                    path_env="",
                    include_common_search_paths=True,
                )

            if os.name == "nt":
                self.assertEqual(result.status, "available")
                self.assertEqual(result.recommended_executable, str(fake))
            else:
                self.assertEqual(result.status, "not_found")

    def test_hermes_uses_help_probe_without_reporting_help_as_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bin_dir = Path(directory)
            fake = _write_fake_tool(bin_dir, "hermes", version="Hermes Agent v9.8.7")

            result = check_agent_runtime_tool(
                "hermes",
                path_env=str(bin_dir),
                include_common_search_paths=False,
            )

            self.assertEqual(result.status, "available")
            self.assertTrue(result.activation_ready)
            self.assertEqual(result.recommended_executable, str(fake))
            self.assertEqual(result.candidates[0].version, "help_probe_passed")

    def test_local_runtime_preflight_cli_outputs_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bin_dir = Path(directory) / "bin"
            bin_dir.mkdir()
            _write_fake_tool(bin_dir, "claude", version="3.2.1")
            completed = _run_cli(
                directory,
                "agent-runtime-preflight",
                "--tool",
                "claude",
                extra_env={"PATH": str(bin_dir)},
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["schema"], "agent_runtime_preflight_report.v1")
            self.assertTrue(payload["readOnly"])
            self.assertEqual(payload["tools"][0]["tool"], "claude")
            self.assertEqual(payload["tools"][0]["status"], "available")
            self.assertIn("activationCapabilities", payload)
            self.assertFalse(
                payload["activationCapabilities"]["providerPermissionProfiles"][
                    "claude"
                ]["selected"]
            )
            claude_sdk = payload["activationCapabilities"][
                "providerProtocolChecks"
            ]["claudeAgentSdk"]
            self.assertEqual(claude_sdk["schema"], "claude_agent_sdk_preflight.v1")
            self.assertTrue(claude_sdk["probeAttempted"])
            self.assertFalse(claude_sdk["sessionStarted"])


def _write_fake_tool(
    directory: Path,
    name: str,
    *,
    version: str,
    exit_code: int = 0,
) -> Path:
    if os.name == "nt":
        path = directory / f"{name}.cmd"
        if exit_code == 0:
            path.write_text(f"@echo off\r\necho {version}\r\n", encoding="utf-8")
        else:
            path.write_text(
                f"@echo off\r\necho {version} 1>&2\r\nexit /b {exit_code}\r\n",
                encoding="utf-8",
            )
        return path
    path = directory / name
    if exit_code == 0:
        path.write_text(f"#!/bin/sh\necho {version}\n", encoding="utf-8")
    else:
        path.write_text(
            f"#!/bin/sh\necho {version} >&2\nexit {exit_code}\n",
            encoding="utf-8",
        )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _write_fake_app_server_probe(
    directory: Path,
    *,
    help_lines: tuple[str, ...],
    exit_code: int = 0,
) -> Path:
    if os.name == "nt":
        path = directory / "codex-app-server-probe.cmd"
        output = ["@echo off"]
        for line in help_lines:
            escaped = line.replace("^", "^^")
            for character in ("&", "|", "<", ">", "(", ")"):
                escaped = escaped.replace(character, f"^{character}")
            output.append(f"echo {escaped}")
        output.append(f"exit /b {exit_code}")
        path.write_text("\r\n".join(output) + "\r\n", encoding="utf-8")
        return path
    path = directory / "codex-app-server-probe"
    output = ["#!/bin/sh"]
    output.extend(f"echo '{line}'" for line in help_lines)
    output.append(f"exit {exit_code}")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _run_cli(
    directory: str,
    *args: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_SRC)
    if extra_env is not None:
        environment.update(extra_env)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_os.local_runtime",
            "--database",
            str(Path(directory) / "platform.sqlite3"),
            "--workspace-root",
            str(Path(directory) / "workspace"),
            "--plugins-directory",
            str(Path(directory) / "plugins"),
            *args,
        ],
        cwd=str(PROJECT_SRC.parents[1]),
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
