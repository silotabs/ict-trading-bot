from __future__ import annotations

from .utils import clean_string


ACCEPTED_THROUGH_EVENT_STATES = {"bsl_close_through_acceptance", "ssl_close_through_acceptance"}
REJECTED_RAID_EVENT_STATES = {"raid_bsl_reject", "raid_ssl_reject"}
TOUCH_EVENT_STATES = {"touched_bsl", "touched_ssl"}
ASIAN_RANGE_ASSUMPTION_REASON = (
    "Asian range uses the configured starter window until the house rules pin a different definition"
)


def _append_flag(flags, value):
    if value and value not in flags:
        flags.append(value)


def _extract_reference_price(item):
    if not isinstance(item, dict):
        return None
    value = item.get("price")
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _match_reference_set(items, *, event_level, tolerance, label_prefix, tier):
    matches = []
    for index, item in enumerate(items or []):
        numeric = _extract_reference_price(item)
        if numeric is None or abs(numeric - event_level) > tolerance:
            continue
        label = label_prefix if index == 0 else f"{label_prefix}_{index + 1}"
        matches.append(
            {
                "label": label,
                "tier": tier,
                "price": numeric,
            }
        )
    return matches


def _match_internal_liquidity_reference(drt_summary, liquidity_event, *, event_level, tolerance):
    event_tier = clean_string((liquidity_event or {}).get("liquidity_tier"))
    event_role = clean_string((liquidity_event or {}).get("reference_role"))
    if event_tier == "internal" and event_role == "intraday_range_liquidity":
        return [
            {
                "label": "intraday_range_liquidity",
                "tier": "internal",
                "price": event_level,
            }
        ]
    if event_tier != "internal" and event_role != "internal_range_liquidity":
        return []

    internal_liquidity = (
        drt_summary.get("internal_liquidity") if isinstance(drt_summary.get("internal_liquidity"), dict) else {}
    )
    event_state = clean_string((liquidity_event or {}).get("state"))
    side_labels = []
    if "bsl" in event_state:
        side_labels = ["high"]
    elif "ssl" in event_state:
        side_labels = ["low"]
    else:
        side_labels = ["high", "low"]

    matches = []
    for side in side_labels:
        numeric = _extract_reference_price({"price": internal_liquidity.get(side)})
        if numeric is None or abs(numeric - event_level) > tolerance:
            continue
        matches.append(
            {
                "label": f"internal_range_{side}",
                "tier": "internal",
                "price": numeric,
            }
        )
    return matches


def _event_direction(event_state, liquidity_event):
    explicit = clean_string((liquidity_event or {}).get("direction"))
    if explicit in {"bullish", "bearish"}:
        return explicit
    if event_state in {"raid_ssl_reject", "bsl_close_through_acceptance"}:
        return "bullish"
    if event_state in {"raid_bsl_reject", "ssl_close_through_acceptance"}:
        return "bearish"
    return "unknown"


def _expected_array_name(direction):
    if direction == "bullish":
        return "BISI"
    if direction == "bearish":
        return "SIBI"
    return ""


def _counter_array_name(direction):
    if direction == "bullish":
        return "SIBI"
    if direction == "bearish":
        return "BISI"
    return ""


