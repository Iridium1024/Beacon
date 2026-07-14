from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import re

from agent_os.orchestrator.convergence import HeartbeatCheckpointInput
from agent_os.protocols.final_answer_candidate import FinalAnswerCandidate


@dataclass(frozen=True, slots=True)
class HeartbeatEvidenceExtractionInput:
    """Normalized raw inputs shared by heartbeat evidence extractors."""

    checkpoint_input: HeartbeatCheckpointInput
    candidate: FinalAnswerCandidate
    candidate_text: str
    candidate_terms: tuple[str, ...]
    candidate_keys: tuple[str, ...]
    goal_terms: tuple[str, ...]
    structured_content_present: bool
    payload_present: bool
    metadata_present: bool
    relevant_context_refs: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


def build_heartbeat_evidence_extraction_input(
    checkpoint_input: HeartbeatCheckpointInput,
    candidate: FinalAnswerCandidate,
) -> HeartbeatEvidenceExtractionInput:
    """Create the shared normalized extraction input from a frozen candidate."""

    candidate_text = _flatten_candidate_text(candidate)
    candidate_terms = tuple(sorted(_normalized_terms(candidate_text)))
    candidate_keys = tuple(sorted(_candidate_keys(candidate)))
    goal_terms = tuple(
        sorted(
            term
            for term in _normalized_terms(checkpoint_input.original_goal)
            if len(term) > 3 and term not in {"with", "from", "into", "that", "this", "only"}
        )
    )

    return HeartbeatEvidenceExtractionInput(
        checkpoint_input=checkpoint_input,
        candidate=candidate,
        candidate_text=candidate_text,
        candidate_terms=candidate_terms,
        candidate_keys=candidate_keys,
        goal_terms=goal_terms,
        structured_content_present=bool(candidate.structured_content),
        payload_present=bool(candidate.payload),
        metadata_present=bool(candidate.metadata),
        relevant_context_refs=checkpoint_input.relevant_context_refs,
        metadata={"candidate_status": candidate.status.value},
    )


class HeartbeatEvidenceExtractor(ABC):
    """Minimal extractor contract for one evidence signal family.

    Extractors only derive structured evidence signals. They do not approve or
    reject candidates and they do not mutate checkpoint state.
    """

    signal_name: str

    @abstractmethod
    def extract(self, extraction_input: HeartbeatEvidenceExtractionInput) -> Mapping[str, object]:
        """Return one signal mapping for the evidence bundle."""

    def _source_anchor(
        self,
        extraction_input: HeartbeatEvidenceExtractionInput,
        *,
        source_fields: Sequence[str],
        matched_refs: Sequence[str] = (),
    ) -> dict[str, object]:
        """Attach lightweight traceability for one extracted signal family."""

        return {
            "source_fields": tuple(source_fields),
            "matched_refs": tuple(matched_refs),
            "derived_from_summary": bool(extraction_input.checkpoint_input.frozen_candidate_summary.strip()),
            "derived_from_structured_content": extraction_input.structured_content_present,
            "derived_from_payload": extraction_input.payload_present,
        }

    def _matched_keywords(
        self,
        extraction_input: HeartbeatEvidenceExtractionInput,
        keywords: Sequence[str],
    ) -> tuple[str, ...]:
        matches = [
            keyword
            for keyword in keywords
            if keyword in extraction_input.candidate_text or keyword in extraction_input.candidate_keys
        ]
        return tuple(sorted(matches))


@dataclass(frozen=True, slots=True)
class CoverageEvidenceExtractor(HeartbeatEvidenceExtractor):
    """Extract signals related to goal coverage and plan closure."""

    signal_name: str = "coverage_signals"

    def extract(self, extraction_input: HeartbeatEvidenceExtractionInput) -> Mapping[str, object]:
        plan_matches = self._matched_keywords(
            extraction_input,
            ("plan", "steps", "step", "phases", "phase", "tasks", "task"),
        )
        matched_goal_terms = tuple(
            sorted(term for term in extraction_input.goal_terms if term in extraction_input.candidate_terms)
        )
        return {
            "goal_terms": extraction_input.goal_terms,
            "matched_goal_terms": matched_goal_terms,
            "has_goal_overlap": bool(matched_goal_terms),
            "has_plan_structure": bool(plan_matches),
            "matched_plan_terms": plan_matches,
            **self._source_anchor(
                extraction_input,
                source_fields=("original_goal", "candidate_summary", "structured_content", "payload"),
            ),
        }


@dataclass(frozen=True, slots=True)
class ConstraintEvidenceExtractor(HeartbeatEvidenceExtractor):
    """Extract signals related to constraints and required deliverables."""

    signal_name: str = "constraint_signals"

    def extract(self, extraction_input: HeartbeatEvidenceExtractionInput) -> Mapping[str, object]:
        matches = self._matched_keywords(
            extraction_input,
            ("constraint", "constraints", "requirement", "requirements", "deliverable"),
        )
        return {
            "matched_terms": matches,
            "has_constraints": bool(matches),
            "candidate_keys": extraction_input.candidate_keys,
            **self._source_anchor(
                extraction_input,
                source_fields=("candidate_summary", "structured_content", "payload"),
            ),
        }


