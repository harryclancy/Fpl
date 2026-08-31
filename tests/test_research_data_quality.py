"""Lints the shipped research files.

The rules themselves live in fpl_assistant/research/validation.py, because
the research is now written by an automated agent and a rule that only
runs in CI would let bad data reach the app first and get caught
afterwards. The agent checks its own output against these rules before
writing; this file checks what actually landed in the repo.

Nothing here can tell whether a football claim is true. What it can tell
is whether claims are stored where they will actually be used, are
attributed, and carry the evidence to argue with — which is the failure
that kept happening.
"""
import json
from pathlib import Path

import pytest

from fpl_assistant.analysis import consensus
from fpl_assistant.research import validation

DATA = Path(__file__).resolve().parent.parent / "data"
PLAYER_FILES = sorted((DATA / "consensus").glob("gw*.json"))
ODDS_FILES = sorted((DATA / "odds").glob("gw*.json"))
TEAM_FILE = DATA / "consensus" / "teams.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


@pytest.mark.parametrize("path", PLAYER_FILES, ids=lambda p: p.name)
def test_the_shipped_player_research_is_usable(path):
    problems = validation.validate_players(_load(path), consensus.load_team_context())
    assert not problems, f"{path.name}:\n  " + "\n  ".join(problems)


def test_the_shipped_club_stances_are_usable():
    problems = validation.validate_teams(_load(TEAM_FILE))
    assert not problems, "teams.json:\n  " + "\n  ".join(problems)


@pytest.mark.parametrize("path", ODDS_FILES, ids=lambda p: p.name)
def test_the_shipped_odds_are_usable(path):
    problems = validation.validate_odds(_load(path))
    assert not problems, f"{path.name}:\n  " + "\n  ".join(problems)


def test_there_is_research_to_ship_at_all():
    """A guard against the automation quietly emptying the directory."""
    assert PLAYER_FILES, "no per-player research is committed"
    assert TEAM_FILE.exists(), "no club stances are committed"


# --- the Haaland failure, encoded in the research ------------------------

def test_the_most_owned_player_in_the_game_is_not_filed_as_optional():
    """The reported complaint: the app dropped Haaland after one blank.

    Part of that was the model (fixed in analysis/history.py) and part was
    the research file, which had a 71%-owned Golden Boot winner tiered the
    same as a £4.6m bandwagon full-back. A player this widely owned is a
    decision you deviate from, not one you have to justify.
    """
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "data" / "consensus" / "gw2.json"
    players = {p["name"]: p for p in json.loads(path.read_text())["players"]}
    haaland = players.get("Haaland")

    assert haaland is not None
    assert haaland["tier"] == "must_have"
    assert haaland["expert_ownership"] >= 50
    # The case has to lead on the multi-season record, not the projection.
    assert "Golden Boot" in haaland["case"] or "27" in haaland["case"]
    assert len(haaland["key_stats"]) >= 5
    assert len(haaland["voices"]) >= 3


def test_every_researched_player_carries_a_case_and_a_counter_case():
    """A recommendation you can't argue against isn't advice."""
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "data" / "consensus" / "gw2.json"
    for player in json.loads(path.read_text())["players"]:
        name = player["name"]
        assert player.get("case", "").strip(), f"{name} has no case"
        assert player.get("watch_out", "").strip(), f"{name} has no counter-case"
        assert player.get("key_stats"), f"{name} has no supporting facts"
        assert player.get("sources"), f"{name} cites no sources"


def test_named_outlets_not_analysts_say():
    """'Analysts say' is not a source. Every voice names who said it."""
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "data" / "consensus" / "gw2.json"
    for player in json.loads(path.read_text())["players"]:
        for voice in player.get("voices", []):
            assert voice.get("source", "").strip(), f"{player['name']} has an unattributed voice"
            assert voice.get("take", "").strip()
            assert voice["source"].lower() not in {"analysts", "experts", "the community"}


# --- the reference data must describe the league that exists -------------

def test_the_club_list_is_the_twenty_clubs_in_the_league():
    """teams.json carried a 21st club — Burnley — who are not in the
    2026/27 Premier League. It was an empty placeholder, which is why
    nothing broke and why nothing flagged it either: a club stance file
    that quietly describes a league with 21 teams in it is wrong in a way
    no player-level check can see."""
    clubs = {t["short_name"] for t in _load(TEAM_FILE)["teams"]}
    assert len(clubs) == 20, f"{len(clubs)} clubs listed: {sorted(clubs)}"


MATCHUP_FILES = sorted((DATA / "consensus").glob("matchups_gw*.json"))


@pytest.mark.parametrize("path", MATCHUP_FILES, ids=lambda p: p.name)
def test_a_matchup_file_covers_a_full_round_of_real_clubs(path):
    """Ten fixtures, twenty distinct clubs, every one of them a club the
    stance file knows about. A typo'd or stale club code here means the
    fixture commentary silently never reaches the player it was written
    about."""
    payload = _load(path)
    fixtures = payload["fixtures"]
    known = {t["short_name"] for t in _load(TEAM_FILE)["teams"]}

    sides = [side for f in fixtures for side in (f["home"], f["away"])]
    unknown = sorted(set(sides) - known)
    assert not unknown, f"{path.name} references clubs not in teams.json: {unknown}"

    assert len(sides) == len(set(sides)), (
        f"{path.name}: a club appears twice in the same round"
    )
    if len(fixtures) == 10:
        assert len(set(sides)) == 20, f"{path.name}: a full round must cover all 20 clubs"


@pytest.mark.parametrize("path", MATCHUP_FILES, ids=lambda p: p.name)
def test_a_matchup_file_is_for_the_gameweek_its_name_claims(path):
    """A file called matchups_gw3 holding gameweek 2 research would be
    served as current with nothing to reveal the swap."""
    claimed = int(path.stem.replace("matchups_gw", ""))
    assert _load(path)["gameweek"] == claimed


def test_the_player_research_and_the_matchups_agree_on_the_gameweek():
    for path in MATCHUP_FILES:
        gw = _load(path)["gameweek"]
        players = DATA / "consensus" / f"gw{gw}.json"
        if not players.exists():
            continue
        assert _load(players)["gameweek"] == gw
