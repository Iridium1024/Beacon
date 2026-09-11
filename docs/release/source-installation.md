# Source Installation and Optional Provider Runtimes

Status: installation guidance for the unreleased DSH source increment. It is
deliberately credential-free and does not assert authenticated provider
availability.

## What This Delivery Is

This delivery is a source update. A Git commit, GitHub source archive, or an
archive extracted from one is **not** a standalone installer or independently
runnable application. Install the required runtime and dependencies before
using the CLI. A future GitHub Release and a future packaged installer are
separate deliverables; neither is created merely by publishing this source.

The DSH increment is optional. The core Beacon CLI does not require Gateway,
DSH, a provider account, or provider credentials to install, show help, and
run its local non-provider checks.

## Required: Core CLI

`python-core/pyproject.toml` declares Python 3.11 or newer and `PyYAML>=6.0`.
Use an isolated virtual environment and install the source package
non-editably when validating an extracted source archive.

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install .\python-core
.\.venv\Scripts\beacon.exe --help
```

Linux/macOS:

```bash
python3.11 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install ./python-core
./.venv/bin/beacon --help
```

`beacon --help` verifies the installed command only. It neither logs in to a
provider nor proves that a real model can communicate.

For source development, replace `pip install ./python-core` with
`pip install -e ./python-core`; this is not required for a source-release
consumer.

## Optional: Gateway

Gateway is not required when using the core CLI alone. Its
`gateway/package.json` declares Node.js `>=22`; use the committed lockfile:

```powershell
Set-Location gateway
npm.cmd ci
npm.cmd run build
npm.cmd start
```

On Linux/macOS, use `npm` in place of `npm.cmd`. The default Gateway mode is
`contract_only`; it does not start the Python bridge or a provider. The
optional Python bridge requires the core CLI environment above and the explicit
environment settings documented in [`../../README.md`](../../README.md#gateway).
Run `npm.cmd run check` and `npm.cmd test` to validate the optional Gateway
build without a live provider.

## Optional: DeepSeek Harness Fourth Agent Platform

DSH is not the `deepseek` model preset and is not installed globally by
Beacon. Exact persisted-session resume uses the project-local Node carrier in
`integrations/deepseek-harness-node/`, whose lockfile pins the audited DSH
packages to `0.1.1-rc.2`. On Windows, this route requires Node.js 22.19 or
newer; the documented Python carrier is only available for new-session mode on
a platform with a supported upstream wheel.

Install the local carrier only when using DSH:

```powershell
Set-Location integrations\deepseek-harness-node
npm.cmd ci
node --version
node --check beacon-sdk-jsonrpc-server.mjs
```

Use an isolated DSH runtime home and an approved session-persistence root. Do
not point Beacon at a foreign live Web, TUI, or Desktop process. A representative
local profile (replace every placeholder; do not commit it with secrets) is:

```json
{
  "localRuntime": {
    "deepseekHarnessControl": {
      "enabled": false,
      "activationBackend": "managed_runtime",
      "carrier": "node",
      "executablePath": "<NODE_EXECUTABLE>",
      "packageRoot": "<BEACON_SOURCE_ROOT>/integrations/deepseek-harness-node",
      "cordisConfigPath": "<BEACON_SOURCE_ROOT>/integrations/deepseek-harness-node/cordis.yml",
      "runtimeHome": "<APPROVED_ISOLATED_DSH_HOME>",
      "stateRoot": "<LOCAL_BEACON_RUNTIME_STATE>",
      "sessionRoot": "<APPROVED_DSH_SESSION_ROOT>",
      "sessionCompression": "zstd",
      "modelProvider": "<DSH_CONFIGURED_PROVIDER>",
      "model": "<DSH_CONFIGURED_MODEL>",
      "replyWritebackMode": "explicit_only"
    }
  }
}
```

The code and locked carrier do not define a universal DSH account-login command
or a verified credential environment-variable name. Obtain the compatible DSH
runtime and configure its provider authentication according to the official
DSH/provider documentation for the account and model selected by the operator.
Keep credentials outside Beacon profiles and the repository. The exact
authenticated configuration is intentionally **not confirmed** by this source
increment: no authenticated real-model communication test has been run.

With a known native session and already-configured DSH runtime, the following
is a read-only persistence/path preflight, not a model smoke:

```powershell
beacon deepseek-harness-runtime-preflight `
  --dsh-carrier node `
  --dsh-executable "<NODE_EXECUTABLE>" `
  --dsh-package-root "<BEACON_SOURCE_ROOT>/integrations/deepseek-harness-node" `
  --dsh-cordis-config "<BEACON_SOURCE_ROOT>/integrations/deepseek-harness-node/cordis.yml" `
  --dsh-session-root "<APPROVED_DSH_SESSION_ROOT>" `
  --dsh-session-compression zstd `
  --session "<NATIVE_SESSION_ID>"
```

See [`../providers/deepseek_harness_managed_runtime.md`](../providers/deepseek_harness_managed_runtime.md)
for ownership, exact-session, stop/resume, and continuity boundaries.

## Other Provider Features

Claude, Codex, and Hermes integrations are optional registered-session
features. Beacon does not install their tools, create accounts, store tokens,
or complete provider login. Before registering a session, the operator must:

1. Install the applicable official provider client/runtime and complete that
   provider's own login/authorization flow outside Beacon.
2. Run Beacon's read-only provider preflight where applicable.
3. Explicitly register or join an already-approved native session with
   `agent-join --provider <claude|codex|hermes> --session <NATIVE_SESSION_ID>`.

The optional Claude Agent SDK additionally requires
`python-core[claude-agent-sdk]`; the optional Hermes TUI Gateway accepts only
the audited `hermes-agent==0.19.0` runtime. The exact commands, compatibility
checks, and session-registration boundaries are in
[`../providers/provider_guides.md`](../providers/provider_guides.md). Client
installation or a successful preflight is not evidence of a live service
response.

## Validation Boundary and Later Release Assets

The source increment is validated through automated Python tests, fake
protocol/runtime tests, and an offline locked-runtime/persistence integration.
Those tests do not authenticate a real DSH account or exchange a real model
request. Real DSH authentication and model communication remain a long-term,
high-priority, separately authorized smoke test.

When source synchronization is approved, identify the exact public commit (or
a later approved tag) that contains this increment. A GitHub Release may then
attach generated assets from that immutable source point. A future independent
installer/runtime package still needs its own build, test, signing, and release
process; even then, users must separately configure their own provider account,
authentication, paths, and service settings.
