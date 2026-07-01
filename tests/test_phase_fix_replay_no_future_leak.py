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


def make_candle(start, open_, high, low, close):
    start = start.astimezone(timezone.utc).replace(microsecond=0)
    return {
        "start_ms": int(start.timestamp() * 1000),
        "start_at": start.isoformat(),
        "open": float(open_),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": 1.0,
        "turnover": 1.0,
    }


def build_series(step_minutes, count, *, start="2026-04-20T00:00:00+00:00", base=100.0):
    current = datetime.fromisoformat(start)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    candles = []
    for index in range(count):
        open_ = base + index * 0.2
        close = open_ + (0.35 if index % 2 == 0 else -0.15)
        candles.append(
            make_candle(
                current,
                open_,
                max(open_, close) + 0.8,
                min(open_, close) - 0.8,
                close,
            )
        )
        current += timedelta(minutes=step_minutes)
    return candles


class PhaseFixReplayNoFutureLeakTests(unittest.TestCase):
    def test_replay_does_not_fallback_to_future_execution_candles(self):
        bias_candles = build_series(240, 80, start="2026-04-17T00:00:00+00:00")
        setup_candles = build_series(15, 160, start="2026-04-19T18:00:00+00:00")
        execution_candles = build_series(5, 70)
        captured = []

        def fake_fetch(_symbol, interval, limit=200, category="linear"):
            return {
                "ok": True,
                "candles": {
                    trading_server.BYBIT_INTERVAL_MAP["4H"]: bias_candles,
                    trading_server.BYBIT_INTERVAL_MAP["15m"]: setup_candles,
                    trading_server.BYBIT_INTERVAL_MAP["5m"]: execution_candles,
                }[interval],
            }

        def fake_build(**kwargs):
            replay = kwargs["replay_metadata"]
            reference_ms = int(replay["reference_ms"])
            interval_ms = trading_server.BYBIT_INTERVAL_MINUTES[trading_server.BYBIT_INTERVAL_MAP["5m"]] * 60 * 1000
            execution_slice = kwargs["execution_candles"]
            assert len(execution_slice) >= 30
            assert all(candle["start_ms"] + interval_ms <= reference_ms for candle in execution_slice)
            assert execution_slice[-1]["start_ms"] + interval_ms == reference_ms
            captured.append(replay)
            return {
                "ok": True,
                "instrument": kwargs["symbol"],
                "context": {"replay": replay},
                "paper_trade_payload": {
                    "instrument": kwargs["symbol"],
                    "session": "london",
                    "direction": "",
                },
                "paper_trade_evaluation": {
                    "decision": "no_paper_trade",
                    "blockers": [],
                    "warnings": [],
                },
                "scan_signature": "no-future-leak",
            }

        with patch.object(trading_server, "fetch_bybit_klines", side_effect=fake_fetch), patch.object(
            trading_server, "build_heuristic_scan_from_market_state", side_effect=fake_build
        ), patch.object(trading_server, "persist_signal_trace_for_scan_result", return_value=None):
            result = trading_server.run_bybit_replay_scan(
                symbol="BTCUSDT",
                category="linear",
                max_steps=1,
                step_stride=1,
                tradable_only=False,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["evaluated_steps"], 1)
        self.assertEqual(len(captured), 1)
        self.assertGreaterEqual(captured[0]["execution_index"], 29)


if __name__ == "__main__":
    unittest.main()
