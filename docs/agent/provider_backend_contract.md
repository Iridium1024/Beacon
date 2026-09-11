# Dispatch And Provider Backend Contract

Status: public v0.1.1 contract for dispatch meanings, backend selection, and
current runtime capability reporting.

## External Operations

Beacon presents four meanings to calling agents:

- `send`: make one bounded inline attempt for a new turn.
- `queue`: store a dispatch for a separately confirmed worker, daemon, or
  supervisor.
- `supplement`: explicitly add guidance to a supported active turn. This is
  never selected implicitly by `send`.
- `status`: read Beacon state or a provider-specific bounded status view.

`reply` is a separate receiver-selected response action exposed as
`agent-reply`; it is not a delivery strategy and is never required by `send`.

The current internal execution strategies are `inline`, `queue`, and
`dry_run`. `async_submit` is reserved for a future managed runtime and is not
implemented. Existing values remain compatible:

| Existing spelling | External operation | Execution strategy |
| --- | --- | --- |
| `worker_execute` / `--wait once` | `send` | `inline` |
| `queued` / `--queued` | `queue` | `queue` |
| `worker_dry_run` / `--dry-run` | `send` | `dry_run` |

The normal documentation uses `agent-dispatch-send` and `--queued`.
`worker_execute` and `--wait once` remain accepted compatibility vocabulary;
they do not represent a third delivery behavior.

## Provider Backends

Provider-neutral operations select one of these current backends:

| Backend id | Provider | Lifecycle | Ownership | Status authority |
| --- | --- | --- | --- | --- |
| `claude_cli` | Claude | `short_lived_operation` | `operation_owned` | `unsupported` |
| `claude_agent_sdk` | Claude | `short_lived_operation` | `operation_owned` | `unsupported` |
| `codex_exec_resume` | Codex | `short_lived_operation` | `operation_owned` | `unsupported` |
| `codex_app_server_stdio` | Codex | `short_lived_operation` | `operation_owned` | `point_read` |
| `hermes_cli` | Hermes | `short_lived_operation` | `operation_owned` | `unsupported` |
| `hermes_tui_gateway_stdio` | Hermes | `short_lived_operation` | `operation_owned` | `point_read` |
| `deepseek_harness_sdk_stdio` | DeepSeek Harness | `managed_runtime` | `persistent_owned` | `owned_live` |

Every selection reports `requestedBackend`, `effectiveBackend`, `source`,
`fallbackApplied`, and the selected descriptor. Beacon does not silently move
between Claude SDK/CLI, Codex app-server/exec-resume, Hermes gateway/CLI, or
providers. `cli` remains the default Claude activation backend,
`exec_resume` remains the default Codex backend, and Hermes keeps `cli` as its
default. All three short-lived programmatic alternatives remain opt-in.
DeepSeek Harness is a separate opt-in fourth Agent platform that can resume an
exact persisted native session or create a new Beacon-owned session; it is not
a fallback for any existing provider.

Upstream interfaces under evaluation are not reserved backend ids and must not
be emitted as effective values. The implemented Claude Agent SDK and Hermes TUI
Gateway, plus reviewed Hermes ACP and hosted/API surfaces, are classified in
[`provider_programmatic_interfaces.md`](../providers/provider_programmatic_interfaces.md).

Capability reports explicitly cover inline execution, detached start, wait,
status read, owned-live status, multi-thread management, active-turn
supplement, cancellation, final-message capture, and runtime ownership. A
false capability is a current Beacon implementation limit, not a claim about
the upstream provider protocol.

`canCancel=false` currently means the shared backend adapter has no
caller-invokable cancel operation. Short-lived provider children still have
bounded timeout and internal process cleanup; that safety cleanup is not
advertised as a public cancellation capability.

## State Projection

Dispatch results keep their legacy statuses and add three independent views:

- `deliveryState`: whether the request was queued, accepted, rejected, failed,
  or remains unknown.
- `executionState`: whether provider work is not started, active, completed,
  failed, or unknown.
- `replyState`: whether a target reply has been recorded.

`replyExpectation` is currently `unspecified`. Provider execution may complete
without a reply, and Beacon does not create a reverse dispatch merely because
an execution completed. Codex provider-final response capture remains available
only as the explicit `provider_final_capture` writeback policy; the default is
`explicit_only`. Claude writeback defaults are backend-specific: `claude_cli`
retains its historical `provider_final_capture` default, while
`claude_agent_sdk` defaults to `explicit_only`. Either can be explicitly
overridden.

