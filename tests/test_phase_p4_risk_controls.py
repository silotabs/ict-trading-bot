from __future__ import annotations

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


def verified_scan_result(signature="sig-p4-verified", reference_at="2026-04-19T06:30:00+00:00"):
    return {
        "ok": True,
        "instrument": "BTCUSDT",
        "scan_signature": signature,
        "scan_batch_id": "WL-P4",
        "signal_trace_id": "ST-P4",
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


def phase_p4_policy():
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


def phase_p4_risk_policy(**overrides):
    policy = {
        "enabled": True,
        "max_daily_realized_loss": 200.0,
        "max_open_exposure_notional": 100000.0,
        "max_active_intents_per_symbol": 1,
        "market_data_stale_after_seconds": 600,
        "execution_state_stale_after_seconds": 900,
        "loss_streak": {
            "max_consecutive_losses": 2,
            "cooldown_seconds": 3600,
        },
    }
    policy.update(overrides)
    return {"ok": True, "policy": policy, "path": "/tmp/risk_control_policy.json", "errors": []}


def make_evaluation():
    return {
        "normalized": {"instrument": "BTCUSDT", "session": "london", "direction": "long"},
        "decision": "verified_paper_trade",
        "setup_tag": "starter verified",
        "confidence": "high",
    }


def create_loss_entry(store, created_at, realized_pnl):
    payload = {"provider": "test"}
    evaluation = make_evaluation()
    with patch.object(trading_server, "utc_now_iso", return_value=created_at):
        journal_id = store.create_entry(payload, evaluation)
    store.update_outcome(journal_id, "loss", "loss recorded", realized_pnl)
    return journal_id


def patch_plan_builders():
    return (
        patch.object(auto_execute_loop, "build_auto_execution_payload", return_value={"ok": True, "payload": {"instrument": "BTCUSDT"}, "levels": {"entry_price": "100", "stop_loss": "99", "take_profit": "102"}}),
        patch.object(auto_execute_loop, "evaluate_payload", return_value={"decision": "verified_paper_trade"}),
        patch.object(auto_execute_loop, "build_bybit_execution_plan", return_value={"status": "ready_for_submission", "venue": "bybit_testnet", "symbol": "BTCUSDT", "side": "Buy", "request": {"orderType": "Limit", "qty": "1", "price": "100"}}),
    )


def test_max_daily_loss_blocks_execution_advancement():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p4-loss.db")
        create_loss_entry(store, "2026-04-19T01:00:00+00:00", "-250")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            with patch.object(auto_execute_loop.TradingAPIHandler, "store", store):
                with patch.object(auto_execute_loop, "resolve_control_state", return_value={"effective_paused": False}):
                    with patch.object(auto_execute_loop, "run_watchlist_scan", return_value={"ok": True, "scanned_at": "2026-04-19T06:30:00+00:00", "results": [verified_scan_result()]}):
                        with patch.object(auto_execute_loop, "load_risk_control_policy", return_value=phase_p4_risk_policy(max_daily_realized_loss=100.0)):
                            result = auto_execute_loop.run_cycle("p4-runtime", previous_state={}, policy=phase_p4_policy())

        intent = store.list_execution_intents(limit=10)[0]
        risk_check = store.get_execution_risk_check(store.list_execution_risk_checks(limit=10)[0]["risk_check_id"])
        assert result["instrument_state"]["BTCUSDT"]["last_action"] == "risk_blocked"
        assert intent["state"] == "signal_detected"
        assert risk_check["state"] == "blocked"
        assert "max daily realized loss reached" in risk_check["risk_check"]["summary"]


def test_max_active_intent_count_per_symbol_blocks_new_intent_advancement():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p4-intents.db")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            first_intent = trading_server.ensure_execution_intent_for_scan_result(
                verified_scan_result(signature="sig-existing"),
                source_path="daemon",
                runtime_key="p4-runtime",
            )["intent_id"]
            store.transition_execution_intent(first_intent, "execution_plan_created", summary="existing active intent")

            with patch.object(auto_execute_loop.TradingAPIHandler, "store", store):
                with patch.object(auto_execute_loop, "resolve_control_state", return_value={"effective_paused": False}):
                    with patch.object(auto_execute_loop, "run_watchlist_scan", return_value={"ok": True, "scanned_at": "2026-04-19T06:30:00+00:00", "results": [verified_scan_result(signature="sig-new")]}):
                        with patch.object(auto_execute_loop, "load_risk_control_policy", return_value=phase_p4_risk_policy(max_active_intents_per_symbol=1)):
                            result = auto_execute_loop.run_cycle("p4-runtime", previous_state={}, policy=phase_p4_policy())

        risk_check = store.get_execution_risk_check(store.list_execution_risk_checks(limit=10)[0]["risk_check_id"])
        assert result["instrument_state"]["BTCUSDT"]["last_action"] == "risk_blocked"
        assert "max active intent count reached" in risk_check["risk_check"]["summary"]


