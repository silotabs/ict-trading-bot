#!/usr/bin/env python3

import json
import os
import re
import sqlite3
import sys
import threading
import time
import hmac
import hashlib
import math
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import parse_qs, urlencode, urlparse
from zoneinfo import ZoneInfo

from concept_briefing import build_concept_brief_packet
from concept_acceptance_response import (
    build_structured_acceptance_record,
    validate_acceptance_response,
)
from concept_stage7_decision_response import (
    build_structured_stage7_decision_record,
    validate_stage7_decision_response,
)
from concept_stage7_decision_briefing import summarize_stage7_decision
from concept_stage_status import build_concept_stage_status
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
    summarize_concept_revision_loop,
)
from ict_engine.context import summarize_context_state, summarize_narrative_state as summarize_narrative_engine
from ict_engine.drt import (
    classify_range_location,
    detect_4h_liquidity_event as detect_4h_liquidity_event_engine,
    infer_4h_bias,
    summarize_4h_drt_state,
    summarize_dealing_range,
)
from ict_engine.execution import (
    detect_recent_displacement_5m as detect_recent_displacement_5m_engine,
    detect_recent_fvg_5m,
    detect_recent_mss_15m as detect_recent_mss_15m_engine,
    detect_recent_mss_5m as detect_recent_mss_5m_engine,
    detect_recent_sweep_15m as detect_recent_sweep_15m_engine,
)
from ict_engine.execution_state_machine import (
    build_execution_intent_key,
    decision_allows_execution_intent,
    execution_intent_is_terminal,
    map_sync_lifecycle_to_intent_state,
    normalize_execution_intent_state,
    transition_validation_error,
)
from ict_engine.evaluation import (
    decision_allows_execution_plan,
    evaluate_payload as evaluate_payload_engine,
    normalize_checklist_payload as normalize_checklist_payload_engine,
)
from ict_engine.liquidity import build_liquidity_map
from ict_engine.opportunity import summarize_opportunity_state
from ict_engine.pd_arrays import summarize_execution_pd_arrays
from ict_engine.risk_controls import evaluate_execution_risk
from ict_engine.signal_trace import build_signal_trace as build_signal_trace_engine
from ict_engine.visual import derive_visual_analysis_state
from runtime_config import (
    load_auto_execution_policy as load_auto_execution_policy_runtime,
    load_execution_spec as load_execution_spec_runtime,
    load_liquidity_context_policy as load_liquidity_context_policy_runtime,
    load_risk_control_policy as load_risk_control_policy_runtime,
    load_trade_management_policy as load_trade_management_policy_runtime,
)
from runtime_health import (
    RuntimeHealthDependencies,
    build_health_payload as build_health_payload_runtime,
    build_operations_status as build_operations_status_runtime,
    build_readiness_payload as build_readiness_payload_runtime,
)
from bybit_client import (
    BYBIT_API_KEY,
    BYBIT_API_SECRET,
    BYBIT_ENABLE_PRIVATE_SUBMIT,
    BYBIT_ENABLE_TESTNET_SUBMIT,
    BYBIT_ENV,
    BYBIT_LEVERAGE_PATH,
    BYBIT_MARKET_BASE_URL,
    BYBIT_ORDER_AMEND_PATH,
    BYBIT_ORDER_CANCEL_PATH,
    BYBIT_ORDER_CREATE_PATH,
    BYBIT_PRIVATE_BASE_URL,
    BYBIT_QUERY_API_KEY_PATH,
    BYBIT_TRADING_STOP_PATH,
    BYBIT_WALLET_BALANCE_PATH,
    bybit_post,
    bybit_public_get,
    extract_bybit_instrument_constraints,
    fetch_bybit_api_key_information,
    fetch_bybit_instrument,
    fetch_bybit_klines,
    fetch_bybit_order_realtime,
    fetch_bybit_positions,
    fetch_bybit_ticker,
    fetch_bybit_wallet_balance,
)
from runtime_paths import STACK_MANIFEST_NAME, default_db_path, default_stack_state_dir
from runtime_repositories import build_runtime_repositories
from shared_utils import age_seconds_from_iso, clean_string, coerce_bool, parse_iso_datetime, utc_now_iso
import trading_store as trading_store_module
from trading_store import PaperTradeStore
from trading_utils import (
    build_order_link_id,
    decimal_string,
    first_present,
    median_value,
    normalize_control_key,
    normalize_instrument,
    render_decimal,
    round_to_increment,
    string_list,
    to_decimal,
    to_float,
    utc_now_ms,
)


trading_store_module.utc_now_iso = lambda: utc_now_iso()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = default_db_path()
EXECUTION_SPEC_PATH = BASE_DIR / "config" / "execution_spec.json"
AUTO_EXECUTION_POLICY_PATH = BASE_DIR / "config" / "auto_execution_policy.json"
TRADE_MANAGEMENT_POLICY_PATH = BASE_DIR / "config" / "trade_management_policy.json"
RISK_CONTROL_POLICY_PATH = BASE_DIR / "config" / "risk_control_policy.json"
LIQUIDITY_CONTEXT_POLICY_PATH = BASE_DIR / "config" / "liquidity_context_policy.json"
HOST = os.environ.get("TRADING_API_HOST", "127.0.0.1")
PORT = int(os.environ.get("TRADING_API_PORT", "8787"))
TRADINGVIEW_WEBHOOK_SECRET = os.environ.get("TRADINGVIEW_WEBHOOK_SECRET", "")
TRADING_API_OPERATOR_TOKEN = clean_string(os.environ.get("TRADING_API_OPERATOR_TOKEN")) or ""
OPERATOR_AUTH_TOKEN_HEADER = "X-Trading-Operator-Token"
OPERATOR_AUTHORIZATION_SCHEME = "Bearer"
OPERATOR_AUTH_EXACT_POST_PATHS = {"/v1/control/state", "/v1/control/kill-switch", "/v1/execution/plan"}
OPERATOR_AUTH_ORDER_PROPOSAL_SUFFIXES = {"/submit", "/cancel", "/amend", "/refresh-trading-stop", "/close-position"}


def current_stack_state_dir():
    return default_stack_state_dir()


def current_planned_services():
    manifest_path = current_stack_state_dir() / STACK_MANIFEST_NAME
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    launch_context = payload.get("launch_context") if isinstance(payload.get("launch_context"), dict) else {}
    planned_services = launch_context.get("planned_services") if isinstance(launch_context.get("planned_services"), list) else []
    normalized = {
        clean_string(item)
        for item in planned_services
        if clean_string(item)
    }
    return normalized or None


def parse_allowed_sessions_env(raw_value):
    aliases = {
        "newyork": "new_york",
        "new-york": "new_york",
        "new york": "new_york",
    }
    allowed_values = {"outside", "london", "new_york", "sydney", "tokyo"}
    default_sessions = ["london", "new_york"]
    if clean_string(raw_value) is None:
        return list(default_sessions)

    sessions = []
    for item in str(raw_value).split(','):
        normalized = clean_string(item)
        if normalized is None:
            continue
        normalized = aliases.get(normalized.lower(), normalized.lower().replace('-', '_').replace(' ', '_'))
        if normalized in allowed_values and normalized not in sessions:
            sessions.append(normalized)
    return sessions or list(default_sessions)


def operator_auth_required(method, path):
    normalized_method = clean_string(method) or "GET"
    normalized_method = normalized_method.upper()
    normalized_path = str(path or "").strip() or "/"
    normalized_path = normalized_path.rstrip("/") or "/"
    if normalized_method != "POST":
        return False
    if normalized_path in OPERATOR_AUTH_EXACT_POST_PATHS:
        return True
    if normalized_path.startswith("/v1/order-proposals/"):
        return any(normalized_path.endswith(suffix) for suffix in OPERATOR_AUTH_ORDER_PROPOSAL_SUFFIXES)
    return False


def _header_value(headers, name):
    getter = getattr(headers, "get", None)
    if callable(getter):
        return clean_string(getter(name))
    if isinstance(headers, dict):
        return clean_string(headers.get(name))
    return None


def extract_operator_auth_token(headers):
    direct = _header_value(headers, OPERATOR_AUTH_TOKEN_HEADER)
    if direct:
        return direct
    authorization = _header_value(headers, "Authorization")
    if not authorization:
        return None
    prefix = f"{OPERATOR_AUTHORIZATION_SCHEME} "
    if authorization.startswith(prefix):
        return clean_string(authorization[len(prefix) :])
    return None


def _operator_auth_request_details(method, path):
    return {
        "header": OPERATOR_AUTH_TOKEN_HEADER,
        "authorization_scheme": OPERATOR_AUTHORIZATION_SCHEME,
        "path": (str(path or "").rstrip("/") or "/"),
        "method": (clean_string(method) or "GET").upper(),
    }


def validate_operator_request_auth(headers, *, method, path, configured_token=None, private_submit_enabled=None):
    token = clean_string(configured_token if configured_token is not None else TRADING_API_OPERATOR_TOKEN) or ""
    submit_enabled = BYBIT_ENABLE_PRIVATE_SUBMIT if private_submit_enabled is None else bool(private_submit_enabled)
    required = operator_auth_required(method, path)
    if not required:
        return {
            "ok": True,
            "required": False,
            "enabled": bool(token),
            "status_code": 200,
            "error": None,
        }

    if not token:
        if submit_enabled:
            return {
                "ok": False,
                "required": True,
                "enabled": False,
                "status_code": 503,
                "error": "operator auth token required while private submission is enabled",
                "details": _operator_auth_request_details(method, path),
            }
        return {
            "ok": True,
            "required": False,
            "enabled": False,
            "status_code": 200,
            "error": None,
        }

    provided_token = extract_operator_auth_token(headers)
    if provided_token == token:
        return {
            "ok": True,
            "required": True,
            "enabled": True,
            "status_code": 200,
            "error": None,
        }

    return {
        "ok": False,
        "required": True,
        "enabled": True,
        "status_code": 401,
        "error": "operator auth required",
        "details": _operator_auth_request_details(method, path),
    }


RULES = {
    "strategy_version": "ict-drt-narrative-v1",
    "execution_mode": "analysis plus manual paper-trade simulation",
    "allowed_instruments": ["BTCUSDT", "ETHUSDT"],
    "approved_proxies": ["BTCUSD", "ETHUSD"],
    "timeframes": {
        "bias": "4H",
        "setup": "15m",
        "execution": "5m",
    },
    "allowed_sessions": parse_allowed_sessions_env(os.environ.get("TRADING_ALLOWED_SESSIONS")),
    "weekend_policy": "allowed_with_lower_confidence",
    "required_checklist": [
        "clear_4h_bias",
        "clear_liquidity_draw",
        "liquidity_event",
        "mss",
        "displacement",
        "fresh_fvg",
        "clear_invalidation",
        "clear_target",
    ],
    "blocking_conditions": [
        "unsupported instrument",
        "invalid timeframe stack",
        "outside allowed session windows",
        "chase entry",
        "missing narrative confirmation or 5m execution leg",
    ],
}

HEURISTIC_RULES = {
    "sweep_15m": {
        "profiles": [
            {
                "name": "external",
                "lookback": 20,
                "search_bars": 6,
                "reclaim_bars": 2,
                "close_tolerance_fraction": 0.12,
            },
            {
                "name": "internal",
                "lookback": 12,
                "search_bars": 8,
                "reclaim_bars": 3,
                "close_tolerance_fraction": 0.15,
            },
            {
                "name": "micro_internal",
                "lookback": 8,
                "search_bars": 10,
                "reclaim_bars": 4,
                "close_tolerance_fraction": 0.18,
            },
        ],
    },
    "mss_15m": {
        "sample_size": 24,
        "break_confirm_bars": 3,
        "level_tolerance_fraction": 0.12,
        "micro_break_lookback": 3,
        "micro_break_search_bars": 6,
        "micro_break_follow_through_bars": 2,
    },
    "mss_5m": {
        "sample_size": 24,
        "break_confirm_bars": 4,
        "level_tolerance_fraction": 0.15,
        "micro_break_lookback": 4,
        "micro_break_search_bars": 8,
        "micro_break_follow_through_bars": 3,
    },
    "displacement_5m": {
        "search_bars": 6,
        "range_multiple": 1.6,
        "body_multiple": 1.35,
        "body_fraction": 0.48,
        "sequence_range_multiple": 2.15,
        "sequence_body_multiple": 1.9,
        "sequence_body_fraction": 0.5,
        "fvg_break_lookback": 5,
        "fvg_min_gap_range_fraction": 0.12,
        "fvg_sequence_body_multiple": 1.15,
    },
}

CONTROL_ROOM_DEFAULTS = {
    "scan_limit": 50,
    "proposal_limit": 8,
    "execution_limit": 8,
    "execution_action_limit": 12,
    "auto_event_limit": 12,
    "concept_event_limit": 8,
    "timeline_limit": 24,
}
CONTROL_ROOM_STREAM_POLL_SECONDS = 6.0

SUPERVISOR_ACTIVE_PROPOSAL_STATUSES = {"ready_for_submission", "submitted_testnet"}
SUPERVISOR_ACTIVE_EXECUTION_STATUSES = {
    "planned",
    "submitted",
    "working",
    "partially_filled",
    "position_open",
    "filled",
    "unknown",
}

SESSION_ALIASES = {
    "new york": "new_york",
    "new_york": "new_york",
    "ny": "new_york",
    "london": "london",
    "ldn": "london",
    "sydney": "sydney",
    "syd": "sydney",
    "tokyo": "tokyo",
    "tky": "tokyo",
    "outside": "outside",
}

TIMEFRAME_ALIASES = {
    "4h": "4H",
    "240": "4H",
    "240m": "4H",
    "15m": "15m",
    "15": "15m",
    "5m": "5m",
    "5": "5m",
}

DIRECTION_ALIASES = {
    "buy": "long",
    "long": "long",
    "bull": "long",
    "bullish": "long",
    "sell": "short",
    "short": "short",
    "bear": "short",
    "bearish": "short",
}

ORDER_TYPE_ALIASES = {
    "limit": "Limit",
    "market": "Market",
}

TIME_IN_FORCE_ALIASES = {
    "gtc": "GTC",
    "ioc": "IOC",
    "fok": "FOK",
    "postonly": "PostOnly",
    "post_only": "PostOnly",
}

TRIGGER_BY_ALIASES = {
    "lastprice": "LastPrice",
    "last_price": "LastPrice",
    "markprice": "MarkPrice",
    "mark_price": "MarkPrice",
    "indexprice": "IndexPrice",
    "index_price": "IndexPrice",
}

LINEAR_SYMBOLS = {"BTCUSDT", "ETHUSDT"}
INVERSE_SYMBOLS = {"BTCUSD", "ETHUSD"}
LINEAR_PROXY_MAP = {
    "BTCUSD": "BTCUSDT",
    "ETHUSD": "ETHUSDT",
}
INVERSE_PROXY_MAP = {
    "BTCUSDT": "BTCUSD",
    "ETHUSDT": "ETHUSD",
}
BYBIT_INTERVAL_MAP = {
    "4H": "240",
    "15m": "15",
    "5m": "5",
}
BYBIT_INTERVAL_MINUTES = {
    "240": 240,
    "15": 15,
    "5": 5,
}
NEW_YORK_TZ = ZoneInfo("America/New_York")
OPERATIONS_DEFAULT_THRESHOLDS = {
    "watchlist_stale_after_seconds": 900,
    "supervisor_stale_after_seconds": 180,
    "private_stream_stale_after_seconds": 90,
    "auto_execution_stale_after_seconds": 180,
    "trade_management_stale_after_seconds": 180,
}


def resolve_control_state(control_key):
    control_key = normalize_control_key(control_key)
    global_record = TradingAPIHandler.store.get_control_state("global")
    specific_record = None if control_key == "global" else TradingAPIHandler.store.get_control_state(control_key)

    paused_records = []
    for record in (global_record, specific_record):
        if isinstance(record, dict) and record.get("paused"):
            paused_records.append(record)

    updated_candidates = [
        clean_string(record.get("updated_at"))
        for record in (specific_record, global_record)
        if isinstance(record, dict) and clean_string(record.get("updated_at"))
    ]
    reasons = [
        clean_string(record.get("reason"))
        for record in paused_records
        if clean_string(record.get("reason"))
    ]

    return {
        "control_key": control_key,
        "effective_paused": bool(paused_records),
        "effective_reason": "; ".join(reasons) if reasons else None,
        "updated_at": max(updated_candidates) if updated_candidates else None,
        "global": global_record,
        "specific": specific_record,
    }


def normalize_session(value):
    raw = clean_string(value)
    if not raw:
        return ""
    session = raw.lower().replace("-", "_")
    return SESSION_ALIASES.get(session, session)


def normalize_direction(value):
    raw = clean_string(value)
    if not raw:
        return ""
    return DIRECTION_ALIASES.get(raw.lower(), "")


def normalize_timeframe(value):
    raw = clean_string(value)
    if not raw:
        return ""
    normalized = raw.lower().replace(" ", "")
    return TIMEFRAME_ALIASES.get(normalized, raw)


def normalize_order_type(value):
    raw = clean_string(value)
    if not raw:
        return ""
    return ORDER_TYPE_ALIASES.get(raw.lower(), raw)


def normalize_time_in_force(value):
    raw = clean_string(value)
    if not raw:
        return ""
    normalized = raw.replace("-", "_").lower()
    return TIME_IN_FORCE_ALIASES.get(normalized, raw.upper())


def normalize_trigger_by(value):
    raw = clean_string(value)
    if not raw:
        return ""
    normalized = raw.replace("-", "_").lower()
    return TRIGGER_BY_ALIASES.get(normalized, raw)




























def session_context_at(reference=None):
    if isinstance(reference, (int, float)):
        now_utc = datetime.fromtimestamp(reference / 1000, tz=timezone.utc)
    elif isinstance(reference, datetime):
        now_utc = reference.astimezone(timezone.utc)
    else:
        now_utc = datetime.now(timezone.utc)
    now_ny = now_utc.astimezone(NEW_YORK_TZ)
    minute_of_day = now_ny.hour * 60 + now_ny.minute

    if 2 * 60 <= minute_of_day < 5 * 60:
        active_session = "london"
    elif 7 * 60 <= minute_of_day < 10 * 60:
        active_session = "new_york"
    else:
        active_session = "outside"

    return {
        "now_utc": now_utc.replace(microsecond=0).isoformat(),
        "now_new_york": now_ny.replace(microsecond=0).isoformat(),
        "active_session": active_session,
        "session_valid": active_session in RULES["allowed_sessions"],
        "weekend": now_utc.weekday() >= 5,
    }


def session_context_now():
    return session_context_at()




def get_runtime_repositories(store=None):
    return build_runtime_repositories(store or TradingAPIHandler.store)


def build_runtime_health_dependencies(store=None, active_service_names=None):
    target_store = store or TradingAPIHandler.store
    if active_service_names is None and store is None:
        active_service_names = current_planned_services()
    return RuntimeHealthDependencies(
        repositories=get_runtime_repositories(target_store),
        resolve_control_state=resolve_control_state,
        normalize_instrument=normalize_instrument,
        age_seconds_from_iso=age_seconds_from_iso,
        clean_string=clean_string,
        coerce_bool=coerce_bool,
        first_present=first_present,
        rules=RULES,
        thresholds=OPERATIONS_DEFAULT_THRESHOLDS,
        load_auto_execution_policy=load_auto_execution_policy,
        load_trade_management_policy=load_trade_management_policy,
        strategy_version=RULES["strategy_version"],
        db_path=str(DB_PATH),
        tradingview_webhook_secret_configured=bool(TRADINGVIEW_WEBHOOK_SECRET),
        bybit_env=BYBIT_ENV,
        bybit_market_base_url=BYBIT_MARKET_BASE_URL,
        bybit_private_base_url=BYBIT_PRIVATE_BASE_URL,
        bybit_private_submit_enabled=BYBIT_ENABLE_PRIVATE_SUBMIT,
        bybit_testnet_base_url=BYBIT_PRIVATE_BASE_URL,
        bybit_testnet_submit_enabled=BYBIT_ENABLE_TESTNET_SUBMIT,
        bybit_credentials_configured=bool(BYBIT_API_KEY and BYBIT_API_SECRET),
        operator_auth_configured=bool(TRADING_API_OPERATOR_TOKEN),
        active_service_names=active_service_names,
    )


def build_operations_status(
    watchlist_stale_after_seconds=None,
    supervisor_stale_after_seconds=None,
    private_stream_stale_after_seconds=None,
    public_market_stale_after_seconds=None,
    auto_execution_stale_after_seconds=None,
    trade_management_stale_after_seconds=None,
):
    return build_operations_status_runtime(
        build_runtime_health_dependencies(),
        watchlist_stale_after_seconds=watchlist_stale_after_seconds,
        supervisor_stale_after_seconds=supervisor_stale_after_seconds,
        private_stream_stale_after_seconds=private_stream_stale_after_seconds,
        public_market_stale_after_seconds=public_market_stale_after_seconds,
        auto_execution_stale_after_seconds=auto_execution_stale_after_seconds,
        trade_management_stale_after_seconds=trade_management_stale_after_seconds,
    )


def coerce_query_limit(raw_value, default, minimum=1, maximum=1000):
    if raw_value is None:
        return default
    try:
        return max(minimum, min(maximum, int(raw_value)))
    except (TypeError, ValueError):
        return default


def build_health_payload():
    return build_health_payload_runtime(build_runtime_health_dependencies())


def build_readiness_payload():
    return build_readiness_payload_runtime(build_runtime_health_dependencies())


def readiness_http_status(readiness):
    payload = readiness if isinstance(readiness, dict) else {}
    status = clean_string(payload.get("status")) or "not_ready"
    return 200 if status in {"healthy_primary", "degraded_fallback"} else 503


def build_controls_snapshot():
    items = TradingAPIHandler.store.list_control_state()
    for item in items:
        item["effective"] = resolve_control_state(item["control_key"])
    return items


def build_ticker_snapshot(symbols):
    items = []
    errors = []
    for symbol in symbols:
        result = fetch_bybit_ticker(symbol)
        if result.get("ok") and isinstance(result.get("ticker"), dict):
            items.append(
                {
                    "source": "bybit",
                    "instrument": symbol,
                    "category": "linear",
                    "ticker": result["ticker"],
                }
            )
            continue

        response = result.get("response")
        if isinstance(response, dict):
            error_message = (
                clean_string(response.get("retMsg"))
                or clean_string(response.get("error"))
                or clean_string(response.get("raw_body"))
            )
        else:
            error_message = None
        errors.append(
            {
                "instrument": symbol,
                "message": error_message or "ticker request failed",
                "http_status": result.get("http_status"),
            }
        )
    return items, errors


def build_ict_structure_snapshot(symbols):
    normalized_symbols = {
        normalize_instrument(symbol)
        for symbol in (symbols or [])
        if normalize_instrument(symbol)
    }
    items = {}

    def round_numeric(value):
        numeric = to_float(value)
        return round(numeric, 4) if numeric is not None else None

    for record in TradingAPIHandler.store.list_watchlist_state():
        symbol = normalize_instrument(record.get("instrument"))
        if not symbol or (normalized_symbols and symbol not in normalized_symbols):
            continue

        last_scan = record.get("last_scan") if isinstance(record.get("last_scan"), dict) else {}
        context = last_scan.get("context") if isinstance(last_scan.get("context"), dict) else {}
        payload = (
            last_scan.get("paper_trade_payload")
            if isinstance(last_scan.get("paper_trade_payload"), dict)
            else {}
        )
        evaluation = (
            last_scan.get("paper_trade_evaluation")
            if isinstance(last_scan.get("paper_trade_evaluation"), dict)
            else {}
        )
        sweep = context.get("sweep_15m") if isinstance(context.get("sweep_15m"), dict) else {}
        mss = (
            context.get("mss_15m")
            if isinstance(context.get("mss_15m"), dict)
            else context.get("mss_5m")
            if isinstance(context.get("mss_5m"), dict)
            else {}
        )
        displacement = (
            context.get("displacement_5m")
            if isinstance(context.get("displacement_5m"), dict)
            else {}
        )
        fvg = context.get("fvg_5m") if isinstance(context.get("fvg_5m"), dict) else {}
        narrative = context.get("narrative") if isinstance(context.get("narrative"), dict) else {}
        pd_arrays = context.get("pd_arrays") if isinstance(context.get("pd_arrays"), dict) else {}
        lead_pd_array = pd_arrays.get("lead") if isinstance(pd_arrays.get("lead"), dict) else {}
        drt_summary = context.get("drt_4h") if isinstance(context.get("drt_4h"), dict) else {}
        liquidity_event = (
            context.get("liquidity_event_4h")
            if isinstance(context.get("liquidity_event_4h"), dict)
            else drt_summary.get("liquidity_event")
            if isinstance(drt_summary.get("liquidity_event"), dict)
            else {}
        )
        drt_range = drt_summary.get("range") if isinstance(drt_summary.get("range"), dict) else {}
        drt_internal = (
            drt_summary.get("internal_liquidity")
            if isinstance(drt_summary.get("internal_liquidity"), dict)
            else {}
        )
        drt_external = (
            drt_summary.get("external_liquidity")
            if isinstance(drt_summary.get("external_liquidity"), dict)
            else {}
        )
        levels = (
            context.get("auto_execution_levels")
            if isinstance(context.get("auto_execution_levels"), dict)
            else {}
        )
        bias_summary = context.get("bias_4h") if isinstance(context.get("bias_4h"), dict) else {}
        range_summary = (
            context.get("dealing_range") if isinstance(context.get("dealing_range"), dict) else {}
        )

        items[symbol] = {
            "symbol": symbol,
            "updated_at": clean_string(record.get("updated_at")),
            "decision": clean_string(evaluation.get("decision")) or "unknown",
            "direction": clean_string(payload.get("direction")) or "",
            "session": clean_string(payload.get("session")) or "",
            "liquidity_draw": clean_string(context.get("liquidity_draw")) or "unclear",
            "narrative": {
                "state": clean_string(narrative.get("state")) or "unclear",
                "array_support": clean_string(narrative.get("array_support")) or "unknown",
                "reason": clean_string(narrative.get("reason")) or "",
            },
            "drt": {
                "state": clean_string(drt_summary.get("state")) or "unclear",
                "open_objective": clean_string(drt_summary.get("open_objective")) or "unclear",
                "range_high": round_numeric(drt_range.get("high")),
                "range_low": round_numeric(drt_range.get("low")),
                "midpoint": round_numeric(drt_range.get("midpoint")),
                "location": clean_string(drt_range.get("location")) or "",
                "internal_high": round_numeric(drt_internal.get("high")),
                "internal_low": round_numeric(drt_internal.get("low")),
                "external_high": round_numeric(drt_external.get("high")),
                "external_low": round_numeric(drt_external.get("low")),
            },
            "bias": {
                "state": clean_string(bias_summary.get("bias")) or "neutral",
                "range_high": round_numeric(range_summary.get("high")),
                "range_low": round_numeric(range_summary.get("low")),
                "midpoint": round_numeric(range_summary.get("midpoint")),
                "location": clean_string(range_summary.get("location")) or "",
            },
            "liquidity_event": {
                "state": clean_string(liquidity_event.get("state")) or "none",
                "level": round_numeric(liquidity_event.get("level")),
                "at": clean_string(liquidity_event.get("at")),
                "direction": clean_string(liquidity_event.get("direction")) or "neutral",
                "narrative_hint": clean_string(liquidity_event.get("narrative_hint")) or "unclear",
                "defended_side": clean_string(liquidity_event.get("defended_side")) or "",
                "body_direction": clean_string(liquidity_event.get("body_direction")) or "",
                "tolerance": round_numeric(liquidity_event.get("tolerance")),
                "reason": clean_string(liquidity_event.get("reason")) or "",
            },
            "sweep": {
                "state": clean_string(sweep.get("state")) or "none",
                "level": round_numeric(sweep.get("level")),
                "at": clean_string(sweep.get("at")),
                "tolerance": round_numeric(sweep.get("tolerance")),
                "profile": clean_string(sweep.get("profile")),
            },
            "mss": {
                "state": clean_string(mss.get("state")) or "none",
                "level": round_numeric(mss.get("level")),
                "at": clean_string(mss.get("at")),
                "broken_swing_at": clean_string(mss.get("broken_swing_at")),
                "tolerance": round_numeric(mss.get("tolerance")),
                "micro_break": bool(mss.get("micro_break")),
            },
            "displacement": {
                "state": clean_string(displacement.get("state")) or "none",
                "at": clean_string(displacement.get("at")),
                "mode": clean_string(displacement.get("mode")),
                "range_multiple": round_numeric(displacement.get("range_multiple")),
                "body_multiple": round_numeric(displacement.get("body_multiple")),
            },
            "fvg": {
                "state": clean_string(fvg.get("state")) or "none",
                "lower": round_numeric(fvg.get("lower")),
                "upper": round_numeric(fvg.get("upper")),
                "midpoint": round_numeric(fvg.get("midpoint")),
                "at": clean_string(fvg.get("at")),
            },
            "pd_array": {
                "name": clean_string(lead_pd_array.get("name")) or "",
                "location": clean_string(lead_pd_array.get("location")) or "",
                "range_relation": clean_string(lead_pd_array.get("range_relation")) or "",
                "respect_state": clean_string(lead_pd_array.get("respect_state")) or "unknown",
                "ifvg_candidate": bool(lead_pd_array.get("ifvg_candidate")),
            },
            "levels": {
                "ok": bool(levels.get("ok")),
                "entry_price": round_numeric(levels.get("entry_price")),
                "stop_loss": round_numeric(levels.get("stop_loss")),
                "take_profit": round_numeric(levels.get("take_profit")),
                "target_at": clean_string(levels.get("target_at")),
                "target_source": clean_string(levels.get("target_source")),
                "rr_multiple": round_numeric(levels.get("rr_multiple")),
                "error": clean_string(levels.get("error")),
            },
        }

    return items


