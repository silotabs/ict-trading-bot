# Shadow Metrics Requirements

## Purpose

These metrics define what the shadow-mode evidence pack must show before any controlled live deployment planning can be considered.

The intent is to prove operational maturity, not to optimize or retune strategy logic.

## Minimum Observation Window

- `30` consecutive calendar days
- both `BTCUSDT` and `ETHUSDT` covered
- event-driven close handling active for:
  - `5m`
  - `15m`
  - `4h`

## Core Shadow Metrics

### Coverage

- confirmed candle-close coverage: `>= 99.5%`
- unexplained missed closes: `0`
- duplicate handled-close rate after dedupe: `<= 0.5%`
- fallback polling share of handled bars: `<= 2.0%`

### Trace Integrity

- shadow traces successfully persisted for handled shadow scans: `>= 99.9%`
- read-after-write trace visibility: expected inside the same operator review window
- unexplained empty-read anomalies after successful write: `0` over the final `7` burn-in days

### Opportunity Review

- minimum reviewed `near_miss` traces: `10`
- minimum reviewed `awaiting_confirmation` traces: `10`
- minimum reviewed `context_watch` traces: `10`
- minimum reviewed human-identified false negatives: `25`

### Blocker Stability

- top `5` blocker clusters explain at least `70%` of reviewed misses
- blocker cluster ordering should remain materially stable across comparable session windows
- any blocker cluster that spikes by more than `2x` week-over-week requires explicit explanation

### Execution Boundary Integrity

- `verified_paper_trade` remains the only execution-eligible decision
- count of non-eligible decisions that advanced as if eligible: `0`
- count of shadow traces that created execution by shadow state alone: `0`

### OMS / Risk Integrity

- duplicate active execution intents for the same eligible signal: `0`
- unresolved orphan active intent count: `0`
- stale sync block failures: `0`
- stale market-data block failures: `0`
- emergency stop failures: `0`

## Review Outputs

Each shadow review cycle should produce:

- by-decision counts
- by-opportunity-state counts
- by-blocker-class counts
- blocker-cluster summary
- session-window distribution
- symbol distribution
- reviewed false-negative notes

## Required Escalations

Shadow evidence must trigger escalation, not silent tolerance, when any of the following occurs:

- repeated unexplained missed trades seen by operators
- repeated empty-read anomalies after successful writes
- unstable blocker clusters with no operational explanation
- shadow traces missing required fields for review
- event-driven coverage degradation
- repeated fallback polling dominance

## Current Known Observation To Carry Forward

During P6, an immediate post-write empty-read was observed once on a newly written shadow trace before subsequent reads returned the stored record correctly.

That observation must be treated as an open operational concern until one of the following is true:

- root cause is identified and bounded, or
- the behavior does not recur for `7` consecutive burn-in days
