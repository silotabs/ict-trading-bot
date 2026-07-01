from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import server as trading_server


class PhaseFixDirectionDerivationTests(unittest.TestCase):
    def test_clear_4h_bias_requires_ready_drt_state(self):
        self.assertTrue(
            trading_server.has_clear_4h_bias(
                {"bias": "bullish", "drt": {"state": "ready", "confidence": 0.82}}
            )
        )
        self.assertFalse(
            trading_server.has_clear_4h_bias(
                {"bias": "bullish", "drt": {"state": "low_confidence", "confidence": 0.71}}
            )
        )

    def test_strong_premise_can_publish_long_direction_before_full_execution_gate(self):
        direction = trading_server.derive_setup_direction(
            {"bias": "bullish"},
            {"state": "reversal"},
            {"premise_strength": "strong", "execution_eligible": False},
            {"state": "none"},
            {"state": "bullish"},
            {"state": "none"},
        )

        self.assertEqual(direction, "long")

    def test_watch_grade_premise_keeps_direction_unset(self):
        direction = trading_server.derive_setup_direction(
            {"bias": "bullish"},
            {"state": "reversal"},
            {"premise_strength": "watch", "execution_eligible": False},
            {"state": "none"},
            {"state": "bullish"},
            {"state": "none"},
        )

        self.assertEqual(direction, "")

    def test_conflicting_lower_timeframe_state_keeps_direction_unset(self):
        direction = trading_server.derive_setup_direction(
            {"bias": "bullish"},
            {"state": "continuation"},
            {"premise_strength": "strong", "execution_eligible": False},
            {"state": "bearish_mss"},
            {"state": "bullish"},
            {"state": "bullish"},
        )

        self.assertEqual(direction, "")


if __name__ == "__main__":
    unittest.main()
