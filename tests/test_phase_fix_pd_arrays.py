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

from ict_engine.pd_arrays import summarize_execution_pd_arrays


def make_candle(start_at, open_, high, low, close):
    return {
        "start_at": start_at,
        "open": float(open_),
        "high": float(high),
        "low": float(low),
        "close": float(close),
    }


def build_5m_series(values, start="2026-04-18T00:00:00+00:00"):
    current = datetime.fromisoformat(start)
    candles = []
    for open_, high, low, close in values:
        candles.append(make_candle(current.replace(microsecond=0).isoformat(), open_, high, low, close))
        current += timedelta(minutes=5)
    return candles


def bullish_fvg():
    return {
        "state": "bullish",
        "lower": 100.0,
        "upper": 103.0,
        "midpoint": 101.5,
        "at": "2026-04-18T00:10:00+00:00",
    }


def bearish_fvg():
    return {
        "state": "bearish",
        "lower": 100.0,
        "upper": 103.0,
        "midpoint": 101.5,
        "at": "2026-04-18T00:10:00+00:00",
    }


def range_summary():
    return {"high": 120.0, "low": 90.0, "midpoint": 105.0}


def test_inside_zone_closes_do_not_auto_mark_disrespected():
    summary = summarize_execution_pd_arrays(
        range_summary=range_summary(),
        execution_candles=build_5m_series(
            [
                (105.6, 106.2, 102.6, 102.8),
                (102.8, 103.1, 101.7, 101.9),
                (101.9, 102.4, 101.2, 101.5),
            ]
        ),
        fvg_summary=bullish_fvg(),
    )

    assert summary["lead"]["respect_state"] == "contested"
    assert summary["lead"]["disrespect_evidence"]["kind"] == "inside_zone_churn"
    assert summary["lead"]["ifvg_candidate"] is False


def test_bearish_inside_zone_closes_do_not_auto_mark_disrespected():
    summary = summarize_execution_pd_arrays(
        range_summary=range_summary(),
        execution_candles=build_5m_series(
            [
                (98.8, 100.4, 98.3, 100.2),
                (100.2, 101.2, 99.9, 100.8),
                (100.8, 102.7, 100.5, 102.3),
            ]
        ),
        fvg_summary=bearish_fvg(),
    )

    assert summary["lead"]["respect_state"] == "contested"
    assert summary["lead"]["disrespect_evidence"]["kind"] == "inside_zone_churn"
    assert summary["lead"]["ifvg_candidate"] is False


def test_no_array_interaction_remains_unclear():
    summary = summarize_execution_pd_arrays(
        range_summary=range_summary(),
        execution_candles=build_5m_series(
            [
                (106.0, 107.0, 105.4, 106.6),
                (106.6, 107.4, 106.1, 107.0),
            ]
        ),
        fvg_summary=bullish_fvg(),
    )

    assert summary["lead"]["respect_state"] == "unclear"
    assert summary["lead"]["disrespect_evidence"]["kind"] == "none"
    assert summary["lead"]["ifvg_candidate"] is False


def test_close_beyond_far_boundary_marks_disrespected():
    summary = summarize_execution_pd_arrays(
        range_summary=range_summary(),
        execution_candles=build_5m_series(
            [
                (106.0, 107.0, 105.4, 106.5),
                (106.5, 107.2, 103.8, 104.4),
                (104.4, 104.9, 99.1, 99.6),
            ]
        ),
        fvg_summary=bullish_fvg(),
    )

    assert summary["lead"]["respect_state"] == "disrespected"
    assert summary["lead"]["disrespect_evidence"]["kind"] == "body_close_through"
    assert summary["lead"]["ifvg_candidate"] is True


def test_repeated_outside_acceptance_can_produce_ifvg_candidacy():
    summary = summarize_execution_pd_arrays(
        range_summary=range_summary(),
        execution_candles=build_5m_series(
            [
                (99.8, 101.0, 99.4, 99.7),
                (99.7, 100.1, 99.0, 99.5),
                (99.5, 100.0, 98.8, 99.4),
            ]
        ),
        fvg_summary=bullish_fvg(),
    )

    assert summary["lead"]["respect_state"] == "disrespected"
    assert summary["lead"]["disrespect_evidence"]["kind"] == "repeated_outside_acceptance_without_rejection"
    assert summary["lead"]["disrespect_evidence"]["count"] == 3
    assert summary["lead"]["ifvg_candidate"] is True


def test_wick_defense_remains_respected():
    summary = summarize_execution_pd_arrays(
        range_summary=range_summary(),
        execution_candles=build_5m_series(
            [
                (97.5, 103.6, 97.2, 99.7),
                (99.7, 102.6, 99.3, 100.1),
                (100.1, 100.8, 99.4, 100.0),
            ]
        ),
        fvg_summary=bearish_fvg(),
    )

    assert summary["lead"]["respect_state"] == "respected"
    assert summary["lead"]["respect_evidence"]["kind"] == "wick_defense"
    assert summary["lead"]["ifvg_candidate"] is False


class TestPhaseFixPdArrays(unittest.TestCase):
    def test_inside_zone_closes_do_not_auto_mark_disrespected(self):
        test_inside_zone_closes_do_not_auto_mark_disrespected()

    def test_bearish_inside_zone_closes_do_not_auto_mark_disrespected(self):
        test_bearish_inside_zone_closes_do_not_auto_mark_disrespected()

    def test_no_array_interaction_remains_unclear(self):
        test_no_array_interaction_remains_unclear()

    def test_close_beyond_far_boundary_marks_disrespected(self):
        test_close_beyond_far_boundary_marks_disrespected()

    def test_repeated_outside_acceptance_can_produce_ifvg_candidacy(self):
        test_repeated_outside_acceptance_can_produce_ifvg_candidacy()

    def test_wick_defense_remains_respected(self):
        test_wick_defense_remains_respected()
