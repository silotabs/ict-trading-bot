from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from ict_engine.execution import detect_recent_mss_15m


MSS_CONFIG = {
    "sample_size": 24,
    "break_confirm_bars": 3,
    "level_tolerance_fraction": 0.12,
    "micro_break_lookback": 3,
    "micro_break_search_bars": 6,
    "micro_break_follow_through_bars": 2,
}


def candle_series(rows):
    current = datetime(2026, 4, 25, 0, 0, tzinfo=timezone.utc)
    candles = []
    for open_, high, low, close in rows:
        candles.append(
            {
                "start_at": current.replace(microsecond=0).isoformat(),
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
            }
        )
        current += timedelta(minutes=15)
    return candles


def bullish_break_then_retrace_rows(*, invalidated=False):
    tail_close = 91.0 if invalidated else 101.0
    return [
        (97, 100, 95, 98),
        (98, 101, 96, 99),
        (100, 104, 97, 101),
        (99, 102, 94, 95),
        (94, 101, 92, 93),
        (94, 103, 93, 101),
        (101, 105, 96, 104.6),
        (104, 104.5, 98, 101),
        (101, 103, 99, 100),
        (100, 102, 97, 101),
        (101, 102, 98, 100.5),
        (100.5, 101.5, 97.5, 99.5),
        (99.5, 101, 96.5, tail_close),
    ]


def test_prior_post_liquidity_mss_remains_active_until_protected_swing_breaks():
    candles = candle_series(bullish_break_then_retrace_rows())
    result = detect_recent_mss_15m(
        candles,
        expected_direction="bullish",
        after_at=candles[3]["start_at"],
        config=MSS_CONFIG,
    )

    assert result["state"] == "bullish_mss"
    assert result["active_break"] is True
    assert result["level"] == 104.0
    assert result["protected_level"] == 92.0
    assert result["at"] == candles[6]["start_at"]


def test_active_mss_memory_expires_when_protected_swing_is_lost():
    candles = candle_series(bullish_break_then_retrace_rows(invalidated=True))
    result = detect_recent_mss_15m(
        candles,
        expected_direction="bullish",
        after_at=candles[3]["start_at"],
        config=MSS_CONFIG,
    )

    assert result["state"] == "none"
    assert result["reason"] == "no aligned 15m MSS heuristic found"


class TestPhaseFixActiveMssMemory(unittest.TestCase):
    def test_prior_post_liquidity_mss_remains_active_until_protected_swing_breaks(self):
        test_prior_post_liquidity_mss_remains_active_until_protected_swing_breaks()

    def test_active_mss_memory_expires_when_protected_swing_is_lost(self):
        test_active_mss_memory_expires_when_protected_swing_is_lost()
