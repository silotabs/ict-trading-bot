#!/usr/bin/env python3

from concept_briefing import clean_text


ALLOWED_VERDICTS = {
    "keep_current_leader",
    "promote_runner_up",
    "hold_revision_loop",
}
ALLOWED_NEXT_ACTION_TYPES = {
    "keep_collecting_evidence",
    "review_regressed_revision",
    "queue_one_variable_review",
    "promote_revision_candidate",
}
ALLOWED_CONFIDENCE = {"low", "medium", "high"}


def build_revision_compare_response_contract():
    return {
        "required_fields": [
            "verdict",
            "leader_revision_id",
            "comparison_summary",
            "primary_risk",
            "next_action_type",
            "next_action_focus",
            "next_action_summary",
            "what_would_change_my_mind",
            "confidence",
            "grounding_refs_used",
        ],
        "field_rules": {
            "verdict": sorted(ALLOWED_VERDICTS),
            "next_action_type": sorted(ALLOWED_NEXT_ACTION_TYPES),
            "confidence": sorted(ALLOWED_CONFIDENCE),
            "challenger_revision_id": "Optional runner-up revision id when the verdict is promote_runner_up.",
            "grounding_refs_used": "Array of grounding reference labels or file paths used by the comparison.",
        },
        "example": {
            "verdict": "hold_revision_loop",
            "leader_revision_id": "RV-00002",
            "challenger_revision_id": "",
            "comparison_summary": "The current leader is still only the least-bad revision because all linked revisions remain regressed.",
            "primary_risk": "The loop is still too flat and regressed to justify promoting a rules change.",
            "next_action_type": "review_regressed_revision",
            "next_action_focus": "displacement",
            "next_action_summary": "Review the regressed displacement-focused revision before queuing any new rule edit.",
            "what_would_change_my_mind": "A fresh-sample evaluation that stabilizes to flat or improved while preserving guardrails would justify keeping the current leader.",
            "confidence": "medium",
            "grounding_refs_used": [
                "House Spec",
                "Review Rubric",
                "Initial Source Map",
            ],
        },
    }


def validate_revision_compare_response(response_payload):
    payload = response_payload if isinstance(response_payload, dict) else {}
    errors = []

    verdict = clean_text(payload.get("verdict"))
    if verdict not in ALLOWED_VERDICTS:
        errors.append(f"verdict must be one of: {', '.join(sorted(ALLOWED_VERDICTS))}")

    leader_revision_id = clean_text(payload.get("leader_revision_id"))
    if not leader_revision_id:
        errors.append("leader_revision_id is required")

    challenger_revision_id = clean_text(payload.get("challenger_revision_id"))
    if verdict == "promote_runner_up" and not challenger_revision_id:
        errors.append("challenger_revision_id is required when verdict is promote_runner_up")

    comparison_summary = clean_text(payload.get("comparison_summary"))
    if not comparison_summary:
        errors.append("comparison_summary is required")

    primary_risk = clean_text(payload.get("primary_risk"))
    if not primary_risk:
        errors.append("primary_risk is required")

    next_action_type = clean_text(payload.get("next_action_type"))
    if next_action_type not in ALLOWED_NEXT_ACTION_TYPES:
        errors.append(
            f"next_action_type must be one of: {', '.join(sorted(ALLOWED_NEXT_ACTION_TYPES))}"
        )

    next_action_focus = clean_text(payload.get("next_action_focus"))
    if not next_action_focus:
        errors.append("next_action_focus is required")

    next_action_summary = clean_text(payload.get("next_action_summary"))
    if not next_action_summary:
        errors.append("next_action_summary is required")

    what_would_change_my_mind = clean_text(payload.get("what_would_change_my_mind"))
    if not what_would_change_my_mind:
        errors.append("what_would_change_my_mind is required")

    confidence = clean_text(payload.get("confidence"))
    if confidence not in ALLOWED_CONFIDENCE:
        errors.append(f"confidence must be one of: {', '.join(sorted(ALLOWED_CONFIDENCE))}")

    refs = payload.get("grounding_refs_used")
    if not isinstance(refs, list) or not [clean_text(item) for item in refs if clean_text(item)]:
        errors.append("grounding_refs_used must contain at least one reference label or path")
        refs = []

    normalized = {
        "verdict": verdict,
        "leader_revision_id": leader_revision_id,
        "challenger_revision_id": challenger_revision_id,
        "comparison_summary": comparison_summary,
        "primary_risk": primary_risk,
        "next_action_type": next_action_type,
        "next_action_focus": next_action_focus,
        "next_action_summary": next_action_summary,
        "what_would_change_my_mind": what_would_change_my_mind,
        "confidence": confidence,
        "grounding_refs_used": [clean_text(item) for item in refs if clean_text(item)],
    }
    return {
        "ok": not errors,
        "errors": errors,
        "response": normalized,
    }


def build_structured_revision_compare_record(validated_response, brief_packet, *, source, author):
    brief = brief_packet if isinstance(brief_packet, dict) else {}
    response = validated_response if isinstance(validated_response, dict) else {}
    decision = brief.get("decision") or {}
    pressure = brief.get("pressure_points") or {}

    summary = (
        f"{response.get('verdict') or 'revision_compare'}: "
        f"{response.get('next_action_summary') or response.get('comparison_summary') or 'revision comparison'}"
    )
    return {
        "concept_id": clean_text(brief.get("concept_id")) or "concept-1",
        "source": clean_text(source) or "llm",
        "author": clean_text(author),
        "review_kind": "revision_compare_structured",
        "overall": clean_text(decision.get("overall")) or "collecting",
        "recommendation": clean_text(response.get("verdict")),
        "primary_blocker": clean_text(
            response.get("next_action_focus")
            or ((pressure.get("dominant_blocker") or {}).get("blocker"))
        ),
        "summary": summary[:400],
        "structured_response": response,
        "concept_brief": brief,
    }
