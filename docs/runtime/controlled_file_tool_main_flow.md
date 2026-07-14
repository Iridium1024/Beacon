# Controlled File Tool Main Flow

Status: current developer note for macro steps 4, 4.5, and 4.6.

## Purpose

This note records the current model-agnostic local invocation path for explicit
workspace file operations.

The current API-facing local backend chain is:

```text
local composition, local payload entrypoint, or opt-in Gateway bridge
  -> explicit fileOperations request
  -> invocation request preflight
  -> workspace policy and sandbox request factory
  -> workspace filesystem adapter
  -> file-operation audit event
  -> redacted file-reference context update
  -> user-message context update
  -> optional requested agent invocation audit record
  -> optional terminal agent invocation audit record
  -> stable response payload
```

File operations are never planned autonomously by the agent. They run only when
the caller includes an explicit `fileOperations` or `file_operations` array in
the local invocation payload.

Macro step 4.5 makes the supported local invocation entrypoints equivalent for
this explicit file-operation path:

- `LocalPlatformRuntimeComponents.handle_payload(...)`
- `handle_local_platform_invocation_payload(...)`
- `SqlitePlatformInvocationGatewayRuntimeBridge` through the existing Gateway
  envelope adapter boundary

This is API-wrap-ready local backend behavior. It does not add a real HTTP
route, service host, network provider call, or Gateway route expansion.

## Local Composition Entry

The local runtime exposes controlled file operations through
`LocalPlatformRuntimeComponents.workspace_file_operations(...)`:

```python
from agent_os.domain.value_objects.identifiers import FileOperationId
from agent_os.infrastructure.composition.local_platform import (
    build_local_platform_runtime,
)

components = build_local_platform_runtime(settings, initial_state=initial_state)
try:
    recorded = components.workspace_file_operations("workspace-1").read_file(
        operation_id=FileOperationId("file-op-1"),
        relative_path="docs/status.md",
    )
finally:
    components.close()
```

This entry uses the persisted workspace root, a read-only binding, the existing
workspace sandbox adapter, and `SqliteFileOperationRecordStore`.

## Invocation Payload

Minimal explicit read-file payload:

```python
response = components.handle_payload(
    {
        "workspaceId": "workspace-1",
        "agentId": "agent-1",
        "instruction": "Run with a controlled file reference.",
        "invocationId": "invoke-1",
        "userContextUpdateId": "update-user-1",
        "fileOperations": [
            {
                "operationKind": "read_file",
                "relativePath": "docs/status.md",
                "operationId": "file-op-1",
                "contextUpdateId": "update-file-ref-1",
            }
        ],
    }
)
```

The same payload shape is accepted by the local composition root, the local
payload entrypoint, and the opt-in SQLite Gateway bridge.

Supported operation kinds:

- `read_file`
- `list_directory`

Currently rejected before execution:

- `write_file`
- recursive directory listing
- duplicate explicit operation/event/context ids inside one payload
- malformed file operation objects

Path validation remains workspace-relative. Absolute paths, parent segments,
empty path segments, and current-directory path segments are rejected before
execution.

## Preflight, Audit, And Context

Before any file-operation side effect, the invocation runtime validates the
workspace, context, agent registration, requested capability, invocation
identity, metadata shape, context references, file references, and duplicate
explicit operation/event/context ids.

Preflight failures create no file-operation records, no platform events, no
context updates, and no agent invocation records. After preflight succeeds, a
file execution failure records a failed file-operation audit event and stops
before creating user-message context updates or agent invocation records.

For each successful file operation:

1. A `file_operation.recorded` platform event is inserted.
2. An audit-safe row is upserted in `platform_file_operation_records`.
3. Read file content is not persisted in the audit row.
4. `FileOperationContextLinker` builds a redacted `file_reference` update.
5. A `context.update_appended` event persists the file reference.
6. The user-message context update runs on the updated context snapshot.
7. The agent invocation record links file-reference context update ids and the
   final user-message update id.

Failed or denied file operations do not create successful context updates and
do not continue into the user-message invocation event.

After macro step 4.6, successful invocation flows with audit recording enabled
write a requested invocation audit event before adapter execution and a terminal
invocation audit event after adapter completion. File-operation failures still
stop before these invocation audit events.

## Response Fields

The top-level local invocation response includes `fileOperations`.

Each file operation summary contains:

- `operationId`
- `workspaceId`
- `operationKind`
- `relativePath`
- `status`
- `sourceEventSequence`
- `contextUpdateId`
- `contextEventSequence`
- `bytesRead`
- `bytesWritten`
- `errorMessage`
- redacted `outputPayload`

`toolInvoked` is `True` when explicit file operations were executed. The
response remains provider-neutral and does not express task quality, scoring,
or adjudication.

`invocationResult.contextUpdateIds` currently reports the user-message context
update ids produced by the deterministic invocation adapter. File-reference
context update ids are exposed in top-level `fileOperations` summaries and are
linked into the persisted agent invocation request metadata.

## Current Limits

- Write operations are not enabled.
- Recursive directory listing is not enabled.
- File operations are local and synchronous.
- File operation FK columns for invocation/task are not written before those
  referenced records exist; invocation/task trace values are stored in request
  metadata and response summaries.
- Requested/terminal invocation audit events are used as the current minimal
  pending boundary; full run-session APIs remain deferred.
- Dedicated HTTP routes for file operations are not added yet. The current
  Gateway path is the opt-in invocation bridge only.
- No real provider, network call, Gateway route expansion, UI, autonomous tool
  planning, or quality judgment is added by this path.

## Verification Commands

Run from `python-core`:

```powershell
$env:PYTHONPATH='src'
py -3.11 -m unittest tests.test_local_platform_composition tests.test_platform_invocation_runtime_handler tests.test_workspace_file_operation_use_case tests.test_file_operation_context_linker
py -3.11 -m unittest tests.test_local_platform_composition tests.test_platform_invocation_runtime_handler tests.test_file_operation_record_store tests.test_context_update_event_recorder tests.test_agent_invocation_record_store
py -3.11 -m unittest discover -s tests
```
