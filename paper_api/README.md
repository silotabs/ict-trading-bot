# Paper Trading API

Local API for structured ICT paper-trade testing, TradingView webhook intake, Bybit public market-data scanning, account-aware Bybit execution planning, and Bybit testnet order proposals.

This service does not place live trades. It evaluates Version 1 setup checklists, stores journal entries in SQLite, records webhook events, and generates Bybit testnet proposal payloads for manual review.

## Run

```bash
cd <repo-root>
python3 paper_api/server.py
```

The server listens on `http://127.0.0.1:8787`.

If you want the standard local stack instead of only the API server:

```bash
cd <repo-root>
python3 paper_api/stackctl.py start
```

By default the SQLite database is stored in the user application-data directory when that directory is available:

- macOS: `~/Library/Application Support/trading/paper-trading.db`
- Linux/XDG: `~/.local/share/trading/paper-trading.db`

If the runtime cannot create that directory, it falls back to:

- `/tmp/trading-paper-trading.db`

The managed stack state directory now follows the same durable-root policy when available:

- macOS: `~/Library/Application Support/trading/stack`
- Linux/XDG: `~/.local/share/trading/stack`

If that durable stack-state directory is unavailable, it falls back to:

- `/tmp/trading-paper-stack`

You can override the managed stack-state location with:

```bash
TRADING_STACK_STATE_DIR=/path/to/stack-state python3 paper_api/stackctl.py start
```

When a durable default path is available and an existing legacy `/tmp/trading-paper-trading.db`
already contains runtime data, the runtime seeds the durable DB from that legacy file automatically.

When a durable default stack-state directory is available and an existing legacy
`/tmp/trading-paper-stack` already contains manifest or log state, the runtime seeds the durable
stack-state directory from that legacy location automatically.

You can override that location with:

```bash
TRADING_API_DB_PATH=/path/to/paper_trading.db python3 paper_api/server.py
```

Optional environment variables:

```bash
TRADINGVIEW_WEBHOOK_SECRET=your-shared-secret \
BYBIT_MARKET_BASE_URL=https://api.bybit.com \
BYBIT_TESTNET_BASE_URL=https://api-testnet.bybit.com \
BYBIT_ENV=testnet \
BYBIT_ENABLE_TESTNET_SUBMIT=true \
BYBIT_API_KEY=your-bybit-testnet-key \
BYBIT_API_SECRET=your-bybit-testnet-secret \
python3 paper_api/server.py
```

The machine-readable execution spec used for Bybit sizing and validation lives at:

`paper_api/config/execution_spec.json`

The Wave 1 auto-execution policy lives at:

`paper_api/config/auto_execution_policy.json`

The Wave 2 trade-management policy lives at:

`paper_api/config/trade_management_policy.json`

The execution risk-control policy lives at:

`paper_api/config/risk_control_policy.json`

The Concept 1 decision policy lives at:

`paper_api/config/concept_decision_policy.json`

The local stack launcher lives at:

`paper_api/stackctl.py`

Operator smoke-test docs for the current paper / daemon baseline live at:

- `dossier/17_paper_daemon_trust_gate.md`
- `dossier/18_smoke_test_runbook.md`
- `dossier/23_one_day_acceptance_checklist.md`
- `dossier/24_demo_trade_validation_template.md`
- `dossier/25_phase_p8_structural_hardening.md`
- `dossier/26_phase_p9_backend_decomposition.md`
- `dossier/27_phase_p10_frontend_decomposition.md`
- `dossier/28_phase_p11_security_interface_boundaries.md`
- `dossier/29_phase_p12_packaging_stage6_closure.md`

Python project metadata now lives at:

- `pyproject.toml`

The current packaging change is repo-hygiene only. It does not change runtime semantics, and it does not change the current stage truth:

- current stage: `Stage 6: Concept Proof / Acceptance Testing`
- next stage: `Stage 7: Promotion or Rejection Decision`
- current standing: `hold_for_more_shadow_evidence`
- candidate for controlled live planning: `no`

Live-readiness planning docs for the current paper / daemon baseline live at:

- `dossier/19_live_readiness_checklist.md`
- `dossier/20_go_no_go_framework.md`
- `dossier/21_shadow_metrics_requirements.md`
- `dossier/22_incident_and_rollback_runbook.md`

## Endpoints

- `GET /health`
- `GET /ready`
- `GET /v1/shadow-review/summary`
- `GET /v1/rules`
- `GET /v1/execution/spec`
- `GET /v1/control/state`
- `GET /v1/control/state/<control-key>`
- `GET /v1/control/events`
- `GET /v1/control/events/<event-id>`
- `GET /v1/auto-execution/policy`
- `GET /v1/auto-execution/runtime`
- `GET /v1/auto-execution/runtime/<runtime-key>`
- `GET /v1/auto-execution/events`
- `GET /v1/auto-execution/events/<event-id>`
- `GET /v1/trade-management/policy`
- `GET /v1/trade-management/runtime`
- `GET /v1/trade-management/runtime/<runtime-key>`
- `GET /v1/trade-management/events`
- `GET /v1/trade-management/events/<event-id>`
- `GET /v1/operations/status`
- `GET /v1/operations/runtime`
- `GET /v1/operations/runtime/<runtime-key>`
- `GET /v1/operations/events`
- `GET /v1/operations/events/<event-id>`
- `GET /v1/supervisor/active`
- `GET /v1/supervisor/runtime`
- `GET /v1/supervisor/runtime/<runtime-key>`
- `GET /v1/supervisor/events`
- `GET /v1/supervisor/events/<event-id>`
- `GET /v1/private-stream/runtime`
- `GET /v1/private-stream/runtime/<runtime-key>`
- `GET /v1/private-stream/events`
- `GET /v1/private-stream/events/<event-id>`
- `GET /v1/execution-actions`
- `GET /v1/execution-actions/<action-id>`
- `GET /v1/execution-intents`
- `GET /v1/execution-intents/<intent-id>`
- `GET /v1/execution-intent-events`
- `GET /v1/execution-intent-events/<event-id>`
- `GET /v1/execution-risk-checks`
- `GET /v1/execution-risk-checks/<risk-check-id>`
- `GET /v1/execution-state`
- `GET /v1/execution-state/<proposal-id>`
- `GET /v1/market/bybit/klines`
- `GET /v1/market/bybit/instrument`
- `GET /v1/market/bybit/ticker`
- `GET /v1/paper-trades`
- `GET /v1/paper-trades/<journal-id>`
- `GET /v1/scan-history`
- `GET /v1/scan-history/<scan-id>`
- `GET /v1/signal-traces`
- `GET /v1/signal-traces/<trace-id>`
- `GET /v1/watchlist-state`
- `GET /v1/webhooks`
- `GET /v1/webhooks/<webhook-id>`
- `GET /v1/concept/acceptance/history`
- `GET /v1/order-proposals`
- `GET /v1/order-proposals/<proposal-id>`
- `GET /v1/stats`
- `POST /v1/control/state`
- `POST /v1/control/kill-switch`
- `POST /v1/execution/plan`
- `POST /v1/supervisor/scan`
- `POST /v1/paper-trades/evaluate`
- `POST /v1/scans/bybit/ict-v1`
- `POST /v1/scans/bybit/watchlist`
- `POST /v1/scans/bybit/watchlist/shadow`
- `POST /v1/scans/bybit/replay`
- `POST /v1/webhooks/tradingview`
- `POST /v1/concept/reviews/structured`
- `POST /v1/concept/revisions/compare-structured`
- `POST /v1/order-proposals/<proposal-id>/amend`
- `POST /v1/order-proposals/<proposal-id>/cancel`
- `POST /v1/order-proposals/<proposal-id>/refresh-trading-stop`
- `POST /v1/order-proposals/<proposal-id>/close-position`
- `POST /v1/order-proposals/<proposal-id>/sync`
- `POST /v1/order-proposals/<proposal-id>/submit`
- `POST /v1/paper-trades/<journal-id>/outcome`

