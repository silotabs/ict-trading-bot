# ICT Examples

Use this file to collect canonical chart examples from your method.

## Example Template

- `Instrument:`
- `Date / Time:`
- `Timezone:`
- `Timeframe stack:`
- `Session:`
- `Weekend or weekday:`
- `4H dealing range used:`
- `Premium / discount / equilibrium location:`
- `Internal / external liquidity map:`
- `Main liquidity event:` raid and reject / close-through acceptance / unclear
- `Active PD arrays in the range:`
- `PD array location:`
- `PD array behavior:` respected / disrespected / mixed
- `Bias:`
- `Narrative:` reversal / continuation / breakaway / measuring / terminus / unclear
- `Higher-timeframe context:`
- `Time-of-day context:`
- `15m MSS:`
- `5m displacement present: yes/no`
- `5m FVG or execution zone used:`
- `Entry model used:`
- `Invalidation:`
- `Target logic:`
- `Outcome:`
- `Notes:`
- `Source or screenshot path:`

## Guidance

- Add one example per setup.
- Prefer screenshots with timestamped TradingView context.
- Separate winning examples from valid-but-losing examples.
- Keep invalid examples too, because they are useful for filters.
- For now, prioritize BTCUSDT and ETHUSDT examples only.
- Tag each example as `starter-valid`, `starter-invalid`, or `unclear`.
- Legacy `version-1` examples may stay below, but new examples should follow the current canonical workflow.

## Legacy Logged Example 001

- `Instrument:` BTCUSD (BTC spot proxy)
- `Date / Time:` 2026-04-09 around 23:01 local chart capture
- `Timezone:` chart likely UTC+2 display; review logic normalized to UTC
- `Timeframe stack:` 4H / 15m / 5m
- `Session:` outside preferred New York kill zone by starter default
- `Weekend or weekday:` weekday
- `Context bias:` mildly bullish recovery context
- `Dealing range used:` visible 4H recovery range from roughly high-66k area into low-72k area
- `PDH / PDL position:` not explicitly marked on chart
- `Asian range reference:` not explicitly marked on chart
- `Liquidity target:` short-term draw toward 72.8k-73.1k, then potentially 75.7k
- `Structure event:` bullish intraday continuation, but not a fresh clean paper-trade trigger at the far right edge
- `Displacement present: yes/no` yes
- `Imbalance or zone used:` likely fresh bullish 5m FVG existed earlier in the move, but price was already extended by the time of review
- `Entry model used:` legacy Version 1 sweep -> MSS -> displacement -> FVG return
- `Invalidation:` below the recent impulse origin / recent local support near the low-71k area
- `Target logic:` first draw recent highs, then higher 15m liquidity
- `Outcome:` no paper trade
- `Notes:` useful as a late-entry / chase filter example; bullish context was present, but the setup looked too mature and likely outside the preferred session window
- `Source or screenshot path:` /Users/silo/Desktop/Screenshot 2026-04-09 at 23.01.35.png ; /Users/silo/Desktop/Screenshot 2026-04-09 at 23.02.07.png ; /Users/silo/Desktop/Screenshot 2026-04-09 at 23.02.24.png

## Legacy Logged Example 002

- `Instrument:` BTCUSD (approved BTC spot proxy)
- `Date / Time:` 2026-04-09 around 23:48 local chart capture
- `Timezone:` chart likely local display time; review normalized conceptually to UTC and New York session logic
- `Timeframe stack:` 4H / 15m / 5m
- `Session:` outside preferred New York kill zone by starter default
- `Weekend or weekday:` weekday
- `Context bias:` bullish recovery / continuation context on 4H
- `Dealing range used:` visible 4H range from the mid-66k area into the mid-75k area
- `PDH / PDL position:` not explicitly marked on chart
- `Asian range reference:` not explicitly marked on chart
- `Liquidity target:` short-term draw toward 72.6k, then 74.8k-75k
- `Structure event:` bullish intraday continuation after a local sell-side run into the 70.6k area
- `Displacement present: yes/no` yes
- `Imbalance or zone used:` likely bullish 5m FVG created during the sharp expansion from the 70.6k area into the 72k area
- `Entry model used:` legacy Version 1 sweep -> MSS -> displacement -> FVG return
- `Invalidation:` below the local 5m impulse origin / below the low that led to the upside displacement
- `Target logic:` first target recent local highs, secondary target the broader 4H buy-side range above
- `Outcome:` no paper trade
- `Notes:` stronger structure than the prior example, but still not a valid paper-trade entry at review time because it appeared late in the move and outside the preferred session window
- `Source or screenshot path:` /Users/silo/Desktop/Screenshot 2026-04-09 at 23.48.28.png ; /Users/silo/Desktop/Screenshot 2026-04-09 at 23.48.40.png ; /Users/silo/Desktop/Screenshot 2026-04-09 at 23.55.12.png
