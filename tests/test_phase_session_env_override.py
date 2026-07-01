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

import server


def test_parse_allowed_sessions_env_supports_demo_values():
    sessions = server.parse_allowed_sessions_env("outside,london,new_york,sydney,tokyo")

    assert sessions == ["outside", "london", "new_york", "sydney", "tokyo"]


def test_session_context_allows_outside_when_configured():
    original_sessions = list(server.RULES["allowed_sessions"])
    try:
        server.RULES["allowed_sessions"] = ["outside", "london", "new_york", "sydney", "tokyo"]
        session = server.session_context_at(datetime(2026, 4, 20, 0, 0, tzinfo=timezone.utc))

        assert session["active_session"] == "outside"
        assert session["session_valid"] is True
    finally:
        server.RULES["allowed_sessions"] = original_sessions


class TestPhaseSessionEnvOverride(unittest.TestCase):
    def test_parse_allowed_sessions_env_supports_demo_values(self):
        test_parse_allowed_sessions_env_supports_demo_values()

    def test_session_context_allows_outside_when_configured(self):
        test_session_context_allows_outside_when_configured()
