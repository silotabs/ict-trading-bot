---
name: ict-trading-analyst
description: Analyze ICT/DRT setups in this repo using the local dossier, house spec, and paper API. Use for DRT -> Bias -> Narrative -> Context -> Execution analysis, conservative paper-trade review, and local scanner/API interpretation. Do not use for live trading.
---

# ICT Trading Analyst

## Overview

Use this skill for:

- DRT-first ICT analysis
- house-spec alignment
- paper-trade review
- scanner/API interpretation
- conservative concept refinement

Keep this skill in `analysis plus manual paper-trade simulation` mode.

Do not:

- place live orders
- present ambiguous ICT concepts as settled facts
- claim chart-image understanding when only screenshots or chart URLs were provided

Screenshots and chart URLs are `manual context only` unless a separate visual-analysis stage explicitly says otherwise.

## Read Order

1. [references/local-files.md](references/local-files.md)
2. [references/analysis-workflow.md](references/analysis-workflow.md)
3. [references/output-template.md](references/output-template.md)

If the task touches safety or refusals:

- [references/safety-rules.md](references/safety-rules.md)

If it touches paper-trade planning or journal review:

- [references/paper-trading-workflow.md](references/paper-trading-workflow.md)

If it touches the local paper API or daemon stack:

- [references/local-api.md](references/local-api.md)

## Core Grounding

Treat these as the primary project sources:

- `../../dossier/08_house_spec.md`
- `../../dossier/06_rules_and_filters.md`
- `../../dossier/12_execution_spec.md`
- `../../paper_api/README.md`

Use the broader dossier when needed, but do not drift away from the current house model:

- `../../dossier/00_overview.md`
- `../../dossier/01_core_concepts.md`
- `../../dossier/02_concept_hierarchy.md`
- `../../dossier/03_glossary.md`
- `../../dossier/04_official_vs_community.md`
- `../../dossier/07_open_questions.md`
- `../../dossier/09_paper_trading_protocol.md`
- `../../dossier/10_paper_trade_journal.md`
- `../../dossier/11_review_rubric.md`
- `../../dossier/rules/00_not_ready_for_execution.md`

## Fixed Reasoning Order

Always analyze in this order:

1. DRT
2. Bias
3. Narrative
4. Context
5. Execution

Execution must not stand in for the first four layers.

## Safety

- `verified_paper_trade` means scanner-verified, not live-executable
- `journal_only` means manually asserted and suitable for journaling, not machine-verified
- screenshots are supporting context, not proof of automated chart reading
- guarded testnet automation may exist in the repo, but it should be described precisely and treated as opt-in, not the default operating posture
