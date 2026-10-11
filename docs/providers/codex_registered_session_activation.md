# Codex Registered Session Activation

For ordinary messages use [daily CLI](../agent/agent_entry.md) or
[daily MCP](../agent/agent_mcp.md). This page is optional setup/troubleshooting
reference; read only the section for your provider task.

Status: advanced supported provider activation path.

This document describes the two local Codex registered-session activation
backends. A user or already-onboarded advanced agent registers one explicit
Codex session id and cwd, then Beacon can complete the same request/ticket,
response, and audit flow through either the established `exec resume` backend
or the opt-in structured `app-server` backend.

This is autonomous local handoff. It is not Codex desktop UI control, browser,
IDE, TUI, tmux, Remote Control, MCP server, WebSocket, LAN/public endpoint,
credential-store, or provider prompt-injection control. The app-server backend
is a Beacon-owned bounded stdio child; it does not attach to or take over a
Codex desktop window. Neither backend reads or copies complete Codex session
history.

## What It Does

- Registers a user-approved Codex session id and cwd as a platform handle for
  one workspace `agentId`.
- Resolves the platform-managed shared workspace for that `workspaceId`. The
  CLI backend renders `--add-dir`; app-server passes the same roots through the
  official `sandbox_workspace_write.writable_roots` resume configuration
  without forcing a sandbox or approval policy.
- Resolves the Codex executable before `shell=false` startup. On Windows this
  prefers a direct wrapper such as `codex.cmd` over a bare `codex` command name.
- Defaults to the established official noninteractive resume command:

```text
codex --cd <CODEX_CWD> --add-dir <PLATFORM_WORKSPACE_ROOT> exec resume --json --skip-git-repo-check --output-last-message <PLATFORM_WORKSPACE_ROOT>\codex-output\req-<REQUEST_HASH>.attempt-<ATTEMPT_HASH>.last-message.txt <CODEX_SESSION_ID> -
```

- Builds a normal platform wake ticket for the target request.
- Runs a lightweight executable preflight (`<resolved-codex> --version`) before
  writing a wake ticket for an execute attempt.
- Sends Codex a controlled stdin handoff containing the request route and
  bounded request summary. The receiving session decides whether and what to
  return through Beacon.
- Observes bounded final provider output from `--output-last-message` or trusted
  final-response events in JSON stdout. By default it records execution
  evidence but does not write that output as the Beacon reply. Each activation
  uses a unique output path so a retry cannot reuse a stale final message. JSON
  reconnect, warning, error, and lifecycle events remain diagnostics and cannot
  complete a request.
- Records provider startup before entering the blocking CLI process. If a final
  message is written but the wrapper process does not exit, Beacon allows a
  short cleanup window, terminates that activation process tree, and records
  the captured answer. A command timeout remains a failed provider lifecycle;
  a final message recovered at that boundary is marked for user review.
- Records append-only audit for ticket delivery, provider command startup,
  opportunistic session continuity evidence, response capture status, and target
  response completion.
- With `--activation-backend app_server`, starts `codex app-server --stdio`,
  completes `initialize`/`initialized`, validates the registered id using
  `thread/read(includeTurns=false)`, resumes it with `thread/resume`, starts one
  bounded `turn/start`, and captures only the target turn's completed
  `agentMessage`. The audit records native thread/turn ids, statuses, client
  requests, notifications, reverse server requests, and approval decisions.

## Register A Handle

For normal first-time Beacon onboarding, prefer `agent-join --agent
<visible-id> --provider codex --session <codex-thread-id>`; it creates or reuses
the Agent identity, exact Codex session handle, and same-named endpoint alias.
`agent-provider-onboard` and this lower-level section remain available for
advanced troubleshooting or deterministic handle registration.

Use an explicit Codex session id and the cwd/project root that should be passed
to `codex --cd`. `--handle-id` is optional; omit it unless a deterministic id
is required. Beacon generates and returns the handle id, so manual UUID
construction or shell-specific UUID tools are not required.