## Runtime Notes

The trusted paper/daemon baseline now keeps a thinner runtime boundary:

- `server.py` remains the orchestration surface
- policy loading is handled through dedicated runtime-config helpers
- trace / intent / risk persistence can be reached through repository wrappers backed by the current SQLite store
- health and readiness assembly are exposed separately, with:
  - `GET /health` for liveness/config summary
  - `GET /ready` for operator-facing readiness based on critical subsystem state

## Stack Control

Start the standard local stack:

```bash
cd <repo-root>
python3 paper_api/stackctl.py start
```

### Scan Loop Runtime

The watchlist scanner now treats confirmed public candle-close events as the primary trigger path.

- `5m`, `15m`, and `4h` public kline close events for `BTCUSDT` and `ETHUSDT` are watched by the scan loop.
- Only confirmed closed bars trigger scans.
- Each event is normalized to a deterministic `reference_at` / `reference_ms` using:
  - `reference_ms = candle_start_ms + interval_ms`
- Coincident close events that resolve to the same reference timestamp only trigger one scan per symbol.
- Repeated receipt of the same closed candle does not trigger a duplicate scan.

REST polling remains in place for bootstrap and backfill only:

- fallback checks the latest closed `5m` bar when the event stream is unavailable or a bar may have been missed
- if the event-driven path already handled that reference timestamp, fallback polling skips it instead of creating a duplicate scan / signal trace

Current posture remains unchanged:

- event-driven scanning does not widen execution eligibility
- evaluation still flows through the same verified-only paper-trade gate
- screenshots and chart URLs remain `manual_context_only` or `not_run`; no chart-image analysis is performed in the core engine

### Opportunity Layer

The scanner now records an additive opportunity read alongside the trusted execution decision.

- `verified_paper_trade` remains the only execution-eligible decision
- opportunity states are additive only:
  - `opportunity_detected`
  - `near_miss`
  - `awaiting_confirmation`
  - `context_watch`
  - `invalid`
- opportunity state is derived from the same DRT, bias, narrative, context, MSS, displacement, FVG, and chase evidence already used by the scanner
- non-executable opportunity states do not widen paper or live execution scope
- signal traces persist the opportunity read so operators can see whether a setup was executable, nearly executable, still confirming, or only watch-worthy

### Shadow Review

The scanner now supports an additive shadow-review path for operator learning and false-negative review.

- `POST /v1/scans/bybit/watchlist/shadow` runs a watchlist scan in shadow mode
- shadow traces are tagged with:
  - `shadow_mode=true`
  - `shadow_session_id`
- `GET /v1/signal-traces` can now filter by:
  - `shadow_mode`
  - `shadow_session_id`
  - `opportunity_state`
  - `session_state`
  - `blocker_reason_contains`
- `GET /v1/shadow-review/summary` groups shadow traces by:
  - decision
  - opportunity state
  - blocker class
  - blocker reason clusters
  - symbol
  - session window
- shadow mode is observational only and does not widen execution scope or change verified-only execution eligibility

### Live-Readiness Planning

The current repo now includes a planning-only live-readiness package for future controlled deployment review.

Optional operator route protection is available through `TRADING_API_OPERATOR_TOKEN`. When set, sensitive POST control / execution routes require either `X-Trading-Operator-Token` or `Authorization: Bearer ...`.

- the compressed one-day operator acceptance checklist lives in `dossier/23_one_day_acceptance_checklist.md`
- the per-trade demo / testnet review template lives in `dossier/24_demo_trade_validation_template.md`
- the checklist lives in `dossier/19_live_readiness_checklist.md`
- the decision framework lives in `dossier/20_go_no_go_framework.md`
- the shadow evidence thresholds live in `dossier/21_shadow_metrics_requirements.md`
- the incident and rollback runbook lives in `dossier/22_incident_and_rollback_runbook.md`

Important:

- this does not add live trading
- this does not add broker-facing behavior
- this does not widen execution eligibility
- the default standing after P7 should remain `hold_for_more_shadow_evidence` until the documented gates are satisfied

### Execution Intents

The daemon now keeps a separate execution-intent / OMS spine above order submission.

- only `verified_paper_trade` may create an execution intent
- execution intent is additive and does not change signal-generation semantics
- repeated handling of the same eligible signal reuses the same intent key instead of creating duplicate active intents
- lifecycle states are explicit and queryable:
  - `signal_detected`
  - `execution_plan_created`
  - `order_submission_pending`
  - `order_submitted`
  - `order_acknowledged`
  - `partially_filled`
  - `fully_filled`
  - `cancelled`
  - `rejected`
  - `flattened`
  - `reconciled`
- intent transitions are recorded separately from order proposals and execution-state snapshots
- this remains paper / testnet safe; no live broker expansion is introduced by the intent layer

### Risk Controls

The daemon now evaluates a separate risk-control layer before advancing an execution intent into plan creation or submission.

- risk checks are additive and do not change signal generation or opportunity classification
- a risk block does not create a trade; it only prevents OMS advancement
- blocked attempts are persisted and queryable through:
  - `GET /v1/execution-risk-checks`
  - `GET /v1/execution-risk-checks/<risk-check-id>`
- current risk checks include:
  - maximum single-order size (`maximum_order_size.max_notional` and optional `max_qty`)
  - maximum daily order/proposal count (`daily_order_count.max_count`)
  - maximum intraday position exposure per symbol (`symbol_exposure.max_intraday_position_exposure`)
  - max daily realized loss
  - max active intent count per symbol
  - max open exposure notional
  - consecutive-loss cooldown
  - stale market-data lockout
  - stale execution-state lockout
  - manual kill switch / operator emergency stop / control-state blocks
  - automatic kill switch when configured risk checks trip
  - cancel-on-disconnect guard for private-stream disconnects
  - duplicate active-intent suppression
- `paper_api/config/risk_control_policy.json` includes descriptions beside the configurable limits; changing limits narrows or blocks advancement only and must not be used to widen strategy eligibility
- `verified_paper_trade` remains the only execution-eligible signal state
- non-eligible decisions never become executable through the risk layer

### Stackctl Verified-Only Metrics

`stackctl` operator summaries treat `verified_paper_trade` as the only default candidate metric. Legacy compatibility-only `paper_trade` rows are not included in candidate ratios, sample candidate totals, proposal-conversion checks, or text summary scan mixes.

If you need to inspect old compatibility rows during a migration/debug pass, opt in explicitly:

```bash
python3 paper_api/stackctl.py concept-review --include-legacy-compat-metrics
python3 paper_api/stackctl.py concept-decision --include-legacy-compat-metrics
python3 paper_api/stackctl.py wave4-review --include-legacy-compat-metrics
```

That flag keeps legacy counts separate; it does not make `paper_trade` execution-eligible.

Check process status:

```bash
cd <repo-root>
python3 paper_api/stackctl.py status
```

The status output now also reports `drift`, which means a managed service process is still alive but no longer matches the PID saved in the stack manifest. The stack controller now locks and atomically writes the manifest during `start`, `stop`, and `restart-service` so concurrent service actions do not clobber each other.

Run a local readiness gate before guarded testnet automation:

```bash
cd <repo-root>
python3 paper_api/stackctl.py preflight --with-private-stream --with-auto-execution --with-trade-management
```

Require a real Bybit private auth probe during that readiness check:

```bash
cd <repo-root>
python3 paper_api/stackctl.py preflight --with-private-stream --with-auto-execution --with-trade-management --probe-bybit-auth
```

Arm the guarded testnet stack in one command:

```bash
cd <repo-root>
python3 paper_api/stackctl.py arm-testnet
```

Arm only if a real Bybit private auth probe also passes:

```bash
cd <repo-root>
python3 paper_api/stackctl.py arm-testnet --probe-bybit-auth
```

Show a single burn-in summary from the stack manifest plus SQLite state:

```bash
cd <repo-root>
python3 paper_api/stackctl.py burnin-report
```

Evaluate recent burn-in health and summarize blockers:

```bash
cd <repo-root>
python3 paper_api/stackctl.py burnin-gate
```

Combine burn-in state with replay tuning for one Wave 4 verdict on the current single-concept model:

```bash
cd <repo-root>
python3 paper_api/stackctl.py wave4-review --max-steps 100 --step-stride 3
```

If you want that review to judge only tradable replay windows:

```bash
cd <repo-root>
python3 paper_api/stackctl.py wave4-review --max-steps 100 --step-stride 3 --tradable-only
```

Summarize whether the current single-concept model is actually ready to graduate beyond Wave 4:

```bash
cd <repo-root>
python3 paper_api/stackctl.py promotion-review --max-steps 100 --step-stride 3
```

If you want the promotion review to judge only tradable replay windows:

```bash
cd <repo-root>
python3 paper_api/stackctl.py promotion-review --max-steps 100 --step-stride 3 --tradable-only
```

Inspect Bybit private auth and configuration before you arm the stack:

```bash
cd <repo-root>
python3 paper_api/stackctl.py bybit-doctor
```

Turn the current concept review into a simple evidence-based decision:

```bash
cd <repo-root>
python3 paper_api/stackctl.py concept-decision --max-steps 12 --step-stride 3 --tradable-only
```

If you want the decision gate to inspect a wider recent scan window while keeping proposal/action windows smaller:

```bash
cd <repo-root>
python3 paper_api/stackctl.py concept-decision --max-steps 12 --step-stride 3 --tradable-only --scan-limit 50
```

Build an LLM-ready concept review packet grounded in the local house spec, review rubric, and source map:

```bash
cd <repo-root>
python3 paper_api/stackctl.py concept-brief --max-steps 12 --step-stride 3 --tradable-only
```

Build an LLM-ready revision-comparison packet for the saved review/revision loop:

```bash
cd <repo-root>
python3 paper_api/stackctl.py concept-revision-brief --max-steps 12 --step-stride 3 --tradable-only
```

Build a Stage 6 acceptance-testing packet that combines live concept evidence with saved revision-loop history:

```bash
cd <repo-root>
python3 paper_api/stackctl.py concept-acceptance-brief --max-steps 12 --step-stride 3 --tradable-only
```

The live concept lab now also tracks Stage 6 evidence progress directly in runtime and the control-room snapshot. It emits `acceptance_progress_updated` when proposal/action/execution evidence moves and `acceptance_stalled` when Stage 6 keeps cycling without meaningful evidence progress.

Build a Stage 7 decision-memo packet that stays blocked until Stage 6 evidence is actually ready:

```bash
cd <repo-root>
python3 paper_api/stackctl.py concept-stage7-decision-brief --max-steps 12 --step-stride 3 --tradable-only
```

If you want the same packet from the daemon API:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/concept/brief?tradable_only=true&max_steps=12&step_stride=3"
```

And the revision-comparison version from the daemon API:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/concept/revisions/brief?tradable_only=true&max_steps=12&step_stride=3&artifact_limit=20&top_limit=3"
```

And the Stage 6 acceptance-testing version from the daemon API:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/concept/acceptance/brief?tradable_only=true&max_steps=12&step_stride=3&artifact_limit=20&top_limit=3"
```

And the live Stage 6 milestone history that shows whether evidence is progressing or stalling:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/concept/acceptance/history?limit=10"
```

And the Stage 7 decision-memo version from the daemon API:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/concept/stage7/decision-brief?tradable_only=true&max_steps=12&step_stride=3&artifact_limit=20&top_limit=3"
```

And the compact Stage 7 summary used by the live terminal surfaces:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/concept/stage7/summary?tradable_only=true&max_steps=12&step_stride=3&artifact_limit=20&top_limit=3"
```

And the canonical roadmap-backed live stage status:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/concept/stage-status?tradable_only=true&max_steps=12&step_stride=3&artifact_limit=20&top_limit=3"
```

Persist a structured Stage 6 acceptance judgment from an external LLM response file:

```bash
cd <repo-root>
python3 paper_api/stackctl.py concept-save-acceptance-review \
  --response-file /tmp/trading-acceptance-review.json \
  --source llm \
  --author gpt-5.4 \
  --max-steps 12 \
  --step-stride 3 \
  --tradable-only
```

Or save the same acceptance judgment through the daemon API:

```bash
/usr/bin/curl -s -X POST "http://127.0.0.1:8787/v1/concept/acceptance/reviews/structured" \
  -H "Content-Type: application/json" \
  -d @/tmp/trading-acceptance-review-payload.json
```

Persist a structured Stage 7 decision memo from an external LLM response file:

```bash
cd <repo-root>
python3 paper_api/stackctl.py concept-save-stage7-decision \
  --response-file /tmp/trading-stage7-decision.json \
  --source llm \
  --author gpt-5.4 \
  --max-steps 12 \
  --step-stride 3 \
  --tradable-only
```

Or save the same Stage 7 memo through the daemon API:

```bash
/usr/bin/curl -s -X POST "http://127.0.0.1:8787/v1/concept/stage7/decisions/structured" \
  -H "Content-Type: application/json" \
  -d @/tmp/trading-stage7-decision-payload.json
```

Store an external LLM or manual concept review artifact, attached to the current brief:

```bash
/usr/bin/curl -s -X POST "http://127.0.0.1:8787/v1/concept/reviews" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "llm",
    "author": "gpt-5.4",
    "review_kind": "analysis",
    "summary": "Collect more evidence before changing rules; review ETH bias imbalance next.",
    "include_current_brief": true,
    "tradable_only": true,
    "max_steps": 12,
    "step_stride": 3
  }'
