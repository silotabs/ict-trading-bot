# Phased Rollout Plan

## Purpose

This document defines the controlled rollout path required before the trading system can move from paper / daemon validation toward live deployment planning.

It is a planning document only.

- It does not authorize live trading.
- It does not enable broker-facing live execution.
- It does not widen execution eligibility beyond `verified_paper_trade`.
- It does not replace `19_live_readiness_checklist.md`, `20_go_no_go_framework.md`, `21_shadow_metrics_requirements.md`, or `22_incident_and_rollback_runbook.md`.

The current default standing remains:

- `hold_for_more_shadow_evidence`

## Rollout Principle

The system may advance only when evidence proves that the runtime, strategy boundary, OMS path, risk controls, and operator procedures behave correctly under realistic market conditions.

Infrastructure completion is not enough. A passing test suite is not enough. A few good calls on the chart are not enough.

The promotion question is:

Can the exact release candidate observe, classify, block, reconcile, and recover safely for a sustained period without widening the house rules?

## Phase 0 - Release Candidate Freeze

### Objective

Establish the exact paper / daemon baseline that will be evaluated during burn-in.

### Required State

- release candidate identifier is recorded
- current regression suite is green
- smoke-test runbook passes on the candidate
- `verified_paper_trade` is the only execution-eligible decision
- live order placement remains disabled
- auto-execution and trade-management policies remain disabled unless explicitly running paper / testnet drills
- risk-control policy is reviewed and committed
- operator auth and kill-switch configuration are verified

### Evidence To Retain

- release identifier or commit reference
- full backend test result
- frontend runtime-surface test result, if UI is part of the review
- smoke-test output
- `/health` and `/ready` payloads
- current risk-control policy snapshot
- current auto-execution and trade-management policy snapshots

### Exit Gate

Move to Phase 1 only if the release candidate is stable, reproducible, and still paper / daemon scoped.

Automatic no-go:

- any live submission path enabled by default
- any execution eligibility beyond `verified_paper_trade`
- any failed emergency-stop or pause-control check

## Phase 1 - Shadow-Mode Burn-In

### Objective

Collect enough real market evidence to prove the scanner and review surfaces behave consistently without creating trades from shadow-only states.

### Minimum Duration

- `30` consecutive calendar days
- monitored symbols: `BTCUSDT` and `ETHUSDT`
- event-driven confirmed candle-close path active for:
  - `5m`
  - `15m`
  - `4h`

### Required Shadow Evidence

The burn-in evidence pack must include:

- daily `/ready` snapshots
- public event-stream health history
- fallback polling usage history
- signal-trace samples
- shadow trace samples
- `/v1/shadow-review/summary` outputs
- false-negative review notes
- false-positive review notes
- blocker-cluster summaries
- opportunity-state distributions
- session-window distributions
- symbol distributions

### Minimum Review Counts

- at least `25` human-reviewed false-negative candidates
- at least `25` human-reviewed system-surfaced opportunities
- at least `10` reviewed `near_miss` traces
- at least `10` reviewed `awaiting_confirmation` traces
- at least `10` reviewed `context_watch` traces

### Shadow Quality Gates

- confirmed candle-close coverage: `>= 99.5%`
- duplicate handled-close rate after dedupe: `<= 0.5%`
- fallback polling share of handled bars: `<= 2.0%`
- unexplained missed closes: `0`
- shadow trace persistence: `>= 99.9%`
- non-eligible decisions that advance as executable: `0`
- shadow traces that create execution by shadow state alone: `0`
- unexplained readiness false positives: `0`

### Blocker-Cluster Stability

Blockers must become explainable before live planning can proceed.

Required evidence:

- top `5` blocker clusters explain at least `70%` of reviewed misses
- at least `80%` of reviewed false-negative candidates map to known blocker classes or known model limitations
- blocker-cluster ordering remains materially stable across comparable session windows
- any blocker cluster that spikes by more than `2x` week-over-week has a written explanation

### Exit Gate

Move to Phase 2 only if the full 30-day burn-in window is complete and the review set is deep enough to distinguish model behavior from random misses.

If runtime is stable but the evidence window is short or the review sample is thin, remain at:

- `hold_for_more_shadow_evidence`

