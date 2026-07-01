from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from ict_engine.context import summarize_context_state, summarize_narrative_state
from ict_engine.drt import detect_4h_liquidity_event, summarize_dealing_range


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


def missing_external_low_candles():
    return build_4h_series(
        [
            (100.0, 101.0, 99.8, 100.5),
            (100.5, 102.2, 100.1, 101.8),
            (101.8, 104.0, 101.4, 103.2),
            (103.2, 106.2, 102.8, 105.3),
            (105.3, 105.7, 104.9, 105.1),
            (105.1, 105.4, 104.7, 104.9),
            (104.9, 105.1, 104.5, 104.8),
            (104.8, 105.0, 104.3, 104.6),
            (104.6, 104.8, 104.1, 104.4),
            (104.4, 104.6, 103.9, 104.2),
            (104.2, 104.4, 103.7, 104.0),
            (104.0, 104.2, 103.5, 103.8),
        ]
    )


def anchors_too_close_candles():
    return build_4h_series(
        [
            (100.8, 101.6, 100.2, 101.0),
            (101.0, 101.9, 100.3, 101.4),
            (101.4, 102.2, 100.4, 101.9),
            (101.9, 102.4, 100.9, 102.0),
            (102.0, 102.1, 101.0, 101.3),
            (101.3, 101.5, 100.0, 100.4),
            (100.4, 101.2, 100.2, 100.8),
            (100.8, 101.6, 100.5, 101.1),
            (101.1, 101.8, 100.7, 101.3),
            (101.3, 101.7, 100.9, 101.2),
            (101.2, 101.6, 100.8, 101.1),
            (101.1, 101.5, 100.7, 101.0),
        ]
    )


def nested_recent_range_candles():
    return build_4h_series(
        [
            (100, 101, 99, 100),
            (100, 102, 98, 101),
            (101, 103, 95, 96),
            (96, 104, 96, 103),
            (103, 120, 100, 115),
            (115, 116, 90, 92),
            (92, 95, 80, 85),
            (85, 105, 84, 100),
            (100, 110, 92, 108),
            (108, 112, 97, 100),
            (100, 111, 108, 109),
            (109, 115, 109, 113),
            (113, 114, 106, 108),
            (108, 112, 105, 106),
            (106, 113, 106, 112),
            (112, 114, 107, 111),
        ]
    )


def test_drt_missing_clear_external_pair_returns_unclear():
    summary = summarize_dealing_range(missing_external_low_candles())

    assert summary["state"] == "unclear"
    assert summary["confidence"] <= 0.12
    assert summary["ambiguity_flags"] == ["missing_external_low"]


def test_drt_anchors_too_close_stays_low_confidence():
    summary = summarize_dealing_range(anchors_too_close_candles())

    assert summary["state"] == "low_confidence"
    assert "anchors_too_close" in summary["ambiguity_flags"]
    assert summary["confidence"] < 0.75


def test_drt_uses_wider_preserved_pair_when_latest_pair_is_nested():
    summary = summarize_dealing_range(nested_recent_range_candles())

    assert summary["state"] == "ready"
    assert summary["anchor_high_price"] == 115.0
    assert summary["anchor_low_price"] == 80.0
    assert summary["evidence"]["range_selection"] == "wider_external_pair"
    assert "anchors_too_close" not in summary["ambiguity_flags"]


def test_4h_liquidity_touch_without_acceptance_or_rejection_stays_touch_only():
    base = clear_bullish_drt_candles()
    drt = summarize_dealing_range(base)
    touch_candles = base + [
        make_candle("2026-04-18T00:00:00+00:00", 111.5, 114.4, 109.2, 113.4)
    ]

    event = detect_4h_liquidity_event(touch_candles, drt_summary=drt)

    assert event["state"] == "touched_bsl"
    assert event["interaction"] == "touched"
    assert event["narrative_hint"] == "watch"


def test_unmapped_liquidity_reference_keeps_context_at_watch():
    narrative = summarize_narrative_state(
        bias_summary={"bias": "bullish"},
        drt_summary={
            "state": "ready",
            "confidence": 0.84,
            "location": "discount",
            "spread": 20,
            "liquidity_event": {
                "state": "raid_ssl_reject",
                "level": 87,
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
        session_info={"session_valid": True, "active_session": "london"},
        bias_summary={"bias": "bullish"},
        narrative_summary=narrative,
        mss_summary={"state": "bullish_mss"},
    )

    assert narrative["liquidity_reference_alignment"]["state"] == "unmapped"
    assert context["state"] == "watch"
    assert context["execution_eligible"] is False


def test_continuation_narrative_requires_clear_4h_acceptance_not_only_mss():
    narrative = summarize_narrative_state(
        bias_summary={"bias": "bullish"},
        drt_summary={
            "state": "ready",
            "confidence": 0.82,
            "location": "premium",
            "spread": 20,
            "liquidity_event": {
                "state": "touched_bsl",
                "level": 110,
                "narrative_hint": "watch",
                "reason": "buy-side liquidity was touched but not accepted",
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

    assert narrative["state"] != "continuation"
    assert narrative["state"] in {"rejection", "developing", "unclear"}


class TestPhase8DrtNarrative(unittest.TestCase):
    def test_drt_missing_clear_external_pair_returns_unclear(self):
        test_drt_missing_clear_external_pair_returns_unclear()

    def test_drt_anchors_too_close_stays_low_confidence(self):
        test_drt_anchors_too_close_stays_low_confidence()

    def test_drt_uses_wider_preserved_pair_when_latest_pair_is_nested(self):
        test_drt_uses_wider_preserved_pair_when_latest_pair_is_nested()

    def test_4h_liquidity_touch_without_acceptance_or_rejection_stays_touch_only(self):
        test_4h_liquidity_touch_without_acceptance_or_rejection_stays_touch_only()

    def test_unmapped_liquidity_reference_keeps_context_at_watch(self):
        test_unmapped_liquidity_reference_keeps_context_at_watch()

    def test_continuation_narrative_requires_clear_4h_acceptance_not_only_mss(self):
        test_continuation_narrative_requires_clear_4h_acceptance_not_only_mss()
