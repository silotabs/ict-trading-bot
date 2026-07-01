from __future__ import annotations

from .utils import clean_string, median_value, to_float


def detect_swings(candles, left=2, right=2):
    swings = []
    if len(candles) < left + right + 1:
        return swings
    for index in range(left, len(candles) - right):
        current = candles[index]
        current_high = to_float(current.get("high"))
        current_low = to_float(current.get("low"))
        if current_high is None or current_low is None:
            continue
        highs_left = [to_float(candles[i].get("high")) for i in range(index - left, index)]
        highs_right = [to_float(candles[i].get("high")) for i in range(index + 1, index + right + 1)]
        lows_left = [to_float(candles[i].get("low")) for i in range(index - left, index)]
        lows_right = [to_float(candles[i].get("low")) for i in range(index + 1, index + right + 1)]
        highs = [value for value in highs_left + highs_right if value is not None]
        lows = [value for value in lows_left + lows_right if value is not None]
        if highs and current_high > max(highs):
            swings.append(
                {
                    "type": "high",
                    "price": current_high,
                    "at": clean_string(current.get("start_at")),
                    "index": index,
                }
            )
        if lows and current_low < min(lows):
            swings.append(
                {
                    "type": "low",
                    "price": current_low,
                    "at": clean_string(current.get("start_at")),
                    "index": index,
                }
            )
    return swings


def classify_range_location(price, range_summary, tolerance_fraction=0.05):
    price_value = to_float(price)
    if price_value is None or not isinstance(range_summary, dict):
        return "unknown"

    range_high = to_float(range_summary.get("high"))
    range_low = to_float(range_summary.get("low"))
    if range_high is None or range_low is None or range_high <= range_low:
        return "unknown"

    midpoint = (range_high + range_low) / 2
    spread = range_high - range_low
    tolerance = max(spread * tolerance_fraction, 0.0)
    if price_value > range_high + tolerance:
        return "above_range"
    if price_value < range_low - tolerance:
        return "below_range"
    if abs(price_value - midpoint) <= tolerance:
        return "equilibrium"
    return "premium" if price_value > midpoint else "discount"


def _swing_prominence(candles, index, swing_type, window=6):
    lower_bound = max(0, index - window)
    upper_bound = min(len(candles), index + window + 1)
    sample = candles[lower_bound:upper_bound]
    if swing_type == "high":
        reference = min(to_float(item.get("low")) for item in sample if to_float(item.get("low")) is not None)
        price = to_float(candles[index].get("high"))
    else:
        reference = max(to_float(item.get("high")) for item in sample if to_float(item.get("high")) is not None)
        price = to_float(candles[index].get("low"))
    if price is None or reference is None:
        return 0.0
    return max(0.0, abs(price - reference))


def _annotate_swings(candles, swings):
    ranges = [
        to_float(candle.get("high")) - to_float(candle.get("low"))
        for candle in candles
        if to_float(candle.get("high")) is not None and to_float(candle.get("low")) is not None
    ]
    median_range = median_value(ranges) or 1.0
    annotated = []
    for swing in swings:
        prominence = _swing_prominence(candles, swing["index"], swing["type"])
        later_same_side = [
            other
            for other in swings
            if other["type"] == swing["type"] and other["index"] > swing["index"]
        ]
        preserved = True
        if swing["type"] == "high":
            preserved = not any(other["price"] >= swing["price"] for other in later_same_side)
        else:
            preserved = not any(other["price"] <= swing["price"] for other in later_same_side)
        annotated.append(
            {
                **swing,
                "prominence": round(prominence, 4),
                "prominence_units": round(prominence / median_range, 4) if median_range else 0.0,
                "classification": "external" if preserved else "internal",
                "preserved": preserved,
            }
        )
    return annotated


def _select_external_anchor(swings, swing_type, minimum_prominence_units=1.15):
    candidates = [swing for swing in swings if swing["type"] == swing_type]
    for swing in reversed(candidates):
        if swing["classification"] == "external" and swing["prominence_units"] >= minimum_prominence_units:
            return swing
    return None


