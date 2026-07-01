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

import replay_tune
import server as trading_server


class PhaseFixReplayReportingTests(unittest.TestCase):
    @staticmethod
    def _series(step_minutes, count, *, start="2026-04-10T00:00:00+00:00", base=100.0):
        current = datetime.fromisoformat(start)
        candles = []
        for index in range(count):
            open_ = base + (index * 0.2)
            close = open_ + (0.4 if index % 2 == 0 else -0.1)
            candles.append(
                {
                    "start_ms": int(current.timestamp() * 1000),
                    "start_at": current.replace(microsecond=0).isoformat(),
                    "open": open_,
                    "high": max(open_, close) + 0.7,
                    "low": min(open_, close) - 0.7,
                    "close": close,
                    "volume": 1.0,
                    "turnover": 1.0,
                }
            )
            current += timedelta(minutes=step_minutes)
        return candles

    def test_instrument_summary_uses_verified_fields_as_primary_metrics(self):
        summary = replay_tune.instrument_summary(
            {
                "instrument": "BTCUSDT",
                "evaluated_steps": 20,
                "verified_trade_count": 3,
                "legacy_compat_trade_count": 7,
                "blocker_counts": {"required checklist field failed: displacement": 4},
                "decision_counts": {"verified_paper_trade": 3},
                "session_counts": {"london": 8},
                "direction_counts": {"long": 5},
            }
        )

        self.assertEqual(summary["verified_trade_count"], 3)
        self.assertEqual(summary["legacy_compat_trade_count"], 7)
        self.assertNotIn("paper_trade_count", summary)
        self.assertNotIn("paper_trade_ratio", summary)

    def test_instrument_summary_does_not_silently_read_paper_trade_alias(self):
        summary = replay_tune.instrument_summary(
            {
                "instrument": "BTCUSDT",
                "evaluated_steps": 20,
                "verified_trade_count": 3,
                "paper_trade_count": 7,
            }
        )

        self.assertEqual(summary["verified_trade_count"], 3)
        self.assertEqual(summary["legacy_compat_trade_count"], 0)

    def test_instrument_summary_normalizes_direction_alignment_blocker(self):
        summary = replay_tune.instrument_summary(
            {
                "instrument": "BTCUSDT",
                "evaluated_steps": 10,
                "verified_trade_count": 0,
                "blocker_counts": {"directional alignment could not be derived": 10},
            }
        )

        self.assertEqual(summary["blocker_counts"]["direction"], 10)
        self.assertAlmostEqual(summary["blocker_ratios"]["direction"], 1.0, places=4)

    def test_compare_reports_uses_verified_delta_keys(self):
        comparison = replay_tune.compare_reports(
            {
                "summaries": [
                    {
                        "instrument": "BTCUSDT",
                        "evaluated_steps": 10,
                        "verified_trade_count": 1,
                        "verified_trade_ratio": 0.1,
                        "legacy_compat_trade_count": 5,
                        "legacy_compat_trade_ratio": 0.5,
                        "blocker_ratios": {"mss": 0.4},
                    }
                ]
            },
            {
                "summaries": [
                    {
                        "instrument": "BTCUSDT",
                        "evaluated_steps": 10,
                        "verified_trade_count": 3,
                        "verified_trade_ratio": 0.3,
                        "legacy_compat_trade_count": 5,
                        "legacy_compat_trade_ratio": 0.5,
                        "blocker_ratios": {"mss": 0.2},
                    }
                ]
            },
        )

        item = comparison["instrument_deltas"][0]
        self.assertEqual(item["verified_trade_count_delta"], 2)
        self.assertAlmostEqual(item["verified_trade_ratio_delta"], 0.2, places=4)
        self.assertEqual(item["legacy_compat_trade_count_delta"], 0)
        self.assertAlmostEqual(item["legacy_compat_trade_ratio_delta"], 0.0, places=4)

    def test_replay_scan_result_uses_verified_count_without_legacy_alias(self):
        bias_candles = self._series(240, 16, start="2026-04-08T00:00:00+00:00")
        setup_candles = self._series(15, 80, start="2026-04-09T18:00:00+00:00")
        execution_candles = self._series(5, 180)

        def fake_fetch(symbol, interval, limit=200, category="linear"):
            candle_map = {
                trading_server.BYBIT_INTERVAL_MAP["4H"]: bias_candles,
                trading_server.BYBIT_INTERVAL_MAP["15m"]: setup_candles,
                trading_server.BYBIT_INTERVAL_MAP["5m"]: execution_candles,
            }
            return {"ok": True, "candles": candle_map[interval]}

        def fake_build(**kwargs):
            replay = kwargs.get("replay_metadata") or {}
            return {
                "ok": True,
                "instrument": kwargs["symbol"],
                "paper_trade_payload": {
                    "instrument": kwargs["symbol"],
                    "session": "london",
                    "direction": "long",
                },
                "paper_trade_evaluation": {
                    "decision": "verified_paper_trade",
                    "blockers": [],
                    "warnings": [],
                },
                "context": {
                    "replay": replay,
                },
                "scan_signature": "sig-replay-reporting",
            }

        with patch.object(trading_server, "fetch_bybit_klines", side_effect=fake_fetch), patch.object(
            trading_server, "build_heuristic_scan_from_market_state", side_effect=fake_build
        ), patch.object(trading_server, "persist_signal_trace_for_scan_result", return_value=None):
            result = trading_server.run_bybit_replay_scan(
                symbol="BTCUSDT",
                category="linear",
                auto_log_candidates=False,
                record_history=False,
                max_steps=1,
                step_stride=1,
                tradable_only=False,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["verified_trade_count"], 1)
        self.assertEqual(result["legacy_compat_trade_count"], 0)
        self.assertNotIn("paper_trade_count", result)

    def test_replay_scan_post_forwards_tradable_only_flag(self):
        captured = {}

        def fake_replay(**kwargs):
            captured.update(kwargs)
            return {
                "ok": True,
                "status": 200,
                "instrument": kwargs["symbol"],
                "evaluated_steps": 0,
            }

        handler = object.__new__(trading_server.TradingAPIHandler)
        responses = []

        def fake_send_json(status, payload):
            responses.append({"status": status, "payload": payload})

        handler._send_json = fake_send_json

        with patch.object(trading_server, "run_bybit_replay_scan", side_effect=fake_replay):
            handler._handle_replay_scan_post(
                {
                    "instrument": "BTCUSDT",
                    "category": "linear",
                    "max_steps": 12,
                    "step_stride": 3,
                    "tradable_only": True,
                    "record_history": False,
                }
            )

        self.assertEqual(responses[0]["status"], 200)
        self.assertIs(captured["tradable_only"], True)
        self.assertEqual(captured["max_steps"], 12)
        self.assertEqual(captured["step_stride"], 3)


if __name__ == "__main__":
    unittest.main()
