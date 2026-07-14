from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.orchestrator.convergence import CoordinationPhase
from agent_os.orchestrator.runtime_state import ExecutionState
from agent_os.protocols.final_answer_candidate import FinalAnswerCandidateStatus
from agent_os.protocols.shared_context import SharedContext


class FinalAnswerCandidateTests(unittest.TestCase):
    def test_publish_candidate_sets_current_candidate(self) -> None:
        state = ExecutionState(workflow_id="wf-1", goal="test goal")

        candidate = state.publish_candidate_from_discussion(
            summary_text="candidate summary",
            source_agent_id="planner",
        )

        self.assertEqual(state.current_phase, CoordinationPhase.DISCUSSION_ROUND)
        self.assertEqual(candidate.workflow_id, "wf-1")
        self.assertEqual(candidate.source_round, 1)
        self.assertEqual(candidate.status, FinalAnswerCandidateStatus.DRAFT)
        self.assertEqual(state.get_current_candidate(), candidate)

    def test_new_candidate_supersedes_previous_without_deleting_history(self) -> None:
        context = SharedContext()
        first = context.update_current_candidate(
            workflow_id="wf-1",
            source_round=1,
            source_agent_id="planner",
            summary_text="first candidate",
        )
        second = context.update_current_candidate(
            workflow_id="wf-1",
            source_round=2,
            source_agent_id="executor",
            summary_text="second candidate",
        )

        self.assertEqual(len(context.final_answer_candidates), 2)
        self.assertEqual(context.get_current_candidate(), second)
        self.assertEqual(
            context.final_answer_candidates[0].status,
            FinalAnswerCandidateStatus.SUPERSEDED,
        )
        self.assertEqual(first.candidate_id, context.final_answer_candidates[0].candidate_id)

    def test_freeze_current_candidate_marks_current_candidate_as_frozen(self) -> None:
        state = ExecutionState(workflow_id="wf-1", goal="test goal")
        candidate = state.publish_candidate_from_discussion(
            summary_text="candidate summary",
            source_agent_id="planner",
        )

        frozen_candidate = state.freeze_current_candidate()

        self.assertIsNotNone(frozen_candidate)
        self.assertEqual(candidate.candidate_id, frozen_candidate.candidate_id)
        self.assertEqual(frozen_candidate.status, FinalAnswerCandidateStatus.FROZEN)
        self.assertEqual(state.get_current_candidate(), frozen_candidate)


if __name__ == "__main__":
    unittest.main()
