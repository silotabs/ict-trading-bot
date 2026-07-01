# Analysis Workflow

Follow this sequence every time:

1. Identify the instrument, timeframe stack, and reference time.
2. Build the 4H DRT from clear external swings.
3. Map internal and external liquidity, including PDH/PDL and the configured Asian range.
4. Derive bias from DRT location plus liquidity interaction.
5. Explain the narrative inside the range.
6. Check context:
   - session validity
   - timing quality
   - 15m inside 4H continuation vs 15m onset of 4H reversal
7. Only then evaluate execution:
   - 15m MSS
   - 5m displacement
   - 5m PD array / FVG entry
8. State whether the outcome is:
   - `verified_paper_trade`
   - `scanner_candidate`
   - `journal_only`
   - `no_paper_trade`
   - `unclear`

If a chart URL or screenshot exists, use it as manual context only unless an explicit visual-analysis stage ran.

