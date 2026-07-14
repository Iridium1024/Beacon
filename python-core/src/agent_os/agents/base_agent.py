from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agent_os.agents.agent_interface import Agent, AgentAction, AgentSummary, Perception, Thought
from agent_os.agents.model_access import ModelAccess
from agent_os.agents.specification import AgentConfig
from agent_os.memory.memory_interface import Memory
from agent_os.orchestrator.convergence import (
    HeartbeatAgentJudgment,
    HeartbeatCheckpointInput,
    HeartbeatEvidenceBundle,
    HeartbeatResourceStatus,
    HeartbeatSourceAnchor,
    HeartbeatVoteChoice,
    RejectionDeficiencyCategory,
)
from agent_os.orchestrator.heartbeat_grading import (
    canonicalize_severity_label,
    derive_heartbeat_grading,
)
from agent_os.orchestrator.source_anchor_utils import source_anchor_candidates_from_signal_keys
from agent_os.protocols.communication_protocol import CommunicationMessage
from agent_os.protocols.shared_context import SharedContext
from agent_os.tools.tool_interface import Tool


@dataclass(slots=True)
class BaseAgent(Agent, ABC):
    """Shared agent base that works against a blackboard-style shared context."""

    config: AgentConfig
    memory: Memory
    tools: Mapping[str, Tool]
    model_access: ModelAccess

    @property
    @abstractmethod
    def role_name(self) -> str:
        ...

    @property
    def agent_id(self) -> str:
        return self.config.agent_id

    @property
    def supports_role_specific_self_check(self) -> bool:
        """Base agents are not heartbeat-eligible until a role-specific check is implemented."""

        return False

    @property
    def parent_agent_id(self) -> str | None:
        return self.config.parent_agent_id

    @property
    def child_agent_ids(self) -> tuple[str, ...]:
        return self.config.child_agent_ids

    def list_tools(self) -> tuple[str, ...]:
        return tuple(self.tools.keys())

    def get_tool(self, tool_name: str) -> Tool | None:
        return self.tools.get(tool_name)

    def agent_metadata(self) -> dict[str, object]:
        return {
            "agent_id": self.config.agent_id,
            "role": self.role_name,
            "model_name": self.config.model_name,
            "model_adapter": self.model_access.metadata().provider_name,
            "memory_namespace": self.config.memory_namespace,
            "parent_agent_id": self.config.parent_agent_id,
            "child_agent_ids": self.config.child_agent_ids,
        }

    async def perceive(
        self,
        shared_context: SharedContext,
        update: CommunicationMessage | None = None,
    ) -> Perception:
        return Perception(
            shared_context=shared_context,
            update=update,
            context=self.agent_metadata(),
        )

    async def think(self, perception: Perception) -> Thought:
        return Thought(
            intent=self.default_intent(),
            reasoning_summary=f"{self.role_name} thought placeholder",
            context={
                **dict(perception.context),
                "available_tools": self.list_tools(),
            },
        )

    async def act(self, thought: Thought) -> AgentAction:
        return AgentAction(
            action_type=self.default_action_type(),
            payload={
                "agent_id": self.agent_id,
                "role": self.role_name,
                "intent": thought.intent,
            },
        )

    async def summarize(self, shared_context: SharedContext) -> AgentSummary:
        return AgentSummary(
            summary=f"{self.config.name} summary placeholder",
            references=tuple(message.message_id for message in shared_context.message_history),
            metadata=self.agent_metadata(),
        )

    async def self_check(
        self,
        checkpoint_input: HeartbeatCheckpointInput,
        evidence_bundle: HeartbeatEvidenceBundle,
    ) -> HeartbeatAgentJudgment:
        """Default conservative heartbeat judgment for agents without custom review logic.

        This fallback remains available for direct calls, but agents using it
        are excluded from formal heartbeat participant selection by default.
        """

        return HeartbeatAgentJudgment.create(
            checkpoint_id=checkpoint_input.checkpoint_id,
            agent_id=self.agent_id,
            candidate_id=checkpoint_input.frozen_candidate_id,
            evidence_bundle_id=evidence_bundle.evidence_bundle_id,
            decision=HeartbeatVoteChoice.REJECT,
            rationale_text=(
                f"{self.role_name} has no role-specific heartbeat self-check and cannot "
                "approve the frozen candidate."
            ),
            deficiency_category=RejectionDeficiencyCategory.OTHER,
            resource_status=HeartbeatResourceStatus.UNKNOWN,
            metadata={"default_self_check": True},
        )

    def _signal_flag(self, signals: Mapping[str, object], key: str) -> bool:
        """Read one boolean-like signal from the structured evidence bundle."""

        return bool(signals.get(key, False))

    def _build_approval_judgment(
        self,
        checkpoint_input: HeartbeatCheckpointInput,
        evidence_bundle: HeartbeatEvidenceBundle,
        rationale_text: str,
        *,
        severity: str | None = None,
        blocker: bool | None = False,
        used_signal_keys: tuple[str, ...] = (),
        source_anchors: Sequence[HeartbeatSourceAnchor] = (),
    ) -> HeartbeatAgentJudgment:
        """Build a concise approval judgment tied to structured evidence."""

        grading = derive_heartbeat_grading(
            decision=HeartbeatVoteChoice.APPROVE,
            deficiency_category=RejectionDeficiencyCategory.SUFFICIENT,
            used_signal_keys=used_signal_keys,
            source_anchors=source_anchors,
            checkpoint_input=checkpoint_input,
            evidence_bundle=evidence_bundle,
            agent_role=self.role_name,
        )
        return HeartbeatAgentJudgment.create(
            checkpoint_id=checkpoint_input.checkpoint_id,
            agent_id=self.agent_id,
            candidate_id=checkpoint_input.frozen_candidate_id,
            evidence_bundle_id=evidence_bundle.evidence_bundle_id,
            decision=HeartbeatVoteChoice.APPROVE,
            rationale_text=rationale_text,
            deficiency_category=RejectionDeficiencyCategory.SUFFICIENT,
            severity=canonicalize_severity_label(severity)
            if severity is not None
            else grading.severity,
            blocker=blocker if blocker is not None else grading.blocker,
            used_signal_keys=used_signal_keys,
            source_anchors=source_anchors,
            resource_status=HeartbeatResourceStatus.UNKNOWN,
            metadata={"role_specific_self_check": True, "agent_role": self.role_name},
        )

    def _build_reject_judgment(
        self,
        checkpoint_input: HeartbeatCheckpointInput,
        evidence_bundle: HeartbeatEvidenceBundle,
        *,
        rationale_text: str,
        deficiency_category: RejectionDeficiencyCategory,
        severity: str | None = None,
        blocker: bool | None = None,
        used_signal_keys: tuple[str, ...] = (),
        source_anchors: Sequence[HeartbeatSourceAnchor] = (),
    ) -> HeartbeatAgentJudgment:
        """Build a concise reject judgment tied to structured evidence."""

        grading = derive_heartbeat_grading(
            decision=HeartbeatVoteChoice.REJECT,
            deficiency_category=deficiency_category,
            used_signal_keys=used_signal_keys,
            source_anchors=source_anchors,
            checkpoint_input=checkpoint_input,
            evidence_bundle=evidence_bundle,
            agent_role=self.role_name,
        )
        return HeartbeatAgentJudgment.create(
            checkpoint_id=checkpoint_input.checkpoint_id,
            agent_id=self.agent_id,
            candidate_id=checkpoint_input.frozen_candidate_id,
            evidence_bundle_id=evidence_bundle.evidence_bundle_id,
            decision=HeartbeatVoteChoice.REJECT,
            rationale_text=rationale_text,
            deficiency_category=deficiency_category,
            severity=canonicalize_severity_label(severity)
            if severity is not None
            else grading.severity,
            blocker=blocker if blocker is not None else grading.blocker,
            used_signal_keys=used_signal_keys,
            source_anchors=source_anchors,
            resource_status=HeartbeatResourceStatus.UNKNOWN,
            metadata={"role_specific_self_check": True, "agent_role": self.role_name},
        )

    def _build_signal_source_anchors(
        self,
        evidence_bundle: HeartbeatEvidenceBundle,
        used_signal_keys: Sequence[str],
    ) -> tuple[HeartbeatSourceAnchor, ...]:
        """Bind used heartbeat signals back to their evidence-family source anchors."""

        return source_anchor_candidates_from_signal_keys(used_signal_keys, evidence_bundle)

    @abstractmethod
    def default_intent(self) -> str:
        ...

    @abstractmethod
    def default_action_type(self) -> str:
        ...
