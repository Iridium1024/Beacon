from __future__ import annotations

import json
import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.codex_app_server import (
    CodexAppServerRunStatus,
    build_codex_app_server_resume_params,
    read_codex_app_server_thread,
    render_codex_app_server_argv,
    run_codex_app_server_activation,
)


class CodexAppServerContractTests(unittest.TestCase):
    def test_argv_and_resume_params_stay_on_local_stdio_stable_surface(self) -> None:
        argv = render_codex_app_server_argv(codex_executable="codex")
        params = build_codex_app_server_resume_params(
            thread_id="thread-1",
            cwd="X:/fixture/project",
            add_dirs=("X:/fixture/platform", "X:/fixture/platform"),
            sandbox_mode="workspace-write",
            approval_policy="never",
        )

        self.assertEqual(argv, ("codex", "app-server", "--stdio"))
        self.assertNotIn("--listen", argv)
        self.assertEqual(params["threadId"], "thread-1")
        self.assertEqual(params["sandbox"], "workspace-write")
        self.assertEqual(params["approvalPolicy"], "never")
        self.assertEqual(
            params["config"],
            {
                "sandbox_workspace_write": {
                    "writable_roots": ["X:/fixture/platform"]
                }
            },
        )

    def test_add_dirs_do_not_force_workspace_write(self) -> None:
        params = build_codex_app_server_resume_params(
            thread_id="thread-1",
            cwd="X:/fixture/project",
            add_dirs=("X:/fixture/platform",),
        )

        self.assertNotIn("sandbox", params)
        self.assertNotIn("approvalPolicy", params)
        self.assertIn("config", params)


