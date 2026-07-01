#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from runtime_api import RULES, run_bybit_replay_scan


SHORT_BLOCKER_LABELS = {
    "directional alignment could not be derived": "direction",
    "required checklist field failed: liquidity_sweep": "liquidity_sweep",
    "required checklist field failed: liquidity_event": "liquidity_event",
    "required checklist field failed: mss": "mss",
    "required checklist field failed: displacement": "displacement",
    "required checklist field failed: fresh_fvg": "fresh_fvg",
    "required checklist field failed: clear_invalidation": "clear_invalidation",
    "required checklist field failed: clear_target": "clear_target",
    "required checklist field failed: clear_4h_bias": "clear_4h_bias",
    "required checklist field failed: clear_liquidity_draw": "clear_liquidity_draw",
    "session outside is outside the allowed paper-trading windows": "session_outside",
    "weekend trading is disabled by the current ruleset": "weekend",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate replay-driven tuning guidance across BTCUSDT and ETHUSDT."
    )
    parser.add_argument(
        "--instruments",
        default=",".join(RULES["allowed_instruments"]),
        help="Comma-separated instruments to compare. Default: BTCUSDT,ETHUSDT.",
    )
    parser.add_argument(
        "--category",
        default="linear",
        help="Bybit category. Default: linear.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=100,
        help="Maximum replay steps per instrument. Default: 100.",
    )
    parser.add_argument(
        "--step-stride",
        type=int,
        default=1,
        help="Stride between replay steps. Default: 1.",
    )
    parser.add_argument(
        "--tradable-only",
        action="store_true",
        help="Only evaluate replay windows that fall inside the currently allowed trading sessions.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full JSON tuning report.",
    )
    parser.add_argument(
        "--save-report",
        default="",
        help="Optional path to write the current tuning report as JSON.",
    )
    parser.add_argument(
        "--compare-report",
        default="",
        help="Optional path to a prior JSON tuning report for before/after comparison.",
    )
    return parser.parse_args()


def ordered_items(mapping, limit=None):
    ordered = sorted((mapping or {}).items(), key=lambda item: (-item[1], item[0]))
    if limit is not None:
        return ordered[:limit]
    return ordered


def ratio(count, total):
    if not total:
        return 0.0
    return round(float(count) / float(total), 4)


def short_blocker_name(name):
    return SHORT_BLOCKER_LABELS.get(name, name)


def instrument_summary(result):
    steps = int(result.get("evaluated_steps") or 0)
    verified_trade_count = int(result.get("verified_trade_count") or 0)
    legacy_compat_trade_count = int(result.get("legacy_compat_trade_count") or 0)
    blocker_counts = result.get("blocker_counts") or {}
    blocker_ratios = {
        short_blocker_name(name): ratio(count, steps)
        for name, count in blocker_counts.items()
    }
    top_blockers = [
        {
            "blocker": short_blocker_name(name),
            "count": count,
            "ratio": ratio(count, steps),
        }
        for name, count in ordered_items(blocker_counts, limit=5)
    ]
    return {
        "instrument": result["instrument"],
        "evaluated_steps": steps,
        "verified_trade_count": verified_trade_count,
        "verified_trade_ratio": ratio(verified_trade_count, steps),
        "legacy_compat_trade_count": legacy_compat_trade_count,
        "legacy_compat_trade_ratio": ratio(legacy_compat_trade_count, steps),
        "decision_counts": result.get("decision_counts") or {},
        "session_counts": result.get("session_counts") or {},
        "direction_counts": result.get("direction_counts") or {},
        "blocker_counts": {short_blocker_name(name): count for name, count in blocker_counts.items()},
        "blocker_ratios": blocker_ratios,
        "top_blockers": top_blockers,
    }


