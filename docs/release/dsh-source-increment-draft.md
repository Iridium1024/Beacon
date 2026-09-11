# Draft: DSH Fourth-Agent Source Increment

Status: review draft only. This file is not a GitHub Release and does not
authorize a tag, upload, or installer build.

## Scope

This source increment adds the opt-in DeepSeek Harness (DSH) fourth Agent
platform to Beacon's Python CLI and includes only its necessary shared runtime
control, project-local locked Node carrier, configuration examples, automated
tests, and documentation. It deliberately excludes the Desktop application,
browser/read-only UI, Gateway changes, and unfinished P3-B assets.

DSH supports explicit creation or exact persisted-session join through one
Beacon-owned managed runtime. It uses the project-local Node carrier locked to
DSH `0.1.1-rc.2`, has explicit path/session configuration, owner/lease
protection, causal final-capture checks, and deliberate stop/resume/recreate
semantics. It never takes over a foreign live DSH Web, TUI, or Desktop process.

## Installation and Compatibility

This is source delivery, not a self-contained installer. Downloading or
extracting source is insufficient until the Python CLI dependencies are
installed. DSH also requires an operator-supplied compatible DSH runtime,
Node 22.19+ on Windows for the locked carrier, approved local runtime/session
paths, and the operator's provider authentication outside Beacon.

Follow [source-installation.md](source-installation.md) for required core CLI
steps, optional Gateway steps, the DSH carrier/configuration example, and
provider-session prerequisites.

## Validation Status

- Automated Python, fake-protocol, and managed-runtime lifecycle coverage is
  included.
- An offline integration uses the locked official runtime and official JSONL
  persistence to check exact history-resume behavior.
- The candidate's `npm audit --omit=dev` reports two moderate and two high
  indirect-carrier findings (with npm-reported fixes available). They are a
  review item, not a claim that the carrier dependency risk is cleared.
- No authenticated real DSH account, user credential, private session, or real
  model communication has been tested.

Installation success, a carrier syntax check, or offline/fake test success must
not be described as real DSH service availability. Authenticated model
communication is a long-term high-priority follow-up and requires separate
operator authorization.

## Publication Plan

After review and explicit approval, synchronize the selected source files to
the public repository and identify the resulting public commit or tag. A
GitHub Release is optional and separate; it may later be created from that
immutable source point. No standalone installer or local minimum package is
produced by this source increment.
