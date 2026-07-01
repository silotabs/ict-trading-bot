#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from runtime_api import RULES, run_bybit_replay_scan


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compare replay summaries across BTCUSDT and ETHUSDT."
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
        "--summary-only",
        action="store_true",
        help="Print only the aggregate compare summary.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full JSON comparison result.",
    )
    parser.add_argument(
        "--export-candidates-dir",
        default="",
        help="Optional directory to write one JSONL candidate export file per instrument.",
    )
    return parser.parse_args()


def sorted_top_items(mapping, limit=5):
    ordered = sorted((mapping or {}).items(), key=lambda item: (-item[1], item[0]))
    return ordered[:limit]


def render_counter(label, mapping):
    items = sorted_top_items(mapping, limit=8)
    rendered = ", ".join(f"{key}={count}" for key, count in items) if items else "-"
    return f"{label}: {rendered}"


def write_candidates(directory, instrument, candidates):
    path = Path(directory).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    output_path = path / f"{instrument.lower()}-replay-candidates.jsonl"
    with output_path.open("w", encoding="utf-8") as handle:
        for item in candidates:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    return str(output_path)


def main():
    args = parse_args()
    instruments = [item.strip().upper() for item in args.instruments.split(",") if item.strip()]
    comparisons = []
    export_paths = {}
    failures = []

    for instrument in instruments:
        result = run_bybit_replay_scan(
            symbol=instrument,
            category=args.category,
            auto_log_candidates=False,
            record_history=False,
            max_steps=args.max_steps,
            step_stride=args.step_stride,
            tradable_only=args.tradable_only,
        )
        if not result.get("ok"):
            failures.append({"instrument": instrument, "error": result.get("error", "replay failed")})
            continue
        comparisons.append(result)
        if args.export_candidates_dir:
            export_paths[instrument] = write_candidates(
                args.export_candidates_dir,
                instrument,
                result.get("candidate_summaries") or [],
            )

    payload = {
        "ok": not failures,
        "instrument_count": len(instruments),
        "compared_count": len(comparisons),
        "failures": failures,
        "results": comparisons,
        "export_paths": export_paths,
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        raise SystemExit(0 if payload["ok"] else 2)

    for result in comparisons:
        instrument = result["instrument"]
        print(
            f"compare instrument={instrument} steps={result['evaluated_steps']} "
            f"verified_trade_count={result.get('verified_trade_count', 0)} logged_count={result['logged_count']}"
        )
        print(render_counter("decision_counts", result.get("decision_counts")))
        print(render_counter("session_counts", result.get("session_counts")))
        print(render_counter("direction_counts", result.get("direction_counts")))
        print(render_counter("blocker_counts", result.get("blocker_counts")))
        if instrument in export_paths:
            print(f"candidate_export={export_paths[instrument]}")
        if not args.summary_only:
            print()

    if failures:
        for item in failures:
            print(f"compare error {item['instrument']}: {item['error']}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
