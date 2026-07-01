# One-Day Acceptance Checklist

Purpose: run a compressed acceptance pass for the current paper / daemon system without changing strategy or widening execution scope.

Status target:

- `pass`
- `pass with blockers`
- `fail`

## Ground Rules

- no live trading
- demo / testnet or shadow-only operation
- no strategy retuning during the acceptance day
- record issues as observed; do not explain away failures
- the current trusted execution boundary remains in force:
  - only `verified_paper_trade` is execution-eligible

---

## 1. Startup and Readiness

### Backend

- [ ] backend service starts cleanly
- [ ] `/ready` returns healthy
- [ ] no obvious startup errors in logs
- [ ] event stream is connected
- [ ] risk policy is loaded
- [ ] OMS / execution state layer is available
- [ ] signal-trace persistence is available

### Frontend / Web UI

- [ ] UI starts cleanly
- [ ] UI reflects current backend state
- [ ] no obvious stale bundle / stale schema issue
- [ ] new routes / data surfaces are visible where expected

### Quick API Checks

- [ ] `GET /ready`
- [ ] `GET /v1/signal-traces?limit=5`
- [ ] `GET /v1/execution-intents?limit=5`
- [ ] `GET /v1/execution-risk-checks?limit=5`
- [ ] `GET /v1/shadow-review/summary`

Result notes:

- readiness status:
- startup issues:
- UI issues:

---

## 2. Shadow Scan Validation

Goal: confirm the system observes market conditions and records traceable decisions.

- [ ] trigger a shadow scan path
- [ ] confirm traces are written
- [ ] confirm traces can be filtered by:
  - [ ] decision
  - [ ] opportunity_state
  - [ ] blocker_class
  - [ ] symbol
  - [ ] session_state
  - [ ] shadow_mode
  - [ ] shadow_session_id
- [ ] confirm summary route returns blocker / opportunity breakdown

Expected states seen during the day:

- [ ] `verified_paper_trade`
- [ ] `near_miss`
- [ ] `awaiting_confirmation`
- [ ] `context_watch`
- [ ] `invalid`

Result notes:

- shadow session ID:
- number of traces observed:
- most common blocker class:
- summary route working: yes / no

---

## 3. Manual False-Negative Review

Goal: compare trades the operator sees versus what the system saw.

Select `3` to `10` chart moments that looked tradable.

For each case record:

- symbol
- timestamp
- what the operator saw
- system decision
- opportunity state
- blocker class
- blocker reasons
- whether the miss is understandable

Checklist:

- [ ] at least `3` manual candidate trades reviewed
- [ ] each reviewed trade matched to a trace or confirmed absent
- [ ] every miss has recorded blocker reasons
- [ ] misses can be grouped into recurring causes
- [ ] no unexplained black-box miss remains

Result notes:

- number of reviewed manual trades:
- number system recognized as verified:
- number marked near_miss:
- number marked awaiting_confirmation:
- number that remain unexplained:

---

## 4. Demo / Testnet Trade Lifecycle Validation

Goal: confirm at least one full eligible path behaves correctly.

Use [24_demo_trade_validation_template.md](./24_demo_trade_validation_template.md) for each meaningful demo / testnet trade or attempted trade reviewed during this section.

Checklist:

- [ ] `verified_paper_trade` produced an execution intent
- [ ] intent entered `signal_detected`
- [ ] intent advanced to `execution_plan_created`
- [ ] risk check executed
- [ ] submission path recorded correctly
- [ ] OMS state transitions were recorded correctly
- [ ] sync / reconciliation updated state correctly
- [ ] fill / flatten / reconcile path completed or was meaningfully exercised
- [ ] no duplicate active intent was created for the same eligible signal

Result notes:

- symbol:
- intent ID:
- proposal ID:
- final intent state:
- any mismatch between OMS and exchange / testnet state:

---

## 5. Risk and Kill-Switch Drills

Goal: verify that execution can be blocked safely.

Test the following where practical:

- [ ] operator / global pause
- [ ] max active intent count
- [ ] max open exposure notional
- [ ] stale market-data lockout
- [ ] stale execution-state lockout
- [ ] daily realized loss block
- [ ] loss-streak cooldown
- [ ] duplicate active-intent suppression

For each drill confirm:

- [ ] signal truth did not change
- [ ] intent may exist but did not advance
- [ ] risk-check record was written
- [ ] blocker reason is explicit

Result notes:

- risk drills completed:
- failures:
- ambiguous outcomes:

---

## 6. Read-After-Write Consistency Check

Goal: investigate the known immediate post-write empty-read issue.

Checklist:

- [ ] create or trigger a new shadow trace
- [ ] immediately query list endpoint
- [ ] repeat multiple times
- [ ] compare immediate API read vs follow-up API read
- [ ] compare API behavior vs repository-backed persisted record
- [ ] record exact reproduction conditions if failure occurs

Result notes:

- empty immediate read observed: yes / no
- number of attempts:
- reproducible: yes / no
- conditions observed:

---

## 7. End-of-Day Review

### Summary Metrics

- total scans:
- total traces:
- verified paper trades:
- opportunity detected:
- near misses:
- awaiting confirmation:
- context watch:
- invalid:
- total risk blocks:
- total execution intents:
- total duplicate-intent incidents:
- total read-after-write anomalies:
- total reconciliation mismatches:

### Top Blocker Clusters

1.
2.
3.

### Top False-Negative Patterns

1.
2.
3.

### Critical Incidents

- [ ] none
- [ ] yes, recorded below

Incident notes:

---

## 8. End-of-Day Outcome

Choose one:

- [ ] Pass — usable for continued paper / demo operation
- [ ] Pass with blockers — usable, but issues must be fixed
- [ ] Fail — not stable enough for ongoing demo validation

### Required Judgment

- safe to continue tomorrow: yes / no
- immediate blocker requiring fix: yes / no
- candidate for controlled live planning: no
- current standing:
  - [ ] still `hold_for_more_shadow_evidence`

Operator signoff:

- name:
- date:
- notes:
