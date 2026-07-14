# Agent Runtime Preflight

Status: implemented as a read-only local CLI diagnostic layer.

This document describes the standardized preflight check used before registering
or activating external CLI-shaped agents such as Claude Code, Codex CLI, Gemini
CLI, and Hermes.

## Boundary

The preflight command is diagnostic only.

It does not install, update, uninstall, repair, delete environment variables,
write provider config, create credentials, inject input into a UI, open remote
control, or start a provider session. It only enumerates local executable
candidates and runs bounded tool-specific executable probes. Most tools use
`--version`; Hermes uses `--help` because the local desktop/CLI bundle can hang
on version-style probes.

The command still uses the normal `agent_os.local_runtime` entrypoint, so callers
must pass the platform database, workspace root, and plugins directory arguments.
The preflight itself does not write agent/provider configuration.

## Command

```powershell
$env:PYTHONPATH="<PROJECT_ROOT>\python-core\\src"
beacon `
  --database "<PROJECT_ROOT>\.smoke\runtime-preflight\platform.sqlite3" `
  --workspace-root "<PROJECT_ROOT>" `
  --plugins-directory "<PROJECT_ROOT>\.smoke\runtime-preflight\plugins" `
  --pretty `
  agent-runtime-preflight `
  --tool claude `
  --tool codex `
  --tool gemini `
  --tool hermes `
  --ticket-path "<PROJECT_ROOT>\.beacon\workspaces\demo\wake-tickets\ticket.json" `
  --response-path "<PROJECT_ROOT>\.beacon\workspaces\demo\output\response.json"
