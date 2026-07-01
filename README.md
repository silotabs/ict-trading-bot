# Trading Paper Stack

Conservative ICT paper-trading stack for local research, shadow-mode review, and operator-controlled trade validation.

The repo contains a Python backend, a React/Vite operator dashboard, ICT concept documentation, regression tests, and runbooks for moving from paper evidence toward a future go/no-go decision.

> Current posture: **paper / daemon review only**. This repository does not authorize live trading. The documented stage remains `Stage 6: Concept Proof / Acceptance Testing`, with `hold_for_more_shadow_evidence` as the live-readiness standing.

## What this project does

- Analyzes market structure from kline data, not chart screenshots.
- Uses 4H / 15m / 5m context for DRT, liquidity interaction, MSS, displacement, FVG, PD-array narrative, and opportunity classification.
- Records signal traces, blocker reasons, opportunity states, execution intents, risk checks, and shadow-review summaries.
- Keeps `verified_paper_trade` as the only execution-eligible decision class.
- Keeps auto-execution, trade management, and broker-facing behavior disabled by default.
- Provides a thin local dashboard for runtime health, signal traces, execution lifecycle review, and operator controls.

## Repository layout

```text
paper_api/         Python API, scanner loops, runtime services, store, ICT engine, policies
web/               React + Vite + Tailwind local operator dashboard
tests/             Python regression and contract tests
dossier/           Strategy specs, stage docs, runbooks, acceptance templates
skills/            Local ICT analyst skill documentation
.github/workflows/ GitHub CI configuration
docs/              GitHub push and operator setup notes
```

## Safety baseline

This project is intentionally conservative:

- `verified_paper_trade` is the only execution-eligible decision.
- Live trading is not approved by the current docs.
- Shadow-mode evidence is required before controlled-live planning can even be discussed.
- Secrets belong in `.env` or your shell environment only; never commit real exchange keys or operator tokens.
- `.env.example` is safe to commit; `.env` is ignored and should remain local.

## Backend quickstart

Requirements:

- Python 3.11+
- Optional Bybit API credentials for testnet/private-runtime experiments

```bash
cd trading
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e . pytest
cp .env.example .env
```

Edit `.env` before running anything that needs exchange credentials or an operator token.

Run the API only:

```bash
python paper_api/server.py
```

The API listens on:

```text
http://127.0.0.1:8787
```

Run the managed local stack:

```bash
python paper_api/stackctl.py start
```

Useful checks:

```bash
python -m pytest -q
curl http://127.0.0.1:8787/health
curl http://127.0.0.1:8787/ready
```

More backend detail lives in [`paper_api/README.md`](README.md).

## Frontend quickstart

Requirements:

- Node.js 20+
- pnpm

```bash
cd web
pnpm install
pnpm dev
```

The dashboard expects the backend at `http://127.0.0.1:8787` by default.

To use a different API base URL:

```bash
VITE_TRADING_API_BASE_URL=http://127.0.0.1:8787 pnpm dev
```

Frontend checks:

```bash
pnpm test
pnpm build
```

More UI detail lives in [`web/README.md`](README.md).

## Key docs

- [`dossier/19_live_readiness_checklist.md`](dossier/19_live_readiness_checklist.md)
- [`dossier/20_go_no_go_framework.md`](dossier/20_go_no_go_framework.md)
- [`dossier/21_shadow_metrics_requirements.md`](dossier/21_shadow_metrics_requirements.md)
- [`dossier/22_incident_and_rollback_runbook.md`](dossier/22_incident_and_rollback_runbook.md)
- [`dossier/23_one_day_acceptance_checklist.md`](dossier/23_one_day_acceptance_checklist.md)
- [`dossier/24_demo_trade_validation_template.md`](dossier/24_demo_trade_validation_template.md)
- [`dossier/29_phase_p12_packaging_stage6_closure.md`](dossier/29_phase_p12_packaging_stage6_closure.md)

## License

MIT License

Copyright (c) 2026 Silotabs contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

