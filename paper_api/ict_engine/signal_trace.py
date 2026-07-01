from __future__ import annotations

from .evaluation import decision_allows_execution_plan
from .opportunity import summarize_opportunity_state
from .utils import clean_string, coerce_bool


TRACE_UNAVAILABLE_STATE = "not_available"
TRACE_ALLOWED_SOURCE_PATHS = {"scanner", "watchlist", "replay", "webhook", "daemon"}
MSS_READY_STATES = {"bullish_mss", "bearish_mss"}
DIRECTION_READY_STATES = {"bullish", "bearish"}
PREMISE_CHECKLIST_FIELDS = {"clear_4h_bias", "clear_liquidity_draw", "liquidity_event"}
STRUCTURE_CHECKLIST_FIELDS = {"mss", "displacement", "fresh_fvg"}
TRADE_PLAN_CHECKLIST_FIELDS = {"clear_invalidation", "clear_target"}


def _append_unique(items, value):
    cleaned = clean_string(value)
    if cleaned and cleaned not in items:
        items.append(cleaned)


def _normalized_state(value, default=TRACE_UNAVAILABLE_STATE):
    cleaned = clean_string(value)
    return cleaned or default


def _normalized_confidence(value):
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _normalize_source_path(source_path):
    cleaned = clean_string(source_path) or "daemon"
    return cleaned if cleaned in TRACE_ALLOWED_SOURCE_PATHS else "daemon"


def _normalize_chase_state(raw_value):
    bool_value = coerce_bool(raw_value)
    if bool_value is True:
        return "chase"
    if bool_value is False:
        return "not_chase"
    cleaned = clean_string(raw_value)
    return cleaned or TRACE_UNAVAILABLE_STATE


def _extract_failed_check_fields(evaluation):
    failed = []
    for blocker in evaluation.get("blockers") or []:
        text = clean_string(blocker) or ""
        prefix = "required checklist field failed: "
        if text.startswith(prefix):
            failed.append(text[len(prefix) :].strip())
    return failed


def _collect_ambiguity_flags(drt_summary, narrative_summary, mss_summary, displacement_summary, fvg_summary):
    flags = []
    for source in (drt_summary, narrative_summary, mss_summary, displacement_summary, fvg_summary):
        items = source.get("ambiguity_flags") if isinstance(source, dict) else []
        if not isinstance(items, list):
            continue
        for item in items:
            _append_unique(flags, item)
    return flags


def _state_reason(summary, fallback):
    if isinstance(summary, dict):
        return clean_string(summary.get("reason")) or fallback
    return fallback


