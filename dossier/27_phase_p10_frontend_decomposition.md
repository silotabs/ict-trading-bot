# Phase P10: Frontend Decomposition

Purpose: reduce frontend monolith risk without changing backend semantics, strategy logic, or execution eligibility.

## Scope

Phase P10 focuses on the verified structural issues around the current web UI:

- reduce `web/src/App.tsx` by moving shared dashboard support code into dedicated modules
- split `web/src/lib/api.ts` into a stable barrel plus domain modules
- extract reusable chart support helpers out of `web/src/components/TerminalChart.tsx`
- preserve the current operator-facing UI behavior and backend contract

## Non-goals

Phase P10 does not:

- change backend trading semantics
- widen execution eligibility
- replace the chart renderer
- redesign the dashboard
- add live trading behavior

## Deliverables

- `web/src/dashboard/app-support.tsx` owns the pre-App dashboard types, helpers, and reusable panels
- `web/src/lib/api-core.ts`, `api-types.ts`, `api-market.ts`, `api-runtime.ts`, and `api-actions.ts` own the frontend API surface by concern
- `web/src/lib/api.ts` becomes a stable barrel for the rest of the app
- `web/src/components/terminal-chart-support.tsx` owns reusable chart helpers and props/types
- `App.tsx` materially shrinks while preserving current operator behavior

## Completion Criteria

Phase P10 is complete when:

- `App.tsx` is materially smaller than the pre-P10 baseline
- `api.ts` is no longer a mixed monolith of helpers, types, and fetchers
- `TerminalChart.tsx` has a cleaner support seam
- the frontend production build passes without changing runtime semantics

## Result

Phase P10 is complete once the frontend decomposition above is present and the web build is green.
