# Conversation Session History Foundation

Status: current developer note for macro steps 12, 15, 16, 17, 18, 19, 20,
and 22.1.

## Purpose

Conversation sessions provide local, workspace-scoped chat-thread isolation for
agent invocations. They are distinct from `PlatformRunSession`:

- `ConversationSession` is a durable local thread for message history.
- `PlatformRunSession` is lifecycle/audit metadata for one runtime execution.
- `ProjectSharedContext` remains the canonical shared context store.

This foundation lets the backend preserve multiple isolated local threads per
agent without implementing UI, remote browser sessions, credential persistence,
or long-history provider injection.

## Python Runtime

The Python core now persists:

- `platform_conversation_sessions`
- `platform_conversation_messages`

Conversation messages can link to:

- `agentId`
- `invocationId`
- `contextUpdateId`
- `runSessionId`

The local operation surface and `python -m agent_os.local_runtime` expose:

```text
conversation-create
conversation-list
conversation-get
conversation-archive
conversation-message-append
conversation-messages
```

`invoke` and `invoke-json` accept optional `conversationId`. When present, the
invocation validates that the conversation belongs to the workspace, is active,
and is either unbound or bound to the invoked agent. After the invocation
completes, the runtime appends user and assistant messages linked to the
invocation, user context update, and run session.

Without `conversationId`, invocation behavior remains unchanged.

Macro step 15 adds a context-management profile foundation that can explicitly
select whether recent conversation messages are in scope for a future context
assembly plan. This is configuration and audit metadata only in the current
baseline. Conversation messages remain queryable local records; they are not
automatically copied into provider prompts.

Macro step 16 adds the authorization boundary around that future path. A
profile may allow or request `recent_messages`, but the assembly plan authorizes
that scope only when the current invocation supplies a conversation source
reference. The source reference records the conversation id for audit and keeps
`content_loaded=false`; it does not read or inject the full message history.

Macro step 17 adds metadata-only window selection over authorized source refs.
An authorized `recent_messages` conversation ref can be selected for a future
context packet, but selection still records only ids, ordering, budget hints,
and `content_loaded=false`. It does not read or render conversation messages.

Macro step 18 defines that future context packet as a contract/status layer
without loading message bodies. A selected `recent_messages` source ref now
becomes a ref-only `conversation_ref` packet item with state `not_loaded`,
estimated tokens `0`, and redaction metadata showing that conversation messages
were not loaded. Denied or omitted conversation refs enter excluded metadata
only and do not become packet items.

Macro step 19 adds bounded local materialization after the content packet. A
selected `recent_messages` packet item can produce a
`conversation_message_window` segment only when explicit sanitized local message
snapshots are supplied to the assembly request. The provider-backed adapter
currently propagates `conversation_id` for authorization/audit but does not
connect a conversation reader, so it records `loader_not_connected` for recent
messages in provider-backed invocations. This preserves the prompt boundary:
conversation history is not automatically injected into provider messages.

Macro step 20 adds runtime access and delegated-context delivery metadata after
materialization. A runtime delivery plan can reference selected materialized
segment ids only when explicitly permitted, but it still does not include
conversation text, connect a real runtime, open WebSocket transport, or inject
provider prompts. Runtime access grants therefore do not bypass the
conversation source-ref, packet, or materialization boundaries above.

Macro step 22.1 adds optional Agent Exchange attribution metadata for
conversation messages. External advanced agents that are explicitly instructed
by the user to use the local platform can append messages with a normalized
`metadata.agentExchange` block that identifies source type, author type,
contribution kind, confidence, instruction authority, review flags, and related
conversation/task/invocation refs. This metadata helps other agents distinguish
user platform messages from agent suggestions, handoff notes, conflicts, tool
observations, and external claims. It does not make another agent's output a
user directive and does not inject conversation history into provider prompts.

## Gateway API

The local `/api/v1` route surface now includes:

```text
POST /api/v1/workspaces/:workspaceId/conversations
GET  /api/v1/workspaces/:workspaceId/conversations
GET  /api/v1/workspaces/:workspaceId/conversations/:conversationId
POST /api/v1/workspaces/:workspaceId/conversations/:conversationId/archive
POST /api/v1/workspaces/:workspaceId/conversations/:conversationId/messages
GET  /api/v1/workspaces/:workspaceId/conversations/:conversationId/messages
```

The explicit `python_cli` bridge maps those routes to the Python local runtime.
The default Gateway adapter remains contract-only.

## Boundaries

- No UI or desktop shell is implemented.
- No remote conversation connector, cookie/session capture, or browser
  automation is implemented.
- No provider credential values are stored.
- No product multi-user account or ACL system is implemented.
- Conversation history is persisted and queryable, but it is not automatically
  injected as full long-history context into model provider requests.
- `recent_messages` is a context access scope plus source reference boundary,
  not an automatic history render. The context-window selection policy selects
  refs only; the content packet records selected refs and loading state; the
  materialization layer can load only explicit sanitized local snapshots and
  otherwise records `loader_not_connected`.
- Runtime access delivery plans can reference conversation-related materialized
  segment metadata only after the preceding source-ref, packet, and
  materialization checks. They do not deliver full conversation text to a real
  runtime in the current baseline.
- Agent Exchange attribution can classify conversation messages for external
  agents, but it is metadata-only. It does not connect a real runtime, start an
  agent-to-agent loop, wake agents automatically, or grant extra file/provider
  permissions.
- `contextManagement.strategy=recent-window` and related profile fields reserve
  a bounded conversation-window path, but they do not connect summary
  generation, provider-native remote sessions, external context engines, remote
  conversation connectors, or provider prompt injection.
- Finite-round discussion, heartbeat, convergence, and automatic judging remain
  deferred and are not connected to the default runtime.

## Verification

Run from `python-core`:

```powershell
$env:PYTHONPATH='src'
py -3.11 -m unittest tests.test_conversation_domain tests.test_conversation_store tests.test_local_platform_operations tests.test_local_runtime_entrypoint tests.test_platform_invocation_runtime_handler
py -3.11 -m unittest discover -s tests
```

Run from `gateway`:

```powershell
npm.cmd run test:platform-route
npm.cmd run test:platform-bridge
```
