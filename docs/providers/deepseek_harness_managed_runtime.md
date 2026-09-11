# DeepSeek Harness Managed Runtime

Status: opt-in fourth Agent platform with exact persisted-session join and
cross-runtime resume; authenticated real-model smoke remains pending.

For credential-free source-installation steps, the optional carrier, and the
distinction between source delivery and a future installer, see
[`../release/source-installation.md`](../release/source-installation.md). That
guide does not claim a verified authenticated DSH configuration.

## What Beacon Owns

`deepseek_harness` (alias `dsh`) is an Agent platform/provider id, separate
from a `deepseek` model preset. Its only Beacon backend is
`deepseek_harness_sdk_stdio`.

Beacon supports two onboarding modes:

- `--session <NATIVE_SESSION_ID>` finds exactly that session in the configured
  official JSONL persistence root and resumes it.
- `--new-session` creates a new native session in an isolated per-session
  persistence directory.

The native session id, persisted history, Beacon Agent id, and endpoint alias
survive a clean runtime stop. A later `deepseek-harness-runtime-resume` creates
a new handle, runtime id, and generation id while retaining the same native
session, Agent, and alias. `recreate` is deliberately different: it creates a
new native session.

This is not arbitrary takeover of a DSH Web/TUI/Desktop process that is
already running. Beacon owns the SDK server processes it starts. A process
already joined through Beacon is reused idempotently; a second live Beacon
owner for the same persistence root and native id is rejected. Stop the known
owner cleanly, reuse it, or select a different session. Beacon does not inject
input into another application's window or claim ownership of a foreign live
process.

## Audited Upstream Route

The reviewed source anchor is DeepSeek Harness commit
`b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`. The project-local Node carrier
pins the DSH packages to exact `0.1.1-rc.2` in
`integrations/deepseek-harness-node/package-lock.json`. It uses the public
`ctx.agents.resume({ resumeSessionId })` capability and official
`@deepseek-ai/dsh-session-persistence-jsonl` store. A thin Beacon SDK-server
adapter chooses `create` or `resume` before the platform publishes an Agent,
handle, or endpoint. It does not implement a replacement session store.

The Node SDK server currently reports wire `serverInfo.version=0.0.1`; package
pin and wire version are checked separately. Windows uses Node 22.19+ because
the official Python runtime wheels do not include Windows. The Python carrier
remains available only for new-session mode on a supported wheel platform;
exact persisted-session resume currently requires the audited Node carrier.

## Runtime and Continuity Model

```text
Beacon CLI / worker / daemon
        | authenticated loopback JSONL IPC
        v
one detached Beacon supervisor (one handle + generation)
        | strict JSON-RPC 2.0 JSONL over stdio
        v
one official DSH SDK server process
        | create or resume
        v
one persistent native DSH session
```

The supervisor binds only `127.0.0.1` on an ephemeral port. An owner token,
workspace/Agent/handle/runtime/generation identity, generation lease, stable
native-session owner lease, operation lease, nonce, and PID/start evidence
prevent cross-generation attachment and concurrent Beacon writers. PID alone
is never authority. One prompt may own the native session at a time; another
send returns `target_runtime_busy` without prompting, queuing, steering,
replaying, or creating a session.

Only `initialize`, `session/prompt`, and `shutdown` requests and the documented
session/subagent notifications are accepted. There is no public cancel,
active-turn supplement, parallel prompt, or protocol negotiation.

`messageId` is prompt receipt evidence, not completion. Provider-final capture
requires the matching root-session inbox receipt, a later non-empty root
assistant message, successful root turn end, and a later root idle event.
Malformed, oversized, duplicate, out-of-order, unknown, timed-out, or
disconnected flows fail closed. Once prompt bytes may have been sent, delivery
is ambiguous and Beacon never automatically replays that request.

## One-Time Configuration and Preflight

No global package install or upgrade is performed. Install the optional locked
carrier locally when authorized:

```powershell
Set-Location integrations\deepseek-harness-node
npm.cmd ci
```

