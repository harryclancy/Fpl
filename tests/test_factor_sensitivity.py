"""Does every factor the model claims to use actually change the answer?

A model can carry a term that looks right, is documented, is even unit
tested in isolation — and still have it cancelled out downstream by a
blend, a clip, or a normalisation, so it moves the final projection by
nothing. That failure is invisible: no test breaks, no error is raised,
and the factor is quietly decorative.

So this file holds one player fixed, changes exactly one input, and
asserts the projection moves in the right direction by a meaningful
amount. It is the audit that the factor list is real rather than
aspirational. FACTORS below is the inventory it enforces.
"""
import pandas as pd
import pytest

from fpl_assistant.analysis.expected_points import expected_points

N_TEAMS = 4
# The factors the model claims to weigh. Every entry has a test below.
FACTORS = {
    "attacking rate (xG/xA per 90)": "test_attacking_rate_raises_projection",
    "penalty duty": "test_penalty_duty_raises_projection",
    "set-piece duty": "test_set_piece_duty_raises_projection",
    "starting probability": "test_starting_probability_dominates_a_good_rate",
    "availability / injury flag": "test_availability_flag_cuts_projection_to_nothing",
    "European rotation risk": "test_european_football_reduces_a_squad_players_projection",
    "competition-specific congestion": "test_europa_league_costs_more_than_champions_league",
    "rotation shaped to spare nailed-on starters": "test_rotation_barely_touches_a_nailed_on_starter",
    "new-manager rotation risk": "test_new_manager_adds_rotation_risk",
    "suspension risk (yellow accumulation)": "test_suspension_risk_reduces_a_booked_players_projection",
    "opponent defensive strength (attackers)": "test_weak_opponent_defence_helps_an_attacker",
    "opponent attacking strength (clean sheets)": "test_weak_opponent_attack_helps_a_defender",
    "home advantage": "test_home_advantage_applies",
    "double gameweeks": "test_double_gameweek_beats_a_single",
    "blank gameweeks": "test_blank_gameweek_scores_zero",
    "horizon decay": "test_horizon_decay_discounts_later_gameweeks",
    "goalkeeper save rate": "test_goalkeeper_save_rate_raises_projection",
    "defensive contributions": "test_defensive_contributions_raise_a_defenders_projection",
    "bonus-point history": "test_bonus_history_raises_projection",
    "disciplinary record": "test_disciplinary_record_lowers_projection",
}

BASE = {
    "web_name": "P", "team": 1, "team_short_name": "CHE", "position": "MID",
    "price": 8.0, "now_cost": 80, "status": "a", "chance_of_playing_next_round": 100,
    "minutes": 900, "starts": 10, "total_points": 60, "points_per_game": 5.0, "form": 5.0,
    "selected_by_percent": 10.0,
    "expected_goals_per_90": 0.3, "expected_assists_per_90": 0.2,
    "expected_goal_involvements": 5.0,
    "expected_goals_conceded_per_90": 1.2, "expected_goals_conceded": 12.0,
    "saves_per_90": 0.0, "saves": 0, "bonus": 8, "defensive_contribution": 4,
    "yellow_cards": 1, "red_cards": 0,
    "penalties_order": pd.NA, "direct_freekicks_order": pd.NA,
    "corners_and_indirect_freekicks_order": pd.NA,
}


def _players(*overrides) -> pd.DataFrame:
    rows = []
    for index, override in enumerate(overrides, start=1):
        row = dict(BASE)
        row.update(override)
        row["id"] = index
        rows.append(row)
    return pd.DataFrame(rows).set_index("id", drop=False)


def _teams(strength: dict | None = None) -> pd.DataFrame:
    rows = []
    for team in range(1, N_TEAMS + 1):
        row = {
            "id": team, "name": f"T{team}", "short_name": ["CHE", "ARS", "BOU", "TOT"][team - 1],
            "strength_attack_home": 1100, "strength_attack_away": 1100,
            "strength_defence_home": 1100, "strength_defence_away": 1100,
        }
        row.update((strength or {}).get(team, {}))
        rows.append(row)
    return pd.DataFrame(rows).set_index("id", drop=False)


def _fixtures(n=3, home_for_team_1=True):
    rows = []
    for gw in range(1, n + 1):
        home, away = (1, 2) if home_for_team_1 else (2, 1)
        rows.append({"event": gw, "team_h": home, "team_a": away,
                     "team_h_difficulty": 3, "team_a_difficulty": 3, "finished": False})
        rows.append({"event": gw, "team_h": 3, "team_a": 4,
                     "team_h_difficulty": 3, "team_a_difficulty": 3, "finished": False})
    return pd.DataFrame(rows)