def test_consecutive_loss_cooldown_blocks_execution_advancement():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p4-streak.db")
        create_loss_entry(store, "2026-04-19T05:10:00+00:00", "-50")
        create_loss_entry(store, "2026-04-19T05:20:00+00:00", "-25")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            with patch.object(auto_execute_loop.TradingAPIHandler, "store", store):
                with patch.object(auto_execute_loop, "resolve_control_state", return_value={"effective_paused": False}):
                    with patch.object(auto_execute_loop, "run_watchlist_scan", return_value={"ok": True, "scanned_at": "2026-04-19T06:30:00+00:00", "results": [verified_scan_result()]}):
                        with patch.object(auto_execute_loop, "load_risk_control_policy", return_value=phase_p4_risk_policy(loss_streak={"max_consecutive_losses": 2, "cooldown_seconds": 7200})):
                            result = auto_execute_loop.run_cycle("p4-runtime", previous_state={}, policy=phase_p4_policy())

        risk_check = store.get_execution_risk_check(store.list_execution_risk_checks(limit=10)[0]["risk_check_id"])
        assert result["instrument_state"]["BTCUSDT"]["last_action"] == "risk_blocked"
        assert "loss-streak cooldown is active" in risk_check["risk_check"]["summary"]


def test_stale_market_data_blocks_execution_advancement():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p4-market-stale.db")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            with patch.object(auto_execute_loop.TradingAPIHandler, "store", store):
                with patch.object(auto_execute_loop, "resolve_control_state", return_value={"effective_paused": False}):
                    with patch.object(auto_execute_loop, "run_watchlist_scan", return_value={"ok": True, "scanned_at": "2026-04-19T06:30:00+00:00", "results": [verified_scan_result(reference_at="2026-04-19T05:00:00+00:00")]}):
                        with patch.object(auto_execute_loop, "load_risk_control_policy", return_value=phase_p4_risk_policy(market_data_stale_after_seconds=300)):
                            result = auto_execute_loop.run_cycle("p4-runtime", previous_state={}, policy=phase_p4_policy())

        risk_check = store.get_execution_risk_check(store.list_execution_risk_checks(limit=10)[0]["risk_check_id"])
        assert result["instrument_state"]["BTCUSDT"]["last_action"] == "risk_blocked"
        assert "market data is stale" in risk_check["risk_check"]["summary"]


def test_stale_sync_state_blocks_execution_advancement():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p4-sync-stale.db")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            old_intent_id = trading_server.ensure_execution_intent_for_scan_result(
                verified_scan_result(signature="sig-old"),
                source_path="daemon",
                runtime_key="p4-runtime",
            )["intent_id"]
            proposal_id, proposal = store.create_order_proposal(
                {
                    "venue": "bybit_testnet",
                    "status": "ready_for_submission",
                    "symbol": "BTCUSDT",
                    "side": "Buy",
                    "request": {"orderType": "Limit", "qty": "1", "price": "100"},
                }
            )
            store.transition_execution_intent(old_intent_id, "execution_plan_created", summary="plan created", proposal_id=proposal_id)
            with patch.object(trading_server, "utc_now_iso", return_value="2026-04-19T05:00:00+00:00"):
                store.upsert_execution_state(
                    proposal_id,
                    {
                        "venue": "bybit_testnet",
                        "symbol": "BTCUSDT",
                        "order": {"orderStatus": "New"},
                        "position": {},
                        "derived": {"lifecycle_status": "working"},
                    },
                )
            with patch.object(auto_execute_loop.TradingAPIHandler, "store", store):
                with patch.object(auto_execute_loop, "resolve_control_state", return_value={"effective_paused": False}):
                    with patch.object(auto_execute_loop, "run_watchlist_scan", return_value={"ok": True, "scanned_at": "2026-04-19T06:30:00+00:00", "results": [verified_scan_result(signature="sig-new")]}):
                        with patch.object(auto_execute_loop, "load_risk_control_policy", return_value=phase_p4_risk_policy(execution_state_stale_after_seconds=300, max_active_intents_per_symbol=5)):
                            result = auto_execute_loop.run_cycle("p4-runtime", previous_state={}, policy=phase_p4_policy())

        risk_check = store.get_execution_risk_check(store.list_execution_risk_checks(limit=10)[0]["risk_check_id"])
        assert result["instrument_state"]["BTCUSDT"]["last_action"] == "risk_blocked"
        assert "stale execution-state lockout is active" in risk_check["risk_check"]["summary"]


