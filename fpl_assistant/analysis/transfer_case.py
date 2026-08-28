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
    # The next few gameweeks as opponents, not as a difficulty number. A
    # rating of 2.8 tells you nothing you can argue with; "Ipswich (H),
    # Coventry (A), Hull (H)" tells you everything.
    fixture_run: list[str] = field(default_factory=list)
    fixture_difficulty: list[float] = field(default_factory=list)
    predicted_start: str = ""
    set_pieces: str = ""
    role: str = ""

    @property
    def label(self) -> str:
        return f"{self.name} ({self.team}, £{self.price:.1f}m)"

    @property
    def run_text(self) -> str:
        return ", ".join(self.fixture_run) if self.fixture_run else ""

    @property
    def good_run(self) -> bool:
        """Whether the fixture run is genuinely favourable, not just the
        next one. Judged over the whole window, because buying a player
        for one fixture is how you end up transferring him straight back."""
        if not self.fixture_difficulty:
            return False
        return sum(self.fixture_difficulty) / len(self.fixture_difficulty) <= 2.9

    @property
    def minutes_risk(self) -> bool:
        return self.predicted_start in ("rotation risk", "doubt", "out")


@dataclass
class TransferCase:
    """Why one player is going out and another coming in.

    Structured rather than free prose because the four questions a manager
    actually asks are always the same, and a paragraph that answers three
    of them and quietly skips the fourth reads as complete. Why sell him,
    why buy him, why THIS swap rather than the obvious alternatives, and
    what it does to the next month.
    """

    out: Side
    into: Side
    gain: float = 0.0
    researched: bool = True
    horizon_gain: float = 0.0
    free_transfers: int = 1
    alternative: str = ""
    bank_after: float | None = None
    # Why this player is the one leaving, rather than someone else in the
    # squad. Filled from the sell-urgency ranking. A transfer that cannot
    # survive this sentence should not be recommended.
    why_not_instead: str = ""

    @property
    def hit_required(self) -> bool:
        return self.free_transfers < 1

    @property
    def confidence(self) -> str:
        """How much to trust this call, derived rather than asserted.

        Deliberately hard to reach "High": it needs the incoming player to
        be researched, to be a reliable starter, to have a fixture run
        rather than one good game, and to gain over the horizon and not
        just this weekend. Anything less is Medium at best, and an
        unresearched swap is always Low however good the numbers look.
        """
        if not self.researched:
            return "Low"
        if self.into.minutes_risk:
            return "Low"
        strong = [
            bool(self.into.reasons),
            self.into.good_run,
            self.horizon_gain > 0,
            self.into.predicted_start == "nailed",
        ]
        if all(strong):
            return "High"
        return "Medium" if sum(strong) >= 2 else "Low"

    @property
    def roll_instead(self) -> bool:
        """Whether banking the transfer is the better call.

        Preserving a transfer has real value — it buys the option to react
        to team news next week — so the bar for spending one is that the
        move pays over the horizon, not just this Saturday.
        """
        if self.into.minutes_risk:
            return True
        if not self.researched:
            return True
        return self.horizon_gain <= 0

    @property
    def roll_verdict(self) -> str:
        if self.roll_instead:
            if self.into.minutes_risk:
                return (
                    f"**Yes — roll it.** {self.into.name} is not a certain starter "
                    f"({self.into.predicted_start or 'minutes unclear'}), and spending a free "
                    f"transfer on a player who might not play is the worst use of one."
                )
            if not self.researched:
                return (
                    "**Yes — roll it.** Nobody has written about either player this week, so this "
                    "is the model talking to itself. Banking the transfer keeps the option open "
                    "until there is a reason to act."
                )
            return (
                f"**Yes — roll it.** The move gains {self.gain:+.1f} this week but "
                f"{self.horizon_gain:+.1f} over the horizon, which means you would likely be "
                f"transferring back out again. A banked transfer is worth more than a marginal upgrade."
            )
        return (
            f"**No — make the move.** It gains {self.gain:+.1f} this week and "
            f"{self.horizon_gain:+.1f} across the run, so it is not a one-week fix you have to undo."
        )

    @property
    def short_term(self) -> str:
        parts = [f"{self.into.name} projects {self.gain:+.1f} points on {self.out.name} this gameweek."]
        if self.into.fixture_run:
            parts.append(f"He faces {self.into.fixture_run[0]}.")
        if self.out.fixture_run:
            parts.append(f"{self.out.name} faces {self.out.fixture_run[0]}.")
        if self.hit_required:
            parts.append("This costs a 4-point hit, which the gain has to clear before it is worth doing.")
        return " ".join(parts)

    @property
    def look_ahead(self) -> str:
        """What the swap means over the next few gameweeks.

        The section that stops a transfer being made for one Saturday. If
        the incoming player's run turns immediately, this says so.
        """
        parts = []
        if self.into.run_text:
            parts.append(f"{self.into.name}'s run: {self.into.run_text}.")
        if self.out.run_text:
            parts.append(f"{self.out.name}'s: {self.out.run_text}.")
        if self.into.good_run and not self.out.good_run:
            parts.append(
                "That is the case in one line — you are buying into the better run and selling out "
                "of the worse one, which is what stops this being a move you undo in a fortnight."
            )
        elif self.out.good_run and not self.into.good_run:
            parts.append(
                "⚠️ Note the direction: the player leaving has the better run of the two. This is a "
                "move for this week that you may well want to reverse, which is usually a reason not "
                "to make it."
            )
        elif not self.into.good_run:
            parts.append(
                "Neither run is especially kind, so this is not a fixture-swing move — it has to be "
                "justified on role and form alone."
            )
        if self.bank_after is not None:
            parts.append(f"It leaves £{self.bank_after:.1f}m in the bank for the next move.")
        return " ".join(parts)

    @property
    def headline(self) -> str:
        return f"{self.out.label} → {self.into.label}"

    @property
    def why_this_swap(self) -> str:
        """Why this pair, rather than holding or doing something else.

        The question the old version skipped. A reader can always see that
        the incoming player is projected higher; what they cannot see is
        why he beats the other things you could do with the same transfer.
        """
        lines = []
        if self.into.reasons and self.out.reasons:
            lines.append(
                f"The swap works because the two arguments point the same way: "
                f"{self.out.reasons[0][0].rstrip('.')}, while {self.into.reasons[0][0][0].lower()}"
                f"{self.into.reasons[0][0][1:].rstrip('.')}."
            )
        if self.into.set_pieces:
            lines.append(
                f"{self.into.name} is on {self.into.set_pieces}, which is the most fixture-proof "
                f"source of points there is — it survives a bad matchup in a way open play does not."
            )
        if self.out.minutes_risk:
            lines.append(
                f"{self.out.name} is a minutes problem ({self.out.predicted_start}), and replacing a "
                f"player who might not start is a repair rather than a churn."
            )
        if self.alternative:
            lines.append(f"**The strongest alternative** is {self.alternative}")
        if self.roll_instead:
            lines.append(
                "On balance, though, holding the transfer beats making this one — see below."
            )
        return " ".join(lines) if lines else (
            f"There is no researched case for preferring {self.into.name} beyond the projection, "
            f"which is not enough on its own to spend a transfer."
        )

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


