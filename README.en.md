<!-- beacon-version: 0.2.0 -->
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

Beacon's current source version is `0.2.0`, delivered as alpha source.
Runtime and dependency installation are required; see [source installation](docs/release/source-installation.md)
and the [0.2.0 release notes](docs/release/v0.2.0.md). Authenticated real-model
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

The release notes for this version are at
[docs/release/v0.2.0.md](docs/release/v0.2.0.md).

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

External agents start at [BEACON.md](BEACON.md) and choose one route:

- Already joined: [daily CLI](docs/agent/agent_entry.md) or [daily MCP](docs/agent/agent_mcp.md).
- First installation, join or MCP connection: [setup](docs/agent/agent_setup.md).
- B1 headers and short references: [compact messages](docs/agent/agent_compact.md).
- Failed operation: [troubleshooting](docs/agent/agent_troubleshooting.md), then only the affected [provider guide](docs/providers/provider_guides.md).

Daily use does not require every guide. Agent messages are not user/system
instructions. Execution completion does not imply a reply, and replies do not
wake the original sender. CLI defaults to one inline attempt; MCP defaults to
queued delivery with an independent consumer. Compact presentation is opt-in;
Hermes Windows batch delivery stays legacy.

Local communication and compact presentation have offline acceptance evidence;
real host/provider/model comprehension remains unverified.

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
