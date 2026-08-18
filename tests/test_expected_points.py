"""Tests for the expected-points projection model.

These assert *directional* behaviour (a penalty taker outscores an
identical non-taker; a blank gameweek scores nothing) rather than exact
point values. The absolute calibration depends on tunable weights that are
expected to be re-tuned as real seasons are observed; the relationships
between players are what the selection engine actually relies on, and
those must not silently invert.
"""
import pandas as pd
import pytest

from fpl_assistant.analysis.expected_points import (
    CAPTAIN_CEILING_FACTOR,
    expected_points,
    team_schedule,
)

N_TEAMS = 4


def _player(pid: int, position: str, team: int, **overrides) -> dict:
    base = {
        "id": pid,
        "web_name": f"P{pid}",
        "team": team,
        "team_short_name": f"T{team}",
        "position": position,
        "price": 6.0,
        "now_cost": 60,
        "status": "a",
        "chance_of_playing_next_round": 100,
        "minutes": 900,
        "starts": 10,
        "total_points": 50,
        "points_per_game": 5.0,
        "form": 5.0,
        "selected_by_percent": 10.0,
        "expected_goals_per_90": 0.3,
        "expected_assists_per_90": 0.2,
        "expected_goal_involvements": 5.0,
        "expected_goals_conceded_per_90": 1.2,
        "expected_goals_conceded": 12.0,
        "saves_per_90": 0.0,
        "saves": 0,
        "bonus": 8,
        "defensive_contribution": 5,
        "yellow_cards": 1,
        "red_cards": 0,
        "penalties_order": pd.NA,
        "direct_freekicks_order": pd.NA,
        "corners_and_indirect_freekicks_order": pd.NA,
    }
    base.update(overrides)
    return base


def _teams() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "id": t,
                "name": f"Team{t}",
                "short_name": f"T{t}",
                "strength_attack_home": 1100,
                "strength_attack_away": 1100,
                "strength_defence_home": 1100,
                "strength_defence_away": 1100,
            }
            for t in range(1, N_TEAMS + 1)
        ]
    ).set_index("id", drop=False)


def _fixtures(n_gameweeks: int = 3, skip_team: int | None = None) -> pd.DataFrame:
    """Round-robin fixtures. `skip_team` is given a blank gameweek in GW1."""
    rows = []
    for gw in range(1, n_gameweeks + 1):
        for home, away in [(1, 2), (3, 4)]:
            if gw == 1 and skip_team in (home, away):
                continue
            rows.append(
                {
                    "event": gw,
                    "team_h": home,
                    "team_a": away,
                    "team_h_difficulty": 3,
                    "team_a_difficulty": 3,
                    "finished": False,
                }
            )
    return pd.DataFrame(rows)


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows).set_index("id", drop=False)


def test_projects_positive_points_for_regular_starters():
    players = _frame([_player(1, "MID", 1), _player(2, "DEF", 2)])
    xp = expected_points(players, _fixtures(), _teams(), from_event=1, horizon=3)

    assert (xp["xp_next"] > 0).all()
    assert (xp["xp_horizon"] > 0).all()
    assert xp["xp_basis"].eq("form").all()


def test_penalty_taker_outscores_identical_non_taker():
    players = _frame(
        [
            _player(1, "FWD", 1, penalties_order=1),
            _player(2, "FWD", 1, penalties_order=pd.NA),
        ]
    )
    xp = expected_points(players, _fixtures(), _teams(), from_event=1, horizon=3)
    assert xp.loc[1, "xp_next"] > xp.loc[2, "xp_next"]


def test_set_piece_taker_outscores_identical_non_taker():
    players = _frame(
        [
            _player(1, "MID", 1, corners_and_indirect_freekicks_order=1),
            _player(2, "MID", 1, corners_and_indirect_freekicks_order=pd.NA),
        ]
    )
    xp = expected_points(players, _fixtures(), _teams(), from_event=1, horizon=3)
    assert xp.loc[1, "xp_next"] > xp.loc[2, "xp_next"]


