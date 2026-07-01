#!/usr/bin/env python3

from datetime import datetime, timezone

from concept_briefing import clean_text, format_percent, utc_now_iso


def _safe_float(value, default=0.0):
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _parse_iso_datetime(value):
    text = clean_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _display_label(value):
    text = clean_text(value) or "concept observation"
    return " ".join(part.capitalize() for part in text.replace("-", " ").replace("_", " ").split())


def _merge_unique(items, additions):
    merged = [clean_text(item) for item in (items or []) if clean_text(item)]
    for item in additions or []:
        text = clean_text(item)
        if text and text not in merged:
            merged.append(text)
    return merged


def _normalize_review_artifact(review_artifact):
    artifact = review_artifact if isinstance(review_artifact, dict) else {}
    nested = artifact.get("review") if isinstance(artifact.get("review"), dict) else None
    review = dict(nested) if nested else dict(artifact)
    for field in (
        "review_id",
        "created_at",
        "source",
        "author",
        "review_kind",
        "overall",
        "recommendation",
        "primary_blocker",
        "summary",
    ):
        if review.get(field) is None and artifact.get(field) is not None:
            review[field] = artifact.get(field)
    return review


def _normalize_revision_compare_artifact(review_artifact):
    review = _normalize_review_artifact(review_artifact)
    if clean_text(review.get("review_kind")) != "revision_compare_structured":
        return None

    structured = (
        review.get("structured_response")
        if isinstance(review.get("structured_response"), dict)
        else {}
    )
    return {
        "review_id": clean_text(review.get("review_id")),
        "created_at": clean_text(review.get("created_at")),
        "source": clean_text(review.get("source")),
        "author": clean_text(review.get("author")),
        "review_kind": clean_text(review.get("review_kind")),
        "summary": clean_text(review.get("summary")),
        "verdict": clean_text(structured.get("verdict")),
        "leader_revision_id": clean_text(structured.get("leader_revision_id")),
        "challenger_revision_id": clean_text(structured.get("challenger_revision_id")),
        "comparison_summary": clean_text(structured.get("comparison_summary")),
        "primary_risk": clean_text(structured.get("primary_risk")),
        "next_action_type": clean_text(structured.get("next_action_type")),
        "next_action_focus": clean_text(structured.get("next_action_focus")),
        "next_action_summary": clean_text(structured.get("next_action_summary")),
        "what_would_change_my_mind": clean_text(structured.get("what_would_change_my_mind")),
        "confidence": clean_text(structured.get("confidence")),
        "grounding_refs_used": [
            clean_text(item)
            for item in (structured.get("grounding_refs_used") or [])
            if clean_text(item)
        ],
    }


