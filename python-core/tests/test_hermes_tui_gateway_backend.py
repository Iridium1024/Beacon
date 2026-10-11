from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import agent_os.application.services.hermes_tui_gateway_backend as gateway_backend

from agent_os.application.services.hermes_tui_gateway_backend import (
    HERMES_TUI_GATEWAY_SUPPORTED_VERSION,
    HermesTuiGatewayActivationConfig,
    HermesTuiGatewayRuntime,
    load_hermes_tui_gateway_runtime,
    run_hermes_tui_gateway_activation,
)


FIXTURE = Path(__file__).parent / "fixtures" / "fake_hermes_tui_gateway.py"


class HermesTuiGatewayBackendTests(unittest.TestCase):
    def test_success_maps_persistent_and_runtime_ids_without_initialize_or_rewind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result, wire = self._run("success", Path(directory))

        self.assertTrue(result.succeeded)
        self.assertEqual(result.persistent_session_id, "persistent-session")
        self.assertEqual(result.runtime_session_id, "runtime-1234")
        self.assertNotEqual(result.runtime_session_id, result.persistent_session_id)
        self.assertTrue(result.session_continuity_verified)
        self.assertEqual(result.final_response, "verified final")
        self.assertEqual(
            result.final_response_source,
            "gateway_event.message.complete",
        )
        self.assertEqual(
            [item["method"] for item in wire[:3]],
            ["session.list", "session.resume", "prompt.submit"],
        )
        self.assertNotIn("initialize", result.wire_methods)
        submit = next(item for item in wire if item["method"] == "prompt.submit")
        self.assertEqual(set(submit["params"]), {"session_id", "text"})
        self.assertEqual(submit["params"]["session_id"], "runtime-1234")
        self.assertFalse(
            {
                "truncate_before_user_ordinal",
                "truncate_before_row_id",
                "confirm_truncate",
                "confirm_empty_truncate",
                "survivor_user_row_ids",
            }.intersection(submit["params"])
        )
        self.assertEqual(result.event_counts["message.delta"], 1)
        self.assertEqual(result.event_counts["message.complete"], 1)

    def test_ready_contract_fails_closed(self) -> None:
        expected = {
            "missing_ready": "gateway_ready_timeout",
            "duplicate_ready": "gateway_ready_duplicate",
            "malformed_ready": "gateway_json_malformed",
        }
        for scenario, category in expected.items():
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                result, _ = self._run(scenario, Path(directory))
                self.assertFalse(result.succeeded)
                self.assertEqual(result.failure_category, category)
                self.assertFalse(result.prompt_submission_attempted)

    def test_session_list_requires_one_exact_id_and_source(self) -> None:
        expected = {
            "list_missing": "session_list_missing",
            "list_duplicate": "session_list_duplicate",
            "list_source_mismatch": "session_source_mismatch",
        }
        for scenario, category in expected.items():
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                result, _ = self._run(scenario, Path(directory))
                self.assertEqual(result.failure_category, category)
                self.assertFalse(result.prompt_submission_attempted)

    def test_resume_persistent_id_and_cwd_must_match(self) -> None:
        expected = {
            "resume_mismatch": "session_resume_persistent_mismatch",
            "cwd_mismatch": "session_cwd_mismatch",
        }
        for scenario, category in expected.items():
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                result, _ = self._run(scenario, Path(directory))
                self.assertEqual(result.failure_category, category)
                self.assertFalse(result.prompt_submission_attempted)

    def test_terminal_and_cross_session_failures_are_deterministic(self) -> None:
        expected = {
            "cross_session": "cross_session_event",
            "stale_before_resume": "session_event_before_resume",
            "terminal_out_of_order": "terminal_event_out_of_order",
            "error_event": "provider_error_event",
            "duplicate_final": "duplicate_terminal_event",
            "malformed_after_submit": "gateway_json_malformed",
            "duplicate_response": "duplicate_response",
            "unknown_response": "unknown_response_id",
        }
        for scenario, category in expected.items():
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                result, _ = self._run(scenario, Path(directory))
                self.assertEqual(result.failure_category, category)
                if scenario not in {
                    "duplicate_response",
                    "unknown_response",
                    "stale_before_resume",
                }:
                    self.assertTrue(result.prompt_submission_attempted)
                self.assertNotEqual(result.final_response, "delta is not final")

    def test_interactions_use_explicit_stable_0190_responses_and_never_supply_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result, wire = self._run("interactions", Path(directory))

        self.assertTrue(result.succeeded)
        self.assertEqual(result.interaction_requests, 4)
        self.assertEqual(result.interaction_responses, 4)
        self.assertEqual(result.interaction_denied, 4)
        by_method = {item["method"]: item["params"] for item in wire}
        self.assertEqual(
            by_method["approval.respond"],
            {"session_id": "runtime-1234", "choice": "deny", "all": False},
        )
        self.assertEqual(by_method["clarify.respond"]["answer"], "")
        self.assertEqual(by_method["sudo.respond"]["password"], "")
        self.assertEqual(by_method["secret.respond"]["value"], "")
        self.assertTrue(result.requires_user_review)

    def test_unknown_or_duplicate_interaction_ids_fail_closed(self) -> None:
        expected = {
            "interaction_duplicate": "interaction_request_duplicate",
            "interaction_unknown_expiry": "interaction_expiry_unknown",
        }
        for scenario, category in expected.items():
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                result, _ = self._run(scenario, Path(directory))
                self.assertEqual(result.failure_category, category)
                self.assertTrue(result.interrupt_attempted)

    def test_transport_bounds_eof_and_nonzero_exit_fail_closed(self) -> None:
        cases = (
            ("oversized_ready", "gateway_frame_oversized", 256, 8192),
            ("stderr_invalid", "gateway_stderr_utf8_invalid", 1024, 8192),
            ("stderr_oversized", "gateway_stderr_oversized", 1024, 1024),
            ("eof_after_ready", "unexpected_eof", 1024, 8192),
            ("nonzero_after_ready", "unexpected_eof", 1024, 8192),
        )
        for scenario, category, max_line, max_total in cases:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                result, _ = self._run(
                    scenario,
                    Path(directory),
                    max_line_bytes=max_line,
                    max_total_bytes=max_total,
                )
                self.assertEqual(result.failure_category, category)
                self.assertFalse(result.prompt_submitted)

    def test_timeout_sends_at_most_one_interrupt_and_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result, wire = self._run("timeout", Path(directory), timeout_seconds=0.35)

        self.assertEqual(result.failure_category, "activation_timeout")
        self.assertTrue(result.prompt_submitted)
        self.assertTrue(result.interrupt_attempted)
        self.assertEqual(result.interrupt_status, "interrupted")
        self.assertEqual(
            [item["method"] for item in wire].count("session.interrupt"),
            1,
        )
        self.assertIn(result.cleanup_status, {"exited", "terminated", "killed"})
        self.assertTrue(result.ambiguous_delivery)

    def test_interrupt_failure_and_delivery_ambiguity_are_reported_separately(self) -> None:
        for scenario in ("interrupt_rpc_error", "interrupt_eof"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                result, wire = self._run(
                    scenario,
                    Path(directory),
                    timeout_seconds=0.35,
                )

            self.assertEqual(result.failure_category, "activation_timeout")
            self.assertTrue(result.prompt_submitted)
            self.assertTrue(result.ambiguous_delivery)
            self.assertTrue(result.interrupt_attempted)
            self.assertTrue(result.interrupt_status.startswith("failed:"))
            self.assertEqual(
                [item["method"] for item in wire].count("session.interrupt"),
                1,
            )

    def test_runtime_preflight_is_read_only_and_rejects_unavailable_environment(self) -> None:
        runtime = load_hermes_tui_gateway_runtime(sys.executable, timeout_seconds=5)

        self.assertFalse(runtime.compatible)
        self.assertIn(
            runtime.status,
            {"unsupported_version", "gateway_module_missing", "probe_failed"},
        )
        metadata = runtime.to_metadata()
        self.assertTrue(metadata["readOnly"])
        self.assertFalse(metadata["sessionStarted"])
        self.assertEqual(metadata["supportedVersion"], "0.19.0")
        self.assertEqual(metadata["launchModule"], "tui_gateway.entry")
        self.assertFalse(metadata["consoleScriptExpected"])
        self.assertEqual(
            metadata["mainAdvisoryCapabilities"]["approvalCorrelation"],
            "request_id",
        )
        self.assertEqual(
            metadata["mainAdvisoryCapabilities"]["clarifyCorrelation"],
            "request_id_and_optional_question_id",
        )
        self.assertFalse(metadata["mainAdvisoryCapabilities"]["supported"])

    def test_runtime_preflight_accepts_only_exact_stable_capability_fixture(self) -> None:
        payload = {
            "version": "0.19.0",
            "package_location": "X:/fixture/site-packages",
            "entry_location": "X:/fixture/tui_gateway/entry.py",
            "server_location": "X:/fixture/tui_gateway/server.py",
            "methods": {
                method: True for method in gateway_backend._REQUIRED_METHODS_0190
            },
            "events": {
                event: True for event in gateway_backend._REQUIRED_EVENTS_0190
            },
            "no_initialize_handler": True,
        }

        for version, compatible, status in (
            ("0.19.0", True, "available"),
            ("0.18.0", False, "unsupported_version"),
            ("0.20.5", False, "unsupported_version"),
            (None, False, "unsupported_version"),
        ):
            with self.subTest(version=version):
                candidate = dict(payload)
                if version is None:
                    candidate.pop("version", None)
                else:
                    candidate["version"] = version
                completed = subprocess.CompletedProcess(
                    args=("gateway-python",),
                    returncode=0,
                    stdout=json.dumps(candidate),
                    stderr="",
                )
                with patch.object(subprocess, "run", return_value=completed) as probe:
                    runtime = load_hermes_tui_gateway_runtime("gateway-python")

                self.assertEqual(runtime.compatible, compatible)
                self.assertEqual(runtime.status, status)
                self.assertEqual(
                    runtime.launch_argv,
                    ("gateway-python", "-u", "-m", "tui_gateway.entry"),
                )
                self.assertEqual(probe.call_args.args[0][:2], ("gateway-python", "-I"))
                self.assertFalse(probe.call_args.kwargs["shell"])

    def test_subprocess_launch_uses_an_isolated_process_group(self) -> None:
        sentinel = object()
        with patch.object(subprocess, "Popen", return_value=sentinel) as popen:
            result = gateway_backend._start_gateway_process(
                ("gateway-python", "-u", "-m", "tui_gateway.entry"),
                os.getcwd(),
                os.environ,
            )

        self.assertIs(result, sentinel)
        kwargs = popen.call_args.kwargs
        self.assertFalse(kwargs["shell"])
        if os.name == "nt":
            self.assertTrue(
                kwargs["creationflags"]
                & getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
            self.assertFalse(kwargs["start_new_session"])
        else:
            self.assertTrue(kwargs["start_new_session"])

    def test_windows_force_cleanup_targets_only_the_owned_process_tree(self) -> None:
        class FakePopen:
            pid = 4242

            def poll(self):
                return None

            def kill(self):
                raise AssertionError("taskkill success must not fall back to parent-only kill")

        process = FakePopen()
        completed = subprocess.CompletedProcess(
            args=("taskkill.exe",),
            returncode=0,
        )
        with patch.object(gateway_backend.os, "name", "nt"), patch.object(
            gateway_backend.subprocess,
            "Popen",
            FakePopen,
        ), patch.object(
            gateway_backend.subprocess,
            "run",
            return_value=completed,
        ) as taskkill:
            gateway_backend._terminate_gateway_process(process, force=True)

        self.assertEqual(
            taskkill.call_args.args[0],
            ("taskkill.exe", "/PID", "4242", "/T", "/F"),
        )
        self.assertFalse(taskkill.call_args.kwargs["check"])

    def _run(
        self,
        scenario: str,
        root: Path,
        *,
        timeout_seconds: float = 0.8,
        max_line_bytes: int = 1024,
        max_total_bytes: int = 8192,
    ):
        log_path = root / "wire.jsonl"
        runtime = HermesTuiGatewayRuntime(
            status="available",
            compatible=True,
            python_executable=sys.executable,
            package_version=HERMES_TUI_GATEWAY_SUPPORTED_VERSION,
            package_location=str(root),
            gateway_entry_location=str(FIXTURE),
            server_location=str(FIXTURE),
            launch_argv=(sys.executable, "-u", str(FIXTURE)),
            methods={},
            events={},
            capabilities={"version": "0.19.0"},
        )
        config = HermesTuiGatewayActivationConfig(
            persistent_session_id="persistent-session",
            registered_source="cli",
            cwd=str(root.resolve()),
            runtime_home=None,
            source_tag="agent-os",
            ready_timeout_seconds=0.25,
            request_timeout_seconds=0.25,
            cleanup_timeout_seconds=0.25,
            max_line_bytes=max_line_bytes,
            max_total_bytes=max_total_bytes,
            max_diagnostic_chars=512,
        )
        environment = {
            "FAKE_HERMES_SCENARIO": scenario,
            "FAKE_HERMES_PERSISTENT": "persistent-session",
            "FAKE_HERMES_RUNTIME": "runtime-1234",
            "FAKE_HERMES_SOURCE": "cli",
            "FAKE_HERMES_CWD": str(root.resolve()),
            "FAKE_HERMES_LOG": str(log_path),
        }
        with patch.dict(os.environ, environment, clear=False):
            result = run_hermes_tui_gateway_activation(
                config,
                runtime=runtime,
                prompt="read the wake ticket",
                timeout_seconds=timeout_seconds,
                max_response_chars=2000,
            )
        wire = []
        if log_path.exists():
            wire = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        return result, wire


if __name__ == "__main__":
    unittest.main()
