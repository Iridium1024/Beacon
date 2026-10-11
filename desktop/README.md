# Beacon local read-only Desktop/browser host

`desktop/` is the current shared React/Vite browser host and Tauri v2 thin host
for Beacon's versioned, redacted `beacon.console.v1` projection. The Tauri host
provides a Windows window; the browser host uses the same React tree in a
system browser. This is one
local product host, not a second Web product, published service, installer, or
Provider controller.

The package has no runtime dependency on DeepSeek Harness (DSH), a Node Host,
Gateway, Python, or a Provider when it runs in Fake mode. DSH remains an
optional DSH presentation adapter in `../session-console/`; it is not linked
into this executable.

## Exact baseline

- React / React DOM: `18.3.1`
- Tauri CLI: `2.11.4`
- Rust `tauri`: `2.11.5`
- `tauri-build`: `2.6.3`
- Vite: `7.3.6`
- TypeScript: `5.9.2`
- Playwright Test: `1.62.1` (development-only deterministic browser gates)
- Rust dependencies: locked by `src-tauri/Cargo.lock`
- npm dependencies: locked by `package-lock.json`

Dependency versions and licenses are listed in `NOTICE.md`.

## Read-only modes

### Fake

Fake is the default. It imports the same checked-in synthetic fixture and
protocol validators as DSH adapter. It performs no HTTP request and does not start a
Gateway, Python, DSH, or Provider process.

The Settings panel exposes five deterministic Fake scenarios for repeatable
product and test review: normal data, empty workspaces, empty sessions,
truncated timeline, and rebuild-required timeline. They transform only the
checked-in synthetic projection and never read real Provider data.

### External Gateway

External Gateway connects only to a user-selected origin shaped as
`http://127.0.0.1:<port>` or `http://localhost:<port>`. An explicit port is
required. Userinfo, paths, query strings, fragments, HTTPS, IPv6, wildcard,
`0.0.0.0`, LAN, and public hosts are rejected.

The Desktop calls only:

```text
GET /api/console/v1/health
GET /api/console/v1/workspaces
GET /api/console/v1/provider-backends
GET /api/console/v1/workspaces/:workspaceId?cursor=ord:<n>&limit=<1..200>
```

Requests omit credentials, reject redirects, time out after five seconds, and
reject responses over 1 MiB. Initial connection requires a compatible
`beacon.console.health.v1` response declaring console API `1.0`, ready health,
Beacon authority, and a read-only Gateway source. Schema-major, redaction, unknown-enum,
pagination, replay, gap, and rebuild rules come from the shared console protocol.
The connection setting stores only the mode and normalized non-sensitive
loopback origin in WebView local storage.

No prompt, send, queue, resume, cancel, steer/supplement, approval, reply,
Provider tool, credential, configuration, transcript, or export method exists
in the Desktop data source.

## Local browser validation

### Windows CMD entry

For the browser validation host, double-click `../start-beacon-browser.cmd` in
the Beacon root. It resolves its own directory, checks Node.js, `npm.cmd`, the
checked-in local Vite dependency, and port 1420 before starting the existing
`npm.cmd run browser:dev` script in the visible foreground window. It opens the
browser only after a bounded readiness probe succeeds. Press `Ctrl+C` or close
that window to stop the host it started.

The CMD entry never installs dependencies, starts Gateway/Python/DSH/Tauri/a
Provider, requests elevation, changes firewall rules, or binds outside
`127.0.0.1`. If dependencies are missing, follow the verification setup below;
the launcher fails closed with that instruction instead of downloading packages.

Start the browser host with one documented loopback-only command:

```powershell
Set-Location '<BEACON_ROOT>\desktop'
npm.cmd run browser:dev
```

Open `http://127.0.0.1:1420`. Vite uses `strictPort` and binds only
`127.0.0.1`; it never listens on `0.0.0.0`, LAN, or a public interface. Fake
mode requires no Gateway, Python, DSH, Tauri runtime, or Provider.

The single Settings entry contains:

- `zh-CN` and `en-US` interface language;
- light, dark, or system appearance;
- standard or enhanced contrast;
- finite 90%, 100%, or 110% text scaling;
- Fake scenario or explicit loopback Gateway connection.

Only those non-sensitive preferences are stored in browser local storage under
versioned allowlists. Credentials, tokens, transcript content, full paths, and
Provider configuration are neither accepted nor persisted. Product status is
layered into workspace/Provider/session navigation, a selected-session detail
view, discoverable term definitions, and real technical-detail disclosures.
Identity, source, observed time, linked Agent, Beacon handle, and continuity are
primary; bounded activity, dispatch, and Provider capability facts are
secondary. Fake is permanently labeled as a synthetic demo dataset that is not
activity from the current computer. Static state facts do not pretend to be
controls.

This host intentionally
contains no create-workspace, target picker, composer, send/queue, confirmation,
or write handler.

### Build outputs

Tauri executables are local build outputs and are not included in this source
release. The browser entry does not rebuild them. Managed Desktop process
ownership is not implemented.

## Tauri security boundary

- the Rust builder registers zero application commands and exposes no custom
  IPC handler;
- the only capability file has an empty permission list;
- no shell, filesystem, SQL, arbitrary HTTP, updater, opener, download, or
  process-management plugin is enabled;
- CSP defaults to `self`, denies objects/forms/frames, avoids `unsafe-eval`,
  and permits connections only to `127.0.0.1` or `localhost` HTTP origins;
- a Rust navigation guard allows only bundled `tauri://` /
  `http://tauri.localhost` pages and the exact development URL;
- production developer tools are disabled and prototypes are frozen;
- no sidecar exists, so closing Desktop ends only Desktop.

Loopback is a routing boundary, not authentication. Do not expose the Gateway
on a LAN or public interface.

## Develop and verify

Prerequisites are Node.js 22+, npm, Rust/Cargo with the MSVC target, Windows C++
build tools/SDK, and WebView2.

```powershell
Set-Location '<BEACON_ROOT>\desktop'
npm.cmd ci --ignore-scripts
npm.cmd audit
npm.cmd run typecheck
npm.cmd run lint
npm.cmd test
npx.cmd playwright install chromium
npm.cmd run test:e2e
npm.cmd run build:web
cargo fmt --manifest-path src-tauri\Cargo.toml -- --check
cargo check --manifest-path src-tauri\Cargo.toml
cargo test --manifest-path src-tauri\Cargo.toml
npm.cmd run tauri:build
```

`tauri:build` uses `--no-bundle`. On Windows it produces the development
executable at:

```text
src-tauri/target/release/beacon-desktop.exe
```

The executable is ignored build output. Desktop host intentionally does not create an
MSI/NSIS package, sign code, install a sidecar, or publish a release.

## Known limits

- snapshot plus bounded 15-second polling, not a subscription;
- local single-user validation only; no authentication or remote deployment;
- no bundled/managed Gateway or Python lifecycle;
- no installer, updater, migration, signing, or distribution hardening;
- fake and synthetic SQLite/Gateway evidence only; no authenticated real
  Provider, model, transcript, or session smoke was run.
- the browser is a local validation host, not a managed runtime or public Web
  deployment; owned Gateway/Python lifecycle is not implemented.
