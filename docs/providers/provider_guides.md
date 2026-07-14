# Provider Guides

Status: external index for provider-specific registered-session and preflight
notes.

Read this file only when the task requires local CLI preflight or
registered-session activation. Ordinary request dispatch usually needs only
`../../BEACON.md` and `../agent/agent_entry.md`.

## Shared Rules

- Beacon does not install provider tools, write provider settings, create
  credentials, store tokens, or bypass provider prompts.
- Default activation keeps provider permission posture unchanged. Claude,
  Codex, and Hermes permission/sandbox/approval/allowed-tools style arguments
  are used only from explicit user-approved profile or CLI input.
- Path reachability, write permission, subprocess ability, platform CLI
  ability, provider executable presence, and provider permission profile are
  separate preflight capabilities.
- A provider session handle is a workspace-local Beacon binding to an
  already-approved Claude/Codex/Hermes session. An endpoint alias is the
  workspace-local address used by `agent-dispatch-send --from/--to`.
- A local provider session profile is a reusable local metadata card for an
  approved provider session. It is not a provider account, login token, or cloud
  identity. Each workspace must be joined explicitly with
  `provider-session-workspace-join`.
- Prefer `agent-provider-onboard` for normal first-time setup. It creates or
  reuses the workspace agent, registers or reuses the provider session handle,
  and logs in or reuses the endpoint alias in one idempotent local workflow.
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
- `claude_registered_session_activation.md`: Claude Code registered-session
  activation boundaries.
- `codex_registered_session_activation.md`: Codex CLI registered-session
  activation boundaries.
- `hermes_registered_session_activation.md`: Hermes CLI registered-session
  activation boundaries.

## Provider Notes

Use placeholders such as `<PROJECT_ROOT>`, `<PLATFORM_WORKSPACE_ROOT>`,
`<DB_PATH>`, and `<PROVIDER_RUNTIME_HOME>` in examples. Do not copy local
operator paths, account quota history, real smoke ids, or private session text
into release-facing docs or request payloads.

For smoke/test feedback, use user-chosen private notes, issues, PR discussion,
or another explicit feedback channel. Do not place private transcripts or local
operator paths in release-facing docs.
