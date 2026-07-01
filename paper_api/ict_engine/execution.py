from __future__ import annotations

from .utils import clean_string, median_value, parse_iso_datetime


def normalize_expected_direction(value):
    expected = clean_string(value)
    if expected in {"long", "bullish"}:
        return "bullish"
    if expected in {"short", "bearish"}:
        return "bearish"
    return ""


def detector_none(
    *,
    state="none",
    reason,
    layer,
    role,
    timeframe="",
    confidence=0.12,
    evidence=None,
    assumptions=None,
    limitations=None,
    legacy_alias=False,
):
    payload = {
        "state": state,
        "confidence": round(float(confidence), 3),
        "reason": clean_string(reason) or "detector did not produce a clear read",
        "layer": layer,
        "role": role,
        "evidence": evidence if isinstance(evidence, dict) else {},
        "assumptions": list(assumptions or []),
        "limitations": list(limitations or []),
    }
    if timeframe:
        payload["timeframe"] = timeframe
    if legacy_alias:
        payload["legacy_alias"] = True
    return payload


def detector_hit(
    *,
    state,
    reason,
    layer,
    role,
    timeframe="",
    confidence=0.7,
    evidence=None,
    assumptions=None,
    limitations=None,
    legacy_alias=False,
    **extra,
):
    payload = {
        "state": state,
        "confidence": round(float(confidence), 3),
        "reason": clean_string(reason) or "detector produced a signal",
        "layer": layer,
        "role": role,
        "evidence": evidence if isinstance(evidence, dict) else {},
        "assumptions": list(assumptions or []),
        "limitations": list(limitations or []),
    }
    if timeframe:
        payload["timeframe"] = timeframe
    if legacy_alias:
        payload["legacy_alias"] = True
    payload.update(extra)
    return payload


def recent_swings(candles, left=2, right=2):
    swings = []
    for index in range(left, len(candles) - right):
        current = candles[index]
        highs_left = [candles[i]["high"] for i in range(index - left, index)]
        highs_right = [candles[i]["high"] for i in range(index + 1, index + right + 1)]
        lows_left = [candles[i]["low"] for i in range(index - left, index)]
        lows_right = [candles[i]["low"] for i in range(index + 1, index + right + 1)]

        if current["high"] is not None and current["high"] > max(highs_left + highs_right):
            swings.append(
                {
                    "type": "high",
                    "price": current["high"],
                    "at": current["start_at"],
                    "index": index,
                }
            )
        if current["low"] is not None and current["low"] < min(lows_left + lows_right):
            swings.append(
                {
                    "type": "low",
                    "price": current["low"],
                    "at": current["start_at"],
                    "index": index,
                }
            )
    return swings


def _find_active_structure_break(sample, swings, *, direction, after_at, level_tolerance):
    after_dt = parse_iso_datetime(after_at)
    if after_dt is None or direction not in {"bullish", "bearish"}:
        return None
    latest = sample[-1] if sample else {}
    latest_close = latest.get("close")
    if latest_close is None:
        return None

    candidates = []
    for swing in swings:
        if direction == "bullish" and swing["type"] != "high":
            continue
        if direction == "bearish" and swing["type"] != "low":
            continue

        break_index = None
        for index in range(swing["index"] + 1, len(sample)):
            candle = sample[index]
            candle_dt = parse_iso_datetime(candle.get("start_at"))
            if candle_dt is None or candle_dt < after_dt:
                continue
            close = candle.get("close")
            high = candle.get("high")
            low = candle.get("low")
            if close is None:
                continue
            if direction == "bullish":
                accepted = close > (swing["price"] + level_tolerance * 0.25)
                probed_and_held = high is not None and high > swing["price"] and close >= (swing["price"] - level_tolerance)
            else:
                accepted = close < (swing["price"] - level_tolerance * 0.25)
                probed_and_held = low is not None and low < swing["price"] and close <= (swing["price"] + level_tolerance)
            if accepted or probed_and_held:
                break_index = index
                break

        if break_index is None:
            continue

        if direction == "bullish":
            protected_swing = next(
                (
                    item
                    for item in reversed(swings)
                    if item["type"] == "low" and swing["index"] < item["index"] < break_index
                ),
                None,
            )
            if protected_swing is not None:
                protected_level = protected_swing["price"]
                protected_at = protected_swing["at"]
            else:
                protected_slice = sample[swing["index"]:break_index + 1]
                protected_values = [candle["low"] for candle in protected_slice if candle["low"] is not None]
                if not protected_values:
                    continue
                protected_level = min(protected_values)
                protected_at = None
            invalidated = any(
                candle.get("close") is not None and candle["close"] < (protected_level - level_tolerance)
                for candle in sample[break_index + 1:]
            )
            still_active = latest_close >= (protected_level - level_tolerance)
        else:
            protected_swing = next(
                (
                    item
                    for item in reversed(swings)
                    if item["type"] == "high" and swing["index"] < item["index"] < break_index
                ),
                None,
            )
            if protected_swing is not None:
                protected_level = protected_swing["price"]
                protected_at = protected_swing["at"]
            else:
                protected_slice = sample[swing["index"]:break_index + 1]
                protected_values = [candle["high"] for candle in protected_slice if candle["high"] is not None]
                if not protected_values:
                    continue
                protected_level = max(protected_values)
                protected_at = None
            invalidated = any(
                candle.get("close") is not None and candle["close"] > (protected_level + level_tolerance)
                for candle in sample[break_index + 1:]
            )
            still_active = latest_close <= (protected_level + level_tolerance)

        if invalidated or not still_active:
            continue

        candidates.append(
            {
                "state": f"{direction}_mss",
                "level": swing["price"],
                "at": sample[break_index]["start_at"],
                "broken_swing_at": swing["at"],
                "protected_level": protected_level,
                "protected_at": protected_at,
                "break_index": break_index,
            }
        )

    if not candidates:
        return None
    return max(candidates, key=lambda item: item["break_index"])


