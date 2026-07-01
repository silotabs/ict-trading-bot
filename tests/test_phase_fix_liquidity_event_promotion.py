from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import server as trading_server
from ict_engine.context import summarize_context_state, summarize_narrative_state
from ict_engine.signal_trace import build_signal_trace


def make_candles(step_minutes, count, start="2026-04-25T00:00:00+00:00"):
    current = datetime.fromisoformat(start).astimezone(timezone.utc)
    candles = []
    for index in range(count):
        open_ = 100.0 + index * 0.05
        close = open_ + (0.2 if index % 2 == 0 else -0.1)
        high = max(open_, close) + 0.5
        low = min(open_, close) - 0.5
        candles.append(
            {
                "start_ms": int(current.timestamp() * 1000),
                "start_at": current.replace(microsecond=0).isoformat(),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1.0,
                "turnover": 1.0,
            }
        )
        current += timedelta(minutes=step_minutes)
    return candles


def ready_discount_bias():
    drt = {
        "state": "ready",
        "confidence": 0.82,
        "high": 110.0,
        "low": 90.0,
        "midpoint": 100.0,
        "spread": 20.0,
        "location": "discount",
        "liquidity_event": {
            "state": "none",
            "confidence": 0.15,
            "at": "2026-04-25T04:00:00+00:00",
            "direction": "neutral",
            "reason": "latest 4H candle did not produce a clear dealing-range liquidity event",
        },
        "open_objective": "unclear",
    }
    return {
        "bias": "bullish",
        "confidence": 0.4,
        "reason": "price is still in discount, but the liquidity decision is not settled",
        "range": {
            "high": 110.0,
            "low": 90.0,
            "midpoint": 100.0,
            "spread": 20.0,
            "location": "discount",
            "last_close": 96.0,
        },
        "drt": drt,
        "liquidity_event": drt["liquidity_event"],
    }


def intraday_ssl_sweep():
    return {
        "state": "sell_side_sweep",
        "confidence": 0.56,
        "level": 95.0,
        "at": "2026-04-25T07:45:00+00:00",
        "reason": "15m sell-side liquidity was raided and reclaimed inside the configured sweep profile",
        "timeframe": "15m",
    }


def test_intraday_ssl_sweep_can_supply_effective_liquidity_event_inside_ready_discount_drt():
    bias = ready_discount_bias()
    event = trading_server.derive_effective_liquidity_event(
        bias["drt"],
        intraday_ssl_sweep(),
        bias,
    )

    assert event["state"] == "raid_ssl_reject"
    assert event["direction"] == "bullish"
    assert event["source_timeframe"] == "15m"
    assert event["source_state"] == "sell_side_sweep"
    assert event["reference_role"] == "intraday_range_liquidity"
    assert event["liquidity_tier"] == "internal"
    assert event["source_event"]["state"] == "sell_side_sweep"


def test_intraday_sweep_does_not_override_existing_4h_liquidity_event():
    bias = ready_discount_bias()
    native_event = {
        "state": "bsl_close_through_acceptance",
        "direction": "bullish",
        "level": 109.5,
        "at": "2026-04-25T04:00:00+00:00",
    }
    bias["drt"]["liquidity_event"] = native_event
    bias["liquidity_event"] = native_event

    event = trading_server.derive_effective_liquidity_event(
        bias["drt"],
        intraday_ssl_sweep(),
        bias,
    )

    assert event is native_event


def test_intraday_sweep_requires_aligned_bias_location_and_half_of_range():
    bias = ready_discount_bias()
    wrong_location = dict(bias["drt"], location="premium")
    wrong_half_sweep = dict(intraday_ssl_sweep(), level=104.0)

    wrong_location_event = trading_server.derive_effective_liquidity_event(
        wrong_location,
        intraday_ssl_sweep(),
        bias,
    )
    wrong_half_event = trading_server.derive_effective_liquidity_event(
        bias["drt"],
        wrong_half_sweep,
        bias,
    )

    assert wrong_location_event["state"] == "none"
    assert wrong_half_event["state"] == "none"


