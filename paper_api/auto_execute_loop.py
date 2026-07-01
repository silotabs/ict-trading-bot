#!/usr/bin/env python3

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from runtime_api import (
    OPERATIONS_DEFAULT_THRESHOLDS,
    TradingAPIHandler,
    age_seconds_from_iso,
    build_auto_execution_payload,
    build_bybit_execution_plan,
    clean_string,
    coerce_bool,
    decision_allows_execution_plan,
    ensure_execution_intent_for_scan_result,
    evaluate_execution_risk,
    evaluate_payload,
    find_active_auto_execution_match,
    list_active_order_proposals,
    load_auto_execution_policy,
    load_risk_control_policy,
    normalize_instrument,
    resolve_control_state,
    run_watchlist_scan,
    submit_saved_order_proposal_record,
    utc_now_iso,
)
from runtime_repositories import build_runtime_repositories


TRACKED_FIELDS = (
    "last_scan_signature",
    "last_decision",
    "last_action",
    "reason",
    "proposal_id",
)

WARNING_ACTIONS = {
    "blocked",
    "blocked_active_symbol",
    "blocked_max_active_total",
    "blocked_private_stream",
    "levels_unavailable",
    "plan_review_required",
    "scan_failed",
    "submission_failed",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run Wave 1 testnet auto-execution after valid watchlist scans."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single auto-execution cycle and exit.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=30,
        help="Seconds to wait between auto-execution cycles. Default: 30.",
    )
    parser.add_argument(
        "--runtime-key",
        default="default",
        help="Auto-execution runtime key used for restart-safe state and event persistence. Default: default.",
    )
    parser.add_argument(
        "--disable-events",
        action="store_true",
        help="Do not persist auto-execution events to SQLite.",
    )
    return parser.parse_args()


def format_event_line(event):
    instrument = event.get("instrument") or "-"
    proposal_id = event.get("proposal_id") or "-"
    return (
        f"EVENT {event.get('severity', 'info').upper()} "
        f"{event.get('event_type', 'unknown')} | {instrument} | {proposal_id} | {event.get('summary', '')}"
    )


def format_state_line(state):
    return (
        f"{state.get('instrument', 'unknown')} | "
        f"decision={state.get('last_decision', 'unknown')} | "
        f"action={state.get('last_action', 'unknown')} | "
        f"{state.get('reason', '')}"
    )


def build_event(runtime_key, event_type, severity, summary, payload, instrument=None, proposal_id=None):
    return {
        "runtime_key": runtime_key,
        "event_type": event_type,
        "severity": severity,
        "summary": summary,
        "instrument": normalize_instrument(instrument) or None,
        "proposal_id": clean_string(proposal_id),
        "payload": payload if isinstance(payload, dict) else {},
    }


def persist_events(events):
    event_ids = []
    for event in events:
        event_id = TradingAPIHandler.store.create_auto_execution_event(
            runtime_key=event["runtime_key"],
            event_type=event["event_type"],
            severity=event["severity"],
            summary=event["summary"],
            event_payload=event["payload"],
            instrument=event.get("instrument"),
            proposal_id=event.get("proposal_id"),
        )
        event_ids.append(event_id)
    return event_ids


def load_runtime_state(runtime_key):
    record = TradingAPIHandler.store.get_auto_execution_runtime(runtime_key)
    if record is None:
        return {}, None
    state = record.get("state") if isinstance(record.get("state"), dict) else {}
    return state, record


def create_runtime_start_event(runtime_key, previous_runtime):
    if previous_runtime is None:
        return build_event(
            runtime_key=runtime_key,
            event_type="runtime_started",
            severity="info",
            summary=f"auto execution runtime {runtime_key} started with no previous state",
            payload={"runtime_key": runtime_key},
        )

    return build_event(
        runtime_key=runtime_key,
        event_type="runtime_resumed",
        severity="info",
        summary=f"auto execution runtime {runtime_key} resumed from stored state",
        payload={
            "runtime_key": runtime_key,
            "previous_updated_at": previous_runtime.get("updated_at"),
            "previous_heartbeat_at": previous_runtime.get("heartbeat_at"),
            "previous_last_scan_at": previous_runtime.get("last_scan_at"),
        },
    )


def persist_runtime(runtime_key, runtime_state, last_summary):
    TradingAPIHandler.store.upsert_auto_execution_runtime(
        runtime_key=runtime_key,
        state=runtime_state,
        last_summary=last_summary,
    )


