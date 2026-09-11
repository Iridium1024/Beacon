# Beacon Agent Entry

Status: external agent start point for the local Beacon exchange platform.

Use this file first when a user explicitly asks an external CLI-capable agent
to work through Beacon. Beacon is a local request, dispatch, and status board.
It is not a provider-owned live connector, desktop takeover path, browser/TUI
input bridge, credential store, or generic runtime host. The sole managed
runtime exception is the explicit, opt-in Beacon-owned DeepSeek Harness
backend described below.

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

## Already-Joined DeepSeek Harness Agents

Do not run `agent-join --new-session` again when receiving ordinary work.
Use the delivered `beacon.agent_communication.v1` context: it identifies your
workspace, Agent, native session, handle and (when unambiguous) sending alias.
Its `actions` contain executable argv arrays for self/member/inbox/request
queries, optional reply and new sends, with the exact Beacon interpreter and
profile. No virtual-environment activation is required; apply only the supplied
`runtimeEnvironment.PYTHONPATH`, not a copy of another process's environment.
`shellExamples` contains separately quoted Bash and PowerShell forms.

Start with `agent-onboarding-status --provider dsh --agent-id <YOUR_AGENT_ID>`;
use `--native-session-id <EXACT_NATIVE_ID>` to resolve a registered mapping.
This is workspace inventory, not external DSH session discovery. Outside the
project, use the delivered explicit `--profile`; never guess the database or
identity from cwd. Query members before selecting `--to`; `--as` is routing,
not authentication. Reply only if you choose. A provider final in
`explicit_only` mode is not a Beacon response; source-side action needs a new
directed request, not text buried in the old reply.

See [the DSH use and preparation guide](docs/providers/deepseek_harness_managed_runtime.md)
for the complete command sequence and failure boundaries.

## First Onboarding Checklist (One-Time Preparation)

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

1. Initialize the project once. This writes a local
   `.beacon/workspace.json` marker that points to the isolated runtime profile.
   Commands launched anywhere below that project directory resolve the nearest
   marker deterministically; Beacon does not ask an Agent to scan local
   databases to guess the project scope:

```powershell
beacon agent-workspace-init `
  --project-root "<PROJECT_ROOT>" `
  --workspace-id "<WORKSPACE_ID>" `
  --display-name "<WORKSPACE_NAME>"
```

2. Join the current provider session with one visible Agent ID. This single
   idempotent command preflights and then creates or reuses the Agent, exact
   native session handle, and same-named endpoint alias. Exact lookup is not
   limited to the recent-session inventory count, and another visible Agent
   cannot silently claim the same active native session:

```powershell
beacon agent-join `
  --agent "<VISIBLE_AGENT_ID>" `
  --provider "<claude|codex|hermes>" `
  --session "<NATIVE_SESSION_ID>"
```

DeepSeek Harness supports the same exact-id form when its approved official
JSONL persistence root and compression are configured. The persisted header
supplies the authoritative cwd, and initialization resumes the native session
before Agent/handle/endpoint registration:

```powershell
beacon agent-join `
  --workspace-id "<WORKSPACE_ID>" `
  --agent "<VISIBLE_AGENT_ID>" `
  --provider dsh `
  --session "<NATIVE_SESSION_ID>" `
  --dsh-session-root "<APPROVED_DSH_SESSION_ROOT>"
```

To create a new Beacon-owned session instead:

```powershell
beacon agent-join `
  --workspace-id "<WORKSPACE_ID>" `
  --agent "<VISIBLE_AGENT_ID>" `
  --provider deepseek_harness `
  --new-session `
  --cwd "<PROJECT_ROOT>"
```

This resumes persisted history but does not take over an arbitrary live
DSH Web/TUI/Desktop process. Read
`docs/providers/deepseek_harness_managed_runtime.md` for storage, compression,
live-owner, stop/resume, and ambiguity rules before enabling it.

3. Run the inventory status command to confirm the workspace agent, provider
   handle, endpoint alias, and alias dispatch readiness:

```powershell
beacon agent-onboarding-status `
  --agent-id "<VISIBLE_AGENT_ID>" `
  --endpoint-alias "<VISIBLE_AGENT_ID>" `
  --format pretty
```

   For deeper per-alias queue/runtime detail, use
   `agent-endpoint-status --alias <ALIAS>`.
4. Dispatch using only the visible source and target IDs:
   `agent-dispatch-send --as <source-id> --to <target-id> --message <request>`.

`--profile` remains available for explicit operation outside the project tree.
An explicit profile, profile environment variable, and nearest project marker
must agree; conflicts fail instead of silently selecting another workspace.
`agent-provider-onboard` and separate discovery/handle/endpoint commands remain
advanced compatibility interfaces, not the normal onboarding path. The
advanced-only `--allow-shared-session-binding` override must be opted into when
one provider-native session is intentionally modeled under multiple visible
Agents; ordinary `agent-join` rejects that ownership ambiguity.

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

The default public operation is `send`, implemented as one bounded inline
attempt. The internal compatibility label is `worker_execute`; `--wait once`
selects the same behavior, so a caller can use the short form below for a
confirmation or concise question without first starting a daemon:

```powershell
beacon --profile "<PROFILE_PATH>" `
  agent-dispatch-send `
  --as "<SOURCE_ALIAS>" `
  --to "<TARGET_ALIAS>" `
  --message "<SHORT_REQUEST>"
