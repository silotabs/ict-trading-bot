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

import server as trading_server
from ict_engine.signal_trace import build_signal_trace
from runtime_repositories import build_runtime_repositories


def minimal_context(opportunity_state="near_miss", reference_at="2026-04-19T06:30:00+00:00"):
    return {
        "reference_at": reference_at,
        "session": {"active_session": "london", "session_valid": True, "weekend": False},
        "drt_4h": {"state": "ready", "confidence": 0.82},
        "bias_4h": {"bias": "bullish"},
        "narrative": {"state": "reversal", "reason": "4H rejection supports reversal"},
        "context_summary": {
            "state": "aligned",
            "reason": "context is aligned",
            "execution_eligible": opportunity_state == "opportunity_detected",
        },
        "mss_15m": {"state": "bullish_mss", "reason": "15m MSS present"},
        "displacement_5m": {"state": "bullish", "reason": "5m displacement present"},
        "fvg_5m": {
            "state": "bullish" if opportunity_state != "awaiting_confirmation" else "none",
            "reason": "5m FVG present" if opportunity_state != "awaiting_confirmation" else "5m FVG missing",
        },
        "opportunity": {
            "state": opportunity_state,
            "reason": f"trace classified as {opportunity_state}",
        },
    }


def payload(decision="no_paper_trade", reference_at="2026-04-19T06:30:00+00:00"):
    return {
        "instrument": "BTCUSDT",
        "session": "london",
        "direction": "long",
        "reference_at": reference_at,
        "source_mode": "scanner_verified",
        "visual_analysis_state": "not_run",
        "checklist": {
            "clear_4h_bias": True,
            "clear_liquidity_draw": True,
            "liquidity_event": True,
            "mss": decision == "verified_paper_trade",
            "displacement": True,
            "fresh_fvg": decision == "verified_paper_trade",
            "clear_invalidation": True,
            "clear_target": True,
            "chase_entry": False,
        },
    }


def evaluation(decision="no_paper_trade", blockers=None):
    return {
        "decision": decision,
        "confidence": "medium",
        "setup_tag": "starter review",
        "verification": {
            "source_mode": "scanner_verified",
            "visual_analysis_state": "not_run",
        },
        "errors": [],
        "warnings": [],
        "blockers": list(blockers or []),
    }


def shadow_scan_result(decision="no_paper_trade", opportunity_state="near_miss"):
    return {
        "ok": True,
        "instrument": "BTCUSDT",
        "scan_signature": "sig-p6-shadow",
        "paper_trade_payload": payload(decision=decision),
        "paper_trade_evaluation": evaluation(
            decision=decision,
            blockers=[] if decision == "verified_paper_trade" else ["required checklist field failed: fresh_fvg"],
        ),
        "context": minimal_context(opportunity_state=opportunity_state),
    }


