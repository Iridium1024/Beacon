# Communication core contract

This developer contract covers the communication foundation, integration and
independent execution ownership in this checkout. It is not replacement Agent
onboarding documentation. See the [local MCP guide](../agent/agent_mcp.md) and
[B1 contract](communication-compact-envelope.md) for their optional adapters.
Real workspace migration and authenticated provider operation are not validated
by the offline contract tests.

## Decision and boundaries

The old request stores one response and becomes terminal on that response. Adding
ACK, progress and independent waits there would multiply exceptions. The communication core instead
implements message facts, recipient delivery, receipts, execution evidence and
observations as separate facts. Existing provider adapters, registrations, native
continuity checks and user permission settings remain unchanged.

The modules are:

- `domain/entities/communication.py`: frozen values, errors, receipt/evidence
  vocabulary, canonical serialization and native-session slot identity.
- `domain/ports/communication.py`: directory and transactional repository ports.
- `application/services/communication_core.py`: in-process agent operations and
  a separate executor evidence surface. It runs no process or network request.
- `infrastructure/persistence/communication_store.py`: explicit schema version 2,
  SQLite UoW, immutable ledger and indexed projections in the existing database.
- `infrastructure/adapters/communication_directory.py`: read-only integration with
  existing workspace/agent materialized state, endpoint bindings, contact policy
  and legacy thread visibility. It does not discover or register native sessions.

The dependency direction is service -> domain ports; infrastructure implements
those ports. The compatibility directory contains the dependency on legacy
application services, including the existing contact-policy evaluator. That
dependency is isolated for later extraction, not copied into the new core.

Production composition has a read-only `communication_mode(workspace_id)` selector
and constructs the core facade only for an explicitly cut-over workspace. Normal
CLI old send/request/dispatch/thread/reply/close/status paths, new message paths,
one-shot worker/daemon and direct registered-session activation choose that
same core; the legacy writer remains for uncut workspaces. Construction of the repository
does not create tables. Its explicit `initialize()` requires the existing platform
schema and rejects an active caller transaction. Schema creation alone never
switches workspace ownership.

## In-process surface

Construct a `SqliteCommunicationRepository(connection)`, explicitly initialize it
on a test platform database, and construct `CommunicationService(repository,
PlatformCommunicationDirectory(connection), clock=...)`. No new database path or
daemon configuration is introduced. One connection is owned by one
operation at a time; concurrent callers use independent connections.

Agent operations:

| Operation | Meaning |
|---|---|
| `send(caller, target_alias, body, key, ...)` | Commit immutable message, recipient snapshot, optional scheduling intent and audit event atomically; return the message. No consumer is started or claimed to exist. |
| `get/status` | Read authorized facts from projections. Execution, delivery, reply and expiry are distinct. |
| `inbox(cursor, limit, include_bodies=False)` | Return addressed events incrementally; bodies opt in. A read never marks anything read. |
| `ack` | Idempotent non-terminal acknowledgement by the intended recipient. |
| `reply(kind=progress/final/reject)` | Append a related receipt. `reply` defaults to final, not ACK. |
| `close` | Stop eligibility for new activation. Does not cancel a running provider. |
| `observe` / `observation_status` / `cancel_observation` | Persist and evaluate independent finite reply observations, not online waiter leases. |

Single-target send is the supported operation. Storage nevertheless keys
delivery and receipt uniqueness by workspace/message/recipient. There is no group
broadcast, automatic reverse wake, conversation loop or task/workflow engine.
`reply_to` links a new directed message to an existing visible message and inherits
its thread. Replies themselves enter only the original sender's inbox and do not
create a second dispatch.
Inbox `from`/`to` describe the event's actual direction: recipient-to-sender for
receipts, sender-to-recipient for original messages and close notices. The original
message ID remains available for correlation.