For a shorter current-session path, start with `agent-session-discover` and use
`agent-session-handle-register-discovered` or
`agent-endpoint-login-discovered`. The latter registers the handle and binds a
Beacon endpoint alias in one command when selection is explicit or
unambiguous.

```powershell
beacon --profile "<PROFILE_PATH>" `
  codex-session-handle-register `
  --agent-id "<TARGET_AGENT_ID>" `
  --codex-session-id "<CODEX_SESSION_ID>" `
  --cwd "<CODEX_CWD>" `
  --created-by "<USER_OR_AGENT_ID>" `
  --reason "User explicitly registered this Codex session for platform handoff."
```

List handles:

```powershell
beacon --profile "<PROFILE_PATH>" `
  codex-session-handle-list `
  --agent-id "<TARGET_AGENT_ID>"
```

Deactivate a handle:

```powershell
beacon --profile "<PROFILE_PATH>" `
  codex-session-handle-deactivate `
  --handle-id "<RETURNED_HANDLE_ID>" `
  --deactivated-by "<USER_OR_AGENT_ID>" `
  --reason "No longer authorized for automatic handoff."
```

## Dry-Run Activation

Dry-run is the default operational check. It renders the ticket path, stdin
handoff text, selected Codex argv, and permission metadata without starting
Codex. The CLI backend also renders its output-capture path.

```powershell
beacon --profile "<PROFILE_PATH>" `
  codex-registered-session-activate `
  --agent-id "<TARGET_AGENT_ID>" `
  --handle-id "<RETURNED_HANDLE_ID>" `
  --exchange-request-id "<REQUEST_ID>" `
  --dry-run
```

The output contains `codexRegisteredSessionActivation.status=dry_run` and
`providerCommandStarted=false`.

Dry-run records executable resolution metadata but does not run preflight. Check
`executableResolution.resolvedExecutable` before executing if the machine has
multiple Codex launchers.

## Select The Activation Backend

`exec_resume` remains the default and rollback backend in v0.1.1. Select the
complete app-server alternative explicitly:

```powershell
beacon --profile "<PROFILE_PATH>" `
  codex-registered-session-activate `
  --agent-id "<TARGET_AGENT_ID>" `
  --handle-id "<RETURNED_HANDLE_ID>" `
  --exchange-request-id "<REQUEST_ID>" `
  --activation-backend app_server `
  --execute