Configure the local profile. For an existing session, `sessionRoot` must be
the exact root originally configured for the official JSONL persistence
plugin; `sessionCompression` must also match (`zstd` by default or `none`).
For new sessions the configured value is a base root and Beacon creates one
subdirectory per native id.

```json
{
  "localRuntime": {
    "deepseekHarnessControl": {
      "enabled": false,
      "activationBackend": "managed_runtime",
      "carrier": "node",
      "executablePath": "<NODE_EXECUTABLE>",
      "packageRoot": "<PROJECT_ROOT>/integrations/deepseek-harness-node",
      "cordisConfigPath": "<PROJECT_ROOT>/integrations/deepseek-harness-node/cordis.yml",
      "runtimeHome": "<APPROVED_ISOLATED_DSH_HOME>",
      "stateRoot": "<LOCAL_BEACON_RUNTIME_STATE>",
      "sessionRoot": "<APPROVED_DSH_SESSION_ROOT>",
      "sessionCompression": "zstd",
      "modelProvider": "deepseek",
      "model": "deepseek-chat",
      "replyWritebackMode": "explicit_only"
    }
  }
}
```

Read-only preflight for a known native session:

```powershell
beacon deepseek-harness-runtime-preflight `
  --dsh-carrier node `
  --dsh-executable "<NODE_EXECUTABLE>" `
  --dsh-package-root "<PROJECT_ROOT>/integrations/deepseek-harness-node" `
  --dsh-cordis-config "<PROJECT_ROOT>/integrations/deepseek-harness-node/cordis.yml" `
  --dsh-session-root "<APPROVED_DSH_SESSION_ROOT>" `
  --dsh-session-compression zstd `
  --session "<NATIVE_SESSION_ID>"
```

The probe calls the official persistence `list()` path and compares the exact
id across all returned headers; it does not use a recent-display limit or read
full history. It reports a missing id, ambiguous identity, unreadable or
incompatible storage, wrong compression, package/version mismatch, missing
adapter/config, path access problem, or unsupported carrier explicitly.

## Join an Existing Session

Initialize/select the Beacon workspace first, then join the existing native
session. `--cwd` may be omitted: the persisted session header is authoritative.
If supplied, it must resolve to the same directory.

```powershell
beacon agent-join `
  --workspace-id "<WORKSPACE_ID>" `
  --agent "<VISIBLE_AGENT_ID>" `
  --provider dsh `
  --session "<NATIVE_SESSION_ID>" `
  --dsh-session-root "<APPROVED_DSH_SESSION_ROOT>" `
  --dsh-session-compression zstd
```

Initialization resumes the exact native id before any platform registration
writes occur. An unknown id never becomes a new empty session. Beacon creates
the Agent only when it does not already exist; the same Agent can therefore
join without inventing another identity. It then creates a managed handle and
same-named endpoint. Repeating the same join while that exact Agent/endpoint
owner is live returns the existing binding rather than starting another
writer. Conflicting Agent, alias, cwd, storage, or live-owner bindings fail.

Automatic DSH discovery and reusable provider-session profiles remain
unsupported. That does not block exact join when the operator supplies the
native id and persistence root. `agent-onboarding-status --provider dsh
--native-session-id <ID>` searches Beacon's registered workspace mappings
only; it is not native session discovery.

## Create a New Session

```powershell
beacon agent-join `
  --workspace-id "<WORKSPACE_ID>" `
  --agent "<VISIBLE_AGENT_ID>" `
  --provider dsh `
  --new-session `
  --cwd "<PROJECT_ROOT>"
```

New mode mints a native id. It does not replace the existing-session command
and is not a recovery action.

## Everyday Communication

After either join mode, native runtime parameters stay on the handle. Normal
traffic uses the provider-neutral commands; do not repeat the DSH runtime
configuration for every request:

```powershell
beacon agent-onboarding-status --provider dsh --agent-id "<YOUR_AGENT_ID>" --alias "<YOUR_ALIAS>"
beacon agent-onboarding-status --workspace-id "<WORKSPACE_ID>"
beacon agent-exchange-request-list --workspace-id "<WORKSPACE_ID>" --target-agent-id "<YOUR_AGENT_ID>" --status active
beacon agent-exchange-status --workspace-id "<WORKSPACE_ID>" --exchange-request-id "<REQUEST_ID>" --format compact
beacon agent-reply --workspace-id "<WORKSPACE_ID>" --request "<REQUEST_ID>" --agent "<YOUR_AGENT_ID>" --message "<CHOSEN_REPLY>"
beacon agent-dispatch-send --workspace-id "<WORKSPACE_ID>" --as "<YOUR_ALIAS>" --to "<TARGET_ALIAS>" --message "<NEW_REQUEST>"
```

Inside a project, the nearest `.beacon/workspace.json` marker selects the
profile. Outside it, pass the same explicit `--profile`. Generated communication
contexts include exact argv and a minimal `PYTHONPATH`, so an activated virtual
environment is not required and paths with spaces or shell metacharacters stay
separate arguments.

The receiver decides whether, when, and what to reply. In `explicit_only`
mode, Provider completion remains separate from a Beacon reply.
`provider_final_capture` is opt-in and uses only the trusted causal final
described above. Replying does not wake the source Agent; request source-side
action through a new directed request. Related work uses explicit thread and
parent ids. Queued mode requires a separately confirmed worker/daemon and does
not start one.

## Stop, Resume, and Recreate

```powershell
beacon deepseek-harness-runtime-status --workspace-id "<WORKSPACE_ID>" --handle-id "<HANDLE_ID>"

beacon deepseek-harness-runtime-stop --workspace-id "<WORKSPACE_ID>" --handle-id "<HANDLE_ID>" --acknowledge-runtime-stop

beacon deepseek-harness-runtime-resume --workspace-id "<WORKSPACE_ID>" --handle-id "<OLD_HANDLE_ID>"

beacon deepseek-harness-runtime-recreate --workspace-id "<WORKSPACE_ID>" --handle-id "<OLD_HANDLE_ID>" --acknowledge-continuity-loss
```

An idle stop asks DSH to shut down cleanly, marks the old handle inactive, and
leaves the persistent native session resumable. Resume uses the old handle's
authoritative package, root, compression, cwd, model, and runtime settings. It
keeps the native session id, Beacon Agent, and endpoint alias, but registers a
new handle/runtime/generation and rebinds the alias. It does not replay a prior
request.

If a runtime fails or is forcibly stopped during an active operation, the last
delivery is ambiguous. Resume is then blocked until the operator explicitly
accepts non-replay with `--acknowledge-ambiguous-delivery`. Inspect the request
and dispatch records first. A live runtime resume request is an idempotent
no-op. `recreate` always creates a different native session and must not be
used to claim history continuity.

Gateway exposes no DSH onboarding/runtime routes in this release. The local
dispatch daemon uses the same worker and supervisor IPC; it is not the native
session owner.

## Evidence and Remaining Limits

Persistent Beacon metadata contains ids, approved paths, versions, bounded
lifecycle evidence, and watermarks—not the owner token, prompt, final text,
tool output, credentials, or full transcript. The preflight header probe does
not materialize history. DSH itself reads the selected persistence root and
runtime home when its official runtime starts.

Automated coverage includes fake-protocol causality/failure tests,
cross-process supervisor and stable-owner tests, exact/missing/conflicting join,
idempotency, clean and ambiguous stop behavior, identity-preserving resume,
the provider-neutral dispatch/reply/thread/project flows, and an offline
integration using the locked official runtime plus official JSONL persistence.
That integration creates history before Beacon registration and proves that
prior user and assistant markers enter model input after exact join and again
after a second process resumes the same native session.

No authenticated real DeepSeek model, user credential, or private real session
was used. Real-model autonomy and tool behavior remain a separately authorized
validation. Public cancel, supplement, parallel prompt, automatic native DSH
discovery, reusable DSH session profiles, foreign live Web/TUI takeover,
remote/multi-user ownership, and Desktop write control remain out of scope.
