"""Detects whether the season has started yet from the bootstrap player table.

Before Gameweek 1's deadline (and until its matches are actually played),
minutes/form/total_points are zero for every player. Anything that filters
or ranks on those fields needs to know this so it can fall back to
preseason-appropriate signals (price, ownership, fixtures) instead of
silently returning an empty table.
"""
import pandas as pd


def is_preseason(players: pd.DataFrame) -> bool:
    return players["minutes"].fillna(0).sum() == 0
