<!-- beacon-version: 0.1.1 -->
# Changelog

All notable public-facing changes will be recorded here. Internal automation
steps and private migration history are intentionally excluded.

## [Unreleased]

### Added

- Deterministic project scope through `.beacon/workspace.json`, plus preflighted
  idempotent `agent-join` and concise `agent-reply` commands.
- Configurable Codex reply writeback with safe `explicit_only` default and an
  explicit `provider_final_capture` compatibility mode.
- Opt-in short-lived Claude Agent SDK registered-session activation with exact
  UUID/cwd resume, typed event/result handling, permission denial, bounded
  interrupt/cleanup, read-only preflight, and explicit CLI rollback.
- Opt-in short-lived Hermes TUI Gateway registered-session activation for the
  exact stable `hermes-agent==0.19.0` stdio contract, with persistent/runtime
  session identity separation, bounded final-message capture, and CLI rollback.
- Opt-in `deepseek_harness` fourth Agent platform with exact `0.1.1-rc.2`
  project-local Node SDK/server locking, one persistent Beacon-owned runtime
  generation per created or exactly resumed persistent DSH session,
  authenticated loopback supervisor IPC, owned-live status, strict causal
  final capture, and explicit stop/resume/recreate.
- Credential-free source-installation and release-draft documentation for the
  DSH increment. The delivery is source-only, not a GitHub Release or an
  installer; authenticated DSH model communication remains unverified.
- P3-A local read-only heterogeneous session-console spike composed through the
  official DeepSeek Harness Web profile and Host/Client plugin points. A
  versioned GET-only Beacon projection shows synthetic/local workspace,
  Agent/session, dispatch, capability, and bounded timeline state for Claude,
  Codex, Hermes, and DSH without provider control or transcript reads.
- P3-B standalone React + Tauri v2 read-only Desktop validation with offline
  fake data and an explicit loopback External Gateway mode. It reuses the P3-A
  host-neutral UI/protocol, validates a GET-only console API 1.0 health/version
  handshake before projection reads, starts without DSH/Node/Gateway/Python, and produces
  a Windows development executable without bundling an installer or sidecar.
- P3-B-2 browser-first product validation on the same React/store/protocol
  tree, with a unified keyboard-accessible Settings surface, Chinese/English
  locale, appearance/contrast/text-scale preferences, layered terminology and
  capability explanations, deterministic Fake/failure scenarios, and exact
  Playwright viewport/screenshot gates. The host remains loopback-only and
  read-only; Tauri and the optional P3-A DSH adapter are retained.
- P3-B-3 local-entry and dependency hardening: `start-beacon-browser.cmd`
  launches the existing foreground loopback browser host after bounded local
  checks, while Gateway pins Fastify 5.12.1 and repaired `fast-uri` /
  `find-my-way` resolutions without a major upgrade or API change.

### Changed

- Normal same-project onboarding and sends now use visible Agent IDs. Lower-
  level provider onboarding/discovery/endpoint commands remain available for
  advanced use.
- Codex provider execution output no longer becomes a Beacon response by
  default. Delivery, execution, and receiver-selected replies remain separate.
- `explicit_only` Codex activations now tell the receiver how to reply instead
  of promising automatic final-answer capture. Exact join is independent of
  display limits, workspace validation precedes provider discovery, and a
  discovered `CODEX_HOME` is reused by status and activation paths.
- Normal join rejects cross-Agent duplicate ownership of one active native
  session, marker writes fail closed under concurrent conflicting setup, and
  terminal provider execution is no longer displayed merely as started.
- Codex app-server compatibility now covers the 0.146 completion-summary
  fallback, nested error/deprecation diagnostics, and an additive read-only
  app-server surface check in runtime preflight. A new real-provider 0.146
  smoke is still pending.
- Codex app-server compatibility is refreshed against exact CLI 0.149.0 stable
  non-experimental schemas while retaining 0.145/0.146 checker compatibility.
  Resume now proves effective cwd/sandbox/approval/writable roots before
  `turn/start`; reverse requests require verified thread/turn/item correlation
  and unique ids; deprecated delta notifications are never final-response
  sources. The refresh has expanded fake-transport coverage but no new
  authenticated 0.149 real-provider smoke.
- Claude Agent SDK compatibility is refreshed against the public `0.2.144`
  shape without raising the `>=0.2.127,<0.3.0` range: optional capability
  reporting now covers structured `ResultError`, conversation resets invalidate
  exact-session continuity, and non-human/unknown result origins cannot become
  final responses. The refresh has fake-SDK coverage but no authenticated
  real-provider/session smoke.
- Provider documentation now distinguishes implemented Beacon backends from
  upstream programmatic surfaces: Claude Agent SDK and the exact stable Hermes
  `0.19.0` TUI Gateway are opt-in implemented backends, while Claude Managed
  Agents, Hermes ACP, and the Hermes API Server retain their separate or
  unsuitable session boundaries. Neither refreshed integration has completed
  authenticated real-provider/session smoke; upstream-main Hermes `0.20.5` is
  advisory only and fails the stable Gateway preflight.
