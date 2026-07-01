from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from ict_engine.evaluation import evaluate_payload
import server as trading_server


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
        evaluated_at=lambda: "2026-04-27T00:00:00+00:00",
    )


def base_payload():
    return {
        "instrument": "BTCUSDT",
        "session": "london",
        "direction": "",
        "source_mode": "scanner_verified",
        "visual_analysis_state": "verified",
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


class PhaseFixDirectionBlockerTests(unittest.TestCase):
    def test_direction_blocker_remains_when_direction_is_the_only_missing_piece(self):
        result = evaluate(base_payload())

        self.assertIn("directional alignment could not be derived", result["blockers"])

    def test_direction_blocker_is_suppressed_when_checklist_failures_already_explain_the_miss(self):
        payload = base_payload()
        payload["checklist"]["mss"] = False
        payload["checklist"]["fresh_fvg"] = False

        result = evaluate(payload)

        self.assertNotIn("directional alignment could not be derived", result["blockers"])
        self.assertIn("required checklist field failed: mss", result["blockers"])
        self.assertIn("required checklist field failed: fresh_fvg", result["blockers"])

    def test_low_confidence_drt_fails_4h_bias_instead_of_direction(self):
        payload = base_payload()
        payload["checklist"]["clear_4h_bias"] = trading_server.has_clear_4h_bias(
            {"bias": "bullish", "drt": {"state": "low_confidence", "confidence": 0.714}}
        )

        result = evaluate(payload)

        self.assertNotIn("directional alignment could not be derived", result["blockers"])
        self.assertIn("required checklist field failed: clear_4h_bias", result["blockers"])


if __name__ == "__main__":
    unittest.main()
