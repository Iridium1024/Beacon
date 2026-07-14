<!-- beacon-version: 0.1.0 -->
# Changelog

All notable public-facing changes will be recorded here. Internal automation
steps and private migration history are intentionally excluded.

## [Unreleased]

## [0.1.0] - 2026-07-13

Public release notes: [简体中文 / English](docs/release/v0.1.0.md).

### Added

- Local workspace, agent, context, conversation, request, dispatch, status, and
  bounded provider-session coordination through the Python CLI.
- Metadata-only provider session discovery by default, with explicit bounded
  opt-ins for snippets and history.
- Localhost-only Gateway contracts with an optional Python CLI bridge.
- Idempotent provider onboarding, endpoint inventory, daemon status, lease
  recovery, runtime backoff, and reusable session-profile membership flows.
- Release hygiene, version consistency, package build, and cross-platform CI
  verification.

### Security

- Provider credentials remain environment-only and are not persisted.
- Provider reconnect, warning, and error events cannot become final Codex
  responses.
- Gateway rejects non-loopback bind targets.

### Known Limitations

- Alpha-quality local experimentation only; not a production multi-user
  service.
- Gateway does not expose the complete Python CLI coordination surface.
- Shared JSON registry updates do not provide multi-process locking.
- No LAN/public deployment, remote agent hosting, UI, or provider account
  connector is included.
Version `0.1.0` is Beacon's first public release and uses the `v0.1.0` Git tag.