def _external_anchor_candidates(swings, swing_type, minimum_prominence_units=1.15):
    return [
        swing
        for swing in swings
        if swing["type"] == swing_type
        and swing["classification"] == "external"
        and swing["prominence_units"] >= minimum_prominence_units
    ]


def _select_wider_external_anchor_pair(swings, minimum_spread, minimum_prominence_units=1.15):
    highs = _external_anchor_candidates(
        swings,
        "high",
        minimum_prominence_units=minimum_prominence_units,
    )
    lows = _external_anchor_candidates(
        swings,
        "low",
        minimum_prominence_units=minimum_prominence_units,
    )
    pairs = []
    for high in highs:
        for low in lows:
            if high["index"] == low["index"] or low["price"] >= high["price"]:
                continue
            spread = high["price"] - low["price"]
            if spread <= minimum_spread:
                continue
            pairs.append(
                {
                    "high": high,
                    "low": low,
                    "spread": spread,
                    "newer_anchor_index": max(high["index"], low["index"]),
                    "older_anchor_index": min(high["index"], low["index"]),
                    "minimum_prominence_units": min(
                        high["prominence_units"],
                        low["prominence_units"],
                    ),
                }
            )
    if not pairs:
        return None, None
    pairs.sort(
        key=lambda item: (
            -item["newer_anchor_index"],
            -item["older_anchor_index"],
            -item["minimum_prominence_units"],
            -item["spread"],
        )
    )
    selected = pairs[0]
    return selected["high"], selected["low"]


def summarize_dealing_range(candles, lookback=48):
    sample = candles[-lookback:] if len(candles) > lookback else list(candles)
    if len(sample) < 12:
        return {
            "state": "unclear",
            "confidence": 0.0,
            "ambiguity_flags": ["not_enough_4h_candles"],
            "rationale": "not enough 4H candles to anchor a clear dealing range",
            "evidence": [],
        }

    swings = _annotate_swings(sample, detect_swings(sample, left=2, right=2))
    ranges = [
        to_float(candle.get("high")) - to_float(candle.get("low"))
        for candle in sample
        if to_float(candle.get("high")) is not None and to_float(candle.get("low")) is not None
    ]
    median_range = median_value(ranges) or 1.0
    minimum_anchor_spread = median_range * 2
    external_high = _select_external_anchor(swings, "high")
    external_low = _select_external_anchor(swings, "low")
    if external_high is None or external_low is None:
        ambiguity_flags = []
        if external_high is None:
            ambiguity_flags.append("missing_external_high")
        if external_low is None:
            ambiguity_flags.append("missing_external_low")
        return {
            "state": "unclear",
            "confidence": 0.12,
            "ambiguity_flags": ambiguity_flags,
            "rationale": "a clear pair of external 4H swing anchors could not be selected",
            "evidence": swings[-6:],
        }

    ambiguity_flags = []
    if external_low["index"] == external_high["index"]:
        ambiguity_flags.append("same_anchor_index")
    if external_low["price"] >= external_high["price"]:
        ambiguity_flags.append("invalid_anchor_order")

    spread = external_high["price"] - external_low["price"]
    range_selection = "latest_external_pair"
    if spread <= minimum_anchor_spread:
        wider_high, wider_low = _select_wider_external_anchor_pair(
            swings,
            max(minimum_anchor_spread, spread * 1.5),
        )
        if wider_high is not None and wider_low is not None:
            external_high = wider_high
            external_low = wider_low
            spread = external_high["price"] - external_low["price"]
            range_selection = "wider_external_pair"
        else:
            ambiguity_flags.append("anchors_too_close")

    last_close = to_float(sample[-1].get("close"))
    midpoint = (external_high["price"] + external_low["price"]) / 2 if spread > 0 else None
    location = classify_range_location(
        last_close,
        {
            "high": external_high["price"],
            "low": external_low["price"],
            "midpoint": midpoint,
        },
    )

    internal_high = next(
        (
            swing
            for swing in reversed(swings)
            if swing["type"] == "high"
            and swing["index"] != external_high["index"]
            and swing["price"] < external_high["price"]
            and swing["price"] > external_low["price"]
        ),
        None,
    )
    internal_low = next(
        (
            swing
            for swing in reversed(swings)
            if swing["type"] == "low"
            and swing["index"] != external_low["index"]
            and swing["price"] > external_low["price"]
            and swing["price"] < external_high["price"]
        ),
        None,
    )

    confidence = 0.78
    if ambiguity_flags:
        confidence -= 0.2
    confidence += min(external_high["prominence_units"], 3.0) * 0.03
    confidence += min(external_low["prominence_units"], 3.0) * 0.03
    confidence = max(0.0, min(1.0, confidence))

    state = "ready" if not ambiguity_flags else "low_confidence"
    return {
        "state": state,
        "anchor_high_price": round(external_high["price"], 4),
        "anchor_high_time": external_high["at"],
        "anchor_high_index": external_high["index"],
        "anchor_low_price": round(external_low["price"], 4),
        "anchor_low_time": external_low["at"],
        "anchor_low_index": external_low["index"],
        "high": round(external_high["price"], 4),
        "low": round(external_low["price"], 4),
        "midpoint": round(midpoint, 4) if midpoint is not None else None,
        "last_close": round(last_close, 4) if last_close is not None else None,
        "location": location,
        "spread": round(spread, 4),
        "confidence": round(confidence, 3),
        "ambiguity_flags": ambiguity_flags,
        "rationale": (
            "anchored on the most recent wider preserved external 4H swing pair"
            if range_selection == "wider_external_pair"
            else "anchored on the most recent preserved external 4H swing high and low"
        ),
        "evidence": {
            "external_high": external_high,
            "external_low": external_low,
            "range_selection": range_selection,
            "minimum_anchor_spread": round(minimum_anchor_spread, 4),
            "recent_swings": swings[-8:],
        },
        "internal_liquidity": {
            "high": round(internal_high["price"], 4) if internal_high else None,
            "high_at": clean_string(internal_high.get("at")) if internal_high else None,
            "low": round(internal_low["price"], 4) if internal_low else None,
            "low_at": clean_string(internal_low.get("at")) if internal_low else None,
        },
        "external_liquidity": {
            "high": round(external_high["price"], 4),
            "low": round(external_low["price"], 4),
        },
    }