def build_stage5_readiness(compare_summary, live_state=None):
    compare = compare_summary if isinstance(compare_summary, dict) else {}
    live = live_state if isinstance(live_state, dict) else {}

    leader = compare.get("best_ranked_revision") if isinstance(compare.get("best_ranked_revision"), dict) else {}
    latest_compare = (
        compare.get("latest_compare_artifact")
        if isinstance(compare.get("latest_compare_artifact"), dict)
        else {}
    )

    leader_revision_id = clean_text(leader.get("revision_id")) or clean_text(compare.get("leader_revision_id"))
    compare_artifact_count = _safe_int(compare.get("compare_artifact_count"))
    evaluation_history_count = _safe_int(compare.get("evaluation_history_count"))
    leader_explanation = clean_text(compare.get("leader_explanation"))
    compare_action = clean_text(compare.get("compare_action")) or clean_text(compare.get("next_action"))
    latest_compare_verdict = clean_text(live.get("latest_compare_verdict")) or clean_text(latest_compare.get("verdict"))
    latest_compare_review_id = clean_text(live.get("latest_compare_review_id")) or clean_text(latest_compare.get("review_id"))
    stability_cycles = _safe_int(live.get("stability_cycles"))
    last_changed_at = clean_text(live.get("last_changed_at"))

    checks = [
        {
            "key": "compare_artifacts_present",
            "label": "compare artifacts are saved",
            "ok": compare_artifact_count > 0,
            "required": True,
            "detail": f"{compare_artifact_count} saved compare artifact{'s' if compare_artifact_count != 1 else ''}.",
        },
        {
            "key": "ranked_leader_present",
            "label": "a ranked revision leader is live",
            "ok": bool(leader_revision_id),
            "required": True,
            "detail": leader_revision_id or "No ranked leader yet.",
        },
        {
            "key": "leader_guidance_present",
            "label": "leader explanation and compare action are exposed",
            "ok": bool(leader_explanation and compare_action),
            "required": True,
            "detail": leader_explanation or compare_action or "Leader guidance is still missing.",
        },
        {
            "key": "compare_verdict_present",
            "label": "latest compare verdict is available",
            "ok": bool(latest_compare_verdict and latest_compare_review_id),
            "required": True,
            "detail": (
                f"{latest_compare_review_id} / {latest_compare_verdict}"
                if latest_compare_verdict and latest_compare_review_id
                else "No saved compare verdict yet."
            ),
        },
        {
            "key": "stability_window_met",
            "label": "compare guidance has stayed stable across multiple cycles",
            "ok": stability_cycles >= 3,
            "required": True,
            "detail": (
                f"{stability_cycles} stable cycle{'s' if stability_cycles != 1 else ''}"
                if stability_cycles > 0
                else "No stability history yet."
            ),
        },
        {
            "key": "evaluation_history_depth_met",
            "label": "revision history is deep enough to compare responsibly",
            "ok": evaluation_history_count >= 6,
            "required": False,
            "detail": (
                f"{evaluation_history_count} evaluation history entr{'y' if evaluation_history_count == 1 else 'ies'}."
            ),
        },
    ]

    score = 0
    weights = {
        "compare_artifacts_present": 15,
        "ranked_leader_present": 20,
        "leader_guidance_present": 20,
        "compare_verdict_present": 15,
        "stability_window_met": 20,
        "evaluation_history_depth_met": 10,
    }
    for item in checks:
        if item["ok"]:
            score += weights.get(item["key"], 0)

    blockers = [item["label"] for item in checks if item["required"] and not item["ok"]]
    ready = not blockers
    if ready:
        status = "ready_for_stage_6_from_daemon_state"
        summary = "Daemon-side compare guidance looks stable enough to treat infrastructure as no longer the main bottleneck."
    elif score >= 50:
        status = "stabilizing"
        summary = "Stage 5 is progressing, but the compare loop still needs more stable live cycles before it can be considered operationally settled."
    else:
        status = "not_ready"
        summary = "Stage 5 still has missing live readiness checks, so the compare loop should not be treated as settled yet."

    return {
        "stage": "stage_5_compare_guidance_live_testing",
        "scope": "daemon_live_gate",
        "status": status,
        "score": score,
        "ready_for_stage_6_from_daemon_state": ready,
        "summary": summary,
        "blockers": blockers,
        "checks": checks,
        "metrics": {
            "compare_artifact_count": compare_artifact_count,
            "leader_revision_id": leader_revision_id,
            "latest_compare_verdict": latest_compare_verdict,
            "latest_compare_review_id": latest_compare_review_id,
            "stability_cycles": stability_cycles,
            "evaluation_history_count": evaluation_history_count,
            "last_changed_at": last_changed_at,
        },
        "caveat": "This gate reflects live daemon state only. Release checks after code changes still need to pass separately.",
    }


def _mode_for_review_action(next_action_type, one_variable_needed):
    action = clean_text(next_action_type) or "collect_evidence"
    if one_variable_needed or action == "review_one_rule":
        return "review"
    if action == "compare_next_concept":
        return "compare"
    if action == "fix_harness":
        return "repair"
    return "observe"


def _readiness_for_review_action(next_action_type, current_readiness):
    action = clean_text(next_action_type) or "collect_evidence"
    if action in {"review_one_rule", "fix_harness"}:
        return "now"
    if action == "compare_next_concept":
        return "later"
    return clean_text(current_readiness) or "now"


def _title_for_review_action(next_action_type, focus, one_variable_needed):
    label = _display_label(focus)
    action = clean_text(next_action_type) or "collect_evidence"
    if one_variable_needed:
        return f"One-variable review for {label}"
    if action == "review_one_rule":
        return f"Review {label} as the next conservative change"
    if action == "compare_next_concept":
        return f"Prepare a comparison checkpoint for {label}"
    if action == "fix_harness":
        return f"Repair workflow around {label}"
    return f"Collect evidence for {label}"


