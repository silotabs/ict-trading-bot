from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from ict_engine.context import summarize_context_state, summarize_narrative_state
from ict_engine.drt import detect_4h_liquidity_event, infer_4h_bias, summarize_4h_drt_state, summarize_dealing_range
from ict_engine.execution import (
    detect_recent_displacement_5m as detect_recent_displacement_5m_engine,
    detect_recent_fvg_5m as detect_recent_fvg_5m_engine,
    detect_recent_mss_15m as detect_recent_mss_15m_engine,
    detect_recent_sweep_15m as detect_recent_sweep_15m_engine,
)
from ict_engine.evaluation import decision_allows_execution_plan, evaluate_payload, normalize_checklist_payload
from ict_engine.liquidity import build_liquidity_map
from ict_engine.visual import derive_visual_analysis_state
import auto_execute_loop
import server as trading_server
from server import HEURISTIC_RULES, build_auto_execution_payload, normalize_tradingview_payload, session_context_at


def make_candle(start_at, open_, high, low, close):
    return {
        "start_at": start_at,
        "open": float(open_),
        "high": float(high),
        "low": float(low),
        "close": float(close),
    }


def build_4h_series(values, start="2026-04-16T00:00:00+00:00"):
    current = datetime.fromisoformat(start)
    candles = []
    for open_, high, low, close in values:
        candles.append(make_candle(current.replace(microsecond=0).isoformat(), open_, high, low, close))
        current += timedelta(hours=4)
    return candles


def build_15m_series(values, start="2026-04-17T00:00:00+00:00"):
    current = datetime.fromisoformat(start)
    candles = []
    for open_, high, low, close in values:
        candles.append(make_candle(current.replace(microsecond=0).isoformat(), open_, high, low, close))
        current += timedelta(minutes=15)
    return candles


def build_5m_series(values, start="2026-04-17T00:00:00+00:00"):
    current = datetime.fromisoformat(start)
    candles = []
    for open_, high, low, close in values:
        candles.append(make_candle(current.replace(microsecond=0).isoformat(), open_, high, low, close))
        current += timedelta(minutes=5)
    return candles


def clear_bullish_drt_candles():
    return build_4h_series(
        [
            (95, 100, 90, 97),
            (97, 102, 91, 100),
            (100, 104, 93, 103),
            (103, 114, 95, 106),
            (106, 107, 94, 95),
            (95, 105, 92, 94),
            (94, 103, 84, 90),
            (90, 104, 90, 101),
            (101, 105, 91, 103),
            (103, 106, 92, 104),
            (104, 108, 94, 106),
            (106, 107, 93, 105),
        ]
    )


def clear_bearish_drt_candles():
    return build_4h_series(
        [
            (125, 130, 120, 126),
            (126, 129, 121, 123),
            (123, 127, 118, 119),
            (119, 124, 110, 113),
            (113, 120, 111, 116),
            (116, 122, 114, 120),
            (120, 135, 118, 132),
            (132, 131, 119, 121),
            (121, 129, 117, 120),
            (120, 126, 116, 119),
            (119, 124, 115, 118),
            (118, 123, 114, 117),
        ]
    )


def ambiguous_drt_candles():
    return build_4h_series(
        [
            (100, 101, 99, 100.5),
            (100.5, 101.2, 99.8, 100.8),
            (100.8, 101.4, 100.0, 100.9),
            (100.9, 101.5, 100.2, 101.0),
            (101.0, 101.6, 100.4, 101.1),
            (101.1, 101.7, 100.6, 101.2),
            (101.2, 101.8, 100.8, 101.3),
            (101.3, 101.9, 101.0, 101.4),
            (101.4, 102.0, 101.2, 101.5),
            (101.5, 102.1, 101.4, 101.6),
            (101.6, 102.2, 101.5, 101.7),
            (101.7, 102.3, 101.6, 101.8),
        ]
    )


