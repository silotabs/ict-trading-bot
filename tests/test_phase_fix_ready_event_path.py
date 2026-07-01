from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import server as trading_server
from runtime_health import build_readiness_payload


def iso_at(dt):
    return dt.replace(microsecond=0).isoformat()


def seed_ready_baseline(store, now_at):
    sample_scan = {"instrument": "BTCUSDT", "paper_trade_evaluation": {"decision": "no_paper_trade"}}
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


def seed_public_market_healthy(store, now_at, now_dt):
    store.upsert_operations_runtime(
        "public_market:default",
        state={
            "connection_status": "streaming",
            "event_path_state": "receiving_events",
            "last_public_event_at": now_at,
            "last_confirmed_close_processed_at": now_at,
            "last_confirmed_close_reference_at": now_at,
            "last_confirmed_close_reference_ms": 1760000000000,
            "last_fallback_poll_at": None,
            "fallback_interval_seconds": 300,
            "next_fallback_due_at": iso_at(now_dt + timedelta(minutes=5)),
            "fallback_active": False,
            "reconnect_count": 0,
            "last_error": None,
        },
        last_summary={"scanned_at": now_at},
    )


def readiness_for_store(
    store,
    active_service_names=None,
    *,
    private_submit_enabled=False,
    bybit_credentials_configured=False,
    operator_token="",
):
    api_key = "key" if bybit_credentials_configured else ""
    api_secret = "secret" if bybit_credentials_configured else ""
    with patch.object(trading_server, "BYBIT_ENABLE_PRIVATE_SUBMIT", private_submit_enabled), \
        patch.object(trading_server, "BYBIT_API_KEY", api_key), \
        patch.object(trading_server, "BYBIT_API_SECRET", api_secret), \
        patch.object(trading_server, "TRADING_API_OPERATOR_TOKEN", operator_token):
        return build_readiness_payload(
            trading_server.build_runtime_health_dependencies(
                store,
                active_service_names=active_service_names,
            )
        )


