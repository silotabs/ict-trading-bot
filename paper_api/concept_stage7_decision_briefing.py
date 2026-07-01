#!/usr/bin/env python3

from concept_briefing import clean_text, format_percent, utc_now_iso
from concept_stage7_decision_response import build_stage7_decision_response_contract


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalize_stage7_decision_artifact(record):
    item = record if isinstance(record, dict) else {}
    payload = item.get("review") if isinstance(item.get("review"), dict) else {}
    if clean_text(item.get("review_kind")) != "stage7_decision_structured" and clean_text(payload.get("review_kind")) != "stage7_decision_structured":
        return None
    response = payload.get("structured_response") if isinstance(payload.get("structured_response"), dict) else {}
    return {
        "review_id": clean_text(item.get("review_id")) or clean_text(payload.get("review_id")),
        "created_at": clean_text(item.get("created_at")) or clean_text(payload.get("created_at")),
        "review_kind": clean_text(item.get("review_kind")) or clean_text(payload.get("review_kind")),
        "summary": clean_text(item.get("summary")) or clean_text(payload.get("summary")),
        "verdict": clean_text(response.get("verdict")),
        "stage7_readiness": clean_text(response.get("stage7_readiness")),
        "primary_reason": clean_text(response.get("primary_reason")),
        "supporting_evidence": clean_text(response.get("supporting_evidence")),
        "next_action_type": clean_text(response.get("next_action_type")),
        "next_action_focus": clean_text(response.get("next_action_focus")),
        "next_action_summary": clean_text(response.get("next_action_summary")),
        "what_would_change_my_mind": clean_text(response.get("what_would_change_my_mind")),
        "confidence": clean_text(response.get("confidence")),
        "grounding_refs_used": [
            clean_text(value) for value in (response.get("grounding_refs_used") or []) if clean_text(value)
        ],
    }


def build_stage7_decision_gate(acceptance_summary, compare_summary):
    acceptance = acceptance_summary if isinstance(acceptance_summary, dict) else {}
    compare = compare_summary if isinstance(compare_summary, dict) else {}
    acceptance_gate = acceptance.get("acceptance_gate") if isinstance(acceptance.get("acceptance_gate"), dict) else {}
    leader = compare.get("best_ranked_revision") if isinstance(compare.get("best_ranked_revision"), dict) else {}
    latest_compare = compare.get("latest_compare_artifact") if isinstance(compare.get("latest_compare_artifact"), dict) else {}

    ready_for_stage_7 = bool(acceptance.get("ready_for_stage_7")) or bool(acceptance_gate.get("ready_for_stage_7"))
    artifact_count = _safe_int(acceptance.get("acceptance_artifact_count"))
    improved_count = _safe_int(((acceptance_gate.get("metrics") or {}).get("improved_count")))
    regressed_count = _safe_int(((acceptance_gate.get("metrics") or {}).get("regressed_count")))
    candidate_ratio = float(((acceptance_gate.get("metrics") or {}).get("candidate_ratio")) or 0.0)

    checks = [
        {
            "key": "stage6_gate_ready",
            "label": "Stage 6 gate is ready for a Stage 7 decision",
            "blocker_label": "Stage 6 gate is still blocking Stage 7",
            "ok": ready_for_stage_7,
            "detail": clean_text(acceptance_gate.get("summary")) or "Stage 6 readiness is unavailable.",
        },
        {
            "key": "acceptance_artifact_present",
            "label": "at least one Stage 6 acceptance artifact is saved",
            "blocker_label": "no Stage 6 acceptance artifact is saved yet",
            "ok": artifact_count > 0,
            "detail": f"{artifact_count} acceptance artifacts saved.",
        },
        {
            "key": "ranked_leader_present",
            "label": "a ranked revision leader exists",
            "blocker_label": "no ranked revision leader is available",
            "ok": bool(clean_text(leader.get("revision_id"))),
            "detail": clean_text(leader.get("revision_id")) or "no leader",
        },
        {
            "key": "compare_verdict_present",
            "label": "latest compare verdict is available",
            "blocker_label": "no compare verdict is available yet",
            "ok": bool(clean_text(latest_compare.get("verdict"))),
            "detail": clean_text(latest_compare.get("verdict")) or "missing",
        },
    ]

    blockers = [item.get("blocker_label") or item["label"] for item in checks if not item["ok"]]
    primary_reason = clean_text(acceptance.get("primary_blocker")) or clean_text((acceptance_gate.get("blockers") or [None])[0]) or "evidence_thresholds"

    if not ready_for_stage_7:
        status = "blocked_by_stage_6"
        summary = "Stage 7 should not be treated as active yet because Stage 6 still lacks enough proof to support a promotion or rejection decision."
        next_action = clean_text(acceptance.get("acceptance_action")) or clean_text(acceptance_gate.get("next_action")) or "Keep collecting fresh evidence."
        suggested_path = "keep_collecting_evidence"
    elif improved_count > 0:
        status = "ready_for_stage_7_decision"
        summary = "Stage 7 can now judge whether the leading revision is strong enough to justify a one-variable rule review."
        next_action = "Prepare a conservative memo focused on whether the leading revision should become the next one-variable review."
        suggested_path = "queue_one_variable_review"
    elif regressed_count > 0 and improved_count == 0:
        status = "ready_for_stage_7_decision"
        summary = "Stage 7 can now judge whether the current concept direction should be compared against the next concept instead of refined further."
        next_action = "Prepare a conservative memo comparing continued observation against moving to the next concept."
        suggested_path = "compare_next_concept"
    else:
        status = "ready_for_stage_7_decision"
        summary = "Stage 7 can now prepare a conservative memo, but the decision should stay anchored to the saved artifact history."
        next_action = "Prepare a memo that explicitly defends the least-risky next path from the saved acceptance and revision history."
        suggested_path = "queue_one_variable_review"

    return {
        "stage": "stage_7_promotion_or_rejection_decision",
        "status": status,
        "ready_for_stage_7": ready_for_stage_7,
        "summary": summary,
        "next_action": next_action,
        "suggested_path": suggested_path,
        "blockers": blockers,
        "primary_reason": primary_reason,
        "checks": checks,
        "metrics": {
            "candidate_ratio": candidate_ratio,
            "acceptance_artifact_count": artifact_count,
            "improved_count": improved_count,
            "regressed_count": regressed_count,
            "leader_revision_id": clean_text(leader.get("revision_id")),
            "leader_status": clean_text(leader.get("status")),
            "latest_compare_verdict": clean_text(latest_compare.get("verdict")),
        },
        "caveat": "A Stage 7 memo is decision support only. It does not authorize live execution or broad rules changes.",
    }


