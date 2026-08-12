from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from pathlib import Path

from shared_utils import open_sqlite_connection


APP_DIR_NAME = "trading"
DB_FILE_NAME = "paper-trading.db"
STACK_DIR_NAME = "stack"
FALLBACK_DB_PATH = Path("/tmp/trading-paper-trading.db")
FALLBACK_STATE_DIR = Path("/tmp/trading-paper-stack")
STACK_MANIFEST_NAME = "stack_state.json"


def preferred_data_dir():
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / APP_DIR_NAME

    return Path.home() / ".local" / "share" / APP_DIR_NAME


def _ensure_directory(path):
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe_path = path / ".trading-write-probe"
        with probe_path.open("w", encoding="utf-8") as handle:
            handle.write("ok")
        probe_path.unlink()
    except OSError:
        return False
    return True


def _db_contains_runtime_rows(path):
    if not path.exists():
        return False
    try:
        conn = open_sqlite_connection(path, read_only=True)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            for table_name in (
                "scan_history",
                "watchlist_state",
                "signal_traces",
                "operations_runtime",
                "private_stream_runtime",
            ):
                if table_name not in tables:
                    continue
                row_count = conn.execute(
                    f"SELECT COUNT(1) FROM {table_name}"
                ).fetchone()[0]
                if int(row_count or 0) > 0:
                    return True
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return False


def _data_dir_contains_managed_artifacts(path):
    if not path.exists():
        return False
    if _db_contains_runtime_rows(path / DB_FILE_NAME):
        return True
    if _state_dir_contains_runtime_state(path / STACK_DIR_NAME):
        return True
    return False


def _copy_db_with_sidecars(source, target):
    shutil.copy2(source, target)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{source}{suffix}")
        if sidecar.exists():
            shutil.copy2(sidecar, Path(f"{target}{suffix}"))


def _seed_from_legacy_fallback(target_db_path):
    source_db_path = FALLBACK_DB_PATH
    if target_db_path == source_db_path:
        return
    if not _db_contains_runtime_rows(source_db_path):
        return
    if target_db_path.exists() and _db_contains_runtime_rows(target_db_path):
        return
    try:
        _copy_db_with_sidecars(source_db_path, target_db_path)
    except OSError:
        return


def _state_dir_contains_runtime_state(path):
    if not path.exists():
        return False
    if (path / STACK_MANIFEST_NAME).exists():
        return True
    logs_dir = path / "logs"
    if logs_dir.exists():
        return any(logs_dir.iterdir())
    return False


def _copy_state_dir(source, target):
    target.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        if child.name.endswith(".lock"):
            continue
        destination = target / child.name
        if child.is_dir():
            shutil.copytree(child, destination, dirs_exist_ok=True)
            continue
        shutil.copy2(child, destination)


def _seed_state_dir_from_legacy_fallback(target_state_dir):
    source_state_dir = FALLBACK_STATE_DIR
    if target_state_dir == source_state_dir:
        return
    if not _state_dir_contains_runtime_state(source_state_dir):
        return
    if _state_dir_contains_runtime_state(target_state_dir):
        return
    try:
        _copy_state_dir(source_state_dir, target_state_dir)
    except OSError:
        return


def default_data_dir(*, prefer_existing=False):
    override = os.environ.get("TRADING_API_DATA_DIR")
    if override:
        return Path(override).expanduser()

    candidate = preferred_data_dir()
    if _ensure_directory(candidate):
        return candidate
    if prefer_existing and _data_dir_contains_managed_artifacts(candidate):
        return candidate
    return None


def default_db_path(*, prefer_existing=False):
    override = os.environ.get("TRADING_API_DB_PATH")
    if override:
        return Path(override).expanduser()
    data_dir = default_data_dir(prefer_existing=prefer_existing)
    if data_dir is not None:
        target_db_path = data_dir / DB_FILE_NAME
        _seed_from_legacy_fallback(target_db_path)
        return target_db_path
    return FALLBACK_DB_PATH


def default_stack_state_dir(*, prefer_existing=False):
    override = os.environ.get("TRADING_STACK_STATE_DIR")
    if override:
        return Path(override).expanduser()
    data_dir = default_data_dir(prefer_existing=prefer_existing)
    if data_dir is not None:
        target_state_dir = data_dir / STACK_DIR_NAME
        if _ensure_directory(target_state_dir):
            _seed_state_dir_from_legacy_fallback(target_state_dir)
            return target_state_dir
        if prefer_existing and _state_dir_contains_runtime_state(target_state_dir):
            return target_state_dir
    return FALLBACK_STATE_DIR
