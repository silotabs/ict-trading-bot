# Execution Spec

This file describes the machine-execution assumptions that sit between the ICT setup rules and any Bybit futures order proposal.

## Current Status

- `Mode:` Bybit testnet planning and manual submission only
- `Live trading:` not authorized
- `Primary machine-readable source:` `paper_api/config/execution_spec.json`

## What This Spec Controls

- default venue and category
- account type and collateral coin
- default leverage and max leverage
- whether market orders are allowed
- whether stop loss and take profit are mandatory
- risk per trade
- minimum risk/reward
- margin usage guardrails

## Current Defaults

- `Venue:` Bybit
- `Category:` linear
- `Collateral coin:` USDT
- `Position mode:` one_way
- `Margin mode:` isolated
- `Default leverage:` 3x
- `Max leverage:` 5x
- `Risk per trade:` 0.5% of equity
- `Max daily loss:` 2% of equity
- `Minimum RR:` 2.0
- `Partial take profit:` disabled for now
- `Market orders:` disabled for now

## Why This Exists

The ICT house spec decides whether a setup is valid.

The execution spec decides whether a valid setup is safe enough to turn into a Bybit futures order proposal.

That means:

1. the setup must pass the house rules
2. the order must pass the execution spec
3. the order must still pass exchange constraints like tick size, qty step, min notional, and leverage limits

## Concept Boundary

This spec does not decide:

- the dealing range
- the bias
- the narrative
- whether a PD array was respected or disrespected

Those belong to the house model.
Execution begins only after the setup already passed:

- `DRT`
- `Bias`
- `Narrative`
- `Context`
- `Execution`

## Execution Metadata To Preserve

Any machine-readable order proposal should eventually carry enough context to explain:

- active 4H dealing range
- premium / discount / equilibrium location
- main liquidity event
- 15m MSS reference
- 5m displacement leg
- entry array used
  - FVG / IFVG / OB / BB / MB / RB / CE / OTE
- whether the entry array was being respected or disrespected at decision time
- invalidation anchor
- target anchor

The execution engine should not reduce the setup to price, stop, and target only.

## Promotion Rule

Do not upgrade this execution spec for live trading until:

- testnet submissions are stable
- sizing behavior is reviewed across winners and losers
- restart recovery and order-state reconciliation are implemented
- exit logic is fully automated and tested
