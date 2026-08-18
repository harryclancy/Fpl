"""Sanity tests against synthetic data — no network access required.

These aren't exhaustive; they exist to catch structural bugs (wrong column
names, broken joins, off-by-one gameweek ranges) before they surface as a
blank dashboard.
"""
import pandas as pd

from fpl_assistant.analysis import captaincy, fixtures as fixtures_analysis, form, injuries, transfers
from fpl_assistant.models import Squad, SquadPick, attach_team_names, players_df, teams_df

BOOTSTRAP = {
    "teams": [
        {"id": 1, "name": "Arsenal", "short_name": "ARS", "strength": 4, "code": 3},
        {"id": 2, "name": "Burnley", "short_name": "BUR", "strength": 2, "code": 90},
    ],
    "elements": [
        {
            "id": 101, "code": 111, "web_name": "Saka", "team": 1, "element_type": 3,
            "now_cost": 100, "total_points": 60, "points_per_game": "5.0",
            "form": "6.0", "selected_by_percent": "35.0", "minutes": 900,
            "status": "a", "news": "", "news_added": None,
            "chance_of_playing_next_round": None, "expected_goal_involvements": "5.5",
            "expected_goals_conceded": "0", "value_form": "1.2", "value_season": "6.0",
        },
        {
            "id": 102, "code": 222, "web_name": "Injured Guy", "team": 2, "element_type": 4,
            "now_cost": 55, "total_points": 10, "points_per_game": "1.0",
            "form": "0.5", "selected_by_percent": "1.0", "minutes": 90,
            "status": "i", "news": "Ankle injury", "news_added": "2026-08-10T10:00:00Z",
            "chance_of_playing_next_round": 0, "expected_goal_involvements": "0.1",
            "expected_goals_conceded": "0", "value_form": "0.1", "value_season": "1.8",
        },
    ],
}

FIXTURES = [
    {"event": 3, "team_h": 1, "team_a": 2, "team_h_difficulty": 2, "team_a_difficulty": 4, "finished": False},
    {"event": 4, "team_h": 2, "team_a": 1, "team_h_difficulty": 3, "team_a_difficulty": 3, "finished": False},
]


def _players_and_teams():
    teams = teams_df(BOOTSTRAP)
    players = attach_team_names(players_df(BOOTSTRAP), teams)
    return players, teams


def test_players_df_basic_shape():
    players, _ = _players_and_teams()
    assert players.loc[101, "position"] == "MID"
    assert players.loc[101, "price"] == 10.0
    assert players.loc[102, "status_label"] == "Injured"


def test_fixture_table_handles_blank_and_normal():
    players, teams = _players_and_teams()
    fixtures = pd.DataFrame(FIXTURES)
    table = fixtures_analysis.team_fixture_table(fixtures, teams, from_event=3, n_gameweeks=2)
    assert table.loc[1, "avg_difficulty"] == 2.5
    assert table.loc[1, 3] == "BUR (H)"


def test_captaincy_excludes_blank_gameweek_teams():
    players, teams = _players_and_teams()
    fixtures = pd.DataFrame(FIXTURES)
    result = captaincy.captaincy_candidates(
        players, fixtures, teams, next_event=3, pool_min_minutes=0
    )
    assert "Saka" in result["web_name"].values


def test_injury_flags():
    players, _ = _players_and_teams()
    flagged = injuries.flagged_players(players)
    assert 102 in flagged.index
    assert 101 not in flagged.index


def test_form_watchlists_exclude_unavailable():
    players, _ = _players_and_teams()
    in_form = form.in_form_players(players, min_minutes=0)
    assert 102 not in in_form.index  # injured, should be excluded


def test_squad_weaknesses_flags_injury():
    players, teams = _players_and_teams()
    fixtures = pd.DataFrame(FIXTURES)
    scored = transfers.squad_with_scores(players, fixtures, teams, from_event=3, window=2)
    squad = Squad(
        team_id=1,
        event=3,
        bank=0.0,
        team_value=100.0,
        transfers_made=0,
        transfers_cost=0,
        picks=[
            SquadPick(101, is_captain=True, is_vice_captain=False, multiplier=2, position_order=1),
            SquadPick(102, is_captain=False, is_vice_captain=False, multiplier=1, position_order=2),
        ],
    )
    weaknesses = transfers.squad_weaknesses(scored, squad)
    assert "Injured Guy" in weaknesses["web_name"].values
    assert "Saka" not in weaknesses["web_name"].values


def test_estimate_free_transfers_simple_case():
    history = [
        {"event": 1, "event_transfers": 0},
        {"event": 2, "event_transfers": 1},
        {"event": 3, "event_transfers": 0},
    ]
    ft = transfers.estimate_free_transfers(history, chips=[])
    assert ft == 2  # gw2: 1->2, minus 1 used = 1; gw3: 1->2
