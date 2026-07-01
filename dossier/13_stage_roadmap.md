# Trading Project Stage Roadmap

As of `2026-04-15`, the project is in:

- `Stage 6: Concept Proof / Acceptance Testing`

This document is the canonical stage map for the trading project. Use it to avoid overstating progress, collapsing concept proof into infrastructure completion, or treating thin evidence as a promotion signal.

## Anti-Hallucination Rule

Only say the project has moved to the next stage when the current stage exit criteria are actually met from live daemon state, recent runtime checks, and saved artifacts.

Do not advance a stage just because:

- code exists
- an endpoint exists
- the UI renders
- one command succeeded once

## Stage Map

### Stage 1: Stack Foundation

Goal:

- stable daemons
- API health
- control plane
- persistent state

Done when:

- stack starts cleanly
- health routes respond
- burn-in checks are usable
- control state works

Status:

- `done`

### Stage 2: Control Room + Operator UI

Goal:

- usable dashboard for monitoring and control

Done when:

- control-room snapshot and stream work
- chart and operator rail are stable
- operator controls are present
- workspace dock works
- UI is no longer the main blocker

Status:

- `done`

### Stage 3: Concept Review Core

Goal:

- grounded concept review and decision workflow

Done when:

- `concept-review` works
- `concept-decision` works
- `concept-brief` works
- outputs are based on live daemon state, not memory

Status:

- `done`

### Stage 4: Revision Loop Core

Goal:

- revisions can be created, linked, evaluated, and compared

Done when:

- structured reviews save
- revisions save
- linked revision evaluation works
- evaluation history exists
- compare summary exists

Status:

- `done`

### Stage 5: Compare-Guidance Integration + Live Daemon Testing

Goal:

- daemon actively understands and publishes revision-loop guidance

Done when:

- compare artifacts save cleanly
- compare leader is ranked live
- runtime exposes leader guidance
- concept lab emits compare-related events
- control-room and concept-runtime surfaces read the same guidance
- release checks pass after changes

Status:

- `done`

### Stage 6: Concept Proof / Acceptance Testing

Goal:

- determine whether Concept 1 actually improves under fresh evidence

Starts when:

- Stage 5 is operationally stable
- infrastructure is no longer the main bottleneck

Done when:

- evidence thresholds are met
- fresh-sample history is meaningful
- at least one revision shows repeatable improvement, or the concept is clearly rejected
- the result can be explained conservatively with saved artifacts

Status:

- `current`

### Stage 7: Promotion or Rejection Decision

Goal:

- decide what happens to Concept 1

Possible outcomes:

- keep collecting evidence
- queue a one-variable rule review
- compare against the next concept
- reject the current concept direction

Status:

- `not started`

## Current Truth Snapshot

Current live state for `Stage 6` should be described using daemon truth, not optimism.

As of the latest verified checks:

- concept runtime overall: `collecting`
- recommendation: `collect_more_evidence`
- candidate ratio: `0%`
- unmet evidence thresholds: `recent_proposal_count`, `recent_action_count`, `recent_execution_state_count`
- dominant blocker: `displacement` at about `88%`
- revision leader: `RV-00002`
- revision leader status: `flat`
- compare verdict: `hold_revision_loop`
- compare guidance: keep collecting fresh-sample evidence before changing rules
- Stage 5 daemon-live gate: `ready_for_stage_6_from_daemon_state`

This means:

- infrastructure is no longer the main bottleneck
- revision-loop machinery is live
- concept proof is now the active bottleneck

## What “Close To Done” Means

Use this split when answering progress questions:

- platform / architecture completion: high
- backend / daemon loop completion: high
- concept validation completion: low to medium

Do not merge these three into one vague percentage.

## Stage Transition Rules

Move from `Stage 5` to `Stage 6` only when:

- compare guidance remains stable across multiple daemon cycles
- no route/runtime regressions remain from Stage 5 work
- operator-facing surfaces agree on the same leader/guidance
- evidence, not infrastructure, becomes the primary constraint

Move from `Stage 6` to `Stage 7` only when:

- evidence thresholds are met
- revision outcomes are no longer mostly flat
- a conservative promotion or rejection argument can be made from saved history

## Default Next Step

Unless the user explicitly redirects elsewhere, the default work inside Stage 6 is:

- keep the stack running
- accumulate fresh samples
- observe whether any revision improves beyond `flat`
- avoid claiming concept success before the evidence supports it
- only prepare a Stage 7 decision once the saved evidence supports a conservative promotion or rejection argument
