# Claude Registered Session Activation

Status: advanced supported provider activation path.

This document describes the local Claude Code registered-session activation
path. It lets a user or already-onboarded advanced agent register one explicit
Claude Code session handle, then ask the local platform to deliver a wake
ticket to that handle through the official Claude CLI resume route.

This is autonomous local handoff. It is not browser, desktop, IDE, TUI, tmux,
Remote Control, WebSocket, LAN/public endpoint, credential-store, or provider
prompt-injection control. It does not read or copy complete Claude Code session
history.

## What It Does

- Registers a user-approved Claude Code session UUID and cwd as a platform
  handle for one workspace `agentId`.
- Resolves the platform-managed shared workspace for that `workspaceId` and
  grants it to the resumed Claude process with `--add-dir`.
- Renders the official resume command plus the bounded local permission
  options recorded in the activation audit:

```text
claude --resume <CLAUDE_SESSION_UUID> --add-dir <PLATFORM_WORKSPACE_ROOT> --print --output-format stream-json --verbose
```

- Builds a normal platform wake ticket for the target request.
- Sends Claude a controlled stdin handoff that points at the wake ticket path
  and the platform CLI read/respond commands.
- Attempts a bounded stdout auto-capture fallback: if Claude exits
  successfully, the request is still active, and Claude emitted final text in
  `stream-json`, the platform records that text as the target agent's response.
- Records append-only audit for:
  - ticket delivery;
  - provider command started;
  - session continuity evidence when Claude output exposes the session id;
  - response capture status;
  - target response completion, which is true when the target agent responds
    through the platform request API or when stdout auto-capture records a
    fallback response.

## Register A Handle

For normal first-time Beacon onboarding, prefer `agent-provider-onboard`; it
creates or reuses the agent identity, registers or reuses the Claude session
handle, and logs in or reuses the endpoint alias. Use this lower-level section
for advanced troubleshooting or deterministic handle registration.

Use an explicit Claude Code session UUID and the cwd/project root that owns the
session. `--handle-id` is optional; omit it unless a deterministic id is
required. Beacon generates and returns the handle id, so manual UUID
construction or shell-specific UUID tools are not required.

For a shorter current-session path, start with `agent-session-discover` and use
`agent-session-handle-register-discovered` or
`agent-endpoint-login-discovered`. The latter registers the handle and binds a
Beacon endpoint alias in one command when selection is explicit or
unambiguous.

```powershell
beacon --profile "<PROFILE_PATH>" `
  claude-session-handle-register `
  --agent-id "<TARGET_AGENT_ID>" `
  --claude-session-uuid "<CLAUDE_SESSION_UUID>" `
  --cwd "<CLAUDE_PROJECT_ROOT>" `
  --created-by "<USER_OR_AGENT_ID>" `
  --reason "User explicitly registered this Claude Code session for platform handoff."
```

List handles:

```powershell
beacon --profile "<PROFILE_PATH>" `
  claude-session-handle-list `
  --agent-id "<TARGET_AGENT_ID>"
```

Deactivate a handle:

```powershell
beacon --profile "<PROFILE_PATH>" `
  claude-session-handle-deactivate `
  --handle-id "<RETURNED_HANDLE_ID>" `
  --deactivated-by "<USER_OR_AGENT_ID>" `
  --reason "No longer authorized for automatic handoff."
```

## Dry-Run Activation

Dry-run is the default operational check. It renders the ticket path, stdin
handoff text, and Claude argv without starting Claude.

```powershell
beacon --profile "<PROFILE_PATH>" `
  claude-registered-session-activate `
  --agent-id "<TARGET_AGENT_ID>" `
  --handle-id "<RETURNED_HANDLE_ID>" `
  --exchange-request-id "<REQUEST_ID>" `
  --dry-run
```

The output contains `claudeRegisteredSessionActivation.status=dry_run` and
`providerCommandStarted=false`.

## Platform Workspace Permission Standardization

The activation permission scope is the platform-managed project workspace, not
the target agent's private session history and not necessarily the real source
repository. A workspace is the shared local exchange space for one logical
project, so Codex, Claude, Hermes, or other registered sessions that cooperate
on that project should normally receive access to the same platform workspace.

The platform workspace may contain the local database, wake tickets, plugins,
request/thread materialization, participant scratch space, and link-specific
subdirectories. A typical layout is:

```text
<PLATFORM_WORKSPACE_ROOT>/
  platform.sqlite3
  plugins/
  wake-tickets/
  participants/<agent-id>/
  links/<link-id>/