def test_rotation_risk_scores_below_nailed_on_starter():
    """The signal the old scoring formula ignored entirely: a player who
    doesn't start can't score, however good their per-90 rates are."""
    players = _frame(
        [
            _player(1, "MID", 1, starts=10, minutes=900),
            _player(2, "MID", 1, starts=2, minutes=200),
        ]
    )
    xp = expected_points(players, _fixtures(), _teams(), from_event=1, horizon=3)

    assert xp.loc[2, "expected_minutes"] < xp.loc[1, "expected_minutes"]
    assert xp.loc[2, "xp_next"] < xp.loc[1, "xp_next"]


def test_high_scoring_rate_does_not_survive_losing_your_place():
    """Points-per-game counts only games a player featured in, so it must
    be rescaled by expected minutes. Left raw, a player who starred twice
    and then lost his place keeps a starter's projection forever -- which
    put a 15-minute-a-week player into the recommended XI."""
    players = _frame(
        [
            # Same excellent scoring rate; one still starts, one doesn't.
            _player(1, "MID", 1, points_per_game=7.0, starts=10, minutes=900),
            _player(2, "MID", 1, points_per_game=7.0, starts=1, minutes=150),
        ]
    )
    xp = expected_points(players, _fixtures(), _teams(), from_event=1, horizon=3)

    assert xp.loc[2, "xp_next"] < xp.loc[1, "xp_next"] / 2


def test_injured_player_projects_near_zero():
    players = _frame(
        [_player(1, "FWD", 1), _player(2, "FWD", 1, status="i", chance_of_playing_next_round=0)]
    )
    xp = expected_points(players, _fixtures(), _teams(), from_event=1, horizon=3)

    assert xp.loc[2, "p_available"] == 0
    assert xp.loc[2, "expected_minutes"] == 0
    assert xp.loc[2, "xp_next"] < xp.loc[1, "xp_next"]


def test_doubtful_player_discounted_but_not_zeroed():
    players = _frame(
        [_player(1, "FWD", 1), _player(2, "FWD", 1, status="d", chance_of_playing_next_round=50)]
    )
    xp = expected_points(players, _fixtures(), _teams(), from_event=1, horizon=3)

    assert 0 < xp.loc[2, "xp_next"] < xp.loc[1, "xp_next"]


def test_blank_gameweek_scores_zero_for_that_week():
    # Team 1 has no GW1 fixture; team 3 does.
    players = _frame([_player(1, "MID", 1), _player(2, "MID", 3)])
    xp = expected_points(players, _fixtures(skip_team=1), _teams(), from_event=1, horizon=3)

    assert xp.loc[1, "xp_gw1"] == 0
    assert xp.loc[2, "xp_gw1"] > 0
    # ...but the horizon still picks up their later fixtures.
    assert xp.loc[1, "xp_horizon"] > 0


def test_double_gameweek_scores_more_than_single():
    single = _fixtures(n_gameweeks=1)
    double = pd.concat(
        [single, pd.DataFrame([{
            "event": 1, "team_h": 1, "team_a": 3,
            "team_h_difficulty": 3, "team_a_difficulty": 3, "finished": False,
        }])],
        ignore_index=True,
    )
    players = _frame([_player(1, "MID", 1)])

    single_xp = expected_points(players, single, _teams(), from_event=1, horizon=1)
    double_xp = expected_points(players, double, _teams(), from_event=1, horizon=1)

    assert double_xp.loc[1, "xp_next"] > single_xp.loc[1, "xp_next"] * 1.5


def test_easier_opponent_defence_boosts_attacker():
    teams = _teams()
    teams.loc[2, "strength_defence_home"] = 800  # team 1 plays team 2
    teams.loc[2, "strength_defence_away"] = 800
    strong_teams = _teams()
    strong_teams.loc[2, "strength_defence_home"] = 1400
    strong_teams.loc[2, "strength_defence_away"] = 1400

    players = _frame([_player(1, "FWD", 1)])
    easy = expected_points(players, _fixtures(1), teams, from_event=1, horizon=1)
    hard = expected_points(players, _fixtures(1), strong_teams, from_event=1, horizon=1)

    assert easy.loc[1, "xp_next"] > hard.loc[1, "xp_next"]


