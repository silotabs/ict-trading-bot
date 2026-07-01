# Incident And Rollback Runbook

## Purpose

This runbook defines the operator response path for runtime incidents relevant to future live-readiness planning.

It applies to the current paper / daemon stack only.

It does not authorize live execution.

## Immediate Safety Actions

If any execution-adjacent anomaly appears, operators should take the following actions in order:

1. assert global execution disable
2. assert emergency stop / kill-switch
3. preserve logs, traces, intents, and risk-check evidence
4. stop advancing execution intents until state is reconciled

## Trigger Conditions

Use this runbook when any of the following occurs:

- duplicate active execution intent
- risk block failed to halt advancement
- stale market-data lockout failed
- stale sync lockout failed
- execution state and OMS state diverge
- repeated unexplained empty-read after successful trace write
- read model does not match stored execution or risk records
- event-driven close handling misses or duplicates bars materially

## Incident Triage Levels

### Severity 1

Immediate stop required.

Examples:

- emergency stop failure
- risk bypass
- execution advancement while policy should block
- duplicate active intent with real downstream advancement

### Severity 2

Runtime is still responsive, but readiness is compromised.

Examples:

- stale sync handling is unreliable
- read-after-write inconsistency repeats
- blocker summaries are missing or corrupted

### Severity 3

Observation issue or degraded review tooling without execution boundary breach.

Examples:

- shadow summary endpoint mismatch
- delayed read visibility without lost data

## Rollback Steps

1. freeze execution advancement through control state and policy gates
2. capture:
   - runtime status
   - readiness status
   - signal traces
   - execution intents
   - execution risk checks
   - relevant daemon logs
3. identify last known good release / commit
4. redeploy or restart to the last known good baseline
5. rerun:
   - paper / daemon trust gate
   - smoke test runbook
   - targeted incident reproduction checks
6. do not resume normal operation until the rollback baseline is verified

## Read-After-Write Anomaly Procedure

If a newly written trace, intent, or risk record is not immediately queryable:

1. verify persistence directly in the store if possible
2. retry the read through the API
3. capture timestamps for:
   - write completion
   - first empty read
   - first successful read
4. classify whether the issue is:
   - persistence failure
   - read-path lag
   - route / filter mismatch
   - unknown
5. if repeated, escalate to a no-go blocker for live planning

## Reconciliation Failure Procedure

If OMS state and stored execution state diverge:

1. pause execution advancement
2. identify affected `intent_id`, `proposal_id`, and related runtime keys
3. classify latest known intent state:
   - pending
   - acknowledged
   - partially filled
   - fully filled
   - cancelled
   - rejected
   - flattened
4. reconcile against stored events and runtime status
5. only resume after the final reconciled state is explicit and recorded

## Operator Signoff After Incident

Before clearing an incident:

- runtime owner signs off
- risk-control owner signs off
- reconciliation owner signs off
- release-check owner signs off

## Required Evidence Retention

For every incident or rollback drill, retain:

- time window of the incident
- affected symbols
- trace identifiers
- execution intent identifiers
- risk-check identifiers
- operator actions taken
- final disposition
