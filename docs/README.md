# Beacon Docs Index

Status: release documentation category index.

The release docs are grouped by external use. Internal decision logs,
migration state, archived handoffs, old version records, real smoke details,
and local operator history are private development materials and are not
included in the standalone Beacon repository.

## Agent

`agent/` contains external agent usage and exchange-board docs:

- `agent_entry.md`: short operating guide for queued dispatch, bounded
  `worker_execute`, daemon polling, reverse handoff, and feedback channels.
- `directed_agent_exchange_requests.md`: request/thread board contract.
- `agent_cli_onboarding.md`: long-form reference for CLI-capable agents.
- `agent_exchange_interface.md`: source authority and exchange write guidance.
- `agent_wake_daemon.md`: local wake ticket / handoff delivery prototype.

## Providers

`providers/` contains provider-specific activation and preflight docs:

- `provider_guides.md`: provider doc index and shared permission boundaries.
- `agent_runtime_preflight.md`: read-only local executable/capability checks.
- `claude_registered_session_activation.md`
- `codex_registered_session_activation.md`
- `hermes_registered_session_activation.md`

## Runtime

`runtime/` contains Python-local platform and operation surface docs:

- local runtime entrypoint and workspace lifecycle
- local operation surface and platform composition
- invocation, model access, conversation history, file-operation flow
- project directory coordination

## Gateway

`gateway/` contains the localhost-first Gateway HTTP/API contract.

## Release

`release/README.md` describes release gates, and `release/v0.1.0.md`
contains the bilingual public notes for the first alpha release. The effective
project license is the root `LICENSE` file.

## Internal Archives

Do not add migration state, migration handoff, automation prompts, real smoke
records, local absolute paths, quota/account-limit observations, or historical
architecture decision logs to this release docs tree. Keep them in a private
development workspace and link only when a user explicitly asks for internal
context.
