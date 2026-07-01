from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import auto_execute_loop
import server as trading_server
from runtime_config import load_auto_execution_policy
from runtime_repositories import build_runtime_repositories


def verified_scan_result(signature="sig-p5", reference_at="2026-04-19T06:30:00+00:00"):
    return {
        "ok": True,
        "instrument": "BTCUSDT",
        "scan_signature": signature,
        "scan_batch_id": "WL-P5",
        "signal_trace_id": "ST-P5",
        "paper_trade_payload": {
            "instrument": "BTCUSDT",
            "session": "london",
            "direction": "long",
            "reference_at": reference_at,
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
            "verification": {"source_mode": "scanner_verified", "visual_analysis_state": "not_run"},
        },
        "opportunity": {"state": "opportunity_detected"},
        "context": {
            "reference_at": reference_at,
            "session": {"active_session": "london", "session_valid": True, "weekend": False},
            "drt_4h": {"state": "ready", "confidence": 0.84},
            "bias_4h": {"bias": "bullish"},
            "narrative": {"state": "reversal"},
            "context_summary": {"state": "aligned", "premise_strength": "strong", "execution_eligible": True},
            "mss_15m": {"state": "bullish_mss"},
            "displacement_5m": {"state": "bullish"},
            "fvg_5m": {"state": "bullish"},
            "chase_state": "not_chase",
            "auto_execution_levels": {"ok": True, "entry_price": "100", "stop_loss": "99", "take_profit": "102"},
        },
    }


def phase_p5_policy():
    return {
        "enabled": True,
        "category": "linear",
        "instruments": ["BTCUSDT"],
        "record_scan_history": False,
        "require_private_stream": False,
        "max_active_proposals_total": 5,
        "max_active_proposals_per_symbol": 5,
        "auto_log_journal": False,
        "auto_submit": False,
    }


def phase_p5_risk_policy():
    return {
        "ok": True,
        "policy": {
            "enabled": True,
            "max_daily_realized_loss": 200.0,
            "max_open_exposure_notional": 100000.0,
            "max_active_intents_per_symbol": 5,
            "market_data_stale_after_seconds": 600,
            "execution_state_stale_after_seconds": 900,
            "loss_streak": {
                "max_consecutive_losses": 2,
                "cooldown_seconds": 3600,
            },
        },
        "path": "/tmp/risk_control_policy.json",
        "errors": [],
    }