def build_concept_revision_plan(brief_packet, candidate_id=None, review_artifact=None, source="manual", author=None):
    brief = brief_packet if isinstance(brief_packet, dict) else {}
    candidates = brief.get("revision_candidates") or []
    selected = None
    if candidate_id:
        for item in candidates:
            if clean_text(item.get("id")) == clean_text(candidate_id):
                selected = item
                break
    if selected is None and candidates:
        selected = candidates[0]
    selected = selected if isinstance(selected, dict) else {}

    decision = brief.get("decision") or {}
    evidence = brief.get("evidence") or {}
    pressure = brief.get("pressure_points") or {}
    dominant = pressure.get("dominant_blocker") or {}
    gap = pressure.get("cross_market_gap") or {}
    review = brief.get("review") or {}
    review_artifact = _normalize_review_artifact(review_artifact)

    focus = clean_text(selected.get("focus")) or clean_text((dominant or {}).get("blocker")) or "concept_observation"
    title = clean_text(selected.get("title")) or "Concept revision plan"
    rationale = clean_text(selected.get("rationale")) or "No rationale provided."
    mode = clean_text(selected.get("mode")) or "observe"
    readiness = clean_text(selected.get("readiness")) or "now"
    guardrails = [clean_text(item) for item in (selected.get("guardrails") or []) if clean_text(item)]
    success_signals = [clean_text(item) for item in (selected.get("success_signals") or []) if clean_text(item)]
    abort_signals = [clean_text(item) for item in (selected.get("abort_signals") or []) if clean_text(item)]

    structured_review = review_artifact.get("structured_response") if isinstance(review_artifact.get("structured_response"), dict) else {}
    review_guidance = {}
    if structured_review:
        one_variable = structured_review.get("one_variable_revision") if isinstance(structured_review.get("one_variable_revision"), dict) else {}
        one_variable_needed = bool(one_variable.get("needed"))
        review_focus = (
            clean_text(one_variable.get("focus"))
            if one_variable_needed
            else clean_text(structured_review.get("next_action_focus"))
        ) or clean_text(structured_review.get("next_action_focus")) or focus
        review_action = clean_text(structured_review.get("next_action_type")) or "collect_evidence"
        review_summary = (
            clean_text(one_variable.get("hypothesis"))
            if one_variable_needed
            else clean_text(structured_review.get("next_action_summary"))
        ) or clean_text(structured_review.get("next_action_summary")) or rationale

        focus = review_focus
        mode = _mode_for_review_action(review_action, one_variable_needed)
        readiness = _readiness_for_review_action(review_action, readiness)
        title = _title_for_review_action(review_action, focus, one_variable_needed)
        rationale = review_summary
        success_signals = _merge_unique(
            success_signals,
            [
                one_variable.get("success_metric"),
                structured_review.get("what_would_change_my_mind"),
            ],
        )
        abort_signals = _merge_unique(
            abort_signals,
            [
                one_variable.get("abort_metric"),
            ],
        )
        guardrails = _merge_unique(
            guardrails,
            [
                f"Stay aligned with the saved review verdict: {structured_review.get('verdict')}.",
                "Do not broaden the change scope beyond the single structured review focus.",
            ],
        )
        review_guidance = {
            "review_id": clean_text(review_artifact.get("review_id")),
            "review_kind": clean_text(review_artifact.get("review_kind")),
            "created_at": clean_text(review_artifact.get("created_at")),
            "verdict": clean_text(structured_review.get("verdict")),
            "primary_blocker": clean_text(structured_review.get("primary_blocker")),
            "evidence_gap": clean_text(structured_review.get("evidence_gap")),
            "next_action_type": review_action,
            "next_action_focus": clean_text(structured_review.get("next_action_focus")),
            "next_action_summary": clean_text(structured_review.get("next_action_summary")),
            "what_would_change_my_mind": clean_text(structured_review.get("what_would_change_my_mind")),
            "confidence": clean_text(structured_review.get("confidence")),
            "grounding_refs_used": structured_review.get("grounding_refs_used") or [],
            "one_variable_revision": {
                "needed": one_variable_needed,
                "focus": clean_text(one_variable.get("focus")),
                "hypothesis": clean_text(one_variable.get("hypothesis")),
                "success_metric": clean_text(one_variable.get("success_metric")),
                "abort_metric": clean_text(one_variable.get("abort_metric")),
            },
        }

    baseline = {
        "captured_at": clean_text(brief.get("generated_at")) or utc_now_iso(),
        "candidate_ratio": _safe_float(pressure.get("candidate_ratio")),
        "dominant_blocker": clean_text(dominant.get("blocker")),
        "dominant_blocker_ratio": _safe_float(dominant.get("ratio")),
        "cross_market_gap_blocker": clean_text(gap.get("blocker")),
        "cross_market_gap": _safe_float(gap.get("gap")),
        "recent_proposals": _safe_int(evidence.get("recent_proposals")),
        "recent_execution_state": _safe_int(evidence.get("recent_execution_state")),
        "recent_scans": _safe_int(evidence.get("recent_scans")),
        "review_overall": clean_text(review.get("overall")),
        "decision_overall": clean_text(decision.get("overall")),
        "sample_started_at": clean_text((review.get("sample_window") or {}).get("started_at")),
    }

    return {
        "generated_at": utc_now_iso(),
        "concept_id": clean_text(brief.get("concept_id")) or "concept-1",
        "source": clean_text(source) or "manual",
        "author": clean_text(author),
        "review_id": clean_text(review_artifact.get("review_id")),
        "selected_candidate": selected,
        "focus": focus,
        "mode": mode,
        "readiness": readiness,
        "title": title,
        "summary": rationale,
        "baseline": baseline,
        "guardrails": guardrails,
        "success_signals": success_signals,
        "abort_signals": abort_signals,
        "linked_review_summary": clean_text(review_artifact.get("summary")),
        "linked_review_guidance": review_guidance,
        "status": "planned",
    }


