# ICT House Spec

This is the current house specification for the future trading-analysis skill.

The spec is intentionally conservative. Anything unresolved stays unresolved until you define it.

## Current Mode

- `Skill status:` draft
- `Execution mode:` analysis plus manual paper-trade simulation
- `Live order placement:` not authorized
- `Paper trading:` enabled for manual testing; Bybit testnet planning is allowed, optional manual testnet submission may be used, no live auto-execution

## Personal Trading Method Snapshot

- `Method family:` ICT
- `Primary concepts currently trusted:` dealing range, premium/discount, equilibrium, liquidity, IRL, ERL, MSS, displacement, FVG, CE, kill zones, Judas Swing, OTE, narrative
- `Concepts not yet trusted for automation:` order block, breaker block, mitigation block, rejection block, Turtle Soup, BPR, IFVG

## Scope

- `Instrument universe:` Crypto majors
- `Primary market:` BTCUSDT, ETHUSDT
- `Approved chart-study proxies:` BTCUSD and ETHUSD spot charts when exact USDT charts are unavailable
- `Timezone:` UTC+2 chart view, but use UTC as the canonical reference when writing rules, journaling setups, or converting session windows
- `Long-term context timeframe:` 4H
- `Narrative timeframe:` 15m
- `Execution timeframe:` 5m
- `Market condition focus:` intraday reversal or continuation inside a 4H dealing range after meaningful liquidity interaction during London or New York activity windows

## Canonical House Workflow

The canonical house workflow is:

1. `DRT`
2. `Bias`
3. `Narrative`
4. `Context`
5. `Execution`

Execution must not stand in for the first four layers. If DRT, bias, narrative, or context are unclear, there is no valid paper-trade setup even if a lower-timeframe FVG appears.

## House Definitions

### DRT - Determine Dealing Range

- `Current status:` canonical starter default
- `Definition:` anchor the active 4H dealing range on the most recent clear external swing high and external swing low. Mark the range high, range low, equilibrium, premium, and discount. Separate internal range liquidity from external range liquidity before forming a trade idea.
- `What it decides:` where price sits inside the active range, which side of the range is being attacked, and whether the next read should be reversal, continuation, or no-trade.
- `Important note:` the dealing range is the first premise. If the range is wrong, premium/discount, liquidity, bias, and execution are all corrupted.

### Liquidity

- `Current status:` canonical starter default
- `Definition:` use obvious equal highs, equal lows, prior day high/low, Asian range high/low, and recent 15m/4H swing extremes as the main BSL and SSL map. Treat random minor wicks as noise unless price reacted clearly from them before.
- `Internal vs external:` internal liquidity sits inside the active dealing range; external liquidity sits at or beyond the dealing-range boundaries.
- `Important note:` the key question is not only whether liquidity was touched, but whether price raided and rejected it or closed through and accepted it.

### Bias

- `Current status:` canonical starter default
- `Definition:` bias comes from where price is inside the dealing range and what liquidity interaction just happened.
- `Starter interpretation rules:`
  - raid SSL near discount / range low and reject it -> bullish reversal bias
  - raid BSL near premium / range high and reject it -> bearish reversal bias
  - close and hold through BSL at the high side of the range -> bullish continuation bias toward the next external liquidity
  - close and hold through SSL at the low side of the range -> bearish continuation bias toward the next external liquidity
  - price at equilibrium without a meaningful liquidity decision -> neutral / likely choppy until the narrative becomes clearer
- `Important note:` bias is not a generic trend label. It is a location-and-liquidity judgment about which side of the dealing range algos are likely defending.

### PD Arrays

- `Current status:` canonical interpretation layer
- `Definition:` PD arrays are price-delivery arrays used inside the dealing range. The important read is not just the name of the array, but:
  - where it forms inside the range
  - whether it forms in premium, discount, or equilibrium
  - whether it is being respected or disrespected
  - what the candle behavior is doing there
- `Important note:` PD arrays help determine bias and narrative. They are not only entry zones.

### PD Array Location Rules

- `Current status:` canonical starter default
- `House read:` a PD array must always be read relative to the active dealing range.
- `Starter location rules:`
  - bullish-supportive arrays forming in discount matter more than the same arrays forming late into premium
  - bearish-supportive arrays forming in premium matter more than the same arrays forming late into discount
  - arrays forming around equilibrium need stronger context because equilibrium is more prone to chop and rebalance
  - internal arrays help explain range delivery; external arrays help explain expansion targets and continuation
- `Important note:` where the array forms is part of the bias decision.

### PD Array Respect / Disrespect

