# Local Operation Surface

Status: current developer note for macro steps 5.1, 5.2, 6.1, 6.2, 7, 8.2,
9, 10, 11, 12, 22.3, 23, 24, and 24.1.

## Purpose

The local operation surface is an API-wrap-ready service over persisted platform
state. It gives local callers a stable backend-facing shape for common platform
operations without enabling HTTP routes by default, UI, or desktop packaging.
Provider-backed invocation is available only through explicit local runtime
configuration.

Macro step 11 adds an explicit local agent-registration creation path and
Agent Runtime Profile metadata. This lets the same configured provider/model
connection host multiple workspace-scoped agents with separate role names,
system prompts, generation options, and reserved reasoning/runtime metadata.
Profiles are metadata and invocation-binding inputs; they are not credential
stores or chat-history sessions.

Macro step 12 adds local conversation-session operations. These operations
persist workspace-scoped chat-like message history and optional invocation
links without implementing UI, remote conversation instances, credential
persistence, or automatic long-history provider injection.

Macro step 13 adds provider API shape configuration for explicit provider-backed
invocation. The local runtime can express and execute OpenAI-compatible Chat
Completions, Anthropic Messages, Gemini generateContent, and Ollama native
`/api/chat` through provider-neutral adapters. It does not add credential
persistence or remote model discovery.

Macro step 22.3 adds advisory project-directory coordination records for
multi-agent workspace-root collaboration. These records capture declared path
scopes, access intent, overlap status, git provenance summaries, and handoff
notes. They are not filesystem locks, git automation, file-body readers, or
real runtime connectors.

Macro step 23 adds directed agent exchange request records for CLI-capable
advanced-agent information exchange. These records capture source/target agent
ids, request kind, short request/response summaries, optional detail refs,
authorization mode, sub-request policy, and parent/root/thread metadata. They
are not runtime connectors, auto-wake mechanisms, provider prompt injection, or
shared-context auto-append paths.

Macro step 24 adds local request threads over the request board. Threads link
related single-target requests, enforce finite-turn budgets, track active and
completed interactions, apply participants-only or workspace-readable
visibility, and support single-target follow-up requests. They are local
interaction contexts, not workspaces, shared context, file/tool permission
scopes, memory namespaces, runtime connectors, auto-wake mechanisms, or
background discussion schedulers.

Macro step 24.1 adds `../agent/agent_cli_onboarding.md` as the practical
agent-facing CLI onboarding guide for Codex, Claude Code, or another
CLI-capable agent. It documents the existing local operation surface and adds
no operation, route, schema, runtime connector, auto-wake path, or UI.

The current path is:

```text
LocalPlatformSettings
  -> build_local_platform_runtime
  -> LocalPlatformRuntimeComponents.operations()
  -> LocalPlatformOperationService
  -> SQLite current-state readers/writers, event log, audit record readers, and context update recorder
  -> optional LocalPlatformApplication / python -m local_runtime wrapper
  -> contract-first Gateway /api/v1 adapter boundary
```

## Read Operations

`LocalPlatformOperationService` exposes current-state reads as JSON-compatible
payload mappings:

- `list_workspaces()`
- `get_workspace(workspace_id)`
- `get_context(workspace_id)`
- `list_agent_registrations(workspace_id)`
- `get_agent_registration(agent_id)`
- `list_conversations(workspace_id)`
- `get_conversation(workspace_id, conversation_id)`
- `list_conversation_messages(workspace_id, conversation_id, limit, offset)`
- `list_tasks(workspace_id)`
- `get_task(task_id)`
- `list_issues(workspace_id)`
- `get_issue(issue_id)`
- `get_run_session_timeline(workspace_id, session_id)`
- `list_agent_invocation_records(workspace_id, filters...)`
- `get_agent_invocation_record(invocation_id)`
- `get_agent_invocation_record_by_idempotency_key(workspace_id, idempotency_key)`
- `list_file_operation_records(workspace_id, filters...)`
- `get_file_operation_record(operation_id)`
- `project_directory_coordination_instructions(workspace_id)`
- `get_project_directory_coordination_status(workspace_id, directory_coordination_id)`
- `list_project_directory_coordination(workspace_id)`
- `agent_exchange_request_instructions(workspace_id)`
- `get_agent_exchange_request_policy(workspace_id)`
- `list_agent_exchange_requests(workspace_id, filters...)`
- `get_agent_exchange_request_status(workspace_id, exchange_request_id)`
- `agent_exchange_thread_instructions(workspace_id)`
- `list_agent_exchange_threads(workspace_id, filters...)`
- `get_agent_exchange_thread_status(workspace_id, thread_id, requesting_agent_id)`
- `list_agent_exchange_thread_requests(workspace_id, thread_id, requesting_agent_id)`

