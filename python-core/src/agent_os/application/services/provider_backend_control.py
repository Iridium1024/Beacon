from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from threading import RLock
from typing import Callable, Mapping, Protocol, TypeVar


class ProviderBackendId(StrEnum):
    CLAUDE_CLI = "claude_cli"
    CLAUDE_AGENT_SDK = "claude_agent_sdk"
    CODEX_EXEC_RESUME = "codex_exec_resume"
    CODEX_APP_SERVER_STDIO = "codex_app_server_stdio"
    HERMES_CLI = "hermes_cli"
    HERMES_TUI_GATEWAY_STDIO = "hermes_tui_gateway_stdio"
    DEEPSEEK_HARNESS_SDK_STDIO = "deepseek_harness_sdk_stdio"


class ProviderRuntimeLifecycle(StrEnum):
    SHORT_LIVED_OPERATION = "short_lived_operation"
    MANAGED_RUNTIME = "managed_runtime"


class ProviderRuntimeOwnership(StrEnum):
    NONE = "none"
    OPERATION_OWNED = "operation_owned"
    PERSISTENT_OWNED = "persistent_owned"


class ProviderStatusAuthority(StrEnum):
    UNSUPPORTED = "unsupported"
    SNAPSHOT = "snapshot"
    POINT_READ = "point_read"
    OWNED_LIVE = "owned_live"


@dataclass(frozen=True, slots=True)
class ProviderBackendCapabilities:
    can_execute_inline: bool
    can_start_detached: bool
    can_wait: bool
    can_read_status: bool
    can_read_owned_live_status: bool
    can_manage_multiple_threads: bool
    can_supplement_active_turn: bool
    can_cancel: bool
    can_capture_final_message: bool
    can_own_runtime: bool

    def to_metadata(self) -> Mapping[str, object]:
        return {
            "canExecuteInline": self.can_execute_inline,
            "canStartDetached": self.can_start_detached,
            "canWait": self.can_wait,
            "canReadStatus": self.can_read_status,
            "canReadOwnedLiveStatus": self.can_read_owned_live_status,
            "canManageMultipleThreads": self.can_manage_multiple_threads,
            "canSupplementActiveTurn": self.can_supplement_active_turn,
            "canCancel": self.can_cancel,
            "canCaptureFinalMessage": self.can_capture_final_message,
            "canOwnRuntime": self.can_own_runtime,
        }


@dataclass(frozen=True, slots=True)
class ProviderBackendDescriptor:
    backend_id: ProviderBackendId
    provider: str
    lifecycle: ProviderRuntimeLifecycle
    runtime_ownership: ProviderRuntimeOwnership
    status_authority: ProviderStatusAuthority
    capabilities: ProviderBackendCapabilities
    current_implementation: str
    continuity_scope: str | None = None
    can_resume_across_runtime_restart: bool | None = None
    cancel_scope: str | None = None
    max_concurrent_operations: int | None = None
    existing_session_import: bool | None = None
    runtime_loss_effect: str | None = None

    def to_metadata(self) -> Mapping[str, object]:
        result: dict[str, object] = {
            "schema": (
                "provider_backend_descriptor.v2"
                if self.continuity_scope is not None
                else "provider_backend_descriptor.v1"
            ),
            "backendId": self.backend_id.value,
            "provider": self.provider,
            "lifecycle": self.lifecycle.value,
            "runtimeOwnership": self.runtime_ownership.value,
            "statusAuthority": self.status_authority.value,
            "capabilities": self.capabilities.to_metadata(),
            "currentImplementation": self.current_implementation,
        }
        optional = {
            "continuityScope": self.continuity_scope,
            "canResumeAcrossRuntimeRestart": self.can_resume_across_runtime_restart,
            "cancelScope": self.cancel_scope,
            "maxConcurrentOperations": self.max_concurrent_operations,
            "existingSessionImport": self.existing_session_import,
            "runtimeLossEffect": self.runtime_loss_effect,
        }
        result.update({key: value for key, value in optional.items() if value is not None})
        return result


