# Phase P9: Backend Decomposition

Purpose: reduce backend monolith risk without changing trading semantics, execution eligibility, OMS rules, or risk behavior.

## Scope

Phase P9 focuses on the verified structural issues around `paper_api/server.py`:

- extract the SQLite store implementation out of `server.py`
- extract Bybit HTTP/client logic out of `server.py`
- introduce a stable runtime-facing facade for daemon loops and replay tools
- remove direct `from server import ...` coupling from loops, replay tools, and stack control helpers where practical
- introduce a route-dispatch seam inside `TradingAPIHandler` for core exact-match GET/POST routes

## Non-goals

Phase P9 does not:

- retune strategy logic
- widen execution eligibility
- change `verified_paper_trade` semantics
- change OMS or risk-control behavior
- add live trading

## Deliverables

- `paper_api/trading_store.py` owns `PaperTradeStore`
- `paper_api/bybit_client.py` owns Bybit environment normalization and HTTP/private API helpers
- `paper_api/runtime_api.py` provides the loop/replay-facing runtime surface
- daemon loops and replay tools no longer import `server` directly
- `stackctl.py` probes import Bybit client helpers directly
- `TradingAPIHandler` has core route-dispatch methods for exact-match GET/POST endpoints
- Phase P9 contract tests prove the new boundaries

## Completion Criteria

Phase P9 is complete when:

- `server.py` materially shrinks versus the pre-P9 baseline
- extracted store/client modules are the canonical implementations used by `server.py`
- loops and replay tools depend on `runtime_api` / extracted modules instead of `server`
- stack/operator probes do not reach into `server` for Bybit client state
- core route dispatch exists as a real seam inside `TradingAPIHandler`
- backend tests pass without changing execution semantics

## Result

Phase P9 is complete once the repo reflects the decomposition above and the backend verification suite is green.