def build_control_room_timeline(limit=24):
    store = TradingAPIHandler.store
    per_source_limit = max(6, limit)
    timeline = []

    def append_item(
        *,
        item_id,
        created_at,
        source,
        kind,
        severity,
        event_type,
        title,
        summary,
        symbol=None,
        proposal_id=None,
        meta=None,
    ):
        if not created_at:
            return
        timeline.append(
            {
                "id": item_id,
                "created_at": created_at,
                "source": source,
                "kind": kind,
                "severity": severity,
                "event_type": event_type,
                "title": title,
                "summary": summary,
                "symbol": symbol,
                "proposal_id": proposal_id,
                "meta": meta,
            }
        )

    for item in store.list_scan_history(limit=per_source_limit):
        decision = clean_string(item.get("decision")) or "scan"
        session = clean_string(item.get("session")) or "-"
        direction = clean_string(item.get("direction")) or "not aligned"
        append_item(
            item_id=item["scan_id"],
            created_at=item["created_at"],
            source="scanner",
            kind="scan",
            severity="info" if decision in {"verified_paper_trade", "scanner_candidate", "journal_only"} else "neutral",
            event_type=decision,
            title=f"{item['instrument']} {decision}",
            summary=f"session {session} · direction {direction}",
            symbol=item.get("instrument"),
            proposal_id=None,
            meta=clean_string(item.get("source")) or "watchlist",
        )

    for item in store.list_order_proposals(limit=per_source_limit):
        status = clean_string(item.get("status")) or "proposal"
        side = clean_string(item.get("side")) or "-"
        qty = clean_string(item.get("qty")) or "-"
        price = clean_string(item.get("price")) or "market"
        append_item(
            item_id=item["proposal_id"],
            created_at=item["created_at"],
            source="proposal",
            kind="proposal",
            severity="warning" if status == "ready_for_submission" else "info",
            event_type=status,
            title=f"{item['symbol']} proposal {status}",
            summary=f"{side} {qty} @ {price}",
            symbol=item.get("symbol"),
            proposal_id=item.get("proposal_id"),
            meta=clean_string(item.get("venue")) or "bybit",
        )

    for item in store.list_execution_state(limit=per_source_limit):
        sync_status = clean_string(item.get("sync_status")) or "unknown"
        order_status = clean_string(item.get("order_status")) or "-"
        position_size = clean_string(item.get("position_size")) or "-"
        severity = "warning" if sync_status in {"rejected", "failed"} else "neutral"
        if sync_status in {"working", "filled", "position_open", "partially_filled"}:
            severity = "info"
        append_item(
            item_id=f"xs-{item['proposal_id']}",
            created_at=item["updated_at"],
            source="execution",
            kind="execution_state",
            severity=severity,
            event_type=sync_status,
            title=f"{item['symbol']} {sync_status}",
            summary=f"order {order_status} · size {position_size}",
            symbol=item.get("symbol"),
            proposal_id=item.get("proposal_id"),
            meta=clean_string(item.get("venue")) or "bybit",
        )

    for item in store.list_execution_actions(limit=per_source_limit):
        status = clean_string(item.get("status")) or "unknown"
        append_item(
            item_id=item["action_id"],
            created_at=item["created_at"],
            source="execution",
            kind="execution_action",
            severity="warning" if status == "action_failed" else "info",
            event_type=clean_string(item.get("action_type")) or "execution_action",
            title=f"{clean_string(item.get('symbol')) or item.get('proposal_id') or 'proposal'} {clean_string(item.get('action_type')) or 'action'}",
            summary=status.replace("_", " "),
            symbol=item.get("symbol"),
            proposal_id=item.get("proposal_id"),
            meta=clean_string(item.get("venue")) or "bybit",
        )

    event_sources = [
        (
            "operations",
            "daemon_event",
            store.list_operations_events(limit=per_source_limit),
            lambda item: {
                "severity": clean_string(item.get("severity")) or "info",
                "event_type": clean_string(item.get("event_type")) or "operations",
                "title": item.get("summary") or "operations event",
                "summary": clean_string(item.get("component_key")) or "operations watchdog",
                "symbol": None,
                "proposal_id": None,
                "meta": clean_string(item.get("runtime_key")) or "main",
            },
        ),
        (
            "private_stream",
            "daemon_event",
            store.list_private_stream_events(limit=per_source_limit),
            lambda item: {
                "severity": clean_string(item.get("severity")) or "info",
                "event_type": clean_string(item.get("event_type")) or "private_stream",
                "title": item.get("summary") or "private stream event",
                "summary": clean_string(item.get("runtime_key")) or "stream-main",
                "symbol": clean_string(item.get("symbol")),
                "proposal_id": clean_string(item.get("proposal_id")),
                "meta": "private stream",
            },
        ),
        (
            "auto_execution",
            "daemon_event",
            store.list_auto_execution_events(limit=per_source_limit),
            lambda item: {
                "severity": clean_string(item.get("severity")) or "info",
                "event_type": clean_string(item.get("event_type")) or "auto_execution",
                "title": item.get("summary") or "auto execution event",
                "summary": clean_string(item.get("instrument")) or clean_string(item.get("runtime_key")) or "auto execution",
                "symbol": clean_string(item.get("instrument")),
                "proposal_id": clean_string(item.get("proposal_id")),
                "meta": clean_string(item.get("runtime_key")) or "main",
            },
        ),
        (
            "trade_management",
            "daemon_event",
            store.list_trade_management_events(limit=per_source_limit),
            lambda item: {
                "severity": clean_string(item.get("severity")) or "info",
                "event_type": clean_string(item.get("event_type")) or "trade_management",
                "title": item.get("summary") or "trade management event",
                "summary": clean_string(item.get("symbol")) or clean_string(item.get("runtime_key")) or "trade management",
                "symbol": clean_string(item.get("symbol")),
                "proposal_id": clean_string(item.get("proposal_id")),
                "meta": clean_string(item.get("runtime_key")) or "main",
            },
        ),
        (
            "supervisor",
            "daemon_event",
            store.list_supervisor_events(limit=per_source_limit),
            lambda item: {
                "severity": clean_string(item.get("severity")) or "info",
                "event_type": clean_string(item.get("event_type")) or "supervisor",
                "title": item.get("summary") or "supervisor event",
                "summary": clean_string(item.get("symbol")) or clean_string(item.get("runtime_key")) or "supervisor",
                "symbol": clean_string(item.get("symbol")),
                "proposal_id": clean_string(item.get("proposal_id")),
                "meta": clean_string(item.get("runtime_key")) or "main",
            },
        ),
        (
            "concept_lab",
            "daemon_event",
            store.list_concept_events(limit=per_source_limit),
            lambda item: {
                "severity": clean_string(item.get("severity")) or "info",
                "event_type": clean_string(item.get("event_type")) or "concept_lab",
                "title": item.get("summary") or "concept lab event",
                "summary": clean_string(item.get("concept_id")) or clean_string(item.get("runtime_key")) or "concept lab",
                "symbol": None,
                "proposal_id": None,
                "meta": clean_string(item.get("concept_id")) or "concept",
            },
        ),
    ]

    for source, kind, rows, mapper in event_sources:
        for item in rows:
            normalized = mapper(item)
            append_item(
                item_id=item["event_id"],
                created_at=item["created_at"],
                source=source,
                kind=kind,
                severity=normalized["severity"],
                event_type=normalized["event_type"],
                title=normalized["title"],
                summary=normalized["summary"],
                symbol=normalized["symbol"],
                proposal_id=normalized["proposal_id"],
                meta=normalized["meta"],
            )

    for item in store.list_control_events(limit=per_source_limit):
        append_item(
            item_id=item["event_id"],
            created_at=item["created_at"],
            source="control",
            kind="control",
            severity="warning" if item.get("paused") else "info",
            event_type="paused" if item.get("paused") else "resumed",
            title=f"{item['control_key']} {'paused' if item.get('paused') else 'resumed'}",
            summary=clean_string(item.get("reason")) or clean_string(item.get("updated_by")) or "control state changed",
            symbol=None,
            proposal_id=None,
            meta=clean_string(item.get("control_key")) or "global",
        )

    timeline.sort(key=lambda item: (item["created_at"], item["id"]), reverse=True)
    return timeline[:limit]


def build_control_room_snapshot(
    scan_limit=CONTROL_ROOM_DEFAULTS["scan_limit"],
    proposal_limit=CONTROL_ROOM_DEFAULTS["proposal_limit"],
    execution_limit=CONTROL_ROOM_DEFAULTS["execution_limit"],
    execution_action_limit=CONTROL_ROOM_DEFAULTS["execution_action_limit"],
    auto_event_limit=CONTROL_ROOM_DEFAULTS["auto_event_limit"],
    concept_event_limit=CONTROL_ROOM_DEFAULTS["concept_event_limit"],
    timeline_limit=CONTROL_ROOM_DEFAULTS["timeline_limit"],
):
    store = TradingAPIHandler.store
    concept_runtime = store.get_concept_runtime("main")
    if concept_runtime is None:
        concept_runtimes = store.list_concept_runtime()
        concept_runtime = concept_runtimes[0] if concept_runtimes else None
    concept_summary = concept_runtime.get("last_summary") if isinstance((concept_runtime or {}).get("last_summary"), dict) else {}
    concept_state = concept_runtime.get("state") if isinstance((concept_runtime or {}).get("state"), dict) else {}
    concept_id = clean_string(concept_summary.get("concept_id")) or clean_string(concept_state.get("concept_id")) or "concept-1"
    concept_reviews = store.list_concept_reviews(limit=6, concept_id=concept_id)
    concept_review_summaries_full = store.list_concept_reviews(limit=100, concept_id=concept_id)
    concept_review_records = [
        store.get_concept_review(item.get("review_id"))
        for item in concept_review_summaries_full
        if clean_string(item.get("review_id"))
    ]
    concept_review_records = [item for item in concept_review_records if item is not None]
    concept_revisions = store.list_concept_revisions(limit=6, concept_id=concept_id)
    concept_revision_summaries_full = store.list_concept_revisions(limit=100, concept_id=concept_id)
    concept_revision_records = [
        store.get_concept_revision(item.get("revision_id"))
        for item in concept_revision_summaries_full
        if clean_string(item.get("revision_id"))
    ]
    concept_revision_records = [item for item in concept_revision_records if item is not None]
    concept_revision_compare = summarize_concept_revision_loop(concept_revision_records, concept_review_records)
    concept_live_compare = (
        concept_runtime.get("state", {}).get("revision_compare")
        if isinstance((concept_runtime or {}).get("state"), dict)
        else None
    ) or (
        concept_runtime.get("last_summary", {}).get("revision_compare")
        if isinstance((concept_runtime or {}).get("last_summary"), dict)
        else None
    )
    concept_revision_compare["stage5_readiness"] = build_stage5_readiness(
        concept_revision_compare,
        concept_live_compare,
    )
    concept_acceptance = (
        concept_runtime.get("state", {}).get("last_acceptance")
        if isinstance((concept_runtime or {}).get("state"), dict)
        else None
    ) or (
        concept_runtime.get("last_summary", {}).get("acceptance")
        if isinstance((concept_runtime or {}).get("last_summary"), dict)
        else None
    )
    concept_acceptance_history = (
        concept_runtime.get("state", {}).get("acceptance_history")
        if isinstance((concept_runtime or {}).get("state"), dict)
        else None
    ) or (
        concept_runtime.get("last_summary", {}).get("acceptance_history")
        if isinstance((concept_runtime or {}).get("last_summary"), dict)
        else None
    ) or []
    concept_stage7_decision = (
        concept_runtime.get("state", {}).get("last_stage7_decision")
        if isinstance((concept_runtime or {}).get("state"), dict)
        else None
    ) or (
        concept_runtime.get("last_summary", {}).get("stage7_decision")
        if isinstance((concept_runtime or {}).get("last_summary"), dict)
        else None
    )
    if not isinstance(concept_stage7_decision, dict) and isinstance(concept_acceptance, dict):
        concept_stage7_decision = summarize_stage7_decision(
            concept_acceptance,
            concept_revision_compare,
            concept_review_records,
        )
    concept_stage_status = build_concept_stage_status(
        concept_acceptance,
        concept_stage7_decision,
        concept_revision_compare,
    )

    tickers, ticker_errors = build_ticker_snapshot(RULES["allowed_instruments"])
    return {
        "built_at": utc_now_iso(),
        "stream_poll_seconds": CONTROL_ROOM_STREAM_POLL_SECONDS,
        "session_context": session_context_now(),
        "health": build_health_payload(),
        "operations": build_operations_status(),
        "scans": store.list_scan_history(limit=scan_limit),
        "proposals": store.list_order_proposals(limit=proposal_limit),
        "executionState": store.list_execution_state(limit=execution_limit),
        "executionActions": store.list_execution_actions(limit=execution_action_limit),
        "autoEvents": store.list_auto_execution_events(limit=auto_event_limit),
        "controls": build_controls_snapshot(),
        "rules": RULES,
        "tickers": tickers,
        "ticker_errors": ticker_errors,
        "ictStructures": build_ict_structure_snapshot(RULES["allowed_instruments"]),
        "conceptRuntime": concept_runtime,
        "conceptEvents": store.list_concept_events(limit=concept_event_limit),
        "conceptReviews": concept_reviews,
        "conceptRevisions": concept_revisions,
        "conceptRevisionCompare": concept_revision_compare,
        "conceptAcceptance": concept_acceptance,
        "conceptAcceptanceHistory": concept_acceptance_history,
        "conceptStage7Decision": concept_stage7_decision,
        "conceptStageStatus": concept_stage_status,
        "timeline": build_control_room_timeline(limit=timeline_limit),
    }


def build_concept_brief_response(
    *,
    state_dir,
    db_path,
    event_limit,
    proposal_limit,
    action_limit,
    scan_limit,
    instruments,
    category,
    max_steps,
    step_stride,
    tradable_only,
    policy_path,
):
    from stackctl import concept_decision

    args = SimpleNamespace(
        state_dir=str(state_dir),
        db_path=str(db_path),
        event_limit=int(event_limit),
        proposal_limit=int(proposal_limit),
        action_limit=int(action_limit),
        scan_limit=int(scan_limit),
        instruments=str(instruments),
        category=str(category),
        max_steps=int(max_steps),
        step_stride=int(step_stride),
        tradable_only=bool(tradable_only),
        policy_path=str(policy_path),
    )
    decision = concept_decision(args)
    review = decision.get("concept_review") or {}
    return build_concept_brief_packet(review, decision)


def build_concept_revision_brief_response(
    *,
    state_dir,
    db_path,
    event_limit,
    proposal_limit,
    action_limit,
    scan_limit,
    instruments,
    category,
    max_steps,
    step_stride,
    tradable_only,
    policy_path,
    artifact_limit,
    top_limit,
):
    from stackctl import concept_revision_brief

    args = SimpleNamespace(
        state_dir=str(state_dir),
        db_path=str(db_path),
        event_limit=int(event_limit),
        proposal_limit=int(proposal_limit),
        action_limit=int(action_limit),
        scan_limit=int(scan_limit),
        instruments=str(instruments),
        category=str(category),
        max_steps=int(max_steps),
        step_stride=int(step_stride),
        tradable_only=bool(tradable_only),
        policy_path=str(policy_path),
        artifact_limit=int(artifact_limit),
        top_limit=int(top_limit),
    )
    return concept_revision_brief(args)


def build_concept_acceptance_brief_response(
    *,
    state_dir,
    db_path,
    event_limit,
    proposal_limit,
    action_limit,
    scan_limit,
    instruments,
    category,
    max_steps,
    step_stride,
    tradable_only,
    policy_path,
    artifact_limit,
    top_limit,
):
    from stackctl import concept_acceptance_brief

    args = SimpleNamespace(
        state_dir=str(state_dir),
        db_path=str(db_path),
        event_limit=int(event_limit),
        proposal_limit=int(proposal_limit),
        action_limit=int(action_limit),
        scan_limit=int(scan_limit),
        instruments=str(instruments),
        category=str(category),
        max_steps=int(max_steps),
        step_stride=int(step_stride),
        tradable_only=bool(tradable_only),
        policy_path=str(policy_path),
        artifact_limit=int(artifact_limit),
        top_limit=int(top_limit),
    )
    return concept_acceptance_brief(args)


def build_concept_stage7_decision_brief_response(
    *,
    state_dir,
    db_path,
    event_limit,
    proposal_limit,
    action_limit,
    scan_limit,
    instruments,
    category,
    max_steps,
    step_stride,
    tradable_only,
    policy_path,
    artifact_limit,
    top_limit,
):
    from stackctl import concept_stage7_decision_brief

    args = SimpleNamespace(
        state_dir=str(state_dir),
        db_path=str(db_path),
        event_limit=int(event_limit),
        proposal_limit=int(proposal_limit),
        action_limit=int(action_limit),
        scan_limit=int(scan_limit),
        instruments=str(instruments),
        category=str(category),
        max_steps=int(max_steps),
        step_stride=int(step_stride),
        tradable_only=bool(tradable_only),
        policy_path=str(policy_path),
        artifact_limit=int(artifact_limit),
        top_limit=int(top_limit),
    )
    return concept_stage7_decision_brief(args)


def build_concept_revision_plan_response(
    *,
    candidate_id,
    review_artifact,
    source,
    author,
    state_dir,
    db_path,
    event_limit,
    proposal_limit,
    action_limit,
    scan_limit,
    instruments,
    category,
    max_steps,
    step_stride,
    tradable_only,
    policy_path,
):
    brief = build_concept_brief_response(
        state_dir=state_dir,
        db_path=db_path,
        event_limit=event_limit,
        proposal_limit=proposal_limit,
        action_limit=action_limit,
        scan_limit=scan_limit,
        instruments=instruments,
        category=category,
        max_steps=max_steps,
        step_stride=step_stride,
        tradable_only=tradable_only,
        policy_path=policy_path,
    )
    review_artifact = review_artifact if isinstance(review_artifact, dict) else {}
    return build_concept_revision_plan(
        brief,
        candidate_id=candidate_id,
        review_artifact=review_artifact,
        source=source,
        author=author,
    )


def normalize_timeframes_payload(timeframes):
    if not isinstance(timeframes, dict):
        return {}
    return {
        "bias": normalize_timeframe(timeframes.get("bias")),
        "setup": normalize_timeframe(timeframes.get("setup")),
        "execution": normalize_timeframe(timeframes.get("execution")),
    }


def normalize_checklist_payload(checklist):
    return normalize_checklist_payload_engine(checklist, RULES["required_checklist"])


def evaluate_payload(payload):
    return evaluate_payload_engine(
        payload,
        rules=RULES,
        normalize_instrument=normalize_instrument,
        normalize_session=normalize_session,
        normalize_direction=normalize_direction,
        normalize_timeframes_payload=normalize_timeframes_payload,
        evaluated_at=utc_now_iso,
    )


def create_signal_trace(
    *,
    source_path,
    payload=None,
    evaluation=None,
    context=None,
    symbol=None,
    reference_timestamp=None,
    journal_id=None,
    webhook_id=None,
    scan_id=None,
    scan_batch_id=None,
    source_error=None,
    shadow_mode=None,
    shadow_session_id=None,
):
    trace = build_signal_trace_engine(
        source_path=source_path,
        payload=payload,
        evaluation=evaluation,
        context=context,
        symbol=symbol,
        reference_timestamp=reference_timestamp,
        journal_id=journal_id,
        webhook_id=webhook_id,
        scan_id=scan_id,
        scan_batch_id=scan_batch_id,
        created_at=utc_now_iso(),
        source_error=source_error,
        shadow_mode=shadow_mode,
        shadow_session_id=shadow_session_id,
    )
    return get_runtime_repositories().signal_traces.create(trace)


def persist_signal_trace_for_evaluation(
    *,
    source_path,
    payload,
    evaluation,
    context=None,
    symbol=None,
    reference_timestamp=None,
    journal_id=None,
    webhook_id=None,
    shadow_mode=None,
    shadow_session_id=None,
):
    return create_signal_trace(
        source_path=source_path,
        payload=payload,
        evaluation=evaluation,
        context=context,
        symbol=symbol,
        reference_timestamp=reference_timestamp,
        journal_id=journal_id,
        webhook_id=webhook_id,
        shadow_mode=shadow_mode,
        shadow_session_id=shadow_session_id,
    )


def persist_signal_trace_for_scan_result(
    scan_result,
    *,
    source_path,
    category=None,
):
    if not isinstance(scan_result, dict):
        return None

    shadow = scan_result.get("shadow") if isinstance(scan_result.get("shadow"), dict) else {}
    trace_id = create_signal_trace(
        source_path=source_path,
        payload=scan_result.get("paper_trade_payload"),
        evaluation=scan_result.get("paper_trade_evaluation"),
        context=scan_result.get("context"),
        symbol=scan_result.get("instrument"),
        reference_timestamp=(
            first_present(scan_result.get("paper_trade_payload"), ["reference_at"])
            or clean_string((scan_result.get("context") or {}).get("reference_at"))
            or clean_string(((scan_result.get("context") or {}).get("replay") or {}).get("reference_at"))
        ),
        journal_id=scan_result.get("journal_id"),
        scan_id=scan_result.get("scan_record_id"),
        scan_batch_id=scan_result.get("scan_batch_id"),
        source_error=scan_result.get("error") if not scan_result.get("ok") else None,
        shadow_mode=shadow.get("shadow_mode"),
        shadow_session_id=shadow.get("shadow_session_id"),
    )
    scan_result["signal_trace_id"] = trace_id
    if category and "category" not in scan_result:
        scan_result["category"] = category
    return trace_id


def apply_evaluation_overrides(evaluation, extra_blockers=None, extra_warnings=None):
    if not isinstance(evaluation, dict):
        return evaluation

    blockers = list(evaluation.get("blockers") or [])
    warnings = list(evaluation.get("warnings") or [])
    errors = list(evaluation.get("errors") or [])

    for item in extra_blockers or []:
        text = clean_string(item)
        if text and text not in blockers:
            blockers.append(text)

    for item in extra_warnings or []:
        text = clean_string(item)
        if text and text not in warnings:
            warnings.append(text)

    verification = evaluation.get("verification") if isinstance(evaluation.get("verification"), dict) else {}
    source_mode = clean_string(verification.get("source_mode")) or "manual_assertion"
    if errors:
        decision = "unclear"
        setup_tag = "unclear"
        confidence = "low"
    elif blockers:
        decision = "no_paper_trade"
        setup_tag = "starter invalid"
        confidence = "low"
    else:
        if source_mode == "scanner_verified":
            decision = "verified_paper_trade"
            setup_tag = "starter verified"
        elif source_mode == "hybrid":
            decision = "scanner_candidate"
            setup_tag = "starter candidate"
        else:
            decision = "journal_only"
            setup_tag = "manual_assertion_only"
        confidence = "medium" if warnings else "high"

    updated = dict(evaluation)
    updated["blockers"] = blockers
    updated["warnings"] = warnings
    updated["errors"] = errors
    updated["decision"] = decision
    updated["setup_tag"] = setup_tag
    updated["confidence"] = confidence
    updated["evaluated_at"] = utc_now_iso()
    return updated


def closed_candles_at(candles, interval_code, reference_ms=None, minimum_count=10, allow_insufficient_fallback=True):
    minutes = BYBIT_INTERVAL_MINUTES.get(interval_code)
    if not minutes:
        return candles

    if reference_ms is None:
        reference_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    usable = [
        candle
        for candle in candles
        if candle.get("start_ms", 0) + minutes * 60 * 1000 <= reference_ms
    ]
    if not allow_insufficient_fallback:
        return usable
    return usable if len(usable) >= max(1, int(minimum_count or 1)) else candles


def closed_candles(candles, interval_code):
    return closed_candles_at(candles, interval_code, reference_ms=None)


def detect_4h_liquidity_event(candles, lookback=20):
    prior_drt = summarize_dealing_range(candles[:-1], lookback=lookback)
    return detect_4h_liquidity_event_engine(candles, drt_summary=prior_drt)


def detect_recent_sweep_15m(
    candles,
    lookback=None,
    search_bars=None,
    reclaim_bars=None,
    close_tolerance_fraction=None,
):
    return detect_recent_sweep_15m_engine(
        candles,
        config=HEURISTIC_RULES["sweep_15m"],
        lookback=lookback,
        search_bars=search_bars,
        reclaim_bars=reclaim_bars,
        close_tolerance_fraction=close_tolerance_fraction,
    )


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


def detect_recent_mss_5m(candles, sweep_state):
    return detect_recent_mss_5m_engine(
        candles,
        sweep_state,
        config=HEURISTIC_RULES["mss_5m"],
    )


def detect_recent_mss_15m(candles, expected_direction="", after_at=None):
    return detect_recent_mss_15m_engine(
        candles,
        expected_direction=expected_direction,
        after_at=after_at,
        config=HEURISTIC_RULES["mss_15m"],
    )


def detect_recent_displacement_5m(candles, after_at=None, expected_direction=None):
    return detect_recent_displacement_5m_engine(
        candles,
        after_at=after_at,
        expected_direction=expected_direction,
        config=HEURISTIC_RULES["displacement_5m"],
    )


def detect_chase_state(direction, fvg_state, current_price):
    if not direction or not fvg_state or fvg_state.get("state") == "none" or current_price is None:
        return False

    lower = fvg_state["lower"]
    upper = fvg_state["upper"]
    if direction == "long":
        return current_price > upper
    if direction == "short":
        return current_price < lower
    return False


def derive_liquidity_draw(bias_state, range_summary):
    if not range_summary:
        return "unclear"
    if bias_state == "bullish":
        return "upside"
    if bias_state == "bearish":
        return "downside"
    if range_summary["location"] == "discount":
        return "upside"
    if range_summary["location"] == "premium":
        return "downside"
    return "unclear"


def has_clear_4h_bias(bias_summary):
    bias_summary = bias_summary if isinstance(bias_summary, dict) else {}
    bias_state = clean_string(bias_summary.get("bias"))
    drt_summary = bias_summary.get("drt") if isinstance(bias_summary.get("drt"), dict) else {}
    return bool(
        bias_state in {"bullish", "bearish"}
        and clean_string(drt_summary.get("state")) == "ready"
    )


def derive_effective_liquidity_event(drt_summary, sweep_summary, bias_summary):
    drt_summary = drt_summary if isinstance(drt_summary, dict) else {}
    sweep_summary = sweep_summary if isinstance(sweep_summary, dict) else {}
    bias_summary = bias_summary if isinstance(bias_summary, dict) else {}
    native_event = (
        drt_summary.get("liquidity_event")
        if isinstance(drt_summary.get("liquidity_event"), dict)
        else {}
    )
    native_state = clean_string(native_event.get("state")) or "none"
    if native_state not in {"", "none"}:
        return native_event

    if clean_string(drt_summary.get("state")) != "ready":
        return native_event

    bias_state = clean_string(bias_summary.get("bias"))
    location = clean_string(drt_summary.get("location"))
    sweep_state = clean_string(sweep_summary.get("state"))
    if sweep_state == "sell_side_sweep":
        event_state = "raid_ssl_reject"
        event_direction = "bullish"
        defended_side = "intraday_low_side"
        required_location = "discount"
    elif sweep_state == "buy_side_sweep":
        event_state = "raid_bsl_reject"
        event_direction = "bearish"
        defended_side = "intraday_high_side"
        required_location = "premium"
    else:
        return native_event

    if bias_state != event_direction or location != required_location:
        return native_event

    confidence = to_float(sweep_summary.get("confidence"))
    level = to_float(sweep_summary.get("level"))
    at = clean_string(sweep_summary.get("at"))
    range_high = to_float(drt_summary.get("high"))
    range_low = to_float(drt_summary.get("low"))
    midpoint = to_float(drt_summary.get("midpoint"))
    spread = to_float(drt_summary.get("spread")) or 0.0
    tolerance = max(spread * 0.01, 0.0)
    if (
        confidence is None
        or confidence < 0.5
        or level is None
        or not at
        or range_high is None
        or range_low is None
        or midpoint is None
        or level < (range_low - tolerance)
        or level > (range_high + tolerance)
    ):
        return native_event

    if event_direction == "bullish" and level > midpoint:
        return native_event
    if event_direction == "bearish" and level < midpoint:
        return native_event

    promoted_confidence = min(float(confidence), 0.56)
    return {
        **native_event,
        "state": event_state,
        "interaction": "raid_reject",
        "level": round(level, 4),
        "at": at,
        "direction": event_direction,
        "narrative_hint": "reversal",
        "defended_side": defended_side,
        "confidence": round(promoted_confidence, 3),
        "liquidity_tier": "internal",
        "reference_role": "intraday_range_liquidity",
        "source_timeframe": "15m",
        "source_state": sweep_state,
        "native_state": native_state,
        "range_high": round(range_high, 4),
        "range_low": round(range_low, 4),
        "tolerance": round(tolerance, 4),
        "reason": (
            f"15m {'sell-side' if event_direction == 'bullish' else 'buy-side'} liquidity was swept and reclaimed "
            f"inside a ready 4H {location} dealing-range read"
        ),
        "assumptions": list(native_event.get("assumptions") or [])
        + ["15m sweep can supply the active liquidity event only when ready 4H DRT, location, and bias agree"],
        "limitations": list(native_event.get("limitations") or [])
        + ["intraday liquidity promotion remains heuristic and must not override unclear 4H DRT"],
        "source_event": sweep_summary,
    }


def derive_setup_direction(
    bias_summary,
    narrative_summary,
    context_summary,
    mss_summary,
    displacement_summary,
    fvg_summary,
):
    bias_state = clean_string((bias_summary or {}).get("bias"))
    if bias_state not in {"bullish", "bearish"}:
        return ""

    direction = "long" if bias_state == "bullish" else "short"
    expected_mss = "bullish_mss" if bias_state == "bullish" else "bearish_mss"
    expected_execution = "bullish" if bias_state == "bullish" else "bearish"
    allowed_narrative_states = {"reversal", "continuation", "developing"}

    narrative_state = clean_string((narrative_summary or {}).get("state"))
    premise_strength = clean_string((context_summary or {}).get("premise_strength"))
    execution_eligible = bool((context_summary or {}).get("execution_eligible"))
    mss_state = clean_string((mss_summary or {}).get("state")) or "none"
    displacement_state = clean_string((displacement_summary or {}).get("state")) or "none"
    fvg_state = clean_string((fvg_summary or {}).get("state")) or "none"

    if (
        execution_eligible
        and mss_state == expected_mss
        and displacement_state == expected_execution
        and fvg_state == expected_execution
    ):
        return direction

    if premise_strength != "strong" or narrative_state not in allowed_narrative_states:
        return ""
    if mss_state not in {"none", expected_mss}:
        return ""
    if displacement_state not in {"none", expected_execution}:
        return ""
    if fvg_state not in {"none", expected_execution}:
        return ""
    return direction


