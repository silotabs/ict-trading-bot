#!/usr/bin/env python3

from concept_briefing import clean_text, format_percent, utc_now_iso
from concept_acceptance_response import build_acceptance_response_contract
from concept_revision import build_stage5_readiness


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


def _normalize_review_record(record):
    item = record if isinstance(record, dict) else {}
    payload = item.get("review") if isinstance(item.get("review"), dict) else {}
    return {
        "review_id": clean_text(item.get("review_id")) or clean_text(payload.get("review_id")),
        "created_at": clean_text(item.get("created_at")) or clean_text(payload.get("created_at")),
        "review_kind": clean_text(item.get("review_kind")) or clean_text(payload.get("review_kind")),
        "recommendation": clean_text(item.get("recommendation")) or clean_text(payload.get("recommendation")),
        "primary_blocker": clean_text(item.get("primary_blocker")) or clean_text(payload.get("primary_blocker")),
        "summary": clean_text(item.get("summary")) or clean_text(payload.get("summary")) or "concept review",
    }


def _normalize_revision_record(record):
    item = record if isinstance(record, dict) else {}
    payload = item.get("revision") if isinstance(item.get("revision"), dict) else {}
    latest = payload.get("latest_evaluation") if isinstance(payload.get("latest_evaluation"), dict) else {}
    return {
        "revision_id": clean_text(item.get("revision_id")) or clean_text(payload.get("revision_id")),
        "review_id": clean_text(item.get("review_id")) or clean_text(payload.get("review_id")),
        "created_at": clean_text(item.get("created_at")) or clean_text(payload.get("generated_at")),
        "focus": clean_text(item.get("focus")) or clean_text(payload.get("focus")),
        "status": clean_text(item.get("status")) or clean_text(payload.get("status")) or clean_text(latest.get("status")) or "planned",
        "summary": clean_text(item.get("summary")) or clean_text(payload.get("summary")) or "concept revision",
        "latest_evaluation": latest,
    }


def _normalize_acceptance_artifact(record):
    item = record if isinstance(record, dict) else {}
    payload = item.get("review") if isinstance(item.get("review"), dict) else {}
    if clean_text(item.get("review_kind")) != "acceptance_structured" and clean_text(payload.get("review_kind")) != "acceptance_structured":
        return None
    response = payload.get("structured_response") if isinstance(payload.get("structured_response"), dict) else {}
    return {
        "review_id": clean_text(item.get("review_id")) or clean_text(payload.get("review_id")),
        "created_at": clean_text(item.get("created_at")) or clean_text(payload.get("created_at")),
        "review_kind": clean_text(item.get("review_kind")) or clean_text(payload.get("review_kind")),
        "summary": clean_text(item.get("summary")) or clean_text(payload.get("summary")),
        "verdict": clean_text(response.get("verdict")),
        "stage6_status": clean_text(response.get("stage6_status")),
        "primary_blocker": clean_text(response.get("primary_blocker")) or clean_text(item.get("primary_blocker")) or clean_text(payload.get("primary_blocker")),
        "next_action_type": clean_text(response.get("next_action_type")),
        "next_action_focus": clean_text(response.get("next_action_focus")),
        "next_action_summary": clean_text(response.get("next_action_summary")),
        "what_would_change_my_mind": clean_text(response.get("what_would_change_my_mind")),
        "confidence": clean_text(response.get("confidence")),
        "grounding_refs_used": [
            clean_text(value) for value in (response.get("grounding_refs_used") or []) if clean_text(value)
        ],
    }