```

The current Claude adapter defaults to adding that shared root to the resumed
Claude process:

```text
--add-dir <PLATFORM_WORKSPACE_ROOT>
```

If `--platform-workspace-root` is omitted, the platform derives the root from
the common parent of the platform database, plugins directory, and wake-ticket
path. For smoke runs this should be a workspace-local directory such as
`<PROJECT_ROOT>\.smoke\claude-registered-session`; for later normal
use it should be a platform-created project exchange directory such as
`.agent-workspaces\<workspace-id>`.

The `--add-dir` default only standardizes path access. If a registered Claude
session must write files, create link directories, or run platform CLI
commands without repeated prompts, the user should authorize a platform
workspace full-access profile for that shared root. The activation command can
now record and render the following explicit options:

```powershell
--platform-workspace-root "<PLATFORM_WORKSPACE_ROOT>" `
--allowed-tool "<CLAUDE_TOOL_OR_PATTERN>" `
--permission-mode "acceptEdits" `
--settings-path "<CLAUDE_SETTINGS_FILE>"
```

The intended policy is: full access is limited to the platform workspace.
Access to the real project directory remains outside the default platform
grant and should be handled by the user and the target agent's own project
configuration. Link folders under the platform workspace may be created by the
platform or by an authorized agent, but they remain within the same shared
workspace permission scope.

Observed smoke behavior on 2026-06-26: resuming the same Claude session with
the same `--add-dir <PLATFORM_WORKSPACE_ROOT>` behaved idempotently; the target
reported no duplicated permission state, session-history confusion, or degraded
behavior. With `--permission-mode acceptEdits`, the target could write a short
note under `links/<link-id>/` in the platform workspace. Running the platform
CLI through a Bash subprocess was still a separate approval boundary, so
stdout auto-capture remained the completion fallback for that run.

The target Claude session suggested one bounded route for the Bash respond
boundary: a user-provisioned Claude settings profile that allows only the
platform CLI respond shape. Treat this as a preflight configuration candidate,
not as an adapter default, until the installed Claude Code settings schema is
validated for the user's version. Example intent:

```json
{
  "allow": [
    {
      "tool": "Bash",
      "pattern": "^beacon\\b.*\\bagent-exchange-request-respond\\b.*"
    }
  ]
}
```

Use `--settings-path <CLAUDE_SETTINGS_FILE>` to pass a user-approved settings
file when that profile exists. Do not auto-write `.claude/settings.json` from a
woken agent, and do not use this pattern to allow arbitrary Bash commands. If
no validated settings profile is present, onboarding agents must tell the user
that platform CLI `respond` may still require manual Claude Code approval even
when `--add-dir` and `acceptEdits` let the session read/write the platform
workspace.

## Execute Activation

Execution starts a local Claude CLI process with `shell=false`, the registered
cwd, and controlled stdin.

```powershell
beacon --profile "<PROFILE_PATH>" `
  claude-registered-session-activate `
  --agent-id "<TARGET_AGENT_ID>" `
  --handle-id "<RETURNED_HANDLE_ID>" `
  --exchange-request-id "<REQUEST_ID>" `
  --platform-workspace-root "<PLATFORM_WORKSPACE_ROOT>" `
  --execute
```

The command writes a wake ticket, records wake delivery, starts Claude through
`--resume`, and records the activation attempt. The preferred completion path is
still that the target Claude agent reads the request/thread and responds through
`agent-exchange-request-respond`.

If Claude cannot run the platform response command because the CLI session is
waiting for tool permission, the interaction may stop at that permission
boundary. Current onboarding should warn the user about this before enabling
registered-session activation. The target agent should confirm whether it is
allowed to run the platform CLI read/respond commands; otherwise the request
may remain active and require manual review.

An experimental stdout auto-capture fallback exists for later validation. It
parses Claude's captured `stream-json` stdout after the process exits and can
write a non-empty final answer through the normal request response path with
metadata `responseSource=claude_stdout_auto_capture`. Do not rely on this as the
current completion path: real-session smoke has shown that permission-blocked
interactions may produce no capturable stdout text. This fallback does not read
or export complete Claude session history and does not grant Claude additional
tool permissions.

## Current Bootstrap Behavior

Registered-session activation is still a bootstrap/smoke-stage path. Operators
should expect some friction until a later profile/adapter optimization step:

- For real target-agent smoke tests, keep the smoke database, plugins directory,
  and wake-ticket handoff directory under the registered project root, for
  example `<PROJECT_ROOT>\.smoke\...`. Avoid `%TEMP%` for these files
  when the target agent's allowed workspace is the project root; otherwise
  Claude Code may block reads or command execution because the ticket/database
  paths sit outside the approved project directory. This only solves the
  location/read boundary. It does not grant write or subprocess permission.
- Real workspace-local smoke has observed the following split: reading a wake
  ticket under `.smoke` can proceed without extra prompts, while creating
  directories, writing markdown files, or running platform CLI subprocesses may
  still stop at Claude Code's tool-approval boundary. Design smoke success
  criteria accordingly.
