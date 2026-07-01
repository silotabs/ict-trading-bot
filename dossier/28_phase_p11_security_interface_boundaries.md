# Phase P11: Security And Interface Boundaries

Purpose: close the verified security and interface-boundary gaps without changing strategy logic, execution eligibility, OMS behavior, or risk semantics.

## Scope

Phase P11 addresses three verified issues:

- add an optional operator-auth boundary for sensitive non-webhook control and execution routes
- decouple `runtime_repositories.py` from direct `shadow_review.py` imports with an injected summarizer seam
- formalize the public `ict_engine` package surface with explicit exports

## Non-goals

Phase P11 does not:

- change strategy logic
- widen execution eligibility
- add live trading
- change OMS or risk behavior

## Deliverables

- `TRADING_API_OPERATOR_TOKEN` enables opt-in protection for sensitive POST control/execution routes
- auth accepts either `X-Trading-Operator-Token` or `Authorization: Bearer ...`
- default local paper behavior remains unchanged when no token is configured
- `runtime_repositories.py` exposes a summarizer protocol/injection seam instead of a hard import
- `paper_api/ict_engine/__init__.py` exports the package’s supported public surface explicitly

## Completion Criteria

Phase P11 is complete when:

- sensitive operator routes can be protected without changing the default local baseline
- runtime repositories no longer hard-import `shadow_review` at module import time
- the `ict_engine` package has an explicit public API
- backend tests remain green

## Result

Phase P11 is complete once the auth seam, repository seam, and engine export surface are all in place and verified.
