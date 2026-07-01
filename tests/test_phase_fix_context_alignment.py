from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from ict_engine.context import summarize_context_state, summarize_narrative_state


def narrative_input(event_state, level, reason):
    return {
        "state": "ready",
        "confidence": 0.84,
        "location": "discount" if "ssl" in event_state else "premium",
        "spread": 20,
        "liquidity_event": {
            "state": event_state,
            "level": level,
            "direction": "bullish" if "ssl" in event_state or "bsl_close" in event_state else "bearish",
            "narrative_hint": "reversal" if "reject" in event_state else "continuation",
            "reason": reason,
        },
    }


def supportive_reversal_array():
    return {"lead": {"name": "SIBI", "respect_state": "disrespected", "ifvg_candidate": True}}


def supportive_bearish_reversal_array():
    return {"lead": {"name": "BISI", "respect_state": "disrespected", "ifvg_candidate": True}}


def supportive_continuation_array():
    return {"lead": {"name": "BISI", "respect_state": "respected", "ifvg_candidate": False}}


def summarize_context(liquidity_map, *, event_state, level, bias="bullish", pd_arrays_summary=None):
    narrative = summarize_narrative_state(
        bias_summary={"bias": bias},
        drt_summary=narrative_input(event_state, level, "house test reference alignment"),
        liquidity_map=liquidity_map,
        pd_arrays_summary=pd_arrays_summary or supportive_reversal_array(),
        mss_summary={"state": "bullish_mss" if bias == "bullish" else "bearish_mss"},
    )
    context = summarize_context_state(
        session_info={"session_valid": True, "active_session": "london"},
        bias_summary={"bias": bias},
        narrative_summary=narrative,
        mss_summary={"state": "bullish_mss" if bias == "bullish" else "bearish_mss"},
    )
    return narrative, context


def empty_liquidity_map():
    return {
        "prior_day_high": {"price": None},
        "prior_day_low": {"price": None},
        "asian_range_high": {"price": None},
        "asian_range_low": {"price": None},
        "equal_high_candidates": [],
        "equal_low_candidates": [],
        "recent_15m_swing_highs": [],
        "recent_15m_swing_lows": [],
        "recent_4h_swing_highs": [],
        "recent_4h_swing_lows": [],
    }


def test_recent_4h_extreme_can_map_context_when_primary_references_absent():
    liquidity_map = empty_liquidity_map()
    liquidity_map["recent_4h_swing_lows"] = [{"price": 90.0, "at": "2026-04-18T00:00:00+00:00", "index": 3}]

    narrative, context = summarize_context(
        liquidity_map,
        event_state="raid_ssl_reject",
        level=90.0,
    )

    assert narrative["liquidity_reference_alignment"]["state"] == "aligned"
    assert narrative["liquidity_reference_alignment"]["reference_tier"] == "secondary"
    assert context["state"] == "aligned"


def test_equal_highs_and_lows_support_alignment_without_promoting_full_alignment():
    liquidity_map = empty_liquidity_map()
    liquidity_map["equal_low_candidates"] = [{"price": 90.0, "count": 2, "members": []}]

    narrative, context = summarize_context(
        liquidity_map,
        event_state="raid_ssl_reject",
        level=90.0,
    )

    assert narrative["liquidity_reference_alignment"]["state"] == "aligned"
    assert narrative["liquidity_reference_alignment"]["reference_tier"] == "supporting"
    assert context["state"] == "aligned"


def test_recent_15m_extreme_maps_context_when_primary_and_secondary_missing():
    liquidity_map = empty_liquidity_map()
    liquidity_map["recent_15m_swing_lows"] = [{"price": 90.0, "at": "2026-04-18T01:15:00+00:00", "index": 8}]

    narrative, context = summarize_context(
        liquidity_map,
        event_state="raid_ssl_reject",
        level=90.0,
    )

    assert narrative["liquidity_reference_alignment"]["state"] == "aligned"
    assert narrative["liquidity_reference_alignment"]["reference_tier"] == "supporting"
    assert narrative["liquidity_reference_alignment"]["matched_supporting_references"] == ["recent_15m_swing_low"]
    assert context["state"] == "aligned"


