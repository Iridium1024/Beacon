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
)
from agent_os.application.services.context_management_profile import (
    ContextAccessScope,
    ContextAssemblyError,
    ContextAssemblyPlanner,
    ContextAssemblyRequest,
    ContextContentKind,
    ContextContentPacketDeliveryMode,
    ContextContentState,
    ContextConversationMessageSnapshot,
    ContextManagementProfile,
    ContextManagementProfileResolver,
    ContextManagementStrategy,
    ContextMaterializationLoadState,
    ContextMaterializedSegmentKind,
    ContextOverflowMode,
    ContextSharedContextUpdateSnapshot,
    ContextTaskContextSnapshot,
    ContextWindowSelectionPolicy,
)
from agent_os.application.services.model_provider_selection import (
    ModelProviderSelection,
    build_provider_backed_agent_invocation_adapter,
)
from agent_os.domain.entities.agent import AgentCapability, AgentRegistration
from agent_os.domain.entities.context import ContextUpdateInfo, ContextUpdateKind
from agent_os.domain.entities.invocation import AgentInvocationRequest
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
    WorkspaceId,
)
from agent_os.infrastructure.persistence.materialized_state import (
    SqliteContextStateStore,
)
from support.platform_invocation_fixtures import (
    connect_in_memory_platform,
    seed_minimal_invocation_platform_state,
)


class ContextManagementProfileTests(unittest.TestCase):
    def test_default_profile_is_pass_through_with_guardrails(self) -> None:
        profile = ContextManagementProfile.default()

        self.assertEqual(profile.strategy, ContextManagementStrategy.PASS_THROUGH)
        self.assertEqual(profile.max_input_tokens, 8192)
        self.assertEqual(profile.allowed_context_scopes, ("current_user_instruction",))
        self.assertEqual(
            profile.window_selection_policy,
            ContextWindowSelectionPolicy.METADATA_ONLY_AUTHORIZED_REFS,
        )
        self.assertEqual(
            profile.content_packet_delivery_mode,
            ContextContentPacketDeliveryMode.AUDIT_ONLY,
        )
        self.assertFalse(profile.include_conversation_history)
        self.assertFalse(profile.include_shared_context)
        self.assertEqual(profile.on_overflow, ContextOverflowMode.FAIL_WITH_EXPLANATION)

    def test_strategy_labels_and_reserved_configs_parse_without_connections(self) -> None:
        for label, expected in (
            ("none", ContextManagementStrategy.PASS_THROUGH),
            ("pass-through", ContextManagementStrategy.PASS_THROUGH),
            ("recent-window", ContextManagementStrategy.RECENT_WINDOW),
            ("platform-summary", ContextManagementStrategy.PLATFORM_SUMMARY),
            ("provider-native", ContextManagementStrategy.PROVIDER_NATIVE),
            (
                "external-context-engine",
                ContextManagementStrategy.EXTERNAL_CONTEXT_ENGINE,
            ),
            ("hybrid", ContextManagementStrategy.HYBRID),
        ):
            with self.subTest(label=label):
                profile = ContextManagementProfile.from_mapping({"strategy": label})
                self.assertEqual(profile.strategy, expected)

        profile = ContextManagementProfile.from_mapping(
            {
                "strategy": "provider-native",
                "providerNative": {
                    "sessionMode": "reserved",
                    "compactionMode": "manual",
                    "remoteSessionRefMode": "metadata-only",
                },
                "externalContextEngine": {
                    "engineId": "future-engine",
                    "mode": "metadata-only",
                },
                "agentPrivateMemory": {
                    "enabled": True,
                    "quotaMb": 16,
                    "ttlSeconds": 3600,
                },
                "allowedContextScopes": [
                    "current_user_instruction",
                    "agent_private_memory",
                ],
            }
        )

        self.assertEqual(profile.provider_native.session_mode, "reserved")
        self.assertEqual(profile.external_context_engine.engine_id, "future-engine")
        self.assertTrue(profile.agent_private_memory.enabled)
        self.assertIn("provider_native", profile.to_metadata())

    def test_invalid_profile_values_have_stable_errors(self) -> None:
        invalid_configs = (
            ({"strategy": "auto-magic"}, "strategy"),
            ({"maxInputTokens": 0}, "maxInputTokens"),
            ({"recentTokenBudget": 0}, "recentTokenBudget"),
            ({"agentPrivateMemory": {"quotaMb": 0}}, "quotaMb"),
            ({"onOverflow": "silently_drop"}, "onOverflow"),
            ({"windowSelectionPolicy": "load_everything"}, "windowSelectionPolicy"),
            ({"contentPacketDeliveryMode": "auto-send-to-agent"}, "contentPacketDeliveryMode"),
            ({"allowedContextScopes": ["current_user_instruction", ""]}, "non-empty"),
        )

        for config, pattern in invalid_configs:
            with self.subTest(config=config):
                with self.assertRaisesRegex(ValueError, pattern):
                    ContextManagementProfile.from_mapping(config)

    def test_context_profile_rejects_inline_credentials(self) -> None:
        configs = (
            {"providerNative": {"apiKey": "must-not-be-stored"}},
            {"externalContextEngine": {"metadata": {"authorization": "Bearer x"}}},
            {"agentPrivateMemory": {"metadata": {"sessionToken": "x"}}},
        )

        for config in configs:
            with self.subTest(config=config):
                with self.assertRaisesRegex(ValueError, "credential values"):
                    ContextManagementProfile.from_mapping(config)

    def test_profile_resolver_applies_documented_precedence(self) -> None:
        resolution = ContextManagementProfileResolver().resolve(
            workspace_default={
                "strategy": "pass-through",
                "maxInputTokens": 1000,
                "allowedContextScopes": ["current_user_instruction"],
            },
            provider_runtime_default={"strategy": "recent-window"},
            agent_profile={
                "includeConversationHistory": True,
                "allowedContextScopes": [
                    "current_user_instruction",
                    "recent_messages",
                ],
            },
            invocation_override={"maxInputTokens": 128},
        )

        self.assertEqual(resolution.precedence[-1], "invocation")
        self.assertEqual(resolution.profile.strategy, ContextManagementStrategy.RECENT_WINDOW)
        self.assertEqual(resolution.profile.max_input_tokens, 128)
        self.assertTrue(resolution.profile.include_conversation_history)