class PhaseP6ShadowReviewTests(unittest.TestCase):
    def test_shadow_mode_traces_are_persisted_and_queryable(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p6-shadow.db")
            with patch.object(trading_server.TradingAPIHandler, "store", store):
                with patch.object(
                    trading_server,
                    "build_bybit_heuristic_scan",
                    return_value=shadow_scan_result(decision="verified_paper_trade", opportunity_state="opportunity_detected"),
                ):
                    result = trading_server.run_watchlist_scan(
                        instruments=["BTCUSDT"],
                        category="linear",
                        auto_log_candidates=False,
                        persistent_dedupe=False,
                        record_history=False,
                        shadow_mode=True,
                        shadow_session_id="SHD-TEST-001",
                    )

            self.assertTrue(result["shadow_mode"])
            self.assertEqual(result["shadow_session_id"], "SHD-TEST-001")
            items = store.list_signal_traces(limit=10, shadow_mode=True, shadow_session_id="SHD-TEST-001")
            self.assertEqual(len(items), 1)
            self.assertTrue(items[0]["shadow_mode"])
            self.assertEqual(items[0]["shadow_session_id"], "SHD-TEST-001")

    def test_near_miss_and_awaiting_confirmation_filters_are_reliable(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p6-filters.db")
            repositories = build_runtime_repositories(store)
            repositories.signal_traces.create(
                build_signal_trace(
                    source_path="watchlist",
                    payload=payload(),
                    evaluation=evaluation(blockers=["required checklist field failed: fresh_fvg"]),
                    context=minimal_context(opportunity_state="near_miss"),
                    symbol="BTCUSDT",
                    reference_timestamp="2026-04-19T06:30:00+00:00",
                    shadow_mode=True,
                    shadow_session_id="SHD-TEST-002",
                )
            )
            repositories.signal_traces.create(
                build_signal_trace(
                    source_path="watchlist",
                    payload=payload(),
                    evaluation=evaluation(blockers=["required checklist field failed: mss"]),
                    context=minimal_context(opportunity_state="awaiting_confirmation"),
                    symbol="BTCUSDT",
                    reference_timestamp="2026-04-19T06:35:00+00:00",
                    shadow_mode=True,
                    shadow_session_id="SHD-TEST-002",
                )
            )

            near_miss = repositories.signal_traces.list(shadow_mode=True, opportunity_state="near_miss")
            awaiting = repositories.signal_traces.list(shadow_mode=True, opportunity_state="awaiting_confirmation")

            self.assertEqual(len(near_miss), 1)
            self.assertEqual(near_miss[0]["opportunity_state"], "near_miss")
            self.assertEqual(len(awaiting), 1)
            self.assertEqual(awaiting[0]["opportunity_state"], "awaiting_confirmation")

    def test_blocker_cluster_summaries_are_deterministic(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p6-summary.db")
            repositories = build_runtime_repositories(store)
            scenarios = [
                ("2026-04-19T06:30:00+00:00", "near_miss", ["required checklist field failed: fresh_fvg"]),
                ("2026-04-19T06:35:00+00:00", "near_miss", ["required checklist field failed: fresh_fvg"]),
                ("2026-04-19T06:40:00+00:00", "awaiting_confirmation", ["required checklist field failed: mss"]),
            ]
            for reference_at, opportunity_state, blockers in scenarios:
                repositories.signal_traces.create(
                    build_signal_trace(
                        source_path="watchlist",
                        payload=payload(reference_at=reference_at),
                        evaluation=evaluation(blockers=blockers),
                        context=minimal_context(opportunity_state=opportunity_state, reference_at=reference_at),
                        symbol="BTCUSDT",
                        reference_timestamp=reference_at,
                        shadow_mode=True,
                        shadow_session_id="SHD-TEST-003",
                    )
                )

            summary = repositories.signal_traces.summarize_shadow_review(
                shadow_mode=True,
                shadow_session_id="SHD-TEST-003",
                cluster_limit=5,
            )

            self.assertEqual(summary["trace_count"], 3)
            self.assertEqual(summary["blocker_clusters"][0]["reason"], "required checklist field failed: fresh_fvg")
            self.assertEqual(summary["blocker_clusters"][0]["count"], 2)
            self.assertEqual(summary["by_opportunity_state"]["near_miss"], 2)
            self.assertEqual(summary["by_opportunity_state"]["awaiting_confirmation"], 1)

    def test_shadow_mode_does_not_change_execution_eligibility(self):
        base = build_signal_trace(
            source_path="watchlist",
            payload=payload(decision="verified_paper_trade"),
            evaluation=evaluation(decision="verified_paper_trade"),
            context=minimal_context(opportunity_state="opportunity_detected"),
            symbol="BTCUSDT",
            reference_timestamp="2026-04-19T06:30:00+00:00",
            shadow_mode=False,
            shadow_session_id=None,
        )
        shadow = build_signal_trace(
            source_path="watchlist",
            payload=payload(decision="verified_paper_trade"),
            evaluation=evaluation(decision="verified_paper_trade"),
            context=minimal_context(opportunity_state="opportunity_detected"),
            symbol="BTCUSDT",
            reference_timestamp="2026-04-19T06:30:00+00:00",
            shadow_mode=True,
            shadow_session_id="SHD-TEST-004",
        )

        self.assertTrue(base["execution_eligible"])
        self.assertTrue(shadow["execution_eligible"])
        self.assertEqual(base["decision"], shadow["decision"])

    def test_verified_paper_trade_remains_the_only_execution_eligible_decision(self):
        verified = build_signal_trace(
            source_path="watchlist",
            payload=payload(decision="verified_paper_trade"),
            evaluation=evaluation(decision="verified_paper_trade"),
            context=minimal_context(opportunity_state="opportunity_detected"),
            symbol="BTCUSDT",
            reference_timestamp="2026-04-19T06:30:00+00:00",
            shadow_mode=True,
            shadow_session_id="SHD-TEST-005",
        )
        candidate = build_signal_trace(
            source_path="watchlist",
            payload=payload(decision="scanner_candidate"),
            evaluation=evaluation(decision="scanner_candidate"),
            context=minimal_context(opportunity_state="near_miss"),
            symbol="BTCUSDT",
            reference_timestamp="2026-04-19T06:35:00+00:00",
            shadow_mode=True,
            shadow_session_id="SHD-TEST-005",
        )

        self.assertTrue(verified["execution_eligible"])
        self.assertFalse(candidate["execution_eligible"])

    def test_review_summaries_do_not_require_strategy_logic_changes(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p6-review.db")
            repositories = build_runtime_repositories(store)
            repositories.signal_traces.create(
                build_signal_trace(
                    source_path="watchlist",
                    payload=payload(),
                    evaluation=evaluation(blockers=["required checklist field failed: fresh_fvg"]),
                    context=minimal_context(opportunity_state="near_miss"),
                    symbol="BTCUSDT",
                    reference_timestamp="2026-04-19T06:30:00+00:00",
                    shadow_mode=True,
                    shadow_session_id="SHD-TEST-006",
                )
            )
            summary = repositories.signal_traces.summarize_shadow_review(
                shadow_mode=True,
                shadow_session_id="SHD-TEST-006",
                only_false_negative_candidates=True,
            )

            self.assertEqual(summary["trace_count"], 1)
            self.assertEqual(summary["false_negative_candidate_count"], 1)
            self.assertEqual(summary["by_decision"]["no_paper_trade"], 1)


if __name__ == "__main__":
    unittest.main()