def build_runtime_summary(cycle_result):
    return {
        "scanned_at": cycle_result.get("scanned_at"),
        "policy_enabled": cycle_result.get("policy_enabled"),
        "scan_count": cycle_result.get("scan_count", 0),
        "verified_paper_trade_candidates": cycle_result.get("verified_paper_trade_candidates", 0),
        "legacy_compat_paper_trade_candidates": cycle_result.get("legacy_compat_paper_trade_candidates", 0),
        "submitted": cycle_result.get("submitted", 0),
        "blocked": cycle_result.get("blocked", 0),
        "errors": cycle_result.get("errors", 0),
    }


def copy_previous_state_with_flags(previous_state, extra=None):
    state = {
        "instrument_state": (
            previous_state.get("instrument_state")
            if isinstance(previous_state.get("instrument_state"), dict)
            else {}
        ),
        "last_scan_at": previous_state.get("last_scan_at"),
        "last_error": None,
        "_control_paused": bool(previous_state.get("_control_paused")),
        "_policy_disabled": bool(previous_state.get("_policy_disabled")),
    }
    if isinstance(extra, dict):
        state.update(extra)
    return state


def private_stream_ready(policy):
    if coerce_bool(policy.get("require_private_stream")) is not True:
        return {"ready": True, "reason": None}

    control = resolve_control_state("private_stream")
    if control["effective_paused"]:
        return {
            "ready": False,
            "reason": control["effective_reason"] or "private stream is paused",
        }

    runtimes = TradingAPIHandler.store.list_private_stream_runtime()
    if not runtimes:
        return {"ready": False, "reason": "private stream runtime is missing"}

    stale_after_seconds = OPERATIONS_DEFAULT_THRESHOLDS["private_stream_stale_after_seconds"]
    for item in runtimes:
        status = clean_string(item.get("connection_status")) or "unknown"
        state = item.get("state") if isinstance(item.get("state"), dict) else {}
        last_message_at = clean_string(item.get("last_message_at")) or clean_string(
            state.get("last_message_at")
        )
        age_seconds = age_seconds_from_iso(last_message_at or item.get("updated_at"))
        if status == "streaming" and age_seconds is not None and age_seconds <= stale_after_seconds:
            return {"ready": True, "reason": None}
    return {
        "ready": False,
        "reason": "private stream is not healthy enough for auto execution",
    }