class ContextAssemblyPlannerTests(unittest.TestCase):
    def test_planner_records_pass_through_scopes_without_prompt_injection(self) -> None:
        profile = ContextManagementProfile.default()

        plan = ContextAssemblyPlanner().plan(
            profile=profile,
            request=_assembly_request("Use current request only."),
        )

        self.assertTrue(plan.pass_through)
        self.assertTrue(plan.within_budget)
        self.assertFalse(plan.requires_compaction)
        self.assertEqual(plan.exposed_context_scopes, ("current_user_instruction",))
        metadata = plan.to_metadata()
        self.assertEqual(metadata["strategy"], "pass-through")
        self.assertEqual(
            metadata["requested_context_scopes"],
            ["current_user_instruction"],
        )
        self.assertEqual(
            metadata["authorized_context_scopes"],
            ["current_user_instruction"],
        )
        self.assertEqual(metadata["denied_context_scopes"], [])
        self.assertEqual(
            metadata["source_refs"],
            [
                {
                    "scope": "current_user_instruction",
                    "ref_type": "context_update",
                    "ref_id": "update-1",
                }
            ],
        )
        self.assertEqual(
            metadata["selected_source_refs"],
            [
                {
                    "scope": "current_user_instruction",
                    "ref_type": "context_update",
                    "ref_id": "update-1",
                }
            ],
        )
        self.assertEqual(metadata["omitted_source_refs"], [])
        self.assertEqual(
            metadata["window_selection"]["denied_scopes_excluded"],
            [],
        )
        self.assertEqual(metadata["content_loaded"], False)
        content_packet = metadata["content_packet"]
        self.assertEqual(content_packet["packet_id"], "context-packet-invoke-1")
        self.assertEqual(
            content_packet["policy_mode"],
            "metadata_only_content_packet_contract",
        )
        self.assertEqual(content_packet["delivery_mode"], "audit_only")
        self.assertFalse(content_packet["provider_payload_required"])
        self.assertEqual(
            content_packet["packet_items"],
            [
                {
                    "item_id": "item-1-current_user_instruction-context_update-update-1",
                    "source_ref": {
                        "scope": "current_user_instruction",
                        "ref_type": "context_update",
                        "ref_id": "update-1",
                    },
                    "content_state": ContextContentState.ALREADY_IN_USER_MESSAGE.value,
                    "content_kind": ContextContentKind.CURRENT_USER_INSTRUCTION.value,
                    "estimated_tokens": 0,
                    "content_loaded": False,
                    "metadata": {
                        "source_ref_only": True,
                        "content_text_included": False,
                        "content_loaded": False,
                        "already_in_user_message": True,
                    },
                }
            ],
        )
        self.assertEqual(content_packet["excluded_refs"], [])
        self.assertEqual(content_packet["estimated_tokens"], 0)
        self.assertFalse(
            content_packet["redaction_metadata"]["current_user_instruction_copied"]
        )
        self.assertEqual(
            metadata["content_packet_items"],
            content_packet["packet_items"],
        )
        self.assertEqual(metadata["excluded_content_refs"], [])
        self.assertFalse(metadata["provider_payload_required"])
        materialization = metadata["materialization"]
        self.assertEqual(
            materialization["source_packet_id"],
            content_packet["packet_id"],
        )
        self.assertFalse(materialization["content_loaded"])
        self.assertFalse(metadata["materialization_content_loaded"])
        self.assertFalse(metadata["provider_prompt_injected"])
        self.assertFalse(metadata["agent_native_runtime_connected"])
        self.assertEqual(
            materialization["materialized_segments"],
            [
                {
                    "segment_id": (
                        "segment-1-item-1-current_user_instruction-"
                        "context_update-update-1"
                    ),
                    "source_packet_item_id": (
                        "item-1-current_user_instruction-context_update-update-1"
                    ),
                    "source_ref": {
                        "scope": "current_user_instruction",
                        "ref_type": "context_update",
                        "ref_id": "update-1",
                    },
                    "segment_kind": "current_user_message_marker",
                    "load_state": "already_in_user_message",
                    "estimated_tokens": 0,
                    "content_loaded": False,
                    "metadata": {
                        "provider_user_message_already_exists": True,
                        "current_user_instruction_copied": False,
                    },
                }
            ],
        )
        self.assertNotIn("text", materialization["materialized_segments"][0])

    def test_planner_enforces_scope_allowlist_and_budget_boundary(self) -> None:
        profile = ContextManagementProfile.default()

        plan = ContextAssemblyPlanner().plan(
            profile=profile,
            request=_assembly_request(
                "Use recent history.",
                requested_context_scopes=("recent_messages",),
            ),
        )

        self.assertEqual(plan.exposed_context_scopes, ("current_user_instruction",))
        self.assertEqual(
            plan.to_metadata()["requested_context_scopes"],
            ["current_user_instruction", "recent_messages"],
        )
        self.assertEqual(
            plan.to_metadata()["denied_context_scopes"],
            [
                {
                    "scope": "recent_messages",
                    "reason": "not_allowed_by_profile",
                }
            ],
        )
        selected_refs = plan.to_metadata()["selected_source_refs"]
        self.assertEqual(
            selected_refs,
            [
                {
                    "scope": "current_user_instruction",
                    "ref_type": "context_update",
                    "ref_id": "update-1",
                }
            ],
        )
        self.assertEqual(
            plan.to_metadata()["window_selection"]["denied_scopes_excluded"],
            [
                {
                    "scope": "recent_messages",
                    "reason": "not_allowed_by_profile",
                }
            ],
        )
        packet_items = plan.to_metadata()["content_packet"]["packet_items"]
        self.assertEqual(
            [item["source_ref"]["scope"] for item in packet_items],
            ["current_user_instruction"],
        )
        self.assertEqual(
            plan.to_metadata()["content_packet"]["excluded_refs"],
            [
                {
                    "reason": "not_allowed_by_profile",
                    "content_state": "denied_by_authorization",
                    "scope": "recent_messages",
                    "metadata": {
                        "excluded_by": "authorization",
                        "content_item_created": False,
                    },
                }
            ],
        )
        self.assertEqual(
            [
                segment["source_ref"]["scope"]
                for segment in plan.to_metadata()["materialized_segments"]
            ],
            ["current_user_instruction"],
        )

        with self.assertRaisesRegex(ContextAssemblyError, "must be one of"):
            ContextAssemblyPlanner().plan(
                profile=profile,
                request=_assembly_request(
                    "Use invalid scope.",
                    requested_context_scopes=("unknown_scope",),
                ),
            )

        tiny_profile = ContextManagementProfile.from_mapping({"maxInputTokens": 1})
        with self.assertRaisesRegex(ContextAssemblyError, "maxInputTokens"):
            ContextAssemblyPlanner().plan(
                profile=tiny_profile,
                request=_assembly_request("This request is longer than one token."),
            )

    def test_planner_keeps_reserved_compaction_explicitly_unsupported(self) -> None:
        profile = ContextManagementProfile.from_mapping(
            {
                "maxInputTokens": 1,
                "onOverflow": "compact_then_retry",
            }
        )

        with self.assertRaisesRegex(ContextAssemblyError, "reserved"):
            ContextAssemblyPlanner().plan(
                profile=profile,
                request=_assembly_request("This request needs compaction."),
            )

        trim_profile = ContextManagementProfile.from_mapping(
            {
                "maxInputTokens": 1,
                "onOverflow": "trim_to_budget",
            }
        )
        plan = ContextAssemblyPlanner().plan(
            profile=trim_profile,
            request=_assembly_request("This request may be trimmed later."),
        )
        self.assertFalse(plan.within_budget)
        self.assertEqual(plan.overflow_action, ContextOverflowMode.TRIM_TO_BUDGET)

    def test_profile_allowlist_does_not_bypass_runtime_source_authorization(self) -> None:
        profile = ContextManagementProfile.from_mapping(
            {
                "strategy": "recent-window",
                "recentMessageLimit": 4,
                "includeConversationHistory": True,
                "allowedContextScopes": [
                    "current_user_instruction",
                    "recent_messages",
                ],
            }
        )

        denied_plan = ContextAssemblyPlanner().plan(
            profile=profile,
            request=_assembly_request("Use history without a conversation id."),
        )

        self.assertEqual(
            denied_plan.to_metadata()["denied_context_scopes"],
            [
                {
                    "scope": "recent_messages",
                    "reason": "conversation_id_required",
                }
            ],
        )
        self.assertNotIn(
            "recent_messages",
            denied_plan.to_metadata()["authorized_context_scopes"],
        )

        authorized_plan = ContextAssemblyPlanner().plan(
            profile=profile,
            request=_assembly_request(
                "Use bounded conversation history.",
                conversation_id="conversation-1",
            ),
        )

        self.assertIn(
            "recent_messages",
            authorized_plan.to_metadata()["authorized_context_scopes"],
        )
        self.assertIn(
            {
                "scope": "recent_messages",
                "ref_type": "conversation",
                "ref_id": "conversation-1",
                "metadata": {"content_loaded": False},
            },
            authorized_plan.to_metadata()["source_refs"],
        )
        self.assertIn(
            {
                "scope": "recent_messages",
                "ref_type": "conversation",
                "ref_id": "conversation-1",
                "metadata": {"content_loaded": False},
            },
            authorized_plan.to_metadata()["selected_source_refs"],
        )
        self.assertEqual(
            authorized_plan.to_metadata()["window_budget"]["recent_message_limit"],
            4,
        )
        content_packet = authorized_plan.to_metadata()["content_packet"]
        recent_items = [
            item
            for item in content_packet["packet_items"]
            if item["source_ref"]["scope"] == "recent_messages"
        ]
        self.assertEqual(
            recent_items,
            [
                {
                    "item_id": "item-2-recent_messages-conversation-conversation-1",
                    "source_ref": {
                        "scope": "recent_messages",
                        "ref_type": "conversation",
                        "ref_id": "conversation-1",
                        "metadata": {"content_loaded": False},
                    },
                    "content_state": "not_loaded",
                    "content_kind": "conversation_ref",
                    "estimated_tokens": 0,
                    "content_loaded": False,
                    "metadata": {
                        "source_ref_only": True,
                        "content_text_included": False,
                        "content_loaded": False,
                        "loader_connected": False,
                        "conversation_messages_loaded": False,
                    },
                }
            ],
        )
        self.assertFalse(
            content_packet["redaction_metadata"]["conversation_messages_loaded"]
        )
        self.assertEqual(content_packet["budget_metadata"]["recent_message_limit"], 4)
        recent_segments = [
            segment
            for segment in authorized_plan.to_metadata()["materialized_segments"]
            if segment["source_ref"]["scope"] == "recent_messages"
        ]
        self.assertEqual(recent_segments[0]["segment_kind"], "conversation_message_window")
        self.assertEqual(recent_segments[0]["load_state"], "loader_not_connected")
        self.assertFalse(recent_segments[0]["content_loaded"])
        self.assertFalse(
            authorized_plan.to_metadata()["materialization"]["redaction_metadata"][
                "conversation_messages_loaded"
            ]
        )

    def test_recent_messages_materialization_uses_bounded_local_snapshots(self) -> None:
        profile = ContextManagementProfile.from_mapping(
            {
                "strategy": "recent-window",
                "recentMessageLimit": 2,
                "recentTokenBudget": 20,
                "includeConversationHistory": True,
                "allowedContextScopes": [
                    "current_user_instruction",
                    "recent_messages",
                ],
            }
        )

        plan = ContextAssemblyPlanner().plan(
            profile=profile,
            request=_assembly_request(
                "Use bounded conversation history.",
                conversation_id="conversation-1",
                conversation_messages=(
                    ContextConversationMessageSnapshot(
                        message_id="message-1",
                        role="user",
                        content="first message",
                        sequence=1,
                    ),
                    ContextConversationMessageSnapshot(
                        message_id="message-2",
                        role="assistant",
                        content="second message",
                        sequence=2,
                    ),
                    ContextConversationMessageSnapshot(
                        message_id="message-3",
                        role="user",
                        content="third message",
                        sequence=3,
                    ),
                ),
            ),
        )
        materialization = plan.to_metadata()["materialization"]
        recent_segments = [
            segment
            for segment in materialization["materialized_segments"]
            if segment["segment_kind"] == "conversation_message_window"
        ]

        self.assertEqual(len(recent_segments), 1)
        self.assertEqual(recent_segments[0]["load_state"], "loaded")
        self.assertEqual(
            recent_segments[0]["text"],
            "assistant: second message\nuser: third message",
        )
        self.assertTrue(recent_segments[0]["content_loaded"])
        self.assertTrue(materialization["content_loaded"])
        self.assertTrue(
            materialization["redaction_metadata"]["conversation_messages_loaded"]
        )
        self.assertFalse(plan.to_metadata()["provider_prompt_injected"])

    def test_referenced_files_scope_records_refs_without_file_body_access(self) -> None:
        profile = ContextManagementProfile.from_mapping(
            {
                "strategy": "recent-window",
                "includeFileReferences": True,
                "allowedContextScopes": [
                    "current_user_instruction",
                    "referenced_files",
                ],
            }
        )

        denied_plan = ContextAssemblyPlanner().plan(
            profile=profile,
            request=_assembly_request("Use referenced files without refs."),
        )
        self.assertEqual(
            denied_plan.to_metadata()["denied_context_scopes"],
            [
                {
                    "scope": "referenced_files",
                    "reason": "file_reference_required",
                }
            ],
        )

        authorized_plan = ContextAssemblyPlanner().plan(
            profile=profile,
            request=_assembly_request(
                "Use referenced files by audit ref.",
                file_references=("file-ref-1",),
            ),
        )

        self.assertIn(
            {
                "scope": "referenced_files",
                "ref_type": "file_reference",
                "ref_id": "file-ref-1",
                "metadata": {"content_loaded": False},
            },
            authorized_plan.to_metadata()["source_refs"],
        )
        self.assertIn(
            {
                "scope": "referenced_files",
                "ref_type": "file_reference",
                "ref_id": "file-ref-1",
                "metadata": {"content_loaded": False},
            },
            authorized_plan.to_metadata()["selected_source_refs"],
        )
        self.assertFalse(authorized_plan.to_metadata()["content_loaded"])
        file_items = [
            item
            for item in authorized_plan.to_metadata()["content_packet"]["packet_items"]
            if item["source_ref"]["scope"] == "referenced_files"
        ]
        self.assertEqual(file_items[0]["content_kind"], "file_ref")
        self.assertEqual(file_items[0]["content_state"], "not_loaded")
        self.assertFalse(file_items[0]["metadata"]["file_body_loaded"])
        self.assertFalse(
            authorized_plan.to_metadata()["content_packet"]["redaction_metadata"][
                "file_bodies_loaded"
            ]
        )
        file_segments = [
            segment
            for segment in authorized_plan.to_metadata()["materialized_segments"]
            if segment["source_ref"]["scope"] == "referenced_files"
        ]
        self.assertEqual(file_segments[0]["segment_kind"], "file_ref_marker")
        self.assertEqual(file_segments[0]["load_state"], "deferred_file_body")
        self.assertFalse(file_segments[0]["content_loaded"])
        self.assertNotIn("text", file_segments[0])
        self.assertFalse(
            authorized_plan.to_metadata()["materialization"]["redaction_metadata"][
                "file_bodies_loaded"
            ]
        )

    def test_pass_through_window_selects_only_current_user_instruction(self) -> None:
        profile = ContextManagementProfile.from_mapping(
            {
                "includeSharedContext": True,
                "allowedContextScopes": [
                    "current_user_instruction",
                    "project_shared_context",
                ],
            }
        )

        plan = ContextAssemblyPlanner().plan(
            profile=profile,
            request=_assembly_request("Request shared context by ref only."),
        )
        metadata = plan.to_metadata()

        self.assertIn(
            "project_shared_context",
            metadata["authorized_context_scopes"],
        )
        self.assertEqual(
            metadata["selected_source_refs"],
            [
                {
                    "scope": "current_user_instruction",
                    "ref_type": "context_update",
                    "ref_id": "update-1",
                }
            ],
        )
        self.assertEqual(
            metadata["omitted_source_refs"],
            [
                {
                    "source_ref": {
                        "scope": "project_shared_context",
                        "ref_type": "project_shared_context",
                        "ref_id": "context-1",
                    },
                    "reason": "not_selected_by_policy",
                }
            ],
        )
        self.assertEqual(
            [item["source_ref"]["scope"] for item in metadata["content_packet_items"]],
            ["current_user_instruction"],
        )
        self.assertEqual(
            metadata["excluded_content_refs"],
            [
                {
                    "reason": "not_selected_by_policy",
                    "content_state": "omitted_by_window_selection",
                    "source_ref": {
                        "scope": "project_shared_context",
                        "ref_type": "project_shared_context",
                        "ref_id": "context-1",
                    },
                    "metadata": {
                        "excluded_by": "window_selection",
                        "content_item_created": False,
                    },
                }
            ],
        )
        self.assertEqual(
            [segment["source_ref"]["scope"] for segment in metadata["materialized_segments"]],
            ["current_user_instruction"],
        )

    def test_window_selection_deduplicates_authorized_source_refs(self) -> None:
        profile = ContextManagementProfile.from_mapping(
            {
                "strategy": "recent-window",
                "includeFileReferences": True,
                "allowedContextScopes": [
                    "current_user_instruction",
                    "referenced_files",
                ],
            }
        )

        plan = ContextAssemblyPlanner().plan(
            profile=profile,
            request=_assembly_request(
                "Use duplicate file references by audit ref.",
                file_references=("file-ref-1", "file-ref-1"),
            ),
        )
        metadata = plan.to_metadata()

        selected_file_refs = [
            source_ref
            for source_ref in metadata["selected_source_refs"]
            if source_ref["scope"] == "referenced_files"
        ]
        self.assertEqual(len(selected_file_refs), 1)
        self.assertIn(
            {
                "source_ref": {
                    "scope": "referenced_files",
                    "ref_type": "file_reference",
                    "ref_id": "file-ref-1",
                    "metadata": {"content_loaded": False},
                },
                "reason": "duplicate_source_ref",
            },
            metadata["omitted_source_refs"],
        )
        packet_file_items = [
            item
            for item in metadata["content_packet_items"]
            if item["source_ref"]["scope"] == "referenced_files"
        ]
        self.assertEqual(len(packet_file_items), 1)
        self.assertIn(
            {
                "reason": "duplicate_source_ref",
                "content_state": "omitted_by_window_selection",
                "source_ref": {
                    "scope": "referenced_files",
                    "ref_type": "file_reference",
                    "ref_id": "file-ref-1",
                    "metadata": {"content_loaded": False},
                },
                "metadata": {
                    "excluded_by": "window_selection",
                    "content_item_created": False,
                },
            },
            metadata["excluded_content_refs"],
        )
        materialized_file_segments = [
            segment
            for segment in metadata["materialized_segments"]
            if segment["source_ref"]["scope"] == "referenced_files"
        ]
        self.assertEqual(len(materialized_file_segments), 1)

    def test_reserved_context_scopes_remain_unconnected(self) -> None:
        profile = ContextManagementProfile.from_mapping(
            {
                "allowedContextScopes": [
                    "current_user_instruction",
                    "agent_private_memory",
                    "provider_native_session_ref",
                    "external_context_engine",
                ],
                "agentPrivateMemory": {"enabled": True},
            }
        )

        plan = ContextAssemblyPlanner().plan(
            profile=profile,
            request=_assembly_request(
                "Request reserved contexts.",
                requested_context_scopes=(
                    "agent_private_memory",
                    "provider_native_session_ref",
                    "external_context_engine",
                ),
            ),
        )

        self.assertEqual(
            plan.to_metadata()["denied_context_scopes"],
            [
                {
                    "scope": "agent_private_memory",
                    "reason": "reserved_scope_not_connected",
                },
                {
                    "scope": "provider_native_session_ref",
                    "reason": "reserved_scope_not_connected",
                },
                {
                    "scope": "external_context_engine",
                    "reason": "reserved_scope_not_connected",
                },
            ],
        )
        self.assertEqual(
            plan.to_metadata()["selected_source_refs"],
            [
                {
                    "scope": "current_user_instruction",
                    "ref_type": "context_update",
                    "ref_id": "update-1",
                }
            ],
        )
        self.assertEqual(
            plan.to_metadata()["window_selection"]["denied_scopes_excluded"],
            plan.to_metadata()["denied_context_scopes"],
        )
        self.assertEqual(
            [item["source_ref"]["scope"] for item in plan.to_metadata()["content_packet_items"]],
            ["current_user_instruction"],
        )
        self.assertEqual(
            plan.to_metadata()["content_packet"]["excluded_refs"],
            [
                {
                    "reason": "reserved_scope_not_connected",
                    "content_state": "denied_by_authorization",
                    "scope": "agent_private_memory",
                    "metadata": {
                        "excluded_by": "authorization",
                        "content_item_created": False,
                    },
                },
                {
                    "reason": "reserved_scope_not_connected",
                    "content_state": "denied_by_authorization",
                    "scope": "provider_native_session_ref",
                    "metadata": {
                        "excluded_by": "authorization",
                        "content_item_created": False,
                    },
                },
                {
                    "reason": "reserved_scope_not_connected",
                    "content_state": "denied_by_authorization",
                    "scope": "external_context_engine",
                    "metadata": {
                        "excluded_by": "authorization",
                        "content_item_created": False,
                    },
                },
            ],
        )
        self.assertEqual(
            [segment["source_ref"]["scope"] for segment in plan.to_metadata()["materialized_segments"]],
            ["current_user_instruction"],
        )

    def test_delegated_delivery_mode_is_reserved_metadata_only(self) -> None:
        profile = ContextManagementProfile.from_mapping(
            {
                "contentPacketDeliveryMode": "agent_native_delegated_context",
            }
        )

        plan = ContextAssemblyPlanner().plan(
            profile=profile,
            request=_assembly_request("Delegate context only by metadata."),
        )
        content_packet = plan.to_metadata()["content_packet"]

        self.assertEqual(
            content_packet["delivery_mode"],
            "agent_native_delegated_context",
        )
        self.assertFalse(content_packet["provider_payload_required"])
        self.assertFalse(content_packet["content_loaded"])
        self.assertTrue(content_packet["metadata"]["delivery_mode_reserved"])
        self.assertTrue(content_packet["metadata"]["agent_native_context_delegated"])
        self.assertFalse(
            content_packet["redaction_metadata"]["agent_native_runtime_connected"]
        )
        self.assertEqual(
            [item["content_state"] for item in content_packet["packet_items"]],
            ["already_in_user_message"],
        )

    def test_shared_context_materialization_uses_update_summaries_only(self) -> None:
        profile = ContextManagementProfile.from_mapping(
            {
                "strategy": "recent-window",
                "includeSharedContext": True,
                "allowedContextScopes": [
                    "current_user_instruction",
                    "project_shared_context",
                ],
            }
        )

        plan = ContextAssemblyPlanner().plan(
            profile=profile,
            request=_assembly_request(
                "Use shared summaries.",
                shared_context_updates=(
                    ContextSharedContextUpdateSnapshot(
                        update_id="update-shared-1",
                        update_kind="decision",
                        summary="Use the local context boundary.",
                    ),
                ),
            ),
        )
        shared_segments = [
            segment
            for segment in plan.to_metadata()["materialized_segments"]
            if segment["segment_kind"] == "shared_context_update_summary"
        ]

        self.assertEqual(len(shared_segments), 1)
        self.assertEqual(shared_segments[0]["load_state"], "loaded")
        self.assertEqual(
            shared_segments[0]["text"],
            "decision update-shared-1: Use the local context boundary.",
        )
        self.assertFalse(
            plan.to_metadata()["materialization"]["redaction_metadata"][
                "shared_context_payload_loaded"
            ]
        )
        self.assertFalse(
            plan.to_metadata()["materialization"]["redaction_metadata"][
                "materialized_state_loaded"
            ]
        )

    def test_task_context_materialization_is_snapshot_bounded(self) -> None:
        profile = ContextManagementProfile.from_mapping(
            {
                "strategy": "recent-window",
                "includeTaskContext": True,
                "allowedContextScopes": [
                    "current_user_instruction",
                    "current_task",
                ],
            }
        )

        disconnected_plan = ContextAssemblyPlanner().plan(
            profile=profile,
            request=_assembly_request(
                "Use task without a reader.",
                task_id="task-1",
            ),
        )
        disconnected_segments = [
            segment
            for segment in disconnected_plan.to_metadata()["materialized_segments"]
            if segment["segment_kind"] == "task_context_summary"
        ]
        self.assertEqual(disconnected_segments[0]["load_state"], "loader_not_connected")

        loaded_plan = ContextAssemblyPlanner().plan(
            profile=profile,
            request=_assembly_request(
                "Use task with a snapshot.",
                task_id="task-1",
                task_snapshot=ContextTaskContextSnapshot(
                    task_id="task-1",
                    title="Close local context loop",
                    status="in_progress",
                    description="Keep prompt assembly deferred.",
                ),
            ),
        )
        task_segments = [
            segment
            for segment in loaded_plan.to_metadata()["materialized_segments"]
            if segment["segment_kind"] == "task_context_summary"
        ]

        self.assertEqual(task_segments[0]["load_state"], "loaded")
        self.assertIn("Close local context loop", task_segments[0]["text"])
        self.assertTrue(
            loaded_plan.to_metadata()["materialization"]["redaction_metadata"][
                "task_summary_loaded"
            ]
        )

    def test_context_materialization_rejects_credential_like_snapshots(self) -> None:
        with self.assertRaisesRegex(ValueError, "credential values"):
            ContextConversationMessageSnapshot(
                message_id="message-1",
                role="user",
                content=(
                    "Authorization:"
                    + " Bearer "
                    + "sk-"
                    + "12345678901234567890"
                ),
            )

        with self.assertRaisesRegex(ValueError, "credential values"):
            ContextSharedContextUpdateSnapshot(
                update_id="update-1",
                update_kind="note",
                summary="safe",
                metadata={"authorization": "Bearer x"},
            )

    def test_context_scope_aliases_and_duplicates_are_stable(self) -> None:
        profile = ContextManagementProfile.from_mapping(
            {"allowedContextScopes": ["project_summary"]}
        )

        self.assertEqual(
            profile.allowed_context_scopes,
            (ContextAccessScope.PROJECT_SHARED_CONTEXT.value,),
        )

        with self.assertRaisesRegex(ValueError, "duplicate"):
            ContextManagementProfile.from_mapping(
                {
                    "allowedContextScopes": [
                        "project_summary",
                        "project_shared_context",
                    ]
                }
            )

        with self.assertRaisesRegex(ContextAssemblyError, "duplicate"):
            ContextAssemblyPlanner().plan(
                profile=ContextManagementProfile.default(),
                request=_assembly_request(
                    "Duplicate scope.",
                    requested_context_scopes=(
                        "current_user_instruction",
                        "user_instruction",
                    ),
                ),
            )