```

The same option is accepted as `--codex-activation-backend` by direct
activation and is propagated through `agent-dispatch-send --wait once`,
one-shot workers, and daemon workers. A local profile can set
`localRuntime.codexControl.activationBackend` to `exec_resume` or `app_server`;
explicit CLI input wins. The older flat `localRuntime.codexActivationBackend`
key remains a compatible alias and is reported as such in `codexControl` output.

The complete control block is:

```json
{
  "localRuntime": {
    "codexControl": {
      "activationBackend": "exec_resume",
      "statusReadMode": "beacon_snapshot",
      "supplementMode": "turn_steer",
      "replyWritebackMode": "explicit_only",
      "busyDeliveryPolicy": "queue_next_turn"
    },
    "dispatchControl": {
      "defaultDeliveryMode": "worker_execute",
      "immediateBusyPolicy": "return_to_sender"
    }
  }
}
```

Resolution is explicit command option, nested `codexControl`, compatible flat
alias, then default. Command results expose the selected values and sources.

`replyWritebackMode` accepts:

- `explicit_only` (default): provider completion is recorded, but the receiver
  chooses whether and what to send with `agent-reply`. The activation text
  explicitly says that the provider final answer is not written back and gives
  the receiver the matching short reply command.
- `provider_final_capture`: the trusted provider final message may be written
  as the request response. This is an explicit local opt-in.

The matching CLI override is `--codex-reply-writeback-mode` on dispatch/worker
commands and `--reply-writeback-mode` on direct Codex activation. The selection
is propagated through one-shot sends, workers, and daemon workers.

The unattended app-server approval decision defaults to `decline`. An operator
may explicitly choose `cancel`, `accept`, or `accept_for_session` with
`--app-server-approval-decision` (or the `--codex-...` form on dispatch/worker
commands), or set `localRuntime.codexAppServerApprovalDecision`. This setting
answers only app-server approval requests; it does not override Codex sandbox
configuration. Beacon returns empty permissions and empty user-input answers
when no safe unattended grant exists.

The app-server backend intentionally uses only the current stable stdio subset.
It does not set `experimentalApi`, use the experimental WebSocket transport,
attach to a desktop-owned app-server instance, switch a desktop task, or enable
Remote Control. CLI-only Codex installations are sufficient when their
`codex` executable provides the `app-server` subcommand.

## Codex CLI Compatibility And Protocol Schema

The original app-server implementation and earlier provider-final smoke used
the Codex 0.144.1-era stable surface. On 2026-08-23 Beacon generated the stable,
non-experimental JSON schemas from isolated exact Codex CLI 0.149.0 and compared
them with exact 0.145.0 and 0.146.0 bundles. The expanded checker passes all
three. This is static/schema and fake-transport evidence only: the current
0.149-compatible implementation has not completed a new authenticated
real-provider or real-machine smoke.

App-server TypeScript and JSON schemas are version-specific. Generate them from
the exact CLI under assessment with `codex app-server generate-ts --out
<DIR>` or `codex app-server generate-json-schema --out <DIR>`; do not treat a
schema generated by another Codex version as an evergreen contract. Beacon
continues to omit initialize capabilities, so `experimentalApi` remains off.

The 0.149 comparison adds `isBlocking` to the stable
`item/tool/requestUserInput` parameters and adds unrelated queue/section
methods and notifications; it does not remove any Beacon-required method.

After `thread/resume`, Beacon requires the official effective `cwd`, `sandbox`,
and `approvalPolicy` response fields before it can call `turn/start`. The cwd
must match the registered cwd. Sandbox and approval may be equal or narrower
than explicit activation settings, but may not widen them;
`workspaceWrite.writableRoots` must stay within the registered cwd plus the
explicit add-dir allowlist, and network access is rejected unless the operator
explicitly requested `danger-full-access`. When sandbox or approval was not explicitly
overridden, `dangerFullAccess` and `never` are still rejected. Missing,
granular/unknown, or expanded evidence fails closed and is recorded as
requested/effective app-server policy metadata.

`item/completed` remains the full item-stream source. Codex 0.146.0 and later may also
include the last non-empty final agent message in a successful
`turn/completed` summary. Beacon consumes that summary as a bounded fallback
when the item stream was dropped and deduplicates it when the same final message
was already completed. Nested `error` notifications and `deprecationNotice`
content are retained only as bounded diagnostics; they never become a provider
reply. Beacon does not use deprecated `item/fileChange/outputDelta` or other
delta notifications as final-response sources; the authoritative sources are
completed agent-message items and the bounded `turn/completed` summary.

Stable server requests are correlated to the verified thread, active turn,
item id, and unique request id before Beacon returns any decision. Requests for
another thread, a stale turn, a missing item, or a duplicate id receive a
JSON-RPC error and are never approved. Command/file approvals, permission
grants, MCP elicitation, and tool user-input responses follow their versioned
response schemas. The `serverRequest/resolved` notification is counted and
safely ignored; Beacon never invents a second response for it. Notifications
or requests before the initialize/initialized handshake and duplicate response
ids fail deterministically.

`agent-runtime-preflight` reports a separate additive `codexAppServer` protocol
check. It runs only `<resolved-codex> app-server --help`, verifies the stdio and
JSON-schema-generation surface, and does not start a server or read a session.
Passing this probe demonstrates command availability, not end-to-end provider
compatibility. The current `--stdio` flag remains equivalent to `--listen
stdio://`; Beacon keeps the existing spelling for compatibility.

