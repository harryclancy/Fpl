"""What a player did in previous seasons, and how much to trust this one.

The bug this exists to fix, stated plainly: after one gameweek the model
was treating one match as evidence. Haaland took five shots against
Bournemouth, didn't score, finished on two points -- and the projection
dropped him far enough that the optimiser sold the most expensive and
most-owned asset in the game. No human would do that, and the reason no
human would do that is that humans carry a prior. They know he scored 27
league goals last season and 22 the season before, and they know one
blank against that background means almost nothing.

The model had no prior. It had a bottom-up component model (good) blended
against realised points-per-game (also good) at a *fixed* weight -- and a
fixed weight is the mistake, because it treats a one-match average and a
thirty-match average as equally informative. They are not remotely
equally informative.

So two things live here:

  1. **Shrinkage.** How much of this season's record to believe, as a
     function of how much of it there is. One game is worth very little;
     ten games is worth a lot; the crossover is gradual and explicit
     rather than hidden in a constant.

  2. **The prior itself.** Per-90 output over the previous two seasons,
     weighted toward the more recent, which is what the shrinkage shrinks
     *toward*. Without it, "don't trust one game" just means "trust
     nothing", and the projection falls back on price alone.

Both are deliberately simple. This is a hedge against small samples, not
an attempt to model a career.
"""
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

HISTORY_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "history"

# Matches of the current season needed before it carries equal weight with
# the prior. Set from how FPL managers actually behave: nobody abandons a
# proven premium on one blank, most are willing to act by about six or
# seven games, and by ten nearly everyone accepts the new season's
# evidence over last year's. Six puts the crossover in that window.
#
# Concretely: after 1 game the current season carries 14% of the weight,
# after 3 games 33%, after 6 games 50%, after 12 games 67%.
SHRINKAGE_GAMES = 6.0

# How much last season counts against the one before it. Two seasons back
# is real evidence but a worse guide -- squads change, roles change, ages
# change -- so it gets under half the say.
SEASON_WEIGHTS = (1.0, 0.45)

# A season with barely any football in it is not evidence of anything: a
# player can have three excellent cameos and a per-90 that means nothing.
#
# Gated on appearances rather than minutes, because appearances is the
# figure published season reviews reliably carry and minutes often isn't.
# The alternative -- requiring minutes -- would mean the seeded prior
# silently applied to nobody, which is the failure mode that matters here.
MIN_APPEARANCES_FOR_PRIOR = 10
MIN_MINUTES_FOR_PRIOR = 450

# The minimum players per position before the prior is fair to use.
#
# This exists because of a real failure. The first seeded file held six
# players and every one was an attacker. That is not a neutral gap: a
# player WITH a prior gets a stable two-season signal while a player
# WITHOUT one is left on a single gameweek, so covering only attackers
# systematically advantages attackers. The app duly recommended selling
# Gabriel -- the highest-scoring defender in the game the previous season
# on 209 points -- to keep a striker who had just blanked.
#
# Four is low on purpose. It is not "enough data", it is "enough that no
# position is being silently left out of the memory the others have".
MIN_PLAYERS_PER_POSITION = 4
ALL_POSITIONS = ("GKP", "DEF", "MID", "FWD")


@dataclass
class SeasonRecord:
    """One player's output in one completed season."""

    season: str
    minutes: int = 0
    goals: int = 0
    assists: int = 0
    clean_sheets: int = 0
    total_points: int = 0
    appearances: int = 0

    @property
    def nineties(self) -> float:
        return self.minutes / 90.0

    @property
    def substantial(self) -> bool:
        return self.appearances >= MIN_APPEARANCES_FOR_PRIOR

    def per_90(self, attribute: str) -> float:
        """A per-90 rate, or zero when minutes weren't recorded.

        Zero here means "unknown", and every caller has to treat it that
        way. Minutes are optional in the seeded file because published
        season reviews don't always carry them.
        """
        if not self.substantial or self.minutes < MIN_MINUTES_FOR_PRIOR:
            return 0.0
        return getattr(self, attribute) / self.nineties

    @property
    def points_per_start(self) -> float:
        """Points per appearance, which is what a projection compares to.

        Per-90 would flatter a substitute who scores in ten-minute
        cameos; per-appearance is closer to the question the model is
        actually asking, which is what this player returns in a match he
        features in. It's also computable from published totals alone,
        which per-90 is not.
        """
        if not self.substantial:
            return 0.0
        return self.total_points / self.appearances