def _build_trace_blocker_reasons(
    *,
    source_path,
    payload,
    evaluation,
    session_info,
    drt_summary,
    narrative_summary,
    context_summary,
    mss_summary,
    displacement_summary,
    fvg_summary,
    liquidity_alignment,
    decision,
    source_mode,
    chase_state,
):
    reasons = []
    payload = payload if isinstance(payload, dict) else {}
    evaluation = evaluation if isinstance(evaluation, dict) else {}
    session_info = session_info if isinstance(session_info, dict) else {}
    drt_summary = drt_summary if isinstance(drt_summary, dict) else {}
    narrative_summary = narrative_summary if isinstance(narrative_summary, dict) else {}
    context_summary = context_summary if isinstance(context_summary, dict) else {}
    mss_summary = mss_summary if isinstance(mss_summary, dict) else {}
    displacement_summary = displacement_summary if isinstance(displacement_summary, dict) else {}
    fvg_summary = fvg_summary if isinstance(fvg_summary, dict) else {}
    liquidity_alignment = liquidity_alignment if isinstance(liquidity_alignment, dict) else {}

    for item in evaluation.get("errors") or []:
        _append_unique(reasons, item)
    for item in evaluation.get("blockers") or []:
        _append_unique(reasons, item)

    if decision in {"journal_only", "scanner_candidate"} and source_mode != "scanner_verified":
        if source_mode == "manual_assertion":
            _append_unique(reasons, "source_mode manual_assertion remains journal-only by policy")
        elif source_mode == "hybrid":
            _append_unique(reasons, "source_mode hybrid remains candidate-only by policy")
        else:
            _append_unique(reasons, f"source_mode {source_mode} does not promote to verified_paper_trade")

    if source_path in {"scanner", "watchlist", "replay"}:
        if not session_info.get("session_valid"):
            _append_unique(
                reasons,
                _state_reason(context_summary, "session timing is outside the current house window"),
            )

        if drt_summary:
            drt_state = clean_string(drt_summary.get("state"))
            drt_confidence = _normalized_confidence(drt_summary.get("confidence"))
            if drt_state in {"unclear", "low_confidence"} or (
                drt_confidence is not None and drt_confidence < 0.5
            ):
                _append_unique(
                    reasons,
                    "the 4H dealing range is not clear enough to support a confident narrative read",
                )

        if liquidity_alignment.get("state") in {"assumption_only", "unmapped"}:
            _append_unique(reasons, clean_string(liquidity_alignment.get("reason")))

        narrative_state = clean_string(narrative_summary.get("state"))
        if narrative_state in {"unclear", "developing", "rebalance", "rejection", "acceptance"}:
            _append_unique(reasons, clean_string(narrative_summary.get("reason")))

        context_state = clean_string(context_summary.get("state"))
        if context_state in {"watch", "unclear", "invalid_session"}:
            _append_unique(reasons, clean_string(context_summary.get("reason")))

        if clean_string(mss_summary.get("state")) not in MSS_READY_STATES:
            _append_unique(reasons, _state_reason(mss_summary, "15m MSS is not confirmed"))

        if clean_string(displacement_summary.get("state")) not in DIRECTION_READY_STATES:
            _append_unique(
                reasons,
                _state_reason(displacement_summary, "5m displacement confirmation is not present"),
            )

        if clean_string(fvg_summary.get("state")) not in DIRECTION_READY_STATES:
            _append_unique(
                reasons,
                _state_reason(fvg_summary, "5m FVG entry array is not present"),
            )

    if chase_state == "chase":
        _append_unique(reasons, "entry is marked as a chase")

    if not reasons and not decision_allows_execution_plan(decision):
        fallback = {
            "journal_only": "decision remained journal_only and is not execution-eligible",
            "scanner_candidate": "decision remained scanner_candidate and did not promote to verified_paper_trade",
            "no_paper_trade": "decision resolved to no_paper_trade",
            "unclear": "evaluation remained unclear",
            "scan_error": "scan did not complete successfully",
        }
        _append_unique(reasons, fallback.get(decision, "trace remained non-executable"))

    return reasons


def _classify_trace_blockers(
    *,
    decision,
    source_mode,
    blocker_reasons,
    failed_check_fields,
    session_state,
    context_state,
    chase_state,
):
    if decision_allows_execution_plan(decision):
        return {
            "primary": "ready",
            "categories": ["ready"],
            "summary": "trace reached verified_paper_trade and remained execution-eligible",
        }

    categories = []
    joined = " ".join(blocker_reasons).lower()

    if decision == "scan_error":
        _append_unique(categories, "scan_error")
    if "missing boolean checklist fields" in joined or "is required" in joined:
        _append_unique(categories, "invalid_payload")
    if "outside the current paper-trading scope" in joined or "outside the current replay scan scope" in joined:
        _append_unique(categories, "scope_guard")
    if "timeframe " in joined and "must be" in joined:
        _append_unique(categories, "timeframe_stack")
    if "session" in joined or session_state == "outside" or context_state == "invalid_session":
        _append_unique(categories, "session_window")
    if "directional alignment could not be derived" in joined:
        _append_unique(categories, "direction_alignment")
    if source_mode != "scanner_verified" and decision in {"journal_only", "scanner_candidate"}:
        _append_unique(categories, "source_verification")
    if chase_state == "chase" or "entry is marked as a chase" in joined:
        _append_unique(categories, "chase_entry")
    if set(failed_check_fields) & PREMISE_CHECKLIST_FIELDS or context_state in {"watch", "unclear"}:
        _append_unique(categories, "premise_alignment")
    if set(failed_check_fields) & STRUCTURE_CHECKLIST_FIELDS:
        _append_unique(categories, "structure_confirmation")
    if set(failed_check_fields) & TRADE_PLAN_CHECKLIST_FIELDS:
        _append_unique(categories, "trade_plan")

    if not categories:
        categories.append("unclear")

    primary = categories[0]
    summary = blocker_reasons[0] if blocker_reasons else "trace remained non-executable"
    return {
        "primary": primary,
        "categories": categories,
        "summary": summary,
    }


