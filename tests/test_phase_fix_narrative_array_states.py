from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from ict_engine.context import summarize_narrative_state


def default_liquidity_map():
    return {
        "prior_day_low": {"price": 90},
        "prior_day_high": {"price": 110},
        "asian_range_high": {"price": 104},
        "asian_range_low": {"price": 96},
        "equal_high_candidates": [],
        "equal_low_candidates": [],
        "recent_15m_swing_highs": [],
        "recent_15m_swing_lows": [],
        "recent_4h_swing_highs": [],
        "recent_4h_swing_lows": [],
    }


def continuation_drt():
    return {
        "state": "ready",
        "confidence": 0.84,
        "location": "premium",
        "spread": 20,
        "liquidity_event": {
            "state": "bsl_close_through_acceptance",
            "level": 110,
            "direction": "bullish",
            "narrative_hint": "continuation",
            "reason": "buy-side liquidity was accepted through and continuation remains open",
        },
    }


def reversal_drt():
    return {
        "state": "ready",
        "confidence": 0.84,
        "location": "discount",
        "spread": 20,
        "liquidity_event": {
            "state": "raid_ssl_reject",
            "level": 90,
            "direction": "bullish",
            "narrative_hint": "reversal",
            "reason": "sell-side liquidity was raided and rejected",
        },
    }


def narrative_for_array(respect_state):
    return summarize_narrative_state(
        bias_summary={"bias": "bullish"},
        drt_summary=continuation_drt(),
        liquidity_map=default_liquidity_map(),
        pd_arrays_summary={"lead": {"name": "BISI", "respect_state": respect_state, "ifvg_candidate": False}},
        mss_summary={"state": "bullish_mss"},
    )


def reversal_narrative_for_counter_array(respect_state, ifvg_candidate=False):
    return summarize_narrative_state(
        bias_summary={"bias": "bullish"},
        drt_summary=reversal_drt(),
        liquidity_map=default_liquidity_map(),
        pd_arrays_summary={
            "lead": {
                "name": "SIBI",
                "respect_state": respect_state,
                "ifvg_candidate": ifvg_candidate,
            }
        },
        mss_summary={"state": "bullish_mss"},
    )


class PhaseFixNarrativeArrayStatesTests(unittest.TestCase):
    def test_contested_does_not_behave_like_disrespected(self):
        contested = narrative_for_array("contested")
        disrespected = narrative_for_array("disrespected")

        self.assertEqual(contested["state"], "unclear")
        self.assertEqual(contested["array_support"], "caution")
        self.assertIn("continuation_array_contested", contested["ambiguity_flags"])
        self.assertLess(disrespected["confidence"], contested["confidence"])
        self.assertNotEqual(disrespected["array_support"], contested["array_support"])

    def test_unclear_does_not_promote_narrative(self):
        narrative = narrative_for_array("unclear")
        respected = narrative_for_array("respected")

        self.assertEqual(narrative["state"], "unclear")
        self.assertEqual(narrative["array_support"], "ambiguous")
        self.assertIn("continuation_array_ambiguous", narrative["ambiguity_flags"])
        self.assertLess(narrative["confidence"], respected["confidence"])

    def test_respected_remains_supportive(self):
        narrative = narrative_for_array("respected")

        self.assertEqual(narrative["state"], "continuation")
        self.assertEqual(narrative["array_support"], "supportive")

    def test_disrespected_remains_counter_evidence(self):
        narrative = narrative_for_array("disrespected")

        self.assertEqual(narrative["state"], "unclear")
        self.assertEqual(narrative["array_support"], "conflicted")
        self.assertIn("continuation_array_not_supportive", narrative["ambiguity_flags"])

    def test_contested_counter_array_does_not_flip_to_reversal(self):
        narrative = reversal_narrative_for_counter_array("contested")

        self.assertEqual(narrative["state"], "unclear")
        self.assertNotEqual(narrative["state"], "reversal")
        self.assertEqual(narrative["array_support"], "caution_counter")
        self.assertIn("reversal_counter_array_contested", narrative["ambiguity_flags"])

    def test_unclear_counter_array_does_not_contribute_reversal_bias(self):
        unclear = reversal_narrative_for_counter_array("unclear")
        respected_counter = reversal_narrative_for_counter_array("disrespected", ifvg_candidate=True)

        self.assertEqual(unclear["state"], "unclear")
        self.assertEqual(unclear["array_support"], "ambiguous")
        self.assertIn("reversal_counter_array_ambiguous", unclear["ambiguity_flags"])
        self.assertLess(unclear["confidence"], respected_counter["confidence"])

    def test_disrespected_counter_array_contributes_to_reversal_signal(self):
        narrative = reversal_narrative_for_counter_array("disrespected", ifvg_candidate=True)

        self.assertEqual(narrative["state"], "reversal")
        self.assertEqual(narrative["array_support"], "supportive_counter")
        self.assertEqual(narrative["evidence"]["pd_array_narrative_role"], "supportive_counter_array")


if __name__ == "__main__":
    unittest.main()
