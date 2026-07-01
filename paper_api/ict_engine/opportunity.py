from __future__ import annotations

from .evaluation import decision_allows_execution_plan
from .utils import clean_string


READY_MSS_STATES = {"bullish_mss", "bearish_mss"}
READY_DIRECTION_STATES = {"bullish", "bearish"}
STRONG_NARRATIVE_STATES = {"reversal", "continuation"}
WATCH_NARRATIVE_STATES = {"developing", "rebalance", "rejection", "acceptance"}


def _extract_failed_check_fields(evaluation):
    failed = []
    for blocker in (evaluation or {}).get("blockers") or []:
        text = clean_string(blocker) or ""
        prefix = "required checklist field failed: "
        if text.startswith(prefix):
            field = text[len(prefix) :].strip()
            if field and field not in failed:
                failed.append(field)
    return failed


def _append_unique(items, value):
    cleaned = clean_string(value)
    if cleaned and cleaned not in items:
        items.append(cleaned)


def _missing_requirements(evaluation, context):
    evaluation = evaluation if isinstance(evaluation, dict) else {}
    context = context if isinstance(context, dict) else {}
    blockers = evaluation.get("blockers") or []

    missing = []
    for field in _extract_failed_check_fields(evaluation):
        _append_unique(missing, field)

    if any("directional alignment could not be derived" in (clean_string(item) or "") for item in blockers):
        _append_unique(missing, "direction")
    if any("session" in (clean_string(item) or "").lower() and "outside" in (clean_string(item) or "").lower() for item in blockers):
        _append_unique(missing, "session_window")
    if any("entry is marked as a chase" in (clean_string(item) or "") for item in blockers):
        _append_unique(missing, "chase_entry")

    mss_state = clean_string(((context.get("mss_15m") or {}) if isinstance(context.get("mss_15m"), dict) else {}).get("state"))
    displacement_state = clean_string(((context.get("displacement_5m") or {}) if isinstance(context.get("displacement_5m"), dict) else {}).get("state"))
    fvg_state = clean_string(((context.get("fvg_5m") or {}) if isinstance(context.get("fvg_5m"), dict) else {}).get("state"))

    if mss_state not in READY_MSS_STATES:
        _append_unique(missing, "mss")
    if displacement_state not in READY_DIRECTION_STATES:
        _append_unique(missing, "displacement")
    if fvg_state not in READY_DIRECTION_STATES:
        _append_unique(missing, "fresh_fvg")

    return missing


def summarize_opportunity_state(*, evaluation=None, context=None, blocker_reasons=None):
    evaluation = evaluation if isinstance(evaluation, dict) else {}
    context = context if isinstance(context, dict) else {}

    decision = clean_string(evaluation.get("decision")) or "unclear"
    source_mode = (
        clean_string(((evaluation.get("verification") or {}) if isinstance(evaluation.get("verification"), dict) else {}).get("source_mode"))
        or clean_string(evaluation.get("source_mode"))
        or "unknown"
    )
    blockers = [
        clean_string(item)
        for item in (blocker_reasons if isinstance(blocker_reasons, list) else (evaluation.get("blockers") or []))
        if clean_string(item)
    ]

    drt_summary = context.get("drt_4h") if isinstance(context.get("drt_4h"), dict) else {}
    bias_summary = context.get("bias_4h") if isinstance(context.get("bias_4h"), dict) else {}
    narrative_summary = context.get("narrative") if isinstance(context.get("narrative"), dict) else {}
    context_summary = context.get("context_summary") if isinstance(context.get("context_summary"), dict) else {}
    mss_summary = context.get("mss_15m") if isinstance(context.get("mss_15m"), dict) else {}
    displacement_summary = context.get("displacement_5m") if isinstance(context.get("displacement_5m"), dict) else {}
    fvg_summary = context.get("fvg_5m") if isinstance(context.get("fvg_5m"), dict) else {}

    drt_state = clean_string(drt_summary.get("state")) or "unknown"
    bias_state = clean_string(bias_summary.get("bias")) or "neutral"
    narrative_state = clean_string(narrative_summary.get("state")) or "unclear"
    context_state = clean_string(context_summary.get("state")) or "unclear"
    premise_strength = clean_string(context_summary.get("premise_strength")) or "weak"
    mss_state = clean_string(mss_summary.get("state")) or "none"
    displacement_state = clean_string(displacement_summary.get("state")) or "none"
    fvg_state = clean_string(fvg_summary.get("state")) or "none"
    chase_state = clean_string(context.get("chase_state")) or "unknown"

    execution_eligible = bool(decision_allows_execution_plan(decision))
    missing_requirements = _missing_requirements(evaluation, context)

    strong_higher_timeframe_premise = (
        drt_state not in {"unclear", "low_confidence", "unknown"}
        and bias_state in READY_DIRECTION_STATES
        and narrative_state in STRONG_NARRATIVE_STATES
        and premise_strength == "strong"
    )
    watchworthy_premise = strong_higher_timeframe_premise or (
        drt_state not in {"unclear", "low_confidence", "unknown"}
        and bias_state in READY_DIRECTION_STATES
        and narrative_state in WATCH_NARRATIVE_STATES.union(STRONG_NARRATIVE_STATES)
    )

    execution_missing = [
        item
        for item in ("mss", "displacement", "fresh_fvg")
        if item in missing_requirements
    ]

    if execution_eligible:
        state = "opportunity_detected"
        reason = "scanner-verified setup passed the current execution gate"
    elif context_state == "invalid_session" and watchworthy_premise:
        state = "context_watch"
        reason = clean_string(context_summary.get("reason")) or "structure is attractive, but session timing is outside the current house window"
    elif strong_higher_timeframe_premise and len(execution_missing) == 1:
        state = "near_miss"
        reason = "the higher-timeframe premise is intact, but one execution confirmation is still missing"
    elif strong_higher_timeframe_premise and execution_missing:
        state = "awaiting_confirmation"
        reason = "the higher-timeframe premise is intact, but lower-timeframe execution confirmation is still developing"
    elif context_state == "watch" or watchworthy_premise:
        state = "context_watch"
        reason = clean_string(context_summary.get("reason")) or "the setup is worth watching, but context is not strong enough for execution"
    else:
        state = "invalid"
        reason = "the current evidence does not support a meaningful opportunity yet"

    return {
        "state": state,
        "reason": reason,
        "execution_decision": decision,
        "execution_eligible": execution_eligible,
        "source_mode": source_mode,
        "missing_requirements": missing_requirements,
        "blocker_reasons": blockers,
        "supporting_evidence": {
            "drt_state": drt_state,
            "bias": bias_state,
            "narrative_state": narrative_state,
            "context_state": context_state,
            "premise_strength": premise_strength,
            "mss_15m_state": mss_state,
            "displacement_5m_state": displacement_state,
            "fvg_5m_state": fvg_state,
            "chase_state": chase_state,
        },
    }
