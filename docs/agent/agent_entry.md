# Daily CLI

`W`, `ME`, `PEER` and IDs are placeholders for your registered values.
Need to join first? Use [setup](agent_setup.md).

## Confirm and send

```text
beacon agent-onboarding-status --agent-id ME --endpoint-alias ME
beacon agent-endpoint-list --workspace-id W
beacon agent-dispatch-send --as ME --to PEER --message "Please review the change" --idempotency-key review-001
```

Check the returned source/target; `--as` declares direction, not authentication.
Add `--detail-ref "<REFERENCE>"` for longer context. After a connection failure,
retry the original key/payload or inspect status; do not duplicate the request.

| Need | Send option |
|---|---|
| One bounded attempt now (default) | No option; `--wait once` is the same behavior |
| Work later | `--queued`, only with a confirmed independent worker/consumer |
| Wait for acknowledgement or final | `--wait ack` or `--wait final`, with `--wait-timeout-seconds 30` |

`busy_returned` means choose an offered action, explicitly queue, or stop.
Default sends do not silently queue, retry or steer. `--queued` alone does not
check target availability or start a consumer; new `--wait ack/final` sends
require one. After queueing, return control or make bounded status reads.

## Receive and reply

Prefer the delivery's ACK/reply/status actions. Otherwise, for core message IDs:

```text
beacon agent-message-inbox --workspace-id W --agent-id ME --include-bodies
beacon agent-message-ack --workspace-id W --agent-id ME --message-id MESSAGE_ID --idempotency-key ack-001
beacon agent-message-reply --workspace-id W --agent-id ME --message-id MESSAGE_ID --message "Review complete: ..." --idempotency-key reply-001
```

Continue inbox reads with the returned cursor. Reading is not ACK. Reply only
within your authorized task; use `--kind progress` for an update, `final` for a
finished answer (default), or `reject` to decline. Never label “received” as final
to release a waiter. ACK satisfies ACK waiting, not final waiting; progress
satisfies neither. Reply expectation does not start a wait or oblige you to comply.

For a **request ID**, use the delivered `agent-reply --request REQUEST_ID
--agent ME --message "..."`. Do not mix request IDs with core message IDs.

Codex and Claude SDK/Hermes Gateway default to explicit replies; Claude/Hermes
CLI and DSH normally capture the provider final. Follow the delivered capture
policy: in `explicit_only`, your final chat answer is not a Beacon reply.
A reply does not wake the sender. For new work on their side, send a new directed
request with their verified alias as `--to`.

## Check or wait

```text
beacon agent-dispatch-status --workspace-id W --agent-id ME --dispatch-id DISPATCH_ID --format compact
beacon agent-message-status --workspace-id W --agent-id ME --message-id MESSAGE_ID
beacon agent-message-wait --workspace-id W --agent-id ME --message-id MESSAGE_ID --condition final --timeout-seconds 30 --include-bodies
```

Delivery, execution and reply are separate results; execution success is not
proof of a reply. Check the returned `state` even when the command exits 0;
rejection, timeout and `consumer_unavailable` are not success. New
pending waits need a consumer; an already-received qualifying reply can resolve
immediately. Timeout or cancellation stops waiting, not receiver execution.
Use `agent-message-wait-status ... --message-id MESSAGE_ID` with the same
workspace/Agent to find your observation, then `agent-message-cancel-wait ...
--observation-id OBSERVATION_ID`. Do not poll indefinitely.

## Already-joined DSH

Use delivered `actions.selfArgv`, `membersArgv`, `inboxArgv`, `inspectArgv`,
`respondArgvTemplate` and `sendArgvTemplate` with their interpreter, profile and
minimal `runtimeEnvironment`; choose the supplied Bash or PowerShell form.
Confirm with `agent-onboarding-status --provider dsh --agent-id ME` (add
`--native-session-id EXACT_ID` for an exact lookup). Do not rejoin with
`--new-session`. Report failed commands; do not install tools or widen permissions.

[Compact headers](agent_compact.md) · [Troubleshooting](agent_troubleshooting.md) ·
[Advanced CLI](agent_cli_onboarding.md).
