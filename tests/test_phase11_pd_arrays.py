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


def test_phase11_pd_array_translation_marks_location_and_liquidity_relation():
    summary = summarize_execution_pd_arrays(
        range_summary={"high": 110.0, "low": 90.0, "midpoint": 100.0},
        execution_candles=build_5m_series(
            [
                (104.0, 105.0, 103.5, 104.5),
                (104.5, 105.2, 104.1, 104.8),
                (104.8, 105.5, 104.2, 105.1),
            ]
        ),
        fvg_summary={
            "state": "bullish",
            "lower": 92.0,
            "upper": 95.0,
            "midpoint": 93.5,
            "at": "2026-04-18T00:10:00+00:00",
        },
    )

    lead = summary["lead"]
    assert lead["name"] == "BISI"
    assert lead["location"] == "discount"
    assert lead["range_relation"] == "internal"
    assert lead["liquidity_relation"] == "closer_to_sell_side_liquidity"


def test_phase11_respect_model_distinguishes_wick_defense_from_body_close_through():
    wick_defense = summarize_execution_pd_arrays(
        range_summary={"high": 120.0, "low": 90.0, "midpoint": 105.0},
        execution_candles=build_5m_series(
            [
                (106.0, 107.0, 105.4, 106.5),
                (106.5, 107.2, 103.8, 104.4),
                (104.4, 105.6, 101.9, 104.1),
            ]
        ),
        fvg_summary={
            "state": "bullish",
            "lower": 100.0,
            "upper": 103.0,
            "midpoint": 101.5,
            "at": "2026-04-18T00:10:00+00:00",
        },
    )
    close_through = summarize_execution_pd_arrays(
        range_summary={"high": 120.0, "low": 90.0, "midpoint": 105.0},
        execution_candles=build_5m_series(
            [
                (106.0, 107.0, 105.4, 106.5),
                (106.5, 107.2, 103.8, 104.4),
                (104.4, 104.9, 99.1, 99.6),
            ]
        ),
        fvg_summary={
            "state": "bullish",
            "lower": 100.0,
            "upper": 103.0,
            "midpoint": 101.5,
            "at": "2026-04-18T00:10:00+00:00",
        },
    )

    assert wick_defense["lead"]["respect_state"] == "respected"
    assert wick_defense["lead"]["respect_evidence"]["kind"] == "wick_defense"
    assert wick_defense["lead"]["disrespect_evidence"]["kind"] == "none"

    assert close_through["lead"]["respect_state"] == "disrespected"
    assert close_through["lead"]["disrespect_evidence"]["kind"] == "body_close_through"
    assert close_through["lead"]["ifvg_candidate"] is True


def test_phase11_inside_zone_churn_marks_array_contested_not_disrespected():
    summary = summarize_execution_pd_arrays(
        range_summary={"high": 120.0, "low": 90.0, "midpoint": 105.0},
        execution_candles=build_5m_series(
            [
                (105.6, 106.2, 102.6, 102.8),
                (102.8, 103.1, 101.7, 101.9),
                (101.9, 102.4, 101.2, 101.5),
            ]
        ),
        fvg_summary={
            "state": "bullish",
            "lower": 100.0,
            "upper": 103.0,
            "midpoint": 101.5,
            "at": "2026-04-18T00:10:00+00:00",
        },
    )

    lead = summary["lead"]
    assert lead["respect_state"] == "contested"
    assert lead["disrespect_evidence"]["kind"] == "inside_zone_churn"
    assert lead["disrespect_evidence"]["count"] == 3
    assert lead["ifvg_candidate"] is False


class TestPhase11PdArrays(unittest.TestCase):
    def test_phase11_pd_array_translation_marks_location_and_liquidity_relation(self):
        test_phase11_pd_array_translation_marks_location_and_liquidity_relation()

    def test_phase11_respect_model_distinguishes_wick_defense_from_body_close_through(self):
        test_phase11_respect_model_distinguishes_wick_defense_from_body_close_through()

    def test_phase11_inside_zone_churn_marks_array_contested_not_disrespected(self):
        test_phase11_inside_zone_churn_marks_array_contested_not_disrespected()
