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
from ict_engine.execution_state_machine import execution_intent_is_terminal


def verified_scan_result(signature="sig-p3-verified"):
    return {
        "ok": True,
        "instrument": "BTCUSDT",
        "scan_signature": signature,
        "scan_batch_id": "WL-P3",
        "signal_trace_id": "ST-P3",
        "paper_trade_payload": {
            "instrument": "BTCUSDT",
            "session": "london",
            "direction": "long",
            "reference_at": "2026-04-19T06:30:00+00:00",
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
            "reference_at": "2026-04-19T06:30:00+00:00",
            "session": {"active_session": "london", "session_valid": True, "weekend": False},
            "drt_4h": {"state": "ready", "confidence": 0.82},
            "bias_4h": {"bias": "bullish"},
            "narrative": {"state": "reversal"},
            "context_summary": {"state": "aligned", "premise_strength": "strong", "execution_eligible": True},
            "mss_15m": {"state": "bullish_mss"},
            "displacement_5m": {"state": "bullish"},
            "fvg_5m": {"state": "bullish"},
            "chase_state": "not_chase",
        },
    }


def non_eligible_scan_result(decision="no_paper_trade", opportunity_state="near_miss"):
    item = verified_scan_result(signature="sig-p3-blocked")
    item["paper_trade_evaluation"]["decision"] = decision
    item["opportunity"] = {"state": opportunity_state}
    return item


def phase_p3_policy(auto_submit=False):
    return {
        "enabled": True,
        "category": "linear",
        "instruments": ["BTCUSDT"],
        "record_scan_history": False,
        "require_private_stream": False,
        "max_active_proposals_total": 5,
        "max_active_proposals_per_symbol": 5,
        "auto_log_journal": False,
        "auto_submit": auto_submit,
    }


def test_verified_paper_trade_creates_one_execution_intent():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p3-intent.db")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            with patch.object(auto_execute_loop.TradingAPIHandler, "store", store):
                with patch.object(auto_execute_loop, "resolve_control_state", return_value={"effective_paused": False}):
                    with patch.object(auto_execute_loop, "run_watchlist_scan", return_value={"ok": True, "scanned_at": "2026-04-19T06:30:00+00:00", "results": [verified_scan_result()]}):
                        with patch.object(auto_execute_loop, "build_auto_execution_payload", return_value={"ok": True, "payload": {"instrument": "BTCUSDT"}, "levels": {"entry_price": "100", "stop_loss": "99", "take_profit": "102"}}):
                            with patch.object(auto_execute_loop, "evaluate_payload", return_value={"decision": "verified_paper_trade"}):
                                with patch.object(auto_execute_loop, "build_bybit_execution_plan", return_value={"status": "ready_for_submission", "venue": "bybit_testnet", "symbol": "BTCUSDT", "side": "Buy", "request": {"orderType": "Limit", "qty": "1", "price": "100"}}):
                                    result = auto_execute_loop.run_cycle("p3-runtime", previous_state={}, policy=phase_p3_policy())

        intents = store.list_execution_intents(limit=20)
        assert result["summary"]["verified_paper_trade_candidates"] == 1
        assert len(intents) == 1
        assert intents[0]["state"] == "execution_plan_created"


def test_non_eligible_decisions_never_create_execution_intent():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p3-blocked.db")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            result = trading_server.ensure_execution_intent_for_scan_result(
                non_eligible_scan_result(decision="no_paper_trade"),
                source_path="watchlist",
                runtime_key="p3-runtime",
            )

        assert result["ok"] is False
        assert store.list_execution_intents(limit=20) == []


def test_repeated_handling_of_the_same_eligible_signal_is_idempotent():
    scan_result = verified_scan_result(signature="sig-p3-repeat")
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p3-repeat.db")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            first = trading_server.ensure_execution_intent_for_scan_result(
                scan_result,
                source_path="daemon",
                runtime_key="p3-runtime",
            )
            second = trading_server.ensure_execution_intent_for_scan_result(
                scan_result,
                source_path="daemon",
                runtime_key="p3-runtime",
            )

        intents = store.list_execution_intents(limit=20)
        assert first["ok"] is True
        assert second["ok"] is True
        assert first["intent_id"] == second["intent_id"]
        assert len(intents) == 1


