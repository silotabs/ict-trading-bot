#!/usr/bin/env python3

import json

from concept_briefing import clean_text, format_percent, utc_now_iso
from concept_revision_compare_response import build_revision_compare_response_contract


def _normalize_review_record(record):
    item = record if isinstance(record, dict) else {}
    payload = item.get("review") if isinstance(item.get("review"), dict) else {}
    return {
        "review_id": clean_text(item.get("review_id")) or clean_text(payload.get("review_id")),
        "created_at": clean_text(item.get("created_at")) or clean_text(payload.get("created_at")),
        "source": clean_text(item.get("source")) or clean_text(payload.get("source")),
        "author": clean_text(item.get("author")) or clean_text(payload.get("author")),
        "review_kind": clean_text(item.get("review_kind")) or clean_text(payload.get("review_kind")),
        "overall": clean_text(item.get("overall")) or clean_text(payload.get("overall")),
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
        "source": clean_text(item.get("source")) or clean_text(payload.get("source")),
        "author": clean_text(item.get("author")) or clean_text(payload.get("author")),
        "focus": clean_text(item.get("focus")) or clean_text(payload.get("focus")),
        "status": clean_text(item.get("status")) or clean_text(payload.get("status")) or clean_text(latest.get("status")) or "planned",
        "summary": clean_text(item.get("summary")) or clean_text(payload.get("summary")) or "concept revision",
        "latest_evaluation": latest,
    }


def build_revision_compare_tasks(compare_summary):
    compare = compare_summary if isinstance(compare_summary, dict) else {}
    tasks = [
        "Validate whether the current ranked revision leader really deserves to stay the leader.",
        "Explain whether the revision loop is still too flat to justify a rules change.",
        "Recommend one conservative next action: keep collecting evidence, continue the current leader, or queue one new one-variable review.",
        "Keep all suggestions compatible with the local house spec, paper-trading protocol, and hard safety gates.",
        "Do not recommend live execution, broker-ready entries, or broad multi-rule edits.",
    ]

    leader = compare.get("best_ranked_revision") if isinstance(compare.get("best_ranked_revision"), dict) else {}
    if clean_text(leader.get("focus")):
        tasks.append(
            f"Assess whether the current leader focus ({leader.get('focus')}) is a true improvement path or just the least-bad flat result."
        )

    improved_count = int((compare.get("status_counts") or {}).get("improved") or 0)
    if improved_count <= 0:
        tasks.append(
            "Because no saved revision is clearly improved yet, say what evidence would be needed before promoting any revision."
        )

    if int(compare.get("evaluation_history_count") or 0) > 0:
        tasks.append(
            "Use the fresh-sample evaluation history to distinguish stable flat behavior from true improvement."
        )

    return tasks


def build_revision_compare_llm_prompt(packet):
    payload = packet if isinstance(packet, dict) else {}
    tasks = payload.get("llm_review_tasks") or []
    response_contract = payload.get("llm_response_contract") or {}
    prompt_lines = [
        "You are reviewing a conservative ICT concept-revision loop for paper trading only.",
        "Stay analysis-only. Do not recommend live order placement, broker-ready execution, or unsafe automation shortcuts.",
        "Use the brief below, the local grounding files, and the hard safety gates as constraints.",
        "Return valid JSON that matches the response contract exactly.",
        "",
        "Return:",
        "1. A verdict on whether the current revision leader should stay the leader.",
        "2. The main reason the loop is still flat or promising.",
        "3. One conservative next action.",
        "4. What evidence would change your mind.",
        "",
        "Review tasks:",
    ]
    for index, task in enumerate(tasks, start=1):
        prompt_lines.append(f"{index}. {task}")
    if response_contract:
        prompt_lines.extend(
            [
                "",
                "Response contract:",
                json.dumps(response_contract, indent=2, sort_keys=True),
            ]
        )
    prompt_lines.extend(["", payload.get("brief_markdown") or ""])
    return "\n".join(prompt_lines).strip()


