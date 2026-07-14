from __future__ import annotations

from dataclasses import dataclass, field

from agent_os.domain.value_objects.enums import ExecutionMode, ProtocolKind


@dataclass(frozen=True, slots=True)
class DeferredFeatureSettings:
    """Feature boundary toggles for advanced collaboration paths."""

    finite_round_discussion: bool = False
    heartbeat: bool = False
    convergence: bool = False
    scheduler_heartbeat_path: bool = False
    heartbeat_terminal_export_consumer: bool = False


@dataclass(frozen=True, slots=True)
class CoreSettings:
    """Configuration shape for wiring the Python orchestration core."""

    workspace_root: str
    plugins_directory: str
    default_protocol: ProtocolKind = ProtocolKind.JSON_RPC
    enabled_execution_modes: tuple[ExecutionMode, ...] = (ExecutionMode.SEQUENTIAL,)
    deferred_features: DeferredFeatureSettings = field(
        default_factory=DeferredFeatureSettings
    )
