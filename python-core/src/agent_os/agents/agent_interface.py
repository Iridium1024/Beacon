from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_os.orchestrator.convergence import (
        HeartbeatAgentJudgment,
        HeartbeatCheckpointInput,
        HeartbeatEvidenceBundle,
    )
    from agent_os.protocols.communication_protocol import CommunicationMessage
    from agent_os.protocols.shared_context import SharedContext


@dataclass(frozen=True, slots=True)
class Perception:
    """Normalized view of shared context and the latest observed state update."""

    shared_context: SharedContext
    update: CommunicationMessage | None = None
    context: Mapping[str, object] = field(default_factory=dict)

    @property
    def message(self) -> CommunicationMessage | None:
        """Backward-compatible alias for the last observed shared-context update."""

        return self.update


@dataclass(frozen=True, slots=True)
class Thought:
    """Internal reasoning artifact exposed only as an interface contract."""

    intent: str
    reasoning_summary: str
    context: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentAction:
    """Externalized action emitted by an agent."""

    action_type: str
    payload: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentSummary:
    """Compressed summary emitted after one or more agent interactions."""

    summary: str
    references: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


class Agent(ABC):
    """Abstract contract for a decoupled agent that reads and writes shared context.

    Agents no longer assume direct message delivery as their primary interaction model.
    They observe shared-context updates and contribute new state back into the
    blackboard through surrounding application infrastructure.
    """

    @abstractmethod
    async def perceive(
        self,
        shared_context: SharedContext,
        update: CommunicationMessage | None = None,
    ) -> Perception:
        ...

    @abstractmethod
    async def think(self, perception: Perception) -> Thought:
        ...

    @abstractmethod
    async def act(self, thought: Thought) -> AgentAction:
        ...

    @abstractmethod
    async def summarize(self, shared_context: SharedContext) -> AgentSummary:
        ...

    @property
    @abstractmethod
    def supports_role_specific_self_check(self) -> bool:
        """Whether this agent should participate in formal heartbeat statistics."""

        ...

    @abstractmethod
    async def self_check(
        self,
        checkpoint_input: HeartbeatCheckpointInput,
        evidence_bundle: HeartbeatEvidenceBundle,
    ) -> HeartbeatAgentJudgment | Mapping[str, object]:
        """Run a non-discussion heartbeat self-check against a frozen candidate.

        This seam is the formal heartbeat entry point for agent-specific review.
        Implementations must evaluate the frozen candidate through the provided
        structured evidence bundle only. They must not propose new solution
        content or rewrite the candidate during heartbeat.
        """

        ...