def test_supporting_references_do_not_override_contradictory_primary_references():
    liquidity_map = empty_liquidity_map()
    liquidity_map["prior_day_low"] = {"price": 84.0}
    liquidity_map["prior_day_high"] = {"price": 110.0}
    liquidity_map["equal_low_candidates"] = [{"price": 90.0, "count": 3, "members": []}]

    narrative, context = summarize_context(
        liquidity_map,
        event_state="raid_ssl_reject",
        level=90.0,
    )

    assert narrative["liquidity_reference_alignment"]["state"] == "supporting_only"
    assert narrative["liquidity_reference_alignment"]["cannot_promote_alignment_alone"] is True
    assert context["state"] == "watch"


def test_asian_range_remains_assumption_grade_and_non_overriding():
    liquidity_map = empty_liquidity_map()
    liquidity_map["asian_range_low"] = {
        "price": 96.0,
        "status": "starter_assumption",
        "assumption_grade": "starter_assumption",
        "assumption_reason": "Asian range uses the configured starter window until the house rules pin a different definition",
        "cannot_promote_alignment_alone": True,
    }

    narrative, context = summarize_context(
        liquidity_map,
        event_state="raid_ssl_reject",
        level=96.0,
    )

    assert narrative["liquidity_reference_alignment"]["state"] == "assumption_only"
    assert narrative["liquidity_reference_alignment"]["assumption_grade"] == "starter_assumption"
    assert context["state"] == "watch"


def test_primary_reference_overrides_matching_weaker_references():
    liquidity_map = empty_liquidity_map()
    liquidity_map["prior_day_low"] = {"price": 90.0}
    liquidity_map["recent_4h_swing_lows"] = [{"price": 90.0, "at": "2026-04-18T00:00:00+00:00", "index": 3}]
    liquidity_map["equal_low_candidates"] = [{"price": 90.0, "count": 2, "members": []}]
    liquidity_map["asian_range_low"] = {
        "price": 90.0,
        "status": "starter_assumption",
        "assumption_grade": "starter_assumption",
        "assumption_reason": "Asian range uses the configured starter window until the house rules pin a different definition",
        "cannot_promote_alignment_alone": True,
    }

    narrative, context = summarize_context(
        liquidity_map,
        event_state="raid_ssl_reject",
        level=90.0,
    )

    alignment = narrative["liquidity_reference_alignment"]
    assert alignment["state"] == "aligned"
    assert alignment["reference_tier"] == "primary"
    assert alignment["matched_verified_references"] == ["prior_day_low"]
    assert alignment["matched_secondary_references"] == ["recent_4h_swing_low"]
    assert alignment["matched_supporting_references"] == ["equal_low_candidate"]
    assert alignment["matched_assumption_references"] == ["asian_range_low"]
    assert context["state"] == "aligned"


def test_asian_range_does_not_override_secondary_reference():
    liquidity_map = empty_liquidity_map()
    liquidity_map["recent_4h_swing_lows"] = [{"price": 90.0, "at": "2026-04-18T00:00:00+00:00", "index": 3}]
    liquidity_map["asian_range_low"] = {
        "price": 90.0,
        "status": "starter_assumption",
        "assumption_grade": "starter_assumption",
        "assumption_reason": "Asian range uses the configured starter window until the house rules pin a different definition",
        "cannot_promote_alignment_alone": True,
    }

    narrative, context = summarize_context(
        liquidity_map,
        event_state="raid_ssl_reject",
        level=90.0,
    )

    alignment = narrative["liquidity_reference_alignment"]
    assert alignment["state"] == "aligned"
    assert alignment["reference_tier"] == "secondary"
    assert alignment["matched_secondary_references"] == ["recent_4h_swing_low"]
    assert alignment["matched_assumption_references"] == ["asian_range_low"]
    assert context["state"] == "aligned"