def render_concept_revision_brief_markdown(packet):
    payload = packet if isinstance(packet, dict) else {}
    decision = payload.get("decision") or {}
    evidence = payload.get("evidence") or {}
    pressure = payload.get("pressure_points") or {}
    compare = payload.get("compare_summary") or {}
    leader = compare.get("best_ranked_revision") or {}
    latest_compare = compare.get("latest_compare_artifact") or {}
    ranked = payload.get("ranked_revisions") or []
    reviews = payload.get("recent_reviews") or []
    lines = [
        "# Concept Revision Compare Brief",
        "",
        f"- Generated at: {payload.get('generated_at')}",
        f"- Concept: {payload.get('concept_id') or '-'}",
        f"- Current decision: {(decision.get('overall') or '-')} / {(decision.get('recommendation') or '-')}",
        f"- Revision takeaway: {compare.get('takeaway') or '-'}",
        f"- Next action: {compare.get('next_action') or '-'}",
        "",
        "## Concept State",
        f"- Candidate ratio: {format_percent(pressure.get('candidate_ratio'))}",
        f"- Dominant blocker: {((pressure.get('dominant_blocker') or {}).get('blocker') or '-')} at {format_percent((pressure.get('dominant_blocker') or {}).get('ratio'))}",
        f"- Cross-market gap: {((pressure.get('cross_market_gap') or {}).get('blocker') or '-')} at {format_percent((pressure.get('cross_market_gap') or {}).get('gap'))}",
        f"- Evidence counts: scans {evidence.get('recent_scans', 0)}, proposals {evidence.get('recent_proposals', 0)}, execution-state {evidence.get('recent_execution_state', 0)}",
        "",
        "## Revision Loop Summary",
        f"- Reviews: {compare.get('review_count', 0)}",
        f"- Revisions: {compare.get('revision_count', 0)}",
        f"- Saved compare artifacts: {compare.get('compare_artifact_count', 0)}",
        f"- Evaluation history entries: {compare.get('evaluation_history_count', 0)}",
        f"- Latest sample: {compare.get('latest_sample_started_at') or '-'}",
    ]

    if leader:
        lines.extend(
            [
                "",
                "## Current Leader",
                f"- Revision: {leader.get('revision_id') or '-'}",
                f"- Focus: {leader.get('focus') or '-'}",
                f"- Status: {leader.get('status') or '-'}",
                f"- Score: {leader.get('score') or 0}",
                f"- Summary: {leader.get('summary') or '-'}",
            ]
        )
        for reason in (leader.get("reasons") or [])[:3]:
            lines.append(f"- Reason: {reason}")

    if latest_compare:
        lines.extend(
            [
                "",
                "## Latest Compare Guidance",
                f"- Review: {latest_compare.get('review_id') or '-'}",
                f"- Verdict: {latest_compare.get('verdict') or '-'}",
                f"- Leader: {latest_compare.get('leader_revision_id') or '-'}",
                f"- Challenger: {latest_compare.get('challenger_revision_id') or '-'}",
                f"- Explanation: {compare.get('leader_explanation') or latest_compare.get('comparison_summary') or '-'}",
                f"- Next action: {compare.get('compare_action') or latest_compare.get('next_action_summary') or '-'}",
            ]
        )

    if ranked:
        lines.extend(["", "## Ranked Revisions"])
        for item in ranked[:3]:
            lines.append(
                f"- {item.get('revision_id') or '-'} | focus {item.get('focus') or '-'} | "
                f"status {item.get('status') or '-'} | score {item.get('score') or 0}"
            )
            lines.append(f"  summary: {item.get('summary') or '-'}")
            for reason in (item.get("reasons") or [])[:2]:
                lines.append(f"  - {reason}")

    if reviews:
        lines.extend(["", "## Linked Reviews"])
        for item in reviews[:3]:
            lines.append(
                f"- {item.get('review_id') or '-'} | {(item.get('recommendation') or '-')}"
                f" | blocker {(item.get('primary_blocker') or '-')}"
            )
            lines.append(f"  summary: {item.get('summary') or '-'}")

    guardrails = (payload.get("house_spec") or {}).get("hard_safety_gates") or []
    if guardrails:
        lines.extend(["", "## Guardrails"])
        for item in guardrails[:6]:
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


def build_concept_revision_brief_packet(base_brief, compare_summary, revision_records, review_records, top_limit=3):
    brief = base_brief if isinstance(base_brief, dict) else {}
    compare = compare_summary if isinstance(compare_summary, dict) else {}
    revisions = [_normalize_revision_record(item) for item in (revision_records or [])]
    reviews = [_normalize_review_record(item) for item in (review_records or [])]
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
        "ranked_revisions": (compare.get("ranked_revisions") or [])[: max(1, int(top_limit or 3))],
        "recent_reviews": reviews[: max(1, int(top_limit or 3))],
        "recent_revisions": revisions[: max(1, int(top_limit or 3))],
    }
    packet["llm_review_tasks"] = build_revision_compare_tasks(compare)
    packet["llm_response_contract"] = build_revision_compare_response_contract()
    packet["brief_markdown"] = render_concept_revision_brief_markdown(packet)
    packet["llm_prompt"] = build_revision_compare_llm_prompt(packet)
    return packet
