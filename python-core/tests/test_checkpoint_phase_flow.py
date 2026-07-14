from __future__ import annotations

import asyncio
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.adapters.model_adapter import (
    ModelAdapter,
    ModelAdapterMetadata,
    ModelGenerateRequest,
    ModelGenerateResponse,
)
from agent_os.agents import AgentConfig, ExecutorAgent, ModelAccess, PlannerAgent, ReviewerAgent
from agent_os.agents.agent_interface import Agent, AgentAction, AgentSummary, Perception, Thought
from agent_os.memory.memory_interface import Memory, MemoryQuery, MemoryRecord
from agent_os.orchestrator.convergence import (
    CheckpointTriggerConfiguration,
    ConvergenceStatus,
    ConvergenceThresholdProfile,
    CoordinationPhase,
    HeartbeatAgentJudgment,
    HeartbeatAggregateArtifact,
    HeartbeatCheckpointDefinition,
    HeartbeatEvidenceBundle,
    HeartbeatCheckpointInput,
    HeartbeatResourceStatus,
    HeartbeatSourceAnchor,
    HeartbeatVoteChoice,
    ParticipantStatus,
    RejectionDeficiencyCategory,
    Trigger,
    TriggerConfigurationLayer,
    TriggerScope,
    TriggerType,
    VotingThresholds,
)
from agent_os.orchestrator.evidence_extractors import (
    ConstraintEvidenceExtractor,
    CoverageEvidenceExtractor,
    ImplementationEvidenceExtractor,
    RiskEvidenceExtractor,
    ValidationEvidenceExtractor,
    build_heartbeat_evidence_extraction_input,
)
from agent_os.orchestrator.heartbeat_convergence_profile import (
    HeartbeatConvergenceDominantReason,
    HeartbeatConvergenceFollowupBias,
    HeartbeatConvergenceReservationLevel,
    HeartbeatConvergenceSemanticState,
)
from agent_os.orchestrator.orchestrator_interface import AgentDescriptor
from agent_os.orchestrator.heartbeat_report_adapter import build_heartbeat_report_payload
from agent_os.orchestrator.heartbeat_terminal_payload import build_heartbeat_terminal_view
from agent_os.orchestrator.runtime_state import ExecutionState
from agent_os.orchestrator.scheduler import Scheduler, SchedulerOptions
from agent_os.protocols.communication_protocol import CommunicationMessage
from agent_os.protocols.final_answer_candidate import FinalAnswerCandidateStatus


class StubAgent(Agent):
    def __init__(
        self,
        *,
        summary_text: str,
        summary_metadata: dict[str, object] | None = None,
        self_check_payload: dict[str, object] | None = None,
        supports_role_specific_self_check: bool = True,
    ) -> None:
        self._summary_text = summary_text
        self._summary_metadata = summary_metadata or {}
        self._self_check_payload = self_check_payload
        self._supports_role_specific_self_check = supports_role_specific_self_check
        self.self_check_calls = 0

    async def perceive(self, shared_context, update=None) -> Perception:
        return Perception(shared_context=shared_context, update=update)

    async def think(self, perception: Perception) -> Thought:
        return Thought(intent="noop", reasoning_summary="noop")

    async def act(self, thought: Thought) -> AgentAction:
        return AgentAction(action_type="noop")

    async def summarize(self, shared_context) -> AgentSummary:
        return AgentSummary(summary=self._summary_text, metadata=self._summary_metadata)

    @property
    def supports_role_specific_self_check(self) -> bool:
        return self._supports_role_specific_self_check

    async def self_check(
        self,
        checkpoint_input: HeartbeatCheckpointInput,
        evidence_bundle: HeartbeatEvidenceBundle,
    ) -> dict[str, object] | None:
        self.self_check_calls += 1
        if self._self_check_payload is None:
            return None
        return dict(self._self_check_payload)


class StubMemory(Memory):
    async def store(self, record: MemoryRecord) -> None:
        return None

    async def retrieve(self, query: MemoryQuery) -> tuple[MemoryRecord, ...]:
        return ()

    async def embed(self, inputs) -> tuple[tuple[float, ...], ...]:
        return tuple((0.0,) for _ in inputs)


class StubModelAdapter(ModelAdapter):
    async def generate(self, request: ModelGenerateRequest) -> ModelGenerateResponse:
        return ModelGenerateResponse(model_name=request.model_name, content="stub")

    async def stream(self, request: ModelGenerateRequest):
        if False:
            yield

    def metadata(self) -> ModelAdapterMetadata:
        return ModelAdapterMetadata(
            adapter_name="stub-adapter",
            provider_name="stub-provider",
            supported_models=("stub-model",),
        )


def make_role_agent(agent_cls, *, agent_id: str, name: str):
    config = AgentConfig(
        agent_id=agent_id,
        role=agent_id,
        name=name,
        model_name="stub-model",
        model_adapter_alias="stub",
        memory_namespace=f"{agent_id}.memory",
    )
    return agent_cls(
        config=config,
        memory=StubMemory(),
        tools={},
        model_access=ModelAccess(adapter=StubModelAdapter(), model_name="stub-model"),
    )


def round_trigger_configuration(interval_rounds: int) -> CheckpointTriggerConfiguration:
    return CheckpointTriggerConfiguration(
        global_defaults=TriggerConfigurationLayer(
            scope=TriggerScope.GLOBAL_DEFAULT,
            triggers=(
                Trigger(
                    id="round-checkpoint",
                    trigger_type=TriggerType.ROUND_BASED,
                    parameters={"interval_rounds": interval_rounds},
                ),
            ),
        )
    )


def threshold_profile(support_ratio_threshold: float) -> ConvergenceThresholdProfile:
    return ConvergenceThresholdProfile(
        voting=VotingThresholds(support_ratio_threshold=support_ratio_threshold)
    )


def build_checkpoint_and_evidence(
    state: ExecutionState,
) -> tuple[HeartbeatCheckpointInput, HeartbeatEvidenceBundle]:
    checkpoint_input = state.create_heartbeat_checkpoint_input()
    evidence_bundle = state.create_heartbeat_evidence_bundle(checkpoint_input)
    return checkpoint_input, evidence_bundle


def build_extraction_input(state: ExecutionState):
    checkpoint_input = state.create_heartbeat_checkpoint_input()
    candidate = state.get_current_candidate()
    if candidate is None:
        raise AssertionError("Expected current candidate for extraction input test.")
    return checkpoint_input, build_heartbeat_evidence_extraction_input(checkpoint_input, candidate)


def build_manual_evidence_bundle(
    *,
    evidence_bundle_id: str = "evidence-1",
    coverage_signals: dict[str, object] | None = None,
    constraint_signals: dict[str, object] | None = None,
    implementation_signals: dict[str, object] | None = None,
    risk_signals: dict[str, object] | None = None,
    evidence_signals: dict[str, object] | None = None,
) -> HeartbeatEvidenceBundle:
    return HeartbeatEvidenceBundle.create(
        checkpoint_id="checkpoint-1",
        candidate_id="candidate-1",
        original_goal="test goal",
        candidate_summary="candidate summary",
        evidence_bundle_id=evidence_bundle_id,
        coverage_signals=coverage_signals,
        constraint_signals=constraint_signals,
        implementation_signals=implementation_signals,
        risk_signals=risk_signals,
        evidence_signals=evidence_signals,
    )


def find_artifact_item(
    artifact: HeartbeatAggregateArtifact,
    category: RejectionDeficiencyCategory,
):
    for item in artifact.consensus_items + artifact.minority_items + artifact.unresolved_items:
        if item.category == category:
            return item
    raise AssertionError(f"Expected artifact item for category {category.value}.")


def assert_terminal_consumption_attached(
    test_case: unittest.TestCase,
    aggregate,
) -> None:
    test_case.assertIsNotNone(aggregate.aggregate_artifact)
    test_case.assertIsNotNone(aggregate.candidate_snapshot)
    test_case.assertIsNotNone(aggregate.convergence_profile)
    test_case.assertIsNotNone(aggregate.outcome_snapshot)
    test_case.assertIsNotNone(aggregate.candidate_presentation)
    test_case.assertIsNotNone(aggregate.terminal_payload)
    test_case.assertIs(aggregate.aggregate_artifact.candidate_snapshot, aggregate.candidate_snapshot)
    test_case.assertIs(aggregate.aggregate_artifact.convergence_profile, aggregate.convergence_profile)
    test_case.assertIs(aggregate.aggregate_artifact.outcome_snapshot, aggregate.outcome_snapshot)
    test_case.assertIs(
        aggregate.aggregate_artifact.candidate_presentation,
        aggregate.candidate_presentation,
    )
    test_case.assertIs(aggregate.aggregate_artifact.terminal_payload, aggregate.terminal_payload)
    terminal_view = build_heartbeat_terminal_view(aggregate)
    test_case.assertIs(terminal_view, aggregate.terminal_payload)
    test_case.assertIs(terminal_view.candidate, aggregate.candidate_presentation)
    test_case.assertEqual(terminal_view.final_decision, aggregate.recommended_outcome)


