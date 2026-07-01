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

import trading_store
from ict_engine.risk_controls import evaluate_execution_risk
from trading_store import PaperTradeStore


NOW_AT = "2026-05-05T10:00:00+00:00"


def base_policy(**overrides):
    policy = {
        "enabled": True,
        "max_daily_realized_loss": 0,
        "max_open_exposure_notional": 0,
        "max_active_intents_per_symbol": 0,
        "market_data_stale_after_seconds": 0,
        "execution_state_stale_after_seconds": 0,
        "loss_streak": {
            "max_consecutive_losses": 0,
            "cooldown_seconds": 0,
        },
    }
    policy.update(overrides)
    return policy


def scan_result():
    return {
        "ok": True,
        "instrument": "BTCUSDT",
        "scan_signature": "sig-risk-fix",
        "paper_trade_payload": {"reference_at": NOW_AT},
        "paper_trade_evaluation": {"decision": "verified_paper_trade"},
        "context": {
            "reference_at": NOW_AT,
            "auto_execution_levels": {
                "ok": True,
                "entry_price": "100",
                "stop_loss": "99",
                "take_profit": "102",
            },
        },
    }


def intent_record(intent_id="EI-risk-fix", symbol="BTCUSDT"):
    return {
        "intent_id": intent_id,
        "symbol": symbol,
        "scan_signature": "sig-risk-fix",
        "state": "signal_detected",
        "terminal": False,
    }


def proposal(symbol="BTCUSDT", qty="1", price="100"):
    return {
        "venue": "bybit_testnet",
        "status": "ready_for_submission",
        "symbol": symbol,
        "side": "Buy",
        "request": {
            "symbol": symbol,
            "orderType": "Limit",
            "qty": qty,
            "price": price,
        },
    }


def create_loss_entry(store, created_at, realized_pnl):
    evaluation = {
        "normalized": {"instrument": "BTCUSDT", "session": "london", "direction": "long"},
        "decision": "verified_paper_trade",
        "setup_tag": "risk control test",
        "confidence": "high",
    }
    with patch.object(trading_store, "utc_now_iso", return_value=created_at):
        journal_id = store.create_entry({"provider": "test"}, evaluation)
    store.update_outcome(journal_id, "loss", "loss recorded", realized_pnl)
    return journal_id


