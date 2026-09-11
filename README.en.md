<!-- beacon-version: 0.1.1 -->
# Beacon

**English** | [简体中文](README.md)

Beacon is a local-first, model-agnostic coordination layer for AI agents that
can operate through a CLI. It gives independently running agents a shared,
explicit surface for workspace onboarding, request dispatch, status tracking,
and bounded provider-session activation without pretending that their private
conversation histories are one shared memory.

The Python CLI is the primary coordination surface. A narrower,
localhost-first TypeScript Gateway exposes selected workspace, context, agent,
conversation, invocation, connection, and binding contracts. This DSH source
increment excludes Desktop, browser UI, and unfinished P3-B assets.

External agents should start with [BEACON.md](BEACON.md). This README is a
developer/module overview, not the shortest operating guide.

> Development note: Beacon began as an exploratory project developed largely
> through vibe coding, so some structural or implementation decisions may
> still deserve revision. The current release has since been hardened with
> automated checks and multi-provider smoke testing, but it remains alpha
> software. Constructive issues, design critiques, and pull requests are
> welcome.

## Where Beacon Fits

- Coordinate independently running Codex, Claude, Hermes, and Beacon-managed
  DeepSeek Harness sessions inside a
  local project through explicit requests and observable status.
- Register provider sessions once, then manage their workspace memberships and
  endpoint identities without treating provider login as Beacon login.
- Inspect onboarding, dispatch, daemon, lease, activation, and exchange state
  when a local collaboration flow stalls.
- Use a local CLI-first control surface today while keeping selected contracts
  available through the optional Gateway.

Beacon is not a remote agent host, a provider account connector, or a
production multi-user chat service.

Beacon's current source version is `0.1.1`; the latest public Git tag/release
is still `v0.1.0`. Version `0.1.1` has not been published from this workspace.
Internal development milestones are not public semantic versions.

The pending DSH fourth-Agent work is prepared as a source increment, not an
independent installer. Downloading or extracting source still requires runtime
and dependency installation. See [source installation and optional
runtimes](docs/release/source-installation.md) and the [DSH source-increment
draft](docs/release/dsh-source-increment-draft.md). Authenticated real-model
communication has not been verified.

## Quick Start

Beacon supports Python 3.11 or newer. The recommended path is an isolated
editable install, which installs PyYAML and creates the `beacon` command. No
preinstalled Python packages or `PYTHONPATH` setup are required.

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .\python-core
.\.venv\Scripts\beacon.exe --help
```

Linux/macOS:

```bash
python3.11 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -e ./python-core
./.venv/bin/beacon --help
```

After activating the virtual environment, use `beacon` directly. Beacon is the
product and CLI name; the internal `agent_os` module, `agent-os-core` Python
package name, and `@agent-os/gateway` package name remain for compatibility.

Run a local smoke from the repository root:

```powershell
beacon `
  --database runtime\state\local-platform.sqlite3 `
  --workspace-root workspace\sandboxes\local-platform `
  --plugins-directory plugins `
  smoke
