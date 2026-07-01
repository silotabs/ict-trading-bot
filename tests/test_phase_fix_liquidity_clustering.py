from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from ict_engine.liquidity import _equal_level_candidates, _prices_within_relative_tolerance


def high(price, at):
    return {"type": "high", "price": float(price), "at": at}


def low(price, at):
    return {"type": "low", "price": float(price), "at": at}


def test_btc_highs_within_relative_tolerance_cluster():
    result = _equal_level_candidates(
        [
            high(64000.0, "2026-04-18T00:00:00+00:00"),
            high(64030.0, "2026-04-18T00:15:00+00:00"),
            high(64040.0, "2026-04-18T00:30:00+00:00"),
        ],
        "high",
        0.0008,
    )

    assert len(result) == 1
    assert result[0]["count"] == 3


def test_btc_highs_outside_relative_tolerance_do_not_cluster():
    result = _equal_level_candidates(
        [
            high(64000.0, "2026-04-18T00:00:00+00:00"),
            high(64120.0, "2026-04-18T00:15:00+00:00"),
        ],
        "high",
        0.0008,
    )

    assert result == []


def test_eth_lows_within_relative_tolerance_cluster():
    result = _equal_level_candidates(
        [
            low(3120.0, "2026-04-18T00:00:00+00:00"),
            low(3122.0, "2026-04-18T00:15:00+00:00"),
            low(3122.3, "2026-04-18T00:30:00+00:00"),
        ],
        "low",
        0.0008,
    )

    assert len(result) == 1
    assert result[0]["count"] == 3


def test_relative_clustering_behaves_sensibly_across_price_regimes():
    btc_result = _equal_level_candidates(
        [
            high(90000.0, "2026-04-18T00:00:00+00:00"),
            high(90060.0, "2026-04-18T00:15:00+00:00"),
        ],
        "high",
        0.0008,
    )
    eth_result = _equal_level_candidates(
        [
            high(1800.0, "2026-04-18T00:00:00+00:00"),
            high(1801.2, "2026-04-18T00:15:00+00:00"),
        ],
        "high",
        0.0008,
    )

    assert len(btc_result) == 1
    assert btc_result[0]["count"] == 2
    assert len(eth_result) == 1
    assert eth_result[0]["count"] == 2


def test_pairwise_relative_formula_uses_larger_price_denominator():
    assert _prices_within_relative_tolerance(100.0, 100.08, 0.0008) is True
    assert _prices_within_relative_tolerance(100.0, 100.081, 0.0008) is False


def test_group_clustering_does_not_chain_distant_levels_through_average():
    result = _equal_level_candidates(
        [
            high(100000.0, "2026-04-18T00:00:00+00:00"),
            high(100079.0, "2026-04-18T00:15:00+00:00"),
            high(100159.0, "2026-04-18T00:30:00+00:00"),
        ],
        "high",
        0.0008,
    )

    assert len(result) == 1
    assert result[0]["count"] == 2
    member_prices = [item["price"] for item in result[0]["members"]]
    assert 100000.0 in member_prices
    assert 100079.0 in member_prices
    assert 100159.0 not in member_prices


class TestPhaseFixLiquidityClustering(unittest.TestCase):
    def test_btc_highs_within_relative_tolerance_cluster(self):
        test_btc_highs_within_relative_tolerance_cluster()

    def test_btc_highs_outside_relative_tolerance_do_not_cluster(self):
        test_btc_highs_outside_relative_tolerance_do_not_cluster()

    def test_eth_lows_within_relative_tolerance_cluster(self):
        test_eth_lows_within_relative_tolerance_cluster()

    def test_relative_clustering_behaves_sensibly_across_price_regimes(self):
        test_relative_clustering_behaves_sensibly_across_price_regimes()

    def test_pairwise_relative_formula_uses_larger_price_denominator(self):
        test_pairwise_relative_formula_uses_larger_price_denominator()

    def test_group_clustering_does_not_chain_distant_levels_through_average(self):
        test_group_clustering_does_not_chain_distant_levels_through_average()