def _evaluate_narrative_array_gate(event_state, event_direction, bias_state, array_lead, liquidity_event=None):
    array_lead = array_lead if isinstance(array_lead, dict) else {}
    array_name = clean_string(array_lead.get("name")) or ""
    respect_state = clean_string(array_lead.get("respect_state")) or "unknown"
    ifvg_candidate = bool(array_lead.get("ifvg_candidate"))
    event_role = clean_string((liquidity_event or {}).get("reference_role"))
    event_timeframe = clean_string((liquidity_event or {}).get("source_timeframe")) or clean_string(
        (liquidity_event or {}).get("timeframe")
    )
    intraday_rejection = (
        event_state in REJECTED_RAID_EVENT_STATES
        and (event_role == "intraday_range_liquidity" or event_timeframe == "15m")
    )
    ambiguity_flags = []

    if bias_state not in {"bullish", "bearish"}:
        _append_flag(ambiguity_flags, "directional_bias_unavailable")
    elif event_direction in {"bullish", "bearish"} and bias_state != event_direction:
        _append_flag(ambiguity_flags, "bias_event_direction_conflict")

    if not array_name:
        _append_flag(ambiguity_flags, "pd_array_missing")
        return {
            "state": "missing",
            "array_support": "unknown",
            "narrative_role": "missing",
            "ambiguity_flags": ambiguity_flags,
        }

    if event_state in ACCEPTED_THROUGH_EVENT_STATES:
        expected_name = _expected_array_name(event_direction)
        if array_name == expected_name and respect_state == "respected":
            return {
                "state": "supportive",
                "array_support": "supportive",
                "narrative_role": "supportive_array",
                "ambiguity_flags": ambiguity_flags,
            }
        if array_name == expected_name and respect_state == "contested":
            _append_flag(ambiguity_flags, "continuation_array_contested")
            return {
                "state": "caution",
                "array_support": "caution",
                "narrative_role": "contested_array",
                "ambiguity_flags": ambiguity_flags,
            }
        if array_name == expected_name and respect_state in {"unclear", "untested", "unknown"}:
            _append_flag(ambiguity_flags, "continuation_array_ambiguous")
            return {
                "state": "ambiguous",
                "array_support": "ambiguous",
                "narrative_role": "ambiguous_array",
                "ambiguity_flags": ambiguity_flags,
            }
        if array_name != expected_name:
            _append_flag(ambiguity_flags, "continuation_array_direction_conflict")
        elif respect_state == "contested":
            _append_flag(ambiguity_flags, "continuation_array_contested")
        elif respect_state in {"unclear", "untested", "unknown"}:
            _append_flag(ambiguity_flags, "continuation_array_ambiguous")
        elif respect_state != "respected":
            _append_flag(ambiguity_flags, "continuation_array_not_supportive")
        if ifvg_candidate:
            _append_flag(ambiguity_flags, "continuation_counter_array_conflict")
        return {
            "state": "conflicted",
            "array_support": "conflicted",
            "narrative_role": "conflicted_array",
            "ambiguity_flags": ambiguity_flags,
        }

    if event_state in REJECTED_RAID_EVENT_STATES:
        if intraday_rejection:
            expected_name = _expected_array_name(event_direction)
            if array_name == expected_name and respect_state == "respected":
                return {
                    "state": "supportive_entry",
                    "array_support": "supportive",
                    "narrative_role": "supportive_entry_array",
                    "ambiguity_flags": ambiguity_flags,
                }
            if array_name == expected_name and respect_state == "contested":
                _append_flag(ambiguity_flags, "intraday_reversal_entry_array_contested")
                return {
                    "state": "caution_entry",
                    "array_support": "caution",
                    "narrative_role": "contested_entry_array",
                    "ambiguity_flags": ambiguity_flags,
                }
            if array_name == expected_name and respect_state in {"unclear", "untested", "unknown"}:
                _append_flag(ambiguity_flags, "intraday_reversal_entry_array_ambiguous")
                return {
                    "state": "ambiguous",
                    "array_support": "ambiguous",
                    "narrative_role": "ambiguous_entry_array",
                    "ambiguity_flags": ambiguity_flags,
                }

        counter_name = _counter_array_name(event_direction)
        if array_name == counter_name and (respect_state == "disrespected" or ifvg_candidate):
            return {
                "state": "supportive_counter",
                "array_support": "supportive_counter",
                "narrative_role": "supportive_counter_array",
                "ambiguity_flags": ambiguity_flags,
            }
        if array_name == counter_name and respect_state == "contested":
            _append_flag(ambiguity_flags, "reversal_counter_array_contested")
            return {
                "state": "caution_counter",
                "array_support": "caution_counter",
                "narrative_role": "contested_counter_array",
                "ambiguity_flags": ambiguity_flags,
            }
        if array_name == counter_name and respect_state in {"unclear", "untested", "unknown"}:
            _append_flag(ambiguity_flags, "reversal_counter_array_ambiguous")
            return {
                "state": "ambiguous",
                "array_support": "ambiguous",
                "narrative_role": "ambiguous_counter_array",
                "ambiguity_flags": ambiguity_flags,
            }
        if array_name != counter_name:
            _append_flag(ambiguity_flags, "reversal_counter_array_direction_conflict")
        elif respect_state == "contested":
            _append_flag(ambiguity_flags, "reversal_counter_array_contested")
        elif respect_state in {"unclear", "untested", "unknown"}:
            _append_flag(ambiguity_flags, "reversal_counter_array_ambiguous")
        elif respect_state != "disrespected" and not ifvg_candidate:
            _append_flag(ambiguity_flags, "reversal_counter_array_not_supportive")
        if array_name == _expected_array_name(event_direction) and respect_state == "respected":
            _append_flag(ambiguity_flags, "reversal_same_direction_array_conflict")
        return {
            "state": "conflicted",
            "array_support": "conflicted",
            "narrative_role": "conflicted_array",
            "ambiguity_flags": ambiguity_flags,
        }

    return {
        "state": "unknown",
        "array_support": (
            "supportive"
            if respect_state == "respected"
            else "caution"
            if respect_state == "contested"
            else "ambiguous"
            if respect_state in {"unclear", "untested"}
            else "failing"
            if respect_state == "disrespected"
            else "unknown"
        ),
        "narrative_role": "non_directional_array",
        "ambiguity_flags": ambiguity_flags,
    }


