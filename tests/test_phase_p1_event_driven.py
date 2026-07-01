from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from ict_engine.evaluation import decision_allows_execution_plan
from public_market_stream import KlineRolloverDetector, normalize_closed_kline_events
from scan_loop import (
    EventDrivenScanRuntime,
    build_fallback_scan_requests,
    execute_scan_requests,
)


def closed_message(symbol="BTCUSDT", interval="5", start_ms=1776556500000, end_ms=1776556799999, confirm=True):
    return {
        "topic": f"kline.{interval}.{symbol}",
        "type": "snapshot",
        "data": [
            {
                "symbol": symbol,
                "interval": interval,
                "start": start_ms,
                "end": end_ms,
                "confirm": confirm,
                "open": "85000",
                "high": "85100",
                "low": "84900",
                "close": "85050",
                "volume": "10",
                "turnover": "100",
            }
        ],
    }


def closed_message_without_symbol(interval="5", start_ms=1776556500000, end_ms=1776556799999, confirm=True):
    message = closed_message(interval=interval, start_ms=start_ms, end_ms=end_ms, confirm=confirm)
    message["data"][0].pop("symbol", None)
    return message


def minimal_scan_result(instrument="BTCUSDT", decision="scanner_candidate"):
    return {
        "ok": True,
        "results": [
            {
                "ok": True,
                "instrument": instrument,
                "paper_trade_evaluation": {"decision": decision},
                "paper_trade_payload": {"instrument": instrument},
                "context": {},
            }
        ],
    }


def test_closed_5m_candle_triggers_one_scan_with_the_correct_reference_timestamp():
    runtime = EventDrivenScanRuntime()
    events = normalize_closed_kline_events(closed_message())
    requests = runtime.build_scan_requests(events)

    assert len(requests) == 1
    request = requests[0]
    assert request["instrument"] == "BTCUSDT"
    assert request["reference_ms"] == 1776556800000
    assert request["trigger_intervals"] == ["5m"]

    runner = Mock(return_value=minimal_scan_result())
    execute_scan_requests(
        requests,
        category="linear",
        auto_log_candidates=False,
        dedupe_state={},
        persistent_dedupe=True,
        record_history=True,
        runtime_state=runtime,
        scan_runner=runner,
    )

    kwargs = runner.call_args.kwargs
    assert kwargs["reference_ms_by_instrument"] == {"BTCUSDT": 1776556800000}
    assert kwargs["scan_trigger_by_instrument"]["BTCUSDT"]["reference_at"] == "2026-04-19T00:00:00+00:00"


def test_kline_topic_supplies_symbol_when_bybit_payload_omits_it():
    events = normalize_closed_kline_events(closed_message_without_symbol())

    assert len(events) == 1
    assert events[0]["symbol"] == "BTCUSDT"
    assert events[0]["event_key"] == "BTCUSDT:5:1776556500000"


def test_incomplete_open_candle_does_not_trigger_a_scan():
    events = normalize_closed_kline_events(closed_message(confirm=False))
    runtime = EventDrivenScanRuntime()
    requests = runtime.build_scan_requests(events)
    assert events == []
    assert requests == []


def test_first_open_snapshot_bootstraps_previous_closed_event_from_stream_flow():
    detector = KlineRolloverDetector(bootstrap_previous=True)
    events = detector.events_from_message(
        closed_message(confirm=False, start_ms=1776556800000, end_ms=1776557099999)
    )

    assert len(events) == 1
    assert events[0]["source"] == "rollover_bootstrap"
    assert events[0]["start_ms"] == 1776556500000
    assert events[0]["reference_ms"] == 1776556800000


def test_open_snapshot_rollover_derives_previous_closed_event_without_confirm_true():
    detector = KlineRolloverDetector(bootstrap_previous=False)

    first = detector.events_from_message(closed_message(confirm=False, start_ms=1776556500000))
    second = detector.events_from_message(
        closed_message(confirm=False, start_ms=1776556800000, end_ms=1776557099999)
    )

    assert first == []
    assert len(second) == 1
    assert second[0]["source"] == "rollover"
    assert second[0]["start_ms"] == 1776556500000
    assert second[0]["reference_ms"] == 1776556800000


