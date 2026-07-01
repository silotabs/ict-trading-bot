#!/usr/bin/env python3

import re
from pathlib import Path

from concept_briefing import clean_text


ROADMAP_PATH = Path(__file__).resolve().parents[1] / "dossier" / "13_stage_roadmap.md"
STAGE_LINE_PATTERN = re.compile(r"^### Stage (\d+):\s+(.+?)$", re.MULTILINE)
CURRENT_STAGE_PATTERN = re.compile(
    r"As of .*?project is in:\s*-\s*`Stage (\d+):\s+([^`]+)`",
    re.DOTALL,
)


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value):
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _evidence_progress_diagnostics(acceptance, acceptance_gate, compare, stage7, stage5_readiness):
    progress = acceptance.get("evidence_progress") if isinstance(acceptance.get("evidence_progress"), dict) else {}
    latest_counts = progress.get("latest_counts") if isinstance(progress.get("latest_counts"), dict) else {}
    thresholds = progress.get("thresholds") if isinstance(progress.get("thresholds"), list) else []
    gate_checks = acceptance_gate.get("checks") if isinstance(acceptance_gate.get("checks"), list) else []

    evidence_counts = {
        "recent_scans": _safe_int(latest_counts.get("recent_scans")),
        "recent_proposals": _safe_int(latest_counts.get("recent_proposals")),
        "recent_actions": _safe_int(latest_counts.get("recent_actions")),
        "recent_execution_state": _safe_int(latest_counts.get("recent_execution_state")),
        "working_orders": _safe_int(latest_counts.get("working_orders")),
        "open_positions": _safe_int(latest_counts.get("open_positions")),
    }
    artifact_counts = {
        "reviews": _safe_int(compare.get("review_count")),
        "revisions": _safe_int(compare.get("revision_count")),
        "compare_artifacts": _safe_int(compare.get("compare_artifact_count")),
        "acceptance_artifacts": _safe_int(acceptance.get("acceptance_artifact_count")),
        "stage7_artifacts": _safe_int(stage7.get("decision_artifact_count")),
    }

    missing_thresholds = []
    for item in thresholds:
        if not isinstance(item, dict):
            continue
        actual = _safe_int(item.get("actual"))
        required = _safe_int(item.get("required"))
        if required > 0 and actual < required:
            missing_thresholds.append(
                {
                    "key": clean_text(item.get("key")) or "unknown",
                    "label": clean_text(item.get("label")) or clean_text(item.get("key")) or "unknown",
                    "actual": actual,
                    "required": required,
                }
            )

    failed_checks = [
        {
            "key": clean_text(item.get("key")) or "unknown",
            "label": clean_text(item.get("label")) or clean_text(item.get("blocker_label")) or "unknown",
            "detail": clean_text(item.get("detail")),
            "required_for_stage7": bool(item.get("required_for_stage7")),
        }
        for item in gate_checks
        if isinstance(item, dict) and not item.get("ok")
    ]

    missing_artifacts = [
        {"key": key, "actual": actual, "required": 1}
        for key, actual in artifact_counts.items()
        if actual < 1
    ]

    no_qualifying_runtime_evidence = not any(evidence_counts.values())
    no_concept_artifacts = not any(artifact_counts.values())
    stage5_ready = bool(stage5_readiness.get("ready_for_stage_6_from_daemon_state"))

    if no_qualifying_runtime_evidence and no_concept_artifacts:
        signal = "no_qualifying_evidence_recorded"
        explanation = (
            "The database has no recent scans, proposals, actions, execution-state records, "
            "or saved concept review artifacts for the stage gate to evaluate."
        )
    elif not stage5_ready:
        signal = "stage5_guidance_not_ready"
        explanation = (
            clean_text(stage5_readiness.get("summary"))
            or "The compare-guidance gate has not produced a stable Stage 5 readiness signal yet."
        )
    elif missing_thresholds:
        signal = "evidence_thresholds_unmet"
        explanation = (
            "Stage 6 has started, but the minimum proposal, action, or execution-state "
            "thresholds are still below policy."
        )
    elif missing_artifacts:
        signal = "concept_artifacts_missing"
        explanation = "Runtime evidence exists, but saved review, revision, compare, acceptance, or Stage 7 artifacts are still missing."
    elif failed_checks:
        signal = clean_text(failed_checks[0].get("key")) or "stage_gate_check_failed"
        explanation = clean_text(failed_checks[0].get("detail")) or "A stage-gate check is still failing."
    else:
        signal = "stage_gate_ready"
        explanation = "The stage gate has enough recorded evidence and artifacts for the next decision step."

    return {
        "operational_signal": signal,
        "explanation": explanation,
        "evidence_counts": evidence_counts,
        "artifact_counts": artifact_counts,
        "missing_thresholds": missing_thresholds,
        "missing_artifacts": missing_artifacts,
        "failed_checks": failed_checks,
        "stage5_ready": stage5_ready,
        "progress_summary": clean_text(progress.get("progress_summary")),
    }


