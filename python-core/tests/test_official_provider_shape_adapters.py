from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch
from uuid import uuid4


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.domain.entities.model import ModelInvocation, ModelMessage
from agent_os.domain.value_objects.enums import MessageRole
from agent_os.infrastructure.adapters.models.anthropic_adapter import (
    AnthropicMessagesAdapter,
    AnthropicMessagesProviderConfigError,
)
from agent_os.infrastructure.adapters.models.gemini_adapter import (
    GeminiGenerateContentAdapter,
    GeminiGenerateContentProviderConfigError,
)
from agent_os.infrastructure.adapters.models.ollama_adapter import OllamaChatAdapter
from agent_os.infrastructure.adapters.models.openai_responses_adapter import (
    OpenAIResponsesAdapter,
    OpenAIResponsesProviderConfigError,
    OpenAIResponsesProviderError,
)
from agent_os.infrastructure.adapters.models.provider_factory import (
    build_model_provider_from_connection_spec,
)
from agent_os.domain.entities.provider_connection import ProviderConnectionSpec


class OfficialProviderShapeAdapterTests(unittest.TestCase):
    def test_openai_responses_posts_official_shape_and_parses_output_text(
        self,
    ) -> None:
        env_var = "AGENT_OS_OPENAI_RESPONSES_TEST_CREDENTIAL"
        credential = uuid4().hex
        with _FakeProviderServer("responses-output-text") as server:
            provider = OpenAIResponsesAdapter(
                api_base_url=server.url,
                model_name="responses-test-model",
                api_key_env_var=env_var,
                default_parameters={"temperature": 0.2},
            )

            with patch.dict(os.environ, {env_var: credential}, clear=False):
                output = asyncio.run(
                    provider.generate(
                        _request("openai-responses", "responses-test-model")
                    )
                )

        self.assertEqual(output.content, "Responses fake response.")
        self.assertEqual(output.metadata["api_shape"], "openai_responses")
        self.assertEqual(output.metadata["status"], "completed")
        sent = server.requests[0]
        self.assertEqual(sent["path"], "/v1/responses")
        self.assertEqual(sent["authorization"], f"Bearer {credential}")
        self.assertEqual(sent["body"]["model"], "responses-test-model")
        self.assertEqual(sent["body"]["instructions"], "Use local platform context.")
        self.assertEqual(sent["body"]["max_output_tokens"], 64)
        self.assertNotIn("max_tokens", sent["body"])
        self.assertNotIn("workspace_id", sent["body"])
        self.assertEqual(
            sent["body"]["input"],
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Summarize the current task.",
                        }
                    ],
                }
            ],
        )

    def test_openai_responses_parses_output_array_text(self) -> None:
        env_var = "AGENT_OS_OPENAI_RESPONSES_TEST_CREDENTIAL"
        with _FakeProviderServer("responses-output-array") as server:
            provider = OpenAIResponsesAdapter(
                api_base_url=server.url,
                model_name="responses-test-model",
                api_key_env_var=env_var,
            )

            with patch.dict(os.environ, {env_var: uuid4().hex}, clear=False):
                output = asyncio.run(
                    provider.generate(
                        _request("openai-responses", "responses-test-model")
                    )
                )

        self.assertEqual(output.content, "Array fake response.")
        self.assertEqual(server.requests[0]["path"], "/v1/responses")

    def test_openai_responses_plain_text_input_mode_posts_string_input(
        self,
    ) -> None:
        env_var = "AGENT_OS_OPENAI_RESPONSES_TEST_CREDENTIAL"
        with _FakeProviderServer("responses-output-text") as server:
            provider = OpenAIResponsesAdapter(
                api_base_url=server.url,
                model_name="responses-test-model",
                api_key_env_var=env_var,
                default_parameters={"input_mode": "plain_text"},
            )

            with patch.dict(os.environ, {env_var: uuid4().hex}, clear=False):
                output = asyncio.run(
                    provider.generate(
                        _request("openai-responses", "responses-test-model")
                    )
                )

        self.assertEqual(provider.input_mode, "plain_text")
        self.assertEqual(output.content, "Responses fake response.")
        self.assertEqual(
            server.requests[0]["body"]["input"],
            "Summarize the current task.",
        )
        self.assertEqual(
            server.requests[0]["body"]["instructions"],
            "Use local platform context.",
        )
        self.assertNotIn("input_mode", server.requests[0]["body"])

    def test_openai_responses_rejects_unknown_input_mode(self) -> None:
        with self.assertRaisesRegex(
            OpenAIResponsesProviderConfigError,
            "input_mode",
        ):
            OpenAIResponsesAdapter(
                api_base_url="http://127.0.0.1:9/v1",
                model_name="responses-test-model",
                default_parameters={"input_mode": "relay-auto"},
            )

    def test_openai_responses_can_send_explicit_provider_user_agent(self) -> None:
        env_var = "AGENT_OS_OPENAI_RESPONSES_TEST_CREDENTIAL"
        with _FakeProviderServer("responses-output-text") as server:
            provider = OpenAIResponsesAdapter(
                api_base_url=server.url,
                model_name="responses-test-model",
                api_key_env_var=env_var,
                default_parameters={
                    "provider_user_agent": "AgentChatTest/14.2",
                },
            )

            with patch.dict(os.environ, {env_var: uuid4().hex}, clear=False):
                asyncio.run(
                    provider.generate(
                        _request("openai-responses", "responses-test-model")
                    )
                )

        sent = server.requests[0]
        self.assertEqual(sent["user-agent"], "AgentChatTest/14.2")
        self.assertNotIn("provider_user_agent", sent["body"])
        self.assertNotIn("user_agent", sent["body"])

    def test_openai_responses_rejects_unsafe_provider_user_agent(self) -> None:
        env_var = "AGENT_OS_OPENAI_RESPONSES_TEST_CREDENTIAL"
        unsafe_values = (
            "",
            "AgentChat\r\nAuthorization: leaked",
            "x" * 257,
        )
        for value in unsafe_values:
            with self.subTest(value=repr(value)):
                with _FakeProviderServer("responses-output-text") as server:
                    provider = OpenAIResponsesAdapter(
                        api_base_url=server.url,
                        model_name="responses-test-model",
                        api_key_env_var=env_var,
                        default_parameters={"provider_user_agent": value},
                    )

                    with patch.dict(os.environ, {env_var: uuid4().hex}, clear=False):
                        with self.assertRaisesRegex(
                            OpenAIResponsesProviderConfigError,
                            "User-Agent",
                        ):
                            asyncio.run(
                                provider.generate(
                                    _request(
                                        "openai-responses",
                                        "responses-test-model",
                                    )
                                )
                            )
                self.assertEqual(server.requests, [])

    def test_openai_responses_request_parameters_override_defaults(self) -> None:
        env_var = "AGENT_OS_OPENAI_RESPONSES_TEST_CREDENTIAL"
        request = ModelInvocation(
            provider_name="openai-responses",
            model_name="responses-test-model",
            messages=(
                ModelMessage(
                    role=MessageRole.USER,
                    content="Check request override precedence.",
                ),
            ),
            parameters={
                "max_tokens": 32,
                "reasoning_effort": "high",
                "verbosity": "medium",
            },
        )
        with _FakeProviderServer("responses-output-text") as server:
            provider = OpenAIResponsesAdapter(
                api_base_url=server.url,
                model_name="responses-test-model",
                api_key_env_var=env_var,
                default_parameters={
                    "max_output_tokens": 128,
                    "reasoning": {"effort": "low"},
                    "text": {"verbosity": "low"},
                },
            )

            with patch.dict(os.environ, {env_var: uuid4().hex}, clear=False):
                asyncio.run(provider.generate(request))

        body = server.requests[0]["body"]
        self.assertEqual(body["max_output_tokens"], 32)
        self.assertEqual(body["reasoning"], {"effort": "high"})
        self.assertEqual(body["text"], {"verbosity": "medium"})
        self.assertNotIn("max_tokens", body)

    def test_openai_responses_rejects_missing_credential_env(self) -> None:
        provider = OpenAIResponsesAdapter(
            api_base_url="http://127.0.0.1:9/v1",
            model_name="responses-test-model",
            api_key_env_var="AGENT_OS_MISSING_RESPONSES_TEST_KEY",
            timeout_seconds=0.1,
        )

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                OpenAIResponsesProviderConfigError,
                "environment variable is not set",
            ):
                asyncio.run(
                    provider.generate(
                        _request("openai-responses", "responses-test-model")
                    )
                )

    def test_openai_responses_maps_provider_http_error_without_body_leak(
        self,
    ) -> None:
        env_var = "AGENT_OS_OPENAI_RESPONSES_TEST_CREDENTIAL"
        credential = uuid4().hex
        with _FakeProviderServer("responses-error") as server:
            provider = OpenAIResponsesAdapter(
                api_base_url=server.url,
                model_name="responses-test-model",
                api_key_env_var=env_var,
            )

            with patch.dict(os.environ, {env_var: credential}, clear=False):
                with self.assertRaisesRegex(
                    OpenAIResponsesProviderError,
                    "status 503",
                ) as raised:
                    asyncio.run(
                        provider.generate(
                            _request("openai-responses", "responses-test-model")
                        )
                    )

        error_text = str(raised.exception)
        self.assertNotIn("upstream unavailable detail", error_text)
        self.assertNotIn(credential, error_text)

    def test_anthropic_messages_posts_official_shape_and_parses_text(self) -> None:
        env_var = "AGENT_OS_ANTHROPIC_TEST_CREDENTIAL"
        credential = uuid4().hex
        with _FakeProviderServer("anthropic") as server:
            provider = AnthropicMessagesAdapter(
                api_base_url=server.url,
                model_name="claude-test-model",
                api_key_env_var=env_var,
                default_parameters={"temperature": 0.2},
            )

            with patch.dict(os.environ, {env_var: credential}, clear=False):
                output = asyncio.run(provider.generate(_request("anthropic", "claude-test-model")))

        self.assertEqual(output.content, "Anthropic fake response.")
        self.assertEqual(output.metadata["api_shape"], "anthropic_messages")
        sent = server.requests[0]
        self.assertEqual(sent["path"], "/v1/messages")
        self.assertEqual(sent["x-api-key"], credential)
        self.assertEqual(sent["anthropic-version"], "2023-06-01")
        self.assertEqual(sent["body"]["model"], "claude-test-model")
        self.assertEqual(sent["body"]["system"], "Use local platform context.")
        self.assertEqual(sent["body"]["max_tokens"], 64)
        self.assertEqual(
            sent["body"]["messages"],
            [{"role": "user", "content": "Summarize the current task."}],
        )

    def test_anthropic_messages_rejects_missing_credential_env(self) -> None:
        provider = AnthropicMessagesAdapter(
            api_base_url="http://127.0.0.1:9",
            model_name="claude-test-model",
            api_key_env_var="AGENT_OS_MISSING_ANTHROPIC_TEST_KEY",
            timeout_seconds=0.1,
        )

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                AnthropicMessagesProviderConfigError,
                "environment variable is not set",
            ):
                asyncio.run(provider.generate(_request("anthropic", "claude-test-model")))

    def test_gemini_generate_content_posts_official_shape_and_parses_text(self) -> None:
        env_var = "AGENT_OS_GEMINI_TEST_CREDENTIAL"
        credential = uuid4().hex
        with _FakeProviderServer("gemini") as server:
            provider = GeminiGenerateContentAdapter(
                api_base_url=server.url,
                model_name="gemini-test-model",
                api_key_env_var=env_var,
                default_parameters={"temperature": 0.3},
            )

            with patch.dict(os.environ, {env_var: credential}, clear=False):
                output = asyncio.run(provider.generate(_request("gemini", "gemini-test-model")))

        self.assertEqual(output.content, "Gemini fake response.")
        self.assertEqual(output.metadata["api_shape"], "gemini_generate_content")
        sent = server.requests[0]
        self.assertEqual(sent["path"], "/v1beta/models/gemini-test-model:generateContent")
        self.assertEqual(sent["x-goog-api-key"], credential)
        self.assertEqual(
            sent["body"]["systemInstruction"],
            {"parts": [{"text": "Use local platform context."}]},
        )
        self.assertEqual(
            sent["body"]["contents"],
            [
                {
                    "role": "user",
                    "parts": [{"text": "Summarize the current task."}],
                }
            ],
        )
        self.assertEqual(sent["body"]["generationConfig"]["maxOutputTokens"], 64)

    def test_gemini_generate_content_rejects_missing_credential_env(self) -> None:
        provider = GeminiGenerateContentAdapter(
            api_base_url="http://127.0.0.1:9",
            model_name="gemini-test-model",
            api_key_env_var="AGENT_OS_MISSING_GEMINI_TEST_KEY",
            timeout_seconds=0.1,
        )

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                GeminiGenerateContentProviderConfigError,
                "environment variable is not set",
            ):
                asyncio.run(provider.generate(_request("gemini", "gemini-test-model")))

    def test_ollama_chat_posts_native_shape_without_credential(self) -> None:
        with _FakeProviderServer("ollama") as server:
            provider = OllamaChatAdapter(
                api_base_url=server.url,
                model_name="llama-test-model",
                default_parameters={"temperature": 0.1},
            )

            output = asyncio.run(provider.generate(_request("ollama", "llama-test-model")))

        self.assertEqual(output.content, "Ollama fake response.")
        self.assertEqual(output.metadata["api_shape"], "ollama_chat")
        sent = server.requests[0]
        self.assertEqual(sent["path"], "/api/chat")
        self.assertEqual(sent["body"]["model"], "llama-test-model")
        self.assertFalse(sent["body"]["stream"])
        self.assertEqual(sent["body"]["options"]["temperature"], 0.1)
        self.assertEqual(sent["body"]["options"]["num_predict"], 64)

    def test_factory_builds_first_official_shape_adapters(self) -> None:
        with _FakeProviderServer("ollama") as server:
            provider = build_model_provider_from_connection_spec(
                ProviderConnectionSpec(
                    provider_name="ollama",
                    api_shape="ollama-chat",
                    base_url=server.url,
                    model_name="llama-test-model",
                )
            )

            output = asyncio.run(provider.generate(_request("ollama", "llama-test-model")))

        self.assertEqual(output.content, "Ollama fake response.")


