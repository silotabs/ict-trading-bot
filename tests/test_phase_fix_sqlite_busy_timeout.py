from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import trading_store


class PhaseFixSqliteBusyTimeoutTests(unittest.TestCase):
    def test_store_connect_uses_busy_timeout_and_wal_pragmas(self):
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "paper-trading.db"
            fake_conn = MagicMock()

            with patch.object(trading_store.PaperTradeStore, "_init_db", return_value=None):
                store = trading_store.PaperTradeStore(db_path)

            with patch.object(trading_store.sqlite3, "connect", return_value=fake_conn) as connect_mock:
                conn = store._connect()

        self.assertIs(conn, fake_conn)
        connect_mock.assert_called_once_with(
            db_path,
            timeout=trading_store.SQLITE_BUSY_TIMEOUT_SECONDS,
        )
        fake_conn.execute.assert_any_call(
            f"PRAGMA busy_timeout = {trading_store.SQLITE_BUSY_TIMEOUT_MS}"
        )
        fake_conn.execute.assert_any_call("PRAGMA journal_mode=WAL")
        fake_conn.execute.assert_any_call("PRAGMA synchronous=NORMAL")


if __name__ == "__main__":
    unittest.main()
