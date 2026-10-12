from __future__ import annotations

import unittest

from agent_os.application.services.claude_session_control import (
    ClaudeActivationBackend,
    ClaudeReplyWritebackMode,
    resolve_claude_control_config,
)


class ClaudeSessionControlTests(unittest.TestCase):
    def test_backend_specific_defaults_preserve_cli_compatibility(self) -> None:
        cli = resolve_claude_control_config({})
        sdk = resolve_claude_control_config({}, activation_backend="agent_sdk")

        self.assertEqual(cli.activation_backend.value, "cli")
        self.assertEqual(cli.reply_writeback_mode.value, "provider_final_capture")
        self.assertEqual(cli.reply_writeback_mode.source, "default_for_cli_compatibility")
        self.assertEqual(sdk.activation_backend.value, "agent_sdk")
        self.assertEqual(sdk.reply_writeback_mode.value, "explicit_only")
        self.assertEqual(sdk.reply_writeback_mode.source, "default_for_agent_sdk")

    def test_explicit_values_override_nested_and_flat_aliases(self) -> None:
        config = resolve_claude_control_config(
            {
                "claudeControl": {
                    "activationBackend": "agent_sdk",
                    "replyWritebackMode": "explicit_only",
                },
                "claudeActivationBackend": "cli",
                "claudeReplyWritebackMode": "provider_final_capture",
            },
            activation_backend="cli",
            reply_writeback_mode="provider_final_capture",
        )

        self.assertEqual(config.activation_backend.value, "cli")
        self.assertEqual(config.activation_backend.source, "explicit_cli")
        self.assertEqual(config.reply_writeback_mode.value, "provider_final_capture")
        self.assertEqual(config.reply_writeback_mode.source, "explicit_cli")

    def test_nested_values_override_flat_aliases_and_report_metadata(self) -> None:
        config = resolve_claude_control_config(
            {
                "claudeControl": {"activationBackend": "agent_sdk"},
                "claudeActivationBackend": "cli",
            }
        )

        self.assertEqual(config.activation_backend.value, "agent_sdk")
        self.assertEqual(config.activation_backend.source, "localRuntime.claudeControl")
        self.assertEqual(
            config.to_metadata()["backendDefaults"]["agent_sdk"],
            "explicit_only",
        )

    def test_flat_alias_is_accepted_but_reported(self) -> None:
        config = resolve_claude_control_config(
            {"claude_activation_backend": "agent_sdk"}
        )

        self.assertEqual(config.activation_backend.value, "agent_sdk")
        self.assertEqual(config.activation_backend.source, "profile")
        self.assertEqual(
            config.activation_backend.legacy_alias,
            "claude_activation_backend",
        )

    def test_invalid_values_and_non_object_control_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be a JSON object"):
            resolve_claude_control_config({"claudeControl": "agent_sdk"})
        with self.assertRaisesRegex(ValueError, "activationBackend"):
            resolve_claude_control_config({}, activation_backend="unknown")
        with self.assertRaisesRegex(ValueError, "replyWritebackMode"):
            resolve_claude_control_config({}, reply_writeback_mode="unknown")

    def test_enums_expose_public_values(self) -> None:
        self.assertEqual(ClaudeActivationBackend.AGENT_SDK.value, "agent_sdk")
        self.assertEqual(
            ClaudeReplyWritebackMode.PROVIDER_FINAL_CAPTURE.value,
            "provider_final_capture",
        )


if __name__ == "__main__":
    unittest.main()
