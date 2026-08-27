"""What people are saying about the two teams in a fixture.

Player-level research answers "is he good?". It does not answer the
question that actually decides most gameweeks, which is "who is he
playing, and what do people say about them?" Those are different, and the
second one is club-level: *Brighton have the third-best defence in the
league and press high* is a fact about every attacker who faces Brighton
this week, not a fact about one of them. Written into a single player's
write-up it reaches a single player, and the app goes on recommending the
other ten in that fixture as though the opposition were neutral.

So matchup commentary lives here, keyed by fixture, and attaches to
everyone involved:

  * if you own an **attacker**, you get what people say about the
    opposition **defence**
  * if you own a **defender or keeper**, you get what people say about the
    opposition **attack**

Everything is attributed. A matchup note without a source is someone's
guess, and this app already has a rule about that.

This is deliberately not derived from the fixture-difficulty ratings. FDR
is a number and it flattens exactly the detail that changes a decision --
"a reshuffled back three missing two starters" and "solid, ranked 8th" can
carry the same rating and are not remotely the same problem to solve.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

MATCHUP_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "consensus"

# Positions that care about the opposition's defence rather than its attack.
ATTACKING_POSITIONS = ("MID", "FWD")


@dataclass
class Note:
    """One attributed observation about a club."""

    point: str
    source: str = ""

    @property
    def display(self) -> str:
        return f"{self.point} — *{self.source}*" if self.source else self.point


@dataclass
class ClubView:
    """What people say about one club's two halves."""

    attack: list[Note] = field(default_factory=list)
    defence: list[Note] = field(default_factory=list)


@dataclass
class Fixture:
    home: str
    away: str
    kickoff: str = ""
    headline: str = ""
    clubs: dict[str, ClubView] = field(default_factory=dict)

    def opponent_of(self, club: str) -> str | None:
        if club == self.home:
            return self.away
        if club == self.away:
            return self.home
        return None

    @property
    def label(self) -> str:
        return f"{self.home} v {self.away}"


def load(gameweek: int) -> list[Fixture]:
    """Reads this gameweek's matchup file, if one has been researched."""
    path = MATCHUP_DIR / f"matchups_gw{gameweek}.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []

    fixtures = []
    for entry in payload.get("fixtures", []):
        clubs = {}
        for club, view in (entry.get("clubs") or {}).items():
            clubs[str(club)] = ClubView(
                attack=[
                    Note(str(n.get("point", "")), str(n.get("source", "")))
                    for n in (view or {}).get("attack", [])
                    if n.get("point")
                ],
                defence=[
                    Note(str(n.get("point", "")), str(n.get("source", "")))
                    for n in (view or {}).get("defence", [])
                    if n.get("point")
                ],
            )
        try:
            fixtures.append(
                Fixture(
                    home=str(entry["home"]),
                    away=str(entry["away"]),
                    kickoff=str(entry.get("kickoff", "")),
                    headline=str(entry.get("headline", "")),
                    clubs=clubs,
                )
            )
        except KeyError:
            continue
    return fixtures


def fixture_for(club: str, fixtures: list[Fixture]) -> Fixture | None:
    for fixture in fixtures:
        if club in (fixture.home, fixture.away):
            return fixture
    return None


def opponent_notes(club: str, position: str, fixtures: list[Fixture]) -> list[Note]:
    """What people say about the half of the opposition that will decide this.

    An attacker is bought or avoided on the opposition's defence; a
    defender on the opposition's attack. Showing both to everyone would
    bury the relevant half in noise.
    """
    fixture = fixture_for(club, fixtures)
    if fixture is None:
        return []
    opponent = fixture.opponent_of(club)
    if opponent is None or opponent not in fixture.clubs:
        return []
    view = fixture.clubs[opponent]
    return view.defence if position in ATTACKING_POSITIONS else view.attack


def own_notes(club: str, position: str, fixtures: list[Fixture]) -> list[Note]:
    """What people say about the player's own side, from his point of view.

    A striker's own attack and a defender's own defence: the half of his
    team that has to function for him to score.
    """
    fixture = fixture_for(club, fixtures)
    if fixture is None or club not in fixture.clubs:
        return []
    view = fixture.clubs[club]
    return view.attack if position in ATTACKING_POSITIONS else view.defence


def summary(club: str, position: str, fixtures: list[Fixture]) -> str:
    """One line naming the fixture and the single loudest opposition point."""
    fixture = fixture_for(club, fixtures)
    if fixture is None:
        return ""
    opponent = fixture.opponent_of(club)
    where = "home to" if club == fixture.home else "away at"
    notes = opponent_notes(club, position, fixtures)
    line = f"{where} {opponent}"
    if fixture.kickoff:
        line += f" ({fixture.kickoff})"
    if notes:
        line += f". {notes[0].display}"
    return line
