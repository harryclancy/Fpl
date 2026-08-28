"""The argument for a transfer, in words rather than in points.

A transfer recommendation that says "Smith → Jones, +2.3 projected" tells
you what the solver concluded and nothing about why. You cannot agree
with it, disagree with it, or sanity-check it -- you can only obey it or
ignore it, and most people sensibly ignore it.

What a manager actually wants to read is the case: what has gone wrong
with the player leaving, what people are saying about the one arriving,
who they are each playing this week and what that means, and whether the
incoming player has any history of doing this against this opponent.
Every one of those is already researched somewhere in this repo. This
module's whole job is to assemble them into an argument.

Nothing here invents anything. If the research doesn't carry a reason,
this says so rather than dressing a points differential up as insight --
"the numbers prefer him and nobody has written about either player" is an
honest thing to tell someone, and it is a signal to go and research
before acting.
"""
from dataclasses import dataclass, field

import pandas as pd

from fpl_assistant.analysis import consensus, matchups

# How many arguments to show per side. More than this and the case stops
# reading like a case and starts reading like a dump.
MAX_POINTS_PER_SIDE = 3


@dataclass
class Side:
    """One half of a transfer: the player, and why he's moving."""

    player_id: int
    name: str
    team: str
    position: str
    price: float
    projected: float
    reasons: list[tuple[str, str]] = field(default_factory=list)
    fixture: str = ""
    opposition: list[str] = field(default_factory=list)
    record: str = ""
    ownership: float = 0.0

    @property
    def label(self) -> str:
        return f"{self.name} ({self.team}, £{self.price:.1f}m)"


@dataclass
class TransferCase:
    """Why one player is going out and another coming in."""

    out: Side
    into: Side
    gain: float = 0.0
    researched: bool = True

    @property
    def headline(self) -> str:
        return f"{self.out.label} → {self.into.label}"

    @property
    def summary(self) -> str:
        """One sentence a person would actually say out loud."""
        if not self.researched:
            return (
                f"{self.into.name} projects higher than {self.out.name}, but nobody has "
                f"written about either of them this week — this one is the model's opinion "
                f"alone, so treat it as a suggestion to go and check rather than a call."
            )
        if self.into.reasons and self.out.reasons:
            return (
                f"{self.out.reasons[0][0]} Meanwhile, {self.into.reasons[0][0].rstrip('.')} "
                f"— which is the swap."
            )
        if self.into.reasons:
            return self.into.reasons[0][0]
        if self.out.reasons:
            return self.out.reasons[0][0]
        return f"{self.into.name} projects {self.gain:+.1f} points ahead of {self.out.name}."


def _side(
    row: pd.Series,
    fixtures: list,
    reasons: list[tuple[str, str]],
    projection_column: str,
) -> Side:
    club = str(row.get("team_short_name") or "")
    position = str(row.get("position") or "")
    notes = matchups.opponent_notes(club, position, fixtures)
    return Side(
        player_id=int(row["id"]),
        name=str(row.get("web_name") or ""),
        team=club,
        position=position,
        price=float(row.get("price", 0) or 0),
        projected=float(row.get(projection_column, 0) or 0),
        reasons=reasons[:MAX_POINTS_PER_SIDE],
        fixture=matchups.summary(club, position, fixtures).split(".")[0],
        opposition=[note.display for note in notes[:MAX_POINTS_PER_SIDE]],
        record=str(row.get("record_vs_opponent") or ""),
        ownership=float(pd.to_numeric(row.get("selected_by_percent", 0), errors="coerce") or 0),
    )


def explain(
    scored: pd.DataFrame,
    out_id: int,
    in_id: int,
    gameweek: int,
    projection_column: str = "xp_next",
) -> TransferCase | None:
    """Assembles the case for one swap.

    The asymmetry is deliberate. The player leaving is explained by what
    people say AGAINST him -- that is the reason he's going. The player
    arriving is explained by what people say FOR him. Showing both sides
    of both players would be balanced and useless; the question on the
    table is "why this swap", not "rate these two men".
    """
    indexed = scored.set_index("id", drop=False) if scored.index.name != "id" else scored
    if out_id not in indexed.index or in_id not in indexed.index:
        return None

    out_row = indexed.loc[out_id]
    in_row = indexed.loc[in_id]
    if isinstance(out_row, pd.DataFrame):
        out_row = out_row.iloc[0]
    if isinstance(in_row, pd.DataFrame):
        in_row = in_row.iloc[0]

    fixtures = matchups.load(int(gameweek))

    out_side = _side(out_row, fixtures, consensus.arguments_against(out_row), projection_column)
    in_side = _side(in_row, fixtures, consensus.arguments_for(in_row), projection_column)

    return TransferCase(
        out=out_side,
        into=in_side,
        gain=round(in_side.projected - out_side.projected, 2),
        # "Researched" means somebody wrote about at least one of these
        # PLAYERS. Fixture-level commentary deliberately does not count,
        # even though it is attached and shown: knowing that Brighton
        # defend well tells you nothing about whether to buy a particular
        # Brighton midfielder, and the summary this flag controls says in
        # plain words that "nobody has written about either of them".
        # Letting matchup notes satisfy it would make that sentence false
        # every week the fixture happened to be covered.
        researched=bool(out_side.reasons or in_side.reasons),
    )


def explain_plan(
    scored: pd.DataFrame,
    out_ids: list[int],
    in_ids: list[int],
    gameweek: int,
    projection_column: str = "xp_next",
) -> list[TransferCase]:
    """Cases for a whole transfer plan, paired in the order given.

    The optimiser returns two unordered sets, and pairing them by position
    is what makes them read as swaps rather than as a shopping list --
    "sell the defender, buy the defender" is a sentence; "sell these two,
    buy these two" is not.
    """
    indexed = scored.set_index("id", drop=False) if scored.index.name != "id" else scored

    def position_of(player_id: int) -> str:
        if player_id not in indexed.index:
            return ""
        row = indexed.loc[player_id]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        return str(row.get("position") or "")

    remaining = list(in_ids)
    pairs = []
    for out_id in out_ids:
        position = position_of(out_id)
        match = next((i for i in remaining if position_of(i) == position), None)
        if match is None:
            match = remaining[0] if remaining else None
        if match is None:
            break
        remaining.remove(match)
        pairs.append((out_id, match))

    cases = []
    for out_id, in_id in pairs:
        case = explain(scored, out_id, in_id, gameweek, projection_column)
        if case is not None:
            cases.append(case)
    return cases