For a version-bound contract check, run `python
scripts/check_codex_app_server_schema.py --codex-executable <CODEX_PATH>` from
the Beacon repository. The script generates JSON schemas in a temporary
directory and checks the methods, request/response required fields, critical
schema references, permission/approval enums, and stable initialization
defaults used by Beacon. Deprecated compatibility notifications may be
observed but are not required, and `thread/rollback` remains out of scope. It
does not start app-server or read a session. A previously generated bundle can
be checked with `--schema-dir <DIR>`.

## Read One Codex Session Status

`codex-session-status` accepts the Beacon workspace, agent, and registered
handle. It never starts a provider turn. The default `beacon_snapshot` mode
uses Beacon runtime, lease, and handle state only:

```powershell
beacon --profile "<PROFILE_PATH>" `
  codex-session-status `
  --agent-id "<TARGET_AGENT_ID>" `
  --handle-id "<RETURNED_HANDLE_ID>"
```

Use `--status-read-mode app_server_point_read` for one short-lived stable stdio
connection that performs `initialize` and `thread/read(includeTurns=false)`,
then closes. It does not call `thread/resume` or `turn/start`. A live
Beacon-owned activation is preferred because it is the only status source that
can truthfully report `canSteer=true`. An active thread observed through a
separate point-read connection is unowned and cannot be steered by that
connection. `thread not found` includes guidance to verify `CODEX_HOME` and
refresh or re-register the native thread id.

When a Codex session is discovered with an explicit or environment-selected
`CODEX_HOME`, Beacon stores that non-secret runtime-home identity with the
registered handle. Point reads, app-server activation, and exec-resume then use
the same home. Old handles without this metadata retain the previous process or
provider-default behavior. The path is audit metadata only; credentials and
session history are not copied.

Runtime audit uses `codex_app_server_runtime.v1` and records only bounded
identity, ownership, state, and timestamps. It does not persist the activation
prompt, full history, reasoning, secrets, or full response in the runtime
record. A closed connection or dead owner PID makes `canSteer=false`.

On Windows, owner-process liveness is checked with a read-only Win32 process
handle and a zero-time wait. Beacon never uses `os.kill(pid, 0)` for this check:
Python implements non-console Windows signals through process termination.
Closed historical runtime records are treated as non-live without probing their
old PID, which also avoids PID-reuse false positives.

## Supplement The Current Turn

`codex-session-supplement` is a separate, explicit operation for guidance that
belongs in the currently active Codex turn. It does not create a new turn and
does not imply that the target produced a response:

```powershell
beacon --profile "<PROFILE_PATH>" `
  codex-session-supplement `
  --agent-id "<TARGET_AGENT_ID>" `
  --handle-id "<RETURNED_HANDLE_ID>" `
  --message "Preserve the existing public API while completing this turn." `
  --expected-turn-id "<CURRENT_NATIVE_TURN_ID>" `
  --submitted-by "<SOURCE_AGENT_ID>" `
  --supplement-id "<STABLE_IDEMPOTENCY_ID>" `
  --wait once