def detect_recent_sweep_15m(
    candles,
    *,
    config,
    lookback=None,
    search_bars=None,
    reclaim_bars=None,
    close_tolerance_fraction=None,
):
    base_assumptions = [
        "15m sweep is supporting execution context only; it does not replace the 4H DRT/liquidity decision.",
    ]
    base_limitations = [
        "15m sweep is still a candle-only heuristic and can misread noisy intraday liquidity probes.",
    ]
    if any(value is not None for value in (lookback, search_bars, reclaim_bars, close_tolerance_fraction)):
        profiles = [
            {
                "name": "custom",
                "lookback": lookback or config["profiles"][0]["lookback"],
                "search_bars": search_bars or config["profiles"][0]["search_bars"],
                "reclaim_bars": reclaim_bars or config["profiles"][0]["reclaim_bars"],
                "close_tolerance_fraction": (
                    close_tolerance_fraction
                    if close_tolerance_fraction is not None
                    else config["profiles"][0]["close_tolerance_fraction"]
                ),
            }
        ]
    else:
        profiles = config["profiles"]

    had_enough_candles = False
    for profile in profiles:
        lookback_value = profile["lookback"]
        search_value = profile["search_bars"]
        reclaim_value = profile["reclaim_bars"]
        tolerance_fraction = profile["close_tolerance_fraction"]
        if len(candles) < lookback_value + 2:
            continue
        had_enough_candles = True

        start_index = max(lookback_value, len(candles) - search_value)
        for index in range(len(candles) - 1, start_index - 1, -1):
            current = candles[index]
            prior = candles[index - lookback_value:index]
            prior_high = max(candle["high"] for candle in prior if candle["high"] is not None)
            prior_low = min(candle["low"] for candle in prior if candle["low"] is not None)
            tolerance = max((prior_high - prior_low) * tolerance_fraction, 0.0)
            follow_through = candles[index + 1:min(len(candles), index + reclaim_value + 1)]

            reclaimed_below_high = current["close"] <= (prior_high + tolerance)
            if not reclaimed_below_high:
                reclaimed_below_high = any(
                    candle["close"] is not None and candle["close"] <= (prior_high + tolerance)
                    for candle in follow_through
                )

            reclaimed_above_low = current["close"] >= (prior_low - tolerance)
            if not reclaimed_above_low:
                reclaimed_above_low = any(
                    candle["close"] is not None and candle["close"] >= (prior_low - tolerance)
                    for candle in follow_through
                )

            if current["high"] > prior_high and reclaimed_below_high:
                return detector_hit(
                    state="buy_side_sweep",
                    reason="15m buy-side liquidity was raided and reclaimed inside the configured sweep profile",
                    layer="execution_support",
                    role="liquidity_probe",
                    timeframe="15m",
                    confidence=0.56,
                    evidence={
                        "prior_high": round(prior_high, 4),
                        "candle_high": round(current["high"], 4),
                        "candle_close": round(current["close"], 4),
                        "reclaimed_below_high": reclaimed_below_high,
                        "profile": profile["name"],
                    },
                    assumptions=base_assumptions,
                    limitations=base_limitations,
                    level=round(prior_high, 4),
                    at=current["start_at"],
                    tolerance=round(tolerance, 4),
                    profile=profile["name"],
                    lookback=lookback_value,
                )
            if current["low"] < prior_low and reclaimed_above_low:
                return detector_hit(
                    state="sell_side_sweep",
                    reason="15m sell-side liquidity was raided and reclaimed inside the configured sweep profile",
                    layer="execution_support",
                    role="liquidity_probe",
                    timeframe="15m",
                    confidence=0.56,
                    evidence={
                        "prior_low": round(prior_low, 4),
                        "candle_low": round(current["low"], 4),
                        "candle_close": round(current["close"], 4),
                        "reclaimed_above_low": reclaimed_above_low,
                        "profile": profile["name"],
                    },
                    assumptions=base_assumptions,
                    limitations=base_limitations,
                    level=round(prior_low, 4),
                    at=current["start_at"],
                    tolerance=round(tolerance, 4),
                    profile=profile["name"],
                    lookback=lookback_value,
                )

    if not had_enough_candles:
        return detector_none(
            reason="not enough 15m candles",
            layer="execution_support",
            role="liquidity_probe",
            timeframe="15m",
            confidence=0.0,
            assumptions=base_assumptions,
            limitations=base_limitations,
        )

    return detector_none(
        reason="no recent 15m liquidity sweep heuristic found",
        layer="execution_support",
        role="liquidity_probe",
        timeframe="15m",
        confidence=0.18,
        assumptions=base_assumptions,
        limitations=base_limitations,
    )