def evaluate_concept_revision_plan(plan_payload, current_brief):
    plan = plan_payload if isinstance(plan_payload, dict) else {}
    brief = current_brief if isinstance(current_brief, dict) else {}
    baseline = plan.get("baseline") or {}
    pressure = brief.get("pressure_points") or {}
    dominant = pressure.get("dominant_blocker") or {}
    gap = pressure.get("cross_market_gap") or {}
    evidence = brief.get("evidence") or {}
    decision = brief.get("decision") or {}
    review = brief.get("review") or {}

    current_candidate_ratio = _safe_float(pressure.get("candidate_ratio"))
    current_dominant_blocker = clean_text(dominant.get("blocker"))
    current_dominant_ratio = _safe_float(dominant.get("ratio"))
    current_gap = _safe_float(gap.get("gap"))
    current_proposals = _safe_int(evidence.get("recent_proposals"))
    current_execution_state = _safe_int(evidence.get("recent_execution_state"))
    baseline_sample_started_at = clean_text(baseline.get("sample_started_at"))
    current_sample_started_at = clean_text((review.get("sample_window") or {}).get("started_at"))

    candidate_ratio_delta = round(current_candidate_ratio - _safe_float(baseline.get("candidate_ratio")), 4)
    blocker_ratio_delta = round(current_dominant_ratio - _safe_float(baseline.get("dominant_blocker_ratio")), 4)
    cross_market_gap_delta = round(current_gap - _safe_float(baseline.get("cross_market_gap")), 4)
    proposal_delta = current_proposals - _safe_int(baseline.get("recent_proposals"))
    execution_state_delta = current_execution_state - _safe_int(baseline.get("recent_execution_state"))

    focus = clean_text(plan.get("focus")) or "concept_observation"
    status = "flat"
    summary = "The revision plan is still in observation."
    baseline_sample_dt = _parse_iso_datetime(baseline_sample_started_at)
    current_sample_dt = _parse_iso_datetime(current_sample_started_at)
    fresh_sample_ready = (
        baseline_sample_dt is None
        or current_sample_dt is None
        or current_sample_dt > baseline_sample_dt
    )

    if not fresh_sample_ready:
        status = "awaiting_fresh_sample"
        summary = "The latest sample window has not advanced beyond the revision baseline yet."
    elif clean_text(decision.get("overall")) == "blocked":
        status = "regressed"
        summary = "The harness is blocked again, so the revision plan cannot be judged yet."
    elif focus == "evidence_thresholds":
        if proposal_delta > 0 or execution_state_delta > 0:
            status = "improved"
            summary = (
                "Evidence is growing in the intended direction: "
                f"proposals {proposal_delta:+d}, execution-state {execution_state_delta:+d}."
            )
        else:
            status = "flat"
            summary = "The evidence thresholds have not advanced yet."
    elif focus == clean_text(gap.get("blocker")) or focus == clean_text(baseline.get("cross_market_gap_blocker")):
        if cross_market_gap_delta <= -0.05:
            status = "improved"
            summary = f"The cross-market gap narrowed by about {format_percent(abs(cross_market_gap_delta))}."
        elif cross_market_gap_delta >= 0.05:
            status = "regressed"
            summary = f"The cross-market gap widened by about {format_percent(cross_market_gap_delta)}."
        else:
            status = "flat"
            summary = "The cross-market gap is broadly unchanged."
    elif focus == current_dominant_blocker or focus == clean_text(baseline.get("dominant_blocker")):
        if blocker_ratio_delta <= -0.05 or candidate_ratio_delta >= 0.02:
            status = "improved"
            summary = (
                f"{focus} pressure eased or candidate flow improved "
                f"(blocker delta {format_percent(abs(blocker_ratio_delta))}, candidate delta {format_percent(candidate_ratio_delta)})."
            )
        elif blocker_ratio_delta >= 0.05 and candidate_ratio_delta <= 0.0:
            status = "regressed"
            summary = f"{focus} is exerting more pressure than the baseline sample."
        else:
            status = "flat"
            summary = f"{focus} is still near the baseline pressure level."
    else:
        if candidate_ratio_delta >= 0.02:
            status = "improved"
            summary = f"Candidate flow improved by about {format_percent(candidate_ratio_delta)}."
        else:
            status = "flat"
            summary = "No clear improvement signal is visible yet."

    quality_guard_ok = clean_text(decision.get("overall")) != "blocked" and not any(
        clean_text(item.get("severity")) == "error" for item in (brief.get("issues") or [])
    )

    return {
        "evaluated_at": utc_now_iso(),
        "status": status,
        "summary": summary,
        "fresh_sample_ready": fresh_sample_ready,
        "baseline_sample_started_at": baseline_sample_started_at,
        "current_sample_started_at": current_sample_started_at,
        "quality_guard_ok": quality_guard_ok,
        "current_decision": {
            "overall": clean_text(decision.get("overall")),
            "recommendation": clean_text(decision.get("recommendation")),
            "operator_signal": clean_text(decision.get("operator_signal")),
        },
        "deltas": {
            "candidate_ratio_delta": candidate_ratio_delta,
            "dominant_blocker_ratio_delta": blocker_ratio_delta,
            "cross_market_gap_delta": cross_market_gap_delta,
            "recent_proposal_delta": proposal_delta,
            "recent_execution_state_delta": execution_state_delta,
        },
        "current_snapshot": {
            "candidate_ratio": current_candidate_ratio,
            "dominant_blocker": current_dominant_blocker,
            "dominant_blocker_ratio": current_dominant_ratio,
            "cross_market_gap": current_gap,
            "recent_proposals": current_proposals,
            "recent_execution_state": current_execution_state,
        },
    }