class CheckpointPhaseFlowTests(unittest.TestCase):
    def test_coverage_extractor_produces_stable_signal_with_source_anchoring(self) -> None:
        state = ExecutionState(
            workflow_id="wf-1",
            goal="deliver explicit sandboxed workflow constraints",
            participant_agent_ids=("planner",),
        )
        state.publish_candidate_from_discussion(
            summary_text="The workflow plan covers sandboxed steps and constraints.",
            source_agent_id="planner",
            structured_content={"steps": ("inspect", "patch"), "constraints": ("sandboxed",)},
        )
        state.enter_heartbeat_checkpoint()
        _, extraction_input = build_extraction_input(state)

        signals = CoverageEvidenceExtractor().extract(extraction_input)

        self.assertTrue(signals["has_goal_overlap"])
        self.assertTrue(signals["has_plan_structure"])
        self.assertIn("candidate_summary", signals["source_fields"])
        self.assertTrue(signals["derived_from_summary"])

    def test_constraint_extractor_gracefully_degrades_with_missing_optional_fields(self) -> None:
        state = ExecutionState(
            workflow_id="wf-1",
            goal="deliver explicit sandboxed workflow constraints",
            participant_agent_ids=("planner",),
        )
        state.publish_candidate_from_discussion(
            summary_text="Candidate without extra structure.",
            source_agent_id="planner",
        )
        state.enter_heartbeat_checkpoint()
        _, extraction_input = build_extraction_input(state)

        signals = ConstraintEvidenceExtractor().extract(extraction_input)

        self.assertFalse(signals["has_constraints"])
        self.assertEqual(signals["matched_terms"], ())
        self.assertIn("candidate_summary", signals["source_fields"])

    def test_implementation_extractor_produces_stable_signal_with_source_anchoring(self) -> None:
        state = ExecutionState(
            workflow_id="wf-1",
            goal="apply implementation changes with explicit interfaces",
            participant_agent_ids=("executor",),
        )
        state.publish_candidate_from_discussion(
            summary_text="Implementation files and interface dependencies are explicit.",
            source_agent_id="executor",
            structured_content={"files": ("scheduler.py",), "interfaces": ("Agent.self_check",)},
        )
        state.enter_heartbeat_checkpoint()
        _, extraction_input = build_extraction_input(state)

        signals = ImplementationEvidenceExtractor().extract(extraction_input)

        self.assertTrue(signals["has_execution_path"])
        self.assertTrue(signals["has_interface_closure"])
        self.assertIn("structured_content", signals["source_fields"])

    def test_risk_extractor_produces_stable_signal_with_source_anchoring(self) -> None:
        state = ExecutionState(
            workflow_id="wf-1",
            goal="review unresolved implementation risk",
            participant_agent_ids=("reviewer",),
        )
        state.publish_candidate_from_discussion(
            summary_text="There is a pending risk and unclear behavior.",
            source_agent_id="reviewer",
        )
        state.enter_heartbeat_checkpoint()
        _, extraction_input = build_extraction_input(state)

        signals = RiskEvidenceExtractor().extract(extraction_input)

        self.assertTrue(signals["has_risk_marker"])
        self.assertTrue(signals["has_clarity_marker"])
        self.assertIn("candidate_summary", signals["source_fields"])

    def test_validation_extractor_produces_stable_signal_with_context_anchoring(self) -> None:
        state = ExecutionState(
            workflow_id="wf-1",
            goal="validate the candidate with explicit checks",
            participant_agent_ids=("reviewer",),
        )
        state.shared_context.append_message(
            CommunicationMessage(
                id="ctx-1",
                sender="reviewer",
                summary_text="prior validation context",
            )
        )
        state.publish_candidate_from_discussion(
            summary_text="Validation checks and evidence are explicit.",
            source_agent_id="reviewer",
            payload={"checks": ("heartbeat",), "evidence": "validated"},
        )
        state.enter_heartbeat_checkpoint()
        checkpoint_input = state.create_heartbeat_checkpoint_input()
        candidate = state.get_current_candidate()
        if candidate is None:
            raise AssertionError("Expected current candidate for validation extractor test.")
        extraction_input = build_heartbeat_evidence_extraction_input(checkpoint_input, candidate)

        signals = ValidationEvidenceExtractor().extract(extraction_input)

        self.assertTrue(signals["has_validation_signal"])
        self.assertEqual(signals["matched_refs"], ("ctx-1",))
        self.assertIn("relevant_context_refs", signals["source_fields"])

    def test_frozen_candidate_builds_heartbeat_evidence_bundle(self) -> None:
        state = ExecutionState(
            workflow_id="wf-1",
            goal="deliver explicit sandboxed workflow constraints",
            participant_agent_ids=("planner",),
        )
        state.publish_candidate_from_discussion(
            summary_text="The workflow includes steps, constraints, checks, and evidence.",
            source_agent_id="planner",
            structured_content={"steps": ("inspect", "patch"), "constraints": ("sandboxed",)},
            payload={"checks": ("heartbeat",), "evidence": "validated"},
        )
        state.enter_heartbeat_checkpoint()

        checkpoint_input, evidence_bundle = build_checkpoint_and_evidence(state)

        self.assertEqual(evidence_bundle.checkpoint_id, checkpoint_input.checkpoint_id)
        self.assertEqual(evidence_bundle.candidate_id, checkpoint_input.frozen_candidate_id)
        self.assertTrue(evidence_bundle.coverage_signals["has_plan_structure"])
        self.assertTrue(evidence_bundle.constraint_signals["has_constraints"])
        self.assertTrue(evidence_bundle.evidence_signals["has_validation_signal"])
        self.assertIn("source_fields", evidence_bundle.coverage_signals)
        self.assertIn("source_fields", evidence_bundle.evidence_signals)

    def test_evidence_bundle_builder_handles_missing_optional_fields(self) -> None:
        state = ExecutionState(
            workflow_id="wf-1",
            goal="produce a stable candidate",
            participant_agent_ids=("planner",),
        )
        state.publish_candidate_from_discussion(
            summary_text="Stable candidate summary only.",
            source_agent_id="planner",
        )
        state.enter_heartbeat_checkpoint()

        checkpoint_input, evidence_bundle = build_checkpoint_and_evidence(state)

        self.assertEqual(evidence_bundle.checkpoint_id, checkpoint_input.checkpoint_id)
        self.assertIsNone(evidence_bundle.structured_content_summary)
        self.assertIsNone(evidence_bundle.payload_summary)
        self.assertIsInstance(evidence_bundle.coverage_signals, dict)
        self.assertIn("source_fields", evidence_bundle.constraint_signals)

    def test_evidence_bundle_is_read_only_evaluation_input(self) -> None:
        state = ExecutionState(
            workflow_id="wf-1",
            goal="produce a stable candidate",
            participant_agent_ids=("planner",),
        )
        state.publish_candidate_from_discussion(
            summary_text="Stable candidate summary only.",
            source_agent_id="planner",
        )
        state.enter_heartbeat_checkpoint()

        _, evidence_bundle = build_checkpoint_and_evidence(state)

        with self.assertRaises(FrozenInstanceError):
            evidence_bundle.candidate_summary = "rewritten candidate"

    def test_planner_role_specific_self_check_produces_valid_judgment(self) -> None:
        planner = make_role_agent(PlannerAgent, agent_id="planner", name="Planner")
        scheduler = Scheduler(agents={"planner": planner})
        state = ExecutionState(
            workflow_id="wf-1",
            goal="deliver sandboxed multi-agent plan with explicit constraints",
            participant_agent_ids=("planner",),
        )
        state.publish_candidate_from_discussion(
            summary_text="The plan covers the sandboxed workflow, steps, and constraints.",
            source_agent_id="planner",
            structured_content={
                "steps": ("inspect", "patch", "verify"),
                "constraints": ("sandboxed", "model-agnostic"),
                "coverage": "complete",
            },
        )
        state.enter_heartbeat_checkpoint()
        checkpoint_input, evidence_bundle = build_checkpoint_and_evidence(state)

        judgment = asyncio.run(
            scheduler.generate_self_check_judgment("planner", checkpoint_input, evidence_bundle, state)
        )

        self.assertEqual(judgment.decision, HeartbeatVoteChoice.APPROVE)
        self.assertEqual(judgment.deficiency_category, RejectionDeficiencyCategory.SUFFICIENT)
        self.assertEqual(judgment.evidence_bundle_id, evidence_bundle.evidence_bundle_id)
        self.assertFalse(judgment.blocker)
        self.assertEqual(
            judgment.used_signal_keys,
            (
                "coverage.has_goal_overlap",
                "coverage.has_plan_structure",
                "constraint.has_constraints",
            ),
        )
        self.assertEqual(
            tuple(anchor.signal_key for anchor in judgment.source_anchors),
            judgment.used_signal_keys,
        )
        self.assertTrue(all(anchor.source_fields for anchor in judgment.source_anchors))
        self.assertNotIn("proposed answer:", judgment.rationale_text.lower())

    def test_executor_role_specific_self_check_produces_valid_judgment(self) -> None:
        executor = make_role_agent(ExecutorAgent, agent_id="executor", name="Executor")
        scheduler = Scheduler(agents={"executor": executor})
        state = ExecutionState(
            workflow_id="wf-1",
            goal="apply the implementation path to the workspace",
            participant_agent_ids=("executor",),
        )
        state.publish_candidate_from_discussion(
            summary_text="Implementation files, actions, interfaces, and dependencies are explicit.",
            source_agent_id="executor",
            structured_content={
                "files": ("scheduler.py", "runtime_state.py"),
                "actions": ("freeze", "self_check"),
                "interfaces": ("Agent.self_check",),
                "dependencies": ("ExecutionState",),
            },
        )
        state.enter_heartbeat_checkpoint()
        checkpoint_input, evidence_bundle = build_checkpoint_and_evidence(state)

        judgment = asyncio.run(
            scheduler.generate_self_check_judgment("executor", checkpoint_input, evidence_bundle, state)
        )

        self.assertEqual(judgment.decision, HeartbeatVoteChoice.APPROVE)
        self.assertEqual(judgment.deficiency_category, RejectionDeficiencyCategory.SUFFICIENT)
        self.assertEqual(judgment.evidence_bundle_id, evidence_bundle.evidence_bundle_id)
        self.assertFalse(judgment.blocker)
        self.assertEqual(
            tuple(anchor.signal_key for anchor in judgment.source_anchors),
            judgment.used_signal_keys,
        )
        self.assertTrue(all(anchor.source_fields for anchor in judgment.source_anchors))
        self.assertNotIn("replace with", judgment.rationale_text.lower())

    def test_source_anchor_binding_matches_between_producer_and_aggregate_fallback(self) -> None:
        executor = make_role_agent(ExecutorAgent, agent_id="executor", name="Executor")
        scheduler = Scheduler(agents={"executor": executor})
        state = ExecutionState(
            workflow_id="wf-1",
            goal="apply the implementation path to the workspace",
            participant_agent_ids=("executor",),
        )
        state.publish_candidate_from_discussion(
            summary_text="Implementation files, actions, interfaces, and dependencies are explicit.",
            source_agent_id="executor",
            structured_content={
                "files": ("scheduler.py", "runtime_state.py"),
                "actions": ("freeze", "self_check"),
                "interfaces": ("Agent.self_check",),
                "dependencies": ("ExecutionState",),
            },
        )
        state.enter_heartbeat_checkpoint()
        checkpoint_input, evidence_bundle = build_checkpoint_and_evidence(state)

        produced_judgment = asyncio.run(
            scheduler.generate_self_check_judgment("executor", checkpoint_input, evidence_bundle, state)
        )
        fallback_judgment = HeartbeatAgentJudgment.create(
            judgment_id="judgment-executor-fallback",
            checkpoint_id=checkpoint_input.checkpoint_id,
            agent_id="executor",
            candidate_id=checkpoint_input.frozen_candidate_id,
            evidence_bundle_id=evidence_bundle.evidence_bundle_id,
            decision=produced_judgment.decision,
            rationale_text=produced_judgment.rationale_text,
            deficiency_category=produced_judgment.deficiency_category,
            severity=produced_judgment.severity,
            blocker=produced_judgment.blocker,
            used_signal_keys=produced_judgment.used_signal_keys,
            metadata={"agent_role": "executor"},
        )

        aggregate = scheduler.aggregate_heartbeat_judgments(
            checkpoint_input,
            (fallback_judgment,),
            evidence_bundle=evidence_bundle,
        )

        item = find_artifact_item(
            aggregate.aggregate_artifact,
            RejectionDeficiencyCategory.SUFFICIENT,
        )
        self.assertEqual(item.source_anchors, produced_judgment.source_anchors)

    def test_reviewer_role_specific_self_check_produces_valid_judgment(self) -> None:
        reviewer = make_role_agent(ReviewerAgent, agent_id="reviewer", name="Reviewer")
        scheduler = Scheduler(agents={"reviewer": reviewer})
        state = ExecutionState(
            workflow_id="wf-1",
            goal="validate the frozen candidate for correctness and evidence",
            participant_agent_ids=("reviewer",),
        )
        state.publish_candidate_from_discussion(
            summary_text="Validation checks and evidence are explicit.",
            source_agent_id="reviewer",
            payload={
                "checks": ("phase guard", "freeze guard"),
                "evidence": "validated",
                "consistency": "aligned",
            },
        )
        state.enter_heartbeat_checkpoint()
        checkpoint_input, evidence_bundle = build_checkpoint_and_evidence(state)

        judgment = asyncio.run(
            scheduler.generate_self_check_judgment("reviewer", checkpoint_input, evidence_bundle, state)
        )

        self.assertEqual(judgment.decision, HeartbeatVoteChoice.APPROVE)
        self.assertEqual(judgment.deficiency_category, RejectionDeficiencyCategory.SUFFICIENT)
        self.assertEqual(judgment.evidence_bundle_id, evidence_bundle.evidence_bundle_id)
        self.assertFalse(judgment.blocker)
        self.assertEqual(
            tuple(anchor.signal_key for anchor in judgment.source_anchors),
            judgment.used_signal_keys,
        )
        self.assertTrue(all(anchor.source_fields for anchor in judgment.source_anchors))
        self.assertNotIn("new solution:", judgment.rationale_text.lower())

    def test_role_specific_reject_judgment_uses_reasonable_deficiency_category(self) -> None:
        planner = make_role_agent(PlannerAgent, agent_id="planner", name="Planner")
        scheduler = Scheduler(agents={"planner": planner})
        state = ExecutionState(
            workflow_id="wf-1",
            goal="deliver sandboxed multi-agent plan with explicit constraints",
            participant_agent_ids=("planner",),
        )
        state.publish_candidate_from_discussion(
            summary_text="The plan covers the goal and steps.",
            source_agent_id="planner",
            structured_content={"steps": ("inspect", "patch")},
        )
        state.enter_heartbeat_checkpoint()
        checkpoint_input, evidence_bundle = build_checkpoint_and_evidence(state)

        judgment = asyncio.run(
            scheduler.generate_self_check_judgment("planner", checkpoint_input, evidence_bundle, state)
        )

        self.assertEqual(judgment.decision, HeartbeatVoteChoice.REJECT)
        self.assertEqual(
            judgment.deficiency_category,
            RejectionDeficiencyCategory.CONSTRAINT_VIOLATION,
        )
        self.assertEqual(judgment.severity, "critical")
        self.assertTrue(judgment.blocker)
        self.assertEqual(judgment.used_signal_keys, ("constraint.has_constraints",))
        self.assertEqual(
            tuple(anchor.signal_key for anchor in judgment.source_anchors),
            ("constraint.has_constraints",),
        )
        self.assertTrue(judgment.source_anchors[0].derived_from_summary)

    def test_executor_gap_marker_emits_non_blocking_moderate_severity_with_source_anchor(
        self,
    ) -> None:
        executor = make_role_agent(ExecutorAgent, agent_id="executor", name="Executor")
        scheduler = Scheduler(agents={"executor": executor})
        state = ExecutionState(
            workflow_id="wf-1",
            goal="apply the implementation path to the workspace",
            participant_agent_ids=("executor",),
        )
        state.publish_candidate_from_discussion(
            summary_text="Implementation files, actions, interfaces, and pending dependencies are explicit.",
            source_agent_id="executor",
            structured_content={
                "files": ("scheduler.py",),
                "actions": ("freeze", "self_check"),
                "interfaces": ("Agent.self_check",),
                "dependencies": ("ExecutionState",),
            },
        )
        state.enter_heartbeat_checkpoint()
        checkpoint_input, evidence_bundle = build_checkpoint_and_evidence(state)

        judgment = asyncio.run(
            scheduler.generate_self_check_judgment("executor", checkpoint_input, evidence_bundle, state)
        )

        self.assertEqual(judgment.decision, HeartbeatVoteChoice.REJECT)
        self.assertEqual(judgment.deficiency_category, RejectionDeficiencyCategory.CLARITY_GAP)
        self.assertEqual(judgment.severity, "moderate")
        self.assertFalse(judgment.blocker)
        self.assertEqual(judgment.used_signal_keys, ("risk.has_gap_marker",))
        self.assertEqual(
            tuple(anchor.signal_key for anchor in judgment.source_anchors),
            ("risk.has_gap_marker",),
        )
        self.assertTrue(judgment.source_anchors[0].derived_from_summary)

    def test_reviewer_core_evidence_gap_emits_major_non_blocking_severity_and_source_anchor(
        self,
    ) -> None:
        reviewer = make_role_agent(ReviewerAgent, agent_id="reviewer", name="Reviewer")
        scheduler = Scheduler(agents={"reviewer": reviewer})
        state = ExecutionState(
            workflow_id="wf-1",
            goal="validate the frozen candidate for correctness and evidence",
            participant_agent_ids=("reviewer",),
        )
        state.publish_candidate_from_discussion(
            summary_text="This candidate is unsupported and missing evidence.",
            source_agent_id="reviewer",
        )
        state.enter_heartbeat_checkpoint()
        checkpoint_input, evidence_bundle = build_checkpoint_and_evidence(state)

        judgment = asyncio.run(
            scheduler.generate_self_check_judgment("reviewer", checkpoint_input, evidence_bundle, state)
        )

        self.assertEqual(judgment.decision, HeartbeatVoteChoice.REJECT)
        self.assertEqual(judgment.deficiency_category, RejectionDeficiencyCategory.EVIDENCE_GAP)
        self.assertEqual(judgment.severity, "major")
        self.assertFalse(judgment.blocker)
        self.assertEqual(judgment.used_signal_keys, ("evidence.has_evidence_gap",))
        self.assertEqual(
            tuple(anchor.signal_key for anchor in judgment.source_anchors),
            ("evidence.has_evidence_gap",),
        )
        self.assertTrue(judgment.source_anchors[0].derived_from_summary)

    def test_reviewer_missing_validation_emits_non_blocking_moderate_severity(self) -> None:
        reviewer = make_role_agent(ReviewerAgent, agent_id="reviewer", name="Reviewer")
        scheduler = Scheduler(agents={"reviewer": reviewer})
        state = ExecutionState(
            workflow_id="wf-1",
            goal="validate the frozen candidate for correctness and evidence",
            participant_agent_ids=("reviewer",),
        )
        state.publish_candidate_from_discussion(
            summary_text="Review notes are explicit and aligned.",
            source_agent_id="reviewer",
            payload={"notes": "aligned"},
        )
        state.enter_heartbeat_checkpoint()
        checkpoint_input, evidence_bundle = build_checkpoint_and_evidence(state)

        judgment = asyncio.run(
            scheduler.generate_self_check_judgment("reviewer", checkpoint_input, evidence_bundle, state)
        )

        self.assertEqual(judgment.decision, HeartbeatVoteChoice.REJECT)
        self.assertEqual(judgment.deficiency_category, RejectionDeficiencyCategory.EVIDENCE_GAP)
        self.assertEqual(judgment.severity, "moderate")
        self.assertFalse(judgment.blocker)
        self.assertEqual(judgment.used_signal_keys, ("evidence.has_validation_signal",))
        self.assertEqual(
            tuple(anchor.signal_key for anchor in judgment.source_anchors),
            ("evidence.has_validation_signal",),
        )
        self.assertTrue(judgment.source_anchors[0].derived_from_payload)

    def test_scheduler_uses_formal_self_check_seam_not_duck_typed_attrs(self) -> None:
        agent = StubAgent(
            summary_text="planner draft",
            self_check_payload={
                "decision": "approve",
                "rationale_text": "Frozen candidate is sufficient for the goal.",
            },
        )
        agent.heartbeat_decision = "reject"
        agent.heartbeat_rationale = "This legacy duck-typed field should be ignored."
        scheduler = Scheduler(agents={"planner": agent})
        state = ExecutionState(
            workflow_id="wf-1",
            goal="test goal",
            participant_agent_ids=("planner",),
        )
        state.publish_candidate_from_discussion(
            summary_text="candidate summary",
            source_agent_id="planner",
        )
        state.enter_heartbeat_checkpoint()
        checkpoint_input, evidence_bundle = build_checkpoint_and_evidence(state)

        judgment = asyncio.run(
            scheduler.generate_self_check_judgment("planner", checkpoint_input, evidence_bundle, state)
        )

        self.assertEqual(judgment.decision, HeartbeatVoteChoice.APPROVE)
        self.assertEqual(agent.self_check_calls, 1)
        self.assertEqual(judgment.evidence_bundle_id, evidence_bundle.evidence_bundle_id)

    def test_agent_without_role_specific_self_check_does_not_pollute_heartbeat_statistics(self) -> None:
        planner = make_role_agent(PlannerAgent, agent_id="planner", name="Planner")
        helper = StubAgent(
            summary_text="helper note",
            self_check_payload={
                "decision": "reject",
                "rationale_text": "Default helper judgment should not count.",
            },
            supports_role_specific_self_check=False,
        )
        scheduler = Scheduler(agents={"planner": planner, "helper": helper})
        state = ExecutionState(
            workflow_id="wf-1",
            goal="deliver sandboxed multi-agent plan with explicit constraints",
            participant_agent_ids=("planner", "helper"),
        )
        state.publish_candidate_from_discussion(
            summary_text="The plan covers the sandboxed workflow, steps, and constraints.",
            source_agent_id="planner",
            structured_content={
                "steps": ("inspect", "patch", "verify"),
                "constraints": ("sandboxed", "model-agnostic"),
                "coverage": "complete",
            },
        )
        state.enter_heartbeat_checkpoint()
        checkpoint_input, _ = build_checkpoint_and_evidence(state)

        assessment = asyncio.run(scheduler.evaluate_heartbeat_checkpoint(checkpoint_input, state))

        self.assertEqual(tuple(judgment.agent_id for judgment in assessment.judgments), ("planner",))
        self.assertEqual(helper.self_check_calls, 0)

    def test_frozen_candidate_builds_checkpoint_input(self) -> None:
        state = ExecutionState(
            workflow_id="wf-1",
            goal="test goal",
            participant_agent_ids=("planner",),
        )
        state.shared_context.append_message(
            CommunicationMessage(
                id="msg-1",
                sender="planner",
                summary_text="discussion context",
            )
        )
        candidate = state.publish_candidate_from_discussion(
            summary_text="candidate summary",
            source_agent_id="planner",
        )
        state.enter_heartbeat_checkpoint()

        checkpoint_input = state.create_heartbeat_checkpoint_input(
            trigger_ids=("round-checkpoint",),
        )

        self.assertEqual(checkpoint_input.workflow_id, "wf-1")
        self.assertEqual(checkpoint_input.original_goal, "test goal")
        self.assertEqual(checkpoint_input.frozen_candidate_id, candidate.candidate_id)
        self.assertEqual(checkpoint_input.frozen_candidate_summary, "candidate summary")
        self.assertEqual(checkpoint_input.source_round, 1)
        self.assertEqual(checkpoint_input.relevant_context_refs, ("msg-1",))

    def test_heartbeat_phase_can_generate_self_check_judgment(self) -> None:
        scheduler = Scheduler(
            agents={
                "planner": StubAgent(
                    summary_text="planner draft",
                    self_check_payload={
                        "decision": "approve",
                        "rationale_text": "Current candidate satisfies the goal.",
                    },
                )
            }
        )
        state = ExecutionState(
            workflow_id="wf-1",
            goal="test goal",
            participant_agent_ids=("planner",),
        )
        candidate = state.publish_candidate_from_discussion(
            summary_text="candidate summary",
            source_agent_id="planner",
        )
        state.enter_heartbeat_checkpoint()
        checkpoint_input, evidence_bundle = build_checkpoint_and_evidence(state)

        judgment = asyncio.run(
            scheduler.generate_self_check_judgment("planner", checkpoint_input, evidence_bundle, state)
        )

        self.assertEqual(judgment.checkpoint_id, checkpoint_input.checkpoint_id)
        self.assertEqual(judgment.agent_id, "planner")
        self.assertEqual(judgment.candidate_id, candidate.candidate_id)
        self.assertEqual(judgment.evidence_bundle_id, evidence_bundle.evidence_bundle_id)
        self.assertEqual(judgment.decision, HeartbeatVoteChoice.APPROVE)
        self.assertEqual(judgment.deficiency_category, RejectionDeficiencyCategory.SUFFICIENT)
        self.assertEqual(judgment.resource_status, HeartbeatResourceStatus.UNKNOWN)

    def test_invalid_judgment_is_standardized_to_explicit_reject(self) -> None:
        scheduler = Scheduler(
            agents={
                "planner": StubAgent(
                    summary_text="planner draft",
                    self_check_payload={},
                )
            }
        )
        state = ExecutionState(
            workflow_id="wf-1",
            goal="test goal",
            participant_agent_ids=("planner",),
        )
        state.publish_candidate_from_discussion(
            summary_text="candidate summary",
            source_agent_id="planner",
        )
        state.enter_heartbeat_checkpoint()
        checkpoint_input, evidence_bundle = build_checkpoint_and_evidence(state)

        judgment = asyncio.run(
            scheduler.generate_self_check_judgment("planner", checkpoint_input, evidence_bundle, state)
        )

        self.assertEqual(judgment.decision, HeartbeatVoteChoice.REJECT)
        self.assertEqual(judgment.deficiency_category, RejectionDeficiencyCategory.OTHER)
        self.assertEqual(judgment.evidence_bundle_id, evidence_bundle.evidence_bundle_id)
        self.assertTrue(judgment.metadata["standardized_invalid_output"])

    def test_generate_self_check_judgment_promotes_legacy_metadata_fields_into_formal_schema(
        self,
    ) -> None:
        scheduler = Scheduler(
            agents={
                "reviewer": StubAgent(
                    summary_text="reviewer draft",
                    self_check_payload={
                        "decision": "reject",
                        "rationale_text": "Validation evidence is not explicit.",
                        "deficiency_category": "evidence_gap",
                        "metadata": {
                            "severity": "high",
                            "blocker": True,
                            "used_signal_keys": ("evidence.has_validation_signal",),
                            "source_anchors": (
                                {
                                    "signal_key": "evidence.has_validation_signal",
                                    "signal_family": "evidence",
                                    "source_fields": ("candidate_summary", "payload"),
                                    "matched_refs": ("ctx-1",),
                                    "derived_from_summary": True,
                                    "derived_from_payload": True,
                                },
                            ),
                        },
                    },
                )
            }
        )
        state = ExecutionState(
            workflow_id="wf-1",
            goal="test goal",
            participant_agent_ids=("reviewer",),
        )
        state.publish_candidate_from_discussion(
            summary_text="candidate summary",
            source_agent_id="reviewer",
        )
        state.enter_heartbeat_checkpoint()
        checkpoint_input, evidence_bundle = build_checkpoint_and_evidence(state)

        judgment = asyncio.run(
            scheduler.generate_self_check_judgment("reviewer", checkpoint_input, evidence_bundle, state)
        )

        self.assertEqual(judgment.severity, "major")
        self.assertTrue(judgment.blocker)
        self.assertEqual(judgment.used_signal_keys, ("evidence.has_validation_signal",))
        self.assertEqual(len(judgment.source_anchors), 1)
        self.assertEqual(judgment.source_anchors[0].signal_key, "evidence.has_validation_signal")
        self.assertEqual(judgment.source_anchors[0].matched_refs, ("ctx-1",))

    def test_sleeping_agent_does_not_participate_in_heartbeat(self) -> None:
        planner = StubAgent(
            summary_text="planner draft",
            self_check_payload={
                "decision": "approve",
                "rationale_text": "Current candidate is sufficient.",
            },
        )
        reviewer = StubAgent(
            summary_text="reviewer note",
            self_check_payload={
                "decision": "reject",
                "rationale_text": "One requirement is still missing.",
                "deficiency_category": "incompleteness",
            },
        )
        scheduler = Scheduler(agents={"planner": planner, "reviewer": reviewer})
        state = ExecutionState(
            workflow_id="wf-1",
            goal="test goal",
            participant_agent_ids=("planner", "reviewer"),
        )
        state.publish_candidate_from_discussion(
            summary_text="candidate summary",
            source_agent_id="planner",
        )
        state.set_participant_status("reviewer", ParticipantStatus.SLEEPING)
        state.enter_heartbeat_checkpoint()
        checkpoint_input, evidence_bundle = build_checkpoint_and_evidence(state)

        assessment = asyncio.run(scheduler.evaluate_heartbeat_checkpoint(checkpoint_input, state))

        self.assertEqual(tuple(judgment.agent_id for judgment in assessment.judgments), ("planner",))
        self.assertEqual(assessment.evidence_bundle.evidence_bundle_id, evidence_bundle.evidence_bundle_id)
        self.assertEqual(planner.self_check_calls, 1)
        self.assertEqual(reviewer.self_check_calls, 0)

    def test_non_sleeping_agents_participate_in_heartbeat(self) -> None:
        planner = StubAgent(
            summary_text="planner draft",
            self_check_payload={
                "decision": "approve",
                "rationale_text": "Current candidate is sufficient.",
            },
        )
        reviewer = StubAgent(
            summary_text="reviewer note",
            self_check_payload={
                "decision": "reject",
                "rationale_text": "One requirement is still missing.",
                "deficiency_category": "incompleteness",
            },
        )
        scheduler = Scheduler(agents={"planner": planner, "reviewer": reviewer})
        state = ExecutionState(
            workflow_id="wf-1",
            goal="test goal",
            participant_agent_ids=("planner", "reviewer"),
        )
        state.publish_candidate_from_discussion(
            summary_text="candidate summary",
            source_agent_id="planner",
        )
        state.enter_heartbeat_checkpoint()
        checkpoint_input, evidence_bundle = build_checkpoint_and_evidence(state)

        assessment = asyncio.run(scheduler.evaluate_heartbeat_checkpoint(checkpoint_input, state))

        self.assertEqual(
            tuple(judgment.agent_id for judgment in assessment.judgments),
            ("planner", "reviewer"),
        )
        self.assertEqual(assessment.evidence_bundle.evidence_bundle_id, evidence_bundle.evidence_bundle_id)
        self.assertEqual(planner.self_check_calls, 1)
        self.assertEqual(reviewer.self_check_calls, 1)

    def test_empty_participants_returns_continue(self) -> None:
        planner = StubAgent(
            summary_text="planner draft",
            self_check_payload={
                "decision": "approve",
                "rationale_text": "Current candidate is sufficient.",
            },
        )
        scheduler = Scheduler(agents={"planner": planner})
        state = ExecutionState(
            workflow_id="wf-1",
            goal="test goal",
            participant_agent_ids=("planner",),
        )
        state.publish_candidate_from_discussion(
            summary_text="candidate summary",
            source_agent_id="planner",
        )
        state.set_participant_status("planner", ParticipantStatus.SLEEPING)
        state.enter_heartbeat_checkpoint()
        checkpoint_input, evidence_bundle = build_checkpoint_and_evidence(state)

        assessment = asyncio.run(scheduler.evaluate_heartbeat_checkpoint(checkpoint_input, state))

        self.assertEqual(assessment.judgments, ())
        self.assertEqual(assessment.evidence_bundle.evidence_bundle_id, evidence_bundle.evidence_bundle_id)
        self.assertEqual(assessment.aggregate.total_judgments, 0)
        self.assertEqual(assessment.aggregate.approval_count, 0)
        self.assertEqual(assessment.aggregate.recommended_outcome, ConvergenceStatus.CONTINUE)
        self.assertEqual(assessment.resolution.value, "resume_discussion")
        self.assertEqual(planner.self_check_calls, 0)
        assert_terminal_consumption_attached(self, assessment.aggregate)

    def test_reject_judgment_defaults_missing_deficiency_category(self) -> None:
        scheduler = Scheduler(
            agents={
                "reviewer": StubAgent(
                    summary_text="reviewer draft",
                    self_check_payload={
                        "decision": "reject",
                        "rationale_text": "A required element is still missing.",
                    },
                )
            }
        )
        state = ExecutionState(
            workflow_id="wf-1",
            goal="test goal",
            participant_agent_ids=("reviewer",),
        )
        state.publish_candidate_from_discussion(
            summary_text="candidate summary",
            source_agent_id="reviewer",
        )
        state.enter_heartbeat_checkpoint()
        checkpoint_input, evidence_bundle = build_checkpoint_and_evidence(state)

        judgment = asyncio.run(
            scheduler.generate_self_check_judgment("reviewer", checkpoint_input, evidence_bundle, state)
        )

        self.assertEqual(judgment.decision, HeartbeatVoteChoice.REJECT)
        self.assertEqual(judgment.deficiency_category, RejectionDeficiencyCategory.OTHER)

    def test_discussion_phase_cannot_generate_self_check_judgment(self) -> None:
        scheduler = Scheduler(agents={"planner": StubAgent(summary_text="planner draft")})
        state = ExecutionState(workflow_id="wf-1", goal="test goal")
        checkpoint_input = HeartbeatCheckpointInput(
            checkpoint_id="checkpoint-1",
            workflow_id="wf-1",
            original_goal="test goal",
            frozen_candidate_id="candidate-1",
            frozen_candidate_summary="candidate summary",
        )
        evidence_bundle = HeartbeatEvidenceBundle.create(
            checkpoint_id="checkpoint-1",
            candidate_id="candidate-1",
            original_goal="test goal",
            candidate_summary="candidate summary",
        )

        with self.assertRaises(RuntimeError):
            asyncio.run(
                scheduler.generate_self_check_judgment(
                    "planner",
                    checkpoint_input,
                    evidence_bundle,
                    state,
                )
            )

    def test_aggregate_result_counts_and_continue_when_threshold_not_met(self) -> None:
        scheduler = Scheduler(
            agents={},
            options=SchedulerOptions(thresholds=threshold_profile(support_ratio_threshold=1.0)),
        )
        evidence_bundle_id = "evidence-1"
        checkpoint_input = HeartbeatCheckpointInput(
            checkpoint_id="checkpoint-1",
            workflow_id="wf-1",
            original_goal="test goal",
            frozen_candidate_id="candidate-1",
            frozen_candidate_summary="candidate summary",
        )
        judgments = (
            HeartbeatAgentJudgment.create(
                checkpoint_id="checkpoint-1",
                agent_id="planner",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle_id,
                decision=HeartbeatVoteChoice.APPROVE,
                rationale_text="Sufficient for the stated goal.",
            ),
            HeartbeatAgentJudgment.create(
                checkpoint_id="checkpoint-1",
                agent_id="reviewer",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Missing one important requirement.",
                deficiency_category=RejectionDeficiencyCategory.INCOMPLETENESS,
            ),
        )

        aggregate = scheduler.aggregate_heartbeat_judgments(checkpoint_input, judgments)

        self.assertEqual(aggregate.total_judgments, 2)
        self.assertEqual(aggregate.approval_count, 1)
        self.assertEqual(aggregate.rejection_count, 1)
        self.assertEqual(aggregate.approval_ratio, 0.5)
        self.assertEqual(aggregate.rejection_ratio, 0.5)
        self.assertEqual(aggregate.aggregate_result_id, "checkpoint-1:aggregate")
        self.assertIsNotNone(aggregate.aggregate_artifact)
        self.assertEqual(
            aggregate.dominant_deficiency_categories,
            (RejectionDeficiencyCategory.INCOMPLETENESS,),
        )
        self.assertEqual(aggregate.recommended_outcome, ConvergenceStatus.CONTINUE)

    def test_aggregate_result_returns_converged_when_threshold_met(self) -> None:
        scheduler = Scheduler(
            agents={},
            options=SchedulerOptions(thresholds=threshold_profile(support_ratio_threshold=1.0)),
        )
        evidence_bundle_id = "evidence-1"
        checkpoint_input = HeartbeatCheckpointInput(
            checkpoint_id="checkpoint-1",
            workflow_id="wf-1",
            original_goal="test goal",
            frozen_candidate_id="candidate-1",
            frozen_candidate_summary="candidate summary",
        )
        judgments = (
            HeartbeatAgentJudgment.create(
                checkpoint_id="checkpoint-1",
                agent_id="planner",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle_id,
                decision=HeartbeatVoteChoice.APPROVE,
                rationale_text="Sufficient for the stated goal.",
            ),
            HeartbeatAgentJudgment.create(
                checkpoint_id="checkpoint-1",
                agent_id="reviewer",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle_id,
                decision=HeartbeatVoteChoice.APPROVE,
                rationale_text="No material deficiency remains.",
            ),
        )

        aggregate = scheduler.aggregate_heartbeat_judgments(checkpoint_input, judgments)

        self.assertEqual(aggregate.approval_count, 2)
        self.assertEqual(aggregate.approval_ratio, 1.0)
        self.assertEqual(aggregate.recommended_outcome, ConvergenceStatus.CONVERGED)
        self.assertIsNotNone(aggregate.aggregate_artifact)

    def test_aggregate_artifact_merges_same_deficiency_category_across_roles(self) -> None:
        scheduler = Scheduler(
            agents={},
            options=SchedulerOptions(thresholds=threshold_profile(support_ratio_threshold=1.0)),
        )
        checkpoint_input = HeartbeatCheckpointInput(
            checkpoint_id="checkpoint-1",
            workflow_id="wf-1",
            original_goal="test goal",
            frozen_candidate_id="candidate-1",
            frozen_candidate_summary="candidate summary",
        )
        evidence_bundle = build_manual_evidence_bundle(
            coverage_signals={
                "source_fields": ("candidate_summary", "structured_content"),
                "matched_refs": (),
                "derived_from_summary": True,
                "derived_from_structured_content": True,
                "derived_from_payload": False,
            },
            implementation_signals={
                "source_fields": ("candidate_summary", "payload"),
                "matched_refs": (),
                "derived_from_summary": True,
                "derived_from_structured_content": False,
                "derived_from_payload": True,
            },
        )
        judgments = (
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-planner",
                checkpoint_id="checkpoint-1",
                agent_id="planner",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Plan closure is not explicit.",
                deficiency_category=RejectionDeficiencyCategory.INCOMPLETENESS,
                used_signal_keys=("coverage.has_plan_structure",),
                metadata={"agent_role": "planner"},
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-executor",
                checkpoint_id="checkpoint-1",
                agent_id="executor",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Execution path is not grounded.",
                deficiency_category=RejectionDeficiencyCategory.INCOMPLETENESS,
                used_signal_keys=("implementation.has_execution_path",),
                metadata={"agent_role": "executor"},
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-reviewer",
                checkpoint_id="checkpoint-1",
                agent_id="reviewer",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.APPROVE,
                rationale_text="No material deficiency remains.",
                metadata={"agent_role": "reviewer"},
            ),
        )

        aggregate = scheduler.aggregate_heartbeat_judgments(
            checkpoint_input,
            judgments,
            evidence_bundle=evidence_bundle,
        )

        item = find_artifact_item(
            aggregate.aggregate_artifact,
            RejectionDeficiencyCategory.INCOMPLETENESS,
        )
        self.assertEqual(item.supporting_roles, ("executor", "planner"))
        self.assertEqual(item.dissenting_roles, ("reviewer",))
        self.assertEqual(item.judgment_ids, ("judgment-executor", "judgment-planner"))
        self.assertIn("executor: Execution path is not grounded.", item.summary)
        self.assertIn("planner: Plan closure is not explicit.", item.summary)

    def test_aggregate_artifact_deduplicates_and_stably_sorts_used_signal_keys(self) -> None:
        scheduler = Scheduler(
            agents={},
            options=SchedulerOptions(thresholds=threshold_profile(support_ratio_threshold=1.0)),
        )
        checkpoint_input = HeartbeatCheckpointInput(
            checkpoint_id="checkpoint-1",
            workflow_id="wf-1",
            original_goal="test goal",
            frozen_candidate_id="candidate-1",
            frozen_candidate_summary="candidate summary",
        )
        evidence_bundle = build_manual_evidence_bundle()
        judgments = (
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-1",
                checkpoint_id="checkpoint-1",
                agent_id="planner",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Plan closure is not explicit.",
                deficiency_category=RejectionDeficiencyCategory.INCOMPLETENESS,
                used_signal_keys=(
                    "implementation.has_execution_path",
                    "coverage.has_plan_structure",
                    "implementation.has_execution_path",
                ),
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-2",
                checkpoint_id="checkpoint-1",
                agent_id="executor",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Execution path is not grounded.",
                deficiency_category=RejectionDeficiencyCategory.INCOMPLETENESS,
                used_signal_keys=(
                    "coverage.has_plan_structure",
                    "constraint.has_constraints",
                ),
            ),
        )

        aggregate = scheduler.aggregate_heartbeat_judgments(
            checkpoint_input,
            judgments,
            evidence_bundle=evidence_bundle,
        )

        item = find_artifact_item(
            aggregate.aggregate_artifact,
            RejectionDeficiencyCategory.INCOMPLETENESS,
        )
        self.assertEqual(
            item.used_signal_keys,
            (
                "constraint.has_constraints",
                "coverage.has_plan_structure",
                "implementation.has_execution_path",
            ),
        )

    def test_aggregate_artifact_deduplicates_and_retains_source_anchors(self) -> None:
        scheduler = Scheduler(
            agents={},
            options=SchedulerOptions(thresholds=threshold_profile(support_ratio_threshold=1.0)),
        )
        checkpoint_input = HeartbeatCheckpointInput(
            checkpoint_id="checkpoint-1",
            workflow_id="wf-1",
            original_goal="test goal",
            frozen_candidate_id="candidate-1",
            frozen_candidate_summary="candidate summary",
        )
        evidence_bundle = build_manual_evidence_bundle(
            coverage_signals={
                "source_fields": ("candidate_summary", "structured_content"),
                "matched_refs": ("ctx-1",),
                "derived_from_summary": True,
                "derived_from_structured_content": True,
                "derived_from_payload": False,
            }
        )
        judgments = (
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-1",
                checkpoint_id="checkpoint-1",
                agent_id="planner",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Plan closure is not explicit.",
                deficiency_category=RejectionDeficiencyCategory.INCOMPLETENESS,
                used_signal_keys=("coverage.has_plan_structure", "coverage.has_plan_structure"),
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-2",
                checkpoint_id="checkpoint-1",
                agent_id="reviewer",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="One requirement is still missing.",
                deficiency_category=RejectionDeficiencyCategory.INCOMPLETENESS,
                used_signal_keys=("coverage.has_plan_structure",),
            ),
        )

        aggregate = scheduler.aggregate_heartbeat_judgments(
            checkpoint_input,
            judgments,
            evidence_bundle=evidence_bundle,
        )

        item = find_artifact_item(
            aggregate.aggregate_artifact,
            RejectionDeficiencyCategory.INCOMPLETENESS,
        )
        self.assertEqual(len(item.source_anchors), 1)
        self.assertEqual(item.source_anchors[0].signal_key, "coverage.has_plan_structure")
        self.assertEqual(item.source_anchors[0].source_fields, ("candidate_summary", "structured_content"))
        self.assertEqual(item.source_anchors[0].matched_refs, ("ctx-1",))

    def test_aggregate_artifact_legacy_metadata_fallback_still_works(self) -> None:
        scheduler = Scheduler(
            agents={},
            options=SchedulerOptions(thresholds=threshold_profile(support_ratio_threshold=1.0)),
        )
        checkpoint_input = HeartbeatCheckpointInput(
            checkpoint_id="checkpoint-1",
            workflow_id="wf-1",
            original_goal="test goal",
            frozen_candidate_id="candidate-1",
            frozen_candidate_summary="candidate summary",
        )
        evidence_bundle = build_manual_evidence_bundle()
        judgments = (
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-reviewer",
                checkpoint_id="checkpoint-1",
                agent_id="reviewer",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Validation evidence is not explicit.",
                deficiency_category=RejectionDeficiencyCategory.EVIDENCE_GAP,
                metadata={
                    "severity": "high",
                    "blocker": True,
                    "used_signal_keys": ("evidence.has_validation_signal",),
                    "source_anchors": (
                        {
                            "signal_key": "evidence.has_validation_signal",
                            "signal_family": "evidence",
                            "source_fields": ("candidate_summary", "payload"),
                            "matched_refs": ("ctx-legacy",),
                            "derived_from_summary": True,
                            "derived_from_payload": True,
                        },
                    ),
                    "agent_role": "reviewer",
                },
            ),
        )

        aggregate = scheduler.aggregate_heartbeat_judgments(
            checkpoint_input,
            judgments,
            evidence_bundle=evidence_bundle,
        )

        item = find_artifact_item(
            aggregate.aggregate_artifact,
            RejectionDeficiencyCategory.EVIDENCE_GAP,
        )
        self.assertEqual(item.severity, "major")
        self.assertTrue(item.blocker)
        self.assertEqual(item.used_signal_keys, ("evidence.has_validation_signal",))
        self.assertEqual(len(item.source_anchors), 1)
        self.assertEqual(item.source_anchors[0].signal_key, "evidence.has_validation_signal")
        self.assertEqual(item.source_anchors[0].matched_refs, ("ctx-legacy",))
        payload = build_heartbeat_report_payload(aggregate)
        self.assertEqual(payload.highest_rejection_severity, "major")
        self.assertEqual(payload.blocker_count, 1)
        self.assertEqual(payload.blocker_roles, ("reviewer",))
        self.assertEqual(payload.severity_histogram, {"major": 1})
        self.assertEqual(payload.consensus_items[0].severity, "major")

    def test_aggregate_artifact_consumes_formal_fields_from_role_specific_producer(self) -> None:
        reviewer = make_role_agent(ReviewerAgent, agent_id="reviewer", name="Reviewer")
        scheduler = Scheduler(agents={"reviewer": reviewer})
        state = ExecutionState(
            workflow_id="wf-1",
            goal="validate the frozen candidate for correctness and evidence",
            participant_agent_ids=("reviewer",),
        )
        state.publish_candidate_from_discussion(
            summary_text="This candidate is unsupported and missing evidence.",
            source_agent_id="reviewer",
        )
        state.enter_heartbeat_checkpoint()
        checkpoint_input, evidence_bundle = build_checkpoint_and_evidence(state)

        judgment = asyncio.run(
            scheduler.generate_self_check_judgment("reviewer", checkpoint_input, evidence_bundle, state)
        )
        aggregate = scheduler.aggregate_heartbeat_judgments(
            checkpoint_input,
            (judgment,),
            evidence_bundle=evidence_bundle,
        )

        item = find_artifact_item(
            aggregate.aggregate_artifact,
            RejectionDeficiencyCategory.EVIDENCE_GAP,
        )
        self.assertEqual(item.severity, judgment.severity)
        self.assertEqual(item.blocker, judgment.blocker)
        self.assertEqual(item.used_signal_keys, judgment.used_signal_keys)
        self.assertEqual(
            tuple(anchor.signal_key for anchor in item.source_anchors),
            tuple(anchor.signal_key for anchor in judgment.source_anchors),
        )
        self.assertEqual(aggregate.highest_rejection_severity, "major")
        self.assertEqual(aggregate.blocker_count, 0)
        self.assertEqual(aggregate.blocker_roles, ())
        self.assertEqual(aggregate.severity_histogram, {"major": 1})

    def test_aggregate_artifact_mixed_formal_and_legacy_paths_remain_deterministic(self) -> None:
        scheduler = Scheduler(
            agents={},
            options=SchedulerOptions(thresholds=threshold_profile(support_ratio_threshold=1.0)),
        )
        checkpoint_input = HeartbeatCheckpointInput(
            checkpoint_id="checkpoint-1",
            workflow_id="wf-1",
            original_goal="test goal",
            frozen_candidate_id="candidate-1",
            frozen_candidate_summary="candidate summary",
        )
        evidence_bundle = build_manual_evidence_bundle()
        judgments = (
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-executor",
                checkpoint_id="checkpoint-1",
                agent_id="executor",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Execution path is not grounded.",
                deficiency_category=RejectionDeficiencyCategory.INCOMPLETENESS,
                severity="medium",
                used_signal_keys=("implementation.has_execution_path",),
                source_anchors=(
                    HeartbeatSourceAnchor(
                        signal_key="implementation.has_execution_path",
                        signal_family="implementation",
                        source_fields=("candidate_summary",),
                        matched_refs=("ctx-formal",),
                        derived_from_summary=True,
                    ),
                ),
                metadata={"agent_role": "executor"},
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-planner",
                checkpoint_id="checkpoint-1",
                agent_id="planner",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Plan closure is not explicit.",
                deficiency_category=RejectionDeficiencyCategory.INCOMPLETENESS,
                metadata={
                    "used_signal_keys": ("constraint.has_constraints",),
                    "source_anchors": (
                        {
                            "signal_key": "constraint.has_constraints",
                            "signal_family": "constraint",
                            "source_fields": ("candidate_summary", "structured_content"),
                            "matched_refs": ("ctx-legacy",),
                            "derived_from_summary": True,
                            "derived_from_structured_content": True,
                        },
                    ),
                    "agent_role": "planner",
                },
            ),
        )

        aggregate = scheduler.aggregate_heartbeat_judgments(
            checkpoint_input,
            judgments,
            evidence_bundle=evidence_bundle,
        )

        item = find_artifact_item(
            aggregate.aggregate_artifact,
            RejectionDeficiencyCategory.INCOMPLETENESS,
        )
        self.assertEqual(item.supporting_roles, ("executor", "planner"))
        self.assertEqual(
            item.used_signal_keys,
            ("constraint.has_constraints", "implementation.has_execution_path"),
        )
        self.assertEqual(
            tuple(anchor.signal_key for anchor in item.source_anchors),
            ("constraint.has_constraints", "implementation.has_execution_path"),
        )
        self.assertEqual(item.judgment_ids, ("judgment-executor", "judgment-planner"))

    def test_aggregate_artifact_preserves_minority_dissent(self) -> None:
        scheduler = Scheduler(
            agents={},
            options=SchedulerOptions(thresholds=threshold_profile(support_ratio_threshold=0.6)),
        )
        checkpoint_input = HeartbeatCheckpointInput(
            checkpoint_id="checkpoint-1",
            workflow_id="wf-1",
            original_goal="test goal",
            frozen_candidate_id="candidate-1",
            frozen_candidate_summary="candidate summary",
        )
        evidence_bundle = build_manual_evidence_bundle(
            risk_signals={
                "source_fields": ("candidate_summary",),
                "matched_refs": (),
                "derived_from_summary": True,
                "derived_from_structured_content": False,
                "derived_from_payload": False,
            }
        )
        judgments = (
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-1",
                checkpoint_id="checkpoint-1",
                agent_id="planner",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.APPROVE,
                rationale_text="Sufficient for the stated goal.",
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-2",
                checkpoint_id="checkpoint-1",
                agent_id="executor",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.APPROVE,
                rationale_text="Execution path and dependencies are grounded.",
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-3",
                checkpoint_id="checkpoint-1",
                agent_id="reviewer",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Unresolved correctness risk is explicit.",
                deficiency_category=RejectionDeficiencyCategory.CORRECTNESS_RISK,
                used_signal_keys=("risk.has_risk_marker",),
            ),
        )

        aggregate = scheduler.aggregate_heartbeat_judgments(
            checkpoint_input,
            judgments,
            evidence_bundle=evidence_bundle,
        )

        self.assertEqual(aggregate.recommended_outcome, ConvergenceStatus.CONVERGED)
        minority_item = find_artifact_item(
            aggregate.aggregate_artifact,
            RejectionDeficiencyCategory.CORRECTNESS_RISK,
        )
        self.assertEqual(aggregate.aggregate_artifact.minority_items, (minority_item,))
        self.assertIn("correctness_risk", aggregate.dissent_summary)

    def test_aggregate_artifact_orders_items_by_grading_priority(self) -> None:
        scheduler = Scheduler(
            agents={},
            options=SchedulerOptions(thresholds=threshold_profile(support_ratio_threshold=1.0)),
        )
        checkpoint_input = HeartbeatCheckpointInput(
            checkpoint_id="checkpoint-1",
            workflow_id="wf-1",
            original_goal="test goal",
            frozen_candidate_id="candidate-1",
            frozen_candidate_summary="candidate summary",
        )
        evidence_bundle = build_manual_evidence_bundle()
        judgments = (
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-planner",
                checkpoint_id="checkpoint-1",
                agent_id="planner",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="The implementation path is still incomplete.",
                deficiency_category=RejectionDeficiencyCategory.INCOMPLETENESS,
                severity="moderate",
                blocker=True,
                metadata={"agent_role": "planner"},
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-executor",
                checkpoint_id="checkpoint-1",
                agent_id="executor",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Execution cannot proceed yet.",
                deficiency_category=RejectionDeficiencyCategory.INCOMPLETENESS,
                severity="moderate",
                blocker=True,
                metadata={"agent_role": "executor"},
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-reviewer",
                checkpoint_id="checkpoint-1",
                agent_id="reviewer",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Evidence support is still thin.",
                deficiency_category=RejectionDeficiencyCategory.EVIDENCE_GAP,
                severity="major",
                blocker=False,
                metadata={"agent_role": "reviewer"},
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-qa",
                checkpoint_id="checkpoint-1",
                agent_id="qa",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Validation evidence is still incomplete.",
                deficiency_category=RejectionDeficiencyCategory.EVIDENCE_GAP,
                severity="major",
                blocker=False,
                metadata={"agent_role": "qa"},
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-editor",
                checkpoint_id="checkpoint-1",
                agent_id="editor",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="The current wording is still ambiguous.",
                deficiency_category=RejectionDeficiencyCategory.CLARITY_GAP,
                severity="moderate",
                blocker=False,
                metadata={"agent_role": "editor"},
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-lead",
                checkpoint_id="checkpoint-1",
                agent_id="lead",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.APPROVE,
                rationale_text="The current candidate is close enough to review.",
                metadata={"agent_role": "lead"},
            ),
        )

        aggregate = scheduler.aggregate_heartbeat_judgments(
            checkpoint_input,
            judgments,
            evidence_bundle=evidence_bundle,
        )
        artifact = aggregate.aggregate_artifact

        self.assertEqual(
            tuple(item.category for item in artifact.unresolved_items),
            (
                RejectionDeficiencyCategory.INCOMPLETENESS,
                RejectionDeficiencyCategory.EVIDENCE_GAP,
                RejectionDeficiencyCategory.CLARITY_GAP,
            ),
        )
        self.assertEqual(
            tuple(item.category for item in artifact.consensus_items),
            (
                RejectionDeficiencyCategory.INCOMPLETENESS,
                RejectionDeficiencyCategory.EVIDENCE_GAP,
            ),
        )
        self.assertEqual(
            tuple(item.category for item in artifact.minority_items),
            (
                RejectionDeficiencyCategory.CLARITY_GAP,
                RejectionDeficiencyCategory.SUFFICIENT,
            ),
        )
        self.assertEqual(
            tuple(item.priority_rank for item in artifact.unresolved_items),
            (1, 2, 3),
        )
        incompleteness_item = find_artifact_item(
            artifact,
            RejectionDeficiencyCategory.INCOMPLETENESS,
        )
        self.assertEqual(
            incompleteness_item.judgment_ids,
            ("judgment-executor", "judgment-planner"),
        )
        self.assertTrue(
            any(
                "prioritized blocker deficiencies remain unresolved" in rationale
                for rationale in artifact.decision_rationale
            )
        )

    def test_decision_rationale_explains_converged_non_blocking_rejects(self) -> None:
        scheduler = Scheduler(
            agents={},
            options=SchedulerOptions(thresholds=threshold_profile(support_ratio_threshold=0.6)),
        )
        checkpoint_input = HeartbeatCheckpointInput(
            checkpoint_id="checkpoint-1",
            workflow_id="wf-1",
            original_goal="test goal",
            frozen_candidate_id="candidate-1",
            frozen_candidate_summary="candidate summary",
        )
        evidence_bundle = build_manual_evidence_bundle(
            risk_signals={
                "source_fields": ("candidate_summary",),
                "matched_refs": (),
                "derived_from_summary": True,
                "derived_from_structured_content": False,
                "derived_from_payload": False,
            }
        )
        judgments = (
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-1",
                checkpoint_id="checkpoint-1",
                agent_id="planner",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.APPROVE,
                rationale_text="The plan is sufficient.",
                metadata={"agent_role": "planner"},
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-2",
                checkpoint_id="checkpoint-1",
                agent_id="executor",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.APPROVE,
                rationale_text="Execution is grounded.",
                metadata={"agent_role": "executor"},
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-3",
                checkpoint_id="checkpoint-1",
                agent_id="reviewer",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="A remaining risk should still be noted.",
                deficiency_category=RejectionDeficiencyCategory.CORRECTNESS_RISK,
                severity="major",
                blocker=False,
                used_signal_keys=("risk.has_risk_marker",),
                metadata={"agent_role": "reviewer"},
            ),
        )

        aggregate = scheduler.aggregate_heartbeat_judgments(
            checkpoint_input,
            judgments,
            evidence_bundle=evidence_bundle,
        )

        self.assertEqual(aggregate.recommended_outcome, ConvergenceStatus.CONVERGED)
        self.assertTrue(
            any(
                "none were blocker-marked; highest rejection severity was major"
                in rationale
                for rationale in aggregate.aggregate_artifact.decision_rationale
            )
        )

    def test_recommended_next_actions_prioritize_blocker_then_high_severity(self) -> None:
        scheduler = Scheduler(
            agents={},
            options=SchedulerOptions(thresholds=threshold_profile(support_ratio_threshold=1.0)),
        )
        checkpoint_input = HeartbeatCheckpointInput(
            checkpoint_id="checkpoint-1",
            workflow_id="wf-1",
            original_goal="test goal",
            frozen_candidate_id="candidate-1",
            frozen_candidate_summary="candidate summary",
        )
        evidence_bundle = build_manual_evidence_bundle()
        judgments = (
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-executor",
                checkpoint_id="checkpoint-1",
                agent_id="executor",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Execution cannot proceed yet.",
                deficiency_category=RejectionDeficiencyCategory.INCOMPLETENESS,
                severity="critical",
                blocker=True,
                metadata={"agent_role": "executor"},
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-reviewer",
                checkpoint_id="checkpoint-1",
                agent_id="reviewer",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Evidence support is still thin.",
                deficiency_category=RejectionDeficiencyCategory.EVIDENCE_GAP,
                severity="major",
                blocker=False,
                metadata={"agent_role": "reviewer"},
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-editor",
                checkpoint_id="checkpoint-1",
                agent_id="editor",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="The current wording is still ambiguous.",
                deficiency_category=RejectionDeficiencyCategory.CLARITY_GAP,
                severity="moderate",
                blocker=False,
                metadata={"agent_role": "editor"},
            ),
        )

        aggregate = scheduler.aggregate_heartbeat_judgments(
            checkpoint_input,
            judgments,
            evidence_bundle=evidence_bundle,
        )

        self.assertEqual(
            aggregate.aggregate_artifact.recommended_next_actions[0],
            "Resolve blocker incompleteness (critical) before the next heartbeat; supported by executor.",
        )
        self.assertEqual(
            aggregate.aggregate_artifact.recommended_next_actions[1],
            "Address high-severity evidence_gap (major) before the next heartbeat; supported by reviewer.",
        )

    def test_formal_severity_blocker_and_source_anchors_override_metadata_in_aggregate_artifact(
        self,
    ) -> None:
        scheduler = Scheduler(
            agents={},
            options=SchedulerOptions(thresholds=threshold_profile(support_ratio_threshold=1.0)),
        )
        checkpoint_input = HeartbeatCheckpointInput(
            checkpoint_id="checkpoint-1",
            workflow_id="wf-1",
            original_goal="test goal",
            frozen_candidate_id="candidate-1",
            frozen_candidate_summary="candidate summary",
        )
        evidence_bundle = build_manual_evidence_bundle(
            evidence_signals={
                "source_fields": ("candidate_summary", "payload"),
                "matched_refs": ("ctx-2",),
                "derived_from_summary": True,
                "derived_from_structured_content": False,
                "derived_from_payload": True,
            }
        )
        judgments = (
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-reviewer",
                checkpoint_id="checkpoint-1",
                agent_id="reviewer",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Validation evidence is not explicit.",
                deficiency_category=RejectionDeficiencyCategory.EVIDENCE_GAP,
                severity="high",
                blocker=True,
                used_signal_keys=("evidence.has_validation_signal",),
                source_anchors=(
                    HeartbeatSourceAnchor(
                        signal_key="evidence.has_validation_signal",
                        signal_family="evidence",
                        source_fields=("candidate_summary",),
                        matched_refs=("ctx-formal",),
                        derived_from_summary=True,
                    ),
                ),
                metadata={
                    "severity": "low",
                    "blocker": False,
                    "source_anchors": (
                        {
                            "signal_key": "risk.has_risk_marker",
                            "signal_family": "risk",
                            "source_fields": ("payload",),
                            "matched_refs": ("ctx-metadata",),
                            "derived_from_payload": True,
                        },
                    ),
                    "agent_role": "reviewer",
                },
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-planner",
                checkpoint_id="checkpoint-1",
                agent_id="planner",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.APPROVE,
                rationale_text="Sufficient for the stated goal.",
                metadata={"agent_role": "planner"},
            ),
        )

        aggregate = scheduler.aggregate_heartbeat_judgments(
            checkpoint_input,
            judgments,
            evidence_bundle=evidence_bundle,
        )

        item = find_artifact_item(
            aggregate.aggregate_artifact,
            RejectionDeficiencyCategory.EVIDENCE_GAP,
        )
        self.assertTrue(item.blocker)
        self.assertEqual(item.severity, "major")
        self.assertEqual(aggregate.aggregate_artifact.unresolved_items, (item,))
        self.assertEqual(len(item.source_anchors), 1)
        self.assertEqual(item.source_anchors[0].signal_key, "evidence.has_validation_signal")
        self.assertEqual(item.source_anchors[0].matched_refs, ("ctx-formal",))
        self.assertTrue(
            any(
                "Blocker deficiencies were flagged" in rationale
                for rationale in aggregate.aggregate_artifact.decision_rationale
            )
        )

    def test_heartbeat_report_payload_projects_continue_aggregate_result(self) -> None:
        scheduler = Scheduler(
            agents={},
            options=SchedulerOptions(thresholds=threshold_profile(support_ratio_threshold=1.0)),
        )
        checkpoint_input = HeartbeatCheckpointInput(
            checkpoint_id="checkpoint-1",
            workflow_id="wf-1",
            original_goal="test goal",
            frozen_candidate_id="candidate-1",
            frozen_candidate_summary="candidate summary",
        )
        evidence_bundle = build_manual_evidence_bundle(
            coverage_signals={
                "source_fields": ("candidate_summary", "structured_content"),
                "matched_refs": (),
                "derived_from_summary": True,
                "derived_from_structured_content": True,
                "derived_from_payload": False,
            },
            implementation_signals={
                "source_fields": ("candidate_summary",),
                "matched_refs": (),
                "derived_from_summary": True,
                "derived_from_structured_content": False,
                "derived_from_payload": False,
            },
        )
        judgments = (
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-planner",
                checkpoint_id="checkpoint-1",
                agent_id="planner",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Plan closure is not explicit.",
                deficiency_category=RejectionDeficiencyCategory.INCOMPLETENESS,
                severity="moderate",
                used_signal_keys=("coverage.has_plan_structure",),
                metadata={"agent_role": "planner"},
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-executor",
                checkpoint_id="checkpoint-1",
                agent_id="executor",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Execution path is not grounded.",
                deficiency_category=RejectionDeficiencyCategory.INCOMPLETENESS,
                severity="major",
                used_signal_keys=("implementation.has_execution_path",),
                metadata={"agent_role": "executor"},
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-reviewer",
                checkpoint_id="checkpoint-1",
                agent_id="reviewer",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.APPROVE,
                rationale_text="No material deficiency remains.",
                metadata={"agent_role": "reviewer"},
            ),
        )

        aggregate = scheduler.aggregate_heartbeat_judgments(
            checkpoint_input,
            judgments,
            evidence_bundle=evidence_bundle,
        )
        profile = aggregate.convergence_profile
        self.assertIsNotNone(profile)
        payload = build_heartbeat_report_payload(aggregate)

        self.assertEqual(payload.final_decision, "continue")
        self.assertEqual(payload.aggregate_result_id, aggregate.aggregate_result_id)
        self.assertEqual(payload.approval_count, aggregate.approval_count)
        self.assertEqual(payload.rejection_count, aggregate.rejection_count)
        self.assertEqual(payload.highest_rejection_severity, "major")
        self.assertEqual(payload.blocker_count, 1)
        self.assertEqual(payload.blocker_roles, ("executor",))
        self.assertEqual(payload.severity_histogram, {"major": 1, "moderate": 1})
        self.assertEqual(payload.consensus_items[0].category, "incompleteness")
        self.assertEqual(payload.consensus_items[0].supporting_roles, ("executor", "planner"))
        self.assertEqual(
            payload.consensus_items[0].priority_rank,
            aggregate.aggregate_artifact.consensus_items[0].priority_rank,
        )
        self.assertEqual(
            payload.consensus_items[0].judgment_ids,
            aggregate.aggregate_artifact.consensus_items[0].judgment_ids,
        )
        self.assertEqual(
            tuple(anchor.signal_key for anchor in payload.consensus_items[0].source_anchors),
            ("coverage.has_plan_structure", "implementation.has_execution_path"),
        )
        self.assertEqual(
            payload.decision_rationale,
            aggregate.aggregate_artifact.decision_rationale,
        )
        self.assertEqual(
            payload.recommended_next_actions,
            aggregate.aggregate_artifact.recommended_next_actions,
        )
        self.assertIsNotNone(aggregate.candidate_snapshot)
        self.assertEqual(aggregate.candidate_snapshot.summary, "candidate summary")
        self.assertEqual(aggregate.aggregate_artifact.candidate_snapshot, aggregate.candidate_snapshot)
        self.assertIsNotNone(payload.candidate_snapshot)
        self.assertEqual(payload.candidate_snapshot.summary, "candidate summary")
        self.assertIsNotNone(payload.outcome_snapshot)
        self.assertEqual(
            payload.outcome_snapshot.candidate_snapshot,
            payload.candidate_snapshot,
        )
        self.assertIsNotNone(payload.convergence_profile)
        self.assertEqual(payload.convergence_profile.final_decision, "continue")
        self.assertEqual(
            payload.convergence_profile.semantic_state,
            profile.semantic_state.value,
        )
        self.assertEqual(
            payload.convergence_profile.dominant_reason,
            profile.dominant_reason.value,
        )
        self.assertEqual(
            payload.convergence_profile.explanation_summary,
            profile.explanation_summary,
        )

    def test_heartbeat_report_payload_projects_converged_artifact(self) -> None:
        scheduler = Scheduler(
            agents={},
            options=SchedulerOptions(thresholds=threshold_profile(support_ratio_threshold=0.6)),
        )
        checkpoint_input = HeartbeatCheckpointInput(
            checkpoint_id="checkpoint-1",
            workflow_id="wf-1",
            original_goal="test goal",
            frozen_candidate_id="candidate-1",
            frozen_candidate_summary="candidate summary",
        )
        evidence_bundle = build_manual_evidence_bundle(
            risk_signals={
                "source_fields": ("candidate_summary",),
                "matched_refs": (),
                "derived_from_summary": True,
                "derived_from_structured_content": False,
                "derived_from_payload": False,
            }
        )
        judgments = (
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-1",
                checkpoint_id="checkpoint-1",
                agent_id="planner",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.APPROVE,
                rationale_text="Sufficient for the stated goal.",
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-2",
                checkpoint_id="checkpoint-1",
                agent_id="executor",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.APPROVE,
                rationale_text="Execution path and dependencies are grounded.",
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-3",
                checkpoint_id="checkpoint-1",
                agent_id="reviewer",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Unresolved correctness risk is explicit.",
                deficiency_category=RejectionDeficiencyCategory.CORRECTNESS_RISK,
                severity="major",
                blocker=True,
                used_signal_keys=("risk.has_risk_marker",),
                metadata={"agent_role": "reviewer"},
            ),
        )

        aggregate = scheduler.aggregate_heartbeat_judgments(
            checkpoint_input,
            judgments,
            evidence_bundle=evidence_bundle,
        )
        payload = build_heartbeat_report_payload(aggregate.aggregate_artifact)

        self.assertEqual(payload.final_decision, "converged")
        self.assertEqual(payload.aggregate_result_id, aggregate.aggregate_result_id)
        self.assertIsNone(payload.approval_count)
        self.assertEqual(payload.highest_rejection_severity, "major")
        self.assertEqual(payload.blocker_count, 1)
        self.assertEqual(payload.blocker_roles, ("reviewer",))
        self.assertEqual(payload.severity_histogram, {"major": 1})
        self.assertEqual(payload.consensus_items[0].category, "sufficient")
        self.assertEqual(payload.minority_items[0].category, "correctness_risk")
        self.assertEqual(
            tuple(anchor.signal_key for anchor in payload.minority_items[0].source_anchors),
            ("risk.has_risk_marker",),
        )
        self.assertEqual(
            payload.decision_rationale,
            aggregate.aggregate_artifact.decision_rationale,
        )
        self.assertEqual(
            payload.recommended_next_actions,
            aggregate.aggregate_artifact.recommended_next_actions,
        )
        self.assertIsNotNone(payload.candidate_snapshot)
        self.assertEqual(payload.candidate_snapshot.summary, "candidate summary")
        self.assertIsNotNone(payload.outcome_snapshot)
        self.assertEqual(
            payload.outcome_snapshot.candidate_snapshot,
            payload.candidate_snapshot,
        )
        self.assertIsNotNone(payload.convergence_profile)
        self.assertEqual(payload.convergence_profile.final_decision, "converged")
        self.assertEqual(
            payload.convergence_profile.semantic_state,
            aggregate.aggregate_artifact.convergence_profile.semantic_state.value,
        )
        self.assertEqual(
            payload.convergence_profile.dominant_reason,
            aggregate.aggregate_artifact.convergence_profile.dominant_reason.value,
        )

    def test_continue_profile_classifies_blocker_semantics(self) -> None:
        scheduler = Scheduler(
            agents={},
            options=SchedulerOptions(thresholds=threshold_profile(support_ratio_threshold=1.0)),
        )
        checkpoint_input = HeartbeatCheckpointInput(
            checkpoint_id="checkpoint-1",
            workflow_id="wf-1",
            original_goal="test goal",
            frozen_candidate_id="candidate-1",
            frozen_candidate_summary="candidate summary",
        )
        evidence_bundle = build_manual_evidence_bundle(
            implementation_signals={
                "source_fields": ("candidate_summary",),
                "matched_refs": (),
                "derived_from_summary": True,
                "derived_from_structured_content": False,
                "derived_from_payload": False,
            }
        )
        judgments = (
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-executor",
                checkpoint_id="checkpoint-1",
                agent_id="executor",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Execution path is not grounded.",
                deficiency_category=RejectionDeficiencyCategory.INCOMPLETENESS,
                severity="critical",
                blocker=True,
                used_signal_keys=("implementation.has_execution_path",),
                metadata={"agent_role": "executor"},
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-planner",
                checkpoint_id="checkpoint-1",
                agent_id="planner",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.APPROVE,
                rationale_text="Plan framing is otherwise sufficient.",
                metadata={"agent_role": "planner"},
            ),
        )

        aggregate = scheduler.aggregate_heartbeat_judgments(
            checkpoint_input,
            judgments,
            evidence_bundle=evidence_bundle,
        )
        profile = aggregate.convergence_profile

        self.assertEqual(aggregate.recommended_outcome, ConvergenceStatus.CONTINUE)
        self.assertIsNotNone(profile)
        self.assertEqual(profile.final_decision, ConvergenceStatus.CONTINUE)
        self.assertEqual(
            profile.semantic_state,
            HeartbeatConvergenceSemanticState.BLOCKED_BY_BLOCKER,
        )
        self.assertEqual(
            profile.dominant_reason,
            HeartbeatConvergenceDominantReason.BLOCKER_PRESENT,
        )
        self.assertTrue(profile.has_blocker)
        self.assertEqual(profile.followup_bias, HeartbeatConvergenceFollowupBias.RESOLVE_BLOCKERS)
        self.assertEqual(aggregate.aggregate_artifact.convergence_profile, profile)
        assert_terminal_consumption_attached(self, aggregate)

    def test_continue_profile_classifies_non_blocking_high_priority_unresolved_gap(self) -> None:
        scheduler = Scheduler(
            agents={},
            options=SchedulerOptions(thresholds=threshold_profile(support_ratio_threshold=1.0)),
        )
        checkpoint_input = HeartbeatCheckpointInput(
            checkpoint_id="checkpoint-1",
            workflow_id="wf-1",
            original_goal="test goal",
            frozen_candidate_id="candidate-1",
            frozen_candidate_summary="candidate summary",
        )
        evidence_bundle = build_manual_evidence_bundle(
            implementation_signals={
                "source_fields": ("candidate_summary",),
                "matched_refs": (),
                "derived_from_summary": True,
                "derived_from_structured_content": False,
                "derived_from_payload": False,
            }
        )
        judgments = (
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-executor",
                checkpoint_id="checkpoint-1",
                agent_id="executor",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Execution path is incomplete.",
                deficiency_category=RejectionDeficiencyCategory.INCOMPLETENESS,
                severity="major",
                blocker=False,
                used_signal_keys=("implementation.has_execution_path",),
                metadata={"agent_role": "executor"},
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-planner",
                checkpoint_id="checkpoint-1",
                agent_id="planner",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.APPROVE,
                rationale_text="Goal framing is sufficient.",
                metadata={"agent_role": "planner"},
            ),
        )

        aggregate = scheduler.aggregate_heartbeat_judgments(
            checkpoint_input,
            judgments,
            evidence_bundle=evidence_bundle,
        )
        profile = aggregate.convergence_profile

        self.assertEqual(aggregate.recommended_outcome, ConvergenceStatus.CONTINUE)
        self.assertIsNotNone(profile)
        self.assertEqual(
            profile.semantic_state,
            HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_UNRESOLVED_GAP,
        )
        self.assertEqual(
            profile.dominant_reason,
            HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP,
        )
        self.assertFalse(profile.has_blocker)
        self.assertEqual(profile.unresolved_high_priority_count, 1)
        self.assertNotEqual(
            profile.semantic_state,
            HeartbeatConvergenceSemanticState.BLOCKED_BY_BLOCKER,
        )
        assert_terminal_consumption_attached(self, aggregate)

    def test_converged_profile_classifies_clean_convergence(self) -> None:
        scheduler = Scheduler(
            agents={},
            options=SchedulerOptions(thresholds=threshold_profile(support_ratio_threshold=1.0)),
        )
        checkpoint_input = HeartbeatCheckpointInput(
            checkpoint_id="checkpoint-1",
            workflow_id="wf-1",
            original_goal="test goal",
            frozen_candidate_id="candidate-1",
            frozen_candidate_summary="candidate summary",
        )
        evidence_bundle = build_manual_evidence_bundle()
        judgments = (
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-planner",
                checkpoint_id="checkpoint-1",
                agent_id="planner",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.APPROVE,
                rationale_text="Sufficient for the stated goal.",
                metadata={"agent_role": "planner"},
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-reviewer",
                checkpoint_id="checkpoint-1",
                agent_id="reviewer",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.APPROVE,
                rationale_text="No material deficiency remains.",
                metadata={"agent_role": "reviewer"},
            ),
        )

        aggregate = scheduler.aggregate_heartbeat_judgments(
            checkpoint_input,
            judgments,
            evidence_bundle=evidence_bundle,
        )
        profile = aggregate.convergence_profile

        self.assertEqual(aggregate.recommended_outcome, ConvergenceStatus.CONVERGED)
        self.assertIsNotNone(profile)
        self.assertEqual(
            profile.semantic_state,
            HeartbeatConvergenceSemanticState.CONVERGED_CLEAN,
        )
        self.assertEqual(
            profile.dominant_reason,
            HeartbeatConvergenceDominantReason.NO_MATERIAL_RESERVATIONS,
        )
        self.assertEqual(
            profile.reservation_level,
            HeartbeatConvergenceReservationLevel.NONE,
        )
        self.assertEqual(
            profile.followup_bias,
            HeartbeatConvergenceFollowupBias.PREPARE_TERMINAL_OUTPUT,
        )
        assert_terminal_consumption_attached(self, aggregate)

    def test_converged_profile_preserves_decision_with_retained_reservations(self) -> None:
        scheduler = Scheduler(
            agents={},
            options=SchedulerOptions(thresholds=threshold_profile(support_ratio_threshold=0.6)),
        )
        checkpoint_input = HeartbeatCheckpointInput(
            checkpoint_id="checkpoint-1",
            workflow_id="wf-1",
            original_goal="test goal",
            frozen_candidate_id="candidate-1",
            frozen_candidate_summary="candidate summary",
        )
        evidence_bundle = build_manual_evidence_bundle(
            risk_signals={
                "source_fields": ("candidate_summary",),
                "matched_refs": (),
                "derived_from_summary": True,
                "derived_from_structured_content": False,
                "derived_from_payload": False,
            }
        )
        judgments = (
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-planner",
                checkpoint_id="checkpoint-1",
                agent_id="planner",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.APPROVE,
                rationale_text="Sufficient for the stated goal.",
                metadata={"agent_role": "planner"},
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-executor",
                checkpoint_id="checkpoint-1",
                agent_id="executor",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.APPROVE,
                rationale_text="Execution path is grounded.",
                metadata={"agent_role": "executor"},
            ),
            HeartbeatAgentJudgment.create(
                judgment_id="judgment-reviewer",
                checkpoint_id="checkpoint-1",
                agent_id="reviewer",
                candidate_id="candidate-1",
                evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                decision=HeartbeatVoteChoice.REJECT,
                rationale_text="Correctness risk remains explicit.",
                deficiency_category=RejectionDeficiencyCategory.CORRECTNESS_RISK,
                severity="major",
                blocker=False,
                used_signal_keys=("risk.has_risk_marker",),
                metadata={"agent_role": "reviewer"},
            ),
        )

        aggregate = scheduler.aggregate_heartbeat_judgments(
            checkpoint_input,
            judgments,
            evidence_bundle=evidence_bundle,
        )
        profile = aggregate.convergence_profile
        payload = build_heartbeat_report_payload(aggregate)

        self.assertEqual(aggregate.recommended_outcome, ConvergenceStatus.CONVERGED)
        self.assertIsNotNone(profile)
        self.assertEqual(profile.final_decision, ConvergenceStatus.CONVERGED)
        self.assertEqual(
            profile.semantic_state,
            HeartbeatConvergenceSemanticState.CONVERGED_WITH_RESERVATIONS,
        )
        self.assertEqual(
            profile.dominant_reason,
            HeartbeatConvergenceDominantReason.CRITICAL_OR_MAJOR_GAP,
        )
        self.assertEqual(profile.minority_high_priority_count, 1)
        self.assertFalse(profile.has_blocker)
        self.assertEqual(
            profile.reservation_level,
            HeartbeatConvergenceReservationLevel.ELEVATED,
        )
        self.assertEqual(
            profile.followup_bias,
            HeartbeatConvergenceFollowupBias.CARRY_FORWARD_RESERVATIONS,
        )
        self.assertEqual(payload.final_decision, "converged")
        self.assertIsNotNone(payload.convergence_profile)
        self.assertEqual(
            payload.convergence_profile.semantic_state,
            profile.semantic_state.value,
        )
        self.assertEqual(
            payload.convergence_profile.dominant_reason,
            profile.dominant_reason.value,
        )
        assert_terminal_consumption_attached(self, aggregate)

    def test_aggregate_artifact_handles_empty_judgments_and_missing_optional_fields(self) -> None:
        scheduler = Scheduler(
            agents={},
            options=SchedulerOptions(thresholds=threshold_profile(support_ratio_threshold=1.0)),
        )
        checkpoint_input = HeartbeatCheckpointInput(
            checkpoint_id="checkpoint-1",
            workflow_id="wf-1",
            original_goal="test goal",
            frozen_candidate_id="candidate-1",
            frozen_candidate_summary="candidate summary",
        )
        evidence_bundle = build_manual_evidence_bundle()

        aggregate = scheduler.aggregate_heartbeat_judgments(
            checkpoint_input,
            (),
            evidence_bundle=evidence_bundle,
        )

        self.assertEqual(aggregate.recommended_outcome, ConvergenceStatus.CONTINUE)
        self.assertIsNotNone(aggregate.convergence_profile)
        self.assertEqual(
            aggregate.convergence_profile.semantic_state,
            HeartbeatConvergenceSemanticState.CONTINUE_DUE_TO_INSUFFICIENT_SUPPORT,
        )
        self.assertEqual(
            aggregate.convergence_profile.dominant_reason,
            HeartbeatConvergenceDominantReason.INSUFFICIENT_APPROVAL_SUPPORT,
        )
        self.assertEqual(aggregate.aggregate_artifact.consensus_items, ())
        self.assertEqual(aggregate.aggregate_artifact.minority_items, ())
        self.assertEqual(aggregate.aggregate_artifact.unresolved_items, ())
        self.assertEqual(
            aggregate.aggregate_artifact.decision_rationale,
            ("No eligible heartbeat judgments were available, so discussion remains active.",),
        )

        partial_judgment_aggregate = scheduler.aggregate_heartbeat_judgments(
            checkpoint_input,
            (
                HeartbeatAgentJudgment.create(
                    judgment_id="judgment-reviewer",
                    checkpoint_id="checkpoint-1",
                    agent_id="reviewer",
                    candidate_id="candidate-1",
                    evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                    decision=HeartbeatVoteChoice.REJECT,
                    rationale_text="A required element is still missing.",
                    deficiency_category=RejectionDeficiencyCategory.OTHER,
                ),
            ),
            evidence_bundle=evidence_bundle,
        )
        partial_item = find_artifact_item(
            partial_judgment_aggregate.aggregate_artifact,
            RejectionDeficiencyCategory.OTHER,
        )
        self.assertEqual(partial_item.severity, "moderate")
        self.assertFalse(partial_item.blocker)
        self.assertEqual(partial_item.used_signal_keys, ())
        self.assertEqual(partial_item.source_anchors, ())
        self.assertEqual(partial_judgment_aggregate.highest_rejection_severity, "moderate")
        self.assertEqual(partial_judgment_aggregate.blocker_count, 0)
        self.assertEqual(partial_judgment_aggregate.blocker_roles, ())
        self.assertEqual(partial_judgment_aggregate.severity_histogram, {"moderate": 1})

    def test_heartbeat_phase_blocks_candidate_updates(self) -> None:
        state = ExecutionState(workflow_id="wf-1", goal="test goal")
        state.publish_candidate_from_discussion(
            summary_text="draft result",
            source_agent_id="planner",
        )

        frozen_candidate = state.enter_heartbeat_checkpoint()

        self.assertIsNotNone(frozen_candidate)
        self.assertEqual(state.current_phase, CoordinationPhase.HEARTBEAT_CHECKPOINT)
        self.assertEqual(frozen_candidate.status, FinalAnswerCandidateStatus.FROZEN)
        with self.assertRaises(RuntimeError):
            state.publish_candidate_from_discussion(
                summary_text="heartbeat rewrite should fail",
                source_agent_id="reviewer",
            )

    def test_execute_heartbeat_main_chain_can_resume_discussion(self) -> None:
        scheduler = Scheduler(
            agents={
                "planner": StubAgent(
                    summary_text="planner draft",
                    self_check_payload={
                        "decision": "approve",
                        "rationale_text": "Sufficient for the goal at this stage.",
                    },
                ),
                "reviewer": StubAgent(
                    summary_text="reviewer refinement",
                    self_check_payload={
                        "decision": "reject",
                        "rationale_text": "One required detail is still missing.",
                        "deficiency_category": "incompleteness",
                    },
                ),
            },
            options=SchedulerOptions(
                thresholds=threshold_profile(support_ratio_threshold=1.0),
                heartbeat_checkpoint=HeartbeatCheckpointDefinition(
                    entry_triggers=round_trigger_configuration(interval_rounds=1)
                ),
            ),
        )

        report = asyncio.run(
            scheduler.execute(
                goal="produce final answer",
                available_agents=(
                    AgentDescriptor(agent_id="planner"),
                    AgentDescriptor(agent_id="reviewer"),
                ),
            )
        )

        current_candidate = report.state.get_current_candidate()
        self.assertEqual(report.state.current_phase, CoordinationPhase.DISCUSSION_ROUND)
        self.assertIsNone(report.state.terminal_status)
        self.assertEqual(report.state.completed_steps, ["step-1", "step-2"])
        self.assertIsNotNone(current_candidate)
        self.assertEqual(current_candidate.status, FinalAnswerCandidateStatus.FROZEN)
        self.assertEqual(
            report.state.shared_context.values["last_heartbeat_recommended_outcome"],
            "continue",
        )

    def test_execute_heartbeat_main_chain_can_converge(self) -> None:
        scheduler = Scheduler(
            agents={
                "planner": StubAgent(
                    summary_text="good enough result",
                    self_check_payload={
                        "decision": "approve",
                        "rationale_text": "Current candidate is sufficient.",
                    },
                ),
                "reviewer": StubAgent(
                    summary_text="should not execute",
                    self_check_payload={
                        "decision": "approve",
                        "rationale_text": "No blocking deficiency remains.",
                    },
                ),
            },
            options=SchedulerOptions(
                thresholds=threshold_profile(support_ratio_threshold=1.0),
                heartbeat_checkpoint=HeartbeatCheckpointDefinition(
                    entry_triggers=round_trigger_configuration(interval_rounds=1)
                ),
            ),
        )

        report = asyncio.run(
            scheduler.execute(
                goal="produce final answer",
                available_agents=(
                    AgentDescriptor(agent_id="planner"),
                    AgentDescriptor(agent_id="reviewer"),
                ),
            )
        )

        current_candidate = report.state.get_current_candidate()
        self.assertEqual(
            report.state.current_phase,
            CoordinationPhase.TERMINATION_EXTENSION_HANDLING,
        )
        self.assertEqual(report.state.terminal_status, ConvergenceStatus.CONVERGED)
        self.assertEqual(report.state.completed_steps, ["step-1"])
        self.assertIsNotNone(current_candidate)
        self.assertEqual(current_candidate.status, FinalAnswerCandidateStatus.FROZEN)


if __name__ == "__main__":
    unittest.main()
