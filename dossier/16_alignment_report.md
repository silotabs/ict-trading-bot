# Alignment Report

## Where The Repo Used To Overstate Behavior

- The scanner and docs previously read too much like the lower-timeframe trigger chain was the whole thesis.
- README payload examples still implied the old `liquidity_sweep` checklist field.
- Screenshot / chart-url handling could be read as stronger than the actual engine capability.
- Some skill references still used local absolute paths or older `paper trade / no paper trade` wording.

## What Is Now Honest And Implemented

- The active 4H dealing range is anchored from preserved external swings.
- 4H liquidity interaction is explicit and feeds bias.
- Narrative and context are first-class engine outputs rather than doc-only concepts.
- Liquidity-map context now includes PDH / PDL and configured Asian range outputs.
- Execution detectors now expose:
  - state
  - confidence
  - evidence
  - assumptions
  - limitations
- 5m MSS is now clearly treated as a legacy compatibility alias rather than the primary structure premise.
- Manual assertions are separated from scanner verification.
- Screenshot / chart-image analysis is not represented as verified engine behavior.
- The tests now cover the core DRT / bias / narrative / context / verification alignment path.

## What Is Still Intentionally Unresolved

- Exact house-grade DRT swing logic can still evolve as the method is refined.
- The current liquidity-map policy uses a starter Asian range assumption.
- Narrative subtypes such as breakaway / measuring / terminus are not fully encoded yet.
- PD-array respect / disrespect is only partially translated into machine rules.
- The core engine does not perform verified screenshot / chart-image analysis.

## Current Screenshot / Chart Reading Status

- `manual_context_only`

That means:

- chart URLs and screenshot paths can be stored and surfaced for review
- the core engine does not inspect the image itself
- no verified visual-analysis stage runs in the current scanner path