`Caller` is a declared local routing identity, not process authentication. Core
checks active workspace membership, target identity and thread visibility. Agent
inputs cannot select user authority; their message origin is always `agent`.
The compatibility directory reuses the current contact policy. Its simple
route remains direct-only; the explicit route can validate a matching delegated
grant reference under the old authorization policy, including an already
consumed valid reference. It does not consume the grant. Disabled policy fails
closed. Public/participants-only
visibility uses the existing wire vocabulary. Imported legacy threads recheck
current legacy visibility on reads; new participants cannot be added to a private
legacy thread until migration. No parallel identity registry is created.
For routes with a resolved old-CLI source alias, `send` can store explicit source
alias/handle, target handle and reply policy. The directory validates the exact
route rather than guessing an alias, and claim repeats the check before external
I/O. The compatibility adapter checks old thread budgets, follow-up/child limits,
length and grant references inside the core send transaction. A separate
transactional platform append couples grant consumption with activation facts;
sending a message by itself never consumes a delegated grant.

## State invariants

Messages and receipts are immutable; close/expiry live in derived state or events.
Each recipient has at most one ACK and one terminal final/reject. Duplicate ACKs
return the original ACK even with another operation key. Duplicate final with the
same idempotency key and payload returns the original; a new key or conflicting
payload cannot overwrite a terminal result. Progress remains append-only.

Idempotency is `(workspace, declared actor, operation, key)` and stores canonical
intent and original result in the same transaction. Canonical JSON sorts keys,
normalizes timestamps to UTC, and preserves body/array content. Runtime timestamps
and generated identities are not part of the caller's intent fingerprint. A
retry cannot silently retarget a previously committed send after an alias changes.
Returning an idempotent result still rechecks current thread visibility.

| Fact | Evidence and behavior |
|---|---|
| Stored | Message and recipient intent committed. No provider acceptance implied. |
| Accepted | An executor adapter supplies correlated positive acceptance evidence. |
| Execution | Starts as not_started. `mark_started` durably marks the external-I/O boundary but reports unknown execution until provider evidence arrives. |
| ACK | Only explicit recipient ACK; database storage or final capture never invents an ACK event. |
| Final | Explicit reply or policy-enabled, correlated trusted provider final. An existing explicit final wins over later capture. |
| Failed execution with captured final | A trusted, accepted failed attempt can retain its final with `requires_user_review=true`; execution remains failed. This matches the existing Codex failure-review branch without declaring success. |
| No reply expected | Does not require ACK/final to complete an accepted delivery. No permanent waiting_response obligation. |
| Late result | Final after message expiry/close is retained with `late=true`; does not satisfy business reply waits or revive activation. |

Deadline comparisons use UTC timestamps. Receipt time must be strictly before the
wait deadline; equality is timed out. Earlier final can satisfy ACK observation
without fabricating ACK history. A rejection ends either wait as `rejected`.
Cancellation retains the event high-water mark, so a later receipt with the same
clock timestamp cannot revive it. Waiting before/after a receipt, multiple
observers, process restart and observer cancellation do not own or cancel execution.
With runtime instrumentation, `active_waiter_verified` reports a message-scoped
waiter lease sample. It does not prove that a particular observation remains
pending or that an Agent is online. Compact delivery uses the joint observation,
receipt, deadline and lease checks described in the
[B1 contract](communication-compact-envelope.md).
Message expiry, observation deadline, target lease and provider timeout are separate.

## Executor boundary and recovery

`claim`, `mark_started`, `complete`, `release`, and `reconcile` are internal executor
operations, not agent tools. ProviderEvidence is trusted only as an internal port
contract: the actual adapter must validate provider-native receipt/turn/final,
continuity, generation and permissions before constructing it. A caller-controlled
`trusted_final=true` field is not a security proof and must never be accepted by a
public agent endpoint. Core tests fake evidence shapes for all four providers and
DSH generation correlation. Adapter tests exercise each existing backend adapter with
controlled fake transports, not authenticated provider sessions.

Claim serializes on workspace + hash(provider, exact native session), excluding
alias, agent, handle and runtime generation. This intentionally conservatively
serializes identical native IDs even from different provider homes. It avoids
accidentally permitting concurrent execution; a future verified namespace adapter
may distinguish homes. Shared cross-workspace profiles remain manual-only.