- `Current status:` canonical starter default
- `Definition:` respect means price reacts in a way that preserves the directional role of the array. Disrespect means price meaningfully violates that role.
- `Starter behavior rules:`
  - wick into the array and close back inside it can support respect
  - repeated candles defending the edge of the array can support respect
  - a full-bodied close through the array can signal disrespect
  - repeated acceptance outside the array weakens it more than a single probing wick
  - candle sequence matters: one probing candle is different from multiple closing candles accepting through the zone
- `Important note:` respect vs disrespect is part of narrative state, not a minor confirmation detail.

### Narrative

- `Current status:` canonical starter default
- `Definition:` narrative is the story of algorithmic delivery inside the active dealing range.
- `Questions it must answer:`
  - which liquidity has already been taken?
  - which liquidity is still open?
  - is price rejecting a sweep, accepting through a boundary, rebalancing, or exhausting?
  - are FVGs supporting repricing, being respected as continuation arrays, or getting disrespected?
  - does the move read as reversal, continuation, breakaway, measuring, or terminus behavior?
- `Important note:` narrative comes before execution. If you cannot explain the story inside the dealing range, the lower timeframe does not get to rescue the setup.

### Context

- `Current status:` canonical starter default
- `Definition:` context escalates the narrative with bigger-picture alignment and time.
- `Context checks:`
  - is the 15m move a retracement inside a 4H continuation, or the start of a 4H reversal?
  - is the liquidity event forming in London / New York activity windows?
  - is the move happening at a quality time of day, or in dead / low-quality hours?
  - is the current instrument cleaner than its peer market, or diverging in a useful way?
- `Important note:` valid execution outside valid context is still a no-trade by house default.

### MSS

- `Current status:` canonical starter default
- `Definition:` MSS is the 15m structural confirmation that the dealing-range narrative is expressing itself in the intended direction.
- `Starter default:` after the meaningful liquidity event in the active range, require a decisive 15m close through the most recent opposing short-term swing point in the intended trade direction.
- `Important note:` MSS is not the entry. It is the narrative-confirmation layer between 4H context and 5m execution.

### Displacement

- `Current status:` canonical starter default
- `Definition:` define displacement as a clear 5m impulsive response that follows the 15m MSS, moves away from the level with urgency, and creates the imbalance used for execution.
- `Important note:` displacement should come from the same reaction leg that follows the 15m MSS. Slow grinding moves do not count.

### FVG

- `Current status:` canonical starter default
- `Definition:` use a wick-to-wick three-candle imbalance model on the 5m chart by starter default. Prefer fresh FVGs created by the displacement leg that follows the 15m MSS.
- `Important note:` the FVG is the execution zone, not the reason for the trade. CE is a refinement level, not a standalone reason to enter.

### BISI / SIBI

- `Current status:` canonical starter default
- `Definition:` use `BISI` for bullish imbalance arrays and `SIBI` for bearish imbalance arrays when the directional naming is helpful.
- `Important note:` the directional label does not override location. A BISI formed in the wrong place in the dealing range can still be weak or late.

### OTE

- `Current status:` yes - starter default
- `Definition:` treat OTE as a preferred entry refinement, not the only reason to trade. The setup still needs DRT, bias, narrative, context, 15m MSS, 5m displacement, and a valid 5m FVG.

### Order Block / Breaker Block / Mitigation Block / Rejection Block

- `Current status:` under observation, not primary starter triggers
- `Definition:` these are valid PD arrays, but the house model does not yet trust them as primary automation-safe triggers.
- `What matters most right now:`
  - where they form inside the dealing range
  - whether they align with current bias and narrative
  - whether price is respecting or disrespecting them
  - what the candle behavior is saying there
- `Candle-behavior read:`
  - wick rejection and close back inside the array can support respect
  - full-bodied closes through the array can support disrespect
  - repeated closes beyond the array strengthen the disrespect read
  - repeated failure to get acceptance beyond the array can strengthen the rejection read
- `Important note:` do not treat the array name itself as sufficient. The behavior around it matters more than the label.

## Canonical Starter Model

This replaces the older draft that compressed the setup into `15m sweep -> 5m MSS -> displacement -> FVG return`.

The canonical starter model is now:

1. determine the 4H dealing range
2. derive bias from location plus liquidity interaction
3. explain the narrative inside the range
4. validate context with higher timeframe plus session / time
5. wait for 15m MSS aligned with that narrative
6. wait for 5m displacement that follows the 15m MSS
7. use the fresh 5m FVG / CE as the execution zone

### Bullish Reversal Starter

1. 4H price raids SSL near discount / range low and rejects it.
2. Bias shifts bullish because the low-side liquidity was raided and not accepted.
3. The narrative points to upside rebalance or expansion toward open liquidity above.
4. Context is valid: higher-timeframe premise still supports the idea and session / time are acceptable.
5. 15m prints bullish MSS.
6. 5m prints bullish displacement from that MSS leg and leaves a fresh bullish FVG.
7. Entry is considered only on the 5m FVG / CE retest, ideally without chasing.

