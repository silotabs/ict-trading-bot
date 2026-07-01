# Paper Trading Protocol

This protocol defines how to test the current canonical ICT starter model without risking real capital.

## Objective

Use paper trading to answer these questions:

- Does the DRT -> Bias -> Narrative -> Context -> Execution workflow produce repeatable entries?
- Which parts of the workflow are actually useful?
- Which conditions lead to failure?
- Does the model work better on BTCUSDT, ETHUSDT, or both?

## Allowed Scope

- Instruments: BTCUSDT, ETHUSDT, and approved BTC spot proxies when exact USDT charts are unavailable
- Timeframe stack: 4H -> 15m -> 5m
- Starter setup family: 4H dealing range -> bias -> narrative -> context -> 15m MSS -> 5m displacement -> 5m FVG entry
- Sessions: London and New York only by starter default

## Not Allowed

- live orders
- auto execution
- changing rules mid-trade to save a bad setup
- logging only winning examples

## Pre-Trade Checklist

Mark every item before a paper trade is considered valid:

- instrument is in scope
- session / time are allowed
- 4H dealing range is clear
- premium / discount / equilibrium are clear
- the main liquidity interaction is clear
- the important PD arrays inside the range are clear
- those arrays formed in sensible locations inside the range
- the arrays being respected or disrespected are clear
- bias is clear
- narrative is clear
- 15m MSS is visible
- 5m displacement is convincing
- fresh 5m FVG is visible
- entry is not a chase
- invalidation idea is clear
- target logic is clear

If any core item is missing, the result should be `no paper trade`.

## Paper Trade Plan

Every paper trade should record:

- setup direction
- 4H dealing range read
- liquidity event and whether it was rejection or close-through acceptance
- active PD arrays and where they formed in the dealing range
- whether those arrays were being respected or disrespected
- bias
- narrative
- context and session
- 15m MSS
- 5m displacement
- 5m FVG / CE entry zone or other execution array used
- invalidation level or invalidation idea
- target 1
- target 2 or final liquidity draw
- screenshots used
- rule blockers or uncertainty

## Review Cadence

- Review each trade after completion.
- Review all trades at the end of the week.
- Separate valid losers from invalid trades.
- Keep notes on recurring failure patterns.

## Minimum Sample Rule

Do not judge the strategy from one or two trades.

Treat the first set of paper trades as discovery, not proof.

## Outcome Labels

Use one of:

- `starter valid winner`
- `starter valid loser`
- `starter invalid`
- `unclear`

Legacy `version-1` tags may still appear in older entries, but new logs should use the starter labels above.
