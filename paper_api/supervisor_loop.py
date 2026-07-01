#!/usr/bin/env python3

import argparse
import sys
import time
from datetime import datetime, timezone

from runtime_api import TradingAPIHandler, resolve_control_state, run_supervisor_scan


TRACKED_FIELDS = (
    "proposal_status",
    "sync_status",
    "recommendation_status",
    "next_action",
    "order_status",
    "position_size",
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run repeated supervision scans for active Bybit testnet proposals."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single supervisor scan and exit.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=60,
        help="Seconds to wait between supervisor scans. Default: 60.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Maximum number of recent proposals to inspect per scan. Default: 25.",
    )
    parser.add_argument(
        "--disable-sync",
        action="store_true",
        help="Inspect active proposals without syncing exchange state.",
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include recent inactive proposals in the output.",
    )
    parser.add_argument(
        "--runtime-key",
        default="default",
        help="Supervisor runtime key used for restart-safe state and event persistence. Default: default.",
    )
    parser.add_argument(
        "--disable-events",
        action="store_true",
        help="Do not persist supervisor events to SQLite.",
    )
    return parser.parse_args()


def format_supervisor_line(item):
    recommendation = item.get("recommendation") or {}
    parts = [
        item.get("proposal_id", "unknown"),
        item.get("symbol", "unknown"),
        f"proposal={item.get('proposal_status', 'unknown')}",
        f"sync={item.get('sync_status', 'untracked')}",
        f"next={recommendation.get('next_action', 'manual_review')}",
    ]

    if item.get("position_size"):
        parts.append(f"size={item['position_size']}")
    if item.get("unrealised_pnl"):
        parts.append(f"upl={item['unrealised_pnl']}")
    if item.get("sync_attempted"):
        sync_result = item.get("sync_result") or {}
        parts.append(f"sync_result={sync_result.get('status', 'unknown')}")

    return " | ".join(parts)


def format_event_line(event):
    proposal_id = event.get("proposal_id") or "-"
    symbol = event.get("symbol") or "-"
    return (
        f"EVENT {event.get('severity', 'info').upper()} "
        f"{event.get('event_type', 'unknown')} | {proposal_id} | {symbol} | {event.get('summary', '')}"
    )


def compact_item_state(item):
    recommendation = item.get("recommendation") if isinstance(item.get("recommendation"), dict) else {}
    sync_result = item.get("sync_result") if isinstance(item.get("sync_result"), dict) else {}
    sync_error = None
    if sync_result and not sync_result.get("ok"):
        sync_error = sync_result.get("error") or sync_result.get("status") or "sync_failed"

    return {
        "proposal_id": item.get("proposal_id"),
        "symbol": item.get("symbol"),
        "side": item.get("side"),
        "proposal_status": item.get("proposal_status"),
        "sync_status": item.get("sync_status"),
        "order_status": item.get("order_status"),
        "position_size": item.get("position_size"),
        "unrealised_pnl": item.get("unrealised_pnl"),
        "recommendation_status": recommendation.get("status"),
        "next_action": recommendation.get("next_action"),
        "updated_at": item.get("updated_at"),
        "last_sync_error": sync_error,
    }


def build_runtime_summary(result):
    return {
        "scanned_at": result.get("scanned_at"),
        "scan_mode": result.get("scan_mode"),
        "summary": result.get("summary") or {},
        "item_count": len(result.get("items") or []),
    }


def load_runtime_state(runtime_key):
    record = TradingAPIHandler.store.get_supervisor_runtime(runtime_key)
    if record is None:
        return {}, None
    state = record.get("state") if isinstance(record.get("state"), dict) else {}
    return state, record


def build_event(runtime_key, event_type, severity, summary, payload, proposal_id=None, symbol=None):
    return {
        "runtime_key": runtime_key,
        "event_type": event_type,
        "severity": severity,
        "summary": summary,
        "proposal_id": proposal_id,
        "symbol": symbol,
        "payload": payload if isinstance(payload, dict) else {},
    }


def create_runtime_start_event(runtime_key, previous_runtime):
    if previous_runtime is None:
        return build_event(
            runtime_key=runtime_key,
            event_type="runtime_started",
            severity="info",
            summary=f"supervisor runtime {runtime_key} started with no previous state",
            payload={"runtime_key": runtime_key},
        )

    return build_event(
        runtime_key=runtime_key,
        event_type="runtime_resumed",
        severity="info",
        summary=f"supervisor runtime {runtime_key} resumed from stored state",
        payload={
            "runtime_key": runtime_key,
            "previous_updated_at": previous_runtime.get("updated_at"),
            "previous_heartbeat_at": previous_runtime.get("heartbeat_at"),
            "previous_last_scan_at": previous_runtime.get("last_scan_at"),
        },
    )


def determine_change_severity(state):
    if state.get("last_sync_error"):
        return "warning"
    if state.get("recommendation_status") == "manual_review":
        return "warning"
    if state.get("sync_status") in {"rejected"}:
        return "warning"
    return "info"


def build_cycle_events(runtime_key, previous_state, result):
    previous_map = (
        previous_state.get("proposal_state")
        if isinstance(previous_state.get("proposal_state"), dict)
        else {}
    )
    current_map = {}
    events = []

    for item in result.get("items") or []:
        proposal_id = item.get("proposal_id")
        if not proposal_id:
            continue

        state = compact_item_state(item)
        current_map[proposal_id] = state
        previous_item = previous_map.get(proposal_id)

        if previous_item is None:
            events.append(
                build_event(
                    runtime_key=runtime_key,
                    event_type="proposal_detected",
                    severity=determine_change_severity(state),
                    summary=(
                        f"{proposal_id} {state.get('symbol') or 'unknown'} became active with "
                        f"next action {state.get('next_action') or 'manual_review'}"
                    ),
                    payload={"current": state},
                    proposal_id=proposal_id,
                    symbol=state.get("symbol"),
                )
            )
        else:
            changes = {}
            for field in TRACKED_FIELDS:
                if previous_item.get(field) != state.get(field):
                    changes[field] = {
                        "from": previous_item.get(field),
                        "to": state.get(field),
                    }
            if changes:
                events.append(
                    build_event(
                        runtime_key=runtime_key,
                        event_type="lifecycle_changed",
                        severity=determine_change_severity(state),
                        summary=(
                            f"{proposal_id} {state.get('symbol') or 'unknown'} changed to "
                            f"sync={state.get('sync_status') or 'unknown'} "
                            f"next={state.get('next_action') or 'manual_review'}"
                        ),
                        payload={"previous": previous_item, "current": state, "changes": changes},
                        proposal_id=proposal_id,
                        symbol=state.get("symbol"),
                    )
                )

            if state.get("last_sync_error") and state.get("last_sync_error") != previous_item.get(
                "last_sync_error"
            ):
                events.append(
                    build_event(
                        runtime_key=runtime_key,
                        event_type="sync_failed",
                        severity="warning",
                        summary=(
                            f"{proposal_id} {state.get('symbol') or 'unknown'} sync failed: "
                            f"{state.get('last_sync_error')}"
                        ),
                        payload={"previous": previous_item, "current": state},
                        proposal_id=proposal_id,
                        symbol=state.get("symbol"),
                    )
                )

    for proposal_id, previous_item in previous_map.items():
        if proposal_id in current_map:
            continue
        events.append(
            build_event(
                runtime_key=runtime_key,
                event_type="proposal_inactive",
                severity="info",
                summary=f"{proposal_id} {previous_item.get('symbol') or 'unknown'} is no longer active",
                payload={"previous": previous_item},
                proposal_id=proposal_id,
                symbol=previous_item.get("symbol"),
            )
        )

    runtime_state = {
        "proposal_state": current_map,
        "last_scan_at": result.get("scanned_at"),
        "last_summary": build_runtime_summary(result),
        "last_error": None,
        "_control_paused": False,
    }
    return events, runtime_state


def persist_runtime(runtime_key, runtime_state, last_summary):
    TradingAPIHandler.store.upsert_supervisor_runtime(
        runtime_key=runtime_key,
        state=runtime_state,
        last_summary=last_summary,
    )