Each claim increments a durable fence. The worker must commit `mark_started`
before any external I/O, then act outside all SQLite transactions. Both claim and
mark_started revalidate current workspace permission, visibility and the exact
recipient binding. A revoked policy or changed alias/handle between these
operations prevents the start. The eventual provider adapter still owns native
continuity/permission checks at its external boundary. Lease expiry:

- Before mark_started: provably no compliant executor I/O; release and allow a
  bounded new attempt. A delayed old worker fails its fence/lease check.
- After mark_started: execution/delivery may have occurred; mark unknown and block
  another activation of that native session until explicit reconciliation.
- An old owner cannot complete or release after expiry or a newer fence. Explicit
  reconciliation accepts fresh stopped evidence only for the still-current
  unknown attempt. It cannot overwrite a subsequent owner.

Safe release, unstarted lease expiry and positive non-delivery evidence recheck
message eligibility before scheduling another attempt: closed, expired or already
replied messages remain cancelled, expired or done respectively.

An explicit release after start also becomes unknown. Positive not_delivered
evidence permits a bounded retry; it cannot contradict prior acceptance. Finished
execution without acceptance leaves delivery unknown and does not auto-replay.
No database guarantee is described as exactly-once external tool execution. The core records claim and provider timeouts. The runtime described below
supervises ownership independently of the caller.

`renew_lease` is available for the existing inline/worker owner. It extends only a
live matching claim before expiry, never restores an expired fence, and records an
event. Its caller must arrange actual heartbeats while a long provider operation
runs; this method alone does not provide worker liveness. The one-shot worker
instead sets a bounded lease at least 30 seconds longer than its configured
provider timeout (maximum one hour), then uses explicit expiry reconciliation.
An expired started attempt becomes unknown and blocks the native slot; neither
timeout nor a crashed worker proves a safe replay.
Repository candidate queries support due-time filtering; imported queued items
with future eligibility cannot be claimed early. They do not start a consumer.

## Transactions, events and cursors

All writes use short `BEGIN IMMEDIATE` transactions, foreign keys and unique
indexes. No SQLite transaction spans provider/network I/O or an ACK wait. The UoW
rejects nested/unowned transactions and detects accidental commits outside it.

`communication_events` is the sole new-core ledger in the SAME platform SQLite
database. Its after-images update messages, deliveries, receipts, attempts, slots,
thread snapshots, observations, idempotency and inbox projections in one commit.
Legacy `platform_events` is unchanged: its per-append commit is not called from
these transactions. The two ledgers do not both write the same new message. A unified read view must not create a dual-write business engine.

Every projection row has a source event sequence. Explicit maintenance rebuild
replays the new ledger under one transaction; failure rolls back the prior views.
It is an offline maintenance operation, not a normal status query. Read paths use
indexed materialized state; they do not replay communication history.

Schema v2 adds event-derived workspace mode and legacy ID mapping projections.
`CommunicationMigration.preview()` is read-only. `migrate()` requires an operator
assertion that old writers are stopped, creates/upgrades schema separately, then
imports historical facts, mappings and one mode marker in a single transaction.
The assertion is not process fencing; an old binary must actually be stopped.
Request ID reuse and multiple dispatches per request block cutover with a report.
Preview also reports legacy platform writes that occurred after a cutover marker;
repeating migrate refuses to treat that drift as an idempotent success.
Only old request/thread/dispatch aggregates count as communication drift;
unrelated registration or grant facts may still be written by the platform.
Stable IDs include the original platform event sequence. Terminal history has no
schedule; ambiguous in-flight work stays unknown. An exact, active, authorized
queued route with no prior attempt may become pending. Historical inactive
bindings remain null, and closed/private threads retain read visibility for
eligible participants. No real workspace has been migrated by this work.

The current binary fences old request/dispatch/thread/worker/provider writers
when it sees a core marker. Older running binaries do not know that marker, so
the stopped-writer requirement remains. `SqlitePlatformEventLog.append_in_transaction`
can add a platform-domain fact to the core UoW without the ordinary append's
eager commit; a fault test verifies both ledgers roll back together. Grant
consumption now serializes through `BEGIN IMMEDIATE` and appends activation and
consumption facts in one transaction; injected append failure rolls back both.

