from __future__ import annotations

from collections.abc import Mapping as MappingABC
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
from typing import Callable, Mapping, Sequence
from uuid import uuid4

from agent_os.application.services.agent_runtime_profile import AgentRuntimeProfile
from agent_os.application.services.agent_runtime_permission_read_model import (
    AgentRuntimePermissionView,
)
from agent_os.application.services.agent_activation import (
    AgentActivationGrant,
    AgentActivationMode,
    AgentActivationState,
    AgentActivityBudget,
    AgentConnectionSurface,
    AgentStopReason,
    agent_activation_interface_metadata,
    dormant_agent_activation_metadata,
)
from agent_os.application.services.agent_delegated_wake import (
    DelegatedWakeDenyReason,
    DelegatedWakeGrant,
    DelegatedWakeGrantMode,
    DelegatedWakeGrantState,
    delegated_wake_interface_metadata,
)
from agent_os.application.services.agent_exchange import (
    agent_exchange_interface_metadata,
    attach_agent_exchange_metadata,
)
from agent_os.application.services.agent_endpoint import (
    AgentEndpointRecord,
    AgentEndpointState,
    normalize_agent_endpoint_alias,
    normalize_agent_endpoint_provider,
)
from agent_os.application.services.agent_exchange_request import (
    AgentExchangeAuthorizationMode,
    AgentExchangeFollowUpPolicy,
    AgentExchangeRequest,
    AgentExchangeRequestKind,
    AgentExchangeRequestPolicy,
    AgentExchangeRequestStatus,
    AgentExchangeRequestTerminalReason,
    AgentExchangeSubRequestPolicy,
    AgentExchangeThread,
    AgentExchangeThreadStatus,
    AgentExchangeThreadTerminalReason,
    AgentExchangeThreadVisibility,
    agent_exchange_request_interface_metadata,
)
from agent_os.application.services.agent_dispatch import (
    AgentDispatchLeaseRecord,
    AgentDispatchLeaseState,
    AgentDispatchRecord,
    AgentDispatchReplyPolicy,
    AgentDispatchStatus,
)
from agent_os.application.services.agent_provider_runtime_status import (
    build_agent_provider_runtime_status,
    normalize_provider_runtime_status_read_policy,
)
from agent_os.application.services.agent_wake import (
    AgentWakeChildProcessPolicy,
    AgentWakeDeliveryRecord,
    AgentWakeDeliveryStatus,
    AgentWakeMode,
    AgentWakeProfile,
    AgentWakeTicket,
    agent_wake_interface_metadata,
    render_safe_command_argv,
)
from agent_os.application.services.claude_registered_session import (
    ClaudeRegisteredSessionActivationAttempt,
    ClaudeRegisteredSessionActivationStatus,
    ClaudeRegisteredSessionHandle,
    ClaudeRegisteredSessionHandleState,
    build_claude_activation_stdin,
    claude_output_mentions_session,
    extract_claude_stream_json_response,
    render_claude_resume_argv,
    resolve_claude_executable,
    summarize_process_text,
    truncate_auto_captured_response,
)
from agent_os.application.services.codex_registered_session import (
    CodexGitRepoCheckPolicy,
    CodexRegisteredSessionActivationAttempt,
    CodexRegisteredSessionActivationStatus,
    CodexRegisteredSessionHandle,
    CodexRegisteredSessionHandleState,
    build_codex_activation_stdin,
    classify_codex_activation_failure,
    classify_codex_command_exit_failure,
    codex_failure_guidance,
    codex_failure_retryable,
    codex_output_mentions_session,
    extract_codex_json_response,
    render_codex_exec_resume_argv,
    normalize_codex_git_repo_check_policy,
    resolve_codex_executable,
    summarize_process_text as summarize_codex_process_text,
    truncate_auto_captured_response as truncate_codex_auto_captured_response,
)
from agent_os.application.services.hermes_registered_session import (
    HermesRegisteredSessionActivationAttempt,
    HermesRegisteredSessionActivationStatus,
    HermesRegisteredSessionHandle,
    HermesRegisteredSessionHandleState,
    build_hermes_activation_query,
    classify_hermes_activation_failure,
    evaluate_hermes_session_continuity,
    extract_hermes_chat_response,
    hermes_failure_retryable,
    render_hermes_chat_resume_argv,
    resolve_hermes_executable,
    summarize_process_text as summarize_hermes_process_text,
    truncate_auto_captured_response as truncate_hermes_auto_captured_response,
)
from agent_os.application.services.project_directory_coordination import (
    ProjectDirectoryAccessIntent,
    ProjectDirectoryCommitPolicy,
    ProjectDirectoryCoordinationRecord,
    ProjectDirectoryDirtyState,
    calculate_project_directory_overlap,
    project_directory_coordination_interface_metadata,
)
from agent_os.domain.entities.agent import AgentCapability, AgentRegistration
from agent_os.domain.entities.context import (
    ContextUpdateInfo,
    ContextUpdateKind,
    ProjectSharedContext,
)
from agent_os.domain.entities.conversation import (
    ConversationMessage,
    ConversationMessageRole,
    ConversationSession,
    ConversationStatus,
)
from agent_os.domain.entities.task import IssueContext, TaskContext
from agent_os.domain.entities.workspace import ProjectWorkspace, WorkspaceStatus
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextId,
    ContextUpdateId,
    ConversationId,
    ConversationMessageId,
    FileOperationId,
    IssueId,
    PlatformEventId,
    PlatformRunSessionId,
    TaskId,
    WorkspaceId,
)
from agent_os.infrastructure.persistence.context_update_events import (
    ContextUpdateEventRecorderPort,
)
from agent_os.infrastructure.persistence.event_log import (
    PlatformEventKind,
    PlatformEventLogEntry,
    PlatformEventLogPort,
    PlatformEventRecord,
)
from agent_os.infrastructure.persistence.conversations import (
    ConversationMessageReaderPort,
    ConversationMessageRecord,
    ConversationMessageWriterPort,
    ConversationSessionReaderPort,
    ConversationSessionRecord,
    ConversationSessionWriterPort,
)
from agent_os.infrastructure.persistence.file_operation_records import (
    FileOperationRecordEntry,
    FileOperationRecordReaderPort,
)
from agent_os.infrastructure.persistence.invocation_records import (
    AgentInvocationRecordEntry,
    AgentInvocationRecordReaderPort,
)
from agent_os.infrastructure.persistence.materialized_state import (
    AgentRegistrationStateReaderPort,
    AgentRegistrationStateRecord,
    AgentRegistrationStateWriterPort,
    ContextStateReaderPort,
    ContextStateRecord,
    ContextStateWriterPort,
    IssueStateReaderPort,
    IssueStateRecord,
    TaskStateReaderPort,
    TaskStateRecord,
    WorkspaceStateReaderPort,
    WorkspaceStateRecord,
    WorkspaceStateWriterPort,
)


_AGENT_DISPATCH_DAEMON_STATES = {
    "not_running",
    "starting",
    "running",
    "failed",
    "exited",
}

_AGENT_DISPATCH_DAEMON_RUNNING_STATES = {"starting", "running"}

STDOUT_FALLBACK_MEANING = (
    "stdout_auto_capture means Beacon captured the target provider process "
    "stdout/stderr response text. It is not private reasoning, hidden chain of "
    "thought, or a full provider transcript."
)

STANDARD_RESPOND_MEANING = (
    "standard_respond means the target agent answered through the platform "
    "agent-exchange-request-respond command/API."
)


@dataclass(slots=True)
class LocalPlatformOperationService:
    """Local API-wrap-ready operation surface over persisted platform state."""

    workspace_reader: WorkspaceStateReaderPort
    context_reader: ContextStateReaderPort
    context_update_recorder: ContextUpdateEventRecorderPort
    event_log_reader: PlatformEventLogPort
    agent_invocation_reader: AgentInvocationRecordReaderPort
    file_operation_reader: FileOperationRecordReaderPort
    conversation_session_reader: ConversationSessionReaderPort
    conversation_message_reader: ConversationMessageReaderPort
    agent_registration_reader: AgentRegistrationStateReaderPort
    task_reader: TaskStateReaderPort
    issue_reader: IssueStateReaderPort
    workspace_writer: WorkspaceStateWriterPort
    context_writer: ContextStateWriterPort
    agent_registration_writer: AgentRegistrationStateWriterPort
    conversation_session_writer: ConversationSessionWriterPort
    conversation_message_writer: ConversationMessageWriterPort

    def list_workspaces(self) -> Mapping[str, object]:
        return {
            "workspaces": [
                workspace_state_record_payload(record)
                for record in self.workspace_reader.list_workspace_states()
            ]
        }

    def get_workspace(self, workspace_id: WorkspaceId | str) -> Mapping[str, object]:
        record = self.workspace_reader.get_workspace_state(_workspace_id(workspace_id))
        return {
            "workspace": (
                workspace_state_record_payload(record)
                if record is not None
                else None
            )
        }

    def get_context(self, workspace_id: WorkspaceId | str) -> Mapping[str, object]:
        record = self.context_reader.get_context_state(_workspace_id(workspace_id))
        return {
            "context": (
                context_state_record_payload(record)
                if record is not None
                else None
            )
        }

    def list_context_updates(
        self,
        workspace_id: WorkspaceId | str,
        *,
        limit: int = 20,
        offset: int = 0,
        update_kind: ContextUpdateKind | str | None = None,
    ) -> Mapping[str, object]:
        if limit < 0:
            raise ValueError("limit must be greater than or equal to 0.")
        if offset < 0:
            raise ValueError("offset must be greater than or equal to 0.")

        record = self.context_reader.get_context_state(_workspace_id(workspace_id))
        if record is None:
            return {
                "context": None,
                "contextUpdates": [],
                "count": 0,
                "totalCount": 0,
                "limit": limit,
                "offset": offset,
                "order": "newest_first",
            }

        resolved_kind = (
            _context_update_kind(update_kind)
            if update_kind is not None
            else None
        )
        indexed_updates = tuple(
            (index, entry)
            for index, entry in enumerate(
                self._context_update_event_entries(record.context.workspace_id)
            )
        )
        if resolved_kind is not None:
            indexed_updates = tuple(
                (index, entry)
                for index, entry in indexed_updates
                if entry.record.payload.get("update_kind") == resolved_kind.value
            )
        ordered_updates = tuple(reversed(indexed_updates))
        selected_updates = ordered_updates[offset : offset + limit]

        return {
            "context": context_state_record_payload(record),
            "contextUpdates": [
                context_update_event_payload(entry, append_index=index)
                for index, entry in selected_updates
            ],
            "count": len(selected_updates),
            "totalCount": len(indexed_updates),
            "limit": limit,
            "offset": offset,
            "order": "newest_first",
        }

    def get_context_update(
        self,
        workspace_id: WorkspaceId | str,
        *,
        update_id: ContextUpdateId | str,
    ) -> Mapping[str, object]:
        record = self.context_reader.get_context_state(_workspace_id(workspace_id))
        if record is None:
            return {
                "context": None,
                "contextUpdate": None,
            }

        resolved_update_id = _context_update_id(update_id)
        for index, entry in enumerate(
            self._context_update_event_entries(record.context.workspace_id)
        ):
            if entry.record.aggregate_id == resolved_update_id.value:
                return {
                    "context": context_state_record_payload(record),
                    "contextUpdate": context_update_event_payload(
                        entry,
                        append_index=index,
                    ),
                }

        return {
            "context": context_state_record_payload(record),
            "contextUpdate": None,
        }

    def create_workspace(
        self,
        *,
        display_name: str,
        root_path: str,
        workspace_id: WorkspaceId | str | None = None,
        context_id: ContextId | str | None = None,
        agent_id: AgentId | str | None = None,
        agent_name: str = "Local Deterministic Agent",
        agent_description: str = "Handles deterministic local single-turn requests.",
        agent_capability_name: str = "single-turn-status",
        agent_capability_description: str = "Captures local single-turn requests.",
        context_materialized_state: Mapping[str, object] | None = None,
        default_model: str = "deterministic-placeholder",
        created_at: datetime | None = None,
        workspace_metadata: Mapping[str, object] | None = None,
        context_metadata: Mapping[str, object] | None = None,
        agent_runtime_config: Mapping[str, object] | None = None,
        agent_metadata: Mapping[str, object] | None = None,
        workspace_event_id: PlatformEventId | str | None = None,
        agent_event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = (
            _workspace_id(workspace_id)
            if workspace_id is not None
            else WorkspaceId.new()
        )
        if self.workspace_reader.get_workspace_state(resolved_workspace_id) is not None:
            raise ValueError("workspace state already exists.")

        timestamp = created_at or _utc_now()
        workspace = ProjectWorkspace.create(
            workspace_id=resolved_workspace_id,
            display_name=display_name,
            root_path=_root_path_text(root_path),
            created_at=timestamp,
            metadata=dict(workspace_metadata or {}),
        )
        workspace_sequence = self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(workspace_event_id)
                    if workspace_event_id is not None
                    else None
                ),
                workspace_id=workspace.workspace_id,
                event_kind=PlatformEventKind.WORKSPACE_CHANGED,
                aggregate_type="workspace",
                aggregate_id=workspace.workspace_id.value,
                occurred_at=timestamp,
                payload={
                    "action": "created",
                    "workspace_id": workspace.workspace_id.value,
                    "display_name": workspace.display_name,
                    "root_path": workspace.root_path,
                    "status": workspace.status.value,
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )
        self.workspace_writer.upsert_workspace_state(
            workspace=workspace,
            source_event_sequence=workspace_sequence,
        )
        baseline = self.ensure_workspace_baseline(
            workspace.workspace_id,
            context_id=(
                _context_id(context_id)
                if context_id is not None
                else None
            ),
            agent_id=(
                _agent_id(agent_id)
                if agent_id is not None
                else None
            ),
            agent_name=agent_name,
            agent_description=agent_description,
            agent_capability_name=agent_capability_name,
            agent_capability_description=agent_capability_description,
            context_materialized_state=context_materialized_state,
            default_model=default_model,
            created_at=timestamp,
            context_metadata=context_metadata,
            agent_runtime_config=agent_runtime_config,
            agent_metadata=agent_metadata,
            context_source_event_sequence=workspace_sequence,
            agent_event_id=agent_event_id,
        )
        return {
            "workspace": self.open_workspace(workspace.workspace_id),
            "created": True,
            "workspaceSourceEventSequence": workspace_sequence,
            "baseline": baseline["baseline"],
        }

    def open_workspace(
        self,
        workspace_id: WorkspaceId | str,
    ) -> Mapping[str, object]:
        record = self._require_workspace(workspace_id)
        if record.workspace.status is WorkspaceStatus.ARCHIVED:
            raise ValueError("workspace is archived.")
        return self._workspace_overview(record)

    def archive_workspace(
        self,
        workspace_id: WorkspaceId | str,
        *,
        archived_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        record = self._require_workspace(workspace_id)
        if record.workspace.status is WorkspaceStatus.ARCHIVED:
            return {
                "workspace": self._workspace_overview(record),
                "archived": False,
                "workspaceSourceEventSequence": record.source_event_sequence,
            }

        timestamp = archived_at or _utc_now()
        archived = record.workspace.archive(archived_at=timestamp)
        sequence = self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=archived.workspace_id,
                event_kind=PlatformEventKind.WORKSPACE_CHANGED,
                aggregate_type="workspace",
                aggregate_id=archived.workspace_id.value,
                occurred_at=timestamp,
                payload={
                    "action": "archived",
                    "workspace_id": archived.workspace_id.value,
                    "status": archived.status.value,
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )
        self.workspace_writer.upsert_workspace_state(
            workspace=archived,
            source_event_sequence=sequence,
        )
        archived_record = self.workspace_reader.get_workspace_state(
            archived.workspace_id
        )
        assert archived_record is not None
        return {
            "workspace": self._workspace_overview(archived_record),
            "archived": True,
            "workspaceSourceEventSequence": sequence,
        }

    def ensure_workspace_baseline(
        self,
        workspace_id: WorkspaceId | str,
        *,
        context_id: ContextId | str | None = None,
        agent_id: AgentId | str | None = None,
        agent_name: str = "Local Deterministic Agent",
        agent_description: str = "Handles deterministic local single-turn requests.",
        agent_capability_name: str = "single-turn-status",
        agent_capability_description: str = "Captures local single-turn requests.",
        context_materialized_state: Mapping[str, object] | None = None,
        default_model: str = "deterministic-placeholder",
        created_at: datetime | None = None,
        context_metadata: Mapping[str, object] | None = None,
        agent_runtime_config: Mapping[str, object] | None = None,
        agent_metadata: Mapping[str, object] | None = None,
        context_source_event_sequence: int | None = None,
        agent_event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        workspace_record = self._require_workspace(workspace_id)
        if workspace_record.workspace.status is WorkspaceStatus.ARCHIVED:
            raise ValueError("workspace is archived.")

        workspace = workspace_record.workspace
        timestamp = created_at or _utc_now()
        context_record = self.context_reader.get_context_state(workspace.workspace_id)
        context_created = False
        if context_record is None:
            context = ProjectSharedContext.create(
                context_id=(
                    _context_id(context_id)
                    if context_id is not None
                    else _default_context_id(workspace.workspace_id)
                ),
                workspace_id=workspace.workspace_id,
                created_at=timestamp,
                materialized_state=(
                    dict(context_materialized_state)
                    if context_materialized_state is not None
                    else {"status": "open"}
                ),
                metadata=dict(context_metadata or {}),
            )
            self.context_writer.upsert_context_state(
                context=context,
                source_event_sequence=(
                    context_source_event_sequence
                    if context_source_event_sequence is not None
                    else workspace_record.source_event_sequence
                ),
            )
            context_created = True

        agent_record = None
        agent_created = False
        if agent_id is not None:
            resolved_agent_id = _agent_id(agent_id)
            agent_record = self.agent_registration_reader.get_agent_registration_state(
                resolved_agent_id
            )
            if (
                agent_record is not None
                and agent_record.registration.workspace_id != workspace.workspace_id
            ):
                raise ValueError("agent registration workspace_id does not match workspace_id.")
        else:
            existing_agents = (
                self.agent_registration_reader
                .list_agent_registration_states_by_workspace(workspace.workspace_id)
            )
            agent_record = existing_agents[0] if existing_agents else None
            resolved_agent_id = _default_agent_id(workspace.workspace_id)

        if agent_record is None:
            registration = AgentRegistration.register(
                agent_id=resolved_agent_id,
                workspace_id=workspace.workspace_id,
                name=agent_name,
                description=agent_description,
                capabilities=(
                    AgentCapability(
                        name=agent_capability_name,
                        description=agent_capability_description,
                    ),
                ),
                created_at=timestamp,
                default_model=default_model,
                tool_permissions=("workspace.read",),
                runtime_config={
                    "mode": "deterministic",
                    **dict(agent_runtime_config or {}),
                },
                metadata=dict(agent_metadata or {}),
            )
            agent_sequence = self.event_log_reader.append(
                PlatformEventRecord.create(
                    event_id=(
                        _platform_event_id(agent_event_id)
                        if agent_event_id is not None
                        else None
                    ),
                    workspace_id=workspace.workspace_id,
                    event_kind=PlatformEventKind.AGENT_REGISTRATION_CHANGED,
                    aggregate_type="agent_registration",
                    aggregate_id=registration.agent_id.value,
                    occurred_at=timestamp,
                    payload={
                        "action": "registered",
                        "agent_id": registration.agent_id.value,
                        "workspace_id": workspace.workspace_id.value,
                        "status": registration.status.value,
                        "default_model": registration.default_model,
                    },
                    metadata={"source": "local_platform_operation_service"},
                )
            )
            self.agent_registration_writer.upsert_agent_registration_state(
                registration=registration,
                source_event_sequence=agent_sequence,
            )
            agent_created = True

        return {
            "baseline": {
                "workspaceId": workspace.workspace_id.value,
                "contextCreated": context_created,
                "agentCreated": agent_created,
                "context": self.get_context(workspace.workspace_id)["context"],
                "agents": self.list_agent_registrations(workspace.workspace_id)[
                    "agents"
                ],
            }
        }

    def create_agent_registration(
        self,
        workspace_id: WorkspaceId | str,
        *,
        agent_id: AgentId | str | None = None,
        name: str,
        description: str,
        capabilities: tuple[AgentCapability | Mapping[str, object], ...] = (),
        default_model: str | None = None,
        tool_permissions: tuple[str, ...] = ("workspace.read",),
        runtime_config: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
        created_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        workspace_record = self._require_workspace(workspace_id)
        if workspace_record.workspace.status is WorkspaceStatus.ARCHIVED:
            raise ValueError("workspace is archived.")

        resolved_agent_id = (
            _agent_id(agent_id)
            if agent_id is not None
            else AgentId.new()
        )
        if (
            self.agent_registration_reader.get_agent_registration_state(
                resolved_agent_id
            )
            is not None
        ):
            raise ValueError("agent registration state already exists.")

        timestamp = created_at or _utc_now()
        registration = AgentRegistration.register(
            agent_id=resolved_agent_id,
            workspace_id=workspace_record.workspace.workspace_id,
            name=name,
            description=description,
            capabilities=_agent_capabilities(capabilities),
            created_at=timestamp,
            default_model=default_model,
            tool_permissions=tuple(tool_permissions),
            runtime_config=dict(runtime_config or {}),
            metadata=dict(metadata or {}),
        )
        profile = AgentRuntimeProfile.from_registration(registration)
        sequence = self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=registration.workspace_id,
                event_kind=PlatformEventKind.AGENT_REGISTRATION_CHANGED,
                aggregate_type="agent_registration",
                aggregate_id=registration.agent_id.value,
                occurred_at=timestamp,
                payload={
                    "action": "registered",
                    "agent_id": registration.agent_id.value,
                    "workspace_id": registration.workspace_id.value,
                    "status": registration.status.value,
                    "default_model": registration.default_model,
                    "profile_name": profile.profile_name,
                    "role_name": profile.role_name,
                    "provider_name": profile.provider_name,
                    "model_name": profile.model_name,
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )
        self.agent_registration_writer.upsert_agent_registration_state(
            registration=registration,
            source_event_sequence=sequence,
        )
        record = self.agent_registration_reader.get_agent_registration_state(
            registration.agent_id
        )
        assert record is not None
        return {
            "agent": agent_registration_state_record_payload(record),
            "created": True,
            "agentSourceEventSequence": sequence,
        }

    def append_context_update(
        self,
        workspace_id: WorkspaceId | str,
        *,
        update_kind: ContextUpdateKind | str,
        summary: str,
        update_id: ContextUpdateId | str | None = None,
        created_at: datetime | None = None,
        source_agent_id: AgentId | str | None = None,
        payload: Mapping[str, object] | None = None,
        materialized_state_patch: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
        exchange_attribution: Mapping[str, object] | None = None,
        event_id: PlatformEventId | str | None = None,
        session_id: PlatformRunSessionId | str | None = None,
        event_metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        record = self.context_reader.get_context_state(resolved_workspace_id)
        if record is None:
            raise ValueError("context state not found.")
        if record.context.workspace_id != resolved_workspace_id:
            raise ValueError(
                "context state workspace_id does not match requested workspace_id."
            )

        update_metadata = attach_agent_exchange_metadata(
            metadata,
            exchange_attribution,
        )
        self._validate_agent_exchange_activation(
            workspace_id=resolved_workspace_id,
            metadata=update_metadata,
        )
        update = ContextUpdateInfo.create(
            workspace_id=resolved_workspace_id,
            update_kind=_context_update_kind(update_kind),
            summary=summary,
            update_id=(
                _context_update_id(update_id)
                if update_id is not None
                else None
            ),
            created_at=created_at,
            source_agent_id=(
                _agent_id(source_agent_id)
                if source_agent_id is not None
                else None
            ),
            payload=dict(payload or {}),
            materialized_state_patch=dict(materialized_state_patch or {}),
            metadata=update_metadata,
        )
        recorded = self.context_update_recorder.record_context_update_event(
            context=record.context,
            update=update,
            event_id=(
                _platform_event_id(event_id)
                if event_id is not None
                else None
            ),
            session_id=(
                _platform_run_session_id(session_id)
                if session_id is not None
                else None
            ),
            metadata=dict(event_metadata or {}),
            base_update_count=record.update_count,
        )
        updated_context_record = ContextStateRecord(
            source_event_sequence=recorded.source_event_sequence,
            update_count=record.update_count + 1,
            context=recorded.context,
            metadata=recorded.context.metadata,
        )
        return {
            "contextUpdate": context_update_payload(update),
            "context": context_state_record_payload(updated_context_record),
            "sourceEventSequence": recorded.source_event_sequence,
        }

    def create_conversation(
        self,
        workspace_id: WorkspaceId | str,
        *,
        title: str,
        conversation_id: ConversationId | str | None = None,
        agent_id: AgentId | str | None = None,
        created_at: datetime | None = None,
        metadata: Mapping[str, object] | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        workspace_record = self._require_workspace(workspace_id)
        if workspace_record.workspace.status is WorkspaceStatus.ARCHIVED:
            raise ValueError("workspace is archived.")
        resolved_agent_id = (
            self._require_workspace_agent(
                workspace_record.workspace.workspace_id,
                agent_id,
            ).registration.agent_id
            if agent_id is not None
            else None
        )
        resolved_conversation_id = (
            _conversation_id(conversation_id)
            if conversation_id is not None
            else ConversationId.new()
        )
        if (
            self.conversation_session_reader.get_conversation_session(
                resolved_conversation_id
            )
            is not None
        ):
            raise ValueError("conversation session already exists.")

        timestamp = created_at or _utc_now()
        conversation = ConversationSession.create(
            conversation_id=resolved_conversation_id,
            workspace_id=workspace_record.workspace.workspace_id,
            agent_id=resolved_agent_id,
            title=title,
            created_at=timestamp,
            metadata=dict(metadata or {}),
        )
        sequence = self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=conversation.workspace_id,
                event_kind=PlatformEventKind.CONVERSATION_CHANGED,
                aggregate_type="conversation",
                aggregate_id=conversation.conversation_id.value,
                occurred_at=timestamp,
                payload={
                    "action": "created",
                    "conversation_id": conversation.conversation_id.value,
                    "workspace_id": conversation.workspace_id.value,
                    "agent_id": (
                        conversation.agent_id.value
                        if conversation.agent_id is not None
                        else None
                    ),
                    "status": conversation.status.value,
                    "title": conversation.title,
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )
        self.conversation_session_writer.upsert_conversation_session(
            conversation=conversation,
            source_event_sequence=sequence,
        )
        record = self.conversation_session_reader.get_conversation_session(
            conversation.conversation_id
        )
        assert record is not None
        return {
            "conversation": conversation_session_record_payload(record),
            "created": True,
            "conversationSourceEventSequence": sequence,
        }

    def list_conversations(
        self,
        workspace_id: WorkspaceId | str,
    ) -> Mapping[str, object]:
        return {
            "conversations": [
                conversation_session_record_payload(record)
                for record in (
                    self.conversation_session_reader
                    .list_conversation_sessions_by_workspace(
                        _workspace_id(workspace_id)
                    )
                )
            ]
        }

    def get_conversation(
        self,
        workspace_id: WorkspaceId | str,
        conversation_id: ConversationId | str,
    ) -> Mapping[str, object]:
        record = self._conversation_record_or_none(workspace_id, conversation_id)
        return {
            "conversation": (
                conversation_session_record_payload(record)
                if record is not None
                else None
            )
        }

    def archive_conversation(
        self,
        workspace_id: WorkspaceId | str,
        conversation_id: ConversationId | str,
        *,
        archived_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        workspace_record = self._require_workspace(workspace_id)
        if workspace_record.workspace.status is WorkspaceStatus.ARCHIVED:
            raise ValueError("workspace is archived.")
        record = self._require_conversation(
            workspace_record.workspace.workspace_id,
            conversation_id,
        )
        if record.conversation.status is ConversationStatus.ARCHIVED:
            return {
                "conversation": conversation_session_record_payload(record),
                "archived": False,
                "conversationSourceEventSequence": record.source_event_sequence,
            }

        timestamp = archived_at or _utc_now()
        archived = record.conversation.archive(archived_at=timestamp)
        sequence = self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=archived.workspace_id,
                event_kind=PlatformEventKind.CONVERSATION_CHANGED,
                aggregate_type="conversation",
                aggregate_id=archived.conversation_id.value,
                occurred_at=timestamp,
                payload={
                    "action": "archived",
                    "conversation_id": archived.conversation_id.value,
                    "workspace_id": archived.workspace_id.value,
                    "status": archived.status.value,
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )
        self.conversation_session_writer.upsert_conversation_session(
            conversation=archived,
            source_event_sequence=sequence,
        )
        updated = self.conversation_session_reader.get_conversation_session(
            archived.conversation_id
        )
        assert updated is not None
        return {
            "conversation": conversation_session_record_payload(updated),
            "archived": True,
            "conversationSourceEventSequence": sequence,
        }

    def append_conversation_message(
        self,
        workspace_id: WorkspaceId | str,
        conversation_id: ConversationId | str,
        *,
        role: ConversationMessageRole | str,
        content: str,
        message_id: ConversationMessageId | str | None = None,
        created_at: datetime | None = None,
        agent_id: AgentId | str | None = None,
        invocation_id: AgentInvocationId | str | None = None,
        context_update_id: ContextUpdateId | str | None = None,
        run_session_id: PlatformRunSessionId | str | None = None,
        metadata: Mapping[str, object] | None = None,
        exchange_attribution: Mapping[str, object] | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        conversation = self._require_active_conversation(workspace_id, conversation_id)
        resolved_agent_id = (
            self._require_workspace_agent(conversation.workspace_id, agent_id)
            .registration
            .agent_id
            if agent_id is not None
            else conversation.agent_id
        )
        timestamp = created_at or _utc_now()
        sequence_number = (
            self.conversation_message_reader.next_conversation_message_sequence(
                conversation.conversation_id
            )
        )
        message_metadata = attach_agent_exchange_metadata(
            metadata,
            exchange_attribution,
        )
        self._validate_agent_exchange_activation(
            workspace_id=conversation.workspace_id,
            metadata=message_metadata,
        )
        message = ConversationMessage.create(
            message_id=(
                _conversation_message_id(message_id)
                if message_id is not None
                else None
            ),
            conversation_id=conversation.conversation_id,
            workspace_id=conversation.workspace_id,
            sequence=sequence_number,
            role=_conversation_message_role(role),
            content=content,
            created_at=timestamp,
            agent_id=resolved_agent_id,
            invocation_id=(
                _agent_invocation_id(invocation_id)
                if invocation_id is not None
                else None
            ),
            context_update_id=(
                _context_update_id(context_update_id)
                if context_update_id is not None
                else None
            ),
            run_session_id=(
                _platform_run_session_id(run_session_id)
                if run_session_id is not None
                else None
            ),
            metadata=message_metadata,
        )
        event_sequence = self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=message.workspace_id,
                session_id=message.run_session_id,
                event_kind=PlatformEventKind.CONVERSATION_MESSAGE_APPENDED,
                aggregate_type="conversation_message",
                aggregate_id=message.message_id.value,
                occurred_at=timestamp,
                payload={
                    "action": "appended",
                    "message_id": message.message_id.value,
                    "conversation_id": message.conversation_id.value,
                    "workspace_id": message.workspace_id.value,
                    "sequence": message.sequence,
                    "role": message.role.value,
                    "agent_id": (
                        message.agent_id.value
                        if message.agent_id is not None
                        else None
                    ),
                    "invocation_id": (
                        message.invocation_id.value
                        if message.invocation_id is not None
                        else None
                    ),
                    "context_update_id": (
                        message.context_update_id.value
                        if message.context_update_id is not None
                        else None
                    ),
                    "run_session_id": (
                        message.run_session_id.value
                        if message.run_session_id is not None
                        else None
                    ),
                    "message_metadata": dict(message.metadata),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )
        self.conversation_message_writer.append_conversation_message(
            message=message,
            source_event_sequence=event_sequence,
        )
        record = self.conversation_message_reader.get_conversation_message(
            message.message_id
        )
        assert record is not None
        return {
            "message": conversation_message_record_payload(record),
            "messageSourceEventSequence": event_sequence,
        }

    def list_conversation_messages(
        self,
        workspace_id: WorkspaceId | str,
        conversation_id: ConversationId | str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> Mapping[str, object]:
        conversation = self._require_conversation(workspace_id, conversation_id)
        return {
            "conversation": conversation_payload(conversation.conversation),
            "messages": [
                conversation_message_record_payload(record)
                for record in self.conversation_message_reader.list_conversation_messages(
                    conversation.conversation.conversation_id,
                    limit=limit,
                    offset=offset,
                )
            ],
        }

    def agent_exchange_instructions(
        self,
        workspace_id: WorkspaceId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = (
            _workspace_id(workspace_id)
            if workspace_id is not None
            else None
        )
        if resolved_workspace_id is not None:
            self._require_workspace(resolved_workspace_id)
        return agent_exchange_interface_metadata(
            workspace_id=(
                resolved_workspace_id.value
                if resolved_workspace_id is not None
                else None
            )
        )

    def agent_exchange_request_instructions(
        self,
        workspace_id: WorkspaceId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = (
            _workspace_id(workspace_id)
            if workspace_id is not None
            else None
        )
        policy = None
        if resolved_workspace_id is not None:
            self._require_workspace(resolved_workspace_id)
            policy = self._latest_agent_exchange_request_policy(
                resolved_workspace_id
            )
        return agent_exchange_request_interface_metadata(
            workspace_id=(
                resolved_workspace_id.value
                if resolved_workspace_id is not None
                else None
            ),
            policy=policy,
        )

    def get_agent_exchange_request_policy(
        self,
        workspace_id: WorkspaceId | str,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        return {
            "agentExchangeRequestPolicy": (
                self._latest_agent_exchange_request_policy(
                    resolved_workspace_id
                ).to_metadata()
            )
        }

    def update_agent_exchange_request_policy(
        self,
        workspace_id: WorkspaceId | str,
        *,
        authorization_mode: AgentExchangeAuthorizationMode | str | None = None,
        sub_request_policy: AgentExchangeSubRequestPolicy | str | None = None,
        thread_workspace_visible: bool | None = None,
        follow_up_policy: AgentExchangeFollowUpPolicy | str | None = None,
        allowed_sub_request_agent_ids: tuple[str, ...] | None = None,
        max_request_length: int | None = None,
        max_response_length: int | None = None,
        max_response_tokens: int | None = None,
        max_turns: int | None = None,
        max_sub_request_depth: int | None = None,
        max_child_requests: int | None = None,
        auto_append_exchange_result_to_shared_context: bool | None = None,
        metadata: Mapping[str, object] | None = None,
        updated_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        workspace_record = self._require_workspace(resolved_workspace_id)
        if workspace_record.workspace.status is WorkspaceStatus.ARCHIVED:
            raise ValueError("workspace is archived.")
        if auto_append_exchange_result_to_shared_context:
            raise ValueError(
                "autoAppendExchangeResultToSharedContext is reserved and must remain false."
            )
        if allowed_sub_request_agent_ids is not None:
            for agent_id in allowed_sub_request_agent_ids:
                self._require_workspace_agent(resolved_workspace_id, agent_id)
        existing = self._latest_agent_exchange_request_policy(resolved_workspace_id)
        timestamp = updated_at or _utc_now()
        updates: dict[str, object] = {}
        if authorization_mode is not None:
            updates["authorizationMode"] = (
                authorization_mode.value
                if isinstance(authorization_mode, AgentExchangeAuthorizationMode)
                else authorization_mode
            )
        if sub_request_policy is not None:
            updates["subRequestPolicy"] = (
                sub_request_policy.value
                if isinstance(sub_request_policy, AgentExchangeSubRequestPolicy)
                else sub_request_policy
            )
        if thread_workspace_visible is not None:
            updates["threadWorkspaceVisible"] = thread_workspace_visible
        if follow_up_policy is not None:
            updates["followUpPolicy"] = (
                follow_up_policy.value
                if isinstance(follow_up_policy, AgentExchangeFollowUpPolicy)
                else follow_up_policy
            )
        if allowed_sub_request_agent_ids is not None:
            updates["allowedSubRequestAgentIds"] = tuple(allowed_sub_request_agent_ids)
        for key, value in (
            ("maxRequestLength", max_request_length),
            ("maxResponseLength", max_response_length),
            ("maxResponseTokens", max_response_tokens),
            ("maxTurns", max_turns),
            ("maxSubRequestDepth", max_sub_request_depth),
            ("maxChildRequests", max_child_requests),
        ):
            if value is not None:
                updates[key] = value
        if auto_append_exchange_result_to_shared_context is not None:
            updates["autoAppendExchangeResultToSharedContext"] = False
        if metadata is not None:
            updates["metadata"] = {
                **dict(existing.metadata),
                **dict(metadata),
            }
        policy = existing.updated_copy(
            updated_at=timestamp,
            **updates,
        )
        sequence = self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=resolved_workspace_id,
                event_kind=PlatformEventKind.AGENT_EXCHANGE_REQUEST_POLICY_CHANGED,
                aggregate_type="agent_exchange_request_policy",
                aggregate_id=resolved_workspace_id.value,
                occurred_at=timestamp,
                payload={
                    "action": "updated",
                    "policy": policy.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )
        return {
            "agentExchangeRequestPolicy": {
                **policy.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "sourceEventSequence": sequence,
            "updated": True,
        }

    def create_agent_exchange_request(
        self,
        workspace_id: WorkspaceId | str,
        *,
        source_agent_id: AgentId | str,
        target_agent_id: AgentId | str,
        request_kind: AgentExchangeRequestKind | str,
        request_summary: str,
        exchange_request_id: str | None = None,
        agent_session_id: str | None = None,
        connection_instance_id: str | None = None,
        detail_refs: tuple[str, ...] = (),
        linked_task_id: TaskId | str | None = None,
        linked_conversation_id: ConversationId | str | None = None,
        linked_activation_id: str | None = None,
        linked_delegated_wake_grant_id: str | None = None,
        parent_request_id: str | None = None,
        root_request_id: str | None = None,
        thread_id: str | None = None,
        turn_index: int | None = None,
        expires_at: datetime | None = None,
        requires_user_review: bool = False,
        metadata: Mapping[str, object] | None = None,
        created_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        workspace_record = self._require_workspace(workspace_id)
        if workspace_record.workspace.status is WorkspaceStatus.ARCHIVED:
            raise ValueError("workspace is archived.")
        resolved_workspace_id = workspace_record.workspace.workspace_id
        source_agent_record = self._require_workspace_agent(
            resolved_workspace_id,
            source_agent_id,
        )
        target_agent_record = self._require_workspace_agent(
            resolved_workspace_id,
            target_agent_id,
        )
        resolved_source_agent_id = source_agent_record.registration.agent_id
        resolved_target_agent_id = target_agent_record.registration.agent_id
        if resolved_source_agent_id == resolved_target_agent_id:
            raise ValueError("sourceAgentId and targetAgentId must not be the same agent.")
        if linked_task_id is not None:
            self._require_workspace_task(resolved_workspace_id, linked_task_id)
        resolved_conversation_id = (
            self._require_conversation(
                resolved_workspace_id,
                linked_conversation_id,
            ).conversation.conversation_id
            if linked_conversation_id is not None
            else None
        )
        if exchange_request_id is not None:
            existing = self._latest_agent_exchange_request_by_id(
                resolved_workspace_id,
                exchange_request_id,
            )
            if existing is not None and existing.is_active():
                raise ValueError("agent exchange request already exists.")
        policy = self._latest_agent_exchange_request_policy(resolved_workspace_id)
        self._validate_agent_exchange_request_authorization(
            policy=policy,
            workspace_id=resolved_workspace_id,
            source_agent_id=resolved_source_agent_id,
            target_agent_id=resolved_target_agent_id,
            linked_delegated_wake_grant_id=linked_delegated_wake_grant_id,
        )
        effective_thread_config = self._effective_agent_exchange_thread_config(
            policy=policy,
            source_agent_runtime_config=source_agent_record.registration.runtime_config,
            target_agent_runtime_config=target_agent_record.registration.runtime_config,
        )
        if effective_thread_config["maxTurns"] == -1:
            raise ValueError("maxTurns=-1 disables request creation.")
        resolved_request_id = (
            exchange_request_id
            if exchange_request_id is not None
            else f"agent-exchange-request-{uuid4()}"
        )
        parent = None
        if parent_request_id is not None:
            parent = self._require_agent_exchange_request(
                resolved_workspace_id,
                parent_request_id,
            )
            self._validate_agent_exchange_sub_request(
                policy=policy,
                workspace_id=resolved_workspace_id,
                source_agent_id=resolved_source_agent_id,
                parent_request=parent,
            )
        resolved_root_request_id = (
            root_request_id
            or (
                parent.root_request_id
                if parent is not None and parent.root_request_id is not None
                else (parent.exchange_request_id if parent is not None else resolved_request_id)
            )
        )
        resolved_thread_id = (
            thread_id
            or (
                parent.thread_id
                if parent is not None and parent.thread_id is not None
                else resolved_root_request_id
            )
        )
        existing_thread = self._latest_agent_exchange_thread_by_id(
            resolved_workspace_id,
            resolved_thread_id,
        )
        if existing_thread is not None:
            if not existing_thread.is_active():
                raise ValueError("agent exchange thread is not active.")
            self._validate_agent_exchange_thread_send_budget(
                thread=existing_thread,
                policy_max_turns=int(effective_thread_config["maxTurns"]),
            )
            self._validate_agent_exchange_thread_follow_up(
                thread=existing_thread,
                policy=policy,
                source_agent_id=resolved_source_agent_id,
                target_agent_id=resolved_target_agent_id,
            )
        elif parent is not None:
            raise ValueError("parent request thread not found.")
        resolved_turn_index = (
            turn_index
            if turn_index is not None
            else (
                (parent.turn_index + 1)
                if parent is not None
                else (
                    (
                        existing_thread.completed_turn_count
                        + existing_thread.active_request_count
                    )
                    if existing_thread is not None
                    else 0
                )
            )
        )
        timestamp = created_at or _utc_now()
        request = AgentExchangeRequest.from_mapping(
            {
                "exchangeRequestId": resolved_request_id,
                "workspaceId": resolved_workspace_id.value,
                "sourceAgentId": resolved_source_agent_id.value,
                "targetAgentId": resolved_target_agent_id.value,
                "agentSessionId": agent_session_id,
                "connectionInstanceId": connection_instance_id,
                "requestKind": (
                    request_kind.value
                    if isinstance(request_kind, AgentExchangeRequestKind)
                    else request_kind
                ),
                "requestSummary": request_summary,
                "detailRefs": tuple(detail_refs),
                "linkedTaskId": (
                    _task_id(linked_task_id).value
                    if linked_task_id is not None
                    else None
                ),
                "linkedConversationId": (
                    resolved_conversation_id.value
                    if resolved_conversation_id is not None
                    else None
                ),
                "linkedActivationId": linked_activation_id,
                "linkedDelegatedWakeGrantId": linked_delegated_wake_grant_id,
                "parentRequestId": parent_request_id,
                "rootRequestId": resolved_root_request_id,
                "threadId": resolved_thread_id,
                "turnIndex": resolved_turn_index,
                "authorizationMode": policy.authorization_mode.value,
                "subRequestPolicy": policy.sub_request_policy.value,
                "maxTurns": (
                    effective_thread_config["maxTurns"]
                    if int(effective_thread_config["maxTurns"]) > 0
                    else 0
                ),
                "maxResponseTokens": policy.max_response_tokens,
                "maxRequestLength": policy.max_request_length,
                "maxResponseLength": policy.max_response_length,
                "expiresAt": expires_at.isoformat() if expires_at else None,
                "requiresUserReview": requires_user_review,
                "autoAppendExchangeResultToSharedContext": False,
                "createdAt": timestamp,
                "updatedAt": timestamp,
                "metadata": dict(metadata or {}),
            }
        )
        sequence = self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=resolved_workspace_id,
                event_kind=PlatformEventKind.AGENT_EXCHANGE_REQUEST_CHANGED,
                aggregate_type="agent_exchange_request",
                aggregate_id=request.exchange_request_id,
                occurred_at=timestamp,
                payload={
                    "action": "created",
                    "request": request.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )
        thread_sequence = self._record_agent_exchange_thread_after_request_change(
            workspace_id=resolved_workspace_id,
            request=request,
            action="request_created",
            occurred_at=timestamp,
            policy=policy,
            effective_thread_config=effective_thread_config,
            existing_thread=existing_thread,
        )
        return {
            "apiLayer": "state-only",
            "requestApiLayer": _agent_exchange_request_api_layer(),
            "agentExchangeRequest": {
                **request.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "agentExchangeThread": self._require_agent_exchange_thread(
                resolved_workspace_id,
                resolved_thread_id,
            ).to_metadata(),
            "sourceEventSequence": sequence,
            "threadSourceEventSequence": thread_sequence,
            "created": True,
        }

    def login_agent_endpoint(
        self,
        workspace_id: WorkspaceId | str,
        *,
        agent_id: AgentId | str,
        alias: str,
        provider: str,
        provider_handle_id: str,
        endpoint_id: str | None = None,
        direction: str = "send_receive",
        default_reply_policy: AgentDispatchReplyPolicy | str = (
            AgentDispatchReplyPolicy.SOURCE_HANDLE_REQUIRED
        ),
        contact_policy: str = "open",
        created_by: str = "user",
        reason: str = "endpoint login",
        metadata: Mapping[str, object] | None = None,
        occurred_at: datetime | None = None,
    ) -> Mapping[str, object]:
        workspace_record = self._require_workspace(workspace_id)
        if workspace_record.workspace.status is WorkspaceStatus.ARCHIVED:
            raise ValueError("workspace is archived.")
        resolved_workspace_id = workspace_record.workspace.workspace_id
        agent = self._require_workspace_agent(
            resolved_workspace_id,
            agent_id,
        ).registration.agent_id
        normalized_provider = normalize_agent_endpoint_provider(provider)
        if normalized_provider is None:
            raise ValueError("provider must be one of: claude, codex, hermes.")
        provider_handle = self._require_agent_endpoint_provider_handle(
            resolved_workspace_id,
            provider=normalized_provider,
            provider_handle_id=provider_handle_id,
            agent_id=agent.value,
        )
        existing_endpoints = self._latest_agent_endpoints(resolved_workspace_id)
        if endpoint_id is not None and endpoint_id in existing_endpoints:
            raise ValueError("agent endpoint already exists.")
        timestamp = occurred_at or _utc_now()
        endpoint = AgentEndpointRecord.from_mapping(
            {
                "workspaceId": resolved_workspace_id.value,
                "endpointId": endpoint_id,
                "alias": alias,
                "agentId": agent.value,
                "provider": normalized_provider,
                "providerHandleId": provider_handle_id,
                "direction": direction,
                "defaultReplyPolicy": (
                    default_reply_policy.value
                    if isinstance(default_reply_policy, AgentDispatchReplyPolicy)
                    else default_reply_policy
                ),
                "contactPolicy": contact_policy,
                "state": AgentEndpointState.ACTIVE.value,
                "createdBy": created_by,
                "reason": reason,
                "metadata": dict(metadata or {}),
                "createdAt": timestamp,
                "updatedAt": timestamp,
            }
        )
        existing_alias = self._latest_agent_endpoint_by_alias(
            resolved_workspace_id,
            endpoint.alias,
        )
        if (
            existing_alias is not None
            and existing_alias.state is AgentEndpointState.ACTIVE
        ):
            raise ValueError("agent endpoint alias is already active.")
        sequence = self._append_agent_endpoint(
            resolved_workspace_id,
            endpoint=endpoint,
            action="logged_in",
            occurred_at=timestamp,
        )
        return {
            "agentEndpoint": {
                **endpoint.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "providerHandle": provider_handle,
            "endpointSemantics": _agent_endpoint_semantics(
                endpoint,
                provider_handle,
                read_live_runtime_status=False,
            ),
            "loggedIn": True,
            "sourceEventSequence": sequence,
        }

    def list_agent_endpoints(
        self,
        workspace_id: WorkspaceId | str,
        *,
        agent_id: AgentId | str | None = None,
        provider: str | None = None,
        include_inactive: bool = False,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        resolved_agent_id = (
            self._require_workspace_agent(
                resolved_workspace_id,
                agent_id,
            ).registration.agent_id.value
            if agent_id is not None
            else None
        )
        normalized_provider = normalize_agent_endpoint_provider(provider)
        if provider is not None and normalized_provider is None:
            raise ValueError("provider must be one of: claude, codex, hermes.")
        endpoints = [
            endpoint
            for endpoint in self._latest_agent_endpoints(resolved_workspace_id).values()
            if (include_inactive or endpoint.state is AgentEndpointState.ACTIVE)
            and (
                resolved_agent_id is None
                or endpoint.agent_id == resolved_agent_id
            )
            and (
                normalized_provider is None
                or endpoint.provider == normalized_provider
            )
        ]
        return {
            "agentEndpoints": [
                endpoint.to_metadata()
                for endpoint in sorted(endpoints, key=lambda item: item.alias)
            ],
            "count": len(endpoints),
            "workspaceId": resolved_workspace_id.value,
        }

    def get_agent_endpoint(
        self,
        workspace_id: WorkspaceId | str,
        *,
        endpoint_id: str | None = None,
        alias: str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        endpoint = self._select_agent_endpoint(
            resolved_workspace_id,
            endpoint_id=endpoint_id,
            alias=alias,
        )
        provider_handle = self._agent_endpoint_provider_handle_metadata(
            resolved_workspace_id,
            provider=endpoint.provider,
            provider_handle_id=endpoint.provider_handle_id,
        )
        return {
            "agentEndpoint": endpoint.to_metadata(),
            "providerHandle": provider_handle,
            "endpointSemantics": _agent_endpoint_semantics(
                endpoint,
                provider_handle,
                read_live_runtime_status=False,
            ),
        }

    def get_agent_endpoint_status(
        self,
        workspace_id: WorkspaceId | str,
        *,
        endpoint_id: str | None = None,
        alias: str | None = None,
        limit: int = 20,
        read_live_runtime_status: bool | str = "auto",
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        if limit <= 0:
            raise ValueError("limit must be greater than zero.")
        endpoint = self._select_agent_endpoint(
            resolved_workspace_id,
            endpoint_id=endpoint_id,
            alias=alias,
        )
        provider_handle = self._agent_endpoint_provider_handle_metadata(
            resolved_workspace_id,
            provider=endpoint.provider,
            provider_handle_id=endpoint.provider_handle_id,
        )
        provider_runtime_status = self._agent_provider_runtime_status(
            resolved_workspace_id,
            provider=endpoint.provider,
            provider_handle_id=endpoint.provider_handle_id,
            endpoint=endpoint,
            read_live_runtime_status=read_live_runtime_status,
        )
        dispatches = list(self._latest_agent_dispatches(resolved_workspace_id).values())
        inbox_records = [
            dispatch
            for dispatch in dispatches
            if dispatch.target_agent_id == endpoint.agent_id
            and dispatch.target_handle_id == endpoint.provider_handle_id
        ]
        outbox_records = [
            dispatch
            for dispatch in dispatches
            if dispatch.source_agent_id == endpoint.agent_id
            and dispatch.source_handle_id == endpoint.provider_handle_id
        ]
        inbox_records = sorted(
            inbox_records,
            key=lambda dispatch: dispatch.updated_at,
            reverse=True,
        )
        outbox_records = sorted(
            outbox_records,
            key=lambda dispatch: dispatch.updated_at,
            reverse=True,
        )
        daemon_status = self.get_agent_dispatch_daemon_status(resolved_workspace_id)
        return {
            "schema": "agent_endpoint_status.v1",
            "workspaceId": resolved_workspace_id.value,
            "agentEndpoint": endpoint.to_metadata(),
            "providerHandle": provider_handle,
            "endpointSemantics": _agent_endpoint_semantics(
                endpoint,
                provider_handle,
                provider_runtime_status=provider_runtime_status,
                read_live_runtime_status=read_live_runtime_status,
            ),
            "replyReachability": _agent_endpoint_reply_reachability(
                endpoint,
                provider_handle,
                provider_runtime_status,
            ),
            "respondPermissionProfile": _agent_endpoint_respond_permission_profile(
                endpoint,
                provider_handle,
                provider_runtime_status,
            ),
            "providerRuntimeStatus": provider_runtime_status,
            "providerRuntimeState": provider_runtime_status["runtimeState"],
            "providerRuntimeStateSource": provider_runtime_status["stateSource"],
            "providerRuntimeStateSupported": provider_runtime_status[
                "providerRuntimeStateSupported"
            ],
            "summary": {
                "inboxTotal": len(inbox_records),
                "outboxTotal": len(outbox_records),
                "inboxStatusCounts": _agent_endpoint_status_counts(inbox_records),
                "outboxStatusCounts": _agent_endpoint_status_counts(outbox_records),
                "pendingInboxCount": _agent_endpoint_pending_count(inbox_records),
                "pendingOutboxCount": _agent_endpoint_pending_count(outbox_records),
            },
            "inbox": {
                "count": min(len(inbox_records), limit),
                "totalMatched": len(inbox_records),
                "agentDispatches": [
                    self._agent_endpoint_dispatch_status_item(
                        resolved_workspace_id,
                        dispatch,
                    )
                    for dispatch in inbox_records[:limit]
                ],
            },
            "outbox": {
                "count": min(len(outbox_records), limit),
                "totalMatched": len(outbox_records),
                "agentDispatches": [
                    self._agent_endpoint_dispatch_status_item(
                        resolved_workspace_id,
                        dispatch,
                    )
                    for dispatch in outbox_records[:limit]
                ],
            },
            "providerRuntimeStatusRead": provider_runtime_status[
                "providerRuntimeStatusRead"
            ],
            "dispatcherRunning": daemon_status["dispatcherRunning"],
            "dispatcherStatus": daemon_status,
            "dispatcherLiveness": daemon_status["daemonLiveness"],
        }

    def get_agent_provider_runtime_status(
        self,
        workspace_id: WorkspaceId | str,
        *,
        provider: str | None = None,
        provider_handle_id: str | None = None,
        endpoint_id: str | None = None,
        alias: str | None = None,
        read_live_runtime_status: bool | str = "auto",
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        endpoint = None
        if endpoint_id is not None or alias is not None:
            endpoint = self._select_agent_endpoint(
                resolved_workspace_id,
                endpoint_id=endpoint_id,
                alias=alias,
            )
            provider = endpoint.provider
            provider_handle_id = endpoint.provider_handle_id
        if provider is None or provider_handle_id is None:
            raise ValueError(
                "provider and providerHandleId are required unless an endpoint "
                "selector is provided."
            )
        normalized_provider = normalize_agent_endpoint_provider(provider)
        if normalized_provider is None:
            raise ValueError("provider must be one of: claude, codex, hermes.")
        return {
            "schema": "agent_provider_runtime_status_get.v1",
            "workspaceId": resolved_workspace_id.value,
            "providerRuntimeStatus": self._agent_provider_runtime_status(
                resolved_workspace_id,
                provider=normalized_provider,
                provider_handle_id=provider_handle_id,
                endpoint=endpoint,
                read_live_runtime_status=read_live_runtime_status,
            ),
        }

    def deactivate_agent_endpoint(
        self,
        workspace_id: WorkspaceId | str,
        *,
        endpoint_id: str | None = None,
        alias: str | None = None,
        deactivated_by: str,
        reason: str,
        occurred_at: datetime | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        endpoint = self._select_agent_endpoint(
            resolved_workspace_id,
            endpoint_id=endpoint_id,
            alias=alias,
        )
        if endpoint.state is not AgentEndpointState.ACTIVE:
            raise ValueError("agent endpoint is not active.")
        timestamp = occurred_at or _utc_now()
        inactive = endpoint.inactive_copy(
            deactivated_by=deactivated_by,
            reason=reason,
            deactivated_at=timestamp,
        )
        sequence = self._append_agent_endpoint(
            resolved_workspace_id,
            endpoint=inactive,
            action="deactivated",
            occurred_at=timestamp,
        )
        return {
            "agentEndpoint": {
                **inactive.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "deactivated": True,
            "sourceEventSequence": sequence,
        }

    def create_agent_dispatch(
        self,
        workspace_id: WorkspaceId | str,
        *,
        source_agent_id: AgentId | str,
        target_agent_id: AgentId | str,
        request_kind: AgentExchangeRequestKind | str,
        request_summary: str,
        dispatch_id: str | None = None,
        exchange_request_id: str | None = None,
        source_handle_id: str | None = None,
        target_handle_id: str | None = None,
        target_provider: str | None = None,
        reply_policy: AgentDispatchReplyPolicy | str = (
            AgentDispatchReplyPolicy.SOURCE_HANDLE_OPTIONAL
        ),
        detail_refs: tuple[str, ...] = (),
        linked_task_id: TaskId | str | None = None,
        linked_conversation_id: ConversationId | str | None = None,
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
        occurred_at: datetime | None = None,
    ) -> Mapping[str, object]:
        workspace_record = self._require_workspace(workspace_id)
        if workspace_record.workspace.status is WorkspaceStatus.ARCHIVED:
            raise ValueError("workspace is archived.")
        resolved_workspace_id = workspace_record.workspace.workspace_id
        source_agent_record = self._require_workspace_agent(
            resolved_workspace_id,
            source_agent_id,
        )
        target_agent_record = self._require_workspace_agent(
            resolved_workspace_id,
            target_agent_id,
        )
        if (
            source_agent_record.registration.agent_id
            == target_agent_record.registration.agent_id
        ):
            raise ValueError("sourceAgentId and targetAgentId must not be the same agent.")
        timestamp = occurred_at or _utc_now()
        resolved_request_id = exchange_request_id or f"agent-exchange-request-{uuid4()}"
        resolved_dispatch_id = dispatch_id or f"agent-dispatch-{uuid4()}"
        preview = AgentDispatchRecord.from_mapping(
            {
                "workspaceId": resolved_workspace_id.value,
                "dispatchId": resolved_dispatch_id,
                "exchangeRequestId": resolved_request_id,
                "threadId": thread_id or root_request_id or resolved_request_id,
                "sourceAgentId": source_agent_record.registration.agent_id.value,
                "targetAgentId": target_agent_record.registration.agent_id.value,
                "sourceHandleId": source_handle_id,
                "targetHandleId": target_handle_id,
                "targetProvider": target_provider,
                "status": (
                    AgentDispatchStatus.DRY_RUN.value
                    if dry_run
                    else AgentDispatchStatus.QUEUED.value
                ),
                "replyPolicy": (
                    reply_policy.value
                    if isinstance(reply_policy, AgentDispatchReplyPolicy)
                    else reply_policy
                ),
                "dispatcherRequired": True,
                "providerRuntimeStateSupported": False,
                "providerRuntimeState": "unknown",
                "providerStateSource": "platform_dispatch_queue",
                "createdAt": timestamp,
                "updatedAt": timestamp,
                "metadata": dict(metadata or {}),
            }
        )
        if dry_run:
            return {
                "apiLayer": "delivery-oriented",
                "dispatchApiLayer": _agent_dispatch_api_layer(),
                "agentDispatch": preview.to_metadata(),
                "plannedAgentExchangeRequest": {
                    "schema": "agent_exchange_request_plan.v1",
                    "workspaceId": resolved_workspace_id.value,
                    "exchangeRequestId": resolved_request_id,
                    "sourceAgentId": source_agent_record.registration.agent_id.value,
                    "targetAgentId": target_agent_record.registration.agent_id.value,
                    "requestKind": (
                        request_kind.value
                        if isinstance(request_kind, AgentExchangeRequestKind)
                        else request_kind
                    ),
                    "requestSummary": request_summary,
                    "detailRefs": list(detail_refs),
                    "threadId": thread_id or root_request_id or resolved_request_id,
                },
                "queued": False,
                "dryRun": True,
            }

        request_result = self.create_agent_exchange_request(
            resolved_workspace_id,
            exchange_request_id=resolved_request_id,
            source_agent_id=source_agent_record.registration.agent_id,
            target_agent_id=target_agent_record.registration.agent_id,
            request_kind=request_kind,
            request_summary=request_summary,
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
            metadata={
                **dict(metadata or {}),
                "dispatchId": resolved_dispatch_id,
                "dispatchQueued": True,
            },
            created_at=timestamp,
        )
        request_payload = request_result["agentExchangeRequest"]
        dispatch = AgentDispatchRecord.from_mapping(
            {
                **preview.to_metadata(),
                "status": AgentDispatchStatus.QUEUED.value,
                "threadId": request_payload.get("threadId"),
                "createdAt": timestamp,
                "updatedAt": timestamp,
            }
        )
        sequence = self._append_agent_dispatch(
            resolved_workspace_id,
            dispatch=dispatch,
            action="queued",
            occurred_at=timestamp,
        )
        return {
            "apiLayer": "delivery-oriented",
            "dispatchApiLayer": _agent_dispatch_api_layer(),
            "agentDispatch": {
                **dispatch.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "agentExchangeRequest": request_result["agentExchangeRequest"],
            "agentExchangeThread": request_result["agentExchangeThread"],
            "sourceEventSequence": sequence,
            "requestSourceEventSequence": request_result["sourceEventSequence"],
            "queued": True,
            "dryRun": False,
            "dispatcherRunning": False,
            "dispatcherRequired": True,
        }

    def list_agent_dispatches(
        self,
        workspace_id: WorkspaceId | str,
        *,
        source_agent_id: AgentId | str | None = None,
        target_agent_id: AgentId | str | None = None,
        status: AgentDispatchStatus | str | None = None,
        limit: int = 20,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        resolved_source_agent_id = (
            self._require_workspace_agent(
                resolved_workspace_id,
                source_agent_id,
            ).registration.agent_id.value
            if source_agent_id is not None
            else None
        )
        resolved_target_agent_id = (
            self._require_workspace_agent(
                resolved_workspace_id,
                target_agent_id,
            ).registration.agent_id.value
            if target_agent_id is not None
            else None
        )
        resolved_status = (
            status.value if isinstance(status, AgentDispatchStatus) else status
        )
        if limit <= 0:
            raise ValueError("limit must be greater than zero.")
        records = list(self._latest_agent_dispatches(resolved_workspace_id).values())
        filtered = [
            item
            for item in records
            if (
                resolved_source_agent_id is None
                or item.source_agent_id == resolved_source_agent_id
            )
            and (
                resolved_target_agent_id is None
                or item.target_agent_id == resolved_target_agent_id
            )
            and (
                resolved_status is None
                or AgentDispatchStatus(item.status).value == resolved_status
            )
        ]
        return {
            "agentDispatches": [
                item.to_metadata()
                for item in sorted(
                    filtered,
                    key=lambda dispatch: dispatch.updated_at,
                    reverse=True,
                )[:limit]
            ],
            "count": min(len(filtered), limit),
            "totalMatched": len(filtered),
            "workspaceId": resolved_workspace_id.value,
        }

    def record_agent_dispatch_daemon_liveness(
        self,
        workspace_id: WorkspaceId | str,
        *,
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
        occurred_at: datetime | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        resolved_dispatcher_id = _non_empty_text(dispatcher_id, "dispatcherId")
        resolved_state = _agent_dispatch_daemon_state(state)
        timestamp = occurred_at or _utc_now()
        previous = self._latest_agent_dispatch_daemon_livenesses(
            resolved_workspace_id
        ).get(resolved_dispatcher_id, {})
        liveness = {
            "schema": "agent_dispatch_daemon_liveness.v1",
            "workspaceId": resolved_workspace_id.value,
            "dispatcherId": resolved_dispatcher_id,
            "profilePath": _coalesced_liveness_value(
                profile_path,
                previous.get("profilePath"),
            ),
            "pid": _coalesced_liveness_value(pid, previous.get("pid")),
            "processHint": _coalesced_liveness_value(
                dict(process_hint) if process_hint is not None else None,
                previous.get("processHint"),
            ),
            "startedAt": _coalesced_liveness_value(
                _optional_datetime_text(started_at),
                previous.get("startedAt"),
            ),
            "lastHeartbeatAt": _coalesced_liveness_value(
                _optional_datetime_text(last_heartbeat_at),
                previous.get("lastHeartbeatAt"),
            ),
            "lastPollAt": _coalesced_liveness_value(
                _optional_datetime_text(last_poll_at),
                previous.get("lastPollAt"),
            ),
            "lastErrorAt": _coalesced_liveness_value(
                _optional_datetime_text(last_error_at),
                previous.get("lastErrorAt"),
            ),
            "lastExitAt": _coalesced_liveness_value(
                _optional_datetime_text(last_exit_at),
                previous.get("lastExitAt"),
            ),
            "lastExitReason": _coalesced_liveness_value(
                last_exit_reason,
                previous.get("lastExitReason"),
            ),
            "errorSummary": _coalesced_liveness_value(
                error_summary,
                previous.get("errorSummary"),
            ),
            "state": resolved_state,
            "updatedAt": _datetime_text(timestamp),
            "metadata": {
                **(
                    dict(previous.get("metadata"))
                    if isinstance(previous.get("metadata"), MappingABC)
                    else {}
                ),
                **dict(metadata or {}),
            },
        }
        sequence = self._append_agent_dispatch_daemon_liveness(
            resolved_workspace_id,
            liveness=liveness,
            action=resolved_state,
            occurred_at=timestamp,
        )
        liveness = {**liveness, "sourceEventSequence": sequence}
        return {
            "schema": "agent_dispatch_daemon_liveness_record.v1",
            "workspaceId": resolved_workspace_id.value,
            "dispatcherId": resolved_dispatcher_id,
            "state": resolved_state,
            "dispatcherRunning": _agent_dispatch_daemon_running(resolved_state),
            "daemonLiveness": liveness,
            "sourceEventSequence": sequence,
        }

    def get_agent_dispatch_daemon_status(
        self,
        workspace_id: WorkspaceId | str,
        *,
        dispatcher_id: str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        liveness = self._select_agent_dispatch_daemon_liveness(
            resolved_workspace_id,
            dispatcher_id=dispatcher_id,
        )
        if liveness is None:
            resolved_dispatcher_id = dispatcher_id or "agent-dispatch-daemon"
            state = "not_running"
            liveness = _default_agent_dispatch_daemon_liveness(
                workspace_id=resolved_workspace_id.value,
                dispatcher_id=resolved_dispatcher_id,
                state=state,
            )
        else:
            resolved_dispatcher_id = str(liveness["dispatcherId"])
            state = str(liveness["state"])
        return {
            "schema": "agent_dispatch_daemon_status.v1",
            "workspaceId": resolved_workspace_id.value,
            "dispatcherId": resolved_dispatcher_id,
            "state": state,
            "dispatcherRunning": _agent_dispatch_daemon_running(state),
            "daemonLiveness": liveness,
        }

    def get_agent_dispatch_status(
        self,
        workspace_id: WorkspaceId | str,
        *,
        dispatch_id: str | None = None,
        exchange_request_id: str | None = None,
        read_live_runtime_status: bool | str = "auto",
        waiting_response_stale_threshold_seconds: int = 600,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        dispatch = self._select_agent_dispatch(
            resolved_workspace_id,
            dispatch_id=dispatch_id,
            exchange_request_id=exchange_request_id,
        )
        request = self._latest_agent_exchange_request_by_id(
            resolved_workspace_id,
            dispatch.exchange_request_id,
        )
        latest_lease = self._latest_agent_dispatch_lease_for_dispatch(
            resolved_workspace_id,
            dispatch.dispatch_id,
        )
        checked_at = _utc_now()
        provider_runtime_status = self._agent_dispatch_target_runtime_status(
            resolved_workspace_id,
            dispatch,
            checked_at=checked_at,
            read_live_runtime_status=read_live_runtime_status,
        )
        waiting_response_status = _agent_dispatch_waiting_response_status(
            dispatch,
            request=request,
            checked_at=checked_at,
            stale_threshold_seconds=waiting_response_stale_threshold_seconds,
        )
        busy_backoff_status = _agent_dispatch_busy_backoff_status(
            dispatch,
            checked_at=checked_at,
        )
        daemon_status = self.get_agent_dispatch_daemon_status(resolved_workspace_id)
        response_source_status = _agent_response_source_status(request)
        timeline = self._agent_exchange_status_timeline(
            resolved_workspace_id,
            exchange_request_id=dispatch.exchange_request_id,
            dispatch_id=dispatch.dispatch_id,
        )
        timeline = _agent_exchange_timeline_with_waiting_warning(
            timeline,
            waiting_response_status=waiting_response_status,
            checked_at=checked_at,
        )
        return {
            "agentDispatch": dispatch.to_metadata(),
            "agentExchangeRequest": request.to_metadata() if request else None,
            "latestLease": latest_lease.to_metadata() if latest_lease else None,
            "leaseRecoveryStatus": _agent_dispatch_lease_recovery_status(
                dispatch.to_metadata(),
            ),
            "wakeStatus": self.get_agent_wake_status(
                resolved_workspace_id,
                exchange_request_id=dispatch.exchange_request_id,
            )["agentWakeStatus"],
            "responseSourceStatus": response_source_status,
            "statusTimeline": timeline,
            "dispatchTimeline": timeline,
            "readableStatusReason": (
                _readable_status_reason(
                    "waiting_response_stale",
                    "waiting_response exceeded its warning threshold; no automatic retry was scheduled.",
                )
                if waiting_response_status["waitingResponseStale"]
                else _agent_dispatch_readable_reason(dispatch.to_metadata())
            ),
            "retryActorStatus": _agent_dispatch_retry_actor_status(
                dispatch.to_metadata(),
            ),
            "dispatcherRunning": daemon_status["dispatcherRunning"],
            "dispatcherStatus": daemon_status,
            "dispatcherLiveness": daemon_status["daemonLiveness"],
            "providerRuntimeStatus": provider_runtime_status,
            "providerRuntimeStatusRead": provider_runtime_status[
                "providerRuntimeStatusRead"
            ],
            "providerRuntimeState": provider_runtime_status["runtimeState"],
            "providerRuntimeStateSource": provider_runtime_status["stateSource"],
            "providerRuntimeStateSupported": provider_runtime_status[
                "providerRuntimeStateSupported"
            ],
            "waitingResponseStatus": waiting_response_status,
            "waitingResponseAgeSeconds": waiting_response_status[
                "waitingResponseAgeSeconds"
            ],
            "waitingResponseStale": waiting_response_status[
                "waitingResponseStale"
            ],
            "staleThresholdSeconds": waiting_response_status[
                "staleThresholdSeconds"
            ],
            "recommendedAction": waiting_response_status["recommendedAction"],
            "busyBackoffStatus": busy_backoff_status,
        }

    def get_agent_exchange_status_summary(
        self,
        workspace_id: WorkspaceId | str,
        *,
        exchange_request_id: str | None = None,
        dispatch_id: str | None = None,
        thread_id: str | None = None,
        read_live_runtime_status: bool | str = "auto",
        waiting_response_stale_threshold_seconds: int = 600,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        workspace_record = self._require_workspace(resolved_workspace_id)
        dispatch: AgentDispatchRecord | None = None
        if dispatch_id is not None:
            dispatch = self._require_agent_dispatch(
                resolved_workspace_id,
                dispatch_id,
            )
        elif exchange_request_id is not None:
            try:
                dispatch = self._select_agent_dispatch(
                    resolved_workspace_id,
                    exchange_request_id=exchange_request_id,
                )
            except ValueError:
                dispatch = None
        if exchange_request_id is None and dispatch is not None:
            exchange_request_id = dispatch.exchange_request_id

        request = (
            self._latest_agent_exchange_request_by_id(
                resolved_workspace_id,
                exchange_request_id,
            )
            if exchange_request_id is not None
            else None
        )
        if thread_id is None and request is not None:
            thread_id = request.thread_id
        if exchange_request_id is None and thread_id is not None:
            exchange_request_id = self._latest_thread_request_id(
                resolved_workspace_id,
                thread_id,
            )
            if exchange_request_id is not None:
                request = self._latest_agent_exchange_request_by_id(
                    resolved_workspace_id,
                    exchange_request_id,
                )
                if dispatch is None:
                    try:
                        dispatch = self._select_agent_dispatch(
                            resolved_workspace_id,
                            exchange_request_id=exchange_request_id,
                        )
                    except ValueError:
                        dispatch = None

        thread = (
            self._latest_agent_exchange_thread_by_id(
                resolved_workspace_id,
                thread_id,
            )
            if thread_id is not None
            else None
        )
        thread_requests = (
            [
                item.to_metadata()
                for item in sorted(
                    (
                        item
                        for item in self._latest_agent_exchange_requests(
                            resolved_workspace_id,
                        ).values()
                        if item.thread_id == thread_id
                    ),
                    key=lambda item: (item.created_at, item.exchange_request_id),
                )
            ]
            if thread_id is not None
            else []
        )
        latest_lease = (
            self._latest_agent_dispatch_lease_for_dispatch(
                resolved_workspace_id,
                dispatch.dispatch_id,
            )
            if dispatch is not None
            else None
        )
        checked_at = _utc_now()
        provider_runtime_status = (
            self._agent_dispatch_target_runtime_status(
                resolved_workspace_id,
                dispatch,
                checked_at=checked_at,
                read_live_runtime_status=read_live_runtime_status,
            )
            if dispatch is not None
            else _unavailable_agent_provider_runtime_status(
                provider=None,
                provider_handle_id=None,
                reason="No agent dispatch is associated with this status query.",
            )
        )
        wake_status = (
            self.get_agent_wake_status(
                resolved_workspace_id,
                exchange_request_id=exchange_request_id,
            )["agentWakeStatus"]
            if exchange_request_id is not None
            else {
                "schema": "agent_wake_status.v1",
                "workspaceId": resolved_workspace_id.value,
                "exchangeRequestId": None,
                "wakeDeliverySummary": None,
            }
        )
        daemon_status = self.get_agent_dispatch_daemon_status(resolved_workspace_id)
        response_source_status = _agent_response_source_status(request)
        waiting_response_status = _agent_dispatch_waiting_response_status(
            dispatch,
            request=request,
            checked_at=checked_at,
            stale_threshold_seconds=waiting_response_stale_threshold_seconds,
        )
        busy_backoff_status = _agent_dispatch_busy_backoff_status(
            dispatch,
            checked_at=checked_at,
        )
        timeline = self._agent_exchange_status_timeline(
            resolved_workspace_id,
            exchange_request_id=exchange_request_id,
            dispatch_id=dispatch.dispatch_id if dispatch is not None else dispatch_id,
            thread_id=thread_id,
        )
        timeline = _agent_exchange_timeline_with_waiting_warning(
            timeline,
            waiting_response_status=waiting_response_status,
            checked_at=checked_at,
        )
        workspace_payload = workspace_state_record_payload(workspace_record)
        context_payload = self.get_context(resolved_workspace_id)["context"]
        return {
            "schema": "agent_exchange_status_summary.v1",
            "workspaceId": resolved_workspace_id.value,
            "workspace": {
                "workspaceId": workspace_payload["workspaceId"],
                "displayName": workspace_payload["displayName"],
                "rootPath": workspace_payload["rootPath"],
                "status": workspace_payload["status"],
                "sourceEventSequence": workspace_payload["sourceEventSequence"],
            },
            "context": (
                {
                    "contextId": context_payload["contextId"],
                    "updateCount": context_payload["updateCount"],
                    "updatedAt": context_payload["updatedAt"],
                    "sourceEventSequence": context_payload["sourceEventSequence"],
                }
                if isinstance(context_payload, MappingABC)
                else None
            ),
            "agentExchangeRequest": request.to_metadata() if request else None,
            "agentExchangeThread": thread.to_metadata() if thread else None,
            "threadRequests": thread_requests,
            "threadRequestCount": len(thread_requests),
            "agentDispatch": dispatch.to_metadata() if dispatch else None,
            "latestLease": latest_lease.to_metadata() if latest_lease else None,
            "leaseRecoveryStatus": (
                _agent_dispatch_lease_recovery_status(dispatch.to_metadata())
                if dispatch is not None
                else _agent_dispatch_lease_recovery_status(None)
            ),
            "dispatchStatusBoundary": {
                "dispatchLinked": dispatch is not None,
                "meaning": (
                    "Dispatch fields are present only when a platform dispatch "
                    "record exists for the request; plain exchange requests can "
                    "still be answered through standard respond."
                ),
            },
            "wakeStatus": wake_status,
            "dispatcherRunning": daemon_status["dispatcherRunning"],
            "dispatcherStatus": daemon_status,
            "dispatcherLiveness": daemon_status["daemonLiveness"],
            "providerRuntimeStatus": provider_runtime_status,
            "providerRuntimeStatusRead": provider_runtime_status[
                "providerRuntimeStatusRead"
            ],
            "providerRuntimeState": provider_runtime_status["runtimeState"],
            "waitingResponseStatus": waiting_response_status,
            "waitingResponseAgeSeconds": waiting_response_status[
                "waitingResponseAgeSeconds"
            ],
            "waitingResponseStale": waiting_response_status[
                "waitingResponseStale"
            ],
            "staleThresholdSeconds": waiting_response_status[
                "staleThresholdSeconds"
            ],
            "recommendedAction": waiting_response_status["recommendedAction"],
            "busyBackoffStatus": busy_backoff_status,
            "responseSourceStatus": response_source_status,
            "statusTimeline": timeline,
            "readableStatusReason": (
                _readable_status_reason(
                    "waiting_response_stale",
                    "waiting_response exceeded its warning threshold; no automatic retry was scheduled.",
                )
                if waiting_response_status["waitingResponseStale"]
                else (
                    _agent_dispatch_readable_reason(dispatch.to_metadata())
                    if dispatch is not None
                    else _agent_request_readable_reason(request)
                )
            ),
            "retryActorStatus": (
                _agent_dispatch_retry_actor_status(dispatch.to_metadata())
                if dispatch is not None
                else {
                    "schema": "agent_retry_actor_status.v1",
                    "platformAutomaticRetry": False,
                    "workerRetryScheduled": False,
                    "senderCreatedNewDispatch": False,
                    "manualRetryOf": None,
                }
            ),
            "privateReasoningRead": False,
            "statusBoundary": {
                "stdoutFallbackMeaning": STDOUT_FALLBACK_MEANING,
                "standardRespondMeaning": STANDARD_RESPOND_MEANING,
                "privateReasoningRead": False,
                "fullTranscriptRead": False,
            },
        }

    def _agent_endpoint_dispatch_status_item(
        self,
        workspace_id: WorkspaceId,
        dispatch: AgentDispatchRecord,
        *,
        read_live_runtime_status: bool | str = "auto",
    ) -> Mapping[str, object]:
        request = self._latest_agent_exchange_request_by_id(
            workspace_id,
            dispatch.exchange_request_id,
        )
        return {
            "agentDispatch": dispatch.to_metadata(),
            "agentExchangeRequest": request.to_metadata() if request else None,
            "wakeStatus": self.get_agent_wake_status(
                workspace_id,
                exchange_request_id=dispatch.exchange_request_id,
            )["agentWakeStatus"],
            "providerRuntimeStatus": self._agent_dispatch_target_runtime_status(
                workspace_id,
                dispatch,
                read_live_runtime_status=read_live_runtime_status,
            ),
        }

    def _agent_dispatch_target_runtime_status(
        self,
        workspace_id: WorkspaceId,
        dispatch: AgentDispatchRecord,
        *,
        checked_at: datetime | None = None,
        read_live_runtime_status: bool | str = "auto",
    ) -> Mapping[str, object]:
        if dispatch.target_handle_id is None:
            return _unavailable_agent_provider_runtime_status(
                provider=dispatch.target_provider,
                provider_handle_id=None,
                reason="targetHandleId is not set.",
            )
        provider = self._resolve_agent_dispatch_provider(workspace_id, dispatch)
        if provider is None:
            return _unavailable_agent_provider_runtime_status(
                provider=dispatch.target_provider,
                provider_handle_id=dispatch.target_handle_id,
                reason="targetProvider could not be resolved.",
            )
        return self._agent_provider_runtime_status(
            workspace_id,
            provider=provider,
            provider_handle_id=dispatch.target_handle_id,
            checked_at=checked_at,
            read_live_runtime_status=read_live_runtime_status,
        )

    def _agent_dispatch_provider_session_profile_activation_block(
        self,
        workspace_id: WorkspaceId,
        *,
        dispatch: AgentDispatchRecord,
        provider: str | None,
    ) -> Mapping[str, object] | None:
        if provider is None or dispatch.target_handle_id is None:
            return None
        provider_handle = self._agent_endpoint_provider_handle_metadata(
            workspace_id,
            provider=provider,
            provider_handle_id=dispatch.target_handle_id,
        )
        if not isinstance(provider_handle, MappingABC):
            return None
        metadata = provider_handle.get("metadata")
        if not isinstance(metadata, MappingABC):
            return None
        join = metadata.get("providerSessionWorkspaceJoin")
        if not isinstance(join, MappingABC):
            return None
        policy = str(join.get("activationPolicy", ""))
        if policy != "manual_only_no_cross_workspace_lease":
            return None
        return {
            "schema": "provider_session_profile_activation_block.v1",
            "blocked": True,
            "reason": "provider_session_profile_manual_only",
            "profileId": join.get("profileId"),
            "profileAlias": join.get("profileAlias"),
            "activationPolicy": policy,
            "crossWorkspaceLeaseGuardImplemented": False,
            "automaticWorkerActivationAllowed": False,
        }

    def _agent_provider_runtime_status(
        self,
        workspace_id: WorkspaceId,
        *,
        provider: str,
        provider_handle_id: str,
        endpoint: AgentEndpointRecord | None = None,
        checked_at: datetime | None = None,
        read_live_runtime_status: bool | str = "auto",
    ) -> Mapping[str, object]:
        timestamp = checked_at or _utc_now()
        provider_handle = self._agent_endpoint_provider_handle_metadata(
            workspace_id,
            provider=provider,
            provider_handle_id=provider_handle_id,
        )
        target_agent_id = (
            endpoint.agent_id
            if endpoint is not None
            else (
                str(provider_handle.get("agentId"))
                if isinstance(provider_handle, MappingABC)
                and provider_handle.get("agentId") is not None
                else None
            )
        )
        active_lease = (
            self._latest_active_agent_dispatch_lease_for_target(
                workspace_id,
                target_agent_id=target_agent_id,
                target_handle_id=provider_handle_id,
                now=timestamp,
            )
            if target_agent_id is not None
            else None
        )
        live_probe = _agent_provider_runtime_status_probe(
            provider=provider,
            provider_handle=provider_handle,
            endpoint=endpoint.to_metadata() if endpoint is not None else None,
            checked_at=timestamp,
            read_live_runtime_status=read_live_runtime_status,
        )
        live_snapshot = (
            live_probe.get("runtimeStatus")
            if isinstance(live_probe, MappingABC)
            and isinstance(live_probe.get("runtimeStatus"), MappingABC)
            else None
        )
        return build_agent_provider_runtime_status(
            provider=provider,
            provider_handle_id=provider_handle_id,
            provider_handle=provider_handle,
            endpoint=endpoint.to_metadata() if endpoint is not None else None,
            active_lease=(
                active_lease.to_metadata() if active_lease is not None else None
            ),
            live_status_snapshot=live_snapshot,
            live_status_probe=live_probe,
            checked_at=timestamp,
        )

    def acquire_agent_dispatch_lease(
        self,
        workspace_id: WorkspaceId | str,
        *,
        dispatch_id: str,
        lease_id: str | None = None,
        acquired_by: str | None = None,
        lease_ttl_seconds: int | None = None,
        metadata: Mapping[str, object] | None = None,
        occurred_at: datetime | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        dispatch = self._require_agent_dispatch(resolved_workspace_id, dispatch_id)
        if dispatch.status not in (
            AgentDispatchStatus.QUEUED,
            AgentDispatchStatus.LEASED,
            AgentDispatchStatus.RETRY_SCHEDULED,
        ):
            raise ValueError("agent dispatch is not leaseable.")
        timestamp = occurred_at or _utc_now()
        expires_at = None
        if lease_ttl_seconds is not None:
            if lease_ttl_seconds <= 0:
                raise ValueError("leaseTtlSeconds must be greater than zero.")
            expires_at = timestamp + timedelta(seconds=lease_ttl_seconds)
        active_lease = self._latest_active_agent_dispatch_lease_for_target(
            resolved_workspace_id,
            target_agent_id=dispatch.target_agent_id,
            target_handle_id=dispatch.target_handle_id,
            now=timestamp,
        )
        if active_lease is not None:
            raise ValueError("target dispatch lease is already active.")
        lease = AgentDispatchLeaseRecord.from_mapping(
            {
                "workspaceId": resolved_workspace_id.value,
                "leaseId": lease_id or f"agent-dispatch-lease-{uuid4()}",
                "dispatchId": dispatch.dispatch_id,
                "exchangeRequestId": dispatch.exchange_request_id,
                "targetAgentId": dispatch.target_agent_id,
                "targetHandleId": dispatch.target_handle_id,
                "state": AgentDispatchLeaseState.ACTIVE.value,
                "acquiredBy": acquired_by,
                "expiresAt": expires_at,
                "createdAt": timestamp,
                "updatedAt": timestamp,
                "metadata": dict(metadata or {}),
            }
        )
        lease_sequence = self._append_agent_dispatch_lease(
            resolved_workspace_id,
            lease=lease,
            action="acquired",
            occurred_at=timestamp,
        )
        leased_dispatch = dispatch.active_copy(
            status=AgentDispatchStatus.LEASED,
            lease_id=lease.lease_id,
            lease_expires_at=expires_at,
            updated_at=timestamp,
            metadata={"lastLeaseAction": "acquired"},
        )
        dispatch_sequence = self._append_agent_dispatch(
            resolved_workspace_id,
            dispatch=leased_dispatch,
            action="leased",
            occurred_at=timestamp,
        )
        return {
            "agentDispatch": {
                **leased_dispatch.to_metadata(),
                "sourceEventSequence": dispatch_sequence,
            },
            "agentDispatchLease": {
                **lease.to_metadata(),
                "sourceEventSequence": lease_sequence,
            },
            "leased": True,
            "dispatcherRunning": False,
            "sourceEventSequence": dispatch_sequence,
            "leaseSourceEventSequence": lease_sequence,
        }

    def release_agent_dispatch_lease(
        self,
        workspace_id: WorkspaceId | str,
        *,
        lease_id: str,
        released_by: str | None = None,
        final_dispatch_status: AgentDispatchStatus | str = AgentDispatchStatus.QUEUED,
        next_attempt_after: datetime | None = None,
        clear_next_attempt_after: bool = False,
        attempt_count: int | None = None,
        clear_busy_retry_delay: bool = False,
        provider_runtime_state_supported: bool | None = None,
        provider_runtime_state: str | None = None,
        provider_state_source: str | None = None,
        provider_activation_executed: bool | None = None,
        provider_runtime_status_read: bool | None = None,
        metadata: Mapping[str, object] | None = None,
        occurred_at: datetime | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        lease = self._require_agent_dispatch_lease(resolved_workspace_id, lease_id)
        if lease.state is not AgentDispatchLeaseState.ACTIVE:
            raise ValueError("agent dispatch lease is not active.")
        timestamp = occurred_at or _utc_now()
        recovery_reason = (
            str(metadata.get("recoveryReason"))
            if isinstance(metadata, MappingABC)
            and metadata.get("recoveryReason") is not None
            else None
        )
        lease_action = "recovered" if recovery_reason is not None else "released"
        dispatch_action = (
            "lease_recovered" if recovery_reason is not None else "lease_released"
        )
        released = AgentDispatchLeaseRecord.from_mapping(
            {
                **lease.to_metadata(),
                "state": AgentDispatchLeaseState.RELEASED.value,
                "updatedAt": timestamp,
                "metadata": {
                    **dict(lease.metadata),
                    **dict(metadata or {}),
                    **({"releasedBy": released_by} if released_by else {}),
                },
            }
        )
        lease_sequence = self._append_agent_dispatch_lease(
            resolved_workspace_id,
            lease=released,
            action=lease_action,
            occurred_at=timestamp,
        )
        dispatch = self._require_agent_dispatch(
            resolved_workspace_id,
            lease.dispatch_id,
        )
        final_dispatch = dispatch.active_copy(
            status=final_dispatch_status,
            updated_at=timestamp,
            clear_lease=True,
            next_attempt_after=next_attempt_after,
            clear_next_attempt_after=clear_next_attempt_after,
            attempt_count=attempt_count,
            clear_busy_retry_delay=clear_busy_retry_delay,
            provider_runtime_state_supported=provider_runtime_state_supported,
            provider_runtime_state=provider_runtime_state,
            provider_state_source=provider_state_source,
            provider_activation_executed=provider_activation_executed,
            provider_runtime_status_read=provider_runtime_status_read,
            metadata={"lastLeaseAction": lease_action, **dict(metadata or {})},
        )
        dispatch_sequence = self._append_agent_dispatch(
            resolved_workspace_id,
            dispatch=final_dispatch,
            action=dispatch_action,
            occurred_at=timestamp,
        )
        return {
            "agentDispatch": {
                **final_dispatch.to_metadata(),
                "sourceEventSequence": dispatch_sequence,
            },
            "agentDispatchLease": {
                **released.to_metadata(),
                "sourceEventSequence": lease_sequence,
            },
            "released": True,
            "recovered": recovery_reason is not None,
            "sourceEventSequence": dispatch_sequence,
            "leaseSourceEventSequence": lease_sequence,
        }

    def reconcile_agent_dispatch_leases(
        self,
        workspace_id: WorkspaceId | str,
        *,
        dispatch_id: str | None = None,
        lease_id: str | None = None,
        recovered_by: str = "agent-dispatch-lease-reconciler",
        recovery_delay_seconds: int = 0,
        dry_run: bool = False,
        occurred_at: datetime | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        if recovery_delay_seconds < 0:
            raise ValueError("recoveryDelaySeconds must be greater than or equal to zero.")
        timestamp = occurred_at or _utc_now()
        livenesses = self._latest_agent_dispatch_daemon_livenesses(
            resolved_workspace_id
        )
        active_leases = sorted(
            (
                lease
                for lease in self._latest_agent_dispatch_leases(
                    resolved_workspace_id
                ).values()
                if lease.state is AgentDispatchLeaseState.ACTIVE
                and (lease_id is None or lease.lease_id == lease_id)
                and (dispatch_id is None or lease.dispatch_id == dispatch_id)
            ),
            key=lambda item: (item.created_at, item.lease_id),
        )
        entries: list[Mapping[str, object]] = []
        recovered_count = 0
        would_recover_count = 0
        preserved_count = 0
        for lease in active_leases:
            dispatch = self._latest_agent_dispatches(
                resolved_workspace_id
            ).get(lease.dispatch_id)
            request = self._latest_agent_exchange_request_by_id(
                resolved_workspace_id,
                lease.exchange_request_id,
            )
            decision = _agent_dispatch_lease_recovery_decision(
                lease=lease,
                dispatch=dispatch,
                request=request,
                checked_at=timestamp,
                recovery_delay_seconds=recovery_delay_seconds,
            )
            owner_liveness = (
                livenesses.get(lease.acquired_by)
                if lease.acquired_by is not None
                else None
            )
            entry: dict[str, object] = {
                "schema": "agent_dispatch_lease_reconciliation_entry.v1",
                "leaseId": lease.lease_id,
                "dispatchId": lease.dispatch_id,
                "exchangeRequestId": lease.exchange_request_id,
                "targetAgentId": lease.target_agent_id,
                "targetHandleId": lease.target_handle_id,
                "originalDispatcher": lease.acquired_by,
                "originalWorkerRunId": lease.metadata.get("workerRunId"),
                "leaseExpiresAt": (
                    lease.expires_at.isoformat()
                    if lease.expires_at is not None
                    else None
                ),
                "leaseExpired": bool(decision["leaseExpired"]),
                "requestStatus": decision["requestStatus"],
                "requestTerminalReason": decision["requestTerminalReason"],
                "decision": decision["decision"],
                "recoveryReason": decision["recoveryReason"],
                "resultDispatchStatus": decision["resultDispatchStatus"],
                "resultNextAttemptAfter": decision["nextAttemptAfter"],
                "ownerMayBeLive": decision["decision"] == "preserve",
                "ownerLivenessState": (
                    owner_liveness.get("state")
                    if isinstance(owner_liveness, MappingABC)
                    else None
                ),
                "attemptCountBefore": (
                    dispatch.attempt_count if dispatch is not None else None
                ),
                "automaticProviderActivationTriggered": False,
                "changed": False,
            }
            if decision["decision"] != "recover":
                preserved_count += 1
                entries.append(entry)
                continue
            if dispatch is None:
                preserved_count += 1
                entry.update(
                    {
                        "decision": "preserve",
                        "recoveryReason": "dispatch_missing_manual_review_required",
                        "resultDispatchStatus": None,
                        "ownerMayBeLive": False,
                    }
                )
                entries.append(entry)
                continue
            would_recover_count += 1
            if dry_run:
                entry["wouldChange"] = True
                entries.append(entry)
                continue

            recovery_metadata = {
                "recoveryReason": decision["recoveryReason"],
                "leaseRecovery": {
                    "schema": "agent_dispatch_lease_recovery.v1",
                    "recoveryReason": decision["recoveryReason"],
                    "originalLeaseId": lease.lease_id,
                    "originalDispatcher": lease.acquired_by,
                    "originalWorkerRunId": lease.metadata.get("workerRunId"),
                    "leaseExpiresAt": (
                        lease.expires_at.isoformat()
                        if lease.expires_at is not None
                        else None
                    ),
                    "leaseExpired": bool(decision["leaseExpired"]),
                    "requestStatus": decision["requestStatus"],
                    "requestTerminalReason": decision["requestTerminalReason"],
                    "resultDispatchStatus": decision["resultDispatchStatus"],
                    "resultNextAttemptAfter": decision["nextAttemptAfter"],
                    "recoveredBy": recovered_by,
                    "recoveredAt": timestamp.isoformat(),
                    "attemptCountIncremented": False,
                    "automaticProviderActivationTriggered": False,
                },
            }
            next_attempt_after = (
                datetime.fromisoformat(str(decision["nextAttemptAfter"]))
                if decision["nextAttemptAfter"] is not None
                else None
            )
            recovered = self.release_agent_dispatch_lease(
                resolved_workspace_id,
                lease_id=lease.lease_id,
                released_by=recovered_by,
                final_dispatch_status=str(decision["resultDispatchStatus"]),
                next_attempt_after=next_attempt_after,
                clear_next_attempt_after=next_attempt_after is None,
                attempt_count=dispatch.attempt_count,
                provider_runtime_state_supported=False,
                provider_runtime_state=self._agent_dispatch_runtime_state_for_status(
                    AgentDispatchStatus(str(decision["resultDispatchStatus"])),
                ),
                provider_state_source="agent_dispatch_lease_recovery",
                metadata=recovery_metadata,
                occurred_at=timestamp,
            )
            recovered_count += 1
            entry.update(
                {
                    "changed": True,
                    "attemptCountAfter": recovered["agentDispatch"]["attemptCount"],
                    "leaseSourceEventSequence": recovered[
                        "leaseSourceEventSequence"
                    ],
                    "dispatchSourceEventSequence": recovered["sourceEventSequence"],
                }
            )
            entries.append(entry)
        return {
            "schema": "agent_dispatch_lease_reconciliation.v1",
            "workspaceId": resolved_workspace_id.value,
            "checkedAt": timestamp.isoformat(),
            "dryRun": dry_run,
            "recoveredBy": recovered_by,
            "recoveryDelaySeconds": recovery_delay_seconds,
            "scannedActiveLeaseCount": len(active_leases),
            "recoveryCandidateCount": would_recover_count,
            "wouldRecoverCount": would_recover_count if dry_run else 0,
            "recoveredCount": recovered_count,
            "preservedCount": preserved_count,
            "entries": entries,
            "idempotent": True,
            "providerActivationTriggered": False,
            "crossWorkspaceProviderSessionLeaseChanged": False,
        }

    def run_agent_dispatch_worker_once(
        self,
        workspace_id: WorkspaceId | str,
        *,
        database_path: str,
        workspace_root: str,
        plugins_directory: str,
        config_path: str | None = None,
        dispatch_id: str | None = None,
        target_agent_id: AgentId | str | None = None,
        dispatcher_id: str = "agent-dispatch-worker",
        limit: int = 1,
        lease_ttl_seconds: int | None = 300,
        retry_delay_seconds: int = 300,
        handoff_directory: str | None = None,
        platform_workspace_root: str | None = None,
        claude_executable: str = "claude",
        claude_default_platform_workspace_add_dir: bool = True,
        claude_add_dirs: Sequence[str] = (),
        claude_allowed_tools: Sequence[str] = (),
        claude_permission_mode: str | None = None,
        claude_settings_path: str | None = None,
        codex_executable: str = "codex",
        codex_default_platform_workspace_add_dir: bool = True,
        codex_add_dirs: Sequence[str] = (),
        codex_sandbox_mode: str | None = None,
        codex_approval_policy: str | None = None,
        codex_git_repo_check_policy: CodexGitRepoCheckPolicy | str = (
            CodexGitRepoCheckPolicy.SKIP
        ),
        codex_git_repo_check_policy_source: str = "default",
        hermes_executable: str = "hermes",
        hermes_home: str | None = None,
        hermes_source_tag: str = "agent-os",
        hermes_max_turns: int | None = None,
        activation_timeout_seconds: int = 120,
        skip_busy_target: bool = True,
        read_live_runtime_status: bool | str = "auto",
        dry_run: bool = False,
        occurred_at: datetime | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        if limit <= 0:
            raise ValueError("limit must be greater than zero.")
        if lease_ttl_seconds is not None and lease_ttl_seconds <= 0:
            raise ValueError("leaseTtlSeconds must be greater than zero.")
        if retry_delay_seconds <= 0:
            raise ValueError("retryDelaySeconds must be greater than zero.")
        if activation_timeout_seconds <= 0:
            raise ValueError("activationTimeoutSeconds must be greater than zero.")
        resolved_target_agent_id = (
            self._require_workspace_agent(
                resolved_workspace_id,
                target_agent_id,
            ).registration.agent_id.value
            if target_agent_id is not None
            else None
        )
        timestamp = occurred_at or _utc_now()
        lease_reconciliation = self.reconcile_agent_dispatch_leases(
            resolved_workspace_id,
            recovered_by=dispatcher_id,
            recovery_delay_seconds=0,
            dry_run=dry_run,
            occurred_at=timestamp,
        )
        candidates = self._agent_dispatch_worker_candidates(
            resolved_workspace_id,
            dispatch_id=dispatch_id,
            target_agent_id=resolved_target_agent_id,
            now=timestamp,
        )
        worker_run_id = f"agent-dispatch-worker-run-{uuid4()}"
        runtime_status_policy = normalize_provider_runtime_status_read_policy(
            read_live_runtime_status
        )
        selected_items: list[
            tuple[AgentDispatchRecord, Mapping[str, object]]
        ] = []
        activation_selected_count = 0
        for dispatch in candidates:
            preview = self._agent_dispatch_worker_candidate_preview(
                resolved_workspace_id,
                dispatch=dispatch,
                now=timestamp,
                read_live_runtime_status=runtime_status_policy,
            )
            selected_items.append((dispatch, preview))
            if skip_busy_target and preview.get("providerRuntimeState") in {
                "busy",
                "blocked",
            }:
                continue
            activation_selected_count += 1
            if activation_selected_count >= limit:
                break
        selected_previews = [preview for _, preview in selected_items]
        if dry_run:
            return {
                "schema": "agent_dispatch_worker_run.v1",
                "workspaceId": resolved_workspace_id.value,
                "workerRunId": worker_run_id,
                "dispatcherId": dispatcher_id,
                "dryRun": True,
                "workerStarted": False,
                "dispatcherRunning": False,
                "requestedLimit": limit,
                "candidateCount": len(candidates),
                "selectedCount": len(selected_items),
                "activationSelectedCount": activation_selected_count,
                "processedCount": 0,
                "skippedCount": 0,
                "candidates": selected_previews,
                "providerRuntimeStatusRead": any(
                    bool(item.get("providerRuntimeStatusRead"))
                    for item in selected_previews
                ),
                "skipBusyTarget": skip_busy_target,
                "readLiveRuntimeStatus": runtime_status_policy == "enabled",
                "runtimeStatusPolicy": runtime_status_policy,
                "leaseReconciliation": lease_reconciliation,
            }

        processed: list[Mapping[str, object]] = []
        for dispatch, preview in selected_items:
            provider_runtime_status = preview.get("providerRuntimeStatus")
            processed.append(self._run_agent_dispatch_worker_item(
                resolved_workspace_id,
                dispatch=dispatch,
                worker_run_id=worker_run_id,
                dispatcher_id=dispatcher_id,
                lease_ttl_seconds=lease_ttl_seconds,
                retry_delay_seconds=retry_delay_seconds,
                database_path=database_path,
                workspace_root=workspace_root,
                plugins_directory=plugins_directory,
                config_path=config_path,
                handoff_directory=handoff_directory,
                platform_workspace_root=platform_workspace_root,
                claude_executable=claude_executable,
                claude_default_platform_workspace_add_dir=(
                    claude_default_platform_workspace_add_dir
                ),
                claude_add_dirs=tuple(claude_add_dirs),
                claude_allowed_tools=tuple(claude_allowed_tools),
                claude_permission_mode=claude_permission_mode,
                claude_settings_path=claude_settings_path,
                codex_executable=codex_executable,
                codex_default_platform_workspace_add_dir=(
                    codex_default_platform_workspace_add_dir
                ),
                codex_add_dirs=tuple(codex_add_dirs),
                codex_sandbox_mode=codex_sandbox_mode,
                codex_approval_policy=codex_approval_policy,
                codex_git_repo_check_policy=codex_git_repo_check_policy,
                codex_git_repo_check_policy_source=(
                    codex_git_repo_check_policy_source
                ),
                hermes_executable=hermes_executable,
                hermes_home=hermes_home,
                hermes_source_tag=hermes_source_tag,
                hermes_max_turns=hermes_max_turns,
                activation_timeout_seconds=activation_timeout_seconds,
                skip_busy_target=skip_busy_target,
                read_live_runtime_status=runtime_status_policy,
                provider_runtime_status=(
                    provider_runtime_status
                    if isinstance(provider_runtime_status, MappingABC)
                    else None
                ),
                occurred_at=timestamp,
            ))
        return {
            "schema": "agent_dispatch_worker_run.v1",
            "workspaceId": resolved_workspace_id.value,
            "workerRunId": worker_run_id,
            "dispatcherId": dispatcher_id,
            "dryRun": False,
            "workerStarted": True,
            "dispatcherRunning": False,
            "requestedLimit": limit,
            "candidateCount": len(candidates),
            "selectedCount": len(selected_items),
            "activationSelectedCount": activation_selected_count,
            "processedCount": len(
                [item for item in processed if item.get("processed")]
            ),
            "skippedCount": len([item for item in processed if item.get("skipped")]),
            "agentDispatches": processed,
            "providerRuntimeStatusRead": any(
                bool(item.get("providerRuntimeStatus", {}).get("providerRuntimeStatusRead"))
                for item in processed
                if isinstance(item.get("providerRuntimeStatus"), MappingABC)
            ),
            "skipBusyTarget": skip_busy_target,
            "readLiveRuntimeStatus": runtime_status_policy == "enabled",
            "runtimeStatusPolicy": runtime_status_policy,
            "leaseReconciliation": lease_reconciliation,
        }

    def _agent_dispatch_worker_candidates(
        self,
        workspace_id: WorkspaceId,
        *,
        dispatch_id: str | None,
        target_agent_id: str | None,
        now: datetime,
    ) -> list[AgentDispatchRecord]:
        candidates: list[AgentDispatchRecord] = []
        for dispatch in self._latest_agent_dispatches(workspace_id).values():
            if dispatch_id is not None and dispatch.dispatch_id != dispatch_id:
                continue
            if (
                target_agent_id is not None
                and dispatch.target_agent_id != target_agent_id
            ):
                continue
            status = AgentDispatchStatus(dispatch.status)
            if status is AgentDispatchStatus.QUEUED and (
                dispatch.next_attempt_after is None
                or dispatch.next_attempt_after <= now
            ):
                candidates.append(dispatch)
                continue
            if status is AgentDispatchStatus.RETRY_SCHEDULED and (
                dispatch.next_attempt_after is None
                or dispatch.next_attempt_after <= now
            ):
                candidates.append(dispatch)
        return sorted(
            candidates,
            key=lambda item: (
                item.next_attempt_after or item.created_at,
                item.created_at,
                item.dispatch_id,
            ),
        )

    def _agent_dispatch_worker_candidate_preview(
        self,
        workspace_id: WorkspaceId,
        *,
        dispatch: AgentDispatchRecord,
        now: datetime,
        read_live_runtime_status: bool | str = "auto",
    ) -> Mapping[str, object]:
        provider = self._resolve_agent_dispatch_provider(workspace_id, dispatch)
        active_lease = self._latest_active_agent_dispatch_lease_for_target(
            workspace_id,
            target_agent_id=dispatch.target_agent_id,
            target_handle_id=dispatch.target_handle_id,
            now=now,
        )
        provider_runtime_status = self._agent_dispatch_target_runtime_status(
            workspace_id,
            dispatch,
            checked_at=now,
            read_live_runtime_status=read_live_runtime_status,
        )
        activation_block = self._agent_dispatch_provider_session_profile_activation_block(
            workspace_id,
            dispatch=dispatch,
            provider=provider,
        )
        runtime_blocked = (
            provider_runtime_status["runtimeState"] in {"busy", "blocked"}
            or activation_block is not None
        )
        runtime_block_reason = (
            _agent_dispatch_runtime_block_reason(provider_runtime_status)
            if provider_runtime_status["runtimeState"] in {"busy", "blocked"}
            else None
        )
        return {
            "schema": "agent_dispatch_worker_candidate.v1",
            "dispatchId": dispatch.dispatch_id,
            "exchangeRequestId": dispatch.exchange_request_id,
            "targetAgentId": dispatch.target_agent_id,
            "targetHandleId": dispatch.target_handle_id,
            "targetProvider": dispatch.target_provider,
            "normalizedTargetProvider": provider,
            "status": AgentDispatchStatus(dispatch.status).value,
            "leaseBlocked": active_lease is not None,
            "activeLeaseId": active_lease.lease_id if active_lease else None,
            "missingTargetHandle": dispatch.target_handle_id is None,
            "providerSupported": provider is not None,
            "providerRuntimeStatus": provider_runtime_status,
            "providerRuntimeState": provider_runtime_status["runtimeState"],
            "providerRuntimeStatusRead": provider_runtime_status[
                "providerRuntimeStatusRead"
            ],
            "providerSessionProfileActivation": activation_block,
            "runtimeBlocked": runtime_blocked,
            "runtimeBlockReason": (
                "provider_session_profile_manual_only"
                if activation_block is not None
                else runtime_block_reason
            ),
        }

    def _run_agent_dispatch_worker_item(
        self,
        workspace_id: WorkspaceId,
        *,
        dispatch: AgentDispatchRecord,
        worker_run_id: str,
        dispatcher_id: str,
        lease_ttl_seconds: int | None,
        retry_delay_seconds: int,
        database_path: str,
        workspace_root: str,
        plugins_directory: str,
        config_path: str | None,
        handoff_directory: str | None,
        platform_workspace_root: str | None,
        claude_executable: str,
        claude_default_platform_workspace_add_dir: bool,
        claude_add_dirs: Sequence[str],
        claude_allowed_tools: Sequence[str],
        claude_permission_mode: str | None,
        claude_settings_path: str | None,
        codex_executable: str,
        codex_default_platform_workspace_add_dir: bool,
        codex_add_dirs: Sequence[str],
        codex_sandbox_mode: str | None,
        codex_approval_policy: str | None,
        codex_git_repo_check_policy: CodexGitRepoCheckPolicy | str,
        codex_git_repo_check_policy_source: str,
        hermes_executable: str,
        hermes_home: str | None,
        hermes_source_tag: str,
        hermes_max_turns: int | None,
        activation_timeout_seconds: int,
        skip_busy_target: bool,
        read_live_runtime_status: bool | str,
        provider_runtime_status: Mapping[str, object] | None,
        occurred_at: datetime,
    ) -> Mapping[str, object]:
        if provider_runtime_status is None:
            provider_runtime_status = self._agent_dispatch_target_runtime_status(
                workspace_id,
                dispatch,
                checked_at=occurred_at,
                read_live_runtime_status=read_live_runtime_status,
            )
        if (
            skip_busy_target
            and provider_runtime_status.get("runtimeState") in {"busy", "blocked"}
        ):
            runtime_block_reason = _agent_dispatch_runtime_block_reason(
                provider_runtime_status
            )
            return self._record_agent_dispatch_worker_skip(
                workspace_id,
                dispatch=dispatch,
                worker_run_id=worker_run_id,
                dispatcher_id=dispatcher_id,
                skip_reason=runtime_block_reason,
                message=(
                    "a valid platform dispatch lease still owns this target; "
                    "dispatch remains queued."
                    if runtime_block_reason == "valid_platform_lease"
                    else (
                        "target provider runtime is blocked; dispatch remains queued."
                        if runtime_block_reason == "target_runtime_blocked"
                        else "target provider runtime is busy; dispatch remains queued."
                    )
                ),
                provider_runtime_status=provider_runtime_status,
                apply_busy_backoff=True,
                occurred_at=occurred_at,
            )
        if dispatch.target_handle_id is None:
            return self._record_agent_dispatch_worker_failure(
                workspace_id,
                dispatch=dispatch,
                worker_run_id=worker_run_id,
                dispatcher_id=dispatcher_id,
                failure_category="missing_target_handle",
                failure_reason="targetHandleId is required for provider activation.",
                retryable=False,
                occurred_at=occurred_at,
            )
        provider = self._resolve_agent_dispatch_provider(workspace_id, dispatch)
        if provider is None:
            return self._record_agent_dispatch_worker_failure(
                workspace_id,
                dispatch=dispatch,
                worker_run_id=worker_run_id,
                dispatcher_id=dispatcher_id,
                failure_category="unsupported_target_provider",
                failure_reason="targetProvider could not be resolved to Claude, Codex, or Hermes.",
                retryable=False,
                occurred_at=occurred_at,
            )
        activation_block = self._agent_dispatch_provider_session_profile_activation_block(
            workspace_id,
            dispatch=dispatch,
            provider=provider,
        )
        if activation_block is not None:
            return self._record_agent_dispatch_worker_skip(
                workspace_id,
                dispatch=dispatch,
                worker_run_id=worker_run_id,
                dispatcher_id=dispatcher_id,
                skip_reason="provider_session_profile_manual_only",
                message=(
                    "target handle comes from a local provider session profile; "
                    "automatic worker/daemon activation is disabled until a "
                    "cross-workspace provider-session lease guard is implemented."
                ),
                provider_runtime_status={
                    **dict(provider_runtime_status),
                    "providerSessionProfileActivation": activation_block,
                },
                occurred_at=occurred_at,
            )
        try:
            lease_result = self.acquire_agent_dispatch_lease(
                workspace_id,
                dispatch_id=dispatch.dispatch_id,
                acquired_by=dispatcher_id,
                lease_ttl_seconds=lease_ttl_seconds,
                metadata={
                    "workerRunId": worker_run_id,
                    "workerAction": "provider_activation_started",
                },
                occurred_at=occurred_at,
            )
        except ValueError as exc:
            if "already active" in str(exc):
                return self._record_agent_dispatch_worker_skip(
                    workspace_id,
                    dispatch=dispatch,
                    worker_run_id=worker_run_id,
                    dispatcher_id=dispatcher_id,
                    skip_reason="valid_platform_lease",
                    message=str(exc),
                    provider_runtime_status=provider_runtime_status,
                    apply_busy_backoff=True,
                    occurred_at=occurred_at,
                )
            raise

        lease = lease_result["agentDispatchLease"]
        activation_result: Mapping[str, object] | None = None
        activation: Mapping[str, object] | None = None
        release_timestamp = _utc_now()
        try:
            activation_result = self._activate_agent_dispatch_provider(
                workspace_id,
                dispatch=dispatch,
                provider=provider,
                database_path=database_path,
                workspace_root=workspace_root,
                plugins_directory=plugins_directory,
                config_path=config_path,
                handoff_directory=handoff_directory,
                platform_workspace_root=platform_workspace_root,
                claude_executable=claude_executable,
                claude_default_platform_workspace_add_dir=(
                    claude_default_platform_workspace_add_dir
                ),
                claude_add_dirs=tuple(claude_add_dirs),
                claude_allowed_tools=tuple(claude_allowed_tools),
                claude_permission_mode=claude_permission_mode,
                claude_settings_path=claude_settings_path,
                codex_executable=codex_executable,
                codex_default_platform_workspace_add_dir=(
                    codex_default_platform_workspace_add_dir
                ),
                codex_add_dirs=tuple(codex_add_dirs),
                codex_sandbox_mode=codex_sandbox_mode,
                codex_approval_policy=codex_approval_policy,
                codex_git_repo_check_policy=codex_git_repo_check_policy,
                codex_git_repo_check_policy_source=(
                    codex_git_repo_check_policy_source
                ),
                hermes_executable=hermes_executable,
                hermes_home=hermes_home,
                hermes_source_tag=hermes_source_tag,
                hermes_max_turns=hermes_max_turns,
                activation_timeout_seconds=activation_timeout_seconds,
                occurred_at=occurred_at,
            )
            activation = self._agent_dispatch_activation_payload(
                provider,
                activation_result,
            )
            release_timestamp = _utc_now()
            final_status = self._agent_dispatch_final_status_from_activation(
                workspace_id,
                dispatch=dispatch,
                activation=activation,
            )
            retryable = (
                bool(activation.get("retryable"))
                if isinstance(activation, MappingABC)
                and activation.get("retryable") is not None
                else None
            )
            failure_category = (
                str(activation.get("failureCategory"))
                if isinstance(activation, MappingABC)
                and activation.get("failureCategory") is not None
                else None
            )
            failure_reason = (
                str(activation.get("failureReason"))
                if isinstance(activation, MappingABC)
                and activation.get("failureReason") is not None
                else None
            )
        except Exception as exc:
            release_timestamp = _utc_now()
            final_status = AgentDispatchStatus.FAILED
            retryable = False
            failure_category = "provider_activation_exception"
            failure_reason = f"{exc.__class__.__name__}: {exc}"
            activation = None

        next_attempt_after = (
            release_timestamp + timedelta(seconds=retry_delay_seconds)
            if final_status is AgentDispatchStatus.RETRY_SCHEDULED
            else None
        )
        release_metadata = {
            "workerRunId": worker_run_id,
            "workerAction": "provider_activation_finished",
            "normalizedTargetProvider": provider,
            "providerRuntimePrecheck": _agent_provider_runtime_precheck_summary(
                provider_runtime_status
            ),
            "providerActivation": self._agent_dispatch_worker_activation_summary(
                provider,
                activation=activation,
            ),
            "failureCategory": failure_category,
            "failureReason": failure_reason,
            "retryable": retryable,
        }
        released = self.release_agent_dispatch_lease(
            workspace_id,
            lease_id=str(lease["leaseId"]),
            released_by=dispatcher_id,
            final_dispatch_status=final_status,
            next_attempt_after=next_attempt_after,
            clear_next_attempt_after=(
                final_status is not AgentDispatchStatus.RETRY_SCHEDULED
            ),
            attempt_count=dispatch.attempt_count + 1,
            provider_runtime_state_supported=False,
            provider_runtime_state=self._agent_dispatch_runtime_state_for_status(
                final_status,
            ),
            provider_state_source="registered_session_activation_adapter",
            provider_activation_executed=activation is not None,
            provider_runtime_status_read=False,
            clear_busy_retry_delay=True,
            metadata=release_metadata,
            occurred_at=release_timestamp,
        )
        return {
            "schema": "agent_dispatch_worker_item.v1",
            "dispatchId": dispatch.dispatch_id,
            "exchangeRequestId": dispatch.exchange_request_id,
            "targetAgentId": dispatch.target_agent_id,
            "targetHandleId": dispatch.target_handle_id,
            "targetProvider": dispatch.target_provider,
            "normalizedTargetProvider": provider,
            "processed": True,
            "skipped": False,
            "finalStatus": final_status.value,
            "agentDispatch": released["agentDispatch"],
            "agentDispatchLease": released["agentDispatchLease"],
            "activation": self._agent_dispatch_worker_activation_summary(
                provider,
                activation=activation,
            ),
            "activationResultIncluded": activation_result is not None,
            "providerRuntimeStatus": provider_runtime_status,
        }

    def _record_agent_dispatch_worker_skip(
        self,
        workspace_id: WorkspaceId,
        *,
        dispatch: AgentDispatchRecord,
        worker_run_id: str,
        dispatcher_id: str,
        skip_reason: str,
        message: str,
        provider_runtime_status: Mapping[str, object] | None = None,
        apply_busy_backoff: bool = False,
        occurred_at: datetime,
    ) -> Mapping[str, object]:
        readable_reason = _readable_status_reason(skip_reason, message)
        busy_skip_count = dispatch.busy_skip_count
        busy_retry_delay_seconds: int | None = None
        next_attempt_after: datetime | None = None
        if apply_busy_backoff:
            busy_skip_count += 1
            busy_retry_delay_seconds = _agent_dispatch_busy_retry_delay_seconds(
                busy_skip_count
            )
            next_attempt_after = occurred_at + timedelta(
                seconds=busy_retry_delay_seconds
            )
        skipped = dispatch.active_copy(
            status=AgentDispatchStatus(dispatch.status),
            updated_at=occurred_at,
            next_attempt_after=next_attempt_after,
            clear_next_attempt_after=False,
            attempt_count=dispatch.attempt_count,
            busy_skip_count=busy_skip_count,
            last_busy_skip_at=occurred_at if apply_busy_backoff else None,
            busy_retry_delay_seconds=busy_retry_delay_seconds,
            provider_runtime_state_supported=(
                bool(provider_runtime_status.get("providerRuntimeStateSupported"))
                if isinstance(provider_runtime_status, MappingABC)
                else dispatch.provider_runtime_state_supported
            ),
            provider_runtime_state=(
                str(provider_runtime_status.get("runtimeState"))
                if isinstance(provider_runtime_status, MappingABC)
                and provider_runtime_status.get("runtimeState") is not None
                else dispatch.provider_runtime_state
            ),
            provider_state_source=(
                str(provider_runtime_status.get("stateSource"))
                if isinstance(provider_runtime_status, MappingABC)
                and provider_runtime_status.get("stateSource") is not None
                else dispatch.provider_state_source
            ),
            provider_activation_executed=False,
            provider_runtime_status_read=(
                bool(provider_runtime_status.get("providerRuntimeStatusRead"))
                if isinstance(provider_runtime_status, MappingABC)
                else False
            ),
            metadata={
                "workerRunId": worker_run_id,
                "dispatcherId": dispatcher_id,
                "workerAction": "provider_activation_skipped",
                "skipReason": skip_reason,
                "readableReason": readable_reason,
                "busyBackoffApplied": apply_busy_backoff,
            },
        )
        sequence = self._append_agent_dispatch(
            workspace_id,
            dispatch=skipped,
            action="worker_skipped",
            occurred_at=occurred_at,
        )
        return {
            "schema": "agent_dispatch_worker_item.v1",
            "dispatchId": dispatch.dispatch_id,
            "exchangeRequestId": dispatch.exchange_request_id,
            "targetAgentId": dispatch.target_agent_id,
            "targetHandleId": dispatch.target_handle_id,
            "targetProvider": dispatch.target_provider,
            "processed": False,
            "skipped": True,
            "skipReason": skip_reason,
            "readableReason": readable_reason,
            "message": message,
            "busyBackoff": {
                "applied": apply_busy_backoff,
                "busySkipCount": busy_skip_count,
                "lastBusySkipAt": (
                    occurred_at.isoformat() if apply_busy_backoff else None
                ),
                "busyRetryDelaySeconds": busy_retry_delay_seconds,
                "nextAttemptAfter": (
                    next_attempt_after.isoformat()
                    if next_attempt_after is not None
                    else dispatch.to_metadata().get("nextAttemptAfter")
                ),
                "maximumDelaySeconds": 60,
            },
            "providerRuntimeStatus": provider_runtime_status,
            "agentDispatch": {
                **skipped.to_metadata(),
                "sourceEventSequence": sequence,
            },
        }

    def _record_agent_dispatch_worker_failure(
        self,
        workspace_id: WorkspaceId,
        *,
        dispatch: AgentDispatchRecord,
        worker_run_id: str,
        dispatcher_id: str,
        failure_category: str,
        failure_reason: str,
        retryable: bool,
        occurred_at: datetime,
    ) -> Mapping[str, object]:
        failed = dispatch.active_copy(
            status=AgentDispatchStatus.FAILED,
            updated_at=occurred_at,
            clear_next_attempt_after=True,
            attempt_count=dispatch.attempt_count + 1,
            provider_runtime_state_supported=False,
            provider_runtime_state="activation_failed",
            provider_state_source="agent_dispatch_worker",
            provider_activation_executed=False,
            provider_runtime_status_read=False,
            metadata={
                "workerRunId": worker_run_id,
                "dispatcherId": dispatcher_id,
                "workerAction": "provider_activation_precheck_failed",
                "failureCategory": failure_category,
                "failureReason": failure_reason,
                "retryable": retryable,
            },
        )
        sequence = self._append_agent_dispatch(
            workspace_id,
            dispatch=failed,
            action="worker_failed",
            occurred_at=occurred_at,
        )
        return {
            "schema": "agent_dispatch_worker_item.v1",
            "dispatchId": dispatch.dispatch_id,
            "exchangeRequestId": dispatch.exchange_request_id,
            "targetAgentId": dispatch.target_agent_id,
            "targetHandleId": dispatch.target_handle_id,
            "processed": True,
            "skipped": False,
            "finalStatus": AgentDispatchStatus.FAILED.value,
            "failureCategory": failure_category,
            "failureReason": failure_reason,
            "agentDispatch": {
                **failed.to_metadata(),
                "sourceEventSequence": sequence,
            },
        }

    def _activate_agent_dispatch_provider(
        self,
        workspace_id: WorkspaceId,
        *,
        dispatch: AgentDispatchRecord,
        provider: str,
        database_path: str,
        workspace_root: str,
        plugins_directory: str,
        config_path: str | None,
        handoff_directory: str | None,
        platform_workspace_root: str | None,
        claude_executable: str,
        claude_default_platform_workspace_add_dir: bool,
        claude_add_dirs: Sequence[str],
        claude_allowed_tools: Sequence[str],
        claude_permission_mode: str | None,
        claude_settings_path: str | None,
        codex_executable: str,
        codex_default_platform_workspace_add_dir: bool,
        codex_add_dirs: Sequence[str],
        codex_sandbox_mode: str | None,
        codex_approval_policy: str | None,
        codex_git_repo_check_policy: CodexGitRepoCheckPolicy | str,
        codex_git_repo_check_policy_source: str,
        hermes_executable: str,
        hermes_home: str | None,
        hermes_source_tag: str,
        hermes_max_turns: int | None,
        activation_timeout_seconds: int,
        occurred_at: datetime,
    ) -> Mapping[str, object]:
        if dispatch.target_handle_id is None:
            raise ValueError("targetHandleId is required for provider activation.")
        if provider == "claude":
            return self.activate_claude_registered_session(
                workspace_id,
                agent_id=dispatch.target_agent_id,
                handle_id=dispatch.target_handle_id,
                exchange_request_id=dispatch.exchange_request_id,
                database_path=database_path,
                workspace_root=workspace_root,
                plugins_directory=plugins_directory,
                config_path=config_path,
                handoff_directory=handoff_directory,
                claude_executable=claude_executable,
                platform_workspace_root=platform_workspace_root,
                default_platform_workspace_add_dir=(
                    claude_default_platform_workspace_add_dir
                ),
                add_dirs=tuple(claude_add_dirs),
                allowed_tools=tuple(claude_allowed_tools),
                permission_mode=claude_permission_mode,
                settings_path=claude_settings_path,
                dry_run=False,
                timeout_seconds=activation_timeout_seconds,
                occurred_at=occurred_at,
            )
        if provider == "codex":
            return self.activate_codex_registered_session(
                workspace_id,
                agent_id=dispatch.target_agent_id,
                handle_id=dispatch.target_handle_id,
                exchange_request_id=dispatch.exchange_request_id,
                database_path=database_path,
                workspace_root=workspace_root,
                plugins_directory=plugins_directory,
                config_path=config_path,
                handoff_directory=handoff_directory,
                codex_executable=codex_executable,
                platform_workspace_root=platform_workspace_root,
                default_platform_workspace_add_dir=(
                    codex_default_platform_workspace_add_dir
                ),
                add_dirs=tuple(codex_add_dirs),
                sandbox_mode=codex_sandbox_mode,
                approval_policy=codex_approval_policy,
                git_repo_check_policy=codex_git_repo_check_policy,
                git_repo_check_policy_source=codex_git_repo_check_policy_source,
                dry_run=False,
                timeout_seconds=activation_timeout_seconds,
                occurred_at=occurred_at,
            )
        if provider == "hermes":
            return self.activate_hermes_registered_session(
                workspace_id,
                agent_id=dispatch.target_agent_id,
                handle_id=dispatch.target_handle_id,
                exchange_request_id=dispatch.exchange_request_id,
                database_path=database_path,
                workspace_root=workspace_root,
                plugins_directory=plugins_directory,
                config_path=config_path,
                handoff_directory=handoff_directory,
                hermes_executable=hermes_executable,
                hermes_home=hermes_home,
                platform_workspace_root=platform_workspace_root,
                source_tag=hermes_source_tag,
                max_turns=hermes_max_turns,
                dry_run=False,
                timeout_seconds=activation_timeout_seconds,
                occurred_at=occurred_at,
            )
        raise ValueError("unsupported target provider.")

    def _agent_dispatch_final_status_from_activation(
        self,
        workspace_id: WorkspaceId,
        *,
        dispatch: AgentDispatchRecord,
        activation: Mapping[str, object] | None,
    ) -> AgentDispatchStatus:
        request = self._latest_agent_exchange_request_by_id(
            workspace_id,
            dispatch.exchange_request_id,
        )
        request_responded = (
            request is not None
            and request.terminal_reason is AgentExchangeRequestTerminalReason.RESPONDED
        )
        if (
            activation is not None
            and activation.get("expectedSessionVerification") == "mismatch"
        ):
            return AgentDispatchStatus.FAILED
        if activation is not None and (
            bool(activation.get("targetResponseCompleted")) or request_responded
        ):
            return AgentDispatchStatus.COMPLETED
        if activation is None:
            return AgentDispatchStatus.FAILED
        status = str(activation.get("status") or "")
        if status == "failed":
            if activation.get("retryable") is True:
                return AgentDispatchStatus.RETRY_SCHEDULED
            return AgentDispatchStatus.FAILED
        if bool(activation.get("providerCommandStarted")) or status in {
            "delivered",
            "skipped",
        }:
            return AgentDispatchStatus.WAITING_RESPONSE
        return AgentDispatchStatus.FAILED

    def _agent_dispatch_worker_activation_summary(
        self,
        provider: str,
        *,
        activation: Mapping[str, object] | None,
    ) -> Mapping[str, object] | None:
        if activation is None:
            return None
        summary: dict[str, object] = {
            "schema": "agent_dispatch_worker_activation_summary.v1",
            "provider": provider,
            "activationAttemptId": activation.get("activationAttemptId"),
            "status": activation.get("status"),
            "sourceEventSequence": activation.get("sourceEventSequence"),
            "wakeTicketId": activation.get("wakeTicketId"),
            "providerCommandStarted": bool(activation.get("providerCommandStarted")),
            "sessionContinuityVerified": bool(
                activation.get("sessionContinuityVerified")
            ),
            "expectedSessionVerification": activation.get(
                "expectedSessionVerification"
            ),
            "expectedSessionVerified": bool(
                activation.get("expectedSessionVerified")
            ),
            "responseInstanceVerified": bool(
                activation.get("responseInstanceVerified")
            ),
            "responseRequiresUserReview": bool(
                activation.get("responseRequiresUserReview")
            ),
            "cliReportedSessionId": activation.get("cliReportedSessionId"),
            "runtimeHomeSource": activation.get("runtimeHomeSource"),
            "targetResponseCompleted": bool(
                activation.get("targetResponseCompleted")
            ),
            "failureCategory": activation.get("failureCategory"),
            "failureReason": activation.get("failureReason"),
            "retryable": activation.get("retryable"),
            "gitRepoCheckPolicy": activation.get("gitRepoCheckPolicy"),
            "gitRepoCheckPolicySource": activation.get("gitRepoCheckPolicySource"),
            "skipGitRepoCheckRendered": activation.get("skipGitRepoCheckRendered"),
        }
        return {key: value for key, value in summary.items() if value is not None}

    def _agent_dispatch_activation_payload(
        self,
        provider: str,
        activation_result: Mapping[str, object],
    ) -> Mapping[str, object]:
        key_by_provider = {
            "claude": "claudeRegisteredSessionActivation",
            "codex": "codexRegisteredSessionActivation",
            "hermes": "hermesRegisteredSessionActivation",
        }
        key = key_by_provider[provider]
        payload = activation_result.get(key)
        if not isinstance(payload, MappingABC):
            raise ValueError("provider activation payload is missing.")
        return payload

    def _agent_dispatch_runtime_state_for_status(
        self,
        status: AgentDispatchStatus,
    ) -> str:
        if status is AgentDispatchStatus.COMPLETED:
            return "target_response_completed"
        if status is AgentDispatchStatus.WAITING_RESPONSE:
            return "provider_command_started"
        if status is AgentDispatchStatus.RETRY_SCHEDULED:
            return "activation_retry_scheduled"
        if status is AgentDispatchStatus.FAILED:
            return "activation_failed"
        return "unknown"

    def _resolve_agent_dispatch_provider(
        self,
        workspace_id: WorkspaceId,
        dispatch: AgentDispatchRecord,
    ) -> str | None:
        provider = _normalize_agent_dispatch_provider(dispatch.target_provider)
        if provider is not None:
            return provider
        if dispatch.target_handle_id is None:
            return None
        if (
            self._latest_claude_session_handle_by_id(
                workspace_id,
                dispatch.target_handle_id,
            )
            is not None
        ):
            return "claude"
        if (
            self._latest_codex_session_handle_by_id(
                workspace_id,
                dispatch.target_handle_id,
            )
            is not None
        ):
            return "codex"
        if (
            self._latest_hermes_session_handle_by_id(
                workspace_id,
                dispatch.target_handle_id,
            )
            is not None
        ):
            return "hermes"
        return None

    def _require_agent_endpoint_provider_handle(
        self,
        workspace_id: WorkspaceId,
        *,
        provider: str,
        provider_handle_id: str,
        agent_id: str,
    ) -> Mapping[str, object]:
        handle = self._agent_endpoint_provider_handle(
            workspace_id,
            provider=provider,
            provider_handle_id=provider_handle_id,
        )
        if handle is None:
            raise ValueError("provider handle not found.")
        if provider == "claude":
            if handle.state is not ClaudeRegisteredSessionHandleState.ACTIVE:
                raise ValueError("provider handle is not active.")
        elif provider == "codex":
            if handle.state is not CodexRegisteredSessionHandleState.ACTIVE:
                raise ValueError("provider handle is not active.")
        elif provider == "hermes":
            if handle.state is not HermesRegisteredSessionHandleState.ACTIVE:
                raise ValueError("provider handle is not active.")
        if handle.agent_id != agent_id:
            raise ValueError("provider handle agentId does not match endpoint agentId.")
        return handle.to_metadata()

    def _agent_endpoint_provider_handle_metadata(
        self,
        workspace_id: WorkspaceId,
        *,
        provider: str,
        provider_handle_id: str,
    ) -> Mapping[str, object] | None:
        handle = self._agent_endpoint_provider_handle(
            workspace_id,
            provider=provider,
            provider_handle_id=provider_handle_id,
        )
        return handle.to_metadata() if handle is not None else None

    def _agent_endpoint_provider_handle(
        self,
        workspace_id: WorkspaceId,
        *,
        provider: str,
        provider_handle_id: str,
    ):
        if provider == "claude":
            return self._latest_claude_session_handle_by_id(
                workspace_id,
                provider_handle_id,
            )
        if provider == "codex":
            return self._latest_codex_session_handle_by_id(
                workspace_id,
                provider_handle_id,
            )
        if provider == "hermes":
            return self._latest_hermes_session_handle_by_id(
                workspace_id,
                provider_handle_id,
            )
        raise ValueError("provider must be one of: claude, codex, hermes.")

    def list_agent_exchange_requests(
        self,
        workspace_id: WorkspaceId | str,
        *,
        source_agent_id: AgentId | str | None = None,
        target_agent_id: AgentId | str | None = None,
        status: AgentExchangeRequestStatus | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        resolved_source = (
            self._require_workspace_agent(
                resolved_workspace_id,
                source_agent_id,
            ).registration.agent_id.value
            if source_agent_id is not None
            else None
        )
        resolved_target = (
            self._require_workspace_agent(
                resolved_workspace_id,
                target_agent_id,
            ).registration.agent_id.value
            if target_agent_id is not None
            else None
        )
        resolved_status = (
            status.value
            if isinstance(status, AgentExchangeRequestStatus)
            else status
        )
        records = self._latest_agent_exchange_requests(resolved_workspace_id).values()
        filtered = [
            request
            for request in records
            if (resolved_source is None or request.source_agent_id == resolved_source)
            and (resolved_target is None or request.target_agent_id == resolved_target)
            and (resolved_status is None or request.status.value == resolved_status)
        ]
        return {
            "agentExchangeRequests": [
                request.to_metadata()
                for request in sorted(
                    filtered,
                    key=lambda item: (
                        item.created_at,
                        item.exchange_request_id,
                    ),
                )
            ]
        }

    def get_agent_exchange_request_status(
        self,
        workspace_id: WorkspaceId | str,
        *,
        exchange_request_id: str,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        request = self._latest_agent_exchange_request_by_id(
            resolved_workspace_id,
            exchange_request_id,
        )
        response_source_status = _agent_response_source_status(request)
        timeline = self._agent_exchange_status_timeline(
            resolved_workspace_id,
            exchange_request_id=exchange_request_id,
            thread_id=request.thread_id if request is not None else None,
        )
        return {
            "agentExchangeRequest": (
                {
                    **request.to_metadata(),
                    "wakeDeliverySummary": self._agent_wake_delivery_summary(
                        resolved_workspace_id,
                        exchange_request_id=exchange_request_id,
                    ),
                    "responseSourceStatus": response_source_status,
                    "statusTimeline": timeline,
                    "readableStatusReason": _agent_request_readable_reason(request),
                }
                if request is not None
                else {
                    "schema": "agent_exchange_request.v1",
                    "exchangeRequestId": exchange_request_id,
                    "workspaceId": resolved_workspace_id.value,
                    "status": "missing",
                    "realRuntimeConnected": False,
                    "runtimeWakeTriggered": False,
                    "autoSharedContextAppendExecuted": False,
                    "fileBodiesRead": False,
                    "wakeDeliverySummary": self._agent_wake_delivery_summary(
                        resolved_workspace_id,
                        exchange_request_id=exchange_request_id,
                    ),
                    "responseSourceStatus": response_source_status,
                    "statusTimeline": timeline,
                    "readableStatusReason": _agent_request_readable_reason(request),
                }
            )
        }

    def respond_agent_exchange_request(
        self,
        workspace_id: WorkspaceId | str,
        *,
        exchange_request_id: str,
        responding_agent_id: AgentId | str,
        response_summary: str,
        requires_user_review: bool | None = None,
        metadata: Mapping[str, object] | None = None,
        responded_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        workspace_record = self._require_workspace(resolved_workspace_id)
        if workspace_record.workspace.status is WorkspaceStatus.ARCHIVED:
            raise ValueError("workspace is archived.")
        existing = self._require_agent_exchange_request(
            resolved_workspace_id,
            exchange_request_id,
        )
        if not existing.is_active():
            raise ValueError("agent exchange request is not active.")
        resolved_agent_id = self._require_workspace_agent(
            resolved_workspace_id,
            responding_agent_id,
        ).registration.agent_id
        if resolved_agent_id.value != existing.target_agent_id:
            raise ValueError("respondingAgentId must match targetAgentId.")
        timestamp = responded_at or _utc_now()
        responded = existing.responded_copy(
            response_summary=response_summary,
            responded_by_agent_id=resolved_agent_id.value,
            responded_at=timestamp,
            requires_user_review=requires_user_review,
            metadata=metadata,
        )
        sequence = self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=resolved_workspace_id,
                event_kind=PlatformEventKind.AGENT_EXCHANGE_REQUEST_CHANGED,
                aggregate_type="agent_exchange_request",
                aggregate_id=responded.exchange_request_id,
                occurred_at=timestamp,
                payload={
                    "action": "responded",
                    "request": responded.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )
        thread_sequence = None
        if responded.thread_id is not None:
            thread_sequence = self._record_agent_exchange_thread_after_request_change(
                workspace_id=resolved_workspace_id,
                request=responded,
                action="request_responded",
                occurred_at=timestamp,
            )
        return {
            "agentExchangeRequest": {
                **responded.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "sourceEventSequence": sequence,
            "threadSourceEventSequence": thread_sequence,
            "responded": True,
        }

    def close_agent_exchange_request(
        self,
        workspace_id: WorkspaceId | str,
        *,
        exchange_request_id: str,
        terminal_reason: AgentExchangeRequestTerminalReason | str = (
            AgentExchangeRequestTerminalReason.CLOSED
        ),
        requires_user_review: bool | None = None,
        metadata: Mapping[str, object] | None = None,
        closed_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        workspace_record = self._require_workspace(resolved_workspace_id)
        if workspace_record.workspace.status is WorkspaceStatus.ARCHIVED:
            raise ValueError("workspace is archived.")
        existing = self._require_agent_exchange_request(
            resolved_workspace_id,
            exchange_request_id,
        )
        if not existing.is_active():
            raise ValueError("agent exchange request is not active.")
        timestamp = closed_at or _utc_now()
        closed = existing.closed_copy(
            terminal_reason=terminal_reason,
            closed_at=timestamp,
            requires_user_review=requires_user_review,
            metadata=metadata,
        )
        sequence = self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=resolved_workspace_id,
                event_kind=PlatformEventKind.AGENT_EXCHANGE_REQUEST_CHANGED,
                aggregate_type="agent_exchange_request",
                aggregate_id=closed.exchange_request_id,
                occurred_at=timestamp,
                payload={
                    "action": "closed",
                    "request": closed.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )
        thread_sequence = None
        if closed.thread_id is not None:
            thread_sequence = self._record_agent_exchange_thread_after_request_change(
                workspace_id=resolved_workspace_id,
                request=closed,
                action="request_closed",
                occurred_at=timestamp,
            )
        return {
            "agentExchangeRequest": {
                **closed.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "sourceEventSequence": sequence,
            "threadSourceEventSequence": thread_sequence,
            "closed": True,
        }

    def agent_exchange_thread_instructions(
        self,
        workspace_id: WorkspaceId | str | None = None,
    ) -> Mapping[str, object]:
        return self.agent_exchange_request_instructions(workspace_id)

    def list_agent_exchange_threads(
        self,
        workspace_id: WorkspaceId | str,
        *,
        requesting_agent_id: AgentId | str | None = None,
        status: AgentExchangeThreadStatus | str | None = None,
        visibility: AgentExchangeThreadVisibility | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        resolved_requesting_agent_id = (
            self._require_workspace_agent(
                resolved_workspace_id,
                requesting_agent_id,
            ).registration.agent_id.value
            if requesting_agent_id is not None
            else None
        )
        resolved_status = (
            status.value if isinstance(status, AgentExchangeThreadStatus) else status
        )
        resolved_visibility = (
            visibility.value
            if isinstance(visibility, AgentExchangeThreadVisibility)
            else visibility
        )
        threads = self._latest_agent_exchange_threads(resolved_workspace_id).values()
        filtered = [
            thread
            for thread in threads
            if (
                resolved_requesting_agent_id is None
                or thread.is_visible_to(resolved_requesting_agent_id)
            )
            and (
                resolved_status is None
                or thread.thread_status.value == resolved_status
            )
            and (
                resolved_visibility is None
                or thread.visibility.value == resolved_visibility
            )
        ]
        return {
            "agentExchangeThreads": [
                thread.to_metadata()
                for thread in sorted(
                    filtered,
                    key=lambda item: (
                        item.created_at,
                        item.exchange_thread_id,
                    ),
                )
            ]
        }

    def get_agent_exchange_thread_status(
        self,
        workspace_id: WorkspaceId | str,
        *,
        thread_id: str,
        requesting_agent_id: AgentId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        thread = self._latest_agent_exchange_thread_by_id(
            resolved_workspace_id,
            thread_id,
        )
        if thread is None:
            return {
                "agentExchangeThread": {
                    "schema": "agent_exchange_thread.v1",
                    "exchangeThreadId": thread_id,
                    "threadId": thread_id,
                    "workspaceId": resolved_workspace_id.value,
                    "threadStatus": "missing",
                    "realRuntimeConnected": False,
                    "runtimeWakeTriggered": False,
                    "autoSharedContextAppendExecuted": False,
                    "fileBodiesRead": False,
                }
            }
        if requesting_agent_id is not None:
            resolved_agent_id = self._require_workspace_agent(
                resolved_workspace_id,
                requesting_agent_id,
            ).registration.agent_id.value
            if not thread.is_visible_to(resolved_agent_id):
                raise ValueError("agent exchange thread is not visible to requesting agent.")
        return {"agentExchangeThread": thread.to_metadata()}

    def list_agent_exchange_thread_requests(
        self,
        workspace_id: WorkspaceId | str,
        *,
        thread_id: str,
        requesting_agent_id: AgentId | str | None = None,
    ) -> Mapping[str, object]:
        thread = self._require_visible_agent_exchange_thread(
            _workspace_id(workspace_id),
            thread_id,
            requesting_agent_id,
        )
        records = self._latest_agent_exchange_requests(
            WorkspaceId(thread.workspace_id)
        ).values()
        return {
            "agentExchangeThread": thread.to_metadata(),
            "agentExchangeRequests": [
                request.to_metadata()
                for request in sorted(
                    (
                        request
                        for request in records
                        if request.thread_id == thread.exchange_thread_id
                    ),
                    key=lambda item: (
                        item.created_at,
                        item.exchange_request_id,
                    ),
                )
            ],
        }

    def create_agent_exchange_thread_follow_up(
        self,
        workspace_id: WorkspaceId | str,
        *,
        thread_id: str,
        source_agent_id: AgentId | str,
        target_agent_id: AgentId | str,
        request_kind: AgentExchangeRequestKind | str,
        request_summary: str,
        parent_request_id: str | None = None,
        exchange_request_id: str | None = None,
        detail_refs: tuple[str, ...] = (),
        linked_task_id: TaskId | str | None = None,
        linked_conversation_id: ConversationId | str | None = None,
        linked_activation_id: str | None = None,
        linked_delegated_wake_grant_id: str | None = None,
        requires_user_review: bool = False,
        metadata: Mapping[str, object] | None = None,
        created_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        thread = self._require_agent_exchange_thread(resolved_workspace_id, thread_id)
        if not thread.is_active():
            raise ValueError("agent exchange thread is not active.")
        if parent_request_id is None:
            parent_request_id = self._latest_thread_request_id(
                resolved_workspace_id,
                thread.exchange_thread_id,
            )
        return self.create_agent_exchange_request(
            resolved_workspace_id,
            exchange_request_id=exchange_request_id,
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            request_kind=request_kind,
            request_summary=request_summary,
            detail_refs=detail_refs,
            linked_task_id=linked_task_id,
            linked_conversation_id=linked_conversation_id,
            linked_activation_id=linked_activation_id,
            linked_delegated_wake_grant_id=linked_delegated_wake_grant_id,
            parent_request_id=parent_request_id,
            root_request_id=thread.root_request_id,
            thread_id=thread.exchange_thread_id,
            requires_user_review=requires_user_review,
            metadata=metadata,
            created_at=created_at,
            event_id=event_id,
        )

    def update_agent_exchange_thread_visibility(
        self,
        workspace_id: WorkspaceId | str,
        *,
        thread_id: str,
        updated_by_agent_id: AgentId | str,
        visibility: AgentExchangeThreadVisibility | str,
        metadata: Mapping[str, object] | None = None,
        updated_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        workspace_record = self._require_workspace(resolved_workspace_id)
        if workspace_record.workspace.status is WorkspaceStatus.ARCHIVED:
            raise ValueError("workspace is archived.")
        thread = self._require_agent_exchange_thread(resolved_workspace_id, thread_id)
        resolved_agent_id = self._require_workspace_agent(
            resolved_workspace_id,
            updated_by_agent_id,
        ).registration.agent_id.value
        if resolved_agent_id not in set(thread.participant_agent_ids):
            raise ValueError("only thread participants may update thread visibility.")
        timestamp = updated_at or _utc_now()
        updated = thread.visibility_copy(
            visibility=visibility,
            updated_by_agent_id=resolved_agent_id,
            updated_at=timestamp,
            metadata=metadata,
        )
        sequence = self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=resolved_workspace_id,
                event_kind=PlatformEventKind.AGENT_EXCHANGE_THREAD_CHANGED,
                aggregate_type="agent_exchange_thread",
                aggregate_id=updated.exchange_thread_id,
                occurred_at=timestamp,
                payload={
                    "action": "visibility_updated",
                    "thread": updated.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )
        return {
            "agentExchangeThread": {
                **updated.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "sourceEventSequence": sequence,
            "updated": True,
        }

    def close_agent_exchange_thread(
        self,
        workspace_id: WorkspaceId | str,
        *,
        thread_id: str,
        terminal_reason: AgentExchangeThreadTerminalReason | str = (
            AgentExchangeThreadTerminalReason.CLOSED
        ),
        closed_by_agent_id: AgentId | str | None = None,
        metadata: Mapping[str, object] | None = None,
        closed_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        workspace_record = self._require_workspace(resolved_workspace_id)
        if workspace_record.workspace.status is WorkspaceStatus.ARCHIVED:
            raise ValueError("workspace is archived.")
        thread = self._require_agent_exchange_thread(resolved_workspace_id, thread_id)
        if not thread.is_active():
            raise ValueError("agent exchange thread is not active.")
        if closed_by_agent_id is not None:
            resolved_agent_id = self._require_workspace_agent(
                resolved_workspace_id,
                closed_by_agent_id,
            ).registration.agent_id.value
            if resolved_agent_id not in set(thread.participant_agent_ids):
                raise ValueError("only thread participants may close a thread.")
        timestamp = closed_at or _utc_now()
        closed = thread.closed_copy(
            terminal_reason=terminal_reason,
            closed_at=timestamp,
            metadata=metadata,
        )
        sequence = self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=resolved_workspace_id,
                event_kind=PlatformEventKind.AGENT_EXCHANGE_THREAD_CHANGED,
                aggregate_type="agent_exchange_thread",
                aggregate_id=closed.exchange_thread_id,
                occurred_at=timestamp,
                payload={
                    "action": "closed",
                    "thread": closed.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )
        return {
            "agentExchangeThread": {
                **closed.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "sourceEventSequence": sequence,
            "closed": True,
        }

    def agent_wake_instructions(
        self,
        workspace_id: WorkspaceId | str | None = None,
        *,
        agent_id: AgentId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = (
            _workspace_id(workspace_id)
            if workspace_id is not None
            else None
        )
        resolved_agent_id = None
        if resolved_workspace_id is not None:
            self._require_workspace(resolved_workspace_id)
            if agent_id is not None:
                resolved_agent_id = self._require_workspace_agent(
                    resolved_workspace_id,
                    agent_id,
                ).registration.agent_id
        return agent_wake_interface_metadata(
            workspace_id=(
                resolved_workspace_id.value
                if resolved_workspace_id is not None
                else None
            ),
            agent_id=resolved_agent_id.value if resolved_agent_id is not None else None,
        )

    def run_agent_wake_once(
        self,
        workspace_id: WorkspaceId | str,
        *,
        agent_id: AgentId | str,
        profile: AgentWakeProfile | Mapping[str, object] | None = None,
        database_path: str,
        workspace_root: str,
        plugins_directory: str,
        config_path: str | None = None,
        runtime_profile_path: str | None = None,
        dry_run: bool = False,
        occurred_at: datetime | None = None,
        simulate_crash_after_marker: bool = False,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        resolved_agent_id = self._require_workspace_agent(
            resolved_workspace_id,
            agent_id,
        ).registration.agent_id
        resolved_profile = self._resolve_agent_wake_profile(
            profile,
            workspace_id=resolved_workspace_id,
            agent_id=resolved_agent_id,
            config_path=config_path,
        )
        timestamp = occurred_at or _utc_now()
        requests = [
            request
            for request in self._latest_agent_exchange_requests(
                resolved_workspace_id
            ).values()
            if request.target_agent_id == resolved_agent_id.value
            and request.is_active()
            and not request.is_expired(timestamp)
        ]
        requests = sorted(
            requests,
            key=lambda item: (item.created_at, item.exchange_request_id),
        )
        all_delivery_records = self._latest_agent_wake_delivery_records(
            resolved_workspace_id
        )
        attempts: list[Mapping[str, object]] = []
        tickets: list[Mapping[str, object]] = []
        delivered_count = 0
        skipped_count = 0
        failed_count = 0
        for request in requests:
            request_records = [
                record
                for record in all_delivery_records
                if record.exchange_request_id == request.exchange_request_id
                and record.target_agent_id == resolved_agent_id.value
            ]
            skip_reason = self._agent_wake_skip_reason(
                profile=resolved_profile,
                records=request_records,
                checked_at=timestamp,
            )
            ticket = self._build_agent_wake_ticket(
                request=request,
                profile=resolved_profile,
                database_path=database_path,
                workspace_root=workspace_root,
                plugins_directory=plugins_directory,
                runtime_profile_path=runtime_profile_path,
                delivery_attempt_count=len(
                    [
                        record
                        for record in request_records
                        if record.counts_as_delivery_marker()
                    ]
                ),
                created_at=timestamp,
            )
            if skip_reason is not None:
                skipped_count += 1
                attempts.append(
                    {
                        "exchangeRequestId": request.exchange_request_id,
                        "threadId": request.thread_id,
                        "status": AgentWakeDeliveryStatus.SKIPPED.value,
                        "skipReason": skip_reason,
                        "ticket": ticket.to_metadata(),
                    }
                )
                continue
            if dry_run:
                attempts.append(
                    {
                        "exchangeRequestId": request.exchange_request_id,
                        "threadId": request.thread_id,
                        "status": AgentWakeDeliveryStatus.DRY_RUN.value,
                        "dryRun": True,
                        "ticket": ticket.to_metadata(),
                    }
                )
                tickets.append(ticket.to_metadata())
                continue

            ticket_path = self._agent_wake_ticket_path(
                profile=resolved_profile,
                ticket=ticket,
                workspace_root=workspace_root,
            )
            lease = AgentWakeDeliveryRecord(
                workspace_id=resolved_workspace_id.value,
                target_agent_id=resolved_agent_id.value,
                exchange_request_id=request.exchange_request_id,
                thread_id=request.thread_id or request.exchange_request_id,
                wake_ticket_id=ticket.wake_ticket_id,
                wake_mode=resolved_profile.wake_mode,
                status=AgentWakeDeliveryStatus.LEASED,
                ticket_path=ticket_path,
                created_at=timestamp,
                lease_recorded_before_command=True,
            )
            lease_sequence = self._append_agent_wake_delivery(
                resolved_workspace_id,
                delivery=lease,
                ticket=ticket,
                action="leased",
                occurred_at=timestamp,
            )
            if simulate_crash_after_marker:
                raise RuntimeError("simulated crash after wake marker.")
            delivered = self._deliver_agent_wake_ticket(
                profile=resolved_profile,
                ticket=ticket,
                ticket_path=ticket_path,
                occurred_at=timestamp,
            )
            sequence = self._append_agent_wake_delivery(
                resolved_workspace_id,
                delivery=delivered,
                ticket=ticket,
                action=delivered.status.value,
                occurred_at=delivered.completed_at or timestamp,
            )
            if delivered.status is AgentWakeDeliveryStatus.FAILED:
                failed_count += 1
            else:
                delivered_count += 1
                tickets.append(ticket.to_metadata())
            attempts.append(
                {
                    **delivered.to_metadata(),
                    "sourceEventSequence": sequence,
                    "leaseSourceEventSequence": lease_sequence,
                    "ticket": ticket.to_metadata(),
                }
            )
        return {
            "agentWakeRun": {
                "schema": "agent_wake_run.v1",
                "workspaceId": resolved_workspace_id.value,
                "agentId": resolved_agent_id.value,
                "wakeMode": resolved_profile.wake_mode.value,
                "enabled": resolved_profile.enabled,
                "dryRun": dry_run,
                "pendingRequestCount": len(requests),
                "deliveredCount": delivered_count,
                "skippedCount": skipped_count,
                "failedCount": failed_count,
                "attempts": attempts,
                "tickets": tickets,
                "realRuntimeConnected": False,
                "providerPromptInjected": False,
                "fileBodiesRead": False,
                "credentialStored": False,
                "checkedAt": timestamp.isoformat(),
            }
        }

    def list_agent_wake_deliveries(
        self,
        workspace_id: WorkspaceId | str,
        *,
        agent_id: AgentId | str | None = None,
        exchange_request_id: str | None = None,
        wake_ticket_id: str | None = None,
        status: AgentWakeDeliveryStatus | str | None = None,
        limit: int = 20,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        resolved_agent_id = (
            self._require_workspace_agent(
                resolved_workspace_id,
                agent_id,
            ).registration.agent_id.value
            if agent_id is not None
            else None
        )
        if limit < 1:
            raise ValueError("limit must be greater than zero.")
        resolved_status = status.value if isinstance(status, AgentWakeDeliveryStatus) else status
        if resolved_status is not None:
            _enum_value(AgentWakeDeliveryStatus, resolved_status, "status")
        entries = [
            entry
            for entry in self._agent_wake_delivery_entries(resolved_workspace_id)
            if (
                resolved_agent_id is None
                or entry["delivery"]["targetAgentId"] == resolved_agent_id
            )
            and (
                exchange_request_id is None
                or entry["delivery"]["exchangeRequestId"] == exchange_request_id
            )
            and (
                wake_ticket_id is None
                or entry["delivery"]["wakeTicketId"] == wake_ticket_id
            )
            and (
                resolved_status is None
                or entry["delivery"]["status"] == resolved_status
            )
        ]
        entries = sorted(
            entries,
            key=lambda item: int(item["sourceEventSequence"]),
            reverse=True,
        )
        return {
            "agentWakeDeliveries": entries[:limit],
            "count": min(len(entries), limit),
            "totalMatched": len(entries),
            "realRuntimeConnected": False,
            "providerPromptInjected": False,
            "fileBodiesRead": False,
            "credentialStored": False,
        }

    def get_agent_wake_status(
        self,
        workspace_id: WorkspaceId | str,
        *,
        exchange_request_id: str,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        request = self._latest_agent_exchange_request_by_id(
            resolved_workspace_id,
            exchange_request_id,
        )
        return {
            "agentWakeStatus": {
                **self._agent_wake_delivery_summary(
                    resolved_workspace_id,
                    exchange_request_id=exchange_request_id,
                ),
                "schema": "agent_wake_status.v1",
                "workspaceId": resolved_workspace_id.value,
                "exchangeRequestId": exchange_request_id,
                "requestStatus": (
                    request.status.value if request is not None else "missing"
                ),
                "requestTargetAgentId": (
                    request.target_agent_id if request is not None else None
                ),
            }
        }

    def get_agent_wake_ticket(
        self,
        workspace_id: WorkspaceId | str,
        *,
        exchange_request_id: str | None = None,
        wake_ticket_id: str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        if exchange_request_id is None and wake_ticket_id is None:
            raise ValueError("exchangeRequestId or wakeTicketId is required.")
        entries = [
            entry
            for entry in self._agent_wake_delivery_entries(resolved_workspace_id)
            if (
                exchange_request_id is None
                or entry["delivery"]["exchangeRequestId"] == exchange_request_id
            )
            and (
                wake_ticket_id is None
                or entry["delivery"]["wakeTicketId"] == wake_ticket_id
            )
        ]
        if not entries:
            return {
                "agentWakeTicket": {
                    "schema": "agent_wake_ticket.v2",
                    "workspaceId": resolved_workspace_id.value,
                    "exchangeRequestId": exchange_request_id,
                    "wakeTicketId": wake_ticket_id,
                    "status": "missing",
                    "realRuntimeConnected": False,
                    "providerPromptInjected": False,
                    "fileBodiesRead": False,
                    "credentialStored": False,
                }
            }
        latest = max(entries, key=lambda item: int(item["sourceEventSequence"]))
        return {
            "agentWakeTicket": {
                **latest["ticket"],
                "sourceEventSequence": latest["sourceEventSequence"],
                "delivery": latest["delivery"],
                "status": "found",
            }
        }

    def register_claude_session_handle(
        self,
        workspace_id: WorkspaceId | str,
        *,
        agent_id: AgentId | str,
        claude_session_uuid: str,
        cwd: str,
        created_by: str,
        reason: str,
        handle_id: str | None = None,
        source_path: str | None = None,
        metadata: Mapping[str, object] | None = None,
        created_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        resolved_agent_id = self._require_workspace_agent(
            resolved_workspace_id,
            agent_id,
        ).registration.agent_id
        resolved_handle_id = handle_id or f"claude-session-handle-{uuid4()}"
        existing = self._latest_claude_session_handle_by_id(
            resolved_workspace_id,
            resolved_handle_id,
        )
        if (
            existing is not None
            and existing.state is ClaudeRegisteredSessionHandleState.ACTIVE
        ):
            raise ValueError("Claude session handle already exists.")
        timestamp = created_at or _utc_now()
        handle = ClaudeRegisteredSessionHandle.from_mapping(
            {
                "workspaceId": resolved_workspace_id.value,
                "agentId": resolved_agent_id.value,
                "handleId": resolved_handle_id,
                "claudeSessionUuid": claude_session_uuid,
                "cwd": cwd,
                "sourcePath": source_path,
                "createdBy": created_by,
                "reason": reason,
                "metadata": dict(metadata or {}),
                "createdAt": timestamp.isoformat(),
                "updatedAt": timestamp.isoformat(),
            }
        )
        sequence = self._append_claude_session_handle(
            resolved_workspace_id,
            handle=handle,
            action="registered",
            occurred_at=timestamp,
            event_id=event_id,
        )
        return {
            "claudeSessionHandle": {
                **handle.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "sourceEventSequence": sequence,
            "created": True,
        }

    def list_claude_session_handles(
        self,
        workspace_id: WorkspaceId | str,
        *,
        agent_id: AgentId | str | None = None,
        include_inactive: bool = False,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        resolved_agent_id = (
            self._require_workspace_agent(resolved_workspace_id, agent_id)
            .registration.agent_id.value
            if agent_id is not None
            else None
        )
        handles = [
            handle
            for handle in self._latest_claude_session_handles(
                resolved_workspace_id
            ).values()
            if (resolved_agent_id is None or handle.agent_id == resolved_agent_id)
            and (
                include_inactive
                or handle.state is ClaudeRegisteredSessionHandleState.ACTIVE
            )
        ]
        return {
            "claudeSessionHandles": [
                handle.to_metadata()
                for handle in sorted(handles, key=lambda item: item.handle_id)
            ]
        }

    def get_claude_session_handle(
        self,
        workspace_id: WorkspaceId | str,
        *,
        handle_id: str,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        handle = self._latest_claude_session_handle_by_id(
            resolved_workspace_id,
            handle_id,
        )
        if handle is None:
            raise ValueError("Claude session handle not found.")
        return {"claudeSessionHandle": handle.to_metadata()}

    def deactivate_claude_session_handle(
        self,
        workspace_id: WorkspaceId | str,
        *,
        handle_id: str,
        deactivated_by: str,
        reason: str,
        deactivated_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        handle = self._latest_claude_session_handle_by_id(
            resolved_workspace_id,
            handle_id,
        )
        if handle is None:
            raise ValueError("Claude session handle not found.")
        timestamp = deactivated_at or _utc_now()
        inactive = handle.inactive_copy(
            deactivated_by=deactivated_by,
            reason=reason,
            deactivated_at=timestamp,
        )
        sequence = self._append_claude_session_handle(
            resolved_workspace_id,
            handle=inactive,
            action="deactivated",
            occurred_at=timestamp,
            event_id=event_id,
        )
        return {
            "claudeSessionHandle": {
                **inactive.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "sourceEventSequence": sequence,
            "deactivated": True,
        }

    def activate_claude_registered_session(
        self,
        workspace_id: WorkspaceId | str,
        *,
        agent_id: AgentId | str,
        handle_id: str,
        exchange_request_id: str,
        database_path: str,
        workspace_root: str,
        plugins_directory: str,
        config_path: str | None = None,
        handoff_directory: str | None = None,
        claude_executable: str = "claude",
        platform_workspace_root: str | None = None,
        default_platform_workspace_add_dir: bool = True,
        add_dirs: Sequence[str] = (),
        allowed_tools: Sequence[str] = (),
        permission_mode: str | None = None,
        settings_path: str | None = None,
        dry_run: bool = True,
        timeout_seconds: int = 120,
        occurred_at: datetime | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        resolved_agent_id = self._require_workspace_agent(
            resolved_workspace_id,
            agent_id,
        ).registration.agent_id
        handle = self._latest_claude_session_handle_by_id(
            resolved_workspace_id,
            handle_id,
        )
        if handle is None:
            raise ValueError("Claude session handle not found.")
        if handle.agent_id != resolved_agent_id.value:
            raise ValueError("Claude session handle agentId mismatch.")
        if handle.state is not ClaudeRegisteredSessionHandleState.ACTIVE:
            raise ValueError("Claude session handle is inactive.")
        request = self._latest_agent_exchange_request_by_id(
            resolved_workspace_id,
            exchange_request_id,
        )
        if request is None:
            raise ValueError("agent exchange request not found.")
        if request.target_agent_id != resolved_agent_id.value:
            raise ValueError("request targetAgentId does not match agentId.")
        timestamp = occurred_at or _utc_now()
        profile = AgentWakeProfile.from_mapping(
            {
                "workspaceId": resolved_workspace_id.value,
                "agentId": resolved_agent_id.value,
                "wakeMode": AgentWakeMode.HANDOFF_FILE.value,
                **(
                    {"handoffDirectory": handoff_directory}
                    if handoff_directory is not None
                    else {}
                ),
            }
        )
        ticket = self._build_agent_wake_ticket(
            request=request,
            profile=profile,
            database_path=database_path,
            workspace_root=workspace_root,
            plugins_directory=plugins_directory,
            runtime_profile_path=None,
            delivery_attempt_count=len(
                [
                    record
                    for record in self._latest_agent_wake_delivery_records(
                        resolved_workspace_id
                    )
                    if record.exchange_request_id == request.exchange_request_id
                    and record.target_agent_id == resolved_agent_id.value
                    and record.counts_as_delivery_marker()
                ]
            ),
            created_at=timestamp,
        )
        ticket_path = self._agent_wake_ticket_path(
            profile=profile,
            ticket=ticket,
            workspace_root=workspace_root,
        )
        if ticket_path is None:
            raise ValueError("ticket path is required for Claude activation.")
        resolved_platform_workspace_root = _resolve_platform_workspace_root(
            explicit_root=platform_workspace_root,
            database_path=database_path,
            plugins_directory=plugins_directory,
            ticket_path=ticket_path,
            workspace_root=workspace_root,
        )
        if not dry_run and default_platform_workspace_add_dir:
            Path(resolved_platform_workspace_root).mkdir(parents=True, exist_ok=True)
        resolved_add_dirs = (
            (resolved_platform_workspace_root,) if default_platform_workspace_add_dir else ()
        ) + tuple(add_dirs)
        executable_resolution = resolve_claude_executable(claude_executable)
        executable_resolution_kwargs = {
            "requested_claude_executable": executable_resolution.requested_executable,
            "resolved_claude_executable": executable_resolution.resolved_executable,
            "executable_resolution_source": executable_resolution.resolution_source,
            "executable_resolution_warning": executable_resolution.warning,
        }
        argv = render_claude_resume_argv(
            handle.claude_session_uuid,
            claude_executable=executable_resolution.resolved_executable,
            add_dirs=resolved_add_dirs,
            allowed_tools=tuple(allowed_tools),
            permission_mode=permission_mode,
            settings_path=settings_path,
        )
        stdin_text = build_claude_activation_stdin(
            ticket_path=ticket_path,
            request_get_command=str(ticket.recommended_cli.get("requestGet") or ""),
            thread_get_command=str(ticket.recommended_cli.get("threadGet") or ""),
            respond_command_template=str(
                ticket.recommended_cli.get("respondTemplate") or ""
            ),
        )
        existing_attempt = self._latest_claude_activation_for_request(
            resolved_workspace_id,
            handle_id=handle_id,
            exchange_request_id=exchange_request_id,
        )
        if (
            not dry_run
            and existing_attempt is not None
            and existing_attempt.provider_command_started
        ):
            attempt = ClaudeRegisteredSessionActivationAttempt(
                workspace_id=resolved_workspace_id.value,
                agent_id=resolved_agent_id.value,
                handle_id=handle.handle_id,
                exchange_request_id=request.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                status=ClaudeRegisteredSessionActivationStatus.SKIPPED,
                ticket_path=ticket_path,
                cwd=handle.cwd,
                command_argv_summary=argv,
                platform_workspace_root=resolved_platform_workspace_root,
                add_dir_paths=tuple(resolved_add_dirs),
                allowed_tools=tuple(allowed_tools),
                permission_mode=permission_mode,
                settings_path=settings_path,
                **executable_resolution_kwargs,
                skip_reason="already_started_for_request_and_handle",
                created_at=timestamp,
                completed_at=timestamp,
            )
            sequence = self._append_claude_activation_attempt(
                resolved_workspace_id,
                attempt=attempt,
                ticket=ticket,
                action="skipped",
                occurred_at=timestamp,
            )
            return {
                "claudeRegisteredSessionActivation": {
                    **attempt.to_metadata(),
                    "sourceEventSequence": sequence,
                },
                "claudeSessionHandle": handle.to_metadata(),
                "ticket": ticket.to_metadata(),
                "stdinPreview": stdin_text,
                "skipped": True,
            }
        if dry_run:
            attempt = ClaudeRegisteredSessionActivationAttempt(
                workspace_id=resolved_workspace_id.value,
                agent_id=resolved_agent_id.value,
                handle_id=handle.handle_id,
                exchange_request_id=request.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                status=ClaudeRegisteredSessionActivationStatus.DRY_RUN,
                ticket_path=ticket_path,
                cwd=handle.cwd,
                command_argv_summary=argv,
                dry_run=True,
                platform_workspace_root=resolved_platform_workspace_root,
                add_dir_paths=tuple(resolved_add_dirs),
                allowed_tools=tuple(allowed_tools),
                permission_mode=permission_mode,
                settings_path=settings_path,
                **executable_resolution_kwargs,
                created_at=timestamp,
                completed_at=timestamp,
            )
            sequence = self._append_claude_activation_attempt(
                resolved_workspace_id,
                attempt=attempt,
                ticket=ticket,
                action="dry_run",
                occurred_at=timestamp,
            )
            return {
                "claudeRegisteredSessionActivation": {
                    **attempt.to_metadata(),
                    "sourceEventSequence": sequence,
                },
                "claudeSessionHandle": handle.to_metadata(),
                "ticket": ticket.to_metadata(),
                "stdinPreview": stdin_text,
                "executeRequired": True,
            }

        try:
            self._write_agent_wake_ticket_file(ticket, ticket_path)
        except OSError as exc:
            attempt = ClaudeRegisteredSessionActivationAttempt(
                workspace_id=resolved_workspace_id.value,
                agent_id=resolved_agent_id.value,
                handle_id=handle.handle_id,
                exchange_request_id=request.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                status=ClaudeRegisteredSessionActivationStatus.FAILED,
                ticket_path=ticket_path,
                cwd=handle.cwd,
                command_argv_summary=argv,
                failure_reason=f"{exc.__class__.__name__}: {exc}",
                provider_command_started=False,
                platform_workspace_root=resolved_platform_workspace_root,
                add_dir_paths=tuple(resolved_add_dirs),
                allowed_tools=tuple(allowed_tools),
                permission_mode=permission_mode,
                settings_path=settings_path,
                **executable_resolution_kwargs,
                created_at=timestamp,
                completed_at=_utc_now(),
            )
            sequence = self._append_claude_activation_attempt(
                resolved_workspace_id,
                attempt=attempt,
                ticket=ticket,
                action="failed",
                occurred_at=attempt.completed_at or timestamp,
            )
            return {
                "claudeRegisteredSessionActivation": {
                    **attempt.to_metadata(),
                    "sourceEventSequence": sequence,
                },
                "claudeSessionHandle": handle.to_metadata(),
                "ticket": ticket.to_metadata(),
            }
        delivery = AgentWakeDeliveryRecord(
            workspace_id=resolved_workspace_id.value,
            target_agent_id=resolved_agent_id.value,
            exchange_request_id=request.exchange_request_id,
            thread_id=ticket.thread_id,
            wake_ticket_id=ticket.wake_ticket_id,
            wake_mode=AgentWakeMode.HANDOFF_FILE,
            status=AgentWakeDeliveryStatus.DELIVERED,
            ticket_path=ticket_path,
            created_at=timestamp,
            completed_at=timestamp,
        )
        delivery_sequence = self._append_agent_wake_delivery(
            resolved_workspace_id,
            delivery=delivery,
            ticket=ticket,
            action="delivered",
            occurred_at=timestamp,
        )
        try:
            completed = subprocess.run(
                argv,
                cwd=handle.cwd,
                input=stdin_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                shell=False,
                timeout=timeout_seconds,
            )
            completed_at = _utc_now()
            response_capture_mode = "claude_stdout_stream_json"
            response_capture_status = (
                "not_attempted_command_failed"
                if completed.returncode != 0
                else None
            )
            response_capture_failure_reason = None
            response_source_sequence = None
            request_after_command = self._latest_agent_exchange_request_by_id(
                resolved_workspace_id,
                request.exchange_request_id,
            )
            request_responded_by_target = (
                request_after_command is not None
                and request_after_command.terminal_reason
                is AgentExchangeRequestTerminalReason.RESPONDED
                and request_after_command.responded_by_agent_id == resolved_agent_id.value
            )
            target_response_completed = bool(request_responded_by_target)
            if completed.returncode == 0:
                captured_response = extract_claude_stream_json_response(
                    completed.stdout,
                )
                if request_responded_by_target:
                    response_capture_status = "already_responded"
                elif not captured_response:
                    response_capture_status = "no_response_text"
                elif (
                    request_after_command is not None
                    and request_after_command.is_active()
                ):
                    response_summary = truncate_auto_captured_response(
                        captured_response,
                        max_chars=request_after_command.max_response_length,
                    )
                    try:
                        response_result = self.respond_agent_exchange_request(
                            resolved_workspace_id,
                            exchange_request_id=request.exchange_request_id,
                            responding_agent_id=resolved_agent_id,
                            response_summary=response_summary,
                            metadata={
                                "responseSource": "claude_stdout_auto_capture",
                                "captureMode": response_capture_mode,
                                "wakeTicketId": ticket.wake_ticket_id,
                                "handleId": handle.handle_id,
                            },
                            responded_at=completed_at,
                        )
                    except ValueError as exc:
                        response_capture_status = "respond_failed"
                        response_capture_failure_reason = (
                            f"{exc.__class__.__name__}: {exc}"
                        )
                    else:
                        response_capture_status = "recorded"
                        response_source_sequence = int(
                            response_result.get("sourceEventSequence", 0)
                        )
                        target_response_completed = True
                else:
                    response_capture_status = "request_not_active"
            attempt = ClaudeRegisteredSessionActivationAttempt(
                workspace_id=resolved_workspace_id.value,
                agent_id=resolved_agent_id.value,
                handle_id=handle.handle_id,
                exchange_request_id=request.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                status=(
                    ClaudeRegisteredSessionActivationStatus.DELIVERED
                    if completed.returncode == 0
                    else ClaudeRegisteredSessionActivationStatus.FAILED
                ),
                ticket_path=ticket_path,
                cwd=handle.cwd,
                command_argv_summary=argv,
                command_exit_code=completed.returncode,
                stdout_tail=summarize_process_text(completed.stdout),
                stderr_tail=summarize_process_text(completed.stderr),
                failure_reason=(
                    None if completed.returncode == 0 else "command_exit_nonzero"
                ),
                provider_command_started=True,
                session_continuity_verified=claude_output_mentions_session(
                    completed.stdout,
                    handle.claude_session_uuid,
                ),
                target_response_completed=target_response_completed,
                response_capture_mode=response_capture_mode,
                response_capture_status=response_capture_status,
                response_capture_failure_reason=response_capture_failure_reason,
                auto_captured_response_source_event_sequence=response_source_sequence,
                platform_workspace_root=resolved_platform_workspace_root,
                add_dir_paths=tuple(resolved_add_dirs),
                allowed_tools=tuple(allowed_tools),
                permission_mode=permission_mode,
                settings_path=settings_path,
                **executable_resolution_kwargs,
                created_at=timestamp,
                completed_at=completed_at,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            completed_at = _utc_now()
            attempt = ClaudeRegisteredSessionActivationAttempt(
                workspace_id=resolved_workspace_id.value,
                agent_id=resolved_agent_id.value,
                handle_id=handle.handle_id,
                exchange_request_id=request.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                status=ClaudeRegisteredSessionActivationStatus.FAILED,
                ticket_path=ticket_path,
                cwd=handle.cwd,
                command_argv_summary=argv,
                failure_reason=f"{exc.__class__.__name__}: {exc}",
                provider_command_started=not isinstance(exc, OSError),
                platform_workspace_root=resolved_platform_workspace_root,
                add_dir_paths=tuple(resolved_add_dirs),
                allowed_tools=tuple(allowed_tools),
                permission_mode=permission_mode,
                settings_path=settings_path,
                **executable_resolution_kwargs,
                created_at=timestamp,
                completed_at=completed_at,
            )
        sequence = self._append_claude_activation_attempt(
            resolved_workspace_id,
            attempt=attempt,
            ticket=ticket,
            action=attempt.status.value,
            occurred_at=attempt.completed_at or timestamp,
        )
        return {
            "claudeRegisteredSessionActivation": {
                **attempt.to_metadata(),
                "sourceEventSequence": sequence,
                "wakeDeliverySourceEventSequence": delivery_sequence,
            },
            "claudeSessionHandle": handle.to_metadata(),
            "ticket": ticket.to_metadata(),
        }

    def register_codex_session_handle(
        self,
        workspace_id: WorkspaceId | str,
        *,
        agent_id: AgentId | str,
        codex_session_id: str,
        cwd: str,
        created_by: str,
        reason: str,
        handle_id: str | None = None,
        source_path: str | None = None,
        metadata: Mapping[str, object] | None = None,
        created_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        resolved_agent_id = self._require_workspace_agent(
            resolved_workspace_id,
            agent_id,
        ).registration.agent_id
        resolved_handle_id = handle_id or f"codex-session-handle-{uuid4()}"
        existing = self._latest_codex_session_handle_by_id(
            resolved_workspace_id,
            resolved_handle_id,
        )
        if (
            existing is not None
            and existing.state is CodexRegisteredSessionHandleState.ACTIVE
        ):
            raise ValueError("Codex session handle already exists.")
        timestamp = created_at or _utc_now()
        handle = CodexRegisteredSessionHandle.from_mapping(
            {
                "workspaceId": resolved_workspace_id.value,
                "agentId": resolved_agent_id.value,
                "handleId": resolved_handle_id,
                "codexSessionId": codex_session_id,
                "cwd": cwd,
                "sourcePath": source_path,
                "createdBy": created_by,
                "reason": reason,
                "metadata": dict(metadata or {}),
                "createdAt": timestamp.isoformat(),
                "updatedAt": timestamp.isoformat(),
            }
        )
        sequence = self._append_codex_session_handle(
            resolved_workspace_id,
            handle=handle,
            action="registered",
            occurred_at=timestamp,
            event_id=event_id,
        )
        return {
            "codexSessionHandle": {
                **handle.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "sourceEventSequence": sequence,
            "created": True,
        }

    def list_codex_session_handles(
        self,
        workspace_id: WorkspaceId | str,
        *,
        agent_id: AgentId | str | None = None,
        include_inactive: bool = False,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        resolved_agent_id = (
            self._require_workspace_agent(resolved_workspace_id, agent_id)
            .registration.agent_id.value
            if agent_id is not None
            else None
        )
        handles = [
            handle
            for handle in self._latest_codex_session_handles(resolved_workspace_id).values()
            if (resolved_agent_id is None or handle.agent_id == resolved_agent_id)
            and (
                include_inactive
                or handle.state is CodexRegisteredSessionHandleState.ACTIVE
            )
        ]
        return {
            "codexSessionHandles": [
                handle.to_metadata()
                for handle in sorted(handles, key=lambda item: item.handle_id)
            ]
        }

    def get_codex_session_handle(
        self,
        workspace_id: WorkspaceId | str,
        *,
        handle_id: str,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        handle = self._latest_codex_session_handle_by_id(
            resolved_workspace_id,
            handle_id,
        )
        if handle is None:
            raise ValueError("Codex session handle not found.")
        return {"codexSessionHandle": handle.to_metadata()}

    def deactivate_codex_session_handle(
        self,
        workspace_id: WorkspaceId | str,
        *,
        handle_id: str,
        deactivated_by: str,
        reason: str,
        deactivated_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        handle = self._latest_codex_session_handle_by_id(
            resolved_workspace_id,
            handle_id,
        )
        if handle is None:
            raise ValueError("Codex session handle not found.")
        timestamp = deactivated_at or _utc_now()
        inactive = handle.inactive_copy(
            deactivated_by=deactivated_by,
            reason=reason,
            deactivated_at=timestamp,
        )
        sequence = self._append_codex_session_handle(
            resolved_workspace_id,
            handle=inactive,
            action="deactivated",
            occurred_at=timestamp,
            event_id=event_id,
        )
        return {
            "codexSessionHandle": {
                **inactive.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "sourceEventSequence": sequence,
            "deactivated": True,
        }

    def activate_codex_registered_session(
        self,
        workspace_id: WorkspaceId | str,
        *,
        agent_id: AgentId | str,
        handle_id: str,
        exchange_request_id: str,
        database_path: str,
        workspace_root: str,
        plugins_directory: str,
        config_path: str | None = None,
        handoff_directory: str | None = None,
        codex_executable: str = "codex",
        platform_workspace_root: str | None = None,
        default_platform_workspace_add_dir: bool = True,
        add_dirs: Sequence[str] = (),
        sandbox_mode: str | None = None,
        approval_policy: str | None = None,
        git_repo_check_policy: CodexGitRepoCheckPolicy | str = (
            CodexGitRepoCheckPolicy.SKIP
        ),
        git_repo_check_policy_source: str = "default",
        dry_run: bool = True,
        timeout_seconds: int = 120,
        occurred_at: datetime | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        resolved_agent_id = self._require_workspace_agent(
            resolved_workspace_id,
            agent_id,
        ).registration.agent_id
        handle = self._latest_codex_session_handle_by_id(
            resolved_workspace_id,
            handle_id,
        )
        if handle is None:
            raise ValueError("Codex session handle not found.")
        if handle.agent_id != resolved_agent_id.value:
            raise ValueError("Codex session handle agentId mismatch.")
        if handle.state is not CodexRegisteredSessionHandleState.ACTIVE:
            raise ValueError("Codex session handle is inactive.")
        request = self._latest_agent_exchange_request_by_id(
            resolved_workspace_id,
            exchange_request_id,
        )
        if request is None:
            raise ValueError("agent exchange request not found.")
        if request.target_agent_id != resolved_agent_id.value:
            raise ValueError("request targetAgentId does not match agentId.")
        timestamp = occurred_at or _utc_now()
        activation_attempt_id = f"codex-session-activation-{uuid4()}"
        profile = AgentWakeProfile.from_mapping(
            {
                "workspaceId": resolved_workspace_id.value,
                "agentId": resolved_agent_id.value,
                "wakeMode": AgentWakeMode.HANDOFF_FILE.value,
                **(
                    {"handoffDirectory": handoff_directory}
                    if handoff_directory is not None
                    else {}
                ),
            }
        )
        ticket = self._build_agent_wake_ticket(
            request=request,
            profile=profile,
            database_path=database_path,
            workspace_root=workspace_root,
            plugins_directory=plugins_directory,
            runtime_profile_path=None,
            delivery_attempt_count=len(
                [
                    record
                    for record in self._latest_agent_wake_delivery_records(
                        resolved_workspace_id
                    )
                    if record.exchange_request_id == request.exchange_request_id
                    and record.target_agent_id == resolved_agent_id.value
                    and record.counts_as_delivery_marker()
                ]
            ),
            created_at=timestamp,
        )
        ticket_path = self._agent_wake_ticket_path(
            profile=profile,
            ticket=ticket,
            workspace_root=workspace_root,
        )
        if ticket_path is None:
            raise ValueError("ticket path is required for Codex activation.")
        resolved_platform_workspace_root = _resolve_platform_workspace_root(
            explicit_root=platform_workspace_root,
            database_path=database_path,
            plugins_directory=plugins_directory,
            ticket_path=ticket_path,
            workspace_root=workspace_root,
        )
        if not dry_run and default_platform_workspace_add_dir:
            Path(resolved_platform_workspace_root).mkdir(parents=True, exist_ok=True)
        output_last_message_path = _codex_output_last_message_path(
            platform_workspace_root=resolved_platform_workspace_root,
            exchange_request_id=request.exchange_request_id,
            activation_attempt_id=activation_attempt_id,
        )
        if not dry_run:
            Path(output_last_message_path).parent.mkdir(parents=True, exist_ok=True)
        resolved_add_dirs = (
            (resolved_platform_workspace_root,) if default_platform_workspace_add_dir else ()
        ) + tuple(add_dirs)
        resolved_git_repo_check_policy = normalize_codex_git_repo_check_policy(
            git_repo_check_policy
        )
        git_repo_check_kwargs = {
            "git_repo_check_policy": resolved_git_repo_check_policy,
            "git_repo_check_policy_source": git_repo_check_policy_source,
            "skip_git_repo_check_rendered": (
                resolved_git_repo_check_policy is CodexGitRepoCheckPolicy.SKIP
            ),
        }
        executable_resolution = resolve_codex_executable(codex_executable)
        executable_resolution_kwargs = {
            "requested_codex_executable": executable_resolution.requested_executable,
            "resolved_codex_executable": executable_resolution.resolved_executable,
            "executable_resolution_source": executable_resolution.resolution_source,
            "executable_resolution_warning": executable_resolution.warning,
        }
        argv = render_codex_exec_resume_argv(
            handle.codex_session_id,
            codex_executable=executable_resolution.resolved_executable,
            cwd=handle.cwd,
            add_dirs=resolved_add_dirs,
            sandbox_mode=sandbox_mode,
            approval_policy=approval_policy,
            git_repo_check_policy=resolved_git_repo_check_policy,
            output_last_message_path=output_last_message_path,
        )
        stdin_text = build_codex_activation_stdin(
            ticket_path=ticket_path,
            exchange_request_id=request.exchange_request_id,
            source_agent_id=request.source_agent_id,
            target_agent_id=request.target_agent_id,
            request_kind=request.request_kind.value,
            request_summary=request.request_summary,
        )
        existing_attempt = self._latest_codex_activation_for_request(
            resolved_workspace_id,
            handle_id=handle_id,
            exchange_request_id=exchange_request_id,
        )
        if (
            not dry_run
            and existing_attempt is not None
            and existing_attempt.provider_command_started
            and (
                existing_attempt.status
                is not CodexRegisteredSessionActivationStatus.STARTED
                or not _codex_started_attempt_is_stale(
                    existing_attempt,
                    occurred_at=timestamp,
                    timeout_seconds=timeout_seconds,
                )
            )
        ):
            attempt = CodexRegisteredSessionActivationAttempt(
                workspace_id=resolved_workspace_id.value,
                agent_id=resolved_agent_id.value,
                handle_id=handle.handle_id,
                exchange_request_id=request.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                status=CodexRegisteredSessionActivationStatus.SKIPPED,
                activation_attempt_id=activation_attempt_id,
                ticket_path=ticket_path,
                cwd=handle.cwd,
                command_argv_summary=argv,
                platform_workspace_root=resolved_platform_workspace_root,
                add_dir_paths=tuple(resolved_add_dirs),
                sandbox_mode=sandbox_mode,
                approval_policy=approval_policy,
                output_last_message_path=output_last_message_path,
                executable_preflight_status="not_run_skipped",
                **git_repo_check_kwargs,
                **executable_resolution_kwargs,
                skip_reason="already_started_for_request_and_handle",
                created_at=timestamp,
                completed_at=timestamp,
            )
            sequence = self._append_codex_activation_attempt(
                resolved_workspace_id,
                attempt=attempt,
                ticket=ticket,
                action="skipped",
                occurred_at=timestamp,
            )
            return {
                "codexRegisteredSessionActivation": {
                    **attempt.to_metadata(),
                    "sourceEventSequence": sequence,
                },
                "codexSessionHandle": handle.to_metadata(),
                "ticket": ticket.to_metadata(),
                "stdinPreview": stdin_text,
                "skipped": True,
            }
        if dry_run:
            attempt = CodexRegisteredSessionActivationAttempt(
                workspace_id=resolved_workspace_id.value,
                agent_id=resolved_agent_id.value,
                handle_id=handle.handle_id,
                exchange_request_id=request.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                status=CodexRegisteredSessionActivationStatus.DRY_RUN,
                activation_attempt_id=activation_attempt_id,
                ticket_path=ticket_path,
                cwd=handle.cwd,
                command_argv_summary=argv,
                dry_run=True,
                platform_workspace_root=resolved_platform_workspace_root,
                add_dir_paths=tuple(resolved_add_dirs),
                sandbox_mode=sandbox_mode,
                approval_policy=approval_policy,
                output_last_message_path=output_last_message_path,
                executable_preflight_status="not_run_dry_run",
                **git_repo_check_kwargs,
                **executable_resolution_kwargs,
                created_at=timestamp,
                completed_at=timestamp,
            )
            sequence = self._append_codex_activation_attempt(
                resolved_workspace_id,
                attempt=attempt,
                ticket=ticket,
                action="dry_run",
                occurred_at=timestamp,
            )
            return {
                "codexRegisteredSessionActivation": {
                    **attempt.to_metadata(),
                    "sourceEventSequence": sequence,
                },
                "codexSessionHandle": handle.to_metadata(),
                "ticket": ticket.to_metadata(),
                "stdinPreview": stdin_text,
                "executeRequired": True,
            }

        preflight = _run_codex_executable_preflight(
            executable_resolution.resolved_executable,
            timeout_seconds=min(timeout_seconds, 15),
        )
        if preflight["status"] != "passed":
            completed_at = _utc_now()
            failure_category = str(preflight.get("failureCategory") or "preflight_failed")
            attempt = CodexRegisteredSessionActivationAttempt(
                workspace_id=resolved_workspace_id.value,
                agent_id=resolved_agent_id.value,
                handle_id=handle.handle_id,
                exchange_request_id=request.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                status=CodexRegisteredSessionActivationStatus.FAILED,
                activation_attempt_id=activation_attempt_id,
                ticket_path=ticket_path,
                cwd=handle.cwd,
                command_argv_summary=argv,
                failure_reason=str(preflight.get("failureReason") or "preflight_failed"),
                provider_command_started=False,
                platform_workspace_root=resolved_platform_workspace_root,
                add_dir_paths=tuple(resolved_add_dirs),
                sandbox_mode=sandbox_mode,
                approval_policy=approval_policy,
                output_last_message_path=output_last_message_path,
                executable_preflight_status=str(preflight["status"]),
                executable_preflight_exit_code=preflight.get("exitCode"),
                executable_preflight_stdout_tail=preflight.get("stdoutTail"),
                executable_preflight_stderr_tail=preflight.get("stderrTail"),
                executable_preflight_failure_reason=preflight.get("failureReason"),
                failure_category=failure_category,
                failure_guidance=codex_failure_guidance(failure_category),
                retryable=codex_failure_retryable(failure_category),
                **git_repo_check_kwargs,
                **executable_resolution_kwargs,
                created_at=timestamp,
                completed_at=completed_at,
            )
            sequence = self._append_codex_activation_attempt(
                resolved_workspace_id,
                attempt=attempt,
                ticket=ticket,
                action="failed",
                occurred_at=completed_at,
            )
            return {
                "codexRegisteredSessionActivation": {
                    **attempt.to_metadata(),
                    "sourceEventSequence": sequence,
                },
                "codexSessionHandle": handle.to_metadata(),
                "ticket": ticket.to_metadata(),
            }

        try:
            self._write_agent_wake_ticket_file(ticket, ticket_path)
        except OSError as exc:
            failure_category = "ticket_write_failed"
            attempt = CodexRegisteredSessionActivationAttempt(
                workspace_id=resolved_workspace_id.value,
                agent_id=resolved_agent_id.value,
                handle_id=handle.handle_id,
                exchange_request_id=request.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                status=CodexRegisteredSessionActivationStatus.FAILED,
                activation_attempt_id=activation_attempt_id,
                ticket_path=ticket_path,
                cwd=handle.cwd,
                command_argv_summary=argv,
                failure_reason=f"{exc.__class__.__name__}: {exc}",
                failure_category=failure_category,
                failure_guidance=codex_failure_guidance(failure_category),
                retryable=codex_failure_retryable(failure_category),
                provider_command_started=False,
                platform_workspace_root=resolved_platform_workspace_root,
                add_dir_paths=tuple(resolved_add_dirs),
                sandbox_mode=sandbox_mode,
                approval_policy=approval_policy,
                output_last_message_path=output_last_message_path,
                executable_preflight_status=str(preflight["status"]),
                executable_preflight_exit_code=preflight.get("exitCode"),
                executable_preflight_stdout_tail=preflight.get("stdoutTail"),
                executable_preflight_stderr_tail=preflight.get("stderrTail"),
                executable_preflight_failure_reason=preflight.get("failureReason"),
                **git_repo_check_kwargs,
                **executable_resolution_kwargs,
                created_at=timestamp,
                completed_at=_utc_now(),
            )
            sequence = self._append_codex_activation_attempt(
                resolved_workspace_id,
                attempt=attempt,
                ticket=ticket,
                action="failed",
                occurred_at=attempt.completed_at or timestamp,
            )
            return {
                "codexRegisteredSessionActivation": {
                    **attempt.to_metadata(),
                    "sourceEventSequence": sequence,
                },
                "codexSessionHandle": handle.to_metadata(),
                "ticket": ticket.to_metadata(),
            }
        delivery = AgentWakeDeliveryRecord(
            workspace_id=resolved_workspace_id.value,
            target_agent_id=resolved_agent_id.value,
            exchange_request_id=request.exchange_request_id,
            thread_id=ticket.thread_id,
            wake_ticket_id=ticket.wake_ticket_id,
            wake_mode=AgentWakeMode.HANDOFF_FILE,
            status=AgentWakeDeliveryStatus.DELIVERED,
            ticket_path=ticket_path,
            lease_recorded_before_command=True,
            created_at=timestamp,
            completed_at=timestamp,
        )
        delivery_sequence = self._append_agent_wake_delivery(
            resolved_workspace_id,
            delivery=delivery,
            ticket=ticket,
            action="delivered",
            occurred_at=timestamp,
        )
        started_attempt = CodexRegisteredSessionActivationAttempt(
            workspace_id=resolved_workspace_id.value,
            agent_id=resolved_agent_id.value,
            handle_id=handle.handle_id,
            exchange_request_id=request.exchange_request_id,
            thread_id=ticket.thread_id,
            wake_ticket_id=ticket.wake_ticket_id,
            status=CodexRegisteredSessionActivationStatus.STARTED,
            activation_attempt_id=activation_attempt_id,
            ticket_path=ticket_path,
            cwd=handle.cwd,
            command_argv_summary=argv,
            provider_command_started=True,
            response_capture_mode="codex_exec_resume_json_last_message",
            response_capture_status="pending_provider_completion",
            platform_workspace_root=resolved_platform_workspace_root,
            add_dir_paths=tuple(resolved_add_dirs),
            sandbox_mode=sandbox_mode,
            approval_policy=approval_policy,
            output_last_message_path=output_last_message_path,
            executable_preflight_status=str(preflight["status"]),
            executable_preflight_exit_code=preflight.get("exitCode"),
            executable_preflight_stdout_tail=preflight.get("stdoutTail"),
            executable_preflight_stderr_tail=preflight.get("stderrTail"),
            executable_preflight_failure_reason=preflight.get("failureReason"),
            **git_repo_check_kwargs,
            **executable_resolution_kwargs,
            created_at=timestamp,
        )
        started_sequence: int | None = None

        def record_provider_command_started() -> None:
            nonlocal started_sequence
            started_sequence = self._append_codex_activation_attempt(
                resolved_workspace_id,
                attempt=started_attempt,
                ticket=ticket,
                action="started",
                occurred_at=timestamp,
            )

        try:
            completed = _run_codex_activation_process(
                argv,
                cwd=handle.cwd,
                stdin_text=stdin_text,
                output_last_message_path=output_last_message_path,
                timeout_seconds=timeout_seconds,
                on_started=record_provider_command_started,
            )
            if completed.timed_out:
                raise subprocess.TimeoutExpired(
                    argv,
                    timeout_seconds,
                    output=completed.stdout,
                    stderr=completed.stderr,
                )
            completed_at = _utc_now()
            last_message_text = _read_optional_text_file(output_last_message_path)
            provider_completed_for_response = (
                completed.returncode == 0
                or completed.terminated_after_response_capture
            )
            response_capture_mode = "codex_exec_resume_json_last_message"
            response_capture_status = (
                "not_attempted_command_failed"
                if not provider_completed_for_response
                else None
            )
            response_capture_failure_reason = None
            response_source_sequence = None
            request_after_command = self._latest_agent_exchange_request_by_id(
                resolved_workspace_id,
                request.exchange_request_id,
            )
            request_responded_by_target = (
                request_after_command is not None
                and request_after_command.terminal_reason
                is AgentExchangeRequestTerminalReason.RESPONDED
                and request_after_command.responded_by_agent_id == resolved_agent_id.value
            )
            target_response_completed = bool(request_responded_by_target)
            if provider_completed_for_response:
                captured_response = extract_codex_json_response(
                    completed.stdout,
                    last_message_text=last_message_text,
                )
                if request_responded_by_target:
                    response_capture_status = "already_responded"
                elif not captured_response:
                    response_capture_status = "no_response_text"
                elif (
                    request_after_command is not None
                    and request_after_command.is_active()
                ):
                    response_summary = truncate_codex_auto_captured_response(
                        captured_response,
                        max_chars=request_after_command.max_response_length,
                    )
                    try:
                        response_result = self.respond_agent_exchange_request(
                            resolved_workspace_id,
                            exchange_request_id=request.exchange_request_id,
                            responding_agent_id=resolved_agent_id,
                            response_summary=response_summary,
                            metadata={
                                "responseSource": "codex_exec_resume_auto_capture",
                                "captureMode": response_capture_mode,
                                "wakeTicketId": ticket.wake_ticket_id,
                                "handleId": handle.handle_id,
                            },
                            responded_at=completed_at,
                        )
                    except ValueError as exc:
                        response_capture_status = "respond_failed"
                        response_capture_failure_reason = (
                            f"{exc.__class__.__name__}: {exc}"
                        )
                    else:
                        response_capture_status = "recorded"
                        response_source_sequence = int(
                            response_result.get("sourceEventSequence", 0)
                        )
                        target_response_completed = True
                else:
                    response_capture_status = "request_not_active"
            attempt = CodexRegisteredSessionActivationAttempt(
                workspace_id=resolved_workspace_id.value,
                agent_id=resolved_agent_id.value,
                handle_id=handle.handle_id,
                exchange_request_id=request.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                status=(
                    CodexRegisteredSessionActivationStatus.DELIVERED
                    if provider_completed_for_response
                    else CodexRegisteredSessionActivationStatus.FAILED
                ),
                activation_attempt_id=activation_attempt_id,
                ticket_path=ticket_path,
                cwd=handle.cwd,
                command_argv_summary=argv,
                command_exit_code=completed.returncode,
                stdout_tail=summarize_codex_process_text(completed.stdout),
                stderr_tail=summarize_codex_process_text(completed.stderr),
                failure_reason=(
                    None
                    if provider_completed_for_response
                    else classify_codex_command_exit_failure(completed.stderr)
                ),
                failure_category=(
                    None
                    if provider_completed_for_response
                    else classify_codex_command_exit_failure(completed.stderr)
                ),
                failure_guidance=(
                    None
                    if provider_completed_for_response
                    else codex_failure_guidance(
                        classify_codex_command_exit_failure(completed.stderr)
                    )
                ),
                retryable=(
                    None
                    if provider_completed_for_response
                    else codex_failure_retryable(
                        classify_codex_command_exit_failure(completed.stderr)
                    )
                ),
                provider_command_started=True,
                provider_process_terminated_after_response_capture=(
                    completed.terminated_after_response_capture
                ),
                session_continuity_verified=codex_output_mentions_session(
                    completed.stdout,
                    handle.codex_session_id,
                ),
                target_response_completed=target_response_completed,
                response_capture_mode=response_capture_mode,
                response_capture_status=response_capture_status,
                response_capture_failure_reason=response_capture_failure_reason,
                auto_captured_response_source_event_sequence=response_source_sequence,
                platform_workspace_root=resolved_platform_workspace_root,
                add_dir_paths=tuple(resolved_add_dirs),
                sandbox_mode=sandbox_mode,
                approval_policy=approval_policy,
                output_last_message_path=output_last_message_path,
                executable_preflight_status=str(preflight["status"]),
                executable_preflight_exit_code=preflight.get("exitCode"),
                executable_preflight_stdout_tail=preflight.get("stdoutTail"),
                executable_preflight_stderr_tail=preflight.get("stderrTail"),
                executable_preflight_failure_reason=preflight.get("failureReason"),
                **git_repo_check_kwargs,
                **executable_resolution_kwargs,
                created_at=timestamp,
                completed_at=completed_at,
            )
        except subprocess.TimeoutExpired as exc:
            completed_at = _utc_now()
            timeout_stdout = _subprocess_timeout_text(exc.stdout)
            timeout_stderr = _subprocess_timeout_text(exc.stderr)
            last_message_text = _read_optional_text_file(output_last_message_path)
            captured_response = extract_codex_json_response(
                timeout_stdout,
                last_message_text=last_message_text,
            )
            response_capture_mode = "codex_output_last_message_timeout_fallback"
            response_capture_status = "no_response_text_after_command_timeout"
            response_capture_failure_reason = None
            response_source_sequence = None
            request_after_command = self._latest_agent_exchange_request_by_id(
                resolved_workspace_id,
                request.exchange_request_id,
            )
            request_responded_by_target = (
                request_after_command is not None
                and request_after_command.terminal_reason
                is AgentExchangeRequestTerminalReason.RESPONDED
                and request_after_command.responded_by_agent_id
                == resolved_agent_id.value
            )
            target_response_completed = bool(request_responded_by_target)
            if request_responded_by_target:
                response_capture_status = "already_responded_after_command_timeout"
            elif (
                captured_response
                and request_after_command is not None
                and request_after_command.is_active()
            ):
                response_summary = truncate_codex_auto_captured_response(
                    captured_response,
                    max_chars=request_after_command.max_response_length,
                )
                try:
                    response_result = self.respond_agent_exchange_request(
                        resolved_workspace_id,
                        exchange_request_id=request.exchange_request_id,
                        responding_agent_id=resolved_agent_id,
                        response_summary=response_summary,
                        requires_user_review=True,
                        metadata={
                            "responseSource": (
                                "codex_exec_resume_timeout_auto_capture"
                            ),
                            "captureMode": response_capture_mode,
                            "wakeTicketId": ticket.wake_ticket_id,
                            "handleId": handle.handle_id,
                            "providerProcessTimedOut": True,
                        },
                        responded_at=completed_at,
                    )
                except ValueError as response_exc:
                    response_capture_status = "respond_failed_after_command_timeout"
                    response_capture_failure_reason = (
                        f"{response_exc.__class__.__name__}: {response_exc}"
                    )
                else:
                    response_capture_status = "recorded_after_command_timeout"
                    response_source_sequence = int(
                        response_result.get("sourceEventSequence", 0)
                    )
                    target_response_completed = True
            elif captured_response:
                response_capture_status = "request_not_active_after_command_timeout"
            failure_category = "command_timeout"
            attempt = CodexRegisteredSessionActivationAttempt(
                workspace_id=resolved_workspace_id.value,
                agent_id=resolved_agent_id.value,
                handle_id=handle.handle_id,
                exchange_request_id=request.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                status=CodexRegisteredSessionActivationStatus.FAILED,
                activation_attempt_id=activation_attempt_id,
                ticket_path=ticket_path,
                cwd=handle.cwd,
                command_argv_summary=argv,
                stdout_tail=summarize_codex_process_text(timeout_stdout),
                stderr_tail=summarize_codex_process_text(timeout_stderr),
                failure_reason=(
                    "command_timeout_after_response_capture"
                    if target_response_completed
                    else f"{exc.__class__.__name__}: {exc}"
                ),
                failure_category=failure_category,
                failure_guidance=(
                    "Codex wrote a final message before the provider process timed out; "
                    "Beacon recovered it and marked the response for user review."
                    if target_response_completed
                    else codex_failure_guidance(failure_category)
                ),
                retryable=(
                    False
                    if target_response_completed
                    else codex_failure_retryable(failure_category)
                ),
                provider_command_started=True,
                provider_process_timed_out=True,
                session_continuity_verified=codex_output_mentions_session(
                    timeout_stdout,
                    handle.codex_session_id,
                ),
                target_response_completed=target_response_completed,
                response_capture_mode=response_capture_mode,
                response_capture_status=response_capture_status,
                response_capture_failure_reason=response_capture_failure_reason,
                auto_captured_response_source_event_sequence=response_source_sequence,
                platform_workspace_root=resolved_platform_workspace_root,
                add_dir_paths=tuple(resolved_add_dirs),
                sandbox_mode=sandbox_mode,
                approval_policy=approval_policy,
                output_last_message_path=output_last_message_path,
                executable_preflight_status=str(preflight["status"]),
                executable_preflight_exit_code=preflight.get("exitCode"),
                executable_preflight_stdout_tail=preflight.get("stdoutTail"),
                executable_preflight_stderr_tail=preflight.get("stderrTail"),
                executable_preflight_failure_reason=preflight.get("failureReason"),
                **git_repo_check_kwargs,
                **executable_resolution_kwargs,
                created_at=timestamp,
                completed_at=completed_at,
            )
        except OSError as exc:
            completed_at = _utc_now()
            failure_category = classify_codex_activation_failure(exc)
            attempt = CodexRegisteredSessionActivationAttempt(
                workspace_id=resolved_workspace_id.value,
                agent_id=resolved_agent_id.value,
                handle_id=handle.handle_id,
                exchange_request_id=request.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                status=CodexRegisteredSessionActivationStatus.FAILED,
                activation_attempt_id=activation_attempt_id,
                ticket_path=ticket_path,
                cwd=handle.cwd,
                command_argv_summary=argv,
                failure_reason=f"{exc.__class__.__name__}: {exc}",
                failure_category=failure_category,
                failure_guidance=codex_failure_guidance(failure_category),
                retryable=codex_failure_retryable(failure_category),
                provider_command_started=False,
                platform_workspace_root=resolved_platform_workspace_root,
                add_dir_paths=tuple(resolved_add_dirs),
                sandbox_mode=sandbox_mode,
                approval_policy=approval_policy,
                output_last_message_path=output_last_message_path,
                executable_preflight_status=str(preflight["status"]),
                executable_preflight_exit_code=preflight.get("exitCode"),
                executable_preflight_stdout_tail=preflight.get("stdoutTail"),
                executable_preflight_stderr_tail=preflight.get("stderrTail"),
                executable_preflight_failure_reason=preflight.get("failureReason"),
                **git_repo_check_kwargs,
                **executable_resolution_kwargs,
                created_at=timestamp,
                completed_at=completed_at,
            )
        sequence = self._append_codex_activation_attempt(
            resolved_workspace_id,
            attempt=attempt,
            ticket=ticket,
            action=attempt.status.value,
            occurred_at=attempt.completed_at or timestamp,
        )
        activation_metadata = {
            **attempt.to_metadata(),
            "sourceEventSequence": sequence,
            "wakeDeliverySourceEventSequence": delivery_sequence,
        }
        if started_sequence is not None:
            activation_metadata["providerCommandStartedSourceEventSequence"] = (
                started_sequence
            )
        return {
            "codexRegisteredSessionActivation": {
                **activation_metadata,
            },
            "codexSessionHandle": handle.to_metadata(),
            "ticket": ticket.to_metadata(),
        }

    def register_hermes_session_handle(
        self,
        workspace_id: WorkspaceId | str,
        *,
        agent_id: AgentId | str,
        hermes_session_id: str,
        cwd: str,
        created_by: str,
        reason: str,
        handle_id: str | None = None,
        source_path: str | None = None,
        metadata: Mapping[str, object] | None = None,
        created_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        resolved_agent_id = self._require_workspace_agent(
            resolved_workspace_id,
            agent_id,
        ).registration.agent_id
        resolved_handle_id = handle_id or f"hermes-session-handle-{uuid4()}"
        existing = self._latest_hermes_session_handle_by_id(
            resolved_workspace_id,
            resolved_handle_id,
        )
        if (
            existing is not None
            and existing.state is HermesRegisteredSessionHandleState.ACTIVE
        ):
            raise ValueError("Hermes session handle already exists.")
        timestamp = created_at or _utc_now()
        handle = HermesRegisteredSessionHandle.from_mapping(
            {
                "workspaceId": resolved_workspace_id.value,
                "agentId": resolved_agent_id.value,
                "handleId": resolved_handle_id,
                "hermesSessionId": hermes_session_id,
                "cwd": cwd,
                "sourcePath": source_path,
                "createdBy": created_by,
                "reason": reason,
                "metadata": dict(metadata or {}),
                "createdAt": timestamp.isoformat(),
                "updatedAt": timestamp.isoformat(),
            }
        )
        sequence = self._append_hermes_session_handle(
            resolved_workspace_id,
            handle=handle,
            action="registered",
            occurred_at=timestamp,
            event_id=event_id,
        )
        return {
            "hermesSessionHandle": {
                **handle.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "sourceEventSequence": sequence,
            "created": True,
        }

    def list_hermes_session_handles(
        self,
        workspace_id: WorkspaceId | str,
        *,
        agent_id: AgentId | str | None = None,
        include_inactive: bool = False,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        resolved_agent_id = (
            self._require_workspace_agent(resolved_workspace_id, agent_id)
            .registration.agent_id.value
            if agent_id is not None
            else None
        )
        handles = [
            handle
            for handle in self._latest_hermes_session_handles(
                resolved_workspace_id
            ).values()
            if (resolved_agent_id is None or handle.agent_id == resolved_agent_id)
            and (
                include_inactive
                or handle.state is HermesRegisteredSessionHandleState.ACTIVE
            )
        ]
        return {
            "hermesSessionHandles": [
                handle.to_metadata()
                for handle in sorted(handles, key=lambda item: item.handle_id)
            ]
        }

    def get_hermes_session_handle(
        self,
        workspace_id: WorkspaceId | str,
        *,
        handle_id: str,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        handle = self._latest_hermes_session_handle_by_id(
            resolved_workspace_id,
            handle_id,
        )
        if handle is None:
            raise ValueError("Hermes session handle not found.")
        return {"hermesSessionHandle": handle.to_metadata()}

    def deactivate_hermes_session_handle(
        self,
        workspace_id: WorkspaceId | str,
        *,
        handle_id: str,
        deactivated_by: str,
        reason: str,
        deactivated_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        handle = self._latest_hermes_session_handle_by_id(
            resolved_workspace_id,
            handle_id,
        )
        if handle is None:
            raise ValueError("Hermes session handle not found.")
        timestamp = deactivated_at or _utc_now()
        inactive = handle.inactive_copy(
            deactivated_by=deactivated_by,
            reason=reason,
            deactivated_at=timestamp,
        )
        sequence = self._append_hermes_session_handle(
            resolved_workspace_id,
            handle=inactive,
            action="deactivated",
            occurred_at=timestamp,
            event_id=event_id,
        )
        return {
            "hermesSessionHandle": {
                **inactive.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "sourceEventSequence": sequence,
            "deactivated": True,
        }

    def activate_hermes_registered_session(
        self,
        workspace_id: WorkspaceId | str,
        *,
        agent_id: AgentId | str,
        handle_id: str,
        exchange_request_id: str,
        database_path: str,
        workspace_root: str,
        plugins_directory: str,
        config_path: str | None = None,
        handoff_directory: str | None = None,
        hermes_executable: str = "hermes",
        hermes_home: str | None = None,
        platform_workspace_root: str | None = None,
        source_tag: str = "agent-os",
        max_turns: int | None = None,
        dry_run: bool = True,
        timeout_seconds: int = 120,
        occurred_at: datetime | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        resolved_agent_id = self._require_workspace_agent(
            resolved_workspace_id,
            agent_id,
        ).registration.agent_id
        handle = self._latest_hermes_session_handle_by_id(
            resolved_workspace_id,
            handle_id,
        )
        if handle is None:
            raise ValueError("Hermes session handle not found.")
        if handle.agent_id != resolved_agent_id.value:
            raise ValueError("Hermes session handle agentId mismatch.")
        if handle.state is not HermesRegisteredSessionHandleState.ACTIVE:
            raise ValueError("Hermes session handle is inactive.")
        request = self._latest_agent_exchange_request_by_id(
            resolved_workspace_id,
            exchange_request_id,
        )
        if request is None:
            raise ValueError("agent exchange request not found.")
        if request.target_agent_id != resolved_agent_id.value:
            raise ValueError("request targetAgentId does not match agentId.")
        stored_session_identity = _hermes_session_identity_from_handle(handle.metadata)
        stored_provider_session_id = stored_session_identity.get("providerSessionId")
        if (
            isinstance(stored_provider_session_id, str)
            and stored_provider_session_id.strip()
            and stored_provider_session_id.strip() != handle.hermes_session_id
        ):
            raise ValueError(
                "registered Hermes session identity does not match the handle session id."
            )
        runtime_home, runtime_home_source = _resolve_hermes_activation_home(
            explicit_home=hermes_home,
            stored_identity=stored_session_identity,
        )
        stored_session_source = stored_session_identity.get("sessionSource")
        registered_session_source = (
            stored_session_source.strip()
            if isinstance(stored_session_source, str)
            and stored_session_source.strip()
            else None
        )
        session_identity_kwargs = {
            "registered_provider_session_id": handle.hermes_session_id,
            "runtime_home": runtime_home,
            "runtime_home_source": runtime_home_source,
            "registered_session_source": registered_session_source,
        }
        provider_environment = os.environ.copy()
        if runtime_home is not None:
            provider_environment["HERMES_HOME"] = runtime_home
        timestamp = occurred_at or _utc_now()
        profile = AgentWakeProfile.from_mapping(
            {
                "workspaceId": resolved_workspace_id.value,
                "agentId": resolved_agent_id.value,
                "wakeMode": AgentWakeMode.HANDOFF_FILE.value,
                **(
                    {"handoffDirectory": handoff_directory}
                    if handoff_directory is not None
                    else {}
                ),
            }
        )
        ticket = self._build_agent_wake_ticket(
            request=request,
            profile=profile,
            database_path=database_path,
            workspace_root=workspace_root,
            plugins_directory=plugins_directory,
            runtime_profile_path=None,
            delivery_attempt_count=len(
                [
                    record
                    for record in self._latest_agent_wake_delivery_records(
                        resolved_workspace_id
                    )
                    if record.exchange_request_id == request.exchange_request_id
                    and record.target_agent_id == resolved_agent_id.value
                    and record.counts_as_delivery_marker()
                ]
            ),
            created_at=timestamp,
        )
        ticket_path = self._agent_wake_ticket_path(
            profile=profile,
            ticket=ticket,
            workspace_root=workspace_root,
        )
        if ticket_path is None:
            raise ValueError("ticket path is required for Hermes activation.")
        resolved_platform_workspace_root = _resolve_platform_workspace_root(
            explicit_root=platform_workspace_root,
            database_path=database_path,
            plugins_directory=plugins_directory,
            ticket_path=ticket_path,
            workspace_root=workspace_root,
        )
        query_text = build_hermes_activation_query(
            ticket_path=ticket_path,
            request_get_command=str(ticket.recommended_cli.get("requestGet") or ""),
            thread_get_command=str(ticket.recommended_cli.get("threadGet") or ""),
            respond_command_template=str(
                ticket.recommended_cli.get("respondTemplate") or ""
            ),
        )
        executable_resolution = resolve_hermes_executable(hermes_executable)
        executable_resolution_kwargs = {
            "requested_hermes_executable": executable_resolution.requested_executable,
            "resolved_hermes_executable": executable_resolution.resolved_executable,
            "executable_resolution_source": executable_resolution.resolution_source,
            "executable_resolution_warning": executable_resolution.warning,
        }
        argv = render_hermes_chat_resume_argv(
            handle.hermes_session_id,
            hermes_executable=executable_resolution.resolved_executable,
            query=query_text,
            source_tag=source_tag,
            max_turns=max_turns,
        )
        existing_attempt = self._latest_hermes_activation_for_request(
            resolved_workspace_id,
            handle_id=handle_id,
            exchange_request_id=exchange_request_id,
        )
        if (
            not dry_run
            and existing_attempt is not None
            and existing_attempt.provider_command_started
        ):
            attempt = HermesRegisteredSessionActivationAttempt(
                workspace_id=resolved_workspace_id.value,
                agent_id=resolved_agent_id.value,
                handle_id=handle.handle_id,
                exchange_request_id=request.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                status=HermesRegisteredSessionActivationStatus.SKIPPED,
                ticket_path=ticket_path,
                cwd=handle.cwd,
                command_argv_summary=argv,
                platform_workspace_root=resolved_platform_workspace_root,
                source_tag=source_tag,
                max_turns=max_turns,
                executable_preflight_status="not_run_skipped",
                **session_identity_kwargs,
                **executable_resolution_kwargs,
                skip_reason="already_started_for_request_and_handle",
                created_at=timestamp,
                completed_at=timestamp,
            )
            sequence = self._append_hermes_activation_attempt(
                resolved_workspace_id,
                attempt=attempt,
                ticket=ticket,
                action="skipped",
                occurred_at=timestamp,
            )
            return {
                "hermesRegisteredSessionActivation": {
                    **attempt.to_metadata(),
                    "sourceEventSequence": sequence,
                },
                "hermesSessionHandle": handle.to_metadata(),
                "ticket": ticket.to_metadata(),
                "queryPreview": query_text,
                "skipped": True,
            }
        if dry_run:
            attempt = HermesRegisteredSessionActivationAttempt(
                workspace_id=resolved_workspace_id.value,
                agent_id=resolved_agent_id.value,
                handle_id=handle.handle_id,
                exchange_request_id=request.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                status=HermesRegisteredSessionActivationStatus.DRY_RUN,
                ticket_path=ticket_path,
                cwd=handle.cwd,
                command_argv_summary=argv,
                dry_run=True,
                platform_workspace_root=resolved_platform_workspace_root,
                source_tag=source_tag,
                max_turns=max_turns,
                executable_preflight_status="not_run_dry_run",
                **session_identity_kwargs,
                **executable_resolution_kwargs,
                created_at=timestamp,
                completed_at=timestamp,
            )
            sequence = self._append_hermes_activation_attempt(
                resolved_workspace_id,
                attempt=attempt,
                ticket=ticket,
                action="dry_run",
                occurred_at=timestamp,
            )
            return {
                "hermesRegisteredSessionActivation": {
                    **attempt.to_metadata(),
                    "sourceEventSequence": sequence,
                },
                "hermesSessionHandle": handle.to_metadata(),
                "ticket": ticket.to_metadata(),
                "queryPreview": query_text,
                "executeRequired": True,
            }

        preflight = _run_hermes_executable_preflight(
            executable_resolution.resolved_executable,
            timeout_seconds=min(timeout_seconds, 15),
            environment=provider_environment,
        )
        if preflight["status"] != "passed":
            completed_at = _utc_now()
            failure_category = str(preflight.get("failureCategory") or "preflight_failed")
            attempt = HermesRegisteredSessionActivationAttempt(
                workspace_id=resolved_workspace_id.value,
                agent_id=resolved_agent_id.value,
                handle_id=handle.handle_id,
                exchange_request_id=request.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                status=HermesRegisteredSessionActivationStatus.FAILED,
                ticket_path=ticket_path,
                cwd=handle.cwd,
                command_argv_summary=argv,
                failure_reason=str(preflight.get("failureReason") or "preflight_failed"),
                provider_command_started=False,
                platform_workspace_root=resolved_platform_workspace_root,
                source_tag=source_tag,
                max_turns=max_turns,
                executable_preflight_status=str(preflight["status"]),
                executable_preflight_exit_code=preflight.get("exitCode"),
                executable_preflight_stdout_tail=preflight.get("stdoutTail"),
                executable_preflight_stderr_tail=preflight.get("stderrTail"),
                executable_preflight_failure_reason=preflight.get("failureReason"),
                failure_category=failure_category,
                retryable=hermes_failure_retryable(failure_category),
                **session_identity_kwargs,
                **executable_resolution_kwargs,
                created_at=timestamp,
                completed_at=completed_at,
            )
            sequence = self._append_hermes_activation_attempt(
                resolved_workspace_id,
                attempt=attempt,
                ticket=ticket,
                action="failed",
                occurred_at=completed_at,
            )
            return {
                "hermesRegisteredSessionActivation": {
                    **attempt.to_metadata(),
                    "sourceEventSequence": sequence,
                },
                "hermesSessionHandle": handle.to_metadata(),
                "ticket": ticket.to_metadata(),
            }

        try:
            self._write_agent_wake_ticket_file(ticket, ticket_path)
        except OSError as exc:
            failure_category = "ticket_write_failed"
            attempt = HermesRegisteredSessionActivationAttempt(
                workspace_id=resolved_workspace_id.value,
                agent_id=resolved_agent_id.value,
                handle_id=handle.handle_id,
                exchange_request_id=request.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                status=HermesRegisteredSessionActivationStatus.FAILED,
                ticket_path=ticket_path,
                cwd=handle.cwd,
                command_argv_summary=argv,
                failure_reason=f"{exc.__class__.__name__}: {exc}",
                failure_category=failure_category,
                retryable=hermes_failure_retryable(failure_category),
                provider_command_started=False,
                platform_workspace_root=resolved_platform_workspace_root,
                source_tag=source_tag,
                max_turns=max_turns,
                executable_preflight_status=str(preflight["status"]),
                executable_preflight_exit_code=preflight.get("exitCode"),
                executable_preflight_stdout_tail=preflight.get("stdoutTail"),
                executable_preflight_stderr_tail=preflight.get("stderrTail"),
                executable_preflight_failure_reason=preflight.get("failureReason"),
                **session_identity_kwargs,
                **executable_resolution_kwargs,
                created_at=timestamp,
                completed_at=_utc_now(),
            )
            sequence = self._append_hermes_activation_attempt(
                resolved_workspace_id,
                attempt=attempt,
                ticket=ticket,
                action="failed",
                occurred_at=attempt.completed_at or timestamp,
            )
            return {
                "hermesRegisteredSessionActivation": {
                    **attempt.to_metadata(),
                    "sourceEventSequence": sequence,
                },
                "hermesSessionHandle": handle.to_metadata(),
                "ticket": ticket.to_metadata(),
            }
        delivery = AgentWakeDeliveryRecord(
            workspace_id=resolved_workspace_id.value,
            target_agent_id=resolved_agent_id.value,
            exchange_request_id=request.exchange_request_id,
            thread_id=ticket.thread_id,
            wake_ticket_id=ticket.wake_ticket_id,
            wake_mode=AgentWakeMode.HANDOFF_FILE,
            status=AgentWakeDeliveryStatus.DELIVERED,
            ticket_path=ticket_path,
            lease_recorded_before_command=True,
            created_at=timestamp,
            completed_at=timestamp,
        )
        delivery_sequence = self._append_agent_wake_delivery(
            resolved_workspace_id,
            delivery=delivery,
            ticket=ticket,
            action="delivered",
            occurred_at=timestamp,
        )
        try:
            completed = subprocess.run(
                argv,
                cwd=handle.cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                shell=False,
                timeout=timeout_seconds,
                env=provider_environment,
            )
            completed_at = _utc_now()
            continuity = evaluate_hermes_session_continuity(
                completed.stdout,
                completed.stderr,
                handle.hermes_session_id,
            )
            continuity_mismatch = continuity.verification == "mismatch"
            response_capture_mode = "hermes_chat_query_stdout"
            response_capture_status = (
                "not_attempted_command_failed"
                if completed.returncode != 0
                else None
            )
            if continuity_mismatch:
                response_capture_status = "rejected_expected_session_mismatch"
            response_capture_failure_reason = None
            response_source_sequence = None
            response_requires_user_review = False
            request_after_command = self._latest_agent_exchange_request_by_id(
                resolved_workspace_id,
                request.exchange_request_id,
            )
            request_responded_by_target = (
                request_after_command is not None
                and request_after_command.terminal_reason
                is AgentExchangeRequestTerminalReason.RESPONDED
                and request_after_command.responded_by_agent_id == resolved_agent_id.value
            )
            target_response_completed = bool(request_responded_by_target)
            if completed.returncode == 0 and not continuity_mismatch:
                captured_response = extract_hermes_chat_response(completed.stdout)
                if request_responded_by_target:
                    response_capture_status = "already_responded"
                elif not captured_response:
                    response_capture_status = "no_response_text"
                elif (
                    request_after_command is not None
                    and request_after_command.is_active()
                ):
                    response_summary = truncate_hermes_auto_captured_response(
                        captured_response,
                        max_chars=request_after_command.max_response_length,
                    )
                    try:
                        response_result = self.respond_agent_exchange_request(
                            resolved_workspace_id,
                            exchange_request_id=request.exchange_request_id,
                            responding_agent_id=resolved_agent_id,
                            response_summary=response_summary,
                            requires_user_review=not continuity.verified,
                            metadata={
                                "responseSource": "hermes_chat_query_auto_capture",
                                "captureMode": response_capture_mode,
                                "wakeTicketId": ticket.wake_ticket_id,
                                "handleId": handle.handle_id,
                                "registeredProviderSessionId": handle.hermes_session_id,
                                "cliReportedSessionId": continuity.reported_session_id,
                                "expectedSessionVerification": continuity.verification,
                                "expectedSessionVerified": continuity.verified,
                                "responseInstanceVerified": continuity.verified,
                                "continuityEvidenceSource": continuity.evidence_source,
                            },
                            responded_at=completed_at,
                        )
                    except ValueError as exc:
                        response_capture_status = "respond_failed"
                        response_capture_failure_reason = (
                            f"{exc.__class__.__name__}: {exc}"
                        )
                    else:
                        response_requires_user_review = not continuity.verified
                        response_capture_status = (
                            "recorded"
                            if continuity.verified
                            else "recorded_unverified_session"
                        )
                        response_source_sequence = int(
                            response_result.get("sourceEventSequence", 0)
                        )
                        target_response_completed = True
                else:
                    response_capture_status = "request_not_active"
            attempt = HermesRegisteredSessionActivationAttempt(
                workspace_id=resolved_workspace_id.value,
                agent_id=resolved_agent_id.value,
                handle_id=handle.handle_id,
                exchange_request_id=request.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                status=(
                    HermesRegisteredSessionActivationStatus.DELIVERED
                    if completed.returncode == 0 and not continuity_mismatch
                    else HermesRegisteredSessionActivationStatus.FAILED
                ),
                ticket_path=ticket_path,
                cwd=handle.cwd,
                command_argv_summary=argv,
                command_exit_code=completed.returncode,
                stdout_tail=summarize_hermes_process_text(completed.stdout),
                stderr_tail=summarize_hermes_process_text(completed.stderr),
                failure_reason=(
                    continuity.failure_reason
                    if continuity_mismatch
                    else (
                        None
                        if completed.returncode == 0
                        else "command_exit_nonzero"
                    )
                ),
                failure_category=(
                    continuity.failure_category
                    if continuity_mismatch
                    else (
                        None
                        if completed.returncode == 0
                        else "command_exit_nonzero"
                    )
                ),
                retryable=(
                    False
                    if continuity_mismatch
                    else (
                        None
                        if completed.returncode == 0
                        else hermes_failure_retryable("command_exit_nonzero")
                    )
                ),
                provider_command_started=True,
                session_continuity_verified=continuity.verified,
                cli_reported_session_id=continuity.reported_session_id,
                expected_session_match=continuity.expected_session_match,
                expected_session_verification=continuity.verification,
                continuity_evidence_source=continuity.evidence_source,
                continuity_confidence=continuity.confidence,
                continuity_warning=continuity.warning,
                response_instance_verified=continuity.verified,
                response_requires_user_review=response_requires_user_review,
                target_response_completed=target_response_completed,
                response_capture_mode=response_capture_mode,
                response_capture_status=response_capture_status,
                response_capture_failure_reason=response_capture_failure_reason,
                auto_captured_response_source_event_sequence=response_source_sequence,
                platform_workspace_root=resolved_platform_workspace_root,
                source_tag=source_tag,
                max_turns=max_turns,
                executable_preflight_status=str(preflight["status"]),
                executable_preflight_exit_code=preflight.get("exitCode"),
                executable_preflight_stdout_tail=preflight.get("stdoutTail"),
                executable_preflight_stderr_tail=preflight.get("stderrTail"),
                executable_preflight_failure_reason=preflight.get("failureReason"),
                **session_identity_kwargs,
                **executable_resolution_kwargs,
                created_at=timestamp,
                completed_at=completed_at,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            completed_at = _utc_now()
            failure_category = classify_hermes_activation_failure(exc)
            attempt = HermesRegisteredSessionActivationAttempt(
                workspace_id=resolved_workspace_id.value,
                agent_id=resolved_agent_id.value,
                handle_id=handle.handle_id,
                exchange_request_id=request.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                status=HermesRegisteredSessionActivationStatus.FAILED,
                ticket_path=ticket_path,
                cwd=handle.cwd,
                command_argv_summary=argv,
                failure_reason=f"{exc.__class__.__name__}: {exc}",
                failure_category=failure_category,
                retryable=hermes_failure_retryable(failure_category),
                provider_command_started=not isinstance(exc, OSError),
                platform_workspace_root=resolved_platform_workspace_root,
                source_tag=source_tag,
                max_turns=max_turns,
                executable_preflight_status=str(preflight["status"]),
                executable_preflight_exit_code=preflight.get("exitCode"),
                executable_preflight_stdout_tail=preflight.get("stdoutTail"),
                executable_preflight_stderr_tail=preflight.get("stderrTail"),
                executable_preflight_failure_reason=preflight.get("failureReason"),
                **session_identity_kwargs,
                **executable_resolution_kwargs,
                created_at=timestamp,
                completed_at=completed_at,
            )
        sequence = self._append_hermes_activation_attempt(
            resolved_workspace_id,
            attempt=attempt,
            ticket=ticket,
            action=attempt.status.value,
            occurred_at=attempt.completed_at or timestamp,
        )
        return {
            "hermesRegisteredSessionActivation": {
                **attempt.to_metadata(),
                "sourceEventSequence": sequence,
                "wakeDeliverySourceEventSequence": delivery_sequence,
            },
            "hermesSessionHandle": handle.to_metadata(),
            "ticket": ticket.to_metadata(),
        }

    def agent_activation_instructions(
        self,
        workspace_id: WorkspaceId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = (
            _workspace_id(workspace_id)
            if workspace_id is not None
            else None
        )
        if resolved_workspace_id is not None:
            self._require_workspace(resolved_workspace_id)
        return agent_activation_interface_metadata(
            workspace_id=(
                resolved_workspace_id.value
                if resolved_workspace_id is not None
                else None
            )
        )

    def wake_agent_activation(
        self,
        workspace_id: WorkspaceId | str,
        *,
        agent_id: AgentId | str,
        created_by: str,
        reason: str,
        activation_id: str | None = None,
        mode: AgentActivationMode | str = AgentActivationMode.MANUAL_WAKE_SAFE_MODE,
        connection_surface: AgentConnectionSurface | str = AgentConnectionSurface.CLI,
        task_id: TaskId | str | None = None,
        conversation_id: ConversationId | str | None = None,
        budget: Mapping[str, object] | None = None,
        allowed_contribution_kinds: tuple[str, ...] = (),
        metadata: Mapping[str, object] | None = None,
        created_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        workspace_record = self._require_workspace(workspace_id)
        if workspace_record.workspace.status is WorkspaceStatus.ARCHIVED:
            raise ValueError("workspace is archived.")
        resolved_agent = self._require_workspace_agent(
            workspace_record.workspace.workspace_id,
            agent_id,
        ).registration.agent_id
        resolved_conversation_id = (
            self._require_conversation(
                workspace_record.workspace.workspace_id,
                conversation_id,
            ).conversation.conversation_id
            if conversation_id is not None
            else None
        )
        if activation_id is not None:
            existing = self._latest_agent_activation_by_id(
                workspace_record.workspace.workspace_id,
                activation_id,
            )
            if existing is not None and existing.state not in {
                AgentActivationState.REVOKED,
                AgentActivationState.EXPIRED,
            }:
                raise ValueError("agent activation already exists.")
        timestamp = created_at or _utc_now()
        grant_input: dict[str, object] = {
            "workspaceId": workspace_record.workspace.workspace_id.value,
            "agentId": resolved_agent.value,
            "state": (
                AgentActivationState.ACTIVE_TASK_BOUND
                if task_id is not None or conversation_id is not None
                else AgentActivationState.AWAKENED
            ),
            "mode": mode.value if isinstance(mode, AgentActivationMode) else mode,
            "connectionSurface": (
                connection_surface.value
                if isinstance(connection_surface, AgentConnectionSurface)
                else connection_surface
            ),
            "createdAt": timestamp,
            "createdBy": created_by,
            "reason": reason,
            "taskId": (
                _task_id(task_id).value
                if task_id is not None
                else None
            ),
            "conversationId": (
                resolved_conversation_id.value
                if resolved_conversation_id is not None
                else None
            ),
            "budget": AgentActivityBudget.from_mapping(
                budget,
                created_at=timestamp,
            ).to_metadata(),
            "allowedContributionKinds": (
                tuple(allowed_contribution_kinds)
                if allowed_contribution_kinds
                else AgentActivationGrant(
                    workspace_id=workspace_record.workspace.workspace_id.value,
                    agent_id=resolved_agent.value,
                    created_by=created_by,
                    reason=reason,
                    created_at=timestamp,
                ).allowed_contribution_kinds
            ),
            "metadata": dict(metadata or {}),
        }
        if activation_id is not None:
            grant_input["activationId"] = activation_id
        grant = AgentActivationGrant.from_mapping(grant_input)
        sequence = self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=workspace_record.workspace.workspace_id,
                event_kind=PlatformEventKind.AGENT_ACTIVATION_CHANGED,
                aggregate_type="agent_activation",
                aggregate_id=grant.activation_id,
                occurred_at=timestamp,
                payload={
                    "action": "woken",
                    "activation": grant.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )
        return {
            "agentActivation": {
                **grant.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "sourceEventSequence": sequence,
            "created": True,
        }

    def get_agent_activation_status(
        self,
        workspace_id: WorkspaceId | str,
        *,
        agent_id: AgentId | str | None = None,
        activation_id: str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        if agent_id is not None:
            self._require_workspace_agent(resolved_workspace_id, agent_id)
        if activation_id is not None:
            activation = self._latest_agent_activation_by_id(
                resolved_workspace_id,
                activation_id,
            )
        elif agent_id is not None:
            activation = self._latest_agent_activation_by_agent(
                resolved_workspace_id,
                _agent_id(agent_id),
            )
        else:
            activation = None
        if (
            activation is not None
            and activation.state is not AgentActivationState.REVOKED
            and activation.is_expired()
        ):
            activation = activation.expired_copy()
        return {
            "agentActivation": (
                activation.to_metadata()
                if activation is not None
                else dormant_agent_activation_metadata(
                    workspace_id=resolved_workspace_id.value,
                    agent_id=(
                        _agent_id(agent_id).value
                        if agent_id is not None
                        else None
                    ),
                )
            )
        }

    def list_agent_activations(
        self,
        workspace_id: WorkspaceId | str,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        activations = [
            activation.expired_copy()
            if (
                activation.state is not AgentActivationState.REVOKED
                and activation.is_expired()
            )
            else activation
            for activation in self._latest_agent_activations(
                resolved_workspace_id
            ).values()
        ]
        return {
            "agentActivations": [
                activation.to_metadata()
                for activation in sorted(
                    activations,
                    key=lambda item: item.activation_id,
                )
            ]
        }

    def revoke_agent_activation(
        self,
        workspace_id: WorkspaceId | str,
        *,
        agent_id: AgentId | str,
        revoked_by: str,
        reason: str,
        activation_id: str | None = None,
        revoked_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        resolved_agent_id = self._require_workspace_agent(
            resolved_workspace_id,
            agent_id,
        ).registration.agent_id
        activation = (
            self._latest_agent_activation_by_id(
                resolved_workspace_id,
                activation_id,
            )
            if activation_id is not None
            else self._latest_agent_activation_by_agent(
                resolved_workspace_id,
                resolved_agent_id,
            )
        )
        if activation is None:
            raise ValueError("agent activation not found.")
        if activation.agent_id != resolved_agent_id.value:
            raise ValueError("agent activation agent_id does not match agent_id.")
        timestamp = revoked_at or _utc_now()
        revoked = activation.revoked_copy(
            revoked_by=revoked_by,
            reason=reason,
            revoked_at=timestamp,
        )
        sequence = self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=resolved_workspace_id,
                event_kind=PlatformEventKind.AGENT_ACTIVATION_CHANGED,
                aggregate_type="agent_activation",
                aggregate_id=revoked.activation_id,
                occurred_at=timestamp,
                payload={
                    "action": "revoked",
                    "activation": revoked.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )
        return {
            "agentActivation": {
                **revoked.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "sourceEventSequence": sequence,
            "revoked": True,
        }

    def delegated_wake_instructions(
        self,
        workspace_id: WorkspaceId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = (
            _workspace_id(workspace_id)
            if workspace_id is not None
            else None
        )
        if resolved_workspace_id is not None:
            self._require_workspace(resolved_workspace_id)
        return delegated_wake_interface_metadata(
            workspace_id=(
                resolved_workspace_id.value
                if resolved_workspace_id is not None
                else None
            )
        )

    def create_delegated_wake_grant(
        self,
        workspace_id: WorkspaceId | str,
        *,
        source_agent_id: AgentId | str,
        target_agent_id: AgentId | str,
        created_by: str,
        reason: str,
        delegated_wake_grant_id: str | None = None,
        mode: DelegatedWakeGrantMode | str = DelegatedWakeGrantMode.USER_AUTHORIZED_ONE_TIME,
        task_id: TaskId | str | None = None,
        conversation_id: ConversationId | str | None = None,
        target_activation_mode: AgentActivationMode | str = AgentActivationMode.MANUAL_WAKE_SAFE_MODE,
        target_activation_budget: Mapping[str, object] | None = None,
        allowed_contribution_kinds: tuple[str, ...] = (),
        expires_at: datetime | None = None,
        metadata: Mapping[str, object] | None = None,
        created_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        workspace_record = self._require_workspace(workspace_id)
        if workspace_record.workspace.status is WorkspaceStatus.ARCHIVED:
            raise ValueError("workspace is archived.")
        resolved_workspace_id = workspace_record.workspace.workspace_id
        resolved_source_agent = self._require_workspace_agent(
            resolved_workspace_id,
            source_agent_id,
        ).registration.agent_id
        resolved_target_agent = self._require_workspace_agent(
            resolved_workspace_id,
            target_agent_id,
        ).registration.agent_id
        if resolved_source_agent == resolved_target_agent:
            raise ValueError(
                "sourceAgentId and targetAgentId must not be the same agent."
            )
        resolved_conversation_id = (
            self._require_conversation(
                resolved_workspace_id,
                conversation_id,
            ).conversation.conversation_id
            if conversation_id is not None
            else None
        )
        if delegated_wake_grant_id is not None:
            existing = self._latest_delegated_wake_grant_by_id(
                resolved_workspace_id,
                delegated_wake_grant_id,
            )
            if existing is not None and existing.state not in {
                DelegatedWakeGrantState.REVOKED,
                DelegatedWakeGrantState.EXPIRED,
            }:
                raise ValueError("delegated wake grant already exists.")
        timestamp = created_at or _utc_now()
        grant_input: dict[str, object] = {
            "workspaceId": resolved_workspace_id.value,
            "sourceAgentId": resolved_source_agent.value,
            "targetAgentId": resolved_target_agent.value,
            "createdBy": created_by,
            "reason": reason,
            "mode": mode.value if isinstance(mode, DelegatedWakeGrantMode) else mode,
            "createdAt": timestamp,
            "taskId": _task_id(task_id).value if task_id is not None else None,
            "conversationId": (
                resolved_conversation_id.value
                if resolved_conversation_id is not None
                else None
            ),
            "targetActivationMode": (
                target_activation_mode.value
                if isinstance(target_activation_mode, AgentActivationMode)
                else target_activation_mode
            ),
            "targetActivationBudget": AgentActivityBudget.from_mapping(
                target_activation_budget,
                created_at=timestamp,
            ).to_metadata(),
            "allowedContributionKinds": (
                tuple(allowed_contribution_kinds)
                if allowed_contribution_kinds
                else DelegatedWakeGrant(
                    workspace_id=resolved_workspace_id.value,
                    source_agent_id=resolved_source_agent.value,
                    target_agent_id=resolved_target_agent.value,
                    created_by=created_by,
                    reason=reason,
                    created_at=timestamp,
                ).allowed_contribution_kinds
            ),
            "metadata": dict(metadata or {}),
        }
        if delegated_wake_grant_id is not None:
            grant_input["delegatedWakeGrantId"] = delegated_wake_grant_id
        if expires_at is not None:
            grant_input["expiresAt"] = expires_at
        grant = DelegatedWakeGrant.from_mapping(grant_input)
        sequence = self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=resolved_workspace_id,
                event_kind=PlatformEventKind.DELEGATED_WAKE_GRANT_CHANGED,
                aggregate_type="delegated_wake_grant",
                aggregate_id=grant.delegated_wake_grant_id,
                occurred_at=timestamp,
                payload={
                    "action": "created",
                    "grant": grant.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )
        return {
            "delegatedWakeGrant": {
                **grant.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "sourceEventSequence": sequence,
            "created": True,
        }

    def get_delegated_wake_grant_status(
        self,
        workspace_id: WorkspaceId | str,
        *,
        delegated_wake_grant_id: str | None = None,
        source_agent_id: AgentId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        if source_agent_id is not None:
            self._require_workspace_agent(resolved_workspace_id, source_agent_id)
        if delegated_wake_grant_id is not None:
            grant = self._latest_delegated_wake_grant_by_id(
                resolved_workspace_id,
                delegated_wake_grant_id,
            )
        elif source_agent_id is not None:
            grant = self._latest_delegated_wake_grant_by_source_agent(
                resolved_workspace_id,
                _agent_id(source_agent_id),
            )
        else:
            grant = None
        if (
            grant is not None
            and grant.state is not DelegatedWakeGrantState.REVOKED
            and grant.state is not DelegatedWakeGrantState.CONSUMED
            and grant.state is not DelegatedWakeGrantState.DENIED
            and grant.is_expired()
        ):
            grant = grant.expired_copy()
        return {
            "delegatedWakeGrant": (
                grant.to_metadata()
                if grant is not None
                else {
                    "schema": "delegated_wake_grant.v1",
                    "delegatedWakeGrantId": None,
                    "workspaceId": resolved_workspace_id.value,
                    "sourceAgentId": (
                        _agent_id(source_agent_id).value
                        if source_agent_id is not None
                        else None
                    ),
                    "state": DelegatedWakeGrantState.PENDING.value,
                    "realRuntimeConnected": False,
                    "agentAutoWakeEnabled": False,
                    "userAuthorizedDelegatedWake": False,
                    "canDelegateFurther": False,
                }
            )
        }

    def list_delegated_wake_grants(
        self,
        workspace_id: WorkspaceId | str,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        grants = [
            (
                grant.expired_copy()
                if (
                    grant.state is not DelegatedWakeGrantState.REVOKED
                    and grant.state is not DelegatedWakeGrantState.CONSUMED
                    and grant.state is not DelegatedWakeGrantState.DENIED
                    and grant.is_expired()
                )
                else grant
            )
            for grant in self._latest_delegated_wake_grants(
                resolved_workspace_id
            ).values()
        ]
        return {
            "delegatedWakeGrants": [
                grant.to_metadata()
                for grant in sorted(
                    grants,
                    key=lambda item: item.delegated_wake_grant_id,
                )
            ]
        }

    def consume_delegated_wake_grant(
        self,
        workspace_id: WorkspaceId | str,
        *,
        delegated_wake_grant_id: str,
        consuming_agent_id: AgentId | str,
        consumed_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        workspace_record = self._require_workspace(workspace_id)
        if workspace_record.workspace.status is WorkspaceStatus.ARCHIVED:
            raise ValueError("workspace is archived.")
        resolved_workspace_id = workspace_record.workspace.workspace_id
        resolved_consuming_agent = self._require_workspace_agent(
            resolved_workspace_id,
            consuming_agent_id,
        ).registration.agent_id
        grant = self._latest_delegated_wake_grant_by_id(
            resolved_workspace_id,
            delegated_wake_grant_id,
        )
        if grant is None:
            raise ValueError("delegated wake grant not found.")
        target_agent_record = self.agent_registration_reader.get_agent_registration_state(
            _agent_id(grant.target_agent_id)
        )
        target_agent_exists = (
            target_agent_record is not None
            and target_agent_record.registration.workspace_id == resolved_workspace_id
        )
        timestamp = consumed_at or _utc_now()
        allowed, deny_reason = grant.is_consume_allowed(
            consuming_agent_id=resolved_consuming_agent.value,
            target_agent_exists=target_agent_exists,
            target_agent_id=grant.target_agent_id,
            checked_at=timestamp,
        )
        if not allowed:
            reason_value = (
                deny_reason.value
                if isinstance(deny_reason, DelegatedWakeDenyReason)
                else str(deny_reason)
            )
            denied = grant.denied_copy(
                deny_reason=reason_value,
                denied_by_agent_id=resolved_consuming_agent.value,
                denied_at=timestamp,
            )
            self.event_log_reader.append(
                PlatformEventRecord.create(
                    event_id=(
                        _platform_event_id(event_id)
                        if event_id is not None
                        else None
                    ),
                    workspace_id=resolved_workspace_id,
                    event_kind=PlatformEventKind.DELEGATED_WAKE_GRANT_CHANGED,
                    aggregate_type="delegated_wake_grant",
                    aggregate_id=denied.delegated_wake_grant_id,
                    occurred_at=timestamp,
                    payload={
                        "action": "consume_denied",
                        "grant": denied.to_metadata(),
                        "denyReason": reason_value,
                    },
                    metadata={"source": "local_platform_operation_service"},
                )
            )
            raise ValueError(
                f"delegated wake grant denied: {reason_value}."
            )

        target_activation = self.wake_agent_activation(
            resolved_workspace_id,
            agent_id=grant.target_agent_id,
            created_by=grant.created_by,
            reason=grant.reason,
            mode=grant.target_activation_mode,
            connection_surface=AgentConnectionSurface.CLI,
            task_id=grant.task_id,
            conversation_id=grant.conversation_id,
            budget=grant.target_activation_budget.to_metadata(),
            allowed_contribution_kinds=tuple(grant.allowed_contribution_kinds),
            metadata={
                "delegatedWakeGrantId": grant.delegated_wake_grant_id,
                "sourceAgentId": grant.source_agent_id,
                "delegatedByUser": grant.created_by,
                "delegatedWakeConsumedAt": timestamp.isoformat(),
            },
            created_at=timestamp,
        )
        target_activation_id = target_activation["agentActivation"]["activationId"]
        consumed = grant.consumed_copy(
            consumed_by_agent_id=resolved_consuming_agent.value,
            target_activation_id=target_activation_id,
            consumed_at=timestamp,
        )
        sequence = self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=resolved_workspace_id,
                event_kind=PlatformEventKind.DELEGATED_WAKE_GRANT_CHANGED,
                aggregate_type="delegated_wake_grant",
                aggregate_id=consumed.delegated_wake_grant_id,
                occurred_at=timestamp,
                payload={
                    "action": "consumed",
                    "grant": consumed.to_metadata(),
                    "targetActivationId": target_activation_id,
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )
        return {
            "delegatedWakeGrant": {
                **consumed.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "targetActivation": target_activation["agentActivation"],
            "sourceEventSequence": sequence,
            "consumed": True,
        }

    def revoke_delegated_wake_grant(
        self,
        workspace_id: WorkspaceId | str,
        *,
        delegated_wake_grant_id: str,
        revoked_by: str,
        reason: str,
        revoked_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        grant = self._latest_delegated_wake_grant_by_id(
            resolved_workspace_id,
            delegated_wake_grant_id,
        )
        if grant is None:
            raise ValueError("delegated wake grant not found.")
        if grant.state is DelegatedWakeGrantState.CONSUMED:
            raise ValueError("consumed delegated wake grant cannot be revoked.")
        timestamp = revoked_at or _utc_now()
        revoked = grant.revoked_copy(
            revoked_by=revoked_by,
            reason=reason,
            revoked_at=timestamp,
        )
        sequence = self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=resolved_workspace_id,
                event_kind=PlatformEventKind.DELEGATED_WAKE_GRANT_CHANGED,
                aggregate_type="delegated_wake_grant",
                aggregate_id=revoked.delegated_wake_grant_id,
                occurred_at=timestamp,
                payload={
                    "action": "revoked",
                    "grant": revoked.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )
        return {
            "delegatedWakeGrant": {
                **revoked.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "sourceEventSequence": sequence,
            "revoked": True,
        }

    def project_directory_coordination_instructions(
        self,
        workspace_id: WorkspaceId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = (
            _workspace_id(workspace_id)
            if workspace_id is not None
            else None
        )
        if resolved_workspace_id is not None:
            self._require_workspace(resolved_workspace_id)
        return project_directory_coordination_interface_metadata(
            workspace_id=(
                resolved_workspace_id.value
                if resolved_workspace_id is not None
                else None
            )
        )

    def declare_project_directory_coordination(
        self,
        workspace_id: WorkspaceId | str,
        *,
        declared_agent_id: AgentId | str,
        project_root: str,
        directory_coordination_id: str | None = None,
        git_repository_id: str | None = None,
        linked_task_id: TaskId | str | None = None,
        linked_conversation_id: ConversationId | str | None = None,
        declared_path_scopes: tuple[str, ...] = (".",),
        directory_access_intent: ProjectDirectoryAccessIntent | str = (
            ProjectDirectoryAccessIntent.EDIT_PLANNED
        ),
        last_known_git_head: str | None = None,
        last_known_branch: str | None = None,
        dirty_state: ProjectDirectoryDirtyState | str = ProjectDirectoryDirtyState.UNKNOWN,
        uncommitted_change_summary: str | None = None,
        test_summary: str | None = None,
        recommended_commit_policy: ProjectDirectoryCommitPolicy | str = (
            ProjectDirectoryCommitPolicy.COMMIT_AFTER_TASK
        ),
        handoff_note: str | None = None,
        requires_user_review: bool = False,
        metadata: Mapping[str, object] | None = None,
        declared_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        workspace_record = self._require_workspace(workspace_id)
        if workspace_record.workspace.status is WorkspaceStatus.ARCHIVED:
            raise ValueError("workspace is archived.")
        resolved_workspace_id = workspace_record.workspace.workspace_id
        resolved_agent_id = self._require_workspace_agent(
            resolved_workspace_id,
            declared_agent_id,
        ).registration.agent_id
        if linked_task_id is not None:
            self._require_workspace_task(resolved_workspace_id, linked_task_id)
        resolved_conversation_id = (
            self._require_conversation(
                resolved_workspace_id,
                linked_conversation_id,
            ).conversation.conversation_id
            if linked_conversation_id is not None
            else None
        )
        if directory_coordination_id is not None:
            existing = self._latest_project_directory_coordination_by_id(
                resolved_workspace_id,
                directory_coordination_id,
            )
            if existing is not None and existing.is_active():
                raise ValueError("project directory coordination record already exists.")
        timestamp = declared_at or _utc_now()
        record_input: dict[str, object] = {
            "workspaceId": resolved_workspace_id.value,
            "declaredAgentId": resolved_agent_id.value,
            "projectRoot": project_root,
            "gitRepositoryId": git_repository_id,
            "linkedTaskId": (
                _task_id(linked_task_id).value
                if linked_task_id is not None
                else None
            ),
            "linkedConversationId": (
                resolved_conversation_id.value
                if resolved_conversation_id is not None
                else None
            ),
            "declaredPathScopes": tuple(declared_path_scopes or (".",)),
            "directoryAccessIntent": (
                directory_access_intent.value
                if isinstance(directory_access_intent, ProjectDirectoryAccessIntent)
                else directory_access_intent
            ),
            "lastKnownGitHead": last_known_git_head,
            "lastKnownBranch": last_known_branch,
            "dirtyState": (
                dirty_state.value
                if isinstance(dirty_state, ProjectDirectoryDirtyState)
                else dirty_state
            ),
            "uncommittedChangeSummary": uncommitted_change_summary,
            "testSummary": test_summary,
            "recommendedCommitPolicy": (
                recommended_commit_policy.value
                if isinstance(recommended_commit_policy, ProjectDirectoryCommitPolicy)
                else recommended_commit_policy
            ),
            "handoffNote": handoff_note,
            "requiresUserReview": requires_user_review,
            "createdAt": timestamp,
            "updatedAt": timestamp,
            "metadata": dict(metadata or {}),
        }
        if directory_coordination_id is not None:
            record_input["directoryCoordinationId"] = directory_coordination_id
        record = ProjectDirectoryCoordinationRecord.from_mapping(record_input)
        record = self._project_directory_record_with_current_overlap(
            resolved_workspace_id,
            record,
        )
        sequence = self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=resolved_workspace_id,
                event_kind=PlatformEventKind.PROJECT_DIRECTORY_COORDINATION_CHANGED,
                aggregate_type="project_directory_coordination",
                aggregate_id=record.directory_coordination_id,
                occurred_at=timestamp,
                payload={
                    "action": "declared",
                    "coordination": record.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )
        return {
            "projectDirectoryCoordination": {
                **record.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "sourceEventSequence": sequence,
            "declared": True,
        }

    def get_project_directory_coordination_status(
        self,
        workspace_id: WorkspaceId | str,
        *,
        directory_coordination_id: str,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        record = self._latest_project_directory_coordination_by_id(
            resolved_workspace_id,
            directory_coordination_id,
        )
        if record is not None:
            record = self._project_directory_record_with_current_overlap(
                resolved_workspace_id,
                record,
            )
        return {
            "projectDirectoryCoordination": (
                record.to_metadata()
                if record is not None
                else {
                    "schema": "project_directory_coordination.v1",
                    "directoryCoordinationId": directory_coordination_id,
                    "workspaceId": resolved_workspace_id.value,
                    "state": "missing",
                    "coordinationStrength": "advisory_only",
                    "notSecurityBoundary": True,
                    "advisoryOnly": True,
                    "fileBodiesRead": False,
                    "gitOperationExecuted": False,
                    "realRuntimeConnected": False,
                }
            )
        }

    def list_project_directory_coordination(
        self,
        workspace_id: WorkspaceId | str,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        records = [
            self._project_directory_record_with_current_overlap(
                resolved_workspace_id,
                record,
            )
            for record in self._latest_project_directory_coordination_records(
                resolved_workspace_id
            ).values()
        ]
        return {
            "projectDirectoryCoordinations": [
                record.to_metadata()
                for record in sorted(
                    records,
                    key=lambda item: item.directory_coordination_id,
                )
            ]
        }

    def update_project_directory_coordination(
        self,
        workspace_id: WorkspaceId | str,
        *,
        directory_coordination_id: str,
        directory_access_intent: ProjectDirectoryAccessIntent | str | None = None,
        declared_path_scopes: tuple[str, ...] | None = None,
        last_known_git_head: str | None = None,
        last_known_branch: str | None = None,
        dirty_state: ProjectDirectoryDirtyState | str | None = None,
        uncommitted_change_summary: str | None = None,
        test_summary: str | None = None,
        recommended_commit_policy: ProjectDirectoryCommitPolicy | str | None = None,
        handoff_note: str | None = None,
        requires_user_review: bool | None = None,
        metadata: Mapping[str, object] | None = None,
        updated_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        workspace_record = self._require_workspace(resolved_workspace_id)
        if workspace_record.workspace.status is WorkspaceStatus.ARCHIVED:
            raise ValueError("workspace is archived.")
        existing = self._latest_project_directory_coordination_by_id(
            resolved_workspace_id,
            directory_coordination_id,
        )
        if existing is None:
            raise ValueError("project directory coordination record not found.")
        timestamp = updated_at or _utc_now()
        updates: dict[str, object] = {}
        if directory_access_intent is not None:
            updates["directoryAccessIntent"] = (
                directory_access_intent.value
                if isinstance(directory_access_intent, ProjectDirectoryAccessIntent)
                else directory_access_intent
            )
        if declared_path_scopes is not None:
            updates["declaredPathScopes"] = tuple(declared_path_scopes)
        for key, value in (
            ("lastKnownGitHead", last_known_git_head),
            ("lastKnownBranch", last_known_branch),
            ("uncommittedChangeSummary", uncommitted_change_summary),
            ("testSummary", test_summary),
            ("handoffNote", handoff_note),
        ):
            if value is not None:
                updates[key] = value
        if dirty_state is not None:
            updates["dirtyState"] = (
                dirty_state.value
                if isinstance(dirty_state, ProjectDirectoryDirtyState)
                else dirty_state
            )
        if recommended_commit_policy is not None:
            updates["recommendedCommitPolicy"] = (
                recommended_commit_policy.value
                if isinstance(recommended_commit_policy, ProjectDirectoryCommitPolicy)
                else recommended_commit_policy
            )
        if requires_user_review is not None:
            updates["requiresUserReview"] = requires_user_review
        if metadata is not None:
            updates["metadata"] = {
                **dict(existing.metadata),
                **dict(metadata),
            }
        updated = existing.updated_copy(
            updated_at=timestamp,
            **updates,
        )
        updated = self._project_directory_record_with_current_overlap(
            resolved_workspace_id,
            updated,
        )
        sequence = self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=resolved_workspace_id,
                event_kind=PlatformEventKind.PROJECT_DIRECTORY_COORDINATION_CHANGED,
                aggregate_type="project_directory_coordination",
                aggregate_id=updated.directory_coordination_id,
                occurred_at=timestamp,
                payload={
                    "action": "updated",
                    "coordination": updated.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )
        return {
            "projectDirectoryCoordination": {
                **updated.to_metadata(),
                "sourceEventSequence": sequence,
            },
            "sourceEventSequence": sequence,
            "updated": True,
        }

    def complete_project_directory_coordination(
        self,
        workspace_id: WorkspaceId | str,
        *,
        directory_coordination_id: str,
        last_known_git_head: str | None = None,
        last_known_branch: str | None = None,
        dirty_state: ProjectDirectoryDirtyState | str | None = None,
        uncommitted_change_summary: str | None = None,
        test_summary: str | None = None,
        recommended_commit_policy: ProjectDirectoryCommitPolicy | str | None = None,
        handoff_note: str | None = None,
        requires_user_review: bool | None = None,
        metadata: Mapping[str, object] | None = None,
        completed_at: datetime | None = None,
        event_id: PlatformEventId | str | None = None,
    ) -> Mapping[str, object]:
        return self.update_project_directory_coordination(
            workspace_id,
            directory_coordination_id=directory_coordination_id,
            directory_access_intent=ProjectDirectoryAccessIntent.DONE_REPORTED,
            last_known_git_head=last_known_git_head,
            last_known_branch=last_known_branch,
            dirty_state=dirty_state,
            uncommitted_change_summary=uncommitted_change_summary,
            test_summary=test_summary,
            recommended_commit_policy=recommended_commit_policy,
            handoff_note=handoff_note,
            requires_user_review=requires_user_review,
            metadata=metadata,
            updated_at=completed_at,
            event_id=event_id,
        )

    def get_run_session_timeline(
        self,
        workspace_id: WorkspaceId | str,
        session_id: PlatformRunSessionId | str,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        resolved_session_id = _platform_run_session_id(session_id)
        entries = self.event_log_reader.list_session_events(
            workspace_id=resolved_workspace_id,
            session_id=resolved_session_id,
        )
        return {
            "session": session_timeline_payload(
                workspace_id=resolved_workspace_id,
                session_id=resolved_session_id,
                entries=entries,
            ),
            "events": [
                platform_event_log_entry_payload(entry)
                for entry in entries
            ],
        }

    def list_agent_invocation_records(
        self,
        workspace_id: WorkspaceId | str,
        *,
        status: str | None = None,
        agent_id: AgentId | str | None = None,
        task_id: TaskId | str | None = None,
        idempotency_key: str | None = None,
    ) -> Mapping[str, object]:
        records = self.agent_invocation_reader.list_agent_invocation_records_by_workspace(
            _workspace_id(workspace_id),
            status=status,
            agent_id=(
                _agent_id(agent_id)
                if agent_id is not None
                else None
            ),
            task_id=(
                _task_id(task_id)
                if task_id is not None
                else None
            ),
            idempotency_key=idempotency_key,
        )
        return {
            "invocations": [
                agent_invocation_record_payload(record)
                for record in records
            ]
        }

    def get_agent_invocation_record(
        self,
        invocation_id: AgentInvocationId | str,
    ) -> Mapping[str, object]:
        record = self.agent_invocation_reader.get_agent_invocation_record(
            _agent_invocation_id(invocation_id)
        )
        return {
            "invocation": (
                agent_invocation_record_payload(record)
                if record is not None
                else None
            )
        }

    def list_file_operation_records(
        self,
        workspace_id: WorkspaceId | str,
        *,
        status: str | None = None,
        operation_kind: str | None = None,
        invocation_id: AgentInvocationId | str | None = None,
        task_id: TaskId | str | None = None,
        requested_by_agent_id: AgentId | str | None = None,
    ) -> Mapping[str, object]:
        records = self.file_operation_reader.list_file_operation_records_by_workspace(
            _workspace_id(workspace_id),
            status=status,
            operation_kind=operation_kind,
            invocation_id=(
                _agent_invocation_id(invocation_id)
                if invocation_id is not None
                else None
            ),
            task_id=(
                _task_id(task_id)
                if task_id is not None
                else None
            ),
            requested_by_agent_id=(
                _agent_id(requested_by_agent_id)
                if requested_by_agent_id is not None
                else None
            ),
        )
        return {
            "fileOperations": [
                file_operation_record_payload(record)
                for record in records
            ]
        }

    def get_file_operation_record(
        self,
        operation_id: FileOperationId | str,
    ) -> Mapping[str, object]:
        record = self.file_operation_reader.get_file_operation_record(
            _file_operation_id(operation_id)
        )
        return {
            "fileOperation": (
                file_operation_record_payload(record)
                if record is not None
                else None
            )
        }

    def get_agent_invocation_record_by_idempotency_key(
        self,
        workspace_id: WorkspaceId | str,
        idempotency_key: str,
    ) -> Mapping[str, object]:
        record = (
            self.agent_invocation_reader
            .get_agent_invocation_record_by_idempotency_key(
                workspace_id=_workspace_id(workspace_id),
                idempotency_key=idempotency_key,
            )
        )
        return {
            "invocation": (
                agent_invocation_record_payload(record)
                if record is not None
                else None
            )
        }

    def list_agent_registrations(
        self,
        workspace_id: WorkspaceId | str,
    ) -> Mapping[str, object]:
        return {
            "agents": [
                agent_registration_state_record_payload(record)
                for record in (
                    self.agent_registration_reader
                    .list_agent_registration_states_by_workspace(
                        _workspace_id(workspace_id)
                    )
                )
            ]
        }

    def list_agent_runtime_permissions(
        self,
        workspace_id: WorkspaceId | str,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        return {
            "runtimePermissions": [
                AgentRuntimePermissionView.from_registration(
                    record.registration
                ).to_metadata()
                for record in (
                    self.agent_registration_reader
                    .list_agent_registration_states_by_workspace(
                        resolved_workspace_id
                    )
                )
            ]
        }

    def get_agent_runtime_permissions(
        self,
        workspace_id: WorkspaceId | str,
        agent_id: AgentId | str,
    ) -> Mapping[str, object]:
        resolved_workspace_id = _workspace_id(workspace_id)
        self._require_workspace(resolved_workspace_id)
        record = self.agent_registration_reader.get_agent_registration_state(
            _agent_id(agent_id)
        )
        if record is None:
            raise ValueError("agent registration state not found.")
        if record.registration.workspace_id != resolved_workspace_id:
            raise ValueError(
                "agent registration workspace_id does not match workspace_id."
            )
        return {
            "runtimePermission": AgentRuntimePermissionView.from_registration(
                record.registration
            ).to_metadata()
        }

    def get_agent_registration(self, agent_id: AgentId | str) -> Mapping[str, object]:
        record = self.agent_registration_reader.get_agent_registration_state(
            _agent_id(agent_id)
        )
        return {
            "agent": (
                agent_registration_state_record_payload(record)
                if record is not None
                else None
            )
        }

    def list_tasks(self, workspace_id: WorkspaceId | str) -> Mapping[str, object]:
        return {
            "tasks": [
                task_state_record_payload(record)
                for record in self.task_reader.list_task_states_by_workspace(
                    _workspace_id(workspace_id)
                )
            ]
        }

    def get_task(self, task_id: TaskId | str) -> Mapping[str, object]:
        record = self.task_reader.get_task_state(_task_id(task_id))
        return {
            "task": (
                task_state_record_payload(record)
                if record is not None
                else None
            )
        }

    def list_issues(self, workspace_id: WorkspaceId | str) -> Mapping[str, object]:
        return {
            "issues": [
                issue_state_record_payload(record)
                for record in self.issue_reader.list_issue_states_by_workspace(
                    _workspace_id(workspace_id)
                )
            ]
        }

    def get_issue(self, issue_id: IssueId | str) -> Mapping[str, object]:
        record = self.issue_reader.get_issue_state(_issue_id(issue_id))
        return {
            "issue": (
                issue_state_record_payload(record)
                if record is not None
                else None
            )
        }

    def _require_workspace(
        self,
        workspace_id: WorkspaceId | str,
    ) -> WorkspaceStateRecord:
        record = self.workspace_reader.get_workspace_state(_workspace_id(workspace_id))
        if record is None:
            raise ValueError("workspace state not found.")
        return record

    def _require_workspace_agent(
        self,
        workspace_id: WorkspaceId | str,
        agent_id: AgentId | str,
    ) -> AgentRegistrationStateRecord:
        resolved_workspace_id = _workspace_id(workspace_id)
        record = self.agent_registration_reader.get_agent_registration_state(
            _agent_id(agent_id)
        )
        if record is None:
            raise ValueError("agent registration state not found.")
        if record.registration.workspace_id != resolved_workspace_id:
            raise ValueError("agent registration workspace_id does not match workspace_id.")
        return record

    def _require_workspace_task(
        self,
        workspace_id: WorkspaceId | str,
        task_id: TaskId | str,
    ) -> TaskStateRecord:
        resolved_workspace_id = _workspace_id(workspace_id)
        record = self.task_reader.get_task_state(_task_id(task_id))
        if record is None:
            raise ValueError("task state not found.")
        if record.task.workspace_id != resolved_workspace_id:
            raise ValueError("task workspace_id does not match workspace_id.")
        return record

    def _conversation_record_or_none(
        self,
        workspace_id: WorkspaceId | str,
        conversation_id: ConversationId | str,
    ) -> ConversationSessionRecord | None:
        resolved_workspace_id = _workspace_id(workspace_id)
        record = self.conversation_session_reader.get_conversation_session(
            _conversation_id(conversation_id)
        )
        if record is None:
            return None
        if record.conversation.workspace_id != resolved_workspace_id:
            raise ValueError("conversation workspace_id does not match workspace_id.")
        return record

    def _require_conversation(
        self,
        workspace_id: WorkspaceId | str,
        conversation_id: ConversationId | str,
    ) -> ConversationSessionRecord:
        record = self._conversation_record_or_none(workspace_id, conversation_id)
        if record is None:
            raise ValueError("conversation session not found.")
        return record

    def _require_active_conversation(
        self,
        workspace_id: WorkspaceId | str,
        conversation_id: ConversationId | str,
    ) -> ConversationSession:
        record = self._require_conversation(workspace_id, conversation_id)
        if record.conversation.status is ConversationStatus.ARCHIVED:
            raise ValueError("conversation is archived.")
        return record.conversation

    def _validate_agent_exchange_activation(
        self,
        *,
        workspace_id: WorkspaceId,
        metadata: Mapping[str, object],
    ) -> None:
        exchange = metadata.get("agentExchange")
        if exchange is None:
            return
        if not isinstance(exchange, MappingABC):
            raise ValueError("metadata.agentExchange must be an object.")
        activation_id = exchange.get("linkedActivationId")
        if activation_id is None:
            return
        if not isinstance(activation_id, str) or not activation_id.strip():
            raise ValueError("linkedActivationId must be a non-empty string.")
        activation = self._latest_agent_activation_by_id(
            workspace_id,
            activation_id.strip(),
        )
        if activation is None:
            raise ValueError("agent activation not found.")
        author_agent_id = exchange.get("authorAgentId")
        if (
            isinstance(author_agent_id, str)
            and author_agent_id.strip()
            and author_agent_id.strip() != activation.agent_id
        ):
            raise ValueError("agent activation agent_id does not match authorAgentId.")
        contribution_kind = exchange.get("contributionKind")
        if not isinstance(contribution_kind, str) or not contribution_kind.strip():
            raise ValueError("agentExchange.contributionKind must be a non-empty string.")
        allowed, reason = activation.is_write_allowed(
            contribution_kind=contribution_kind.strip(),
        )
        if not allowed:
            raise ValueError(f"agent activation is not active: {reason}.")
        if (
            activation.budget.max_writes
            <= self._agent_activation_write_count(
                workspace_id,
                activation.activation_id,
            )
        ):
            raise ValueError(
                "agent activation is not active: "
                f"{AgentStopReason.BUDGET_EXHAUSTED.value}."
            )

    def _context_update_event_entries(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[PlatformEventLogEntry, ...]:
        return tuple(
            entry
            for entry in self.event_log_reader.list_workspace_events(workspace_id)
            if entry.record.event_kind is PlatformEventKind.CONTEXT_UPDATE_APPENDED
        )

    def _agent_activation_write_count(
        self,
        workspace_id: WorkspaceId,
        activation_id: str,
    ) -> int:
        total = 0
        for entry in self.event_log_reader.list_workspace_events(workspace_id):
            event_kind = entry.record.event_kind
            payload = entry.record.payload
            if event_kind is PlatformEventKind.CONTEXT_UPDATE_APPENDED:
                metadata = payload.get("update_metadata")
            elif event_kind is PlatformEventKind.CONVERSATION_MESSAGE_APPENDED:
                metadata = payload.get("message_metadata")
            else:
                continue
            if not isinstance(metadata, MappingABC):
                continue
            exchange = metadata.get("agentExchange")
            if not isinstance(exchange, MappingABC):
                continue
            if exchange.get("linkedActivationId") == activation_id:
                total += 1
        return total

    def _latest_agent_exchange_request_policy(
        self,
        workspace_id: WorkspaceId,
    ) -> AgentExchangeRequestPolicy:
        policy = AgentExchangeRequestPolicy.from_mapping(
            {"workspaceId": workspace_id.value}
        )
        for entry in self.event_log_reader.list_workspace_events(workspace_id):
            if (
                entry.record.event_kind
                is not PlatformEventKind.AGENT_EXCHANGE_REQUEST_POLICY_CHANGED
            ):
                continue
            policy_payload = entry.record.payload.get("policy")
            if not isinstance(policy_payload, MappingABC):
                continue
            policy = AgentExchangeRequestPolicy.from_mapping(
                {
                    **dict(policy_payload),
                    "sourceEventSequence": entry.sequence,
                }
            )
        return policy

    def _latest_agent_exchange_request_by_id(
        self,
        workspace_id: WorkspaceId,
        exchange_request_id: str,
    ) -> AgentExchangeRequest | None:
        return self._latest_agent_exchange_requests(workspace_id).get(
            exchange_request_id
        )

    def _require_agent_exchange_request(
        self,
        workspace_id: WorkspaceId,
        exchange_request_id: str,
    ) -> AgentExchangeRequest:
        request = self._latest_agent_exchange_request_by_id(
            workspace_id,
            exchange_request_id,
        )
        if request is None:
            raise ValueError("agent exchange request not found.")
        return request

    def _latest_agent_exchange_requests(
        self,
        workspace_id: WorkspaceId,
    ) -> dict[str, AgentExchangeRequest]:
        requests: dict[str, AgentExchangeRequest] = {}
        for entry in self.event_log_reader.list_workspace_events(workspace_id):
            if (
                entry.record.event_kind
                is not PlatformEventKind.AGENT_EXCHANGE_REQUEST_CHANGED
            ):
                continue
            request_payload = entry.record.payload.get("request")
            if not isinstance(request_payload, MappingABC):
                continue
            request = AgentExchangeRequest.from_mapping(
                {
                    **dict(request_payload),
                    "sourceEventSequence": entry.sequence,
                }
            )
            requests[request.exchange_request_id] = request
        return requests

    def _latest_agent_endpoints(
        self,
        workspace_id: WorkspaceId,
    ) -> dict[str, AgentEndpointRecord]:
        endpoints: dict[str, AgentEndpointRecord] = {}
        for entry in self.event_log_reader.list_workspace_events(workspace_id):
            if entry.record.event_kind is not PlatformEventKind.AGENT_ENDPOINT_CHANGED:
                continue
            endpoint_payload = entry.record.payload.get("endpoint")
            if not isinstance(endpoint_payload, MappingABC):
                continue
            endpoint = AgentEndpointRecord.from_mapping(
                {
                    **dict(endpoint_payload),
                    "sourceEventSequence": entry.sequence,
                }
            )
            endpoints[endpoint.endpoint_id] = endpoint
        return endpoints

    def _latest_agent_endpoint_by_id(
        self,
        workspace_id: WorkspaceId,
        endpoint_id: str,
    ) -> AgentEndpointRecord | None:
        return self._latest_agent_endpoints(workspace_id).get(endpoint_id)

    def _latest_agent_endpoint_by_alias(
        self,
        workspace_id: WorkspaceId,
        alias: str,
    ) -> AgentEndpointRecord | None:
        normalized_alias = normalize_agent_endpoint_alias(alias)
        matches = [
            endpoint
            for endpoint in self._latest_agent_endpoints(workspace_id).values()
            if endpoint.alias == normalized_alias
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda item: item.updated_at, reverse=True)[0]

    def _select_agent_endpoint(
        self,
        workspace_id: WorkspaceId,
        *,
        endpoint_id: str | None = None,
        alias: str | None = None,
    ) -> AgentEndpointRecord:
        if (endpoint_id is None) == (alias is None):
            raise ValueError("choose exactly one of endpointId or alias.")
        endpoint = (
            self._latest_agent_endpoint_by_id(workspace_id, endpoint_id)
            if endpoint_id is not None
            else self._latest_agent_endpoint_by_alias(workspace_id, alias or "")
        )
        if endpoint is None:
            raise ValueError("agent endpoint not found.")
        return endpoint

    def _latest_agent_dispatches(
        self,
        workspace_id: WorkspaceId,
    ) -> dict[str, AgentDispatchRecord]:
        dispatches: dict[str, AgentDispatchRecord] = {}
        for entry in self.event_log_reader.list_workspace_events(workspace_id):
            if entry.record.event_kind is not PlatformEventKind.AGENT_DISPATCH_CHANGED:
                continue
            dispatch_payload = entry.record.payload.get("dispatch")
            if not isinstance(dispatch_payload, MappingABC):
                continue
            dispatch = AgentDispatchRecord.from_mapping(
                {
                    **dict(dispatch_payload),
                    "sourceEventSequence": entry.sequence,
                }
            )
            dispatches[dispatch.dispatch_id] = dispatch
        return dispatches

    def _latest_agent_dispatch_by_id(
        self,
        workspace_id: WorkspaceId,
        dispatch_id: str,
    ) -> AgentDispatchRecord | None:
        return self._latest_agent_dispatches(workspace_id).get(dispatch_id)

    def _require_agent_dispatch(
        self,
        workspace_id: WorkspaceId,
        dispatch_id: str,
    ) -> AgentDispatchRecord:
        dispatch = self._latest_agent_dispatch_by_id(workspace_id, dispatch_id)
        if dispatch is None:
            raise ValueError("agent dispatch not found.")
        return dispatch

    def _select_agent_dispatch(
        self,
        workspace_id: WorkspaceId,
        *,
        dispatch_id: str | None = None,
        exchange_request_id: str | None = None,
    ) -> AgentDispatchRecord:
        if dispatch_id is None and exchange_request_id is None:
            raise ValueError("dispatchId or exchangeRequestId is required.")
        if dispatch_id is not None:
            return self._require_agent_dispatch(workspace_id, dispatch_id)
        matches = [
            item
            for item in self._latest_agent_dispatches(workspace_id).values()
            if item.exchange_request_id == exchange_request_id
        ]
        if not matches:
            raise ValueError("agent dispatch not found.")
        return sorted(matches, key=lambda item: item.updated_at, reverse=True)[0]

    def _latest_agent_dispatch_leases(
        self,
        workspace_id: WorkspaceId,
    ) -> dict[str, AgentDispatchLeaseRecord]:
        leases: dict[str, AgentDispatchLeaseRecord] = {}
        for entry in self.event_log_reader.list_workspace_events(workspace_id):
            if (
                entry.record.event_kind
                is not PlatformEventKind.AGENT_DISPATCH_LEASE_CHANGED
            ):
                continue
            lease_payload = entry.record.payload.get("lease")
            if not isinstance(lease_payload, MappingABC):
                continue
            lease = AgentDispatchLeaseRecord.from_mapping(
                {
                    **dict(lease_payload),
                    "sourceEventSequence": entry.sequence,
                }
            )
            leases[lease.lease_id] = lease
        return leases

    def _latest_agent_dispatch_lease_by_id(
        self,
        workspace_id: WorkspaceId,
        lease_id: str,
    ) -> AgentDispatchLeaseRecord | None:
        return self._latest_agent_dispatch_leases(workspace_id).get(lease_id)

    def _require_agent_dispatch_lease(
        self,
        workspace_id: WorkspaceId,
        lease_id: str,
    ) -> AgentDispatchLeaseRecord:
        lease = self._latest_agent_dispatch_lease_by_id(workspace_id, lease_id)
        if lease is None:
            raise ValueError("agent dispatch lease not found.")
        return lease

    def _latest_agent_dispatch_lease_for_dispatch(
        self,
        workspace_id: WorkspaceId,
        dispatch_id: str,
    ) -> AgentDispatchLeaseRecord | None:
        matches = [
            lease
            for lease in self._latest_agent_dispatch_leases(workspace_id).values()
            if lease.dispatch_id == dispatch_id
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda item: item.updated_at, reverse=True)[0]

    def _latest_agent_dispatch_daemon_livenesses(
        self,
        workspace_id: WorkspaceId,
    ) -> dict[str, Mapping[str, object]]:
        livenesses: dict[str, Mapping[str, object]] = {}
        for entry in self.event_log_reader.list_workspace_events(workspace_id):
            if (
                entry.record.event_kind
                is not PlatformEventKind.AGENT_DISPATCH_DAEMON_LIVENESS_CHANGED
            ):
                continue
            liveness_payload = entry.record.payload.get("daemonLiveness")
            if not isinstance(liveness_payload, MappingABC):
                continue
            dispatcher_id = liveness_payload.get("dispatcherId")
            if not isinstance(dispatcher_id, str) or not dispatcher_id.strip():
                continue
            livenesses[dispatcher_id] = {
                **dict(liveness_payload),
                "sourceEventSequence": entry.sequence,
            }
        return livenesses

    def _select_agent_dispatch_daemon_liveness(
        self,
        workspace_id: WorkspaceId,
        *,
        dispatcher_id: str | None = None,
    ) -> Mapping[str, object] | None:
        livenesses = self._latest_agent_dispatch_daemon_livenesses(workspace_id)
        if dispatcher_id is not None:
            return livenesses.get(_non_empty_text(dispatcher_id, "dispatcherId"))
        default_liveness = livenesses.get("agent-dispatch-daemon")
        if default_liveness is not None:
            return default_liveness
        running = [
            liveness
            for liveness in livenesses.values()
            if _agent_dispatch_daemon_running(str(liveness.get("state")))
        ]
        if running:
            return sorted(
                running,
                key=lambda item: str(item.get("updatedAt") or ""),
                reverse=True,
            )[0]
        if not livenesses:
            return None
        return sorted(
            livenesses.values(),
            key=lambda item: str(item.get("updatedAt") or ""),
            reverse=True,
        )[0]

    def _latest_active_agent_dispatch_lease_for_target(
        self,
        workspace_id: WorkspaceId,
        *,
        target_agent_id: str,
        target_handle_id: str | None,
        now: datetime,
    ) -> AgentDispatchLeaseRecord | None:
        matches = []
        for lease in self._latest_agent_dispatch_leases(workspace_id).values():
            if lease.state is not AgentDispatchLeaseState.ACTIVE:
                continue
            if lease.expires_at is not None and lease.expires_at <= now:
                continue
            same_target = (
                lease.target_handle_id == target_handle_id
                if target_handle_id is not None
                else (
                    lease.target_handle_id is None
                    and lease.target_agent_id == target_agent_id
                )
            )
            if same_target:
                matches.append(lease)
        if not matches:
            return None
        return sorted(matches, key=lambda item: item.updated_at, reverse=True)[0]

    def _latest_agent_exchange_thread_by_id(
        self,
        workspace_id: WorkspaceId,
        thread_id: str,
    ) -> AgentExchangeThread | None:
        return self._latest_agent_exchange_threads(workspace_id).get(thread_id)

    def _require_agent_exchange_thread(
        self,
        workspace_id: WorkspaceId,
        thread_id: str,
    ) -> AgentExchangeThread:
        thread = self._latest_agent_exchange_thread_by_id(workspace_id, thread_id)
        if thread is None:
            raise ValueError("agent exchange thread not found.")
        return thread

    def _require_visible_agent_exchange_thread(
        self,
        workspace_id: WorkspaceId,
        thread_id: str,
        requesting_agent_id: AgentId | str | None,
    ) -> AgentExchangeThread:
        self._require_workspace(workspace_id)
        thread = self._require_agent_exchange_thread(workspace_id, thread_id)
        if requesting_agent_id is not None:
            resolved_agent_id = self._require_workspace_agent(
                workspace_id,
                requesting_agent_id,
            ).registration.agent_id.value
            if not thread.is_visible_to(resolved_agent_id):
                raise ValueError("agent exchange thread is not visible to requesting agent.")
        return thread

    def _latest_agent_exchange_threads(
        self,
        workspace_id: WorkspaceId,
    ) -> dict[str, AgentExchangeThread]:
        threads: dict[str, AgentExchangeThread] = {}
        for entry in self.event_log_reader.list_workspace_events(workspace_id):
            if (
                entry.record.event_kind
                is not PlatformEventKind.AGENT_EXCHANGE_THREAD_CHANGED
            ):
                continue
            thread_payload = entry.record.payload.get("thread")
            if not isinstance(thread_payload, MappingABC):
                continue
            thread = AgentExchangeThread.from_mapping(
                {
                    **dict(thread_payload),
                    "sourceEventSequence": entry.sequence,
                }
            )
            threads[thread.exchange_thread_id] = thread
        return threads

    def _record_agent_exchange_thread_after_request_change(
        self,
        *,
        workspace_id: WorkspaceId,
        request: AgentExchangeRequest,
        action: str,
        occurred_at: datetime,
        policy: AgentExchangeRequestPolicy | None = None,
        effective_thread_config: Mapping[str, object] | None = None,
        existing_thread: AgentExchangeThread | None = None,
    ) -> int:
        thread_id = (
            request.thread_id
            or request.root_request_id
            or request.exchange_request_id
        )
        current_thread = existing_thread or self._latest_agent_exchange_thread_by_id(
            workspace_id,
            thread_id,
        )
        requests = [
            item
            for item in self._latest_agent_exchange_requests(workspace_id).values()
            if item.thread_id == thread_id
        ]
        participant_agent_ids = tuple(
            dict.fromkeys(
                [
                    *(current_thread.participant_agent_ids if current_thread else ()),
                    *[
                        agent_id
                        for item in requests
                        for agent_id in (item.source_agent_id, item.target_agent_id)
                    ],
                    request.source_agent_id,
                    request.target_agent_id,
                ]
            )
        )
        completed_turn_count = sum(
            1
            for item in requests
            if item.terminal_reason
            is AgentExchangeRequestTerminalReason.RESPONDED
        )
        active_request_count = sum(1 for item in requests if item.is_active())
        if current_thread is None:
            config = effective_thread_config or {
                "visibility": AgentExchangeThreadVisibility.WORKSPACE_READABLE.value,
                "maxTurns": request.max_turns,
                "followUpPolicy": AgentExchangeFollowUpPolicy.SINGLE_TARGET_CHAIN.value,
            }
            thread = AgentExchangeThread.from_mapping(
                {
                    "exchangeThreadId": thread_id,
                    "workspaceId": workspace_id.value,
                    "rootRequestId": request.root_request_id or request.exchange_request_id,
                    "createdByAgentId": request.source_agent_id,
                    "participantAgentIds": participant_agent_ids,
                    "sourceAgentId": request.source_agent_id,
                    "targetAgentId": request.target_agent_id,
                    "visibility": config["visibility"],
                    "maxTurns": (
                        config["maxTurns"]
                        if int(config["maxTurns"]) >= 0
                        else 0
                    ),
                    "completedTurnCount": completed_turn_count,
                    "activeRequestCount": active_request_count,
                    "followUpPolicy": config["followUpPolicy"],
                    "authorizationMode": (
                        policy.authorization_mode.value
                        if policy is not None
                        else request.authorization_mode.value
                    ),
                    "threadStatus": AgentExchangeThreadStatus.ACTIVE.value,
                    "createdAt": request.created_at.isoformat(),
                    "updatedAt": occurred_at.isoformat(),
                    "lastActivityAt": occurred_at.isoformat(),
                    "metadata": {
                        "lastAction": action,
                        "autoAppendExchangeResultToSharedContext": False,
                        "parallelSchedulingExecuted": False,
                    },
                }
            )
        else:
            thread = current_thread.activity_copy(
                participant_agent_ids=participant_agent_ids,
                completed_turn_count=completed_turn_count,
                active_request_count=active_request_count,
                last_activity_at=occurred_at,
                metadata={
                    "lastAction": action,
                    "autoAppendExchangeResultToSharedContext": False,
                    "parallelSchedulingExecuted": False,
                },
            )
        sequence = self.event_log_reader.append(
            PlatformEventRecord.create(
                workspace_id=workspace_id,
                event_kind=PlatformEventKind.AGENT_EXCHANGE_THREAD_CHANGED,
                aggregate_type="agent_exchange_thread",
                aggregate_id=thread.exchange_thread_id,
                occurred_at=occurred_at,
                payload={
                    "action": action,
                    "thread": thread.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )
        return sequence

    def _effective_agent_exchange_thread_config(
        self,
        *,
        policy: AgentExchangeRequestPolicy,
        source_agent_runtime_config: Mapping[str, object],
        target_agent_runtime_config: Mapping[str, object],
    ) -> Mapping[str, object]:
        source = self._agent_exchange_runtime_config(source_agent_runtime_config)
        target = self._agent_exchange_runtime_config(target_agent_runtime_config)
        source_visible = self._optional_thread_workspace_visible(source)
        target_visible = self._optional_thread_workspace_visible(target)
        thread_workspace_visible = (
            policy.thread_workspace_visible
            if source_visible is None
            else source_visible
        ) and (
            policy.thread_workspace_visible
            if target_visible is None
            else target_visible
        )
        turn_values = [
            policy.max_turns,
            *[
                value
                for value in (
                    self._optional_thread_max_turns(source),
                    self._optional_thread_max_turns(target),
                )
                if value is not None
            ],
        ]
        max_turns = self._effective_max_turns(turn_values)
        follow_up_policy = self._effective_follow_up_policy(
            (
                policy.follow_up_policy.value,
                self._optional_follow_up_policy(source),
                self._optional_follow_up_policy(target),
            )
        )
        return {
            "visibility": (
                AgentExchangeThreadVisibility.WORKSPACE_READABLE.value
                if thread_workspace_visible
                else AgentExchangeThreadVisibility.PARTICIPANTS_ONLY.value
            ),
            "maxTurns": max_turns,
            "followUpPolicy": follow_up_policy,
        }

    def _agent_exchange_runtime_config(
        self,
        runtime_config: Mapping[str, object],
    ) -> Mapping[str, object]:
        raw = runtime_config.get("agentExchange")
        if raw is None:
            raw = runtime_config.get("agent_exchange")
        if raw is None:
            return {}
        if not isinstance(raw, MappingABC):
            raise ValueError("runtimeConfig.agentExchange must be an object.")
        return dict(raw)

    def _optional_thread_workspace_visible(
        self,
        config: Mapping[str, object],
    ) -> bool | None:
        value = config.get("threadWorkspaceVisible")
        if value is None:
            value = config.get("thread_workspace_visible")
        if value is None:
            return None
        if not isinstance(value, bool):
            raise ValueError("threadWorkspaceVisible must be a boolean.")
        return value

    def _optional_thread_max_turns(
        self,
        config: Mapping[str, object],
    ) -> int | None:
        value = config.get("maxThreadTurns")
        if value is None:
            value = config.get("max_thread_turns")
        if value is None:
            value = config.get("maxTurns")
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("maxThreadTurns must be an integer.")
        if value < -1:
            raise ValueError("maxThreadTurns must be -1, 0, or a positive integer.")
        return value

    def _optional_follow_up_policy(
        self,
        config: Mapping[str, object],
    ) -> str | None:
        value = config.get("followUpPolicy")
        if value is None:
            value = config.get("follow_up_policy")
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError("followUpPolicy must be a non-empty string.")
        return AgentExchangeFollowUpPolicy(
            value.strip().lower().replace("-", "_")
        ).value

    def _effective_max_turns(self, values: list[int]) -> int:
        if any(value == -1 for value in values):
            return -1
        positive_values = [value for value in values if value > 0]
        if positive_values:
            return min(positive_values)
        return 0

    def _effective_follow_up_policy(
        self,
        values: tuple[str | None, ...],
    ) -> str:
        normalized = [
            AgentExchangeFollowUpPolicy(value.strip().lower().replace("-", "_"))
            for value in values
            if value is not None
        ]
        if AgentExchangeFollowUpPolicy.DISABLED in normalized:
            return AgentExchangeFollowUpPolicy.DISABLED.value
        if AgentExchangeFollowUpPolicy.SINGLE_TARGET_CHAIN in normalized:
            return AgentExchangeFollowUpPolicy.SINGLE_TARGET_CHAIN.value
        if AgentExchangeFollowUpPolicy.PARALLEL_SINGLE_TARGET_REQUESTS in normalized:
            return AgentExchangeFollowUpPolicy.PARALLEL_SINGLE_TARGET_REQUESTS.value
        return AgentExchangeFollowUpPolicy.SINGLE_TARGET_CHAIN.value

    def _validate_agent_exchange_thread_send_budget(
        self,
        *,
        thread: AgentExchangeThread,
        policy_max_turns: int,
    ) -> None:
        if policy_max_turns == -1:
            raise ValueError("maxTurns=-1 disables request creation.")
        max_turns = self._effective_max_turns(
            [
                value
                for value in (thread.max_turns, policy_max_turns)
                if value >= 0
            ]
        )
        if max_turns > 0 and (
            thread.completed_turn_count + thread.active_request_count
        ) >= max_turns:
            raise ValueError("agent exchange thread exceeds maxTurns.")

    def _validate_agent_exchange_thread_follow_up(
        self,
        *,
        thread: AgentExchangeThread,
        policy: AgentExchangeRequestPolicy,
        source_agent_id: AgentId,
        target_agent_id: AgentId,
    ) -> None:
        if thread.follow_up_policy is AgentExchangeFollowUpPolicy.DISABLED:
            raise ValueError("follow-up request creation is disabled.")
        if policy.follow_up_policy is AgentExchangeFollowUpPolicy.DISABLED:
            raise ValueError("follow-up request creation is disabled.")
        if source_agent_id == target_agent_id:
            raise ValueError("sourceAgentId and targetAgentId must not be the same agent.")

    def _latest_thread_request_id(
        self,
        workspace_id: WorkspaceId,
        thread_id: str,
    ) -> str | None:
        requests = [
            request
            for request in self._latest_agent_exchange_requests(workspace_id).values()
            if request.thread_id == thread_id
        ]
        if not requests:
            return None
        return sorted(
            requests,
            key=lambda item: (item.created_at, item.exchange_request_id),
        )[-1].exchange_request_id

    def _validate_agent_exchange_request_authorization(
        self,
        *,
        policy: AgentExchangeRequestPolicy,
        workspace_id: WorkspaceId,
        source_agent_id: AgentId,
        target_agent_id: AgentId,
        linked_delegated_wake_grant_id: str | None,
    ) -> None:
        if policy.authorization_mode is AgentExchangeAuthorizationMode.DISABLED:
            raise ValueError("agent exchange request creation is disabled.")
        if (
            policy.authorization_mode
            is AgentExchangeAuthorizationMode.DELEGATED_GRANT_REQUIRED
        ):
            if linked_delegated_wake_grant_id is None:
                raise ValueError("linkedDelegatedWakeGrantId is required.")
            grant = self._latest_delegated_wake_grant_by_id(
                workspace_id,
                linked_delegated_wake_grant_id,
            )
            if grant is None:
                raise ValueError("delegated wake grant not found.")
            if grant.source_agent_id != source_agent_id.value:
                raise ValueError("delegated wake grant source_agent_mismatch.")
            if grant.target_agent_id != target_agent_id.value:
                raise ValueError("delegated wake grant target_agent_mismatch.")
            if grant.state in {
                DelegatedWakeGrantState.REVOKED,
                DelegatedWakeGrantState.DENIED,
                DelegatedWakeGrantState.EXPIRED,
            } or grant.is_expired():
                raise ValueError("delegated wake grant is not active.")

    def _validate_agent_exchange_sub_request(
        self,
        *,
        policy: AgentExchangeRequestPolicy,
        workspace_id: WorkspaceId,
        source_agent_id: AgentId,
        parent_request: AgentExchangeRequest,
    ) -> None:
        if policy.sub_request_policy is AgentExchangeSubRequestPolicy.DISABLED:
            raise ValueError("sub request creation is disabled.")
        if (
            policy.sub_request_policy
            is AgentExchangeSubRequestPolicy.ALLOWED_FOR_CONFIGURED_AGENTS
            and source_agent_id.value not in set(policy.allowed_sub_request_agent_ids)
        ):
            raise ValueError("sourceAgentId is not allowed to create sub requests.")
        records = self._latest_agent_exchange_requests(workspace_id)
        depth = self._agent_exchange_request_depth(parent_request, records) + 1
        if depth > policy.max_sub_request_depth:
            raise ValueError("sub request depth exceeds maxSubRequestDepth.")
        child_count = sum(
            1
            for request in records.values()
            if request.parent_request_id == parent_request.exchange_request_id
        )
        if child_count >= policy.max_child_requests:
            raise ValueError("sub request count exceeds maxChildRequests.")

    def _agent_exchange_request_depth(
        self,
        request: AgentExchangeRequest,
        records: Mapping[str, AgentExchangeRequest],
    ) -> int:
        depth = 0
        seen = {request.exchange_request_id}
        current = request
        while current.parent_request_id is not None:
            if current.parent_request_id in seen:
                raise ValueError("agent exchange request parent chain contains a cycle.")
            seen.add(current.parent_request_id)
            parent = records.get(current.parent_request_id)
            if parent is None:
                break
            depth += 1
            current = parent
        return depth

    def _resolve_agent_wake_profile(
        self,
        profile: AgentWakeProfile | Mapping[str, object] | None,
        *,
        workspace_id: WorkspaceId,
        agent_id: AgentId,
        config_path: str | None,
    ) -> AgentWakeProfile:
        if isinstance(profile, AgentWakeProfile):
            resolved = profile
        else:
            resolved = AgentWakeProfile.from_mapping(
                {
                    "workspaceId": workspace_id.value,
                    "agentId": agent_id.value,
                    **dict(profile or {}),
                    **({"configPath": config_path} if config_path is not None else {}),
                }
            )
        if resolved.workspace_id != workspace_id.value:
            raise ValueError("agent wake profile workspaceId mismatch.")
        if resolved.agent_id != agent_id.value:
            raise ValueError("agent wake profile agentId mismatch.")
        return resolved

    def _build_agent_wake_ticket(
        self,
        *,
        request: AgentExchangeRequest,
        profile: AgentWakeProfile,
        database_path: str,
        workspace_root: str,
        plugins_directory: str,
        runtime_profile_path: str | None,
        delivery_attempt_count: int,
        created_at: datetime,
    ) -> AgentWakeTicket:
        thread_id = request.thread_id or request.root_request_id or request.exchange_request_id
        local_runtime_hints: dict[str, object] = {
            "runtimeConfigSource": (
                "profile" if runtime_profile_path is not None else "explicit_args"
            ),
        }
        if runtime_profile_path is not None:
            local_runtime_hints["profileConfigPath"] = runtime_profile_path
        recommended_action = self._agent_wake_recommended_action(
            database_path=database_path,
            workspace_root=workspace_root,
            plugins_directory=plugins_directory,
            profile_path=runtime_profile_path,
            workspace_id=request.workspace_id,
            exchange_request_id=request.exchange_request_id,
            target_agent_id=request.target_agent_id,
        )
        source_attribution = {
            "sourceType": "agent_exchange_request",
            "authorType": "agent",
            "sourceChannel": "local_agent_wake_daemon",
        }
        if isinstance(request.metadata, MappingABC):
            raw_exchange = request.metadata.get("agentExchange")
            if isinstance(raw_exchange, MappingABC):
                source_attribution = {
                    **source_attribution,
                    **dict(raw_exchange),
                }
        for duplicated_key in (
            "authorAgentId",
            "targetAgentId",
            "instructionAuthority",
        ):
            source_attribution.pop(duplicated_key, None)
        return AgentWakeTicket(
            workspace_id=request.workspace_id,
            target_agent_id=request.target_agent_id,
            source_agent_id=request.source_agent_id,
            exchange_request_id=request.exchange_request_id,
            thread_id=thread_id,
            request_kind=request.request_kind.value,
            request_summary=request.request_summary,
            instruction_authority="agent_suggestion",
            source_attribution=source_attribution,
            local_runtime_hints=local_runtime_hints,
            recommended_action=recommended_action,
            delivery_attempt_count=delivery_attempt_count,
            created_at=created_at,
        )

    def _agent_wake_recommended_action(
        self,
        *,
        database_path: str,
        workspace_root: str,
        plugins_directory: str,
        profile_path: str | None = None,
        workspace_id: str,
        exchange_request_id: str,
        target_agent_id: str,
    ) -> Mapping[str, object]:
        source_root = str(Path(__file__).resolve().parents[3])
        common = [sys.executable, "-m", "agent_os.local_runtime"]
        if profile_path is not None:
            common.extend(["--profile", profile_path])
        else:
            common.extend(
                [
                    "--database",
                    database_path,
                    "--workspace-root",
                    workspace_root,
                    "--plugins-directory",
                    plugins_directory,
                ]
            )
        common.append("--pretty")
        inspect = [
            *common,
            "agent-exchange-status",
            "--workspace-id",
            workspace_id,
            "--exchange-request-id",
            exchange_request_id,
            "--format",
            "compact",
        ]
        respond = [
            *common,
            "agent-exchange-request-respond",
            "--workspace-id",
            workspace_id,
            "--exchange-request-id",
            exchange_request_id,
            "--responding-agent-id",
            target_agent_id,
            "--response-summary",
            "<short target-agent response>",
        ]
        return {
            "schema": "agent_wake_action.v1",
            "runtimeConfigSource": (
                "profile" if profile_path is not None else "explicit_args"
            ),
            **({"profilePath": profile_path} if profile_path is not None else {}),
            "runtimeEnvironment": {"PYTHONPATH": source_root},
            "inspectArgv": inspect,
            "respondArgvTemplate": respond,
        }

    def _agent_wake_ticket_path(
        self,
        *,
        profile: AgentWakeProfile,
        ticket: AgentWakeTicket,
        workspace_root: str,
    ) -> str | None:
        if profile.wake_mode is AgentWakeMode.NOTIFY_ONLY:
            return None
        base = (
            Path(profile.handoff_directory)
            if profile.handoff_directory is not None
            else (
                Path(workspace_root)
                / ".agent_os"
                / "wake_tickets"
                / _agent_wake_ticket_namespace(ticket)
            )
        )
        return str(base / _agent_wake_ticket_filename(ticket))

    def _deliver_agent_wake_ticket(
        self,
        *,
        profile: AgentWakeProfile,
        ticket: AgentWakeTicket,
        ticket_path: str | None,
        occurred_at: datetime,
    ) -> AgentWakeDeliveryRecord:
        if profile.wake_mode is AgentWakeMode.NOTIFY_ONLY:
            return AgentWakeDeliveryRecord(
                workspace_id=ticket.workspace_id,
                target_agent_id=ticket.target_agent_id,
                exchange_request_id=ticket.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                wake_mode=profile.wake_mode,
                status=AgentWakeDeliveryStatus.DELIVERED,
                ticket_path=None,
                created_at=occurred_at,
                completed_at=_utc_now(),
            )
        if ticket_path is None:
            return AgentWakeDeliveryRecord(
                workspace_id=ticket.workspace_id,
                target_agent_id=ticket.target_agent_id,
                exchange_request_id=ticket.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                wake_mode=profile.wake_mode,
                status=AgentWakeDeliveryStatus.FAILED,
                failure_reason="ticket_path_required",
                created_at=occurred_at,
                completed_at=_utc_now(),
            )
        try:
            self._write_agent_wake_ticket_file(ticket, ticket_path)
            if profile.wake_mode is AgentWakeMode.HANDOFF_FILE:
                return AgentWakeDeliveryRecord(
                    workspace_id=ticket.workspace_id,
                    target_agent_id=ticket.target_agent_id,
                    exchange_request_id=ticket.exchange_request_id,
                    thread_id=ticket.thread_id,
                    wake_ticket_id=ticket.wake_ticket_id,
                    wake_mode=profile.wake_mode,
                    status=AgentWakeDeliveryStatus.DELIVERED,
                    ticket_path=ticket_path,
                    created_at=occurred_at,
                    completed_at=_utc_now(),
                )
            rendered_argv = render_safe_command_argv(
                profile.command_argv,
                ticket_path=ticket_path,
                workspace_id=ticket.workspace_id,
                agent_id=ticket.target_agent_id,
                request_id=ticket.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
            )
            if profile.child_process_policy is AgentWakeChildProcessPolicy.DETACH:
                creationflags = (
                    subprocess.CREATE_NEW_PROCESS_GROUP
                    if sys.platform.startswith("win")
                    else 0
                )
                subprocess.Popen(
                    rendered_argv,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    shell=False,
                    creationflags=creationflags,
                )
                return AgentWakeDeliveryRecord(
                    workspace_id=ticket.workspace_id,
                    target_agent_id=ticket.target_agent_id,
                    exchange_request_id=ticket.exchange_request_id,
                    thread_id=ticket.thread_id,
                    wake_ticket_id=ticket.wake_ticket_id,
                    wake_mode=profile.wake_mode,
                    status=AgentWakeDeliveryStatus.DELIVERED,
                    ticket_path=ticket_path,
                    command_argv_summary=rendered_argv,
                    created_at=occurred_at,
                    completed_at=_utc_now(),
                )
            completed = subprocess.run(
                rendered_argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                shell=False,
            )
            return AgentWakeDeliveryRecord(
                workspace_id=ticket.workspace_id,
                target_agent_id=ticket.target_agent_id,
                exchange_request_id=ticket.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                wake_mode=profile.wake_mode,
                status=(
                    AgentWakeDeliveryStatus.DELIVERED
                    if completed.returncode == 0
                    else AgentWakeDeliveryStatus.FAILED
                ),
                ticket_path=ticket_path,
                command_argv_summary=rendered_argv,
                command_exit_code=completed.returncode,
                failure_reason=(
                    None
                    if completed.returncode == 0
                    else "command_exit_nonzero"
                ),
                created_at=occurred_at,
                completed_at=_utc_now(),
            )
        except OSError as exc:
            return AgentWakeDeliveryRecord(
                workspace_id=ticket.workspace_id,
                target_agent_id=ticket.target_agent_id,
                exchange_request_id=ticket.exchange_request_id,
                thread_id=ticket.thread_id,
                wake_ticket_id=ticket.wake_ticket_id,
                wake_mode=profile.wake_mode,
                status=AgentWakeDeliveryStatus.FAILED,
                ticket_path=ticket_path,
                command_argv_summary=tuple(profile.command_argv),
                failure_reason=f"{exc.__class__.__name__}: {exc}",
                created_at=occurred_at,
                completed_at=_utc_now(),
            )

    def _write_agent_wake_ticket_file(
        self,
        ticket: AgentWakeTicket,
        ticket_path: str,
    ) -> None:
        path = Path(ticket_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(ticket.to_metadata(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _agent_wake_skip_reason(
        self,
        *,
        profile: AgentWakeProfile,
        records: list[AgentWakeDeliveryRecord],
        checked_at: datetime,
    ) -> str | None:
        if not profile.enabled:
            return "profile_disabled"
        if any(
            record.status
            in {
                AgentWakeDeliveryStatus.LEASED,
                AgentWakeDeliveryStatus.DELIVERED,
            }
            for record in records
        ):
            return "already_delivered_or_leased"
        delivery_markers = [
            record for record in records if record.counts_as_delivery_marker()
        ]
        if len(delivery_markers) >= profile.max_wake_attempts_per_request:
            return "max_attempts_reached"
        latest_marker = (
            max(delivery_markers, key=lambda item: item.created_at)
            if delivery_markers
            else None
        )
        if latest_marker is not None and profile.cooldown_ms > 0:
            elapsed_ms = (
                checked_at - latest_marker.created_at
            ).total_seconds() * 1000
            if elapsed_ms < profile.cooldown_ms:
                return "cooldown_active"
        return None

    def _append_agent_wake_delivery(
        self,
        workspace_id: WorkspaceId,
        *,
        delivery: AgentWakeDeliveryRecord,
        ticket: AgentWakeTicket,
        action: str,
        occurred_at: datetime,
    ) -> int:
        return self.event_log_reader.append(
            PlatformEventRecord.create(
                workspace_id=workspace_id,
                event_kind=PlatformEventKind.AGENT_WAKE_DELIVERY_RECORDED,
                aggregate_type="agent_wake_delivery",
                aggregate_id=delivery.exchange_request_id,
                occurred_at=occurred_at,
                payload={
                    "action": action,
                    "delivery": delivery.to_metadata(),
                    "ticket": ticket.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )

    def _append_agent_dispatch(
        self,
        workspace_id: WorkspaceId,
        *,
        dispatch: AgentDispatchRecord,
        action: str,
        occurred_at: datetime,
    ) -> int:
        return self.event_log_reader.append(
            PlatformEventRecord.create(
                workspace_id=workspace_id,
                event_kind=PlatformEventKind.AGENT_DISPATCH_CHANGED,
                aggregate_type="agent_dispatch",
                aggregate_id=dispatch.dispatch_id,
                occurred_at=occurred_at,
                payload={
                    "action": action,
                    "dispatch": dispatch.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )

    def _append_agent_dispatch_lease(
        self,
        workspace_id: WorkspaceId,
        *,
        lease: AgentDispatchLeaseRecord,
        action: str,
        occurred_at: datetime,
    ) -> int:
        return self.event_log_reader.append(
            PlatformEventRecord.create(
                workspace_id=workspace_id,
                event_kind=PlatformEventKind.AGENT_DISPATCH_LEASE_CHANGED,
                aggregate_type="agent_dispatch_lease",
                aggregate_id=lease.lease_id,
                occurred_at=occurred_at,
                payload={
                    "action": action,
                    "lease": lease.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )

    def _append_agent_dispatch_daemon_liveness(
        self,
        workspace_id: WorkspaceId,
        *,
        liveness: Mapping[str, object],
        action: str,
        occurred_at: datetime,
    ) -> int:
        return self.event_log_reader.append(
            PlatformEventRecord.create(
                workspace_id=workspace_id,
                event_kind=PlatformEventKind.AGENT_DISPATCH_DAEMON_LIVENESS_CHANGED,
                aggregate_type="agent_dispatch_daemon_liveness",
                aggregate_id=str(liveness["dispatcherId"]),
                occurred_at=occurred_at,
                payload={
                    "action": action,
                    "daemonLiveness": dict(liveness),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )

    def _append_claude_session_handle(
        self,
        workspace_id: WorkspaceId,
        *,
        handle: ClaudeRegisteredSessionHandle,
        action: str,
        occurred_at: datetime,
        event_id: PlatformEventId | str | None = None,
    ) -> int:
        return self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=workspace_id,
                event_kind=(
                    PlatformEventKind.CLAUDE_REGISTERED_SESSION_HANDLE_CHANGED
                ),
                aggregate_type="claude_registered_session_handle",
                aggregate_id=handle.handle_id,
                occurred_at=occurred_at,
                payload={
                    "action": action,
                    "handle": handle.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )

    def _append_claude_activation_attempt(
        self,
        workspace_id: WorkspaceId,
        *,
        attempt: ClaudeRegisteredSessionActivationAttempt,
        ticket: AgentWakeTicket,
        action: str,
        occurred_at: datetime,
    ) -> int:
        return self.event_log_reader.append(
            PlatformEventRecord.create(
                workspace_id=workspace_id,
                event_kind=(
                    PlatformEventKind.CLAUDE_REGISTERED_SESSION_ACTIVATION_RECORDED
                ),
                aggregate_type="claude_registered_session_activation",
                aggregate_id=attempt.exchange_request_id,
                occurred_at=occurred_at,
                payload={
                    "action": action,
                    "activation": attempt.to_metadata(),
                    "ticket": ticket.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )

    def _append_codex_session_handle(
        self,
        workspace_id: WorkspaceId,
        *,
        handle: CodexRegisteredSessionHandle,
        action: str,
        occurred_at: datetime,
        event_id: PlatformEventId | str | None = None,
    ) -> int:
        return self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=workspace_id,
                event_kind=(
                    PlatformEventKind.CODEX_REGISTERED_SESSION_HANDLE_CHANGED
                ),
                aggregate_type="codex_registered_session_handle",
                aggregate_id=handle.handle_id,
                occurred_at=occurred_at,
                payload={
                    "action": action,
                    "handle": handle.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )

    def _append_codex_activation_attempt(
        self,
        workspace_id: WorkspaceId,
        *,
        attempt: CodexRegisteredSessionActivationAttempt,
        ticket: AgentWakeTicket,
        action: str,
        occurred_at: datetime,
    ) -> int:
        return self.event_log_reader.append(
            PlatformEventRecord.create(
                workspace_id=workspace_id,
                event_kind=(
                    PlatformEventKind.CODEX_REGISTERED_SESSION_ACTIVATION_RECORDED
                ),
                aggregate_type="codex_registered_session_activation",
                aggregate_id=attempt.exchange_request_id,
                occurred_at=occurred_at,
                payload={
                    "action": action,
                    "activation": attempt.to_metadata(),
                    "ticket": ticket.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )

    def _append_hermes_session_handle(
        self,
        workspace_id: WorkspaceId,
        *,
        handle: HermesRegisteredSessionHandle,
        action: str,
        occurred_at: datetime,
        event_id: PlatformEventId | str | None = None,
    ) -> int:
        return self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=workspace_id,
                event_kind=(
                    PlatformEventKind.HERMES_REGISTERED_SESSION_HANDLE_CHANGED
                ),
                aggregate_type="hermes_registered_session_handle",
                aggregate_id=handle.handle_id,
                occurred_at=occurred_at,
                payload={
                    "action": action,
                    "handle": handle.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )

    def _append_agent_endpoint(
        self,
        workspace_id: WorkspaceId,
        *,
        endpoint: AgentEndpointRecord,
        action: str,
        occurred_at: datetime,
        event_id: PlatformEventId | str | None = None,
    ) -> int:
        return self.event_log_reader.append(
            PlatformEventRecord.create(
                event_id=(
                    _platform_event_id(event_id)
                    if event_id is not None
                    else None
                ),
                workspace_id=workspace_id,
                event_kind=PlatformEventKind.AGENT_ENDPOINT_CHANGED,
                aggregate_type="agent_endpoint",
                aggregate_id=endpoint.endpoint_id,
                occurred_at=occurred_at,
                payload={
                    "action": action,
                    "endpoint": endpoint.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )

    def _append_hermes_activation_attempt(
        self,
        workspace_id: WorkspaceId,
        *,
        attempt: HermesRegisteredSessionActivationAttempt,
        ticket: AgentWakeTicket,
        action: str,
        occurred_at: datetime,
    ) -> int:
        return self.event_log_reader.append(
            PlatformEventRecord.create(
                workspace_id=workspace_id,
                event_kind=(
                    PlatformEventKind.HERMES_REGISTERED_SESSION_ACTIVATION_RECORDED
                ),
                aggregate_type="hermes_registered_session_activation",
                aggregate_id=attempt.exchange_request_id,
                occurred_at=occurred_at,
                payload={
                    "action": action,
                    "activation": attempt.to_metadata(),
                    "ticket": ticket.to_metadata(),
                },
                metadata={"source": "local_platform_operation_service"},
            )
        )

    def _agent_exchange_status_timeline(
        self,
        workspace_id: WorkspaceId,
        *,
        exchange_request_id: str | None = None,
        dispatch_id: str | None = None,
        thread_id: str | None = None,
        limit: int = 80,
    ) -> Mapping[str, object]:
        events: list[Mapping[str, object]] = []
        for entry in self.event_log_reader.list_workspace_events(workspace_id):
            item = self._agent_exchange_status_timeline_event(
                entry,
                exchange_request_id=exchange_request_id,
                dispatch_id=dispatch_id,
                thread_id=thread_id,
            )
            if item is not None:
                activation = entry.record.payload.get("activation")
                if (
                    item.get("subject") == "provider_activation"
                    and item.get("stage") == "stdout_captured"
                    and isinstance(activation, MappingABC)
                    and activation.get("providerCommandStarted")
                ):
                    events.append(
                        {
                            **dict(item),
                            "stage": "provider_started",
                            "responseSourceStatus": None,
                            "responseSource": None,
                            "rawResponseSource": None,
                            "stdoutFallbackCaptured": False,
                            "standardResponded": False,
                            "captureMode": None,
                            "readableReason": _readable_status_reason(
                                "provider_started",
                                "provider command started for registered session activation.",
                            ),
                            "reasonCode": "provider_started",
                        }
                    )
                dispatch_payload = entry.record.payload.get("dispatch")
                dispatch_metadata = (
                    _nested_metadata(dispatch_payload)
                    if isinstance(dispatch_payload, MappingABC)
                    else {}
                )
                runtime_precheck = dispatch_metadata.get("providerRuntimePrecheck")
                if (
                    item.get("subject") == "agent_dispatch"
                    and item.get("action") == "lease_released"
                    and isinstance(runtime_precheck, MappingABC)
                    and runtime_precheck.get("probeFailed") is True
                ):
                    events.append(
                        {
                            **dict(item),
                            "stage": "probe_failed",
                            "reasonCode": "probe_failed",
                            "readableReason": _readable_status_reason(
                                "probe_failed",
                                str(
                                    runtime_precheck.get("failureReason")
                                    or "provider runtime status probe failed."
                                ),
                            ),
                            "providerRuntimePrecheck": dict(runtime_precheck),
                        }
                    )
                events.append(item)
        return {
            "schema": "agent_exchange_status_timeline.v1",
            "workspaceId": workspace_id.value,
            "exchangeRequestId": exchange_request_id,
            "dispatchId": dispatch_id,
            "threadId": thread_id,
            "source": "platform_event_log",
            "eventCount": len(events),
            "events": events[-limit:],
            "stdoutFallbackMeaning": STDOUT_FALLBACK_MEANING,
            "standardRespondMeaning": STANDARD_RESPOND_MEANING,
            "privateReasoningRead": False,
            "fullTranscriptRead": False,
        }

    def _agent_exchange_status_timeline_event(
        self,
        entry: PlatformEventLogEntry,
        *,
        exchange_request_id: str | None,
        dispatch_id: str | None,
        thread_id: str | None,
    ) -> Mapping[str, object] | None:
        kind = entry.record.event_kind
        payload = entry.record.payload
        if kind is PlatformEventKind.AGENT_EXCHANGE_REQUEST_CHANGED:
            request = payload.get("request")
            if not isinstance(request, MappingABC):
                return None
            if not _agent_status_ids_match(
                request,
                exchange_request_id=exchange_request_id,
                dispatch_id=None,
                thread_id=thread_id,
            ):
                return None
            action = str(payload.get("action") or "")
            response_source_status = _agent_response_source_status(request)
            stage = "created" if action == "created" else action
            if action == "responded":
                stage = (
                    "stdout_captured"
                    if response_source_status["stdoutFallbackCaptured"]
                    else "responded"
                )
            return _agent_status_timeline_item(
                entry,
                action=action,
                stage=stage,
                subject="agent_exchange_request",
                ids=request,
                response_source_status=response_source_status,
                readable_reason=_agent_request_readable_reason_mapping(request),
            )

        if kind is PlatformEventKind.AGENT_DISPATCH_CHANGED:
            dispatch = payload.get("dispatch")
            if not isinstance(dispatch, MappingABC):
                return None
            if not _agent_status_ids_match(
                dispatch,
                exchange_request_id=exchange_request_id,
                dispatch_id=dispatch_id,
                thread_id=thread_id,
            ):
                return None
            action = str(payload.get("action") or "")
            status = str(dispatch.get("status") or "")
            stage = {
                "queued": "queued",
                "leased": "leased",
                "worker_skipped": "skipped",
                "worker_failed": "failed",
                "lease_released": status or "released",
                "lease_recovered": "lease_recovered",
            }.get(action, action or status)
            readable_reason = _agent_dispatch_readable_reason(dispatch)
            return _agent_status_timeline_item(
                entry,
                action=action,
                stage=stage,
                subject="agent_dispatch",
                ids=dispatch,
                readable_reason=readable_reason,
                retry_actor_status=_agent_dispatch_retry_actor_status(dispatch),
            )

        if kind is PlatformEventKind.AGENT_DISPATCH_LEASE_CHANGED:
            lease = payload.get("lease")
            if not isinstance(lease, MappingABC):
                return None
            if not _agent_status_ids_match(
                lease,
                exchange_request_id=exchange_request_id,
                dispatch_id=dispatch_id,
                thread_id=None,
            ):
                return None
            action = str(payload.get("action") or "")
            stage = {
                "acquired": "leased",
                "recovered": "lease_recovered",
            }.get(action, action)
            lease_metadata = lease.get("metadata")
            recovery_reason = (
                lease_metadata.get("recoveryReason")
                if isinstance(lease_metadata, MappingABC)
                else None
            )
            return _agent_status_timeline_item(
                entry,
                action=action,
                stage=stage,
                subject="agent_dispatch_lease",
                ids=lease,
                readable_reason=(
                    {
                        "schema": "agent_readable_status_reason.v1",
                        "reasonCode": "lease_released",
                        "message": "Dispatch lease was released by the worker.",
                    }
                    if action == "released"
                    else (
                        {
                            "schema": "agent_readable_status_reason.v1",
                            "reasonCode": "orphan_lease_recovered",
                            "message": (
                                "An orphan or expired dispatch lease was "
                                f"recovered: {recovery_reason}."
                            ),
                        }
                        if action == "recovered"
                        else None
                    )
                ),
            )

        if kind is PlatformEventKind.AGENT_WAKE_DELIVERY_RECORDED:
            delivery = payload.get("delivery")
            ticket = payload.get("ticket")
            if not isinstance(delivery, MappingABC):
                return None
            ids = {
                **dict(delivery),
                **(
                    {
                        "threadId": ticket.get("threadId"),
                        "exchangeRequestId": ticket.get("exchangeRequestId"),
                    }
                    if isinstance(ticket, MappingABC)
                    else {}
                ),
            }
            if not _agent_status_ids_match(
                ids,
                exchange_request_id=exchange_request_id,
                dispatch_id=None,
                thread_id=thread_id,
            ):
                return None
            delivery_status = str(delivery.get("status") or "")
            stage = "wake_delivered" if delivery_status == "delivered" else delivery_status
            return _agent_status_timeline_item(
                entry,
                action=str(payload.get("action") or ""),
                stage=stage,
                subject="agent_wake_delivery",
                ids=ids,
                readable_reason=_agent_wake_readable_reason(delivery),
            )

        if kind in {
            PlatformEventKind.CLAUDE_REGISTERED_SESSION_ACTIVATION_RECORDED,
            PlatformEventKind.CODEX_REGISTERED_SESSION_ACTIVATION_RECORDED,
            PlatformEventKind.HERMES_REGISTERED_SESSION_ACTIVATION_RECORDED,
        }:
            activation = payload.get("activation")
            if not isinstance(activation, MappingABC):
                return None
            if not _agent_status_ids_match(
                activation,
                exchange_request_id=exchange_request_id,
                dispatch_id=None,
                thread_id=thread_id,
            ):
                return None
            response_capture_status = str(
                activation.get("responseCaptureStatus") or ""
            )
            if response_capture_status == "recorded":
                stage = "stdout_captured"
            elif activation.get("providerCommandStarted"):
                stage = "provider_started"
            else:
                stage = str(activation.get("status") or payload.get("action") or "")
            return _agent_status_timeline_item(
                entry,
                action=str(payload.get("action") or ""),
                stage=stage,
                subject="provider_activation",
                ids=activation,
                provider=str(activation.get("provider") or ""),
                response_source_status=_agent_response_source_status_from_activation(
                    activation,
                ),
                readable_reason=_agent_activation_readable_reason(activation),
            )

        return None

    def _agent_wake_delivery_summary(
        self,
        workspace_id: WorkspaceId,
        *,
        exchange_request_id: str,
    ) -> Mapping[str, object]:
        entries = [
            entry
            for entry in self._agent_wake_delivery_entries(workspace_id)
            if entry["delivery"]["exchangeRequestId"] == exchange_request_id
        ]
        latest = (
            max(entries, key=lambda item: int(item["sourceEventSequence"]))
            if entries
            else None
        )
        delivered_entries = [
            entry
            for entry in entries
            if entry["delivery"]["status"] == AgentWakeDeliveryStatus.DELIVERED.value
        ]
        latest_delivered = (
            max(delivered_entries, key=lambda item: int(item["sourceEventSequence"]))
            if delivered_entries
            else None
        )
        claude_activation_summary = self._claude_activation_summary(
            workspace_id,
            exchange_request_id=exchange_request_id,
        )
        codex_activation_summary = self._codex_activation_summary(
            workspace_id,
            exchange_request_id=exchange_request_id,
        )
        hermes_activation_summary = self._hermes_activation_summary(
            workspace_id,
            exchange_request_id=exchange_request_id,
        )
        return {
            "schema": "agent_wake_delivery_summary.v1",
            "exchangeRequestId": exchange_request_id,
            "hasDeliveryRecord": bool(entries),
            "ticketDeliveryOccurred": bool(delivered_entries),
            "deliveryRecordCount": len(entries),
            "latestDelivery": latest["delivery"] if latest is not None else None,
            "latestTicket": latest["ticket"] if latest is not None else None,
            "latestDeliveredTicketId": (
                latest_delivered["delivery"]["wakeTicketId"]
                if latest_delivered is not None
                else None
            ),
            "latestDeliveredTicketPath": (
                latest_delivered["delivery"].get("ticketPath")
                if latest_delivered is not None
                else None
            ),
            "ticketDeliveryMeaning": (
                "Wake delivery records show local ticket, handoff-file, or "
                "configured argv delivery attempts only."
            ),
            **claude_activation_summary,
            **codex_activation_summary,
            **hermes_activation_summary,
            "providerCommandStarted": bool(
                claude_activation_summary.get("providerCommandStarted")
                or codex_activation_summary.get("providerCommandStarted")
                or hermes_activation_summary.get("providerCommandStarted")
            ),
            "sessionContinuityVerified": bool(
                claude_activation_summary.get("sessionContinuityVerified")
                or codex_activation_summary.get("sessionContinuityVerified")
                or hermes_activation_summary.get("sessionContinuityVerified")
            ),
            "targetResponseCompleted": bool(
                claude_activation_summary.get("targetResponseCompleted")
                or codex_activation_summary.get("targetResponseCompleted")
                or hermes_activation_summary.get("targetResponseCompleted")
            ),
            "runtimeWakeTriggered": bool(
                claude_activation_summary.get("runtimeWakeTriggered")
                or codex_activation_summary.get("runtimeWakeTriggered")
                or hermes_activation_summary.get("runtimeWakeTriggered")
            ),
            "realRuntimeConnected": False,
            "realRuntimeControlMeaning": (
                "False means the platform did not control a real external "
                "agent runtime/session; it does not mean ticket delivery failed. "
                "Claude/Codex/Hermes registered-session activation, if present, is a "
                "local official CLI resume attempt and not UI/TUI/browser takeover."
            ),
            "providerPromptInjected": False,
            "fileBodiesRead": False,
            "credentialStored": False,
        }

    def _claude_activation_summary(
        self,
        workspace_id: WorkspaceId,
        *,
        exchange_request_id: str,
    ) -> Mapping[str, object]:
        entries = [
            entry
            for entry in self._claude_activation_attempt_entries(workspace_id)
            if entry["activation"]["exchangeRequestId"] == exchange_request_id
        ]
        latest = (
            max(entries, key=lambda item: int(item["sourceEventSequence"]))
            if entries
            else None
        )
        if not entries:
            return {
                "claudeRegisteredSessionActivationOccurred": False,
                "latestClaudeRegisteredSessionActivation": None,
                "claudeRegisteredSessionActivationCount": 0,
            }
        provider_started = [
            entry
            for entry in entries
            if entry["activation"].get("providerCommandStarted")
        ]
        continuity_verified = [
            entry
            for entry in entries
            if entry["activation"].get("sessionContinuityVerified")
        ]
        target_completed = [
            entry
            for entry in entries
            if entry["activation"].get("targetResponseCompleted")
        ]
        request = self._latest_agent_exchange_request_by_id(
            workspace_id,
            exchange_request_id,
        )
        request_responded = (
            request is not None
            and request.terminal_reason is AgentExchangeRequestTerminalReason.RESPONDED
        )
        return {
            "claudeRegisteredSessionActivationOccurred": bool(provider_started),
            "providerCommandStarted": bool(provider_started),
            "sessionContinuityVerified": bool(continuity_verified),
            "targetResponseCompleted": bool(target_completed) or request_responded,
            "runtimeWakeTriggered": bool(provider_started),
            "latestClaudeRegisteredSessionActivation": (
                latest["activation"] if latest is not None else None
            ),
            "claudeRegisteredSessionActivationCount": len(entries),
        }

    def _codex_activation_summary(
        self,
        workspace_id: WorkspaceId,
        *,
        exchange_request_id: str,
    ) -> Mapping[str, object]:
        entries = [
            entry
            for entry in self._codex_activation_attempt_entries(workspace_id)
            if entry["activation"]["exchangeRequestId"] == exchange_request_id
        ]
        latest = (
            max(entries, key=lambda item: int(item["sourceEventSequence"]))
            if entries
            else None
        )
        if not entries:
            return {
                "codexRegisteredSessionActivationOccurred": False,
                "latestCodexRegisteredSessionActivation": None,
                "codexRegisteredSessionActivationCount": 0,
            }
        provider_started = [
            entry
            for entry in entries
            if entry["activation"].get("providerCommandStarted")
        ]
        continuity_verified = [
            entry
            for entry in entries
            if entry["activation"].get("sessionContinuityVerified")
        ]
        target_completed = [
            entry
            for entry in entries
            if entry["activation"].get("targetResponseCompleted")
        ]
        attempt_ids = {
            str(
                entry["activation"].get("activationAttemptId")
                or entry["sourceEventSequence"]
            )
            for entry in entries
        }
        request = self._latest_agent_exchange_request_by_id(
            workspace_id,
            exchange_request_id,
        )
        request_responded = (
            request is not None
            and request.terminal_reason is AgentExchangeRequestTerminalReason.RESPONDED
        )
        return {
            "codexRegisteredSessionActivationOccurred": bool(provider_started),
            "providerCommandStarted": bool(provider_started),
            "sessionContinuityVerified": bool(continuity_verified),
            "targetResponseCompleted": bool(target_completed) or request_responded,
            "runtimeWakeTriggered": bool(provider_started),
            "latestCodexRegisteredSessionActivation": (
                latest["activation"] if latest is not None else None
            ),
            "codexRegisteredSessionActivationCount": len(attempt_ids),
        }

    def _hermes_activation_summary(
        self,
        workspace_id: WorkspaceId,
        *,
        exchange_request_id: str,
    ) -> Mapping[str, object]:
        entries = [
            entry
            for entry in self._hermes_activation_attempt_entries(workspace_id)
            if entry["activation"]["exchangeRequestId"] == exchange_request_id
        ]
        latest = (
            max(entries, key=lambda item: int(item["sourceEventSequence"]))
            if entries
            else None
        )
        if not entries:
            return {
                "hermesRegisteredSessionActivationOccurred": False,
                "latestHermesRegisteredSessionActivation": None,
                "hermesRegisteredSessionActivationCount": 0,
            }
        provider_started = [
            entry
            for entry in entries
            if entry["activation"].get("providerCommandStarted")
        ]
        continuity_verified = [
            entry
            for entry in entries
            if entry["activation"].get("sessionContinuityVerified")
        ]
        target_completed = [
            entry
            for entry in entries
            if entry["activation"].get("targetResponseCompleted")
        ]
        request = self._latest_agent_exchange_request_by_id(
            workspace_id,
            exchange_request_id,
        )
        request_responded = (
            request is not None
            and request.terminal_reason is AgentExchangeRequestTerminalReason.RESPONDED
        )
        return {
            "hermesRegisteredSessionActivationOccurred": bool(provider_started),
            "providerCommandStarted": bool(provider_started),
            "sessionContinuityVerified": bool(continuity_verified),
            "targetResponseCompleted": bool(target_completed) or request_responded,
            "runtimeWakeTriggered": bool(provider_started),
            "latestHermesRegisteredSessionActivation": (
                latest["activation"] if latest is not None else None
            ),
            "hermesRegisteredSessionActivationCount": len(entries),
        }

    def _agent_wake_delivery_entries(
        self,
        workspace_id: WorkspaceId,
    ) -> list[Mapping[str, object]]:
        entries: list[Mapping[str, object]] = []
        for entry in self.event_log_reader.list_workspace_events(workspace_id):
            if (
                entry.record.event_kind
                is not PlatformEventKind.AGENT_WAKE_DELIVERY_RECORDED
            ):
                continue
            delivery_payload = entry.record.payload.get("delivery")
            ticket_payload = entry.record.payload.get("ticket")
            if not isinstance(delivery_payload, MappingABC) or not isinstance(
                ticket_payload,
                MappingABC,
            ):
                continue
            delivery = AgentWakeDeliveryRecord.from_mapping(
                {
                    **dict(delivery_payload),
                    "sourceEventSequence": entry.sequence,
                }
            ).to_metadata()
            ticket = AgentWakeTicket.from_mapping(dict(ticket_payload)).to_metadata()
            entries.append(
                {
                    "schema": "agent_wake_delivery_event.v1",
                    "sourceEventSequence": entry.sequence,
                    "occurredAt": entry.record.occurred_at.isoformat(),
                    "action": entry.record.payload.get("action"),
                    "delivery": delivery,
                    "ticket": ticket,
                    "realRuntimeConnected": False,
                    "providerPromptInjected": False,
                    "fileBodiesRead": False,
                    "credentialStored": False,
                }
            )
        return entries

    def _claude_activation_attempt_entries(
        self,
        workspace_id: WorkspaceId,
    ) -> list[Mapping[str, object]]:
        entries: list[Mapping[str, object]] = []
        for entry in self.event_log_reader.list_workspace_events(workspace_id):
            if (
                entry.record.event_kind
                is not PlatformEventKind.CLAUDE_REGISTERED_SESSION_ACTIVATION_RECORDED
            ):
                continue
            activation_payload = entry.record.payload.get("activation")
            ticket_payload = entry.record.payload.get("ticket")
            if not isinstance(activation_payload, MappingABC):
                continue
            activation = ClaudeRegisteredSessionActivationAttempt.from_mapping(
                {
                    **dict(activation_payload),
                    "sourceEventSequence": entry.sequence,
                }
            ).to_metadata()
            ticket = (
                AgentWakeTicket.from_mapping(dict(ticket_payload)).to_metadata()
                if isinstance(ticket_payload, MappingABC)
                else None
            )
            entries.append(
                {
                    "schema": "claude_registered_session_activation_event.v1",
                    "sourceEventSequence": entry.sequence,
                    "occurredAt": entry.record.occurred_at.isoformat(),
                    "action": entry.record.payload.get("action"),
                    "activation": activation,
                    "ticket": ticket,
                    "credentialStored": False,
                    "remoteControlEnabled": False,
                    "browserOrDesktopInputInjected": False,
                    "fullSessionHistoryRead": False,
                }
            )
        return entries

    def _codex_activation_attempt_entries(
        self,
        workspace_id: WorkspaceId,
    ) -> list[Mapping[str, object]]:
        entries: list[Mapping[str, object]] = []
        for entry in self.event_log_reader.list_workspace_events(workspace_id):
            if (
                entry.record.event_kind
                is not PlatformEventKind.CODEX_REGISTERED_SESSION_ACTIVATION_RECORDED
            ):
                continue
            activation_payload = entry.record.payload.get("activation")
            ticket_payload = entry.record.payload.get("ticket")
            if not isinstance(activation_payload, MappingABC):
                continue
            activation = CodexRegisteredSessionActivationAttempt.from_mapping(
                {
                    **dict(activation_payload),
                    "sourceEventSequence": entry.sequence,
                }
            ).to_metadata()
            ticket = (
                AgentWakeTicket.from_mapping(dict(ticket_payload)).to_metadata()
                if isinstance(ticket_payload, MappingABC)
                else None
            )
            entries.append(
                {
                    "schema": "codex_registered_session_activation_event.v1",
                    "sourceEventSequence": entry.sequence,
                    "occurredAt": entry.record.occurred_at.isoformat(),
                    "action": entry.record.payload.get("action"),
                    "activation": activation,
                    "ticket": ticket,
                    "credentialStored": False,
                    "remoteControlEnabled": False,
                    "browserOrDesktopInputInjected": False,
                    "fullSessionHistoryRead": False,
                }
            )
        return entries

    def _hermes_activation_attempt_entries(
        self,
        workspace_id: WorkspaceId,
    ) -> list[Mapping[str, object]]:
        entries: list[Mapping[str, object]] = []
        for entry in self.event_log_reader.list_workspace_events(workspace_id):
            if (
                entry.record.event_kind
                is not PlatformEventKind.HERMES_REGISTERED_SESSION_ACTIVATION_RECORDED
            ):
                continue
            activation_payload = entry.record.payload.get("activation")
            ticket_payload = entry.record.payload.get("ticket")
            if not isinstance(activation_payload, MappingABC):
                continue
            activation = HermesRegisteredSessionActivationAttempt.from_mapping(
                {
                    **dict(activation_payload),
                    "sourceEventSequence": entry.sequence,
                }
            ).to_metadata()
            ticket = (
                AgentWakeTicket.from_mapping(dict(ticket_payload)).to_metadata()
                if isinstance(ticket_payload, MappingABC)
                else None
            )
            entries.append(
                {
                    "schema": "hermes_registered_session_activation_event.v1",
                    "sourceEventSequence": entry.sequence,
                    "occurredAt": entry.record.occurred_at.isoformat(),
                    "action": entry.record.payload.get("action"),
                    "activation": activation,
                    "ticket": ticket,
                    "credentialStored": False,
                    "gatewayOrWebhookEnabled": False,
                    "desktopInputInjected": False,
                    "browserOrDesktopInputInjected": False,
                    "fullSessionHistoryRead": False,
                }
            )
        return entries

    def _latest_agent_wake_delivery_records(
        self,
        workspace_id: WorkspaceId,
    ) -> list[AgentWakeDeliveryRecord]:
        records: list[AgentWakeDeliveryRecord] = []
        for entry in self.event_log_reader.list_workspace_events(workspace_id):
            if (
                entry.record.event_kind
                is not PlatformEventKind.AGENT_WAKE_DELIVERY_RECORDED
            ):
                continue
            delivery_payload = entry.record.payload.get("delivery")
            if not isinstance(delivery_payload, MappingABC):
                continue
            records.append(
                AgentWakeDeliveryRecord.from_mapping(
                    {
                        **dict(delivery_payload),
                        "sourceEventSequence": entry.sequence,
                    }
                )
            )
        return records

    def _latest_claude_session_handle_by_id(
        self,
        workspace_id: WorkspaceId,
        handle_id: str,
    ) -> ClaudeRegisteredSessionHandle | None:
        return self._latest_claude_session_handles(workspace_id).get(handle_id)

    def _latest_claude_session_handles(
        self,
        workspace_id: WorkspaceId,
    ) -> dict[str, ClaudeRegisteredSessionHandle]:
        handles: dict[str, ClaudeRegisteredSessionHandle] = {}
        for entry in self.event_log_reader.list_workspace_events(workspace_id):
            if (
                entry.record.event_kind
                is not PlatformEventKind.CLAUDE_REGISTERED_SESSION_HANDLE_CHANGED
            ):
                continue
            handle_payload = entry.record.payload.get("handle")
            if not isinstance(handle_payload, MappingABC):
                continue
            handle = ClaudeRegisteredSessionHandle.from_mapping(
                {
                    **dict(handle_payload),
                    "sourceEventSequence": entry.sequence,
                }
            )
            handles[handle.handle_id] = handle
        return handles

    def _latest_claude_activation_for_request(
        self,
        workspace_id: WorkspaceId,
        *,
        handle_id: str,
        exchange_request_id: str,
    ) -> ClaudeRegisteredSessionActivationAttempt | None:
        attempts = [
            ClaudeRegisteredSessionActivationAttempt.from_mapping(
                entry["activation"]
            )
            for entry in self._claude_activation_attempt_entries(workspace_id)
            if entry["activation"]["handleId"] == handle_id
            and entry["activation"]["exchangeRequestId"] == exchange_request_id
        ]
        if not attempts:
            return None
        return max(
            attempts,
            key=lambda attempt: attempt.source_event_sequence or 0,
        )

    def _latest_codex_session_handle_by_id(
        self,
        workspace_id: WorkspaceId,
        handle_id: str,
    ) -> CodexRegisteredSessionHandle | None:
        return self._latest_codex_session_handles(workspace_id).get(handle_id)

    def _latest_codex_session_handles(
        self,
        workspace_id: WorkspaceId,
    ) -> dict[str, CodexRegisteredSessionHandle]:
        handles: dict[str, CodexRegisteredSessionHandle] = {}
        for entry in self.event_log_reader.list_workspace_events(workspace_id):
            if (
                entry.record.event_kind
                is not PlatformEventKind.CODEX_REGISTERED_SESSION_HANDLE_CHANGED
            ):
                continue
            handle_payload = entry.record.payload.get("handle")
            if not isinstance(handle_payload, MappingABC):
                continue
            handle = CodexRegisteredSessionHandle.from_mapping(
                {
                    **dict(handle_payload),
                    "sourceEventSequence": entry.sequence,
                }
            )
            handles[handle.handle_id] = handle
        return handles

    def _latest_codex_activation_for_request(
        self,
        workspace_id: WorkspaceId,
        *,
        handle_id: str,
        exchange_request_id: str,
    ) -> CodexRegisteredSessionActivationAttempt | None:
        attempts = [
            CodexRegisteredSessionActivationAttempt.from_mapping(
                entry["activation"]
            )
            for entry in self._codex_activation_attempt_entries(workspace_id)
            if entry["activation"]["handleId"] == handle_id
            and entry["activation"]["exchangeRequestId"] == exchange_request_id
            and entry["activation"].get("providerCommandStarted")
        ]
        if not attempts:
            return None
        return max(
            attempts,
            key=lambda attempt: attempt.source_event_sequence or 0,
        )

    def _latest_hermes_session_handle_by_id(
        self,
        workspace_id: WorkspaceId,
        handle_id: str,
    ) -> HermesRegisteredSessionHandle | None:
        return self._latest_hermes_session_handles(workspace_id).get(handle_id)

    def _latest_hermes_session_handles(
        self,
        workspace_id: WorkspaceId,
    ) -> dict[str, HermesRegisteredSessionHandle]:
        handles: dict[str, HermesRegisteredSessionHandle] = {}
        for entry in self.event_log_reader.list_workspace_events(workspace_id):
            if (
                entry.record.event_kind
                is not PlatformEventKind.HERMES_REGISTERED_SESSION_HANDLE_CHANGED
            ):
                continue
            handle_payload = entry.record.payload.get("handle")
            if not isinstance(handle_payload, MappingABC):
                continue
            handle = HermesRegisteredSessionHandle.from_mapping(
                {
                    **dict(handle_payload),
                    "sourceEventSequence": entry.sequence,
                }
            )
            handles[handle.handle_id] = handle
        return handles

    def _latest_hermes_activation_for_request(
        self,
        workspace_id: WorkspaceId,
        *,
        handle_id: str,
        exchange_request_id: str,
    ) -> HermesRegisteredSessionActivationAttempt | None:
        attempts = [
            HermesRegisteredSessionActivationAttempt.from_mapping(
                entry["activation"]
            )
            for entry in self._hermes_activation_attempt_entries(workspace_id)
            if entry["activation"]["handleId"] == handle_id
            and entry["activation"]["exchangeRequestId"] == exchange_request_id
        ]
        if not attempts:
            return None
        return max(
            attempts,
            key=lambda attempt: attempt.source_event_sequence or 0,
        )

    def _latest_agent_activation_by_id(
        self,
        workspace_id: WorkspaceId,
        activation_id: str,
    ) -> AgentActivationGrant | None:
        return self._latest_agent_activations(workspace_id).get(activation_id)

    def _latest_agent_activation_by_agent(
        self,
        workspace_id: WorkspaceId,
        agent_id: AgentId,
    ) -> AgentActivationGrant | None:
        candidates = [
            activation
            for activation in self._latest_agent_activations(workspace_id).values()
            if activation.agent_id == agent_id.value
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda activation: activation.source_event_sequence or 0,
        )

    def _latest_agent_activations(
        self,
        workspace_id: WorkspaceId,
    ) -> dict[str, AgentActivationGrant]:
        activations: dict[str, AgentActivationGrant] = {}
        for entry in self.event_log_reader.list_workspace_events(workspace_id):
            if entry.record.event_kind is not PlatformEventKind.AGENT_ACTIVATION_CHANGED:
                continue
            activation_payload = entry.record.payload.get("activation")
            if not isinstance(activation_payload, MappingABC):
                continue
            activation = AgentActivationGrant.from_mapping(
                {
                    **dict(activation_payload),
                    "sourceEventSequence": entry.sequence,
                }
            )
            activations[activation.activation_id] = activation
        return activations

    def _latest_delegated_wake_grant_by_id(
        self,
        workspace_id: WorkspaceId,
        delegated_wake_grant_id: str,
    ) -> DelegatedWakeGrant | None:
        return self._latest_delegated_wake_grants(workspace_id).get(
            delegated_wake_grant_id
        )

    def _latest_delegated_wake_grant_by_source_agent(
        self,
        workspace_id: WorkspaceId,
        source_agent_id: AgentId,
    ) -> DelegatedWakeGrant | None:
        candidates = [
            grant
            for grant in self._latest_delegated_wake_grants(workspace_id).values()
            if grant.source_agent_id == source_agent_id.value
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda grant: grant.source_event_sequence or 0,
        )

    def _latest_delegated_wake_grants(
        self,
        workspace_id: WorkspaceId,
    ) -> dict[str, DelegatedWakeGrant]:
        grants: dict[str, DelegatedWakeGrant] = {}
        for entry in self.event_log_reader.list_workspace_events(workspace_id):
            if (
                entry.record.event_kind
                is not PlatformEventKind.DELEGATED_WAKE_GRANT_CHANGED
            ):
                continue
            grant_payload = entry.record.payload.get("grant")
            if not isinstance(grant_payload, MappingABC):
                continue
            grant = DelegatedWakeGrant.from_mapping(
                {
                    **dict(grant_payload),
                    "sourceEventSequence": entry.sequence,
                }
            )
            grants[grant.delegated_wake_grant_id] = grant
        return grants

    def _latest_project_directory_coordination_by_id(
        self,
        workspace_id: WorkspaceId,
        directory_coordination_id: str,
    ) -> ProjectDirectoryCoordinationRecord | None:
        return self._latest_project_directory_coordination_records(workspace_id).get(
            directory_coordination_id
        )

    def _latest_project_directory_coordination_records(
        self,
        workspace_id: WorkspaceId,
    ) -> dict[str, ProjectDirectoryCoordinationRecord]:
        records: dict[str, ProjectDirectoryCoordinationRecord] = {}
        for entry in self.event_log_reader.list_workspace_events(workspace_id):
            if (
                entry.record.event_kind
                is not PlatformEventKind.PROJECT_DIRECTORY_COORDINATION_CHANGED
            ):
                continue
            coordination_payload = entry.record.payload.get("coordination")
            if not isinstance(coordination_payload, MappingABC):
                continue
            record = ProjectDirectoryCoordinationRecord.from_mapping(
                {
                    **dict(coordination_payload),
                    "sourceEventSequence": entry.sequence,
                }
            )
            records[record.directory_coordination_id] = record
        return records

    def _project_directory_record_with_current_overlap(
        self,
        workspace_id: WorkspaceId,
        record: ProjectDirectoryCoordinationRecord,
    ) -> ProjectDirectoryCoordinationRecord:
        status, overlapping_ids = calculate_project_directory_overlap(
            record,
            tuple(
                self._latest_project_directory_coordination_records(
                    workspace_id
                ).values()
            ),
        )
        return record.with_overlap(
            overlap_status=status,
            overlapping_coordination_ids=overlapping_ids,
        )

    def _workspace_overview(
        self,
        record: WorkspaceStateRecord,
    ) -> Mapping[str, object]:
        workspace_id = record.workspace.workspace_id
        return {
            "workspace": workspace_state_record_payload(record),
            "context": self.get_context(workspace_id)["context"],
            "agents": self.list_agent_registrations(workspace_id)["agents"],
            "tasks": self.list_tasks(workspace_id)["tasks"],
            "issues": self.list_issues(workspace_id)["issues"],
        }


def workspace_state_record_payload(
    record: WorkspaceStateRecord,
) -> Mapping[str, object]:
    workspace = record.workspace
    return {
        "workspaceId": workspace.workspace_id.value,
        "sourceEventSequence": record.source_event_sequence,
        "displayName": workspace.display_name,
        "rootPath": workspace.root_path,
        "status": workspace.status.value,
        "createdAt": _datetime_text(workspace.created_at),
        "updatedAt": _datetime_text(workspace.updated_at),
        "workspaceState": dict(record.workspace_state),
        "bindingState": dict(record.binding_state),
        "metadata": dict(record.metadata),
    }


def context_state_record_payload(
    record: ContextStateRecord,
) -> Mapping[str, object]:
    context = record.context
    return {
        "workspaceId": context.workspace_id.value,
        "contextId": context.context_id.value,
        "sourceEventSequence": record.source_event_sequence,
        "updateCount": record.update_count,
        "materializedState": dict(context.materialized_state),
        "createdAt": _datetime_text(context.created_at),
        "updatedAt": _datetime_text(context.updated_at),
        "metadata": dict(record.metadata),
    }


def context_update_payload(update: ContextUpdateInfo) -> Mapping[str, object]:
    return {
        "updateId": update.update_id.value,
        "workspaceId": update.workspace_id.value,
        "updateKind": update.update_kind.value,
        "summary": update.summary,
        "createdAt": _datetime_text(update.created_at),
        "sourceAgentId": (
            update.source_agent_id.value
            if update.source_agent_id is not None
            else None
        ),
        "payload": dict(update.payload),
        "materializedStatePatch": dict(update.materialized_state_patch),
        "metadata": dict(update.metadata),
    }


def context_update_event_payload(
    entry: PlatformEventLogEntry,
    *,
    append_index: int,
) -> Mapping[str, object]:
    payload = entry.record.payload
    update_payload = payload.get("payload")
    materialized_state_patch = payload.get("materialized_state_patch")
    update_metadata = payload.get("update_metadata")
    return {
        "appendIndex": append_index,
        "sourceEventSequence": entry.sequence,
        "eventId": entry.record.event_id.value,
        "updateId": str(payload.get("update_id") or entry.record.aggregate_id),
        "workspaceId": str(
            payload.get("workspace_id") or entry.record.workspace_id.value
        ),
        "updateKind": str(payload.get("update_kind") or ""),
        "summary": str(payload.get("summary") or ""),
        "createdAt": str(
            payload.get("created_at") or _datetime_text(entry.record.occurred_at)
        ),
        "sourceAgentId": payload.get("source_agent_id"),
        "payload": (
            dict(update_payload)
            if isinstance(update_payload, MappingABC)
            else {}
        ),
        "materializedStatePatch": (
            dict(materialized_state_patch)
            if isinstance(materialized_state_patch, MappingABC)
            else {}
        ),
        "metadata": (
            dict(update_metadata)
            if isinstance(update_metadata, MappingABC)
            else {}
        ),
    }


def conversation_session_record_payload(
    record: ConversationSessionRecord,
) -> Mapping[str, object]:
    payload = conversation_payload(record.conversation)
    return {
        **payload,
        "sourceEventSequence": record.source_event_sequence,
    }


def conversation_payload(conversation: ConversationSession) -> Mapping[str, object]:
    return {
        "conversationId": conversation.conversation_id.value,
        "workspaceId": conversation.workspace_id.value,
        "agentId": (
            conversation.agent_id.value
            if conversation.agent_id is not None
            else None
        ),
        "title": conversation.title,
        "status": conversation.status.value,
        "createdAt": _datetime_text(conversation.created_at),
        "updatedAt": _datetime_text(conversation.updated_at),
        "archivedAt": (
            _datetime_text(conversation.archived_at)
            if conversation.archived_at is not None
            else None
        ),
        "metadata": dict(conversation.metadata),
    }


def conversation_message_record_payload(
    record: ConversationMessageRecord,
) -> Mapping[str, object]:
    message = record.message
    return {
        "messageId": message.message_id.value,
        "conversationId": message.conversation_id.value,
        "workspaceId": message.workspace_id.value,
        "sourceEventSequence": record.source_event_sequence,
        "sequence": message.sequence,
        "role": message.role.value,
        "content": message.content,
        "agentId": (
            message.agent_id.value
            if message.agent_id is not None
            else None
        ),
        "invocationId": (
            message.invocation_id.value
            if message.invocation_id is not None
            else None
        ),
        "contextUpdateId": (
            message.context_update_id.value
            if message.context_update_id is not None
            else None
        ),
        "runSessionId": (
            message.run_session_id.value
            if message.run_session_id is not None
            else None
        ),
        "createdAt": _datetime_text(message.created_at),
        "metadata": dict(message.metadata),
    }


def session_timeline_payload(
    *,
    workspace_id: WorkspaceId,
    session_id: PlatformRunSessionId,
    entries: tuple[PlatformEventLogEntry, ...],
) -> Mapping[str, object]:
    first_entry = entries[0] if entries else None
    last_entry = entries[-1] if entries else None
    lifecycle = _session_lifecycle_payload(entries)
    return {
        "workspaceId": workspace_id.value,
        "sessionId": session_id.value,
        "status": _session_timeline_status(entries),
        "eventCount": len(entries),
        "firstSequence": (
            first_entry.sequence
            if first_entry is not None
            else None
        ),
        "lastSequence": (
            last_entry.sequence
            if last_entry is not None
            else None
        ),
        "firstOccurredAt": (
            _datetime_text(first_entry.record.occurred_at)
            if first_entry is not None
            else None
        ),
        "lastOccurredAt": (
            _datetime_text(last_entry.record.occurred_at)
            if last_entry is not None
            else None
        ),
        "lifecycle": lifecycle,
    }


def platform_event_log_entry_payload(
    entry: PlatformEventLogEntry,
) -> Mapping[str, object]:
    record = entry.record
    return {
        "sequence": entry.sequence,
        "eventId": record.event_id.value,
        "workspaceId": record.workspace_id.value,
        "sessionId": (
            record.session_id.value
            if record.session_id is not None
            else None
        ),
        "eventKind": record.event_kind.value,
        "aggregateType": record.aggregate_type,
        "aggregateId": record.aggregate_id,
        "occurredAt": _datetime_text(record.occurred_at),
        "correlationId": record.correlation_id,
        "idempotencyKey": record.idempotency_key,
        "payload": dict(record.payload),
        "metadata": dict(record.metadata),
    }


def agent_invocation_record_payload(
    record: AgentInvocationRecordEntry,
) -> Mapping[str, object]:
    return {
        "invocationId": record.invocation_id.value,
        "workspaceId": record.workspace_id.value,
        "agentId": record.agent_id.value,
        "taskId": (
            record.task_id.value
            if record.task_id is not None
            else None
        ),
        "sourceEventSequence": record.source_event_sequence,
        "status": record.status,
        "instruction": record.instruction,
        "requestedCapability": record.requested_capability,
        "idempotencyKey": record.idempotency_key,
        "correlationId": record.correlation_id,
        "requestState": dict(record.request_state),
        "resultState": dict(record.result_state),
        "contextUpdateIds": [
            update_id.value for update_id in record.context_update_ids
        ],
        "fileReferences": list(record.file_references),
        "metadata": dict(record.metadata),
        "requestedAt": _datetime_text(record.requested_at),
        "completedAt": (
            _datetime_text(record.completed_at)
            if record.completed_at is not None
            else None
        ),
        "createdAt": _datetime_text(record.created_at),
        "updatedAt": _datetime_text(record.updated_at),
    }


def file_operation_record_payload(
    record: FileOperationRecordEntry,
) -> Mapping[str, object]:
    return {
        "operationId": record.operation_id.value,
        "workspaceId": record.workspace_id.value,
        "sourceEventSequence": record.source_event_sequence,
        "operationKind": record.operation_kind,
        "relativePath": record.relative_path,
        "status": record.status,
        "requestedByAgentId": (
            record.requested_by_agent_id.value
            if record.requested_by_agent_id is not None
            else None
        ),
        "invocationId": (
            record.invocation_id.value
            if record.invocation_id is not None
            else None
        ),
        "taskId": (
            record.task_id.value
            if record.task_id is not None
            else None
        ),
        "contextUpdateId": (
            record.context_update_id.value
            if record.context_update_id is not None
            else None
        ),
        "requestState": _audit_safe_mapping(record.request_state),
        "resultState": _audit_safe_mapping(record.result_state),
        "outputPayload": _audit_safe_mapping(record.output_payload),
        "metadata": _audit_safe_mapping(record.metadata),
        "requestedAt": _datetime_text(record.requested_at),
        "completedAt": (
            _datetime_text(record.completed_at)
            if record.completed_at is not None
            else None
        ),
        "bytesRead": record.bytes_read,
        "bytesWritten": record.bytes_written,
        "errorMessage": record.error_message,
        "createdAt": _datetime_text(record.created_at),
        "updatedAt": _datetime_text(record.updated_at),
    }


def _audit_safe_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return {
        key: _audit_safe_json_value(item)
        for key, item in value.items()
        if key != "content"
    }


def _audit_safe_json_value(value: object) -> object:
    if isinstance(value, MappingABC):
        return _audit_safe_mapping(value)
    if isinstance(value, list):
        return [_audit_safe_json_value(item) for item in value]
    return value


def _session_timeline_status(
    entries: tuple[PlatformEventLogEntry, ...],
) -> str:
    for entry in reversed(entries):
        record = entry.record
        if record.event_kind is PlatformEventKind.RUN_SESSION_CHANGED:
            status = record.payload.get("status")
            if isinstance(status, str) and status.strip():
                return status
    if entries:
        return "observed"
    return "unknown"


def _session_lifecycle_payload(
    entries: tuple[PlatformEventLogEntry, ...],
) -> Mapping[str, object]:
    lifecycle_entries = tuple(
        entry
        for entry in entries
        if entry.record.event_kind is PlatformEventKind.RUN_SESSION_CHANGED
    )
    started_entry = lifecycle_entries[0] if lifecycle_entries else None
    terminal_entry = _last_terminal_session_entry(lifecycle_entries)
    return {
        "hasExplicitLifecycleEvents": bool(lifecycle_entries),
        "statusSource": (
            "run_session_event"
            if lifecycle_entries
            else ("observed_events" if entries else "none")
        ),
        "recoveryState": _session_recovery_state(entries, lifecycle_entries),
        "startedSequence": (
            started_entry.sequence
            if started_entry is not None
            else None
        ),
        "terminalSequence": (
            terminal_entry.sequence
            if terminal_entry is not None
            else None
        ),
        "startedAt": (
            _datetime_text(started_entry.record.occurred_at)
            if started_entry is not None
            else None
        ),
        "endedAt": (
            _datetime_text(terminal_entry.record.occurred_at)
            if terminal_entry is not None
            else None
        ),
        "invocationEventCount": _event_kind_count(
            entries,
            PlatformEventKind.AGENT_INVOCATION_RECORDED,
        ),
        "contextUpdateEventCount": _event_kind_count(
            entries,
            PlatformEventKind.CONTEXT_UPDATE_APPENDED,
        ),
        "fileOperationEventCount": _event_kind_count(
            entries,
            PlatformEventKind.FILE_OPERATION_RECORDED,
        ),
    }


def _last_terminal_session_entry(
    entries: tuple[PlatformEventLogEntry, ...],
) -> PlatformEventLogEntry | None:
    for entry in reversed(entries):
        status = entry.record.payload.get("status")
        if status in {"completed", "failed", "cancelled"}:
            return entry
    return None


def _session_recovery_state(
    entries: tuple[PlatformEventLogEntry, ...],
    lifecycle_entries: tuple[PlatformEventLogEntry, ...],
) -> str:
    if not entries:
        return "missing"
    if _last_terminal_session_entry(lifecycle_entries) is not None:
        return "closed"
    if lifecycle_entries:
        return "open"
    return "observed_without_lifecycle"


def _event_kind_count(
    entries: tuple[PlatformEventLogEntry, ...],
    event_kind: PlatformEventKind,
) -> int:
    return sum(1 for entry in entries if entry.record.event_kind is event_kind)


def agent_registration_state_record_payload(
    record: AgentRegistrationStateRecord,
) -> Mapping[str, object]:
    registration = record.registration
    return {
        "agentId": registration.agent_id.value,
        "workspaceId": registration.workspace_id.value,
        "sourceEventSequence": record.source_event_sequence,
        "name": registration.name,
        "description": registration.description,
        "status": registration.status.value,
        "defaultModel": registration.default_model,
        "capabilities": [
            agent_capability_payload(capability)
            for capability in registration.capabilities
        ],
        "toolPermissions": list(registration.tool_permissions),
        "runtimeConfig": dict(registration.runtime_config),
        "createdAt": _datetime_text(registration.created_at),
        "updatedAt": _datetime_text(registration.updated_at),
        "registrationState": dict(record.registration_state),
        "metadata": dict(record.metadata),
    }


def task_state_record_payload(record: TaskStateRecord) -> Mapping[str, object]:
    task = record.task
    return {
        "taskId": task.task_id.value,
        "workspaceId": task.workspace_id.value,
        "sourceEventSequence": record.source_event_sequence,
        "title": task.title,
        "status": task.status.value,
        "description": task.description,
        "assigneeAgentId": (
            task.assignee_agent_id.value
            if task.assignee_agent_id is not None
            else None
        ),
        "contextUpdateIds": [
            update_id.value for update_id in task.context_update_ids
        ],
        "linkedFilePaths": list(task.linked_file_paths),
        "createdAt": _datetime_text(task.created_at),
        "updatedAt": _datetime_text(task.updated_at),
        "taskState": dict(record.task_state),
        "metadata": dict(record.metadata),
    }


def issue_state_record_payload(record: IssueStateRecord) -> Mapping[str, object]:
    issue = record.issue
    return {
        "issueId": issue.issue_id.value,
        "workspaceId": issue.workspace_id.value,
        "sourceEventSequence": record.source_event_sequence,
        "title": issue.title,
        "status": issue.status.value,
        "severity": issue.severity.value,
        "description": issue.description,
        "linkedTaskId": (
            issue.linked_task_id.value
            if issue.linked_task_id is not None
            else None
        ),
        "contextUpdateIds": [
            update_id.value for update_id in issue.context_update_ids
        ],
        "linkedFilePaths": list(issue.linked_file_paths),
        "createdAt": _datetime_text(issue.created_at),
        "updatedAt": _datetime_text(issue.updated_at),
        "issueState": dict(record.issue_state),
        "metadata": dict(record.metadata),
    }


def agent_capability_payload(capability: AgentCapability) -> Mapping[str, object]:
    return {
        "name": capability.name,
        "description": capability.description,
        "metadata": dict(capability.metadata),
    }


def _agent_capabilities(
    capabilities: tuple[AgentCapability | Mapping[str, object], ...],
) -> tuple[AgentCapability, ...]:
    if not capabilities:
        return (
            AgentCapability(
                name="single-turn-status",
                description="Captures local single-turn requests.",
            ),
        )
    resolved: list[AgentCapability] = []
    for capability in capabilities:
        if isinstance(capability, AgentCapability):
            resolved.append(capability)
            continue
        if not isinstance(capability, MappingABC):
            raise ValueError("capabilities must contain objects.")
        name = capability.get("name")
        description = capability.get("description")
        metadata = capability.get("metadata", {})
        if not isinstance(name, str) or not name.strip():
            raise ValueError("capability name must be a non-empty string.")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("capability description must be a non-empty string.")
        if not isinstance(metadata, MappingABC):
            raise ValueError("capability metadata must be an object.")
        resolved.append(
            AgentCapability(
                name=name.strip(),
                description=description.strip(),
                metadata={
                    str(key): str(value)
                    for key, value in metadata.items()
                },
            )
        )
    return tuple(resolved)


def _command_line_preview(argv: list[str]) -> str:
    return " ".join(_quote_arg(item) for item in argv)


def _resolve_platform_workspace_root(
    *,
    explicit_root: str | None,
    database_path: str,
    plugins_directory: str,
    ticket_path: str,
    workspace_root: str,
) -> str:
    if explicit_root is not None:
        root = Path(_non_empty_text(explicit_root, "platformWorkspaceRoot"))
    else:
        platform_paths = [
            Path(database_path).parent,
            Path(plugins_directory),
            Path(ticket_path).parent,
        ]
        try:
            root = Path(
                os.path.commonpath(
                    [str(path.resolve(strict=False)) for path in platform_paths]
                )
            )
        except ValueError:
            root = Path(workspace_root)
    if not root.is_absolute():
        raise ValueError("platformWorkspaceRoot must be an absolute path.")
    return str(root)


def _codex_output_last_message_path(
    *,
    platform_workspace_root: str,
    exchange_request_id: str,
    activation_attempt_id: str,
) -> str:
    return str(
        Path(platform_workspace_root)
        / "codex-output"
        / (
            f"req-{_short_stable_id(exchange_request_id)}."
            f"attempt-{_short_stable_id(activation_attempt_id)}.last-message.txt"
        )
    )


def _run_codex_executable_preflight(
    executable: str,
    *,
    timeout_seconds: int,
) -> Mapping[str, object]:
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            shell=False,
            timeout=max(1, timeout_seconds),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        failure_category = classify_codex_activation_failure(exc)
        return {
            "status": "failed",
            "failureReason": f"{exc.__class__.__name__}: {exc}",
            "failureCategory": failure_category,
        }
    failure_category = None if completed.returncode == 0 else "command_exit_nonzero"
    return {
        "status": "passed" if completed.returncode == 0 else "failed",
        "exitCode": completed.returncode,
        "stdoutTail": summarize_codex_process_text(completed.stdout, max_chars=500),
        "stderrTail": summarize_codex_process_text(completed.stderr, max_chars=500),
        "failureReason": None if completed.returncode == 0 else "preflight_exit_nonzero",
        "failureCategory": failure_category,
    }


def _run_hermes_executable_preflight(
    executable: str,
    *,
    timeout_seconds: int,
    environment: Mapping[str, str] | None = None,
) -> Mapping[str, object]:
    try:
        completed = subprocess.run(
            [executable, "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            shell=False,
            timeout=max(1, timeout_seconds),
            env=dict(environment) if environment is not None else None,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        failure_category = classify_hermes_activation_failure(exc)
        return {
            "status": "failed",
            "failureReason": f"{exc.__class__.__name__}: {exc}",
            "failureCategory": failure_category,
        }
    failure_category = None if completed.returncode == 0 else "command_exit_nonzero"
    return {
        "status": "passed" if completed.returncode == 0 else "failed",
        "exitCode": completed.returncode,
        "stdoutTail": summarize_hermes_process_text(completed.stdout, max_chars=500),
        "stderrTail": summarize_hermes_process_text(completed.stderr, max_chars=500),
        "failureReason": None if completed.returncode == 0 else "preflight_exit_nonzero",
        "failureCategory": failure_category,
    }


def _hermes_session_identity_from_handle(
    metadata: Mapping[str, object],
) -> Mapping[str, object]:
    identity = metadata.get("hermesSessionIdentity")
    if not isinstance(identity, MappingABC):
        return {}
    return dict(identity)


def _resolve_hermes_activation_home(
    *,
    explicit_home: str | None,
    stored_identity: Mapping[str, object],
) -> tuple[str | None, str]:
    explicit = explicit_home.strip() if explicit_home and explicit_home.strip() else None
    stored_value = stored_identity.get("runtimeHome")
    stored = (
        stored_value.strip()
        if isinstance(stored_value, str) and stored_value.strip()
        else None
    )
    if explicit is not None:
        resolved = str(Path(explicit).expanduser().resolve(strict=False))
        if stored is not None:
            resolved_stored = str(Path(stored).expanduser().resolve(strict=False))
            if os.path.normcase(resolved) != os.path.normcase(resolved_stored):
                raise ValueError(
                    "hermesHome does not match the runtime home stored with the "
                    "registered Hermes session."
                )
        return resolved, "explicit"
    if stored is not None:
        return (
            str(Path(stored).expanduser().resolve(strict=False)),
            "registered_session_identity",
        )
    environment_home = os.environ.get("HERMES_HOME")
    if environment_home and environment_home.strip():
        return (
            str(Path(environment_home).expanduser().resolve(strict=False)),
            "process_environment",
        )
    return None, "provider_default_unknown"


def _read_optional_text_file(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _subprocess_timeout_text(value: str | bytes | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _normalize_agent_dispatch_provider(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip().lower().replace("_", "-")
    if normalized in {"claude", "claude-cli", "claude-code"}:
        return "claude"
    if normalized in {"codex", "codex-cli"}:
        return "codex"
    if normalized in {"hermes", "hermes-cli", "hermes-desktop"}:
        return "hermes"
    return None


def _agent_endpoint_status_counts(
    records: Sequence[AgentDispatchRecord],
) -> Mapping[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        status = _agent_dispatch_status_value(record.status)
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _agent_endpoint_pending_count(records: Sequence[AgentDispatchRecord]) -> int:
    pending_statuses = {
        AgentDispatchStatus.QUEUED.value,
        AgentDispatchStatus.LEASED.value,
        AgentDispatchStatus.WAITING_RESPONSE.value,
        AgentDispatchStatus.RETRY_SCHEDULED.value,
    }
    return sum(
        1
        for record in records
        if _agent_dispatch_status_value(record.status) in pending_statuses
    )


def _agent_dispatch_waiting_response_status(
    dispatch: AgentDispatchRecord | None,
    *,
    request: AgentExchangeRequest | None,
    checked_at: datetime,
    stale_threshold_seconds: int,
) -> Mapping[str, object]:
    if stale_threshold_seconds <= 0:
        raise ValueError(
            "waitingResponseStaleThresholdSeconds must be greater than zero."
        )
    waiting = (
        dispatch is not None
        and AgentDispatchStatus(dispatch.status) is AgentDispatchStatus.WAITING_RESPONSE
    )
    target_response_completed = bool(
        request is not None
        and request.status is AgentExchangeRequestStatus.TERMINAL
        and request.terminal_reason is AgentExchangeRequestTerminalReason.RESPONDED
    )
    age_seconds = (
        max(0, int((checked_at - dispatch.updated_at).total_seconds()))
        if waiting and dispatch is not None
        else None
    )
    stale = bool(
        waiting
        and not target_response_completed
        and age_seconds is not None
        and age_seconds >= stale_threshold_seconds
    )
    recommended_action = (
        "manual_review"
        if stale or (waiting and target_response_completed)
        else "continue_waiting" if waiting else None
    )
    reason_code = (
        "waiting_response_stale"
        if stale
        else "target_response_completed_dispatch_pending_reconcile"
        if waiting and target_response_completed
        else "waiting_response"
        if waiting
        else "not_waiting_response"
    )
    return {
        "schema": "agent_dispatch_waiting_response_status.v1",
        "waitingResponse": waiting,
        "waitingResponseSince": (
            dispatch.updated_at.isoformat() if waiting and dispatch is not None else None
        ),
        "waitingResponseAgeSeconds": age_seconds,
        "waitingResponseStale": stale,
        "staleThresholdSeconds": stale_threshold_seconds,
        "targetResponseCompleted": target_response_completed,
        "reasonCode": reason_code,
        "recommendedAction": recommended_action,
        "manualActions": [
            {
                "action": "close_as_expired",
                "automatic": False,
                "destructive": True,
            },
            {
                "action": "create_retry_dispatch",
                "automatic": False,
                "duplicateExecutionRisk": True,
            },
        ],
        "automaticRetryScheduled": False,
        "providerActivationTriggered": False,
    }


def _agent_dispatch_busy_backoff_status(
    dispatch: AgentDispatchRecord | None,
    *,
    checked_at: datetime,
) -> Mapping[str, object]:
    next_attempt_after = dispatch.next_attempt_after if dispatch is not None else None
    retry_delay = dispatch.busy_retry_delay_seconds if dispatch is not None else None
    active = bool(
        next_attempt_after is not None
        and retry_delay is not None
        and next_attempt_after > checked_at
    )
    return {
        "schema": "agent_dispatch_busy_backoff_status.v1",
        "busySkipCount": dispatch.busy_skip_count if dispatch is not None else 0,
        "lastBusySkipAt": (
            dispatch.last_busy_skip_at.isoformat()
            if dispatch is not None and dispatch.last_busy_skip_at is not None
            else None
        ),
        "busyRetryDelaySeconds": retry_delay,
        "nextAttemptAfter": (
            next_attempt_after.isoformat() if next_attempt_after is not None else None
        ),
        "active": active,
        "due": bool(
            next_attempt_after is not None
            and retry_delay is not None
            and next_attempt_after <= checked_at
        ),
        "maximumDelaySeconds": 60,
        "historyRetainedAfterRecovery": True,
    }


def _agent_exchange_timeline_with_waiting_warning(
    timeline: Mapping[str, object],
    *,
    waiting_response_status: Mapping[str, object],
    checked_at: datetime,
) -> Mapping[str, object]:
    if not waiting_response_status.get("waitingResponseStale"):
        return timeline
    events = timeline.get("events")
    copied_events = list(events) if isinstance(events, Sequence) else []
    copied_events.append(
        {
            "schema": "agent_exchange_status_timeline_event.v1",
            "stage": "waiting_response_stale",
            "action": "warning",
            "status": "stale",
            "occurredAt": checked_at.isoformat(),
            "reasonCode": "waiting_response_stale",
            "recommendedAction": waiting_response_status.get(
                "recommendedAction"
            ),
            "derived": True,
            "providerActivationTriggered": False,
        }
    )
    return {
        **dict(timeline),
        "events": copied_events,
        "eventCount": len(copied_events),
    }


def _agent_exchange_request_api_layer() -> Mapping[str, object]:
    return {
        "schema": "agent_exchange_request_api_layer.v1",
        "apiLayer": "state-only",
        "deliveryOrWakeAttempted": False,
        "dispatchQueueEntryCreated": False,
        "daemonOrWorkerStarted": False,
        "meaning": (
            "agent-exchange-request-create records request and thread state only. "
            "It does not deliver to a provider runtime, wake a target, or start a "
            "dispatcher."
        ),
    }


def _agent_dispatch_api_layer() -> Mapping[str, object]:
    return {
        "schema": "agent_dispatch_api_layer.v1",
        "apiLayer": "delivery-oriented",
        "createsExchangeRequestState": True,
        "dispatchQueueEntryCreated": True,
        "lowLevelRequestApiPreserved": True,
        "meaning": (
            "agent-dispatch-create/send builds on exchange-request state and adds "
            "a dispatch queue entry that can be handled by a worker or daemon."
        ),
    }


def _agent_endpoint_semantics(
    endpoint: AgentEndpointRecord,
    provider_handle: Mapping[str, object] | None,
    *,
    provider_runtime_status: Mapping[str, object] | None = None,
    read_live_runtime_status: bool | str,
) -> Mapping[str, object]:
    runtime_status_policy = normalize_provider_runtime_status_read_policy(
        read_live_runtime_status
    )
    provider_handle_active = (
        isinstance(provider_handle, MappingABC)
        and provider_handle.get("state") == "active"
    )
    runtime_status_read = (
        isinstance(provider_runtime_status, MappingABC)
        and bool(provider_runtime_status.get("providerRuntimeStatusRead"))
    )
    return {
        "schema": "agent_endpoint_semantics.v1",
        "endpointAlias": endpoint.alias,
        "endpointId": endpoint.endpoint_id,
        "agentId": endpoint.agent_id,
        "provider": endpoint.provider,
        "providerHandleId": endpoint.provider_handle_id,
        "endpointState": _enum_or_text(endpoint.state),
        "direction": _enum_or_text(endpoint.direction),
        "defaultReplyPolicy": _enum_or_text(endpoint.default_reply_policy),
        "contactPolicy": _enum_or_text(endpoint.contact_policy),
        "providerHandleActive": provider_handle_active,
        "providerSessionHandleBound": provider_handle is not None,
        "credentialStored": False,
        "providerAccountAuthenticated": False,
        "endpointLoginMeaning": (
            "Endpoint login binds a platform endpoint alias to an already "
            "registered provider session handle. It is not a provider account "
            "authentication flow."
        ),
        "handleBoundary": (
            "The provider handle identifies a resumable provider session. The "
            "endpoint alias is Beacon-local addressing metadata used for dispatch."
        ),
        "credentialBoundary": (
            "Beacon does not store provider credentials, cookies, tokens, or auth "
            "headers in endpoint login/status payloads."
        ),
        "runtimeProbe": {
            "runtimeStatusPolicy": runtime_status_policy,
            "readLiveRuntimeStatusRequested": runtime_status_policy == "enabled",
            "providerRuntimeStatusRead": runtime_status_read,
            "probeRunsOnlyWhenRequested": runtime_status_policy != "auto",
            "probeRunsOnlyWhenConfigured": True,
            "autoReadsConfiguredSafeProbe": runtime_status_policy == "auto",
            "runtimePresenceNotInferredFromLogin": True,
        },
    }


def _agent_endpoint_reply_reachability(
    endpoint: AgentEndpointRecord,
    provider_handle: Mapping[str, object] | None,
    provider_runtime_status: Mapping[str, object] | None,
) -> Mapping[str, object]:
    direction = _enum_or_text(endpoint.direction)
    state = _enum_or_text(endpoint.state)
    provider_handle_active = (
        isinstance(provider_handle, MappingABC)
        and provider_handle.get("state") == "active"
    )
    runtime_status_read = (
        isinstance(provider_runtime_status, MappingABC)
        and bool(provider_runtime_status.get("providerRuntimeStatusRead"))
    )
    endpoint_active = state == "active"
    can_send = (
        endpoint_active
        and provider_handle_active
        and direction in {"send_only", "send_receive"}
    )
    can_receive = (
        endpoint_active
        and provider_handle_active
        and direction in {"receive_only", "send_receive"}
    )
    return {
        "schema": "agent_endpoint_reply_reachability.v1",
        "endpointActive": endpoint_active,
        "providerHandleActive": provider_handle_active,
        "direction": direction,
        "canSend": can_send,
        "canReceive": can_receive,
        "replyAddressable": can_send,
        "defaultReplyPolicy": _enum_or_text(endpoint.default_reply_policy),
        "contactPolicy": _enum_or_text(endpoint.contact_policy),
        "providerRuntimeStatusRead": runtime_status_read,
        "realRuntimePresenceRead": runtime_status_read,
    }


def _agent_endpoint_respond_permission_profile(
    endpoint: AgentEndpointRecord,
    provider_handle: Mapping[str, object] | None,
    provider_runtime_status: Mapping[str, object] | None,
) -> Mapping[str, object]:
    direction = _enum_or_text(endpoint.direction)
    endpoint_active = _enum_or_text(endpoint.state) == "active"
    provider_handle_active = (
        isinstance(provider_handle, MappingABC)
        and provider_handle.get("state") == "active"
    )
    metadata = _merged_endpoint_handle_metadata(endpoint.to_metadata(), provider_handle)
    declared = _first_mapping(
        metadata,
        "respondPermissionProfile",
        "permissionProfile",
        "respondProfile",
    )
    platform_cli_respond_allowed = _optional_bool_from_mapping(
        declared,
        "platformCliRespondAllowed",
        "platformRespondAllowed",
        "respondCommandAllowed",
    )
    settings_path = _optional_text_from_mapping(
        declared,
        "settingsPath",
        "claudeSettingsPath",
        "userAuthorizedSettingsPath",
    )
    provider = endpoint.provider
    manual_approval_may_be_required = (
        provider == "claude"
        and platform_cli_respond_allowed is not True
        and settings_path is None
    )
    return {
        "schema": "agent_endpoint_respond_permission_profile.v1",
        "endpointAlias": endpoint.alias,
        "provider": provider,
        "endpointActive": endpoint_active,
        "providerHandleActive": provider_handle_active,
        "direction": direction,
        "canReadIncomingRequests": (
            endpoint_active
            and provider_handle_active
            and direction in {"receive_only", "send_receive"}
        ),
        "canWritePlatformResponse": endpoint_active and provider_handle_active,
        "canAddressRepliesByEndpointAlias": (
            endpoint_active
            and provider_handle_active
            and direction in {"send_only", "send_receive"}
        ),
        "defaultReplyPolicy": _enum_or_text(endpoint.default_reply_policy),
        "contactPolicy": _enum_or_text(endpoint.contact_policy),
        "platformCliRespondAllowedDeclared": platform_cli_respond_allowed is True,
        "manualApprovalMayBeRequired": manual_approval_may_be_required,
        "settingsPathDeclared": settings_path is not None,
        "settingsPath": settings_path,
        "responseCaptureFallbackAvailable": provider in {"claude", "codex", "hermes"},
        "providerRuntimeStatusRead": (
            isinstance(provider_runtime_status, MappingABC)
            and bool(provider_runtime_status.get("providerRuntimeStatusRead"))
        ),
        "generatesOrInstallsSettings": False,
    }


def _agent_provider_runtime_status_probe(
    *,
    provider: str,
    provider_handle: Mapping[str, object] | None,
    endpoint: Mapping[str, object] | None,
    checked_at: datetime,
    read_live_runtime_status: bool | str,
) -> Mapping[str, object]:
    runtime_status_policy = normalize_provider_runtime_status_read_policy(
        read_live_runtime_status
    )
    config, source = _agent_provider_runtime_status_probe_config(
        provider_handle,
        endpoint,
    )
    base = {
        "schema": "agent_provider_runtime_status_probe.v1",
        "provider": provider,
        "configured": config is not None,
        "configSource": source,
        "checkedAt": checked_at.isoformat(),
        "runtimeStatus": None,
        "runtimeStatusPolicy": runtime_status_policy,
        "readLiveRuntimeStatusRequested": runtime_status_policy == "enabled",
    }
    if config is None:
        return {**base, "status": "not_configured"}
    if runtime_status_policy == "disabled":
        return {
            **base,
            "status": "disabled",
            "reason": "live runtime status read is disabled by policy.",
        }
    try:
        probe = _normalize_runtime_status_probe_config(
            config,
            provider_handle=provider_handle,
        )
    except ValueError as exc:
        return {
            **base,
            "status": "invalid_config",
            "failureReason": str(exc),
        }
    argv = probe["argv"]
    cwd = probe.get("cwd")
    timeout_seconds = int(probe["timeoutSeconds"])
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            shell=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            **base,
            "status": "timeout",
            "commandArgvSummary": _probe_argv_summary(argv),
            "cwd": cwd,
            "timeoutSeconds": timeout_seconds,
            "failureReason": f"TimeoutExpired: {exc}",
        }
    except OSError as exc:
        return {
            **base,
            "status": "failed",
            "commandArgvSummary": _probe_argv_summary(argv),
            "cwd": cwd,
            "timeoutSeconds": timeout_seconds,
            "failureReason": f"{exc.__class__.__name__}: {exc}",
        }
    common = {
        **base,
        "commandArgvSummary": _probe_argv_summary(argv),
        "cwd": cwd,
        "timeoutSeconds": timeout_seconds,
        "exitCode": completed.returncode,
        "stdoutTail": _summarize_probe_text(completed.stdout),
        "stderrTail": _summarize_probe_text(completed.stderr),
    }
    if completed.returncode != 0:
        return {
            **common,
            "status": "exit_nonzero",
            "failureReason": "runtime status probe command exited non-zero.",
        }
    try:
        payload = _parse_runtime_status_probe_json(completed.stdout)
    except ValueError as exc:
        return {
            **common,
            "status": "invalid_json",
            "failureReason": str(exc),
        }
    snapshot = _runtime_status_probe_snapshot(
        payload,
        state_path=probe.get("statePath"),
    )
    if snapshot is None:
        return {
            **common,
            "status": "state_missing",
            "failureReason": "runtime status probe JSON did not include a state.",
        }
    return {
        **common,
        "status": "read",
        "runtimeStatus": snapshot,
    }


def _agent_provider_runtime_status_probe_config(
    provider_handle: Mapping[str, object] | None,
    endpoint: Mapping[str, object] | None,
) -> tuple[Mapping[str, object] | None, str]:
    endpoint_metadata = _nested_metadata(endpoint)
    endpoint_config = _first_mapping(
        endpoint_metadata,
        "providerRuntimeStatusProbe",
        "runtimeStatusProbe",
        "statusProbe",
    )
    if endpoint_config is not None:
        return endpoint_config, "endpoint_metadata"
    handle_metadata = _nested_metadata(provider_handle)
    handle_config = _first_mapping(
        handle_metadata,
        "providerRuntimeStatusProbe",
        "runtimeStatusProbe",
        "statusProbe",
    )
    if handle_config is not None:
        return handle_config, "provider_handle_metadata"
    return None, "not_configured"


def _normalize_runtime_status_probe_config(
    config: Mapping[str, object],
    *,
    provider_handle: Mapping[str, object] | None,
) -> Mapping[str, object]:
    enabled = config.get("enabled")
    if enabled is False:
        raise ValueError("runtime status probe is disabled.")
    mode = _optional_text_from_mapping(config, "mode") or "local_command_json"
    if mode != "local_command_json":
        raise ValueError("runtime status probe mode must be local_command_json.")
    argv_value = config.get("argv")
    if not isinstance(argv_value, Sequence) or isinstance(argv_value, (str, bytes)):
        raise ValueError("runtime status probe argv must be a JSON array of strings.")
    if not argv_value:
        raise ValueError("runtime status probe argv must not be empty.")
    if len(argv_value) > 64:
        raise ValueError("runtime status probe argv must contain at most 64 items.")
    argv = tuple(
        _expand_runtime_status_probe_arg(str(item), provider_handle)
        if isinstance(item, str)
        else _raise_probe_value_error("runtime status probe argv items must be strings.")
        for item in argv_value
    )
    for item in argv:
        _validate_probe_text(item, "runtime status probe argv item")
    cwd = _optional_text_from_mapping(config, "cwd")
    if cwd is None and isinstance(provider_handle, MappingABC):
        cwd = _optional_text_from_mapping(provider_handle, "cwd")
    if cwd is not None and not Path(cwd).is_dir():
        raise ValueError("runtime status probe cwd must be an existing directory.")
    timeout_value = config.get("timeoutSeconds", 5)
    if not isinstance(timeout_value, int) or isinstance(timeout_value, bool):
        raise ValueError("runtime status probe timeoutSeconds must be an integer.")
    if timeout_value <= 0 or timeout_value > 30:
        raise ValueError("runtime status probe timeoutSeconds must be between 1 and 30.")
    state_path = _optional_text_from_mapping(
        config,
        "statePath",
        "stateJsonPath",
        "runtimeStatePath",
    )
    return {
        "argv": argv,
        "cwd": cwd,
        "timeoutSeconds": timeout_value,
        "statePath": state_path,
    }


def _runtime_status_probe_snapshot(
    payload: Mapping[str, object],
    *,
    state_path: str | None,
) -> Mapping[str, object] | None:
    snapshot = dict(payload)
    if state_path is not None:
        state_value = _mapping_path_value(payload, state_path)
        if state_value is not None:
            snapshot["state"] = str(state_value)
    for key in (
        "canonicalState",
        "runtimeState",
        "providerRuntimeState",
        "state",
        "status",
        "threadStatus",
        "codexThreadStatus",
        "appServerThreadStatus",
        "runStatus",
        "hermesRunStatus",
        "streamStatus",
        "sdkSessionStatus",
        "claudeStreamStatus",
    ):
        if _optional_text_from_mapping(snapshot, key) is not None:
            snapshot.setdefault("source", "local_command_probe")
            return snapshot
    return None


def _parse_runtime_status_probe_json(value: str) -> Mapping[str, object]:
    stripped = value.strip()
    if not stripped:
        raise ValueError("runtime status probe stdout was empty.")
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None
        for line in stripped.splitlines():
            candidate = line.strip()
            if not candidate.startswith("{"):
                continue
            try:
                parsed = json.loads(candidate)
                break
            except json.JSONDecodeError:
                continue
        if parsed is None:
            raise ValueError("runtime status probe stdout was not a JSON object.")
    if not isinstance(parsed, MappingABC):
        raise ValueError("runtime status probe stdout must be a JSON object.")
    return dict(parsed)


def _expand_runtime_status_probe_arg(
    value: str,
    provider_handle: Mapping[str, object] | None,
) -> str:
    if not isinstance(provider_handle, MappingABC):
        return value
    replacements = {
        "providerHandleId": provider_handle.get("handleId"),
        "agentId": provider_handle.get("agentId"),
        "cwd": provider_handle.get("cwd"),
        "claudeSessionUuid": provider_handle.get("claudeSessionUuid"),
        "codexSessionId": provider_handle.get("codexSessionId"),
        "hermesSessionId": provider_handle.get("hermesSessionId"),
    }
    expanded = value
    for key, replacement in replacements.items():
        if replacement is not None:
            expanded = expanded.replace("{" + key + "}", str(replacement))
    return expanded


def _probe_argv_summary(argv: Sequence[str]) -> tuple[str, ...]:
    return tuple(_summarize_probe_text(item, max_chars=180) for item in argv)


def _summarize_probe_text(value: str | None, *, max_chars: int = 800) -> str:
    if value is None:
        return ""
    text = value.strip()
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _validate_probe_text(value: str, logical_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{logical_name} must not be empty.")
    if "\x00" in value:
        raise ValueError(f"{logical_name} must not contain null bytes.")
    if _PROBE_SENSITIVE_TEXT_PATTERN.search(value):
        raise ValueError(f"{logical_name} must not contain credential values.")


def _raise_probe_value_error(message: str) -> None:
    raise ValueError(message)


def _merged_endpoint_handle_metadata(
    endpoint: Mapping[str, object] | None,
    provider_handle: Mapping[str, object] | None,
) -> Mapping[str, object]:
    return {
        **dict(_nested_metadata(provider_handle)),
        **dict(_nested_metadata(endpoint)),
    }


def _nested_metadata(source: Mapping[str, object] | None) -> Mapping[str, object]:
    if not isinstance(source, MappingABC):
        return {}
    metadata = source.get("metadata")
    if isinstance(metadata, MappingABC):
        return dict(metadata)
    return {}


def _first_mapping(
    source: Mapping[str, object],
    *keys: str,
) -> Mapping[str, object] | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, MappingABC):
            return dict(value)
    return None


def _optional_text_from_mapping(
    source: Mapping[str, object] | None,
    *keys: str,
) -> str | None:
    if not isinstance(source, MappingABC):
        return None
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _optional_bool_from_mapping(
    source: Mapping[str, object] | None,
    *keys: str,
) -> bool | None:
    if not isinstance(source, MappingABC):
        return None
    for key in keys:
        value = source.get(key)
        if isinstance(value, bool):
            return value
    return None


def _mapping_path_value(source: Mapping[str, object], path: str) -> object | None:
    current: object = source
    for part in path.split("."):
        if not isinstance(current, MappingABC):
            return None
        current = current.get(part)
    return current


def _unavailable_agent_provider_runtime_status(
    *,
    provider: str | None,
    provider_handle_id: str | None,
    reason: str,
) -> Mapping[str, object]:
    timestamp = _utc_now()
    return {
        "schema": "agent_provider_runtime_status.v1",
        "provider": provider,
        "providerHandleId": provider_handle_id,
        "agentId": None,
        "endpointId": None,
        "endpointAlias": None,
        "runtimeState": "unavailable",
        "stateSource": "dispatch_target_unavailable",
        "reason": reason,
        "providerRuntimeState": "unknown",
        "providerRuntimeStateSource": "provider_runtime_status_not_configured",
        "providerRuntimeStateSupported": False,
        "providerRuntimeStatusRead": False,
        "providerRuntimeStatusReadMode": "not_configured",
        "runtimeStatusPolicy": "auto",
        "rawProviderRuntimeState": None,
        "providerStatusAdapter": {
            "schema": "agent_provider_runtime_status_adapter.v1",
            "provider": provider,
            "adapterKind": "provider_runtime_status",
            "directProviderRuntimeReadConfigured": False,
            "directProviderRuntimeRead": False,
            "directProviderRuntimeReadStatus": None,
            "metadataSnapshotSupported": False,
            "metadataSnapshotRead": False,
        },
        "providerRuntimeStatusProbe": {
            "schema": "agent_provider_runtime_status_probe.v1",
            "configured": False,
            "status": "not_configured",
            "runtimeStatusPolicy": "auto",
        },
        "providerHandleFound": False,
        "providerHandleActive": False,
        "platformDispatchBusy": False,
        "activeDispatchLease": {},
        "realRuntimePresenceRead": False,
        "checkedAt": timestamp.isoformat(),
    }


def _agent_response_source_status(
    request: AgentExchangeRequest | Mapping[str, object] | None,
) -> Mapping[str, object]:
    if request is None:
        return {
            "schema": "agent_response_source_status.v1",
            "responded": False,
            "responseSource": None,
            "rawResponseSource": None,
            "standardResponded": False,
            "stdoutFallbackCaptured": False,
            "captureMode": None,
            "stdoutFallbackMeaning": STDOUT_FALLBACK_MEANING,
            "standardRespondMeaning": STANDARD_RESPOND_MEANING,
            "privateReasoningRead": False,
            "fullTranscriptRead": False,
        }
    if isinstance(request, AgentExchangeRequest):
        metadata = dict(request.metadata)
        terminal_reason = request.terminal_reason.value if request.terminal_reason else None
    else:
        metadata = _nested_metadata(request)
        terminal_reason = (
            request.get("terminalReason")
            or request.get("terminal_reason")
        )
    raw_source = _optional_text_from_mapping(
        metadata,
        "standardResponseSource",
        "responseSource",
        "response_source",
    )
    responded = terminal_reason == AgentExchangeRequestTerminalReason.RESPONDED.value
    stdout_captured = _response_source_is_stdout_capture(raw_source)
    standard_responded = responded and not stdout_captured
    response_source = (
        "stdout_auto_capture"
        if stdout_captured
        else ("standard_respond" if standard_responded else None)
    )
    return {
        "schema": "agent_response_source_status.v1",
        "responded": responded,
        "responseSource": response_source,
        "rawResponseSource": raw_source,
        "standardResponded": standard_responded,
        "stdoutFallbackCaptured": stdout_captured,
        "captureMode": _optional_text_from_mapping(
            metadata,
            "captureMode",
            "responseCaptureMode",
        ),
        "stdoutFallbackMeaning": STDOUT_FALLBACK_MEANING,
        "standardRespondMeaning": STANDARD_RESPOND_MEANING,
        "privateReasoningRead": False,
        "fullTranscriptRead": False,
    }


def _agent_response_source_status_from_activation(
    activation: Mapping[str, object],
) -> Mapping[str, object]:
    response_capture_status = _optional_text_from_mapping(
        activation,
        "responseCaptureStatus",
    )
    captured = response_capture_status in {
        "recorded",
        "recorded_after_command_timeout",
        "recorded_unverified_session",
    }
    return {
        "schema": "agent_response_source_status.v1",
        "responded": captured,
        "responseSource": "stdout_auto_capture" if captured else None,
        "rawResponseSource": _optional_text_from_mapping(
            activation,
            "responseSource",
            "rawResponseSource",
        ),
        "standardResponded": False,
        "stdoutFallbackCaptured": captured,
        "captureMode": _optional_text_from_mapping(
            activation,
            "responseCaptureMode",
            "captureMode",
        ),
        "stdoutFallbackMeaning": STDOUT_FALLBACK_MEANING,
        "standardRespondMeaning": STANDARD_RESPOND_MEANING,
        "privateReasoningRead": False,
        "fullTranscriptRead": False,
    }


def _response_source_is_stdout_capture(raw_source: str | None) -> bool:
    if raw_source is None:
        return False
    normalized = raw_source.strip().lower()
    if normalized == "stdout_auto_capture":
        return True
    return "auto_capture" in normalized or (
        "stdout" in normalized and "capture" in normalized
    )


def _agent_status_ids_match(
    source: Mapping[str, object],
    *,
    exchange_request_id: str | None,
    dispatch_id: str | None,
    thread_id: str | None,
) -> bool:
    if exchange_request_id is not None and source.get("exchangeRequestId") != exchange_request_id:
        return False
    if dispatch_id is not None and source.get("dispatchId") != dispatch_id:
        return False
    if thread_id is not None and source.get("threadId") != thread_id:
        return False
    if exchange_request_id is None and dispatch_id is None and thread_id is None:
        return True
    return True


def _agent_status_timeline_item(
    entry: PlatformEventLogEntry,
    *,
    action: str,
    stage: str,
    subject: str,
    ids: Mapping[str, object],
    provider: str | None = None,
    response_source_status: Mapping[str, object] | None = None,
    readable_reason: Mapping[str, object] | None = None,
    retry_actor_status: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    item: dict[str, object] = {
        "schema": "agent_exchange_status_timeline_event.v1",
        "sourceEventSequence": entry.sequence,
        "occurredAt": entry.record.occurred_at.isoformat(),
        "eventKind": _enum_or_text(entry.record.event_kind),
        "aggregateType": entry.record.aggregate_type,
        "aggregateId": entry.record.aggregate_id,
        "subject": subject,
        "action": action,
        "stage": stage,
        "exchangeRequestId": ids.get("exchangeRequestId"),
        "dispatchId": ids.get("dispatchId"),
        "threadId": ids.get("threadId"),
        "wakeTicketId": ids.get("wakeTicketId"),
        "leaseId": ids.get("leaseId"),
        "provider": provider or ids.get("targetProvider") or ids.get("provider"),
        "privateReasoningRead": False,
        "fullTranscriptRead": False,
    }
    if response_source_status is not None:
        item["responseSourceStatus"] = response_source_status
        item["responseSource"] = response_source_status.get("responseSource")
        item["rawResponseSource"] = response_source_status.get("rawResponseSource")
        item["stdoutFallbackCaptured"] = response_source_status.get(
            "stdoutFallbackCaptured"
        )
        item["standardResponded"] = response_source_status.get("standardResponded")
        item["captureMode"] = response_source_status.get("captureMode")
    if readable_reason is not None:
        item["readableReason"] = readable_reason
        item["reasonCode"] = readable_reason.get("reasonCode")
    if retry_actor_status is not None:
        item["retryActorStatus"] = retry_actor_status
    return item


def _agent_request_readable_reason(
    request: AgentExchangeRequest | Mapping[str, object] | None,
) -> Mapping[str, object]:
    if request is None:
        return _readable_status_reason("request_missing", "request not found.")
    if isinstance(request, AgentExchangeRequest):
        if request.terminal_reason is AgentExchangeRequestTerminalReason.RESPONDED:
            return _readable_status_reason("responded", "request was answered.")
        return _readable_status_reason(request.status.value, "request is active.")
    return _agent_request_readable_reason_mapping(request)


def _agent_request_readable_reason_mapping(
    request: Mapping[str, object],
) -> Mapping[str, object]:
    terminal_reason = str(request.get("terminalReason") or "")
    if terminal_reason == AgentExchangeRequestTerminalReason.RESPONDED.value:
        return _readable_status_reason("responded", "request was answered.")
    status = str(request.get("status") or "request_observed")
    return _readable_status_reason(status, f"request status is {status}.")


def _agent_dispatch_readable_reason(
    dispatch: Mapping[str, object],
) -> Mapping[str, object]:
    metadata = _nested_metadata(dispatch)
    status = str(dispatch.get("status") or "")
    lease_recovery = metadata.get("leaseRecovery")
    recovery_is_latest_action = (
        isinstance(lease_recovery, MappingABC)
        and metadata.get("lastLeaseAction") == "recovered"
        and metadata.get("workerAction")
        not in {
            "provider_activation_finished",
            "provider_activation_precheck_failed",
            "provider_activation_skipped",
        }
    )
    if recovery_is_latest_action:
        result_status = str(lease_recovery.get("resultDispatchStatus") or status)
        return _readable_status_reason(
            "orphan_lease_recovered",
            (
                "An orphan or expired dispatch lease was reconciled; "
                f"dispatch is now {result_status}."
            ),
        )
    skip_reason = _optional_text_from_mapping(metadata, "skipReason")
    if skip_reason is not None:
        return _readable_status_reason(
            "already_delivered_or_leased"
            if skip_reason == "target_lease_active"
            else skip_reason,
            _optional_text_from_mapping(metadata, "readableReason"),
        )
    if status == AgentDispatchStatus.RETRY_SCHEDULED.value:
        return _readable_status_reason(
            "retry_scheduled",
            _optional_text_from_mapping(metadata, "failureReason"),
        )
    failure_category = _optional_text_from_mapping(metadata, "failureCategory")
    failure_reason = _optional_text_from_mapping(metadata, "failureReason")
    if failure_category is not None:
        return _readable_status_reason(failure_category, failure_reason)
    if status == AgentDispatchStatus.COMPLETED.value:
        return _readable_status_reason("completed", "dispatch completed.")
    if status == AgentDispatchStatus.LEASED.value:
        return _readable_status_reason("leased", "dispatch was leased by a worker.")
    if status == AgentDispatchStatus.QUEUED.value:
        return _readable_status_reason("queued", "dispatch is queued.")
    return _readable_status_reason(status or "dispatch_observed", None)


def _agent_dispatch_retry_actor_status(
    dispatch: Mapping[str, object],
) -> Mapping[str, object]:
    metadata = _nested_metadata(dispatch)
    lease_recovery = metadata.get("leaseRecovery")
    recovered_retry = (
        isinstance(lease_recovery, MappingABC)
        and lease_recovery.get("resultDispatchStatus")
        == AgentDispatchStatus.RETRY_SCHEDULED.value
    )
    manual_retry_of = _optional_text_from_mapping(
        metadata,
        "manualRetryOf",
        "manualRetryOfDispatchId",
        "manualRetryOfRequestId",
    )
    status = str(dispatch.get("status") or "")
    return {
        "schema": "agent_retry_actor_status.v1",
        "platformAutomaticRetry": recovered_retry,
        "workerRetryScheduled": status == AgentDispatchStatus.RETRY_SCHEDULED.value,
        "senderCreatedNewDispatch": manual_retry_of is not None,
        "manualRetryOf": manual_retry_of,
        "retryMeaning": (
            "Worker retry uses the same dispatch with nextAttemptAfter; "
            "manual/sender retry should appear as a new request or dispatch "
            "with manualRetryOf metadata."
        ),
    }


def _agent_dispatch_lease_recovery_status(
    dispatch: Mapping[str, object] | None,
) -> Mapping[str, object]:
    metadata = _nested_metadata(dispatch or {})
    recovery = metadata.get("leaseRecovery")
    if not isinstance(recovery, MappingABC):
        return {
            "schema": "agent_dispatch_lease_recovery_status.v1",
            "recovered": False,
            "recoveryReason": None,
            "originalLeaseId": None,
            "resultDispatchStatus": None,
            "resultNextAttemptAfter": None,
            "attemptCountIncremented": False,
            "automaticProviderActivationTriggered": False,
        }
    return {
        "schema": "agent_dispatch_lease_recovery_status.v1",
        "recovered": True,
        "recoveryReason": recovery.get("recoveryReason"),
        "originalLeaseId": recovery.get("originalLeaseId"),
        "originalDispatcher": recovery.get("originalDispatcher"),
        "originalWorkerRunId": recovery.get("originalWorkerRunId"),
        "leaseExpiresAt": recovery.get("leaseExpiresAt"),
        "leaseExpired": bool(recovery.get("leaseExpired")),
        "requestStatus": recovery.get("requestStatus"),
        "requestTerminalReason": recovery.get("requestTerminalReason"),
        "resultDispatchStatus": recovery.get("resultDispatchStatus"),
        "resultNextAttemptAfter": recovery.get("resultNextAttemptAfter"),
        "recoveredBy": recovery.get("recoveredBy"),
        "recoveredAt": recovery.get("recoveredAt"),
        "attemptCountIncremented": bool(recovery.get("attemptCountIncremented")),
        "automaticProviderActivationTriggered": bool(
            recovery.get("automaticProviderActivationTriggered")
        ),
    }


def _agent_wake_readable_reason(
    delivery: Mapping[str, object],
) -> Mapping[str, object]:
    status = str(delivery.get("status") or "")
    skip_reason = _optional_text_from_mapping(delivery, "skipReason")
    if skip_reason is not None:
        return _readable_status_reason(skip_reason, None)
    if status == AgentWakeDeliveryStatus.LEASED.value:
        return _readable_status_reason("wake_leased", "wake delivery was leased.")
    if status == AgentWakeDeliveryStatus.DELIVERED.value:
        return _readable_status_reason("wake_delivered", "wake ticket was delivered.")
    failure_reason = _optional_text_from_mapping(delivery, "failureReason")
    if failure_reason is not None:
        return _readable_status_reason("wake_failed", failure_reason)
    return _readable_status_reason(status or "wake_observed", None)


def _agent_activation_readable_reason(
    activation: Mapping[str, object],
) -> Mapping[str, object]:
    capture_status = _optional_text_from_mapping(activation, "responseCaptureStatus")
    if capture_status == "recorded":
        return _readable_status_reason(
            "stdout_auto_capture",
            "provider stdout/stderr response was captured as fallback output.",
        )
    failure_category = _optional_text_from_mapping(activation, "failureCategory")
    failure_reason = _optional_text_from_mapping(activation, "failureReason")
    if failure_category is not None:
        return _readable_status_reason(failure_category, failure_reason)
    if activation.get("providerCommandStarted"):
        return _readable_status_reason(
            "provider_started",
            "provider command started for registered session activation.",
        )
    return _readable_status_reason(
        str(activation.get("status") or "activation_observed"),
        None,
    )


def _readable_status_reason(
    reason_code: str | None,
    detail: str | None,
) -> Mapping[str, object]:
    normalized = (reason_code or "unknown").strip() or "unknown"
    lower_detail = (detail or "").lower()
    if normalized in {
        "target_lease_active",
        "valid_platform_lease",
        "already_delivered_or_leased",
    }:
        stable_code = "already_delivered_or_leased"
        message = (
            "A non-expired platform lease still owns the target; duplicate "
            "activation was skipped."
        )
    elif normalized == "target_runtime_busy":
        stable_code = normalized
        message = "Target runtime is busy; worker skipped activation and left the dispatch queued."
    elif normalized == "target_runtime_blocked":
        stable_code = normalized
        message = (
            "Target runtime is blocked on an external dependency; worker skipped "
            "activation and left the dispatch queued."
        )
    elif normalized == "probe_failed":
        stable_code = normalized
        message = "Provider runtime status probe failed; runtime state is unknown."
    elif normalized == "waiting_response_stale":
        stable_code = normalized
        message = "The dispatch has waited for a target response beyond its warning threshold."
    elif normalized == "orphan_lease_recovered":
        stable_code = normalized
        message = detail or "An orphan or expired dispatch lease was recovered."
    elif normalized == "retry_scheduled":
        stable_code = normalized
        message = "Worker scheduled a retry for this dispatch."
    elif normalized == "executable_not_found":
        stable_code = normalized
        message = "Provider executable was not found."
    elif normalized in {"command_exit_nonzero", "provider_command_failed"}:
        stable_code = "provider_command_failed"
        message = "Provider command failed."
    elif (
        "quota" in lower_detail
        or "rate" in lower_detail
        or "limit" in lower_detail
        or "quota" in normalized
        or "rate_limit" in normalized
    ):
        stable_code = "provider_quota_or_rate_limit"
        message = "Provider quota or rate limit appears to have blocked activation."
    elif (
        "permission" in lower_detail
        or "access denied" in lower_detail
        or "eacces" in lower_detail
        or "permission" in normalized
    ):
        stable_code = "permission_denied"
        message = "Provider command was blocked by permissions."
    else:
        stable_code = normalized
        message = {
            "queued": "Dispatch is queued.",
            "leased": "Dispatch was leased by a worker.",
            "completed": "Dispatch completed.",
            "failed": "Dispatch failed.",
            "responded": "Request was answered.",
            "stdout_auto_capture": "Provider stdout/stderr response was captured as fallback output.",
            "provider_started": "Provider command started.",
        }.get(normalized, detail or normalized.replace("_", " "))
    return {
        "schema": "agent_readable_status_reason.v1",
        "reasonCode": stable_code,
        "message": message,
        "detail": detail,
    }


def _agent_dispatch_runtime_block_reason(
    provider_runtime_status: Mapping[str, object],
) -> str:
    if provider_runtime_status.get("stateSource") == "platform_dispatch_lease":
        return "valid_platform_lease"
    if provider_runtime_status.get("runtimeState") == "blocked":
        return "target_runtime_blocked"
    return "target_runtime_busy"


def _agent_dispatch_busy_retry_delay_seconds(busy_skip_count: int) -> int:
    schedule = (5, 15, 30, 60)
    index = min(max(busy_skip_count, 1) - 1, len(schedule) - 1)
    return schedule[index]


def _agent_provider_runtime_precheck_summary(
    provider_runtime_status: Mapping[str, object],
) -> Mapping[str, object]:
    probe = provider_runtime_status.get("providerRuntimeStatusProbe")
    probe_status = (
        _optional_text_from_mapping(probe, "status")
        if isinstance(probe, MappingABC)
        else None
    )
    probe_failed = probe_status in {
        "invalid_config",
        "timeout",
        "failed",
        "exit_nonzero",
        "invalid_json",
        "state_missing",
    }
    return {
        "schema": "agent_provider_runtime_precheck.v1",
        "runtimeState": provider_runtime_status.get("runtimeState"),
        "stateSource": provider_runtime_status.get("stateSource"),
        "runtimeStatusPolicy": provider_runtime_status.get("runtimeStatusPolicy"),
        "providerRuntimeStatusRead": provider_runtime_status.get(
            "providerRuntimeStatusRead"
        ),
        "probeStatus": probe_status,
        "probeFailed": probe_failed,
        "reasonCode": "probe_failed" if probe_failed else None,
        "failureReason": (
            probe.get("failureReason")
            if isinstance(probe, MappingABC) and probe_failed
            else None
        ),
    }


def _agent_dispatch_status_value(value: AgentDispatchStatus | str) -> str:
    return value.value if isinstance(value, AgentDispatchStatus) else str(value)


def _agent_dispatch_lease_recovery_decision(
    *,
    lease: AgentDispatchLeaseRecord,
    dispatch: AgentDispatchRecord | None,
    request: AgentExchangeRequest | None,
    checked_at: datetime,
    recovery_delay_seconds: int,
) -> Mapping[str, object]:
    lease_expired = lease.expires_at is not None and lease.expires_at <= checked_at
    request_status = request.status.value if request is not None else "missing"
    terminal_reason = (
        request.terminal_reason.value
        if request is not None and request.terminal_reason is not None
        else None
    )
    result_status: AgentDispatchStatus | None = None
    recovery_reason: str | None = None
    next_attempt_after: datetime | None = None

    if request is not None and request.status is AgentExchangeRequestStatus.TERMINAL:
        if request.terminal_reason is AgentExchangeRequestTerminalReason.RESPONDED:
            result_status = AgentDispatchStatus.COMPLETED
            recovery_reason = "request_responded_orphan_lease"
        elif request.terminal_reason is AgentExchangeRequestTerminalReason.BLOCKED:
            result_status = AgentDispatchStatus.FAILED
            recovery_reason = "request_blocked_orphan_lease"
        else:
            result_status = AgentDispatchStatus.CANCELLED
            recovery_reason = (
                f"request_{request.terminal_reason.value}_orphan_lease"
                if request.terminal_reason is not None
                else "request_terminal_orphan_lease"
            )
    elif dispatch is not None and AgentDispatchStatus(dispatch.status) in {
        AgentDispatchStatus.CANCELLED,
        AgentDispatchStatus.FAILED,
        AgentDispatchStatus.COMPLETED,
    }:
        result_status = AgentDispatchStatus(dispatch.status)
        recovery_reason = "dispatch_terminal_orphan_lease"
    elif request is not None and request.is_expired(checked_at):
        result_status = AgentDispatchStatus.CANCELLED
        recovery_reason = "request_deadline_expired_orphan_lease"
    elif lease_expired and request is None:
        result_status = AgentDispatchStatus.FAILED
        recovery_reason = "request_missing_expired_orphan_lease"
    elif lease_expired:
        result_status = AgentDispatchStatus.RETRY_SCHEDULED
        recovery_reason = "expired_orphan_lease_active_request"
        next_attempt_after = checked_at + timedelta(seconds=recovery_delay_seconds)

    if result_status is None:
        return {
            "decision": "preserve",
            "leaseExpired": lease_expired,
            "requestStatus": request_status,
            "requestTerminalReason": terminal_reason,
            "recoveryReason": "valid_active_lease",
            "resultDispatchStatus": (
                AgentDispatchStatus(dispatch.status).value
                if dispatch is not None
                else None
            ),
            "nextAttemptAfter": (
                dispatch.next_attempt_after.isoformat()
                if dispatch is not None
                and dispatch.next_attempt_after is not None
                else None
            ),
        }
    return {
        "decision": "recover",
        "leaseExpired": lease_expired,
        "requestStatus": request_status,
        "requestTerminalReason": terminal_reason,
        "recoveryReason": recovery_reason,
        "resultDispatchStatus": result_status.value,
        "nextAttemptAfter": (
            next_attempt_after.isoformat()
            if next_attempt_after is not None
            else None
        ),
    }


def _enum_or_text(value: object) -> str:
    enum_value = getattr(value, "value", None)
    return enum_value if isinstance(enum_value, str) else str(value)


def _quote_arg(value: str) -> str:
    if value == "":
        return '""'
    if any(character.isspace() for character in value) or '"' in value:
        return '"' + value.replace('"', '\\"') + '"'
    return value


_PROBE_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9]{20,}|Bearer\s+sk-|Authorization:\s*Bearer|Cookie:)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _CodexActivationProcessResult:
    returncode: int
    stdout: str | None
    stderr: str | None
    timed_out: bool = False
    terminated_after_response_capture: bool = False


_CODEX_FINAL_OUTPUT_EXIT_GRACE_SECONDS = 5.0


def _run_codex_activation_process(
    argv: Sequence[str],
    *,
    cwd: str,
    stdin_text: str,
    output_last_message_path: str,
    timeout_seconds: int,
    on_started: Callable[[], None],
) -> _CodexActivationProcessResult:
    popen_kwargs: dict[str, object] = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(
            subprocess,
            "CREATE_NEW_PROCESS_GROUP",
            0,
        )
    else:
        popen_kwargs["start_new_session"] = True

    with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(
        mode="w+b"
    ) as stderr_file:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            **popen_kwargs,
        )
        try:
            on_started()
        except BaseException:
            _terminate_codex_activation_process_tree(process)
            raise
        if process.stdin is not None:
            try:
                process.stdin.write(stdin_text)
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            finally:
                process.stdin.close()

        deadline = time.monotonic() + timeout_seconds
        response_observed_at: float | None = None
        timed_out = False
        terminated_after_response_capture = False
        while process.poll() is None:
            now = time.monotonic()
            if response_observed_at is None and _read_optional_text_file(
                output_last_message_path
            ):
                response_observed_at = now
            if (
                response_observed_at is not None
                and now - response_observed_at
                >= _CODEX_FINAL_OUTPUT_EXIT_GRACE_SECONDS
            ):
                terminated_after_response_capture = True
                _terminate_codex_activation_process_tree(process)
                break
            if now >= deadline:
                timed_out = True
                _terminate_codex_activation_process_tree(process)
                break
            time.sleep(0.05)

        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read().decode("utf-8", errors="replace") or None
        stderr = stderr_file.read().decode("utf-8", errors="replace") or None
        return _CodexActivationProcessResult(
            returncode=process.returncode if process.returncode is not None else -1,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            terminated_after_response_capture=terminated_after_response_capture,
        )


def _terminate_codex_activation_process_tree(
    process: subprocess.Popen[str],
) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                shell=False,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except OSError:
            pass
    if process.poll() is None:
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except OSError:
                    process.kill()


def _codex_started_attempt_is_stale(
    attempt: CodexRegisteredSessionActivationAttempt,
    *,
    occurred_at: datetime,
    timeout_seconds: int,
) -> bool:
    stale_after = timedelta(seconds=timeout_seconds + 30)
    return occurred_at - attempt.created_at > stale_after


def _safe_filename(value: str) -> str:
    return "".join(
        character
        if character.isalnum() or character in {"-", "_", "."}
        else "_"
        for character in value
    )[:160]


def _short_stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _agent_wake_ticket_namespace(ticket: AgentWakeTicket) -> str:
    return (
        f"ws-{_short_stable_id(ticket.workspace_id)}."
        f"agent-{_short_stable_id(ticket.target_agent_id)}"
    )


def _agent_wake_ticket_filename(ticket: AgentWakeTicket) -> str:
    return (
        f"req-{_short_stable_id(ticket.exchange_request_id)}."
        f"wake-{_short_stable_id(ticket.wake_ticket_id)}.json"
    )


def _datetime_text(value: datetime) -> str:
    return value.isoformat()


def _optional_datetime_text(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _datetime_text(value)
    if isinstance(value, str):
        return value
    raise TypeError("datetime value must be a datetime, string, or None.")


def _coalesced_liveness_value(
    value: object | None,
    previous: object | None,
) -> object | None:
    return previous if value is None else value


def _agent_dispatch_daemon_state(value: str) -> str:
    state = _non_empty_text(value, "state")
    if state not in _AGENT_DISPATCH_DAEMON_STATES:
        raise ValueError(
            "state must be one of: "
            + ", ".join(sorted(_AGENT_DISPATCH_DAEMON_STATES))
        )
    return state


def _agent_dispatch_daemon_running(state: str) -> bool:
    return state in _AGENT_DISPATCH_DAEMON_RUNNING_STATES


def _default_agent_dispatch_daemon_liveness(
    *,
    workspace_id: str,
    dispatcher_id: str,
    state: str,
) -> Mapping[str, object]:
    return {
        "schema": "agent_dispatch_daemon_liveness.v1",
        "workspaceId": workspace_id,
        "dispatcherId": dispatcher_id,
        "profilePath": None,
        "pid": None,
        "processHint": None,
        "startedAt": None,
        "lastHeartbeatAt": None,
        "lastPollAt": None,
        "lastErrorAt": None,
        "lastExitAt": None,
        "lastExitReason": None,
        "errorSummary": None,
        "state": state,
        "updatedAt": None,
        "metadata": {},
    }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _root_path_text(value: str) -> str:
    return _non_empty_text(value, "root_path")


def _non_empty_text(value: str, logical_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{logical_name} must be a non-empty string.")
    if "\x00" in value:
        raise ValueError(f"{logical_name} must not contain null bytes.")
    return value


def _default_context_id(workspace_id: WorkspaceId) -> ContextId:
    return ContextId(f"context-{workspace_id.value}")


def _default_agent_id(workspace_id: WorkspaceId) -> AgentId:
    return AgentId(f"agent-{workspace_id.value}")


def _workspace_id(value: WorkspaceId | str) -> WorkspaceId:
    return value if isinstance(value, WorkspaceId) else WorkspaceId(value)


def _context_id(value: ContextId | str) -> ContextId:
    return value if isinstance(value, ContextId) else ContextId(value)


def _agent_id(value: AgentId | str) -> AgentId:
    return value if isinstance(value, AgentId) else AgentId(value)


def _agent_invocation_id(
    value: AgentInvocationId | str,
) -> AgentInvocationId:
    return (
        value
        if isinstance(value, AgentInvocationId)
        else AgentInvocationId(value)
    )


def _context_update_id(value: ContextUpdateId | str) -> ContextUpdateId:
    return value if isinstance(value, ContextUpdateId) else ContextUpdateId(value)


def _conversation_id(value: ConversationId | str) -> ConversationId:
    return value if isinstance(value, ConversationId) else ConversationId(value)


def _conversation_message_id(
    value: ConversationMessageId | str,
) -> ConversationMessageId:
    return (
        value
        if isinstance(value, ConversationMessageId)
        else ConversationMessageId(value)
    )


def _conversation_message_role(
    value: ConversationMessageRole | str,
) -> ConversationMessageRole:
    return (
        value
        if isinstance(value, ConversationMessageRole)
        else ConversationMessageRole(value)
    )


def _file_operation_id(value: FileOperationId | str) -> FileOperationId:
    return (
        value
        if isinstance(value, FileOperationId)
        else FileOperationId(value)
    )


def _context_update_kind(value: ContextUpdateKind | str) -> ContextUpdateKind:
    return value if isinstance(value, ContextUpdateKind) else ContextUpdateKind(value)


def _platform_event_id(value: PlatformEventId | str) -> PlatformEventId:
    return value if isinstance(value, PlatformEventId) else PlatformEventId(value)


def _platform_run_session_id(
    value: PlatformRunSessionId | str,
) -> PlatformRunSessionId:
    return (
        value
        if isinstance(value, PlatformRunSessionId)
        else PlatformRunSessionId(value)
    )


def _task_id(value: TaskId | str) -> TaskId:
    return value if isinstance(value, TaskId) else TaskId(value)


def _issue_id(value: IssueId | str) -> IssueId:
    return value if isinstance(value, IssueId) else IssueId(value)
