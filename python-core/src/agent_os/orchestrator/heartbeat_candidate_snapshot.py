from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from agent_os.orchestrator.convergence import (
    HeartbeatAggregateArtifact,
    HeartbeatAggregateResult,
    HeartbeatCheckpointInput,
)


@dataclass(frozen=True, slots=True)
class HeartbeatCandidateSnapshot:
    """Minimal, stable candidate-consumption view derived from one checkpoint input."""

    candidate_id: str
    checkpoint_id: str
    summary: str
    source_round: int | None = None
    supporting_context_refs: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        candidate_id = str(self.candidate_id).strip()
        if not candidate_id:
            raise ValueError("Heartbeat candidate snapshot requires candidate_id.")
        checkpoint_id = str(self.checkpoint_id).strip()
        if not checkpoint_id:
            raise ValueError("Heartbeat candidate snapshot requires checkpoint_id.")
        summary = str(self.summary).strip()
        if not summary:
            raise ValueError("Heartbeat candidate snapshot requires a non-empty summary.")
        source_round = None if self.source_round is None else int(self.source_round)
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "checkpoint_id", checkpoint_id)
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "source_round", source_round)
        object.__setattr__(
            self,
            "supporting_context_refs",
            _normalize_context_refs(self.supporting_context_refs),
        )


def build_heartbeat_candidate_snapshot(
    checkpoint_input: HeartbeatCheckpointInput,
) -> HeartbeatCandidateSnapshot:
    """Build the minimal upper-layer candidate snapshot from checkpoint input."""

    if not isinstance(checkpoint_input, HeartbeatCheckpointInput):
        raise TypeError(
            "Heartbeat candidate snapshot requires HeartbeatCheckpointInput."
        )
    snapshot = HeartbeatCandidateSnapshot(
        candidate_id=checkpoint_input.frozen_candidate_id,
        checkpoint_id=checkpoint_input.checkpoint_id,
        summary=checkpoint_input.frozen_candidate_summary,
        source_round=checkpoint_input.source_round,
        supporting_context_refs=checkpoint_input.relevant_context_refs,
        metadata={
            "source_view_kind": "heartbeat_checkpoint_input",
            "supporting_context_ref_count": len(
                _normalize_context_refs(checkpoint_input.relevant_context_refs)
            ),
        },
    )
    assert_heartbeat_candidate_snapshot_matches_checkpoint(
        snapshot=snapshot,
        checkpoint_input=checkpoint_input,
    )
    return snapshot


def validate_heartbeat_candidate_snapshot(snapshot: HeartbeatCandidateSnapshot) -> None:
    """Validate one candidate snapshot reference."""

    if not isinstance(snapshot, HeartbeatCandidateSnapshot):
        raise TypeError(
            "Heartbeat candidate snapshot validation requires HeartbeatCandidateSnapshot."
        )


def assert_matching_heartbeat_candidate_snapshots(
    *snapshots: HeartbeatCandidateSnapshot | None,
    require_all_or_none: bool = False,
) -> HeartbeatCandidateSnapshot | None:
    """Validate and reconcile snapshot references that should agree exactly."""

    present_snapshots = tuple(snapshot for snapshot in snapshots if snapshot is not None)
    if require_all_or_none and present_snapshots and len(present_snapshots) != len(snapshots):
        raise ValueError(
            "Heartbeat candidate snapshot references must either all be present or all be absent."
        )
    if not present_snapshots:
        return None

    canonical_snapshot = present_snapshots[0]
    validate_heartbeat_candidate_snapshot(canonical_snapshot)
    for snapshot in present_snapshots[1:]:
        validate_heartbeat_candidate_snapshot(snapshot)
        if snapshot is not canonical_snapshot:
            raise ValueError(
                "Heartbeat candidate snapshot references must reuse the same object instance."
            )
        if snapshot != canonical_snapshot:
            raise ValueError("Heartbeat candidate snapshot references must agree exactly.")
    return canonical_snapshot


def assert_heartbeat_candidate_snapshot_matches_checkpoint(
    *,
    snapshot: HeartbeatCandidateSnapshot,
    checkpoint_input: HeartbeatCheckpointInput,
) -> None:
    """Assert that one candidate snapshot matches the checkpoint view it was derived from."""

    validate_heartbeat_candidate_snapshot(snapshot)
    if snapshot.candidate_id != checkpoint_input.frozen_candidate_id:
        raise ValueError(
            "Heartbeat candidate snapshot candidate_id must match checkpoint_input."
        )
    if snapshot.checkpoint_id != checkpoint_input.checkpoint_id:
        raise ValueError(
            "Heartbeat candidate snapshot checkpoint_id must match checkpoint_input."
        )
    if snapshot.summary != str(checkpoint_input.frozen_candidate_summary).strip():
        raise ValueError(
            "Heartbeat candidate snapshot summary must match checkpoint_input."
        )
    if snapshot.source_round != checkpoint_input.source_round:
        raise ValueError(
            "Heartbeat candidate snapshot source_round must match checkpoint_input."
        )
    if snapshot.supporting_context_refs != _normalize_context_refs(
        checkpoint_input.relevant_context_refs
    ):
        raise ValueError(
            "Heartbeat candidate snapshot supporting_context_refs must match checkpoint_input."
        )


def assert_heartbeat_candidate_snapshot_matches_aggregate(
    *,
    snapshot: HeartbeatCandidateSnapshot,
    artifact: HeartbeatAggregateArtifact,
    aggregate_result: HeartbeatAggregateResult | None = None,
) -> None:
    """Assert that one candidate snapshot matches the canonical aggregate objects."""

    validate_heartbeat_candidate_snapshot(snapshot)
    attached_snapshot = assert_matching_heartbeat_candidate_snapshots(
        artifact.candidate_snapshot,
        aggregate_result.candidate_snapshot if aggregate_result is not None else None,
        require_all_or_none=aggregate_result is not None,
    )
    if attached_snapshot is not None and attached_snapshot is not snapshot:
        raise ValueError(
            "Heartbeat candidate snapshot must match the attached aggregate candidate_snapshot."
        )
    if snapshot.candidate_id != artifact.candidate_id:
        raise ValueError(
            "Heartbeat candidate snapshot candidate_id must match aggregate artifact."
        )
    if snapshot.checkpoint_id != artifact.checkpoint_id:
        raise ValueError(
            "Heartbeat candidate snapshot checkpoint_id must match aggregate artifact."
        )
    if aggregate_result is not None and snapshot.checkpoint_id != aggregate_result.checkpoint_id:
        raise ValueError(
            "Heartbeat candidate snapshot checkpoint_id must match aggregate result."
        )


def _normalize_context_refs(values: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized_value = str(value).strip()
        if not normalized_value or normalized_value in seen:
            continue
        seen.add(normalized_value)
        normalized.append(normalized_value)
    return tuple(normalized)