```

The result includes `agent_dispatch_delivery_decision.v1`. If the target is
busy, Beacon returns `busy_returned` and asks the caller to choose explicitly:
use the separate Codex supplement interface only when `canSteer=true`, create
an explicit queued next-turn dispatch, or cancel. Beacon does not silently
queue, retry, or turn a normal request into steer on this path.

`--wait once` remains a compatible explicit spelling of `send`. One call
is one synchronous, bounded observation window—not a background loop. A capable
agent may call it again for a later conversational turn after examining the
previous result.

Use short requests for confirmation and concise Q&A. For complex context, put
the details in a project file and send a summary plus `--detail-ref`. For work
that should run after the caller exits, explicitly choose the advanced queue
path only after confirming that a worker, daemon, or external supervisor will
consume it:

```powershell
beacon --profile "<PROFILE_PATH>" `
  agent-dispatch-send `
  --as "<SOURCE_ALIAS>" `
  --to "<TARGET_ALIAS>" `
  --message "<LONG_RUNNING_REQUEST>" `
  --queued
```

Queued mode persists request/dispatch state only. It does not start a provider,
check target runtime state, or auto-start a daemon. Use a daemon or later status
read to observe progress. Do not hold the source agent in an unbounded poll.
Runtime status policy defaults to `auto`: Beacon runs a local JSON status probe
only when the target handle or endpoint explicitly configures one. Use
`--runtime-status-policy disabled` to forbid probes, or the legacy
`--read-live-runtime-status` alias for `enabled`.

The legacy explicit bounded form remains:

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

Receiving a request does not require the target to reply. When it chooses to
reply, the short interface is:

```powershell
beacon agent-reply `
  --request "<REQUEST_ID>" `
  --agent "<RECEIVER_VISIBLE_ID>" `
  --message "<SELECTED_REPLY>"