### Bearish Reversal Starter

1. 4H price raids BSL near premium / range high and rejects it.
2. Bias shifts bearish because the high-side liquidity was raided and not accepted.
3. The narrative points to downside rebalance or expansion toward open liquidity below.
4. Context is valid: higher-timeframe premise still supports the idea and session / time are acceptable.
5. 15m prints bearish MSS.
6. 5m prints bearish displacement from that MSS leg and leaves a fresh bearish FVG.
7. Entry is considered only on the 5m FVG / CE retest, ideally without chasing.

### Bullish Continuation Starter

1. The 4H dealing range and liquidity map support further upside delivery.
2. A prior BSL interaction is accepted through or defended in a way that supports continuation rather than reversal.
3. The narrative still points higher and does not read as terminus / exhaustion.
4. Context is valid.
5. 15m prints or preserves bullish MSS in the intended direction.
6. 5m prints bullish displacement and leaves a fresh bullish FVG for entry.

### Bearish Continuation Starter

1. The 4H dealing range and liquidity map support further downside delivery.
2. A prior SSL interaction is accepted through or defended in a way that supports continuation rather than reversal.
3. The narrative still points lower and does not read as terminus / exhaustion.
4. Context is valid.
5. 15m prints or preserves bearish MSS in the intended direction.
6. 5m prints bearish displacement and leaves a fresh bearish FVG for entry.

### What Cancels The Starter Model

- the 4H dealing range is unclear
- premium / discount / equilibrium are unclear
- the liquidity event is unclear or happened in the wrong place in the range
- bias is unresolved or price is stuck around equilibrium chop
- the relevant PD arrays are forming in the wrong place in the range
- the key array is being clearly disrespected when the thesis requires respect
- the narrative cannot be explained as reversal, continuation, or a clean rebalance
- 15m MSS is absent or forms away from the meaningful liquidity event
- 5m displacement is weak or disconnected from the MSS leg
- no fresh 5m FVG forms from the displacement leg
- the move happens outside the valid session / time window
- the entry is a chase rather than a proper return to the execution array

## Crypto-Specific Notes

- Crypto trades continuously, but this model still prefers London and New York activity windows for cleaner intraday movement.
- Prior day high/low and the Asian range remain useful liquidity references even though BTC and ETH trade 24/7.
- Weekend conditions are allowed but should be treated with lower confidence by starter default until you decide otherwise.

## Default Analysis Sequence

Until you replace it, the skill should analyze in this order:

1. determine the active 4H dealing range
2. map internal and external liquidity
3. derive bias from location plus liquidity interaction
4. read the PD arrays by location plus respect / disrespect
5. explain the narrative inside the range
6. apply higher-timeframe and session / time context
7. wait for 15m MSS in the intended direction
8. wait for 5m displacement plus fresh 5m FVG
9. check entry, invalidation, and targets
10. invalidate the idea if quality drops at any layer

## Hard Safety Gates

- Do not place live trades.
- Do not size positions outside the local execution spec.
- Do not claim broker-ready entries.
- Do not treat unstable concepts as signals without a house definition.
- Do not convert a paper-trade plan into a live order plan.

Bybit testnet order planning may be used only through the local execution spec and only for manual review or explicit manual testnet submission.

## Required User Inputs Before Automation

- market and instruments
- timeframe stack
- dealing-range rules
- liquidity raid vs close-through rules
- bias rules
- narrative-state rules
- context and session rules
- 15m MSS rules
- 5m displacement rules
- 5m FVG / CE entry rules
- invalidation rule
- target rule
- risk rule

## Immediate Next Task

Collect real BTCUSDT and ETHUSDT chart examples that show:

- 4H dealing-range definition
- liquidity raid vs close-through behavior
- reversal vs continuation narrative
- 15m MSS quality
- 5m displacement plus FVG execution quality

Then refine the rules from evidence instead of theory alone.

## Paper-Trading Promotion Gates

The current model is allowed to generate manual paper-trade plans only when:

- the chart is BTCUSDT, ETHUSDT, or an approved BTC spot proxy
- the timeframe stack includes 4H, 15m, and 5m context
- the setup matches the canonical DRT -> Bias -> Narrative -> Context -> Execution workflow closely enough to be more than context-only
- the trade is logged in the paper-trading journal before outcome review

The model is not ready for any live execution upgrade until:

- at least several paper-trading examples are logged
- invalid setups and losing setups are reviewed, not just winners
- rules are refined from the journal results