def build_gap_report(summaries):
    instruments = [item["instrument"] for item in summaries]
    blocker_names = sorted(
        {
            blocker
            for item in summaries
            for blocker in (item.get("blocker_ratios") or {}).keys()
        }
    )
    gap_report = []
    for blocker in blocker_names:
        ratios = []
        for item in summaries:
            ratios.append(
                {
                    "instrument": item["instrument"],
                    "ratio": float(item.get("blocker_ratios", {}).get(blocker, 0.0)),
                }
            )
        ordered = sorted(ratios, key=lambda item: (-item["ratio"], item["instrument"]))
        highest = ordered[0]
        lowest = ordered[-1]
        gap_report.append(
            {
                "blocker": blocker,
                "gap": round(highest["ratio"] - lowest["ratio"], 4),
                "highest": highest,
                "lowest": lowest,
                "ratios": {item["instrument"]: item["ratio"] for item in ratios},
            }
        )
    gap_report.sort(key=lambda item: (-item["gap"], item["blocker"]))
    return {
        "instrument_count": len(instruments),
        "blocker_gaps": gap_report,
    }


def average_blocker_ratio(summaries, blocker):
    if not summaries:
        return 0.0
    total = 0.0
    for item in summaries:
        ratios = item.get("blocker_ratios", {}) if isinstance(item, dict) else {}
        if blocker == "liquidity_event":
            total += max(float(ratios.get("liquidity_event", 0.0)), float(ratios.get("liquidity_sweep", 0.0)))
        else:
            total += float(ratios.get(blocker, 0.0))
    return round(total / float(len(summaries)), 4)


def build_tuning_hints(summaries, gap_report):
    hints = []
    total_steps = sum(item["evaluated_steps"] for item in summaries)
    total_verified_trades = sum(item["verified_trade_count"] for item in summaries)
    if total_steps and total_verified_trades == 0:
        hints.append(
            "No scanner-verified replay candidates passed in the sampled window, so the current ruleset is still in a heavy filtering phase."
        )

    direction_ratio = average_blocker_ratio(summaries, "direction")
    if direction_ratio >= 0.5:
        hints.append(
            f"Directional alignment is failing in about {direction_ratio:.0%} of replay steps, so the higher-timeframe premise is not resolving into a tradable long/short read yet."
        )

    bias_ratio = average_blocker_ratio(summaries, "clear_4h_bias")
    if bias_ratio >= 0.5:
        hints.append(
            f"4H bias clarity is failing in about {bias_ratio:.0%} of replay steps, so the dealing-range read should be audited before changing lower-timeframe execution filters."
        )

    mss_ratio = average_blocker_ratio(summaries, "mss")
    if mss_ratio >= 0.6:
        hints.append(
            f"MSS is the dominant blocker across the sampled markets at about {mss_ratio:.0%} of replay steps, so that heuristic is the first place to audit for over-strictness."
        )

    liquidity_event_ratio = max(
        average_blocker_ratio(summaries, "liquidity_event"),
        average_blocker_ratio(summaries, "liquidity_sweep"),
    )
    if liquidity_event_ratio >= 0.5:
        hints.append(
            f"Liquidity-event alignment is failing in about {liquidity_event_ratio:.0%} of replay steps across the sampled markets, which suggests the higher-timeframe liquidity gate is still excluding a large share of setups."
        )

    displacement_ratio = average_blocker_ratio(summaries, "displacement")
    if displacement_ratio >= 0.35:
        hints.append(
            f"Displacement is blocking about {displacement_ratio:.0%} of replay steps, so the displacement threshold may be contributing materially to low candidate flow."
        )

    session_ratio = average_blocker_ratio(summaries, "session_outside")
    if session_ratio >= 0.3:
        hints.append(
            f"Session gating is active in about {session_ratio:.0%} of replay steps, so part of the low candidate rate is structural rather than purely pattern-detection strictness."
        )

    for item in gap_report.get("blocker_gaps") or []:
        if item["gap"] < 0.25:
            continue
        blocker = item["blocker"]
        highest = item["highest"]
        lowest = item["lowest"]
        hints.append(
            f"{blocker} is materially stricter on {highest['instrument']} ({highest['ratio']:.0%}) than on {lowest['instrument']} ({lowest['ratio']:.0%}), so that heuristic is not behaving evenly across BTC and ETH."
        )
        if len(hints) >= 6:
            break

    if not hints:
        hints.append(
            "Replay blocker ratios look reasonably balanced in this sample, so the next step is to increase the replay window and inspect individual candidate summaries before changing rules."
        )

    return hints


