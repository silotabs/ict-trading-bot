from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from server import normalize_tradingview_payload


README_PATH = REPO_ROOT / "paper_api" / "README.md"
SKILL_ROOT = REPO_ROOT / "skills" / "ict-trading-analyst"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def skill_reference_paths():
    return [SKILL_ROOT / "SKILL.md"] + sorted((SKILL_ROOT / "references").glob("*.md"))


def extract_readme_json_example(label: str) -> dict:
    readme = read_text(README_PATH)
    pattern = re.compile(
        rf"{re.escape(label)}.*?```bash\s+.*?-d '(\{{.*?\}})'\s+```",
        re.S,
    )
    match = pattern.search(readme)
    if not match:
        raise AssertionError(f"could not find JSON example for label: {label}")
    return json.loads(match.group(1))


def test_readme_examples_use_liquidity_event_not_liquidity_sweep():
    readme = read_text(README_PATH)

    assert '"liquidity_event"' in readme
    assert '"liquidity_sweep"' not in readme


def test_readme_examples_use_source_mode_semantics():
    readme = read_text(README_PATH)

    assert '"source_mode": "manual_assertion"' in readme
    assert '"source_mode": "scanner_verified"' in readme
    assert "`journal_only`" in readme
    assert "`verified_paper_trade`" in readme


def test_docs_do_not_claim_verified_chart_reading():
    combined = "\n".join(read_text(path) for path in [README_PATH, *skill_reference_paths()])
    lowered = combined.lower()

    assert "the core engine does not implement verified chart-image reading" in lowered
    assert "manual_context_only" in combined
    assert "not_run" in combined
    assert "verified chart-image reading in the core engine" in lowered
    assert "can read screenshots automatically" not in lowered
    assert "automatically reads chart images" not in lowered


def test_docs_do_not_imply_live_auto_execution():
    combined = "\n".join(read_text(path) for path in [README_PATH, *skill_reference_paths()])
    lowered = combined.lower()

    assert "testnet-only" in lowered
    assert "disabled and `auto_submit = false`" in combined
    assert "do not place live trades" in lowered
    assert "live auto-execution" not in lowered
    assert "live auto execution" not in lowered


def test_skill_references_do_not_use_absolute_user_paths():
    for path in skill_reference_paths():
        text = read_text(path)
        assert "/Users/" not in text
        assert "/home/" not in text


def test_readme_payload_examples_round_trip_through_normalization():
    headings = [
        "Example Evaluation Request",
        "Example TradingView Webhook Request",
    ]
    for heading in headings:
        payload = extract_readme_json_example(heading)
        normalized = normalize_tradingview_payload(payload)

        assert normalized["checklist"]["liquidity_event"] is True
        assert "liquidity_sweep" not in normalized["checklist"]
        assert normalized["source_mode"] == "manual_assertion"

    execution_plan_payload = extract_readme_json_example(
        "Build an execution plan from a scanner-verified setup that already meets the ICT house rules:"
    )
    normalized_execution = normalize_tradingview_payload(execution_plan_payload)
    assert normalized_execution["source_mode"] == "scanner_verified"
    assert normalized_execution["visual_analysis_state"] == "not_run"
    assert normalized_execution["checklist"]["liquidity_event"] is True


class TestPhase9DocsContract(unittest.TestCase):
    def test_readme_examples_use_liquidity_event_not_liquidity_sweep(self):
        test_readme_examples_use_liquidity_event_not_liquidity_sweep()

    def test_readme_examples_use_source_mode_semantics(self):
        test_readme_examples_use_source_mode_semantics()

    def test_docs_do_not_claim_verified_chart_reading(self):
        test_docs_do_not_claim_verified_chart_reading()

    def test_docs_do_not_imply_live_auto_execution(self):
        test_docs_do_not_imply_live_auto_execution()

    def test_skill_references_do_not_use_absolute_user_paths(self):
        test_skill_references_do_not_use_absolute_user_paths()

    def test_readme_payload_examples_round_trip_through_normalization(self):
        test_readme_payload_examples_round_trip_through_normalization()
