from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.agent_session_discovery import (
    discover_agent_sessions,
)
from agent_os.application.services.local_platform_application import (
    LocalPlatformApplication,
)
from agent_os.infrastructure.config import LocalPlatformSettings


class AgentSessionDiscoveryServiceTests(unittest.TestCase):
    def test_discovers_claude_jsonl_without_leaking_message_body(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cwd = root / "workspace"
            cwd.mkdir()
            claude_home = root / ".claude"
            project = claude_home / "projects" / "F--Documents-Agent-Chat"
            project.mkdir(parents=True)
            session_id = str(uuid4())
            secret_body = "SECRET_CLAUDE_TRANSCRIPT_BODY"
            (project / f"{session_id}.jsonl").write_text(
                "\n".join(
                    (
                        json.dumps({"type": "system", "sessionId": session_id}),
                        json.dumps(
                            {
                                "type": "user",
                                "sessionId": session_id,
                                "cwd": str(cwd),
                                "message": {"content": secret_body},
                            }
                        ),
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            result = discover_agent_sessions(
                provider="claude",
                claude_home=str(claude_home),
            )

            self.assertEqual(result["count"], 1)
            record = result["agentSessions"][0]
            self.assertEqual(record["agentRuntime"], "claude")
            self.assertEqual(record["sessionId"], session_id)
            self.assertEqual(record["providerSessionField"], "claudeSessionUuid")
            self.assertTrue(record["registrationReady"])
            self.assertEqual(record["cwd"], str(cwd))
            self.assertNotIn(secret_body, json.dumps(result))

    def test_discovers_codex_session_meta_without_leaking_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cwd = root / "workspace"
            cwd.mkdir()
            codex_home = root / ".codex"
            sessions = codex_home / "sessions" / "2026" / "06" / "28"
            sessions.mkdir(parents=True)
            session_id = "codex-session-27-3"
            secret_body = "SECRET_CODEX_BASE_INSTRUCTIONS"
            (sessions / "rollout-2026-06-28T00-00-00-session.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-06-28T00:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "session_id": session_id,
                            "cwd": str(cwd),
                            "base_instructions": secret_body,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = discover_agent_sessions(
                provider="codex",
                codex_home=str(codex_home),
            )

            self.assertEqual(result["count"], 1)
            record = result["agentSessions"][0]
            self.assertEqual(record["agentRuntime"], "codex")
            self.assertEqual(record["sessionId"], session_id)
            self.assertEqual(record["providerSessionField"], "codexSessionId")
            self.assertTrue(record["registrationReady"])
            self.assertEqual(record["cwd"], str(cwd))
            self.assertNotIn(secret_body, json.dumps(result))

    def test_discovers_codex_current_session_and_opt_in_turn_snippet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cwd = root / "workspace"
            cwd.mkdir()
            codex_home = root / ".codex"
            sessions = codex_home / "sessions" / "2026" / "06" / "30"
            sessions.mkdir(parents=True)
            session_id = "codex-session-27-12"
            (sessions / "rollout-2026-06-30T00-00-00-session.jsonl").write_text(
                "\n".join(
                    (
                        json.dumps(
                            {
                                "timestamp": "2026-06-30T00:00:00Z",
                                "type": "session_meta",
                                "payload": {
                                    "session_id": session_id,
                                    "cwd": str(cwd),
                                    "providerAccountLabel": "relay-profile",
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "user",
                                "payload": {
                                    "message": {
                                        "content": "first user turn visible by opt-in"
                                    }
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "assistant",
                                "message": {
                                    "content": "first assistant turn visible by opt-in"
                                },
                            }
                        ),
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            result = discover_agent_sessions(
                provider="codex",
                codex_home=str(codex_home),
                current_session_id=session_id,
                include_turn_snippets=True,
                snippet_turn_index=1,
                snippet_max_chars=12,
            )

            self.assertEqual(result["count"], 1)
            self.assertEqual(result["agentSessionDiscovery"]["currentSessionMatchCount"], 1)
            record = result["agentSessions"][0]
            self.assertTrue(record["currentSessionMatch"])
            self.assertTrue(record["providerAccountRead"])
            self.assertEqual(record["providerAccountLabel"], "relay-profile")
            self.assertTrue(record["turnSnippetRead"])
            self.assertEqual(record["turnSnippet"]["turnIndex"], 1)
            self.assertEqual(
                record["turnSnippet"]["user"],
                "first use...",
            )
            self.assertEqual(record["turnSnippet"]["messages"][0]["role"], "user")
            self.assertEqual(record["turnSnippet"]["messages"][0]["maxChars"], 12)
            self.assertTrue(record["turnSnippet"]["messages"][0]["truncated"])
            self.assertGreater(
                record["turnSnippet"]["messages"][0]["originalCharCount"],
                12,
            )
            self.assertFalse(record["fullSessionHistoryRead"])

    def test_discovery_filters_account_labels_and_full_history_requires_opt_in(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cwd = root / "workspace"
            cwd.mkdir()
            codex_home = root / ".codex"
            sessions = codex_home / "sessions" / "2026" / "07" / "01"
            sessions.mkdir(parents=True)
            (sessions / "rollout-2026-07-01T00-00-00-a.jsonl").write_text(
                "\n".join(
                    (
                        json.dumps(
                            {
                                "timestamp": "2026-07-01T00:00:00Z",
                                "type": "session_meta",
                                "payload": {
                                    "session_id": "codex-session-matching-account",
                                    "cwd": str(cwd),
                                    "providerAccountLabel": "openai-work",
                                    "vendorAccountLabel": "org-1",
                                    "relayAccountLabel": "relay-blue",
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "user",
                                "payload": {
                                    "message": {
                                        "content": (
                                            "full message only visible through "
                                            "explicit opt-in"
                                        )
                                    }
                                },
                            }
                        ),
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            (sessions / "rollout-2026-07-01T00-00-00-b.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-07-01T00:00:01Z",
                        "type": "session_meta",
                        "payload": {
                            "session_id": "codex-session-other-account",
                            "cwd": str(cwd),
                            "providerAccountLabel": "openai-personal",
                            "vendorAccountLabel": "org-2",
                            "relayAccountLabel": "relay-green",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            default = discover_agent_sessions(
                provider="codex",
                codex_home=str(codex_home),
                provider_account_label="openai-work",
            )
            self.assertEqual(default["count"], 1)
            self.assertFalse(default["agentSessions"][0]["fullSessionHistoryRead"])
            self.assertNotIn("full message only visible", json.dumps(default))

            with_history = discover_agent_sessions(
                provider="codex",
                codex_home=str(codex_home),
                provider_account_label="openai-work",
                vendor_account_label="org-1",
                relay_account_label="relay-blue",
                include_full_session_history=True,
            )
            self.assertEqual(with_history["count"], 1)
            discovery = with_history["agentSessionDiscovery"]
            self.assertTrue(discovery["accountLabelFilter"]["active"])
            self.assertFalse(discovery["fullSessionHistoryReadDefault"])
            record = with_history["agentSessions"][0]
            self.assertEqual(record["providerAccountLabel"], "openai-work")
            self.assertEqual(record["vendorAccountLabel"], "org-1")
            self.assertEqual(record["relayAccountLabel"], "relay-blue")
            self.assertTrue(record["fullSessionHistoryRead"])
            self.assertEqual(record["sessionHistory"]["readMode"], "explicit_opt_in")
            self.assertIn(
                "full message only visible through explicit opt-in",
                record["sessionHistory"]["messages"][0]["text"],
            )

            unmatched = discover_agent_sessions(
                provider="codex",
                codex_home=str(codex_home),
                provider_account_label="missing-account",
            )
            self.assertEqual(unmatched["count"], 0)

    def test_full_history_enforces_character_and_message_budgets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex_home = root / ".codex"
            sessions = codex_home / "sessions" / "2026" / "07" / "13"
            sessions.mkdir(parents=True)
            session_path = sessions / "bounded-history-session.jsonl"
            rows = [
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "session_id": "bounded-history-session",
                            "cwd": str(root),
                        },
                    }
                )
            ]
            rows.extend(
                json.dumps(
                    {
                        "type": "user",
                        "payload": {"message": {"content": "x" * 1000}},
                    }
                )
                for _ in range(140)
            )
            session_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

            result = discover_agent_sessions(
                provider="codex",
                codex_home=str(codex_home),
                include_full_session_history=True,
            )

            history = result["agentSessions"][0]["sessionHistory"]
            self.assertTrue(history["truncated"])
            self.assertIn("full_history_character_limit", history["truncationReason"])
            self.assertLessEqual(history["messageCount"], history["maxMessageCount"])
            self.assertEqual(history["characterCount"], history["maxCharacterCount"])
            self.assertEqual(history["scannedLineCount"], len(rows))
            self.assertGreater(history["scannedByteCount"], history["characterCount"])

    def test_jsonl_scan_skips_oversized_lines_and_reports_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex_home = root / ".codex"
            sessions = codex_home / "sessions"
            sessions.mkdir(parents=True)
            session_path = sessions / "oversized-line-session.jsonl"
            oversized = json.dumps(
                {"type": "user", "payload": {"message": {"content": "x" * (1024 * 1024)}}}
            )
            metadata = json.dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "session_id": "oversized-line-session",
                        "cwd": str(root),
                    },
                }
            )
            session_path.write_text(oversized + "\n" + metadata + "\n", encoding="utf-8")

            result = discover_agent_sessions(
                provider="codex",
                codex_home=str(codex_home),
                include_full_session_history=True,
            )

            record = result["agentSessions"][0]
            history = record["sessionHistory"]
            self.assertEqual(record["sessionId"], "oversized-line-session")
            self.assertTrue(history["truncated"])
            self.assertIn("jsonl_line_byte_limit", history["truncationReason"])
            self.assertEqual(history["scannedLineCount"], 2)
            self.assertEqual(
                record["metadata"]["jsonlScan"]["truncationReason"],
                "jsonl_line_byte_limit",
            )

    def test_recursive_json_metadata_parsing_stops_at_bounded_depth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex_home = root / ".codex"
            sessions = codex_home / "sessions"
            sessions.mkdir(parents=True)
            nested: dict[str, object] = {"session_id": "too-deep-session"}
            for _ in range(24):
                nested = {"nested": nested}
            (sessions / "filename-fallback-session.jsonl").write_text(
                json.dumps(nested) + "\n",
                encoding="utf-8",
            )

            result = discover_agent_sessions(
                provider="codex",
                codex_home=str(codex_home),
            )

            self.assertEqual(
                result["agentSessions"][0]["sessionId"],
                "filename-fallback-session",
            )

    def test_discovers_hermes_sessions_list_output_with_cwd_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cwd = root / "workspace"
            cwd.mkdir()
            session_id = "20260627_225530_4ca16d"
            fake_hermes = _fake_hermes_sessions_command(root, session_id)

            result = discover_agent_sessions(
                provider="hermes",
                hermes_executable=str(fake_hermes),
                cwd=str(cwd),
            )

            self.assertEqual(result["discoveryErrors"], [])
            self.assertEqual(result["count"], 1)
            record = result["agentSessions"][0]
            self.assertEqual(record["agentRuntime"], "hermes")
            self.assertEqual(record["sessionId"], session_id)
            self.assertEqual(record["providerSessionField"], "hermesSessionId")
            self.assertEqual(record["cwd"], str(cwd))
            self.assertEqual(record["cwdSource"], "fallback")
            self.assertTrue(record["registrationReady"])

    def test_discovers_hermes_state_db_metadata_with_instance_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cwd = root / "workspace"
            cwd.mkdir()
            hermes_home = root / "hermes-home"
            expected = "20260710_120000_expected"
            _write_hermes_state_db(
                hermes_home,
                (
                    (expected, "cli", str(cwd), 100.0),
                    ("20260710_120001_desktop", "desktop", str(cwd), 101.0),
                ),
            )

            result = discover_agent_sessions(
                provider="hermes",
                hermes_home=str(hermes_home),
                hermes_source="cli",
                current_session_id=expected,
            )

            self.assertEqual(result["count"], 1)
            self.assertEqual(result["discoveryErrors"], [])
            self.assertEqual(result["discoveryDiagnostics"], [])
            record = result["agentSessions"][0]
            self.assertEqual(record["sourceKind"], "hermes_state_db_metadata")
            self.assertEqual(record["sessionId"], expected)
            self.assertTrue(record["currentSessionMatch"])
            identity = record["providerSessionIdentity"]
            self.assertEqual(identity["runtimeHome"], str(hermes_home.resolve()))
            self.assertEqual(identity["runtimeHomeSource"], "explicit")
            self.assertEqual(identity["sessionSource"], "cli")
            self.assertEqual(identity["sourceFilter"], "cli")
            self.assertFalse(identity["fullSessionHistoryRead"])

    def test_hermes_discovery_distinguishes_empty_source_and_runtime_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hermes_home = root / "hermes-home"
            expected = "20260710_120000_expected"
            _write_hermes_state_db(
                hermes_home,
                ((expected, "desktop", str(root), 100.0),),
            )

            source_mismatch = discover_agent_sessions(
                provider="hermes",
                hermes_home=str(hermes_home),
                hermes_source="cli",
                current_session_id=expected,
            )
            runtime_mismatch = discover_agent_sessions(
                provider="hermes",
                hermes_home=str(hermes_home),
                current_session_id="20260710_120099_missing",
            )

            source_categories = {
                item["diagnosticCategory"]
                for item in source_mismatch["discoveryDiagnostics"]
            }
            runtime_categories = {
                item["diagnosticCategory"]
                for item in runtime_mismatch["discoveryDiagnostics"]
            }
            self.assertIn("no_sessions", source_categories)
            self.assertIn("source_filter_mismatch", source_categories)
            self.assertNotIn("runtime_home_mismatch", source_categories)
            self.assertIn("runtime_home_mismatch", runtime_categories)

    def test_hermes_cli_empty_and_failure_are_not_silent_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty = _fake_hermes_sessions_result(
                root,
                "hermes-empty",
                output="No sessions found",
                exit_code=0,
            )
            failed = _fake_hermes_sessions_result(
                root,
                "hermes-failed",
                output="session store unavailable",
                exit_code=7,
            )

            empty_result = discover_agent_sessions(
                provider="hermes",
                hermes_executable=str(empty),
            )
            failed_result = discover_agent_sessions(
                provider="hermes",
                hermes_executable=str(failed),
            )

            self.assertEqual(empty_result["count"], 0)
            self.assertEqual(
                empty_result["discoveryDiagnostics"][0]["diagnosticCategory"],
                "no_sessions",
            )
            self.assertEqual(failed_result["count"], 0)
            self.assertEqual(
                failed_result["discoveryErrors"][0]["failureCategory"],
                "command_failed",
            )


class AgentSessionDiscoveryCliTests(unittest.TestCase):
    def test_register_discovered_hermes_session_preserves_instance_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cwd = root / "workspace"
            cwd.mkdir()
            hermes_home = root / "hermes-home"
            session_id = "20260710_120000_registered"
            _write_hermes_state_db(
                hermes_home,
                ((session_id, "cli", str(cwd), 100.0),),
            )
            app = LocalPlatformApplication(
                LocalPlatformSettings(
                    database=str(root / "platform.sqlite3"),
                    workspace_root=str(root / "runtime-workspace"),
                    plugins_directory=str(root / "plugins"),
                )
            )
            app.create_workspace(
                workspace_id="workspace-hermes-discovery",
                display_name="Hermes Discovery Workspace",
                root_path=str(cwd),
                agent_id="agent-a",
            )
            app.create_agent(
                workspace_id="workspace-hermes-discovery",
                agent_id="agent-b",
                name="Agent B",
                description="Hermes target.",
            )

            result = app.register_discovered_agent_session_handle(
                workspace_id="workspace-hermes-discovery",
                agent_id="agent-b",
                provider="hermes",
                session_id=session_id,
                handle_id="hermes-discovered-handle",
                created_by="tester",
                reason="register structured Hermes discovery",
                hermes_home=str(hermes_home),
                hermes_source="cli",
            )

            handle = result["hermesSessionHandle"]
            identity = handle["metadata"]["hermesSessionIdentity"]
            self.assertEqual(identity["providerSessionId"], session_id)
            self.assertEqual(identity["runtimeHome"], str(hermes_home.resolve()))
            self.assertEqual(identity["sessionSource"], "cli")
            self.assertFalse(identity["fullSessionHistoryRead"])

    def test_application_logs_endpoint_from_discovered_codex_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cwd = root / "workspace"
            cwd.mkdir()
            codex_home = root / ".codex"
            sessions = codex_home / "sessions" / "2026" / "06" / "29"
            sessions.mkdir(parents=True)
            session_id = "codex-login-session-27-7"
            (sessions / "rollout-2026-06-29T00-00-00-codex.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-06-29T00:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "session_id": session_id,
                            "cwd": str(cwd),
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            app = LocalPlatformApplication(
                LocalPlatformSettings(
                    database=str(root / "platform.sqlite3"),
                    workspace_root=str(root / "runtime-workspace"),
                    plugins_directory=str(root / "plugins"),
                )
            )
            app.create_workspace(
                workspace_id="workspace-login-discovered",
                display_name="Login Discovered Workspace",
                root_path=str(cwd),
                agent_id="agent-a",
            )

            result = app.login_discovered_agent_endpoint(
                workspace_id="workspace-login-discovered",
                agent_id="agent-a",
                provider="codex",
                alias="Codex-Main",
                handle_id="handle-login-codex",
                endpoint_id="endpoint-login-codex",
                cwd=str(cwd),
                codex_home=str(codex_home),
                created_by="user",
                reason="login discovered Codex session",
            )

            self.assertEqual(result["schema"], "agent_endpoint_login_discovered.v1")
            self.assertTrue(result["handleRegistered"])
            self.assertTrue(result["endpointLoggedIn"])
            self.assertEqual(result["selection"]["selectionMethod"], "unique_cwd_match")
            self.assertTrue(result["selection"]["cwdMatched"])
            self.assertEqual(result["discoveredAgentSession"]["sessionId"], session_id)
            self.assertEqual(
                result["registeredSessionHandle"]["handleId"],
                "handle-login-codex",
            )
            self.assertEqual(result["agentEndpoint"]["alias"], "codex-main")
            self.assertEqual(
                result["agentEndpoint"]["providerHandleId"],
                "handle-login-codex",
            )
            self.assertEqual(
                result["agentEndpoint"]["metadata"]["endpointLoginMacro"][
                    "selectionMethod"
                ],
                "unique_cwd_match",
            )
            listed = app.list_agent_endpoints(
                workspace_id="workspace-login-discovered",
            )
            self.assertEqual(listed["count"], 1)
            handles = app.list_codex_session_handles(
                workspace_id="workspace-login-discovered",
                agent_id="agent-a",
            )
            self.assertEqual(len(handles["codexSessionHandles"]), 1)

    def test_application_requires_session_id_when_discovery_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cwd = root / "workspace"
            cwd.mkdir()
            codex_home = root / ".codex"
            sessions = codex_home / "sessions" / "2026" / "06" / "29"
            sessions.mkdir(parents=True)
            for index in range(2):
                path = sessions / (
                    f"rollout-2026-06-29T00-00-0{index}-codex.jsonl"
                )
                path.write_text(
                    json.dumps(
                        {
                            "timestamp": f"2026-06-29T00:00:0{index}Z",
                            "type": "session_meta",
                            "payload": {
                                "session_id": f"codex-login-session-{index}",
                                "cwd": str(cwd),
                            },
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
            app = LocalPlatformApplication(
                LocalPlatformSettings(
                    database=str(root / "platform.sqlite3"),
                    workspace_root=str(root / "runtime-workspace"),
                    plugins_directory=str(root / "plugins"),
                )
            )
            app.create_workspace(
                workspace_id="workspace-login-discovered",
                display_name="Login Discovered Workspace",
                root_path=str(cwd),
                agent_id="agent-a",
            )

            with self.assertRaisesRegex(ValueError, "pass --session-id"):
                app.login_discovered_agent_endpoint(
                    workspace_id="workspace-login-discovered",
                    agent_id="agent-a",
                    provider="codex",
                    alias="codex-main",
                    cwd=str(cwd),
                    codex_home=str(codex_home),
                    created_by="user",
                    reason="ambiguous discovered Codex session",
                )

    def test_application_provider_onboard_creates_and_reuses_codex_endpoint(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cwd, codex_home, session_id = _write_codex_session(
                root,
                "codex-provider-onboard-session",
            )
            app = LocalPlatformApplication(
                LocalPlatformSettings(
                    database=str(root / "platform.sqlite3"),
                    workspace_root=str(root / "runtime-workspace"),
                    plugins_directory=str(root / "plugins"),
                )
            )
            app.create_workspace(
                workspace_id="workspace-provider-onboard",
                display_name="Provider Onboard Workspace",
                root_path=str(cwd),
                agent_id="workspace-agent",
            )

            first = app.onboard_agent_provider(
                workspace_id="workspace-provider-onboard",
                provider="codex",
                agent_id="agent-codex",
                agent_name="Codex Agent",
                endpoint_alias="Codex-Main",
                cwd=str(cwd),
                codex_home=str(codex_home),
                created_by="user",
                reason="onboard Codex provider",
            )
            second = app.onboard_agent_provider(
                workspace_id="workspace-provider-onboard",
                provider="codex",
                agent_id="agent-codex",
                agent_name="Codex Agent",
                endpoint_alias="Codex-Main",
                cwd=str(cwd),
                codex_home=str(codex_home),
                created_by="user",
                reason="onboard Codex provider",
            )

            self.assertTrue(first["ok"])
            self.assertTrue(first["completed"])
            self.assertEqual(first["schema"], "agent_provider_onboard.v1")
            self.assertEqual(first["sessionId"], session_id)
            self.assertEqual(first["endpointAlias"], "codex-main")
            self.assertEqual(
                [stage["status"] for stage in first["stages"]],
                ["selected", "created", "registered", "logged_in"],
            )
            self.assertFalse(first["boundaries"]["providerCredentialStored"])
            self.assertFalse(first["boundaries"]["providerPermissionDefaultsModified"])
            self.assertIn("agent-endpoint-status", first["nextStatusCommand"])
            self.assertIn("agent-dispatch-send", first["nextDispatchExample"])

            self.assertTrue(second["ok"])
            self.assertEqual(
                [stage["status"] for stage in second["stages"]],
                ["selected", "reused", "reused", "reused"],
            )
            handles = app.list_codex_session_handles(
                workspace_id="workspace-provider-onboard",
                agent_id="agent-codex",
            )
            endpoints = app.list_agent_endpoints(
                workspace_id="workspace-provider-onboard",
            )
            self.assertEqual(len(handles["codexSessionHandles"]), 1)
            self.assertEqual(endpoints["count"], 1)

    def test_application_provider_onboard_rejects_endpoint_alias_conflict(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cwd, codex_home, first_session_id = _write_codex_session(
                root,
                "codex-provider-onboard-conflict-a",
                index=0,
            )
            _, _, second_session_id = _write_codex_session(
                root,
                "codex-provider-onboard-conflict-b",
                cwd=cwd,
                index=1,
            )
            app = LocalPlatformApplication(
                LocalPlatformSettings(
                    database=str(root / "platform.sqlite3"),
                    workspace_root=str(root / "runtime-workspace"),
                    plugins_directory=str(root / "plugins"),
                )
            )
            app.create_workspace(
                workspace_id="workspace-provider-onboard-conflict",
                display_name="Provider Onboard Conflict Workspace",
                root_path=str(cwd),
                agent_id="workspace-agent",
            )
            first = app.onboard_agent_provider(
                workspace_id="workspace-provider-onboard-conflict",
                provider="codex",
                session_id=first_session_id,
                agent_id="agent-codex-a",
                agent_name="Codex Agent A",
                endpoint_alias="codex-main",
                cwd=str(cwd),
                codex_home=str(codex_home),
                created_by="user",
                reason="onboard first Codex provider",
            )
            conflict = app.onboard_agent_provider(
                workspace_id="workspace-provider-onboard-conflict",
                provider="codex",
                session_id=second_session_id,
                agent_id="agent-codex-b",
                agent_name="Codex Agent B",
                endpoint_alias="codex-main",
                cwd=str(cwd),
                codex_home=str(codex_home),
                created_by="user",
                reason="onboard conflicting Codex provider",
            )

            self.assertTrue(first["ok"])
            self.assertFalse(conflict["ok"])
            self.assertFalse(conflict["completed"])
            self.assertEqual(conflict["failedStage"], "endpointLogin")
            self.assertEqual(
                [stage["status"] for stage in conflict["stages"]],
                ["selected", "created", "registered", "conflict"],
            )
            self.assertEqual(
                conflict["conflict"]["mismatches"]["agentId"]["actual"],
                "agent-codex-a",
            )
            self.assertEqual(
                conflict["conflict"]["mismatches"]["agentId"]["expected"],
                "agent-codex-b",
            )
            handles = app.list_codex_session_handles(
                workspace_id="workspace-provider-onboard-conflict",
            )
            endpoints = app.list_agent_endpoints(
                workspace_id="workspace-provider-onboard-conflict",
            )
            self.assertEqual(len(handles["codexSessionHandles"]), 2)
            self.assertEqual(endpoints["count"], 1)

    def test_application_provider_onboard_ambiguous_discovery_is_actionable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cwd, codex_home, _ = _write_codex_session(
                root,
                "codex-provider-onboard-ambiguous-a",
                index=0,
            )
            _write_codex_session(
                root,
                "codex-provider-onboard-ambiguous-b",
                cwd=cwd,
                index=1,
            )
            app = LocalPlatformApplication(
                LocalPlatformSettings(
                    database=str(root / "platform.sqlite3"),
                    workspace_root=str(root / "runtime-workspace"),
                    plugins_directory=str(root / "plugins"),
                )
            )
            app.create_workspace(
                workspace_id="workspace-provider-onboard-ambiguous",
                display_name="Provider Onboard Ambiguous Workspace",
                root_path=str(cwd),
                agent_id="workspace-agent",
            )

            result = app.onboard_agent_provider(
                workspace_id="workspace-provider-onboard-ambiguous",
                provider="codex",
                agent_id="agent-codex",
                agent_name="Codex Agent",
                endpoint_alias="codex-main",
                cwd=str(cwd),
                codex_home=str(codex_home),
                created_by="user",
                reason="onboard ambiguous Codex provider",
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["failedStage"], "sessionDiscovery")
            self.assertIn("pass --session-id", result["error"]["message"])
            self.assertEqual(result["stages"], [])
            handles = app.list_codex_session_handles(
                workspace_id="workspace-provider-onboard-ambiguous",
            )
            endpoints = app.list_agent_endpoints(
                workspace_id="workspace-provider-onboard-ambiguous",
            )
            self.assertEqual(handles["codexSessionHandles"], [])
            self.assertEqual(endpoints["count"], 0)

    def test_application_provider_onboard_dry_run_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cwd, codex_home, _ = _write_codex_session(
                root,
                "codex-provider-onboard-dry-run",
            )
            app = LocalPlatformApplication(
                LocalPlatformSettings(
                    database=str(root / "platform.sqlite3"),
                    workspace_root=str(root / "runtime-workspace"),
                    plugins_directory=str(root / "plugins"),
                )
            )
            app.create_workspace(
                workspace_id="workspace-provider-onboard-dry-run",
                display_name="Provider Onboard Dry Run Workspace",
                root_path=str(cwd),
                agent_id="workspace-agent",
            )

            result = app.onboard_agent_provider(
                workspace_id="workspace-provider-onboard-dry-run",
                provider="codex",
                agent_id="agent-codex",
                agent_name="Codex Agent",
                endpoint_alias="codex-main",
                cwd=str(cwd),
                codex_home=str(codex_home),
                created_by="user",
                reason="dry-run Codex provider onboarding",
                dry_run=True,
            )

            self.assertTrue(result["ok"])
            self.assertTrue(result["dryRun"])
            self.assertFalse(result["completed"])
            self.assertEqual(
                [stage["status"] for stage in result["stages"]],
                ["selected", "would_create", "would_register", "would_login"],
            )
            handles = app.list_codex_session_handles(
                workspace_id="workspace-provider-onboard-dry-run",
            )
            endpoints = app.list_agent_endpoints(
                workspace_id="workspace-provider-onboard-dry-run",
            )
            self.assertEqual(handles["codexSessionHandles"], [])
            self.assertEqual(endpoints["count"], 0)

    def test_application_onboarding_status_tracks_missing_ready_and_inactive_alias(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cwd = root / "workspace"
            cwd.mkdir(parents=True)
            app = LocalPlatformApplication(
                LocalPlatformSettings(
                    database=str(root / "platform.sqlite3"),
                    workspace_root=str(root / "runtime-workspace"),
                    plugins_directory=str(root / "plugins"),
                    profile_path=str(root / "agent profile.json"),
                )
            )
            app.create_workspace(
                workspace_id="workspace-onboarding-status",
                display_name="Onboarding Status Workspace",
                root_path=str(cwd),
            )

            empty = app.get_agent_onboarding_status(
                workspace_id="workspace-onboarding-status",
                endpoint_alias="codex-main",
                provider="codex",
            )
            self.assertEqual(empty["schema"], "agent_onboarding_status.v1")
            self.assertFalse(empty["ready"])
            self.assertEqual(
                empty["missing"],
                ["agent", "session_handle", "endpoint_alias"],
            )
            self.assertIn(
                "agent-provider-onboard",
                empty["commands"]["providerOnboard"]["command"],
            )

            app.create_agent(
                workspace_id="workspace-onboarding-status",
                agent_id="agent-codex",
                name="Codex Agent",
                description="Codex target.",
            )
            only_agent = app.get_agent_onboarding_status(
                workspace_id="workspace-onboarding-status",
                agent_id="agent-codex",
                endpoint_alias="codex-main",
                provider="codex",
            )
            self.assertEqual(only_agent["agents"]["count"], 1)
            self.assertIn("session_handle", only_agent["missing"])
            self.assertEqual(
                only_agent["nextAction"],
                "discover_or_register_provider_session",
            )

            app.register_codex_session_handle(
                workspace_id="workspace-onboarding-status",
                agent_id="agent-codex",
                handle_id="codex-status-handle",
                codex_session_id="codex-status-session",
                cwd=str(cwd),
                created_by="user",
                reason="status fixture handle",
            )
            handle_only = app.get_agent_onboarding_status(
                workspace_id="workspace-onboarding-status",
                agent_id="agent-codex",
                endpoint_alias="codex-main",
                provider="codex",
            )
            self.assertEqual(handle_only["providerSessionHandles"]["count"], 1)
            self.assertEqual(
                handle_only["providerSessionHandles"]["handles"][0]["session"]["id"],
                "codex-status-session",
            )
            self.assertIn("endpoint_alias", handle_only["missing"])

            app.login_agent_endpoint(
                workspace_id="workspace-onboarding-status",
                agent_id="agent-codex",
                alias="Codex-Main",
                provider="codex",
                provider_handle_id="codex-status-handle",
                direction="receive_only",
                created_by="user",
                reason="status fixture endpoint",
            )
            ready = app.get_agent_onboarding_status(
                workspace_id="workspace-onboarding-status",
                agent_id="agent-codex",
                endpoint_alias="codex-main",
                provider="codex",
            )
            self.assertTrue(ready["ready"])
            self.assertEqual(ready["missing"], [])
            self.assertEqual(ready["nextAction"], "dispatch_by_alias")
            self.assertTrue(
                ready["endpointAliases"]["endpoints"][0]["readyForDispatch"]
            )
            self.assertIn("--profile", ready["commands"]["onboardingStatus"]["argv"])
            self.assertNotIn("SECRET", json.dumps(ready))

            app.create_agent(
                workspace_id="workspace-onboarding-status",
                agent_id="agent-other",
                name="Other Agent",
                description="Different target.",
            )
            mismatch = app.get_agent_onboarding_status(
                workspace_id="workspace-onboarding-status",
                agent_id="agent-other",
                endpoint_alias="codex-main",
                provider="codex",
            )
            self.assertFalse(mismatch["ready"])
            self.assertIn(
                "agent_filter_mismatch",
                mismatch["endpointAliases"]["endpoints"][0]["notReadyReasons"],
            )

            app.deactivate_codex_session_handle(
                workspace_id="workspace-onboarding-status",
                handle_id="codex-status-handle",
                deactivated_by="user",
                reason="status fixture inactive handle",
            )
            inactive = app.get_agent_onboarding_status(
                workspace_id="workspace-onboarding-status",
                agent_id="agent-codex",
                endpoint_alias="codex-main",
                provider="codex",
            )
            self.assertFalse(inactive["ready"])
            self.assertIn(
                "provider_handle_inactive",
                inactive["endpointAliases"]["endpoints"][0]["notReadyReasons"],
            )

    def test_cli_discovers_and_registers_codex_session_handle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cwd = root / "workspace"
            cwd.mkdir()
            codex_home = root / ".codex"
            sessions = codex_home / "sessions" / "2026" / "06" / "28"
            sessions.mkdir(parents=True)
            session_id = "codex-cli-session-27-3"
            (sessions / "rollout-2026-06-28T00-00-00-codex.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-06-28T00:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "session_id": session_id,
                            "cwd": str(cwd),
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            created = _run_cli(
                root,
                "workspace-create",
                "--workspace-id",
                "workspace-discovery-cli",
                "--agent-id",
                "agent-a",
                "--display-name",
                "Discovery CLI Workspace",
                "--root-path",
                str(cwd),
            )
            target = _run_cli(
                root,
                "agent-create",
                "--workspace-id",
                "workspace-discovery-cli",
                "--agent-id",
                "agent-b",
                "--name",
                "Agent B",
                "--description",
                "Codex target.",
            )
            discovered = _run_cli(
                root,
                "agent-session-discover",
                "--provider",
                "codex",
                "--codex-home",
                str(codex_home),
            )
            registered = _run_cli(
                root,
                "agent-session-handle-register-discovered",
                "--workspace-id",
                "workspace-discovery-cli",
                "--agent-id",
                "agent-b",
                "--provider",
                "codex",
                "--session-id",
                session_id,
                "--handle-id",
                "handle-discovered-codex",
                "--codex-home",
                str(codex_home),
                "--created-by",
                "user",
                "--reason",
                "register discovered Codex session",
            )
            listed = _run_cli(
                root,
                "codex-session-handle-list",
                "--workspace-id",
                "workspace-discovery-cli",
                "--agent-id",
                "agent-b",
            )

            for result in (created, target, discovered, registered, listed):
                self.assertEqual(result.returncode, 0, result.stderr)

            discovered_payload = json.loads(discovered.stdout)
            registered_payload = json.loads(registered.stdout)
            listed_payload = json.loads(listed.stdout)
            self.assertEqual(discovered_payload["count"], 1)
            self.assertEqual(
                registered_payload["discoveredAgentSession"]["sessionId"],
                session_id,
            )
            handle = registered_payload["codexSessionHandle"]
            self.assertEqual(handle["handleId"], "handle-discovered-codex")
            self.assertEqual(handle["codexSessionId"], session_id)
            self.assertEqual(
                handle["metadata"]["registeredFromDiscovery"]["sourceKind"],
                "codex_sessions_jsonl",
            )
            self.assertEqual(len(listed_payload["codexSessionHandles"]), 1)

    def test_cli_logs_endpoint_from_discovered_codex_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cwd = root / "workspace"
            cwd.mkdir()
            codex_home = root / ".codex"
            sessions = codex_home / "sessions" / "2026" / "06" / "29"
            sessions.mkdir(parents=True)
            session_id = "codex-cli-login-session-27-7"
            (sessions / "rollout-2026-06-29T00-00-00-codex.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-06-29T00:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "session_id": session_id,
                            "cwd": str(cwd),
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            created = _run_cli(
                root,
                "workspace-create",
                "--workspace-id",
                "workspace-login-discovered-cli",
                "--agent-id",
                "agent-a",
                "--display-name",
                "Login Discovered CLI Workspace",
                "--root-path",
                str(cwd),
            )
            logged_in = _run_cli(
                root,
                "agent-endpoint-login-discovered",
                "--workspace-id",
                "workspace-login-discovered-cli",
                "--agent-id",
                "agent-a",
                "--provider",
                "codex",
                "--alias",
                "Codex-Main",
                "--handle-id",
                "handle-cli-login-codex",
                "--endpoint-id",
                "endpoint-cli-login-codex",
                "--cwd",
                str(cwd),
                "--codex-home",
                str(codex_home),
                "--created-by",
                "user",
                "--reason",
                "CLI login discovered Codex session",
            )
            endpoint = _run_cli(
                root,
                "agent-endpoint-get",
                "--workspace-id",
                "workspace-login-discovered-cli",
                "--alias",
                "codex-main",
            )

            for result in (created, logged_in, endpoint):
                self.assertEqual(result.returncode, 0, result.stderr)

            login_payload = json.loads(logged_in.stdout)
            self.assertEqual(
                login_payload["schema"],
                "agent_endpoint_login_discovered.v1",
            )
            self.assertEqual(
                login_payload["selection"]["selectionMethod"],
                "unique_cwd_match",
            )
            self.assertEqual(
                login_payload["registeredSessionHandle"]["codexSessionId"],
                session_id,
            )
            self.assertEqual(login_payload["agentEndpoint"]["alias"], "codex-main")
            endpoint_payload = json.loads(endpoint.stdout)
            self.assertEqual(
                endpoint_payload["providerHandle"]["handleId"],
                "handle-cli-login-codex",
            )

    def test_cli_provider_onboard_uses_profile_and_reuses_existing_binding(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Project With Spaces"
            cwd, codex_home, _ = _write_codex_session(
                root,
                "codex-cli-provider-onboard",
            )
            profile = _write_local_runtime_profile(
                root,
                "workspace-provider-onboard-cli",
            )
            resolved_profile = str(profile.resolve(strict=False))
            created = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "workspace-create",
                "--display-name",
                "Provider Onboard CLI Workspace",
                "--root-path",
                str(cwd),
                "--agent-id",
                "workspace-agent",
            )
            first = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-provider-onboard",
                "--provider",
                "codex",
                "--agent-id",
                "agent-codex",
                "--agent-name",
                "Codex Agent",
                "--endpoint-alias",
                "Codex-Main",
                "--cwd",
                str(cwd),
                "--codex-home",
                str(codex_home),
                "--format",
                "json",
            )
            second = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-provider-onboard",
                "--provider",
                "codex",
                "--agent-id",
                "agent-codex",
                "--agent-name",
                "Codex Agent",
                "--endpoint-alias",
                "Codex-Main",
                "--cwd",
                str(cwd),
                "--codex-home",
                str(codex_home),
            )

            for result in (created, first, second):
                self.assertEqual(result.returncode, 0, result.stderr)

            first_payload = json.loads(first.stdout)
            second_payload = json.loads(second.stdout)
            self.assertEqual(first_payload["schema"], "agent_provider_onboard.v1")
            self.assertEqual(
                [stage["status"] for stage in first_payload["stages"]],
                ["selected", "created", "registered", "logged_in"],
            )
            self.assertEqual(
                [stage["status"] for stage in second_payload["stages"]],
                ["selected", "reused", "reused", "reused"],
            )
            self.assertIn("--profile", first_payload["nextStatusArgv"])
            self.assertIn(resolved_profile, first_payload["nextStatusArgv"])
            self.assertNotIn("--database", first_payload["nextStatusArgv"])
            self.assertIn("--profile", first_payload["nextDispatchExampleArgv"])
            self.assertIn(resolved_profile, first_payload["nextDispatchExampleArgv"])
            self.assertNotIn("--database", first_payload["nextDispatchExampleArgv"])
            self.assertEqual(first_payload["endpointAlias"], "codex-main")


def _write_codex_session(
    root: Path,
    session_id: str,
    *,
    cwd: Path | None = None,
    index: int = 0,
) -> tuple[Path, Path, str]:
    root.mkdir(parents=True, exist_ok=True)
    resolved_cwd = cwd or (root / "workspace")
    resolved_cwd.mkdir(parents=True, exist_ok=True)
    codex_home = root / ".codex"
    sessions = codex_home / "sessions" / "2026" / "07" / "08"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / f"rollout-2026-07-08T00-00-0{index}-codex.jsonl").write_text(
        json.dumps(
            {
                "timestamp": f"2026-07-08T00:00:0{index}Z",
                "type": "session_meta",
                "payload": {
                    "session_id": session_id,
                    "cwd": str(resolved_cwd),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return resolved_cwd, codex_home, session_id


def _write_local_runtime_profile(root: Path, workspace_id: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    profile = root / "agent os profile.json"
    profile.write_text(
        json.dumps(
            {
                "localRuntime": {
                    "workspaceId": workspace_id,
                    "databasePath": str(root / "platform.sqlite3"),
                    "workspaceRoot": str(root / "runtime workspace"),
                    "pluginsDirectory": str(root / "plugins directory"),
                }
            }
        ),
        encoding="utf-8",
    )
    return profile


def _run_cli_without_runtime_args(
    *args: str,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_SRC)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_os.local_runtime",
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


def _fake_hermes_sessions_command(root: Path, session_id: str) -> Path:
    if os.name == "nt":
        command = root / "hermes.cmd"
        command.write_text(
            f"@echo off\r\necho {session_id}  tui  active\r\n",
            encoding="utf-8",
        )
        return command
    command = root / "hermes"
    command.write_text(
        f"#!/usr/bin/env sh\nprintf '%s  tui  active\\n' '{session_id}'\n",
        encoding="utf-8",
    )
    command.chmod(0o755)
    return command


def _write_hermes_state_db(
    hermes_home: Path,
    rows: tuple[tuple[str, str, str, float], ...],
) -> None:
    hermes_home.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(hermes_home / "state.db")
    try:
        connection.execute(
            "CREATE TABLE sessions ("
            "id TEXT PRIMARY KEY, source TEXT NOT NULL, cwd TEXT, "
            "started_at REAL, ended_at REAL)"
        )
        connection.executemany(
            "INSERT INTO sessions(id, source, cwd, started_at, ended_at) "
            "VALUES (?, ?, ?, ?, NULL)",
            rows,
        )
        connection.commit()
    finally:
        connection.close()


def _fake_hermes_sessions_result(
    root: Path,
    name: str,
    *,
    output: str,
    exit_code: int,
) -> Path:
    if os.name == "nt":
        command = root / f"{name}.cmd"
        command.write_text(
            "\r\n".join(
                (
                    "@echo off",
                    f"echo {output}",
                    f"exit /b {exit_code}",
                )
            )
            + "\r\n",
            encoding="utf-8",
        )
        return command
    command = root / name
    command.write_text(
        "\n".join(
            (
                "#!/usr/bin/env sh",
                f"printf '%s\\n' {output!r}",
                f"exit {exit_code}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    command.chmod(0o755)
    return command


def _run_cli(
    root: Path,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_SRC)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_os.local_runtime",
            "--database",
            str(root / "platform.sqlite3"),
            "--workspace-root",
            str(root / "runtime-workspace"),
            "--plugins-directory",
            str(root / "plugins"),
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
