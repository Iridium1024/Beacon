# Local HTTP API Contract

Status: supported local Gateway API contract.

## Purpose

The local HTTP API contract exposes the platform as resource-oriented Gateway
routes for future UI, scripts, local tools, and external agent callers.

This is a multi-agent shared-context platform API. It is not a single-model
chat API.

## Runtime State

The current Gateway route layer is contract-first:

```text
Gateway /api/v1 routes
  -> LocalPlatformApiAdapter interface
  -> ContractOnlyLocalPlatformApiAdapter by default
  -> PythonLocalPlatformApiAdapter when LOCAL_PLATFORM_BRIDGE_MODE=python_cli
```

The default adapter returns a stable not-connected response. It does not call
Python, start a subprocess, connect a provider, open a browser session, or run
tools.

In `python_cli` mode, Gateway calls `python -m agent_os.local_runtime` through non-shell child processes with
explicit cwd, PYTHONPATH, database, workspace root, plugin directory, and
timeout settings.

The bridge is still local-only. It does not connect model providers, browser
sessions, account connectors, UI, file-write routes, or multi-user permission
systems.

The Python CLI remains the primary coordination surface. Gateway does not
currently expose agent dispatch, endpoint onboarding, registered-session
activation, or the complete exchange request/status command family. Those
capabilities must not be inferred from the presence of the Python bridge.

The local API boundary accepts only localhost bind targets, route metadata
carries a local-process access policy, bridge errors are sanitized before they
are returned to HTTP callers, and session-bound invocations append explicit
run-session lifecycle events through the Python event log.

An explicit OpenAI-compatible provider adapter is available behind the Python
provider-neutral model boundary. Gateway can pass provider mode/config to the
Python CLI bridge through allowlisted environment/config values, while the
`/api/v1` route shapes stay unchanged. Default route behavior remains
deterministic/contract-only unless provider mode is explicitly enabled.

The local agent creation route `POST /api/v1/workspaces/:workspaceId/agents`
creates an additional
workspace-scoped agent registration through Python-local runtime. The request
can include runtime profile metadata such as profile name, role name, system
prompt, provider/model names, generation options, and reserved
reasoning/runtime metadata. Credential values are rejected by Python and are not
stored by Gateway.

Local conversation-session route contracts and Python bridge mapping are
available. Conversation sessions are workspace-scoped durable message threads.
They are distinct from run-session lifecycle records and project shared context.
Invocations may optionally include `conversationId`; when present, Python
persists linked user and assistant messages after the invocation completes.
This does not enable UI, remote browser conversations, credential capture, or
automatic full-history provider injection.

Provider API shape support is available in the Python local runtime
configuration layer. Gateway route contracts stay unchanged. The Python bridge
can use the allowlisted OpenAI-compatible provider mode/config or generic
`provider-api-shape` bridge passthrough.

Gateway `python_cli` passthrough supports allowlisted Python-local provider API
shapes. In `provider-api-shape` mode, Gateway can pass shape, base URL, model,
provider name, timeout, temperature, max token,
reasoning effort, thinking type, provider input mode, provider HTTP
`User-Agent`, and credential environment variable name to
`python -m agent_os.local_runtime`. Credential
values are copied only from the current Gateway process environment into the
child process and are not stored in Gateway config, route payloads, logs, or
repository files. The default adapter and default invocation mode remain
contract-only / deterministic-placeholder.

OpenAI Responses relay compatibility can use that passthrough.
`AGENT_OS_PROVIDER_INPUT_MODE=plain_text` is an explicit opt-in
for relays that accept string `input`; the default structured Responses input
shape remains unchanged.

Safe `AGENT_OS_PROVIDER_USER_AGENT` passthrough is available for
relay/provider compatibility. Gateway validates the value as a short
single-line string and passes it to Python as `--provider-user-agent`; Python
then sends it only as the provider HTTP `User-Agent` header. This is not an
arbitrary header injection surface and does not enable credential header
configuration, provider capability discovery, or context compression.

Use this reproducible Gateway TypeScript verification path:

```powershell
Set-Location '<PROJECT_ROOT>\gateway'
npm.cmd ci
npm.cmd run build
npm.cmd run check
npm.cmd test
npm.cmd run test:platform-route
npm.cmd run test:platform-bridge
npm.cmd run test:legacy-heartbeat
```

