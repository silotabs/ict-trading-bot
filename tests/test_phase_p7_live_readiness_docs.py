from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)


README_PATH = REPO_ROOT / "paper_api" / "README.md"
CHECKLIST_PATH = REPO_ROOT / "dossier" / "19_live_readiness_checklist.md"
FRAMEWORK_PATH = REPO_ROOT / "dossier" / "20_go_no_go_framework.md"
METRICS_PATH = REPO_ROOT / "dossier" / "21_shadow_metrics_requirements.md"
RUNBOOK_PATH = REPO_ROOT / "dossier" / "22_incident_and_rollback_runbook.md"
ROLLOUT_PLAN_PATH = REPO_ROOT / "dossier" / "23_phased_rollout_plan.md"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_live_readiness_docs_exist_and_are_linked():
    readme = read_text(README_PATH)

    for path in (CHECKLIST_PATH, FRAMEWORK_PATH, METRICS_PATH, RUNBOOK_PATH):
        assert path.exists(), f"missing live-readiness doc: {path.name}"
        assert path.name in readme


def test_live_readiness_docs_do_not_claim_live_enablement():
    combined = "\n".join(
        read_text(path)
        for path in (README_PATH, CHECKLIST_PATH, FRAMEWORK_PATH, METRICS_PATH, RUNBOOK_PATH)
    ).lower()

    assert "does not add live trading" in combined
    assert "does not widen execution eligibility" in combined
    assert "planning only" in combined
    assert "live trading approved" not in combined
    assert "live deployment is approved" not in combined


def test_live_readiness_docs_capture_required_blockers_and_controls():
    checklist = read_text(CHECKLIST_PATH).lower()
    metrics = read_text(METRICS_PATH).lower()
    runbook = read_text(RUNBOOK_PATH).lower()

    assert "shadow-mode evidence gates" in checklist
    assert "read-after-write consistency" in checklist
    assert "operator emergency stop" in checklist
    assert "max daily realized loss" in checklist
    assert "immediate post-write empty-read" in checklist

    assert "duplicate handled-close rate" in metrics
    assert "unexplained empty-read anomalies" in metrics
    assert "verified_paper_trade" in metrics

    assert "rollback steps" in runbook
    assert "read-after-write anomaly procedure" in runbook
    assert "reconciliation failure procedure" in runbook


def test_go_no_go_framework_defaults_to_hold_for_more_shadow_evidence():
    framework = read_text(FRAMEWORK_PATH)

    assert "`no_go`" in framework
    assert "`hold_for_more_shadow_evidence`" in framework
    assert "`ready_for_controlled_live_planning`" in framework
    assert "default standing should remain" in framework
    assert "`hold_for_more_shadow_evidence`" in framework


def test_phased_rollout_plan_remains_planning_only():
    plan = read_text(ROLLOUT_PLAN_PATH)
    normalized = plan.lower()

    assert "it is a planning document only." in normalized
    assert "it does not authorize live trading." in normalized
    assert "this phase still does not authorize live trading." in normalized
    assert "until that separate plan is approved, the system remains paper / daemon or testnet only." in normalized

    assert "the current default standing remains:\n\n- `hold_for_more_shadow_evidence`" in normalized
    assert "use this sequence when deciding whether to move from `hold_for_more_shadow_evidence`" in normalized

    equivalence = (
        "`ready_for_live_planning` is equivalent to the planning-only state named "
        "`ready_for_controlled_live_planning`"
    )
    assert equivalence in plan

    approval_marker = "- live trading is approved"
    assert f"this state does not mean:\n\n{approval_marker}" in normalized
    assert normalized.count(approval_marker) == 1
    assert "live trading approved" not in normalized
    assert "live deployment is approved" not in normalized
    assert "broker-facing live execution is approved" not in normalized


class TestPhase7LiveReadinessDocs(unittest.TestCase):
    def test_live_readiness_docs_exist_and_are_linked(self):
        test_live_readiness_docs_exist_and_are_linked()

    def test_live_readiness_docs_do_not_claim_live_enablement(self):
        test_live_readiness_docs_do_not_claim_live_enablement()

    def test_live_readiness_docs_capture_required_blockers_and_controls(self):
        test_live_readiness_docs_capture_required_blockers_and_controls()

    def test_go_no_go_framework_defaults_to_hold_for_more_shadow_evidence(self):
        test_go_no_go_framework_defaults_to_hold_for_more_shadow_evidence()

    def test_phased_rollout_plan_remains_planning_only(self):
        test_phased_rollout_plan_remains_planning_only()
