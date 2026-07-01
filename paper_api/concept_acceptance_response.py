#!/usr/bin/env python3

from concept_briefing import clean_text


ALLOWED_VERDICTS = {
    "support_acceptance_status",
    "challenge_acceptance_status",
    "ready_for_stage_7_decision",
}
ALLOWED_NEXT_ACTION_TYPES = {
    "collect_evidence",
    "continue_current_leader",
    "prepare_stage_7_decision",
    "review_one_rule",
}
ALLOWED_CONFIDENCE = {"low", "medium", "high"}


def build_acceptance_response_contract():
    return {
        "required_fields": [
            "verdict",
            "stage6_status",
            "primary_blocker",
            "evidence_gap",
            "next_action_type",
            "next_action_focus",
            "next_action_summary",
            "what_would_change_my_mind",
            "confidence",
            "grounding_refs_used",
        ],
        "field_rules": {
            "verdict": sorted(ALLOWED_VERDICTS),
            "stage6_status": [
                "collecting_evidence",
                "observing_revision_outcomes",
                "ready_for_stage_7_decision",
            ],
            "next_action_type": sorted(ALLOWED_NEXT_ACTION_TYPES),
            "confidence": sorted(ALLOWED_CONFIDENCE),
            "grounding_refs_used": "Array of grounding reference labels or file paths used by the acceptance review.",
        },
        "example": {
            "verdict": "support_acceptance_status",
            "stage6_status": "collecting_evidence",
            "primary_blocker": "evidence_thresholds",
            "evidence_gap": "recent_proposal_count, recent_action_count, and recent_execution_state_count are all still below threshold",
            "next_action_type": "collect_evidence",
            "next_action_focus": "evidence_thresholds",
            "next_action_summary": "Keep collecting fresh evidence until the minimum thresholds are met before judging concept proof.",
            "what_would_change_my_mind": "If the evidence thresholds are met and a future fresh sample shows a real revision outcome beyond flat, I would revisit Stage 7 readiness.",
            "confidence": "medium",
            "grounding_refs_used": [
                "House Spec",
                "Review Rubric",
                "Paper Trading Protocol",
            ],
        },
    }


def validate_acceptance_response(response_payload):
    payload = response_payload if isinstance(response_payload, dict) else {}
    errors = []

    verdict = clean_text(payload.get("verdict"))
    if verdict not in ALLOWED_VERDICTS:
        errors.append(f"verdict must be one of: {', '.join(sorted(ALLOWED_VERDICTS))}")

    stage6_status = clean_text(payload.get("stage6_status"))
    if stage6_status not in {"collecting_evidence", "observing_revision_outcomes", "ready_for_stage_7_decision"}:
        errors.append("stage6_status must be one of: collecting_evidence, observing_revision_outcomes, ready_for_stage_7_decision")

    primary_blocker = clean_text(payload.get("primary_blocker"))
    if not primary_blocker:
        errors.append("primary_blocker is required")

    evidence_gap = clean_text(payload.get("evidence_gap"))
    if not evidence_gap:
        errors.append("evidence_gap is required")

    next_action_type = clean_text(payload.get("next_action_type"))
    if next_action_type not in ALLOWED_NEXT_ACTION_TYPES:
        errors.append(f"next_action_type must be one of: {', '.join(sorted(ALLOWED_NEXT_ACTION_TYPES))}")

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
        "stage6_status": stage6_status,
        "primary_blocker": primary_blocker,
        "evidence_gap": evidence_gap,
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


def build_structured_acceptance_record(validated_response, brief_packet, *, source, author):
    brief = brief_packet if isinstance(brief_packet, dict) else {}
    response = validated_response if isinstance(validated_response, dict) else {}
    decision = brief.get("decision") or {}

    summary = (
        f"{response.get('verdict') or 'acceptance'}: "
        f"{response.get('next_action_summary') or response.get('evidence_gap') or 'stage 6 acceptance review'}"
    )
    return {
        "concept_id": clean_text(brief.get("concept_id")) or "concept-1",
        "source": clean_text(source) or "llm",
        "author": clean_text(author),
        "review_kind": "acceptance_structured",
        "overall": clean_text(decision.get("overall")) or "collecting",
        "recommendation": clean_text(response.get("stage6_status")) or clean_text(decision.get("recommendation")),
        "primary_blocker": clean_text(response.get("primary_blocker")),
        "summary": summary[:400],
        "structured_response": response,
        "concept_brief": brief,
    }
