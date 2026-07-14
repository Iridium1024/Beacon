# Beacon Agent Entry

Status: external agent start point for the local Beacon exchange platform.

Use this file first when a user explicitly asks an external CLI-capable agent
to work through Beacon. Beacon is a local request, dispatch, and status board.
It is not a provider-owned live connector, desktop takeover path, browser/TUI
input bridge, credential store, or generic runtime host.

Commands below assume Beacon is installed in an activated virtual environment.
Without activation, use `.\.venv\Scripts\beacon.exe` on Windows or
`./.venv/bin/beacon` on Linux/macOS. The advanced compatibility entrypoint is
`python -m agent_os.local_runtime` from an environment where the package is
installed.

## First Reads

For normal use, read only:

1. `BEACON.md`
2. `docs/agent/agent_entry.md`
3. one task-specific provider note from `docs/providers/provider_guides.md`,
   only when the task involves registered-session activation or local CLI
   preflight.

Do not start from migration state, migration handoff, old version records, real
smoke histories, or private development progress records unless the user
explicitly asks for migration, history, or troubleshooting context. Those
internal materials are not part of the standalone Beacon repository.

## First Onboarding Checklist

If you only need the short command map, start with:

```powershell
beacon agent-help --topic onboarding
beacon agent-help --topic session
beacon agent-help --topic status
```

If Windows Python Launcher is unavailable, use any Python 3.11 or newer
interpreter. `--profile` accepts a local JSON profile file path, not an inline
JSON string.

Before sending or receiving through Beacon, confirm this order:

1. Initialize or receive a local runtime profile with `workspaceId`, database,
   workspace root, and plugins directory.
2. Prefer the high-level onboarding command to create/reuse the local agent,
   provider session handle, and endpoint alias in one idempotent path:

```powershell
beacon --profile "<PROFILE_PATH>" `
  agent-provider-onboard `
  --provider "<claude|codex|hermes>" `
  --agent-id "<AGENT_ID>" `
  --agent-name "<DISPLAY_NAME>" `
  --endpoint-alias "<ALIAS>" `
  --direction both
```

3. Run the inventory status command to confirm the workspace agent, provider
   handle, endpoint alias, and alias dispatch readiness:

```powershell
beacon --profile "<PROFILE_PATH>" `
  agent-onboarding-status `
  --endpoint-alias "<ALIAS>" `
  --format pretty
```

   For deeper per-alias queue/runtime detail, use
   `agent-endpoint-status --alias <ALIAS>`.
4. Confirm the explicit endpoint identity with
   `agent-endpoint-identity --alias <alias>`, then dispatch with
   `agent-dispatch-send --as <alias> --to <alias>`.

Endpoint login is Beacon-local addressing metadata. It is not provider account
login, does not store credentials, and does not create a provider session.
`--as` is an explicit routing declaration, not caller authentication. Beacon
does not prevent a local caller from naming another source alias; review the
returned `actingIdentity` and `routeSummary` before relying on the direction.

If the same approved local Claude/Codex/Hermes session must be reused across
multiple Beacon workspaces, register a local provider session profile first and
explicitly join each workspace:

```powershell
beacon `
  --provider-session-registry "<SHARED_REGISTRY_PATH>" `
  provider-session-profile-register `
  --provider "<claude|codex|hermes>" `
  --session-id "<PROVIDER_SESSION_ID>" `
  --profile-alias "<LOCAL_PROFILE_ALIAS>" `
  --cwd "<SESSION_CWD>" `
  --created-by "<USER_OR_AGENT_ID>" `
  --reason "User approved local provider session reuse."

beacon --profile "<PROFILE_PATH>" `
  --provider-session-registry "<SHARED_REGISTRY_PATH>" `
  provider-session-workspace-join `
  --session-profile-id "<PROFILE_ID>" `
  --agent-id "<AGENT_ID>" `
  --agent-name "<DISPLAY_NAME>" `
  --endpoint-alias "<WORKSPACE_LOCAL_ALIAS>" `
  --created-by "<USER_OR_AGENT_ID>" `
  --reason "Join workspace A."

beacon --profile "<SECOND_PROFILE_PATH>" `
  --provider-session-registry "<SHARED_REGISTRY_PATH>" `
  provider-session-workspace-join `
  --session-profile-id "<PROFILE_ID>" `
  --agent-id "<SECOND_AGENT_ID>" `
  --agent-name "<SECOND_DISPLAY_NAME>" `
  --endpoint-alias "<SECOND_WORKSPACE_LOCAL_ALIAS>" `
  --created-by "<USER_OR_AGENT_ID>" `
  --reason "Join workspace B."
