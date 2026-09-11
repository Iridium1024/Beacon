from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping as MappingABC
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Mapping, Sequence
from uuid import uuid4

from agent_os.application.services.agent_endpoint import (
    normalize_agent_endpoint_alias,
    normalize_agent_endpoint_provider,
)
from agent_os.application.services.agent_communication_context import (
    build_beacon_cli_invocation,
    cli_shell_examples,
)
from agent_os.application.services.agent_dispatch_control import (
    effective_agent_dispatch_semantic_mapping,
)
from agent_os.application.services.agent_provider_runtime_status import (
    normalize_provider_runtime_status_read_policy,
)
from agent_os.application.services.agent_runtime_preflight import (
    build_agent_runtime_preflight_report,
)
from agent_os.application.services.agent_session_discovery import (
    discovery_registration_metadata,
    discover_agent_sessions,
    find_discovered_agent_session,
)
from agent_os.application.services.provider_session_profile import (
    MANUAL_ONLY_ACTIVATION_POLICY,
    ProviderSessionRegistry,
    ProviderSessionRegistryPathResolution,
    provider_session_registry_path_resolution,
    provider_session_profile_ref,
    resolve_provider_session_registry_path,
    synthetic_discovered_session_from_profile,
)
from agent_os.application.services.provider_backend_control import (
    resolve_provider_backend,
)
from agent_os.application.services.deepseek_harness_managed_runtime import (
    DeepSeekHarnessRuntimeError,
    DeepSeekHarnessRuntimeSpec,
    build_deepseek_harness_runtime_spec,
    preflight_deepseek_harness_runtime,
    launch_deepseek_harness_supervisor,
    read_runtime_state,
    request_deepseek_harness_supervisor,
    runtime_handle_metadata,
)
from agent_os.application.services.deepseek_harness_registered_session import (
    DeepSeekHarnessRegisteredSessionHandleState,
)
from agent_os.application.services.console_projection import (
    ConsoleProjectionService,
    DEFAULT_TIMELINE_LIMIT,
)
from agent_os.domain.entities.context import ContextUpdateKind
from agent_os.infrastructure.composition.local_platform import (
    LocalPlatformRuntimeComponents,
    build_local_platform_runtime,
)
from agent_os.infrastructure.config import LocalPlatformSettings


