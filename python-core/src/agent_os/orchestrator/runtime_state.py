from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from agent_os.orchestrator.convergence import (
    ConvergenceStatus,
    CoordinationPhase,
    HeartbeatEvidenceBundle,
    HeartbeatCheckpointInput,
    ParticipantStateDefinition,
    ParticipantStatus,
)
from agent_os.orchestrator.evidence_extractors import (
    DEFAULT_HEARTBEAT_EVIDENCE_EXTRACTORS,
    build_heartbeat_evidence_extraction_input,
)
from agent_os.protocols.final_answer_candidate import (
    FinalAnswerCandidate,
    FinalAnswerCandidateStatus,
)
from agent_os.protocols.shared_context import SharedContext


@dataclass(slots=True)
class TokenUsageLedger:
    """Mutable token accounting used by the execution skeleton."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def register_mock_usage(self, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        """Track placeholder token counts until real provider accounting exists."""

        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_tokens = self.prompt_tokens + self.completion_tokens


@dataclass(slots=True)
class ExecutionState:
    """Mutable orchestration state around a blackboard of explicit semantic objects.

    The shared context stores canonical discussion messages and explicit
    final-answer candidates. Auxiliary vector memory remains attached to the
    shared context but is not treated as the direct control surface for phase
    transitions or checkpoint evaluation.
    """

    workflow_id: str
    goal: str
    shared_context: SharedContext = field(default_factory=SharedContext)
    iteration_count: int = 0
    token_usage: TokenUsageLedger = field(default_factory=TokenUsageLedger)
    current_step_id: str | None = None
    completed_steps: list[str] = field(default_factory=list)
    current_phase: CoordinationPhase = CoordinationPhase.DISCUSSION_ROUND
    terminal_status: ConvergenceStatus | None = None
    last_checkpoint_iteration: int | None = None
    participant_agent_ids: tuple[str, ...] = ()
    participant_states: dict[str, ParticipantStateDefinition] = field(default_factory=dict)
    last_checkpoint_id: str | None = None

    def __post_init__(self) -> None:
        """Mirror execution-phase metadata into the shared blackboard."""

        if not self.participant_states and self.participant_agent_ids:
            self.participant_states = {
                agent_id: ParticipantStateDefinition(
                    agent_id=agent_id,
                    status=ParticipantStatus.ACTIVE,
                )
                for agent_id in self.participant_agent_ids
            }
        elif self.participant_states and not self.participant_agent_ids:
            self.participant_agent_ids = tuple(self.participant_states.keys())
        elif self.participant_states and self.participant_agent_ids:
            merged_states = dict(self.participant_states)
            for agent_id in self.participant_agent_ids:
                merged_states.setdefault(
                    agent_id,
                    ParticipantStateDefinition(
                        agent_id=agent_id,
                        status=ParticipantStatus.ACTIVE,
                    ),
                )
            self.participant_states = merged_states
            self.participant_agent_ids = tuple(merged_states.keys())

        self.shared_context.values["workflow_id"] = self.workflow_id
        self.shared_context.values["current_phase"] = self.current_phase.value
        self.shared_context.values["participant_agent_ids"] = self.participant_agent_ids
        self.shared_context.values["participant_statuses"] = {
            agent_id: state.status.value for agent_id, state in self.participant_states.items()
        }
        if self.terminal_status is not None:
            self.shared_context.values["terminal_status"] = self.terminal_status.value

    def get_current_candidate(self) -> FinalAnswerCandidate | None:
        """Return the current canonical checkpoint-evaluation object."""

        return self.shared_context.get_current_candidate()

    @property
    def current_final_answer_candidate(self) -> FinalAnswerCandidate | None:
        """Backward-friendly property access to the current candidate."""

        return self.get_current_candidate()

    @property
    def is_terminal(self) -> bool:
        """Whether the orchestration state has reached a terminal outcome."""

        return self.terminal_status is not None

    def publish_candidate_from_discussion(
        self,
        *,
        summary_text: str,
        source_agent_id: str | None = None,
        synthesis_source: str | None = None,
        source_round: int | None = None,
        structured_content: Mapping[str, object] | None = None,
        payload: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> FinalAnswerCandidate:
        """Create a new draft candidate from a discussion-round update.

        Candidate publication is explicitly guarded to the proposal-bearing
        `discussion_round` phase. Heartbeat checkpoints and terminal handling
        must treat the current candidate as read-only.
        """

        if self.current_phase != CoordinationPhase.DISCUSSION_ROUND:
            raise RuntimeError(
                "Final-answer candidates may only be updated during discussion_round. "
                "heartbeat_checkpoint is read-only for candidate updates."
            )

        resolved_source_round = source_round if source_round is not None else self.iteration_count + 1
        return self.shared_context.update_current_candidate(
            workflow_id=self.workflow_id,
            source_round=resolved_source_round,
            source_agent_id=source_agent_id,
            synthesis_source=synthesis_source,
            summary_text=summary_text,
            structured_content=structured_content,
            payload=payload,
            metadata=metadata,
        )

    def freeze_current_candidate(self) -> FinalAnswerCandidate | None:
        """Freeze the current canonical evaluation object for heartbeat."""

        return self.shared_context.freeze_current_candidate()

    def enter_heartbeat_checkpoint(self) -> FinalAnswerCandidate | None:
        """Enter heartbeat and freeze the explicit final-answer candidate.

        Heartbeat is non-proposal-bearing. Once frozen, the candidate becomes
        the normative checkpoint input and later discussion must publish a new
        candidate rather than mutating the frozen one in place.
        """

        self.current_phase = CoordinationPhase.HEARTBEAT_CHECKPOINT
        self.last_checkpoint_iteration = self.iteration_count
        self.shared_context.values["current_phase"] = self.current_phase.value
        self.shared_context.values["last_checkpoint_iteration"] = self.last_checkpoint_iteration

        frozen_candidate = self.freeze_current_candidate()
        if frozen_candidate is not None:
            self.shared_context.values["frozen_final_answer_candidate_id"] = (
                frozen_candidate.candidate_id
            )
        return frozen_candidate

    def create_heartbeat_checkpoint_input(
        self,
        *,
        trigger_ids: Sequence[str] = (),
        relevant_context_limit: int = 5,
        metadata: Mapping[str, object] | None = None,
    ) -> HeartbeatCheckpointInput:
        """Build the canonical heartbeat input from the frozen current candidate."""

        if self.current_phase != CoordinationPhase.HEARTBEAT_CHECKPOINT:
            raise RuntimeError(
                "Heartbeat checkpoint input may only be created during heartbeat_checkpoint."
            )

        candidate = self.get_current_candidate()
        if candidate is None:
            raise RuntimeError("Cannot create heartbeat checkpoint input without a current candidate.")
        if candidate.status != FinalAnswerCandidateStatus.FROZEN:
            raise RuntimeError(
                "Heartbeat checkpoint input requires the current final-answer candidate to be frozen."
            )

        relevant_context_refs = tuple(
            message.id
            for message in self.shared_context.query_recent_messages(limit=relevant_context_limit)
        )
        checkpoint_input = HeartbeatCheckpointInput.from_candidate(
            workflow_id=self.workflow_id,
            original_goal=self.goal,
            candidate=candidate,
            relevant_context_refs=relevant_context_refs,
            metadata={
                "trigger_ids": tuple(trigger_ids),
                **dict(metadata or {}),
            },
        )
        self.last_checkpoint_id = checkpoint_input.checkpoint_id
        self.shared_context.values["last_checkpoint_id"] = checkpoint_input.checkpoint_id
        self.shared_context.values["last_checkpoint_candidate_id"] = checkpoint_input.frozen_candidate_id
        return checkpoint_input

    def create_heartbeat_evidence_bundle(
        self,
        checkpoint_input: HeartbeatCheckpointInput,
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> HeartbeatEvidenceBundle:
        """Build the canonical structured evidence bundle through the extractor pipeline."""

        if self.current_phase != CoordinationPhase.HEARTBEAT_CHECKPOINT:
            raise RuntimeError(
                "Heartbeat evidence bundles may only be created during heartbeat_checkpoint."
            )

        candidate = self.get_current_candidate()
        if candidate is None:
            raise RuntimeError("Cannot create heartbeat evidence without a current candidate.")
        if candidate.status != FinalAnswerCandidateStatus.FROZEN:
            raise RuntimeError(
                "Heartbeat evidence requires the current final-answer candidate to be frozen."
            )
        if candidate.candidate_id != checkpoint_input.frozen_candidate_id:
            raise RuntimeError(
                "Heartbeat evidence must be built from the active frozen candidate only."
            )

        extraction_input = build_heartbeat_evidence_extraction_input(checkpoint_input, candidate)
        extracted_signals = {
            extractor.signal_name: dict(extractor.extract(extraction_input))
            for extractor in DEFAULT_HEARTBEAT_EVIDENCE_EXTRACTORS
        }

        evidence_bundle = HeartbeatEvidenceBundle.create(
            checkpoint_id=checkpoint_input.checkpoint_id,
            candidate_id=checkpoint_input.frozen_candidate_id,
            original_goal=checkpoint_input.original_goal,
            candidate_summary=checkpoint_input.frozen_candidate_summary,
            structured_content_summary=self._mapping_summary(candidate.structured_content),
            payload_summary=self._mapping_summary(candidate.payload),
            source_round=checkpoint_input.source_round,
            relevant_context_refs=checkpoint_input.relevant_context_refs,
            constraint_signals=extracted_signals["constraint_signals"],
            coverage_signals=extracted_signals["coverage_signals"],
            implementation_signals=extracted_signals["implementation_signals"],
            risk_signals=extracted_signals["risk_signals"],
            evidence_signals=extracted_signals["evidence_signals"],
            metadata={
                "builder": "ExecutionState.create_heartbeat_evidence_bundle",
                "extractors": tuple(
                    extractor.__class__.__name__ for extractor in DEFAULT_HEARTBEAT_EVIDENCE_EXTRACTORS
                ),
                "candidate_status": candidate.status.value,
                **dict(metadata or {}),
            },
        )
        self._remember_heartbeat_evidence_bundle(evidence_bundle)
        return evidence_bundle

    def resolve_heartbeat_evidence_bundle(
        self,
        checkpoint_input: HeartbeatCheckpointInput,
        *,
        evidence_bundle: HeartbeatEvidenceBundle | None = None,
    ) -> HeartbeatEvidenceBundle:
        """Return the canonical evidence bundle for one checkpoint evaluation."""

        if evidence_bundle is not None:
            self._validate_heartbeat_evidence_bundle(checkpoint_input, evidence_bundle)
            self._remember_heartbeat_evidence_bundle(evidence_bundle)
            return evidence_bundle

        cached_bundle = self._cached_heartbeat_evidence_bundle(checkpoint_input)
        if cached_bundle is not None:
            return cached_bundle

        return self.create_heartbeat_evidence_bundle(checkpoint_input)

    def get_participant_state(self, agent_id: str) -> ParticipantStateDefinition | None:
        """Return the centralized participation state for one agent."""

        return self.participant_states.get(agent_id)

    def set_participant_status(
        self,
        agent_id: str,
        status: ParticipantStatus,
        *,
        sleep_reply: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> ParticipantStateDefinition:
        """Update one agent's participation status in the shared execution state."""

        current = self.participant_states.get(agent_id)
        next_state = ParticipantStateDefinition(
            agent_id=agent_id,
            status=status,
            recorder_role=current.recorder_role if current is not None else None,
            sleep_reply=sleep_reply if sleep_reply is not None else (current.sleep_reply if current else None),
            metadata={
                **dict(current.metadata if current is not None else {}),
                **dict(metadata or {}),
            },
        )
        self.participant_states[agent_id] = next_state
        if agent_id not in self.participant_agent_ids:
            self.participant_agent_ids = (*self.participant_agent_ids, agent_id)
            self.shared_context.values["participant_agent_ids"] = self.participant_agent_ids
        self.shared_context.values["participant_statuses"] = {
            participant_id: participant_state.status.value
            for participant_id, participant_state in self.participant_states.items()
        }
        return next_state

    def eligible_heartbeat_participant_ids(self) -> tuple[str, ...]:
        """Return heartbeat participants after centralized non-sleeping filtering."""

        if not self.participant_states:
            return self.participant_agent_ids
        return tuple(
            agent_id
            for agent_id in self.participant_agent_ids
            if self.participant_states.get(agent_id, ParticipantStateDefinition(agent_id=agent_id)).status
            == ParticipantStatus.ACTIVE
        )

    def resume_discussion_round(self) -> None:
        """Return control to the proposal-bearing discussion phase."""

        self.current_phase = CoordinationPhase.DISCUSSION_ROUND
        self.shared_context.values["current_phase"] = self.current_phase.value

    def mark_terminal(
        self,
        status: ConvergenceStatus,
        *,
        reason: str | None = None,
    ) -> None:
        """Move the execution state into terminal handling with a fixed outcome."""

        self.current_phase = CoordinationPhase.TERMINATION_EXTENSION_HANDLING
        self.terminal_status = status
        self.shared_context.values["current_phase"] = self.current_phase.value
        self.shared_context.values["terminal_status"] = status.value
        if reason is not None:
            self.shared_context.values["terminal_reason"] = reason

    def _mapping_summary(
        self,
        mapping: Mapping[str, object] | None,
    ) -> Mapping[str, object] | None:
        """Build a shallow summary for optional candidate mappings."""

        if mapping is None:
            return None
        return {
            "keys": tuple(sorted(str(key) for key in mapping.keys())),
            "item_count": len(mapping),
        }

    def _remember_heartbeat_evidence_bundle(
        self,
        evidence_bundle: HeartbeatEvidenceBundle,
    ) -> None:
        self.shared_context.values["last_heartbeat_evidence_bundle"] = evidence_bundle
        self.shared_context.values["last_heartbeat_evidence_bundle_id"] = (
            evidence_bundle.evidence_bundle_id
        )

    def _cached_heartbeat_evidence_bundle(
        self,
        checkpoint_input: HeartbeatCheckpointInput,
    ) -> HeartbeatEvidenceBundle | None:
        value = self.shared_context.values.get("last_heartbeat_evidence_bundle")
        if not isinstance(value, HeartbeatEvidenceBundle):
            return None
        if value.checkpoint_id != checkpoint_input.checkpoint_id:
            return None
        if value.candidate_id != checkpoint_input.frozen_candidate_id:
            return None
        return value

    def _validate_heartbeat_evidence_bundle(
        self,
        checkpoint_input: HeartbeatCheckpointInput,
        evidence_bundle: HeartbeatEvidenceBundle,
    ) -> None:
        if evidence_bundle.checkpoint_id != checkpoint_input.checkpoint_id:
            raise RuntimeError(
                "Heartbeat evidence bundle must match the active checkpoint input."
            )
        if evidence_bundle.candidate_id != checkpoint_input.frozen_candidate_id:
            raise RuntimeError(
                "Heartbeat evidence bundle must match the active frozen candidate."
            )
