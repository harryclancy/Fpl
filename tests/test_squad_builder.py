"""Tests for the from-scratch squad recommender, against synthetic data."""
import pandas as pd

from fpl_assistant.analysis.squad_builder import (
    MAX_PER_CLUB,
    SQUAD_QUOTAS,
    best_starting_xi,
    build_squad,
    pick_captain,
    score_players,
)

N_TEAMS = 6


def _synthetic_players() -> pd.DataFrame:
    rows = []
    pid = 1
    # Enough players per position, spread across teams, at a range of
    # prices, so budget/quota/club-cap constraints are all exercised.
    counts = {"GKP": 2, "DEF": 4, "MID": 4, "FWD": 3}
    for team in range(1, N_TEAMS + 1):
        for pos, n in counts.items():
            for i in range(n):
                price = 4.0 + (pid % 12) * 0.9  # spread of prices ~4.0-14.0
                rows.append(
                    {
                        "id": pid,
                        "web_name": f"{pos}{pid}",
                        "team": team,
                        "team_short_name": f"T{team}",
                        "position": pos,
                        "now_cost": int(price * 10),
                        "price": price,
                        "total_points": 0,
                        "points_per_game": 0.0,
                        "form": 0.0,
                        "selected_by_percent": float((pid * 7) % 40),
                        "minutes": 0,
                        "status": "a",
                        "status_label": "Available",
                        "news": "",
                        "chance_of_playing_next_round": 100,
                        "expected_goal_involvements": 0.0,
                        "expected_goals_conceded": 0.0,
                    }
                )
                pid += 1
    return pd.DataFrame(rows).set_index("id", drop=False)


def _teams_df() -> pd.DataFrame:
    return pd.DataFrame(
        [{"id": t, "name": f"Team{t}", "short_name": f"T{t}"} for t in range(1, N_TEAMS + 1)]
    ).set_index("id", drop=False)


def _fixtures_df(from_event: int = 1, n_gameweeks: int = 5) -> pd.DataFrame:
    rows = []
    for gw in range(from_event, from_event + n_gameweeks):
        # round-robin pairing so every team has exactly one fixture per gw
        for i in range(0, N_TEAMS, 2):
            rows.append(
                {
                    "event": gw,
                    "team_h": i + 1,
                    "team_a": i + 2,
                    "team_h_difficulty": 3,
                    "team_a_difficulty": 3,
                    "finished": False,
                }
            )
    return pd.DataFrame(rows)


def test_score_players_preseason_basis():
    players = _synthetic_players()
    scored = score_players(players, _fixtures_df(), _teams_df(), from_event=1)
    assert (scored["scoring_basis"] == "preseason").all()
    assert scored["squad_score"].notna().all()


def test_build_squad_respects_quotas_budget_and_club_cap():
    players = _synthetic_players()
    scored = score_players(players, _fixtures_df(), _teams_df(), from_event=1)
    squad = build_squad(scored, budget=100.0)

    assert len(squad) == 15
    assert squad["price"].sum() <= 100.0 + 1e-6

    for pos, quota in SQUAD_QUOTAS.items():
        assert (squad["position"] == pos).sum() == quota

    club_counts = squad["team"].value_counts()
    assert (club_counts <= MAX_PER_CLUB).all()


def test_best_starting_xi_is_valid_formation():
    players = _synthetic_players()
    scored = score_players(players, _fixtures_df(), _teams_df(), from_event=1)
    squad = build_squad(scored, budget=100.0)
    starters, bench, formation = best_starting_xi(squad)

    assert len(starters) == 11
    assert len(bench) == 4

    d, m, f = (int(x) for x in formation.split("-"))
    assert d + m + f == 10
    assert 3 <= d <= 5
    assert 2 <= m <= 5
    assert 1 <= f <= 3

    starting_positions = squad.set_index("id").loc[starters, "position"]
    assert (starting_positions == "GKP").sum() == 1
    assert (starting_positions == "DEF").sum() == d
    assert (starting_positions == "MID").sum() == m
    assert (starting_positions == "FWD").sum() == f


def test_pick_captain_prefers_attackers():
    players = _synthetic_players()
    scored = score_players(players, _fixtures_df(), _teams_df(), from_event=1)
    squad = build_squad(scored, budget=100.0)
    starters, _, _ = best_starting_xi(squad)

    captain_id, vice_id = pick_captain(squad, starters)
    captain_pos = squad.set_index("id").loc[captain_id, "position"]
    vice_pos = squad.set_index("id").loc[vice_id, "position"]

    assert captain_id != vice_id
    assert captain_pos in ("MID", "FWD")
    assert vice_pos in ("MID", "FWD")