class PhaseFixRiskControlsTests(unittest.TestCase):
    def test_max_order_size_blocks_oversized_order_preview(self):
        with TemporaryDirectory() as tmpdir:
            store = PaperTradeStore(Path(tmpdir) / "max-order-size.db")
            result = evaluate_execution_risk(
                store=store,
                policy=base_policy(maximum_order_size={"max_notional": 100.0, "max_qty": 0}),
                scan_result=scan_result(),
                intent_record=intent_record(),
                order_preview=proposal(qty="2", price="75"),
                now_at=NOW_AT,
            )

        self.assertEqual(result["state"], "blocked")
        self.assertIn("max order notional exceeded", result["summary"])
        self.assertEqual(result["checks"]["max_order_size"]["status"], "blocked")

    def test_max_open_exposure_notional_blocks_active_intent_linked_to_limit_sized_proposal(self):
        with TemporaryDirectory() as tmpdir:
            store = PaperTradeStore(Path(tmpdir) / "max-open-exposure.db")
            proposal_id, _ = store.create_order_proposal(proposal(qty="2", price="50"))
            existing_intent = intent_record()
            existing_intent.update(
                {
                    "intent_key": "risk-fix:BTCUSDT:sig-open-exposure",
                    "source_path": "risk-fix",
                    "scan_signature": "sig-open-exposure",
                    "decision": "verified_paper_trade",
                }
            )
            existing_intent_id, _, _ = store.create_or_get_execution_intent(existing_intent)
            store.transition_execution_intent(
                existing_intent_id,
                "execution_plan_created",
                summary="proposal linked",
                proposal_id=proposal_id,
            )

            result = evaluate_execution_risk(
                store=store,
                policy=base_policy(max_open_exposure_notional=100.0),
                scan_result=scan_result(),
                intent_record=intent_record(intent_id="EI-risk-fix-next"),
                now_at=NOW_AT,
            )

        self.assertEqual(result["state"], "blocked")
        self.assertIn("max open exposure reached", result["summary"])
        self.assertEqual(result["checks"]["open_exposure"]["status"], "blocked")
        self.assertEqual(result["checks"]["open_exposure"]["details"]["total_notional"], 100.0)
        self.assertEqual(result["checks"]["open_exposure"]["details"]["limit"], 100.0)

    def test_duplicate_active_intent_blocks_second_non_terminal_intent_for_same_signal(self):
        with TemporaryDirectory() as tmpdir:
            store = PaperTradeStore(Path(tmpdir) / "duplicate-active-intent.db")
            existing_intent = intent_record()
            existing_intent.update(
                {
                    "intent_key": "risk-fix:BTCUSDT:sig-risk-fix",
                    "source_path": "risk-fix",
                    "decision": "verified_paper_trade",
                }
            )
            existing_intent_id, _, _ = store.create_or_get_execution_intent(existing_intent)

            result = evaluate_execution_risk(
                store=store,
                policy=base_policy(),
                scan_result=scan_result(),
                intent_record=intent_record(intent_id="EI-risk-fix-next"),
                now_at=NOW_AT,
            )

        self.assertEqual(result["state"], "blocked")
        self.assertIn("duplicate active intent already exists", result["summary"])
        self.assertEqual(result["checks"]["duplicate_active_intent"]["status"], "blocked")
        self.assertEqual(
            result["checks"]["duplicate_active_intent"]["details"]["duplicate_intent_ids"],
            [existing_intent_id],
        )

    def test_max_daily_order_count_blocks_next_order(self):
        with TemporaryDirectory() as tmpdir:
            store = PaperTradeStore(Path(tmpdir) / "daily-order-count.db")
            with patch.object(trading_store, "utc_now_iso", return_value=NOW_AT):
                store.create_order_proposal(proposal(), journal_id=None, webhook_id=None)

            result = evaluate_execution_risk(
                store=store,
                policy=base_policy(daily_order_count={"max_count": 1}),
                scan_result=scan_result(),
                intent_record=intent_record(),
                now_at=NOW_AT,
            )

        self.assertEqual(result["state"], "blocked")
        self.assertIn("max daily order count would be exceeded", result["summary"])
        self.assertEqual(result["checks"]["daily_order_count"]["details"]["current_count"], 1)

    def test_intraday_symbol_exposure_blocks_projected_exposure(self):
        with TemporaryDirectory() as tmpdir:
            store = PaperTradeStore(Path(tmpdir) / "symbol-exposure.db")
            store.upsert_execution_state(
                "BP-risk-fix",
                {
                    "venue": "bybit_testnet",
                    "symbol": "BTCUSDT",
                    "order": {"orderStatus": "Filled"},
                    "position": {"side": "Buy", "size": "2", "avgPrice": "60"},
                    "derived": {"lifecycle_status": "position_open"},
                },
            )

            result = evaluate_execution_risk(
                store=store,
                policy=base_policy(symbol_exposure={"max_intraday_position_exposure": 100.0}),
                scan_result=scan_result(),
                intent_record=intent_record(),
                order_preview=proposal(qty="1", price="10"),
                now_at=NOW_AT,
            )

        self.assertEqual(result["state"], "blocked")
        self.assertIn("max intraday exposure reached for BTCUSDT", result["summary"])
        self.assertEqual(result["checks"]["symbol_exposure"]["status"], "blocked")

    def test_manual_kill_switch_blocks_execution_advancement(self):
        with TemporaryDirectory() as tmpdir:
            store = PaperTradeStore(Path(tmpdir) / "manual-kill.db")
            result = evaluate_execution_risk(
                store=store,
                policy=base_policy(),
                scan_result=scan_result(),
                intent_record=intent_record(),
                control_states={
                    "global": {
                        "effective_paused": True,
                        "effective_reason": "manual kill switch engaged",
                    },
                    "auto_execution": {"effective_paused": False},
                    "order_submission": {"effective_paused": False},
                },
                now_at=NOW_AT,
            )

        self.assertEqual(result["state"], "blocked")
        self.assertIn("manual kill switch engaged", result["summary"])
        self.assertEqual(result["checks"]["manual_kill_switch"]["status"], "blocked")

    def test_automatic_kill_switch_triggers_from_daily_loss(self):
        with TemporaryDirectory() as tmpdir:
            store = PaperTradeStore(Path(tmpdir) / "auto-kill.db")
            create_loss_entry(store, "2026-05-05T01:00:00+00:00", "-150")

            result = evaluate_execution_risk(
                store=store,
                policy=base_policy(
                    max_daily_realized_loss=100.0,
                    automatic_kill_switch={
                        "enabled": True,
                        "trigger_checks": ["daily_realized_loss"],
                    },
                ),
                scan_result=scan_result(),
                intent_record=intent_record(),
                now_at=NOW_AT,
            )

        self.assertEqual(result["state"], "blocked")
        self.assertEqual(result["checks"]["daily_realized_loss"]["status"], "blocked")
        self.assertEqual(result["checks"]["automatic_kill_switch"]["status"], "blocked")

    def test_cancel_on_disconnect_blocks_new_execution_when_stream_is_down(self):
        with TemporaryDirectory() as tmpdir:
            store = PaperTradeStore(Path(tmpdir) / "cancel-disconnect.db")
            result = evaluate_execution_risk(
                store=store,
                policy=base_policy(
                    cancel_on_disconnect={
                        "enabled": True,
                        "block_new_orders_when_disconnected": True,
                        "cancel_open_orders": True,
                    },
                ),
                scan_result=scan_result(),
                intent_record=intent_record(),
                runtime_state={
                    "private_stream": {
                        "ready": False,
                        "reason": "private stream disconnected",
                    },
                },
                now_at=NOW_AT,
            )

        self.assertEqual(result["state"], "blocked")
        self.assertIn("cancel-on-disconnect guard is active", result["summary"])
        self.assertEqual(result["checks"]["cancel_on_disconnect"]["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
