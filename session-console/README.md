# Beacon Session Console shared UI and optional DSH adapter

This package retains the DSH adapter local, loopback-only DSH Host/Client adapter and
owns the host-neutral React components, store, protocol validators, fixture,
styles, and locale provider reused by the Beacon Desktop/browser host. The
adapter composes the official DeepSeek
Harness (DSH) Web profile and mounts one Beacon plugin; Beacon remains
authoritative for workspaces, Agents, provider-native session identity,
dispatch state, timeline events, and backend capabilities.

The shared layer is exported from `src/client/host-neutral.ts`; the standalone
entry in `../desktop/` imports the same source modules directly. DSH slot
registration, generated profile, and ModuleLoader handoff stay in this adapter
and are not Desktop dependencies.

Browser UI keeps the shared workspace/Provider/session navigation and selected
session detail in this package while the Desktop/browser shell owns its unified
local Settings drawer and persistent data-source notice. Compound native
identity, Beacon handle mapping, linked Agent, time, source, continuity, and
recovery semantics are primary. Timeline, dispatch, raw identifiers, and
capability facts are secondary disclosures. Static facts remain noninteractive;
real session selection, filtering, refresh, help, and technical disclosures
remain keyboard reachable in both hosts.

This is an architecture spike, not a provider controller. It has no composer,
send, resume, cancel, steer/supplement, approval, reply, queue, credential,
provider-setting, or transcript-export path. DSH's host/trusted-host fence is
not authentication, so both DSH and Beacon Gateway must remain on loopback.

## Fixed upstream baseline

- DeepSeek Harness commit:
  `b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`
- DSH npm packages: exact `0.1.1-rc.2` (locked by `package-lock.json` and the
  executable compatibility gate)
- zixi visual-review commit:
  `e18e7617669b76c5a2386f9eb5e0421d98e6a050`

DSH supplies the Web composition/runtime. zixi was reviewed only for warm
neutral surfaces, density, status chips, appearance controls, focus treatment,
and narrow-window behavior. No zixi source, asset, storage model, Tauri setup,
brand, or product copy is included. See `NOTICE.md` and the architecture ADR.

## Prerequisites

- Node.js 22 or newer
- npm
- For Gateway mode, a local Beacon Gateway configured with
  `LOCAL_PLATFORM_BRIDGE_MODE=python_cli`

The package does not install DSH globally or modify the user's DSH home. Its
generated profile and dependencies live below the ignored `.runtime/` folder.
DSH `0.1.1-rc.2` creates junctions below `$DSH_HOME/profiles/node_modules` on
Windows. If the repository is on FAT32 or another volume without junction
support, set `BEACON_CONSOLE_DSH_HOME` to a dedicated directory on an NTFS
volume; the directory remains isolated from the normal user DSH home:

```powershell
$env:BEACON_CONSOLE_DSH_HOME = Join-Path $env:TEMP 'beacon-dsh-console-p3a'
```

## Fake/demo path

The lightweight demo uses only the checked-in synthetic fixture and never
starts a model or reads provider state:

```powershell
Set-Location '<PROJECT_ROOT>\session-console'
npm.cmd ci --ignore-scripts
npm.cmd run gate
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
npm.cmd run demo
```

Open `http://127.0.0.1:5173`. The demo binds only `127.0.0.1` and its middleware
answers GET/HEAD projection reads only.

## Official DSH Web profile path

Build and prepare the isolated DSH profile, then start the foreground-owned
Host against fake data:

```powershell
npm.cmd run build
npm.cmd run profile:prepare
npm.cmd run gate:profile
npm.cmd run dsh:fake
```

Open `http://127.0.0.1:4179`. Press `Ctrl+C` in that terminal to stop only the
DSH process started by this command. The script does not terminate existing DSH,
Beacon, Claude, Codex, or Hermes processes.

## Gateway-backed local path

Start Beacon Gateway separately on loopback, then:

```powershell
$env:BEACON_CONSOLE_GATEWAY_URL='http://127.0.0.1:4311'
npm.cmd run dsh:gateway
```

The DSH Host proxies only these Beacon reads under `/beacon-console/api`:

- `GET /health`
- `GET /workspaces`
- `GET /provider-backends`
- `GET /workspaces/:workspaceId?cursor=ord:<n>&limit=<1..200>`

Beacon Gateway's source namespace is `/api/console/v1`. `/health` validates
console API version/readiness before projection reads. A disconnected Bridge,
permission failure, malformed/oversized payload, invalid cursor, health/API/schema-major
mismatch, or rebuild-token change is shown as an explicit console state and
never triggers a provider operation.

## Verification

```powershell
npm.cmd run gate
npm.cmd run gate:profile
npm.cmd run typecheck
npm.cmd run lint
npm.cmd test
npm.cmd run build
```

The compatibility gate deliberately fails on DSH version/export/row drift. DSH
is still a fast-moving RC; upgrading it requires reviewing the exact package
exports, profile dump, bundle handoff, and public plugin services before
changing the pins.

The generated profile uses npm's legacy peer resolver only because the reviewed
RC Web graph has a pathologically expensive fresh peer search. Every runtime
peer that standard npm added during review is also a direct exact dependency
and is checked by the gate, so this optimization does not silently omit DSH
runtime packages.

## Current limits

- Snapshot plus bounded 15-second polling, not a live subscription.
- Fake browser and local Bridge coverage only; no authenticated provider/session
  or real-model smoke was run.
- No remote access, account authentication, or published installer. The
  separate Desktop host package validates a standalone Tauri development executable;
  this DSH adapter itself remains a Web/profile package.
- Foreign provider transcripts, prompts, tool output, credentials, databases,
  and full local paths are not projected.