@dataclass(frozen=True, slots=True)
class ProviderBackendSelection:
    requested_backend: ProviderBackendId
    effective_backend: ProviderBackendId
    source: str
    descriptor: ProviderBackendDescriptor
    fallback_applied: bool = False
    fallback_reason: str | None = None

    def to_metadata(self) -> Mapping[str, object]:
        result: dict[str, object] = {
            "schema": "provider_backend_selection.v1",
            "requestedBackend": self.requested_backend.value,
            "effectiveBackend": self.effective_backend.value,
            "source": self.source,
            "fallbackApplied": self.fallback_applied,
            "descriptor": self.descriptor.to_metadata(),
        }
        if self.fallback_reason is not None:
            result["fallbackReason"] = self.fallback_reason
        return result


def _capabilities(
    *,
    read_status: bool = False,
    owned_live: bool = False,
    supplement: bool = False,
    cancel: bool = False,
    own_runtime: bool = False,
) -> ProviderBackendCapabilities:
    return ProviderBackendCapabilities(
        can_execute_inline=True,
        can_start_detached=False,
        can_wait=True,
        can_read_status=read_status,
        can_read_owned_live_status=owned_live,
        can_manage_multiple_threads=False,
        can_supplement_active_turn=supplement,
        can_cancel=cancel,
        can_capture_final_message=True,
        can_own_runtime=own_runtime,
    )


_BACKENDS: Mapping[ProviderBackendId, ProviderBackendDescriptor] = {
    ProviderBackendId.CLAUDE_CLI: ProviderBackendDescriptor(
        backend_id=ProviderBackendId.CLAUDE_CLI,
        provider="claude",
        lifecycle=ProviderRuntimeLifecycle.SHORT_LIVED_OPERATION,
        runtime_ownership=ProviderRuntimeOwnership.OPERATION_OWNED,
        status_authority=ProviderStatusAuthority.UNSUPPORTED,
        capabilities=_capabilities(cancel=False),
        current_implementation="registered_session_cli_activation",
    ),
    ProviderBackendId.CLAUDE_AGENT_SDK: ProviderBackendDescriptor(
        backend_id=ProviderBackendId.CLAUDE_AGENT_SDK,
        provider="claude",
        lifecycle=ProviderRuntimeLifecycle.SHORT_LIVED_OPERATION,
        runtime_ownership=ProviderRuntimeOwnership.OPERATION_OWNED,
        status_authority=ProviderStatusAuthority.UNSUPPORTED,
        capabilities=_capabilities(cancel=False, own_runtime=True),
        current_implementation="short_lived_agent_sdk_streaming_operation",
    ),
    ProviderBackendId.CODEX_EXEC_RESUME: ProviderBackendDescriptor(
        backend_id=ProviderBackendId.CODEX_EXEC_RESUME,
        provider="codex",
        lifecycle=ProviderRuntimeLifecycle.SHORT_LIVED_OPERATION,
        runtime_ownership=ProviderRuntimeOwnership.OPERATION_OWNED,
        status_authority=ProviderStatusAuthority.UNSUPPORTED,
        capabilities=_capabilities(cancel=False),
        current_implementation="codex_exec_resume",
    ),
    ProviderBackendId.CODEX_APP_SERVER_STDIO: ProviderBackendDescriptor(
        backend_id=ProviderBackendId.CODEX_APP_SERVER_STDIO,
        provider="codex",
        lifecycle=ProviderRuntimeLifecycle.SHORT_LIVED_OPERATION,
        runtime_ownership=ProviderRuntimeOwnership.OPERATION_OWNED,
        status_authority=ProviderStatusAuthority.POINT_READ,
        capabilities=_capabilities(
            read_status=True,
            supplement=True,
            cancel=False,
            own_runtime=True,
        ),
        current_implementation="short_lived_app_server_stdio_operation",
    ),
    ProviderBackendId.HERMES_CLI: ProviderBackendDescriptor(
        backend_id=ProviderBackendId.HERMES_CLI,
        provider="hermes",
        lifecycle=ProviderRuntimeLifecycle.SHORT_LIVED_OPERATION,
        runtime_ownership=ProviderRuntimeOwnership.OPERATION_OWNED,
        status_authority=ProviderStatusAuthority.UNSUPPORTED,
        capabilities=_capabilities(cancel=False),
        current_implementation="registered_session_cli_activation",
    ),
    ProviderBackendId.HERMES_TUI_GATEWAY_STDIO: ProviderBackendDescriptor(
        backend_id=ProviderBackendId.HERMES_TUI_GATEWAY_STDIO,
        provider="hermes",
        lifecycle=ProviderRuntimeLifecycle.SHORT_LIVED_OPERATION,
        runtime_ownership=ProviderRuntimeOwnership.OPERATION_OWNED,
        status_authority=ProviderStatusAuthority.POINT_READ,
        capabilities=_capabilities(
            read_status=True,
            cancel=True,
            own_runtime=True,
        ),
        current_implementation="short_lived_tui_gateway_stdio_operation",
    ),
    ProviderBackendId.DEEPSEEK_HARNESS_SDK_STDIO: ProviderBackendDescriptor(
        backend_id=ProviderBackendId.DEEPSEEK_HARNESS_SDK_STDIO,
        provider="deepseek_harness",
        lifecycle=ProviderRuntimeLifecycle.MANAGED_RUNTIME,
        runtime_ownership=ProviderRuntimeOwnership.PERSISTENT_OWNED,
        status_authority=ProviderStatusAuthority.OWNED_LIVE,
        capabilities=_capabilities(
            read_status=True,
            owned_live=True,
            supplement=False,
            cancel=False,
            own_runtime=True,
        ),
        current_implementation="persistent_owned_sdk_jsonrpc_stdio_supervisor",
        continuity_scope="persistent_native_session",
        can_resume_across_runtime_restart=True,
        cancel_scope="none",
        max_concurrent_operations=1,
        existing_session_import=True,
        runtime_loss_effect="runtime_generation_unavailable_resume_required",
    ),
}