def test_repeated_receipt_of_the_same_closed_candle_does_not_duplicate_the_scan():
    runtime = EventDrivenScanRuntime()
    events = normalize_closed_kline_events(closed_message())
    first_requests = runtime.build_scan_requests(events)
    second_requests = runtime.build_scan_requests(events)

    assert len(first_requests) == 1
    assert second_requests == []


def test_15m_and_4h_close_events_produce_deterministic_reference_timestamps():
    fifteen = normalize_closed_kline_events(
        closed_message(interval="15", start_ms=1776555900000, end_ms=1776556799999)
    )
    four_hour = normalize_closed_kline_events(
        closed_message(interval="240", start_ms=1776542400000, end_ms=1776556799999)
    )

    assert fifteen[0]["interval"] == "15m"
    assert fifteen[0]["reference_ms"] == 1776556800000
    assert four_hour[0]["interval"] == "4H"
    assert four_hour[0]["reference_ms"] == 1776556800000


def test_fallback_polling_path_does_not_create_duplicate_decision_traces_when_event_driven_scan_already_handled_the_bar():
    runtime = EventDrivenScanRuntime()
    runtime.mark_reference_handled("BTCUSDT", 1776556800000)

    def fetcher(instrument, category="linear", interval_code="5m"):
        return {
            "ok": True,
            "instrument": instrument,
            "interval": "5",
            "reference_ms": 1776556800000,
            "reference_at": "2026-04-18T00:00:00+00:00",
        }

    requests = build_fallback_scan_requests(["BTCUSDT"], "linear", runtime, reference_fetcher=fetcher)
    assert requests == []


def test_event_driven_path_preserves_verified_only_execution_semantics():
    runtime = EventDrivenScanRuntime()
    events = normalize_closed_kline_events(closed_message())
    requests = runtime.build_scan_requests(events)
    runner = Mock(return_value=minimal_scan_result(decision="scanner_candidate"))

    batches = execute_scan_requests(
        requests,
        category="linear",
        auto_log_candidates=False,
        dedupe_state={},
        persistent_dedupe=True,
        record_history=True,
        runtime_state=runtime,
        scan_runner=runner,
    )

    decision = batches[0]["results"][0]["paper_trade_evaluation"]["decision"]
    assert decision == "scanner_candidate"
    assert decision_allows_execution_plan(decision) is False


class TestPhaseP1EventDriven(unittest.TestCase):
    def test_closed_5m_candle_triggers_one_scan_with_the_correct_reference_timestamp(self):
        test_closed_5m_candle_triggers_one_scan_with_the_correct_reference_timestamp()

    def test_kline_topic_supplies_symbol_when_bybit_payload_omits_it(self):
        test_kline_topic_supplies_symbol_when_bybit_payload_omits_it()

    def test_incomplete_open_candle_does_not_trigger_a_scan(self):
        test_incomplete_open_candle_does_not_trigger_a_scan()

    def test_first_open_snapshot_bootstraps_previous_closed_event_from_stream_flow(self):
        test_first_open_snapshot_bootstraps_previous_closed_event_from_stream_flow()

    def test_open_snapshot_rollover_derives_previous_closed_event_without_confirm_true(self):
        test_open_snapshot_rollover_derives_previous_closed_event_without_confirm_true()

    def test_repeated_receipt_of_the_same_closed_candle_does_not_duplicate_the_scan(self):
        test_repeated_receipt_of_the_same_closed_candle_does_not_duplicate_the_scan()

    def test_15m_and_4h_close_events_produce_deterministic_reference_timestamps(self):
        test_15m_and_4h_close_events_produce_deterministic_reference_timestamps()

    def test_fallback_polling_path_does_not_create_duplicate_decision_traces_when_event_driven_scan_already_handled_the_bar(self):
        test_fallback_polling_path_does_not_create_duplicate_decision_traces_when_event_driven_scan_already_handled_the_bar()

    def test_event_driven_path_preserves_verified_only_execution_semantics(self):
        test_event_driven_path_preserves_verified_only_execution_semantics()
