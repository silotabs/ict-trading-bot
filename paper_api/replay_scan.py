#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from runtime_api import RULES, run_bybit_replay_scan


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run an offline replay scan over recent Bybit public candles."
    )
    parser.add_argument(
        "--instrument",
        default=RULES["allowed_instruments"][0],
        help="Instrument to replay. Default: BTCUSDT.",
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
        help="Maximum replay steps to evaluate. Default: 100.",
    )
    parser.add_argument(
        "--step-stride",
        type=int,
        default=1,
        help="Stride between replay steps. Default: 1.",
    )
    parser.add_argument(
        "--auto-log-candidates",
        action="store_true",
        help="Log replay scanner-verified paper-trade candidates into the journal.",
    )
    parser.add_argument(
        "--record-history",
        action="store_true",
        help="Persist replay scan-history entries.",
    )
    parser.add_argument(
        "--tradable-only",
        action="store_true",
        help="Only evaluate replay windows that fall inside the currently allowed trading sessions.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full JSON result.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only aggregate replay summary information.",
    )
    parser.add_argument(
        "--export-candidates",
        default="",
        help="Optional path to write replay candidate summaries as JSONL.",
    )
    return parser.parse_args()


def format_result(scan_result):
    replay = scan_result.get("context", {}).get("replay") or {}
    evaluation = scan_result.get("paper_trade_evaluation") or {}
    payload = scan_result.get("paper_trade_payload") or {}
    return " | ".join(
        [
            replay.get("reference_at") or "-",
            payload.get("instrument") or "-",
            evaluation.get("decision") or "-",
            f"session={payload.get('session') or '-'}",
            f"direction={payload.get('direction') or '-'}",
        ]
    )


def format_counter(name, values):
    ordered = sorted((values or {}).items(), key=lambda item: (-item[1], item[0]))
    rendered = ", ".join(f"{key}={count}" for key, count in ordered) if ordered else "-"
    return f"{name}: {rendered}"


def write_candidates(path_value, candidates):
    path = Path(path_value).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in candidates:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    return str(path)


def main():
    args = parse_args()
    result = run_bybit_replay_scan(
        symbol=args.instrument.strip().upper(),
        category=args.category,
        auto_log_candidates=args.auto_log_candidates,
        record_history=args.record_history,
        max_steps=args.max_steps,
        step_stride=args.step_stride,
        tradable_only=args.tradable_only,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        raise SystemExit(0 if result.get("ok") else 2)

    if not result.get("ok"):
        print(f"replay error: {result.get('error', 'replay failed')}")
        raise SystemExit(2)

    export_path = ""
    if args.export_candidates:
        export_path = write_candidates(args.export_candidates, result.get("candidate_summaries") or [])

    print(
        f"replay instrument={result['instrument']} steps={result['evaluated_steps']} "
        f"verified_trade_count={result.get('verified_trade_count', 0)} logged_count={result['logged_count']}"
    )
    print(format_counter("decision_counts", result.get("decision_counts")))
    print(format_counter("session_counts", result.get("session_counts")))
    print(format_counter("direction_counts", result.get("direction_counts")))
    print(format_counter("blocker_counts", result.get("blocker_counts")))
    if export_path:
        print(f"candidate_export={export_path}")
    if args.summary_only:
        return
    for item in result.get("results") or []:
        print(format_result(item))


if __name__ == "__main__":
    main()