def find_nearest_opposing_liquidity(direction, entry_price, execution_candles, setup_candles, bias_summary, range_summary):
    candidates = []
    seen = set()

    def add_candidate(price, source, at=None):
        price_value = to_float(price)
        if price_value is None:
            return
        key = round(price_value, 4)
        if key in seen:
            return
        seen.add(key)
        candidates.append(
            {
                "price": round(price_value, 4),
                "source": source,
                "at": at,
            }
        )

    for swing in recent_swings(execution_candles[-60:] if len(execution_candles) > 60 else execution_candles):
        if direction == "long" and swing["type"] == "high" and swing["price"] > entry_price:
            add_candidate(swing["price"], "5m_swing_high", swing.get("at"))
        elif direction == "short" and swing["type"] == "low" and swing["price"] < entry_price:
            add_candidate(swing["price"], "5m_swing_low", swing.get("at"))

    for swing in recent_swings(setup_candles[-40:] if len(setup_candles) > 40 else setup_candles):
        if direction == "long" and swing["type"] == "high" and swing["price"] > entry_price:
            add_candidate(swing["price"], "15m_swing_high", swing.get("at"))
        elif direction == "short" and swing["type"] == "low" and swing["price"] < entry_price:
            add_candidate(swing["price"], "15m_swing_low", swing.get("at"))

    recent_high = to_float(bias_summary.get("recent_high")) if isinstance(bias_summary, dict) else None
    recent_low = to_float(bias_summary.get("recent_low")) if isinstance(bias_summary, dict) else None
    if direction == "long" and recent_high and recent_high > entry_price:
        add_candidate(recent_high, "4h_recent_high")
    elif direction == "short" and recent_low and recent_low < entry_price:
        add_candidate(recent_low, "4h_recent_low")

    if isinstance(range_summary, dict):
        if direction == "long" and to_float(range_summary.get("high")) and to_float(range_summary.get("high")) > entry_price:
            add_candidate(range_summary.get("high"), "4h_range_high")
        elif direction == "short" and to_float(range_summary.get("low")) and to_float(range_summary.get("low")) < entry_price:
            add_candidate(range_summary.get("low"), "4h_range_low")

    if direction == "long":
        candidates.sort(key=lambda item: item["price"])
    else:
        candidates.sort(key=lambda item: item["price"], reverse=True)
    return candidates


def derive_auto_execution_levels(
    symbol,
    category,
    direction,
    current_price,
    sweep_summary,
    fvg_summary,
    bias_summary,
    range_summary,
    setup_candles,
    execution_candles,
    stop_buffer_ticks=2,
):
    if direction not in {"long", "short"}:
        return {"ok": False, "error": "direction must be long or short"}
    if not isinstance(fvg_summary, dict) or fvg_summary.get("state") not in {"bullish", "bearish"}:
        return {"ok": False, "error": "fresh FVG is required for auto-execution levels"}
    if not isinstance(sweep_summary, dict) or sweep_summary.get("state") == "none":
        return {"ok": False, "error": "a clear liquidity interaction is required for auto-execution levels"}

    lower = to_float(fvg_summary.get("lower"))
    upper = to_float(fvg_summary.get("upper"))
    midpoint = to_float(fvg_summary.get("midpoint"))
    sweep_level = to_float(sweep_summary.get("level"))
    if lower is None or upper is None or midpoint is None:
        return {"ok": False, "error": "FVG bounds are incomplete"}

    if direction == "long":
        if current_price is not None and current_price < lower:
            return {"ok": False, "error": "current price traded below the bullish FVG"}
        stop_base = min(
            [value for value in [lower, sweep_level] if value is not None]
        )
        entry_price = midpoint
    else:
        if current_price is not None and current_price > upper:
            return {"ok": False, "error": "current price traded above the bearish FVG"}
        stop_base = max(
            [value for value in [upper, sweep_level] if value is not None]
        )
        entry_price = midpoint

    instrument_result = fetch_bybit_instrument(symbol, category=category) if symbol else {"ok": False}
    instrument_constraints = extract_bybit_instrument_constraints(
        instrument_result.get("instrument") if instrument_result.get("ok") else None
    )
    tick_size = to_float(instrument_constraints.get("tick_size")) or 0.0
    buffer = tick_size * max(1, int(stop_buffer_ticks or 1)) if tick_size else 0.0

    if direction == "long":
        stop_loss = stop_base - buffer
    else:
        stop_loss = stop_base + buffer

    target_candidates = find_nearest_opposing_liquidity(
        direction=direction,
        entry_price=entry_price,
        execution_candles=execution_candles,
        setup_candles=setup_candles,
        bias_summary=bias_summary,
        range_summary=range_summary,
    )
    if not target_candidates:
        return {"ok": False, "error": "no opposing liquidity target could be derived"}

    take_profit = target_candidates[0]["price"]
    risk_distance = abs(entry_price - stop_loss)
    reward_distance = abs(take_profit - entry_price)
    rr_multiple = reward_distance / risk_distance if risk_distance > 0 else None

    if direction == "long" and not (stop_loss < entry_price < take_profit):
        return {"ok": False, "error": "derived long levels are not ordered correctly"}
    if direction == "short" and not (take_profit < entry_price < stop_loss):
        return {"ok": False, "error": "derived short levels are not ordered correctly"}

    return {
        "ok": True,
        "entry_price": round(entry_price, 4),
        "stop_loss": round(stop_loss, 4),
        "take_profit": round(take_profit, 4),
        "target_source": target_candidates[0]["source"],
        "target_at": target_candidates[0].get("at"),
        "target_candidates": target_candidates[:5],
        "stop_reference": round(stop_base, 4),
        "stop_buffer": round(buffer, 4),
        "rr_multiple": round(rr_multiple, 4) if rr_multiple is not None else None,
        "instrument_constraints": instrument_constraints,
    }


def fetch_latest_closed_reference_ms(symbol, category="linear", interval_code="5m", limit=8):
    interval = BYBIT_INTERVAL_MAP.get(normalize_timeframe(interval_code), interval_code)
    result = fetch_bybit_klines(symbol, interval, limit=max(3, int(limit or 3)), category=category)
    if not result.get("ok"):
        return {
            "ok": False,
            "error": "failed to fetch market data for latest closed reference",
            "details": result,
        }

    candles = closed_candles_at(
        result.get("candles") or [],
        interval,
        reference_ms=None,
        minimum_count=1,
        allow_insufficient_fallback=False,
    )
    if not candles:
        return {
            "ok": False,
            "error": "no closed candles were available for the requested interval",
        }

    latest = candles[-1]
    reference_ms = latest["start_ms"] + BYBIT_INTERVAL_MINUTES[interval] * 60 * 1000
    return {
        "ok": True,
        "symbol": symbol,
        "interval": interval,
        "reference_ms": reference_ms,
        "reference_at": datetime.fromtimestamp(reference_ms / 1000, tz=timezone.utc).replace(microsecond=0).isoformat(),
        "start_ms": latest.get("start_ms"),
        "start_at": latest.get("start_at"),
    }


def build_bybit_heuristic_scan(symbol, category="linear", auto_log=True, reference_ms=None, scan_trigger=None):
    if symbol not in RULES["allowed_instruments"]:
        return {
            "ok": False,
            "status": 400,
            "error": f"instrument {symbol} is outside the current market-data scan scope",
        }

    bias_interval = BYBIT_INTERVAL_MAP["4H"]
    setup_interval = BYBIT_INTERVAL_MAP["15m"]
    execution_interval = BYBIT_INTERVAL_MAP["5m"]

    bias_result = fetch_bybit_klines(symbol, bias_interval, limit=80, category=category)
    if not bias_result["ok"]:
        return {
            "ok": False,
            "status": 502,
            "error": "failed to fetch 4H candles from Bybit",
            "details": bias_result,
        }

    setup_result = fetch_bybit_klines(symbol, setup_interval, limit=120, category=category)
    if not setup_result["ok"]:
        return {
            "ok": False,
            "status": 502,
            "error": "failed to fetch 15m candles from Bybit",
            "details": setup_result,
        }

    execution_result = fetch_bybit_klines(symbol, execution_interval, limit=150, category=category)
    if not execution_result["ok"]:
        return {
            "ok": False,
            "status": 502,
            "error": "failed to fetch 5m candles from Bybit",
            "details": execution_result,
        }

    ticker_result = fetch_bybit_ticker(symbol, category=category)

    if reference_ms is None:
        bias_candles = closed_candles(bias_result["candles"], bias_interval)
        setup_candles = closed_candles(setup_result["candles"], setup_interval)
        execution_candles = closed_candles(execution_result["candles"], execution_interval)
        reference_ms = execution_candles[-1]["start_ms"] + BYBIT_INTERVAL_MINUTES[execution_interval] * 60 * 1000
        if not ticker_result["ok"]:
            return {
                "ok": False,
                "status": 502,
                "error": "failed to fetch Bybit ticker",
                "details": ticker_result,
            }
        ticker = ticker_result.get("ticker") or {}
    else:
        reference_ms = int(reference_ms)
        bias_candles = closed_candles_at(
            bias_result["candles"],
            bias_interval,
            reference_ms=reference_ms,
            allow_insufficient_fallback=False,
        )
        setup_candles = closed_candles_at(
            setup_result["candles"],
            setup_interval,
            reference_ms=reference_ms,
            allow_insufficient_fallback=False,
        )
        execution_candles = closed_candles_at(
            execution_result["candles"],
            execution_interval,
            reference_ms=reference_ms,
            allow_insufficient_fallback=False,
        )
        latest_close = execution_candles[-1]["close"] if execution_candles else None
        ticker = {
            "lastPrice": latest_close,
            "markPrice": latest_close,
            "indexPrice": latest_close,
            "openInterest": None,
            "fundingRate": None,
            "nextFundingTime": None,
        }

    return build_heuristic_scan_from_market_state(
        symbol=symbol,
        category=category,
        bias_candles=bias_candles,
        setup_candles=setup_candles,
        execution_candles=execution_candles,
        ticker=ticker,
        session_info=session_context_at(reference_ms),
        wall_clock_session_info=session_context_now(),
        auto_log=auto_log,
        provider="bybit-public-api",
        notes="Heuristic scan from Bybit public market data; manual visual review still required",
        limitations=[
            "4H liquidity, 15m MSS, 5m displacement, and PD arrays are inferred from raw candles only",
            "news and calendar filters are not automatically applied yet",
            "visual/chart reading is not implemented in the core engine; screenshots remain manual context only",
        ],
        scan_trigger=scan_trigger,
    )


def build_heuristic_scan_from_market_state(
    symbol,
    category,
    bias_candles,
    setup_candles,
    execution_candles,
    ticker,
    session_info,
    wall_clock_session_info=None,
    auto_log=False,
    provider="bybit-public-api",
    notes="",
    limitations=None,
    replay_metadata=None,
    scan_trigger=None,
):
    ticker = ticker if isinstance(ticker, dict) else {}
    session_info = session_info if isinstance(session_info, dict) else session_context_now()
    wall_clock_session_info = (
        wall_clock_session_info
        if isinstance(wall_clock_session_info, dict)
        else session_context_now()
    )
    limitations = limitations if isinstance(limitations, list) else []
    replay_metadata = replay_metadata if isinstance(replay_metadata, dict) else {}
    scan_trigger = scan_trigger if isinstance(scan_trigger, dict) else {}

    if len(bias_candles) < 8:
        return {
            "ok": False,
            "status": 400,
            "error": "not enough closed 4H candles for heuristic scan",
        }
    if len(setup_candles) < 25:
        return {
            "ok": False,
            "status": 400,
            "error": "not enough closed 15m candles for heuristic scan",
        }
    if len(execution_candles) < 30:
        return {
            "ok": False,
            "status": 400,
            "error": "not enough closed 5m candles for heuristic scan",
        }

    bias_summary = infer_4h_bias(bias_candles)
    drt_summary = bias_summary.get("drt") if isinstance(bias_summary, dict) else {}
    range_summary = bias_summary.get("range") if isinstance(bias_summary, dict) else {}
    liquidity_policy_result = load_liquidity_context_policy()
    liquidity_policy = liquidity_policy_result.get("policy") if liquidity_policy_result.get("ok") else {}
    liquidity_map = build_liquidity_map(
        drt_summary=drt_summary,
        setup_candles=setup_candles,
        bias_candles=bias_candles,
        reference_time=session_info.get("now_utc"),
        policy=liquidity_policy,
    )
    sweep_summary = detect_recent_sweep_15m(setup_candles)
    native_liquidity_event = (
        drt_summary.get("liquidity_event") if isinstance(drt_summary.get("liquidity_event"), dict) else {}
    )
    effective_liquidity_event = derive_effective_liquidity_event(
        drt_summary,
        sweep_summary,
        bias_summary,
    )
    if effective_liquidity_event is not native_liquidity_event:
        drt_summary = dict(drt_summary)
        drt_summary["native_liquidity_event"] = native_liquidity_event
        drt_summary["liquidity_event"] = effective_liquidity_event
        drt_summary["open_objective"] = (
            "upside"
            if effective_liquidity_event.get("direction") == "bullish"
            else "downside"
            if effective_liquidity_event.get("direction") == "bearish"
            else clean_string(drt_summary.get("open_objective")) or "unclear"
        )
        bias_summary = dict(bias_summary)
        bias_summary["drt"] = drt_summary
        bias_summary["liquidity_event"] = effective_liquidity_event
        if clean_string(bias_summary.get("bias")) == clean_string(effective_liquidity_event.get("direction")):
            bias_summary["reason"] = clean_string(effective_liquidity_event.get("reason")) or clean_string(
                bias_summary.get("reason")
            )
            bias_summary["confidence"] = max(
                to_float(bias_summary.get("confidence")) or 0.0,
                to_float(effective_liquidity_event.get("confidence")) or 0.0,
            )
    mss_summary = detect_recent_mss_15m(
        setup_candles,
        expected_direction=bias_summary.get("bias"),
        after_at=(drt_summary.get("liquidity_event") or {}).get("at") or sweep_summary.get("at"),
    )
    displacement_summary = detect_recent_displacement_5m(
        execution_candles,
        after_at=mss_summary.get("at"),
        expected_direction=bias_summary.get("bias"),
    )
    fvg_summary = detect_recent_fvg_5m(
        execution_candles,
        after_at=displacement_summary.get("at"),
        expected_direction=displacement_summary.get("state"),
    )
    pd_arrays_summary = summarize_execution_pd_arrays(range_summary, execution_candles, fvg_summary)
    narrative_summary = summarize_narrative_engine(
        bias_summary=bias_summary,
        drt_summary=drt_summary,
        liquidity_map=liquidity_map,
        mss_summary=mss_summary,
        pd_arrays_summary=pd_arrays_summary,
    )
    context_summary = summarize_context_state(
        session_info=session_info,
        bias_summary=bias_summary,
        narrative_summary=narrative_summary,
        mss_summary=mss_summary,
    )
    last_price = to_float(ticker.get("lastPrice")) or execution_candles[-1]["close"]

    direction = derive_setup_direction(
        bias_summary,
        narrative_summary,
        context_summary,
        mss_summary,
        displacement_summary,
        fvg_summary,
    )

    liquidity_draw = derive_liquidity_draw(bias_summary["bias"], range_summary)
    chase_entry = detect_chase_state(direction, fvg_summary, last_price)

    checklist = {
        "clear_4h_bias": has_clear_4h_bias(bias_summary),
        "clear_liquidity_draw": liquidity_draw != "unclear",
        "liquidity_event": (
            drt_summary.get("liquidity_event", {}).get("state") != "none"
            if isinstance(drt_summary, dict)
            else False
        ),
        "mss": mss_summary["state"] in {"bullish_mss", "bearish_mss"},
        "displacement": displacement_summary["state"] in {"bullish", "bearish"},
        "fresh_fvg": fvg_summary["state"] in {"bullish", "bearish"},
        "clear_invalidation": (
            clean_string((drt_summary.get("liquidity_event") or {}).get("state")) not in {"", "none"}
            or fvg_summary["state"] != "none"
        ),
        "clear_target": liquidity_draw != "unclear",
        "chase_entry": chase_entry,
    }

    evaluation_payload = {
        "instrument": symbol,
        "provider": provider,
        "session": session_info["active_session"] if session_info["session_valid"] else "outside",
        "direction": direction,
        "weekend": session_info["weekend"],
        "reference_at": session_info.get("now_utc"),
        "source_mode": "scanner_verified",
        "visual_analysis_state": "not_run",
        "timeframes": {
            "bias": RULES["timeframes"]["bias"],
            "setup": RULES["timeframes"]["setup"],
            "execution": RULES["timeframes"]["execution"],
        },
        "checklist": checklist,
        "notes": notes,
    }
    evaluation = evaluate_payload(evaluation_payload)
    evaluation["warnings"].append(
        "scanner result is heuristic and should be visually confirmed before any paper-trade submission"
    )

    context = {
        "scan_mode": "heuristic",
        "requires_visual_confirmation": True,
        "reference_at": session_info.get("now_utc"),
        "visual_analysis_state": "not_run",
        "scan_trigger": scan_trigger,
        "session": session_info,
        "session_wall_clock": wall_clock_session_info,
        "bias_4h": bias_summary,
        "drt_4h": drt_summary,
        "dealing_range": range_summary,
        "liquidity_event_4h": drt_summary.get("liquidity_event") if isinstance(drt_summary, dict) else {},
        "native_liquidity_event_4h": native_liquidity_event,
        "liquidity_map": liquidity_map,
        "liquidity_draw": liquidity_draw,
        "sweep_15m": sweep_summary,
        "mss_15m": mss_summary,
        "mss_5m": {
            **mss_summary,
            "legacy_alias": True,
            "role": clean_string(mss_summary.get("role")) or "legacy_structure_alias",
            "layer": clean_string(mss_summary.get("layer")) or "execution_compatibility",
            "reason": clean_string(mss_summary.get("reason"))
            or "legacy alias to the 15m MSS output; keep for compatibility only",
        },
        "narrative": narrative_summary,
        "narrative_state": narrative_summary.get("state"),
        "narrative_reason": narrative_summary.get("reason"),
        "context_summary": context_summary,
        "context_state": context_summary.get("state"),
        "context_reason": context_summary.get("reason"),
        "displacement_5m": displacement_summary,
        "fvg_5m": fvg_summary,
        "pd_arrays": pd_arrays_summary,
        "chase_state": "chase" if chase_entry else "not_chase",
        "current_price": round(last_price, 4) if last_price is not None else None,
        "ticker": {
            "last_price": clean_string(ticker.get("lastPrice")),
            "mark_price": clean_string(ticker.get("markPrice")),
            "index_price": clean_string(ticker.get("indexPrice")),
            "open_interest": clean_string(ticker.get("openInterest")),
            "funding_rate": clean_string(ticker.get("fundingRate")),
            "next_funding_time": clean_string(ticker.get("nextFundingTime")),
        },
        "limitations": limitations,
    }
    if replay_metadata:
        context["replay"] = replay_metadata

    auto_execution_levels = None
    if direction and not chase_entry:
        auto_execution_levels = derive_auto_execution_levels(
            symbol=symbol,
            category=category,
            direction=direction,
            current_price=last_price,
            sweep_summary=(drt_summary.get("liquidity_event") if isinstance(drt_summary, dict) else {}) or sweep_summary,
            fvg_summary=fvg_summary,
            bias_summary=bias_summary,
            range_summary=range_summary,
            setup_candles=setup_candles,
            execution_candles=execution_candles,
        )
        if auto_execution_levels.get("ok"):
            context["auto_execution_levels"] = auto_execution_levels
        else:
            context["auto_execution_levels"] = {
                "ok": False,
                "error": auto_execution_levels.get("error"),
            }
            evaluation = apply_evaluation_overrides(
                evaluation,
                extra_blockers=[
                    clean_string(auto_execution_levels.get("error"))
                    or "auto execution levels could not be derived"
                ],
            )

    opportunity = summarize_opportunity_state(
        evaluation=evaluation,
        context=context,
    )
    context["opportunity"] = opportunity

    journal_id = None
    if auto_log:
        journal_id = TradingAPIHandler.store.create_entry(evaluation_payload, evaluation)
        evaluation["journal_id"] = journal_id

    result = {
        "ok": True,
        "status": 200,
        "instrument": symbol,
        "category": category,
        "market_data_counts": {
            "4H": len(bias_candles),
            "15m": len(setup_candles),
            "5m": len(execution_candles),
        },
        "context": context,
        "opportunity": opportunity,
        "paper_trade_payload": evaluation_payload,
        "paper_trade_evaluation": evaluation,
        "journal_id": journal_id,
    }
    result["scan_signature"] = build_scan_signature(result)
    return result