def _xp(players, teams=None, fixtures=None, horizon=3, team_context=None, column="xp_next"):
    result = expected_points(
        players, fixtures if fixtures is not None else _fixtures(),
        teams if teams is not None else _teams(), from_event=1,
        horizon=horizon, team_context=team_context,
    )
    return result[column]


def test_every_declared_factor_has_a_test():
    """Guards the inventory itself: a factor added to FACTORS without a
    test here would let the list drift into fiction."""
    import tests.test_factor_sensitivity as module

    missing = {
        factor: test for factor, test in FACTORS.items() if not hasattr(module, test)
    }
    assert not missing, f"Factors whose named test does not exist: {missing}"


# --- Attacking output --------------------------------------------------

def test_attacking_rate_raises_projection():
    xp = _xp(_players({"expected_goals_per_90": 0.15}, {"expected_goals_per_90": 0.75}))
    assert xp.loc[2] > xp.loc[1] + 0.5


def test_penalty_duty_raises_projection():
    xp = _xp(_players({"penalties_order": pd.NA}, {"penalties_order": 1}))
    assert xp.loc[2] > xp.loc[1]


def test_set_piece_duty_raises_projection():
    xp = _xp(_players(
        {"corners_and_indirect_freekicks_order": pd.NA},
        {"corners_and_indirect_freekicks_order": 1},
    ))
    assert xp.loc[2] > xp.loc[1]


# --- Minutes -----------------------------------------------------------

def test_starting_probability_dominates_a_good_rate():
    """Minutes are the foundation: a brilliant rate off the bench must not
    beat a good rate that plays."""
    xp = _xp(_players(
        {"starts": 10, "minutes": 900, "expected_goals_per_90": 0.30},
        {"starts": 1, "minutes": 120, "expected_goals_per_90": 0.90},
    ))
    assert xp.loc[1] > xp.loc[2]


def test_availability_flag_cuts_projection_to_nothing():
    xp = _xp(_players({}, {"status": "i", "chance_of_playing_next_round": 0}))
    assert xp.loc[2] == pytest.approx(0.0, abs=0.01)


def test_european_football_reduces_a_squad_players_projection():
    """The factor the Bournemouth question exposed: midweek football costs
    minutes, and no per-90 rate can see it coming."""
    rotation_prone = {"starts": 6, "minutes": 560}
    context = {"CHE": {"european_competition": "none"}}
    europe = {"CHE": {"european_competition": "uel"}}

    rested = _xp(_players(rotation_prone), team_context=context)
    congested = _xp(_players(rotation_prone), team_context=europe)
    assert congested.loc[1] < rested.loc[1]


def test_europa_league_costs_more_than_champions_league():
    """A Thursday night leaves two fewer recovery days than a Tuesday."""
    rotation_prone = {"starts": 6, "minutes": 560}
    ucl = _xp(_players(rotation_prone), team_context={"CHE": {"european_competition": "ucl"}})
    uel = _xp(_players(rotation_prone), team_context={"CHE": {"european_competition": "uel"}})
    assert uel.loc[1] < ucl.loc[1]


def test_rotation_barely_touches_a_nailed_on_starter():
    """The penalty must be shaped so it hits squad players, not the elite
    assets a squad is built around — a flat multiplier would wrongly shave
    points off everyone."""
    nailed = {"starts": 10, "minutes": 900}
    rested = _xp(_players(nailed), team_context={"CHE": {"european_competition": "none"}})
    congested = _xp(_players(nailed), team_context={"CHE": {"european_competition": "uel"}})
    assert congested.loc[1] == pytest.approx(rested.loc[1], rel=0.05)


def test_new_manager_adds_rotation_risk():
    rotation_prone = {"starts": 6, "minutes": 560}
    settled = _xp(_players(rotation_prone), team_context={"CHE": {"european_competition": "none"}})
    unsettled = _xp(
        _players(rotation_prone),
        team_context={"CHE": {"european_competition": "none", "new_manager": True}},
    )
    assert unsettled.loc[1] < settled.loc[1]


def test_suspension_risk_reduces_a_booked_players_projection():
    """A player on four yellows is one tackle from a ban, and carries no
    availability flag because he's perfectly fit."""
    xp = _xp(_players({"yellow_cards": 0}, {"yellow_cards": 4}), horizon=5)
    assert xp.loc[2] < xp.loc[1]


# --- Fixtures ----------------------------------------------------------

def test_weak_opponent_defence_helps_an_attacker():
    weak = _teams({2: {"strength_defence_home": 800, "strength_defence_away": 800}})
    strong = _teams({2: {"strength_defence_home": 1400, "strength_defence_away": 1400}})
    assert _xp(_players({}), teams=weak).loc[1] > _xp(_players({}), teams=strong).loc[1]


