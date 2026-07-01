# Trading Web Dashboard

Thin React + Vite + Tailwind dashboard for the local paper trading stack.

It reads directly from the existing `paper_api` service instead of introducing a second backend.

## Run

From the trading repo:

```bash
cd /Users/silo/Downloads/trading/web
pnpm install
pnpm dev
```

The dashboard expects the paper trading API to already be running at:

`http://127.0.0.1:8787`

If you want to point the UI at a different local API base URL:

```bash
VITE_TRADING_API_BASE_URL=http://127.0.0.1:8787 pnpm dev
```

## Current surface

- stack health and exchange posture
- live daemon stream via `EventSource`
- BTC and ETH live ticker strip
- 5m candlestick terminal view for allowed instruments
- latest scan truth
- merged daemon event tape
- operator controls for pause / resume / kill switch / proposal actions
- operator runbook showing the current trading lifecycle phase
- richer chart posture badges and live context overlays
- proposal and execution evidence
- readiness view for the primary public candle-close stream and REST fallback path
- signal traces with opportunity state, blocker class, and executable status
- execution intents and risk-check lifecycle rows
- shadow-review summaries for opportunity states and blocker clusters
- concept-lab runtime posture
- current ruleset overview

## Notes

- this UI is local-operator oriented
- it is intentionally thin over the current Python API
- it now prefers the control-room API surfaces:
  - `/v1/control-room/snapshot`
  - `/v1/control-room/timeline`
  - `/v1/control-room/stream`
- runtime panels also poll `/ready`, `/v1/signal-traces`, `/v1/execution-intents`, `/v1/execution-risk-checks`, and `/v1/shadow-review/summary`
- operator labels are friendly by default; raw backend states remain available in hover titles/detail text
- executable signal wording is based on `verified_paper_trade` only
- run `pnpm test` for the frontend runtime-surface wiring checks
