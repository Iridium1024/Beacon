# Model And Agent Access

Status: current developer note for macro steps 2, 10, 11, 13, 15, 16, 17, 18,
19, 20, 21, 22.1, 22.2, 22.2.1, and 22.3.

## Purpose

This note records the current model-neutral access layer for the Python
platform runtime.

The current chain is:

```text
AgentInvocationRequest
  -> optional AgentRuntimeProfile resolution
  -> ProviderBackedAgentInvocationAdapter
  -> ModelInvocation
  -> ModelProviderPort
  -> ModelOutput
  -> AgentInvocationResult
```

## Provider Contract

The provider-neutral contract is `ModelProviderPort`:

- `generate(ModelInvocation) -> ModelOutput`
- `embed(EmbeddingRequest) -> EmbeddingResult`
- `list_models() -> tuple[str, ...]`

The provider-neutral data objects live in `agent_os.domain.entities.model`.

Macro step 11 adds model capability and option metadata objects for provider
selection:

- `ModelCapabilityKind`
- `ModelCapability`
- `ModelGenerationOptions`
- `ModelReasoningOptions`
- `ModelRuntimeConstraints`

Generation options can be forwarded to provider parameters. Reasoning options
and runtime constraints remain reserved metadata for later provider-specific
capability negotiation; they are not treated as automatic provider parameters.
The OpenAI-compatible adapter has an explicit allowlist for provider-specific
`reasoning_effort` and `thinking` passthrough when the caller opts in through
configuration or invocation parameters.

## Deterministic Provider

`DeterministicModelProvider` is the default executable provider for tests and
local wiring.

It does not read keys, call network endpoints, or depend on third-party
packages.

```python
from agent_os.infrastructure.adapters.models import DeterministicModelProvider

provider = DeterministicModelProvider()
```

## OpenAI-Compatible Provider

Macro step 10 adds an explicit OpenAI-compatible adapter behind
`ModelProviderPort`. It supports chat-completions style text generation through
an allowlisted local runtime configuration path. It is opt-in, covered by local
fake-provider tests, and reads credential values only from the configured
process environment variable.

DeepSeek and similar APIs can be used only insofar as they expose an
OpenAI-compatible endpoint in this baseline. The platform core still depends on
`ModelProviderPort`, not a vendor-specific API.

## Provider API Shapes

Macro step 13 adds a credential-safe provider API shape foundation. The runtime
can now express configured provider connections through:

- `ProviderApiShape`
- `ProviderConnectionSpec`
- `ProviderPreset`
- `build_model_provider_from_connection_spec(...)`

Supported API shape labels are:

- `openai_chat_completions`
- `openai_responses`
- `anthropic_messages`
- `gemini_generate_content`
- `ollama_chat`
- `azure_openai`

Executable adapters currently exist for:

- OpenAI-compatible Chat Completions through `OpenAIAdapter`;
- OpenAI Responses text generation through `OpenAIResponsesAdapter`;
- Anthropic Messages through `AnthropicMessagesAdapter`;
- Gemini generateContent through `GeminiGenerateContentAdapter`;
- Ollama native `/api/chat` through `OllamaChatAdapter`.

Macro step 14.1 hardens `OpenAIResponsesAdapter` for relay compatibility by
adding an explicit `input_mode`/`responses_input_mode` provider parameter. The
default remains `structured_messages`, which posts official Responses message
content arrays. `plain_text` is opt-in for relay endpoints that accept only a
single string `input`. This setting changes only the request `input` shape; it
is not forwarded to the provider as a generation parameter and does not add
automatic context compression, remote conversation state, or provider
capability discovery.

Macro step 14.2 adds an explicit provider HTTP `User-Agent` compatibility
option. Adapters may receive `provider_user_agent` or `user_agent` through
provider parameters, and the shared HTTP client sends it only after validating
that it is a non-empty single-line value of at most 256 characters. No custom
`User-Agent` is sent by default, the value is not forwarded in JSON request
bodies, and this does not introduce arbitrary header injection, credential
storage, remote model discovery, or context-management behavior.

Macro step 15 adds a context-management profile foundation adjacent to, but
separate from, provider compatibility settings. `ContextManagementProfile`
defines user-selectable strategy families such as `pass-through`,
`recent-window`, `platform-summary`, `provider-native`,
`external-context-engine`, and `hybrid`. It validates input budgets, overflow
modes, context scopes, reserved agent-private memory, provider-native, and
external-engine metadata without opening remote sessions or storing
credentials.

