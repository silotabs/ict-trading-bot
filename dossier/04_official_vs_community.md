# Official Vs Community Interpretation

This file is the guardrail layer for future implementation.

## Relatively Strong Official Support

These concepts appear strongly connected to official ICT teaching or official ICT channel material reviewed in this pass:

- Power of 3
- OTE
- Judas Swing
- internal range liquidity
- market structure shift
- premium / discount framing

## Widely Used And Fairly Stable In Community Practice

These appear widely used in ICT/SMC education and tooling, but still need house definitions before automation:

- dealing range
- BSL / SSL
- displacement
- FVG
- CE
- kill zones
- BOS

## Widely Used But Definition Drift Is High

These should not be automated without explicit house rules:

- order block
- breaker block
- mitigation block
- rejection block
- IRL / ERL boundary rules
- valid versus weak FVG filters
- which swing qualifies for MSS or BOS
- how BISI / SIBI should be tagged and when the label adds value
- how to decide that a PD array was respected or disrespected
- when a wick-only interaction counts versus when a close-through is required

## Mostly Community Extensions Or Tooling Refinements

These are useful to track but should be treated as optional until personally adopted:

- IFVG
- BPR
- hidden FVG
- first presented FVG
- highly specific indicator-only labels

## House Canonical Read

For this dossier, PD arrays are not execution-only tools.
They are part of:

- `DRT`
- `Bias`
- `Narrative`
- `Execution`

That means the house definition must answer:

- where the array formed inside the dealing range
- whether it formed in premium, discount, or equilibrium
- whether it formed against internal or external liquidity
- whether price is respecting or disrespecting it
- what the candle behavior is doing at that array
  - wick into zone and close back inside
  - full-bodied close through
  - repeated acceptance beyond it
  - repeated rejection from it

## House-Definition Requirement

Before any of the unstable concepts are used for trading logic, we should lock down:

- exact dealing-range location rules
- exact premium / discount / equilibrium interpretation
- exact internal versus external liquidity relationship
- exact candle rules
- exact zone boundaries
- exact confirmation requirements
- exact invalidation rules
- exact respect / disrespect logic
- exact wick-versus-close-through logic
- exact repeated-acceptance versus rejection logic
- exact priority when multiple zones overlap

Until then, the future agent should treat them as annotations, not executable signals.
