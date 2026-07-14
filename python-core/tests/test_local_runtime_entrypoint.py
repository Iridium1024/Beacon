from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4
from datetime import datetime, timedelta, timezone


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"


class LocalRuntimeEntrypointTests(unittest.TestCase):
    def test_python_module_reports_canonical_beacon_version(self) -> None:
        result = _run_cli_without_runtime_args("--version")
        expected = (PROJECT_SRC / "agent_os" / "VERSION").read_text(
            encoding="ascii"
        ).strip()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), f"beacon {expected}")

    def test_python_module_smoke_command_runs_from_empty_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = _run_cli(
                directory,
                "smoke",
                "--workspace-id",
                "workspace-cli-smoke-1",
                "--invocation-id",
                "invoke-cli-smoke-1",
                "--session-id",
                "session-cli-smoke-1",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["workspaceId"], "workspace-cli-smoke-1")
            self.assertTrue(all(payload["steps"].values()))
            self.assertEqual(
                payload["invocation"]["invocationResult"]["invocationId"],
                "invoke-cli-smoke-1",
            )
            self.assertEqual(len(payload["invocationRecords"]), 1)
            self.assertEqual(payload["fileOperationRecords"], [])
            self.assertEqual(payload["session"]["sessionId"], "session-cli-smoke-1")
            self.assertEqual(payload["session"]["status"], "completed")
            self.assertEqual(payload["session"]["lifecycle"]["recoveryState"], "closed")

    def test_smoke_creates_explicit_runtime_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fresh-runtime"
            database = root / "runtime" / "state" / "local-platform.sqlite3"
            workspace_root = root / "workspace" / "sandboxes" / "local-platform"
            plugins_directory = root / "plugins"
            result = _run_cli_without_runtime_args(
                "--database",
                str(database),
                "--workspace-root",
                str(workspace_root),
                "--plugins-directory",
                str(plugins_directory),
                "smoke",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(database.exists())
            self.assertTrue(workspace_root.is_dir())
            self.assertTrue(plugins_directory.is_dir())

    def test_agent_help_topic_runs_without_runtime_settings(self) -> None:
        pretty = _run_cli_without_runtime_args(
            "agent-help",
            "--topic",
            "status",
            extra_env={"AGENT_OS_LOCAL_RUNTIME_PROFILE": "Z:/missing/profile.json"},
        )
        json_result = _run_cli_without_runtime_args(
            "agent-help",
            "--topic",
            "dispatch",
            "--format",
            "json",
        )

        self.assertEqual(pretty.returncode, 0, pretty.stderr)
        self.assertEqual(json_result.returncode, 0, json_result.stderr)
        self.assertIn("agent-onboarding-status", pretty.stdout)
        self.assertIn("agent-dispatch-status", pretty.stdout)
        self.assertNotIn("SECRET", pretty.stdout)
        payload = json.loads(json_result.stdout)
        self.assertEqual(payload["schema"], "agent_help.v1")
        self.assertEqual(payload["topic"], "dispatch")
        self.assertIn("agent-dispatch-send", json.dumps(payload))

    def test_onboarding_status_cli_uses_profile_workspace_default_and_pretty(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Project With Spaces"
            root.mkdir(parents=True)
            profile = _write_local_runtime_profile(root, "workspace-onboarding-cli")
            created = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "workspace-create",
                "--workspace-id",
                "workspace-onboarding-cli",
                "--display-name",
                "Onboarding CLI Workspace",
                "--root-path",
                str(root),
            )
            status = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-onboarding-status",
                "--format",
                "pretty",
            )

            self.assertEqual(created.returncode, 0, created.stderr)
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn("Beacon onboarding status", status.stdout)
            self.assertIn("workspace-onboarding-cli", status.stdout)
            self.assertIn(str(profile.resolve()), status.stdout)
            self.assertIn("ready: false", status.stdout)
            self.assertIn("nextAction: create_or_onboard_agent", status.stdout)
            self.assertIn("agent-provider-onboard", status.stdout)
            self.assertNotIn("SECRET", status.stdout)

    def test_provider_session_profile_can_join_and_leave_multiple_workspaces(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Project With Spaces"
            session_cwd = root / "provider session cwd"
            session_cwd.mkdir(parents=True)
            registry = root / ".beacon" / "provider-session-registry.json"

            registered = _run_cli_without_runtime_args(
                "--provider-session-registry",
                str(registry),
                "provider-session-profile-register",
                "--provider",
                "codex",
                "--session-id",
                "codex-provider-session-shared",
                "--profile-alias",
                "codex-main",
                "--cwd",
                str(session_cwd),
                "--created-by",
                "tester",
                "--reason",
                "User approved local provider session reuse.",
            )
            reused = _run_cli_without_runtime_args(
                "--provider-session-registry",
                str(registry),
                "provider-session-profile-register",
                "--provider",
                "codex",
                "--session-id",
                "codex-provider-session-shared",
                "--profile-alias",
                "codex-main",
                "--cwd",
                str(session_cwd),
                "--created-by",
                "tester",
                "--reason",
                "Repeat registration should reuse the profile.",
            )
            listed = _run_cli_without_runtime_args(
                "--provider-session-registry",
                str(registry),
                "provider-session-profile-list",
            )
            sensitive = _run_cli_without_runtime_args(
                "--provider-session-registry",
                str(registry),
                "provider-session-profile-register",
                "--provider",
                "codex",
                "--session-id",
                "codex-provider-session-sensitive",
                "--profile-alias",
                "codex-sensitive",
                "--cwd",
                str(session_cwd),
                "--created-by",
                "tester",
                "--reason",
                "Sensitive metadata should be rejected.",
                "--metadata-json",
                json.dumps({"apiToken": "SECRET"}),
            )
            self.assertEqual(registered.returncode, 0, registered.stderr)
            self.assertEqual(reused.returncode, 0, reused.stderr)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertEqual(sensitive.returncode, 1)
            self.assertIn("credential", sensitive.stderr)
            profile_payload = json.loads(registered.stdout)
            profile_id = profile_payload["providerSessionProfile"]["profileId"]
            self.assertTrue(profile_payload["created"])
            self.assertEqual(
                profile_payload["registryPath"],
                str(registry.resolve(strict=False)),
            )
            self.assertEqual(profile_payload["registryPathSource"], "explicit_cli")
            self.assertEqual(
                profile_payload["registryPathSourceKey"],
                "--provider-session-registry",
            )
            self.assertTrue(profile_payload["registryPathStatus"]["exists"])
            self.assertTrue(profile_payload["registryPathStatus"]["readable"])
            self.assertFalse(profile_payload["providerSessionProfile"]["credentialStored"])
            self.assertFalse(
                profile_payload["boundaries"]["providerAccountLogin"]
            )
            self.assertTrue(json.loads(reused.stdout)["reused"])
            self.assertEqual(
                json.loads(listed.stdout)["registryPathSource"],
                "explicit_cli",
            )
            fetched = _run_cli_without_runtime_args(
                "--provider-session-registry",
                str(registry),
                "provider-session-profile-get",
                "--profile-id",
                profile_id,
            )
            self.assertEqual(fetched.returncode, 0, fetched.stderr)
            self.assertEqual(
                json.loads(fetched.stdout)["registryPathSource"],
                "explicit_cli",
            )

            workspace_profiles: dict[str, Path] = {}
            for workspace_id in ("workspace-profile-a", "workspace-profile-b"):
                initialized = _run_cli_without_runtime_args(
                    "--provider-session-registry",
                    str(registry),
                    "agent-workspace-init",
                    "--project-root",
                    str(root),
                    "--workspace-id",
                    workspace_id,
                    "--display-name",
                    workspace_id,
                )
                self.assertEqual(initialized.returncode, 0, initialized.stderr)
                initialized_payload = json.loads(initialized.stdout)
                profile_path = Path(initialized_payload["profile"]["path"])
                workspace_profiles[workspace_id] = profile_path
                initialized_profile = json.loads(
                    profile_path.read_text(encoding="utf-8")
                )
                self.assertEqual(
                    initialized_profile["localRuntime"]["providerSessionRegistry"],
                    str(registry.resolve(strict=False)),
                )
                self.assertEqual(
                    initialized_payload["registryPath"],
                    str(registry.resolve(strict=False)),
                )
                self.assertEqual(
                    initialized_payload["registryPathSource"],
                    "explicit_cli",
                )

            join_payloads = []
            for workspace_id, profile_path in workspace_profiles.items():
                joined = _run_cli_without_runtime_args(
                    "--profile",
                    str(profile_path),
                    "provider-session-workspace-join",
                    "--session-profile-id",
                    profile_id,
                    "--agent-id",
                    "codex-agent",
                    "--agent-name",
                    "Codex Agent",
                    "--endpoint-alias",
                    "codex-local",
                    "--created-by",
                    "tester",
                    "--reason",
                    f"Join {workspace_id}.",
                )
                self.assertEqual(joined.returncode, 0, joined.stderr)
                join_payload = json.loads(joined.stdout)
                join_payloads.append(join_payload)
                self.assertTrue(join_payload["completed"])
                self.assertEqual(join_payload["workspaceId"], workspace_id)
                self.assertEqual(
                    join_payload["registryPath"],
                    str(registry.resolve(strict=False)),
                )
                self.assertEqual(join_payload["registryPathSource"], "profile")
                self.assertEqual(
                    join_payload["activationPolicy"]["policy"],
                    "manual_only_no_cross_workspace_lease",
                )
                self.assertFalse(
                    join_payload["activationPolicy"][
                        "automaticWorkerActivationAllowed"
                    ]
                )
                self.assertFalse(
                    join_payload["boundaries"]["globalDispatchAliasCreated"]
                )

            repeated_join = _run_cli_without_runtime_args(
                "--profile",
                str(workspace_profiles["workspace-profile-a"]),
                "provider-session-workspace-join",
                "--session-profile-id",
                profile_id,
                "--agent-id",
                "codex-agent",
                "--agent-name",
                "Codex Agent",
                "--endpoint-alias",
                "codex-local",
                "--created-by",
                "tester",
                "--reason",
                "Repeat join should reuse membership.",
            )
            memberships = _run_cli_without_runtime_args(
                "--provider-session-registry",
                str(registry),
                "provider-session-membership-list",
                "--session-profile-id",
                profile_id,
            )
            status_a = _run_cli_without_runtime_args(
                "--profile",
                str(workspace_profiles["workspace-profile-a"]),
                "agent-onboarding-status",
                "--endpoint-alias",
                "codex-local",
            )

            self.assertEqual(repeated_join.returncode, 0, repeated_join.stderr)
            self.assertEqual(
                json.loads(repeated_join.stdout)["membershipStage"]["status"],
                "reused",
            )
            self.assertEqual(memberships.returncode, 0, memberships.stderr)
            membership_payload = json.loads(memberships.stdout)
            self.assertEqual(membership_payload["count"], 2)
            self.assertEqual(
                membership_payload["registryPathSource"],
                "explicit_cli",
            )
            self.assertEqual(
                sorted(
                    membership["workspaceId"]
                    for membership in membership_payload["memberships"]
                ),
                ["workspace-profile-a", "workspace-profile-b"],
            )
            self.assertEqual(status_a.returncode, 0, status_a.stderr)
            status_payload = json.loads(status_a.stdout)
            self.assertEqual(
                status_payload["registryPath"],
                str(registry.resolve(strict=False)),
            )
            self.assertEqual(status_payload["registryPathSource"], "profile")
            self.assertEqual(status_payload["providerSessionProfiles"]["count"], 1)
            self.assertEqual(
                status_payload["providerSessionProfiles"]["memberships"][0][
                    "profileId"
                ],
                profile_id,
            )

            source_agent = _run_cli_without_runtime_args(
                "--profile",
                str(workspace_profiles["workspace-profile-a"]),
                "agent-create",
                "--agent-id",
                "source-agent",
                "--name",
                "Source Agent",
                "--description",
                "Source endpoint fixture.",
            )
            source_handle = _run_cli_without_runtime_args(
                "--profile",
                str(workspace_profiles["workspace-profile-a"]),
                "codex-session-handle-register",
                "--agent-id",
                "source-agent",
                "--codex-session-id",
                "codex-source-session",
                "--cwd",
                str(session_cwd),
                "--created-by",
                "tester",
                "--reason",
                "Source endpoint fixture.",
            )
            self.assertEqual(source_agent.returncode, 0, source_agent.stderr)
            self.assertEqual(source_handle.returncode, 0, source_handle.stderr)
            source_endpoint = _run_cli_without_runtime_args(
                "--profile",
                str(workspace_profiles["workspace-profile-a"]),
                "agent-endpoint-login",
                "--agent-id",
                "source-agent",
                "--alias",
                "codex-source",
                "--provider",
                "codex",
                "--provider-handle-id",
                json.loads(source_handle.stdout)["codexSessionHandle"]["handleId"],
                "--direction",
                "send_only",
                "--created-by",
                "tester",
                "--reason",
                "Source endpoint fixture.",
            )
            dry_run_send = _run_cli_without_runtime_args(
                "--profile",
                str(workspace_profiles["workspace-profile-a"]),
                "agent-dispatch-send",
                "--from",
                "codex-source",
                "--to",
                "codex-local",
                "--message",
                "Preview provider-session profile dispatch.",
                "--delivery-mode",
                "worker_dry_run",
            )
            self.assertEqual(source_endpoint.returncode, 0, source_endpoint.stderr)
            self.assertEqual(dry_run_send.returncode, 0, dry_run_send.stderr)
            candidate = json.loads(dry_run_send.stdout)["workerRun"]["candidates"][0]
            self.assertTrue(candidate["runtimeBlocked"])
            self.assertEqual(
                candidate["runtimeBlockReason"],
                "provider_session_profile_manual_only",
            )
            self.assertFalse(
                candidate["providerSessionProfileActivation"][
                    "automaticWorkerActivationAllowed"
                ]
            )

            conflict = _run_cli_without_runtime_args(
                "--provider-session-registry",
                str(registry),
                "provider-session-profile-register",
                "--provider",
                "codex",
                "--session-id",
                "codex-provider-session-other",
                "--profile-alias",
                "codex-other",
                "--cwd",
                str(session_cwd),
                "--created-by",
                "tester",
                "--reason",
                "Second local profile.",
            )
            conflict_profile_id = json.loads(conflict.stdout)[
                "providerSessionProfile"
            ]["profileId"]
            conflict_join = _run_cli_without_runtime_args(
                "--profile",
                str(workspace_profiles["workspace-profile-a"]),
                "provider-session-workspace-join",
                "--session-profile-id",
                conflict_profile_id,
                "--agent-id",
                "other-agent",
                "--agent-name",
                "Other Agent",
                "--endpoint-alias",
                "codex-local",
                "--created-by",
                "tester",
                "--reason",
                "Endpoint alias conflict should stay workspace-local.",
            )
            self.assertEqual(conflict.returncode, 0, conflict.stderr)
            self.assertEqual(conflict_join.returncode, 1)
            self.assertEqual(
                json.loads(conflict_join.stdout)["failedStage"],
                "endpointLogin",
            )
            self.assertTrue(join_payloads[1]["completed"])

            leave_a = _run_cli_without_runtime_args(
                "--profile",
                str(workspace_profiles["workspace-profile-a"]),
                "provider-session-workspace-leave",
                "--session-profile-id",
                profile_id,
                "--reason",
                "Leave workspace A.",
            )
            after_leave = _run_cli_without_runtime_args(
                "--provider-session-registry",
                str(registry),
                "provider-session-membership-list",
                "--session-profile-id",
                profile_id,
                "--include-inactive",
            )
            deactivate_preview = _run_cli_without_runtime_args(
                "--provider-session-registry",
                str(registry),
                "provider-session-profile-deactivate",
                "--profile-id",
                profile_id,
                "--deactivated-by",
                "tester",
                "--reason",
                "Preview profile deactivation.",
            )
            deactivate_confirmed = _run_cli_without_runtime_args(
                "--provider-session-registry",
                str(registry),
                "provider-session-profile-deactivate",
                "--profile-id",
                profile_id,
                "--deactivated-by",
                "tester",
                "--reason",
                "Confirm profile deactivation.",
                "--confirm-deactivate-profile",
            )

            self.assertEqual(leave_a.returncode, 0, leave_a.stderr)
            leave_payload = json.loads(leave_a.stdout)
            self.assertTrue(leave_payload["left"])
            self.assertEqual(leave_payload["registryPathSource"], "profile")
            self.assertTrue(leave_payload["endpointResult"]["deactivated"])
            self.assertFalse(
                leave_payload["boundaries"]["otherWorkspaceMembershipsAffected"]
            )
            self.assertEqual(after_leave.returncode, 0, after_leave.stderr)
            after_leave_payload = json.loads(after_leave.stdout)
            self.assertEqual(
                len(
                    [
                        item
                        for item in after_leave_payload["memberships"]
                        if item["state"] == "active"
                    ]
                ),
                1,
            )
            self.assertEqual(
                len(
                    [
                        item
                        for item in after_leave_payload["memberships"]
                        if item["state"] == "left"
                    ]
                ),
                1,
            )
            self.assertEqual(deactivate_preview.returncode, 1)
            preview_payload = json.loads(deactivate_preview.stdout)
            self.assertTrue(preview_payload["requiresConfirmation"])
            self.assertEqual(preview_payload["registryPathSource"], "explicit_cli")
            self.assertEqual(preview_payload["confirmFlag"], "--confirm-deactivate-profile")
            self.assertEqual(len(preview_payload["affectedMemberships"]), 1)
            self.assertEqual(deactivate_confirmed.returncode, 0, deactivate_confirmed.stderr)
            deactivate_payload = json.loads(deactivate_confirmed.stdout)
            self.assertTrue(deactivate_payload["ok"])
            self.assertEqual(
                deactivate_payload["registryPathSource"],
                "explicit_cli",
            )

    def test_provider_session_registry_not_found_reports_resolution_and_fix(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "wrong-registry.json"
            result = _run_cli_without_runtime_args(
                "--provider-session-registry",
                str(registry),
                "provider-session-profile-get",
                "--profile-id",
                "provider-session-profile-missing",
            )
            alias_result = _run_cli_without_runtime_args(
                "--provider-session-registry",
                str(registry),
                "provider-session-profile-get",
                "--profile-alias",
                "missing-alias",
            )

            self.assertEqual(result.returncode, 1)
            self.assertEqual(alias_result.returncode, 1)
            resolved = str(registry.resolve(strict=False))
            error_message = json.loads(result.stderr)["error"]["message"]
            self.assertIn("provider session profile not found", error_message)
            self.assertIn(f"Resolved registry path: {resolved}", error_message)
            self.assertIn("source: explicit_cli", error_message)
            self.assertIn("--provider-session-registry", error_message)
            alias_error_message = json.loads(alias_result.stderr)["error"]["message"]
            self.assertIn("profile alias missing-alias", alias_error_message)
            self.assertIn(f"Resolved registry path: {resolved}", alias_error_message)

    def test_hermes_profile_join_preserves_runtime_home_and_session_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session_cwd = root / "session-cwd"
            hermes_home = root / "hermes-home"
            session_cwd.mkdir()
            hermes_home.mkdir()
            registry = root / "provider-session-registry.json"
            workspace_profile = root / "workspace-profile.json"

            registered = _run_cli_without_runtime_args(
                "--provider-session-registry",
                str(registry),
                "provider-session-profile-register",
                "--provider",
                "hermes",
                "--session-id",
                "20260710_120000_profile",
                "--profile-alias",
                "hermes-main",
                "--cwd",
                str(session_cwd),
                "--hermes-home",
                str(hermes_home),
                "--hermes-session-source",
                "cli",
                "--created-by",
                "tester",
                "--reason",
                "Preserve Hermes instance identity.",
            )
            initialized = _run_cli_without_runtime_args(
                "--provider-session-registry",
                str(registry),
                "agent-workspace-init",
                "--project-root",
                str(root),
                "--workspace-id",
                "workspace-hermes-profile",
                "--display-name",
                "Hermes Profile Workspace",
                "--profile-path",
                str(workspace_profile),
            )
            self.assertEqual(registered.returncode, 0, registered.stderr)
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            profile_id = json.loads(registered.stdout)["providerSessionProfile"][
                "profileId"
            ]

            joined = _run_cli_without_runtime_args(
                "--profile",
                str(workspace_profile),
                "provider-session-workspace-join",
                "--session-profile-id",
                profile_id,
                "--agent-id",
                "hermes-agent",
                "--agent-name",
                "Hermes Agent",
                "--endpoint-alias",
                "hermes-local",
                "--created-by",
                "tester",
                "--reason",
                "Join Hermes profile.",
            )

            self.assertEqual(joined.returncode, 0, joined.stderr)
            handle = json.loads(joined.stdout)["providerHandle"]
            identity = handle["metadata"]["hermesSessionIdentity"]
            self.assertEqual(identity["providerSessionId"], "20260710_120000_profile")
            self.assertEqual(identity["runtimeHome"], str(hermes_home.resolve()))
            self.assertEqual(identity["sessionSource"], "cli")
            self.assertEqual(identity["discoverySource"], "explicit_profile_registration")

    def test_python_module_command_level_flow_reuses_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            init = _run_cli(directory, "init")
            created = _run_cli(
                directory,
                "workspace-create",
                "--workspace-id",
                "workspace-cli-1",
                "--display-name",
                "CLI Workspace",
            )
            listed = _run_cli(directory, "workspace-list")
            opened = _run_cli(
                directory,
                "workspace-open",
                "--workspace-id",
                "workspace-cli-1",
            )
            invoked = _run_cli(
                directory,
                "invoke",
                "--workspace-id",
                "workspace-cli-1",
                "--instruction",
                "Run CLI deterministic invocation.",
                "--invocation-id",
                "invoke-cli-1",
                "--session-id",
                "session-cli-1",
                "--correlation-id",
                "correlation-cli-1",
            )
            context = _run_cli(
                directory,
                "context-get",
                "--workspace-id",
                "workspace-cli-1",
            )
            invocations = _run_cli(
                directory,
                "records-invocations",
                "--workspace-id",
                "workspace-cli-1",
            )
            file_operations = _run_cli(
                directory,
                "records-file-operations",
                "--workspace-id",
                "workspace-cli-1",
            )
            timeline = _run_cli(
                directory,
                "session-timeline",
                "--workspace-id",
                "workspace-cli-1",
                "--session-id",
                "session-cli-1",
            )

            for result in (
                init,
                created,
                listed,
                opened,
                invoked,
                context,
                invocations,
                file_operations,
                timeline,
            ):
                self.assertEqual(result.returncode, 0, result.stderr)

            self.assertTrue(json.loads(init.stdout)["initialized"])
            self.assertTrue(json.loads(created.stdout)["created"])
            self.assertEqual(
                json.loads(listed.stdout)["workspaces"][0]["workspaceId"],
                "workspace-cli-1",
            )
            self.assertEqual(
                json.loads(opened.stdout)["workspace"]["workspaceId"],
                "workspace-cli-1",
            )
            self.assertEqual(
                json.loads(invoked.stdout)["invocationResult"]["invocationId"],
                "invoke-cli-1",
            )
            self.assertEqual(json.loads(context.stdout)["context"]["updateCount"], 1)
            self.assertEqual(
                json.loads(invocations.stdout)["invocations"][0]["invocationId"],
                "invoke-cli-1",
            )
            self.assertEqual(
                json.loads(invocations.stdout)["invocations"][0]["correlationId"],
                "correlation-cli-1",
            )
            self.assertEqual(json.loads(file_operations.stdout)["fileOperations"], [])
            timeline_payload = json.loads(timeline.stdout)
            self.assertGreaterEqual(
                timeline_payload["session"]["eventCount"],
                1,
            )
            self.assertEqual(timeline_payload["session"]["status"], "completed")
            self.assertTrue(
                timeline_payload["session"]["lifecycle"]["hasExplicitLifecycleEvents"]
            )
            self.assertEqual(
                timeline_payload["session"]["lifecycle"]["recoveryState"],
                "closed",
            )

    def test_python_module_accepts_runtime_paths_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = _run_cli_without_runtime_args(
                "workspace-create",
                "--workspace-id",
                "workspace-env-1",
                "--display-name",
                "Env Workspace",
                extra_env={
                    "AGENT_OS_DATABASE": str(root / "platform.sqlite3"),
                    "AGENT_OS_WORKSPACE_ROOT": str(root / "workspace"),
                    "AGENT_OS_PLUGINS_DIRECTORY": str(root / "plugins"),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["created"])
            self.assertEqual(
                payload["workspace"]["workspace"]["workspaceId"],
                "workspace-env-1",
            )

    def test_python_module_workspace_init_creates_profile_for_space_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory) / "Project With Spaces"
            result = _run_cli_without_runtime_args(
                "agent-workspace-init",
                "--project-root",
                str(project_root),
                "--workspace-id",
                "workspace-profile-init-1",
                "--display-name",
                "Profile Init Workspace",
                "--pretty",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["schema"], "agent_workspace_init.v1")
            self.assertTrue(payload["initialized"])
            self.assertTrue(payload["workspaceCreated"])
            self.assertEqual(payload["workspaceId"], "workspace-profile-init-1")
            paths = payload["paths"]["localAbsolutePaths"]
            relative_paths = payload["paths"]["projectRelativePaths"]
            self.assertEqual(
                relative_paths["databasePath"],
                ".beacon/workspaces/workspace-profile-init-1/platform.sqlite3",
            )
            self.assertEqual(
                relative_paths["profilePath"],
                ".beacon/profiles/workspace-profile-init-1.local-runtime.json",
            )
            for key in (
                "workspaceBase",
                "workspaceRoot",
                "pluginsDirectory",
                "wakeTicketsDirectory",
                "dispatchStateDirectory",
                "outputDirectory",
            ):
                self.assertTrue(Path(paths[key]).is_dir(), key)
            self.assertTrue(Path(paths["databasePath"]).is_file())
            profile_path = Path(payload["profile"]["path"])
            profile_payload = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assertEqual(
                profile_payload["localRuntime"]["workspaceId"],
                "workspace-profile-init-1",
            )
            self.assertEqual(
                profile_payload["localRuntime"]["databasePath"],
                paths["databasePath"],
            )
            self.assertTrue(payload["paths"]["doNotCommit"])
            self.assertNotEqual(
                Path(paths["baseDirectory"]).resolve(strict=False),
                PROJECT_SRC.parents[1].resolve(strict=False),
            )

            opened = _run_cli_without_runtime_args(
                "--profile",
                str(profile_path),
                "workspace-open",
            )
            context = _run_cli_without_runtime_args(
                "context-get",
                extra_env={
                    "AGENT_OS_LOCAL_RUNTIME_PROFILE": str(profile_path),
                },
            )

            self.assertEqual(opened.returncode, 0, opened.stderr)
            self.assertEqual(context.returncode, 0, context.stderr)
            self.assertEqual(
                json.loads(opened.stdout)["workspace"]["workspaceId"],
                "workspace-profile-init-1",
            )
            self.assertEqual(
                json.loads(context.stdout)["context"]["workspaceId"],
                "workspace-profile-init-1",
            )

    def test_python_module_workspace_init_isolates_workspace_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory) / "multi-project"
            payloads = []
            for workspace_id in ("workspace-alpha", "workspace-beta"):
                result = _run_cli_without_runtime_args(
                    "agent-workspace-init",
                    "--project-root",
                    str(project_root),
                    "--workspace-id",
                    workspace_id,
                    "--display-name",
                    f"{workspace_id} display",
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                payloads.append(json.loads(result.stdout))

            first_paths = payloads[0]["paths"]["localAbsolutePaths"]
            second_paths = payloads[1]["paths"]["localAbsolutePaths"]
            for key in (
                "databasePath",
                "workspaceRoot",
                "pluginsDirectory",
                "wakeTicketsDirectory",
                "dispatchStateDirectory",
                "outputDirectory",
            ):
                self.assertNotEqual(first_paths[key], second_paths[key], key)
                self.assertTrue(Path(first_paths[key]).exists(), key)
                self.assertTrue(Path(second_paths[key]).exists(), key)
            self.assertEqual(
                payloads[0]["paths"]["projectRelativePaths"]["databasePath"],
                ".beacon/workspaces/workspace-alpha/platform.sqlite3",
            )
            self.assertEqual(
                payloads[1]["paths"]["projectRelativePaths"]["databasePath"],
                ".beacon/workspaces/workspace-beta/platform.sqlite3",
            )

    def test_python_module_accepts_workspace_id_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {
                "AGENT_OS_DATABASE": str(root / "platform.sqlite3"),
                "AGENT_OS_WORKSPACE_ROOT": str(root / "workspace"),
                "AGENT_OS_PLUGINS_DIRECTORY": str(root / "plugins"),
                "AGENT_OS_WORKSPACE_ID": "workspace-env-default",
            }
            created = _run_cli_without_runtime_args(
                "workspace-create",
                "--display-name",
                "Env Default Workspace",
                extra_env=env,
            )
            opened = _run_cli_without_runtime_args(
                "workspace-open",
                extra_env=env,
            )

            self.assertEqual(created.returncode, 0, created.stderr)
            self.assertEqual(opened.returncode, 0, opened.stderr)
            self.assertEqual(
                json.loads(created.stdout)["workspace"]["workspace"]["workspaceId"],
                "workspace-env-default",
            )
            self.assertEqual(
                json.loads(opened.stdout)["workspace"]["workspaceId"],
                "workspace-env-default",
            )

    def test_python_module_profile_drives_dispatch_cli_flow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Project With Spaces"
            profile = _write_local_runtime_profile(root, "workspace-dispatch-cli")
            resolved_profile = str(profile.resolve(strict=False))

            created = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "workspace-create",
                "--workspace-id",
                "workspace-dispatch-cli",
                "--display-name",
                "Dispatch CLI Workspace",
                "--agent-id",
                "agent-a",
            )
            agent_b = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-create",
                "--workspace-id",
                "workspace-dispatch-cli",
                "--agent-id",
                "agent-b",
                "--name",
                "Agent B",
                "--description",
                "Target agent.",
            )
            dispatched = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-dispatch-create",
                "--workspace-id",
                "workspace-dispatch-cli",
                "--dispatch-id",
                "dispatch-cli-1",
                "--exchange-request-id",
                "req-dispatch-cli-1",
                "--source-agent-id",
                "agent-a",
                "--target-agent-id",
                "agent-b",
                "--target-handle-id",
                "handle-agent-b",
                "--target-provider",
                "codex-cli",
                "--request-kind",
                "review",
                "--request-summary",
                "Review via queued dispatch.",
            )
            status = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-dispatch-status",
                "--workspace-id",
                "workspace-dispatch-cli",
                "--dispatch-id",
                "dispatch-cli-1",
            )
            worker = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-dispatch-worker-run-once",
                "--workspace-id",
                "workspace-dispatch-cli",
                "--dispatch-id",
                "dispatch-cli-1",
                "--dry-run",
            )
            source_handle = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "codex-session-handle-register",
                "--workspace-id",
                "workspace-dispatch-cli",
                "--agent-id",
                "agent-a",
                "--handle-id",
                "codex-source-handle-cli",
                "--codex-session-id",
                "codex-source-session-cli",
                "--cwd",
                str(root),
                "--created-by",
                "user",
                "--reason",
                "CLI dispatch source endpoint fixture",
            )
            target_handle = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "codex-session-handle-register",
                "--workspace-id",
                "workspace-dispatch-cli",
                "--agent-id",
                "agent-b",
                "--handle-id",
                "codex-target-handle-cli",
                "--codex-session-id",
                "codex-target-session-cli",
                "--cwd",
                str(root),
                "--created-by",
                "user",
                "--reason",
                "CLI dispatch target endpoint fixture",
            )
            source_endpoint = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-endpoint-login",
                "--workspace-id",
                "workspace-dispatch-cli",
                "--agent-id",
                "agent-a",
                "--alias",
                "codex-source",
                "--provider",
                "codex",
                "--provider-handle-id",
                "codex-source-handle-cli",
                "--direction",
                "send_only",
                "--default-reply-policy",
                "source_handle_required",
                "--created-by",
                "user",
                "--reason",
                "CLI dispatch source endpoint login",
            )
            target_endpoint = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-endpoint-login",
                "--workspace-id",
                "workspace-dispatch-cli",
                "--agent-id",
                "agent-b",
                "--alias",
                "codex-target",
                "--provider",
                "codex",
                "--provider-handle-id",
                "codex-target-handle-cli",
                "--direction",
                "receive_only",
                "--created-by",
                "user",
                "--reason",
                "CLI dispatch target endpoint login",
            )
            before_preview_dispatches = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-dispatch-list",
                "--workspace-id",
                "workspace-dispatch-cli",
            )
            before_preview_requests = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-exchange-request-list",
                "--workspace-id",
                "workspace-dispatch-cli",
            )
            route_preview = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-dispatch-send",
                "--workspace-id",
                "workspace-dispatch-cli",
                "--dispatch-id",
                "dispatch-route-preview-cli",
                "--exchange-request-id",
                "req-route-preview-cli",
                "--as",
                "codex-source",
                "--to",
                "codex-target",
                "--message",
                "Preview this route without writes.",
                "--dry-run",
            )
            after_preview_dispatches = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-dispatch-list",
                "--workspace-id",
                "workspace-dispatch-cli",
            )
            after_preview_requests = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-exchange-request-list",
                "--workspace-id",
                "workspace-dispatch-cli",
            )
            conflicting_identity = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-dispatch-send",
                "--workspace-id",
                "workspace-dispatch-cli",
                "--as",
                "codex-source",
                "--from",
                "codex-target",
                "--to",
                "codex-target",
                "--message",
                "This conflicting source identity must fail.",
                "--dry-run",
            )
            matching_identity = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-dispatch-send",
                "--workspace-id",
                "workspace-dispatch-cli",
                "--as",
                "codex-source",
                "--from",
                "codex-source",
                "--to",
                "codex-target",
                "--message",
                "Matching source identity aliases are accepted.",
                "--dry-run",
            )
            identity = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-endpoint-identity",
                "--workspace-id",
                "workspace-dispatch-cli",
                "--alias",
                "codex-source",
            )
            sent = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-dispatch-send",
                "--workspace-id",
                "workspace-dispatch-cli",
                "--dispatch-id",
                "dispatch-send-cli-1",
                "--exchange-request-id",
                "req-dispatch-send-cli-1",
                "--from",
                "codex-source",
                "--to",
                "codex-target",
                "--message",
                "Review via high-level dispatch send.",
                "--detail-ref",
                "docs/dispatch-handoff.md",
                "--metadata",
                "priority=high",
                "--delivery-mode",
                "worker_dry_run",
            )
            target_endpoint_status = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-endpoint-status",
                "--workspace-id",
                "workspace-dispatch-cli",
                "--alias",
                "codex-target",
            )
            compact_dispatch_status = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-dispatch-status",
                "--workspace-id",
                "workspace-dispatch-cli",
                "--dispatch-id",
                "dispatch-send-cli-1",
                "--format",
                "compact",
            )
            compact_request_status = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-exchange-request-get",
                "--workspace-id",
                "workspace-dispatch-cli",
                "--exchange-request-id",
                "req-dispatch-send-cli-1",
                "--format",
                "compact",
            )
            failed_dispatch = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-dispatch-create",
                "--workspace-id",
                "workspace-dispatch-cli",
                "--dispatch-id",
                "dispatch-compact-failure-cli",
                "--exchange-request-id",
                "req-compact-failure-cli",
                "--source-agent-id",
                "agent-a",
                "--target-agent-id",
                "agent-b",
                "--request-kind",
                "review",
                "--request-summary",
                "Compact status should expose precheck failure.",
            )
            failed_worker = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-dispatch-worker-run-once",
                "--workspace-id",
                "workspace-dispatch-cli",
                "--dispatch-id",
                "dispatch-compact-failure-cli",
                "--execute",
            )
            compact_failure_status = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-dispatch-status",
                "--workspace-id",
                "workspace-dispatch-cli",
                "--dispatch-id",
                "dispatch-compact-failure-cli",
                "--format",
                "compact",
            )

            for result in (
                created,
                agent_b,
                dispatched,
                status,
                worker,
                source_handle,
                target_handle,
                source_endpoint,
                target_endpoint,
                before_preview_dispatches,
                before_preview_requests,
                route_preview,
                after_preview_dispatches,
                after_preview_requests,
                matching_identity,
                identity,
                sent,
                target_endpoint_status,
                compact_dispatch_status,
                compact_request_status,
                failed_dispatch,
                failed_worker,
                compact_failure_status,
            ):
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(conflicting_identity.returncode, 1)
            self.assertIn("--as and --from", conflicting_identity.stderr)
            self.assertEqual(
                json.loads(matching_identity.stdout)["actingIdentity"]["inputSource"],
                "as_and_from",
            )

            preview_payload = json.loads(route_preview.stdout)
            self.assertTrue(preview_payload["dryRun"])
            self.assertFalse(preview_payload["queuedDispatchCreated"])
            self.assertTrue(preview_payload["routeSummary"]["previewOnly"])
            self.assertEqual(
                preview_payload["routeSummary"]["workspaceId"],
                "workspace-dispatch-cli",
            )
            self.assertEqual(
                preview_payload["routeSummary"]["source"],
                {
                    "alias": "codex-source",
                    "agentId": "agent-a",
                    "providerHandleId": "codex-source-handle-cli",
                    "provider": "codex",
                },
            )
            self.assertEqual(
                preview_payload["routeSummary"]["target"]["alias"],
                "codex-target",
            )
            self.assertEqual(
                preview_payload["routeSummary"]["replyPolicy"],
                "source_handle_required",
            )
            self.assertEqual(
                preview_payload["routeSummary"]["contactDecision"]["decision"],
                "allowed",
            )
            self.assertEqual(preview_payload["actingIdentity"]["inputSource"], "as")
            self.assertFalse(preview_payload["actingIdentity"]["callerAuthenticated"])
            self.assertEqual(
                json.loads(before_preview_dispatches.stdout)["agentDispatches"],
                json.loads(after_preview_dispatches.stdout)["agentDispatches"],
            )
            self.assertEqual(
                json.loads(before_preview_requests.stdout)["agentExchangeRequests"],
                json.loads(after_preview_requests.stdout)["agentExchangeRequests"],
            )
            identity_payload = json.loads(identity.stdout)
            self.assertEqual(identity_payload["schema"], "agent_endpoint_identity_compact.v1")
            self.assertEqual(identity_payload["alias"], "codex-source")
            self.assertEqual(identity_payload["agentId"], "agent-a")
            self.assertFalse(identity_payload["identityBoundary"]["callerAuthenticated"])
            self.assertFalse(
                identity_payload["identityBoundary"]["automaticallyDetectedCurrentSession"]
            )

            dispatch_payload = json.loads(dispatched.stdout)
            self.assertTrue(dispatch_payload["queued"])
            self.assertFalse(dispatch_payload["dispatcherRunning"])
            self.assertEqual(
                dispatch_payload["agentDispatch"]["status"],
                "queued",
            )
            status_payload = json.loads(status.stdout)
            self.assertEqual(
                status_payload["agentExchangeRequest"]["exchangeRequestId"],
                "req-dispatch-cli-1",
            )
            self.assertFalse(status_payload["wakeStatus"]["ticketDeliveryOccurred"])
            worker_payload = json.loads(worker.stdout)
            self.assertTrue(worker_payload["dryRun"])
            self.assertFalse(worker_payload["workerStarted"])
            self.assertEqual(worker_payload["processedCount"], 0)
            self.assertEqual(worker_payload["candidateCount"], 1)
            self.assertEqual(
                worker_payload["candidates"][0]["normalizedTargetProvider"],
                "codex",
            )
            self.assertFalse(worker_payload["providerRuntimeStatusRead"])
            send_payload = json.loads(sent.stdout)
            self.assertEqual(send_payload["schema"], "agent_dispatch_send.v1")
            self.assertEqual(send_payload["actingIdentity"]["inputSource"], "legacy_from")
            self.assertEqual(send_payload["routeSummary"]["source"]["alias"], "codex-source")
            self.assertFalse(
                send_payload["routeSummary"]["identityBoundary"]["callerAuthenticated"]
            )
            self.assertEqual(send_payload["apiLayer"], "delivery-oriented")
            self.assertEqual(send_payload["deliveryMode"], "worker_dry_run")
            self.assertEqual(
                send_payload["sendModeSummary"]["deliveryMode"],
                "worker_dry_run",
            )
            self.assertTrue(send_payload["queuedDispatchCreated"])
            self.assertTrue(send_payload["workerRunRequested"])
            self.assertFalse(send_payload["workerExecuted"])
            self.assertEqual(send_payload["agentDispatch"]["status"], "queued")
            self.assertEqual(send_payload["agentDispatch"]["sourceAgentId"], "agent-a")
            self.assertEqual(send_payload["agentDispatch"]["targetAgentId"], "agent-b")
            self.assertEqual(
                send_payload["agentDispatch"]["sourceHandleId"],
                "codex-source-handle-cli",
            )
            self.assertEqual(
                send_payload["agentDispatch"]["targetHandleId"],
                "codex-target-handle-cli",
            )
            self.assertEqual(send_payload["agentDispatch"]["targetProvider"], "codex")
            self.assertEqual(
                send_payload["agentDispatch"]["replyPolicy"],
                "source_handle_required",
            )
            self.assertEqual(
                send_payload["agentExchangeRequest"]["detailRefs"],
                ["docs/dispatch-handoff.md"],
            )
            self.assertEqual(
                send_payload["agentExchangeRequest"]["requestKind"],
                "sync",
            )
            self.assertEqual(
                send_payload["agentExchangeRequest"]["requestSummary"],
                "Review via high-level dispatch send.",
            )
            self.assertIn("targetHandoff", send_payload)
            handoff = send_payload["targetHandoff"]
            self.assertEqual(handoff["runtimeConfigSource"], "profile")
            self.assertEqual(handoff["profilePath"], resolved_profile)
            self.assertIn("--profile", handoff["requestReadArgv"])
            self.assertIn(resolved_profile, handoff["requestReadArgv"])
            self.assertNotIn("--database", handoff["requestReadArgv"])
            self.assertNotIn("@common", handoff["requestReadCommand"])
            self.assertIn(f'"{resolved_profile}"', handoff["requestReadCommand"])
            self.assertIn(
                "agent-exchange-request-get",
                handoff["requestReadCommand"],
            )
            self.assertIn(
                "agent-exchange-request-respond",
                handoff["respondCommandTemplate"],
            )
            self.assertIn("--profile", send_payload["statusCommand"])
            self.assertIn(f'"{resolved_profile}"', send_payload["statusCommand"])
            self.assertNotIn("--database", send_payload["statusCommand"])
            self.assertTrue(
                send_payload["endpointAliasResolution"][
                    "sourceEndpointAliasResolved"
                ]
            )
            self.assertTrue(
                send_payload["endpointAliasResolution"][
                    "targetEndpointAliasResolved"
                ]
            )
            self.assertEqual(
                send_payload["agentDispatch"]["metadata"]["agentDispatchSend"][
                    "deliveryMode"
                ],
                "worker_dry_run",
            )
            self.assertEqual(
                send_payload["agentDispatch"]["metadata"]["priority"],
                "high",
            )
            self.assertEqual(
                send_payload["agentDispatch"]["metadata"]["agentDispatchSend"][
                    "endpointAliasResolution"
                ]["targetEndpoint"]["alias"],
                "codex-target",
            )
            self.assertTrue(send_payload["workerRun"]["dryRun"])
            self.assertEqual(send_payload["workerRun"]["candidateCount"], 1)
            self.assertEqual(send_payload["workerRun"]["processedCount"], 0)
            self.assertIn("agent-dispatch-status", send_payload["statusCommand"])
            target_status_payload = json.loads(target_endpoint_status.stdout)
            self.assertEqual(
                target_status_payload["schema"],
                "agent_endpoint_status.v1",
            )
            self.assertEqual(target_status_payload["summary"]["inboxTotal"], 1)
            self.assertEqual(target_status_payload["summary"]["outboxTotal"], 0)
            self.assertEqual(
                target_status_payload["inbox"]["agentDispatches"][0][
                    "agentDispatch"
                ]["dispatchId"],
                "dispatch-send-cli-1",
            )
            compact_payload = json.loads(compact_dispatch_status.stdout)
            self.assertEqual(compact_payload["schema"], "agent_exchange_compact_status.v1")
            self.assertEqual(compact_payload["requestId"], "req-dispatch-send-cli-1")
            self.assertEqual(compact_payload["source"]["alias"], "codex-source")
            self.assertEqual(compact_payload["target"]["alias"], "codex-target")
            self.assertEqual(compact_payload["requestStatus"], "active")
            self.assertEqual(compact_payload["dispatchStatus"], "queued")
            self.assertFalse(compact_payload["wakeDelivered"])
            self.assertEqual(compact_payload["providerCommandStatus"], "not_started")
            self.assertFalse(compact_payload["targetResponseCompleted"])
            self.assertEqual(compact_payload["recommendedAction"], "run_worker_or_daemon")
            self.assertFalse(compact_payload["timelineIncluded"])
            self.assertFalse(compact_payload["wakeTicketIncluded"])
            self.assertNotIn("statusTimeline", compact_payload)
            self.assertNotIn("wakeStatus", compact_payload)
            self.assertEqual(
                json.loads(compact_request_status.stdout),
                compact_payload,
            )
            compact_failure_payload = json.loads(compact_failure_status.stdout)
            self.assertEqual(compact_failure_payload["dispatchStatus"], "failed")
            self.assertEqual(
                compact_failure_payload["providerCommandStatus"],
                "failed",
            )
            self.assertEqual(
                compact_failure_payload["providerFailure"]["category"],
                "missing_target_handle",
            )
            self.assertEqual(
                compact_failure_payload["recommendedAction"],
                "inspect_provider_failure",
            )

    def test_python_module_profile_drives_endpoint_login_cli_flow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "agent-os-profile.json"
            profile.write_text(
                json.dumps(
                    {
                        "localRuntime": {
                            "databasePath": str(root / "platform.sqlite3"),
                            "workspaceRoot": str(root / "workspace"),
                            "pluginsDirectory": str(root / "plugins"),
                        }
                    }
                ),
                encoding="utf-8",
            )

            created = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "workspace-create",
                "--workspace-id",
                "workspace-endpoint-cli",
                "--display-name",
                "Endpoint CLI Workspace",
                "--agent-id",
                "agent-a",
            )
            handle = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "codex-session-handle-register",
                "--workspace-id",
                "workspace-endpoint-cli",
                "--agent-id",
                "agent-a",
                "--handle-id",
                "codex-handle-cli",
                "--codex-session-id",
                "codex-session-cli",
                "--cwd",
                str(root),
                "--created-by",
                "user",
                "--reason",
                "CLI endpoint fixture",
                "--metadata-json",
                json.dumps(
                    {
                        "providerRuntimeStatus": {
                            "threadStatus": "running",
                            "threadId": "codex-thread-cli",
                        },
                        "providerRuntimeStatusProbe": {
                            "mode": "local_command_json",
                            "argv": [
                                sys.executable,
                                "-c",
                                "print('{\"threadStatus\":\"completed\"}')",
                            ],
                            "timeoutSeconds": 5,
                        },
                    }
                ),
            )
            login = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-endpoint-login",
                "--workspace-id",
                "workspace-endpoint-cli",
                "--agent-id",
                "agent-a",
                "--endpoint-id",
                "endpoint-codex-cli",
                "--alias",
                "Codex-Main",
                "--provider",
                "codex-cli",
                "--provider-handle-id",
                "codex-handle-cli",
                "--created-by",
                "user",
                "--reason",
                "CLI endpoint login",
                "--allow-source-alias",
                "codex-peer",
                "--block-source-agent-id",
                "agent-muted",
            )
            listed = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-endpoint-list",
                "--workspace-id",
                "workspace-endpoint-cli",
            )
            fetched = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-endpoint-get",
                "--workspace-id",
                "workspace-endpoint-cli",
                "--alias",
                "codex-main",
            )
            runtime_status = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-provider-runtime-status",
                "--workspace-id",
                "workspace-endpoint-cli",
                "--alias",
                "codex-main",
            )
            runtime_status_live = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-provider-runtime-status",
                "--workspace-id",
                "workspace-endpoint-cli",
                "--alias",
                "codex-main",
                "--read-live-runtime-status",
            )
            runtime_status_disabled = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-provider-runtime-status",
                "--workspace-id",
                "workspace-endpoint-cli",
                "--alias",
                "codex-main",
                "--runtime-status-policy",
                "disabled",
            )
            deactivated = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-endpoint-deactivate",
                "--workspace-id",
                "workspace-endpoint-cli",
                "--alias",
                "codex-main",
                "--deactivated-by",
                "user",
                "--reason",
                "CLI cleanup",
            )

            for result in (
                created,
                handle,
                login,
                listed,
                fetched,
                runtime_status,
                runtime_status_live,
                runtime_status_disabled,
                deactivated,
            ):
                self.assertEqual(result.returncode, 0, result.stderr)

            login_payload = json.loads(login.stdout)
            self.assertTrue(login_payload["loggedIn"])
            self.assertEqual(login_payload["agentEndpoint"]["schema"], "agent_endpoint.v1")
            self.assertEqual(login_payload["agentEndpoint"]["alias"], "codex-main")
            self.assertEqual(login_payload["agentEndpoint"]["provider"], "codex")
            self.assertEqual(
                login_payload["agentEndpoint"]["providerHandleId"],
                "codex-handle-cli",
            )
            self.assertEqual(
                login_payload["agentEndpoint"]["metadata"]["contactPolicyProfile"][
                    "allowedSourceEndpointAliases"
                ],
                ["codex-peer"],
            )
            self.assertEqual(
                login_payload["agentEndpoint"]["metadata"]["contactPolicyProfile"][
                    "blockedSourceAgentIds"
                ],
                ["agent-muted"],
            )
            list_payload = json.loads(listed.stdout)
            self.assertEqual(list_payload["count"], 1)
            self.assertEqual(
                list_payload["agentEndpoints"][0]["endpointId"],
                "endpoint-codex-cli",
            )
            fetched_payload = json.loads(fetched.stdout)
            self.assertEqual(
                fetched_payload["providerHandle"]["codexSessionId"],
                "codex-session-cli",
            )
            runtime_payload = json.loads(runtime_status.stdout)
            self.assertEqual(
                runtime_payload["schema"],
                "agent_provider_runtime_status_get.v1",
            )
            self.assertEqual(
                runtime_payload["providerRuntimeStatus"]["runtimeState"],
                "idle",
            )
            self.assertTrue(
                runtime_payload["providerRuntimeStatus"][
                    "providerRuntimeStatusRead"
                ],
            )
            self.assertEqual(
                runtime_payload["providerRuntimeStatus"]["runtimeStatusPolicy"],
                "auto",
            )
            live_payload = json.loads(runtime_status_live.stdout)
            self.assertEqual(
                live_payload["providerRuntimeStatus"]["runtimeState"],
                "idle",
            )
            self.assertEqual(
                live_payload["providerRuntimeStatus"][
                    "providerRuntimeStatusReadMode"
                ],
                "local_command_probe",
            )
            self.assertEqual(
                live_payload["providerRuntimeStatus"][
                    "providerRuntimeStatusProbe"
                ]["status"],
                "read",
            )
            disabled_payload = json.loads(runtime_status_disabled.stdout)
            self.assertEqual(
                disabled_payload["providerRuntimeStatus"]["runtimeState"],
                "busy",
            )
            self.assertEqual(
                disabled_payload["providerRuntimeStatus"]["runtimeStatusPolicy"],
                "disabled",
            )
            self.assertEqual(
                disabled_payload["providerRuntimeStatus"][
                    "providerRuntimeStatusProbe"
                ]["status"],
                "disabled",
            )
            deactivated_payload = json.loads(deactivated.stdout)
            self.assertTrue(deactivated_payload["deactivated"])
            self.assertEqual(
                deactivated_payload["agentEndpoint"]["state"],
                "inactive",
            )

    def test_python_module_invoke_json_preserves_payload_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            created = _run_cli(
                directory,
                "workspace-create",
                "--workspace-id",
                "workspace-json-1",
                "--display-name",
                "JSON Workspace",
            )
            self.assertEqual(created.returncode, 0, created.stderr)

            invoked = _run_cli(
                directory,
                "invoke-json",
                "--payload-json",
                json.dumps(
                    {
                        "workspaceId": "workspace-json-1",
                        "agentId": "agent-workspace-json-1",
                        "instruction": "Run JSON invocation.",
                    }
                ),
                "--payload",
                "invocationId=invoke-json-1",
                "--payload",
                "sessionId=session-json-1",
                "--payload",
                "correlationId=correlation-json-1",
            )
            invocations = _run_cli(
                directory,
                "records-invocations",
                "--workspace-id",
                "workspace-json-1",
            )

            self.assertEqual(invoked.returncode, 0, invoked.stderr)
            self.assertEqual(invocations.returncode, 0, invocations.stderr)
            self.assertEqual(
                json.loads(invoked.stdout)["invocationResult"]["invocationId"],
                "invoke-json-1",
            )
            self.assertEqual(
                json.loads(invocations.stdout)["invocations"][0]["correlationId"],
                "correlation-json-1",
            )

    def test_python_module_runtime_permission_commands_are_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            created = _run_cli(
                directory,
                "workspace-create",
                "--workspace-id",
                "workspace-runtime-permissions-cli-1",
                "--agent-id",
                "agent-runtime-permissions-cli-1",
                "--display-name",
                "Runtime Permissions CLI Workspace",
            )
            agent = _run_cli(
                directory,
                "agent-create",
                "--workspace-id",
                "workspace-runtime-permissions-cli-1",
                "--agent-id",
                "agent-native-cli-1",
                "--name",
                "Native CLI",
                "--description",
                "Declares future runtime permissions.",
                "--runtime-config-json",
                json.dumps(
                    {
                        "profile": {
                            "profileName": "native-cli",
                            "roleName": "native",
                            "runtimeKind": "agent-native-runtime",
                            "runtimeAccess": {
                                "delegatedContextDelivery": (
                                    "bounded_materialized_segments"
                                ),
                                "toolPermissions": ["declared_tools_only"],
                                "filePermission": "file_ref_metadata_only",
                                "memoryPolicy": "runtime_local_ephemeral",
                                "memoryNamespace": "native-cli",
                                "memoryQuotaMb": 4,
                                "networkPolicy": "disabled",
                            },
                        },
                    }
                ),
            )
            listed = _run_cli(
                directory,
                "agent-runtime-permissions",
                "--workspace-id",
                "workspace-runtime-permissions-cli-1",
            )
            viewed = _run_cli(
                directory,
                "agent-runtime-permission-get",
                "--workspace-id",
                "workspace-runtime-permissions-cli-1",
                "--agent-id",
                "agent-native-cli-1",
            )
            invocations = _run_cli(
                directory,
                "records-invocations",
                "--workspace-id",
                "workspace-runtime-permissions-cli-1",
            )

            for result in (created, agent, listed, viewed, invocations):
                self.assertEqual(result.returncode, 0, result.stderr)

            list_payload = json.loads(listed.stdout)
            view_payload = json.loads(viewed.stdout)["runtimePermission"]
            self.assertEqual(len(list_payload["runtimePermissions"]), 2)
            self.assertEqual(view_payload["agentId"], "agent-native-cli-1")
            self.assertEqual(view_payload["runtimeKind"], "agent_native_runtime")
            self.assertTrue(view_payload["readModelOnly"])
            self.assertFalse(view_payload["runtimeConnected"])
            self.assertFalse(
                view_payload["deliveryPlan"]["materialized_text_included"]
            )
            self.assertFalse(
                view_payload["capabilities"]["flags"][
                    "websocket_transport_allowed"
                ]
            )
            self.assertEqual(json.loads(invocations.stdout)["invocations"], [])

    def test_python_module_conversation_command_flow_reuses_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            created = _run_cli(
                directory,
                "workspace-create",
                "--workspace-id",
                "workspace-conversation-cli-1",
                "--agent-id",
                "agent-conversation-cli-1",
                "--display-name",
                "Conversation CLI Workspace",
            )
            conversation = _run_cli(
                directory,
                "conversation-create",
                "--workspace-id",
                "workspace-conversation-cli-1",
                "--conversation-id",
                "conversation-cli-1",
                "--agent-id",
                "agent-conversation-cli-1",
                "--title",
                "Reviewer thread",
                "--metadata-json",
                json.dumps({"profile_name": "reviewer"}),
            )
            listed = _run_cli(
                directory,
                "conversation-list",
                "--workspace-id",
                "workspace-conversation-cli-1",
            )
            opened = _run_cli(
                directory,
                "conversation-get",
                "--workspace-id",
                "workspace-conversation-cli-1",
                "--conversation-id",
                "conversation-cli-1",
            )
            message = _run_cli(
                directory,
                "conversation-message-append",
                "--workspace-id",
                "workspace-conversation-cli-1",
                "--conversation-id",
                "conversation-cli-1",
                "--message-id",
                "message-cli-1",
                "--role",
                "user",
                "--content",
                "Please review this.",
                "--run-session-id",
                "session-conversation-cli-1",
                "--metadata",
                "visibility=team",
                "--exchange-attribution-source-type",
                "agent_message",
                "--exchange-attribution-author-type",
                "agent",
                "--exchange-attribution-contribution-kind",
                "observation",
                "--exchange-attribution-author-agent-id",
                "agent-conversation-cli-1",
                "--exchange-attribution-request-id",
                "req-conversation-cli-1",
                "--exchange-attribution-source",
                "local_runtime_cli",
            )
            messages = _run_cli(
                directory,
                "conversation-messages",
                "--workspace-id",
                "workspace-conversation-cli-1",
                "--conversation-id",
                "conversation-cli-1",
            )
            archived = _run_cli(
                directory,
                "conversation-archive",
                "--workspace-id",
                "workspace-conversation-cli-1",
                "--conversation-id",
                "conversation-cli-1",
            )
            rejected = _run_cli(
                directory,
                "conversation-message-append",
                "--workspace-id",
                "workspace-conversation-cli-1",
                "--conversation-id",
                "conversation-cli-1",
                "--role",
                "user",
                "--content",
                "Should fail.",
            )

            for result in (
                created,
                conversation,
                listed,
                opened,
                message,
                messages,
                archived,
            ):
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(rejected.returncode, 1)
            self.assertNotIn("Traceback", rejected.stderr)

            self.assertEqual(
                json.loads(conversation.stdout)["conversation"]["conversationId"],
                "conversation-cli-1",
            )
            self.assertEqual(
                json.loads(listed.stdout)["conversations"][0]["conversationId"],
                "conversation-cli-1",
            )
            self.assertEqual(
                json.loads(opened.stdout)["conversation"]["metadata"]["profile_name"],
                "reviewer",
            )
            self.assertEqual(json.loads(message.stdout)["message"]["sequence"], 1)
            self.assertEqual(
                json.loads(message.stdout)["message"]["metadata"]["visibility"],
                "team",
            )
            self.assertEqual(
                json.loads(message.stdout)["message"]["metadata"]["agentExchange"][
                    "metadata"
                ][
                    "exchangeRequestId"
                ],
                "req-conversation-cli-1",
            )
            self.assertEqual(
                json.loads(messages.stdout)["messages"][0]["messageId"],
                "message-cli-1",
            )
            self.assertEqual(json.loads(archived.stdout)["conversation"]["status"], "archived")
            self.assertIn("conversation is archived", rejected.stderr)

    def test_python_module_agent_exchange_commands_return_metadata_only_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            created = _run_cli(
                directory,
                "workspace-create",
                "--workspace-id",
                "workspace-agent-exchange-cli-1",
                "--agent-id",
                "agent-agent-exchange-cli-1",
                "--display-name",
                "Agent Exchange CLI Workspace",
            )
            instructions = _run_cli(
                directory,
                "agent-exchange-instructions",
                "--workspace-id",
                "workspace-agent-exchange-cli-1",
            )
            context = _run_cli(
                directory,
                "context-append",
                "--workspace-id",
                "workspace-agent-exchange-cli-1",
                "--summary",
                "Reviewer proposes a source-attributed handoff.",
                "--update-kind",
                "agent_message",
                "--payload",
                "note=field-style-payload",
                "--exchange-attribution-source-type",
                "agent_context_update",
                "--exchange-attribution-author-type",
                "agent",
                "--exchange-attribution-contribution-kind",
                "proposal",
                "--exchange-attribution-author-agent-id",
                "agent-agent-exchange-cli-1",
                "--exchange-attribution-source-confidence",
                "medium",
                "--exchange-attribution-request-id",
                "req-context-cli-1",
                "--exchange-attribution-source",
                "local_runtime_cli",
            )
            context_updates = _run_cli(
                directory,
                "context-updates",
                "--workspace-id",
                "workspace-agent-exchange-cli-1",
            )
            context_update = _run_cli(
                directory,
                "context-update-get",
                "--workspace-id",
                "workspace-agent-exchange-cli-1",
                "--update-id",
                json.loads(context.stdout)["contextUpdate"]["updateId"],
            )
            invalid_context_kind = _run_cli(
                directory,
                "context-append",
                "--workspace-id",
                "workspace-agent-exchange-cli-1",
                "--summary",
                "Invalid update kind should fail early.",
                "--update-kind",
                "handoff_note",
            )
            conversation = _run_cli(
                directory,
                "conversation-create",
                "--workspace-id",
                "workspace-agent-exchange-cli-1",
                "--conversation-id",
                "conversation-agent-exchange-cli-1",
                "--agent-id",
                "agent-agent-exchange-cli-1",
                "--title",
                "Agent exchange thread",
            )
            message = _run_cli(
                directory,
                "conversation-message-append",
                "--workspace-id",
                "workspace-agent-exchange-cli-1",
                "--conversation-id",
                "conversation-agent-exchange-cli-1",
                "--message-id",
                "message-agent-exchange-cli-1",
                "--role",
                "assistant",
                "--content",
                "I will wait for user review before treating this as decided.",
                "--agent-id",
                "agent-agent-exchange-cli-1",
                "--exchange-attribution-json",
                json.dumps(
                    {
                        "sourceType": "agent_message",
                        "authorType": "agent",
                        "contributionKind": "conflict_note",
                        "authorAgentId": "agent-agent-exchange-cli-1",
                        "conflictWith": ["update-previous"],
                    }
                ),
            )

            for result in (
                created,
                instructions,
                context,
                context_updates,
                context_update,
                conversation,
                message,
            ):
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotEqual(invalid_context_kind.returncode, 0)
            self.assertIn("invalid choice", invalid_context_kind.stderr)

            interface = json.loads(instructions.stdout)["agentExchangeInterface"]
            self.assertFalse(interface["realRuntimeConnected"])
            self.assertFalse(interface["agentAutoWakeEnabled"])
            self.assertIn("agent_context_update", interface["sourceTypes"])

            context_exchange = (
                json.loads(context.stdout)["contextUpdate"]["metadata"]["agentExchange"]
            )
            self.assertEqual(context_exchange["authorType"], "agent")
            self.assertEqual(context_exchange["sourceChannel"], "local_runtime_cli")
            self.assertEqual(
                context_exchange["metadata"]["exchangeRequestId"],
                "req-context-cli-1",
            )
            self.assertEqual(
                context_exchange["instructionAuthority"],
                "agent_suggestion",
            )
            self.assertFalse(context_exchange["autoPromoteToDecision"])
            listed_update = json.loads(context_updates.stdout)["contextUpdates"][0]
            self.assertEqual(
                listed_update["metadata"]["agentExchange"]["contributionKind"],
                "proposal",
            )
            fetched_update = json.loads(context_update.stdout)["contextUpdate"]
            self.assertEqual(
                fetched_update["summary"],
                "Reviewer proposes a source-attributed handoff.",
            )
            self.assertEqual(fetched_update["payload"]["note"], "field-style-payload")

            message_exchange = (
                json.loads(message.stdout)["message"]["metadata"]["agentExchange"]
            )
            self.assertEqual(message_exchange["contributionKind"], "conflict_note")
            self.assertTrue(message_exchange["requiresUserReview"])
            self.assertEqual(message_exchange["conflictWith"], ["update-previous"])

    def test_python_module_agent_exchange_request_commands_flow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            created = _run_cli(
                directory,
                "workspace-create",
                "--workspace-id",
                "workspace-exchange-request-cli-1",
                "--agent-id",
                "agent-request-a-cli-1",
                "--display-name",
                "Agent Exchange Request CLI Workspace",
            )
            target = _run_cli(
                directory,
                "agent-create",
                "--workspace-id",
                "workspace-exchange-request-cli-1",
                "--agent-id",
                "agent-request-b-cli-1",
                "--name",
                "Request Target",
                "--description",
                "Responds to directed exchange requests.",
            )
            instructions = _run_cli(
                directory,
                "agent-exchange-request-instructions",
                "--workspace-id",
                "workspace-exchange-request-cli-1",
            )
            policy = _run_cli(
                directory,
                "agent-exchange-request-policy",
                "--workspace-id",
                "workspace-exchange-request-cli-1",
            )
            request = _run_cli(
                directory,
                "agent-exchange-request-create",
                "--workspace-id",
                "workspace-exchange-request-cli-1",
                "--exchange-request-id",
                "req-cli-1",
                "--source-agent-id",
                "agent-request-a-cli-1",
                "--target-agent-id",
                "agent-request-b-cli-1",
                "--request-kind",
                "review",
                "--request-summary",
                "Please review the CLI request contract.",
                "--detail-refs-json",
                json.dumps(["docs/directed_agent_exchange_requests.md"]),
            )
            thread_instructions = _run_cli(
                directory,
                "agent-exchange-thread-instructions",
                "--workspace-id",
                "workspace-exchange-request-cli-1",
            )
            thread_list = _run_cli(
                directory,
                "agent-exchange-thread-list",
                "--workspace-id",
                "workspace-exchange-request-cli-1",
                "--requesting-agent-id",
                "agent-request-b-cli-1",
            )
            thread_get = _run_cli(
                directory,
                "agent-exchange-thread-get",
                "--workspace-id",
                "workspace-exchange-request-cli-1",
                "--thread-id",
                "req-cli-1",
                "--requesting-agent-id",
                "agent-request-b-cli-1",
            )
            listed = _run_cli(
                directory,
                "agent-exchange-request-list",
                "--workspace-id",
                "workspace-exchange-request-cli-1",
                "--target-agent-id",
                "agent-request-b-cli-1",
            )
            responded = _run_cli(
                directory,
                "agent-exchange-request-respond",
                "--workspace-id",
                "workspace-exchange-request-cli-1",
                "--exchange-request-id",
                "req-cli-1",
                "--responding-agent-id",
                "agent-request-b-cli-1",
                "--response-summary",
                "The CLI request contract is readable.",
                "--response-source",
                "manual_or_proxy_diagnostic",
                "--actual-writer-agent-id",
                "claude-smoke-26-5",
            )
            exchange_status = _run_cli(
                directory,
                "agent-exchange-status",
                "--workspace-id",
                "workspace-exchange-request-cli-1",
                "--exchange-request-id",
                "req-cli-1",
            )
            compact_exchange_status = _run_cli(
                directory,
                "agent-exchange-status",
                "--workspace-id",
                "workspace-exchange-request-cli-1",
                "--exchange-request-id",
                "req-cli-1",
                "--format",
                "compact",
            )
            follow_up = _run_cli(
                directory,
                "agent-exchange-thread-follow-up-create",
                "--workspace-id",
                "workspace-exchange-request-cli-1",
                "--thread-id",
                "req-cli-1",
                "--exchange-request-id",
                "req-cli-2",
                "--source-agent-id",
                "agent-request-a-cli-1",
                "--target-agent-id",
                "agent-request-b-cli-1",
                "--request-kind",
                "question",
                "--request-summary",
                "Please confirm the follow-up thread command.",
            )
            thread_requests = _run_cli(
                directory,
                "agent-exchange-thread-requests",
                "--workspace-id",
                "workspace-exchange-request-cli-1",
                "--thread-id",
                "req-cli-1",
                "--requesting-agent-id",
                "agent-request-a-cli-1",
            )
            visibility = _run_cli(
                directory,
                "agent-exchange-thread-visibility-update",
                "--workspace-id",
                "workspace-exchange-request-cli-1",
                "--thread-id",
                "req-cli-1",
                "--updated-by-agent-id",
                "agent-request-a-cli-1",
                "--visibility",
                "participants_only",
            )
            thread_close = _run_cli(
                directory,
                "agent-exchange-thread-close",
                "--workspace-id",
                "workspace-exchange-request-cli-1",
                "--thread-id",
                "req-cli-1",
                "--closed-by-agent-id",
                "agent-request-a-cli-1",
            )
            opened = _run_cli(
                directory,
                "agent-exchange-request-get",
                "--workspace-id",
                "workspace-exchange-request-cli-1",
                "--exchange-request-id",
                "req-cli-1",
            )
            invocations = _run_cli(
                directory,
                "records-invocations",
                "--workspace-id",
                "workspace-exchange-request-cli-1",
            )

            for result in (
                created,
                target,
                instructions,
                policy,
                request,
                thread_instructions,
                thread_list,
                thread_get,
                listed,
                responded,
                exchange_status,
                compact_exchange_status,
                follow_up,
                thread_requests,
                visibility,
                thread_close,
                opened,
                invocations,
            ):
                self.assertEqual(result.returncode, 0, result.stderr)

            interface = json.loads(instructions.stdout)[
                "agentExchangeRequestInterface"
            ]
            self.assertFalse(interface["realRuntimeConnected"])
            self.assertFalse(interface["agentAutoWakeEnabled"])
            self.assertIn("review", interface["requestKinds"])
            self.assertIn("workspace_readable", interface["threadVisibilities"])
            self.assertEqual(
                interface["localRuntimeCommands"]["threadList"],
                "agent-exchange-thread-list",
            )
            policy_payload = json.loads(policy.stdout)["agentExchangeRequestPolicy"]
            self.assertEqual(policy_payload["authorizationMode"], "direct_allowed")
            self.assertEqual(policy_payload["subRequestPolicy"], "allowed")
            self.assertEqual(policy_payload["maxTurns"], 5)
            self.assertEqual(policy_payload["followUpPolicy"], "single_target_chain")
            self.assertFalse(
                policy_payload["autoAppendExchangeResultToSharedContext"]
            )
            request_payload = json.loads(request.stdout)["agentExchangeRequest"]
            self.assertEqual(request_payload["exchangeRequestId"], "req-cli-1")
            self.assertEqual(request_payload["targetAgentId"], "agent-request-b-cli-1")
            self.assertEqual(
                request_payload["detailRefs"],
                ["docs/directed_agent_exchange_requests.md"],
            )
            self.assertEqual(
                json.loads(listed.stdout)["agentExchangeRequests"][0][
                    "exchangeRequestId"
                ],
                "req-cli-1",
            )
            thread_interface = json.loads(thread_instructions.stdout)[
                "agentExchangeRequestInterface"
            ]
            self.assertFalse(thread_interface["agentAutoWakeEnabled"])
            self.assertEqual(
                json.loads(thread_list.stdout)["agentExchangeThreads"][0][
                    "exchangeThreadId"
                ],
                "req-cli-1",
            )
            self.assertEqual(
                json.loads(thread_get.stdout)["agentExchangeThread"]["maxTurns"],
                5,
            )
            response_payload = json.loads(responded.stdout)["agentExchangeRequest"]
            self.assertEqual(response_payload["status"], "terminal")
            self.assertEqual(response_payload["terminalReason"], "responded")
            self.assertFalse(response_payload["autoSharedContextAppendExecuted"])
            self.assertEqual(
                response_payload["metadata"]["responseSource"],
                "manual_or_proxy_diagnostic",
            )
            self.assertEqual(
                response_payload["metadata"]["actualWriterAgentId"],
                "claude-smoke-26-5",
            )
            self.assertEqual(
                response_payload["metadata"]["claimedRespondingAgentId"],
                "agent-request-b-cli-1",
            )
            exchange_status_payload = json.loads(exchange_status.stdout)
            self.assertEqual(
                exchange_status_payload["schema"],
                "agent_exchange_status_summary.v1",
            )
            self.assertEqual(
                exchange_status_payload["responseSourceStatus"]["responseSource"],
                "standard_respond",
            )
            self.assertFalse(
                exchange_status_payload["responseSourceStatus"][
                    "stdoutFallbackCaptured"
                ]
            )
            self.assertFalse(
                exchange_status_payload["dispatchStatusBoundary"]["dispatchLinked"]
            )
            self.assertEqual(
                exchange_status_payload["workspace"]["workspaceId"],
                "workspace-exchange-request-cli-1",
            )
            self.assertIn(
                "responded",
                [
                    event["stage"]
                    for event in exchange_status_payload["statusTimeline"]["events"]
                ],
            )
            compact_status_payload = json.loads(compact_exchange_status.stdout)
            self.assertEqual(
                compact_status_payload["schema"],
                "agent_exchange_compact_status.v1",
            )
            self.assertEqual(compact_status_payload["requestStatus"], "terminal")
            self.assertIsNone(compact_status_payload["dispatchStatus"])
            self.assertFalse(compact_status_payload["wakeDelivered"])
            self.assertEqual(
                compact_status_payload["providerCommandStatus"],
                "not_started",
            )
            self.assertTrue(compact_status_payload["targetResponseCompleted"])
            self.assertTrue(compact_status_payload["standardRespondWritten"])
            self.assertEqual(
                compact_status_payload["responseSource"],
                "standard_respond",
            )
            self.assertEqual(
                compact_status_payload["recommendedAction"],
                "read_response",
            )
            self.assertFalse(compact_status_payload["timelineIncluded"])
            follow_up_payload = json.loads(follow_up.stdout)["agentExchangeRequest"]
            self.assertEqual(follow_up_payload["parentRequestId"], "req-cli-1")
            self.assertEqual(follow_up_payload["threadId"], "req-cli-1")
            thread_requests_payload = json.loads(thread_requests.stdout)
            self.assertEqual(
                [
                    item["exchangeRequestId"]
                    for item in thread_requests_payload["agentExchangeRequests"]
                ],
                ["req-cli-1", "req-cli-2"],
            )
            self.assertEqual(
                json.loads(visibility.stdout)["agentExchangeThread"]["visibility"],
                "participants_only",
            )
            self.assertEqual(
                json.loads(thread_close.stdout)["agentExchangeThread"]["threadStatus"],
                "terminal",
            )
            self.assertEqual(
                json.loads(opened.stdout)["agentExchangeRequest"]["responseSummary"],
                "The CLI request contract is readable.",
            )
            self.assertEqual(json.loads(invocations.stdout)["invocations"], [])

    def test_python_module_agent_wake_watch_and_daemon_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace_id = "workspace-wake-cli-1"
            source_agent_id = "agent-wake-a-cli-1"
            target_agent_id = "agent-wake-b-cli-1"
            request_id = "req-wake-cli-1"
            created = _run_cli(
                directory,
                "workspace-create",
                "--workspace-id",
                workspace_id,
                "--agent-id",
                source_agent_id,
                "--display-name",
                "Wake CLI Workspace",
            )
            target = _run_cli(
                directory,
                "agent-create",
                "--workspace-id",
                workspace_id,
                "--agent-id",
                target_agent_id,
                "--name",
                "Wake Target",
                "--description",
                "Receives wake tickets.",
            )
            request = _run_cli(
                directory,
                "agent-exchange-request-create",
                "--workspace-id",
                workspace_id,
                "--exchange-request-id",
                request_id,
                "--source-agent-id",
                source_agent_id,
                "--target-agent-id",
                target_agent_id,
                "--request-kind",
                "review",
                "--request-summary",
                "请检查 wake daemon ticket 的中文摘要。",
            )
            instructions = _run_cli(
                directory,
                "agent-wake-instructions",
                "--workspace-id",
                workspace_id,
                "--agent-id",
                target_agent_id,
            )
            dry_run = _run_cli(
                directory,
                "agent-exchange-wake-watch",
                "--workspace-id",
                workspace_id,
                "--agent-id",
                target_agent_id,
                "--once",
                "--dry-run",
            )
            daemon_dry_run = _run_wake_daemon(
                directory,
                "--workspace-id",
                workspace_id,
                "--agent-id",
                target_agent_id,
                "--once",
                "--dry-run",
            )
            handoff_dir = Path(directory) / "handoff files"
            handoff = _run_cli(
                directory,
                "agent-exchange-wake-watch",
                "--workspace-id",
                workspace_id,
                "--agent-id",
                target_agent_id,
                "--wake-mode",
                "handoff_file",
                "--handoff-directory",
                str(handoff_dir),
            )
            delivery_list = _run_cli(
                directory,
                "agent-wake-delivery-list",
                "--workspace-id",
                workspace_id,
                "--agent-id",
                target_agent_id,
                "--exchange-request-id",
                request_id,
            )
            wake_status = _run_cli(
                directory,
                "agent-wake-status",
                "--workspace-id",
                workspace_id,
                "--exchange-request-id",
                request_id,
            )
            ticket_get = _run_cli(
                directory,
                "agent-wake-ticket-get",
                "--workspace-id",
                workspace_id,
                "--exchange-request-id",
                request_id,
            )
            request_get = _run_cli(
                directory,
                "agent-exchange-request-get",
                "--workspace-id",
                workspace_id,
                "--exchange-request-id",
                request_id,
            )

            for result in (
                created,
                target,
                request,
                instructions,
                dry_run,
                daemon_dry_run,
                handoff,
                delivery_list,
                wake_status,
                ticket_get,
                request_get,
            ):
                self.assertEqual(result.returncode, 0, result.stderr)

            interface = json.loads(instructions.stdout)["agentWakeInterface"]
            self.assertEqual(interface["status"], "local_wrapper_daemon_prototype")
            self.assertIn("handoff_file", interface["wakeModes"])
            self.assertFalse(interface["realRuntimeConnected"])

            dry_payload = json.loads(dry_run.stdout)["agentWakeRun"]
            self.assertEqual(dry_payload["pendingRequestCount"], 1)
            self.assertEqual(dry_payload["attempts"][0]["status"], "dry_run")
            self.assertEqual(
                dry_payload["attempts"][0]["ticket"]["exchangeRequestId"],
                request_id,
            )
            self.assertIn("agent wake daemon started", daemon_dry_run.stdout)
            self.assertIn("agent wake daemon graceful shutdown", daemon_dry_run.stdout)

            handoff_payload = json.loads(handoff.stdout)["agentWakeRun"]
            ticket_path = Path(handoff_payload["attempts"][0]["ticketPath"])
            ticket = json.loads(ticket_path.read_text(encoding="utf-8"))
            self.assertEqual(handoff_payload["deliveredCount"], 1)
            self.assertTrue(ticket_path.exists())
            self.assertEqual(ticket["exchangeRequestId"], request_id)
            self.assertIn("中文摘要", ticket["requestSummary"])
            self.assertEqual(ticket["schema"], "agent_wake_ticket.v2")
            action = ticket["recommendedAction"]
            self.assertEqual(action["runtimeConfigSource"], "explicit_args")
            self.assertEqual(action["inspectArgv"][0], sys.executable)
            self.assertEqual(
                action["inspectArgv"][1:3],
                ["-m", "agent_os.local_runtime"],
            )
            self.assertIn("PYTHONPATH", action["runtimeEnvironment"])
            self.assertNotIn("recommendedCli", ticket)
            responding_agent_index = action[
                "respondArgvTemplate"
            ].index("--responding-agent-id")
            self.assertEqual(
                action["respondArgvTemplate"][
                    responding_agent_index + 1
                ],
                "agent-wake-b-cli-1",
            )
            self.assertIn("中文摘要", request_get.stdout)

            delivery_payload = json.loads(delivery_list.stdout)
            status_payload = json.loads(wake_status.stdout)["agentWakeStatus"]
            ticket_payload = json.loads(ticket_get.stdout)["agentWakeTicket"]
            request_payload = json.loads(request_get.stdout)["agentExchangeRequest"]

            self.assertEqual(delivery_payload["totalMatched"], 2)
            self.assertEqual(
                delivery_payload["agentWakeDeliveries"][0]["delivery"]["status"],
                "delivered",
            )
            self.assertTrue(status_payload["ticketDeliveryOccurred"])
            self.assertFalse(status_payload["realRuntimeConnected"])
            self.assertIn(
                "does not mean ticket delivery failed",
                status_payload["realRuntimeControlMeaning"],
            )
            self.assertEqual(ticket_payload["exchangeRequestId"], request_id)
            self.assertEqual(ticket_payload["delivery"]["ticketPath"], str(ticket_path))
            self.assertTrue(
                request_payload["wakeDeliverySummary"]["ticketDeliveryOccurred"]
            )
            self.assertFalse(
                request_payload["wakeDeliverySummary"]["runtimeWakeTriggered"]
            )

    def test_python_module_agent_dispatch_daemon_once_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace_id = "workspace-dispatch-daemon-cli"
            source_agent_id = "agent-dispatch-daemon-a"
            target_agent_id = "agent-dispatch-daemon-b"
            created = _run_cli(
                directory,
                "workspace-create",
                "--workspace-id",
                workspace_id,
                "--agent-id",
                source_agent_id,
                "--display-name",
                "Dispatch Daemon CLI Workspace",
            )
            target = _run_cli(
                directory,
                "agent-create",
                "--workspace-id",
                workspace_id,
                "--agent-id",
                target_agent_id,
                "--name",
                "Dispatch Target",
                "--description",
                "Receives dispatch daemon work.",
            )
            dispatch = _run_cli(
                directory,
                "agent-dispatch-create",
                "--workspace-id",
                workspace_id,
                "--dispatch-id",
                "dispatch-daemon-cli-1",
                "--exchange-request-id",
                "req-dispatch-daemon-cli-1",
                "--source-agent-id",
                source_agent_id,
                "--target-agent-id",
                target_agent_id,
                "--target-handle-id",
                "missing-target-handle",
                "--target-provider",
                "codex-cli",
                "--request-kind",
                "review",
                "--request-summary",
                "Preview dispatch daemon handling.",
            )
            daemon = _run_dispatch_daemon(
                directory,
                "--workspace-id",
                workspace_id,
                "--once",
                "--dry-run",
                "--read-live-runtime-status",
            )

            for result in (created, target, dispatch, daemon):
                self.assertEqual(result.returncode, 0, result.stderr)

            self.assertIn("agent dispatch daemon started", daemon.stdout)
            self.assertIn("agent dispatch daemon graceful shutdown", daemon.stdout)
            daemon_payload = _first_json_line(daemon.stdout)
            self.assertEqual(daemon_payload["schema"], "agent_dispatch_worker_run.v1")
            self.assertTrue(daemon_payload["dryRun"])
            self.assertTrue(daemon_payload["readLiveRuntimeStatus"])
            self.assertEqual(daemon_payload["runtimeStatusPolicy"], "enabled")
            self.assertEqual(daemon_payload["candidateCount"], 1)
            self.assertEqual(
                daemon_payload["candidates"][0]["dispatchId"],
                "dispatch-daemon-cli-1",
            )

    def test_dispatch_daemon_restart_recovers_responded_orphan_lease(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace_id = "workspace-dispatch-daemon-recovery"
            source_agent_id = "agent-dispatch-recovery-a"
            target_agent_id = "agent-dispatch-recovery-b"
            commands = [
                _run_cli(
                    directory,
                    "workspace-create",
                    "--workspace-id",
                    workspace_id,
                    "--agent-id",
                    source_agent_id,
                    "--display-name",
                    "Dispatch Recovery Workspace",
                ),
                _run_cli(
                    directory,
                    "agent-create",
                    "--workspace-id",
                    workspace_id,
                    "--agent-id",
                    target_agent_id,
                    "--name",
                    "Recovery Target",
                    "--description",
                    "Responds before the original worker exits.",
                ),
                _run_cli(
                    directory,
                    "agent-dispatch-create",
                    "--workspace-id",
                    workspace_id,
                    "--dispatch-id",
                    "dispatch-daemon-recovery-1",
                    "--exchange-request-id",
                    "req-daemon-recovery-1",
                    "--source-agent-id",
                    source_agent_id,
                    "--target-agent-id",
                    target_agent_id,
                    "--target-handle-id",
                    "missing-target-handle",
                    "--target-provider",
                    "claude-code",
                    "--request-kind",
                    "review",
                    "--request-summary",
                    "Recover response after caller timeout.",
                ),
            ]
            for result in commands:
                self.assertEqual(result.returncode, 0, result.stderr)
            leased = _run_cli(
                directory,
                "agent-dispatch-lease-acquire",
                "--workspace-id",
                workspace_id,
                "--dispatch-id",
                "dispatch-daemon-recovery-1",
                "--lease-id",
                "lease-daemon-recovery-1",
                "--acquired-by",
                "agent-dispatch-daemon",
                "--lease-ttl-seconds",
                "300",
                "--metadata-json",
                json.dumps({"workerRunId": "worker-run-before-restart"}),
            )
            responded = _run_cli(
                directory,
                "agent-exchange-request-respond",
                "--workspace-id",
                workspace_id,
                "--exchange-request-id",
                "req-daemon-recovery-1",
                "--responding-agent-id",
                target_agent_id,
                "--response-summary",
                "Durable response available after daemon restart.",
            )
            preview = _run_cli(
                directory,
                "agent-dispatch-lease-reconcile",
                "--workspace-id",
                workspace_id,
                "--dry-run",
            )
            for result in (leased, responded, preview):
                self.assertEqual(result.returncode, 0, result.stderr)
            preview_payload = json.loads(preview.stdout)
            self.assertEqual(preview_payload["wouldRecoverCount"], 1)
            self.assertEqual(preview_payload["recoveredCount"], 0)

            daemon = _run_dispatch_daemon(
                directory,
                "--workspace-id",
                workspace_id,
                "--once",
            )
            status = _run_cli(
                directory,
                "agent-dispatch-status",
                "--workspace-id",
                workspace_id,
                "--dispatch-id",
                "dispatch-daemon-recovery-1",
            )
            repeated = _run_cli(
                directory,
                "agent-dispatch-lease-reconcile",
                "--workspace-id",
                workspace_id,
                "--execute",
            )
            for result in (daemon, status, repeated):
                self.assertEqual(result.returncode, 0, result.stderr)

            daemon_payload = _first_json_line(daemon.stdout)
            self.assertEqual(
                daemon_payload["leaseReconciliation"]["recoveredCount"],
                1,
            )
            self.assertEqual(daemon_payload["candidateCount"], 0)
            status_payload = json.loads(status.stdout)
            self.assertEqual(status_payload["agentDispatch"]["status"], "completed")
            self.assertEqual(status_payload["agentDispatch"]["attemptCount"], 0)
            self.assertEqual(
                status_payload["agentExchangeRequest"]["responseSummary"],
                "Durable response available after daemon restart.",
            )
            self.assertTrue(status_payload["leaseRecoveryStatus"]["recovered"])
            self.assertIn(
                "lease_recovered",
                [
                    event["stage"]
                    for event in status_payload["statusTimeline"]["events"]
                ],
            )
            repeated_payload = json.loads(repeated.stdout)
            self.assertEqual(repeated_payload["recoveredCount"], 0)
            self.assertEqual(repeated_payload["scannedActiveLeaseCount"], 0)

    def test_python_module_agent_dispatch_daemon_profile_space_path_liveness(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Project With Spaces"
            workspace_id = "workspace-dispatch-daemon-profile"
            source_agent_id = "agent-dispatch-profile-a"
            target_agent_id = "agent-dispatch-profile-b"
            profile = _write_local_runtime_profile(root, workspace_id)
            resolved_profile = str(profile.resolve(strict=False))

            created = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "workspace-create",
                "--workspace-id",
                workspace_id,
                "--display-name",
                "Dispatch Daemon Profile Workspace",
                "--agent-id",
                source_agent_id,
            )
            target = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-create",
                "--agent-id",
                target_agent_id,
                "--name",
                "Dispatch Profile Target",
                "--description",
                "Receives profile daemon work.",
            )
            dispatch = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-dispatch-create",
                "--dispatch-id",
                "dispatch-daemon-profile-1",
                "--exchange-request-id",
                "req-dispatch-daemon-profile-1",
                "--source-agent-id",
                source_agent_id,
                "--target-agent-id",
                target_agent_id,
                "--target-handle-id",
                "missing-target-handle",
                "--target-provider",
                "codex-cli",
                "--request-kind",
                "review",
                "--request-summary",
                "Preview profile daemon handling.",
            )
            daemon = _run_dispatch_daemon_without_runtime_args(
                "--profile",
                str(profile),
                "--once",
                "--dry-run",
                "--read-live-runtime-status",
            )
            daemon_status = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-dispatch-daemon-status",
            )
            dispatch_status = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-dispatch-status",
                "--dispatch-id",
                "dispatch-daemon-profile-1",
            )

            for result in (
                created,
                target,
                dispatch,
                daemon,
                daemon_status,
                dispatch_status,
            ):
                self.assertEqual(result.returncode, 0, result.stderr)

            daemon_payload = _first_json_line(daemon.stdout)
            self.assertEqual(daemon_payload["workspaceId"], workspace_id)
            self.assertEqual(daemon_payload["candidateCount"], 1)
            liveness_payload = json.loads(daemon_status.stdout)
            liveness = liveness_payload["daemonLiveness"]
            self.assertEqual(liveness_payload["state"], "exited")
            self.assertFalse(liveness_payload["dispatcherRunning"])
            self.assertEqual(liveness["profilePath"], resolved_profile)
            self.assertIsNotNone(liveness["pid"])
            self.assertIsNotNone(liveness["startedAt"])
            self.assertIsNotNone(liveness["lastHeartbeatAt"])
            self.assertIsNotNone(liveness["lastPollAt"])
            self.assertEqual(liveness["lastExitReason"], "once_completed")

            dispatch_payload = json.loads(dispatch_status.stdout)
            self.assertEqual(dispatch_payload["dispatcherStatus"]["state"], "exited")
            self.assertEqual(
                dispatch_payload["dispatcherLiveness"]["profilePath"],
                resolved_profile,
            )

    def test_python_module_agent_dispatch_daemon_start_argv_and_failure_status(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Project With Spaces"
            workspace_id = "workspace-dispatch-daemon-start"
            profile = _write_local_runtime_profile(root, workspace_id)
            resolved_profile = str(profile.resolve(strict=False))

            created = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "workspace-create",
                "--workspace-id",
                workspace_id,
                "--display-name",
                "Dispatch Daemon Start Workspace",
                "--agent-id",
                "agent-dispatch-start-a",
            )
            started = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-dispatch-daemon-start",
                "--once",
                "--dry-run",
                "--wait",
                "--codex-git-repo-check-policy",
                "strict",
                "--poll-interval-ms",
                "1",
            )
            daemon_failure = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-dispatch-daemon-start",
                "--once",
                "--dry-run",
                "--wait",
                "--poll-interval-ms",
                "0",
            )
            startup_failure = _run_cli_without_runtime_args(
                "--profile",
                str(profile),
                "agent-dispatch-daemon-start",
                "--once",
                "--dry-run",
                "--wait",
                "--python-executable",
                str(root / "missing python.exe"),
            )

            for result in (created, started, daemon_failure, startup_failure):
                self.assertEqual(result.returncode, 0, result.stderr)

            started_payload = json.loads(started.stdout)
            self.assertEqual(started_payload["launchMode"], "subprocess_argv")
            self.assertFalse(started_payload["usesShell"])
            self.assertEqual(started_payload["processExitCode"], 0)
            self.assertIn(resolved_profile, started_payload["argv"])
            self.assertNotIn("--profile " + resolved_profile, started_payload["argv"])
            self.assertIn("--codex-git-repo-check-policy", started_payload["argv"])
            self.assertIn("strict", started_payload["argv"])
            self.assertIn("--runtime-status-policy", started_payload["argv"])
            policy_index = started_payload["argv"].index("--runtime-status-policy")
            self.assertEqual(started_payload["argv"][policy_index + 1], "auto")
            self.assertEqual(started_payload["daemonStatus"]["state"], "exited")
            self.assertEqual(
                started_payload["daemonStatus"]["daemonLiveness"]["lastExitReason"],
                "once_completed",
            )

            daemon_failure_payload = json.loads(daemon_failure.stdout)
            self.assertEqual(daemon_failure_payload["processExitCode"], 1)
            self.assertEqual(daemon_failure_payload["daemonStatus"]["state"], "failed")
            self.assertIn(
                "pollIntervalMs",
                daemon_failure_payload["daemonStatus"]["daemonLiveness"][
                    "errorSummary"
                ],
            )
            self.assertIsNotNone(
                daemon_failure_payload["daemonStatus"]["daemonLiveness"][
                    "lastErrorAt"
                ]
            )

            startup_failure_payload = json.loads(startup_failure.stdout)
            self.assertFalse(startup_failure_payload["processStarted"])
            self.assertFalse(startup_failure_payload["usesShell"])
            self.assertEqual(
                startup_failure_payload["daemonStatus"]["state"],
                "failed",
            )
            self.assertEqual(
                startup_failure_payload["daemonStatus"]["daemonLiveness"][
                    "lastExitReason"
                ],
                "startup_failed",
            )

    def test_python_module_agent_activation_commands_are_manual_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            created = _run_cli(
                directory,
                "workspace-create",
                "--workspace-id",
                "workspace-agent-activation-cli-1",
                "--agent-id",
                "agent-agent-activation-cli-1",
                "--display-name",
                "Agent Activation CLI Workspace",
            )
            instructions = _run_cli(
                directory,
                "agent-activation-instructions",
                "--workspace-id",
                "workspace-agent-activation-cli-1",
            )
            wake = _run_cli(
                directory,
                "agent-activation-wake",
                "--workspace-id",
                "workspace-agent-activation-cli-1",
                "--agent-id",
                "agent-agent-activation-cli-1",
                "--activation-id",
                "activation-agent-cli-1",
                "--created-by",
                "user",
                "--reason",
                "Allow bounded CLI agent handoff.",
                "--connection-surface",
                "desktop_app_cli_capable",
                "--max-writes",
                "1",
                "--max-agent-to-agent-turns",
                "0",
            )
            status = _run_cli(
                directory,
                "agent-activation-status",
                "--workspace-id",
                "workspace-agent-activation-cli-1",
                "--agent-id",
                "agent-agent-activation-cli-1",
            )
            context = _run_cli(
                directory,
                "context-append",
                "--workspace-id",
                "workspace-agent-activation-cli-1",
                "--summary",
                "CLI agent writes a bounded proposal.",
                "--update-kind",
                "agent_message",
                "--exchange-attribution-json",
                json.dumps(
                    {
                        "sourceType": "agent_context_update",
                        "authorType": "agent",
                        "contributionKind": "proposal",
                        "authorAgentId": "agent-agent-activation-cli-1",
                        "linkedActivationId": "activation-agent-cli-1",
                    }
                ),
            )
            revoke = _run_cli(
                directory,
                "agent-activation-revoke",
                "--workspace-id",
                "workspace-agent-activation-cli-1",
                "--agent-id",
                "agent-agent-activation-cli-1",
                "--activation-id",
                "activation-agent-cli-1",
                "--revoked-by",
                "user",
                "--reason",
                "End CLI handoff.",
            )
            blocked = _run_cli(
                directory,
                "context-append",
                "--workspace-id",
                "workspace-agent-activation-cli-1",
                "--summary",
                "CLI agent tries to write after revoke.",
                "--update-kind",
                "agent_message",
                "--exchange-attribution-json",
                json.dumps(
                    {
                        "sourceType": "agent_context_update",
                        "authorType": "agent",
                        "contributionKind": "proposal",
                        "authorAgentId": "agent-agent-activation-cli-1",
                        "linkedActivationId": "activation-agent-cli-1",
                    }
                ),
            )

            for result in (created, instructions, wake, status, context, revoke):
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(blocked.returncode, 1)
            self.assertNotIn("Traceback", blocked.stderr)

            interface = json.loads(instructions.stdout)["agentActivationInterface"]
            self.assertFalse(interface["safeModeDefaults"]["realRuntimeConnected"])
            self.assertFalse(interface["safeModeDefaults"]["agentAutoWakeEnabled"])
            self.assertEqual(interface["exchangeLinkKey"], "linkedActivationId")

            woken = json.loads(wake.stdout)["agentActivation"]
            self.assertEqual(woken["activationId"], "activation-agent-cli-1")
            self.assertEqual(woken["connectionSurface"], "desktop_app_cli_capable")
            self.assertTrue(woken["requiresManualUserWake"])
            self.assertEqual(
                json.loads(status.stdout)["agentActivation"]["state"],
                "awakened",
            )
            self.assertEqual(
                json.loads(context.stdout)["contextUpdate"]["metadata"]["agentExchange"][
                    "linkedActivationId"
                ],
                "activation-agent-cli-1",
            )
            self.assertEqual(json.loads(revoke.stdout)["agentActivation"]["state"], "revoked")
            self.assertIn("agent activation is not active", blocked.stderr)

    def test_python_module_delegated_wake_grant_commands_are_one_time_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _run_cli(
                directory,
                "workspace-create",
                "--workspace-id",
                "workspace-delegated-wake-cli-1",
                "--agent-id",
                "agent-src-cli",
                "--display-name",
                "Delegated Wake CLI Workspace",
            )
            _run_cli(
                directory,
                "agent-create",
                "--workspace-id",
                "workspace-delegated-wake-cli-1",
                "--agent-id",
                "agent-tgt-cli",
                "--name",
                "Target Agent",
                "--description",
                "Target agent for delegated wake.",
            )
            future = (
                datetime.now(timezone.utc) + timedelta(hours=1)
            ).isoformat()
            instructions = _run_cli(
                directory,
                "agent-delegated-wake-grant-instructions",
                "--workspace-id",
                "workspace-delegated-wake-cli-1",
            )
            created = _run_cli(
                directory,
                "agent-delegated-wake-grant-create",
                "--workspace-id",
                "workspace-delegated-wake-cli-1",
                "--delegated-wake-grant-id",
                "dw-cli-1",
                "--source-agent-id",
                "agent-src-cli",
                "--target-agent-id",
                "agent-tgt-cli",
                "--created-by",
                "user",
                "--reason",
                "Allow one bounded delegated wake.",
                "--expires-at",
                future,
                "--target-max-writes",
                "1",
            )
            wrong_source = _run_cli(
                directory,
                "agent-delegated-wake-grant-consume",
                "--workspace-id",
                "workspace-delegated-wake-cli-1",
                "--delegated-wake-grant-id",
                "dw-cli-1",
                "--consuming-agent-id",
                "agent-tgt-cli",
            )
            consumed = _run_cli(
                directory,
                "agent-delegated-wake-grant-consume",
                "--workspace-id",
                "workspace-delegated-wake-cli-1",
                "--delegated-wake-grant-id",
                "dw-cli-1",
                "--consuming-agent-id",
                "agent-src-cli",
            )
            second_consume = _run_cli(
                directory,
                "agent-delegated-wake-grant-consume",
                "--workspace-id",
                "workspace-delegated-wake-cli-1",
                "--delegated-wake-grant-id",
                "dw-cli-1",
                "--consuming-agent-id",
                "agent-src-cli",
            )
            status = _run_cli(
                directory,
                "agent-delegated-wake-grant-status",
                "--workspace-id",
                "workspace-delegated-wake-cli-1",
                "--delegated-wake-grant-id",
                "dw-cli-1",
            )

            self.assertEqual(instructions.returncode, 0, instructions.stderr)
            self.assertEqual(created.returncode, 0, created.stderr)
            self.assertEqual(wrong_source.returncode, 1)
            self.assertEqual(consumed.returncode, 0, consumed.stderr)
            self.assertEqual(second_consume.returncode, 1)
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertNotIn("Traceback", wrong_source.stderr)
            self.assertNotIn("Traceback", second_consume.stderr)

            interface = json.loads(instructions.stdout)[
                "delegatedWakeInterface"
            ]
            self.assertEqual(interface["schema"], "delegated_wake_interface.v1")
            self.assertFalse(interface["defaults"]["realRuntimeConnected"])
            self.assertFalse(interface["defaults"]["canDelegateFurther"])

            grant = json.loads(created.stdout)["delegatedWakeGrant"]
            self.assertEqual(grant["state"], "pending")
            self.assertEqual(grant["maxUses"], 1)
            self.assertFalse(grant["canDelegateFurther"])

            consumed_payload = json.loads(consumed.stdout)
            self.assertTrue(consumed_payload["consumed"])
            self.assertEqual(
                consumed_payload["delegatedWakeGrant"]["state"], "consumed"
            )
            target_activation = consumed_payload["targetActivation"]
            self.assertEqual(
                target_activation["metadata"]["delegatedWakeGrantId"], "dw-cli-1"
            )
            self.assertEqual(
                target_activation["metadata"]["sourceAgentId"], "agent-src-cli"
            )
            self.assertEqual(
                target_activation["metadata"]["delegatedByUser"], "user"
            )

            self.assertIn("source_agent_mismatch", wrong_source.stderr)
            self.assertIn("grant_already_consumed", second_consume.stderr)
            self.assertEqual(
                json.loads(status.stdout)["delegatedWakeGrant"]["state"],
                "consumed",
            )

    def test_python_module_project_directory_coordination_commands_are_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _run_cli(
                directory,
                "workspace-create",
                "--workspace-id",
                "workspace-directory-cli-1",
                "--agent-id",
                "agent-directory-src",
                "--display-name",
                "Directory CLI Workspace",
            )
            _run_cli(
                directory,
                "agent-create",
                "--workspace-id",
                "workspace-directory-cli-1",
                "--agent-id",
                "agent-directory-tgt",
                "--name",
                "Directory Target",
                "--description",
                "Second agent for directory coordination.",
            )

            instructions = _run_cli(
                directory,
                "project-directory-coordination-instructions",
                "--workspace-id",
                "workspace-directory-cli-1",
            )
            first = _run_cli(
                directory,
                "project-directory-coordination-declare",
                "--workspace-id",
                "workspace-directory-cli-1",
                "--directory-coordination-id",
                "coord-cli-src",
                "--declared-agent-id",
                "agent-directory-src",
                "--project-root",
                "X:/fixture/workspace-directory-cli-1",
                "--git-repository-id",
                "repo-directory-cli",
                "--declared-path-scopes-json",
                '["src"]',
                "--directory-access-intent",
                "editing",
                "--last-known-git-head",
                "abc123",
                "--last-known-branch",
                "main",
                "--dirty-state",
                "dirty_reported",
                "--uncommitted-change-summary",
                "Editing src.",
            )
            second = _run_cli(
                directory,
                "project-directory-coordination-declare",
                "--workspace-id",
                "workspace-directory-cli-1",
                "--directory-coordination-id",
                "coord-cli-tgt",
                "--declared-agent-id",
                "agent-directory-tgt",
                "--project-root",
                "X:/fixture/workspace-directory-cli-1",
                "--git-repository-id",
                "repo-directory-cli",
                "--declared-path-scopes-json",
                '["src/agent_os"]',
                "--directory-access-intent",
                "read_only",
            )
            first_status = _run_cli(
                directory,
                "project-directory-coordination-status",
                "--workspace-id",
                "workspace-directory-cli-1",
                "--directory-coordination-id",
                "coord-cli-src",
            )
            completed = _run_cli(
                directory,
                "project-directory-coordination-complete",
                "--workspace-id",
                "workspace-directory-cli-1",
                "--directory-coordination-id",
                "coord-cli-src",
                "--dirty-state",
                "clean",
                "--test-summary",
                "CLI focused test passed.",
                "--handoff-note",
                "Ready for review.",
            )
            target_status = _run_cli(
                directory,
                "project-directory-coordination-status",
                "--workspace-id",
                "workspace-directory-cli-1",
                "--directory-coordination-id",
                "coord-cli-tgt",
            )
            listed = _run_cli(
                directory,
                "project-directory-coordination-status",
                "--workspace-id",
                "workspace-directory-cli-1",
                "--list",
            )

            for result in (
                instructions,
                first,
                second,
                first_status,
                completed,
                target_status,
                listed,
            ):
                self.assertEqual(result.returncode, 0, result.stderr)

            interface = json.loads(instructions.stdout)[
                "projectDirectoryCoordinationInterface"
            ]
            self.assertEqual(
                interface["schema"],
                "project_directory_coordination_interface.v1",
            )
            self.assertTrue(interface["defaults"]["notSecurityBoundary"])
            self.assertFalse(interface["defaults"]["gitOperationExecuted"])

            first_record = json.loads(first.stdout)["projectDirectoryCoordination"]
            second_record = json.loads(second.stdout)["projectDirectoryCoordination"]
            first_status_record = json.loads(first_status.stdout)[
                "projectDirectoryCoordination"
            ]
            completed_record = json.loads(completed.stdout)[
                "projectDirectoryCoordination"
            ]
            target_status_record = json.loads(target_status.stdout)[
                "projectDirectoryCoordination"
            ]
            listed_records = json.loads(listed.stdout)[
                "projectDirectoryCoordinations"
            ]

            self.assertEqual(first_record["directoryAccessIntent"], "editing")
            self.assertTrue(first_record["notSecurityBoundary"])
            self.assertTrue(first_record["advisoryOnly"])
            self.assertFalse(first_record["fileBodiesRead"])
            self.assertFalse(first_record["gitOperationExecuted"])
            self.assertEqual(second_record["overlapStatus"], "shared_write_risk")
            self.assertEqual(first_status_record["overlapStatus"], "shared_write_risk")
            self.assertEqual(
                completed_record["directoryAccessIntent"],
                "done_reported",
            )
            self.assertFalse(completed_record["gitOperationExecuted"])
            self.assertEqual(target_status_record["overlapStatus"], "none")
            self.assertEqual(
                [item["directoryCoordinationId"] for item in listed_records],
                ["coord-cli-src", "coord-cli-tgt"],
            )

    def test_python_module_invoke_can_append_conversation_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            created = _run_cli(
                directory,
                "workspace-create",
                "--workspace-id",
                "workspace-invoke-conversation-cli-1",
                "--agent-id",
                "agent-invoke-conversation-cli-1",
                "--display-name",
                "Invocation Conversation CLI Workspace",
            )
            conversation = _run_cli(
                directory,
                "conversation-create",
                "--workspace-id",
                "workspace-invoke-conversation-cli-1",
                "--conversation-id",
                "conversation-invoke-cli-1",
                "--agent-id",
                "agent-invoke-conversation-cli-1",
                "--title",
                "Invocation thread",
            )
            invoked = _run_cli(
                directory,
                "invoke",
                "--workspace-id",
                "workspace-invoke-conversation-cli-1",
                "--agent-id",
                "agent-invoke-conversation-cli-1",
                "--instruction",
                "Capture this invocation in a local conversation.",
                "--invocation-id",
                "invoke-conversation-cli-1",
                "--session-id",
                "session-conversation-cli-2",
                "--conversation-id",
                "conversation-invoke-cli-1",
            )
            messages = _run_cli(
                directory,
                "conversation-messages",
                "--workspace-id",
                "workspace-invoke-conversation-cli-1",
                "--conversation-id",
                "conversation-invoke-cli-1",
            )

            for result in (created, conversation, invoked, messages):
                self.assertEqual(result.returncode, 0, result.stderr)

            invoked_payload = json.loads(invoked.stdout)
            messages_payload = json.loads(messages.stdout)
            self.assertEqual(
                invoked_payload["conversation"]["conversationId"],
                "conversation-invoke-cli-1",
            )
            self.assertEqual(
                [message["role"] for message in invoked_payload["conversationMessages"]],
                ["user", "assistant"],
            )
            self.assertEqual(
                [message["role"] for message in messages_payload["messages"]],
                ["user", "assistant"],
            )
            self.assertEqual(
                messages_payload["messages"][0]["contextUpdateId"],
                invoked_payload["userContextUpdate"]["updateId"],
            )
            self.assertEqual(
                [message["invocationId"] for message in messages_payload["messages"]],
                ["invoke-conversation-cli-1", "invoke-conversation-cli-1"],
            )

    def test_python_module_invoke_json_can_use_openai_compatible_provider_mode(
        self,
    ) -> None:
        env_var = "AGENT_OS_OPENAI_COMPAT_CLI_TEST_CREDENTIAL"
        with tempfile.TemporaryDirectory() as directory:
            with _FakeOpenAICompatibleServer(
                response_content="CLI fake provider response.",
            ) as server:
                created = _run_cli(
                    directory,
                    "workspace-create",
                    "--workspace-id",
                    "workspace-openai-cli-1",
                    "--display-name",
                    "OpenAI Compatible CLI Workspace",
                )
                invoked = _run_cli(
                    directory,
                    "--agent-adapter-mode",
                    "openai-compatible-provider",
                    "--openai-compatible-base-url",
                    server.url,
                    "--openai-compatible-model",
                    "fake-chat-model",
                    "--openai-compatible-api-key-env-var",
                    env_var,
                    "--openai-compatible-temperature",
                    "0.1",
                    "--openai-compatible-max-tokens",
                    "24",
                    "--openai-compatible-reasoning-effort",
                    "high",
                    "--openai-compatible-thinking-type",
                    "disabled",
                    "invoke-json",
                    "--payload-json",
                    json.dumps(
                        {
                            "workspaceId": "workspace-openai-cli-1",
                            "agentId": "agent-workspace-openai-cli-1",
                            "instruction": "Run provider-backed CLI invocation.",
                            "invocationId": "invoke-openai-cli-1",
                            "sessionId": "session-openai-cli-1",
                        }
                    ),
                    extra_env={env_var: uuid4().hex},
                )

            self.assertEqual(created.returncode, 0, created.stderr)
            self.assertEqual(invoked.returncode, 0, invoked.stderr)
            payload = json.loads(invoked.stdout)
            self.assertTrue(payload["modelInvoked"])
            self.assertFalse(payload["deterministicPlaceholder"])
            self.assertEqual(
                payload["invocationResult"]["outputText"],
                "CLI fake provider response.",
            )
            self.assertEqual(
                payload["invocationResult"]["outputPayload"]["provider_name"],
                "openai-compatible",
            )
            self.assertEqual(server.requests[0]["body"]["temperature"], 0.1)
            self.assertEqual(server.requests[0]["body"]["max_tokens"], 24)
            self.assertEqual(server.requests[0]["body"]["reasoning_effort"], "high")
            self.assertEqual(
                server.requests[0]["body"]["thinking"],
                {"type": "disabled"},
            )

    def test_python_module_invoke_json_can_use_provider_api_shape_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with _FakeOllamaServer(
                response_content="CLI fake Ollama response.",
            ) as server:
                created = _run_cli(
                    directory,
                    "workspace-create",
                    "--workspace-id",
                    "workspace-provider-shape-cli-1",
                    "--display-name",
                    "Provider Shape CLI Workspace",
                )
                invoked = _run_cli(
                    directory,
                    "--agent-adapter-mode",
                    "provider-api-shape",
                    "--provider-api-shape",
                    "ollama-chat",
                    "--provider-base-url",
                    server.url,
                    "--provider-model",
                    "llama-test-model",
                    "--provider-temperature",
                    "0.2",
                    "--provider-max-tokens",
                    "25",
                    "invoke-json",
                    "--payload-json",
                    json.dumps(
                        {
                            "workspaceId": "workspace-provider-shape-cli-1",
                            "agentId": "agent-workspace-provider-shape-cli-1",
                            "instruction": "Run provider-shape CLI invocation.",
                            "invocationId": "invoke-provider-shape-cli-1",
                            "sessionId": "session-provider-shape-cli-1",
                        }
                    ),
                )

            self.assertEqual(created.returncode, 0, created.stderr)
            self.assertEqual(invoked.returncode, 0, invoked.stderr)
            payload = json.loads(invoked.stdout)
            self.assertTrue(payload["modelInvoked"])
            self.assertFalse(payload["deterministicPlaceholder"])
            self.assertEqual(
                payload["invocationResult"]["outputText"],
                "CLI fake Ollama response.",
            )
            self.assertEqual(
                payload["invocationResult"]["outputPayload"]["provider_name"],
                "ollama",
            )
            self.assertEqual(server.requests[0]["body"]["options"]["temperature"], 0.2)
            self.assertEqual(server.requests[0]["body"]["options"]["num_predict"], 25)

    def test_python_module_invoke_json_can_use_openai_responses_shape_mode(
        self,
    ) -> None:
        env_var = "AGENT_OS_OPENAI_RESPONSES_CLI_TEST_CREDENTIAL"
        with tempfile.TemporaryDirectory() as directory:
            with _FakeResponsesServer(
                response_content="CLI fake Responses response.",
            ) as server:
                created = _run_cli(
                    directory,
                    "workspace-create",
                    "--workspace-id",
                    "workspace-responses-shape-cli-1",
                    "--display-name",
                    "Responses Shape CLI Workspace",
                )
                invoked = _run_cli(
                    directory,
                    "--agent-adapter-mode",
                    "provider-api-shape",
                    "--provider-api-shape",
                    "openai-responses",
                    "--provider-base-url",
                    server.url,
                    "--provider-model",
                    "responses-test-model",
                    "--provider-name",
                    "openai-responses",
                    "--provider-api-key-env-var",
                    env_var,
                    "--provider-max-tokens",
                    "23",
                    "--provider-input-mode",
                    "plain_text",
                    "--provider-user-agent",
                    "AgentChatCLI/14.2",
                    "invoke-json",
                    "--payload-json",
                    json.dumps(
                        {
                            "workspaceId": "workspace-responses-shape-cli-1",
                            "agentId": "agent-workspace-responses-shape-cli-1",
                            "instruction": "Run Responses shape CLI invocation.",
                            "invocationId": "invoke-responses-shape-cli-1",
                            "sessionId": "session-responses-shape-cli-1",
                        }
                    ),
                    extra_env={env_var: uuid4().hex},
                )

            self.assertEqual(created.returncode, 0, created.stderr)
            self.assertEqual(invoked.returncode, 0, invoked.stderr)
            payload = json.loads(invoked.stdout)
            self.assertTrue(payload["modelInvoked"])
            self.assertFalse(payload["deterministicPlaceholder"])
            self.assertEqual(
                payload["invocationResult"]["outputText"],
                "CLI fake Responses response.",
            )
            self.assertEqual(
                payload["invocationResult"]["outputPayload"]["provider_name"],
                "openai-responses",
            )
            self.assertEqual(server.requests[0]["path"], "/v1/responses")
            self.assertEqual(
                server.requests[0]["body"]["max_output_tokens"],
                23,
            )
            self.assertEqual(
                server.requests[0]["body"]["input"],
                "Run Responses shape CLI invocation.",
            )
            self.assertEqual(
                server.requests[0]["user-agent"],
                "AgentChatCLI/14.2",
            )
            self.assertNotIn("max_tokens", server.requests[0]["body"])
            self.assertNotIn("input_mode", server.requests[0]["body"])
            self.assertNotIn("provider_user_agent", server.requests[0]["body"])

    def test_python_module_agent_create_profiles_resolve_provider_invocation(
        self,
    ) -> None:
        env_var = "AGENT_OS_OPENAI_COMPAT_PROFILE_CLI_TEST_CREDENTIAL"
        with tempfile.TemporaryDirectory() as directory:
            with _FakeOpenAICompatibleServer(
                response_content="CLI fake provider profile response.",
            ) as server:
                created = _run_cli(
                    directory,
                    "workspace-create",
                    "--workspace-id",
                    "workspace-profile-cli-1",
                    "--display-name",
                    "Profile CLI Workspace",
                )
                reviewer = _run_cli(
                    directory,
                    "agent-create",
                    "--workspace-id",
                    "workspace-profile-cli-1",
                    "--agent-id",
                    "agent-reviewer-cli-1",
                    "--name",
                    "Reviewer",
                    "--description",
                    "Reviews plans.",
                    "--default-model",
                    "fake-chat-model",
                    "--runtime-config-json",
                    json.dumps(
                        {
                            "profile": {
                                "profileName": "reviewer",
                                "roleName": "reviewer",
                                "systemPrompt": "Review plans for risk.",
                                "providerName": "openai-compatible",
                                "modelName": "fake-chat-model",
                                "generationOptions": {
                                    "temperature": 0,
                                    "maxTokens": 31,
                                },
                                "bindingId": "binding-reviewer-cli-1",
                            }
                        }
                    ),
                )
                planner = _run_cli(
                    directory,
                    "agent-create",
                    "--workspace-id",
                    "workspace-profile-cli-1",
                    "--agent-id",
                    "agent-planner-cli-1",
                    "--name",
                    "Planner",
                    "--description",
                    "Plans tasks.",
                    "--default-model",
                    "fake-chat-model",
                    "--runtime-config-json",
                    json.dumps(
                        {
                            "profile": {
                                "profileName": "planner",
                                "roleName": "planner",
                                "systemPrompt": "Plan work in bounded steps.",
                                "providerName": "openai-compatible",
                                "modelName": "fake-chat-model",
                                "generationOptions": {
                                    "temperature": 0.7,
                                    "maxTokens": 41,
                                },
                                "bindingId": "binding-planner-cli-1",
                            }
                        }
                    ),
                )
                reviewer_invocation = _run_cli(
                    directory,
                    "--agent-adapter-mode",
                    "openai-compatible-provider",
                    "--openai-compatible-base-url",
                    server.url,
                    "--openai-compatible-model",
                    "fake-chat-model",
                    "--openai-compatible-api-key-env-var",
                    env_var,
                    "invoke-json",
                    "--payload-json",
                    json.dumps(
                        {
                            "workspaceId": "workspace-profile-cli-1",
                            "agentId": "agent-reviewer-cli-1",
                            "instruction": "Review this plan.",
                            "invocationId": "invoke-reviewer-cli-1",
                            "sessionId": "session-profile-cli-1",
                        }
                    ),
                    extra_env={env_var: uuid4().hex},
                )
                planner_invocation = _run_cli(
                    directory,
                    "--agent-adapter-mode",
                    "openai-compatible-provider",
                    "--openai-compatible-base-url",
                    server.url,
                    "--openai-compatible-model",
                    "fake-chat-model",
                    "--openai-compatible-api-key-env-var",
                    env_var,
                    "invoke-json",
                    "--payload-json",
                    json.dumps(
                        {
                            "workspaceId": "workspace-profile-cli-1",
                            "agentId": "agent-planner-cli-1",
                            "instruction": "Plan the work.",
                            "invocationId": "invoke-planner-cli-1",
                            "sessionId": "session-profile-cli-1",
                        }
                    ),
                    extra_env={env_var: uuid4().hex},
                )

            for result in (
                created,
                reviewer,
                planner,
                reviewer_invocation,
                planner_invocation,
            ):
                self.assertEqual(result.returncode, 0, result.stderr)

            reviewer_payload = json.loads(reviewer_invocation.stdout)
            planner_payload = json.loads(planner_invocation.stdout)
            self.assertEqual(server.requests[0]["body"]["temperature"], 0)
            self.assertEqual(server.requests[0]["body"]["max_tokens"], 31)
            self.assertEqual(server.requests[1]["body"]["temperature"], 0.7)
            self.assertEqual(server.requests[1]["body"]["max_tokens"], 41)
            self.assertEqual(
                server.requests[0]["body"]["messages"][0]["content"],
                "Review plans for risk.",
            )
            self.assertEqual(
                server.requests[1]["body"]["messages"][0]["content"],
                "Plan work in bounded steps.",
            )
            self.assertEqual(
                reviewer_payload["invocationResult"]["outputPayload"]["runtime_profile"][
                    "profile_name"
                ],
                "reviewer",
            )
            self.assertEqual(
                reviewer_payload["invocationResult"]["metadata"]["runtime_profile_name"],
                "reviewer",
            )
            self.assertEqual(
                planner_payload["invocationResult"]["outputPayload"]["runtime_profile"][
                    "profile_name"
                ],
                "planner",
            )

    def test_python_module_runtime_error_outputs_json_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = _run_cli(
                directory,
                "workspace-open",
                "--workspace-id",
                "workspace-missing",
            )

            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertNotIn("Traceback", result.stderr)
            payload = json.loads(result.stderr)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["error"]["type"], "ValueError")
            self.assertIn("workspace state not found", payload["error"]["message"])

    def test_python_module_runtime_missing_plugins_error_points_to_profile_options(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = _run_cli_without_runtime_args(
                "workspace-open",
                "--workspace-id",
                "workspace-missing",
                extra_env={
                    "AGENT_OS_DATABASE": str(root / "platform.sqlite3"),
                    "AGENT_OS_WORKSPACE_ROOT": str(root / "workspace"),
                },
            )

            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertNotIn("Traceback", result.stderr)
            payload = json.loads(result.stderr)
            message = payload["error"]["message"]
            self.assertEqual(payload["error"]["type"], "ValueError")
            self.assertIn("plugins_directory is required", message)
            self.assertIn("--plugins-directory", message)
            self.assertIn("--profile", message)
            self.assertIn("AGENT_OS_LOCAL_RUNTIME_PROFILE", message)
            self.assertIn("AGENT_OS_PLUGINS_DIRECTORY", message)
            self.assertIn("AGENT_OS_PLUGINS_DIR", message)
            self.assertIn("pluginsDirectory", message)


def _run_cli(
    directory: str,
    *args: str,
    extra_env: Mapping[str, str] | None = None,
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


def _run_cli_without_runtime_args(
    *args: str,
    extra_env: Mapping[str, str] | None = None,
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


def _run_wake_daemon(
    directory: str,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_SRC)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_os.agent_wake_daemon",
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


def _run_dispatch_daemon(
    directory: str,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_SRC)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_os.agent_dispatch_daemon",
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


def _run_dispatch_daemon_without_runtime_args(
    *args: str,
    extra_env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_SRC)
    if extra_env is not None:
        environment.update(extra_env)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_os.agent_dispatch_daemon",
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


def _write_local_runtime_profile(root: Path, workspace_id: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    profile = root / "agent os profile.json"
    profile.write_text(
        json.dumps(
            {
                "localRuntime": {
                    "workspaceId": workspace_id,
                    "databasePath": str(root / "platform.sqlite3"),
                    "workspaceRoot": str(root / "workspace root"),
                    "pluginsDirectory": str(root / "plugins directory"),
                }
            }
        ),
        encoding="utf-8",
    )
    return profile


def _first_json_line(stdout: str) -> dict[str, Any]:
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("{"):
            parsed = json.loads(stripped)
            if not isinstance(parsed, dict):
                raise AssertionError("expected JSON object line")
            return parsed
    raise AssertionError("no JSON object line found")


class _FakeOpenAICompatibleServer:
    def __init__(self, *, response_content: str) -> None:
        self.response_content = response_content
        self.requests: list[dict[str, Any]] = []

    def __enter__(self) -> "_FakeOpenAICompatibleServer":
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenAIHandler)
        self._server.fake = self
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
        )
        self._thread.start()
        port = self._server.server_address[1]
        self.url = f"http://127.0.0.1:{port}/v1"
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)


class _FakeOpenAIHandler(BaseHTTPRequestHandler):
    server: ThreadingHTTPServer

    def do_POST(self) -> None:
        fake: _FakeOpenAICompatibleServer = self.server.fake
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        fake.requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "user-agent": self.headers.get("User-Agent"),
                "body": body,
            }
        )
        response = {
            "model": body["model"],
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": fake.response_content,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        }
        data = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, _format: str, *_args: object) -> None:
        return None