```

`python -m agent_os.local_runtime` remains a fully compatible source/module
entrypoint. Use it with `PYTHONPATH=python-core\src` only when an editable
install is not available.

The smoke command prints JSON. It does not start a daemon, open a public port,
connect a live model provider by default, create credentials, or launch a UI.

## Release Readiness

See [CHANGELOG.md](CHANGELOG.md), [SECURITY.md](SECURITY.md),
[CONTRIBUTING.md](CONTRIBUTING.md), and
[docs/release/README.md](docs/release/README.md). The selected project license
is Apache-2.0. A public release must pass:

```powershell
py -3.11 scripts\release_check.py --strict
```

The command validates the root license, private security contact, version
consistency, repository hygiene, and release documentation.

The reviewable note for this DSH source increment is at
[docs/release/dsh-source-increment-draft.md](docs/release/dsh-source-increment-draft.md).

## Current Capability Matrix

| Area | Python CLI | Gateway HTTP |
| --- | --- | --- |
| Workspace and profile setup | Full local profile/workspace flow | Workspace create/list/open/archive; no profile initialization route |
| Agent onboarding and endpoints | Idempotent provider onboarding, handles, aliases, inventory | Agent create/list only; no endpoint onboarding routes |
| Requests and dispatch | Request board, queued/once dispatch, daemon and lease recovery | Not exposed |
| Provider sessions | Metadata discovery, registration, reusable profile join/leave | Not exposed |
| Status | Onboarding, endpoint, dispatch, exchange, activation and daemon status; Codex adds owned-runtime snapshots and optional app-server point reads | Selected workspace/runtime-permission records only |
| Provider activation | Bounded Claude/Codex/Hermes registered-session activation plus opt-in DeepSeek Harness exact existing-session join, create, and cross-runtime resume; Claude supports default CLI and opt-in Agent SDK, Codex supports default CLI, an optional 0.149-schema-verified stable stdio app-server with non-expanding resume permissions, and explicit active-turn supplements, and Hermes supports default CLI plus an exact-version-gated opt-in stdio TUI Gateway | Not exposed |
| Context and conversations | Full local CLI operations | Selected `/api/v1` routes through the optional Python bridge |
| Invocation and records | Local invocation, timeline and record queries | Selected invocation, file-record and timeline routes |
| Deferred | Published Desktop and Desktop write control, Hermes WebSocket/ACP/HTTP or persistent runtime, persistent Claude SDK runtime, DSH cancel/supplement/parallel prompts/automatic discovery/foreign live Web/TUI takeover, remote credentials, LAN/public exposure | Complete CLI parity, remote/multi-user service behavior |

## First-Use Flow

1. Read [BEACON.md](BEACON.md).
2. For normal agent work, read [docs/agent/agent_entry.md](docs/agent/agent_entry.md).
3. Run `agent-workspace-init` once. Beacon writes a local
   `.beacon/workspace.json` marker and resolves the nearest project scope from
   the current directory without scanning local databases.
4. Use `agent-join --agent <visible-id> --provider ... --session ...` to bind
   the Agent, exact native session, and same-named endpoint in one operation.
   DeepSeek Harness also accepts exact `--session` and resumes it from the
   configured official persistence root. Use `--new-session` only when a new
   native session is intended.
5. Use `agent-onboarding-status` before dispatch.
6. Dispatch with visible Agent IDs. A receiver may reply with `agent-reply`;
   dispatch itself does not require a reply. Explicit `--profile` remains
   available outside the project tree.

An explicitly supplied native session id uses exact lookup rather than the
recent-session display limit. Normal `agent-join` does not silently assign one
active native session to two visible Agents in the same workspace, and an
invalid workspace fails before provider session storage is read.

For a legacy workspace without a project marker, do not run plain
initialization and accidentally create a parallel empty database. Pass the
known database to `agent-workspace-init --existing-database`, plus the existing
workspace root and plugins directory when they are nonstandard. Beacon verifies
the workspace id before writing the current marker/profile and never scans,
copies, or rewrites the old database.

Queue reads preserve append-only raw state for audit. If the linked request was
answered, closed, or otherwise terminated before provider delivery, its
effective status is `terminal_unprocessed` and workers no longer select it.

`agent-dispatch-send` is the public `send` operation. With no delivery mode it
runs one bounded inline attempt; `--wait once` and the internal
`worker_execute` name are compatibility spellings for the same behavior. A
busy target returns the
decision to the caller; Beacon does not silently queue, retry, or steer. Put
complex detail in a project file and send a summary/reference. Use explicit
`--queued` for long work only when a worker, daemon, or supervisor is known to
consume it. `localRuntime.dispatchControl` configures the default mode and
immediate busy policy. Provider execution completion does not imply a reply.

Provider-specific preflight or registered-session activation tasks should start
from [docs/providers/provider_guides.md](docs/providers/provider_guides.md).
The separate [programmatic interface status](docs/providers/provider_programmatic_interfaces.md)
distinguishes official provider surfaces from backends that Beacon actually
implements; upstream availability never implies a selectable backend.

Claude control settings live under `localRuntime.claudeControl`. The default
and rollback backend remains `cli`; `agent_sdk` is opt-in and requires the
`python-core[claude-agent-sdk]` extra. CLI keeps historical final-output
writeback for compatibility, while Agent SDK defaults to `explicit_only`.
Missing or incompatible SDK packages fail before ticket delivery and never
fall back silently. Each SDK activation owns one short-lived client; the latest
implementation has not completed an authenticated real-session smoke.

Codex control settings live under `localRuntime.codexControl`. Defaults remain
`exec_resume` activation, Beacon snapshot status, explicit `turn_steer`
supplement capability, and `explicit_only` reply writeback. Codex final output
is written as a Beacon reply only when `provider_final_capture` is explicitly
selected. Codex-specific busy settings remain compatible. Use `codex-session-status` for
a registered target. Use `codex-session-supplement` only when the caller has
decided that guidance belongs to the current active turn. The command never
creates a turn, and only the Beacon runner that owns the same app-server stdio
connection can deliver it. See the
[Codex activation guide](docs/providers/codex_registered_session_activation.md)
for configuration, status, idempotency, and ambiguous-delivery behavior.
The default `explicit_only` activation text tells the receiver how to use
`agent-reply` and never claims that its final answer will be captured. A
`CODEX_HOME` discovered during join is reused by point status, app-server, and
exec-resume activation. The current implementation passes exact Codex CLI
0.149.0 stable non-experimental schema and fake-transport checks. Before
`turn/start`, app-server verifies that resumed cwd, sandbox, approval policy,
and writable roots did not expand. This 0.149 path has not completed an
authenticated real-session smoke.

Beacon exposes `send`, `queue`, `supplement`, and `status` while the currently
implemented execution strategies are `inline`, `queue`, and `dry_run`.
`async_submit` is reserved only. Provider backends are selected through a
single contract that reports requested/effective values and never falls back
silently. The current Codex app-server backend is a short-lived stdio operation
per activation, not a persistent multi-thread manager. See the
[dispatch and provider backend contract](docs/agent/provider_backend_contract.md).

Hermes keeps `hermes_cli` as the default. Only explicit
`--hermes-activation-backend tui_gateway` starts one operation-owned
`python -u -m tui_gateway.entry` stdio child. The current gate accepts exact
audited `hermes-agent==0.19.0`; incompatibility fails before prompt submission
without CLI fallback. Saved persistent and returned runtime session ids are
different identity domains, and the runtime id is never written back to the
handle. Gateway writeback defaults to `explicit_only`, and no authenticated
real Hermes-session smoke has been performed yet. See the
[Hermes activation guide](docs/providers/hermes_registered_session_activation.md).

DeepSeek Harness is a separate fourth Agent platform, not the `deepseek` model
preset. Its only opt-in backend is the `deepseek_harness_sdk_stdio` managed
runtime: it can exactly resume a session from official JSONL persistence or
create a new one, while independent CLI/worker processes reuse the same
generation through authenticated local IPC. After a clean stop, explicit
resume preserves native session, Agent, and alias while creating a new
handle/runtime/generation; recreate still means a new native session. Windows
uses the project-local Node 22.19+ carrier pinned to exact `0.1.1-rc.2`.
Beacon never globally installs DSH or takes over a foreign live Web/TUI
process. Fake cross-process regression and a locked official-runtime/
persistence offline history test exist, but no authenticated real-model smoke
has been run. See the
[DeepSeek Harness managed-runtime guide](docs/providers/deepseek_harness_managed_runtime.md).

## Gateway

Gateway is optional and does not mirror the complete Python CLI. In particular,
it does not expose `agent-dispatch`, endpoint onboarding, registered-session
activation, or the complete exchange request/status surface.

Install dependencies and run checks from `gateway`:

```powershell
Set-Location gateway
npm.cmd ci
npm.cmd run check
npm.cmd run test:platform-route
npm.cmd run test:platform-bridge
```

On Linux/macOS, use `npm` in place of `npm.cmd`. `npm ci` is the default for
the committed lockfile; use `npm install` only when intentionally changing
dependencies or `package-lock.json`.

To start Gateway with the Python bridge:

```powershell
$env:LOCAL_PLATFORM_BRIDGE_MODE='python_cli'
$env:LOCAL_PLATFORM_PYTHON_CORE_CWD='../python-core'
$env:LOCAL_PLATFORM_PYTHONPATH='src'
$env:LOCAL_PLATFORM_DATABASE='../runtime/state/local-platform.sqlite3'
$env:LOCAL_PLATFORM_WORKSPACE_ROOT='../workspace/sandboxes/local-platform'
$env:LOCAL_PLATFORM_PLUGINS_DIRECTORY='../plugins'
npm run build
npm start
```

The default Gateway mode is `contract_only`.

Gateway first honors `LOCAL_PLATFORM_PYTHON_COMMAND`, then an active
`VIRTUAL_ENV`, then `py -3.11` on Windows or `python3.11`/`python3` on
Linux/macOS. It rejects interpreters older than Python 3.11 before starting the
bridge. Set the command explicitly only when those candidates are unsuitable.

## Repository Layout

```text
.
|-- AGENTS.md
|-- BEACON.md
|-- LICENSE
|-- NOTICE
|-- README.md
|-- README.en.md
|-- config/
|-- contracts/
|-- docs/
|   |-- agent/
|   |-- gateway/
|   |-- providers/
|   `-- runtime/
|-- gateway/
|-- python-core/
|   |-- src/
|   `-- tests/       # canonical Python regression suite
|-- runtime/      # ignored local runtime state by default
|-- workspace/    # ignored local workspace state by default
`-- plugins/      # ignored local plugin/runtime state by default
```

## Local State

Runtime databases, local profiles, provider-session registries, wake tickets,
daemon logs, provider output, plugin state, and smoke artifacts are local
machine state. They are ignored by the release repository and should not be
committed.

Private development workspaces may keep migration notes, automation logs, and
real smoke history outside this repository. Those materials are not part of
normal external-agent onboarding.

## Roadmap

Beacon's planned development focuses on:

1. Persistent local identities, workspace memberships, connection state,
   recovery, and diagnostics.
2. Stable control contracts that keep registered identities separate from
   workspace membership and live connection state.
3. MCP-compatible integration for supported desktop clients.
4. A desktop control center for registered sessions, workspaces, memberships,
   and live connections.
5. Bounded multi-agent rooms that bring selected registered agents into a
   managed group conversation.
6. Workspace-scoped shared context with explicit permissions, provenance,
   capacity limits, and loop prevention.
7. Installers, updates, migration tooling, and production-grade desktop
   lifecycle management.

This roadmap does not imply fixed release dates and may change based on
implementation findings and community feedback.

## License

Beacon is licensed under the [Apache License 2.0](LICENSE). Copyright 2026
Beacon contributors.
