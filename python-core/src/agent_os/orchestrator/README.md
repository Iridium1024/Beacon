# Orchestrator Module

## Debate Evaluation Semantics

The debate evaluation model distinguishes stage boundaries from broader orchestration phases.

Phases:
- `discussion_round`
- `heartbeat_checkpoint`
- `termination_extension_handling`

Evaluation stages:
- `discussion_round`: proposal-bearing stage with no per-response voting by default
- `heartbeat_checkpoint`: checkpoint stage where voting is permitted, but new solution proposals are not
- `final_answer_evaluation`: terminal evaluation stage where voting is permitted and the final report is expected
- `extension_handling`: structural review stage for extension requests only

## Canonical Semantic Objects

- `CommunicationMessage` is the canonical semantic object for discussion-round shared-context updates.
- `FinalAnswerCandidate` is the canonical evaluation object for checkpoint, heartbeat, and final-answer review.
- `embedding_vector` and `vector_memory` are auxiliary representations only.
- Checkpoint, freeze, self-check, voting, dispatcher, and report flows must consume explicit semantic objects directly.
- Vector representations may support retrieval, compression, clustering, similarity association, or history trimming, but they are not the primary decision surface.

Heartbeat checkpoint semantics:
- heartbeat is a non-discussion phase
- the current discussion result is frozen when checkpoint begins
- the frozen `FinalAnswerCandidate` is the normative heartbeat input
- only non-sleeping agents participate in heartbeat self-check
- self-checks are intended to run in parallel and independently
- agents compare the frozen result against the original task goal
- agents vote on the current final answer using binary `approve` / `reject` only
- every vote includes a short mandatory rationale
- approve rationale explains why the current result is sufficient
- reject rationale identifies the main deficiency category
- rationale is intended to stay concise and diagnostic, not a solution rewrite
- agents must not propose new solution content during checkpoint
- if approval threshold is reached, the system stops and outputs the frozen result plus concise dissent summary
- otherwise, the system resumes discussion or exits through existing fallback mechanisms

Checkpoint entry is controlled by generic `Trigger` objects rather than hard-coded interval logic.

Supported trigger semantics:
- `round_based`
- `time_based`

Multiple triggers may coexist with OR semantics:
- if any enabled trigger fires, the system enters `heartbeat_checkpoint`
- the system does not invent or optimize trigger values
- users define trigger parameters and scope placement

Configuration scopes:
- global defaults
- project-level overrides
- runtime adjustments

Convergence remains structurally defined as a combination of:
- goal satisfaction
- improvement stagnation
- voting-threshold outcome in stages where voting is allowed

Consensus may still be evaluated as a semantic signal, but it is not required to trigger voting on each response.

## Sleep And Diversity Notes

- Quality-based forced sleep is not a default mechanism.
- Sleeping agents do not rejoin discussion automatically.
- Sleeping responses are intended to remain short and standardized.
- Low approval does not imply automatic removal from the next discussion round.
- Minority positions are intended to remain visible in the final report.

## Final Report Fields

The final debate evaluation report is intended to be emitted whether convergence succeeds or fails.

Per-agent metrics:
- `vote_approval_rate`
- `rejection_rate`
- `adoption_rate`
- `rationale_history_summary`
- `final_contribution_status`

User-facing guidance:
- advisory next-round inclusion signal
- next-round inclusion note
- visible minority-opinion summaries

The report is intended to help the user decide whether an agent should remain in the next discussion round without automatically excluding low-support or minority-position agents.

## Trigger Responsibility Boundaries

- Users define trigger parameters.
- Users choose whether a trigger belongs in global defaults, project overrides, or runtime adjustments.
- The system only evaluates the configured triggers and applies the heartbeat transition when a trigger fires.
- Adaptive trigger optimization is out of scope for this design.

## Heartbeat Responsibility Boundaries

- Agents only self-check the frozen result during heartbeat.
- The frozen result is an explicit candidate object, not an inferred vector state.
- Agents do not generate new solution content during heartbeat.
- Empty approval and empty rejection are structurally disallowed.
- The dispatcher only aggregates approval and rejection results plus concise dissent.
- The dispatcher does not reinterpret or override agent judgments.