def default_rules():
    return {
        "strategy_version": "ict-drt-narrative-v1",
        "allowed_instruments": ["BTCUSDT", "ETHUSDT"],
        "approved_proxies": ["BTCUSD", "ETHUSD"],
        "allowed_sessions": ["london", "new_york"],
        "timeframes": {"bias": "4H", "setup": "15m", "execution": "5m"},
        "required_checklist": [
            "clear_4h_bias",
            "clear_liquidity_draw",
            "liquidity_event",
            "mss",
            "displacement",
            "fresh_fvg",
            "clear_invalidation",
            "clear_target",
        ],
    }


def evaluate(payload):
    return evaluate_payload(
        payload,
        rules=default_rules(),
        normalize_instrument=lambda value: str(value).upper() if value else "",
        normalize_session=lambda value: str(value).lower() if value else "",
        normalize_direction=lambda value: str(value).lower() if value else "",
        normalize_timeframes_payload=lambda value: value if isinstance(value, dict) else {},
        evaluated_at=lambda: "2026-04-18T00:00:00+00:00",
    )


def test_bullish_external_swing_drt_anchor_selection():
    summary = summarize_dealing_range(clear_bullish_drt_candles())
    assert summary["state"] == "ready"
    assert summary["anchor_high_price"] == 114.0
    assert summary["anchor_low_price"] == 84.0
    assert summary["location"] == "premium"
    assert summary["confidence"] > 0.7


def test_bearish_external_swing_drt_anchor_selection():
    summary = summarize_dealing_range(clear_bearish_drt_candles())
    assert summary["state"] == "ready"
    assert summary["anchor_high_price"] == 135.0
    assert summary["anchor_low_price"] == 110.0
    assert summary["location"] == "discount"
    assert summary["confidence"] > 0.7


def test_ambiguous_noisy_drt_returns_unclear():
    summary = summarize_dealing_range(ambiguous_drt_candles())
    assert summary["state"] == "unclear"
    assert summary["confidence"] < 0.2
    assert summary["ambiguity_flags"]


def test_4h_liquidity_event_classifies_rejection_vs_acceptance():
    base = clear_bullish_drt_candles()
    drt = summarize_dealing_range(base)

    reject_candles = base + [
        make_candle("2026-04-18T00:00:00+00:00", 104, 116, 99, 106)
    ]
    accept_candles = base + [
        make_candle("2026-04-18T00:00:00+00:00", 108, 118, 104, 117)
    ]

    reject = detect_4h_liquidity_event(reject_candles, drt_summary=drt)
    accept = detect_4h_liquidity_event(accept_candles, drt_summary=drt)

    assert reject["state"] == "raid_bsl_reject"
    assert reject["interaction"] == "raid_reject"
    assert accept["state"] == "bsl_close_through_acceptance"
    assert accept["interaction"] == "accepted_through"


def test_4h_liquidity_event_accepts_internal_range_raid_rejection():
    drt = {
        "state": "ready",
        "high": 120.0,
        "low": 80.0,
        "spread": 40.0,
        "internal_liquidity": {
            "high": 108.0,
            "high_at": "2026-04-17T08:00:00+00:00",
            "low": 92.0,
            "low_at": "2026-04-17T12:00:00+00:00",
        },
    }
    candles = build_4h_series(
        [
            (101.0, 105.0, 98.0, 102.0),
            (103.0, 109.5, 101.0, 106.0),
        ],
        start="2026-04-18T00:00:00+00:00",
    )

    event = detect_4h_liquidity_event(candles, drt_summary=drt)

    assert event["state"] == "raid_bsl_reject"
    assert event["interaction"] == "raid_reject"
    assert event["direction"] == "bearish"
    assert event["level"] == 108.0
    assert event["liquidity_tier"] == "internal"
    assert event["reference_role"] == "internal_range_liquidity"


