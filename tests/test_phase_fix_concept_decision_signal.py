from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import stackctl


def concept_decision_args():
    return type(
        "Args",
        (),
        {"policy_path": str(PAPER_API_DIR / "config" / "concept_decision_policy.json")},
    )()


def concept_review_args():
    return concept_decision_args()


def overfiltered_review(*, scans=50):
    return {
        "overall": "collecting",
        "recommendation": "collect_more_evidence",
        "state_dir": "/tmp/trading-stack",
        "db_path": "/tmp/paper-trading.db",
        "evidence": {
            "recent_scan_count": scans,
            "recent_proposal_count": 0,
            "recent_action_count": 0,
            "recent_execution_state_count": 0,
            "working_order_count": 0,
            "open_position_count": 0,
        },
        "scan_mix": {"no_paper_trade": scans},
        "auto_execution_top_blocker": {},
        "wave4_review": {
            "next_focus": [
                "No scanner-verified replay candidates passed in the sampled window.",
                "Displacement is blocking most replay steps.",
            ],
            "replay_tuning": {
                "gap_report": {"blocker_gaps": []},
                "summaries": [
                    {
                        "instrument": "BTCUSDT",
                        "evaluated_steps": 12,
                        "verified_trade_count": 0,
                        "decision_counts": {"no_paper_trade": 12},
                        "blocker_ratios": {"displacement": 0.8333, "mss": 0.4167},
                    },
                    {
                        "instrument": "ETHUSDT",
                        "evaluated_steps": 12,
                        "verified_trade_count": 0,
                        "decision_counts": {"no_paper_trade": 12},
                        "blocker_ratios": {"displacement": 0.8333, "mss": 0.6667},
                    },
                ],
            },
        },
    }


def wave4_review_with_replay_pressure(*, scans=50):
    return {
        "ok": False,
        "overall": "watch",
        "recommendation": "continue_burnin",
        "state_dir": "/tmp/trading-stack",
        "db_path": "/tmp/paper-trading.db",
        "counts": {"error": 0, "warning": 2, "info": 2},
        "burnin_gate": {
            "overall": "watch",
            "issues": [],
            "report": {
                "manifest": {"items": []},
                "runtimes": {"concept_lab": []},
                "recent_concept_events": [],
                "recent_scan_history": [
                    {"scan_id": f"scan-{index}", "decision": "no_paper_trade"}
                    for index in range(scans)
                ],
                "recent_proposals": [],
                "recent_execution_actions": [],
                "recent_execution_state": [],
                "recent_auto_execution_events": [],
            },
        },
        "replay_tuning": {
            "gap_report": {"blocker_gaps": []},
            "summaries": [
                {
                    "instrument": "BTCUSDT",
                    "evaluated_steps": 12,
                    "verified_trade_count": 0,
                    "decision_counts": {"no_paper_trade": 12},
                    "blocker_ratios": {"clear_4h_bias": 0.8333, "displacement": 0.4167},
                },
                {
                    "instrument": "ETHUSDT",
                    "evaluated_steps": 12,
                    "verified_trade_count": 0,
                    "decision_counts": {"no_paper_trade": 12},
                    "blocker_ratios": {"clear_4h_bias": 0.8333, "displacement": 0.4167},
                },
            ],
        },
        "issues": [],
        "next_focus": [
            "No scanner-verified replay candidates passed in the sampled window.",
        ],
    }


def cross_market_gap_review(*, scans=50):
    review = overfiltered_review(scans=scans)
    review["wave4_review"]["replay_tuning"] = {
        "gap_report": {
            "blocker_gaps": [
                {
                    "blocker": "liquidity_event",
                    "gap": 1.0,
                    "highest": {"instrument": "ETHUSDT", "ratio": 1.0},
                    "lowest": {"instrument": "BTCUSDT", "ratio": 0.0},
                    "ratios": {"BTCUSDT": 0.0, "ETHUSDT": 1.0},
                }
            ]
        },
        "summaries": [
            {
                "instrument": "BTCUSDT",
                "evaluated_steps": 12,
                "verified_trade_count": 0,
                "decision_counts": {"no_paper_trade": 12},
                "blocker_ratios": {"displacement": 0.4167, "liquidity_event": 0.0, "mss": 0.3333},
            },
            {
                "instrument": "ETHUSDT",
                "evaluated_steps": 12,
                "verified_trade_count": 0,
                "decision_counts": {"no_paper_trade": 12},
                "blocker_ratios": {"displacement": 0.4167, "liquidity_event": 1.0, "mss": 0.3333},
            },
        ],
    }
    return review


def direction_alignment_review(*, scans=50):
    review = overfiltered_review(scans=scans)
    review["wave4_review"]["replay_tuning"] = {
        "gap_report": {"blocker_gaps": []},
        "summaries": [
            {
                "instrument": "BTCUSDT",
                "evaluated_steps": 12,
                "verified_trade_count": 0,
                "decision_counts": {"no_paper_trade": 12},
                "blocker_ratios": {"direction": 1.0, "displacement": 0.4167, "mss": 0.3333},
            },
            {
                "instrument": "ETHUSDT",
                "evaluated_steps": 12,
                "verified_trade_count": 0,
                "decision_counts": {"no_paper_trade": 12},
                "blocker_ratios": {"direction": 1.0, "displacement": 0.4167, "mss": 0.3333},
            },
        ],
    }
    return review


