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

from ict_engine.evaluation import decision_allows_execution_plan
from server import normalize_tradingview_payload


README_PATH = REPO_ROOT / "paper_api" / "README.md"
AUTO_POLICY_PATH = REPO_ROOT / "paper_api" / "config" / "auto_execution_policy.json"
TRADE_POLICY_PATH = REPO_ROOT / "paper_api" / "config" / "trade_management_policy.json"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def test_release_gate_requires_auto_execution_disabled_by_default():
    policy = read_json(AUTO_POLICY_PATH)

    assert policy["enabled"] is False
    assert policy["auto_submit"] is False


def test_release_gate_requires_trade_management_disabled_by_default():
    policy = read_json(TRADE_POLICY_PATH)

    assert policy["enabled"] is False


def test_release_gate_requires_verified_paper_trade_for_execution_plan():
    assert decision_allows_execution_plan("verified_paper_trade") is True
    assert decision_allows_execution_plan("scanner_candidate") is False
    assert decision_allows_execution_plan("journal_only") is False
    assert decision_allows_execution_plan("paper_trade") is False
    assert decision_allows_execution_plan("no_paper_trade") is False
    assert decision_allows_execution_plan("unclear") is False


def test_release_gate_requires_manual_context_only_for_chart_payloads():
    evaluation_payload = extract_readme_json_example("Example Evaluation Request")
    webhook_payload = extract_readme_json_example("Example TradingView Webhook Request")

    normalized_evaluation = normalize_tradingview_payload(evaluation_payload)
    normalized_webhook = normalize_tradingview_payload(webhook_payload)

    assert normalized_evaluation["visual_analysis_state"] == "manual_context_only"
    assert normalized_webhook["visual_analysis_state"] == "manual_context_only"


def test_release_gate_requires_docs_examples_match_current_schema():
    readme = read_text(README_PATH)

    assert '"liquidity_sweep"' not in readme
    assert '"liquidity_event"' in readme
    assert '"source_mode": "manual_assertion"' in readme
    assert '"source_mode": "scanner_verified"' in readme

    execution_plan_payload = extract_readme_json_example(
        "Build an execution plan from a scanner-verified setup that already meets the ICT house rules:"
    )
    normalized_execution = normalize_tradingview_payload(execution_plan_payload)

    assert normalized_execution["source_mode"] == "scanner_verified"
    assert normalized_execution["visual_analysis_state"] == "not_run"
    assert normalized_execution["checklist"]["liquidity_event"] is True


class TestPhase10ReleaseGate(unittest.TestCase):
    def test_release_gate_requires_auto_execution_disabled_by_default(self):
        test_release_gate_requires_auto_execution_disabled_by_default()

    def test_release_gate_requires_trade_management_disabled_by_default(self):
        test_release_gate_requires_trade_management_disabled_by_default()

    def test_release_gate_requires_verified_paper_trade_for_execution_plan(self):
        test_release_gate_requires_verified_paper_trade_for_execution_plan()

    def test_release_gate_requires_manual_context_only_for_chart_payloads(self):
        test_release_gate_requires_manual_context_only_for_chart_payloads()

    def test_release_gate_requires_docs_examples_match_current_schema(self):
        test_release_gate_requires_docs_examples_match_current_schema()