def build_stage7_decision_tasks(stage7_gate, compare_summary):
    gate = stage7_gate if isinstance(stage7_gate, dict) else {}
    compare = compare_summary if isinstance(compare_summary, dict) else {}
    leader = compare.get("best_ranked_revision") if isinstance(compare.get("best_ranked_revision"), dict) else {}

    tasks = [
        "Validate whether Stage 7 should remain blocked or be treated as decision-ready.",
        "Choose one conservative path: keep collecting evidence, queue a one-variable review, compare the next concept, or reject the current concept direction.",
        "Explain why the current revision leader does or does not justify a Stage 7 decision.",
        "Keep all suggestions compatible with the local house spec, paper-trading protocol, and hard safety gates.",
        "Do not recommend live execution, broker-ready entries, or broad multi-rule edits.",
    ]

    if clean_text(leader.get("revision_id")):
        tasks.append(
            f"Assess whether {leader.get('revision_id')} is a real promotion candidate or still only the least-bad leader."
        )
    if not gate.get("ready_for_stage_7"):
        tasks.append(
            "State exactly what additional evidence would move the project from Stage 6 acceptance testing into a real Stage 7 decision."
        )
    return tasks[:8]


def summarize_stage7_decision(acceptance_summary, compare_summary, review_records):
    gate = build_stage7_decision_gate(acceptance_summary, compare_summary)
    artifacts = [
        item
        for item in (_normalize_stage7_decision_artifact(record) for record in (review_records or []))
        if item is not None
    ]
    latest = artifacts[0] if artifacts else None
    return {
        "decision_artifact_count": len(artifacts),
        "latest_stage7_review_id": clean_text((latest or {}).get("review_id")),
        "latest_stage7_verdict": clean_text((latest or {}).get("verdict")),
        "latest_stage7_artifact": latest,
        "decision_takeaway": clean_text(gate.get("summary")) or "Stage 7 decision guidance is not available yet.",
        "decision_action": clean_text((latest or {}).get("next_action_summary")) or clean_text(gate.get("next_action")),
        "stage7_gate": gate,
    }


