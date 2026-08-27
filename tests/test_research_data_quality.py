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