- DeepSeek Harness uses `deepseek_harness_sdk_stdio` only. It now performs
  exact header-only lookup and official persistent-session resume, preserves
  Agent/native-id/alias identity across runtime generations, rejects live
  Beacon owner conflicts, and separates resume from new-session recreate.
  Windows uses Node 22.19+; official Python runtime wheels remain platform-
  gated. Support is backed by fake cross-process tests and locked official-
  runtime/persistence offline integration, not an authenticated real-model
  smoke or foreign live Web/TUI takeover.

### Security

- Project scope resolution never scans local databases, and conflicting scope
  sources fail closed. Beacon still does not default to unrestricted/full-
  access provider permissions.
- Hermes Gateway interaction requests are never approved or answered with
  secrets by default, malformed/cross-session messages fail closed, and
  timeout cleanup is bounded to one interrupt plus the isolated process tree.
- Codex app-server fails closed before starting a turn when resume permission
  evidence is missing or wider than requested, and never approves cross-thread,
  stale-turn, malformed, or duplicate reverse requests.
- DSH malformed/oversized/unknown JSON-RPC frames, ambiguous delivery, unknown
  queued work, stale identities, duplicate owners, and out-of-order final
  evidence fail closed without replay. Stop targets only the owned generation.
- The session-console Bridge has no mutation method or write route, accepts
  only bounded/redacted projection data, and runs on loopback. The spike has
  fake/contract coverage only and has not run authenticated real-provider,
  remote, or model smoke.
- Desktop registers zero Tauri commands, uses an empty capability permission
  list, denies remote navigation, allows only explicit-port HTTP loopback
  Gateway origins, omits credentials, rejects redirects and oversized payloads,
  and never owns Gateway/Python/DSH/Provider process lifecycle.

## [0.1.1] - 2026-07-15

The historical public notes for this local development version are not part of
the DSH-only source increment.

### Added

- Complete opt-in Codex `app-server` registered-session activation using the
  stable local stdio protocol: handshake, thread id validation, resume, one
  bounded turn, final-response capture, interrupt, and lifecycle audit.
- Backend selection across direct activation, immediate dispatch, one-shot
  workers, daemon workers, and local runtime profiles.
- Explicit unattended approval handling with a safe `decline` default and
  audit of client requests, notifications, reverse requests, and decisions.
- Provider-neutral `localRuntime.dispatchControl` and stable
  `agent_dispatch_delivery_decision.v1` results for bounded sends.
- A centralized external-operation/internal-strategy/legacy-mode mapping,
  provider backend registry with explicit capability descriptors, and a
  process-free managed-runtime contract scaffold.

### Changed

- Kept `exec_resume` as the default Codex backend and rollback-compatible path
  while making `app_server` a complete alternative rather than a partial
  probe or supplement.
- Codex app-server additional writable roots use the official resume config
  without silently forcing a sandbox or approval policy.
- Ordinary `agent-dispatch-send` now defaults to one bounded worker attempt;
  busy targets return a caller decision. Queue/daemon delivery remains an
  explicit advanced mode with its existing bounded backoff.
- Dispatch output now projects delivery, provider execution, and reply state
  independently. The current Codex app-server implementation remains one
  short-lived stdio process per operation; persistent multi-thread runtime
  ownership and `async_submit` remain unimplemented.

### Security

- App-server uses a Beacon-owned bounded stdio child and the stable API subset;
  it does not enable experimental API mode, WebSocket, Remote Control, desktop
  UI takeover, credentials, or full-session-history reads.
- Busy threads do not receive a second turn. Non-final messages, warnings,
  errors, and mismatched thread/turn events cannot complete a Beacon request.
- Beacon does not add deletion APIs or automatically select unrestricted/full-
  access provider modes.

## [0.1.0] - 2026-07-13

Public release notes: [简体中文 / English](docs/release/v0.1.0.md).

### Added

- Local workspace, agent, context, conversation, request, dispatch, status, and
  bounded provider-session coordination through the Python CLI.
- Metadata-only provider session discovery by default, with explicit bounded
  opt-ins for snippets and history.
- Localhost-only Gateway contracts with an optional Python CLI bridge.
- Idempotent provider onboarding, endpoint inventory, daemon status, lease
  recovery, runtime backoff, and reusable session-profile membership flows.
- Release hygiene, version consistency, package build, and cross-platform CI
  verification.

### Security

- Provider credentials remain environment-only and are not persisted.
- Provider reconnect, warning, and error events cannot become final Codex
  responses.
- Gateway rejects non-loopback bind targets.

### Known Limitations

- Alpha-quality local experimentation only; not a production multi-user
  service.
- Gateway does not expose the complete Python CLI coordination surface.
- Shared JSON registry updates do not provide multi-process locking.
- No LAN/public deployment, remote agent hosting, UI, or provider account
  connector is included.
Version `0.1.0` is Beacon's first public release and uses the `v0.1.0` Git tag.