def provider_backend_registry() -> Mapping[str, Mapping[str, object]]:
    return {
        backend_id.value: descriptor.to_metadata()
        for backend_id, descriptor in _BACKENDS.items()
    }


def resolve_provider_backend(
    provider: object,
    *,
    claude_activation_backend: object = "cli",
    codex_activation_backend: object = "exec_resume",
    hermes_activation_backend: object = "cli",
    deepseek_harness_activation_backend: object = "managed_runtime",
    source: str = "resolved_provider_configuration",
) -> ProviderBackendSelection:
    normalized_provider = str(provider).strip().lower()
    if normalized_provider == "claude":
        normalized_backend = str(claude_activation_backend).strip().lower()
        backend_by_activation = {
            "cli": ProviderBackendId.CLAUDE_CLI,
            "agent_sdk": ProviderBackendId.CLAUDE_AGENT_SDK,
        }
        try:
            backend_id = backend_by_activation[normalized_backend]
        except KeyError as exc:
            raise ValueError(
                "claude activation backend must be cli or agent_sdk."
            ) from exc
    elif normalized_provider == "hermes":
        normalized_backend = str(hermes_activation_backend).strip().lower()
        backend_by_activation = {
            "cli": ProviderBackendId.HERMES_CLI,
            "tui_gateway": ProviderBackendId.HERMES_TUI_GATEWAY_STDIO,
        }
        try:
            backend_id = backend_by_activation[normalized_backend]
        except KeyError as exc:
            raise ValueError(
                "hermes activation backend must be cli or tui_gateway."
            ) from exc
    elif normalized_provider == "codex":
        normalized_backend = str(codex_activation_backend).strip().lower()
        if normalized_backend.endswith(".exec_resume"):
            normalized_backend = "exec_resume"
        elif normalized_backend.endswith(".app_server"):
            normalized_backend = "app_server"
        backend_by_activation = {
            "exec_resume": ProviderBackendId.CODEX_EXEC_RESUME,
            "app_server": ProviderBackendId.CODEX_APP_SERVER_STDIO,
        }
        try:
            backend_id = backend_by_activation[normalized_backend]
        except KeyError as exc:
            raise ValueError(
                "codex activation backend must be exec_resume or app_server."
            ) from exc
    elif normalized_provider == "deepseek_harness":
        normalized_backend = str(deepseek_harness_activation_backend).strip().lower()
        if normalized_backend not in {"managed_runtime", "sdk_stdio"}:
            raise ValueError(
                "deepseek_harness activation backend must be managed_runtime."
            )
        backend_id = ProviderBackendId.DEEPSEEK_HARNESS_SDK_STDIO
    else:
        raise ValueError("unsupported target provider.")
    descriptor = _BACKENDS[backend_id]
    return ProviderBackendSelection(
        requested_backend=backend_id,
        effective_backend=backend_id,
        source=source,
        descriptor=descriptor,
    )