class _FakeOllamaServer:
    def __init__(self, *, response_content: str) -> None:
        self.response_content = response_content
        self.requests: list[dict[str, Any]] = []

    def __enter__(self) -> "_FakeOllamaServer":
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllamaHandler)
        self._server.fake = self
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
        )
        self._thread.start()
        port = self._server.server_address[1]
        self.url = f"http://127.0.0.1:{port}"
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)


class _FakeOllamaHandler(BaseHTTPRequestHandler):
    server: ThreadingHTTPServer

    def do_POST(self) -> None:
        fake: _FakeOllamaServer = self.server.fake
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        fake.requests.append(
            {
                "path": self.path,
                "body": body,
            }
        )
        response = {
            "model": body["model"],
            "message": {
                "role": "assistant",
                "content": fake.response_content,
            },
            "done_reason": "stop",
        }
        data = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, _format: str, *_args: object) -> None:
        return None


class _FakeResponsesServer:
    def __init__(self, *, response_content: str) -> None:
        self.response_content = response_content
        self.requests: list[dict[str, Any]] = []

    def __enter__(self) -> "_FakeResponsesServer":
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeResponsesHandler)
        self._server.fake = self
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
        )
        self._thread.start()
        port = self._server.server_address[1]
        self.url = f"http://127.0.0.1:{port}/v1"
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)


class _FakeResponsesHandler(BaseHTTPRequestHandler):
    server: ThreadingHTTPServer

    def do_POST(self) -> None:
        fake: _FakeResponsesServer = self.server.fake
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        fake.requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "user-agent": self.headers.get("User-Agent"),
                "body": body,
            }
        )
        response = {
            "id": "resp_cli_fake",
            "model": body["model"],
            "status": "completed",
            "output_text": fake.response_content,
            "usage": {
                "input_tokens": 1,
                "output_tokens": 1,
                "total_tokens": 2,
            },
        }
        data = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, _format: str, *_args: object) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
