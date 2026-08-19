"""Tests for "copy the suggested squad, minus these players".

The distinction that matters: removing a player and re-solving is not the
same as removing him and leaving a hole. The money he freed changes what
the rest of the squad should be, and the best replacement is often not the
next-best player in his position. These tests pin down that it actually
re-solves, that the players you kept are kept, and that a solve which has
to relax constraints says so rather than quietly changing more than you
asked for.
"""
import pandas as pd
import pytest

from fpl_assistant.analysis import optimiser, squad_builder

N_TEAMS = 20


def _players() -> pd.DataFrame:
    rows = []
    pid = 1
    counts = {"GKP": 3, "DEF": 8, "MID": 8, "FWD": 5}
    for team in range(1, N_TEAMS + 1):
        for pos, n in counts.items():
            for i in range(n):
                price = round(4.0 + i * 0.8, 1)
                rows.append({
                    "id": pid, "web_name": f"{pos}{pid}", "team": team,
                    "team_short_name": f"T{team}", "position": pos, "price": price,
                    "now_cost": int(price * 10), "selected_by_percent": 5.0,
                    # Value rises with price but not perfectly, so the solver
                    # has real choices to make rather than a fixed ordering.
                    "xp_horizon": 8.0 + i * 2.2 + (pid % 5) * 0.4,
                    "xp_next": 1.6 + i * 0.45 + (pid % 5) * 0.08,
                    "xp_captain": 1.6 + i * 0.45,
                    "status": "a",
                })
                pid += 1
    return pd.DataFrame(rows).set_index("id", drop=False)


@pytest.fixture
def solved():
    scored = _players()
    return scored, optimiser.optimise_squad(scored, template_weight=0.0)


# --- the core behaviour -------------------------------------------------

def test_a_removed_player_is_not_in_the_rebuilt_squad(solved):
    scored, solution = solved
    victim = solution.starting_ids[0]

    rebuilt = squad_builder.rebuild_without(scored, solution, [victim], template_weight=0.0)

    assert victim not in rebuilt.solution.squad_ids
    assert rebuilt.removed_ids == [victim]


def test_removing_two_players_removes_both(solved):
    scored, solution = solved
    victims = solution.starting_ids[:2]

    rebuilt = squad_builder.rebuild_without(scored, solution, victims, template_weight=0.0)

    assert not set(victims) & set(rebuilt.solution.squad_ids)


def test_everyone_you_did_not_veto_is_kept(solved):
    """The point of locking the rest: you asked to change one player, not
    to be handed a different squad."""
    scored, solution = solved
    victim = solution.starting_ids[0]

    rebuilt = squad_builder.rebuild_without(scored, solution, [victim], template_weight=0.0)

    survivors = set(solution.squad_ids) - {victim}
    assert survivors <= set(rebuilt.solution.squad_ids)
    assert rebuilt.notes == [], "no constraint should have needed relaxing here"


def test_the_result_is_still_a_legal_squad(solved):
    scored, solution = solved
    rebuilt = squad_builder.rebuild_without(
        scored, solution, solution.starting_ids[:2], template_weight=0.0
    )
    squad = scored[scored["id"].isin(rebuilt.solution.squad_ids)]

    assert len(squad) == optimiser.SQUAD_SIZE
    assert squad["price"].sum() <= optimiser.DEFAULT_BUDGET + 1e-6
    assert squad["position"].value_counts().to_dict() == optimiser.SQUAD_QUOTAS
    assert squad["team"].value_counts().max() <= optimiser.MAX_PER_CLUB
    assert len(rebuilt.solution.starting_ids) == optimiser.STARTING_SIZE


def test_it_re_solves_rather_than_taking_the_next_best_in_that_position(solved):
    """The distinction the whole feature rests on. Freeing a premium's
    budget should be allowed to change the squad somewhere else, not just
    slot in the nearest like-for-like."""
    scored, solution = solved
    indexed = scored.set_index("id")
    # Veto the most expensive player, which frees the most money.
    victim = max(solution.squad_ids, key=lambda pid: float(indexed.loc[pid, "price"]))

    rebuilt = squad_builder.rebuild_without(scored, solution, [victim], template_weight=0.0)

    # The replacement need not be in the same position as the player
    # removed; what must hold is that the budget is actually re-spent
    # rather than left sitting in the bank.
    new_cost = float(scored[scored["id"].isin(rebuilt.solution.squad_ids)]["price"].sum())
    old_cost = float(scored[scored["id"].isin(solution.squad_ids)]["price"].sum())
    assert new_cost > old_cost - float(indexed.loc[victim, "price"]) + 0.5


def test_removing_a_player_never_improves_on_the_unrestricted_solve(solved):
    """A veto is a constraint. It can be free, but it cannot be better than
    the unconstrained optimum — if it were, the original solve was wrong."""
    scored, solution = solved
    rebuilt = squad_builder.rebuild_without(
        scored, solution, [solution.starting_ids[0]], template_weight=0.0
    )
    assert rebuilt.points_delta <= 1e-6


def test_the_swaps_are_reported_position_for_position(solved):
    scored, solution = solved
    indexed = scored.set_index("id")
    victim = solution.starting_ids[0]

    rebuilt = squad_builder.rebuild_without(scored, solution, [victim], template_weight=0.0)

    assert rebuilt.swaps
    for swap in rebuilt.swaps:
        out_pos = indexed[indexed["web_name"] == swap.out_name]["position"].iloc[0]
        in_pos = indexed[indexed["web_name"] == swap.in_name]["position"].iloc[0]
        assert out_pos == in_pos


# --- edges --------------------------------------------------------------

def test_removing_nobody_returns_the_original_squad_untouched(solved):
    scored, solution = solved
    rebuilt = squad_builder.rebuild_without(scored, solution, [], template_weight=0.0)

    assert rebuilt.solution is solution
    assert rebuilt.swaps == []
    assert rebuilt.points_delta == 0.0


def test_removing_someone_who_was_never_picked_is_a_no_op(solved):
    scored, solution = solved
    outsider = next(pid for pid in scored["id"] if pid not in set(solution.squad_ids))

    rebuilt = squad_builder.rebuild_without(scored, solution, [outsider], template_weight=0.0)
    assert rebuilt.solution is solution


def test_an_impossible_veto_raises_rather_than_returning_a_broken_squad():
    """If banning the players leaves no legal fifteen, that has to surface
    as an error the page can explain — not a squad quietly missing a
    goalkeeper."""
    rows = []
    pid = 1
    # Exactly enough goalkeepers to fill the quota, so banning one makes
    # the problem genuinely infeasible.
    for pos, n in (("GKP", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        for _ in range(n):
            rows.append({
                "id": pid, "web_name": f"{pos}{pid}", "team": pid, "team_short_name": f"T{pid}",
                "position": pos, "price": 5.0, "now_cost": 50, "selected_by_percent": 5.0,
                "xp_horizon": 20.0, "xp_next": 4.0, "xp_captain": 4.0, "status": "a",
            })
            pid += 1
    scored = pd.DataFrame(rows).set_index("id", drop=False)
    solution = optimiser.optimise_squad(scored, template_weight=0.0)
    keeper = next(p for p in solution.squad_ids if scored.loc[p, "position"] == "GKP")

    with pytest.raises(RuntimeError):
        squad_builder.rebuild_without(scored, solution, [keeper], template_weight=0.0)
