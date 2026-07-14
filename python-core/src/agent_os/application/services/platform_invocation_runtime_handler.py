from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import sqlite3
from typing import Callable, Mapping

from agent_os.application.services.file_operation_service import (
    RecordedFileOperationResult,
)
from agent_os.application.services.file_operation_context_linker import (
    FileOperationContextLinker,
)
from agent_os.application.services.platform_invocation_gateway_handler import (
    SingleTurnPlatformInvocationPayloadDraft,
)
from agent_os.application.services.single_turn_platform_runtime import (
    AgentInvocationAdapterPort,
    ContextUpdateRecorderPort,
    SingleTurnPlatformRunResult,
)
from agent_os.application.services.workspace_file_operation_use_case import (
    WorkspaceFileOperationUseCase,
)
from agent_os.domain.entities.context import ContextUpdateInfo, ProjectSharedContext
from agent_os.domain.entities.agent import AgentRegistration
from agent_os.domain.entities.conversation import (
    ConversationMessage,
    ConversationMessageRole,
    ConversationStatus,
)
from agent_os.domain.entities.file_operation import (
    FileOperationKind,
    FileOperationResultStatus,
)
from agent_os.domain.entities.invocation import AgentInvocationResult
from agent_os.domain.value_objects.identifiers import (
    AgentId,
    AgentInvocationId,
    ContextUpdateId,
    ConversationId,
    FileOperationId,
    PlatformEventId,
    PlatformRunSessionId,
    TaskId,
    WorkspaceId,
)
from agent_os.infrastructure.composition.local_single_turn_use_case import (
    build_sqlite_local_single_turn_platform_use_case,
)
from agent_os.infrastructure.persistence.invocation_records import (
    SqliteAgentInvocationRecordStore,
)
from agent_os.infrastructure.persistence.conversations import (
    ConversationMessageRecord,
    ConversationSessionRecord,
    SqliteConversationStore,
)
from agent_os.infrastructure.persistence.event_log import (
    PlatformEventKind,
    PlatformEventRecord,
    SqlitePlatformEventLog,
)


PLATFORM_INVOCATION_RESPONSE_FIELDS = (
    "workspaceId",
    "agentId",
    "contextId",
    "runtimeLoaded",
    "modelInvoked",
    "toolInvoked",
    "deterministicPlaceholder",
    "sourceEventSequence",
    "agentInvocationEventSequence",
    "materializedState",
    "userContextUpdate",
    "invocationResult",
    "fileOperations",
    "conversation",
    "conversationMessages",
    "runSessionEventSequences",
)

PLATFORM_INVOCATION_USER_CONTEXT_UPDATE_FIELDS = (
    "updateId",
    "workspaceId",
    "updateKind",
    "summary",
    "createdAt",
    "sourceAgentId",
    "payload",
    "materializedStatePatch",
    "metadata",
)

PLATFORM_INVOCATION_RESULT_FIELDS = (
    "invocationId",
    "workspaceId",
    "agentId",
    "status",
    "summary",
    "completedAt",
    "outputText",
    "errorMessage",
    "outputPayload",
    "contextUpdateIds",
    "metadata",
)


