#!/usr/bin/env python3

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from concept_briefing import build_concept_brief_packet, render_concept_brief_markdown
from concept_acceptance_briefing import (
    build_concept_acceptance_brief_packet,
    render_concept_acceptance_brief_markdown,
)
from concept_acceptance_response import (
    build_structured_acceptance_record,
    validate_acceptance_response,
)
from concept_stage7_decision_briefing import (
    build_concept_stage7_decision_brief_packet,
    render_concept_stage7_decision_brief_markdown,
)
from concept_stage7_decision_response import (
    build_structured_stage7_decision_record,
    validate_stage7_decision_response,
)
from concept_revision_briefing import (
    build_concept_revision_brief_packet,
    render_concept_revision_brief_markdown,
)
from concept_revision_compare_response import (
    build_structured_revision_compare_record,
    validate_revision_compare_response,
)
from concept_review_response import (
    build_structured_review_record,
    validate_structured_review_response,
)
from concept_revision import (
    build_stage5_readiness,
    build_concept_revision_plan,
    evaluate_concept_revision_plan,
    record_concept_revision_evaluation,
    render_concept_revision_plan_markdown,
    summarize_concept_revision_loop,
)
from runtime_paths import default_db_path, default_stack_state_dir
from shared_utils import clean_string as clean_text, parse_iso_datetime, utc_now_iso
from trading_store import PaperTradeStore


BASE_DIR = Path(__file__).resolve().parent
EXECUTION_SPEC_PATH = BASE_DIR / "config" / "execution_spec.json"
AUTO_EXECUTION_POLICY_PATH = BASE_DIR / "config" / "auto_execution_policy.json"
TRADE_MANAGEMENT_POLICY_PATH = BASE_DIR / "config" / "trade_management_policy.json"
CONCEPT_DECISION_POLICY_PATH = BASE_DIR / "config" / "concept_decision_policy.json"
DEFAULT_DB_PATH = str(default_db_path(prefer_existing=True))
DEFAULT_PORT = int(os.environ.get("TRADING_API_PORT", "8787"))
DEFAULT_HOST = os.environ.get("TRADING_API_HOST", "127.0.0.1")
DEFAULT_STATE_DIR = default_stack_state_dir(prefer_existing=True)
DEFAULT_ENV_FILE = (BASE_DIR.parent / ".env").expanduser()
MANIFEST_NAME = "stack_state.json"
STARTUP_GRACE_SECONDS = 90
SQLITE_BUSY_TIMEOUT_SECONDS = 30.0
SQLITE_BUSY_TIMEOUT_MS = int(SQLITE_BUSY_TIMEOUT_SECONDS * 1000)
CONCEPT_REPLAY_BLOCKERS = ("clear_4h_bias", "direction", "liquidity_event", "mss", "displacement")
CONCEPT_BLOCKER_LABELS = {
    "clear_4h_bias": "4H bias clarity",
    "direction": "direction alignment",
}
LEGACY_COMPAT_ARG = "--include-legacy-compat-metrics"


def include_legacy_compat_metrics(args):
    return bool(getattr(args, "include_legacy_compat_metrics", False))


def add_legacy_compat_metrics_arg(parser):
    parser.add_argument(
        LEGACY_COMPAT_ARG,
        action="store_true",
        help=(
            "Include separated legacy paper_trade compatibility counts in operator reports. "
            "Defaults remain verified_paper_trade-only."
        ),
    )


def strip_legacy_compat_metrics(value):
    if isinstance(value, dict):
        stripped = {}
        for key, item in value.items():
            if key == "paper_trade" or str(key).startswith("legacy_compat"):
                continue
            stripped[key] = strip_legacy_compat_metrics(item)
        return stripped
    if isinstance(value, list):
        return [strip_legacy_compat_metrics(item) for item in value]
    return value


def sqlite_connect(path):
    conn = sqlite3.connect(str(Path(path).expanduser()), timeout=SQLITE_BUSY_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    return conn


def iso_is_older(left_raw, right_raw):
    left = parse_iso_datetime(left_raw)
    right = parse_iso_datetime(right_raw)
    if left is None or right is None:
        return False
    return left < right


def iso_age_seconds(raw_value):
    parsed = parse_iso_datetime(raw_value)
    if parsed is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())


def iso_within_seconds_after(value_raw, start_raw, seconds):
    value = parse_iso_datetime(value_raw)
    start = parse_iso_datetime(start_raw)
    if value is None or start is None:
        return False
    try:
        window_seconds = float(seconds or 0)
    except (TypeError, ValueError):
        return False
    delta = (value - start).total_seconds()
    return 0 <= delta <= window_seconds


def parse_args():
    parser = argparse.ArgumentParser(
        description="Control the local trading stack daemons."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="Start the local trading stack.")
    add_shared_runtime_args(start)
    start.add_argument(
        "--with-private-stream",
        action="store_true",
        help="Start the private stream daemon too. Requires BYBIT_API_KEY and BYBIT_API_SECRET.",
    )
    start.add_argument(
        "--with-auto-execution",
        action="store_true",
        help="Start the Wave 1 auto-execution daemon too. The policy remains disabled until enabled in config.",
    )
    start.add_argument(
        "--with-trade-management",
        action="store_true",
        help="Start the Wave 2 trade-management daemon too. The policy remains disabled until enabled in config.",
    )
    start.add_argument(
        "--with-concept-lab",
        action="store_true",
        help="Start the background concept lab daemon too. It keeps evaluating Concept 1 against the local decision policy.",
    )
    start.add_argument(
        "--scan-interval-seconds",
        type=int,
        default=300,
        help="Watchlist scan interval. Default: 300.",
    )
    start.add_argument(
        "--supervisor-interval-seconds",
        type=int,
        default=60,
        help="Supervisor interval. Default: 60.",
    )
    start.add_argument(
        "--ops-interval-seconds",
        type=int,
        default=30,
        help="Operations watchdog interval. Default: 30.",
    )
    start.add_argument(
        "--auto-execution-interval-seconds",
        type=int,
        default=30,
        help="Auto-execution interval. Default: 30.",
    )
    start.add_argument(
        "--trade-management-interval-seconds",
        type=int,
        default=30,
        help="Trade-management interval. Default: 30.",
    )
    start.add_argument(
        "--concept-lab-interval-seconds",
        type=int,
        default=300,
        help="Concept lab interval. Default: 300.",
    )
    start.add_argument(
        "--disable-auto-log-candidates",
        action="store_true",
        help="Do not auto-log watchlist candidates.",
    )

    stop = subparsers.add_parser("stop", help="Stop the local trading stack.")
    add_shared_runtime_args(stop)
    stop.add_argument(
        "--force-after-seconds",
        type=int,
        default=10,
        help="Seconds to wait before SIGKILL. Default: 10.",
    )

    status = subparsers.add_parser("status", help="Show local trading stack status.")
    add_shared_runtime_args(status)
    status.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )

    restart_service = subparsers.add_parser(
        "restart-service",
        help="Restart one managed daemon without bouncing the full stack.",
    )
    add_shared_runtime_args(restart_service)
    restart_service.add_argument(
        "service_name",
        help="Managed service name such as concept_lab_loop, private_stream_loop, or server.",
    )
    restart_service.add_argument(
        "--scan-interval-seconds",
        type=int,
        default=300,
        help="Watchlist scan interval. Default: 300.",
    )
    restart_service.add_argument(
        "--supervisor-interval-seconds",
        type=int,
        default=60,
        help="Supervisor interval. Default: 60.",
    )
    restart_service.add_argument(
        "--ops-interval-seconds",
        type=int,
        default=30,
        help="Operations watchdog interval. Default: 30.",
    )
    restart_service.add_argument(
        "--auto-execution-interval-seconds",
        type=int,
        default=30,
        help="Auto-execution interval. Default: 30.",
    )
    restart_service.add_argument(
        "--trade-management-interval-seconds",
        type=int,
        default=30,
        help="Trade-management interval. Default: 30.",
    )
    restart_service.add_argument(
        "--concept-lab-interval-seconds",
        type=int,
        default=300,
        help="Concept lab interval. Default: 300.",
    )
    restart_service.add_argument(
        "--disable-auto-log-candidates",
        action="store_true",
        help="Do not auto-log watchlist candidates.",
    )
    restart_service.add_argument(
        "--force-after-seconds",
        type=int,
        default=10,
        help="Seconds to wait before SIGKILL during service stop. Default: 10.",
    )
    restart_service.add_argument(
        "--fresh-log",
        action="store_true",
        help="Truncate the service log before starting it again so follow mode only shows the new run.",
    )

    restart = subparsers.add_parser("restart", help="Restart the local trading stack.")
    add_shared_runtime_args(restart)
    restart.add_argument(
        "--with-private-stream",
        action="store_true",
        help="Start the private stream daemon too after restart.",
    )
    restart.add_argument(
        "--with-auto-execution",
        action="store_true",
        help="Start the Wave 1 auto-execution daemon too after restart.",
    )
    restart.add_argument(
        "--with-trade-management",
        action="store_true",
        help="Start the Wave 2 trade-management daemon too after restart.",
    )
    restart.add_argument(
        "--with-concept-lab",
        action="store_true",
        help="Start the background concept lab daemon too after restart.",
    )
    restart.add_argument(
        "--scan-interval-seconds",
        type=int,
        default=300,
        help="Watchlist scan interval. Default: 300.",
    )
    restart.add_argument(
        "--supervisor-interval-seconds",
        type=int,
        default=60,
        help="Supervisor interval. Default: 60.",
    )
    restart.add_argument(
        "--ops-interval-seconds",
        type=int,
        default=30,
        help="Operations watchdog interval. Default: 30.",
    )
    restart.add_argument(
        "--auto-execution-interval-seconds",
        type=int,
        default=30,
        help="Auto-execution interval. Default: 30.",
    )
    restart.add_argument(
        "--trade-management-interval-seconds",
        type=int,
        default=30,
        help="Trade-management interval. Default: 30.",
    )
    restart.add_argument(
        "--concept-lab-interval-seconds",
        type=int,
        default=300,
        help="Concept lab interval. Default: 300.",
    )
    restart.add_argument(
        "--disable-auto-log-candidates",
        action="store_true",
        help="Do not auto-log watchlist candidates.",
    )
    restart.add_argument(
        "--force-after-seconds",
        type=int,
        default=10,
        help="Seconds to wait before SIGKILL during stop. Default: 10.",
    )

    preflight = subparsers.add_parser(
        "preflight",
        help="Validate whether the local stack is ready for guarded testnet automation.",
    )
    add_shared_runtime_args(preflight)
    preflight.add_argument(
        "--with-private-stream",
        action="store_true",
        help="Assume the private stream daemon will be started in this run.",
    )
    preflight.add_argument(
        "--with-auto-execution",
        action="store_true",
        help="Assume the auto-execution daemon will be started in this run.",
    )
    preflight.add_argument(
        "--with-trade-management",
        action="store_true",
        help="Assume the trade-management daemon will be started in this run.",
    )
    preflight.add_argument(
        "--with-concept-lab",
        action="store_true",
        help="Assume the concept lab daemon will be started in this run.",
    )
    preflight.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    preflight.add_argument(
        "--probe-bybit-auth",
        action="store_true",
        help="Require a real Bybit private wallet-balance auth probe for the selected environment before readiness passes.",
    )

    arm = subparsers.add_parser(
        "arm-testnet",
        help="Run preflight and start the guarded testnet automation stack only if it is ready.",
    )
    add_shared_runtime_args(arm)
    arm.add_argument(
        "--scan-interval-seconds",
        type=int,
        default=300,
        help="Watchlist scan interval. Default: 300.",
    )
    arm.add_argument(
        "--supervisor-interval-seconds",
        type=int,
        default=60,
        help="Supervisor interval. Default: 60.",
    )
    arm.add_argument(
        "--ops-interval-seconds",
        type=int,
        default=30,
        help="Operations watchdog interval. Default: 30.",
    )
    arm.add_argument(
        "--auto-execution-interval-seconds",
        type=int,
        default=30,
        help="Auto-execution interval. Default: 30.",
    )
    arm.add_argument(
        "--trade-management-interval-seconds",
        type=int,
        default=30,
        help="Trade-management interval. Default: 30.",
    )
    arm.add_argument(
        "--concept-lab-interval-seconds",
        type=int,
        default=300,
        help="Concept lab interval. Default: 300.",
    )
    arm.add_argument(
        "--with-concept-lab",
        action="store_true",
        help="Start the background concept lab daemon too after readiness passes.",
    )
    arm.add_argument(
        "--disable-auto-log-candidates",
        action="store_true",
        help="Do not auto-log watchlist candidates.",
    )
    arm.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    arm.add_argument(
        "--probe-bybit-auth",
        action="store_true",
        help="Require a real Bybit private wallet-balance auth probe for the selected environment before starting the stack.",
    )

    burnin = subparsers.add_parser(
        "burnin-report",
        help="Summarize local burn-in state from the SQLite DB and daemon manifest.",
    )
    add_shared_runtime_args(burnin)
    burnin.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    burnin.add_argument(
        "--event-limit",
        type=int,
        default=10,
        help="Combined event limit. Default: 10.",
    )
    burnin.add_argument(
        "--proposal-limit",
        type=int,
        default=10,
        help="Recent proposal limit. Default: 10.",
    )
    burnin.add_argument(
        "--action-limit",
        type=int,
        default=10,
        help="Recent execution action limit. Default: 10.",
    )
    burnin.add_argument(
        "--scan-limit",
        type=int,
        default=50,
        help="Recent scan-history limit. Default: 50.",
    )

    burnin_gate = subparsers.add_parser(
        "burnin-gate",
        help="Evaluate recent burn-in health and summarize blockers from the local SQLite DB.",
    )
    add_shared_runtime_args(burnin_gate)
    burnin_gate.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    burnin_gate.add_argument(
        "--event-limit",
        type=int,
        default=25,
        help="Combined event limit. Default: 25.",
    )
    burnin_gate.add_argument(
        "--proposal-limit",
        type=int,
        default=10,
        help="Recent proposal limit. Default: 10.",
    )
    burnin_gate.add_argument(
        "--action-limit",
        type=int,
        default=10,
        help="Recent execution action limit. Default: 10.",
    )
    burnin_gate.add_argument(
        "--scan-limit",
        type=int,
        default=50,
        help="Recent scan-history limit. Default: 50.",
    )

    wave4 = subparsers.add_parser(
        "wave4-review",
        help="Combine burn-in readiness with replay tuning so the current concept can be reviewed for Wave 4 completion.",
    )
    add_shared_runtime_args(wave4)
    wave4.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    wave4.add_argument(
        "--event-limit",
        type=int,
        default=25,
        help="Combined event limit. Default: 25.",
    )
    wave4.add_argument(
        "--proposal-limit",
        type=int,
        default=10,
        help="Recent proposal limit. Default: 10.",
    )
    wave4.add_argument(
        "--action-limit",
        type=int,
        default=10,
        help="Recent execution action limit. Default: 10.",
    )
    wave4.add_argument(
        "--scan-limit",
        type=int,
        default=50,
        help="Recent scan-history limit. Default: 50.",
    )
    wave4.add_argument(
        "--instruments",
        default="BTCUSDT,ETHUSDT",
        help="Comma-separated instruments to use for replay tuning. Default: BTCUSDT,ETHUSDT.",
    )
    wave4.add_argument(
        "--category",
        default="linear",
        help="Bybit category for replay tuning. Default: linear.",
    )
    wave4.add_argument(
        "--max-steps",
        type=int,
        default=100,
        help="Maximum replay steps per instrument. Default: 100.",
    )
    wave4.add_argument(
        "--step-stride",
        type=int,
        default=1,
        help="Stride between replay steps. Default: 1.",
    )
    wave4.add_argument(
        "--tradable-only",
        action="store_true",
        help="Only evaluate replay windows that fall inside the currently allowed trading sessions.",
    )
    add_legacy_compat_metrics_arg(wave4)

    promotion = subparsers.add_parser(
        "promotion-review",
        help="Summarize whether the current single-concept model is ready to graduate beyond Wave 4 burn-in.",
    )
    add_shared_runtime_args(promotion)
    promotion.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    promotion.add_argument(
        "--event-limit",
        type=int,
        default=25,
        help="Combined event limit. Default: 25.",
    )
    promotion.add_argument(
        "--proposal-limit",
        type=int,
        default=10,
        help="Recent proposal limit. Default: 10.",
    )
    promotion.add_argument(
        "--action-limit",
        type=int,
        default=10,
        help="Recent execution action limit. Default: 10.",
    )
    promotion.add_argument(
        "--scan-limit",
        type=int,
        default=50,
        help="Recent scan-history limit. Default: 50.",
    )
    promotion.add_argument(
        "--instruments",
        default="BTCUSDT,ETHUSDT",
        help="Comma-separated instruments to use for replay tuning. Default: BTCUSDT,ETHUSDT.",
    )
    promotion.add_argument(
        "--category",
        default="linear",
        help="Bybit category for replay tuning. Default: linear.",
    )
    promotion.add_argument(
        "--max-steps",
        type=int,
        default=100,
        help="Maximum replay steps per instrument. Default: 100.",
    )
    promotion.add_argument(
        "--step-stride",
        type=int,
        default=1,
        help="Stride between replay steps. Default: 1.",
    )
    promotion.add_argument(
        "--tradable-only",
        action="store_true",
        help="Only evaluate replay windows that fall inside the currently allowed trading sessions.",
    )
    add_legacy_compat_metrics_arg(promotion)

    concept = subparsers.add_parser(
        "concept-review",
        help="Summarize whether the current concept is still collecting evidence, actively being tested, or showing promising live demo behavior.",
    )
    add_shared_runtime_args(concept)
    concept.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    concept.add_argument(
        "--event-limit",
        type=int,
        default=25,
        help="Combined event limit. Default: 25.",
    )
    concept.add_argument(
        "--proposal-limit",
        type=int,
        default=10,
        help="Recent proposal limit. Default: 10.",
    )
    concept.add_argument(
        "--action-limit",
        type=int,
        default=10,
        help="Recent execution action limit. Default: 10.",
    )
    concept.add_argument(
        "--scan-limit",
        type=int,
        default=50,
        help="Recent scan-history limit. Default: 50.",
    )
    concept.add_argument(
        "--instruments",
        default="BTCUSDT,ETHUSDT",
        help="Comma-separated instruments to use for replay tuning. Default: BTCUSDT,ETHUSDT.",
    )
    concept.add_argument(
        "--category",
        default="linear",
        help="Bybit category for replay tuning. Default: linear.",
    )
    concept.add_argument(
        "--max-steps",
        type=int,
        default=12,
        help="Maximum replay steps per instrument. Default: 12.",
    )
    concept.add_argument(
        "--step-stride",
        type=int,
        default=3,
        help="Stride between replay steps. Default: 3.",
    )
    concept.add_argument(
        "--tradable-only",
        action="store_true",
        help="Only evaluate replay windows that fall inside the currently allowed trading sessions.",
    )
    add_legacy_compat_metrics_arg(concept)

    concept_decision = subparsers.add_parser(
        "concept-decision",
        help="Evaluate the current concept against explicit evidence thresholds so we can decide whether to keep testing, revise, or compare it.",
    )
    add_shared_runtime_args(concept_decision)
    concept_decision.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    concept_decision.add_argument(
        "--event-limit",
        type=int,
        default=25,
        help="Combined event limit. Default: 25.",
    )
    concept_decision.add_argument(
        "--proposal-limit",
        type=int,
        default=10,
        help="Recent proposal limit. Default: 10.",
    )
    concept_decision.add_argument(
        "--action-limit",
        type=int,
        default=10,
        help="Recent execution action limit. Default: 10.",
    )
    concept_decision.add_argument(
        "--scan-limit",
        type=int,
        default=50,
        help="Recent scan-history limit. Default: 50.",
    )
    concept_decision.add_argument(
        "--instruments",
        default="BTCUSDT,ETHUSDT",
        help="Comma-separated instruments to use for replay tuning. Default: BTCUSDT,ETHUSDT.",
    )
    concept_decision.add_argument(
        "--category",
        default="linear",
        help="Bybit category for replay tuning. Default: linear.",
    )
    concept_decision.add_argument(
        "--max-steps",
        type=int,
        default=12,
        help="Maximum replay steps per instrument. Default: 12.",
    )
    concept_decision.add_argument(
        "--step-stride",
        type=int,
        default=3,
        help="Stride between replay steps. Default: 3.",
    )
    concept_decision.add_argument(
        "--tradable-only",
        action="store_true",
        help="Only evaluate replay windows that fall inside the currently allowed trading sessions.",
    )
    concept_decision.add_argument(
        "--policy-path",
        default=str(CONCEPT_DECISION_POLICY_PATH),
        help=f"Concept decision policy JSON path. Default: {CONCEPT_DECISION_POLICY_PATH}",
    )
    add_legacy_compat_metrics_arg(concept_decision)

    concept_brief = subparsers.add_parser(
        "concept-brief",
        help="Build an LLM-ready review packet for the current concept using the local house spec and review rubric.",
    )
    add_shared_runtime_args(concept_brief)
    concept_brief.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    concept_brief.add_argument(
        "--event-limit",
        type=int,
        default=25,
        help="Combined event limit. Default: 25.",
    )
    concept_brief.add_argument(
        "--proposal-limit",
        type=int,
        default=10,
        help="Recent proposal limit. Default: 10.",
    )
    concept_brief.add_argument(
        "--action-limit",
        type=int,
        default=10,
        help="Recent execution action limit. Default: 10.",
    )
    concept_brief.add_argument(
        "--scan-limit",
        type=int,
        default=50,
        help="Recent scan-history limit. Default: 50.",
    )
    concept_brief.add_argument(
        "--instruments",
        default="BTCUSDT,ETHUSDT",
        help="Comma-separated instruments to use for replay tuning. Default: BTCUSDT,ETHUSDT.",
    )
    concept_brief.add_argument(
        "--category",
        default="linear",
        help="Bybit category for replay tuning. Default: linear.",
    )
    concept_brief.add_argument(
        "--max-steps",
        type=int,
        default=12,
        help="Maximum replay steps per instrument. Default: 12.",
    )
    concept_brief.add_argument(
        "--step-stride",
        type=int,
        default=3,
        help="Stride between replay steps. Default: 3.",
    )
    concept_brief.add_argument(
        "--tradable-only",
        action="store_true",
        help="Only evaluate replay windows that fall inside the currently allowed trading sessions.",
    )
    concept_brief.add_argument(
        "--policy-path",
        default=str(CONCEPT_DECISION_POLICY_PATH),
        help=f"Concept decision policy JSON path. Default: {CONCEPT_DECISION_POLICY_PATH}",
    )

    concept_revision_brief = subparsers.add_parser(
        "concept-revision-brief",
        help="Build an LLM-ready comparison brief for the saved concept revision loop.",
    )
    add_shared_runtime_args(concept_revision_brief)
    concept_revision_brief.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    concept_revision_brief.add_argument(
        "--event-limit",
        type=int,
        default=25,
        help="Combined event limit. Default: 25.",
    )
    concept_revision_brief.add_argument(
        "--proposal-limit",
        type=int,
        default=10,
        help="Recent proposal limit. Default: 10.",
    )
    concept_revision_brief.add_argument(
        "--action-limit",
        type=int,
        default=10,
        help="Recent execution action limit. Default: 10.",
    )
    concept_revision_brief.add_argument(
        "--scan-limit",
        type=int,
        default=50,
        help="Recent scan-history limit. Default: 50.",
    )
    concept_revision_brief.add_argument(
        "--instruments",
        default="BTCUSDT,ETHUSDT",
        help="Comma-separated instruments to use for replay tuning. Default: BTCUSDT,ETHUSDT.",
    )
    concept_revision_brief.add_argument(
        "--category",
        default="linear",
        help="Bybit category for replay tuning. Default: linear.",
    )
    concept_revision_brief.add_argument(
        "--max-steps",
        type=int,
        default=12,
        help="Maximum replay steps per instrument. Default: 12.",
    )
    concept_revision_brief.add_argument(
        "--step-stride",
        type=int,
        default=3,
        help="Stride between replay steps. Default: 3.",
    )
    concept_revision_brief.add_argument(
        "--tradable-only",
        action="store_true",
        help="Only evaluate replay windows that fall inside the currently allowed trading sessions.",
    )
    concept_revision_brief.add_argument(
        "--policy-path",
        default=str(CONCEPT_DECISION_POLICY_PATH),
        help=f"Concept decision policy JSON path. Default: {CONCEPT_DECISION_POLICY_PATH}",
    )
    concept_revision_brief.add_argument(
        "--artifact-limit",
        type=int,
        default=20,
        help="Maximum saved reviews/revisions to inspect. Default: 20.",
    )
    concept_revision_brief.add_argument(
        "--top-limit",
        type=int,
        default=3,
        help="Maximum top-ranked revisions to include in the brief. Default: 3.",
    )

    concept_acceptance_brief = subparsers.add_parser(
        "concept-acceptance-brief",
        help="Build a Stage 6 acceptance-testing brief from live concept evidence and saved revision history.",
    )
    add_shared_runtime_args(concept_acceptance_brief)
    concept_acceptance_brief.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    concept_acceptance_brief.add_argument(
        "--event-limit",
        type=int,
        default=25,
        help="Combined event limit. Default: 25.",
    )
    concept_acceptance_brief.add_argument(
        "--proposal-limit",
        type=int,
        default=10,
        help="Recent proposal limit. Default: 10.",
    )
    concept_acceptance_brief.add_argument(
        "--action-limit",
        type=int,
        default=10,
        help="Recent execution action limit. Default: 10.",
    )
    concept_acceptance_brief.add_argument(
        "--scan-limit",
        type=int,
        default=50,
        help="Recent scan-history limit. Default: 50.",
    )
    concept_acceptance_brief.add_argument(
        "--instruments",
        default="BTCUSDT,ETHUSDT",
        help="Comma-separated instruments to use for replay tuning. Default: BTCUSDT,ETHUSDT.",
    )
    concept_acceptance_brief.add_argument(
        "--category",
        default="linear",
        help="Bybit category for replay tuning. Default: linear.",
    )
    concept_acceptance_brief.add_argument(
        "--max-steps",
        type=int,
        default=12,
        help="Maximum replay steps per instrument. Default: 12.",
    )
    concept_acceptance_brief.add_argument(
        "--step-stride",
        type=int,
        default=3,
        help="Stride between replay steps. Default: 3.",
    )
    concept_acceptance_brief.add_argument(
        "--tradable-only",
        action="store_true",
        help="Only evaluate replay windows that fall inside the currently allowed trading sessions.",
    )
    concept_acceptance_brief.add_argument(
        "--policy-path",
        default=str(CONCEPT_DECISION_POLICY_PATH),
        help=f"Concept decision policy JSON path. Default: {CONCEPT_DECISION_POLICY_PATH}",
    )
    concept_acceptance_brief.add_argument(
        "--artifact-limit",
        type=int,
        default=20,
        help="Maximum saved reviews/revisions to inspect. Default: 20.",
    )
    concept_acceptance_brief.add_argument(
        "--top-limit",
        type=int,
        default=3,
        help="Maximum top-ranked revisions to include in the brief. Default: 3.",
    )

    concept_stage7_decision_brief = subparsers.add_parser(
        "concept-stage7-decision-brief",
        help="Build a conservative Stage 7 decision-memo brief from the live Stage 6 acceptance state.",
    )
    add_shared_runtime_args(concept_stage7_decision_brief)
    concept_stage7_decision_brief.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    concept_stage7_decision_brief.add_argument(
        "--event-limit",
        type=int,
        default=25,
        help="Combined event limit. Default: 25.",
    )
    concept_stage7_decision_brief.add_argument(
        "--proposal-limit",
        type=int,
        default=10,
        help="Recent proposal limit. Default: 10.",
    )
    concept_stage7_decision_brief.add_argument(
        "--action-limit",
        type=int,
        default=10,
        help="Recent execution action limit. Default: 10.",
    )
    concept_stage7_decision_brief.add_argument(
        "--scan-limit",
        type=int,
        default=50,
        help="Recent scan-history limit. Default: 50.",
    )
    concept_stage7_decision_brief.add_argument(
        "--instruments",
        default="BTCUSDT,ETHUSDT",
        help="Comma-separated instruments to use for replay tuning. Default: BTCUSDT,ETHUSDT.",
    )
    concept_stage7_decision_brief.add_argument(
        "--category",
        default="linear",
        help="Bybit category for replay tuning. Default: linear.",
    )
    concept_stage7_decision_brief.add_argument(
        "--max-steps",
        type=int,
        default=12,
        help="Maximum replay steps per instrument. Default: 12.",
    )
    concept_stage7_decision_brief.add_argument(
        "--step-stride",
        type=int,
        default=3,
        help="Stride between replay steps. Default: 3.",
    )
    concept_stage7_decision_brief.add_argument(
        "--tradable-only",
        action="store_true",
        help="Only evaluate replay windows that fall inside the currently allowed trading sessions.",
    )
    concept_stage7_decision_brief.add_argument(
        "--policy-path",
        default=str(CONCEPT_DECISION_POLICY_PATH),
        help=f"Concept decision policy JSON path. Default: {CONCEPT_DECISION_POLICY_PATH}",
    )
    concept_stage7_decision_brief.add_argument(
        "--artifact-limit",
        type=int,
        default=20,
        help="Maximum saved reviews/revisions to inspect. Default: 20.",
    )
    concept_stage7_decision_brief.add_argument(
        "--top-limit",
        type=int,
        default=3,
        help="Maximum top-ranked revisions to include in the brief. Default: 3.",
    )

    concept_revision_plan = subparsers.add_parser(
        "concept-revision-plan",
        help="Generate a conservative one-variable revision plan from the current concept brief.",
    )
    add_shared_runtime_args(concept_revision_plan)
    concept_revision_plan.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    concept_revision_plan.add_argument(
        "--event-limit",
        type=int,
        default=25,
        help="Combined event limit. Default: 25.",
    )
    concept_revision_plan.add_argument(
        "--proposal-limit",
        type=int,
        default=10,
        help="Recent proposal limit. Default: 10.",
    )
    concept_revision_plan.add_argument(
        "--action-limit",
        type=int,
        default=10,
        help="Recent execution action limit. Default: 10.",
    )
    concept_revision_plan.add_argument(
        "--scan-limit",
        type=int,
        default=50,
        help="Recent scan-history limit. Default: 50.",
    )
    concept_revision_plan.add_argument(
        "--instruments",
        default="BTCUSDT,ETHUSDT",
        help="Comma-separated instruments to use for replay tuning. Default: BTCUSDT,ETHUSDT.",
    )
    concept_revision_plan.add_argument(
        "--category",
        default="linear",
        help="Bybit category for replay tuning. Default: linear.",
    )
    concept_revision_plan.add_argument(
        "--max-steps",
        type=int,
        default=12,
        help="Maximum replay steps per instrument. Default: 12.",
    )
    concept_revision_plan.add_argument(
        "--step-stride",
        type=int,
        default=3,
        help="Stride between replay steps. Default: 3.",
    )
    concept_revision_plan.add_argument(
        "--tradable-only",
        action="store_true",
        help="Only evaluate replay windows that fall inside the currently allowed trading sessions.",
    )
    concept_revision_plan.add_argument(
        "--policy-path",
        default=str(CONCEPT_DECISION_POLICY_PATH),
        help=f"Concept decision policy JSON path. Default: {CONCEPT_DECISION_POLICY_PATH}",
    )
    concept_revision_plan.add_argument(
        "--candidate-id",
        default="",
        help="Optional revision candidate id from concept-brief. Default: first candidate.",
    )
    concept_revision_plan.add_argument(
        "--review-id",
        default="",
        help="Optional saved concept review id to fold into the revision plan.",
    )

    concept_save_review = subparsers.add_parser(
        "concept-save-review",
        help="Validate and persist a structured LLM concept review from a JSON file.",
    )
    add_shared_runtime_args(concept_save_review)
    concept_save_review.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    concept_save_review.add_argument(
        "--event-limit",
        type=int,
        default=25,
        help="Combined event limit. Default: 25.",
    )
    concept_save_review.add_argument(
        "--proposal-limit",
        type=int,
        default=10,
        help="Recent proposal limit. Default: 10.",
    )
    concept_save_review.add_argument(
        "--action-limit",
        type=int,
        default=10,
        help="Recent execution action limit. Default: 10.",
    )
    concept_save_review.add_argument(
        "--scan-limit",
        type=int,
        default=50,
        help="Recent scan-history limit. Default: 50.",
    )
    concept_save_review.add_argument(
        "--instruments",
        default="BTCUSDT,ETHUSDT",
        help="Comma-separated instruments to use for replay tuning. Default: BTCUSDT,ETHUSDT.",
    )
    concept_save_review.add_argument(
        "--category",
        default="linear",
        help="Bybit category for replay tuning. Default: linear.",
    )
    concept_save_review.add_argument(
        "--max-steps",
        type=int,
        default=12,
        help="Maximum replay steps per instrument. Default: 12.",
    )
    concept_save_review.add_argument(
        "--step-stride",
        type=int,
        default=3,
        help="Stride between replay steps. Default: 3.",
    )
    concept_save_review.add_argument(
        "--tradable-only",
        action="store_true",
        help="Only evaluate replay windows that fall inside the currently allowed trading sessions.",
    )
    concept_save_review.add_argument(
        "--policy-path",
        default=str(CONCEPT_DECISION_POLICY_PATH),
        help=f"Concept decision policy JSON path. Default: {CONCEPT_DECISION_POLICY_PATH}",
    )
    concept_save_review.add_argument(
        "--response-file",
        required=True,
        help="Path to the structured LLM review JSON file.",
    )
    concept_save_review.add_argument(
        "--source",
        default="llm",
        help="Review source label. Default: llm.",
    )
    concept_save_review.add_argument(
        "--author",
        default="",
        help="Review author label, such as gpt-5.4.",
    )

    concept_save_acceptance_review = subparsers.add_parser(
        "concept-save-acceptance-review",
        help="Validate and persist a structured LLM Stage 6 acceptance review from a JSON file.",
    )
    add_shared_runtime_args(concept_save_acceptance_review)
    concept_save_acceptance_review.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    concept_save_acceptance_review.add_argument(
        "--event-limit",
        type=int,
        default=25,
        help="Combined event limit. Default: 25.",
    )
    concept_save_acceptance_review.add_argument(
        "--proposal-limit",
        type=int,
        default=10,
        help="Recent proposal limit. Default: 10.",
    )
    concept_save_acceptance_review.add_argument(
        "--action-limit",
        type=int,
        default=10,
        help="Recent execution action limit. Default: 10.",
    )
    concept_save_acceptance_review.add_argument(
        "--scan-limit",
        type=int,
        default=50,
        help="Recent scan-history limit. Default: 50.",
    )
    concept_save_acceptance_review.add_argument(
        "--instruments",
        default="BTCUSDT,ETHUSDT",
        help="Comma-separated instruments to use for replay tuning. Default: BTCUSDT,ETHUSDT.",
    )
    concept_save_acceptance_review.add_argument(
        "--category",
        default="linear",
        help="Bybit category for replay tuning. Default: linear.",
    )
    concept_save_acceptance_review.add_argument(
        "--max-steps",
        type=int,
        default=12,
        help="Maximum replay steps per instrument. Default: 12.",
    )
    concept_save_acceptance_review.add_argument(
        "--step-stride",
        type=int,
        default=3,
        help="Stride between replay steps. Default: 3.",
    )
    concept_save_acceptance_review.add_argument(
        "--tradable-only",
        action="store_true",
        help="Only evaluate replay windows that fall inside the currently allowed trading sessions.",
    )
    concept_save_acceptance_review.add_argument(
        "--policy-path",
        default=str(CONCEPT_DECISION_POLICY_PATH),
        help=f"Concept decision policy JSON path. Default: {CONCEPT_DECISION_POLICY_PATH}",
    )
    concept_save_acceptance_review.add_argument(
        "--artifact-limit",
        type=int,
        default=20,
        help="Maximum saved reviews/revisions to inspect. Default: 20.",
    )
    concept_save_acceptance_review.add_argument(
        "--top-limit",
        type=int,
        default=3,
        help="Maximum top-ranked revisions to include in the brief. Default: 3.",
    )
    concept_save_acceptance_review.add_argument(
        "--response-file",
        required=True,
        help="Path to the structured LLM acceptance-review JSON file.",
    )
    concept_save_acceptance_review.add_argument(
        "--source",
        default="llm",
        help="Review source label. Default: llm.",
    )
    concept_save_acceptance_review.add_argument(
        "--author",
        default="",
        help="Review author label, such as gpt-5.4.",
    )

    concept_save_stage7_decision = subparsers.add_parser(
        "concept-save-stage7-decision",
        help="Validate and persist a structured LLM Stage 7 decision memo from a JSON file.",
    )
    add_shared_runtime_args(concept_save_stage7_decision)
    concept_save_stage7_decision.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    concept_save_stage7_decision.add_argument(
        "--event-limit",
        type=int,
        default=25,
        help="Combined event limit. Default: 25.",
    )
    concept_save_stage7_decision.add_argument(
        "--proposal-limit",
        type=int,
        default=10,
        help="Recent proposal limit. Default: 10.",
    )
    concept_save_stage7_decision.add_argument(
        "--action-limit",
        type=int,
        default=10,
        help="Recent execution action limit. Default: 10.",
    )
    concept_save_stage7_decision.add_argument(
        "--scan-limit",
        type=int,
        default=50,
        help="Recent scan-history limit. Default: 50.",
    )
    concept_save_stage7_decision.add_argument(
        "--instruments",
        default="BTCUSDT,ETHUSDT",
        help="Comma-separated instruments to use for replay tuning. Default: BTCUSDT,ETHUSDT.",
    )
    concept_save_stage7_decision.add_argument(
        "--category",
        default="linear",
        help="Bybit category for replay tuning. Default: linear.",
    )
    concept_save_stage7_decision.add_argument(
        "--max-steps",
        type=int,
        default=12,
        help="Maximum replay steps per instrument. Default: 12.",
    )
    concept_save_stage7_decision.add_argument(
        "--step-stride",
        type=int,
        default=3,
        help="Stride between replay steps. Default: 3.",
    )
    concept_save_stage7_decision.add_argument(
        "--tradable-only",
        action="store_true",
        help="Only evaluate replay windows that fall inside the currently allowed trading sessions.",
    )
    concept_save_stage7_decision.add_argument(
        "--policy-path",
        default=str(CONCEPT_DECISION_POLICY_PATH),
        help=f"Concept decision policy JSON path. Default: {CONCEPT_DECISION_POLICY_PATH}",
    )
    concept_save_stage7_decision.add_argument(
        "--artifact-limit",
        type=int,
        default=20,
        help="Maximum saved reviews/revisions to inspect. Default: 20.",
    )
    concept_save_stage7_decision.add_argument(
        "--top-limit",
        type=int,
        default=3,
        help="Maximum top-ranked revisions to include in the brief. Default: 3.",
    )
    concept_save_stage7_decision.add_argument(
        "--response-file",
        required=True,
        help="Path to the structured LLM Stage 7 decision JSON file.",
    )
    concept_save_stage7_decision.add_argument(
        "--source",
        default="llm",
        help="Review source label. Default: llm.",
    )
    concept_save_stage7_decision.add_argument(
        "--author",
        default="",
        help="Review author label, such as gpt-5.4.",
    )

    concept_save_revision_compare = subparsers.add_parser(
        "concept-save-revision-compare",
        help="Validate and persist a structured LLM revision-compare response from a JSON file.",
    )
    add_shared_runtime_args(concept_save_revision_compare)
    concept_save_revision_compare.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    concept_save_revision_compare.add_argument(
        "--event-limit",
        type=int,
        default=25,
        help="Combined event limit. Default: 25.",
    )
    concept_save_revision_compare.add_argument(
        "--proposal-limit",
        type=int,
        default=10,
        help="Recent proposal limit. Default: 10.",
    )
    concept_save_revision_compare.add_argument(
        "--action-limit",
        type=int,
        default=10,
        help="Recent execution action limit. Default: 10.",
    )
    concept_save_revision_compare.add_argument(
        "--scan-limit",
        type=int,
        default=50,
        help="Recent scan-history limit. Default: 50.",
    )
    concept_save_revision_compare.add_argument(
        "--instruments",
        default="BTCUSDT,ETHUSDT",
        help="Comma-separated instruments to use for replay tuning. Default: BTCUSDT,ETHUSDT.",
    )
    concept_save_revision_compare.add_argument(
        "--category",
        default="linear",
        help="Bybit category for replay tuning. Default: linear.",
    )
    concept_save_revision_compare.add_argument(
        "--max-steps",
        type=int,
        default=12,
        help="Maximum replay steps per instrument. Default: 12.",
    )
    concept_save_revision_compare.add_argument(
        "--step-stride",
        type=int,
        default=3,
        help="Stride between replay steps. Default: 3.",
    )
    concept_save_revision_compare.add_argument(
        "--tradable-only",
        action="store_true",
        help="Only evaluate replay windows that fall inside the currently allowed trading sessions.",
    )
    concept_save_revision_compare.add_argument(
        "--policy-path",
        default=str(CONCEPT_DECISION_POLICY_PATH),
        help=f"Concept decision policy JSON path. Default: {CONCEPT_DECISION_POLICY_PATH}",
    )
    concept_save_revision_compare.add_argument(
        "--artifact-limit",
        type=int,
        default=20,
        help="Maximum saved reviews/revisions to inspect. Default: 20.",
    )
    concept_save_revision_compare.add_argument(
        "--top-limit",
        type=int,
        default=3,
        help="Maximum top-ranked revisions to include in the brief. Default: 3.",
    )
    concept_save_revision_compare.add_argument(
        "--response-file",
        required=True,
        help="Path to the structured LLM revision-compare JSON file.",
    )
    concept_save_revision_compare.add_argument(
        "--source",
        default="llm",
        help="Review source label. Default: llm.",
    )
    concept_save_revision_compare.add_argument(
        "--author",
        default="",
        help="Review author label, such as gpt-5.4.",
    )

    concept_promote_review = subparsers.add_parser(
        "concept-promote-review",
        help="Promote a saved concept review into a persisted revision plan.",
    )
    add_shared_runtime_args(concept_promote_review)
    concept_promote_review.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    concept_promote_review.add_argument(
        "--event-limit",
        type=int,
        default=25,
        help="Combined event limit. Default: 25.",
    )
    concept_promote_review.add_argument(
        "--proposal-limit",
        type=int,
        default=10,
        help="Recent proposal limit. Default: 10.",
    )
    concept_promote_review.add_argument(
        "--action-limit",
        type=int,
        default=10,
        help="Recent execution action limit. Default: 10.",
    )
    concept_promote_review.add_argument(
        "--scan-limit",
        type=int,
        default=50,
        help="Recent scan-history limit. Default: 50.",
    )
    concept_promote_review.add_argument(
        "--instruments",
        default="BTCUSDT,ETHUSDT",
        help="Comma-separated instruments to use for replay tuning. Default: BTCUSDT,ETHUSDT.",
    )
    concept_promote_review.add_argument(
        "--category",
        default="linear",
        help="Bybit category for replay tuning. Default: linear.",
    )
    concept_promote_review.add_argument(
        "--max-steps",
        type=int,
        default=12,
        help="Maximum replay steps per instrument. Default: 12.",
    )
    concept_promote_review.add_argument(
        "--step-stride",
        type=int,
        default=3,
        help="Stride between replay steps. Default: 3.",
    )
    concept_promote_review.add_argument(
        "--tradable-only",
        action="store_true",
        help="Only evaluate replay windows that fall inside the currently allowed trading sessions.",
    )
    concept_promote_review.add_argument(
        "--policy-path",
        default=str(CONCEPT_DECISION_POLICY_PATH),
        help=f"Concept decision policy JSON path. Default: {CONCEPT_DECISION_POLICY_PATH}",
    )
    concept_promote_review.add_argument(
        "--review-id",
        required=True,
        help="Saved concept review id to promote, such as CR-00002.",
    )
    concept_promote_review.add_argument(
        "--candidate-id",
        default="",
        help="Optional revision candidate id to use as the baseline plan before review guidance is applied.",
    )
    concept_promote_review.add_argument(
        "--source",
        default="linked_review",
        help="Revision source label. Default: linked_review.",
    )
    concept_promote_review.add_argument(
        "--author",
        default="",
        help="Override the revision author label. Default: reuse the saved review author when present.",
    )

    concept_evaluate_review = subparsers.add_parser(
        "concept-evaluate-review",
        help="Evaluate the latest saved revision linked to a saved concept review.",
    )
    add_shared_runtime_args(concept_evaluate_review)
    concept_evaluate_review.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    concept_evaluate_review.add_argument(
        "--event-limit",
        type=int,
        default=25,
        help="Combined event limit. Default: 25.",
    )
    concept_evaluate_review.add_argument(
        "--proposal-limit",
        type=int,
        default=10,
        help="Recent proposal limit. Default: 10.",
    )
    concept_evaluate_review.add_argument(
        "--action-limit",
        type=int,
        default=10,
        help="Recent execution action limit. Default: 10.",
    )
    concept_evaluate_review.add_argument(
        "--scan-limit",
        type=int,
        default=50,
        help="Recent scan-history limit. Default: 50.",
    )
    concept_evaluate_review.add_argument(
        "--instruments",
        default="BTCUSDT,ETHUSDT",
        help="Comma-separated instruments to use for replay tuning. Default: BTCUSDT,ETHUSDT.",
    )
    concept_evaluate_review.add_argument(
        "--category",
        default="linear",
        help="Bybit category for replay tuning. Default: linear.",
    )
    concept_evaluate_review.add_argument(
        "--max-steps",
        type=int,
        default=12,
        help="Maximum replay steps per instrument. Default: 12.",
    )
    concept_evaluate_review.add_argument(
        "--step-stride",
        type=int,
        default=3,
        help="Stride between replay steps. Default: 3.",
    )
    concept_evaluate_review.add_argument(
        "--tradable-only",
        action="store_true",
        help="Only evaluate replay windows that fall inside the currently allowed trading sessions.",
    )
    concept_evaluate_review.add_argument(
        "--policy-path",
        default=str(CONCEPT_DECISION_POLICY_PATH),
        help=f"Concept decision policy JSON path. Default: {CONCEPT_DECISION_POLICY_PATH}",
    )
    concept_evaluate_review.add_argument(
        "--review-id",
        required=True,
        help="Saved concept review id whose latest linked revision should be evaluated.",
    )

    bybit_doctor = subparsers.add_parser(
        "bybit-doctor",
        help="Inspect Bybit private-environment configuration and optionally probe private REST auth.",
    )
    add_shared_runtime_args(bybit_doctor)
    bybit_doctor.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    bybit_doctor.add_argument(
        "--account-type",
        default="",
        help="Override execution-spec account type for the wallet probe.",
    )
    bybit_doctor.add_argument(
        "--balance-coin",
        default="",
        help="Override execution-spec balance coin for the wallet probe.",
    )
    bybit_doctor.add_argument(
        "--skip-wallet-probe",
        action="store_true",
        help="Do not call the private wallet-balance endpoint; only inspect local configuration.",
    )

    env_debug = subparsers.add_parser(
        "env-debug",
        help="Show safe fingerprints and sources for critical Bybit env values without revealing the secrets.",
    )
    add_shared_runtime_args(env_debug)
    env_debug.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )

    return parser.parse_args()