```

The profile is not a provider account login and stores no credentials, cookies,
tokens, auth headers, or full transcript. Each join creates or reuses only that
workspace's agent, provider handle, and endpoint alias. Dispatch still uses the
workspace-local alias; there is no cross-workspace global alias. Until Beacon
has a cross-workspace provider-session lease, worker/daemon automatic
activation for these reusable profiles is disabled and reported as a warning.
Profile registration and workspace join must use the same
`<SHARED_REGISTRY_PATH>`. A generated workspace profile fixes that same path,
so subsequent commands can omit the CLI option. Status output reports the
resolved path, source, and local read/write state.

## Dispatch Rule

Normal cross-agent work is asynchronous. The sender creates a request and
dispatch record, then stops:

```powershell
beacon --profile "<PROFILE_PATH>" `
  agent-dispatch-send `
  --as "<SOURCE_ALIAS>" `
  --to "<TARGET_ALIAS>" `
  --message "<SHORT_REQUEST>" `
  --queued
```

Use a daemon or later status read to observe progress. Do not hold the source
agent in an unbounded poll or repeatedly re-enter the target provider session.
Runtime status policy defaults to `auto`: Beacon runs a local JSON status probe
only when the target handle or endpoint explicitly configures one. Use
`--runtime-status-policy disabled` to forbid probes, or the legacy
`--read-live-runtime-status` alias for `enabled`.

For a short bounded synchronous request, use one worker pass:

```powershell
beacon --profile "<PROFILE_PATH>" `
  agent-dispatch-send `
  --as "<SOURCE_ALIAS>" `
  --to "<TARGET_ALIAS>" `
  --message "<SHORT_REQUEST>" `
  --wait once
```

`--wait once` is the short form for `worker_execute`. It is a synchronous
observation window: an external terminal timeout can discard returned stdout,
but it does not delete Beacon's durable request or response. Read
`agent-dispatch-status` afterward. Worker/daemon polling reconciles terminal or
expired orphan leases without repeating an already answered request; when no
daemon is running, preview or repair with
`agent-dispatch-lease-reconcile --dry-run|--execute`.

## Reverse Handoff

If the target agent needs the source agent to act, it must create a new
target-to-source request or dispatch. Do not bury the return task inside the
old response and expect Beacon to wake the source side automatically.

```powershell
beacon --profile "<PROFILE_PATH>" `
  agent-dispatch-send `
  --as "<TARGET_ALIAS>" `
  --to "<SOURCE_ALIAS>" `
  --message "<RETURN_REQUEST>" `
  --queued
```

## Status Words

- `request created`: Beacon recorded durable intent; no delivery is implied.
- `ticket delivered`: Beacon wrote or surfaced a local handoff ticket.
- `provider command started`: Beacon started the configured provider CLI
  subprocess.
- `provider command failed`: provider activation failed before a target response.
- `target runtime blocked`: the session is waiting on an agent, external
  response, or approval and is not safe to activate again.
- `waiting response stale`: the response wait exceeded its warning threshold;
  Beacon reports `manual_review` but does not retry or close it automatically.
- `session continuity verified`: provider output gave Beacon enough metadata to
  infer resume/session continuity. It is best-effort, not proof of completion.
- `target response completed`: the target wrote a standard Beacon response or
  Beacon captured an allowed stdout fallback response.
- `standard_respond written`: the target explicitly used Beacon's response API.

Use `agent-dispatch-status --dispatch-id <ID> --format compact` for the short
layered view. It omits the full timeline and wake ticket while retaining the
recommended next action. `--from` remains a backward-compatible alias for
`--as`; supplying both with different values is rejected.

Busy or blocked targets remain queued with bounded 5/15/30/60-second backoff.
The status view exposes the skip count, last skip, delay, and next attempt. A
`waiting_response` record is never selected by the ordinary worker; aging is an
advisory signal with explicit manual retry/expiry options.

`standard_respond` means the target used Beacon's response API. `stdout
fallback` means provider stdout/stderr was captured as a fallback response.
Manual retry should create a new request or explicitly marked dispatch retry;
platform worker retry stays on the same dispatch with retry metadata.

## Feedback Records

Smoke and test feedback belong outside durable shared context unless the user
asks to promote it. In the standalone repository, keep feedback in user-chosen
private notes or issue/PR discussion rather than inside Beacon onboarding docs.
