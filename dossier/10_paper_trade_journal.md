# Paper Trade Journal

Use this file to log manual paper trades from the current canonical ICT starter model.

Legacy `version-1` entries may remain below for history, but new logs should follow the current DRT -> Bias -> Narrative -> Context -> Execution workflow.

## Summary Table

| ID | Date | Instrument | Session | Direction | Setup Tag | Decision | Result | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PT-001 | YYYY-MM-DD | BTCUSDT | London / New York | Long / Short | starter-valid / starter-invalid / unclear | paper trade / no trade | open / win / loss / invalid | brief note |
| PT-002 | 2026-04-09 | BTCUSD | outside preferred kill zone | Long bias | legacy-version-1 invalid | no trade | invalid | bullish context but late / chase risk |
| PT-003 | 2026-04-09 | BTCUSD | outside preferred kill zone | Long bias | legacy-version-1 invalid | no trade | invalid | cleaner structure, but still late and outside session |

## Entry Template

### PT-XXX

- `Date:`
- `Timezone used:`
- `Instrument:`
- `Chart source:`
- `Session:`
- `Weekend or weekday:`
- `4H dealing range:`
- `Premium / discount / equilibrium location:`
- `Internal / external liquidity map:`
- `Main liquidity event:` raid and reject / close-through acceptance / unclear
- `Active PD arrays in the range:`
- `PD array location:` premium / discount / equilibrium + internal / external
- `PD array behavior:` respected / disrespected / mixed
- `Bias:`
- `Narrative:` reversal / continuation / breakaway / measuring / terminus / unclear
- `Higher-timeframe context:`
- `Time-of-day context:`
- `15m MSS seen: yes/no`
- `5m displacement seen: yes/no`
- `Fresh 5m FVG seen: yes/no`
- `Execution array used:` FVG / IFVG / OB / BB / MB / RB / CE / OTE / none
- `CE / OTE confluence: yes/no`
- `Entry zone:`
- `Invalidation idea:`
- `Target 1:`
- `Target 2 / final target:`
- `Decision:` paper trade / no trade
- `Setup tag:` starter valid / starter invalid / unclear
- `Why:`
- `Screenshot paths:`

## Outcome Template

- `Outcome:` win / loss / invalid / missed / unclear
- `Was the setup valid under the rules?`
- `Did the trade follow the plan?`
- `Did the key PD array hold or fail?`
- `What worked?`
- `What failed?`
- `Rule to refine:`

## Legacy Logged Entries

The entries below were logged under the older `version-1` draft. Keep them for evidence, but do not use their field order as the canonical template going forward.

### PT-002

- `Date:` 2026-04-09
- `Timezone used:` chart captured in local display time; review normalized conceptually to UTC / New York session logic
- `Instrument:` BTCUSD (Bitstamp)
- `Chart source:` TradingView screenshots
- `Session:` outside preferred New York kill zone by starter default
- `Weekend or weekday:` weekday
- `4H bias:` mildly bullish recovery
- `15m context:` bullish continuation into upper local range
- `5m trigger:` recent bullish impulse already delivered
- `Main draw on liquidity:` recent highs around 72.8k-73.1k, then higher 15m liquidity
- `Liquidity sweep seen: yes/no` unclear from the provided screenshots
- `MSS seen: yes/no` likely occurred earlier, not fresh at the right edge
- `Displacement seen: yes/no` yes
- `Fresh FVG seen: yes/no` likely earlier, but no clean non-chased return was visible at review time
- `OTE confluence: yes/no` unclear
- `Entry zone:` not taken
- `Invalidation idea:` below recent impulse origin / local support
- `Target 1:` recent highs
- `Target 2 / final target:` higher 15m liquidity
- `Decision:` no trade
- `Setup tag:` version-1 invalid
- `Why:` setup looked late, outside preferred session timing, and likely violated the no-chasing rule
- `Screenshot paths:` /Users/silo/Desktop/Screenshot 2026-04-09 at 23.01.35.png ; /Users/silo/Desktop/Screenshot 2026-04-09 at 23.02.07.png ; /Users/silo/Desktop/Screenshot 2026-04-09 at 23.02.24.png

### PT-003

- `Date:` 2026-04-09
- `Timezone used:` chart captured in local display time; review normalized conceptually to UTC / New York session logic
- `Instrument:` BTCUSD (approved BTC spot proxy)
- `Chart source:` TradingView screenshots
- `Session:` outside preferred New York kill zone by starter default
- `Weekend or weekday:` weekday
- `4H bias:` bullish recovery / continuation
- `15m context:` bullish continuation with price holding near local highs
- `5m trigger:` earlier bullish displacement from the low 70.6k area into the 72k area
- `Main draw on liquidity:` local highs around 72.6k, then broader 4H highs above
- `Liquidity sweep seen: yes/no` yes, likely local sell-side raid before expansion
- `MSS seen: yes/no` yes, likely occurred during the 5m upside reversal
- `Displacement seen: yes/no` yes
- `Fresh FVG seen: yes/no` likely yes, earlier in the move
- `OTE confluence: yes/no` unclear
- `Entry zone:` not taken
- `Invalidation idea:` below the local low and impulse origin that produced the upside move
- `Target 1:` local highs around 72.6k
- `Target 2 / final target:` broader 4H buy-side liquidity above
- `Decision:` no trade
- `Setup tag:` version-1 invalid
- `Why:` setup structure was stronger than PT-002, but the chart was still reviewed late and outside the preferred session window, so the paper-trade decision remains no trade
- `Screenshot paths:` /Users/silo/Desktop/Screenshot 2026-04-09 at 23.48.28.png ; /Users/silo/Desktop/Screenshot 2026-04-09 at 23.48.40.png ; /Users/silo/Desktop/Screenshot 2026-04-09 at 23.55.12.png