def test_bias_inference_uses_drt_location_and_liquidity_event():
    base = clear_bullish_drt_candles()
    reject_candles = base + [
        make_candle("2026-04-18T00:00:00+00:00", 104, 116, 99, 106)
    ]
    accept_candles = base + [
        make_candle("2026-04-18T00:00:00+00:00", 108, 118, 104, 117)
    ]

    reject_bias = infer_4h_bias(reject_candles)
    accept_bias = infer_4h_bias(accept_candles)

    assert reject_bias["bias"] == "bearish"
    assert accept_bias["bias"] == "bullish"


def test_liquidity_map_includes_pdh_pdl_and_asian_range():
    bias_candles = clear_bullish_drt_candles()
    drt = summarize_4h_drt_state(bias_candles)

    setup_candles = [
        make_candle("2026-04-17T00:00:00+00:00", 100, 101, 99, 100.5),
        make_candle("2026-04-17T00:15:00+00:00", 100.5, 103, 100, 102),
        make_candle("2026-04-17T00:30:00+00:00", 102, 102.5, 98, 99),
        make_candle("2026-04-18T00:00:00+00:00", 100.0, 101.5, 99.7, 101.0),
        make_candle("2026-04-18T00:15:00+00:00", 101.0, 104.0, 100.8, 103.5),
        make_candle("2026-04-18T00:30:00+00:00", 103.5, 103.8, 99.5, 100.0),
        make_candle("2026-04-18T00:45:00+00:00", 100.0, 102.0, 99.8, 101.2),
        make_candle("2026-04-18T01:00:00+00:00", 101.2, 101.6, 100.9, 101.0),
    ]

    liquidity_map = build_liquidity_map(
        drt_summary=drt,
        setup_candles=setup_candles,
        bias_candles=bias_candles,
        reference_time="2026-04-18T05:30:00+00:00",
        policy={
            "asian_range_timezone": "UTC",
            "asian_range_start_hour": 0,
            "asian_range_end_hour": 6,
            "asian_range_status": "starter_assumption",
        },
    )

    assert liquidity_map["prior_day_high"]["price"] == 103.0
    assert liquidity_map["prior_day_low"]["price"] == 98.0
    assert liquidity_map["asian_range_high"]["price"] == 104.0
    assert liquidity_map["asian_range_low"]["price"] == 99.5


def test_narrative_context_gate_blocks_execution_even_with_lower_tf_trigger():
    narrative = summarize_narrative_state(
        bias_summary={"bias": "bullish"},
        drt_summary={
            "location": "discount",
            "spread": 20,
            "liquidity_event": {
                "state": "raid_ssl_reject",
                "level": 90,
                "narrative_hint": "reversal",
                "reason": "sell-side liquidity was raided and rejected",
            },
        },
        liquidity_map={
            "prior_day_low": {"price": 90},
            "prior_day_high": {"price": 110},
            "asian_range_high": {"price": 104},
            "asian_range_low": {"price": 96},
        },
        pd_arrays_summary={"lead": {"name": "SIBI", "respect_state": "disrespected", "ifvg_candidate": True}},
        mss_summary={"state": "bullish_mss"},
    )
    context = summarize_context_state(
        session_info={"session_valid": False, "active_session": "outside"},
        bias_summary={"bias": "bullish"},
        narrative_summary=narrative,
        mss_summary={"state": "bullish_mss"},
    )

    assert narrative["state"] == "reversal"
    assert context["state"] == "invalid_session"
    assert context["execution_eligible"] is False


def test_manual_assertion_evaluates_to_journal_only_not_verified():
    result = evaluate(
        {
            "instrument": "BTCUSDT",
            "provider": "manual",
            "session": "london",
            "direction": "long",
            "source_mode": "manual_assertion",
            "timeframes": {"bias": "4H", "setup": "15m", "execution": "5m"},
            "checklist": {
                "clear_4h_bias": True,
                "clear_liquidity_draw": True,
                "liquidity_event": True,
                "mss": True,
                "displacement": True,
                "fresh_fvg": True,
                "clear_invalidation": True,
                "clear_target": True,
                "chase_entry": False,
            },
        }
    )

    assert result["decision"] == "journal_only"
    assert result["verification"]["source_mode"] == "manual_assertion"


