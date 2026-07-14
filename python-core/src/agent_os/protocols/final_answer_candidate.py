from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4


def utc_now() -> datetime:
    """Return an aware UTC timestamp for candidate lifecycle events."""

    return datetime.now(timezone.utc)


class FinalAnswerCandidateStatus(StrEnum):
    """Lifecycle states for a final-answer candidate on the shared blackboard."""

    DRAFT = "draft"
    FROZEN = "frozen"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class FinalAnswerCandidate:
    """Canonical evaluation object for checkpoint, heartbeat, and final review.

    A final-answer candidate is derived from discussion outputs but is not the
    same thing as a discussion message. It exists so checkpoint, freeze,
    self-check, voting, dispatcher, and reporting flows can operate on one
    explicit, auditable object.
    """

    candidate_id: str
    workflow_id: str
    source_round: int
    source_agent_id: str | None = None
    synthesis_source: str | None = None
    summary_text: str = ""
    structured_content: Mapping[str, object] | None = None
    payload: Mapping[str, object] | None = None
    status: FinalAnswerCandidateStatus = FinalAnswerCandidateStatus.DRAFT
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def is_canonical_evaluation_object(self) -> bool:
        """Whether this object is the canonical checkpoint evaluation surface."""

        return True

    @classmethod
    def create(
        cls,
        *,
        workflow_id: str,
        source_round: int,
        source_agent_id: str | None = None,
        synthesis_source: str | None = None,
        summary_text: str,
        structured_content: Mapping[str, object] | None = None,
        payload: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
        candidate_id: str | None = None,
    ) -> FinalAnswerCandidate:
        """Create a new draft evaluation object from discussion-round output."""

        timestamp = utc_now()
        return cls(
            candidate_id=candidate_id or str(uuid4()),
            workflow_id=workflow_id,
            source_round=source_round,
            source_agent_id=source_agent_id,
            synthesis_source=synthesis_source,
            summary_text=summary_text,
            structured_content=structured_content,
            payload=payload,
            status=FinalAnswerCandidateStatus.DRAFT,
            created_at=timestamp,
            updated_at=timestamp,
            metadata=dict(metadata or {}),
        )

    def with_status(
        self,
        status: FinalAnswerCandidateStatus,
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> FinalAnswerCandidate:
        """Return a copy of the candidate with an updated lifecycle status."""

        merged_metadata = dict(self.metadata)
        if metadata is not None:
            merged_metadata.update(metadata)

        return replace(
            self,
            status=status,
            updated_at=utc_now(),
            metadata=merged_metadata,
        )

    def supersede(
        self,
        *,
        replacement_candidate_id: str | None = None,
    ) -> FinalAnswerCandidate:
        """Mark the candidate as superseded while preserving audit history."""

        metadata: dict[str, object] = {}
        if replacement_candidate_id is not None:
            metadata["replacement_candidate_id"] = replacement_candidate_id
        return self.with_status(FinalAnswerCandidateStatus.SUPERSEDED, metadata=metadata)

    def freeze(self) -> FinalAnswerCandidate:
        """Freeze the candidate as the normative heartbeat/checkpoint input."""

        return self.with_status(FinalAnswerCandidateStatus.FROZEN)

    def accept(self) -> FinalAnswerCandidate:
        """Mark the candidate as accepted."""

        return self.with_status(FinalAnswerCandidateStatus.ACCEPTED)

    def reject(self) -> FinalAnswerCandidate:
        """Mark the candidate as rejected."""

        return self.with_status(FinalAnswerCandidateStatus.REJECTED)