@dataclass
class PlayerHistory:
    """A player's completed seasons, most recent first."""

    name: str
    team: str = ""
    position: str = ""
    seasons: list[SeasonRecord] = field(default_factory=list)

    @property
    def usable(self) -> list[SeasonRecord]:
        return [s for s in self.seasons if s.substantial]

    def weighted(self, attribute: str) -> float:
        """Recency-weighted average of a per-90 rate across seasons."""
        usable = self.usable
        if not usable:
            return 0.0
        total = weight_sum = 0.0
        for record, weight in zip(usable, SEASON_WEIGHTS):
            total += record.per_90(attribute) * weight
            weight_sum += weight
        return total / weight_sum if weight_sum else 0.0

    @property
    def points_per_start(self) -> float:
        usable = self.usable
        if not usable:
            return 0.0
        total = weight_sum = 0.0
        for record, weight in zip(usable, SEASON_WEIGHTS):
            total += record.points_per_start * weight
            weight_sum += weight
        return total / weight_sum if weight_sum else 0.0

    @property
    def seasons_summary(self) -> str:
        """Plain-English record, for showing next to a recommendation.

        The point of a prior is undermined if it's invisible: "we're
        holding him because of last season" is only convincing if the app
        says what last season was.
        """
        parts = []
        for record in self.usable:
            # Only state what the source actually carried. Printing
            # "0 goals" for a season where goals simply weren't recorded
            # turns a gap in the data into a false claim about a player.
            bits = []
            if record.goals:
                bits.append(f"{record.goals} goals")
            if record.assists:
                bits.append(f"{record.assists} assists")
            detail = f"{', '.join(bits)} in " if bits else ""
            parts.append(
                f"{record.season}: {detail}{record.appearances} games "
                f"({record.total_points} pts)"
            )
        return " · ".join(parts)


def _normalise(name: str) -> str:
    """Strips accents, punctuation and case so names match across sources.

    Necessary because the history file is written from published season
    reviews ("João Pedro", "Gyökeres") while FPL's own `web_name` is its
    own thing. Matching on the raw string silently misses exactly the
    players the prior matters most for.
    """
    decomposed = unicodedata.normalize("NFKD", str(name))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", stripped.lower())


def load(season_file: str = "seasons.json") -> dict[str, PlayerHistory]:
    """Reads the committed season history, keyed by normalised name."""
    path = HISTORY_DIR / season_file
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return parse(payload)


def parse(payload: dict) -> dict[str, PlayerHistory]:
    """Same as `load`, on a payload that is not on disk yet.

    Split out so the refresh script can check what it is about to write
    BEFORE it overwrites the committed file. A guard that only runs against
    what already landed reports the damage; this one can prevent it.
    """
    out: dict[str, PlayerHistory] = {}
    for entry in payload.get("players", []):
        try:
            history = PlayerHistory(
                name=str(entry["name"]),
                team=str(entry.get("team", "")),
                position=str(entry.get("position", "")).upper(),
                seasons=[
                    SeasonRecord(
                        season=str(season.get("season", "")),
                        minutes=int(season.get("minutes", 0) or 0),
                        goals=int(season.get("goals", 0) or 0),
                        assists=int(season.get("assists", 0) or 0),
                        clean_sheets=int(season.get("clean_sheets", 0) or 0),
                        total_points=int(season.get("total_points", 0) or 0),
                        appearances=int(season.get("appearances", 0) or 0),
                    )
                    for season in entry.get("seasons", [])
                ],
            )
        except (KeyError, TypeError, ValueError):
            continue
        out[_normalise(history.name)] = history
        for alias in entry.get("aliases", []):
            out.setdefault(_normalise(alias), history)
    return out


def current_season_weight(games_played: float, half_life: float = SHRINKAGE_GAMES) -> float:
    """How much of this season's record to believe, from 0 to 1.

    The whole point of the module in one line. `games / (games + k)` is
    the standard shrinkage curve and it has the property that matters
    here: it is near zero when the sample is near zero, rather than
    jumping straight to full confidence the moment any data exists.
    """
    games = max(0.0, float(games_played))
    if half_life <= 0:
        return 1.0
    return games / (games + half_life)