def test_rejection_cancel_fill_transitions_are_recorded_correctly():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p3-transitions.db")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            rejected_id = trading_server.ensure_execution_intent_for_scan_result(
                verified_scan_result(signature="sig-p3-rejected"),
                source_path="daemon",
                runtime_key="p3-runtime",
            )["intent_id"]
            store.transition_execution_intent(rejected_id, "execution_plan_created", summary="plan created")
            store.transition_execution_intent(rejected_id, "order_submission_pending", summary="submit pending")
            store.transition_execution_intent(rejected_id, "rejected", summary="exchange rejected")

            cancelled_id = trading_server.ensure_execution_intent_for_scan_result(
                verified_scan_result(signature="sig-p3-cancelled"),
                source_path="daemon",
                runtime_key="p3-runtime",
            )["intent_id"]
            store.transition_execution_intent(cancelled_id, "execution_plan_created", summary="plan created")
            store.transition_execution_intent(cancelled_id, "order_submission_pending", summary="submit pending")
            store.transition_execution_intent(cancelled_id, "order_submitted", summary="submitted")
            store.transition_execution_intent(cancelled_id, "order_acknowledged", summary="working")
            store.transition_execution_intent(cancelled_id, "cancelled", summary="cancelled")

            filled_id = trading_server.ensure_execution_intent_for_scan_result(
                verified_scan_result(signature="sig-p3-filled"),
                source_path="daemon",
                runtime_key="p3-runtime",
            )["intent_id"]
            store.transition_execution_intent(filled_id, "execution_plan_created", summary="plan created")
            store.transition_execution_intent(filled_id, "order_submission_pending", summary="submit pending")
            store.transition_execution_intent(filled_id, "order_submitted", summary="submitted")
            store.transition_execution_intent(filled_id, "order_acknowledged", summary="working")
            store.transition_execution_intent(filled_id, "fully_filled", summary="filled")

        assert store.get_execution_intent(rejected_id)["state"] == "rejected"
        assert store.get_execution_intent(cancelled_id)["state"] == "cancelled"
        assert store.get_execution_intent(filled_id)["state"] == "fully_filled"
        assert store.list_execution_intent_events(limit=20, intent_id=rejected_id)[0]["to_state"] == "rejected"


def test_flattened_reconciled_terminal_handling_works():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p3-terminal.db")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            intent_id = trading_server.ensure_execution_intent_for_scan_result(
                verified_scan_result(signature="sig-p3-terminal"),
                source_path="daemon",
                runtime_key="p3-runtime",
            )["intent_id"]
            store.transition_execution_intent(intent_id, "execution_plan_created", summary="plan created")
            store.transition_execution_intent(intent_id, "order_submission_pending", summary="submit pending")
            store.transition_execution_intent(intent_id, "order_submitted", summary="submitted")
            store.transition_execution_intent(intent_id, "order_acknowledged", summary="working")
            store.transition_execution_intent(intent_id, "fully_filled", summary="filled")
            store.transition_execution_intent(intent_id, "flattened", summary="position flattened")
            reconciled = store.transition_execution_intent(intent_id, "reconciled", summary="records reconciled")
            repeated = store.transition_execution_intent(intent_id, "reconciled", summary="records reconciled")

        record = store.get_execution_intent(intent_id)
        assert record["state"] == "reconciled"
        assert execution_intent_is_terminal(record["state"]) is True
        assert reconciled["ok"] is True
        assert repeated["changed"] is False


def test_opportunity_state_never_creates_execution_intent_by_itself():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p3-opportunity.db")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            result = trading_server.ensure_execution_intent_for_scan_result(
                non_eligible_scan_result(decision="scanner_candidate", opportunity_state="opportunity_detected"),
                source_path="daemon",
                runtime_key="p3-runtime",
            )

        assert result["ok"] is False
        assert "not execution-intent eligible" in result["error"]
        assert store.list_execution_intents(limit=20) == []


def test_legacy_decision_values_do_not_create_execution_intent():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p3-legacy.db")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            result = trading_server.ensure_execution_intent_for_scan_result(
                non_eligible_scan_result(decision="paper_trade", opportunity_state="opportunity_detected"),
                source_path="daemon",
                runtime_key="p3-runtime",
            )

        assert result["ok"] is False
        assert store.list_execution_intents(limit=20) == []


class TestPhaseP3ExecutionStateMachine(unittest.TestCase):
    def test_verified_paper_trade_creates_one_execution_intent(self):
        test_verified_paper_trade_creates_one_execution_intent()

    def test_non_eligible_decisions_never_create_execution_intent(self):
        test_non_eligible_decisions_never_create_execution_intent()

    def test_repeated_handling_of_the_same_eligible_signal_is_idempotent(self):
        test_repeated_handling_of_the_same_eligible_signal_is_idempotent()

    def test_rejection_cancel_fill_transitions_are_recorded_correctly(self):
        test_rejection_cancel_fill_transitions_are_recorded_correctly()

    def test_flattened_reconciled_terminal_handling_works(self):
        test_flattened_reconciled_terminal_handling_works()

    def test_opportunity_state_never_creates_execution_intent_by_itself(self):
        test_opportunity_state_never_creates_execution_intent_by_itself()

    def test_legacy_decision_values_do_not_create_execution_intent(self):
        test_legacy_decision_values_do_not_create_execution_intent()