def detect_4h_liquidity_event(candles, drt_summary=None):
    if len(candles) < 2:
        return {"state": "none", "confidence": 0.0, "reason": "not enough 4H candles for liquidity-event read"}

    drt = drt_summary if isinstance(drt_summary, dict) else summarize_dealing_range(candles[:-1] or candles)
    if not isinstance(drt, dict) or drt.get("high") is None or drt.get("low") is None:
        return {
            "state": "none",
            "confidence": 0.0,
            "reason": "the active dealing range is unclear, so liquidity interaction cannot be trusted",
        }

    latest = candles[-1]
    latest_high = to_float(latest.get("high"))
    latest_low = to_float(latest.get("low"))
    latest_close = to_float(latest.get("close"))
    latest_open = to_float(latest.get("open"))
    range_high = to_float(drt.get("high"))
    range_low = to_float(drt.get("low"))
    spread = to_float(drt.get("spread")) or 0.0
    if None in {latest_high, latest_low, latest_close, latest_open, range_high, range_low}:
        return {"state": "none", "confidence": 0.0, "reason": "incomplete 4H liquidity-event inputs"}

    tolerance = max(spread * 0.03, 0.0)
    touch_high = latest_high >= (range_high - tolerance)
    touch_low = latest_low <= (range_low + tolerance)
    high_raid = latest_high > (range_high + tolerance)
    low_raid = latest_low < (range_low - tolerance)
    close_above_high = latest_close > (range_high + tolerance * 0.25)
    close_below_low = latest_close < (range_low - tolerance * 0.25)
    body_direction = "bullish" if latest_close > latest_open else "bearish" if latest_close < latest_open else "flat"

    base = {
        "at": clean_string(latest.get("start_at")),
        "body_direction": body_direction,
        "tolerance": round(tolerance, 4),
        "range_high": round(range_high, 4),
        "range_low": round(range_low, 4),
        "assumptions": ["4H external swing anchors are selected heuristically from preserved pivots"],
        "limitations": ["liquidity interaction is inferred from raw candle behavior only"],
    }

    if high_raid and low_raid:
        return {
            **base,
            "state": "two_sided_raid",
            "interaction": "ambiguous",
            "direction": "neutral",
            "narrative_hint": "unclear",
            "confidence": 0.2,
            "reason": "latest 4H candle traded through both sides of the dealing range",
        }
    if high_raid:
        if close_above_high:
            return {
                **base,
                "state": "bsl_close_through_acceptance",
                "interaction": "accepted_through",
                "level": round(range_high, 4),
                "direction": "bullish",
                "narrative_hint": "continuation",
                "defended_side": "high_side",
                "confidence": 0.82,
                "reason": "latest 4H candle raided buy-side liquidity and closed through it with acceptance",
            }
        return {
            **base,
            "state": "raid_bsl_reject",
            "interaction": "raid_reject",
            "level": round(range_high, 4),
            "direction": "bearish",
            "narrative_hint": "reversal",
            "defended_side": "high_side",
            "confidence": 0.8,
            "reason": "latest 4H candle raided buy-side liquidity and closed back below the range high",
        }
    if low_raid:
        if close_below_low:
            return {
                **base,
                "state": "ssl_close_through_acceptance",
                "interaction": "accepted_through",
                "level": round(range_low, 4),
                "direction": "bearish",
                "narrative_hint": "continuation",
                "defended_side": "low_side",
                "confidence": 0.82,
                "reason": "latest 4H candle raided sell-side liquidity and closed through it with acceptance",
            }
        return {
            **base,
            "state": "raid_ssl_reject",
            "interaction": "raid_reject",
            "level": round(range_low, 4),
            "direction": "bullish",
            "narrative_hint": "reversal",
            "defended_side": "low_side",
            "confidence": 0.8,
            "reason": "latest 4H candle raided sell-side liquidity and closed back above the range low",
        }
    if touch_high:
        return {
            **base,
            "state": "touched_bsl",
            "interaction": "touched",
            "level": round(range_high, 4),
            "direction": "neutral",
            "narrative_hint": "watch",
            "defended_side": "high_side",
            "confidence": 0.45,
            "reason": "latest 4H candle touched buy-side liquidity but did not produce a decisive raid or close-through",
        }
    if touch_low:
        return {
            **base,
            "state": "touched_ssl",
            "interaction": "touched",
            "level": round(range_low, 4),
            "direction": "neutral",
            "narrative_hint": "watch",
            "defended_side": "low_side",
            "confidence": 0.45,
            "reason": "latest 4H candle touched sell-side liquidity but did not produce a decisive raid or close-through",
        }

    internal_liquidity = drt.get("internal_liquidity") if isinstance(drt.get("internal_liquidity"), dict) else {}
    internal_high = to_float(internal_liquidity.get("high"))
    internal_low = to_float(internal_liquidity.get("low"))
    internal_tolerance = max(tolerance * 0.25, 0.0)
    valid_internal_high = bool(
        internal_high is not None
        and range_low < internal_high < range_high
    )
    valid_internal_low = bool(
        internal_low is not None
        and range_low < internal_low < range_high
    )
    internal_high_raid = bool(
        valid_internal_high
        and latest_high > (internal_high + internal_tolerance)
    )
    internal_low_raid = bool(
        valid_internal_low
        and latest_low < (internal_low - internal_tolerance)
    )
    if internal_high_raid and internal_low_raid:
        return {
            **base,
            "state": "two_sided_raid",
            "interaction": "ambiguous",
            "direction": "neutral",
            "narrative_hint": "unclear",
            "confidence": 0.18,
            "liquidity_tier": "internal",
            "reference_role": "internal_range_liquidity",
            "reason": "latest 4H candle traded through both internal liquidity references inside the dealing range",
        }
    if internal_high_raid:
        close_through = latest_close > (internal_high + internal_tolerance)
        return {
            **base,
            "state": "bsl_close_through_acceptance" if close_through else "raid_bsl_reject",
            "interaction": "accepted_through" if close_through else "raid_reject",
            "level": round(internal_high, 4),
            "direction": "bullish" if close_through else "bearish",
            "narrative_hint": "continuation" if close_through else "reversal",
            "defended_side": "internal_high_side",
            "confidence": 0.64 if close_through else 0.62,
            "liquidity_tier": "internal",
            "reference_role": "internal_range_liquidity",
            "reason": (
                "latest 4H candle closed through internal buy-side liquidity inside the dealing range"
                if close_through
                else "latest 4H candle raided internal buy-side liquidity and closed back below it"
            ),
        }
    if internal_low_raid:
        close_through = latest_close < (internal_low - internal_tolerance)
        return {
            **base,
            "state": "ssl_close_through_acceptance" if close_through else "raid_ssl_reject",
            "interaction": "accepted_through" if close_through else "raid_reject",
            "level": round(internal_low, 4),
            "direction": "bearish" if close_through else "bullish",
            "narrative_hint": "continuation" if close_through else "reversal",
            "defended_side": "internal_low_side",
            "confidence": 0.64 if close_through else 0.62,
            "liquidity_tier": "internal",
            "reference_role": "internal_range_liquidity",
            "reason": (
                "latest 4H candle closed through internal sell-side liquidity inside the dealing range"
                if close_through
                else "latest 4H candle raided internal sell-side liquidity and closed back above it"
            ),
        }
    return {
        **base,
        "state": "none",
        "interaction": "none",
        "direction": "neutral",
        "narrative_hint": "unclear",
        "confidence": 0.15,
        "reason": "latest 4H candle did not produce a clear dealing-range liquidity event",
    }