@dataclass(slots=True)
class SqlitePlatformInvocationRuntimeHandler:
    """Executable local handler for one single-turn platform invocation payload."""

    connection: sqlite3.Connection
    record_agent_invocations: bool = True
    agent_invocation_adapter: AgentInvocationAdapterPort | None = None
    agent_invocation_adapter_factory: Callable[
        [AgentRegistration],
        AgentInvocationAdapterPort | None,
    ] | None = None
    file_operation_use_case_factory: Callable[
        [WorkspaceId],
        WorkspaceFileOperationUseCase,
    ] | None = None

    def handle_payload(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        draft = SingleTurnPlatformInvocationPayloadDraft.from_payload(payload)
        file_operation_drafts = _file_operation_drafts(payload)
        workspace_id = WorkspaceId(draft.workspace_id)
        self._validate_idempotency_boundary(
            workspace_id=workspace_id,
            idempotency_key=draft.idempotency_key,
        )
        invocation_id = _agent_invocation_id(draft.invocation_id) or AgentInvocationId.new()
        requested_at = _datetime_from_text(draft.requested_at, "requested_at")
        task_id = _task_id(draft.task_id)
        user_context_update_id = _context_update_id(
            _optional_payload_text(
                payload,
                "user_context_update_id",
                "userContextUpdateId",
                "user_context_update_id",
            )
        )
        user_context_created_at = _datetime_from_text(
            _optional_payload_text(
                payload,
                "user_context_created_at",
                "userContextCreatedAt",
                "user_context_created_at",
            ),
            "user_context_created_at",
        )
        context_event_id = _platform_event_id(
            _optional_payload_text(
                payload,
                "context_event_id",
                "contextEventId",
                "context_event_id",
            )
        )
        agent_invocation_event_id = _platform_event_id(
            _optional_payload_text(
                payload,
                "agent_invocation_event_id",
                "agentInvocationEventId",
                "agent_invocation_event_id",
            )
        )
        session_id = _platform_run_session_id(
            _optional_payload_text(payload, "session_id", "sessionId", "session_id")
        )
        context_metadata = _optional_payload_mapping(
            payload,
            "context_metadata",
            "contextMetadata",
            "context_metadata",
        )
        context_event_metadata = _optional_payload_mapping(
            payload,
            "context_event_metadata",
            "contextEventMetadata",
            "context_event_metadata",
            "eventMetadata",
            "event_metadata",
        )
        agent_invocation_event_metadata = _optional_payload_mapping(
            payload,
            "agent_invocation_event_metadata",
            "agentInvocationEventMetadata",
            "agent_invocation_event_metadata",
        )
        context_update_ids = tuple(
            ContextUpdateId(update_id) for update_id in draft.context_update_ids
        )
        file_references = tuple(draft.file_references)
        conversation_id = _conversation_id(
            _optional_payload_text(
                payload,
                "conversation_id",
                "conversationId",
                "conversation_id",
            )
        )
        components = build_sqlite_local_single_turn_platform_use_case(
            self.connection,
            workspace_id=workspace_id,
            agent_id=AgentId(draft.agent_id),
            record_agent_invocations=self.record_agent_invocations,
            agent_invocation_adapter=self.agent_invocation_adapter,
            agent_invocation_adapter_factory=self.agent_invocation_adapter_factory,
        )
        _preflight_invocation_request(
            components,
            invocation_id=invocation_id,
            instruction=draft.instruction,
            requested_at=requested_at,
            task_id=task_id,
            requested_capability=draft.requested_capability,
            context_update_ids=context_update_ids,
            file_references=file_references,
            idempotency_key=draft.idempotency_key,
            correlation_id=draft.correlation_id,
            request_metadata=dict(draft.request_metadata),
        )
        conversation_store = SqliteConversationStore(self.connection)
        conversation_record = _require_invocation_conversation(
            conversation_store=conversation_store,
            workspace_id=workspace_id,
            agent_id=AgentId(draft.agent_id),
            conversation_id=conversation_id,
        )
        file_operation_batch = self._execute_file_operation_drafts(
            workspace_id=workspace_id,
            agent_id=AgentId(draft.agent_id),
            invocation_id=invocation_id,
            task_id=task_id,
            requested_at=requested_at,
            context=components.context,
            context_update_recorder=components.runtime_components.context_update_recorder,
            session_id=session_id,
            drafts=file_operation_drafts,
        )
        file_context_update_ids = tuple(
            record.context_update.update_id
            for record in file_operation_batch.records
        )
        result = components.use_case.run(
            context=file_operation_batch.context,
            invocation_id=invocation_id,
            instruction=draft.instruction,
            requested_at=requested_at,
            task_id=task_id,
            requested_capability=draft.requested_capability,
            context_update_ids=_merged_context_update_ids(
                file_context_update_ids,
                context_update_ids,
            ),
            file_references=file_references,
            idempotency_key=draft.idempotency_key,
            correlation_id=draft.correlation_id,
            request_metadata=_invocation_request_metadata(
                draft.request_metadata,
                conversation_id=conversation_id,
                file_operation_batch=file_operation_batch,
            ),
            update_id=user_context_update_id,
            created_at=user_context_created_at,
            event_id=context_event_id,
            invocation_event_id=agent_invocation_event_id,
            session_id=session_id,
            context_metadata=context_metadata,
            event_metadata=context_event_metadata,
            invocation_event_metadata=agent_invocation_event_metadata,
        )
        conversation_batch = _append_invocation_conversation_messages(
            connection=self.connection,
            conversation_store=conversation_store,
            conversation_record=conversation_record,
            invocation_id=invocation_id,
            agent_id=AgentId(draft.agent_id),
            instruction=draft.instruction,
            result=result,
            session_id=session_id,
            correlation_id=draft.correlation_id,
        )
        return _run_result_payload(
            result,
            file_operation_batch=file_operation_batch,
            conversation_batch=conversation_batch,
        )

    def _execute_file_operation_drafts(
        self,
        *,
        workspace_id: WorkspaceId,
        agent_id: AgentId,
        invocation_id: AgentInvocationId,
        task_id: TaskId | None,
        requested_at: datetime | None,
        context: ProjectSharedContext,
        context_update_recorder: ContextUpdateRecorderPort,
        session_id: PlatformRunSessionId | None,
        drafts: tuple["PlatformInvocationFileOperationDraft", ...],
    ) -> "PlatformInvocationFileOperationBatch":
        if not drafts:
            return PlatformInvocationFileOperationBatch(context=context)
        if self.file_operation_use_case_factory is None:
            raise ValueError(
                "explicit file operation payloads require a configured file operation use case."
            )

        use_case = self.file_operation_use_case_factory(workspace_id)
        current_context = context
        linker = FileOperationContextLinker()
        records: list[PlatformInvocationFileOperationRecord] = []
        for draft in drafts:
            if draft.operation_kind == FileOperationKind.READ_FILE:
                recorded = use_case.read_file(
                    operation_id=_file_operation_id(draft.operation_id),
                    relative_path=draft.relative_path,
                    requested_at=requested_at,
                    requested_by_agent_id=agent_id,
                    event_id=_platform_event_id(draft.event_id),
                    reason=draft.reason,
                    request_metadata=_file_operation_request_metadata(
                        draft,
                        invocation_id=invocation_id,
                        task_id=task_id,
                    ),
                    audit_metadata=draft.audit_metadata,
                )
            elif draft.operation_kind == FileOperationKind.LIST_DIRECTORY:
                recorded = use_case.list_directory(
                    operation_id=_file_operation_id(draft.operation_id),
                    relative_path=draft.relative_path,
                    recursive=draft.recursive,
                    requested_at=requested_at,
                    requested_by_agent_id=agent_id,
                    event_id=_platform_event_id(draft.event_id),
                    reason=draft.reason,
                    request_metadata=_file_operation_request_metadata(
                        draft,
                        invocation_id=invocation_id,
                        task_id=task_id,
                    ),
                    audit_metadata=draft.audit_metadata,
                )
            else:
                raise ValueError(
                    "platform invocation file operations currently support only read_file and list_directory."
                )

            if recorded.result.status != FileOperationResultStatus.SUCCEEDED:
                raise ValueError(
                    "platform invocation file operation failed: "
                    f"{recorded.result.error_message or recorded.result.status.value}."
                )
            context_update = linker.build_update(
                result=recorded.result,
                source_event_sequence=recorded.source_event_sequence,
                update_id=_context_update_id(draft.context_update_id),
                metadata={
                    "source": "platform_invocation_file_operation_payload",
                },
            )
            recorded_context = context_update_recorder.record_context_update_event(
                context=current_context,
                update=context_update,
                event_id=_platform_event_id(draft.context_event_id),
                session_id=session_id,
                metadata={
                    "source": "platform_invocation_file_operation_payload",
                },
            )
            current_context = recorded_context.context
            records.append(
                PlatformInvocationFileOperationRecord(
                    file_operation=recorded,
                    context_update=context_update,
                    context_event_sequence=recorded_context.source_event_sequence,
                )
            )
        return PlatformInvocationFileOperationBatch(
            context=current_context,
            records=tuple(records),
        )

    def _validate_idempotency_boundary(
        self,
        *,
        workspace_id: WorkspaceId,
        idempotency_key: str | None,
    ) -> None:
        if idempotency_key is None:
            return
        if not self.record_agent_invocations:
            raise ValueError(
                "platform invocation payload field 'idempotency_key' requires agent invocation recording."
            )
        existing = SqliteAgentInvocationRecordStore(
            self.connection
        ).get_agent_invocation_record_by_idempotency_key(
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            raise ValueError(
                "platform invocation payload field 'idempotency_key' is already recorded for this workspace."
            )


def handle_sqlite_platform_invocation_payload(
    connection: sqlite3.Connection,
    payload: Mapping[str, object],
    *,
    record_agent_invocations: bool = True,
    agent_invocation_adapter: AgentInvocationAdapterPort | None = None,
    agent_invocation_adapter_factory: Callable[
        [AgentRegistration],
        AgentInvocationAdapterPort | None,
    ] | None = None,
    file_operation_use_case_factory: Callable[
        [WorkspaceId],
        WorkspaceFileOperationUseCase,
    ] | None = None,
) -> Mapping[str, object]:
    return SqlitePlatformInvocationRuntimeHandler(
        connection=connection,
        record_agent_invocations=record_agent_invocations,
        agent_invocation_adapter=agent_invocation_adapter,
        agent_invocation_adapter_factory=agent_invocation_adapter_factory,
        file_operation_use_case_factory=file_operation_use_case_factory,
    ).handle_payload(payload)


def _preflight_invocation_request(
    components,
    *,
    invocation_id: AgentInvocationId,
    instruction: str,
    requested_at: datetime | None,
    task_id: TaskId | None,
    requested_capability: str | None,
    context_update_ids: tuple[ContextUpdateId, ...],
    file_references: tuple[str, ...],
    idempotency_key: str | None,
    correlation_id: str | None,
    request_metadata: Mapping[str, object],
) -> None:
    components.request_factory.create_request(
        invocation_id=invocation_id,
        instruction=instruction,
        requested_at=requested_at,
        task_id=task_id,
        requested_capability=requested_capability,
        context_update_ids=context_update_ids,
        file_references=file_references,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        metadata=dict(request_metadata),
    )


@dataclass(frozen=True, slots=True)
class PlatformInvocationFileOperationDraft:
    """Explicit file operation requested by a local invocation payload."""

    operation_kind: FileOperationKind
    relative_path: str
    operation_id: str | None = None
    event_id: str | None = None
    context_update_id: str | None = None
    context_event_id: str | None = None
    recursive: bool = False
    reason: str | None = None
    request_metadata: Mapping[str, object] = field(default_factory=dict)
    audit_metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PlatformInvocationFileOperationRecord:
    """Recorded file operation and its derived context update."""

    file_operation: RecordedFileOperationResult
    context_update: ContextUpdateInfo
    context_event_sequence: int


@dataclass(frozen=True, slots=True)
class PlatformInvocationFileOperationBatch:
    """Context snapshot after explicit file operation handling."""

    context: ProjectSharedContext
    records: tuple[PlatformInvocationFileOperationRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class PlatformInvocationConversationBatch:
    """Conversation records created by an invocation-linked conversation write."""

    conversation: ConversationSessionRecord | None = None
    records: tuple[ConversationMessageRecord, ...] = ()


def _file_operation_drafts(
    payload: Mapping[str, object],
) -> tuple[PlatformInvocationFileOperationDraft, ...]:
    for field_name in ("fileOperations", "file_operations"):
        if field_name not in payload:
            continue
        value = payload[field_name]
        if not isinstance(value, (list, tuple)):
            raise ValueError(
                "platform invocation payload field 'file_operations' must be an array of objects."
            )
        drafts: list[PlatformInvocationFileOperationDraft] = []
        for item in value:
            if not isinstance(item, Mapping):
                raise ValueError(
                    "platform invocation payload field 'file_operations' must be an array of objects."
                )
            drafts.append(_file_operation_draft(dict(item)))
        return _validated_file_operation_drafts(tuple(drafts))
    return ()


def _validated_file_operation_drafts(
    drafts: tuple[PlatformInvocationFileOperationDraft, ...],
) -> tuple[PlatformInvocationFileOperationDraft, ...]:
    for draft in drafts:
        if draft.operation_kind not in {
            FileOperationKind.READ_FILE,
            FileOperationKind.LIST_DIRECTORY,
        }:
            raise ValueError(
                "platform invocation file operations currently support only read_file and list_directory."
            )
        if draft.operation_kind == FileOperationKind.LIST_DIRECTORY and draft.recursive:
            raise ValueError(
                "platform invocation file operations do not support recursive directory listing."
            )

    _reject_duplicate_optional_values(drafts, "operation_id")
    _reject_duplicate_optional_values(drafts, "event_id")
    _reject_duplicate_optional_values(drafts, "context_update_id")
    _reject_duplicate_optional_values(drafts, "context_event_id")
    return drafts


def _reject_duplicate_optional_values(
    drafts: tuple[PlatformInvocationFileOperationDraft, ...],
    field_name: str,
) -> None:
    seen: set[str] = set()
    for draft in drafts:
        value = getattr(draft, field_name)
        if value is None:
            continue
        if value in seen:
            raise ValueError(
                f"platform invocation file operation field '{field_name}' must not contain duplicate values."
            )
        seen.add(value)


def _file_operation_draft(
    payload: Mapping[str, object],
) -> PlatformInvocationFileOperationDraft:
    operation_kind_text = _optional_payload_text(
        payload,
        "file_operations.operation_kind",
        "operationKind",
        "operation_kind",
        "kind",
    )
    if operation_kind_text is None:
        raise ValueError(
            "platform invocation file operation field 'operation_kind' must be a non-empty string."
        )
    relative_path = _optional_payload_text(
        payload,
        "file_operations.relative_path",
        "relativePath",
        "relative_path",
    )
    if relative_path is None:
        raise ValueError(
            "platform invocation file operation field 'relative_path' must be a non-empty string."
        )
    return PlatformInvocationFileOperationDraft(
        operation_kind=_file_operation_kind(operation_kind_text),
        relative_path=relative_path,
        operation_id=_optional_payload_text(
            payload,
            "file_operations.operation_id",
            "operationId",
            "operation_id",
        ),
        event_id=_optional_payload_text(
            payload,
            "file_operations.event_id",
            "eventId",
            "event_id",
        ),
        context_update_id=_optional_payload_text(
            payload,
            "file_operations.context_update_id",
            "contextUpdateId",
            "context_update_id",
        ),
        context_event_id=_optional_payload_text(
            payload,
            "file_operations.context_event_id",
            "contextEventId",
            "context_event_id",
        ),
        recursive=_optional_payload_bool(
            payload,
            "file_operations.recursive",
            "recursive",
        ),
        reason=_optional_payload_text(
            payload,
            "file_operations.reason",
            "reason",
        ),
        request_metadata=_optional_payload_mapping(
            payload,
            "file_operations.request_metadata",
            "requestMetadata",
            "request_metadata",
            "metadata",
        ),
        audit_metadata=_optional_payload_mapping(
            payload,
            "file_operations.audit_metadata",
            "auditMetadata",
            "audit_metadata",
        ),
    )


def _file_operation_kind(value: str) -> FileOperationKind:
    normalized = {
        "readFile": "read_file",
        "listDirectory": "list_directory",
        "writeFile": "write_file",
    }.get(value, value)
    try:
        return FileOperationKind(normalized)
    except ValueError as exc:
        raise ValueError(
            "platform invocation file operation field 'operation_kind' must be one of: "
            "read_file, list_directory, write_file."
        ) from exc


def _file_operation_request_metadata(
    draft: PlatformInvocationFileOperationDraft,
    *,
    invocation_id: AgentInvocationId,
    task_id: TaskId | None,
) -> Mapping[str, object]:
    metadata = dict(draft.request_metadata)
    metadata.setdefault("source", "platform_invocation_file_operation_payload")
    metadata["invocation_id"] = invocation_id.value
    if task_id is not None:
        metadata["task_id"] = task_id.value
    return metadata


def _invocation_request_metadata(
    metadata: Mapping[str, object],
    *,
    conversation_id: ConversationId | None,
    file_operation_batch: PlatformInvocationFileOperationBatch,
) -> Mapping[str, object]:
    merged = dict(metadata)
    if conversation_id is not None:
        merged["conversation_id"] = conversation_id.value
    if file_operation_batch.records:
        merged["file_operation_ids"] = [
            record.file_operation.result.operation_id.value
            for record in file_operation_batch.records
        ]
        merged["file_operation_context_update_ids"] = [
            record.context_update.update_id.value
            for record in file_operation_batch.records
        ]
        merged["file_operation_event_sequences"] = [
            record.file_operation.source_event_sequence
            for record in file_operation_batch.records
        ]
        merged["file_operation_context_event_sequences"] = [
            record.context_event_sequence
            for record in file_operation_batch.records
        ]
    return merged


def _merged_context_update_ids(
    *groups: tuple[ContextUpdateId, ...],
) -> tuple[ContextUpdateId, ...]:
    merged: list[ContextUpdateId] = []
    seen: set[str] = set()
    for group in groups:
        for update_id in group:
            if update_id.value in seen:
                continue
            seen.add(update_id.value)
            merged.append(update_id)
    return tuple(merged)


def _require_invocation_conversation(
    *,
    conversation_store: SqliteConversationStore,
    workspace_id: WorkspaceId,
    agent_id: AgentId,
    conversation_id: ConversationId | None,
) -> ConversationSessionRecord | None:
    if conversation_id is None:
        return None
    record = conversation_store.get_conversation_session(conversation_id)
    if record is None:
        raise ValueError("conversation session not found.")
    conversation = record.conversation
    if conversation.workspace_id != workspace_id:
        raise ValueError("conversation workspace_id does not match workspace_id.")
    if conversation.status is ConversationStatus.ARCHIVED:
        raise ValueError("conversation is archived.")
    if conversation.agent_id is not None and conversation.agent_id != agent_id:
        raise ValueError("conversation agent_id does not match agent_id.")
    return record


def _append_invocation_conversation_messages(
    *,
    connection: sqlite3.Connection,
    conversation_store: SqliteConversationStore,
    conversation_record: ConversationSessionRecord | None,
    invocation_id: AgentInvocationId,
    agent_id: AgentId,
    instruction: str,
    result: SingleTurnPlatformRunResult,
    session_id: PlatformRunSessionId | None,
    correlation_id: str | None,
) -> PlatformInvocationConversationBatch:
    if conversation_record is None:
        return PlatformInvocationConversationBatch()

    user_message = _append_invocation_conversation_message(
        conversation_store=conversation_store,
        event_log=SqlitePlatformEventLog(connection),
        conversation_record=conversation_record,
        role=ConversationMessageRole.USER,
        content=instruction,
        created_at=result.user_context_update.created_at,
        agent_id=agent_id,
        invocation_id=invocation_id,
        context_update_id=result.user_context_update.update_id,
        session_id=session_id,
        correlation_id=correlation_id,
        metadata={
            "source": "platform_invocation_runtime_handler",
            "message_source": "user_instruction",
        },
    )
    assistant_message = _append_invocation_conversation_message(
        conversation_store=conversation_store,
        event_log=SqlitePlatformEventLog(connection),
        conversation_record=conversation_record,
        role=ConversationMessageRole.ASSISTANT,
        content=(
            result.invocation_result.output_text
            or result.invocation_result.summary
        ),
        created_at=result.invocation_result.completed_at,
        agent_id=agent_id,
        invocation_id=invocation_id,
        context_update_id=None,
        session_id=session_id,
        correlation_id=correlation_id,
        metadata={
            "source": "platform_invocation_runtime_handler",
            "message_source": "invocation_result",
            "invocation_status": result.invocation_result.status.value,
        },
    )
    return PlatformInvocationConversationBatch(
        conversation=conversation_record,
        records=(user_message, assistant_message),
    )


def _append_invocation_conversation_message(
    *,
    conversation_store: SqliteConversationStore,
    event_log: SqlitePlatformEventLog,
    conversation_record: ConversationSessionRecord,
    role: ConversationMessageRole,
    content: str,
    created_at: datetime,
    agent_id: AgentId,
    invocation_id: AgentInvocationId,
    context_update_id: ContextUpdateId | None,
    session_id: PlatformRunSessionId | None,
    correlation_id: str | None,
    metadata: Mapping[str, object],
) -> ConversationMessageRecord:
    conversation = conversation_record.conversation
    message = ConversationMessage.create(
        conversation_id=conversation.conversation_id,
        workspace_id=conversation.workspace_id,
        sequence=conversation_store.next_conversation_message_sequence(
            conversation.conversation_id
        ),
        role=role,
        content=content,
        created_at=created_at,
        agent_id=agent_id,
        invocation_id=invocation_id,
        context_update_id=context_update_id,
        run_session_id=session_id,
        metadata=dict(metadata),
    )
    event_sequence = event_log.append(
        PlatformEventRecord.create(
            workspace_id=message.workspace_id,
            session_id=message.run_session_id,
            event_kind=PlatformEventKind.CONVERSATION_MESSAGE_APPENDED,
            aggregate_type="conversation_message",
            aggregate_id=message.message_id.value,
            occurred_at=created_at,
            correlation_id=correlation_id,
            payload={
                "action": "appended",
                "message_id": message.message_id.value,
                "conversation_id": message.conversation_id.value,
                "workspace_id": message.workspace_id.value,
                "sequence": message.sequence,
                "role": message.role.value,
                "agent_id": message.agent_id.value,
                "invocation_id": message.invocation_id.value,
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
            },
            metadata={"source": "platform_invocation_runtime_handler"},
        )
    )
    conversation_store.append_conversation_message(
        message=message,
        source_event_sequence=event_sequence,
    )
    record = conversation_store.get_conversation_message(message.message_id)
    assert record is not None
    return record


def _run_result_payload(
    result: SingleTurnPlatformRunResult,
    *,
    file_operation_batch: PlatformInvocationFileOperationBatch,
    conversation_batch: PlatformInvocationConversationBatch,
) -> Mapping[str, object]:
    output_payload = dict(result.invocation_result.output_payload)
    result_metadata = dict(result.invocation_result.metadata)
    file_operation_payloads = tuple(
        _file_operation_record_payload(record)
        for record in file_operation_batch.records
    )
    conversation_message_payloads = tuple(
        _conversation_message_record_payload(record)
        for record in conversation_batch.records
    )
    invocation_result_payload = _invocation_result_payload(result.invocation_result)
    if file_operation_payloads:
        invocation_output_payload = dict(invocation_result_payload["outputPayload"])
        invocation_output_payload["tool_invoked"] = True
        invocation_output_payload["file_operations"] = list(file_operation_payloads)
        invocation_result_payload["outputPayload"] = invocation_output_payload
    return {
        "workspaceId": result.context.workspace_id.value,
        "agentId": result.invocation_result.agent_id.value,
        "contextId": result.context.context_id.value,
        "runtimeLoaded": True,
        "modelInvoked": output_payload.get("model_invoked") is True,
        "toolInvoked": (
            bool(file_operation_payloads)
            or output_payload.get("tool_invoked") is True
        ),
        "deterministicPlaceholder": (
            result_metadata.get("deterministic_placeholder") is True
        ),
        "sourceEventSequence": result.recorded_context_update.source_event_sequence,
        "agentInvocationEventSequence": result.agent_invocation_event_sequence,
        "materializedState": dict(result.context.materialized_state),
        "userContextUpdate": _context_update_payload(result.user_context_update),
        "invocationResult": invocation_result_payload,
        "fileOperations": list(file_operation_payloads),
        "conversation": (
            _conversation_session_record_payload(conversation_batch.conversation)
            if conversation_batch.conversation is not None
            else None
        ),
        "conversationMessages": list(conversation_message_payloads),
        "runSessionEventSequences": {
            "started": result.run_session_started_event_sequence,
            "terminal": result.run_session_terminal_event_sequence,
        },
    }


def _file_operation_record_payload(
    record: PlatformInvocationFileOperationRecord,
) -> Mapping[str, object | None]:
    result = record.file_operation.result
    file_operation_state = record.context_update.payload.get("file_operation", {})
    output_payload: object = {}
    if isinstance(file_operation_state, Mapping):
        output_payload = file_operation_state.get("output_payload", {})
    return {
        "operationId": result.operation_id.value,
        "workspaceId": result.workspace_id.value,
        "operationKind": result.operation_kind.value,
        "relativePath": result.relative_path,
        "status": result.status.value,
        "sourceEventSequence": record.file_operation.source_event_sequence,
        "contextUpdateId": record.context_update.update_id.value,
        "contextEventSequence": record.context_event_sequence,
        "bytesRead": result.bytes_read,
        "bytesWritten": result.bytes_written,
        "errorMessage": result.error_message,
        "outputPayload": dict(output_payload) if isinstance(output_payload, Mapping) else {},
    }


def _conversation_session_record_payload(
    record: ConversationSessionRecord,
) -> Mapping[str, object | None]:
    conversation = record.conversation
    return {
        "conversationId": conversation.conversation_id.value,
        "workspaceId": conversation.workspace_id.value,
        "agentId": (
            conversation.agent_id.value
            if conversation.agent_id is not None
            else None
        ),
        "sourceEventSequence": record.source_event_sequence,
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


def _conversation_message_record_payload(
    record: ConversationMessageRecord,
) -> Mapping[str, object | None]:
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


def _context_update_payload(update: ContextUpdateInfo) -> Mapping[str, object]:
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


def _invocation_result_payload(result: AgentInvocationResult) -> Mapping[str, object]:
    return {
        "invocationId": result.invocation_id.value,
        "workspaceId": result.workspace_id.value,
        "agentId": result.agent_id.value,
        "status": result.status.value,
        "summary": result.summary,
        "completedAt": _datetime_text(result.completed_at),
        "outputText": result.output_text,
        "errorMessage": result.error_message,
        "outputPayload": dict(result.output_payload),
        "contextUpdateIds": [
            update_id.value for update_id in result.context_update_ids
        ],
        "metadata": dict(result.metadata),
    }


def _datetime_text(value: datetime) -> str:
    return value.isoformat()


def _datetime_from_text(value: str | None, logical_name: str) -> datetime | None:
    if value is None:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            f"platform invocation payload field '{logical_name}' must be an ISO datetime."
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _agent_invocation_id(value: str | None) -> AgentInvocationId | None:
    return AgentInvocationId(value) if value is not None else None


def _task_id(value: str | None) -> TaskId | None:
    return TaskId(value) if value is not None else None


def _context_update_id(value: str | None) -> ContextUpdateId | None:
    return ContextUpdateId(value) if value is not None else None


def _conversation_id(value: str | None) -> ConversationId | None:
    return ConversationId(value) if value is not None else None


def _file_operation_id(value: str | None) -> FileOperationId | None:
    return FileOperationId(value) if value is not None else None


def _platform_event_id(value: str | None) -> PlatformEventId | None:
    return PlatformEventId(value) if value is not None else None


def _platform_run_session_id(value: str | None) -> PlatformRunSessionId | None:
    return PlatformRunSessionId(value) if value is not None else None


def _optional_payload_text(
    payload: Mapping[str, object],
    logical_name: str,
    *field_names: str,
) -> str | None:
    for field_name in field_names:
        if field_name not in payload:
            continue
        value = payload[field_name]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"platform invocation payload field '{logical_name}' must be a non-empty string."
            )
        return value.strip()
    return None


def _optional_payload_mapping(
    payload: Mapping[str, object],
    logical_name: str,
    *field_names: str,
) -> Mapping[str, object]:
    for field_name in field_names:
        if field_name not in payload:
            continue
        value = payload[field_name]
        if not isinstance(value, Mapping):
            raise ValueError(
                f"platform invocation payload field '{logical_name}' must be an object."
            )
        return dict(value)
    return {}


def _optional_payload_bool(
    payload: Mapping[str, object],
    logical_name: str,
    *field_names: str,
) -> bool:
    for field_name in field_names:
        if field_name not in payload:
            continue
        value = payload[field_name]
        if not isinstance(value, bool):
            raise ValueError(
                f"platform invocation payload field '{logical_name}' must be a boolean."
            )
        return value
    return False
