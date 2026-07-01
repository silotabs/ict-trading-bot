#!/usr/bin/env python3

import argparse
import sys
import time
from pathlib import Path
from types import SimpleNamespace

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from runtime_api import TradingAPIHandler, resolve_control_state, utc_now_iso
from concept_acceptance_briefing import summarize_concept_acceptance
from concept_briefing import build_concept_brief_packet
from concept_stage_status import build_concept_stage_status
from concept_stage7_decision_briefing import summarize_stage7_decision
from concept_revision import (
    build_stage5_readiness,
    build_concept_revision_plan,
    evaluate_concept_revision_plan,
    record_concept_revision_evaluation,
    summarize_concept_revision_loop,
)
from stackctl import (
    CONCEPT_DECISION_POLICY_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_STATE_DIR,
    clean_text,
    concept_decision,
)


TRACKED_FIELDS = (
    "overall",
    "recommendation",
    "candidate_ratio",
    "dominant_blocker",
    "operator_signal",
)


def emit(line):
    print(line, flush=True)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run a background concept lab loop that periodically evaluates Concept 1 against the current evidence thresholds."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single concept decision cycle and exit.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=300,
        help="Seconds to wait between concept decision cycles. Default: 300.",
    )
    parser.add_argument(
        "--runtime-key",
        default="default",
        help="Concept lab runtime key used for restart-safe state and event persistence. Default: default.",
    )
    parser.add_argument(
        "--disable-events",
        action="store_true",
        help="Do not persist concept lab events to SQLite.",
    )
    parser.add_argument(
        "--state-dir",
        default=str(DEFAULT_STATE_DIR),
        help=f"Directory for pid/log/manifest state. Default: {DEFAULT_STATE_DIR}",
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"SQLite path passed to the concept lab. Default: {DEFAULT_DB_PATH}",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"API host for local review helpers. Default: {DEFAULT_HOST}.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"API port for local review helpers. Default: {DEFAULT_PORT}.",
    )
    parser.add_argument(
        "--event-limit",
        type=int,
        default=25,
        help="Combined event limit. Default: 25.",
    )
    parser.add_argument(
        "--proposal-limit",
        type=int,
        default=10,
        help="Recent proposal limit. Default: 10.",
    )
    parser.add_argument(
        "--action-limit",
        type=int,
        default=10,
        help="Recent execution action limit. Default: 10.",
    )
    parser.add_argument(
        "--scan-limit",
        type=int,
        default=50,
        help="Recent scan-history limit. Default: 50.",
    )
    parser.add_argument(
        "--instruments",
        default="BTCUSDT,ETHUSDT",
        help="Comma-separated instruments to use for replay tuning. Default: BTCUSDT,ETHUSDT.",
    )
    parser.add_argument(
        "--category",
        default="linear",
        help="Bybit category for replay tuning. Default: linear.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=12,
        help="Maximum replay steps per instrument. Default: 12.",
    )
    parser.add_argument(
        "--step-stride",
        type=int,
        default=3,
        help="Stride between replay steps. Default: 3.",
    )
    parser.add_argument(
        "--tradable-only",
        action="store_true",
        help="Only evaluate replay windows that fall inside the currently allowed trading sessions.",
    )
    parser.add_argument(
        "--policy-path",
        default=str(CONCEPT_DECISION_POLICY_PATH),
        help=f"Concept decision policy JSON path. Default: {CONCEPT_DECISION_POLICY_PATH}",
    )
    return parser.parse_args()


def format_event_line(event):
    return (
        f"EVENT {event.get('severity', 'info').upper()} "
        f"{event.get('event_type', 'unknown')} | {event.get('concept_id') or '-'} | "
        f"{event.get('summary', '')}"
    )


def format_state_line(summary):
    return (
        f"{summary.get('concept_id', 'concept')} | "
        f"overall={summary.get('overall', 'unknown')} | "
        f"recommendation={summary.get('recommendation', 'unknown')} | "
        f"signal={summary.get('operator_signal', 'unknown')} | "
        f"candidate_ratio={float(summary.get('candidate_ratio') or 0.0):.0%}"
    )


def build_event(runtime_key, event_type, severity, summary, payload, concept_id=None):
    return {
        "runtime_key": runtime_key,
        "event_type": event_type,
        "severity": severity,
        "summary": summary,
        "concept_id": clean_text(concept_id),
        "payload": payload if isinstance(payload, dict) else {},
    }


def persist_events(events):
    event_ids = []
    for event in events:
        event_id = TradingAPIHandler.store.create_concept_event(
            runtime_key=event["runtime_key"],
            event_type=event["event_type"],
            severity=event["severity"],
            summary=event["summary"],
            event_payload=event["payload"],
            concept_id=event.get("concept_id"),
        )
        event_ids.append(event_id)
    return event_ids


def load_runtime_state(runtime_key):
    record = TradingAPIHandler.store.get_concept_runtime(runtime_key)
    if record is None:
        return {}, None
    state = record.get("state") if isinstance(record.get("state"), dict) else {}
    return state, record


def create_runtime_start_event(runtime_key, previous_runtime, concept_id):
    if previous_runtime is None:
        return build_event(
            runtime_key=runtime_key,
            event_type="runtime_started",
            severity="info",
            summary=f"concept lab runtime {runtime_key} started with no previous state",
            payload={"runtime_key": runtime_key},
            concept_id=concept_id,
        )
    return build_event(
        runtime_key=runtime_key,
        event_type="runtime_resumed",
        severity="info",
        summary=f"concept lab runtime {runtime_key} resumed from stored state",
        payload={
            "runtime_key": runtime_key,
            "previous_updated_at": previous_runtime.get("updated_at"),
            "previous_heartbeat_at": previous_runtime.get("heartbeat_at"),
            "previous_last_scan_at": previous_runtime.get("last_scan_at"),
        },
        concept_id=concept_id,
    )


def persist_runtime(runtime_key, runtime_state, last_summary):
    TradingAPIHandler.store.upsert_concept_runtime(
        runtime_key=runtime_key,
        state=runtime_state,
        last_summary=last_summary,
    )


def compact_state(decision):
    dominant = decision.get("dominant_blocker") if isinstance(decision.get("dominant_blocker"), dict) else {}
    return {
        "last_scan_at": utc_now_iso(),
        "overall": decision.get("overall"),
        "recommendation": decision.get("recommendation"),
        "candidate_ratio": float(decision.get("candidate_ratio") or 0.0),
        "dominant_blocker": dominant.get("blocker"),
        "dominant_blocker_ratio": float(dominant.get("ratio") or 0.0),
        "operator_signal": decision.get("operator_signal"),
        "operator_summary": decision.get("operator_summary"),
        "unmet_evidence": decision.get("unmet_evidence") or [],
        "last_error": None,
        "_control_paused": False,
    }