class PhaseP5InfraHardeningTests(unittest.TestCase):
    def test_server_runtime_wiring_follows_current_store(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p5-wiring.db")
            with patch.object(trading_server.TradingAPIHandler, "store", store):
                trace_id = trading_server.create_signal_trace(
                    source_path="watchlist",
                    payload={"instrument": "BTCUSDT", "session": "london"},
                    evaluation={"decision": "no_paper_trade"},
                    context={"session_state": "valid"},
                    symbol="BTCUSDT",
                    reference_timestamp="2026-04-19T06:30:00+00:00",
                )
            record = store.get_signal_trace(trace_id)
            self.assertIsNotNone(record)
            self.assertEqual(record["symbol"], "BTCUSDT")

    def test_runtime_repository_round_trip_preserves_behavior(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p5-repos.db")
            repositories = build_runtime_repositories(store)

            trace_id = repositories.signal_traces.create(
                {
                    "symbol": "BTCUSDT",
                    "reference_timestamp": "2026-04-19T06:30:00+00:00",
                    "source_path": "watchlist",
                    "source_mode": "scanner_verified",
                    "decision": "verified_paper_trade",
                    "execution_eligible": True,
                    "session_state": "valid",
                    "narrative_state": "reversal",
                    "context_state": "aligned",
                    "blocker_classification": {},
                    "blocker_reasons": [],
                }
            )
            intent_id, _, _ = repositories.execution_intents.create_or_get(
                {
                    "intent_key": "daemon:BTCUSDT:sig-p5",
                    "source_path": "daemon",
                    "runtime_key": "default",
                    "symbol": "BTCUSDT",
                    "reference_timestamp": "2026-04-19T06:30:00+00:00",
                    "signal_trace_id": trace_id,
                    "scan_signature": "sig-p5",
                    "decision": "verified_paper_trade",
                    "opportunity_state": "opportunity_detected",
                    "state": "signal_detected",
                    "reason": "verified candidate",
                }
            )
            risk_check_id = repositories.execution_risk_checks.create(
                {
                    "checked_at": "2026-04-19T06:30:00+00:00",
                    "runtime_key": "default",
                    "intent_id": intent_id,
                    "symbol": "BTCUSDT",
                    "state": "allow",
                    "summary": "risk checks allow advancement",
                    "blocker_reasons": [],
                    "checks": {},
                }
            )

            self.assertEqual(repositories.signal_traces.get(trace_id)["trace_id"], trace_id)
            self.assertEqual(repositories.execution_intents.get(intent_id)["intent_id"], intent_id)
            self.assertEqual(repositories.execution_risk_checks.get(risk_check_id)["risk_check_id"], risk_check_id)

    def test_scan_history_entry_retries_after_scan_id_collision(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p5-scan-history.db")
            base_scan = {
                "scan_signature": "sig-phase-p5-scan",
                "candidate_logged": False,
                "duplicate_candidate": False,
                "journal_id": None,
                "paper_trade_payload": {"session": "london", "direction": "long"},
                "paper_trade_evaluation": {"decision": "no_paper_trade"},
            }

            first_id = store.create_scan_history_entry(
                source="watchlist",
                instrument="BTCUSDT",
                category="linear",
                scan_result=base_scan,
                scan_batch_id="WL-P5",
            )

            with patch.object(store, "_next_id", side_effect=[1, 2]):
                second_id = store.create_scan_history_entry(
                    source="watchlist",
                    instrument="BTCUSDT",
                    category="linear",
                    scan_result={**base_scan, "scan_signature": "sig-phase-p5-scan-2"},
                    scan_batch_id="WL-P5",
                )

            self.assertEqual(first_id, "SH-00001")
            self.assertEqual(second_id, "SH-00002")
            items = store.list_scan_history(limit=10)
            self.assertEqual(len(items), 2)
            self.assertEqual({item["scan_id"] for item in items}, {"SH-00001", "SH-00002"})

    def test_config_loading_remains_deterministic(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "auto_execution_policy.json"
            path.write_text(
                json.dumps(
                    {
                        "enabled": False,
                        "category": "linear",
                        "entry_model": "fvg_midpoint",
                        "stop_model": "sweep_or_fvg_boundary",
                        "target_model": "nearest_opposing_liquidity",
                        "instruments": ["BTCUSDT", "ETHUSDT"],
                    }
                )
            )
            first = load_auto_execution_policy(
                path,
                clean_string=trading_server.clean_string,
                normalize_instrument=trading_server.normalize_instrument,
                allowed_instruments=trading_server.RULES["allowed_instruments"],
            )
            second = load_auto_execution_policy(
                path,
                clean_string=trading_server.clean_string,
                normalize_instrument=trading_server.normalize_instrument,
                allowed_instruments=trading_server.RULES["allowed_instruments"],
            )
            self.assertEqual(first, second)
            self.assertTrue(first["ok"])

    def test_health_and_readiness_surfaces_reflect_critical_subsystems(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p5-health.db")
            sample_scan = {"instrument": "BTCUSDT", "paper_trade_evaluation": {"decision": "no_paper_trade"}}
            now_at = trading_server.utc_now_iso()
            with patch.object(trading_server.TradingAPIHandler, "store", store), \
                patch.object(trading_server, "BYBIT_ENABLE_PRIVATE_SUBMIT", False):
                initial_readiness = trading_server.build_readiness_payload()
                self.assertEqual(initial_readiness["status"], "not_ready")

                store.upsert_watchlist_state("BTCUSDT", "sig-btc", "no_paper_trade", sample_scan)
                store.upsert_watchlist_state("ETHUSDT", "sig-eth", "no_paper_trade", sample_scan)
                store.upsert_supervisor_runtime("default", state={}, last_summary={"scanned_at": now_at})
                store.upsert_private_stream_runtime(
                    "default",
                    "streaming",
                    subscriptions=["orders"],
                    state={"last_message_at": now_at},
                    connected_at=now_at,
                    last_message_at=now_at,
                )
                store.upsert_operations_runtime(
                    "public_market:default",
                    state={
                        "connection_status": "streaming",
                        "last_public_event_at": now_at,
                        "last_confirmed_close_processed_at": now_at,
                        "last_confirmed_close_reference_at": now_at,
                        "last_confirmed_close_reference_ms": 1760000000000,
                        "fallback_active": False,
                    },
                    last_summary={"scanned_at": now_at},
                )

                operations = trading_server.build_operations_status()
                readiness = trading_server.build_readiness_payload()

            self.assertIn(operations["overall"]["health"], {"healthy", "warning"})
            self.assertEqual(readiness["status"], "healthy_primary")
            self.assertEqual(readiness["blocker_count"], 0)

    def test_event_oms_and_risk_paths_still_function_after_decomposition(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p5-paths.db")
            with patch.object(trading_server.TradingAPIHandler, "store", store):
                with patch.object(auto_execute_loop.TradingAPIHandler, "store", store):
                    with patch.object(auto_execute_loop, "resolve_control_state", return_value={"effective_paused": False}):
                        with patch.object(
                            auto_execute_loop,
                            "run_watchlist_scan",
                            return_value={"ok": True, "scanned_at": "2026-04-19T06:30:00+00:00", "results": [verified_scan_result()]},
                        ):
                            with patch.object(auto_execute_loop, "load_risk_control_policy", return_value=phase_p5_risk_policy()):
                                with patch.object(
                                    auto_execute_loop,
                                    "build_auto_execution_payload",
                                    return_value={
                                        "ok": True,
                                        "payload": {"instrument": "BTCUSDT"},
                                        "levels": {"entry_price": "100", "stop_loss": "99", "take_profit": "102"},
                                    },
                                ):
                                    with patch.object(auto_execute_loop, "evaluate_payload", return_value={"decision": "verified_paper_trade"}):
                                        with patch.object(
                                            auto_execute_loop,
                                            "build_bybit_execution_plan",
                                            return_value={
                                                "status": "ready_for_submission",
                                                "venue": "bybit_testnet",
                                                "symbol": "BTCUSDT",
                                                "side": "Buy",
                                                "request": {"orderType": "Limit", "qty": "1", "price": "100"},
                                            },
                                        ):
                                            result = auto_execute_loop.run_cycle("p5-runtime", previous_state={}, policy=phase_p5_policy())

            self.assertEqual(result["instrument_state"]["BTCUSDT"]["last_action"], "proposal_created")
            self.assertEqual(len(store.list_execution_intents(limit=10)), 1)
            self.assertEqual(len(store.list_execution_risk_checks(limit=10)), 1)

    def test_execution_semantics_do_not_change(self):
        result = trading_server.ensure_execution_intent_for_scan_result(
            {
                "ok": True,
                "instrument": "BTCUSDT",
                "scan_signature": "sig-non-eligible",
                "paper_trade_evaluation": {"decision": "scanner_candidate"},
                "opportunity": {"state": "opportunity_detected"},
            },
            source_path="daemon",
        )
        self.assertFalse(result["ok"])
        self.assertIn("not execution-intent eligible", result["error"])


if __name__ == "__main__":
    unittest.main()
