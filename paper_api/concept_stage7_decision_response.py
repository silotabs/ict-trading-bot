#!/usr/bin/env python3

from concept_briefing import clean_text


ALLOWED_VERDICTS = {
    "keep_collecting_evidence",
    "queue_one_variable_review",
    "compare_next_concept",
    "reject_current_concept",
}
ALLOWED_STAGE7_READINESS = {
    "blocked_by_stage_6",
    "ready_for_stage_7_decision",
}
ALLOWED_NEXT_ACTION_TYPES = {
    "collect_evidence",
    "review_one_rule",
    "compare_next_concept",
    "reject_concept",
}
ALLOWED_CONFIDENCE = {"low", "medium", "high"}


def build_stage7_decision_response_contract():
    return {
        "required_fields": [
            "verdict",
            "stage7_readiness",
            "primary_reason",
            "supporting_evidence",
            "next_action_type",
            "next_action_focus",
            "next_action_summary",
            "what_would_change_my_mind",
            "confidence",
            "grounding_refs_used",
        ],
        "field_rules": {
            "verdict": sorted(ALLOWED_VERDICTS),
            "stage7_readiness": sorted(ALLOWED_STAGE7_READINESS),
            "next_action_type": sorted(ALLOWED_NEXT_ACTION_TYPES),
            "confidence": sorted(ALLOWED_CONFIDENCE),
            "grounding_refs_used": "Array of grounding reference labels or file paths used by the Stage 7 memo.",
        },
        "example": {
            "verdict": "keep_collecting_evidence",
            "stage7_readiness": "blocked_by_stage_6",
            "primary_reason": "Stage 6 still has unmet evidence thresholds and the revision loop remains flat.",
            "supporting_evidence": "recent_proposal_count, recent_action_count, and recent_execution_state_count are all still below threshold, and no revision has improved beyond flat.",
            "next_action_type": "collect_evidence",
            "next_action_focus": "evidence_thresholds",
            "next_action_summary": "Keep collecting fresh evidence until Stage 6 clears the remaining evidence and revision-outcome gates.",
            "what_would_change_my_mind": "If the evidence thresholds are met and a future fresh sample shows a real revision outcome beyond flat, I would revisit a Stage 7 decision.",
            "confidence": "medium",
            "grounding_refs_used": [
                "House Spec",
                "Review Rubric",
                "Paper Trading Protocol",
            ],
        },
    }


def validate_stage7_decision_response(response_payload):
    payload = response_payload if isinstance(response_payload, dict) else {}
    errors = []

    verdict = clean_text(payload.get("verdict"))
    if verdict not in ALLOWED_VERDICTS:
        errors.append(f"verdict must be one of: {', '.join(sorted(ALLOWED_VERDICTS))}")

    stage7_readiness = clean_text(payload.get("stage7_readiness"))
    if stage7_readiness not in ALLOWED_STAGE7_READINESS:
        errors.append(
            f"stage7_readiness must be one of: {', '.join(sorted(ALLOWED_STAGE7_READINESS))}"
        )

    primary_reason = clean_text(payload.get("primary_reason"))
    if not primary_reason:
        errors.append("primary_reason is required")

    supporting_evidence = clean_text(payload.get("supporting_evidence"))
    if not supporting_evidence:
        errors.append("supporting_evidence is required")

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
        "stage7_readiness": stage7_readiness,
        "primary_reason": primary_reason,
        "supporting_evidence": supporting_evidence,
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


def build_structured_stage7_decision_record(validated_response, brief_packet, *, source, author):
    brief = brief_packet if isinstance(brief_packet, dict) else {}
    response = validated_response if isinstance(validated_response, dict) else {}
    decision = brief.get("decision") or {}

    summary = (
        f"{response.get('verdict') or 'stage7_decision'}: "
        f"{response.get('next_action_summary') or response.get('primary_reason') or 'stage 7 decision memo'}"
    )
    return {
        "concept_id": clean_text(brief.get("concept_id")) or "concept-1",
        "source": clean_text(source) or "llm",
        "author": clean_text(author),
        "review_kind": "stage7_decision_structured",
        "overall": clean_text(decision.get("overall")) or "collecting",
        "recommendation": clean_text(response.get("verdict")),
        "primary_blocker": clean_text(response.get("next_action_focus")) or clean_text(response.get("primary_reason")),
        "summary": summary[:400],
        "structured_response": response,
        "concept_brief": brief,
    }