def add_shared_runtime_args(parser):
    parser.add_argument(
        "--state-dir",
        default=str(DEFAULT_STATE_DIR),
        help=f"Directory for pid/log/manifest state. Default: {DEFAULT_STATE_DIR}",
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"SQLite path passed to the stack. Default: {DEFAULT_DB_PATH}",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"API host for the server process. Default: {DEFAULT_HOST}.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"API port for the server process. Default: {DEFAULT_PORT}.",
    )
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
        help=f"Optional .env file loaded into the launcher and child daemons. Default: {DEFAULT_ENV_FILE}",
    )
    parser.add_argument(
        "--no-env-file",
        action="store_true",
        help="Do not load any .env file; use only the current shell/process environment.",
    )
    parser.add_argument(
        "--env-file-override",
        action="store_true",
        help="Let values from --env-file override already-exported shell variables.",
    )


def ensure_state_dir(state_dir):
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "logs").mkdir(parents=True, exist_ok=True)


def parse_env_line(raw_line):
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[len("export ") :].lstrip()
    if "=" not in line:
        raise ValueError("expected KEY=VALUE format")
    key, value = line.split("=", 1)
    key = key.strip()
    if not key:
        raise ValueError("env key is empty")
    value = value.strip()
    if value and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def normalize_bybit_env(raw_value):
    text = str(raw_value or "").strip().lower()
    aliases = {
        "prod": "mainnet",
        "production": "mainnet",
        "live": "mainnet",
        "demo": "demo",
        "mainnet-demo": "demo",
        "prod-demo": "demo",
        "test": "testnet",
        "testnet": "testnet",
        "mainnet": "mainnet",
    }
    return aliases.get(text, "testnet")


def load_env_file_into_process(env_file_arg, override=False, disabled=False):
    initial_keys = set(os.environ.keys())
    if disabled:
        return {
            "loaded": False,
            "disabled": True,
            "path": None,
            "entries": 0,
            "used_default": False,
            "skipped_existing": 0,
            "override": bool(override),
            "loaded_keys": [],
            "initial_keys": sorted(initial_keys),
        }
    env_file = clean_text(env_file_arg)
    if env_file is None:
        return {
            "loaded": False,
            "disabled": False,
            "path": None,
            "entries": 0,
            "used_default": False,
            "skipped_existing": 0,
            "override": bool(override),
            "loaded_keys": [],
            "initial_keys": sorted(initial_keys),
        }
    path = Path(env_file).expanduser()
    used_default = path == DEFAULT_ENV_FILE
    if not path.exists():
        if used_default:
            return {
                "loaded": False,
                "disabled": False,
                "path": str(path),
                "entries": 0,
                "used_default": True,
                "skipped_existing": 0,
                "override": bool(override),
                "loaded_keys": [],
                "initial_keys": sorted(initial_keys),
            }
        raise SystemExit(f"env file not found: {path}")

    loaded_entries = 0
    skipped_existing = 0
    loaded_keys = []
    try:
        for line_number, raw_line in enumerate(path.read_text().splitlines(), start=1):
            parsed = parse_env_line(raw_line)
            if parsed is None:
                continue
            key, value = parsed
            if not override and key in os.environ:
                skipped_existing += 1
                continue
            os.environ[key] = value
            loaded_entries += 1
            loaded_keys.append(key)
    except OSError as exc:
        raise SystemExit(f"failed to read env file {path}: {exc}") from exc
    except ValueError as exc:
        raise SystemExit(f"invalid env file {path}: line {line_number}: {exc}") from exc

    return {
        "loaded": True,
        "path": str(path),
        "entries": loaded_entries,
        "used_default": used_default,
        "skipped_existing": skipped_existing,
        "override": bool(override),
        "loaded_keys": sorted(loaded_keys),
        "initial_keys": sorted(initial_keys),
    }


def resolve_env_source(key, env_info):
    env_info = env_info if isinstance(env_info, dict) else {}
    initial_keys = set(env_info.get("initial_keys") or [])
    loaded_keys = set(env_info.get("loaded_keys") or [])
    if key in initial_keys:
        return "shell_or_process"
    if key in loaded_keys:
        return "env_file"
    return "unset"


def resolve_first_env_source(names, env_info):
    for name in names:
        source = resolve_env_source(name, env_info)
        if source != "unset":
            return source
    return "unset"


def safe_value_fingerprint(value):
    text = clean_text(value)
    if text is None:
        return {
            "present": False,
            "length": 0,
            "sha256_prefix": None,
        }
    return {
        "present": True,
        "length": len(text),
            "sha256_prefix": hashlib.sha256(text.encode("utf-8")).hexdigest()[:12],
        }


def build_bybit_env_snapshot(env_info=None):
    env_info = env_info if isinstance(env_info, dict) else {}
    bybit_env_raw = clean_text(os.environ.get("BYBIT_ENV")) or "testnet"
    submit_raw = clean_text(os.environ.get("BYBIT_ENABLE_PRIVATE_SUBMIT")) or clean_text(
        os.environ.get("BYBIT_ENABLE_TESTNET_SUBMIT")
    )
    snapshot = {
        "captured_at": utc_now_iso(),
        "BYBIT_ENV": {
            "present": True,
            "raw_value": bybit_env_raw,
            "normalized_value": normalize_bybit_env(bybit_env_raw),
            "source": resolve_env_source("BYBIT_ENV", env_info),
        },
        "BYBIT_API_KEY": safe_value_fingerprint(os.environ.get("BYBIT_API_KEY")),
        "BYBIT_API_SECRET": safe_value_fingerprint(os.environ.get("BYBIT_API_SECRET")),
        "BYBIT_ENABLE_TESTNET_SUBMIT": {
            "present": submit_raw is not None,
            "raw_value": submit_raw,
            "normalized_true": env_bool("BYBIT_ENABLE_PRIVATE_SUBMIT", "BYBIT_ENABLE_TESTNET_SUBMIT"),
            "source": resolve_first_env_source(
                ["BYBIT_ENABLE_PRIVATE_SUBMIT", "BYBIT_ENABLE_TESTNET_SUBMIT"], env_info
            ),
        },
    }
    snapshot["BYBIT_API_KEY"]["source"] = resolve_env_source("BYBIT_API_KEY", env_info)
    snapshot["BYBIT_API_SECRET"]["source"] = resolve_env_source("BYBIT_API_SECRET", env_info)
    return snapshot


def compare_bybit_env_snapshots(current_snapshot, launch_snapshot):
    current_snapshot = current_snapshot if isinstance(current_snapshot, dict) else {}
    launch_snapshot = launch_snapshot if isinstance(launch_snapshot, dict) else {}
    keys = ["BYBIT_ENV", "BYBIT_API_KEY", "BYBIT_API_SECRET", "BYBIT_ENABLE_TESTNET_SUBMIT"]
    changed_keys = []
    comparisons = {}
    for key in keys:
        current_value = current_snapshot.get(key) if isinstance(current_snapshot.get(key), dict) else {}
        launch_value = launch_snapshot.get(key) if isinstance(launch_snapshot.get(key), dict) else {}
        if key == "BYBIT_ENV":
            same = clean_text(current_value.get("normalized_value")) == clean_text(launch_value.get("normalized_value"))
        elif key == "BYBIT_ENABLE_TESTNET_SUBMIT":
            same = (
                bool(current_value.get("present")) == bool(launch_value.get("present"))
                and bool(current_value.get("normalized_true")) == bool(launch_value.get("normalized_true"))
                and clean_text(current_value.get("raw_value")) == clean_text(launch_value.get("raw_value"))
            )
        else:
            same = (
                bool(current_value.get("present")) == bool(launch_value.get("present"))
                and int(current_value.get("length") or 0) == int(launch_value.get("length") or 0)
                and clean_text(current_value.get("sha256_prefix")) == clean_text(launch_value.get("sha256_prefix"))
            )
        comparisons[key] = {
            "same": same,
            "current": current_value,
            "launch": launch_value,
        }
        if not same:
            changed_keys.append(key)
    return {
        "has_snapshot": bool(launch_snapshot),
        "matches": not changed_keys and bool(launch_snapshot),
        "changed_keys": changed_keys,
        "comparisons": comparisons,
    }


def manifest_path(state_dir):
    return state_dir / MANIFEST_NAME


@contextmanager
def manifest_lock(state_dir, exclusive=True):
    lock_path = state_dir / f"{MANIFEST_NAME}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as handle:
        lock_type = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(handle.fileno(), lock_type)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_manifest(state_dir):
    path = manifest_path(state_dir)
    if not path.exists():
        return {
            "version": 1,
            "updated_at": None,
            "state_dir": str(state_dir),
            "services": {},
            "launch_context": {},
        }
    return json.loads(path.read_text())


def save_manifest(state_dir, manifest):
    manifest["updated_at"] = utc_now_iso()
    manifest["state_dir"] = str(state_dir)
    path = manifest_path(state_dir)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    os.replace(tmp_path, path)


def manifest_db_path(manifest):
    launch_context = manifest.get("launch_context") if isinstance(manifest.get("launch_context"), dict) else {}
    return clean_text(launch_context.get("db_path")) or DEFAULT_DB_PATH


def retire_service_runtime_state(db_path, service_name):
    runtime_db_path = Path(str(db_path)).expanduser()
    if not runtime_db_path.exists():
        return False

    store = PaperTradeStore(runtime_db_path)
    service_name = clean_text(service_name)
    if service_name == "private_stream_loop":
        store.delete_private_stream_runtime("stream-main")
        return True
    if service_name == "supervisor_loop":
        store.delete_supervisor_runtime("main")
        return True
    if service_name == "ops_loop":
        store.delete_operations_runtime("main")
        return True
    if service_name == "scan_loop":
        store.delete_operations_runtime("public_market:default")
        return True
    if service_name == "auto_execute_loop":
        store.delete_auto_execution_runtime("main")
        return True
    if service_name == "trade_management_loop":
        store.delete_trade_management_runtime("main")
        return True
    return False


def is_process_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def service_log_path(state_dir, service_name):
    return state_dir / "logs" / f"{service_name}.log"


def env_bool(*names):
    for name in names:
        raw = os.environ.get(name, "").strip().lower()
        if raw:
            return raw in {"1", "true", "yes", "on"}
    return False


def load_json_document(path, label):
    if not path.exists():
        return {
            "ok": False,
            "path": str(path),
            "errors": [f"{label} file not found: {path}"],
            "data": None,
        }
    try:
        data = json.loads(path.read_text())
    except OSError as exc:
        return {
            "ok": False,
            "path": str(path),
            "errors": [f"failed to read {label}: {exc}"],
            "data": None,
        }
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "path": str(path),
            "errors": [f"invalid JSON in {label}: {exc.msg}"],
            "data": None,
        }
    if not isinstance(data, dict):
        return {
            "ok": False,
            "path": str(path),
            "errors": [f"{label} must be a JSON object"],
            "data": None,
        }
    return {
        "ok": True,
        "path": str(path),
        "errors": [],
        "data": data,
    }


