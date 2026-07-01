#!/usr/bin/env python3

import argparse
import sys
import time
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from runtime_api import (
    OPERATIONS_DEFAULT_THRESHOLDS,
    TradingAPIHandler,
    age_seconds_from_iso,
    clean_string,
    coerce_bool,
    execute_cancel_order_action,
    execute_refresh_trading_stop_action,
    fetch_bybit_ticker,
    first_present,
    list_active_order_proposals,
    load_trade_management_policy,
    normalize_instrument,
    resolve_control_state,
    resolve_supervisor_lifecycle,
    round_to_increment,
    to_decimal,
    utc_now_iso,
)


TRACKED_FIELDS = (
    "lifecycle",
    "proposal_status",
    "last_action",
    "reason",
    "working_age_seconds",
    "rr_now",
    "managed_stop",
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run Wave 2 guarded testnet trade management."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single trade-management cycle and exit.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=30,
        help="Seconds to wait between trade-management cycles. Default: 30.",
    )
    parser.add_argument(
        "--runtime-key",
        default="default",
        help="Trade-management runtime key used for restart-safe state and event persistence. Default: default.",
    )
    parser.add_argument(
        "--disable-events",
        action="store_true",
        help="Do not persist trade-management events to SQLite.",
    )
    return parser.parse_args()


def format_event_line(event):
    symbol = event.get("symbol") or "-"
    proposal_id = event.get("proposal_id") or "-"
    return (
        f"EVENT {event.get('severity', 'info').upper()} "
        f"{event.get('event_type', 'unknown')} | {symbol} | {proposal_id} | {event.get('summary', '')}"
    )


def format_state_line(state):
    return (
        f"{state.get('proposal_id', 'unknown')} | "
        f"{state.get('symbol', 'unknown')} | "
        f"lifecycle={state.get('lifecycle', 'unknown')} | "
        f"action={state.get('last_action', 'unknown')} | "
        f"{state.get('reason', '')}"
    )


def build_event(runtime_key, event_type, severity, summary, payload, proposal_id=None, symbol=None):
    return {
        "runtime_key": runtime_key,
        "event_type": event_type,
        "severity": severity,
        "summary": summary,
        "proposal_id": clean_string(proposal_id),
        "symbol": normalize_instrument(symbol) or None,
        "payload": payload if isinstance(payload, dict) else {},
    }


def persist_events(events):
    event_ids = []
    for event in events:
        event_id = TradingAPIHandler.store.create_trade_management_event(
            runtime_key=event["runtime_key"],
            event_type=event["event_type"],
            severity=event["severity"],
            summary=event["summary"],
            event_payload=event["payload"],
            proposal_id=event.get("proposal_id"),
            symbol=event.get("symbol"),
        )
        event_ids.append(event_id)
    return event_ids


def load_runtime_state(runtime_key):
    record = TradingAPIHandler.store.get_trade_management_runtime(runtime_key)
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
            summary=f"trade management runtime {runtime_key} started with no previous state",
            payload={"runtime_key": runtime_key},
        )

    return build_event(
        runtime_key=runtime_key,
        event_type="runtime_resumed",
        severity="info",
        summary=f"trade management runtime {runtime_key} resumed from stored state",
        payload={
            "runtime_key": runtime_key,
            "previous_updated_at": previous_runtime.get("updated_at"),
            "previous_heartbeat_at": previous_runtime.get("heartbeat_at"),
            "previous_last_scan_at": previous_runtime.get("last_scan_at"),
        },
    )


def persist_runtime(runtime_key, runtime_state, last_summary):
    TradingAPIHandler.store.upsert_trade_management_runtime(
        runtime_key=runtime_key,
        state=runtime_state,
        last_summary=last_summary,
    )


def build_runtime_summary(summary):
    return {
        "scanned_at": summary.get("scanned_at"),
        "policy_enabled": summary.get("policy_enabled"),
        "active_proposals": summary.get("active_proposals", 0),
        "actions_attempted": summary.get("actions_attempted", 0),
        "actions_applied": summary.get("actions_applied", 0),
        "blocked": summary.get("blocked", 0),
        "errors": summary.get("errors", 0),
    }