```

Provider execution completion and a Beacon reply are separate states. Codex
final provider output is not written back as a reply by default; automatic
writeback is an explicit local policy opt-in.

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
  an explicitly enabled provider-final capture policy wrote one.
- `standard_respond written`: the target explicitly used Beacon's response API.

Use `agent-dispatch-status --dispatch-id <ID> --format compact` for the short
layered view. It omits the full timeline and wake ticket while retaining the
recommended next action. `--from` remains a backward-compatible alias for
`--as`; supplying both with different values is rejected.

Busy or blocked targets remain queued with bounded 5/15/30/60-second backoff
only in the explicit worker/daemon queue path. The default immediate send
returns the decision to the caller instead. The status view exposes the skip
count, last skip, delay, and next attempt. A
`waiting_response` record is never selected by the ordinary worker; aging is an
advisory signal with explicit manual retry/expiry options.

`standard_respond` means the target used Beacon's response API. A provider
stdout/final-message fallback is used only when the corresponding local
writeback policy is explicitly enabled.
Manual retry should create a new request or explicitly marked dispatch retry;
platform worker retry stays on the same dispatch with retry metadata.

## Provider Programmatic Control

Provider-neutral send defaults can be changed in the local-only profile:

```json
{
  "dispatchControl": {
    "defaultDeliveryMode": "worker_execute",
    "immediateBusyPolicy": "return_to_sender"
  }
}
```

Explicit CLI mode flags win over this profile. `--queued` always selects the
asynchronous queue, and `--immediate-busy-policy queue_next_turn` is an explicit
opt-in when a caller intentionally wants the immediate path to preserve queued
busy behavior.

Claude keeps its CLI route as default and rollback. The opt-in public Agent SDK
route is selected under `localRuntime.claudeControl`:

```json
{
  "activationBackend": "cli",
  "replyWritebackMode": "provider_final_capture"
}
```

`activationBackend` accepts `cli` or `agent_sdk`. Writeback defaults are
backend-specific: CLI keeps historical provider-final capture, while Agent SDK
uses `explicit_only`. Install the optional SDK extra before selecting it:
`py -3.11 -m pip install -e ".\python-core[claude-agent-sdk]"`. SDK preflight
is read-only, missing/incompatible packages fail before ticket delivery, and
Beacon never silently falls back to CLI. The SDK client exists for one bounded
activation only; it is not a persistent runtime or public supplement/cancel
surface. The latest SDK implementation has not completed authenticated
real-provider/session smoke.

Hermes keeps its CLI route as default and rollback. The opt-in stable TUI
Gateway route is selected under `localRuntime.hermesControl`:

```json
{
  "activationBackend": "tui_gateway",
  "replyWritebackMode": "explicit_only",
  "gatewayPython": "<PYTHON_WITH_HERMES_0.19.0>"
}
```

`activationBackend` accepts `cli` or `tui_gateway`. The Gateway backend uses
one short-lived stdio process per activation and does not install or upgrade
Hermes. Read-only preflight requires the selected interpreter to expose the
exact stable `hermes-agent==0.19.0` protocol and launches
`python -u -m tui_gateway.entry`; local `0.18.0`, upstream-main `0.20.5`, and
unknown shapes fail without silently falling back to CLI. Gateway writeback
defaults to `explicit_only`; the historical CLI default remains provider-final
capture. No authenticated Hermes provider/session smoke has been completed.

Codex uses `exec_resume` by default. A local profile may select the complete
stable stdio backend and related behavior under `localRuntime.codexControl`:

```json
{
  "activationBackend": "exec_resume",
  "statusReadMode": "beacon_snapshot",
  "supplementMode": "turn_steer",
  "replyWritebackMode": "explicit_only",
  "busyDeliveryPolicy": "queue_next_turn"
}
```

Use `codex-session-status --agent-id <ID> --handle-id <ID>` for one registered
target. `app_server_point_read` performs only a bounded `thread/read` and never
resumes or starts a turn.

`codex-session-supplement` is deliberately separate from normal dispatch. It
queues guidance for a matching active native turn; only the Beacon runner that
owns that exact stdio connection may send `turn/steer`. `accepted` is provider
acceptance of extra input, not turn completion or a target response. Reuse a
stable `supplementId` for idempotency, and never automatically retry
`delivery_unknown`. Busy ordinary immediate dispatch returns a caller decision
by default and never steers implicitly. Explicit Codex busy configuration is
still honored; queued worker/daemon processing keeps its bounded backoff.
`replyWritebackMode` defaults to `explicit_only`, so an activated Codex session
is told that its provider final answer is not automatically registered and is
given the short `agent-reply` path. It may choose whether and what to return. Set
`provider_final_capture` only when automatic final-message writeback is desired.
The Codex home recorded during discovery is reused for point status,
app-server activation, and exec-resume; older handles without that identity
continue to use the process/default environment.
See `docs/providers/codex_registered_session_activation.md` for commands and
failure guidance.

Beacon keeps provider-neutral operations separate from provider backends:
`send`, `queue`, `supplement`, and `status` are the external meanings, while
the current execution strategies are `inline`, `queue`, and `dry_run`.
`async_submit` is reserved and is not implemented. Current backend ids are
`claude_cli`, `claude_agent_sdk`, `codex_exec_resume`,
`codex_app_server_stdio`, `hermes_cli`, `hermes_tui_gateway_stdio`, and
`deepseek_harness_sdk_stdio`.
Backend selection is reported as requested/effective values and never falls
back silently. See `docs/agent/provider_backend_contract.md`.

The current Codex app-server backend starts one short-lived stdio operation for
one activation and then closes it. Although the upstream app-server protocol
can describe multiple threads, Beacon does not yet provide a persistent
multi-thread runtime. Its point status read is not an owned-live subscription.
The exact stable 0.149 compatibility layer verifies the effective cwd,
sandbox, approval policy, and writable roots returned by `thread/resume` before
starting a turn, rejects mismatched/stale/duplicate reverse requests, and uses
only completed item/turn data for final capture. This is schema and
fake-transport evidence; a new authenticated 0.149 real-provider smoke remains
outstanding.
The Hermes TUI Gateway backend has the same operation-owned topology: one
bounded persistent-session resume and prompt turn, followed by process-tree
cleanup. It is not a daemon or a shared Gateway runtime.

The opt-in DeepSeek Harness backend has a different topology: one detached
Beacon supervisor owns one DSH runtime generation over one persistent native
session across ordinary CLI/worker calls. It can create a session or use the
official persistence/resume API to join an exact existing id. Clean stop leaves
that native session resumable; explicit resume preserves the Agent, native id,
and alias while minting a new handle/runtime/generation. Ambiguous in-flight
loss requires acknowledgement and is never replayed. `recreate` remains the
explicit new-session path. There is no public cancel, supplement, parallel
prompt, automatic DSH discovery/profile import, or foreign live Web/TUI
takeover. Evidence includes the locked official runtime/persistence with an
offline fake model; authenticated real-model/session smoke remains outstanding.

## Feedback Records

Smoke and test feedback belong outside durable shared context unless the user
asks to promote it. In the standalone repository, keep feedback in user-chosen
private notes or issue/PR discussion rather than inside Beacon onboarding docs.
