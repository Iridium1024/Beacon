# Setup

Use this only for first setup or an explicitly requested change. Already joined?
Go to [daily CLI](agent_entry.md) or [daily MCP](agent_mcp.md).
Replace all placeholders. Use only approved sessions, paths and permissions.

## Install

From the Beacon source root, use Python 3.11+ in a dedicated environment.
On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install ./python-core
.\.venv\Scripts\Activate.ps1
beacon agent-help --topic onboarding
```

On Linux/macOS:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install ./python-core
. .venv/bin/activate
beacon agent-help --topic onboarding
```

If activation is unavailable, use that environment's full `beacon` executable
path. CLI use does not require the MCP extra, Gateway or Desktop.
Provider tools and their account access must already be available; Beacon does
not install them, log in for you or bypass their permissions.

## Join a project

Initialize a **new** project once, then run later commands from that project:

```text
beacon agent-workspace-init --project-root "<PROJECT_ROOT>" --workspace-id W --display-name "Project"
beacon agent-join --agent ME --provider codex --session "<EXACT_NATIVE_SESSION_ID>"
beacon agent-onboarding-status --agent-id ME --endpoint-alias ME
```

Choose `codex`, `claude` or `hermes` for the exact approved session. Repeat join
with each participant's own ID/session. Do not pick an arbitrary recent session
or claim a session already owned by another Agent. For DSH, use its
[one-time configuration](../providers/deepseek_harness_managed_runtime.md#one-time-configuration-and-preflight)
and [exact join](../providers/deepseek_harness_managed_runtime.md#join-an-existing-session);
`--new-session` is only for intentionally creating a new session.

A project marker `.beacon/workspace.json` selects the workspace. Outside that
project, pass `--profile "<PROFILE_JSON_PATH>"` before the command. Explicit
profile, profile environment and marker must agree. Keep the returned profile
path for operator commands below; do not search databases to infer it.

For an **existing** workspace without a marker, add `--existing-database
"<KNOWN_DATABASE>"` to initialization, plus `--existing-workspace-root` and
`--existing-plugins-directory` if nonstandard. Do not accidentally initialize
a second empty workspace. Advanced shared-session setup is in the
[CLI reference](agent_cli_onboarding.md#project-first-onboarding-checklist-one-time-preparation).

Before first activation, check only your selected provider's settings if not
already configured: [Codex](../providers/codex_registered_session_activation.md#select-the-activation-backend),
[Claude](../providers/claude_registered_session_activation.md#backend-selection-install-and-rollback),
[Hermes](../providers/hermes_registered_session_activation.md#default-cli-route).
Keep existing permission/sandbox settings unless the user authorizes a change.
Then follow [daily CLI](agent_entry.md#confirm-and-send) to send the first request.
For MCP, compact mode or ACK/final waits, complete the applicable preparation below.

## Operator preparation

For MCP/core message operations, use an explicitly prepared communication workspace.
If not already prepared, stop all writers and preview the existing workspace:

```text
beacon --profile "<PROFILE_JSON_PATH>" communication-migrate-preview --workspace-id W
beacon --profile "<PROFILE_JSON_PATH>" communication-migrate --workspace-id W --operator OP --backup-path "<NEW_BACKUP_FILE>" --confirm-stopped-writers
```

Inspect the preview and resolve reported conflicts before migration. Never reuse
an existing backup path. This is an explicit operator action, not a receive step.

For queued MCP delivery or new pending waits, initialize and start an independent
consumer in its own managed terminal/process, outside the MCP client's cleanup:

```text
beacon --profile "<PROFILE_JSON_PATH>" communication-runtime-init --workspace-id W
python -m agent_os.agent_dispatch_daemon --profile "<PROFILE_JSON_PATH>" --workspace-id W
```

Use the same installed environment and the chosen provider settings. Keep this
consumer running separately from sending agents. Verify with
`beacon --profile "<PROFILE_JSON_PATH>" communication-runtime-status --workspace-id W`.
Do not assume queue creation, MCP startup or registration starts a consumer.
MCP `store` does not need one and creates no wake.

## MCP

After joining and operator preparation, install only the optional extra in the
chosen environment, from the Beacon source root:

```text
python -m pip install "./python-core[mcp]"
```

Configure the host to launch the installed environment's interpreter with argv:

```json
{
  "command": "<VENV_PYTHON>",
  "args": ["-m", "agent_os.communication_mcp", "--profile", "<PROFILE_JSON_PATH>", "--agent", "ME"]
}
```

This is a host configuration example, not a command to send as a message.
Alternatively launch `beacon-mcp --agent ME` inside the marked project or add
`--project-root "<PROJECT_ROOT>"`. Use `--alias` if the sending endpoint differs
from the Agent ID. If configuring a profile manually, `localRuntime` must contain
`workspaceId`, `databasePath`, `workspaceRoot` and `pluginsDirectory`; relative
paths are based on the profile directory.

When nondefault provider backends are selected, match the consumer with MCP's
`--codex-backend exec_resume|app_server`, `--claude-backend cli|agent_sdk`, or
`--hermes-backend cli|tui_gateway`. Reconnect deliberately after changing the
registered session/handle. MCP cannot join, migrate or start the consumer.
Continue with [daily MCP](agent_mcp.md).

## Compact mode

Optional; legacy presentation remains available. With writers stopped and a
prepared core workspace, the operator runs:

```text
beacon --profile "<PROFILE_JSON_PATH>" communication-short-refs-init --workspace-id W --operator OP --backup-path "<NEW_SHORT_REF_BACKUP>" --confirm-stopped-writers
```

Add `--compact-messages` to the independent consumer or inline send/worker for
compact provider handoffs; add it separately to `beacon-mcp` for compact MCP
presentation. Queries do not initialize this feature. Read
[compact messages](agent_compact.md) before using B1/short references.
Hermes `.cmd`/`.bat` delivery remains legacy; use a supported direct executable
or Gateway when compact delivery is required.
