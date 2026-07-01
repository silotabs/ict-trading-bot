from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import auto_execute_loop
import server as trading_server
from ict_engine.evaluation import decision_allows_execution_plan
from server import (
    build_auto_execution_payload,
    normalize_tradingview_payload,
    run_bybit_replay_scan,
    run_watchlist_scan,
)


def make_parsed_candle(start_at, open_, high, low, close, volume=1.0, turnover=1.0):
    dt = datetime.fromisoformat(start_at)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return {
        "start_ms": int(dt.timestamp() * 1000),
        "start_at": dt.replace(microsecond=0).isoformat(),
        "open": float(open_),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": float(volume),
        "turnover": float(turnover),
    }


def build_parsed_series(step_minutes, count, start="2026-04-10T00:00:00+00:00", base=100.0, drift=0.12):
    current = datetime.fromisoformat(start)
    candles = []
    for index in range(count):
        wave = ((index % 6) - 3) * 0.35
        open_ = base + index * drift + wave
        close = open_ + (0.45 if index % 2 == 0 else -0.25)
        high = max(open_, close) + 0.9 + ((index % 3) * 0.08)
        low = min(open_, close) - 0.9 - (((index + 1) % 3) * 0.08)
        candles.append(
            make_parsed_candle(
                current.replace(microsecond=0).isoformat(),
                open_,
                high,
                low,
                close,
            )
        )
        current += timedelta(minutes=step_minutes)
    return candles


def sanitize_replay_result(result):
    return {
        "evaluated_steps": result.get("evaluated_steps"),
        "decision_counts": result.get("decision_counts"),
        "session_counts": result.get("session_counts"),
        "direction_counts": result.get("direction_counts"),
        "blocker_counts": result.get("blocker_counts"),
        "warning_counts": result.get("warning_counts"),
        "verified_trade_count": result.get("verified_trade_count"),
        "references": [
            {
                "reference_at": item.get("context", {}).get("replay", {}).get("reference_at"),
                "decision": item.get("paper_trade_evaluation", {}).get("decision"),
                "session": item.get("paper_trade_payload", {}).get("session"),
                "direction": item.get("paper_trade_payload", {}).get("direction"),
            }
            for item in result.get("results") or []
        ],
    }


def phase7_verified_scan_result():
    return {
        "ok": True,
        "instrument": "BTCUSDT",
        "paper_trade_evaluation": {"decision": "verified_paper_trade"},
        "paper_trade_payload": {"instrument": "BTCUSDT"},
        "scan_signature": "sig-phase7-verified",
    }


