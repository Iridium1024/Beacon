# Codex Registered Session Activation

Status: advanced supported provider activation path.

This document describes the local Codex CLI registered-session activation path.
It lets a user or already-onboarded advanced agent register one explicit Codex
session id and cwd, then ask the local platform to deliver a wake ticket to that
handle through the official noninteractive Codex CLI resume route.

This is autonomous local handoff. It is not Codex desktop UI control, browser,
IDE, TUI, tmux, Remote Control, app-server, MCP server, WebSocket, LAN/public
endpoint, credential-store, or provider prompt-injection control. It does not
read or copy complete Codex session history.

## What It Does

- Registers a user-approved Codex session id and cwd as a platform handle for
  one workspace `agentId`.
- Resolves the platform-managed shared workspace for that `workspaceId` and
  adds it to the resumed Codex process with `--add-dir`.
- Resolves the Codex executable before `shell=false` startup. On Windows this
  prefers a direct wrapper such as `codex.cmd` over a bare `codex` command name.
- Renders the official noninteractive resume command:

```text
codex --cd <CODEX_CWD> --add-dir <PLATFORM_WORKSPACE_ROOT> exec resume --json --skip-git-repo-check --output-last-message <PLATFORM_WORKSPACE_ROOT>\codex-output\req-<REQUEST_HASH>.attempt-<ATTEMPT_HASH>.last-message.txt <CODEX_SESSION_ID> -
```

- Builds a normal platform wake ticket for the target request.
- Runs a lightweight executable preflight (`<resolved-codex> --version`) before
  writing a wake ticket for an execute attempt.
- Sends Codex a controlled stdin handoff containing the request route and
  bounded request summary. The normal reply path asks the registered session
  for a direct final answer and does not require a target-side shell or Beacon
  CLI process.
- Attempts bounded output auto-capture from `--output-last-message` or trusted
  final-response events in JSON stdout. Each activation uses a unique output
  path so a retry cannot reuse a stale final message. JSON reconnect, warning,
  error, and lifecycle events remain diagnostics and cannot complete a request.
- Records provider startup before entering the blocking CLI process. If a final
  message is written but the wrapper process does not exit, Beacon allows a
  short cleanup window, terminates that activation process tree, and records
  the captured answer. A command timeout remains a failed provider lifecycle;
  a final message recovered at that boundary is marked for user review.
- Records append-only audit for ticket delivery, provider command startup,
  opportunistic session continuity evidence, response capture status, and target
  response completion.

## Register A Handle

For normal first-time Beacon onboarding, prefer `agent-provider-onboard`; it
creates or reuses the agent identity, registers or reuses the Codex session
handle, and logs in or reuses the endpoint alias. Use this lower-level section
for advanced troubleshooting or deterministic handle registration.

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
handoff text, Codex argv, output-capture path, and permission metadata without
starting Codex.

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

The current Codex adapter defaults to path reachability only:

```text
--add-dir <PLATFORM_WORKSPACE_ROOT>
```

`--sandbox` and `--ask-for-approval` are permission profile arguments, not
defaults. If the user explicitly supplies a profile such as
`--sandbox-mode workspace-write --approval-policy never`, activation audit
records `providerPermissionProfile.selected=true` and
`selectionSource=explicit_activation_arguments`.

This differs from the Claude adapter in one important way: Codex also receives
`--cd <CODEX_CWD>`. Under an explicit `workspace-write` profile, the registered
cwd may be writable as part of Codex's workspace. If `<CODEX_CWD>` is the real
project directory, the activation may grant write access there as well as to the
platform exchange workspace. To keep the activation limited to the platform
exchange area, either register a Codex session/cwd that is already scoped to
that platform workspace, choose a narrower explicit sandbox profile, or rely on
output auto-capture rather than target-side CLI writes.

## Execute Activation

Execution starts a local Codex CLI process with `shell=false`, the registered
cwd, and controlled stdin.

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
delivery, starts Codex through `exec resume`, and records the activation
attempt. The preferred current Codex completion path is the captured final
response from `--output-last-message` or an explicit JSON final-response event.
The output-last-message file has priority. JSON stdout fallback accepts Codex
`item.completed` agent messages and the legacy final `result` shape; it does not
promote reconnect, warning, error, or thread/turn lifecycle text into the target
response. A target Codex session may still read the ticket and run the platform
CLI respond command itself when its sandbox and command policy allow that, but
the adapter does not require that path for the minimum closed loop.

If the command times out without a trusted final response, provider activation
is failed and the request remains unanswered. If a trusted final response was
already written at the timeout boundary, Beacon may recover it with
`requiresUserReview=true`, while the provider lifecycle still remains failed.

`--codex-path` is an alias for `--codex-executable`. Use either one when the
default executable resolution is ambiguous.

## Registered Cwd Git Check

For an explicitly registered Codex session and its registered cwd, Beacon
defaults to `--codex-git-repo-check-policy skip`. It renders
`--skip-git-repo-check` after `exec resume --json`, so activation can reach a
valid registered session whose cwd is not itself a Git repository.

This changes only Codex's repository-location precondition. It does not add a
directory, alter `--sandbox`, alter `--ask-for-approval`, bypass confirmation,
or grant credentials. Audit output records `gitRepoCheck.policy`, its source
(`default`, `profile`, or `explicit_cli`), and whether the skip flag was
rendered.

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
  delivery audit, output-last-message capture, and local runtime CLI
  register/list/dry-run.
- A user-provided wake ticket reached the current Codex target session through
  the registered-session handoff path, and the target session wrote a platform
  response confirming the Claude-to-Codex handoff arrived.
- An earlier Claude-to-Codex smoke correctly exposed a Windows launcher failure
  before provider command startup. The adapter now resolves `codex` to a usable
  `.cmd` wrapper where possible, supports `--codex-path`, and records
  executable preflight diagnostics.
- `sessionContinuityVerified` is opportunistic. It only turns true when Codex
  output exposes the session id; a false value does not prove resume failed.
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
  The direct final-output path avoids making that shell capability a prerequisite
  for a routine registered-session reply; it does not repair the provider's
  sandbox implementation.
- Source agents should not repeatedly re-enter or poll the target Codex session
  after triggering delivery. Request creation plus wake delivery is the handoff
  point; use bounded status checks.

## Boundaries

Do not use this path for Codex desktop-app current-panel takeover, TUI input
injection, `codex resume` interactive UI control, `codex fork`, `codex
app-server`, `codex mcp-server`, `remote-control`, WebSocket, LAN/public
exposure, credential storage, or complete session-history export.
