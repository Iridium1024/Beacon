# Local Platform Composition

Status: current developer note for macro steps 3, 4.6, 5.1, 5.2, 6.1, 6.2, 7, 8.2, 9, 10, and 11.

## Purpose

This note records the current local backend composition path for the Python
platform runtime.

The current local path is:

```text
LocalPlatformSettings
  -> build_local_platform_runtime
  -> configured SQLite connection
  -> SQLite schema initialization
  -> optional LocalPlatformInitialState storage
  -> SqlitePlatformInvocationRuntimeHandler
  -> optional explicit controlled file operations
  -> optional local operation service via components.operations()
  -> optional workspace lifecycle and baseline operations via components.operations()
  -> optional LocalPlatformApplication facade and python -m command entrypoint
  -> contract-first Gateway /api/v1 route surface
  -> optional Gateway python_cli bridge to Python-local runtime
  -> optional provider-backed per-agent profile resolution
  -> stable local invocation response
```

## Settings

Use `LocalPlatformSettings` to describe the local database and adapter mode:

```python
from agent_os.infrastructure.config import LocalPlatformSettings

settings = LocalPlatformSettings(
    database="platform.sqlite3",
    workspace_root="X:/fixture/workspace",
    plugins_directory="X:/fixture/plugins",
)
```

The default adapter mode keeps the existing deterministic placeholder agent
path.

To explicitly use the deterministic provider-backed model path:

```python
from agent_os.infrastructure.config import (
    LocalAgentInvocationAdapterMode,
    LocalPlatformSettings,
)

settings = LocalPlatformSettings(
    database="platform.sqlite3",
    workspace_root="X:/fixture/workspace",
    plugins_directory="X:/fixture/plugins",
    agent_invocation_adapter_mode=(
        LocalAgentInvocationAdapterMode.DETERMINISTIC_PROVIDER
    ),
)
```

## Composition

Build the local runtime through the narrow composition root:

```python
from agent_os.infrastructure.composition.local_platform import (
    build_local_platform_runtime,
)

components = build_local_platform_runtime(settings)
try:
    response = components.handle_payload(
        {
            "workspaceId": "workspace-1",
            "agentId": "agent-1",
            "instruction": "Capture this local request.",
        }
    )
finally:
    components.close()
```

This composition root does not fill the broad `build_core()` scaffold. It only
opens local persistence and wires the executable invocation path that exists
today.

`connect_local_platform_database(...)` applies platform-required SQLite
connection settings before the schema initialization step. Foreign-key
enforcement is therefore active even when callers intentionally skip schema
initialization for an already-created database.

The same invocation handler path is used by the local payload entrypoint and the
opt-in SQLite Gateway bridge. After macro step 4.5, these local backend
entrypoints are equivalent for explicit controlled `fileOperations` payloads,
including preflight validation and audit-safe failure behavior.

After macro step 5.1, the same composition root also exposes
`components.operations()`. This returns a local API-wrap-ready operation service
for persisted workspace, context, agent registration, task, and issue
current-state reads, plus explicit context append.

After macro step 5.2, `components.operations()` also exposes run-session
timeline reads, agent invocation record queries, and file operation record
queries. These are still Python-local service methods, not Gateway routes.

After macro step 6.1, `components.operations()` also exposes workspace
`create/open/archive` and explicit idempotent baseline operations. These methods
can create an invocation-ready workspace, shared context, and deterministic
default agent in an initialized empty SQLite database.

After macro step 6.2, `LocalPlatformApplication` wraps this composition root as
a non-UI local program facade. The package command `python -m
agent_os.local_runtime` exposes the same backend capabilities as JSON-returning
commands for local smoke and future UI/API wrapping.

After macro step 7, Gateway exposes a contract-first `/api/v1` local platform
route surface over a `LocalPlatformApiAdapter` interface. The default registered
adapter is `ContractOnlyLocalPlatformApiAdapter`, so routes return stable
not-connected envelopes until a later Python bridge task connects the runtime.