def phase0_rejected_trace_scan_result():
    return {
        "ok": True,
        "instrument": "BTCUSDT",
        "category": "linear",
        "scan_batch_id": "WL-20260418T063000Z",
        "paper_trade_payload": {
            "instrument": "BTCUSDT",
            "provider": "bybit-public-api",
            "session": "london",
            "direction": "",
            "reference_at": "2026-04-18T06:30:00+00:00",
            "source_mode": "scanner_verified",
            "visual_analysis_state": "not_run",
            "timeframes": {"bias": "4H", "setup": "15m", "execution": "5m"},
            "checklist": {
                "clear_4h_bias": True,
                "clear_liquidity_draw": True,
                "liquidity_event": True,
                "mss": False,
                "displacement": True,
                "fresh_fvg": False,
                "clear_invalidation": True,
                "clear_target": True,
                "chase_entry": False,
            },
        },
        "paper_trade_evaluation": {
            "decision": "no_paper_trade",
            "setup_tag": "starter invalid",
            "confidence": "low",
            "errors": [],
            "blockers": [
                "required checklist field failed: mss",
                "required checklist field failed: fresh_fvg",
            ],
            "warnings": [
                "scanner result is heuristic and should be visually confirmed before any paper-trade submission"
            ],
            "verification": {
                "source_mode": "scanner_verified",
                "visual_analysis_state": "not_run",
            },
        },
        "context": {
            "reference_at": "2026-04-18T06:30:00+00:00",
            "visual_analysis_state": "not_run",
            "session": {
                "now_utc": "2026-04-18T06:30:00+00:00",
                "active_session": "london",
                "session_valid": True,
                "weekend": False,
            },
            "bias_4h": {"bias": "bullish"},
            "drt_4h": {
                "state": "ready",
                "confidence": 0.82,
                "liquidity_event": {
                    "state": "raid_ssl_reject",
                    "reason": "sell-side liquidity was raided and rejected",
                },
            },
            "liquidity_event_4h": {
                "state": "raid_ssl_reject",
                "reason": "sell-side liquidity was raided and rejected",
            },
            "narrative": {
                "state": "developing",
                "reason": "15m MSS is present, but the higher-timeframe narrative is still only partially confirmed",
                "liquidity_reference_alignment": {
                    "state": "aligned",
                    "reason": "the active 4H liquidity event sits near verified higher-timeframe liquidity",
                },
            },
            "context_summary": {
                "state": "watch",
                "reason": "the premise is forming, but timing or narrative clarity is not strong enough yet",
                "execution_eligible": False,
            },
            "mss_15m": {"state": "none", "reason": "15m MSS is not confirmed"},
            "displacement_5m": {"state": "bullish", "reason": "bullish displacement is present"},
            "fvg_5m": {"state": "none", "reason": "5m FVG entry array is not present"},
            "chase_state": "not_chase",
        },
        "scan_signature": "sig-phase0-rejected",
    }


def phase0_verified_trace_scan_result():
    return {
        "ok": True,
        "instrument": "BTCUSDT",
        "category": "linear",
        "scan_batch_id": "WL-20260418T070000Z",
        "paper_trade_payload": {
            "instrument": "BTCUSDT",
            "provider": "bybit-public-api",
            "session": "london",
            "direction": "long",
            "reference_at": "2026-04-18T07:00:00+00:00",
            "source_mode": "scanner_verified",
            "visual_analysis_state": "not_run",
            "timeframes": {"bias": "4H", "setup": "15m", "execution": "5m"},
            "checklist": {
                "clear_4h_bias": True,
                "clear_liquidity_draw": True,
                "liquidity_event": True,
                "mss": True,
                "displacement": True,
                "fresh_fvg": True,
                "clear_invalidation": True,
                "clear_target": True,
                "chase_entry": False,
            },
        },
        "paper_trade_evaluation": {
            "decision": "verified_paper_trade",
            "setup_tag": "starter verified",
            "confidence": "medium",
            "errors": [],
            "blockers": [],
            "warnings": [
                "scanner result is heuristic and should be visually confirmed before any paper-trade submission"
            ],
            "verification": {
                "source_mode": "scanner_verified",
                "visual_analysis_state": "not_run",
            },
        },
        "context": {
            "reference_at": "2026-04-18T07:00:00+00:00",
            "visual_analysis_state": "not_run",
            "session": {
                "now_utc": "2026-04-18T07:00:00+00:00",
                "active_session": "london",
                "session_valid": True,
                "weekend": False,
            },
            "bias_4h": {"bias": "bullish"},
            "drt_4h": {
                "state": "ready",
                "confidence": 0.88,
                "liquidity_event": {
                    "state": "raid_ssl_reject",
                    "reason": "sell-side liquidity was raided and rejected",
                },
            },
            "liquidity_event_4h": {
                "state": "raid_ssl_reject",
                "reason": "sell-side liquidity was raided and rejected",
            },
            "narrative": {
                "state": "reversal",
                "reason": "4H liquidity rejection implies reversal",
                "liquidity_reference_alignment": {
                    "state": "aligned",
                    "reason": "the active 4H liquidity event sits near verified higher-timeframe liquidity",
                },
            },
            "context_summary": {
                "state": "aligned",
                "reason": "higher-timeframe premise and timing are supportive",
                "execution_eligible": True,
            },
            "mss_15m": {"state": "bullish_mss", "reason": "bullish MSS is present"},
            "displacement_5m": {"state": "bullish", "reason": "bullish displacement is present"},
            "fvg_5m": {"state": "bullish", "reason": "bullish FVG entry array is present"},
            "chase_state": "not_chase",
        },
        "scan_signature": "sig-phase0-verified",
    }