```

List saved concept review artifacts:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/concept/reviews?limit=20"
```

Generate a conservative one-variable revision plan from the current brief:

```bash
cd <repo-root>
python3 paper_api/stackctl.py concept-revision-plan --max-steps 12 --step-stride 3 --tradable-only
```

Persist the current top revision plan in the daemon:

```bash
/usr/bin/curl -s -X POST "http://127.0.0.1:8787/v1/concept/revisions" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "llm",
    "author": "gpt-5.4",
    "include_current_brief": true,
    "tradable_only": true,
    "max_steps": 12,
    "step_stride": 3
  }'
```

Evaluate a saved revision plan against the latest brief:

```bash
/usr/bin/curl -s -X POST "http://127.0.0.1:8787/v1/concept/revisions/RV-00001/evaluate" \
  -H "Content-Type: application/json" \
  -d '{
    "tradable_only": true,
    "max_steps": 12,
    "step_stride": 3
  }'
```

Save a structured LLM review from a local JSON file into the local concept review history:

```bash
cd <repo-root>
python3 paper_api/stackctl.py concept-save-review \
  --response-file /absolute/path/to/review-response.json \
  --source llm \
  --author gpt-5.4 \
  --max-steps 12 \
  --step-stride 3 \
  --tradable-only
```

Save a structured LLM revision-compare response from a local JSON file into the same review history:

```bash
cd <repo-root>
python3 paper_api/stackctl.py concept-save-revision-compare \
  --response-file /absolute/path/to/revision-compare-response.json \
  --source llm \
  --author gpt-5.4 \
  --max-steps 12 \
  --step-stride 3 \
  --tradable-only
```

Promote a saved structured review directly into a persisted revision plan:

```bash
cd <repo-root>
python3 paper_api/stackctl.py concept-promote-review \
  --review-id CR-00002 \
  --max-steps 12 \
  --step-stride 3 \
  --tradable-only
```

Evaluate the latest saved revision linked to that review, with a fresh-sample guard:

```bash
cd <repo-root>
python3 paper_api/stackctl.py concept-evaluate-review \
  --review-id CR-00002 \
  --max-steps 12 \
  --step-stride 3 \
  --tradable-only
```

If you re-run the same evaluation inside the same replay sample window, the latest history entry is replaced instead of duplicated. When the sample window advances, a new evaluation-history entry is appended automatically.

Or send the same structured response directly to the daemon:

```bash
/usr/bin/curl -s -X POST "http://127.0.0.1:8787/v1/concept/reviews/structured" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "llm",
    "author": "gpt-5.4",
    "include_current_brief": true,
    "tradable_only": true,
    "max_steps": 12,
    "step_stride": 3,
    "response": {
      "verdict": "support_current_recommendation",
      "primary_blocker": "displacement",
      "evidence_gap": "recent proposal and execution-state counts are still below threshold",
      "next_action_type": "collect_evidence",
      "next_action_focus": "evidence_thresholds",
      "next_action_summary": "Keep collecting evidence until the next clean proposal and execution-state row arrive.",
      "what_would_change_my_mind": "If evidence thresholds are met and candidate ratio stays at zero, I would shift to a one-variable displacement review.",
      "confidence": "medium",
      "grounding_refs_used": ["House Spec", "Review Rubric"],
      "one_variable_revision": {
        "needed": false,
        "focus": "",
        "hypothesis": "",
        "success_metric": "",
        "abort_metric": ""
      }
    }
  }'
```

And you can store a structured revision-compare response directly against the current revision brief:

```bash
/usr/bin/curl -s -X POST "http://127.0.0.1:8787/v1/concept/revisions/compare-structured" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "llm",
    "author": "gpt-5.4",
    "include_current_brief": true,
    "tradable_only": true,
    "max_steps": 12,
    "step_stride": 3,
    "artifact_limit": 20,
    "top_limit": 3,
    "response": {
      "verdict": "hold_revision_loop",
      "leader_revision_id": "RV-00002",
      "challenger_revision_id": "",
      "comparison_summary": "The current leader is still only the least-bad revision because all linked revisions remain regressed.",
      "primary_risk": "The loop is still too flat and regressed to justify promoting a rules change.",
      "next_action_type": "review_regressed_revision",
      "next_action_focus": "displacement",
      "next_action_summary": "Review the regressed displacement-focused revision before queuing any new rule edit.",
      "what_would_change_my_mind": "A fresh-sample evaluation that stabilizes to flat or improved while preserving guardrails would justify keeping the current leader.",
      "confidence": "medium",
      "grounding_refs_used": ["House Spec", "Review Rubric", "Initial Source Map"]
    }
  }'
```

Once a structured review is saved, you can promote that saved review into a revision artifact from the daemon too:

```bash
/usr/bin/curl -s -X POST "http://127.0.0.1:8787/v1/concept/reviews/CR-00002/promote-revision" \
  -H "Content-Type: application/json" \
  -d '{
    "tradable_only": true,
    "max_steps": 12,
    "step_stride": 3
  }'
```

And you can ask the daemon to evaluate the latest revision linked to that same review:

```bash
/usr/bin/curl -s -X POST "http://127.0.0.1:8787/v1/concept/reviews/CR-00002/evaluate-latest-revision" \
  -H "Content-Type: application/json" \
  -d '{
    "tradable_only": true,
    "max_steps": 12,
    "step_stride": 3
  }'
```

That daemon route follows the same history rule: one entry per fresh sample window, replace on same-window re-checks.

When `concept_lab_loop.py` is running, it now also auto-links any saved structured review that does not yet have a linked revision. On the next concept-lab cycle, the daemon will create that missing revision automatically, evaluate it against the current sample when appropriate, and surface the result through `revision_activity` in `concept_runtime`.

That same concept-lab cycle now also tracks the live revision-compare leader. When the preferred leader or compare verdict changes, the daemon emits:

- `revision_compare_updated`
- `revision_leader_changed`
- `revision_compare_verdict_changed`

and refreshes the compact compare snapshot in `concept_runtime.last_summary.revision_compare`. The compare snapshot also tracks `stability_cycles` and `last_changed_at` so Stage 5 readiness can be judged from live daemon state instead of guesswork.

You can also ask the daemon for a compact comparison summary across the saved revision history:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/concept/revisions/summary?concept_id=concept-1&limit=20"
```

That summary rolls up status counts, focus counts, evaluation-history depth, the current best revision candidate, and a conservative next-action takeaway for the operator. If a saved `revision_compare_structured` artifact exists, the summary also includes the latest compare guidance, a plain-language leader explanation, the compare artifact's next-action summary, and a `stage5_readiness` gate derived from live daemon state.

The generic revision endpoint now also honors a linked `review_id` by default, so this works too:

```bash
/usr/bin/curl -s -X POST "http://127.0.0.1:8787/v1/concept/revisions" \
  -H "Content-Type: application/json" \
  -d '{
    "review_id": "CR-00002",
    "tradable_only": true,
    "max_steps": 12,
    "step_stride": 3
  }'