def risk_policy_needs_order_preview(policy):
    policy = policy if isinstance(policy, dict) else {}
    section = policy.get("maximum_order_size") if isinstance(policy.get("maximum_order_size"), dict) else {}
    for value in (
        section.get("max_notional"),
        section.get("max_qty"),
        policy.get("max_order_notional"),
        policy.get("max_order_qty"),
    ):
        try:
            if float(value or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def stable_repeat_action(previous_item, scan_signature):
    if not isinstance(previous_item, dict):
        return False
    if clean_string(previous_item.get("last_scan_signature")) != clean_string(scan_signature):
        return False
    return clean_string(previous_item.get("last_action")) in {
        "submitted_testnet",
        "proposal_created",
    }


def build_instrument_state(
    instrument,
    scan_result,
    action,
    reason,
    proposal_id=None,
    details=None,
):
    evaluation = scan_result.get("paper_trade_evaluation") if isinstance(scan_result, dict) else {}
    return {
        "instrument": instrument,
        "last_scan_signature": scan_result.get("scan_signature") if isinstance(scan_result, dict) else None,
        "last_decision": evaluation.get("decision") if isinstance(evaluation, dict) else None,
        "last_action": action,
        "reason": reason,
        "proposal_id": proposal_id,
        "updated_at": utc_now_iso(),
        "details": details if isinstance(details, dict) else {},
    }


def build_transition_events(runtime_key, previous_state, current_state):
    previous_map = (
        previous_state.get("instrument_state")
        if isinstance(previous_state.get("instrument_state"), dict)
        else {}
    )
    current_map = (
        current_state.get("instrument_state")
        if isinstance(current_state.get("instrument_state"), dict)
        else {}
    )
    events = []

    for instrument, state in current_map.items():
        previous_item = previous_map.get(instrument)
        changes = {}
        if previous_item is None:
            if state.get("last_action") not in {"no_trade"}:
                events.append(
                    build_event(
                        runtime_key=runtime_key,
                        event_type=state.get("last_action") or "state_created",
                        severity="warning" if state.get("last_action") in WARNING_ACTIONS else "info",
                        summary=state.get("reason") or f"{instrument} changed state",
                        payload={"current": state},
                        instrument=instrument,
                        proposal_id=state.get("proposal_id"),
                    )
                )
            continue

        for field in TRACKED_FIELDS:
            if previous_item.get(field) != state.get(field):
                changes[field] = {
                    "from": previous_item.get(field),
                    "to": state.get(field),
                }
        if not changes:
            continue

        action = state.get("last_action") or "state_changed"
        severity = "info"
        if action in WARNING_ACTIONS:
            severity = "warning"
        events.append(
            build_event(
                runtime_key=runtime_key,
                event_type=action,
                severity=severity,
                summary=state.get("reason") or f"{instrument} changed state",
                payload={"previous": previous_item, "current": state, "changes": changes},
                instrument=instrument,
                proposal_id=state.get("proposal_id"),
            )
        )

    return events


def run_cycle(runtime_key, previous_state, policy):
    repositories = build_runtime_repositories(TradingAPIHandler.store)
    control = resolve_control_state("auto_execution")
    if control["effective_paused"]:
        return {
            "mode": "paused",
            "control": control,
            "runtime_state": copy_previous_state_with_flags(
                previous_state,
                {
                    "_control_paused": True,
                    "_policy_disabled": False,
                    "control": control,
                },
            ),
            "summary": {
                "scanned_at": utc_now_iso(),
                "policy_enabled": True,
                "scan_count": 0,
                "verified_paper_trade_candidates": 0,
                "legacy_compat_paper_trade_candidates": 0,
                "submitted": 0,
                "blocked": 0,
                "errors": 0,
            },
            "instrument_state": copy_previous_state_with_flags(previous_state).get("instrument_state", {}),
        }

    if coerce_bool(policy.get("enabled")) is not True:
        return {
            "mode": "disabled",
            "runtime_state": copy_previous_state_with_flags(
                previous_state,
                {
                    "_control_paused": False,
                    "_policy_disabled": True,
                },
            ),
            "summary": {
                "scanned_at": utc_now_iso(),
                "policy_enabled": False,
                "scan_count": 0,
                "verified_paper_trade_candidates": 0,
                "legacy_compat_paper_trade_candidates": 0,
                "submitted": 0,
                "blocked": 0,
                "errors": 0,
            },
            "instrument_state": copy_previous_state_with_flags(previous_state).get("instrument_state", {}),
        }

    risk_policy_result = load_risk_control_policy()
    if not risk_policy_result["ok"] or coerce_bool((risk_policy_result.get("policy") or {}).get("enabled")) is not True:
        return {
            "mode": "risk_blocked",
            "runtime_state": copy_previous_state_with_flags(
                previous_state,
                {
                    "_control_paused": False,
                    "_policy_disabled": False,
                    "last_error": {
                        "message": "; ".join(risk_policy_result.get("errors") or ["risk-control policy is disabled"]),
                        "at": utc_now_iso(),
                    },
                    "risk_policy_path": risk_policy_result.get("path"),
                },
            ),
            "summary": {
                "scanned_at": utc_now_iso(),
                "policy_enabled": True,
                "scan_count": 0,
                "verified_paper_trade_candidates": 0,
                "legacy_compat_paper_trade_candidates": 0,
                "submitted": 0,
                "blocked": 0,
                "errors": 1,
            },
            "instrument_state": copy_previous_state_with_flags(previous_state).get("instrument_state", {}),
        }

    risk_policy = risk_policy_result.get("policy") or {}
    active_proposals = list_active_order_proposals(limit=250)
    active_by_symbol = {}
    for item in active_proposals:
        symbol = normalize_instrument(item["proposal_record"].get("symbol"))
        active_by_symbol[symbol] = active_by_symbol.get(symbol, 0) + 1

    instruments = [normalize_instrument(item) for item in policy.get("instruments", []) if normalize_instrument(item)]
    scan_result = run_watchlist_scan(
        instruments=instruments,
        category=clean_string(policy.get("category")) or "linear",
        auto_log_candidates=False,
        dedupe_state=None,
        persistent_dedupe=True,
        record_history=coerce_bool(policy.get("record_scan_history")) is not False,
    )

    instrument_state = {}
    summary = {
        "scanned_at": scan_result.get("scanned_at") or utc_now_iso(),
        "policy_enabled": True,
        "scan_count": len(scan_result.get("results") or []),
        "verified_paper_trade_candidates": 0,
        "legacy_compat_paper_trade_candidates": 0,
        "submitted": 0,
        "blocked": 0,
        "errors": 0,
    }

    private_stream_state = private_stream_ready(policy)
    max_active_total = int(policy.get("max_active_proposals_total") or 1)
    max_active_per_symbol = int(policy.get("max_active_proposals_per_symbol") or 1)

    for item in scan_result.get("results") or []:
        instrument = normalize_instrument(item.get("instrument"))
        previous_item = (
            previous_state.get("instrument_state", {}).get(instrument)
            if isinstance(previous_state.get("instrument_state"), dict)
            else None
        )

        if not item.get("ok"):
            summary["errors"] += 1
            instrument_state[instrument] = build_instrument_state(
                instrument,
                item,
                action="scan_failed",
                reason=item.get("error") or "watchlist scan failed",
            )
            continue

        if stable_repeat_action(previous_item, item.get("scan_signature")):
            instrument_state[instrument] = dict(previous_item)
            instrument_state[instrument]["updated_at"] = utc_now_iso()
            continue

        evaluation = item.get("paper_trade_evaluation") or {}
        if not decision_allows_execution_plan(evaluation.get("decision")):
            instrument_state[instrument] = build_instrument_state(
                instrument,
                item,
                action="no_trade",
                reason="watchlist scan did not produce a scanner-verified execution candidate",
            )
            continue

        summary["verified_paper_trade_candidates"] += 1

        intent_result = ensure_execution_intent_for_scan_result(
            item,
            source_path="daemon",
            runtime_key=runtime_key,
        )
        if not intent_result.get("ok"):
            summary["blocked"] += 1
            instrument_state[instrument] = build_instrument_state(
                instrument,
                item,
                action="intent_failed",
                reason=intent_result.get("error") or "execution intent could not be created",
                details={"intent_error": intent_result.get("error")},
            )
            continue
        execution_intent_id = intent_result.get("intent_id")
        intent_record = repositories.execution_intents.get(execution_intent_id)

        risk_result = evaluate_execution_risk(
            store=TradingAPIHandler.store,
            policy=risk_policy,
            scan_result=item,
            intent_record=intent_record,
            runtime_key=runtime_key,
            now_at=summary["scanned_at"],
            control_states={
                "global": resolve_control_state("global"),
                "auto_execution": control,
                "order_submission": resolve_control_state("order_submission"),
            },
            runtime_state={"private_stream": private_stream_state},
        )
        risk_check_id = repositories.execution_risk_checks.create(risk_result)
        if risk_result.get("state") != "allow":
            summary["blocked"] += 1
            instrument_state[instrument] = build_instrument_state(
                instrument,
                item,
                action="risk_blocked",
                reason=risk_result.get("summary") or "risk controls blocked execution advancement",
                details={
                    "execution_intent_id": execution_intent_id,
                    "risk_check_id": risk_check_id,
                    "risk_state": risk_result.get("state"),
                    "risk_blocker_reasons": risk_result.get("blocker_reasons"),
                },
            )
            continue

        if len(active_proposals) >= max_active_total:
            summary["blocked"] += 1
            instrument_state[instrument] = build_instrument_state(
                instrument,
                item,
                action="blocked_max_active_total",
                reason=f"max active proposal limit reached ({len(active_proposals)}/{max_active_total})",
                proposal_id=None,
                details={
                    "active_total": len(active_proposals),
                    "max_active_total": max_active_total,
                    "execution_intent_id": execution_intent_id,
                },
            )
            continue

        if active_by_symbol.get(instrument, 0) >= max_active_per_symbol:
            summary["blocked"] += 1
            instrument_state[instrument] = build_instrument_state(
                instrument,
                item,
                action="blocked_active_symbol",
                reason=(
                    f"active proposal limit reached for {instrument} "
                    f"({active_by_symbol.get(instrument, 0)}/{max_active_per_symbol})"
                ),
                proposal_id=None,
                details={
                    "instrument": instrument,
                    "active_for_symbol": active_by_symbol.get(instrument, 0),
                    "max_active_per_symbol": max_active_per_symbol,
                    "execution_intent_id": execution_intent_id,
                },
            )
            continue

        duplicate_match = find_active_auto_execution_match(instrument, item.get("scan_signature"))
        if duplicate_match is not None:
            summary["blocked"] += 1
            instrument_state[instrument] = build_instrument_state(
                instrument,
                item,
                action="duplicate_active",
                reason="an active auto-execution proposal already exists for this scan signature",
                proposal_id=duplicate_match["proposal_record"].get("proposal_id"),
                details={
                    "matched_proposal_id": duplicate_match["proposal_record"].get("proposal_id"),
                    "execution_intent_id": execution_intent_id,
                },
            )
            continue

        if not private_stream_state["ready"]:
            summary["blocked"] += 1
            instrument_state[instrument] = build_instrument_state(
                instrument,
                item,
                action="blocked_private_stream",
                reason=private_stream_state["reason"],
                details={
                    "private_stream_required": coerce_bool(policy.get("require_private_stream")) is True,
                    "execution_intent_id": execution_intent_id,
                },
            )
            continue

        payload_result = build_auto_execution_payload(item, policy, runtime_key)
        if not payload_result["ok"]:
            summary["blocked"] += 1
            instrument_state[instrument] = build_instrument_state(
                instrument,
                item,
                action="levels_unavailable",
                reason=payload_result["error"],
                details={"payload_error": payload_result["error"], "execution_intent_id": execution_intent_id},
            )
            continue

        auto_evaluation = evaluate_payload(payload_result["payload"])
        journal_id = None
        if coerce_bool(policy.get("auto_log_journal")) is not False:
            journal_id = TradingAPIHandler.store.create_entry(
                payload_result["payload"],
                auto_evaluation,
            )

        proposal = build_bybit_execution_plan(
            raw_payload=payload_result["payload"],
            normalized_payload={},
            evaluation=auto_evaluation,
            journal_id=journal_id,
            created_from="auto_execution",
        )
        if not isinstance(proposal, dict) or proposal.get("status") != "ready_for_submission":
            summary["blocked"] += 1
            instrument_state[instrument] = build_instrument_state(
                instrument,
                item,
                action="plan_review_required",
                reason="execution plan did not reach ready_for_submission",
                details={
                    "proposal_status": proposal.get("status") if isinstance(proposal, dict) else None,
                    "execution_intent_id": execution_intent_id,
                },
            )
            continue

        if risk_policy_needs_order_preview(risk_policy):
            proposal_risk_result = evaluate_execution_risk(
                store=TradingAPIHandler.store,
                policy=risk_policy,
                scan_result=item,
                intent_record=repositories.execution_intents.get(execution_intent_id) or intent_record,
                runtime_key=runtime_key,
                now_at=summary["scanned_at"],
                control_states={
                    "global": resolve_control_state("global"),
                    "auto_execution": control,
                    "order_submission": resolve_control_state("order_submission"),
                },
                runtime_state={"private_stream": private_stream_state},
                order_preview=proposal,
            )
            proposal_risk_check_id = repositories.execution_risk_checks.create(proposal_risk_result)
            if proposal_risk_result.get("state") != "allow":
                summary["blocked"] += 1
                instrument_state[instrument] = build_instrument_state(
                    instrument,
                    item,
                    action="risk_blocked",
                    reason=proposal_risk_result.get("summary") or "risk controls blocked execution advancement",
                    details={
                        "execution_intent_id": execution_intent_id,
                        "risk_check_id": proposal_risk_check_id,
                        "risk_state": proposal_risk_result.get("state"),
                        "risk_blocker_reasons": proposal_risk_result.get("blocker_reasons"),
                    },
                )
                continue

        proposal["automation"] = {
            "runtime_key": runtime_key,
            "execution_intent_id": execution_intent_id,
            "scan_signature": item.get("scan_signature"),
            "policy_path": str((SCRIPT_DIR / "config" / "auto_execution_policy.json").resolve()),
            "entry_model": policy.get("entry_model"),
            "stop_model": policy.get("stop_model"),
            "target_model": policy.get("target_model"),
            "levels": payload_result["levels"],
        }

        proposal_id, proposal_record_copy = TradingAPIHandler.store.create_order_proposal(
            proposal,
            journal_id=journal_id,
            webhook_id=None,
        )
        TradingAPIHandler.store.transition_execution_intent(
            execution_intent_id,
            "execution_plan_created",
            summary="execution plan was created for the verified signal",
            proposal_id=proposal_id,
            details={"source": "auto_execute_loop", "scan_signature": item.get("scan_signature")},
        )
        proposal_record = TradingAPIHandler.store.get_order_proposal(proposal_id)

        if coerce_bool(policy.get("auto_submit")) is not False:
            submit_response = submit_saved_order_proposal_record(proposal_record)
            submission = submit_response.get("submission") or {}
            if submission.get("ok"):
                summary["submitted"] += 1
                active_proposals.append(
                    {
                        "proposal_record": TradingAPIHandler.store.get_order_proposal(proposal_id),
                        "execution_state": TradingAPIHandler.store.get_execution_state(proposal_id),
                    }
                )
                active_by_symbol[instrument] = active_by_symbol.get(instrument, 0) + 1
                instrument_state[instrument] = build_instrument_state(
                    instrument,
                    item,
                    action="submitted_testnet",
                    reason="proposal was auto-submitted to Bybit testnet",
                    proposal_id=proposal_id,
                    details={"submit_response": submit_response, "execution_intent_id": execution_intent_id},
                )
            else:
                summary["blocked"] += 1
                instrument_state[instrument] = build_instrument_state(
                    instrument,
                    item,
                    action="submission_failed",
                    reason=submission.get("error") or submission.get("status") or "proposal submission failed",
                    proposal_id=proposal_id,
                    details={"submit_response": submit_response, "execution_intent_id": execution_intent_id},
                )
        else:
            active_proposals.append(
                {
                    "proposal_record": proposal_record,
                    "execution_state": TradingAPIHandler.store.get_execution_state(proposal_id),
                }
            )
            active_by_symbol[instrument] = active_by_symbol.get(instrument, 0) + 1
            instrument_state[instrument] = build_instrument_state(
                instrument,
                item,
                action="proposal_created",
                reason="proposal was created but auto submission is disabled in policy",
                proposal_id=proposal_id,
                details={"execution_intent_id": execution_intent_id},
            )

    runtime_state = {
        "instrument_state": instrument_state,
        "last_scan_at": summary["scanned_at"],
        "last_error": None,
        "_control_paused": False,
        "_policy_disabled": False,
        "policy_path": str((SCRIPT_DIR / "config" / "auto_execution_policy.json").resolve()),
        "policy_enabled": True,
    }

    return {
        "mode": "active",
        "runtime_state": runtime_state,
        "summary": summary,
        "instrument_state": instrument_state,
    }


def main():
    args = parse_args()
    runtime_key = (args.runtime_key or "").strip() or "default"
    previous_state, previous_runtime = load_runtime_state(runtime_key)

    startup_event = create_runtime_start_event(runtime_key, previous_runtime)
    if not args.disable_events:
        event_id = persist_events([startup_event])[0]
        startup_event["event_id"] = event_id
    print(format_event_line(startup_event))

    policy_disabled_announced = bool(previous_state.get("_policy_disabled")) if isinstance(previous_state, dict) else False
    control_paused = bool(previous_state.get("_control_paused")) if isinstance(previous_state, dict) else False

    while True:
        started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        policy_result = load_auto_execution_policy()
        if not policy_result["ok"]:
            error_state = copy_previous_state_with_flags(
                previous_state,
                {
                    "last_error": {
                        "message": "; ".join(policy_result["errors"]),
                        "at": started_at,
                    },
                    "_control_paused": False,
                    "_policy_disabled": False,
                    "policy_path": policy_result["path"],
                },
            )
            persist_runtime(
                runtime_key,
                error_state,
                {
                    "scanned_at": started_at,
                    "policy_enabled": False,
                    "scan_count": 0,
                    "verified_paper_trade_candidates": 0,
                    "legacy_compat_paper_trade_candidates": 0,
                    "submitted": 0,
                    "blocked": 0,
                    "errors": 1,
                },
            )
            error_event = build_event(
                runtime_key=runtime_key,
                event_type="policy_error",
                severity="error",
                summary="auto-execution policy could not be loaded",
                payload={"errors": policy_result["errors"], "path": policy_result["path"]},
            )
            if not args.disable_events:
                event_id = persist_events([error_event])[0]
                error_event["event_id"] = event_id
            print(format_event_line(error_event))
            previous_state = error_state
            if args.once:
                break
            time.sleep(max(5, args.interval_seconds))
            continue

        try:
            cycle_result = run_cycle(runtime_key, previous_state, policy_result["policy"])
            runtime_state = cycle_result["runtime_state"]
            summary = cycle_result["summary"]
            persist_runtime(runtime_key, runtime_state, build_runtime_summary(summary))

            events = []
            if cycle_result["mode"] == "paused":
                if not control_paused:
                    events.append(
                        build_event(
                            runtime_key=runtime_key,
                            event_type="control_paused",
                            severity="warning",
                            summary=cycle_result["control"]["effective_reason"]
                            or "auto execution paused by control state",
                            payload={"control": cycle_result["control"]},
                        )
                    )
                control_paused = True
                policy_disabled_announced = False
                previous_state = runtime_state
                if not args.disable_events and events:
                    event_ids = persist_events(events)
                    for event, event_id in zip(events, event_ids):
                        event["event_id"] = event_id
                for event in events:
                    print(format_event_line(event))
                print(f"[{started_at}] auto execution paused")
                if args.once:
                    break
                time.sleep(max(5, args.interval_seconds))
                continue

            if control_paused:
                events.append(
                    build_event(
                        runtime_key=runtime_key,
                        event_type="control_resumed",
                        severity="info",
                        summary="auto execution resumed after control pause",
                        payload={},
                    )
                )
                control_paused = False

            if cycle_result["mode"] == "disabled":
                if not policy_disabled_announced:
                    events.append(
                        build_event(
                            runtime_key=runtime_key,
                            event_type="policy_disabled",
                            severity="info",
                            summary="auto execution policy is disabled",
                            payload={"policy_enabled": False},
                        )
                    )
                policy_disabled_announced = True
                previous_state = runtime_state
                if not args.disable_events and events:
                    event_ids = persist_events(events)
                    for event, event_id in zip(events, event_ids):
                        event["event_id"] = event_id
                for event in events:
                    print(format_event_line(event))
                print(f"[{started_at}] auto execution disabled by policy")
                if args.once:
                    break
                time.sleep(max(5, args.interval_seconds))
                continue

            if policy_disabled_announced:
                events.append(
                    build_event(
                        runtime_key=runtime_key,
                        event_type="policy_enabled",
                        severity="info",
                        summary="auto execution policy is enabled",
                        payload={"policy_enabled": True},
                    )
                )
                policy_disabled_announced = False

            transition_events = build_transition_events(runtime_key, previous_state, runtime_state)
            events.extend(transition_events)
            if not args.disable_events and events:
                event_ids = persist_events(events)
                for event, event_id in zip(events, event_ids):
                    event["event_id"] = event_id

            print(
                f"[{started_at}] auto execution scanned={summary['scan_count']} "
                f"verified_candidates={summary['verified_paper_trade_candidates']} submitted={summary['submitted']} "
                f"blocked={summary['blocked']} errors={summary['errors']}"
            )
            for item in runtime_state.get("instrument_state", {}).values():
                print(format_state_line(item))
            for event in events:
                print(format_event_line(event))

            previous_state = runtime_state
        except Exception as exc:
            error_message = str(exc)
            error_state = copy_previous_state_with_flags(
                previous_state,
                {
                    "last_error": {
                        "message": error_message,
                        "at": started_at,
                    },
                    "policy_path": policy_result["path"],
                },
            )
            persist_runtime(
                runtime_key,
                error_state,
                {
                    "scanned_at": started_at,
                    "policy_enabled": coerce_bool(
                        policy_result["policy"].get("enabled")
                        if isinstance(policy_result.get("policy"), dict)
                        else None
                    )
                    is True,
                    "scan_count": 0,
                    "verified_paper_trade_candidates": 0,
                    "legacy_compat_paper_trade_candidates": 0,
                    "submitted": 0,
                    "blocked": 0,
                    "errors": 1,
                },
            )
            error_event = build_event(
                runtime_key=runtime_key,
                event_type="cycle_exception",
                severity="error",
                summary=f"auto execution cycle failed: {error_message}",
                payload={"error": error_message, "at": started_at},
            )
            if not args.disable_events:
                event_id = persist_events([error_event])[0]
                error_event["event_id"] = event_id
            print(format_event_line(error_event), file=sys.stderr)
            previous_state = error_state
            if args.once:
                raise

        if args.once:
            break
        time.sleep(max(5, args.interval_seconds))


if __name__ == "__main__":
    main()