def _normalize_evaluation_history(items):
    history = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        history.append(dict(item))
    return history


def _evaluation_history_key(evaluation):
    payload = evaluation if isinstance(evaluation, dict) else {}
    return (
        clean_text(payload.get("current_sample_started_at"))
        or clean_text(payload.get("baseline_sample_started_at"))
        or clean_text(payload.get("evaluated_at"))
        or "unknown"
    )


def record_concept_revision_evaluation(plan_payload, evaluation):
    plan = dict(plan_payload) if isinstance(plan_payload, dict) else {}
    result = dict(evaluation) if isinstance(evaluation, dict) else {}
    history = _normalize_evaluation_history(plan.get("evaluation_history"))
    key = _evaluation_history_key(result)
    updated = False
    replaced = False

    for index, item in enumerate(history):
        if _evaluation_history_key(item) == key:
            history[index] = result
            replaced = True
            updated = True
            break

    if not replaced:
        history.append(result)
        updated = True

    history.sort(
        key=lambda item: (
            _parse_iso_datetime(item.get("evaluated_at"))
            or _parse_iso_datetime(item.get("current_sample_started_at"))
            or datetime.min.replace(tzinfo=timezone.utc)
        )
    )
    plan["evaluation_history"] = history[-25:]
    plan["evaluation_history_count"] = len(plan["evaluation_history"])
    plan["latest_evaluation"] = result
    plan["last_evaluated_at"] = clean_text(result.get("evaluated_at"))
    return {
        "plan": plan,
        "history_key": key,
        "history_updated": updated,
        "history_replaced": replaced,
        "history_count": len(plan["evaluation_history"]),
    }


def _normalize_revision_summary_record(record):
    item = record if isinstance(record, dict) else {}
    payload = item.get("revision") if isinstance(item.get("revision"), dict) else {}
    latest_evaluation = payload.get("latest_evaluation") if isinstance(payload.get("latest_evaluation"), dict) else {}
    history = _normalize_evaluation_history(payload.get("evaluation_history"))
    return {
        "revision_id": clean_text(item.get("revision_id")),
        "review_id": clean_text(payload.get("review_id")),
        "focus": clean_text(item.get("focus")) or clean_text(payload.get("focus")),
        "status": clean_text(item.get("status")) or clean_text(payload.get("status")) or clean_text(latest_evaluation.get("status")) or "planned",
        "summary": clean_text(item.get("summary")) or clean_text(payload.get("summary")) or "concept revision",
        "created_at": clean_text(item.get("created_at")) or clean_text(payload.get("generated_at")),
        "source": clean_text(item.get("source")) or clean_text(payload.get("source")),
        "author": clean_text(item.get("author")) or clean_text(payload.get("author")),
        "latest_evaluation": latest_evaluation,
        "evaluation_history": history,
        "evaluation_history_count": len(history),
    }