def persist_events(events):
    event_ids = []
    for event in events:
        event_id = TradingAPIHandler.store.create_supervisor_event(
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


def main():
    args = parse_args()
    runtime_key = args.runtime_key.strip() or "default"
    previous_state, previous_runtime = load_runtime_state(runtime_key)
    control_paused = bool(previous_state.get("_control_paused")) if isinstance(previous_state, dict) else False

    startup_event = create_runtime_start_event(runtime_key, previous_runtime)
    if not args.disable_events:
        event_id = persist_events([startup_event])[0]
        startup_event["event_id"] = event_id
    print(format_event_line(startup_event))

    while True:
        started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        control = resolve_control_state("supervisor")
        if control["effective_paused"]:
            paused_state = {
                "proposal_state": (
                    previous_state.get("proposal_state")
                    if isinstance(previous_state.get("proposal_state"), dict)
                    else {}
                ),
                "last_scan_at": previous_state.get("last_scan_at"),
                "last_summary": previous_state.get("last_summary") if isinstance(previous_state, dict) else {},
                "last_error": None,
                "_control_paused": True,
                "control": control,
            }
            persist_runtime(
                runtime_key,
                paused_state,
                {
                    "scanned_at": started_at,
                    "scan_mode": "supervisor",
                    "summary": {
                        "paused": True,
                        "reason": control["effective_reason"],
                    },
                    "item_count": 0,
                },
            )
            if not control_paused:
                pause_event = build_event(
                    runtime_key=runtime_key,
                    event_type="control_paused",
                    severity="warning",
                    summary=f"supervisor runtime paused: {control['effective_reason'] or 'paused by control state'}",
                    payload={"control": control},
                )
                if not args.disable_events:
                    event_id = persist_events([pause_event])[0]
                    pause_event["event_id"] = event_id
                print(format_event_line(pause_event))
            control_paused = True
            previous_state = paused_state
            print(f"[{started_at}] supervisor paused: {control['effective_reason'] or 'paused by control state'}")
            if args.once:
                break
            time.sleep(max(10, args.interval_seconds))
            continue
        elif control_paused:
            resume_event = build_event(
                runtime_key=runtime_key,
                event_type="control_resumed",
                severity="info",
                summary="supervisor runtime resumed after control pause",
                payload={"control": control},
            )
            if not args.disable_events:
                event_id = persist_events([resume_event])[0]
                resume_event["event_id"] = event_id
            print(format_event_line(resume_event))
            control_paused = False

        try:
            result = run_supervisor_scan(
                limit=max(1, min(200, args.limit)),
                sync_active=not args.disable_sync,
                include_inactive=args.include_inactive,
            )
            summary = result["summary"]
            runtime_events, runtime_state = build_cycle_events(runtime_key, previous_state, result)
            summary_payload = build_runtime_summary(result)
            persist_runtime(runtime_key, runtime_state, summary_payload)

            event_ids = []
            if not args.disable_events and runtime_events:
                event_ids = persist_events(runtime_events)
                for event, event_id in zip(runtime_events, event_ids):
                    event["event_id"] = event_id

            print(
                f"[{started_at}] supervisor active={summary['active']} "
                f"sync_attempted={summary['sync_attempted']} synced_ok={summary['synced_ok']} "
                f"sync_failed={summary['sync_failed']} events={len(runtime_events)}"
            )
            for item in result["items"]:
                print(format_supervisor_line(item))
            for event in runtime_events:
                print(format_event_line(event))

            previous_state = runtime_state
        except Exception as exc:
            error_message = str(exc)
            error_state = {
                "proposal_state": (
                    previous_state.get("proposal_state")
                    if isinstance(previous_state.get("proposal_state"), dict)
                    else {}
                ),
                "last_scan_at": previous_state.get("last_scan_at"),
                "last_summary": previous_state.get("last_summary") if isinstance(previous_state, dict) else {},
                "last_error": {
                    "message": error_message,
                    "at": started_at,
                },
            }
            persist_runtime(
                runtime_key,
                error_state,
                {
                    "scanned_at": started_at,
                    "scan_mode": "supervisor",
                    "summary": {
                        "error": error_message,
                    },
                    "item_count": 0,
                },
            )
            error_event = build_event(
                runtime_key=runtime_key,
                event_type="scan_exception",
                severity="error",
                summary=f"supervisor scan failed: {error_message}",
                payload={
                    "runtime_key": runtime_key,
                    "error": error_message,
                    "at": started_at,
                },
            )
            if not args.disable_events:
                event_id = persist_events([error_event])[0]
                error_event["event_id"] = event_id
            print(format_event_line(error_event), file=sys.stderr)
            if args.once:
                raise

        if args.once:
            break

        time.sleep(max(10, args.interval_seconds))


if __name__ == "__main__":
    main()
