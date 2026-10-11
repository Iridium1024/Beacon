from __future__ import annotations

import unittest

from agent_os.application.services.hermes_session_control import (
    HermesActivationBackend,
    HermesReplyWritebackMode,
    normalize_hermes_activation_backend,
    resolve_hermes_control_config,
)


class HermesSessionControlTests(unittest.TestCase):
    def test_default_preserves_cli_and_historical_auto_capture(self) -> None:
        config = resolve_hermes_control_config({})

        self.assertEqual(config.activation_backend.value, "cli")
        self.assertEqual(
            config.reply_writeback_mode.value,
            "provider_final_capture",
        )
        self.assertEqual(
            config.reply_writeback_mode.source,
            "default_for_cli_compatibility",
        )
        self.assertIsNone(config.gateway_python)

    def test_tui_gateway_is_explicit_and_defaults_to_explicit_only(self) -> None:
        config = resolve_hermes_control_config(
            {},
            activation_backend="tui_gateway",
            gateway_python="C:/Hermes/python.exe",
        )

        self.assertEqual(config.activation_backend.value, "tui_gateway")
        self.assertEqual(config.activation_backend.source, "explicit_cli")
        self.assertEqual(config.reply_writeback_mode.value, "explicit_only")
        self.assertEqual(
            config.reply_writeback_mode.source,
            "default_for_tui_gateway",
        )
        self.assertEqual(config.gateway_python.value, "C:/Hermes/python.exe")

    def test_nested_profile_and_explicit_precedence_are_audited(self) -> None:
        config = resolve_hermes_control_config(
            {
                "hermesControl": {
                    "activationBackend": "tui_gateway",
                    "replyWritebackMode": "provider_final_capture",
                    "gatewayPython": "profile-python",
                },
                "hermesActivationBackend": "cli",
            },
            reply_writeback_mode="explicit_only",
        )

        self.assertEqual(config.activation_backend.value, "tui_gateway")
        self.assertEqual(
            config.activation_backend.source,
            "localRuntime.hermesControl",
        )
        self.assertEqual(config.reply_writeback_mode.value, "explicit_only")
        self.assertEqual(config.reply_writeback_mode.source, "explicit_cli")
        self.assertEqual(config.gateway_python.value, "profile-python")

    def test_invalid_backend_never_falls_back(self) -> None:
        with self.assertRaisesRegex(ValueError, "cli, tui_gateway"):
            normalize_hermes_activation_backend("app_server")
        with self.assertRaisesRegex(ValueError, "activationBackend"):
            resolve_hermes_control_config({}, activation_backend="unknown")

        self.assertIs(
            normalize_hermes_activation_backend(HermesActivationBackend.CLI),
            HermesActivationBackend.CLI,
        )
        self.assertEqual(
            HermesReplyWritebackMode.EXPLICIT_ONLY.value,
            "explicit_only",
        )


if __name__ == "__main__":
    unittest.main()
