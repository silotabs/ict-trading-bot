from __future__ import annotations

import json
import sqlite3
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

import server as trading_server
import trading_store as trading_store_module


def minimal_context(opportunity_state="context_watch"):
    return {
        "session_state": "london",
        "narrative_state": "reversal",
        "context_state": "watch",
        "opportunity": {
            "state": opportunity_state,
            "reason": f"trace classified as {opportunity_state}",
        },
    }


def minimal_evaluation(decision="no_paper_trade"):
    return {"decision": decision, "blockers": []}


def minimal_payload(reference_at="2026-04-20T12:00:00+00:00"):
    return {"instrument": "BTCUSDT", "reference_at": reference_at}


def test_replay_insert_populates_indexed_opportunity_state():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-fix-replay-index.db")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            trace_id = trading_server.create_signal_trace(
                source_path="replay",
                payload=minimal_payload(),
                evaluation=minimal_evaluation(),
                context=minimal_context("context_watch"),
                symbol="BTCUSDT",
                reference_timestamp="2026-04-20T12:00:00+00:00",
            )

        record = store.get_signal_trace(trace_id)
        assert record["opportunity_state"] == "context_watch"
        assert record["trace"]["opportunity_state"] == "context_watch"


def test_replay_query_filtering_by_opportunity_state_works():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-fix-replay-filter.db")
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            trading_server.create_signal_trace(
                source_path="replay",
                payload=minimal_payload("2026-04-20T12:00:00+00:00"),
                evaluation=minimal_evaluation(),
                context=minimal_context("near_miss"),
                symbol="BTCUSDT",
                reference_timestamp="2026-04-20T12:00:00+00:00",
            )
            trading_server.create_signal_trace(
                source_path="replay",
                payload=minimal_payload("2026-04-20T12:05:00+00:00"),
                evaluation=minimal_evaluation(),
                context=minimal_context("awaiting_confirmation"),
                symbol="BTCUSDT",
                reference_timestamp="2026-04-20T12:05:00+00:00",
            )

        rows = store.list_signal_traces(limit=10, source_path="replay", opportunity_state="near_miss")
        assert len(rows) == 1
        assert rows[0]["opportunity_state"] == "near_miss"


def test_server_signal_trace_write_paths_populate_indexed_opportunity_state():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-fix-trace-paths.db")
        source_states = {
            "scanner": "opportunity_detected",
            "watchlist": "near_miss",
            "replay": "context_watch",
            "webhook": "awaiting_confirmation",
            "daemon": "invalid",
        }
        with patch.object(trading_server.TradingAPIHandler, "store", store):
            trace_ids = {
                source_path: trading_server.create_signal_trace(
                    source_path=source_path,
                    payload=minimal_payload(f"2026-04-20T12:0{index}:00+00:00"),
                    evaluation=minimal_evaluation(),
                    context=minimal_context(opportunity_state),
                    symbol="BTCUSDT",
                    reference_timestamp=f"2026-04-20T12:0{index}:00+00:00",
                )
                for index, (source_path, opportunity_state) in enumerate(source_states.items())
            }

        for source_path, opportunity_state in source_states.items():
            record = store.get_signal_trace(trace_ids[source_path])
            assert record["source_path"] == source_path
            assert record["opportunity_state"] == opportunity_state
            assert record["trace"]["opportunity_state"] == opportunity_state


def test_scan_result_persistence_populates_indexed_opportunity_state():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-fix-scan-result-trace.db")
        scan_result = {
            "ok": True,
            "instrument": "BTCUSDT",
            "scan_record_id": "SCAN-TRACE-001",
            "scan_batch_id": "BATCH-TRACE-001",
            "paper_trade_payload": minimal_payload(),
            "paper_trade_evaluation": minimal_evaluation(),
            "context": minimal_context("near_miss"),
        }

        with patch.object(trading_server.TradingAPIHandler, "store", store):
            trace_id = trading_server.persist_signal_trace_for_scan_result(
                scan_result,
                source_path="watchlist",
            )

        record = store.get_signal_trace(trace_id)
        assert scan_result["signal_trace_id"] == trace_id
        assert record["source_path"] == "watchlist"
        assert record["scan_id"] == "SCAN-TRACE-001"
        assert record["scan_batch_id"] == "BATCH-TRACE-001"
        assert record["opportunity_state"] == "near_miss"
        assert record["trace"]["opportunity_state"] == "near_miss"


def test_legacy_writer_shape_does_not_bypass_indexed_opportunity_population():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-fix-replay-legacy.db")
        trace_id = store.create_signal_trace(
            {
                "created_at": "2026-04-20T12:00:00+00:00",
                "symbol": "BTCUSDT",
                "reference_timestamp": "2026-04-20T12:00:00+00:00",
                "source_path": "replay",
                "source_mode": "scanner_verified",
                "decision": "no_paper_trade",
                "execution_eligible": False,
                "session_state": "london",
                "narrative_state": "reversal",
                "context_state": "watch",
                "blocker_classification": {},
                "blocker_reasons": [],
                "details": {
                    "opportunity": {
                        "state": "near_miss",
                        "reason": "legacy writer only provided nested opportunity state",
                    }
                },
            }
        )

        record = store.get_signal_trace(trace_id)
        assert record["opportunity_state"] == "near_miss"
        assert record["trace"]["opportunity_state"] == "near_miss"


