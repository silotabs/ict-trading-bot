#!/usr/bin/env python3

import argparse
import time
from datetime import datetime, timezone

from runtime_api import OPERATIONS_DEFAULT_THRESHOLDS, TradingAPIHandler, build_operations_status


TRACKED_FIELDS = (
    "health",
    "status",
    "summary",
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run a read-only operations watchdog over the trading stack."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single watchdog cycle and exit.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=30,
        help="Seconds to wait between watchdog scans. Default: 30.",
    )
    parser.add_argument(
        "--runtime-key",
        default="default",
        help="Operations runtime key used for persisted watchdog state. Default: default.",
    )
    parser.add_argument(
        "--watchlist-stale-after-seconds",
        type=int,
        default=OPERATIONS_DEFAULT_THRESHOLDS["watchlist_stale_after_seconds"],
        help="Mark watchlist scan state stale after this many seconds. Default: 900.",
    )
    parser.add_argument(
        "--supervisor-stale-after-seconds",
        type=int,
        default=OPERATIONS_DEFAULT_THRESHOLDS["supervisor_stale_after_seconds"],
        help="Mark supervisor runtime stale after this many seconds. Default: 180.",
    )
    parser.add_argument(
        "--private-stream-stale-after-seconds",
        type=int,
        default=OPERATIONS_DEFAULT_THRESHOLDS["private_stream_stale_after_seconds"],
        help="Mark private-stream runtime stale after this many seconds. Default: 90.",
    )
    parser.add_argument(
        "--auto-execution-stale-after-seconds",
        type=int,
        default=OPERATIONS_DEFAULT_THRESHOLDS["auto_execution_stale_after_seconds"],
        help="Mark auto-execution runtime stale after this many seconds. Default: 180.",
    )
    parser.add_argument(
        "--trade-management-stale-after-seconds",
        type=int,
        default=OPERATIONS_DEFAULT_THRESHOLDS["trade_management_stale_after_seconds"],
        help="Mark trade-management runtime stale after this many seconds. Default: 180.",
    )
    parser.add_argument(
        "--disable-events",
        action="store_true",
        help="Do not persist operations events to SQLite.",
    )
    return parser.parse_args()


def format_component_line(item):
    return (
        f"{item.get('component_key', 'unknown')} | "
        f"health={item.get('health', 'unknown')} | "
        f"status={item.get('status', 'unknown')} | "
        f"{item.get('summary', '')}"
    )


def format_event_line(event):
    return (
        f"EVENT {event.get('severity', 'info').upper()} "
        f"{event.get('event_type', 'unknown')} | "
        f"{event.get('component_key') or '-'} | "
        f"{event.get('summary', '')}"
    )


def compact_component_state(component):
    return {
        "component_key": component.get("component_key"),
        "component_type": component.get("component_type"),
        "health": component.get("health"),
        "status": component.get("status"),
        "summary": component.get("summary"),
    }


def build_event(runtime_key, event_type, severity, summary, payload, component_key=None):
    return {
        "runtime_key": runtime_key,
        "event_type": event_type,
        "severity": severity,
        "summary": summary,
        "component_key": component_key,
        "payload": payload if isinstance(payload, dict) else {},
    }


def load_runtime_state(runtime_key):
    record = TradingAPIHandler.store.get_operations_runtime(runtime_key)
    if record is None:
        return {}, None
    state = record.get("state") if isinstance(record.get("state"), dict) else {}
    return state, record


def build_runtime_start_event(runtime_key, previous_runtime):
    if previous_runtime is None:
        return build_event(
            runtime_key=runtime_key,
            event_type="runtime_started",
            severity="info",
            summary=f"operations runtime {runtime_key} started with no previous state",
            payload={"runtime_key": runtime_key},
        )

    return build_event(
        runtime_key=runtime_key,
        event_type="runtime_resumed",
        severity="info",
        summary=f"operations runtime {runtime_key} resumed from stored state",
        payload={
            "runtime_key": runtime_key,
            "previous_updated_at": previous_runtime.get("updated_at"),
            "previous_heartbeat_at": previous_runtime.get("heartbeat_at"),
            "previous_last_scan_at": previous_runtime.get("last_scan_at"),
        },
    )


def build_runtime_summary(result):
    return {
        "scanned_at": result.get("scanned_at"),
        "overall": result.get("overall") or {},
        "component_count": len(result.get("components") or []),
    }


def persist_runtime(runtime_key, runtime_state, last_summary):
    TradingAPIHandler.store.upsert_operations_runtime(
        runtime_key=runtime_key,
        state=runtime_state,
        last_summary=last_summary,
    )


def persist_events(events):
    event_ids = []
    for event in events:
        event_id = TradingAPIHandler.store.create_operations_event(
            runtime_key=event["runtime_key"],
            event_type=event["event_type"],
            severity=event["severity"],
            summary=event["summary"],
            event_payload=event["payload"],
            component_key=event.get("component_key"),
        )
        event_ids.append(event_id)
    return event_ids


