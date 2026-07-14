# Project Directory Coordination

Status: macro step 22.3 advisory coordination contract.

## Purpose

Project directory coordination lets local callers and external advanced agents
record who is working on which project root, path scopes, task/conversation
scope, branch/head, and handoff state. It is meant for human-plus-agent and
multi-agent collaboration when several agents may share the same workspace
directory.

This is not a filesystem permission system. It does not lock directories,
restrict shell or IDE access, scan file bodies, run git, resolve conflicts, or
connect a real Codex, Claude Code, browser, IDE, provider-native, external
context engine, or remote conversation runtime.

## Record Contract

`ProjectDirectoryCoordinationRecord` serializes as
`project_directory_coordination.v1` and includes:

- `directoryCoordinationId`, `workspaceId`, `declaredAgentId`, `projectRoot`,
  and optional `gitRepositoryId`.
- Optional `linkedTaskId` and `linkedConversationId`.
- `declaredPathScopes` normalized as metadata-only relative scopes.
- `directoryAccessIntent`: `read_only`, `edit_planned`, `editing`,
  `handoff_ready`, `review_requested`, or `done_reported`.
- `overlapStatus`: `none`, `shared_read`, `shared_write_risk`, or
  `conflict_declared`.
- `coordinationStrength=advisory_only`, `notSecurityBoundary=true`, and
  `advisoryOnly=true`.
- Caller-reported git provenance: `lastKnownGitHead`, `lastKnownBranch`,
  `dirtyState`, `uncommittedChangeSummary`, `testSummary`,
  `recommendedCommitPolicy`, and `handoffNote`.

Boundary flags always report `fileBodiesRead=false`,
`recursiveFileScanExecuted=false`, `gitOperationExecuted=false`,
`destructiveGitOperationExecuted=false`, `realRuntimeConnected=false`,
`providerPromptInjected=false`, and `credentialStored=false`.

## Overlap Semantics

The platform compares declared path scopes within the same project root or
repository id. It uses conservative prefix matching only; it does not read the
filesystem.

- Disjoint scopes produce `none`.
- Overlapping read-only scopes produce `shared_read`.
- Any overlap involving `edit_planned`, `editing`, `handoff_ready`, or
  `review_requested` produces `shared_write_risk`.
- `done_reported` records are excluded from active overlap calculations.

Agents should treat `shared_write_risk` as a request to pause and ask the user
before continuing overlapping edits.

## Local Runtime Commands

`python -m agent_os.local_runtime` exposes:

- `project-directory-coordination-instructions`
- `project-directory-coordination-declare`
- `project-directory-coordination-status`
- `project-directory-coordination-update`
- `project-directory-coordination-complete`

`complete` only records `directoryAccessIntent=done_reported` and the supplied
git/test/handoff summaries. It does not execute `git commit`, `push`, `reset`,
`checkout`, `rebase`, or any file operation.

## Agent Guidance

Before editing a shared project directory, an external agent should:

- Read `agent-exchange-instructions` and
  `project-directory-coordination-instructions`.
- Declare its project root, path scopes, access intent, current branch/head,
  and expected task or conversation scope.
- Check for existing `shared_write_risk` records.
- Pause and ask the user before continuing overlapping writes.
- On completion, report changed scopes, test results, current branch/head, and
  whether the work was committed.

Records must not contain file bodies, full prompts, full model replies, API
keys, Authorization headers, cookies, proxy credentials, browser session tokens,
provider session tokens, or remote runtime handles.