class ContextManagementAgentIntegrationTests(unittest.TestCase):
    def test_agent_runtime_profile_carries_context_management_config(self) -> None:
        registration = _registration(
            runtime_config={
                "profile": {
                    "profileName": "review-profile",
                    "providerName": "deterministic",
                    "modelName": "deterministic-text",
                    "contextManagement": {
                        "strategy": "recent-window",
                        "maxInputTokens": 2048,
                        "recentMessageLimit": 6,
                        "includeConversationHistory": True,
                        "allowedContextScopes": [
                            "current_user_instruction",
                            "recent_messages",
                        ],
                    },
                },
            },
        )

        profile = AgentRuntimeProfile.from_registration(registration)
        selection = profile.provider_selection(
            ModelProviderSelection(
                provider_name="deterministic",
                model_name="deterministic-text",
            )
        )

        self.assertEqual(
            profile.context_management_profile.strategy,
            ContextManagementStrategy.RECENT_WINDOW,
        )
        self.assertEqual(selection.context_management_profile.max_input_tokens, 2048)
        self.assertEqual(
            selection.runtime_metadata["context_management_strategy"],
            "recent-window",
        )
        self.assertEqual(
            selection.runtime_metadata["context_management_profile_reserved"],
            "true",
        )

    def test_provider_backed_adapter_adds_context_plan_to_local_invocation(self) -> None:
        provider = RecordingModelProvider()
        selection = ModelProviderSelection(
            provider_name="recording",
            model_name="recording-text",
            context_management_profile=ContextManagementProfile.from_mapping(
                {
                    "strategy": "recent-window",
                    "includeConversationHistory": True,
                    "allowedContextScopes": [
                        "current_user_instruction",
                        "recent_messages",
                    ],
                }
            ),
        )
        adapter = build_provider_backed_agent_invocation_adapter(
            model_provider=provider,
            selection=selection,
        )

        model_invocation = adapter.build_model_invocation(
            request=_invocation_request(),
            context=_context_from_seed(),
            user_context_update=_context_update(),
        )

        context_management = model_invocation.parameters["context_management"]
        self.assertEqual(context_management["strategy"], "recent-window")
        self.assertEqual(
            context_management["authorized_context_scopes"],
            ["current_user_instruction"],
        )
        self.assertEqual(
            context_management["denied_context_scopes"],
            [
                {
                    "scope": "recent_messages",
                    "reason": "conversation_id_required",
                }
            ],
        )
        self.assertEqual(
            context_management["selected_source_refs"],
            [
                {
                    "scope": "current_user_instruction",
                    "ref_type": "context_update",
                    "ref_id": "update-1",
                }
            ],
        )
        self.assertEqual(
            context_management["window_selection"]["denied_scopes_excluded"],
            context_management["denied_context_scopes"],
        )
        self.assertFalse(context_management["content_loaded"])
        self.assertEqual(
            context_management["content_packet"]["delivery_mode"],
            "audit_only",
        )
        self.assertFalse(
            context_management["content_packet"]["provider_payload_required"]
        )
        self.assertEqual(
            [item["source_ref"]["scope"] for item in context_management["content_packet_items"]],
            ["current_user_instruction"],
        )
        self.assertEqual(
            context_management["content_packet"]["excluded_refs"],
            [
                {
                    "reason": "conversation_id_required",
                    "content_state": "denied_by_authorization",
                    "scope": "recent_messages",
                    "metadata": {
                        "excluded_by": "authorization",
                        "content_item_created": False,
                    },
                }
            ],
        )
        self.assertFalse(context_management["materialization_content_loaded"])
        self.assertFalse(context_management["provider_prompt_injected"])
        self.assertEqual(
            [segment["segment_kind"] for segment in context_management["materialized_segments"]],
            ["current_user_message_marker"],
        )
        self.assertEqual(len(model_invocation.messages), 1)
        self.assertNotIn("provider_user_agent", context_management)
        runtime_access = model_invocation.parameters["runtime_access"]
        self.assertEqual(runtime_access["runtime_kind"], "provider_backed_model")
        self.assertEqual(
            runtime_access["delivery_plan"]["delegated_context_delivery"],
            "none",
        )
        self.assertFalse(runtime_access["delivery_plan"]["delegated_context_delivered"])
        self.assertFalse(runtime_access["delivery_plan"]["real_runtime_connected"])
        self.assertFalse(runtime_access["delivery_plan"]["provider_prompt_injected"])
        self.assertEqual(
            runtime_access["delivery_plan"]["denied_segments"][0]["reason"],
            "delegated_context_delivery_disabled",
        )

    def test_provider_backed_adapter_records_materialization_without_prompt_change(self) -> None:
        provider = RecordingModelProvider()
        selection = ModelProviderSelection(
            provider_name="recording",
            model_name="recording-text",
            context_management_profile=ContextManagementProfile.from_mapping(
                {
                    "strategy": "recent-window",
                    "includeConversationHistory": True,
                    "includeSharedContext": True,
                    "allowedContextScopes": [
                        "current_user_instruction",
                        "recent_messages",
                        "project_shared_context",
                    ],
                }
            ),
        )
        adapter = build_provider_backed_agent_invocation_adapter(
            model_provider=provider,
            selection=selection,
        )

        model_invocation = adapter.build_model_invocation(
            request=_invocation_request(metadata={"conversation_id": "conversation-1"}),
            context=_context_with_update(),
            user_context_update=_context_update(),
        )

        context_management = model_invocation.parameters["context_management"]
        self.assertIn(
            "recent_messages",
            context_management["authorized_context_scopes"],
        )
        recent_segments = [
            segment
            for segment in context_management["materialized_segments"]
            if segment["segment_kind"] == "conversation_message_window"
        ]
        self.assertEqual(recent_segments[0]["load_state"], "loader_not_connected")
        shared_segments = [
            segment
            for segment in context_management["materialized_segments"]
            if segment["segment_kind"] == "shared_context_update_summary"
        ]
        self.assertEqual(shared_segments[0]["load_state"], "loaded")
        self.assertIn("Seed shared context summary.", shared_segments[0]["text"])
        self.assertFalse(context_management["provider_prompt_injected"])
        self.assertFalse(context_management["provider_payload_required"])
        self.assertEqual(len(model_invocation.messages), 1)

    def test_runtime_access_delivery_plan_is_metadata_only_for_explicit_agent_runtime(self) -> None:
        provider = RecordingModelProvider()
        selection = ModelProviderSelection(
            provider_name="recording",
            model_name="recording-text",
            context_management_profile=ContextManagementProfile.from_mapping(
                {
                    "strategy": "recent-window",
                    "includeSharedContext": True,
                    "allowedContextScopes": [
                        "current_user_instruction",
                        "project_shared_context",
                    ],
                }
            ),
            runtime_access_profile=AgentRuntimeAccessProfile.from_mapping(
                {
                    "runtimeKind": "agent-native-runtime",
                    "delegatedContextDelivery": "bounded_materialized_segments",
                    "filePermission": "file_ref_metadata_only",
                    "networkPolicy": "disabled",
                }
            ),
        )
        adapter = build_provider_backed_agent_invocation_adapter(
            model_provider=provider,
            selection=selection,
        )

        model_invocation = adapter.build_model_invocation(
            request=_invocation_request(),
            context=_context_with_update(),
            user_context_update=_context_update(),
        )

        runtime_access = model_invocation.parameters["runtime_access"]
        context_management = model_invocation.parameters["context_management"]
        delivery_plan = runtime_access["delivery_plan"]
        self.assertEqual(runtime_access["runtime_kind"], "agent_native_runtime")
        self.assertEqual(
            delivery_plan["delegated_context_delivery"],
            "bounded_materialized_segments",
        )
        self.assertFalse(delivery_plan["delegated_context_delivered"])
        self.assertFalse(delivery_plan["real_runtime_connected"])
        self.assertFalse(delivery_plan["provider_prompt_injected"])
        self.assertFalse(delivery_plan["materialized_text_included"])
        self.assertEqual(delivery_plan["denied_segments"], [])
        self.assertEqual(
            [
                segment["source_packet_item_id"]
                for segment in delivery_plan["deliverable_segments"]
            ],
            context_management["materialization"]["source_packet_item_ids"],
        )
        for segment in delivery_plan["deliverable_segments"]:
            self.assertFalse(segment["text_included"])
            self.assertNotIn("text", segment)
        self.assertEqual(len(model_invocation.messages), 1)


