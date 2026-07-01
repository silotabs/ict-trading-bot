from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from ict_engine.evaluation import decision_allows_execution_plan
from ict_engine.opportunity import summarize_opportunity_state
import server as trading_server


def phase_p2_scan_result(
    *,
    decision="no_paper_trade",
    session="london",
    session_valid=True,
    direction="long",
    blockers=None,
    narrative_state="reversal",
    narrative_reason="4H liquidity rejection implies reversal",
    context_state="aligned",
    context_reason="higher-timeframe premise and timing are supportive",
    premise_strength="strong",
    mss_state="bullish_mss",
    displacement_state="bullish",
    fvg_state="bullish",
):
    blockers = list(blockers or [])
    return {
        "ok": True,
        "instrument": "BTCUSDT",
        "category": "linear",
        "scan_batch_id": "WL-P2",
        "paper_trade_payload": {
            "instrument": "BTCUSDT",
            "provider": "bybit-public-api",
            "session": session,
            "direction": direction,
            "reference_at": "2026-04-19T06:30:00+00:00",
            "source_mode": "scanner_verified",
            "visual_analysis_state": "not_run",
            "timeframes": {"bias": "4H", "setup": "15m", "execution": "5m"},
            "checklist": {
                "clear_4h_bias": True,
                "clear_liquidity_draw": True,
                "liquidity_event": True,
                "mss": mss_state in {"bullish_mss", "bearish_mss"},
                "displacement": displacement_state in {"bullish", "bearish"},
                "fresh_fvg": fvg_state in {"bullish", "bearish"},
                "clear_invalidation": True,
                "clear_target": True,
                "chase_entry": False,
            },
        },
        "paper_trade_evaluation": {
            "decision": decision,
            "setup_tag": "starter invalid" if decision != "verified_paper_trade" else "starter verified",
            "confidence": "medium" if decision == "verified_paper_trade" else "low",
            "errors": [],
            "blockers": blockers,
            "warnings": [],
            "verification": {
                "source_mode": "scanner_verified",
                "visual_analysis_state": "not_run",
            },
        },
        "context": {
            "reference_at": "2026-04-19T06:30:00+00:00",
            "visual_analysis_state": "not_run",
            "session": {
                "now_utc": "2026-04-19T06:30:00+00:00",
                "active_session": session,
                "session_valid": session_valid,
                "weekend": False,
            },
            "bias_4h": {"bias": "bullish"},
            "drt_4h": {
                "state": "ready",
                "confidence": 0.84,
                "liquidity_event": {
                    "state": "raid_ssl_reject",
                    "reason": "sell-side liquidity was raided and rejected",
                },
            },
            "liquidity_event_4h": {
                "state": "raid_ssl_reject",
                "reason": "sell-side liquidity was raided and rejected",
            },
            "narrative": {
                "state": narrative_state,
                "reason": narrative_reason,
                "liquidity_reference_alignment": {
                    "state": "aligned",
                    "reason": "the active 4H liquidity event sits near verified higher-timeframe liquidity",
                },
            },
            "context_summary": {
                "state": context_state,
                "reason": context_reason,
                "premise_strength": premise_strength,
                "execution_eligible": context_state == "aligned" and mss_state in {"bullish_mss", "bearish_mss"},
            },
            "mss_15m": {"state": mss_state, "reason": "15m MSS state"},
            "displacement_5m": {"state": displacement_state, "reason": "5m displacement state"},
            "fvg_5m": {"state": fvg_state, "reason": "5m FVG state"},
            "chase_state": "not_chase",
        },
    }


def test_strong_higher_timeframe_premise_but_missing_5m_trigger_awaiting_confirmation():
    scan_result = phase_p2_scan_result(
        blockers=[
            "required checklist field failed: displacement",
            "required checklist field failed: fresh_fvg",
        ],
        displacement_state="none",
        fvg_state="none",
    )

    opportunity = summarize_opportunity_state(
        evaluation=scan_result["paper_trade_evaluation"],
        context=scan_result["context"],
    )

    assert opportunity["state"] == "awaiting_confirmation"
    assert opportunity["execution_eligible"] is False
    assert "displacement" in opportunity["missing_requirements"]
    assert "fresh_fvg" in opportunity["missing_requirements"]


