# Canonical Concept Translation Plan

This file bridges the current canonical house model to future detector and daemon changes.

## Canonical Workflow

The canonical workflow is:

1. `DRT`
2. `Bias`
3. `Narrative`
4. `Context`
5. `Execution`

Execution means:

- `15m MSS`
- `5m displacement`
- `5m FVG / CE entry`

PD arrays participate throughout the workflow, not only at execution:

- `DRT`: where arrays formed inside the range
- `Bias`: which arrays are being defended or violated
- `Narrative`: whether arrays are respecting continuation, reversal, breakaway, measuring, or terminus behavior
- `Execution`: which array offers the cleanest 5m entry refinement

## Current Implementation Mismatch

The current live implementation still leans on an older execution-first draft:

- it detects a recent 15m sweep heuristic
- it checks MSS on 5m
- it checks 5m displacement
- it checks 5m FVG

This is useful as a starter heuristic, but it does not yet encode the canonical workflow.

The main mismatches are:

1. `DRT is not first-class in the detector stack`
   - the system infers a 4H bias, but not a full dealing-range state with internal vs external liquidity ownership
   - the system does not yet model where the key PD arrays formed inside that range

2. `Bias is too compressed`
   - bias is currently closer to a directional checklist than a location-plus-liquidity judgment
   - respect versus disrespect of PD arrays is not yet a first-class input

3. `Narrative is missing as an explicit state`
   - reversal, continuation, breakaway, measuring, and terminus behavior are not yet modeled directly
   - arrays are not yet read as supporting or failing the narrative

4. `MSS is on the wrong timeframe`
   - canonical model: `15m MSS`
   - live draft: `5m MSS`

5. `Execution is partly disconnected from the structural event`
   - canonical model: 5m displacement and 5m FVG must come from the reaction leg that follows the 15m MSS
   - live draft: the features are recent and directionally aligned, but not fully chained together

## Target Detector Ownership

### 4H Layer

The 4H layer should own:

- active dealing range high / low
- equilibrium
- premium / discount
- internal liquidity map
- external liquidity map
- main open liquidity objective
- current location inside the range
- PD arrays formed inside the active range
- whether those arrays formed in premium, discount, or equilibrium
- whether those arrays sit against internal or external liquidity

### Bias Layer

Bias should be derived from:

- location inside the dealing range
- liquidity event type
  - raid and reject
  - close-through and accept
- defended side of the range
- reversal vs continuation tendency
- PD arrays being respected
- PD arrays being disrespected
- candle behavior at those arrays
  - wick and close back inside
  - full-bodied close through
  - repeated acceptance beyond
  - repeated failure beyond

### Narrative Layer

Narrative should classify the current read as one of:

- reversal
- continuation
- breakaway
- measuring
- terminus
- unclear

Starter narrative questions:

- which liquidity has already been taken?
- which liquidity is still open?
- are FVGs supporting continuation or failing?
- which PD arrays are holding the story together?
- which PD arrays have already failed?
- is price rebalancing or exhausting?

### Context Layer

Context should confirm:

- higher-timeframe alignment
- session validity
- time-of-day quality
- peer-market cleanliness / asymmetry if used

### Execution Layer

Execution should require:

1. 15m MSS in the intended direction after the meaningful liquidity event
2. 5m displacement from that MSS reaction leg
3. fresh 5m FVG created by that displacement
4. entry on FVG / CE retest without chasing

Execution candidates may also track:

- 5m OB
- 5m BB
- 5m MB
- 5m RB
- 5m IFVG

But only after the house rules say how each one should be read by location and behavior.

## PD Array Translation Requirements

The detector layer eventually needs to model, at minimum:

- `FVG / BISI / SIBI`
- `IFVG`
- `OB`
- `BB`
- `MB`
- `RB`

For each tracked PD array, the translation should eventually answer:

1. where did it form inside the active dealing range?
2. did it form in premium, discount, or equilibrium?
3. is it attached to internal or external liquidity?
4. is price respecting it or disrespecting it?
5. is that read based on wick behavior, body closes, or repeated acceptance / rejection?
6. what narrative weight does that array have right now?

## Recommended Refactor Order

1. `Add first-class 4H DRT state`
   - range high / low
   - equilibrium
   - premium / discount
   - internal / external liquidity references
   - PD array registry by location

2. `Replace generic bias with location-plus-liquidity bias`
   - raid and reject
   - close-through acceptance
   - equilibrium-neutral fallback
   - PD array respect / disrespect evaluation

3. `Add explicit narrative state`
   - reversal / continuation / breakaway / measuring / terminus / unclear
   - narrative support / failure from PD arrays

4. `Move MSS to 15m`
   - MSS should be detected on 15m, not 5m
   - MSS should be anchored to the meaningful liquidity event

5. `Constrain 5m execution to the MSS leg`
   - 5m displacement must follow the 15m MSS
   - 5m FVG must come from that displacement leg

6. `Update scoring / review / acceptance language`
   - review the concept by DRT, bias, narrative, context, and execution quality
   - stop treating execution features as if they alone represent the whole concept

## What To Keep From The Current Implementation

Keep and reuse where possible:

- 4H range and bias primitives
- recent swing detection
- displacement heuristics
- FVG heuristics
- session filters
- acceptance / revision / compare loop infrastructure

The target is not to throw away the system.
The target is to reassign the detectors to the correct conceptual layers.

## Immediate Coding Priorities

When coding resumes on the detector side, the next priorities should be:

1. `4H DRT detector`
2. `Bias-from-liquidity-state engine`
3. `15m MSS detector`
4. `5m execution-leg chaining`
5. `PD-array respect / disrespect state`
6. `Narrative state summary in daemon runtime`

## Acceptance Standard For The New Translation

The concept translation is only successful if the daemon can eventually explain a setup like this:

- active 4H dealing range
- where price is inside it
- what liquidity was raided or accepted through
- what bias that created
- what narrative price is expressing
- which PD arrays are active
- where they formed inside the dealing range
- whether price is respecting or disrespecting them
- why the current session / time is acceptable
- where 15m MSS printed
- where the 5m displacement leg formed
- where the 5m FVG entry came from

If the system still has to jump straight from sweep detection to entry heuristics, the translation is incomplete.
