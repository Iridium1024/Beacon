from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.infrastructure.adapters.models import OpenAIAdapter, OpenAIResponsesAdapter
from agent_os.infrastructure.adapters.models.provider_factory import (
    ProviderAdapterUnsupportedError,
    build_model_provider_from_connection_spec,
)
from agent_os.domain.entities.provider_connection import (
    ProviderApiShape,
    ProviderConnectionConfigError,
    ProviderConnectionSpec,
    deepseek_provider_preset,
    normalize_provider_api_shape,
)


class ProviderConnectionConfigAndFactoryTests(unittest.TestCase):
    def test_provider_api_shape_normalizes_hyphenated_and_vendor_aliases(self) -> None:
        self.assertIs(
            normalize_provider_api_shape("openai-chat-completions"),
            ProviderApiShape.OPENAI_CHAT_COMPLETIONS,
        )
        self.assertIs(
            normalize_provider_api_shape("openai-compatible"),
            ProviderApiShape.OPENAI_CHAT_COMPLETIONS,
        )
        self.assertIs(
            normalize_provider_api_shape("openai-response"),
            ProviderApiShape.OPENAI_RESPONSES,
        )
        self.assertIs(
            normalize_provider_api_shape("anthropic"),
            ProviderApiShape.ANTHROPIC_MESSAGES,
        )
        self.assertIs(
            normalize_provider_api_shape("gemini"),
            ProviderApiShape.GEMINI_GENERATE_CONTENT,
        )
        self.assertIs(
            normalize_provider_api_shape("ollama"),
            ProviderApiShape.OLLAMA_CHAT,
        )

    def test_provider_connection_spec_rejects_invalid_shape_and_url(self) -> None:
        with self.assertRaisesRegex(
            ProviderConnectionConfigError,
            "provider api shape",
        ):
            ProviderConnectionSpec(
                provider_name="unknown",
                api_shape="unsupported-shape",
                base_url="https://example.invalid",
                model_name="model",
            )

        with self.assertRaisesRegex(ProviderConnectionConfigError, "base_url"):
            ProviderConnectionSpec(
                provider_name="bad-url",
                api_shape="openai-chat-completions",
                base_url="not-a-url",
                model_name="model",
            )

    def test_provider_connection_spec_rejects_credential_values_in_metadata(self) -> None:
        with self.assertRaisesRegex(
            ProviderConnectionConfigError,
            "credential values",
        ):
            ProviderConnectionSpec(
                provider_name="unsafe",
                api_shape="openai-chat-completions",
                base_url="https://example.invalid/v1",
                model_name="model",
                credential_env_var="PROVIDER_KEY_ENV",
                metadata={"apiKey": "must-not-be-stored"},
            )

    def test_deepseek_preset_is_openai_compatible_with_static_models(self) -> None:
        preset = deepseek_provider_preset(credential_env_var="DEEPSEEK_TEST_KEY")

        self.assertEqual(preset.preset_id, "deepseek")
        self.assertEqual(preset.connection.provider_name, "deepseek")
        self.assertIs(
            preset.connection.api_shape,
            ProviderApiShape.OPENAI_CHAT_COMPLETIONS,
        )
        self.assertEqual(preset.connection.credential_env_var, "DEEPSEEK_TEST_KEY")
        self.assertEqual(
            preset.connection.configured_models(),
            ("deepseek-v4-flash", "deepseek-v4-pro"),
        )
        self.assertEqual(preset.connection.model_name, "deepseek-v4-flash")
        self.assertEqual(
            preset.connection.metadata["legacy_models_deprecated_on"],
            "2026-07-24",
        )
        self.assertEqual(
            preset.connection.metadata["reasoning_effort_values"],
            "high,max",
        )

    def test_factory_builds_openai_chat_completions_adapter(self) -> None:
        spec = ProviderConnectionSpec(
            provider_name="fake-openai-compatible",
            api_shape="openai-chat-completions",
            base_url="http://127.0.0.1:9/v1",
            model_name="fake-chat-model",
            credential_env_var="FAKE_OPENAI_KEY",
            parameters={"temperature": 0},
        )

        provider = build_model_provider_from_connection_spec(spec)

        self.assertIsInstance(provider, OpenAIAdapter)
        self.assertEqual(
            asyncio.run(provider.list_models()),
            ("fake-chat-model",),
        )

    def test_factory_builds_openai_responses_adapter(self) -> None:
        spec = ProviderConnectionSpec(
            provider_name="fake-openai-responses",
            api_shape="openai-responses",
            base_url="http://127.0.0.1:9/v1",
            model_name="fake-responses-model",
            credential_env_var="FAKE_OPENAI_RESPONSES_KEY",
            parameters={"max_output_tokens": 16},
        )

        provider = build_model_provider_from_connection_spec(spec)

        self.assertIsInstance(provider, OpenAIResponsesAdapter)
        self.assertEqual(
            asyncio.run(provider.list_models()),
            ("fake-responses-model",),
        )

    def test_factory_requires_credential_env_var_for_openai_shape(self) -> None:
        spec = ProviderConnectionSpec(
            provider_name="missing-key-ref",
            api_shape="openai-chat-completions",
            base_url="http://127.0.0.1:9/v1",
            model_name="fake-chat-model",
        )

        with self.assertRaisesRegex(
            ProviderConnectionConfigError,
            "credential_env_var",
        ):
            build_model_provider_from_connection_spec(spec)

    def test_factory_rejects_unimplemented_shape_with_stable_error(self) -> None:
        spec = ProviderConnectionSpec(
            provider_name="azure-openai",
            api_shape="azure-openai",
            base_url="https://api.openai.com",
            model_name="gpt-placeholder",
            credential_env_var="OPENAI_TEST_KEY",
        )

        with self.assertRaisesRegex(
            ProviderAdapterUnsupportedError,
            "azure_openai",
        ):
            build_model_provider_from_connection_spec(spec)


if __name__ == "__main__":
    unittest.main()
