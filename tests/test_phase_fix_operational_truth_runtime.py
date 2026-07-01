from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import auto_execute_loop
import scan_loop


class PhaseFixOperationalTruthRuntimeTests(unittest.TestCase):
    def test_initialize_public_market_runtime_persists_blank_startup_state(self):
        class FakeStore:
            def __init__(self):
                self.calls = []

            def upsert_operations_runtime(self, runtime_key, state, last_summary=None):
                self.calls.append(
                    {
                        "runtime_key": runtime_key,
                        "state": state,
                        "last_summary": last_summary,
                    }
                )

        fake_store = FakeStore()
        original_store = scan_loop.TradingAPIHandler.store
        runtime = scan_loop.EventDrivenScanRuntime()
        try:
            scan_loop.TradingAPIHandler.store = fake_store
            scan_loop.initialize_public_market_runtime(runtime)
        finally:
            scan_loop.TradingAPIHandler.store = original_store

        self.assertEqual(len(fake_store.calls), 1)
        call = fake_store.calls[0]
        self.assertEqual(call["runtime_key"], "public_market:default")
        self.assertEqual(call["state"]["connection_status"], "disconnected")
        self.assertEqual(call["state"]["event_path_state"], "disconnected")
        self.assertFalse(call["state"]["fallback_active"])
        self.assertIsNone(call["state"]["last_public_event_at"])
        self.assertIsNone(call["state"]["last_confirmed_close_processed_at"])

    def test_degraded_event_path_uses_faster_fallback_interval(self):
        runtime = scan_loop.EventDrivenScanRuntime()
        runtime.note_stream_connected("2026-04-21T12:00:00+00:00")

        interval = scan_loop.determine_fallback_interval_seconds(
            True,
            runtime,
            interval_seconds=300,
            degraded_interval_seconds=60,
        )

        self.assertEqual(interval, 60)

    def test_receiving_event_flow_uses_normal_fallback_interval(self):
        runtime = scan_loop.EventDrivenScanRuntime()
        runtime.note_stream_connected("2026-04-21T12:00:00+00:00")
        runtime.note_public_events("2026-04-21T12:05:00+00:00")

        interval = scan_loop.determine_fallback_interval_seconds(
            True,
            runtime,
            interval_seconds=300,
            degraded_interval_seconds=60,
        )

        self.assertEqual(interval, 300)

    def test_fallback_mode_marks_runtime_as_degraded_between_polls(self):
        runtime = scan_loop.EventDrivenScanRuntime()
        runtime.note_stream_connected("2026-04-21T12:00:00+00:00")
        runtime.note_fallback_poll(
            "2026-04-21T12:01:00+00:00",
            active=True,
            interval_seconds=60,
        )

        self.assertEqual(runtime.event_path_state, "degraded_fallback")
        self.assertTrue(runtime.fallback_active)
        self.assertEqual(runtime.fallback_interval_seconds, 60)

    def test_event_error_backoff_grows_and_resets_after_connect(self):
        runtime = scan_loop.EventDrivenScanRuntime()
        runtime.note_event_error("socket timeout", observed_at="2026-04-21T12:00:00+00:00")
        self.assertEqual(runtime.consecutive_event_errors, 1)
        self.assertEqual(runtime.event_reconnect_backoff_seconds, 5)

        runtime.note_event_error("socket timeout", observed_at="2026-04-21T12:00:05+00:00")
        self.assertEqual(runtime.consecutive_event_errors, 2)
        self.assertEqual(runtime.event_reconnect_backoff_seconds, 10)

        runtime.note_stream_connected("2026-04-21T12:00:15+00:00")
        self.assertEqual(runtime.consecutive_event_errors, 0)
        self.assertIsNone(runtime.event_reconnect_backoff_seconds)
        self.assertIsNone(runtime.next_event_connect_due_at)

    def test_event_connect_is_deferred_until_backoff_due(self):
        runtime = scan_loop.EventDrivenScanRuntime()
        runtime.note_event_error("socket timeout", observed_at="2026-04-21T12:00:00+00:00")

        not_due_dt = datetime(2026, 4, 21, 12, 0, 3, tzinfo=timezone.utc)
        due_dt = datetime(2026, 4, 21, 12, 0, 5, tzinfo=timezone.utc)

        self.assertFalse(runtime.event_connect_due(now_dt=not_due_dt))
        self.assertTrue(runtime.event_connect_due(now_dt=due_dt))

    def test_auto_execution_runtime_summary_is_verified_only_by_default(self):
        summary = auto_execute_loop.build_runtime_summary(
            {
                "scanned_at": "2026-04-21T12:00:00+00:00",
                "policy_enabled": True,
                "scan_count": 2,
                "verified_paper_trade_candidates": 1,
                "submitted": 0,
                "blocked": 1,
                "errors": 0,
            }
        )

        self.assertEqual(summary["verified_paper_trade_candidates"], 1)
        self.assertEqual(summary["legacy_compat_paper_trade_candidates"], 0)
        self.assertNotIn("paper_trade_candidates", summary)


if __name__ == "__main__":
    unittest.main()