def render_concept_stage7_decision_brief_markdown(payload):
    data = payload if isinstance(payload, dict) else {}
    gate = data.get("stage7_gate") if isinstance(data.get("stage7_gate"), dict) else {}
    compare = data.get("compare_summary") if isinstance(data.get("compare_summary"), dict) else {}
    leader = compare.get("best_ranked_revision") if isinstance(compare.get("best_ranked_revision"), dict) else {}
    latest_decision = data.get("latest_stage7_artifact") if isinstance(data.get("latest_stage7_artifact"), dict) else {}

    lines = [
        "# Stage 7 Decision Memo Brief",
        "",
        f"- Generated at: {data.get('generated_at')}",
        f"- Stage 7 gate: {gate.get('status') or 'unknown'}",
        f"- Suggested path: {clean_text(gate.get('suggested_path')) or 'keep_collecting_evidence'}",
        f"- Decision: {(data.get('decision') or {}).get('overall') or '-'} / {(data.get('decision') or {}).get('recommendation') or '-'}",
        f"- Acceptance status: {(data.get('acceptance_summary') or {}).get('latest_acceptance_status') or '-'}",
    ]

    if leader:
        lines.extend(
            [
                "",
                "## Current Leader",
                f"- Revision: {leader.get('revision_id')}",
                f"- Focus: {clean_text(leader.get('focus')) or '-'}",
                f"- Status: {clean_text(leader.get('status')) or '-'}",
                f"- Score: {leader.get('score')}",
            ]
        )

    lines.extend(
        [
            "",
            "## Stage 7 Gate",
            f"- Summary: {gate.get('summary') or '-'}",
            f"- Next action: {gate.get('next_action') or '-'}",
            f"- Candidate ratio: {format_percent(((gate.get('metrics') or {}).get('candidate_ratio')) or 0.0)}",
        ]
    )

    blockers = gate.get("blockers") or []
    if blockers:
        lines.extend(["", "## Current Blockers"])
        for item in blockers:
            lines.append(f"- {item}")

    if latest_decision:
        lines.extend(
            [
                "",
                "## Latest Saved Stage 7 Memo",
                f"- Review: {latest_decision.get('review_id')}",
                f"- Verdict: {clean_text(latest_decision.get('verdict')) or '-'}",
                f"- Reason: {latest_decision.get('primary_reason') or latest_decision.get('summary') or '-'}",
            ]
        )

    tasks = data.get("llm_review_tasks") or []
    if tasks:
        lines.extend(["", "## LLM Review Tasks"])
        for index, task in enumerate(tasks, start=1):
            lines.append(f"{index}. {task}")

    refs = data.get("grounding_refs") or []
    if refs:
        lines.extend(["", "## Grounding Files"])
        for item in refs:
            lines.append(f"- {item.get('label')}: {item.get('path')} — {item.get('purpose')}")

    return "\n".join(lines).strip()


def build_concept_stage7_decision_llm_prompt(payload):
    data = payload if isinstance(payload, dict) else {}
    tasks = data.get("llm_review_tasks") or []
    markdown = data.get("brief_markdown") or render_concept_stage7_decision_brief_markdown(data)
    return (
        "You are reviewing whether Concept 1 is ready for a conservative Stage 7 promotion-or-rejection memo.\n"
        "Stay analysis-only. Do not recommend live order placement, broker-ready execution, or unsafe automation shortcuts.\n"
        "Use the brief below, the listed local grounding files, and the hard safety gates as constraints.\n\n"
        "Return:\n"
        "1. A verdict on whether Stage 7 should remain blocked or move to a conservative decision memo.\n"
        "2. The strongest reason for that verdict.\n"
        "3. One conservative next path.\n"
        "4. What evidence would change your mind.\n\n"
        "Review tasks:\n"
        + "\n".join(f"{index}. {task}" for index, task in enumerate(tasks, start=1))
        + "\n\n"
        + markdown
    )


def build_concept_stage7_decision_brief_packet(
    acceptance_brief,
    review_records=None,
):
    brief = acceptance_brief if isinstance(acceptance_brief, dict) else {}
    acceptance_summary = brief.get("acceptance_summary") if isinstance(brief.get("acceptance_summary"), dict) else {}
    compare_summary = brief.get("compare_summary") if isinstance(brief.get("compare_summary"), dict) else {}

    packet = {
        "generated_at": utc_now_iso(),
        "concept_id": clean_text(brief.get("concept_id")) or "concept-1",
        "decision": brief.get("decision") or {},
        "review": brief.get("review") or {},
        "evidence": brief.get("evidence") or {},
        "pressure_points": brief.get("pressure_points") or {},
        "house_spec": brief.get("house_spec") or {},
        "review_rubric": brief.get("review_rubric") or {},
        "grounding_refs": brief.get("grounding_refs") or [],
        "official_source_highlights": brief.get("official_source_highlights") or [],
        "acceptance_summary": acceptance_summary,
        "compare_summary": compare_summary,
        "stage7_gate": build_stage7_decision_gate(acceptance_summary, compare_summary),
        "ranked_revisions": (compare_summary.get("ranked_revisions") or [])[:3],
    }
    packet.update(summarize_stage7_decision(acceptance_summary, compare_summary, review_records or []))
    packet["llm_review_tasks"] = build_stage7_decision_tasks(packet.get("stage7_gate"), compare_summary)
    packet["llm_response_contract"] = build_stage7_decision_response_contract()
    packet["brief_markdown"] = render_concept_stage7_decision_brief_markdown(packet)
    packet["llm_prompt"] = build_concept_stage7_decision_llm_prompt(packet)
    return packet
