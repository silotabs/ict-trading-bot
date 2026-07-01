# ICT Research Dossier

## Purpose

This dossier is the research base for a future trading-analysis skill built around Inner Circle Trader (ICT) concepts.

The immediate goal is not to automate trading yet. The goal is to:

- understand the vocabulary and concept hierarchy
- separate official ICT teaching from community interpretation
- identify which concepts are stable enough to formalize into rules
- record open questions before any execution logic is written

## What ICT Appears To Be

Based on the official ICT website and official YouTube channel material, ICT is Michael J. Huddleston's price-action teaching framework centered on liquidity, market structure, dealing ranges, timing, and delivery inefficiencies.

The official site presents ICT as Michael J. Huddleston's teaching library and mentorship archive:

- https://www.theinnercircletrader.com/

## Working Research Constraints

- Official ICT teaching exists mostly in long-form videos, not in a compact written specification.
- A large amount of usable written material comes from secondary explainers and TradingView implementations.
- Some terms are fairly stable across sources, especially `FVG`, `liquidity`, `premium/discount`, `OTE`, and `Power of 3`.
- Some terms are noticeably less stable, especially `order block`, `breaker block`, `mitigation block`, `IFVG`, and other refinements.

## Canonical House Read

The current house read is:

1. `DRT`
2. `Bias`
3. `Narrative`
4. `Context`
5. `Execution`

This means the dossier should not treat PD arrays as isolated entry gadgets.

They must be read as part of the dealing-range story:

- where the array forms inside the active range
- whether it forms in premium, discount, or equilibrium
- whether it is internal or external relative to the range
- whether price is respecting it, wicking through it, or closing decisively through it
- whether the candle behavior implies defense, rejection, rebalance, continuation, or failure

In other words, PD arrays help determine:

- bias
- narrative
- execution quality

not just entry location.

## Research Rule For This Dossier

Every concept should be labeled as one of:

- `official`: directly supported by official ICT site or official ICT video/channel material
- `community-standard`: widely used in ICT/SMC circles, but not confirmed here as a canonical written ICT definition
- `community-extension`: later refinement, implementation detail, or popular derivative interpretation

If a statement is not directly supported by a source, it should be treated as inference, not doctrine.

## What This Means For The Future Skill

The future skill should reason in this order:

1. DRT
2. Bias from location plus liquidity interaction
3. Narrative inside the range
4. Context and time
5. Execution
6. Risk and invalidation

PD arrays must be evaluated at all three of these layers:

- `Bias:` where the array forms in the range
- `Narrative:` whether it is being respected or disrespected
- `Execution:` whether candle behavior confirms a valid entry

The future skill should not place live trades until:

- your personal ICT rules are written explicitly
- each concept is translated into operational conditions
- ambiguous terms are narrowed to one house definition
- paper-trading or replay validation is completed

## Next Research Priorities

- collect official ICT video references for each core concept
- capture screenshots or timestamps for canonical examples
- write your house definitions for ambiguous zones and entry triggers
- decide which concepts are required versus optional for your personal model