## Phase 2 - Operational Reliability Review

### Objective

Prove that runtime health, event ingestion, persistence, and reconciliation surfaces are trustworthy enough for live planning.

### Event-Stream Reliability Gate

Required pass conditions:

- `/ready` correctly reports:
  - `healthy_primary`
  - `degraded_fallback`
  - `not_ready`
- public candle-close stream remains the primary production path
- stale event stream does not report as fully healthy
- fallback polling is visible as degraded, not silently treated as healthy
- fallback polling does not duplicate already handled confirmed closes
- missed close count is `0` unless each miss is explained and marked no-go for the review window

No-go examples:

- event stream stale while `/ready` reports healthy primary
- fallback polling dominates handled bars
- unexplained confirmed close gap
- duplicated signal traces from the same confirmed close

### Read-After-Write Gate

Required pass conditions:

- signal traces are queryable after write within the same operator review window
- shadow traces are queryable after write within the same operator review window
- execution intents are queryable after write
- risk checks are queryable after write
- `signal_traces.opportunity_state` and `trace_json.opportunity_state` stay consistent
- known P6 empty-read behavior is either root-caused and bounded or absent for `7` consecutive burn-in days

No-go examples:

- repeated empty-read after successful write
- indexed trace fields missing while JSON fields are populated
- summary queries disagree with stored records

### OMS / Reconciliation Gate

Required pass conditions:

- execution intent creation is idempotent for repeated handling of the same eligible signal
- no duplicate active intent exists for the same symbol and scan signature
- every proposal links back to the originating intent where applicable
- execution-state snapshots reconcile with proposal lifecycle state
- stale sync lockout blocks advancement when execution state freshness is lost
- orphan active intents count is `0`
- unresolved reconciliation divergence count is `0`

No-go examples:

- intent advances without a risk check
- proposal exists without a traceable eligible signal
- OMS state and stored execution state diverge without recorded resolution
- stale sync handling fails to block advancement

### Exit Gate

Move to Phase 3 only if event ingestion, trace persistence, and reconciliation are proven against the exact release candidate.

## Phase 3 - Risk-Control And Operator Drill Review

### Objective

Prove that pre-trade controls and operator procedures stop advancement before damage can occur.

### Risk-Control Gate

The following controls must be demonstrated with recorded risk-check evidence:

- maximum single-order size
- maximum daily order count
- maximum intraday position exposure per symbol
- maximum daily realized loss
- maximum open exposure notional
- maximum active intent count per symbol
- consecutive-loss cooldown
- stale market-data lockout
- stale execution-state lockout
- duplicate active-intent suppression
- manual kill switch
- automatic kill switch
- cancel-on-disconnect guard

Each demonstrated control must include:

- trigger condition
- policy threshold
- risk-check identifier
- blocker reason
- proof that execution advancement stopped
- operator-visible recovery path

No-go examples:

- risk block fails to halt advancement
- blocked state is not persisted
- primary blocker reason is missing
- operator cannot determine which policy blocked the attempt
- recovery requires ad hoc database edits

### Operator Drill Gate

Operators must complete and record the following drills:

- normal startup verification
- `/ready` degraded-fallback interpretation
- global pause / resume
- emergency stop
- order-submission pause
- risk-block triage
- stale-market-data triage
- stale-sync triage
- read-after-write anomaly triage
- rollback to last known good baseline

Each drill record must include:

- date and operator
- release candidate
- command or route used
- expected result
- observed result
- evidence links or identifiers
- final disposition

### Rollback Gate

Rollback is considered proven only when operators can:

1. freeze execution advancement through control state and policy gates
2. preserve traces, intents, risk checks, events, and daemon logs
3. identify the last known good baseline
4. restart or redeploy that baseline
5. rerun trust-gate and smoke checks
6. verify readiness after rollback
7. record signoff from runtime, risk, reconciliation, and release owners

No-go examples:

- rollback drill missing
- rollback depends on undocumented manual steps
- emergency stop fails
- logs or evidence are lost during rollback
- restarted baseline cannot be verified

### Exit Gate

Move to Phase 4 only if all risk controls and operator drills pass with retained evidence.

## Phase 4 - Go / No-Go Decision For Live Planning

