# Provider Guides

Status: external index for provider-specific registered-session and preflight
notes.

Read this file only when the task requires local CLI preflight or
registered-session activation. Ordinary request dispatch usually needs only
`../../BEACON.md` and `../agent/agent_entry.md`.

## Shared Rules

- Beacon does not install provider tools, write provider settings, create
  credentials, store tokens, or bypass provider prompts.
- A normal `agent-dispatch-send` performs one bounded attempt by default. Busy
  targets return a caller decision; explicit `--queued` remains the advanced
  worker/daemon path and never auto-starts a daemon. Only Codex currently has a
  separate active-turn supplement command, and it is offered only for a
  Beacon-owned steerable runtime.
- `send`, `queue`, `supplement`, and `status` are provider-neutral meanings.
  Backend ids such as `codex_app_server_stdio` are selected behind that
  interface and reported explicitly; backend fallback is never silent. See
  `../agent/provider_backend_contract.md`.
- An official upstream SDK, gateway, or server is not automatically a Beacon
  backend. Only implemented backend ids may be selected or reported as
  effective. See `provider_programmatic_interfaces.md` for the reviewed Claude,
  Codex, and Hermes surfaces and their exact-session fit.
- DeepSeek Harness is different in runtime topology, not in exact-id intent:
  `agent-join --provider deepseek_harness --session <id>` resumes the exact id
  from the configured official persistence root, while `--new-session` creates
  one. It does not provide automatic discovery, reusable provider-session
  profile import, or foreign live Web/TUI takeover. It is also distinct from
  the `deepseek` model preset.
- Default activation keeps provider permission posture unchanged. Claude,
  Codex, and Hermes permission/sandbox/approval/allowed-tools style arguments
  are used only from explicit user-approved profile or CLI input.
- Path reachability, write permission, subprocess ability, platform CLI
  ability, provider executable presence, and provider permission profile are
  separate preflight capabilities.
- A provider session handle is a workspace-local Beacon binding to an
  already-approved Claude/Codex/Hermes session. An endpoint alias is the
  workspace-local address used by `agent-dispatch-send --from/--to`.
- Normal project scope comes from the nearest `.beacon/workspace.json` marker
  created by `agent-workspace-init`; Beacon does not infer it by scanning local
  databases.
- A local provider session profile is a reusable local metadata card for an
  approved provider session. It is not a provider account, login token, or cloud
  identity. Each workspace must be joined explicitly with
  `provider-session-workspace-join`.
- Prefer `agent-join --agent <visible-id> --provider <provider> --session
  <native-session-id>` for normal first-time setup. It creates or reuses the
  workspace Agent, exact session handle, and same-named endpoint alias in one
  idempotent local workflow. `agent-provider-onboard` remains an advanced
  compatibility interface.
- Exact join is independent of recent-session display limits, validates the
  workspace before provider discovery, and does not silently share one active
  native session between visible Agents in the same workspace.
- Provider execution does not require or imply a reply. Receivers can choose a
  response through `agent-reply`; Codex provider-final writeback defaults to
  `explicit_only` and is opt-in as `provider_final_capture`. Claude CLI keeps
  historical final capture for compatibility, while opt-in Claude Agent SDK
  defaults to `explicit_only`. Hermes follows the same compatibility split:
  `hermes_cli` retains historical capture and opt-in
  `hermes_tui_gateway_stdio` defaults to `explicit_only`.
- Under `explicit_only`, the Codex activation text provides the short
  `agent-reply` command instead of promising automatic final-answer capture.
- Reusing one native provider session across projects can mix provider-side
  working-directory assumptions, visible conversation state, quota incidents,
  and tool-permission expectations. Beacon keeps the workspace records
  separate, but it cannot make one provider-native session forget other local
  context.
- Until Beacon implements a cross-workspace provider-session lease, reusable
  local provider session profiles are manual-only for activation. Worker or
  daemon automatic activation is blocked with an explicit warning.
- Use `agent-session-discover`, `agent-session-handle-register-discovered`,
  `agent-endpoint-login-discovered`, or provider-specific
  `*-session-handle-register` commands as advanced troubleshooting paths before
  asking an agent to inspect provider session files manually.
- `--handle-id` is optional on handle registration paths. Omit it unless a
  deterministic id is required; Beacon generates and returns the handle id, so
  external UUID shell tools are not required.
- Endpoint login is not provider account login. It does not store credentials,
  tokens, cookies, auth headers, or a complete provider transcript.
- Local runtime homes, provider quota incidents, and real smoke history are
  private troubleshooting records. They are not external onboarding input and
  are not included in the standalone Beacon repository.

Provider command examples use the installed `beacon` command. See
`../../BEACON.md` for activated and unactivated virtual-environment forms.

## Codex Cwd Troubleshooting

Codex registered-session activation defaults to a bounded repository-check
policy for the explicit registered cwd. If an audit reports
`codex_git_repo_check_failed`, use the Codex activation guide to decide whether
the registered cwd should be a Git working directory or whether the bounded
default policy is appropriate. Do not change sandbox, approval, directory
grants, or credentials to address this condition.

## Entry Points

- `agent_runtime_preflight.md`: read-only diagnostics for provider executables
  and activation capabilities.
- `provider_programmatic_interfaces.md`: current upstream programmatic
  interfaces, Beacon implementation status, and candidate integration rules.
- `claude_registered_session_activation.md`: Claude CLI and opt-in Agent SDK
  registered-session activation, optional install, preflight, writeback, and
  rollback boundaries.
- `codex_registered_session_activation.md`: Codex CLI and stable stdio
  app-server activation, point status, explicit `turn/steer` supplement,
  configuration, and rollback boundaries.
- `hermes_registered_session_activation.md`: default Hermes CLI and opt-in,
  exact-version TUI Gateway registered-session activation boundaries.
- `deepseek_harness_managed_runtime.md`: exact-version preflight, exact persisted
  join and new-session onboarding, persistent supervisor/native identity,
  causal final capture, owned-live status, stop/resume/recreate, and current
  smoke limits.

## Provider Notes

Use placeholders such as `<PROJECT_ROOT>`, `<PLATFORM_WORKSPACE_ROOT>`,
`<DB_PATH>`, and `<PROVIDER_RUNTIME_HOME>` in examples. Do not copy local
operator paths, account quota history, real smoke ids, or private session text
into release-facing docs or request payloads.

For smoke/test feedback, use user-chosen private notes, issues, PR discussion,
or another explicit feedback channel. Do not place private transcripts or local
operator paths in release-facing docs.