def build_acceptance_evidence_progress(base_brief):
    brief = base_brief if isinstance(base_brief, dict) else {}
    evidence = brief.get("evidence") if isinstance(brief.get("evidence"), dict) else {}
    pressure = brief.get("pressure_points") if isinstance(brief.get("pressure_points"), dict) else {}
    unmet_items = evidence.get("unmet_thresholds") if isinstance(evidence.get("unmet_thresholds"), list) else []
    unmet_by_metric = {
        clean_text(item.get("metric")): item
        for item in unmet_items
        if isinstance(item, dict) and clean_text(item.get("metric"))
    }

    threshold_specs = [
        ("recent_proposal_count", "proposals", _safe_int(evidence.get("recent_proposals")), 2),
        ("recent_action_count", "actions", _safe_int(evidence.get("recent_actions")), 2),
        ("recent_execution_state_count", "execution", _safe_int(evidence.get("recent_execution_state")), 2),
    ]

    thresholds = []
    for key, label, default_actual, default_required in threshold_specs:
        unmet = unmet_by_metric.get(key) or {}
        actual = _safe_int(unmet.get("actual")) if unmet else default_actual
        required = _safe_int(unmet.get("required")) if unmet else default_required
        thresholds.append(
            {
                "key": key,
                "label": label,
                "actual": actual,
                "required": required,
                "met": actual >= required if required > 0 else True,
            }
        )

    thresholds_total_count = len(thresholds)
    thresholds_met_count = sum(1 for item in thresholds if item["met"])
    threshold_progress_ratio = (
        float(thresholds_met_count) / float(thresholds_total_count) if thresholds_total_count else 0.0
    )
    next_needed = next((item for item in thresholds if not item["met"]), None)
    candidate_ratio = _safe_float(pressure.get("candidate_ratio"))

    return {
        "thresholds": thresholds,
        "thresholds_total_count": thresholds_total_count,
        "thresholds_met_count": thresholds_met_count,
        "threshold_progress_ratio": threshold_progress_ratio,
        "next_needed_metric": clean_text((next_needed or {}).get("key")),
        "next_needed_label": clean_text((next_needed or {}).get("label")),
        "candidate_ratio": candidate_ratio,
        "latest_counts": {
            "recent_scans": _safe_int(evidence.get("recent_scans")),
            "recent_proposals": _safe_int(evidence.get("recent_proposals")),
            "recent_actions": _safe_int(evidence.get("recent_actions")),
            "recent_execution_state": _safe_int(evidence.get("recent_execution_state")),
            "working_orders": _safe_int(evidence.get("working_orders")),
            "open_positions": _safe_int(evidence.get("open_positions")),
        },
        "progress_summary": (
            f"{thresholds_met_count}/{thresholds_total_count} thresholds met"
            + (
                f" · next {clean_text((next_needed or {}).get('label'))} "
                f"{(next_needed or {}).get('actual')}/{(next_needed or {}).get('required')}"
                if next_needed
                else " · all minimum thresholds met"
            )
        ),
    }


def build_stage6_acceptance_gate(base_brief, compare_summary, live_compare=None):
    brief = base_brief if isinstance(base_brief, dict) else {}
    compare = compare_summary if isinstance(compare_summary, dict) else {}
    live = live_compare if isinstance(live_compare, dict) else {}
    evidence = brief.get("evidence") or {}
    pressure = brief.get("pressure_points") or {}

    stage5 = compare.get("stage5_readiness")
    if not isinstance(stage5, dict):
        stage5 = build_stage5_readiness(compare, live)

    unmet = evidence.get("unmet_thresholds") or []
    compare_artifact_count = _safe_int(compare.get("compare_artifact_count"))
    review_count = _safe_int(compare.get("review_count"))
    revision_count = _safe_int(compare.get("revision_count"))
    evaluation_history_count = _safe_int(compare.get("evaluation_history_count"))
    leader = compare.get("best_ranked_revision") if isinstance(compare.get("best_ranked_revision"), dict) else {}
    leader_history_count = _safe_int(leader.get("history_count"))
    leader_status = clean_text(leader.get("status")) or "-"
    status_counts = compare.get("status_counts") if isinstance(compare.get("status_counts"), dict) else {}
    improved_count = _safe_int(status_counts.get("improved"))
    regressed_count = _safe_int(status_counts.get("regressed"))
    candidate_ratio = pressure.get("candidate_ratio") or 0.0
    try:
        candidate_ratio = float(candidate_ratio)
    except (TypeError, ValueError):
        candidate_ratio = 0.0

    checks = [
        {
            "key": "stage5_ready",
            "label": "Stage 5 daemon guidance is operationally stable",
            "blocker_label": "Stage 5 daemon guidance is not yet operationally stable",
            "ok": bool((stage5 or {}).get("ready_for_stage_6_from_daemon_state")),
            "required_for_stage6": True,
            "required_for_stage7": True,
            "detail": (stage5 or {}).get("summary") or "Stage 5 readiness has not passed yet.",
        },
        {
            "key": "evidence_thresholds_met",
            "label": "concept evidence thresholds are met",
            "blocker_label": "concept evidence thresholds are still unmet",
            "ok": len(unmet) == 0,
            "required_for_stage6": False,
            "required_for_stage7": True,
            "detail": (
                "All minimum evidence thresholds are currently satisfied."
                if not unmet
                else ", ".join(
                    f"{item.get('metric')} {item.get('actual')}/{item.get('required')}" for item in unmet[:3]
                )
            ),
        },
        {
            "key": "fresh_sample_history_meaningful",
            "label": "fresh-sample revision history is deep enough",
            "blocker_label": "fresh-sample revision history is still too shallow",
            "ok": evaluation_history_count >= 12 and leader_history_count >= 5,
            "required_for_stage6": False,
            "required_for_stage7": True,
            "detail": (
                f"{evaluation_history_count} evaluation entries, leader history {leader_history_count}."
                if evaluation_history_count or leader_history_count
                else "Revision history is still shallow."
            ),
        },
        {
            "key": "artifacts_present",
            "label": "saved review, revision, and compare artifacts exist",
            "blocker_label": "saved review, revision, or compare artifacts are missing",
            "ok": review_count > 0 and revision_count > 0 and compare_artifact_count > 0,
            "required_for_stage6": False,
            "required_for_stage7": True,
            "detail": (
                f"reviews={review_count}, revisions={revision_count}, compare_artifacts={compare_artifact_count}"
            ),
        },
        {
            "key": "decision_signal_present",
            "label": "a revision outcome has moved beyond flat observation",
            "blocker_label": "revision outcomes are still mostly flat",
            "ok": improved_count > 0 or regressed_count > 0,
            "required_for_stage6": False,
            "required_for_stage7": True,
            "detail": (
                f"improved={improved_count}, regressed={regressed_count}, leader_status={leader_status}"
            ),
        },
    ]

    stage6_started = bool((stage5 or {}).get("ready_for_stage_6_from_daemon_state"))
    stage7_blockers = [item.get("blocker_label") or item["label"] for item in checks if item["required_for_stage7"] and not item["ok"]]

    if not stage6_started:
        status = "blocked_by_stage_5"
        summary = "Acceptance testing should not be treated as active yet because the Stage 5 daemon guidance gate is not stable."
        next_action = "Keep stabilizing the compare-guidance loop before calling this acceptance testing."
        provisional_outcome = "hold_stage_5"
    elif unmet:
        status = "collecting_evidence"
        summary = "Stage 6 is active, but concept proof is still blocked by missing proposal, action, and execution-state evidence."
        next_action = "Keep collecting fresh evidence until the minimum thresholds are met before judging concept proof."
        provisional_outcome = "collect_more_evidence"
    elif stage7_blockers:
        status = "observing_revision_outcomes"
        summary = "Acceptance testing is active, but the revision loop is still too flat or immature to justify a Stage 7 decision."
        next_action = compare.get("next_action") or "Keep observing the current leader across more fresh samples."
        provisional_outcome = "continue_current_leader"
    else:
        status = "ready_for_stage_7_decision"
        summary = "Acceptance testing now has enough evidence and revision movement to prepare a conservative promotion or rejection decision."
        next_action = "Prepare a Stage 7 decision memo using the saved review, revision, and compare history."
        provisional_outcome = "prepare_stage_7_decision"

    return {
        "stage": "stage_6_concept_proof_acceptance_testing",
        "status": status,
        "stage6_started": stage6_started,
        "ready_for_stage_7": status == "ready_for_stage_7_decision",
        "summary": summary,
        "next_action": next_action,
        "provisional_outcome": provisional_outcome,
        "blockers": stage7_blockers if stage6_started else [checks[0].get("blocker_label") or checks[0]["label"]],
        "checks": checks,
        "metrics": {
            "candidate_ratio": candidate_ratio,
            "compare_artifact_count": compare_artifact_count,
            "review_count": review_count,
            "revision_count": revision_count,
            "evaluation_history_count": evaluation_history_count,
            "leader_history_count": leader_history_count,
            "improved_count": improved_count,
            "regressed_count": regressed_count,
            "leader_status": leader_status,
        },
        "caveat": "Stage 6 status means concept proof is being tested, not that the concept is accepted.",
    }


def summarize_concept_acceptance(base_brief, compare_summary, review_records, live_compare=None):
    gate = build_stage6_acceptance_gate(base_brief, compare_summary, live_compare)
    evidence_progress = build_acceptance_evidence_progress(base_brief)
    artifacts = [
        item
        for item in (_normalize_acceptance_artifact(record) for record in (review_records or []))
        if item is not None
    ]
    latest = artifacts[0] if artifacts else None
    primary_blocker = (
        clean_text((latest or {}).get("primary_blocker"))
        or clean_text((gate.get("blockers") or [None])[0])
        or "evidence_thresholds"
    )
    return {
        "acceptance_artifact_count": len(artifacts),
        "latest_acceptance_review_id": clean_text((latest or {}).get("review_id")),
        "latest_acceptance_verdict": clean_text((latest or {}).get("verdict")),
        "latest_acceptance_status": clean_text((latest or {}).get("stage6_status")) or clean_text(gate.get("status")),
        "primary_blocker": primary_blocker,
        "takeaway": clean_text(gate.get("summary")) or "Stage 6 acceptance guidance is not available yet.",
        "acceptance_explanation": clean_text((latest or {}).get("summary")) or clean_text(gate.get("summary")),
        "acceptance_action": clean_text((latest or {}).get("next_action_summary")) or clean_text(gate.get("next_action")),
        "ready_for_stage_7": bool(gate.get("ready_for_stage_7")),
        "evidence_progress": evidence_progress,
        "latest_acceptance_artifact": latest,
        "acceptance_gate": gate,
    }


def build_concept_acceptance_tasks(acceptance_gate, compare_summary):
    gate = acceptance_gate if isinstance(acceptance_gate, dict) else {}
    compare = compare_summary if isinstance(compare_summary, dict) else {}
    tasks = [
        "Validate whether the current Stage 6 acceptance status matches the live concept evidence.",
        "Name the single strongest blocker preventing a Stage 7 promotion or rejection decision.",
        "Say whether the concept is still blocked by missing evidence, flat revisions, or a repeated structural failure mode.",
        "Recommend one conservative next action: keep collecting evidence, continue observing the current leader, or prepare a Stage 7 decision only if the saved history justifies it.",
        "Keep all suggestions compatible with the local house spec, paper-trading protocol, and hard safety gates.",
        "Do not recommend live execution, broker-ready entries, or broad multi-rule edits.",
    ]

    leader = compare.get("best_ranked_revision") if isinstance(compare.get("best_ranked_revision"), dict) else {}
    if clean_text(leader.get("focus")):
        tasks.append(
            f"Explain whether the current leader focus ({leader.get('focus')}) is a real proof path or just an observation placeholder."
        )

    if not gate.get("ready_for_stage_7"):
        tasks.append(
            "State exactly what evidence would move the project from Stage 6 acceptance testing to Stage 7 decision-making."
        )

    return tasks[:8]


def build_concept_acceptance_llm_prompt(packet):
    payload = packet if isinstance(packet, dict) else {}
    tasks = payload.get("llm_review_tasks") or []
    response_contract = payload.get("llm_response_contract") or {}
    prompt_lines = [
        "You are reviewing Stage 6 acceptance testing for a conservative ICT paper-trading concept.",
        "Stay analysis-only. Do not recommend live order placement, broker-ready execution, or unsafe automation shortcuts.",
        "Use the brief below, the local grounding files, and the hard safety gates as constraints.",
        "Return valid JSON that matches the response contract exactly.",
        "",
        "Return:",
        "1. Whether the current acceptance status is sound.",
        "2. The main blocker preventing Stage 7.",
        "3. One conservative next action.",
        "4. What evidence would change your mind.",
        "",
        "Review tasks:",
    ]
    for index, task in enumerate(tasks, start=1):
        prompt_lines.append(f"{index}. {task}")
    if response_contract:
        import json

        prompt_lines.extend(
            [
                "",
                "Response contract:",
                json.dumps(response_contract, indent=2, sort_keys=True),
            ]
        )
    prompt_lines.extend(["", payload.get("brief_markdown") or ""])
    return "\n".join(prompt_lines).strip()


def render_concept_acceptance_brief_markdown(packet):
    payload = packet if isinstance(packet, dict) else {}
    decision = payload.get("decision") or {}
    evidence = payload.get("evidence") or {}
    pressure = payload.get("pressure_points") or {}
    compare = payload.get("compare_summary") or {}
    gate = payload.get("acceptance_gate") or {}
    leader = compare.get("best_ranked_revision") or {}
    lines = [
        "# Concept Acceptance Brief",
        "",
        f"- Generated at: {payload.get('generated_at')}",
        f"- Concept: {payload.get('concept_id') or '-'}",
        f"- Stage: Stage 6 / Concept Proof Acceptance Testing",
        f"- Decision: {(decision.get('overall') or '-')} / {(decision.get('recommendation') or '-')}",
        f"- Acceptance status: {gate.get('status') or '-'}",
        f"- Summary: {gate.get('summary') or '-'}",
        f"- Next action: {gate.get('next_action') or '-'}",
        "",
        "## Live Evidence",
        f"- Recent scans: {evidence.get('recent_scans', 0)}",
        f"- Recent proposals: {evidence.get('recent_proposals', 0)}",
        f"- Recent actions: {evidence.get('recent_actions', 0)}",
        f"- Recent execution-state rows: {evidence.get('recent_execution_state', 0)}",
        f"- Candidate ratio: {format_percent(pressure.get('candidate_ratio'))}",
        f"- Dominant blocker: {((pressure.get('dominant_blocker') or {}).get('blocker') or '-')} at {format_percent((pressure.get('dominant_blocker') or {}).get('ratio'))}",
        f"- Cross-market gap: {((pressure.get('cross_market_gap') or {}).get('blocker') or '-')} at {format_percent((pressure.get('cross_market_gap') or {}).get('gap'))}",
        "",
        "## Revision Loop",
        f"- Reviews: {compare.get('review_count', 0)}",
        f"- Revisions: {compare.get('revision_count', 0)}",
        f"- Compare artifacts: {compare.get('compare_artifact_count', 0)}",
        f"- Evaluation history: {compare.get('evaluation_history_count', 0)}",
        f"- Current leader: {leader.get('revision_id') or '-'}",
        f"- Leader status: {leader.get('status') or '-'}",
        f"- Leader score: {leader.get('score') or 0}",
        f"- Compare takeaway: {compare.get('takeaway') or '-'}",
    ]

    checks = gate.get("checks") or []
    if checks:
        lines.extend(["", "## Acceptance Gate Checks"])
        for item in checks:
            marker = "PASS" if item.get("ok") else "HOLD"
            lines.append(f"- {marker}: {item.get('label')} — {item.get('detail')}")

    blockers = gate.get("blockers") or []
    if blockers:
        lines.extend(["", "## Current Blockers"])
        for item in blockers:
            lines.append(f"- {item}")

    tasks = payload.get("llm_review_tasks") or []
    if tasks:
        lines.extend(["", "## LLM Review Tasks"])
        for index, task in enumerate(tasks, start=1):
            lines.append(f"{index}. {task}")

    refs = payload.get("grounding_refs") or []
    if refs:
        lines.extend(["", "## Grounding Files"])
        for item in refs:
            lines.append(f"- {item.get('label')}: {item.get('path')} — {item.get('purpose')}")

    return "\n".join(lines).strip()


def build_concept_acceptance_brief_packet(
    base_brief,
    compare_summary,
    live_compare=None,
    review_records=None,
    revision_records=None,
    top_limit=3,
):
    brief = base_brief if isinstance(base_brief, dict) else {}
    compare = compare_summary if isinstance(compare_summary, dict) else {}
    gate = build_stage6_acceptance_gate(brief, compare, live_compare)
    packet = {
        "generated_at": utc_now_iso(),
        "concept_id": clean_text(brief.get("concept_id")) or "concept-1",
        "decision": brief.get("decision") or {},
        "review": brief.get("review") or {},
        "evidence": brief.get("evidence") or {},
        "pressure_points": brief.get("pressure_points") or {},
        "next_focus": brief.get("next_focus") or [],
        "house_spec": brief.get("house_spec") or {},
        "review_rubric": brief.get("review_rubric") or {},
        "grounding_refs": brief.get("grounding_refs") or [],
        "official_source_highlights": brief.get("official_source_highlights") or [],
        "compare_summary": compare,
        "acceptance_gate": gate,
        "ranked_revisions": (compare.get("ranked_revisions") or [])[: max(1, int(top_limit or 3))],
        "recent_reviews": [
            _normalize_review_record(item) for item in (review_records or [])[: max(1, int(top_limit or 3))]
        ],
        "recent_revisions": [
            _normalize_revision_record(item) for item in (revision_records or [])[: max(1, int(top_limit or 3))]
        ],
    }
    packet["acceptance_summary"] = summarize_concept_acceptance(
        brief,
        compare,
        review_records or [],
        live_compare=live_compare,
    )
    packet["llm_review_tasks"] = build_concept_acceptance_tasks(gate, compare)
    packet["llm_response_contract"] = build_acceptance_response_contract()
    packet["brief_markdown"] = render_concept_acceptance_brief_markdown(packet)
    packet["llm_prompt"] = build_concept_acceptance_llm_prompt(packet)
    return packet
