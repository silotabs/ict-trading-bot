# Open Questions

## Definition Stability

- Which exact swing logic should define the dealing range in your method?
- Do you want BOS and MSS treated as separate concepts or one structure event with different strength?
- What exact threshold turns an impulsive move into `displacement`?
- Do you want wick-based or body-based FVG logic?
- When does a liquidity raid become `rejection` versus `acceptance through` liquidity?
- Which 15m structure break is the valid MSS after the 4H liquidity event?

## Zone Handling

- What is your house definition of an order block?
- What is your house definition of a breaker block, mitigation block, and rejection block?
- Do you treat `BISI` and `SIBI` as naming refinements on FVG, or do they get separate decision weight?
- When does an FVG become an IFVG in your read?
- When several PD arrays overlap, which one has priority?
- How much decision weight should location inside the dealing range carry for each PD array?
- What makes a PD array `respected` versus `disrespected`?
- Is a wick into the array enough, or do you require a candle close?
- When several candles form around the array, what counts as continued acceptance and what counts as failure?
- Is CE enough for entry, or only a refinement inside a larger setup?

## Time Logic

- Which session windows matter most for your trading: London, New York AM, New York PM, Asia?
- Which timezone should be the canonical one for analysis and alerts?
- Do you want Judas Swing logic only during certain sessions or markets?

## Instrument Scope

- Will this skill analyze forex only, or also indices, futures, and crypto?
- Do your ICT rules change by instrument?
- Do your preferred timeframes change by instrument?

## Narrative Logic

- How should the house rules distinguish `breakaway`, `measuring`, and `terminus` inside the dealing range?
- Which PD arrays matter most for continuation narrative versus reversal narrative?
- When do repeated FVG fills show healthy rebalancing, and when do they show narrative weakness?

## Execution Scope

- Do you want the first version to be analysis-only, paper-trading, or semi-auto execution?
- What invalidates a setup fast enough that the assistant should say `stand aside`?
- What risk limits must be hard-coded from day one?

## Research Gaps

- We still need a cleaner official source map for each concept.
- We still need timestamped official examples for the concepts you actually trade.
- We still need your personal rules, because ICT as a public framework is broader than any single trader's method.
- We still need example charts that show PD-array respect versus disrespect inside one active dealing range.
