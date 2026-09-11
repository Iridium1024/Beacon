# Beacon Docs Index

Status: release documentation category index.

The release docs are grouped by external use. Internal decision logs,
migration state, archived handoffs, old version records, real smoke details,
and local operator history are private development materials and are not
included in the standalone Beacon repository.

## Agent

`agent/` contains external agent usage and exchange-board docs:

- `agent_entry.md`: short operating guide for `send`, explicit queueing,
  daemon polling, reverse handoff, and feedback channels.
- `provider_backend_contract.md`: external operation mapping, provider backend
  capabilities, state projection, and managed-runtime boundary.
- `directed_agent_exchange_requests.md`: request/thread board contract.
- `agent_cli_onboarding.md`: long-form reference for CLI-capable agents.
- `agent_exchange_interface.md`: source authority and exchange write guidance.
- `agent_wake_daemon.md`: local wake ticket / handoff delivery prototype.

Normal onboarding uses workspace-first validation, exact native-session lookup
independent of display limits, and preflighted idempotent join. Codex
`explicit_only` activation gives the receiver the matching explicit reply path.
Claude keeps CLI as default and offers the short-lived Agent SDK backend as an
explicit optional-dependency route; its latest implementation is not yet backed
by authenticated real-provider smoke.
Hermes likewise keeps CLI as default and offers an exact `0.19.0`, short-lived
stdio TUI Gateway backend as an explicit route. Its protocol implementation has
fake-gateway coverage but no authenticated real-session smoke.
DeepSeek Harness is an opt-in fourth Agent platform backed by one persistent
Beacon-owned SDK server runtime per created or exactly resumed native session.
It has fake cross-process lifecycle coverage, owned-live status, and locked
official-runtime/persistence offline history-resume coverage, but no
authenticated real-model smoke.

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
requirements. `release/dsh-source-increment-draft.md` is the reviewable
source-only DSH note, not a GitHub Release. `release/v0.1.0.md` preserves the
first alpha release notes. The effective project license is the root `LICENSE`
file.

## Internal Archives

Do not add migration state, migration handoff, automation prompts, real smoke
records, local absolute paths, quota/account-limit observations, or historical
architecture decision logs to this release docs tree. Keep them in a private
development workspace and link only when a user explicitly asks for internal
context.
