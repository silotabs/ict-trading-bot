# Live Readiness Checklist

## Scope

This checklist defines the minimum conditions required before the current paper / daemon stack can be considered ready for controlled live deployment planning.

This is a planning gate only.

- It does not authorize live trading.
- It does not widen execution eligibility.
- It does not replace the current trusted paper / daemon baseline.

## Hard Preconditions

All of the following must be true before any live pilot planning can move forward:

- `verified_paper_trade` is still the only execution-eligible decision.
- auto-execution, trade management, and broker-facing live behavior remain disabled by default.
- current paper / daemon regression suite is green.
- paper / daemon smoke runbook passes on the exact release candidate intended for planning review.
- operator pause and emergency stop controls are verified on the active runtime.

## Shadow-Mode Evidence Gates

The system must accumulate a stable shadow-mode evidence window before any go decision can be discussed.

- minimum duration: `30` consecutive calendar days
- minimum monitored symbols: `BTCUSDT` and `ETHUSDT`
- minimum trigger basis: event-driven confirmed `5m` / `15m` / `4h` candle-close scanning must remain the primary production path throughout the sample
- minimum operator review cadence: at least `3` review sessions per week
- minimum false-negative review set: at least `25` human-reviewed candidate misses
- minimum false-positive review set: at least `25` human-reviewed system surfaced opportunities

## Shadow-Mode Performance Requirements

- event-driven scan coverage for confirmed candle closes: `>= 99.5%`
- duplicate closed-candle trigger rate after dedupe: `<= 0.5%`
- fallback polling usage for production-path scans: `<= 2.0%` of handled bars
- unexplained missed-bar count: `0`
- unexplained execution-intent duplication count: `0`
- unexplained risk-check bypass count: `0`
- unexplained readiness false-positive count: `0`

## Review Quality Requirements

- blocker clusters must be stable enough to explain the majority of misses:
  - top `5` blocker clusters should explain at least `70%` of reviewed near-miss and awaiting-confirmation traces
- false-negative review must show that promising misses are explainable, not random:
  - at least `80%` of reviewed false-negative candidates must map to known blocker classes or known model limitations
- opportunity-state populations must remain interpretable:
  - `near_miss`
  - `awaiting_confirmation`
  - `context_watch`
  - `invalid`
- unexplained swings in blocker populations between comparable session windows must be investigated before any go decision

## Runtime Reliability Requirements

### Event Stream

- public candle-close stream must remain healthy for the entire burn-in window
- stale market-data lockout must trigger correctly when the stream becomes stale
- scan fallback must not create duplicate traces for already handled bars

### Read-After-Write Consistency

- signal traces, shadow traces, intents, and risk checks must be queryable after write within the same operational review window
- the immediate post-write empty-read behavior observed during P6 must be either:
  - reproduced and root-caused with a bounded explanation, or
  - absent for `7` consecutive burn-in days
- any repeated empty-read anomaly on newly written shadow traces is a no-go item until resolved

### OMS / Reconciliation

- execution intents must remain idempotent under repeated handling
- OMS state transitions must reconcile cleanly with stored execution state
- stale sync lockout must block advancement when state freshness is lost
- no orphaned active intent may remain unresolved beyond the documented reconciliation threshold

## Risk-Control Requirements

All configured risk controls must be demonstrated during paper / daemon burn-in:

- max daily realized loss block
- max open exposure block
- max active intent count per symbol block
- consecutive-loss cooldown block
- stale market-data lockout
- stale execution-state lockout
- operator emergency stop
- duplicate active-intent suppression

Each control must show:

- trigger condition
- recorded blocker reason
- successful prevention of execution advancement
- operator-visible recovery path

## Operator Signoffs

The following manual signoffs are required before a go decision can even be considered:

- trading operator signoff
- release / runtime signoff
- risk-control signoff
- reconciliation signoff
- incident-response / rollback signoff

All signoffs must point to the exact evidence pack used for review.

## Automatic No-Go Conditions

Any one of the following is enough to block live pilot planning:

- any widening of execution eligibility beyond `verified_paper_trade`
- unresolved read-after-write inconsistency on traces or risk records
- unresolved stale-data or stale-sync false negatives
- inability to explain blocker clusters for reviewed misses
- unbounded duplicate active-intent creation
- emergency stop failure
- risk block that fails to halt executable advancement
- missing incident rollback drill
- missing operator signoff

## Decision Output

The checklist result must be recorded as one of:

- `no_go`
- `hold_for_more_shadow_evidence`
- `ready_for_controlled_live_planning`

`ready_for_controlled_live_planning` still means planning only, not live deployment approval.