```

Alias:

```text
agent-runtime-doctor
```

If `--tool` is omitted, the command checks the current default set:

```text
claude, codex, gemini, hermes
```

Supported tool ids:

```text
claude, codex, gemini, hermes, opencode, openclaw
```

## Output Contract

The top-level response has schema `agent_runtime_preflight_report.v1`.

Important fields:

- `readOnly`, `noInstallAttempted`, `noRepairAttempted`,
  `noCredentialOrConfigWrite`: fixed boundary markers.
- `summary.checked`: number of checked tool ids.
- `summary.activationReady`: number of tools with a runnable recommended
  executable.
- `tools[].status`: `available`, `installed_but_broken`, or `not_found`.
- `tools[].recommendedExecutable`: the path that activation adapters should
  prefer when present.
- `tools[].pathDefault`: the command path resolved from PATH, when available.
- `tools[].hasConflict`: true when multiple candidates differ by version or
  include a mix of runnable and broken candidates.
- `tools[].candidates[]`: individual executable candidates with path, source,
  probe result, runnable state, and error details. The `version` field is a
  version string when the tool exposes one; Hermes reports
  `help_probe_passed` when the bounded `--help` probe succeeds.
- `activationCapabilities.ticketPathReadable`: whether an explicitly supplied
  wake ticket path exists and can be read. If `--ticket-path` is omitted, this
  reports `status=not_configured`.
- `activationCapabilities.responsePathWritable`: whether the parent directory
  for an explicitly supplied response/output path appears writable. This is a
  non-mutating parent-directory check; it does not create a response file.
- `activationCapabilities.subprocessAllowed`: whether this Python process can
  start a bounded child process with `shell=False`.
- `activationCapabilities.platformCliRunnable`: whether
  `python -m agent_os.local_runtime --help` can run as a local platform CLI
  subprocess.
- `activationCapabilities.providerExecutableFound`: provider executable
  availability summarized separately from path/response/platform checks.
- `activationCapabilities.providerPermissionProfiles`: per-provider default
  permission profile state. Default preflight reports `selected=false` and
  `selectionSource=default_no_permission_profile`; path reachability parameters
  such as `--add-dir` are classified separately from permission, sandbox,
  approval, allowed-tools, settings, and dangerous-bypass parameters.

## Current Windows Behavior

The Windows probe intentionally checks direct executable candidates such as:

```text
<dir>\codex.cmd
<dir>\codex.exe
<dir>\codex
```

This catches the common mismatch where PowerShell appears to find `codex`, but a
background `subprocess(shell=False)` activation needs a usable wrapper such as
`<USER_PROFILE>\AppData\Roaming\npm\codex.cmd`. Extensionless npm shims and
WindowsApps launchers may be reported as candidates but not runnable.

Typical Windows outcomes:

- Claude Code: activation-ready through npm `claude.cmd`.
- Codex CLI: activation-ready through npm `codex.cmd`; WindowsApps Codex
  resource entries are detected but not suitable for background activation.
- Gemini CLI: activation-ready through npm `gemini.cmd`.
- Hermes: activation-ready through PATH, an explicit executable profile, or a
  bounded `--help` probe against an approved local install path. If the current
  process does not inherit Hermes on PATH, preflight reports the warning instead
  of treating request-board routing as failed.

## How Adapters Should Use It

For future provider-specific activation:

1. Run preflight before registering or executing a session handle.
2. If `status=not_found`, stop before attempting activation.
3. If `status=installed_but_broken`, surface the candidate error and ask the
   user to fix the local install.
4. If `hasConflict=true`, prefer `recommendedExecutable` explicitly instead of a
   bare command name.
5. Record the relevant preflight result in activation audit when practical.

Current adapter linkage:

- Codex registered-session activation resolves the default bare `codex` command
  through this preflight layer before rendering `codex exec resume`. Explicit
  paths still bypass discovery and are respected as user-provided inputs.
- Claude registered-session activation resolves the default bare `claude`
  command through this preflight layer before rendering `claude --resume`, and
  records the executable resolution in activation audit. Explicit paths still
  bypass discovery and are respected as user-provided inputs.
- Hermes registered-session activation resolves the default bare `hermes`
  command through this preflight layer before rendering
  `hermes chat --query <platform handoff> --quiet --resume <session-id>
  --source agent-os`. Explicit paths still bypass discovery and are respected
  as user-provided inputs.

This linkage only selects the correct local executable path. It does not change
the provider-specific activation recipe, session-handle model, credential
policy, permission model, or transport boundary.

## Permission Profile Boundary

Provider activation defaults are frozen to avoid silently broadening provider
permissions:

- Claude defaults may pass path reachability through
  `--add-dir <platform-workspace-root>`, but they do not inject
  `--allowedTools`, `--permission-mode`, `--settings`, or bypass-permission
  flags unless explicitly supplied.
- Codex defaults may pass path reachability through `--add-dir`, but they do
  not inject `--sandbox`, `--ask-for-approval`, or dangerous bypass flags unless
  explicitly supplied.
- Hermes defaults do not inject dangerous permission flags such as `--yolo`.

When an explicit provider permission profile is supplied through activation
arguments, activation audit includes `providerPermissionProfile.selected=true`
and `selectionSource=explicit_activation_arguments`. Otherwise the audit records
`selected=false` and `selectionSource=default_no_permission_profile`. Permission
shortages should therefore be reported as provider permission or capability
issues, not as platform communication failures.

## Related Session Discovery

Beacon also provides a separate metadata-only helper for finding provider
session ids before handle registration:

```powershell
beacon --profile "<PROFILE_PATH>" `
  agent-session-discover `
  --provider "codex"
```

That command is not a replacement for runtime preflight. Preflight answers
"which local executable can be safely started by a background subprocess?"
Session discovery answers "which local provider session ids look suitable for
explicit handle registration?"

`agent-session-discover` may scan Claude/Codex local session metadata or run a
bounded `hermes sessions list` command. It reports `registrationReady` and
`missingFields`, and it must not export full session transcript bodies or
credentials. `agent-session-handle-register-discovered` then reuses the existing
provider-specific handle registration paths after the user chooses a candidate.
`agent-endpoint-login-discovered` can additionally register the discovered
handle and bind an endpoint alias in one command when selection is explicit or
unambiguous.
Handle ids are generated by Beacon when omitted. Endpoint login remains
Beacon-local routing metadata; it is not provider account authentication and
does not store credentials.
