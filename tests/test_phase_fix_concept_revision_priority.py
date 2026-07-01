from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from concept_briefing import build_concept_brief_packet
from concept_revision import build_concept_revision_plan


def base_review():
    return {
        "overall": "collecting",
        "recommendation": "collect_more_evidence",
        "evidence": {
            "recent_scan_count": 50,
            "recent_proposal_count": 0,
            "recent_action_count": 0,
            "recent_execution_state_count": 0,
        },
    }


def revise_decision():
    return {
        "policy": {"concept_id": "concept-1"},
        "overall": "revise",
        "recommendation": "revise_concept",
        "operator_signal": "revise_concept",
        "operator_summary": "Revise Concept 1 now.",
        "evidence": {
            "recent_scan_count": 50,
            "recent_proposal_count": 0,
            "recent_action_count": 0,
            "recent_execution_state_count": 0,
        },
        "unmet_evidence": [
            {"metric": "recent_proposal_count", "actual": 0, "required": 2},
            {"metric": "recent_action_count", "actual": 0, "required": 2},
            {"metric": "recent_execution_state_count", "actual": 0, "required": 2},
        ],
        "candidate_ratio": 0.0,
        "dominant_blocker": {"blocker": "displacement", "ratio": 0.625},
        "largest_gap": {
            "blocker": "liquidity_event",
            "gap": 1.0,
            "highest": {"instrument": "ETHUSDT", "ratio": 1.0},
            "lowest": {"instrument": "BTCUSDT", "ratio": 0.0},
            "ratios": {"BTCUSDT": 0.0, "ETHUSDT": 1.0},
        },
        "issues": [],
        "next_focus": ["The concept now has enough evidence to justify a rules revision."],
    }


class PhaseFixConceptRevisionPriorityTests(unittest.TestCase):
    def test_revise_decision_prioritizes_rule_review_before_evidence_collection(self):
        brief = build_concept_brief_packet(base_review(), revise_decision())

        candidate_ids = [item["id"] for item in brief["revision_candidates"]]
        self.assertEqual(candidate_ids[0], "review-cross-market-bias")
        self.assertEqual(candidate_ids[1], "review-displacement")
        self.assertEqual(candidate_ids[2], "collect-evidence-first")
        self.assertEqual(brief["revision_candidates"][2]["readiness"], "later")

        plan = build_concept_revision_plan(brief, source="test", author="test")
        self.assertEqual(plan["focus"], "liquidity_event")
        self.assertEqual(plan["mode"], "review")
        self.assertIn("cross-market", plan["title"].lower())

    def test_collecting_decision_still_keeps_evidence_first(self):
        decision = revise_decision()
        decision["overall"] = "collecting"
        decision["recommendation"] = "collect_more_evidence"
        decision["operator_signal"] = "collect_more_evidence"

        brief = build_concept_brief_packet(base_review(), decision)

        self.assertEqual(brief["revision_candidates"][0]["id"], "collect-evidence-first")
        self.assertEqual(brief["revision_candidates"][0]["readiness"], "now")


if __name__ == "__main__":
    unittest.main()
