"""Captaincy scoring: who to armband for the next gameweek.

Combines three signals, each min-max normalised to 0-1 so no single one
dominates just because of its raw scale:
  - recent form (FPL's rolling per-gameweek average)
  - fixture difficulty for the next gameweek (inverted: easier = better)
  - underlying attacking threat (expected goal involvements)
Weights are a starting point, not gospel — tune them as you see how well
they track your own read of a gameweek.
"""
import pandas as pd

from fpl_assistant.analysis.fixtures import team_fixture_table

WEIGHTS = {"form": 0.4, "fixture": 0.3, "threat": 0.3}


def _normalise(series: pd.Series) -> pd.Series:
    lo, hi = series.min(), series.max()
    if hi == lo:
        return pd.Series(0.5, index=series.index)
    return (series - lo) / (hi - lo)


def captaincy_candidates(
    players: pd.DataFrame,
    fixtures: pd.DataFrame,
    teams: pd.DataFrame,
    next_event: int,
    top_n: int = 10,
    pool_min_minutes: int = 300,
) -> pd.DataFrame:
    next_gw_table = team_fixture_table(fixtures, teams, from_event=next_event, n_gameweeks=1)

    df = players[
        (players["minutes"] >= pool_min_minutes) & (players["status"] == "a")
    ].copy()

    df["fixture_difficulty"] = df["team"].map(next_gw_table["avg_difficulty"])
    df["opponent"] = df["team"].map(next_gw_table[next_event])
    df = df[df["fixture_difficulty"].notna()]  # drop players whose team has a blank gameweek

    df["form_score"] = _normalise(df["form"])
    df["fixture_score"] = _normalise(6 - df["fixture_difficulty"])  # invert: 5=hard -> low score
    df["threat_score"] = _normalise(df["expected_goal_involvements"])

    df["captaincy_score"] = (
        WEIGHTS["form"] * df["form_score"]
        + WEIGHTS["fixture"] * df["fixture_score"]
        + WEIGHTS["threat"] * df["threat_score"]
    ).round(3)

    cols = [
        "web_name",
        "team_short_name",
        "opponent",
        "position",
        "form",
        "fixture_difficulty",
        "expected_goal_involvements",
        "selected_by_percent",
        "captaincy_score",
    ]
    return df.sort_values("captaincy_score", ascending=False)[cols].head(top_n)
