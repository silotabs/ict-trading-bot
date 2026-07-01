# Core ICT Concepts

## 1. Range Framing

### Determine Dealing Range (DRT)

- Status: `house-canonical`
- Short definition: define the active dealing range first, usually from the most relevant external swing high and swing low on the long-term context timeframe.
- Why it matters: the range decides premium, discount, equilibrium, IRL, ERL, and the side of the market most likely being defended.
- Caution: if the dealing range is wrong, every later read is distorted.

### Premium / Discount / Equilibrium

- Status: `official/community-standard`
- Short definition: the upper half of the range is premium, the lower half is discount, and the 50% midpoint is equilibrium.
- Why it matters: this is the base location filter for longs, shorts, reversal reads, and continuation reads.
- Caution: this only works after the dealing range is defined consistently.

### PD Arrays

- Status: `official/community-standard`
- Short definition: the family of price-delivery or reaction arrays used inside a dealing range.
- Why it matters: it groups together the zones ICT traders watch for continuation or reversal.
- Caution: different traders include different subtypes under `PD arrays`.
- House note: the important read is not only the array itself, but where it forms in the dealing range and how price behaves inside it.

### PD Array Location And Behavior

- Status: `house-canonical`
- Short definition: PD arrays help determine bias and narrative by their location in the dealing range and by whether price respects or disrespects them.
- Why it matters: the same array means different things depending on whether it forms in premium, discount, or equilibrium, and whether price wicks into it, closes through it, or keeps accepting inside it.
- House read:
  - array in discount that is respected can support bullish bias
  - array in premium that is respected can support bearish bias
  - repeated disrespect of an array weakens its directional value
  - a full-body close through an array means something very different from a wick into it that closes back inside
  - candle behavior at the array is part of the narrative, not just confirmation noise

## 2. Liquidity And Bias

### Buy-Side Liquidity (BSL) / Sell-Side Liquidity (SSL)

- Status: `official/community-standard`
- Short definition: stop clusters or obvious resting liquidity above highs or below lows.
- Why it matters: price is often narrated as moving toward liquidity before repricing.
- Caution: some traders use `liquidity` very narrowly, others much more broadly.

### Internal Range Liquidity (IRL) / External Range Liquidity (ERL)

- Status: `official/community-standard`
- Short definition: internal liquidity sits inside the active range; external liquidity sits at or beyond the boundaries.
- Why it matters: it helps frame whether price is still working inside the range or expanding beyond it.
- Caution: implementation rules vary a lot in community tools.

### Bias

- Status: `house-canonical`
- Short definition: bias comes from where price is inside the dealing range and what liquidity interaction just happened.
- Why it matters: it converts range location plus liquidity behavior into a directional read.
- Caution: bias is not just trend. Rejection vs close-through acceptance matters.

## 3. Narrative And Structure

### Narrative

- Status: `house-canonical`
- Short definition: the story of algorithmic delivery inside the active range.
- Why it matters: this is where reversal, continuation, breakaway, measuring, and terminus behavior get interpreted.
- Caution: if the narrative cannot be explained clearly, execution should not be forced.

### Break Of Structure (BOS) / Market Structure Shift (MSS)

- Status: `community-standard`, with strong official support for MSS
- Short definition: structure breaks or shifts that signal continuation or directional change.
- Why it matters: in the current house model, MSS is the 15m structural confirmation that the range narrative is expressing itself.
- Caution: traders disagree on exactly which swing counts, and whether BOS and MSS should be treated as separate or overlapping signals.

## 4. Delivery And Imbalance

### Displacement

- Status: `official/community-standard`
- Short definition: an aggressive directional move that signals repricing and often leaves imbalance behind.
- Why it matters: in the current house model, 5m displacement is the execution confirmation that follows the 15m MSS.
- Caution: the threshold for a real displacement move is often discretionary.

### Fair Value Gap (FVG)

- Status: `official/community-standard`
- Short definition: a three-candle imbalance where the first and third candles do not fully overlap.
- Why it matters: probably the most widely standardized ICT concept in community practice, and the starter execution array in the current house model.
- Caution: some traders require wick-to-wick gaps, some use body-based filters, and some only trade FVGs with displacement and context.

### Buyside Imbalance Sellside Inefficiency (BISI) / Sellside Imbalance Buyside Inefficiency (SIBI)