def collect_trace_summaries(store, **filters):
    summaries = []
    for item in store.list_signal_traces(limit=200, **filters):
        trace = store.get_signal_trace(item["trace_id"])["trace"]
        summaries.append(
            {
                "symbol": trace.get("symbol"),
                "reference_timestamp": trace.get("reference_timestamp"),
                "source_path": trace.get("source_path"),
                "source_mode": trace.get("source_mode"),
                "decision": trace.get("decision"),
                "execution_eligible": trace.get("execution_eligible"),
                "blocker_class": (trace.get("blocker_classification") or {}).get("primary"),
                "blocker_reasons": trace.get("blocker_reasons"),
                "session_state": trace.get("session_state"),
                "narrative_state": trace.get("narrative_state"),
                "context_state": trace.get("context_state"),
                "mss_15m_state": trace.get("mss_15m_state"),
                "displacement_5m_state": trace.get("displacement_5m_state"),
                "fvg_5m_state": trace.get("fvg_5m_state"),
                "chase_state": trace.get("chase_state"),
            }
        )
    return sorted(
        summaries,
        key=lambda item: (
            item.get("reference_timestamp") or "",
            item.get("source_path") or "",
            item.get("decision") or "",
        ),
    )


def test_webhook_manual_assertion_normalize_evaluate_gate_end_to_end():
    normalized = normalize_tradingview_payload(
        {
            "ticker": "BITSTAMP:BTCUSD",
            "direction": "long",
            "timeframes": {"bias": "4H", "setup": "15m", "execution": "5m"},
            "checklist": {
                "clear_4h_bias": True,
                "clear_liquidity_draw": True,
                "liquidity_event": True,
                "mss": True,
                "displacement": True,
                "fresh_fvg": True,
                "clear_invalidation": True,
                "clear_target": True,
                "chase_entry": False,
            },
            "screenshot_paths": ["screenshots/manual-context.png"],
            "reference_at": "2026-04-18T06:30:00+00:00",
        }
    )
    evaluation = trading_server.evaluate_payload(normalized)

    assert normalized["source_mode"] == "manual_assertion"
    assert normalized["visual_analysis_state"] == "manual_context_only"
    assert evaluation["decision"] == "journal_only"
    assert decision_allows_execution_plan(evaluation["decision"]) is False


def test_webhook_scanner_verified_only_reaches_verified_paper_trade_with_full_gate():
    normalized = normalize_tradingview_payload(
        {
            "ticker": "BITSTAMP:BTCUSD",
            "source_mode": "scanner_verified",
            "direction": "long",
            "timeframes": {"bias": "4H", "setup": "15m", "execution": "5m"},
            "checklist": {
                "clear_4h_bias": True,
                "clear_liquidity_draw": True,
                "liquidity_event": True,
                "mss": True,
                "displacement": True,
                "fresh_fvg": True,
                "clear_invalidation": True,
                "clear_target": True,
                "chase_entry": False,
            },
            "reference_at": "2026-04-18T06:30:00+00:00",
        }
    )
    evaluation = trading_server.evaluate_payload(normalized)

    assert normalized["source_mode"] == "scanner_verified"
    assert evaluation["decision"] == "verified_paper_trade"
    assert decision_allows_execution_plan(evaluation["decision"]) is True