def merge_nested_defaults(base, override):
    result = dict(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_nested_defaults(result[key], value)
        else:
            result[key] = value
    return result


def load_concept_decision_policy(path):
    document = load_json_document(Path(path).expanduser(), "concept decision policy")
    defaults = {
        "version": "2026-04-12",
        "concept_id": "concept-1",
        "minimum_evidence": {
            "recent_scan_count": 20,
            "recent_proposal_count": 2,
            "recent_action_count": 2,
            "recent_execution_state_count": 2,
        },
        "quality_thresholds": {
            "minimum_candidate_ratio": 0.05,
            "review_blocker_ratio": 0.6,
            "severe_blocker_ratio": 0.75,
            "severe_cross_market_gap": 0.5,
        },
    }
    if not document.get("ok"):
        document["policy"] = defaults
        return document
    data = document.get("data") if isinstance(document.get("data"), dict) else {}
    document["policy"] = merge_nested_defaults(defaults, data)
    return document


def validate_execution_spec_document(doc):
    errors = []
    data = doc.get("data") if isinstance(doc, dict) else None
    if not isinstance(data, dict):
        return ["execution spec is unavailable"]
    if data.get("venue") != "bybit":
        errors.append("execution spec venue must be bybit")
    if data.get("category") != "linear":
        errors.append("execution spec category must be linear")
    if not isinstance(data.get("risk"), dict):
        errors.append("execution spec risk section is required")
    if not isinstance(data.get("execution"), dict):
        errors.append("execution spec execution section is required")
    if not isinstance(data.get("instruments"), dict) or not data.get("instruments"):
        errors.append("execution spec instruments section is required")
    return errors


def validate_auto_policy_document(doc):
    errors = []
    data = doc.get("data") if isinstance(doc, dict) else None
    if not isinstance(data, dict):
        return ["auto-execution policy is unavailable"]
    if data.get("category") != "linear":
        errors.append("auto-execution policy category must be linear")
    if data.get("entry_model") != "fvg_midpoint":
        errors.append("auto-execution entry_model must be fvg_midpoint")
    if data.get("stop_model") != "sweep_or_fvg_boundary":
        errors.append("auto-execution stop_model must be sweep_or_fvg_boundary")
    if data.get("target_model") != "nearest_opposing_liquidity":
        errors.append("auto-execution target_model must be nearest_opposing_liquidity")
    instruments = data.get("instruments")
    if not isinstance(instruments, list) or not instruments:
        errors.append("auto-execution instruments list is required")
    return errors


def validate_trade_policy_document(doc):
    errors = []
    data = doc.get("data") if isinstance(doc, dict) else None
    if not isinstance(data, dict):
        return ["trade-management policy is unavailable"]
    if not isinstance(data.get("working_orders"), dict):
        errors.append("trade-management working_orders section is required")
    if not isinstance(data.get("open_positions"), dict):
        errors.append("trade-management open_positions section is required")
    return errors


def load_control_rows(db_path):
    path = Path(db_path).expanduser()
    if not path.exists():
        return {}
    try:
        conn = sqlite_connect(path)
    except sqlite3.Error:
        return {}
    try:
        rows = conn.execute(
            """
            SELECT control_key, updated_at, paused, reason
            FROM control_state
            """
        ).fetchall()
        return {
            row["control_key"]: {
                "control_key": row["control_key"],
                "updated_at": row["updated_at"],
                "paused": bool(row["paused"]),
                "reason": row["reason"],
            }
            for row in rows
        }
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def resolve_local_control(control_rows, control_key):
    global_record = control_rows.get("global")
    specific_record = None if control_key == "global" else control_rows.get(control_key)
    paused_records = []
    for record in (global_record, specific_record):
        if isinstance(record, dict) and record.get("paused"):
            paused_records.append(record)
    reasons = [record.get("reason") for record in paused_records if record.get("reason")]
    updated_candidates = [
        record.get("updated_at")
        for record in (specific_record, global_record)
        if isinstance(record, dict) and record.get("updated_at")
    ]
    return {
        "control_key": control_key,
        "effective_paused": bool(paused_records),
        "effective_reason": "; ".join(reasons) if reasons else None,
        "updated_at": max(updated_candidates) if updated_candidates else None,
        "global": global_record,
        "specific": specific_record,
    }


def add_issue(issues, severity, code, summary, details=None):
    issues.append(
        {
            "severity": severity,
            "code": code,
            "summary": summary,
            "details": details if isinstance(details, dict) else {},
        }
    )


def is_service_alive_from_manifest(manifest, service_name):
    record = (manifest.get("services") or {}).get(service_name)
    if not isinstance(record, dict):
        return False
    return is_process_alive(record.get("pid"))


def preflight_stack(args):
    state_dir = Path(args.state_dir).expanduser()
    ensure_state_dir(state_dir)
    with manifest_lock(state_dir, exclusive=False):
        manifest = load_manifest(state_dir)
    issues = []
    env_info = getattr(args, "_env_info", {}) if hasattr(args, "_env_info") else {}

    execution_spec = load_json_document(EXECUTION_SPEC_PATH, "execution spec")
    auto_policy = load_json_document(AUTO_EXECUTION_POLICY_PATH, "auto-execution policy")
    trade_policy = load_json_document(TRADE_MANAGEMENT_POLICY_PATH, "trade-management policy")

    execution_errors = validate_execution_spec_document(execution_spec) if execution_spec["ok"] else execution_spec["errors"]
    auto_policy_errors = validate_auto_policy_document(auto_policy) if auto_policy["ok"] else auto_policy["errors"]
    trade_policy_errors = validate_trade_policy_document(trade_policy) if trade_policy["ok"] else trade_policy["errors"]

    if env_info.get("loaded"):
        add_issue(
            issues,
            "info",
            "env_file_loaded",
            "launcher env file loaded successfully",
            {
                "path": env_info.get("path"),
                "entries": env_info.get("entries"),
                "skipped_existing": env_info.get("skipped_existing"),
                "override": env_info.get("override"),
            },
        )

    if execution_errors:
        add_issue(issues, "error", "execution_spec_invalid", "execution spec is not valid for testnet automation", {"errors": execution_errors, "path": execution_spec["path"]})
    else:
        add_issue(issues, "info", "execution_spec_ok", "execution spec loaded successfully", {"path": execution_spec["path"]})

    if auto_policy_errors:
        add_issue(issues, "error", "auto_policy_invalid", "auto-execution policy is not valid", {"errors": auto_policy_errors, "path": auto_policy["path"]})
    else:
        add_issue(issues, "info", "auto_policy_ok", "auto-execution policy loaded successfully", {"path": auto_policy["path"], "enabled": bool(auto_policy["data"].get("enabled"))})

    if trade_policy_errors:
        add_issue(issues, "error", "trade_policy_invalid", "trade-management policy is not valid", {"errors": trade_policy_errors, "path": trade_policy["path"]})
    else:
        add_issue(issues, "info", "trade_policy_ok", "trade-management policy loaded successfully", {"path": trade_policy["path"], "enabled": bool(trade_policy["data"].get("enabled"))})

    control_rows = load_control_rows(args.db_path)
    global_control = resolve_local_control(control_rows, "global")
    private_control = resolve_local_control(control_rows, "private_stream")
    submission_control = resolve_local_control(control_rows, "order_submission")
    auto_control = resolve_local_control(control_rows, "auto_execution")
    trade_control = resolve_local_control(control_rows, "trade_management")

    if global_control["effective_paused"]:
        add_issue(issues, "error", "global_paused", "global control is paused", {"reason": global_control["effective_reason"]})

    bybit_creds_present = bool(os.environ.get("BYBIT_API_KEY") and os.environ.get("BYBIT_API_SECRET"))
    submit_enabled = env_bool("BYBIT_ENABLE_PRIVATE_SUBMIT", "BYBIT_ENABLE_TESTNET_SUBMIT")

    private_stream_running = is_service_alive_from_manifest(manifest, "private_stream_loop")
    auto_exec_running = is_service_alive_from_manifest(manifest, "auto_execute_loop")
    trade_mgmt_running = is_service_alive_from_manifest(manifest, "trade_management_loop")
    concept_lab_running = is_service_alive_from_manifest(manifest, "concept_lab_loop")

    private_stream_planned = bool(args.with_private_stream or private_stream_running)
    auto_exec_planned = bool(args.with_auto_execution or auto_exec_running)
    trade_mgmt_planned = bool(args.with_trade_management or trade_mgmt_running)
    concept_lab_planned = bool(getattr(args, "with_concept_lab", False) or concept_lab_running)

    add_issue(
        issues,
        "info",
        "service_plan",
        "service plan evaluated",
        {
            "private_stream_planned": private_stream_planned,
            "auto_execution_planned": auto_exec_planned,
            "trade_management_planned": trade_mgmt_planned,
            "concept_lab_planned": concept_lab_planned,
            "private_stream_running": private_stream_running,
            "auto_execution_running": auto_exec_running,
            "trade_management_running": trade_mgmt_running,
            "concept_lab_running": concept_lab_running,
        },
    )

    if private_stream_planned and not bybit_creds_present:
        add_issue(issues, "error", "private_stream_credentials_missing", "private stream requires BYBIT_API_KEY and BYBIT_API_SECRET", {})
    elif private_stream_planned:
        add_issue(issues, "info", "private_stream_credentials_ok", "private stream credentials are present", {})

    if getattr(args, "probe_bybit_auth", False):
        account_type = clean_text(execution_spec.get("data", {}).get("account_type")) or "UNIFIED"
        balance_coin = clean_text(execution_spec.get("data", {}).get("balance_coin")) or "USDT"
        if not bybit_creds_present:
            add_issue(
                issues,
                "error",
                "bybit_auth_probe_blocked",
                "Bybit auth probe requested but credentials are missing",
                {"account_type": account_type, "balance_coin": balance_coin},
            )
        else:
            probe = run_bybit_wallet_probe(account_type, balance_coin)
            diagnosis = interpret_bybit_probe(probe)
            if probe["ok"]:
                add_issue(
                    issues,
                    "info",
                    "bybit_auth_probe_ok",
                    "Bybit private wallet auth probe succeeded for the selected environment",
                    {
                        "account_type": account_type,
                        "balance_coin": balance_coin,
                        "coin_found": probe.get("coin_found"),
                    },
                )
            else:
                add_issue(
                    issues,
                    "error",
                    "bybit_auth_probe_failed",
                    "Bybit private wallet auth probe failed for the selected environment",
                    {
                        "account_type": account_type,
                        "balance_coin": balance_coin,
                        "http_status": probe.get("http_status"),
                        "ret_code": probe.get("ret_code"),
                        "ret_msg": probe.get("ret_msg"),
                        "error": probe.get("error"),
                        "diagnosis": diagnosis,
                    },
                )

    auto_enabled = bool(auto_policy.get("data", {}).get("enabled")) if auto_policy["ok"] else False
    auto_submit = bool(auto_policy.get("data", {}).get("auto_submit")) if auto_policy["ok"] else False
    auto_requires_stream = bool(auto_policy.get("data", {}).get("require_private_stream")) if auto_policy["ok"] else False
    if auto_enabled:
        if not auto_exec_planned:
            add_issue(issues, "warning", "auto_execution_not_planned", "auto-execution policy is enabled but no auto-execution daemon is planned or running", {})
        if auto_control["effective_paused"]:
            add_issue(issues, "error", "auto_execution_paused", "auto-execution control is paused", {"reason": auto_control["effective_reason"]})
        if auto_requires_stream and not private_stream_planned:
            add_issue(issues, "error", "auto_execution_private_stream_missing", "auto-execution requires a private stream daemon but none is planned or running", {})
        if auto_requires_stream and private_control["effective_paused"]:
            add_issue(issues, "error", "private_stream_paused_for_auto_execution", "private stream control is paused while auto execution requires it", {"reason": private_control["effective_reason"]})
        if auto_submit and not submit_enabled:
            add_issue(issues, "error", "submission_disabled", "auto-execution auto_submit is enabled but BYBIT_ENABLE_TESTNET_SUBMIT is not true", {})
        if auto_submit and submission_control["effective_paused"]:
            add_issue(issues, "error", "order_submission_paused", "order submission is paused while auto execution is enabled", {"reason": submission_control["effective_reason"]})
        if auto_submit and not bybit_creds_present:
            add_issue(issues, "error", "auto_execution_credentials_missing", "auto-execution submission requires Bybit API credentials", {})
    elif args.with_auto_execution:
        add_issue(issues, "warning", "auto_execution_idle", "auto-execution daemon is planned but the policy is disabled", {})

    trade_enabled = bool(trade_policy.get("data", {}).get("enabled")) if trade_policy["ok"] else False
    trade_requires_stream = bool(trade_policy.get("data", {}).get("require_private_stream")) if trade_policy["ok"] else False
    if trade_enabled:
        if not trade_mgmt_planned:
            add_issue(issues, "warning", "trade_management_not_planned", "trade-management policy is enabled but no trade-management daemon is planned or running", {})
        if trade_control["effective_paused"]:
            add_issue(issues, "error", "trade_management_paused", "trade-management control is paused", {"reason": trade_control["effective_reason"]})
        if trade_requires_stream and not private_stream_planned:
            add_issue(issues, "error", "trade_management_private_stream_missing", "trade management requires a private stream daemon but none is planned or running", {})
        if trade_requires_stream and private_control["effective_paused"]:
            add_issue(issues, "error", "private_stream_paused_for_trade_management", "private stream control is paused while trade management requires it", {"reason": private_control["effective_reason"]})
        if not bybit_creds_present:
            add_issue(issues, "error", "trade_management_credentials_missing", "trade management requires Bybit API credentials", {})
    elif args.with_trade_management:
        add_issue(issues, "warning", "trade_management_idle", "trade-management daemon is planned but the policy is disabled", {})

    if not submit_enabled:
        add_issue(issues, "warning", "submit_disabled_info", "Bybit private submission is currently disabled", {})
    else:
        add_issue(issues, "info", "submit_enabled_info", "Bybit private submission is enabled", {})

    severity_rank = {"info": 0, "warning": 1, "error": 2}
    counts = {"info": 0, "warning": 0, "error": 0}
    for issue in issues:
        counts[issue["severity"]] = counts.get(issue["severity"], 0) + 1
    overall = "ready" if counts["error"] == 0 else "blocked"
    return {
        "ok": True,
        "action": "preflight",
        "overall": overall,
        "counts": counts,
        "state_dir": str(state_dir),
        "db_path": args.db_path,
        "env_file": env_info,
        "issues": sorted(issues, key=lambda item: severity_rank.get(item["severity"], 99), reverse=True),
    }


def sqlite_connect_readonly(db_path):
    path = Path(db_path).expanduser()
    if not path.exists():
        return None
    try:
        return sqlite_connect(path)
    except sqlite3.Error:
        return None


def sqlite_table_exists(conn, table_name):
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def sqlite_select_rows(conn, query, params=()):
    try:
        rows = conn.execute(query, params).fetchall()
    except sqlite3.Error:
        return []
    return [dict(row) for row in rows]


def store_concept_review_record(db_path, review_payload):
    payload = review_payload if isinstance(review_payload, dict) else {}
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite_connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS concept_reviews (
                review_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_id TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                concept_id TEXT,
                source TEXT NOT NULL,
                author TEXT,
                review_kind TEXT NOT NULL,
                overall TEXT,
                recommendation TEXT,
                primary_blocker TEXT,
                summary TEXT NOT NULL,
                review_json TEXT NOT NULL
            )
            """
        )
        next_id = conn.execute(
            "SELECT COALESCE(MAX(review_entry_id), 0) + 1 AS next_id FROM concept_reviews"
        ).fetchone()["next_id"]
        review_id = f"CR-{int(next_id):05d}"
        now = utc_now_iso()
        conn.execute(
            """
            INSERT INTO concept_reviews (
                review_id,
                created_at,
                concept_id,
                source,
                author,
                review_kind,
                overall,
                recommendation,
                primary_blocker,
                summary,
                review_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_id,
                now,
                clean_text(payload.get("concept_id")) or "concept-1",
                clean_text(payload.get("source")) or "llm",
                clean_text(payload.get("author")),
                clean_text(payload.get("review_kind")) or "llm_structured",
                clean_text(payload.get("overall")),
                clean_text(payload.get("recommendation")),
                clean_text(payload.get("primary_blocker")),
                clean_text(payload.get("summary")) or "concept review artifact",
                json.dumps(payload, sort_keys=True),
            ),
        )
        conn.commit()
        return {
            "review_id": review_id,
            "created_at": now,
        }
    finally:
        conn.close()


def get_concept_review_record(db_path, review_id):
    path = Path(db_path).expanduser()
    if not path.exists():
        return None
    conn = sqlite_connect(path)
    try:
        row = conn.execute(
            """
            SELECT *
            FROM concept_reviews
            WHERE review_id = ?
            """,
            (clean_text(review_id),),
        ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["review"] = parse_json_text(record.pop("review_json"), fallback={}) or {}
        return record
    finally:
        conn.close()


def store_concept_revision_record(db_path, revision_payload):
    payload = revision_payload if isinstance(revision_payload, dict) else {}
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite_connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS concept_revisions (
                revision_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                revision_id TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                concept_id TEXT,
                source TEXT NOT NULL,
                author TEXT,
                focus TEXT,
                status TEXT NOT NULL,
                summary TEXT NOT NULL,
                revision_json TEXT NOT NULL
            )
            """
        )
        next_id = conn.execute(
            "SELECT COALESCE(MAX(revision_entry_id), 0) + 1 AS next_id FROM concept_revisions"
        ).fetchone()["next_id"]
        revision_id = f"RV-{int(next_id):05d}"
        now = utc_now_iso()
        conn.execute(
            """
            INSERT INTO concept_revisions (
                revision_id,
                created_at,
                concept_id,
                source,
                author,
                focus,
                status,
                summary,
                revision_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision_id,
                now,
                clean_text(payload.get("concept_id")) or "concept-1",
                clean_text(payload.get("source")) or "manual",
                clean_text(payload.get("author")),
                clean_text(payload.get("focus")),
                clean_text(payload.get("status")) or "planned",
                clean_text(payload.get("summary")) or "concept revision",
                json.dumps(payload, sort_keys=True),
            ),
        )
        conn.commit()
        return {
            "revision_id": revision_id,
            "created_at": now,
        }
    finally:
        conn.close()


