# Hermes Registered Session Activation

For ordinary messages use [daily CLI](../agent/agent_entry.md) or
[daily MCP](../agent/agent_mcp.md). This page is optional setup/troubleshooting
reference; read only the section for your provider task.

Status: implemented as a bounded provider-specific registered-session adapter.

This document describes both implemented Hermes activation backends. Beacon
stores a user-approved saved-session handle, writes one wake ticket, starts one
short-lived provider process for the operation, and records append-only audit
events. `cli` remains the default and rollback route. `tui_gateway` is an
explicit opt-in route pinned to the audited PyPI `hermes-agent==0.19.0` surface.

## Default CLI route

The adapter renders:

```text
hermes chat --query <platform handoff> --quiet --resume <session-id> --source agent-os
```

The query is intentionally short and points Hermes to the wake ticket JSON. The
ticket contains the request, thread, and platform response command details.

The adapter does not use `-z` / `--oneshot`, because local help describes that
mode as automatically bypassing approvals. It also does not use `--yolo`,
worktree mode, gateway/webhook/send, OAuth/secrets, MCP/ACP server startup,
desktop input injection, browser input injection, or TUI automation.

## Opt-in TUI Gateway route

The implemented backend id is `hermes_tui_gateway_stdio`. It launches the
gateway from the same exact Python environment that is preflighted:

```text
<gateway-python> -u -m tui_gateway.entry
```

PyPI `0.19.0` supplies the module but no `tui_gateway` console script, so Beacon
does not invent one. The process is operation-owned stdio JSON-RPC/JSONL. It is
closed after the activation; Beacon does not connect to a desktop-owned
gateway, use WebSocket, expose an HTTP endpoint, or keep a persistent runtime.

The only handshake is the `method=event`, `type=gateway.ready` notification.
Beacon never sends an `initialize` RPC. It then performs this bounded identity
flow before sending the prompt:

1. `session.list` must contain exactly one row matching the registered
   persistent session id and registered source.
2. `session.resume` receives the persistent id. Both `resumed` and
   `session_key` must return that exact persistent id.
3. The returned `session_id` is a process-local runtime id. It is expected to
   differ from the persistent id, is used for submit/events/status/interrupt,
   and is never written back to the handle registry.
4. Resume `info.cwd` must match the registered cwd. Stable `0.19.0` does not
   expose every home/source field in that result, so the audit distinguishes
   gateway verification from registered-source evidence instead of claiming
   more than the protocol proves.
5. `prompt.submit` carries only the runtime id and wake-ticket prompt. Ordinary
   activation never sends rewind/truncation fields.

Only one matching, non-empty `message.complete` event with
`payload.status=complete` can be considered a provider final. Deltas, tool
events, status text, errors, interaction prompts, and other-session text never
become replies. The TUI Gateway defaults to `explicit_only`; automatic final
capture is available only through explicit `provider_final_capture` selection
and still requires the verified identity and terminal-event checks.

Approval, clarification, sudo, and secret prompts are event notifications, not
generic reverse requests. For stable `0.19.0`, approval is denied through
`approval.respond` scoped by runtime session id; clarify/sudo/secret responses
use their event `request_id`. Beacon sends an empty/deny response, never reads or
supplies a password or secret, fails closed on unknown/duplicate/expired ids,
and marks interaction-bearing results for user review. Timeout or cancellation
sends at most one `session.interrupt` before bounded process cleanup.

### Exact-version preflight

`tui_gateway` selection performs a read-only probe before ticket delivery. The
probe uses the selected interpreter to find the installed `hermes-agent`
distribution, package version and location, `tui_gateway.entry` and server
source, and the required method/event surface. Only exact audited `0.19.0` is
accepted. Local `0.18.0`, missing modules, and unknown/newer versions fail before
prompt submission and do not silently fall back to `hermes_cli`.

The official `main` branch reported `0.20.5` during the 2026-08-23 audit and has
already evolved interaction/clarification details. It is advisory evidence,
not an accepted runtime range. Support for it requires a new pinned capability
fixture and fake-transport audit.

