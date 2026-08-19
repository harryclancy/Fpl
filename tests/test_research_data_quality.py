"""Lints the shipped research files.

The recurring failure in this project is not arithmetic, it's the research
layer. The maths is tested; the football facts are hand-entered, and they
have been wrong more than once. Worse, the specific bug that prompted this
file was invisible from the inside: club-wide advice ("avoid Bournemouth
assets until the schedule clears") was typed into one player's prose,
where it read perfectly to a human and reached nothing but that one
player.

So these tests run over the real data/consensus files, not fixtures. They
cannot check whether a football claim is true -- nothing here can -- but
they can check the claims are *stored where they will actually be used*,
which is the failure that keeps happening. Every rule below exists because
something went wrong in that shape.
"""
import json
import re
from pathlib import Path

import pytest

from fpl_assistant.analysis import consensus

DATA = Path(__file__).resolve().parent.parent / "data" / "consensus"
PLAYER_FILES = sorted(DATA.glob("gw*.json"))
TEAM_FILE = DATA / "teams.json"

VALID_TIERS = set(consensus.TIER_BONUS)
VALID_STANCES = set(consensus.CLUB_STANCE_BONUS)
VALID_POSITIONS = set(consensus.ALL_POSITIONS)


def _players(path: Path) -> list[dict]:
    return json.loads(path.read_text()).get("players", [])


def _teams() -> list[dict]:
    return json.loads(TEAM_FILE.read_text()).get("teams", [])


# --- the bug that started this ------------------------------------------

# Prose that is making a claim about a whole club rather than one player.
# "avoid Bournemouth assets", "Bournemouth's opening run is the worst in
# the league", "avoid Coventry defenders".
CLUB_WIDE_PROSE = re.compile(
    r"avoid\s+(?:all\s+)?(?P<club>[A-Z][a-zA-Z']+(?:\s+[A-Z][a-zA-Z']+)?)"
    r"\s+(?:assets|players|defenders|attackers|midfielders)",
    re.IGNORECASE,
)

# Maps the long names analysts write to the FPL short names teams.json is
# keyed by. Only clubs a stance might plausibly be written about.
CLUB_ALIASES = {
    "bournemouth": "BOU", "coventry": "COV", "hull": "HUL", "hull city": "HUL",
    "ipswich": "IPS", "sunderland": "SUN", "arsenal": "ARS", "chelsea": "CHE",
    "everton": "EVE", "brentford": "BRE", "newcastle": "NEW", "liverpool": "LIV",
    "man city": "MCI", "manchester city": "MCI", "man utd": "MUN",
    "manchester united": "MUN", "spurs": "TOT", "tottenham": "TOT",
    "aston villa": "AVL", "crystal palace": "CRY", "brighton": "BHA",
    "fulham": "FUL", "wolves": "WOL", "west ham": "WHU",
    "nottingham forest": "NFO", "leeds": "LEE", "burnley": "BUR",
}


@pytest.mark.parametrize("path", PLAYER_FILES, ids=lambda p: p.name)
def test_club_wide_advice_is_not_buried_in_one_players_prose(path):
    """THE regression test for this whole class of bug.

    If a write-up says "analysts are saying avoid Bournemouth assets
    entirely", that verdict has to exist as a club stance in teams.json.
    Left in prose it applies to one player and the optimiser goes on
    picking the club's other twenty -- which is exactly what happened, and
    read perfectly fine to anyone reviewing the file.
    """
    context = consensus.load_team_context()
    offences = []

    for entry in _players(path):
        prose = " ".join(
            str(entry.get(field) or "")
            for field in ("case", "watch_out", "verdict", "reason")
        )
        for match in CLUB_WIDE_PROSE.finditer(prose):
            short = CLUB_ALIASES.get(match.group("club").strip().lower())
            if short is None:
                continue
            if not context.get(short, {}).get("stances"):
                offences.append(
                    f"{entry['name']}'s write-up says {match.group(0)!r}, but {short} carries "
                    f"no stance in teams.json -- so that advice reaches only {entry['name']}."
                )

    assert not offences, "Club-wide advice stored per-player:\n  " + "\n  ".join(offences)


# --- the stances themselves ---------------------------------------------

