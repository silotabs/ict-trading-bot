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
    }


def test_phase12_continuation_requires_accepted_4h_event_and_supportive_array():
    narrative = summarize_narrative_state(
        bias_summary={"bias": "bullish"},
        drt_summary={
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
        },
        liquidity_map=default_liquidity_map(),
        pd_arrays_summary={"lead": {"name": "BISI", "respect_state": "respected", "ifvg_candidate": False}},
        mss_summary={"state": "bullish_mss"},
    )

    assert narrative["state"] == "continuation"
    assert narrative["array_support"] == "supportive"
    assert narrative["ambiguity_flags"] == []
    assert narrative["evidence"]["pd_array_narrative_role"] == "supportive_array"


def test_phase12_reversal_requires_rejected_4h_event_and_supportive_counter_array():
    narrative = summarize_narrative_state(
        bias_summary={"bias": "bullish"},
        drt_summary={
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
        },
        liquidity_map=default_liquidity_map(),
        pd_arrays_summary={"lead": {"name": "SIBI", "respect_state": "disrespected", "ifvg_candidate": True}},
        mss_summary={"state": "bullish_mss"},
    )

    assert narrative["state"] == "reversal"
    assert narrative["array_support"] == "supportive_counter"
    assert narrative["ambiguity_flags"] == []
    assert narrative["evidence"]["pd_array_narrative_role"] == "supportive_counter_array"


def test_phase12_conflicted_event_and_array_evidence_returns_unclear_with_ambiguity_flags():
    narrative = summarize_narrative_state(
        bias_summary={"bias": "bullish"},
        drt_summary={
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
        },
        liquidity_map=default_liquidity_map(),
        pd_arrays_summary={"lead": {"name": "SIBI", "respect_state": "disrespected", "ifvg_candidate": True}},
        mss_summary={"state": "bullish_mss"},
    )

    assert narrative["state"] == "unclear"
    assert "continuation_array_direction_conflict" in narrative["ambiguity_flags"]
    assert "continuation_counter_array_conflict" in narrative["ambiguity_flags"]
    assert narrative["array_support"] == "conflicted"


class TestPhase12NarrativeGate(unittest.TestCase):
    def test_phase12_continuation_requires_accepted_4h_event_and_supportive_array(self):
        test_phase12_continuation_requires_accepted_4h_event_and_supportive_array()

    def test_phase12_reversal_requires_rejected_4h_event_and_supportive_counter_array(self):
        test_phase12_reversal_requires_rejected_4h_event_and_supportive_counter_array()

    def test_phase12_conflicted_event_and_array_evidence_returns_unclear_with_ambiguity_flags(self):
        test_phase12_conflicted_event_and_array_evidence_returns_unclear_with_ambiguity_flags()