@dataclass(frozen=True, slots=True)
class ImplementationEvidenceExtractor(HeartbeatEvidenceExtractor):
    """Extract signals related to implementation grounding and interface closure."""

    signal_name: str = "implementation_signals"

    def extract(self, extraction_input: HeartbeatEvidenceExtractionInput) -> Mapping[str, object]:
        implementation_matches = self._matched_keywords(
            extraction_input,
            ("implementation", "execute", "execution", "action", "actions", "files", "changes"),
        )
        interface_matches = self._matched_keywords(
            extraction_input,
            ("interface", "interfaces", "dependency", "dependencies", "api", "endpoint"),
        )
        return {
            "matched_terms": implementation_matches,
            "interface_terms": interface_matches,
            "has_execution_path": bool(implementation_matches),
            "has_interface_closure": bool(interface_matches),
            **self._source_anchor(
                extraction_input,
                source_fields=("candidate_summary", "structured_content", "payload"),
            ),
        }


@dataclass(frozen=True, slots=True)
class RiskEvidenceExtractor(HeartbeatEvidenceExtractor):
    """Extract signals related to implementation gaps, risk, and clarity concerns."""

    signal_name: str = "risk_signals"

    def extract(self, extraction_input: HeartbeatEvidenceExtractionInput) -> Mapping[str, object]:
        gap_matches = self._matched_keywords(
            extraction_input,
            ("todo", "tbd", "pending", "later", "missing interface", "unknown dependency"),
        )
        risk_matches = self._matched_keywords(
            extraction_input,
            ("risk", "bug", "incorrect", "failure", "conflict"),
        )
        clarity_matches = self._matched_keywords(
            extraction_input,
            ("unclear", "ambiguous", "unspecified", "not explained"),
        )
        return {
            "gap_terms": gap_matches,
            "risk_terms": risk_matches,
            "clarity_terms": clarity_matches,
            "has_gap_marker": bool(gap_matches),
            "has_risk_marker": bool(risk_matches),
            "has_clarity_marker": bool(clarity_matches),
            **self._source_anchor(
                extraction_input,
                source_fields=("candidate_summary", "structured_content", "payload"),
            ),
        }


@dataclass(frozen=True, slots=True)
class ValidationEvidenceExtractor(HeartbeatEvidenceExtractor):
    """Extract signals related to evidence support and validation trace."""

    signal_name: str = "evidence_signals"

    def extract(self, extraction_input: HeartbeatEvidenceExtractionInput) -> Mapping[str, object]:
        evidence_gap_matches = self._matched_keywords(
            extraction_input,
            ("missing evidence", "unsupported", "unverified", "evidence gap"),
        )
        validation_matches = self._matched_keywords(
            extraction_input,
            ("validated", "validation", "checks", "verification", "tests", "evidence", "consistency"),
        )
        return {
            "matched_terms": validation_matches,
            "gap_terms": evidence_gap_matches,
            "has_validation_signal": bool(validation_matches),
            "has_evidence_gap": bool(evidence_gap_matches),
            "context_ref_count": len(extraction_input.relevant_context_refs),
            **self._source_anchor(
                extraction_input,
                source_fields=(
                    "candidate_summary",
                    "structured_content",
                    "payload",
                    "relevant_context_refs",
                ),
                matched_refs=extraction_input.relevant_context_refs,
            ),
        }


DEFAULT_HEARTBEAT_EVIDENCE_EXTRACTORS: tuple[HeartbeatEvidenceExtractor, ...] = (
    CoverageEvidenceExtractor(),
    ConstraintEvidenceExtractor(),
    ImplementationEvidenceExtractor(),
    RiskEvidenceExtractor(),
    ValidationEvidenceExtractor(),
)


def _flatten_candidate_text(candidate: FinalAnswerCandidate) -> str:
    fragments: list[str] = [candidate.summary_text]
    for container in (candidate.structured_content, candidate.payload, candidate.metadata):
        if not container:
            continue
        fragments.extend(str(key) for key in container.keys())
        for value in container.values():
            if isinstance(value, str):
                fragments.append(value)
            elif isinstance(value, (int, float, bool)):
                fragments.append(str(value))
            elif isinstance(value, (list, tuple, set)):
                fragments.extend(str(item) for item in value)
    return " ".join(fragment for fragment in fragments if fragment).lower()


def _candidate_keys(candidate: FinalAnswerCandidate) -> set[str]:
    keys: set[str] = set()
    for container in (candidate.structured_content, candidate.payload, candidate.metadata):
        if not container:
            continue
        keys.update(str(key).strip().lower() for key in container.keys())
    return keys


def _normalized_terms(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", text.lower()))