def _liquidity_reference_alignment(drt_summary, liquidity_map):
    drt_summary = drt_summary if isinstance(drt_summary, dict) else {}
    liquidity_map = liquidity_map if isinstance(liquidity_map, dict) else {}
    liquidity_event = drt_summary.get("liquidity_event") if isinstance(drt_summary.get("liquidity_event"), dict) else {}
    event_role = clean_string(liquidity_event.get("reference_role"))
    event_timeframe = clean_string(liquidity_event.get("source_timeframe")) or clean_string(liquidity_event.get("timeframe"))
    event_label = (
        "active intraday liquidity event"
        if event_role == "intraday_range_liquidity" or event_timeframe == "15m"
        else "active 4H liquidity event"
    )
    level = liquidity_event.get("level")
    if level in {None, ""}:
        return {
            "state": "unmapped",
            "matched_references": [],
            "reason": f"no clear {event_label.replace('active ', '')} is available to compare against the higher-timeframe liquidity map",
        }

    try:
        event_level = float(level)
    except (TypeError, ValueError):
        return {
            "state": "unmapped",
            "matched_references": [],
            "reason": f"the {event_label} level is incomplete",
        }

    spread = drt_summary.get("spread") or 0.0
    try:
        tolerance = max(float(spread) * 0.03, 0.0)
    except (TypeError, ValueError):
        tolerance = 0.0

    matched_primary = []
    matched_internal = []
    matched_secondary = []
    matched_supporting = []
    matched_assumption = []
    assumption_grade = None
    assumption_reason = None
    cannot_promote_alignment_alone = False

    primary_labels = ("prior_day_high", "prior_day_low")
    primary_available = False
    for label in primary_labels:
        item = liquidity_map.get(label) if isinstance(liquidity_map.get(label), dict) else {}
        numeric = _extract_reference_price(item)
        if numeric is None:
            continue
        primary_available = True
        if abs(numeric - event_level) <= tolerance:
            matched_primary.append({"label": label, "tier": "primary", "price": numeric})

    matched_internal.extend(
        _match_internal_liquidity_reference(
            drt_summary,
            liquidity_event,
            event_level=event_level,
            tolerance=tolerance,
        )
    )
    matched_secondary.extend(
        _match_reference_set(
            liquidity_map.get("recent_4h_swing_highs"),
            event_level=event_level,
            tolerance=tolerance,
            label_prefix="recent_4h_swing_high",
            tier="secondary",
        )
    )
    matched_secondary.extend(
        _match_reference_set(
            liquidity_map.get("recent_4h_swing_lows"),
            event_level=event_level,
            tolerance=tolerance,
            label_prefix="recent_4h_swing_low",
            tier="secondary",
        )
    )
    matched_supporting.extend(
        _match_reference_set(
            liquidity_map.get("equal_high_candidates"),
            event_level=event_level,
            tolerance=tolerance,
            label_prefix="equal_high_candidate",
            tier="supporting",
        )
    )
    matched_supporting.extend(
        _match_reference_set(
            liquidity_map.get("equal_low_candidates"),
            event_level=event_level,
            tolerance=tolerance,
            label_prefix="equal_low_candidate",
            tier="supporting",
        )
    )
    matched_supporting.extend(
        _match_reference_set(
            liquidity_map.get("recent_15m_swing_highs"),
            event_level=event_level,
            tolerance=tolerance,
            label_prefix="recent_15m_swing_high",
            tier="supporting",
        )
    )
    matched_supporting.extend(
        _match_reference_set(
            liquidity_map.get("recent_15m_swing_lows"),
            event_level=event_level,
            tolerance=tolerance,
            label_prefix="recent_15m_swing_low",
            tier="supporting",
        )
    )

    for label in ("asian_range_high", "asian_range_low"):
        item = liquidity_map.get(label) if isinstance(liquidity_map.get(label), dict) else {}
        numeric = _extract_reference_price(item)
        if numeric is None or abs(numeric - event_level) > tolerance:
            continue
        matched_assumption.append({"label": label, "tier": "assumption", "price": numeric})
        assumption_grade = clean_string(item.get("assumption_grade")) or clean_string(item.get("status")) or "starter_assumption"
        assumption_reason = clean_string(item.get("assumption_reason")) or ASIAN_RANGE_ASSUMPTION_REASON
        cannot_promote_alignment_alone = bool(item.get("cannot_promote_alignment_alone")) if "cannot_promote_alignment_alone" in item else True

    matched_primary_labels = [item["label"] for item in matched_primary]
    matched_internal_labels = [item["label"] for item in matched_internal]
    matched_secondary_labels = [item["label"] for item in matched_secondary]
    matched_supporting_labels = [item["label"] for item in matched_supporting]
    matched_assumption_labels = [item["label"] for item in matched_assumption]
    matched = (
        matched_primary_labels
        + matched_internal_labels
        + matched_secondary_labels
        + matched_supporting_labels
        + matched_assumption_labels
    )

    if matched_primary:
        return {
            "state": "aligned",
            "matched_references": matched,
            "reference_tier": "primary",
            "matched_verified_references": matched_primary_labels,
            "matched_internal_references": matched_internal_labels,
            "matched_secondary_references": matched_secondary_labels,
            "matched_supporting_references": matched_supporting_labels,
            "matched_assumption_references": matched_assumption_labels,
            "assumption_grade": assumption_grade,
            "assumption_reason": assumption_reason,
            "cannot_promote_alignment_alone": cannot_promote_alignment_alone,
            "supports_read": bool(matched_secondary or matched_supporting or matched_assumption),
            "reason": (
                f"the {event_label} sits near primary higher-timeframe liquidity ({', '.join(matched_primary_labels)})"
                if not matched_assumption_labels
                else (
                    f"the {event_label} sits near primary higher-timeframe liquidity ({', '.join(matched_primary_labels)}); "
                    f"Asian range overlap ({', '.join(matched_assumption_labels)}) remains assumption-grade support only"
                )
            ),
        }
    if matched_internal:
        return {
            "state": "aligned",
            "matched_references": matched,
            "reference_tier": "internal",
            "matched_verified_references": [],
            "matched_internal_references": matched_internal_labels,
            "matched_secondary_references": matched_secondary_labels,
            "matched_supporting_references": matched_supporting_labels,
            "matched_assumption_references": matched_assumption_labels,
            "assumption_grade": assumption_grade,
            "assumption_reason": assumption_reason,
            "cannot_promote_alignment_alone": cannot_promote_alignment_alone,
            "supports_read": bool(matched_secondary or matched_supporting or matched_assumption),
            "reason": (
                "the active intraday liquidity event maps to internal range liquidity inside the selected 4H dealing range"
                if event_role == "intraday_range_liquidity" or event_timeframe == "15m"
                else "the active 4H liquidity event maps to internal range liquidity inside the selected dealing range"
            ),
        }
    if matched_secondary and not primary_available:
        return {
            "state": "aligned",
            "matched_references": matched,
            "reference_tier": "secondary",
            "matched_verified_references": [],
            "matched_internal_references": matched_internal_labels,
            "matched_secondary_references": matched_secondary_labels,
            "matched_supporting_references": matched_supporting_labels,
            "matched_assumption_references": matched_assumption_labels,
            "assumption_grade": assumption_grade,
            "assumption_reason": assumption_reason,
            "cannot_promote_alignment_alone": cannot_promote_alignment_alone,
            "supports_read": bool(matched_supporting or matched_assumption),
            "reason": (
                f"the {event_label} sits near secondary 4H swing liquidity ({', '.join(matched_secondary_labels)}) "
                "while primary PDH/PDL references are unavailable"
            ),
        }
    if matched_secondary:
        return {
            "state": "secondary_only",
            "matched_references": matched_secondary_labels,
            "reference_tier": "secondary",
            "matched_verified_references": [],
            "matched_internal_references": matched_internal_labels,
            "matched_secondary_references": matched_secondary_labels,
            "matched_supporting_references": matched_supporting_labels,
            "matched_assumption_references": matched_assumption_labels,
            "assumption_grade": assumption_grade,
            "assumption_reason": assumption_reason,
            "cannot_promote_alignment_alone": True,
            "supports_read": True,
            "reason": (
                "secondary 4H swing references align with the active liquidity event, "
                "but PDH/PDL are present and unmatched so secondary references cannot promote full alignment alone"
            ),
        }
    if matched_supporting and not primary_available:
        return {
            "state": "aligned",
            "matched_references": matched_supporting_labels,
            "reference_tier": "supporting",
            "matched_verified_references": [],
            "matched_internal_references": matched_internal_labels,
            "matched_secondary_references": [],
            "matched_supporting_references": matched_supporting_labels,
            "matched_assumption_references": matched_assumption_labels,
            "assumption_grade": assumption_grade,
            "assumption_reason": assumption_reason,
            "cannot_promote_alignment_alone": False,
            "supports_read": bool(matched_assumption),
            "reason": (
                "supporting liquidity references align with the active 4H liquidity event, "
                "while primary PDH/PDL and secondary 4H swing references are unavailable"
            ),
        }
    if matched_supporting:
        return {
            "state": "supporting_only",
            "matched_references": matched_supporting_labels,
            "reference_tier": "supporting",
            "matched_verified_references": [],
            "matched_internal_references": matched_internal_labels,
            "matched_secondary_references": [],
            "matched_supporting_references": matched_supporting_labels,
            "matched_assumption_references": matched_assumption_labels,
            "assumption_grade": assumption_grade,
            "assumption_reason": assumption_reason,
            "cannot_promote_alignment_alone": True,
            "supports_read": True,
            "reason": (
                "supporting liquidity references align with the active liquidity event, "
                "but stronger primary references are present and unmatched so supporting evidence cannot promote full alignment alone"
            ),
        }
    if matched_assumption:
        return {
            "state": "assumption_only",
            "matched_references": matched_assumption_labels,
            "reference_tier": "assumption",
            "matched_verified_references": [],
            "matched_internal_references": matched_internal_labels,
            "matched_secondary_references": [],
            "matched_supporting_references": [],
            "matched_assumption_references": matched_assumption_labels,
            "assumption_grade": assumption_grade,
            "assumption_reason": assumption_reason,
            "cannot_promote_alignment_alone": cannot_promote_alignment_alone or True,
            "supports_read": True,
            "reason": (
                "only assumption-grade Asian range references align with the active 4H liquidity event; "
                "PDH/PDL remain unmatched, so this cannot promote alignment by itself"
            ),
        }
    return {
        "state": "unmapped",
        "matched_references": [],
        "matched_verified_references": [],
        "matched_internal_references": [],
        "matched_secondary_references": [],
        "matched_supporting_references": [],
        "matched_assumption_references": [],
        "reference_tier": None,
        "assumption_grade": None,
        "assumption_reason": None,
        "cannot_promote_alignment_alone": False,
        "supports_read": False,
        "reason": f"the {event_label} does not yet align with the mapped PDH/PDL or configured Asian range references",
    }