def test_liquidity_sweep_alias_is_still_accepted_for_compatibility():
    normalized = normalize_checklist_payload(
        {"clear_4h_bias": True, "liquidity_sweep": True, "chase_entry": False},
        ["clear_4h_bias", "liquidity_event"],
    )
    assert normalized["liquidity_event"] is True


def test_session_context_is_deterministic_for_reference_timestamp():
    reference_ms = int(datetime(2026, 4, 17, 6, 30, tzinfo=timezone.utc).timestamp() * 1000)
    first = session_context_at(reference_ms)
    second = session_context_at(reference_ms)
    assert first == second
    assert first["active_session"] == "london"


def test_normalize_tradingview_payload_labels_screenshot_as_manual_context_only():
    payload = normalize_tradingview_payload(
        {
            "ticker": "BITSTAMP:BTCUSD",
            "direction": "long",
            "timeframes": {"bias": "4H", "setup": "15m", "execution": "5m"},
            "checklist": {"liquidity_event": True, "chase_entry": False},
            "chart_url": "https://www.tradingview.com/chart/example",
            "screenshot_paths": ["screenshots/example.png"],
            "reference_at": "2026-04-18T08:00:00+00:00",
        }
    )

    assert payload["source_mode"] == "manual_assertion"
    assert payload["visual_analysis_state"] == "manual_context_only"


def test_visual_analysis_state_without_images_is_not_run():
    assert derive_visual_analysis_state() == "not_run"


def test_execution_plan_gate_allows_only_verified_decisions():
    assert decision_allows_execution_plan("verified_paper_trade") is True
    assert decision_allows_execution_plan("scanner_candidate") is False
    assert decision_allows_execution_plan("journal_only") is False
    assert decision_allows_execution_plan("no_paper_trade") is False


def test_tradingview_payload_derives_session_from_reference_time():
    payload = normalize_tradingview_payload(
        {
            "ticker": "BITSTAMP:BTCUSD",
            "direction": "long",
            "timeframes": {"bias": "4H", "setup": "15m", "execution": "5m"},
            "checklist": {"liquidity_event": True, "chase_entry": False},
            "reference_at": "2026-04-18T06:30:00+00:00",
        }
    )
    assert payload["session"] == "london"


def test_extracted_15m_detectors_return_structured_payloads():
    candles = build_15m_series(
        [
            (100.0, 101.0, 99.5, 100.4),
            (100.4, 101.2, 99.8, 100.9),
            (100.9, 101.4, 100.3, 101.1),
            (101.1, 101.6, 100.5, 101.4),
            (101.4, 101.8, 100.8, 101.2),
            (101.2, 101.5, 100.6, 100.9),
            (100.9, 101.1, 100.0, 100.2),
            (100.2, 100.6, 99.1, 99.6),
            (99.6, 100.0, 99.0, 99.4),
            (99.4, 100.4, 99.2, 100.3),
            (100.3, 102.4, 100.1, 102.1),
            (102.1, 103.0, 101.7, 102.7),
        ]
    )

    sweep = detect_recent_sweep_15m_engine(candles, config=HEURISTIC_RULES["sweep_15m"])
    mss = detect_recent_mss_15m_engine(
        candles,
        expected_direction="bullish",
        after_at=candles[7]["start_at"],
        config=HEURISTIC_RULES["mss_15m"],
    )

    assert sweep["state"] in {"buy_side_sweep", "sell_side_sweep", "none"}
    assert "confidence" in sweep
    assert "evidence" in sweep
    assert mss["state"] == "bullish_mss"
    assert mss["timeframe"] == "15m"
    assert "limitations" in mss


