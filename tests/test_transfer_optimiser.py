"""Tests for transfer planning.

The discipline being tested is hit economics: a transfer that gains less
than the 4 points it costs must not be recommended, however attractive the
incoming player looks in isolation. Churning through hits is the most
common way a good squad turns into a mediocre season.
"""
import pandas as pd
import pytest

from fpl_assistant.analysis.optimiser import (
    SQUAD_QUOTAS,
    optimise_squad,
    optimise_transfers,
)
from tests.test_optimiser import _pool


def _starting_squad(pool: pd.DataFrame, budget: float = 95.0) -> list[int]:
    """A legal squad with money left over, so transfers are affordable."""
    return optimise_squad(pool, budget=budget).squad_ids


def test_holds_when_nothing_is_worth_a_hit():
    """With zero free transfers, only a gain above the hit cost justifies
    moving -- and an already-optimal squad has no such gain available."""
    pool = _pool()
    squad = optimise_squad(pool, budget=100.0).squad_ids

    plan = optimise_transfers(pool, squad, bank=0.0, free_transfers=0)

    assert plan.transfers == 0
    assert plan.points_cost == 0
    assert "Hold" in plan.summary


def test_takes_a_free_transfer_that_improves_the_squad():
    pool = _pool()
    squad = _starting_squad(pool)

    plan = optimise_transfers(pool, squad, bank=5.0, free_transfers=1)

    assert plan.transfers <= 1
    assert plan.points_cost == 0
    assert plan.net_gain >= 0


def test_hit_is_only_taken_when_the_gain_clears_its_cost():
    pool = _pool()
    squad = _starting_squad(pool)

    plan = optimise_transfers(pool, squad, bank=5.0, free_transfers=1, max_transfers=3)

    if plan.transfers > 1:
        # Every transfer beyond the free one must pay for itself.
        assert plan.gross_gain > plan.points_cost
        assert plan.net_gain > 0
    assert plan.hits == max(0, plan.transfers - 1)
    assert plan.points_cost == plan.hits * 4


def test_result_is_still_a_legal_squad():
    pool = _pool()
    squad = _starting_squad(pool)
    plan = optimise_transfers(pool, squad, bank=5.0, free_transfers=2)

    new_squad = pool[pool["id"].isin(plan.solution.squad_ids)]
    assert len(plan.solution.squad_ids) == 15
    for position, quota in SQUAD_QUOTAS.items():
        assert (new_squad["position"] == position).sum() == quota
    assert new_squad["team"].value_counts().max() <= 3
    assert len(plan.solution.starting_ids) == 11


def test_spending_is_capped_by_squad_value_plus_bank():
    pool = _pool()
    squad = _starting_squad(pool, budget=90.0)
    held_value = pool[pool["id"].isin(squad)]["price"].sum()
    bank = 2.0

    plan = optimise_transfers(pool, squad, bank=bank, free_transfers=2)
    assert plan.solution.total_cost <= held_value + bank + 1e-6


def test_transfers_out_and_in_match_up():
    pool = _pool()
    squad = _starting_squad(pool)
    plan = optimise_transfers(pool, squad, bank=5.0, free_transfers=2)

    assert len(plan.out_ids) == len(plan.in_ids) == plan.transfers
    assert set(plan.out_ids).issubset(set(squad))
    assert set(plan.in_ids).isdisjoint(set(squad))


def test_more_free_transfers_never_makes_you_worse_off():
    pool = _pool()
    squad = _starting_squad(pool)

    one = optimise_transfers(pool, squad, bank=5.0, free_transfers=1, max_transfers=3)
    three = optimise_transfers(pool, squad, bank=5.0, free_transfers=3, max_transfers=3)

    assert three.net_gain >= one.net_gain - 1e-6


def test_max_transfers_is_respected():
    pool = _pool()
    squad = _starting_squad(pool, budget=88.0)
    plan = optimise_transfers(pool, squad, bank=10.0, free_transfers=5, max_transfers=2)
    assert plan.transfers <= 2


def test_rejects_a_squad_it_cannot_find():
    pool = _pool()
    with pytest.raises(RuntimeError):
        optimise_transfers(pool, [999_999], bank=0.0, free_transfers=1)