List operations are ordered by stable ids in the persistence layer, so later API
wrappers can preserve deterministic response ordering without adding sorting at
the route boundary.

Missing records return `None` for single-record reads and an empty list for
workspace-scoped list reads. Invalid empty identifiers are rejected by the same
identifier/value-object path used by existing persistence readers.

## Workspace Lifecycle

Macro step 6.1 adds explicit workspace lifecycle operations to the Python-local
operation service:

- `create_workspace(...)`
- `open_workspace(workspace_id)`
- `archive_workspace(workspace_id)`
- `ensure_workspace_baseline(workspace_id, ...)`
- `create_agent_registration(...)`
- `create_conversation(...)`
- `archive_conversation(...)`
- `append_conversation_message(...)`
- `declare_project_directory_coordination(...)`
- `update_project_directory_coordination(...)`
- `complete_project_directory_coordination(...)`
- `update_agent_exchange_request_policy(...)`
- `create_agent_exchange_request(...)`
- `respond_agent_exchange_request(...)`
- `close_agent_exchange_request(...)`
- `create_agent_exchange_thread_follow_up(...)`
- `update_agent_exchange_thread_visibility(...)`
- `close_agent_exchange_thread(...)`

`create_workspace(...)` can run against an initialized empty SQLite database. It
creates the workspace current state, appends a `workspace.changed` event, then
ensures a minimal shared context and deterministic default agent registration.
If caller ids are not supplied, the baseline ids are deterministic:

- `context-<workspace_id>`
- `agent-<workspace_id>`

Example:

```python
components = build_local_platform_runtime(settings)
try:
    operations = components.operations()
    created = operations.create_workspace(
        workspace_id="workspace-1",
        display_name="Workspace",
        root_path="X:/fixture/workspace",
    )
    opened = operations.open_workspace("workspace-1")
finally:
    components.close()
```

`open_workspace(...)` returns a workspace overview containing workspace,
context, agents, tasks, and issues. Unknown workspaces raise a clear error.
Archived workspaces remain queryable through `get_workspace(...)` and
`list_workspaces()`, but `open_workspace(...)` rejects them because they are not
valid active invocation targets.

`archive_workspace(...)` records a `workspace.changed` event, marks current state
as archived, and preserves context, invocation records, file-operation records,
and event history. Re-archiving an already archived workspace is idempotent and
does not append another archive event.

`ensure_workspace_baseline(...)` is explicit and idempotent. It can add a
missing shared context and deterministic agent registration to an existing
active workspace. Context baseline creation currently writes current state
without a dedicated replayable context-created event; full replayable baseline
eventing remains a later recovery-hardening task.

`create_agent_registration(...)` appends an `agent_registration.changed` event
and stores a workspace-scoped agent state. It accepts optional capabilities,
tool permissions, metadata, and `runtime_config`. Runtime profile config is
validated before persistence, including rejection of inline credential values.
In explicit provider mode the invocation composition uses this profile to
override the agent system prompt and generation options inside the configured
provider/model boundary.

## Run State

`get_run_session_timeline(workspace_id, session_id)` returns a local read model
over `platform_events.session_id`. Session-bound invocations through the
SQLite single-turn runtime now append explicit `run_session.changed` lifecycle
events for `running` and terminal status.

The response contains:

- `session`: workspace id, session id, inferred status, event count, first/last
  sequence, first/last event time, and lifecycle recovery summary.
- `events`: ordered event-log entries for that workspace/session pair.

Status is inferred from the latest `run_session.changed` event that contains a
status payload. If no such status exists but events are present, the status is
`observed`. Empty timelines return `unknown`.

The `session.lifecycle` summary indicates whether explicit lifecycle events are
present, whether the session is currently open or closed, the lifecycle event
sequence numbers, and counts for invocation, context-update, and file-operation
events. This is a local recovery aid; crash-safe pending operation repair
remains deferred.

## Conversation Sessions

Conversation sessions are local durable message threads. They are separate from
`PlatformRunSession` lifecycle records and from canonical `ProjectSharedContext`
updates.

The operation service exposes:

- `create_conversation(...)`
- `list_conversations(workspace_id)`
- `get_conversation(workspace_id, conversation_id)`
- `archive_conversation(workspace_id, conversation_id)`
- `append_conversation_message(...)`
- `list_conversation_messages(workspace_id, conversation_id, limit, offset)`

