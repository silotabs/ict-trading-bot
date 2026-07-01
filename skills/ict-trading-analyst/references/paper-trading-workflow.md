# Paper Trading Workflow

Use this workflow when the user wants to test setups without live execution.

## Goal

Turn chart analysis into a disciplined paper-trade decision and journal entry.

## Decide First

Return one of:

- `verified_paper_trade`
- `scanner_candidate`
- `journal_only`
- `no paper trade`
- `unclear`

Do not default to a tradable label just because the chart has movement.

## Conditions For A Paper Trade

Only allow `verified_paper_trade` when:

- the setup matches the current DRT -> Bias -> Narrative -> Context -> Execution model well enough
- the entry is not already chased
- invalidation is clear enough to explain
- target logic is clear enough to explain
- the setup is scanner-verified rather than manually asserted

Use `journal_only` when the structure is worth storing and reviewing but the payload is still manual assertion only.

## Conditions For No Paper Trade

Return `no paper trade` when:

- the setup is only higher-timeframe context
- the chart is outside the allowed session window
- sweep, MSS, displacement, or fresh FVG are missing
- the chart is too messy to define invalidation cleanly

## Journal Behavior

When a paper trade is valid, give the user the fields needed for:

- date
- instrument
- session
- direction
- trigger
- entry zone
- invalidation idea
- target logic
- rule blockers
- screenshot path

Point the user to:

- `../../../dossier/10_paper_trade_journal.md`

## Review Behavior

When the user asks for review, compare the setup against:

- `../../../dossier/09_paper_trading_protocol.md`
- `../../../dossier/11_review_rubric.md`
