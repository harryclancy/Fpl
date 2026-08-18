"""Injury / suspension / rotation-risk flags, straight from the bootstrap feed.

FPL's own `status` + `news` + `chance_of_playing_next_round` fields are
maintained by their editorial team and updated frequently on matchdays —
this is more reliable than us trying to scrape/guess it independently.
"""
import pandas as pd


def flagged_players(players: pd.DataFrame, owned_only_ids: list[int] | None = None) -> pd.DataFrame:
    """Anyone not nailed-on 'available' — injured, doubtful, suspended, or
    with a chance_of_playing below 100%. Optionally restricted to a given
    set of player ids (e.g. your own squad).
    """
    df = players[
        (players["status"] != "a") | (players["chance_of_playing_next_round"] < 100)
    ].copy()

    if owned_only_ids is not None:
        df = df[df["id"].isin(owned_only_ids)]

    cols = [
        "web_name",
        "team_short_name",
        "position",
        "status_label",
        "chance_of_playing_next_round",
        "news",
        "news_added",
    ]
    return df.sort_values("chance_of_playing_next_round")[cols]
