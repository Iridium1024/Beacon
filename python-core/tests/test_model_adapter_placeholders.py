from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.domain.entities.model import EmbeddingRequest, ModelInvocation
from agent_os.infrastructure.adapters.models import (
    LocalModelAdapter,
    OpenAIAdapter,
    RemoteHttpModelAdapter,
)


class ModelAdapterPlaceholderTests(unittest.TestCase):
    def test_local_adapter_remains_intentionally_unimplemented(self) -> None:
        adapter = LocalModelAdapter(runtime_name="local")

        with self.assertRaisesRegex(NotImplementedError, "Local generation"):
            asyncio.run(adapter.generate(_generation_request("local")))

        with self.assertRaisesRegex(NotImplementedError, "Local embeddings"):
            asyncio.run(adapter.embed(_embedding_request("local")))

        with self.assertRaisesRegex(NotImplementedError, "Local model discovery"):
            asyncio.run(adapter.list_models())

    def test_openai_adapter_lists_configured_model_without_embedding_support(
        self,
    ) -> None:
        adapter = OpenAIAdapter(
            api_base_url="http://127.0.0.1:9/v1",
            model_name="placeholder",
            api_key_env_var="SHOULD_NOT_BE_READ",
        )

        self.assertEqual(asyncio.run(adapter.list_models()), ("placeholder",))

        with self.assertRaisesRegex(NotImplementedError, "embeddings"):
            asyncio.run(adapter.embed(_embedding_request("openai-compatible")))

    def test_remote_http_adapter_remains_intentionally_unimplemented(self) -> None:
        adapter = RemoteHttpModelAdapter(endpoint_url="https://example.invalid")

        with self.assertRaisesRegex(NotImplementedError, "Remote HTTP generation"):
            asyncio.run(adapter.generate(_generation_request("remote")))

        with self.assertRaisesRegex(NotImplementedError, "Remote HTTP embeddings"):
            asyncio.run(adapter.embed(_embedding_request("remote")))

        with self.assertRaisesRegex(NotImplementedError, "Remote HTTP model discovery"):
            asyncio.run(adapter.list_models())


def _generation_request(provider_name: str) -> ModelInvocation:
    return ModelInvocation(
        provider_name=provider_name,
        model_name="placeholder",
        messages=(),
    )


def _embedding_request(provider_name: str) -> EmbeddingRequest:
    return EmbeddingRequest(
        provider_name=provider_name,
        model_name="placeholder",
        inputs=("text",),
    )


if __name__ == "__main__":
    unittest.main()
