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
class PlannerAgent(BaseAgent):
    """Role-specialized agent for planning and task decomposition."""

    @property
    def supports_role_specific_self_check(self) -> bool:
        return True

    @property
    def role_name(self) -> str:
        return "planner"

    def default_intent(self) -> str:
        return "plan"

    def default_action_type(self) -> str:
        return "plan.create"

    async def self_check(
        self,
        checkpoint_input: HeartbeatCheckpointInput,
        evidence_bundle: HeartbeatEvidenceBundle,
    ) -> HeartbeatAgentJudgment:
        coverage_signals = evidence_bundle.coverage_signals
        constraint_signals = evidence_bundle.constraint_signals
        has_goal_anchor = self._signal_flag(coverage_signals, "has_goal_overlap")
        has_plan_structure = self._signal_flag(coverage_signals, "has_plan_structure")
        has_constraints = self._signal_flag(constraint_signals, "has_constraints")

        if not has_goal_anchor:
            used_signal_keys = ("coverage.has_goal_overlap",)
            return self._build_reject_judgment(
                checkpoint_input,
                evidence_bundle,
                rationale_text="Goal coverage is not explicit.",
                deficiency_category=RejectionDeficiencyCategory.GOAL_MISALIGNMENT,
                used_signal_keys=used_signal_keys,
                source_anchors=self._build_signal_source_anchors(
                    evidence_bundle,
                    used_signal_keys,
                ),
            )
        if not has_plan_structure:
            used_signal_keys = ("coverage.has_plan_structure",)
            return self._build_reject_judgment(
                checkpoint_input,
                evidence_bundle,
                rationale_text="Plan closure is not explicit.",
                deficiency_category=RejectionDeficiencyCategory.INCOMPLETENESS,
                used_signal_keys=used_signal_keys,
                source_anchors=self._build_signal_source_anchors(
                    evidence_bundle,
                    used_signal_keys,
                ),
            )
        if not has_constraints:
            used_signal_keys = ("constraint.has_constraints",)
            return self._build_reject_judgment(
                checkpoint_input,
                evidence_bundle,
                rationale_text="Key constraints are not explicit.",
                deficiency_category=RejectionDeficiencyCategory.CONSTRAINT_VIOLATION,
                used_signal_keys=used_signal_keys,
                source_anchors=self._build_signal_source_anchors(
                    evidence_bundle,
                    used_signal_keys,
                ),
            )
        used_signal_keys = (
            "coverage.has_goal_overlap",
            "coverage.has_plan_structure",
            "constraint.has_constraints",
        )
        return self._build_approval_judgment(
            checkpoint_input,
            evidence_bundle,
            "Goal coverage and plan closure are explicit.",
            blocker=False,
            used_signal_keys=used_signal_keys,
            source_anchors=self._build_signal_source_anchors(
                evidence_bundle,
                used_signal_keys,
            ),
        )
