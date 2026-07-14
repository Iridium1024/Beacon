from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services import ModelProviderSelection
from agent_os.domain.entities.provider_connection import ProviderConnectionSpec
from agent_os.infrastructure.config import (
    LocalAgentInvocationAdapterMode,
    OpenAICompatibleProviderSettings,
    LocalPlatformSettings,
    default_deterministic_provider_selection,
    normalize_local_agent_invocation_adapter_mode,
    openai_compatible_provider_settings_from_env,
    provider_connection_spec_from_env,
)


class LocalPlatformSettingsTests(unittest.TestCase):
    def test_defaults_keep_placeholder_adapter_mode(self) -> None:
        settings = LocalPlatformSettings(
            database="platform.sqlite3",
            workspace_root="workspace",
            plugins_directory="plugins",
        )

        self.assertEqual(settings.database, "platform.sqlite3")
        self.assertEqual(settings.workspace_root, "workspace")
        self.assertEqual(settings.plugins_directory, "plugins")
        self.assertEqual(
            settings.agent_invocation_adapter_mode,
            LocalAgentInvocationAdapterMode.DETERMINISTIC_PLACEHOLDER,
        )
        self.assertIsNone(settings.provider_selection)
        self.assertTrue(settings.initialize_schema)
        self.assertTrue(settings.record_agent_invocations)

    def test_accepts_explicit_deterministic_provider_mode(self) -> None:
        settings = LocalPlatformSettings(
            database="platform.sqlite3",
            workspace_root="workspace",
            plugins_directory="plugins",
            agent_invocation_adapter_mode="deterministic-provider",
        )

        selection = settings.provider_selection_or_default()

        self.assertEqual(
            settings.agent_invocation_adapter_mode,
            LocalAgentInvocationAdapterMode.DETERMINISTIC_PROVIDER,
        )
        self.assertEqual(selection.provider_name, "deterministic")
        self.assertEqual(selection.model_name, "deterministic-text")

    def test_accepts_explicit_provider_selection_for_provider_mode(self) -> None:
        selection = ModelProviderSelection(
            provider_name="deterministic",
            model_name="deterministic-text",
            parameters={"temperature": 0},
        )

        settings = LocalPlatformSettings(
            database="platform.sqlite3",
            workspace_root="workspace",
            plugins_directory="plugins",
            agent_invocation_adapter_mode=(
                LocalAgentInvocationAdapterMode.DETERMINISTIC_PROVIDER
            ),
            provider_selection=selection,
        )

        self.assertIs(settings.provider_selection_or_default(), selection)

    def test_accepts_openai_compatible_provider_mode(self) -> None:
        provider = OpenAICompatibleProviderSettings(
            base_url="http://127.0.0.1:8000/v1",
            model_name="fake-chat-model",
            timeout_seconds=2.5,
            parameters={"temperature": 0},
        )

        settings = LocalPlatformSettings(
            database="platform.sqlite3",
            workspace_root="workspace",
            plugins_directory="plugins",
            agent_invocation_adapter_mode="openai-compatible-provider",
            openai_compatible_provider=provider,
        )

        self.assertEqual(
            settings.agent_invocation_adapter_mode,
            LocalAgentInvocationAdapterMode.OPENAI_COMPATIBLE_PROVIDER,
        )
        self.assertIs(settings.openai_compatible_provider_or_raise(), provider)
        self.assertEqual(provider.model_selection().provider_name, "openai-compatible")
        self.assertEqual(provider.model_selection().model_name, "fake-chat-model")
        self.assertEqual(provider.model_selection().parameters["temperature"], 0)

    def test_builds_openai_compatible_provider_settings_from_env_without_key_value(
        self,
    ) -> None:
        provider = openai_compatible_provider_settings_from_env(
            {
                "AGENT_OS_OPENAI_COMPAT_BASE_URL": "http://127.0.0.1:8000/v1",
                "AGENT_OS_OPENAI_COMPAT_MODEL": "fake-chat-model",
                "AGENT_OS_OPENAI_COMPAT_PROVIDER_NAME": "test-compatible",
                "AGENT_OS_OPENAI_COMPAT_API_KEY_ENV_VAR": (
                    "AGENT_OS_OPENAI_COMPAT_TEST_CREDENTIAL"
                ),
                "AGENT_OS_OPENAI_COMPAT_TIMEOUT_SECONDS": "2.5",
            },
            parameters={"max_tokens": 32},
        )

        self.assertEqual(provider.base_url, "http://127.0.0.1:8000/v1")
        self.assertEqual(provider.model_name, "fake-chat-model")
        self.assertEqual(provider.provider_name, "test-compatible")
        self.assertEqual(
            provider.api_key_env_var,
            "AGENT_OS_OPENAI_COMPAT_TEST_CREDENTIAL",
        )
        self.assertEqual(provider.timeout_seconds, 2.5)
        self.assertEqual(provider.parameters["max_tokens"], 32)

    def test_accepts_provider_api_shape_mode(self) -> None:
        connection = ProviderConnectionSpec(
            provider_name="ollama",
            api_shape="ollama-chat",
            base_url="http://127.0.0.1:11434",
            model_name="llama-test-model",
            parameters={"temperature": 0},
        )

        settings = LocalPlatformSettings(
            database="platform.sqlite3",
            workspace_root="workspace",
            plugins_directory="plugins",
            agent_invocation_adapter_mode="provider-api-shape",
            provider_connection=connection,
        )

        self.assertEqual(
            settings.agent_invocation_adapter_mode,
            LocalAgentInvocationAdapterMode.PROVIDER_API_SHAPE,
        )
        self.assertIs(settings.provider_connection_or_raise(), connection)

    def test_builds_provider_connection_spec_from_env_without_key_value(self) -> None:
        connection = provider_connection_spec_from_env(
            {
                "AGENT_OS_PROVIDER_API_SHAPE": "anthropic-messages",
                "AGENT_OS_PROVIDER_BASE_URL": "https://api.anthropic.com",
                "AGENT_OS_PROVIDER_MODEL": "claude-test-model",
                "AGENT_OS_PROVIDER_API_KEY_ENV_VAR": "ANTHROPIC_TEST_KEY",
                "AGENT_OS_PROVIDER_TIMEOUT_SECONDS": "2.5",
            },
            parameters={
                "max_tokens": 32,
                "provider_user_agent": "AgentChatSettings/14.2",
            },
        )

        self.assertEqual(connection.provider_name, "anthropic")
        self.assertEqual(connection.api_shape.value, "anthropic_messages")
        self.assertEqual(connection.base_url, "https://api.anthropic.com")
        self.assertEqual(connection.model_name, "claude-test-model")
        self.assertEqual(connection.credential_env_var, "ANTHROPIC_TEST_KEY")
        self.assertEqual(connection.timeout_seconds, 2.5)
        self.assertEqual(connection.parameters["max_tokens"], 32)
        self.assertEqual(
            connection.parameters["provider_user_agent"],
            "AgentChatSettings/14.2",
        )

    def test_builds_openai_responses_connection_defaults_from_env(self) -> None:
        connection = provider_connection_spec_from_env(
            {
                "AGENT_OS_PROVIDER_API_SHAPE": "openai-responses",
                "AGENT_OS_PROVIDER_BASE_URL": "https://api.openai.com/v1",
                "AGENT_OS_PROVIDER_MODEL": "gpt-test-model",
            },
            parameters={"max_tokens": 32},
        )

        self.assertEqual(connection.provider_name, "openai-responses")
        self.assertEqual(connection.api_shape.value, "openai_responses")
        self.assertEqual(
            connection.credential_env_var,
            "AGENT_OS_OPENAI_RESPONSES_API_KEY",
        )
        self.assertEqual(connection.parameters["max_tokens"], 32)

    def test_rejects_empty_required_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "database"):
            LocalPlatformSettings(
                database=" ",
                workspace_root="workspace",
                plugins_directory="plugins",
            )
        with self.assertRaisesRegex(ValueError, "workspace_root"):
            LocalPlatformSettings(
                database="platform.sqlite3",
                workspace_root="",
                plugins_directory="plugins",
            )
        with self.assertRaisesRegex(ValueError, "plugins_directory"):
            LocalPlatformSettings(
                database="platform.sqlite3",
                workspace_root="workspace",
                plugins_directory=" ",
            )

    def test_rejects_invalid_adapter_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "agent_invocation_adapter_mode"):
            normalize_local_agent_invocation_adapter_mode("unknown")

        with self.assertRaisesRegex(ValueError, "agent_invocation_adapter_mode"):
            LocalPlatformSettings(
                database="platform.sqlite3",
                workspace_root="workspace",
                plugins_directory="plugins",
                agent_invocation_adapter_mode="unknown",
            )

    def test_rejects_provider_selection_without_provider_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "provider_selection"):
            LocalPlatformSettings(
                database="platform.sqlite3",
                workspace_root="workspace",
                plugins_directory="plugins",
                provider_selection=default_deterministic_provider_selection(),
            )

    def test_rejects_openai_compatible_provider_without_openai_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "openai_compatible_provider"):
            LocalPlatformSettings(
                database="platform.sqlite3",
                workspace_root="workspace",
                plugins_directory="plugins",
                openai_compatible_provider=OpenAICompatibleProviderSettings(
                    base_url="http://127.0.0.1:8000/v1",
                    model_name="fake-chat-model",
                ),
            )

    def test_rejects_openai_mode_without_provider_settings(self) -> None:
        with self.assertRaisesRegex(ValueError, "openai_compatible_provider"):
            LocalPlatformSettings(
                database="platform.sqlite3",
                workspace_root="workspace",
                plugins_directory="plugins",
                agent_invocation_adapter_mode="openai-compatible-provider",
            )

    def test_rejects_provider_connection_without_provider_api_shape_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "provider_connection"):
            LocalPlatformSettings(
                database="platform.sqlite3",
                workspace_root="workspace",
                plugins_directory="plugins",
                provider_connection=ProviderConnectionSpec(
                    provider_name="ollama",
                    api_shape="ollama-chat",
                    base_url="http://127.0.0.1:11434",
                    model_name="llama-test-model",
                ),
            )

    def test_rejects_provider_api_shape_mode_without_connection(self) -> None:
        with self.assertRaisesRegex(ValueError, "provider_connection"):
            LocalPlatformSettings(
                database="platform.sqlite3",
                workspace_root="workspace",
                plugins_directory="plugins",
                agent_invocation_adapter_mode="provider-api-shape",
            )

    def test_rejects_provider_selection_request_for_placeholder_mode(self) -> None:
        settings = LocalPlatformSettings(
            database="platform.sqlite3",
            workspace_root="workspace",
            plugins_directory="plugins",
        )

        with self.assertRaisesRegex(ValueError, "deterministic-provider"):
            settings.provider_selection_or_default()


if __name__ == "__main__":
    unittest.main()