def _request(provider_name: str, model_name: str) -> ModelInvocation:
    return ModelInvocation(
        provider_name=provider_name,
        model_name=model_name,
        system_prompt="Use local platform context.",
        messages=(
            ModelMessage(
                role=MessageRole.USER,
                content="Summarize the current task.",
            ),
        ),
        parameters={
            "max_tokens": 64,
            "workspace_id": "must-not-be-forwarded",
        },
    )


class _FakeProviderServer:
    def __init__(self, provider_kind: str) -> None:
        self.provider_kind = provider_kind
        self.requests: list[dict[str, Any]] = []

    def __enter__(self) -> "_FakeProviderServer":
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeProviderHandler)
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


class _FakeProviderHandler(BaseHTTPRequestHandler):
    server: ThreadingHTTPServer

    def do_POST(self) -> None:
        fake: _FakeProviderServer = self.server.fake
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        fake.requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "user-agent": self.headers.get("User-Agent"),
                "x-api-key": self.headers.get("x-api-key"),
                "x-goog-api-key": self.headers.get("x-goog-api-key"),
                "anthropic-version": self.headers.get("anthropic-version"),
                "body": body,
            }
        )
        if fake.provider_kind == "responses-error":
            self._write_json(
                503,
                {
                    "error": {
                        "message": "upstream unavailable detail",
                        "type": "upstream_error",
                    }
                },
            )
            return
        if fake.provider_kind == "responses-output-text":
            self._write_json(
                200,
                {
                    "id": "resp_fake_1",
                    "model": body["model"],
                    "status": "completed",
                    "output_text": "Responses fake response.",
                    "usage": {
                        "input_tokens": 3,
                        "output_tokens": 4,
                        "total_tokens": 7,
                    },
                },
            )
            return
        if fake.provider_kind == "responses-output-array":
            self._write_json(
                200,
                {
                    "id": "resp_fake_2",
                    "model": body["model"],
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "Array fake response.",
                                }
                            ],
                        }
                    ],
                },
            )
            return
        if fake.provider_kind == "anthropic":
            self._write_json(
                200,
                {
                    "model": body["model"],
                    "content": [
                        {
                            "type": "text",
                            "text": "Anthropic fake response.",
                        }
                    ],
                    "stop_reason": "end_turn",
                    "usage": {
                        "input_tokens": 3,
                        "output_tokens": 4,
                    },
                },
            )
            return
        if fake.provider_kind == "gemini":
            self._write_json(
                200,
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": "Gemini fake response.",
                                    }
                                ]
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 3,
                        "candidatesTokenCount": 4,
                        "totalTokenCount": 7,
                    },
                },
            )
            return
        self._write_json(
            200,
            {
                "model": body["model"],
                "message": {
                    "role": "assistant",
                    "content": "Ollama fake response.",
                },
                "done_reason": "stop",
            },
        )

    def log_message(self, _format: str, *_args: object) -> None:
        return None

    def _write_json(self, status_code: int, payload: Mapping[str, object]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    unittest.main()