def test_extracted_5m_execution_detectors_return_structured_payloads():
    base = [(100.0, 100.4, 99.8, 100.1)] * 20
    candles = build_5m_series(
        base
        + [
            (100.1, 103.9, 100.0, 103.7),
            (103.7, 104.1, 103.5, 103.9),
            (104.7, 105.4, 104.5, 105.2),
        ]
    )

    displacement = detect_recent_displacement_5m_engine(
        candles,
        after_at=candles[20]["start_at"],
        expected_direction="bullish",
        config=HEURISTIC_RULES["displacement_5m"],
    )
    fvg = detect_recent_fvg_5m_engine(
        candles,
        after_at=candles[20]["start_at"],
        expected_direction="bullish",
    )

    assert displacement["state"] == "bullish"
    assert displacement["role"] == "displacement_confirmation"
    assert "assumptions" in displacement
    assert fvg["state"] == "bullish"
    assert fvg["role"] == "entry_array"
    assert "limitations" in fvg


def test_fvg_backed_break_counts_as_displacement_confirmation():
    base = [(100.0, 100.7, 99.8, 100.4)] * 20
    candles = build_5m_series(
        base
        + [
            (100.4, 101.0, 100.0, 100.6),
            (100.6, 101.4, 100.5, 101.2),
            (101.3, 102.0, 101.2, 101.6),
        ]
    )

    displacement = detect_recent_displacement_5m_engine(
        candles,
        after_at=candles[20]["start_at"],
        expected_direction="bullish",
        config=HEURISTIC_RULES["displacement_5m"],
    )

    assert displacement["state"] == "bullish"
    assert displacement["mode"] == "fvg_break"
    assert displacement["role"] == "displacement_confirmation"
    assert displacement["evidence"]["fvg_lower"] == 101.0
    assert displacement["evidence"]["fvg_upper"] == 101.2


def test_webhook_manual_assertion_flow_stays_non_executable():
    normalized = normalize_tradingview_payload(
        {
            "ticker": "BITSTAMP:BTCUSD",
            "direction": "long",
            "timeframes": {"bias": "4H", "setup": "15m", "execution": "5m"},
            "checklist": {
                "clear_4h_bias": True,
                "clear_liquidity_draw": True,
                "liquidity_event": True,
                "mss": True,
                "displacement": True,
                "fresh_fvg": True,
                "clear_invalidation": True,
                "clear_target": True,
                "chase_entry": False,
            },
            "screenshot_paths": ["screenshots/context.png"],
            "reference_at": "2026-04-18T06:30:00+00:00",
        }
    )
    evaluation = evaluate(normalized)
    scan_result = {
        "ok": True,
        "instrument": normalized["instrument"],
        "scan_signature": "manual-test",
        "paper_trade_evaluation": {"decision": evaluation["decision"]},
        "context": {
            "auto_execution_levels": {
                "ok": True,
                "entry_price": "100.0",
                "stop_loss": "99.0",
                "take_profit": "102.0",
            }
        },
        "paper_trade_payload": normalized,
    }

    payload_result = build_auto_execution_payload(scan_result, {"category": "linear"}, "test-runtime")

    assert evaluation["decision"] == "journal_only"
    assert normalized["visual_analysis_state"] == "manual_context_only"
    assert decision_allows_execution_plan(evaluation["decision"]) is False
    assert payload_result["ok"] is False


def test_auto_execute_run_cycle_stays_disabled_when_policy_off():
    with patch.object(auto_execute_loop, "resolve_control_state", return_value={"effective_paused": False}):
        result = auto_execute_loop.run_cycle("test-runtime", previous_state={}, policy={"enabled": False})

    assert result["mode"] == "disabled"
    assert result["summary"]["policy_enabled"] is False
    assert result["summary"]["scan_count"] == 0
    assert result["summary"]["verified_paper_trade_candidates"] == 0