def format_counter(mapping, limit=5):
    items = ordered_items(mapping, limit=limit)
    if not items:
        return "-"
    return ", ".join(f"{key}={count}" for key, count in items)


def format_top_blockers(items):
    if not items:
        return "-"
    return ", ".join(f"{item['blocker']}={item['count']} ({item['ratio']:.0%})" for item in items)


def build_tuning_payload(instruments, category="linear", max_steps=100, step_stride=1, tradable_only=False):
    raw_results = []
    failures = []

    for instrument in instruments:
        result = run_bybit_replay_scan(
            symbol=instrument,
            category=category,
            auto_log_candidates=False,
            record_history=False,
            max_steps=max_steps,
            step_stride=step_stride,
            tradable_only=tradable_only,
        )
        if not result.get("ok"):
            failures.append({"instrument": instrument, "error": result.get("error", "replay failed")})
            continue
        raw_results.append(result)

    summaries = [instrument_summary(item) for item in raw_results]
    gap_report = build_gap_report(summaries)
    return {
        "ok": not failures,
        "instrument_count": len(instruments),
        "compared_count": len(summaries),
        "failures": failures,
        "summaries": summaries,
        "gap_report": gap_report,
        "tuning_hints": build_tuning_hints(summaries, gap_report),
        "config": {
            "instruments": list(instruments),
            "category": category,
            "max_steps": int(max_steps),
            "step_stride": int(step_stride),
            "tradable_only": bool(tradable_only),
        },
    }


def write_report(path_value, payload):
    path = Path(path_value).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(path)


def load_report(path_value):
    path = Path(path_value).expanduser()
    return json.loads(path.read_text(encoding="utf-8"))


def compare_reports(previous_payload, current_payload):
    previous_map = {item["instrument"]: item for item in previous_payload.get("summaries") or []}
    current_map = {item["instrument"]: item for item in current_payload.get("summaries") or []}
    instruments = sorted(set(previous_map.keys()) | set(current_map.keys()))
    comparisons = []
    for instrument in instruments:
        previous = previous_map.get(instrument) or {}
        current = current_map.get(instrument) or {}
        blocker_names = sorted(
            set((previous.get("blocker_ratios") or {}).keys())
            | set((current.get("blocker_ratios") or {}).keys())
        )
        blocker_deltas = []
        for blocker in blocker_names:
            previous_ratio = float((previous.get("blocker_ratios") or {}).get(blocker, 0.0))
            current_ratio = float((current.get("blocker_ratios") or {}).get(blocker, 0.0))
            blocker_deltas.append(
                {
                    "blocker": blocker,
                    "previous_ratio": previous_ratio,
                    "current_ratio": current_ratio,
                    "delta": round(current_ratio - previous_ratio, 4),
                }
            )
        blocker_deltas.sort(key=lambda item: (-abs(item["delta"]), item["blocker"]))
        comparisons.append(
            {
                "instrument": instrument,
                "previous_steps": int(previous.get("evaluated_steps") or 0),
                "current_steps": int(current.get("evaluated_steps") or 0),
                "verified_trade_ratio_delta": round(
                    float(current.get("verified_trade_ratio") or 0.0)
                    - float(previous.get("verified_trade_ratio") or 0.0),
                    4,
                ),
                "verified_trade_count_delta": int(current.get("verified_trade_count") or 0)
                - int(previous.get("verified_trade_count") or 0),
                "legacy_compat_trade_ratio_delta": round(
                    float(current.get("legacy_compat_trade_ratio") or 0.0)
                    - float(previous.get("legacy_compat_trade_ratio") or 0.0),
                    4,
                ),
                "legacy_compat_trade_count_delta": int(current.get("legacy_compat_trade_count") or 0)
                - int(previous.get("legacy_compat_trade_count") or 0),
                "top_blocker_deltas": blocker_deltas[:5],
            }
        )
    return {
        "previous_compared_count": int(previous_payload.get("compared_count") or 0),
        "current_compared_count": int(current_payload.get("compared_count") or 0),
        "instrument_deltas": comparisons,
    }


