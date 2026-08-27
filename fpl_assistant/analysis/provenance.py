"""Where a recommendation's confidence actually comes from.

A player with five outlets behind him and a player nobody has written
about look identical in a squad list — one just has more text underneath.
That is the same failure as a player who was weighed and rejected looking
like one that was never considered: the reader can't tell which they're
looking at, so they can't calibrate how much to trust it.

So each player carries a visible marker of what's behind him: research
from this gameweek, research from an earlier one, or the projection alone.
None of these is bad. Numbers-only is a perfectly good basis for a
sixth-choice bench defender. It is a much weaker basis for the armband,
and the difference should be on the page rather than in the reader's
assumptions.
"""
from dataclasses import dataclass

import pandas as pd

FRESH = "fresh"
STALE = "stale"
NUMBERS = "numbers"

LABELS = {
    FRESH: ("🟢", "Researched this gameweek"),
    STALE: ("🟡", "Researched earlier — re-check before the deadline"),
    NUMBERS: ("⚪", "Projection only — no analyst has written about him"),
}

BLURBS = {
    FRESH: "Backed by this week's research, with named sources.",
    STALE: (
        "Backed by research from an earlier gameweek. Team news and prices move fast, "
        "so treat the write-up as context rather than as current."
    ),
    NUMBERS: (
        "No analyst coverage — this is the projection on its own. Fine for a squad filler, "
        "thinner ground for a captaincy or a transfer."
    ),
}


@dataclass
class Provenance:
    level: str
    researched_gameweek: int | None = None

    @property
    def icon(self) -> str:
        return LABELS[self.level][0]

    @property
    def label(self) -> str:
        return LABELS[self.level][1]

    @property
    def blurb(self) -> str:
        return BLURBS[self.level]


def for_player(row: pd.Series, gameweek: int) -> Provenance:
    """What's behind this player, from the columns the consensus layer adds."""
    tier = row.get("consensus_tier")
    if not isinstance(tier, str) or not tier:
        return Provenance(NUMBERS)

    source_gw = pd.to_numeric(row.get("consensus_gameweek"), errors="coerce")
    if source_gw is None or pd.isna(source_gw):
        # Older files didn't stamp the gameweek. Treat unknown as current
        # rather than as stale: the annotation only loads from this
        # gameweek's file in the first place.
        return Provenance(FRESH, gameweek)
    source_gw = int(source_gw)
    return Provenance(FRESH if source_gw >= gameweek else STALE, source_gw)


def summarise(scored: pd.DataFrame, player_ids, gameweek: int) -> dict[str, int]:
    """How many of these players sit at each level of backing."""
    indexed = scored.set_index("id", drop=False)
    counts = {FRESH: 0, STALE: 0, NUMBERS: 0}
    for pid in player_ids:
        if pid not in indexed.index:
            counts[NUMBERS] += 1
            continue
        counts[for_player(indexed.loc[pid], gameweek).level] += 1
    return counts