def test_scan_uses_promoted_intraday_liquidity_event_for_checklist_and_mss_anchor():
    bias = ready_discount_bias()
    sweep = intraday_ssl_sweep()
    mss_mock = Mock(
        return_value={
            "state": "none",
            "confidence": 0.18,
            "at": None,
            "reason": "no recent 15m MSS",
        }
    )

    with patch.object(trading_server, "infer_4h_bias", return_value=bias):
        with patch.object(trading_server, "detect_recent_sweep_15m", return_value=sweep):
            with patch.object(trading_server, "detect_recent_mss_15m", mss_mock):
                with patch.object(
                    trading_server,
                    "detect_recent_displacement_5m",
                    return_value={"state": "none", "at": None, "confidence": 0.18},
                ):
                    with patch.object(
                        trading_server,
                        "detect_recent_fvg_5m",
                        return_value={"state": "none", "at": None, "confidence": 0.18},
                    ):
                        with patch.object(
                            trading_server,
                            "summarize_execution_pd_arrays",
                            return_value={"lead": {"name": "", "respect_state": "unknown"}},
                        ):
                            result = trading_server.build_heuristic_scan_from_market_state(
                                symbol="BTCUSDT",
                                category="linear",
                                bias_candles=make_candles(240, 8),
                                setup_candles=make_candles(15, 25),
                                execution_candles=make_candles(5, 30),
                                ticker={"lastPrice": 99.0},
                                session_info={
                                    "active_session": "london",
                                    "session_valid": True,
                                    "weekend": False,
                                    "now_utc": "2026-04-25T08:00:00+00:00",
                                },
                                auto_log=False,
                            )

    assert result["ok"] is True
    assert result["paper_trade_payload"]["checklist"]["liquidity_event"] is True
    assert result["context"]["liquidity_event_4h"]["state"] == "raid_ssl_reject"
    assert result["context"]["liquidity_event_4h"]["source_timeframe"] == "15m"
    assert result["context"]["native_liquidity_event_4h"]["state"] == "none"
    assert result["context"]["drt_4h"]["open_objective"] == "upside"
    assert mss_mock.call_args.kwargs["after_at"] == sweep["at"]


