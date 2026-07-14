# Invocation Main Chain

Status: current developer note for macro steps 1, 4.5, 4.6, 5.2, 6.2, 7, and 12.

## Purpose

This note records how to execute one model-agnostic local platform invocation
through the current Python main chain.

The current chain is:

```text
local composition, local application/command entrypoint, local payload entrypoint, opt-in Gateway adapter, or contract-first Gateway /api/v1 route
  -> Python invocation runtime handler
  -> invocation request preflight
  -> optional explicit controlled file operations
  -> persisted workspace/context/agent state
  -> deterministic single-turn runtime
  -> context update event
  -> optional requested agent invocation audit record
  -> agent adapter invocation
  -> optional terminal agent invocation audit record
  -> optional conversation message history linkage
  -> stable response payload
```

## Available Entrypoints

### Local Runtime Command

Use the 6.2 command entrypoint for an executable non-UI backend smoke flow:

```powershell
$env:PYTHONPATH='src'
py -3.11 -m agent_os.local_runtime `
  --database platform.sqlite3 `
  --workspace-root X:/fixture/workspace `
  --plugins-directory X:/fixture/plugins `
  smoke
```

The smoke command initializes SQLite, creates an invocation-ready workspace
baseline, runs one deterministic single-turn invocation, then queries context,
invocation records, file operation records, and the run-session timeline. It
prints JSON and does not enable Gateway, real providers, UI, or `write_file`.

### Local HTTP API Contract

Macro step 7 adds Gateway `/api/v1` platform routes for workspace, context,
agent, invocation, record, session, connection, and binding resources. These
routes are contract-first and use `LocalPlatformApiAdapter`.

The default Gateway adapter is not connected to Python, so the route surface is
ready for UI/API contract work but does not execute the Python runtime until a
later bridge task connects it.

### Local Payload

Use `handle_local_platform_invocation_payload` when a local caller has a seeded
SQLite database path and wants to execute one invocation payload:

```python
from agent_os.application.services import handle_local_platform_invocation_payload

response = handle_local_platform_invocation_payload(
    "platform.sqlite3",
    {
        "workspaceId": "workspace-1",
        "agentId": "agent-1",
        "instruction": "Capture this local task.",
        "invocationId": "invoke-local-1",
        "requestedAt": "2026-06-04T06:30:00Z",
        "userContextUpdateId": "update-local-1",
    },
)
```

The database must already contain a compatible workspace, shared context, and
agent registration. After macro step 6.1, local callers can create that baseline
through `components.operations().create_workspace(...)` before invoking. Tests can use
`tests.support.platform_invocation_fixtures.seed_minimal_invocation_platform_database`
for a minimal smoke database.

When the payload contains explicit `fileOperations` or `file_operations`, this
entrypoint uses the same controlled file-operation path as the local composition
root.

When the payload contains `conversationId`, the runtime validates the local
conversation session before side effects. After the invocation completes, it
persists linked user and assistant messages. The user message links to the user
context update; both messages link to the invocation and optional run session.
Without `conversationId`, behavior remains unchanged.

### Gateway Envelope

The default Gateway entrypoint still returns the existing not-wired response.
To execute the Python runtime, pass the opt-in SQLite bridge through the
existing adapter boundary:

```python
import sqlite3

from agent_os.application.services import (
    PLATFORM_SINGLE_TURN_INVOCATION_KIND,
    SqlitePlatformInvocationGatewayRuntimeBridge,
    handle_platform_invocation_gateway_envelope,
)

connection = sqlite3.connect("platform.sqlite3")
bridge = SqlitePlatformInvocationGatewayRuntimeBridge(connection)

response = handle_platform_invocation_gateway_envelope(
    {
        "protocolVersion": "1.0",
        "requestId": "request-1",
        "kind": PLATFORM_SINGLE_TURN_INVOCATION_KIND,
        "payload": {
            "workspaceId": "workspace-1",
            "agentId": "agent-1",
            "instruction": "Capture this task.",
            "invocationId": "invoke-1",
            "requestedAt": "2026-06-04T05:05:44Z",
            "userContextUpdateId": "update-user-1",
        },
        "metadata": {"correlation_id": "corr-1"},
    },
    adapter=bridge,
)
```

The opt-in SQLite bridge accepts the same explicit `fileOperations` payload
shape as the local runtime. The default Gateway adapter behavior remains
unchanged, and this bridge does not create a new HTTP route.

## Runtime Hardening

Macro step 4.6 adds these local runtime guardrails:

- local composition and path-based local entrypoints share the same SQLite
  connection policy;