def copy_previous_state_with_flags(previous_state, extra=None):
    state = {
        "proposal_state": (
            previous_state.get("proposal_state")
            if isinstance(previous_state.get("proposal_state"), dict)
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
        return {"ready": False, "reason": control["effective_reason"] or "private stream is paused"}

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
    return {"ready": False, "reason": "private stream is not healthy enough for trade management"}


def decimal_to_float(value, places=4):
    if value is None:
        return None
    return round(float(value), places)


def safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def proposal_context(proposal_record, execution_state, policy):
    proposal = proposal_record.get("proposal") if isinstance(proposal_record.get("proposal"), dict) else {}
    request = proposal.get("request") if isinstance(proposal.get("request"), dict) else {}
    sizing = proposal.get("sizing") if isinstance(proposal.get("sizing"), dict) else {}
    instrument_constraints = (
        proposal.get("instrument_constraints")
        if isinstance(proposal.get("instrument_constraints"), dict)
        else {}
    )
    snapshot = execution_state.get("snapshot") if isinstance(execution_state, dict) else {}
    order = snapshot.get("order") if isinstance(snapshot.get("order"), dict) else {}
    position = snapshot.get("position") if isinstance(snapshot.get("position"), dict) else {}
    lifecycle, _ = resolve_supervisor_lifecycle(proposal_record, execution_state, None)

    symbol = normalize_instrument(proposal_record.get("symbol") or proposal.get("symbol"))
    category = clean_string(first_present(request, ["category"])) or "linear"
    side = clean_string(proposal.get("side"))
    submitted_at = clean_string(
        first_present(
            proposal_record.get("submit_response") if isinstance(proposal_record.get("submit_response"), dict) else {},
            ["submitted_at"],
        )
    ) or clean_string(proposal_record.get("created_at"))
    working_age_seconds = age_seconds_from_iso(submitted_at)

    entry_price = (
        to_decimal(first_present(position, ["avgPrice", "avg_price"]))
        or to_decimal(first_present(sizing, ["entry_reference_price"]))
        or to_decimal(first_present(request, ["price"]))
    )
    current_stop = (
        to_decimal(first_present(position, ["stopLoss", "stop_loss"]))
        or to_decimal(first_present(order, ["stopLoss", "stop_loss"]))
        or to_decimal(first_present(request, ["stopLoss", "stop_loss"]))
    )
    initial_stop = to_decimal(first_present(request, ["stopLoss", "stop_loss"]))
    take_profit = (
        to_decimal(first_present(position, ["takeProfit", "take_profit"]))
        or to_decimal(first_present(request, ["takeProfit", "take_profit"]))
    )
    current_price = (
        to_decimal(first_present(position, ["markPrice", "mark_price", "lastPrice", "last_price"]))
        or to_decimal(first_present(order, ["lastPrice", "price"]))
    )
    if current_price is None and symbol:
        ticker_result = fetch_bybit_ticker(symbol, category=category)
        if ticker_result.get("ok"):
            ticker = ticker_result.get("ticker") or {}
            current_price = to_decimal(first_present(ticker, ["markPrice", "lastPrice", "indexPrice"]))

    tick_size = to_decimal(first_present(instrument_constraints, ["tick_size"]))
    buffer_ticks = safe_int(
        first_present(
            policy.get("open_positions", {}).get("break_even")
            if isinstance(policy.get("open_positions"), dict)
            else {},
            ["buffer_ticks"],
        )
    ) or 0
    buffer = tick_size * buffer_ticks if tick_size is not None else None

    risk_distance = None
    rr_now = None
    break_even_stop = None
    if entry_price is not None and initial_stop is not None:
        risk_distance = abs(entry_price - initial_stop)
        if side == "Buy":
            break_even_stop = entry_price + (buffer or 0)
        elif side == "Sell":
            break_even_stop = entry_price - (buffer or 0)
        if break_even_stop is not None and tick_size is not None:
            break_even_stop = round_to_increment(break_even_stop, tick_size, ROUND_HALF_UP)

    if entry_price is not None and current_price is not None and risk_distance and risk_distance > 0:
        favorable_move = current_price - entry_price if side == "Buy" else entry_price - current_price
        rr_now = favorable_move / risk_distance

    return {
        "proposal": proposal,
        "request": request,
        "snapshot": snapshot,
        "order": order,
        "position": position,
        "proposal_status": clean_string(proposal_record.get("status")) or "unknown",
        "proposal_id": proposal_record.get("proposal_id"),
        "symbol": symbol,
        "category": category,
        "side": side,
        "lifecycle": lifecycle,
        "submitted_at": submitted_at,
        "working_age_seconds": working_age_seconds,
        "entry_price": entry_price,
        "initial_stop": initial_stop,
        "current_stop": current_stop,
        "take_profit": take_profit,
        "current_price": current_price,
        "risk_distance": risk_distance,
        "rr_now": rr_now,
        "break_even_stop": break_even_stop,
        "tick_size": tick_size,
    }


def stop_is_protective(side, current_stop, break_even_stop):
    if side == "Buy":
        return current_stop is not None and break_even_stop is not None and current_stop >= break_even_stop
    if side == "Sell":
        return current_stop is not None and break_even_stop is not None and current_stop <= break_even_stop
    return False


def build_proposal_state(context, action, reason, details=None):
    return {
        "proposal_id": context.get("proposal_id"),
        "symbol": context.get("symbol"),
        "proposal_status": context.get("proposal_status"),
        "lifecycle": context.get("lifecycle"),
        "last_action": action,
        "reason": reason,
        "working_age_seconds": (
            round(context.get("working_age_seconds"), 1)
            if context.get("working_age_seconds") is not None
            else None
        ),
        "rr_now": decimal_to_float(context.get("rr_now")),
        "managed_stop": decimal_to_float(context.get("current_stop")),
        "updated_at": utc_now_iso(),
        "details": details if isinstance(details, dict) else {},
    }


def build_transition_events(runtime_key, previous_state, current_state):
    previous_map = (
        previous_state.get("proposal_state")
        if isinstance(previous_state.get("proposal_state"), dict)
        else {}
    )
    current_map = (
        current_state.get("proposal_state")
        if isinstance(current_state.get("proposal_state"), dict)
        else {}
    )
    events = []

    for proposal_id, state in current_map.items():
        previous_item = previous_map.get(proposal_id)
        if previous_item is None:
            if state.get("last_action") not in {"monitor", "await_submission"}:
                events.append(
                    build_event(
                        runtime_key=runtime_key,
                        event_type=state.get("last_action") or "proposal_detected",
                        severity="warning"
                        if state.get("last_action") in {"action_failed", "blocked"}
                        else "info",
                        summary=state.get("reason") or f"{proposal_id} changed state",
                        payload={"current": state},
                        proposal_id=proposal_id,
                        symbol=state.get("symbol"),
                    )
                )
            continue

        changes = {}
        for field in TRACKED_FIELDS:
            if previous_item.get(field) != state.get(field):
                changes[field] = {
                    "from": previous_item.get(field),
                    "to": state.get(field),
                }
        if not changes:
            continue
        action = state.get("last_action") or "state_changed"
        events.append(
            build_event(
                runtime_key=runtime_key,
                event_type=action,
                severity="warning" if action in {"action_failed", "blocked"} else "info",
                summary=state.get("reason") or f"{proposal_id} changed state",
                payload={"previous": previous_item, "current": state, "changes": changes},
                proposal_id=proposal_id,
                symbol=state.get("symbol"),
            )
        )

    return events


def should_skip_for_cooldown(previous_item, cooldown_seconds):
    if not isinstance(previous_item, dict) or cooldown_seconds <= 0:
        return False
    last_action_at = clean_string(previous_item.get("updated_at"))
    age_seconds = age_seconds_from_iso(last_action_at)
    if age_seconds is None:
        return False
    last_action = clean_string(previous_item.get("last_action")) or ""
    return last_action in {
        "cancelled_stale_order",
        "moved_stop_to_break_even",
        "action_failed",
    } and age_seconds < cooldown_seconds


def run_cycle(runtime_key, previous_state, policy):
    control = resolve_control_state("trade_management")
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
                "active_proposals": 0,
                "actions_attempted": 0,
                "actions_applied": 0,
                "blocked": 0,
                "errors": 0,
            },
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
                "active_proposals": 0,
                "actions_attempted": 0,
                "actions_applied": 0,
                "blocked": 0,
                "errors": 0,
            },
        }

    stream_state = private_stream_ready(policy)
    proposals = list_active_order_proposals(limit=250)
    proposal_state = {}
    summary = {
        "scanned_at": utc_now_iso(),
        "policy_enabled": True,
        "active_proposals": len(proposals),
        "actions_attempted": 0,
        "actions_applied": 0,
        "blocked": 0,
        "errors": 0,
    }
    max_actions = max(1, safe_int(policy.get("max_actions_per_cycle")) or 1)
    cooldown_seconds = max(0, safe_int(policy.get("cooldown_seconds_per_proposal")) or 0)
    working_policy = policy.get("working_orders") if isinstance(policy.get("working_orders"), dict) else {}
    open_positions = policy.get("open_positions") if isinstance(policy.get("open_positions"), dict) else {}
    break_even_policy = open_positions.get("break_even") if isinstance(open_positions.get("break_even"), dict) else {}
    actions_used = 0

    for item in proposals:
        proposal_record = item.get("proposal_record")
        if not isinstance(proposal_record, dict):
            continue
        proposal_id = proposal_record.get("proposal_id")
        execution_state = TradingAPIHandler.store.get_execution_state(proposal_id) or item.get("execution_state")
        context = proposal_context(proposal_record, execution_state, policy)
        previous_item = (
            previous_state.get("proposal_state", {}).get(proposal_id)
            if isinstance(previous_state.get("proposal_state"), dict)
            else None
        )

        if not stream_state["ready"]:
            summary["blocked"] += 1
            proposal_state[proposal_id] = build_proposal_state(
                context,
                action="blocked",
                reason=stream_state["reason"],
            )
            continue

        if should_skip_for_cooldown(previous_item, cooldown_seconds):
            proposal_state[proposal_id] = dict(previous_item)
            proposal_state[proposal_id]["updated_at"] = utc_now_iso()
            continue

        if actions_used >= max_actions:
            proposal_state[proposal_id] = build_proposal_state(
                context,
                action="deferred",
                reason="trade-management action limit reached for this cycle",
            )
            continue

        lifecycle = context.get("lifecycle")
        if lifecycle == "working" and coerce_bool(working_policy.get("auto_cancel_stale")) is True:
            stale_after_seconds = max(1, safe_int(working_policy.get("stale_after_seconds")) or 1)
            if (
                context.get("working_age_seconds") is not None
                and context.get("working_age_seconds") >= stale_after_seconds
            ):
                summary["actions_attempted"] += 1
                actions_used += 1
                action_result = execute_cancel_order_action(proposal_record)
                if action_result.get("ok"):
                    summary["actions_applied"] += 1
                    proposal_state[proposal_id] = build_proposal_state(
                        context,
                        action="cancelled_stale_order",
                        reason=f"working order exceeded stale threshold of {stale_after_seconds} seconds",
                        details={"execution_action": action_result},
                    )
                else:
                    summary["errors"] += 1
                    proposal_state[proposal_id] = build_proposal_state(
                        context,
                        action="action_failed",
                        reason=action_result.get("error") or "failed to cancel stale working order",
                        details={"execution_action": action_result},
                    )
                continue
            proposal_state[proposal_id] = build_proposal_state(
                context,
                action="monitor",
                reason="working order remains inside the stale-order threshold",
            )
            continue

        if lifecycle == "position_open" and coerce_bool(break_even_policy.get("enabled")) is True:
            trigger_rr = safe_int(None)
            try:
                trigger_rr = float(break_even_policy.get("trigger_rr"))
            except (TypeError, ValueError):
                trigger_rr = None
            if context.get("entry_price") is None or context.get("initial_stop") is None:
                summary["blocked"] += 1
                proposal_state[proposal_id] = build_proposal_state(
                    context,
                    action="blocked",
                    reason="break-even management needs entry and initial stop from the saved proposal",
                )
                continue
            if context.get("current_price") is None or context.get("rr_now") is None:
                summary["blocked"] += 1
                proposal_state[proposal_id] = build_proposal_state(
                    context,
                    action="blocked",
                    reason="break-even management needs a usable current market price",
                )
                continue
            if trigger_rr is None or context.get("rr_now") < trigger_rr:
                proposal_state[proposal_id] = build_proposal_state(
                    context,
                    action="monitor",
                    reason="open position has not reached the break-even RR trigger yet",
                )
                continue
            if stop_is_protective(context.get("side"), context.get("current_stop"), context.get("break_even_stop")):
                proposal_state[proposal_id] = build_proposal_state(
                    context,
                    action="already_protected",
                    reason="current stop is already at or beyond the break-even protection level",
                )
                continue

            refresh_payload = {
                "stop_loss": decimal_to_float(context.get("break_even_stop")),
            }
            if context.get("take_profit") is not None:
                refresh_payload["take_profit"] = decimal_to_float(context.get("take_profit"))

            summary["actions_attempted"] += 1
            actions_used += 1
            action_result = execute_refresh_trading_stop_action(proposal_record, refresh_payload)
            if action_result.get("ok"):
                summary["actions_applied"] += 1
                proposal_state[proposal_id] = build_proposal_state(
                    context,
                    action="moved_stop_to_break_even",
                    reason=f"open position reached {trigger_rr}R and stop was refreshed to break-even",
                    details={"execution_action": action_result, "refresh_payload": refresh_payload},
                )
            else:
                summary["errors"] += 1
                proposal_state[proposal_id] = build_proposal_state(
                    context,
                    action="action_failed",
                    reason=action_result.get("error") or "failed to refresh stop to break-even",
                    details={"execution_action": action_result, "refresh_payload": refresh_payload},
                )
            continue

        passive_reason = {
            "planned": "proposal is not submitted yet; trade management is waiting",
            "submitted": "proposal is waiting for exchange state to settle",
            "partially_filled": "partial fill needs monitoring but no automatic action is configured yet",
            "filled": "filled state needs a position/open check before management acts",
            "cancelled": "proposal is already terminal",
            "rejected": "proposal is already terminal",
            "unknown": "proposal lifecycle is ambiguous and needs supervision",
        }.get(lifecycle, "trade management is monitoring this proposal")
        proposal_state[proposal_id] = build_proposal_state(
            context,
            action="monitor" if lifecycle != "planned" else "await_submission",
            reason=passive_reason,
        )

    runtime_state = {
        "proposal_state": proposal_state,
        "last_scan_at": summary["scanned_at"],
        "last_error": None,
        "_control_paused": False,
        "_policy_disabled": False,
        "policy_path": str((SCRIPT_DIR / "config" / "trade_management_policy.json").resolve()),
        "policy_enabled": True,
    }
    return {
        "mode": "active",
        "runtime_state": runtime_state,
        "summary": summary,
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
        policy_result = load_trade_management_policy()
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
                    "active_proposals": 0,
                    "actions_attempted": 0,
                    "actions_applied": 0,
                    "blocked": 0,
                    "errors": 1,
                },
            )
            error_event = build_event(
                runtime_key=runtime_key,
                event_type="policy_error",
                severity="error",
                summary="trade-management policy could not be loaded",
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
                            or "trade management paused by control state",
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
                print(f"[{started_at}] trade management paused")
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
                        summary="trade management resumed after control pause",
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
                            summary="trade management policy is disabled",
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
                print(f"[{started_at}] trade management disabled by policy")
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
                        summary="trade management policy is enabled",
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
                f"[{started_at}] trade management active={summary['active_proposals']} "
                f"attempted={summary['actions_attempted']} applied={summary['actions_applied']} "
                f"blocked={summary['blocked']} errors={summary['errors']}"
            )
            for item in runtime_state.get("proposal_state", {}).values():
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
                    "active_proposals": 0,
                    "actions_attempted": 0,
                    "actions_applied": 0,
                    "blocked": 0,
                    "errors": 1,
                },
            )
            error_event = build_event(
                runtime_key=runtime_key,
                event_type="cycle_exception",
                severity="error",
                summary=f"trade management cycle failed: {error_message}",
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
