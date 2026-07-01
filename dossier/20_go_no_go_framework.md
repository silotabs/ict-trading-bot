# Go / No-Go Framework

## Purpose

This framework translates the live-readiness checklist into an explicit planning decision.

It exists to answer one narrow question:

Is the current paper / daemon system mature enough to begin controlled live deployment planning?

It does not authorize live trading.

## Inputs

The go / no-go review must use the following evidence pack:

- current release identifier or commit reference
- full paper / daemon test results
- smoke-run results from the current baseline runbook
- shadow-review summaries
- blocker-cluster summaries
- false-negative review sample
- false-positive review sample
- event-stream reliability report
- OMS reconciliation report
- risk-control drill results
- incident / rollback drill results

## Decision States

### `no_go`

Use when any hard blocker remains open.

Examples:

- unresolved read-after-write inconsistency
- stale market-data handling not proven
- stale sync handling not proven
- emergency stop not verified
- risk-control bypass or duplicate intent anomaly
- shadow evidence window too short or too sparse

### `hold_for_more_shadow_evidence`

Use when the runtime is stable but the evidence window is still too thin for live planning.

Examples:

- insufficient review depth on near-miss and awaiting-confirmation populations
- blocker clusters are still unstable across session windows
- too few operator-reviewed false negatives
- too little event-driven burn-in duration

### `ready_for_controlled_live_planning`

Use only when:

- all hard gates pass
- the shadow evidence window is complete
- blocker clusters are understandable
- risk and rollback drills are proven
- operator signoffs are complete

This state means it is acceptable to begin a separate, formal live-pilot planning phase.

It does not mean:

- live trading is approved
- broker expansion is approved
- autonomous execution is approved

## Decision Method

1. Validate hard gates.
2. Validate shadow evidence duration and quality thresholds.
3. Review blocker clusters and false-negative sample quality.
4. Review event-stream and read-after-write reliability.
5. Review OMS reconciliation and risk-control drills.
6. Review incident-response and rollback drill quality.
7. Collect required operator signoffs.
8. Record the decision and unresolved risks.

If any hard gate fails, the result is immediately `no_go`.

If hard gates pass but evidence is still too thin, the result is `hold_for_more_shadow_evidence`.

Only when both hard gates and evidence depth pass should the result be `ready_for_controlled_live_planning`.

## Required Signoff Roles

- operator / runtime owner
- release-check owner
- risk-control owner
- reconciliation owner
- incident-response owner

## Mandatory Recorded Outputs

Every decision record must include:

- decision state
- checklist version
- reviewed date range
- shadow-session identifiers reviewed
- named blockers, if any
- named assumptions still open
- explicit recommendation:
  - continue shadowing
  - fix blockers
  - begin controlled live planning

## Current Standing

As of the P7 planning phase, the default standing should remain:

- `hold_for_more_shadow_evidence`

Reason:

- the system is operationally stronger after P0-P6, but live deployment planning still depends on longer shadow evidence, blocker stability, and explicit closure of remaining runtime risks.