The CLI exposes `agent-message-get/status/inbox/ack/reply` for an
explicitly migrated workspace. Old send, request, dispatch, reply and thread
commands choose the core when that workspace has a marker. Core reads require an
explicit viewer identity. Old reply keeps strict active/expiry and recipient
checks; a caller cannot label its own reply as trusted provider capture. ACK and
progress do not terminate the request. Old `sourceEventSequence` is null for
new facts; `communicationLedgerSequence` names the new domain. Existing provider
branches call one internal final-recording method. Under core-owned scope it
records correlated evidence in the core only; legacy workspaces retain the old
result writer.

Cursor includes version, database identity, workspace, viewer, last sequence and
optional fixed page upper bound. Each stream entry corresponds to a visible
message/receipt/control event, not merely message creation time. New events during
paging appear on the next completed page window. Event and projection visibility
is atomic; an uncommitted projection cannot be skipped by an advanced cursor.
Malformed, foreign-scope and ahead-of-database cursors are rejected. Permission is
rechecked on each read. If visibility is later granted for previously skipped
history, explicit `get`/a fresh inbox scan is needed; old cursors do not rewind.

## Compatibility and migration contract

| Legacy concept | New mapping / constraint |
|---|---|
| request + requestSummary/detailRefs | Message body/refs plus delivery intention; retain stable legacy-to-new ID mapping. |
| responseSummary / agent-reply | Terminal final receipt. ACK is a separate operation. |
| replyPolicy | Existing source-handle/contact reachability policy; never reinterpret as ACK/final expectation. |
| queued/retry_scheduled | Eligible recipient scheduling projection only when non-delivery is proven. |
| leased | Current attempt/slot; expired does not imply provider stopped. |
| waiting_response | Project execution/delivery independently; old uncertain items require reconciliation. |
| completed | Compatibility view from facts, not a new authoritative state enum. |
| default inline, busy return, explicit queue | Preserve defaults; new independent waits require explicit worker ownership in the runtime. |
| reply does not wake sender | Preserved. New source-side work is a new directed send. |

Provider writeback extraction points in `local_platform_operations.py` (locate by
function and calls, not fixed line numbers):

- `activate_claude_registered_session`: SDK and CLI branches call old respond.
- `activate_codex_registered_session`: app-server and exec-resume/final capture
  branches call old respond.
- `activate_hermes_registered_session`: TUI gateway and CLI capture branches.
- `activate_deepseek_harness_registered_session`: trusted root-final capture.

All seven backends execute through their existing restricted runner under a
core-owned scope. The worker performs the sole core evidence write. The same
provider runners still serve legacy workspaces through the old writer. Backend
capture defaults and native continuity checks remain in the existing runners;
fake CLI/SDK/TUI/app-server/DSH adapter tests cover the branches offline.

| Backend selection | Frozen default capture policy |
|---|---|
| Codex `exec_resume`, `app_server` | `explicit_only` |
| Claude `cli` | `provider_final_capture` |
| Claude `agent_sdk` | `explicit_only` |
| Hermes `cli` | `provider_final_capture` |
| Hermes `tui_gateway` | `explicit_only` |
| DSH `sdk_stdio` | `provider_final_capture` |

An explicit override is stored with the delivery. The adapter requires a
correlated provider start plus a non-ambiguous terminal runner status to mark
the attempt stopped; a ticket or exit code alone is insufficient. Only a
policy-enabled trusted captured final or an independently committed explicit
final proves recipient acceptance. A stopped no-reply execution may be
`finished` while delivery remains `unknown`. DSH root receipt/idle/generation,
Codex turn/permission/cwd and other native checks remain in their runners.