def test_intraday_range_liquidity_can_align_context_after_strict_promotion():
    drt = {
        "state": "ready",
        "confidence": 0.82,
        "location": "discount",
        "spread": 20.0,
        "liquidity_event": {
            "state": "raid_ssl_reject",
            "direction": "bullish",
            "narrative_hint": "reversal",
            "level": 95.0,
            "reference_role": "intraday_range_liquidity",
            "liquidity_tier": "internal",
            "source_timeframe": "15m",
            "reason": "15m sell-side liquidity was swept and reclaimed inside a ready 4H discount read",
        },
    }
    narrative = summarize_narrative_state(
        bias_summary={"bias": "bullish"},
        drt_summary=drt,
        liquidity_map={
            "prior_day_high": {"price": 120.0},
            "prior_day_low": {"price": 80.0},
            "asian_range_high": {"price": None},
            "asian_range_low": {"price": None},
            "equal_high_candidates": [],
            "equal_low_candidates": [],
            "recent_15m_swing_highs": [],
            "recent_15m_swing_lows": [],
            "recent_4h_swing_highs": [],
            "recent_4h_swing_lows": [],
        },
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
    assert narrative["liquidity_reference_alignment"]["state"] == "aligned"
    assert narrative["liquidity_reference_alignment"]["reference_tier"] == "internal"
    assert narrative["liquidity_reference_alignment"]["matched_internal_references"] == ["intraday_range_liquidity"]
    assert context["state"] == "aligned"


def test_intraday_reversal_accepts_same_direction_entry_array_after_ssl_reclaim():
    drt = {
        "state": "ready",
        "confidence": 0.82,
        "location": "discount",
        "spread": 20.0,
        "liquidity_event": {
            "state": "raid_ssl_reject",
            "direction": "bullish",
            "narrative_hint": "reversal",
            "level": 95.0,
            "reference_role": "intraday_range_liquidity",
            "liquidity_tier": "internal",
            "source_timeframe": "15m",
            "reason": "15m sell-side liquidity was swept and reclaimed inside a ready 4H discount read",
        },
    }
    narrative = summarize_narrative_state(
        bias_summary={"bias": "bullish"},
        drt_summary=drt,
        liquidity_map={
            "prior_day_high": {"price": 120.0},
            "prior_day_low": {"price": 80.0},
            "asian_range_high": {"price": None},
            "asian_range_low": {"price": None},
            "equal_high_candidates": [],
            "equal_low_candidates": [],
            "recent_15m_swing_highs": [],
            "recent_15m_swing_lows": [],
            "recent_4h_swing_highs": [],
            "recent_4h_swing_lows": [],
        },
        pd_arrays_summary={"lead": {"name": "BISI", "respect_state": "respected", "ifvg_candidate": False}},
        mss_summary={"state": "bullish_mss"},
    )

    assert narrative["state"] == "reversal"
    assert narrative["array_support"] == "supportive"
    assert narrative["evidence"]["pd_array_narrative_role"] == "supportive_entry_array"
    assert "reversal_counter_array_direction_conflict" not in narrative["ambiguity_flags"]


def test_4h_reversal_still_requires_counter_array_not_same_direction_entry_array():
    narrative = summarize_narrative_state(
        bias_summary={"bias": "bullish"},
        drt_summary={
            "state": "ready",
            "confidence": 0.82,
            "location": "discount",
            "spread": 20.0,
            "liquidity_event": {
                "state": "raid_ssl_reject",
                "direction": "bullish",
                "narrative_hint": "reversal",
                "level": 90.0,
                "reason": "4H sell-side liquidity was raided and rejected",
            },
        },
        liquidity_map={
            "prior_day_high": {"price": 120.0},
            "prior_day_low": {"price": 90.0},
            "asian_range_high": {"price": None},
            "asian_range_low": {"price": None},
            "equal_high_candidates": [],
            "equal_low_candidates": [],
            "recent_15m_swing_highs": [],
            "recent_15m_swing_lows": [],
            "recent_4h_swing_highs": [],
            "recent_4h_swing_lows": [],
        },
        pd_arrays_summary={"lead": {"name": "BISI", "respect_state": "respected", "ifvg_candidate": False}},
        mss_summary={"state": "bullish_mss"},
    )

    assert narrative["state"] == "unclear"
    assert "reversal_counter_array_direction_conflict" in narrative["ambiguity_flags"]


def test_signal_trace_keeps_15m_sweep_detail_for_auditability():
    trace = build_signal_trace(
        source_path="replay",
        context={
            "session": {"active_session": "london", "session_valid": True},
            "drt_4h": {"state": "ready", "confidence": 0.8},
            "liquidity_event_4h": {"state": "raid_ssl_reject"},
            "sweep_15m": intraday_ssl_sweep(),
            "pd_arrays": {"lead": {"name": "BISI", "respect_state": "respected"}},
        },
        evaluation={"decision": "no_paper_trade", "blockers": []},
        payload={"instrument": "BTCUSDT", "source_mode": "scanner_verified"},
    )

    assert trace["details"]["sweep_15m"]["state"] == "sell_side_sweep"
    assert trace["details"]["pd_arrays"]["lead"]["name"] == "BISI"


class TestPhaseFixLiquidityEventPromotion(unittest.TestCase):
    def test_intraday_ssl_sweep_can_supply_effective_liquidity_event_inside_ready_discount_drt(self):
        test_intraday_ssl_sweep_can_supply_effective_liquidity_event_inside_ready_discount_drt()

    def test_intraday_sweep_does_not_override_existing_4h_liquidity_event(self):
        test_intraday_sweep_does_not_override_existing_4h_liquidity_event()

    def test_intraday_sweep_requires_aligned_bias_location_and_half_of_range(self):
        test_intraday_sweep_requires_aligned_bias_location_and_half_of_range()

    def test_scan_uses_promoted_intraday_liquidity_event_for_checklist_and_mss_anchor(self):
        test_scan_uses_promoted_intraday_liquidity_event_for_checklist_and_mss_anchor()

    def test_intraday_range_liquidity_can_align_context_after_strict_promotion(self):
        test_intraday_range_liquidity_can_align_context_after_strict_promotion()

    def test_intraday_reversal_accepts_same_direction_entry_array_after_ssl_reclaim(self):
        test_intraday_reversal_accepts_same_direction_entry_array_after_ssl_reclaim()

    def test_4h_reversal_still_requires_counter_array_not_same_direction_entry_array(self):
        test_4h_reversal_still_requires_counter_array_not_same_direction_entry_array()

    def test_signal_trace_keeps_15m_sweep_detail_for_auditability(self):
        test_signal_trace_keeps_15m_sweep_detail_for_auditability()