def build_runtime_summary(decision):
    dominant = decision.get("dominant_blocker") if isinstance(decision.get("dominant_blocker"), dict) else {}
    return {
        "scanned_at": utc_now_iso(),
        "concept_id": ((decision.get("policy") or {}).get("concept_id")) or "concept-1",
        "overall": decision.get("overall"),
        "recommendation": decision.get("recommendation"),
        "candidate_ratio": float(decision.get("candidate_ratio") or 0.0),
        "dominant_blocker": dominant.get("blocker"),
        "dominant_blocker_ratio": float(dominant.get("ratio") or 0.0),
        "operator_signal": decision.get("operator_signal"),
        "operator_summary": decision.get("operator_summary"),
        "unmet_evidence_count": len(decision.get("unmet_evidence") or []),
    }


def build_brief_from_decision(decision):
    review = decision.get("concept_review") if isinstance(decision.get("concept_review"), dict) else {}
    return build_concept_brief_packet(review, decision)


def summarize_revision_activity(results):
    items = results if isinstance(results, list) else []
    status_counts = {}
    for item in items:
        status = clean_text(item.get("status")) or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "linked_revision_count": len(items),
        "evaluated_revision_count": len([item for item in items if not item.get("skipped")]),
        "status_counts": status_counts,
        "last_sample_started_at": clean_text((items[-1].get("current_sample_started_at") if items else None)),
    }


def build_revision_loop_records(concept_id):
    review_summaries = TradingAPIHandler.store.list_concept_reviews(limit=100, concept_id=concept_id)
    review_records = [
        TradingAPIHandler.store.get_concept_review(item.get("review_id"))
        for item in review_summaries
        if clean_text(item.get("review_id"))
    ]
    review_records = [item for item in review_records if item is not None]

    revision_summaries = TradingAPIHandler.store.list_concept_revisions(limit=100, concept_id=concept_id)
    revision_records = [
        TradingAPIHandler.store.get_concept_revision(item.get("revision_id"))
        for item in revision_summaries
        if clean_text(item.get("revision_id"))
    ]
    revision_records = [item for item in revision_records if item is not None]
    return review_records, revision_records


def build_revision_compare_summary(concept_id):
    review_records, revision_records = build_revision_loop_records(concept_id)
    return summarize_concept_revision_loop(revision_records, review_records)


def compact_revision_compare_state(compare_summary):
    compare = compare_summary if isinstance(compare_summary, dict) else {}
    leader = compare.get("best_ranked_revision") if isinstance(compare.get("best_ranked_revision"), dict) else {}
    latest_compare = compare.get("latest_compare_artifact") if isinstance(compare.get("latest_compare_artifact"), dict) else {}
    return {
        "leader_revision_id": clean_text(leader.get("revision_id")),
        "leader_status": clean_text(leader.get("status")),
        "leader_score": int(leader.get("score") or 0),
        "latest_compare_review_id": clean_text(latest_compare.get("review_id")),
        "latest_compare_verdict": clean_text(latest_compare.get("verdict")),
        "compare_artifact_count": int(compare.get("compare_artifact_count") or 0),
        "leader_explanation": clean_text(compare.get("leader_explanation")),
        "compare_action": clean_text(compare.get("compare_action")),
    }


def compact_acceptance_state(acceptance_summary):
    acceptance = acceptance_summary if isinstance(acceptance_summary, dict) else {}
    latest = acceptance.get("latest_acceptance_artifact") if isinstance(acceptance.get("latest_acceptance_artifact"), dict) else {}
    gate = acceptance.get("acceptance_gate") if isinstance(acceptance.get("acceptance_gate"), dict) else {}
    progress = acceptance.get("evidence_progress") if isinstance(acceptance.get("evidence_progress"), dict) else {}
    latest_counts = progress.get("latest_counts") if isinstance(progress.get("latest_counts"), dict) else {}
    return {
        "latest_acceptance_review_id": clean_text(acceptance.get("latest_acceptance_review_id")) or clean_text(latest.get("review_id")),
        "latest_acceptance_verdict": clean_text(acceptance.get("latest_acceptance_verdict")) or clean_text(latest.get("verdict")),
        "latest_acceptance_status": clean_text(acceptance.get("latest_acceptance_status")) or clean_text(latest.get("stage6_status")) or clean_text(gate.get("status")),
        "primary_blocker": clean_text(acceptance.get("primary_blocker")) or clean_text(latest.get("primary_blocker")),
        "acceptance_artifact_count": int(acceptance.get("acceptance_artifact_count") or 0),
        "acceptance_explanation": clean_text(acceptance.get("acceptance_explanation")) or clean_text(acceptance.get("takeaway")),
        "acceptance_action": clean_text(acceptance.get("acceptance_action")) or clean_text(gate.get("next_action")),
        "ready_for_stage_7": bool(acceptance.get("ready_for_stage_7")),
        "evidence_progress": {
            "thresholds_met_count": int(progress.get("thresholds_met_count") or 0),
            "thresholds_total_count": int(progress.get("thresholds_total_count") or 0),
            "threshold_progress_ratio": float(progress.get("threshold_progress_ratio") or 0.0),
            "next_needed_metric": clean_text(progress.get("next_needed_metric")),
            "next_needed_label": clean_text(progress.get("next_needed_label")),
            "candidate_ratio": float(progress.get("candidate_ratio") or 0.0),
            "progress_summary": clean_text(progress.get("progress_summary")),
            "latest_counts": {
                "recent_scans": int(latest_counts.get("recent_scans") or 0),
                "recent_proposals": int(latest_counts.get("recent_proposals") or 0),
                "recent_actions": int(latest_counts.get("recent_actions") or 0),
                "recent_execution_state": int(latest_counts.get("recent_execution_state") or 0),
                "working_orders": int(latest_counts.get("working_orders") or 0),
                "open_positions": int(latest_counts.get("open_positions") or 0),
            },
        },
    }


def compact_stage7_state(stage7_summary):
    decision = stage7_summary if isinstance(stage7_summary, dict) else {}
    latest = decision.get("latest_stage7_artifact") if isinstance(decision.get("latest_stage7_artifact"), dict) else {}
    gate = decision.get("stage7_gate") if isinstance(decision.get("stage7_gate"), dict) else {}
    return {
        "latest_stage7_review_id": clean_text(decision.get("latest_stage7_review_id")) or clean_text(latest.get("review_id")),
        "latest_stage7_verdict": clean_text(decision.get("latest_stage7_verdict")) or clean_text(latest.get("verdict")),
        "stage7_status": clean_text(gate.get("status")) or clean_text(latest.get("stage7_readiness")),
        "primary_reason": clean_text(latest.get("primary_reason")) or clean_text(gate.get("primary_reason")),
        "decision_artifact_count": int(decision.get("decision_artifact_count") or 0),
        "decision_takeaway": clean_text(decision.get("decision_takeaway")) or clean_text(gate.get("summary")),
        "decision_action": clean_text(decision.get("decision_action")) or clean_text(gate.get("next_action")),
        "suggested_path": clean_text(gate.get("suggested_path")),
        "ready_for_stage_7": bool(gate.get("ready_for_stage_7")),
    }