## Other official programmatic interfaces

Hermes also documents ACP over stdio and an OpenAI-compatible HTTP API Server.
Neither is selected for this registered-session path. ACP's load/resume/fork
scope is tied to sessions known by the current ACP server process rather than
arbitrary saved CLI sessions in the registered `state.db`. The HTTP API Server
is a separate future remote/runtime-managed path.

ACP is not selected for this registered-session path because its documented
load/resume/fork scope is tied to sessions known by the current ACP server
process, rather than arbitrary saved CLI sessions in the registered
`state.db`. The HTTP API Server is a useful future remote/runtime-managed path,
but is likewise separate from the current exact local CLI-session contract.
See [`provider_programmatic_interfaces.md`](provider_programmatic_interfaces.md)
for the full status matrix and official references.

## Commands

For normal first-time Beacon onboarding, prefer `agent-provider-onboard`; it
creates or reuses the agent identity, registers or reuses the Hermes session
handle, and logs in or reuses the endpoint alias. Use the lower-level
provider-specific commands below for advanced troubleshooting or deterministic
handle registration.

Register a user-approved Hermes session handle:

```powershell
beacon --profile "<PROFILE_PATH>" `
  hermes-session-handle-register `
  --agent-id <target-agent-id> `
  --hermes-session-id <hermes-session-id> `
  --cwd <target-cwd> `
  --hermes-home <hermes-runtime-home> `
  --hermes-session-source <session-source> `
  --created-by <operator> `
  --reason <reason>
```

`--handle-id` is optional; omit it unless a deterministic id is required.
Beacon generates and returns the handle id, so manual UUID construction or
shell-specific UUID tools are not required. For a shorter current-session path,
start with `agent-session-discover` and use
`agent-session-handle-register-discovered` or
`agent-endpoint-login-discovered`.

`--hermes-home` identifies the Hermes data directory containing `state.db`.
`--hermes-session-source` identifies the source under which the existing
session was created, commonly `cli`. These values describe the registered
session and are retained when the session is joined to a workspace. The
activation command's `--source-tag` is separate: it labels the new Beacon
query and does not select the existing session inventory.

Dry-run activation:

```powershell
beacon --profile "<PROFILE_PATH>" `
  hermes-registered-session-activate `
  --agent-id <target-agent-id> `
  --handle-id <returned-handle-id> `
  --exchange-request-id <request-id> `
  --dry-run
```

Execute activation:

```powershell
beacon --profile "<PROFILE_PATH>" `
  hermes-registered-session-activate `
  --agent-id <target-agent-id> `
  --handle-id <returned-handle-id> `
  --exchange-request-id <request-id> `
  --execute
```

Opt in to the stable TUI Gateway backend:

```powershell
beacon --profile "<PROFILE_PATH>" `
  hermes-registered-session-activate `
  --agent-id <target-agent-id> `
  --handle-id <returned-handle-id> `
  --exchange-request-id <request-id> `
  --hermes-activation-backend tui_gateway `
  --hermes-gateway-python "<python-from-hermes-0.19.0-environment>" `
  --execute