```

The command writes a durable Beacon inbox record. Only the runner that owns the
same live app-server stdio connection drains that inbox and calls stable
`turn/steer(threadId, expectedTurnId, input)`. This prevents a separate process
from claiming an unrelated runtime connection. Callers decide whether
supplement semantics are appropriate; ordinary work remains a new
request/dispatch.

Results use `queued`, `accepted`, `rejected`, `stale_turn`, `no_active_turn`,
`runtime_unavailable`, `runtime_not_owned`, `supplement_disabled`, or
`delivery_unknown`. `accepted` means app-server accepted guidance for the
existing turn; it does not mean a new turn or final response exists. Beacon
records `delivery_unknown` before the stdio write so a crash or disconnect is
never automatically resent. Inspect the target turn before using a new
supplement id. Reusing the same `supplementId` is idempotent.

## Busy Delivery Policy

Provider-neutral `localRuntime.dispatchControl` makes a normal send perform one
bounded attempt and return a busy decision to the caller. It never converts a
normal request into `turn/steer`. A busy decision offers the separate
supplement command only when the status result proves that Beacon owns the
matching active runtime and `canSteer=true`; otherwise it offers explicit queue
or cancel only.

`localRuntime.codexControl.busyDeliveryPolicy` remains compatible and defaults
to `queue_next_turn` when no higher-level immediate decision applies. Existing
explicit worker/daemon backoff remains 5/15/30/60 seconds. Set it to `reject`, or pass
`--codex-busy-delivery-policy reject` on dispatch, worker, or daemon commands,
for a deterministic failed dispatch when the Codex target is already busy or
blocked. The reject path neither queues another provider activation nor
converts the request into supplemental guidance.

An explicitly configured Codex busy policy keeps priority over the
provider-neutral immediate default. For a merely queued dispatch, the worker or
daemon profile in effect when the dispatch is consumed selects the policy. A
one-shot sender option is not stored as a permanent worker profile.

## Platform Workspace Permission Standardization

The activation permission scope is intended to be the platform-managed project
exchange workspace. A workspace is the shared local exchange space for one
logical project, so Codex, Claude, Hermes, or other registered sessions that
cooperate on that project should normally receive access to the same platform
workspace.

A typical layout is:

```text
<PLATFORM_WORKSPACE_ROOT>/
  platform.sqlite3
  plugins/
  wake-tickets/
  codex-output/
  participants/<agent-id>/
  links/<link-id>/
```

The CLI backend defaults to path reachability only:

```text
--add-dir <PLATFORM_WORKSPACE_ROOT>
```

`--sandbox` and `--ask-for-approval` are permission profile arguments, not
defaults. If the user explicitly supplies a profile such as
`--sandbox-mode workspace-write --approval-policy never`, activation audit
records `providerPermissionProfile.selected=true` and
`selectionSource=explicit_activation_arguments`.

For app-server, the equivalent additional roots are passed in
`thread/resume.config.sandbox_workspace_write.writable_roots`; `sandbox` and
`approvalPolicy` remain absent unless explicitly selected. This preserves the
same permission posture while avoiding CLI-only flags.

This differs from the Claude adapter in one important way: Codex also receives
`--cd <CODEX_CWD>`. Under an explicit `workspace-write` profile, the registered
cwd may be writable as part of Codex's workspace. If `<CODEX_CWD>` is the real
project directory, the activation may grant write access there as well as to the
platform exchange workspace. To keep the activation limited to the platform
exchange area, either register a Codex session/cwd that is already scoped to
that platform workspace, choose a narrower explicit sandbox profile, or rely on
an explicit receiver-selected reply.

Never use unrestricted/full-access as Beacon's default. That mode can modify or
delete any file the provider process can reach; keep version control or backups,
use the narrowest writable roots, and inspect destructive changes before
accepting them.

## Execute Activation

Execution starts a local Codex process with `shell=false`, the registered cwd,
and a controlled stdio boundary. Without a backend option it uses
`exec_resume`; add `--activation-backend app_server` for the structured path.

```powershell
beacon --profile "<PROFILE_PATH>" `
  codex-registered-session-activate `
  --agent-id "<TARGET_AGENT_ID>" `
  --handle-id "<RETURNED_HANDLE_ID>" `
  --exchange-request-id "<REQUEST_ID>" `
  --platform-workspace-root "<PLATFORM_WORKSPACE_ROOT>" `
  --codex-path "<USER_PROFILE>\AppData\Roaming\npm\codex.cmd" `
  --execute
```