Macro step 16 adds the local context access authorization boundary for that
profile foundation. `ContextAssemblyPlanner` now records requested scopes,
profile-allowed scopes, authorized scopes, denied scopes with stable reasons,
and source references. This is pre-invocation assembly authorization metadata,
not prompt rendering. `pass-through` still goes through scope authorization and
budget checks. Current provider-backed invocations keep this audit data under
`ModelInvocation.parameters["context_management"]`; existing provider adapters
continue to forward only allowlisted generation/provider parameters, so context
authorization metadata is not sent to upstream provider JSON bodies.

Macro step 17 adds metadata-only window selection over authorized source refs.
The same local `context_management` metadata now includes selected source refs,
omitted refs with reasons, denied scopes excluded from selection, selection
order, and budget/window hints. Selection works only after authorization and
does not load conversation messages, shared context bodies, task bodies, file
bodies, provider-native state, or external-engine output. Provider adapters
still do not forward this metadata to upstream JSON bodies.

Macro step 18 adds a selected-source content packet contract to the same local
metadata seam. `ContextAssemblyPlanner` now emits a `content_packet` with a
packet id, delivery mode, selected source refs, packet items, excluded
omitted/denied refs, content state/kind labels, token estimates, budget
metadata, redaction metadata, and `content_loaded=false`. The packet is not a
prompt renderer: current user text is marked as already present in the user
message, and conversation/shared/task/file refs are represented as ref-only
`not_loaded` packet items. Reserved `agent_native_delegated_context` delivery
metadata can be selected for future agent-native runtimes, but no real Codex,
web, IDE, provider-native session, external context engine, or prompt injection
connector is enabled in this baseline.

Macro step 19 adds a bounded local materialization layer after that packet.
`ContextAssemblyPlanner` now emits a `materialization` plan with segment ids,
source packet item ids, source refs, segment kind, load state, optional bounded
local text, estimated tokens, budget metadata, redaction metadata, and delivery
metadata. Segments are derived only from selected packet items. The current
user instruction remains a marker because it is already the provider user
message. Explicit local conversation snapshots, shared-context update summaries,
and task snapshots can be materialized with deterministic truncation when they
are supplied. File refs remain `deferred_file_body`, and provider-native,
external-engine, and agent-native runtime scopes remain unconnected. Existing
provider adapters still forward only allowlisted generation/provider
parameters, so this local `context_management` metadata is not sent to upstream
provider JSON bodies by current adapters.

Macro step 20 adds the first advanced agent/runtime access contract after
materialization. `AgentRuntimeAccessProfile` distinguishes provider-backed
models from future agent-native runtimes, external bridges, browser-session
runtimes, IDE runtimes, and reserved runtime kinds. It records delegated-context
delivery policy plus declarative tool, skill, file, memory, and network
permissions. `AgentRuntimeAccessPlanner` emits an auditable grant and a
metadata-only delivery plan in `ModelInvocation.parameters["runtime_access"]`.
The plan may reference materialized segment ids only when explicitly allowed,
but it never includes segment text, file bodies, credentials, WebSocket
transport, provider prompt injection, or a real runtime connection.

Macro step 21 adds a read-only runtime permission projection before any real
runtime connector. `AgentRuntimePermissionView` reads an agent registration,
parses the existing `AgentRuntimeProfile` and `AgentRuntimeAccessProfile`, and
returns a JSON-compatible permission view with configured runtime kind,
delegated-context delivery, tool/skill/file/memory/network policy, allowed and
denied capability flags, preview grant metadata, delivery-plan audit flags, and
explicit boundary flags. The view is not an invocation: it does not call a
provider, connect a runtime, read file bodies, create memory storage, open
WebSocket transport, or change provider messages.

Macro step 22.1 adds an explicit Agent Exchange source-attribution contract for
advanced agents that are instructed by the user to access the platform through
local CLI/API surfaces. `AgentExchangeAttribution` normalizes
`agentExchange` metadata for context updates and conversation messages, with
stable source, author, contribution, confidence, and instruction-authority
labels. Agent-authored records default to `agent_suggestion`, cannot claim
`user_directive`, and cannot become `decision` records without
`user_confirmed` source confidence. This is a shared-context exchange contract,
not a real Codex/Claude/browser/IDE runtime connector.

