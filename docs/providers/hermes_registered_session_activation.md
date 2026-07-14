# Hermes Registered Session Activation

Status: implemented as a bounded provider-specific registered-session adapter.

This document describes the Hermes activation path. It follows the same
platform pattern as the Claude and Codex registered-session
adapters: the platform stores a user-approved session handle, writes a wake
ticket for one directed request, starts the official local CLI in a bounded
background subprocess, and records append-only audit events.

## Route

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
Hermes session. The platform still activates through the bounded local CLI
subprocess above. The handle stores the explicitly approved Hermes session id,
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
