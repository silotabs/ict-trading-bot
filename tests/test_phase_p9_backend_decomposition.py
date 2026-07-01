from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import bybit_client
import runtime_api
import server as trading_server
import trading_store
import trading_utils


class PhaseP9BackendDecompositionTests(unittest.TestCase):
    def test_server_uses_extracted_store_and_bybit_client_modules(self):
        self.assertIs(trading_server.PaperTradeStore, trading_store.PaperTradeStore)
        self.assertIs(trading_server.bybit_public_get, bybit_client.bybit_public_get)
        self.assertIs(trading_server.fetch_bybit_wallet_balance, bybit_client.fetch_bybit_wallet_balance)
        self.assertIs(trading_server.fetch_bybit_api_key_information, bybit_client.fetch_bybit_api_key_information)

    def test_runtime_api_exposes_loop_facing_surface(self):
        self.assertIs(runtime_api.TradingAPIHandler, trading_server.TradingAPIHandler)
        self.assertIs(runtime_api.build_operations_status, trading_server.build_operations_status)
        self.assertIs(runtime_api.run_watchlist_scan, trading_server.run_watchlist_scan)
        self.assertIs(runtime_api.normalize_instrument, trading_utils.normalize_instrument)
        self.assertEqual(runtime_api.BYBIT_ENV, bybit_client.BYBIT_ENV)

    def test_loops_replays_and_stackctl_no_longer_import_server_directly(self):
        targets = [
            REPO_ROOT / 'paper_api' / 'scan_loop.py',
            REPO_ROOT / 'paper_api' / 'auto_execute_loop.py',
            REPO_ROOT / 'paper_api' / 'private_stream_loop.py',
            REPO_ROOT / 'paper_api' / 'trade_management_loop.py',
            REPO_ROOT / 'paper_api' / 'supervisor_loop.py',
            REPO_ROOT / 'paper_api' / 'ops_loop.py',
            REPO_ROOT / 'paper_api' / 'concept_lab_loop.py',
            REPO_ROOT / 'paper_api' / 'replay_scan.py',
            REPO_ROOT / 'paper_api' / 'replay_tune.py',
            REPO_ROOT / 'paper_api' / 'replay_compare.py',
            REPO_ROOT / 'paper_api' / 'stackctl.py',
        ]
        for path in targets:
            with self.subTest(path=path.name):
                text = path.read_text()
                self.assertNotIn('from server import', text)
                self.assertNotIn('import server', text)

    def test_server_has_core_route_dispatch_seams(self):
        self.assertTrue(hasattr(trading_server.TradingAPIHandler, '_dispatch_core_get_route'))
        self.assertTrue(hasattr(trading_server.TradingAPIHandler, '_dispatch_core_post_route'))
        server_lines = len((REPO_ROOT / 'paper_api' / 'server.py').read_text().splitlines())
        self.assertLess(server_lines, 8000)


if __name__ == '__main__':
    unittest.main()
