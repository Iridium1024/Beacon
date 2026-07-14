from __future__ import annotations

from dataclasses import dataclass

from agent_os.agents.base_agent import BaseAgent
from agent_os.orchestrator.convergence import (
    HeartbeatAgentJudgment,
    HeartbeatCheckpointInput,
    HeartbeatEvidenceBundle,
    RejectionDeficiencyCategory,
)


@dataclass(slots=True)
class ReviewerAgent(BaseAgent):
    """Role-specialized agent for validation and critique."""

    @property
    def supports_role_specific_self_check(self) -> bool:
        return True

    @property
    def role_name(self) -> str:
        return "reviewer"

    def default_intent(self) -> str:
        return "review"

    def default_action_type(self) -> str:
        return "review.perform"

    async def self_check(
        self,
        checkpoint_input: HeartbeatCheckpointInput,
        evidence_bundle: HeartbeatEvidenceBundle,
    ) -> HeartbeatAgentJudgment:
        evidence_signals = evidence_bundle.evidence_signals
        risk_signals = evidence_bundle.risk_signals
        if self._signal_flag(evidence_signals, "has_evidence_gap"):
            used_signal_keys = ("evidence.has_evidence_gap",)
            return self._build_reject_judgment(
                checkpoint_input,
                evidence_bundle,
                rationale_text="Evidence support is not explicit.",
                deficiency_category=RejectionDeficiencyCategory.EVIDENCE_GAP,
                used_signal_keys=used_signal_keys,
                source_anchors=self._build_signal_source_anchors(
                    evidence_bundle,
                    used_signal_keys,
                ),
            )
        if self._signal_flag(risk_signals, "has_risk_marker"):
            used_signal_keys = ("risk.has_risk_marker",)
            return self._build_reject_judgment(
                checkpoint_input,
                evidence_bundle,
                rationale_text="Unresolved correctness risk is explicit.",
                deficiency_category=RejectionDeficiencyCategory.CORRECTNESS_RISK,
                used_signal_keys=used_signal_keys,
                source_anchors=self._build_signal_source_anchors(
                    evidence_bundle,
                    used_signal_keys,
                ),
            )
        if self._signal_flag(risk_signals, "has_clarity_marker"):
            used_signal_keys = ("risk.has_clarity_marker",)
            return self._build_reject_judgment(
                checkpoint_input,
                evidence_bundle,
                rationale_text="A material clarity gap remains.",
                deficiency_category=RejectionDeficiencyCategory.CLARITY_GAP,
                used_signal_keys=used_signal_keys,
                source_anchors=self._build_signal_source_anchors(
                    evidence_bundle,
                    used_signal_keys,
                ),
            )
        has_validation_signal = self._signal_flag(evidence_signals, "has_validation_signal")
        if not has_validation_signal:
            used_signal_keys = ("evidence.has_validation_signal",)
            return self._build_reject_judgment(
                checkpoint_input,
                evidence_bundle,
                rationale_text="Validation evidence is not explicit.",
                deficiency_category=RejectionDeficiencyCategory.EVIDENCE_GAP,
                used_signal_keys=used_signal_keys,
                source_anchors=self._build_signal_source_anchors(
                    evidence_bundle,
                    used_signal_keys,
                ),
            )
        used_signal_keys = (
            "risk.has_risk_marker",
            "risk.has_clarity_marker",
            "evidence.has_validation_signal",
        )
        return self._build_approval_judgment(
            checkpoint_input,
            evidence_bundle,
            "No unresolved risk or evidence gap is explicit.",
            blocker=False,
            used_signal_keys=used_signal_keys,
            source_anchors=self._build_signal_source_anchors(
                evidence_bundle,
                used_signal_keys,
            ),
        )
