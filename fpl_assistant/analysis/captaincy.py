"""Captaincy scoring: who to armband for the next gameweek.

Combines three signals, each min-max normalised to 0-1 so no single one
dominates just because of its raw scale:
  - recent form (FPL's rolling per-gameweek average)
  - fixture difficulty for the next gameweek (inverted: easier = better)
  - underlying attacking threat (expected goal involvements)
Weights are a starting point, not gospel — tune them as you see how well
they track your own read of a gameweek.

Before matches have actually been played (preseason, or GW1 before
kickoff), form/xGI are zero for everyone, so this falls back to
price/ownership instead — see squad_builder.score_players for the same
pattern.
"""
import pandas as pd

from fpl_assistant.analysis.fixtures import team_fixture_table
from fpl_assistant.analysis.season_state import is_preseason

WEIGHTS = {"form": 0.4, "fixture": 0.3, "threat": 0.3}
PRESEASON_WEIGHTS = {"price": 0.4, "ownership": 0.25, "fixture": 0.35}


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
    preseason = is_preseason(players)
    effective_min_minutes = 0 if preseason else pool_min_minutes

    next_gw_table = team_fixture_table(fixtures, teams, from_event=next_event, n_gameweeks=1)

    df = players[
        (players["minutes"] >= effective_min_minutes) & (players["status"] == "a")
    ].copy()
    # Armband value comes from goal involvements far more often than clean
    # sheets, so keep the pool to attacking positions even if a defender's
    # underlying score would otherwise sneak in.
    df = df[df["position"].isin(["MID", "FWD"])]

    df["fixture_difficulty"] = df["team"].map(next_gw_table["avg_difficulty"])
    df["opponent"] = df["team"].map(next_gw_table[next_event])
    df = df[df["fixture_difficulty"].notna()]  # drop players whose team has a blank gameweek

    df["fixture_score"] = _normalise(6 - df["fixture_difficulty"])  # invert: 5=hard -> low score

    if preseason:
        df["price_score"] = _normalise(df["price"])
        df["ownership_score"] = _normalise(df["selected_by_percent"])
        df["captaincy_score"] = (
            PRESEASON_WEIGHTS["price"] * df["price_score"]
            + PRESEASON_WEIGHTS["ownership"] * df["ownership_score"]
            + PRESEASON_WEIGHTS["fixture"] * df["fixture_score"]
        ).round(3)
    else:
        df["form_score"] = _normalise(df["form"])
        df["threat_score"] = _normalise(df["expected_goal_involvements"])
        df["captaincy_score"] = (
            WEIGHTS["form"] * df["form_score"]
            + WEIGHTS["fixture"] * df["fixture_score"]
            + WEIGHTS["threat"] * df["threat_score"]
        ).round(3)

    cols = [
        "id",
        "code",
        "web_name",
        "team_short_name",
        "team_code",
        "opponent",
        "position",
        "price",
        "form",
        "fixture_difficulty",
        "expected_goal_involvements",
        "selected_by_percent",
        "captaincy_score",
    ]
    return df.sort_values("captaincy_score", ascending=False)[cols].head(top_n)
