from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from concept_stage_status import build_concept_stage_status


def acceptance_summary_with_progress(*, scans=0, proposals=0, actions=0, execution=0):
    return {
        "acceptance_artifact_count": 0,
        "takeaway": "Stage 6 is still waiting on more evidence.",
        "evidence_progress": {
            "progress_summary": f"scans={scans} proposals={proposals} actions={actions} execution={execution}",
            "latest_counts": {
                "recent_scans": scans,
                "recent_proposals": proposals,
                "recent_actions": actions,
                "recent_execution_state": execution,
                "working_orders": 0,
                "open_positions": 0,
            },
            "thresholds": [
                {"key": "recent_proposal_count", "label": "proposals", "actual": proposals, "required": 2},
                {"key": "recent_action_count", "label": "actions", "actual": actions, "required": 2},
                {"key": "recent_execution_state_count", "label": "execution", "actual": execution, "required": 2},
            ],
        },
        "acceptance_gate": {
            "checks": [
                {
                    "key": "stage5_ready",
                    "label": "Stage 5 daemon guidance is operationally stable",
                    "ok": False,
                    "required_for_stage7": True,
                    "detail": "No stable daemon guidance yet.",
                },
                {
                    "key": "evidence_thresholds_met",
                    "label": "concept evidence thresholds are met",
                    "ok": proposals >= 2 and actions >= 2 and execution >= 2,
                    "required_for_stage7": True,
                    "detail": "Evidence thresholds are still unmet.",
                },
            ],
            "metrics": {"candidate_ratio": 0.0},
            "blockers": ["Stage 5 daemon guidance is not yet operationally stable"],
            "next_action": "Keep collecting fresh evidence until the minimum thresholds are met.",
        },
    }


def compare_summary(*, stage5_ready=False, compare_artifacts=0, reviews=0, revisions=0):
    return {
        "compare_artifact_count": compare_artifacts,
        "review_count": reviews,
        "revision_count": revisions,
        "stage5_readiness": {
            "ready_for_stage_6_from_daemon_state": stage5_ready,
            "summary": "Stage 5 ready." if stage5_ready else "Stage 5 has no qualifying daemon evidence yet.",
        },
    }


def stage7_summary(*, ready=False):
    return {
        "decision_artifact_count": 0,
        "stage7_gate": {
            "ready_for_stage_7": ready,
            "blockers": ["Stage 6 gate is still blocking Stage 7"] if not ready else [],
            "suggested_path": "keep_collecting_evidence",
        },
    }


class PhaseP13OperationalSignalTests(unittest.TestCase):
    def test_fresh_empty_database_reports_no_qualifying_evidence(self):
        status = build_concept_stage_status(
            acceptance_summary_with_progress(),
            stage7_summary(),
            compare_summary(),
        )

        self.assertEqual(status["status"], "no_qualifying_evidence_recorded")
        self.assertEqual(status["current_focus"], "no_qualifying_evidence_recorded")
        self.assertEqual(status["diagnostics"]["operational_signal"], "no_qualifying_evidence_recorded")
        self.assertEqual(status["diagnostics"]["evidence_counts"]["recent_scans"], 0)
        self.assertEqual(status["diagnostics"]["artifact_counts"]["compare_artifacts"], 0)

    def test_partial_runtime_evidence_reports_missing_thresholds_not_generic_collection(self):
        acceptance = acceptance_summary_with_progress(scans=20, proposals=1, actions=0, execution=0)
        acceptance["acceptance_gate"]["checks"][0]["ok"] = True
        status = build_concept_stage_status(
            acceptance,
            stage7_summary(),
            compare_summary(stage5_ready=True, compare_artifacts=1, reviews=1, revisions=1),
        )

        self.assertEqual(status["status"], "active_waiting_for_evidence")
        self.assertEqual(status["current_focus"], "evidence_thresholds_unmet")
        self.assertEqual(status["diagnostics"]["operational_signal"], "evidence_thresholds_unmet")
        self.assertEqual(
            [item["key"] for item in status["diagnostics"]["missing_thresholds"]],
            ["recent_proposal_count", "recent_action_count", "recent_execution_state_count"],
        )


if __name__ == "__main__":
    unittest.main()