- The first resume attempt can take noticeable time because it starts a fresh
  local Claude CLI process and lets Claude reload the project/session state.
- The controlled stdin handoff is intentionally verbose today. It includes the
  ticket path, database path, workspace root, plugins directory, and read/respond
  commands so an unconfigured target session can act without hidden local state.
- On Windows, use `claude.cmd` for Python `subprocess` execution. PowerShell's
  `claude.ps1` wrapper is not directly executable with `shell=false`.
- Claude Code 2.1.193 requires `--verbose` with
  `--output-format stream-json`.
- Some wrapper scripts may see non-JSON text if an external CLI prints an error
  before the platform command returns JSON. Treat that as a smoke harness issue
  and inspect `agent-wake-status` for the authoritative state.

## Permission Preflight

Claude Code separates readable project context from tool execution. A resumed
session can usually read a workspace-local wake ticket, but file writes,
directory creation, and subprocess execution can still require approval.

Before using registered-session activation for a target that must write files
or run the platform CLI, ask the user whether that Claude Code session should
receive scoped tool permissions for the shared platform workspace. This is a
project-level exchange space shared by registered participants; it is not a
per-session private folder and it is not the real project directory unless the
user deliberately makes those paths the same.

Known permission routes in the local Claude Code CLI surface include:

- `--add-dir <path>`: allow an additional directory tree for tool access. The
  adapter now defaults this to the shared platform workspace root and records
  the path in `permissionStandardization`. This is treated as path
  reachability, not as a blanket permission-mode grant.
- `--allowedTools` / `--allowed-tools`: allow specific tool names or tool
  patterns. Use this only with narrowly scoped patterns.
- `--permission-mode <mode>`: session permission mode. Prefer scoped modes such
  as `acceptEdits` or `auto` only after user approval; avoid broad bypass modes
  as a default.
- `--settings <file-or-json>`: load settings from a file or JSON string. This is
  the right place for persistent project policy once the settings schema is
  explicitly validated. A narrow Bash allowlist for
  `agent_os.local_runtime ... agent-exchange-request-respond` is the preferred
  future route for zero-popup platform CLI respond, but it is not generated by
  the current adapter.
- `--dangerously-skip-permissions` or `--permission-mode bypassPermissions`:
  bypass permission checks. This is not a safe default for this project and
  should only be used in an isolated sandbox after explicit user approval.

Do not let an agent silently grant itself broader authority. The current
implementation can render and audit `--add-dir`, `--allowedTools`,
`--permission-mode`, and `--settings`/`--settings-path`, but bypass permission
modes remain unsupported here. If a settings file is used to permit Bash, file
writes, or platform CLI execution, keep the rules scoped to the platform
workspace root.

By default, activation does not inject `--allowedTools`, `--permission-mode`, or
`--settings`. If one of those arguments is explicitly supplied, activation audit
records `providerPermissionProfile.selected=true` and
`selectionSource=explicit_activation_arguments`; otherwise it records
`selected=false` and `selectionSource=default_no_permission_profile`.

## Status

Check the request wake status:

```powershell
beacon --profile "<PROFILE_PATH>" `
  agent-wake-status `
  --exchange-request-id "<REQUEST_ID>"
```

Important fields:

- `ticketDeliveryOccurred`: a platform wake ticket was delivered.
- `providerCommandStarted`: a Claude CLI resume command was started.
- `sessionContinuityVerified`: Claude output contained the registered session
  UUID.
- `targetResponseCompleted`: the target agent responded through the platform,
  or stdout auto-capture recorded a fallback response through the same request
  response path.
- `responseCaptureMode`: `claude_stdout_stream_json` when stdout auto-capture
  was evaluated.
- `responseCaptureStatus`: `recorded`, `already_responded`,
  `no_response_text`, `request_not_active`, `respond_failed`, or
  `not_attempted_command_failed`.
- `autoCapturedResponseSourceEventSequence`: present when stdout auto-capture
  wrote the request response.
- `runtimeWakeTriggered`: true only when a provider command was started.
- `realRuntimeConnected`: remains false because the platform did not host or
  take over Claude's runtime.

## Boundaries

- Use `--resume <session uuid>` for exact registered-session activation.
- Do not use `--continue` as the default exact target route.
- Do not use `--fork-session`; it creates a different session.
- Do not use `--no-session-persistence`; it breaks resume continuity.
- Do not enable Remote Control, Chrome/IDE integration, tmux, worktree
  creation, WebSocket, LAN/public exposure, or desktop/browser/TUI input
  injection in this path.
- Do not store API keys, OAuth tokens, cookies, authorization headers, session
  tokens, or keychain material in handle metadata.
- Do not read, export, summarize, delete, migrate, or modify complete Claude
  Code session history.
