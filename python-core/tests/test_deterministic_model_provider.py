from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.domain.entities.model import (
    EmbeddingRequest,
    ModelInvocation,
    ModelMessage,
)
from agent_os.domain.value_objects.enums import MessageRole
from agent_os.infrastructure.adapters.models import DeterministicModelProvider


class DeterministicModelProviderTests(unittest.TestCase):
    def test_generate_returns_provider_neutral_output(self) -> None:
        provider = DeterministicModelProvider()

        output = asyncio.run(
            provider.generate(
                ModelInvocation(
                    provider_name="deterministic",
                    model_name="deterministic-text",
                    messages=(
                        ModelMessage(
                            role=MessageRole.SYSTEM,
                            content="Use platform context only.",
                        ),
                        ModelMessage(
                            role=MessageRole.USER,
                            content="Capture this task.",
                        ),
                    ),
                    parameters={"temperature": 0},
                )
            )
        )

        self.assertEqual(output.model_name, "deterministic-text")
        self.assertEqual(
            output.content,
            "Deterministic model response: Capture this task.",
        )
        self.assertEqual(output.metadata["provider_name"], "deterministic")
        self.assertEqual(output.metadata["deterministic"], "true")

    def test_embed_returns_stable_vectors(self) -> None:
        provider = DeterministicModelProvider(vector_dimensions=3)
        request = EmbeddingRequest(
            provider_name="deterministic",
            model_name="deterministic-embedding",
            inputs=("alpha", "alpha", "beta"),
        )

        result = asyncio.run(provider.embed(request))

        self.assertEqual(result.model_name, "deterministic-embedding")
        self.assertEqual(len(result.vectors), 3)
        self.assertEqual(result.vectors[0], result.vectors[1])
        self.assertNotEqual(result.vectors[0], result.vectors[2])
        self.assertEqual(len(result.vectors[0]), 3)

    def test_list_models_returns_generation_and_embedding_models(self) -> None:
        provider = DeterministicModelProvider(
            generation_models=("text-a", "text-b"),
            embedding_models=("embed-a",),
        )

        models = asyncio.run(provider.list_models())

        self.assertEqual(models, ("text-a", "text-b", "embed-a"))

    def test_rejects_mismatched_provider_or_model(self) -> None:
        provider = DeterministicModelProvider()

        with self.assertRaisesRegex(ValueError, "provider_name"):
            asyncio.run(
                provider.generate(
                    ModelInvocation(
                        provider_name="other",
                        model_name="deterministic-text",
                        messages=(),
                    )
                )
            )

        with self.assertRaisesRegex(ValueError, "generation model"):
            asyncio.run(
                provider.generate(
                    ModelInvocation(
                        provider_name="deterministic",
                        model_name="missing",
                        messages=(),
                    )
                )
            )

        with self.assertRaisesRegex(ValueError, "vector_dimensions"):
            DeterministicModelProvider(vector_dimensions=0)


if __name__ == "__main__":
    unittest.main()