def test_watchlist_scan_does_not_log_scanner_candidate():
    fake_store = SimpleNamespace(
        get_watchlist_state=lambda instrument: None,
        create_entry=lambda payload, evaluation: "J-should-not-happen",
        upsert_watchlist_state=lambda **kwargs: "WL-1",
        clear_watchlist_logged_state=lambda **kwargs: None,
        create_scan_history_entry=lambda **kwargs: "SH-1",
        create_signal_trace=lambda trace: "ST-1",
    )
    scan_result = {
        "ok": True,
        "instrument": "BTCUSDT",
        "paper_trade_evaluation": {"decision": "scanner_candidate"},
        "paper_trade_payload": {"instrument": "BTCUSDT"},
        "scan_signature": "sig-1",
    }

    with patch.object(trading_server, "build_bybit_heuristic_scan", return_value=dict(scan_result)):
        with patch.object(trading_server.TradingAPIHandler, "store", fake_store):
            result = trading_server.run_watchlist_scan(
                instruments=["BTCUSDT"],
                auto_log_candidates=True,
                persistent_dedupe=False,
                record_history=False,
            )

    item = result["results"][0]
    assert item["paper_trade_evaluation"]["decision"] == "scanner_candidate"
    assert item["candidate_logged"] is False
    assert "journal_id" not in item


def test_watchlist_scan_logs_verified_paper_trade_candidate():
    created = {"entries": 0}

    def create_entry(payload, evaluation):
        created["entries"] += 1
        return "J-1"

    fake_store = SimpleNamespace(
        get_watchlist_state=lambda instrument: None,
        create_entry=create_entry,
        upsert_watchlist_state=lambda **kwargs: "WL-1",
        clear_watchlist_logged_state=lambda **kwargs: None,
        create_scan_history_entry=lambda **kwargs: "SH-1",
        create_signal_trace=lambda trace: "ST-1",
    )
    scan_result = {
        "ok": True,
        "instrument": "BTCUSDT",
        "paper_trade_evaluation": {"decision": "verified_paper_trade"},
        "paper_trade_payload": {"instrument": "BTCUSDT"},
        "scan_signature": "sig-verified",
    }

    with patch.object(trading_server, "build_bybit_heuristic_scan", return_value=dict(scan_result)):
        with patch.object(trading_server.TradingAPIHandler, "store", fake_store):
            result = trading_server.run_watchlist_scan(
                instruments=["BTCUSDT"],
                auto_log_candidates=True,
                persistent_dedupe=False,
                record_history=False,
            )

    item = result["results"][0]
    assert item["paper_trade_evaluation"]["decision"] == "verified_paper_trade"
    assert item["candidate_logged"] is True
    assert item["journal_id"] == "J-1"
    assert created["entries"] == 1


def test_build_auto_execution_payload_accepts_only_verified_paper_trade():
    base_scan_result = {
        "ok": True,
        "instrument": "BTCUSDT",
        "scan_signature": "sig-auto",
        "context": {
            "auto_execution_levels": {
                "ok": True,
                "entry_price": "100.0",
                "stop_loss": "99.0",
                "take_profit": "102.0",
            }
        },
        "paper_trade_payload": {
            "instrument": "BTCUSDT",
            "session": "london",
            "direction": "long",
            "weekend": False,
            "timeframes": {"bias": "4H", "setup": "15m", "execution": "5m"},
            "checklist": {"liquidity_event": True, "chase_entry": False},
        },
    }

    verified_result = build_auto_execution_payload(
        {
            **base_scan_result,
            "paper_trade_evaluation": {"decision": "verified_paper_trade"},
        },
        {"category": "linear"},
        "test-runtime",
    )
    legacy_result = build_auto_execution_payload(
        {
            **base_scan_result,
            "paper_trade_evaluation": {"decision": "paper_trade"},
        },
        {"category": "linear"},
        "test-runtime",
    )

    assert verified_result["ok"] is True
    assert verified_result["payload"]["provider"] == "auto-execution-policy"
    assert legacy_result["ok"] is False
    assert "not execution-eligible" in legacy_result["error"]