```

If your key belongs to Bybit Demo Trading instead of testnet, export `BYBIT_ENV=demo` before running `bybit-doctor`, `preflight`, or `arm-testnet`. The stack now supports `BYBIT_ENV=testnet`, `BYBIT_ENV=demo`, and `BYBIT_ENV=mainnet` for the private REST and websocket side. Public market-data scanning still defaults to `https://api.bybit.com` unless you override `BYBIT_MARKET_BASE_URL`.

Show safe fingerprints and sources for the loaded Bybit env values:

```bash
cd <repo-root>
python3 paper_api/stackctl.py env-debug
```

Stop the stack cleanly:

```bash
cd <repo-root>
python3 paper_api/stackctl.py stop
```

Restart the stack:

```bash
cd <repo-root>
python3 paper_api/stackctl.py restart
```

Default services:

- `server.py`
- `scan_loop.py`
- `supervisor_loop.py`
- `ops_loop.py`

If Bybit private-stream credentials are already exported and you want websocket reconciliation too:

```bash
cd <repo-root>
python3 paper_api/stackctl.py start --with-private-stream
```

If you also want the Wave 1 auto-execution daemon running:

```bash
cd <repo-root>
python3 paper_api/stackctl.py start --with-private-stream --with-auto-execution
```

The auto-execution daemon still obeys the control plane and the policy file. Check the current `"enabled"` flag in `paper_api/config/auto_execution_policy.json` before you run it with submission credentials.

If you also want the Wave 2 trade-management daemon running:

```bash
cd <repo-root>
python3 paper_api/stackctl.py start --with-private-stream --with-auto-execution --with-trade-management
```

The trade-management daemon is also policy-gated. Check the current `"enabled"` flag in `paper_api/config/trade_management_policy.json` before you run it live on testnet.

Logs and pid state are stored under `/tmp/trading-paper-stack` by default. Override that with `--state-dir` when needed.

`stackctl.py` now also loads `.env` by default when that file exists. Exported shell variables win by default and the env file only fills missing values. Use `--env-file /path/to/file.env` for a different file, `--env-file-override` if you explicitly want the env file to overwrite the current shell variables, or `--no-env-file` if you want to ignore env files completely for a run.

The `preflight` command checks:

- execution spec and policy files parse cleanly
- current control-plane pauses in the configured SQLite DB
- whether private-stream, auto-execution, and trade-management daemons are planned or already running
- whether Bybit credentials and private-submission enablement are present when the enabled policies require them
- and, when `--probe-bybit-auth` is set, whether the Bybit testnet wallet endpoint accepts the current credentials for the execution-spec account type and balance coin

The `arm-testnet` command runs that same preflight and only starts the full guarded testnet daemon set if the result is `ready`. If you also want a background concept judge running alongside the stack, add `--with-concept-lab`; that daemon keeps running `concept-decision` on the current Concept 1 evidence and writes its own runtime and events into the same SQLite DB.

The `burnin-report` command gives a compact operator snapshot from the daemon manifest plus the local SQLite DB. It includes current controls, runtime freshness, recent events, recent proposals, recent execution actions, recent execution state, recent scan history, concept-lab runtime status when enabled, and a safe Bybit launch-env comparison for each daemon so you can review whether the stack is healthy before or during testnet burn-in.

The `burnin-gate` command reads that same local state and turns it into a plain readiness verdict. It marks the stack `ready`, `watch`, `idle`, or `blocked` based on paused controls, recent warning/error events, recent scan activity, private-stream health, daemon launch-env drift, and the latest operations and automation runtimes. If the current shell Bybit values differ from the ones a running private-stream daemon was started with, it will surface `private_stream_restart_required` instead of leaving you to infer that from generic auth failures.

The `wave4-review` command builds on that burn-in verdict and runs the replay tuning pass in the same command. It gives you one plain-text or JSON answer for the current single-concept model: `blocked`, `watch`, `idle`, or `ready`, along with the replay blocker mix and the next Wave 4 focus items.

The `concept-review` command is meant for the phase after infrastructure and auth are working. It separates “is Concept 1 still worth testing?” from “is the stack promotable right this second?” and summarizes live scan evidence, proposal evidence, execution-state evidence, current replay pressure, and recent auto-execution conversion blockers when paper-trade scans are not turning into proposals. It can return states like `collecting`, `testing`, or `promising` so you can evaluate the concept without overloading that decision onto the stricter promotion gate.

The `promotion-review` command builds on `wave4-review` and checks whether the local SQLite state has enough recent scan, proposal, execution-action, and execution-state evidence to justify promoting the current concept beyond Wave 4. It separates “the code path exists” from “we have enough burn-in evidence to trust it.”

The `concept-decision` command is the explicit keep/revise/compare gate for Concept 1. It now also surfaces an operator signal when concept detection is ahead of proposal creation, so you can see whether the next bottleneck is still the ruleset itself or a specific auto-execution gate. The optional `concept_lab_loop.py` daemon simply runs that same decision logic in the background on a cadence, persists its runtime in `concept_runtime`, and emits `concept_events` like `decision_changed`, `evidence_threshold_met`, `revise_candidate`, or `compare_candidate`.

To run that background concept judge alongside the demo stack:

```bash
cd <repo-root>
export BYBIT_ENV=demo
python3 paper_api/stackctl.py arm-testnet --probe-bybit-auth --no-env-file --with-concept-lab
```

If you change concept-lab code and want to reload only that daemon without replaying old log lines, use:

```bash
cd <repo-root>
export BYBIT_ENV=demo
python3 paper_api/stackctl.py restart-service concept_lab_loop --no-env-file --fresh-log
tail -n 0 -f /tmp/trading-paper-stack/logs/concept_lab_loop.log
```

The `bybit-doctor` command focuses on the exchange side. It checks whether the current shell has the expected Bybit credentials, environment, and submission flag, shows the resolved private REST/websocket URLs, probes the lighter `query-api` private endpoint first, and then probes the private wallet-balance endpoint using the account type and balance coin from the execution spec. It also translates common auth failures into likely causes such as environment mismatch, signature problems, permission gaps, IP allowlist mismatch, or account-mode mismatch.
It also reports where each critical Bybit setting came from: exported shell/process environment, env file, or unset.

The `env-debug` command never prints the raw API key or secret. It only shows source, presence, string length, and a short SHA-256 prefix so you can confirm whether two runs are using the same loaded values without exposing the secrets.

## Example Evaluation Request

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/paper-trades/evaluate \
  -H 'Content-Type: application/json' \
  -d '{
    "instrument": "BTCUSD",
    "provider": "bitstamp",
    "session": "new_york",
    "direction": "long",
    "source_mode": "manual_assertion",
    "weekend": false,
    "timeframes": {
      "bias": "4H",
      "setup": "15m",
      "execution": "5m"
    },
    "checklist": {
      "clear_4h_bias": true,
      "clear_liquidity_draw": true,
      "liquidity_event": true,
      "mss": true,
      "displacement": true,
      "fresh_fvg": true,
      "clear_invalidation": true,
      "clear_target": true,
      "chase_entry": false
    },
    "screenshot_paths": [
      "screenshots/example-4h.png",
      "screenshots/example-15m.png",
      "screenshots/example-5m.png"
    ],
    "notes": "Paper-test candidate"
  }'
