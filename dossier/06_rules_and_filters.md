# Rules And Filters

This file converts ICT concepts into house rules.

This is still a starter execution model for analysis, not a live-trading spec.

## Market Scope

- `Allowed instruments:` BTCUSDT and ETHUSDT only for now
- `Approved chart-study proxies:` BTCUSD and ETHUSD spot charts are acceptable for analysis and paper-trade review when exact USDT charts are unavailable
- `Excluded instruments:` all other crypto pairs until the house model is stable
- `Canonical timezone:` UTC for rules and journaling, even if the chart is displayed in UTC+2

## Timeframe Stack

- `DRT timeframe:` 4H
- `Narrative timeframe:` 15m
- `Execution timeframe:` 5m

## Context Rules

- Use the active 4H dealing range before labeling premium or discount.
- Do not form a directional opinion without identifying the relevant liquidity interaction.
- `Dealing range anchor:` use the most recent clear 4H external swing high and swing low.
- `Liquidity decision required:` classify the interaction as raid and reject or close-through acceptance.
- `PD arrays must be location-aware:` read every array relative to premium, discount, equilibrium, and whether it is internal or external to the active range.
- `Higher-timeframe premise mandatory:` yes.
- `Preferred liquidity references:` prior day high, prior day low, Asian high, Asian low, equal highs/lows, and recent 4H extremes.
- `Equilibrium warning:` if price is sitting around equilibrium without a meaningful liquidity decision, downgrade the idea to neutral / likely choppy.
- `Weekend handling:` allowed, but lower confidence by starter default because structure can degrade.

## PD Array Rules

- `Primary arrays currently tracked:` FVG / BISI / SIBI / IFVG / OB / BB / MB / RB
- `Bias relevance:` arrays help determine bias by where they form in the active range and whether they are being respected or disrespected
- `Respect examples:` wick into the array and close back inside it; repeated defense of the edge; failure to gain acceptance beyond it
- `Disrespect examples:` full-bodied close through the array; repeated closes beyond the edge; clear acceptance outside the array
- `Important note:` the array label alone is not enough; candle behavior at the array matters

## Structure Rules

- `BOS:` a close through a prior swing in the current direction, used mainly as continuation context.
- `MSS:` after the meaningful liquidity event, require a 15m close through the most recent opposing short-term swing point in the intended trade direction.
- `Swing points that count:` clear 15m highs/lows with visible reaction; 5m swings are execution detail, not the primary structure premise.
- `Preferred MSS quality:` best when the break candle either contributes to the coming displacement leg or is followed immediately by it.

## Displacement Rules

- `Role:` 5m execution confirmation after 15m MSS.
- `Minimum displacement conditions:` one or more wide-body candles with visible urgency, decisive movement away from the level, and a clear move that creates the execution imbalance.
- `Displacement must leave FVG:` yes by starter default; if no fresh 5m FVG is left behind, downgrade the read to context-only.
- `Weak displacement warning:` if the move stalls immediately, overlaps heavily, or lacks follow-through, do not treat it as valid delivery.

## FVG Rules

- `FVG model:` wick-to-wick
- `Timeframe:` 5m by starter default
- `CE required:` no, but CE is preferred as a refinement
- `Only fresh FVGs tradable:` yes by starter default
- `FVG role:` execution zone created by the displacement leg, not the reason for the trade

## Zone Rules

- `Order block:` under observation only; not a primary starter trigger yet, but still relevant for bias and narrative when it forms in the right part of the range
- `Breaker block:` under observation; useful mainly when the disrespect of the prior array is decisive
- `Mitigation block:` under observation; useful mainly as a rebalance / continuation read inside the range
- `Rejection block:` under observation; useful when candle behavior clearly shows rejection rather than acceptance
- `IFVG:` under observation; useful only when the inversion is clear and the prior array was meaningfully disrespected
- `Zone priority:` DRT -> liquidity interaction -> 15m MSS -> 5m displacement -> fresh 5m FVG; other zones are secondary confluence only

## Timing Rules

- `Allowed sessions:` London and New York only by starter default
- `Kill-zone definitions:` use New York local time on TradingView or in your notes; London kill zone 02:00-05:00 New York time, New York kill zone 07:00-10:00 New York time
- `Time-of-day rule:` time of day is checked before entry; do not wait until after execution features appear to decide whether the time is acceptable
- `Judas Swing usage rules:` only use it around approved session opens after a visible liquidity draw forms; ignore random fakeouts outside the active session windows
- `Crypto note:` market is 24/7, but the model only opens new ideas during the allowed windows unless you later approve more session types

## Entry Rules

- `Exact trigger sequence:` 4H dealing range -> liquidity map -> bias -> narrative -> context -> 15m MSS -> 5m displacement -> return into fresh 5m FVG / CE -> optional OTE confluence -> entry
- `OTE required:` preferred but not mandatory; no chasing if price runs without retracement
- `Confirmation requirements:` narrative set, 15m MSS, 5m displacement, and a fresh 5m FVG inside a valid session window
- `Starter setup family:` DRT -> Bias -> Narrative -> Context -> 15m MSS -> 5m displacement -> 5m FVG entry
- `Chasing rule:` if price trades too far away from the fresh FVG before retracing, stand aside instead of forcing entry

## Invalidation Rules

- `Invalidation:` beyond the swing that caused the setup or beyond the origin side of the FVG, depending on the cleaner structure reference
- `Setup expiry:` if the retracement and trigger do not form inside the same planned session window, cancel the idea
- `Narrative failure:` if price accepts through the opposite side of the intended narrative and closes back through the MSS premise, invalidate the thesis
- `Late-session rule:` if the setup forms near the end of the allowed window and follow-through is weak, prefer no trade

## Trade Management Rules

- `Target model:` first target at the nearest opposing internal liquidity, final target at external liquidity or the main draw on liquidity
- `Partials model:` optional first partial at the first meaningful liquidity objective
- `Break-even rule:` move to break-even only after price has clearly delivered away from entry and taken at least the first internal objective

## Hard Filters

- `No-trade conditions:` no clear 4H dealing range, no clear liquidity decision, no clear bias, no clear narrative, no 15m MSS, no 5m displacement, no fresh 5m FVG, or setup appears outside the allowed session windows
- `News filter:` stand aside around major macro releases that typically shock BTC and ETH until you define a more precise event list and time buffer
- `Volatility filter:` skip if the move is already overextended before retracement or if execution candles become erratic and structure becomes unclear
- `Session cutoff:` no new setups outside London and New York windows by starter default
- `Pair filter:` ignore all non-BTCUSDT and non-ETHUSDT charts in the starter model, except approved BTCUSD and ETHUSD spot proxies used for analysis and paper-trade review
