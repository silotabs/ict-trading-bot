from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .drt import detect_swings
from .utils import clean_string, parse_iso_datetime, to_float


DEFAULT_LIQUIDITY_CONTEXT_POLICY = {
    "prior_day_timezone": "UTC",
    "asian_range_timezone": "UTC",
    "asian_range_start_hour": 0,
    "asian_range_end_hour": 6,
    "asian_range_status": "starter_assumption",
    "equal_level_tolerance_fraction": 0.0008,
}

ASIAN_RANGE_ASSUMPTION_REASON = (
    "Asian range uses the configured starter window until the house rules pin a different definition"
)


def _normalize_reference(reference_time, candles):
    parsed = parse_iso_datetime(reference_time)
    if parsed is not None:
        return parsed
    if candles:
        latest = parse_iso_datetime(candles[-1].get("start_at"))
        if latest is not None:
            return latest
    return datetime.now(timezone.utc)


def _select_day_candles(candles, target_day):
    selected = []
    for candle in candles:
        parsed = parse_iso_datetime(candle.get("start_at"))
        if parsed is None:
            continue
        if parsed.date() == target_day:
            selected.append((parsed, candle))
    return selected


def _summarize_extreme(candles, side):
    if not candles:
        return {"price": None, "at": None}
    key = "high" if side == "high" else "low"
    comparator = max if side == "high" else min
    priced = [(to_float(candle.get(key)), at) for at, candle in candles if to_float(candle.get(key)) is not None]
    if not priced:
        return {"price": None, "at": None}
    price = comparator(value for value, _ in priced)
    at = next(at for value, at in priced if value == price)
    return {"price": round(price, 4), "at": at.replace(microsecond=0).isoformat()}


def _recent_swing_summary(candles, limit=4):
    swings = detect_swings(candles, left=2, right=2)
    highs = [swing for swing in swings if swing["type"] == "high"][-limit:]
    lows = [swing for swing in swings if swing["type"] == "low"][-limit:]
    return {
        "highs": [{"price": round(item["price"], 4), "at": item["at"], "index": item["index"]} for item in highs],
        "lows": [{"price": round(item["price"], 4), "at": item["at"], "index": item["index"]} for item in lows],
    }


def _equal_level_candidates(swings, side, tolerance_fraction):
    candidates = [swing for swing in swings if swing["type"] == side]
    if len(candidates) < 2:
        return []

    sorted_candidates = sorted(candidates, key=lambda swing: swing["price"])
    groups = []
    tolerance_fraction = max(float(tolerance_fraction or 0.0), 1e-6)

    for swing in sorted_candidates:
        placed = False
        for group in groups:
            if all(_prices_within_relative_tolerance(swing["price"], member["price"], tolerance_fraction) for member in group):
                group.append(swing)
                placed = True
                break
        if not placed:
            groups.append([swing])

    result = []
    for members in groups:
        if len(members) < 2:
            continue
        prices = [member["price"] for member in members]
        result.append(
            {
                "price": round(sum(prices) / len(prices), 4),
                "count": len(members),
                "members": [{"price": round(member["price"], 4), "at": member["at"]} for member in members[-3:]],
            }
        )
    return sorted(result, key=lambda item: (-item["count"], -item["price"]))[:4]


def _prices_within_relative_tolerance(left, right, tolerance_fraction):
    left = float(left)
    right = float(right)
    denominator = max(abs(left), abs(right), 1e-6)
    relative_distance = abs(left - right) / denominator
    return relative_distance <= float(tolerance_fraction)


def _asian_range_reference_metadata(policy_data):
    assumption_grade = clean_string(policy_data.get("asian_range_status")) or "starter_assumption"
    return {
        "status": assumption_grade,
        "assumption_grade": assumption_grade,
        "assumption_reason": ASIAN_RANGE_ASSUMPTION_REASON,
        "cannot_promote_alignment_alone": True,
    }


def build_liquidity_map(
    drt_summary,
    setup_candles,
    bias_candles,
    reference_time=None,
    policy=None,
):
    policy_data = dict(DEFAULT_LIQUIDITY_CONTEXT_POLICY)
    if isinstance(policy, dict):
        policy_data.update(policy)

    reference_dt = _normalize_reference(reference_time, setup_candles)
    prior_day = reference_dt.date() - timedelta(days=1)
    prior_day_candles = _select_day_candles(setup_candles, prior_day)

    asian_start = int(policy_data.get("asian_range_start_hour", 0))
    asian_end = int(policy_data.get("asian_range_end_hour", 6))
    asian_candles = []
    for candle in setup_candles:
        parsed = parse_iso_datetime(candle.get("start_at"))
        if parsed is None or parsed.date() != reference_dt.date():
            continue
        if asian_start <= parsed.hour < asian_end:
            asian_candles.append((parsed, candle))

    setup_swings = detect_swings(setup_candles, left=2, right=2)
    tolerance_fraction = float(policy_data.get("equal_level_tolerance_fraction", 0.0008))
    asian_range_metadata = _asian_range_reference_metadata(policy_data)

    return {
        "reference_at": reference_dt.replace(microsecond=0).isoformat(),
        "prior_day_high": {
            **_summarize_extreme(prior_day_candles, "high"),
            "timezone": policy_data.get("prior_day_timezone", "UTC"),
        },
        "prior_day_low": {
            **_summarize_extreme(prior_day_candles, "low"),
            "timezone": policy_data.get("prior_day_timezone", "UTC"),
        },
        "asian_range_high": {
            **_summarize_extreme(asian_candles, "high"),
            "timezone": policy_data.get("asian_range_timezone", "UTC"),
            **asian_range_metadata,
            "window": f"{asian_start:02d}:00-{asian_end:02d}:00",
        },
        "asian_range_low": {
            **_summarize_extreme(asian_candles, "low"),
            "timezone": policy_data.get("asian_range_timezone", "UTC"),
            **asian_range_metadata,
            "window": f"{asian_start:02d}:00-{asian_end:02d}:00",
        },
        "equal_high_candidates": _equal_level_candidates(setup_swings[-12:], "high", tolerance_fraction),
        "equal_low_candidates": _equal_level_candidates(setup_swings[-12:], "low", tolerance_fraction),
        "recent_15m_swing_highs": _recent_swing_summary(setup_candles, limit=5)["highs"],
        "recent_15m_swing_lows": _recent_swing_summary(setup_candles, limit=5)["lows"],
        "recent_4h_swing_highs": _recent_swing_summary(bias_candles, limit=4)["highs"],
        "recent_4h_swing_lows": _recent_swing_summary(bias_candles, limit=4)["lows"],
        "internal_liquidity": (drt_summary or {}).get("internal_liquidity") if isinstance(drt_summary, dict) else {},
        "external_liquidity": (drt_summary or {}).get("external_liquidity") if isinstance(drt_summary, dict) else {},
        "assumptions": [
            ASIAN_RANGE_ASSUMPTION_REASON,
        ],
    }