def test_every_stance_is_usable_by_the_code_that_reads_it():
    for team in _teams():
        for stance in team.get("stances", []) or []:
            label = stance.get("stance")
            assert label in VALID_STANCES, (
                f"{team['short_name']} has stance {label!r}, which the code ignores silently -- "
                f"valid: {sorted(VALID_STANCES)}"
            )
            scope = stance.get("scope", "all")
            if scope != "all":
                unknown = set(p.upper() for p in scope) - VALID_POSITIONS
                assert not unknown, f"{team['short_name']} stance scopes unknown positions {unknown}"


def test_every_stance_states_its_reasoning_and_its_sources():
    """A verdict that moves the squad without saying why is exactly the
    thing the user cannot argue with, and the whole point is that they
    can."""
    for team in _teams():
        for stance in team.get("stances", []) or []:
            short = team["short_name"]
            assert stance.get("case", "").strip(), f"{short} stance has no stated reasoning"
            assert len(stance["case"]) > 60, f"{short} stance reasoning is too thin to be useful"
            assert stance.get("sources"), f"{short} stance cites no sources"


def test_every_stance_can_expire():
    """Fixture-run advice is temporary by nature. A stance with no expiry
    is a permanent hardcode, and research data that cannot expire rots
    silently into a wrong answer."""
    for team in _teams():
        for stance in team.get("stances", []) or []:
            until = stance.get("until_gameweek")
            assert until is not None, (
                f"{team['short_name']} has a stance with no until_gameweek -- it will still be "
                f"applied in May"
            )
            assert 1 <= int(until) <= 38


def test_no_club_appears_twice():
    shorts = [t["short_name"] for t in _teams()]
    assert len(shorts) == len(set(shorts)), "duplicate club entries silently shadow each other"


# --- the player entries -------------------------------------------------

@pytest.mark.parametrize("path", PLAYER_FILES, ids=lambda p: p.name)
def test_every_player_entry_is_usable_by_the_code_that_reads_it(path):
    for entry in _players(path):
        assert entry.get("name"), f"nameless entry in {path.name}"
        assert entry.get("tier") in VALID_TIERS, (
            f"{entry.get('name')} has tier {entry.get('tier')!r}, which annotate() skips silently"
        )


@pytest.mark.parametrize("path", PLAYER_FILES, ids=lambda p: p.name)
def test_every_recommendation_carries_an_argument_and_a_counter_argument(path):
    """A recommendation you can't argue against isn't advice."""
    for entry in _players(path):
        name = entry["name"]
        assert (entry.get("case") or entry.get("reason")), f"{name} has no stated case"
        assert entry.get("watch_out"), f"{name} has no counter-argument"
        assert entry.get("sources"), f"{name} cites no sources"


@pytest.mark.parametrize("path", PLAYER_FILES, ids=lambda p: p.name)
def test_a_recorded_dissent_is_structured_so_it_can_be_shown(path):
    for entry in _players(path):
        dissent = entry.get("dissent")
        if dissent is None:
            continue
        assert isinstance(dissent, dict), f"{entry['name']}'s dissent must carry its own sources"
        assert dissent.get("case", "").strip(), f"{entry['name']}'s dissent states no case"
        assert dissent.get("sources"), f"{entry['name']}'s dissent cites no sources"


@pytest.mark.parametrize("path", PLAYER_FILES, ids=lambda p: p.name)
def test_a_contested_pick_is_never_also_a_hard_lock(path):
    """The must-have lock exists for near-unanimity. Forcing in a player
    the file itself records an argument about is the app contradicting its
    own evidence."""
    for entry in _players(path):
        if entry.get("dissent"):
            assert entry.get("tier") != consensus.MUST_HAVE_TIER, (
                f"{entry['name']} is locked in as a must-have while the file records a dissent"
            )


@pytest.mark.parametrize("path", PLAYER_FILES, ids=lambda p: p.name)
def test_the_file_records_when_it_was_researched(path):
    """Every claim in here has a shelf life measured in days."""
    data = json.loads(path.read_text())
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(data.get("researched", ""))), (
        f"{path.name} has no valid `researched` date, so nobody can tell how stale it is"
    )
