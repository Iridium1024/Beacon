# Provider Programmatic Interface Status

Status: public capability and integration-boundary review, updated 2026-08-24.

This document separates interfaces published by a provider from backends that
Beacon actually ships. Upstream availability alone does not create a Beacon
backend id, change a default route, or prove exact registered-session
continuity.

## Status Vocabulary

- `implemented`: Beacon has a selectable backend, tests, and an explicit
  lifecycle/rollback boundary for the interface.
- `evaluated_candidate`: the provider publishes an applicable interface, but
  Beacon has not implemented or exposed it as a backend.
- `separate_product`: the interface is official, but it does not attach to the
  same local native-session inventory used by the current registered-session
  route.
- `not_selected`: the interface exists, but its documented session semantics do
  not satisfy the current exact registered-session requirement.

Only `implemented` entries may appear as effective backend ids in Beacon
runtime output. Candidate names below are descriptive and are not accepted
configuration values.

## Capability Matrix

| Provider interface | Official surface | Registered-session fit | Beacon status |
| --- | --- | --- | --- |
| Codex app-server | Local JSON-RPC over stdio | Exact thread resume, turn events, point reads, steer, and interrupt | `implemented` in this source tree as opt-in `codex_app_server_stdio`; `codex_exec_resume` remains default |
| Claude Agent SDK | Python library around Claude Code | Resumes the exact registered local session UUID with matching cwd and provides typed messages, bounded interrupt, and permission callbacks | `implemented` in this source tree as opt-in `claude_agent_sdk`; `claude_cli` remains default and rollback |
| Claude Managed Agents | Hosted REST/SSE session API | New hosted sessions and events rather than attachment to an existing local Claude Code transcript | `separate_product`; not a registered-session backend |
| Hermes TUI Gateway | JSON-RPC over stdio or WebSocket | Exposes saved-session list/resume, prompt submission, streamed events, interrupt, history/status, and explicit interaction responses | `implemented` for exact PyPI `0.19.0` stdio as opt-in `hermes_tui_gateway_stdio`; `hermes_cli` remains default/rollback; WebSocket and main `0.20.5` are not selected |
| Hermes ACP | ACP JSON-RPC over stdio | Its documented load/resume/fork scope is tied to sessions known by the current ACP server process, not arbitrary saved CLI sessions | `not_selected` for exact registered-session activation |
| Hermes API Server | OpenAI-compatible HTTP plus SSE/run endpoints | Appropriate for an HTTP-managed Hermes runtime, but not the current exact local CLI-session route | `separate_product`; not a registered-session backend |
| DeepSeek Harness SDK Server | Public JSON-RPC 2.0 JSONL over stdio plus official session persistence | Creates a new session or resumes an exact persisted id through `ctx.agents.resume`; it does not take over a foreign live Web/TUI process | `implemented` as opt-in `deepseek_harness_sdk_stdio`, the only backend for Agent platform `deepseek_harness` |

The current backend ids and their reported capabilities remain authoritative in
[`provider_backend_contract.md`](../agent/provider_backend_contract.md). A
`false` Beacon capability describes the selected backend, not everything the
upstream provider can do.

## Current Invocation Boundaries

Claude registered-session activation selects one of two short-lived,
operation-owned routes. The default/rollback route starts one bounded CLI
process:

```text
claude --resume <session-uuid> --add-dir <workspace-root> --print --output-format stream-json --verbose
```

The opt-in `claude_agent_sdk` route uses `ClaudeSDKClient` with `resume`, `cwd`,
`add_dirs`, explicit permission options, typed response events, bounded
interrupt, and guaranteed disconnect cleanup. It does not hold a persistent
SDK client between operations and is not a public supplement/cancel/status
surface.

The route has been compatibility-audited against the public `0.2.144` package
shape while retaining `>=0.2.127,<0.3.0`. Optional detection adapts to
`ConversationResetMessage`, `ResultMessage.origin`, and `ResultError` without
making those post-`0.2.127` symbols mandatory. Conversation resets and
non-human/unknown result origins invalidate final capture, while structured
`ResultError` failures are bounded and correlated with an earlier error result
when one was streamed. This does not enable rewind/resume truncation,
`SessionStore`, forwarded subagent text, MCP 2.x features, or any longer-lived
runtime topology.

Hermes registered-session activation defaults to one bounded CLI process:

```text
hermes chat --query <handoff> --quiet --resume <session-id> --source agent-os
```

The opt-in alternative starts one operation-owned stable gateway process with
the exact interpreter that passed its package/module/method/event preflight:

```text
<gateway-python> -u -m tui_gateway.entry
```