T = TypeVar("T")


class ProviderBackendAdapter(Protocol[T]):
    selection: ProviderBackendSelection

    def execute_inline(self) -> T: ...


@dataclass(frozen=True, slots=True)
class CallableProviderBackendAdapter:
    selection: ProviderBackendSelection
    executor: Callable[[], Mapping[str, object]]

    def execute_inline(self) -> Mapping[str, object]:
        if not self.selection.descriptor.capabilities.can_execute_inline:
            raise RuntimeError("selected provider backend cannot execute inline.")
        return self.executor()


@dataclass(frozen=True, slots=True)
class ManagedRuntimeThreadBinding:
    thread_id: str
    workspace_root: str
    metadata: Mapping[str, object] = field(default_factory=dict)

    def to_metadata(self) -> Mapping[str, object]:
        return {
            "threadId": self.thread_id,
            "workspaceRoot": self.workspace_root,
            "metadata": dict(self.metadata),
        }


class ManagedProviderRuntime(Protocol):
    """Future persistent-runtime boundary; no production implementation yet."""

    runtime_id: str

    def bind_thread(self, binding: ManagedRuntimeThreadBinding) -> None: ...

    def read_thread_status(self, thread_id: str) -> Mapping[str, object]: ...


class ManagedRuntimeBindingSet:
    """Process-free scaffold proving thread-scoped identity and locking."""

    def __init__(self) -> None:
        self._bindings: dict[str, ManagedRuntimeThreadBinding] = {}
        self._locks: dict[str, RLock] = {}

    def bind_thread(self, binding: ManagedRuntimeThreadBinding) -> None:
        existing = self._bindings.get(binding.thread_id)
        if existing is not None and existing != binding:
            raise ValueError("threadId is already bound to different metadata.")
        self._bindings[binding.thread_id] = binding
        self._locks.setdefault(binding.thread_id, RLock())

    def binding(self, thread_id: str) -> ManagedRuntimeThreadBinding:
        try:
            return self._bindings[thread_id]
        except KeyError as exc:
            raise KeyError(f"unknown managed runtime thread: {thread_id}") from exc

    def lock_for(self, thread_id: str) -> RLock:
        self.binding(thread_id)
        return self._locks[thread_id]

    def to_metadata(self) -> Mapping[str, object]:
        return {
            "schema": "managed_provider_runtime_scaffold.v1",
            "implemented": False,
            "processManaged": False,
            "bindings": [
                self._bindings[key].to_metadata()
                for key in sorted(self._bindings)
            ],
            "lockScope": "thread_id",
        }
