from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class AgentId:
    value: str

    @classmethod
    def new(cls) -> "AgentId":
        return cls(str(uuid4()))


@dataclass(frozen=True, slots=True)
class AgentInvocationId:
    value: str

    @classmethod
    def new(cls) -> "AgentInvocationId":
        return cls(str(uuid4()))


@dataclass(frozen=True, slots=True)
class WorkflowId:
    value: str

    @classmethod
    def new(cls) -> "WorkflowId":
        return cls(str(uuid4()))


@dataclass(frozen=True, slots=True)
class WorkspaceId:
    value: str

    @classmethod
    def new(cls) -> "WorkspaceId":
        return cls(str(uuid4()))


@dataclass(frozen=True, slots=True)
class TaskId:
    value: str

    @classmethod
    def new(cls) -> "TaskId":
        return cls(str(uuid4()))


@dataclass(frozen=True, slots=True)
class IssueId:
    value: str

    @classmethod
    def new(cls) -> "IssueId":
        return cls(str(uuid4()))


@dataclass(frozen=True, slots=True)
class ContextId:
    value: str

    @classmethod
    def new(cls) -> "ContextId":
        return cls(str(uuid4()))


@dataclass(frozen=True, slots=True)
class ContextUpdateId:
    value: str

    @classmethod
    def new(cls) -> "ContextUpdateId":
        return cls(str(uuid4()))


@dataclass(frozen=True, slots=True)
class ConversationId:
    value: str

    @classmethod
    def new(cls) -> "ConversationId":
        return cls(str(uuid4()))


@dataclass(frozen=True, slots=True)
class ConversationMessageId:
    value: str

    @classmethod
    def new(cls) -> "ConversationMessageId":
        return cls(str(uuid4()))


@dataclass(frozen=True, slots=True)
class FileOperationId:
    value: str

    @classmethod
    def new(cls) -> "FileOperationId":
        return cls(str(uuid4()))


@dataclass(frozen=True, slots=True)
class PlatformRunSessionId:
    value: str

    @classmethod
    def new(cls) -> "PlatformRunSessionId":
        return cls(str(uuid4()))


@dataclass(frozen=True, slots=True)
class PlatformEventId:
    value: str

    @classmethod
    def new(cls) -> "PlatformEventId":
        return cls(str(uuid4()))


@dataclass(frozen=True, slots=True)
class MessageId:
    value: str

    @classmethod
    def new(cls) -> "MessageId":
        return cls(str(uuid4()))


@dataclass(frozen=True, slots=True)
class MemoryId:
    value: str

    @classmethod
    def new(cls) -> "MemoryId":
        return cls(str(uuid4()))


@dataclass(frozen=True, slots=True)
class PluginId:
    value: str

    @classmethod
    def new(cls) -> "PluginId":
        return cls(str(uuid4()))
