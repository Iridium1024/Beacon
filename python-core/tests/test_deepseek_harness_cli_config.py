from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from agent_os.local_runtime import (
    _build_parser,
    _deepseek_harness_control_config,
    _dispatch,
)
from agent_os.infrastructure.config import LocalPlatformSettings


class DeepSeekHarnessCliConfigTests(unittest.TestCase):
    def test_dsh_alias_dispatches_new_and_existing_session_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parser = _build_parser()
            common = [
                "--workspace-id",
                "workspace-dsh",
                "--agent",
                "dsh-agent",
                "--provider",
                "dsh",
                "--dsh-carrier",
                "node",
                "--dsh-executable",
                str(root / "node.exe"),
                "--dsh-package-root",
                str(root / "carrier"),
                "--dsh-cordis-config",
                str(root / "carrier" / "cordis.yml"),
                "--dsh-runtime-home",
                str(root / "runtime-home"),
                "--dsh-state-root",
                str(root / "state"),
                "--dsh-session-root",
                str(root / "sessions"),
                "--dsh-model-provider",
                "fake-provider",
                "--dsh-model",
                "fake-model",
            ]
            application = Mock()
            application.settings = LocalPlatformSettings(
                database=str(root / "platform.sqlite3"),
                workspace_root=str(root / "workspace"),
                plugins_directory=str(root / "plugins"),
            )
            application.join_deepseek_harness_agent.side_effect = (
                {"schema": "deepseek_harness_agent_join.v1", "ok": True},
                {"schema": "deepseek_harness_agent_join.v1", "ok": True},
            )

            created = _dispatch(
                application,
                parser.parse_args(
                    ["agent-join", *common, "--new-session", "--cwd", str(root)]
                ),
            )
            resumed = _dispatch(
                application,
                parser.parse_args(
                    ["agent-join", *common, "--session", "native-session-01"]
                ),
            )

            self.assertTrue(created["ok"])
            self.assertTrue(resumed["ok"])
            create_call, resume_call = (
                call.kwargs
                for call in application.join_deepseek_harness_agent.call_args_list
            )
            self.assertIsNone(create_call["session_id"])
            self.assertEqual(create_call["cwd"], str(root))
            self.assertEqual(resume_call["session_id"], "native-session-01")
            self.assertIsNone(resume_call["cwd"])

    def test_new_session_join_and_lifecycle_commands_are_explicit(self) -> None:
        parser = _build_parser()
        joined = parser.parse_args(
            [
                "agent-join",
                "--workspace-id",
                "workspace-dsh",
                "--agent",
                "dsh-agent",
                "--provider",
                "dsh",
                "--new-session",
                "--cwd",
                ".",
            ]
        )
        self.assertTrue(joined.new_session)
        self.assertIsNone(joined.session_id)
        self.assertEqual(joined.provider, "dsh")

        existing = parser.parse_args(
            [
                "agent-join",
                "--workspace-id",
                "workspace-dsh",
                "--agent",
                "dsh-agent",
                "--provider",
                "deepseek_harness",
                "--session",
                "native-session-01",
                "--dsh-session-root",
                "C:/isolated/sessions",
                "--dsh-session-compression",
                "none",
            ]
        )
        self.assertEqual(existing.provider, "deepseek_harness")
        self.assertEqual(existing.session_id, "native-session-01")
        self.assertFalse(existing.new_session)
        self.assertEqual(existing.dsh_session_compression, "none")

        stopped = parser.parse_args(
            [
                "deepseek-harness-runtime-stop",
                "--workspace-id",
                "workspace-dsh",
                "--handle-id",
                "dsh-handle",
                "--acknowledge-continuity-loss",
            ]
        )
        recreated = parser.parse_args(
            [
                "deepseek-harness-runtime-recreate",
                "--workspace-id",
                "workspace-dsh",
                "--handle-id",
                "dsh-handle",
                "--acknowledge-continuity-loss",
            ]
        )
        self.assertTrue(stopped.acknowledge_runtime_stop)
        self.assertTrue(recreated.acknowledge_continuity_loss)

        resumed = parser.parse_args(
            [
                "deepseek-harness-runtime-resume",
                "--workspace-id",
                "workspace-dsh",
                "--handle-id",
                "dsh-handle",
                "--acknowledge-ambiguous-delivery",
            ]
        )
        self.assertTrue(resumed.acknowledge_ambiguous_delivery)

    def test_profile_config_keeps_agent_platform_and_model_preset_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parser = _build_parser()
            args = parser.parse_args(
                [
                    "agent-join",
                    "--workspace-id",
                    "workspace-dsh",
                    "--agent",
                    "dsh-agent",
                    "--provider",
                    "deepseek_harness",
                    "--new-session",
                    "--cwd",
                    str(root),
                ]
            )
            profile = {
                "deepseekHarnessControl": {
                    "enabled": False,
                    "activationBackend": "managed_runtime",
                    "carrier": "node",
                    "executablePath": "C:/Program Files/nodejs/node.exe",
                    "packageRoot": str(root / "carrier"),
                    "cordisConfigPath": str(root / "carrier" / "cordis.yml"),
                    "runtimeHome": str(root / "runtime-home"),
                    "stateRoot": str(root / "state"),
                    "sessionRoot": str(root / "sessions"),
                    "modelProvider": "deepseek",
                    "model": "deepseek-chat",
                    "replyWritebackMode": "explicit_only",
                }
            }
            config = _deepseek_harness_control_config(
                args,
                profile,
                settings=LocalPlatformSettings(
                    database=str(root / "platform.sqlite3"),
                    workspace_root=str(root / "workspace"),
                    plugins_directory=str(root / "plugins"),
                ),
                require_runtime_paths=True,
            )
            self.assertEqual(args.provider, "deepseek_harness")
            self.assertEqual(config["modelProvider"], "deepseek")
            self.assertEqual(config["activationBackend"], "managed_runtime")
            self.assertTrue(config["existingSessionImport"])
            self.assertTrue(config["coldResume"])


if __name__ == "__main__":
    unittest.main()
