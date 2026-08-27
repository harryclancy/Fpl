"""The reasons people actually give, for and against.

The complaint this exists to answer, verbatim: "I want the main reasoning
for the pick to be what people have said. POSITIVES AND NEGATIVES E.G
SZOBOSZLAI PLAYED DEEPER SO MAY NOT ATTACK, BRIGHTON STRONG DEFENCE."

Both halves of that example are things the app previously had no place to
put. "He's been playing deeper in a double pivot" is a tactical
observation about a role, not a statistic. "Brighton have a strong
defence" is a fact about a *fixture*, true for every attacker who faces
them, and writing it into one player's paragraph reaches one player.

So there are two structures: `talking_points` on a player (for/against,
each attributed) and `matchups_gw{N}.json` on a fixture (what people say
about each side's attack and defence).
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant.analysis import consensus, matchups

DATA = Path(__file__).resolve().parent.parent / "data" / "consensus"


def _gw2() -> dict:
    return json.loads((DATA / "gw2.json").read_text())


# --- the arguments, per player ------------------------------------------

def test_both_sides_of_the_argument_survive_a_round_trip():
    frame = pd.DataFrame([{"id": 1, "web_name": "X", "position": "MID", "team": 1}])
    entry = {
        "talking_points": {
            "for": [{"point": "on penalties", "source": "RotoWire"}],
            "against": [{"point": "playing deeper", "source": "Scout"}],
        }
    }
    frame["consensus_for"] = consensus._pack(entry["talking_points"]["for"])
    frame["consensus_against"] = consensus._pack(entry["talking_points"]["against"])
    row = frame.iloc[0]

    assert consensus.arguments_for(row) == [("on penalties", "RotoWire")]
    assert consensus.arguments_against(row) == [("playing deeper", "Scout")]


def test_a_player_with_no_talking_points_returns_nothing_rather_than_raising():
    row = pd.Series({"web_name": "X"})
    assert consensus.arguments_for(row) == []
    assert consensus.arguments_against(row) == []


def test_a_bare_string_still_reads_as_a_point_with_no_source():
    frame = pd.DataFrame([{"id": 1}])
    frame["consensus_for"] = consensus._pack(["just a claim"])
    assert consensus.arguments_for(frame.iloc[0]) == [("just a claim", "")]


def test_the_szoboszlai_objection_is_actually_in_the_research():
    """The user's own example, taken literally.

    He is on set pieces and penalties, which is a reason to buy; he has
    also been playing deeper in a double pivot, which is a reason not to.
    Both have to be in the file, attributed, on opposite sides.
    """
    players = {p["name"]: p for p in _gw2()["players"]}
    szoboszlai = players.get("Szoboszlai")

    assert szoboszlai is not None, "Szoboszlai missing from the GW2 research"
    against = " ".join(p["point"] for p in szoboszlai["talking_points"]["against"]).lower()
    favour = " ".join(p["point"] for p in szoboszlai["talking_points"]["for"]).lower()

    assert "deeper" in against
    assert "pivot" in against
    assert "penalt" in favour or "set piece" in favour or "set-piece" in favour


def test_every_argument_names_who_made_it():
    for player in _gw2()["players"]:
        for side in ("for", "against"):
            for item in (player.get("talking_points") or {}).get(side, []):
                assert item.get("point", "").strip(), f"{player['name']}: empty {side} point"
                assert item.get("source", "").strip(), (
                    f"{player['name']}: unattributed {side} point — a claim with no source is a guess"
                )


def test_nobody_gets_only_good_news():
    """A pile of reasons to buy with nothing against is advocacy."""
    for player in _gw2()["players"]:
        talking = player.get("talking_points")
        if not talking or not talking.get("for"):
            continue
        assert talking.get("against"), f"{player['name']} has no case against him"


def test_the_research_carries_real_depth_not_a_token_line_each():
    total = sum(
        len((p.get("talking_points") or {}).get("for", []))
        + len((p.get("talking_points") or {}).get("against", []))
        for p in _gw2()["players"]
    )
    assert total >= 50, f"only {total} arguments across the whole file"


# --- the matchups, per fixture ------------------------------------------

def test_the_brighton_defence_point_reaches_every_chelsea_attacker():
    """The other half of the user's example.

    "Brighton have a strong defence" is a fact about the fixture. Written
    into Palmer's write-up it reaches Palmer; attached to the fixture it
    reaches Palmer, João Pedro, Rogers and anyone else in that game.
    """
    fixtures = matchups.load(2)
    assert fixtures, "no GW2 matchup research found"

    notes = matchups.opponent_notes("CHE", "MID", fixtures)
    text = " ".join(n.point for n in notes).lower()

    assert notes, "a Chelsea attacker sees nothing about Brighton"
    assert "defen" in text
    assert all(n.source for n in notes), "an unattributed matchup note"


def test_an_attacker_is_shown_the_defence_and_a_defender_the_attack():
    fixtures = matchups.load(2)

    attacker_view = {n.point for n in matchups.opponent_notes("MCI", "FWD", fixtures)}
    defender_view = {n.point for n in matchups.opponent_notes("MCI", "DEF", fixtures)}

    assert attacker_view and defender_view
    assert attacker_view != defender_view


def test_a_club_not_playing_this_gameweek_gets_nothing_rather_than_a_wrong_fixture():
    fixtures = matchups.load(2)
    assert matchups.opponent_notes("NOTACLUB", "MID", fixtures) == []
    assert matchups.fixture_for("NOTACLUB", fixtures) is None


def test_the_summary_names_the_opponent_and_the_loudest_point():
    fixtures = matchups.load(2)
    line = matchups.summary("CHE", "MID", fixtures)

    assert "BHA" in line
    assert "home to" in line or "away at" in line
    assert len(line) > 40, "the summary dropped the actual commentary"


def test_a_missing_matchup_file_degrades_quietly(monkeypatch, tmp_path):
    monkeypatch.setattr(matchups, "MATCHUP_DIR", tmp_path)
    assert matchups.load(2) == []
    assert matchups.opponent_notes("CHE", "MID", []) == []


def test_every_researched_fixture_covers_both_sides():
    for fixture in matchups.load(2):
        assert fixture.headline, f"{fixture.label} has no headline"
        for club in (fixture.home, fixture.away):
            assert club in fixture.clubs, f"{fixture.label}: nothing about {club}"
            view = fixture.clubs[club]
            assert view.attack or view.defence, f"{fixture.label}: {club} has no notes"