Macro step 22.2 adds a manual wake safe-mode activation contract on top of
Agent Exchange. `AgentActivationGrant` records user-explicit wake state,
activation mode, metadata-only connection surface, task/conversation scope,
bounded activity budget, allowed contribution kinds, stop reason, and
revocation metadata. The local operation surface and CLI can return activation
instructions, wake an agent, query/list activation state, and revoke an
activation. `AgentExchangeAttribution` can now carry `linkedActivationId`; when
present, local context and conversation write paths reject missing, revoked,
expired, dormant, review-blocked, mismatched, or `maxWrites`-exhausted
activations. The feature is still a local contract: it does not connect real
Codex/Claude/browser/IDE
agents, open WebSocket transport, read file bodies, store credentials, inject
provider prompts, run finite-round discussion, start heartbeat, or auto-wake
agents.

Macro step 22.2.1 adds a user-authorized delegated one-time wake grant on top
of manual wake activation. `DelegatedWakeGrant` records a user-created single-use
grant that lets one `sourceAgentId` create exactly one bounded
`AgentActivationGrant` for one `targetAgentId` inside a workspace/task/conversation
scope. The grant enforces `maxUses=1`, `canDelegateFurther=false`, expiration,
revocation, source/target agent validation, a target activation budget cap, and
stable deny reasons. Consuming a grant creates a target activation whose
metadata records `delegatedWakeGrantId`, `sourceAgentId`, and `delegatedByUser`;
the target activation is still bound by the step 22.2 safe-mode budget,
`maxWrites`, `linkedActivationId`, source attribution, and runtime permission
contracts. The local operation surface, `LocalPlatformApplication`, and
`python -m agent_os.local_runtime` expose `agent-delegated-wake-grant-instructions`,
`-create`, `-status`, `-consume`, and `-revoke`. This is still a local contract:
it does not connect or control a real Codex, Claude Code, browser, IDE,
provider-native session, external context engine, or remote conversation
runtime, does not wake the target agent, does not read file bodies, does not
store credentials, does not change provider prompts, and grants no tool, file,
memory, network, or runtime-control permission.
If a local caller omits `expiresAt`, the platform materializes a bounded
one-hour default from `createdAt` rather than creating an open-ended delegated
wake grant.

Macro step 22.3 adds advisory project-directory coordination and git provenance
metadata for multiple advanced agents that may work in one project directory.
`ProjectDirectoryCoordinationRecord` records a declaring agent, project root,
optional git repository id, task/conversation links, declared path scopes,
access intent, overlap status, caller-reported dirty state, branch/head
summaries, test/handoff notes, recommended commit policy, and
`notSecurityBoundary=true` / `advisoryOnly=true` flags. The local operation
surface, `LocalPlatformApplication`, and `python -m agent_os.local_runtime`
expose `project-directory-coordination-instructions`, `-declare`, `-status`,
`-update`, and `-complete`. Overlap is calculated from declared metadata only:
read-only overlaps become `shared_read`, overlaps involving edit intent become
`shared_write_risk`, and completed `done_reported` records are excluded from
active overlap. This is still not a runtime connector, filesystem sandbox, hard
lock, file-body reader, credential store, provider prompt injector, or git
automation path.

Reserved but not executable in this baseline:

- Azure OpenAI.

`ProviderConnectionSpec` stores endpoint/model metadata and credential
environment variable names only. It rejects credential-looking values inside
parameters and metadata. `deepseek_provider_preset(...)` represents DeepSeek as
an OpenAI-compatible Chat Completions preset with current static model names
(`deepseek-v4-flash`, `deepseek-v4-pro`) plus legacy-model deprecation
metadata; it does not make DeepSeek a platform core dependency.

`list_models()` remains configured/static. The current baseline does not crawl
remote model registries or negotiate capabilities automatically.

## Agent Adapter

Use `ProviderBackedAgentInvocationAdapter` when a single-turn runtime should
call a provider-neutral model provider:

```python
from agent_os.application.services import ProviderBackedAgentInvocationAdapter
from agent_os.infrastructure.adapters.models import DeterministicModelProvider

adapter = ProviderBackedAgentInvocationAdapter(
    model_provider=DeterministicModelProvider(),
    provider_name="deterministic",
    model_name="deterministic-text",
)
```

The adapter maps platform invocation state to `ModelInvocation`, then maps
`ModelOutput` to `AgentInvocationResult`.

