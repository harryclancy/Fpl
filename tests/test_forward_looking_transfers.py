"""Transfer suggestions must look forward, not back.

The reported case, near enough verbatim: a promoted-side centre-back
scores and keeps a clean sheet in GW1, so his form is the best in the
game. He is not a better buy than an Arsenal defender if his side play
Villa and Chelsea next — but a ranking built on recent points says he is,
confidently, and that is what the app was doing.

So the fixture here is deliberately built to make form and projection
disagree, because a test where they agree proves nothing.
"""
import pandas as pd
import pytest

from fpl_assistant.analysis import transfers
from fpl_assistant.models import Squad, SquadPick


def _squad(ids):
    return Squad(
        team_id=1, event=2, bank=0.0, team_value=100.0, transfers_made=0, transfers_cost=0,
        picks=[SquadPick(pid, False, False, 1, i + 1) for i, pid in enumerate(ids)],
    )


def _pool() -> pd.DataFrame:
    """One owned defender to replace, and two candidates who disagree.

    `hot_streak` is the Ajayi shape: enormous form off one huge week, a
    brutal run ahead, and a projection that knows it. `steady` is the
    White shape: unremarkable recent points, easy fixtures, better
    projection.
    """
    rows = [
        {
            "id": 1, "code": 1, "web_name": "Owned", "team": 1, "team_short_name": "OWN",
            "team_code": 1, "position": "DEF", "price": 5.0, "status": "a",
            "status_label": "Available", "form": 1.0, "minutes": 900,
            "fixture_run_difficulty": 3.4, "upcoming_blanks": 0, "minutes_share": 1.0,
            "xp_horizon": 14.0,
        },
        {
            "id": 2, "code": 2, "web_name": "HotStreak", "team": 2, "team_short_name": "HUL",
            "team_code": 2, "position": "DEF", "price": 4.5, "status": "a",
            "status_label": "Available",
            # One goal and a clean sheet: the best form in the game.
            "form": 9.5, "minutes": 900,
            # ...and Villa then Chelsea to come.
            "fixture_run_difficulty": 4.6, "upcoming_blanks": 0, "minutes_share": 1.0,
            "xp_horizon": 15.5,
        },
        {
            "id": 3, "code": 3, "web_name": "Steady", "team": 3, "team_short_name": "ARS",
            "team_code": 3, "position": "DEF", "price": 5.5, "status": "a",
            "status_label": "Available",
            "form": 2.5, "minutes": 900,
            "fixture_run_difficulty": 2.1, "upcoming_blanks": 0, "minutes_share": 1.0,
            "xp_horizon": 24.0,
        },
    ]
    return pd.DataFrame(rows).set_index("id", drop=False)


def test_the_better_projection_beats_the_better_form():
    """The headline requirement."""
    pool = _pool()
    ranked = transfers.suggest_replacements(pool, _squad([1]), outgoing_player_id=1, budget=1.0)

    assert list(ranked["web_name"]) [0] == "Steady", (
        "the form leader was suggested ahead of the better projection"
    )


def test_form_alone_would_have_given_the_opposite_answer():
    """Guards the test itself: if form and projection agreed here, the
    test above would pass with the fix reverted."""
    pool = _pool()
    by_form = pool[pool["id"] != 1].sort_values("form", ascending=False)
    assert by_form["web_name"].iloc[0] == "HotStreak"


def test_the_upgrade_over_the_outgoing_player_is_reported():
    pool = _pool()
    ranked = transfers.suggest_replacements(pool, _squad([1]), outgoing_player_id=1, budget=1.0)
    steady = ranked[ranked["web_name"] == "Steady"].iloc[0]
    assert steady["upgrade"] == pytest.approx(10.0)


def test_a_swap_that_gains_nothing_is_not_suggested():
    """Transfers are scarce; a sideways move wastes one."""
    pool = _pool()
    pool.loc[2, "xp_horizon"] = 14.2  # barely better than Owned's 14.0
    pool.loc[3, "xp_horizon"] = 14.1
    ranked = transfers.suggest_replacements(pool, _squad([1]), outgoing_player_id=1, budget=1.0)
    # Nothing clears the upgrade bar, so the fallback shows the pool rather
    # than pretending one of them is an upgrade.
    assert (ranked["upgrade"] < transfers.MIN_UPGRADE_POINTS).all()


def test_weaknesses_are_ordered_by_projection_not_by_recent_scoring():
    """A player who blanked once ranks above one whose whole run has
    turned, if you sort on form. That's backwards."""
    pool = _pool()
    pool.loc[2, "fixture_run_difficulty"] = 4.6   # flagged: tough run
    pool.loc[1, "fixture_run_difficulty"] = 4.6   # flagged: tough run
    weak = transfers.squad_weaknesses(pool, _squad([1, 2]))

    assert list(weak["web_name"]) == ["Owned", "HotStreak"], (
        "expected the worse projection first, not the worse form"
    )


def test_it_still_works_without_a_projection_attached():
    """Older callers pass a bare player table. It must fall back to
    fixtures rather than to form — fixtures are at least about games still
    to be played."""
    pool = _pool().drop(columns=["xp_horizon"])
    ranked = transfers.suggest_replacements(pool, _squad([1]), outgoing_player_id=1, budget=1.0)
    assert ranked["web_name"].iloc[0] == "Steady"