def enrich_acceptance_state(previous_acceptance, current_acceptance):
    previous = previous_acceptance if isinstance(previous_acceptance, dict) else {}
    current = dict(current_acceptance or {})
    unchanged = (
        clean_text(previous.get("latest_acceptance_review_id")) == clean_text(current.get("latest_acceptance_review_id"))
        and clean_text(previous.get("latest_acceptance_verdict")) == clean_text(current.get("latest_acceptance_verdict"))
        and clean_text(previous.get("latest_acceptance_status")) == clean_text(current.get("latest_acceptance_status"))
        and clean_text(previous.get("acceptance_action")) == clean_text(current.get("acceptance_action"))
        and bool(previous.get("ready_for_stage_7")) == bool(current.get("ready_for_stage_7"))
    )
    previous_cycles = int(previous.get("stability_cycles") or 0)
    current["stability_cycles"] = previous_cycles + 1 if unchanged and previous_cycles > 0 else 1
    current["last_changed_at"] = (
        clean_text(previous.get("last_changed_at"))
        if unchanged and clean_text(previous.get("last_changed_at"))
        else utc_now_iso()
    )
    previous_progress = previous.get("evidence_progress") if isinstance(previous.get("evidence_progress"), dict) else {}
    current_progress = current.get("evidence_progress") if isinstance(current.get("evidence_progress"), dict) else {}
    previous_counts = previous_progress.get("latest_counts") if isinstance(previous_progress.get("latest_counts"), dict) else {}
    current_counts = current_progress.get("latest_counts") if isinstance(current_progress.get("latest_counts"), dict) else {}
    previous_met = int(previous_progress.get("thresholds_met_count") or 0)
    current_met = int(current_progress.get("thresholds_met_count") or 0)
    tracked_count_keys = ("recent_proposals", "recent_actions", "recent_execution_state", "recent_scans")
    progressed = current_met > previous_met or any(
        int(current_counts.get(key) or 0) > int(previous_counts.get(key) or 0)
        for key in tracked_count_keys
    )
    regressed = current_met < previous_met or any(
        int(current_counts.get(key) or 0) < int(previous_counts.get(key) or 0)
        for key in tracked_count_keys
    )
    current["progress_direction"] = "forward" if progressed else "backward" if regressed else "flat"
    previous_stalled_cycles = int(previous.get("stalled_cycles") or 0)
    current["stalled_cycles"] = (
        0
        if progressed or bool(current.get("ready_for_stage_7"))
        else previous_stalled_cycles + 1
        if previous
        else 0
    )
    current["last_progress_at"] = (
        utc_now_iso()
        if progressed or not clean_text(previous.get("last_progress_at"))
        else clean_text(previous.get("last_progress_at"))
    )
    return current


def _build_acceptance_history_entry(current_acceptance):
    current = current_acceptance if isinstance(current_acceptance, dict) else {}
    progress = current.get("evidence_progress") if isinstance(current.get("evidence_progress"), dict) else {}
    latest_counts = progress.get("latest_counts") if isinstance(progress.get("latest_counts"), dict) else {}
    return {
        "entry_key": "|".join(
            [
                clean_text(current.get("latest_acceptance_review_id")) or "-",
                clean_text(current.get("latest_acceptance_status")) or "-",
                clean_text(current.get("primary_blocker")) or "-",
                clean_text(progress.get("progress_summary")) or "-",
                clean_text(current.get("progress_direction")) or "-",
            ]
        ),
        "recorded_at": utc_now_iso(),
        "last_seen_at": utc_now_iso(),
        "cycles_seen": 1,
        "latest_acceptance_review_id": clean_text(current.get("latest_acceptance_review_id")),
        "latest_acceptance_status": clean_text(current.get("latest_acceptance_status")),
        "latest_acceptance_verdict": clean_text(current.get("latest_acceptance_verdict")),
        "primary_blocker": clean_text(current.get("primary_blocker")),
        "acceptance_action": clean_text(current.get("acceptance_action")),
        "ready_for_stage_7": bool(current.get("ready_for_stage_7")),
        "progress_direction": clean_text(current.get("progress_direction")) or "flat",
        "stalled_cycles": int(current.get("stalled_cycles") or 0),
        "last_progress_at": clean_text(current.get("last_progress_at")),
        "progress_summary": clean_text(progress.get("progress_summary")),
        "thresholds_met_count": int(progress.get("thresholds_met_count") or 0),
        "thresholds_total_count": int(progress.get("thresholds_total_count") or 0),
        "next_needed_label": clean_text(progress.get("next_needed_label")),
        "candidate_ratio": float(progress.get("candidate_ratio") or 0.0),
        "latest_counts": {
            "recent_scans": int(latest_counts.get("recent_scans") or 0),
            "recent_proposals": int(latest_counts.get("recent_proposals") or 0),
            "recent_actions": int(latest_counts.get("recent_actions") or 0),
            "recent_execution_state": int(latest_counts.get("recent_execution_state") or 0),
        },
    }


def update_acceptance_history(previous_history, current_acceptance, limit=20):
    history = [item for item in (previous_history or []) if isinstance(item, dict)]
    if not isinstance(current_acceptance, dict) or not current_acceptance:
        return history[:limit]

    entry = _build_acceptance_history_entry(current_acceptance)
    if history and clean_text(history[0].get("entry_key")) == clean_text(entry.get("entry_key")):
        updated = dict(history[0])
        updated["last_seen_at"] = entry["last_seen_at"]
        updated["cycles_seen"] = int(updated.get("cycles_seen") or 0) + 1
        updated["stalled_cycles"] = entry["stalled_cycles"]
        updated["last_progress_at"] = entry["last_progress_at"]
        updated["latest_counts"] = entry["latest_counts"]
        updated["candidate_ratio"] = entry["candidate_ratio"]
        updated["progress_summary"] = entry["progress_summary"]
        updated["thresholds_met_count"] = entry["thresholds_met_count"]
        updated["thresholds_total_count"] = entry["thresholds_total_count"]
        updated["next_needed_label"] = entry["next_needed_label"]
        updated["progress_direction"] = entry["progress_direction"]
        history[0] = updated
    else:
        history.insert(0, entry)

    return history[:limit]


def enrich_stage7_state(previous_stage7, current_stage7):
    previous = previous_stage7 if isinstance(previous_stage7, dict) else {}
    current = dict(current_stage7 or {})
    unchanged = (
        clean_text(previous.get("latest_stage7_review_id")) == clean_text(current.get("latest_stage7_review_id"))
        and clean_text(previous.get("latest_stage7_verdict")) == clean_text(current.get("latest_stage7_verdict"))
        and clean_text(previous.get("stage7_status")) == clean_text(current.get("stage7_status"))
        and clean_text(previous.get("decision_action")) == clean_text(current.get("decision_action"))
        and clean_text(previous.get("suggested_path")) == clean_text(current.get("suggested_path"))
    )
    previous_cycles = int(previous.get("stability_cycles") or 0)
    current["stability_cycles"] = previous_cycles + 1 if unchanged and previous_cycles > 0 else 1
    current["last_changed_at"] = (
        clean_text(previous.get("last_changed_at"))
        if unchanged and clean_text(previous.get("last_changed_at"))
        else utc_now_iso()
    )
    return current