def parse_stage_roadmap(roadmap_path=None):
    path = Path(roadmap_path or ROADMAP_PATH)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    current_match = CURRENT_STAGE_PATTERN.search(text)
    current_stage_number = int(current_match.group(1)) if current_match else None
    current_stage_label = clean_text(current_match.group(2)) if current_match else None

    stage_titles = []
    for number, label in STAGE_LINE_PATTERN.findall(text):
        stage_titles.append(
            {
                "number": int(number),
                "label": clean_text(label) or f"Stage {number}",
            }
        )

    next_stage = None
    if current_stage_number is not None:
        for item in stage_titles:
            if item["number"] > current_stage_number:
                next_stage = item
                break

    return {
        "path": str(path),
        "current_stage_number": current_stage_number,
        "current_stage_label": current_stage_label,
        "stage_titles": stage_titles,
        "next_stage": next_stage,
    }


def build_concept_stage_status(acceptance_summary, stage7_summary, compare_summary, roadmap_path=None):
    roadmap = parse_stage_roadmap(roadmap_path=roadmap_path)
    current_stage_number = roadmap.get("current_stage_number") or 6
    current_stage_label = roadmap.get("current_stage_label") or "Concept Proof / Acceptance Testing"
    next_stage = roadmap.get("next_stage")

    acceptance = acceptance_summary if isinstance(acceptance_summary, dict) else {}
    acceptance_gate = acceptance.get("acceptance_gate") if isinstance(acceptance.get("acceptance_gate"), dict) else {}
    stage7 = stage7_summary if isinstance(stage7_summary, dict) else {}
    stage7_gate = stage7.get("stage7_gate") if isinstance(stage7.get("stage7_gate"), dict) else {}
    compare = compare_summary if isinstance(compare_summary, dict) else {}
    stage5_readiness = compare.get("stage5_readiness") if isinstance(compare.get("stage5_readiness"), dict) else {}

    compare_artifact_count = _safe_int(compare.get("compare_artifact_count"))
    acceptance_artifact_count = _safe_int(acceptance.get("acceptance_artifact_count"))
    decision_artifact_count = _safe_int(stage7.get("decision_artifact_count"))
    leader_revision_id = clean_text(((compare.get("best_ranked_revision") or {}).get("revision_id")))
    leader_status = clean_text(((compare.get("best_ranked_revision") or {}).get("status")))
    latest_compare_verdict = clean_text(((compare.get("latest_compare_artifact") or {}).get("verdict")))
    latest_stage7_verdict = clean_text(stage7.get("latest_stage7_verdict"))
    candidate_ratio = _safe_float(((acceptance_gate.get("metrics") or {}).get("candidate_ratio")))
    diagnostics = _evidence_progress_diagnostics(acceptance, acceptance_gate, compare, stage7, stage5_readiness)

    engineering_lane_complete = bool(
        stage5_readiness.get("ready_for_stage_6_from_daemon_state")
        and compare_artifact_count > 0
        and acceptance_artifact_count > 0
        and decision_artifact_count > 0
    )

    if current_stage_number == 6:
        ready_for_next = bool(stage7_gate.get("ready_for_stage_7"))
        blockers = list(stage7_gate.get("blockers") or acceptance_gate.get("blockers") or [])
        if ready_for_next:
            status = "ready_for_stage_7_decision"
            summary = clean_text(stage7_gate.get("summary")) or "Stage 6 has accumulated enough proof to open a conservative Stage 7 memo."
        elif diagnostics.get("operational_signal") == "no_qualifying_evidence_recorded":
            status = "no_qualifying_evidence_recorded"
            summary = clean_text(diagnostics.get("explanation")) or "No qualifying runtime evidence has been recorded yet."
        else:
            status = "active_waiting_for_evidence"
            summary = clean_text(stage7_gate.get("summary")) or clean_text(acceptance.get("takeaway")) or "Stage 6 is active and still waiting on more evidence."
    elif current_stage_number == 7:
        ready_for_next = False
        blockers = []
        status = "stage_7_active"
        summary = clean_text(stage7.get("decision_takeaway")) or "Stage 7 decision support is active."
    else:
        ready_for_next = False
        blockers = []
        status = "tracked"
        summary = clean_text(acceptance.get("takeaway")) or "Live stage status is being tracked."

    return {
        "roadmap_path": roadmap.get("path"),
        "current_stage": {
            "number": current_stage_number,
            "label": current_stage_label,
        },
        "next_stage": next_stage,
        "status": status,
        "summary": summary,
        "ready_for_next_stage": ready_for_next,
        "blockers": blockers,
        "current_focus": clean_text(diagnostics.get("operational_signal"))
        or clean_text(stage7_gate.get("suggested_path"))
        or clean_text(acceptance_gate.get("next_action"))
        or clean_text(compare.get("next_action"))
        or "collect_more_evidence",
        "engineering_lane_complete": engineering_lane_complete,
        "evidence_is_primary_constraint": bool(engineering_lane_complete and current_stage_number == 6 and not ready_for_next),
        "diagnostics": diagnostics,
        "metrics": {
            "candidate_ratio": candidate_ratio,
            "compare_artifact_count": compare_artifact_count,
            "acceptance_artifact_count": acceptance_artifact_count,
            "decision_artifact_count": decision_artifact_count,
            "leader_revision_id": leader_revision_id,
            "leader_status": leader_status,
            "latest_compare_verdict": latest_compare_verdict,
            "latest_stage7_verdict": latest_stage7_verdict,
        },
    }
