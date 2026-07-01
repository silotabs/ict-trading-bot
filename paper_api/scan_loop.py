#!/usr/bin/env python3

import argparse
import time
from datetime import datetime, timedelta, timezone

from public_market_stream import (
    DEFAULT_PUBLIC_INTERVALS,
    PublicKlineEventService,
    WebSocketError,
)
from runtime_api import (
    BYBIT_MARKET_BASE_URL,
    RULES,
    TradingAPIHandler,
    fetch_latest_closed_reference_ms,
    resolve_control_state,
    run_watchlist_scan,
)


def utc_from_ms(value):
    return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).replace(microsecond=0).isoformat()


class EventDrivenScanRuntime:
    def __init__(self):
        self.seen_event_keys = set()
        self.last_handled_reference_ms = {}
        self.connection_status = "disconnected"
        self.event_path_state = "disconnected"
        self.connected_at = None
        self.last_public_event_at = None
        self.last_confirmed_close_processed_at = None
        self.last_confirmed_close_reference_at = None
        self.last_confirmed_close_reference_ms = None
        self.last_fallback_poll_at = None
        self.last_fallback_carry_at = None
        self.last_fallback_carry_reference_at = None
        self.last_fallback_carry_reference_ms = None
        self.fallback_reference_interval_seconds = None
        self.fallback_interval_seconds = None
        self.next_fallback_due_at = None
        self.fallback_active = False
        self.last_error = None
        self.reconnect_count = 0
        self.consecutive_event_errors = 0
        self.event_reconnect_backoff_seconds = None
        self.next_event_connect_due_at = None
        self.last_trigger_mode = None

    def note_stream_connected(self, observed_at):
        if self.connected_at:
            self.reconnect_count += 1
        self.connected_at = observed_at
        self.connection_status = "connected"
        self.event_path_state = "connected_no_flow"
        self.last_error = None
        self.consecutive_event_errors = 0
        self.event_reconnect_backoff_seconds = None
        self.next_event_connect_due_at = None

    def note_public_events(self, observed_at):
        self.last_public_event_at = observed_at
        self.connection_status = "streaming"
        self.event_path_state = "receiving_events"
        self.fallback_active = False
        self.last_error = None
        self.consecutive_event_errors = 0
        self.event_reconnect_backoff_seconds = None
        self.next_event_connect_due_at = None

    def note_event_error(self, message, *, observed_at=None, base_backoff_seconds=5, max_backoff_seconds=60):
        self.connection_status = "unavailable"
        self.event_path_state = "disconnected"
        self.last_error = str(message or "").strip() or "event stream error"
        self.consecutive_event_errors += 1
        backoff_seconds = min(
            max(1, int(max_backoff_seconds)),
            max(1, int(base_backoff_seconds)) * (2 ** max(0, self.consecutive_event_errors - 1)),
        )
        self.event_reconnect_backoff_seconds = backoff_seconds
        observed_dt = (
            datetime.fromisoformat(observed_at)
            if isinstance(observed_at, str) and observed_at
            else datetime.now(timezone.utc).replace(microsecond=0)
        )
        self.next_event_connect_due_at = (
            observed_dt + timedelta(seconds=backoff_seconds)
        ).replace(microsecond=0).isoformat()

    def seconds_until_event_connect_due(self, now_dt=None):
        if not self.next_event_connect_due_at:
            return 0.0
        current_dt = now_dt if isinstance(now_dt, datetime) else datetime.now(timezone.utc).replace(microsecond=0)
        due_dt = datetime.fromisoformat(self.next_event_connect_due_at)
        if due_dt.tzinfo is None:
            due_dt = due_dt.replace(tzinfo=timezone.utc)
        delta_seconds = (due_dt.astimezone(timezone.utc) - current_dt.astimezone(timezone.utc)).total_seconds()
        return max(0.0, delta_seconds)

    def event_connect_due(self, now_dt=None):
        return self.seconds_until_event_connect_due(now_dt=now_dt) <= 0.0

    def note_fallback_poll(self, observed_at, *, active, interval_seconds=None):
        self.last_fallback_poll_at = observed_at
        self.fallback_active = bool(active)
        if interval_seconds not in (None, ""):
            interval_seconds = max(1, int(interval_seconds))
            self.fallback_interval_seconds = interval_seconds
            observed_dt = datetime.fromisoformat(observed_at)
            next_due_dt = observed_dt + timedelta(seconds=interval_seconds)
            self.next_fallback_due_at = next_due_dt.replace(microsecond=0).isoformat()
        if active:
            self.last_trigger_mode = "fallback_poll"
            self.event_path_state = "degraded_fallback"
        elif self.connection_status == "streaming":
            self.event_path_state = "receiving_events"
        elif self.connection_status == "connected":
            self.event_path_state = "connected_no_flow"
        else:
            self.event_path_state = "disconnected"

    def build_scan_requests(self, events):
        pending = {}
        ordered = sorted(
            [item for item in (events or []) if isinstance(item, dict)],
            key=lambda item: (int(item.get("reference_ms") or 0), item.get("symbol") or ""),
        )
        for event in ordered:
            if event.get("type") != "closed_candle":
                continue
            event_key = str(event.get("event_key") or "").strip()
            if not event_key or event_key in self.seen_event_keys:
                continue
            self.seen_event_keys.add(event_key)

            symbol = str(event.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            reference_ms = int(event.get("reference_ms") or 0)
            if reference_ms <= int(self.last_handled_reference_ms.get(symbol, 0) or 0):
                continue

            request_key = (symbol, reference_ms)
            request = pending.setdefault(
                request_key,
                {
                    "instrument": symbol,
                    "reference_ms": reference_ms,
                    "reference_at": event.get("reference_at") or utc_from_ms(reference_ms),
                    "trigger_intervals": [],
                    "event_keys": [],
                    "trigger_mode": "event_driven",
                },
            )
            interval = str(event.get("interval") or "").strip()
            if interval and interval not in request["trigger_intervals"]:
                request["trigger_intervals"].append(interval)
            if event_key not in request["event_keys"]:
                request["event_keys"].append(event_key)

        return list(pending.values())

    def should_run_fallback(self, instrument, reference_ms):
        instrument = str(instrument or "").strip().upper()
        if not instrument or reference_ms in (None, ""):
            return False
        return int(reference_ms) > int(self.last_handled_reference_ms.get(instrument, 0) or 0)

    def mark_reference_handled(self, instrument, reference_ms, *, reference_at=None, trigger_mode=None):
        instrument = str(instrument or "").strip().upper()
        if not instrument or reference_ms in (None, ""):
            return
        current = int(self.last_handled_reference_ms.get(instrument, 0) or 0)
        self.last_handled_reference_ms[instrument] = max(current, int(reference_ms))
        handled_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        self.last_confirmed_close_processed_at = handled_at
        self.last_confirmed_close_reference_at = reference_at or utc_from_ms(reference_ms)
        self.last_confirmed_close_reference_ms = int(reference_ms)
        if trigger_mode:
            self.last_trigger_mode = str(trigger_mode)
        if trigger_mode == "fallback_poll":
            self.last_fallback_carry_at = handled_at
            self.last_fallback_carry_reference_at = self.last_confirmed_close_reference_at
            self.last_fallback_carry_reference_ms = self.last_confirmed_close_reference_ms
            self.fallback_reference_interval_seconds = 5 * 60

    def build_runtime_state(self):
        return {
            "connection_status": self.connection_status,
            "event_path_state": self.event_path_state,
            "connected_at": self.connected_at,
            "last_public_event_at": self.last_public_event_at,
            "last_confirmed_close_processed_at": self.last_confirmed_close_processed_at,
            "last_confirmed_close_reference_at": self.last_confirmed_close_reference_at,
            "last_confirmed_close_reference_ms": self.last_confirmed_close_reference_ms,
            "last_fallback_poll_at": self.last_fallback_poll_at,
            "last_fallback_carry_at": self.last_fallback_carry_at,
            "last_fallback_carry_reference_at": self.last_fallback_carry_reference_at,
            "last_fallback_carry_reference_ms": self.last_fallback_carry_reference_ms,
            "fallback_reference_interval_seconds": self.fallback_reference_interval_seconds,
            "fallback_interval_seconds": self.fallback_interval_seconds,
            "next_fallback_due_at": self.next_fallback_due_at,
            "fallback_active": self.fallback_active,
            "last_error": self.last_error,
            "reconnect_count": self.reconnect_count,
            "consecutive_event_errors": self.consecutive_event_errors,
            "event_reconnect_backoff_seconds": self.event_reconnect_backoff_seconds,
            "next_event_connect_due_at": self.next_event_connect_due_at,
            "last_trigger_mode": self.last_trigger_mode,
        }


def persist_public_market_runtime(runtime_state):
    snapshot = runtime_state.build_runtime_state()
    TradingAPIHandler.store.upsert_operations_runtime(
        runtime_key="public_market:default",
        state=snapshot,
        last_summary={
            "scanned_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "connection_status": snapshot.get("connection_status"),
            "event_path_state": snapshot.get("event_path_state"),
            "last_public_event_at": snapshot.get("last_public_event_at"),
            "last_confirmed_close_processed_at": snapshot.get("last_confirmed_close_processed_at"),
            "last_confirmed_close_reference_at": snapshot.get("last_confirmed_close_reference_at"),
            "last_fallback_poll_at": snapshot.get("last_fallback_poll_at"),
            "last_fallback_carry_at": snapshot.get("last_fallback_carry_at"),
            "last_fallback_carry_reference_at": snapshot.get("last_fallback_carry_reference_at"),
            "fallback_reference_interval_seconds": snapshot.get("fallback_reference_interval_seconds"),
            "fallback_interval_seconds": snapshot.get("fallback_interval_seconds"),
            "next_fallback_due_at": snapshot.get("next_fallback_due_at"),
            "fallback_active": bool(snapshot.get("fallback_active")),
            "consecutive_event_errors": snapshot.get("consecutive_event_errors"),
            "event_reconnect_backoff_seconds": snapshot.get("event_reconnect_backoff_seconds"),
            "next_event_connect_due_at": snapshot.get("next_event_connect_due_at"),
            "last_trigger_mode": snapshot.get("last_trigger_mode"),
        },
    )


def initialize_public_market_runtime(runtime_state):
    persist_public_market_runtime(runtime_state)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run repeated Bybit ICT watchlist scans for BTCUSDT and ETHUSDT."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scan cycle and exit.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=300,
        help="Seconds to wait between scan cycles. Default: 300.",
    )
    parser.add_argument(
        "--instruments",
        default=",".join(RULES["allowed_instruments"]),
        help="Comma-separated list of instruments. Default: BTCUSDT,ETHUSDT.",
    )
    parser.add_argument(
        "--category",
        default="linear",
        help="Bybit category. Default: linear.",
    )
    parser.add_argument(
        "--auto-log-candidates",
        action="store_true",
        help="Log new paper-trade candidates into the journal.",
    )
    parser.add_argument(
        "--disable-persistent-dedupe",
        action="store_true",
        help="Use only in-memory dedupe for this process.",
    )
    parser.add_argument(
        "--disable-history",
        action="store_true",
        help="Do not persist watchlist scan history entries.",
    )
    parser.add_argument(
        "--disable-event-driven",
        action="store_true",
        help="Use fallback polling only instead of the public candle-close stream.",
    )
    parser.add_argument(
        "--event-timeout-seconds",
        type=float,
        default=10.0,
        help="Seconds to wait for public candle-close events before checking fallback polling. Default: 10.",
    )
    parser.add_argument(
        "--disable-fallback-polling",
        action="store_true",
        help="Do not use REST fallback polling for missed or bootstrap bars.",
    )
    parser.add_argument(
        "--degraded-fallback-interval-seconds",
        type=int,
        default=60,
        help="Seconds between fallback polls while the primary event path is degraded. Default: 60.",
    )
    return parser.parse_args()


