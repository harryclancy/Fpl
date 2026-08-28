"""Why each player is in the squad, written out rather than scored.

The homepage used to answer "who starts" and leave "why" to a projection.
A projection is a conclusion: a reader can accept it or ignore it, but
they cannot argue with it, and arguing with it is the whole point of
owning the squad rather than having it handed to you.

So every one of the fifteen gets a written case, and the case is built
from the things a manager actually weighs:

  * what the player's job in the side currently is
  * whether he will be on the pitch
  * set pieces and penalties, which survive bad fixtures
  * who he plays this week and over the next few
  * what people are actually saying, attributed
  * the risk, stated rather than implied
  * why he beats the realistic alternative

Two rules keep this honest. Nothing is asserted that isn't in the data —
a player nobody researched gets a case that says so, rather than a
paragraph of confident filler. And a player who is only in the squad to
free up money is described that way, because "budget enabler" is a real
reason and dressing it up as a football argument insults the reader.
"""
from dataclasses import dataclass, field

import pandas as pd

from fpl_assistant.analysis import consensus, matchups

# Below this price a player in the squad is almost certainly there to make
# the money work rather than to score points, and saying so is more useful
# than inventing a footballing case for a fourth-choice defender.
ENABLER_PRICE = 4.5

# Ownership at or above this is effectively the template. Owning them
# protects rank rather than gaining it, which is worth saying out loud.
TEMPLATE_OWNERSHIP = 40.0


@dataclass
class PlayerCase:
    """The written argument for one player's place in the squad."""

    player_id: int
    name: str
    team: str
    position: str
    price: float
    ownership: float = 0.0
    starting: bool = False
    captain: bool = False
    vice_captain: bool = False

    role: str = ""
    set_pieces: str = ""
    predicted_start: str = ""
    fixture: str = ""
    fixture_run: list[str] = field(default_factory=list)
    record_vs: str = ""
    opposition_notes: list[str] = field(default_factory=list)
    arguments_for: list[tuple[str, str]] = field(default_factory=list)
    arguments_against: list[tuple[str, str]] = field(default_factory=list)
    dissent: str = ""
    prior_seasons: str = ""
    enabler: bool = False

    @property
    def header(self) -> str:
        return f"{self.name.upper()}"

    @property
    def subtitle(self) -> str:
        return f"{self.team} | {self.position} | £{self.price:.1f}m"

    @property
    def source_count(self) -> int:
        """Distinct outlets behind this case, for the quiet footer line."""
        names = {source for _, source in self.arguments_for + self.arguments_against if source}
        return len(names)

    @property
    def sources(self) -> list[str]:
        seen = []
        for _, source in self.arguments_for + self.arguments_against:
            if source and source not in seen:
                seen.append(source)
        return seen

    @property
    def researched(self) -> bool:
        return bool(self.arguments_for or self.arguments_against)

    @property
    def risk(self) -> str:
        """The honest health warning, or nothing.

        Separate from the arguments against so it cannot be buried at the
        bottom of a list. A minutes risk is not one consideration among
        several — it is the one that voids all the others.
        """
        if self.predicted_start == "out":
            return "**He is not expected to play.** Nothing else on this card matters until that changes."
        if self.predicted_start == "doubt":
            return "**Genuine doubt over whether he starts.** Check the late team news before the deadline."
        if self.predicted_start == "rotation risk":
            return "**Rotation risk.** He is good enough to start and may not."
        if self.arguments_against:
            return self.arguments_against[0][0]
        return ""

    def write_up(self) -> str:
        """The paragraph, assembled from what is actually known.

        Ordered the way a person explains a pick out loud: what he does,
        whether he'll play, what he's on, who he faces, what people say,
        and what could go wrong. Anything missing is skipped rather than
        padded, which is why two players' cards do not read the same.
        """
        parts: list[str] = []

        if self.enabler:
            parts.append(
                f"He is in the squad to make the budget work. At £{self.price:.1f}m he frees up "
                f"money for the players who actually score, and that is a real reason rather than "
                f"a footballing one — expect bench minutes, not returns."
            )

        if self.role:
            parts.append(f"His job in the side: {self.role}.")

        minutes = {
            "nailed": "He starts every week when fit, which is the foundation everything else rests on.",
            "likely": "He is expected to start, though it is not quite guaranteed.",
            "rotation risk": "Minutes are the concern here — he is a rotation risk rather than a certainty.",
            "doubt": "There is a real doubt over whether he features at all.",
            "out": "He is not expected to play.",
        }.get(self.predicted_start)
        if minutes:
            parts.append(minutes)

        if self.set_pieces:
            parts.append(
                f"He is on {self.set_pieces}. Dead-ball duty is the least fixture-dependent source "
                f"of points in the game — it survives a bad matchup and a quiet afternoon."
            )

        if self.prior_seasons:
            parts.append(f"Over full seasons: {self.prior_seasons}.")

        if self.arguments_for:
            point, source = self.arguments_for[0]
            parts.append(f"{point} ({source}).")
            if len(self.arguments_for) > 1:
                point, source = self.arguments_for[1]
                parts.append(f"{point} ({source}).")

        if self.record_vs:
            parts.append(f"Against this opponent specifically: {self.record_vs}")

        if self.opposition_notes:
            parts.append(f"On the opposition: {self.opposition_notes[0]}")

        if self.fixture_run:
            parts.append(f"His next few: {', '.join(self.fixture_run)}.")

        if self.ownership >= TEMPLATE_OWNERSHIP:
            parts.append(
                f"At {self.ownership:.0f}% ownership he is close to template — owning him protects "
                f"your rank rather than gaining it, and not owning him is the actual risk."
            )

        if self.dissent:
            parts.append(f"**Sources disagree here.** {self.dissent}")

        if not self.researched:
            parts.append(
                "No outlet has written about him this week, so this place is held on the projection "
                "alone. That is thinner evidence than the rest of the squad and worth knowing."
            )

        return " ".join(parts)


