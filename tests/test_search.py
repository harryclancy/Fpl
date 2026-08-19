"""Tests for the research search.

The point of a local index over a model call is that it cannot invent a
fact — every hit has to come from the corpus and point at the text that
matched. So these tests care about two things: that the thing you searched
for ranks first, and that a miss is honest rather than padded with
loosely-related results.
"""
import json

import pandas as pd
import pytest

from fpl_assistant.analysis import consensus, search


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    directory = tmp_path / "consensus"
    directory.mkdir(exist_ok=True)
    monkeypatch.setattr(consensus, "CONSENSUS_DIR", directory)

    def _write(players=None, teams=None, gameweek=1):
        (directory / f"gw{gameweek}.json").write_text(
            json.dumps({"gameweek": gameweek, "players": players or []})
        )
        (directory / "teams.json").write_text(json.dumps({"teams": teams or []}))

    return _write


ENTRY = {
    "name": "B.Fernandes", "full_name": "Bruno Fernandes", "tier": "strong",
    "verdict": "The safest premium midfielder.",
    "case": "He takes penalties, corners and direct free-kicks.",
    "watch_out": "He missed another penalty in pre-season.",
    "key_stats": ["9 goals and 24 assists last season"],
    "voices": [{"source": "Fantasy Football Scout", "take": "Flagged the pre-season penalty misses."}],
    "sources": ["Fantasy Football Scout"],
}


def _teams_frame():
    return pd.DataFrame([
        {"short_name": "BOU", "name": "Bournemouth"},
        {"short_name": "MUN", "name": "Man Utd"},
    ])


# --- ranking ------------------------------------------------------------

def test_searching_a_name_puts_that_player_first(corpus):
    corpus([ENTRY, dict(ENTRY, name="Other", full_name="Someone Else",
                        case="Bruno Fernandes is better than him.")])
    hits = search.search("Bruno Fernandes")
    assert hits[0].title == "Bruno Fernandes"


def test_searching_a_club_puts_that_clubs_verdict_first(corpus):
    """The bug this caught: a club's own name appears once in its own
    write-up, so it scored lower on itself than a player whose article
    mentioned it repeatedly."""
    corpus(
        players=[dict(ENTRY, case="Bournemouth are the worst run in the league, avoid Bournemouth.")],
        teams=[{"short_name": "BOU", "stances": [
            {"stance": "avoid", "scope": "all", "until_gameweek": 9,
             "case": "Toughest opening in the division.", "sources": ["RotoWire"]},
        ]}],
    )
    hits = search.search("Bournemouth", teams=_teams_frame())
    assert hits[0].kind == "club"
    assert "BOU" in hits[0].title


def test_a_topic_search_finds_the_players_it_applies_to(corpus):
    corpus([ENTRY])
    hits = search.search("penalties")
    assert hits[0].title == "Bruno Fernandes"
    assert any("penalt" in text.lower() for _, text in hits[0].snippets)


def test_matches_inside_an_attributed_take_are_found_and_credited(corpus):
    corpus([ENTRY])
    hits = search.search("pre-season penalty misses")
    labels = [label for label, _ in hits[0].snippets]
    assert "Fantasy Football Scout" in labels


def test_a_stat_match_is_labelled_as_a_stat(corpus):
    corpus([ENTRY])
    hits = search.search("24 assists")
    assert ("Stat", "9 goals and 24 assists last season") in hits[0].snippets


# --- honesty ------------------------------------------------------------

def test_a_miss_returns_nothing_rather_than_loosely_related_results(corpus):
    corpus([ENTRY])
    assert search.search("volcano insurance") == []


def test_stopwords_alone_return_nothing(corpus):
    """Without this, "who is the best" matches every entry containing
    "is" and the results are pure noise."""
    corpus([ENTRY])
    assert search.search("who is the") == []
    assert search.search("") == []


def test_matching_is_whole_word_not_substring(corpus):
    """"pen" must not hit "expensive" and "open"."""
    corpus([dict(ENTRY, case="He is expensive and the game is open.",
                 watch_out="", key_stats=["x"], voices=[{"source": "S", "take": "t"}])])
    assert search.search("pen") == []


def test_a_named_player_with_no_research_still_comes_back(corpus):
    """Searching a name shouldn't come back empty just because no analyst
    covered him — the live numbers are still an answer."""
    corpus([])
    scored = pd.DataFrame([{
        "id": 1, "web_name": "Nobody", "team_short_name": "BOU", "position": "MID",
        "price": 5.5, "xp_next": 3.2, "xp_horizon": 16.0, "selected_by_percent": 0.4,
    }])
    hits = search.search("Nobody", scored=scored)

    assert hits[0].title == "Nobody"
    assert hits[0].player_id == 1
    assert "No analyst has written about him" in hits[0].snippets[0][0]


def test_a_researched_player_is_not_duplicated_by_the_live_pool(corpus):
    corpus([ENTRY])
    scored = pd.DataFrame([{
        "id": 1, "web_name": "B.Fernandes", "team_short_name": "MUN", "position": "MID",
        "price": 12.0, "xp_next": 6.0, "xp_horizon": 30.0, "selected_by_percent": 48.0,
    }])
    titles = [h.title for h in search.search("Fernandes", scored=scored)]
    assert len(titles) == len(set(titles))


def test_report_sections_are_returned_with_their_heading(corpus):
    corpus([])
    report = "# Odds\nHaaland is 4/5 to score.\n\n## Injuries\nSaliba is out with a back problem."
    hits = search.search("Saliba", report_text=report)

    assert hits[0].kind == "report"
    assert hits[0].title == "Injuries"


def test_the_limit_is_respected(corpus):
    corpus([dict(ENTRY, name=f"P{i}", full_name=f"Player {i}") for i in range(20)])
    assert len(search.search("penalties", limit=3)) == 3


def test_search_falls_back_to_the_most_recent_researched_gameweek(corpus):
    """Search shouldn't come back empty just because this gameweek hasn't
    been researched — last week's verdict is stale, not nothing."""
    corpus([ENTRY], gameweek=7)
    assert search.search("Bruno Fernandes")[0].title == "Bruno Fernandes"
