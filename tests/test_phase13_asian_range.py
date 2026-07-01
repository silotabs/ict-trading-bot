from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from ict_engine.context import summarize_context_state, summarize_narrative_state
from ict_engine.drt import summarize_4h_drt_state
from ict_engine.liquidity import build_liquidity_map
from ict_engine.evaluation import decision_allows_execution_plan
import server as trading_server


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


def default_liquidity_map():
    return {
        "prior_day_low": {"price": 90, "timezone": "UTC"},
        "prior_day_high": {"price": 110, "timezone": "UTC"},
        "asian_range_high": {
            "price": 104,
            "timezone": "UTC",
            "status": "starter_assumption",
            "assumption_grade": "starter_assumption",
            "assumption_reason": "Asian range uses the configured starter window until the house rules pin a different definition",
            "cannot_promote_alignment_alone": True,
            "window": "00:00-06:00",
        },
        "asian_range_low": {
            "price": 96,
            "timezone": "UTC",
            "status": "starter_assumption",
            "assumption_grade": "starter_assumption",
            "assumption_reason": "Asian range uses the configured starter window until the house rules pin a different definition",
            "cannot_promote_alignment_alone": True,
            "window": "00:00-06:00",
        },
    }


def test_phase13_asian_range_is_tagged_assumption_grade_in_liquidity_map():
    bias_candles = clear_bullish_drt_candles()
    drt = summarize_4h_drt_state(bias_candles)
    setup_candles = [
        make_candle("2026-04-17T00:00:00+00:00", 100.0, 101.0, 99.0, 100.5),
        make_candle("2026-04-17T00:15:00+00:00", 100.5, 103.0, 100.0, 102.0),
        make_candle("2026-04-17T00:30:00+00:00", 102.0, 102.5, 98.0, 99.0),
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

    assert liquidity_map["asian_range_high"]["assumption_grade"] == "starter_assumption"
    assert liquidity_map["asian_range_high"]["cannot_promote_alignment_alone"] is True
    assert "configured starter window" in liquidity_map["asian_range_high"]["assumption_reason"]
    assert liquidity_map["asian_range_low"]["assumption_grade"] == "starter_assumption"
    assert liquidity_map["asian_range_low"]["cannot_promote_alignment_alone"] is True


def test_phase13_asian_range_alignment_cannot_alone_promote_context_to_aligned():
    narrative = summarize_narrative_state(
        bias_summary={"bias": "bullish"},
        drt_summary={
            "state": "ready",
            "confidence": 0.84,
            "location": "discount",
            "spread": 20,
            "liquidity_event": {
                "state": "raid_ssl_reject",
                "level": 96,
                "direction": "bullish",
                "narrative_hint": "reversal",
                "reason": "sell-side liquidity was raided and rejected",
            },
        },
        liquidity_map=default_liquidity_map(),
        pd_arrays_summary={"lead": {"name": "SIBI", "respect_state": "disrespected", "ifvg_candidate": True}},
        mss_summary={"state": "bullish_mss"},
    )
    context = summarize_context_state(
        session_info={"session_valid": True, "active_session": "london"},
        bias_summary={"bias": "bullish"},
        narrative_summary=narrative,
        mss_summary={"state": "bullish_mss"},
    )

    assert narrative["state"] == "reversal"
    assert narrative["liquidity_reference_alignment"]["state"] == "assumption_only"
    assert narrative["liquidity_reference_alignment"]["assumption_grade"] == "starter_assumption"
    assert narrative["liquidity_reference_alignment"]["cannot_promote_alignment_alone"] is True
    assert context["state"] == "watch"
    assert context["execution_eligible"] is False
    assert "assumption-grade Asian range alignment" in context["reason"]


def test_phase13_scanner_context_reports_assumption_only_narrative_without_changing_execution_gate():
    bias_candles = build_4h_series([(100.0, 101.0, 99.0, 100.5)] * 8)
    setup_candles = build_15m_series([(100.0, 101.0, 99.0, 100.5)] * 25)
    execution_candles = build_5m_series([(100.0, 101.0, 99.5, 100.6)] * 30)

    patched_bias_summary = {
        "bias": "bullish",
        "confidence": 0.82,
        "range": {
            "high": 110.0,
            "low": 90.0,
            "midpoint": 100.0,
            "last_close": 100.5,
            "location": "discount",
            "spread": 20.0,
        },
        "drt": {
            "state": "ready",
            "confidence": 0.84,
            "high": 110.0,
            "low": 90.0,
            "midpoint": 100.0,
            "location": "discount",
            "spread": 20.0,
            "liquidity_event": {
                "state": "raid_ssl_reject",
                "level": 96.0,
                "direction": "bullish",
                "narrative_hint": "reversal",
                "reason": "sell-side liquidity was raided and rejected",
            },
        },
        "liquidity_event": {
            "state": "raid_ssl_reject",
            "level": 96.0,
            "direction": "bullish",
            "narrative_hint": "reversal",
            "reason": "sell-side liquidity was raided and rejected",
        },
    }

    with patch.object(trading_server, "infer_4h_bias", return_value=patched_bias_summary):
        with patch.object(trading_server, "load_liquidity_context_policy", return_value={"ok": True, "policy": {"asian_range_status": "starter_assumption"}}):
            with patch.object(trading_server, "build_liquidity_map", return_value=default_liquidity_map()):
                with patch.object(trading_server, "detect_recent_sweep_15m", return_value={"state": "none", "at": None}):
                    with patch.object(trading_server, "detect_recent_mss_15m", return_value={"state": "bullish_mss", "at": "2026-04-18T05:00:00+00:00"}):
                        with patch.object(trading_server, "detect_recent_displacement_5m", return_value={"state": "bullish", "at": "2026-04-18T05:05:00+00:00"}):
                            with patch.object(trading_server, "detect_recent_fvg_5m", return_value={"state": "bullish", "lower": 100.0, "upper": 101.0, "midpoint": 100.5, "at": "2026-04-18T05:10:00+00:00"}):
                                with patch.object(trading_server, "summarize_execution_pd_arrays", return_value={"lead": {"name": "SIBI", "respect_state": "disrespected", "ifvg_candidate": True}, "tracked": []}):
                                    with patch.object(trading_server, "derive_liquidity_draw", return_value="upside"):
                                        with patch.object(trading_server, "detect_chase_state", return_value=False):
                                            result = trading_server.build_heuristic_scan_from_market_state(
                                                symbol="BTCUSDT",
                                                category="linear",
                                                bias_candles=bias_candles,
                                                setup_candles=setup_candles,
                                                execution_candles=execution_candles,
                                                ticker={"lastPrice": "100.6"},
                                                session_info={
                                                    "session_valid": True,
                                                    "active_session": "london",
                                                    "weekend": False,
                                                    "now_utc": "2026-04-18T05:30:00+00:00",
                                                },
                                                wall_clock_session_info={
                                                    "session_valid": True,
                                                    "active_session": "london",
                                                    "weekend": False,
                                                    "now_utc": "2026-04-18T05:30:00+00:00",
                                                },
                                                auto_log=False,
                                            )

    assert result["ok"] is True
    assert result["context"]["narrative"]["state"] == "reversal"
    assert result["context"]["narrative"]["liquidity_reference_alignment"]["state"] == "assumption_only"
    assert result["context"]["context_summary"]["state"] == "watch"
    assert result["context"]["context_summary"]["execution_eligible"] is False
    assert result["paper_trade_payload"]["direction"] == ""
    assert decision_allows_execution_plan(result["paper_trade_evaluation"]["decision"]) is False


class TestPhase13AsianRange(unittest.TestCase):
    def test_phase13_asian_range_is_tagged_assumption_grade_in_liquidity_map(self):
        test_phase13_asian_range_is_tagged_assumption_grade_in_liquidity_map()

    def test_phase13_asian_range_alignment_cannot_alone_promote_context_to_aligned(self):
        test_phase13_asian_range_alignment_cannot_alone_promote_context_to_aligned()

    def test_phase13_scanner_context_reports_assumption_only_narrative_without_changing_execution_gate(self):
        test_phase13_scanner_context_reports_assumption_only_narrative_without_changing_execution_gate()