`gateway/package-lock.json` is part of the toolchain baseline.
`npm test` runs the current platform mainline tests. The old heartbeat terminal
export consumer remains available only through `test:legacy-heartbeat`.
The route test script covers local platform routes, DTO contract shape,
localhost-first config, and the old disabled `/platform/invocations/single-turn`
boundary. This verification still runs against the contract-only adapter.

Bridge verification is available through:

```powershell
Set-Location '<PROJECT_ROOT>\gateway'
npm.cmd run test:platform-bridge
```

The bridge test starts Gateway on `127.0.0.1` with a temporary SQLite database
and verifies real HTTP calls through Python-local runtime, sanitized bridge
errors, session lifecycle visibility, and a local fake OpenAI-compatible
provider path.

`npm start` runs `dist/src/main.js`; run `npm run build` first. Gateway test
sources live under `gateway/tests` so the standalone release directory can
be cloned and tested without relying on a parent `tests/gateway` directory.

## Host And Port

Gateway remains localhost-only:

- default host: `127.0.0.1`
- default port: `3000`
- host and port remain configurable through Gateway environment settings
- accepted hosts: `127.0.0.1`, `localhost`, and `::1`
- rejected hosts include `0.0.0.0` and LAN/public interface addresses

The default must not be changed to `0.0.0.0`. If future builds allow LAN access,
that must be a separate explicit task with product-grade authentication,
permission, CORS, and service-hosting boundaries.

## Route Map

The current route contract is:

```text
POST /api/v1/workspaces
GET  /api/v1/workspaces
GET  /api/v1/workspaces/:workspaceId
POST /api/v1/workspaces/:workspaceId/archive

GET  /api/v1/workspaces/:workspaceId/context
POST /api/v1/workspaces/:workspaceId/context-updates

GET  /api/v1/workspaces/:workspaceId/agents
POST /api/v1/workspaces/:workspaceId/agents

GET  /api/v1/workspaces/:workspaceId/conversations
POST /api/v1/workspaces/:workspaceId/conversations
GET  /api/v1/workspaces/:workspaceId/conversations/:conversationId
POST /api/v1/workspaces/:workspaceId/conversations/:conversationId/archive
GET  /api/v1/workspaces/:workspaceId/conversations/:conversationId/messages
POST /api/v1/workspaces/:workspaceId/conversations/:conversationId/messages

POST /api/v1/workspaces/:workspaceId/invocations
GET  /api/v1/workspaces/:workspaceId/invocations
GET  /api/v1/workspaces/:workspaceId/file-operations
GET  /api/v1/workspaces/:workspaceId/sessions/:sessionId/timeline

GET  /api/v1/connections
POST /api/v1/connections
GET  /api/v1/agent-bindings
POST /api/v1/agent-bindings
```

The older `/platform/invocations/single-turn` route remains a disabled
compatibility boundary and still returns not wired.

## Response Envelope

Successful route responses use:

```json
{
  "ok": true,
  "payload": {},
  "metadata": {
    "routeStatus": "ok",
    "platformRuntimeWired": "contract_only",
    "sessionId": "...",
    "correlationId": "...",
    "localApiPolicy": "local_only",
    "actorKind": "local_process",
    "permissionScopes": ["workspace.read", "agent.invoke"]
  }
}
```

Contract-only failures use:

```json
{
  "ok": false,
  "payload": {
    "error": {
      "type": "not_connected",
      "message": "..."
    }
  },
  "metadata": {
    "routeStatus": "not_connected",
    "platformRuntimeWired": "contract_only",
    "sessionId": "...",
    "correlationId": "...",
    "localApiPolicy": "local_only",
    "actorKind": "local_process",
    "permissionScopes": ["workspace.read", "agent.invoke"]
  }
}
```

Invalid request bodies return `routeStatus: "invalid_request"` and a stable JSON
error payload.

Bridge failures return the same envelope shape. Internal Python tracebacks and
local filesystem paths must not be exposed through the `message` field.

## Local Access Policy

The current policy is a local-process boundary, not a product user-account
system:

- `policyMode`: `local_only`
- `localOnly`: `true`
- `lanExposureEnabled`: `false`
- `accountSystemEnabled`: `false`
- actor kind: `local_process`
- reserved scopes: workspace read/write, context read/append, agent read/write/invoke,
  conversation read/write, records read, provider-connection reserve, and
  agent-binding reserve

