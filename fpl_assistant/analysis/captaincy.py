"""Captaincy scoring: who to armband for the next gameweek.

Ranks on `xp_captain` from the expected-points model -- the same
projection that drives squad selection, so the two can't disagree. An app
that puts a player in the recommended XI and then declines to captain him
on unrelated reasoning leaves the user no way to tell which answer to
believe.

`xp_captain` is the ceiling-adjusted variant rather than the raw mean,
because the armband doubles a result: a defender and a forward projected
identically are not equivalent bets once doubled, since the forward can
return 15+ on a two-goal afternoon while the defender's realistic best is
a clean sheet plus bonus.

The older normalised form/fixture/threat blend is retained only as a
fallback for the case where no projection can be produced at all.
"""
import pandas as pd

from fpl_assistant.analysis import consensus
from fpl_assistant.analysis.expected_points import expected_points
from fpl_assistant.analysis.fixtures import team_fixture_table
from fpl_assistant.analysis.season_state import is_preseason

WEIGHTS = {"form": 0.4, "fixture": 0.3, "threat": 0.3}
# Price and ownership already encode the market's and the crowd's own
# preseason homework -- a heavily-owned nailed-on premium (a Haaland-type
# captaincy lock) stays a strong captaincy pick even across a moderately
# tough single-gameweek fixture, in practice. Fixture difficulty is real
# signal but noisier this early, so it should nudge close calls, not
# outweigh price+ownership and drop a clear premium out of contention --
# see squad_builder.score_players for the same reasoning applied there.
PRESEASON_WEIGHTS = {"price": 0.5, "ownership": 0.3, "fixture": 0.2}


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

    # Rank on the same projection the selection engine uses, so the two
    # tabs can't contradict each other -- an app that recommends a player
    # into the XI and then declines to captain him for unrelated reasons
    # gives the user no way to tell which answer to trust. `xp_captain` is
    # the ceiling-adjusted variant: the armband doubles a result, so upside
    # matters more than the average (see expected_points).
    projected = expected_points(
        players, fixtures, teams, next_event, horizon=1,
        team_context=consensus.load_team_context(),
    )
    df["expected_points"] = df["id"].map(projected["xp_next"])
    df["captaincy_score"] = df["id"].map(projected["xp_captain"]).round(2)
    df["expected_minutes"] = df["id"].map(projected["expected_minutes"])

    # Fall back to the old normalised blend only if the projection couldn't
    # be produced for anyone (e.g. every team blank in this gameweek).
    if df["captaincy_score"].isna().all():
        if preseason:
            df["captaincy_score"] = (
                PRESEASON_WEIGHTS["price"] * _normalise(df["price"])
                + PRESEASON_WEIGHTS["ownership"] * _normalise(df["selected_by_percent"])
                + PRESEASON_WEIGHTS["fixture"] * df["fixture_score"]
            ).round(3)
        else:
            df["captaincy_score"] = (
                WEIGHTS["form"] * _normalise(df["form"])
                + WEIGHTS["fixture"] * df["fixture_score"]
                + WEIGHTS["threat"] * _normalise(df["expected_goal_involvements"])
            ).round(3)
    df["captaincy_score"] = df["captaincy_score"].fillna(0.0)

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
        "expected_points",
        "expected_minutes",
        "captaincy_score",
    ]
    return df.sort_values("captaincy_score", ascending=False)[cols].head(top_n)
