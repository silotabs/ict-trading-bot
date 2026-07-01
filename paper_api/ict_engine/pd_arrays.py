from __future__ import annotations

from .drt import classify_range_location
from .utils import clean_string, to_float


def summarize_execution_pd_arrays(range_summary, execution_candles, fvg_summary, respect_lookback=5):
    direction = clean_string((fvg_summary or {}).get("state")) or ""
    if direction not in {"bullish", "bearish"}:
        return {"lead": None, "tracked": []}

    lower = to_float((fvg_summary or {}).get("lower"))
    upper = to_float((fvg_summary or {}).get("upper"))
    midpoint = to_float((fvg_summary or {}).get("midpoint"))
    if lower is None or upper is None or upper <= lower:
        return {"lead": None, "tracked": []}
    if midpoint is None:
        midpoint = (lower + upper) / 2

    recent_candles = execution_candles[-max(int(respect_lookback or 0), 1):] if execution_candles else []
    respect_model = _summarize_respect_model(recent_candles, lower=lower, upper=upper, direction=direction)

    lead = {
        "name": "BISI" if direction == "bullish" else "SIBI",
        "kind": "fvg",
        "state": direction,
        "at": clean_string((fvg_summary or {}).get("at")),
        "lower": round(lower, 4),
        "upper": round(upper, 4),
        "midpoint": round(midpoint, 4),
        "location": classify_range_location(midpoint, range_summary),
        "range_relation": _classify_range_relation(lower, upper, range_summary),
        "liquidity_relation": _classify_liquidity_relation(midpoint, range_summary),
        "respect_state": respect_model["respect_state"],
        "respect_evidence": respect_model["respect_evidence"],
        "disrespect_evidence": respect_model["disrespect_evidence"],
        "narrative_weight": respect_model["narrative_weight"],
        "ifvg_candidate": respect_model["respect_state"] == "disrespected",
    }
    return {"lead": lead, "tracked": [lead]}


def _classify_range_relation(lower, upper, range_summary):
    if not isinstance(range_summary, dict):
        return "unknown"

    range_high = to_float(range_summary.get("high"))
    range_low = to_float(range_summary.get("low"))
    if None in {range_high, range_low}:
        return "unknown"
    return "internal" if lower >= range_low and upper <= range_high else "external_or_boundary"


def _classify_liquidity_relation(price, range_summary, tolerance_fraction=0.05):
    price_value = to_float(price)
    if price_value is None or not isinstance(range_summary, dict):
        return "unknown"

    range_high = to_float(range_summary.get("high"))
    range_low = to_float(range_summary.get("low"))
    if range_high is None or range_low is None or range_high <= range_low:
        return "unknown"

    spread = range_high - range_low
    midpoint = (range_high + range_low) / 2
    tolerance = max(spread * tolerance_fraction, 0.0)
    if price_value > range_high + tolerance:
        return "beyond_buy_side_liquidity"
    if price_value < range_low - tolerance:
        return "beyond_sell_side_liquidity"
    if abs(price_value - midpoint) <= tolerance:
        return "balanced_between_buy_side_and_sell_side_liquidity"
    return (
        "closer_to_sell_side_liquidity"
        if abs(price_value - range_low) < abs(price_value - range_high)
        else "closer_to_buy_side_liquidity"
    )


def _summarize_respect_model(candles, lower, upper, direction):
    wick_defenses = []
    far_boundary_closes = []
    inside_acceptances = []

    for index, candle in enumerate(candles or []):
        normalized = _normalize_candle_signal(index, candle)
        close = normalized["close"]
        if close is None:
            continue

        if direction == "bullish":
            low = normalized["low"]
            if low is None:
                continue
            if close < lower:
                far_boundary_closes.append({**normalized, "interaction": "body_close_through"})
            elif low <= upper and close >= upper:
                wick_defenses.append({**normalized, "interaction": "wick_defense"})
            elif low <= upper and lower <= close < upper:
                inside_acceptances.append({**normalized, "interaction": "inside_acceptance"})
        else:
            high = normalized["high"]
            if high is None:
                continue
            if close > upper:
                far_boundary_closes.append({**normalized, "interaction": "body_close_through"})
            elif high >= lower and close <= lower:
                wick_defenses.append({**normalized, "interaction": "wick_defense"})
            elif high >= lower and lower < close <= upper:
                inside_acceptances.append({**normalized, "interaction": "inside_acceptance"})

    latest_wick_defense_index = max((signal["index"] for signal in wick_defenses), default=-1)
    inside_acceptance_after_last_defense = [
        signal for signal in inside_acceptances if signal["index"] > latest_wick_defense_index
    ]
    far_boundary_close_after_last_defense = [
        signal for signal in far_boundary_closes if signal["index"] > latest_wick_defense_index
    ]

    respect_evidence = _build_evidence("wick_defense", wick_defenses)
    if len(far_boundary_close_after_last_defense) >= 2:
        respect_state = "disrespected"
        disrespect_evidence = _build_evidence(
            "repeated_outside_acceptance_without_rejection",
            far_boundary_close_after_last_defense,
        )
    elif far_boundary_closes:
        respect_state = "disrespected"
        disrespect_evidence = _build_evidence("body_close_through", far_boundary_closes)
    elif inside_acceptance_after_last_defense:
        respect_state = "contested"
        disrespect_evidence = _build_evidence(
            "inside_zone_churn",
            inside_acceptance_after_last_defense,
        )
    elif wick_defenses:
        respect_state = "respected"
        disrespect_evidence = _build_evidence("none", [])
    else:
        respect_state = "unclear"
        disrespect_evidence = _build_evidence("none", [])

    return {
        "respect_state": respect_state,
        "respect_evidence": respect_evidence,
        "disrespect_evidence": disrespect_evidence,
        "narrative_weight": _narrative_weight(
            respect_state=respect_state,
            respect_evidence=respect_evidence,
            disrespect_evidence=disrespect_evidence,
        ),
    }


def _normalize_candle_signal(index, candle):
    open_ = to_float((candle or {}).get("open"))
    high = to_float((candle or {}).get("high"))
    low = to_float((candle or {}).get("low"))
    close = to_float((candle or {}).get("close"))
    return {
        "index": index,
        "at": clean_string((candle or {}).get("start_at")),
        "open": round(open_, 4) if open_ is not None else None,
        "high": round(high, 4) if high is not None else None,
        "low": round(low, 4) if low is not None else None,
        "close": round(close, 4) if close is not None else None,
    }


def _build_evidence(kind, signals):
    return {
        "kind": kind,
        "count": len(signals),
        "latest_at": clean_string(signals[-1].get("at")) if signals else None,
        "signals": [{key: value for key, value in signal.items() if key != "index"} for signal in signals[-3:]],
    }


def _narrative_weight(respect_state, respect_evidence, disrespect_evidence):
    if respect_state == "respected":
        count = respect_evidence.get("count") or 0
        return round(min(0.6, 0.35 + max(count - 1, 0) * 0.05), 3)
    if respect_state == "disrespected":
        if disrespect_evidence.get("kind") == "body_close_through":
            return -0.7
        return -0.55
    if respect_state == "contested":
        return -0.15
    return 0.0