```

Add `--hermes-reply-writeback-mode provider_final_capture` only when automatic
capture is explicitly desired. Omitting it gives `explicit_only` for the
gateway. The CLI backend retains historical provider-final capture unless
overridden with `--hermes-reply-writeback-mode explicit_only`.

If a custom Hermes executable is needed, pass `--hermes-executable` or
`--hermes-path`. If omitted, the adapter resolves bare `hermes` through
`agent-runtime-preflight`. Pass `--hermes-home` during activation only when the
handle was registered without one. Beacon rejects an explicit activation home
that conflicts with the home already stored on the handle.

## Discovery Diagnostics

When a runtime home contains `state.db`, Beacon reads session identifiers,
source tags, working directories, and timestamps from the structured session
inventory. It does not read message bodies, titles, or previews. Older or
unknown Hermes layouts fall back to `hermes sessions list`.

An empty result is accompanied by `discoveryDiagnostics`. The main categories
are:

- `no_sessions`: discovery completed but no matching sessions were returned.
- `source_filter_mismatch`: sessions exist, but not under the requested source.
- `runtime_home_mismatch`: the expected session is absent from the selected home.

Command launch, timeout, and non-zero exit failures remain in
`discoveryErrors`; they are not reported as an empty successful inventory.

## Nonblocking Operation

`hermes-registered-session-activate --execute` is a bounded delivery attempt,
not a synchronous request/response RPC. The source agent should create the
request, trigger one activation, then stop or perform one bounded
`agent-wake-status` / request-status check. It should not keep re-entering the
Hermes session or wait indefinitely for `targetResponseCompleted=true`.

This matters when the target request says "do not reply" or the target Hermes
session needs user-side time. A timeout can still mean the wake ticket reached
Hermes and Hermes is processing or intentionally not writing a platform
response. In that case, inspect `providerCommandStarted`, `ticketPath`,
`responseCaptureStatus`, and any target-side platform records instead of
blocking the current source session.

Wake ticket paths are platform-generated. Consumers must read the recorded
`ticketPath` instead of reconstructing paths from ids. The shared default
ticket path strategy uses short stable hash components for workspace, agent,
request, and ticket ids, so this Windows path-length hardening applies to
Hermes, Codex, and Claude registered-session activation alike.

## Desktop Hermes

Desktop Hermes can be used by the user to log in and create or confirm a usable
Hermes session. Activation still uses a new bounded CLI or TUI Gateway process;
it never takes over the desktop process. The handle stores the approved id,
cwd, and optional runtime-home/source identity. It does not store credentials,
tokens, cookies, message history, or desktop state.

The local preflight may find Hermes through PATH or an explicit executable
profile. If a desktop-created `tui` session is not visible to the CLI, pass the
user-approved provider runtime home through an explicit profile or CLI argument.
Historical desktop runtime-home examples are private development material; do
not copy operator-specific paths into release-facing request payloads.

Without the matching runtime home, `hermes chat --resume <session-id>` can fail
with `Session not found` even though the session id is valid in the desktop app.
This is an environment/runtime-home issue, not a platform request-board or
wake-ticket failure.

## Audit And Completion

Activation audit records include:

- `executableResolution`
- `executablePreflight`
- `providerCommandStarted`
- `sessionContinuityVerified`
- `expectedSessionVerification=verified|mismatch|unverified`
- `cliReportedSessionId`
- `runtimeHome` and `runtimeHomeSource`
- `continuityEvidenceSource` and `continuityConfidence`
- `responseCaptureMode=hermes_chat_query_stdout`
- `responseCaptureStatus`
- `responseInstanceVerified`
- `responseRequiresUserReview`
- `targetResponseCompleted`
- `failureCategory`
- `retryable`
- `activationBackend=cli|tui_gateway`
- `replyWritebackMode=explicit_only|provider_final_capture`
- `providerRuntimeMetadata.preflight` and, after launch,
  `providerRuntimeMetadata.run`
- `runtimeSessionId` for the gateway's process-local id

Target Hermes actively running the platform respond command is the stronger
completion path. Stdout auto-capture is an independent fallback and retains
`responseSource=hermes_chat_query_auto_capture`; it is never relabeled as a
standard target response.

Only an explicit Hermes resume banner for the registered session, or a verified
compression redirect to its successor, sets `expectedSessionVerified=true`.
Command arguments, echoed query text, and plain `session_id=` output are not
continuity evidence. An explicit different resumed session is a failed
activation and its stdout is not recorded as the response. If stdout is usable
but session continuity cannot be verified, Beacon may preserve it for
compatibility while setting `responseRequiresUserReview=true` and
`responseInstanceVerified=false`.

For `tui_gateway`, continuity instead comes from the exact list/resume/cwd
identity flow. A runtime id differing from the persistent id is normal and is
not a continuity warning. Gateway stdout is protocol framing, never a response
capture source.