After macro step 8.2, Gateway also has `PythonLocalPlatformApiAdapter`. When
`LOCAL_PLATFORM_BRIDGE_MODE=python_cli`, Gateway routes call
`python -m agent_os.local_runtime` through non-shell child processes and can run
workspace lifecycle, context, invocation, record, file-operation record, agent
list, and session timeline operations over the Python-local runtime.

After macro step 10, the same composition can explicitly select an
OpenAI-compatible provider adapter behind `ModelProviderPort`.

After macro step 11, the composition root builds a per-agent invocation adapter
factory when provider mode is enabled. The factory resolves
`AgentRegistration.runtime_config` through `AgentRuntimeProfile` so each agent
can use its own role/system prompt and generation options while staying inside
the configured provider/model boundary.

## Local Runtime Entrypoint

Use the facade when a local caller needs a stable application boundary instead
of direct component/store access:

```python
from agent_os.application.services import LocalPlatformApplication
from agent_os.infrastructure.config import LocalPlatformSettings

application = LocalPlatformApplication(
    LocalPlatformSettings(
        database="platform.sqlite3",
        workspace_root="X:/fixture/workspace",
        plugins_directory="X:/fixture/plugins",
    )
)

smoke = application.run_smoke()
```

Use the command entrypoint for a local executable smoke flow:

```powershell
$env:PYTHONPATH='src'
py -3.11 -m agent_os.local_runtime `
  --database platform.sqlite3 `
  --workspace-root X:/fixture/workspace `
  --plugins-directory X:/fixture/plugins `
  smoke
```

The command prints JSON. Runtime errors are returned as a stable JSON error
envelope on stderr with a non-zero exit code. The command does not start a
long-running service or enable HTTP.

## Local Operation Surface

Use `components.operations()` when a local caller needs backend state without
calling the single-turn invocation handler:

```python
operations = components.operations()
created = operations.create_workspace(
    workspace_id="workspace-1",
    display_name="Workspace",
    root_path="X:/fixture/workspace",
)
opened = operations.open_workspace("workspace-1")
workspaces = operations.list_workspaces()
context = operations.get_context("workspace-1")
agents = operations.list_agent_registrations("workspace-1")
agent = operations.create_agent_registration(
    "workspace-1",
    name="Reviewer",
    description="Reviews local work.",
    default_model="fake-chat-model",
    runtime_config={
        "profile": {
            "profileName": "reviewer",
            "roleName": "reviewer",
            "systemPrompt": "Review local work.",
            "generationOptions": {"temperature": 0},
        }
    },
)
timeline = operations.get_run_session_timeline("workspace-1", "session-1")
invocations = operations.list_agent_invocation_records("workspace-1")
file_operations = operations.list_file_operation_records("workspace-1")
```

The operation service returns JSON-compatible mappings and keeps deterministic
ordering in list responses through the SQLite current-state readers.

Workspace lifecycle writes are explicit. `create_workspace(...)` records a
`workspace.changed` event, writes current workspace state, then ensures minimal
shared context and deterministic agent registration. `archive_workspace(...)`
marks current state as archived without deleting history.
`ensure_workspace_baseline(...)` can safely be called again and reports whether
it created context or agent baseline state.

Agent registration writes are explicit. `create_agent_registration(...)`
records an `agent_registration.changed` event and stores runtime profile
metadata after rejecting inline credential values.

Context append is explicit:

```python
result = operations.append_context_update(
    "workspace-1",
    update_kind="note",
    summary="Captured local note",
    materialized_state_patch={"latest_note": "Captured local note"},
)
```

The append path records a context update event, updates materialized context
state, and returns the appended update, updated context payload, and event-log
sequence. It does not create an autonomous tool loop or enable any HTTP route.

Run/session status is currently a timeline read model over event-log rows with
`session_id`. Invocation and file operation records are read from the dedicated
SQLite audit record stores. File operation record responses omit file body
content.

## Initialization

