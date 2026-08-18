"""Form and underlying-stats analysis on top of the bootstrap player table."""
import pandas as pd


def minutes_reliability(players: pd.DataFrame, events_played: int) -> pd.Series:
    """Fraction of available minutes a player has actually played this season.

    A guard against picking players who look great on a per-90 basis but
    are rotation risks — 90 mins possible per gameweek so far.
    """
    if events_played <= 0:
        return pd.Series(0.0, index=players.index)
    possible = events_played * 90
    return (players["minutes"] / possible).clip(upper=1.0)


def in_form_players(
    players: pd.DataFrame,
    position: str | None = None,
    max_price: float | None = None,
    min_minutes: int = 180,
    top_n: int = 15,
) -> pd.DataFrame:
    """Players ranked by recent form (FPL's own rolling metric), filtered to
    exclude nailed-off bench-warmers and, optionally, a position/budget.
    """
    df = players[players["minutes"] >= min_minutes].copy()
    if position:
        df = df[df["position"] == position]
    if max_price is not None:
        df = df[df["price"] <= max_price]

    df = df[df["status"] == "a"]  # available only — no point recommending injured players

    cols = [
        "web_name",
        "team_short_name",
        "position",
        "price",
        "form",
        "points_per_game",
        "total_points",
        "selected_by_percent",
        "expected_goal_involvements",
    ]
    return df.sort_values("form", ascending=False)[cols].head(top_n)


def best_value_players(
    players: pd.DataFrame, position: str | None = None, min_minutes: int = 270, top_n: int = 15
) -> pd.DataFrame:
    """Points per million spent — who's overperforming their price tag."""
    df = players[(players["minutes"] >= min_minutes) & (players["status"] == "a")].copy()
    if position:
        df = df[df["position"] == position]

    df["points_per_million"] = (df["total_points"] / df["price"]).round(2)
    cols = [
        "web_name",
        "team_short_name",
        "position",
        "price",
        "total_points",
        "points_per_million",
        "selected_by_percent",
    ]
    return df.sort_values("points_per_million", ascending=False)[cols].head(top_n)


def differentials(
    players: pd.DataFrame,
    max_ownership: float = 10.0,
    min_form: float = 4.0,
    top_n: int = 15,
) -> pd.DataFrame:
    """Low-ownership, in-form players — the classic 'differential' pick to
    gain rank on the rest of your mini-league.
    """
    df = players[
        (players["selected_by_percent"] <= max_ownership)
        & (players["form"] >= min_form)
        & (players["status"] == "a")
    ].copy()
    cols = [
        "web_name",
        "team_short_name",
        "position",
        "price",
        "form",
        "selected_by_percent",
        "total_points",
    ]
    return df.sort_values("form", ascending=False)[cols].head(top_n)
