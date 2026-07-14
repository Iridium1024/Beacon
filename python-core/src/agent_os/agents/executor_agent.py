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
class ExecutorAgent(BaseAgent):
    """Role-specialized agent for task execution."""

    @property
    def supports_role_specific_self_check(self) -> bool:
        return True

    @property
    def role_name(self) -> str:
        return "executor"

    def default_intent(self) -> str:
        return "execute"

    def default_action_type(self) -> str:
        return "task.execute"

    async def self_check(
        self,
        checkpoint_input: HeartbeatCheckpointInput,
        evidence_bundle: HeartbeatEvidenceBundle,
    ) -> HeartbeatAgentJudgment:
        implementation_signals = evidence_bundle.implementation_signals
        risk_signals = evidence_bundle.risk_signals
        has_execution_path = self._signal_flag(implementation_signals, "has_execution_path")
        has_interface_closure = self._signal_flag(implementation_signals, "has_interface_closure")
        has_gap_marker = self._signal_flag(risk_signals, "has_gap_marker")

        if not has_execution_path:
            used_signal_keys = ("implementation.has_execution_path",)
            return self._build_reject_judgment(
                checkpoint_input,
                evidence_bundle,
                rationale_text="Execution path is not grounded.",
                deficiency_category=RejectionDeficiencyCategory.INCOMPLETENESS,
                used_signal_keys=used_signal_keys,
                source_anchors=self._build_signal_source_anchors(
                    evidence_bundle,
                    used_signal_keys,
                ),
            )
        if not has_interface_closure:
            used_signal_keys = ("implementation.has_interface_closure",)
            return self._build_reject_judgment(
                checkpoint_input,
                evidence_bundle,
                rationale_text="Dependencies or interfaces are not explicit.",
                deficiency_category=RejectionDeficiencyCategory.INCOMPLETENESS,
                used_signal_keys=used_signal_keys,
                source_anchors=self._build_signal_source_anchors(
                    evidence_bundle,
                    used_signal_keys,
                ),
            )
        if has_gap_marker:
            used_signal_keys = ("risk.has_gap_marker",)
            return self._build_reject_judgment(
                checkpoint_input,
                evidence_bundle,
                rationale_text="Implementation gaps are still explicit.",
                deficiency_category=RejectionDeficiencyCategory.CLARITY_GAP,
                used_signal_keys=used_signal_keys,
                source_anchors=self._build_signal_source_anchors(
                    evidence_bundle,
                    used_signal_keys,
                ),
            )
        used_signal_keys = (
            "implementation.has_execution_path",
            "implementation.has_interface_closure",
        )
        return self._build_approval_judgment(
            checkpoint_input,
            evidence_bundle,
            "Execution path and dependencies are grounded.",
            blocker=False,
            used_signal_keys=used_signal_keys,
            source_anchors=self._build_signal_source_anchors(
                evidence_bundle,
                used_signal_keys,
            ),
        )