def summarize_narrative_state(bias_summary, drt_summary, liquidity_map, pd_arrays_summary, mss_summary):
    bias_state = clean_string((bias_summary or {}).get("bias")) or "neutral"
    drt_state = clean_string((drt_summary or {}).get("state"))
    drt_confidence = (drt_summary or {}).get("confidence")
    liquidity_event = (drt_summary or {}).get("liquidity_event") if isinstance(drt_summary, dict) else {}
    event_state = clean_string((liquidity_event or {}).get("state")) or "none"
    event_direction = _event_direction(event_state, liquidity_event)
    location = clean_string((drt_summary or {}).get("location")) or "unknown"
    array_lead = (pd_arrays_summary or {}).get("lead") if isinstance(pd_arrays_summary, dict) else {}
    array_support = clean_string((array_lead or {}).get("respect_state")) or "unknown"
    array_gate = _evaluate_narrative_array_gate(event_state, event_direction, bias_state, array_lead, liquidity_event)
    liquidity_alignment = _liquidity_reference_alignment(drt_summary, liquidity_map)
    ambiguity_flags = []

    try:
        drt_confidence_value = float(drt_confidence)
    except (TypeError, ValueError):
        drt_confidence_value = None

    if drt_state in {"unclear", "low_confidence"} or (
        drt_confidence_value is not None and drt_confidence_value < 0.5
    ):
        state = "unclear"
        reason = "the 4H dealing range is not clear enough to support a confident narrative read"
        _append_flag(ambiguity_flags, "drt_low_confidence")
    elif event_state in REJECTED_RAID_EVENT_STATES and array_gate["state"] in {"supportive_counter", "supportive_entry"}:
        state = "reversal"
        reason = clean_string((liquidity_event or {}).get("reason")) or "4H liquidity rejection implies reversal"
    elif event_state in REJECTED_RAID_EVENT_STATES and array_gate["state"] in {"caution_counter", "caution_entry"}:
        state = "unclear"
        reason = (
            "liquidity rejection is present, but the entry-array response is still contested for reversal"
            if array_gate["state"] == "caution_entry"
            else "4H liquidity rejection is present, but the counter-array response is still contested for reversal"
        )
        for flag in array_gate["ambiguity_flags"]:
            _append_flag(ambiguity_flags, flag)
    elif event_state in REJECTED_RAID_EVENT_STATES and array_gate["state"] == "ambiguous":
        state = "unclear"
        reason = "4H liquidity rejection is present, but the counter-array evidence is still ambiguous for reversal"
        for flag in array_gate["ambiguity_flags"]:
            _append_flag(ambiguity_flags, flag)
        if not ambiguity_flags:
            _append_flag(ambiguity_flags, "reversal_counter_array_ambiguous")
    elif event_state in REJECTED_RAID_EVENT_STATES:
        state = "unclear"
        reason = "4H liquidity rejection is present, but the array evidence is conflicted for reversal"
        for flag in array_gate["ambiguity_flags"]:
            _append_flag(ambiguity_flags, flag)
        if not ambiguity_flags:
            _append_flag(ambiguity_flags, "reversal_requires_supportive_counter_array")
    elif event_state in ACCEPTED_THROUGH_EVENT_STATES and array_gate["state"] == "supportive":
        state = "continuation"
        reason = clean_string((liquidity_event or {}).get("reason")) or "4H liquidity acceptance implies continuation"
    elif event_state in ACCEPTED_THROUGH_EVENT_STATES and array_gate["state"] == "caution":
        state = "unclear"
        reason = "4H liquidity acceptance is present, but the same-direction array is still contested for continuation"
        for flag in array_gate["ambiguity_flags"]:
            _append_flag(ambiguity_flags, flag)
    elif event_state in ACCEPTED_THROUGH_EVENT_STATES and array_gate["state"] == "ambiguous":
        state = "unclear"
        reason = "4H liquidity acceptance is present, but the same-direction array evidence is still ambiguous for continuation"
        for flag in array_gate["ambiguity_flags"]:
            _append_flag(ambiguity_flags, flag)
        if not ambiguity_flags:
            _append_flag(ambiguity_flags, "continuation_array_ambiguous")
    elif event_state in ACCEPTED_THROUGH_EVENT_STATES:
        state = "unclear"
        reason = "4H liquidity acceptance is present, but the array evidence is conflicted for continuation"
        for flag in array_gate["ambiguity_flags"]:
            _append_flag(ambiguity_flags, flag)
        if not ambiguity_flags:
            _append_flag(ambiguity_flags, "continuation_requires_supportive_array")
    elif event_state in TOUCH_EVENT_STATES:
        state = "rejection"
        reason = "liquidity was touched, but acceptance versus rejection is still developing"
    elif location == "equilibrium":
        state = "rebalance"
        reason = "price is still near equilibrium, so the range looks more like a rebalance than a clean trend leg"
    elif array_support == "disrespected":
        state = "acceptance"
        reason = "the current execution array is being disrespected, which weakens the current reaction narrative"
    elif clean_string((mss_summary or {}).get("state")) in {"bullish_mss", "bearish_mss"}:
        state = "developing"
        reason = "15m MSS is present, but the higher-timeframe narrative is still only partially confirmed"
    else:
        state = "unclear"
        reason = "the current dealing-range story is still incomplete"

    confidence = 0.78 if state in {"reversal", "continuation"} else 0.52 if state in {"rebalance", "developing"} else 0.32
    if array_gate["state"] in {"supportive", "supportive_counter", "supportive_entry"}:
        confidence = min(1.0, confidence + 0.08)
    elif array_gate["state"] in {"caution", "caution_counter", "caution_entry"}:
        confidence = max(0.0, confidence - 0.05)
    elif array_gate["state"] == "ambiguous":
        confidence = max(0.0, confidence - 0.1)
    elif array_gate["state"] == "conflicted":
        confidence = max(0.0, confidence - 0.12)
    elif array_support == "respected":
        confidence = min(1.0, confidence + 0.08)
    elif array_support == "contested":
        confidence = max(0.0, confidence - 0.05)
    elif array_support in {"unclear", "untested"}:
        confidence = max(0.0, confidence - 0.1)
    elif array_support == "disrespected":
        confidence = max(0.0, confidence - 0.12)
    if liquidity_alignment["state"] == "aligned":
        confidence = min(1.0, confidence + 0.06)

    return {
        "state": state,
        "reason": reason,
        "confidence": round(confidence, 3),
        "array_support": (
            array_gate["array_support"]
            if array_gate["array_support"] != "unknown"
            else "supportive"
            if array_support == "respected"
            else "caution"
            if array_support == "contested"
            else "ambiguous"
            if array_support in {"unclear", "untested"}
            else "failing"
            if array_support == "disrespected"
            else "unknown"
        ),
        "ambiguity_flags": ambiguity_flags,
        "liquidity_reference_alignment": liquidity_alignment,
        "evidence": {
            "bias": bias_state,
            "drt_state": drt_state or "unknown",
            "drt_confidence": round(drt_confidence_value, 3) if drt_confidence_value is not None else None,
            "liquidity_event": event_state,
            "liquidity_event_direction": event_direction,
            "drt_location": location,
            "pd_array": clean_string((array_lead or {}).get("name")),
            "pd_array_state": array_support,
            "pd_array_narrative_role": array_gate["narrative_role"],
            "liquidity_references": liquidity_alignment.get("matched_references") or [],
        },
        "assumptions": ["Narrative state is still heuristic and should stay conservative when PD-array behavior is mixed."],
        "limitations": ["Narrative does not yet classify breakaway, measuring, or terminus with full house-grade precision."],
    }