```

This manual example will be labeled `journal_only` unless a real scanner-verified or hybrid source mode is supplied. Screenshot paths are stored as supporting context only; the core engine does not read the image.

## Example TradingView Webhook Request

Use a valid JSON alert body so TradingView sends `application/json`.

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/webhooks/tradingview \
  -H 'Content-Type: application/json' \
  -d '{
    "passphrase": "shared-secret",
    "ticker": "BITSTAMP:BTCUSD",
    "session": "new_york",
    "direction": "long",
    "source_mode": "manual_assertion",
    "timeframes": {
      "bias": "4H",
      "setup": "15m",
      "execution": "5m"
    },
    "checklist": {
      "clear_4h_bias": true,
      "clear_liquidity_draw": true,
      "liquidity_event": true,
      "mss": true,
      "displacement": true,
      "fresh_fvg": true,
      "clear_invalidation": true,
      "clear_target": true,
      "chase_entry": false
    },
    "entry": {
      "type": "limit",
      "price": 71250
    },
    "risk": {
      "stop_loss": 70980,
      "take_profit": 71880,
      "take_profit_2": 72450
    },
    "futures": {
      "category": "linear",
      "symbol": "BTCUSDT",
      "qty": 0.01,
      "leverage": 3,
      "margin_mode": "isolated",
      "position_mode": "one_way"
    },
    "chart_url": "https://www.tradingview.com/chart/example",
    "notes": "TV alert test"
  }'
```

If the setup passes the Version 1 rules, the response will include:

- a `paper_trade_evaluation`
- a `webhook_id`
- an optional `order_proposal`
- an optional `proposal_id`

Proposal status meanings:

- `ready_for_submission`: the proposal includes Bybit create-order fields and passes the execution spec, exchange constraints, and sizing checks
- `review_required`: the setup passed the paper-trade rules, but the order proposal failed a sizing, leverage, RR, or exchange-validation check

## Wave 1 Auto Execution

Run one dry cycle:

```bash
cd <repo-root>
python3 paper_api/auto_execute_loop.py --once --runtime-key main
```

Run it continuously:

```bash
cd <repo-root>
python3 paper_api/auto_execute_loop.py --runtime-key main --interval-seconds 30
```

Inspect the persisted runtime and events:

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/auto-execution/policy
/usr/bin/curl -s http://127.0.0.1:8787/v1/auto-execution/runtime
/usr/bin/curl -s "http://127.0.0.1:8787/v1/auto-execution/events?limit=20"
```

Wave 1 is intentionally testnet-only. It:

- scans the watchlist
- requires a `verified_paper_trade` candidate
- derives entry, stop loss, and take profit from the existing scan context
- builds a Bybit testnet execution plan
- saves an auditable proposal
- auto-submits only if the auto-execution policy is enabled and all controls and requirements pass

The default repo policy keeps Wave 1 disabled and `auto_submit = false` until you deliberately enable it.

It does not bypass the control plane. `global`, `auto_execution`, `private_stream`, and `order_submission` can all still block submission.

## Wave 2 Trade Management

Run one dry cycle:

```bash
cd <repo-root>
python3 paper_api/trade_management_loop.py --once --runtime-key main
```

Run it continuously:

```bash
cd <repo-root>
python3 paper_api/trade_management_loop.py --runtime-key main --interval-seconds 30
```

Inspect the persisted runtime and events:

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/trade-management/policy
/usr/bin/curl -s http://127.0.0.1:8787/v1/trade-management/runtime
/usr/bin/curl -s "http://127.0.0.1:8787/v1/trade-management/events?limit=20"
```

Wave 2 is intentionally conservative. Right now it only automates:

- stale working-order cancellation after the configured age threshold
- stop-loss refresh to break-even on open positions after the configured RR threshold is reached

The default repo policy keeps Wave 2 disabled until you deliberately enable it.

It does not yet automate trailing stops, partial take profit, or discretionary exit logic.

## Example Bybit Market Requests

Fetch live candles directly from Bybit without TradingView:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/market/bybit/klines?symbol=BTCUSDT&interval=5&limit=50"
```

Fetch the latest ticker:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/market/bybit/ticker?symbol=BTCUSDT"
```

Fetch instrument constraints such as tick size, qty step, min notional, and leverage caps:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/market/bybit/instrument?symbol=BTCUSDT&category=linear"
```

Inspect the active execution spec:

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/execution/spec
```

Run a first-pass ICT Version 1 scan from Bybit public data:

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/scans/bybit/ict-v1 \
  -H 'Content-Type: application/json' \
  -d '{
    "instrument": "BTCUSDT",
    "category": "linear",
    "auto_log": false,
    "record_history": true
  }'
```

The scan response includes:

- live Bybit-backed context for `4H`, `15m`, and `5m`
- DRT / liquidity-event / narrative / context outputs plus execution-layer MSS, displacement, and FVG reads
- a paper-trade payload in the same shape as the manual workflow
- a DRT-first paper-trade evaluation with explicit verification state

This scanner is intentionally conservative and still requires manual visual confirmation. The core engine does not implement verified chart-image reading.

Build an execution plan from a scanner-verified setup that already meets the ICT house rules:

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/execution/plan \
  -H 'Content-Type: application/json' \
  -d '{
    "instrument": "BTCUSDT",
    "provider": "bybit-public-api",
    "session": "london",
    "direction": "long",
    "source_mode": "scanner_verified",
    "visual_analysis_state": "not_run",
    "weekend": false,
    "timeframes": {
      "bias": "4H",
      "setup": "15m",
      "execution": "5m"
    },
    "checklist": {
      "clear_4h_bias": true,
      "clear_liquidity_draw": true,
      "liquidity_event": true,
      "mss": true,
      "displacement": true,
      "fresh_fvg": true,
      "clear_invalidation": true,
      "clear_target": true,
      "chase_entry": false
    },
    "entry": {
      "type": "limit",
      "price": 72000
    },
    "risk": {
      "stop_loss": 71750,
      "take_profit": 72550
    },
    "account": {
      "equity": 10000,
      "available_balance": 5000
    },
    "futures": {
      "symbol": "BTCUSDT",
      "category": "linear"
    }
  }'
```

This endpoint evaluates the setup first and then:

- loads the local execution spec
- fetches Bybit instrument constraints
- sizes the order from account equity if explicit `qty` is not provided
- validates RR, leverage, min qty, min notional, and margin usage
- returns a `ready_for_submission` or `review_required` proposal

Inspect tracked execution state for saved proposals:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/execution-state?limit=20"
```

Inspect one proposal's latest synced lifecycle snapshot:

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/execution-state/BP-001
```

Inspect audited execution actions:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/execution-actions?limit=20"
```

Inspect currently active supervised proposals without forcing a sync:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/supervisor/active?limit=20"
```

Inspect the persisted control-plane state:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/control/state"
```

Pause only Bybit testnet submission while leaving scanners and supervisors running:

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/control/state \
  -H 'Content-Type: application/json' \
  -d '{
    "control_key": "order_submission",
    "paused": true,
    "reason": "review window",
    "updated_by": "operator"
  }'
```

Enable the global kill switch across all control-aware loops:

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/control/kill-switch \
  -H 'Content-Type: application/json' \
  -d '{
    "paused": true,
    "reason": "manual maintenance",
    "updated_by": "operator"
  }'