class CodexAppServerRuntimeTests(unittest.TestCase):
    def test_point_read_does_not_resume_or_start_a_turn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            thread_id = str(uuid4())
            capture = root / "capture.json"
            command = _fake_app_server(
                root,
                scenario="completed",
                thread_id=thread_id,
                capture_path=capture,
            )

            result = read_codex_app_server_thread(
                render_codex_app_server_argv(codex_executable=str(command)),
                cwd=str(root),
                thread_id=thread_id,
                timeout_seconds=5,
            )

            self.assertEqual(result.status, "ok")
            self.assertTrue(result.thread_found)
            self.assertEqual(result.native_thread_id, thread_id)
            self.assertEqual(result.thread_status, "notLoaded")
            received = json.loads(capture.read_text(encoding="utf-8"))
            methods = [entry.get("method") for entry in received]
            self.assertEqual(methods, ["initialize", "initialized", "thread/read"])

    def test_turn_completion_summary_recovers_final_message_without_item_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            thread_id = str(uuid4())
            command = _fake_app_server(
                root,
                scenario="summary_only",
                thread_id=thread_id,
                capture_path=root / "capture.json",
            )

            result = run_codex_app_server_activation(
                render_codex_app_server_argv(codex_executable=str(command)),
                cwd=str(root),
                thread_id=thread_id,
                input_text="Recover the completion summary.",
                timeout_seconds=5,
            )

            self.assertEqual(result.status, CodexAppServerRunStatus.COMPLETED)
            self.assertEqual(result.final_response, "final answer from completion summary")
            self.assertEqual(result.response_phase, "final_answer")
            self.assertIn("turn/completed", result.notification_methods)
            self.assertNotIn("item/completed", result.notification_methods)

    def test_nested_error_and_deprecation_notifications_are_diagnostics_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            thread_id = str(uuid4())
            command = _fake_app_server(
                root,
                scenario="diagnostics",
                thread_id=thread_id,
                capture_path=root / "capture.json",
            )

            result = run_codex_app_server_activation(
                render_codex_app_server_argv(codex_executable=str(command)),
                cwd=str(root),
                thread_id=thread_id,
                input_text="Preserve diagnostics without promoting them.",
                timeout_seconds=5,
            )

            self.assertEqual(result.status, CodexAppServerRunStatus.COMPLETED)
            self.assertEqual(result.final_response, "final answer from app-server")
            self.assertIn("error", result.notification_methods)
            self.assertIn("deprecationNotice", result.notification_methods)
            diagnostics = "\n".join(result.warning_messages)
            self.assertIn("temporary upstream failure", diagnostics)
            self.assertIn("willRetry=true", diagnostics)
            self.assertIn('codexErrorInfo={"kind":"rateLimit"}', diagnostics)
            self.assertIn('additionalDetails={"retryAfterMs":250}', diagnostics)
            self.assertIn("Legacy field is deprecated", diagnostics)
            self.assertNotEqual(result.final_response, diagnostics)

    def test_turn_steer_is_delivered_on_the_owning_stdio_connection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            thread_id = str(uuid4())
            capture = root / "capture.json"
            command = _fake_app_server(
                root,
                scenario="steer",
                thread_id=thread_id,
                capture_path=capture,
            )
            pending = True
            outcomes: list[dict[str, object]] = []

            def load_pending(native_thread_id: str, native_turn_id: str):
                self.assertEqual(native_thread_id, thread_id)
                self.assertEqual(native_turn_id, "turn-1")
                return (
                    ({
                        "supplementId": "supplement-1",
                        "expectedTurnId": "turn-1",
                        "message": "Use this additional constraint.",
                    },)
                    if pending
                    else ()
                )

            def record_outcome(outcome):
                nonlocal pending
                outcomes.append(dict(outcome))
                if outcome["status"] == "delivery_unknown":
                    pending = False

            result = run_codex_app_server_activation(
                render_codex_app_server_argv(codex_executable=str(command)),
                cwd=str(root),
                thread_id=thread_id,
                input_text="Start the owning turn.",
                timeout_seconds=5,
                load_pending_supplements=load_pending,
                on_supplement_outcome=record_outcome,
            )

            self.assertEqual(result.status, CodexAppServerRunStatus.COMPLETED)
            self.assertEqual(
                [entry["status"] for entry in outcomes],
                ["delivery_unknown", "accepted"],
            )
            received = json.loads(capture.read_text(encoding="utf-8"))
            steer = next(
                entry for entry in received if entry.get("method") == "turn/steer"
            )
            self.assertEqual(steer["params"]["threadId"], thread_id)
            self.assertEqual(steer["params"]["expectedTurnId"], "turn-1")
            self.assertEqual(
                steer["params"]["input"],
                [{"type": "text", "text": "Use this additional constraint."}],
            )

    def test_stale_turn_supplement_is_settled_without_writing_turn_steer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            thread_id = str(uuid4())
            capture = root / "capture.json"
            command = _fake_app_server(
                root,
                scenario="completed",
                thread_id=thread_id,
                capture_path=capture,
            )
            pending = True
            outcomes: list[dict[str, object]] = []

            def record(outcome):
                nonlocal pending
                pending = False
                outcomes.append(dict(outcome))

            result = run_codex_app_server_activation(
                render_codex_app_server_argv(codex_executable=str(command)),
                cwd=str(root),
                thread_id=thread_id,
                input_text="Start the turn.",
                timeout_seconds=5,
                load_pending_supplements=lambda *_: (
                    ({
                        "supplementId": "stale-1",
                        "expectedTurnId": "old-turn",
                        "message": "stale",
                    },)
                    if pending
                    else ()
                ),
                on_supplement_outcome=record,
            )

            self.assertEqual(result.status, CodexAppServerRunStatus.COMPLETED)
            self.assertEqual([item["status"] for item in outcomes], ["stale_turn"])
            received = json.loads(capture.read_text(encoding="utf-8"))
            self.assertNotIn("turn/steer", [item.get("method") for item in received])

    def test_unsupported_turn_steer_is_rejected_after_ambiguous_guard_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            thread_id = str(uuid4())
            command = _fake_app_server(
                root,
                scenario="steer_unsupported",
                thread_id=thread_id,
                capture_path=root / "capture.json",
            )
            pending = True
            outcomes: list[dict[str, object]] = []

            def record(outcome):
                nonlocal pending
                outcomes.append(dict(outcome))
                if outcome["status"] == "delivery_unknown":
                    pending = False

            result = run_codex_app_server_activation(
                render_codex_app_server_argv(codex_executable=str(command)),
                cwd=str(root),
                thread_id=thread_id,
                input_text="Start the turn.",
                timeout_seconds=5,
                load_pending_supplements=lambda *_: (
                    ({
                        "supplementId": "unsupported-1",
                        "expectedTurnId": "turn-1",
                        "message": "guide",
                    },)
                    if pending
                    else ()
                ),
                on_supplement_outcome=record,
            )

            self.assertEqual(result.status, CodexAppServerRunStatus.COMPLETED)
            self.assertEqual(
                [item["status"] for item in outcomes],
                ["delivery_unknown", "rejected"],
            )
            self.assertEqual(
                outcomes[-1]["failureCategory"],
                "app_server_steer_method_not_supported",
            )

    def test_stdio_disconnect_leaves_supplement_delivery_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            thread_id = str(uuid4())
            command = _fake_app_server(
                root,
                scenario="steer_disconnect",
                thread_id=thread_id,
                capture_path=root / "capture.json",
            )
            pending = True
            outcomes: list[dict[str, object]] = []

            def record(outcome):
                nonlocal pending
                outcomes.append(dict(outcome))
                if outcome["status"] == "delivery_unknown":
                    pending = False

            result = run_codex_app_server_activation(
                render_codex_app_server_argv(codex_executable=str(command)),
                cwd=str(root),
                thread_id=thread_id,
                input_text="Start the turn.",
                timeout_seconds=5,
                load_pending_supplements=lambda *_: (
                    ({
                        "supplementId": "disconnect-1",
                        "expectedTurnId": "turn-1",
                        "message": "guide",
                    },)
                    if pending
                    else ()
                ),
                on_supplement_outcome=record,
            )

            self.assertEqual(result.status, CodexAppServerRunStatus.FAILED)
            self.assertEqual([item["status"] for item in outcomes], ["delivery_unknown"])

    def test_complete_turn_verifies_thread_and_captures_final_agent_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            thread_id = str(uuid4())
            capture = root / "capture.json"
            command = _fake_app_server(
                root,
                scenario="completed",
                thread_id=thread_id,
                capture_path=capture,
            )

            result = run_codex_app_server_activation(
                render_codex_app_server_argv(codex_executable=str(command)),
                cwd=str(root),
                thread_id=thread_id,
                input_text="Complete this Beacon request.",
                add_dirs=(str(root / "platform"),),
                timeout_seconds=5,
            )

            self.assertEqual(result.status, CodexAppServerRunStatus.COMPLETED)
            self.assertTrue(result.process_started)
            self.assertTrue(result.initialized)
            self.assertTrue(result.thread_verified)
            self.assertEqual(result.native_thread_id, thread_id)
            self.assertEqual(result.native_session_id, thread_id)
            self.assertEqual(result.native_turn_id, "turn-1")
            self.assertEqual(
                result.client_request_methods,
                ("initialize", "thread/read", "thread/resume", "turn/start"),
            )
            self.assertEqual(result.turn_status, "completed")
            self.assertEqual(result.final_response, "final answer from app-server")
            self.assertEqual(result.response_phase, "final_answer")
            self.assertEqual(result.process_exit_code, 0)
            self.assertTrue(result.stdin_closed)
            self.assertFalse(result.process_timed_out)
            received = json.loads(capture.read_text(encoding="utf-8"))
            methods = [message.get("method") for message in received]
            self.assertEqual(
                methods[:5],
                [
                    "initialize",
                    "initialized",
                    "thread/read",
                    "thread/resume",
                    "turn/start",
                ],
            )
            read = next(message for message in received if message.get("method") == "thread/read")
            self.assertFalse(read["params"]["includeTurns"])
            initialize = received[0]
            self.assertNotIn("capabilities", initialize["params"])

    def test_active_thread_returns_retryable_busy_without_starting_turn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            thread_id = str(uuid4())
            capture = root / "capture.json"
            command = _fake_app_server(
                root,
                scenario="busy",
                thread_id=thread_id,
                capture_path=capture,
            )

            result = run_codex_app_server_activation(
                render_codex_app_server_argv(codex_executable=str(command)),
                cwd=str(root),
                thread_id=thread_id,
                input_text="Do not duplicate this active turn.",
                timeout_seconds=5,
            )

            self.assertEqual(result.status, CodexAppServerRunStatus.BUSY)
            self.assertEqual(result.failure_category, "app_server_thread_busy")
            self.assertTrue(result.retryable)
            received = json.loads(capture.read_text(encoding="utf-8"))
            self.assertNotIn("turn/start", [entry.get("method") for entry in received])

    def test_command_approval_uses_safe_default_decline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            thread_id = str(uuid4())
            capture = root / "capture.json"
            command = _fake_app_server(
                root,
                scenario="approval",
                thread_id=thread_id,
                capture_path=capture,
            )

            result = run_codex_app_server_activation(
                render_codex_app_server_argv(codex_executable=str(command)),
                cwd=str(root),
                thread_id=thread_id,
                input_text="Request an approval.",
                timeout_seconds=5,
            )

            self.assertEqual(result.status, CodexAppServerRunStatus.COMPLETED)
            self.assertEqual(result.approval_request_count, 1)
            self.assertEqual(result.approval_decisions, ("decline",))
            received = json.loads(capture.read_text(encoding="utf-8"))
            approval = next(entry for entry in received if entry.get("id") == "approval-1")
            self.assertEqual(approval["result"], {"decision": "decline"})

    def test_resume_policy_equal_and_narrower_are_verified(self) -> None:
        for scenario, requested_approval, expected_sandbox, expected_approval in (
            ("completed", "on-request", "workspace-write", "on-request"),
            ("resume_narrower", "on-request", "read-only", "on-request"),
            (
                "resume_approval_narrower",
                "never",
                "workspace-write",
                "on-request",
            ),
        ):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                thread_id = str(uuid4())
                command = _fake_app_server(
                    root,
                    scenario=scenario,
                    thread_id=thread_id,
                    capture_path=root / "capture.json",
                )

                result = run_codex_app_server_activation(
                    render_codex_app_server_argv(codex_executable=str(command)),
                    cwd=str(root),
                    thread_id=thread_id,
                    input_text="Verify the effective resume policy.",
                    add_dirs=(str(root / "platform"),),
                    sandbox_mode="workspace-write",
                    approval_policy=requested_approval,
                    timeout_seconds=5,
                )

                self.assertEqual(result.status, CodexAppServerRunStatus.COMPLETED)
                self.assertTrue(result.resume_policy_verified)
                self.assertEqual(result.effective_sandbox, expected_sandbox)
                self.assertEqual(result.effective_approval_policy, expected_approval)
                self.assertFalse(result.effective_network_access)

    def test_resume_policy_expansion_or_missing_evidence_fails_before_turn_start(self) -> None:
        for scenario, requested_approval, category in (
            ("resume_wider", "on-request", "app_server_resume_policy_expanded"),
            (
                "resume_approval_wider",
                "on-request",
                "app_server_resume_policy_expanded",
            ),
            (
                "resume_network_wider",
                "on-request",
                "app_server_resume_policy_expanded",
            ),
            (
                "resume_root_wider",
                "on-request",
                "app_server_resume_policy_expanded",
            ),
            (
                "resume_active_profile",
                "on-request",
                "app_server_resume_policy_unverified",
            ),
            (
                "resume_wrong_cwd",
                "on-request",
                "app_server_resume_policy_expanded",
            ),
            (
                "resume_missing_evidence",
                "on-request",
                "app_server_resume_policy_unverified",
            ),
        ):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                thread_id = str(uuid4())
                capture = root / "capture.json"
                command = _fake_app_server(
                    root,
                    scenario=scenario,
                    thread_id=thread_id,
                    capture_path=capture,
                )

                result = run_codex_app_server_activation(
                    render_codex_app_server_argv(codex_executable=str(command)),
                    cwd=str(root),
                    thread_id=thread_id,
                    input_text="Do not start after an unsafe resume.",
                    sandbox_mode="workspace-write",
                    approval_policy=requested_approval,
                    timeout_seconds=5,
                )

                self.assertEqual(result.status, CodexAppServerRunStatus.FAILED)
                self.assertEqual(result.failure_category, category)
                self.assertFalse(result.resume_policy_verified)
                received = json.loads(capture.read_text(encoding="utf-8"))
                self.assertNotIn("turn/start", [item.get("method") for item in received])

    def test_all_supported_server_requests_use_schema_shaped_fail_closed_responses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            thread_id = str(uuid4())
            capture = root / "capture.json"
            command = _fake_app_server(
                root,
                scenario="request_matrix",
                thread_id=thread_id,
                capture_path=capture,
            )

            result = run_codex_app_server_activation(
                render_codex_app_server_argv(codex_executable=str(command)),
                cwd=str(root),
                thread_id=thread_id,
                input_text="Exercise stable server requests.",
                timeout_seconds=5,
            )

            self.assertEqual(result.status, CodexAppServerRunStatus.COMPLETED)
            self.assertEqual(result.approval_request_count, 3)
            self.assertEqual(result.server_request_resolved_count, 5)
            received = json.loads(capture.read_text(encoding="utf-8"))
            responses = {entry.get("id"): entry for entry in received if "result" in entry}
            self.assertEqual(responses["command-1"]["result"], {"decision": "decline"})
            self.assertEqual(responses["file-1"]["result"], {"decision": "decline"})
            self.assertEqual(
                responses["permissions-1"]["result"],
                {"permissions": {}, "scope": "turn"},
            )
            self.assertEqual(
                responses["mcp-1"]["result"],
                {"action": "decline", "content": None},
            )
            self.assertEqual(
                responses["input-1"]["result"],
                {"answers": {"q1": {"answers": []}}},
            )

    def test_mismatched_and_duplicate_server_requests_are_never_approved(self) -> None:
        for scenario, request_id in (
            ("request_other_thread", "unsafe-1"),
            ("request_stale_turn", "unsafe-1"),
            ("request_duplicate", "duplicate-1"),
        ):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                thread_id = str(uuid4())
                capture = root / "capture.json"
                command = _fake_app_server(
                    root,
                    scenario=scenario,
                    thread_id=thread_id,
                    capture_path=capture,
                )

                result = run_codex_app_server_activation(
                    render_codex_app_server_argv(codex_executable=str(command)),
                    cwd=str(root),
                    thread_id=thread_id,
                    input_text="Reject unsafe request correlation.",
                    timeout_seconds=5,
                )

                self.assertEqual(result.status, CodexAppServerRunStatus.COMPLETED)
                received = json.loads(capture.read_text(encoding="utf-8"))
                matching = [entry for entry in received if entry.get("id") == request_id]
                self.assertTrue(any("error" in entry for entry in matching))
                if scenario != "request_duplicate":
                    self.assertFalse(any("result" in entry for entry in matching))
                else:
                    self.assertEqual(sum("result" in entry for entry in matching), 1)

    def test_pre_initialize_messages_fail_deterministically(self) -> None:
        for scenario, category in (
            (
                "pre_initialize_notification",
                "app_server_notification_before_initialize",
            ),
            ("pre_initialize_request", "app_server_request_before_initialize"),
        ):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                thread_id = str(uuid4())
                command = _fake_app_server(
                    root,
                    scenario=scenario,
                    thread_id=thread_id,
                    capture_path=root / "capture.json",
                )

                result = run_codex_app_server_activation(
                    render_codex_app_server_argv(codex_executable=str(command)),
                    cwd=str(root),
                    thread_id=thread_id,
                    input_text="Fail the invalid handshake.",
                    timeout_seconds=5,
                )

                self.assertEqual(result.status, CodexAppServerRunStatus.FAILED)
                self.assertEqual(result.failure_category, category)

    def test_duplicate_initialize_response_fails_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            thread_id = str(uuid4())
            command = _fake_app_server(
                root,
                scenario="duplicate_initialize_response",
                thread_id=thread_id,
                capture_path=root / "capture.json",
            )

            result = run_codex_app_server_activation(
                render_codex_app_server_argv(codex_executable=str(command)),
                cwd=str(root),
                thread_id=thread_id,
                input_text="Reject the duplicate initialize response.",
                timeout_seconds=5,
            )

            self.assertEqual(result.status, CodexAppServerRunStatus.FAILED)
            self.assertEqual(result.failure_category, "app_server_duplicate_response")
            self.assertEqual(result.protocol_error_count, 1)

    def test_deprecated_output_delta_is_ignored_for_final_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            thread_id = str(uuid4())
            command = _fake_app_server(
                root,
                scenario="deprecated_delta_only",
                thread_id=thread_id,
                capture_path=root / "capture.json",
            )

            result = run_codex_app_server_activation(
                render_codex_app_server_argv(codex_executable=str(command)),
                cwd=str(root),
                thread_id=thread_id,
                input_text="Ignore deprecated output delta.",
                timeout_seconds=5,
            )

            self.assertEqual(result.status, CodexAppServerRunStatus.COMPLETED)
            self.assertIsNone(result.final_response)
            self.assertIn("item/fileChange/outputDelta", result.notification_methods)

    def test_unknown_notification_is_counted_and_safely_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            thread_id = str(uuid4())
            command = _fake_app_server(
                root,
                scenario="unknown_notification",
                thread_id=thread_id,
                capture_path=root / "capture.json",
            )

            result = run_codex_app_server_activation(
                render_codex_app_server_argv(codex_executable=str(command)),
                cwd=str(root),
                thread_id=thread_id,
                input_text="Ignore the unknown notification.",
                timeout_seconds=5,
            )

            self.assertEqual(result.status, CodexAppServerRunStatus.COMPLETED)
            self.assertEqual(result.final_response, "final answer from app-server")
            self.assertIn("future/notification", result.notification_methods)

    def test_explicit_accept_for_session_maps_to_wire_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            thread_id = str(uuid4())
            capture = root / "capture.json"
            command = _fake_app_server(
                root,
                scenario="approval",
                thread_id=thread_id,
                capture_path=capture,
            )

            result = run_codex_app_server_activation(
                render_codex_app_server_argv(codex_executable=str(command)),
                cwd=str(root),
                thread_id=thread_id,
                input_text="Request an explicit approval.",
                approval_decision="accept_for_session",
                timeout_seconds=5,
            )

            self.assertEqual(result.approval_decisions, ("acceptForSession",))
            received = json.loads(capture.read_text(encoding="utf-8"))
            approval = next(entry for entry in received if entry.get("id") == "approval-1")
            self.assertEqual(approval["result"], {"decision": "acceptForSession"})

    def test_unknown_server_request_is_rejected_without_becoming_response_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            thread_id = str(uuid4())
            capture = root / "capture.json"
            command = _fake_app_server(
                root,
                scenario="unknown_request",
                thread_id=thread_id,
                capture_path=capture,
            )

            result = run_codex_app_server_activation(
                render_codex_app_server_argv(codex_executable=str(command)),
                cwd=str(root),
                thread_id=thread_id,
                input_text="Complete after an unknown request.",
                timeout_seconds=5,
            )

            self.assertEqual(result.status, CodexAppServerRunStatus.COMPLETED)
            self.assertEqual(result.final_response, "final answer from app-server")
            self.assertEqual(result.protocol_error_count, 1)
            received = json.loads(capture.read_text(encoding="utf-8"))
            rejected = next(entry for entry in received if entry.get("id") == "unknown-1")
            self.assertEqual(rejected["error"]["code"], -32601)

    def test_thread_not_found_is_non_retryable_and_does_not_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            thread_id = str(uuid4())
            capture = root / "capture.json"
            command = _fake_app_server(
                root,
                scenario="not_found",
                thread_id=thread_id,
                capture_path=capture,
            )

            result = run_codex_app_server_activation(
                render_codex_app_server_argv(codex_executable=str(command)),
                cwd=str(root),
                thread_id=thread_id,
                input_text="This thread does not exist.",
                timeout_seconds=5,
            )

            self.assertEqual(result.status, CodexAppServerRunStatus.FAILED)
            self.assertEqual(result.failure_category, "app_server_thread_not_found")
            self.assertFalse(result.retryable)
            self.assertFalse(result.thread_verified)

    def test_invalid_json_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            thread_id = str(uuid4())
            command = _fake_app_server(
                root,
                scenario="invalid_json",
                thread_id=thread_id,
                capture_path=root / "capture.json",
            )

            result = run_codex_app_server_activation(
                render_codex_app_server_argv(codex_executable=str(command)),
                cwd=str(root),
                thread_id=thread_id,
                input_text="Fail closed.",
                timeout_seconds=5,
            )

            self.assertEqual(result.status, CodexAppServerRunStatus.FAILED)
            self.assertEqual(result.failure_category, "app_server_invalid_json")
            self.assertEqual(result.protocol_error_count, 1)
            self.assertIsNone(result.final_response)

    def test_timeout_requests_interrupt_and_terminates_bounded_connection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            thread_id = str(uuid4())
            capture = root / "capture.json"
            command = _fake_app_server(
                root,
                scenario="timeout",
                thread_id=thread_id,
                capture_path=capture,
            )

            result = run_codex_app_server_activation(
                render_codex_app_server_argv(codex_executable=str(command)),
                cwd=str(root),
                thread_id=thread_id,
                input_text="Wait until Beacon interrupts.",
                timeout_seconds=1,
            )

            self.assertEqual(result.status, CodexAppServerRunStatus.FAILED)
            self.assertEqual(result.failure_category, "app_server_timeout")
            self.assertTrue(result.process_timed_out)
            self.assertTrue(result.retryable)
            received = json.loads(capture.read_text(encoding="utf-8"))
            self.assertIn("turn/interrupt", [entry.get("method") for entry in received])


