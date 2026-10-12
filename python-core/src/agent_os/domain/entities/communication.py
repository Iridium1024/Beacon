"""Provider-neutral communication values. Caller identity is declared, not authenticated."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json

class CommunicationError(ValueError):
    pass


class Conflict(CommunicationError):
    pass


class AccessDenied(CommunicationError):
    pass


class StaleAttempt(Conflict):
    pass


class ReceiptKind(StrEnum):
    ACK = "ack"
    PROGRESS = "progress"
    FINAL = "final"
    REJECT = "reject"


class ReplyExpectation(StrEnum):
    NONE = "none"
    ACK = "ack"
    FINAL = "final"


class EvidenceOutcome(StrEnum):
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"
    NOT_DELIVERED = "not_delivered"
    UNKNOWN = "unknown"


def text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CommunicationError(f"{name} must be non-empty text")
    return value


def stamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CommunicationError("time must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def delivery_identity(message_id: str, target: str) -> str:
    return canonical([message_id, target])


@dataclass(frozen=True, slots=True)
class Caller:
    workspace_id: str
    agent_id: str

    def __post_init__(self) -> None:
        text(self.workspace_id, "workspace_id")
        text(self.agent_id, "agent_id")


@dataclass(frozen=True, slots=True)
class RecipientBinding:
    agent_id: str
    alias: str
    provider: str
    native_session_id: str
    handle_id: str
    generation: str | None = None
    automatic_activation_allowed: bool = True

    def __post_init__(self) -> None:
        for name in ("agent_id", "alias", "provider", "native_session_id", "handle_id"):
            text(getattr(self, name), name)
        if self.provider not in {"codex", "claude", "hermes", "deepseek_harness"}:
            raise CommunicationError("unsupported provider")
        if self.generation is not None:
            text(self.generation, "generation")
        if type(self.automatic_activation_allowed) is not bool:
            raise CommunicationError("automatic_activation_allowed must be boolean")

    @property
    def session_key(self) -> str:
        # Conservative within a workspace: different aliases/handles/generations
        # for the same provider-native session must share the same slot.
        return hashlib.sha256(canonical([self.provider, self.native_session_id]).encode()).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Message:
    workspace_id: str
    id: str
    sender: str
    target: str
    thread_id: str
    body: str
    refs: tuple[str, ...]
    created_at: str
    expires_at: str | None
    reply_to: str | None = None
    expectation: str = "none"
    origin: str = "agent"

    def __post_init__(self) -> None:
        for name in ("workspace_id", "id", "sender", "target", "thread_id", "body"):
            text(getattr(self, name), name)
        ReplyExpectation(self.expectation)
        if self.origin != "agent":
            raise AccessDenied("agent entry cannot create user authority")

    def to_dict(self) -> dict:
        return json.loads(canonical(asdict(self)))


@dataclass(frozen=True, slots=True)
class Claim:
    workspace_id: str
    message_id: str
    target: str
    session_key: str
    attempt_id: str
    fence: int
    owner: str

    def __post_init__(self) -> None:
        for name in ("workspace_id", "message_id", "target", "session_key", "attempt_id", "owner"):
            text(getattr(self, name), name)
        if type(self.fence) is not int or self.fence <= 0:
            raise CommunicationError("fence must be a positive integer")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProviderEvidence:
    """Internal delivery-port input, never accepted as agent-authored tool data.

    The adapter must validate native lifecycle/continuity before constructing it.
    C1-A verifies correlation and policy, not real provider authenticity.
    """
    provider: str
    native_session_id: str
    outcome: str
    evidence_ref: str
    accepted: bool = False
    stopped: bool = False
    final: str | None = None
    trusted_final: bool = False
    generation: str | None = None
    requires_user_review: bool = False
    provider_command_started: bool = False

    def __post_init__(self) -> None:
        EvidenceOutcome(self.outcome)
        text(self.provider, "provider")
        text(self.native_session_id, "native_session_id")
        text(self.evidence_ref, "evidence_ref")
        if any(type(v) is not bool for v in (self.accepted, self.stopped, self.trusted_final,
                                              self.requires_user_review, self.provider_command_started)):
            raise CommunicationError("evidence flags must be boolean")
        if self.final is not None:
            text(self.final, "final")
            if len(self.final) > 16000:
                raise CommunicationError("final exceeds communication body limit")
        if self.outcome == "running" and self.stopped:
            raise CommunicationError("running contradicts stopped evidence")
        if self.outcome in {"finished", "failed", "not_delivered"} and not self.stopped:
            raise CommunicationError("terminal execution needs stopped evidence")
        if self.outcome == "not_delivered" and (self.accepted or self.final is not None):
            raise CommunicationError("not_delivered contradicts acceptance/final")
        if self.final is not None and (
            not self.trusted_final or not self.accepted
            or self.outcome not in {"finished", "failed"}
            or (self.outcome == "failed" and not self.requires_user_review)
        ):
            raise CommunicationError("final capture requires trusted accepted terminal evidence; failure needs review")


class ThreadVisibility(StrEnum):
    # Same wire vocabulary as the legacy thread contract.
    PARTICIPANTS_ONLY = "participants_only"
    WORKSPACE_READABLE = "workspace_readable"