def test_internal_range_liquidity_event_promotes_context_alignment():
    liquidity_map = empty_liquidity_map()
    liquidity_map["prior_day_high"] = {"price": 120.0}
    liquidity_map["prior_day_low"] = {"price": 80.0}
    drt_summary = narrative_input(
        "raid_bsl_reject",
        108.0,
        "latest 4H candle raided internal buy-side liquidity and closed back below it",
    )
    drt_summary["internal_liquidity"] = {"high": 108.0, "low": 92.0}
    drt_summary["liquidity_event"]["liquidity_tier"] = "internal"
    drt_summary["liquidity_event"]["reference_role"] = "internal_range_liquidity"

    narrative = summarize_narrative_state(
        bias_summary={"bias": "bearish"},
        drt_summary=drt_summary,
        liquidity_map=liquidity_map,
        pd_arrays_summary=supportive_bearish_reversal_array(),
        mss_summary={"state": "bearish_mss"},
    )
    context = summarize_context_state(
        session_info={"session_valid": True, "active_session": "london"},
        bias_summary={"bias": "bearish"},
        narrative_summary=narrative,
        mss_summary={"state": "bearish_mss"},
    )

    alignment = narrative["liquidity_reference_alignment"]
    assert narrative["state"] == "reversal"
    assert alignment["state"] == "aligned"
    assert alignment["reference_tier"] == "internal"
    assert alignment["matched_internal_references"] == ["internal_range_high"]
    assert context["state"] == "aligned"


def test_internal_range_liquidity_requires_explicit_internal_event_metadata():
    liquidity_map = empty_liquidity_map()
    liquidity_map["prior_day_high"] = {"price": 120.0}
    liquidity_map["prior_day_low"] = {"price": 80.0}
    drt_summary = narrative_input(
        "raid_bsl_reject",
        108.0,
        "house test reference alignment",
    )
    drt_summary["internal_liquidity"] = {"high": 108.0, "low": 92.0}

    narrative = summarize_narrative_state(
        bias_summary={"bias": "bearish"},
        drt_summary=drt_summary,
        liquidity_map=liquidity_map,
        pd_arrays_summary=supportive_bearish_reversal_array(),
        mss_summary={"state": "bearish_mss"},
    )
    context = summarize_context_state(
        session_info={"session_valid": True, "active_session": "london"},
        bias_summary={"bias": "bearish"},
        narrative_summary=narrative,
        mss_summary={"state": "bearish_mss"},
    )

    assert narrative["liquidity_reference_alignment"]["state"] == "unmapped"
    assert context["state"] == "watch"


class TestPhaseFixContextAlignment(unittest.TestCase):
    def test_recent_4h_extreme_can_map_context_when_primary_references_absent(self):
        test_recent_4h_extreme_can_map_context_when_primary_references_absent()

    def test_equal_highs_and_lows_support_alignment_without_promoting_full_alignment(self):
        test_equal_highs_and_lows_support_alignment_without_promoting_full_alignment()

    def test_recent_15m_extreme_maps_context_when_primary_and_secondary_missing(self):
        test_recent_15m_extreme_maps_context_when_primary_and_secondary_missing()

    def test_supporting_references_do_not_override_contradictory_primary_references(self):
        test_supporting_references_do_not_override_contradictory_primary_references()

    def test_asian_range_remains_assumption_grade_and_non_overriding(self):
        test_asian_range_remains_assumption_grade_and_non_overriding()

    def test_primary_reference_overrides_matching_weaker_references(self):
        test_primary_reference_overrides_matching_weaker_references()

    def test_asian_range_does_not_override_secondary_reference(self):
        test_asian_range_does_not_override_secondary_reference()

    def test_internal_range_liquidity_event_promotes_context_alignment(self):
        test_internal_range_liquidity_event_promotes_context_alignment()

    def test_internal_range_liquidity_requires_explicit_internal_event_metadata(self):
        test_internal_range_liquidity_requires_explicit_internal_event_metadata()