def summarize_4h_drt_state(candles, lookback=48):
    drt = summarize_dealing_range(candles, lookback=lookback)
    if drt.get("state") == "unclear":
        return drt
    liquidity_event = detect_4h_liquidity_event(candles, drt_summary=drt)
    drt = dict(drt)
    drt["liquidity_event"] = liquidity_event
    drt["open_objective"] = (
        "upside"
        if liquidity_event.get("direction") == "bullish"
        else "downside"
        if liquidity_event.get("direction") == "bearish"
        else "unclear"
    )
    return drt


def infer_4h_bias(candles, drt_summary=None):
    if len(candles) < 8:
        return {"bias": "neutral", "confidence": 0.0, "reason": "not enough 4H candles"}

    drt = drt_summary if isinstance(drt_summary, dict) else summarize_4h_drt_state(candles)
    range_summary = drt if isinstance(drt, dict) else {}
    liquidity_event = range_summary.get("liquidity_event")
    if not isinstance(liquidity_event, dict):
        liquidity_event = {}
    event_state = clean_string(liquidity_event.get("state")) or "none"
    location = clean_string(range_summary.get("location")) or "unknown"
    last_close = to_float(candles[-1].get("close"))

    if event_state in {"raid_ssl_reject", "bsl_close_through_acceptance"}:
        bias = "bullish"
        reason = clean_string(liquidity_event.get("reason")) or "4H liquidity interaction supports bullish bias"
        confidence = 0.82
    elif event_state in {"raid_bsl_reject", "ssl_close_through_acceptance"}:
        bias = "bearish"
        reason = clean_string(liquidity_event.get("reason")) or "4H liquidity interaction supports bearish bias"
        confidence = 0.82
    elif event_state in {"touched_ssl", "touched_bsl"}:
        bias = "neutral"
        reason = "4H liquidity was touched but not decided yet"
        confidence = 0.38
    elif location == "discount" and last_close is not None:
        bias = "bullish"
        reason = "price is still in discount, but the liquidity decision is not settled"
        confidence = 0.4
    elif location == "premium" and last_close is not None:
        bias = "bearish"
        reason = "price is still in premium, but the liquidity decision is not settled"
        confidence = 0.4
    else:
        bias = "neutral"
        reason = "4H location and liquidity interaction are mixed"
        confidence = 0.25

    return {
        "bias": bias,
        "reason": reason,
        "confidence": round(confidence, 3),
        "range": {
            "high": drt.get("high"),
            "low": drt.get("low"),
            "midpoint": drt.get("midpoint"),
            "last_close": round(last_close, 4) if last_close is not None else None,
            "location": drt.get("location"),
            "spread": drt.get("spread"),
        },
        "drt": drt,
        "liquidity_event": liquidity_event,
    }