## Managed Runtime Boundary

The `deepseek_harness_sdk_stdio` backend is Beacon's first persistent owned
runtime. One detached local supervisor owns one official DSH SDK server process
and one runtime generation over one persistent native DSH session.
Authenticated loopback IPC lets independent Beacon CLI/worker processes reuse
that exact generation; generation/session owner leases and an operation lease
allow only one Beacon owner and prompt operation at a time. Continuity is
`persistent_native_session`, restart resume is true, cancel scope is `none`,
maximum concurrent operations is one, and exact existing-session import is
true. Runtime-generation loss requires explicit resume; ambiguous in-flight
delivery requires acknowledgement and is never replayed.

Its capabilities are `canExecuteInline=true`, `canWait=true`,
`canReadStatus=true`, `canReadOwnedLiveStatus=true`,
`canCaptureFinalMessage=true`, and `canOwnRuntime=true`.
`canStartDetached`, multiple-thread management, active-turn supplement, and
cancel are false. The supervisor itself is persistent, but Beacon does not
expose a detached prompt operation.

DSH `messageId` is only enqueue/receipt evidence. Trusted final capture
requires the matching root receipt, a later root assistant message, successful
root turn end, and a later root idle notification. Unknown, duplicate, or
out-of-order evidence fails closed. Clean stop plus resume preserves the native
session/Agent/alias and mints new handle/runtime/generation ids. Explicit
recreate mints a new native session as well. See
[`deepseek_harness_managed_runtime.md`](../providers/deepseek_harness_managed_runtime.md).

The current `codex_app_server_stdio` backend still creates one short-lived
app-server stdio child for one operation and closes it. The upstream Codex
app-server protocol can manage multiple threads in one server, but Beacon does
not yet run that persistent multi-thread topology. A separate point status read
is `point_read`, not an owned-live subscription to a desktop or CLI instance
opened elsewhere.

The stable 0.149 compatibility contract requires `thread/resume` to prove an
effective registered cwd plus a sandbox, approval policy, and writable-root set
that are no wider than Beacon requested. Network access is likewise rejected
unless the operator explicitly requested full access. That proof is completed before
`turn/start` and is included in the activation audit; missing or expanded
evidence fails closed. Stable reverse requests must match the verified native
thread and active turn, use a valid item when required, and have a unique
request id. `serverRequest/resolved` is observation-only. Final capture uses
completed agent-message items or the bounded completed-turn summary and never
depends on deprecated delta notifications. These guarantees have fake-transport
and exact-schema coverage but no new authenticated 0.149 provider smoke.

`hermes_tui_gateway_stdio` has the same operation-owned topology: one exact
`hermes-agent==0.19.0` `python -u -m tui_gateway.entry` stdio child per
activation, then bounded cleanup. Its `point_read` authority covers only RPCs
against that owned child/runtime session. It is not a subscription to Hermes
Desktop, a persistent multi-session service, WebSocket, ACP, or the HTTP API
Server. The saved persistent session id and returned process-local runtime id
remain separate identity domains.

The current `claude_agent_sdk` backend likewise creates one SDK client for one
activation and disconnects it. It does not retain a live stream, supervise
multiple sessions, expose active-turn supplement/cancel, or publish provider
runtime status. Its internal timeout interrupt is cleanup behavior, not a
caller-invokable cancel capability.

Its public-SDK compatibility layer keeps the `>=0.2.127,<0.3.0` dependency
range and treats post-baseline symbols as optional capabilities. When exposed,
`ResultError` is a structured terminal failure, `ConversationResetMessage`
invalidates exact session continuity, and `ResultMessage.origin` admits final
capture only for missing/`None` or `human` provenance. These signals do not
change backend lifecycle, ownership, status authority, writeback defaults, or
the no-silent-fallback contract. The `0.2.144` audit is code/test evidence only;
an authenticated real-provider smoke remains outstanding.

## Safety Boundary

Beacon does not automatically select unrestricted/dangerous full-access modes,
does not add deletion APIs, and does not make destructive Git or recursive
filesystem operations part of provider activation. Provider permissions remain
explicit operator choices. Unrestricted provider modes can permit destructive
actions, so tests and development should use the narrowest practical sandbox
and preserve unrelated working-tree changes.
