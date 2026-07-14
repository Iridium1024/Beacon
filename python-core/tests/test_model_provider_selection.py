from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.model_provider_selection import (
    ModelProviderSelection,
    build_provider_backed_agent_invocation_adapter,
)
from agent_os.domain.entities.context import ContextUpdateInfo, ContextUpdateKind
from agent_os.domain.entities.invocation import AgentInvocationRequest
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextUpdateId,
    WorkspaceId,
)
from agent_os.infrastructure.adapters.models import DeterministicModelProvider
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteContextStateStore,
)
from support.platform_invocation_fixtures import (
    connect_in_memory_platform,
    seed_minimal_invocation_platform_state,
)


class ModelProviderSelectionTests(unittest.TestCase):
    def test_selection_merges_defaults_without_overwriting_explicit_parameters(self) -> None:
        selection = ModelProviderSelection(
            provider_name="deterministic",
            model_name="deterministic-text",
            system_prompt="Use platform context.",
            parameters={"temperature": 0},
        )

        merged = selection.with_parameter_defaults(
            {
                "temperature": 1,
                "max_tokens": 256,
            }
        )

        self.assertEqual(merged.provider_name, "deterministic")
        self.assertEqual(merged.model_name, "deterministic-text")
        self.assertEqual(merged.parameters["temperature"], 0)
        self.assertEqual(merged.parameters["max_tokens"], 256)

    def test_factory_builds_provider_backed_adapter_from_selection(self) -> None:
        selection = ModelProviderSelection(
            provider_name="deterministic",
            model_name="deterministic-text",
            system_prompt="Use platform context.",
            parameters={"temperature": 0},
        )
        adapter = build_provider_backed_agent_invocation_adapter(
            model_provider=DeterministicModelProvider(),
            selection=selection,
        )
        connection = connect_in_memory_platform()
        seed_minimal_invocation_platform_state(connection)
        context_record = SqliteContextStateStore(connection).get_context_state(
            WorkspaceId("workspace-1")
        )
        assert context_record is not None
        requested_at = datetime(2026, 6, 4, 18, 50, tzinfo=timezone.utc)
        request = AgentInvocationRequest.create(
            invocation_id=AgentInvocationId("invoke-selection-1"),
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
            instruction="Use configured provider selection.",
            requested_at=requested_at,
        )
        update = ContextUpdateInfo.create(
            update_id=ContextUpdateId("update-selection-1"),
            workspace_id=WorkspaceId("workspace-1"),
            update_kind=ContextUpdateKind.USER_MESSAGE,
            summary="Captured request.",
            created_at=requested_at,
        )

        invocation = adapter.build_model_invocation(
            request=request,
            context=context_record.context,
            user_context_update=update,
        )

        self.assertEqual(invocation.provider_name, "deterministic")
        self.assertEqual(invocation.model_name, "deterministic-text")
        self.assertEqual(invocation.system_prompt, "Use platform context.")
        self.assertEqual(invocation.parameters["temperature"], 0)

    def test_selection_rejects_empty_required_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "provider_name"):
            ModelProviderSelection(
                provider_name=" ",
                model_name="deterministic-text",
            )

        with self.assertRaisesRegex(ValueError, "model_name"):
            ModelProviderSelection(
                provider_name="deterministic",
                model_name="",
            )

        with self.assertRaisesRegex(ValueError, "system_prompt"):
            ModelProviderSelection(
                provider_name="deterministic",
                model_name="deterministic-text",
                system_prompt=" ",
            )


if __name__ == "__main__":
    unittest.main()