def _fake_app_server(
    root: Path,
    *,
    scenario: str,
    thread_id: str,
    capture_path: Path,
) -> Path:
    script = root / f"fake_app_server_{scenario}.py"
    command = root / (
        f"fake_app_server_{scenario}.cmd"
        if os.name == "nt"
        else f"fake_app_server_{scenario}"
    )
    script.write_text(
        "\n".join(
            [
                "import json, pathlib, sys",
                f"SCENARIO = {scenario!r}",
                f"THREAD_ID = {thread_id!r}",
                f"CAPTURE_PATH = pathlib.Path({str(capture_path)!r})",
                "received = []",
                "request_index = 0",
                "def send(value):",
                "    print(json.dumps(value), flush=True)",
                "def request_matrix():",
                "    return [",
                "        {'method':'item/commandExecution/requestApproval','id':'command-1','params':{'threadId':THREAD_ID,'turnId':'turn-1','itemId':'cmd-1','startedAtMs':1,'command':'echo test','cwd':str(CAPTURE_PATH.parent)}},",
                "        {'method':'item/fileChange/requestApproval','id':'file-1','params':{'threadId':THREAD_ID,'turnId':'turn-1','itemId':'file-item-1','startedAtMs':2,'reason':'test'}},",
                "        {'method':'item/permissions/requestApproval','id':'permissions-1','params':{'threadId':THREAD_ID,'turnId':'turn-1','itemId':'permissions-item-1','startedAtMs':3,'cwd':str(CAPTURE_PATH.parent),'permissions':{'fileSystem':{'read':['.'],'write':['.']}}}},",
                "        {'method':'mcpServer/elicitation/request','id':'mcp-1','params':{'threadId':THREAD_ID,'turnId':'turn-1','serverName':'fake','message':'test','mode':'form','requestedSchema':{'type':'object'}}},",
                "        {'method':'item/tool/requestUserInput','id':'input-1','params':{'threadId':THREAD_ID,'turnId':'turn-1','itemId':'tool-1','isBlocking':True,'questions':[{'id':'q1','header':'Choice','question':'Continue?','options':[{'label':'No','description':'Decline'}]}]}},",
                "    ]",
                "def send_next_matrix_request():",
                "    global request_index",
                "    requests = request_matrix()",
                "    if request_index >= len(requests):",
                "        complete()",
                "        return",
                "    send(requests[request_index])",
                "    request_index += 1",
                "def resume_result(params):",
                "    cwd = params.get('cwd')",
                "    sandbox = params.get('sandbox', 'read-only')",
                "    approval = params.get('approvalPolicy', 'on-request')",
                "    if SCENARIO == 'resume_missing_evidence':",
                "        return {'thread':{'id':THREAD_ID,'sessionId':THREAD_ID,'status':{'type':'idle'}}}",
                "    if SCENARIO == 'resume_wider':",
                "        sandbox = 'danger-full-access'",
                "        approval = 'never'",
                "    elif SCENARIO == 'resume_approval_wider':",
                "        approval = 'never'",
                "    elif SCENARIO == 'resume_narrower':",
                "        sandbox = 'read-only'",
                "    elif SCENARIO == 'resume_approval_narrower':",
                "        approval = 'on-request'",
                "    elif SCENARIO == 'resume_wrong_cwd':",
                "        cwd = str(CAPTURE_PATH.parent / 'other')",
                "    if sandbox == 'workspace-write':",
                "        extra = params.get('config', {}).get('sandbox_workspace_write', {}).get('writable_roots', [])",
                "        roots = [cwd, *extra]",
                "        if SCENARIO == 'resume_root_wider':",
                "            roots.append(str(CAPTURE_PATH.parent / 'unexpected-root'))",
                "        policy = {'type':'workspaceWrite','writableRoots':roots,'networkAccess':SCENARIO == 'resume_network_wider'}",
                "    elif sandbox == 'danger-full-access':",
                "        policy = {'type':'dangerFullAccess'}",
                "    else:",
                "        policy = {'type':'readOnly','networkAccess':False}",
                "    result = {'thread':{'id':THREAD_ID,'sessionId':THREAD_ID,'status':{'type':'idle'}},'cwd':cwd,'sandbox':policy,'approvalPolicy':approval,'approvalsReviewer':'user','model':'fake','modelProvider':'fake'}",
                "    if SCENARIO == 'resume_active_profile':",
                "        result['activePermissionProfile'] = {'permissions': {'network': True}}",
                "    return result",
                "def complete():",
                "    send({'method':'thread/status/changed','params':{'threadId':THREAD_ID,'status':{'type':'active','activeFlags':[]}}})",
                "    if SCENARIO == 'deprecated_delta_only':",
                "        send({'method':'item/fileChange/outputDelta','params':{'threadId':THREAD_ID,'turnId':'turn-1','itemId':'file-1','delta':'must not become final text'}})",
                "        send({'method':'turn/completed','params':{'threadId':THREAD_ID,'turn':{'id':'turn-1','status':'completed','itemsView':'summary','items':[],'error':None}}})",
                "    elif SCENARIO == 'summary_only':",
                "        send({'method':'turn/completed','params':{'threadId':THREAD_ID,'turn':{'id':'turn-1','status':'completed','itemsView':'summary','items':[{'type':'agentMessage','id':'summary-1','phase':'final_answer','text':'final answer from completion summary'}],'error':None}}})",
                "    else:",
                "        if SCENARIO == 'diagnostics':",
                "            send({'method':'error','params':{'threadId':THREAD_ID,'turnId':'turn-1','willRetry':True,'error':{'message':'temporary upstream failure','codexErrorInfo':{'kind':'rateLimit'},'additionalDetails':{'retryAfterMs':250}}}})",
                "            send({'method':'deprecationNotice','params':{'summary':'Legacy field is deprecated','details':'Use the stable replacement field.'}})",
                "        if SCENARIO == 'unknown_notification':",
                "            send({'method':'future/notification','params':{'threadId':THREAD_ID,'value':1}})",
                "        send({'method':'item/completed','params':{'threadId':THREAD_ID,'turnId':'turn-1','completedAtMs':1,'item':{'type':'agentMessage','id':'msg-1','phase':'commentary','text':'progress only'}}})",
                "        send({'method':'item/completed','params':{'threadId':THREAD_ID,'turnId':'turn-1','completedAtMs':2,'item':{'type':'agentMessage','id':'msg-2','phase':'final_answer','text':'final answer from app-server'}}})",
                "        send({'method':'turn/completed','params':{'threadId':THREAD_ID,'turn':{'id':'turn-1','status':'completed','itemsView':'summary','items':[{'type':'agentMessage','id':'summary-2','phase':'final_answer','text':'final answer from app-server'}],'error':None}}})",
                "    send({'method':'thread/status/changed','params':{'threadId':THREAD_ID,'status':{'type':'idle'}}})",
                "try:",
                "    while True:",
                "        line = sys.stdin.readline()",
                "        if not line:",
                "            break",
                "        message = json.loads(line)",
                "        received.append(message)",
                "        method = message.get('method')",
                "        request_id = message.get('id')",
                "        if method == 'initialize':",
                "            if SCENARIO == 'invalid_json':",
                "                print('not-json', flush=True)",
                "            elif SCENARIO == 'pre_initialize_notification':",
                "                send({'method':'warning','params':{'message':'too early'}})",
                "            elif SCENARIO == 'pre_initialize_request':",
                "                send({'method':'item/commandExecution/requestApproval','id':'early-1','params':{'threadId':THREAD_ID,'turnId':'turn-1','itemId':'cmd-1','startedAtMs':1}})",
                "            else:",
                "                send({'id':request_id,'result':{'userAgent':'codex-cli 0.149.0'}})",
                "                if SCENARIO == 'duplicate_initialize_response':",
                "                    send({'id':request_id,'result':{'userAgent':'codex-cli 0.149.0'}})",
                "        elif method == 'initialized':",
                "            pass",
                "        elif method == 'thread/read':",
                "            if SCENARIO == 'not_found':",
                "                send({'id':request_id,'error':{'code':-32000,'message':'thread not found'}})",
                "            else:",
                "                status = {'type':'active','activeFlags':['waitingOnApproval']} if SCENARIO == 'busy' else {'type':'notLoaded'}",
                "                send({'id':request_id,'result':{'thread':{'id':THREAD_ID,'sessionId':THREAD_ID,'status':status}}})",
                "        elif method == 'thread/resume':",
                "            send({'id':request_id,'result':resume_result(message.get('params', {}))})",
                "        elif method == 'turn/start':",
                "            send({'id':request_id,'result':{'turn':{'id':'turn-1','status':'inProgress','items':[],'error':None}}})",
                "            if SCENARIO == 'approval':",
                "                send({'method':'item/commandExecution/requestApproval','id':'approval-1','params':{'threadId':THREAD_ID,'turnId':'turn-1','itemId':'cmd-1','startedAtMs':1,'command':'echo test','cwd':str(CAPTURE_PATH.parent)}})",
                "            elif SCENARIO == 'request_matrix':",
                "                send_next_matrix_request()",
                "            elif SCENARIO == 'request_other_thread':",
                "                send({'method':'item/commandExecution/requestApproval','id':'unsafe-1','params':{'threadId':'other-thread','turnId':'turn-1','itemId':'cmd-1','startedAtMs':1}})",
                "            elif SCENARIO == 'request_stale_turn':",
                "                send({'method':'item/commandExecution/requestApproval','id':'unsafe-1','params':{'threadId':THREAD_ID,'turnId':'old-turn','itemId':'cmd-1','startedAtMs':1}})",
                "            elif SCENARIO == 'request_duplicate':",
                "                send({'method':'item/commandExecution/requestApproval','id':'duplicate-1','params':{'threadId':THREAD_ID,'turnId':'turn-1','itemId':'cmd-1','startedAtMs':1}})",
                "            elif SCENARIO == 'unknown_request':",
                "                send({'method':'beacon/unknown/request','id':'unknown-1','params':{'threadId':THREAD_ID,'turnId':'turn-1'}})",
                "            elif SCENARIO not in ('timeout', 'steer', 'steer_unsupported', 'steer_disconnect'):",
                "                complete()",
                "        elif method == 'turn/steer':",
                "            if SCENARIO == 'steer_disconnect':",
                "                break",
                "            if SCENARIO == 'steer_unsupported':",
                "                send({'id':request_id,'error':{'code':-32601,'message':'method not found'}})",
                "            else:",
                "                send({'id':request_id,'result':{'turnId':'turn-1'}})",
                "            complete()",
                "        elif request_id == 'approval-1':",
                "            complete()",
                "        elif SCENARIO == 'request_matrix' and request_id in ('command-1','file-1','permissions-1','mcp-1','input-1'):",
                "            send({'method':'serverRequest/resolved','params':{'threadId':THREAD_ID,'requestId':request_id}})",
                "            send_next_matrix_request()",
                "        elif SCENARIO in ('request_other_thread','request_stale_turn') and request_id == 'unsafe-1':",
                "            complete()",
                "        elif SCENARIO == 'request_duplicate' and request_id == 'duplicate-1':",
                "            if 'result' in message:",
                "                send({'method':'item/commandExecution/requestApproval','id':'duplicate-1','params':{'threadId':THREAD_ID,'turnId':'turn-1','itemId':'cmd-2','startedAtMs':2}})",
                "            else:",
                "                complete()",
                "        elif request_id == 'unknown-1':",
                "            complete()",
                "        elif method == 'turn/interrupt':",
                "            send({'id':request_id,'result':{}})",
                "            send({'method':'turn/completed','params':{'threadId':THREAD_ID,'turn':{'id':'turn-1','status':'interrupted','items':[],'error':None}}})",
                "finally:",
                "    CAPTURE_PATH.write_text(json.dumps(received), encoding='utf-8')",
            ]
        ),
        encoding="utf-8",
    )
    if os.name == "nt":
        command.write_text(
            "\n".join(["@echo off", f'"{sys.executable}" "{script}" %*']),
            encoding="utf-8",
        )
    else:
        command.write_text(
            "\n".join(
                [
                    "#!/bin/sh",
                    f"exec {shlex.quote(sys.executable)} {shlex.quote(str(script))} \"$@\"",
                ]
            ),
            encoding="utf-8",
        )
        command.chmod(0o755)
    return command


if __name__ == "__main__":
    unittest.main()
