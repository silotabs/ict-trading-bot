# Local API

Use the local paper API when the task needs structured storage or machine-readable evaluation instead of markdown-only analysis.

## Core Files

- `../../../paper_api/server.py`
- `../../../paper_api/README.md`
- `../../../paper_api/stackctl.py`

## What The API Honestly Supports

- Bybit public-data scanning for BTCUSDT / ETHUSDT
- replay scans using historical candle windows
- TradingView webhook intake
- journal storage
- guarded testnet proposal planning
- optional guarded testnet automation loops that are policy-gated and now disabled by default

## What The API Does Not Honestly Support

- live trading
- verified chart-image reading in the core engine
- automatic certainty around unresolved ICT concepts

## Decision Semantics

The important decision outputs are:

- `journal_only`
- `scanner_candidate`
- `verified_paper_trade`
- `no_paper_trade`
- `unclear`

Manual assertion must not be treated as scanner verification.

## Screenshot / Chart Handling

- `visual_analysis_state = not_run` means no visual-analysis stage ran
- `visual_analysis_state = manual_context_only` means a chart URL or screenshot path was provided, but the engine did not read the image
- do not imply verified chart reading unless a separate visual-analysis stage exists and says so explicitly

## Safety Posture

- guarded testnet submission logic exists in the repo
- it is not live trading
- the policy files control whether those loops are enabled
- the default repo posture should stay conservative