def test_strong_setup_with_one_missing_execution_leg_near_miss():
    scan_result = phase_p2_scan_result(
        blockers=[
            "required checklist field failed: fresh_fvg",
        ],
        fvg_state="none",
    )

    opportunity = summarize_opportunity_state(
        evaluation=scan_result["paper_trade_evaluation"],
        context=scan_result["context"],
    )

    assert opportunity["state"] == "near_miss"
    assert opportunity["missing_requirements"] == ["fresh_fvg"]


def test_invalid_session_but_otherwise_attractive_structure_maps_to_context_watch_not_executable():
    scan_result = phase_p2_scan_result(
        session="outside",
        session_valid=False,
        blockers=["session outside is outside the allowed paper-trading windows"],
        context_state="invalid_session",
        context_reason="session timing is outside the current house window",
    )

    opportunity = summarize_opportunity_state(
        evaluation=scan_result["paper_trade_evaluation"],
        context=scan_result["context"],
    )

    assert opportunity["state"] == "context_watch"
    assert opportunity["execution_eligible"] is False
    assert decision_allows_execution_plan(scan_result["paper_trade_evaluation"]["decision"]) is False


def test_verified_paper_trade_also_maps_to_opportunity_detected_but_remains_only_execution_eligible_decision():
    scan_result = phase_p2_scan_result(
        decision="verified_paper_trade",
        blockers=[],
    )

    opportunity = summarize_opportunity_state(
        evaluation=scan_result["paper_trade_evaluation"],
        context=scan_result["context"],
    )

    assert opportunity["state"] == "opportunity_detected"
    assert opportunity["execution_eligible"] is True
    assert decision_allows_execution_plan("verified_paper_trade") is True
    assert decision_allows_execution_plan("near_miss") is False


def test_blocker_reasons_and_opportunity_state_remain_consistent():
    blockers = [
        "required checklist field failed: fresh_fvg",
    ]
    scan_result = phase_p2_scan_result(
        blockers=blockers,
        fvg_state="none",
    )

    opportunity = summarize_opportunity_state(
        evaluation=scan_result["paper_trade_evaluation"],
        context=scan_result["context"],
        blocker_reasons=blockers,
    )

    assert opportunity["state"] == "near_miss"
    assert opportunity["blocker_reasons"] == blockers
    assert "fresh_fvg" in opportunity["missing_requirements"]


def test_signal_traces_persist_opportunity_state_without_changing_trusted_baseline_decisions():
    scan_result = phase_p2_scan_result(
        blockers=[
            "required checklist field failed: fresh_fvg",
        ],
        fvg_state="none",
    )

    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p2.db")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            trace_id = trading_server.persist_signal_trace_for_scan_result(
                scan_result,
                source_path="scanner",
                category="linear",
            )
            trace = store.get_signal_trace(trace_id)["trace"]

    assert trace["decision"] == "no_paper_trade"
    assert trace["execution_eligible"] is False
    assert trace["opportunity_state"] == "near_miss"
    assert trace["details"]["opportunity"]["execution_decision"] == "no_paper_trade"
    assert "fresh_fvg" in trace["details"]["opportunity"]["missing_requirements"]
    assert trace["details"]["opportunity"]["blocker_reasons"]


class TestPhaseP2OpportunityLayer(unittest.TestCase):
    def test_strong_higher_timeframe_premise_but_missing_5m_trigger_awaiting_confirmation(self):
        test_strong_higher_timeframe_premise_but_missing_5m_trigger_awaiting_confirmation()

    def test_strong_setup_with_one_missing_execution_leg_near_miss(self):
        test_strong_setup_with_one_missing_execution_leg_near_miss()

    def test_invalid_session_but_otherwise_attractive_structure_maps_to_context_watch_not_executable(self):
        test_invalid_session_but_otherwise_attractive_structure_maps_to_context_watch_not_executable()

    def test_verified_paper_trade_also_maps_to_opportunity_detected_but_remains_only_execution_eligible_decision(self):
        test_verified_paper_trade_also_maps_to_opportunity_detected_but_remains_only_execution_eligible_decision()

    def test_blocker_reasons_and_opportunity_state_remain_consistent(self):
        test_blocker_reasons_and_opportunity_state_remain_consistent()

    def test_signal_traces_persist_opportunity_state_without_changing_trusted_baseline_decisions(self):
        test_signal_traces_persist_opportunity_state_without_changing_trusted_baseline_decisions()
