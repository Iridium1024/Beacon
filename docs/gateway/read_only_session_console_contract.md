# Read-only session console contract

Status: shared local read contract; schema major `1`.

## Boundary

The Console API is a small projection over Beacon's existing workspace, Agent,
provider handle, dispatch, and append-only event state. It does not introduce a
second business-state store. Beacon is authoritative. The optional DeepSeek
Harness Web plugin, standalone Tauri Desktop, and its loopback-only browser
validation mode are presentation hosts only.

The host-neutral data source exposes exactly four read operations:

```text
checkHealth()
listWorkspaces()
getProviderBackends()
getWorkspaceView(workspaceId, cursor?, limit?)
```

The matching HTTP routes are GET-only:

```text
GET /api/console/v1/health
GET /api/console/v1/workspaces
GET /api/console/v1/provider-backends
GET /api/console/v1/workspaces/:workspaceId?cursor=ord:<n>&limit=<1..200>
```

There is no prompt, dispatch, queue, resume, cancel, steer/supplement, approval,
reply, provider-tool, credential, or configuration method. Unsupported HTTP
verbs are not registered. This namespace is loopback-only and is not an
authenticated remote API.

## DTOs and identity

The versioned surface contains `ConsoleWorkspaceView`, `ConsoleAgentView`,
`ForeignSessionRef`, `ProviderBackendView`, `ProviderCapabilities`,
`DispatchProjection`, and `ConsoleTimelineEvent`.

Provider-native identity is always the compound pair
`{ provider, nativeSessionId }`. DSH-native sessions are explicitly marked and
are never inferred for Claude, Codex, or Hermes records. Display names, cwd,
recent order, and native ids without a provider are not identity keys.

Every projection response carries `schema`, `schemaMajor`, `authority: "beacon"`,
and `readOnly: true`; workspace list/view envelopes additionally carry
`displayShell: "beacon_read_only_projection"`. The host-neutral `displayShell`
value deliberately does not grant ownership to DSH or Desktop. Unknown enum values are preserved as
`{ value: "unknown", rawValue, known: false }` so a newer producer does not
silently acquire older semantics.

Browser UI does not extend these DTOs. The session-first view derives its detail
matrix only from existing allowlisted fields: compound native identity from
`ForeignSessionRef.identity`, Beacon mapping from `handleId`, linked Agent name
from `ConsoleAgentView`, observed time and source sequence, native/foreign
projection markers, cwd summary, and continuity/recovery facts. Missing or
unknown values are rendered explicitly. A native session id is described as
resumable only when the existing backend and continuity semantics make that
claim; otherwise it is labeled as not guaranteed resumable.

The health response is `beacon.console.health.v1` and declares
`consoleSchema: "beacon.console.v1"`, `apiVersion: "1.0"`, `status: "ready"`,
`source: "gateway"`, Beacon authority, and `readOnly: true`. External Desktop
connection succeeds only after this bounded GET validates; an incompatible
health/schema/API version fails as the existing version diagnostic.

## Timeline and reconnect

Events use stable ids and deterministic `(sequence, eventId)` ordering. The
producer deduplicates repeated ids with first-sequence ownership; the client
repeats that rule when merging pages. Cursors use `ord:<non-negative integer>`.
The default page size is 50 and the hard maximum is 200.

Each page declares its cursor, next cursor, limit, returned/total counts,
`hasMore`, `truncated`, `cursorOutOfRange`, and `rebuildRequired`. A stable
rebuild token binds incremental pages to one snapshot lineage. A missing
sequence, cursor outside the current window, or changed token causes the client
to discard incremental state and perform one bounded snapshot rebuild. The
first version polls every 15 seconds; it is not a WebSocket, SSE, or live
subscription contract.

## Projection and redaction

The Python application builds the DTOs directly from normalized Beacon state.
It does not parse pretty CLI output, scan provider databases, read provider
transcripts, or import a DSH native event log. Timeline metadata uses an
allowlist and never includes raw payloads.

Responses exclude full prompts, transcript/message bodies, tool output,
credentials, environment values, source metadata, raw event payloads, and full
filesystem paths. Cwd is reduced to a safe summary. Response bytes, collection
sizes, string sizes, cursor values, and timeouts are bounded and validated
again by each presentation adapter. The standalone Desktop omits credentials,
rejects redirects, uses a five-second request timeout, and rejects a response
over 1 MiB before parsing.

## Standalone Desktop and browser-validation transport

Desktop host calls the Gateway namespace directly from the Tauri WebView. The user must
select an explicit-port origin on `http://127.0.0.1` or `http://localhost`;
userinfo, paths, queries, fragments, other schemes, IPv6, wildcard, LAN, and
public hosts fail closed. Gateway emits CORS only for reviewed local Vite/Tauri
origins and never for an arbitrary request origin.

Browser UI uses the same data source and component/store tree from a Vite host that
binds only `127.0.0.1`. Fake remains the zero-network default. Browser External
mode applies the identical explicit-loopback, GET-only, redirect, credential,
timeout, version, schema, and 1 MiB bounds; the browser does not own or manage
Gateway, Python, DSH, or Provider lifecycle.

Connection failure, timeout, permission denial, health/API or schema-major incompatibility,
oversize/malformed payload, timeline gap, truncation, and rebuild-required
state remain presentation diagnostics. None of them starts a Provider or
causes a write/retry outside the bounded read store.

Browser UI makes workspace/Provider/session navigation and selected-session detail
the primary information architecture. The permanent Fake source notice states
that checked-in examples are not activity from the current computer. External
healthy state states that it is a local Beacon Gateway read-only projection.
Timeline rows are secondary workspace-scoped Beacon event facts and are
explicitly not chat or transcript. Raw event kind, aggregate id, backend id,
and extensible-enum values remain only inside localized technical disclosures.

## Capability semantics

Capability rows distinguish an upstream/public interface from Beacon's current
backend implementation. A false or limited value must not be displayed as a
disabled control: the console explains the limit and has no corresponding
action path. The matrix explicitly covers send, resume, snapshot status,
owned-live status, supplement/steer, cancel, approval handling, history read,
final capture, cross-process resume, runtime ownership, and multi-session
management. DSH backend runtime ownership is separate from DSH Web console
ownership; closing the console cannot stop, attach to, or recreate a managed
DSH runtime.