def detect_recent_mss_5m(candles, sweep_state, *, config):
    sample_size = config["sample_size"]
    break_confirm_bars = config["break_confirm_bars"]
    level_tolerance_fraction = config["level_tolerance_fraction"]
    micro_break_lookback = config["micro_break_lookback"]
    micro_break_search_bars = config["micro_break_search_bars"]
    micro_break_follow_through_bars = config["micro_break_follow_through_bars"]

    base_assumptions = [
        "5m MSS is kept only as a legacy compatibility alias while 15m MSS owns the primary structure read.",
    ]
    base_limitations = [
        "5m MSS should not be treated as the primary structure premise in the current house model.",
    ]

    if len(candles) < 12:
        return detector_none(
            reason="not enough 5m candles",
            layer="execution_compatibility",
            role="legacy_structure_alias",
            timeframe="5m",
            confidence=0.0,
            assumptions=base_assumptions,
            limitations=base_limitations,
            legacy_alias=True,
        )

    sample = candles[-sample_size:]
    swings = recent_swings(sample)
    if not swings:
        return detector_none(
            reason="no recent 5m swing structure found",
            layer="execution_compatibility",
            role="legacy_structure_alias",
            timeframe="5m",
            confidence=0.12,
            assumptions=base_assumptions,
            limitations=base_limitations,
            legacy_alias=True,
        )

    recent_ranges = [
        candle["high"] - candle["low"]
        for candle in sample
        if candle["high"] is not None and candle["low"] is not None
    ]
    median_range = median_value(recent_ranges) or 0.0
    level_tolerance = median_range * level_tolerance_fraction
    recent_closes = [candle["close"] for candle in sample[-break_confirm_bars:] if candle["close"] is not None]
    recent_highs = [candle["high"] for candle in sample[-break_confirm_bars:] if candle["high"] is not None]
    recent_lows = [candle["low"] for candle in sample[-break_confirm_bars:] if candle["low"] is not None]

    if sweep_state == "sell_side_sweep":
        anchor_low = next((swing for swing in reversed(swings) if swing["type"] == "low"), None)
        reference_high = None
        if anchor_low is not None:
            reference_high = next(
                (
                    swing
                    for swing in reversed(swings)
                    if swing["type"] == "high" and swing["index"] < anchor_low["index"]
                ),
                None,
            )
        if reference_high is None:
            reference_high = next((swing for swing in reversed(swings) if swing["type"] == "high"), None)
        if reference_high and (
            any(close > reference_high["price"] for close in recent_closes)
            or (
                recent_highs
                and max(recent_highs) > reference_high["price"]
                and max(recent_closes or [0.0]) >= (reference_high["price"] - level_tolerance)
            )
        ):
            return detector_hit(
                state="bullish_mss",
                reason="legacy 5m MSS alias found a bullish break above the local swing reference",
                layer="execution_compatibility",
                role="legacy_structure_alias",
                timeframe="5m",
                confidence=0.42,
                evidence={
                    "reference_high": round(reference_high["price"], 4),
                    "recent_closes": [round(value, 4) for value in recent_closes[-break_confirm_bars:]],
                    "sweep_state": sweep_state,
                },
                assumptions=base_assumptions,
                limitations=base_limitations,
                legacy_alias=True,
                level=round(reference_high["price"], 4),
                at=sample[-1]["start_at"],
                broken_swing_at=reference_high["at"],
                tolerance=round(level_tolerance, 4),
            )
    if sweep_state == "buy_side_sweep":
        anchor_high = next((swing for swing in reversed(swings) if swing["type"] == "high"), None)
        reference_low = None
        if anchor_high is not None:
            reference_low = next(
                (
                    swing
                    for swing in reversed(swings)
                    if swing["type"] == "low" and swing["index"] < anchor_high["index"]
                ),
                None,
            )
        if reference_low is None:
            reference_low = next((swing for swing in reversed(swings) if swing["type"] == "low"), None)
        if reference_low and (
            any(close < reference_low["price"] for close in recent_closes)
            or (
                recent_lows
                and min(recent_lows) < reference_low["price"]
                and min(recent_closes or [reference_low["price"] + level_tolerance + 1.0]) <= (reference_low["price"] + level_tolerance)
            )
        ):
            return detector_hit(
                state="bearish_mss",
                reason="legacy 5m MSS alias found a bearish break below the local swing reference",
                layer="execution_compatibility",
                role="legacy_structure_alias",
                timeframe="5m",
                confidence=0.42,
                evidence={
                    "reference_low": round(reference_low["price"], 4),
                    "recent_closes": [round(value, 4) for value in recent_closes[-break_confirm_bars:]],
                    "sweep_state": sweep_state,
                },
                assumptions=base_assumptions,
                limitations=base_limitations,
                legacy_alias=True,
                level=round(reference_low["price"], 4),
                at=sample[-1]["start_at"],
                broken_swing_at=reference_low["at"],
                tolerance=round(level_tolerance, 4),
            )

    search_start = max(micro_break_lookback, len(sample) - micro_break_search_bars)
    if sweep_state == "sell_side_sweep":
        for index in range(len(sample) - 1, search_start - 1, -1):
            current = sample[index]
            prior = sample[index - micro_break_lookback:index]
            prior_high = max(candle["high"] for candle in prior if candle["high"] is not None)
            follow_through = sample[index:min(len(sample), index + micro_break_follow_through_bars + 1)]
            follow_closes = [candle["close"] for candle in follow_through if candle["close"] is not None]
            if (
                current["high"] is not None
                and current["close"] is not None
                and current["open"] is not None
                and current["close"] > current["open"]
                and current["high"] > prior_high
                and max(follow_closes or [0.0]) >= (prior_high - level_tolerance)
            ):
                return detector_hit(
                    state="bullish_mss",
                    reason="legacy 5m MSS alias found a bullish micro-break through the local swing reference",
                    layer="execution_compatibility",
                    role="legacy_structure_alias",
                    timeframe="5m",
                    confidence=0.32,
                    evidence={
                        "prior_high": round(prior_high, 4),
                        "sweep_state": sweep_state,
                        "micro_break": True,
                    },
                    assumptions=base_assumptions,
                    limitations=base_limitations,
                    legacy_alias=True,
                    level=round(prior_high, 4),
                    at=current["start_at"],
                    micro_break=True,
                )
    if sweep_state == "buy_side_sweep":
        for index in range(len(sample) - 1, search_start - 1, -1):
            current = sample[index]
            prior = sample[index - micro_break_lookback:index]
            prior_low = min(candle["low"] for candle in prior if candle["low"] is not None)
            follow_through = sample[index:min(len(sample), index + micro_break_follow_through_bars + 1)]
            follow_closes = [candle["close"] for candle in follow_through if candle["close"] is not None]
            if (
                current["low"] is not None
                and current["close"] is not None
                and current["open"] is not None
                and current["close"] < current["open"]
                and current["low"] < prior_low
                and min(follow_closes or [prior_low + level_tolerance + 1.0]) <= (prior_low + level_tolerance)
            ):
                return detector_hit(
                    state="bearish_mss",
                    reason="legacy 5m MSS alias found a bearish micro-break through the local swing reference",
                    layer="execution_compatibility",
                    role="legacy_structure_alias",
                    timeframe="5m",
                    confidence=0.32,
                    evidence={
                        "prior_low": round(prior_low, 4),
                        "sweep_state": sweep_state,
                        "micro_break": True,
                    },
                    assumptions=base_assumptions,
                    limitations=base_limitations,
                    legacy_alias=True,
                    level=round(prior_low, 4),
                    at=current["start_at"],
                    micro_break=True,
                )

    return detector_none(
        reason="no aligned 5m MSS heuristic found",
        layer="execution_compatibility",
        role="legacy_structure_alias",
        timeframe="5m",
        confidence=0.14,
        assumptions=base_assumptions,
        limitations=base_limitations,
        legacy_alias=True,
    )