def build_cycle_events(runtime_key, previous_state, result):
    previous_map = (
        previous_state.get("component_state")
        if isinstance(previous_state.get("component_state"), dict)
        else {}
    )
    current_map = {}
    events = []

    for component in result.get("components") or []:
        component_key = component.get("component_key")
        if not component_key:
            continue
        state = compact_component_state(component)
        current_map[component_key] = state
        previous_item = previous_map.get(component_key)

        if previous_item is None:
            if state.get("health") != "healthy":
                events.append(
                    build_event(
                        runtime_key=runtime_key,
                        event_type="component_alert",
                        severity=state.get("health") or "warning",
                        summary=state.get("summary") or f"{component_key} is {state.get('status')}",
                        payload={"current": state},
                        component_key=component_key,
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

        if state.get("health") == "healthy" and previous_item.get("health") != "healthy":
            event_type = "component_recovered"
            severity = "info"
        elif state.get("health") != "healthy":
            event_type = "component_alert"
            severity = state.get("health") or "warning"
        else:
            event_type = "component_status_changed"
            severity = "info"

        events.append(
            build_event(
                runtime_key=runtime_key,
                event_type=event_type,
                severity=severity,
                summary=state.get("summary") or f"{component_key} is {state.get('status')}",
                payload={"previous": previous_item, "current": state, "changes": changes},
                component_key=component_key,
            )
        )

    for component_key, previous_item in previous_map.items():
        if component_key in current_map:
            continue
        events.append(
            build_event(
                runtime_key=runtime_key,
                event_type="component_removed",
                severity="warning",
                summary=f"{component_key} no longer appears in operations status",
                payload={"previous": previous_item},
                component_key=component_key,
            )
        )

    runtime_state = {
        "component_state": current_map,
        "overall": result.get("overall") or {},
        "thresholds": result.get("thresholds") or {},
        "last_scan_at": result.get("scanned_at"),
        "last_error": None,
    }
    return events, runtime_state


def main():
    args = parse_args()
    runtime_key = (args.runtime_key or "").strip() or "default"
    previous_state, previous_runtime = load_runtime_state(runtime_key)

    startup_event = build_runtime_start_event(runtime_key, previous_runtime)
    if not args.disable_events:
        event_id = persist_events([startup_event])[0]
        startup_event["event_id"] = event_id
    print(format_event_line(startup_event))

    while True:
        started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        try:
            result = build_operations_status(
                watchlist_stale_after_seconds=args.watchlist_stale_after_seconds,
                supervisor_stale_after_seconds=args.supervisor_stale_after_seconds,
                private_stream_stale_after_seconds=args.private_stream_stale_after_seconds,
                auto_execution_stale_after_seconds=args.auto_execution_stale_after_seconds,
                trade_management_stale_after_seconds=args.trade_management_stale_after_seconds,
            )
            runtime_events, runtime_state = build_cycle_events(runtime_key, previous_state, result)
            summary_payload = build_runtime_summary(result)
            persist_runtime(runtime_key, runtime_state, summary_payload)

            if not args.disable_events and runtime_events:
                event_ids = persist_events(runtime_events)
                for event, event_id in zip(runtime_events, event_ids):
                    event["event_id"] = event_id

            overall = result.get("overall") or {}
            print(
                f"[{started_at}] operations overall={overall.get('health', 'unknown')} "
                f"components={overall.get('component_count', 0)} "
                f"alerts={overall.get('alert_count', 0)}"
            )
            for item in result.get("components") or []:
                print(format_component_line(item))
            for event in runtime_events:
                print(format_event_line(event))

            previous_state = runtime_state
        except Exception as exc:
            error_message = str(exc)
            error_state = {
                "component_state": (
                    previous_state.get("component_state")
                    if isinstance(previous_state.get("component_state"), dict)
                    else {}
                ),
                "overall": previous_state.get("overall") if isinstance(previous_state, dict) else {},
                "thresholds": previous_state.get("thresholds") if isinstance(previous_state, dict) else {},
                "last_scan_at": previous_state.get("last_scan_at"),
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
                    "overall": {"health": "error"},
                    "component_count": len(error_state["component_state"]),
                },
            )
            error_event = build_event(
                runtime_key=runtime_key,
                event_type="watchdog_error",
                severity="error",
                summary=f"operations watchdog failed: {error_message}",
                payload={"error": error_message},
            )
            if not args.disable_events:
                event_id = persist_events([error_event])[0]
                error_event["event_id"] = event_id
            print(format_event_line(error_event))
            previous_state = error_state

        if args.once:
            break
        time.sleep(max(5, args.interval_seconds))


if __name__ == "__main__":
    main()