- connection-level foreign-key enforcement is enabled independently from schema
  initialization;
- `idempotencyKey` requires invocation audit recording, because the current
  idempotency check is backed by persisted invocation records;
- the single-turn runtime records the user-message context update before calling
  the agent adapter;
- when invocation recording is enabled, the runtime records a requested
  invocation event before adapter execution and a terminal invocation event
  after adapter completion or adapter failure.

For the no-file success path, the normal event order is now:

```text
1. context.update_appended
2. agent_invocation.recorded  # requested
3. agent_invocation.recorded  # succeeded/failed terminal result
```

For explicit successful file operations, file-operation audit and file-reference
context events still occur before the user-message context event. Failed file
operations keep their step 4.5 behavior: a failed file-operation audit record is
written and the flow stops before user-message context or invocation records.

## Response Contract

The runtime handler exports these field sets:

- `PLATFORM_INVOCATION_RESPONSE_FIELDS`
- `PLATFORM_INVOCATION_USER_CONTEXT_UPDATE_FIELDS`
- `PLATFORM_INVOCATION_RESULT_FIELDS`

The top-level response uses camelCase fields. `agentInvocationEventSequence`
is nullable when agent invocation recording is disabled. `modelInvoked` remains
`False` in the current deterministic placeholder runtime. `toolInvoked` is
`True` only when explicit controlled file operations are requested.

When file operations are requested, the response includes top-level
`fileOperations` summaries. `invocationResult.contextUpdateIds` remains the
deterministic user-message update id list; file-reference update ids are exposed
through `fileOperations` and persisted invocation request metadata.

When `conversationId` is requested and validated, the response includes:

- `conversation`: the local conversation session summary;
- `conversationMessages`: the user and assistant message records appended for
  this invocation.

Gateway TypeScript DTOs express the same request/response field families at
source level, including `fileOperations`, `conversationId`, `conversation`,
`conversationMessages`, `runtimeLoaded`, `modelInvoked`, `toolInvoked`, and
`deterministicPlaceholder`. The request-side
`fileOperations.operationKind` contract is intentionally limited to the
currently executable read-file and list-directory operations. The Gateway route
remains a 501 not-wired route until a later explicit API wiring step.

Macro step 5.2 adds separate Gateway source-level DTOs for later local operation
API wrapping in
`gateway/src/application/dto/local-platform-operation-response.ts`. Those DTOs
cover workspace/context/agent/task/issue current state, run-session timelines,
agent invocation records, and file operation records. They do not enable any
route.

## Verification Commands

Run from `python-core`:

```powershell
$env:PYTHONPATH='src'
py -3.11 -m unittest tests.test_platform_invocation_runtime_handler tests.test_platform_invocation_gateway_bridge tests.test_platform_invocation_local_entrypoint tests.test_local_platform_application tests.test_local_runtime_entrypoint
py -3.11 -m unittest tests.test_platform_invocation_runtime_handler tests.test_platform_invocation_local_entrypoint tests.test_platform_invocation_gateway_bridge tests.test_platform_invocation_gateway_entrypoint tests.test_platform_invocation_gateway_transport tests.test_platform_invocation_gateway_handler tests.test_local_single_turn_use_case_composition tests.test_local_single_turn_platform_use_case tests.test_single_turn_runtime_composition tests.test_single_turn_platform_runtime
py -3.11 -m unittest discover -s tests
```

## Current Limits

- The runtime returns a deterministic placeholder result.
- No real model provider is called.
- Controlled local file operations are available only through explicit payload
  requests across the local composition root, local payload entrypoint, and
  opt-in Gateway bridge; no autonomous tool planning is performed.
- The local database must contain workspace, context, and agent state before
  invocation. This can now be created through the Python-local operation service
  lifecycle path.
- The Gateway runtime bridge is opt-in; default Gateway behavior is unchanged.
- A dedicated workspace, context, agent, invocation, record, session,
  conversation, connection, and binding HTTP API contract now exists under
  `/api/v1`, but the default Gateway adapter remains not connected to Python.
- Run-session timelines, invocation records, and file operation records are
  queryable through the Python local operation service, local runtime command,
  and explicit Gateway `python_cli` bridge.
- Conversation sessions and messages are queryable through the Python local
  operation service, local runtime command, and explicit Gateway `python_cli`
  bridge.
- Full run-session persistence and recovery APIs are still deferred; 5.2 uses
  event-log session timelines and audit record queries as the local read
  boundary.
- This note does not define UI, service hosting, or packaging behavior.
