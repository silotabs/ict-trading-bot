from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import server as trading_server


class PhaseFixFallbackClosedReferenceTests(unittest.TestCase):
    def test_fetch_latest_closed_reference_ms_excludes_open_candle(self):
        now_dt = datetime.now(timezone.utc).replace(microsecond=0)
        current_bar_start = now_dt - timedelta(
            minutes=now_dt.minute % 5,
            seconds=now_dt.second,
        )
        candles = []
        for offset in range(7, -1, -1):
            start_dt = current_bar_start - timedelta(minutes=5 * offset)
            candles.append(
                {
                    "start_ms": int(start_dt.timestamp() * 1000),
                    "start_at": start_dt.isoformat(),
                    "open": 100.0 + offset,
                    "high": 101.0 + offset,
                    "low": 99.0 + offset,
                    "close": 100.5 + offset,
                    "volume": 1.0,
                    "turnover": 1.0,
                }
            )

        with patch.object(trading_server, "fetch_bybit_klines", return_value={"ok": True, "candles": candles}):
            result = trading_server.fetch_latest_closed_reference_ms("BTCUSDT", interval_code="5m")

        self.assertTrue(result["ok"])
        expected_reference_dt = current_bar_start
        self.assertEqual(result["reference_ms"], int(expected_reference_dt.timestamp() * 1000))
        self.assertEqual(result["reference_at"], expected_reference_dt.isoformat())
        self.assertEqual(result["start_ms"], int((current_bar_start - timedelta(minutes=5)).timestamp() * 1000))


if __name__ == "__main__":
    unittest.main()