def build_scan_signature(scan_result):
    signature_payload = {
        "instrument": scan_result.get("instrument"),
        "decision": scan_result.get("paper_trade_evaluation", {}).get("decision"),
        "direction": scan_result.get("paper_trade_payload", {}).get("direction"),
        "session": scan_result.get("paper_trade_payload", {}).get("session"),
        "drt": scan_result.get("context", {}).get("drt_4h"),
        "liquidity_event": scan_result.get("context", {}).get("liquidity_event_4h"),
        "mss": scan_result.get("context", {}).get("mss_15m") or scan_result.get("context", {}).get("mss_5m"),
        "displacement": scan_result.get("context", {}).get("displacement_5m"),
        "fvg": scan_result.get("context", {}).get("fvg_5m"),
        "narrative": scan_result.get("context", {}).get("narrative"),
        "context_state": scan_result.get("context", {}).get("context_state"),
    }
    return hashlib.sha256(
        json.dumps(signature_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]


def build_shadow_session_id():
    return datetime.now(timezone.utc).strftime("SHD-%Y%m%dT%H%M%SZ")


def run_bybit_replay_scan(
    symbol,
    category="linear",
    auto_log_candidates=False,
    record_history=False,
    max_steps=100,
    step_stride=1,
    tradable_only=False,
):
    if symbol not in RULES["allowed_instruments"]:
        return {
            "ok": False,
            "status": 400,
            "error": f"instrument {symbol} is outside the current replay scan scope",
        }

    max_steps = max(1, min(500, int(max_steps)))
    step_stride = max(1, min(50, int(step_stride)))
    bias_interval = BYBIT_INTERVAL_MAP["4H"]
    setup_interval = BYBIT_INTERVAL_MAP["15m"]
    execution_interval = BYBIT_INTERVAL_MAP["5m"]

    bias_result = fetch_bybit_klines(symbol, bias_interval, limit=160, category=category)
    if not bias_result["ok"]:
        return {
            "ok": False,
            "status": 502,
            "error": "failed to fetch 4H candles from Bybit",
            "details": bias_result,
        }
    setup_result = fetch_bybit_klines(symbol, setup_interval, limit=400, category=category)
    if not setup_result["ok"]:
        return {
            "ok": False,
            "status": 502,
            "error": "failed to fetch 15m candles from Bybit",
            "details": setup_result,
        }
    execution_result = fetch_bybit_klines(symbol, execution_interval, limit=1000, category=category)
    if not execution_result["ok"]:
        return {
            "ok": False,
            "status": 502,
            "error": "failed to fetch 5m candles from Bybit",
            "details": execution_result,
        }

    execution_candles_all = closed_candles(execution_result["candles"], execution_interval)
    if len(execution_candles_all) < 60:
        return {
            "ok": False,
            "status": 400,
            "error": "not enough closed 5m candles for replay scan",
        }

    candidate_indexes = list(range(len(execution_candles_all) - 1, -1, -step_stride))
    candidate_indexes = list(reversed(candidate_indexes))
    results = []
    decision_counts = {}
    session_counts = {}
    direction_counts = {}
    blocker_counts = {}
    warning_counts = {}
    verified_trade_count = 0
    logged_count = 0
    candidate_summaries = []
    scan_batch_id = datetime.now(timezone.utc).strftime("RP-%Y%m%dT%H%M%SZ")

    for index in candidate_indexes:
        if len(results) >= max_steps:
            break
        execution_anchor = execution_candles_all[index]
        reference_ms = execution_anchor["start_ms"] + BYBIT_INTERVAL_MINUTES[execution_interval] * 60 * 1000
        bias_candles = closed_candles_at(
            bias_result["candles"],
            bias_interval,
            reference_ms=reference_ms,
            allow_insufficient_fallback=False,
        )
        setup_candles = closed_candles_at(
            setup_result["candles"],
            setup_interval,
            reference_ms=reference_ms,
            allow_insufficient_fallback=False,
        )
        execution_candles = closed_candles_at(
            execution_result["candles"],
            execution_interval,
            reference_ms=reference_ms,
            allow_insufficient_fallback=False,
        )
        if len(bias_candles) < 8 or len(setup_candles) < 25 or len(execution_candles) < 30:
            continue

        ticker = {
            "lastPrice": execution_candles[-1]["close"],
            "markPrice": execution_candles[-1]["close"],
            "indexPrice": execution_candles[-1]["close"],
            "openInterest": None,
            "fundingRate": None,
            "nextFundingTime": None,
        }
        replay_metadata = {
            "reference_at": datetime.fromtimestamp(reference_ms / 1000, tz=timezone.utc).replace(microsecond=0).isoformat(),
            "reference_ms": reference_ms,
            "execution_anchor_at": execution_anchor.get("start_at"),
            "execution_index": index,
        }
        session_info = session_context_at(reference_ms)
        if tradable_only and not session_info.get("session_valid"):
            continue
        scan_result = build_heuristic_scan_from_market_state(
            symbol=symbol,
            category=category,
            bias_candles=bias_candles,
            setup_candles=setup_candles,
            execution_candles=execution_candles,
            ticker=ticker,
            session_info=session_info,
            auto_log=False,
            provider="bybit-public-api-replay",
            notes="Heuristic replay scan from Bybit public market data; manual visual review still required",
            limitations=[
                "Replay mode uses historical closed candles only",
                "Ticker fields are approximated from the replay candle close",
                "News and calendar filters are not automatically applied yet",
                "4H liquidity, 15m MSS, 5m displacement, and PD arrays are inferred from raw candles only",
            ],
            replay_metadata=replay_metadata,
        )
        if not scan_result.get("ok"):
            continue

        scan_result["scan_batch_id"] = scan_batch_id
        evaluation = scan_result["paper_trade_evaluation"]
        payload = scan_result["paper_trade_payload"]
        replay = scan_result.get("context", {}).get("replay") or {}
        decision = evaluation["decision"]
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
        session_key = payload.get("session") or "unset"
        direction_key = payload.get("direction") or "unset"
        session_counts[session_key] = session_counts.get(session_key, 0) + 1
        direction_counts[direction_key] = direction_counts.get(direction_key, 0) + 1
        for blocker in evaluation.get("blockers") or []:
            blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
        for warning in evaluation.get("warnings") or []:
            warning_counts[warning] = warning_counts.get(warning, 0) + 1

        if decision == "verified_paper_trade":
            verified_trade_count += 1
            candidate_summary = {
                "reference_at": replay.get("reference_at"),
                "execution_anchor_at": replay.get("execution_anchor_at"),
                "instrument": scan_result.get("instrument"),
                "session": session_key,
                "direction": direction_key,
                "decision": decision,
                "scan_signature": scan_result.get("scan_signature"),
                "journal_id": None,
                "auto_execution_levels": scan_result.get("context", {}).get("auto_execution_levels"),
            }
            if auto_log_candidates:
                journal_id = TradingAPIHandler.store.create_entry(
                    payload,
                    evaluation,
                )
                evaluation["journal_id"] = journal_id
                scan_result["journal_id"] = journal_id
                candidate_summary["journal_id"] = journal_id
                scan_result["candidate_logged"] = True
                logged_count += 1
            else:
                scan_result["candidate_logged"] = False
            scan_result["duplicate_candidate"] = False
            candidate_summaries.append(candidate_summary)
        else:
            scan_result["candidate_logged"] = False
            scan_result["duplicate_candidate"] = False

        if record_history:
            scan_result["scan_record_id"] = TradingAPIHandler.store.create_scan_history_entry(
                source="replay",
                instrument=symbol,
                category=category,
                scan_result=scan_result,
                scan_batch_id=scan_batch_id,
            )
        persist_signal_trace_for_scan_result(
            scan_result,
            source_path="replay",
            category=category,
        )
        results.append(scan_result)

    return {
        "ok": True,
        "status": 200,
        "scan_mode": "replay",
        "scan_batch_id": scan_batch_id,
        "scanned_at": utc_now_iso(),
        "instrument": symbol,
        "category": category,
        "evaluated_steps": len(results),
        "max_steps": max_steps,
        "step_stride": step_stride,
        "tradable_only": bool(tradable_only),
        "verified_trade_count": verified_trade_count,
        "legacy_compat_trade_count": 0,
        "logged_count": logged_count,
        "decision_counts": decision_counts,
        "session_counts": session_counts,
        "direction_counts": direction_counts,
        "blocker_counts": blocker_counts,
        "warning_counts": warning_counts,
        "candidate_summaries": candidate_summaries,
        "results": results,
    }


def run_watchlist_scan(
    instruments=None,
    category="linear",
    auto_log_candidates=False,
    dedupe_state=None,
    persistent_dedupe=True,
    record_history=True,
    reference_ms_by_instrument=None,
    scan_trigger_by_instrument=None,
    shadow_mode=False,
    shadow_session_id=None,
):
    if instruments is None:
        instruments = list(RULES["allowed_instruments"])

    results = []
    scan_batch_id = datetime.now(timezone.utc).strftime("WL-%Y%m%dT%H%M%SZ")
    reference_ms_by_instrument = (
        reference_ms_by_instrument if isinstance(reference_ms_by_instrument, dict) else {}
    )
    scan_trigger_by_instrument = (
        scan_trigger_by_instrument if isinstance(scan_trigger_by_instrument, dict) else {}
    )
    normalized_shadow_mode = bool(shadow_mode)
    normalized_shadow_session_id = clean_string(shadow_session_id) or (
        build_shadow_session_id() if normalized_shadow_mode else None
    )
    for instrument in instruments:
        scan_result = build_bybit_heuristic_scan(
            symbol=instrument,
            category=category,
            auto_log=False,
            reference_ms=reference_ms_by_instrument.get(instrument),
            scan_trigger=scan_trigger_by_instrument.get(instrument),
        )
        scan_result["scan_batch_id"] = scan_batch_id
        scan_result["shadow"] = {
            "shadow_mode": normalized_shadow_mode,
            "shadow_session_id": normalized_shadow_session_id,
        }
        if not scan_result["ok"]:
            if record_history:
                scan_result["scan_record_id"] = TradingAPIHandler.store.create_scan_history_entry(
                    source="watchlist",
                    instrument=instrument,
                    category=category,
                    scan_result=scan_result,
                    scan_batch_id=scan_batch_id,
                )
            persist_signal_trace_for_scan_result(
                scan_result,
                source_path="watchlist",
                category=category,
            )
            results.append(scan_result)
            continue

        scan_result["candidate_logged"] = False
        scan_result["duplicate_candidate"] = False
        decision = scan_result["paper_trade_evaluation"]["decision"]
        signature = scan_result["scan_signature"]
        existing_watchlist_state = None
        if persistent_dedupe:
            existing_watchlist_state = TradingAPIHandler.store.get_watchlist_state(instrument)

        if decision == "verified_paper_trade" and auto_log_candidates:
            previous_signature = None
            if dedupe_state is not None:
                previous_signature = dedupe_state.get(instrument)
            if previous_signature is None and existing_watchlist_state is not None:
                previous_signature = existing_watchlist_state.get("last_logged_signature")
            if previous_signature != signature:
                journal_id = TradingAPIHandler.store.create_entry(
                    scan_result["paper_trade_payload"],
                    scan_result["paper_trade_evaluation"],
                )
                scan_result["paper_trade_evaluation"]["journal_id"] = journal_id
                scan_result["journal_id"] = journal_id
                scan_result["candidate_logged"] = True
                if dedupe_state is not None:
                    dedupe_state[instrument] = signature
                if persistent_dedupe:
                    TradingAPIHandler.store.upsert_watchlist_state(
                        instrument=instrument,
                        scan_signature=signature,
                        scan_decision=decision,
                        scan_result=scan_result,
                        last_logged_signature=signature,
                        last_logged_journal_id=journal_id,
                    )
            else:
                scan_result["duplicate_candidate"] = True
                if persistent_dedupe:
                    TradingAPIHandler.store.upsert_watchlist_state(
                        instrument=instrument,
                        scan_signature=signature,
                        scan_decision=decision,
                        scan_result=scan_result,
                    )
        else:
            if dedupe_state is not None:
                dedupe_state.pop(instrument, None)
            if persistent_dedupe and auto_log_candidates:
                TradingAPIHandler.store.clear_watchlist_logged_state(
                    instrument=instrument,
                    scan_signature=signature,
                    scan_decision=decision,
                    scan_result=scan_result,
                )
            elif persistent_dedupe:
                TradingAPIHandler.store.upsert_watchlist_state(
                    instrument=instrument,
                    scan_signature=signature,
                    scan_decision=decision,
                    scan_result=scan_result,
                )

        if record_history:
            scan_result["scan_record_id"] = TradingAPIHandler.store.create_scan_history_entry(
                source="watchlist",
                instrument=instrument,
                category=category,
                scan_result=scan_result,
                scan_batch_id=scan_batch_id,
            )
        persist_signal_trace_for_scan_result(
            scan_result,
            source_path="watchlist",
            category=category,
        )
        results.append(scan_result)

    return {
        "ok": True,
        "status": 200,
        "scan_mode": "watchlist",
        "shadow_mode": normalized_shadow_mode,
        "shadow_session_id": normalized_shadow_session_id,
        "scan_batch_id": scan_batch_id,
        "scanned_at": utc_now_iso(),
        "instruments": instruments,
        "results": results,
    }


def list_active_order_proposals(limit=250):
    active = []
    for proposal_id in TradingAPIHandler.store.list_order_proposal_ids(limit=limit):
        proposal_record = TradingAPIHandler.store.get_order_proposal(proposal_id)
        if proposal_record is None:
            continue
        execution_state = TradingAPIHandler.store.get_execution_state(proposal_id)
        if proposal_is_supervisable(proposal_record, execution_state):
            active.append(
                {
                    "proposal_record": proposal_record,
                    "execution_state": execution_state,
                }
            )
    return active


def find_active_auto_execution_match(symbol, scan_signature, limit=250):
    symbol = normalize_instrument(symbol)
    scan_signature = clean_string(scan_signature)
    if not symbol or not scan_signature:
        return None

    for item in list_active_order_proposals(limit=limit):
        proposal_record = item["proposal_record"]
        proposal = proposal_record.get("proposal") if isinstance(proposal_record.get("proposal"), dict) else {}
        automation = proposal.get("automation") if isinstance(proposal.get("automation"), dict) else {}
        candidate_symbol = normalize_instrument(proposal_record.get("symbol") or proposal.get("symbol"))
        if candidate_symbol != symbol:
            continue
        if clean_string(automation.get("scan_signature")) == scan_signature:
            return item
    return None


def ensure_execution_intent_for_scan_result(scan_result, *, source_path, runtime_key=None):
    if not isinstance(scan_result, dict) or not scan_result.get("ok"):
        return {"ok": False, "error": "scan result must be successful to create an execution intent"}

    evaluation = scan_result.get("paper_trade_evaluation") if isinstance(scan_result.get("paper_trade_evaluation"), dict) else {}
    decision = clean_string(evaluation.get("decision"))
    if not decision_allows_execution_intent(decision):
        return {
            "ok": False,
            "error": f"{decision} is not execution-intent eligible" if decision else "decision is not execution-intent eligible",
        }

    instrument = normalize_instrument(scan_result.get("instrument"))
    scan_signature = clean_string(scan_result.get("scan_signature"))
    if not instrument or not scan_signature:
        return {"ok": False, "error": "instrument and scan_signature are required for execution intent creation"}

    opportunity = (
        scan_result.get("opportunity")
        if isinstance(scan_result.get("opportunity"), dict)
        else (scan_result.get("context") or {}).get("opportunity")
        if isinstance(scan_result.get("context"), dict)
        else {}
    )
    intent = {
        "intent_key": build_execution_intent_key(
            source_path=source_path,
            symbol=instrument,
            scan_signature=scan_signature,
        ),
        "source_path": clean_string(source_path) or "daemon",
        "runtime_key": clean_string(runtime_key),
        "symbol": instrument,
        "reference_timestamp": (
            first_present(scan_result.get("paper_trade_payload"), ["reference_at"])
            or clean_string((scan_result.get("context") or {}).get("reference_at"))
            or clean_string(((scan_result.get("context") or {}).get("replay") or {}).get("reference_at"))
        ),
        "signal_trace_id": clean_string(scan_result.get("signal_trace_id")),
        "scan_id": clean_string(scan_result.get("scan_record_id")),
        "scan_batch_id": clean_string(scan_result.get("scan_batch_id")),
        "scan_signature": scan_signature,
        "decision": decision,
        "opportunity_state": clean_string((opportunity or {}).get("state")),
        "state": "signal_detected",
        "proposal_id": None,
        "reason": "verified_paper_trade created an execution intent",
    }
    intent_id, record, created = get_runtime_repositories().execution_intents.create_or_get(intent)
    return {
        "ok": True,
        "intent_id": intent_id,
        "created": created,
        "record": record,
    }


def transition_execution_intent_from_sync(proposal_record, sync_result):
    if not isinstance(proposal_record, dict):
        return None
    proposal_id = clean_string(proposal_record.get("proposal_id"))
    if not proposal_id:
        return None

    proposal = proposal_record.get("proposal") if isinstance(proposal_record.get("proposal"), dict) else {}
    automation = proposal.get("automation") if isinstance(proposal.get("automation"), dict) else {}
    intent_id = clean_string(automation.get("execution_intent_id"))
    if not intent_id or not isinstance(sync_result, dict) or not sync_result.get("ok"):
        return None

    snapshot = sync_result.get("snapshot") if isinstance(sync_result.get("snapshot"), dict) else {}
    derived = snapshot.get("derived") if isinstance(snapshot.get("derived"), dict) else {}
    lifecycle_state = clean_string(first_present(derived, ["lifecycle_status"]))
    intent_state = map_sync_lifecycle_to_intent_state(lifecycle_state)
    if not intent_state:
        return None

    return get_runtime_repositories().execution_intents.transition(
        intent_id,
        intent_state,
        summary=f"execution sync mapped lifecycle {lifecycle_state or 'unknown'} to {intent_state}",
        proposal_id=proposal_id,
        details={"lifecycle_status": lifecycle_state, "snapshot": snapshot},
    )


def build_auto_execution_payload(scan_result, policy, runtime_key):
    if not isinstance(scan_result, dict) or not scan_result.get("ok"):
        return {"ok": False, "error": "scan_result must be a successful watchlist scan item"}

    evaluation = scan_result.get("paper_trade_evaluation") or {}
    decision = clean_string(evaluation.get("decision"))
    if not decision_allows_execution_plan(decision):
        return {
            "ok": False,
            "error": f"{decision} is not execution-eligible" if decision else "scan result is not execution-eligible",
        }

    levels = (
        scan_result.get("context", {}).get("auto_execution_levels")
        if isinstance(scan_result.get("context"), dict)
        else None
    )
    if not isinstance(levels, dict) or not levels.get("ok"):
        return {
            "ok": False,
            "error": clean_string(first_present(levels or {}, ["error"])) or "auto execution levels are unavailable",
        }

    evaluation_payload = scan_result.get("paper_trade_payload") or {}
    symbol = normalize_instrument(scan_result.get("instrument"))
    category = clean_string(policy.get("category")) or "linear"

    payload = {
        "instrument": symbol,
        "provider": "auto-execution-policy",
        "session": evaluation_payload.get("session"),
        "direction": evaluation_payload.get("direction"),
        "weekend": evaluation_payload.get("weekend"),
        "timeframes": evaluation_payload.get("timeframes"),
        "checklist": evaluation_payload.get("checklist"),
        "notes": (
            f"auto execution candidate from scan signature {scan_result.get('scan_signature')} "
            f"via runtime {runtime_key}"
        ),
        "entry": {
            "type": "limit",
            "price": levels.get("entry_price"),
        },
        "risk": {
            "stop_loss": levels.get("stop_loss"),
            "take_profit": levels.get("take_profit"),
        },
        "futures": {
            "symbol": symbol,
            "category": category,
        },
    }

    return {
        "ok": True,
        "payload": payload,
        "evaluation": evaluation,
        "levels": levels,
    }


def submit_saved_order_proposal_record(proposal_record):
    proposal_id = proposal_record["proposal_id"]
    proposal = proposal_record.get("proposal") if isinstance(proposal_record.get("proposal"), dict) else {}
    automation = proposal.get("automation") if isinstance(proposal.get("automation"), dict) else {}
    execution_intent_id = clean_string(automation.get("execution_intent_id"))
    if execution_intent_id:
        TradingAPIHandler.store.transition_execution_intent(
            execution_intent_id,
            "order_submission_pending",
            summary="order submission started for execution intent",
            proposal_id=proposal_id,
            details={"source": "submit_saved_order_proposal_record"},
        )
    submit_result = submit_order_proposal(proposal_record)
    updated = TradingAPIHandler.store.update_order_proposal_submission(
        proposal_id,
        submit_result["status"],
        submit_result,
    )
    response = {
        "proposal_id": proposal_id,
        "updated": updated,
        "submission": submit_result,
    }
    if submit_result["ok"]:
        if execution_intent_id:
            TradingAPIHandler.store.transition_execution_intent(
                execution_intent_id,
                "order_submitted",
                summary="proposal was submitted to Bybit testnet",
                proposal_id=proposal_id,
                details={"source": "submit_saved_order_proposal_record"},
            )
        refreshed_record = TradingAPIHandler.store.get_order_proposal(proposal_id)
        sync_result = sync_order_proposal_execution(refreshed_record)
        response["execution_sync"] = sync_result
    return response


def normalize_tradingview_payload(payload):
    timeframes = payload.get("timeframes") if isinstance(payload.get("timeframes"), dict) else {}
    checklist = payload.get("checklist") if isinstance(payload.get("checklist"), dict) else {}
    entry = payload.get("entry") if isinstance(payload.get("entry"), dict) else {}
    risk = payload.get("risk") if isinstance(payload.get("risk"), dict) else {}
    reference_at = parse_iso_datetime(
        first_present(payload, ["reference_at", "timestamp", "alert_time", "event_time", "bar_time"])
    )

    instrument_value = first_present(payload, ["instrument", "symbol", "ticker"])
    provider = first_present(payload, ["provider", "exchange", "venue"])
    if provider is None and isinstance(instrument_value, str) and ":" in instrument_value:
        provider = instrument_value.split(":")[0].strip().lower()
    if provider is None:
        provider = "tradingview"

    explicit_session = normalize_session(first_present(payload, ["session", "kill_zone"]))
    derived_session = session_context_at(reference_at).get("active_session") if reference_at is not None else ""

    normalized = {
        "instrument": normalize_instrument(instrument_value),
        "provider": clean_string(provider),
        "session": explicit_session or derived_session,
        "direction": normalize_direction(first_present(payload, ["direction", "side"])),
        "weekend": coerce_bool(payload.get("weekend")),
        "source_mode": clean_string(payload.get("source_mode")) or "manual_assertion",
        "timeframes": {
            "bias": normalize_timeframe(
                first_present(timeframes, ["bias", "bias_tf", "higher_timeframe"])
                or payload.get("bias_timeframe")
            ),
            "setup": normalize_timeframe(
                first_present(timeframes, ["setup", "setup_tf"])
                or payload.get("setup_timeframe")
            ),
            "execution": normalize_timeframe(
                first_present(timeframes, ["execution", "execution_tf"])
                or payload.get("execution_timeframe")
            ),
        },
        "checklist": {},
        "chart_url": clean_string(first_present(payload, ["chart_url", "tradingview_url"])),
        "screenshot_paths": string_list(payload.get("screenshot_paths")),
        "visual_analysis_state": derive_visual_analysis_state(
            chart_url=clean_string(first_present(payload, ["chart_url", "tradingview_url"])),
            screenshot_paths=string_list(payload.get("screenshot_paths")),
            explicit_state=payload.get("visual_analysis_state"),
        ),
        "reference_at": reference_at.replace(microsecond=0).isoformat() if reference_at is not None else None,
        "notes": clean_string(first_present(payload, ["notes", "comment", "alert_message"])),
        "entry": {
            "type": normalize_order_type(first_present(entry, ["type", "order_type"])),
            "price": decimal_string(first_present(entry, ["price", "entry_price"])),
            "zone_low": decimal_string(first_present(entry, ["zone_low", "lower"])),
            "zone_high": decimal_string(first_present(entry, ["zone_high", "upper"])),
        },
        "risk": {
            "stop_loss": decimal_string(first_present(risk, ["stop_loss", "sl"])),
            "take_profit": decimal_string(first_present(risk, ["take_profit", "tp"])),
            "take_profit_2": decimal_string(first_present(risk, ["take_profit_2", "tp2"])),
        },
    }

    for field in RULES["required_checklist"] + ["chase_entry"]:
        value = checklist.get(field)
        if value is None:
            value = payload.get(field)
        bool_value = coerce_bool(value)
        normalized["checklist"][field] = bool_value if bool_value is not None else value

    if normalized["weekend"] is None:
        normalized["weekend"] = False

    return normalized


def position_idx_from_mode(position_mode, side):
    if not position_mode or position_mode in {"one_way", "oneway"}:
        return 0
    if position_mode in {"hedge", "hedge_mode"}:
        return 1 if side == "Buy" else 2
    return None


def load_execution_spec():
    return load_execution_spec_runtime(
        EXECUTION_SPEC_PATH,
        clean_string=clean_string,
    )


def load_auto_execution_policy():
    return load_auto_execution_policy_runtime(
        AUTO_EXECUTION_POLICY_PATH,
        clean_string=clean_string,
        normalize_instrument=normalize_instrument,
        allowed_instruments=RULES["allowed_instruments"],
    )


def load_trade_management_policy():
    return load_trade_management_policy_runtime(TRADE_MANAGEMENT_POLICY_PATH)


def load_risk_control_policy():
    return load_risk_control_policy_runtime(RISK_CONTROL_POLICY_PATH)


def load_liquidity_context_policy():
    return load_liquidity_context_policy_runtime(LIQUIDITY_CONTEXT_POLICY_PATH)


def resolve_execution_spec_for_symbol(spec, symbol):
    instrument_overrides = {}
    if isinstance(spec.get("instruments"), dict):
        instrument_overrides = spec["instruments"].get(symbol, {})
        if not isinstance(instrument_overrides, dict):
            instrument_overrides = {}

    risk = dict(spec.get("risk") or {})
    execution = dict(spec.get("execution") or {})

    instrument_risk = instrument_overrides.get("risk")
    if isinstance(instrument_risk, dict):
        risk.update(instrument_risk)
    instrument_execution = instrument_overrides.get("execution")
    if isinstance(instrument_execution, dict):
        execution.update(instrument_execution)

    for key in ("min_rr", "risk_per_trade_pct", "max_daily_loss_pct", "max_margin_fraction_of_equity"):
        if key in instrument_overrides:
            risk[key] = instrument_overrides[key]
    for key in ("default_leverage", "max_leverage", "default_order_type"):
        if key in instrument_overrides:
            execution[key] = instrument_overrides[key]

    return {
        "version": clean_string(spec.get("version")),
        "venue": clean_string(spec.get("venue")) or "bybit",
        "category": clean_string(instrument_overrides.get("category")) or clean_string(spec.get("category")) or "linear",
        "account_type": clean_string(spec.get("account_type")) or "UNIFIED",
        "balance_coin": clean_string(spec.get("balance_coin")) or "USDT",
        "position_mode": clean_string(spec.get("position_mode")) or "one_way",
        "margin_mode": clean_string(spec.get("margin_mode")) or "isolated",
        "risk": risk,
        "execution": execution,
        "instrument": instrument_overrides,
    }
















def normalize_bybit_side(side):
    raw = clean_string(side)
    if not raw:
        return ""
    lowered = raw.lower()
    if lowered in {"buy", "long"}:
        return "Buy"
    if lowered in {"sell", "short"}:
        return "Sell"
    return raw


def select_relevant_position(positions, proposal):
    if not isinstance(positions, list):
        return None

    target_symbol = proposal.get("symbol")
    target_side = normalize_bybit_side(proposal.get("side"))
    matching = []
    for item in positions:
        if clean_string(item.get("symbol")) != target_symbol:
            continue
        matching.append(item)
        side = normalize_bybit_side(item.get("side"))
        size = to_decimal(item.get("size"))
        if target_side and side == target_side and size and size > 0:
            return item

    for item in matching:
        size = to_decimal(item.get("size"))
        if size and size > 0:
            return item
    return matching[0] if matching else None


def derive_execution_lifecycle(order, position, proposal_record):
    order = order if isinstance(order, dict) else {}
    position = position if isinstance(position, dict) else {}
    proposal_status = proposal_record.get("status")

    order_status = clean_string(first_present(order, ["orderStatus", "order_status"])) or ""
    cum_exec_qty = to_decimal(first_present(order, ["cumExecQty", "cum_exec_qty"]))
    leaves_qty = to_decimal(first_present(order, ["leavesQty", "leaves_qty"]))
    position_size = to_decimal(first_present(position, ["size", "position_size"]))
    reject_reason = clean_string(first_present(order, ["rejectReason", "reject_reason"]))

    if reject_reason and order_status in {"Rejected", "Deactivated"}:
        return "rejected"
    if order_status in {"Cancelled", "PartiallyFilledCanceled"}:
        return "cancelled"
    if position_size and position_size > 0:
        return "position_open"
    if order_status == "Filled":
        return "filled"
    if order_status == "PartiallyFilled" or (cum_exec_qty and cum_exec_qty > 0 and (leaves_qty is None or leaves_qty > 0)):
        return "partially_filled"
    if order_status in {"New", "Untriggered", "Triggered"}:
        return "working"
    if proposal_status == "submitted_testnet":
        return "submitted"
    if proposal_status == "ready_for_submission":
        return "planned"
    return "unknown"


def build_execution_snapshot(proposal_record, order_result, position_result, wallet_result=None):
    proposal = proposal_record.get("proposal") or {}
    order = order_result.get("order") if isinstance(order_result, dict) else None
    positions = position_result.get("positions") if isinstance(position_result, dict) else None
    position = select_relevant_position(positions, proposal)
    wallet_coin = wallet_result.get("coin_record") if isinstance(wallet_result, dict) else None
    submit_response = proposal_record.get("submit_response") if isinstance(proposal_record.get("submit_response"), dict) else {}
    create_order_result = submit_response.get("create_order_result") if isinstance(submit_response.get("create_order_result"), dict) else {}
    create_payload = create_order_result.get("response", {}).get("result", {}) if isinstance(create_order_result.get("response"), dict) else {}

    lifecycle_status = derive_execution_lifecycle(order, position, proposal_record)

    account_context = proposal.get("account_context") if isinstance(proposal.get("account_context"), dict) else {}
    wallet_summary = {
        "account_type": clean_string(account_context.get("account_type")),
        "balance_coin": clean_string(account_context.get("balance_coin")),
        "equity": clean_string(account_context.get("equity")),
        "available_balance": clean_string(account_context.get("available_balance")),
        "source": clean_string(account_context.get("source")),
    }
    if wallet_coin:
        wallet_summary.update(
            {
                "equity": clean_string(first_present(wallet_coin, ["equity", "walletBalance"])) or wallet_summary["equity"],
                "available_balance": clean_string(
                    first_present(wallet_coin, ["availableToWithdraw", "availableBalance", "equity"])
                )
                or wallet_summary["available_balance"],
                "source": "bybit_wallet_coin",
            }
        )

    return {
        "proposal_id": proposal_record.get("proposal_id"),
        "venue": proposal.get("venue") or "bybit_testnet",
        "symbol": proposal.get("symbol"),
        "synced_at": utc_now_iso(),
        "order_lookup": {
            "order_id": clean_string(first_present(order, ["orderId", "order_id"]))
            or clean_string(first_present(create_payload, ["orderId"])),
            "order_link_id": clean_string(first_present(order, ["orderLinkId", "order_link_id"]))
            or clean_string(first_present(proposal.get("request") or {}, ["orderLinkId"])),
        },
        "order": order or {"found": False},
        "position": position or {"found": False},
        "wallet": wallet_summary,
        "derived": {
            "lifecycle_status": lifecycle_status,
            "order_found": bool(order),
            "position_found": bool(position),
        },
        "raw": {
            "order_result": order_result,
            "position_result": position_result,
            "wallet_result": wallet_result,
        },
    }


def sync_order_proposal_execution(proposal_record):
    if not BYBIT_API_KEY or not BYBIT_API_SECRET:
        return {
            "ok": False,
            "status": "sync_unavailable",
            "error": "BYBIT_API_KEY and BYBIT_API_SECRET are required",
        }

    proposal = proposal_record.get("proposal") or {}
    if proposal.get("venue") != "bybit_testnet":
        return {
            "ok": False,
            "status": "sync_unavailable",
            "error": "proposal venue is not bybit_testnet",
        }

    request = proposal.get("request") if isinstance(proposal.get("request"), dict) else {}
    category = clean_string(first_present(request, ["category"])) or "linear"
    symbol = clean_string(first_present(request, ["symbol"]))
    order_link_id = clean_string(first_present(request, ["orderLinkId"]))

    submit_response = proposal_record.get("submit_response") if isinstance(proposal_record.get("submit_response"), dict) else {}
    create_result = submit_response.get("create_order_result") if isinstance(submit_response.get("create_order_result"), dict) else {}
    create_payload = create_result.get("response", {}).get("result", {}) if isinstance(create_result.get("response"), dict) else {}
    order_id = clean_string(first_present(create_payload, ["orderId"]))

    order_result = fetch_bybit_order_realtime(
        category=category,
        symbol=symbol,
        order_id=order_id,
        order_link_id=order_link_id,
        open_only=0,
    )
    if not order_result["ok"]:
        return {
            "ok": False,
            "status": "sync_failed",
            "error": "failed to fetch Bybit order state",
            "details": order_result,
        }
    if order_result.get("order") is None:
        retry_result = fetch_bybit_order_realtime(
            category=category,
            symbol=symbol,
            order_id=order_id,
            order_link_id=order_link_id,
            open_only=1,
        )
        if retry_result.get("ok"):
            order_result = retry_result

    position_result = fetch_bybit_positions(category=category, symbol=symbol)
    if not position_result["ok"]:
        return {
            "ok": False,
            "status": "sync_failed",
            "error": "failed to fetch Bybit position state",
            "details": position_result,
        }

    account_context = proposal.get("account_context") if isinstance(proposal.get("account_context"), dict) else {}
    wallet_result = None
    account_type = clean_string(first_present(account_context, ["account_type"]))
    balance_coin = clean_string(first_present(account_context, ["balance_coin"]))
    if account_type:
        fetched_wallet = fetch_bybit_wallet_balance(account_type=account_type, coin=balance_coin)
        if fetched_wallet.get("ok"):
            wallet_result = fetched_wallet

    snapshot = build_execution_snapshot(proposal_record, order_result, position_result, wallet_result)
    TradingAPIHandler.store.upsert_execution_state(proposal_record["proposal_id"], snapshot)
    intent_transition = transition_execution_intent_from_sync(
        proposal_record,
        {"ok": True, "snapshot": snapshot},
    )
    return {
        "ok": True,
        "status": "synced",
        "snapshot": snapshot,
        "intent_transition": intent_transition,
    }


def proposal_execution_context(proposal_record):
    proposal = proposal_record.get("proposal") or {}
    request = proposal.get("request") if isinstance(proposal.get("request"), dict) else {}
    execution_state = TradingAPIHandler.store.get_execution_state(proposal_record["proposal_id"])
    snapshot = execution_state.get("snapshot") if isinstance(execution_state, dict) else {}
    order = snapshot.get("order") if isinstance(snapshot.get("order"), dict) else {}
    position = snapshot.get("position") if isinstance(snapshot.get("position"), dict) else {}
    submit_response = proposal_record.get("submit_response") if isinstance(proposal_record.get("submit_response"), dict) else {}
    create_order_result = submit_response.get("create_order_result") if isinstance(submit_response.get("create_order_result"), dict) else {}
    create_payload = create_order_result.get("response", {}).get("result", {}) if isinstance(create_order_result.get("response"), dict) else {}

    return {
        "proposal": proposal,
        "execution_state": execution_state,
        "category": clean_string(first_present(request, ["category"])) or "linear",
        "symbol": clean_string(first_present(request, ["symbol"])) or clean_string(proposal.get("symbol")),
        "order_id": clean_string(first_present(order, ["orderId", "order_id"]))
        or clean_string(first_present(create_payload, ["orderId"])),
        "order_link_id": clean_string(first_present(order, ["orderLinkId", "order_link_id"]))
        or clean_string(first_present(request, ["orderLinkId"])),
        "position": position,
        "position_idx": first_present(request, ["positionIdx"]),
        "side": clean_string(proposal.get("side")),
    }


def execute_cancel_order_action(proposal_record):
    if not BYBIT_API_KEY or not BYBIT_API_SECRET:
        return {
            "ok": False,
            "status": "action_unavailable",
            "error": "BYBIT_API_KEY and BYBIT_API_SECRET are required",
        }

    context = proposal_execution_context(proposal_record)
    if proposal_record.get("proposal", {}).get("venue") != "bybit_testnet":
        return {
            "ok": False,
            "status": "action_unavailable",
            "error": "proposal venue is not bybit_testnet",
        }

    if not context["symbol"]:
        return {
            "ok": False,
            "status": "action_failed",
            "error": "proposal symbol is missing",
        }
    if not context["order_id"] and not context["order_link_id"]:
        return {
            "ok": False,
            "status": "action_failed",
            "error": "no synced order reference found; sync the proposal before cancelling",
        }

    payload = {
        "category": context["category"],
        "symbol": context["symbol"],
    }
    if context["order_id"]:
        payload["orderId"] = context["order_id"]
    else:
        payload["orderLinkId"] = context["order_link_id"]

    cancel_result = bybit_post(BYBIT_ORDER_CANCEL_PATH, payload)
    action_payload = {
        "venue": "bybit_testnet",
        "action_type": "cancel_order",
        "symbol": context["symbol"],
        "request": payload,
        "order": {
            "orderId": context["order_id"],
            "orderLinkId": context["order_link_id"],
        },
        "result": cancel_result,
    }

    if not cancel_result["ok"]:
        action_payload["status"] = "action_failed"
        action_id = TradingAPIHandler.store.create_execution_action(
            proposal_record["proposal_id"],
            "cancel_order",
            "action_failed",
            action_payload,
        )
        return {
            "ok": False,
            "status": "action_failed",
            "action_id": action_id,
            "error": "Bybit cancel-order request failed",
            "details": cancel_result,
        }

    sync_result = sync_order_proposal_execution(proposal_record)
    action_payload["status"] = "action_applied"
    action_payload["execution_sync"] = sync_result
    action_id = TradingAPIHandler.store.create_execution_action(
        proposal_record["proposal_id"],
        "cancel_order",
        "action_applied",
        action_payload,
    )
    return {
        "ok": True,
        "status": "action_applied",
        "action_id": action_id,
        "cancel_result": cancel_result,
        "execution_sync": sync_result,
    }


def execute_close_position_action(proposal_record):
    if not BYBIT_API_KEY or not BYBIT_API_SECRET:
        return {
            "ok": False,
            "status": "action_unavailable",
            "error": "BYBIT_API_KEY and BYBIT_API_SECRET are required",
        }

    if proposal_record.get("proposal", {}).get("venue") != "bybit_testnet":
        return {
            "ok": False,
            "status": "action_unavailable",
            "error": "proposal venue is not bybit_testnet",
        }

    initial_sync = sync_order_proposal_execution(proposal_record)
    if not initial_sync["ok"]:
        return {
            "ok": False,
            "status": "action_failed",
            "error": "failed to sync proposal before close-position action",
            "details": initial_sync,
        }

    snapshot = initial_sync["snapshot"]
    position = snapshot.get("position") if isinstance(snapshot.get("position"), dict) else {}
    symbol = clean_string(snapshot.get("symbol"))
    proposal = proposal_record.get("proposal") or {}
    request = proposal.get("request") if isinstance(proposal.get("request"), dict) else {}
    position_size = to_decimal(first_present(position, ["size", "position_size"]))
    position_side = normalize_bybit_side(first_present(position, ["side", "position_side"]))
    if not symbol:
        return {
            "ok": False,
            "status": "action_failed",
            "error": "proposal symbol is missing",
        }
    if position_size is None or position_size <= 0:
        return {
            "ok": False,
            "status": "action_failed",
            "error": "no open position found to close",
            "details": initial_sync,
        }

    close_side = "Sell" if position_side == "Buy" else "Buy"
    close_request = {
        "category": clean_string(first_present(request, ["category"])) or "linear",
        "symbol": symbol,
        "side": close_side,
        "orderType": "Market",
        "qty": render_decimal(position_size),
        "reduceOnly": True,
        "closeOnTrigger": True,
        "timeInForce": "IOC",
        "orderLinkId": build_order_link_id(symbol, f"{proposal_record['proposal_id']}-close"),
    }
    position_idx = first_present(request, ["positionIdx"])
    if position_idx is not None:
        close_request["positionIdx"] = position_idx

    create_result = bybit_post(BYBIT_ORDER_CREATE_PATH, close_request)
    action_payload = {
        "venue": "bybit_testnet",
        "action_type": "close_position",
        "symbol": symbol,
        "request": close_request,
        "order": {
            "orderId": clean_string(first_present(create_result.get("response", {}).get("result", {}), ["orderId"])),
            "orderLinkId": clean_string(first_present(close_request, ["orderLinkId"])),
        },
        "result": create_result,
        "pre_sync": initial_sync,
    }

    if not create_result["ok"]:
        action_payload["status"] = "action_failed"
        action_id = TradingAPIHandler.store.create_execution_action(
            proposal_record["proposal_id"],
            "close_position",
            "action_failed",
            action_payload,
        )
        return {
            "ok": False,
            "status": "action_failed",
            "action_id": action_id,
            "error": "Bybit close-position request failed",
            "details": create_result,
        }

    final_sync = sync_order_proposal_execution(proposal_record)
    action_payload["status"] = "action_applied"
    action_payload["execution_sync"] = final_sync
    action_id = TradingAPIHandler.store.create_execution_action(
        proposal_record["proposal_id"],
        "close_position",
        "action_applied",
        action_payload,
    )
    return {
        "ok": True,
        "status": "action_applied",
        "action_id": action_id,
        "close_result": create_result,
        "execution_sync": final_sync,
    }


def execute_amend_order_action(proposal_record, payload):
    if not BYBIT_API_KEY or not BYBIT_API_SECRET:
        return {
            "ok": False,
            "status": "action_unavailable",
            "error": "BYBIT_API_KEY and BYBIT_API_SECRET are required",
        }

    if proposal_record.get("proposal", {}).get("venue") != "bybit_testnet":
        return {
            "ok": False,
            "status": "action_unavailable",
            "error": "proposal venue is not bybit_testnet",
        }

    context = proposal_execution_context(proposal_record)
    if not context["symbol"]:
        return {
            "ok": False,
            "status": "action_failed",
            "error": "proposal symbol is missing",
        }
    if not context["order_id"] and not context["order_link_id"]:
        return {
            "ok": False,
            "status": "action_failed",
            "error": "no synced order reference found; sync the proposal before amending",
        }

    amend_request = {
        "category": context["category"],
        "symbol": context["symbol"],
    }
    if context["order_id"]:
        amend_request["orderId"] = context["order_id"]
    else:
        amend_request["orderLinkId"] = context["order_link_id"]

    amended_fields = []
    new_price = decimal_string(first_present(payload, ["price", "entry_price"]))
    new_qty = decimal_string(first_present(payload, ["qty", "quantity", "size"]))
    new_take_profit = decimal_string(first_present(payload, ["take_profit", "tp"]))
    new_stop_loss = decimal_string(first_present(payload, ["stop_loss", "sl"]))
    new_tpsl_mode = clean_string(first_present(payload, ["tpsl_mode"]))

    if new_price is not None:
        amend_request["price"] = new_price
        amended_fields.append("price")
    if new_qty is not None:
        amend_request["qty"] = new_qty
        amended_fields.append("qty")
    if new_take_profit is not None:
        amend_request["takeProfit"] = new_take_profit
        amended_fields.append("takeProfit")
    if new_stop_loss is not None:
        amend_request["stopLoss"] = new_stop_loss
        amended_fields.append("stopLoss")
    if new_tpsl_mode is not None:
        amend_request["tpslMode"] = new_tpsl_mode
        amended_fields.append("tpslMode")

    if not amended_fields:
        return {
            "ok": False,
            "status": "action_failed",
            "error": "at least one amendable field is required: price, qty, take_profit, stop_loss, or tpsl_mode",
        }

    amend_result = bybit_post(BYBIT_ORDER_AMEND_PATH, amend_request)
    action_payload = {
        "venue": "bybit_testnet",
        "action_type": "amend_order",
        "symbol": context["symbol"],
        "request": amend_request,
        "amended_fields": amended_fields,
        "order": {
            "orderId": context["order_id"],
            "orderLinkId": context["order_link_id"],
        },
        "result": amend_result,
    }

    if not amend_result["ok"]:
        action_payload["status"] = "action_failed"
        action_id = TradingAPIHandler.store.create_execution_action(
            proposal_record["proposal_id"],
            "amend_order",
            "action_failed",
            action_payload,
        )
        return {
            "ok": False,
            "status": "action_failed",
            "action_id": action_id,
            "error": "Bybit amend-order request failed",
            "details": amend_result,
        }

    sync_result = sync_order_proposal_execution(proposal_record)
    action_payload["status"] = "action_applied"
    action_payload["execution_sync"] = sync_result
    action_id = TradingAPIHandler.store.create_execution_action(
        proposal_record["proposal_id"],
        "amend_order",
        "action_applied",
        action_payload,
    )
    return {
        "ok": True,
        "status": "action_applied",
        "action_id": action_id,
        "amend_result": amend_result,
        "execution_sync": sync_result,
    }


def execute_refresh_trading_stop_action(proposal_record, payload):
    if not BYBIT_API_KEY or not BYBIT_API_SECRET:
        return {
            "ok": False,
            "status": "action_unavailable",
            "error": "BYBIT_API_KEY and BYBIT_API_SECRET are required",
        }

    if proposal_record.get("proposal", {}).get("venue") != "bybit_testnet":
        return {
            "ok": False,
            "status": "action_unavailable",
            "error": "proposal venue is not bybit_testnet",
        }

    initial_sync = sync_order_proposal_execution(proposal_record)
    if not initial_sync["ok"]:
        return {
            "ok": False,
            "status": "action_failed",
            "error": "failed to sync proposal before refreshing trading stop",
            "details": initial_sync,
        }

    snapshot = initial_sync["snapshot"]
    position = snapshot.get("position") if isinstance(snapshot.get("position"), dict) else {}
    if position.get("found") is False:
        position = {}
    position_size = to_decimal(first_present(position, ["size", "position_size"]))
    if position_size is None or position_size <= 0:
        return {
            "ok": False,
            "status": "action_failed",
            "error": "no open position found to update trading stop",
            "details": initial_sync,
        }

    proposal = proposal_record.get("proposal") or {}
    request = proposal.get("request") if isinstance(proposal.get("request"), dict) else {}
    refresh_request = {
        "category": clean_string(first_present(request, ["category"])) or "linear",
        "symbol": clean_string(snapshot.get("symbol")) or clean_string(first_present(request, ["symbol"])),
        "positionIdx": first_present(request, ["positionIdx"]) or 0,
        "tpslMode": clean_string(first_present(payload, ["tpsl_mode"])) or "Full",
    }

    updated_fields = []
    take_profit = decimal_string(first_present(payload, ["take_profit", "tp"]))
    stop_loss = decimal_string(first_present(payload, ["stop_loss", "sl"]))
    trailing_stop = decimal_string(first_present(payload, ["trailing_stop"]))
    active_price = decimal_string(first_present(payload, ["active_price"]))
    tp_trigger_by = normalize_trigger_by(first_present(payload, ["tp_trigger_by"])) or None
    sl_trigger_by = normalize_trigger_by(first_present(payload, ["sl_trigger_by"])) or None

    if take_profit is not None:
        refresh_request["takeProfit"] = take_profit
        updated_fields.append("takeProfit")
    if stop_loss is not None:
        refresh_request["stopLoss"] = stop_loss
        updated_fields.append("stopLoss")
    if trailing_stop is not None:
        refresh_request["trailingStop"] = trailing_stop
        updated_fields.append("trailingStop")
    if active_price is not None:
        refresh_request["activePrice"] = active_price
        updated_fields.append("activePrice")
    if tp_trigger_by is not None:
        refresh_request["tpTriggerBy"] = tp_trigger_by
        updated_fields.append("tpTriggerBy")
    if sl_trigger_by is not None:
        refresh_request["slTriggerBy"] = sl_trigger_by
        updated_fields.append("slTriggerBy")

    if not updated_fields:
        return {
            "ok": False,
            "status": "action_failed",
            "error": "at least one trading-stop field is required: take_profit, stop_loss, trailing_stop, active_price, tp_trigger_by, or sl_trigger_by",
        }

    trading_stop_result = bybit_post(BYBIT_TRADING_STOP_PATH, refresh_request)
    action_payload = {
        "venue": "bybit_testnet",
        "action_type": "refresh_trading_stop",
        "symbol": refresh_request["symbol"],
        "request": refresh_request,
        "updated_fields": updated_fields,
        "position": {
            "side": clean_string(first_present(position, ["side", "position_side"])),
            "size": render_decimal(position_size),
        },
        "result": trading_stop_result,
        "pre_sync": initial_sync,
    }

    if not trading_stop_result["ok"]:
        action_payload["status"] = "action_failed"
        action_id = TradingAPIHandler.store.create_execution_action(
            proposal_record["proposal_id"],
            "refresh_trading_stop",
            "action_failed",
            action_payload,
        )
        return {
            "ok": False,
            "status": "action_failed",
            "action_id": action_id,
            "error": "Bybit trading-stop request failed",
            "details": trading_stop_result,
        }

    final_sync = sync_order_proposal_execution(proposal_record)
    action_payload["status"] = "action_applied"
    action_payload["execution_sync"] = final_sync
    action_id = TradingAPIHandler.store.create_execution_action(
        proposal_record["proposal_id"],
        "refresh_trading_stop",
        "action_applied",
        action_payload,
    )
    return {
        "ok": True,
        "status": "action_applied",
        "action_id": action_id,
        "trading_stop_result": trading_stop_result,
        "execution_sync": final_sync,
    }


def proposal_is_supervisable(proposal_record, execution_state):
    if not isinstance(proposal_record, dict):
        return False

    proposal = proposal_record.get("proposal") or {}
    if proposal.get("venue") != "bybit_testnet":
        return False

    sync_status = clean_string(first_present(execution_state or {}, ["sync_status"])) or ""
    if sync_status:
        return sync_status in SUPERVISOR_ACTIVE_EXECUTION_STATUSES

    proposal_status = clean_string(proposal_record.get("status")) or ""
    if proposal_status in SUPERVISOR_ACTIVE_PROPOSAL_STATUSES:
        return True

    return sync_status in SUPERVISOR_ACTIVE_EXECUTION_STATUSES


def resolve_supervisor_snapshot(execution_state=None, sync_result=None):
    stored_snapshot = {}
    if isinstance(execution_state, dict) and isinstance(execution_state.get("snapshot"), dict):
        stored_snapshot = execution_state.get("snapshot") or {}

    sync_snapshot = {}
    if (
        isinstance(sync_result, dict)
        and sync_result.get("ok")
        and isinstance(sync_result.get("snapshot"), dict)
    ):
        sync_snapshot = sync_result.get("snapshot") or {}

    if not stored_snapshot:
        return sync_snapshot
    if not sync_snapshot:
        return stored_snapshot

    merged = dict(stored_snapshot)
    for key in ("order", "position", "wallet", "raw", "derived", "order_lookup"):
        if not isinstance(merged.get(key), dict) and isinstance(sync_snapshot.get(key), dict):
            merged[key] = sync_snapshot.get(key)
    for key in ("synced_at", "symbol", "venue", "status", "position_status"):
        if not clean_string(merged.get(key)) and clean_string(sync_snapshot.get(key)):
            merged[key] = sync_snapshot.get(key)
    return merged


def resolve_supervisor_lifecycle(proposal_record, execution_state=None, sync_result=None):
    snapshot = resolve_supervisor_snapshot(execution_state, sync_result)
    derived = snapshot.get("derived") if isinstance(snapshot.get("derived"), dict) else {}
    lifecycle = clean_string(first_present(derived, ["lifecycle_status"]))
    if lifecycle:
        return lifecycle, snapshot

    lifecycle = clean_string(first_present(execution_state or {}, ["sync_status"]))
    if lifecycle and lifecycle != "unknown":
        return lifecycle, snapshot

    order = snapshot.get("order") if isinstance(snapshot.get("order"), dict) else {}
    position = snapshot.get("position") if isinstance(snapshot.get("position"), dict) else {}
    lifecycle = derive_execution_lifecycle(order, position, proposal_record)
    return lifecycle or "unknown", snapshot


def build_supervisor_recommendation(proposal_record, execution_state, sync_result=None):
    proposal_status = clean_string(proposal_record.get("status")) or ""
    lifecycle, _snapshot = resolve_supervisor_lifecycle(proposal_record, execution_state, sync_result)

    if proposal_status == "ready_for_submission":
        return {
            "status": "await_submission",
            "summary": "proposal is ready but has not been submitted to Bybit testnet",
            "next_action": "submit_or_archive",
        }
    if sync_result is not None and not sync_result.get("ok"):
        return {
            "status": "manual_review",
            "summary": clean_string(sync_result.get("error")) or "sync failed or is unavailable",
            "next_action": "check_credentials_or_manual_review",
        }
    if lifecycle == "working":
        return {
            "status": "monitor_working_order",
            "summary": "working order is still pending on Bybit",
            "next_action": "monitor_or_amend",
        }
    if lifecycle == "partially_filled":
        return {
            "status": "monitor_partial_fill",
            "summary": "order is partially filled and still needs supervision",
            "next_action": "monitor_or_cancel",
        }
    if lifecycle == "position_open":
        return {
            "status": "monitor_open_position",
            "summary": "position is open and TP/SL lifecycle should be supervised",
            "next_action": "monitor_or_refresh_trading_stop",
        }
    if lifecycle == "filled":
        return {
            "status": "verify_fill_outcome",
            "summary": "order is filled; verify whether a position is open or the trade is flat",
            "next_action": "sync_again_or_manual_review",
        }
    if lifecycle in {"cancelled", "rejected"}:
        return {
            "status": "terminal",
            "summary": f"proposal reached terminal lifecycle: {lifecycle}",
            "next_action": "archive",
        }
    if lifecycle == "submitted":
        return {
            "status": "await_exchange_state",
            "summary": "proposal was submitted but exchange state has not stabilized yet",
            "next_action": "sync_again",
        }
    return {
        "status": "manual_review",
        "summary": "proposal lifecycle is ambiguous",
        "next_action": "manual_review",
    }


def build_supervisor_item(proposal_record, execution_state=None, sync_result=None):
    proposal = proposal_record.get("proposal") or {}
    execution_state = execution_state if isinstance(execution_state, dict) else {}
    lifecycle, snapshot = resolve_supervisor_lifecycle(proposal_record, execution_state, sync_result)
    recommendation = build_supervisor_recommendation(proposal_record, execution_state, sync_result)

    return {
        "proposal_id": proposal_record.get("proposal_id"),
        "symbol": proposal_record.get("symbol") or proposal.get("symbol"),
        "side": proposal_record.get("side") or proposal.get("side"),
        "venue": proposal_record.get("venue") or proposal.get("venue"),
        "proposal_status": proposal_record.get("status"),
        "sync_status": clean_string(first_present(execution_state, ["sync_status"]))
        or lifecycle
        or "untracked",
        "updated_at": clean_string(first_present(execution_state, ["updated_at"]))
        or clean_string(first_present(snapshot, ["synced_at"]))
        or proposal_record.get("created_at"),
        "order_status": clean_string(first_present(execution_state, ["order_status"]))
        or clean_string(first_present(snapshot.get("order") if isinstance(snapshot, dict) else {}, ["orderStatus"])),
        "position_size": clean_string(first_present(execution_state, ["position_size"]))
        or clean_string(first_present(snapshot.get("position") if isinstance(snapshot, dict) else {}, ["size"])),
        "unrealised_pnl": clean_string(first_present(execution_state, ["unrealised_pnl"]))
        or clean_string(first_present(snapshot.get("position") if isinstance(snapshot, dict) else {}, ["unrealisedPnl"])),
        "recommendation": recommendation,
        "sync_attempted": bool(sync_result is not None),
        "sync_result": {
            "ok": sync_result.get("ok"),
            "status": sync_result.get("status"),
            "error": sync_result.get("error"),
        }
        if isinstance(sync_result, dict)
        else None,
    }


def run_supervisor_scan(limit=25, sync_active=True, include_inactive=False):
    proposal_ids = TradingAPIHandler.store.list_order_proposal_ids(limit=limit)
    items = []
    summary = {
        "considered": 0,
        "active": 0,
        "sync_attempted": 0,
        "synced_ok": 0,
        "sync_failed": 0,
    }

    for proposal_id in proposal_ids:
        proposal_record = TradingAPIHandler.store.get_order_proposal(proposal_id)
        if proposal_record is None:
            continue
        summary["considered"] += 1

        execution_state = TradingAPIHandler.store.get_execution_state(proposal_id)
        is_active = proposal_is_supervisable(proposal_record, execution_state)
        if is_active:
            summary["active"] += 1
        if not include_inactive and not is_active:
            continue

        sync_result = None
        if (
            sync_active
            and is_active
            and clean_string(proposal_record.get("status")) == "submitted_testnet"
        ):
            summary["sync_attempted"] += 1
            sync_result = sync_order_proposal_execution(proposal_record)
            if sync_result.get("ok"):
                summary["synced_ok"] += 1
                execution_state = TradingAPIHandler.store.get_execution_state(proposal_id)
            else:
                summary["sync_failed"] += 1

        items.append(build_supervisor_item(proposal_record, execution_state, sync_result))

    return {
        "ok": True,
        "status": 200,
        "scan_mode": "supervisor",
        "scanned_at": utc_now_iso(),
        "summary": summary,
        "items": items,
    }


def resolve_account_state(account_payload, execution_spec):
    account_payload = account_payload if isinstance(account_payload, dict) else {}
    warnings = []

    account_type = clean_string(account_payload.get("account_type")) or execution_spec["account_type"]
    balance_coin = clean_string(account_payload.get("balance_coin")) or execution_spec["balance_coin"]

    equity = to_decimal(
        first_present(account_payload, ["equity", "wallet_balance", "balance", "account_equity"])
    )
    available_balance = to_decimal(
        first_present(account_payload, ["available_balance", "free_balance", "available"])
    )
    source = "payload" if equity is not None or available_balance is not None else ""
    wallet_snapshot = None

    if (equity is None or available_balance is None) and BYBIT_API_KEY and BYBIT_API_SECRET:
        wallet_result = fetch_bybit_wallet_balance(account_type=account_type, coin=balance_coin)
        if wallet_result["ok"]:
            wallet_snapshot = wallet_result
            account_record = wallet_result.get("account") or {}
            coin_record = wallet_result.get("coin_record") or {}
            if equity is None:
                equity = (
                    to_decimal(first_present(coin_record, ["walletBalance", "equity"]))
                    or to_decimal(first_present(account_record, ["totalWalletBalance", "totalEquity"]))
                )
                if coin_record:
                    source = "bybit_wallet_coin"
                elif equity is not None:
                    source = "bybit_wallet_account"
                    warnings.append(
                        "equity was derived from Bybit account totals because no coin-level wallet balance was available"
                    )
            if available_balance is None:
                available_balance = (
                    to_decimal(
                        first_present(
                            coin_record,
                            [
                                "availableToWithdraw",
                                "availableBalance",
                                "availableToBorrow",
                                "equity",
                            ],
                        )
                    )
                    or to_decimal(first_present(account_record, ["totalAvailableBalance"]))
                )
        else:
            warnings.append("failed to fetch Bybit wallet balance for account-aware sizing")

    return {
        "account_type": account_type,
        "balance_coin": balance_coin,
        "equity": equity,
        "available_balance": available_balance,
        "source": source or "unavailable",
        "warnings": warnings,
        "wallet_snapshot": wallet_snapshot,
    }


def build_bybit_execution_plan(raw_payload, normalized_payload, evaluation, journal_id=None, created_from="api"):
    if not decision_allows_execution_plan(evaluation.get("decision")):
        return None

    futures = raw_payload.get("futures") if isinstance(raw_payload.get("futures"), dict) else {}
    entry = raw_payload.get("entry") if isinstance(raw_payload.get("entry"), dict) else {}
    risk = raw_payload.get("risk") if isinstance(raw_payload.get("risk"), dict) else {}
    account = raw_payload.get("account") if isinstance(raw_payload.get("account"), dict) else {}

    warnings = []
    missing_fields = []
    review_required = False

    spec_result = load_execution_spec()
    if not spec_result["ok"]:
        return {
            "venue": "bybit_testnet",
            "status": "review_required",
            "strategy_version": RULES["strategy_version"],
            "symbol": None,
            "side": None,
            "paper_trade_journal_id": journal_id,
            "missing_fields": ["execution_spec"],
            "warnings": spec_result["errors"],
            "bybit": {
                "base_url": BYBIT_PRIVATE_BASE_URL,
                "create_order_endpoint": f"{BYBIT_PRIVATE_BASE_URL}{BYBIT_ORDER_CREATE_PATH}",
                "create_order_path": BYBIT_ORDER_CREATE_PATH,
            },
            "request": {},
            "execution_context": {
                "analysis_instrument": evaluation["normalized"]["instrument"],
                "direction": evaluation["normalized"].get("direction"),
            },
            "pre_submit_actions": [],
            "created_from": created_from,
            "created_at": utc_now_iso(),
            "execution_spec_path": spec_result["path"],
        }

    direction = evaluation["normalized"].get("direction")
    if direction == "long":
        side = "Buy"
    elif direction == "short":
        side = "Sell"
    else:
        side = None
        missing_fields.append("direction")
        review_required = True

    raw_symbol = normalize_instrument(
        first_present(futures, ["symbol", "execution_symbol"])
        or raw_payload.get("execution_symbol")
        or evaluation["normalized"]["instrument"]
    )
    execution_spec = resolve_execution_spec_for_symbol(spec_result["spec"], raw_symbol)

    category = clean_string(first_present(futures, ["category"]) or raw_payload.get("category")) or execution_spec["category"]
    category = category.lower()

    if category == "linear":
        symbol = LINEAR_PROXY_MAP.get(raw_symbol, raw_symbol)
        if raw_symbol in LINEAR_PROXY_MAP:
            warnings.append(
                f"execution symbol defaulted from {raw_symbol} to {symbol} for Bybit linear futures"
            )
        if symbol not in LINEAR_SYMBOLS:
            missing_fields.append("futures.symbol")
    elif category == "inverse":
        symbol = INVERSE_PROXY_MAP.get(raw_symbol, raw_symbol)
        if raw_symbol in INVERSE_PROXY_MAP:
            warnings.append(
                f"execution symbol defaulted from {raw_symbol} to {symbol} for Bybit inverse futures"
            )
        if symbol not in INVERSE_SYMBOLS:
            missing_fields.append("futures.symbol")
        warnings.append("inverse Bybit futures are not the house default; review required")
        review_required = True
    else:
        symbol = raw_symbol
        missing_fields.append("futures.category")
        warnings.append(f"unsupported Bybit category: {category}")
        review_required = True

    order_type = normalize_order_type(
        first_present(entry, ["type", "order_type"]) or raw_payload.get("order_type")
    )
    if not order_type:
        order_type = normalize_order_type(execution_spec["execution"].get("default_order_type")) or "Limit"

    if order_type == "Market" and not coerce_bool(execution_spec["execution"].get("allow_market_orders")):
        warnings.append("market orders are disabled by the execution spec")
        review_required = True

    entry_price = to_decimal(
        first_present(entry, ["price", "entry_price"])
        or raw_payload.get("entry_price")
        or raw_payload.get("price")
    )
    explicit_qty = to_decimal(
        first_present(futures, ["qty", "quantity", "size"])
        or raw_payload.get("qty")
        or raw_payload.get("quantity")
        or raw_payload.get("size")
    )
    stop_loss = to_decimal(
        first_present(risk, ["stop_loss", "sl"])
        or first_present(futures, ["stop_loss", "sl"])
        or raw_payload.get("stop_loss")
    )
    take_profit = to_decimal(
        first_present(risk, ["take_profit", "tp"])
        or first_present(futures, ["take_profit", "tp"])
        or raw_payload.get("take_profit")
    )
    take_profit_2 = to_decimal(
        first_present(risk, ["take_profit_2", "tp2"])
        or raw_payload.get("take_profit_2")
    )
    leverage = to_decimal(first_present(futures, ["leverage"]) or raw_payload.get("leverage"))
    margin_mode = clean_string(
        first_present(futures, ["margin_mode", "trade_mode"]) or raw_payload.get("margin_mode")
    ) or execution_spec["margin_mode"]
    position_mode = clean_string(
        first_present(futures, ["position_mode"]) or raw_payload.get("position_mode")
    ) or execution_spec["position_mode"]
    position_idx = position_idx_from_mode((position_mode or "one_way").lower(), side)
    time_in_force = normalize_time_in_force(
        first_present(entry, ["time_in_force"]) or raw_payload.get("time_in_force")
    )
    if not time_in_force:
        default_tif = normalize_time_in_force(execution_spec["execution"].get("default_time_in_force"))
        time_in_force = default_tif or ("GTC" if order_type == "Limit" else "IOC")

    tp_trigger_by = normalize_trigger_by(
        first_present(futures, ["tp_trigger_by"]) or raw_payload.get("tp_trigger_by")
    ) or normalize_trigger_by(execution_spec["execution"].get("tp_trigger_by")) or "LastPrice"
    sl_trigger_by = normalize_trigger_by(
        first_present(futures, ["sl_trigger_by"]) or raw_payload.get("sl_trigger_by")
    ) or normalize_trigger_by(execution_spec["execution"].get("sl_trigger_by")) or "LastPrice"

    instrument_result = fetch_bybit_instrument(symbol, category=category) if symbol else {"ok": False}
    instrument = instrument_result.get("instrument") if instrument_result.get("ok") else None
    if symbol and instrument is None:
        missing_fields.append("market.instrument_info")
        warnings.append(f"failed to fetch Bybit instrument info for {symbol}")
        review_required = True
    instrument_constraints = extract_bybit_instrument_constraints(instrument)

    tick_size = to_decimal(instrument_constraints.get("tick_size"))
    qty_step = to_decimal(instrument_constraints.get("qty_step"))
    min_order_qty = to_decimal(instrument_constraints.get("min_order_qty"))
    min_notional_value = to_decimal(instrument_constraints.get("min_notional_value"))
    max_instrument_leverage = to_decimal(instrument_constraints.get("max_leverage"))
    leverage_step = to_decimal(instrument_constraints.get("leverage_step"))

    pricing_reference = "payload.entry_price"
    if entry_price is None:
        if order_type == "Market" and symbol:
            ticker_result = fetch_bybit_ticker(symbol, category=category)
            if ticker_result.get("ok"):
                ticker = ticker_result.get("ticker") or {}
                entry_price = to_decimal(first_present(ticker, ["lastPrice", "markPrice", "indexPrice"]))
                pricing_reference = "bybit_ticker.last_price"
                warnings.append("market order sizing used the current Bybit ticker snapshot as the entry reference")
            else:
                missing_fields.append("entry.price")
                warnings.append("failed to fetch Bybit ticker for market-order sizing")
                review_required = True
        else:
            missing_fields.append("entry.price")
            review_required = True

    if stop_loss is None and coerce_bool(execution_spec["execution"].get("require_stop_loss")) is not False:
        missing_fields.append("risk.stop_loss")
        review_required = True

    if take_profit is None and coerce_bool(execution_spec["execution"].get("require_take_profit")) is not False:
        missing_fields.append("risk.take_profit")
        review_required = True

    if entry_price is not None and tick_size:
        entry_price = round_to_increment(entry_price, tick_size, ROUND_HALF_UP)
    if stop_loss is not None and tick_size:
        stop_loss = round_to_increment(stop_loss, tick_size, ROUND_HALF_UP)
    if take_profit is not None and tick_size:
        take_profit = round_to_increment(take_profit, tick_size, ROUND_HALF_UP)
    if take_profit_2 is not None and tick_size:
        take_profit_2 = round_to_increment(take_profit_2, tick_size, ROUND_HALF_UP)

    if entry_price is not None and stop_loss is not None:
        if direction == "long" and stop_loss >= entry_price:
            warnings.append("for a long trade, stop_loss must be below entry")
            review_required = True
        elif direction == "short" and stop_loss <= entry_price:
            warnings.append("for a short trade, stop_loss must be above entry")
            review_required = True

    if entry_price is not None and take_profit is not None:
        if direction == "long" and take_profit <= entry_price:
            warnings.append("for a long trade, take_profit must be above entry")
            review_required = True
        elif direction == "short" and take_profit >= entry_price:
            warnings.append("for a short trade, take_profit must be below entry")
            review_required = True

    if leverage is None:
        leverage = to_decimal(execution_spec["execution"].get("default_leverage"))
    max_spec_leverage = to_decimal(execution_spec["execution"].get("max_leverage"))
    if leverage_step and leverage is not None:
        leverage = round_to_increment(leverage, leverage_step, ROUND_DOWN)
    if leverage is None or leverage <= 0:
        missing_fields.append("futures.leverage")
        review_required = True
    if leverage is not None and max_spec_leverage is not None and leverage > max_spec_leverage:
        warnings.append(
            f"requested leverage {render_decimal(leverage)} exceeds execution spec max {render_decimal(max_spec_leverage)}"
        )
        review_required = True
    if leverage is not None and max_instrument_leverage is not None and leverage > max_instrument_leverage:
        warnings.append(
            f"requested leverage {render_decimal(leverage)} exceeds instrument max {render_decimal(max_instrument_leverage)}"
        )
        review_required = True

    if margin_mode:
        warnings.append("margin_mode is tracked as execution metadata and is not sent in /v5/order/create")

    account_state = resolve_account_state(account, execution_spec)
    warnings.extend(account_state["warnings"])

    stop_distance = None
    rr_multiple = None
    if entry_price is not None and stop_loss is not None:
        stop_distance = abs(entry_price - stop_loss)
        if stop_distance <= 0:
            warnings.append("entry and stop_loss must not be equal")
            review_required = True

    if stop_distance and take_profit is not None and entry_price is not None:
        reward_distance = abs(take_profit - entry_price)
        if reward_distance > 0:
            rr_multiple = reward_distance / stop_distance
            min_rr = to_decimal(execution_spec["risk"].get("min_rr"))
            if min_rr is not None and rr_multiple < min_rr:
                warnings.append(
                    f"risk/reward {render_decimal(rr_multiple)} is below execution spec minimum {render_decimal(min_rr)}"
                )
                review_required = True

    risk_amount = None
    planned_qty = explicit_qty
    qty_source = "payload" if explicit_qty is not None else ""
    if stop_distance and account_state["equity"] is not None:
        risk_pct = to_decimal(execution_spec["risk"].get("risk_per_trade_pct"))
        if risk_pct is not None:
            risk_amount = account_state["equity"] * risk_pct
            if planned_qty is None:
                planned_qty = risk_amount / stop_distance
                qty_source = "risk_model"

    if planned_qty is None:
        if explicit_qty is None:
            missing_fields.append("futures.qty_or_account.equity")
            warnings.append("qty could not be sized because neither explicit qty nor account equity was available")
            review_required = True
    elif qty_step:
        planned_qty = round_to_increment(planned_qty, qty_step, ROUND_DOWN)

    if planned_qty is not None and planned_qty <= 0:
        warnings.append("computed qty is zero after exchange step-size rounding")
        review_required = True

    notional_value = None
    risk_amount_for_qty = None
    margin_required = None
    if planned_qty is not None and entry_price is not None:
        notional_value = planned_qty * entry_price
    if planned_qty is not None and stop_distance is not None:
        risk_amount_for_qty = planned_qty * stop_distance
    if planned_qty is not None and entry_price is not None and leverage:
        margin_required = notional_value / leverage

    if planned_qty is not None and min_order_qty is not None and planned_qty < min_order_qty:
        warnings.append(
            f"qty {render_decimal(planned_qty)} is below instrument minOrderQty {render_decimal(min_order_qty)}"
        )
        review_required = True
    if notional_value is not None and min_notional_value is not None and notional_value < min_notional_value:
        warnings.append(
            f"notional {render_decimal(notional_value)} is below instrument minNotionalValue {render_decimal(min_notional_value)}"
        )
        review_required = True

    max_margin_fraction = to_decimal(execution_spec["risk"].get("max_margin_fraction_of_equity"))
    if (
        margin_required is not None
        and account_state["equity"] is not None
        and max_margin_fraction is not None
        and margin_required > account_state["equity"] * max_margin_fraction
    ):
        warnings.append(
            "required margin exceeds the execution spec margin-usage limit for this account size"
        )
        review_required = True
    if (
        margin_required is not None
        and account_state["available_balance"] is not None
        and margin_required > account_state["available_balance"]
    ):
        warnings.append("required margin exceeds available balance")
        review_required = True

    if (
        qty_source == "payload"
        and risk_amount is not None
        and risk_amount_for_qty is not None
        and risk_amount_for_qty > risk_amount
    ):
        warnings.append("explicit qty risks more than the execution spec allows for one trade")
        review_required = True

    if take_profit_2 is not None and not coerce_bool(execution_spec["execution"].get("partial_take_profit")):
        warnings.append("secondary take profit was provided but partial take-profit is disabled in the execution spec")
        review_required = True

    request_body = {
        "category": category,
        "symbol": symbol,
        "orderType": order_type,
        "timeInForce": time_in_force,
        "reduceOnly": False,
        "orderLinkId": build_order_link_id(symbol or "unknown", journal_id),
    }

    if side:
        request_body["side"] = side
    if planned_qty is not None:
        request_body["qty"] = render_decimal(planned_qty)
    if entry_price is not None and order_type == "Limit":
        request_body["price"] = render_decimal(entry_price)
    if position_idx is not None:
        request_body["positionIdx"] = position_idx
    if take_profit is not None:
        request_body["takeProfit"] = render_decimal(take_profit)
        request_body["tpTriggerBy"] = tp_trigger_by
    if stop_loss is not None:
        request_body["stopLoss"] = render_decimal(stop_loss)
        request_body["slTriggerBy"] = sl_trigger_by
    if take_profit is not None or stop_loss is not None:
        request_body["tpslMode"] = "Full"
        request_body["tpOrderType"] = "Market"
        request_body["slOrderType"] = "Market"

    pre_submit_actions = []
    if leverage and coerce_bool(execution_spec["execution"].get("auto_set_leverage")) is not False:
        pre_submit_actions.append(
            {
                "endpoint": f"{BYBIT_PRIVATE_BASE_URL}{BYBIT_LEVERAGE_PATH}",
                "request": {
                    "category": category,
                    "symbol": symbol,
                    "buyLeverage": render_decimal(leverage),
                    "sellLeverage": render_decimal(leverage),
                },
                "type": "set_leverage",
            }
        )

    status = "ready_for_submission"
    if missing_fields or review_required:
        status = "review_required"

    return {
        "venue": "bybit_testnet",
        "status": status,
        "strategy_version": RULES["strategy_version"],
        "symbol": symbol,
        "side": side,
        "paper_trade_journal_id": journal_id,
        "missing_fields": missing_fields,
        "warnings": warnings,
        "execution_spec_path": spec_result["path"],
        "bybit": {
            "base_url": BYBIT_PRIVATE_BASE_URL,
            "create_order_endpoint": f"{BYBIT_PRIVATE_BASE_URL}{BYBIT_ORDER_CREATE_PATH}",
            "create_order_path": BYBIT_ORDER_CREATE_PATH,
        },
        "request": request_body,
        "instrument_constraints": instrument_constraints,
        "account_context": {
            "account_type": account_state["account_type"],
            "balance_coin": account_state["balance_coin"],
            "equity": render_decimal(account_state["equity"]),
            "available_balance": render_decimal(account_state["available_balance"]),
            "source": account_state["source"],
        },
        "sizing": {
            "qty_source": qty_source or "unavailable",
            "risk_amount": render_decimal(risk_amount),
            "planned_qty": render_decimal(planned_qty),
            "entry_reference_price": render_decimal(entry_price),
            "entry_reference_source": pricing_reference,
            "stop_distance": render_decimal(stop_distance),
            "risk_amount_for_qty": render_decimal(risk_amount_for_qty),
            "notional_value": render_decimal(notional_value),
            "margin_required": render_decimal(margin_required),
            "rr_multiple": render_decimal(rr_multiple),
        },
        "execution_context": {
            "analysis_instrument": evaluation["normalized"]["instrument"],
            "direction": evaluation["normalized"].get("direction"),
            "leverage": render_decimal(leverage),
            "margin_mode": margin_mode,
            "position_mode": position_mode or "one_way",
            "secondary_take_profit": render_decimal(take_profit_2),
        },
        "pre_submit_actions": pre_submit_actions,
        "created_from": created_from,
        "created_at": utc_now_iso(),
    }


def build_bybit_order_proposal(raw_payload, normalized_payload, evaluation, journal_id=None):
    return build_bybit_execution_plan(
        raw_payload=raw_payload,
        normalized_payload=normalized_payload,
        evaluation=evaluation,
        journal_id=journal_id,
        created_from="tradingview_webhook",
    )






def submit_order_proposal(proposal_record):
    control_state = resolve_control_state("order_submission")
    if control_state["effective_paused"]:
        return {
            "ok": False,
            "status": "submission_paused",
            "error": control_state["effective_reason"] or "order submission is paused by control state",
            "control_state": control_state,
        }

    if not BYBIT_ENABLE_PRIVATE_SUBMIT:
        return {
            "ok": False,
            "status": "submission_disabled",
            "error": "Bybit private submission is not enabled",
        }

    if not BYBIT_API_KEY or not BYBIT_API_SECRET:
        return {
            "ok": False,
            "status": "submission_disabled",
            "error": "BYBIT_API_KEY and BYBIT_API_SECRET are required",
        }

    proposal = proposal_record["proposal"]
    if proposal.get("venue") != "bybit_testnet":
        return {
            "ok": False,
            "status": "submit_failed",
            "error": "proposal venue is not bybit_testnet",
        }

    if proposal_record.get("status") != "ready_for_submission":
        return {
            "ok": False,
            "status": "submit_failed",
            "error": "proposal is not ready_for_submission",
        }

    pre_submit_results = []
    for action in proposal.get("pre_submit_actions", []):
        action_type = action.get("type")
        endpoint = action.get("endpoint", "")
        path = urlparse(endpoint).path if endpoint else ""
        result = bybit_post(path, action.get("request", {}))
        pre_submit_results.append(
            {
                "type": action_type,
                "endpoint": endpoint,
                "request": action.get("request", {}),
                "result": result,
            }
        )
        if not result["ok"]:
            return {
                "ok": False,
                "status": "submit_failed",
                "error": f"pre-submit action failed: {action_type}",
                "pre_submit_results": pre_submit_results,
            }

    create_result = bybit_post(BYBIT_ORDER_CREATE_PATH, proposal.get("request", {}))
    if not create_result["ok"]:
        return {
            "ok": False,
            "status": "submit_failed",
            "error": "Bybit create-order request failed",
            "pre_submit_results": pre_submit_results,
            "create_order_result": create_result,
        }

    return {
        "ok": True,
        "status": "submitted_testnet",
        "pre_submit_results": pre_submit_results,
        "create_order_result": create_result,
        "submitted_at": utc_now_iso(),
    }


class TradingAPIHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    store = PaperTradeStore(DB_PATH)

    def log_message(self, _format, *args):
        return

    def _send_cors_headers(self):
        # The local dashboard runs on a different loopback port, so the
        # paper-trading API must explicitly allow browser cross-origin reads.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, status_code, payload):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status_code)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_detail(self, path, getter, label):
        """Handle a ``/prefix/{id}`` detail route: fetch one record by the path
        suffix and respond ``404`` if missing, otherwise ``200`` with the record.

        ``getter`` is a callable taking the id and returning the record or None.
        """
        key = path.split("/")[-1]
        record = getter(key)
        if record is None:
            self._send_json(404, {"error": f"{label} {key} not found"})
            return
        self._send_json(200, record)

    def _send_filtered_events(self, params, lister, filter_keys):
        """Handle a filtered event-list route: coerce ``limit`` from query
        params, extract each named filter (passing ``value or None``), and
        respond ``200`` with ``{"items": lister(limit=limit, **filters)}``.

        ``lister`` is a store method accepting ``limit`` plus the filter keys
        as keyword arguments; ``filter_keys`` is the per-route set of filters.
        """
        limit = coerce_query_limit(params.get("limit", [None])[0], 100)
        filters = {
            key: clean_string(params.get(key, [""])[0]) or None
            for key in filter_keys
        }
        self._send_json(200, {"items": lister(limit=limit, **filters)})

    def _send_runtime(self, params, getter, lister, label):
        """Handle a ``/prefix/runtime`` dual-mode route: if a ``runtime_key``
        query param is present, return that single record (``404`` if missing);
        otherwise return the full runtime list as ``{"items": ...}``.
        """
        runtime_key = clean_string(params.get("runtime_key", [""])[0])
        if runtime_key:
            record = getter(runtime_key)
            if record is None:
                self._send_json(404, {"error": f"{label} runtime {runtime_key} not found"})
                return
            self._send_json(200, record)
            return
        self._send_json(200, {"items": lister()})

    def _send_sse_headers(self):
        self.send_response(200)
        self._send_cors_headers()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

    def _send_sse_event(self, event_name, payload):
        raw_payload = json.dumps(payload, separators=(",", ":"))
        lines = [f"event: {event_name}"]
        for line in raw_payload.splitlines() or ["{}"]:
            lines.append(f"data: {line}")
        lines.append("")
        body = "\n".join(lines).encode("utf-8")
        self.wfile.write(body)
        self.wfile.flush()

    def _enforce_operator_auth(self, method, path):
        auth_result = validate_operator_request_auth(self.headers, method=method, path=path)
        if auth_result.get("ok"):
            return True
        response = {
            "error": auth_result.get("error") or "operator auth required",
            "operator_auth_enabled": True,
            "details": auth_result.get("details") or {},
        }
        self._send_json(int(auth_result.get("status_code") or 401), response)
        return False

    def _read_json_body(self):
        length = self.headers.get("Content-Length")
        if not length:
            return None, "missing Content-Length header"

        try:
            size = int(length)
        except ValueError:
            return None, "invalid Content-Length header"

        raw = self.rfile.read(size)
        try:
            return json.loads(raw.decode("utf-8")), None
        except json.JSONDecodeError as exc:
            return None, f"invalid JSON body: {exc.msg}"

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _control_room_limits(self, params):
        return {
            "scan_limit": coerce_query_limit(
                params.get("scan_limit", [None])[0],
                CONTROL_ROOM_DEFAULTS["scan_limit"],
            ),
            "proposal_limit": coerce_query_limit(
                params.get("proposal_limit", [None])[0],
                CONTROL_ROOM_DEFAULTS["proposal_limit"],
            ),
            "execution_limit": coerce_query_limit(
                params.get("execution_limit", [None])[0],
                CONTROL_ROOM_DEFAULTS["execution_limit"],
            ),
            "execution_action_limit": coerce_query_limit(
                params.get("execution_action_limit", [None])[0],
                CONTROL_ROOM_DEFAULTS["execution_action_limit"],
            ),
            "auto_event_limit": coerce_query_limit(
                params.get("auto_event_limit", [None])[0],
                CONTROL_ROOM_DEFAULTS["auto_event_limit"],
            ),
            "concept_event_limit": coerce_query_limit(
                params.get("concept_event_limit", [None])[0],
                CONTROL_ROOM_DEFAULTS["concept_event_limit"],
            ),
            "timeline_limit": coerce_query_limit(
                params.get("timeline_limit", [None])[0],
                CONTROL_ROOM_DEFAULTS["timeline_limit"],
            ),
        }

    def _handle_health_get(self, _params):
        self._send_json(200, build_health_payload())

    def _handle_ready_get(self, _params):
        readiness = build_readiness_payload()
        self._send_json(readiness_http_status(readiness), readiness)

    def _handle_rules_get(self, _params):
        self._send_json(200, RULES)

    def _handle_control_room_snapshot_get(self, params):
        self._send_json(200, build_control_room_snapshot(**self._control_room_limits(params)))

    def _handle_control_room_timeline_get(self, params):
        limit = coerce_query_limit(
            params.get("limit", [None])[0],
            CONTROL_ROOM_DEFAULTS["timeline_limit"],
        )
        self._send_json(200, {"items": build_control_room_timeline(limit=limit)})

    def _handle_control_room_stream_get(self, params):
        self._send_sse_headers()
        try:
            self._send_sse_event(
                "status",
                {
                    "connected_at": utc_now_iso(),
                    "poll_seconds": CONTROL_ROOM_STREAM_POLL_SECONDS,
                },
            )
            while True:
                self._send_sse_event(
                    "snapshot",
                    build_control_room_snapshot(**self._control_room_limits(params)),
                )
                time.sleep(CONTROL_ROOM_STREAM_POLL_SECONDS)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            try:
                self._send_sse_event(
                    "stream-error",
                    {
                        "message": str(exc),
                        "raised_at": utc_now_iso(),
                    },
                )
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _handle_execution_spec_get(self, _params):
        spec_result = load_execution_spec()
        status_code = 200 if spec_result["ok"] else 500
        self._send_json(status_code, spec_result)

    def _handle_risk_controls_policy_get(self, _params):
        policy_result = load_risk_control_policy()
        status_code = 200 if policy_result["ok"] else 500
        self._send_json(status_code, policy_result)

    def _dispatch_core_get_route(self, path, params):
        route_handlers = {
            "/health": self._handle_health_get,
            "/ready": self._handle_ready_get,
            "/v1/rules": self._handle_rules_get,
            "/v1/control-room/snapshot": self._handle_control_room_snapshot_get,
            "/v1/control-room/timeline": self._handle_control_room_timeline_get,
            "/v1/control-room/stream": self._handle_control_room_stream_get,
            "/v1/execution/spec": self._handle_execution_spec_get,
            "/v1/risk-controls/policy": self._handle_risk_controls_policy_get,
        }
        handler = route_handlers.get(path)
        if handler is None:
            return False
        handler(params)
        return True

    def _handle_control_state_post(self, payload):
        control_key = normalize_control_key(payload.get("control_key"))
        paused = coerce_bool(payload.get("paused"))
        if paused is None:
            self._send_json(400, {"error": "paused must be a boolean"})
            return
        event_id = self.store.set_control_state(
            control_key=control_key,
            paused=paused,
            reason=payload.get("reason"),
            updated_by=payload.get("updated_by"),
            metadata=payload.get("metadata"),
        )
        record = self.store.get_control_state(control_key)
        record["effective"] = resolve_control_state(control_key)
        record["event_id"] = event_id
        self._send_json(200, record)

    def _handle_control_kill_switch_post(self, payload):
        paused = coerce_bool(payload.get("paused"))
        if paused is None:
            paused = True
        event_id = self.store.set_control_state(
            control_key="global",
            paused=paused,
            reason=payload.get("reason"),
            updated_by=payload.get("updated_by"),
            metadata=payload.get("metadata"),
        )
        record = self.store.get_control_state("global")
        record["effective"] = resolve_control_state("global")
        record["event_id"] = event_id
        self._send_json(200, record)

    def _handle_paper_trade_evaluate_post(self, payload):
        evaluation = evaluate_payload(payload)
        auto_log = coerce_bool(payload.get("auto_log"))
        if auto_log is None:
            auto_log = True
        journal_id = None
        if auto_log:
            journal_id = self.store.create_entry(payload, evaluation)
            evaluation["journal_id"] = journal_id
        signal_trace_id = persist_signal_trace_for_evaluation(
            source_path="daemon",
            payload=payload,
            evaluation=evaluation,
            journal_id=journal_id,
            reference_timestamp=clean_string(payload.get("reference_at")),
        )
        evaluation["signal_trace_id"] = signal_trace_id
        self._send_json(200, evaluation)

    def _handle_execution_plan_post(self, payload):
        evaluation_payload = {
            "instrument": payload.get("instrument"),
            "provider": clean_string(payload.get("provider")) or "execution-plan",
            "session": payload.get("session"),
            "direction": payload.get("direction"),
            "weekend": payload.get("weekend"),
            "reference_at": payload.get("reference_at"),
            "source_mode": clean_string(payload.get("source_mode")) or "manual_assertion",
            "visual_analysis_state": payload.get("visual_analysis_state"),
            "chart_url": payload.get("chart_url"),
            "screenshot_paths": payload.get("screenshot_paths"),
            "timeframes": payload.get("timeframes"),
            "checklist": payload.get("checklist"),
            "notes": payload.get("notes"),
        }
        evaluation = evaluate_payload(evaluation_payload)

        auto_log = coerce_bool(payload.get("auto_log"))
        if auto_log is None:
            auto_log = False
        auto_save_proposal = coerce_bool(payload.get("auto_save_proposal"))
        if auto_save_proposal is None:
            auto_save_proposal = False

        journal_id = None
        if auto_log:
            journal_id = self.store.create_entry(evaluation_payload, evaluation)
            evaluation["journal_id"] = journal_id
        signal_trace_id = persist_signal_trace_for_evaluation(
            source_path="daemon",
            payload=evaluation_payload,
            evaluation=evaluation,
            journal_id=journal_id,
            reference_timestamp=clean_string(evaluation_payload.get("reference_at")),
        )
        evaluation["signal_trace_id"] = signal_trace_id

        proposal = build_bybit_execution_plan(
            raw_payload=payload,
            normalized_payload={},
            evaluation=evaluation,
            journal_id=journal_id,
            created_from="execution_plan",
        )

        proposal_id = None
        if proposal is not None and auto_save_proposal:
            proposal_id, proposal = self.store.create_order_proposal(
                proposal,
                journal_id=journal_id,
                webhook_id=None,
            )

        self._send_json(
            200,
            {
                "paper_trade_evaluation": evaluation,
                "order_proposal": proposal,
                "proposal_id": proposal_id,
                "journal_id": journal_id,
            },
        )

    def _handle_supervisor_scan_post(self, payload):
        try:
            limit = max(1, min(200, int(payload.get("limit", 25))))
        except (TypeError, ValueError):
            limit = 25
        sync_active = coerce_bool(payload.get("sync_active"))
        if sync_active is None:
            sync_active = True
        include_inactive = coerce_bool(payload.get("include_inactive"))
        if include_inactive is None:
            include_inactive = False

        result = run_supervisor_scan(
            limit=limit,
            sync_active=sync_active,
            include_inactive=include_inactive,
        )
        self._send_json(200, result)

    def _handle_ict_scan_post(self, payload):
        symbol = normalize_instrument(payload.get("instrument"))
        if not symbol:
            self._send_json(400, {"error": "instrument is required"})
            return
        category = clean_string(payload.get("category")) or "linear"
        auto_log = coerce_bool(payload.get("auto_log"))
        if auto_log is None:
            auto_log = True
        record_history = coerce_bool(payload.get("record_history"))
        if record_history is None:
            record_history = False

        scan_result = build_bybit_heuristic_scan(
            symbol=symbol,
            category=category,
            auto_log=auto_log,
        )
        if record_history:
            scan_result["scan_record_id"] = self.store.create_scan_history_entry(
                source="ict-v1",
                instrument=symbol,
                category=category,
                scan_result=scan_result,
            )
        persist_signal_trace_for_scan_result(
            scan_result,
            source_path="scanner",
            category=category,
        )
        if not scan_result["ok"]:
            self._send_json(scan_result["status"], scan_result)
            return
        self._send_json(200, scan_result)

    def _normalize_watchlist_instruments(self, instruments):
        if instruments is None:
            return list(RULES["allowed_instruments"]), None
        if isinstance(instruments, list):
            normalized = [normalize_instrument(item) for item in instruments]
            normalized = [item for item in normalized if item]
            if normalized:
                return normalized, None
            return None, {"error": "at least one instrument is required"}
        return None, {"error": "instruments must be a list"}

    def _handle_watchlist_scan_post(self, payload):
        normalized_instruments, error = self._normalize_watchlist_instruments(payload.get("instruments"))
        if error:
            self._send_json(400, error)
            return

        category = clean_string(payload.get("category")) or "linear"
        auto_log_candidates = coerce_bool(payload.get("auto_log_candidates"))
        if auto_log_candidates is None:
            auto_log_candidates = False
        persistent_dedupe = coerce_bool(payload.get("persistent_dedupe"))
        if persistent_dedupe is None:
            persistent_dedupe = True
        record_history = coerce_bool(payload.get("record_history"))
        if record_history is None:
            record_history = True

        result = run_watchlist_scan(
            instruments=normalized_instruments,
            category=category,
            auto_log_candidates=auto_log_candidates,
            persistent_dedupe=persistent_dedupe,
            record_history=record_history,
            dedupe_state=None,
        )
        self._send_json(200, result)

    def _handle_shadow_watchlist_scan_post(self, payload):
        normalized_instruments, error = self._normalize_watchlist_instruments(payload.get("instruments"))
        if error:
            self._send_json(400, error)
            return

        category = clean_string(payload.get("category")) or "linear"
        record_history = coerce_bool(payload.get("record_history"))
        if record_history is None:
            record_history = True
        shadow_session_id = clean_string(payload.get("shadow_session_id")) or build_shadow_session_id()

        result = run_watchlist_scan(
            instruments=normalized_instruments,
            category=category,
            auto_log_candidates=False,
            persistent_dedupe=True,
            record_history=record_history,
            dedupe_state=None,
            shadow_mode=True,
            shadow_session_id=shadow_session_id,
        )
        self._send_json(200, result)

    def _handle_replay_scan_post(self, payload):
        symbol = normalize_instrument(payload.get("instrument"))
        if not symbol:
            self._send_json(400, {"error": "instrument is required"})
            return
        category = clean_string(payload.get("category")) or "linear"
        auto_log_candidates = coerce_bool(payload.get("auto_log_candidates"))
        if auto_log_candidates is None:
            auto_log_candidates = False
        record_history = coerce_bool(payload.get("record_history"))
        if record_history is None:
            record_history = False
        tradable_only = coerce_bool(payload.get("tradable_only")) is True
        try:
            max_steps = int(payload.get("max_steps", 100))
        except (TypeError, ValueError):
            self._send_json(400, {"error": "max_steps must be an integer"})
            return
        try:
            step_stride = int(payload.get("step_stride", 1))
        except (TypeError, ValueError):
            self._send_json(400, {"error": "step_stride must be an integer"})
            return

        result = run_bybit_replay_scan(
            symbol=symbol,
            category=category,
            auto_log_candidates=auto_log_candidates,
            record_history=record_history,
            max_steps=max_steps,
            step_stride=step_stride,
            tradable_only=tradable_only,
        )
        if not result["ok"]:
            self._send_json(result["status"], result)
            return
        self._send_json(200, result)

    def _dispatch_core_post_route(self, path, payload):
        route_handlers = {
            "/v1/control/state": self._handle_control_state_post,
            "/v1/control/kill-switch": self._handle_control_kill_switch_post,
            "/v1/paper-trades/evaluate": self._handle_paper_trade_evaluate_post,
            "/v1/execution/plan": self._handle_execution_plan_post,
            "/v1/supervisor/scan": self._handle_supervisor_scan_post,
            "/v1/scans/bybit/ict-v1": self._handle_ict_scan_post,
            "/v1/scans/bybit/watchlist": self._handle_watchlist_scan_post,
            "/v1/scans/bybit/watchlist/shadow": self._handle_shadow_watchlist_scan_post,
            "/v1/scans/bybit/replay": self._handle_replay_scan_post,
        }
        handler = route_handlers.get(path)
        if handler is None:
            return False
        handler(payload)
        return True

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)

        if self._dispatch_core_get_route(path, params):
            return

        if path == "/v1/supervisor/active":
            limit = 25
            if "limit" in params:
                try:
                    limit = max(1, min(200, int(params["limit"][0])))
                except ValueError:
                    pass
            result = run_supervisor_scan(limit=limit, sync_active=False, include_inactive=False)
            self._send_json(200, result)
            return

        if path == "/v1/supervisor/runtime":
            self._send_runtime(params, self.store.get_supervisor_runtime, self.store.list_supervisor_runtime, "supervisor")
            return

        if path.startswith("/v1/supervisor/runtime/"):
            self._send_detail(path, self.store.get_supervisor_runtime, "supervisor runtime")
            return

            if path == "/v1/supervisor/events":
                self._send_filtered_events(params, self.store.list_supervisor_events, ["runtime_key", "proposal_id", "severity", "event_type"])
                return

        if path.startswith("/v1/supervisor/events/"):
            self._send_detail(path, self.store.get_supervisor_event, "supervisor event")
            return

        if path == "/v1/private-stream/runtime":
            self._send_runtime(params, self.store.get_private_stream_runtime, self.store.list_private_stream_runtime, "private stream")
            return

        if path.startswith("/v1/private-stream/runtime/"):
            self._send_detail(path, self.store.get_private_stream_runtime, "private stream runtime")
            return

            if path == "/v1/private-stream/events":
                self._send_filtered_events(params, self.store.list_private_stream_events, ["runtime_key", "proposal_id", "severity", "event_type"])
                return

        if path.startswith("/v1/private-stream/events/"):
            self._send_detail(path, self.store.get_private_stream_event, "private stream event")
            return

        if path == "/v1/operations/status":
            watchlist_stale_after_seconds = params.get("watchlist_stale_after_seconds", [None])[0]
            supervisor_stale_after_seconds = params.get("supervisor_stale_after_seconds", [None])[0]
            private_stream_stale_after_seconds = params.get("private_stream_stale_after_seconds", [None])[0]
            auto_execution_stale_after_seconds = params.get("auto_execution_stale_after_seconds", [None])[0]
            trade_management_stale_after_seconds = params.get(
                "trade_management_stale_after_seconds", [None]
            )[0]
            self._send_json(
                200,
                build_operations_status(
                    watchlist_stale_after_seconds=watchlist_stale_after_seconds,
                    supervisor_stale_after_seconds=supervisor_stale_after_seconds,
                    private_stream_stale_after_seconds=private_stream_stale_after_seconds,
                    auto_execution_stale_after_seconds=auto_execution_stale_after_seconds,
                    trade_management_stale_after_seconds=trade_management_stale_after_seconds,
                ),
            )
            return

        if path == "/v1/operations/runtime":
            self._send_runtime(params, self.store.get_operations_runtime, self.store.list_operations_runtime, "operations")
            return

        if path.startswith("/v1/operations/runtime/"):
            self._send_detail(path, self.store.get_operations_runtime, "operations runtime")
            return

            if path == "/v1/operations/events":
                self._send_filtered_events(params, self.store.list_operations_events, ["runtime_key", "component_key", "severity", "event_type"])
                return

        if path.startswith("/v1/operations/events/"):
            self._send_detail(path, self.store.get_operations_event, "operations event")
            return

        if path == "/v1/auto-execution/policy":
            policy_result = load_auto_execution_policy()
            status_code = 200 if policy_result["ok"] else 500
            self._send_json(status_code, policy_result)
            return

        if path == "/v1/auto-execution/runtime":
            self._send_runtime(params, self.store.get_auto_execution_runtime, self.store.list_auto_execution_runtime, "auto execution")
            return

        if path.startswith("/v1/auto-execution/runtime/"):
            self._send_detail(path, self.store.get_auto_execution_runtime, "auto execution runtime")
            return

            if path == "/v1/auto-execution/events":
                self._send_filtered_events(params, self.store.list_auto_execution_events, ["runtime_key", "instrument", "proposal_id", "severity", "event_type"])
                return

        if path.startswith("/v1/auto-execution/events/"):
            self._send_detail(path, self.store.get_auto_execution_event, "auto execution event")
            return

        if path == "/v1/trade-management/policy":
            policy_result = load_trade_management_policy()
            status_code = 200 if policy_result["ok"] else 500
            self._send_json(status_code, policy_result)
            return

        if path == "/v1/trade-management/runtime":
            self._send_runtime(params, self.store.get_trade_management_runtime, self.store.list_trade_management_runtime, "trade management")
            return

        if path.startswith("/v1/trade-management/runtime/"):
            self._send_detail(path, self.store.get_trade_management_runtime, "trade management runtime")
            return

            if path == "/v1/trade-management/events":
                self._send_filtered_events(params, self.store.list_trade_management_events, ["runtime_key", "proposal_id", "symbol", "severity", "event_type"])
                return

        if path.startswith("/v1/trade-management/events/"):
            self._send_detail(path, self.store.get_trade_management_event, "trade management event")
            return

        if path == "/v1/concept/runtime":
            self._send_runtime(params, self.store.get_concept_runtime, self.store.list_concept_runtime, "concept")
            return

        if path.startswith("/v1/concept/runtime/"):
            self._send_detail(path, self.store.get_concept_runtime, "concept runtime")
            return

            if path == "/v1/concept/events":
                self._send_filtered_events(params, self.store.list_concept_events, ["runtime_key", "concept_id", "severity", "event_type"])
                return

        if path.startswith("/v1/concept/events/"):
            self._send_detail(path, self.store.get_concept_event, "concept event")
            return

        if path == "/v1/concept/brief":
            tradable_only = coerce_bool(params.get("tradable_only", [""])[0]) is True
            result = build_concept_brief_response(
                state_dir=current_stack_state_dir(),
                db_path=DB_PATH,
                event_limit=coerce_query_limit(params.get("event_limit", [None])[0], 25),
                proposal_limit=coerce_query_limit(params.get("proposal_limit", [None])[0], 10),
                action_limit=coerce_query_limit(params.get("action_limit", [None])[0], 10),
                scan_limit=coerce_query_limit(params.get("scan_limit", [None])[0], 50),
                instruments=clean_string(params.get("instruments", ["BTCUSDT,ETHUSDT"])[0]) or "BTCUSDT,ETHUSDT",
                category=clean_string(params.get("category", ["linear"])[0]) or "linear",
                max_steps=coerce_query_limit(params.get("max_steps", [None])[0], 12, maximum=500),
                step_stride=coerce_query_limit(params.get("step_stride", [None])[0], 3, maximum=100),
                tradable_only=tradable_only,
                policy_path=clean_string(params.get("policy_path", [""])[0]) or str(BASE_DIR / "config" / "concept_decision_policy.json"),
            )
            self._send_json(200, result)
            return

        if path == "/v1/concept/revisions/brief":
            tradable_only = coerce_bool(params.get("tradable_only", [""])[0]) is True
            result = build_concept_revision_brief_response(
                state_dir=current_stack_state_dir(),
                db_path=DB_PATH,
                event_limit=coerce_query_limit(params.get("event_limit", [None])[0], 25),
                proposal_limit=coerce_query_limit(params.get("proposal_limit", [None])[0], 10),
                action_limit=coerce_query_limit(params.get("action_limit", [None])[0], 10),
                scan_limit=coerce_query_limit(params.get("scan_limit", [None])[0], 50),
                instruments=clean_string(params.get("instruments", ["BTCUSDT,ETHUSDT"])[0]) or "BTCUSDT,ETHUSDT",
                category=clean_string(params.get("category", ["linear"])[0]) or "linear",
                max_steps=coerce_query_limit(params.get("max_steps", [None])[0], 12, maximum=500),
                step_stride=coerce_query_limit(params.get("step_stride", [None])[0], 3, maximum=100),
                tradable_only=tradable_only,
                policy_path=clean_string(params.get("policy_path", [""])[0]) or str(BASE_DIR / "config" / "concept_decision_policy.json"),
                artifact_limit=coerce_query_limit(params.get("artifact_limit", [None])[0], 20, maximum=200),
                top_limit=coerce_query_limit(params.get("top_limit", [None])[0], 3, maximum=10),
            )
            self._send_json(200, result)
            return

        if path == "/v1/concept/acceptance/brief":
            tradable_only = coerce_bool(params.get("tradable_only", [""])[0]) is True
            result = build_concept_acceptance_brief_response(
                state_dir=current_stack_state_dir(),
                db_path=DB_PATH,
                event_limit=coerce_query_limit(params.get("event_limit", [None])[0], 25),
                proposal_limit=coerce_query_limit(params.get("proposal_limit", [None])[0], 10),
                action_limit=coerce_query_limit(params.get("action_limit", [None])[0], 10),
                scan_limit=coerce_query_limit(params.get("scan_limit", [None])[0], 50),
                instruments=clean_string(params.get("instruments", ["BTCUSDT,ETHUSDT"])[0]) or "BTCUSDT,ETHUSDT",
                category=clean_string(params.get("category", ["linear"])[0]) or "linear",
                max_steps=coerce_query_limit(params.get("max_steps", [None])[0], 12, maximum=500),
                step_stride=coerce_query_limit(params.get("step_stride", [None])[0], 3, maximum=100),
                tradable_only=tradable_only,
                policy_path=clean_string(params.get("policy_path", [""])[0]) or str(BASE_DIR / "config" / "concept_decision_policy.json"),
                artifact_limit=coerce_query_limit(params.get("artifact_limit", [None])[0], 20, maximum=200),
                top_limit=coerce_query_limit(params.get("top_limit", [None])[0], 3, maximum=10),
            )
            self._send_json(200, result)
            return

        if path == "/v1/concept/acceptance/summary":
            tradable_only = coerce_bool(params.get("tradable_only", [""])[0]) is True
            result = build_concept_acceptance_brief_response(
                state_dir=current_stack_state_dir(),
                db_path=DB_PATH,
                event_limit=coerce_query_limit(params.get("event_limit", [None])[0], 25),
                proposal_limit=coerce_query_limit(params.get("proposal_limit", [None])[0], 10),
                action_limit=coerce_query_limit(params.get("action_limit", [None])[0], 10),
                scan_limit=coerce_query_limit(params.get("scan_limit", [None])[0], 50),
                instruments=clean_string(params.get("instruments", ["BTCUSDT,ETHUSDT"])[0]) or "BTCUSDT,ETHUSDT",
                category=clean_string(params.get("category", ["linear"])[0]) or "linear",
                max_steps=coerce_query_limit(params.get("max_steps", [None])[0], 12, maximum=500),
                step_stride=coerce_query_limit(params.get("step_stride", [None])[0], 3, maximum=100),
                tradable_only=tradable_only,
                policy_path=clean_string(params.get("policy_path", [""])[0]) or str(BASE_DIR / "config" / "concept_decision_policy.json"),
                artifact_limit=coerce_query_limit(params.get("artifact_limit", [None])[0], 20, maximum=200),
                top_limit=coerce_query_limit(params.get("top_limit", [None])[0], 3, maximum=10),
            )
            self._send_json(
                200,
                {
                    "acceptance_summary": result.get("acceptance_summary"),
                    "acceptance_gate": result.get("acceptance_gate"),
                    "concept_id": result.get("concept_id"),
                    "generated_at": result.get("generated_at"),
                },
            )
            return

        if path == "/v1/concept/acceptance/history":
            runtime = self.store.get_concept_runtime("main")
            if runtime is None:
                runtimes = self.store.list_concept_runtime()
                runtime = runtimes[0] if runtimes else None
            state = runtime.get("state") if isinstance((runtime or {}).get("state"), dict) else {}
            summary = runtime.get("last_summary") if isinstance((runtime or {}).get("last_summary"), dict) else {}
            history = state.get("acceptance_history") if isinstance(state.get("acceptance_history"), list) else None
            if not isinstance(history, list):
                history = summary.get("acceptance_history") if isinstance(summary.get("acceptance_history"), list) else []
            limit = coerce_query_limit(params.get("limit", [None])[0], 20, maximum=200)
            self._send_json(
                200,
                {
                    "generated_at": utc_now_iso(),
                    "runtime_key": clean_string((runtime or {}).get("runtime_key")) or "main",
                    "items": list(history or [])[:limit],
                },
            )
            return

        if path == "/v1/concept/stage7/decision-brief":
            tradable_only = coerce_bool(params.get("tradable_only", [""])[0]) is True
            result = build_concept_stage7_decision_brief_response(
                state_dir=current_stack_state_dir(),
                db_path=DB_PATH,
                event_limit=coerce_query_limit(params.get("event_limit", [None])[0], 25),
                proposal_limit=coerce_query_limit(params.get("proposal_limit", [None])[0], 10),
                action_limit=coerce_query_limit(params.get("action_limit", [None])[0], 10),
                scan_limit=coerce_query_limit(params.get("scan_limit", [None])[0], 50),
                instruments=clean_string(params.get("instruments", ["BTCUSDT,ETHUSDT"])[0]) or "BTCUSDT,ETHUSDT",
                category=clean_string(params.get("category", ["linear"])[0]) or "linear",
                max_steps=coerce_query_limit(params.get("max_steps", [None])[0], 12, maximum=500),
                step_stride=coerce_query_limit(params.get("step_stride", [None])[0], 3, maximum=100),
                tradable_only=tradable_only,
                policy_path=clean_string(params.get("policy_path", [""])[0]) or str(BASE_DIR / "config" / "concept_decision_policy.json"),
                artifact_limit=coerce_query_limit(params.get("artifact_limit", [None])[0], 20, maximum=200),
                top_limit=coerce_query_limit(params.get("top_limit", [None])[0], 3, maximum=10),
            )
            self._send_json(200, result)
            return

        if path == "/v1/concept/stage7/summary":
            tradable_only = coerce_bool(params.get("tradable_only", [""])[0]) is True
            result = build_concept_stage7_decision_brief_response(
                state_dir=current_stack_state_dir(),
                db_path=DB_PATH,
                event_limit=coerce_query_limit(params.get("event_limit", [None])[0], 25),
                proposal_limit=coerce_query_limit(params.get("proposal_limit", [None])[0], 10),
                action_limit=coerce_query_limit(params.get("action_limit", [None])[0], 10),
                scan_limit=coerce_query_limit(params.get("scan_limit", [None])[0], 50),
                instruments=clean_string(params.get("instruments", ["BTCUSDT,ETHUSDT"])[0]) or "BTCUSDT,ETHUSDT",
                category=clean_string(params.get("category", ["linear"])[0]) or "linear",
                max_steps=coerce_query_limit(params.get("max_steps", [None])[0], 12, maximum=500),
                step_stride=coerce_query_limit(params.get("step_stride", [None])[0], 3, maximum=100),
                tradable_only=tradable_only,
                policy_path=clean_string(params.get("policy_path", [""])[0]) or str(BASE_DIR / "config" / "concept_decision_policy.json"),
                artifact_limit=coerce_query_limit(params.get("artifact_limit", [None])[0], 20, maximum=200),
                top_limit=coerce_query_limit(params.get("top_limit", [None])[0], 3, maximum=10),
            )
            self._send_json(
                200,
                {
                    "generated_at": result.get("generated_at"),
                    "concept_id": result.get("concept_id"),
                    "stage7_gate": result.get("stage7_gate"),
                    "decision_summary": {
                        "decision_artifact_count": result.get("decision_artifact_count"),
                        "latest_stage7_review_id": result.get("latest_stage7_review_id"),
                        "latest_stage7_verdict": result.get("latest_stage7_verdict"),
                        "latest_stage7_artifact": result.get("latest_stage7_artifact"),
                        "decision_takeaway": result.get("decision_takeaway"),
                        "decision_action": result.get("decision_action"),
                    },
                    "acceptance_summary": result.get("acceptance_summary"),
                    "compare_summary": result.get("compare_summary"),
                },
            )
            return

        if path == "/v1/concept/stage-status":
            tradable_only = coerce_bool(params.get("tradable_only", [""])[0]) is True
            stage7_result = build_concept_stage7_decision_brief_response(
                state_dir=current_stack_state_dir(),
                db_path=DB_PATH,
                event_limit=coerce_query_limit(params.get("event_limit", [None])[0], 25),
                proposal_limit=coerce_query_limit(params.get("proposal_limit", [None])[0], 10),
                action_limit=coerce_query_limit(params.get("action_limit", [None])[0], 10),
                scan_limit=coerce_query_limit(params.get("scan_limit", [None])[0], 50),
                instruments=clean_string(params.get("instruments", ["BTCUSDT,ETHUSDT"])[0]) or "BTCUSDT,ETHUSDT",
                category=clean_string(params.get("category", ["linear"])[0]) or "linear",
                max_steps=coerce_query_limit(params.get("max_steps", [None])[0], 12, maximum=500),
                step_stride=coerce_query_limit(params.get("step_stride", [None])[0], 3, maximum=100),
                tradable_only=tradable_only,
                policy_path=clean_string(params.get("policy_path", [""])[0]) or str(BASE_DIR / "config" / "concept_decision_policy.json"),
                artifact_limit=coerce_query_limit(params.get("artifact_limit", [None])[0], 20, maximum=200),
                top_limit=coerce_query_limit(params.get("top_limit", [None])[0], 3, maximum=10),
            )
            status = build_concept_stage_status(
                stage7_result.get("acceptance_summary"),
                {
                    **(stage7_result.get("latest_stage7_artifact") and {
                        "latest_stage7_artifact": stage7_result.get("latest_stage7_artifact")
                    } or {}),
                    "decision_artifact_count": stage7_result.get("decision_artifact_count"),
                    "latest_stage7_review_id": stage7_result.get("latest_stage7_review_id"),
                    "latest_stage7_verdict": stage7_result.get("latest_stage7_verdict"),
                    "decision_takeaway": stage7_result.get("decision_takeaway"),
                    "decision_action": stage7_result.get("decision_action"),
                    "stage7_gate": stage7_result.get("stage7_gate"),
                },
                stage7_result.get("compare_summary"),
            )
            self._send_json(
                200,
                {
                    "generated_at": stage7_result.get("generated_at"),
                    "concept_id": stage7_result.get("concept_id"),
                    "stage_status": status,
                    "acceptance_summary": stage7_result.get("acceptance_summary"),
                    "stage7_gate": stage7_result.get("stage7_gate"),
                },
            )
            return

        if path == "/v1/concept/reviews":
            limit = coerce_query_limit(params.get("limit", [None])[0], 100)
            concept_id = clean_string(params.get("concept_id", [""])[0])
            source = clean_string(params.get("source", [""])[0])
            review_kind = clean_string(params.get("review_kind", [""])[0])
            self._send_json(
                200,
                {
                    "items": self.store.list_concept_reviews(
                        limit=limit,
                        concept_id=concept_id or None,
                        source=source or None,
                        review_kind=review_kind or None,
                    )
                },
            )
            return

        if path.startswith("/v1/concept/reviews/"):
            self._send_detail(path, self.store.get_concept_review, "concept review")
            return

        if path == "/v1/concept/revisions":
            limit = coerce_query_limit(params.get("limit", [None])[0], 100)
            concept_id = clean_string(params.get("concept_id", [""])[0])
            source = clean_string(params.get("source", [""])[0])
            focus = clean_string(params.get("focus", [""])[0])
            self._send_json(
                200,
                {
                    "items": self.store.list_concept_revisions(
                        limit=limit,
                        concept_id=concept_id or None,
                        source=source or None,
                        focus=focus or None,
                    )
                },
            )
            return

        if path == "/v1/concept/revisions/summary":
            limit = coerce_query_limit(params.get("limit", [None])[0], 100)
            concept_id = clean_string(params.get("concept_id", [""])[0])
            review_summaries = self.store.list_concept_reviews(limit=limit, concept_id=concept_id or None)
            review_records = [
                self.store.get_concept_review(item.get("review_id"))
                for item in review_summaries
                if clean_string(item.get("review_id"))
            ]
            review_records = [item for item in review_records if item is not None]
            revision_summaries = self.store.list_concept_revisions(limit=limit, concept_id=concept_id or None)
            revision_records = [
                self.store.get_concept_revision(item.get("revision_id"))
                for item in revision_summaries
                if clean_string(item.get("revision_id"))
            ]
            revision_records = [item for item in revision_records if item is not None]
            compare_summary = summarize_concept_revision_loop(revision_records, review_records)
            concept_runtime = self.store.get_concept_runtime("main")
            if concept_runtime is None:
                runtimes = self.store.list_concept_runtime()
                concept_runtime = runtimes[0] if runtimes else None
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
            self._send_json(200, compare_summary)
            return

        if path.startswith("/v1/concept/revisions/"):
            self._send_detail(path, self.store.get_concept_revision, "concept revision")
            return

        if path == "/v1/control/state":
            control_key = clean_string(params.get("control_key", [""])[0])
            if control_key:
                record = self.store.get_control_state(control_key)
                if record is None:
                    self._send_json(
                        200,
                        {
                            "control_key": normalize_control_key(control_key),
                            "paused": False,
                            "reason": None,
                            "updated_by": None,
                            "metadata": {},
                            "updated_at": None,
                            "effective": resolve_control_state(control_key),
                        },
                    )
                    return
                record["effective"] = resolve_control_state(control_key)
                self._send_json(200, record)
                return
            items = self.store.list_control_state()
            for item in items:
                item["effective"] = resolve_control_state(item["control_key"])
            self._send_json(200, {"items": items})
            return

        if path.startswith("/v1/control/state/"):
            control_key = path.split("/")[-1]
            record = self.store.get_control_state(control_key)
            if record is None:
                self._send_json(
                    200,
                    {
                        "control_key": normalize_control_key(control_key),
                        "paused": False,
                        "reason": None,
                        "updated_by": None,
                        "metadata": {},
                        "updated_at": None,
                        "effective": resolve_control_state(control_key),
                    },
                )
                return
            record["effective"] = resolve_control_state(control_key)
            self._send_json(200, record)
            return

            if path == "/v1/control/events":
                self._send_filtered_events(params, self.store.list_control_events, ["control_key"])
                return

        if path.startswith("/v1/control/events/"):
            self._send_detail(path, self.store.get_control_event, "control event")
            return

        if path == "/v1/stats":
            self._send_json(200, self.store.stats())
            return

        if path == "/v1/watchlist-state":
            instrument = normalize_instrument(params.get("instrument", [""])[0])
            if instrument:
                record = self.store.get_watchlist_state(instrument)
                if record is None:
                    self._send_json(404, {"error": f"watchlist state for {instrument} not found"})
                    return
                self._send_json(200, record)
                return

            self._send_json(200, {"items": self.store.list_watchlist_state()})
            return

        if path == "/v1/scan-history":
            limit = coerce_query_limit(params.get("limit", [None])[0], 100)

            instrument = normalize_instrument(params.get("instrument", [""])[0])
            source = clean_string(params.get("source", [""])[0])
            decision = clean_string(params.get("decision", [""])[0])
            if decision:
                decision = decision.lower()
            scan_batch_id = clean_string(params.get("scan_batch_id", [""])[0])

            self._send_json(
                200,
                {
                    "items": self.store.list_scan_history(
                        limit=limit,
                        instrument=instrument,
                        source=source,
                        decision=decision,
                        scan_batch_id=scan_batch_id,
                    )
                },
            )
            return

        if path.startswith("/v1/scan-history/"):
            self._send_detail(path, self.store.get_scan_history_entry, "scan history")
            return

        if path == "/v1/signal-traces":
            limit = coerce_query_limit(params.get("limit", [None])[0], 100)

            symbol = normalize_instrument(params.get("symbol", [""])[0])
            source_path = clean_string(params.get("source_path", [""])[0])
            decision = clean_string(params.get("decision", [""])[0])
            opportunity_state = clean_string(params.get("opportunity_state", [""])[0])
            blocker_class = clean_string(params.get("blocker_class", [""])[0])
            blocker_reason_contains = clean_string(params.get("blocker_reason_contains", [""])[0])
            source_mode = clean_string(params.get("source_mode", [""])[0])
            shadow_session_id = clean_string(params.get("shadow_session_id", [""])[0])
            session_state = clean_string(params.get("session_state", [""])[0])
            journal_id = clean_string(params.get("journal_id", [""])[0])
            webhook_id = clean_string(params.get("webhook_id", [""])[0])
            scan_batch_id = clean_string(params.get("scan_batch_id", [""])[0])
            reference_timestamp_from = clean_string(params.get("reference_timestamp_from", [""])[0])
            reference_timestamp_to = clean_string(params.get("reference_timestamp_to", [""])[0])
            execution_eligible = None
            if "execution_eligible" in params:
                execution_eligible = coerce_bool(params["execution_eligible"][0])
            shadow_mode = None
            if "shadow_mode" in params:
                shadow_mode = coerce_bool(params["shadow_mode"][0])

            self._send_json(
                200,
                {
                    "items": get_runtime_repositories(self.store).signal_traces.list(
                        limit=limit,
                        symbol=symbol,
                        source_path=source_path,
                        decision=decision,
                        opportunity_state=opportunity_state,
                        blocker_class=blocker_class,
                        blocker_reason_contains=blocker_reason_contains,
                        execution_eligible=execution_eligible,
                        reference_timestamp_from=reference_timestamp_from,
                        reference_timestamp_to=reference_timestamp_to,
                        journal_id=journal_id,
                        webhook_id=webhook_id,
                        scan_batch_id=scan_batch_id,
                        source_mode=source_mode,
                        shadow_mode=shadow_mode,
                        shadow_session_id=shadow_session_id,
                        session_state=session_state,
                    )
                },
            )
            return

        if path == "/v1/shadow-review/summary":
            limit = coerce_query_limit(params.get("limit", [None])[0], 200)
            cluster_limit = 10
            if "cluster_limit" in params:
                try:
                    cluster_limit = max(1, min(50, int(params["cluster_limit"][0])))
                except ValueError:
                    pass
            only_false_negative_candidates = coerce_bool(
                params.get("only_false_negative_candidates", ["false"])[0]
            )
            symbol = normalize_instrument(params.get("symbol", [""])[0])
            decision = clean_string(params.get("decision", [""])[0])
            opportunity_state = clean_string(params.get("opportunity_state", [""])[0])
            blocker_class = clean_string(params.get("blocker_class", [""])[0])
            blocker_reason_contains = clean_string(params.get("blocker_reason_contains", [""])[0])
            shadow_session_id = clean_string(params.get("shadow_session_id", [""])[0])
            session_state = clean_string(params.get("session_state", [""])[0])
            reference_timestamp_from = clean_string(params.get("reference_timestamp_from", [""])[0])
            reference_timestamp_to = clean_string(params.get("reference_timestamp_to", [""])[0])
            summary = get_runtime_repositories(self.store).signal_traces.summarize_shadow_review(
                limit=limit,
                shadow_mode=True,
                shadow_session_id=shadow_session_id or None,
                symbol=symbol or None,
                decision=decision or None,
                opportunity_state=opportunity_state or None,
                blocker_class=blocker_class or None,
                blocker_reason_contains=blocker_reason_contains or None,
                session_state=session_state or None,
                reference_timestamp_from=reference_timestamp_from or None,
                reference_timestamp_to=reference_timestamp_to or None,
                cluster_limit=cluster_limit,
                only_false_negative_candidates=only_false_negative_candidates is True,
            )
            self._send_json(200, summary)
            return

        if path.startswith("/v1/signal-traces/"):
            self._send_detail(path, get_runtime_repositories(self.store).signal_traces.get, "signal trace")
            return

        if path == "/v1/market/bybit/klines":
            symbol = normalize_instrument(params.get("symbol", [""])[0])
            if not symbol:
                self._send_json(400, {"error": "symbol is required"})
                return

            interval_input = clean_string(params.get("interval", [""])[0]) or BYBIT_INTERVAL_MAP["5m"]
            interval = BYBIT_INTERVAL_MAP.get(normalize_timeframe(interval_input), interval_input)
            category = clean_string(params.get("category", ["linear"])[0]) or "linear"
            try:
                limit = max(10, min(1000, int(params.get("limit", ["200"])[0])))
            except ValueError:
                limit = 200

            result = fetch_bybit_klines(symbol, interval, limit=limit, category=category)
            if not result["ok"]:
                self._send_json(
                    502,
                    {
                        "error": "failed to fetch Bybit klines",
                        "details": result,
                    },
                )
                return

            self._send_json(
                200,
                {
                    "source": "bybit-public-api",
                    "instrument": symbol,
                    "category": category,
                    "interval": interval,
                    "count": len(result["candles"]),
                    "candles": result["candles"],
                },
            )
            return

        if path == "/v1/market/bybit/ticker":
            symbol = normalize_instrument(params.get("symbol", [""])[0])
            if not symbol:
                self._send_json(400, {"error": "symbol is required"})
                return
            category = clean_string(params.get("category", ["linear"])[0]) or "linear"
            result = fetch_bybit_ticker(symbol, category=category)
            if not result["ok"]:
                self._send_json(
                    502,
                    {
                        "error": "failed to fetch Bybit ticker",
                        "details": result,
                    },
                )
                return

            self._send_json(
                200,
                {
                    "source": "bybit-public-api",
                    "instrument": symbol,
                    "category": category,
                    "ticker": result.get("ticker"),
                },
            )
            return

        if path == "/v1/market/bybit/instrument":
            symbol = normalize_instrument(params.get("symbol", [""])[0])
            if not symbol:
                self._send_json(400, {"error": "symbol is required"})
                return
            category = clean_string(params.get("category", ["linear"])[0]) or "linear"
            result = fetch_bybit_instrument(symbol, category=category)
            if not result["ok"]:
                self._send_json(
                    502,
                    {
                        "error": "failed to fetch Bybit instrument info",
                        "details": result,
                    },
                )
                return

            self._send_json(
                200,
                {
                    "source": "bybit-public-api",
                    "instrument": symbol,
                    "category": category,
                    "details": result.get("instrument"),
                    "constraints": extract_bybit_instrument_constraints(result.get("instrument")),
                },
            )
            return

        if path == "/v1/paper-trades":
            limit = 50
            if "limit" in params:
                try:
                    limit = max(1, min(500, int(params["limit"][0])))
                except ValueError:
                    pass
            self._send_json(200, {"items": self.store.list_entries(limit=limit)})
            return

        if path.startswith("/v1/paper-trades/"):
            self._send_detail(path, self.store.get_entry, "paper trade")
            return

        if path == "/v1/webhooks":
            limit = 50
            if "limit" in params:
                try:
                    limit = max(1, min(500, int(params["limit"][0])))
                except ValueError:
                    pass
            self._send_json(200, {"items": self.store.list_webhook_events(limit=limit)})
            return

        if path.startswith("/v1/webhooks/"):
            self._send_detail(path, self.store.get_webhook_event, "webhook")
            return

        if path == "/v1/order-proposals":
            limit = 50
            if "limit" in params:
                try:
                    limit = max(1, min(500, int(params["limit"][0])))
                except ValueError:
                    pass
            self._send_json(200, {"items": self.store.list_order_proposals(limit=limit)})
            return

        if path == "/v1/execution-state":
            limit = 50
            if "limit" in params:
                try:
                    limit = max(1, min(500, int(params["limit"][0])))
                except ValueError:
                    pass
            symbol = normalize_instrument(params.get("symbol", [""])[0])
            sync_status = clean_string(params.get("sync_status", [""])[0])
            self._send_json(
                200,
                {
                    "items": self.store.list_execution_state(
                        limit=limit,
                        symbol=symbol or None,
                        sync_status=sync_status or None,
                    )
                },
            )
            return

        if path == "/v1/execution-intents":
            limit = 50
            if "limit" in params:
                try:
                    limit = max(1, min(500, int(params["limit"][0])))
                except ValueError:
                    pass
            symbol = normalize_instrument(params.get("symbol", [""])[0])
            state = clean_string(params.get("state", [""])[0])
            source_path = clean_string(params.get("source_path", [""])[0])
            terminal = None
            if "terminal" in params:
                terminal = coerce_bool(params["terminal"][0])
            self._send_json(
                200,
                {
                    "items": get_runtime_repositories(self.store).execution_intents.list(
                        limit=limit,
                        symbol=symbol or None,
                        state=state or None,
                        source_path=source_path or None,
                        terminal=terminal,
                    )
                },
            )
            return

        if path == "/v1/execution-risk-checks":
            limit = 50
            if "limit" in params:
                try:
                    limit = max(1, min(500, int(params["limit"][0])))
                except ValueError:
                    pass
            intent_id = clean_string(params.get("intent_id", [""])[0])
            state = clean_string(params.get("state", [""])[0])
            symbol = normalize_instrument(params.get("symbol", [""])[0])
            runtime_key = clean_string(params.get("runtime_key", [""])[0])
            self._send_json(
                200,
                {
                    "items": get_runtime_repositories(self.store).execution_risk_checks.list(
                        limit=limit,
                        intent_id=intent_id or None,
                        state=state or None,
                        symbol=symbol or None,
                        runtime_key=runtime_key or None,
                    )
                },
            )
            return

        if path.startswith("/v1/execution-intents/"):
            self._send_detail(path, get_runtime_repositories(self.store).execution_intents.get, "execution intent")
            return

        if path.startswith("/v1/execution-risk-checks/"):
            self._send_detail(path, get_runtime_repositories(self.store).execution_risk_checks.get, "execution risk check")
            return

        if path == "/v1/execution-intent-events":
            limit = 50
            if "limit" in params:
                try:
                    limit = max(1, min(500, int(params["limit"][0])))
                except ValueError:
                    pass
            intent_id = clean_string(params.get("intent_id", [""])[0])
            to_state = clean_string(params.get("to_state", [""])[0])
            self._send_json(
                200,
                {
                    "items": self.store.list_execution_intent_events(
                        limit=limit,
                        intent_id=intent_id or None,
                        to_state=to_state or None,
                    )
                },
            )
            return

        if path.startswith("/v1/execution-state/"):
            self._send_detail(path, self.store.get_execution_state, "execution state for")
            return

        if path == "/v1/execution-actions":
            limit = 50
            if "limit" in params:
                try:
                    limit = max(1, min(500, int(params["limit"][0])))
                except ValueError:
                    pass
            proposal_id = clean_string(params.get("proposal_id", [""])[0])
            action_type = clean_string(params.get("action_type", [""])[0])
            status = clean_string(params.get("status", [""])[0])
            self._send_json(
                200,
                {
                    "items": self.store.list_execution_actions(
                        limit=limit,
                        proposal_id=proposal_id or None,
                        action_type=action_type or None,
                        status=status or None,
                    )
                },
            )
            return

        if path.startswith("/v1/execution-intent-events/"):
            self._send_detail(path, self.store.get_execution_intent_event, "execution intent event")
            return

        if path.startswith("/v1/execution-actions/"):
            self._send_detail(path, self.store.get_execution_action, "execution action")
            return

        if path.startswith("/v1/order-proposals/"):
            self._send_detail(path, self.store.get_order_proposal, "order proposal")
            return

        self._send_json(404, {"error": f"unknown route: {path}"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if not self._enforce_operator_auth("POST", path):
            return
        payload, error = self._read_json_body()
        if error:
            self._send_json(400, {"error": error})
            return

        if path == "/v1/concept/reviews":
            include_current_brief = coerce_bool(payload.get("include_current_brief")) is True
            review_payload = dict(payload) if isinstance(payload, dict) else {}
            if include_current_brief:
                def _payload_int(name, default, minimum=1, maximum=1000):
                    try:
                        return max(minimum, min(maximum, int(review_payload.get(name) or default)))
                    except (TypeError, ValueError):
                        return default

                tradable_only = coerce_bool(review_payload.get("tradable_only")) is True
                current_brief = build_concept_brief_response(
                    state_dir=current_stack_state_dir(),
                    db_path=DB_PATH,
                    event_limit=_payload_int("event_limit", 25),
                    proposal_limit=_payload_int("proposal_limit", 10),
                    action_limit=_payload_int("action_limit", 10),
                    scan_limit=_payload_int("scan_limit", 50),
                    instruments=clean_string(review_payload.get("instruments")) or "BTCUSDT,ETHUSDT",
                    category=clean_string(review_payload.get("category")) or "linear",
                    max_steps=_payload_int("max_steps", 12, maximum=500),
                    step_stride=_payload_int("step_stride", 3, maximum=100),
                    tradable_only=tradable_only,
                    policy_path=clean_string(review_payload.get("policy_path")) or str(BASE_DIR / "config" / "concept_decision_policy.json"),
                )
                review_payload["concept_brief"] = current_brief
                review_payload["concept_id"] = clean_string(review_payload.get("concept_id")) or clean_string(current_brief.get("concept_id")) or "concept-1"
                decision = current_brief.get("decision") or {}
                pressure = current_brief.get("pressure_points") or {}
                if not clean_string(review_payload.get("overall")):
                    review_payload["overall"] = decision.get("overall")
                if not clean_string(review_payload.get("recommendation")):
                    review_payload["recommendation"] = decision.get("recommendation")
                if not clean_string(review_payload.get("primary_blocker")):
                    review_payload["primary_blocker"] = ((pressure.get("dominant_blocker") or {}).get("blocker"))

            review_id = self.store.create_concept_review(review_payload)
            record = self.store.get_concept_review(review_id)
            self._send_json(201, record)
            return

        if path == "/v1/concept/reviews/structured":
            response_payload = payload.get("response")
            validation = validate_structured_review_response(response_payload)
            if not validation.get("ok"):
                self._send_json(
                    400,
                    {
                        "error": "structured review response failed validation",
                        "details": validation.get("errors") or [],
                    },
                )
                return

            include_current_brief = coerce_bool(payload.get("include_current_brief"))
            if include_current_brief is None:
                include_current_brief = True

            brief = payload.get("concept_brief") if isinstance(payload.get("concept_brief"), dict) else None
            if include_current_brief or brief is None:
                def _payload_int(name, default, minimum=1, maximum=1000):
                    try:
                        return max(minimum, min(maximum, int(payload.get(name) or default)))
                    except (TypeError, ValueError):
                        return default

                tradable_only = coerce_bool(payload.get("tradable_only")) is True
                brief = build_concept_brief_response(
                    state_dir=current_stack_state_dir(),
                    db_path=DB_PATH,
                    event_limit=_payload_int("event_limit", 25),
                    proposal_limit=_payload_int("proposal_limit", 10),
                    action_limit=_payload_int("action_limit", 10),
                    scan_limit=_payload_int("scan_limit", 50),
                    instruments=clean_string(payload.get("instruments")) or "BTCUSDT,ETHUSDT",
                    category=clean_string(payload.get("category")) or "linear",
                    max_steps=_payload_int("max_steps", 12, maximum=500),
                    step_stride=_payload_int("step_stride", 3, maximum=100),
                    tradable_only=tradable_only,
                    policy_path=clean_string(payload.get("policy_path")) or str(BASE_DIR / "config" / "concept_decision_policy.json"),
                )

            review_record = build_structured_review_record(
                validation.get("response") or {},
                brief,
                source=clean_string(payload.get("source")) or "llm",
                author=clean_string(payload.get("author")),
            )
            review_id = self.store.create_concept_review(review_record)
            record = self.store.get_concept_review(review_id)
            self._send_json(
                201,
                {
                    "validation": validation,
                    "review": record,
                },
            )
            return

        if path == "/v1/concept/acceptance/reviews/structured":
            response_payload = payload.get("response")
            validation = validate_acceptance_response(response_payload)
            if not validation.get("ok"):
                self._send_json(
                    400,
                    {
                        "error": "structured acceptance response failed validation",
                        "details": validation.get("errors") or [],
                    },
                )
                return

            include_current_brief = coerce_bool(payload.get("include_current_brief"))
            if include_current_brief is None:
                include_current_brief = True

            brief = payload.get("concept_brief") if isinstance(payload.get("concept_brief"), dict) else None
            if include_current_brief or brief is None:
                def _payload_int(name, default, minimum=1, maximum=1000):
                    try:
                        return max(minimum, min(maximum, int(payload.get(name) or default)))
                    except (TypeError, ValueError):
                        return default

                tradable_only = coerce_bool(payload.get("tradable_only")) is True
                brief = build_concept_acceptance_brief_response(
                    state_dir=current_stack_state_dir(),
                    db_path=DB_PATH,
                    event_limit=_payload_int("event_limit", 25),
                    proposal_limit=_payload_int("proposal_limit", 10),
                    action_limit=_payload_int("action_limit", 10),
                    scan_limit=_payload_int("scan_limit", 50),
                    instruments=clean_string(payload.get("instruments")) or "BTCUSDT,ETHUSDT",
                    category=clean_string(payload.get("category")) or "linear",
                    max_steps=_payload_int("max_steps", 12, maximum=500),
                    step_stride=_payload_int("step_stride", 3, maximum=100),
                    tradable_only=tradable_only,
                    policy_path=clean_string(payload.get("policy_path")) or str(BASE_DIR / "config" / "concept_decision_policy.json"),
                    artifact_limit=_payload_int("artifact_limit", 20, maximum=200),
                    top_limit=_payload_int("top_limit", 3, maximum=10),
                )

            review_record = build_structured_acceptance_record(
                validation.get("response") or {},
                brief,
                source=clean_string(payload.get("source")) or "llm",
                author=clean_string(payload.get("author")),
            )
            review_id = self.store.create_concept_review(review_record)
            record = self.store.get_concept_review(review_id)
            self._send_json(
                201,
                {
                    "validation": validation,
                    "review": record,
                },
            )
            return

        if path == "/v1/concept/stage7/decisions/structured":
            response_payload = payload.get("response")
            validation = validate_stage7_decision_response(response_payload)
            if not validation.get("ok"):
                self._send_json(
                    400,
                    {
                        "error": "structured stage7 decision response failed validation",
                        "details": validation.get("errors") or [],
                    },
                )
                return

            include_current_brief = coerce_bool(payload.get("include_current_brief"))
            if include_current_brief is None:
                include_current_brief = True

            brief = payload.get("stage7_brief") if isinstance(payload.get("stage7_brief"), dict) else None
            if include_current_brief or brief is None:
                def _payload_int(name, default, minimum=1, maximum=1000):
                    try:
                        return max(minimum, min(maximum, int(payload.get(name) or default)))
                    except (TypeError, ValueError):
                        return default

                tradable_only = coerce_bool(payload.get("tradable_only")) is True
                brief = build_concept_stage7_decision_brief_response(
                    state_dir=current_stack_state_dir(),
                    db_path=DB_PATH,
                    event_limit=_payload_int("event_limit", 25),
                    proposal_limit=_payload_int("proposal_limit", 10),
                    action_limit=_payload_int("action_limit", 10),
                    scan_limit=_payload_int("scan_limit", 50),
                    instruments=clean_string(payload.get("instruments")) or "BTCUSDT,ETHUSDT",
                    category=clean_string(payload.get("category")) or "linear",
                    max_steps=_payload_int("max_steps", 12, maximum=500),
                    step_stride=_payload_int("step_stride", 3, maximum=100),
                    tradable_only=tradable_only,
                    policy_path=clean_string(payload.get("policy_path")) or str(BASE_DIR / "config" / "concept_decision_policy.json"),
                    artifact_limit=_payload_int("artifact_limit", 20, maximum=200),
                    top_limit=_payload_int("top_limit", 3, maximum=10),
                )

            review_record = build_structured_stage7_decision_record(
                validation.get("response") or {},
                brief,
                source=clean_string(payload.get("source")) or "llm",
                author=clean_string(payload.get("author")),
            )
            review_id = self.store.create_concept_review(review_record)
            record = self.store.get_concept_review(review_id)
            self._send_json(
                201,
                {
                    "validation": validation,
                    "review": record,
                },
            )
            return

        if path == "/v1/concept/revisions/compare-structured":
            response_payload = payload.get("response")
            validation = validate_revision_compare_response(response_payload)
            if not validation.get("ok"):
                self._send_json(
                    400,
                    {
                        "error": "structured revision compare response failed validation",
                        "details": validation.get("errors") or [],
                    },
                )
                return

            include_current_brief = coerce_bool(payload.get("include_current_brief"))
            if include_current_brief is None:
                include_current_brief = True

            brief = (
                payload.get("revision_brief")
                if isinstance(payload.get("revision_brief"), dict)
                else None
            )
            if include_current_brief or brief is None:
                def _payload_int(name, default, minimum=1, maximum=1000):
                    try:
                        return max(minimum, min(maximum, int(payload.get(name) or default)))
                    except (TypeError, ValueError):
                        return default

                tradable_only = coerce_bool(payload.get("tradable_only")) is True
                brief = build_concept_revision_brief_response(
                    state_dir=current_stack_state_dir(),
                    db_path=DB_PATH,
                    event_limit=_payload_int("event_limit", 25),
                    proposal_limit=_payload_int("proposal_limit", 10),
                    action_limit=_payload_int("action_limit", 10),
                    scan_limit=_payload_int("scan_limit", 50),
                    instruments=clean_string(payload.get("instruments")) or "BTCUSDT,ETHUSDT",
                    category=clean_string(payload.get("category")) or "linear",
                    max_steps=_payload_int("max_steps", 12, maximum=500),
                    step_stride=_payload_int("step_stride", 3, maximum=100),
                    tradable_only=tradable_only,
                    policy_path=clean_string(payload.get("policy_path"))
                    or str(BASE_DIR / "config" / "concept_decision_policy.json"),
                    artifact_limit=_payload_int("artifact_limit", 20, maximum=500),
                    top_limit=_payload_int("top_limit", 3, maximum=20),
                )

            review_record = build_structured_revision_compare_record(
                validation.get("response") or {},
                brief,
                source=clean_string(payload.get("source")) or "llm",
                author=clean_string(payload.get("author")),
            )
            review_id = self.store.create_concept_review(review_record)
            record = self.store.get_concept_review(review_id)
            self._send_json(
                201,
                {
                    "validation": validation,
                    "review": record,
                },
            )
            return

        if path.startswith("/v1/concept/reviews/") and path.endswith("/evaluate-latest-revision"):
            review_id = path.split("/")[-2]
            linked_review = self.store.get_concept_review(review_id)
            if linked_review is None:
                self._send_json(404, {"error": f"concept review {review_id} not found"})
                return

            revision_record = self.store.get_latest_concept_revision_for_review(review_id)
            if revision_record is None:
                self._send_json(404, {"error": f"no saved concept revision is linked to review {review_id}"})
                return

            revision_payload = revision_record.get("revision") or {}

            def _payload_int(name, default, minimum=1, maximum=1000):
                try:
                    return max(minimum, min(maximum, int(payload.get(name) or default)))
                except (TypeError, ValueError):
                    return default

            tradable_only = coerce_bool(payload.get("tradable_only")) is True
            current_brief = build_concept_brief_response(
                state_dir=current_stack_state_dir(),
                db_path=DB_PATH,
                event_limit=_payload_int("event_limit", 25),
                proposal_limit=_payload_int("proposal_limit", 10),
                action_limit=_payload_int("action_limit", 10),
                scan_limit=_payload_int("scan_limit", 50),
                instruments=clean_string(payload.get("instruments")) or "BTCUSDT,ETHUSDT",
                category=clean_string(payload.get("category")) or "linear",
                max_steps=_payload_int("max_steps", 12, maximum=500),
                step_stride=_payload_int("step_stride", 3, maximum=100),
                tradable_only=tradable_only,
                policy_path=clean_string(payload.get("policy_path")) or str(BASE_DIR / "config" / "concept_decision_policy.json"),
            )
            evaluation = evaluate_concept_revision_plan(revision_payload, current_brief)
            history_result = record_concept_revision_evaluation(revision_payload, evaluation)
            revision_payload = history_result.get("plan") or revision_payload
            revision_payload["status"] = evaluation.get("status") or revision_payload.get("status") or "planned"
            revision_payload["summary"] = revision_payload.get("summary") or clean_string(
                (revision_payload.get("selected_candidate") or {}).get("rationale")
            ) or "concept revision"
            self.store.update_concept_revision(revision_record.get("revision_id"), revision_payload)
            self._send_json(
                200,
                {
                    "review": linked_review,
                    "revision_id": revision_record.get("revision_id"),
                    "evaluation": evaluation,
                    "history": {
                        "key": history_result.get("history_key"),
                        "updated": history_result.get("history_updated"),
                        "replaced": history_result.get("history_replaced"),
                        "count": history_result.get("history_count"),
                    },
                    "current_brief": current_brief,
                    "revision": self.store.get_concept_revision(revision_record.get("revision_id")),
                },
            )
            return

        if path.startswith("/v1/concept/reviews/") and path.endswith("/promote-revision"):
            review_id = path.split("/")[-2]
            linked_review = self.store.get_concept_review(review_id)
            if linked_review is None:
                self._send_json(404, {"error": f"concept review {review_id} not found"})
                return

            include_current_brief = coerce_bool(payload.get("include_current_brief"))
            if include_current_brief is None:
                include_current_brief = True

            def _payload_int(name, default, minimum=1, maximum=1000):
                try:
                    return max(minimum, min(maximum, int(payload.get(name) or default)))
                except (TypeError, ValueError):
                    return default

            revision_payload = dict(payload) if isinstance(payload, dict) else {}
            if include_current_brief:
                tradable_only = coerce_bool(revision_payload.get("tradable_only")) is True
                revision_payload = build_concept_revision_plan_response(
                    candidate_id=clean_string(revision_payload.get("candidate_id")),
                    review_artifact=linked_review,
                    source=clean_string(revision_payload.get("source")) or "linked_review",
                    author=clean_string(revision_payload.get("author")) or clean_string(linked_review.get("author")),
                    state_dir=current_stack_state_dir(),
                    db_path=DB_PATH,
                    event_limit=_payload_int("event_limit", 25),
                    proposal_limit=_payload_int("proposal_limit", 10),
                    action_limit=_payload_int("action_limit", 10),
                    scan_limit=_payload_int("scan_limit", 50),
                    instruments=clean_string(revision_payload.get("instruments")) or "BTCUSDT,ETHUSDT",
                    category=clean_string(revision_payload.get("category")) or "linear",
                    max_steps=_payload_int("max_steps", 12, maximum=500),
                    step_stride=_payload_int("step_stride", 3, maximum=100),
                    tradable_only=tradable_only,
                    policy_path=clean_string(revision_payload.get("policy_path")) or str(BASE_DIR / "config" / "concept_decision_policy.json"),
                )

            revision_id = self.store.create_concept_revision(revision_payload)
            record = self.store.get_concept_revision(revision_id)
            self._send_json(
                201,
                {
                    "review": linked_review,
                    "revision": record,
                },
            )
            return

        if path == "/v1/concept/revisions":
            revision_payload = dict(payload) if isinstance(payload, dict) else {}

            linked_review = None
            review_id = clean_string(revision_payload.get("review_id"))
            if review_id:
                linked_review = self.store.get_concept_review(review_id)
                if linked_review is None:
                    self._send_json(404, {"error": f"concept review {review_id} not found"})
                    return

            include_current_brief = coerce_bool(revision_payload.get("include_current_brief"))
            if include_current_brief is None:
                include_current_brief = linked_review is not None

            if include_current_brief:
                def _payload_int(name, default, minimum=1, maximum=1000):
                    try:
                        return max(minimum, min(maximum, int(revision_payload.get(name) or default)))
                    except (TypeError, ValueError):
                        return default

                tradable_only = coerce_bool(revision_payload.get("tradable_only")) is True
                plan = build_concept_revision_plan_response(
                    candidate_id=clean_string(revision_payload.get("candidate_id")),
                    review_artifact=linked_review,
                    source=clean_string(revision_payload.get("source")) or "manual",
                    author=clean_string(revision_payload.get("author")),
                    state_dir=current_stack_state_dir(),
                    db_path=DB_PATH,
                    event_limit=_payload_int("event_limit", 25),
                    proposal_limit=_payload_int("proposal_limit", 10),
                    action_limit=_payload_int("action_limit", 10),
                    scan_limit=_payload_int("scan_limit", 50),
                    instruments=clean_string(revision_payload.get("instruments")) or "BTCUSDT,ETHUSDT",
                    category=clean_string(revision_payload.get("category")) or "linear",
                    max_steps=_payload_int("max_steps", 12, maximum=500),
                    step_stride=_payload_int("step_stride", 3, maximum=100),
                    tradable_only=tradable_only,
                    policy_path=clean_string(revision_payload.get("policy_path")) or str(BASE_DIR / "config" / "concept_decision_policy.json"),
                )
                revision_payload = plan

            revision_id = self.store.create_concept_revision(revision_payload)
            record = self.store.get_concept_revision(revision_id)
            self._send_json(201, record)
            return

        if path.startswith("/v1/concept/revisions/") and path.endswith("/evaluate"):
            revision_id = path.split("/")[-2]
            revision_record = self.store.get_concept_revision(revision_id)
            if revision_record is None:
                self._send_json(404, {"error": f"concept revision {revision_id} not found"})
                return

            revision_payload = revision_record.get("revision") or {}

            def _payload_int(name, default, minimum=1, maximum=1000):
                try:
                    return max(minimum, min(maximum, int(payload.get(name) or default)))
                except (TypeError, ValueError):
                    return default

            tradable_only = coerce_bool(payload.get("tradable_only")) is True
            current_brief = build_concept_brief_response(
                state_dir=current_stack_state_dir(),
                db_path=DB_PATH,
                event_limit=_payload_int("event_limit", 25),
                proposal_limit=_payload_int("proposal_limit", 10),
                action_limit=_payload_int("action_limit", 10),
                scan_limit=_payload_int("scan_limit", 50),
                instruments=clean_string(payload.get("instruments")) or "BTCUSDT,ETHUSDT",
                category=clean_string(payload.get("category")) or "linear",
                max_steps=_payload_int("max_steps", 12, maximum=500),
                step_stride=_payload_int("step_stride", 3, maximum=100),
                tradable_only=tradable_only,
                policy_path=clean_string(payload.get("policy_path")) or str(BASE_DIR / "config" / "concept_decision_policy.json"),
            )
            evaluation = evaluate_concept_revision_plan(revision_payload, current_brief)
            history_result = record_concept_revision_evaluation(revision_payload, evaluation)
            revision_payload = history_result.get("plan") or revision_payload
            revision_payload["status"] = evaluation.get("status") or revision_payload.get("status") or "planned"
            revision_payload["summary"] = revision_payload.get("summary") or clean_string(
                (revision_payload.get("selected_candidate") or {}).get("rationale")
            ) or "concept revision"
            self.store.update_concept_revision(revision_id, revision_payload)
            self._send_json(
                200,
                {
                    "revision_id": revision_id,
                    "evaluation": evaluation,
                    "history": {
                        "key": history_result.get("history_key"),
                        "updated": history_result.get("history_updated"),
                        "replaced": history_result.get("history_replaced"),
                        "count": history_result.get("history_count"),
                    },
                    "current_brief": current_brief,
                    "revision": self.store.get_concept_revision(revision_id),
                },
            )
            return

        if self._dispatch_core_post_route(path, payload):
            return

        if path == "/v1/webhooks/tradingview":
            if TRADINGVIEW_WEBHOOK_SECRET:
                provided_secret = clean_string(first_present(payload, ["passphrase", "secret"]))
                if provided_secret != TRADINGVIEW_WEBHOOK_SECRET:
                    self._send_json(403, {"error": "invalid TradingView webhook secret"})
                    return

            normalized_payload = normalize_tradingview_payload(payload)
            evaluation_payload = {
                "instrument": normalized_payload["instrument"],
                "provider": normalized_payload["provider"],
                "session": normalized_payload["session"],
                "direction": normalized_payload["direction"],
                "weekend": normalized_payload["weekend"],
                "source_mode": normalized_payload.get("source_mode"),
                "visual_analysis_state": normalized_payload.get("visual_analysis_state"),
                "timeframes": normalized_payload["timeframes"],
                "checklist": normalized_payload["checklist"],
                "notes": normalized_payload.get("notes"),
                "chart_url": normalized_payload.get("chart_url"),
                "screenshot_paths": normalized_payload.get("screenshot_paths"),
            }
            evaluation = evaluate_payload(evaluation_payload)

            auto_log = coerce_bool(payload.get("auto_log"))
            if auto_log is None:
                auto_log = True

            journal_id = None
            if auto_log:
                journal_id = self.store.create_entry(evaluation_payload, evaluation)
                evaluation["journal_id"] = journal_id

            webhook_summary = {
                "instrument": evaluation["normalized"]["instrument"],
                "provider": evaluation["normalized"].get("provider"),
                "session": evaluation["normalized"]["session"],
                "direction": evaluation["normalized"].get("direction"),
                "timeframes": evaluation["normalized"]["timeframes"],
                "chart_url": normalized_payload.get("chart_url"),
                "screenshot_paths": normalized_payload.get("screenshot_paths"),
                "notes": normalized_payload.get("notes"),
                "reference_at": normalized_payload.get("reference_at"),
                "evaluation": {
                    "decision": evaluation["decision"],
                    "setup_tag": evaluation["setup_tag"],
                    "confidence": evaluation["confidence"],
                },
            }
            webhook_id = self.store.create_webhook_event(
                source="tradingview",
                payload=payload,
                normalized_summary=webhook_summary,
                evaluation=evaluation,
                journal_id=journal_id,
            )
            signal_trace_id = persist_signal_trace_for_evaluation(
                source_path="webhook",
                payload=evaluation_payload,
                evaluation=evaluation,
                journal_id=journal_id,
                webhook_id=webhook_id,
                reference_timestamp=clean_string(normalized_payload.get("reference_at")),
            )
            evaluation["signal_trace_id"] = signal_trace_id

            order_proposal = build_bybit_order_proposal(
                raw_payload=payload,
                normalized_payload=normalized_payload,
                evaluation=evaluation,
                journal_id=journal_id,
            )
            proposal_id = None
            if order_proposal is not None:
                proposal_id, order_proposal = self.store.create_order_proposal(
                    order_proposal,
                    journal_id=journal_id,
                    webhook_id=webhook_id,
                )
                self.store.update_webhook_proposal(webhook_id, proposal_id)

            response = {
                "status": "accepted",
                "webhook_id": webhook_id,
                "paper_trade_evaluation": evaluation,
                "order_proposal": order_proposal,
                "proposal_id": proposal_id,
            }
            self._send_json(202, response)
            return

        if path.startswith("/v1/paper-trades/") and path.endswith("/outcome"):
            journal_id = path.split("/")[-2]
            result_status = payload.get("result_status")
            if not isinstance(result_status, str) or not result_status.strip():
                self._send_json(400, {"error": "result_status is required"})
                return
            outcome_notes = payload.get("outcome_notes")
            if outcome_notes is not None and not isinstance(outcome_notes, str):
                self._send_json(400, {"error": "outcome_notes must be a string"})
                return
            realized_pnl = payload.get("realized_pnl")
            if realized_pnl is not None and to_decimal(realized_pnl) is None:
                self._send_json(400, {"error": "realized_pnl must be numeric when provided"})
                return
            updated = self.store.update_outcome(journal_id, result_status.strip(), outcome_notes, realized_pnl)
            if not updated:
                self._send_json(404, {"error": f"paper trade {journal_id} not found"})
                return
            self._send_json(
                200,
                {
                    "journal_id": journal_id,
                    "result_status": result_status.strip(),
                    "realized_pnl": decimal_string(realized_pnl),
                    "updated": True,
                },
            )
            return

        if path.startswith("/v1/order-proposals/") and path.endswith("/submit"):
            proposal_id = path.split("/")[-2]
            confirm = coerce_bool(payload.get("confirm"))
            if confirm is not True:
                self._send_json(400, {"error": "confirm must be true"})
                return

            proposal_record = self.store.get_order_proposal(proposal_id)
            if proposal_record is None:
                self._send_json(404, {"error": f"order proposal {proposal_id} not found"})
                return

            response = submit_saved_order_proposal_record(proposal_record)
            submission = response.get("submission") or {}
            if submission.get("ok"):
                self._send_json(200, response)
            elif submission.get("status") in {"submission_disabled", "submission_paused"}:
                self._send_json(409, response)
            else:
                self._send_json(502, response)
            return

        if path.startswith("/v1/order-proposals/") and path.endswith("/sync"):
            proposal_id = path.split("/")[-2]
            proposal_record = self.store.get_order_proposal(proposal_id)
            if proposal_record is None:
                self._send_json(404, {"error": f"order proposal {proposal_id} not found"})
                return

            sync_result = sync_order_proposal_execution(proposal_record)
            if sync_result["ok"]:
                self._send_json(
                    200,
                    {
                        "proposal_id": proposal_id,
                        "execution_sync": sync_result,
                    },
                )
            elif sync_result["status"] == "sync_unavailable":
                self._send_json(
                    409,
                    {
                        "proposal_id": proposal_id,
                        "execution_sync": sync_result,
                    },
                )
            else:
                self._send_json(
                    502,
                    {
                        "proposal_id": proposal_id,
                        "execution_sync": sync_result,
                    },
                )
            return

        if path.startswith("/v1/order-proposals/") and path.endswith("/cancel"):
            proposal_id = path.split("/")[-2]
            confirm = coerce_bool(payload.get("confirm"))
            if confirm is not True:
                self._send_json(400, {"error": "confirm must be true"})
                return

            proposal_record = self.store.get_order_proposal(proposal_id)
            if proposal_record is None:
                self._send_json(404, {"error": f"order proposal {proposal_id} not found"})
                return

            action_result = execute_cancel_order_action(proposal_record)
            response = {
                "proposal_id": proposal_id,
                "execution_action": action_result,
            }
            if action_result["ok"]:
                self._send_json(200, response)
            elif action_result["status"] == "action_unavailable":
                self._send_json(409, response)
            else:
                self._send_json(502, response)
            return

        if path.startswith("/v1/order-proposals/") and path.endswith("/amend"):
            proposal_id = path.split("/")[-2]
            confirm = coerce_bool(payload.get("confirm"))
            if confirm is not True:
                self._send_json(400, {"error": "confirm must be true"})
                return

            proposal_record = self.store.get_order_proposal(proposal_id)
            if proposal_record is None:
                self._send_json(404, {"error": f"order proposal {proposal_id} not found"})
                return

            action_result = execute_amend_order_action(proposal_record, payload)
            response = {
                "proposal_id": proposal_id,
                "execution_action": action_result,
            }
            if action_result["ok"]:
                self._send_json(200, response)
            elif action_result["status"] == "action_unavailable":
                self._send_json(409, response)
            else:
                self._send_json(502, response)
            return

        if path.startswith("/v1/order-proposals/") and path.endswith("/refresh-trading-stop"):
            proposal_id = path.split("/")[-2]
            confirm = coerce_bool(payload.get("confirm"))
            if confirm is not True:
                self._send_json(400, {"error": "confirm must be true"})
                return

            proposal_record = self.store.get_order_proposal(proposal_id)
            if proposal_record is None:
                self._send_json(404, {"error": f"order proposal {proposal_id} not found"})
                return

            action_result = execute_refresh_trading_stop_action(proposal_record, payload)
            response = {
                "proposal_id": proposal_id,
                "execution_action": action_result,
            }
            if action_result["ok"]:
                self._send_json(200, response)
            elif action_result["status"] == "action_unavailable":
                self._send_json(409, response)
            else:
                self._send_json(502, response)
            return

        if path.startswith("/v1/order-proposals/") and path.endswith("/close-position"):
            proposal_id = path.split("/")[-2]
            confirm = coerce_bool(payload.get("confirm"))
            if confirm is not True:
                self._send_json(400, {"error": "confirm must be true"})
                return

            proposal_record = self.store.get_order_proposal(proposal_id)
            if proposal_record is None:
                self._send_json(404, {"error": f"order proposal {proposal_id} not found"})
                return

            action_result = execute_close_position_action(proposal_record)
            response = {
                "proposal_id": proposal_id,
                "execution_action": action_result,
            }
            if action_result["ok"]:
                self._send_json(200, response)
            elif action_result["status"] == "action_unavailable":
                self._send_json(409, response)
            else:
                self._send_json(502, response)
            return

        self._send_json(404, {"error": f"unknown route: {path}"})


class TradingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that silences benign client-disconnect noise.

    A client that opens a TCP connection and then drops it without sending a
    complete request (browser probe, health check, cancelled curl, port scan)
    raises ConnectionResetError/ConnectionAbortedError/BrokenPipeError from
    the per-connection worker thread. These are not actionable and are not
    server faults, so they are suppressed here; every other exception still
    gets the default traceback via the parent ``handle_error``.
    """

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def run():
    server = TradingHTTPServer((HOST, PORT), TradingAPIHandler)
    print(f"paper-trading-api listening on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