def build_acceptance_event(runtime_key, concept_id, previous_acceptance, current_acceptance):
    previous = previous_acceptance if isinstance(previous_acceptance, dict) else {}
    current = current_acceptance if isinstance(current_acceptance, dict) else {}
    changes = {}
    for field in (
        "latest_acceptance_review_id",
        "latest_acceptance_verdict",
        "latest_acceptance_status",
        "primary_blocker",
        "acceptance_artifact_count",
        "acceptance_explanation",
        "acceptance_action",
        "ready_for_stage_7",
    ):
        if previous.get(field) != current.get(field):
            changes[field] = {"from": previous.get(field), "to": current.get(field)}

    if not changes:
        return None

    summary = (
        f"{concept_id} acceptance guidance updated: "
        f"{current.get('latest_acceptance_status') or 'acceptance'}"
    )
    severity = "warning" if bool(current.get("ready_for_stage_7")) else "info"
    return build_event(
        runtime_key=runtime_key,
        event_type="acceptance_updated",
        severity=severity,
        summary=summary,
        payload={
            "previous": previous,
            "current": current,
            "changes": changes,
        },
        concept_id=concept_id,
    )


def build_acceptance_transition_events(runtime_key, concept_id, previous_acceptance, current_acceptance):
    previous = previous_acceptance if isinstance(previous_acceptance, dict) else {}
    current = current_acceptance if isinstance(current_acceptance, dict) else {}
    events = []

    previous_verdict = clean_text(previous.get("latest_acceptance_verdict"))
    current_verdict = clean_text(current.get("latest_acceptance_verdict"))
    if current_verdict and current_verdict != previous_verdict:
        events.append(
            build_event(
                runtime_key=runtime_key,
                event_type="acceptance_verdict_changed",
                severity="warning" if current_verdict == "ready_for_stage_7_decision" else "info",
                summary=f"{concept_id} acceptance verdict changed to {current_verdict}",
                payload={
                    "previous_verdict": previous_verdict,
                    "current_verdict": current_verdict,
                    "stage6_status": clean_text(current.get("latest_acceptance_status")),
                    "acceptance_action": clean_text(current.get("acceptance_action")),
                },
                concept_id=concept_id,
            )
        )

    previous_status = clean_text(previous.get("latest_acceptance_status"))
    current_status = clean_text(current.get("latest_acceptance_status"))
    if current_status and current_status != previous_status:
        events.append(
            build_event(
                runtime_key=runtime_key,
                event_type="acceptance_status_changed",
                severity="warning" if current_status == "ready_for_stage_7_decision" else "info",
                summary=f"{concept_id} acceptance status changed to {current_status}",
                payload={
                    "previous_status": previous_status,
                    "current_status": current_status,
                    "primary_blocker": clean_text(current.get("primary_blocker")),
                    "acceptance_action": clean_text(current.get("acceptance_action")),
                },
                concept_id=concept_id,
            )
        )

    previous_ready = bool(previous.get("ready_for_stage_7"))
    current_ready = bool(current.get("ready_for_stage_7"))
    if current_ready and current_ready != previous_ready:
        events.append(
            build_event(
                runtime_key=runtime_key,
                event_type="acceptance_ready_for_stage_7",
                severity="warning",
                summary=f"{concept_id} acceptance loop is ready for a Stage 7 decision",
                payload={
                    "latest_acceptance_review_id": clean_text(current.get("latest_acceptance_review_id")),
                    "latest_acceptance_verdict": clean_text(current.get("latest_acceptance_verdict")),
                    "acceptance_action": clean_text(current.get("acceptance_action")),
                },
                concept_id=concept_id,
            )
        )

    previous_progress = previous.get("evidence_progress") if isinstance(previous.get("evidence_progress"), dict) else {}
    current_progress = current.get("evidence_progress") if isinstance(current.get("evidence_progress"), dict) else {}
    if previous_progress != current_progress and current_progress:
        direction = clean_text(current.get("progress_direction")) or "flat"
        events.append(
            build_event(
                runtime_key=runtime_key,
                event_type="acceptance_progress_updated",
                severity="warning" if direction == "backward" else "info",
                summary=f"{concept_id} acceptance evidence {direction}: {clean_text(current_progress.get('progress_summary')) or 'progress updated'}",
                payload={
                    "previous": previous_progress,
                    "current": current_progress,
                    "progress_direction": direction,
                    "latest_acceptance_status": clean_text(current.get("latest_acceptance_status")),
                    "stalled_cycles": int(current.get("stalled_cycles") or 0),
                    "last_progress_at": clean_text(current.get("last_progress_at")),
                },
                concept_id=concept_id,
            )
        )

    previous_stalled = int(previous.get("stalled_cycles") or 0)
    current_stalled = int(current.get("stalled_cycles") or 0)
    if (
        current_stalled >= 3
        and current_stalled != previous_stalled
        and current_stalled % 3 == 0
        and not bool(current.get("ready_for_stage_7"))
    ):
        events.append(
            build_event(
                runtime_key=runtime_key,
                event_type="acceptance_stalled",
                severity="warning",
                summary=f"{concept_id} acceptance evidence has stalled for {current_stalled} cycles",
                payload={
                    "stalled_cycles": current_stalled,
                    "latest_acceptance_status": clean_text(current.get("latest_acceptance_status")),
                    "primary_blocker": clean_text(current.get("primary_blocker")),
                    "progress_summary": clean_text(current_progress.get("progress_summary")),
                    "last_progress_at": clean_text(current.get("last_progress_at")),
                },
                concept_id=concept_id,
            )
        )

    return events


def build_stage7_event(runtime_key, concept_id, previous_stage7, current_stage7):
    previous = previous_stage7 if isinstance(previous_stage7, dict) else {}
    current = current_stage7 if isinstance(current_stage7, dict) else {}
    changes = {}
    for field in (
        "latest_stage7_review_id",
        "latest_stage7_verdict",
        "stage7_status",
        "primary_reason",
        "decision_artifact_count",
        "decision_takeaway",
        "decision_action",
        "suggested_path",
        "ready_for_stage_7",
    ):
        if previous.get(field) != current.get(field):
            changes[field] = {"from": previous.get(field), "to": current.get(field)}

    if not changes:
        return None

    summary = (
        f"{concept_id} Stage 7 guidance updated: "
        f"{current.get('stage7_status') or 'stage7'}"
    )
    severity = "warning" if clean_text(current.get("stage7_status")) == "ready_for_stage_7_decision" else "info"
    return build_event(
        runtime_key=runtime_key,
        event_type="stage7_decision_updated",
        severity=severity,
        summary=summary,
        payload={
            "previous": previous,
            "current": current,
            "changes": changes,
        },
        concept_id=concept_id,
    )