@dataclass(frozen=True, slots=True)
class LocalPlatformApplication:
    """Stable local application facade for non-UI platform entrypoints."""

    settings: LocalPlatformSettings

    def initialize_database(self) -> Mapping[str, object]:
        with self._components() as components:
            return {
                "initialized": True,
                "database": components.settings.database,
                "schemaInitialized": components.settings.initialize_schema,
            }

    def agent_runtime_preflight(
        self,
        *,
        tools: Sequence[str] | None = None,
        timeout_seconds: float = 8.0,
        ticket_path: str | None = None,
        response_path: str | None = None,
    ) -> Mapping[str, object]:
        return build_agent_runtime_preflight_report(
            tools=tools,
            timeout_seconds=timeout_seconds,
            ticket_path=ticket_path,
            response_path=response_path,
        )

    def create_workspace(
        self,
        *,
        display_name: str,
        root_path: str | None = None,
        workspace_id: str | None = None,
        context_id: str | None = None,
        agent_id: str | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().create_workspace(
                workspace_id=workspace_id,
                context_id=context_id,
                agent_id=agent_id,
                display_name=display_name,
                root_path=root_path or self.settings.workspace_root,
            )

    def list_workspaces(self) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().list_workspaces()

    def list_console_workspaces(self) -> Mapping[str, object]:
        """Return the redacted read-only workspace roster for the local console."""

        with self._components() as components:
            operations = components.operations()
            return ConsoleProjectionService(
                operations=operations,
                event_log=operations.event_log_reader,
            ).list_workspaces()

    def get_console_provider_backends(self) -> Mapping[str, object]:
        """Return current Beacon backend capabilities without probing providers."""

        with self._components() as components:
            operations = components.operations()
            return ConsoleProjectionService(
                operations=operations,
                event_log=operations.event_log_reader,
            ).provider_backends()

    def get_console_workspace_view(
        self,
        *,
        workspace_id: str,
        cursor: str | None = None,
        limit: int = DEFAULT_TIMELINE_LIMIT,
    ) -> Mapping[str, object]:
        """Return a bounded heterogeneous-session view with no mutation surface."""

        with self._components() as components:
            operations = components.operations()
            return ConsoleProjectionService(
                operations=operations,
                event_log=operations.event_log_reader,
            ).workspace_view(
                workspace_id,
                cursor=cursor,
                limit=limit,
            )

    def open_workspace(self, workspace_id: str) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().open_workspace(workspace_id)

    def archive_workspace(self, workspace_id: str) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().archive_workspace(workspace_id)

    def create_agent(
        self,
        *,
        workspace_id: str,
        name: str,
        description: str,
        agent_id: str | None = None,
        default_model: str | None = None,
        capabilities: tuple[Mapping[str, object], ...] = (),
        tool_permissions: tuple[str, ...] = ("workspace.read",),
        runtime_config: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().create_agent_registration(
                workspace_id,
                agent_id=agent_id,
                name=name,
                description=description,
                capabilities=tuple(capabilities),
                default_model=default_model,
                tool_permissions=tuple(tool_permissions),
                runtime_config=runtime_config,
                metadata=metadata,
            )

    def list_agent_runtime_permissions(
        self,
        workspace_id: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().list_agent_runtime_permissions(
                workspace_id
            )

    def get_agent_runtime_permissions(
        self,
        *,
        workspace_id: str,
        agent_id: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_agent_runtime_permissions(
                workspace_id,
                agent_id,
            )

    def create_conversation(
        self,
        *,
        workspace_id: str,
        title: str,
        conversation_id: str | None = None,
        agent_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().create_conversation(
                workspace_id,
                conversation_id=conversation_id,
                agent_id=agent_id,
                title=title,
                metadata=metadata,
            )

    def list_conversations(self, workspace_id: str) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().list_conversations(workspace_id)

    def get_conversation(
        self,
        *,
        workspace_id: str,
        conversation_id: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_conversation(
                workspace_id,
                conversation_id,
            )

    def archive_conversation(
        self,
        *,
        workspace_id: str,
        conversation_id: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().archive_conversation(
                workspace_id,
                conversation_id,
            )

    def append_conversation_message(
        self,
        *,
        workspace_id: str,
        conversation_id: str,
        role: str,
        content: str,
        message_id: str | None = None,
        agent_id: str | None = None,
        invocation_id: str | None = None,
        context_update_id: str | None = None,
        run_session_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
        exchange_attribution: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().append_conversation_message(
                workspace_id,
                conversation_id,
                role=role,
                content=content,
                message_id=message_id,
                agent_id=agent_id,
                invocation_id=invocation_id,
                context_update_id=context_update_id,
                run_session_id=run_session_id,
                metadata=metadata,
                exchange_attribution=exchange_attribution,
            )

    def list_conversation_messages(
        self,
        *,
        workspace_id: str,
        conversation_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().list_conversation_messages(
                workspace_id,
                conversation_id,
                limit=limit,
                offset=offset,
            )

    def invoke_deterministic(
        self,
        *,
        workspace_id: str,
        instruction: str,
        agent_id: str | None = None,
        invocation_id: str | None = None,
        requested_at: str | None = None,
        session_id: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        conversation_id: str | None = None,
    ) -> Mapping[str, object]:
        payload: dict[str, object] = {
            "workspaceId": workspace_id,
            "agentId": agent_id or _default_agent_id(workspace_id),
            "instruction": instruction,
            "requestedAt": requested_at or _utc_now_text(),
        }
        if invocation_id is not None:
            payload["invocationId"] = invocation_id
        if session_id is not None:
            payload["sessionId"] = session_id
        if idempotency_key is not None:
            payload["idempotencyKey"] = idempotency_key
        if correlation_id is not None:
            payload["correlationId"] = correlation_id
        if conversation_id is not None:
            payload["conversationId"] = conversation_id

        return self.invoke_payload(payload)

    def invoke_payload(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        with self._components() as components:
            return components.handle_payload(payload)

    def get_context(self, workspace_id: str) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_context(workspace_id)

    def list_context_updates(
        self,
        *,
        workspace_id: str,
        limit: int = 20,
        offset: int = 0,
        update_kind: str | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().list_context_updates(
                workspace_id,
                limit=limit,
                offset=offset,
                update_kind=update_kind,
            )

    def get_context_update(
        self,
        *,
        workspace_id: str,
        update_id: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_context_update(
                workspace_id,
                update_id=update_id,
            )

    def append_context_update(
        self,
        *,
        workspace_id: str,
        summary: str,
        update_kind: str = ContextUpdateKind.NOTE.value,
        update_id: str | None = None,
        materialized_state_patch: Mapping[str, object] | None = None,
        payload: Mapping[str, object] | None = None,
        session_id: str | None = None,
        exchange_attribution: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().append_context_update(
                workspace_id,
                update_kind=update_kind,
                summary=summary,
                update_id=update_id,
                materialized_state_patch=materialized_state_patch,
                payload=payload,
                session_id=session_id,
                exchange_attribution=exchange_attribution,
            )

    def agent_exchange_instructions(
        self,
        workspace_id: str | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().agent_exchange_instructions(workspace_id)

    def agent_exchange_request_instructions(
        self,
        workspace_id: str | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().agent_exchange_request_instructions(
                workspace_id
            )

    def get_agent_exchange_request_policy(
        self,
        workspace_id: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_agent_exchange_request_policy(
                workspace_id
            )

    def update_agent_exchange_request_policy(
        self,
        *,
        workspace_id: str,
        authorization_mode: str | None = None,
        sub_request_policy: str | None = None,
        thread_workspace_visible: bool | None = None,
        follow_up_policy: str | None = None,
        allowed_sub_request_agent_ids: tuple[str, ...] | None = None,
        max_request_length: int | None = None,
        max_response_length: int | None = None,
        max_response_tokens: int | None = None,
        max_turns: int | None = None,
        max_sub_request_depth: int | None = None,
        max_child_requests: int | None = None,
        auto_append_exchange_result_to_shared_context: bool | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().update_agent_exchange_request_policy(
                workspace_id,
                authorization_mode=authorization_mode,
                sub_request_policy=sub_request_policy,
                thread_workspace_visible=thread_workspace_visible,
                follow_up_policy=follow_up_policy,
                allowed_sub_request_agent_ids=allowed_sub_request_agent_ids,
                max_request_length=max_request_length,
                max_response_length=max_response_length,
                max_response_tokens=max_response_tokens,
                max_turns=max_turns,
                max_sub_request_depth=max_sub_request_depth,
                max_child_requests=max_child_requests,
                auto_append_exchange_result_to_shared_context=(
                    auto_append_exchange_result_to_shared_context
                ),
                metadata=metadata,
            )

    def create_agent_exchange_request(
        self,
        *,
        workspace_id: str,
        source_agent_id: str,
        target_agent_id: str,
        request_kind: str,
        request_summary: str,
        exchange_request_id: str | None = None,
        agent_session_id: str | None = None,
        connection_instance_id: str | None = None,
        detail_refs: tuple[str, ...] = (),
        linked_task_id: str | None = None,
        linked_conversation_id: str | None = None,
        linked_activation_id: str | None = None,
        linked_delegated_wake_grant_id: str | None = None,
        parent_request_id: str | None = None,
        root_request_id: str | None = None,
        thread_id: str | None = None,
        turn_index: int | None = None,
        expires_at: str | None = None,
        requires_user_review: bool = False,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().create_agent_exchange_request(
                workspace_id,
                source_agent_id=source_agent_id,
                target_agent_id=target_agent_id,
                request_kind=request_kind,
                request_summary=request_summary,
                exchange_request_id=exchange_request_id,
                agent_session_id=agent_session_id,
                connection_instance_id=connection_instance_id,
                detail_refs=detail_refs,
                linked_task_id=linked_task_id,
                linked_conversation_id=linked_conversation_id,
                linked_activation_id=linked_activation_id,
                linked_delegated_wake_grant_id=linked_delegated_wake_grant_id,
                parent_request_id=parent_request_id,
                root_request_id=root_request_id,
                thread_id=thread_id,
                turn_index=turn_index,
                expires_at=_optional_datetime(expires_at),
                requires_user_review=requires_user_review,
                metadata=metadata,
            )

    def list_agent_exchange_requests(
        self,
        *,
        workspace_id: str,
        source_agent_id: str | None = None,
        target_agent_id: str | None = None,
        status: str | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().list_agent_exchange_requests(
                workspace_id,
                source_agent_id=source_agent_id,
                target_agent_id=target_agent_id,
                status=status,
            )

    def get_agent_exchange_request_status(
        self,
        *,
        workspace_id: str,
        exchange_request_id: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_agent_exchange_request_status(
                workspace_id,
                exchange_request_id=exchange_request_id,
            )

    def get_agent_exchange_status_summary(
        self,
        *,
        workspace_id: str,
        exchange_request_id: str | None = None,
        dispatch_id: str | None = None,
        thread_id: str | None = None,
        read_live_runtime_status: bool | str = "auto",
        waiting_response_stale_threshold_seconds: int = 600,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_agent_exchange_status_summary(
                workspace_id,
                exchange_request_id=exchange_request_id,
                dispatch_id=dispatch_id,
                thread_id=thread_id,
                read_live_runtime_status=read_live_runtime_status,
                waiting_response_stale_threshold_seconds=(
                    waiting_response_stale_threshold_seconds
                ),
            )

    def respond_agent_exchange_request(
        self,
        *,
        workspace_id: str,
        exchange_request_id: str,
        responding_agent_id: str,
        response_summary: str,
        requires_user_review: bool | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().respond_agent_exchange_request(
                workspace_id,
                exchange_request_id=exchange_request_id,
                responding_agent_id=responding_agent_id,
                response_summary=response_summary,
                requires_user_review=requires_user_review,
                metadata=metadata,
            )

    def close_agent_exchange_request(
        self,
        *,
        workspace_id: str,
        exchange_request_id: str,
        terminal_reason: str = "closed",
        requires_user_review: bool | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().close_agent_exchange_request(
                workspace_id,
                exchange_request_id=exchange_request_id,
                terminal_reason=terminal_reason,
                requires_user_review=requires_user_review,
                metadata=metadata,
            )

    def create_agent_dispatch(
        self,
        *,
        workspace_id: str,
        source_agent_id: str,
        target_agent_id: str,
        request_kind: str,
        request_summary: str,
        dispatch_id: str | None = None,
        exchange_request_id: str | None = None,
        source_handle_id: str | None = None,
        target_handle_id: str | None = None,
        target_provider: str | None = None,
        reply_policy: str = "source_handle_optional",
        detail_refs: tuple[str, ...] = (),
        linked_task_id: str | None = None,
        linked_conversation_id: str | None = None,
        linked_activation_id: str | None = None,
        linked_delegated_wake_grant_id: str | None = None,
        parent_request_id: str | None = None,
        root_request_id: str | None = None,
        thread_id: str | None = None,
        turn_index: int | None = None,
        expires_at: datetime | None = None,
        requires_user_review: bool = False,
        metadata: Mapping[str, object] | None = None,
        dry_run: bool = False,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().create_agent_dispatch(
                workspace_id,
                source_agent_id=source_agent_id,
                target_agent_id=target_agent_id,
                request_kind=request_kind,
                request_summary=request_summary,
                dispatch_id=dispatch_id,
                exchange_request_id=exchange_request_id,
                source_handle_id=source_handle_id,
                target_handle_id=target_handle_id,
                target_provider=target_provider,
                reply_policy=reply_policy,
                detail_refs=detail_refs,
                linked_task_id=linked_task_id,
                linked_conversation_id=linked_conversation_id,
                linked_activation_id=linked_activation_id,
                linked_delegated_wake_grant_id=linked_delegated_wake_grant_id,
                parent_request_id=parent_request_id,
                root_request_id=root_request_id,
                thread_id=thread_id,
                turn_index=turn_index,
                expires_at=expires_at,
                requires_user_review=requires_user_review,
                metadata=metadata,
                dry_run=dry_run,
            )

    def send_agent_dispatch(
        self,
        *,
        workspace_id: str,
        source_agent_id: str | None = None,
        target_agent_id: str | None = None,
        request_kind: str | None = None,
        request_summary: str | None = None,
        message: str | None = None,
        dispatch_id: str | None = None,
        exchange_request_id: str | None = None,
        acting_endpoint_alias: str | None = None,
        from_endpoint_alias: str | None = None,
        to_endpoint_alias: str | None = None,
        source_handle_id: str | None = None,
        target_handle_id: str | None = None,
        target_provider: str | None = None,
        reply_policy: str | None = None,
        detail_refs: tuple[str, ...] = (),
        linked_task_id: str | None = None,
        linked_conversation_id: str | None = None,
        linked_activation_id: str | None = None,
        linked_delegated_wake_grant_id: str | None = None,
        parent_request_id: str | None = None,
        root_request_id: str | None = None,
        thread_id: str | None = None,
        turn_index: int | None = None,
        expires_at: datetime | None = None,
        requires_user_review: bool = False,
        metadata: Mapping[str, object] | None = None,
        delivery_mode: str = "worker_execute",
        delivery_mode_source: str = "default",
        immediate_busy_policy: str = "return_to_sender",
        immediate_busy_policy_source: str = "default",
        dispatcher_id: str = "agent-dispatch-worker",
        lease_ttl_seconds: int | None = 300,
        retry_delay_seconds: int = 300,
        handoff_directory: str | None = None,
        platform_workspace_root: str | None = None,
        config_path: str | None = None,
        claude_executable: str = "claude",
        claude_default_platform_workspace_add_dir: bool = True,
        claude_add_dirs: tuple[str, ...] = (),
        claude_allowed_tools: tuple[str, ...] = (),
        claude_permission_mode: str | None = None,
        claude_settings_path: str | None = None,
        claude_activation_backend: str = "cli",
        claude_reply_writeback_mode: str | None = None,
        codex_executable: str = "codex",
        codex_default_platform_workspace_add_dir: bool = True,
        codex_add_dirs: tuple[str, ...] = (),
        codex_sandbox_mode: str | None = None,
        codex_approval_policy: str | None = None,
        codex_git_repo_check_policy: str = "skip",
        codex_git_repo_check_policy_source: str = "default",
        codex_activation_backend: str = "exec_resume",
        codex_app_server_approval_decision: str = "decline",
        codex_busy_delivery_policy: str = "queue_next_turn",
        codex_busy_delivery_policy_explicit: bool = False,
        codex_reply_writeback_mode: str = "explicit_only",
        hermes_executable: str = "hermes",
        hermes_home: str | None = None,
        hermes_activation_backend: str = "cli",
        hermes_reply_writeback_mode: str | None = None,
        hermes_gateway_python: str | None = None,
        hermes_source_tag: str = "agent-os",
        hermes_max_turns: int | None = None,
        activation_timeout_seconds: int = 120,
        skip_busy_target: bool = True,
        read_live_runtime_status: bool | str = "auto",
        dry_run: bool = False,
    ) -> Mapping[str, object]:
        if delivery_mode not in ("queued", "worker_dry_run", "worker_execute"):
            raise ValueError(
                "deliveryMode must be one of: queued, worker_dry_run, worker_execute."
            )
        if immediate_busy_policy not in ("return_to_sender", "queue_next_turn"):
            raise ValueError(
                "immediateBusyPolicy must be one of: return_to_sender, "
                "queue_next_turn."
            )
        resolved_message = _optional_text(message)
        resolved_request_summary = _optional_text(request_summary) or resolved_message
        if resolved_request_summary is None:
            raise ValueError("message or requestSummary is required.")
        resolved_request_kind = _optional_text(request_kind) or "sync"
        resolved_source_alias, identity_input_source = (
            _resolve_dispatch_acting_endpoint_alias(
                acting_endpoint_alias=acting_endpoint_alias,
                from_endpoint_alias=from_endpoint_alias,
            )
        )
        endpoint_resolution = self._resolve_dispatch_endpoint_aliases(
            workspace_id=workspace_id,
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            from_endpoint_alias=resolved_source_alias,
            to_endpoint_alias=to_endpoint_alias,
            source_handle_id=source_handle_id,
            target_handle_id=target_handle_id,
            target_provider=target_provider,
            reply_policy=reply_policy,
        )
        acting_identity = _agent_dispatch_acting_identity(
            endpoint_resolution,
            input_source=identity_input_source,
        )
        route_summary = _agent_dispatch_route_summary(
            workspace_id=workspace_id,
            endpoint_resolution=endpoint_resolution,
            acting_identity=acting_identity,
            preview_only=dry_run,
        )

        enriched_metadata = _agent_dispatch_send_metadata(
            metadata,
            delivery_mode=delivery_mode,
            delivery_mode_source=delivery_mode_source,
            immediate_busy_policy=immediate_busy_policy,
            immediate_busy_policy_source=immediate_busy_policy_source,
            message_input_provided=resolved_message is not None,
            endpoint_alias_resolution=endpoint_resolution.to_metadata(),
        )
        created = self.create_agent_dispatch(
            workspace_id=workspace_id,
            dispatch_id=dispatch_id,
            exchange_request_id=exchange_request_id,
            source_agent_id=endpoint_resolution.source_agent_id,
            target_agent_id=endpoint_resolution.target_agent_id,
            source_handle_id=endpoint_resolution.source_handle_id,
            target_handle_id=endpoint_resolution.target_handle_id,
            target_provider=endpoint_resolution.target_provider,
            reply_policy=endpoint_resolution.reply_policy,
            request_kind=resolved_request_kind,
            request_summary=resolved_request_summary,
            detail_refs=detail_refs,
            linked_task_id=linked_task_id,
            linked_conversation_id=linked_conversation_id,
            linked_activation_id=linked_activation_id,
            linked_delegated_wake_grant_id=linked_delegated_wake_grant_id,
            parent_request_id=parent_request_id,
            root_request_id=root_request_id,
            thread_id=thread_id,
            turn_index=turn_index,
            expires_at=expires_at,
            requires_user_review=requires_user_review,
            metadata=enriched_metadata,
            dry_run=dry_run,
        )
        created_dispatch = created["agentDispatch"]
        resolved_dispatch_id = str(created_dispatch["dispatchId"])

        if dry_run:
            return {
                "schema": "agent_dispatch_send.v1",
                "apiLayer": "delivery-oriented",
                "dispatchApiLayer": _agent_dispatch_api_layer(
                    delivery_mode,
                    dry_run=True,
                ),
                "workspaceId": workspace_id,
                "deliveryMode": delivery_mode,
                "sendModeSummary": _agent_dispatch_send_mode_summary(
                    delivery_mode,
                    dry_run=True,
                ),
                "routeSummary": route_summary,
                "actingIdentity": acting_identity,
                "dryRun": True,
                "queuedDispatchCreated": False,
                "workerRunRequested": delivery_mode in (
                    "worker_dry_run",
                    "worker_execute",
                ),
                "workerExecuted": False,
                "agentDispatch": created_dispatch,
                "plannedAgentExchangeRequest": created.get(
                    "plannedAgentExchangeRequest"
                ),
                "agentExchangeRequest": None,
                "agentExchangeThread": None,
                "targetHandoff": _agent_dispatch_target_handoff(
                    database_path=self.settings.database,
                    workspace_root=self.settings.workspace_root,
                    plugins_directory=self.settings.plugins_directory,
                    profile_path=self.settings.profile_path,
                    workspace_id=workspace_id,
                    exchange_request_id=str(
                        (
                            created.get("plannedAgentExchangeRequest") or {}
                        ).get(
                            "exchangeRequestId",
                            exchange_request_id or "",
                        )
                    ),
                    target_agent_id=endpoint_resolution.target_agent_id,
                ),
                "wakeStatus": None,
                "workerRun": None,
                "statusCommand": _agent_dispatch_status_command(
                    workspace_id,
                    resolved_dispatch_id,
                    database_path=self.settings.database,
                    workspace_root=self.settings.workspace_root,
                    plugins_directory=self.settings.plugins_directory,
                    profile_path=self.settings.profile_path,
                ),
                "endpointAliasResolution": endpoint_resolution.to_metadata(),
                "deliveryDecision": _agent_dispatch_delivery_decision(
                    delivery_mode=delivery_mode,
                    delivery_mode_source=delivery_mode_source,
                    immediate_busy_policy=immediate_busy_policy,
                    immediate_busy_policy_source=immediate_busy_policy_source,
                    dry_run=True,
                    worker_run=None,
                    status=None,
                    target_provider=endpoint_resolution.target_provider,
                ),
            }

        worker_run: Mapping[str, object] | None = None
        if delivery_mode in ("worker_dry_run", "worker_execute"):
            worker_run = self.run_agent_dispatch_worker_once(
                workspace_id=workspace_id,
                dispatch_id=resolved_dispatch_id,
                dispatcher_id=dispatcher_id,
                limit=1,
                lease_ttl_seconds=lease_ttl_seconds,
                retry_delay_seconds=retry_delay_seconds,
                handoff_directory=handoff_directory,
                platform_workspace_root=platform_workspace_root,
                config_path=config_path,
                claude_executable=claude_executable,
                claude_default_platform_workspace_add_dir=(
                    claude_default_platform_workspace_add_dir
                ),
                claude_add_dirs=claude_add_dirs,
                claude_allowed_tools=claude_allowed_tools,
                claude_permission_mode=claude_permission_mode,
                claude_settings_path=claude_settings_path,
                claude_activation_backend=claude_activation_backend,
                claude_reply_writeback_mode=claude_reply_writeback_mode,
                codex_executable=codex_executable,
                codex_default_platform_workspace_add_dir=(
                    codex_default_platform_workspace_add_dir
                ),
                codex_add_dirs=codex_add_dirs,
                codex_sandbox_mode=codex_sandbox_mode,
                codex_approval_policy=codex_approval_policy,
                codex_git_repo_check_policy=codex_git_repo_check_policy,
                codex_git_repo_check_policy_source=(
                    codex_git_repo_check_policy_source
                ),
                codex_activation_backend=codex_activation_backend,
                codex_app_server_approval_decision=(
                    codex_app_server_approval_decision
                ),
                codex_busy_delivery_policy=codex_busy_delivery_policy,
                codex_busy_delivery_policy_explicit=(
                    codex_busy_delivery_policy_explicit
                ),
                codex_reply_writeback_mode=codex_reply_writeback_mode,
                immediate_busy_policy=immediate_busy_policy,
                hermes_executable=hermes_executable,
                hermes_home=hermes_home,
                hermes_activation_backend=hermes_activation_backend,
                hermes_reply_writeback_mode=hermes_reply_writeback_mode,
                hermes_gateway_python=hermes_gateway_python,
                hermes_source_tag=hermes_source_tag,
                hermes_max_turns=hermes_max_turns,
                activation_timeout_seconds=activation_timeout_seconds,
                skip_busy_target=skip_busy_target,
                read_live_runtime_status=read_live_runtime_status,
                dry_run=(delivery_mode == "worker_dry_run"),
            )

        status = self.get_agent_dispatch_status(
            workspace_id=workspace_id,
            dispatch_id=resolved_dispatch_id,
            read_live_runtime_status=(
                "disabled" if delivery_mode == "queued" else read_live_runtime_status
            ),
        )
        return {
            "schema": "agent_dispatch_send.v1",
            "apiLayer": "delivery-oriented",
            "dispatchApiLayer": _agent_dispatch_api_layer(delivery_mode),
            "workspaceId": workspace_id,
            "deliveryMode": delivery_mode,
            "deliveryType": "new_turn",
            "sendModeSummary": _agent_dispatch_send_mode_summary(delivery_mode),
            "routeSummary": route_summary,
            "actingIdentity": acting_identity,
            "dryRun": False,
            "queuedDispatchCreated": bool(created.get("queued")),
            "workerRunRequested": delivery_mode in ("worker_dry_run", "worker_execute"),
            "workerExecuted": bool(
                worker_run
                and not worker_run.get("dryRun")
                and worker_run.get("workerStarted")
            ),
            "agentDispatch": status["agentDispatch"],
            "agentExchangeRequest": status["agentExchangeRequest"],
            "agentExchangeThread": created.get("agentExchangeThread"),
            "targetHandoff": _agent_dispatch_target_handoff(
                database_path=self.settings.database,
                workspace_root=self.settings.workspace_root,
                plugins_directory=self.settings.plugins_directory,
                profile_path=self.settings.profile_path,
                workspace_id=workspace_id,
                exchange_request_id=str(
                    status["agentExchangeRequest"]["exchangeRequestId"]
                ),
                target_agent_id=endpoint_resolution.target_agent_id,
            ),
            "wakeStatus": status["wakeStatus"],
            "workerRun": worker_run,
            "statusCommand": _agent_dispatch_status_command(
                workspace_id,
                resolved_dispatch_id,
                database_path=self.settings.database,
                workspace_root=self.settings.workspace_root,
                plugins_directory=self.settings.plugins_directory,
                profile_path=self.settings.profile_path,
            ),
            "endpointAliasResolution": endpoint_resolution.to_metadata(),
            "sourceEventSequence": created.get("sourceEventSequence"),
            "requestSourceEventSequence": created.get("requestSourceEventSequence"),
            "deliveryDecision": _agent_dispatch_delivery_decision(
                delivery_mode=delivery_mode,
                delivery_mode_source=delivery_mode_source,
                immediate_busy_policy=immediate_busy_policy,
                immediate_busy_policy_source=immediate_busy_policy_source,
                dry_run=False,
                worker_run=worker_run,
                status=status,
                target_provider=endpoint_resolution.target_provider,
            ),
        }

    def _resolve_dispatch_endpoint_aliases(
        self,
        *,
        workspace_id: str,
        source_agent_id: str | None,
        target_agent_id: str | None,
        from_endpoint_alias: str | None,
        to_endpoint_alias: str | None,
        source_handle_id: str | None,
        target_handle_id: str | None,
        target_provider: str | None,
        reply_policy: str | None,
    ) -> "_DispatchEndpointAliasResolution":
        source_endpoint_result = (
            self.get_agent_endpoint(
                workspace_id=workspace_id,
                alias=from_endpoint_alias,
            )
            if from_endpoint_alias is not None
            else None
        )
        target_endpoint_result = (
            self.get_agent_endpoint(
                workspace_id=workspace_id,
                alias=to_endpoint_alias,
            )
            if to_endpoint_alias is not None
            else None
        )
        source_endpoint = (
            source_endpoint_result["agentEndpoint"]
            if source_endpoint_result is not None
            else None
        )
        target_endpoint = (
            target_endpoint_result["agentEndpoint"]
            if target_endpoint_result is not None
            else None
        )
        if source_endpoint is not None:
            _require_active_endpoint(source_endpoint, "source")
            _require_active_endpoint_provider_handle(
                source_endpoint,
                source_endpoint_result.get("providerHandle")
                if source_endpoint_result is not None
                else None,
                "source",
            )
            _require_endpoint_direction(source_endpoint, "source", allowed="send")
            source_agent_id = _resolve_endpoint_text_conflict(
                explicit=source_agent_id,
                resolved=_required_endpoint_text(source_endpoint, "agentId"),
                role="source endpoint",
                field_name="sourceAgentId",
            )
            source_handle_id = _resolve_endpoint_text_conflict(
                explicit=source_handle_id,
                resolved=_required_endpoint_text(source_endpoint, "providerHandleId"),
                role="source endpoint",
                field_name="sourceHandleId",
            )
            if reply_policy is None:
                reply_policy = str(
                    source_endpoint.get("defaultReplyPolicy")
                    or "source_handle_optional"
                )
                reply_policy_source = "source_endpoint_default"
            else:
                reply_policy_source = "explicit"
        else:
            reply_policy_source = "explicit" if reply_policy is not None else "default"
        if target_endpoint is not None:
            _require_active_endpoint(target_endpoint, "target")
            _require_active_endpoint_provider_handle(
                target_endpoint,
                target_endpoint_result.get("providerHandle")
                if target_endpoint_result is not None
                else None,
                "target",
            )
            _require_endpoint_direction(target_endpoint, "target", allowed="receive")
            target_agent_id = _resolve_endpoint_text_conflict(
                explicit=target_agent_id,
                resolved=_required_endpoint_text(target_endpoint, "agentId"),
                role="target endpoint",
                field_name="targetAgentId",
            )
            target_handle_id = _resolve_endpoint_text_conflict(
                explicit=target_handle_id,
                resolved=_required_endpoint_text(target_endpoint, "providerHandleId"),
                role="target endpoint",
                field_name="targetHandleId",
            )
            endpoint_provider = _required_endpoint_text(target_endpoint, "provider")
            if target_provider is not None:
                normalized = normalize_agent_endpoint_provider(target_provider)
                if normalized != endpoint_provider:
                    raise ValueError(
                        "target endpoint targetProvider conflicts with explicit "
                        "targetProvider."
                    )
            target_provider = endpoint_provider
        if source_agent_id is None:
            raise ValueError(
                "sourceAgentId is required unless a source endpoint alias is provided."
            )
        if target_agent_id is None:
            raise ValueError(
                "targetAgentId is required unless a target endpoint alias is provided."
            )
        resolved_reply_policy = _normalize_dispatch_reply_policy(
            reply_policy or "source_handle_optional"
        )
        contact_policy_decision = _dispatch_contact_policy_decision(
            source_endpoint=source_endpoint,
            target_endpoint=target_endpoint,
            reply_policy=resolved_reply_policy,
        )
        reply_reachability = _dispatch_reply_reachability(
            source_endpoint=source_endpoint,
            target_endpoint=target_endpoint,
            source_handle_id=source_handle_id,
            reply_policy=resolved_reply_policy,
        )
        return _DispatchEndpointAliasResolution(
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            source_handle_id=source_handle_id,
            target_handle_id=target_handle_id,
            target_provider=target_provider,
            reply_policy=resolved_reply_policy,
            source_endpoint=_endpoint_reference(source_endpoint),
            target_endpoint=_endpoint_reference(target_endpoint),
            reply_policy_source=reply_policy_source,
            reply_reachability=reply_reachability,
            contact_policy_decision=contact_policy_decision,
        )

    def list_agent_dispatches(
        self,
        *,
        workspace_id: str,
        source_agent_id: str | None = None,
        target_agent_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().list_agent_dispatches(
                workspace_id,
                source_agent_id=source_agent_id,
                target_agent_id=target_agent_id,
                status=status,
                limit=limit,
            )

    def get_agent_dispatch_status(
        self,
        *,
        workspace_id: str,
        dispatch_id: str | None = None,
        exchange_request_id: str | None = None,
        read_live_runtime_status: bool | str = "auto",
        waiting_response_stale_threshold_seconds: int = 600,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_agent_dispatch_status(
                workspace_id,
                dispatch_id=dispatch_id,
                exchange_request_id=exchange_request_id,
                read_live_runtime_status=read_live_runtime_status,
                waiting_response_stale_threshold_seconds=(
                    waiting_response_stale_threshold_seconds
                ),
            )

    def record_agent_dispatch_daemon_liveness(
        self,
        *,
        workspace_id: str,
        dispatcher_id: str = "agent-dispatch-daemon",
        state: str,
        profile_path: str | None = None,
        pid: int | None = None,
        process_hint: Mapping[str, object] | None = None,
        started_at: datetime | str | None = None,
        last_heartbeat_at: datetime | str | None = None,
        last_poll_at: datetime | str | None = None,
        last_error_at: datetime | str | None = None,
        last_exit_at: datetime | str | None = None,
        last_exit_reason: str | None = None,
        error_summary: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().record_agent_dispatch_daemon_liveness(
                workspace_id,
                dispatcher_id=dispatcher_id,
                state=state,
                profile_path=profile_path,
                pid=pid,
                process_hint=process_hint,
                started_at=started_at,
                last_heartbeat_at=last_heartbeat_at,
                last_poll_at=last_poll_at,
                last_error_at=last_error_at,
                last_exit_at=last_exit_at,
                last_exit_reason=last_exit_reason,
                error_summary=error_summary,
                metadata=metadata,
            )

    def get_agent_dispatch_daemon_status(
        self,
        *,
        workspace_id: str,
        dispatcher_id: str | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_agent_dispatch_daemon_status(
                workspace_id,
                dispatcher_id=dispatcher_id,
            )

    def acquire_agent_dispatch_lease(
        self,
        *,
        workspace_id: str,
        dispatch_id: str,
        lease_id: str | None = None,
        acquired_by: str | None = None,
        lease_ttl_seconds: int | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().acquire_agent_dispatch_lease(
                workspace_id,
                dispatch_id=dispatch_id,
                lease_id=lease_id,
                acquired_by=acquired_by,
                lease_ttl_seconds=lease_ttl_seconds,
                metadata=metadata,
            )

    def release_agent_dispatch_lease(
        self,
        *,
        workspace_id: str,
        lease_id: str,
        released_by: str | None = None,
        final_dispatch_status: str = "queued",
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().release_agent_dispatch_lease(
                workspace_id,
                lease_id=lease_id,
                released_by=released_by,
                final_dispatch_status=final_dispatch_status,
                metadata=metadata,
            )

    def reconcile_agent_dispatch_leases(
        self,
        *,
        workspace_id: str,
        dispatch_id: str | None = None,
        lease_id: str | None = None,
        recovered_by: str = "agent-dispatch-lease-reconciler",
        recovery_delay_seconds: int = 0,
        dry_run: bool = False,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().reconcile_agent_dispatch_leases(
                workspace_id,
                dispatch_id=dispatch_id,
                lease_id=lease_id,
                recovered_by=recovered_by,
                recovery_delay_seconds=recovery_delay_seconds,
                dry_run=dry_run,
            )

    def run_agent_dispatch_worker_once(
        self,
        *,
        workspace_id: str,
        dispatch_id: str | None = None,
        target_agent_id: str | None = None,
        dispatcher_id: str = "agent-dispatch-worker",
        limit: int = 1,
        lease_ttl_seconds: int | None = 300,
        retry_delay_seconds: int = 300,
        handoff_directory: str | None = None,
        platform_workspace_root: str | None = None,
        config_path: str | None = None,
        claude_executable: str = "claude",
        claude_default_platform_workspace_add_dir: bool = True,
        claude_add_dirs: tuple[str, ...] = (),
        claude_allowed_tools: tuple[str, ...] = (),
        claude_permission_mode: str | None = None,
        claude_settings_path: str | None = None,
        claude_activation_backend: str = "cli",
        claude_reply_writeback_mode: str | None = None,
        codex_executable: str = "codex",
        codex_default_platform_workspace_add_dir: bool = True,
        codex_add_dirs: tuple[str, ...] = (),
        codex_sandbox_mode: str | None = None,
        codex_approval_policy: str | None = None,
        codex_git_repo_check_policy: str = "skip",
        codex_git_repo_check_policy_source: str = "default",
        codex_activation_backend: str = "exec_resume",
        codex_app_server_approval_decision: str = "decline",
        codex_busy_delivery_policy: str = "queue_next_turn",
        codex_busy_delivery_policy_explicit: bool = False,
        codex_reply_writeback_mode: str = "explicit_only",
        immediate_busy_policy: str = "queue_next_turn",
        hermes_executable: str = "hermes",
        hermes_home: str | None = None,
        hermes_activation_backend: str = "cli",
        hermes_reply_writeback_mode: str | None = None,
        hermes_gateway_python: str | None = None,
        hermes_source_tag: str = "agent-os",
        hermes_max_turns: int | None = None,
        activation_timeout_seconds: int = 120,
        skip_busy_target: bool = True,
        read_live_runtime_status: bool | str = "auto",
        dry_run: bool = False,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().run_agent_dispatch_worker_once(
                workspace_id,
                database_path=self.settings.database,
                workspace_root=self.settings.workspace_root,
                plugins_directory=self.settings.plugins_directory,
                config_path=config_path,
                dispatch_id=dispatch_id,
                target_agent_id=target_agent_id,
                dispatcher_id=dispatcher_id,
                limit=limit,
                lease_ttl_seconds=lease_ttl_seconds,
                retry_delay_seconds=retry_delay_seconds,
                handoff_directory=handoff_directory,
                platform_workspace_root=platform_workspace_root,
                claude_executable=claude_executable,
                claude_default_platform_workspace_add_dir=(
                    claude_default_platform_workspace_add_dir
                ),
                claude_add_dirs=claude_add_dirs,
                claude_allowed_tools=claude_allowed_tools,
                claude_permission_mode=claude_permission_mode,
                claude_settings_path=claude_settings_path,
                claude_activation_backend=claude_activation_backend,
                claude_reply_writeback_mode=claude_reply_writeback_mode,
                codex_executable=codex_executable,
                codex_default_platform_workspace_add_dir=(
                    codex_default_platform_workspace_add_dir
                ),
                codex_add_dirs=codex_add_dirs,
                codex_sandbox_mode=codex_sandbox_mode,
                codex_approval_policy=codex_approval_policy,
                codex_git_repo_check_policy=codex_git_repo_check_policy,
                codex_git_repo_check_policy_source=(
                    codex_git_repo_check_policy_source
                ),
                codex_activation_backend=codex_activation_backend,
                codex_app_server_approval_decision=(
                    codex_app_server_approval_decision
                ),
                codex_busy_delivery_policy=codex_busy_delivery_policy,
                codex_busy_delivery_policy_explicit=(
                    codex_busy_delivery_policy_explicit
                ),
                codex_reply_writeback_mode=codex_reply_writeback_mode,
                immediate_busy_policy=immediate_busy_policy,
                hermes_executable=hermes_executable,
                hermes_home=hermes_home,
                hermes_activation_backend=hermes_activation_backend,
                hermes_reply_writeback_mode=hermes_reply_writeback_mode,
                hermes_gateway_python=hermes_gateway_python,
                hermes_source_tag=hermes_source_tag,
                hermes_max_turns=hermes_max_turns,
                activation_timeout_seconds=activation_timeout_seconds,
                skip_busy_target=skip_busy_target,
                read_live_runtime_status=read_live_runtime_status,
                dry_run=dry_run,
            )

    def agent_exchange_thread_instructions(
        self,
        workspace_id: str | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().agent_exchange_thread_instructions(
                workspace_id
            )

    def list_agent_exchange_threads(
        self,
        *,
        workspace_id: str,
        requesting_agent_id: str | None = None,
        status: str | None = None,
        visibility: str | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().list_agent_exchange_threads(
                workspace_id,
                requesting_agent_id=requesting_agent_id,
                status=status,
                visibility=visibility,
            )

    def get_agent_exchange_thread_status(
        self,
        *,
        workspace_id: str,
        thread_id: str,
        requesting_agent_id: str | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_agent_exchange_thread_status(
                workspace_id,
                thread_id=thread_id,
                requesting_agent_id=requesting_agent_id,
            )

    def list_agent_exchange_thread_requests(
        self,
        *,
        workspace_id: str,
        thread_id: str,
        requesting_agent_id: str | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().list_agent_exchange_thread_requests(
                workspace_id,
                thread_id=thread_id,
                requesting_agent_id=requesting_agent_id,
            )

    def create_agent_exchange_thread_follow_up(
        self,
        *,
        workspace_id: str,
        thread_id: str,
        source_agent_id: str,
        target_agent_id: str,
        request_kind: str,
        request_summary: str,
        parent_request_id: str | None = None,
        exchange_request_id: str | None = None,
        detail_refs: tuple[str, ...] = (),
        linked_task_id: str | None = None,
        linked_conversation_id: str | None = None,
        linked_activation_id: str | None = None,
        linked_delegated_wake_grant_id: str | None = None,
        requires_user_review: bool = False,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().create_agent_exchange_thread_follow_up(
                workspace_id,
                thread_id=thread_id,
                source_agent_id=source_agent_id,
                target_agent_id=target_agent_id,
                request_kind=request_kind,
                request_summary=request_summary,
                parent_request_id=parent_request_id,
                exchange_request_id=exchange_request_id,
                detail_refs=detail_refs,
                linked_task_id=linked_task_id,
                linked_conversation_id=linked_conversation_id,
                linked_activation_id=linked_activation_id,
                linked_delegated_wake_grant_id=linked_delegated_wake_grant_id,
                requires_user_review=requires_user_review,
                metadata=metadata,
            )

    def update_agent_exchange_thread_visibility(
        self,
        *,
        workspace_id: str,
        thread_id: str,
        updated_by_agent_id: str,
        visibility: str,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().update_agent_exchange_thread_visibility(
                workspace_id,
                thread_id=thread_id,
                updated_by_agent_id=updated_by_agent_id,
                visibility=visibility,
                metadata=metadata,
            )

    def close_agent_exchange_thread(
        self,
        *,
        workspace_id: str,
        thread_id: str,
        terminal_reason: str = "closed",
        closed_by_agent_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().close_agent_exchange_thread(
                workspace_id,
                thread_id=thread_id,
                terminal_reason=terminal_reason,
                closed_by_agent_id=closed_by_agent_id,
                metadata=metadata,
            )

    def agent_wake_instructions(
        self,
        workspace_id: str | None = None,
        *,
        agent_id: str | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().agent_wake_instructions(
                workspace_id,
                agent_id=agent_id,
            )

    def run_agent_wake_once(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        profile: Mapping[str, object] | None = None,
        config_path: str | None = None,
        dry_run: bool = False,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().run_agent_wake_once(
                workspace_id,
                agent_id=agent_id,
                profile=profile,
                database_path=self.settings.database,
                workspace_root=self.settings.workspace_root,
                plugins_directory=self.settings.plugins_directory,
                config_path=config_path,
                runtime_profile_path=self.settings.profile_path,
                dry_run=dry_run,
            )

    def list_agent_wake_deliveries(
        self,
        *,
        workspace_id: str,
        agent_id: str | None = None,
        exchange_request_id: str | None = None,
        wake_ticket_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().list_agent_wake_deliveries(
                workspace_id,
                agent_id=agent_id,
                exchange_request_id=exchange_request_id,
                wake_ticket_id=wake_ticket_id,
                status=status,
                limit=limit,
            )

    def get_agent_wake_status(
        self,
        *,
        workspace_id: str,
        exchange_request_id: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_agent_wake_status(
                workspace_id,
                exchange_request_id=exchange_request_id,
            )

    def get_agent_wake_ticket(
        self,
        *,
        workspace_id: str,
        exchange_request_id: str | None = None,
        wake_ticket_id: str | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_agent_wake_ticket(
                workspace_id,
                exchange_request_id=exchange_request_id,
                wake_ticket_id=wake_ticket_id,
            )

    def discover_agent_sessions(
        self,
        *,
        provider: str,
        limit: int = 20,
        cwd: str | None = None,
        claude_home: str | None = None,
        codex_home: str | None = None,
        hermes_home: str | None = None,
        hermes_executable: str = "hermes",
        hermes_source: str | None = None,
        hermes_timeout_seconds: float = 15.0,
        current_session_id: str | None = None,
        include_turn_snippets: bool = False,
        include_full_session_history: bool = False,
        snippet_turn_index: int | None = None,
        snippet_max_chars: int = 160,
        provider_account_label: str | None = None,
        vendor_account_label: str | None = None,
        relay_account_label: str | None = None,
    ) -> Mapping[str, object]:
        return discover_agent_sessions(
            provider=provider,
            limit=limit,
            cwd=cwd,
            claude_home=claude_home,
            codex_home=codex_home,
            hermes_home=hermes_home,
            hermes_executable=hermes_executable,
            hermes_source=hermes_source,
            hermes_timeout_seconds=hermes_timeout_seconds,
            current_session_id=current_session_id,
            include_turn_snippets=include_turn_snippets,
            include_full_session_history=include_full_session_history,
            snippet_turn_index=snippet_turn_index,
            snippet_max_chars=snippet_max_chars,
            provider_account_label=provider_account_label,
            vendor_account_label=vendor_account_label,
            relay_account_label=relay_account_label,
        )

    def register_discovered_agent_session_handle(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        provider: str,
        session_id: str,
        created_by: str,
        reason: str,
        handle_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
        limit: int = 20,
        cwd: str | None = None,
        claude_home: str | None = None,
        codex_home: str | None = None,
        hermes_home: str | None = None,
        hermes_executable: str = "hermes",
        hermes_source: str | None = None,
        hermes_timeout_seconds: float = 15.0,
        current_session_id: str | None = None,
        include_turn_snippets: bool = False,
        snippet_turn_index: int | None = None,
        snippet_max_chars: int = 160,
    ) -> Mapping[str, object]:
        self.open_workspace(workspace_id)
        discovery = self.discover_agent_sessions(
            provider=provider,
            limit=limit,
            cwd=cwd,
            claude_home=claude_home,
            codex_home=codex_home,
            hermes_home=hermes_home,
            hermes_executable=hermes_executable,
            hermes_source=hermes_source,
            hermes_timeout_seconds=hermes_timeout_seconds,
            current_session_id=current_session_id,
            include_turn_snippets=include_turn_snippets,
            snippet_turn_index=snippet_turn_index,
            snippet_max_chars=snippet_max_chars,
        )
        record = find_discovered_agent_session(
            discovery,
            provider=provider,
            session_id=session_id,
        )
        return self._register_discovered_agent_session_record(
            workspace_id=workspace_id,
            agent_id=agent_id,
            record=record,
            handle_id=handle_id,
            created_by=created_by,
            reason=reason,
            metadata=metadata,
        )

    def _register_discovered_agent_session_record(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        record: Mapping[str, object],
        created_by: str,
        reason: str,
        handle_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        if not record.get("registrationReady"):
            missing = ", ".join(str(item) for item in record.get("missingFields", ()))
            raise ValueError(
                "discovered agent session is not registration-ready"
                f" (missing: {missing})."
            )
        registration_metadata = discovery_registration_metadata(
            record,
            metadata=metadata,
        )
        runtime = str(record["agentRuntime"])
        if runtime == "claude":
            registered = self.register_claude_session_handle(
                workspace_id=workspace_id,
                agent_id=agent_id,
                handle_id=handle_id,
                claude_session_uuid=str(record["sessionId"]),
                cwd=str(record["cwd"]),
                source_path=_optional_text(record.get("sourcePath")),
                created_by=created_by,
                reason=reason,
                metadata=registration_metadata,
            )
        elif runtime == "codex":
            registered = self.register_codex_session_handle(
                workspace_id=workspace_id,
                agent_id=agent_id,
                handle_id=handle_id,
                codex_session_id=str(record["sessionId"]),
                cwd=str(record["cwd"]),
                source_path=_optional_text(record.get("sourcePath")),
                created_by=created_by,
                reason=reason,
                metadata=registration_metadata,
            )
        elif runtime == "hermes":
            registered = self.register_hermes_session_handle(
                workspace_id=workspace_id,
                agent_id=agent_id,
                handle_id=handle_id,
                hermes_session_id=str(record["sessionId"]),
                cwd=str(record["cwd"]),
                source_path=_optional_text(record.get("sourcePath")),
                created_by=created_by,
                reason=reason,
                metadata=registration_metadata,
            )
        else:
            raise ValueError("provider must be one of: claude, codex, hermes.")
        return {
            **registered,
            "discoveredAgentSession": record,
        }

    def login_discovered_agent_endpoint(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        provider: str,
        alias: str,
        created_by: str,
        reason: str,
        session_id: str | None = None,
        handle_id: str | None = None,
        endpoint_id: str | None = None,
        direction: str = "send_receive",
        default_reply_policy: str = "source_handle_required",
        contact_policy: str = "open",
        metadata: Mapping[str, object] | None = None,
        limit: int = 20,
        cwd: str | None = None,
        claude_home: str | None = None,
        codex_home: str | None = None,
        hermes_home: str | None = None,
        hermes_executable: str = "hermes",
        hermes_source: str | None = None,
        hermes_timeout_seconds: float = 15.0,
        current_session_id: str | None = None,
        include_turn_snippets: bool = False,
        snippet_turn_index: int | None = None,
        snippet_max_chars: int = 160,
        allow_source_endpoint_aliases: Sequence[str] = (),
        allow_source_agent_ids: Sequence[str] = (),
        allow_source_handle_ids: Sequence[str] = (),
        block_source_endpoint_aliases: Sequence[str] = (),
        block_source_agent_ids: Sequence[str] = (),
        block_source_handle_ids: Sequence[str] = (),
    ) -> Mapping[str, object]:
        normalized_provider = normalize_agent_endpoint_provider(provider)
        if normalized_provider is None:
            raise ValueError("provider must be one of: claude, codex, hermes.")
        self.open_workspace(workspace_id)
        discovery = self.discover_agent_sessions(
            provider=normalized_provider,
            limit=limit,
            cwd=cwd,
            claude_home=claude_home,
            codex_home=codex_home,
            hermes_home=hermes_home,
            hermes_executable=hermes_executable,
            hermes_source=hermes_source,
            hermes_timeout_seconds=hermes_timeout_seconds,
            current_session_id=current_session_id,
            include_turn_snippets=include_turn_snippets,
            snippet_turn_index=snippet_turn_index,
            snippet_max_chars=snippet_max_chars,
        )
        selected = (
            _DiscoveredEndpointLoginSelection.explicit(
                find_discovered_agent_session(
                    discovery,
                    provider=normalized_provider,
                    session_id=session_id,
                )
            )
            if session_id is not None
            else _select_discovered_endpoint_login_session(
                discovery,
                provider=normalized_provider,
                cwd=cwd,
            )
        )
        macro_metadata = {
            **dict(metadata or {}),
            "endpointLoginMacro": {
                "schema": "agent_endpoint_login_discovered_metadata.v1",
                "highLevelEndpointLoginApi": True,
                "selectionMethod": selected.selection_method,
                "cwdMatched": selected.cwd_matched,
                "providerAccountRead": bool(
                    selected.record.get("providerAccountRead")
                ),
                "turnSnippetRead": bool(selected.record.get("turnSnippetRead")),
            },
        }
        registered = self._register_discovered_agent_session_record(
            workspace_id=workspace_id,
            agent_id=agent_id,
            record=selected.record,
            handle_id=handle_id,
            created_by=created_by,
            reason=reason,
            metadata=macro_metadata,
        )
        provider_handle_id = _registered_provider_handle_id(
            registered,
            normalized_provider,
        )
        endpoint = self.login_agent_endpoint(
            workspace_id=workspace_id,
            agent_id=agent_id,
            endpoint_id=endpoint_id,
            alias=alias,
            provider=normalized_provider,
            provider_handle_id=provider_handle_id,
            direction=direction,
            default_reply_policy=default_reply_policy,
            contact_policy=contact_policy,
            created_by=created_by,
            reason=reason,
            metadata=_agent_endpoint_login_metadata(
                macro_metadata,
                allow_source_endpoint_aliases=allow_source_endpoint_aliases,
                allow_source_agent_ids=allow_source_agent_ids,
                allow_source_handle_ids=allow_source_handle_ids,
                block_source_endpoint_aliases=block_source_endpoint_aliases,
                block_source_agent_ids=block_source_agent_ids,
                block_source_handle_ids=block_source_handle_ids,
            ),
        )
        return {
            "schema": "agent_endpoint_login_discovered.v1",
            "workspaceId": workspace_id,
            "agentId": agent_id,
            "provider": normalized_provider,
            "alias": endpoint["agentEndpoint"]["alias"],
            "selection": selected.to_metadata(),
            "discoveredAgentSession": selected.record,
            "registeredSessionHandle": _registered_provider_handle_metadata(
                registered,
                normalized_provider,
            ),
            "agentEndpoint": endpoint["agentEndpoint"],
            "providerHandle": endpoint["providerHandle"],
            "handleRegistered": True,
            "endpointLoggedIn": True,
            "discovery": discovery["agentSessionDiscovery"],
            "sourceEventSequence": endpoint.get("sourceEventSequence"),
            "handleSourceEventSequence": registered.get("sourceEventSequence"),
        }

    def onboard_agent_provider(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        agent_name: str,
        provider: str,
        endpoint_alias: str,
        description: str = "Beacon provider endpoint agent.",
        session_id: str | None = None,
        handle_id: str | None = None,
        endpoint_id: str | None = None,
        direction: str = "send_receive",
        default_reply_policy: str = "source_handle_required",
        contact_policy: str = "open",
        created_by: str = "user",
        reason: str = "agent provider onboard",
        metadata: Mapping[str, object] | None = None,
        reuse_existing: bool = True,
        dry_run: bool = False,
        limit: int = 20,
        cwd: str | None = None,
        claude_home: str | None = None,
        codex_home: str | None = None,
        hermes_home: str | None = None,
        hermes_executable: str = "hermes",
        hermes_source: str | None = None,
        hermes_timeout_seconds: float = 15.0,
        current_session_id: str | None = None,
        include_turn_snippets: bool = False,
        snippet_turn_index: int | None = None,
        snippet_max_chars: int = 160,
        allow_source_endpoint_aliases: Sequence[str] = (),
        allow_source_agent_ids: Sequence[str] = (),
        allow_source_handle_ids: Sequence[str] = (),
        block_source_endpoint_aliases: Sequence[str] = (),
        block_source_agent_ids: Sequence[str] = (),
        block_source_handle_ids: Sequence[str] = (),
        allow_shared_session_binding: bool = False,
    ) -> Mapping[str, object]:
        normalized_provider = normalize_agent_endpoint_provider(provider)
        if normalized_provider is None:
            raise ValueError("provider must be one of: claude, codex, hermes.")
        normalized_direction = _onboard_endpoint_direction(direction)
        normalized_reply_policy = _onboard_reply_policy(default_reply_policy)
        normalized_alias = normalize_agent_endpoint_alias(endpoint_alias)
        effective_session_id = _optional_text(session_id) or _optional_text(
            current_session_id
        )
        stages: list[Mapping[str, object]] = []
        try:
            self.open_workspace(workspace_id)
        except ValueError as exc:
            return _agent_provider_onboard_failure(
                settings=self.settings,
                workspace_id=workspace_id,
                endpoint_alias=normalized_alias,
                provider=normalized_provider,
                failed_stage="workspacePreflight",
                stages=stages,
                message=str(exc),
                discovery={},
                dry_run=dry_run,
            )
        discovery = self.discover_agent_sessions(
            provider=normalized_provider,
            limit=limit,
            cwd=cwd,
            claude_home=claude_home,
            codex_home=codex_home,
            hermes_home=hermes_home,
            hermes_executable=hermes_executable,
            hermes_source=hermes_source,
            hermes_timeout_seconds=hermes_timeout_seconds,
            current_session_id=current_session_id,
            include_turn_snippets=include_turn_snippets,
            snippet_turn_index=snippet_turn_index,
            snippet_max_chars=snippet_max_chars,
        )
        try:
            selected = (
                _DiscoveredEndpointLoginSelection.explicit(
                    find_discovered_agent_session(
                        discovery,
                        provider=normalized_provider,
                        session_id=effective_session_id,
                    )
                )
                if effective_session_id is not None
                else _select_discovered_endpoint_login_session(
                    discovery,
                    provider=normalized_provider,
                    cwd=cwd,
                )
            )
            if not selected.record.get("registrationReady"):
                missing = ", ".join(
                    str(item) for item in selected.record.get("missingFields", ())
                )
                raise ValueError(
                    "discovered agent session is not registration-ready"
                    f" (missing: {missing})."
                )
        except ValueError as exc:
            return _agent_provider_onboard_failure(
                settings=self.settings,
                workspace_id=workspace_id,
                endpoint_alias=normalized_alias,
                provider=normalized_provider,
                failed_stage="sessionDiscovery",
                stages=stages,
                message=str(exc),
                discovery=discovery,
                dry_run=dry_run,
            )
        stages.append(
            {
                "stage": "sessionDiscovery",
                "status": "selected",
                "selection": selected.to_metadata(),
                "discoveredAgentSession": selected.record,
            }
        )

        preflight_conflict = self._agent_provider_onboard_binding_conflict(
            workspace_id=workspace_id,
            agent_id=agent_id,
            provider=normalized_provider,
            session_id=str(selected.record["sessionId"]),
            endpoint_alias=normalized_alias,
            handle_id=handle_id,
            endpoint_id=endpoint_id,
            direction=normalized_direction,
            default_reply_policy=normalized_reply_policy,
            contact_policy=contact_policy,
            allow_shared_session_binding=allow_shared_session_binding,
        )
        if preflight_conflict is not None:
            return _agent_provider_onboard_failure(
                settings=self.settings,
                workspace_id=workspace_id,
                endpoint_alias=normalized_alias,
                provider=normalized_provider,
                failed_stage="bindingPreflight",
                stages=stages,
                message=str(preflight_conflict["message"]),
                conflict=preflight_conflict,
                discovery=discovery,
                dry_run=dry_run,
            )

        existing_agent = self._find_workspace_agent(
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        if existing_agent is not None:
            if not reuse_existing:
                return _agent_provider_onboard_failure(
                    settings=self.settings,
                    workspace_id=workspace_id,
                    endpoint_alias=normalized_alias,
                    provider=normalized_provider,
                    failed_stage="agentIdentity",
                    stages=stages,
                    message="agent already exists and --no-reuse-existing was set.",
                    conflict={"agent": existing_agent},
                    discovery=discovery,
                    dry_run=dry_run,
                )
            agent_stage = {
                "stage": "agentIdentity",
                "status": "reused",
                "agent": existing_agent,
            }
        elif dry_run:
            agent_stage = {
                "stage": "agentIdentity",
                "status": "would_create",
                "agent": {
                    "agentId": agent_id,
                    "workspaceId": workspace_id,
                    "name": agent_name,
                    "description": description,
                },
            }
        else:
            try:
                created_agent = self.create_agent(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    name=agent_name,
                    description=description,
                    metadata={
                        **dict(metadata or {}),
                        "agentProviderOnboard": {
                            "schema": "agent_provider_onboard_metadata.v1",
                            "provider": normalized_provider,
                            "endpointAlias": normalized_alias,
                        },
                    },
                )
            except ValueError as exc:
                return _agent_provider_onboard_failure(
                    settings=self.settings,
                    workspace_id=workspace_id,
                    endpoint_alias=normalized_alias,
                    provider=normalized_provider,
                    failed_stage="agentIdentity",
                    stages=stages,
                    message=str(exc),
                    discovery=discovery,
                    dry_run=dry_run,
                )
            agent_stage = {
                "stage": "agentIdentity",
                "status": "created",
                "agent": created_agent["agent"],
            }
        stages.append(agent_stage)

        selected_session_id = str(selected.record["sessionId"])
        handle_result = self._onboard_provider_handle(
            workspace_id=workspace_id,
            agent_id=agent_id,
            provider=normalized_provider,
            session_id=selected_session_id,
            selected_record=selected.record,
            handle_id=handle_id,
            created_by=created_by,
            reason=reason,
            metadata=metadata,
            reuse_existing=reuse_existing,
            dry_run=dry_run,
        )
        stages.append(handle_result["stage"])
        if not handle_result["ok"]:
            return _agent_provider_onboard_failure(
                settings=self.settings,
                workspace_id=workspace_id,
                endpoint_alias=normalized_alias,
                provider=normalized_provider,
                failed_stage="providerSessionHandle",
                stages=stages,
                message=str(handle_result["message"]),
                conflict=handle_result.get("conflict"),
                discovery=discovery,
                dry_run=dry_run,
            )
        provider_handle = handle_result["providerHandle"]
        provider_handle_id = str(provider_handle["handleId"])

        endpoint_result = self._onboard_agent_endpoint(
            workspace_id=workspace_id,
            agent_id=agent_id,
            alias=normalized_alias,
            provider=normalized_provider,
            provider_handle_id=provider_handle_id,
            endpoint_id=endpoint_id,
            direction=normalized_direction,
            default_reply_policy=normalized_reply_policy,
            contact_policy=contact_policy,
            created_by=created_by,
            reason=reason,
            metadata=metadata,
            allow_source_endpoint_aliases=allow_source_endpoint_aliases,
            allow_source_agent_ids=allow_source_agent_ids,
            allow_source_handle_ids=allow_source_handle_ids,
            block_source_endpoint_aliases=block_source_endpoint_aliases,
            block_source_agent_ids=block_source_agent_ids,
            block_source_handle_ids=block_source_handle_ids,
            reuse_existing=reuse_existing,
            dry_run=dry_run,
        )
        stages.append(endpoint_result["stage"])
        if not endpoint_result["ok"]:
            return _agent_provider_onboard_failure(
                settings=self.settings,
                workspace_id=workspace_id,
                endpoint_alias=normalized_alias,
                provider=normalized_provider,
                failed_stage="endpointLogin",
                stages=stages,
                message=str(endpoint_result["message"]),
                conflict=endpoint_result.get("conflict"),
                discovery=discovery,
                dry_run=dry_run,
            )

        next_commands = _agent_provider_onboard_next_commands(
            self.settings,
            workspace_id=workspace_id,
            endpoint_alias=normalized_alias,
        )
        return {
            "schema": "agent_provider_onboard.v1",
            "ok": True,
            "completed": not dry_run,
            "dryRun": dry_run,
            "workspaceId": workspace_id,
            "agentId": agent_id,
            "provider": normalized_provider,
            "endpointAlias": normalized_alias,
            "sessionId": selected_session_id,
            "providerHandleId": provider_handle_id,
            "stages": stages,
            "selection": selected.to_metadata(),
            "discoveredAgentSession": selected.record,
            "registeredSessionHandle": provider_handle,
            "agentEndpoint": endpoint_result.get("agentEndpoint"),
            "discovery": discovery["agentSessionDiscovery"],
            **next_commands,
            "boundaries": {
                "providerAccountCreated": False,
                "providerCredentialStored": False,
                "providerGlobalSettingsModified": False,
                "providerPermissionDefaultsModified": False,
                "fullSessionHistoryRead": False,
            },
        }

    def join_agent(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        provider: str,
        session_id: str,
        agent_name: str | None = None,
        created_by: str = "agent",
        reason: str = "agent join",
        metadata: Mapping[str, object] | None = None,
        reuse_existing: bool = True,
        dry_run: bool = False,
        limit: int = 100,
        cwd: str | None = None,
        claude_home: str | None = None,
        codex_home: str | None = None,
        hermes_home: str | None = None,
        hermes_executable: str = "hermes",
        hermes_source: str | None = None,
        hermes_timeout_seconds: float = 15.0,
    ) -> Mapping[str, object]:
        normalized_provider = normalize_agent_endpoint_provider(provider)
        if normalized_provider == "deepseek_harness":
            raise ValueError(
                "DeepSeek Harness exact-session join requires managed-runtime "
                "configuration; use join_deepseek_harness_agent or the agent-join CLI."
            )
        visible_agent_id = _required_visible_agent_id(agent_id)
        exact_session_id = _required_visible_agent_id(session_id)
        result = self.onboard_agent_provider(
            workspace_id=workspace_id,
            agent_id=visible_agent_id,
            agent_name=_optional_text(agent_name) or visible_agent_id,
            provider=provider,
            endpoint_alias=visible_agent_id,
            description="Beacon joined provider session agent.",
            session_id=exact_session_id,
            direction="send_receive",
            default_reply_policy="source_handle_required",
            contact_policy="open",
            created_by=created_by,
            reason=reason,
            metadata={
                **dict(metadata or {}),
                "agentJoin": {
                    "schema": "agent_join_metadata.v1",
                    "visibleAgentId": visible_agent_id,
                    "exactSessionIdProvided": True,
                    "primaryEndpointAlias": visible_agent_id,
                },
            },
            reuse_existing=reuse_existing,
            dry_run=dry_run,
            limit=limit,
            cwd=cwd,
            claude_home=claude_home,
            codex_home=codex_home,
            hermes_home=hermes_home,
            hermes_executable=hermes_executable,
            hermes_source=hermes_source,
            hermes_timeout_seconds=hermes_timeout_seconds,
            current_session_id=exact_session_id,
        )
        return {
            "schema": "agent_join.v1",
            "ok": result.get("ok", False),
            "completed": result.get("completed", False),
            "dryRun": dry_run,
            "workspaceId": workspace_id,
            "visibleAgentId": visible_agent_id,
            "provider": normalize_agent_endpoint_provider(provider),
            "nativeSessionId": exact_session_id,
            "primaryEndpointAlias": visible_agent_id,
            "onboarding": result,
            "ordinarySendAddress": visible_agent_id,
            "databaseScanned": False,
            "sessionSelection": "exact_id",
        }

    def join_deepseek_harness_agent(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        cwd: str | None,
        carrier: str,
        executable_path: str,
        package_root: str,
        cordis_config_path: str | None,
        runtime_home: str,
        runtime_home_source: str,
        state_root: str,
        session_root: str,
        model_provider: str,
        model: str,
        session_id: str | None = None,
        session_compression: str = "zstd",
        resumed_from: Mapping[str, object] | None = None,
        reply_writeback_mode: str = "explicit_only",
        agent_name: str | None = None,
        created_by: str = "user",
        reason: str = "join DeepSeek Harness session",
        initialize_timeout_seconds: float = 30.0,
        operation_timeout_seconds: float = 120.0,
        shutdown_timeout_seconds: float = 5.0,
        max_line_bytes: int = 1024 * 1024,
        max_total_output_bytes: int = 32 * 1024 * 1024,
        max_stderr_bytes: int = 64 * 1024,
    ) -> Mapping[str, object]:
        """Create or resume, register, and address one Beacon-managed DSH session."""

        visible_agent_id = _required_visible_agent_id(agent_id)
        self.open_workspace(workspace_id)
        alias = normalize_agent_endpoint_alias(visible_agent_id)
        dsh_session_id = (
            _required_visible_agent_id(session_id)
            if session_id is not None
            else f"beacon-dsh-session-{uuid4()}"
        )
        session_start_mode = "resume" if session_id is not None else "create"
        active_endpoints = self.list_agent_endpoints(
            workspace_id=workspace_id,
            include_inactive=False,
        )["agentEndpoints"]
        existing_handles = self.list_deepseek_harness_session_handles(
            workspace_id=workspace_id,
            include_inactive=True,
        )["deepseekHarnessSessionHandles"]
        active_session_owners = [
            item
            for item in existing_handles
            if item.get("deepseekHarnessSessionId") == dsh_session_id
            and item.get("state") == "active"
        ]
        if active_session_owners:
            if len(active_session_owners) != 1:
                raise ValueError(
                    "DeepSeek Harness native session has multiple active Beacon "
                    "owners; resolve the registry conflict before joining."
                )
            owner = active_session_owners[0]
            matching_endpoint = next(
                (
                    item
                    for item in active_endpoints
                    if item.get("alias") == alias
                    and item.get("agentId") == visible_agent_id
                    and item.get("providerHandleId") == owner.get("handleId")
                ),
                None,
            )
            if owner.get("agentId") == visible_agent_id and matching_endpoint is not None:
                binding = _deepseek_harness_handle_binding(owner)
                try:
                    raw_live_spec = json.loads(
                        Path(str(binding["runtimeSpecPath"])).read_text(
                            encoding="utf-8"
                        )
                    )
                    if not isinstance(raw_live_spec, MappingABC):
                        raise ValueError("runtime spec is not an object")
                    live_spec = DeepSeekHarnessRuntimeSpec.from_mapping(raw_live_spec)
                except (KeyError, OSError, TypeError, ValueError) as exc:
                    raise ValueError(
                        "the live DeepSeek Harness binding runtime spec is unreadable; "
                        "inspect or stop the known owner before joining again."
                    ) from exc

                def path_differs(current: str | None, requested: str | None) -> bool:
                    if current is None or requested is None:
                        return current != requested
                    return (
                        Path(current).expanduser().resolve(strict=False)
                        != Path(requested).expanduser().resolve(strict=False)
                    )

                conflicts: list[str] = []
                if cwd is not None and path_differs(live_spec.cwd, cwd):
                    conflicts.append("cwd")
                if live_spec.session_compression != session_compression:
                    conflicts.append("sessionCompression")
                if live_spec.carrier != carrier:
                    conflicts.append("carrier")
                if path_differs(live_spec.executable_path, executable_path):
                    conflicts.append("executablePath")
                if path_differs(live_spec.package_root, package_root):
                    conflicts.append("packageRoot")
                if path_differs(live_spec.cordis_config_path, cordis_config_path):
                    conflicts.append("cordisConfigPath")
                if path_differs(live_spec.runtime_home, runtime_home):
                    conflicts.append("runtimeHome")
                if path_differs(
                    str(Path(live_spec.paths.state_directory).parent),
                    state_root,
                ):
                    conflicts.append("stateRoot")
                if path_differs(live_spec.session_root, session_root):
                    conflicts.append("sessionRoot")
                if live_spec.model_provider != model_provider:
                    conflicts.append("modelProvider")
                if live_spec.model != model:
                    conflicts.append("model")
                if live_spec.reply_writeback_mode != reply_writeback_mode:
                    conflicts.append("replyWritebackMode")
                if live_spec.initialize_timeout_seconds != initialize_timeout_seconds:
                    conflicts.append("initializeTimeoutSeconds")
                if live_spec.operation_timeout_seconds != operation_timeout_seconds:
                    conflicts.append("operationTimeoutSeconds")
                if live_spec.shutdown_timeout_seconds != shutdown_timeout_seconds:
                    conflicts.append("shutdownTimeoutSeconds")
                if live_spec.max_line_bytes != max_line_bytes:
                    conflicts.append("maxLineBytes")
                if live_spec.max_total_output_bytes != max_total_output_bytes:
                    conflicts.append("maxTotalOutputBytes")
                if live_spec.max_stderr_bytes != max_stderr_bytes:
                    conflicts.append("maxStderrBytes")
                if conflicts:
                    raise ValueError(
                        "repeat DeepSeek Harness join conflicts with the live "
                        "binding: " + ", ".join(conflicts)
                    )
                status = self.get_deepseek_harness_runtime_status(
                    workspace_id=workspace_id,
                    handle_id=str(owner["handleId"]),
                )
                runtime_status = status.get("runtimeStatus")
                if isinstance(runtime_status, MappingABC) and runtime_status.get("ok") is True:
                    return {
                        "schema": "deepseek_harness_agent_join.v1",
                        "ok": True,
                        "completed": True,
                        "reused": True,
                        "workspaceId": workspace_id,
                        "visibleAgentId": visible_agent_id,
                        "provider": "deepseek_harness",
                        "nativeSessionId": dsh_session_id,
                        "primaryEndpointAlias": alias,
                        "deepseekHarnessSessionHandle": owner,
                        "agentEndpoint": matching_endpoint,
                        "runtime": runtime_status.get("runtimeState"),
                        "dispatchReady": True,
                        "existingSessionImport": session_start_mode == "resume",
                        "sessionStartMode": session_start_mode,
                        "sessionSelection": "exact_id",
                        "databaseScanned": False,
                        "authenticatedRealModelSmokeRun": False,
                    }
            raise ValueError(
                "DeepSeek Harness native session already has an active owner in this workspace."
            )
        if any(
            item.get("agentId") == visible_agent_id and item.get("state") == "active"
            for item in existing_handles
        ):
            raise ValueError(
                "visible Agent already owns an active DeepSeek Harness session."
            )
        endpoint_to_rebind = next(
            (item for item in active_endpoints if item.get("alias") == alias),
            None,
        )
        if endpoint_to_rebind is not None:
            old_handle_id = endpoint_to_rebind.get("providerHandleId")
            old_handle = next(
                (item for item in existing_handles if item.get("handleId") == old_handle_id),
                None,
            )
            if (
                session_start_mode != "resume"
                or endpoint_to_rebind.get("agentId") != visible_agent_id
                or old_handle is None
                or old_handle.get("deepseekHarnessSessionId") != dsh_session_id
                or old_handle.get("state") == "active"
            ):
                raise ValueError("visible Agent alias is already active.")
        previous_same_session = max(
            (
                item
                for item in existing_handles
                if item.get("agentId") == visible_agent_id
                and item.get("deepseekHarnessSessionId") == dsh_session_id
                and item.get("state") != "active"
            ),
            key=lambda item: str(item.get("updatedAt") or ""),
            default=None,
        )
        effective_session_root = session_root
        if previous_same_session is not None:
            previous_binding = _deepseek_harness_handle_binding(previous_same_session)
            stored_root = previous_binding.get("sessionRoot")
            if isinstance(stored_root, str) and stored_root.strip():
                effective_session_root = stored_root

        preflight = preflight_deepseek_harness_runtime(
            carrier=carrier,
            executable_path=executable_path,
            package_root=package_root,
            cordis_config_path=cordis_config_path,
            runtime_home=runtime_home,
            state_root=state_root,
            session_root=effective_session_root,
            session_id=dsh_session_id,
            session_start_mode=session_start_mode,
            session_compression=session_compression,
        )
        if preflight.get("supported") is not True:
            return {
                "schema": "deepseek_harness_agent_join.v1",
                "ok": False,
                "completed": False,
                "failedStage": "runtimePreflight",
                "workspaceId": workspace_id,
                "visibleAgentId": visible_agent_id,
                "provider": "deepseek_harness",
                "preflight": preflight,
                "writesApplied": False,
            }

        if session_start_mode == "resume":
            probe = preflight.get("sessionProbe")
            persisted = probe.get("session") if isinstance(probe, MappingABC) else None
            persisted_cwd = (
                persisted.get("cwd") if isinstance(persisted, MappingABC) else None
            )
            if not isinstance(persisted_cwd, str) or not persisted_cwd.strip():
                raise ValueError(
                    "the existing DSH session header does not provide a usable cwd."
                )
            resolved_cwd = Path(persisted_cwd).expanduser().resolve()
            if cwd is not None and Path(cwd).expanduser().resolve() != resolved_cwd:
                raise ValueError(
                    "configured cwd conflicts with the persisted DSH session header cwd."
                )
        else:
            if cwd is None:
                raise ValueError("cwd is required when creating a new DSH session.")
            resolved_cwd = Path(cwd).expanduser().resolve()
        if not resolved_cwd.is_dir():
            raise ValueError("DSH session cwd must be an existing directory.")

        handle_id = f"deepseek-harness-handle-{uuid4()}"
        launch_args = preflight.get("launchArgs")
        if not isinstance(launch_args, Sequence) or isinstance(launch_args, (str, bytes)):
            raise ValueError("DeepSeek Harness preflight launchArgs are missing.")
        package_version = str(preflight["expectedPackageVersion"])
        runtime_executable = str(
            preflight.get("runtimeExecutablePath") or launch_args[0]
        )
        spec = build_deepseek_harness_runtime_spec(
            workspace_id=workspace_id,
            agent_id=visible_agent_id,
            handle_id=handle_id,
            dsh_session_id=dsh_session_id,
            session_start_mode=session_start_mode,
            session_compression=session_compression,
            cwd=str(resolved_cwd),
            session_root=str(
                Path(effective_session_root).expanduser().resolve(strict=False)
                if session_start_mode == "resume"
                else Path(effective_session_root).expanduser().resolve(strict=False)
                / dsh_session_id
            ),
            runtime_home=runtime_home,
            runtime_home_source=runtime_home_source,
            carrier=carrier,
            executable_path=runtime_executable,
            launch_args=tuple(str(item) for item in launch_args),
            cordis_config_path=(
                str(preflight["runtimeConfigPath"])
                if preflight.get("runtimeConfigPath") is not None
                else cordis_config_path
            ),
            package_root=package_root,
            package_version=package_version,
            expected_server_version=str(
                preflight.get("expectedServerVersion") or package_version
            ),
            model_provider=model_provider,
            model=model,
            state_root=state_root,
            reply_writeback_mode=reply_writeback_mode,
            initialize_timeout_seconds=initialize_timeout_seconds,
            operation_timeout_seconds=operation_timeout_seconds,
            shutdown_timeout_seconds=shutdown_timeout_seconds,
            max_line_bytes=max_line_bytes,
            max_total_output_bytes=max_total_output_bytes,
            max_stderr_bytes=max_stderr_bytes,
        )
        Path(spec.runtime_home).mkdir(parents=True, exist_ok=True)
        Path(spec.session_root).mkdir(parents=True, exist_ok=True)
        started = launch_deepseek_harness_supervisor(spec)
        if started.get("started") is not True:
            return {
                "schema": "deepseek_harness_agent_join.v1",
                "ok": False,
                "completed": False,
                "failedStage": "runtimeInitialize",
                "workspaceId": workspace_id,
                "visibleAgentId": visible_agent_id,
                "provider": "deepseek_harness",
                "preflight": preflight,
                "supervisorStart": started,
                "dispatchReady": False,
                "platformRegistrationWritesApplied": False,
                "ownedRuntimeArtifactsMayExist": True,
            }
        existing_agent = self._find_workspace_agent(
            workspace_id=workspace_id,
            agent_id=visible_agent_id,
        )
        if existing_agent is None:
            agent_result = self.create_agent(
                workspace_id=workspace_id,
                agent_id=visible_agent_id,
                name=_optional_text(agent_name) or visible_agent_id,
                description="Beacon-owned DeepSeek Harness managed runtime Agent.",
                metadata={
                    "deepseekHarnessManagedRuntime": {
                        "schema": "deepseek_harness_agent_metadata.v1",
                        "existingSessionImport": session_start_mode == "resume",
                        "continuityScope": "persistent_native_session",
                    }
                },
            )
            agent = agent_result["agent"]
            agent_created = True
        else:
            agent = existing_agent
            agent_created = False
        binding = runtime_handle_metadata(spec)
        if endpoint_to_rebind is not None:
            self.deactivate_agent_endpoint(
                workspace_id=workspace_id,
                endpoint_id=str(endpoint_to_rebind["endpointId"]),
                deactivated_by=created_by,
                reason=(
                    "DeepSeek Harness persistent session rebound to a new runtime "
                    "generation"
                ),
            )
        registered = self.register_deepseek_harness_session_handle(
            workspace_id=workspace_id,
            agent_id=visible_agent_id,
            handle_id=handle_id,
            deepseek_harness_session_id=dsh_session_id,
            cwd=str(resolved_cwd),
            created_by=created_by,
            reason=reason,
            metadata={
                "runtimeBinding": binding,
                **(
                    {"resumedFrom": dict(resumed_from)}
                    if resumed_from is not None
                    else {}
                ),
                "providerBackend": resolve_provider_backend(
                    "deepseek_harness"
                ).to_metadata(),
            },
        )
        handle = registered["deepseekHarnessSessionHandle"]
        endpoint = self.login_agent_endpoint(
            workspace_id=workspace_id,
            agent_id=visible_agent_id,
            alias=alias,
            provider="deepseek_harness",
            provider_handle_id=handle_id,
            direction="send_receive",
            default_reply_policy="source_handle_required",
            contact_policy="open",
            created_by=created_by,
            reason=reason,
            metadata={
                "deepseekHarnessRuntime": {
                    "runtimeId": spec.runtime_id,
                    "generationId": spec.generation_id,
                    "statusAuthority": "owned_live",
                }
            },
        )
        with self._components() as components:
            runtime_audit = components.operations().record_deepseek_harness_runtime_lifecycle(
                workspace_id,
                handle_id=handle_id,
                action="initialized_and_dispatch_ready",
                runtime_state=dict(started["runtimeState"]),
            )
        return {
            "schema": "deepseek_harness_agent_join.v1",
            "ok": True,
            "completed": True,
            "workspaceId": workspace_id,
            "visibleAgentId": visible_agent_id,
            "provider": "deepseek_harness",
            "nativeSessionId": dsh_session_id,
            "primaryEndpointAlias": alias,
            "agent": agent,
            "agentCreated": agent_created,
            "deepseekHarnessSessionHandle": handle,
            "agentEndpoint": endpoint["agentEndpoint"],
            "runtime": dict(started["runtimeState"]),
            "runtimeAudit": runtime_audit,
            "preflight": preflight,
            "providerBackendSelection": resolve_provider_backend(
                "deepseek_harness"
            ).to_metadata(),
            "dispatchReady": True,
            "existingSessionImport": session_start_mode == "resume",
            "sessionStartMode": session_start_mode,
            "sessionSelection": "exact_id" if session_id is not None else "new",
            "databaseScanned": False,
            "reused": False,
            "authenticatedRealModelSmokeRun": False,
        }

    def get_deepseek_harness_runtime_status(
        self,
        *,
        workspace_id: str,
        handle_id: str,
    ) -> Mapping[str, object]:
        handle = self.get_deepseek_harness_session_handle(
            workspace_id=workspace_id,
            handle_id=handle_id,
        )["deepseekHarnessSessionHandle"]
        binding = _deepseek_harness_handle_binding(handle)
        try:
            response = request_deepseek_harness_supervisor(
                state_path=str(binding["runtimeStatePath"]),
                token_path=str(binding["runtimeTokenPath"]),
                method="status",
                workspace_id=workspace_id,
                agent_id=str(handle["agentId"]),
                handle_id=handle_id,
                runtime_id=str(binding["runtimeId"]),
                generation_id=str(binding["generationId"]),
                payload={},
                timeout_seconds=5.0,
            )
        except (OSError, ValueError, DeepSeekHarnessRuntimeError) as exc:
            response = {
                "schema": "deepseek_harness_supervisor_response.v1",
                "ok": False,
                "status": "continuity_lost",
                "failureCategory": "owned_runtime_status_unavailable",
                "failureReason": f"{exc.__class__.__name__}: {exc}",
                "ambiguousDelivery": False,
            }
        handle_transition = None
        runtime_state = response.get("runtimeState")
        cleanly_stopped = (
            isinstance(runtime_state, MappingABC)
            and runtime_state.get("lifecycle") == "stopped"
        )
        continuity_lost = response.get("ok") is not True and not cleanly_stopped
        if continuity_lost and handle.get("state") == "active":
            with self._components() as components:
                handle_transition = components.operations().transition_deepseek_harness_session_handle(
                    workspace_id,
                    handle_id=handle_id,
                    state=DeepSeekHarnessRegisteredSessionHandleState.CONTINUITY_LOST,
                    changed_by="deepseek-harness-owned-status",
                    reason=str(
                        response.get("failureCategory")
                        or "owned_runtime_status_unavailable"
                    ),
                )
        return {
            "schema": "deepseek_harness_runtime_status.v1",
            "provider": "deepseek_harness",
            "handle": handle,
            "statusAuthority": "owned_live",
            "runtimeStatus": response,
            "handleTransition": handle_transition,
            "continuityLost": continuity_lost,
            "resumeRequired": response.get("ok") is not True,
            "resumeAvailable": (
                response.get("ok") is not True
                and response.get("ambiguousDelivery") is not True
            ),
            "requiresRecreate": False,
        }

    def stop_deepseek_harness_runtime(
        self,
        *,
        workspace_id: str,
        handle_id: str,
        acknowledge_continuity_loss: bool = False,
        acknowledge_runtime_stop: bool = False,
        stopped_by: str = "user",
    ) -> Mapping[str, object]:
        if not acknowledge_runtime_stop and not acknowledge_continuity_loss:
            raise ValueError(
                "DeepSeek Harness runtime stop requires explicit runtime-stop acknowledgement."
            )
        handle = self.get_deepseek_harness_session_handle(
            workspace_id=workspace_id,
            handle_id=handle_id,
        )["deepseekHarnessSessionHandle"]
        binding = _deepseek_harness_handle_binding(handle)
        response = request_deepseek_harness_supervisor(
            state_path=str(binding["runtimeStatePath"]),
            token_path=str(binding["runtimeTokenPath"]),
            method="stop",
            workspace_id=workspace_id,
            agent_id=str(handle["agentId"]),
            handle_id=handle_id,
            runtime_id=str(binding["runtimeId"]),
            generation_id=str(binding["generationId"]),
            payload={"acknowledgeRuntimeStop": True},
            timeout_seconds=15.0,
        )
        runtime_state = response.get("runtimeState")
        with self._components() as components:
            if isinstance(runtime_state, MappingABC):
                runtime_audit = components.operations().record_deepseek_harness_runtime_lifecycle(
                    workspace_id,
                    handle_id=handle_id,
                    action="explicit_stop",
                    runtime_state=runtime_state,
                )
            else:
                runtime_audit = None
            continuity_lost = response.get("continuityLost") is True
            transitioned = components.operations().transition_deepseek_harness_session_handle(
                workspace_id,
                handle_id=handle_id,
                state=(
                    DeepSeekHarnessRegisteredSessionHandleState.CONTINUITY_LOST
                    if continuity_lost
                    else DeepSeekHarnessRegisteredSessionHandleState.INACTIVE
                ),
                changed_by=stopped_by,
                reason=(
                    "active_operation_forced_termination"
                    if continuity_lost
                    else "clean_runtime_stop_resumable"
                ),
            )
        return {
            "schema": "deepseek_harness_runtime_stop.v1",
            "ok": response.get("ok") is True,
            "continuityLost": response.get("continuityLost") is True,
            "resumeRequired": response.get("ok") is True,
            "resumeAvailable": response.get("resumeAvailable") is True,
            "requiresRecreate": False,
            "supervisorResponse": response,
            "handleTransition": transitioned,
            "runtimeAudit": runtime_audit,
        }

    def resume_deepseek_harness_runtime(
        self,
        *,
        workspace_id: str,
        handle_id: str,
        acknowledge_ambiguous_delivery: bool = False,
        resumed_by: str = "user",
    ) -> Mapping[str, object]:
        """Start a new runtime generation on the same persisted native session."""

        old_handle = self.get_deepseek_harness_session_handle(
            workspace_id=workspace_id,
            handle_id=handle_id,
        )["deepseekHarnessSessionHandle"]
        if old_handle.get("state") == "active":
            status = self.get_deepseek_harness_runtime_status(
                workspace_id=workspace_id,
                handle_id=handle_id,
            )
            runtime_status = status.get("runtimeStatus")
            if isinstance(runtime_status, MappingABC) and runtime_status.get("ok") is True:
                return {
                    "schema": "deepseek_harness_runtime_resume.v1",
                    "ok": True,
                    "resumed": False,
                    "reusedLiveRuntime": True,
                    "oldHandle": old_handle,
                    "newHandle": old_handle,
                    "nativeSessionId": old_handle["deepseekHarnessSessionId"],
                    "runtime": runtime_status.get("runtimeState"),
                }
            old_handle = self.get_deepseek_harness_session_handle(
                workspace_id=workspace_id,
                handle_id=handle_id,
            )["deepseekHarnessSessionHandle"]
        old_binding = _deepseek_harness_handle_binding(old_handle)
        old_state = read_runtime_state(str(old_binding["runtimeStatePath"]))
        ambiguous_delivery = old_state.get("ambiguousDelivery") is True
        if ambiguous_delivery and not acknowledge_ambiguous_delivery:
            raise ValueError(
                "the previous DSH generation ended with ambiguous delivery; pass "
                "--acknowledge-ambiguous-delivery to resume without replaying it, or "
                "choose explicit recreate for a new session."
            )
        raw_spec = json.loads(
            Path(str(old_binding["runtimeSpecPath"])).read_text(encoding="utf-8")
        )
        if not isinstance(raw_spec, MappingABC):
            raise ValueError("old DeepSeek Harness runtime spec is invalid.")
        old_spec = DeepSeekHarnessRuntimeSpec.from_mapping(raw_spec)
        joined = self.join_deepseek_harness_agent(
            workspace_id=workspace_id,
            agent_id=str(old_handle["agentId"]),
            agent_name=None,
            cwd=old_spec.cwd,
            carrier=old_spec.carrier,
            executable_path=old_spec.executable_path,
            package_root=old_spec.package_root,
            cordis_config_path=old_spec.cordis_config_path,
            runtime_home=old_spec.runtime_home,
            runtime_home_source=old_spec.runtime_home_source,
            state_root=str(Path(old_spec.paths.state_directory).parent),
            session_root=old_spec.session_root,
            session_id=old_spec.dsh_session_id,
            session_compression=old_spec.session_compression,
            model_provider=old_spec.model_provider,
            model=old_spec.model,
            reply_writeback_mode=old_spec.reply_writeback_mode,
            created_by=resumed_by,
            reason="resume persistent DeepSeek Harness session",
            initialize_timeout_seconds=old_spec.initialize_timeout_seconds,
            operation_timeout_seconds=old_spec.operation_timeout_seconds,
            shutdown_timeout_seconds=old_spec.shutdown_timeout_seconds,
            max_line_bytes=old_spec.max_line_bytes,
            max_total_output_bytes=old_spec.max_total_output_bytes,
            max_stderr_bytes=old_spec.max_stderr_bytes,
            resumed_from={
                "handleId": handle_id,
                "runtimeId": old_binding["runtimeId"],
                "generationId": old_binding["generationId"],
                "deepseekHarnessSessionId": old_spec.dsh_session_id,
                "ambiguousDeliveryAcknowledged": ambiguous_delivery,
            },
        )
        return {
            "schema": "deepseek_harness_runtime_resume.v1",
            "ok": joined.get("ok") is True,
            "resumed": joined.get("ok") is True,
            "reusedLiveRuntime": False,
            "oldHandle": old_handle,
            "newHandle": joined.get("deepseekHarnessSessionHandle"),
            "nativeSessionId": old_spec.dsh_session_id,
            "sameNativeSessionId": (
                joined.get("nativeSessionId") == old_spec.dsh_session_id
            ),
            "newRuntime": joined.get("runtime"),
            "join": joined,
            "ambiguousDeliveryAcknowledged": ambiguous_delivery,
            "requestReplayAttempted": False,
        }

    def recreate_deepseek_harness_runtime(
        self,
        *,
        workspace_id: str,
        handle_id: str,
        acknowledge_continuity_loss: bool,
        recreated_by: str = "user",
    ) -> Mapping[str, object]:
        if not acknowledge_continuity_loss:
            raise ValueError(
                "DeepSeek Harness recreate requires explicit continuity-loss acknowledgement."
            )
        old_handle = self.get_deepseek_harness_session_handle(
            workspace_id=workspace_id,
            handle_id=handle_id,
        )["deepseekHarnessSessionHandle"]
        old_binding = _deepseek_harness_handle_binding(old_handle)
        raw_spec = json.loads(
            Path(str(old_binding["runtimeSpecPath"])).read_text(encoding="utf-8")
        )
        if not isinstance(raw_spec, MappingABC):
            raise ValueError("old DeepSeek Harness runtime spec is invalid.")
        old_spec = DeepSeekHarnessRuntimeSpec.from_mapping(raw_spec)
        if old_handle.get("state") == "active":
            self.stop_deepseek_harness_runtime(
                workspace_id=workspace_id,
                handle_id=handle_id,
                acknowledge_continuity_loss=True,
                stopped_by=recreated_by,
            )
        endpoint = next(
            (
                item
                for item in self.list_agent_endpoints(
                    workspace_id=workspace_id,
                    include_inactive=False,
                )["agentEndpoints"]
                if item.get("providerHandleId") == handle_id
            ),
            None,
        )
        if endpoint is None:
            raise ValueError("DeepSeek Harness endpoint for old handle was not found.")
        self.deactivate_agent_endpoint(
            workspace_id=workspace_id,
            endpoint_id=str(endpoint["endpointId"]),
            deactivated_by=recreated_by,
            reason="DeepSeek Harness runtime/session recreated",
        )

        new_handle_id = f"deepseek-harness-handle-{uuid4()}"
        new_session_id = f"beacon-dsh-session-{uuid4()}"
        new_spec = build_deepseek_harness_runtime_spec(
            workspace_id=workspace_id,
            agent_id=str(old_handle["agentId"]),
            handle_id=new_handle_id,
            dsh_session_id=new_session_id,
            cwd=old_spec.cwd,
            session_root=str(Path(old_spec.session_root).parent / new_session_id),
            runtime_home=old_spec.runtime_home,
            runtime_home_source=old_spec.runtime_home_source,
            carrier=old_spec.carrier,
            executable_path=old_spec.executable_path,
            launch_args=old_spec.launch_args,
            cordis_config_path=old_spec.cordis_config_path,
            package_root=old_spec.package_root,
            package_version=old_spec.package_version,
            expected_server_version=old_spec.expected_server_version,
            model_provider=old_spec.model_provider,
            model=old_spec.model,
            state_root=str(Path(old_spec.paths.state_directory).parent),
            session_start_mode="create",
            session_compression=old_spec.session_compression,
            reply_writeback_mode=old_spec.reply_writeback_mode,
            initialize_timeout_seconds=old_spec.initialize_timeout_seconds,
            operation_timeout_seconds=old_spec.operation_timeout_seconds,
            shutdown_timeout_seconds=old_spec.shutdown_timeout_seconds,
            max_line_bytes=old_spec.max_line_bytes,
            max_total_output_bytes=old_spec.max_total_output_bytes,
            max_stderr_bytes=old_spec.max_stderr_bytes,
        )
        started = launch_deepseek_harness_supervisor(new_spec)
        if started.get("started") is not True:
            return {
                "schema": "deepseek_harness_runtime_recreate.v1",
                "ok": False,
                "oldHandle": old_handle,
                "oldSessionTerminal": True,
                "newSessionId": new_session_id,
                "newRuntimeStarted": False,
                "supervisorStart": started,
            }
        registered = self.register_deepseek_harness_session_handle(
            workspace_id=workspace_id,
            agent_id=str(old_handle["agentId"]),
            handle_id=new_handle_id,
            deepseek_harness_session_id=new_session_id,
            cwd=old_spec.cwd,
            created_by=recreated_by,
            reason="explicit DeepSeek Harness runtime/session recreate",
            metadata={
                "runtimeBinding": runtime_handle_metadata(new_spec),
                "recreatedFrom": {
                    "handleId": handle_id,
                    "deepseekHarnessSessionId": old_handle.get(
                        "deepseekHarnessSessionId"
                    ),
                    "runtimeId": old_binding["runtimeId"],
                    "generationId": old_binding["generationId"],
                },
                "providerBackend": resolve_provider_backend(
                    "deepseek_harness"
                ).to_metadata(),
            },
        )
        new_endpoint = self.login_agent_endpoint(
            workspace_id=workspace_id,
            agent_id=str(old_handle["agentId"]),
            alias=str(endpoint["alias"]),
            provider="deepseek_harness",
            provider_handle_id=new_handle_id,
            direction=str(endpoint["direction"]),
            default_reply_policy=str(endpoint["defaultReplyPolicy"]),
            contact_policy=str(endpoint["contactPolicy"]),
            created_by=recreated_by,
            reason="DeepSeek Harness runtime/session recreated",
        )
        with self._components() as components:
            audit = components.operations().record_deepseek_harness_runtime_lifecycle(
                workspace_id,
                handle_id=new_handle_id,
                action="recreated_new_session",
                runtime_state=dict(started["runtimeState"]),
            )
        return {
            "schema": "deepseek_harness_runtime_recreate.v1",
            "ok": True,
            "oldHandle": old_handle,
            "oldSessionTerminal": True,
            "newHandle": registered["deepseekHarnessSessionHandle"],
            "newEndpoint": new_endpoint["agentEndpoint"],
            "oldSessionIdReused": False,
            "newSessionId": new_session_id,
            "newRuntime": started["runtimeState"],
            "runtimeAudit": audit,
        }

    def _agent_provider_onboard_binding_conflict(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        provider: str,
        session_id: str,
        endpoint_alias: str,
        handle_id: str | None,
        endpoint_id: str | None,
        direction: str,
        default_reply_policy: str,
        contact_policy: str,
        allow_shared_session_binding: bool = False,
    ) -> Mapping[str, object] | None:
        handles = _provider_session_handles(
            self,
            workspace_id=workspace_id,
            provider=provider,
            agent_id=None,
        )
        session_field = _provider_session_id_field(provider)
        handles_by_id = {
            str(item.get("handleId")): item
            for item in handles
            if item.get("handleId") is not None
        }
        existing_session_handle = next(
            (
                item
                for item in handles
                if item.get(session_field) == session_id
                and item.get("state", "active") == "active"
            ),
            None,
        )
        if (
            existing_session_handle is not None
            and existing_session_handle.get("agentId") != agent_id
            and not allow_shared_session_binding
        ):
            return {
                "message": (
                    "provider native session is already joined by another visible "
                    "Agent; ordinary agent-join does not share active sessions."
                ),
                "providerHandle": existing_session_handle,
                "existingVisibleAgentId": existing_session_handle.get("agentId"),
                "writesApplied": False,
            }
        if handle_id is not None and handle_id in handles_by_id:
            existing_handle = handles_by_id[handle_id]
            if not _provider_handle_matches(
                existing_handle,
                agent_id=agent_id,
                session_field=session_field,
                session_id=session_id,
            ):
                return {
                    "message": "provider session handle id is already bound differently.",
                    "providerHandle": existing_handle,
                    "writesApplied": False,
                }

        endpoints = self.list_agent_endpoints(
            workspace_id=workspace_id,
            include_inactive=False,
        )["agentEndpoints"]
        existing_by_id = next(
            (
                item
                for item in endpoints
                if endpoint_id is not None and item.get("endpointId") == endpoint_id
            ),
            None,
        )
        if existing_by_id is not None and existing_by_id.get("alias") != endpoint_alias:
            return {
                "message": "agent endpoint id is already bound differently.",
                "agentEndpoint": existing_by_id,
                "writesApplied": False,
            }
        existing_alias = next(
            (item for item in endpoints if item.get("alias") == endpoint_alias),
            None,
        )
        if existing_alias is None:
            return None
        existing_handle = handles_by_id.get(str(existing_alias.get("providerHandleId")))
        expected = {
            "agentId": agent_id,
            "provider": provider,
            "direction": direction,
            "defaultReplyPolicy": default_reply_policy,
            "contactPolicy": contact_policy,
        }
        mismatches = {
            key: {"expected": value, "actual": existing_alias.get(key)}
            for key, value in expected.items()
            if existing_alias.get(key) != value
        }
        if existing_handle is None or not _provider_handle_matches(
            existing_handle,
            agent_id=agent_id,
            session_field=session_field,
            session_id=session_id,
        ):
            mismatches["nativeSessionId"] = {
                "expected": session_id,
                "actual": (
                    existing_handle.get(session_field)
                    if existing_handle is not None
                    else None
                ),
            }
        if mismatches:
            return {
                "message": "endpoint alias is already active with different binding.",
                "agentEndpoint": existing_alias,
                "providerHandle": existing_handle,
                "mismatches": mismatches,
                "writesApplied": False,
            }
        return None

    def login_agent_endpoint(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        alias: str,
        provider: str,
        provider_handle_id: str,
        endpoint_id: str | None = None,
        direction: str = "send_receive",
        default_reply_policy: str = "source_handle_required",
        contact_policy: str = "open",
        created_by: str = "user",
        reason: str = "endpoint login",
        metadata: Mapping[str, object] | None = None,
        allow_source_endpoint_aliases: Sequence[str] = (),
        allow_source_agent_ids: Sequence[str] = (),
        allow_source_handle_ids: Sequence[str] = (),
        block_source_endpoint_aliases: Sequence[str] = (),
        block_source_agent_ids: Sequence[str] = (),
        block_source_handle_ids: Sequence[str] = (),
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().login_agent_endpoint(
                workspace_id,
                agent_id=agent_id,
                endpoint_id=endpoint_id,
                alias=alias,
                provider=provider,
                provider_handle_id=provider_handle_id,
                direction=direction,
                default_reply_policy=default_reply_policy,
                contact_policy=contact_policy,
                created_by=created_by,
                reason=reason,
                metadata=_agent_endpoint_login_metadata(
                    metadata,
                    allow_source_endpoint_aliases=allow_source_endpoint_aliases,
                    allow_source_agent_ids=allow_source_agent_ids,
                    allow_source_handle_ids=allow_source_handle_ids,
                    block_source_endpoint_aliases=block_source_endpoint_aliases,
                    block_source_agent_ids=block_source_agent_ids,
                    block_source_handle_ids=block_source_handle_ids,
                ),
            )

    def _find_workspace_agent(
        self,
        *,
        workspace_id: str,
        agent_id: str,
    ) -> Mapping[str, object] | None:
        with self._components() as components:
            agents = components.operations().list_agent_registrations(
                workspace_id
            )["agents"]
        for agent in agents:
            if isinstance(agent, MappingABC) and agent.get("agentId") == agent_id:
                return dict(agent)
        return None

    def _onboard_provider_handle(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        provider: str,
        session_id: str,
        selected_record: Mapping[str, object],
        handle_id: str | None,
        created_by: str,
        reason: str,
        metadata: Mapping[str, object] | None,
        reuse_existing: bool,
        dry_run: bool,
    ) -> Mapping[str, object]:
        handles = _provider_session_handles(
            self,
            workspace_id=workspace_id,
            provider=provider,
            agent_id=None,
        )
        session_field = _provider_session_id_field(provider)
        exact_handle = (
            next(
                (
                    handle
                    for handle in handles
                    if handle.get("handleId") == handle_id
                ),
                None,
            )
            if handle_id is not None
            else None
        )
        if exact_handle is not None:
            if _provider_handle_matches(
                exact_handle,
                agent_id=agent_id,
                session_field=session_field,
                session_id=session_id,
            ):
                if not reuse_existing:
                    return {
                        "ok": False,
                        "message": (
                            "provider session handle already exists and "
                            "--no-reuse-existing was set."
                        ),
                        "conflict": {"providerHandle": exact_handle},
                        "stage": {
                            "stage": "providerSessionHandle",
                            "status": "conflict",
                            "providerHandle": exact_handle,
                        },
                    }
                return {
                    "ok": True,
                    "providerHandle": exact_handle,
                    "stage": {
                        "stage": "providerSessionHandle",
                        "status": "reused",
                        "providerHandle": exact_handle,
                    },
                }
            return {
                "ok": False,
                "message": "provider session handle id is already bound differently.",
                "conflict": {"providerHandle": exact_handle},
                "stage": {
                    "stage": "providerSessionHandle",
                    "status": "conflict",
                    "providerHandle": exact_handle,
                },
            }
        matching = [
            handle
            for handle in handles
            if _provider_handle_matches(
                handle,
                agent_id=agent_id,
                session_field=session_field,
                session_id=session_id,
            )
        ]
        if matching and reuse_existing:
            reused = sorted(matching, key=lambda item: str(item["handleId"]))[0]
            return {
                "ok": True,
                "providerHandle": reused,
                "stage": {
                    "stage": "providerSessionHandle",
                    "status": "reused",
                    "providerHandle": reused,
                },
            }
        if dry_run:
            planned = {
                "schema": f"{provider}_session_handle.v1",
                "workspaceId": workspace_id,
                "agentId": agent_id,
                "handleId": handle_id or "<generated>",
                session_field: session_id,
                "cwd": selected_record.get("cwd"),
                "sourcePath": selected_record.get("sourcePath"),
                "state": "active",
            }
            return {
                "ok": True,
                "providerHandle": planned,
                "stage": {
                    "stage": "providerSessionHandle",
                    "status": "would_register",
                    "providerHandle": planned,
                },
            }
        registered = self._register_discovered_agent_session_record(
            workspace_id=workspace_id,
            agent_id=agent_id,
            record=selected_record,
            handle_id=handle_id,
            created_by=created_by,
            reason=reason,
            metadata={
                **dict(metadata or {}),
                "agentProviderOnboard": {
                    "schema": "agent_provider_onboard_metadata.v1",
                    "stage": "providerSessionHandle",
                },
            },
        )
        provider_handle = _registered_provider_handle_metadata(
            registered,
            provider,
        )
        return {
            "ok": True,
            "providerHandle": provider_handle,
            "stage": {
                "stage": "providerSessionHandle",
                "status": "registered",
                "providerHandle": provider_handle,
                "sourceEventSequence": registered.get("sourceEventSequence"),
            },
        }

    def _onboard_agent_endpoint(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        alias: str,
        provider: str,
        provider_handle_id: str,
        endpoint_id: str | None,
        direction: str,
        default_reply_policy: str,
        contact_policy: str,
        created_by: str,
        reason: str,
        metadata: Mapping[str, object] | None,
        allow_source_endpoint_aliases: Sequence[str],
        allow_source_agent_ids: Sequence[str],
        allow_source_handle_ids: Sequence[str],
        block_source_endpoint_aliases: Sequence[str],
        block_source_agent_ids: Sequence[str],
        block_source_handle_ids: Sequence[str],
        reuse_existing: bool,
        dry_run: bool,
    ) -> Mapping[str, object]:
        existing = next(
            (
                endpoint
                for endpoint in self.list_agent_endpoints(
                    workspace_id=workspace_id,
                    include_inactive=False,
                )["agentEndpoints"]
                if endpoint.get("alias") == alias
            ),
            None,
        )
        expected = {
            "agentId": agent_id,
            "provider": provider,
            "providerHandleId": provider_handle_id,
            "direction": direction,
            "defaultReplyPolicy": default_reply_policy,
            "contactPolicy": contact_policy,
        }
        if existing is not None:
            mismatches = {
                key: {
                    "expected": value,
                    "actual": existing.get(key),
                }
                for key, value in expected.items()
                if existing.get(key) != value
            }
            if not mismatches and reuse_existing:
                return {
                    "ok": True,
                    "agentEndpoint": existing,
                    "stage": {
                        "stage": "endpointLogin",
                        "status": "reused",
                        "agentEndpoint": existing,
                    },
                }
            return {
                "ok": False,
                "message": "endpoint alias is already active with different binding.",
                "conflict": {
                    "agentEndpoint": existing,
                    "mismatches": mismatches,
                },
                "stage": {
                    "stage": "endpointLogin",
                    "status": "conflict",
                    "agentEndpoint": existing,
                    "mismatches": mismatches,
                },
            }
        if dry_run:
            planned = {
                "schema": "agent_endpoint.v1",
                "workspaceId": workspace_id,
                "endpointId": endpoint_id or "<generated>",
                "alias": alias,
                **expected,
                "state": "active",
            }
            return {
                "ok": True,
                "agentEndpoint": planned,
                "stage": {
                    "stage": "endpointLogin",
                    "status": "would_login",
                    "agentEndpoint": planned,
                },
            }
        endpoint = self.login_agent_endpoint(
            workspace_id=workspace_id,
            agent_id=agent_id,
            endpoint_id=endpoint_id,
            alias=alias,
            provider=provider,
            provider_handle_id=provider_handle_id,
            direction=direction,
            default_reply_policy=default_reply_policy,
            contact_policy=contact_policy,
            created_by=created_by,
            reason=reason,
            metadata={
                **dict(metadata or {}),
                "agentProviderOnboard": {
                    "schema": "agent_provider_onboard_metadata.v1",
                    "stage": "endpointLogin",
                },
            },
            allow_source_endpoint_aliases=allow_source_endpoint_aliases,
            allow_source_agent_ids=allow_source_agent_ids,
            allow_source_handle_ids=allow_source_handle_ids,
            block_source_endpoint_aliases=block_source_endpoint_aliases,
            block_source_agent_ids=block_source_agent_ids,
            block_source_handle_ids=block_source_handle_ids,
        )
        return {
            "ok": True,
            "agentEndpoint": endpoint["agentEndpoint"],
            "stage": {
                "stage": "endpointLogin",
                "status": "logged_in",
                "agentEndpoint": endpoint["agentEndpoint"],
                "sourceEventSequence": endpoint.get("sourceEventSequence"),
            },
        }

    def list_agent_endpoints(
        self,
        *,
        workspace_id: str,
        agent_id: str | None = None,
        provider: str | None = None,
        include_inactive: bool = False,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().list_agent_endpoints(
                workspace_id,
                agent_id=agent_id,
                provider=provider,
                include_inactive=include_inactive,
            )

    def get_agent_endpoint(
        self,
        *,
        workspace_id: str,
        endpoint_id: str | None = None,
        alias: str | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_agent_endpoint(
                workspace_id,
                endpoint_id=endpoint_id,
                alias=alias,
            )

    def get_agent_endpoint_status(
        self,
        *,
        workspace_id: str,
        endpoint_id: str | None = None,
        alias: str | None = None,
        limit: int = 20,
        read_live_runtime_status: bool | str = "auto",
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_agent_endpoint_status(
                workspace_id,
                endpoint_id=endpoint_id,
                alias=alias,
                limit=limit,
                read_live_runtime_status=read_live_runtime_status,
            )

    def get_agent_provider_runtime_status(
        self,
        *,
        workspace_id: str,
        provider: str | None = None,
        provider_handle_id: str | None = None,
        endpoint_id: str | None = None,
        alias: str | None = None,
        read_live_runtime_status: bool | str = "auto",
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_agent_provider_runtime_status(
                workspace_id,
                provider=provider,
                provider_handle_id=provider_handle_id,
                endpoint_id=endpoint_id,
                alias=alias,
                read_live_runtime_status=read_live_runtime_status,
            )

    def join_provider_session_workspace(
        self,
        *,
        workspace_id: str,
        provider_session_profile: Mapping[str, object],
        agent_id: str,
        agent_name: str,
        endpoint_alias: str,
        description: str = "Beacon provider endpoint agent.",
        direction: str = "send_receive",
        default_reply_policy: str = "source_handle_required",
        contact_policy: str = "open",
        handle_id: str | None = None,
        endpoint_id: str | None = None,
        created_by: str = "user",
        reason: str = "provider session workspace join",
        metadata: Mapping[str, object] | None = None,
        reuse_existing: bool = True,
    ) -> Mapping[str, object]:
        normalized_provider = normalize_agent_endpoint_provider(
            str(provider_session_profile.get("provider", ""))
        )
        if normalized_provider is None:
            raise ValueError("provider session profile provider is invalid.")
        if provider_session_profile.get("state") != "active":
            raise ValueError("provider session profile is not active.")
        normalized_direction = _onboard_endpoint_direction(direction)
        normalized_reply_policy = _onboard_reply_policy(default_reply_policy)
        normalized_alias = normalize_agent_endpoint_alias(endpoint_alias)
        profile_ref = _provider_session_workspace_join_metadata(
            provider_session_profile,
            membership_id=None,
        )
        stages: list[Mapping[str, object]] = [
            {
                "stage": "providerSessionProfile",
                "status": "selected",
                "providerSessionProfile": _provider_session_profile_summary(
                    provider_session_profile
                ),
            }
        ]
        existing_agent = self._find_workspace_agent(
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        if existing_agent is not None:
            agent_stage = {
                "stage": "agentIdentity",
                "status": "reused",
                "agent": existing_agent,
            }
        else:
            try:
                created_agent = self.create_agent(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    name=agent_name,
                    description=description,
                    metadata={
                        **dict(metadata or {}),
                        "providerSessionWorkspaceJoin": profile_ref,
                    },
                )
            except ValueError as exc:
                return _provider_session_workspace_join_failure(
                    settings=self.settings,
                    workspace_id=workspace_id,
                    provider_session_profile=provider_session_profile,
                    failed_stage="agentIdentity",
                    stages=stages,
                    message=str(exc),
                )
            agent_stage = {
                "stage": "agentIdentity",
                "status": "created",
                "agent": created_agent["agent"],
            }
        stages.append(agent_stage)

        selected_record = synthetic_discovered_session_from_profile(
            provider_session_profile
        )
        handle_result = self._onboard_provider_handle(
            workspace_id=workspace_id,
            agent_id=agent_id,
            provider=normalized_provider,
            session_id=str(provider_session_profile["providerSessionId"]),
            selected_record=selected_record,
            handle_id=handle_id,
            created_by=created_by,
            reason=reason,
            metadata={
                **dict(metadata or {}),
                "providerSessionWorkspaceJoin": profile_ref,
            },
            reuse_existing=reuse_existing,
            dry_run=False,
        )
        stages.append(handle_result["stage"])
        if not handle_result["ok"]:
            return _provider_session_workspace_join_failure(
                settings=self.settings,
                workspace_id=workspace_id,
                provider_session_profile=provider_session_profile,
                failed_stage="providerSessionHandle",
                stages=stages,
                message=str(handle_result["message"]),
                conflict=handle_result.get("conflict"),
            )
        provider_handle = handle_result["providerHandle"]
        provider_handle_id = str(provider_handle["handleId"])

        endpoint_result = self._onboard_agent_endpoint(
            workspace_id=workspace_id,
            agent_id=agent_id,
            alias=normalized_alias,
            provider=normalized_provider,
            provider_handle_id=provider_handle_id,
            endpoint_id=endpoint_id,
            direction=normalized_direction,
            default_reply_policy=normalized_reply_policy,
            contact_policy=contact_policy,
            created_by=created_by,
            reason=reason,
            metadata={
                **dict(metadata or {}),
                "providerSessionWorkspaceJoin": profile_ref,
            },
            allow_source_endpoint_aliases=(),
            allow_source_agent_ids=(),
            allow_source_handle_ids=(),
            block_source_endpoint_aliases=(),
            block_source_agent_ids=(),
            block_source_handle_ids=(),
            reuse_existing=reuse_existing,
            dry_run=False,
        )
        stages.append(endpoint_result["stage"])
        if not endpoint_result["ok"]:
            return _provider_session_workspace_join_failure(
                settings=self.settings,
                workspace_id=workspace_id,
                provider_session_profile=provider_session_profile,
                failed_stage="endpointLogin",
                stages=stages,
                message=str(endpoint_result["message"]),
                conflict=endpoint_result.get("conflict"),
            )
        endpoint = endpoint_result["agentEndpoint"]
        endpoint_readiness = _provider_session_workspace_endpoint_readiness(
            endpoint,
            provider_handle,
        )
        return {
            "schema": "provider_session_workspace_join.v1",
            "ok": True,
            "completed": True,
            "workspaceId": workspace_id,
            "profileId": provider_session_profile.get("profileId"),
            "providerSessionProfile": _provider_session_profile_summary(
                provider_session_profile
            ),
            "stages": stages,
            "agent": agent_stage["agent"],
            "providerHandle": provider_handle,
            "agentEndpoint": endpoint,
            "endpointReadiness": endpoint_readiness,
            "activationPolicy": {
                "schema": "provider_session_workspace_activation_policy.v1",
                "policy": MANUAL_ONLY_ACTIVATION_POLICY,
                "crossWorkspaceLeaseGuardImplemented": False,
                "automaticWorkerActivationAllowed": False,
                "warning": (
                    "This membership records a reusable local provider session, "
                    "but worker/daemon automatic activation is disabled until a "
                    "cross-workspace provider-session lease exists."
                ),
            },
            **_agent_provider_onboard_next_commands(
                self.settings,
                workspace_id=workspace_id,
                endpoint_alias=normalized_alias,
            ),
            "boundaries": _provider_session_workspace_join_boundaries(),
        }

    def get_agent_onboarding_status(
        self,
        *,
        workspace_id: str,
        agent_id: str | None = None,
        endpoint_alias: str | None = None,
        provider: str | None = None,
        native_session_id: str | None = None,
        read_live_runtime_status: bool | str = "auto",
    ) -> Mapping[str, object]:
        normalized_provider = normalize_agent_endpoint_provider(provider)
        if provider is not None and normalized_provider is None:
            raise ValueError("provider must be one of: claude, codex, hermes, deepseek_harness.")
        if native_session_id is not None and normalized_provider is None:
            raise ValueError("--native-session-id requires --provider; native IDs are provider-scoped.")
        normalized_alias = (
            normalize_agent_endpoint_alias(endpoint_alias)
            if endpoint_alias is not None
            else None
        )
        filters = {
            "agentId": agent_id,
            "endpointAlias": normalized_alias,
            "provider": normalized_provider,
            "nativeSessionId": native_session_id,
        }
        registry_resolution = _provider_session_registry_resolution_from_settings(
            self.settings
        )
        with self._components() as components:
            operations = components.operations()
            workspace = operations.get_workspace(workspace_id)["workspace"]
            if workspace is None:
                return _agent_onboarding_status_payload(
                    settings=self.settings,
                    workspace_id=workspace_id,
                    workspace=None,
                    agents=[],
                    provider_handles=[],
                    endpoints=[],
                    dispatcher_status=None,
                    provider_session_memberships=[],
                    provider_session_registry_resolution=registry_resolution,
                    filters=filters,
                    read_live_runtime_status=read_live_runtime_status,
                )
            agents = [
                _agent_onboarding_agent_item(agent)
                for agent in operations.list_agent_registrations(workspace_id)[
                    "agents"
                ]
                if _agent_matches_onboarding_filters(agent, agent_id=agent_id)
            ]
            all_provider_handles = _agent_onboarding_provider_handles(
                operations,
                workspace_id=workspace_id,
                agent_id=None,
                provider=None,
            )
            provider_handles = [
                handle
                for handle in all_provider_handles
                if _provider_handle_matches_onboarding_filters(
                    handle,
                    agent_id=agent_id,
                    provider=normalized_provider,
                )
            ]
            endpoints = _agent_onboarding_endpoints(
                operations.list_agent_endpoints(
                    workspace_id,
                    include_inactive=True,
                )["agentEndpoints"],
                provider_handles=all_provider_handles,
                agent_id=agent_id,
                endpoint_alias=normalized_alias,
                provider=normalized_provider,
            )
            if normalized_alias is not None and (endpoints or agent_id is None):
                alias_handles = {
                    (endpoint["provider"], endpoint["providerHandleId"])
                    for endpoint in endpoints
                }
                provider_handles = [
                    handle for handle in provider_handles
                    if (handle["provider"], handle["handleId"]) in alias_handles
                ]
            if native_session_id is not None:
                provider_handles = [
                    handle for handle in provider_handles
                    if handle["session"]["id"] == native_session_id
                ]
                matching_handles = {(h["provider"], h["handleId"]) for h in provider_handles}
                endpoints = [e for e in endpoints
                             if (e["provider"], e["providerHandleId"]) in matching_handles]
            if agent_id is None and (normalized_alias is not None or native_session_id is not None or normalized_provider is not None):
                matching_agents = {h["agentId"] for h in provider_handles}
                agents = [a for a in agents if a["agentId"] in matching_agents]
            dispatcher_status = operations.get_agent_dispatch_daemon_status(
                workspace_id
            )
            provider_session_memberships = ProviderSessionRegistry(
                registry_resolution.registry_path
            ).list_memberships(
                workspace_id=workspace_id,
                include_inactive=True,
            )["memberships"]
        return _agent_onboarding_status_payload(
            settings=self.settings,
            workspace_id=workspace_id,
            workspace=workspace,
            agents=agents,
            provider_handles=provider_handles,
            endpoints=endpoints,
            dispatcher_status=dispatcher_status,
            provider_session_memberships=provider_session_memberships,
            provider_session_registry_resolution=registry_resolution,
            filters=filters,
            read_live_runtime_status=read_live_runtime_status,
        )

    def deactivate_agent_endpoint(
        self,
        *,
        workspace_id: str,
        endpoint_id: str | None = None,
        alias: str | None = None,
        deactivated_by: str,
        reason: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().deactivate_agent_endpoint(
                workspace_id,
                endpoint_id=endpoint_id,
                alias=alias,
                deactivated_by=deactivated_by,
                reason=reason,
            )

    def register_claude_session_handle(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        claude_session_uuid: str,
        cwd: str,
        created_by: str,
        reason: str,
        handle_id: str | None = None,
        source_path: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().register_claude_session_handle(
                workspace_id,
                agent_id=agent_id,
                handle_id=handle_id,
                claude_session_uuid=claude_session_uuid,
                cwd=cwd,
                source_path=source_path,
                created_by=created_by,
                reason=reason,
                metadata=metadata,
            )

    def list_claude_session_handles(
        self,
        *,
        workspace_id: str,
        agent_id: str | None = None,
        include_inactive: bool = False,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().list_claude_session_handles(
                workspace_id,
                agent_id=agent_id,
                include_inactive=include_inactive,
            )

    def get_claude_session_handle(
        self,
        *,
        workspace_id: str,
        handle_id: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_claude_session_handle(
                workspace_id,
                handle_id=handle_id,
            )

    def deactivate_claude_session_handle(
        self,
        *,
        workspace_id: str,
        handle_id: str,
        deactivated_by: str,
        reason: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().deactivate_claude_session_handle(
                workspace_id,
                handle_id=handle_id,
                deactivated_by=deactivated_by,
                reason=reason,
            )

    def activate_claude_registered_session(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        handle_id: str,
        exchange_request_id: str,
        handoff_directory: str | None = None,
        claude_executable: str = "claude",
        platform_workspace_root: str | None = None,
        default_platform_workspace_add_dir: bool = True,
        add_dirs: tuple[str, ...] = (),
        allowed_tools: tuple[str, ...] = (),
        permission_mode: str | None = None,
        settings_path: str | None = None,
        activation_backend: str = "cli",
        reply_writeback_mode: str | None = None,
        dry_run: bool = True,
        timeout_seconds: int = 120,
    ) -> Mapping[str, object]:
        with self._components() as components:
            result = components.operations().activate_claude_registered_session(
                workspace_id,
                agent_id=agent_id,
                handle_id=handle_id,
                exchange_request_id=exchange_request_id,
                database_path=self.settings.database,
                workspace_root=self.settings.workspace_root,
                plugins_directory=self.settings.plugins_directory,
                handoff_directory=handoff_directory,
                claude_executable=claude_executable,
                platform_workspace_root=platform_workspace_root,
                default_platform_workspace_add_dir=default_platform_workspace_add_dir,
                add_dirs=add_dirs,
                allowed_tools=allowed_tools,
                permission_mode=permission_mode,
                settings_path=settings_path,
                activation_backend=activation_backend,
                reply_writeback_mode=reply_writeback_mode,
                dry_run=dry_run,
                timeout_seconds=timeout_seconds,
            )
            selection = resolve_provider_backend(
                "claude",
                claude_activation_backend=activation_backend,
                source=(
                    "provider_default"
                    if activation_backend == "cli"
                    else "resolved_claude_control"
                ),
            )
            return {
                **dict(result),
                "providerBackendSelection": selection.to_metadata(),
            }

    def register_codex_session_handle(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        codex_session_id: str,
        cwd: str,
        created_by: str,
        reason: str,
        handle_id: str | None = None,
        source_path: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().register_codex_session_handle(
                workspace_id,
                agent_id=agent_id,
                handle_id=handle_id,
                codex_session_id=codex_session_id,
                cwd=cwd,
                source_path=source_path,
                created_by=created_by,
                reason=reason,
                metadata=metadata,
            )

    def list_codex_session_handles(
        self,
        *,
        workspace_id: str,
        agent_id: str | None = None,
        include_inactive: bool = False,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().list_codex_session_handles(
                workspace_id,
                agent_id=agent_id,
                include_inactive=include_inactive,
            )

    def get_codex_session_handle(
        self,
        *,
        workspace_id: str,
        handle_id: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_codex_session_handle(
                workspace_id,
                handle_id=handle_id,
            )

    def deactivate_codex_session_handle(
        self,
        *,
        workspace_id: str,
        handle_id: str,
        deactivated_by: str,
        reason: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().deactivate_codex_session_handle(
                workspace_id,
                handle_id=handle_id,
                deactivated_by=deactivated_by,
                reason=reason,
            )

    def activate_codex_registered_session(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        handle_id: str,
        exchange_request_id: str,
        handoff_directory: str | None = None,
        codex_executable: str = "codex",
        platform_workspace_root: str | None = None,
        default_platform_workspace_add_dir: bool = True,
        add_dirs: tuple[str, ...] = (),
        sandbox_mode: str | None = None,
        approval_policy: str | None = None,
        git_repo_check_policy: str = "skip",
        git_repo_check_policy_source: str = "default",
        activation_backend: str = "exec_resume",
        app_server_approval_decision: str = "decline",
        reply_writeback_mode: str = "explicit_only",
        control_config: Mapping[str, object] | None = None,
        dry_run: bool = True,
        timeout_seconds: int = 120,
    ) -> Mapping[str, object]:
        with self._components() as components:
            result = components.operations().activate_codex_registered_session(
                workspace_id,
                agent_id=agent_id,
                handle_id=handle_id,
                exchange_request_id=exchange_request_id,
                database_path=self.settings.database,
                workspace_root=self.settings.workspace_root,
                plugins_directory=self.settings.plugins_directory,
                handoff_directory=handoff_directory,
                codex_executable=codex_executable,
                platform_workspace_root=platform_workspace_root,
                default_platform_workspace_add_dir=default_platform_workspace_add_dir,
                add_dirs=add_dirs,
                sandbox_mode=sandbox_mode,
                approval_policy=approval_policy,
                git_repo_check_policy=git_repo_check_policy,
                git_repo_check_policy_source=git_repo_check_policy_source,
                activation_backend=activation_backend,
                app_server_approval_decision=app_server_approval_decision,
                reply_writeback_mode=reply_writeback_mode,
                dry_run=dry_run,
                timeout_seconds=timeout_seconds,
            )
            backend_source = "resolved_provider_configuration"
            if isinstance(control_config, MappingABC):
                activation_selection = control_config.get("activationBackend")
                if isinstance(activation_selection, MappingABC):
                    configured_source = activation_selection.get("source")
                    if configured_source is not None:
                        backend_source = str(configured_source)
            selection = resolve_provider_backend(
                "codex",
                codex_activation_backend=activation_backend,
                source=backend_source,
            )
            return {
                **dict(result),
                **(
                    {"codexControl": dict(control_config)}
                    if control_config is not None
                    else {}
                ),
                "providerBackendSelection": selection.to_metadata(),
            }

    def get_codex_session_status(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        handle_id: str,
        status_read_mode: str = "beacon_snapshot",
        codex_executable: str = "codex",
        point_read_timeout_seconds: int = 20,
        control_config: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_codex_session_status(
                workspace_id,
                agent_id=agent_id,
                handle_id=handle_id,
                status_read_mode=status_read_mode,
                codex_executable=codex_executable,
                point_read_timeout_seconds=point_read_timeout_seconds,
                control_config=control_config,
            )

    def submit_codex_session_supplement(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        handle_id: str,
        message: str,
        expected_turn_id: str,
        submitted_by: str,
        supplement_id: str | None = None,
        supplement_mode: str = "turn_steer",
        wait_once: bool = False,
        wait_timeout_seconds: float = 5.0,
        control_config: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().submit_codex_session_supplement(
                workspace_id,
                agent_id=agent_id,
                handle_id=handle_id,
                message=message,
                expected_turn_id=expected_turn_id,
                submitted_by=submitted_by,
                supplement_id=supplement_id,
                supplement_mode=supplement_mode,
                wait_once=wait_once,
                wait_timeout_seconds=wait_timeout_seconds,
                control_config=control_config,
            )

    def register_deepseek_harness_session_handle(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        deepseek_harness_session_id: str,
        cwd: str,
        created_by: str,
        reason: str,
        handle_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().register_deepseek_harness_session_handle(
                workspace_id,
                agent_id=agent_id,
                handle_id=handle_id,
                deepseek_harness_session_id=deepseek_harness_session_id,
                cwd=cwd,
                created_by=created_by,
                reason=reason,
                metadata=metadata,
            )

    def list_deepseek_harness_session_handles(
        self,
        *,
        workspace_id: str,
        agent_id: str | None = None,
        include_inactive: bool = False,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().list_deepseek_harness_session_handles(
                workspace_id,
                agent_id=agent_id,
                include_inactive=include_inactive,
            )

    def get_deepseek_harness_session_handle(
        self,
        *,
        workspace_id: str,
        handle_id: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_deepseek_harness_session_handle(
                workspace_id,
                handle_id=handle_id,
            )

    def register_hermes_session_handle(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        hermes_session_id: str,
        cwd: str,
        created_by: str,
        reason: str,
        handle_id: str | None = None,
        source_path: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().register_hermes_session_handle(
                workspace_id,
                agent_id=agent_id,
                handle_id=handle_id,
                hermes_session_id=hermes_session_id,
                cwd=cwd,
                source_path=source_path,
                created_by=created_by,
                reason=reason,
                metadata=metadata,
            )

    def list_hermes_session_handles(
        self,
        *,
        workspace_id: str,
        agent_id: str | None = None,
        include_inactive: bool = False,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().list_hermes_session_handles(
                workspace_id,
                agent_id=agent_id,
                include_inactive=include_inactive,
            )

    def get_hermes_session_handle(
        self,
        *,
        workspace_id: str,
        handle_id: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_hermes_session_handle(
                workspace_id,
                handle_id=handle_id,
            )

    def deactivate_hermes_session_handle(
        self,
        *,
        workspace_id: str,
        handle_id: str,
        deactivated_by: str,
        reason: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().deactivate_hermes_session_handle(
                workspace_id,
                handle_id=handle_id,
                deactivated_by=deactivated_by,
                reason=reason,
            )

    def activate_hermes_registered_session(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        handle_id: str,
        exchange_request_id: str,
        handoff_directory: str | None = None,
        hermes_executable: str = "hermes",
        hermes_home: str | None = None,
        activation_backend: str = "cli",
        reply_writeback_mode: str | None = None,
        gateway_python: str | None = None,
        platform_workspace_root: str | None = None,
        source_tag: str = "agent-os",
        max_turns: int | None = None,
        dry_run: bool = True,
        timeout_seconds: int = 120,
    ) -> Mapping[str, object]:
        with self._components() as components:
            result = components.operations().activate_hermes_registered_session(
                workspace_id,
                agent_id=agent_id,
                handle_id=handle_id,
                exchange_request_id=exchange_request_id,
                database_path=self.settings.database,
                workspace_root=self.settings.workspace_root,
                plugins_directory=self.settings.plugins_directory,
                handoff_directory=handoff_directory,
                hermes_executable=hermes_executable,
                hermes_home=hermes_home,
                activation_backend=activation_backend,
                reply_writeback_mode=reply_writeback_mode,
                gateway_python=gateway_python,
                platform_workspace_root=platform_workspace_root,
                source_tag=source_tag,
                max_turns=max_turns,
                dry_run=dry_run,
                timeout_seconds=timeout_seconds,
            )
            selection = resolve_provider_backend(
                "hermes",
                hermes_activation_backend=activation_backend,
                source=(
                    "provider_default"
                    if activation_backend == "cli"
                    else "resolved_hermes_control"
                ),
            )
            return {
                **dict(result),
                "providerBackendSelection": selection.to_metadata(),
            }

    def agent_activation_instructions(
        self,
        workspace_id: str | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().agent_activation_instructions(workspace_id)

    def wake_agent_activation(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        created_by: str,
        reason: str,
        activation_id: str | None = None,
        mode: str = "manual_wake_safe_mode",
        connection_surface: str = "cli",
        task_id: str | None = None,
        conversation_id: str | None = None,
        budget: Mapping[str, object] | None = None,
        allowed_contribution_kinds: tuple[str, ...] = (),
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().wake_agent_activation(
                workspace_id,
                agent_id=agent_id,
                created_by=created_by,
                reason=reason,
                activation_id=activation_id,
                mode=mode,
                connection_surface=connection_surface,
                task_id=task_id,
                conversation_id=conversation_id,
                budget=budget,
                allowed_contribution_kinds=allowed_contribution_kinds,
                metadata=metadata,
            )

    def get_agent_activation_status(
        self,
        *,
        workspace_id: str,
        agent_id: str | None = None,
        activation_id: str | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_agent_activation_status(
                workspace_id,
                agent_id=agent_id,
                activation_id=activation_id,
            )

    def list_agent_activations(
        self,
        workspace_id: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().list_agent_activations(workspace_id)

    def revoke_agent_activation(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        revoked_by: str,
        reason: str,
        activation_id: str | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().revoke_agent_activation(
                workspace_id,
                agent_id=agent_id,
                revoked_by=revoked_by,
                reason=reason,
                activation_id=activation_id,
            )

    def delegated_wake_instructions(
        self,
        workspace_id: str | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().delegated_wake_instructions(
                workspace_id
            )

    def create_delegated_wake_grant(
        self,
        *,
        workspace_id: str,
        source_agent_id: str,
        target_agent_id: str,
        created_by: str,
        reason: str,
        delegated_wake_grant_id: str | None = None,
        mode: str = "user_authorized_one_time",
        task_id: str | None = None,
        conversation_id: str | None = None,
        target_activation_mode: str = "manual_wake_safe_mode",
        target_activation_budget: Mapping[str, object] | None = None,
        allowed_contribution_kinds: tuple[str, ...] = (),
        expires_at: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().create_delegated_wake_grant(
                workspace_id,
                source_agent_id=source_agent_id,
                target_agent_id=target_agent_id,
                created_by=created_by,
                reason=reason,
                delegated_wake_grant_id=delegated_wake_grant_id,
                mode=mode,
                task_id=task_id,
                conversation_id=conversation_id,
                target_activation_mode=target_activation_mode,
                target_activation_budget=target_activation_budget,
                allowed_contribution_kinds=allowed_contribution_kinds,
                expires_at=_optional_datetime(expires_at),
                metadata=metadata,
            )

    def get_delegated_wake_grant_status(
        self,
        *,
        workspace_id: str,
        delegated_wake_grant_id: str | None = None,
        source_agent_id: str | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_delegated_wake_grant_status(
                workspace_id,
                delegated_wake_grant_id=delegated_wake_grant_id,
                source_agent_id=source_agent_id,
            )

    def list_delegated_wake_grants(
        self,
        workspace_id: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().list_delegated_wake_grants(workspace_id)

    def consume_delegated_wake_grant(
        self,
        *,
        workspace_id: str,
        delegated_wake_grant_id: str,
        consuming_agent_id: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().consume_delegated_wake_grant(
                workspace_id,
                delegated_wake_grant_id=delegated_wake_grant_id,
                consuming_agent_id=consuming_agent_id,
            )

    def revoke_delegated_wake_grant(
        self,
        *,
        workspace_id: str,
        delegated_wake_grant_id: str,
        revoked_by: str,
        reason: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().revoke_delegated_wake_grant(
                workspace_id,
                delegated_wake_grant_id=delegated_wake_grant_id,
                revoked_by=revoked_by,
                reason=reason,
            )

    def project_directory_coordination_instructions(
        self,
        workspace_id: str | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().project_directory_coordination_instructions(
                workspace_id
            )

    def declare_project_directory_coordination(
        self,
        *,
        workspace_id: str,
        declared_agent_id: str,
        project_root: str,
        directory_coordination_id: str | None = None,
        git_repository_id: str | None = None,
        linked_task_id: str | None = None,
        linked_conversation_id: str | None = None,
        declared_path_scopes: tuple[str, ...] = (".",),
        directory_access_intent: str = "edit_planned",
        last_known_git_head: str | None = None,
        last_known_branch: str | None = None,
        dirty_state: str = "unknown",
        uncommitted_change_summary: str | None = None,
        test_summary: str | None = None,
        recommended_commit_policy: str = "commit_after_task",
        handoff_note: str | None = None,
        requires_user_review: bool = False,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().declare_project_directory_coordination(
                workspace_id,
                declared_agent_id=declared_agent_id,
                project_root=project_root,
                directory_coordination_id=directory_coordination_id,
                git_repository_id=git_repository_id,
                linked_task_id=linked_task_id,
                linked_conversation_id=linked_conversation_id,
                declared_path_scopes=declared_path_scopes,
                directory_access_intent=directory_access_intent,
                last_known_git_head=last_known_git_head,
                last_known_branch=last_known_branch,
                dirty_state=dirty_state,
                uncommitted_change_summary=uncommitted_change_summary,
                test_summary=test_summary,
                recommended_commit_policy=recommended_commit_policy,
                handoff_note=handoff_note,
                requires_user_review=requires_user_review,
                metadata=metadata,
            )

    def get_project_directory_coordination_status(
        self,
        *,
        workspace_id: str,
        directory_coordination_id: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_project_directory_coordination_status(
                workspace_id,
                directory_coordination_id=directory_coordination_id,
            )

    def list_project_directory_coordination(
        self,
        workspace_id: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().list_project_directory_coordination(
                workspace_id
            )

    def update_project_directory_coordination(
        self,
        *,
        workspace_id: str,
        directory_coordination_id: str,
        directory_access_intent: str | None = None,
        declared_path_scopes: tuple[str, ...] | None = None,
        last_known_git_head: str | None = None,
        last_known_branch: str | None = None,
        dirty_state: str | None = None,
        uncommitted_change_summary: str | None = None,
        test_summary: str | None = None,
        recommended_commit_policy: str | None = None,
        handoff_note: str | None = None,
        requires_user_review: bool | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().update_project_directory_coordination(
                workspace_id,
                directory_coordination_id=directory_coordination_id,
                directory_access_intent=directory_access_intent,
                declared_path_scopes=declared_path_scopes,
                last_known_git_head=last_known_git_head,
                last_known_branch=last_known_branch,
                dirty_state=dirty_state,
                uncommitted_change_summary=uncommitted_change_summary,
                test_summary=test_summary,
                recommended_commit_policy=recommended_commit_policy,
                handoff_note=handoff_note,
                requires_user_review=requires_user_review,
                metadata=metadata,
            )

    def complete_project_directory_coordination(
        self,
        *,
        workspace_id: str,
        directory_coordination_id: str,
        last_known_git_head: str | None = None,
        last_known_branch: str | None = None,
        dirty_state: str | None = None,
        uncommitted_change_summary: str | None = None,
        test_summary: str | None = None,
        recommended_commit_policy: str | None = None,
        handoff_note: str | None = None,
        requires_user_review: bool | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().complete_project_directory_coordination(
                workspace_id,
                directory_coordination_id=directory_coordination_id,
                last_known_git_head=last_known_git_head,
                last_known_branch=last_known_branch,
                dirty_state=dirty_state,
                uncommitted_change_summary=uncommitted_change_summary,
                test_summary=test_summary,
                recommended_commit_policy=recommended_commit_policy,
                handoff_note=handoff_note,
                requires_user_review=requires_user_review,
                metadata=metadata,
            )

    def list_invocation_records(
        self,
        workspace_id: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().list_agent_invocation_records(workspace_id)

    def list_file_operation_records(
        self,
        workspace_id: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().list_file_operation_records(workspace_id)

    def get_run_session_timeline(
        self,
        *,
        workspace_id: str,
        session_id: str,
    ) -> Mapping[str, object]:
        with self._components() as components:
            return components.operations().get_run_session_timeline(
                workspace_id,
                session_id,
            )

    def run_smoke(
        self,
        *,
        workspace_id: str = "workspace-local-smoke-1",
        display_name: str = "Local Smoke Workspace",
        root_path: str | None = None,
        instruction: str = "Run local smoke invocation.",
        invocation_id: str = "invoke-local-smoke-1",
        session_id: str = "session-local-smoke-1",
    ) -> Mapping[str, object]:
        agent_id = _default_agent_id(workspace_id)
        created = self.create_workspace(
            workspace_id=workspace_id,
            display_name=display_name,
            root_path=root_path or self.settings.workspace_root,
            agent_id=agent_id,
        )
        opened = self.open_workspace(workspace_id)
        workspaces = self.list_workspaces()
        invocation = self.invoke_deterministic(
            workspace_id=workspace_id,
            agent_id=agent_id,
            instruction=instruction,
            invocation_id=invocation_id,
            session_id=session_id,
        )
        context = self.get_context(workspace_id)
        invocations = self.list_invocation_records(workspace_id)
        file_operations = self.list_file_operation_records(workspace_id)
        timeline = self.get_run_session_timeline(
            workspace_id=workspace_id,
            session_id=session_id,
        )
        return {
            "ok": True,
            "workspaceId": workspace_id,
            "agentId": agent_id,
            "sessionId": session_id,
            "steps": {
                "created": created["created"],
                "opened": opened["workspace"]["workspaceId"] == workspace_id,
                "listed": any(
                    item["workspaceId"] == workspace_id
                    for item in workspaces["workspaces"]
                ),
                "invoked": invocation["invocationResult"]["status"] == "succeeded",
                "contextQueried": context["context"] is not None,
                "invocationRecordsQueried": len(invocations["invocations"]) >= 1,
                "fileOperationRecordsQueried": (
                    len(file_operations["fileOperations"]) == 0
                ),
                "sessionTimelineQueried": timeline["session"]["eventCount"] >= 1,
            },
            "workspace": opened["workspace"],
            "context": context["context"],
            "invocation": invocation,
            "invocationRecords": invocations["invocations"],
            "fileOperationRecords": file_operations["fileOperations"],
            "session": timeline["session"],
            "sessionEvents": timeline["events"],
        }

    @contextmanager
    def _components(self) -> Iterator[LocalPlatformRuntimeComponents]:
        components = build_local_platform_runtime(self.settings)
        try:
            yield components
        finally:
            components.close()


def _default_agent_id(workspace_id: str) -> str:
    return f"agent-{workspace_id}"


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _optional_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("expiresAt must be timezone-aware.")
    return parsed


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _required_visible_agent_id(value: object) -> str:
    resolved = _optional_text(value)
    if resolved is None:
        raise ValueError("visibleAgentId must be a non-empty string.")
    return resolved


def _agent_dispatch_send_metadata(
    metadata: Mapping[str, object] | None,
    *,
    delivery_mode: str,
    delivery_mode_source: str,
    immediate_busy_policy: str,
    immediate_busy_policy_source: str,
    message_input_provided: bool = False,
    endpoint_alias_resolution: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    return {
        **dict(metadata or {}),
        "agentDispatchSend": {
            "schema": "agent_dispatch_send_metadata.v1",
            "apiLayer": "delivery-oriented",
            "highLevelDispatchApi": True,
            "deliveryMode": delivery_mode,
            "deliveryModeSource": delivery_mode_source,
            "immediateBusyPolicy": immediate_busy_policy,
            "immediateBusyPolicySource": immediate_busy_policy_source,
            "messageInputProvided": message_input_provided,
            "workerRunRequested": delivery_mode in (
                "worker_dry_run",
                "worker_execute",
            ),
            "workerExecuteRequested": delivery_mode == "worker_execute",
            "endpointAliasResolution": dict(endpoint_alias_resolution or {}),
        },
    }


def _agent_dispatch_api_layer(
    delivery_mode: str,
    *,
    dry_run: bool = False,
) -> Mapping[str, object]:
    semantic_mapping = effective_agent_dispatch_semantic_mapping(
        delivery_mode,
        dry_run=dry_run,
    )
    return {
        "schema": "agent_dispatch_api_layer.v1",
        "apiLayer": "delivery-oriented",
        "lowLevelRequestApiPreserved": True,
        "createsExchangeRequestState": True,
        "queuesDispatch": True,
        "canAttemptDelivery": delivery_mode in ("worker_dry_run", "worker_execute"),
        "deliveryMode": delivery_mode,
        "semanticMapping": semantic_mapping.to_metadata(),
        "deliveryType": "new_turn",
        "meaning": (
            "agent-dispatch-send/create is the delivery-oriented API. It may "
            "create exchange-request state and a dispatch queue entry, then "
            "optionally run one bounded worker pass."
        ),
    }


def _agent_dispatch_send_mode_summary(
    delivery_mode: str,
    *,
    dry_run: bool = False,
) -> Mapping[str, object]:
    semantic_mapping = effective_agent_dispatch_semantic_mapping(
        delivery_mode,
        dry_run=dry_run,
    )
    return {
        "schema": "agent_dispatch_send_mode_summary.v1",
        "deliveryMode": delivery_mode,
        "externalOperation": semantic_mapping.external_operation.value,
        "executionStrategy": semantic_mapping.execution_strategy.value,
        "legacyDeliveryMode": semantic_mapping.legacy_delivery_mode,
        "deliveryType": "new_turn",
        "waitMode": "once" if delivery_mode == "worker_execute" else "none",
        "senderCanExitAfterQueue": delivery_mode == "queued",
        "workerRunRequested": delivery_mode in ("worker_dry_run", "worker_execute"),
        "workerExecuteRequested": delivery_mode == "worker_execute",
        "deliveryAttemptBounded": delivery_mode in ("worker_dry_run", "worker_execute"),
    }


def _agent_dispatch_delivery_decision(
    *,
    delivery_mode: str,
    delivery_mode_source: str,
    immediate_busy_policy: str,
    immediate_busy_policy_source: str,
    dry_run: bool,
    worker_run: Mapping[str, object] | None,
    status: Mapping[str, object] | None,
    target_provider: str | None,
) -> Mapping[str, object]:
    semantic_mapping = effective_agent_dispatch_semantic_mapping(
        delivery_mode,
        dry_run=dry_run,
    )
    immediate_attempt = delivery_mode in {"worker_dry_run", "worker_execute"}
    item = _first_mapping_item(worker_run, "agentDispatches")
    provider_status = (
        item.get("providerRuntimeStatus")
        if isinstance(item, MappingABC)
        and isinstance(item.get("providerRuntimeStatus"), MappingABC)
        else None
    )
    target_state = (
        str(provider_status.get("runtimeState"))
        if isinstance(provider_status, MappingABC)
        and provider_status.get("runtimeState") is not None
        else "not_checked" if delivery_mode == "queued" else "unknown"
    )
    target_state_source = (
        str(provider_status.get("stateSource"))
        if isinstance(provider_status, MappingABC)
        and provider_status.get("stateSource") is not None
        else "not_checked" if delivery_mode == "queued" else "unknown"
    )
    dispatch = (
        status.get("agentDispatch")
        if isinstance(status, MappingABC)
        and isinstance(status.get("agentDispatch"), MappingABC)
        else None
    )
    request = (
        status.get("agentExchangeRequest")
        if isinstance(status, MappingABC)
        and isinstance(status.get("agentExchangeRequest"), MappingABC)
        else None
    )
    dispatch_status = (
        str(dispatch.get("status"))
        if isinstance(dispatch, MappingABC) and dispatch.get("status") is not None
        else None
    )
    effective_dispatch_status = (
        str(status.get("effectiveDispatchStatus"))
        if isinstance(status, MappingABC)
        and status.get("effectiveDispatchStatus") is not None
        else dispatch_status
    )
    failure_category = (
        str(item.get("failureCategory"))
        if isinstance(item, MappingABC) and item.get("failureCategory") is not None
        else None
    )
    provider_failure_category = _nested_text(
        item,
        ("providerFailureCategory",),
        ("activation", "failureCategory"),
        ("activation", "providerFailureCategory"),
    )
    busy_categories = {
        "target_busy_requires_sender_decision",
        "codex_target_busy_rejected_by_policy",
        "app_server_thread_busy",
        "target_runtime_busy",
        "target_runtime_blocked",
    }
    busy_returned = (
        failure_category in busy_categories
        or provider_failure_category in busy_categories
    )
    response_available = bool(
        isinstance(request, MappingABC)
        and (
            request.get("responseSummary") is not None
            or request.get("response") is not None
        )
    )
    terminal_unprocessed = effective_dispatch_status == "terminal_unprocessed"
    completion_observed = (
        effective_dispatch_status == "completed" or response_available
    )
    if dry_run:
        outcome = "unknown"
    elif terminal_unprocessed:
        outcome = "terminal_unprocessed"
    elif delivery_mode == "queued":
        outcome = "queued"
    elif busy_returned:
        outcome = "busy_returned"
    elif completion_observed:
        outcome = "completed"
    elif effective_dispatch_status in {"failed", "cancelled"}:
        outcome = "failed"
    else:
        outcome = "unknown"

    can_steer = bool(
        isinstance(provider_status, MappingABC)
        and (
            provider_status.get("canSteer") is True
            or _nested_bool(provider_status, "canSteer")
        )
    )
    available_actions: list[str] = []
    guidance: str
    if busy_returned:
        if (target_provider or "").strip().lower() == "codex" and can_steer:
            available_actions.append("supplement_active_turn")
        available_actions.extend(("queue_next_turn", "cancel"))
        guidance = (
            "Target is busy. The caller must explicitly choose whether to "
            "supplement an owned active Codex turn when offered, create a queued "
            "next-turn dispatch, or cancel."
        )
    elif outcome == "terminal_unprocessed":
        guidance = (
            "The linked request was already terminal before provider delivery. "
            "The append-only raw dispatch remains available for audit and will "
            "not be selected by a worker."
        )
    elif outcome == "queued":
        available_actions.append("inspect_queue_status")
        guidance = (
            "Dispatch was stored for an explicitly selected asynchronous worker "
            "or daemon path; Beacon did not start or verify a provider command."
        )
    elif outcome == "completed":
        available_actions.append("read_response")
        guidance = "The bounded delivery completed; read the recorded response."
    elif dry_run:
        available_actions.append("execute_planned_delivery")
        guidance = "Dry-run only: no dispatch state or provider command was created."
    else:
        available_actions.extend(("inspect_status", "cancel"))
        guidance = "Inspect the returned dispatch and provider failure details."

    provider_command_started = bool(
        _nested_bool(item, "providerCommandStarted")
        or _nested_bool(worker_run, "providerCommandStarted")
    )
    delivery_attempted = bool(
        immediate_attempt
        and not dry_run
        and isinstance(worker_run, MappingABC)
        and worker_run.get("workerStarted") is True
        and isinstance(item, MappingABC)
        and not bool(item.get("skipped"))
    )
    activation_status = _nested_text(item, ("activation", "status"))
    native_turn_status = _nested_text(
        item,
        ("activation", "nativeTurnStatus"),
    )
    execution_completed = bool(
        completion_observed
        or activation_status in {"delivered", "completed"}
        or native_turn_status in {"completed", "succeeded"}
    )
    if dry_run:
        delivery_state = "unknown"
        execution_state = "not_started"
    elif terminal_unprocessed:
        delivery_state = "not_delivered"
        execution_state = "not_started"
    elif delivery_mode == "queued":
        delivery_state = "queued"
        execution_state = "not_started"
    elif busy_returned:
        delivery_state = "rejected"
        execution_state = "not_started"
    elif effective_dispatch_status in {"failed", "cancelled"}:
        delivery_state = "failed"
        execution_state = "failed"
    elif execution_completed:
        delivery_state = "accepted"
        execution_state = "completed"
    elif provider_command_started:
        delivery_state = "unknown"
        execution_state = "active"
    else:
        delivery_state = "unknown"
        execution_state = "unknown"
    reply_state = "recorded" if response_available else "none"
    state_projection = {
        "schema": "agent_dispatch_state_projection.v1",
        "deliveryState": delivery_state,
        "executionState": execution_state,
        "replyState": reply_state,
        "replyExpectation": "unspecified",
    }
    return {
        "schema": "agent_dispatch_delivery_decision.v1",
        "externalOperation": semantic_mapping.external_operation.value,
        "executionStrategy": semantic_mapping.execution_strategy.value,
        "legacyDeliveryMode": semantic_mapping.legacy_delivery_mode,
        "semanticMapping": semantic_mapping.to_metadata(),
        "stateProjection": state_projection,
        "deliveryState": delivery_state,
        "executionState": execution_state,
        "replyState": reply_state,
        "replyExpectation": "unspecified",
        "requestedMode": delivery_mode,
        "effectiveMode": delivery_mode,
        "modeSource": delivery_mode_source,
        "immediateBusyPolicy": immediate_busy_policy,
        "immediateBusyPolicySource": immediate_busy_policy_source,
        "immediateAttempt": immediate_attempt,
        "targetStateBeforeAttempt": target_state,
        "targetStateSource": target_state_source,
        "deliveryAttempted": delivery_attempted,
        "providerCommandStarted": provider_command_started,
        "deliveryAccepted": bool(
            not terminal_unprocessed
            and (provider_command_started or completion_observed)
        ),
        "completionObserved": completion_observed,
        "responseAvailable": response_available,
        "outcome": outcome,
        "busyDecisionRequired": busy_returned,
        "normalizedFailureCategory": (
            "target_busy_requires_sender_decision"
            if busy_returned
            else failure_category
        ),
        "providerFailureCategory": provider_failure_category,
        "availableActions": available_actions,
        "guidance": guidance,
        "requiresUserReview": bool(
            isinstance(request, MappingABC)
            and request.get("requiresUserReview") is True
        ),
    }


def _first_mapping_item(
    value: Mapping[str, object] | None,
    key: str,
) -> Mapping[str, object] | None:
    if not isinstance(value, MappingABC):
        return None
    items = value.get(key)
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        return None
    return items[0] if items and isinstance(items[0], MappingABC) else None


def _nested_bool(value: object, key: str) -> bool:
    if isinstance(value, MappingABC):
        if value.get(key) is True:
            return True
        return any(_nested_bool(item, key) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_nested_bool(item, key) for item in value)
    return False


def _nested_text(
    value: Mapping[str, object] | None,
    *paths: tuple[str, ...],
) -> str | None:
    for path in paths:
        current: object = value
        for key in path:
            if not isinstance(current, MappingABC):
                current = None
                break
            current = current.get(key)
        if current is not None:
            text = str(current).strip()
            if text:
                return text
    return None


def _agent_onboarding_status_payload(
    *,
    settings: LocalPlatformSettings,
    workspace_id: str,
    workspace: Mapping[str, object] | None,
    agents: Sequence[Mapping[str, object]],
    provider_handles: Sequence[Mapping[str, object]],
    endpoints: Sequence[Mapping[str, object]],
    dispatcher_status: Mapping[str, object] | None,
    provider_session_memberships: Sequence[Mapping[str, object]],
    provider_session_registry_resolution: ProviderSessionRegistryPathResolution,
    filters: Mapping[str, object],
    read_live_runtime_status: bool | str,
) -> Mapping[str, object]:
    runtime_status_policy = normalize_provider_runtime_status_read_policy(
        read_live_runtime_status
    )
    commands = _agent_onboarding_commands(
        settings,
        workspace_id=workspace_id,
        agent_id=_optional_command_text(filters.get("agentId")),
        endpoint_alias=_optional_command_text(filters.get("endpointAlias")),
        provider=_optional_command_text(filters.get("provider")),
    )
    missing = _agent_onboarding_missing(
        workspace=workspace,
        agents=agents,
        provider_handles=provider_handles,
        endpoints=endpoints,
        agent_id=_optional_command_text(filters.get("agentId")),
    )
    dispatch_readiness = _agent_onboarding_dispatch_readiness(
        endpoint_alias=_optional_command_text(filters.get("endpointAlias")),
        endpoints=endpoints,
        missing=missing,
    )
    if filters.get("nativeSessionId") is not None and len(provider_handles) != 1:
        dispatch_readiness = {**dispatch_readiness, "ready": False,
                              "reason": "native_session_missing_or_ambiguous"}
    next_action = _agent_onboarding_next_action(missing, dispatch_readiness)
    next_actions = _agent_onboarding_next_actions(
        missing=missing,
        dispatch_readiness=dispatch_readiness,
        commands=commands,
    )
    return {
        "schema": "agent_onboarding_status.v1",
        "ok": True,
        "workspaceId": workspace_id,
        "runtime": {
            "schema": "agent_onboarding_runtime.v1",
            "runtimeConfigSource": (
                "profile" if settings.profile_path is not None else "explicit_args"
            ),
            "profileResolved": settings.profile_path is not None,
            "profilePath": settings.profile_path,
            "databasePath": settings.database,
            "workspaceRoot": settings.workspace_root,
            "pluginsDirectory": settings.plugins_directory,
        },
        "workspace": {
            "schema": "agent_onboarding_workspace.v1",
            "workspaceId": workspace_id,
            "exists": workspace is not None,
            "status": workspace.get("status") if workspace is not None else None,
            "displayName": workspace.get("displayName")
            if workspace is not None
            else None,
            "rootPath": workspace.get("rootPath") if workspace is not None else None,
        },
        "filters": dict(filters),
        "nativeSessionResolution": {
            "status": (
                "not_requested" if filters.get("nativeSessionId") is None else
                "missing" if not provider_handles else
                "ambiguous" if len(provider_handles) > 1 else
                "matched" if provider_handles[0].get("active") else "inactive"
            ),
            "matchCount": len(provider_handles) if filters.get("nativeSessionId") is not None else None,
            "scope": "registered_workspace_handles",
            "externalDiscoveryPerformed": False,
            "runtimeStarted": False,
        },
        "agents": {
            "schema": "agent_onboarding_agents.v1",
            "count": len(agents),
            "agents": list(agents),
        },
        "providerSessionHandles": _agent_onboarding_handle_inventory(
            provider_handles
        ),
        "endpointAliases": _agent_onboarding_endpoint_inventory(endpoints),
        "providerSessionProfiles": _agent_onboarding_provider_session_profiles(
            provider_session_memberships
        ),
        **provider_session_registry_resolution.to_metadata(),
        "dispatchReadiness": dispatch_readiness,
        "dispatcher": _agent_onboarding_dispatcher(dispatcher_status),
        "missing": missing,
        "ready": dispatch_readiness["ready"],
        "nextAction": next_action,
        "nextActions": next_actions,
        "commands": commands,
        "statusHints": {
            "schema": "agent_onboarding_status_hints.v1",
            "daemonAffectsDeliveryTiming": True,
            "daemonRequiredForQueuedAutoDelivery": True,
            "workerExecuteCanAttemptOneBoundedDeliveryNow": True,
            "dispatchReadinessDoesNotStartDaemonOrWorker": True,
            "runtimeStatusPolicy": runtime_status_policy,
            "readLiveRuntimeStatusRequested": runtime_status_policy == "enabled",
        },
        "boundaries": {
            "schema": "agent_onboarding_status_boundaries.v1",
            "providerCredentialStored": False,
            "providerAccountAuthenticated": False,
            "providerPermissionDefaultsModified": False,
            "fullProviderTranscriptRead": False,
            "privateReasoningIncluded": False,
            "internalMigrationHistoryIncluded": False,
            "dispatchOrDaemonSemanticsModified": False,
        },
    }


def _provider_session_registry_resolution_from_settings(
    settings: LocalPlatformSettings,
) -> ProviderSessionRegistryPathResolution:
    if settings.provider_session_registry is not None:
        return provider_session_registry_path_resolution(
            settings.provider_session_registry,
            source=(
                settings.provider_session_registry_source or "workspace_derived"
            ),
            source_key=(
                settings.provider_session_registry_source_key or "workspaceRoot"
            ),
        )
    return resolve_provider_session_registry_path(
        workspace_root=settings.workspace_root,
    )


def _provider_session_workspace_join_failure(
    *,
    settings: LocalPlatformSettings,
    workspace_id: str,
    provider_session_profile: Mapping[str, object],
    failed_stage: str,
    stages: Sequence[Mapping[str, object]],
    message: str,
    conflict: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    alias = str(provider_session_profile.get("profileAlias", "<endpoint-alias>"))
    return {
        "schema": "provider_session_workspace_join.v1",
        "ok": False,
        "completed": False,
        "workspaceId": workspace_id,
        "profileId": provider_session_profile.get("profileId"),
        "providerSessionProfile": _provider_session_profile_summary(
            provider_session_profile
        ),
        "failedStage": failed_stage,
        "stages": list(stages),
        "error": {
            "type": "WorkspaceJoinStageFailed",
            "message": message,
        },
        **({"conflict": conflict} if conflict is not None else {}),
        **_agent_provider_onboard_next_commands(
            settings,
            workspace_id=workspace_id,
            endpoint_alias=alias,
        ),
        "boundaries": _provider_session_workspace_join_boundaries(),
    }


def _provider_session_profile_summary(
    profile: Mapping[str, object],
) -> Mapping[str, object]:
    return {
        "schema": "local_provider_session_profile_summary.v1",
        "profileId": profile.get("profileId"),
        "provider": profile.get("provider"),
        "providerSessionId": profile.get("providerSessionId"),
        "profileAlias": profile.get("profileAlias"),
        "state": profile.get("state"),
        "cwdSummary": profile.get("cwdSummary"),
        "sourcePathSummary": profile.get("sourcePathSummary"),
        "credentialStored": False,
        "providerAccountAuthenticated": False,
        "fullSessionHistoryRead": False,
        "activationPolicy": profile.get("activationPolicy", MANUAL_ONLY_ACTIVATION_POLICY),
        "activationGuardEnforced": bool(profile.get("activationGuardEnforced")),
    }


def _provider_session_workspace_join_metadata(
    profile: Mapping[str, object],
    *,
    membership_id: str | None,
) -> Mapping[str, object]:
    return {
        "schema": "provider_session_workspace_join_metadata.v1",
        "profileId": profile.get("profileId"),
        "profileAlias": profile.get("profileAlias"),
        "provider": profile.get("provider"),
        "providerSessionId": profile.get("providerSessionId"),
        "membershipId": membership_id,
        "activationPolicy": MANUAL_ONLY_ACTIVATION_POLICY,
        "activationGuardEnforced": False,
        "automaticWorkerActivationAllowed": False,
    }


def _provider_session_workspace_endpoint_readiness(
    endpoint: Mapping[str, object],
    provider_handle: Mapping[str, object],
) -> Mapping[str, object]:
    endpoint_active = endpoint.get("state") == "active"
    handle_active = provider_handle.get("state") == "active"
    direction = str(endpoint.get("direction"))
    ready = endpoint_active and handle_active and direction in {
        "receive_only",
        "send_receive",
    }
    reasons: list[str] = []
    if not endpoint_active:
        reasons.append("endpoint_inactive")
    if not handle_active:
        reasons.append("provider_handle_inactive")
    if direction not in {"receive_only", "send_receive"}:
        reasons.append("endpoint_not_receive_capable")
    return {
        "schema": "provider_session_workspace_endpoint_readiness.v1",
        "readyForDispatch": ready,
        "notReadyReasons": reasons,
        "endpointAlias": endpoint.get("alias"),
        "endpointId": endpoint.get("endpointId"),
        "providerHandleId": provider_handle.get("handleId"),
        "direction": direction,
        "defaultReplyPolicy": endpoint.get("defaultReplyPolicy"),
        "contactPolicy": endpoint.get("contactPolicy"),
        "activationPolicy": MANUAL_ONLY_ACTIVATION_POLICY,
        "automaticWorkerActivationAllowed": False,
    }


def _provider_session_workspace_join_boundaries() -> Mapping[str, object]:
    return {
        "schema": "provider_session_workspace_join_boundaries.v1",
        "providerAccountLogin": False,
        "providerCredentialStored": False,
        "credentialStored": False,
        "fullSessionHistoryRead": False,
        "globalDispatchAliasCreated": False,
        "workspaceLocalAgentPreserved": True,
        "endpointAliasWorkspaceLocal": True,
        "providerPermissionDefaultsModified": False,
    }


def _agent_onboarding_agent_item(
    agent: Mapping[str, object],
) -> Mapping[str, object]:
    return {
        "agentId": agent.get("agentId"),
        "workspaceId": agent.get("workspaceId"),
        "name": agent.get("name"),
        "description": agent.get("description"),
        "status": agent.get("status"),
        "createdAt": agent.get("createdAt"),
        "updatedAt": agent.get("updatedAt"),
    }


def _agent_matches_onboarding_filters(
    agent: Mapping[str, object],
    *,
    agent_id: str | None,
) -> bool:
    return agent_id is None or agent.get("agentId") == agent_id


def _agent_onboarding_provider_handles(
    operations,
    *,
    workspace_id: str,
    agent_id: str | None,
    provider: str | None,
) -> list[Mapping[str, object]]:
    handles: list[Mapping[str, object]] = []
    if provider in (None, "claude"):
        handles.extend(
            _agent_onboarding_handle_item("claude", handle)
            for handle in operations.list_claude_session_handles(
                workspace_id,
                include_inactive=True,
            )["claudeSessionHandles"]
        )
    if provider in (None, "codex"):
        handles.extend(
            _agent_onboarding_handle_item("codex", handle)
            for handle in operations.list_codex_session_handles(
                workspace_id,
                include_inactive=True,
            )["codexSessionHandles"]
        )
    if provider in (None, "hermes"):
        handles.extend(
            _agent_onboarding_handle_item("hermes", handle)
            for handle in operations.list_hermes_session_handles(
                workspace_id,
                include_inactive=True,
            )["hermesSessionHandles"]
        )
    if provider in (None, "deepseek_harness"):
        handles.extend(
            _agent_onboarding_handle_item("deepseek_harness", handle)
            for handle in operations.list_deepseek_harness_session_handles(
                workspace_id,
                include_inactive=True,
            )["deepseekHarnessSessionHandles"]
        )
    return [
        handle
        for handle in sorted(
            handles,
            key=lambda item: (
                str(item.get("provider")),
                str(item.get("agentId")),
                str(item.get("handleId")),
            ),
        )
        if _provider_handle_matches_onboarding_filters(
            handle,
            agent_id=agent_id,
            provider=provider,
        )
    ]


def _provider_handle_matches_onboarding_filters(
    handle: Mapping[str, object],
    *,
    agent_id: str | None,
    provider: str | None,
) -> bool:
    return (
        (agent_id is None or handle.get("agentId") == agent_id)
        and (provider is None or handle.get("provider") == provider)
    )


def _agent_onboarding_handle_item(
    provider: str,
    handle: Mapping[str, object],
) -> Mapping[str, object]:
    session_field = _provider_session_id_field(provider)
    session_id = handle.get(session_field)
    state = str(handle.get("state", "active"))
    return {
        "schema": "agent_provider_session_handle_inventory_item.v1",
        "provider": provider,
        "providerKind": handle.get("provider"),
        "handleId": handle.get("handleId"),
        "agentId": handle.get("agentId"),
        "nativeSessionId": session_id,
        "active": state == "active",
        "state": state,
        "session": {
            "field": session_field,
            "id": session_id,
            "summary": _safe_session_summary(session_id),
        },
        "cwd": handle.get("cwd"),
        "sourcePath": handle.get("sourcePath"),
        "createdAt": handle.get("createdAt"),
        "updatedAt": handle.get("updatedAt"),
        "credentialStored": False,
        "fullSessionHistoryRead": False,
    }


def _safe_session_summary(session_id: object) -> str | None:
    if session_id is None:
        return None
    text = str(session_id)
    if len(text) <= 24:
        return text
    return f"{text[:12]}...{text[-8:]}"


def _agent_onboarding_endpoints(
    endpoint_records: Sequence[Mapping[str, object]],
    *,
    provider_handles: Sequence[Mapping[str, object]],
    agent_id: str | None,
    endpoint_alias: str | None,
    provider: str | None,
) -> list[Mapping[str, object]]:
    handle_index = {
        (str(handle.get("provider")), str(handle.get("handleId"))): handle
        for handle in provider_handles
    }
    endpoints: list[Mapping[str, object]] = []
    for endpoint in endpoint_records:
        if endpoint_alias is not None and endpoint.get("alias") != endpoint_alias:
            continue
        agent_matches = agent_id is None or endpoint.get("agentId") == agent_id
        provider_matches = provider is None or endpoint.get("provider") == provider
        if endpoint_alias is None and (not agent_matches or not provider_matches):
            continue
        endpoints.append(
            _agent_onboarding_endpoint_item(
                endpoint,
                provider_handle=handle_index.get(
                    (
                        str(endpoint.get("provider")),
                        str(endpoint.get("providerHandleId")),
                    )
                ),
                agent_matches=agent_matches,
                provider_matches=provider_matches,
            )
        )
    return sorted(endpoints, key=lambda item: str(item.get("alias")))


def _agent_onboarding_endpoint_item(
    endpoint: Mapping[str, object],
    *,
    provider_handle: Mapping[str, object] | None,
    agent_matches: bool,
    provider_matches: bool,
) -> Mapping[str, object]:
    state = str(endpoint.get("state", "active"))
    direction = str(endpoint.get("direction", "send_receive"))
    endpoint_active = state == "active"
    provider_handle_found = provider_handle is not None
    provider_handle_active = bool(
        provider_handle_found and provider_handle.get("active")
    )
    profile_ref = provider_session_profile_ref(endpoint) or provider_session_profile_ref(
        provider_handle
    )
    ready_as_source = (
        endpoint_active
        and provider_handle_active
        and agent_matches
        and provider_matches
        and direction in {"send_only", "send_receive"}
    )
    ready_as_target = (
        endpoint_active
        and provider_handle_active
        and agent_matches
        and provider_matches
        and direction in {"receive_only", "send_receive"}
        and endpoint.get("contactPolicy") != "block_all"
    )
    reasons: list[str] = []
    if not endpoint_active:
        reasons.append("endpoint_inactive")
    if not provider_handle_found:
        reasons.append("provider_handle_missing")
    elif not provider_handle_active:
        reasons.append("provider_handle_inactive")
    if not agent_matches:
        reasons.append("agent_filter_mismatch")
    if not provider_matches:
        reasons.append("provider_filter_mismatch")
    if direction not in {"receive_only", "send_receive"}:
        reasons.append("endpoint_not_receive_capable")
    if endpoint.get("contactPolicy") == "block_all":
        reasons.append("contact_policy_blocks_all")
    return {
        "schema": "agent_endpoint_inventory_item.v1",
        "endpointId": endpoint.get("endpointId"),
        "alias": endpoint.get("alias"),
        "agentId": endpoint.get("agentId"),
        "provider": endpoint.get("provider"),
        "providerHandleId": endpoint.get("providerHandleId"),
        "active": endpoint_active,
        "state": state,
        "direction": direction,
        "defaultReplyPolicy": endpoint.get("defaultReplyPolicy"),
        "contactPolicy": endpoint.get("contactPolicy"),
        "providerHandleFound": provider_handle_found,
        "providerHandleActive": provider_handle_active,
        "targetProvider": endpoint.get("provider"),
        "readyAsDispatchSource": ready_as_source,
        "readyAsDispatchTarget": ready_as_target,
        "readyForDispatch": ready_as_target,
        "notReadyReasons": [] if ready_as_target else reasons,
        "localProviderSessionProfile": profile_ref,
        "createdAt": endpoint.get("createdAt"),
        "updatedAt": endpoint.get("updatedAt"),
    }


def _agent_onboarding_handle_inventory(
    handles: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    by_provider = []
    for provider in ("claude", "codex", "hermes", "deepseek_harness"):
        provider_handles = [
            handle for handle in handles if handle.get("provider") == provider
        ]
        by_provider.append(
            {
                "provider": provider,
                "count": len(provider_handles),
                "activeCount": sum(
                    1 for handle in provider_handles if handle.get("active")
                ),
            }
        )
    by_agent: dict[str, int] = {}
    for handle in handles:
        agent_id = str(handle.get("agentId"))
        by_agent[agent_id] = by_agent.get(agent_id, 0) + 1
    return {
        "schema": "agent_provider_session_handle_inventory.v1",
        "count": len(handles),
        "activeCount": sum(1 for handle in handles if handle.get("active")),
        "byProvider": by_provider,
        "byAgent": [
            {"agentId": agent_id, "count": count}
            for agent_id, count in sorted(by_agent.items())
        ],
        "handles": list(handles),
    }


def _agent_onboarding_endpoint_inventory(
    endpoints: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    return {
        "schema": "agent_endpoint_inventory.v1",
        "count": len(endpoints),
        "activeCount": sum(1 for endpoint in endpoints if endpoint.get("active")),
        "readyForDispatchCount": sum(
            1 for endpoint in endpoints if endpoint.get("readyForDispatch")
        ),
        "endpoints": list(endpoints),
    }


def _agent_onboarding_provider_session_profiles(
    memberships: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    active = [item for item in memberships if item.get("state") == "active"]
    return {
        "schema": "agent_onboarding_provider_session_profiles.v1",
        "count": len(memberships),
        "activeMembershipCount": len(active),
        "activationPolicy": MANUAL_ONLY_ACTIVATION_POLICY,
        "activationGuardEnforced": False,
        "automaticWorkerActivationAllowed": False,
        "memberships": list(memberships),
    }


def _agent_onboarding_dispatch_readiness(
    *,
    endpoint_alias: str | None,
    endpoints: Sequence[Mapping[str, object]],
    missing: Sequence[str],
) -> Mapping[str, object]:
    ready_endpoints = [
        endpoint for endpoint in endpoints if endpoint.get("readyForDispatch")
    ]
    not_ready_reasons = sorted(
        {
            str(reason)
            for endpoint in endpoints
            for reason in endpoint.get("notReadyReasons", ())
        }
    )
    if not endpoints:
        not_ready_reasons.extend(
            reason
            for reason in missing
            if reason in {"workspace", "agent", "session_handle", "endpoint_alias"}
        )
    return {
        "schema": "agent_alias_dispatch_readiness.v1",
        "ready": bool(ready_endpoints),
        "selectedAlias": endpoint_alias,
        "readyAliasCount": len(ready_endpoints),
        "readyAliases": [endpoint.get("alias") for endpoint in ready_endpoints],
        "notReadyReasons": not_ready_reasons,
        "meaning": (
            "ready means at least one matching active endpoint alias is bound to "
            "an active provider handle and can be used as a dispatch target."
        ),
    }


def _agent_onboarding_dispatcher(
    dispatcher_status: Mapping[str, object] | None,
) -> Mapping[str, object]:
    if dispatcher_status is None:
        return {
            "schema": "agent_onboarding_dispatcher_hint.v1",
            "known": False,
            "dispatcherRunning": False,
            "state": "unknown",
            "daemonLiveness": None,
        }
    return {
        "schema": "agent_onboarding_dispatcher_hint.v1",
        "known": True,
        "dispatcherRunning": bool(dispatcher_status.get("dispatcherRunning")),
        "state": dispatcher_status.get("state"),
        "daemonLiveness": dispatcher_status.get("daemonLiveness"),
    }


def _agent_onboarding_missing(
    *,
    workspace: Mapping[str, object] | None,
    agents: Sequence[Mapping[str, object]],
    provider_handles: Sequence[Mapping[str, object]],
    endpoints: Sequence[Mapping[str, object]],
    agent_id: str | None,
) -> list[str]:
    missing: list[str] = []
    if workspace is None:
        return ["workspace", "agent", "session_handle", "endpoint_alias"]
    if not agents or (
        agent_id is None
        and not provider_handles
        and not endpoints
    ):
        missing.append("agent")
    if not provider_handles:
        missing.append("session_handle")
    if not endpoints:
        missing.append("endpoint_alias")
    elif not any(endpoint.get("readyForDispatch") for endpoint in endpoints):
        missing.append("dispatch_readiness")
    return missing


def _agent_onboarding_next_action(
    missing: Sequence[str],
    dispatch_readiness: Mapping[str, object],
) -> str:
    if "workspace" in missing:
        return "create_or_open_workspace"
    if "agent" in missing:
        return "join_agent"
    if "session_handle" in missing:
        return "join_agent_session"
    if "endpoint_alias" in missing:
        return "join_agent_endpoint"
    if "dispatch_readiness" in missing:
        return "fix_endpoint_or_provider_handle"
    if dispatch_readiness.get("ready"):
        return "dispatch_by_alias"
    return "inspect_status"


def _agent_onboarding_next_actions(
    *,
    missing: Sequence[str],
    dispatch_readiness: Mapping[str, object],
    commands: Mapping[str, Mapping[str, object]],
) -> list[Mapping[str, object]]:
    def action(kind: str, reason: str, command_key: str) -> Mapping[str, object]:
        command = commands[command_key]
        return {
            "kind": kind,
            "reason": reason,
            "commandKey": command_key,
            "argv": command["argv"],
            "command": command["command"],
        }

    if "workspace" in missing:
        return [
            action("create_workspace", "workspace state is missing", "workspaceCreate"),
            action("initialize_profile", "profile-first setup path", "profileInit"),
        ]
    if "agent" in missing:
        return [
            action("join_agent", "workspace agent is missing", "agentJoin"),
        ]
    if "session_handle" in missing:
        return [
            action("join_agent", "provider session handle is missing", "agentJoin"),
        ]
    if "endpoint_alias" in missing:
        return [
            action("join_agent", "endpoint alias is missing", "agentJoin"),
        ]
    if "dispatch_readiness" in missing:
        return [
            action("inspect_status", "matching alias is not ready for dispatch", "onboardingStatus"),
            action("endpoint_status", "inspect endpoint and provider handle status", "endpointStatus"),
        ]
    if dispatch_readiness.get("ready"):
        return [
            action("send", "alias is ready as a dispatch target", "dispatchSendExample"),
            action("dispatch_queued", "advanced queue requires a worker or daemon", "dispatchQueuedExample"),
        ]
    return [action("inspect_status", "no actionable readiness state found", "onboardingStatus")]


def _agent_onboarding_commands(
    settings: LocalPlatformSettings,
    *,
    workspace_id: str,
    agent_id: str | None,
    endpoint_alias: str | None,
    provider: str | None,
) -> Mapping[str, Mapping[str, object]]:
    base = _agent_dispatch_runtime_base(
        database_path=settings.database,
        workspace_root=settings.workspace_root,
        plugins_directory=settings.plugins_directory,
        profile_path=settings.profile_path,
        pretty=False,
    )
    profile_init_argv = [
        "py",
        "-3",
        "-m",
        "agent_os.local_runtime",
        "agent-workspace-init",
        "--project-root",
        "<project-root>",
        "--workspace-id",
        workspace_id,
        "--display-name",
        "<workspace-name>",
    ]
    provider_arg = provider or "<provider>"
    agent_arg = agent_id or "<agent-id>"
    alias_arg = endpoint_alias or "<endpoint-alias>"
    status_argv = [
        *base,
        "agent-onboarding-status",
        "--workspace-id",
        workspace_id,
    ]
    if agent_id is not None:
        status_argv.extend(["--agent-id", agent_id])
    if endpoint_alias is not None:
        status_argv.extend(["--endpoint-alias", endpoint_alias])
    if provider is not None:
        status_argv.extend(["--provider", provider])
    endpoint_status_argv = [
        *base,
        "agent-endpoint-status",
        "--workspace-id",
        workspace_id,
        "--alias",
        alias_arg,
    ]
    commands = {
        "profileInit": profile_init_argv,
        "agentJoin": [
            *base,
            "agent-join",
            "--workspace-id",
            workspace_id,
            "--agent",
            agent_arg,
            "--provider",
            provider_arg,
            "--session",
            "<native-session-id>",
            "--cwd",
            "<project-cwd>",
        ],
        "workspaceCreate": [
            *base,
            "workspace-create",
            "--workspace-id",
            workspace_id,
            "--display-name",
            "<workspace-name>",
        ],
        "agentCreate": [
            *base,
            "agent-create",
            "--workspace-id",
            workspace_id,
            "--agent-id",
            agent_arg,
            "--name",
            "<agent-name>",
            "--description",
            "<agent description>",
        ],
        "sessionDiscover": [
            *base,
            "agent-session-discover",
            "--provider",
            provider_arg,
            "--cwd",
            "<project-cwd>",
        ],
        "registerDiscoveredHandle": [
            *base,
            "agent-session-handle-register-discovered",
            "--workspace-id",
            workspace_id,
            "--agent-id",
            agent_arg,
            "--provider",
            provider_arg,
            "--session-id",
            "<session-id>",
            "--created-by",
            "<agent-or-user>",
            "--reason",
            "register discovered provider session",
        ],
        "providerOnboard": [
            *base,
            "agent-provider-onboard",
            "--workspace-id",
            workspace_id,
            "--provider",
            provider_arg,
            "--agent-id",
            agent_arg,
            "--agent-name",
            "<agent-name>",
            "--endpoint-alias",
            alias_arg,
            "--cwd",
            "<project-cwd>",
        ],
        "endpointLogin": [
            *base,
            "agent-endpoint-login",
            "--workspace-id",
            workspace_id,
            "--agent-id",
            agent_arg,
            "--alias",
            alias_arg,
            "--provider",
            provider_arg,
            "--provider-handle-id",
            "<provider-handle-id>",
            "--created-by",
            "<agent-or-user>",
            "--reason",
            "endpoint login",
        ],
        "onboardingStatus": status_argv,
        "endpointStatus": endpoint_status_argv,
        "dispatchQueuedExample": [
            *base,
            "agent-dispatch-send",
            "--workspace-id",
            workspace_id,
            "--as",
            "<source-endpoint-alias>",
            "--to",
            alias_arg,
            "--message",
            "<message>",
            "--queued",
        ],
        "dispatchSendExample": [
            *base,
            "agent-dispatch-send",
            "--workspace-id",
            workspace_id,
            "--as",
            "<source-endpoint-alias>",
            "--to",
            alias_arg,
            "--message",
            "<message>",
        ],
        "daemonStart": [
            *base,
            "agent-dispatch-daemon-start",
            "--workspace-id",
            workspace_id,
        ],
        "daemonStatus": [
            *base,
            "agent-dispatch-daemon-status",
            "--workspace-id",
            workspace_id,
        ],
        "helpOnboarding": [
            "py",
            "-3",
            "-m",
            "agent_os.local_runtime",
            "agent-help",
            "--topic",
            "onboarding",
        ],
    }
    if provider == "deepseek_harness":
        join = commands["agentJoin"]
        index = join.index("--session")
        join[index:index + 2] = ["--new-session"]
        # Discovery/profile import are not DSH capabilities. Do not offer
        # syntactically invalid or capability-expanding repair commands.
        for key in ("sessionDiscover", "registerDiscoveredHandle", "providerOnboard"):
            commands.pop(key)
        invocation, environment = build_beacon_cli_invocation(
            database_path=settings.database, workspace_root=settings.workspace_root,
            plugins_directory=settings.plugins_directory, profile_path=settings.profile_path,
        )
        rendered = {}
        for key, argv in commands.items():
            if argv[:len(base)] == base:
                argv = [*invocation, *argv[len(base):]]
            else:
                argv = [*invocation[:3], *argv[4:]]
            examples = cli_shell_examples({"runtimeEnvironment": environment, "commandArgv": argv})["commandArgv"]
            rendered[key] = {"argv": argv, "runtimeEnvironment": environment,
                             "command": examples["powershell"], "shellExamples": examples}
        return rendered
    return {
        key: {
            "argv": argv,
            "command": subprocess.list2cmdline(argv),
        }
        for key, argv in commands.items()
    }


def _optional_command_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _agent_dispatch_status_command(
    workspace_id: str,
    dispatch_id: str,
    *,
    database_path: str,
    workspace_root: str,
    plugins_directory: str,
    profile_path: str | None,
) -> str:
    argv = [
        *_agent_dispatch_runtime_base(
            database_path=database_path,
            workspace_root=workspace_root,
            plugins_directory=plugins_directory,
            profile_path=profile_path,
            pretty=False,
        ),
        "agent-dispatch-status",
        "--workspace-id",
        workspace_id,
        "--dispatch-id",
        dispatch_id,
    ]
    return subprocess.list2cmdline(argv)


def _agent_dispatch_target_handoff(
    *,
    database_path: str,
    workspace_root: str,
    plugins_directory: str,
    profile_path: str | None = None,
    workspace_id: str,
    exchange_request_id: str,
    target_agent_id: str,
) -> Mapping[str, object]:
    base = _agent_dispatch_runtime_base(
        database_path=database_path,
        workspace_root=workspace_root,
        plugins_directory=plugins_directory,
        profile_path=profile_path,
        pretty=True,
    )
    request_read_argv = [
        *base,
        "agent-exchange-request-get",
        "--workspace-id",
        workspace_id,
        "--exchange-request-id",
        exchange_request_id,
    ]
    thread_read_argv = [
        *base,
        "agent-exchange-thread-get",
        "--workspace-id",
        workspace_id,
        "--thread-id",
        exchange_request_id,
        "--requesting-agent-id",
        target_agent_id,
    ]
    respond_argv_template = [
        *base,
        "agent-reply",
        "--workspace-id",
        workspace_id,
        "--request",
        exchange_request_id,
        "--agent",
        target_agent_id,
        "--message",
        "<short target-agent response>",
    ]
    return {
        "schema": "agent_dispatch_target_handoff.v1",
        "workspaceId": workspace_id,
        "exchangeRequestId": exchange_request_id,
        "threadId": exchange_request_id,
        "targetAgentId": target_agent_id,
        "runtimeConfigSource": (
            "profile" if profile_path is not None else "explicit_args"
        ),
        **({"profilePath": profile_path} if profile_path is not None else {}),
        "requestReadArgv": request_read_argv,
        "requestReadCommand": subprocess.list2cmdline(request_read_argv),
        "threadReadArgv": thread_read_argv,
        "threadReadCommand": subprocess.list2cmdline(thread_read_argv),
        "respondArgvTemplate": respond_argv_template,
        "respondCommandTemplate": subprocess.list2cmdline(respond_argv_template),
    }


def _agent_dispatch_runtime_base(
    *,
    database_path: str,
    workspace_root: str,
    plugins_directory: str,
    profile_path: str | None,
    pretty: bool,
) -> list[str]:
    base = ["py", "-3.11", "-m", "agent_os.local_runtime"]
    if profile_path is not None:
        base.extend(["--profile", profile_path])
    else:
        base.extend(
            [
                "--database",
                database_path,
                "--workspace-root",
                workspace_root,
                "--plugins-directory",
                plugins_directory,
            ]
        )
    if pretty:
        base.append("--pretty")
    return base


def _agent_provider_onboard_failure(
    *,
    settings: LocalPlatformSettings,
    workspace_id: str,
    endpoint_alias: str,
    provider: str,
    failed_stage: str,
    stages: Sequence[Mapping[str, object]],
    message: str,
    discovery: Mapping[str, object],
    dry_run: bool,
    conflict: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    return {
        "schema": "agent_provider_onboard.v1",
        "ok": False,
        "completed": False,
        "dryRun": dry_run,
        "workspaceId": workspace_id,
        "provider": provider,
        "endpointAlias": endpoint_alias,
        "failedStage": failed_stage,
        "stages": list(stages),
        "error": {
            "type": "OnboardingStageFailed",
            "message": message,
        },
        **({"conflict": conflict} if conflict is not None else {}),
        "discovery": discovery.get("agentSessionDiscovery", discovery),
        **_agent_provider_onboard_next_commands(
            settings,
            workspace_id=workspace_id,
            endpoint_alias=endpoint_alias,
        ),
        "boundaries": {
            "providerAccountCreated": False,
            "providerCredentialStored": False,
            "providerGlobalSettingsModified": False,
            "providerPermissionDefaultsModified": False,
            "fullSessionHistoryRead": False,
        },
    }


def _agent_provider_onboard_next_commands(
    settings: LocalPlatformSettings,
    *,
    workspace_id: str,
    endpoint_alias: str,
) -> Mapping[str, object]:
    base = _agent_dispatch_runtime_base(
        database_path=settings.database,
        workspace_root=settings.workspace_root,
        plugins_directory=settings.plugins_directory,
        profile_path=settings.profile_path,
        pretty=False,
    )
    status_argv = [
        *base,
        "agent-endpoint-status",
        "--workspace-id",
        workspace_id,
        "--alias",
        endpoint_alias,
    ]
    dispatch_argv = [
        *base,
        "agent-dispatch-send",
        "--workspace-id",
        workspace_id,
        "--as",
        "<source-endpoint-alias>",
        "--to",
        endpoint_alias,
        "--message",
        "<message>",
        "--queued",
    ]
    return {
        "nextStatusArgv": status_argv,
        "nextStatusCommand": subprocess.list2cmdline(status_argv),
        "nextDispatchExampleArgv": dispatch_argv,
        "nextDispatchExample": subprocess.list2cmdline(dispatch_argv),
    }


def _onboard_endpoint_direction(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    aliases = {
        "send": "send_only",
        "receive": "receive_only",
        "both": "send_receive",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"send_only", "receive_only", "send_receive"}:
        raise ValueError(
            "direction must be one of: send, receive, both, "
            "send_only, receive_only, send_receive."
        )
    return normalized


def _onboard_reply_policy(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    aliases = {
        "standard": "source_handle_required",
        "manual": "source_handle_optional",
        "none": "message_only",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {
        "message_only",
        "source_handle_optional",
        "source_handle_required",
    }:
        raise ValueError(
            "defaultReplyPolicy must be one of: standard, manual, none, "
            "message_only, source_handle_optional, source_handle_required."
        )
    return normalized


def _provider_session_id_field(provider: str) -> str:
    return {
        "claude": "claudeSessionUuid",
        "codex": "codexSessionId",
        "hermes": "hermesSessionId",
        "deepseek_harness": "deepseekHarnessSessionId",
    }[provider]


def _provider_session_handles(
    application: LocalPlatformApplication,
    *,
    workspace_id: str,
    provider: str,
    agent_id: str | None,
) -> list[Mapping[str, object]]:
    if provider == "claude":
        return [
            dict(handle)
            for handle in application.list_claude_session_handles(
                workspace_id=workspace_id,
                agent_id=agent_id,
            )["claudeSessionHandles"]
        ]
    if provider == "codex":
        return [
            dict(handle)
            for handle in application.list_codex_session_handles(
                workspace_id=workspace_id,
                agent_id=agent_id,
            )["codexSessionHandles"]
        ]
    if provider == "hermes":
        return [
            dict(handle)
            for handle in application.list_hermes_session_handles(
                workspace_id=workspace_id,
                agent_id=agent_id,
            )["hermesSessionHandles"]
        ]
    if provider == "deepseek_harness":
        return [
            dict(handle)
            for handle in application.list_deepseek_harness_session_handles(
                workspace_id=workspace_id,
                agent_id=agent_id,
            )["deepseekHarnessSessionHandles"]
        ]
    raise ValueError(
        "provider must be one of: claude, codex, hermes, deepseek_harness."
    )


def _provider_handle_matches(
    handle: Mapping[str, object],
    *,
    agent_id: str,
    session_field: str,
    session_id: str,
) -> bool:
    return (
        handle.get("agentId") == agent_id
        and handle.get(session_field) == session_id
        and handle.get("state", "active") == "active"
    )


def _agent_endpoint_login_metadata(
    metadata: Mapping[str, object] | None,
    *,
    allow_source_endpoint_aliases: Sequence[str] = (),
    allow_source_agent_ids: Sequence[str] = (),
    allow_source_handle_ids: Sequence[str] = (),
    block_source_endpoint_aliases: Sequence[str] = (),
    block_source_agent_ids: Sequence[str] = (),
    block_source_handle_ids: Sequence[str] = (),
) -> Mapping[str, object] | None:
    merged = dict(metadata or {})
    existing = merged.get("contactPolicyProfile")
    existing_profile = dict(existing) if isinstance(existing, MappingABC) else {}
    profile = {
        **existing_profile,
        "schema": "agent_endpoint_contact_policy_profile.v1",
        "allowedSourceEndpointAliases": _merged_texts(
            existing_profile.get("allowedSourceEndpointAliases"),
            allow_source_endpoint_aliases,
            normalize_alias=True,
        ),
        "allowedSourceAgentIds": _merged_texts(
            existing_profile.get("allowedSourceAgentIds"),
            allow_source_agent_ids,
        ),
        "allowedSourceProviderHandleIds": _merged_texts(
            existing_profile.get("allowedSourceProviderHandleIds"),
            allow_source_handle_ids,
        ),
        "blockedSourceEndpointAliases": _merged_texts(
            existing_profile.get("blockedSourceEndpointAliases"),
            block_source_endpoint_aliases,
            normalize_alias=True,
        ),
        "blockedSourceAgentIds": _merged_texts(
            existing_profile.get("blockedSourceAgentIds"),
            block_source_agent_ids,
        ),
        "blockedSourceProviderHandleIds": _merged_texts(
            existing_profile.get("blockedSourceProviderHandleIds"),
            block_source_handle_ids,
        ),
    }
    compact_profile = {
        key: value
        for key, value in profile.items()
        if key == "schema" or (isinstance(value, tuple) and value)
    }
    if len(compact_profile) == 1:
        return merged or None
    merged["contactPolicyProfile"] = compact_profile
    return merged


def _merged_texts(
    existing: object,
    extra: Sequence[str],
    *,
    normalize_alias: bool = False,
) -> tuple[str, ...]:
    values: list[str] = []
    for value in _text_tuple(existing) + tuple(extra):
        normalized = (
            normalize_agent_endpoint_alias(value)
            if normalize_alias
            else _required_list_text(value)
        )
        if normalized not in values:
            values.append(normalized)
    return tuple(values)


def _required_list_text(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("contact policy values must be non-empty strings.")
    return stripped


def _text_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("contact policy lists must be arrays of strings.")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("contact policy lists must be arrays of strings.")
        result.append(item)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class _DispatchEndpointAliasResolution:
    source_agent_id: str
    target_agent_id: str
    reply_policy: str
    source_handle_id: str | None = None
    target_handle_id: str | None = None
    target_provider: str | None = None
    source_endpoint: Mapping[str, object] | None = None
    target_endpoint: Mapping[str, object] | None = None
    reply_policy_source: str = "default"
    reply_reachability: Mapping[str, object] | None = None
    contact_policy_decision: Mapping[str, object] | None = None

    def to_metadata(self) -> Mapping[str, object]:
        return {
            "schema": "agent_dispatch_endpoint_alias_resolution.v1",
            "sourceEndpointAliasResolved": self.source_endpoint is not None,
            "targetEndpointAliasResolved": self.target_endpoint is not None,
            "sourceEndpoint": dict(self.source_endpoint or {}),
            "targetEndpoint": dict(self.target_endpoint or {}),
            "sourceAgentId": self.source_agent_id,
            "targetAgentId": self.target_agent_id,
            "sourceHandleId": self.source_handle_id,
            "targetHandleId": self.target_handle_id,
            "targetProvider": self.target_provider,
            "replyPolicy": self.reply_policy,
            "replyPolicySource": self.reply_policy_source,
            "replyReachability": dict(self.reply_reachability or {}),
            "contactPolicyDecision": dict(self.contact_policy_decision or {}),
        }


def _resolve_dispatch_acting_endpoint_alias(
    *,
    acting_endpoint_alias: str | None,
    from_endpoint_alias: str | None,
) -> tuple[str | None, str]:
    acting = (
        normalize_agent_endpoint_alias(acting_endpoint_alias)
        if acting_endpoint_alias is not None
        else None
    )
    legacy = (
        normalize_agent_endpoint_alias(from_endpoint_alias)
        if from_endpoint_alias is not None
        else None
    )
    if acting is not None and legacy is not None and acting != legacy:
        raise ValueError(
            "--as and --from identify different source endpoint aliases; "
            "provide one source identity or make both values match."
        )
    if acting is not None:
        return acting, "as_and_from" if legacy is not None else "as"
    if legacy is not None:
        return legacy, "legacy_from"
    return None, "explicit_ids"


def _agent_dispatch_acting_identity(
    endpoint_resolution: _DispatchEndpointAliasResolution,
    *,
    input_source: str,
) -> Mapping[str, object]:
    endpoint = dict(endpoint_resolution.source_endpoint or {})
    return {
        "schema": "agent_dispatch_acting_identity.v1",
        "alias": endpoint.get("alias"),
        "agentId": endpoint_resolution.source_agent_id,
        "providerHandleId": endpoint_resolution.source_handle_id,
        "provider": endpoint.get("provider"),
        "inputSource": input_source,
        "explicitlySupplied": True,
        "automaticallyDetectedCurrentSession": False,
        "callerAuthenticated": False,
        "credentialVerified": False,
        "sourceOverrideAllowed": True,
        "meaning": (
            "This is the caller-supplied Beacon source identity used for routing. "
            "It is an error-prevention aid, not authentication or impersonation protection."
        ),
    }


def _agent_dispatch_route_summary(
    *,
    workspace_id: str,
    endpoint_resolution: _DispatchEndpointAliasResolution,
    acting_identity: Mapping[str, object],
    preview_only: bool,
) -> Mapping[str, object]:
    source_endpoint = dict(endpoint_resolution.source_endpoint or {})
    target_endpoint = dict(endpoint_resolution.target_endpoint or {})
    return {
        "schema": "agent_dispatch_route_summary.v1",
        "workspaceId": workspace_id,
        "previewOnly": preview_only,
        "source": {
            "alias": source_endpoint.get("alias"),
            "agentId": endpoint_resolution.source_agent_id,
            "providerHandleId": endpoint_resolution.source_handle_id,
            "provider": source_endpoint.get("provider"),
        },
        "target": {
            "alias": target_endpoint.get("alias"),
            "agentId": endpoint_resolution.target_agent_id,
            "providerHandleId": endpoint_resolution.target_handle_id,
            "provider": (
                target_endpoint.get("provider")
                or endpoint_resolution.target_provider
            ),
        },
        "replyPolicy": endpoint_resolution.reply_policy,
        "replyPolicySource": endpoint_resolution.reply_policy_source,
        "contactDecision": dict(
            endpoint_resolution.contact_policy_decision or {}
        ),
        "directionAndBindingValidated": True,
        "actingIdentity": dict(acting_identity),
        "identityBoundary": {
            "schema": "agent_dispatch_identity_boundary.v1",
            "callerAuthenticated": False,
            "credentialVerified": False,
            "automaticCurrentSessionDetection": False,
            "sourceIdentityUserSupplied": True,
            "securityMeaning": (
                "Beacon validates workspace endpoint bindings and directions, "
                "but does not authenticate the process invoking this command."
            ),
        },
    }


def _normalize_dispatch_reply_policy(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    valid = {
        "message_only",
        "source_handle_optional",
        "source_handle_required",
    }
    if normalized not in valid:
        raise ValueError(
            "replyPolicy must be one of: message_only, "
            "source_handle_optional, source_handle_required."
        )
    return normalized


def _contact_policy_profile(
    endpoint: Mapping[str, object],
) -> Mapping[str, tuple[str, ...]]:
    metadata = endpoint.get("metadata")
    profiles: list[Mapping[str, object]] = []
    if isinstance(metadata, MappingABC):
        for key in ("contactPolicyProfile", "contactAllowlist"):
            value = metadata.get(key)
            if isinstance(value, MappingABC):
                profiles.append(value)
        profiles.append(metadata)
    merged: dict[str, tuple[str, ...]] = {}
    for output_key, input_keys, normalize_alias in (
        (
            "allowedSourceEndpointAliases",
            ("allowedSourceEndpointAliases", "allowSourceEndpointAliases"),
            True,
        ),
        (
            "allowedSourceAgentIds",
            ("allowedSourceAgentIds", "allowSourceAgentIds"),
            False,
        ),
        (
            "allowedSourceProviderHandleIds",
            (
                "allowedSourceProviderHandleIds",
                "allowedSourceHandleIds",
                "allowSourceProviderHandleIds",
                "allowSourceHandleIds",
            ),
            False,
        ),
        (
            "blockedSourceEndpointAliases",
            ("blockedSourceEndpointAliases", "blockSourceEndpointAliases"),
            True,
        ),
        (
            "blockedSourceAgentIds",
            ("blockedSourceAgentIds", "blockSourceAgentIds"),
            False,
        ),
        (
            "blockedSourceProviderHandleIds",
            (
                "blockedSourceProviderHandleIds",
                "blockedSourceHandleIds",
                "blockSourceProviderHandleIds",
                "blockSourceHandleIds",
            ),
            False,
        ),
    ):
        values: list[str] = []
        for profile in profiles:
            for key in input_keys:
                for value in _text_tuple(profile.get(key)):
                    normalized = (
                        normalize_agent_endpoint_alias(value)
                        if normalize_alias
                        else _required_list_text(value)
                    )
                    if normalized not in values:
                        values.append(normalized)
        merged[output_key] = tuple(values)
    return merged


def _contact_policy_source_facts(
    source_endpoint: Mapping[str, object] | None,
) -> Mapping[str, object]:
    if source_endpoint is None:
        return {
            "sourceEndpointAlias": None,
            "sourceAgentId": None,
            "sourceProviderHandleId": None,
        }
    return {
        "sourceEndpointAlias": source_endpoint.get("alias"),
        "sourceAgentId": source_endpoint.get("agentId"),
        "sourceProviderHandleId": source_endpoint.get("providerHandleId"),
    }


def _contact_policy_has_rules(
    profile: Mapping[str, tuple[str, ...]],
    prefix: str,
) -> bool:
    return any(values for key, values in profile.items() if key.startswith(prefix))


def _matched_contact_policy_rules(
    profile: Mapping[str, tuple[str, ...]],
    *,
    source_facts: Mapping[str, object],
    prefix: str,
) -> tuple[Mapping[str, object], ...]:
    mappings = (
        ("SourceEndpointAliases", "sourceEndpointAlias"),
        ("SourceAgentIds", "sourceAgentId"),
        ("SourceProviderHandleIds", "sourceProviderHandleId"),
    )
    matches: list[Mapping[str, object]] = []
    for suffix, fact_key in mappings:
        profile_key = f"{prefix}{suffix}"
        source_value = source_facts.get(fact_key)
        if not isinstance(source_value, str):
            continue
        if source_value in profile.get(profile_key, ()):
            matches.append(
                {
                    "field": profile_key,
                    "sourceFact": fact_key,
                    "value": source_value,
                }
            )
    return tuple(matches)


def _dispatch_contact_policy_decision(
    *,
    source_endpoint: Mapping[str, object] | None,
    target_endpoint: Mapping[str, object] | None,
    reply_policy: str,
) -> Mapping[str, object]:
    source_facts = _contact_policy_source_facts(source_endpoint)
    if target_endpoint is None:
        return {
            "schema": "agent_dispatch_contact_policy_decision.v1",
            "targetEndpointAliasResolved": False,
            "targetContactPolicy": None,
            "decision": "not_applicable",
            "requiresSourceEndpoint": False,
            "sourceEndpointAliasResolved": source_endpoint is not None,
            "sourceFacts": source_facts,
        }
    contact_policy = str(target_endpoint.get("contactPolicy") or "open")
    if contact_policy == "block_all":
        raise ValueError("target endpoint contactPolicy blocks incoming dispatch.")
    contact_profile = _contact_policy_profile(target_endpoint)
    matched_block = _matched_contact_policy_rules(
        contact_profile,
        source_facts=source_facts,
        prefix="blocked",
    )
    if matched_block:
        raise ValueError("target endpoint contactPolicy blocks source endpoint.")
    requires_source_endpoint = contact_policy == "contacts_only"
    if requires_source_endpoint and source_endpoint is None:
        raise ValueError(
            "target endpoint contactPolicy=contacts_only requires a source "
            "endpoint alias."
        )
    matched_allow = _matched_contact_policy_rules(
        contact_profile,
        source_facts=source_facts,
        prefix="allowed",
    )
    allowlist_configured = _contact_policy_has_rules(contact_profile, "allowed")
    blocklist_configured = _contact_policy_has_rules(contact_profile, "blocked")
    if requires_source_endpoint and allowlist_configured and not matched_allow:
        raise ValueError(
            "target endpoint contactPolicy=contacts_only does not allow source "
            "endpoint."
        )
    if reply_policy != "message_only" and source_endpoint is None:
        raise ValueError(
            "source endpoint alias is required for reply-reachable endpoint dispatch."
        )
    return {
        "schema": "agent_dispatch_contact_policy_decision.v1",
        "targetEndpointAliasResolved": True,
        "targetContactPolicy": contact_policy,
        "decision": "allowed",
        "requiresSourceEndpoint": requires_source_endpoint,
        "sourceEndpointAliasResolved": source_endpoint is not None,
        "allowlistConfigured": allowlist_configured,
        "blocklistConfigured": blocklist_configured,
        "matchedAllowlistRules": matched_allow,
        "matchedBlocklistRules": matched_block,
        "sourceFacts": source_facts,
    }


def _dispatch_reply_reachability(
    *,
    source_endpoint: Mapping[str, object] | None,
    target_endpoint: Mapping[str, object] | None,
    source_handle_id: str | None,
    reply_policy: str,
) -> Mapping[str, object]:
    reply_required = reply_policy != "message_only"
    reply_reachable = (
        not reply_required
        or (source_endpoint is not None and source_handle_id is not None)
    )
    return {
        "schema": "agent_dispatch_reply_reachability.v1",
        "replyPolicy": reply_policy,
        "replyRequired": reply_required,
        "replyReachable": reply_reachable,
        "sourceEndpointAliasResolved": source_endpoint is not None,
        "sourceHandleResolved": source_handle_id is not None,
        "targetEndpointAliasResolved": target_endpoint is not None,
    }


@dataclass(frozen=True, slots=True)
class _DiscoveredEndpointLoginSelection:
    record: Mapping[str, object]
    selection_method: str
    cwd_matched: bool = False

    @classmethod
    def explicit(
        cls,
        record: Mapping[str, object],
    ) -> "_DiscoveredEndpointLoginSelection":
        return cls(
            record=record,
            selection_method="explicit_session_id",
            cwd_matched=False,
        )

    def to_metadata(self) -> Mapping[str, object]:
        return {
            "schema": "agent_endpoint_login_discovery_selection.v1",
            "selectionMethod": self.selection_method,
            "cwdMatched": self.cwd_matched,
            "agentRuntime": self.record.get("agentRuntime"),
            "sessionId": self.record.get("sessionId"),
            "registrationReady": self.record.get("registrationReady"),
            "currentSessionMatch": self.record.get("currentSessionMatch"),
            "providerAccountRead": bool(self.record.get("providerAccountRead")),
            "turnSnippetRead": bool(self.record.get("turnSnippetRead")),
        }


def _select_discovered_endpoint_login_session(
    discovery: Mapping[str, object],
    *,
    provider: str,
    cwd: str | None,
) -> _DiscoveredEndpointLoginSelection:
    normalized_provider = normalize_agent_endpoint_provider(provider)
    if normalized_provider is None:
        raise ValueError("provider must be one of: claude, codex, hermes.")
    ready_records = [
        dict(record)
        for record in discovery.get("agentSessions", ())
        if isinstance(record, MappingABC)
        and record.get("agentRuntime") == normalized_provider
        and bool(record.get("registrationReady"))
    ]
    resolved_cwd = _optional_text(cwd)
    if resolved_cwd is not None:
        cwd_matches = [
            record for record in ready_records if record.get("cwd") == resolved_cwd
        ]
        if len(cwd_matches) == 1:
            return _DiscoveredEndpointLoginSelection(
                record=cwd_matches[0],
                selection_method="unique_cwd_match",
                cwd_matched=True,
            )
        if len(cwd_matches) > 1:
            raise ValueError(
                "multiple registration-ready discovered sessions matched cwd; "
                "pass --session-id."
            )
        raise ValueError(
            "no registration-ready discovered session matched cwd; pass --session-id "
            "or adjust --cwd."
        )
    if len(ready_records) == 1:
        return _DiscoveredEndpointLoginSelection(
            record=ready_records[0],
            selection_method="unique_registration_ready",
            cwd_matched=False,
        )
    if not ready_records:
        raise ValueError("no registration-ready discovered sessions found.")
    raise ValueError(
        "multiple registration-ready discovered sessions found; pass --session-id."
    )


def _registered_provider_handle_id(
    registered: Mapping[str, object],
    provider: str,
) -> str:
    handle = _registered_provider_handle_metadata(registered, provider)
    value = handle.get("handleId")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("registered provider handleId is missing.")
    return value


def _registered_provider_handle_metadata(
    registered: Mapping[str, object],
    provider: str,
) -> Mapping[str, object]:
    key_by_provider = {
        "claude": "claudeSessionHandle",
        "codex": "codexSessionHandle",
        "hermes": "hermesSessionHandle",
        "deepseek_harness": "deepseekHarnessSessionHandle",
    }
    key = key_by_provider.get(provider)
    if key is None:
        raise ValueError(
            "provider must be one of: claude, codex, hermes, deepseek_harness."
        )
    handle = registered.get(key)
    if not isinstance(handle, MappingABC):
        raise ValueError("registered provider handle is missing.")
    return dict(handle)


def _deepseek_harness_handle_binding(
    handle: Mapping[str, object],
) -> Mapping[str, object]:
    metadata = handle.get("metadata")
    binding = metadata.get("runtimeBinding") if isinstance(metadata, MappingABC) else None
    if not isinstance(binding, MappingABC):
        raise ValueError("DeepSeek Harness runtime binding is missing.")
    for key in (
        "runtimeId",
        "generationId",
        "runtimeStatePath",
        "runtimeTokenPath",
        "runtimeSpecPath",
    ):
        value = binding.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"DeepSeek Harness runtime binding {key} is missing.")
    if binding.get("dshSessionId") != handle.get("deepseekHarnessSessionId"):
        raise ValueError("DeepSeek Harness runtime/session identity mismatch.")
    return dict(binding)


def _endpoint_reference(
    endpoint: Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    if endpoint is None:
        return None
    return {
        "endpointId": endpoint.get("endpointId"),
        "alias": endpoint.get("alias"),
        "agentId": endpoint.get("agentId"),
        "provider": endpoint.get("provider"),
        "providerHandleId": endpoint.get("providerHandleId"),
        "direction": endpoint.get("direction"),
        "defaultReplyPolicy": endpoint.get("defaultReplyPolicy"),
        "contactPolicy": endpoint.get("contactPolicy"),
        "state": endpoint.get("state"),
    }


def _required_endpoint_text(endpoint: Mapping[str, object], key: str) -> str:
    value = endpoint.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"agent endpoint {key} is missing.")
    return value.strip()


def _require_active_endpoint(endpoint: Mapping[str, object], role: str) -> None:
    if endpoint.get("state") != "active":
        raise ValueError(f"{role} endpoint is not active.")


def _require_active_endpoint_provider_handle(
    endpoint: Mapping[str, object],
    provider_handle: object,
    role: str,
) -> None:
    if not isinstance(provider_handle, MappingABC):
        raise ValueError(f"{role} endpoint provider handle not found.")
    if provider_handle.get("state") != "active":
        raise ValueError(f"{role} endpoint provider handle is not active.")
    if provider_handle.get("handleId") != endpoint.get("providerHandleId"):
        raise ValueError(f"{role} endpoint provider handleId does not match.")
    if provider_handle.get("agentId") != endpoint.get("agentId"):
        raise ValueError(f"{role} endpoint provider handle agentId does not match.")


def _require_endpoint_direction(
    endpoint: Mapping[str, object],
    role: str,
    *,
    allowed: str,
) -> None:
    direction = endpoint.get("direction")
    if allowed == "send" and direction == "receive_only":
        raise ValueError("source endpoint direction does not allow sending.")
    if allowed == "receive" and direction == "send_only":
        raise ValueError("target endpoint direction does not allow receiving.")
    if direction not in ("send_only", "receive_only", "send_receive"):
        raise ValueError(f"{role} endpoint direction is invalid.")


def _resolve_endpoint_text_conflict(
    *,
    explicit: str | None,
    resolved: str,
    role: str,
    field_name: str,
) -> str:
    if explicit is not None and explicit != resolved:
        raise ValueError(f"{role} {field_name} conflicts with explicit {field_name}.")
    return resolved