def get_concept_revision_record(db_path, revision_id):
    path = Path(db_path).expanduser()
    if not path.exists():
        return None
    conn = sqlite_connect(path)
    try:
        row = conn.execute(
            """
            SELECT *
            FROM concept_revisions
            WHERE revision_id = ?
            """,
            (clean_text(revision_id),),
        ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["revision"] = parse_json_text(record.pop("revision_json"), fallback={}) or {}
        return record
    finally:
        conn.close()


def list_concept_review_records(db_path, concept_id=None, limit=20):
    path = Path(db_path).expanduser()
    if not path.exists():
        return []
    conn = sqlite_connect(path)
    try:
        query = [
            "SELECT * FROM concept_reviews",
        ]
        params = []
        concept = clean_text(concept_id)
        if concept:
            query.append("WHERE concept_id = ?")
            params.append(concept)
        query.append("ORDER BY review_entry_id DESC LIMIT ?")
        params.append(max(1, int(limit or 20)))
        rows = conn.execute("\n".join(query), tuple(params)).fetchall()
        items = []
        for row in rows:
            record = dict(row)
            record["review"] = parse_json_text(record.pop("review_json"), fallback={}) or {}
            items.append(record)
        return items
    finally:
        conn.close()


def list_concept_revision_records(db_path, concept_id=None, limit=20):
    path = Path(db_path).expanduser()
    if not path.exists():
        return []
    conn = sqlite_connect(path)
    try:
        query = [
            "SELECT * FROM concept_revisions",
        ]
        params = []
        concept = clean_text(concept_id)
        if concept:
            query.append("WHERE concept_id = ?")
            params.append(concept)
        query.append("ORDER BY revision_entry_id DESC LIMIT ?")
        params.append(max(1, int(limit or 20)))
        rows = conn.execute("\n".join(query), tuple(params)).fetchall()
        items = []
        for row in rows:
            record = dict(row)
            record["revision"] = parse_json_text(record.pop("revision_json"), fallback={}) or {}
            items.append(record)
        return items
    finally:
        conn.close()


def get_concept_runtime_record(db_path, runtime_key="main"):
    path = Path(db_path).expanduser()
    if not path.exists():
        return None
    conn = sqlite_connect(path)
    try:
        row = conn.execute(
            """
            SELECT *
            FROM concept_runtime
            WHERE runtime_key = ?
            """,
            (clean_text(runtime_key) or "main",),
        ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["last_summary"] = parse_json_text(record.pop("last_summary_json"), fallback={}) or {}
        record["state"] = parse_json_text(record.pop("state_json"), fallback={}) or {}
        return record
    finally:
        conn.close()


def get_latest_concept_revision_for_review(db_path, review_id):
    path = Path(db_path).expanduser()
    if not path.exists():
        return None
    target_review_id = clean_text(review_id)
    if not target_review_id:
        return None
    conn = sqlite_connect(path)
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM concept_revisions
            ORDER BY revision_entry_id DESC
            """
        ).fetchall()
        for row in rows:
            record = dict(row)
            revision = parse_json_text(record.get("revision_json"), fallback={}) or {}
            if clean_text(revision.get("review_id")) != target_review_id:
                continue
            record["revision"] = revision
            record.pop("revision_json", None)
            return record
        return None
    finally:
        conn.close()


def update_concept_revision_record(db_path, revision_id, revision_payload):
    path = Path(db_path).expanduser()
    if not path.exists():
        return False
    payload = revision_payload if isinstance(revision_payload, dict) else {}
    conn = sqlite_connect(path)
    try:
        cursor = conn.execute(
            """
            UPDATE concept_revisions
            SET focus = ?, status = ?, summary = ?, revision_json = ?
            WHERE revision_id = ?
            """,
            (
                clean_text(payload.get("focus")),
                clean_text(payload.get("status")) or "planned",
                clean_text(payload.get("summary")) or "concept revision",
                json.dumps(payload, sort_keys=True),
                clean_text(revision_id),
            ),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def parse_json_text(value, fallback=None):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def latest_runtime_rows(conn, table_name):
    if not sqlite_table_exists(conn, table_name):
        return []
    rows = sqlite_select_rows(
        conn,
        f"""
        SELECT *
        FROM {table_name}
        ORDER BY updated_at DESC, runtime_key ASC
        """,
    )
    items = []
    for row in rows:
        item = dict(row)
        if "last_summary_json" in item:
            item["last_summary"] = parse_json_text(item.pop("last_summary_json"), {})
        if "state_json" in item:
            item["state"] = parse_json_text(item.pop("state_json"), {})
        if "subscriptions_json" in item:
            item["subscriptions"] = parse_json_text(item.pop("subscriptions_json"), [])
        items.append(item)
    return items


def load_control_state_rows(conn):
    if not sqlite_table_exists(conn, "control_state"):
        return []
    rows = sqlite_select_rows(
        conn,
        """
        SELECT control_key, updated_at, paused, reason, updated_by
        FROM control_state
        ORDER BY control_key ASC
        """,
    )
    for row in rows:
        row["paused"] = bool(row.get("paused"))
    return rows


def load_recent_order_proposals(conn, limit):
    if not sqlite_table_exists(conn, "order_proposals"):
        return []
    return sqlite_select_rows(
        conn,
        """
        SELECT proposal_id, created_at, venue, status, symbol, side, order_type, qty,
               price, stop_loss, take_profit, paper_trade_journal_id
        FROM order_proposals
        ORDER BY proposal_entry_id DESC
        LIMIT ?
        """,
        (limit,),
    )


def load_recent_execution_actions(conn, limit):
    if not sqlite_table_exists(conn, "execution_actions"):
        return []
    return sqlite_select_rows(
        conn,
        """
        SELECT action_id, created_at, proposal_id, venue, action_type, status, symbol
        FROM execution_actions
        ORDER BY action_entry_id DESC
        LIMIT ?
        """,
        (limit,),
    )


def load_recent_execution_state(conn, limit):
    if not sqlite_table_exists(conn, "execution_state"):
        return []
    return sqlite_select_rows(
        conn,
        """
        SELECT proposal_id, updated_at, venue, symbol, sync_status, order_status,
               position_side, position_size, position_avg_price, unrealised_pnl
        FROM execution_state
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (limit,),
    )


def load_recent_scan_history(conn, limit):
    if not sqlite_table_exists(conn, "scan_history"):
        return []
    return sqlite_select_rows(
        conn,
        """
        SELECT scan_id, created_at, source, instrument, category, decision, session,
               direction, candidate_logged, duplicate_candidate, journal_id
        FROM scan_history
        ORDER BY scan_entry_id DESC
        LIMIT ?
        """,
        (limit,),
    )


def load_recent_combined_events(conn, limit):
    event_specs = [
        (
            "operations_events",
            """
            SELECT created_at, severity, event_type, summary,
                   runtime_key AS owner_key, component_key AS subject_key,
                   'operations' AS source
            FROM operations_events
            ORDER BY event_entry_id DESC
            LIMIT ?
            """,
        ),
        (
            "auto_execution_events",
            """
            SELECT created_at, severity, event_type, summary,
                   runtime_key AS owner_key, proposal_id AS subject_key,
                   'auto_execution' AS source
            FROM auto_execution_events
            ORDER BY event_entry_id DESC
            LIMIT ?
            """,
        ),
        (
            "trade_management_events",
            """
            SELECT created_at, severity, event_type, summary,
                   runtime_key AS owner_key, proposal_id AS subject_key,
                   'trade_management' AS source
            FROM trade_management_events
            ORDER BY event_entry_id DESC
            LIMIT ?
            """,
        ),
        (
            "private_stream_events",
            """
            SELECT created_at, severity, event_type, summary,
                   runtime_key AS owner_key, proposal_id AS subject_key,
                   'private_stream' AS source
            FROM private_stream_events
            ORDER BY event_entry_id DESC
            LIMIT ?
            """,
        ),
        (
            "supervisor_events",
            """
            SELECT created_at, severity, event_type, summary,
                   runtime_key AS owner_key, proposal_id AS subject_key,
                   'supervisor' AS source
            FROM supervisor_events
            ORDER BY event_entry_id DESC
            LIMIT ?
            """,
        ),
    ]
    items = []
    for table_name, query in event_specs:
        if not sqlite_table_exists(conn, table_name):
            continue
        items.extend(sqlite_select_rows(conn, query, (limit,)))
    items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return items[:limit]


def load_recent_concept_events(conn, limit):
    if not sqlite_table_exists(conn, "concept_events"):
        return []
    return sqlite_select_rows(
        conn,
        """
        SELECT created_at, runtime_key, concept_id, severity, event_type, summary
        FROM concept_events
        ORDER BY event_entry_id DESC
        LIMIT ?
        """,
        (limit,),
    )


def load_recent_auto_execution_events(conn, limit):
    if not sqlite_table_exists(conn, "auto_execution_events"):
        return []
    return sqlite_select_rows(
        conn,
        """
        SELECT created_at, runtime_key, instrument, proposal_id, severity, event_type, summary
        FROM auto_execution_events
        ORDER BY event_entry_id DESC
        LIMIT ?
        """,
        (limit,),
    )


def build_runtime_summary_rows(runtimes, kind):
    items = []
    for row in runtimes:
        summary = row.get("last_summary") if isinstance(row.get("last_summary"), dict) else {}
        state = row.get("state") if isinstance(row.get("state"), dict) else {}
        item = {
            "kind": kind,
            "runtime_key": row.get("runtime_key"),
            "updated_at": row.get("updated_at"),
            "heartbeat_at": row.get("heartbeat_at"),
            "last_scan_at": row.get("last_scan_at"),
            "last_error": state.get("last_error"),
            "last_summary": summary,
            "state": state,
        }
        if kind == "private_stream":
            item["connection_status"] = row.get("connection_status")
            item["connected_at"] = row.get("connected_at")
            item["last_message_at"] = row.get("last_message_at")
            item["subscriptions"] = row.get("subscriptions") if isinstance(row.get("subscriptions"), list) else []
        items.append(item)
    return items


def build_service_launch_env_map(manifest_status):
    items = manifest_status.get("items") if isinstance(manifest_status, dict) else []
    mapping = {}
    for item in items if isinstance(items, list) else []:
        service_name = item.get("service_name")
        if not service_name:
            continue
        launch_snapshot = item.get("launch_env") if isinstance(item.get("launch_env"), dict) else {}
        mapping[service_name] = {
            "service_name": service_name,
            "alive": bool(item.get("alive")),
            "pid": item.get("pid"),
            "started_at": item.get("started_at"),
            "launch_env": launch_snapshot,
        }
    return mapping


def burnin_report(args):
    state_dir = Path(args.state_dir).expanduser()
    ensure_state_dir(state_dir)
    manifest_status = stack_status(args)
    current_env = build_bybit_env_snapshot(getattr(args, "_env_info", {}))
    service_env = build_service_launch_env_map(manifest_status)
    env_comparisons = {}
    for service_name, item in service_env.items():
        env_comparisons[service_name] = compare_bybit_env_snapshots(
            current_env,
            item.get("launch_env"),
        )
    conn = sqlite_connect_readonly(args.db_path)

    report = {
        "ok": True,
        "action": "burnin-report",
        "state_dir": str(state_dir),
        "db_path": args.db_path,
        "manifest": manifest_status,
        "env": {
            "current": current_env,
            "service_launch": service_env,
            "comparisons": env_comparisons,
        },
        "controls": [],
        "runtimes": {
            "supervisor": [],
            "private_stream": [],
            "operations": [],
            "auto_execution": [],
            "trade_management": [],
            "concept_lab": [],
        },
        "recent_events": [],
        "recent_proposals": [],
        "recent_execution_actions": [],
        "recent_execution_state": [],
        "recent_scan_history": [],
        "recent_concept_events": [],
        "recent_auto_execution_events": [],
        "overall": "unknown",
    }
    if conn is None:
        report["ok"] = False
        report["overall"] = "missing_db"
        return report

    try:
        report["controls"] = load_control_state_rows(conn)
        report["runtimes"]["supervisor"] = build_runtime_summary_rows(
            latest_runtime_rows(conn, "supervisor_runtime"),
            "supervisor",
        )
        report["runtimes"]["private_stream"] = build_runtime_summary_rows(
            latest_runtime_rows(conn, "private_stream_runtime"),
            "private_stream",
        )
        report["runtimes"]["operations"] = build_runtime_summary_rows(
            latest_runtime_rows(conn, "operations_runtime"),
            "operations",
        )
        report["runtimes"]["auto_execution"] = build_runtime_summary_rows(
            latest_runtime_rows(conn, "auto_execution_runtime"),
            "auto_execution",
        )
        report["runtimes"]["trade_management"] = build_runtime_summary_rows(
            latest_runtime_rows(conn, "trade_management_runtime"),
            "trade_management",
        )
        report["runtimes"]["concept_lab"] = build_runtime_summary_rows(
            latest_runtime_rows(conn, "concept_runtime"),
            "concept_lab",
        )
        report["recent_events"] = load_recent_combined_events(conn, max(1, args.event_limit))
        report["recent_proposals"] = load_recent_order_proposals(conn, max(1, args.proposal_limit))
        report["recent_execution_actions"] = load_recent_execution_actions(conn, max(1, args.action_limit))
        report["recent_execution_state"] = load_recent_execution_state(conn, max(1, args.proposal_limit))
        report["recent_scan_history"] = load_recent_scan_history(
            conn,
            max(1, int(getattr(args, "scan_limit", getattr(args, "proposal_limit", 10)))),
        )
        report["recent_concept_events"] = load_recent_concept_events(conn, max(1, args.event_limit))
        report["recent_auto_execution_events"] = load_recent_auto_execution_events(
            conn,
            max(1, args.event_limit),
        )
    finally:
        conn.close()

    alive_count = manifest_status.get("alive_count", 0)
    launch_context = manifest_status.get("launch_context") if isinstance(manifest_status.get("launch_context"), dict) else {}
    launch_started_at = clean_text(launch_context.get("started_at"))
    launch_age_seconds = iso_age_seconds(launch_started_at)
    report["startup"] = {
        "launch_started_at": launch_started_at,
        "launch_age_seconds": launch_age_seconds,
        "grace_window_seconds": STARTUP_GRACE_SECONDS,
        "grace_active": bool(
            alive_count > 0
            and launch_age_seconds is not None
            and launch_age_seconds < STARTUP_GRACE_SECONDS
        ),
    }
    error_events = [
        item for item in report["recent_events"] if item.get("severity") == "error"
    ]
    warning_events = [
        item for item in report["recent_events"] if item.get("severity") == "warning"
    ]
    if alive_count == 0:
        report["overall"] = "idle"
    elif error_events:
        report["overall"] = "attention"
    elif warning_events:
        report["overall"] = "watch"
    else:
        report["overall"] = "healthy"
    return report


def latest_runtime_item(items):
    if not items:
        return None
    return sorted(items, key=lambda item: item.get("updated_at") or "", reverse=True)[0]


def latest_runtime_item_by_key(items, runtime_key):
    if not items:
        return None
    target = clean_text(runtime_key)
    if not target:
        return latest_runtime_item(items)
    matching = [
        item for item in items
        if clean_text(item.get("runtime_key")) == target
    ]
    if matching:
        return latest_runtime_item(matching)
    return latest_runtime_item(items)


def private_stream_status_is_healthy(connection_status):
    status = clean_text(connection_status)
    return status in {"connected", "streaming"}


def _planned_services_from_manifest(manifest):
    launch_context = manifest.get("launch_context") if isinstance(manifest.get("launch_context"), dict) else {}
    planned_services = launch_context.get("planned_services") if isinstance(launch_context.get("planned_services"), list) else []
    return {
        clean_text(item)
        for item in planned_services
        if clean_text(item)
    }


def _burnin_service_expectations(manifest, auto_policy, trade_policy):
    planned_services = _planned_services_from_manifest(manifest)
    auto_enabled = bool(auto_policy.get("data", {}).get("enabled")) if auto_policy.get("ok") else False
    trade_enabled = bool(trade_policy.get("data", {}).get("enabled")) if trade_policy.get("ok") else False
    auto_requires_stream = bool(auto_policy.get("data", {}).get("require_private_stream")) if auto_policy.get("ok") else False
    trade_requires_stream = bool(trade_policy.get("data", {}).get("require_private_stream")) if trade_policy.get("ok") else False
    private_stream_expected = (
        "private_stream_loop" in planned_services
        or (auto_enabled and auto_requires_stream)
        or (trade_enabled and trade_requires_stream)
    )
    auto_execution_expected = "auto_execute_loop" in planned_services or auto_enabled
    trade_management_expected = "trade_management_loop" in planned_services or trade_enabled
    return {
        "planned_services": planned_services,
        "private_stream_expected": private_stream_expected,
        "auto_execution_expected": auto_execution_expected,
        "trade_management_expected": trade_management_expected,
    }


def _event_targets_optional_component(event, expectations):
    subject_key = clean_text(event.get("subject_key"))
    source = clean_text(event.get("source"))
    if (
        subject_key
        and (subject_key == "private_stream" or subject_key.startswith("private_stream:"))
        and not expectations.get("private_stream_expected")
    ):
        return True
    if subject_key and subject_key.startswith("auto_execution:") and not expectations.get("auto_execution_expected"):
        return True
    if subject_key and subject_key.startswith("trade_management:") and not expectations.get("trade_management_expected"):
        return True
    if source == "private_stream" and not expectations.get("private_stream_expected"):
        return True
    if source == "auto_execution" and not expectations.get("auto_execution_expected"):
        return True
    if source == "trade_management" and not expectations.get("trade_management_expected"):
        return True
    return False


def _component_targets_optional_component(component_key, expectations):
    component = clean_text(component_key)
    if (
        component
        and (component == "private_stream" or component.startswith("private_stream:"))
        and not expectations.get("private_stream_expected")
    ):
        return True
    if component == "auto_execution" and not expectations.get("auto_execution_expected"):
        return True
    if component == "trade_management" and not expectations.get("trade_management_expected"):
        return True
    return False


def _latest_operations_component(latest_operations, prefix):
    state = latest_operations.get("state") if isinstance(latest_operations, dict) else {}
    component_state = state.get("component_state") if isinstance(state, dict) else {}
    for component_key, item in component_state.items() if isinstance(component_state, dict) else []:
        if clean_text(component_key).startswith(prefix) and isinstance(item, dict):
            return item
    return None


def burnin_gate(args):
    report = burnin_report(args)
    issues = []
    severity_rank = {"info": 0, "warning": 1, "error": 2}

    def add_gate_issue(severity, code, summary, details=None):
        issues.append(
            {
                "severity": severity,
                "code": code,
                "summary": summary,
                "details": details if isinstance(details, dict) else {},
            }
        )

    if not report.get("ok"):
        add_gate_issue("error", "db_unavailable", "burn-in database is unavailable", {"db_path": report.get("db_path")})
    manifest = report.get("manifest") or {}
    auto_policy = load_json_document(AUTO_EXECUTION_POLICY_PATH, "auto-execution policy")
    trade_policy = load_json_document(TRADE_MANAGEMENT_POLICY_PATH, "trade-management policy")
    service_expectations = _burnin_service_expectations(manifest, auto_policy, trade_policy)
    alive_count = manifest.get("alive_count", 0)
    drift_count = int(manifest.get("drift_count") or 0)
    manifest_items = manifest.get("items") if isinstance(manifest.get("items"), list) else []
    service_alive = {
        clean_text(item.get("service_name")): bool(item.get("alive"))
        for item in manifest_items
        if clean_text(item.get("service_name"))
    }
    if alive_count == 0:
        add_gate_issue("warning", "stack_idle", "no stack daemons are currently alive", {"service_count": manifest.get("service_count", 0)})
    else:
        add_gate_issue("info", "stack_running", "stack daemons are running", {"alive_count": alive_count})
    drifted_services = [
        clean_text(item.get("service_name"))
        for item in manifest_items
        if item.get("drift_detected") and clean_text(item.get("service_name"))
    ]
    if drift_count > 0 and drifted_services:
        add_gate_issue(
            "warning",
            "service_pid_drift_detected",
            "one or more managed services have duplicate or drifted processes",
            {"service_names": drifted_services, "drift_count": drift_count},
        )
    else:
        add_gate_issue("info", "service_pid_drift_clear", "no managed service drift was detected", {})

    paused_controls = [item for item in (report.get("controls") or []) if item.get("paused")]
    if paused_controls:
        add_gate_issue(
            "error",
            "controls_paused",
            "one or more controls are paused",
            {"control_keys": [item.get("control_key") for item in paused_controls]},
        )
    else:
        add_gate_issue("info", "controls_clear", "no paused controls are recorded", {})

    if service_expectations.get("private_stream_expected") and not service_alive.get("private_stream_loop"):
        add_gate_issue(
            "error",
            "private_stream_daemon_stopped",
            "private stream daemon is not running",
            {},
        )
    if service_expectations.get("auto_execution_expected") and not service_alive.get("auto_execute_loop"):
        add_gate_issue(
            "error",
            "auto_execution_daemon_stopped",
            "auto-execution daemon is not running",
            {},
        )
    if service_expectations.get("trade_management_expected") and not service_alive.get("trade_management_loop"):
        add_gate_issue(
            "error",
            "trade_management_daemon_stopped",
            "trade-management daemon is not running",
            {},
        )

    env_payload = report.get("env") if isinstance(report.get("env"), dict) else {}
    startup_payload = report.get("startup") if isinstance(report.get("startup"), dict) else {}
    startup_grace_active = bool(startup_payload.get("grace_active"))
    startup_launch_at = clean_text(startup_payload.get("launch_started_at"))
    env_comparisons = env_payload.get("comparisons") if isinstance(env_payload.get("comparisons"), dict) else {}
    service_launch = env_payload.get("service_launch") if isinstance(env_payload.get("service_launch"), dict) else {}
    private_stream_env = env_comparisons.get("private_stream_loop") if isinstance(env_comparisons.get("private_stream_loop"), dict) else {}
    private_stream_service = service_launch.get("private_stream_loop") if isinstance(service_launch.get("private_stream_loop"), dict) else {}
    latest_operations_hint = latest_runtime_item_by_key((report.get("runtimes") or {}).get("operations") or [], "main")
    latest_operations_private_stream_hint = _latest_operations_component(latest_operations_hint, "private_stream:")
    if private_stream_env:
        if not private_stream_env.get("has_snapshot"):
            add_gate_issue(
                "warning",
                "private_stream_launch_env_missing",
                "private stream launch env snapshot is missing, so stale-credential detection is unavailable for this process",
                {},
            )
        elif not private_stream_env.get("matches"):
            add_gate_issue(
                "error",
                "private_stream_restart_required",
                "the running private stream was started with different Bybit env values than the current shell, so a restart is required",
                {"changed_keys": private_stream_env.get("changed_keys") or []},
            )
        else:
            add_gate_issue(
                "info",
                "private_stream_launch_env_current",
                "the running private stream matches the current shell Bybit env values",
                {},
            )

    latest_private_stream = latest_runtime_item((report.get("runtimes") or {}).get("private_stream") or [])
    private_stream_healthy = False
    private_stream_effectively_healthy = False
    if latest_private_stream is None:
        if not service_expectations.get("private_stream_expected"):
            private_stream_effectively_healthy = True
        if startup_grace_active:
            add_gate_issue(
                "warning",
                "private_stream_starting",
                "private stream is still within the startup grace window and has not written a fresh runtime row yet",
                startup_payload,
            )
        else:
            add_gate_issue("warning", "private_stream_runtime_missing", "private stream runtime is missing from SQLite", {})
    else:
        connection_status = latest_private_stream.get("connection_status")
        last_error = latest_private_stream.get("last_error") if isinstance(latest_private_stream.get("last_error"), dict) else {}
        last_error_message = clean_text(last_error.get("message"))
        private_stream_started_at = clean_text(private_stream_service.get("started_at"))
        private_stream_updated_at = latest_private_stream.get("updated_at")
        private_stream_stale_after_restart = bool(
            private_stream_started_at
            and private_stream_updated_at
            and iso_is_older(private_stream_updated_at, private_stream_started_at)
        )
        private_stream_warming_up = bool(
            startup_grace_active
            and not last_error_message
            and (
                private_stream_stale_after_restart
                or clean_text(connection_status) in {None, "connecting", "authenticating", "subscribing"}
            )
        )
        component_hint = (
            latest_operations_private_stream_hint
            if isinstance(latest_operations_private_stream_hint, dict)
            else {}
        )
        component_health = clean_text(component_hint.get("health"))
        component_status = clean_text(component_hint.get("status"))
        component_summary = clean_text(component_hint.get("summary"))
        component_is_optional = _component_targets_optional_component(
            component_hint.get("component_key"),
            service_expectations,
        )
        if component_health == "healthy":
            private_stream_healthy = True
            private_stream_effectively_healthy = True
            add_gate_issue(
                "info",
                "private_stream_healthy",
                component_summary or f"private stream is {connection_status}",
                {
                    "connection_status": connection_status,
                    "component_status": component_status,
                },
            )
        elif component_health == "warning":
            private_stream_effectively_healthy = bool(component_is_optional)
            issue_code = "private_stream_optional_component_unhealthy" if component_is_optional else "private_stream_unhealthy"
            issue_severity = "warning"
            if private_stream_warming_up:
                issue_code = "private_stream_starting"
            add_gate_issue(
                issue_severity,
                issue_code,
                component_summary or "private stream is not fully healthy",
                {
                    "connection_status": connection_status,
                    "component_status": component_status,
                    "updated_at": latest_private_stream.get("updated_at"),
                    "started_at": private_stream_started_at,
                    "startup": startup_payload if private_stream_warming_up else None,
                },
            )
        elif component_health == "error":
            private_stream_effectively_healthy = bool(component_is_optional)
            issue_code = "private_stream_optional_component_unhealthy" if component_is_optional else "private_stream_unhealthy"
            issue_severity = "warning" if component_is_optional else "error"
            issue_summary = component_summary or "private stream is not in a healthy state"
            if last_error_message and "api key is invalid" in last_error_message.lower():
                issue_code = "private_stream_auth_invalid"
                issue_severity = "error"
                issue_summary = "private stream auth is failing because the active Bybit API key is invalid"
            add_gate_issue(
                issue_severity,
                issue_code,
                issue_summary,
                {
                    "connection_status": connection_status,
                    "component_status": component_status,
                    "updated_at": latest_private_stream.get("updated_at"),
                    "last_error_message": last_error_message,
                },
            )
        elif not private_stream_status_is_healthy(connection_status):
            if private_stream_warming_up:
                add_gate_issue(
                    "warning",
                    "private_stream_starting",
                    "private stream is still within the startup grace window and has not reached a healthy state yet",
                    {
                        "connection_status": connection_status,
                        "updated_at": latest_private_stream.get("updated_at"),
                        "started_at": private_stream_started_at,
                        "startup": startup_payload,
                    },
                )
            else:
                issue_code = "private_stream_unhealthy"
                issue_summary = "private stream is not in a connected state"
                if last_error_message and "api key is invalid" in last_error_message.lower():
                    issue_code = "private_stream_auth_invalid"
                    issue_summary = "private stream auth is failing because the active Bybit API key is invalid"
                add_gate_issue(
                    "error",
                    issue_code,
                    issue_summary,
                    {
                        "connection_status": connection_status,
                        "updated_at": latest_private_stream.get("updated_at"),
                        "last_error_message": last_error_message,
                    },
                )
        else:
            private_stream_healthy = True
            private_stream_effectively_healthy = True
            add_gate_issue(
                "info",
                "private_stream_healthy",
                f"private stream is {connection_status}",
                {"connection_status": connection_status},
            )

    recent_events = report.get("recent_events") or []
    actionable_recent_events = [
        item for item in recent_events
        if not _event_targets_optional_component(item, service_expectations)
    ]
    ignored_optional_events = [
        item for item in recent_events
        if _event_targets_optional_component(item, service_expectations)
    ]
    actionable_error_events = [item for item in actionable_recent_events if item.get("severity") == "error"]
    actionable_warning_events = [item for item in actionable_recent_events if item.get("severity") == "warning"]
    ignored_optional_error_events = [item for item in ignored_optional_events if item.get("severity") == "error"]

    latest_operations = latest_runtime_item_by_key((report.get("runtimes") or {}).get("operations") or [], "main")
    latest_operations_private_stream = _latest_operations_component(latest_operations, "private_stream:")
    operations_health = None
    optional_error_components = []
    actionable_error_components = []
    optional_warning_components = []
    actionable_warning_components = []
    public_market_component = {}
    if latest_operations is None:
        if startup_grace_active:
            add_gate_issue(
                "warning",
                "operations_starting",
                "operations watchdog is still within the startup grace window and has not written a fresh runtime row yet",
                startup_payload,
            )
        else:
            add_gate_issue("warning", "operations_runtime_missing", "operations runtime is missing from SQLite", {})
    else:
        operations_health = (((latest_operations.get("last_summary") or {}).get("overall")) or {}).get("health")
        operations_state = latest_operations.get("state") if isinstance(latest_operations.get("state"), dict) else {}
        component_state = (
            operations_state.get("component_state")
            if isinstance(operations_state.get("component_state"), dict)
            else {}
        )
        public_market_component = (
            component_state.get("public_market_event_path")
            if isinstance(component_state.get("public_market_event_path"), dict)
            else {}
        )
        for component_key, item in component_state.items() if isinstance(component_state, dict) else []:
            component_health = clean_text(item.get("health"))
            if component_health not in {"error", "warning"}:
                continue
            component_payload = {
                "component_key": component_key,
                "status": item.get("status"),
                "summary": item.get("summary"),
            }
            is_optional_component = _component_targets_optional_component(component_key, service_expectations)
            if component_health == "error" and is_optional_component:
                optional_error_components.append(component_payload)
            elif component_health == "error":
                actionable_error_components.append(component_payload)
            elif is_optional_component:
                optional_warning_components.append(component_payload)
            else:
                actionable_warning_components.append(component_payload)
        operations_updated_at = latest_operations.get("updated_at")
        operations_stale_after_restart = bool(
            startup_launch_at
            and operations_updated_at
            and iso_is_older(operations_updated_at, startup_launch_at)
        )
        if operations_health == "error":
            if startup_grace_active and operations_stale_after_restart:
                add_gate_issue(
                    "warning",
                    "operations_starting",
                    "operations watchdog is still within the startup grace window and has not published a fresh healthy status yet",
                    {"updated_at": latest_operations.get("updated_at"), "startup": startup_payload},
                )
            elif not actionable_error_components and optional_error_components:
                add_gate_issue(
                    "warning",
                    "operations_health_optional_component_error",
                    "operations watchdog last reported error health, but only optional disabled components are currently failing",
                    {
                        "updated_at": latest_operations.get("updated_at"),
                        "optional_error_components": optional_error_components,
                        "ignored_error_count": len(ignored_optional_error_events),
                        "latest_ignored_error": ignored_optional_error_events[0] if ignored_optional_error_events else None,
                    },
                )
            elif not actionable_error_events and ignored_optional_error_events:
                add_gate_issue(
                    "warning",
                    "operations_health_optional_component_error",
                    "operations watchdog last reported error health, but only optional disabled components are currently failing",
                    {
                        "updated_at": latest_operations.get("updated_at"),
                        "ignored_error_count": len(ignored_optional_error_events),
                        "latest_ignored_error": ignored_optional_error_events[0],
                    },
                )
            else:
                add_gate_issue(
                    "error",
                    "operations_health_error",
                    "operations watchdog last reported error health",
                    {"updated_at": latest_operations.get("updated_at")},
                )
        elif operations_health == "warning":
            if startup_grace_active and operations_stale_after_restart:
                add_gate_issue(
                    "warning",
                    "operations_starting",
                    "operations watchdog is still within the startup grace window and has not published a fresh post-start status yet",
                    {"updated_at": latest_operations.get("updated_at"), "startup": startup_payload},
                )
            elif not actionable_warning_components and optional_warning_components:
                add_gate_issue(
                    "warning",
                    "operations_health_optional_component_warning",
                    "operations watchdog last reported warning health, but only optional disabled components are currently warning",
                    {
                        "updated_at": latest_operations.get("updated_at"),
                        "optional_warning_components": optional_warning_components,
                    },
                )
            else:
                add_gate_issue(
                    "warning",
                    "operations_health_warning",
                    "operations watchdog last reported warning health",
                    {"updated_at": latest_operations.get("updated_at")},
                )
        else:
            add_gate_issue("info", "operations_health_ok", "operations watchdog last reported healthy status", {})

    latest_auto_execution = latest_runtime_item((report.get("runtimes") or {}).get("auto_execution") or [])
    if latest_auto_execution is None:
        add_gate_issue("warning", "auto_execution_runtime_missing", "auto-execution runtime is missing from SQLite", {})
    else:
        policy_enabled = bool((latest_auto_execution.get("last_summary") or {}).get("policy_enabled"))
        if not policy_enabled:
            add_gate_issue("warning", "auto_execution_policy_disabled", "auto-execution runtime reports policy disabled", {})
        else:
            add_gate_issue("info", "auto_execution_policy_enabled", "auto-execution runtime reports policy enabled", {})

    latest_trade_management = latest_runtime_item((report.get("runtimes") or {}).get("trade_management") or [])
    if latest_trade_management is None:
        add_gate_issue("warning", "trade_management_runtime_missing", "trade-management runtime is missing from SQLite", {})
    else:
        policy_enabled = bool((latest_trade_management.get("last_summary") or {}).get("policy_enabled"))
        if not policy_enabled:
            add_gate_issue("warning", "trade_management_policy_disabled", "trade-management runtime reports policy disabled", {})
        else:
            add_gate_issue("info", "trade_management_policy_enabled", "trade-management runtime reports policy enabled", {})

    concept_lab_service = next(
        (
            item for item in (manifest.get("items") or [])
            if item.get("service_name") == "concept_lab_loop"
        ),
        None,
    )
    latest_concept_lab = latest_runtime_item((report.get("runtimes") or {}).get("concept_lab") or [])
    if concept_lab_service and concept_lab_service.get("alive"):
        concept_lab_started_at = clean_text(concept_lab_service.get("started_at"))
        if latest_concept_lab is None:
            if startup_grace_active:
                add_gate_issue(
                    "warning",
                    "concept_lab_starting",
                    "concept lab is still within the startup grace window and has not written a fresh runtime row yet",
                    startup_payload,
                )
            else:
                add_gate_issue(
                    "warning",
                    "concept_lab_runtime_missing",
                    "concept lab is running but no concept runtime row is available yet",
                    {},
                )
        else:
            concept_lab_updated_at = latest_concept_lab.get("updated_at")
            concept_lab_stale_after_restart = bool(
                concept_lab_started_at
                and concept_lab_updated_at
                and iso_is_older(concept_lab_updated_at, concept_lab_started_at)
            )
            concept_lab_last_error = (
                latest_concept_lab.get("last_error")
                if isinstance(latest_concept_lab.get("last_error"), dict)
                else {}
            )
            concept_lab_last_error_message = clean_text(concept_lab_last_error.get("message"))
            if startup_grace_active and concept_lab_stale_after_restart:
                add_gate_issue(
                    "warning",
                    "concept_lab_starting",
                    "concept lab is still within the startup grace window and has not published a fresh post-start runtime yet",
                    {"updated_at": concept_lab_updated_at, "startup": startup_payload},
                )
            elif concept_lab_last_error_message:
                add_gate_issue(
                    "warning",
                    "concept_lab_runtime_error",
                    "concept lab recorded a recent cycle error",
                    {
                        "updated_at": concept_lab_updated_at,
                        "message": concept_lab_last_error_message,
                    },
                )
            else:
                add_gate_issue(
                    "info",
                    "concept_lab_runtime_ok",
                    "concept lab is publishing runtime state without recent cycle errors",
                    {"updated_at": concept_lab_updated_at},
                )

    recent_events = report.get("recent_events") or []
    error_events = actionable_error_events
    warning_events = actionable_warning_events
    latest_error_at = error_events[0].get("created_at") if error_events else None
    private_stream_updated_at = latest_private_stream.get("updated_at") if isinstance(latest_private_stream, dict) else None
    operations_updated_at = latest_operations.get("updated_at") if isinstance(latest_operations, dict) else None
    operations_effectively_healthy = operations_health not in {"error", "warning"} or (
        operations_health == "error"
        and not actionable_error_components
        and (bool(optional_error_components) or bool(ignored_optional_error_events))
    ) or (
        operations_health == "warning"
        and not actionable_warning_components
        and bool(optional_warning_components)
    )
    recovered_after_runtime_updates = bool(
        latest_error_at
        and (private_stream_healthy or private_stream_effectively_healthy)
        and operations_effectively_healthy
        and (
            (private_stream_updated_at and private_stream_updated_at > latest_error_at)
            or (operations_updated_at and operations_updated_at > latest_error_at)
        )
    )
    public_market_warning_recovered = bool(
        error_events
        and not actionable_error_components
        and all(clean_text(item.get("subject_key")) == "public_market_event_path" for item in error_events)
        and operations_updated_at
        and latest_error_at
        and operations_updated_at > latest_error_at
        and clean_text(public_market_component.get("health")) in {"healthy", "warning"}
        and clean_text(public_market_component.get("status")) in {"healthy_primary", "degraded_fallback"}
    )
    recovered_after_errors = recovered_after_runtime_updates or public_market_warning_recovered
    latest_error_in_current_startup_window = bool(
        latest_error_at
        and startup_launch_at
        and iso_within_seconds_after(
            latest_error_at,
            startup_launch_at,
            startup_payload.get("grace_window_seconds") or STARTUP_GRACE_SECONDS,
        )
    )
    recovered_from_startup_error = bool(
        latest_error_in_current_startup_window
        and operations_updated_at
        and operations_updated_at > latest_error_at
        and operations_health != "error"
    )
    latest_error_before_current_launch = bool(
        startup_launch_at
        and latest_error_at
        and iso_is_older(latest_error_at, startup_launch_at)
    )
    current_launch_observed_after_error = bool(
        latest_error_before_current_launch
        and (
            startup_grace_active
            or (
                operations_updated_at
                and not iso_is_older(operations_updated_at, startup_launch_at)
            )
            or (
                private_stream_updated_at
                and not iso_is_older(private_stream_updated_at, startup_launch_at)
            )
        )
    )
    if error_events:
        if recovered_from_startup_error:
            add_gate_issue(
                "warning",
                "recent_error_events_startup_recovered",
                "recent error events were recorded during startup warmup, but a newer operations runtime has moved past them",
                {"count": len(error_events), "latest": error_events[0], "startup": startup_payload},
            )
        elif public_market_warning_recovered and current_launch_observed_after_error:
            add_gate_issue(
                "warning",
                "recent_error_events_prestart",
                "recent error events were recorded before the current launch and are not blocking the current burn-in window",
                {"count": len(error_events), "latest": error_events[0], "startup": startup_payload},
            )
        elif recovered_after_errors:
            add_gate_issue(
                "warning",
                "recent_error_events_recovered",
                "recent error events were recorded, but the latest private-stream and operations runtimes have recovered since then",
                {"count": len(error_events), "latest": error_events[0]},
            )
        elif current_launch_observed_after_error:
            add_gate_issue(
                "warning",
                "recent_error_events_prestart",
                "recent error events were recorded before the current launch and are not blocking the current burn-in window",
                {"count": len(error_events), "latest": error_events[0], "startup": startup_payload},
            )
        else:
            add_gate_issue(
                "error",
                "recent_error_events",
                "recent error events were recorded during burn-in",
                {"count": len(error_events), "latest": error_events[0]},
            )
    elif ignored_optional_error_events:
        add_gate_issue(
            "info",
            "recent_optional_component_errors_ignored",
            "recent error events only affect optional disabled components and are not blocking this baseline",
            {"count": len(ignored_optional_error_events), "latest": ignored_optional_error_events[0]},
        )
    elif warning_events:
        add_gate_issue(
            "warning",
            "recent_warning_events",
            "recent warning events were recorded during burn-in",
            {"count": len(warning_events), "latest": warning_events[0]},
        )
    else:
        add_gate_issue("info", "recent_events_clean", "no recent warning or error events were recorded", {})

    recent_scans = report.get("recent_scan_history") or []
    if recent_scans:
        add_gate_issue("info", "scan_history_present", "recent scan history is available", {"count": len(recent_scans)})
    else:
        add_gate_issue("error", "scan_history_missing", "no recent scan history is available", {})

    counts = {"info": 0, "warning": 0, "error": 0}
    for issue in issues:
        counts[issue["severity"]] = counts.get(issue["severity"], 0) + 1

    if counts["error"] > 0:
        overall = "blocked"
    elif counts["warning"] > 0:
        overall = "watch"
    elif alive_count == 0:
        overall = "idle"
    else:
        overall = "ready"

    return {
        "ok": counts["error"] == 0,
        "action": "burnin-gate",
        "overall": overall,
        "counts": counts,
        "state_dir": report.get("state_dir"),
        "db_path": report.get("db_path"),
        "issues": sorted(issues, key=lambda item: severity_rank.get(item["severity"], 99), reverse=True),
        "report": report,
    }


def parse_instruments_csv(raw_value):
    values = [item.strip().upper() for item in str(raw_value or "").split(",") if item.strip()]
    return values or ["BTCUSDT", "ETHUSDT"]


def average_replay_ratio(payload, blocker):
    summaries = payload.get("summaries") or []
    if not summaries:
        return 0.0
    total = 0.0
    for item in summaries:
        total += replay_blocker_ratio(item, blocker)
    return round(total / float(len(summaries)), 4)


def ratio(count, total):
    if not total:
        return 0.0
    return round(float(count) / float(total), 4)


def count_verified_candidate_decisions(mapping):
    mapping = mapping if isinstance(mapping, dict) else {}
    return int(mapping.get("verified_paper_trade") or 0)


def count_legacy_candidate_decisions(mapping):
    mapping = mapping if isinstance(mapping, dict) else {}
    return int(mapping.get("paper_trade") or 0)


def count_candidate_decisions(mapping, *, include_legacy=False):
    total = count_verified_candidate_decisions(mapping)
    if include_legacy:
        total += count_legacy_candidate_decisions(mapping)
    return total


def replay_metric_count(item, *, include_legacy=False):
    if not isinstance(item, dict):
        return 0
    total = int(item.get("verified_trade_count") or 0)
    if include_legacy:
        total += int(item.get("legacy_compat_trade_count") or 0)
    return total


def summarize_candidate_scan_metrics(items):
    scans = list(items) if isinstance(items, list) else []
    verified_candidate_scans = [
        item for item in scans
        if clean_text(item.get("decision")) == "verified_paper_trade"
    ]
    legacy_candidate_scans = [
        item for item in scans
        if clean_text(item.get("decision")) == "paper_trade"
    ]
    logged_verified_candidates = [
        item for item in verified_candidate_scans
        if bool(item.get("candidate_logged"))
    ]
    duplicate_verified_candidates = [
        item for item in verified_candidate_scans
        if bool(item.get("duplicate_candidate"))
    ]
    return {
        "verified_candidate_scans": verified_candidate_scans,
        "legacy_candidate_scans": legacy_candidate_scans,
        "verified_candidate_count": len(verified_candidate_scans),
        "legacy_candidate_count": len(legacy_candidate_scans),
        "logged_verified_candidates": logged_verified_candidates,
        "duplicate_verified_candidates": duplicate_verified_candidates,
    }


def replay_blocker_ratio(item, blocker):
    ratios = item.get("blocker_ratios") if isinstance(item, dict) else {}
    if not isinstance(ratios, dict):
        return 0.0
    if blocker == "liquidity_event":
        return max(
            float(ratios.get("liquidity_event") or 0.0),
            float(ratios.get("liquidity_sweep") or 0.0),
        )
    return float(ratios.get(blocker) or 0.0)


def render_concept_blocker_label(blocker):
    text = clean_text(blocker)
    return CONCEPT_BLOCKER_LABELS.get(text, text)


def build_concept_operator_signal(
    overall,
    recommendation,
    *,
    unmet_evidence=None,
    dominant_blocker=None,
    cross_market_gap=None,
    candidate_ratio=None,
):
    unmet_evidence = unmet_evidence if isinstance(unmet_evidence, list) else []
    dominant_blocker = dominant_blocker if isinstance(dominant_blocker, dict) else {}
    cross_market_gap = cross_market_gap if isinstance(cross_market_gap, dict) else {}
    blocker_name = clean_text(dominant_blocker.get("blocker"))
    blocker_label = render_concept_blocker_label(blocker_name)
    blocker_ratio = float(dominant_blocker.get("ratio") or 0.0)
    gap_blocker = clean_text(cross_market_gap.get("blocker"))
    gap_blocker_label = render_concept_blocker_label(gap_blocker)
    gap_ratio = float(cross_market_gap.get("gap") or 0.0)
    candidate_ratio_value = float(candidate_ratio or 0.0)

    if overall == "blocked":
        return {
            "signal": "fix_harness",
            "summary": "Fix the live harness before using Concept 1 evidence for decisions.",
        }
    if overall == "collecting":
        metric_names = [clean_text(item.get("metric")) for item in unmet_evidence if clean_text(item.get("metric"))]
        rendered = ", ".join(metric_names[:3]) if metric_names else "minimum evidence"
        return {
            "signal": "collect_more_evidence",
            "summary": f"Keep collecting evidence until the remaining thresholds are met: {rendered}.",
        }
    if overall == "revise":
        if gap_blocker and gap_ratio > 0.0:
            if blocker_name and blocker_name != gap_blocker:
                return {
                    "signal": "revise_concept",
                    "summary": (
                        f"Revise Concept 1 now. {gap_blocker_label} is diverging across BTC/ETH by about {gap_ratio:.0%}; "
                        f"{blocker_label} is also filtering about {blocker_ratio:.0%}."
                    ),
                }
            return {
                "signal": "revise_concept",
                "summary": f"Revise Concept 1 now. {gap_blocker_label} is diverging across BTC/ETH by about {gap_ratio:.0%}.",
            }
        if blocker_name:
            return {
                "signal": "revise_concept",
                "summary": f"Revise Concept 1 now. {blocker_label} is still over-filtering the sample at about {blocker_ratio:.0%}.",
            }
        return {
            "signal": "revise_concept",
            "summary": "Revise Concept 1 now before collecting more passive demo evidence.",
        }
    if overall == "compare":
        return {
            "signal": "compare_next_concept",
            "summary": "Concept 1 has crossed the minimum thresholds and is ready to be compared against the next concept.",
        }
    if overall == "testing":
        if blocker_name:
            return {
                "signal": "continue_testing",
                "summary": f"Keep testing Concept 1. The main pressure point is still {blocker_label} at about {blocker_ratio:.0%}.",
            }
        if candidate_ratio_value <= 0.0:
            return {
                "signal": "continue_testing",
                "summary": "Keep testing Concept 1. The harness is usable, but the current replay sample still has zero passing candidates.",
            }
        return {
            "signal": "continue_testing",
            "summary": "Keep testing Concept 1 and gather more cycles before making a revision or comparison decision.",
        }
    return {
        "signal": clean_text(recommendation) or "observe",
        "summary": "Continue observing the current concept state.",
    }


def summarize_concept_replay_pressure(review, scan_count, policy_path):
    replay = (review.get("replay_tuning") if isinstance(review, dict) else {}) or {}
    policy_doc = load_concept_decision_policy(policy_path)
    policy = policy_doc.get("policy") if isinstance(policy_doc.get("policy"), dict) else {}
    minimum_evidence = policy.get("minimum_evidence") if isinstance(policy.get("minimum_evidence"), dict) else {}
    quality_thresholds = policy.get("quality_thresholds") if isinstance(policy.get("quality_thresholds"), dict) else {}
    minimum_candidate_ratio = float(quality_thresholds.get("minimum_candidate_ratio") or 0.0)
    severe_blocker_ratio = float(quality_thresholds.get("severe_blocker_ratio") or 1.0)
    severe_cross_market_gap = float(quality_thresholds.get("severe_cross_market_gap") or 1.0)
    required_scan_count = int(minimum_evidence.get("recent_scan_count") or 0)

    replay_summaries = replay.get("summaries") or []
    total_steps = sum(int(item.get("evaluated_steps") or 0) for item in replay_summaries)
    total_verified_trades = sum(replay_metric_count(item) for item in replay_summaries)
    candidate_ratio = ratio(total_verified_trades, total_steps)
    blocker_ratios = {
        blocker: average_replay_ratio(replay, blocker)
        for blocker in CONCEPT_REPLAY_BLOCKERS
    }
    dominant_blocker = max(blocker_ratios.items(), key=lambda item: item[1]) if blocker_ratios else (None, 0.0)
    gap_report = ((replay.get("gap_report") or {}).get("blocker_gaps")) or []
    largest_gap = gap_report[0] if gap_report else None
    scan_evidence_met = int(scan_count or 0) >= required_scan_count
    severe_filtering = bool(dominant_blocker[0] and dominant_blocker[1] >= severe_blocker_ratio)
    severe_market_gap = bool(largest_gap and float(largest_gap.get("gap") or 0.0) >= severe_cross_market_gap)
    revise_ready = bool(
        scan_evidence_met
        and total_steps
        and candidate_ratio < minimum_candidate_ratio
        and (severe_filtering or severe_market_gap)
    )
    operator_signal = {}
    if revise_ready:
        operator_signal = build_concept_operator_signal(
            "revise",
            "revise_concept",
            dominant_blocker={
                "blocker": dominant_blocker[0],
                "ratio": dominant_blocker[1],
            },
            cross_market_gap=largest_gap if severe_market_gap else None,
            candidate_ratio=candidate_ratio,
        )

    return {
        "revise_ready": revise_ready,
        "operator_signal": operator_signal.get("signal"),
        "operator_summary": operator_signal.get("summary"),
        "candidate_ratio": candidate_ratio,
        "total_steps": total_steps,
        "verified_trade_count": total_verified_trades,
        "required_scan_count": required_scan_count,
        "scan_count": int(scan_count or 0),
        "dominant_blocker": {
            "blocker": dominant_blocker[0],
            "ratio": dominant_blocker[1],
        },
        "largest_gap": largest_gap,
        "blocker_ratios": blocker_ratios,
    }


def wave4_review(args):
    from replay_tune import build_tuning_payload

    include_legacy_metrics = include_legacy_compat_metrics(args)
    burnin = burnin_gate(args)
    replay = build_tuning_payload(
        instruments=parse_instruments_csv(getattr(args, "instruments", "")),
        category=getattr(args, "category", "linear"),
        max_steps=getattr(args, "max_steps", 100),
        step_stride=getattr(args, "step_stride", 1),
        tradable_only=bool(getattr(args, "tradable_only", False)),
    )

    severity_rank = {"info": 0, "warning": 1, "error": 2}
    issues = []

    def add_issue(severity, code, summary, details=None):
        issues.append(
            {
                "severity": severity,
                "code": code,
                "summary": summary,
                "details": details if isinstance(details, dict) else {},
            }
        )

    burnin_overall = burnin.get("overall")
    burnin_issues = burnin.get("issues") or []
    preferred_burnin_codes = [
        "controls_paused",
        "stack_idle",
        "private_stream_daemon_stopped",
        "auto_execution_daemon_stopped",
        "trade_management_daemon_stopped",
        "private_stream_restart_required",
        "private_stream_auth_invalid",
        "private_stream_unhealthy",
        "operations_health_error",
        "operations_health_warning",
        "recent_error_events",
    ]
    primary_burnin_issue = None
    for code in preferred_burnin_codes:
        primary_burnin_issue = next((item for item in burnin_issues if item.get("code") == code), None)
        if primary_burnin_issue is not None:
            break
    if primary_burnin_issue is None:
        primary_burnin_issue = next(
            (item for item in burnin_issues if item.get("severity") == "error"),
            burnin_issues[0] if burnin_issues else None,
        )
    if burnin_overall == "blocked":
        add_issue("error", "burnin_blocked", "burn-in gate is still blocked, so Wave 4 cannot complete yet.", {})
        if primary_burnin_issue and primary_burnin_issue.get("code") != "burnin_blocked":
            add_issue(
                primary_burnin_issue.get("severity") or "error",
                f"burnin_detail_{primary_burnin_issue.get('code')}",
                primary_burnin_issue.get("summary") or "burn-in issue details are available",
                primary_burnin_issue.get("details") if isinstance(primary_burnin_issue.get("details"), dict) else {},
            )
    elif burnin_overall == "watch":
        add_issue("warning", "burnin_watch", "burn-in gate is still in watch mode and needs cleanup before promotion.", {})
    elif burnin_overall == "idle":
        add_issue("warning", "burnin_idle", "burn-in stack is idle, so Wave 4 evidence is incomplete.", {})
    else:
        add_issue("info", "burnin_ready", "burn-in gate is in a ready state.", {})

    if not replay.get("ok"):
        add_issue(
            "error",
            "replay_failed",
            "Replay tuning did not complete successfully for all requested instruments.",
            {"failures": replay.get("failures") or []},
        )
    elif int(replay.get("compared_count") or 0) == 0:
        add_issue("error", "replay_empty", "Replay tuning returned no usable instrument summaries.", {})
    else:
        add_issue(
            "info",
            "replay_ready",
            "Replay tuning completed successfully for the requested instruments.",
            {"compared_count": replay.get("compared_count")},
        )

    summaries = replay.get("summaries") or []
    total_steps = sum(int(item.get("evaluated_steps") or 0) for item in summaries)
    total_verified_trades = sum(replay_metric_count(item) for item in summaries)
    if total_steps and total_verified_trades == 0:
        add_issue(
            "warning",
            "replay_overfiltered",
            "Replay tuning found zero scanner-verified candidates in the sampled window.",
            {"evaluated_steps": total_steps},
        )
    elif total_steps:
        add_issue(
            "info",
            "replay_candidate_flow_present",
            "Replay tuning found at least one candidate in the sampled window.",
            {"verified_trade_count": total_verified_trades, "evaluated_steps": total_steps},
        )

    average_mss = average_replay_ratio(replay, "mss")
    if average_mss >= 0.8:
        add_issue(
            "warning",
            "mss_strict",
            "MSS is still the dominant blocker across the sampled markets.",
            {"average_ratio": average_mss},
        )

    average_liquidity_event = average_replay_ratio(replay, "liquidity_event")
    if average_liquidity_event >= 0.6:
        add_issue(
            "warning",
            "liquidity_event_strict",
            "The higher-timeframe liquidity-event gate is still filtering a large share of replay steps.",
            {"average_ratio": average_liquidity_event},
        )

    average_direction = average_replay_ratio(replay, "direction")
    if average_direction >= 0.6:
        add_issue(
            "warning",
            "direction_alignment_strict",
            "Directional alignment is failing across a large share of replay steps.",
            {"average_ratio": average_direction},
        )

    blocker_gaps = ((replay.get("gap_report") or {}).get("blocker_gaps")) or []
    if blocker_gaps:
        largest_gap = blocker_gaps[0]
        if float(largest_gap.get("gap") or 0.0) >= 0.5:
            add_issue(
                "warning",
                "cross_market_imbalance",
                "At least one blocker is behaving very differently across BTC and ETH.",
                {"largest_gap": largest_gap},
            )
        else:
            add_issue(
                "info",
                "cross_market_balance_ok",
                "No major cross-market blocker imbalance was detected in the sampled replay window.",
                {"largest_gap": largest_gap},
            )

    counts = {"info": 0, "warning": 0, "error": 0}
    for item in issues:
        counts[item["severity"]] = counts.get(item["severity"], 0) + 1

    if counts["error"] > 0:
        overall = "blocked"
    elif burnin_overall == "idle":
        overall = "idle"
    elif counts["warning"] > 0:
        overall = "watch"
    else:
        overall = "ready"

    next_focus = []
    if overall != "ready":
        next_focus.extend((replay.get("tuning_hints") or [])[:3])
        if burnin_overall in {"blocked", "watch", "idle"}:
            next_focus.append("Run the full guarded stack and clear the remaining burn-in gate issues before promotion.")

    return {
        "ok": overall == "ready",
        "action": "wave4-review",
        "overall": overall,
        "counts": counts,
        "state_dir": burnin.get("state_dir"),
        "db_path": burnin.get("db_path"),
        "burnin_gate": burnin,
        "legacy_compat_metrics_included": include_legacy_metrics,
        "replay_tuning": replay if include_legacy_metrics else strip_legacy_compat_metrics(replay),
        "issues": sorted(issues, key=lambda item: severity_rank.get(item["severity"], 99), reverse=True),
        "next_focus": next_focus,
    }


def promotion_review(args):
    review = wave4_review(args)
    burnin_report_payload = ((review.get("burnin_gate") or {}).get("report")) or {}
    recent_scans = burnin_report_payload.get("recent_scan_history") or []
    recent_proposals = burnin_report_payload.get("recent_proposals") or []
    recent_actions = burnin_report_payload.get("recent_execution_actions") or []
    recent_execution_state = burnin_report_payload.get("recent_execution_state") or []

    severity_rank = {"info": 0, "warning": 1, "error": 2}
    issues = []

    def add_issue(severity, code, summary, details=None):
        issues.append(
            {
                "severity": severity,
                "code": code,
                "summary": summary,
                "details": details if isinstance(details, dict) else {},
            }
        )

    if review.get("overall") == "blocked":
        add_issue("error", "wave4_blocked", "Wave 4 review is still blocked, so promotion cannot proceed.", {})
    elif review.get("overall") == "watch":
        add_issue("warning", "wave4_watch", "Wave 4 review is still in watch mode, so promotion should wait.", {})
    elif review.get("overall") == "idle":
        add_issue("warning", "wave4_idle", "Wave 4 review is idle, so promotion evidence is incomplete.", {})
    else:
        add_issue("info", "wave4_ready", "Wave 4 review is in a ready state.", {})

    if not recent_scans:
        add_issue("error", "promotion_scan_evidence_missing", "No recent scan history is available for promotion review.", {})
    else:
        add_issue("info", "promotion_scan_evidence_present", "Recent scan history is available for promotion review.", {"count": len(recent_scans)})

    if not recent_proposals:
        add_issue("warning", "promotion_proposals_missing", "No recent proposals are available, so testnet execution evidence is still thin.", {})
    else:
        add_issue("info", "promotion_proposals_present", "Recent proposals are available for promotion review.", {"count": len(recent_proposals)})

    if not recent_execution_state:
        add_issue("warning", "promotion_execution_state_missing", "No recent execution-state rows are available, so position lifecycle evidence is still thin.", {})
    else:
        add_issue("info", "promotion_execution_state_present", "Recent execution-state rows are available for promotion review.", {"count": len(recent_execution_state)})

    if not recent_actions:
        add_issue("warning", "promotion_action_history_thin", "No recent execution actions are available, so operator/testnet management evidence is still thin.", {})
    else:
        add_issue("info", "promotion_action_history_present", "Recent execution actions are available for promotion review.", {"count": len(recent_actions)})

    counts = {"info": 0, "warning": 0, "error": 0}
    for item in issues:
        counts[item["severity"]] = counts.get(item["severity"], 0) + 1

    if counts["error"] > 0:
        overall = "blocked"
        recommendation = "stay_in_wave4"
    elif counts["warning"] > 0:
        overall = "watch"
        recommendation = "continue_burnin"
    else:
        overall = "ready"
        recommendation = "ready_for_promotion"

    next_focus = []
    if overall != "ready":
        next_focus.extend((review.get("next_focus") or [])[:3])
        if not recent_proposals:
            next_focus.append("Run more guarded testnet submissions so promotion review includes real proposal evidence.")
        if not recent_execution_state:
            next_focus.append("Keep the stack running long enough to collect execution-state evidence from working orders or positions.")

    return {
        "ok": overall == "ready",
        "action": "promotion-review",
        "overall": overall,
        "recommendation": recommendation,
        "counts": counts,
        "state_dir": review.get("state_dir"),
        "db_path": review.get("db_path"),
        "wave4_review": review,
        "evidence": {
            "recent_scan_count": len(recent_scans),
            "recent_proposal_count": len(recent_proposals),
            "recent_action_count": len(recent_actions),
            "recent_execution_state_count": len(recent_execution_state),
        },
        "issues": sorted(issues, key=lambda item: severity_rank.get(item["severity"], 99), reverse=True),
        "next_focus": next_focus,
    }


def count_value_occurrences(items, key, empty_label):
    counts = {}
    for item in items:
        value = clean_text(item.get(key)) if isinstance(item, dict) else None
        label = value or empty_label
        counts[label] = counts.get(label, 0) + 1
    return counts


AUTO_EXECUTION_CONVERSION_BLOCKER_LABELS = {
    "blocked_active_symbol": "per-symbol active proposal limit",
    "blocked_max_active_total": "total active proposal limit",
    "blocked_private_stream": "private-stream readiness",
    "duplicate_active": "duplicate active proposal suppression",
    "levels_unavailable": "execution payload level derivation",
    "plan_review_required": "execution-plan readiness",
    "submission_failed": "proposal submission",
}


def summarize_auto_execution_conversion_blockers(events):
    blocker_events = []
    for item in events if isinstance(events, list) else []:
        event_type = clean_text(item.get("event_type"))
        if event_type in AUTO_EXECUTION_CONVERSION_BLOCKER_LABELS:
            blocker_events.append(item)

    blocker_mix = count_value_occurrences(blocker_events, "event_type", "unknown")
    top_blocker = None
    if blocker_mix:
        top_event_type, top_count = max(blocker_mix.items(), key=lambda item: item[1])
        top_blocker = {
            "event_type": top_event_type,
            "count": top_count,
            "label": AUTO_EXECUTION_CONVERSION_BLOCKER_LABELS.get(top_event_type, top_event_type),
        }
    return blocker_events, blocker_mix, top_blocker


def latest_service_started_at(manifest, service_names):
    items = manifest.get("items") if isinstance(manifest, dict) else []
    latest = None
    for item in items if isinstance(items, list) else []:
        service_name = clean_text(item.get("service_name"))
        if service_name not in service_names:
            continue
        started_at = clean_text(item.get("started_at"))
        parsed = parse_iso_datetime(started_at)
        if parsed is None:
            continue
        if latest is None or parsed > latest[0]:
            latest = (parsed, started_at)
    return latest[1] if latest else None


def filter_rows_since(items, since_at):
    if not since_at:
        return list(items) if isinstance(items, list) else []
    filtered = []
    for item in items if isinstance(items, list) else []:
        created_at = clean_text(item.get("created_at"))
        if created_at and not iso_is_older(created_at, since_at):
            filtered.append(item)
    return filtered


def concept_review(args):
    include_legacy_metrics = include_legacy_compat_metrics(args)
    review = wave4_review(args)
    burnin = review.get("burnin_gate") or {}
    burnin_report_payload = (burnin.get("report") or {}) if isinstance(burnin.get("report"), dict) else {}
    burnin_issues = burnin.get("issues") or []
    manifest = burnin_report_payload.get("manifest") or {}
    concept_runtimes = ((burnin_report_payload.get("runtimes") or {}).get("concept_lab")) or []
    latest_concept_runtime = latest_runtime_item(concept_runtimes)
    concept_lab_summary = (
        latest_concept_runtime.get("last_summary")
        if isinstance(latest_concept_runtime, dict) and isinstance(latest_concept_runtime.get("last_summary"), dict)
        else {}
    )
    concept_lab_state = (
        latest_concept_runtime.get("state")
        if isinstance(latest_concept_runtime, dict) and isinstance(latest_concept_runtime.get("state"), dict)
        else {}
    )
    recent_concept_events = burnin_report_payload.get("recent_concept_events") or []
    recent_scans = burnin_report_payload.get("recent_scan_history") or []
    recent_proposals = burnin_report_payload.get("recent_proposals") or []
    recent_actions = burnin_report_payload.get("recent_execution_actions") or []
    recent_execution_state = burnin_report_payload.get("recent_execution_state") or []
    recent_auto_execution_events = burnin_report_payload.get("recent_auto_execution_events") or []
    current_sample_started_at = latest_service_started_at(
        manifest,
        {"server", "scan_loop", "auto_execute_loop"},
    )
    current_sample_scans = filter_rows_since(recent_scans, current_sample_started_at)
    current_sample_auto_execution_events = filter_rows_since(
        recent_auto_execution_events,
        current_sample_started_at,
    )
    sample_scans = current_sample_scans if current_sample_scans else list(recent_scans)
    sample_auto_execution_events = (
        current_sample_auto_execution_events
        if current_sample_auto_execution_events
        else list(recent_auto_execution_events)
    )

    candidate_scan_metrics = summarize_candidate_scan_metrics(sample_scans)
    verified_candidate_scans = candidate_scan_metrics["verified_candidate_scans"]
    legacy_candidate_scans = candidate_scan_metrics["legacy_candidate_scans"]
    logged_candidates = candidate_scan_metrics["logged_verified_candidates"]
    duplicate_candidates = candidate_scan_metrics["duplicate_verified_candidates"]
    (
        recent_conversion_events,
        conversion_blocker_mix,
        top_conversion_blocker,
    ) = summarize_auto_execution_conversion_blockers(sample_auto_execution_events)

    severity_rank = {"info": 0, "warning": 1, "error": 2}
    issues = []

    def add_issue(severity, code, summary, details=None):
        issues.append(
            {
                "severity": severity,
                "code": code,
                "summary": summary,
                "details": details if isinstance(details, dict) else {},
            }
        )

    burnin_overall = burnin.get("overall")
    preferred_burnin_codes = [
        "controls_paused",
        "stack_idle",
        "private_stream_restart_required",
        "private_stream_auth_invalid",
        "private_stream_unhealthy",
        "operations_health_error",
        "operations_health_warning",
        "recent_error_events",
    ]
    primary_burnin_issue = None
    for code in preferred_burnin_codes:
        primary_burnin_issue = next((item for item in burnin_issues if item.get("code") == code), None)
        if primary_burnin_issue is not None:
            break
    if primary_burnin_issue is None:
        primary_burnin_issue = next(
            (item for item in burnin_issues if item.get("severity") == "error"),
            burnin_issues[0] if burnin_issues else None,
        )
    if burnin_overall == "blocked":
        add_issue("error", "concept_harness_blocked", "The live demo harness is blocked, so concept testing cannot be trusted.", {})
        if primary_burnin_issue and primary_burnin_issue.get("code") != "concept_harness_blocked":
            add_issue(
                primary_burnin_issue.get("severity") or "error",
                f"concept_harness_detail_{primary_burnin_issue.get('code')}",
                primary_burnin_issue.get("summary") or "The live demo harness has a more specific blocking issue.",
                primary_burnin_issue.get("details") if isinstance(primary_burnin_issue.get("details"), dict) else {},
            )
    elif burnin_overall == "idle":
        add_issue("warning", "concept_harness_idle", "The live demo harness is idle, so concept evidence is not advancing.", {})
    elif burnin_overall == "watch":
        add_issue("warning", "concept_harness_watch", "The live demo harness is in watch mode, so concept evidence should be treated cautiously.", {})
    else:
        add_issue("info", "concept_harness_ready", "The live demo harness is healthy enough for concept testing.", {})

    if recent_scans:
        add_issue("info", "concept_scan_evidence_present", "Recent scan evidence is available for the current concept.", {"count": len(recent_scans)})
    else:
        add_issue("warning", "concept_scan_evidence_missing", "No recent scan evidence is available for the current concept.", {})

    if current_sample_started_at and current_sample_scans and len(current_sample_scans) != len(recent_scans):
        add_issue(
            "info",
            "concept_current_sample_since_restart",
            "The current concept sample is being judged from post-restart scan evidence so older rows do not distort the latest readout.",
            {
                "sample_started_at": current_sample_started_at,
                "current_sample_scan_count": len(current_sample_scans),
                "recent_scan_count": len(recent_scans),
            },
        )

    if recent_proposals:
        add_issue("info", "concept_proposals_present", "At least one proposal exists for the current concept.", {"count": len(recent_proposals)})
    else:
        add_issue("warning", "concept_proposals_missing", "No proposals exist yet, so the concept has not crossed into execution planning.", {})

    if recent_actions:
        add_issue("info", "concept_actions_present", "Execution actions exist for the current concept.", {"count": len(recent_actions)})
    else:
        add_issue("warning", "concept_actions_missing", "No execution actions exist yet, so operator/exchange evidence is still thin.", {})

    if recent_execution_state:
        add_issue("info", "concept_execution_state_present", "Execution-state evidence exists for the current concept.", {"count": len(recent_execution_state)})
    else:
        add_issue("warning", "concept_execution_state_missing", "Execution-state evidence is still missing for the current concept.", {})

    if verified_candidate_scans and len(recent_proposals) < len(verified_candidate_scans):
        details = {
            "verified_candidate_scan_count": len(verified_candidate_scans),
            "proposal_count": len(recent_proposals),
            "logged_candidate_count": len(logged_candidates),
            "duplicate_candidate_count": len(duplicate_candidates),
        }
        if include_legacy_metrics:
            details["legacy_candidate_scan_count"] = len(legacy_candidate_scans)
        add_issue(
            "warning",
            "concept_conversion_gap",
            "Recent verified candidates exist, but proposal conversion is still lagging behind concept detection.",
            details,
        )
        if top_conversion_blocker is not None:
            add_issue(
                "warning",
                "concept_conversion_blocker_visible",
                (
                    "Recent auto-execution blocker evidence points to "
                    f"{top_conversion_blocker.get('label')} as the leading conversion bottleneck."
                ),
                {
                    "event_type": top_conversion_blocker.get("event_type"),
                    "count": top_conversion_blocker.get("count"),
                    "blocker_mix": conversion_blocker_mix,
                },
            )
    elif verified_candidate_scans:
        details = {
            "verified_candidate_scan_count": len(verified_candidate_scans),
            "proposal_count": len(recent_proposals),
        }
        if include_legacy_metrics:
            details["legacy_candidate_scan_count"] = len(legacy_candidate_scans)
        add_issue(
            "info",
            "concept_conversion_flow_present",
            "Recent verified candidates are converting into proposal flow.",
            details,
        )

    if include_legacy_metrics and legacy_candidate_scans:
        add_issue(
            "info",
            "concept_legacy_candidate_compatibility_present",
            "Legacy compatibility-only paper_trade decisions are present, but they are excluded from the verified candidate totals.",
            {
                "legacy_candidate_scan_count": len(legacy_candidate_scans),
            },
        )

    working_orders = [
        item for item in recent_execution_state
        if clean_text(item.get("sync_status")) in {"working", "synced"}
        and clean_text(item.get("order_status")) in {"New", "PartiallyFilled", "Untriggered"}
    ]
    open_positions = [
        item for item in recent_execution_state
        if clean_text(item.get("position_size")) not in {None, "", "0", "0.0"}
    ]
    if working_orders:
        add_issue("info", "concept_working_order_present", "A live working order exists for the current concept on the exchange.", {"count": len(working_orders)})
    if open_positions:
        add_issue("info", "concept_open_position_present", "At least one open position exists for the current concept.", {"count": len(open_positions)})

    replay_pressure = summarize_concept_replay_pressure(
        review,
        len(recent_scans),
        getattr(args, "policy_path", CONCEPT_DECISION_POLICY_PATH),
    )
    if replay_pressure.get("revise_ready"):
        add_issue(
            "warning",
            "concept_replay_revision_pressure",
            "Replay evidence is mature enough to revise the visible rule pressure instead of waiting passively.",
            {
                "candidate_ratio": replay_pressure.get("candidate_ratio"),
                "total_steps": replay_pressure.get("total_steps"),
                "verified_trade_count": replay_pressure.get("verified_trade_count"),
                "dominant_blocker": replay_pressure.get("dominant_blocker"),
                "largest_gap": replay_pressure.get("largest_gap"),
            },
        )

    if review.get("overall") == "blocked":
        add_issue("warning", "concept_current_sample_strict", "The current replay sample is stricter than the concept-signoff baseline, so keep collecting evidence before changing rules.", {})
    elif replay_pressure.get("revise_ready"):
        add_issue("warning", "concept_current_sample_revision_ready", "The current replay sample has enough rule pressure to justify a concept revision.", {})
    elif review.get("overall") == "watch":
        add_issue("warning", "concept_current_sample_watch", "The current replay sample is in watch mode, so continue collecting evidence.", {})
    else:
        add_issue("info", "concept_current_sample_healthy", "The current replay sample looks healthy for the concept.", {})

    if latest_concept_runtime is not None:
        last_error = concept_lab_state.get("last_error") if isinstance(concept_lab_state.get("last_error"), dict) else {}
        last_error_message = clean_text(last_error.get("message"))
        lab_signal = clean_text(concept_lab_summary.get("operator_signal"))
        lab_summary_text = clean_text(concept_lab_summary.get("operator_summary"))
        if last_error_message:
            add_issue(
                "warning",
                "concept_background_lab_error",
                "The background concept lab recorded a recent cycle error, so its latest persisted verdict should be treated cautiously.",
                {
                    "updated_at": latest_concept_runtime.get("updated_at"),
                    "message": last_error_message,
                },
            )
        elif lab_signal == "revise_concept":
            add_issue(
                "warning",
                "concept_background_lab_revise_ready",
                "The background concept lab thinks Concept 1 has enough evidence to justify revision.",
                {
                    "updated_at": latest_concept_runtime.get("updated_at"),
                    "operator_summary": lab_summary_text,
                },
            )
        elif lab_signal == "compare_next_concept":
            add_issue(
                "info",
                "concept_background_lab_compare_ready",
                "The background concept lab thinks Concept 1 is ready to be compared against the next concept.",
                {
                    "updated_at": latest_concept_runtime.get("updated_at"),
                    "operator_summary": lab_summary_text,
                },
            )
        else:
            add_issue(
                "info",
                "concept_background_lab_present",
                "The background concept lab is persisting runtime state for this concept.",
                {
                    "updated_at": latest_concept_runtime.get("updated_at"),
                    "overall": concept_lab_summary.get("overall"),
                    "recommendation": concept_lab_summary.get("recommendation"),
                    "operator_signal": lab_signal,
                    "operator_summary": lab_summary_text,
                },
            )
    elif any(
        item.get("service_name") == "concept_lab_loop" and item.get("alive")
        for item in ((burnin_report_payload.get("manifest") or {}).get("items") or [])
    ):
        add_issue(
            "warning",
            "concept_background_lab_runtime_missing",
            "The concept lab daemon is running but has not written a runtime row yet.",
            {},
        )

    counts = {"info": 0, "warning": 0, "error": 0}
    for item in issues:
        counts[item["severity"]] = counts.get(item["severity"], 0) + 1

    if counts["error"] > 0:
        overall = "blocked"
        recommendation = "fix_harness"
    elif not recent_proposals or not recent_execution_state:
        overall = "collecting"
        recommendation = "revise_concept" if replay_pressure.get("revise_ready") else "collect_more_evidence"
    elif review.get("overall") in {"blocked", "watch"}:
        overall = "testing"
        recommendation = "continue_concept_testing"
    else:
        overall = "promising"
        recommendation = "continue_demo_burnin"

    if overall == "blocked":
        operator_signal = build_concept_operator_signal(
            "blocked",
            recommendation,
        )
    elif replay_pressure.get("operator_signal"):
        operator_signal = {
            "signal": replay_pressure.get("operator_signal"),
            "summary": replay_pressure.get("operator_summary"),
        }
    elif overall == "collecting":
        operator_signal = {
            "signal": "collect_more_evidence",
            "summary": "Keep collecting lifecycle evidence until proposals, actions, and execution-state rows are present.",
        }
    elif overall == "promising":
        operator_signal = {
            "signal": "continue_testing",
            "summary": "Continue demo burn-in; concept evidence is flowing without a dominant replay revision signal.",
        }
    else:
        operator_signal = build_concept_operator_signal(
            "testing",
            recommendation,
            dominant_blocker=replay_pressure.get("dominant_blocker"),
            candidate_ratio=replay_pressure.get("candidate_ratio"),
        )

    next_focus = []
    if overall in {"blocked", "collecting", "testing"}:
        next_focus.extend((review.get("next_focus") or [])[:3])
    if verified_candidate_scans and len(recent_proposals) < len(verified_candidate_scans):
        next_focus.append("Inspect auto-execution gating or duplicate suppression, because recent verified candidates are outpacing proposal creation.")
        if top_conversion_blocker is not None:
            next_focus.append(
                f"Recent auto-execution blockers are led by {top_conversion_blocker.get('label')}, so inspect that gate first."
            )
    if not recent_execution_state:
        next_focus.append("Keep the stack running until proposals produce exchange-backed execution-state rows.")
    elif working_orders and not open_positions:
        next_focus.append("Let the current working order either fill, cancel, or get managed so the concept collects deeper lifecycle evidence.")
    elif open_positions:
        next_focus.append("Observe the open position through management and exit so the concept gets full lifecycle evidence.")

    scan_mix = count_value_occurrences(sample_scans, "decision", "unset")
    if not include_legacy_metrics:
        scan_mix.pop("paper_trade", None)
    scan_metrics = {
        "verified_candidate_scan_count": len(verified_candidate_scans),
        "logged_verified_candidate_count": len(logged_candidates),
        "duplicate_verified_candidate_count": len(duplicate_candidates),
    }
    if include_legacy_metrics:
        scan_metrics["legacy_candidate_scan_count"] = len(legacy_candidate_scans)

    return {
        "ok": overall in {"testing", "promising"},
        "action": "concept-review",
        "overall": overall,
        "recommendation": recommendation,
        "counts": counts,
        "state_dir": review.get("state_dir"),
        "db_path": review.get("db_path"),
        "wave4_review": review,
        "evidence": {
            "recent_scan_count": len(recent_scans),
            "recent_proposal_count": len(recent_proposals),
            "recent_action_count": len(recent_actions),
            "recent_execution_state_count": len(recent_execution_state),
            "working_order_count": len(working_orders),
            "open_position_count": len(open_positions),
        },
        "sample_window": {
            "started_at": current_sample_started_at,
            "scan_count": len(sample_scans),
            "auto_execution_event_count": len(sample_auto_execution_events),
        },
        "legacy_compat_metrics_included": include_legacy_metrics,
        "scan_metrics": scan_metrics,
        "operator_signal": operator_signal.get("signal"),
        "operator_summary": operator_signal.get("summary"),
        "candidate_ratio": replay_pressure.get("candidate_ratio"),
        "dominant_blocker": replay_pressure.get("dominant_blocker"),
        "largest_gap": replay_pressure.get("largest_gap"),
        "scan_mix": scan_mix,
        "execution_mix": count_value_occurrences(recent_execution_state, "sync_status", "unset"),
        "auto_execution_blocker_mix": conversion_blocker_mix,
        "auto_execution_top_blocker": top_conversion_blocker,
        "background_lab": {
            "updated_at": latest_concept_runtime.get("updated_at") if isinstance(latest_concept_runtime, dict) else None,
            "overall": concept_lab_summary.get("overall"),
            "recommendation": concept_lab_summary.get("recommendation"),
            "candidate_ratio": concept_lab_summary.get("candidate_ratio"),
            "dominant_blocker": concept_lab_summary.get("dominant_blocker"),
            "dominant_blocker_ratio": concept_lab_summary.get("dominant_blocker_ratio"),
            "operator_signal": concept_lab_summary.get("operator_signal"),
            "operator_summary": concept_lab_summary.get("operator_summary"),
            "last_error": concept_lab_state.get("last_error"),
        },
        "background_events": recent_concept_events[:5],
        "issues": sorted(issues, key=lambda item: severity_rank.get(item["severity"], 99), reverse=True),
        "next_focus": next_focus,
    }


def concept_decision(args):
    include_legacy_metrics = include_legacy_compat_metrics(args)
    review = concept_review(args)
    wave4 = review.get("wave4_review") or {}
    replay = wave4.get("replay_tuning") or {}
    policy_doc = load_concept_decision_policy(getattr(args, "policy_path", CONCEPT_DECISION_POLICY_PATH))
    policy = policy_doc.get("policy") if isinstance(policy_doc.get("policy"), dict) else {}
    severity_rank = {"info": 0, "warning": 1, "error": 2}
    issues = []

    def add_issue(severity, code, summary, details=None):
        issues.append(
            {
                "severity": severity,
                "code": code,
                "summary": summary,
                "details": details if isinstance(details, dict) else {},
            }
        )

    if not policy_doc.get("ok"):
        add_issue(
            "error",
            "concept_policy_unavailable",
            "Concept decision policy could not be loaded.",
            {"errors": policy_doc.get("errors") or [], "path": policy_doc.get("path")},
        )

    evidence = review.get("evidence") or {}
    verified_candidate_scan_count = count_candidate_decisions(review.get("scan_mix") or {})
    legacy_candidate_scan_count = (
        count_legacy_candidate_decisions(review.get("scan_mix") or {})
        if include_legacy_metrics
        else 0
    )
    auto_execution_top_blocker = review.get("auto_execution_top_blocker") or {}
    minimum_evidence = policy.get("minimum_evidence") if isinstance(policy.get("minimum_evidence"), dict) else {}
    evidence_mapping = {
        "recent_scan_count": int(evidence.get("recent_scan_count") or 0),
        "recent_proposal_count": int(evidence.get("recent_proposal_count") or 0),
        "recent_action_count": int(evidence.get("recent_action_count") or 0),
        "recent_execution_state_count": int(evidence.get("recent_execution_state_count") or 0),
    }
    unmet_evidence = []
    for key, threshold in minimum_evidence.items():
        threshold_value = int(threshold or 0)
        actual_value = int(evidence_mapping.get(key) or 0)
        if actual_value < threshold_value:
            unmet_evidence.append(
                {
                    "metric": key,
                    "actual": actual_value,
                    "required": threshold_value,
                }
            )

    replay_summaries = replay.get("summaries") or []
    total_steps = sum(int(item.get("evaluated_steps") or 0) for item in replay_summaries)
    total_verified_trades = sum(replay_metric_count(item) for item in replay_summaries)
    candidate_ratio = ratio(total_verified_trades, total_steps)
    quality_thresholds = policy.get("quality_thresholds") if isinstance(policy.get("quality_thresholds"), dict) else {}
    minimum_candidate_ratio = float(quality_thresholds.get("minimum_candidate_ratio") or 0.0)
    review_blocker_ratio = float(quality_thresholds.get("review_blocker_ratio") or 0.0)
    severe_blocker_ratio = float(quality_thresholds.get("severe_blocker_ratio") or 1.0)
    severe_cross_market_gap = float(quality_thresholds.get("severe_cross_market_gap") or 1.0)

    blocker_ratios = {}
    for blocker in CONCEPT_REPLAY_BLOCKERS:
        blocker_ratios[blocker] = average_replay_ratio(replay, blocker)
    dominant_blocker = max(blocker_ratios.items(), key=lambda item: item[1]) if blocker_ratios else (None, 0.0)
    gap_report = ((replay.get("gap_report") or {}).get("blocker_gaps")) or []
    largest_gap = gap_report[0] if gap_report else None
    required_scan_count = int(minimum_evidence.get("recent_scan_count") or 0)
    scan_evidence_met = evidence_mapping.get("recent_scan_count", 0) >= required_scan_count
    severe_filtering = bool(dominant_blocker[0] and dominant_blocker[1] >= severe_blocker_ratio)
    severe_market_gap = bool(largest_gap and float(largest_gap.get("gap") or 0.0) >= severe_cross_market_gap)
    mature_revision_sample = bool(
        scan_evidence_met
        and total_steps
        and candidate_ratio < minimum_candidate_ratio
        and (severe_filtering or severe_market_gap)
    )
    mature_overfiltered_sample = bool(mature_revision_sample and severe_filtering)

    if review.get("overall") == "blocked":
        add_issue("error", "concept_harness_blocked", "The concept harness is still blocked, so the concept cannot be judged yet.", {})
    elif unmet_evidence:
        if mature_revision_sample:
            add_issue(
                "warning",
                "concept_scan_evidence_mature_but_overfiltered",
                (
                    "Scan evidence is mature enough to judge the current sample, but candidate flow is still blocked before proposals; "
                    "revise the visible rule pressure instead of waiting passively."
                ),
                {
                    "recent_scan_count": evidence_mapping.get("recent_scan_count", 0),
                    "required_scan_count": required_scan_count,
                    "candidate_ratio": candidate_ratio,
                    "dominant_blocker": {
                        "blocker": dominant_blocker[0],
                        "ratio": dominant_blocker[1],
                    },
                    "largest_gap": largest_gap,
                },
            )
        add_issue(
            "warning",
            "concept_evidence_below_threshold",
            (
                "Lifecycle evidence is still below threshold because no verified candidates are reaching proposals yet; scan evidence is mature enough to revise the visible rule pressure."
                if mature_revision_sample
                else "Concept evidence is still below the minimum decision threshold, so keep collecting data before judging the concept."
            ),
            {"unmet_evidence": unmet_evidence},
        )
    else:
        add_issue(
            "info",
            "concept_evidence_threshold_met",
            "Concept evidence has reached the minimum decision threshold.",
            {"minimum_evidence": minimum_evidence},
        )

    if dominant_blocker[0] and dominant_blocker[1] >= severe_blocker_ratio:
        blocker_label = render_concept_blocker_label(dominant_blocker[0])
        add_issue(
            "warning",
            "concept_overfiltered",
            f"{blocker_label} is still filtering an oversized share of replay steps.",
            {"blocker": dominant_blocker[0], "ratio": dominant_blocker[1]},
        )
    elif dominant_blocker[0] and dominant_blocker[1] >= review_blocker_ratio:
        blocker_label = render_concept_blocker_label(dominant_blocker[0])
        add_issue(
            "warning",
            "concept_heavy_filtering",
            f"{blocker_label} is still the dominant blocker in the current replay sample.",
            {"blocker": dominant_blocker[0], "ratio": dominant_blocker[1]},
        )
    else:
        add_issue(
            "info",
            "concept_filtering_balanced",
            "No single replay blocker is dominating the sample beyond the review threshold.",
            {"blocker_ratios": blocker_ratios},
        )

    if largest_gap and float(largest_gap.get("gap") or 0.0) >= severe_cross_market_gap:
        add_issue(
            "warning",
            "concept_cross_market_gap",
            "The concept is still behaving very differently across BTC and ETH.",
            {"largest_gap": largest_gap},
        )
    elif largest_gap:
        add_issue(
            "info",
            "concept_cross_market_gap_ok",
            "No severe BTC/ETH imbalance was detected at the current decision threshold.",
            {"largest_gap": largest_gap},
        )

    if total_steps and candidate_ratio < minimum_candidate_ratio:
        add_issue(
            "warning",
            "concept_candidate_ratio_low",
            "The replay candidate ratio is still below the minimum concept decision threshold.",
            {
                "candidate_ratio": candidate_ratio,
                "minimum_candidate_ratio": minimum_candidate_ratio,
                "total_steps": total_steps,
                "verified_trade_count": total_verified_trades,
            },
        )
    elif total_steps:
        add_issue(
            "info",
            "concept_candidate_ratio_ok",
            "The replay candidate ratio is at or above the minimum decision threshold.",
            {
                "candidate_ratio": candidate_ratio,
                "minimum_candidate_ratio": minimum_candidate_ratio,
                "total_steps": total_steps,
                "verified_trade_count": total_verified_trades,
            },
        )

    if verified_candidate_scan_count > evidence_mapping.get("recent_proposal_count", 0):
        details = {
            "verified_candidate_scan_count": verified_candidate_scan_count,
            "recent_proposal_count": evidence_mapping.get("recent_proposal_count", 0),
        }
        if include_legacy_metrics:
            details["legacy_candidate_scan_count"] = legacy_candidate_scan_count
        add_issue(
            "warning",
            "concept_proposal_conversion_thin",
            "Recent verified candidates are appearing, but they are not yet converting into enough proposals.",
            details,
        )
        if auto_execution_top_blocker.get("event_type"):
            add_issue(
                "warning",
                "concept_conversion_blocker_visible",
                (
                    "Recent auto-execution evidence points to "
                    f"{auto_execution_top_blocker.get('label')} as the dominant proposal-conversion blocker."
                ),
                auto_execution_top_blocker,
            )

    if include_legacy_metrics and legacy_candidate_scan_count:
        add_issue(
            "info",
            "concept_legacy_candidate_compatibility_present",
            "Legacy compatibility-only paper_trade counts are present, but they are excluded from the verified candidate totals.",
            {
                "legacy_candidate_scan_count": legacy_candidate_scan_count,
            },
        )

    counts = {"info": 0, "warning": 0, "error": 0}
    for item in issues:
        counts[item["severity"]] = counts.get(item["severity"], 0) + 1

    if review.get("overall") == "blocked" or counts["error"] > 0:
        overall = "blocked"
        recommendation = "fix_harness"
    elif mature_revision_sample or (scan_evidence_met and (severe_filtering or severe_market_gap)):
        overall = "revise"
        recommendation = "revise_concept"
    elif unmet_evidence:
        overall = "collecting"
        recommendation = "collect_more_evidence"
    elif severe_filtering or severe_market_gap:
        overall = "revise"
        recommendation = "revise_concept"
    elif candidate_ratio < minimum_candidate_ratio:
        overall = "testing"
        recommendation = "continue_testing"
    else:
        overall = "compare"
        recommendation = "compare_against_next_concept"

    next_focus = []
    if overall == "collecting":
        next_focus.append("Keep the stack running until the concept reaches the minimum evidence thresholds in the concept decision policy.")
    elif overall == "revise":
        next_focus.append("The concept now has enough evidence to justify a rules revision rather than another purely observational pass.")
    elif overall == "testing":
        next_focus.append("The harness is usable and the concept has enough evidence to keep testing, but candidate flow is still below the decision threshold.")
    elif overall == "compare":
        next_focus.append("The concept has crossed the minimum decision thresholds and is ready to be compared against the next candidate concept.")
    if verified_candidate_scan_count > evidence_mapping.get("recent_proposal_count", 0):
        next_focus.append("Inspect why verified candidates are not converting into proposals yet, because concept detection is now ahead of execution flow.")
        if auto_execution_top_blocker.get("event_type"):
            next_focus.append(
                f"Start with {auto_execution_top_blocker.get('label')}, because that is the dominant recent auto-execution blocker."
            )
    next_focus.extend((review.get("next_focus") or [])[:2])

    operator_signal = build_concept_operator_signal(
        overall,
        recommendation,
        unmet_evidence=unmet_evidence,
        dominant_blocker={
            "blocker": dominant_blocker[0],
            "ratio": dominant_blocker[1],
        },
        cross_market_gap=largest_gap if severe_market_gap else None,
        candidate_ratio=candidate_ratio,
    )

    return {
        "ok": overall in {"testing", "compare"},
        "action": "concept-decision",
        "overall": overall,
        "recommendation": recommendation,
        "counts": counts,
        "state_dir": review.get("state_dir"),
        "db_path": review.get("db_path"),
        "policy": policy,
        "policy_path": policy_doc.get("path"),
        "concept_review": review,
        "legacy_compat_metrics_included": include_legacy_metrics,
        "evidence": evidence_mapping,
        "unmet_evidence": unmet_evidence,
        "candidate_ratio": candidate_ratio,
        "dominant_blocker": {
            "blocker": dominant_blocker[0],
            "ratio": dominant_blocker[1],
        },
        "operator_signal": operator_signal.get("signal"),
        "operator_summary": operator_signal.get("summary"),
        "largest_gap": largest_gap,
        "issues": sorted(issues, key=lambda item: severity_rank.get(item["severity"], 99), reverse=True),
        "next_focus": next_focus,
    }


def concept_brief(args):
    decision = concept_decision(args)
    review = decision.get("concept_review") or {}
    return build_concept_brief_packet(review, decision)


def concept_revision_brief(args):
    brief = concept_brief(args)
    concept_id = clean_text(brief.get("concept_id")) or "concept-1"
    artifact_limit = max(1, int(getattr(args, "artifact_limit", 20) or 20))
    top_limit = max(1, int(getattr(args, "top_limit", 3) or 3))
    review_records = list_concept_review_records(getattr(args, "db_path", DEFAULT_DB_PATH), concept_id=concept_id, limit=artifact_limit)
    revision_records = list_concept_revision_records(
        getattr(args, "db_path", DEFAULT_DB_PATH),
        concept_id=concept_id,
        limit=artifact_limit,
    )
    compare_summary = summarize_concept_revision_loop(revision_records, review_records)
    return build_concept_revision_brief_packet(
        brief,
        compare_summary,
        revision_records,
        review_records,
        top_limit=top_limit,
    )


def concept_acceptance_brief(args):
    brief = concept_brief(args)
    concept_id = clean_text(brief.get("concept_id")) or "concept-1"
    artifact_limit = max(1, int(getattr(args, "artifact_limit", 20) or 20))
    top_limit = max(1, int(getattr(args, "top_limit", 3) or 3))
    review_records = list_concept_review_records(getattr(args, "db_path", DEFAULT_DB_PATH), concept_id=concept_id, limit=artifact_limit)
    revision_records = list_concept_revision_records(
        getattr(args, "db_path", DEFAULT_DB_PATH),
        concept_id=concept_id,
        limit=artifact_limit,
    )
    compare_summary = summarize_concept_revision_loop(revision_records, review_records)
    concept_runtime = get_concept_runtime_record(getattr(args, "db_path", DEFAULT_DB_PATH), runtime_key="main")
    live_compare = (
        concept_runtime.get("state", {}).get("revision_compare")
        if isinstance((concept_runtime or {}).get("state"), dict)
        else None
    ) or (
        concept_runtime.get("last_summary", {}).get("revision_compare")
        if isinstance((concept_runtime or {}).get("last_summary"), dict)
        else None
    )
    compare_summary["stage5_readiness"] = build_stage5_readiness(compare_summary, live_compare)
    return build_concept_acceptance_brief_packet(
        brief,
        compare_summary,
        live_compare=live_compare,
        review_records=review_records,
        revision_records=revision_records,
        top_limit=top_limit,
    )


def concept_stage7_decision_brief(args):
    acceptance_brief = concept_acceptance_brief(args)
    concept_id = clean_text(acceptance_brief.get("concept_id")) or "concept-1"
    artifact_limit = max(1, int(getattr(args, "artifact_limit", 20) or 20))
    review_records = list_concept_review_records(
        getattr(args, "db_path", DEFAULT_DB_PATH),
        concept_id=concept_id,
        limit=artifact_limit,
    )
    return build_concept_stage7_decision_brief_packet(
        acceptance_brief,
        review_records=review_records,
    )


def concept_revision_plan(args):
    brief = concept_brief(args)
    review_artifact = None
    review_id = clean_text(getattr(args, "review_id", ""))
    if review_id:
        review_artifact = get_concept_review_record(getattr(args, "db_path", DEFAULT_DB_PATH), review_id)
    return build_concept_revision_plan(
        brief,
        candidate_id=getattr(args, "candidate_id", ""),
        review_artifact=review_artifact,
        source="stackctl",
        author="stackctl",
    )


def concept_save_review(args):
    response_path = Path(getattr(args, "response_file", "")).expanduser()
    document = json.loads(response_path.read_text(encoding="utf-8"))
    validation = validate_structured_review_response(document)
    if not validation.get("ok"):
        return {
            "ok": False,
            "response_file": str(response_path),
            "errors": validation.get("errors") or [],
        }

    brief = concept_brief(args)
    record = build_structured_review_record(
        validation.get("response") or {},
        brief,
        source=getattr(args, "source", "llm"),
        author=getattr(args, "author", ""),
    )
    stored = store_concept_review_record(getattr(args, "db_path", DEFAULT_DB_PATH), record)
    record["review_id"] = stored.get("review_id")
    record["created_at"] = stored.get("created_at")
    return {
        "ok": True,
        "response_file": str(response_path),
        "validation": validation,
        "review_record": record,
    }


def concept_save_acceptance_review(args):
    response_path = Path(getattr(args, "response_file", "")).expanduser()
    document = json.loads(response_path.read_text(encoding="utf-8"))
    validation = validate_acceptance_response(document)
    if not validation.get("ok"):
        return {
            "ok": False,
            "response_file": str(response_path),
            "errors": validation.get("errors") or [],
        }

    brief = concept_acceptance_brief(args)
    record = build_structured_acceptance_record(
        validation.get("response") or {},
        brief,
        source=getattr(args, "source", "llm"),
        author=getattr(args, "author", ""),
    )
    stored = store_concept_review_record(getattr(args, "db_path", DEFAULT_DB_PATH), record)
    record["review_id"] = stored.get("review_id")
    record["created_at"] = stored.get("created_at")
    return {
        "ok": True,
        "response_file": str(response_path),
        "validation": validation,
        "review_record": record,
    }


def concept_save_stage7_decision(args):
    response_path = Path(getattr(args, "response_file", "")).expanduser()
    document = json.loads(response_path.read_text(encoding="utf-8"))
    validation = validate_stage7_decision_response(document)
    if not validation.get("ok"):
        return {
            "ok": False,
            "response_file": str(response_path),
            "errors": validation.get("errors") or [],
        }

    brief = concept_stage7_decision_brief(args)
    record = build_structured_stage7_decision_record(
        validation.get("response") or {},
        brief,
        source=getattr(args, "source", "llm"),
        author=getattr(args, "author", ""),
    )
    stored = store_concept_review_record(getattr(args, "db_path", DEFAULT_DB_PATH), record)
    record["review_id"] = stored.get("review_id")
    record["created_at"] = stored.get("created_at")
    return {
        "ok": True,
        "response_file": str(response_path),
        "validation": validation,
        "review_record": record,
    }


def concept_save_revision_compare(args):
    response_path = Path(getattr(args, "response_file", "")).expanduser()
    document = json.loads(response_path.read_text(encoding="utf-8"))
    validation = validate_revision_compare_response(document)
    if not validation.get("ok"):
        return {
            "ok": False,
            "response_file": str(response_path),
            "errors": validation.get("errors") or [],
        }

    brief = concept_revision_brief(args)
    record = build_structured_revision_compare_record(
        validation.get("response") or {},
        brief,
        source=getattr(args, "source", "llm"),
        author=getattr(args, "author", ""),
    )
    stored = store_concept_review_record(getattr(args, "db_path", DEFAULT_DB_PATH), record)
    record["review_id"] = stored.get("review_id")
    record["created_at"] = stored.get("created_at")
    return {
        "ok": True,
        "response_file": str(response_path),
        "validation": validation,
        "review_record": record,
    }


def concept_promote_review(args):
    review_id = clean_text(getattr(args, "review_id", ""))
    review_record = get_concept_review_record(getattr(args, "db_path", DEFAULT_DB_PATH), review_id)
    if review_record is None:
        return {
            "ok": False,
            "review_id": review_id,
            "error": f"concept review {review_id or '-'} not found",
        }

    brief = concept_brief(args)
    source = clean_text(getattr(args, "source", "")) or "linked_review"
    author = clean_text(getattr(args, "author", "")) or clean_text(review_record.get("author"))
    plan = build_concept_revision_plan(
        brief,
        candidate_id=getattr(args, "candidate_id", ""),
        review_artifact=review_record,
        source=source,
        author=author,
    )
    stored = store_concept_revision_record(getattr(args, "db_path", DEFAULT_DB_PATH), plan)
    plan["revision_id"] = stored.get("revision_id")
    plan["created_at"] = stored.get("created_at")
    return {
        "ok": True,
        "review_record": review_record,
        "revision_record": plan,
    }


def concept_evaluate_review(args):
    review_id = clean_text(getattr(args, "review_id", ""))
    review_record = get_concept_review_record(getattr(args, "db_path", DEFAULT_DB_PATH), review_id)
    if review_record is None:
        return {
            "ok": False,
            "review_id": review_id,
            "error": f"concept review {review_id or '-'} not found",
        }

    revision_record = get_latest_concept_revision_for_review(getattr(args, "db_path", DEFAULT_DB_PATH), review_id)
    if revision_record is None:
        return {
            "ok": False,
            "review_id": review_id,
            "error": f"no saved concept revision is linked to review {review_id}",
        }

    revision_payload = revision_record.get("revision") or {}
    brief = concept_brief(args)
    evaluation = evaluate_concept_revision_plan(revision_payload, brief)
    history_result = record_concept_revision_evaluation(revision_payload, evaluation)
    revision_payload = history_result.get("plan") or revision_payload
    revision_payload["status"] = evaluation.get("status") or revision_payload.get("status") or "planned"
    revision_payload["summary"] = revision_payload.get("summary") or clean_text(
        (revision_payload.get("selected_candidate") or {}).get("rationale")
    ) or "concept revision"
    update_concept_revision_record(getattr(args, "db_path", DEFAULT_DB_PATH), revision_record.get("revision_id"), revision_payload)
    updated_revision = get_concept_revision_record(getattr(args, "db_path", DEFAULT_DB_PATH), revision_record.get("revision_id"))
    return {
        "ok": True,
        "review_record": review_record,
        "revision_record": updated_revision,
        "evaluation": evaluation,
        "history": {
            "key": history_result.get("history_key"),
            "updated": history_result.get("history_updated"),
            "replaced": history_result.get("history_replaced"),
            "count": history_result.get("history_count"),
        },
        "current_brief": brief,
    }


def redact_secret(raw_value, prefix=4, suffix=2):
    value = clean_text(raw_value)
    if value is None:
        return None
    if len(value) <= prefix + suffix:
        return "*" * len(value)
    return f"{value[:prefix]}...{value[-suffix:]}"
def run_bybit_wallet_probe(account_type, balance_coin):
    from bybit_client import fetch_bybit_wallet_balance

    result = fetch_bybit_wallet_balance(account_type=account_type, coin=balance_coin)
    response = result.get("response") if isinstance(result.get("response"), dict) else {}
    account_record = result.get("account") if isinstance(result.get("account"), dict) else {}
    coin_record = result.get("coin_record") if isinstance(result.get("coin_record"), dict) else None
    return {
        "ok": bool(result.get("ok")),
        "http_status": result.get("http_status"),
        "ret_code": response.get("retCode"),
        "ret_msg": response.get("retMsg"),
        "error": response.get("error"),
        "account_type_returned": account_record.get("accountType"),
        "coin_found": coin_record is not None,
    }


def run_bybit_api_key_probe():
    from bybit_client import fetch_bybit_api_key_information

    result = fetch_bybit_api_key_information()
    response = result.get("response") if isinstance(result.get("response"), dict) else {}
    api_info = result.get("api_info") if isinstance(result.get("api_info"), dict) else {}
    permissions = api_info.get("permissions") if isinstance(api_info.get("permissions"), dict) else {}
    return {
        "ok": bool(result.get("ok")),
        "http_status": result.get("http_status"),
        "ret_code": response.get("retCode"),
        "ret_msg": response.get("retMsg"),
        "error": response.get("error"),
        "api_key": api_info.get("apiKey"),
        "note": api_info.get("note"),
        "read_only": api_info.get("readOnly"),
        "uta": api_info.get("uta"),
        "is_master": api_info.get("isMaster"),
        "permissions": permissions,
        "rsa_public_key_present": bool(api_info.get("rsaPublicKey")),
    }


def interpret_bybit_probe(probe):
    probe = probe if isinstance(probe, dict) else {}
    http_status = probe.get("http_status")
    ret_code = probe.get("ret_code")
    diagnosis = {
        "code": None,
        "summary": None,
        "likely_causes": [],
    }
    if probe.get("ok"):
        diagnosis["code"] = "auth_ok"
        diagnosis["summary"] = "Bybit private auth is working for the selected environment."
        return diagnosis

    if ret_code == 10003:
        diagnosis["code"] = "api_key_domain_mismatch"
        diagnosis["summary"] = "API key is invalid for the selected Bybit environment."
        diagnosis["likely_causes"] = [
            "The key/secret pair does not belong to the selected Bybit environment.",
            "The key was created for a different Bybit environment such as mainnet, demo, or testnet.",
        ]
        return diagnosis
    if ret_code == 10004:
        diagnosis["code"] = "signature_invalid"
        diagnosis["summary"] = "Bybit rejected the request signature."
        diagnosis["likely_causes"] = [
            "The secret does not match the API key.",
            "The key or secret contains an accidental extra character or whitespace.",
        ]
        return diagnosis
    if ret_code == 10005:
        diagnosis["code"] = "permission_denied"
        diagnosis["summary"] = "The API key is missing the required private-account permission."
        diagnosis["likely_causes"] = [
            "The key does not have wallet/account read access.",
            "The key was created with permissions too narrow for private REST usage.",
        ]
        return diagnosis
    if ret_code == 10008:
        diagnosis["code"] = "account_mode_mismatch"
        diagnosis["summary"] = "The account mode does not match the request."
        diagnosis["likely_causes"] = [
            "The account is not in the expected Unified account mode.",
            "The request account type does not match the account behind the API key.",
        ]
        return diagnosis
    if ret_code == 10010:
        diagnosis["code"] = "ip_mismatch"
        diagnosis["summary"] = "The request IP does not match the API key IP allowlist."
        diagnosis["likely_causes"] = [
            "The key is restricted to different IP addresses.",
            "The current network egress IP is not in the API key allowlist.",
        ]
        return diagnosis
    if http_status == 401:
        diagnosis["code"] = "http_401_invalid_request"
        diagnosis["summary"] = "Bybit returned HTTP 401 for the signed private request."
        diagnosis["likely_causes"] = [
            "The API key and selected environment do not match.",
            "The key/secret pair is invalid or copied incorrectly.",
            "The request was signed with a key that is not accepted for this private endpoint.",
        ]
        return diagnosis
    if http_status == 403:
        diagnosis["code"] = "http_403_forbidden"
        diagnosis["summary"] = "Bybit returned HTTP 403 for the private request."
        diagnosis["likely_causes"] = [
            "The current IP is restricted or not allowed by the API key.",
            "The request originated from a restricted jurisdiction.",
            "A request rule was blocked before auth completed.",
        ]
        return diagnosis

    diagnosis["code"] = "auth_failed_unknown"
    diagnosis["summary"] = "Bybit private auth failed, but the response did not include a specific documented code."
    return diagnosis


def bybit_doctor(args):
    from bybit_client import (
        BYBIT_API_KEY,
        BYBIT_API_SECRET,
        BYBIT_ENABLE_PRIVATE_SUBMIT,
        BYBIT_ENV,
        BYBIT_MARKET_BASE_URL,
        BYBIT_PRIVATE_BASE_URL,
    )
    from private_stream_loop import build_private_ws_url

    issues = []
    severity_rank = {"info": 0, "warning": 1, "error": 2}
    env_info = getattr(args, "_env_info", {}) if hasattr(args, "_env_info") else {}

    def add_issue(severity, code, summary, details=None):
        issues.append(
            {
                "severity": severity,
                "code": code,
                "summary": summary,
                "details": details if isinstance(details, dict) else {},
            }
        )

    execution_doc = load_json_document(EXECUTION_SPEC_PATH, "execution spec")
    execution_data = execution_doc.get("data") if execution_doc.get("ok") else {}
    account_type = clean_text(getattr(args, "account_type", "")) or clean_text(execution_data.get("account_type")) or "UNIFIED"
    balance_coin = clean_text(getattr(args, "balance_coin", "")) or clean_text(execution_data.get("balance_coin")) or "USDT"

    has_key = bool(BYBIT_API_KEY)
    has_secret = bool(BYBIT_API_SECRET)
    if env_info.get("loaded"):
        add_issue(
            "info",
            "env_file_loaded",
            "launcher env file loaded successfully",
            {
                "path": env_info.get("path"),
                "entries": env_info.get("entries"),
                "skipped_existing": env_info.get("skipped_existing"),
                "override": env_info.get("override"),
            },
        )
    elif env_info.get("disabled"):
        add_issue("info", "env_file_disabled", "launcher env file loading is disabled for this run", {})
    if has_key and has_secret:
        add_issue("info", "credentials_present", "Bybit API credentials are present in the current shell", {})
    else:
        missing = []
        if not has_key:
            missing.append("BYBIT_API_KEY")
        if not has_secret:
            missing.append("BYBIT_API_SECRET")
        add_issue(
            "error",
            "credentials_missing",
            "Bybit API credentials are missing from the current shell",
            {"missing": missing},
        )

    if BYBIT_ENABLE_PRIVATE_SUBMIT:
        add_issue("info", "submit_enabled", "Bybit private submission is enabled", {})
    else:
        add_issue("warning", "submit_disabled", "Bybit private submission is disabled", {})

    add_issue(
        "info",
        "base_urls",
        "Bybit base URLs were resolved",
        {
            "bybit_env": BYBIT_ENV,
            "market_base_url": BYBIT_MARKET_BASE_URL,
            "private_base_url": BYBIT_PRIVATE_BASE_URL,
            "private_ws_url": build_private_ws_url(max_active_time="", environment=BYBIT_ENV),
        },
    )

    api_probe = {
        "attempted": False,
        "ok": None,
        "http_status": None,
        "ret_code": None,
        "ret_msg": None,
        "error": None,
        "read_only": None,
        "uta": None,
        "is_master": None,
        "permissions": {},
        "rsa_public_key_present": None,
        "diagnosis": None,
    }
    if not (has_key and has_secret):
        add_issue("error", "api_probe_blocked", "API info probe could not run because credentials are missing", {})
    else:
        api_probe["attempted"] = True
        api_probe_result = run_bybit_api_key_probe()
        api_probe["ok"] = api_probe_result.get("ok")
        api_probe["http_status"] = api_probe_result.get("http_status")
        api_probe["ret_code"] = api_probe_result.get("ret_code")
        api_probe["ret_msg"] = api_probe_result.get("ret_msg")
        api_probe["error"] = api_probe_result.get("error")
        api_probe["read_only"] = api_probe_result.get("read_only")
        api_probe["uta"] = api_probe_result.get("uta")
        api_probe["is_master"] = api_probe_result.get("is_master")
        api_probe["permissions"] = api_probe_result.get("permissions") or {}
        api_probe["rsa_public_key_present"] = api_probe_result.get("rsa_public_key_present")
        api_probe["diagnosis"] = interpret_bybit_probe(api_probe_result)
        if api_probe_result.get("ok"):
            add_issue(
                "info",
                "api_probe_ok",
                "private API-key info auth succeeded on the selected Bybit environment",
                {
                    "read_only": api_probe_result.get("read_only"),
                    "uta": api_probe_result.get("uta"),
                    "is_master": api_probe_result.get("is_master"),
                    "rsa_public_key_present": api_probe_result.get("rsa_public_key_present"),
                },
            )
        else:
            diagnosis = api_probe.get("diagnosis") or {}
            detail_summary = (
                api_probe_result.get("ret_msg")
                or api_probe_result.get("error")
                or diagnosis.get("summary")
                or "API info probe failed"
            )
            add_issue(
                "error",
                "api_probe_failed",
                f"private API-key info auth failed: {detail_summary}",
                {
                    "http_status": api_probe_result.get("http_status"),
                    "ret_code": api_probe_result.get("ret_code"),
                    "ret_msg": api_probe_result.get("ret_msg"),
                    "error": api_probe_result.get("error"),
                    "diagnosis": diagnosis,
                },
            )

    wallet_probe = {
        "attempted": False,
        "ok": None,
        "account_type": account_type,
        "balance_coin": balance_coin,
        "http_status": None,
        "ret_code": None,
        "ret_msg": None,
        "error": None,
        "account_type_returned": None,
        "coin_found": None,
        "diagnosis": None,
        "masked_key": redact_secret(BYBIT_API_KEY),
    }
    if args.skip_wallet_probe:
        add_issue("warning", "wallet_probe_skipped", "wallet probe was skipped by request", {})
    elif not (has_key and has_secret):
        add_issue("error", "wallet_probe_blocked", "wallet probe could not run because credentials are missing", {})
    else:
        wallet_probe["attempted"] = True
        probe_result = run_bybit_wallet_probe(account_type, balance_coin)
        wallet_probe["ok"] = probe_result.get("ok")
        wallet_probe["http_status"] = probe_result.get("http_status")
        wallet_probe["ret_code"] = probe_result.get("ret_code")
        wallet_probe["ret_msg"] = probe_result.get("ret_msg")
        wallet_probe["error"] = probe_result.get("error")
        wallet_probe["account_type_returned"] = probe_result.get("account_type_returned")
        wallet_probe["coin_found"] = probe_result.get("coin_found")
        wallet_probe["diagnosis"] = interpret_bybit_probe(probe_result)
        if probe_result.get("ok"):
            add_issue(
                "info",
                "wallet_probe_ok",
                "private wallet-balance auth succeeded on the selected Bybit environment",
                {
                    "account_type": account_type,
                    "balance_coin": balance_coin,
                    "coin_found": probe_result.get("coin_found"),
                },
            )
        else:
            diagnosis = wallet_probe.get("diagnosis") or {}
            detail_summary = (
                probe_result.get("ret_msg")
                or probe_result.get("error")
                or diagnosis.get("summary")
                or "wallet probe failed"
            )
            add_issue(
                "error",
                "wallet_probe_failed",
                f"private wallet-balance auth failed: {detail_summary}",
                {
                    "http_status": probe_result.get("http_status"),
                    "ret_code": probe_result.get("ret_code"),
                    "ret_msg": probe_result.get("ret_msg"),
                    "error": probe_result.get("error"),
                    "account_type": account_type,
                    "balance_coin": balance_coin,
                    "diagnosis": diagnosis,
                },
            )

    counts = {"info": 0, "warning": 0, "error": 0}
    for issue in issues:
        counts[issue["severity"]] = counts.get(issue["severity"], 0) + 1
    overall = "blocked" if counts["error"] else ("watch" if counts["warning"] else "ready")
    env_sources = {
        "BYBIT_API_KEY": resolve_env_source("BYBIT_API_KEY", env_info),
        "BYBIT_API_SECRET": resolve_env_source("BYBIT_API_SECRET", env_info),
        "BYBIT_ENV": resolve_env_source("BYBIT_ENV", env_info),
        "BYBIT_ENABLE_TESTNET_SUBMIT": resolve_first_env_source(
            ["BYBIT_ENABLE_PRIVATE_SUBMIT", "BYBIT_ENABLE_TESTNET_SUBMIT"], env_info
        ),
    }
    return {
        "ok": counts["error"] == 0,
        "action": "bybit-doctor",
        "overall": overall,
        "counts": counts,
        "state_dir": str(Path(args.state_dir).expanduser()),
        "db_path": args.db_path,
        "env_file": env_info,
        "env_sources": env_sources,
        "issues": sorted(issues, key=lambda item: severity_rank.get(item["severity"], 99), reverse=True),
        "api_probe": api_probe,
        "probe": wallet_probe,
    }


def env_debug(args):
    from bybit_client import BYBIT_API_KEY, BYBIT_API_SECRET, BYBIT_ENABLE_PRIVATE_SUBMIT, BYBIT_ENV

    env_info = getattr(args, "_env_info", {}) if hasattr(args, "_env_info") else {}
    variables = {
        "BYBIT_ENV": {
            "present": True,
            "raw_value": clean_text(os.environ.get("BYBIT_ENV")) or "testnet",
            "normalized_value": BYBIT_ENV,
            "source": resolve_env_source("BYBIT_ENV", env_info),
        },
        "BYBIT_API_KEY": safe_value_fingerprint(BYBIT_API_KEY),
        "BYBIT_API_SECRET": safe_value_fingerprint(BYBIT_API_SECRET),
        "BYBIT_ENABLE_TESTNET_SUBMIT": {
            "present": clean_text(os.environ.get("BYBIT_ENABLE_TESTNET_SUBMIT")) is not None,
            "raw_value": clean_text(os.environ.get("BYBIT_ENABLE_PRIVATE_SUBMIT"))
            or clean_text(os.environ.get("BYBIT_ENABLE_TESTNET_SUBMIT")),
            "normalized_true": bool(BYBIT_ENABLE_PRIVATE_SUBMIT),
            "source": resolve_first_env_source(
                ["BYBIT_ENABLE_PRIVATE_SUBMIT", "BYBIT_ENABLE_TESTNET_SUBMIT"], env_info
            ),
        },
    }
    variables["BYBIT_API_KEY"]["source"] = resolve_env_source("BYBIT_API_KEY", env_info)
    variables["BYBIT_API_SECRET"]["source"] = resolve_env_source("BYBIT_API_SECRET", env_info)

    return {
        "ok": True,
        "action": "env-debug",
        "state_dir": str(Path(args.state_dir).expanduser()),
        "db_path": args.db_path,
        "env_file": env_info,
        "variables": variables,
    }


def build_service_specs(args):
    env = {
        "TRADING_API_DB_PATH": args.db_path,
        "TRADING_API_HOST": args.host,
        "TRADING_API_PORT": str(args.port),
    }
    base = sys.executable
    launch_snapshot = build_bybit_env_snapshot(getattr(args, "_env_info", {}))
    specs = [
        {
            "service_name": "server",
            "command": [base, str(BASE_DIR / "server.py")],
            "env": env,
            "launch_snapshot": launch_snapshot,
        },
        {
            "service_name": "scan_loop",
            "command": [
                base,
                str(BASE_DIR / "scan_loop.py"),
                "--interval-seconds",
                str(max(10, args.scan_interval_seconds)),
            ]
            + ([] if args.disable_auto_log_candidates else ["--auto-log-candidates"]),
            "env": env,
            "launch_snapshot": launch_snapshot,
        },
        {
            "service_name": "supervisor_loop",
            "command": [
                base,
                str(BASE_DIR / "supervisor_loop.py"),
                "--runtime-key",
                "main",
                "--interval-seconds",
                str(max(10, args.supervisor_interval_seconds)),
            ],
            "env": env,
            "launch_snapshot": launch_snapshot,
        },
        {
            "service_name": "ops_loop",
            "command": [
                base,
                str(BASE_DIR / "ops_loop.py"),
                "--runtime-key",
                "main",
                "--interval-seconds",
                str(max(5, args.ops_interval_seconds)),
            ],
            "env": env,
            "launch_snapshot": launch_snapshot,
        },
    ]

    if getattr(args, "with_private_stream", False):
        if not os.environ.get("BYBIT_API_KEY") or not os.environ.get("BYBIT_API_SECRET"):
            raise SystemExit("BYBIT_API_KEY and BYBIT_API_SECRET are required for --with-private-stream")
        specs.append(
            {
                "service_name": "private_stream_loop",
                "command": [
                    base,
                    str(BASE_DIR / "private_stream_loop.py"),
                    "--runtime-key",
                    "stream-main",
                ],
                "env": env,
                "launch_snapshot": launch_snapshot,
            }
        )
    if getattr(args, "with_auto_execution", False):
        specs.append(
            {
                "service_name": "auto_execute_loop",
                "command": [
                    base,
                    str(BASE_DIR / "auto_execute_loop.py"),
                    "--runtime-key",
                    "main",
                    "--interval-seconds",
                    str(max(5, args.auto_execution_interval_seconds)),
                ],
                "env": env,
                "launch_snapshot": launch_snapshot,
            }
        )
    if getattr(args, "with_trade_management", False):
        specs.append(
            {
                "service_name": "trade_management_loop",
                "command": [
                    base,
                    str(BASE_DIR / "trade_management_loop.py"),
                    "--runtime-key",
                    "main",
                    "--interval-seconds",
                    str(max(5, args.trade_management_interval_seconds)),
                ],
                "env": env,
                "launch_snapshot": launch_snapshot,
            }
        )
    if getattr(args, "with_concept_lab", False):
        specs.append(
            {
                "service_name": "concept_lab_loop",
                "command": [
                    base,
                    str(BASE_DIR / "concept_lab_loop.py"),
                    "--state-dir",
                    str(Path(args.state_dir).expanduser()),
                    "--db-path",
                    args.db_path,
                    "--host",
                    args.host,
                    "--port",
                    str(args.port),
                    "--runtime-key",
                    "main",
                    "--interval-seconds",
                    str(max(30, args.concept_lab_interval_seconds)),
                    "--event-limit",
                    "25",
                    "--proposal-limit",
                    "10",
                    "--action-limit",
                    "10",
                    "--scan-limit",
                    "50",
                    "--instruments",
                    "BTCUSDT,ETHUSDT",
                    "--category",
                    "linear",
                    "--max-steps",
                    "12",
                    "--step-stride",
                    "3",
                    "--tradable-only",
                    "--policy-path",
                    str(CONCEPT_DECISION_POLICY_PATH),
                ],
                "env": env,
                "launch_snapshot": launch_snapshot,
            }
        )
    return specs

def discover_service_pids(spec, exclude_pids=None):
    command = spec.get("command") or []
    markers = [item for item in command if isinstance(item, str) and item.endswith(".py")]
    if not markers and command:
        markers = [str(command[-1])]
    excluded = {int(item) for item in (exclude_pids or []) if item}
    try:
        result = subprocess.run(
            ["ps", "-ax", "-o", "pid=,command="],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return []

    discovered = []
    for raw_line in (result.stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        pid_text, _, command_text = line.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid == os.getpid() or pid in excluded:
            continue
        if markers and not all(marker in command_text for marker in markers):
            continue
        if is_process_alive(pid):
            discovered.append(pid)
    return discovered


def start_service(state_dir, manifest, spec):
    service_name = spec["service_name"]
    existing = manifest["services"].get(service_name)
    if existing and is_process_alive(existing.get("pid")):
        return {
            "service_name": service_name,
            "status": "already_running",
            "pid": existing.get("pid"),
            "log_path": existing.get("log_path"),
        }

    discovered_pids = discover_service_pids(spec, exclude_pids=[existing.get("pid")] if existing else [])
    if discovered_pids:
        adopted_pid = discovered_pids[0]
        log_path = service_log_path(state_dir, service_name)
        manifest["services"][service_name] = {
            "service_name": service_name,
            "pid": adopted_pid,
            "started_at": clean_text((existing or {}).get("started_at")) or utc_now_iso(),
            "command": spec["command"],
            "log_path": str(log_path),
            "enabled": True,
            "launch_env": spec.get("launch_snapshot") or {},
            "adopted_at": utc_now_iso(),
            "manifest_pid_drift_recovered": True,
        }
        return {
            "service_name": service_name,
            "status": "adopted_running",
            "pid": adopted_pid,
            "log_path": str(log_path),
            "discovered_pids": discovered_pids,
        }

    log_path = service_log_path(state_dir, service_name)
    log_handle = open(log_path, "a", encoding="utf-8")
    child_env = os.environ.copy()
    child_env.update(spec.get("env") or {})
    process = subprocess.Popen(
        spec["command"],
        cwd=str(BASE_DIR.parent),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=child_env,
        start_new_session=True,
    )
    log_handle.close()
    manifest["services"][service_name] = {
        "service_name": service_name,
        "pid": process.pid,
        "started_at": utc_now_iso(),
        "command": spec["command"],
        "log_path": str(log_path),
        "enabled": True,
        "launch_env": spec.get("launch_snapshot") or {},
    }
    return {
        "service_name": service_name,
        "status": "started",
        "pid": process.pid,
        "log_path": str(log_path),
    }


def terminate_process_group(pid, force_after_seconds):
    if not is_process_alive(pid):
        return "not_running"
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return "not_running"
    deadline = time.time() + max(1, force_after_seconds)
    while time.time() < deadline:
        if not is_process_alive(pid):
            return "stopped"
        time.sleep(0.25)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return "stopped"
    for _ in range(20):
        if not is_process_alive(pid):
            return "killed"
        time.sleep(0.1)
    return "unknown"


def stop_service_processes(record, spec, force_after_seconds):
    manifest_pid = record.get("pid") if isinstance(record, dict) else None
    seen = set()
    manifest_status = "not_running"
    if manifest_pid:
        try:
            seen.add(int(manifest_pid))
        except (TypeError, ValueError):
            pass
        manifest_status = terminate_process_group(manifest_pid, force_after_seconds)

    drift_results = []
    for drift_pid in discover_service_pids(spec, exclude_pids=seen):
        drift_results.append(
            {
                "pid": drift_pid,
                "status": terminate_process_group(drift_pid, force_after_seconds),
            }
        )

    return {
        "manifest_pid": manifest_pid,
        "manifest_status": manifest_status,
        "drift_results": drift_results,
    }


def start_stack(args):
    state_dir = Path(args.state_dir).expanduser()
    ensure_state_dir(state_dir)
    with manifest_lock(state_dir):
        manifest = load_manifest(state_dir)
        planned_specs = build_service_specs(args)
        manifest["launch_context"] = {
            "started_at": utc_now_iso(),
            "env_file": getattr(args, "_env_info", {}),
            "current_env": build_bybit_env_snapshot(getattr(args, "_env_info", {})),
            "db_path": args.db_path,
            "host": args.host,
            "port": args.port,
            "planned_services": [item["service_name"] for item in planned_specs],
        }
        results = []
        for spec in planned_specs:
            results.append(start_service(state_dir, manifest, spec))
        save_manifest(state_dir, manifest)
    return {
        "ok": True,
        "action": "start",
        "state_dir": str(state_dir),
        "db_path": args.db_path,
        "env_file": getattr(args, "_env_info", {}),
        "port": args.port,
        "results": results,
    }


def stop_stack(args):
    state_dir = Path(args.state_dir).expanduser()
    ensure_state_dir(state_dir)
    with manifest_lock(state_dir):
        manifest = load_manifest(state_dir)
        db_path = manifest_db_path(manifest)
        results = []
        for service_name, record in sorted(manifest.get("services", {}).items()):
            stop_report = stop_service_processes(
                record,
                {
                    "service_name": service_name,
                    "command": record.get("command") or [],
                },
                args.force_after_seconds,
            )
            record["stopped_at"] = utc_now_iso()
            record["last_stop_status"] = stop_report["manifest_status"]
            retire_service_runtime_state(db_path, service_name)
            results.append(
                {
                    "service_name": service_name,
                    "pid": stop_report["manifest_pid"],
                    "status": stop_report["manifest_status"],
                    "drift_stops": stop_report["drift_results"],
                }
            )
        save_manifest(state_dir, manifest)
    return {
        "ok": True,
        "action": "stop",
        "state_dir": str(state_dir),
        "env_file": getattr(args, "_env_info", {}),
        "results": results,
    }


def restart_single_service(args):
    state_dir = Path(args.state_dir).expanduser()
    ensure_state_dir(state_dir)
    service_name = clean_text(getattr(args, "service_name", None))
    if service_name is None:
        raise SystemExit("service_name is required for restart-service")

    optional_flag_by_service = {
        "private_stream_loop": "with_private_stream",
        "auto_execute_loop": "with_auto_execution",
        "trade_management_loop": "with_trade_management",
        "concept_lab_loop": "with_concept_lab",
    }
    optional_flag = optional_flag_by_service.get(service_name)
    if optional_flag:
        setattr(args, optional_flag, True)

    spec_by_name = {
        item["service_name"]: item
        for item in build_service_specs(args)
    }
    spec = spec_by_name.get(service_name)
    if spec is None:
        raise SystemExit(f"unsupported or unmanaged service: {service_name}")

    with manifest_lock(state_dir):
        manifest = load_manifest(state_dir)
        existing_planned_services = _planned_services_from_manifest(manifest)
        existing_planned_services.add(service_name)
        manifest["launch_context"] = {
            "started_at": utc_now_iso(),
            "env_file": getattr(args, "_env_info", {}),
            "current_env": build_bybit_env_snapshot(getattr(args, "_env_info", {})),
            "db_path": args.db_path,
            "host": args.host,
            "port": args.port,
            "planned_services": sorted(existing_planned_services),
        }
        record = manifest.get("services", {}).get(service_name) or {}
        stop_report = stop_service_processes(record, spec, args.force_after_seconds)
        manifest["services"].setdefault(service_name, {})
        manifest["services"][service_name]["stopped_at"] = utc_now_iso()
        manifest["services"][service_name]["last_stop_status"] = stop_report["manifest_status"]
        retire_service_runtime_state(args.db_path, service_name)
        if getattr(args, "fresh_log", False):
            log_path = service_log_path(state_dir, service_name)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("", encoding="utf-8")
        start_result = start_service(state_dir, manifest, spec)
        save_manifest(state_dir, manifest)
    return {
        "ok": True,
        "action": "restart-service",
        "state_dir": str(state_dir),
        "env_file": getattr(args, "_env_info", {}),
        "service_name": service_name,
        "fresh_log": bool(getattr(args, "fresh_log", False)),
        "stop": {
            "service_name": service_name,
            "pid": stop_report["manifest_pid"],
            "status": stop_report["manifest_status"],
            "drift_stops": stop_report["drift_results"],
        },
        "start": start_result,
    }


def stack_status(args):
    state_dir = Path(args.state_dir).expanduser()
    ensure_state_dir(state_dir)
    with manifest_lock(state_dir, exclusive=False):
        manifest = load_manifest(state_dir)
    items = []
    for service_name, record in sorted(manifest.get("services", {}).items()):
        pid = record.get("pid")
        drift_pids = discover_service_pids(
            {
                "service_name": service_name,
                "command": record.get("command") or [],
            },
            exclude_pids=[pid] if pid else [],
        )
        items.append(
            {
                "service_name": service_name,
                "pid": pid,
                "alive": is_process_alive(pid),
                "drift_detected": bool(drift_pids),
                "drift_pids": drift_pids,
                "started_at": record.get("started_at"),
                "stopped_at": record.get("stopped_at"),
                "last_stop_status": record.get("last_stop_status"),
                "log_path": record.get("log_path"),
                "command": record.get("command"),
                "launch_env": record.get("launch_env") if isinstance(record.get("launch_env"), dict) else {},
            }
        )
    alive_count = sum(1 for item in items if item["alive"])
    drift_count = sum(1 for item in items if item["drift_detected"])
    return {
        "ok": True,
        "action": "status",
        "state_dir": str(state_dir),
        "env_file": getattr(args, "_env_info", {}),
        "launch_context": manifest.get("launch_context") if isinstance(manifest.get("launch_context"), dict) else {},
        "service_count": len(items),
        "alive_count": alive_count,
        "drift_count": drift_count,
        "items": items,
    }


def print_status_text(result):
    print(f"state_dir={result['state_dir']}")
    print(
        f"services={result['service_count']} alive={result['alive_count']} drift={result.get('drift_count', 0)}"
    )
    for item in result["items"]:
        status = "alive" if item["alive"] else "stopped"
        print(
            f"{item['service_name']} | {status} | pid={item.get('pid')} | "
            f"log={item.get('log_path')}"
        )
        if item.get("drift_detected"):
            print(f"  drift_pids={','.join(str(pid) for pid in item.get('drift_pids') or [])}")


def print_action_text(result):
    print(f"{result['action']} state_dir={result['state_dir']}")
    for item in result["results"]:
        print(
            f"{item['service_name']} | {item['status']}"
            + (f" | pid={item['pid']}" if item.get("pid") else "")
            + (f" | log={item['log_path']}" if item.get("log_path") else "")
        )
        drift_stops = item.get("drift_stops") or []
        if drift_stops:
            summary = ", ".join(
                f"{entry.get('pid')}:{entry.get('status')}" for entry in drift_stops
            )
            print(f"  drift_stops={summary}")


def print_restart_service_text(result):
    print(f"{result['action']} state_dir={result['state_dir']}")
    if result.get("fresh_log"):
        print("fresh_log=true")
    stop = result.get("stop") or {}
    start = result.get("start") or {}
    print(
        f"{result.get('service_name')} | {stop.get('status')}"
        + (f" | old_pid={stop.get('pid')}" if stop.get("pid") else "")
    )
    if stop.get("drift_stops"):
        summary = ", ".join(
            f"{entry.get('pid')}:{entry.get('status')}" for entry in stop.get("drift_stops") or []
        )
        print(f"  drift_stops={summary}")
    print(
        f"{start.get('service_name')} | {start.get('status')}"
        + (f" | pid={start.get('pid')}" if start.get("pid") else "")
        + (f" | log={start.get('log_path')}" if start.get('log_path') else "")
    )


def print_preflight_text(result):
    print(f"preflight overall={result['overall']} state_dir={result['state_dir']}")
    counts = result.get("counts") or {}
    print(
        f"errors={counts.get('error', 0)} warnings={counts.get('warning', 0)} info={counts.get('info', 0)}"
    )
    for item in result.get("issues") or []:
        print(f"{item['severity'].upper()} | {item['code']} | {item['summary']}")


def print_burnin_report_text(result):
    manifest = result.get("manifest") or {}
    print(f"burnin overall={result.get('overall', 'unknown')} state_dir={result.get('state_dir')}")
    print(
        f"services={manifest.get('service_count', 0)} alive={manifest.get('alive_count', 0)} db={result.get('db_path')}"
    )
    if not result.get("ok"):
        print("database_unavailable=true")
        return

    controls = result.get("controls") or []
    if controls:
        print("controls:")
        for item in controls:
            status = "paused" if item.get("paused") else "running"
            line = f"  {item.get('control_key')} | {status}"
            if item.get("reason"):
                line += f" | reason={item['reason']}"
            print(line)

    env_payload = result.get("env") if isinstance(result.get("env"), dict) else {}
    env_comparisons = env_payload.get("comparisons") if isinstance(env_payload.get("comparisons"), dict) else {}
    if env_comparisons:
        print("launch_env:")
        for service_name, comparison in sorted(env_comparisons.items()):
            if not comparison.get("has_snapshot"):
                print(f"  {service_name} | launch snapshot missing")
                continue
            if comparison.get("matches"):
                print(f"  {service_name} | matches current shell env")
                continue
            changed = ",".join(comparison.get("changed_keys") or []) or "-"
            print(f"  {service_name} | differs from current shell env | changed={changed}")

    print("runtimes:")
    for kind, items in (result.get("runtimes") or {}).items():
        if not items:
            print(f"  {kind} | missing")
            continue
        for item in items:
            line = f"  {kind}:{item.get('runtime_key')} | updated={item.get('updated_at')}"
            if item.get("last_scan_at"):
                line += f" | last_scan={item.get('last_scan_at')}"
            if item.get("connection_status"):
                line += f" | status={item.get('connection_status')}"
            if kind == "concept_lab":
                summary = item.get("last_summary") if isinstance(item.get("last_summary"), dict) else {}
                if summary.get("overall"):
                    line += f" | overall={summary.get('overall')}"
                if summary.get("recommendation"):
                    line += f" | recommendation={summary.get('recommendation')}"
                if summary.get("candidate_ratio") is not None:
                    line += f" | candidate_ratio={float(summary.get('candidate_ratio') or 0.0):.0%}"
                if summary.get("dominant_blocker"):
                    line += f" | dominant_blocker={summary.get('dominant_blocker')}"
            print(line)

    recent_events = result.get("recent_events") or []
    if recent_events:
        print("recent_events:")
        for item in recent_events:
            print(
                f"  {item.get('created_at')} | {item.get('source')} | {item.get('severity')} | "
                f"{item.get('event_type')} | {item.get('summary')}"
            )

    recent_proposals = result.get("recent_proposals") or []
    if recent_proposals:
        print("recent_proposals:")
        for item in recent_proposals:
            print(
                f"  {item.get('proposal_id')} | {item.get('symbol')} | {item.get('status')} | "
                f"{item.get('side') or '-'} | qty={item.get('qty') or '-'}"
            )

    recent_actions = result.get("recent_execution_actions") or []
    if recent_actions:
        print("recent_actions:")
        for item in recent_actions:
            print(
                f"  {item.get('action_id')} | {item.get('proposal_id')} | {item.get('action_type')} | "
                f"{item.get('status')} | {item.get('symbol') or '-'}"
            )

    recent_state = result.get("recent_execution_state") or []
    if recent_state:
        print("recent_execution_state:")
        for item in recent_state:
            print(
                f"  {item.get('proposal_id')} | {item.get('symbol')} | sync={item.get('sync_status') or '-'} | "
                f"order={item.get('order_status') or '-'} | pos={item.get('position_side') or '-'} "
                f"size={item.get('position_size') or '-'} | upnl={item.get('unrealised_pnl') or '-'}"
            )

    recent_scans = result.get("recent_scan_history") or []
    if recent_scans:
        print("recent_scan_history:")
        for item in recent_scans:
            print(
                f"  {item.get('scan_id')} | {item.get('instrument')} | {item.get('decision')} | "
                f"session={item.get('session') or '-'} | direction={item.get('direction') or '-'}"
            )

    recent_concept_events = result.get("recent_concept_events") or []
    if recent_concept_events:
        print("recent_concept_events:")
        for item in recent_concept_events:
            print(
                f"  {item.get('created_at')} | {item.get('runtime_key')} | {item.get('severity')} | "
                f"{item.get('event_type')} | {item.get('summary')}"
            )


def print_burnin_gate_text(result):
    print(f"burnin-gate overall={result.get('overall')} state_dir={result.get('state_dir')}")
    counts = result.get("counts") or {}
    print(
        f"errors={counts.get('error', 0)} warnings={counts.get('warning', 0)} info={counts.get('info', 0)}"
    )
    for item in result.get("issues") or []:
        print(f"{item['severity'].upper()} | {item['code']} | {item['summary']}")


def print_wave4_review_text(result):
    print(
        f"wave4-review overall={result.get('overall')} "
        f"burnin={((result.get('burnin_gate') or {}).get('overall') or '-')} "
        f"state_dir={result.get('state_dir')}"
    )
    counts = result.get("counts") or {}
    print(
        f"errors={counts.get('error', 0)} warnings={counts.get('warning', 0)} info={counts.get('info', 0)}"
    )
    for item in result.get("issues") or []:
        print(f"{item['severity'].upper()} | {item['code']} | {item['summary']}")

    summaries = ((result.get("replay_tuning") or {}).get("summaries")) or []
    if summaries:
        print("replay_summaries:")
        include_legacy_metrics = bool(result.get("legacy_compat_metrics_included"))
        for item in summaries:
            top_blockers = item.get("top_blockers") or []
            rendered = ", ".join(
                f"{blocker['blocker']}={blocker['ratio']:.0%}" for blocker in top_blockers[:3]
            ) or "-"
            verified_ratio = float(item.get("verified_trade_ratio") or 0.0)
            line = f"  {item.get('instrument')} | verified_trade_ratio={verified_ratio:.0%}"
            if include_legacy_metrics:
                legacy_ratio = float(item.get("legacy_compat_trade_ratio") or 0.0)
                line += f" | legacy_compat_ratio={legacy_ratio:.0%}"
            line += f" | top_blockers={rendered}"
            print(line)

    next_focus = result.get("next_focus") or []
    if next_focus:
        print("next_focus:")
        for item in next_focus:
            print(f"  - {item}")


def print_promotion_review_text(result):
    print(
        f"promotion-review overall={result.get('overall')} "
        f"recommendation={result.get('recommendation')} "
        f"state_dir={result.get('state_dir')}"
    )
    counts = result.get("counts") or {}
    print(
        f"errors={counts.get('error', 0)} warnings={counts.get('warning', 0)} info={counts.get('info', 0)}"
    )
    for item in result.get("issues") or []:
        print(f"{item['severity'].upper()} | {item['code']} | {item['summary']}")

    if result.get("operator_signal"):
        print(
            f"operator_signal: {result.get('operator_signal')} | "
            f"{result.get('operator_summary') or '-'}"
        )
    dominant = result.get("dominant_blocker") or {}
    if dominant.get("blocker") and float(dominant.get("ratio") or 0.0) > 0.0:
        print(
            f"dominant_blocker: {dominant.get('blocker')}={float(dominant.get('ratio') or 0.0):.0%}"
        )
    if result.get("candidate_ratio") is not None:
        print(f"candidate_ratio: {float(result.get('candidate_ratio') or 0.0):.0%}")

    evidence = result.get("evidence") or {}
    print(
        "evidence: "
        f"scans={evidence.get('recent_scan_count', 0)} "
        f"proposals={evidence.get('recent_proposal_count', 0)} "
        f"actions={evidence.get('recent_action_count', 0)} "
        f"execution_state={evidence.get('recent_execution_state_count', 0)}"
    )

    next_focus = result.get("next_focus") or []
    if next_focus:
        print("next_focus:")
        for item in next_focus:
            print(f"  - {item}")


def print_concept_review_text(result):
    print(
        f"concept-review overall={result.get('overall')} "
        f"recommendation={result.get('recommendation')} "
        f"state_dir={result.get('state_dir')}"
    )
    counts = result.get("counts") or {}
    print(
        f"errors={counts.get('error', 0)} warnings={counts.get('warning', 0)} info={counts.get('info', 0)}"
    )
    for item in result.get("issues") or []:
        print(f"{item['severity'].upper()} | {item['code']} | {item['summary']}")

    if result.get("operator_signal"):
        print(
            f"operator_signal: {result.get('operator_signal')} | "
            f"{result.get('operator_summary') or '-'}"
        )
    dominant = result.get("dominant_blocker") or {}
    if dominant.get("blocker") and float(dominant.get("ratio") or 0.0) > 0.0:
        print(
            f"dominant_blocker: {dominant.get('blocker')}={float(dominant.get('ratio') or 0.0):.0%}"
        )
    if result.get("candidate_ratio") is not None:
        print(f"candidate_ratio: {float(result.get('candidate_ratio') or 0.0):.0%}")

    evidence = result.get("evidence") or {}
    print(
        "evidence: "
        f"scans={evidence.get('recent_scan_count', 0)} "
        f"proposals={evidence.get('recent_proposal_count', 0)} "
        f"actions={evidence.get('recent_action_count', 0)} "
        f"execution_state={evidence.get('recent_execution_state_count', 0)} "
        f"working_orders={evidence.get('working_order_count', 0)} "
        f"open_positions={evidence.get('open_position_count', 0)}"
    )

    sample_window = result.get("sample_window") or {}
    if sample_window.get("started_at"):
        print(
            "sample_window: "
            f"started_at={sample_window.get('started_at')} "
            f"scans={sample_window.get('scan_count', 0)} "
            f"auto_execution_events={sample_window.get('auto_execution_event_count', 0)}"
        )

    scan_mix = result.get("scan_mix") or {}
    if scan_mix:
        rendered = ", ".join(f"{key}={value}" for key, value in sorted(scan_mix.items()))
        print(f"scan_mix: {rendered}")

    execution_mix = result.get("execution_mix") or {}
    if execution_mix:
        rendered = ", ".join(f"{key}={value}" for key, value in sorted(execution_mix.items()))
        print(f"execution_mix: {rendered}")

    auto_execution_blocker_mix = result.get("auto_execution_blocker_mix") or {}
    if auto_execution_blocker_mix:
        rendered = ", ".join(
            f"{AUTO_EXECUTION_CONVERSION_BLOCKER_LABELS.get(key, key)}={value}"
            for key, value in sorted(auto_execution_blocker_mix.items())
        )
        print(f"auto_execution_blockers: {rendered}")

    background_lab = result.get("background_lab") or {}
    if any(value is not None for value in background_lab.values()):
        print(
            "background_lab: "
            f"updated_at={background_lab.get('updated_at') or '-'} "
            f"overall={background_lab.get('overall') or '-'} "
            f"recommendation={background_lab.get('recommendation') or '-'} "
            f"candidate_ratio={float(background_lab.get('candidate_ratio') or 0.0):.0%}"
        )
        if background_lab.get("operator_signal"):
            print(
                f"background_lab_signal: {background_lab.get('operator_signal')} | "
                f"{background_lab.get('operator_summary') or '-'}"
            )
        if background_lab.get("dominant_blocker"):
            print(
                f"background_lab_blocker: {background_lab.get('dominant_blocker')}="
                f"{float(background_lab.get('dominant_blocker_ratio') or 0.0):.0%}"
            )

    background_events = result.get("background_events") or []
    if background_events:
        print("background_events:")
        for item in background_events:
            print(
                f"  {item.get('created_at')} | {item.get('severity')} | "
                f"{item.get('event_type')} | {item.get('summary')}"
            )

    next_focus = result.get("next_focus") or []
    if next_focus:
        print("next_focus:")
        for item in next_focus:
            print(f"  - {item}")


def print_concept_decision_text(result):
    print(
        f"concept-decision overall={result.get('overall')} "
        f"recommendation={result.get('recommendation')} "
        f"state_dir={result.get('state_dir')}"
    )
    counts = result.get("counts") or {}
    print(
        f"errors={counts.get('error', 0)} warnings={counts.get('warning', 0)} info={counts.get('info', 0)}"
    )
    policy = result.get("policy") or {}
    if policy:
        print(
            f"policy concept_id={policy.get('concept_id')} version={policy.get('version')} "
            f"path={result.get('policy_path')}"
        )
    for item in result.get("issues") or []:
        print(f"{item['severity'].upper()} | {item['code']} | {item['summary']}")

    evidence = result.get("evidence") or {}
    unmet = result.get("unmet_evidence") or []
    if evidence:
        rendered = " ".join(
            f"{key}={value}" for key, value in (
                ("scans", evidence.get("recent_scan_count", 0)),
                ("proposals", evidence.get("recent_proposal_count", 0)),
                ("actions", evidence.get("recent_action_count", 0)),
                ("execution_state", evidence.get("recent_execution_state_count", 0)),
            )
        )
        print(f"evidence: {rendered}")
    if unmet:
        rendered = ", ".join(
            f"{item.get('metric')}={item.get('actual')}/{item.get('required')}" for item in unmet
        )
        print(f"unmet_evidence: {rendered}")

    dominant = result.get("dominant_blocker") or {}
    if dominant.get("blocker") and float(dominant.get("ratio") or 0.0) > 0.0:
        print(
            f"dominant_blocker: {dominant.get('blocker')}={float(dominant.get('ratio') or 0.0):.0%}"
        )
    if result.get("candidate_ratio") is not None:
        print(f"candidate_ratio: {float(result.get('candidate_ratio') or 0.0):.0%}")
    if result.get("operator_signal"):
        print(
            f"operator_signal: {result.get('operator_signal')} | "
            f"{result.get('operator_summary') or '-'}"
        )

    next_focus = result.get("next_focus") or []
    if next_focus:
        print("next_focus:")
        for item in next_focus:
            print(f"  - {item}")


def print_concept_brief_text(result):
    print(render_concept_brief_markdown(result))


def print_concept_revision_brief_text(result):
    print(render_concept_revision_brief_markdown(result))


def print_concept_acceptance_brief_text(result):
    print(render_concept_acceptance_brief_markdown(result))


def print_concept_stage7_decision_brief_text(result):
    print(render_concept_stage7_decision_brief_markdown(result))


def print_concept_revision_plan_text(result):
    print(render_concept_revision_plan_markdown(result))


def print_concept_save_review_text(result):
    if not result.get("ok"):
        print(f"concept-save-review ok=false response_file={result.get('response_file')}")
        for item in result.get("errors") or []:
            print(f"ERROR | validation | {item}")
        return

    review = result.get("review_record") or {}
    response = (result.get("validation") or {}).get("response") or {}
    print(
        f"concept-save-review ok=true response_file={result.get('response_file')} "
        f"concept_id={review.get('concept_id')}"
    )
    print(
        f"source={review.get('source')} author={review.get('author') or '-'} "
        f"review_kind={review.get('review_kind')}"
    )
    print(f"review_id={review.get('review_id')} created_at={review.get('created_at')}")
    print(
        f"verdict={response.get('verdict')} next_action={response.get('next_action_type')} "
        f"focus={response.get('next_action_focus')}"
    )
    print(f"summary: {review.get('summary')}")


def print_concept_save_acceptance_review_text(result):
    if not result.get("ok"):
        print(f"concept-save-acceptance-review ok=false response_file={result.get('response_file')}")
        for item in result.get("errors") or []:
            print(f"ERROR | validation | {item}")
        return

    review = result.get("review_record") or {}
    response = (result.get("validation") or {}).get("response") or {}
    print(
        f"concept-save-acceptance-review ok=true response_file={result.get('response_file')} "
        f"concept_id={review.get('concept_id')}"
    )
    print(
        f"source={review.get('source')} author={review.get('author') or '-'} "
        f"review_kind={review.get('review_kind')}"
    )
    print(f"review_id={review.get('review_id')} created_at={review.get('created_at')}")
    print(
        f"verdict={response.get('verdict')} stage6_status={response.get('stage6_status')} "
        f"next_action={response.get('next_action_type')} focus={response.get('next_action_focus')}"
    )
    print(f"summary: {review.get('summary')}")


def print_concept_save_stage7_decision_text(result):
    if not result.get("ok"):
        print(f"concept-save-stage7-decision ok=false response_file={result.get('response_file')}")
        for item in result.get("errors") or []:
            print(f"ERROR | validation | {item}")
        return

    review = result.get("review_record") or {}
    response = (result.get("validation") or {}).get("response") or {}
    print(
        f"concept-save-stage7-decision ok=true response_file={result.get('response_file')} "
        f"concept_id={review.get('concept_id')}"
    )
    print(
        f"source={review.get('source')} author={review.get('author') or '-'} "
        f"review_kind={review.get('review_kind')}"
    )
    print(f"review_id={review.get('review_id')} created_at={review.get('created_at')}")
    print(
        f"verdict={response.get('verdict')} stage7_readiness={response.get('stage7_readiness')} "
        f"next_action={response.get('next_action_type')} focus={response.get('next_action_focus')}"
    )
    print(f"summary: {review.get('summary')}")


def print_concept_save_revision_compare_text(result):
    if not result.get("ok"):
        print(
            f"concept-save-revision-compare ok=false response_file={result.get('response_file')}"
        )
        for item in result.get("errors") or []:
            print(f"ERROR | validation | {item}")
        return

    review = result.get("review_record") or {}
    response = (result.get("validation") or {}).get("response") or {}
    print(
        f"concept-save-revision-compare ok=true response_file={result.get('response_file')} "
        f"concept_id={review.get('concept_id')}"
    )
    print(
        f"source={review.get('source')} author={review.get('author') or '-'} "
        f"review_kind={review.get('review_kind')}"
    )
    print(f"review_id={review.get('review_id')} created_at={review.get('created_at')}")
    print(
        f"verdict={response.get('verdict')} leader={response.get('leader_revision_id')} "
        f"next_action={response.get('next_action_type')}"
    )
    if response.get("challenger_revision_id"):
        print(f"challenger={response.get('challenger_revision_id')}")
    print(f"summary: {review.get('summary')}")


def print_concept_promote_review_text(result):
    if not result.get("ok"):
        print(f"concept-promote-review ok=false review_id={result.get('review_id') or '-'}")
        print(f"ERROR | promote | {result.get('error') or 'unknown error'}")
        return

    review = result.get("review_record") or {}
    revision = result.get("revision_record") or {}
    linked = revision.get("linked_review_guidance") or {}
    print(
        f"concept-promote-review ok=true review_id={review.get('review_id')} "
        f"revision_id={revision.get('revision_id')} concept_id={revision.get('concept_id')}"
    )
    print(
        f"source={revision.get('source')} author={revision.get('author') or '-'} "
        f"focus={revision.get('focus') or '-'} mode={revision.get('mode') or '-'}"
    )
    print(f"title: {revision.get('title') or '-'}")
    print(f"summary: {revision.get('summary') or '-'}")
    if linked:
        print(
            f"linked_review verdict={linked.get('verdict') or '-'} "
            f"next_action={linked.get('next_action_type') or '-'} "
            f"confidence={linked.get('confidence') or '-'}"
        )


def print_concept_evaluate_review_text(result):
    if not result.get("ok"):
        print(f"concept-evaluate-review ok=false review_id={result.get('review_id') or '-'}")
        print(f"ERROR | evaluate | {result.get('error') or 'unknown error'}")
        return

    review = result.get("review_record") or {}
    revision = result.get("revision_record") or {}
    evaluation = result.get("evaluation") or {}
    print(
        f"concept-evaluate-review ok=true review_id={review.get('review_id')} "
        f"revision_id={revision.get('revision_id')} status={evaluation.get('status') or '-'}"
    )
    print(f"summary: {evaluation.get('summary') or '-'}")
    print(
        f"fresh_sample_ready={evaluation.get('fresh_sample_ready')} "
        f"baseline_sample_started_at={evaluation.get('baseline_sample_started_at') or '-'} "
        f"current_sample_started_at={evaluation.get('current_sample_started_at') or '-'}"
    )
    deltas = evaluation.get("deltas") or {}
    print(
        f"deltas candidate_ratio={deltas.get('candidate_ratio_delta')} "
        f"blocker_ratio={deltas.get('dominant_blocker_ratio_delta')} "
        f"gap={deltas.get('cross_market_gap_delta')} "
        f"proposals={deltas.get('recent_proposal_delta')} "
        f"execution_state={deltas.get('recent_execution_state_delta')}"
    )
    history = result.get("history") or {}
    print(
        f"history updated={history.get('updated')} replaced={history.get('replaced')} "
        f"count={history.get('count')} key={history.get('key') or '-'}"
    )


def print_bybit_doctor_text(result):
    print(f"bybit-doctor overall={result.get('overall')} state_dir={result.get('state_dir')}")
    counts = result.get("counts") or {}
    print(
        f"errors={counts.get('error', 0)} warnings={counts.get('warning', 0)} info={counts.get('info', 0)}"
    )
    env_sources = result.get("env_sources") or {}
    if env_sources:
        print(
            f"env_sources BYBIT_ENV={env_sources.get('BYBIT_ENV')} "
            f"BYBIT_API_KEY={env_sources.get('BYBIT_API_KEY')} "
            f"BYBIT_API_SECRET={env_sources.get('BYBIT_API_SECRET')} "
            f"BYBIT_ENABLE_TESTNET_SUBMIT={env_sources.get('BYBIT_ENABLE_TESTNET_SUBMIT')}"
        )
    for item in result.get("issues") or []:
        print(f"{item['severity'].upper()} | {item['code']} | {item['summary']}")
    api_probe = result.get("api_probe") or {}
    if api_probe:
        print(
            f"api_probe attempted={api_probe.get('attempted')} ok={api_probe.get('ok')} "
            f"read_only={api_probe.get('read_only')} uta={api_probe.get('uta')}"
        )
        diagnosis = api_probe.get("diagnosis") if isinstance(api_probe.get("diagnosis"), dict) else {}
        if diagnosis.get("summary"):
            print(f"api_probe_diagnosis {diagnosis.get('code')} | {diagnosis.get('summary')}")
        if api_probe.get("ret_code") is not None or api_probe.get("ret_msg") or api_probe.get("error"):
            print(
                f"api_probe_detail http_status={api_probe.get('http_status')} ret_code={api_probe.get('ret_code')} "
                f"ret_msg={api_probe.get('ret_msg') or '-'} error={api_probe.get('error') or '-'}"
            )
    probe = result.get("probe") or {}
    if probe:
        print(
            f"wallet_probe attempted={probe.get('attempted')} ok={probe.get('ok')} "
            f"account_type={probe.get('account_type')} balance_coin={probe.get('balance_coin')}"
        )
        diagnosis = probe.get("diagnosis") if isinstance(probe.get("diagnosis"), dict) else {}
        if diagnosis.get("summary"):
            print(f"wallet_probe_diagnosis {diagnosis.get('code')} | {diagnosis.get('summary')}")
        if probe.get("ret_code") is not None or probe.get("ret_msg") or probe.get("error"):
            print(
                f"wallet_probe_detail http_status={probe.get('http_status')} ret_code={probe.get('ret_code')} "
                f"ret_msg={probe.get('ret_msg') or '-'} error={probe.get('error') or '-'}"
            )


def print_env_debug_text(result):
    print(f"env-debug state_dir={result.get('state_dir')}")
    env_info = result.get("env_file") or {}
    if env_info.get("disabled"):
        print("env_file disabled=true")
    elif env_info.get("loaded"):
        print(
            f"env_file loaded=true path={env_info.get('path')} entries={env_info.get('entries')} "
            f"skipped_existing={env_info.get('skipped_existing')} override={env_info.get('override')}"
        )
    elif env_info.get("path"):
        print(f"env_file loaded=false path={env_info.get('path')}")
    for name, item in (result.get("variables") or {}).items():
        if name == "BYBIT_ENV":
            print(
                f"{name} | source={item.get('source')} | present={item.get('present')} | "
                f"raw={item.get('raw_value') or '-'} | normalized={item.get('normalized_value') or '-'}"
            )
        elif name == "BYBIT_ENABLE_TESTNET_SUBMIT":
            print(
                f"{name} | source={item.get('source')} | present={item.get('present')} | "
                f"raw={item.get('raw_value') or '-'} | normalized_true={item.get('normalized_true')}"
            )
        else:
            print(
                f"{name} | source={item.get('source')} | present={item.get('present')} | "
                f"length={item.get('length')} | sha256_prefix={item.get('sha256_prefix') or '-'}"
            )


def arm_testnet(args):
    args.with_private_stream = True
    args.with_auto_execution = True
    args.with_trade_management = True
    preflight_result = preflight_stack(args)
    if preflight_result.get("overall") != "ready":
        return {
            "ok": False,
            "action": "arm-testnet",
            "status": "blocked",
            "preflight": preflight_result,
            "start": None,
        }
    start_result = start_stack(args)
    return {
        "ok": True,
        "action": "arm-testnet",
        "status": "started",
        "preflight": preflight_result,
        "start": start_result,
    }


def main():
    args = parse_args()
    args._env_info = load_env_file_into_process(
        args.env_file,
        override=bool(getattr(args, "env_file_override", False)),
        disabled=bool(getattr(args, "no_env_file", False)),
    )
    if args.command == "start":
        result = start_stack(args)
        print_action_text(result)
        return
    if args.command == "stop":
        result = stop_stack(args)
        print_action_text(result)
        return
    if args.command == "restart-service":
        result = restart_single_service(args)
        print_restart_service_text(result)
        return
    if args.command == "status":
        result = stack_status(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_status_text(result)
        return
    if args.command == "preflight":
        result = preflight_stack(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_preflight_text(result)
        return
    if args.command == "arm-testnet":
        result = arm_testnet(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_preflight_text(result["preflight"])
            if result["start"] is not None:
                print_action_text(result["start"])
        if not result["ok"]:
            raise SystemExit(2)
        return
    if args.command == "burnin-report":
        result = burnin_report(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_burnin_report_text(result)
        if not result.get("ok"):
            raise SystemExit(2)
        return
    if args.command == "burnin-gate":
        result = burnin_gate(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_burnin_gate_text(result)
        if result.get("overall") == "blocked":
            raise SystemExit(2)
        return
    if args.command == "wave4-review":
        result = wave4_review(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_wave4_review_text(result)
        if result.get("overall") == "blocked":
            raise SystemExit(2)
        return
    if args.command == "promotion-review":
        result = promotion_review(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_promotion_review_text(result)
        if result.get("overall") == "blocked":
            raise SystemExit(2)
        return
    if args.command == "concept-review":
        result = concept_review(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_concept_review_text(result)
        if result.get("overall") == "blocked":
            raise SystemExit(2)
        return
    if args.command == "concept-decision":
        result = concept_decision(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_concept_decision_text(result)
        if result.get("overall") == "blocked":
            raise SystemExit(2)
        return
    if args.command == "concept-brief":
        result = concept_brief(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_concept_brief_text(result)
        if (result.get("decision") or {}).get("overall") == "blocked":
            raise SystemExit(2)
        return
    if args.command == "concept-revision-brief":
        result = concept_revision_brief(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_concept_revision_brief_text(result)
        if (result.get("decision") or {}).get("overall") == "blocked":
            raise SystemExit(2)
        return
    if args.command == "concept-acceptance-brief":
        result = concept_acceptance_brief(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_concept_acceptance_brief_text(result)
        if (result.get("decision") or {}).get("overall") == "blocked":
            raise SystemExit(2)
        return
    if args.command == "concept-stage7-decision-brief":
        result = concept_stage7_decision_brief(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_concept_stage7_decision_brief_text(result)
        return
    if args.command == "concept-revision-plan":
        result = concept_revision_plan(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_concept_revision_plan_text(result)
        return
    if args.command == "concept-save-review":
        result = concept_save_review(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_concept_save_review_text(result)
        if not result.get("ok"):
            raise SystemExit(2)
        return
    if args.command == "concept-save-acceptance-review":
        result = concept_save_acceptance_review(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_concept_save_acceptance_review_text(result)
        if not result.get("ok"):
            raise SystemExit(2)
        return
    if args.command == "concept-save-stage7-decision":
        result = concept_save_stage7_decision(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_concept_save_stage7_decision_text(result)
        if not result.get("ok"):
            raise SystemExit(2)
        return
    if args.command == "concept-save-revision-compare":
        result = concept_save_revision_compare(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_concept_save_revision_compare_text(result)
        if not result.get("ok"):
            raise SystemExit(2)
        return
    if args.command == "concept-promote-review":
        result = concept_promote_review(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_concept_promote_review_text(result)
        if not result.get("ok"):
            raise SystemExit(2)
        return
    if args.command == "concept-evaluate-review":
        result = concept_evaluate_review(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_concept_evaluate_review_text(result)
        if not result.get("ok"):
            raise SystemExit(2)
        return
    if args.command == "bybit-doctor":
        result = bybit_doctor(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_bybit_doctor_text(result)
        if result.get("overall") == "blocked":
            raise SystemExit(2)
        return
    if args.command == "env-debug":
        result = env_debug(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_env_debug_text(result)
        return
    if args.command == "restart":
        stop_result = stop_stack(args)
        start_result = start_stack(args)
        print_action_text(stop_result)
        print_action_text(start_result)
        return
    raise SystemExit(f"unsupported command: {args.command}")


if __name__ == "__main__":
    main()