def _assembly_request(
    instruction: str,
    *,
    conversation_id: str | None = None,
    task_id: str | None = None,
    file_references: tuple[str, ...] = (),
    requested_context_scopes: tuple[str, ...] = (),
    conversation_messages: tuple[ContextConversationMessageSnapshot, ...] = (),
    shared_context_updates: tuple[ContextSharedContextUpdateSnapshot, ...] = (),
    task_snapshot: ContextTaskContextSnapshot | None = None,
) -> ContextAssemblyRequest:
    return ContextAssemblyRequest(
        workspace_id="workspace-1",
        agent_id="agent-1",
        invocation_id="invoke-1",
        context_id="context-1",
        user_instruction=instruction,
        current_context_update_id="update-1",
        task_id=task_id,
        conversation_id=conversation_id,
        file_references=file_references,
        requested_context_scopes=requested_context_scopes,
        conversation_messages=conversation_messages,
        shared_context_updates=shared_context_updates,
        task_snapshot=task_snapshot,
    )


def _registration(
    *,
    runtime_config: dict[str, object],
) -> AgentRegistration:
    return AgentRegistration.register(
        agent_id=AgentId("agent-reviewer"),
        workspace_id=WorkspaceId("workspace-1"),
        name="Reviewer",
        description="Reviews current work.",
        capabilities=(
            AgentCapability(
                name="single-turn-status",
                description="Captures single-turn requests.",
            ),
        ),
        created_at=datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc),
        default_model="deterministic-text",
        runtime_config=runtime_config,
    )


