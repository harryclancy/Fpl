"""Expected minutes, built from selection evidence rather than from quotes.

The flaw this fixes: the engine only counted a player's minutes as
"assessed" if a retrieved article discussed his selection. Three days
before a deadline almost nothing does, so all fifteen players came back
UNASSESSED and every downstream score was flattened by the same +6
penalty. The ranking that produced was not wrong so much as uninformed.

But a team sheet IS evidence. A player who has started every league game
and played ninety minutes each time has told you more about his expected
minutes than a press conference ever will. So minutes are assessed in two
layers:

  BASE      from appearances, starts and minutes actually played
  MODIFIED  by current news — a knock, an omission, a suspension, a
            transfer saga — which can only ever move the base downwards
            or confirm it

That ordering matters. Deadline-day team news refines a picture; it does
not create one from nothing. And UNASSESSED now means what it says: no
appearance record AND no reporting, which is a genuinely new signing or a
player who has not featured at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field

VERY_SECURE = "Very secure"
SECURE = "Secure"
SLIGHT = "Slight concern"
SIGNIFICANT = "Significant concern"
MAJOR_DOUBT = "Major doubt"
UNASSESSED = "Unassessed"

# Ordered worst-last so a modifier can only ever move a player down the
# list, never invent security he has not earned.
LADDER = (VERY_SECURE, SECURE, SLIGHT, SIGNIFICANT, MAJOR_DOUBT)

# How much of a player's projected points to expect, per category. These
# are multipliers on a projection that already assumes he plays.
CONFIDENCE = {
    VERY_SECURE: 1.0,
    SECURE: 0.92,
    SLIGHT: 0.78,
    SIGNIFICANT: 0.55,
    MAJOR_DOUBT: 0.3,
    UNASSESSED: 0.6,
}

# A full game. Used to tell a starter from a player who comes on.
FULL_GAME_MINUTES = 80
# Below this many team games there is not enough of a record to lean on,
# so the base is held at SLIGHT rather than asserted either way.
MIN_GAMES_FOR_BASE = 2


@dataclass
class MinutesAssessment:
    """One player's expected minutes, and the evidence for it."""

    category: str = UNASSESSED
    base: str = UNASSESSED
    start_rate: float = 0.0
    average_minutes: float = 0.0
    starts: int = 0
    appearances: int = 0
    reasons: list[str] = field(default_factory=list)
    modifiers: list[str] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        return CONFIDENCE.get(self.category, 0.6)

    @property
    def assessed(self) -> bool:
        return self.category != UNASSESSED

    @property
    def secure(self) -> bool:
        return self.category in (VERY_SECURE, SECURE)

    def as_dict(self) -> dict:
        return {
            "category": self.category, "base": self.base,
            "start_rate": round(self.start_rate, 2),
            "average_minutes": round(self.average_minutes, 1),
            "starts": self.starts, "appearances": self.appearances,
            "confidence": self.confidence,
            "reasons": self.reasons, "modifiers": self.modifiers,
        }


def _downgrade(category: str, steps: int = 1) -> str:
    if category not in LADDER:
        return category
    index = min(len(LADDER) - 1, LADDER.index(category) + steps)
    return LADDER[index]


def base_from_appearances(starts: int, appearances: int, minutes: int,
                          team_games: int) -> MinutesAssessment:
    """The selection record, read as evidence about the next team sheet."""
    result = MinutesAssessment(starts=starts, appearances=appearances)
    if team_games <= 0 or (appearances == 0 and starts == 0 and minutes == 0):
        result.reasons.append("no appearances recorded this season")
        return result

    result.start_rate = starts / team_games if team_games else 0.0
    result.average_minutes = minutes / appearances if appearances else 0.0

    if team_games < MIN_GAMES_FOR_BASE:
        result.base = result.category = SLIGHT
        result.reasons.append(
            f"only {team_games} team game(s) played — too little record to lean on")
        return result

    rate, average = result.start_rate, result.average_minutes
    if rate >= 0.9 and average >= FULL_GAME_MINUTES:
        category = VERY_SECURE
    elif rate >= 0.7:
        category = SECURE
    elif rate >= 0.45:
        category = SLIGHT
    elif rate >= 0.2 or appearances:
        category = SIGNIFICANT
    else:
        category = MAJOR_DOUBT

    result.base = result.category = category
    result.reasons.append(
        f"started {starts} of {team_games} team games "
        f"({rate:.0%}), averaging {average:.0f} minutes per appearance")
    return result


def assess(starts: int, appearances: int, minutes: int, team_games: int,
           status: str = "a", chance_of_playing: float | None = None,
           injury_talk: bool = False, omission_talk: bool = False,
           suspension: bool = False, rotation_talk: bool = False,
           transfer_talk: bool = False, positive_team_news: bool = False,
           ) -> MinutesAssessment:
    """Base expected minutes, then whatever the current news does to it.

    News only moves the assessment down, with one exception: positive team
    news confirms a base that already looked secure. It cannot promote a
    fringe player to nailed on, because an article saying somebody trained
    is not the same as him being picked.
    """
    result = base_from_appearances(starts, appearances, minutes, team_games)

    if suspension:
        result.category = MAJOR_DOUBT
        result.modifiers.append("suspended")
        return result
    if status != "a":
        result.category = _downgrade(result.category, 2)
        result.modifiers.append("flagged as unavailable in the official data")
    if chance_of_playing is not None:
        if chance_of_playing <= 25:
            result.category = MAJOR_DOUBT
            result.modifiers.append(f"chance of playing {chance_of_playing:.0f}%")
        elif chance_of_playing <= 75:
            result.category = _downgrade(result.category, 2)
            result.modifiers.append(f"chance of playing {chance_of_playing:.0f}%")

    if injury_talk:
        result.category = _downgrade(result.category)
        result.modifiers.append("injury reported in this week's coverage")
    if omission_talk:
        result.category = _downgrade(result.category)
        result.modifiers.append("recent squad omission reported")
    if rotation_talk:
        result.category = _downgrade(result.category)
        result.modifiers.append("rotation risk raised in the coverage")
    if transfer_talk:
        result.category = _downgrade(result.category)
        result.modifiers.append("transfer speculation may affect selection")

    if positive_team_news and result.category == result.base and result.secure:
        result.modifiers.append("team news confirms the selection record")

    # A player with no record at all stays unassessed unless the news
    # itself is the evidence — a new signing everyone is writing about.
    if result.base == UNASSESSED and not result.modifiers:
        result.category = UNASSESSED
    return result