def test_watchlist_scan_verified_only_logs_when_decision_is_verified_paper_trade():
    created = {"entries": 0}

    def create_entry(payload, evaluation):
        created["entries"] += 1
        return "J-phase7"

    fake_store = SimpleNamespace(
        get_watchlist_state=lambda instrument: None,
        create_entry=create_entry,
        upsert_watchlist_state=lambda **kwargs: "WL-phase7",
        clear_watchlist_logged_state=lambda **kwargs: None,
        create_scan_history_entry=lambda **kwargs: "SH-phase7",
        create_signal_trace=lambda trace: "ST-phase7",
    )

    with patch.object(trading_server, "build_bybit_heuristic_scan", return_value=phase7_verified_scan_result()):
        with patch.object(trading_server.TradingAPIHandler, "store", fake_store):
            result = run_watchlist_scan(
                instruments=["BTCUSDT"],
                auto_log_candidates=True,
                persistent_dedupe=False,
                record_history=False,
            )

    item = result["results"][0]
    assert item["paper_trade_evaluation"]["decision"] == "verified_paper_trade"
    assert item["candidate_logged"] is True
    assert item["journal_id"] == "J-phase7"
    assert created["entries"] == 1


def test_replay_scan_reference_time_is_deterministic_end_to_end():
    bias_candles = build_parsed_series(240, 28, base=100.0, drift=0.18)
    setup_candles = build_parsed_series(15, 120, base=101.0, drift=0.06)
    execution_candles = build_parsed_series(5, 220, base=101.5, drift=0.03)

    def fake_fetch(symbol, interval, limit=200, category="linear"):
        candles = {
            trading_server.BYBIT_INTERVAL_MAP["4H"]: bias_candles,
            trading_server.BYBIT_INTERVAL_MAP["15m"]: setup_candles,
            trading_server.BYBIT_INTERVAL_MAP["5m"]: execution_candles,
        }[interval]
        return {"ok": True, "candles": candles}

    with patch.object(trading_server, "fetch_bybit_klines", side_effect=fake_fetch):
        first = run_bybit_replay_scan(
            symbol="BTCUSDT",
            category="linear",
            auto_log_candidates=False,
            record_history=False,
            max_steps=6,
            step_stride=7,
            tradable_only=False,
        )
        second = run_bybit_replay_scan(
            symbol="BTCUSDT",
            category="linear",
            auto_log_candidates=False,
            record_history=False,
            max_steps=6,
            step_stride=7,
            tradable_only=False,
        )

    assert first["ok"] is True
    assert second["ok"] is True
    assert sanitize_replay_result(first) == sanitize_replay_result(second)


def test_scanner_trace_creation_end_to_end():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase0-scanner.db")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            scan_result = dict(phase0_rejected_trace_scan_result())
            trace_id = trading_server.persist_signal_trace_for_scan_result(
                scan_result,
                source_path="scanner",
                category="linear",
            )
            record = store.get_signal_trace(trace_id)
            trace = record["trace"]
            assert trace["symbol"] == "BTCUSDT"
            assert trace["reference_timestamp"] == "2026-04-18T06:30:00+00:00"
            assert trace["source_path"] == "scanner"
            assert trace["drt_state"] == "ready"
            assert trace["drt_confidence"] == 0.82
            assert trace["liquidity_event"] == "raid_ssl_reject"
            assert trace["liquidity_reference_alignment"] == "aligned"
            assert trace["bias"] == "bullish"
            assert trace["narrative_state"] == "developing"
            assert trace["context_state"] == "watch"
            assert trace["session_state"] == "london"
            assert trace["mss_15m_state"] == "none"
            assert trace["displacement_5m_state"] == "bullish"
            assert trace["fvg_5m_state"] == "none"
            assert trace["chase_state"] == "not_chase"
            assert trace["decision"] == "no_paper_trade"
            assert trace["execution_eligible"] is False
            assert trace["blocker_reasons"]
            assert record["blocker_class"] == "premise_alignment"