Before a workspace cutover, stop old writers/workers. `CommunicationMigration`
previews without mutation, takes an explicit SQLite backup to a new path, then
initializes schema separately from its import transaction. Stable UUID5 IDs
include workspace/entity/legacy ID/original platform sequence; persisted mappings
also retain the old ID and source sequence. Import, projections and the mode
marker commit together. Duplicate request IDs, multiple dispatches per request
and live old leases block the cutover. Terminal history creates no scheduling
intent; proven unprocessed queued entries can migrate; waiting/unknown work
stays non-runnable. Missing historical bindings stay queryable but cannot execute.

After new-semantic writes, switching to an old binary is not lossless rollback.
`downgrade_advice` refuses automatic rollback and reports whether new semantic
writes exist. Recovery requires stopping writers, preserving/exporting the
post-backup `communication_events`, and a manual restore/reconciliation review.
There is no destructive downgrade command. The current binary fences cut-over
request/dispatch writers; an older binary cannot read the marker and must be
stopped operationally. Legacy workspaces continue using old writers.

The core selector is workspace-specific and read-only. Normal CLI send defaults to
inline execution; `--queued` leaves an explicit pending intent for a one-shot
worker or the bounded existing daemon. Dry-run neither sends nor claims. A busy
default inline attempt cancels its pending intent. A direct Claude, Codex or
Hermes registered-session activation may arm an existing request-only core message, but cannot create a
second request or silently select another recipient.

Core CLI messages use `messageId`; old request and dispatch IDs resolve through
the mapping table. An explicit send idempotency key scopes to workspace, source
agent and operation. Reply remains final by default. `agent-message-inbox` is
agent-scoped and paged; `--include-bodies` opts into full text. Generated receiver
argv carries database, workspace root, plugin directory, optional profile,
workspace and request/message identity as separate argv tokens. `sourceEventSequence`
is only for the old platform ledger; `communicationLedgerSequence` is for the
new ledger. Console/Gateway retain their old platform-event timeline and expose
a separate redacted `communicationLedger` page with `ledger:<sequence>` cursor;
it contains event kind and receipt kinds but no message or reply body. Core
agent-scoped reads recheck visibility at read time. Granting visibility later
requires a fresh inbox scan or direct get, not reuse of an advanced cursor.

The existing wake ticket remains a diagnostic event, never an ACK or proof of
provider acceptance. Core wake status/list project delivery/execution facts
with explicit agent identity. The old standalone wake watcher does not own core
execution; use the one-shot worker or the explicitly prepared consumer below
for core workspaces.

## Independent execution and finite waits

Only an explicitly cut-over core workspace can enable runtime coordination.
`communication-runtime-init --workspace-id W` initializes version 1 operational
tables in the same database. Status reads do not initialize tables; unknown
versions/database identities fail closed. There is no implicit live migration.
With the same explicit profile, start the existing
`agent-dispatch-daemon-start --workspace-id W --activation-concurrency 2` entry.
The continuous core consumer covers the whole workspace; selected target/dispatch
execution remains `--once`. Legacy daemon behavior and one-shot execution remain.

The supervisor owns its connection, consumer generation/lease and a bounded
set of activation subprocess handles. Each activation assembles its own
connection, provider adapter and capture scope. The caller owns its send
connection and optional waiter only. Closing or killing the sender does not
stop the consumer or receiver. PID plus launch nonce correlates operational
records; only retained owned OS handles authorize cleanup. These capabilities
do not confer user authority or authenticate an agent beyond the existing
local trust boundary.

`agent-dispatch-send ... --wait ack|final --wait-timeout-seconds 120` commits a
queued message only if a running consumer lease is currently valid. It never
starts a consumer or falls back to inline. Queued send without waiting can
still exist without a consumer. An idempotent retry recovers an already
committed message before applying the new-message availability guard.
Send and observation creation are two recoverable steps: after interruption,
retry the send with its original idempotency key or call
`agent-message-wait --workspace-id W --agent-id A --message-id M --condition ack|final`.
An earlier ACK/final is recognized before checking consumer availability.
`--wait once` retains its original inline meaning; ordinary send, busy return,
dry-run and reply policy remain unchanged.