def _invocation_request(
    *,
    metadata: dict[str, object] | None = None,
) -> AgentInvocationRequest:
    return AgentInvocationRequest.create(
        invocation_id=AgentInvocationId("invoke-1"),
        workspace_id=WorkspaceId("workspace-1"),
        agent_id=AgentId("agent-1"),
        instruction="Use the context profile plan.",
        requested_at=datetime(2026, 6, 14, 10, 0, tzinfo=timezone.utc),
        metadata=metadata,
    )


def _context_update() -> ContextUpdateInfo:
    return ContextUpdateInfo.create(
        update_id=ContextUpdateId("update-1"),
        workspace_id=WorkspaceId("workspace-1"),
        update_kind=ContextUpdateKind.USER_MESSAGE,
        summary="Captured user request.",
        created_at=datetime(2026, 6, 14, 10, 0, tzinfo=timezone.utc),
    )


def _context_from_seed():
    connection = connect_in_memory_platform()
    seed_minimal_invocation_platform_state(connection)
    context_record = SqliteContextStateStore(connection).get_context_state(
        WorkspaceId("workspace-1")
    )
    assert context_record is not None
    return context_record.context


def _context_with_update():
    return _context_from_seed().append_update(
        ContextUpdateInfo.create(
            update_id=ContextUpdateId("update-shared-1"),
            workspace_id=WorkspaceId("workspace-1"),
            update_kind=ContextUpdateKind.NOTE,
            summary="Seed shared context summary.",
            created_at=datetime(2026, 6, 14, 9, 30, tzinfo=timezone.utc),
        )
    )


class RecordingModelProvider:
    async def generate(self, request: ModelInvocation) -> ModelOutput:
        return ModelOutput(
            model_name=request.model_name,
            content="Recorded provider output.",
            metadata={},
        )

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        return EmbeddingResult(
            model_name=request.model_name,
            vectors=tuple((0.0,) for _ in request.inputs),
        )

    async def list_models(self) -> tuple[str, ...]:
        return ("recording-text",)


if __name__ == "__main__":
    unittest.main()
