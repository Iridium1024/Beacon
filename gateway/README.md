# Gateway Module

Node.js API gateway and transport boundary for the local shared-context
platform.

## Toolchain

Install declared dependencies from `gateway`:

```powershell
npm.cmd ci
```

On Linux/macOS, use `npm ci`. The committed `package-lock.json` is the normal
install baseline; use `npm install` only when deliberately updating dependencies
or the lockfile.

Run the current platform-facing Gateway checks:

```powershell
npm.cmd run build
npm.cmd run check
npm.cmd test
npm.cmd run test:platform-route
npm.cmd run test:platform-bridge
```

`package-lock.json` is the reproducible dependency baseline. `node_modules/`
and build outputs are local artifacts and must remain untracked.

## Build, Test, And Start

`tsconfig.json` uses `rootDir=.` and `outDir=dist`, so a package-local build
emits:

```text
dist/src/main.js
dist/tests/*.test.js
```

The npm scripts are:

- `npm run build`: compile Gateway source and package-local tests.
- `npm run check`: type-check without emitting files.
- `npm test`: run the current platform mainline tests.
- `npm run test:platform-route`: run platform route/config/API contract tests.
- `npm run test:platform-bridge`: run Python bridge and HTTP bridge smoke tests.
- `npm run test:legacy-heartbeat`: run the deferred heartbeat terminal export
  consumer test explicitly.
- `npm start`: start `dist/src/main.js`; run `npm run build` first.

Gateway tests live under `gateway/tests` so they remain available when
the standalone release directory is cloned independently. The old heartbeat
consumer test is still retained, but it is named as legacy and is not the
default `npm test` entry.

## Local Platform API State

The `/api/v1` local platform routes are contract-first. They expose workspace,
context, agent, invocation, record, session, provider connection, and agent
binding route shapes through `LocalPlatformApiAdapter`.

The default adapter is contract-only and returns stable not-connected
responses. It does not connect Python, a real provider, a UI, file writes, or a
browser/session connector.

The Gateway can run an explicit Python CLI bridge mode:

```powershell
$env:LOCAL_PLATFORM_BRIDGE_MODE='python_cli'
$env:LOCAL_PLATFORM_PYTHON_CORE_CWD='../python-core'
$env:LOCAL_PLATFORM_PYTHONPATH='src'
$env:LOCAL_PLATFORM_DATABASE='../runtime/state/local-platform.sqlite3'
$env:LOCAL_PLATFORM_WORKSPACE_ROOT='../workspace/sandboxes/local-platform'
$env:LOCAL_PLATFORM_PLUGINS_DIRECTORY='../plugins'
npm.cmd run build
npm.cmd start
```

Python resolution prefers an explicit `LOCAL_PLATFORM_PYTHON_COMMAND`, then an
active virtual environment, then `py -3.11` on Windows or
`python3.11`/`python3` on Linux/macOS. The bridge performs a cached Python 3.11+
preflight before its first operation.

Run the bridge smoke:

```powershell
npm.cmd run test:platform-bridge
```

The bridge uses non-shell Python child processes and keeps all traffic local.
Provider connections and agent bindings remain contract boundaries; no real
provider, browser session, account connector, UI, or file-write route is
enabled.

An explicit OpenAI-compatible provider mode is available through the same
Python CLI bridge. To enable it, set `LOCAL_PLATFORM_AGENT_ADAPTER_MODE` to
`openai-compatible-provider` and provide `AGENT_OS_OPENAI_COMPAT_BASE_URL`,
`AGENT_OS_OPENAI_COMPAT_MODEL`, and the configured credential environment
variable in the Gateway process environment. The bridge stores only provider
configuration and the credential environment variable name; it does not store
the credential value in Gateway config or logs.

The bridge smoke test uses a local fake OpenAI-compatible provider. Live
provider smoke is optional and must be explicitly authorized with a
user-supplied test credential.

Generic provider API shape passthrough is available through the same Python CLI
bridge. To enable it, set `LOCAL_PLATFORM_AGENT_ADAPTER_MODE` to
`provider-api-shape` and provide allowlisted provider shape settings such as:

```powershell
$env:AGENT_OS_PROVIDER_API_SHAPE='openai-responses'
$env:AGENT_OS_PROVIDER_BASE_URL='http://127.0.0.1:9999/v1'
$env:AGENT_OS_PROVIDER_MODEL='fake-responses-model'
$env:AGENT_OS_PROVIDER_NAME='openai-responses'
$env:AGENT_OS_PROVIDER_API_KEY_ENV_VAR='AGENT_OS_PROVIDER_TEST_CREDENTIAL'
$env:AGENT_OS_PROVIDER_INPUT_MODE='plain_text'
$env:AGENT_OS_PROVIDER_USER_AGENT='AgentChatRelaySmoke/14.2'
```

Allowed shapes are OpenAI-compatible Chat Completions, OpenAI Responses,
Anthropic Messages, Gemini generateContent, and Ollama `/api/chat`. Gateway
stores only the provider configuration and credential environment variable
name; credential values are copied from the Gateway process environment into the
Python child process only when needed. No provider credential store, remote
model discovery, browser/session connector, UI, or multi-user account system is
enabled.

`AGENT_OS_PROVIDER_INPUT_MODE` is optional. It currently matters for OpenAI
Responses-compatible relay endpoints: the default is official structured
Responses input, while `plain_text` sends a single string `input` for relays
that reject structured message arrays.

`AGENT_OS_PROVIDER_USER_AGENT` is also optional. It is a validated single-line
provider HTTP `User-Agent` compatibility setting for relays/providers that
require a specific client identity. Gateway does not expose arbitrary provider
HTTP header injection and does not store credential header values.

Local agent creation is available through the same bridge:

```text
POST /api/v1/workspaces/:workspaceId/agents
```

The request can include runtime profile metadata for profile name, role name,
system prompt, provider/model names, generation options, and reserved future
binding metadata. In explicit provider mode Python resolves the invoked agent
profile before calling the configured provider, so multiple local agents can use
the same provider/model connection with separate prompts and options. Credential
values are rejected by Python and are not stored by Gateway.

## Local API Safety Boundary

Gateway remains local-only for the current backend baseline:

- `GATEWAY_HOST` accepts only `127.0.0.1`, `localhost`, or `::1`.
- LAN/public bind addresses such as `0.0.0.0` are rejected at config load time.
- Route metadata includes `localApiPolicy: "local_only"`, `actorKind:
  "local_process"`, and reserved permission scopes for future product policy.
- The local access policy is not a user account system and does not read API
  keys, authorization headers, cookies, or provider credentials.
- Python bridge failures are converted into stable error envelopes without
  traceback or local filesystem path leakage.

Session-bound invocations through the Python bridge append explicit
`run_session.changed` lifecycle events. The session timeline response exposes
whether lifecycle events are present, whether the session is open or closed, and
how many invocation/context/file-operation events were observed.

## Deferred Feature Boundary

Gateway config exposes disabled-by-default switches for deferred collaboration
features:

- `GATEWAY_ENABLE_FINITE_ROUND_DISCUSSION`
- `GATEWAY_ENABLE_HEARTBEAT`
- `GATEWAY_ENABLE_CONVERGENCE`
- `GATEWAY_ENABLE_SCHEDULER_HEARTBEAT_PATH`
- `GATEWAY_ENABLE_HEARTBEAT_TERMINAL_EXPORT_CONSUMER`

These switches are configuration boundaries only. They must not be treated as
default runtime wiring for finite-round discussion, heartbeat, convergence, or
heartbeat terminal export consumer paths.
