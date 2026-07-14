# Local Workspace Lifecycle

Status: current developer note for macro step 6.1, with macro step 22.3
coordination addendum.

## Purpose

The local workspace lifecycle surface lets Python-local callers create an
invocation-ready workspace baseline from an initialized empty SQLite database.
It does not enable HTTP routes, real model providers, UI, desktop packaging, or
write-file behavior.

## Local Flow

```text
build_local_platform_runtime(settings)
  -> components.operations()
  -> create_workspace(...)
  -> workspace.changed event
  -> workspace current state
  -> minimal shared context current state
  -> deterministic default agent registration event and current state
  -> open_workspace(...) overview
```

## Methods

`LocalPlatformOperationService` exposes:

- `create_workspace(...)`
- `open_workspace(workspace_id)`
- `archive_workspace(workspace_id)`
- `ensure_workspace_baseline(workspace_id, ...)`

`create_workspace(...)` rejects duplicate workspace ids. If caller ids are not
supplied, it derives deterministic baseline ids:

- `context-<workspace_id>`
- `agent-<workspace_id>`

`ensure_workspace_baseline(...)` is explicit and idempotent. It reports whether
context or agent state was created.

`archive_workspace(...)` preserves history. It changes current workspace status
to `archived` and leaves context, invocation records, file-operation records,
and platform events intact.

Macro step 22.3 adds workspace-scoped project directory coordination records.
They are append-only advisory events that can be queried by workspace to show
which agents declared activity over a project root and path scopes. Archiving a
workspace prevents new coordination declarations through the local operation
service, but existing records remain part of the workspace event history.

## Example

```python
from agent_os.infrastructure.composition.local_platform import (
    build_local_platform_runtime,
)
from agent_os.infrastructure.config import LocalPlatformSettings

settings = LocalPlatformSettings(
    database="platform.sqlite3",
    workspace_root="X:/fixture/workspace",
    plugins_directory="X:/fixture/plugins",
)

components = build_local_platform_runtime(settings)
try:
    operations = components.operations()
    created = operations.create_workspace(
        workspace_id="workspace-1",
        display_name="Workspace",
        root_path="X:/fixture/workspace",
    )
    opened = operations.open_workspace("workspace-1")
finally:
    components.close()
```

The default agent id in this example is `agent-workspace-1`. The default context
id is `context-workspace-1`.

## Limits

- No CLI or `python -m` command is defined in 6.1.
- No Gateway route is enabled.
- No provider key is loaded and no network model call is made.
- No UI or desktop shell is implemented.
- Write-file operations remain disabled.
- Project directory coordination is not an OS lock, filesystem sandbox, git
  automation path, or file-body reader.
- Context baseline creation currently writes current state without a dedicated
  replayable context-created event. Full replayable baseline eventing remains a
  later persistence/recovery hardening task.
