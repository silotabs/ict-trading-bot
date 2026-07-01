# Alignment Migration Note

## Scope

This note covers the DRT-first alignment pass for Phases 1-3:

1. DRT
2. Bias
3. Narrative / Context
4. Execution demotion and detector honesty

## Old Behavior

- The scanner historically leaned on an execution-first chain:
  - sweep
  - MSS
  - displacement
  - FVG
- The 4H dealing range was previously summarized from rolling window extremes rather than explicit external-swing anchors.
- Manual checklist assertions could look too close to scanner-derived validation in some flows.
- Screenshot paths and chart URLs were accepted as context, but the surrounding docs could imply more chart-reading capability than the engine actually had.
- README examples still used stale checklist fields such as `liquidity_sweep`.

## New Behavior

- The engine now anchors the 4H dealing range from preserved external swing highs and lows.
- 4H liquidity interaction is now a first-class input to bias:
  - touch
  - raid and reject
  - close-through / acceptance
- Narrative and context are now explicit engine outputs.
- Liquidity-map context is now first-class and includes:
  - prior day high / low
  - configured Asian range high / low
  - equal-high / equal-low candidates
  - recent 15m / 4H swing extremes
  - internal / external liquidity
- Execution detectors remain in the system, but they now report structured uncertainty and are explicitly subordinate to the higher-order layers.
- Manual payloads are now clearly distinguished from scanner-verified payloads through:
  - `source_mode`
  - verification state
  - decision semantics

## Decision / Schema Changes

### Checklist

- Canonical field: `liquidity_event`
- Compatibility alias still accepted: `liquidity_sweep`

### Verification

- `source_mode = manual_assertion | scanner_verified | hybrid`
- `visual_analysis_state = not_run | manual_context_only | partial | verified`

### Decisions

- `journal_only`
- `scanner_candidate`
- `verified_paper_trade`
- `no_paper_trade`
- `unclear`

## Safety Posture

- Live trading remains unauthorized.
- Guarded testnet automation still exists in the repo, but the default policy files remain disabled.
- Screenshot / chart handling remains supporting context only unless a separate visual-analysis stage explicitly says otherwise.

## Still Unresolved

- The Asian range definition is still a starter configured assumption, not a finalized house truth.
- Narrative does not yet classify breakaway / measuring / terminus with full house-grade precision.
- PD-array classification beyond the current starter execution arrays is still partial.
- The execution detectors remain heuristic and candle-based; they are more honest now, but not fully discretionary-equivalent.
