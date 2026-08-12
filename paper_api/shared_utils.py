from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------

SQLITE_BUSY_TIMEOUT_SECONDS = 30.0
SQLITE_BUSY_TIMEOUT_MS = int(SQLITE_BUSY_TIMEOUT_SECONDS * 1000)


def open_sqlite_connection(path, *, apply_wal_pragmas=True, read_only=False):
    """Open a SQLite connection with the project's standard safety pragmas.

    This is the single canonical connector used across the codebase. Every
    caller gets the same busy timeout and ``row_factory = Row``; writers (the
    default) additionally get WAL + synchronous=NORMAL. ``read_only`` opens the
    database in immutable query mode without the write-oriented pragmas.
    """
    target = Path(path).expanduser()
    if read_only:
        uri = f"file:{target}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=SQLITE_BUSY_TIMEOUT_SECONDS)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(target), timeout=SQLITE_BUSY_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    if apply_wal_pragmas and not read_only:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    return conn


# ---------------------------------------------------------------------------
# JSON config loading
# ---------------------------------------------------------------------------

def load_json_document(path, *, label):
    """Load a JSON object from ``path`` and return an envelope dict.

    The envelope always carries ``ok`` (bool), ``path`` (str), ``errors``
    (list[str]) and the parsed object. The parsed object is exposed under both
    ``"data"`` (legacy ``stackctl`` key) and ``"document"`` (legacy
    ``runtime_config`` key) so that all existing call sites keep working.
    """
    target = Path(path)
    envelope = {"ok": False, "path": str(target), "errors": [], "data": None, "document": None}
    if not target.exists():
        envelope["errors"] = [f"{label} file not found: {target}"]
        return envelope
    try:
        raw = json.loads(target.read_text())
    except OSError as exc:
        envelope["errors"] = [f"failed to read {label}: {exc}"]
        return envelope
    except json.JSONDecodeError as exc:
        envelope["errors"] = [f"invalid JSON in {label}: {exc.msg}"]
        return envelope
    if not isinstance(raw, dict):
        envelope["errors"] = [f"{label} must be a JSON object"]
        return envelope
    envelope["ok"] = True
    envelope["data"] = raw
    envelope["document"] = raw
    return envelope


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------

def utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean_string(value):
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return str(value).strip() or None


def parse_iso_datetime(value):
    raw = clean_string(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def age_seconds_from_iso(value, now_dt=None, clamp_zero=True):
    """Return the age (in seconds) of an ISO timestamp.

    The single canonical implementation shared by ``server.py`` and
    ``stackctl.py``. ``now_dt`` defaults to the current UTC time; when
    ``clamp_zero`` is true (the default) the result never goes negative.
    """
    parsed = parse_iso_datetime(value)
    if parsed is None:
        return None
    reference = now_dt if isinstance(now_dt, datetime) else datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    delta = (reference.astimezone(timezone.utc) - parsed).total_seconds()
    if clamp_zero:
        return max(0.0, delta)
    return delta


def coerce_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in {"1", "true", "yes", "y", "on"}:
            return True
        if raw in {"0", "false", "no", "n", "off"}:
            return False
    return None