def detect_recent_mss_15m(candles, expected_direction="", after_at=None, *, config):
    sample_size = config["sample_size"]
    break_confirm_bars = config["break_confirm_bars"]
    level_tolerance_fraction = config["level_tolerance_fraction"]
    micro_break_lookback = config["micro_break_lookback"]
    micro_break_search_bars = config["micro_break_search_bars"]
    micro_break_follow_through_bars = config["micro_break_follow_through_bars"]

    base_assumptions = [
        "15m MSS is the primary lower-timeframe structure confirmation after the higher-timeframe liquidity decision.",
    ]
    base_limitations = [
        "15m MSS is still inferred from candle structure only and can remain ambiguous in choppy conditions.",
    ]

    if len(candles) < 12:
        return detector_none(
            reason="not enough 15m candles",
            layer="narrative_execution_bridge",
            role="structure_confirmation",
            timeframe="15m",
            confidence=0.0,
            assumptions=base_assumptions,
            limitations=base_limitations,
        )

    sample = candles[-sample_size:]
    structure_sample = sample
    after_dt = parse_iso_datetime(after_at)
    if after_dt is not None:
        post_event = []
        for candle in sample:
            candle_dt = parse_iso_datetime(candle.get("start_at"))
            if candle_dt is not None and candle_dt >= after_dt:
                post_event.append(candle)
        if len(post_event) >= 6:
            sample = post_event

    swings = recent_swings(sample)
    if not swings:
        return detector_none(
            reason="no recent 15m swing structure found",
            layer="narrative_execution_bridge",
            role="structure_confirmation",
            timeframe="15m",
            confidence=0.1,
            evidence={"after_at": after_at},
            assumptions=base_assumptions,
            limitations=base_limitations,
        )

    recent_ranges = [
        candle["high"] - candle["low"]
        for candle in sample
        if candle["high"] is not None and candle["low"] is not None
    ]
    median_range = median_value(recent_ranges) or 0.0
    level_tolerance = median_range * level_tolerance_fraction
    recent_closes = [candle["close"] for candle in sample[-break_confirm_bars:] if candle["close"] is not None]
    recent_highs = [candle["high"] for candle in sample[-break_confirm_bars:] if candle["high"] is not None]
    recent_lows = [candle["low"] for candle in sample[-break_confirm_bars:] if candle["low"] is not None]
    expected = normalize_expected_direction(expected_direction)

    if expected in {"", "bullish"}:
        anchor_low = next((swing for swing in reversed(swings) if swing["type"] == "low"), None)
        reference_high = None
        if anchor_low is not None:
            reference_high = next(
                (
                    swing
                    for swing in reversed(swings)
                    if swing["type"] == "high" and swing["index"] < anchor_low["index"]
                ),
                None,
            )
        if reference_high is None:
            reference_high = next((swing for swing in reversed(swings) if swing["type"] == "high"), None)
        if reference_high and (
            any(close > reference_high["price"] for close in recent_closes)
            or (
                recent_highs
                and max(recent_highs) > reference_high["price"]
                and max(recent_closes or [0.0]) >= (reference_high["price"] - level_tolerance)
            )
        ):
            return detector_hit(
                state="bullish_mss",
                reason="15m bullish MSS confirmed above the most recent opposing swing reference",
                layer="narrative_execution_bridge",
                role="structure_confirmation",
                timeframe="15m",
                confidence=0.72,
                evidence={
                    "reference_high": round(reference_high["price"], 4),
                    "after_at": after_at,
                    "expected_direction": expected,
                    "recent_closes": [round(value, 4) for value in recent_closes[-break_confirm_bars:]],
                },
                assumptions=base_assumptions,
                limitations=base_limitations,
                level=round(reference_high["price"], 4),
                at=sample[-1]["start_at"],
                broken_swing_at=reference_high["at"],
                tolerance=round(level_tolerance, 4),
            )

    if expected in {"", "bearish"}:
        anchor_high = next((swing for swing in reversed(swings) if swing["type"] == "high"), None)
        reference_low = None
        if anchor_high is not None:
            reference_low = next(
                (
                    swing
                    for swing in reversed(swings)
                    if swing["type"] == "low" and swing["index"] < anchor_high["index"]
                ),
                None,
            )
        if reference_low is None:
            reference_low = next((swing for swing in reversed(swings) if swing["type"] == "low"), None)
        if reference_low and (
            any(close < reference_low["price"] for close in recent_closes)
            or (
                recent_lows
                and min(recent_lows) < reference_low["price"]
                and min(recent_closes or [reference_low["price"] + level_tolerance + 1.0]) <= (reference_low["price"] + level_tolerance)
            )
        ):
            return detector_hit(
                state="bearish_mss",
                reason="15m bearish MSS confirmed below the most recent opposing swing reference",
                layer="narrative_execution_bridge",
                role="structure_confirmation",
                timeframe="15m",
                confidence=0.72,
                evidence={
                    "reference_low": round(reference_low["price"], 4),
                    "after_at": after_at,
                    "expected_direction": expected,
                    "recent_closes": [round(value, 4) for value in recent_closes[-break_confirm_bars:]],
                },
                assumptions=base_assumptions,
                limitations=base_limitations,
                level=round(reference_low["price"], 4),
                at=sample[-1]["start_at"],
                broken_swing_at=reference_low["at"],
                tolerance=round(level_tolerance, 4),
            )

    search_start = max(micro_break_lookback, len(sample) - micro_break_search_bars)
    if expected in {"", "bullish"}:
        for index in range(len(sample) - 1, search_start - 1, -1):
            current = sample[index]
            prior = sample[index - micro_break_lookback:index]
            prior_high = max(candle["high"] for candle in prior if candle["high"] is not None)
            follow_through = sample[index:min(len(sample), index + micro_break_follow_through_bars + 1)]
            follow_closes = [candle["close"] for candle in follow_through if candle["close"] is not None]
            if (
                current["high"] is not None
                and current["close"] is not None
                and current["open"] is not None
                and current["close"] > current["open"]
                and current["high"] > prior_high
                and max(follow_closes or [0.0]) >= (prior_high - level_tolerance)
            ):
                return detector_hit(
                    state="bullish_mss",
                    reason="15m bullish MSS found through a micro-break sequence",
                    layer="narrative_execution_bridge",
                    role="structure_confirmation",
                    timeframe="15m",
                    confidence=0.58,
                    evidence={
                        "prior_high": round(prior_high, 4),
                        "after_at": after_at,
                        "micro_break": True,
                    },
                    assumptions=base_assumptions,
                    limitations=base_limitations,
                    level=round(prior_high, 4),
                    at=current["start_at"],
                    micro_break=True,
                )

    if expected in {"", "bearish"}:
        for index in range(len(sample) - 1, search_start - 1, -1):
            current = sample[index]
            prior = sample[index - micro_break_lookback:index]
            prior_low = min(candle["low"] for candle in prior if candle["low"] is not None)
            follow_through = sample[index:min(len(sample), index + micro_break_follow_through_bars + 1)]
            follow_closes = [candle["close"] for candle in follow_through if candle["close"] is not None]
            if (
                current["low"] is not None
                and current["close"] is not None
                and current["open"] is not None
                and current["close"] < current["open"]
                and current["low"] < prior_low
                and min(follow_closes or [prior_low + level_tolerance + 1.0]) <= (prior_low + level_tolerance)
            ):
                return detector_hit(
                    state="bearish_mss",
                    reason="15m bearish MSS found through a micro-break sequence",
                    layer="narrative_execution_bridge",
                    role="structure_confirmation",
                    timeframe="15m",
                    confidence=0.58,
                    evidence={
                        "prior_low": round(prior_low, 4),
                        "after_at": after_at,
                        "micro_break": True,
                    },
                    assumptions=base_assumptions,
                    limitations=base_limitations,
                    level=round(prior_low, 4),
                    at=current["start_at"],
                    micro_break=True,
                )

    active_direction = expected if expected in {"bullish", "bearish"} else ""
    structure_swings = swings if structure_sample is sample else recent_swings(structure_sample)
    active_break = _find_active_structure_break(
        structure_sample,
        structure_swings,
        direction=active_direction,
        after_at=after_at,
        level_tolerance=level_tolerance,
    )
    if active_break is not None:
        level_key = "reference_high" if active_direction == "bullish" else "reference_low"
        return detector_hit(
            state=active_break["state"],
            reason=f"15m {active_direction} MSS remains active after a prior post-liquidity structure break",
            layer="narrative_execution_bridge",
            role="structure_confirmation",
            timeframe="15m",
            confidence=0.64,
            evidence={
                level_key: round(active_break["level"], 4),
                "after_at": after_at,
                "expected_direction": expected,
                "active_break": True,
                "protected_level": round(active_break["protected_level"], 4),
                "protected_at": active_break.get("protected_at"),
            },
            assumptions=base_assumptions,
            limitations=base_limitations,
            level=round(active_break["level"], 4),
            at=active_break["at"],
            broken_swing_at=active_break["broken_swing_at"],
            protected_level=round(active_break["protected_level"], 4),
            active_break=True,
        )

    return detector_none(
        reason="no aligned 15m MSS heuristic found",
        layer="narrative_execution_bridge",
        role="structure_confirmation",
        timeframe="15m",
        confidence=0.18,
        evidence={"after_at": after_at, "expected_direction": expected},
        assumptions=base_assumptions,
        limitations=base_limitations,
    )