def test_preseason_falls_back_to_price_prior():
    players = _frame(
        [
            _player(1, "MID", 1, price=13.0, minutes=0, starts=0, total_points=0,
                    points_per_game=0.0, form=0.0, expected_goals_per_90=0.0,
                    expected_assists_per_90=0.0, expected_goal_involvements=0.0,
                    expected_goals_conceded_per_90=0.0, expected_goals_conceded=0.0,
                    bonus=0, defensive_contribution=0, yellow_cards=0),
            _player(2, "MID", 1, price=4.5, minutes=0, starts=0, total_points=0,
                    points_per_game=0.0, form=0.0, expected_goals_per_90=0.0,
                    expected_assists_per_90=0.0, expected_goal_involvements=0.0,
                    expected_goals_conceded_per_90=0.0, expected_goals_conceded=0.0,
                    bonus=0, defensive_contribution=0, yellow_cards=0),
        ]
    )
    xp = expected_points(players, _fixtures(), _teams(), from_event=1, horizon=3)

    assert xp["xp_basis"].eq("preseason").all()
    # With no match data, price is the prior — the expensive player projects higher.
    assert xp.loc[1, "xp_next"] > xp.loc[2, "xp_next"]


def test_captaincy_score_discounts_defenders_relative_to_forwards():
    """Same projected mean, different ceiling: doubling a forward is worth
    more than doubling a defender."""
    players = _frame([_player(1, "FWD", 1), _player(2, "DEF", 1)])
    xp = expected_points(players, _fixtures(), _teams(), from_event=1, horizon=3)

    ratio = CAPTAIN_CEILING_FACTOR["DEF"] / CAPTAIN_CEILING_FACTOR["FWD"]
    assert xp.loc[2, "xp_captain"] / xp.loc[2, "xp_next"] == pytest.approx(ratio, abs=0.02)
    assert xp.loc[1, "xp_captain"] == pytest.approx(xp.loc[1, "xp_next"], abs=0.02)


def test_defensive_contribution_cannot_exceed_one_per_match():
    """Guards a real trap: the API has reported this stat as raw actions in
    some seasons and threshold-hits in others. Reading a raw-action count
    as threshold-hits would inflate defenders by several points a game."""
    players = _frame(
        [_player(1, "DEF", 1, defensive_contribution=5), _player(2, "DEF", 1, defensive_contribution=5000)]
    )
    xp = expected_points(players, _fixtures(), _teams(), from_event=1, horizon=3)

    # The absurd value is clamped, so the gap stays bounded rather than exploding.
    assert xp.loc[2, "xp_next"] - xp.loc[1, "xp_next"] < 3.0


def test_clean_sheet_probability_stays_realistic_on_absurd_inputs():
    """A near-zero expected-concession is always a data artefact, never a
    real defence. Without a floor it yields a >90% clean-sheet chance,
    which inflates defenders past forwards and hands them the armband."""
    # A defender whose only case is the clean sheet, against a forward who
    # actually scores. Zero attacking output on the defender isolates what
    # this test is about.
    players = _frame(
        [
            _player(
                1, "DEF", 1,
                expected_goals_conceded_per_90=0.0, expected_goals_conceded=0.0,
                expected_goals_per_90=0.0, expected_assists_per_90=0.0,
                defensive_contribution=0, bonus=0, points_per_game=0.0,
            ),
            _player(
                2, "FWD", 1,
                expected_goals_per_90=0.6, expected_assists_per_90=0.0,
                defensive_contribution=0, bonus=0, points_per_game=0.0,
            ),
        ]
    )
    xp = expected_points(players, _fixtures(), _teams(), from_event=1, horizon=3)

    # Clean-sheet points alone (max 4, and only on a coin-flip at best) must
    # not carry a defender past a genuinely productive forward.
    assert xp.loc[1, "xp_next"] < xp.loc[2, "xp_next"]


def test_team_schedule_captures_doubles_and_blanks():
    schedule = team_schedule(_fixtures(skip_team=1), from_event=1, horizon=3)
    assert 1 not in schedule.get(1, {})  # team 1 blank in GW1
    assert len(schedule[3][1]) == 1
    assert schedule[1][2] == [(2, True)]