ACK waits accept ACK/final; final waits ignore ACK/progress. Reject, cancellation,
deadline equality and receipt ordering follow the core observation rules.
Results contain IDs, condition, deadline, sampled time and separate delivery/
execution/consumer states; reply text requires `--include-bodies` on message wait.
`agent-message-wait-status --workspace-id W --agent-id A --message-id M` lists
only A's observations, allowing cancellation while a caller is waiting. Query
one with `--observation-id O`; cancel it with `agent-message-cancel-wait ...
--observation-id O`. Cancellation, timeout or waiter death never cancels the
message/provider. Observation pending is not proof of a live waiter.
Message status exposes redacted condition/deadline/lease samples only to its
sender/recipient. Recent waiter heartbeat proves only recent waiting activity,
not that the whole agent is online. Cleanup requires only that waiter's capability
and remains possible after message visibility is revoked.

Consumer generation checks join core claim/start/renew/complete transactions.
Old generations cannot revive or complete attempts. A native session's aliases
and handles share one slot. Keyset paging selects one candidate per native key,
bounded concurrency allows different keys to proceed, and periodic bounded
scans recover pending work after restart. Busy/backoff/unknown keys cannot hide
other candidates behind a global earliest-100 prefix. This is fairness among
eligible routes: a revoked/rebound target backs off without stopping other keys;
stale consumer ownership still stops scheduling. Fairness applies to
eligible keys with available capacity, not preemption or a business dependency
solver. Cyclic waits can occupy all slots until their finite timeout; agents
should acknowledge and separate longer follow-up work when appropriate.

Wake intents coalesce only notification version/dirty hints. Conditional version
drain cannot erase a concurrent send; messages, attempts, receipts and model
turns are never merged. Heartbeats update operational rows rather than append
business events. Operational audit retains at most 500 transitions per workspace;
bounded cleanup removes old waiter/settled activation/unused clean hint records,
keeping unknown evidence and all business history.

Concurrency is 1..16, provider timeout 1..3570 seconds, attempt lease 1..3600,
and other intervals must be finite. Consumer lease needs at least three heartbeat
intervals; poll cannot exceed heartbeat. Daemon defaults retain 5s polling/
heartbeat, 30s consumer lease, 300s attempt lease, 120s provider timeout and a
10s drain budget. Standalone runtime defaults poll .2s/heartbeat 2s/attempt lease
30s. Operational connections have a 100ms SQLite contention bound; failure
does not renew ownership. Provider I/O and process waits occur outside SQL
transactions. Renewals never extend the original provider deadline. Output is
discarded in the activation launcher, so an unread pipe cannot stall scheduling.

`communication-runtime-stop` requests drain, stops new claims and lets owned
work finish within the drain budget. Exact owned child cleanup then has finite
adapter waits (up to 4s per stop call, plus a Windows tree-stop attempt up to 2s;
close can retry cleanup after an error, with the same finite bounds).
DSH activation cleanup stops only its activation handle, preserving a separate
managed runtime. Abrupt consumer death does not prove its children/providers
stopped. Before-start death is safely recoverable; after-start/ACK/final death
keeps execution unknown and blocks automatic replay. Final is reply evidence,
not stop evidence. Fenced children can retain correlated internal native evidence;
`communication-runtime-reconcile --workspace-id W --attempt-id T` applies only
that retained evidence through the existing fenced reconcile rule. Callers cannot
submit stop/capture flags. An unknown result without native stop evidence still
requires explicit verification; there is no exactly-once external execution claim.

Directory assembly injects a narrow reader. Shared contact/reply policy has one
pure implementation. A transitional legacy reader delegates existing private
authorization reads; budget/grant atomicity stays with the existing policy owner.
Runtime/wait use ports and structured query results, not CLI parsing, UI state or
concrete SQLite tables. Existing daemon status projects consumer lease when
coordination is enabled. MCP and B1 consume these narrow wait/runtime queries;
their representation rules are documented separately. Documentation compression
remains outside this runtime. Live providers, a real workspace cutover and non-Windows process
tree behavior are not established by the offline fixtures.

Envelope changes follow B1's separate versioned contract. Representation and
onboarding documentation can evolve without replacing this ledger.
