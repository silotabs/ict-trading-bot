from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import ict_engine
import runtime_repositories
import server as trading_server


class PhaseP11SecurityInterfaceBoundaryTests(unittest.TestCase):
    def test_operator_auth_required_only_for_sensitive_post_routes(self):
        self.assertTrue(trading_server.operator_auth_required("POST", "/v1/control/kill-switch"))
        self.assertTrue(trading_server.operator_auth_required("POST", "/v1/execution/plan"))
        self.assertTrue(trading_server.operator_auth_required("POST", "/v1/order-proposals/BP-001/submit"))
        self.assertFalse(trading_server.operator_auth_required("GET", "/v1/control/state"))
        self.assertFalse(trading_server.operator_auth_required("POST", "/v1/webhooks/tradingview"))
        self.assertFalse(trading_server.operator_auth_required("POST", "/v1/scans/bybit/watchlist"))

    def test_operator_auth_validation_is_opt_in_and_accepts_bearer_or_header_token(self):
        disabled = trading_server.validate_operator_request_auth(
            {},
            method="POST",
            path="/v1/control/kill-switch",
            configured_token="",
            private_submit_enabled=False,
        )
        self.assertTrue(disabled["ok"])

        missing = trading_server.validate_operator_request_auth({}, method="POST", path="/v1/control/kill-switch", configured_token="secret")
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["status_code"], 401)

        bearer = trading_server.validate_operator_request_auth(
            {"Authorization": "Bearer secret"},
            method="POST",
            path="/v1/control/kill-switch",
            configured_token="secret",
        )
        self.assertTrue(bearer["ok"])

        header = trading_server.validate_operator_request_auth(
            {"X-Trading-Operator-Token": "secret"},
            method="POST",
            path="/v1/order-proposals/BP-001/cancel",
            configured_token="secret",
        )
        self.assertTrue(header["ok"])

    def test_operator_auth_fails_closed_when_private_submit_is_enabled(self):
        missing = trading_server.validate_operator_request_auth(
            {},
            method="POST",
            path="/v1/order-proposals/BP-001/submit",
            configured_token="",
            private_submit_enabled=True,
        )

        self.assertFalse(missing["ok"])
        self.assertTrue(missing["required"])
        self.assertEqual(missing["status_code"], 503)
        self.assertIn("private submission", missing["error"])

    def test_runtime_repositories_accept_injected_shadow_review_summarizer(self):
        with TemporaryDirectory() as tmpdir:
            store = trading_server.PaperTradeStore(Path(tmpdir) / "phase-p11-repositories.db")
            called = {}

            def fake_summarizer(records, *, cluster_limit=10, only_false_negative_candidates=False):
                called["records"] = records
                called["cluster_limit"] = cluster_limit
                called["only_false_negative_candidates"] = only_false_negative_candidates
                return {"trace_count": len(records), "cluster_limit": cluster_limit}

            repositories = runtime_repositories.build_runtime_repositories(
                store,
                shadow_review_summarizer=fake_summarizer,
            )
            trace_id = repositories.signal_traces.create(
                {
                    "symbol": "BTCUSDT",
                    "reference_timestamp": "2026-04-19T06:30:00+00:00",
                    "source_path": "shadow",
                    "source_mode": "scanner_verified",
                    "decision": "no_paper_trade",
                    "opportunity_state": "near_miss",
                    "execution_eligible": False,
                    "session_state": "london",
                    "narrative_state": "reversal",
                    "context_state": "watch",
                    "blocker_classification": {},
                    "blocker_reasons": ["required checklist field failed: displacement"],
                }
            )
            self.assertIsNotNone(repositories.signal_traces.get(trace_id))
            summary = repositories.signal_traces.summarize_shadow_review(cluster_limit=4)

        self.assertEqual(summary["trace_count"], 1)
        self.assertEqual(summary["cluster_limit"], 4)
        self.assertEqual(called["cluster_limit"], 4)

    def test_runtime_repositories_no_longer_hard_import_shadow_review(self):
        text = (REPO_ROOT / "paper_api" / "runtime_repositories.py").read_text()
        self.assertNotIn("from shadow_review import summarize_shadow_review", text)
        self.assertIn("class ShadowReviewSummarizer", text)

    def test_ict_engine_package_exports_public_surface(self):
        self.assertIn("summarize_context_state", ict_engine.__all__)
        self.assertIn("evaluate_execution_risk", ict_engine.__all__)
        self.assertIn("build_signal_trace", ict_engine.__all__)
        self.assertTrue(callable(ict_engine.summarize_context_state))
        self.assertTrue(callable(ict_engine.evaluate_execution_risk))
        self.assertTrue(callable(ict_engine.build_signal_trace))


if __name__ == "__main__":
    unittest.main()