def detect_recent_displacement_5m(candles, after_at=None, expected_direction=None, *, config):
    search_bars = config["search_bars"]
    range_multiple = config["range_multiple"]
    body_multiple = config["body_multiple"]
    body_fraction = config["body_fraction"]
    sequence_range_multiple = config["sequence_range_multiple"]
    sequence_body_multiple = config["sequence_body_multiple"]
    sequence_body_fraction = config["sequence_body_fraction"]
    fvg_break_lookback = int(config.get("fvg_break_lookback", 5))
    fvg_min_gap_range_fraction = float(config.get("fvg_min_gap_range_fraction", 0.12))
    fvg_sequence_body_multiple = float(config.get("fvg_sequence_body_multiple", 1.15))

    base_assumptions = [
        "5m displacement is execution confirmation only and does not repair weak DRT, bias, narrative, or context.",
    ]
    base_limitations = [
        "Displacement is inferred from candle expansion heuristics and can miss discretionary quality cues.",
    ]

    if len(candles) < 22:
        return detector_none(
            reason="not enough 5m candles",
            layer="execution",
            role="displacement_confirmation",
            timeframe="5m",
            confidence=0.0,
            assumptions=base_assumptions,
            limitations=base_limitations,
        )

    after_dt = parse_iso_datetime(after_at)
    expected = normalize_expected_direction(expected_direction)

    for index in range(len(candles) - 1, max(len(candles) - search_bars, 0) - 1, -1):
        candle = candles[index]
        if after_dt is not None:
            candle_dt = parse_iso_datetime(candle.get("start_at"))
            if candle_dt is None or candle_dt < after_dt:
                continue
        prior = candles[max(0, index - 20):index]
        if len(prior) < 10:
            continue
        ranges = [
            candle_item["high"] - candle_item["low"]
            for candle_item in prior
            if candle_item["high"] is not None and candle_item["low"] is not None
        ]
        bodies = [
            abs(candle_item["close"] - candle_item["open"])
            for candle_item in prior
            if candle_item["close"] is not None and candle_item["open"] is not None
        ]
        median_range = median_value(ranges)
        median_body = median_value(bodies)
        current_range = candle["high"] - candle["low"]
        current_body = abs(candle["close"] - candle["open"])
        if (
            median_range
            and median_body
            and current_range >= median_range * range_multiple
            and current_body >= median_body * body_multiple
            and current_body >= current_range * body_fraction
        ):
            direction = "bullish" if candle["close"] > candle["open"] else "bearish"
            if expected and direction != expected:
                continue
            return detector_hit(
                state=direction,
                reason="5m displacement confirmed through a single decisive candle",
                layer="execution",
                role="displacement_confirmation",
                timeframe="5m",
                confidence=0.7,
                evidence={
                    "after_at": after_at,
                    "expected_direction": expected,
                    "current_range": round(current_range, 4),
                    "current_body": round(current_body, 4),
                    "median_range": round(median_range, 4),
                    "median_body": round(median_body, 4),
                },
                assumptions=base_assumptions,
                limitations=base_limitations,
                at=candle["start_at"],
                mode="single",
                range_multiple=round(current_range / median_range, 3),
                body_multiple=round(current_body / median_body, 3),
            )

    for index in range(len(candles) - 1, max(len(candles) - search_bars + 1, 1) - 1, -1):
        first = candles[index - 1]
        second = candles[index]
        if after_dt is not None:
            second_dt = parse_iso_datetime(second.get("start_at"))
            if second_dt is None or second_dt < after_dt:
                continue
        prior = candles[max(0, index - 21):index - 1]
        if len(prior) < 10:
            continue
        if (
            first["open"] is None
            or first["close"] is None
            or first["high"] is None
            or first["low"] is None
            or second["open"] is None
            or second["close"] is None
            or second["high"] is None
            or second["low"] is None
        ):
            continue

        first_direction = "bullish" if first["close"] > first["open"] else "bearish" if first["close"] < first["open"] else None
        second_direction = "bullish" if second["close"] > second["open"] else "bearish" if second["close"] < second["open"] else None
        if first_direction is None or second_direction is None or first_direction != second_direction:
            continue
        if expected and first_direction != expected:
            continue

        ranges = [
            candle_item["high"] - candle_item["low"]
            for candle_item in prior
            if candle_item["high"] is not None and candle_item["low"] is not None
        ]
        bodies = [
            abs(candle_item["close"] - candle_item["open"])
            for candle_item in prior
            if candle_item["close"] is not None and candle_item["open"] is not None
        ]
        median_range = median_value(ranges)
        median_body = median_value(bodies)
        if not median_range or not median_body:
            continue

        combined_high = max(first["high"], second["high"])
        combined_low = min(first["low"], second["low"])
        combined_range = combined_high - combined_low
        combined_body = abs(second["close"] - first["open"])
        sequence_closes_near_extreme = False
        if first_direction == "bullish":
            sequence_closes_near_extreme = second["close"] > first["high"]
        else:
            sequence_closes_near_extreme = second["close"] < first["low"]

        if (
            sequence_closes_near_extreme
            and combined_range >= median_range * sequence_range_multiple
            and combined_body >= median_body * sequence_body_multiple
            and combined_body >= combined_range * sequence_body_fraction
        ):
            return detector_hit(
                state=first_direction,
                reason="5m displacement confirmed through a short continuation sequence",
                layer="execution",
                role="displacement_confirmation",
                timeframe="5m",
                confidence=0.64,
                evidence={
                    "after_at": after_at,
                    "expected_direction": expected,
                    "combined_range": round(combined_range, 4),
                    "combined_body": round(combined_body, 4),
                    "median_range": round(median_range, 4),
                    "median_body": round(median_body, 4),
                },
                assumptions=base_assumptions,
                limitations=base_limitations,
                at=second["start_at"],
                mode="sequence",
                bars=2,
                range_multiple=round(combined_range / median_range, 3),
                body_multiple=round(combined_body / median_body, 3),
            )

    fvg_search_start = max(2, len(candles) - search_bars)
    for index in range(len(candles) - 1, fvg_search_start - 1, -1):
        first = candles[index - 2]
        middle = candles[index - 1]
        third = candles[index]
        if after_dt is not None:
            third_dt = parse_iso_datetime(third.get("start_at"))
            if third_dt is None or third_dt < after_dt:
                continue
        required_values = (
            first.get("open"),
            first.get("high"),
            first.get("low"),
            first.get("close"),
            middle.get("open"),
            middle.get("high"),
            middle.get("low"),
            middle.get("close"),
            third.get("open"),
            third.get("high"),
            third.get("low"),
            third.get("close"),
        )
        if any(value is None for value in required_values):
            continue
        prior = candles[max(0, index - 2 - fvg_break_lookback):index - 2]
        if len(prior) < 3:
            continue
        ranges = [
            candle_item["high"] - candle_item["low"]
            for candle_item in prior
            if candle_item["high"] is not None and candle_item["low"] is not None
        ]
        bodies = [
            abs(candle_item["close"] - candle_item["open"])
            for candle_item in prior
            if candle_item["close"] is not None and candle_item["open"] is not None
        ]
        median_range = median_value(ranges)
        median_body = median_value(bodies)
        if not median_range or not median_body:
            continue

        bullish_gap = third["low"] - first["high"]
        bearish_gap = first["low"] - third["high"]
        sequence_body = abs(third["close"] - first["open"])
        min_gap = median_range * fvg_min_gap_range_fraction
        min_sequence_body = median_body * fvg_sequence_body_multiple

        if expected in {"", "bullish"} and bullish_gap > 0:
            prior_high = max(candle_item["high"] for candle_item in prior if candle_item["high"] is not None)
            break_confirmed = (
                max(middle["high"], third["high"]) > prior_high
                and max(middle["close"], third["close"]) >= prior_high
            )
            if break_confirmed and bullish_gap >= min_gap and sequence_body >= min_sequence_body:
                return detector_hit(
                    state="bullish",
                    reason="5m displacement confirmed by a bullish break that left a fresh FVG",
                    layer="execution",
                    role="displacement_confirmation",
                    timeframe="5m",
                    confidence=0.6,
                    evidence={
                        "after_at": after_at,
                        "expected_direction": expected,
                        "prior_high": round(prior_high, 4),
                        "fvg_lower": round(first["high"], 4),
                        "fvg_upper": round(third["low"], 4),
                        "gap_size": round(bullish_gap, 4),
                        "median_range": round(median_range, 4),
                        "sequence_body": round(sequence_body, 4),
                        "median_body": round(median_body, 4),
                    },
                    assumptions=base_assumptions,
                    limitations=base_limitations,
                    at=third["start_at"],
                    mode="fvg_break",
                    bars=3,
                    gap_range_fraction=round(bullish_gap / median_range, 3),
                    body_multiple=round(sequence_body / median_body, 3),
                )

        if expected in {"", "bearish"} and bearish_gap > 0:
            prior_low = min(candle_item["low"] for candle_item in prior if candle_item["low"] is not None)
            break_confirmed = (
                min(middle["low"], third["low"]) < prior_low
                and min(middle["close"], third["close"]) <= prior_low
            )
            if break_confirmed and bearish_gap >= min_gap and sequence_body >= min_sequence_body:
                return detector_hit(
                    state="bearish",
                    reason="5m displacement confirmed by a bearish break that left a fresh FVG",
                    layer="execution",
                    role="displacement_confirmation",
                    timeframe="5m",
                    confidence=0.6,
                    evidence={
                        "after_at": after_at,
                        "expected_direction": expected,
                        "prior_low": round(prior_low, 4),
                        "fvg_lower": round(third["high"], 4),
                        "fvg_upper": round(first["low"], 4),
                        "gap_size": round(bearish_gap, 4),
                        "median_range": round(median_range, 4),
                        "sequence_body": round(sequence_body, 4),
                        "median_body": round(median_body, 4),
                    },
                    assumptions=base_assumptions,
                    limitations=base_limitations,
                    at=third["start_at"],
                    mode="fvg_break",
                    bars=3,
                    gap_range_fraction=round(bearish_gap / median_range, 3),
                    body_multiple=round(sequence_body / median_body, 3),
                )

    return detector_none(
        reason="no strong 5m displacement heuristic found",
        layer="execution",
        role="displacement_confirmation",
        timeframe="5m",
        confidence=0.18,
        evidence={"after_at": after_at, "expected_direction": expected},
        assumptions=base_assumptions,
        limitations=base_limitations,
    )