An empty local database can be initialized with explicit minimal state:

```python
from agent_os.infrastructure.composition.local_platform import (
    build_local_platform_runtime,
)
from agent_os.infrastructure.composition.local_platform_initialization import (
    LocalPlatformInitialState,
)

components = build_local_platform_runtime(
    settings,
    initial_state=LocalPlatformInitialState(
        workspace_id="workspace-1",
        context_id="context-1",
        agent_id="agent-1",
        workspace_display_name="Workspace",
        workspace_root="X:/fixture/workspace",
        agent_name="Runtime Agent",
        agent_description="Handles local requests",
        agent_capability_name="single-turn-status",
        agent_capability_description="Captures single-turn requests",
    ),
)
```

The initializer stores workspace, shared context, and agent registration state
as a local seed baseline with source event sequence `0`.

It does not append replayable platform events. Recovery from the event log
starts after this seed baseline until a later initialization-event task is
added.

For new local runtime flows, prefer the 6.1 operation-service lifecycle methods
when the caller wants auditable workspace creation:

```python
components = build_local_platform_runtime(settings)
try:
    created = components.operations().create_workspace(
        workspace_id="workspace-1",
        display_name="Workspace",
        root_path="X:/fixture/workspace",
    )
finally:
    components.close()
```

This path records workspace and agent-registration events and creates an
invocation-ready baseline without requiring the test-only initialization helper.

## Current Limits

- Default invocation still uses the deterministic placeholder agent path.
- Provider-backed model paths are explicit opt-in. OpenAI-compatible provider
  invocation exists through the configured provider mode and local fake-provider
  tests; live provider calls require a caller-supplied environment credential.
- Local and remote HTTP providers remain placeholders.
- No provider credential value is stored by this composition path.
- Agent runtime profiles can override prompt/options for the configured
  provider/model, but they do not create full chat histories or remote
  conversation instances.
- Agent invocation idempotency currently depends on invocation audit records;
  payloads with `idempotencyKey` fail fast when invocation recording is disabled.
- Explicit controlled file operations are supported locally, but write
  operations and dedicated HTTP file-operation routes remain disabled.
- Local operation service reads, workspace lifecycle writes, baseline creation,
  explicit context append, runtime smoke, and record queries are available
  through the Python composition root, `LocalPlatformApplication`, and
  `python -m agent_os.local_runtime`.
- Gateway `/api/v1` wrappers exist as a contract-first route surface, but the
  default adapter is not connected to Python. Explicit `python_cli` mode connects
  the same route family to Python-local runtime.
- Run-session timeline, invocation-record, and file-operation-record query
  surfaces are available through the Python local operation service only.
- Full run-session lifecycle persistence/writer APIs remain deferred.
- A formal non-UI local facade, `python -m` command, and end-to-end local smoke
  flow now exist. Daemon/service hosting, product HTTP API connection, UI,
  desktop shell, and packaging remain deferred.
- The local database must use an existing parent directory.
- UI and packaging remain outside this step.

## Verification Commands

Run from `python-core`:

```powershell
$env:PYTHONPATH='src'
py -3.11 -m unittest tests.test_local_platform_settings tests.test_local_platform_composition tests.test_local_platform_initialization
py -3.11 -m unittest tests.test_local_platform_operations tests.test_workspace_state_store tests.test_agent_registration_state_store tests.test_task_state_store tests.test_issue_state_store
py -3.11 -m unittest tests.test_platform_event_log tests.test_agent_invocation_record_store tests.test_file_operation_record_store
py -3.11 -m unittest tests.test_platform_invocation_runtime_handler tests.test_platform_invocation_local_entrypoint tests.test_local_platform_application tests.test_local_runtime_entrypoint tests.test_local_single_turn_use_case_composition
py -3.11 -m unittest discover -s tests
```

Gateway source-level route and bridge verification depends on local TypeScript tooling:

```powershell
npm.cmd run check
npm.cmd run test:platform-route
npm.cmd run test:platform-bridge
```