Messages are append-only and can carry optional `agentId`, `invocationId`,
`contextUpdateId`, and `runSessionId` links. Invocation-linked messages are
created only when the invocation payload explicitly includes `conversationId`.
The default invocation path remains unchanged.

## Invocation Records

Agent invocation audit records are queryable through the local operation
service:

- by invocation id;
- by workspace-scoped idempotency key;
- by workspace list with optional status, agent id, task id, and idempotency
  key filters.

The payload exposes requested and terminal record state, including final
`status`, request/result snapshots, context update ids, file references,
timestamps, and source event sequence.

## File Operation Records

File operation audit records are queryable through the local operation service:

- by operation id;
- by workspace list with optional status, operation kind, invocation id, task id,
  and requested-by agent id filters.

The payload is audit-safe. It returns file operation metadata, result status,
byte counts, context update linkage, and redacted output payloads. The service
defensively omits `content` fields from returned mappings.

## Context Append

`append_context_update(...)` remains the explicit caller-driven context write
path:

```python
result = components.operations().append_context_update(
    "workspace-1",
    update_kind="note",
    summary="Captured local note",
    update_id="update-1",
    materialized_state_patch={"latest_note": "Captured local note"},
    event_id="event-1",
)
```

The method reads the current materialized context first, appends a
`ContextUpdateInfo` event, updates materialized context state through the
existing SQLite recorder, and returns:

- `contextUpdate`: the appended update payload.
- `context`: the updated current context payload.
- `sourceEventSequence`: the persisted event-log sequence.

The recorder now accepts an optional persisted base update count. This preserves
the materialized context's stored `update_count` when the in-memory seed context
does not already contain every historical update item.

## Composition

The operation service is exposed through the local composition root:

```python
from agent_os.infrastructure.composition.local_platform import (
    build_local_platform_runtime,
)

components = build_local_platform_runtime(settings, initial_state=initial_state)
try:
    operations = components.operations()
    workspaces = operations.list_workspaces()
    context = operations.get_context("workspace-1")
finally:
    components.close()
```

`build_local_platform_operation_service(connection)` is also available for tests
and local callers that already own an initialized SQLite connection.

Macro step 6.2 adds `LocalPlatformApplication` as a stable local application
facade over this surface, plus `python -m agent_os.local_runtime` for JSON
command output. The command exposes operation-surface reads and explicit writes
without requiring callers to import SQLite stores or the composition root.

Macro step 7 adds Gateway DTOs and `/api/v1` routes around this surface through
`LocalPlatformApiAdapter`. The default Gateway adapter is contract-only and does
not call Python. This gives future UI/API work a stable route contract before
the real bridge is connected.

Macro step 8.2 adds an explicit `python_cli` Gateway adapter that calls the
Python local runtime entrypoint. In that mode, the `/api/v1` workspace,
context, agent list, invocation, record, file-operation record, and session
timeline routes are backed by this operation surface through
`LocalPlatformApplication` / `python -m agent_os.local_runtime`.

Macro step 9 keeps the Gateway bridge local-only and exposes the lifecycle
summary through the same session timeline route. It does not add a daemon,
product account system, LAN/public API exposure, real provider, or UI shell.

Macro step 10 adds an explicit OpenAI-compatible provider adapter behind the
provider-neutral model boundary. The default operation path remains
deterministic; the provider-backed path is validated by local fake-provider
tests and reads credentials only from a configured process environment
variable. It does not add provider credential storage or provider connection
persistence.

Macro step 11 adds profile-aware agent creation to the same surface and wires
profile resolution into provider-backed invocation. Gateway `python_cli` mode
can call the `agent-create` command through `POST
/api/v1/workspaces/:workspaceId/agents`.

Macro step 12 adds conversation commands to `LocalPlatformApplication` and
`python -m agent_os.local_runtime`, plus `/api/v1` conversation routes in
Gateway `python_cli` mode.

Macro step 13 adds a generic `provider-api-shape` local runtime mode. This is a
Python-local configuration path, not a new operation-surface write/read method.
Gateway routes are unchanged in this step.

Macro step 14 wires the existing Gateway `python_cli` bridge to the Python-local
`provider-api-shape` mode through an explicit allowlist. This still does not add
new operation-surface methods or provider credential persistence; it only lets
the existing invocation route call configured provider shapes when the bridge
and agent adapter mode are both explicitly enabled.

