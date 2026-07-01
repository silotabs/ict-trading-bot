from __future__ import annotations

import os
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
import runtime_paths
import shared_utils
import stackctl
import concept_briefing
import concept_review_response


class PhaseP8StorageDurabilityTests(unittest.TestCase):
    def test_default_db_path_moves_out_of_tmp_on_macos(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("runtime_paths.sys.platform", "darwin"):
                with patch("runtime_paths.Path.home", return_value=Path("/Users/tester")):
                    with patch("runtime_paths._ensure_directory", return_value=True):
                        db_path = runtime_paths.default_db_path()

        self.assertEqual(
            db_path,
            Path("/Users/tester/Library/Application Support/trading/paper-trading.db"),
        )
        self.assertNotIn("/tmp/", str(db_path))

    def test_default_db_path_falls_back_to_tmp_when_app_data_dir_is_unavailable(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("runtime_paths.sys.platform", "darwin"):
                with patch("runtime_paths.Path.home", return_value=Path("/Users/tester")):
                    with patch("runtime_paths._ensure_directory", return_value=False):
                        db_path = runtime_paths.default_db_path()

        self.assertEqual(
            db_path,
            Path("/tmp/trading-paper-trading.db"),
        )

    def test_default_db_path_prefers_existing_durable_db_even_when_write_probe_fails(self):
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            durable_dir = home_dir / "Library" / "Application Support" / "trading"
            durable_dir.mkdir(parents=True, exist_ok=True)
            durable_db = durable_dir / "paper-trading.db"

            conn = sqlite3.connect(durable_db)
            try:
                conn.execute("CREATE TABLE scan_history (scan_id TEXT)")
                conn.execute("INSERT INTO scan_history (scan_id) VALUES ('SCAN-EXISTING')")
                conn.commit()
            finally:
                conn.close()

            with patch.dict(os.environ, {}, clear=True):
                with patch("runtime_paths.sys.platform", "darwin"):
                    with patch("runtime_paths.Path.home", return_value=home_dir):
                        with patch("runtime_paths._ensure_directory", return_value=False):
                            db_path = runtime_paths.default_db_path(prefer_existing=True)

        self.assertEqual(db_path, durable_db)

    def test_default_db_path_honors_explicit_override(self):
        with patch.dict(os.environ, {"TRADING_API_DB_PATH": "~/custom/paper.db"}, clear=True):
            db_path = runtime_paths.default_db_path()

        self.assertEqual(db_path, Path("~/custom/paper.db").expanduser())

    def test_default_db_path_seeds_durable_target_from_legacy_tmp_db(self):
        with TemporaryDirectory() as tmpdir:
            legacy_db = Path(tmpdir) / "legacy-paper.db"
            target_dir = Path(tmpdir) / "durable"
            target_db = target_dir / "paper-trading.db"
            target_dir.mkdir(parents=True, exist_ok=True)

            conn = sqlite3.connect(legacy_db)
            try:
                conn.execute("CREATE TABLE scan_history (scan_id TEXT)")
                conn.execute("INSERT INTO scan_history (scan_id) VALUES ('SCAN-1')")
                conn.commit()
            finally:
                conn.close()

            with patch.dict(os.environ, {}, clear=True):
                with patch.object(runtime_paths, "FALLBACK_DB_PATH", legacy_db):
                    with patch("runtime_paths.preferred_data_dir", return_value=target_dir):
                        with patch("runtime_paths._ensure_directory", return_value=True):
                            resolved = runtime_paths.default_db_path()

            self.assertEqual(resolved, target_db)
            self.assertTrue(target_db.exists())
            conn = sqlite3.connect(target_db)
            try:
                scan_id = conn.execute("SELECT scan_id FROM scan_history").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(scan_id, "SCAN-1")

    def test_default_stack_state_dir_moves_out_of_tmp_on_macos(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("runtime_paths.default_data_dir", return_value=Path("/Users/tester/Library/Application Support/trading")):
                with patch("runtime_paths._ensure_directory", return_value=True):
                    state_dir = runtime_paths.default_stack_state_dir()

        self.assertEqual(
            state_dir,
            Path("/Users/tester/Library/Application Support/trading/stack"),
        )
        self.assertNotIn("/tmp/", str(state_dir))

    def test_default_stack_state_dir_falls_back_to_tmp_when_app_data_dir_is_unavailable(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("runtime_paths.default_data_dir", return_value=None):
                state_dir = runtime_paths.default_stack_state_dir()

        self.assertEqual(state_dir, Path("/tmp/trading-paper-stack"))

    def test_default_stack_state_dir_honors_explicit_override(self):
        with patch.dict(os.environ, {"TRADING_STACK_STATE_DIR": "~/custom/stack-state"}, clear=True):
            state_dir = runtime_paths.default_stack_state_dir()

        self.assertEqual(state_dir, Path("~/custom/stack-state").expanduser())

    def test_default_stack_state_dir_prefers_existing_durable_state_even_when_write_probe_fails(self):
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            durable_dir = home_dir / "Library" / "Application Support" / "trading" / "stack"
            logs_dir = durable_dir / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (durable_dir / "stack_state.json").write_text('{"services": {"server": {"pid": 1}}}')
            (logs_dir / "server.log").write_text("ok\n")

            with patch.dict(os.environ, {}, clear=True):
                with patch("runtime_paths.sys.platform", "darwin"):
                    with patch("runtime_paths.Path.home", return_value=home_dir):
                        with patch("runtime_paths._ensure_directory", return_value=False):
                            state_dir = runtime_paths.default_stack_state_dir(prefer_existing=True)

        self.assertEqual(state_dir, durable_dir)

    def test_default_stack_state_dir_seeds_durable_target_from_legacy_tmp_state_dir(self):
        with TemporaryDirectory() as tmpdir:
            legacy_state_dir = Path(tmpdir) / "legacy-stack"
            (legacy_state_dir / "logs").mkdir(parents=True, exist_ok=True)
            (legacy_state_dir / "stack_state.json").write_text('{"services": {"server": {"pid": 1234}}}')
            (legacy_state_dir / "logs" / "server.log").write_text("server alive\n")

            target_root = Path(tmpdir) / "durable"
            target_root.mkdir(parents=True, exist_ok=True)

            with patch.dict(os.environ, {}, clear=True):
                with patch.object(runtime_paths, "FALLBACK_STATE_DIR", legacy_state_dir):
                    with patch("runtime_paths.default_data_dir", return_value=target_root):
                        with patch("runtime_paths._ensure_directory", return_value=True):
                            resolved = runtime_paths.default_stack_state_dir()

            self.assertEqual(resolved, target_root / "stack")
            self.assertTrue((resolved / "stack_state.json").exists())
            self.assertTrue((resolved / "logs" / "server.log").exists())

    def test_server_and_stackctl_use_shared_runtime_helpers(self):
        self.assertIs(trading_server.clean_string, shared_utils.clean_string)
        self.assertIs(trading_server.parse_iso_datetime, shared_utils.parse_iso_datetime)
        self.assertIs(trading_server.coerce_bool, shared_utils.coerce_bool)
        self.assertIs(trading_server.utc_now_iso, shared_utils.utc_now_iso)
        self.assertIs(stackctl.clean_text, shared_utils.clean_string)
        self.assertIs(stackctl.parse_iso_datetime, shared_utils.parse_iso_datetime)
        self.assertIs(stackctl.utc_now_iso, shared_utils.utc_now_iso)
        self.assertIs(concept_briefing.clean_text, shared_utils.clean_string)
        self.assertIs(concept_briefing.utc_now_iso, shared_utils.utc_now_iso)
        self.assertIs(concept_review_response.clean_text, shared_utils.clean_string)

    def test_paper_trade_store_enables_wal_mode(self):
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "phase-p8-wal.db"
            trading_server.PaperTradeStore(db_path)

            conn = sqlite3.connect(db_path)
            try:
                journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            finally:
                conn.close()

        self.assertEqual(str(journal_mode).lower(), "wal")

    def test_restart_service_refreshes_launch_context_db_path(self):
        with TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "services": {
                    "server": {
                        "service_name": "server",
                        "pid": None,
                        "command": ["python3", "server.py"],
                        "log_path": str(state_dir / "logs" / "server.log"),
                    }
                },
                "launch_context": {
                    "db_path": "/tmp/trading-paper-trading.db",
                },
            }
            stackctl.save_manifest(state_dir, manifest)

            args = type(
                "Args",
                (),
                {
                    "state_dir": str(state_dir),
                    "service_name": "server",
                    "force_after_seconds": 1,
                    "fresh_log": False,
                    "db_path": "/Users/tester/Library/Application Support/trading/paper-trading.db",
                    "host": "127.0.0.1",
                    "port": 8787,
                    "_env_info": {},
                    "scan_interval_seconds": 300,
                    "supervisor_interval_seconds": 30,
                    "ops_interval_seconds": 15,
                    "auto_execution_interval_seconds": 15,
                    "trade_management_interval_seconds": 15,
                    "concept_lab_interval_seconds": 60,
                    "disable_auto_log_candidates": False,
                    "with_private_stream": False,
                    "with_auto_execution": False,
                    "with_trade_management": False,
                    "with_concept_lab": False,
                },
            )()

            with patch.object(stackctl, "stop_service_processes", return_value={"manifest_pid": None, "manifest_status": "not_running", "drift_results": []}):
                with patch.object(stackctl, "start_service", return_value={"service_name": "server", "status": "started", "pid": 1234, "log_path": str(state_dir / "logs" / "server.log")}):
                    result = stackctl.restart_single_service(args)

            updated = stackctl.load_manifest(state_dir)
            self.assertTrue(result["ok"])
            self.assertEqual(
                updated.get("launch_context", {}).get("db_path"),
                "/Users/tester/Library/Application Support/trading/paper-trading.db",
            )

    def test_stop_stack_retires_optional_runtime_rows_for_stopped_services(self):
        with TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "state"
            db_path = Path(tmpdir) / "paper.db"
            state_dir.mkdir(parents=True, exist_ok=True)
            store = trading_server.PaperTradeStore(db_path)
            now_at = shared_utils.utc_now_iso()
            store.upsert_private_stream_runtime(
                "stream-main",
                "streaming",
                subscriptions=["order"],
                state={"last_message_at": now_at},
                connected_at=now_at,
                last_message_at=now_at,
            )
            manifest = {
                "services": {
                    "private_stream_loop": {
                        "service_name": "private_stream_loop",
                        "pid": None,
                        "command": ["python3", "private_stream_loop.py"],
                        "log_path": str(state_dir / "logs" / "private_stream_loop.log"),
                    }
                },
                "launch_context": {
                    "db_path": str(db_path),
                },
            }
            stackctl.save_manifest(state_dir, manifest)
            args = type(
                "Args",
                (),
                {
                    "state_dir": str(state_dir),
                    "force_after_seconds": 1,
                },
            )()

            with patch.object(
                stackctl,
                "stop_service_processes",
                return_value={"manifest_pid": None, "manifest_status": "not_running", "drift_results": []},
            ):
                result = stackctl.stop_stack(args)

            self.assertTrue(result["ok"])
            self.assertEqual(store.list_private_stream_runtime(), [])


if __name__ == "__main__":
    unittest.main()
