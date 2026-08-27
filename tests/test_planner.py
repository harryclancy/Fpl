"""Tests for multi-gameweek transfer planning.

A single-week optimiser and a multi-week planner give different answers,
and the difference *is* the feature. So these tests are mostly about the
three things a one-week optimiser structurally cannot do: bank a transfer,
stage a two-part move, and wait for a fixture swing. Checking that the
plan obeys the squad rules matters too, but it's the cheap half.
"""
import random

import pandas as pd
import pytest

from fpl_assistant.analysis import planner
from fpl_assistant.analysis.optimiser import MAX_PER_CLUB, SQUAD_QUOTAS, optimise_squad

N_TEAMS = 8
HORIZON = [1, 2, 3, 4]


def _pool(seed: int = 5) -> pd.DataFrame:
    """A small pool with an explicit projection for each gameweek.

    Deliberately smaller than the optimiser's fixture: the planner builds
    three binary variables per player *per gameweek*, so a full-size pool
    would make every test a solver benchmark.
    """
    rng = random.Random(seed)
    rows = []
    pid = 1
    for team in range(1, N_TEAMS + 1):
        for position, count in {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}.items():
            for _ in range(count):
                quality = rng.random() * 0.8
                price = max(4.0, round(4.0 + (quality**2) * 10.0, 1))
                row = {
                    "id": pid,
                    "web_name": f"{position}{pid}",
                    "team": team,
                    "team_short_name": f"T{team}",
                    "position": position,
                    "price": price,
                    "selected_by_percent": round(rng.uniform(0.1, 30), 1),
                    "xp_next": round(1.0 + quality * 6.0, 3),
                    "xp_captain": round(1.0 + quality * 6.0, 3),
                }
                for gw in HORIZON:
                    row[f"xp_gw{gw}"] = round(1.0 + quality * 6.0, 3)
                row["xp_horizon"] = round(sum(row[f"xp_gw{gw}"] for gw in HORIZON), 3)
                rows.append(row)
                pid += 1
    return pd.DataFrame(rows).set_index("id", drop=False)


def _owned(pool: pd.DataFrame, budget: float = 95.0) -> list[int]:
    return optimise_squad(pool, budget=budget).squad_ids


def _names(pool: pd.DataFrame) -> dict[int, str]:
    return dict(zip(pool["id"], pool["web_name"]))


# --- the squad rules hold every single week -----------------------------

def test_every_planned_week_is_a_legal_squad():
    pool = _pool()
    owned = _owned(pool)
    plan = planner.plan_transfers(pool, owned, bank=5.0, free_transfers=1)

    assert plan.weeks
    for week in plan.weeks:
        assert len(week.starting_ids) == 11
        starters = pool[pool["id"].isin(week.starting_ids)]
        counts = starters["position"].value_counts()
        assert counts.get("GKP", 0) == 1
        assert 3 <= counts.get("DEF", 0) <= 5
        assert 2 <= counts.get("MID", 0) <= 5
        assert 1 <= counts.get("FWD", 0) <= 3
        assert week.captain_id in week.starting_ids


def test_the_plan_covers_the_gameweeks_in_order():
    pool = _pool()
    plan = planner.plan_transfers(pool, _owned(pool), bank=2.0)

    assert [w.gameweek for w in plan.weeks] == sorted(w.gameweek for w in plan.weeks)
    assert [w.gameweek for w in plan.weeks] == HORIZON[: len(plan.weeks)]


def test_transfers_in_and_out_always_balance():
    """A squad is fifteen players. If a plan sells three and buys two it
    has quietly broken the rules somewhere, and every projection after
    that point is fiction."""
    pool = _pool()
    plan = planner.plan_transfers(pool, _owned(pool), bank=6.0, free_transfers=2)

    for week in plan.weeks:
        assert len(week.in_ids) == len(week.out_ids)
        assert not set(week.in_ids) & set(week.out_ids)


def test_the_club_limit_survives_the_whole_plan():
    pool = _pool()
    plan = planner.plan_transfers(pool, _owned(pool), bank=5.0, free_transfers=2)

    owned = set(_owned(pool))
    for week in plan.weeks:
        owned = (owned - set(week.out_ids)) | set(week.in_ids)
        clubs = pool[pool["id"].isin(owned)]["team"].value_counts()
        assert clubs.max() <= MAX_PER_CLUB
        assert len(owned) == 15


# --- the things a one-week optimiser cannot do --------------------------

def test_it_waits_for_the_fixture_swing():
    """The headline capability.

    A player who is poor next week and outstanding in three weeks is a bad
    buy now and a great buy later. A one-week optimiser can only ever see
    the first half of that and will pass on him permanently.
    """
    pool = _pool()
    owned = _owned(pool)
    target = int(pool[~pool["id"].isin(owned)].query("position == 'MID'")["id"].iloc[0])

    # Terrible for two gameweeks, then enormous.
    pool.loc[target, "xp_gw1"] = 0.5
    pool.loc[target, "xp_gw2"] = 0.5
    pool.loc[target, "xp_gw3"] = 14.0
    pool.loc[target, "xp_gw4"] = 14.0
    pool.loc[target, "xp_horizon"] = 29.0
    pool.loc[target, "price"] = 5.0

    plan = planner.plan_transfers(pool, owned, bank=10.0, free_transfers=1)
    bought_in = {w.gameweek: set(w.in_ids) for w in plan.weeks}

    assert target not in bought_in.get(1, set()), "bought him for his worst gameweek"
    assert any(target in ids for ids in bought_in.values()), "never bought him at all"


def test_holding_banks_a_free_transfer_for_the_following_week():
    pool = _pool()
    plan = planner.plan_transfers(pool, _owned(pool), bank=0.0, free_transfers=1)

    for previous, week in zip(plan.weeks, plan.weeks[1:]):
        expected = min(
            planner.MAX_FREE_TRANSFERS, previous.free_transfers - previous.transfers + 1
        )
        assert week.free_transfers == expected


def test_free_transfers_never_exceed_the_cap():
    pool = _pool()
    # An already-optimal squad with no money: nothing to buy, so the
    # balance climbs every week and must stop at the cap.
    owned = optimise_squad(pool, budget=100.0).squad_ids
    plan = planner.plan_transfers(
        pool, owned, bank=0.0, free_transfers=5, horizon=4
    )

    for week in plan.weeks:
        assert week.free_transfers <= planner.MAX_FREE_TRANSFERS


def test_a_hit_is_only_taken_when_the_plan_still_comes_out_ahead():
    pool = _pool()
    owned = _owned(pool)
    plan = planner.plan_transfers(pool, owned, bank=8.0, free_transfers=1)

    for week in plan.weeks:
        assert week.hits == max(0, week.transfers - week.free_transfers)
        assert week.points_cost == week.hits * 4
    if plan.total_hits:
        assert plan.gain > 0


def test_the_plan_is_never_worse_than_standing_pat():
    pool = _pool()
    owned = _owned(pool)
    plan = planner.plan_transfers(pool, owned, bank=4.0, free_transfers=1)

    # Holding is always available to the planner, so a plan that scores
    # below the hold baseline means the objective is wired up wrong.
    assert plan.total_projected >= plan.baseline_projected - 0.01


# --- what it says -------------------------------------------------------

def test_a_hold_is_explained_as_banking_rather_than_as_nothing():
    pool = _pool()
    owned = optimise_squad(pool, budget=100.0).squad_ids
    plan = planner.plan_transfers(
        pool, owned, bank=0.0, free_transfers=1, names=_names(pool)
    )

    first = plan.first_move
    assert first is not None
    if not first.transfers:
        assert "Hold" in plan.headline
        assert any("roll to" in line for line in plan.schedule)


def test_the_headline_names_the_players_in_the_first_move():
    pool = _pool()
    owned = _owned(pool)
    plan = planner.plan_transfers(
        pool, owned, bank=10.0, free_transfers=1, names=_names(pool)
    )

    first = plan.first_move
    if first and first.transfers:
        for pid in first.out_ids + first.in_ids:
            assert plan.name(pid) in plan.headline


def test_it_always_says_only_the_first_move_is_a_decision():
    pool = _pool()
    plan = planner.plan_transfers(pool, _owned(pool), bank=3.0)

    assert any("first move is a decision" in note for note in plan.reasoning)


# --- failure modes ------------------------------------------------------

def test_a_pool_with_no_per_gameweek_projections_is_refused():
    pool = _pool().drop(columns=[f"xp_gw{gw}" for gw in HORIZON])

    with pytest.raises(RuntimeError, match="xp_gw"):
        planner.plan_transfers(pool, list(pool["id"].iloc[:15]))


def test_an_incomplete_squad_is_refused_rather_than_silently_planned():
    pool = _pool()
    with pytest.raises(RuntimeError, match="owned players"):
        planner.plan_transfers(pool, _owned(pool)[:10])


def test_horizon_columns_are_read_in_gameweek_order_not_frame_order():
    """`xp_gw10` sorts before `xp_gw9` as a string.

    Planning the weeks in the wrong order would make the transfer chain
    meaningless while looking perfectly fine, so the ordering is by
    gameweek number and this pins it.
    """
    frame = pd.DataFrame(columns=["xp_gw10", "xp_gw2", "xp_gw1", "price"])
    assert planner._horizon_columns(frame, 3) == ["xp_gw1", "xp_gw2", "xp_gw10"]


# --- injured players you still own --------------------------------------

def test_an_injured_owned_player_is_put_back_in_at_zero():
    """Projections are only computed for available players, so an injured
    one you own simply vanishes from the pool. Refusing to plan is the
    wrong answer -- a squad with an injury is exactly when the next few
    weeks of transfers need thinking about."""
    pool = _pool()
    owned = _owned(pool)
    dropped = owned[0]
    scored = pool[pool["id"] != dropped]

    restored = planner.with_owned_players(scored, pool, owned)

    assert dropped in set(restored["id"])
    row = restored[restored["id"] == dropped].iloc[0]
    assert row["xp_gw1"] == 0.0
    assert row["xp_horizon"] == 0.0
    assert row["price"] == pool.loc[dropped, "price"]
    assert row["position"] == pool.loc[dropped, "position"]


def test_the_plan_transfers_out_a_player_who_will_score_nothing():
    pool = _pool()
    owned = _owned(pool)
    dropped = owned[0]
    restored = planner.with_owned_players(pool[pool["id"] != dropped], pool, owned)

    plan = planner.plan_transfers(restored, owned, bank=5.0, free_transfers=1)

    assert any(dropped in week.out_ids for week in plan.weeks)


def test_a_pool_that_already_has_everyone_is_returned_untouched():
    pool = _pool()
    owned = _owned(pool)
    assert planner.with_owned_players(pool, pool, owned) is pool
