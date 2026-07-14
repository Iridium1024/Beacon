# Local Runtime Entrypoint

Status: current Python CLI runtime reference.

## Purpose

The `beacon` command is the primary local coordination surface. It wraps the
Python application layer and SQLite persistence without requiring Gateway, a
UI, or direct database access. The compatible advanced entrypoint is
`python -m agent_os.local_runtime`.

The CLI does not install provider tools, create provider accounts, bypass
permissions, expose a public service, or persist credentials.

## Supported Modes

- Deterministic local operations and smoke verification.
- Explicit OpenAI-compatible or allowlisted provider API-shape invocation.
- Workspace, agent, context, conversation, request, dispatch, status, daemon,
  lease-recovery, and project-coordination operations.
- Metadata-only provider session discovery by default.
- Bounded registered-session activation for Claude, Codex, and Hermes after
  explicit local registration and permission checks.

Provider-backed model invocation and registered-session activation are separate
paths. Neither is enabled by a normal local smoke.

## Installation And Entrypoints

From the repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .\python-core
.\.venv\Scripts\beacon.exe --version
```

Linux/macOS uses `python3.11`, `./.venv/bin/python`, and
`./.venv/bin/beacon`. After activation, use `beacon` directly.

```powershell
beacon --profile "<PROFILE_PATH>" agent-onboarding-status --format pretty
```

## Configuration Resolution

Runtime state can be provided by an explicit `--profile` path or individual
CLI options. Required state includes a database path, workspace root, and
plugins directory. Workspace-scoped commands also require a workspace id,
which may come from the command or profile.

Provider credentials are accepted only through explicitly named environment
variables. Inline credential values in profiles, metadata, or route payloads
are rejected.

## Persistence

Beacon stores durable local state in SQLite, including workspace, context,
agent, request, dispatch, conversation, invocation, file-operation, and event
records. Provider-session profiles use a separate local JSON registry.

Runtime databases, registries, profiles, logs, wake tickets, provider output,
and generated workspace/plugin directories are local state and must not be
committed.

## Provider Adapter Boundaries

Deterministic mode is the default. Provider API adapters require explicit
configuration and read credentials from the process environment. Supported API
shapes are bounded adapters, not remote model discovery or account connectors.

Registered-session activation starts an approved local provider CLI as a
bounded subprocess. Beacon records lifecycle and sanitized output, but does not
own provider authentication, sandbox policy, approval prompts, or network
transport.

## Session Discovery Boundaries

Discovery reads provider-local metadata only by default. Turn snippets and full
history require explicit opt-in. JSONL reading enforces line-byte, scan-line,
nested-structure, message-count, character-count, and filesystem-depth limits.
Responses report scan counts and truncation reasons.

Discovery metadata is registration input, not proof that a provider session is
currently connected or safe to activate.

## Dispatch And Activation Boundaries

`agent-dispatch-send` creates durable request/dispatch state. Queued mode
returns without waiting. `--wait once` runs one bounded worker observation.
Daemon workers use bounded backoff, do not reactivate ordinary
`waiting_response` records, and can reconcile expired orphan leases.

Provider reconnect, warning, and error events are diagnostic only and cannot
become a Codex final response. A response recovered at a timeout boundary is
marked for user review.

## Security Properties

- Gateway and CLI defaults do not expose LAN/public service endpoints.
- Credentials are environment-only and are not written to local state.
- Agent-authored requests remain coordination input, not user authority.
- Endpoint aliases are routing metadata, not caller authentication.
- Reusable provider-session profiles remain manual-only for automatic
  activation until cross-workspace leasing exists.

## Known Limitations

- Shared JSON registry writes do not provide multi-process locking.
- Gateway exposes only a subset of the Python CLI surface.
- No product user-account authorization, remote agent hosting, UI, or provider
  account connector is implemented.
- Crash-safe repair is limited to the documented dispatch lease and local
  status paths; it is not a general process supervisor.

## Test Commands

From the repository root:

```powershell
py -3.11 -m unittest discover -s python-core\tests
py -3.11 scripts\check_versions.py
py -3.11 scripts\release_check.py --allow-license-placeholder
npm.cmd --prefix gateway ci
npm.cmd --prefix gateway test
```

A real release candidate must also pass `scripts/release_check.py --strict`
after the owner selects a root license and private security contact.