def build_stage7_transition_events(runtime_key, concept_id, previous_stage7, current_stage7):
    previous = previous_stage7 if isinstance(previous_stage7, dict) else {}
    current = current_stage7 if isinstance(current_stage7, dict) else {}
    events = []

    previous_verdict = clean_text(previous.get("latest_stage7_verdict"))
    current_verdict = clean_text(current.get("latest_stage7_verdict"))
    if current_verdict and current_verdict != previous_verdict:
        events.append(
            build_event(
                runtime_key=runtime_key,
                event_type="stage7_decision_verdict_changed",
                severity="warning" if current_verdict != "keep_collecting_evidence" else "info",
                summary=f"{concept_id} Stage 7 verdict changed to {current_verdict}",
                payload={
                    "previous_verdict": previous_verdict,
                    "current_verdict": current_verdict,
                    "stage7_status": clean_text(current.get("stage7_status")),
                    "decision_action": clean_text(current.get("decision_action")),
                },
                concept_id=concept_id,
            )
        )

    previous_status = clean_text(previous.get("stage7_status"))
    current_status = clean_text(current.get("stage7_status"))
    if current_status and current_status != previous_status:
        events.append(
            build_event(
                runtime_key=runtime_key,
                event_type="stage7_decision_status_changed",
                severity="warning" if current_status == "ready_for_stage_7_decision" else "info",
                summary=f"{concept_id} Stage 7 status changed to {current_status}",
                payload={
                    "previous_status": previous_status,
                    "current_status": current_status,
                    "primary_reason": clean_text(current.get("primary_reason")),
                    "decision_action": clean_text(current.get("decision_action")),
                },
                concept_id=concept_id,
            )
        )

    previous_ready = bool(previous.get("ready_for_stage_7"))
    current_ready = bool(current.get("ready_for_stage_7"))
    if current_ready and current_ready != previous_ready:
        events.append(
            build_event(
                runtime_key=runtime_key,
                event_type="stage7_decision_ready",
                severity="warning",
                summary=f"{concept_id} is ready for a Stage 7 memo decision",
                payload={
                    "latest_stage7_review_id": clean_text(current.get("latest_stage7_review_id")),
                    "latest_stage7_verdict": clean_text(current.get("latest_stage7_verdict")),
                    "suggested_path": clean_text(current.get("suggested_path")),
                    "decision_action": clean_text(current.get("decision_action")),
                },
                concept_id=concept_id,
            )
        )

    return events


def build_stage_status_event(runtime_key, concept_id, previous_status, current_status):
    previous = previous_status if isinstance(previous_status, dict) else {}
    current = current_status if isinstance(current_status, dict) else {}
    changes = {}
    for field in ("status", "summary", "ready_for_next_stage", "current_focus"):
        if previous.get(field) != current.get(field):
            changes[field] = {"from": previous.get(field), "to": current.get(field)}

    if not changes:
        return None

    stage_label = ((current.get("current_stage") or {}).get("label")) or "Current stage"
    summary = f"{concept_id} stage status updated: {stage_label}"
    severity = "warning" if bool(current.get("ready_for_next_stage")) else "info"
    return build_event(
        runtime_key=runtime_key,
        event_type="stage_status_updated",
        severity=severity,
        summary=summary,
        payload={
            "previous": previous,
            "current": current,
            "changes": changes,
        },
        concept_id=concept_id,
    )


def build_stage_status_transition_events(runtime_key, concept_id, previous_status, current_status):
    previous = previous_status if isinstance(previous_status, dict) else {}
    current = current_status if isinstance(current_status, dict) else {}
    events = []

    previous_ready = bool(previous.get("ready_for_next_stage"))
    current_ready = bool(current.get("ready_for_next_stage"))
    if current_ready and current_ready != previous_ready:
        next_stage = current.get("next_stage") if isinstance(current.get("next_stage"), dict) else {}
        label = clean_text(next_stage.get("label")) or "next stage"
        events.append(
            build_event(
                runtime_key=runtime_key,
                event_type="stage_ready_for_transition",
                severity="warning",
                summary=f"{concept_id} is ready for {label}",
                payload={
                    "current_stage": current.get("current_stage"),
                    "next_stage": next_stage,
                    "summary": clean_text(current.get("summary")),
                    "current_focus": clean_text(current.get("current_focus")),
                },
                concept_id=concept_id,
            )
        )

    return events


def enrich_revision_compare_state(previous_compare, current_compare):
    previous = previous_compare if isinstance(previous_compare, dict) else {}
    current = dict(current_compare or {})
    unchanged = (
        clean_text(previous.get("leader_revision_id")) == clean_text(current.get("leader_revision_id"))
        and clean_text(previous.get("latest_compare_verdict")) == clean_text(current.get("latest_compare_verdict"))
        and clean_text(previous.get("compare_action")) == clean_text(current.get("compare_action"))
    )
    previous_cycles = int(previous.get("stability_cycles") or 0)
    current["stability_cycles"] = previous_cycles + 1 if unchanged and previous_cycles > 0 else 1
    current["last_changed_at"] = (
        clean_text(previous.get("last_changed_at"))
        if unchanged and clean_text(previous.get("last_changed_at"))
        else utc_now_iso()
    )
    return current


def build_revision_compare_event(runtime_key, concept_id, previous_compare, current_compare):
    previous = previous_compare if isinstance(previous_compare, dict) else {}
    current = current_compare if isinstance(current_compare, dict) else {}
    changes = {}
    for field in (
        "leader_revision_id",
        "leader_status",
        "leader_score",
        "latest_compare_review_id",
        "latest_compare_verdict",
        "compare_artifact_count",
        "leader_explanation",
        "compare_action",
    ):
        if previous.get(field) != current.get(field):
            changes[field] = {"from": previous.get(field), "to": current.get(field)}

    if not changes:
        return None

    leader_id = current.get("leader_revision_id") or "no leader"
    verdict = current.get("latest_compare_verdict")
    if verdict:
        summary = f"{concept_id} compare guidance updated: {leader_id} / {verdict}"
    else:
        summary = f"{concept_id} revision leader updated: {leader_id}"

    severity = "info"
    if verdict == "promote_runner_up":
        severity = "warning"

    return build_event(
        runtime_key=runtime_key,
        event_type="revision_compare_updated",
        severity=severity,
        summary=summary,
        payload={
            "previous": previous,
            "current": current,
            "changes": changes,
        },
        concept_id=concept_id,
    )