def test_webhook_trace_creation_end_to_end():
    normalized = normalize_tradingview_payload(
        {
            "ticker": "BITSTAMP:BTCUSD",
            "direction": "long",
            "timeframes": {"bias": "4H", "setup": "15m", "execution": "5m"},
            "checklist": {
                "clear_4h_bias": True,
                "clear_liquidity_draw": True,
                "liquidity_event": True,
                "mss": True,
                "displacement": True,
                "fresh_fvg": True,
                "clear_invalidation": True,
                "clear_target": True,
                "chase_entry": False,
            },
            "screenshot_paths": ["screenshots/manual-context.png"],
            "reference_at": "2026-04-18T06:30:00+00:00",
        }
    )
    evaluation = trading_server.evaluate_payload(normalized)

    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase0-webhook.db")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            trace_id = trading_server.persist_signal_trace_for_evaluation(
                source_path="webhook",
                payload=normalized,
                evaluation=evaluation,
                webhook_id="TV-TRACE",
                reference_timestamp=normalized["reference_at"],
            )
            trace = store.get_signal_trace(trace_id)["trace"]
            assert trace["source_path"] == "webhook"
            assert trace["source_mode"] == "manual_assertion"
            assert trace["visual_analysis_state"] == "manual_context_only"
            assert trace["decision"] == "journal_only"
            assert trace["execution_eligible"] is False
            assert "source_mode manual_assertion remains journal-only by policy" in trace["blocker_reasons"]
            assert trace["webhook_id"] == "TV-TRACE"


def test_replay_trace_determinism_for_same_reference_timestamp():
    bias_candles = build_parsed_series(240, 28, base=100.0, drift=0.18)
    setup_candles = build_parsed_series(15, 120, base=101.0, drift=0.06)
    execution_candles = build_parsed_series(5, 220, base=101.5, drift=0.03)

    def fake_fetch(symbol, interval, limit=200, category="linear"):
        candles = {
            trading_server.BYBIT_INTERVAL_MAP["4H"]: bias_candles,
            trading_server.BYBIT_INTERVAL_MAP["15m"]: setup_candles,
            trading_server.BYBIT_INTERVAL_MAP["5m"]: execution_candles,
        }[interval]
        return {"ok": True, "candles": candles}

    with TemporaryDirectory() as first_tmpdir:
        first_store = trading_server.PaperTradeStore(Path(first_tmpdir) / "phase0-replay-first.db")
        with patch.object(trading_server, "fetch_bybit_klines", side_effect=fake_fetch):
            with patch.object(trading_server.TradingAPIHandler, "store", first_store):
                first = run_bybit_replay_scan(
                    symbol="BTCUSDT",
                    category="linear",
                    auto_log_candidates=False,
                    record_history=False,
                    max_steps=6,
                    step_stride=7,
                    tradable_only=False,
                )
                first_trace_summaries = collect_trace_summaries(first_store, source_path="replay")

    with TemporaryDirectory() as second_tmpdir:
        second_store = trading_server.PaperTradeStore(Path(second_tmpdir) / "phase0-replay-second.db")
        with patch.object(trading_server, "fetch_bybit_klines", side_effect=fake_fetch):
            with patch.object(trading_server.TradingAPIHandler, "store", second_store):
                second = run_bybit_replay_scan(
                    symbol="BTCUSDT",
                    category="linear",
                    auto_log_candidates=False,
                    record_history=False,
                    max_steps=6,
                    step_stride=7,
                    tradable_only=False,
                )
                second_trace_summaries = collect_trace_summaries(second_store, source_path="replay")

    assert first["ok"] is True
    assert second["ok"] is True
    assert first_trace_summaries == second_trace_summaries


