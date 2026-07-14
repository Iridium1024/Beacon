# Agent Wake Wrapper / Daemon Prototype

Status: advanced local wake delivery helper.

This document describes the local wake wrapper/daemon prototype for CLI-capable advanced agents. It is a local delivery helper for pending `AgentExchangeRequest` records. It can surface a wake ticket through terminal output, a handoff file, or an explicitly configured local argv command. It is not a real Codex, Claude, browser, IDE, provider-native session, or desktop-app connector.

## What It Does

- Polls pending directed exchange requests for one target `agentId`.
- Builds a compact, directly readable wake ticket containing the request route,
  request summary, source attribution, and one structured inspect/respond action.
- Supports `notify_only`, `handoff_file`, and explicitly configured `command` wake modes. Command mode can start a configured local command, but only with platform-generated safe placeholders.
- Records daemon-owned wake delivery audit events in the append-only event log.
- Uses lease/delivery markers outside request/thread records, so request/thread facts are not rewritten to track delivery.
- Provides a PyCharm-friendly Python entrypoint for visible process testing.
- Exposes agent-facing wake delivery status, ticket lookup, and delivery list commands.
- Configures the local runtime CLI stdout/stderr path for UTF-8 JSON output so Chinese request summaries remain readable in the CLI path.

## What It Does Not Do

- It does not connect to real Codex, Claude Code, browser, IDE, provider-native, or remote conversation sessions.
- It does not prove that a command-mode child process is a real external agent session or that the external agent completed the request.
- It does not inject provider prompts or desktop/browser/IDE input boxes.
- It does not read project file bodies or copy private agent conversation state.
- It does not store credentials, API keys, cookies, authorization headers, or remote session tokens.
- It does not run automatic finite-round discussion, convergence, scoring, or adjudication.

## CLI Commands

Inspect the wake interface:

```bat
beacon --database "<DB_PATH>" --workspace-root "<WORKSPACE_ROOT>" --plugins-directory "<PLUGINS_DIR>" --pretty agent-wake-instructions --workspace-id "<WORKSPACE_ID>" --agent-id "<TARGET_AGENT_ID>"
```

Run one local watch cycle through the normal runtime CLI:

```bat
beacon --database "<DB_PATH>" --workspace-root "<WORKSPACE_ROOT>" --plugins-directory "<PLUGINS_DIR>" --pretty agent-exchange-wake-watch --workspace-id "<WORKSPACE_ID>" --agent-id "<TARGET_AGENT_ID>" --once --dry-run
```

Run one handoff-file delivery cycle:

```bat
beacon --database "<DB_PATH>" --workspace-root "<WORKSPACE_ROOT>" --plugins-directory "<PLUGINS_DIR>" --pretty agent-exchange-wake-watch --workspace-id "<WORKSPACE_ID>" --agent-id "<TARGET_AGENT_ID>" --wake-mode handoff_file --handoff-directory "<HANDOFF_DIR>"
```

Run the PyCharm-friendly daemon module:

```bat
py -3.11 -m agent_os.agent_wake_daemon --database "<DB_PATH>" --workspace-root "<WORKSPACE_ROOT>" --plugins-directory "<PLUGINS_DIR>" --workspace-id "<WORKSPACE_ID>" --agent-id "<TARGET_AGENT_ID>" --once --dry-run --pretty
```

Check whether a request has local wake delivery records:

```bat
beacon --database "<DB_PATH>" --workspace-root "<WORKSPACE_ROOT>" --plugins-directory "<PLUGINS_DIR>" --pretty agent-wake-status --workspace-id "<WORKSPACE_ID>" --exchange-request-id "<REQUEST_ID>"
```

List recent delivery records for a target agent:

```bat
beacon --database "<DB_PATH>" --workspace-root "<WORKSPACE_ROOT>" --plugins-directory "<PLUGINS_DIR>" --pretty agent-wake-delivery-list --workspace-id "<WORKSPACE_ID>" --agent-id "<TARGET_AGENT_ID>" --limit 20
```

Read the latest ticket captured in delivery audit for a request:

```bat
beacon --database "<DB_PATH>" --workspace-root "<WORKSPACE_ROOT>" --plugins-directory "<PLUGINS_DIR>" --pretty agent-wake-ticket-get --workspace-id "<WORKSPACE_ID>" --exchange-request-id "<REQUEST_ID>"
```