def summarize_context_state(session_info, bias_summary, narrative_summary, mss_summary):
    session_info = session_info if isinstance(session_info, dict) else {}
    session_valid = bool(session_info.get("session_valid"))
    active_session = clean_string(session_info.get("active_session")) or "outside"
    bias_state = clean_string((bias_summary or {}).get("bias")) or "neutral"
    narrative_state = clean_string((narrative_summary or {}).get("state")) or "unclear"
    mss_state = clean_string((mss_summary or {}).get("state")) or "none"
    liquidity_alignment = (
        (narrative_summary or {}).get("liquidity_reference_alignment")
        if isinstance((narrative_summary or {}).get("liquidity_reference_alignment"), dict)
        else {}
    )

    if not session_valid:
        state = "invalid_session"
        reason = "session timing is outside the current house window"
        timing_quality = "invalid"
    elif bias_state in {"bullish", "bearish"} and narrative_state in {"reversal", "continuation"}:
        state = "aligned"
        reason = "higher-timeframe premise and timing are supportive"
        timing_quality = active_session
        if liquidity_alignment.get("state") == "assumption_only":
            state = "watch"
            reason = (
                "higher-timeframe narrative is present, but only assumption-grade Asian range alignment is available "
                "and it cannot promote context to aligned by itself"
            )
        elif liquidity_alignment.get("state") == "secondary_only":
            state = "watch"
            reason = (
                "higher-timeframe narrative is present, and secondary 4H swing references align, "
                "but primary PDH/PDL references are present and unmatched"
            )
        elif liquidity_alignment.get("state") == "supporting_only":
            state = "watch"
            reason = (
                "higher-timeframe narrative is present, but only supporting liquidity references align "
                "and that is not enough to promote context to aligned"
            )
        elif liquidity_alignment.get("state") != "aligned":
            state = "watch"
            reason = "higher-timeframe narrative is present, but the active liquidity event is still unmapped against the current liquidity references"
    elif narrative_state in {"rebalance", "developing"}:
        state = "watch"
        reason = "the premise is forming, but timing or narrative clarity is not strong enough yet"
        timing_quality = active_session
    else:
        state = "unclear"
        reason = "context is not strong enough for execution"
        timing_quality = active_session

    if narrative_state == "continuation":
        structure_relation = "15m_retracement_inside_4h_continuation"
    elif narrative_state == "reversal":
        structure_relation = "15m_onset_of_4h_reversal"
    else:
        structure_relation = "unclear"

    execution_eligible = (
        state == "aligned"
        and mss_state in {"bullish_mss", "bearish_mss"}
    )
    premise_strength = "strong" if state == "aligned" else "watch" if state == "watch" else "weak"
    if liquidity_alignment.get("state") == "aligned" and premise_strength != "weak":
        premise_strength = "strong"

    return {
        "state": state,
        "reason": reason,
        "timing_quality": timing_quality,
        "valid_session": session_valid,
        "structure_relation": structure_relation,
        "premise_strength": premise_strength,
        "execution_eligible": execution_eligible,
        "liquidity_reference_alignment": liquidity_alignment,
        "confidence": 0.82 if state == "aligned" else 0.5 if state == "watch" else 0.24,
    }