### Objective

Decide whether the system should remain in shadow evidence mode or begin a separate controlled live-planning process.

This phase still does not authorize live trading.

### Required Evidence Pack

The decision review must include:

- release candidate identifier
- full regression test results
- smoke-test results
- 30-day shadow burn-in summary
- false-negative review sample
- false-positive review sample
- blocker-cluster summary
- event-stream reliability report
- trace persistence and read-after-write report
- OMS reconciliation report
- risk-control drill report
- operator drill report
- rollback drill report
- signoffs from required owners

### Decision States

#### `no_go`

Use when any hard safety blocker remains open.

Examples:

- live path enabled before approval
- execution eligibility widened beyond `verified_paper_trade`
- event stream readiness is unreliable
- risk-control bypass observed
- duplicate active intent observed
- reconciliation divergence unresolved
- emergency stop or rollback drill failed
- shadow evidence cannot explain misses

#### `hold_for_more_shadow_evidence`

Use when the system appears operationally stable but evidence is still too thin.

Examples:

- fewer than `30` consecutive burn-in days
- false-negative review sample is below threshold
- blocker clusters are unstable
- fallback usage is elevated but explainable
- operator drills passed but have not repeated under enough runtime conditions

#### `ready_for_live_planning`

Use only when every hard gate passes and the evidence window is complete.

This state means:

- it is acceptable to begin a separate controlled live-pilot planning discussion
- the paper / daemon release candidate has enough evidence for planning review
- operators have proved they can stop, diagnose, and roll back the system

This state does not mean:

- live trading is approved
- autonomous execution is approved
- broker expansion is approved
- risk limits may be relaxed

For compatibility with the existing go/no-go framework, `ready_for_live_planning` is equivalent to the planning-only state named `ready_for_controlled_live_planning`.

## Decision Framework

Use this sequence when deciding whether to move from `hold_for_more_shadow_evidence` to `ready_for_live_planning`.

1. Check hard scope boundaries.
   - If live execution is enabled by default, result is `no_go`.
   - If execution eligibility is wider than `verified_paper_trade`, result is `no_go`.

2. Check shadow evidence depth.
   - If the 30-day burn-in window is incomplete, result is `hold_for_more_shadow_evidence`.
   - If false-negative or false-positive samples are too small, result is `hold_for_more_shadow_evidence`.

3. Check event-stream reliability.
   - If readiness misreports degraded ingestion as healthy, result is `no_go`.
   - If fallback dominates production-path scans, result is `hold_for_more_shadow_evidence` or `no_go` depending on severity and explanation.

4. Check blocker-cluster stability.
   - If blocker clusters explain the majority of reviewed misses and remain stable, continue.
   - If blocker clusters are unstable or unexplained, result is `hold_for_more_shadow_evidence`.

5. Check reconciliation.
   - If duplicate active intents, orphan intents, or unresolved state divergence exist, result is `no_go`.
   - If reconciliation is clean and stale-sync lockouts are proven, continue.

6. Check risk controls.
   - If any configured control fails to block advancement, result is `no_go`.
   - If all controls block with recorded reasons and visible recovery paths, continue.

7. Check operator readiness.
   - If emergency stop or rollback drill is missing or failed, result is `no_go`.
   - If all drills are complete and signed off, continue.

8. Record final decision.
   - Any hard failure: `no_go`
   - Hard gates pass but evidence is incomplete: `hold_for_more_shadow_evidence`
   - Hard gates pass and evidence is complete: `ready_for_live_planning`

## Required Signoffs

The final planning decision must include signoff from:

- trading operator
- runtime / release owner
- risk-control owner
- reconciliation owner
- incident-response / rollback owner

Each signoff must reference the exact evidence pack used for review.

## Final Live-Planning Boundary

Even after `ready_for_live_planning`, the next step is not immediate live trading.

The next step is a separate live-pilot plan that must define:

- venue and account boundary
- maximum capital exposure
- allowed symbols
- allowed sessions
- order-size limits
- daily loss limits
- manual supervision requirements
- kill-switch operator
- rollback owner
- start and stop dates
- post-pilot review criteria

Until that separate plan is approved, the system remains paper / daemon or testnet only.

