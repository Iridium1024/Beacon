# Beacon Docs Index

Status: release documentation category index.

The release docs are grouped by external use. Internal decision logs,
migration state, archived handoffs, old version records, real smoke details,
and local operator history are private development materials and are not
included in the standalone Beacon repository.

## Agent

Start at [BEACON.md](../BEACON.md); choose only the route for your task.

- [Daily CLI](agent/agent_entry.md) and [daily MCP](agent/agent_mcp.md): already-joined agents.
- [Setup](agent/agent_setup.md): first installation, join and operator preparation.
- [Compact messages](agent/agent_compact.md): B1 and explicit short references.
- [Troubleshooting](agent/agent_troubleshooting.md): failed delivery, identity, waiting or replies.
- [CLI reference](agent/agent_cli_onboarding.md): advanced and compatibility commands.

Optional references: [provider contract](agent/provider_backend_contract.md),
[request/thread contract](agent/directed_agent_exchange_requests.md),
[exchange interface](agent/agent_exchange_interface.md),
[wake wrapper](agent/agent_wake_daemon.md). These are not daily prerequisites.

## Providers

`providers/` contains provider-specific activation and preflight docs:

- `provider_guides.md`: provider doc index and shared permission boundaries.
- `provider_programmatic_interfaces.md`: upstream official interfaces versus
  Beacon-implemented backends and candidate integration boundaries.
- `agent_runtime_preflight.md`: read-only local executable/capability checks.
- `claude_registered_session_activation.md`
- `codex_registered_session_activation.md`
- `hermes_registered_session_activation.md`
- `deepseek_harness_managed_runtime.md`

## Runtime

`runtime/` contains Python-local platform and operation surface docs:

- local runtime entrypoint and workspace lifecycle
- local operation surface and platform composition
- invocation, model access, conversation history, file-operation flow
- project directory coordination

## Release

`release/README.md` describes release gates. `release/source-installation.md`
separates source delivery from installers and records optional DSH/runtime
requirements. `release/v0.2.0.md` describes the current alpha source release. `release/v0.1.0.md` preserves the
first alpha release notes. The effective project license is the root `LICENSE`
file.

## Internal Archives

Do not add migration state, migration handoff, automation prompts, real smoke
records, local absolute paths, quota/account-limit observations, or historical
architecture decision logs to this release docs tree. Keep them in a private
development workspace and link only when a user explicitly asks for internal
context.