def test_weak_opponent_attack_helps_a_defender():
    defender = {"position": "DEF", "expected_goals_per_90": 0.05}
    weak = _teams({2: {"strength_attack_home": 800, "strength_attack_away": 800}})
    strong = _teams({2: {"strength_attack_home": 1400, "strength_attack_away": 1400}})
    assert _xp(_players(defender), teams=weak).loc[1] > _xp(_players(defender), teams=strong).loc[1]


def test_home_advantage_applies():
    home = _xp(_players({}), fixtures=_fixtures(home_for_team_1=True))
    away = _xp(_players({}), fixtures=_fixtures(home_for_team_1=False))
    assert home.loc[1] > away.loc[1]


def test_double_gameweek_beats_a_single():
    single = _fixtures(n=1)
    double = pd.concat([single, pd.DataFrame([{
        "event": 1, "team_h": 1, "team_a": 3,
        "team_h_difficulty": 3, "team_a_difficulty": 3, "finished": False}])], ignore_index=True)
    assert _xp(_players({}), fixtures=double, horizon=1).loc[1] > _xp(
        _players({}), fixtures=single, horizon=1).loc[1] * 1.5


def test_blank_gameweek_scores_zero():
    blank = pd.DataFrame([{"event": 1, "team_h": 3, "team_a": 4,
                           "team_h_difficulty": 3, "team_a_difficulty": 3, "finished": False}])
    assert _xp(_players({}), fixtures=blank, horizon=1).loc[1] == pytest.approx(0.0, abs=0.01)


def test_horizon_decay_discounts_later_gameweeks():
    """A fixture four weeks out is worth less than one this weekend,
    because you can transfer before then."""
    result = expected_points(_players({}), _fixtures(n=3), _teams(), from_event=1, horizon=3)
    per_match = result["xp_per_match"].loc[1]
    # The decayed horizon total must sit below a naive 3x of one gameweek.
    assert result["xp_horizon"].loc[1] < result["xp_next"].loc[1] * 3
    assert per_match > 0


# --- Other scoring categories -------------------------------------------

def test_goalkeeper_save_rate_raises_projection():
    keeper = {"position": "GKP", "expected_goals_per_90": 0.0, "expected_assists_per_90": 0.0}
    xp = _xp(_players({**keeper, "saves_per_90": 1.5}, {**keeper, "saves_per_90": 4.5}))
    assert xp.loc[2] > xp.loc[1]


def test_defensive_contributions_raise_a_defenders_projection():
    defender = {"position": "DEF"}
    xp = _xp(_players({**defender, "defensive_contribution": 0},
                      {**defender, "defensive_contribution": 9}))
    assert xp.loc[2] > xp.loc[1]


def test_bonus_history_raises_projection():
    xp = _xp(_players({"bonus": 0}, {"bonus": 20}))
    assert xp.loc[2] > xp.loc[1]


def test_disciplinary_record_lowers_projection():
    """Cards cost points directly, separately from the ban risk."""
    xp = _xp(_players({"yellow_cards": 0, "red_cards": 0}, {"yellow_cards": 0, "red_cards": 3}))
    assert xp.loc[2] < xp.loc[1]


def test_suspension_risk_costs_a_match_not_a_season():
    """The bug this guards against was a whole-window ban probability
    applied as a per-gameweek multiplier, so a player one booking from a
    ban had his starting probability multiplied by zero and disappeared
    from the model. A ban costs one match, not every match — left unfixed
    it took five projected points off the recommended XI while every test
    still passed."""
    from fpl_assistant.analysis.expected_points import (
        MAX_SUSPENSION_DISCOUNT,
        _suspension_risk,
    )

    profiles = pd.DataFrame(
        [{"id": i, "yellow_cards": y} for i, y in enumerate([0, 3, 4, 9, 40])]
    ).set_index("id", drop=False)
    risk = _suspension_risk(profiles, games=20, horizon=5)

    assert risk.iloc[0] == 0.0, "a player with no bookings carries no ban risk"
    assert risk.max() <= MAX_SUSPENSION_DISCOUNT + 1e-9
    # One booking from a ban is the worst realistic case and should cost
    # roughly one match in five — not the whole window.
    assert 0.1 <= risk.iloc[2] <= 0.25


def test_a_booked_player_still_projects_most_of_his_points():
    """Sanity at the level that actually matters: the projection, not the
    intermediate risk number."""
    xp = _xp(_players({"yellow_cards": 0}, {"yellow_cards": 4}), horizon=5)
    assert xp.loc[2] < xp.loc[1]
    assert xp.loc[2] > xp.loc[1] * 0.7, "a booking record must not erase a player"
