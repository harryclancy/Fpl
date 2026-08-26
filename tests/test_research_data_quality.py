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