def test_operator_emergency_stop_blocks_execution_advancement():
    def control_side_effect(key):
        if key == "global":
            return {"effective_paused": True, "effective_reason": "global emergency stop"}
        return {"effective_paused": False}

    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p4-stop.db")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            with patch.object(auto_execute_loop.TradingAPIHandler, "store", store):
                with patch.object(auto_execute_loop, "resolve_control_state", side_effect=control_side_effect):
                    with patch.object(auto_execute_loop, "run_watchlist_scan", return_value={"ok": True, "scanned_at": "2026-04-19T06:30:00+00:00", "results": [verified_scan_result()]}):
                        with patch.object(auto_execute_loop, "load_risk_control_policy", return_value=phase_p4_risk_policy()):
                            result = auto_execute_loop.run_cycle("p4-runtime", previous_state={}, policy=phase_p4_policy())

        risk_check = store.get_execution_risk_check(store.list_execution_risk_checks(limit=10)[0]["risk_check_id"])
        assert result["instrument_state"]["BTCUSDT"]["last_action"] == "risk_blocked"
        assert "global emergency stop" in risk_check["risk_check"]["summary"]


def test_risk_blocks_are_recorded_with_explicit_reasons():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p4-records.db")
        create_loss_entry(store, "2026-04-19T01:00:00+00:00", "-250")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            with patch.object(auto_execute_loop.TradingAPIHandler, "store", store):
                with patch.object(auto_execute_loop, "resolve_control_state", return_value={"effective_paused": False}):
                    with patch.object(auto_execute_loop, "run_watchlist_scan", return_value={"ok": True, "scanned_at": "2026-04-19T06:30:00+00:00", "results": [verified_scan_result()]}):
                        with patch.object(auto_execute_loop, "load_risk_control_policy", return_value=phase_p4_risk_policy(max_daily_realized_loss=100.0)):
                            result = auto_execute_loop.run_cycle("p4-runtime", previous_state={}, policy=phase_p4_policy())

        risk_record = store.list_execution_risk_checks(limit=10)[0]
        full_record = store.get_execution_risk_check(risk_record["risk_check_id"])
        assert risk_record["state"] == "blocked"
        assert full_record["risk_check"]["blocker_reasons"]
        assert result["instrument_state"]["BTCUSDT"]["details"]["risk_check_id"] == risk_record["risk_check_id"]


def test_risk_layer_never_creates_execution_on_its_own():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p4-no-create.db")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            with patch.object(auto_execute_loop.TradingAPIHandler, "store", store):
                with patch.object(auto_execute_loop, "resolve_control_state", return_value={"effective_paused": False}):
                    with patch.object(auto_execute_loop, "run_watchlist_scan", return_value={"ok": True, "scanned_at": "2026-04-19T06:30:00+00:00", "results": [{"ok": True, "instrument": "BTCUSDT", "scan_signature": "sig-p4-none", "paper_trade_evaluation": {"decision": "scanner_candidate"}}]}):
                        with patch.object(auto_execute_loop, "load_risk_control_policy", return_value=phase_p4_risk_policy()):
                            result = auto_execute_loop.run_cycle("p4-runtime", previous_state={}, policy=phase_p4_policy())

        assert result["instrument_state"]["BTCUSDT"]["last_action"] == "no_trade"
        assert store.list_execution_intents(limit=10) == []
        assert store.list_execution_risk_checks(limit=10) == []


def test_non_eligible_decisions_remain_non_executable_regardless_of_risk_state():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p4-noneligible.db")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            result = trading_server.ensure_execution_intent_for_scan_result(
                {
                    **verified_scan_result(),
                    "paper_trade_evaluation": {"decision": "scanner_candidate"},
                },
                source_path="daemon",
                runtime_key="p4-runtime",
            )

        assert result["ok"] is False
        assert store.list_execution_intents(limit=10) == []


class TestPhaseP4RiskControls(unittest.TestCase):
    def test_max_daily_loss_blocks_execution_advancement(self):
        test_max_daily_loss_blocks_execution_advancement()

    def test_max_active_intent_count_per_symbol_blocks_new_intent_advancement(self):
        test_max_active_intent_count_per_symbol_blocks_new_intent_advancement()

    def test_consecutive_loss_cooldown_blocks_execution_advancement(self):
        test_consecutive_loss_cooldown_blocks_execution_advancement()

    def test_stale_market_data_blocks_execution_advancement(self):
        test_stale_market_data_blocks_execution_advancement()

    def test_stale_sync_state_blocks_execution_advancement(self):
        test_stale_sync_state_blocks_execution_advancement()

    def test_operator_emergency_stop_blocks_execution_advancement(self):
        test_operator_emergency_stop_blocks_execution_advancement()

    def test_risk_blocks_are_recorded_with_explicit_reasons(self):
        test_risk_blocks_are_recorded_with_explicit_reasons()

    def test_risk_layer_never_creates_execution_on_its_own(self):
        test_risk_layer_never_creates_execution_on_its_own()

    def test_non_eligible_decisions_remain_non_executable_regardless_of_risk_state(self):
        test_non_eligible_decisions_remain_non_executable_regardless_of_risk_state()