def _rank_revision_candidate(item, latest_sample_started_at):
    record = item if isinstance(item, dict) else {}
    latest_evaluation = record.get("latest_evaluation") if isinstance(record.get("latest_evaluation"), dict) else {}
    deltas = latest_evaluation.get("deltas") if isinstance(latest_evaluation.get("deltas"), dict) else {}
    status = clean_text(record.get("status")) or "planned"
    history_count = int(record.get("evaluation_history_count") or 0)
    score = 0
    reasons = []

    def add(points, reason):
        nonlocal score
        score += points
        if reason:
            reasons.append(reason)

    if status == "improved":
        add(70, "Has an improved evaluation status.")
    elif status == "flat":
        add(44, "Has stayed stable across fresh-sample evaluation.")
    elif status == "awaiting_fresh_sample":
        add(22, "Is linked and waiting for the next fresh sample.")
    elif status == "planned":
        add(12, "Exists as a planned revision but has not matured yet.")
    elif status == "regressed":
        add(-8, "Has regressed relative to its baseline.")

    if history_count > 0:
        add(min(24, history_count * 6), f"Has {history_count} evaluation history entr{'y' if history_count == 1 else 'ies'}.")

    if latest_evaluation.get("quality_guard_ok") is True:
        add(8, "Latest evaluation passed the quality guard.")

    if latest_evaluation.get("fresh_sample_ready") is True:
        add(6, "Latest evaluation came from a fresh sample.")

    if clean_text(latest_evaluation.get("current_sample_started_at")) == clean_text(latest_sample_started_at):
        add(5, "Uses the latest sample window.")

    candidate_ratio_delta = _safe_float(deltas.get("candidate_ratio_delta"))
    if candidate_ratio_delta > 0:
        add(12, f"Candidate flow improved by about {format_percent(candidate_ratio_delta)}.")

    proposal_delta = _safe_int(deltas.get("recent_proposal_delta"))
    execution_delta = _safe_int(deltas.get("recent_execution_state_delta"))
    if proposal_delta > 0 or execution_delta > 0:
        add(10, f"Evidence grew: proposals {proposal_delta:+d}, execution-state {execution_delta:+d}.")

    blocker_delta = _safe_float(deltas.get("dominant_blocker_ratio_delta"))
    if blocker_delta < 0:
        add(8, f"Dominant blocker pressure eased by about {format_percent(abs(blocker_delta))}.")
    elif blocker_delta > 0 and status != "improved":
        add(-4, f"Dominant blocker pressure increased by about {format_percent(blocker_delta)}.")

    gap_delta = _safe_float(deltas.get("cross_market_gap_delta"))
    if gap_delta < 0:
        add(6, f"Cross-market gap narrowed by about {format_percent(abs(gap_delta))}.")
    elif gap_delta > 0 and status == "regressed":
        add(-4, f"Cross-market gap widened by about {format_percent(gap_delta)}.")

    return {
        "revision_id": record.get("revision_id"),
        "review_id": record.get("review_id"),
        "focus": record.get("focus"),
        "status": status,
        "summary": record.get("summary"),
        "score": score,
        "reasons": reasons[:4],
        "history_count": history_count,
        "latest_sample_started_at": clean_text(latest_evaluation.get("current_sample_started_at")),
    }


