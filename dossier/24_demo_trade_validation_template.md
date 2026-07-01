# Demo Trade Validation Template

Use one copy of this template per meaningful demo / testnet trade or attempted trade.

## Trade Record

- Date:
- Symbol:
- Shadow session ID:
- Reference timestamp:
- Scan trigger:
- Decision:
- Opportunity state:
- Execution eligible: yes / no
- Trace ID:
- Intent ID:
- Proposal ID:

## Strategy / Context Snapshot

- DRT state:
- DRT confidence:
- Liquidity event:
- Liquidity reference alignment:
- Bias:
- Narrative state:
- Context state:
- Session state:
- 15m MSS state:
- 5m displacement state:
- 5m FVG state:
- Chase state:
- Blocker class:
- Blocker reasons:

## OMS Lifecycle

Mark all states reached:

- [ ] `signal_detected`
- [ ] `execution_plan_created`
- [ ] `order_submission_pending`
- [ ] `order_submitted`
- [ ] `order_acknowledged`
- [ ] `partially_filled`
- [ ] `fully_filled`
- [ ] `cancelled`
- [ ] `rejected`
- [ ] `flattened`
- [ ] `reconciled`

Notes on transitions:

- did any transition fail?
- did any transition repeat unexpectedly?
- did sync match the expected state?

## Risk Review

- Risk check state:
- Risk summary:
- Risk blocker reasons:
- Any risk rule triggered unexpectedly: yes / no
- Any risk rule failed to trigger when expected: yes / no

## Operator Review

### Did the system behave correctly?

- [ ] Yes
- [ ] Partly
- [ ] No

### If no or partly, what was wrong?

- [ ] missed intent creation
- [ ] duplicate intent
- [ ] incorrect risk block
- [ ] incorrect OMS transition
- [ ] reconciliation mismatch
- [ ] stale data / sync issue
- [ ] unexplained decision mismatch
- [ ] other

Details:

## Final Outcome

- Trade lifecycle status:
- Correct according to system rules: yes / no
- Correct according to operator judgment: yes / no
- Follow-up needed: yes / no

Follow-up notes:
