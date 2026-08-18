"""Tests for the ILP squad optimiser.

The point of replacing the greedy builder was to get guarantees, so these
tests assert guarantees: every FPL rule holds exactly, and the solution is
genuinely optimal rather than merely legal. The optimality test is the one
that matters most -- a heuristic can pass every constraint check while
still leaving points on the table, which is exactly how the old builder
managed to drop a near-unanimous premium and look fine doing it.
"""
import random

import pandas as pd
import pytest

from fpl_assistant.analysis.optimiser import (
    MAX_PER_CLUB,
    SQUAD_QUOTAS,
    optimise_squad,
    optimise_starting_xi,
)

N_TEAMS = 20


def _pool(seed: int = 3) -> pd.DataFrame:
    """A realistically-shaped player pool.

    Price tracks quality, because that's the trade-off the optimiser exists
    to resolve. A pool where cheap players carry elite underlying numbers
    makes every premium look like a mistake and tests nothing real.
    """
    rng = random.Random(seed)
    rows = []
    pid = 1
    for team in range(1, N_TEAMS + 1):
        for position, count in {"GKP": 3, "DEF": 8, "MID": 9, "FWD": 5}.items():
            for _ in range(count):
                quality = rng.random() * 0.8
                price = max(4.0, round(4.0 + (quality**2) * 12.0 + rng.uniform(-0.2, 0.2), 1))
                rows.append(
                    {
                        "id": pid,
                        "web_name": f"{position}{pid}",
                        "team": team,
                        "team_short_name": f"T{team}",
                        "position": position,
                        "price": price,
                        "selected_by_percent": round(rng.uniform(0.1, 30), 1),
                        "xp_horizon": round(4.0 + quality * 22.0, 3),
                        "xp_next": round(1.0 + quality * 6.0, 3),
                        "xp_captain": round(1.0 + quality * 6.0, 3),
                    }
                )
                pid += 1
    return pd.DataFrame(rows).set_index("id", drop=False)


def _squad_of(pool: pd.DataFrame, solution) -> pd.DataFrame:
    return pool[pool["id"].isin(solution.squad_ids)]


def test_solution_satisfies_every_fpl_rule():
    pool = _pool()
    solution = optimise_squad(pool, budget=100.0)
    squad = _squad_of(pool, solution)

    assert len(solution.squad_ids) == 15
    assert len(set(solution.squad_ids)) == 15
    assert len(solution.starting_ids) == 11
    assert len(solution.bench_ids) == 4

    # Unlike the greedy builder, the budget is a hard constraint, not a
    # target it tries to hit and then patches up afterwards.
    assert squad["price"].sum() <= 100.0 + 1e-6

    for position, quota in SQUAD_QUOTAS.items():
        assert (squad["position"] == position).sum() == quota

    assert squad["team"].value_counts().max() <= MAX_PER_CLUB

    assert set(solution.starting_ids).issubset(set(solution.squad_ids))
    assert set(solution.bench_ids).isdisjoint(set(solution.starting_ids))


def test_starting_xi_is_a_legal_formation():
    pool = _pool()
    solution = optimise_squad(pool, budget=100.0)
    starters = pool[pool["id"].isin(solution.starting_ids)]

    counts = starters["position"].value_counts()
    assert counts.get("GKP", 0) == 1
    assert 3 <= counts.get("DEF", 0) <= 5
    assert 2 <= counts.get("MID", 0) <= 5
    assert 1 <= counts.get("FWD", 0) <= 3
    assert counts.get("DEF", 0) + counts.get("MID", 0) + counts.get("FWD", 0) == 10
    assert solution.formation == f"{counts['DEF']}-{counts['MID']}-{counts['FWD']}"


def test_captain_and_vice_are_distinct_starters():
    pool = _pool()
    solution = optimise_squad(pool, budget=100.0)

    assert solution.captain_id in solution.starting_ids
    assert solution.vice_captain_id in solution.starting_ids
    assert solution.captain_id != solution.vice_captain_id


def test_solution_is_optimal_not_merely_legal():
    """No random legal squad should beat the solver's objective.

    This is the guarantee the greedy builder could not give.
    """
    pool = _pool()
    solution = optimise_squad(pool, budget=100.0, template_weight=0.0)

    points = pool.set_index("id")["xp_horizon"]
    solver_xi_points = points.loc[solution.starting_ids].sum()

    rng = random.Random(99)
    for _ in range(150):
        # Build a random legal squad, then field its best legal XI.
        picks = []
        for position, quota in SQUAD_QUOTAS.items():
            candidates = pool[pool["position"] == position]
            picks.append(candidates.sample(quota, random_state=rng.randint(0, 10**6)))
        candidate = pd.concat(picks)
        if candidate["price"].sum() > 100.0:
            continue
        if candidate["team"].value_counts().max() > MAX_PER_CLUB:
            continue
        starters, _, _ = optimise_starting_xi(candidate, points_column="xp_horizon")
        assert points.loc[starters].sum() <= solver_xi_points + 1e-6


def test_locked_players_are_forced_into_the_squad():
    pool = _pool()
    # Pick an expensive, low-projection player the optimiser would never
    # choose on merit, so the lock is doing real work.
    unattractive = pool.sort_values(["xp_horizon", "price"], ascending=[True, False]).iloc[0]
    solution = optimise_squad(pool, budget=100.0, locked_ids=[int(unattractive["id"])])

    assert int(unattractive["id"]) in solution.squad_ids
    assert len(solution.squad_ids) == 15


def test_banned_players_are_excluded():
    pool = _pool()
    baseline = optimise_squad(pool, budget=100.0)
    banned = baseline.squad_ids[:3]

    solution = optimise_squad(pool, budget=100.0, banned_ids=banned)
    assert set(banned).isdisjoint(set(solution.squad_ids))
    assert len(solution.squad_ids) == 15


def test_tighter_budget_yields_no_better_squad():
    pool = _pool()
    rich = optimise_squad(pool, budget=100.0, template_weight=0.0)
    poor = optimise_squad(pool, budget=85.0, template_weight=0.0)

    assert poor.total_cost <= 85.0 + 1e-6
    assert poor.expected_points <= rich.expected_points + 1e-6


def test_template_weight_pulls_a_highly_owned_player_in():
    """The rank-risk lever: with ownership ignored a low-projection player
    is skipped; weighted heavily, shadowing the template wins."""
    pool = _pool()
    # Make one mid-tier player near-universally owned but unremarkable.
    target = pool[(pool["position"] == "MID") & (pool["price"].between(7.0, 9.0))].iloc[0]
    pool.loc[target["id"], "selected_by_percent"] = 90.0
    pool.loc[target["id"], "xp_horizon"] = float(pool["xp_horizon"].median())

    ignored = optimise_squad(pool, budget=100.0, template_weight=0.0)
    shadowed = optimise_squad(pool, budget=100.0, template_weight=0.5)

    assert int(target["id"]) not in ignored.squad_ids
    assert int(target["id"]) in shadowed.squad_ids


def test_chasing_rank_lowers_ownership_and_costs_projected_points():
    """The differential strategy has to actually do something.

    Measured as a mirror image of "protect" (penalising only ownership
    above the template threshold), chasing was a silent no-op whenever the
    squad held no template player -- which is the normal case.
    """
    pool = _pool()
    balanced = optimise_squad(pool, budget=100.0, template_weight=0.05)
    chasing = optimise_squad(pool, budget=100.0, template_weight=-0.15)

    ownership = pool.set_index("id")["selected_by_percent"]
    balanced_own = ownership.loc[balanced.squad_ids].mean()
    chasing_own = ownership.loc[chasing.squad_ids].mean()

    assert chasing_own < balanced_own
    # ...and it pays for that in expected points, which is the whole trade.
    points = pool.set_index("id")["xp_horizon"]
    assert points.loc[chasing.starting_ids].sum() <= points.loc[balanced.starting_ids].sum() + 1e-6


def test_bench_prefers_cheap_players_over_expensive_cover():
    """Points come from the XI, so budget belongs there -- an expensive
    bench is the classic beginner mistake the objective must avoid."""
    pool = _pool()
    solution = optimise_squad(pool, budget=100.0)
    squad = _squad_of(pool, solution)

    bench_cost = squad.loc[squad["id"].isin(solution.bench_ids), "price"].sum()
    xi_cost = squad.loc[squad["id"].isin(solution.starting_ids), "price"].sum()
    assert bench_cost < xi_cost / 3


def test_reserve_keeper_is_last_off_the_bench():
    pool = _pool()
    solution = optimise_squad(pool, budget=100.0)
    positions = pool.set_index("id")["position"]
    assert positions.loc[solution.bench_ids[-1]] == "GKP"


def test_infeasible_budget_raises():
    pool = _pool()
    with pytest.raises(RuntimeError):
        optimise_squad(pool, budget=10.0)


def test_optimise_starting_xi_picks_the_best_legal_eleven():
    pool = _pool()
    solution = optimise_squad(pool, budget=100.0)
    squad = _squad_of(pool, solution)

    starters, bench, _ = optimise_starting_xi(squad, points_column="xp_next")
    assert len(starters) == 11
    assert len(bench) == 4

    indexed = squad.set_index("id")
    # Within each position, the starters must be exactly the highest
    # scorers -- benching a better player than one you started is never
    # right, whatever formation was chosen.
    for position in SQUAD_QUOTAS:
        starting = indexed.loc[[s for s in starters if indexed.loc[s, "position"] == position]]
        benched = indexed.loc[[b for b in bench if indexed.loc[b, "position"] == position]]
        if starting.empty or benched.empty:
            continue
        assert starting["xp_next"].min() >= benched["xp_next"].max()