def four_hour_bias_review(*, scans=50):
    review = overfiltered_review(scans=scans)
    review["wave4_review"]["replay_tuning"] = {
        "gap_report": {"blocker_gaps": []},
        "summaries": [
            {
                "instrument": "BTCUSDT",
                "evaluated_steps": 12,
                "verified_trade_count": 0,
                "decision_counts": {"no_paper_trade": 12},
                "blocker_ratios": {"clear_4h_bias": 0.8333, "displacement": 0.4167},
            },
            {
                "instrument": "ETHUSDT",
                "evaluated_steps": 12,
                "verified_trade_count": 0,
                "decision_counts": {"no_paper_trade": 12},
                "blocker_ratios": {"clear_4h_bias": 0.8333, "displacement": 0.4167},
            },
        ],
    }
    return review


class PhaseFixConceptDecisionSignalTests(unittest.TestCase):
    def test_mature_overfiltered_sample_signals_revision_not_more_waiting(self):
        with patch.object(stackctl, "concept_review", return_value=overfiltered_review(scans=50)):
            result = stackctl.concept_decision(concept_decision_args())

        codes = {item["code"]: item for item in result["issues"]}
        self.assertEqual(result["overall"], "revise")
        self.assertEqual(result["recommendation"], "revise_concept")
        self.assertEqual(result["operator_signal"], "revise_concept")
        self.assertIn("displacement", result["operator_summary"])
        self.assertIn("concept_scan_evidence_mature_but_overfiltered", codes)
        self.assertIn("Lifecycle evidence", codes["concept_evidence_below_threshold"]["summary"])

    def test_mature_cross_market_gap_signals_revision_not_more_waiting(self):
        with patch.object(stackctl, "concept_review", return_value=cross_market_gap_review(scans=50)):
            result = stackctl.concept_decision(concept_decision_args())

        codes = {item["code"]: item for item in result["issues"]}
        self.assertEqual(result["overall"], "revise")
        self.assertEqual(result["recommendation"], "revise_concept")
        self.assertEqual(result["operator_signal"], "revise_concept")
        self.assertIn("liquidity_event", result["operator_summary"])
        self.assertIn("BTC/ETH", result["operator_summary"])
        self.assertIn("concept_scan_evidence_mature_but_overfiltered", codes)
        self.assertIn("visible rule pressure", codes["concept_evidence_below_threshold"]["summary"])
        self.assertNotIn("keep collecting data before judging", codes["concept_evidence_below_threshold"]["summary"])

    def test_immature_scan_sample_still_collects_more_evidence(self):
        with patch.object(stackctl, "concept_review", return_value=overfiltered_review(scans=5)):
            result = stackctl.concept_decision(concept_decision_args())

        self.assertEqual(result["overall"], "collecting")
        self.assertEqual(result["operator_signal"], "collect_more_evidence")

    def test_direction_alignment_can_become_dominant_revision_blocker(self):
        with patch.object(stackctl, "concept_review", return_value=direction_alignment_review(scans=50)):
            result = stackctl.concept_decision(concept_decision_args())

        self.assertEqual(result["overall"], "revise")
        self.assertEqual(result["dominant_blocker"]["blocker"], "direction")
        self.assertEqual(result["operator_signal"], "revise_concept")
        self.assertIn("direction alignment", result["operator_summary"])

    def test_4h_bias_clarity_can_become_dominant_revision_blocker(self):
        with patch.object(stackctl, "concept_review", return_value=four_hour_bias_review(scans=50)):
            result = stackctl.concept_decision(concept_decision_args())

        self.assertEqual(result["overall"], "revise")
        self.assertEqual(result["dominant_blocker"]["blocker"], "clear_4h_bias")
        self.assertEqual(result["operator_signal"], "revise_concept")
        self.assertIn("4H bias clarity", result["operator_summary"])

    def test_concept_review_surfaces_mature_replay_revision_pressure(self):
        with patch.object(stackctl, "wave4_review", return_value=wave4_review_with_replay_pressure(scans=50)):
            result = stackctl.concept_review(concept_review_args())

        codes = {item["code"]: item for item in result["issues"]}
        self.assertEqual(result["overall"], "collecting")
        self.assertEqual(result["recommendation"], "revise_concept")
        self.assertEqual(result["operator_signal"], "revise_concept")
        self.assertIn("4H bias clarity", result["operator_summary"])
        self.assertIn("concept_replay_revision_pressure", codes)

    def test_concept_review_keeps_collecting_when_replay_sample_is_immature(self):
        with patch.object(stackctl, "wave4_review", return_value=wave4_review_with_replay_pressure(scans=5)):
            result = stackctl.concept_review(concept_review_args())

        self.assertEqual(result["overall"], "collecting")
        self.assertEqual(result["recommendation"], "collect_more_evidence")
        self.assertEqual(result["operator_signal"], "collect_more_evidence")


if __name__ == "__main__":
    unittest.main()
