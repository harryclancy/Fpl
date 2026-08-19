"""Tests for the "why him, why not the other guy" answers.

The value of this feature is that the answer is *computed*, not asserted:
"why not Bruno" is answered by forcing him into the squad and re-solving,
so the reply is the actual trade rather than an opinion. These tests check
the trade is reported correctly and honestly.
"""
import pandas as pd
import pytest

from fpl_assistant.analysis import explain, optimiser
from tests.test_optimiser import _pool


@pytest.fixture
def pool_and_solution():
    pool = _pool()
    solution = optimiser.optimise_squad(pool, budget=100.0)
    return pool, solution


def _an_omitted_player(pool, solution, position=None):
    outside = pool[~pool["id"].isin(solution.squad_ids)]
    if position:
        outside = outside[outside["position"] == position]
    return int(outside.sort_values("xp_horizon", ascending=False)["id"].iloc[0])


def test_explains_a_player_who_is_in_the_squad(pool_and_solution):
    pool, solution = pool_and_solution
    answer = explain.explain_player(pool, solution, solution.starting_ids[0])

    assert answer.in_squad
    assert "is in the squad" in answer.headline
    assert answer.detail


def test_identifies_the_captain_by_role(pool_and_solution):
    pool, solution = pool_and_solution
    answer = explain.explain_player(pool, solution, solution.captain_id)
    assert "captaining" in answer.headline


def test_omitted_player_answer_shows_the_actual_cost(pool_and_solution):
    pool, solution = pool_and_solution
    player_id = _an_omitted_player(pool, solution)

    answer = explain.explain_player(pool, solution, player_id)

    assert not answer.in_squad
    assert answer.points_delta is not None
    # Forcing a player the optimiser rejected can never improve the squad --
    # the original solve was optimal, so this is a sanity check on the whole
    # counterfactual.
    assert answer.points_delta <= 1e-6


def test_swaps_are_position_for_position(pool_and_solution):
    """Squad quotas are fixed, so every change is like-for-like. Zipping
    the dropped and added lists in solver order reported nonsense swaps
    like a forward being replaced by a midfielder."""
    pool, solution = pool_and_solution
    player_id = _an_omitted_player(pool, solution)
    answer = explain.explain_player(pool, solution, player_id)

    positions = pool.set_index("id")["position"]
    names_to_position = pool.set_index("web_name")["position"].to_dict()
    for swap in answer.swaps:
        assert names_to_position[swap.out_name] == names_to_position[swap.in_name]

    assert positions.loc[player_id] in names_to_position.values()


def test_forced_player_leads_the_swap_list(pool_and_solution):
    """The swap that brings him in is the change the question was about;
    everything else is a knock-on downgrade to pay for it, and the list
    only reads correctly in that order."""
    pool, solution = pool_and_solution
    player_id = _an_omitted_player(pool, solution)
    answer = explain.explain_player(pool, solution, player_id)

    name = pool.set_index("id").loc[player_id, "web_name"]
    if answer.swaps:
        assert answer.swaps[0].in_name == name


def test_close_calls_are_described_as_close(pool_and_solution):
    """A near-tie should read as a judgement call, not a verdict -- the
    model's margin of error is bigger than a fraction of a point."""
    pool, solution = pool_and_solution
    # Find the cheapest omission, which is likeliest to be near-free.
    outside = pool[~pool["id"].isin(solution.squad_ids)]
    best = None
    for player_id in outside.sort_values("xp_horizon", ascending=False)["id"].head(25):
        answer = explain.explain_player(pool, solution, int(player_id))
        if answer.points_delta is not None and answer.points_delta >= -0.5:
            best = answer
            break
    if best is None:
        pytest.skip("No near-tie omission in this pool")
    assert "close call" in best.headline


def test_compare_reports_the_gap_and_the_price_difference():
    pool = _pool()
    expensive = int(pool.sort_values("price", ascending=False)["id"].iloc[0])
    cheap = int(pool.sort_values("price")["id"].iloc[0])

    answer = explain.compare_players(pool, expensive, cheap)

    assert answer.points_delta is not None
    joined = " ".join(answer.detail)
    assert "costs" in joined and "more" in joined


def test_compare_calls_a_near_tie_level():
    pool = _pool().copy()
    ids = pool["id"].tolist()[:2]
    pool.loc[pool["id"].isin(ids), "xp_horizon"] = 20.0

    answer = explain.compare_players(pool, ids[0], ids[1])
    assert "effectively level" in answer.headline


def test_consensus_reasoning_is_carried_into_the_answer(pool_and_solution):
    pool, solution = pool_and_solution
    pool = pool.copy()
    player_id = _an_omitted_player(pool, solution)
    pool["consensus_reason"] = None
    pool["consensus_watch_out"] = None
    pool.loc[pool["id"] == player_id, "consensus_reason"] = "Analysts love him."
    pool.loc[pool["id"] == player_id, "consensus_watch_out"] = "But he is expensive."

    answer = explain.explain_player(pool, solution, player_id)
    assert answer.consensus_case == "Analysts love him."
    assert answer.consensus_against == "But he is expensive."


# --- club-level verdicts in a direct answer -----------------------------

def _row_with(**extra):
    import pandas as pd

    base = {
        "id": 1, "web_name": "Player", "team_short_name": "BOU", "position": "DEF",
        "price": 5.0, "xp_next": 4.0, "xp_horizon": 20.0, "consensus_reason": None,
        "consensus_watch_out": None, "consensus_dissent": None, "club_stance": None,
        "club_stance_case": None, "club_stance_until": pd.NA,
    }
    base.update(extra)
    return pd.Series(base)


def test_a_club_verdict_is_phrased_as_being_about_the_club():
    from fpl_assistant.analysis import explain

    verdict = explain._club_verdict(
        _row_with(club_stance="avoid", club_stance_until=9,
                  club_stance_case="Worst opening run in the league.")
    )
    assert "BOU" in verdict
    assert "GW9" in verdict
    assert "Worst opening run" in verdict


def test_a_player_with_no_club_verdict_gets_none():
    from fpl_assistant.analysis import explain

    assert explain._club_verdict(_row_with()) is None
    assert explain._club_verdict(_row_with(club_stance="target")) is None


def test_a_verdict_with_no_expiry_omits_the_gameweek():
    from fpl_assistant.analysis import explain

    verdict = explain._club_verdict(_row_with(club_stance="caution", club_stance_case="Risky."))
    assert "GW" not in verdict
    assert "wary" in verdict
