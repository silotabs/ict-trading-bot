#!/usr/bin/env python3

from shared_utils import clean_string as clean_text

ALLOWED_VERDICTS = {
    "support_current_recommendation",
    "challenge_current_recommendation",
}
ALLOWED_NEXT_ACTION_TYPES = {
    "collect_evidence",
    "review_one_rule",
    "compare_next_concept",
    "fix_harness",
}
ALLOWED_CONFIDENCE = {"low", "medium", "high"}


def build_llm_response_contract():
    return {
        "required_fields": [
            "verdict",
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
            "next_action_type": sorted(ALLOWED_NEXT_ACTION_TYPES),
            "confidence": sorted(ALLOWED_CONFIDENCE),
            "grounding_refs_used": "Array of grounding reference labels or file paths used by the review.",
            "one_variable_revision": {
                "needed": "boolean",
                "focus": "short string",
                "hypothesis": "one-variable hypothesis",
                "success_metric": "what would count as improvement",
                "abort_metric": "what would count as regression",
            },
        },
        "example": {
            "verdict": "support_current_recommendation",
            "primary_blocker": "displacement",
            "evidence_gap": "recent_proposal_count and recent_execution_state_count are both still below threshold",
            "next_action_type": "collect_evidence",
            "next_action_focus": "evidence_thresholds",
            "next_action_summary": "Keep collecting evidence until the next clean proposal and execution-state row arrive.",
            "what_would_change_my_mind": "If evidence thresholds are met and candidate ratio stays at 0%, I would shift to a one-variable rule review.",
            "confidence": "medium",
            "grounding_refs_used": [
                "House Spec",
                "Review Rubric",
                "Paper Trading Protocol",
            ],
            "one_variable_revision": {
                "needed": False,
                "focus": "",
                "hypothesis": "",
                "success_metric": "",
                "abort_metric": "",
            },
        },
    }


def validate_structured_review_response(response_payload):
    payload = response_payload if isinstance(response_payload, dict) else {}
    errors = []

    verdict = clean_text(payload.get("verdict"))
    if verdict not in ALLOWED_VERDICTS:
        errors.append(f"verdict must be one of: {', '.join(sorted(ALLOWED_VERDICTS))}")

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

    revision = payload.get("one_variable_revision")
    if revision is None:
        revision = {}
    if not isinstance(revision, dict):
        errors.append("one_variable_revision must be an object when provided")
        revision = {}

    needed = bool(revision.get("needed"))
    normalized_revision = {
        "needed": needed,
        "focus": clean_text(revision.get("focus")),
        "hypothesis": clean_text(revision.get("hypothesis")),
        "success_metric": clean_text(revision.get("success_metric")),
        "abort_metric": clean_text(revision.get("abort_metric")),
    }
    if needed:
        for field in ("focus", "hypothesis", "success_metric", "abort_metric"):
            if not normalized_revision.get(field):
                errors.append(f"one_variable_revision.{field} is required when needed is true")

    normalized = {
        "verdict": verdict,
        "primary_blocker": primary_blocker,
        "evidence_gap": evidence_gap,
        "next_action_type": next_action_type,
        "next_action_focus": next_action_focus,
        "next_action_summary": next_action_summary,
        "what_would_change_my_mind": what_would_change_my_mind,
        "confidence": confidence,
        "grounding_refs_used": [clean_text(item) for item in refs if clean_text(item)],
        "one_variable_revision": normalized_revision,
    }
    return {
        "ok": not errors,
        "errors": errors,
        "response": normalized,
    }


def build_structured_review_record(validated_response, brief_packet, *, source, author):
    brief = brief_packet if isinstance(brief_packet, dict) else {}
    response = validated_response if isinstance(validated_response, dict) else {}
    decision = brief.get("decision") or {}

    summary = (
        f"{response.get('verdict') or 'review'}: "
        f"{response.get('next_action_summary') or response.get('evidence_gap') or 'concept review'}"
    )
    return {
        "concept_id": clean_text(brief.get("concept_id")) or "concept-1",
        "source": clean_text(source) or "llm",
        "author": clean_text(author),
        "review_kind": "llm_structured",
        "overall": clean_text(decision.get("overall")),
        "recommendation": clean_text(decision.get("recommendation")),
        "primary_blocker": clean_text(response.get("primary_blocker")),
        "summary": summary[:400],
        "structured_response": response,
        "concept_brief": brief,
    }