class PhaseFixReadyEventPathTests(unittest.TestCase):
    def test_readiness_is_healthy_when_public_event_stream_is_healthy(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-fix-ready-healthy.db")
            now_dt = datetime.now(timezone.utc).replace(microsecond=0)
            now_at = iso_at(now_dt)
            seed_ready_baseline(store, now_at)
            seed_public_market_healthy(store, now_at, now_dt)

            readiness = readiness_for_store(store)

        self.assertEqual(readiness["status"], "healthy_primary")
        public_component = next(
            item for item in readiness["operations"]["components"]
            if item["component_key"] == "public_market_event_path"
        )
        self.assertEqual(public_component["status"], "healthy_primary")
        self.assertEqual(public_component["details"]["event_path_state"], "receiving_events")
        self.assertEqual(public_component["details"]["connection_status"], "streaming")
        self.assertFalse(public_component["details"]["fallback_active"])

    def test_readiness_blocks_private_submit_without_operator_auth(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-fix-ready-submit-auth.db")
            now_dt = datetime.now(timezone.utc).replace(microsecond=0)
            now_at = iso_at(now_dt)
            seed_ready_baseline(store, now_at)
            seed_public_market_healthy(store, now_at, now_dt)

            readiness = readiness_for_store(
                store,
                private_submit_enabled=True,
                bybit_credentials_configured=True,
                operator_token="",
            )

        self.assertEqual(readiness["status"], "not_ready")
        submit_component = next(
            item for item in readiness["operations"]["components"]
            if item["component_key"] == "submission_safety"
        )
        self.assertEqual(submit_component["status"], "misconfigured")
        self.assertIn("operator auth token", submit_component["summary"])

    def test_primary_event_path_stays_healthy_across_5m_close_window(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-fix-ready-primary-window.db")
            now_dt = datetime.now(timezone.utc).replace(microsecond=0)
            recent_event_at = iso_at(now_dt - timedelta(seconds=240))
            recent_reference_at = iso_at(now_dt - timedelta(seconds=260))
            seed_ready_baseline(store, iso_at(now_dt))
            store.upsert_operations_runtime(
                "public_market:default",
                state={
                    "connection_status": "streaming",
                    "event_path_state": "receiving_events",
                    "last_public_event_at": recent_event_at,
                    "last_confirmed_close_processed_at": recent_event_at,
                    "last_confirmed_close_reference_at": recent_reference_at,
                    "last_confirmed_close_reference_ms": 1760000000000,
                    "fallback_active": False,
                    "fallback_reference_interval_seconds": 300,
                    "fallback_interval_seconds": 300,
                    "next_fallback_due_at": iso_at(now_dt + timedelta(seconds=60)),
                },
                last_summary={"scanned_at": iso_at(now_dt)},
            )

            readiness = readiness_for_store(store)

        self.assertEqual(readiness["status"], "healthy_primary")
        public_component = next(
            item for item in readiness["operations"]["components"]
            if item["component_key"] == "public_market_event_path"
        )
        self.assertEqual(public_component["status"], "healthy_primary")
        self.assertGreaterEqual(public_component["details"]["primary_fresh_window_seconds"], 330)

    def test_readiness_is_degraded_when_fallback_polling_is_active(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-fix-ready-degraded.db")
            now_dt = datetime.now(timezone.utc).replace(microsecond=0)
            now_at = iso_at(now_dt)
            stale_at = iso_at(now_dt - timedelta(minutes=5))
            fallback_at = iso_at(now_dt - timedelta(seconds=175))
            seed_ready_baseline(store, now_at)
            store.upsert_operations_runtime(
                "public_market:default",
                state={
                    "connection_status": "connected",
                    "event_path_state": "degraded_fallback",
                    "last_public_event_at": stale_at,
                    "last_confirmed_close_processed_at": stale_at,
                    "last_confirmed_close_reference_at": stale_at,
                    "last_confirmed_close_reference_ms": 1760000000000,
                    "last_fallback_poll_at": fallback_at,
                    "last_fallback_carry_at": fallback_at,
                    "last_fallback_carry_reference_at": stale_at,
                    "fallback_reference_interval_seconds": 300,
                    "fallback_interval_seconds": 300,
                    "next_fallback_due_at": iso_at(now_dt + timedelta(seconds=125)),
                    "fallback_active": True,
                    "reconnect_count": 2,
                    "last_error": "socket timeout",
                },
                last_summary={"scanned_at": now_at},
            )

            readiness = readiness_for_store(store)

        self.assertEqual(readiness["status"], "degraded_fallback")
        public_component = next(
            item for item in readiness["operations"]["components"]
            if item["component_key"] == "public_market_event_path"
        )
        self.assertEqual(public_component["status"], "degraded_fallback")
        self.assertTrue(public_component["details"]["fallback_active"])
        self.assertEqual(public_component["details"]["event_path_state"], "degraded_fallback")
        self.assertEqual(public_component["details"]["fallback_interval_seconds"], 300)
        self.assertEqual(public_component["details"]["fallback_reference_interval_seconds"], 300)
        self.assertEqual(public_component["details"]["last_fallback_carry_at"], fallback_at)
        self.assertEqual(public_component["details"]["last_error"], "socket timeout")

    def test_degraded_fallback_stays_ready_across_the_reference_bar_window(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-fix-ready-reference-window.db")
            now_dt = datetime.now(timezone.utc).replace(microsecond=0)
            now_at = iso_at(now_dt)
            fallback_poll_at = iso_at(now_dt - timedelta(seconds=5))
            fallback_carry_at = iso_at(now_dt - timedelta(minutes=2, seconds=56))
            fallback_reference_at = iso_at(now_dt - timedelta(seconds=4))
            seed_ready_baseline(store, now_at)
            store.upsert_operations_runtime(
                "public_market:default",
                state={
                    "connection_status": "connected",
                    "event_path_state": "degraded_fallback",
                    "last_public_event_at": None,
                    "last_confirmed_close_processed_at": fallback_carry_at,
                    "last_confirmed_close_reference_at": fallback_reference_at,
                    "last_confirmed_close_reference_ms": 1760000000000,
                    "last_fallback_poll_at": fallback_poll_at,
                    "last_fallback_carry_at": fallback_carry_at,
                    "last_fallback_carry_reference_at": fallback_reference_at,
                    "fallback_reference_interval_seconds": 300,
                    "fallback_interval_seconds": 60,
                    "next_fallback_due_at": iso_at(now_dt + timedelta(seconds=55)),
                    "fallback_active": True,
                    "reconnect_count": 0,
                    "last_error": None,
                },
                last_summary={"scanned_at": now_at},
            )

            readiness = readiness_for_store(store)

        self.assertEqual(readiness["status"], "degraded_fallback")
        public_component = next(
            item for item in readiness["operations"]["components"]
            if item["component_key"] == "public_market_event_path"
        )
        self.assertEqual(public_component["status"], "degraded_fallback")
        self.assertEqual(public_component["details"]["last_fallback_carry_reference_at"], fallback_reference_at)
        self.assertLessEqual(public_component["details"]["last_fallback_carry_reference_age_seconds"], 10)

    def test_fresh_fallback_carry_counts_even_when_stream_state_still_receiving(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-fix-ready-connected-fallback.db")
            now_dt = datetime.now(timezone.utc).replace(microsecond=0)
            now_at = iso_at(now_dt)
            stale_event_at = iso_at(now_dt - timedelta(minutes=15))
            fallback_poll_at = iso_at(now_dt - timedelta(seconds=25))
            fallback_carry_at = iso_at(now_dt - timedelta(seconds=20))
            fallback_reference_at = iso_at(now_dt - timedelta(minutes=3))
            seed_ready_baseline(store, now_at)
            store.upsert_operations_runtime(
                "public_market:default",
                state={
                    "connection_status": "streaming",
                    "event_path_state": "receiving_events",
                    "last_public_event_at": stale_event_at,
                    "last_confirmed_close_processed_at": fallback_carry_at,
                    "last_confirmed_close_reference_at": fallback_reference_at,
                    "last_confirmed_close_reference_ms": 1760000000000,
                    "last_fallback_poll_at": fallback_poll_at,
                    "last_fallback_carry_at": fallback_carry_at,
                    "last_fallback_carry_reference_at": fallback_reference_at,
                    "fallback_reference_interval_seconds": 300,
                    "fallback_interval_seconds": 300,
                    "next_fallback_due_at": iso_at(now_dt + timedelta(minutes=4)),
                    "fallback_active": False,
                    "reconnect_count": 0,
                    "last_error": None,
                },
                last_summary={"scanned_at": now_at},
            )

            readiness = readiness_for_store(store)

        self.assertEqual(readiness["status"], "degraded_fallback")
        public_component = next(
            item for item in readiness["operations"]["components"]
            if item["component_key"] == "public_market_event_path"
        )
        self.assertEqual(public_component["status"], "degraded_fallback")
        self.assertFalse(public_component["details"]["fallback_active"])
        self.assertEqual(public_component["details"]["event_path_state"], "receiving_events")
        self.assertEqual(public_component["details"]["last_fallback_carry_at"], fallback_carry_at)

    def test_fallback_carry_stays_ready_until_next_fallback_due_when_reference_window_ages(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-fix-ready-fallback-reference-aged.db")
            now_dt = datetime.now(timezone.utc).replace(microsecond=0)
            now_at = iso_at(now_dt)
            stale_event_at = iso_at(now_dt - timedelta(seconds=666))
            fallback_poll_at = iso_at(now_dt - timedelta(seconds=227))
            fallback_carry_at = iso_at(now_dt - timedelta(seconds=207))
            fallback_reference_at = iso_at(now_dt - timedelta(seconds=368))
            seed_ready_baseline(store, now_at)
            store.upsert_operations_runtime(
                "public_market:default",
                state={
                    "connection_status": "streaming",
                    "event_path_state": "receiving_events",
                    "last_public_event_at": stale_event_at,
                    "last_confirmed_close_processed_at": fallback_carry_at,
                    "last_confirmed_close_reference_at": fallback_reference_at,
                    "last_confirmed_close_reference_ms": 1760000000000,
                    "last_fallback_poll_at": fallback_poll_at,
                    "last_fallback_carry_at": fallback_carry_at,
                    "last_fallback_carry_reference_at": fallback_reference_at,
                    "fallback_reference_interval_seconds": 300,
                    "fallback_interval_seconds": 300,
                    "next_fallback_due_at": iso_at(now_dt + timedelta(seconds=72)),
                    "fallback_active": False,
                    "reconnect_count": 0,
                    "last_error": None,
                },
                last_summary={"scanned_at": now_at},
            )

            readiness = readiness_for_store(store)

        self.assertEqual(readiness["status"], "degraded_fallback")
        public_component = next(
            item for item in readiness["operations"]["components"]
            if item["component_key"] == "public_market_event_path"
        )
        self.assertEqual(public_component["status"], "degraded_fallback")
        self.assertGreaterEqual(
            public_component["details"]["fallback_reference_fresh_window_seconds"],
            600,
        )
        self.assertLess(
            public_component["details"]["last_fallback_carry_reference_age_seconds"],
            public_component["details"]["fallback_reference_fresh_window_seconds"],
        )

    def test_readiness_is_not_ready_when_primary_and_fallback_are_insufficient(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-fix-ready-not-ready.db")
            now_dt = datetime.now(timezone.utc).replace(microsecond=0)
            now_at = iso_at(now_dt)
            stale_at = iso_at(now_dt - timedelta(minutes=10))
            seed_ready_baseline(store, now_at)
            store.upsert_operations_runtime(
                "public_market:default",
                state={
                    "connection_status": "disconnected",
                    "event_path_state": "disconnected",
                    "last_public_event_at": stale_at,
                    "last_confirmed_close_processed_at": stale_at,
                    "last_confirmed_close_reference_at": stale_at,
                    "last_confirmed_close_reference_ms": 1760000000000,
                    "last_fallback_poll_at": stale_at,
                    "fallback_interval_seconds": 60,
                    "next_fallback_due_at": stale_at,
                    "fallback_active": False,
                    "reconnect_count": 3,
                    "last_error": "connection lost",
                },
                last_summary={"scanned_at": now_at},
            )

            readiness = readiness_for_store(store)

        self.assertEqual(readiness["status"], "not_ready")
        public_component = next(
            item for item in readiness["operations"]["components"]
            if item["component_key"] == "public_market_event_path"
        )
        self.assertEqual(public_component["status"], "not_ready")
        self.assertIn("public candle-close event path", public_component["summary"])

    def test_connected_no_flow_does_not_present_as_healthy_primary(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-fix-ready-connected-no-flow.db")
            now_dt = datetime.now(timezone.utc).replace(microsecond=0)
            now_at = iso_at(now_dt)
            seed_ready_baseline(store, now_at)
            store.upsert_operations_runtime(
                "public_market:default",
                state={
                    "connection_status": "connected",
                    "event_path_state": "connected_no_flow",
                    "last_public_event_at": None,
                    "last_confirmed_close_processed_at": None,
                    "last_confirmed_close_reference_at": None,
                    "last_confirmed_close_reference_ms": None,
                    "last_fallback_poll_at": None,
                    "fallback_interval_seconds": 60,
                    "next_fallback_due_at": iso_at(now_dt + timedelta(seconds=60)),
                    "fallback_active": False,
                    "reconnect_count": 0,
                    "last_error": None,
                },
                last_summary={"scanned_at": now_at},
            )

            readiness = readiness_for_store(store)

        self.assertEqual(readiness["status"], "not_ready")
        public_component = next(
            item for item in readiness["operations"]["components"]
            if item["component_key"] == "public_market_event_path"
        )
        self.assertEqual(public_component["status"], "not_ready")
        self.assertEqual(public_component["details"]["event_path_state"], "connected_no_flow")
        self.assertIn("no confirmed public close flow", public_component["summary"])

    def test_stale_private_stream_does_not_block_when_not_in_active_stack_profile(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-fix-ready-private-stream-optional.db")
            now_dt = datetime.now(timezone.utc).replace(microsecond=0)
            now_at = iso_at(now_dt)
            stale_private_at = iso_at(now_dt - timedelta(hours=2))
            fallback_poll_at = iso_at(now_dt - timedelta(seconds=15))
            fallback_carry_at = iso_at(now_dt - timedelta(seconds=10))
            fallback_reference_at = iso_at(now_dt - timedelta(minutes=1))
            seed_ready_baseline(store, now_at)
            store.upsert_private_stream_runtime(
                "stream-main",
                "streaming",
                subscriptions=["orders"],
                state={"last_message_at": stale_private_at},
                connected_at=stale_private_at,
                last_message_at=stale_private_at,
            )
            store.upsert_operations_runtime(
                "public_market:default",
                state={
                    "connection_status": "connected",
                    "event_path_state": "degraded_fallback",
                    "last_public_event_at": None,
                    "last_confirmed_close_processed_at": fallback_carry_at,
                    "last_confirmed_close_reference_at": fallback_reference_at,
                    "last_confirmed_close_reference_ms": 1760000000000,
                    "last_fallback_poll_at": fallback_poll_at,
                    "last_fallback_carry_at": fallback_carry_at,
                    "last_fallback_carry_reference_at": fallback_reference_at,
                    "fallback_reference_interval_seconds": 300,
                    "fallback_interval_seconds": 60,
                    "next_fallback_due_at": iso_at(now_dt + timedelta(seconds=45)),
                    "fallback_active": True,
                    "reconnect_count": 0,
                    "last_error": None,
                },
                last_summary={"scanned_at": now_at},
            )

            readiness = readiness_for_store(
                store,
                active_service_names={"server", "scan_loop", "supervisor_loop", "ops_loop", "concept_lab_loop"},
            )

        self.assertEqual(readiness["status"], "degraded_fallback")
        blocker_keys = {item["component_key"] for item in readiness["blockers"]}
        self.assertEqual(blocker_keys, {"public_market_event_path"})
        self.assertFalse(readiness["service_expectations"]["private_stream_expected"])

    def test_stale_private_stream_still_blocks_when_active_stack_expects_it(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-fix-ready-private-stream-required.db")
            now_dt = datetime.now(timezone.utc).replace(microsecond=0)
            now_at = iso_at(now_dt)
            stale_private_at = iso_at(now_dt - timedelta(hours=2))
            seed_ready_baseline(store, now_at)
            store.upsert_private_stream_runtime(
                "stream-main",
                "streaming",
                subscriptions=["orders"],
                state={"last_message_at": stale_private_at},
                connected_at=stale_private_at,
                last_message_at=stale_private_at,
            )
            store.upsert_operations_runtime(
                "public_market:default",
                state={
                    "connection_status": "connected",
                    "event_path_state": "degraded_fallback",
                    "last_public_event_at": None,
                    "last_confirmed_close_processed_at": now_at,
                    "last_confirmed_close_reference_at": now_at,
                    "last_confirmed_close_reference_ms": 1760000000000,
                    "last_fallback_poll_at": now_at,
                    "last_fallback_carry_at": now_at,
                    "last_fallback_carry_reference_at": now_at,
                    "fallback_reference_interval_seconds": 300,
                    "fallback_interval_seconds": 60,
                    "next_fallback_due_at": iso_at(now_dt + timedelta(seconds=60)),
                    "fallback_active": True,
                    "reconnect_count": 0,
                    "last_error": None,
                },
                last_summary={"scanned_at": now_at},
            )

            readiness = readiness_for_store(
                store,
                active_service_names={"server", "scan_loop", "supervisor_loop", "ops_loop", "private_stream_loop"},
            )

        self.assertEqual(readiness["status"], "not_ready")
        blocker_keys = {item["component_key"] for item in readiness["blockers"]}
        self.assertIn("private_stream:stream-main", blocker_keys)
        self.assertTrue(readiness["service_expectations"]["private_stream_expected"])

    def test_fallback_active_without_confirmed_carry_remains_not_ready(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-fix-ready-fallback-no-carry.db")
            now_dt = datetime.now(timezone.utc).replace(microsecond=0)
            now_at = iso_at(now_dt)
            seed_ready_baseline(store, now_at)
            store.upsert_operations_runtime(
                "public_market:default",
                state={
                    "connection_status": "unavailable",
                    "event_path_state": "degraded_fallback",
                    "last_public_event_at": None,
                    "last_confirmed_close_processed_at": None,
                    "last_confirmed_close_reference_at": None,
                    "last_confirmed_close_reference_ms": None,
                    "last_fallback_poll_at": now_at,
                    "last_fallback_carry_at": None,
                    "last_fallback_carry_reference_at": None,
                    "fallback_interval_seconds": 60,
                    "next_fallback_due_at": iso_at(now_dt + timedelta(seconds=60)),
                    "fallback_active": True,
                    "reconnect_count": 0,
                    "last_error": "socket timeout",
                },
                last_summary={"scanned_at": now_at},
            )

            readiness = readiness_for_store(store)

        self.assertEqual(readiness["status"], "not_ready")
        public_component = next(
            item for item in readiness["operations"]["components"]
            if item["component_key"] == "public_market_event_path"
        )
        self.assertEqual(public_component["status"], "not_ready")
        self.assertIn("has not yet carried a confirmed scan", public_component["summary"])

    def test_future_fallback_reference_is_flagged_in_readiness_details(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-fix-ready-future-reference.db")
            now_dt = datetime.now(timezone.utc).replace(microsecond=0)
            now_at = iso_at(now_dt)
            future_reference_at = iso_at(now_dt + timedelta(minutes=4))
            carry_at = iso_at(now_dt - timedelta(seconds=5))
            seed_ready_baseline(store, now_at)
            store.upsert_operations_runtime(
                "public_market:default",
                state={
                    "connection_status": "connected",
                    "event_path_state": "degraded_fallback",
                    "last_public_event_at": None,
                    "last_confirmed_close_processed_at": carry_at,
                    "last_confirmed_close_reference_at": future_reference_at,
                    "last_confirmed_close_reference_ms": 1760000000000,
                    "last_fallback_poll_at": now_at,
                    "last_fallback_carry_at": carry_at,
                    "last_fallback_carry_reference_at": future_reference_at,
                    "fallback_reference_interval_seconds": 300,
                    "fallback_interval_seconds": 60,
                    "next_fallback_due_at": iso_at(now_dt + timedelta(seconds=55)),
                    "fallback_active": True,
                    "reconnect_count": 0,
                    "last_error": None,
                },
                last_summary={"scanned_at": now_at},
            )

            readiness = readiness_for_store(store)

        public_component = next(
            item for item in readiness["operations"]["components"]
            if item["component_key"] == "public_market_event_path"
        )
        self.assertTrue(public_component["details"]["last_fallback_carry_reference_in_future"])
        self.assertTrue(public_component["details"]["last_confirmed_close_reference_in_future"])
        self.assertEqual(public_component["details"]["last_fallback_carry_reference_age_seconds"], 0.0)


if __name__ == "__main__":
    unittest.main()
