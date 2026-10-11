"""Bind one trusted local startup identity; no SDK, provider I/O or schema init."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import json

from agent_os.application.services.communication_agent import AgentCommunication, registered_source
from agent_os.application.services.communication_policy import dispatch_backend_capture
from agent_os.application.services.project_workspace_scope import resolve_runtime_profile_from_project_scope
from agent_os.domain.entities.communication import Caller, CommunicationError
from agent_os.infrastructure.composition.communication_runtime import prepared_runtime
from agent_os.infrastructure.config import LocalPlatformSettings


def load_bound_settings(*, profile=None, start=None, workspace_id=None):
    path, scope, _ = resolve_runtime_profile_from_project_scope(
        explicit_profile_path=profile, environment_profile_path=None, start=start)
    if path is None:
        raise CommunicationError("explicit profile or nearest project marker is required")
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise CommunicationError("profile must be an object")
    data = loaded.get("localRuntime")
    if not isinstance(data, dict):
        raise CommunicationError("profile requires a localRuntime object")
    selected = data.get("workspaceId")
    if not isinstance(selected, str) or not selected.strip():
        raise CommunicationError("profile requires workspaceId")
    if (workspace_id is not None and workspace_id != selected) or (scope and scope.workspace_id != selected):
        raise CommunicationError("workspace/profile/marker conflict")
    def required(name):
        value = data.get(name)
        if not isinstance(value, str) or not value.strip():
            raise CommunicationError("profile requires " + name)
        candidate = Path(value)
        return str((Path(path).parent / candidate).resolve() if not candidate.is_absolute() else candidate.resolve())
    settings = LocalPlatformSettings(database=required("databasePath"), workspace_root=required("workspaceRoot"),
        plugins_directory=required("pluginsDirectory"), profile_path=path, initialize_schema=False,
        record_agent_invocations=False)
    return settings, selected


def bind_communication(settings, workspace_id, agent_id, *, alias=None, backends=None):
    settings = replace(settings, initialize_schema=False, record_agent_invocations=False)
    @contextmanager
    def opened():
        with prepared_runtime(settings, workspace_id) as (_, service):
            yield service
    with opened() as service:
        binding = registered_source(service, Caller(workspace_id, agent_id), alias or agent_id)
    # These options come only from the operator's process configuration, never
    # tool arguments. Consumer/provider preflight still checks actual capability.
    selected = {"codex": "exec_resume", "claude": "cli", "hermes": "cli",
                "deepseek_harness": "sdk_stdio", **dict(backends or {})}
    allowed = {"codex": {"exec_resume", "app_server"}, "claude": {"cli", "agent_sdk"},
               "hermes": {"cli", "tui_gateway"}, "deepseek_harness": {"sdk_stdio"}}
    if any(provider not in allowed or backend not in allowed[provider] for provider, backend in selected.items()):
        raise CommunicationError("unsupported configured backend")
    def backend_policy(provider):
        backend = selected[provider]
        return dispatch_backend_capture(provider, backend, "explicit_only" if provider == "codex" else None)
    return AgentCommunication(binding, opened, backend_policy=backend_policy)
