# Paper / Daemon Trust Gate

## Scope

This trust gate is the conservative operator acceptance check for the current paper / daemon baseline.

It is intentionally limited to:

- paper / daemon workflows
- current corrected verification semantics
- current disabled-by-default auto-execution policy

It does not authorize or imply:

- live trading
- verified chart-image analysis
- broader ICT concept expansion
- new strategy logic

## Minimum Operator Flows

The baseline is considered operationally trustworthy only if all of these flows pass:

- manual or webhook payload normalizes cleanly, evaluates cleanly, and stays non-executable
- scanner-verified payload can reach `verified_paper_trade`
- only `verified_paper_trade` is execution-plan eligible
- replay scan output is deterministic for the same replay window and reference timestamps
- watchlist logging remains verified-only
- auto-execute stays non-submitting while policy is disabled
- chart or screenshot payloads stay `manual_context_only`
- no-chart scanner-style payloads stay `not_run`

## Pass Criteria

- No smoke command raises a traceback or test failure.
- Every targeted smoke command in [18_smoke_test_runbook.md](./18_smoke_test_runbook.md) ends in the expected `Ran ... OK` output.
- The full test suite passes after the smoke checks.

## Acceptance Checklist

- [ ] Repo is in the trusted paper / daemon baseline and no strategy-logic edits were required for the smoke pass.
- [ ] Manual payload smoke passed: `manual_assertion` stays non-executable and does not become execution-plan eligible.
- [ ] Scanner-verified payload smoke passed: `verified_paper_trade` remains execution-plan eligible.
- [ ] Replay determinism smoke passed at a fixed reference window.
- [ ] Watchlist verified-only gate smoke passed for both negative and positive cases.
- [ ] Disabled-policy auto-execute smoke passed and submitted nothing.
- [ ] Chart / screenshot payload smoke passed as `manual_context_only`.
- [ ] No-chart scanner payload smoke passed as `not_run`.
- [ ] Full test suite passed.

## Operator Reading

Use [18_smoke_test_runbook.md](./18_smoke_test_runbook.md) for the exact commands and expected outputs.