It waits for `event/gateway.ready` without `initialize`, proves the saved
persistent id/source through `session.list`, proves the persistent resume id
and cwd through `session.resume`, and then uses the distinct returned runtime
id for one `prompt.submit` and its events. It closes the process after the
operation. Stable approval uses runtime-session correlation; clarify/sudo/secret
use request ids and are denied/emptied without secret access. Main `0.20.5` is
tracked only as advisory protocol drift. Neither version implies WebSocket,
ACP, HTTP server, or persistent runtime support.

Codex app-server in this source tree is also operation-owned and short-lived.
It is not a persistent connection to Codex Desktop and is not a Beacon-managed
multi-thread daemon. Its latest compatibility implementation has automated and
static coverage against the exact stable, non-experimental 0.149.0 schema. On
resume it verifies the effective cwd, sandbox, approval policy, and writable
roots before starting a turn; wider or missing permission evidence fails
closed. Reverse requests are correlated to the verified thread/turn/item and a
unique request id. Completed items and the turn summary are authoritative for
final capture, not deprecated delta notifications. The 0.149-compatible path
has not completed a new authenticated real-machine provider smoke.

DeepSeek Harness is the distinct managed-runtime route. Beacon pins the Node
SDK/server packages to exact `0.1.1-rc.2` and audited commit
`b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`. Independent Beacon processes talk
to one loopback-only supervisor, which retains one official SDK server process
and one created or exactly resumed persistent DSH session. A thin composition
adapter selects the public `ctx.agents.resume({resumeSessionId})` path and the
official JSONL store before registration. The accepted wire contract is limited to `initialize`,
`session/prompt`, `shutdown`, and the four documented notifications. It offers
no public Beacon cancel, supplement, parallel prompt, automatic discovery, or
foreign live Web/TUI takeover. Clean stop can resume the same native session in
a new runtime generation; in-flight ambiguity is never replayed. Windows uses the
project-local Node 22.19+ carrier; the official Python runtime wheel route is
platform-gated. Fake-runtime coverage and locked official-runtime/persistence
offline integration exist, but no authenticated real-model smoke has been
performed.

Publication note (2026-08-04): the public GitHub repository did not yet contain
or use the newer local Codex app-server implementation when
[status issue #1](https://github.com/Iridium1024/Beacon/issues/1) was opened.
Documentation in a later source checkout must not be used to infer that an
older public tag, package, or checkout contains the same backend.

## Candidate Integration Rules

Any later programmatic backend or Hermes version-range expansion must:

- be opt-in until its own fake-transport tests and separately authorized real
  smoke pass;
- preserve the existing CLI backend as an explicit rollback path and never
  fall back silently;
- validate the exact provider-native session id, cwd, runtime home, and source
  identity before submitting a prompt;
- expose provider events through bounded Beacon metadata without exporting a
  complete private transcript;
- fail closed on unknown permission, approval, clarification, protocol, or
  version behavior;
- own and clean up only the process/connection it started, with no desktop UI,
  browser input, credential extraction, or unrelated-session takeover; and
- report requested/effective backend and lifecycle/capability information using
  the existing provider backend contract.

The implemented Claude route uses the public Agent SDK rather than an
undocumented raw Claude Code control protocol. Product/auth review remains a
separate boundary: Beacon does not collect credentials or offer Claude
subscription login, and third-party integrations should use provider-supported
API-key or cloud-provider authentication.

The optional Python dependency is pinned to the tested public surface:
`claude-agent-sdk>=0.2.127,<0.3.0`. This source checkout has fake-SDK,
integration, static, and regression coverage, including the `0.2.144` optional
message/error shapes. It has **not** completed an authenticated
real-provider/session smoke after that refresh; `implemented` describes the
local backend contract and test state, not a smoke claim.

The Hermes implementation is pinned to stable `0.19.0`, has fake-executable,
integration, malformed-transport, interaction, timeout/interrupt, configuration,
and regression coverage, and has **not** completed an authenticated real Hermes
session smoke. Local `0.18.0` and official-main `0.20.5` are not accepted by
the preflight. That is an exact compatibility boundary, not a claim that those
versions lack a TUI Gateway module.

## Official References

- [Claude Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)
- [Claude Agent SDK Python reference](https://code.claude.com/docs/en/agent-sdk/python)
- [Claude Agent SDK sessions](https://code.claude.com/docs/en/agent-sdk/sessions)
- [Claude streaming versus single mode](https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode)
- [Claude Managed Agents sessions](https://platform.claude.com/docs/en/managed-agents/sessions)
- [Hermes programmatic integration](https://hermes-agent.nousresearch.com/docs/developer-guide/programmatic-integration)
- [Hermes ACP](https://hermes-agent.nousresearch.com/docs/user-guide/features/acp)
- [Hermes API Server](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server)
- [DeepSeek Harness repository](https://github.com/deepseek-ai/deepseek-harness)
- [DeepSeek Harness JSON-RPC agent example](https://github.com/deepseek-ai/deepseek-harness/tree/master/examples/jsonrpc-agent)