def test_schema_backfill_repairs_blank_indexed_opportunity_state():
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "phase-fix-replay-backfill.db"
        store = trading_server.PaperTradeStore(db_path)
        with store._connect() as conn:
            conn.execute(
                """
                INSERT INTO signal_traces (
                    trace_id,
                    created_at,
                    symbol,
                    reference_timestamp,
                    source_path,
                    source_mode,
                    decision,
                    opportunity_state,
                    shadow_mode,
                    shadow_session_id,
                    execution_eligible,
                    blocker_class,
                    primary_blocker_reason,
                    session_state,
                    narrative_state,
                    context_state,
                    scan_batch_id,
                    scan_id,
                    journal_id,
                    webhook_id,
                    trace_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "ST-LEGACY",
                    "2026-04-20T12:00:00+00:00",
                    "BTCUSDT",
                    "2026-04-20T12:00:00+00:00",
                    "replay",
                    "scanner_verified",
                    "no_paper_trade",
                    None,
                    0,
                    None,
                    0,
                    None,
                    None,
                    "london",
                    "reversal",
                    "watch",
                    None,
                    None,
                    None,
                    None,
                    json.dumps(
                        {
                            "trace_id": "ST-LEGACY",
                            "created_at": "2026-04-20T12:00:00+00:00",
                            "symbol": "BTCUSDT",
                            "reference_timestamp": "2026-04-20T12:00:00+00:00",
                            "source_path": "replay",
                            "source_mode": "scanner_verified",
                            "decision": "no_paper_trade",
                            "opportunity_state": "context_watch",
                        },
                        sort_keys=True,
                    ),
                ),
            )
            conn.commit()

        repaired_store = trading_server.PaperTradeStore(db_path)
        record = repaired_store.get_signal_trace("ST-LEGACY")
        assert record["opportunity_state"] == "context_watch"
        assert record["trace"]["opportunity_state"] == "context_watch"


def test_signal_trace_creation_recovers_from_duplicate_trace_id_collision():
    with TemporaryDirectory() as tmpdir:
        store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-fix-replay-trace-id-race.db")

        original_next_id = trading_store_module.PaperTradeStore._next_id
        call_state = {"count": 0}

        def patched_next_id(self, conn, table_name, pk_column):
            if table_name == "signal_traces":
                call_state["count"] += 1
                if call_state["count"] == 2:
                    return 1
            return original_next_id(self, conn, table_name, pk_column)

        with patch.object(trading_store_module.PaperTradeStore, "_next_id", patched_next_id):
            first_id = store.create_signal_trace(
                {
                    "created_at": "2026-04-20T12:00:00+00:00",
                    "symbol": "BTCUSDT",
                    "reference_timestamp": "2026-04-20T12:00:00+00:00",
                    "source_path": "replay",
                    "source_mode": "scanner_verified",
                    "decision": "no_paper_trade",
                    "execution_eligible": False,
                    "session_state": "london",
                    "narrative_state": "reversal",
                    "context_state": "watch",
                    "blocker_classification": {},
                    "blocker_reasons": [],
                    "opportunity_state": "context_watch",
                }
            )
            second_id = store.create_signal_trace(
                {
                    "created_at": "2026-04-20T12:05:00+00:00",
                    "symbol": "BTCUSDT",
                    "reference_timestamp": "2026-04-20T12:05:00+00:00",
                    "source_path": "replay",
                    "source_mode": "scanner_verified",
                    "decision": "no_paper_trade",
                    "execution_eligible": False,
                    "session_state": "london",
                    "narrative_state": "reversal",
                    "context_state": "watch",
                    "blocker_classification": {},
                    "blocker_reasons": [],
                    "opportunity_state": "near_miss",
                }
            )

        assert first_id == "ST-00001"
        assert second_id == "ST-00002"
        rows = store.list_signal_traces(limit=10, source_path="replay")
        assert len(rows) == 2


class TestPhaseFixReplayTraceIndexing(unittest.TestCase):
    def test_replay_insert_populates_indexed_opportunity_state(self):
        test_replay_insert_populates_indexed_opportunity_state()

    def test_replay_query_filtering_by_opportunity_state_works(self):
        test_replay_query_filtering_by_opportunity_state_works()

    def test_server_signal_trace_write_paths_populate_indexed_opportunity_state(self):
        test_server_signal_trace_write_paths_populate_indexed_opportunity_state()

    def test_scan_result_persistence_populates_indexed_opportunity_state(self):
        test_scan_result_persistence_populates_indexed_opportunity_state()

    def test_legacy_writer_shape_does_not_bypass_indexed_opportunity_population(self):
        test_legacy_writer_shape_does_not_bypass_indexed_opportunity_population()

    def test_schema_backfill_repairs_blank_indexed_opportunity_state(self):
        test_schema_backfill_repairs_blank_indexed_opportunity_state()

    def test_signal_trace_creation_recovers_from_duplicate_trace_id_collision(self):
        test_signal_trace_creation_recovers_from_duplicate_trace_id_collision()
