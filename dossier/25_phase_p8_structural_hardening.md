# Phase P8: Structural Hardening

Purpose: close the verified durability and baseline-infrastructure issues from the trusted paper/daemon baseline without changing strategy semantics, execution eligibility, OMS behavior, or risk posture.

This phase is intentionally infrastructure-first. It hardens storage, runtime defaults, and shared helper seams before broader backend/frontend decomposition begins.

## Completed Scope

- moved the default SQLite path out of `/tmp` when a durable app-data directory is available
- added safe fallback back to `/tmp/trading-paper-trading.db` when the durable app-data directory cannot be created
- seeded the durable DB path from the legacy `/tmp` database when legacy runtime data exists and the new target is still empty
- enabled SQLite WAL mode for the main runtime store
- centralized the default runtime DB-path decision in one helper
- reduced duplicated runtime helpers by centralizing:
  - `clean_string`
  - `utc_now_iso`
  - `parse_iso_datetime`
  - `coerce_bool`
- rewired core runtime callers to use the shared helper module
- restored the conservative disabled-by-default policy baseline for:
  - `auto_execution_policy.json`
  - `trade_management_policy.json`
- refreshed stack manifest launch context on single-service restart so DB-path reporting stays truthful
- documented the new durable storage default

## Non-Goals

- no strategy retuning
- no execution-eligibility change
- no live-trading enablement
- no chart-image analysis
- no broad alignment rework

## Acceptance Criteria

- default runtime DB path resolves to a durable user-data location unless explicitly overridden or the runtime cannot create that directory
- `PaperTradeStore` opens SQLite with WAL enabled
- server and stack tooling share one DB-path decision helper
- core runtime helper duplication is materially reduced across the backend runtime path
- conservative policy defaults and trusted-baseline tests agree again
- stack manifest launch context stays aligned with restarted service DB-path configuration
- README reflects the new default storage posture
- regression tests cover:
  - durable default DB path selection
  - DB-path override behavior
  - legacy `/tmp` seeding into the durable target
  - WAL enabled on the runtime store
  - shared helper wiring
  - restart-service launch-context refresh

## Phase Outcome

Phase P8 is complete when:

- the repo defaults to durable storage instead of volatile `/tmp`
- SQLite WAL is active on the main runtime store
- the trusted conservative policy baseline is restored
- shared runtime helper duplication is reduced enough to support later extraction work
- stack/runtime DB-path reporting is operationally truthful after service restarts

## Deferred To Later Phases

These are real issues, but they are intentionally deferred out of P8:

- extract `PaperTradeStore` from `server.py`
- extract Bybit client calls from `server.py`
- replace large route `if/elif` chains with route tables
- reduce broad loop/tool import coupling into `server.py`
- split `web/src/App.tsx` into operator-facing component modules
- add optional HTTP auth and clearer package/module boundaries