The command first resolves the Codex executable and runs `<resolved-codex>
--version`. If that preflight fails, activation records `status=failed`,
`providerCommandStarted=false`, `executablePreflight.status=failed`, and a
`failureCategory` such as `executable_not_found` or
`executable_permission_denied`; it does not claim that the provider command
started. If preflight passes, the command writes a wake ticket, records wake
delivery, starts the selected backend, and records the activation attempt. For
`exec_resume`, Beacon observes final provider output from
`--output-last-message` or an explicit JSON final-response event.
The output-last-message file has priority. JSON stdout fallback accepts Codex
`item.completed` agent messages and the legacy final `result` shape; it never
promotes reconnect, warning, error, or thread/turn lifecycle text. Under the
default `explicit_only` policy, even trusted final output does not become the
target response. The receiver chooses whether to use `agent-reply`.

For `app_server`, Beacon verifies that `thread/read` returns the registered
native id before resuming. An `active` thread fails as
`app_server_thread_busy` with `retryable=true`; Beacon does not start a second
turn, and a later worker retry is allowed. A normal completion requires the
matching `turn/completed` event. Reasoning, commentary-only messages, warnings,
errors, and messages from another thread or turn cannot complete the Beacon
request. Timeout triggers a best-effort `turn/interrupt` followed by bounded
process-tree cleanup. With `provider_final_capture` enabled, a trusted final
message may be written as the response; otherwise it remains execution output.

If the command times out, provider activation is failed and the request remains
unanswered by default. Under `provider_final_capture`, a trusted final message
already present at the timeout boundary may be written with
`requiresUserReview=true`, while the provider lifecycle still remains failed.

`--codex-path` is an alias for `--codex-executable`. Use either one when the
default executable resolution is ambiguous.

## Registered Cwd Git Check

For the `exec_resume` backend, Beacon defaults to
`--codex-git-repo-check-policy skip`. It renders
`--skip-git-repo-check` after `exec resume --json`, so activation can reach a
valid registered session whose cwd is not itself a Git repository.

This changes only Codex's repository-location precondition. It does not add a
directory, alter `--sandbox`, alter `--ask-for-approval`, bypass confirmation,
or grant credentials. Audit output records `gitRepoCheck.policy`, its source
(`default`, `profile`, or `explicit_cli`), and whether the skip flag was
rendered. App-server does not render this CLI-only flag; its registered thread
is validated with `thread/read` before resume.

Use strict mode when the provider's native repository check is required:

```powershell
beacon --profile "<PROFILE_PATH>" `
  codex-registered-session-activate `
  --agent-id "<TARGET_AGENT_ID>" `
  --handle-id "<RETURNED_HANDLE_ID>" `
  --exchange-request-id "<REQUEST_ID>" `
  --codex-git-repo-check-policy strict `
  --execute
```

For a local runtime profile, set
`localRuntime.codexGitRepoCheckPolicy` to `skip` or `strict`. An explicit CLI
option takes precedence. The same policy is passed through direct activation,
`agent-dispatch-send --wait once`, one-shot workers, and daemon workers.

If strict mode exits with `codex_git_repo_check_failed`, inspect the registered
cwd and either use a Git working directory or deliberately choose the default
`skip` policy. Do not solve this error by expanding sandbox access or changing
approval settings.

## Windows Launcher Notes

Windows shell lookup and Python `subprocess(shell=false)` do not always choose
the same Codex launcher. In particular, an extensionless npm shim or a
WindowsApps `codex.exe` can fail even when PowerShell appears to find `codex`.

Recommended Windows smoke command:

```powershell
beacon --profile "<PROFILE_PATH>" `
  codex-registered-session-activate `
  --agent-id "<TARGET_AGENT_ID>" `
  --handle-id "<RETURNED_HANDLE_ID>" `
  --exchange-request-id "<REQUEST_ID>" `
  --codex-path "<USER_PROFILE>\AppData\Roaming\npm\codex.cmd" `
  --execute
```