- Status: `community-standard`
- Short definition: directional naming for bullish and bearish FVG-style imbalance arrays.
- Why it matters: it makes the directional role of the FVG more explicit.
- House read:
  - `BISI:` bullish imbalance used as a buy-side supportive array
  - `SIBI:` bearish imbalance used as a sell-side supportive array
  - the same directional imbalance has different meaning depending on where it forms inside the active dealing range
  - a BISI in discount can support bullish bias more strongly than a BISI printed late into premium
  - a SIBI in premium can support bearish bias more strongly than one printed late into discount
- Caution: the directional label alone is not enough; respect/disrespect and location must still be read.

### Consequent Encroachment (CE)

- Status: `official/community-standard`
- Short definition: the midpoint of an FVG, OB, or wick range.
- Why it matters: often treated as a more precise reaction level than the full zone.
- Caution: not every trader uses CE as a mandatory entry condition.

### Balanced Price Range (BPR)

- Status: `community-extension`
- Short definition: overlapping opposing FVGs creating a temporary balance zone.
- Why it matters: used by many ICT-style traders as a reaction or target area.
- Caution: not treated here as a core canonical concept yet.

### Inversion Fair Value Gap (IFVG)

- Status: `community-extension`
- Short definition: a formerly valid FVG that fails and is then treated as a flipped zone.
- Why it matters: often used by indicator authors and rule-based implementations.
- Caution: appears more standardized in community tooling than in core official material reviewed so far.
- House note: IFVG matters most when the disrespect is clear. A wick through the array is not the same as decisive candle acceptance through it.

## 5. Timing And Session Logic

### Kill Zones

- Status: `official/community-standard`
- Short definition: time windows, usually around active sessions, where ICT traders expect key movement.
- Why it matters: session timing is a major filter in ICT workflow.
- Caution: exact time windows need to be normalized for local timezone and market traded.

### Judas Swing

- Status: `official/community-standard`
- Short definition: an early-session deceptive move that raids liquidity before the intended move develops.
- Why it matters: it links time, liquidity, and reversal logic.
- Caution: many community summaries simplify it into a generic false-break pattern.

### Power Of 3 (PO3)

- Status: `official`
- Short definition: accumulation, manipulation, distribution.
- Why it matters: it is a compact narrative model for many ICT setups.
- Caution: mapping a live chart into the three phases is still discretionary.

## 6. Execution Models

### OTE (Optimal Trade Entry)

- Status: `official/community-standard`
- Short definition: a preferred retracement entry zone inside a larger setup, often expressed with fib levels.
- Why it matters: one of the clearest execution concepts in ICT.
- Caution: OTE alone is not a complete model without DRT, bias, narrative, context, and structure.

### Order Block (OB)

- Status: `community-standard`, but definition is unstable
- Short definition: a candle or zone treated as the origin of institutional repricing.
- Why it matters: widely used for entries and mitigations.
- Caution: not trusted as an automation-safe primary execution model in the current house workflow.

### Breaker Block (BB)

- Status: `community-standard`
- Short definition: a former order block that fails and later acts as a flipped continuation or reversal array.
- Why it matters: can show that price has decisively disrespected the original array and repriced through it.
- Caution: the flip only matters when the disrespect is real, not when price merely wicks through the zone and closes back inside.

### Mitigation Block (MB)

- Status: `community-standard`
- Short definition: a zone price revisits to mitigate prior imbalance or prior positioning before continuing the move.
- Why it matters: can help explain rebalance behavior inside the range.
- Caution: mitigation logic is easy to over-label after the fact; location in the dealing range still matters more than the name.

### Rejection Block (RB)

- Status: `community-standard`
- Short definition: a reaction candle or zone showing sharp rejection from a price area.
- Why it matters: useful for reading whether price is rejecting a PD array rather than accepting through it.
- Caution: rejection quality must be judged from the candle behavior:
  - wick rejection and close back inside the array
  - multiple candles respecting the edge
  - failure to get acceptance beyond the zone

## Current Working View

The strongest candidates for early formalization are:

- DRT
- premium / discount / equilibrium
- liquidity map
- bias from location plus liquidity interaction
- narrative state
- PD array location and respect / disrespect
- 15m MSS
- 5m displacement
- 5m FVG
- CE
- kill-zone timing
- OTE

The weakest candidates for early automation are:

- order block as a standalone trigger
- mitigation block as a standalone trigger
- breaker block as a standalone trigger
- rejection block as a standalone trigger
- Turtle Soup
- BPR
- IFVG

Those weaker candidates may still be useful, but they need stable house definitions for:

- where they form in the dealing range
- whether price is respecting or disrespecting them
- what candle behavior confirms rejection vs acceptance

before a skill should act on them.