def build_revision_compare_transition_events(runtime_key, concept_id, previous_compare, current_compare):
    previous = previous_compare if isinstance(previous_compare, dict) else {}
    current = current_compare if isinstance(current_compare, dict) else {}
    events = []

    previous_leader = clean_text(previous.get("leader_revision_id"))
    current_leader = clean_text(current.get("leader_revision_id"))
    if current_leader and current_leader != previous_leader:
        events.append(
            build_event(
                runtime_key=runtime_key,
                event_type="revision_leader_changed",
                severity="warning" if previous_leader else "info",
                summary=f"{concept_id} revision leader changed to {current_leader}",
                payload={
                    "previous_leader_revision_id": previous_leader,
                    "current_leader_revision_id": current_leader,
                    "leader_status": clean_text(current.get("leader_status")),
                    "leader_score": int(current.get("leader_score") or 0),
                    "leader_explanation": clean_text(current.get("leader_explanation")),
                },
                concept_id=concept_id,
            )
        )

    previous_verdict = clean_text(previous.get("latest_compare_verdict"))
    current_verdict = clean_text(current.get("latest_compare_verdict"))
    if current_verdict and current_verdict != previous_verdict:
        events.append(
            build_event(
                runtime_key=runtime_key,
                event_type="revision_compare_verdict_changed",
                severity="warning" if current_verdict == "promote_runner_up" else "info",
                summary=f"{concept_id} compare verdict changed to {current_verdict}",
                payload={
                    "previous_verdict": previous_verdict,
                    "current_verdict": current_verdict,
                    "leader_revision_id": current_leader,
                    "compare_action": clean_text(current.get("compare_action")),
                    "leader_explanation": clean_text(current.get("leader_explanation")),
                },
                concept_id=concept_id,
            )
        )

    return events


def build_revision_event(runtime_key, concept_id, revision_result):
    payload = revision_result if isinstance(revision_result, dict) else {}
    status = clean_text(payload.get("status")) or "unknown"
    revision_id = clean_text(payload.get("revision_id")) or "revision"
    review_id = clean_text(payload.get("review_id")) or "-"
    if status == "improved":
        severity = "info"
        event_type = "revision_improved"
    elif status == "regressed":
        severity = "warning"
        event_type = "revision_regressed"
    elif status == "awaiting_fresh_sample":
        severity = "info"
        event_type = "revision_waiting_for_sample"
    else:
        severity = "info"
        event_type = "revision_evaluated"
    summary = f"{revision_id} for {review_id} evaluated as {status}"
    return build_event(
        runtime_key=runtime_key,
        event_type=event_type,
        severity=severity,
        summary=summary,
        payload=payload,
        concept_id=concept_id,
    )


def build_revision_linked_event(runtime_key, concept_id, review_id, revision_id, revision_payload):
    payload = revision_payload if isinstance(revision_payload, dict) else {}
    focus = clean_text(payload.get("focus")) or "concept_observation"
    summary = f"{revision_id} auto-linked from {review_id} for {focus}"
    return build_event(
        runtime_key=runtime_key,
        event_type="revision_linked",
        severity="info",
        summary=summary,
        payload={
            "review_id": review_id,
            "revision_id": revision_id,
            "focus": focus,
            "mode": clean_text(payload.get("mode")),
            "readiness": clean_text(payload.get("readiness")),
            "summary": clean_text(payload.get("summary")),
        },
        concept_id=concept_id,
    )


def auto_link_unlinked_reviews(runtime_key, concept_id, brief):
    review_summaries = TradingAPIHandler.store.list_concept_reviews(
        limit=100,
        concept_id=concept_id,
        review_kind="llm_structured",
    )
    created = []
    events = []
    for item in review_summaries:
        review_id = clean_text(item.get("review_id"))
        if not review_id:
            continue
        if TradingAPIHandler.store.get_latest_concept_revision_for_review(review_id) is not None:
            continue
        review_record = TradingAPIHandler.store.get_concept_review(review_id)
        if review_record is None:
            continue
        revision_payload = build_concept_revision_plan(
            brief,
            review_artifact=review_record,
            source="auto_linked_review",
            author=clean_text(review_record.get("author")),
        )
        revision_id = TradingAPIHandler.store.create_concept_revision(revision_payload)
        revision_record = TradingAPIHandler.store.get_concept_revision(revision_id) or {
            "revision_id": revision_id,
            "revision": revision_payload,
        }
        created.append(
            {
                "review_id": review_id,
                "revision_id": revision_id,
                "focus": clean_text(revision_payload.get("focus")),
                "mode": clean_text(revision_payload.get("mode")),
                "readiness": clean_text(revision_payload.get("readiness")),
            }
        )
        events.append(
            build_revision_linked_event(
                runtime_key,
                concept_id,
                review_id,
                revision_id,
                revision_record.get("revision") if isinstance(revision_record.get("revision"), dict) else revision_payload,
            )
        )
    return created, events


def auto_evaluate_linked_revisions(runtime_key, concept_id, brief):
    revision_summaries = TradingAPIHandler.store.list_concept_revisions(limit=100)
    latest_by_review = {}
    for item in revision_summaries:
        revision_id = clean_text(item.get("revision_id"))
        if not revision_id:
            continue
        record = TradingAPIHandler.store.get_concept_revision(revision_id)
        if record is None:
            continue
        revision_payload = record.get("revision") if isinstance(record.get("revision"), dict) else {}
        review_id = clean_text(revision_payload.get("review_id"))
        if not review_id or review_id in latest_by_review:
            continue
        latest_by_review[review_id] = record

    current_sample_started_at = clean_text((((brief.get("review") or {}).get("sample_window") or {}).get("started_at")))
    results = []
    events = []
    for review_id, record in latest_by_review.items():
        revision_id = clean_text(record.get("revision_id"))
        revision_payload = record.get("revision") if isinstance(record.get("revision"), dict) else {}
        latest_evaluation = revision_payload.get("latest_evaluation") if isinstance(revision_payload.get("latest_evaluation"), dict) else {}
        baseline_sample_started_at = clean_text(((revision_payload.get("baseline") or {}).get("sample_started_at")))
        latest_sample_key = (
            clean_text(latest_evaluation.get("current_sample_started_at"))
            or clean_text(latest_evaluation.get("baseline_sample_started_at"))
        )
        current_sample_key = current_sample_started_at or baseline_sample_started_at
        if current_sample_key and latest_sample_key == current_sample_key:
            results.append(
                {
                    "revision_id": revision_id,
                    "review_id": review_id,
                    "status": clean_text(latest_evaluation.get("status")) or "unchanged",
                    "skipped": True,
                    "reason": "sample_already_evaluated",
                    "current_sample_started_at": current_sample_started_at,
                }
            )
            continue

        evaluation = evaluate_concept_revision_plan(revision_payload, brief)
        history_result = record_concept_revision_evaluation(revision_payload, evaluation)
        updated_payload = history_result.get("plan") or revision_payload
        updated_payload["status"] = evaluation.get("status") or updated_payload.get("status") or "planned"
        updated_payload["summary"] = updated_payload.get("summary") or clean_text(
            (updated_payload.get("selected_candidate") or {}).get("rationale")
        ) or "concept revision"
        TradingAPIHandler.store.update_concept_revision(revision_id, updated_payload)

        result = {
            "revision_id": revision_id,
            "review_id": review_id,
            "status": evaluation.get("status"),
            "summary": evaluation.get("summary"),
            "skipped": False,
            "current_sample_started_at": evaluation.get("current_sample_started_at"),
            "history_key": history_result.get("history_key"),
            "history_count": history_result.get("history_count"),
        }
        results.append(result)
        if not history_result.get("history_replaced"):
            events.append(build_revision_event(runtime_key, concept_id, result))

    return results, events