def _text(row: pd.Series, *columns: str) -> str:
    for column in columns:
        value = row.get(column)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def build(
    row: pd.Series,
    gameweek: int,
    fixtures: list | None = None,
    fixture_run: list[str] | None = None,
    starting: bool = False,
    captain: bool = False,
    vice_captain: bool = False,
) -> PlayerCase:
    club = str(row.get("team_short_name") or "")
    position = str(row.get("position") or "")
    fixtures = matchups.load(int(gameweek)) if fixtures is None else fixtures
    notes = matchups.opponent_notes(club, position, fixtures)
    price = float(row.get("price", 0) or 0)

    return PlayerCase(
        player_id=int(row["id"]),
        name=str(row.get("web_name") or ""),
        team=club,
        position=position,
        price=price,
        ownership=float(pd.to_numeric(row.get("selected_by_percent", 0), errors="coerce") or 0),
        starting=starting,
        captain=captain,
        vice_captain=vice_captain,
        role=_text(row, "role_note", "role"),
        set_pieces=_text(row, "set_pieces"),
        predicted_start=_text(row, "predicted_start"),
        fixture=matchups.summary(club, position, fixtures).split(".")[0],
        fixture_run=list(fixture_run or []),
        record_vs=_text(row, "record_vs_opponent"),
        opposition_notes=[note.display for note in notes[:2]],
        arguments_for=consensus.arguments_for(row),
        arguments_against=consensus.arguments_against(row),
        dissent=_text(row, "consensus_dissent"),
        prior_seasons=_text(row, "prior_seasons"),
        # An enabler is cheap AND benched. A cheap starter is a bargain,
        # which is a completely different thing and must not be described
        # as though he were there to pad the budget.
        enabler=price <= ENABLER_PRICE and not starting,
    )


def captaincy_reasoning(case: PlayerCase, alternative: PlayerCase | None = None) -> str:
    """Why the armband is going here rather than to the obvious rival."""
    if not (case.captain or case.vice_captain):
        return ""

    # Written out rather than derived with .title(), which capitalises
    # after the hyphen and produces "Vice-Captaincy".
    label = "Captaincy" if case.captain else "Vice-captaincy"
    parts = [f"**{label} reasoning.**"]

    if case.arguments_for:
        parts.append(case.arguments_for[0][0].rstrip(".") + f" ({case.arguments_for[0][1]}).")
    if case.record_vs:
        parts.append(f"Against this opponent: {case.record_vs}")
    if case.opposition_notes:
        parts.append(case.opposition_notes[0])

    if case.ownership >= TEMPLATE_OWNERSHIP:
        parts.append(
            f"At {case.ownership:.0f}% owned this is the safe armband rather than the clever one — "
            f"it protects rank more than it gains it, which in most weeks is the right trade."
        )
    else:
        parts.append(
            f"At {case.ownership:.0f}% owned this is a genuine differential armband. It gains ground "
            f"if it lands and costs ground if it doesn't, so take it deliberately rather than by accident."
        )

    if alternative is not None:
        parts.append(
            f"The obvious alternative is {alternative.name}; he is the pick if you would rather "
            f"track the field than move against it."
        )
    if case.risk:
        parts.append(f"Risk: {case.risk}")
    return " ".join(parts)
