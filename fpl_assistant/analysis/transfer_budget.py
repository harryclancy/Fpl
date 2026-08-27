"""How many transfers to make this week, decided rather than asked.

The app used to put a slider on the page -- "most transfers to consider,
1 to 4" -- and let the reader pick. That is the wrong division of labour.
Choosing how many transfers to make is a judgement about how much damage
your squad has taken and how much a hit is worth, which is exactly the
kind of thing the app has the information to work out and the reader
mostly does not. A slider there is the app declining to do its job and
calling it flexibility.

The rule, in plain terms: **two transfers is the ceiling in a normal
week.** Beyond that you are paying four points a move to chase a squad
that was probably fine, and the season-long evidence is that churn loses
more than it gains. The exception is chaos -- when enough of your fifteen
is actually broken that patching it is not optional:

  * players who cannot play at all (injured, suspended, out on loan)
  * players flagged as serious doubts
  * players whose club has been written off by the research this week
  * players who have simply lost their place

Chaos is counted, not felt. Each unavailable body raises the ceiling by
one, because a transfer that replaces a zero is not a churn, it is a
repair -- and the same 4-point hit buys far more when the alternative is
fielding ten men.
"""
from dataclasses import dataclass

import pandas as pd

# The ceiling in a week where nothing has gone wrong.
NORMAL_MAX_TRANSFERS = 2

# The hard ceiling however bad it gets. Beyond four you are wildcarding,
# and the honest advice at that point is "play the chip", not "take a
# 20-point hit".
ABSOLUTE_MAX_TRANSFERS = 4

# Availability below this counts the player as effectively missing.
DOUBT_THRESHOLD = 50.0

# FPL status codes that mean the player cannot play at all.
UNAVAILABLE_STATUSES = ("i", "s", "u", "n")


@dataclass
class TransferBudget:
    """How many transfers this week can justify, and why."""

    limit: int
    free_transfers: int
    broken: list[str]
    reason: str

    @property
    def is_chaos(self) -> bool:
        return self.limit > NORMAL_MAX_TRANSFERS

    @property
    def headline(self) -> str:
        if not self.is_chaos:
            return f"Considering up to {self.limit} transfer{'s' if self.limit > 1 else ''}."
        return (
            f"Considering up to {self.limit} transfers — "
            f"{len(self.broken)} of your fifteen can't be relied on this week."
        )


def _broken_players(squad: pd.DataFrame) -> list[str]:
    """Players in the squad who cannot be counted on to play.

    Deliberately generous about what counts. A 50%-doubtful player and an
    injured one are different in the abstract and identical in the way
    that matters here: you cannot plan an eleven around either.
    """
    if squad.empty:
        return []

    names = squad.get("web_name", pd.Series(dtype=str))
    broken: list[str] = []

    status = squad.get("status")
    if status is not None:
        for name, value in zip(names, status.fillna("a")):
            if str(value) in UNAVAILABLE_STATUSES:
                broken.append(str(name))

    chance = pd.to_numeric(
        squad.get("chance_of_playing_next_round", pd.Series(dtype=float)), errors="coerce"
    )
    if not chance.empty:
        for name, value in zip(names, chance):
            if pd.notna(value) and value <= DOUBT_THRESHOLD and str(name) not in broken:
                broken.append(str(name))

    # A club the research has written off is a squad problem too, even
    # when every individual is nominally fit -- "avoid this defence" is
    # advice about the returns, not about availability.
    stance = squad.get("club_stance")
    if stance is not None:
        for name, value in zip(names, stance.fillna("")):
            if str(value) == "avoid" and str(name) not in broken:
                broken.append(str(name))

    return broken


def decide(
    squad: pd.DataFrame,
    free_transfers: int = 1,
    normal_max: int = NORMAL_MAX_TRANSFERS,
    absolute_max: int = ABSOLUTE_MAX_TRANSFERS,
) -> TransferBudget:
    """Works out this week's transfer ceiling from the state of the squad.

    Never returns fewer than the free transfers available: banking is a
    decision the optimiser is entitled to make, but the ceiling should
    never stop it from spending transfers that cost nothing.
    """
    broken = _broken_players(squad)
    limit = max(normal_max, min(absolute_max, normal_max + len(broken) - 1) if broken else normal_max)
    limit = min(limit, absolute_max)
    limit = max(limit, min(free_transfers, absolute_max))

    if not broken:
        reason = (
            f"Nothing in your fifteen is injured, suspended or flagged, so this is a normal "
            f"week — capped at {limit}. Beyond two moves you're paying four points each to "
            f"churn a squad that's fine, which is how a good season becomes an average one."
        )
    elif limit <= normal_max:
        reason = (
            f"{', '.join(broken)} can't be relied on, but one problem is a one-transfer "
            f"problem — still capped at {limit}."
        )
    else:
        reason = (
            f"{len(broken)} of your fifteen can't be relied on ({', '.join(broken)}), so the "
            f"cap goes up to {limit}. A transfer that replaces a zero isn't churn, it's a "
            f"repair, and the same hit buys far more when the alternative is fielding ten men."
        )

    return TransferBudget(
        limit=int(limit),
        free_transfers=int(free_transfers),
        broken=broken,
        reason=reason,
    )
