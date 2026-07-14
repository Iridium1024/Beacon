from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.application.services.agent_runtime_profile import AgentRuntimeProfile
from agent_os.application.services.agent_runtime_access import (
    AgentRuntimeAccessProfile,
    AgentRuntimeKind,
    DelegatedContextDeliveryPolicy,
    RuntimeFilePermission,
    RuntimeMemoryPolicy,
    RuntimeNetworkPolicy,
    RuntimeToolPermission,
)
from agent_os.application.services.model_provider_selection import ModelProviderSelection
from agent_os.domain.entities.agent import AgentCapability, AgentRegistration
from agent_os.domain.entities.model import (
    ModelCapability,
    ModelCapabilityKind,
    ModelGenerationOptions,
    ModelReasoningOptions,
    ModelRuntimeConstraints,
)
from agent_os.domain.value_objects.identifiers import AgentId, WorkspaceId


class ModelRuntimeProfileTests(unittest.TestCase):
    def test_generation_options_validate_and_convert_to_provider_parameters(self) -> None:
        options = ModelGenerationOptions.from_mapping(
            {
                "temperature": 0,
                "maxTokens": 128,
                "top_p": 0.9,
                "stop": ["DONE"],
            }
        )

        self.assertEqual(
            options.to_parameters(),
            {
                "temperature": 0.0,
                "max_tokens": 128,
                "top_p": 0.9,
                "stop": ["DONE"],
            },
        )

        with self.assertRaisesRegex(ValueError, "max_tokens"):
            ModelGenerationOptions(max_tokens=0)
        with self.assertRaisesRegex(ValueError, "unsupported"):
            ModelGenerationOptions.from_mapping({"provider_specific": True})

    def test_reasoning_and_runtime_constraints_are_reserved_metadata(self) -> None:
        reasoning = ModelReasoningOptions.from_mapping(
            {
                "reasoningEffort": "medium",
                "thinkingBudgetTokens": 256,
                "verbosity": "concise",
            }
        )
        constraints = ModelRuntimeConstraints.from_mapping(
            {
                "contextWindowTokens": 8192,
                "precision": "fp16",
                "quantization": "int8",
            }
        )
        capability = ModelCapability(
            kind=ModelCapabilityKind.REASONING,
            implemented=False,
            metadata={"provider_mapping": "future"},
        )

        self.assertEqual(reasoning.to_metadata()["reasoning_effort"], "medium")
        self.assertEqual(constraints.to_metadata()["precision"], "fp16")
        self.assertEqual(capability.to_metadata()["kind"], "reasoning")
        self.assertFalse(capability.to_metadata()["implemented"])

    def test_agent_profile_builds_provider_selection_without_credential_values(self) -> None:
        registration = _registration(
            agent_id="agent-reviewer",
            name="Reviewer",
            runtime_config={
                "profile": {
                    "profileName": "review-profile",
                    "roleName": "reviewer",
                    "systemPrompt": "Review the answer.",
                    "providerName": "openai-compatible",
                    "modelName": "fake-chat-model",
                    "generationOptions": {
                        "temperature": 0,
                        "max_tokens": 64,
                    },
                    "reasoningOptions": {
                        "reasoning_effort": "medium",
                    },
                    "runtimeKind": "provider_connection",
                    "bindingId": "binding-reviewer",
                    "connectionId": "connection-shared",
                    "metadata": {
                        "credential_env_var": "AGENT_OS_OPENAI_COMPAT_API_KEY",
                    },
                },
            },
        )
        default_selection = ModelProviderSelection(
            provider_name="openai-compatible",
            model_name="fake-chat-model",
            system_prompt="Default prompt.",
            parameters={"temperature": 1, "top_p": 1},
        )

        profile = AgentRuntimeProfile.from_registration(registration)
        selection = profile.provider_selection(default_selection)

        self.assertEqual(profile.profile_name, "review-profile")
        self.assertEqual(profile.role_name, "reviewer")
        self.assertEqual(selection.system_prompt, "Review the answer.")
        self.assertEqual(selection.parameters["temperature"], 0.0)
        self.assertEqual(selection.parameters["max_tokens"], 64)
        self.assertEqual(selection.parameters["top_p"], 1)
        self.assertEqual(selection.runtime_metadata["profile_name"], "review-profile")
        self.assertEqual(
            selection.runtime_metadata["reasoning_options_reserved"],
            "true",
        )
        self.assertEqual(
            selection.runtime_access_profile.runtime_kind,
            AgentRuntimeKind.PROVIDER_BACKED_MODEL,
        )
        self.assertEqual(
            selection.runtime_metadata["runtime_access_kind"],
            "provider_backed_model",
        )
        self.assertEqual(
            selection.runtime_metadata["runtime_access_delegated_context"],
            "none",
        )

    def test_agent_profile_rejects_inline_credential_values(self) -> None:
        registration = _registration(
            agent_id="agent-secret",
            runtime_config={
                "profile": {
                    "providerName": "openai-compatible",
                    "modelName": "fake-chat-model",
                    "apiKey": "must-not-be-stored",
                },
            },
        )

        with self.assertRaisesRegex(ValueError, "credential values"):
            AgentRuntimeProfile.from_registration(registration)

    def test_agent_profile_parses_runtime_access_permission_contract(self) -> None:
        registration = _registration(
            agent_id="agent-native",
            runtime_config={
                "profile": {
                    "profileName": "native-profile",
                    "runtimeKind": "agent-native-runtime",
                    "runtimeAccess": {
                        "delegatedContextDelivery": "bounded-materialized-segments",
                        "toolPermissions": [
                            "declared_tools_only",
                            "skill_repository_read",
                        ],
                        "allowedToolNames": ["context_reader"],
                        "allowedSkillRefs": ["skill://review"],
                        "filePermission": "file-ref-metadata-only",
                        "memoryPolicy": "runtime-local-ephemeral",
                        "memoryNamespace": "agent-native",
                        "memoryQuotaMb": 16,
                        "networkPolicy": "disabled",
                    },
                },
            },
        )

        profile = AgentRuntimeProfile.from_registration(registration)
        access = profile.runtime_access_profile

        self.assertEqual(access.runtime_kind, AgentRuntimeKind.AGENT_NATIVE_RUNTIME)
        self.assertEqual(
            access.delegated_context_delivery,
            DelegatedContextDeliveryPolicy.BOUNDED_MATERIALIZED_SEGMENTS,
        )
        self.assertEqual(
            access.tool_permissions,
            (
                RuntimeToolPermission.DECLARED_TOOLS_ONLY,
                RuntimeToolPermission.SKILL_REPOSITORY_READ,
            ),
        )
        self.assertEqual(access.file_permission, RuntimeFilePermission.FILE_REF_METADATA_ONLY)
        self.assertEqual(access.memory_policy, RuntimeMemoryPolicy.RUNTIME_LOCAL_EPHEMERAL)
        self.assertEqual(access.network_policy, RuntimeNetworkPolicy.DISABLED)
        self.assertEqual(access.memory_quota_mb, 16)
        self.assertEqual(
            profile.runtime_metadata()["runtime_access_profile_reserved"],
            "true",
        )

    def test_runtime_access_contract_rejects_credentials_and_websocket_transport(self) -> None:
        with self.assertRaisesRegex(ValueError, "credential values"):
            AgentRuntimeAccessProfile.from_mapping(
                {
                    "runtimeKind": "agent-native-runtime",
                    "metadata": {"authorization": "Bearer x"},
                }
            )

        with self.assertRaisesRegex(ValueError, "WebSocket"):
            AgentRuntimeAccessProfile.from_mapping(
                {
                    "runtimeKind": "agent-native-runtime",
                    "runtimeConnectionRef": "ws://127.0.0.1:9999/session",
                }
            )

    def test_provider_backed_runtime_does_not_gain_agent_native_permissions(self) -> None:
        with self.assertRaisesRegex(ValueError, "provider-backed runtime"):
            AgentRuntimeAccessProfile.from_mapping(
                {
                    "runtimeKind": "provider-backed-model",
                    "delegatedContextDelivery": "bounded_materialized_segments",
                }
            )

        with self.assertRaisesRegex(ValueError, "agent-native tool permissions"):
            AgentRuntimeAccessProfile.from_mapping(
                {
                    "runtimeKind": "provider-backed-model",
                    "toolPermissions": ["declared_tools_only"],
                }
            )


def _registration(
    *,
    agent_id: str,
    name: str = "Agent",
    runtime_config: dict[str, object],
) -> AgentRegistration:
    return AgentRegistration.register(
        agent_id=AgentId(agent_id),
        workspace_id=WorkspaceId("workspace-1"),
        name=name,
        description="Handles profile tests.",
        capabilities=(
            AgentCapability(
                name="single-turn-status",
                description="Captures single-turn requests.",
            ),
        ),
        created_at=datetime(2026, 6, 11, 10, 0, tzinfo=timezone.utc),
        default_model="fake-chat-model",
        runtime_config=runtime_config,
    )


if __name__ == "__main__":
    unittest.main()
