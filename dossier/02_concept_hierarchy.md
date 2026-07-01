# ICT Concept Hierarchy

## Top-Level Flow

1. `DRT`
2. `Bias`
3. `Narrative`
4. `Context`
5. `Execution`
6. `Risk / invalidation`
7. `Management / target`

## Dependency Map

### DRT

- dealing-range high
- dealing-range low
- equilibrium
- premium
- discount
- IRL
- ERL
- PD array location inside the range

### Bias

- where price sits inside the range
- which liquidity was raided
- whether that liquidity was rejected or accepted through
- which side of the range is likely being defended
- which PD arrays are forming in premium / discount / equilibrium
- which PD arrays are being respected
- which PD arrays are being disrespected

### Narrative

- what liquidity has already been taken
- what liquidity is still open
- reversal
- continuation
- breakaway
- measuring
- terminus
- whether arrays are supporting continuation, rebalance, or failure
- wick rejection vs full-body acceptance through an array
- repeated closes inside / outside an array

### Context

- higher-timeframe alignment
- market traded
- timeframe stack
- session / kill zone
- quality time of day

### Execution

- 15m MSS
- 5m displacement
- 5m FVG
- IFVG
- CE
- OTE
- optional reaction model under observation: OB / BB / MB / RB / Judas / Turtle Soup

### Risk / Invalidation

- invalidation beyond the structure that produced the setup
- setup expiry if the return never forms in-session
- cancel if the narrative is invalidated by opposite-side acceptance

### Management / Target

- first internal liquidity objective
- final external liquidity objective
- partials / break-even only after clear delivery

## Practical Reasoning Order For A Future Agent

When analyzing a chart, the future skill should not jump straight to entry.

It should ask:

1. What dealing range am I using?
2. Where is price inside that range?
3. What liquidity is nearest and which side has just been raided or accepted through?
4. What bias follows from that location plus liquidity interaction?
5. Which PD arrays are forming there, and are they being respected or disrespected?
6. What narrative is price expressing inside the range?
7. Is the higher-timeframe and session / time context good enough?
8. Has 15m printed MSS in the intended direction?
9. Has 5m delivered displacement and a fresh execution array from that same reaction leg?
10. Is there a valid execution entry, invalidation, and target?

If those questions cannot be answered cleanly, the future skill should return `no clear setup`.