def test_replay_signal_trace_list_persists_indexed_opportunity_state():
    bias = build_parsed_series(240, 160)
    setup = build_parsed_series(15, 400)
    execution = build_parsed_series(5, 1000)

    def fake_fetch(symbol, interval, limit=200, category="linear"):
        candles = {
            "240": bias,
            "15": setup,
            "5": execution,
        }[interval]
        return {"ok": True, "candles": candles}

    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase7-replay-opportunity.db")
        with patch.object(trading_server, "fetch_bybit_klines", side_effect=fake_fetch):
            with patch.object(trading_server.TradingAPIHandler, "store", store):
                result = run_bybit_replay_scan(
                    symbol="BTCUSDT",
                    category="linear",
                    auto_log_candidates=False,
                    record_history=False,
                    max_steps=3,
                    step_stride=10,
                    tradable_only=False,
                )

        assert result["ok"] is True
        rows = store.list_signal_traces(limit=10, source_path="replay")
        assert len(rows) == 3
        for row in rows:
            record = store.get_signal_trace(row["trace_id"])
            trace = record["trace"]
            assert row["opportunity_state"] == trace["opportunity_state"]
            assert row["opportunity_state"] in {"invalid", "context_watch", "near_miss", "awaiting_confirmation", "opportunity_detected"}


def test_verified_paper_trade_trace_vs_non_executable_trace_comparison():
    normalized = normalize_tradingview_payload(
        {
            "ticker": "BITSTAMP:BTCUSD",
            "direction": "long",
            "timeframes": {"bias": "4H", "setup": "15m", "execution": "5m"},
            "checklist": {
                "clear_4h_bias": True,
                "clear_liquidity_draw": True,
                "liquidity_event": True,
                "mss": True,
                "displacement": True,
                "fresh_fvg": True,
                "clear_invalidation": True,
                "clear_target": True,
                "chase_entry": False,
            },
            "screenshot_paths": ["screenshots/manual-context.png"],
            "reference_at": "2026-04-18T06:30:00+00:00",
        }
    )
    manual_evaluation = trading_server.evaluate_payload(normalized)

    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase0-compare.db")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            verified_id = trading_server.persist_signal_trace_for_scan_result(
                dict(phase0_verified_trace_scan_result()),
                source_path="scanner",
                category="linear",
            )
            blocked_id = trading_server.persist_signal_trace_for_evaluation(
                source_path="webhook",
                payload=normalized,
                evaluation=manual_evaluation,
                reference_timestamp=normalized["reference_at"],
            )
            verified_trace = store.get_signal_trace(verified_id)["trace"]
            blocked_trace = store.get_signal_trace(blocked_id)["trace"]
            assert verified_trace["decision"] == "verified_paper_trade"
            assert verified_trace["execution_eligible"] is True
            assert verified_trace["blocker_reasons"] == []
            assert blocked_trace["decision"] == "journal_only"
            assert blocked_trace["execution_eligible"] is False
            assert blocked_trace["blocker_reasons"]


def test_blocker_list_present_when_trade_is_rejected():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase0-blockers.db")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            trace_id = trading_server.persist_signal_trace_for_scan_result(
                dict(phase0_rejected_trace_scan_result()),
                source_path="watchlist",
                category="linear",
            )
            trace = store.get_signal_trace(trace_id)["trace"]
            assert trace["execution_eligible"] is False
            assert trace["blocker_reasons"]
            assert trace["source_path"] == "watchlist"


def test_legacy_compatibility_states_do_not_bypass_trace_semantics():
    legacy_result = {
        "ok": True,
        "instrument": "BTCUSDT",
        "scan_batch_id": "WL-legacy",
        "paper_trade_evaluation": {"decision": "paper_trade"},
        "paper_trade_payload": {
            "instrument": "BTCUSDT",
            "session": "london",
            "source_mode": "scanner_verified",
            "reference_at": "2026-04-18T06:30:00+00:00",
            "checklist": {"chase_entry": False},
        },
        "context": {
            "session": {
                "now_utc": "2026-04-18T06:30:00+00:00",
                "active_session": "london",
                "session_valid": True,
                "weekend": False,
            },
            "context_summary": {"state": "aligned", "execution_eligible": True},
            "mss_15m": {"state": "bullish_mss"},
            "displacement_5m": {"state": "bullish"},
            "fvg_5m": {"state": "bullish"},
            "chase_state": "not_chase",
        },
        "scan_signature": "legacy-trace",
    }

    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase0-legacy.db")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            trace_id = trading_server.persist_signal_trace_for_scan_result(
                legacy_result,
                source_path="scanner",
                category="linear",
            )
            trace = store.get_signal_trace(trace_id)["trace"]
            assert trace["decision"] == "paper_trade"
            assert trace["execution_eligible"] is False
            assert trace["blocker_reasons"]


