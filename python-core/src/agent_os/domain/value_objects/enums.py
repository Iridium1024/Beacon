from enum import StrEnum


class ExecutionMode(StrEnum):
    """Supported orchestration modes."""

    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    HYBRID = "hybrid"


class WorkflowStatus(StrEnum):
    """Lifecycle states emitted by orchestration."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class MessageRole(StrEnum):
    """Canonical roles for model and agent messages."""

    SYSTEM = "system"
    USER = "user"
    AGENT = "agent"
    TOOL = "tool"


class ProtocolKind(StrEnum):
    """Transport abstractions supported by the scaffold."""

    JSON_RPC = "json-rpc"
    HTTP = "http"
    STDIO = "stdio"


class PluginHookName(StrEnum):
    """Lifecycle hook names exposed to plugins."""

    BEFORE_PLAN = "before_plan"
    AFTER_PLAN = "after_plan"
    BEFORE_STEP = "before_step"
    AFTER_STEP = "after_step"
    BEFORE_RESPONSE = "before_response"
    AFTER_RESPONSE = "after_response"