Macro step 14.1 adds explicit OpenAI Responses input-mode passthrough for relay
compatibility. This remains provider configuration for the existing invocation
path, not a new operation-surface method, context-compression engine, or remote
conversation connector.

Macro step 14.2 adds explicit provider HTTP `User-Agent` passthrough for
relay/provider compatibility. This remains a validated single-header provider
configuration option on the existing invocation path, not an arbitrary header
injection surface, credential configuration mechanism, context-management
profile, or new operation-surface method.

Macro step 22.3 adds project directory coordination methods to the same local
operation surface. They append and rebuild
`project_directory_coordination.changed` events over the existing event log.
Overlap is calculated from declared path scopes with conservative prefix
matching only; the service does not read directories, load file bodies, execute
git commands, mutate the worktree, or enforce OS-level permissions.

Macro step 23 adds directed exchange request methods to the same local
operation surface. They append and rebuild `agent_exchange_request.changed`
events, and store workspace policy changes as
`agent_exchange_request_policy.changed` events. The default policy is
`direct_allowed` plus `subRequestPolicy=allowed`. A stricter
`delegated_grant_required` policy validates a matching delegated wake grant
link without consuming the grant or waking the target agent. Requests and
responses remain local records and are not automatically appended to shared
context.

## Current Limits

- Gateway `/api/v1` routes are contract-first and not connected to Python by
  default. Explicit `python_cli` mode connects them to Python-local runtime.
- Provider-backed invocation is explicit opt-in. Default local operations do
  not perform provider network calls.
- Gateway `python_cli` mode can explicitly pass allowlisted provider API shape
  configuration to Python-local runtime; contract-only and deterministic
  placeholder remain the defaults.
- OpenAI Responses-compatible relays can opt into `plain_text` input mode
  through provider configuration when they reject official structured Responses
  input.
- Provider HTTP `User-Agent` can be set explicitly for provider/relay
  compatibility. No arbitrary provider HTTP headers can be configured.
- Executable provider API shapes currently include OpenAI-compatible Chat
  Completions, OpenAI Responses, Anthropic Messages, Gemini generateContent,
  and Ollama native `/api/chat`.
- OpenAI Responses is a minimal text-generation adapter only; streaming, tools,
  remote conversation state, and automatic capability discovery remain
  deferred.
- Azure OpenAI is reserved but not an executable adapter yet.
- Remote model discovery is not implemented; model listing is configured/static.
- Provider keys are not stored in SQLite, logs, Gateway config, or repository
  files.
- Agent runtime profiles reject inline credential values and only preserve
  provider/model/profile/options metadata.
- Current `sessionId` handling is lifecycle/audit-oriented. `conversationId` is
  the durable local message-thread boundary.
- Conversation history is persisted and queryable, but it is not automatically
  injected into provider prompts as full long-history context.
- Remote conversation instances remain deferred.
- LocalAI/arbitrary HTTP providers remain unconnected.
- No UI or desktop shell is introduced.
- Controlled file operations remain on their existing explicit invocation path.
- Write file operations remain disabled by policy.
- Run-session timeline, invocation-record, and file-operation-record query
  surfaces are available through the Python local operation service and the
  6.2 local application/command entrypoint.
- Session-bound single-turn invocations append run-session lifecycle events.
  Crash-safe long-running session recovery and pending-operation repair remain
  deferred.
- A formal non-UI local application facade, `python -m` command, and end-to-end
  local smoke command now exist. Daemon/service hosting, HTTP API, UI, desktop
  shell, and packaging remain deferred.
- Task/issue mutation operations remain deferred.
- Full replayable eventing for context baseline creation remains deferred.
- Project directory coordination is advisory only. It cannot prevent external
  agents with local filesystem or shell access from bypassing the platform.
- Directed exchange requests are local request-board records only. They do not
  connect or wake target agents, do not execute provider calls, do not read
  file bodies, and do not automatically write request/response text to shared
  context.

## Verification Commands

Run from `python-core`:

```powershell
$env:PYTHONPATH='src'
py -3.11 -m unittest tests.test_conversation_domain tests.test_conversation_store tests.test_local_platform_operations tests.test_local_platform_composition tests.test_local_platform_application tests.test_local_runtime_entrypoint
py -3.11 -m unittest tests.test_platform_event_log tests.test_agent_invocation_record_store tests.test_file_operation_record_store
py -3.11 -m unittest tests.test_workspace_state_store tests.test_agent_registration_state_store tests.test_task_state_store tests.test_issue_state_store
py -3.11 -m unittest discover -s tests
```