## Provider Selection

Use `ModelProviderSelection` to express the provider/model choice and default
parameters without constructing a real provider:

```python
from agent_os.application.services import (
    ModelProviderSelection,
    build_provider_backed_agent_invocation_adapter,
)
from agent_os.infrastructure.adapters.models import DeterministicModelProvider

selection = ModelProviderSelection(
    provider_name="deterministic",
    model_name="deterministic-text",
    parameters={"temperature": 0},
)

adapter = build_provider_backed_agent_invocation_adapter(
    model_provider=DeterministicModelProvider(),
    selection=selection,
)
```

## Agent Runtime Profile

Macro step 11 adds `AgentRuntimeProfile` as the current agent-binding
foundation. It parses `AgentRegistration.runtime_config` and can provide:

- profile and role names;
- system prompt override;
- provider/model names;
- generation options such as temperature, max tokens, top-p, and stop strings;
- reserved reasoning/runtime constraint metadata;
- resolved context-management profile configuration;
- resolved runtime-access permission profile configuration;
- binding and connection identifiers for future provider-connection resources.

The local invocation composition resolves the invoked agent registration before
building the provider-backed adapter. A reviewer and planner can therefore use
the same configured provider/model connection while keeping separate prompts
and generation options. Inline credential values such as API keys, bearer
tokens, passwords, cookies, or secrets are rejected.

`AgentRegistration.runtime_config.profile.contextManagement` may now carry a
validated context-management profile. The default is `pass-through` with a
bounded input budget and an explicit context-scope allowlist. `pass-through`
does not bypass permissions or forward unlimited context; it only means the
platform does not summarize or compact context in this baseline.

`AgentRegistration.runtime_config.profile.runtimeAccess` may now carry a
validated runtime-access profile. The provider-backed default keeps delegated
context delivery disabled, tool execution disabled, file permission limited to
file-reference metadata, runtime-local memory disabled, and network disabled.
Agent-native or bridge-like runtime kinds can declare future permissions, but
those permissions remain a contract and audit record until a separate runtime
adapter task connects a real executable surface.

The profile allowlist is not a permission bypass. It can request scopes such as
`recent_messages`, `project_shared_context`, `current_task`, or
`referenced_files`, but the active invocation must still provide an authorized
source boundary such as a conversation id, task id, or file-reference id. The
reserved scopes `agent_private_memory`, `provider_native_session_ref`, and
`external_context_engine` remain explicitly denied until their future storage or
runtime integrations are connected.

## Composition

The local SQLite single-turn composition keeps the deterministic placeholder
adapter as its default. Explicit provider modes can pass a provider-backed
adapter or a per-agent adapter factory. The local runtime uses the factory when
agent profiles are present.

`python -m agent_os.local_runtime` supports both the legacy explicit
`openai-compatible-provider` mode and a generic `provider-api-shape` mode. The
generic mode accepts a provider API shape, base URL, model, optional provider
name, optional credential env var name, timeout, temperature, max-token, and
explicit reasoning/thinking settings. For OpenAI Responses-compatible relay
endpoints, it also accepts explicit provider input mode through
`--provider-input-mode` or `AGENT_OS_PROVIDER_INPUT_MODE`. Provider-shape mode
also accepts an explicit safe provider HTTP `User-Agent` through
`--provider-user-agent` or `AGENT_OS_PROVIDER_USER_AGENT`. The deterministic
placeholder remains the default.

Provider-backed invocations build a local `context_management` assembly plan in
`ModelInvocation.parameters`. Current provider adapters do not forward that
metadata to upstream JSON bodies because generation parameters remain
allowlisted per adapter. The plan records the resolved strategy, budget,
exposed context scopes, authorization results, window selection results,
selected-source content packet contract, bounded local materialization status,
overflow behavior, and whether compaction would be needed. It does not inject
full conversation history into prompts or copy source bodies into provider
payloads.

Provider-backed invocations also build a local `runtime_access` grant in
`ModelInvocation.parameters`. Current provider adapters do not forward this
metadata to upstream JSON bodies. The grant records runtime kind, declared
permissions, denied capabilities, revocation status, and a delivery plan that
is bounded by the already selected and materialized context plan.

The local operation surface, CLI, and Gateway `python_cli` bridge can now query
runtime permissions without invoking the agent:

- Python service/facade: `list_agent_runtime_permissions(...)` and
  `get_agent_runtime_permissions(...)`;