The route layer passes this policy into `LocalPlatformApiCallContext` so future
authorization, provider binding, remote conversation connectors, or external
context synchronization can be added without reshaping the core API. Current
routes do not inspect account cookies, bearer tokens, API keys, or provider
credentials. In explicit provider mode, the Python bridge forwards only the
configured provider credential environment variable to the child process; it
does not store credential values in Gateway config.

## Session Lifecycle

Session-bound invocations through the Python bridge append
`run_session.changed` events for `running` and terminal status. Timeline
responses include a `session.lifecycle` summary with:

- whether explicit lifecycle events exist;
- lifecycle status source;
- recovery state: `missing`, `open`, `closed`, or
  `observed_without_lifecycle`;
- started and terminal event sequence/time;
- invocation, context-update, and file-operation event counts.

This is sufficient for the local API baseline to distinguish a closed session
from historical events without lifecycle records. Crash-safe long-running
session recovery remains a later task.

## Connection And Binding Contracts

Provider connections and agent runtime bindings are abstract platform resources.

`ProviderConnection` separates account/provider configuration from workspace and
agent state:

- `connectionId`
- `providerKind`
- `accountAlias`
- `displayName`
- `authMode`
- `status`
- `metadata`

`AgentRuntimeBinding` separates an agent from its runtime connection:

- `bindingId`
- `agentId`
- `connectionId`
- `runtimeKind`
- `remoteInstanceId`
- `capabilities`
- `status`
- `metadata`

These contracts are intended to support future real providers and remote
conversation instances without changing workspace, context, or invocation
routes. The current implementation does not connect them.

Agent runtime profile metadata on `AgentRegistration.runtimeConfig` is the
current local binding foundation. It supports multiple isolated local agents
over the same configured provider/model path by changing role/system prompt and
generation options per agent. It is intentionally narrower than a real provider
connection or remote conversation connector.

Future extension space is reserved for provider adapters, external context
synchronization, same-account remote conversation instances, and optional
multi-user permission scopes. None of those paths are active in the current
Gateway contract.

## Conversation Sessions

Conversation sessions expose local message-history storage:

- `conversationId`: durable local thread id;
- `workspaceId`: owning workspace;
- optional `agentId`: thread-level default or binding hint;
- message role: `user`, `assistant`, `system`, `tool`, or `note`;
- optional links: `invocationId`, `contextUpdateId`, and `runSessionId`.

`conversationId` may be included in `POST
/api/v1/workspaces/:workspaceId/invocations`. The Gateway bridge forwards that
field to Python. Python validates workspace and agent boundaries and persists
linked user/assistant messages only when a conversation id is provided.

Conversation sessions do not replace `ProjectSharedContext`. They are a local
history boundary for isolated chat-like threads. Shared context remains the
canonical cross-agent context store.

## Limits

- Not a product HTTP API yet.
- Python bridge is available only through explicit `python_cli` mode and is not
  the default.
- OpenAI-compatible provider invocation and generic provider API shape
  passthrough are available only through explicit provider modes; live provider
  smoke is optional and not part of the default test path.
- Gateway generic provider API shape passthrough is allowlisted for
  OpenAI-compatible Chat Completions, OpenAI Responses, Anthropic Messages,
  Gemini generateContent, and Ollama native `/api/chat`.
- Gateway provider HTTP `User-Agent` passthrough is an explicit single-header
  compatibility option; arbitrary provider HTTP header injection is not
  implemented.
- OpenAI Responses is wired only as a minimal text-generation Python adapter.
  Streaming, tools, remote conversation state, automatic context compression,
  and automatic capability discovery remain deferred.
- Azure OpenAI is a reserved Python shape label but not an executable adapter
  yet.
- Remote model discovery is not implemented; model listing is configured/static.
- Agent creation through the Gateway Python bridge is available in explicit
  `python_cli` mode and stores profile metadata in Python-local state.
- Conversation creation, message append/query, and optional invocation linkage
  are available in explicit `python_cli` mode.
- No provider credential store is implemented.
- No UI or desktop shell is implemented.
- No file write route is exposed.
- No autonomous tool planning is introduced.
- No remote conversation connector is implemented.
- Conversation history is persisted and queryable, but it is not automatically
  injected into model provider requests as full long-history context.
- Product user accounts, multi-user authorization, CORS policy, and LAN/public
  exposure remain deferred.
