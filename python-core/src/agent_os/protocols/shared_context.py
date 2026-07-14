from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from uuid import uuid4

from agent_os.memory.memory_interface import MemoryQuery
from agent_os.memory.vector_store import InMemoryVectorStore, SimilarityMatch, VectorStore
from agent_os.protocols.final_answer_candidate import FinalAnswerCandidate
from agent_os.protocols.message import CommunicationMessage


@dataclass(frozen=True, slots=True)
class ContextPartition:
    """Optional partition metadata for future segmented shared contexts."""

    context_id: str
    partition_id: str | None = None
    parent_context_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    """Immutable snapshot of canonical shared-context state for checkpointing.

    The snapshot preserves explicit semantic history (`messages`) and explicit
    checkpoint inputs (`final_answer_candidates`). Auxiliary vector memory
    stays attached to the context implementation and is not treated as the
    canonical state body.
    """

    context_id: str
    partition_id: str | None
    messages: tuple[CommunicationMessage, ...]
    final_answer_candidates: tuple[FinalAnswerCandidate, ...] = ()
    current_final_answer_candidate: FinalAnswerCandidate | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class SharedContext:
    """Blackboard-style shared context that agents read from and write to.

    In this model, agents do not exchange direct transmissions by default.
    Instead, they append canonical semantic state updates to a shared context
    and inspect the current blackboard view.

    Canonical state surfaces:
    - `messages`: discussion-round semantic objects
    - `final_answer_candidates`: checkpoint / heartbeat evaluation objects

    Auxiliary state surfaces:
    - `vector_memory`: supplemental retrieval/compression layer
    - `values` / `metadata`: runtime bookkeeping and compatibility storage
    """

    messages: list[CommunicationMessage] = field(default_factory=list)
    vector_memory: VectorStore = field(default_factory=InMemoryVectorStore)
    final_answer_candidates: list[FinalAnswerCandidate] = field(default_factory=list)
    current_final_answer_candidate_id: str | None = None
    values: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    context_id: str = field(default_factory=lambda: str(uuid4()))
    partition_id: str | None = None
    parent_context_id: str | None = None

    def append_message(self, message: CommunicationMessage) -> None:
        """Append a canonical discussion-round semantic update to the blackboard."""

        self.messages.append(message)

    def get_current_candidate(self) -> FinalAnswerCandidate | None:
        """Return the current canonical checkpoint-evaluation object if present."""

        if self.current_final_answer_candidate_id is None:
            return None

        for candidate in reversed(self.final_answer_candidates):
            if candidate.candidate_id == self.current_final_answer_candidate_id:
                return candidate
        return None

    def publish_final_answer_candidate(
        self,
        candidate: FinalAnswerCandidate,
    ) -> FinalAnswerCandidate:
        """Publish a canonical checkpoint-evaluation object to the blackboard.

        The candidate remains distinct from ordinary discussion messages so
        heartbeat, checkpoint, and later evaluation stages can consume an
        explicit object rather than inferring state from message history alone.
        """

        current_candidate = self.get_current_candidate()
        if current_candidate is not None and current_candidate.candidate_id != candidate.candidate_id:
            superseded = current_candidate.supersede(
                replacement_candidate_id=candidate.candidate_id,
            )
            self._replace_candidate(superseded)

        self._replace_candidate(candidate)
        self.current_final_answer_candidate_id = candidate.candidate_id
        self.values["current_final_answer_candidate_id"] = candidate.candidate_id
        self.values["current_final_answer_candidate_status"] = candidate.status
        return candidate

    def update_current_candidate(
        self,
        *,
        workflow_id: str,
        source_round: int,
        source_agent_id: str | None = None,
        synthesis_source: str | None = None,
        summary_text: str,
        structured_content: Mapping[str, object] | None = None,
        payload: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> FinalAnswerCandidate:
        """Create and publish a new draft candidate during a discussion round.

        Discussion messages remain the canonical semantic outputs of the round.
        This helper derives a distinct final-answer candidate object for later
        checkpoint evaluation and freezing.
        """

        candidate = FinalAnswerCandidate.create(
            workflow_id=workflow_id,
            source_round=source_round,
            source_agent_id=source_agent_id,
            synthesis_source=synthesis_source,
            summary_text=summary_text,
            structured_content=structured_content,
            payload=payload,
            metadata=metadata,
        )
        return self.publish_final_answer_candidate(candidate)

    def freeze_current_candidate(self) -> FinalAnswerCandidate | None:
        """Freeze the current candidate as the normative heartbeat input."""

        current_candidate = self.get_current_candidate()
        if current_candidate is None:
            return None

        frozen_candidate = current_candidate.freeze()
        self._replace_candidate(frozen_candidate)
        self.current_final_answer_candidate_id = frozen_candidate.candidate_id
        self.values["current_final_answer_candidate_id"] = frozen_candidate.candidate_id
        self.values["current_final_answer_candidate_status"] = frozen_candidate.status
        return frozen_candidate

    def query_recent_messages(self, limit: int = 10) -> tuple[CommunicationMessage, ...]:
        """Return the most recent canonical discussion-round semantic updates."""

        if limit <= 0:
            return ()
        return tuple(self.messages[-limit:])

    async def retrieve_semantic_context(self, query: MemoryQuery) -> tuple[SimilarityMatch, ...]:
        """Retrieve semantically relevant context via the auxiliary vector store.

        More specialized retrieval patterns remain available through the
        `vector_memory` abstraction itself, including future context-window
        and partition-aware retrieval strategies. These retrieval results assist
        context selection and compression only; they do not replace canonical
        semantic state or direct checkpoint inputs.
        """

        return await self.vector_memory.similarity_search(query)

    def snapshot(self) -> ContextSnapshot:
        """Capture an immutable snapshot of canonical semantic state."""

        current_candidate = self.get_current_candidate()
        return ContextSnapshot(
            context_id=self.context_id,
            partition_id=self.partition_id,
            messages=tuple(self.messages),
            final_answer_candidates=tuple(self.final_answer_candidates),
            current_final_answer_candidate=current_candidate,
            metadata={
                **self.metadata,
                "parent_context_id": self.parent_context_id,
            },
        )

    def partition(self) -> ContextPartition:
        """Expose partition metadata for future partition-aware context management."""

        return ContextPartition(
            context_id=self.context_id,
            partition_id=self.partition_id,
            parent_context_id=self.parent_context_id,
            metadata=dict(self.metadata),
        )

    @property
    def message_history(self) -> list[CommunicationMessage]:
        """Backward-compatible alias for legacy message-history access."""

        return self.messages

    @property
    def current_final_answer_candidate(self) -> FinalAnswerCandidate | None:
        """Typed accessor for the current canonical checkpoint input."""

        return self.get_current_candidate()

    def _replace_candidate(self, candidate: FinalAnswerCandidate) -> None:
        for index, existing in enumerate(self.final_answer_candidates):
            if existing.candidate_id == candidate.candidate_id:
                self.final_answer_candidates[index] = candidate
                return
        self.final_answer_candidates.append(candidate)