def summarize_concept_revision_loop(revision_records, review_records=None):
    revisions = [_normalize_revision_summary_record(item) for item in (revision_records or [])]
    revisions = [item for item in revisions if item.get("revision_id")]
    reviews = [item for item in (review_records or []) if isinstance(item, dict)]
    compare_artifacts = [
        item
        for item in (_normalize_revision_compare_artifact(review) for review in reviews)
        if item is not None
    ]
    status_counts = {}
    focus_counts = {}
    source_counts = {}
    total_history_entries = 0
    latest_sample_dt = None
    latest_sample_started_at = None

    status_rank = {
        "improved": 4,
        "flat": 3,
        "awaiting_fresh_sample": 2,
        "planned": 1,
        "regressed": 0,
    }

    def _item_dt(item):
        return (
            _parse_iso_datetime((item.get("latest_evaluation") or {}).get("evaluated_at"))
            or _parse_iso_datetime(item.get("created_at"))
            or datetime.min.replace(tzinfo=timezone.utc)
        )

    for item in revisions:
        status = item.get("status") or "planned"
        focus = item.get("focus") or "concept_observation"
        source = item.get("source") or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        focus_counts[focus] = focus_counts.get(focus, 0) + 1
        source_counts[source] = source_counts.get(source, 0) + 1
        total_history_entries += int(item.get("evaluation_history_count") or 0)
        sample_started_at = clean_text((item.get("latest_evaluation") or {}).get("current_sample_started_at"))
        sample_dt = _parse_iso_datetime(sample_started_at)
        if sample_dt and (latest_sample_dt is None or sample_dt > latest_sample_dt):
            latest_sample_dt = sample_dt
            latest_sample_started_at = sample_started_at

    revisions.sort(
        key=lambda item: (
            status_rank.get(item.get("status") or "planned", -1),
            _item_dt(item),
        ),
        reverse=True,
    )
    best_revision = revisions[0] if revisions else None
    latest_revision = (
        max(revisions, key=_item_dt)
        if revisions
        else None
    )
    ranked_revisions = [
        _rank_revision_candidate(item, latest_sample_started_at)
        for item in revisions
    ]
    ranked_revisions.sort(
        key=lambda item: (
            int(item.get("score") or 0),
            _parse_iso_datetime(item.get("latest_sample_started_at"))
            or _parse_iso_datetime(
                next(
                    (
                        candidate.get("created_at")
                        for candidate in revisions
                        if candidate.get("revision_id") == item.get("revision_id")
                    ),
                    None,
                )
            )
            or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    best_ranked = ranked_revisions[0] if ranked_revisions else None
    latest_compare_artifact = (
        max(
            compare_artifacts,
            key=lambda item: _parse_iso_datetime(item.get("created_at"))
            or datetime.min.replace(tzinfo=timezone.utc),
        )
        if compare_artifacts
        else None
    )

    improved_count = status_counts.get("improved", 0)
    regressed_count = status_counts.get("regressed", 0)
    awaiting_count = status_counts.get("awaiting_fresh_sample", 0)

    if not revisions:
        takeaway = "No saved concept revisions are available yet."
        next_action = "Save a structured review first so the daemon can link and evaluate revisions."
    elif improved_count > 0 and best_ranked is not None:
        takeaway = (
            f"{best_ranked.get('revision_id')} is the current best revision candidate "
            f"with status {best_ranked.get('status')}."
        )
        next_action = "Keep collecting fresh-sample evaluations before treating the improved revision as trustworthy."
    elif awaiting_count == len(revisions):
        takeaway = "All linked revisions are waiting for a fresh sample before they can be judged."
        next_action = "Let the next fresh sample window complete so the daemon can evaluate the linked revisions."
    elif regressed_count > 0 and improved_count == 0:
        takeaway = "At least one linked revision is regressing, and none are improving yet."
        next_action = "Review the regressed revision before promoting any rules change."
    else:
        takeaway = "The revision loop is active, but no revision has produced a clear improvement yet."
        next_action = "Keep collecting evidence and compare the next fresh-sample evaluations before changing the rules."

    leader_explanation = None
    compare_action = None
    if latest_compare_artifact:
        leader_id = latest_compare_artifact.get("leader_revision_id")
        challenger_id = latest_compare_artifact.get("challenger_revision_id")
        verdict = latest_compare_artifact.get("verdict")
        comparison_summary = latest_compare_artifact.get("comparison_summary")
        if verdict == "promote_runner_up" and challenger_id:
            leader_explanation = (
                f"{challenger_id} is the preferred replacement for {leader_id or 'the current leader'}."
            )
            if comparison_summary:
                leader_explanation = f"{leader_explanation} {comparison_summary}"
        elif leader_id:
            leader_explanation = f"{leader_id} remains the preferred leader."
            if comparison_summary:
                leader_explanation = f"{leader_explanation} {comparison_summary}"
        else:
            leader_explanation = comparison_summary or latest_compare_artifact.get("summary")
        compare_action = latest_compare_artifact.get("next_action_summary") or next_action

    return {
        "review_count": len(reviews),
        "revision_count": len(revisions),
        "compare_artifact_count": len(compare_artifacts),
        "status_counts": status_counts,
        "focus_counts": focus_counts,
        "source_counts": source_counts,
        "evaluation_history_count": total_history_entries,
        "latest_sample_started_at": latest_sample_started_at,
        "takeaway": takeaway,
        "next_action": next_action,
        "leader_explanation": leader_explanation,
        "compare_action": compare_action,
        "best_revision": {
            "revision_id": best_revision.get("revision_id"),
            "review_id": best_revision.get("review_id"),
            "focus": best_revision.get("focus"),
            "status": best_revision.get("status"),
            "summary": best_revision.get("summary"),
        } if best_revision else None,
        "best_ranked_revision": best_ranked,
        "latest_compare_artifact": latest_compare_artifact,
        "latest_revision": {
            "revision_id": latest_revision.get("revision_id"),
            "review_id": latest_revision.get("review_id"),
            "focus": latest_revision.get("focus"),
            "status": latest_revision.get("status"),
            "summary": latest_revision.get("summary"),
        } if latest_revision else None,
        "ranked_revisions": ranked_revisions[:5],
    }


def render_concept_revision_plan_markdown(plan):
    payload = plan if isinstance(plan, dict) else {}
    baseline = payload.get("baseline") or {}
    selected = payload.get("selected_candidate") or {}
    lines = [
        "# Concept Revision Plan",
        "",
        f"- Generated at: {payload.get('generated_at')}",
        f"- Concept: {payload.get('concept_id') or '-'}",
        f"- Title: {payload.get('title') or '-'}",
        f"- Focus: {payload.get('focus') or '-'}",
        f"- Mode: {payload.get('mode') or '-'} / {payload.get('readiness') or '-'}",
        f"- Summary: {payload.get('summary') or '-'}",
        "",
        "## Baseline",
        f"- Candidate ratio: {format_percent(baseline.get('candidate_ratio'))}",
        f"- Dominant blocker: {(baseline.get('dominant_blocker') or '-')} at {format_percent(baseline.get('dominant_blocker_ratio'))}",
        f"- Cross-market gap: {(baseline.get('cross_market_gap_blocker') or '-')} at {format_percent(baseline.get('cross_market_gap'))}",
        f"- Evidence counts: proposals {baseline.get('recent_proposals', 0)}, execution-state {baseline.get('recent_execution_state', 0)}, scans {baseline.get('recent_scans', 0)}",
    ]

    if selected:
        lines.extend(["", "## Candidate Context"])
        lines.append(f"- Candidate id: {selected.get('id') or '-'}")
        lines.append(f"- Rationale: {selected.get('rationale') or '-'}")

    linked_review = payload.get("linked_review_guidance") or {}
    if linked_review:
        lines.extend(["", "## Linked Review Guidance"])
        lines.append(f"- Review id: {linked_review.get('review_id') or '-'}")
        lines.append(f"- Verdict: {linked_review.get('verdict') or '-'}")
        lines.append(f"- Next action: {linked_review.get('next_action_type') or '-'} / {linked_review.get('next_action_focus') or '-'}")
        lines.append(f"- Confidence: {linked_review.get('confidence') or '-'}")
        lines.append(f"- Evidence gap: {linked_review.get('evidence_gap') or '-'}")

    guardrails = payload.get("guardrails") or []
    if guardrails:
        lines.extend(["", "## Guardrails"])
        for item in guardrails:
            lines.append(f"- {item}")

    success_signals = payload.get("success_signals") or []
    if success_signals:
        lines.extend(["", "## Success Signals"])
        for item in success_signals:
            lines.append(f"- {item}")

    abort_signals = payload.get("abort_signals") or []
    if abort_signals:
        lines.extend(["", "## Abort Signals"])
        for item in abort_signals:
            lines.append(f"- {item}")

    evaluation = payload.get("latest_evaluation") or {}
    if evaluation:
        lines.extend(
            [
                "",
                "## Latest Evaluation",
                f"- Status: {evaluation.get('status') or '-'}",
                f"- Summary: {evaluation.get('summary') or '-'}",
                f"- Quality guard ok: {evaluation.get('quality_guard_ok')}",
                f"- Fresh sample ready: {evaluation.get('fresh_sample_ready')}",
            ]
        )

    history = payload.get("evaluation_history") or []
    if history:
        lines.extend(
            [
                "",
                "## Evaluation History",
                f"- Entries: {len(history)}",
            ]
        )
        for item in history[-3:]:
            lines.append(
                f"- {(item.get('current_sample_started_at') or item.get('evaluated_at') or '-')} | "
                f"{item.get('status') or '-'} | {item.get('summary') or '-'}"
            )

    return "\n".join(lines).strip()