def format_scan_line(result):
    if not result.get("ok"):
        return f"{result.get('instrument', 'unknown')} error: {result.get('error', 'scan failed')}"

    evaluation = result["paper_trade_evaluation"]
    context = result["context"]
    mss = context.get("mss_15m") or context.get("mss_5m") or {}
    narrative = context.get("narrative") or {}
    parts = [
        result["instrument"],
        evaluation["decision"],
        f"session={context['session']['active_session']}",
        f"bias={context['bias_4h']['bias']}",
        f"sweep={context['sweep_15m']['state']}",
        f"mss={mss.get('state', 'none')}",
        f"disp={context['displacement_5m']['state']}",
        f"fvg={context['fvg_5m']['state']}",
        f"narr={narrative.get('state', 'unclear')}",
    ]

    if result.get("candidate_logged"):
        parts.append(f"logged={result.get('journal_id')}")
    elif result.get("duplicate_candidate"):
        parts.append("duplicate_candidate=true")

    trigger = result.get("context", {}).get("scan_trigger") if isinstance(result.get("context"), dict) else {}
    if isinstance(trigger, dict):
        mode = trigger.get("mode")
        intervals = trigger.get("trigger_intervals") or []
        if mode:
            parts.append(f"trigger={mode}:{'/'.join(intervals) if intervals else '-'}")

    return " | ".join(parts)