def test_low_confidence_drt_blocks_aligned_narrative_and_context():
    narrative = summarize_narrative_state(
        bias_summary={"bias": "bullish"},
        drt_summary={
            "state": "low_confidence",
            "confidence": 0.34,
            "location": "discount",
            "spread": 20,
            "liquidity_event": {
                "state": "raid_ssl_reject",
                "level": 90,
                "narrative_hint": "reversal",
                "reason": "sell-side liquidity was raided and rejected",
            },
        },
        liquidity_map={
            "prior_day_low": {"price": 90},
            "prior_day_high": {"price": 110},
            "asian_range_high": {"price": 104},
            "asian_range_low": {"price": 96},
        },
        pd_arrays_summary={"lead": {"name": "BISI", "respect_state": "respected"}},
        mss_summary={"state": "bullish_mss"},
    )
    context = summarize_context_state(
        session_info={"session_valid": True, "active_session": "london"},
        bias_summary={"bias": "bullish"},
        narrative_summary=narrative,
        mss_summary={"state": "bullish_mss"},
    )

    assert narrative["state"] == "unclear"
    assert context["state"] != "aligned"
    assert context["execution_eligible"] is False


class TestIctEngineAlignment(unittest.TestCase):
    def test_bullish_external_swing_drt_anchor_selection(self):
        test_bullish_external_swing_drt_anchor_selection()

    def test_bearish_external_swing_drt_anchor_selection(self):
        test_bearish_external_swing_drt_anchor_selection()

    def test_ambiguous_noisy_drt_returns_unclear(self):
        test_ambiguous_noisy_drt_returns_unclear()

    def test_4h_liquidity_event_classifies_rejection_vs_acceptance(self):
        test_4h_liquidity_event_classifies_rejection_vs_acceptance()

    def test_bias_inference_uses_drt_location_and_liquidity_event(self):
        test_bias_inference_uses_drt_location_and_liquidity_event()

    def test_liquidity_map_includes_pdh_pdl_and_asian_range(self):
        test_liquidity_map_includes_pdh_pdl_and_asian_range()

    def test_narrative_context_gate_blocks_execution_even_with_lower_tf_trigger(self):
        test_narrative_context_gate_blocks_execution_even_with_lower_tf_trigger()

    def test_manual_assertion_evaluates_to_journal_only_not_verified(self):
        test_manual_assertion_evaluates_to_journal_only_not_verified()

    def test_liquidity_sweep_alias_is_still_accepted_for_compatibility(self):
        test_liquidity_sweep_alias_is_still_accepted_for_compatibility()

    def test_session_context_is_deterministic_for_reference_timestamp(self):
        test_session_context_is_deterministic_for_reference_timestamp()

    def test_normalize_tradingview_payload_labels_screenshot_as_manual_context_only(self):
        test_normalize_tradingview_payload_labels_screenshot_as_manual_context_only()

    def test_visual_analysis_state_without_images_is_not_run(self):
        test_visual_analysis_state_without_images_is_not_run()

    def test_execution_plan_gate_allows_only_verified_decisions(self):
        test_execution_plan_gate_allows_only_verified_decisions()

    def test_tradingview_payload_derives_session_from_reference_time(self):
        test_tradingview_payload_derives_session_from_reference_time()

    def test_extracted_15m_detectors_return_structured_payloads(self):
        test_extracted_15m_detectors_return_structured_payloads()

    def test_extracted_5m_execution_detectors_return_structured_payloads(self):
        test_extracted_5m_execution_detectors_return_structured_payloads()

    def test_webhook_manual_assertion_flow_stays_non_executable(self):
        test_webhook_manual_assertion_flow_stays_non_executable()

    def test_auto_execute_run_cycle_stays_disabled_when_policy_off(self):
        test_auto_execute_run_cycle_stays_disabled_when_policy_off()

    def test_watchlist_scan_does_not_log_scanner_candidate(self):
        test_watchlist_scan_does_not_log_scanner_candidate()

    def test_watchlist_scan_logs_verified_paper_trade_candidate(self):
        test_watchlist_scan_logs_verified_paper_trade_candidate()

    def test_build_auto_execution_payload_accepts_only_verified_paper_trade(self):
        test_build_auto_execution_payload_accepts_only_verified_paper_trade()

    def test_low_confidence_drt_blocks_aligned_narrative_and_context(self):
        test_low_confidence_drt_blocks_aligned_narrative_and_context()
