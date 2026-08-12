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
from shared_utils import SQLITE_BUSY_TIMEOUT_MS


class PhaseFixSqliteBusyTimeoutTests(unittest.TestCase):
    def test_store_connect_uses_busy_timeout_and_wal_pragmas(self):
        """A connection opened by the store must carry the canonical busy
        timeout and WAL durability pragmas, regardless of which helper performs
        the open. Validates behaviour on a real SQLite connection rather than
        coupling to the constant's location or the internal connect call."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "paper-trading.db"

            with patch.object(trading_store.PaperTradeStore, "_init_db", return_value=None):
                store = trading_store.PaperTradeStore(db_path)

            conn = store._connect()
            try:
                busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
                journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
                synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]
            finally:
                conn.close()

        self.assertEqual(busy_timeout, SQLITE_BUSY_TIMEOUT_MS)
        self.assertEqual(journal_mode.lower(), "wal")
        self.assertEqual(synchronous, 1)  # synchronous=NORMAL


if __name__ == "__main__":
    unittest.main()