def build_scan_trigger(request):
    return {
        "mode": request.get("trigger_mode") or "event_driven",
        "kind": "closed_candle",
        "reference_ms": int(request.get("reference_ms")),
        "reference_at": request.get("reference_at") or utc_from_ms(request.get("reference_ms")),
        "trigger_intervals": list(request.get("trigger_intervals") or []),
        "event_keys": list(request.get("event_keys") or []),
    }


def execute_scan_requests(
    requests,
    *,
    category,
    auto_log_candidates,
    dedupe_state,
    persistent_dedupe,
    record_history,
    runtime_state,
    scan_runner=run_watchlist_scan,
):
    batches = []
    for request in requests or []:
        instrument = request.get("instrument")
        reference_ms = int(request.get("reference_ms"))
        trigger = build_scan_trigger(request)
        batch = scan_runner(
            instruments=[instrument],
            category=category,
            auto_log_candidates=auto_log_candidates,
            dedupe_state=dedupe_state,
            persistent_dedupe=persistent_dedupe,
            record_history=record_history,
            reference_ms_by_instrument={instrument: reference_ms},
            scan_trigger_by_instrument={instrument: trigger},
        )
        batches.append(batch)
        for item in batch.get("results") or []:
            if item.get("ok"):
                runtime_state.mark_reference_handled(
                    instrument,
                    reference_ms,
                    reference_at=request.get("reference_at"),
                    trigger_mode=request.get("trigger_mode"),
                )
    return batches