def build_signal_trace(
    *,
    source_path,
    payload=None,
    evaluation=None,
    context=None,
    symbol=None,
    reference_timestamp=None,
    journal_id=None,
    webhook_id=None,
    scan_id=None,
    scan_batch_id=None,
    created_at=None,
    source_error=None,
    shadow_mode=None,
    shadow_session_id=None,
):
    payload = payload if isinstance(payload, dict) else {}
    evaluation = evaluation if isinstance(evaluation, dict) else {}
    context = context if isinstance(context, dict) else {}

    verification = evaluation.get("verification") if isinstance(evaluation.get("verification"), dict) else {}
    session_info = context.get("session") if isinstance(context.get("session"), dict) else {}
    drt_summary = context.get("drt_4h") if isinstance(context.get("drt_4h"), dict) else {}
    narrative_summary = context.get("narrative") if isinstance(context.get("narrative"), dict) else {}
    context_summary = (
        context.get("context_summary") if isinstance(context.get("context_summary"), dict) else {}
    )
    liquidity_alignment = (
        narrative_summary.get("liquidity_reference_alignment")
        if isinstance(narrative_summary.get("liquidity_reference_alignment"), dict)
        else context_summary.get("liquidity_reference_alignment")
        if isinstance(context_summary.get("liquidity_reference_alignment"), dict)
        else {}
    )
    liquidity_event = (
        context.get("liquidity_event_4h")
        if isinstance(context.get("liquidity_event_4h"), dict)
        else drt_summary.get("liquidity_event")
        if isinstance(drt_summary.get("liquidity_event"), dict)
        else {}
    )
    mss_summary = context.get("mss_15m") if isinstance(context.get("mss_15m"), dict) else {}
    sweep_summary = context.get("sweep_15m") if isinstance(context.get("sweep_15m"), dict) else {}
    displacement_summary = (
        context.get("displacement_5m") if isinstance(context.get("displacement_5m"), dict) else {}
    )
    fvg_summary = context.get("fvg_5m") if isinstance(context.get("fvg_5m"), dict) else {}
    pd_arrays_summary = context.get("pd_arrays") if isinstance(context.get("pd_arrays"), dict) else {}

    normalized_symbol = (
        clean_string(symbol)
        or clean_string(payload.get("instrument"))
        or clean_string((evaluation.get("normalized") or {}).get("instrument"))
        or "unknown"
    )
    normalized_source_path = _normalize_source_path(source_path)
    normalized_reference_timestamp = (
        clean_string(reference_timestamp)
        or clean_string(payload.get("reference_at"))
        or clean_string(context.get("reference_at"))
        or clean_string((context.get("replay") or {}).get("reference_at"))
        or clean_string(session_info.get("now_utc"))
    )
    source_mode = (
        clean_string(verification.get("source_mode"))
        or clean_string(payload.get("source_mode"))
        or ("scanner_verified" if normalized_source_path in {"scanner", "watchlist", "replay"} else "manual_assertion")
    )
    visual_analysis_state = (
        clean_string(verification.get("visual_analysis_state"))
        or clean_string(payload.get("visual_analysis_state"))
        or clean_string(context.get("visual_analysis_state"))
        or "not_run"
    )
    chase_state = _normalize_chase_state(
        first_non_empty(
            context.get("chase_state"),
            (payload.get("checklist") or {}).get("chase_entry")
            if isinstance(payload.get("checklist"), dict)
            else None,
        )
    )
    decision = clean_string(evaluation.get("decision")) or ("scan_error" if source_error else "unclear")
    execution_eligible = decision_allows_execution_plan(decision)
    session_state = clean_string(session_info.get("active_session")) or clean_string(payload.get("session"))
    if not session_state:
        session_state = (
            "outside" if normalized_source_path in {"scanner", "watchlist", "replay"} else TRACE_UNAVAILABLE_STATE
        )
    if not clean_string(session_state):
        session_state = TRACE_UNAVAILABLE_STATE

    ambiguity_flags = _collect_ambiguity_flags(
        drt_summary,
        narrative_summary,
        mss_summary,
        displacement_summary,
        fvg_summary,
    )
    failed_check_fields = _extract_failed_check_fields(evaluation)
    blocker_reasons = _build_trace_blocker_reasons(
        source_path=normalized_source_path,
        payload=payload,
        evaluation=evaluation,
        session_info=session_info,
        drt_summary=drt_summary,
        narrative_summary=narrative_summary,
        context_summary=context_summary,
        mss_summary=mss_summary,
        displacement_summary=displacement_summary,
        fvg_summary=fvg_summary,
        liquidity_alignment=liquidity_alignment,
        decision=decision,
        source_mode=source_mode,
        chase_state=chase_state,
    )
    if source_error:
        _append_unique(blocker_reasons, source_error)

    blocker_classification = _classify_trace_blockers(
        decision=decision,
        source_mode=source_mode,
        blocker_reasons=blocker_reasons,
        failed_check_fields=failed_check_fields,
        session_state=session_state,
        context_state=_normalized_state(
            first_non_empty(context.get("context_state"), context_summary.get("state"))
        ),
        chase_state=chase_state,
    )
    existing_opportunity = context.get("opportunity") if isinstance(context.get("opportunity"), dict) else {}
    opportunity = (
        existing_opportunity
        if clean_string(existing_opportunity.get("state"))
        else summarize_opportunity_state(
            evaluation=evaluation,
            context=context,
            blocker_reasons=blocker_reasons,
        )
    )

    narrative_reason = clean_string(narrative_summary.get("reason"))
    context_reason = clean_string(context_summary.get("reason"))
    decision_reason = blocker_classification.get("summary")
    if execution_eligible:
        decision_reason = (
            "scanner-verified structure passed the current gate"
            if source_mode == "scanner_verified"
            else "decision reached verified_paper_trade"
        )
    normalized_shadow_mode = bool(coerce_bool(shadow_mode))
    normalized_shadow_session_id = clean_string(shadow_session_id)

    return {
        "created_at": clean_string(created_at),
        "symbol": normalized_symbol,
        "reference_timestamp": normalized_reference_timestamp,
        "source_path": normalized_source_path,
        "source_mode": source_mode,
        "visual_analysis_state": visual_analysis_state,
        "drt_state": _normalized_state(drt_summary.get("state")),
        "drt_confidence": _normalized_confidence(drt_summary.get("confidence")),
        "liquidity_event": _normalized_state(liquidity_event.get("state"), default="none"),
        "liquidity_reference_alignment": _normalized_state(liquidity_alignment.get("state")),
        "bias": _normalized_state(
            first_non_empty(context.get("narrative_bias"), (context.get("bias_4h") or {}).get("bias")),
            default="neutral",
        ),
        "narrative_state": _normalized_state(
            first_non_empty(context.get("narrative_state"), narrative_summary.get("state"))
        ),
        "context_state": _normalized_state(
            first_non_empty(context.get("context_state"), context_summary.get("state"))
        ),
        "session_state": _normalized_state(session_state, default="outside"),
        "mss_15m_state": _normalized_state(mss_summary.get("state"), default="none"),
        "displacement_5m_state": _normalized_state(displacement_summary.get("state"), default="none"),
        "fvg_5m_state": _normalized_state(fvg_summary.get("state"), default="none"),
        "chase_state": chase_state,
        "decision": decision,
        "execution_eligible": bool(execution_eligible),
        "opportunity_state": _normalized_state(opportunity.get("state"), default="invalid"),
        "opportunity_reason": clean_string(opportunity.get("reason")),
        "shadow_mode": normalized_shadow_mode,
        "shadow_session_id": normalized_shadow_session_id,
        "context_execution_eligible": bool(context_summary.get("execution_eligible"))
        if "execution_eligible" in context_summary
        else None,
        "blocker_reasons": blocker_reasons,
        "ambiguity_flags": ambiguity_flags,
        "blocker_classification": blocker_classification,
        "decision_reason": decision_reason,
        "journal_id": clean_string(journal_id),
        "webhook_id": clean_string(webhook_id),
        "scan_id": clean_string(scan_id),
        "scan_batch_id": clean_string(scan_batch_id),
        "details": {
            "evaluation_errors": list(evaluation.get("errors") or []),
            "evaluation_blockers": list(evaluation.get("blockers") or []),
            "evaluation_warnings": list(evaluation.get("warnings") or []),
            "evaluation_confidence": clean_string(evaluation.get("confidence")),
            "evaluation_setup_tag": clean_string(evaluation.get("setup_tag")),
            "narrative_reason": narrative_reason,
            "context_reason": context_reason,
            "session_valid": bool(session_info.get("session_valid")) if session_info else None,
            "liquidity_event_detail": liquidity_event,
            "liquidity_reference_alignment_detail": liquidity_alignment,
            "drt": drt_summary,
            "sweep_15m": sweep_summary,
            "mss_15m": mss_summary,
            "displacement_5m": displacement_summary,
            "fvg_5m": fvg_summary,
            "pd_arrays": pd_arrays_summary,
            "opportunity": opportunity,
            "shadow": {
                "shadow_mode": normalized_shadow_mode,
                "shadow_session_id": normalized_shadow_session_id,
            },
            "source_error": clean_string(source_error),
        },
    }


def first_non_empty(*values):
    for value in values:
        cleaned = clean_string(value)
        if cleaned:
            return cleaned
    return None