def build_cycle_events(runtime_key, concept_id, previous_state, decision):
    previous_state = previous_state if isinstance(previous_state, dict) else {}
    current_state = compact_state(decision)
    events = []
    changes = {}
    for field in TRACKED_FIELDS:
        previous_value = previous_state.get(field)
        current_value = current_state.get(field)
        if previous_value != current_value:
            changes[field] = {"from": previous_value, "to": current_value}

    if changes:
        severity = "info"
        if current_state.get("overall") in {"revise", "blocked"}:
            severity = "warning"
        events.append(
            build_event(
                runtime_key=runtime_key,
                event_type="decision_changed",
                severity=severity,
                summary=f"{concept_id} changed to {current_state.get('overall')} / {current_state.get('recommendation')}",
                payload={"previous": previous_state, "current": current_state, "changes": changes},
                concept_id=concept_id,
            )
        )

    previous_unmet = previous_state.get("unmet_evidence") if isinstance(previous_state.get("unmet_evidence"), list) else []
    current_unmet = current_state.get("unmet_evidence") if isinstance(current_state.get("unmet_evidence"), list) else []
    if previous_unmet and not current_unmet:
        events.append(
            build_event(
                runtime_key=runtime_key,
                event_type="evidence_threshold_met",
                severity="info",
                summary=f"{concept_id} reached the minimum evidence threshold",
                payload={"previous_unmet_evidence": previous_unmet},
                concept_id=concept_id,
            )
        )

    if current_state.get("overall") == "revise" and previous_state.get("overall") != "revise":
        events.append(
            build_event(
                runtime_key=runtime_key,
                event_type="revise_candidate",
                severity="warning",
                summary=f"{concept_id} now has enough evidence to justify revision rather than passive collection",
                payload={"decision": decision},
                concept_id=concept_id,
            )
        )
    if current_state.get("overall") == "compare" and previous_state.get("overall") != "compare":
        events.append(
            build_event(
                runtime_key=runtime_key,
                event_type="compare_candidate",
                severity="info",
                summary=f"{concept_id} is ready to be compared against the next concept",
                payload={"decision": decision},
                concept_id=concept_id,
            )
        )
    previous_signal = clean_text(previous_state.get("operator_signal"))
    current_signal = clean_text(current_state.get("operator_signal"))
    if current_signal and current_signal != previous_signal:
        severity = "info"
        if current_signal in {"fix_harness", "revise_concept"}:
            severity = "warning"
        events.append(
            build_event(
                runtime_key=runtime_key,
                event_type="operator_signal_changed",
                severity=severity,
                summary=current_state.get("operator_summary") or f"{concept_id} signal changed to {current_signal}",
                payload={
                    "previous_signal": previous_signal,
                    "current_signal": current_signal,
                    "operator_summary": current_state.get("operator_summary"),
                },
                concept_id=concept_id,
            )
        )
    return current_state, events


def paused_runtime_state(previous_state, reason):
    state = dict(previous_state or {})
    state["last_error"] = None
    state["_control_paused"] = True
    state["pause_reason"] = reason
    state["last_scan_at"] = state.get("last_scan_at") or utc_now_iso()
    return state


def build_concept_args(loop_args):
    return SimpleNamespace(
        state_dir=loop_args.state_dir,
        db_path=loop_args.db_path,
        host=loop_args.host,
        port=loop_args.port,
        event_limit=loop_args.event_limit,
        proposal_limit=loop_args.proposal_limit,
        action_limit=loop_args.action_limit,
        scan_limit=loop_args.scan_limit,
        instruments=loop_args.instruments,
        category=loop_args.category,
        max_steps=loop_args.max_steps,
        step_stride=loop_args.step_stride,
        tradable_only=bool(loop_args.tradable_only),
        policy_path=loop_args.policy_path,
        _env_info={},
    )


def run_cycle(loop_args, runtime_key):
    concept_args = build_concept_args(loop_args)
    return concept_decision(concept_args)