def test_auto_execute_loop_disabled_policy_never_submits_even_with_verified_candidate():
    with patch.object(auto_execute_loop, "resolve_control_state", return_value={"effective_paused": False}):
        with patch.object(auto_execute_loop, "run_watchlist_scan") as mock_watchlist:
            with patch.object(auto_execute_loop, "submit_saved_order_proposal_record") as mock_submit:
                result = auto_execute_loop.run_cycle(
                    "phase7-runtime",
                    previous_state={},
                    policy={"enabled": False, "auto_submit": True},
                )

    assert result["mode"] == "disabled"
    assert result["summary"]["policy_enabled"] is False
    assert result["summary"]["submitted"] == 0
    mock_watchlist.assert_not_called()
    mock_submit.assert_not_called()


def test_legacy_paper_trade_decision_never_becomes_execution_payload():
    payload_result = build_auto_execution_payload(
        {
            "ok": True,
            "instrument": "BTCUSDT",
            "scan_signature": "phase7-legacy",
            "paper_trade_evaluation": {"decision": "paper_trade"},
            "context": {
                "auto_execution_levels": {
                    "ok": True,
                    "entry_price": "100.0",
                    "stop_loss": "99.0",
                    "take_profit": "102.0",
                }
            },
            "paper_trade_payload": {
                "instrument": "BTCUSDT",
                "session": "london",
                "direction": "long",
                "weekend": False,
                "timeframes": {"bias": "4H", "setup": "15m", "execution": "5m"},
                "checklist": {"liquidity_event": True, "chase_entry": False},
            },
        },
        {"category": "linear"},
        "phase7-runtime",
    )

    assert payload_result["ok"] is False
    assert payload_result["error"] == "paper_trade is not execution-eligible"


class TestPhase7Integration(unittest.TestCase):
    def test_webhook_manual_assertion_normalize_evaluate_gate_end_to_end(self):
        test_webhook_manual_assertion_normalize_evaluate_gate_end_to_end()

    def test_webhook_scanner_verified_only_reaches_verified_paper_trade_with_full_gate(self):
        test_webhook_scanner_verified_only_reaches_verified_paper_trade_with_full_gate()

    def test_watchlist_scan_verified_only_logs_when_decision_is_verified_paper_trade(self):
        test_watchlist_scan_verified_only_logs_when_decision_is_verified_paper_trade()

    def test_replay_scan_reference_time_is_deterministic_end_to_end(self):
        test_replay_scan_reference_time_is_deterministic_end_to_end()

    def test_scanner_trace_creation_end_to_end(self):
        test_scanner_trace_creation_end_to_end()

    def test_webhook_trace_creation_end_to_end(self):
        test_webhook_trace_creation_end_to_end()

    def test_replay_trace_determinism_for_same_reference_timestamp(self):
        test_replay_trace_determinism_for_same_reference_timestamp()

    def test_verified_paper_trade_trace_vs_non_executable_trace_comparison(self):
        test_verified_paper_trade_trace_vs_non_executable_trace_comparison()

    def test_blocker_list_present_when_trade_is_rejected(self):
        test_blocker_list_present_when_trade_is_rejected()

    def test_legacy_compatibility_states_do_not_bypass_trace_semantics(self):
        test_legacy_compatibility_states_do_not_bypass_trace_semantics()

    def test_auto_execute_loop_disabled_policy_never_submits_even_with_verified_candidate(self):
        test_auto_execute_loop_disabled_policy_never_submits_even_with_verified_candidate()

    def test_legacy_paper_trade_decision_never_becomes_execution_payload(self):
        test_legacy_paper_trade_decision_never_becomes_execution_payload()