def format_delta(value):
    if value > 0:
        return f"+{value:.0%}"
    if value < 0:
        return f"{value:.0%}"
    return "0%"


def main():
    args = parse_args()
    instruments = [item.strip().upper() for item in args.instruments.split(",") if item.strip()]
    payload = build_tuning_payload(
        instruments=instruments,
        category=args.category,
        max_steps=args.max_steps,
        step_stride=args.step_stride,
        tradable_only=args.tradable_only,
    )
    saved_report_path = ""
    if args.save_report:
        saved_report_path = write_report(args.save_report, payload)

    comparison = None
    if args.compare_report:
        comparison = compare_reports(load_report(args.compare_report), payload)
        payload["comparison"] = comparison

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        raise SystemExit(0 if payload["ok"] else 2)

    summaries = payload.get("summaries") or []
    gap_report = payload.get("gap_report") or {}

    for item in summaries:
        print(
            f"tune instrument={item['instrument']} steps={item['evaluated_steps']} "
            f"verified_trade_count={item.get('verified_trade_count', 0)} "
            f"verified_trade_ratio={item.get('verified_trade_ratio', 0.0):.0%}"
        )
        print(f"decision_counts: {format_counter(item.get('decision_counts'))}")
        print(f"session_counts: {format_counter(item.get('session_counts'))}")
        print(f"direction_counts: {format_counter(item.get('direction_counts'))}")
        print(f"top_blockers: {format_top_blockers(item.get('top_blockers'))}")
        print(
            "compatibility: "
            f"legacy_compat_trade_count={item.get('legacy_compat_trade_count', 0)} "
            f"legacy_compat_trade_ratio={item.get('legacy_compat_trade_ratio', 0.0):.0%}"
        )
        print()

    gap_items = (gap_report.get("blocker_gaps") or [])[:5]
    if gap_items:
        print("cross_market_gaps:")
        for item in gap_items:
            print(
                f"- {item['blocker']}: {item['highest']['instrument']}={item['highest']['ratio']:.0%}, "
                f"{item['lowest']['instrument']}={item['lowest']['ratio']:.0%}, gap={item['gap']:.0%}"
            )
        print()

    print("tuning_hints:")
    for hint in payload["tuning_hints"]:
        print(f"- {hint}")

    if comparison:
        print()
        print("comparison:")
        for item in comparison.get("instrument_deltas") or []:
            print(
                f"- {item['instrument']}: verified_trade_ratio_delta={format_delta(item['verified_trade_ratio_delta'])}, "
                f"verified_trade_count_delta={item['verified_trade_count_delta']}"
            )
            print(
                "  compatibility: "
                f"legacy_compat_trade_ratio_delta={format_delta(item['legacy_compat_trade_ratio_delta'])}, "
                f"legacy_compat_trade_count_delta={item['legacy_compat_trade_count_delta']}"
            )
            if item.get("top_blocker_deltas"):
                rendered = ", ".join(
                    f"{delta['blocker']}={format_delta(delta['delta'])}"
                    for delta in item["top_blocker_deltas"]
                )
                print(f"  blocker_deltas: {rendered}")

    if saved_report_path:
        print()
        print(f"saved_report={saved_report_path}")

    failures = payload.get("failures") or []
    if failures:
        print()
        for item in failures:
            print(f"tune error {item['instrument']}: {item['error']}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