The adapter now resolves bare `codex` to a direct path where possible and writes
both requested and resolved executable values into activation audit. Prefer the
npm `codex.cmd` wrapper when it exists. Treat a WindowsApps `codex.exe`
permission failure as an environment launcher problem, not as proof that the
request/ticket path failed.

If another agent writes a failure diagnosis after a launcher/preflight failure,
it should use `agent-exchange-request-respond --response-source
manual_or_proxy_diagnostic --actual-writer-agent-id <ITS_AGENT_ID>
--requires-user-review`. That response is a platform diagnostic, not proof that
the registered Codex session processed the request.

## Current Smoke Status

Registered-session activation has passed the current minimum closed-loop
standard for a registered Codex session:

- The implementation is covered by fake Codex fixture tests, including command
  rendering, executable preflight audit, failure classification, wake ticket
  delivery audit, explicit versus provider-final reply writeback, app-server
  handshake/read/resume/turn lifecycle, approvals, busy/timeout/error handling,
  completion-summary fallback, nested error/deprecation diagnostics, and local
  runtime CLI register/list/dry-run.
- `turn/steer` supplement behavior is closed only by unit tests, a fake
  app-server, and isolated SQLite concurrency tests. No real Codex thread was
  steered for this release; a real smoke requires separate user authorization.
- A user-provided wake ticket reached the current Codex target session through
  the registered-session handoff path, and the target session wrote a platform
  response confirming the Claude-to-Codex handoff arrived.
- An earlier Claude-to-Codex smoke correctly exposed a Windows launcher failure
  before provider command startup. The adapter now resolves `codex` to a usable
  `.cmd` wrapper where possible, supports `--codex-path`, and records
  executable preflight diagnostics.
- For `exec_resume`, `sessionContinuityVerified` is opportunistic because it
  depends on output exposing the session id. For app-server it requires both a
  successful `thread/read` id match and a verified non-expanding
  `thread/resume` permission result.
- Keep smoke database, plugins directory, wake tickets, and output capture under
  a workspace-local platform exchange directory, for example
  `<PROJECT_ROOT>\.smoke\codex-registered-session`.
- Inspect `failureCategory`, `executableResolution`, and
  `executablePreflight` when activation fails before retrying.
- The controlled stdin handoff includes the request route and bounded summary.
  The wake ticket retains a compact structured inspect/respond action for cases
  where the summary explicitly lacks required detail.
- On Windows, `CreateProcessAsUserW failed: 5` is a Codex sandbox/runner failure,
  not evidence that Beacon's request database or response API is unavailable.
  Provider-final capture may avoid target-side Beacon CLI writeback when it is
  explicitly enabled; it does not repair the provider's sandbox implementation.
- Source agents should not repeatedly re-enter or poll the target Codex session
  after triggering delivery. Request creation plus wake delivery is the handoff
  point; use bounded status checks.

## Boundaries

The current app-server implementation is one short-lived stdio child per
operation. It does not keep one server alive to manage multiple registered
threads, even though the upstream protocol supports thread-scoped methods and
events. Beacon's `app_server_point_read` is a bounded read, not an owned-live
subscription to a Codex desktop/CLI instance opened by the user or another
process. Persistent multi-thread ownership remains a future managed-runtime
capability.

Beacon does not automatically enable dangerous/unrestricted full-access modes
or add provider-facing deletion operations. Keep sandbox and approval choices
explicit and use the narrowest practical permission scope.

Do not use this path for Codex desktop-app current-panel takeover, TUI input
injection, `codex resume` interactive UI control, `codex fork`, `codex
mcp-server`, `remote-control`, WebSocket, LAN/public exposure, credential
storage, or complete session-history export. The supported app-server backend
is a Beacon-owned stdio child only; it is not a desktop-app attachment API.