def _fixture_run(row: pd.Series, fixture_table, gameweek: int, weeks: int) -> tuple[list, list]:
    """The next few opponents by name, and their difficulty ratings.

    Names rather than a single averaged rating, because "Ipswich (H),
    Coventry (A)" is something a reader can weigh and "2.4" is something
    they can only accept.
    """
    if fixture_table is None or "team" not in row.index:
        return [], []
    team_id = row.get("team")
    if team_id not in getattr(fixture_table, "index", []):
        return [], []
    names, diffs = [], []
    for gw in range(int(gameweek), int(gameweek) + weeks):
        if gw in fixture_table.columns:
            value = fixture_table.loc[team_id, gw]
            if isinstance(value, str) and value != "-":
                names.append(f"GW{gw} {value}")
        key = f"{gw}_difficulty"
        if key in fixture_table.columns:
            try:
                diffs.append(float(fixture_table.loc[team_id, key]))
            except (TypeError, ValueError):
                pass
    return names, diffs


def _side(
    row: pd.Series,
    fixtures: list,
    reasons: list[tuple[str, str]],
    projection_column: str,
    fixture_table=None,
    gameweek: int = 1,
    weeks: int = 4,
) -> Side:
    club = str(row.get("team_short_name") or "")
    position = str(row.get("position") or "")
    notes = matchups.opponent_notes(club, position, fixtures)
    run, diffs = _fixture_run(row, fixture_table, gameweek, weeks)

    def text(column: str) -> str:
        value = row.get(column)
        return str(value) if isinstance(value, str) and value.strip() else ""

    return Side(
        fixture_run=run,
        fixture_difficulty=diffs,
        predicted_start=text("predicted_start"),
        set_pieces=text("set_pieces"),
        role=text("role_note") or text("role"),
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


# How far ahead a transfer has to make sense. One good fixture is how you
# end up transferring a player straight back out; four is long enough for a
# fixture swing to show and short enough to still be forecastable.
LOOKAHEAD_GAMEWEEKS = 4


def explain(
    scored: pd.DataFrame,
    out_id: int,
    in_id: int,
    gameweek: int,
    projection_column: str = "xp_next",
    fixture_table=None,
    horizon_column: str = "xp_horizon",
    free_transfers: int = 1,
    alternative: str = "",
    bank_after: float | None = None,
    weeks: int = LOOKAHEAD_GAMEWEEKS,
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

    out_side = _side(out_row, fixtures, consensus.arguments_against(out_row),
                     projection_column, fixture_table, gameweek, weeks)
    in_side = _side(in_row, fixtures, consensus.arguments_for(in_row),
                    projection_column, fixture_table, gameweek, weeks)

    def horizon(row) -> float:
        try:
            return float(row.get(horizon_column, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    return TransferCase(
        out=out_side,
        into=in_side,
        gain=round(in_side.projected - out_side.projected, 2),
        horizon_gain=round(horizon(in_row) - horizon(out_row), 2),
        free_transfers=int(free_transfers),
        alternative=alternative,
        bank_after=bank_after,
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
    fixture_table=None,
    free_transfers: int = 1,
    bank_after: float | None = None,
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
        case = explain(
            scored, out_id, in_id, gameweek, projection_column,
            fixture_table=fixture_table,
            free_transfers=free_transfers,
            alternative=_best_alternative(scored, out_id, in_id, projection_column),
            bank_after=bank_after,
        )
        if case is not None:
            cases.append(case)
    return cases


def _best_alternative(
    scored: pd.DataFrame, out_id: int, in_id: int, projection_column: str
) -> str:
    """The next-best player you could buy with the same sale.

    Named rather than described, because "there were other options" is not
    information — "Semenyo at the same price projects 0.4 less but has the
    better run" is. Restricted to the same position and roughly the same
    money, since anything else is not the same decision.
    """
    indexed = scored.set_index("id", drop=False) if scored.index.name != "id" else scored
    if out_id not in indexed.index or in_id not in indexed.index:
        return ""
    chosen = indexed.loc[in_id]
    if isinstance(chosen, pd.DataFrame):
        chosen = chosen.iloc[0]

    same = scored[
        (scored["position"] == chosen.get("position"))
        & (scored["id"] != in_id)
        & (scored["id"] != out_id)
        & (scored["price"] <= float(chosen.get("price", 0)) + 0.5)
    ]
    if same.empty:
        return ""
    runner_up = same.sort_values(projection_column, ascending=False).iloc[0]
    gap = float(chosen.get(projection_column, 0)) - float(runner_up.get(projection_column, 0))
    reasons = consensus.arguments_for(runner_up)
    line = (
        f"{runner_up['web_name']} ({runner_up.get('team_short_name')}, "
        f"£{float(runner_up.get('price', 0)):.1f}m), who projects {gap:.1f} lower"
    )
    if reasons:
        line += f" — {reasons[0][0].rstrip('.')}"
    return line + "."
