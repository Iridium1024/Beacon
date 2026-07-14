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
from agent_os.infrastructure.adapters.models.openai_adapter import (
    OpenAIAdapter,
    OpenAICompatibleProviderConfigError,
    OpenAICompatibleProviderError,
)


class OpenAICompatibleProviderAdapterTests(unittest.TestCase):
    def test_generate_posts_chat_completions_and_parses_text_output(self) -> None:
        env_var = "AGENT_OS_OPENAI_COMPAT_TEST_CREDENTIAL"
        credential = uuid4().hex
        with _FakeOpenAICompatibleServer(
            response_content="Provider response from fake server.",
        ) as server:
            provider = OpenAIAdapter(
                api_base_url=server.url,
                model_name="fake-chat-model",
                api_key_env_var=env_var,
                default_parameters={
                    "temperature": 0.25,
                    "thinking": {"type": "disabled"},
                    "provider_user_agent": "AgentChatOpenAICompat/14.2",
                    "workspace_id": "must-not-be-forwarded",
                },
            )
            request = ModelInvocation(
                provider_name="openai-compatible",
                model_name="fake-chat-model",
                system_prompt="Use local platform context.",
                messages=(
                    ModelMessage(
                        role=MessageRole.USER,
                        content="Summarize the current task.",
                    ),
                ),
                parameters={
                    "max_tokens": 64,
                    "reasoning_effort": "high",
                    "context_id": "must-not-be-forwarded",
                },
            )

            with patch.dict(os.environ, {env_var: credential}, clear=False):
                output = asyncio.run(provider.generate(request))

        self.assertEqual(output.model_name, "fake-chat-model")
        self.assertEqual(output.content, "Provider response from fake server.")
        self.assertEqual(output.metadata["openai_compatible"], "true")
        self.assertEqual(output.metadata["finish_reason"], "stop")
        self.assertEqual(output.metadata["total_tokens"], "11")

        sent = server.requests[0]
        self.assertEqual(sent["path"], "/v1/chat/completions")
        self.assertEqual(sent["authorization"], f"Bearer {credential}")
        self.assertEqual(sent["user-agent"], "AgentChatOpenAICompat/14.2")
        body = sent["body"]
        self.assertEqual(body["model"], "fake-chat-model")
        self.assertEqual(
            body["messages"],
            [
                {"role": "system", "content": "Use local platform context."},
                {"role": "user", "content": "Summarize the current task."},
            ],
        )
        self.assertEqual(body["temperature"], 0.25)
        self.assertEqual(body["max_tokens"], 64)
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertEqual(body["reasoning_effort"], "high")
        self.assertNotIn("provider_user_agent", body)
        self.assertNotIn("workspace_id", body)
        self.assertNotIn("context_id", body)

    def test_generate_rejects_unsafe_provider_user_agent(self) -> None:
        env_var = "AGENT_OS_OPENAI_COMPAT_TEST_CREDENTIAL"
        with _FakeOpenAICompatibleServer(
            response_content="Provider response from fake server.",
        ) as server:
            provider = OpenAIAdapter(
                api_base_url=server.url,
                model_name="fake-chat-model",
                api_key_env_var=env_var,
                default_parameters={
                    "provider_user_agent": "AgentChat\r\nCookie: leaked",
                },
            )
            request = ModelInvocation(
                provider_name="openai-compatible",
                model_name="fake-chat-model",
                messages=(ModelMessage(role=MessageRole.USER, content="Hello."),),
            )

            with patch.dict(os.environ, {env_var: uuid4().hex}, clear=False):
                with self.assertRaisesRegex(
                    OpenAICompatibleProviderConfigError,
                    "User-Agent",
                ):
                    asyncio.run(provider.generate(request))

        self.assertEqual(server.requests, [])

    def test_generate_rejects_missing_api_credential_environment(self) -> None:
        env_var = "AGENT_OS_OPENAI_COMPAT_MISSING_TEST_CREDENTIAL"
        provider = OpenAIAdapter(
            api_base_url="http://127.0.0.1:9/v1",
            model_name="fake-chat-model",
            api_key_env_var=env_var,
            timeout_seconds=0.1,
        )
        request = ModelInvocation(
            provider_name="openai-compatible",
            model_name="fake-chat-model",
            messages=(ModelMessage(role=MessageRole.USER, content="Hello."),),
        )

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                OpenAICompatibleProviderConfigError,
                "environment variable is not set",
            ):
                asyncio.run(provider.generate(request))

    def test_generate_maps_provider_http_error_without_response_body(self) -> None:
        env_var = "AGENT_OS_OPENAI_COMPAT_TEST_CREDENTIAL"
        with _FakeOpenAICompatibleServer(
            status_code=503,
            response_content="ignored provider detail",
        ) as server:
            provider = OpenAIAdapter(
                api_base_url=server.url,
                model_name="fake-chat-model",
                api_key_env_var=env_var,
            )
            request = ModelInvocation(
                provider_name="openai-compatible",
                model_name="fake-chat-model",
                messages=(ModelMessage(role=MessageRole.USER, content="Hello."),),
            )

            with patch.dict(os.environ, {env_var: uuid4().hex}, clear=False):
                with self.assertRaisesRegex(
                    OpenAICompatibleProviderError,
                    "status 503",
                ) as raised:
                    asyncio.run(provider.generate(request))

        self.assertNotIn("ignored provider detail", str(raised.exception))

    def test_generate_rejects_mismatched_provider_or_model(self) -> None:
        provider = OpenAIAdapter(
            api_base_url="http://127.0.0.1:9/v1",
            model_name="fake-chat-model",
        )

        with self.assertRaisesRegex(
            OpenAICompatibleProviderConfigError,
            "provider_name",
        ):
            asyncio.run(
                provider.generate(
                    ModelInvocation(
                        provider_name="other",
                        model_name="fake-chat-model",
                        messages=(
                            ModelMessage(role=MessageRole.USER, content="Hello."),
                        ),
                    )
                )
            )

        with self.assertRaisesRegex(
            OpenAICompatibleProviderConfigError,
            "model_name",
        ):
            asyncio.run(
                provider.generate(
                    ModelInvocation(
                        provider_name="openai-compatible",
                        model_name="other-model",
                        messages=(
                            ModelMessage(role=MessageRole.USER, content="Hello."),
                        ),
                    )
                )
            )


class _FakeOpenAICompatibleServer:
    def __init__(
        self,
        *,
        status_code: int = 200,
        response_content: str,
    ) -> None:
        self.status_code = status_code
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
        if fake.status_code != 200:
            payload = {
                "error": {
                    "message": fake.response_content,
                }
            }
            self._write_json(fake.status_code, payload)
            return
        self._write_json(
            200,
            {
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
                    "prompt_tokens": 7,
                    "completion_tokens": 4,
                    "total_tokens": 11,
                },
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
