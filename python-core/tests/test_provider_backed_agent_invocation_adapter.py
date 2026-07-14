from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.provider_backed_agent_invocation_adapter import (
    ProviderBackedAgentInvocationAdapter,
)
from agent_os.application.services.single_turn_platform_runtime import (
    SingleTurnPlatformRuntime,
)
from agent_os.domain.entities.context import ContextUpdateInfo, ContextUpdateKind
from agent_os.domain.entities.invocation import (
    AgentInvocationRequest,
    AgentInvocationResultStatus,
)
from agent_os.domain.entities.model import (
    EmbeddingRequest,
    EmbeddingResult,
    ModelInvocation,
    ModelOutput,
)
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextUpdateId,
    PlatformEventId,
    WorkspaceId,
)
from agent_os.infrastructure.adapters.models import DeterministicModelProvider
from agent_os.infrastructure.persistence.context_update_events import (
    SqliteContextUpdateEventRecorder,
)
from agent_os.infrastructure.persistence.invocation_records import (
    SqliteAgentInvocationRecordStore,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteContextStateStore,
)
from support.platform_invocation_fixtures import (
    connect_in_memory_platform,
    platform_event_count,
    seed_minimal_invocation_platform_state,
)


class ProviderBackedAgentInvocationAdapterTests(unittest.TestCase):
    def test_build_model_invocation_maps_request_context_and_update(self) -> None:
        provider = RecordingModelProvider()
        adapter = ProviderBackedAgentInvocationAdapter(
            model_provider=provider,
            provider_name="recording",
            model_name="recording-text",
            system_prompt="Use only the platform context.",
            parameters={"temperature": 0},
        )
        request = AgentInvocationRequest.create(
            invocation_id=AgentInvocationId("invoke-1"),
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
            instruction="Capture this task.",
            requested_at=datetime(2026, 6, 4, 18, 0, tzinfo=timezone.utc),
            metadata={"surface": "unit"},
        )
        context_update = ContextUpdateInfo.create(
            update_id=ContextUpdateId("update-1"),
            workspace_id=WorkspaceId("workspace-1"),
            update_kind=ContextUpdateKind.USER_MESSAGE,
            summary="Captured user request.",
            created_at=request.requested_at,
        )
        context = _context_from_seed()

        model_invocation = adapter.build_model_invocation(
            request=request,
            context=context,
            user_context_update=context_update,
        )

        self.assertEqual(model_invocation.provider_name, "recording")
        self.assertEqual(model_invocation.model_name, "recording-text")
        self.assertEqual(model_invocation.system_prompt, "Use only the platform context.")
        self.assertEqual(model_invocation.messages[0].content, "Capture this task.")
        self.assertEqual(model_invocation.parameters["temperature"], 0)
        self.assertEqual(model_invocation.parameters["workspace_id"], "workspace-1")
        self.assertEqual(model_invocation.parameters["context_id"], "context-1")
        self.assertEqual(model_invocation.parameters["context_update_id"], "update-1")
        self.assertEqual(
            model_invocation.parameters["request_metadata"],
            {"surface": "unit"},
        )

    def test_runtime_can_use_provider_backed_adapter(self) -> None:
        connection = connect_in_memory_platform()
        seed_minimal_invocation_platform_state(connection)
        context_record = SqliteContextStateStore(connection).get_context_state(
            WorkspaceId("workspace-1")
        )
        assert context_record is not None
        adapter = ProviderBackedAgentInvocationAdapter(
            model_provider=DeterministicModelProvider(),
            provider_name="deterministic",
            model_name="deterministic-text",
        )
        request = AgentInvocationRequest.create(
            invocation_id=AgentInvocationId("invoke-2"),
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
            instruction="Use the model provider boundary.",
            requested_at=datetime(2026, 6, 4, 18, 5, tzinfo=timezone.utc),
        )

        result = SingleTurnPlatformRuntime(
            context_update_recorder=SqliteContextUpdateEventRecorder(connection),
            agent_invocation_adapter=adapter,
        ).run_single_turn(
            context=context_record.context,
            invocation_request=request,
            update_id=ContextUpdateId("update-2"),
            event_id=PlatformEventId("event-2"),
        )

        self.assertEqual(result.invocation_result.status, AgentInvocationResultStatus.SUCCEEDED)
        self.assertEqual(
            result.invocation_result.output_text,
            "Deterministic model response: Use the model provider boundary.",
        )
        self.assertTrue(result.invocation_result.output_payload["model_invoked"])
        self.assertFalse(result.invocation_result.output_payload["tool_invoked"])
        self.assertEqual(
            result.invocation_result.output_payload["provider_name"],
            "deterministic",
        )
        self.assertEqual(
            result.invocation_result.metadata["source"],
            "provider_backed_agent_invocation_adapter",
        )
        self.assertEqual(result.recorded_context_update.source_event_sequence, 1)

    def test_runtime_records_failed_result_when_provider_raises(self) -> None:
        connection = connect_in_memory_platform()
        seed_minimal_invocation_platform_state(connection)
        context_record = SqliteContextStateStore(connection).get_context_state(
            WorkspaceId("workspace-1")
        )
        assert context_record is not None
        invocation_store = SqliteAgentInvocationRecordStore(connection)
        adapter = ProviderBackedAgentInvocationAdapter(
            model_provider=FailingModelProvider(),
            provider_name="failing",
            model_name="failing-text",
        )
        request = AgentInvocationRequest.create(
            invocation_id=AgentInvocationId("invoke-failed-1"),
            workspace_id=WorkspaceId("workspace-1"),
            agent_id=AgentId("agent-1"),
            instruction="Use a failing provider.",
            requested_at=datetime(2026, 6, 4, 18, 10, tzinfo=timezone.utc),
        )

        result = SingleTurnPlatformRuntime(
            context_update_recorder=SqliteContextUpdateEventRecorder(connection),
            agent_invocation_recorder=invocation_store,
            agent_invocation_adapter=adapter,
        ).run_single_turn(
            context=context_record.context,
            invocation_request=request,
            update_id=ContextUpdateId("update-failed-1"),
            event_id=PlatformEventId("event-context-failed-1"),
            invocation_event_id=PlatformEventId("event-invoke-failed-1"),
        )

        self.assertEqual(result.invocation_result.status, AgentInvocationResultStatus.FAILED)
        self.assertEqual(result.invocation_result.error_message, "provider unavailable")
        self.assertFalse(result.invocation_result.output_payload["model_invoked"])
        self.assertEqual(result.recorded_context_update.source_event_sequence, 1)
        self.assertEqual(result.agent_invocation_requested_event_sequence, 2)
        self.assertEqual(result.agent_invocation_event_sequence, 3)
        self.assertEqual(platform_event_count(connection), 3)
        stored_context = SqliteContextStateStore(connection).get_context_state(
            WorkspaceId("workspace-1")
        )
        self.assertIsNotNone(stored_context)
        assert stored_context is not None
        self.assertEqual(stored_context.update_count, 1)
        record = invocation_store.get_agent_invocation_record(
            AgentInvocationId("invoke-failed-1")
        )
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.status, "failed")
        self.assertEqual(record.source_event_sequence, 3)


def _context_from_seed():
    connection = connect_in_memory_platform()
    seed_minimal_invocation_platform_state(connection)
    context_record = SqliteContextStateStore(connection).get_context_state(
        WorkspaceId("workspace-1")
    )
    assert context_record is not None
    return context_record.context


class RecordingModelProvider:
    def __init__(self) -> None:
        self.requests: list[ModelInvocation] = []

    async def generate(self, request: ModelInvocation) -> ModelOutput:
        self.requests.append(request)
        return ModelOutput(
            model_name=request.model_name,
            content="Recorded provider output.",
            metadata={"provider_name": request.provider_name},
        )

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        return EmbeddingResult(
            model_name=request.model_name,
            vectors=tuple((0.0,) for _ in request.inputs),
        )

    async def list_models(self) -> tuple[str, ...]:
        return ("recording-text",)


class FailingModelProvider:
    async def generate(self, request: ModelInvocation) -> ModelOutput:
        raise RuntimeError("provider unavailable")

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        return EmbeddingResult(
            model_name=request.model_name,
            vectors=tuple((0.0,) for _ in request.inputs),
        )

    async def list_models(self) -> tuple[str, ...]:
        return ("failing-text",)


if __name__ == "__main__":
    unittest.main()