def build_fallback_scan_requests(instruments, category, runtime_state, reference_fetcher=fetch_latest_closed_reference_ms):
    requests = []
    for instrument in instruments or []:
        latest = reference_fetcher(instrument, category=category, interval_code="5m")
        if not latest.get("ok"):
            continue
        reference_ms = latest.get("reference_ms")
        if not runtime_state.should_run_fallback(instrument, reference_ms):
            continue
        requests.append(
            {
                "instrument": instrument,
                "reference_ms": int(reference_ms),
                "reference_at": latest.get("reference_at") or utc_from_ms(reference_ms),
                "trigger_intervals": ["5m"],
                "event_keys": [],
                "trigger_mode": "fallback_poll",
            }
        )
    return requests


def determine_fallback_interval_seconds(event_service_enabled, runtime_state, *, interval_seconds, degraded_interval_seconds):
    normal_interval = max(10, int(interval_seconds))
    degraded_interval = max(10, int(degraded_interval_seconds))
    if not event_service_enabled:
        return normal_interval
    event_path_state = str(getattr(runtime_state, "event_path_state", "") or "disconnected")
    if event_path_state == "receiving_events":
        return normal_interval
    return degraded_interval


def main():
    args = parse_args()
    instruments = [item.strip().upper() for item in args.instruments.split(",") if item.strip()]
    dedupe_state = {}
    runtime_state = EventDrivenScanRuntime()
    event_service = None
    next_fallback_at = 0.0

    if not args.disable_event_driven:
        event_service = PublicKlineEventService(
            market_base_url=BYBIT_MARKET_BASE_URL,
            category=args.category,
            symbols=instruments,
            intervals=DEFAULT_PUBLIC_INTERVALS,
            timeout=args.event_timeout_seconds,
        )

    initialize_public_market_runtime(runtime_state)

    while True:
        started_dt = datetime.now(timezone.utc).replace(microsecond=0)
        started_at = started_dt.isoformat()
        degraded_event_path = False
        event_reconnect_delayed = False
        control = resolve_control_state("scan_loop")
        if control["effective_paused"]:
            reason = control["effective_reason"] or "scan loop paused by control state"
            print(f"[{started_at}] scan loop paused: {reason}", flush=True)
            if args.once:
                break
            time.sleep(max(10, args.interval_seconds))
            continue

        batches = []
        if event_service is not None:
            try:
                if event_service.client.sock is None:
                    if runtime_state.event_connect_due(now_dt=started_dt):
                        event_service.connect()
                        runtime_state.note_stream_connected(started_at)
                        print(f"[{started_at}] event stream connected for {', '.join(instruments)}", flush=True)
                    else:
                        event_reconnect_delayed = True
                if event_service.client.sock is not None:
                    events = event_service.recv_closed_events(timeout=args.event_timeout_seconds)
                    if events:
                        runtime_state.note_public_events(started_at)
                    requests = runtime_state.build_scan_requests(events)
                    if requests:
                        print(f"[{started_at}] event-triggered scan for {', '.join(item['instrument'] for item in requests)}", flush=True)
                        batches.extend(
                            execute_scan_requests(
                                requests,
                                category=args.category,
                                auto_log_candidates=args.auto_log_candidates,
                                dedupe_state=dedupe_state,
                                persistent_dedupe=not args.disable_persistent_dedupe,
                                record_history=not args.disable_history,
                                runtime_state=runtime_state,
                            )
                        )
            except WebSocketError as exc:
                runtime_state.note_event_error(exc, observed_at=started_at)
                degraded_event_path = True
                print(f"[{started_at}] event stream error: {exc}", flush=True)
                event_service.close()

        now_monotonic = time.monotonic()
        fallback_interval_seconds = determine_fallback_interval_seconds(
            event_service is not None,
            runtime_state,
            interval_seconds=args.interval_seconds,
            degraded_interval_seconds=args.degraded_fallback_interval_seconds,
        )
        if not args.disable_fallback_polling and (event_service is None or now_monotonic >= next_fallback_at):
            fallback_mode_active = event_service is None or runtime_state.event_path_state != "receiving_events"
            requests = build_fallback_scan_requests(
                instruments,
                args.category,
                runtime_state,
            )
            if requests:
                runtime_state.note_fallback_poll(
                    started_at,
                    active=fallback_mode_active,
                    interval_seconds=fallback_interval_seconds,
                )
                print(f"[{started_at}] fallback scan for {', '.join(item['instrument'] for item in requests)}", flush=True)
                batches.extend(
                    execute_scan_requests(
                        requests,
                        category=args.category,
                        auto_log_candidates=args.auto_log_candidates,
                        dedupe_state=dedupe_state,
                        persistent_dedupe=not args.disable_persistent_dedupe,
                        record_history=not args.disable_history,
                        runtime_state=runtime_state,
                    )
                )
            else:
                runtime_state.note_fallback_poll(
                    started_at,
                    active=fallback_mode_active,
                    interval_seconds=fallback_interval_seconds,
                )
            next_fallback_at = now_monotonic + fallback_interval_seconds

        if not batches and event_service is None and args.disable_fallback_polling:
            print(f"[{started_at}] no scan path configured", flush=True)

        for batch in batches:
            for item in batch.get("results") or []:
                print(format_scan_line(item), flush=True)

        persist_public_market_runtime(runtime_state)

        if args.once:
            break
        if event_service is None:
            time.sleep(max(10, args.interval_seconds))
        elif event_reconnect_delayed and not batches:
            backoff_wait = runtime_state.seconds_until_event_connect_due(now_dt=started_dt)
            time.sleep(max(1.0, min(backoff_wait or 1.0, float(fallback_interval_seconds), 15.0)))
        elif degraded_event_path and not batches:
            backoff_wait = runtime_state.seconds_until_event_connect_due(now_dt=started_dt)
            time.sleep(max(1.0, min(backoff_wait or 1.0, float(fallback_interval_seconds), 15.0)))


if __name__ == "__main__":
    main()