- CLI: `agent-runtime-permissions` and `agent-runtime-permission-get`;
- Gateway: `GET /api/v1/workspaces/:workspaceId/runtime-permissions` and
  `GET /api/v1/workspaces/:workspaceId/agents/:agentId/runtime-permissions`.

These routes expose read-only audit state only. They do not expose credential
values, provider compatibility settings, provider JSON payloads, or real
session handles.

The local operation surface and CLI also expose an Agent Exchange contract for
external advanced agents that are manually instructed to use the platform:

- Python service/facade: `agent_exchange_instructions(...)`;
- CLI: `agent-exchange-instructions`;
- CLI write metadata: `context-append --exchange-attribution-json` and
  `conversation-message-append --exchange-attribution-json`.

The normalized metadata is stored under `metadata.agentExchange`. It remains
metadata-only and does not call providers, connect runtimes, read file bodies,
or grant extra runtime permissions.

## Verification Commands

Run from `python-core`:

```powershell
$env:PYTHONPATH='src'
py -3.11 -m unittest tests.test_deterministic_model_provider tests.test_provider_backed_agent_invocation_adapter tests.test_model_provider_selection tests.test_model_runtime_profile tests.test_model_adapter_placeholders
py -3.11 -m unittest tests.test_local_single_turn_use_case_composition tests.test_single_turn_platform_runtime tests.test_platform_invocation_runtime_handler
py -3.11 -m unittest tests.test_openai_compatible_provider_adapter tests.test_official_provider_shape_adapters tests.test_provider_connection_config_and_factory tests.test_local_runtime_entrypoint
py -3.11 -m unittest tests.test_context_management_profile tests.test_model_runtime_profile tests.test_provider_backed_agent_invocation_adapter
py -3.11 -m unittest discover -s tests
```

## Current Limits

- Provider-backed invocation exists only through explicit opt-in configuration.
  Live provider smoke requires user-supplied credentials through environment
  variables.
- OpenAI Responses is a minimal text-generation adapter only. Streaming, tools,
  file/image input, remote conversation state, prompt caching, background mode,
  automatic context compression, and automatic Responses capability discovery
  remain deferred.
- Azure OpenAI is a reserved API shape but not an executable adapter yet.
- Remote model discovery is not implemented; model listing is configured/static.
- Local and remote HTTP adapters remain placeholders.
- The runtime remains synchronous at the agent invocation adapter boundary.
- The deterministic provider is for tests and local wiring only.
- Agent profiles do not create full chat-history sessions or remote
  conversation instances.
- Context Management Profiles are implemented as validated configuration and a
  local assembly-plan seam with a simple bounded materialization layer. This
  layer performs deterministic local selection/truncation over explicit
  sanitized inputs only; it is not an LLM summarizer, provider-native
  compaction/session state, external context engine, file-body loader, or
  automatic long-history prompt injection path.
- Runtime Access Profiles are implemented as validated permission contracts and
  local audit metadata only. They do not execute tools, read file bodies,
  create runtime-local memory storage, open network/WebSocket transports,
  connect real Codex/web/IDE/browser agents, or inject provider prompts.
- Runtime Permission Views are implemented as read-only projections over
  registered agent profiles and runtime-access grants. They do not create
  invocations, call providers, connect runtimes, or make permission decisions
  beyond exposing the current contract state for API/UI review.
- Agent Exchange is implemented as source-attribution metadata and an
  agent-facing local interface contract. It does not wake agents, run
  background loops, connect Codex/Claude/browser/IDE sessions, or allow agent
  outputs to become user directives automatically.
- Delegated wake grants are implemented as user-authorized single-use local
  state transitions on top of manual wake activation. They do not wake, connect,
  host, or control a real external agent runtime, do not read file bodies, do
  not store credentials, do not change provider prompts, and grant no runtime
  permissions beyond what the target activation's own runtime access contract
  allows.
- Project directory coordination is advisory metadata for overlap awareness and
  provenance handoff only. It does not enforce OS-level locks, sandbox a
  high-capability agent, scan directories, read file bodies, resolve conflicts,
  or execute `git commit`, `push`, `reset`, `checkout`, or `rebase`.
- Provider credential persistence is not implemented.
- Arbitrary provider HTTP header injection is not implemented. Only the
  explicit safe `User-Agent` compatibility option is currently allowlisted.
