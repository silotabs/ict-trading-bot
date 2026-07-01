from __future__ import annotations

import json
import sqlite3
import threading

from ict_engine.execution_state_machine import (
    execution_intent_is_terminal,
    normalize_execution_intent_state,
    transition_validation_error,
)
from shared_utils import clean_string, coerce_bool, utc_now_iso
from trading_utils import (
    decimal_string,
    first_present,
    normalize_control_key,
    normalize_instrument,
)


SUPERVISOR_ACTIVE_PROPOSAL_STATUSES = {"ready_for_submission", "submitted_testnet"}
SQLITE_BUSY_TIMEOUT_SECONDS = 30.0
SQLITE_BUSY_TIMEOUT_MS = int(SQLITE_BUSY_TIMEOUT_SECONDS * 1000)


class PaperTradeStore:
    def __init__(self, db_path):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_db()

    def _connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=SQLITE_BUSY_TIMEOUT_SECONDS)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _next_id(self, conn, table_name, pk_column):
        return conn.execute(
            f"SELECT COALESCE(MAX({pk_column}), 0) + 1 AS next_id FROM {table_name}"
        ).fetchone()["next_id"]

    def _init_db(self):
        with self.lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS paper_trades (
                        entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        journal_id TEXT UNIQUE NOT NULL,
                        created_at TEXT NOT NULL,
                        instrument TEXT NOT NULL,
                        provider TEXT,
                        session TEXT,
                        direction TEXT,
                        decision TEXT NOT NULL,
                        setup_tag TEXT NOT NULL,
                        confidence TEXT NOT NULL,
                        result_status TEXT,
                        realized_pnl TEXT,
                        payload_json TEXT NOT NULL,
                        evaluation_json TEXT NOT NULL,
                        outcome_notes TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS webhook_events (
                        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        webhook_id TEXT UNIQUE NOT NULL,
                        created_at TEXT NOT NULL,
                        source TEXT NOT NULL,
                        instrument TEXT,
                        session TEXT,
                        direction TEXT,
                        decision TEXT,
                        paper_trade_journal_id TEXT,
                        proposal_id TEXT,
                        payload_json TEXT NOT NULL,
                        normalized_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS order_proposals (
                        proposal_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        proposal_id TEXT UNIQUE NOT NULL,
                        created_at TEXT NOT NULL,
                        venue TEXT NOT NULL,
                        status TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        side TEXT,
                        order_type TEXT,
                        qty TEXT,
                        price TEXT,
                        stop_loss TEXT,
                        take_profit TEXT,
                        paper_trade_journal_id TEXT,
                        webhook_id TEXT,
                        proposal_json TEXT NOT NULL,
                        submit_response_json TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS execution_state (
                        proposal_id TEXT PRIMARY KEY,
                        updated_at TEXT NOT NULL,
                        venue TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        sync_status TEXT NOT NULL,
                        order_id TEXT,
                        order_link_id TEXT,
                        order_status TEXT,
                        position_side TEXT,
                        position_size TEXT,
                        position_avg_price TEXT,
                        unrealised_pnl TEXT,
                        snapshot_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS execution_actions (
                        action_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        action_id TEXT UNIQUE NOT NULL,
                        created_at TEXT NOT NULL,
                        proposal_id TEXT NOT NULL,
                        venue TEXT NOT NULL,
                        action_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        order_id TEXT,
                        order_link_id TEXT,
                        symbol TEXT,
                        action_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS execution_intents (
                        intent_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        intent_id TEXT UNIQUE NOT NULL,
                        intent_key TEXT UNIQUE NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        source_path TEXT NOT NULL,
                        runtime_key TEXT,
                        symbol TEXT NOT NULL,
                        reference_timestamp TEXT,
                        signal_trace_id TEXT,
                        scan_id TEXT,
                        scan_batch_id TEXT,
                        scan_signature TEXT,
                        decision TEXT NOT NULL,
                        opportunity_state TEXT,
                        state TEXT NOT NULL,
                        terminal INTEGER NOT NULL DEFAULT 0,
                        proposal_id TEXT,
                        intent_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_execution_intents_symbol_state
                    ON execution_intents(symbol, state)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_execution_intents_scan_signature
                    ON execution_intents(scan_signature)
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS execution_intent_events (
                        intent_event_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT UNIQUE NOT NULL,
                        created_at TEXT NOT NULL,
                        intent_id TEXT NOT NULL,
                        from_state TEXT,
                        to_state TEXT NOT NULL,
                        proposal_id TEXT,
                        summary TEXT,
                        event_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_execution_intent_events_intent
                    ON execution_intent_events(intent_id, created_at)
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS execution_risk_checks (
                        risk_check_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        risk_check_id TEXT UNIQUE NOT NULL,
                        created_at TEXT NOT NULL,
                        runtime_key TEXT,
                        intent_id TEXT,
                        proposal_id TEXT,
                        symbol TEXT,
                        state TEXT NOT NULL,
                        primary_reason TEXT,
                        risk_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_execution_risk_checks_intent
                    ON execution_risk_checks(intent_id, created_at)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_execution_risk_checks_state
                    ON execution_risk_checks(state, created_at)
                    """
                )
                columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(paper_trades)").fetchall()
                }
                if "realized_pnl" not in columns:
                    conn.execute("ALTER TABLE paper_trades ADD COLUMN realized_pnl TEXT")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS watchlist_state (
                        instrument TEXT PRIMARY KEY,
                        updated_at TEXT NOT NULL,
                        last_scan_signature TEXT,
                        last_scan_decision TEXT,
                        last_logged_signature TEXT,
                        last_logged_journal_id TEXT,
                        last_scan_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS scan_history (
                        scan_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        scan_id TEXT UNIQUE NOT NULL,
                        created_at TEXT NOT NULL,
                        source TEXT NOT NULL,
                        scan_batch_id TEXT,
                        instrument TEXT NOT NULL,
                        category TEXT,
                        decision TEXT,
                        session TEXT,
                        direction TEXT,
                        scan_signature TEXT,
                        candidate_logged INTEGER NOT NULL DEFAULT 0,
                        duplicate_candidate INTEGER NOT NULL DEFAULT 0,
                        journal_id TEXT,
                        scan_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS signal_traces (
                        trace_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trace_id TEXT UNIQUE NOT NULL,
                        created_at TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        reference_timestamp TEXT,
                        source_path TEXT NOT NULL,
                        source_mode TEXT,
                        decision TEXT,
                        opportunity_state TEXT,
                        shadow_mode INTEGER NOT NULL DEFAULT 0,
                        shadow_session_id TEXT,
                        execution_eligible INTEGER NOT NULL DEFAULT 0,
                        blocker_class TEXT,
                        primary_blocker_reason TEXT,
                        session_state TEXT,
                        narrative_state TEXT,
                        context_state TEXT,
                        scan_batch_id TEXT,
                        scan_id TEXT,
                        journal_id TEXT,
                        webhook_id TEXT,
                        trace_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_signal_traces_symbol_reference
                    ON signal_traces(symbol, reference_timestamp)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_signal_traces_source_decision
                    ON signal_traces(source_path, decision)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_signal_traces_blocker_class
                    ON signal_traces(blocker_class)
                    """
                )
                signal_trace_columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(signal_traces)").fetchall()
                }
                if "opportunity_state" not in signal_trace_columns:
                    conn.execute("ALTER TABLE signal_traces ADD COLUMN opportunity_state TEXT")
                if "shadow_mode" not in signal_trace_columns:
                    conn.execute("ALTER TABLE signal_traces ADD COLUMN shadow_mode INTEGER NOT NULL DEFAULT 0")
                if "shadow_session_id" not in signal_trace_columns:
                    conn.execute("ALTER TABLE signal_traces ADD COLUMN shadow_session_id TEXT")
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_signal_traces_shadow_session
                    ON signal_traces(shadow_session_id, reference_timestamp)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_signal_traces_opportunity_state
                    ON signal_traces(opportunity_state)
                    """
                )
                conn.execute(
                    """
                    UPDATE signal_traces
                    SET opportunity_state = json_extract(trace_json, '$.opportunity_state')
                    WHERE (opportunity_state IS NULL OR trim(opportunity_state) = '')
                      AND json_extract(trace_json, '$.opportunity_state') IS NOT NULL
                      AND trim(json_extract(trace_json, '$.opportunity_state')) != ''
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS supervisor_runtime (
                        runtime_key TEXT PRIMARY KEY,
                        updated_at TEXT NOT NULL,
                        heartbeat_at TEXT NOT NULL,
                        last_scan_at TEXT,
                        last_summary_json TEXT NOT NULL,
                        state_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS supervisor_events (
                        event_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT UNIQUE NOT NULL,
                        created_at TEXT NOT NULL,
                        runtime_key TEXT NOT NULL,
                        proposal_id TEXT,
                        symbol TEXT,
                        severity TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        event_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS private_stream_runtime (
                        runtime_key TEXT PRIMARY KEY,
                        updated_at TEXT NOT NULL,
                        heartbeat_at TEXT NOT NULL,
                        connection_status TEXT NOT NULL,
                        connected_at TEXT,
                        last_message_at TEXT,
                        subscriptions_json TEXT NOT NULL,
                        state_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS private_stream_events (
                        event_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT UNIQUE NOT NULL,
                        created_at TEXT NOT NULL,
                        runtime_key TEXT NOT NULL,
                        proposal_id TEXT,
                        symbol TEXT,
                        severity TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        event_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS control_state (
                        control_key TEXT PRIMARY KEY,
                        updated_at TEXT NOT NULL,
                        paused INTEGER NOT NULL DEFAULT 0,
                        reason TEXT,
                        updated_by TEXT,
                        metadata_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS control_events (
                        event_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT UNIQUE NOT NULL,
                        created_at TEXT NOT NULL,
                        control_key TEXT NOT NULL,
                        paused INTEGER NOT NULL DEFAULT 0,
                        reason TEXT,
                        updated_by TEXT,
                        event_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS operations_runtime (
                        runtime_key TEXT PRIMARY KEY,
                        updated_at TEXT NOT NULL,
                        heartbeat_at TEXT NOT NULL,
                        last_scan_at TEXT,
                        last_summary_json TEXT NOT NULL,
                        state_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS operations_events (
                        event_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT UNIQUE NOT NULL,
                        created_at TEXT NOT NULL,
                        runtime_key TEXT NOT NULL,
                        component_key TEXT,
                        severity TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        event_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS auto_execution_runtime (
                        runtime_key TEXT PRIMARY KEY,
                        updated_at TEXT NOT NULL,
                        heartbeat_at TEXT NOT NULL,
                        last_scan_at TEXT,
                        last_summary_json TEXT NOT NULL,
                        state_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS auto_execution_events (
                        event_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT UNIQUE NOT NULL,
                        created_at TEXT NOT NULL,
                        runtime_key TEXT NOT NULL,
                        instrument TEXT,
                        proposal_id TEXT,
                        severity TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        event_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS trade_management_runtime (
                        runtime_key TEXT PRIMARY KEY,
                        updated_at TEXT NOT NULL,
                        heartbeat_at TEXT NOT NULL,
                        last_scan_at TEXT,
                        last_summary_json TEXT NOT NULL,
                        state_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS trade_management_events (
                        event_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT UNIQUE NOT NULL,
                        created_at TEXT NOT NULL,
                        runtime_key TEXT NOT NULL,
                        proposal_id TEXT,
                        symbol TEXT,
                        severity TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        event_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS concept_runtime (
                        runtime_key TEXT PRIMARY KEY,
                        updated_at TEXT NOT NULL,
                        heartbeat_at TEXT NOT NULL,
                        last_scan_at TEXT,
                        last_summary_json TEXT NOT NULL,
                        state_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS concept_events (
                        event_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT UNIQUE NOT NULL,
                        created_at TEXT NOT NULL,
                        runtime_key TEXT NOT NULL,
                        concept_id TEXT,
                        severity TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        event_json TEXT NOT NULL
                    )
                    """
                )
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
                conn.commit()
            finally:
                conn.close()

    def create_entry(self, payload, evaluation):
        with self.lock:
            conn = self._connect()
            try:
                next_id = self._next_id(conn, "paper_trades", "entry_id")
                journal_id = f"PT-{next_id:03d}"
                conn.execute(
                    """
                    INSERT INTO paper_trades (
                        journal_id,
                        created_at,
                        instrument,
                        provider,
                        session,
                        direction,
                        decision,
                        setup_tag,
                        confidence,
                        realized_pnl,
                        payload_json,
                        evaluation_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        journal_id,
                        utc_now_iso(),
                        evaluation["normalized"]["instrument"],
                        payload.get("provider"),
                        evaluation["normalized"]["session"],
                        evaluation["normalized"].get("direction"),
                        evaluation["decision"],
                        evaluation["setup_tag"],
                        evaluation["confidence"],
                        None,
                        json.dumps(payload, sort_keys=True),
                        json.dumps(evaluation, sort_keys=True),
                    ),
                )
                conn.commit()
                return journal_id
            finally:
                conn.close()

    def list_entries(self, limit=50):
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT journal_id, created_at, instrument, session, direction,
                       decision, setup_tag, confidence, result_status, realized_pnl
                FROM paper_trades
                ORDER BY entry_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_entry(self, journal_id):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM paper_trades
                WHERE journal_id = ?
                """,
                (journal_id,),
            ).fetchone()
            if row is None:
                return None

            record = dict(row)
            record["payload"] = json.loads(record.pop("payload_json"))
            record["evaluation"] = json.loads(record.pop("evaluation_json"))
            return record
        finally:
            conn.close()

    def update_outcome(self, journal_id, result_status, outcome_notes, realized_pnl=None):
        with self.lock:
            conn = self._connect()
            try:
                updated = conn.execute(
                    """
                    UPDATE paper_trades
                    SET result_status = ?, outcome_notes = ?, realized_pnl = ?
                    WHERE journal_id = ?
                    """,
                    (result_status, outcome_notes, decimal_string(realized_pnl), journal_id),
                )
                conn.commit()
                return updated.rowcount > 0
            finally:
                conn.close()

    def list_paper_trade_outcomes(self, limit=100, created_at_from=None, instrument=None):
        conn = self._connect()
        try:
            query = [
                """
                SELECT journal_id, created_at, instrument, result_status, realized_pnl
                FROM paper_trades
                """
            ]
            params = []
            filters = []
            if created_at_from:
                filters.append("created_at >= ?")
                params.append(created_at_from)
            if instrument:
                filters.append("instrument = ?")
                params.append(instrument)
            if filters:
                query.append("WHERE " + " AND ".join(filters))
            query.append("ORDER BY entry_id DESC")
            query.append("LIMIT ?")
            params.append(limit)
            rows = conn.execute("\n".join(query), params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def create_webhook_event(self, source, payload, normalized_summary, evaluation, journal_id=None):
        with self.lock:
            conn = self._connect()
            try:
                next_id = self._next_id(conn, "webhook_events", "event_id")
                webhook_id = f"TV-{next_id:03d}"
                conn.execute(
                    """
                    INSERT INTO webhook_events (
                        webhook_id,
                        created_at,
                        source,
                        instrument,
                        session,
                        direction,
                        decision,
                        paper_trade_journal_id,
                        payload_json,
                        normalized_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        webhook_id,
                        utc_now_iso(),
                        source,
                        normalized_summary.get("instrument"),
                        normalized_summary.get("session"),
                        normalized_summary.get("direction"),
                        evaluation.get("decision"),
                        journal_id,
                        json.dumps(payload, sort_keys=True),
                        json.dumps(normalized_summary, sort_keys=True),
                    ),
                )
                conn.commit()
                return webhook_id
            finally:
                conn.close()

    def update_webhook_proposal(self, webhook_id, proposal_id):
        with self.lock:
            conn = self._connect()
            try:
                updated = conn.execute(
                    """
                    UPDATE webhook_events
                    SET proposal_id = ?
                    WHERE webhook_id = ?
                    """,
                    (proposal_id, webhook_id),
                )
                conn.commit()
                return updated.rowcount > 0
            finally:
                conn.close()

    def list_webhook_events(self, limit=50):
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT webhook_id, created_at, source, instrument, session, direction,
                       decision, paper_trade_journal_id, proposal_id
                FROM webhook_events
                ORDER BY event_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_webhook_event(self, webhook_id):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM webhook_events
                WHERE webhook_id = ?
                """,
                (webhook_id,),
            ).fetchone()
            if row is None:
                return None

            record = dict(row)
            record["payload"] = json.loads(record.pop("payload_json"))
            record["normalized"] = json.loads(record.pop("normalized_json"))
            return record
        finally:
            conn.close()

    def create_order_proposal(self, proposal, journal_id=None, webhook_id=None):
        with self.lock:
            conn = self._connect()
            try:
                next_id = self._next_id(conn, "order_proposals", "proposal_entry_id")
                proposal_id = f"BP-{next_id:03d}"
                proposal_copy = dict(proposal)
                proposal_copy["proposal_id"] = proposal_id
                conn.execute(
                    """
                    INSERT INTO order_proposals (
                        proposal_id,
                        created_at,
                        venue,
                        status,
                        symbol,
                        side,
                        order_type,
                        qty,
                        price,
                        stop_loss,
                        take_profit,
                        paper_trade_journal_id,
                        webhook_id,
                        proposal_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        proposal_id,
                        utc_now_iso(),
                        proposal_copy["venue"],
                        proposal_copy["status"],
                        proposal_copy["symbol"],
                        proposal_copy.get("side"),
                        proposal_copy.get("request", {}).get("orderType"),
                        proposal_copy.get("request", {}).get("qty"),
                        proposal_copy.get("request", {}).get("price"),
                        proposal_copy.get("request", {}).get("stopLoss"),
                        proposal_copy.get("request", {}).get("takeProfit"),
                        journal_id,
                        webhook_id,
                        json.dumps(proposal_copy, sort_keys=True),
                    ),
                )
                conn.commit()
                return proposal_id, proposal_copy
            finally:
                conn.close()

    def list_order_proposals(self, limit=50):
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT proposal_id, created_at, venue, status, symbol, side,
                       order_type, qty, price, stop_loss, take_profit,
                       paper_trade_journal_id, webhook_id
                FROM order_proposals
                ORDER BY proposal_entry_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def list_order_proposal_ids(self, limit=50):
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT proposal_id
                FROM order_proposals
                ORDER BY proposal_entry_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [row["proposal_id"] for row in rows]
        finally:
            conn.close()

    def get_order_proposal(self, proposal_id):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM order_proposals
                WHERE proposal_id = ?
                """,
                (proposal_id,),
            ).fetchone()
            if row is None:
                return None

            record = dict(row)
            record["proposal"] = json.loads(record.pop("proposal_json"))
            if record["submit_response_json"]:
                record["submit_response"] = json.loads(record.pop("submit_response_json"))
            else:
                record.pop("submit_response_json")
            return record
        finally:
            conn.close()

    def find_order_proposal_for_stream(self, order_id=None, order_link_id=None, symbol=None, limit=250):
        order_id = clean_string(order_id)
        order_link_id = clean_string(order_link_id)
        symbol = normalize_instrument(symbol)
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT *
                FROM order_proposals
                ORDER BY proposal_entry_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            fallback = None
            for row in rows:
                record = dict(row)
                proposal = json.loads(record.pop("proposal_json"))
                submit_response = (
                    json.loads(record.pop("submit_response_json"))
                    if record.get("submit_response_json")
                    else None
                )
                request = proposal.get("request") if isinstance(proposal.get("request"), dict) else {}
                create_order_result = (
                    submit_response.get("create_order_result")
                    if isinstance(submit_response, dict)
                    else {}
                )
                create_payload = (
                    create_order_result.get("response", {}).get("result", {})
                    if isinstance(create_order_result, dict)
                    and isinstance(create_order_result.get("response"), dict)
                    else {}
                )
                candidate_symbol = normalize_instrument(
                    clean_string(first_present(request, ["symbol"]))
                    or clean_string(proposal.get("symbol"))
                    or clean_string(record.get("symbol"))
                )
                candidate_order_id = clean_string(first_present(create_payload, ["orderId"]))
                candidate_order_link_id = clean_string(
                    first_present(request, ["orderLinkId"])
                    or first_present(create_payload, ["orderLinkId"])
                )

                record["proposal"] = proposal
                if submit_response is not None:
                    record["submit_response"] = submit_response

                if order_id and candidate_order_id == order_id:
                    return record
                if order_link_id and candidate_order_link_id == order_link_id:
                    return record
                if (
                    fallback is None
                    and symbol
                    and candidate_symbol == symbol
                    and clean_string(record.get("status")) in SUPERVISOR_ACTIVE_PROPOSAL_STATUSES
                ):
                    fallback = record
            return fallback
        finally:
            conn.close()

    def update_order_proposal_submission(self, proposal_id, status, submit_response):
        with self.lock:
            conn = self._connect()
            try:
                updated = conn.execute(
                    """
                    UPDATE order_proposals
                    SET status = ?, submit_response_json = ?
                    WHERE proposal_id = ?
                    """,
                    (
                        status,
                        json.dumps(submit_response, sort_keys=True),
                        proposal_id,
                    ),
                )
                conn.commit()
                return updated.rowcount > 0
            finally:
                conn.close()

    def upsert_execution_state(self, proposal_id, snapshot):
        with self.lock:
            conn = self._connect()
            try:
                order = snapshot.get("order") if isinstance(snapshot.get("order"), dict) else {}
                position = snapshot.get("position") if isinstance(snapshot.get("position"), dict) else {}
                derived = snapshot.get("derived") if isinstance(snapshot.get("derived"), dict) else {}
                conn.execute(
                    """
                    INSERT INTO execution_state (
                        proposal_id,
                        updated_at,
                        venue,
                        symbol,
                        sync_status,
                        order_id,
                        order_link_id,
                        order_status,
                        position_side,
                        position_size,
                        position_avg_price,
                        unrealised_pnl,
                        snapshot_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(proposal_id) DO UPDATE SET
                        updated_at = excluded.updated_at,
                        venue = excluded.venue,
                        symbol = excluded.symbol,
                        sync_status = excluded.sync_status,
                        order_id = excluded.order_id,
                        order_link_id = excluded.order_link_id,
                        order_status = excluded.order_status,
                        position_side = excluded.position_side,
                        position_size = excluded.position_size,
                        position_avg_price = excluded.position_avg_price,
                        unrealised_pnl = excluded.unrealised_pnl,
                        snapshot_json = excluded.snapshot_json
                    """,
                    (
                        proposal_id,
                        utc_now_iso(),
                        snapshot.get("venue") or "unknown",
                        snapshot.get("symbol") or "unknown",
                        derived.get("lifecycle_status") or "unknown",
                        clean_string(first_present(order, ["orderId", "order_id"])),
                        clean_string(first_present(order, ["orderLinkId", "order_link_id"])),
                        clean_string(first_present(order, ["orderStatus", "order_status"])),
                        clean_string(first_present(position, ["side", "position_side"])),
                        clean_string(first_present(position, ["size", "position_size"])),
                        clean_string(first_present(position, ["avgPrice", "avg_price"])),
                        clean_string(first_present(position, ["unrealisedPnl", "unrealised_pnl"])),
                        json.dumps(snapshot, sort_keys=True),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def create_execution_action(self, proposal_id, action_type, status, action_payload):
        with self.lock:
            conn = self._connect()
            try:
                next_id = self._next_id(conn, "execution_actions", "action_entry_id")
                action_id = f"EA-{next_id:04d}"
                venue = clean_string(action_payload.get("venue")) or "unknown"
                order = action_payload.get("order") if isinstance(action_payload.get("order"), dict) else {}
                conn.execute(
                    """
                    INSERT INTO execution_actions (
                        action_id,
                        created_at,
                        proposal_id,
                        venue,
                        action_type,
                        status,
                        order_id,
                        order_link_id,
                        symbol,
                        action_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        action_id,
                        utc_now_iso(),
                        proposal_id,
                        venue,
                        action_type,
                        status,
                        clean_string(first_present(order, ["orderId", "order_id"])),
                        clean_string(first_present(order, ["orderLinkId", "order_link_id"])),
                        clean_string(action_payload.get("symbol")),
                        json.dumps(action_payload, sort_keys=True),
                    ),
                )
                conn.commit()
                return action_id
            finally:
                conn.close()

    def create_or_get_execution_intent(self, intent):
        intent = intent if isinstance(intent, dict) else {}
        intent_key = clean_string(intent.get("intent_key"))
        if not intent_key:
            raise ValueError("intent_key is required")

        with self.lock:
            conn = self._connect()
            try:
                existing = conn.execute(
                    """
                    SELECT *
                    FROM execution_intents
                    WHERE intent_key = ?
                    """,
                    (intent_key,),
                ).fetchone()
                if existing is not None:
                    record = dict(existing)
                    record["terminal"] = bool(record["terminal"])
                    record["intent"] = json.loads(record.pop("intent_json"))
                    return record["intent_id"], record, False

                next_id = self._next_id(conn, "execution_intents", "intent_entry_id")
                intent_id = f"EI-{next_id:05d}"
                created_at = utc_now_iso()
                stored_intent = dict(intent)
                stored_intent["intent_id"] = intent_id
                stored_intent["created_at"] = created_at
                stored_intent["updated_at"] = created_at
                stored_intent["state"] = normalize_execution_intent_state(
                    stored_intent.get("state"),
                    default="signal_detected",
                )
                stored_intent["terminal"] = execution_intent_is_terminal(stored_intent["state"])

                conn.execute(
                    """
                    INSERT INTO execution_intents (
                        intent_id,
                        intent_key,
                        created_at,
                        updated_at,
                        source_path,
                        runtime_key,
                        symbol,
                        reference_timestamp,
                        signal_trace_id,
                        scan_id,
                        scan_batch_id,
                        scan_signature,
                        decision,
                        opportunity_state,
                        state,
                        terminal,
                        proposal_id,
                        intent_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        intent_id,
                        intent_key,
                        created_at,
                        created_at,
                        clean_string(stored_intent.get("source_path")) or "unknown",
                        clean_string(stored_intent.get("runtime_key")),
                        clean_string(stored_intent.get("symbol")) or "unknown",
                        clean_string(stored_intent.get("reference_timestamp")),
                        clean_string(stored_intent.get("signal_trace_id")),
                        clean_string(stored_intent.get("scan_id")),
                        clean_string(stored_intent.get("scan_batch_id")),
                        clean_string(stored_intent.get("scan_signature")),
                        clean_string(stored_intent.get("decision")),
                        clean_string(stored_intent.get("opportunity_state")),
                        stored_intent["state"],
                        1 if stored_intent["terminal"] else 0,
                        clean_string(stored_intent.get("proposal_id")),
                        json.dumps(stored_intent, sort_keys=True),
                    ),
                )

                event_id = f"IE-{self._next_id(conn, 'execution_intent_events', 'intent_event_entry_id'):05d}"
                conn.execute(
                    """
                    INSERT INTO execution_intent_events (
                        event_id,
                        created_at,
                        intent_id,
                        from_state,
                        to_state,
                        proposal_id,
                        summary,
                        event_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        created_at,
                        intent_id,
                        None,
                        stored_intent["state"],
                        clean_string(stored_intent.get("proposal_id")),
                        clean_string(stored_intent.get("reason")) or "execution intent created",
                        json.dumps(
                            {
                                "intent_id": intent_id,
                                "event_type": "created",
                                "to_state": stored_intent["state"],
                                "summary": clean_string(stored_intent.get("reason")) or "execution intent created",
                                "details": stored_intent,
                            },
                            sort_keys=True,
                        ),
                    ),
                )

                conn.commit()
                record = {
                    "intent_id": intent_id,
                    "terminal": stored_intent["terminal"],
                    "intent": stored_intent,
                }
                return intent_id, record, True
            finally:
                conn.close()

    def list_execution_intents(self, limit=50, symbol=None, state=None, source_path=None, terminal=None):
        conn = self._connect()
        try:
            query = [
                """
                SELECT intent_id, created_at, updated_at, source_path, runtime_key, symbol,
                       reference_timestamp, signal_trace_id, scan_id, scan_batch_id,
                       scan_signature, decision, opportunity_state, state, terminal, proposal_id
                FROM execution_intents
                """
            ]
            params = []
            filters = []
            if symbol:
                filters.append("symbol = ?")
                params.append(symbol)
            if state:
                filters.append("state = ?")
                params.append(state)
            if source_path:
                filters.append("source_path = ?")
                params.append(source_path)
            if terminal is not None:
                filters.append("terminal = ?")
                params.append(1 if terminal else 0)
            if filters:
                query.append("WHERE " + " AND ".join(filters))
            query.append("ORDER BY intent_entry_id DESC")
            query.append("LIMIT ?")
            params.append(limit)
            rows = conn.execute("\n".join(query), params).fetchall()
            items = []
            for row in rows:
                record = dict(row)
                record["terminal"] = bool(record["terminal"])
                items.append(record)
            return items
        finally:
            conn.close()

    def get_execution_intent(self, intent_id):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM execution_intents
                WHERE intent_id = ?
                """,
                (intent_id,),
            ).fetchone()
            if row is None:
                return None
            record = dict(row)
            record["terminal"] = bool(record["terminal"])
            record["intent"] = json.loads(record.pop("intent_json"))
            return record
        finally:
            conn.close()

    def transition_execution_intent(self, intent_id, next_state, *, summary=None, proposal_id=None, details=None):
        with self.lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT *
                    FROM execution_intents
                    WHERE intent_id = ?
                    """,
                    (intent_id,),
                ).fetchone()
                if row is None:
                    return {"ok": False, "error": f"execution intent {intent_id} not found"}

                record = dict(row)
                current_intent = json.loads(record.pop("intent_json"))
                current_state = normalize_execution_intent_state(record.get("state"))
                target_state = normalize_execution_intent_state(next_state)

                validation_error = transition_validation_error(current_state, target_state)
                if validation_error is not None:
                    return {"ok": False, "error": validation_error, "intent": current_intent}

                existing_proposal_id = clean_string(proposal_id) or clean_string(record.get("proposal_id")) or clean_string(current_intent.get("proposal_id"))
                if current_state == target_state and existing_proposal_id == (clean_string(record.get("proposal_id")) or clean_string(current_intent.get("proposal_id"))):
                    current_intent["state"] = current_state
                    current_intent["proposal_id"] = existing_proposal_id
                    current_intent["terminal"] = execution_intent_is_terminal(current_state)
                    return {
                        "ok": True,
                        "changed": False,
                        "intent_id": intent_id,
                        "intent": current_intent,
                    }

                updated_at = utc_now_iso()
                current_intent["updated_at"] = updated_at
                current_intent["state"] = target_state
                current_intent["proposal_id"] = existing_proposal_id
                current_intent["terminal"] = execution_intent_is_terminal(target_state)
                if isinstance(details, dict) and details:
                    current_intent["last_transition_details"] = details
                if clean_string(summary):
                    current_intent["last_transition_summary"] = clean_string(summary)

                conn.execute(
                    """
                    UPDATE execution_intents
                    SET updated_at = ?, state = ?, terminal = ?, proposal_id = ?, intent_json = ?
                    WHERE intent_id = ?
                    """,
                    (
                        updated_at,
                        target_state,
                        1 if current_intent["terminal"] else 0,
                        existing_proposal_id,
                        json.dumps(current_intent, sort_keys=True),
                        intent_id,
                    ),
                )

                event_id = f"IE-{self._next_id(conn, 'execution_intent_events', 'intent_event_entry_id'):05d}"
                event_payload = {
                    "intent_id": intent_id,
                    "from_state": current_state,
                    "to_state": target_state,
                    "summary": clean_string(summary) or f"execution intent transitioned to {target_state}",
                    "proposal_id": existing_proposal_id,
                    "details": details if isinstance(details, dict) else {},
                }
                conn.execute(
                    """
                    INSERT INTO execution_intent_events (
                        event_id,
                        created_at,
                        intent_id,
                        from_state,
                        to_state,
                        proposal_id,
                        summary,
                        event_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        updated_at,
                        intent_id,
                        current_state,
                        target_state,
                        existing_proposal_id,
                        event_payload["summary"],
                        json.dumps(event_payload, sort_keys=True),
                    ),
                )
                conn.commit()
                return {
                    "ok": True,
                    "changed": True,
                    "intent_id": intent_id,
                    "event_id": event_id,
                    "intent": current_intent,
                }
            finally:
                conn.close()

    def list_execution_intent_events(self, limit=50, intent_id=None, to_state=None):
        conn = self._connect()
        try:
            query = [
                """
                SELECT event_id, created_at, intent_id, from_state, to_state, proposal_id, summary
                FROM execution_intent_events
                """
            ]
            params = []
            filters = []
            if intent_id:
                filters.append("intent_id = ?")
                params.append(intent_id)
            if to_state:
                filters.append("to_state = ?")
                params.append(to_state)
            if filters:
                query.append("WHERE " + " AND ".join(filters))
            query.append("ORDER BY intent_event_entry_id DESC")
            query.append("LIMIT ?")
            params.append(limit)
            rows = conn.execute("\n".join(query), params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_execution_intent_event(self, event_id):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM execution_intent_events
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()
            if row is None:
                return None
            record = dict(row)
            record["event"] = json.loads(record.pop("event_json"))
            return record
        finally:
            conn.close()

    def create_execution_risk_check(self, risk_check):
        risk_check = risk_check if isinstance(risk_check, dict) else {}
        with self.lock:
            conn = self._connect()
            try:
                next_id = self._next_id(conn, "execution_risk_checks", "risk_check_entry_id")
                risk_check_id = f"RC-{next_id:05d}"
                created_at = clean_string(risk_check.get("checked_at")) or utc_now_iso()
                stored = dict(risk_check)
                stored["risk_check_id"] = risk_check_id
                stored["created_at"] = created_at
                conn.execute(
                    """
                    INSERT INTO execution_risk_checks (
                        risk_check_id,
                        created_at,
                        runtime_key,
                        intent_id,
                        proposal_id,
                        symbol,
                        state,
                        primary_reason,
                        risk_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        risk_check_id,
                        created_at,
                        clean_string(stored.get("runtime_key")),
                        clean_string(stored.get("intent_id")),
                        clean_string(stored.get("proposal_id")),
                        clean_string(stored.get("symbol")),
                        clean_string(stored.get("state")) or "blocked",
                        clean_string((stored.get("blocker_reasons") or [None])[0]) or clean_string(stored.get("summary")),
                        json.dumps(stored, sort_keys=True),
                    ),
                )
                conn.commit()
                return risk_check_id
            finally:
                conn.close()

    def list_execution_risk_checks(self, limit=50, intent_id=None, state=None, symbol=None, runtime_key=None):
        conn = self._connect()
        try:
            query = [
                """
                SELECT risk_check_id, created_at, runtime_key, intent_id, proposal_id,
                       symbol, state, primary_reason
                FROM execution_risk_checks
                """
            ]
            params = []
            filters = []
            if intent_id:
                filters.append("intent_id = ?")
                params.append(intent_id)
            if state:
                filters.append("state = ?")
                params.append(state)
            if symbol:
                filters.append("symbol = ?")
                params.append(symbol)
            if runtime_key:
                filters.append("runtime_key = ?")
                params.append(runtime_key)
            if filters:
                query.append("WHERE " + " AND ".join(filters))
            query.append("ORDER BY risk_check_entry_id DESC")
            query.append("LIMIT ?")
            params.append(limit)
            rows = conn.execute("\n".join(query), params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_execution_risk_check(self, risk_check_id):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM execution_risk_checks
                WHERE risk_check_id = ?
                """,
                (risk_check_id,),
            ).fetchone()
            if row is None:
                return None
            record = dict(row)
            record["risk_check"] = json.loads(record.pop("risk_json"))
            return record
        finally:
            conn.close()

    def list_execution_actions(self, limit=50, proposal_id=None, action_type=None, status=None):
        conn = self._connect()
        try:
            query = [
                """
                SELECT action_id, created_at, proposal_id, venue, action_type, status,
                       order_id, order_link_id, symbol
                FROM execution_actions
                """
            ]
            params = []
            filters = []
            if proposal_id:
                filters.append("proposal_id = ?")
                params.append(proposal_id)
            if action_type:
                filters.append("action_type = ?")
                params.append(action_type)
            if status:
                filters.append("status = ?")
                params.append(status)
            if filters:
                query.append("WHERE " + " AND ".join(filters))
            query.append("ORDER BY action_entry_id DESC")
            query.append("LIMIT ?")
            params.append(limit)
            rows = conn.execute("\n".join(query), params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_execution_action(self, action_id):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM execution_actions
                WHERE action_id = ?
                """,
                (action_id,),
            ).fetchone()
            if row is None:
                return None
            record = dict(row)
            record["action"] = json.loads(record.pop("action_json"))
            return record
        finally:
            conn.close()

    def list_execution_state(self, limit=50, symbol=None, sync_status=None):
        conn = self._connect()
        try:
            query = [
                """
                SELECT proposal_id, updated_at, venue, symbol, sync_status, order_id,
                       order_link_id, order_status, position_side, position_size,
                       position_avg_price, unrealised_pnl
                FROM execution_state
                """
            ]
            params = []
            filters = []
            if symbol:
                filters.append("symbol = ?")
                params.append(symbol)
            if sync_status:
                filters.append("sync_status = ?")
                params.append(sync_status)
            if filters:
                query.append("WHERE " + " AND ".join(filters))
            query.append("ORDER BY updated_at DESC")
            query.append("LIMIT ?")
            params.append(limit)
            rows = conn.execute("\n".join(query), params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_execution_state(self, proposal_id):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM execution_state
                WHERE proposal_id = ?
                """,
                (proposal_id,),
            ).fetchone()
            if row is None:
                return None
            record = dict(row)
            record["snapshot"] = json.loads(record.pop("snapshot_json"))
            return record
        finally:
            conn.close()

    def stats(self):
        conn = self._connect()
        try:
            total = conn.execute("SELECT COUNT(*) AS count FROM paper_trades").fetchone()["count"]
            by_decision = {
                row["decision"]: row["count"]
                for row in conn.execute(
                    "SELECT decision, COUNT(*) AS count FROM paper_trades GROUP BY decision"
                ).fetchall()
            }
            by_result = {
                (row["result_status"] or "unset"): row["count"]
                for row in conn.execute(
                    "SELECT result_status, COUNT(*) AS count FROM paper_trades GROUP BY result_status"
                ).fetchall()
            }
            total_webhooks = conn.execute(
                "SELECT COUNT(*) AS count FROM webhook_events"
            ).fetchone()["count"]
            total_proposals = conn.execute(
                "SELECT COUNT(*) AS count FROM order_proposals"
            ).fetchone()["count"]
            total_execution_state = conn.execute(
                "SELECT COUNT(*) AS count FROM execution_state"
            ).fetchone()["count"]
            total_execution_actions = conn.execute(
                "SELECT COUNT(*) AS count FROM execution_actions"
            ).fetchone()["count"]
            total_watchlist_state = conn.execute(
                "SELECT COUNT(*) AS count FROM watchlist_state"
            ).fetchone()["count"]
            total_scan_history = conn.execute(
                "SELECT COUNT(*) AS count FROM scan_history"
            ).fetchone()["count"]
            total_supervisor_runtime = conn.execute(
                "SELECT COUNT(*) AS count FROM supervisor_runtime"
            ).fetchone()["count"]
            total_supervisor_events = conn.execute(
                "SELECT COUNT(*) AS count FROM supervisor_events"
            ).fetchone()["count"]
            total_private_stream_runtime = conn.execute(
                "SELECT COUNT(*) AS count FROM private_stream_runtime"
            ).fetchone()["count"]
            total_private_stream_events = conn.execute(
                "SELECT COUNT(*) AS count FROM private_stream_events"
            ).fetchone()["count"]
            total_control_state = conn.execute(
                "SELECT COUNT(*) AS count FROM control_state"
            ).fetchone()["count"]
            total_control_events = conn.execute(
                "SELECT COUNT(*) AS count FROM control_events"
            ).fetchone()["count"]
            total_operations_runtime = conn.execute(
                "SELECT COUNT(*) AS count FROM operations_runtime"
            ).fetchone()["count"]
            total_operations_events = conn.execute(
                "SELECT COUNT(*) AS count FROM operations_events"
            ).fetchone()["count"]
            total_auto_execution_runtime = conn.execute(
                "SELECT COUNT(*) AS count FROM auto_execution_runtime"
            ).fetchone()["count"]
            total_auto_execution_events = conn.execute(
                "SELECT COUNT(*) AS count FROM auto_execution_events"
            ).fetchone()["count"]
            total_trade_management_runtime = conn.execute(
                "SELECT COUNT(*) AS count FROM trade_management_runtime"
            ).fetchone()["count"]
            total_trade_management_events = conn.execute(
                "SELECT COUNT(*) AS count FROM trade_management_events"
            ).fetchone()["count"]
            proposal_statuses = {
                row["status"]: row["count"]
                for row in conn.execute(
                    "SELECT status, COUNT(*) AS count FROM order_proposals GROUP BY status"
                ).fetchall()
            }
            scan_history_by_source = {
                row["source"]: row["count"]
                for row in conn.execute(
                    "SELECT source, COUNT(*) AS count FROM scan_history GROUP BY source"
                ).fetchall()
            }
            scan_history_by_decision = {
                (row["decision"] or "unset"): row["count"]
                for row in conn.execute(
                    "SELECT decision, COUNT(*) AS count FROM scan_history GROUP BY decision"
                ).fetchall()
            }
            supervisor_events_by_type = {
                row["event_type"]: row["count"]
                for row in conn.execute(
                    "SELECT event_type, COUNT(*) AS count FROM supervisor_events GROUP BY event_type"
                ).fetchall()
            }
            supervisor_events_by_severity = {
                row["severity"]: row["count"]
                for row in conn.execute(
                    "SELECT severity, COUNT(*) AS count FROM supervisor_events GROUP BY severity"
                ).fetchall()
            }
            private_stream_events_by_type = {
                row["event_type"]: row["count"]
                for row in conn.execute(
                    "SELECT event_type, COUNT(*) AS count FROM private_stream_events GROUP BY event_type"
                ).fetchall()
            }
            private_stream_events_by_severity = {
                row["severity"]: row["count"]
                for row in conn.execute(
                    "SELECT severity, COUNT(*) AS count FROM private_stream_events GROUP BY severity"
                ).fetchall()
            }
            control_state_by_paused = {
                ("paused" if row["paused"] else "running"): row["count"]
                for row in conn.execute(
                    "SELECT paused, COUNT(*) AS count FROM control_state GROUP BY paused"
                ).fetchall()
            }
            control_events_by_paused = {
                ("paused" if row["paused"] else "running"): row["count"]
                for row in conn.execute(
                    "SELECT paused, COUNT(*) AS count FROM control_events GROUP BY paused"
                ).fetchall()
            }
            operations_events_by_type = {
                row["event_type"]: row["count"]
                for row in conn.execute(
                    "SELECT event_type, COUNT(*) AS count FROM operations_events GROUP BY event_type"
                ).fetchall()
            }
            operations_events_by_severity = {
                row["severity"]: row["count"]
                for row in conn.execute(
                    "SELECT severity, COUNT(*) AS count FROM operations_events GROUP BY severity"
                ).fetchall()
            }
            auto_execution_events_by_type = {
                row["event_type"]: row["count"]
                for row in conn.execute(
                    "SELECT event_type, COUNT(*) AS count FROM auto_execution_events GROUP BY event_type"
                ).fetchall()
            }
            auto_execution_events_by_severity = {
                row["severity"]: row["count"]
                for row in conn.execute(
                    "SELECT severity, COUNT(*) AS count FROM auto_execution_events GROUP BY severity"
                ).fetchall()
            }
            trade_management_events_by_type = {
                row["event_type"]: row["count"]
                for row in conn.execute(
                    "SELECT event_type, COUNT(*) AS count FROM trade_management_events GROUP BY event_type"
                ).fetchall()
            }
            trade_management_events_by_severity = {
                row["severity"]: row["count"]
                for row in conn.execute(
                    "SELECT severity, COUNT(*) AS count FROM trade_management_events GROUP BY severity"
                ).fetchall()
            }
            execution_state_by_status = {
                row["sync_status"]: row["count"]
                for row in conn.execute(
                    "SELECT sync_status, COUNT(*) AS count FROM execution_state GROUP BY sync_status"
                ).fetchall()
            }
            execution_actions_by_type = {
                row["action_type"]: row["count"]
                for row in conn.execute(
                    "SELECT action_type, COUNT(*) AS count FROM execution_actions GROUP BY action_type"
                ).fetchall()
            }
            execution_actions_by_status = {
                row["status"]: row["count"]
                for row in conn.execute(
                    "SELECT status, COUNT(*) AS count FROM execution_actions GROUP BY status"
                ).fetchall()
            }
            return {
                "total_entries": total,
                "by_decision": by_decision,
                "by_result": by_result,
                "total_webhooks": total_webhooks,
                "total_order_proposals": total_proposals,
                "total_execution_state": total_execution_state,
                "total_execution_actions": total_execution_actions,
                "total_watchlist_state": total_watchlist_state,
                "total_scan_history": total_scan_history,
                "total_supervisor_runtime": total_supervisor_runtime,
                "total_supervisor_events": total_supervisor_events,
                "total_private_stream_runtime": total_private_stream_runtime,
                "total_private_stream_events": total_private_stream_events,
                "total_control_state": total_control_state,
                "total_control_events": total_control_events,
                "total_operations_runtime": total_operations_runtime,
                "total_operations_events": total_operations_events,
                "total_auto_execution_runtime": total_auto_execution_runtime,
                "total_auto_execution_events": total_auto_execution_events,
                "total_trade_management_runtime": total_trade_management_runtime,
                "total_trade_management_events": total_trade_management_events,
                "by_proposal_status": proposal_statuses,
                "by_execution_state_status": execution_state_by_status,
                "by_execution_action_type": execution_actions_by_type,
                "by_execution_action_status": execution_actions_by_status,
                "by_scan_history_source": scan_history_by_source,
                "by_scan_history_decision": scan_history_by_decision,
                "by_supervisor_event_type": supervisor_events_by_type,
                "by_supervisor_event_severity": supervisor_events_by_severity,
                "by_private_stream_event_type": private_stream_events_by_type,
                "by_private_stream_event_severity": private_stream_events_by_severity,
                "by_control_state_paused": control_state_by_paused,
                "by_control_event_paused": control_events_by_paused,
                "by_operations_event_type": operations_events_by_type,
                "by_operations_event_severity": operations_events_by_severity,
                "by_auto_execution_event_type": auto_execution_events_by_type,
                "by_auto_execution_event_severity": auto_execution_events_by_severity,
                "by_trade_management_event_type": trade_management_events_by_type,
                "by_trade_management_event_severity": trade_management_events_by_severity,
            }
        finally:
            conn.close()

    def get_watchlist_state(self, instrument):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM watchlist_state
                WHERE instrument = ?
                """,
                (instrument,),
            ).fetchone()
            if row is None:
                return None

            record = dict(row)
            record["last_scan"] = json.loads(record.pop("last_scan_json"))
            return record
        finally:
            conn.close()

    def list_watchlist_state(self):
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT *
                FROM watchlist_state
                ORDER BY instrument ASC
                """
            ).fetchall()
            items = []
            for row in rows:
                record = dict(row)
                record["last_scan"] = json.loads(record.pop("last_scan_json"))
                items.append(record)
            return items
        finally:
            conn.close()

    def upsert_watchlist_state(
        self,
        instrument,
        scan_signature,
        scan_decision,
        scan_result,
        last_logged_signature=None,
        last_logged_journal_id=None,
    ):
        with self.lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO watchlist_state (
                        instrument,
                        updated_at,
                        last_scan_signature,
                        last_scan_decision,
                        last_logged_signature,
                        last_logged_journal_id,
                        last_scan_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(instrument) DO UPDATE SET
                        updated_at = excluded.updated_at,
                        last_scan_signature = excluded.last_scan_signature,
                        last_scan_decision = excluded.last_scan_decision,
                        last_logged_signature = COALESCE(excluded.last_logged_signature, watchlist_state.last_logged_signature),
                        last_logged_journal_id = COALESCE(excluded.last_logged_journal_id, watchlist_state.last_logged_journal_id),
                        last_scan_json = excluded.last_scan_json
                    """,
                    (
                        instrument,
                        utc_now_iso(),
                        scan_signature,
                        scan_decision,
                        last_logged_signature,
                        last_logged_journal_id,
                        json.dumps(scan_result, sort_keys=True),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def clear_watchlist_logged_state(self, instrument, scan_signature, scan_decision, scan_result):
        with self.lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO watchlist_state (
                        instrument,
                        updated_at,
                        last_scan_signature,
                        last_scan_decision,
                        last_logged_signature,
                        last_logged_journal_id,
                        last_scan_json
                    ) VALUES (?, ?, ?, ?, NULL, NULL, ?)
                    ON CONFLICT(instrument) DO UPDATE SET
                        updated_at = excluded.updated_at,
                        last_scan_signature = excluded.last_scan_signature,
                        last_scan_decision = excluded.last_scan_decision,
                        last_logged_signature = NULL,
                        last_logged_journal_id = NULL,
                        last_scan_json = excluded.last_scan_json
                    """,
                    (
                        instrument,
                        utc_now_iso(),
                        scan_signature,
                        scan_decision,
                        json.dumps(scan_result, sort_keys=True),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def create_scan_history_entry(
        self,
        source,
        instrument,
        category,
        scan_result,
        scan_batch_id=None,
    ):
        evaluation = scan_result.get("paper_trade_evaluation") or {}
        payload = scan_result.get("paper_trade_payload") or {}

        with self.lock:
            last_error = None
            for _ in range(3):
                conn = self._connect()
                try:
                    # Serialize scan-history ID allocation across daemon processes.
                    conn.execute("BEGIN IMMEDIATE")
                    next_id = self._next_id(conn, "scan_history", "scan_entry_id")
                    scan_id = f"SH-{next_id:05d}"
                    conn.execute(
                        """
                        INSERT INTO scan_history (
                            scan_id,
                            created_at,
                            source,
                            scan_batch_id,
                            instrument,
                            category,
                            decision,
                            session,
                            direction,
                            scan_signature,
                            candidate_logged,
                            duplicate_candidate,
                            journal_id,
                            scan_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            scan_id,
                            utc_now_iso(),
                            source,
                            scan_batch_id,
                            instrument,
                            category,
                            evaluation.get("decision"),
                            payload.get("session"),
                            payload.get("direction"),
                            scan_result.get("scan_signature"),
                            1 if scan_result.get("candidate_logged") else 0,
                            1 if scan_result.get("duplicate_candidate") else 0,
                            scan_result.get("journal_id"),
                            json.dumps(scan_result, sort_keys=True),
                        ),
                    )
                    conn.commit()
                    return scan_id
                except sqlite3.IntegrityError as exc:
                    conn.rollback()
                    if "scan_history.scan_id" not in str(exc):
                        raise
                    last_error = exc
                finally:
                    conn.close()

            if last_error is not None:
                raise last_error

    def list_scan_history(
        self,
        limit=100,
        instrument=None,
        source=None,
        decision=None,
        scan_batch_id=None,
    ):
        conn = self._connect()
        try:
            query = [
                """
                SELECT scan_id, created_at, source, scan_batch_id, instrument, category,
                       decision, session, direction, scan_signature,
                       candidate_logged, duplicate_candidate, journal_id
                FROM scan_history
                """
            ]
            params = []
            filters = []
            if instrument:
                filters.append("instrument = ?")
                params.append(instrument)
            if source:
                filters.append("source = ?")
                params.append(source)
            if decision:
                filters.append("decision = ?")
                params.append(decision)
            if scan_batch_id:
                filters.append("scan_batch_id = ?")
                params.append(scan_batch_id)
            if filters:
                query.append("WHERE " + " AND ".join(filters))
            query.append("ORDER BY scan_entry_id DESC")
            query.append("LIMIT ?")
            params.append(limit)

            rows = conn.execute("\n".join(query), params).fetchall()
            items = []
            for row in rows:
                record = dict(row)
                record["candidate_logged"] = bool(record["candidate_logged"])
                record["duplicate_candidate"] = bool(record["duplicate_candidate"])
                items.append(record)
            return items
        finally:
            conn.close()

    def get_scan_history_entry(self, scan_id):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM scan_history
                WHERE scan_id = ?
                """,
                (scan_id,),
            ).fetchone()
            if row is None:
                return None

            record = dict(row)
            record["candidate_logged"] = bool(record["candidate_logged"])
            record["duplicate_candidate"] = bool(record["duplicate_candidate"])
            record["scan"] = json.loads(record.pop("scan_json"))
            return record
        finally:
            conn.close()

    def create_signal_trace(self, trace):
        trace = trace if isinstance(trace, dict) else {}

        with self.lock:
            last_error = None
            for _ in range(3):
                conn = self._connect()
                try:
                    # Serialize signal-trace ID allocation across daemon and replay processes.
                    conn.execute("BEGIN IMMEDIATE")
                    next_id = self._next_id(conn, "signal_traces", "trace_entry_id")
                    trace_id = f"ST-{next_id:05d}"
                    created_at = clean_string(trace.get("created_at")) or utc_now_iso()
                    blocker_classification = (
                        trace.get("blocker_classification")
                        if isinstance(trace.get("blocker_classification"), dict)
                        else {}
                    )
                    blocker_reasons = trace.get("blocker_reasons") if isinstance(trace.get("blocker_reasons"), list) else []
                    stored_trace = dict(trace)
                    stored_trace["trace_id"] = trace_id
                    stored_trace["created_at"] = created_at
                    opportunity_state = (
                        clean_string(stored_trace.get("opportunity_state"))
                        or clean_string(((stored_trace.get("details") or {}).get("opportunity") or {}).get("state"))
                    )
                    if opportunity_state:
                        stored_trace["opportunity_state"] = opportunity_state
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
                            trace_id,
                            created_at,
                            clean_string(stored_trace.get("symbol")) or "unknown",
                            clean_string(stored_trace.get("reference_timestamp")),
                            clean_string(stored_trace.get("source_path")) or "daemon",
                            clean_string(stored_trace.get("source_mode")),
                            clean_string(stored_trace.get("decision")),
                            opportunity_state,
                            1 if bool(stored_trace.get("shadow_mode")) else 0,
                            clean_string(stored_trace.get("shadow_session_id")),
                            1 if bool(stored_trace.get("execution_eligible")) else 0,
                            clean_string(blocker_classification.get("primary")),
                            clean_string(blocker_reasons[0]) if blocker_reasons else None,
                            clean_string(stored_trace.get("session_state")),
                            clean_string(stored_trace.get("narrative_state")),
                            clean_string(stored_trace.get("context_state")),
                            clean_string(stored_trace.get("scan_batch_id")),
                            clean_string(stored_trace.get("scan_id")),
                            clean_string(stored_trace.get("journal_id")),
                            clean_string(stored_trace.get("webhook_id")),
                            json.dumps(stored_trace, sort_keys=True),
                        ),
                    )
                    conn.commit()
                    return trace_id
                except sqlite3.IntegrityError as exc:
                    conn.rollback()
                    if "signal_traces.trace_id" not in str(exc):
                        raise
                    last_error = exc
                finally:
                    conn.close()

            if last_error is not None:
                raise last_error

    def list_signal_traces(
        self,
        limit=100,
        symbol=None,
        source_path=None,
        decision=None,
        opportunity_state=None,
        blocker_class=None,
        blocker_reason_contains=None,
        execution_eligible=None,
        reference_timestamp_from=None,
        reference_timestamp_to=None,
        journal_id=None,
        webhook_id=None,
        scan_batch_id=None,
        source_mode=None,
        shadow_mode=None,
        shadow_session_id=None,
        session_state=None,
    ):
        conn = self._connect()
        try:
            query = [
                """
                SELECT trace_id, created_at, symbol, reference_timestamp, source_path,
                       source_mode, decision, opportunity_state, shadow_mode, shadow_session_id,
                       execution_eligible, blocker_class, primary_blocker_reason,
                       session_state, narrative_state, context_state, scan_batch_id, scan_id,
                       journal_id, webhook_id
                FROM signal_traces
                """
            ]
            params = []
            filters = []
            if symbol:
                filters.append("symbol = ?")
                params.append(symbol)
            if source_path:
                filters.append("source_path = ?")
                params.append(source_path)
            if decision:
                filters.append("decision = ?")
                params.append(decision)
            if opportunity_state:
                filters.append("opportunity_state = ?")
                params.append(opportunity_state)
            if blocker_class:
                filters.append("blocker_class = ?")
                params.append(blocker_class)
            if blocker_reason_contains:
                filters.append("primary_blocker_reason LIKE ?")
                params.append(f"%{blocker_reason_contains}%")
            if execution_eligible is not None:
                filters.append("execution_eligible = ?")
                params.append(1 if execution_eligible else 0)
            if reference_timestamp_from:
                filters.append("reference_timestamp >= ?")
                params.append(reference_timestamp_from)
            if reference_timestamp_to:
                filters.append("reference_timestamp <= ?")
                params.append(reference_timestamp_to)
            if journal_id:
                filters.append("journal_id = ?")
                params.append(journal_id)
            if webhook_id:
                filters.append("webhook_id = ?")
                params.append(webhook_id)
            if scan_batch_id:
                filters.append("scan_batch_id = ?")
                params.append(scan_batch_id)
            if source_mode:
                filters.append("source_mode = ?")
                params.append(source_mode)
            if shadow_mode is not None:
                filters.append("shadow_mode = ?")
                params.append(1 if shadow_mode else 0)
            if shadow_session_id:
                filters.append("shadow_session_id = ?")
                params.append(shadow_session_id)
            if session_state:
                filters.append("session_state = ?")
                params.append(session_state)
            if filters:
                query.append("WHERE " + " AND ".join(filters))
            query.append("ORDER BY COALESCE(reference_timestamp, created_at) DESC, trace_entry_id DESC")
            query.append("LIMIT ?")
            params.append(limit)

            rows = conn.execute("\n".join(query), params).fetchall()
            items = []
            for row in rows:
                record = dict(row)
                record["execution_eligible"] = bool(record["execution_eligible"])
                record["shadow_mode"] = bool(record["shadow_mode"])
                items.append(record)
            return items
        finally:
            conn.close()

    def get_signal_trace(self, trace_id):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM signal_traces
                WHERE trace_id = ?
                """,
                (trace_id,),
            ).fetchone()
            if row is None:
                return None

            record = dict(row)
            record["execution_eligible"] = bool(record["execution_eligible"])
            record["shadow_mode"] = bool(record.get("shadow_mode"))
            record["trace"] = json.loads(record.pop("trace_json"))
            return record
        finally:
            conn.close()

    def upsert_supervisor_runtime(self, runtime_key, state, last_summary=None):
        runtime_key = clean_string(runtime_key) or "default"
        state = state if isinstance(state, dict) else {}
        last_summary = last_summary if isinstance(last_summary, dict) else {}
        now = utc_now_iso()
        last_scan_at = clean_string(
            first_present(last_summary, ["scanned_at", "last_scan_at", "updated_at"])
        ) or clean_string(first_present(state, ["last_scan_at"]))

        with self.lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO supervisor_runtime (
                        runtime_key,
                        updated_at,
                        heartbeat_at,
                        last_scan_at,
                        last_summary_json,
                        state_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(runtime_key) DO UPDATE SET
                        updated_at = excluded.updated_at,
                        heartbeat_at = excluded.heartbeat_at,
                        last_scan_at = excluded.last_scan_at,
                        last_summary_json = excluded.last_summary_json,
                        state_json = excluded.state_json
                    """,
                    (
                        runtime_key,
                        now,
                        now,
                        last_scan_at,
                        json.dumps(last_summary, sort_keys=True),
                        json.dumps(state, sort_keys=True),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def list_supervisor_runtime(self):
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT *
                FROM supervisor_runtime
                ORDER BY updated_at DESC, runtime_key ASC
                """
            ).fetchall()
            items = []
            for row in rows:
                record = dict(row)
                record["last_summary"] = json.loads(record.pop("last_summary_json"))
                record["state"] = json.loads(record.pop("state_json"))
                items.append(record)
            return items
        finally:
            conn.close()

    def get_supervisor_runtime(self, runtime_key):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM supervisor_runtime
                WHERE runtime_key = ?
                """,
                (runtime_key,),
            ).fetchone()
            if row is None:
                return None

            record = dict(row)
            record["last_summary"] = json.loads(record.pop("last_summary_json"))
            record["state"] = json.loads(record.pop("state_json"))
            return record
        finally:
            conn.close()

    def delete_supervisor_runtime(self, runtime_key):
        conn = self._connect()
        try:
            conn.execute(
                """
                DELETE FROM supervisor_runtime
                WHERE runtime_key = ?
                """,
                (clean_string(runtime_key) or "default",),
            )
            conn.commit()
        finally:
            conn.close()

    def create_supervisor_event(
        self,
        runtime_key,
        event_type,
        severity,
        summary,
        event_payload,
        proposal_id=None,
        symbol=None,
    ):
        runtime_key = clean_string(runtime_key) or "default"
        event_type = clean_string(event_type) or "unknown"
        severity = clean_string(severity) or "info"
        summary = clean_string(summary) or "supervisor event"

        with self.lock:
            conn = self._connect()
            try:
                next_id = self._next_id(conn, "supervisor_events", "event_entry_id")
                event_id = f"SE-{next_id:05d}"
                conn.execute(
                    """
                    INSERT INTO supervisor_events (
                        event_id,
                        created_at,
                        runtime_key,
                        proposal_id,
                        symbol,
                        severity,
                        event_type,
                        summary,
                        event_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        utc_now_iso(),
                        runtime_key,
                        clean_string(proposal_id),
                        clean_string(symbol),
                        severity,
                        event_type,
                        summary,
                        json.dumps(event_payload if isinstance(event_payload, dict) else {}, sort_keys=True),
                    ),
                )
                conn.commit()
                return event_id
            finally:
                conn.close()

    def list_supervisor_events(
        self,
        limit=100,
        runtime_key=None,
        proposal_id=None,
        severity=None,
        event_type=None,
    ):
        conn = self._connect()
        try:
            query = [
                """
                SELECT event_id, created_at, runtime_key, proposal_id, symbol,
                       severity, event_type, summary
                FROM supervisor_events
                """
            ]
            params = []
            filters = []
            if runtime_key:
                filters.append("runtime_key = ?")
                params.append(runtime_key)
            if proposal_id:
                filters.append("proposal_id = ?")
                params.append(proposal_id)
            if severity:
                filters.append("severity = ?")
                params.append(severity)
            if event_type:
                filters.append("event_type = ?")
                params.append(event_type)
            if filters:
                query.append("WHERE " + " AND ".join(filters))
            query.append("ORDER BY event_entry_id DESC")
            query.append("LIMIT ?")
            params.append(limit)
            rows = conn.execute("\n".join(query), params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_supervisor_event(self, event_id):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM supervisor_events
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()
            if row is None:
                return None

            record = dict(row)
            record["event"] = json.loads(record.pop("event_json"))
            return record
        finally:
            conn.close()

    def upsert_private_stream_runtime(
        self,
        runtime_key,
        connection_status,
        subscriptions=None,
        state=None,
        connected_at=None,
        last_message_at=None,
    ):
        runtime_key = clean_string(runtime_key) or "default"
        connection_status = clean_string(connection_status) or "unknown"
        subscriptions = subscriptions if isinstance(subscriptions, list) else []
        state = state if isinstance(state, dict) else {}
        now = utc_now_iso()

        with self.lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO private_stream_runtime (
                        runtime_key,
                        updated_at,
                        heartbeat_at,
                        connection_status,
                        connected_at,
                        last_message_at,
                        subscriptions_json,
                        state_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(runtime_key) DO UPDATE SET
                        updated_at = excluded.updated_at,
                        heartbeat_at = excluded.heartbeat_at,
                        connection_status = excluded.connection_status,
                        connected_at = COALESCE(excluded.connected_at, private_stream_runtime.connected_at),
                        last_message_at = COALESCE(excluded.last_message_at, private_stream_runtime.last_message_at),
                        subscriptions_json = excluded.subscriptions_json,
                        state_json = excluded.state_json
                    """,
                    (
                        runtime_key,
                        now,
                        now,
                        connection_status,
                        clean_string(connected_at),
                        clean_string(last_message_at),
                        json.dumps(subscriptions, sort_keys=True),
                        json.dumps(state, sort_keys=True),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def list_private_stream_runtime(self):
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT *
                FROM private_stream_runtime
                ORDER BY updated_at DESC, runtime_key ASC
                """
            ).fetchall()
            items = []
            for row in rows:
                record = dict(row)
                record["subscriptions"] = json.loads(record.pop("subscriptions_json"))
                record["state"] = json.loads(record.pop("state_json"))
                items.append(record)
            return items
        finally:
            conn.close()

    def get_private_stream_runtime(self, runtime_key):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM private_stream_runtime
                WHERE runtime_key = ?
                """,
                (runtime_key,),
            ).fetchone()
            if row is None:
                return None
            record = dict(row)
            record["subscriptions"] = json.loads(record.pop("subscriptions_json"))
            record["state"] = json.loads(record.pop("state_json"))
            return record
        finally:
            conn.close()

    def delete_private_stream_runtime(self, runtime_key):
        conn = self._connect()
        try:
            conn.execute(
                """
                DELETE FROM private_stream_runtime
                WHERE runtime_key = ?
                """,
                (clean_string(runtime_key) or "default",),
            )
            conn.commit()
        finally:
            conn.close()

    def create_private_stream_event(
        self,
        runtime_key,
        event_type,
        severity,
        summary,
        event_payload,
        proposal_id=None,
        symbol=None,
    ):
        runtime_key = clean_string(runtime_key) or "default"
        event_type = clean_string(event_type) or "unknown"
        severity = clean_string(severity) or "info"
        summary = clean_string(summary) or "private stream event"

        with self.lock:
            conn = self._connect()
            try:
                next_id = self._next_id(conn, "private_stream_events", "event_entry_id")
                event_id = f"PE-{next_id:05d}"
                conn.execute(
                    """
                    INSERT INTO private_stream_events (
                        event_id,
                        created_at,
                        runtime_key,
                        proposal_id,
                        symbol,
                        severity,
                        event_type,
                        summary,
                        event_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        utc_now_iso(),
                        runtime_key,
                        clean_string(proposal_id),
                        clean_string(symbol),
                        severity,
                        event_type,
                        summary,
                        json.dumps(event_payload if isinstance(event_payload, dict) else {}, sort_keys=True),
                    ),
                )
                conn.commit()
                return event_id
            finally:
                conn.close()

    def list_private_stream_events(
        self,
        limit=100,
        runtime_key=None,
        proposal_id=None,
        severity=None,
        event_type=None,
    ):
        conn = self._connect()
        try:
            query = [
                """
                SELECT event_id, created_at, runtime_key, proposal_id, symbol,
                       severity, event_type, summary
                FROM private_stream_events
                """
            ]
            params = []
            filters = []
            if runtime_key:
                filters.append("runtime_key = ?")
                params.append(runtime_key)
            if proposal_id:
                filters.append("proposal_id = ?")
                params.append(proposal_id)
            if severity:
                filters.append("severity = ?")
                params.append(severity)
            if event_type:
                filters.append("event_type = ?")
                params.append(event_type)
            if filters:
                query.append("WHERE " + " AND ".join(filters))
            query.append("ORDER BY event_entry_id DESC")
            query.append("LIMIT ?")
            params.append(limit)
            rows = conn.execute("\n".join(query), params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_private_stream_event(self, event_id):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM private_stream_events
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()
            if row is None:
                return None
            record = dict(row)
            record["event"] = json.loads(record.pop("event_json"))
            return record
        finally:
            conn.close()

    def set_control_state(self, control_key, paused, reason=None, updated_by=None, metadata=None):
        control_key = normalize_control_key(control_key)
        paused_bool = bool(coerce_bool(paused)) if coerce_bool(paused) is not None else bool(paused)
        metadata = metadata if isinstance(metadata, dict) else {}
        reason = clean_string(reason)
        updated_by = clean_string(updated_by)
        now = utc_now_iso()

        with self.lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO control_state (
                        control_key,
                        updated_at,
                        paused,
                        reason,
                        updated_by,
                        metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(control_key) DO UPDATE SET
                        updated_at = excluded.updated_at,
                        paused = excluded.paused,
                        reason = excluded.reason,
                        updated_by = excluded.updated_by,
                        metadata_json = excluded.metadata_json
                    """,
                    (
                        control_key,
                        now,
                        1 if paused_bool else 0,
                        reason,
                        updated_by,
                        json.dumps(metadata, sort_keys=True),
                    ),
                )
                next_id = self._next_id(conn, "control_events", "event_entry_id")
                event_id = f"CE-{next_id:05d}"
                event_payload = {
                    "control_key": control_key,
                    "paused": paused_bool,
                    "reason": reason,
                    "updated_by": updated_by,
                    "metadata": metadata,
                }
                conn.execute(
                    """
                    INSERT INTO control_events (
                        event_id,
                        created_at,
                        control_key,
                        paused,
                        reason,
                        updated_by,
                        event_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        now,
                        control_key,
                        1 if paused_bool else 0,
                        reason,
                        updated_by,
                        json.dumps(event_payload, sort_keys=True),
                    ),
                )
                conn.commit()
                return event_id
            finally:
                conn.close()

    def list_control_state(self):
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT *
                FROM control_state
                ORDER BY control_key ASC
                """
            ).fetchall()
            items = []
            for row in rows:
                record = dict(row)
                record["paused"] = bool(record["paused"])
                record["metadata"] = json.loads(record.pop("metadata_json"))
                items.append(record)
            return items
        finally:
            conn.close()

    def get_control_state(self, control_key):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM control_state
                WHERE control_key = ?
                """,
                (normalize_control_key(control_key),),
            ).fetchone()
            if row is None:
                return None
            record = dict(row)
            record["paused"] = bool(record["paused"])
            record["metadata"] = json.loads(record.pop("metadata_json"))
            return record
        finally:
            conn.close()

    def list_control_events(self, limit=100, control_key=None):
        conn = self._connect()
        try:
            query = [
                """
                SELECT event_id, created_at, control_key, paused, reason, updated_by
                FROM control_events
                """
            ]
            params = []
            if control_key:
                query.append("WHERE control_key = ?")
                params.append(normalize_control_key(control_key))
            query.append("ORDER BY event_entry_id DESC")
            query.append("LIMIT ?")
            params.append(limit)
            rows = conn.execute("\n".join(query), params).fetchall()
            items = []
            for row in rows:
                record = dict(row)
                record["paused"] = bool(record["paused"])
                items.append(record)
            return items
        finally:
            conn.close()

    def get_control_event(self, event_id):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM control_events
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()
            if row is None:
                return None
            record = dict(row)
            record["paused"] = bool(record["paused"])
            record["event"] = json.loads(record.pop("event_json"))
            return record
        finally:
            conn.close()

    def upsert_operations_runtime(self, runtime_key, state, last_summary=None):
        runtime_key = clean_string(runtime_key) or "default"
        state = state if isinstance(state, dict) else {}
        last_summary = last_summary if isinstance(last_summary, dict) else {}
        now = utc_now_iso()
        last_scan_at = clean_string(
            first_present(last_summary, ["scanned_at", "last_scan_at", "updated_at"])
        ) or clean_string(first_present(state, ["last_scan_at"]))

        with self.lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO operations_runtime (
                        runtime_key,
                        updated_at,
                        heartbeat_at,
                        last_scan_at,
                        last_summary_json,
                        state_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(runtime_key) DO UPDATE SET
                        updated_at = excluded.updated_at,
                        heartbeat_at = excluded.heartbeat_at,
                        last_scan_at = excluded.last_scan_at,
                        last_summary_json = excluded.last_summary_json,
                        state_json = excluded.state_json
                    """,
                    (
                        runtime_key,
                        now,
                        now,
                        last_scan_at,
                        json.dumps(last_summary, sort_keys=True),
                        json.dumps(state, sort_keys=True),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def list_operations_runtime(self):
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT *
                FROM operations_runtime
                ORDER BY updated_at DESC, runtime_key ASC
                """
            ).fetchall()
            items = []
            for row in rows:
                record = dict(row)
                record["last_summary"] = json.loads(record.pop("last_summary_json"))
                record["state"] = json.loads(record.pop("state_json"))
                items.append(record)
            return items
        finally:
            conn.close()

    def get_operations_runtime(self, runtime_key):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM operations_runtime
                WHERE runtime_key = ?
                """,
                (runtime_key,),
            ).fetchone()
            if row is None:
                return None
            record = dict(row)
            record["last_summary"] = json.loads(record.pop("last_summary_json"))
            record["state"] = json.loads(record.pop("state_json"))
            return record
        finally:
            conn.close()

    def delete_operations_runtime(self, runtime_key):
        conn = self._connect()
        try:
            conn.execute(
                """
                DELETE FROM operations_runtime
                WHERE runtime_key = ?
                """,
                (clean_string(runtime_key) or "default",),
            )
            conn.commit()
        finally:
            conn.close()

    def create_operations_event(
        self,
        runtime_key,
        event_type,
        severity,
        summary,
        event_payload,
        component_key=None,
    ):
        runtime_key = clean_string(runtime_key) or "default"
        event_type = clean_string(event_type) or "unknown"
        severity = clean_string(severity) or "info"
        summary = clean_string(summary) or "operations event"

        with self.lock:
            conn = self._connect()
            try:
                next_id = self._next_id(conn, "operations_events", "event_entry_id")
                event_id = f"OE-{next_id:05d}"
                conn.execute(
                    """
                    INSERT INTO operations_events (
                        event_id,
                        created_at,
                        runtime_key,
                        component_key,
                        severity,
                        event_type,
                        summary,
                        event_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        utc_now_iso(),
                        runtime_key,
                        clean_string(component_key),
                        severity,
                        event_type,
                        summary,
                        json.dumps(event_payload if isinstance(event_payload, dict) else {}, sort_keys=True),
                    ),
                )
                conn.commit()
                return event_id
            finally:
                conn.close()

    def list_operations_events(
        self,
        limit=100,
        runtime_key=None,
        component_key=None,
        severity=None,
        event_type=None,
    ):
        conn = self._connect()
        try:
            query = [
                """
                SELECT event_id, created_at, runtime_key, component_key,
                       severity, event_type, summary
                FROM operations_events
                """
            ]
            params = []
            filters = []
            if runtime_key:
                filters.append("runtime_key = ?")
                params.append(runtime_key)
            if component_key:
                filters.append("component_key = ?")
                params.append(component_key)
            if severity:
                filters.append("severity = ?")
                params.append(severity)
            if event_type:
                filters.append("event_type = ?")
                params.append(event_type)
            if filters:
                query.append("WHERE " + " AND ".join(filters))
            query.append("ORDER BY event_entry_id DESC")
            query.append("LIMIT ?")
            params.append(limit)
            rows = conn.execute("\n".join(query), params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_operations_event(self, event_id):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM operations_events
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()
            if row is None:
                return None
            record = dict(row)
            record["event"] = json.loads(record.pop("event_json"))
            return record
        finally:
            conn.close()

    def upsert_auto_execution_runtime(self, runtime_key, state, last_summary=None):
        runtime_key = clean_string(runtime_key) or "default"
        state = state if isinstance(state, dict) else {}
        last_summary = last_summary if isinstance(last_summary, dict) else {}
        now = utc_now_iso()
        last_scan_at = clean_string(
            first_present(last_summary, ["scanned_at", "last_scan_at", "updated_at"])
        ) or clean_string(first_present(state, ["last_scan_at"]))

        with self.lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO auto_execution_runtime (
                        runtime_key,
                        updated_at,
                        heartbeat_at,
                        last_scan_at,
                        last_summary_json,
                        state_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(runtime_key) DO UPDATE SET
                        updated_at = excluded.updated_at,
                        heartbeat_at = excluded.heartbeat_at,
                        last_scan_at = excluded.last_scan_at,
                        last_summary_json = excluded.last_summary_json,
                        state_json = excluded.state_json
                    """,
                    (
                        runtime_key,
                        now,
                        now,
                        last_scan_at,
                        json.dumps(last_summary, sort_keys=True),
                        json.dumps(state, sort_keys=True),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def list_auto_execution_runtime(self):
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT *
                FROM auto_execution_runtime
                ORDER BY updated_at DESC, runtime_key ASC
                """
            ).fetchall()
            items = []
            for row in rows:
                record = dict(row)
                record["last_summary"] = json.loads(record.pop("last_summary_json"))
                record["state"] = json.loads(record.pop("state_json"))
                items.append(record)
            return items
        finally:
            conn.close()

    def get_auto_execution_runtime(self, runtime_key):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM auto_execution_runtime
                WHERE runtime_key = ?
                """,
                (runtime_key,),
            ).fetchone()
            if row is None:
                return None
            record = dict(row)
            record["last_summary"] = json.loads(record.pop("last_summary_json"))
            record["state"] = json.loads(record.pop("state_json"))
            return record
        finally:
            conn.close()

    def delete_auto_execution_runtime(self, runtime_key):
        conn = self._connect()
        try:
            conn.execute(
                """
                DELETE FROM auto_execution_runtime
                WHERE runtime_key = ?
                """,
                (clean_string(runtime_key) or "default",),
            )
            conn.commit()
        finally:
            conn.close()

    def create_auto_execution_event(
        self,
        runtime_key,
        event_type,
        severity,
        summary,
        event_payload,
        instrument=None,
        proposal_id=None,
    ):
        runtime_key = clean_string(runtime_key) or "default"
        event_type = clean_string(event_type) or "unknown"
        severity = clean_string(severity) or "info"
        summary = clean_string(summary) or "auto execution event"
        instrument = normalize_instrument(instrument)

        with self.lock:
            conn = self._connect()
            try:
                next_id = self._next_id(conn, "auto_execution_events", "event_entry_id")
                event_id = f"AE-{next_id:05d}"
                conn.execute(
                    """
                    INSERT INTO auto_execution_events (
                        event_id,
                        created_at,
                        runtime_key,
                        instrument,
                        proposal_id,
                        severity,
                        event_type,
                        summary,
                        event_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        utc_now_iso(),
                        runtime_key,
                        instrument or None,
                        clean_string(proposal_id),
                        severity,
                        event_type,
                        summary,
                        json.dumps(event_payload if isinstance(event_payload, dict) else {}, sort_keys=True),
                    ),
                )
                conn.commit()
                return event_id
            finally:
                conn.close()

    def list_auto_execution_events(
        self,
        limit=100,
        runtime_key=None,
        instrument=None,
        proposal_id=None,
        severity=None,
        event_type=None,
    ):
        conn = self._connect()
        try:
            query = [
                """
                SELECT event_id, created_at, runtime_key, instrument, proposal_id,
                       severity, event_type, summary
                FROM auto_execution_events
                """
            ]
            params = []
            filters = []
            if runtime_key:
                filters.append("runtime_key = ?")
                params.append(runtime_key)
            if instrument:
                filters.append("instrument = ?")
                params.append(normalize_instrument(instrument))
            if proposal_id:
                filters.append("proposal_id = ?")
                params.append(proposal_id)
            if severity:
                filters.append("severity = ?")
                params.append(severity)
            if event_type:
                filters.append("event_type = ?")
                params.append(event_type)
            if filters:
                query.append("WHERE " + " AND ".join(filters))
            query.append("ORDER BY event_entry_id DESC")
            query.append("LIMIT ?")
            params.append(limit)
            rows = conn.execute("\n".join(query), params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_auto_execution_event(self, event_id):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM auto_execution_events
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()
            if row is None:
                return None
            record = dict(row)
            record["event"] = json.loads(record.pop("event_json"))
            return record
        finally:
            conn.close()

    def upsert_trade_management_runtime(self, runtime_key, state, last_summary=None):
        runtime_key = clean_string(runtime_key) or "default"
        state = state if isinstance(state, dict) else {}
        last_summary = last_summary if isinstance(last_summary, dict) else {}
        now = utc_now_iso()
        last_scan_at = clean_string(
            first_present(last_summary, ["scanned_at", "last_scan_at", "updated_at"])
        ) or clean_string(first_present(state, ["last_scan_at"]))

        with self.lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO trade_management_runtime (
                        runtime_key,
                        updated_at,
                        heartbeat_at,
                        last_scan_at,
                        last_summary_json,
                        state_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(runtime_key) DO UPDATE SET
                        updated_at = excluded.updated_at,
                        heartbeat_at = excluded.heartbeat_at,
                        last_scan_at = excluded.last_scan_at,
                        last_summary_json = excluded.last_summary_json,
                        state_json = excluded.state_json
                    """,
                    (
                        runtime_key,
                        now,
                        now,
                        last_scan_at,
                        json.dumps(last_summary, sort_keys=True),
                        json.dumps(state, sort_keys=True),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def list_trade_management_runtime(self):
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT *
                FROM trade_management_runtime
                ORDER BY updated_at DESC, runtime_key ASC
                """
            ).fetchall()
            items = []
            for row in rows:
                record = dict(row)
                record["last_summary"] = json.loads(record.pop("last_summary_json"))
                record["state"] = json.loads(record.pop("state_json"))
                items.append(record)
            return items
        finally:
            conn.close()

    def get_trade_management_runtime(self, runtime_key):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM trade_management_runtime
                WHERE runtime_key = ?
                """,
                (runtime_key,),
            ).fetchone()
            if row is None:
                return None
            record = dict(row)
            record["last_summary"] = json.loads(record.pop("last_summary_json"))
            record["state"] = json.loads(record.pop("state_json"))
            return record
        finally:
            conn.close()

    def delete_trade_management_runtime(self, runtime_key):
        conn = self._connect()
        try:
            conn.execute(
                """
                DELETE FROM trade_management_runtime
                WHERE runtime_key = ?
                """,
                (clean_string(runtime_key) or "default",),
            )
            conn.commit()
        finally:
            conn.close()

    def create_trade_management_event(
        self,
        runtime_key,
        event_type,
        severity,
        summary,
        event_payload,
        proposal_id=None,
        symbol=None,
    ):
        runtime_key = clean_string(runtime_key) or "default"
        event_type = clean_string(event_type) or "unknown"
        severity = clean_string(severity) or "info"
        summary = clean_string(summary) or "trade management event"
        symbol = normalize_instrument(symbol)

        with self.lock:
            conn = self._connect()
            try:
                next_id = self._next_id(conn, "trade_management_events", "event_entry_id")
                event_id = f"TM-{next_id:05d}"
                conn.execute(
                    """
                    INSERT INTO trade_management_events (
                        event_id,
                        created_at,
                        runtime_key,
                        proposal_id,
                        symbol,
                        severity,
                        event_type,
                        summary,
                        event_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        utc_now_iso(),
                        runtime_key,
                        clean_string(proposal_id),
                        symbol or None,
                        severity,
                        event_type,
                        summary,
                        json.dumps(event_payload if isinstance(event_payload, dict) else {}, sort_keys=True),
                    ),
                )
                conn.commit()
                return event_id
            finally:
                conn.close()

    def list_trade_management_events(
        self,
        limit=100,
        runtime_key=None,
        proposal_id=None,
        symbol=None,
        severity=None,
        event_type=None,
    ):
        conn = self._connect()
        try:
            query = [
                """
                SELECT event_id, created_at, runtime_key, proposal_id, symbol,
                       severity, event_type, summary
                FROM trade_management_events
                """
            ]
            params = []
            filters = []
            if runtime_key:
                filters.append("runtime_key = ?")
                params.append(runtime_key)
            if proposal_id:
                filters.append("proposal_id = ?")
                params.append(proposal_id)
            if symbol:
                filters.append("symbol = ?")
                params.append(normalize_instrument(symbol))
            if severity:
                filters.append("severity = ?")
                params.append(severity)
            if event_type:
                filters.append("event_type = ?")
                params.append(event_type)
            if filters:
                query.append("WHERE " + " AND ".join(filters))
            query.append("ORDER BY event_entry_id DESC")
            query.append("LIMIT ?")
            params.append(limit)
            rows = conn.execute("\n".join(query), params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_trade_management_event(self, event_id):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM trade_management_events
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()
            if row is None:
                return None
            record = dict(row)
            record["event"] = json.loads(record.pop("event_json"))
            return record
        finally:
            conn.close()

    def upsert_concept_runtime(self, runtime_key, state, last_summary=None):
        runtime_key = clean_string(runtime_key) or "default"
        state = state if isinstance(state, dict) else {}
        last_summary = last_summary if isinstance(last_summary, dict) else {}
        now = utc_now_iso()
        last_scan_at = clean_string(
            first_present(last_summary, ["scanned_at", "last_scan_at", "updated_at"])
        ) or clean_string(first_present(state, ["last_scan_at"]))

        with self.lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO concept_runtime (
                        runtime_key,
                        updated_at,
                        heartbeat_at,
                        last_scan_at,
                        last_summary_json,
                        state_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(runtime_key) DO UPDATE SET
                        updated_at = excluded.updated_at,
                        heartbeat_at = excluded.heartbeat_at,
                        last_scan_at = excluded.last_scan_at,
                        last_summary_json = excluded.last_summary_json,
                        state_json = excluded.state_json
                    """,
                    (
                        runtime_key,
                        now,
                        now,
                        last_scan_at,
                        json.dumps(last_summary, sort_keys=True),
                        json.dumps(state, sort_keys=True),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def list_concept_runtime(self):
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT *
                FROM concept_runtime
                ORDER BY updated_at DESC, runtime_key ASC
                """
            ).fetchall()
            items = []
            for row in rows:
                record = dict(row)
                record["last_summary"] = json.loads(record.pop("last_summary_json"))
                record["state"] = json.loads(record.pop("state_json"))
                items.append(record)
            return items
        finally:
            conn.close()

    def get_concept_runtime(self, runtime_key):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM concept_runtime
                WHERE runtime_key = ?
                """,
                (runtime_key,),
            ).fetchone()
            if row is None:
                return None
            record = dict(row)
            record["last_summary"] = json.loads(record.pop("last_summary_json"))
            record["state"] = json.loads(record.pop("state_json"))
            return record
        finally:
            conn.close()

    def create_concept_event(
        self,
        runtime_key,
        event_type,
        severity,
        summary,
        event_payload,
        concept_id=None,
    ):
        runtime_key = clean_string(runtime_key) or "default"
        event_type = clean_string(event_type) or "unknown"
        severity = clean_string(severity) or "info"
        summary = clean_string(summary) or "concept event"

        with self.lock:
            conn = self._connect()
            try:
                next_id = self._next_id(conn, "concept_events", "event_entry_id")
                event_id = f"CL-{next_id:05d}"
                conn.execute(
                    """
                    INSERT INTO concept_events (
                        event_id,
                        created_at,
                        runtime_key,
                        concept_id,
                        severity,
                        event_type,
                        summary,
                        event_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        utc_now_iso(),
                        runtime_key,
                        clean_string(concept_id),
                        severity,
                        event_type,
                        summary,
                        json.dumps(event_payload if isinstance(event_payload, dict) else {}, sort_keys=True),
                    ),
                )
                conn.commit()
                return event_id
            finally:
                conn.close()

    def list_concept_events(
        self,
        limit=100,
        runtime_key=None,
        concept_id=None,
        severity=None,
        event_type=None,
    ):
        conn = self._connect()
        try:
            query = [
                """
                SELECT event_id, created_at, runtime_key, concept_id,
                       severity, event_type, summary
                FROM concept_events
                """
            ]
            params = []
            filters = []
            if runtime_key:
                filters.append("runtime_key = ?")
                params.append(runtime_key)
            if concept_id:
                filters.append("concept_id = ?")
                params.append(clean_string(concept_id))
            if severity:
                filters.append("severity = ?")
                params.append(severity)
            if event_type:
                filters.append("event_type = ?")
                params.append(event_type)
            if filters:
                query.append("WHERE " + " AND ".join(filters))
            query.append("ORDER BY event_entry_id DESC")
            query.append("LIMIT ?")
            params.append(limit)
            rows = conn.execute("\n".join(query), params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_concept_event(self, event_id):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM concept_events
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()
            if row is None:
                return None
            record = dict(row)
            record["event"] = json.loads(record.pop("event_json"))
            return record
        finally:
            conn.close()

    def create_concept_review(self, review_payload):
        payload = review_payload if isinstance(review_payload, dict) else {}
        concept_id = clean_string(payload.get("concept_id")) or "concept-1"
        source = clean_string(payload.get("source")) or "manual"
        author = clean_string(payload.get("author"))
        review_kind = clean_string(payload.get("review_kind")) or "analysis"
        overall = clean_string(payload.get("overall"))
        recommendation = clean_string(payload.get("recommendation"))
        primary_blocker = clean_string(payload.get("primary_blocker"))
        summary = clean_string(payload.get("summary")) or "concept review artifact"

        with self.lock:
            conn = self._connect()
            try:
                next_id = self._next_id(conn, "concept_reviews", "review_entry_id")
                review_id = f"CR-{next_id:05d}"
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
                        utc_now_iso(),
                        concept_id,
                        source,
                        author,
                        review_kind,
                        overall,
                        recommendation,
                        primary_blocker,
                        summary,
                        json.dumps(payload, sort_keys=True),
                    ),
                )
                conn.commit()
                return review_id
            finally:
                conn.close()

    def list_concept_reviews(
        self,
        limit=100,
        concept_id=None,
        source=None,
        review_kind=None,
    ):
        conn = self._connect()
        try:
            query = [
                """
                SELECT review_id, created_at, concept_id, source, author, review_kind,
                       overall, recommendation, primary_blocker, summary
                FROM concept_reviews
                """
            ]
            params = []
            filters = []
            if concept_id:
                filters.append("concept_id = ?")
                params.append(clean_string(concept_id))
            if source:
                filters.append("source = ?")
                params.append(clean_string(source))
            if review_kind:
                filters.append("review_kind = ?")
                params.append(clean_string(review_kind))
            if filters:
                query.append("WHERE " + " AND ".join(filters))
            query.append("ORDER BY review_entry_id DESC")
            query.append("LIMIT ?")
            params.append(limit)
            rows = conn.execute("\n".join(query), params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_concept_review(self, review_id):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM concept_reviews
                WHERE review_id = ?
                """,
                (review_id,),
            ).fetchone()
            if row is None:
                return None
            record = dict(row)
            record["review"] = json.loads(record.pop("review_json"))
            return record
        finally:
            conn.close()

    def create_concept_revision(self, revision_payload):
        payload = revision_payload if isinstance(revision_payload, dict) else {}
        concept_id = clean_string(payload.get("concept_id")) or "concept-1"
        source = clean_string(payload.get("source")) or "manual"
        author = clean_string(payload.get("author"))
        focus = clean_string(payload.get("focus"))
        status = clean_string(payload.get("status")) or "planned"
        summary = clean_string(payload.get("summary")) or "concept revision"

        with self.lock:
            conn = self._connect()
            try:
                next_id = self._next_id(conn, "concept_revisions", "revision_entry_id")
                revision_id = f"RV-{next_id:05d}"
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
                        utc_now_iso(),
                        concept_id,
                        source,
                        author,
                        focus,
                        status,
                        summary,
                        json.dumps(payload, sort_keys=True),
                    ),
                )
                conn.commit()
                return revision_id
            finally:
                conn.close()

    def list_concept_revisions(
        self,
        limit=100,
        concept_id=None,
        source=None,
        focus=None,
    ):
        conn = self._connect()
        try:
            query = [
                """
                SELECT revision_id, created_at, concept_id, source, author, focus, status, summary
                FROM concept_revisions
                """
            ]
            params = []
            filters = []
            if concept_id:
                filters.append("concept_id = ?")
                params.append(clean_string(concept_id))
            if source:
                filters.append("source = ?")
                params.append(clean_string(source))
            if focus:
                filters.append("focus = ?")
                params.append(clean_string(focus))
            if filters:
                query.append("WHERE " + " AND ".join(filters))
            query.append("ORDER BY revision_entry_id DESC")
            query.append("LIMIT ?")
            params.append(limit)
            rows = conn.execute("\n".join(query), params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_concept_revision(self, revision_id):
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM concept_revisions
                WHERE revision_id = ?
                """,
                (revision_id,),
            ).fetchone()
            if row is None:
                return None
            record = dict(row)
            record["revision"] = json.loads(record.pop("revision_json"))
            return record
        finally:
            conn.close()

    def get_latest_concept_revision_for_review(self, review_id):
        target_review_id = clean_string(review_id)
        if not target_review_id:
            return None
        conn = self._connect()
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
                revision = json.loads(record.pop("revision_json"))
                if clean_string(revision.get("review_id")) != target_review_id:
                    continue
                record["revision"] = revision
                return record
            return None
        finally:
            conn.close()

    def update_concept_revision(self, revision_id, revision_payload):
        payload = revision_payload if isinstance(revision_payload, dict) else {}
        summary = clean_string(payload.get("summary")) or "concept revision"
        status = clean_string(payload.get("status")) or "planned"
        focus = clean_string(payload.get("focus"))

        with self.lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    """
                    UPDATE concept_revisions
                    SET focus = ?, status = ?, summary = ?, revision_json = ?
                    WHERE revision_id = ?
                    """,
                    (
                        focus,
                        status,
                        summary,
                        json.dumps(payload, sort_keys=True),
                        revision_id,
                    ),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()
