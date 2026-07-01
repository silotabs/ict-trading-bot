from __future__ import annotations

from .utils import clean_string, coerce_bool
from .visual import derive_visual_analysis_state


CHECKLIST_ALIASES = {
    "liquidity_event": ["liquidity_sweep"],
}


def normalize_checklist_payload(checklist, required_fields):
    if not isinstance(checklist, dict):
        return {}

    normalized = {}
    for field in list(required_fields) + ["chase_entry"]:
        value = checklist.get(field)
        if value is None:
            for alias in CHECKLIST_ALIASES.get(field, []):
                if alias in checklist:
                    value = checklist.get(alias)
                    break
        bool_value = coerce_bool(value)
        normalized[field] = bool_value if bool_value is not None else value
    return normalized


def evaluate_payload(
    payload,
    *,
    rules,
    normalize_instrument,
    normalize_session,
    normalize_direction,
    normalize_timeframes_payload,
    evaluated_at,
):
    errors = []
    blockers = []
    warnings = []

    instrument = normalize_instrument(payload.get("instrument"))
    if not instrument:
        errors.append("instrument is required")

    session = normalize_session(payload.get("session"))
    if not session:
        errors.append("session is required")

    direction = normalize_direction(payload.get("direction"))

    provider = clean_string(payload.get("provider"))
    source_mode = clean_string(payload.get("source_mode")) or "manual_assertion"
    if source_mode not in {"manual_assertion", "scanner_verified", "hybrid"}:
        warnings.append(f"unknown source_mode {source_mode}; defaulting to manual_assertion")
        source_mode = "manual_assertion"

    visual_analysis_state = derive_visual_analysis_state(
        chart_url=payload.get("chart_url"),
        screenshot_paths=payload.get("screenshot_paths"),
        explicit_state=payload.get("visual_analysis_state"),
    )

    timeframes = normalize_timeframes_payload(payload.get("timeframes"))
    if not timeframes:
        errors.append("timeframes object is required")

    checklist = normalize_checklist_payload(payload.get("checklist"), rules["required_checklist"])
    if not isinstance(payload.get("checklist"), dict):
        errors.append("checklist object is required")

    weekend = coerce_bool(payload.get("weekend"))
    if weekend is None:
        weekend = False

    if instrument and instrument not in rules["allowed_instruments"] + rules["approved_proxies"]:
        blockers.append(f"instrument {instrument} is outside the current paper-trading scope")
    elif instrument in rules["approved_proxies"]:
        warnings.append(f"instrument {instrument} is being treated as an approved proxy")

    if session and session not in rules["allowed_sessions"]:
        blockers.append(f"session {session} is outside the allowed paper-trading windows")

    if timeframes:
        for key, expected in rules["timeframes"].items():
            if timeframes.get(key) != expected:
                blockers.append(
                    f"timeframe {key} must be {expected}, got {timeframes.get(key) or 'missing'}"
                )

    missing_checks = []
    failed_checks = []
    for field in rules["required_checklist"]:
        value = checklist.get(field)
        if not isinstance(value, bool):
            missing_checks.append(field)
        elif value is False:
            failed_checks.append(field)

    if missing_checks:
        errors.append(f"missing boolean checklist fields: {', '.join(missing_checks)}")

    for field in failed_checks:
        blockers.append(f"required checklist field failed: {field}")

    if not direction and not failed_checks:
        blockers.append("directional alignment could not be derived")

    chase_entry = checklist.get("chase_entry")
    if isinstance(chase_entry, bool):
        if chase_entry:
            blockers.append("entry is marked as a chase")
    else:
        errors.append("missing boolean checklist field: chase_entry")

    if weekend:
        warnings.append("weekend setup: lower confidence until weekend behavior is refined")

    if source_mode != "scanner_verified":
        warnings.append("checklist booleans were not fully scanner-verified")
    if visual_analysis_state != "verified":
        warnings.append(f"visual analysis state is {visual_analysis_state}")

    normalized = {
        "instrument": instrument,
        "provider": provider,
        "session": session,
        "direction": direction,
        "timeframes": timeframes,
    }

    if errors:
        decision = "unclear"
        setup_tag = "unclear"
        confidence = "low"
    elif blockers:
        decision = "no_paper_trade"
        setup_tag = "starter invalid"
        confidence = "low"
    elif source_mode == "scanner_verified":
        decision = "verified_paper_trade"
        setup_tag = "starter verified"
        confidence = "medium" if warnings else "high"
    elif source_mode == "hybrid":
        decision = "scanner_candidate"
        setup_tag = "starter candidate"
        confidence = "medium"
    else:
        decision = "journal_only"
        setup_tag = "manual_assertion_only"
        confidence = "medium" if warnings else "low"

    return {
        "strategy_version": rules["strategy_version"],
        "decision": decision,
        "setup_tag": setup_tag,
        "confidence": confidence,
        "errors": errors,
        "blockers": blockers,
        "warnings": warnings,
        "normalized": normalized,
        "checklist": checklist,
        "verification": {
            "source_mode": source_mode,
            "visual_analysis_state": visual_analysis_state,
            "verification_status": (
                "verified"
                if decision == "verified_paper_trade"
                else "candidate"
                if decision == "scanner_candidate"
                else "asserted"
                if decision == "journal_only"
                else "failed"
                if decision == "no_paper_trade"
                else "unclear"
            ),
        },
        "evaluated_at": evaluated_at(),
    }


def decision_allows_execution_plan(decision):
    return decision == "verified_paper_trade"