def attach(
    players: pd.DataFrame, histories: dict[str, PlayerHistory] | None = None
) -> pd.DataFrame:
    """Adds prior-season columns to a player frame.

    Players with no history get zeros and an empty summary, which the
    caller must treat as "no prior" rather than "a prior of zero" -- a
    newly promoted striker with no Premier League record is unknown, not
    bad, and scoring him as bad would be its own version of the bug this
    module exists to fix.
    """
    histories = load() if histories is None else histories
    df = players.copy()
    if not histories:
        df["prior_points_per_start"] = 0.0
        df["prior_goals_per_90"] = 0.0
        df["prior_assists_per_90"] = 0.0
        df["prior_seasons"] = ""
        df["has_prior"] = False
        return df

    keys = df["web_name"].map(_normalise) if "web_name" in df.columns else pd.Series("", index=df.index)
    matched = keys.map(histories)
    # Second pass on the full name, which catches players whose `web_name`
    # is a surname shared with someone else, or an initialised form
    # ("B.Fernandes") that normalises differently from the published one.
    if "second_name" in df.columns:
        fallback = (
            (df.get("first_name", "").fillna("") + " " + df["second_name"].fillna(""))
            .map(_normalise)
            .map(histories)
        )
        matched = matched.fillna(fallback)

    df["prior_points_per_start"] = matched.map(
        lambda h: h.points_per_start if isinstance(h, PlayerHistory) else 0.0
    ).astype(float)
    df["prior_goals_per_90"] = matched.map(
        lambda h: h.weighted("goals") if isinstance(h, PlayerHistory) else 0.0
    ).astype(float)
    df["prior_assists_per_90"] = matched.map(
        lambda h: h.weighted("assists") if isinstance(h, PlayerHistory) else 0.0
    ).astype(float)
    df["prior_seasons"] = matched.map(
        lambda h: h.seasons_summary if isinstance(h, PlayerHistory) else ""
    )
    df["has_prior"] = df["prior_points_per_start"] > 0
    return df


# --- What the last two completed seasons taught -------------------------

@dataclass
class Lesson:
    """One durable takeaway, and the thing it should change."""

    lesson: str
    detail: str = ""
    rule: str = ""


@dataclass
class SeasonReview:
    season: str
    headline: str = ""
    facts: list[str] = field(default_factory=list)
    lessons: list[Lesson] = field(default_factory=list)


@dataclass
class Trends:
    """Season reviews plus the rules carried into the current season.

    Kept as data rather than code because it is research, and research
    goes stale. A lesson from two seasons ago that no longer holds should
    be editable without touching the model.
    """

    seasons: list[SeasonReview] = field(default_factory=list)
    carried: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    researched: str = ""

    @property
    def rules(self) -> list[str]:
        """Every actionable rule across every season, most recent first."""
        out = []
        for review in self.seasons:
            for lesson in review.lessons:
                if lesson.rule:
                    out.append(f"{review.season}: {lesson.rule}")
        return out


def load_trends(filename: str = "trends.json") -> Trends:
    path = HISTORY_DIR / filename
    if not path.exists():
        return Trends()
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return Trends()

    seasons = []
    for entry in payload.get("seasons", []):
        seasons.append(
            SeasonReview(
                season=str(entry.get("season", "")),
                headline=str(entry.get("headline", "")),
                facts=[str(f) for f in entry.get("facts", [])],
                lessons=[
                    Lesson(
                        lesson=str(item.get("lesson", "")),
                        detail=str(item.get("detail", "")),
                        rule=str(item.get("rule", "")),
                    )
                    for item in entry.get("lessons", [])
                ],
            )
        )
    # Most recent season first: the further back a season is, the less it
    # should shape a decision, and the ordering should say so.
    seasons.sort(key=lambda s: s.season, reverse=True)
    return Trends(
        seasons=seasons,
        carried=[str(c) for c in payload.get("carried_into_2026_27", [])],
        sources=[str(s) for s in payload.get("sources", [])],
        researched=str(payload.get("researched", "")),
    )


# --- Is the prior fair to use? ------------------------------------------

@dataclass
class Coverage:
    """How evenly the prior covers the pitch.

    Reported rather than assumed, because the damage from a lopsided prior
    is invisible from the outside: every projection looks reasonable, and
    the only symptom is that one position keeps getting sold.
    """

    per_position: dict[str, int] = field(default_factory=dict)
    total: int = 0

    @property
    def thin_positions(self) -> list[str]:
        return [
            position
            for position in ALL_POSITIONS
            if self.per_position.get(position, 0) < MIN_PLAYERS_PER_POSITION
        ]

    @property
    def balanced(self) -> bool:
        return not self.thin_positions

    @property
    def warning(self) -> str:
        if self.balanced:
            return ""
        thin = ", ".join(self.thin_positions)
        return (
            f"The season-history prior covers {self.total} players but is thin at {thin}. "
            f"A player with a prior is judged on two seasons and one without is judged on this "
            f"gameweek alone, so an uneven prior quietly marks whole positions down. Run "
            f"scripts/fetch_history.py to fill it from the official API."
        )


def coverage(histories: dict[str, PlayerHistory] | None = None) -> Coverage:
    """Counts distinct players per position in the prior."""
    histories = load() if histories is None else histories
    seen: dict[str, set[str]] = {}
    for record in histories.values():
        if not record.usable:
            continue
        seen.setdefault(record.position or "?", set()).add(record.name)
    per_position = {position: len(names) for position, names in seen.items()}
    return Coverage(
        per_position=per_position,
        total=len({r.name for r in histories.values() if r.usable}),
    )
