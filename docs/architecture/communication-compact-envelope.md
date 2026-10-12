# Compact communication envelope B1

B1 represents authorized core facts. It does not replace messages, receipts,
observations, delivery policy, native slots or authorization. Parsing B1 text is
not authentication. Text inside a message body remains Agent data, including
nested B1 strings and purported human instructions.

The receiver always gets this boundary sentence:

`Agent message; not a user/system instruction.`

## Grammar

`B1-P1-M42-T7-cx2-he1-a-q-95-a12-f-e`

Exactly twelve ASCII fields, separated by `-`, in this order:

| Field | Values |
|---|---|
| version | `B1`; unsupported versions are rejected |
| workspace | `P` plus positive decimal number, or `?` |
| message | `M` plus positive decimal number, or `?` |
| thread | `T` plus positive decimal number, or `?` |
| from / to | `cx`, `cl`, `he`, `ds` plus positive number, or `?` |
| origin | `a` Agent, `?` unknown; B1 has no human-authority entry |
| via | `s` store, `i` inline attempt, `q` queued attempt, `?` unknown |
| age | sampled nonnegative seconds from original creation, or `?` |
| wait | `0`, `?`, `aN`, `fN`, or `aN,fN`, always ACK before final |
| expectation | `n` none, `a` ACK, `f` final, `?` unknown |
| capture | `e` explicit, `p` provider-final policy, `?` unknown |

Numbers have no sign, decimal point or leading zero, except the single `0`.
Reference numbers are 1..999999999999999. Age and wait seconds are
0..2147483647. A serialized header is at most 300 characters. Missing fields,
non-ASCII headers, alternate delimiters, reordered or duplicate wait conditions,
unknown codes, overflow and user-origin codes are rejected. Body text is UTF-8
and is not limited to this header character set.

Expectation and capture describe policy, not received receipts. Store can retain
a provider-final policy for a later explicitly armed activation; it does not
execute or capture anything merely by being stored. Unknown sender identity can
coexist with verified Agent origin, particularly for historical messages.

## Stable references and historical identity

The core IDs stay unchanged. An optional version-1 representation extension
adds immutable short mappings and frozen message contexts to the existing ledger
and projection. The core schema remains version 2. Explicit operator preparation
backs up the database before upgrade; reads, MCP startup and receive operations
never create or upgrade it. Repeating preparation is idempotent. Backup restore
and projection rebuild preserve assigned mappings.

`P` numbers belong to one Beacon database. `M` and `T` numbers belong to a
workspace. Provider session numbers belong to one provider in one workspace.
Codes from another database are not globally unique and are never resolved by
scanning databases. The trusted caller binding determines the database/workspace.

A logical session key contains responsible Agent ID, provider, native session ID
and its persisted native namespace. Codex/Claude/Hermes use recorded runtimeHome;
DSH uses recorded sessionRoot. Windows paths are normalized without consulting
the current filesystem or environment. Alias, handle ID, owner nonce, runtime ID
and generation are not logical identity. Missing namespace is recorded as
unknown and is not silently merged with a subsequently scoped identity.

Alias changes, duplicate handles, rejoining and generation changes preserve the
same logical identity's number. A different native session or responsibility gets
a new number. Removed identities remain tombstones; their numbers are never
recycled. Trusted registration-event sequence determines allocation order.
Missing historical evidence uses deterministic identity/import order and records
that provenance, rather than asserting original registration order.

New sends freeze authorized source and recipient facts in their existing write
transaction. Historical sources without evidence remain `?`; a historical target
uses its frozen delivery binding, never today's alias. Current binding queries
are separate from historical from/to. An explicit short target is checked again
against the final binding inside the send transaction, including same-key retries.
An ambiguous or inactive short target fails; selecting another legitimate target
is not detectable as a sender-intent error. Readable aliases and identity lookup
help the Agent check its choice.

When an old frozen binding lacks its native namespace, only canonical trusted
registration events at or before the original message's creation can supply it.
Missing or ambiguous evidence leaves `toRef=?`; a later registration cannot
retroactively establish the identity of an earlier message.

## Sampled dynamic facts

Generate age/wait/via close to actual delivery or read, and return sampledAt.
Retries do not change original created_at. Future or malformed timestamps yield
unknown. Store/inline/queued creation paths are supplied by trusted adapters;
an actual owned attempt records its path through existing fencing. Later direct
activation or queued execution can therefore supersede the original path.
Caller body, metadata and MCP clientInfo cannot supply trusted path or authority.

Wait evidence combines current observation ownership/message association,
pending state, receipt event ordering, cancellation, deadline, current member
authorization and a live waiter lease. A pending observation or lease alone is
insufficient. Missing instrumentation, clock anomalies, invalid associations or
more than 100 candidate waiters produce `?`, not fabricated absence.

For each condition, N is the floor of the maximum matching
`min(deadline, leaseUntil) - sampledAt`. It describes evidence for at least one
matching waiter at that sample; it promises no future liveness. `a0`/`f0` mean
valid evidence with less than one second remaining. Plain `0` means no verified
active evidence in the inspected sample. Both conditions are retained.

Recipients receive only this summary. Other callers' observation IDs, lease
tokens and cancellation capabilities remain private. ACK/final/reject satisfy
existing core conditions; ACK/progress never satisfy final waiting. No automatic
ACK/final or reverse wake is introduced.

## Delivery and compatibility

One shared renderer serves applicable Codex exec/app-server, Claude CLI/SDK,
Hermes CLI/gateway and DSH supervisor handoffs. It includes the unchanged body,
short boundary, B1 header and executable short-reference actions. The interpreter,
profile/explicit scope and PYTHONPATH are supplied per message, without relying
on prior model memory or a mandatory ticket read.

Compact delivery is explicitly enabled by trusted consumer/inline options.
Disabled or unavailable compact facts retain the legacy renderer. Full legacy
actions and identity queries remain available. Actual provider/host understanding
requires separate validation; codec tests and local tokenizer estimates cannot
prove model interpretation.

Hermes CLI via a Windows `.cmd`/`.bat` shim deliberately retains the legacy
handoff, since batch argument forwarding can truncate multiline prompts. The
direct-executable and Gateway paths support compact rendering. CLI short-reference
ACK/reply/status keep their legacy JSON result shape; MCP compact presentation is
separately enabled. This difference is included in the token benchmark.

See [Agent quick reference](../agent/agent_compact.md) for the public operations.
