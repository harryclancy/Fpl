"""Bookmaker expectations: what's anticipated, not what's already happened.

Every other signal in this app is backward-looking. Expected goals per 90
describes chances a player has had; form describes points already scored.
Both are useful and both share a blind spot: they don't know that a
manager said yesterday he'd rotate, that a defence is missing two
centre-backs, or that this particular striker has scored in four straight
against this particular opponent.

Bookmakers price all of that, continuously, with money at stake. An
anytime-goalscorer price isn't a read on finishing ability -- it's a read
on where a player is being found, how often he arrives in dangerous areas,
and which patterns the market expects to repeat against this opponent. It
is the closest thing available to an *anticipated* return.

The prices are hand-researched into a file per gameweek rather than
scraped, because bookmaker sites don't offer a usable free feed and
scraping them is neither reliable nor obviously allowed. That makes this
layer only as fresh as its research date, which the app states rather than
hides.

Implied probability here is the raw 1/odds figure, which includes the
bookmaker's margin and therefore runs a few points high. That overround is
left in deliberately: removing it needs the full market for the fixture,
which the file doesn't hold, and a slightly conservative-in-the-right-
direction number beats a fabricated correction.
"""
import json
import re
from pathlib import Path

import pandas as pd

ODDS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "odds"


def load(gameweek: int) -> dict | None:
    path = ODDS_DIR / f"gw{gameweek}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def implied_probability(decimal_odds) -> float | None:
    """1/odds, with the bookmaker margin left in. See the module note.

    Guards pd.NA explicitly. Most players have no researched price, so the
    missing case is the common one -- and `not pd.NA` raises rather than
    being falsey, which would take the page down for every squad
    containing a player nobody priced.
    """
    if decimal_odds is None or pd.isna(decimal_odds):
        return None
    try:
        value = float(decimal_odds)
    except (TypeError, ValueError):
        return None
    return None if value <= 1.0 else round(1.0 / value, 3)


def _normalise(name: str) -> str:
    return re.sub(r"[^a-z ]", "", str(name).lower()).strip()


def annotate(players: pd.DataFrame, gameweek: int) -> pd.DataFrame:
    """Adds `goal_odds`, `p_goal_odds`, `odds_note` and `captain_share`.

    `captain_share` is the percentage of managers expected to captain the
    player. It is the single most important number for rank and it appears
    nowhere in the FPL API, so it is researched alongside the prices.
    """
    df = players.copy()
    for column in ("goal_odds", "p_goal_odds", "captain_share"):
        df[column] = pd.NA
    df["odds_note"] = None

    data = load(gameweek)
    if not data:
        return df

    lookup = {}
    for entry in data.get("players", []):
        for key in (entry.get("name"), entry.get("full_name")):
            if key:
                lookup[_normalise(key)] = entry

    def _entry_for(row):
        for key in ("web_name", "second_name"):
            value = row.get(key)
            if value and _normalise(value) in lookup:
                return lookup[_normalise(value)]
        first, second = row.get("first_name"), row.get("second_name")
        if first and second:
            return lookup.get(_normalise(f"{first} {second}"))
        return None

    matched = df.apply(_entry_for, axis=1)
    df["goal_odds"] = matched.map(lambda e: e.get("anytime_goalscorer") if e else pd.NA)
    df["p_goal_odds"] = df["goal_odds"].map(implied_probability)
    df["captain_share"] = matched.map(lambda e: e.get("captain_share") if e else pd.NA)
    df["odds_note"] = matched.map(lambda e: e.get("note") if e else None)
    return df


def matchup_note(gameweek: int, team_short: str, opponent_short: str | None = None) -> str | None:
    """What typically happens when this side plays this opponent.

    History against a specific opponent is the kind of thing a per-90 rate
    cannot express and every human analyst reaches for first.
    """
    data = load(gameweek)
    if not data:
        return None
    for entry in data.get("matchups", []):
        if str(entry.get("team", "")).upper() != str(team_short or "").upper():
            continue
        against = entry.get("opponent")
        if opponent_short and against and str(against).upper() != str(opponent_short).upper():
            continue
        return entry.get("note")
    return None