## PyCharm Run Configuration

Use this as the first smoke configuration:

- Module name: `agent_os.agent_wake_daemon`
- Working directory: `<PROJECT_ROOT>`
- Environment: `PYTHONPATH=python-core\\src`
- Parameters:

```text
--database <PROJECT_ROOT>\.smoke\agent-wake-25.sqlite --workspace-root <PROJECT_ROOT> --plugins-directory <PROJECT_ROOT>\.smoke\plugins --workspace-id <WORKSPACE_ID> --agent-id <TARGET_AGENT_ID> --once --dry-run --pretty
```

Expected visible output includes:

- `agent wake daemon started`
- current workspace / agent / wake mode
- pending request count
- delivered / skipped / failed counts
- `agent wake daemon graceful shutdown: once=true`

`--once` means one local polling/delivery cycle. It is useful for smoke tests
and manual handoff, but it is not a background service. Without `--once`, the
daemon module can loop until stopped; this is still local ticket delivery, not
real external runtime control.

## Command Mode

`command` mode is disabled unless explicitly configured with `wakeMode=command` and a `commandArgv` array.

Only platform-generated safe placeholders are supported:

- `{ticket_path}`
- `{workspace_id}`
- `{agent_id}`
- `{request_id}`
- `{thread_id}`
- `{wake_ticket_id}`

Do not put request summaries, response summaries, model output, user text, or other agent free text into `commandArgv`.

Example:

```json
{
  "agentWakeProfile": {
    "workspaceId": "workspace-demo",
    "agentId": "agent-b",
    "wakeMode": "command",
    "enabled": true,
    "handoffDirectory": "C:\\FixtureUser\\beacon-runtime\\wake-tickets",
    "commandArgv": [
      "py",
      "-3",
      "C:\\FixtureUser\\beacon-runtime\\dummy_responder.py",
      "{ticket_path}"
    ],
    "childProcessPolicy": "wait"
  }
}
```

The built-in tests only verify this mechanical command boundary with a dummy fixture. A passing dummy fixture does not prove real Codex or Claude integration.

## Wake Ticket Contract

A wake ticket is a full JSON handoff record. It should be readable without querying shared context update bodies.

It contains:

- `wakeTicketId`
- `workspaceId`
- `targetAgentId`
- `sourceAgentId`
- `exchangeRequestId`
- `threadId`
- `requestKind`
- `requestSummary`
- `instructionAuthority=agent_suggestion`
- `sourceAttribution`
- `localRuntimeHints`
- `recommendedAction`, containing one compact status argv, one response argv
  template, and the runtime environment required for source-tree execution
- safety flags showing no real runtime connection, prompt injection, file body read, or credential storage

The ticket is not a user direct instruction. The target agent should treat it as
an agent-authored collaboration request. It can run the structured
`inspectArgv` when additional platform state is needed and use
`respondArgvTemplate` when the provider adapter does not capture its final
response directly. `runtimeEnvironment.PYTHONPATH` makes those argv values
usable from a source checkout where Beacon is not installed as a package.

## Delivery Status Versus Runtime Control

Do not infer ticket delivery from `runtimeWakeTriggered=false`.

That flag means the platform did not control a real external agent
runtime/session. It does not mean a ticket was not delivered. Ticket delivery
is reported through `agent-wake-status`, `agent-wake-delivery-list`,
`agent-wake-ticket-get`, and the `wakeDeliverySummary` returned by
`agent-exchange-request-get`.

If the daemon is not running, no new ticket delivery will happen. That is an
operational state, not the same thing as the design boundary that the platform
does not control real Codex/Claude/browser/IDE/provider-native sessions.

## Next Smoke

After step 25.2 closes, the next validation should be another bounded
three-party smoke:

1. Source agent creates a request.
2. The daemon delivers a ticket for the target agent.
3. The target agent reads the ticket, then reads request/thread through CLI.
4. The target agent responds.
5. The source agent reads the response.

That smoke determines whether to prioritize request handoff output, CLI
parameter defaults/profile, shell examples, JSON helpers, one-command status
summaries, or further wake integration.
