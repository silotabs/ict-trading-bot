# Operator Smoke Test Runbook

## Purpose

This runbook proves the current repo state is trustworthy for paper / daemon operation without changing strategy logic.

It is designed to be:

- repeatable
- deterministic where possible
- small enough to run before operator handoff

## Preconditions

Run everything from the repo root:

```bash
cd /Users/silo/Downloads/trading
```

The smoke pack below relies on the existing acceptance tests because they are deterministic and already encode the current baseline semantics.

Use the built-in `unittest` runner so the smoke pass does not depend on `pytest` being installed.

If you want a broader operator acceptance pass after the deterministic smoke checks, use [23_one_day_acceptance_checklist.md](./23_one_day_acceptance_checklist.md).

## Optional Daemon Sanity

Use these when you want a quick live-process check before or after the deterministic smoke pack.

Command:

```bash
python3 paper_api/stackctl.py status --json
```

Expected output:

- JSON object
- includes managed-service status keys such as `server`, `scan_loop`, and `auto_execute_loop`
- no traceback

If `status --json` disagrees with a live route while you are inside a restricted shell, treat the live route as the stronger signal and confirm the listening process from the OS.

Command:

```bash
/usr/bin/curl -s http://127.0.0.1:8787/health
```

Expected output:

- JSON response
- contains `"status": "ok"`
- contains `"service": "paper-trading-api"`
- no traceback

## Acceptance Smoke Commands

### 1. Manual Payload -> Normalize -> Evaluate -> Non-Executable

Command:

```bash
python3 -m unittest -q tests.test_phase7_integration.TestPhase7Integration.test_webhook_manual_assertion_normalize_evaluate_gate_end_to_end
```

Expected output:

- output includes `Ran 1 test`
- output ends with `OK`
- covered behavior:
  - normalized `source_mode` is `manual_assertion`
  - `visual_analysis_state` is `manual_context_only`
  - evaluation decision is `journal_only`
  - execution-plan gate stays false

### 2. Scanner-Verified Payload -> Verified -> Execution-Plan Eligible

Command:

```bash
python3 -m unittest -q tests.test_phase7_integration.TestPhase7Integration.test_webhook_scanner_verified_only_reaches_verified_paper_trade_with_full_gate
```

Expected output:

- output includes `Ran 1 test`
- output ends with `OK`
- covered behavior:
  - normalized `source_mode` is `scanner_verified`
  - evaluation decision is `verified_paper_trade`
  - execution-plan gate is true

### 3. Replay Scan -> Fixed Reference Window -> Deterministic Output

Command:

```bash
python3 -m unittest -q tests.test_phase7_integration.TestPhase7Integration.test_replay_scan_reference_time_is_deterministic_end_to_end
```

Expected output:

- output includes `Ran 1 test`
- output ends with `OK`
- covered behavior:
  - two replay runs over the same candle inputs return the same replay summary
  - reference timestamps, decisions, sessions, and directions stay stable

### 4. Watchlist / Scan Path -> Verified-Only Gating

Command:

```bash
python3 -m unittest -q \
  tests.test_ict_engine_alignment.TestIctEngineAlignment.test_watchlist_scan_does_not_log_scanner_candidate \
  tests.test_ict_engine_alignment.TestIctEngineAlignment.test_watchlist_scan_logs_verified_paper_trade_candidate
```

Expected output:

- output includes `Ran 2 tests`
- output ends with `OK`
- covered behavior:
  - `scanner_candidate` does not auto-log
  - `verified_paper_trade` does auto-log

### 5. Auto-Execute Loop With Disabled Policy -> Never Submits

Command:

```bash
python3 -m unittest -q tests.test_phase7_integration.TestPhase7Integration.test_auto_execute_loop_disabled_policy_never_submits_even_with_verified_candidate
```

Expected output:

- output includes `Ran 1 test`
- output ends with `OK`
- covered behavior:
  - cycle mode is `disabled`
  - `policy_enabled` is false
  - `submitted` stays `0`
  - no submission function is called

### 6. Chart / Screenshot Payload -> `manual_context_only`

Command:

```bash
python3 -m unittest -q tests.test_phase10_release_gate.TestPhase10ReleaseGate.test_release_gate_requires_manual_context_only_for_chart_payloads
```

Expected output:

- output includes `Ran 1 test`
- output ends with `OK`
- covered behavior:
  - evaluation and webhook examples with chart context normalize to `manual_context_only`

### 7. No-Chart Scanner Path -> `not_run`

Command:

```bash
python3 -m unittest -q tests.test_phase10_release_gate.TestPhase10ReleaseGate.test_release_gate_requires_docs_examples_match_current_schema
```

Expected output:

- output includes `Ran 1 test`
- output ends with `OK`
- covered behavior:
  - scanner-verified execution-plan example normalizes with `visual_analysis_state = not_run`
  - canonical checklist field remains `liquidity_event`

## Full Smoke Pack

If you want one deterministic acceptance pass for the operator handoff, run:

```bash
python3 -m unittest -q \
  tests.test_phase7_integration \
  tests.test_ict_engine_alignment \
  tests.test_phase9_docs_contract \
  tests.test_phase10_release_gate
```

Expected output:

- all tests pass
- output ends with `OK`
- no traceback

## Full Repo Test Suite

Run this after the smoke pack:

```bash
python3 -m unittest discover -s tests -q
```

Expected output:

- full suite passes
- output ends with `OK`
- no traceback

## Stop Rule

Stop for review if any smoke command fails, if a live sanity command returns an error, or if a fix would require strategy-logic changes.