```

Resume the global kill switch:

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/control/kill-switch \
  -H 'Content-Type: application/json' \
  -d '{
    "paused": false,
    "reason": "maintenance finished",
    "updated_by": "operator"
  }'
```

Inspect recent control-plane audit events:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/control/events?limit=20"
```

Inspect the read-only operations watchdog status:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/operations/status"
```

Inspect persisted operations watchdog runtimes:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/operations/runtime"
```

Inspect persisted operations watchdog events:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/operations/events?limit=20"
```

Run a supervisor scan and sync active submitted proposals:

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/supervisor/scan \
  -H 'Content-Type: application/json' \
  -d '{
    "limit": 20,
    "sync_active": true,
    "include_inactive": false
  }'
```

Inspect persisted supervisor runtime state:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/supervisor/runtime"
```

Inspect recent supervisor events:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/supervisor/events?limit=20"
```

Inspect persisted private-stream runtime state:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/private-stream/runtime"
```

Inspect recent private-stream events:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/private-stream/events?limit=20"
```

Run a one-shot watchlist scan for both BTCUSDT and ETHUSDT:

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/scans/bybit/watchlist \
  -H 'Content-Type: application/json' \
  -d '{
    "instruments": ["BTCUSDT", "ETHUSDT"],
    "category": "linear",
    "auto_log_candidates": false,
    "persistent_dedupe": true,
    "record_history": true
  }'
```

Run a replay scan over recent historical windows for one instrument:

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/scans/bybit/replay \
  -H 'Content-Type: application/json' \
  -d '{
    "instrument": "BTCUSDT",
    "category": "linear",
    "max_steps": 50,
    "step_stride": 5,
    "record_history": false
  }'
```

Inspect the persistent watchlist state:

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/watchlist-state
```

Inspect recent scan history:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/scan-history?limit=20"
```

Inspect only BTCUSDT watchlist scans:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/scan-history?instrument=BTCUSDT&source=watchlist&limit=20"
```

Inspect recent signal traces:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/signal-traces?limit=20"
```

Inspect only rejected BTCUSDT watchlist traces:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/signal-traces?symbol=BTCUSDT&source_path=watchlist&execution_eligible=false&limit=20"
```

Inspect traces for a replay window:

```bash
/usr/bin/curl -s "http://127.0.0.1:8787/v1/signal-traces?source_path=replay&reference_timestamp_from=2026-04-18T06:00:00%2B00:00&reference_timestamp_to=2026-04-18T09:00:00%2B00:00&limit=50"
```

Inspect one exact trace:

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/signal-traces/ST-00001
```

Each signal trace stores the decision snapshot at one evaluation point, including:

- `symbol`
- `reference_timestamp`
- `source_path`
- `drt_state`
- `drt_confidence`
- `liquidity_event`
- `liquidity_reference_alignment`
- `bias`
- `narrative_state`
- `context_state`
- `session_state`
- `mss_15m_state`
- `displacement_5m_state`
- `fvg_5m_state`
- `chase_state`
- `decision`
- `execution_eligible`
- `blocker_reasons`
- `ambiguity_flags`
- `source_mode`
- `visual_analysis_state`

For a missed setup, the quickest operator flow is:

1. Query `/v1/signal-traces` by `symbol`, `source_path`, and a tight `reference_timestamp_from` / `reference_timestamp_to` window.
2. Open the matching trace with `/v1/signal-traces/<trace-id>`.
3. Read `decision`, `execution_eligible`, `blocker_class`, `primary_blocker_reason`, and the trace payload's `blocker_reasons`.
4. Use the detailed fields to see whether the miss came from session timing, source verification, DRT or narrative ambiguity, missing MSS or FVG confirmation, or a chase-state rejection.

## Watchlist Loop

If you want repeated scans without TradingView, run:

```bash
cd <repo-root>
python3 paper_api/scan_loop.py --once
```

To keep scanning every 5 minutes and auto-log only new candidate setups:

```bash
cd <repo-root>
python3 paper_api/scan_loop.py --interval-seconds 300 --auto-log-candidates
```

If you want to replay recent historical windows with the same scan logic:

```bash
cd <repo-root>
python3 paper_api/replay_scan.py --instrument BTCUSDT --max-steps 50 --step-stride 5
```

If you want replay to judge only tradable session windows:

```bash
cd <repo-root>
python3 paper_api/replay_scan.py --instrument BTCUSDT --max-steps 50 --step-stride 5 --tradable-only
```

If you only want the aggregate summary and a candidate export file:

```bash
cd <repo-root>
python3 paper_api/replay_scan.py \
  --instrument BTCUSDT \
  --max-steps 100 \
  --step-stride 3 \
  --summary-only \
  --export-candidates /tmp/btcusdt-replay-candidates.jsonl
```

Compare replay summaries across BTCUSDT and ETHUSDT:

```bash
cd <repo-root>
python3 paper_api/replay_compare.py --max-steps 100 --step-stride 3 --summary-only
```

Compare only tradable replay windows:

```bash
cd <repo-root>
python3 paper_api/replay_compare.py --max-steps 100 --step-stride 3 --summary-only --tradable-only
```

Export one candidate file per instrument while comparing:

```bash
cd <repo-root>
python3 paper_api/replay_compare.py \
  --max-steps 100 \
  --step-stride 3 \
  --summary-only \
  --export-candidates-dir /tmp/replay-compare-candidates
```

Turn the replay comparison into a tuning report with blocker-ratio gaps and rule-adjustment hints:

```bash
cd <repo-root>
python3 paper_api/replay_tune.py --max-steps 100 --step-stride 3
```

If you want the tuning report to ignore outside-session windows:

```bash
cd <repo-root>
python3 paper_api/replay_tune.py --max-steps 100 --step-stride 3 --tradable-only
```

If you want the structured JSON report:

```bash
cd <repo-root>
python3 paper_api/replay_tune.py --max-steps 100 --step-stride 3 --json
```

If you want to save a baseline tuning report, then compare a later run after a rules change:

```bash
cd <repo-root>
python3 paper_api/replay_tune.py \
  --max-steps 100 \
  --step-stride 3 \
  --save-report /tmp/ict-replay-baseline.json

python3 paper_api/replay_tune.py \
  --max-steps 100 \
  --step-stride 3 \
  --compare-report /tmp/ict-replay-baseline.json
```

Replay mode uses the same heuristic scan logic as the live Bybit public-data path, but evaluates recent closed-candle windows with a timestamp override. It is useful for concept training and burn-in review when private auth or order submission is unavailable.

The loop uses persistent SQLite-backed dedupe by default, so it will not keep logging the same active candidate after restarts unless the signal changes and then returns later.

The loop also records scan history by default, so you can review context changes even when no paper trade was taken.

The loop obeys both the global kill switch and the `scan_loop` control key.

If you want process-local dedupe only:

```bash
cd <repo-root>
python3 paper_api/scan_loop.py --interval-seconds 300 --auto-log-candidates --disable-persistent-dedupe
```

If you want to disable history recording for a temporary run:

```bash
cd <repo-root>
python3 paper_api/scan_loop.py --interval-seconds 300 --auto-log-candidates --disable-history
```

## Example Outcome Update

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/paper-trades/PT-001/outcome \
  -H 'Content-Type: application/json' \
  -d '{
    "result_status": "win",
    "outcome_notes": "Target 1 and final liquidity draw reached."
  }'
```