def main():
    args = parse_args()
    runtime_key = clean_text(args.runtime_key) or "default"
    previous_state, previous_runtime = load_runtime_state(runtime_key)
    concept_id = "concept-1"

    start_event = create_runtime_start_event(runtime_key, previous_runtime, concept_id)
    if not args.disable_events:
        persist_events([start_event])
    emit(format_event_line(start_event))

    while True:
        global_control = resolve_control_state("global")
        concept_control = resolve_control_state("concept_lab")
        if global_control["effective_paused"] or concept_control["effective_paused"]:
            reason = concept_control["effective_reason"] or global_control["effective_reason"] or "concept lab paused by control state"
            state = paused_runtime_state(previous_state, reason)
            summary = {
                "scanned_at": utc_now_iso(),
                "concept_id": concept_id,
                "overall": "paused",
                "recommendation": "wait",
                "candidate_ratio": 0.0,
                "dominant_blocker": None,
                "dominant_blocker_ratio": 0.0,
                "unmet_evidence_count": len(state.get("unmet_evidence") or []),
            }
            persist_runtime(runtime_key, state, summary)
            emit(f"{concept_id} | overall=paused | recommendation=wait | {reason}")
            if args.once:
                break
            time.sleep(max(5, args.interval_seconds))
            continue

        try:
            decision = run_cycle(args, runtime_key)
            policy = decision.get("policy") if isinstance(decision.get("policy"), dict) else {}
            concept_id = clean_text(policy.get("concept_id")) or concept_id
            brief = build_brief_from_decision(decision)
            linked_revisions, linked_revision_events = auto_link_unlinked_reviews(runtime_key, concept_id, brief)
            revision_results, revision_events = auto_evaluate_linked_revisions(runtime_key, concept_id, brief)
            current_state, events = build_cycle_events(runtime_key, concept_id, previous_state, decision)
            revision_activity = summarize_revision_activity(revision_results)
            revision_activity["auto_linked_count"] = len(linked_revisions)
            review_records, revision_records = build_revision_loop_records(concept_id)
            compare_summary = summarize_concept_revision_loop(revision_records, review_records)
            compare_state = enrich_revision_compare_state(
                previous_state.get("revision_compare"),
                compact_revision_compare_state(compare_summary),
            )
            stage5_readiness = build_stage5_readiness(compare_summary, compare_state)
            compare_summary["stage5_readiness"] = stage5_readiness
            acceptance_summary = summarize_concept_acceptance(
                brief,
                compare_summary,
                review_records,
                live_compare=compare_state,
            )
            acceptance_state = enrich_acceptance_state(
                previous_state.get("acceptance"),
                compact_acceptance_state(acceptance_summary),
            )
            acceptance_summary["stability_cycles"] = acceptance_state.get("stability_cycles")
            acceptance_summary["last_changed_at"] = acceptance_state.get("last_changed_at")
            acceptance_summary["stalled_cycles"] = acceptance_state.get("stalled_cycles")
            acceptance_summary["last_progress_at"] = acceptance_state.get("last_progress_at")
            acceptance_summary["progress_direction"] = acceptance_state.get("progress_direction")
            acceptance_history = update_acceptance_history(
                previous_state.get("acceptance_history"),
                acceptance_state,
            )
            stage7_summary = summarize_stage7_decision(
                acceptance_summary,
                compare_summary,
                review_records,
            )
            stage7_state = enrich_stage7_state(
                previous_state.get("stage7_decision"),
                compact_stage7_state(stage7_summary),
            )
            stage7_summary["stability_cycles"] = stage7_state.get("stability_cycles")
            stage7_summary["last_changed_at"] = stage7_state.get("last_changed_at")
            stage_status = build_concept_stage_status(
                acceptance_summary,
                stage7_summary,
                compare_summary,
            )
            compare_event = build_revision_compare_event(
                runtime_key,
                concept_id,
                previous_state.get("revision_compare"),
                compare_state,
            )
            compare_transition_events = build_revision_compare_transition_events(
                runtime_key,
                concept_id,
                previous_state.get("revision_compare"),
                compare_state,
            )
            acceptance_event = build_acceptance_event(
                runtime_key,
                concept_id,
                previous_state.get("acceptance"),
                acceptance_state,
            )
            acceptance_transition_events = build_acceptance_transition_events(
                runtime_key,
                concept_id,
                previous_state.get("acceptance"),
                acceptance_state,
            )
            stage7_event = build_stage7_event(
                runtime_key,
                concept_id,
                previous_state.get("stage7_decision"),
                stage7_state,
            )
            stage7_transition_events = build_stage7_transition_events(
                runtime_key,
                concept_id,
                previous_state.get("stage7_decision"),
                stage7_state,
            )
            stage_status_event = build_stage_status_event(
                runtime_key,
                concept_id,
                previous_state.get("stage_status"),
                stage_status,
            )
            stage_status_transition_events = build_stage_status_transition_events(
                runtime_key,
                concept_id,
                previous_state.get("stage_status"),
                stage_status,
            )
            revision_activity["leader_revision_id"] = compare_state.get("leader_revision_id")
            revision_activity["leader_status"] = compare_state.get("leader_status")
            revision_activity["leader_score"] = compare_state.get("leader_score")
            revision_activity["compare_artifact_count"] = compare_state.get("compare_artifact_count")
            revision_activity["leader_explanation"] = compare_state.get("leader_explanation")
            revision_activity["compare_action"] = compare_state.get("compare_action")
            revision_activity["stability_cycles"] = compare_state.get("stability_cycles")
            revision_activity["last_changed_at"] = compare_state.get("last_changed_at")
            revision_activity["stage5_readiness"] = stage5_readiness
            revision_activity["acceptance_status"] = acceptance_state.get("latest_acceptance_status")
            revision_activity["acceptance_verdict"] = acceptance_state.get("latest_acceptance_verdict")
            revision_activity["acceptance_action"] = acceptance_state.get("acceptance_action")
            revision_activity["acceptance_ready_for_stage_7"] = acceptance_state.get("ready_for_stage_7")
            revision_activity["acceptance_progress_summary"] = (
                (acceptance_state.get("evidence_progress") or {}).get("progress_summary")
                if isinstance(acceptance_state.get("evidence_progress"), dict)
                else None
            )
            revision_activity["acceptance_stalled_cycles"] = acceptance_state.get("stalled_cycles")
            revision_activity["acceptance_last_progress_at"] = acceptance_state.get("last_progress_at")
            revision_activity["stage7_status"] = stage7_state.get("stage7_status")
            revision_activity["stage7_verdict"] = stage7_state.get("latest_stage7_verdict")
            revision_activity["stage7_action"] = stage7_state.get("decision_action")
            revision_activity["stage7_suggested_path"] = stage7_state.get("suggested_path")
            revision_activity["stage_status"] = stage_status.get("status")
            revision_activity["stage_ready_for_next"] = stage_status.get("ready_for_next_stage")
            current_state["revision_activity"] = revision_activity
            current_state["revision_compare"] = compare_state
            current_state["stage5_readiness"] = stage5_readiness
            current_state["acceptance"] = acceptance_state
            current_state["acceptance_history"] = acceptance_history
            current_state["acceptance_gate"] = acceptance_summary.get("acceptance_gate")
            current_state["stage7_decision"] = stage7_state
            current_state["stage7_gate"] = stage7_summary.get("stage7_gate")
            current_state["stage_status"] = stage_status
            current_state["last_revision_results"] = revision_results[-5:]
            current_state["last_linked_revisions"] = linked_revisions[-5:]
            current_state["last_revision_compare"] = compare_summary
            current_state["last_acceptance"] = acceptance_summary
            current_state["last_acceptance_history"] = acceptance_history
            current_state["last_stage7_decision"] = stage7_summary
            summary = build_runtime_summary(decision)
            summary["revision_activity"] = revision_activity
            summary["revision_compare"] = compare_state
            summary["stage5_readiness"] = stage5_readiness
            summary["acceptance"] = acceptance_summary
            summary["acceptance_history"] = acceptance_history
            summary["acceptance_gate"] = acceptance_summary.get("acceptance_gate")
            summary["stage7_decision"] = stage7_summary
            summary["stage7_gate"] = stage7_summary.get("stage7_gate")
            summary["stage_status"] = stage_status
            events.extend(linked_revision_events)
            events.extend(revision_events)
            if compare_event is not None:
                events.append(compare_event)
            events.extend(compare_transition_events)
            if acceptance_event is not None:
                events.append(acceptance_event)
            events.extend(acceptance_transition_events)
            if stage7_event is not None:
                events.append(stage7_event)
            events.extend(stage7_transition_events)
            if stage_status_event is not None:
                events.append(stage_status_event)
            events.extend(stage_status_transition_events)
            persist_runtime(runtime_key, current_state, summary)
            if not args.disable_events and events:
                persist_events(events)
            emit(format_state_line(summary))
            for event in events:
                emit(format_event_line(event))
            previous_state = current_state
        except Exception as exc:
            error_summary = clean_text(str(exc)) or "concept lab cycle failed"
            error_event = build_event(
                runtime_key=runtime_key,
                event_type="cycle_failed",
                severity="error",
                summary=error_summary,
                payload={"error": error_summary},
                concept_id=concept_id,
            )
            error_state = dict(previous_state or {})
            error_state["last_error"] = {"message": error_summary, "at": utc_now_iso()}
            error_state["_control_paused"] = False
            persist_runtime(
                runtime_key,
                error_state,
                {
                    "scanned_at": utc_now_iso(),
                    "concept_id": concept_id,
                    "overall": "error",
                    "recommendation": "inspect_error",
                    "candidate_ratio": 0.0,
                    "dominant_blocker": None,
                    "dominant_blocker_ratio": 0.0,
                    "unmet_evidence_count": len(error_state.get("unmet_evidence") or []),
                },
            )
            if not args.disable_events:
                persist_events([error_event])
            emit(format_event_line(error_event))
        if args.once:
            break
        time.sleep(max(5, args.interval_seconds))


if __name__ == "__main__":
    main()
