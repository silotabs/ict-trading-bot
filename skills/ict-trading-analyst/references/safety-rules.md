# Safety Rules

Treat this skill as analysis plus manual paper-trade simulation.

## Never Do

- Do not place live trades.
- Do not auto-place paper trades on any platform.
- Do not claim broker-ready instructions exist when the house spec still has unresolved fields.
- Do not invent risk rules, stop placement rules, or position sizing rules.
- Do not present ambiguous community terminology as settled fact.

## Always Do

- State when a rule comes from the house spec versus broader ICT community usage.
- Lower confidence when the chart context is incomplete.
- Prefer `no clear setup` over overstating conviction.
- Flag unresolved `TODO` items that block reliable analysis.
- Keep paper-trade plans clearly labeled as simulated.

## Escalation Rule

If the user later wants paper trading, semi-auto execution, or live execution, require an explicit upgrade to the house spec first:

- market scope
- timeframe scope
- entry trigger
- stop logic
- target logic
- risk cap
- max daily loss
- execution venue
- allowed automation mode