## Example Manual Testnet Submission

This endpoint is manual only. It does nothing unless private submission is enabled and valid Bybit private credentials are configured for the selected `BYBIT_ENV`.

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/order-proposals/BP-001/submit \
  -H 'Content-Type: application/json' \
  -d '{
    "confirm": true
  }'
```

If submission succeeds, the API will also try to sync the latest order and position state immediately.

To resync later:

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/order-proposals/BP-001/sync \
  -H 'Content-Type: application/json' \
  -d '{}'
```

Execution sync requires valid Bybit testnet API credentials because it uses private order, position, and wallet endpoints.

Cancel a working order tied to a saved proposal:

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/order-proposals/BP-001/cancel \
  -H 'Content-Type: application/json' \
  -d '{
    "confirm": true
  }'
```

Close an open position tied to a saved proposal using a reduce-only market order:

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/order-proposals/BP-001/close-position \
  -H 'Content-Type: application/json' \
  -d '{
    "confirm": true
  }'
```

Both actions are recorded in the execution action log and attempt a fresh execution-state sync afterward.

Amend a working entry order tied to a saved proposal:

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/order-proposals/BP-001/amend \
  -H 'Content-Type: application/json' \
  -d '{
    "confirm": true,
    "price": 71950,
    "take_profit": 72500,
    "stop_loss": 71740
  }'
```

Refresh TP/SL or trailing stop for an open proposal-linked position:

```bash
/usr/bin/curl -s http://127.0.0.1:8787/v1/order-proposals/BP-001/refresh-trading-stop \
  -H 'Content-Type: application/json' \
  -d '{
    "confirm": true,
    "take_profit": 72600,
    "stop_loss": 71920
  }'
```

`/amend` is for working orders. `/refresh-trading-stop` is for open positions. Both actions are audited and followed by an execution-state sync.

## Supervisor Loop

To supervise active proposals continuously:

```bash
cd <repo-root>
python3 paper_api/supervisor_loop.py --once
```

To keep supervising every minute:

```bash
cd <repo-root>
python3 paper_api/supervisor_loop.py --interval-seconds 60
```

To run it with a named persistent runtime key:

```bash
cd <repo-root>
python3 paper_api/supervisor_loop.py --runtime-key main --interval-seconds 60
```

The supervisor loop:

- inspects recent Bybit testnet proposals
- syncs active submitted proposals when credentials are available
- stores restart-safe runtime state in SQLite so it can resume after restarts
- emits supervisor events when proposals appear, change lifecycle, fail to sync, or drop out of the active set
- classifies each proposal into a recommendation such as `monitor_working_order`, `monitor_open_position`, or `await_submission`
- obeys both the global kill switch and the `supervisor` control key
- does not submit, cancel, amend, or close anything by itself

## Operations Watchdog

To run a read-only watchdog pass once:

```bash
cd <repo-root>
python3 paper_api/ops_loop.py --once
```

To keep recording operator incidents every 30 seconds:

```bash
cd <repo-root>
python3 paper_api/ops_loop.py --runtime-key main --interval-seconds 30
```

Optional thresholds:

```bash
cd <repo-root>
python3 paper_api/ops_loop.py \
  --runtime-key main \
  --interval-seconds 30 \
  --watchlist-stale-after-seconds 900 \
  --supervisor-stale-after-seconds 180 \
  --private-stream-stale-after-seconds 90
```

The watchdog:

- is read-only and never places, amends, cancels, or closes orders
- evaluates control state, watchlist freshness, supervisor freshness, and private-stream health
- persists runtime state and operator events to SQLite
- emits events when a component becomes unhealthy, changes status, or recovers
- is intended for burn-in and operator visibility, not for trade decision making

## Private Stream Loop

To start a Bybit private websocket reconciler on testnet:

```bash
cd <repo-root>
BYBIT_API_KEY=your-bybit-testnet-key \
BYBIT_API_SECRET=your-bybit-testnet-secret \
python3 paper_api/private_stream_loop.py --runtime-key stream-main
```

Optional flags:

```bash
cd <repo-root>
BYBIT_API_KEY=your-bybit-testnet-key \
BYBIT_API_SECRET=your-bybit-testnet-secret \
python3 paper_api/private_stream_loop.py \
  --runtime-key stream-main \
  --topics order,execution,position,wallet \
  --ping-interval-seconds 20 \
  --max-active-time 1m
```

The private stream loop:

- connects to the official Bybit private websocket
- authenticates and subscribes to `order`, `execution`, `position`, and `wallet`
- reconciles matching stream messages back into the existing `execution_state` records
- persists its own runtime state and events so restart recovery is observable
- obeys both the global kill switch and the `private_stream` control key
- does not place, amend, cancel, or close orders by itself

## TradingView Notes

TradingView’s official webhook guidance says:

- valid JSON alert bodies are sent as `application/json`
- only ports `80` and `443` are accepted for real webhook delivery
- requests are canceled if the remote server takes longer than about `3` seconds

That means local testing on `127.0.0.1:8787` is for curl/manual testing only. For real TradingView delivery, expose the API through a secure HTTPS endpoint or reverse proxy on an allowed port.

If you do not have a TradingView paid plan, use the Bybit market-data endpoints and the Bybit ICT scan instead of webhooks.

## Bybit Notes

The API builds proposals for Bybit testnet using the official V5 create-order shape.

Important limitations:

- live market scanning uses `BYBIT_MARKET_BASE_URL`, which defaults to `https://api.bybit.com`
- regional Bybit domains such as `https://api.bybit.tr` can be supplied explicitly through `BYBIT_MARKET_BASE_URL` when required by the account jurisdiction
- order submission is manual only and disabled by default
- when enabled, this service submits only to Bybit testnet and only through `POST /v1/order-proposals/<proposal-id>/submit`
- leverage is included as advisory metadata and as a separate `set_leverage` pre-submit action because Bybit handles leverage outside `/v5/order/create`
- `qty` can be auto-sized when the request includes account equity or available balance plus a valid stop distance; otherwise provide explicit `qty`
- the Bybit ICT scan is heuristic and should not be treated as a broker-ready signal generator

## Control Plane

The API has a persisted control plane for safe operator intervention.

Supported control keys:

- `global`
- `scan_loop`
- `supervisor`
- `private_stream`
- `order_submission`

How it works:

- `global` pauses every control-aware loop and blocks order submission
- a specific control key pauses only that subsystem
- effective pause state is merged from `global` plus the specific key
- every control update writes an audit event to SQLite

Current behavior:

- `scan_loop.py` checks `scan_loop` before every cycle
- `supervisor_loop.py` checks `supervisor` before every cycle and persists paused runtime state
- `private_stream_loop.py` checks `private_stream` before connecting and while streaming
- proposal submission checks `order_submission` before any Bybit testnet order call

## Storage

Data is stored in:

the user application-data directory by default, falling back to `/tmp/trading-paper-trading.db` only when that directory cannot be created, or `TRADING_API_DB_PATH` if set