def detect_recent_fvg_5m(candles, after_at=None, expected_direction=None):
    base_assumptions = [
        "5m FVG is an execution array only; it should not validate a weak higher-timeframe premise by itself.",
    ]
    base_limitations = [
        "FVG detection is wick-to-wick only and does not yet classify IFVG, OB, BB, MB, or RB with full house precision.",
    ]

    if len(candles) < 5:
        return detector_none(
            reason="not enough 5m candles",
            layer="execution",
            role="entry_array",
            timeframe="5m",
            confidence=0.0,
            assumptions=base_assumptions,
            limitations=base_limitations,
        )

    after_dt = parse_iso_datetime(after_at)
    expected = normalize_expected_direction(expected_direction)

    for index in range(len(candles) - 1, 1, -1):
        first = candles[index - 2]
        third = candles[index]
        third_dt = parse_iso_datetime(third.get("start_at"))
        if after_dt is not None and (third_dt is None or third_dt < after_dt):
            continue
        if third["low"] > first["high"]:
            if expected and expected != "bullish":
                continue
            lower = first["high"]
            upper = third["low"]
            return detector_hit(
                state="bullish",
                reason="fresh bullish 5m FVG formed after the displacement leg",
                layer="execution",
                role="entry_array",
                timeframe="5m",
                confidence=0.68,
                evidence={
                    "after_at": after_at,
                    "expected_direction": expected,
                    "first_high": round(first["high"], 4),
                    "third_low": round(third["low"], 4),
                },
                assumptions=base_assumptions,
                limitations=base_limitations,
                lower=round(lower, 4),
                upper=round(upper, 4),
                midpoint=round((lower + upper) / 2, 4),
                at=third["start_at"],
            )
        if third["high"] < first["low"]:
            if expected and expected != "bearish":
                continue
            lower = third["high"]
            upper = first["low"]
            return detector_hit(
                state="bearish",
                reason="fresh bearish 5m FVG formed after the displacement leg",
                layer="execution",
                role="entry_array",
                timeframe="5m",
                confidence=0.68,
                evidence={
                    "after_at": after_at,
                    "expected_direction": expected,
                    "first_low": round(first["low"], 4),
                    "third_high": round(third["high"], 4),
                },
                assumptions=base_assumptions,
                limitations=base_limitations,
                lower=round(lower, 4),
                upper=round(upper, 4),
                midpoint=round((lower + upper) / 2, 4),
                at=third["start_at"],
            )

    return detector_none(
        reason="no fresh 5m FVG heuristic found",
        layer="execution",
        role="entry_array",
        timeframe="5m",
        confidence=0.18,
        evidence={"after_at": after_at, "expected_direction": expected},
        assumptions=base_assumptions,
        limitations=base_limitations,
    )
