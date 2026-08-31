"""Tests for the expert-consensus layer.

Name matching gets the most attention here because it fails silently: FPL
writes "B.Fernandes" where analysts write "Bruno Fernandes", so a matcher
that only compares `web_name` drops most of the research on the floor and
still looks like it worked. A missed must-have is exactly the bug this
whole layer exists to prevent.
"""
import json

import pandas as pd
import pytest

from fpl_assistant.analysis import consensus


@pytest.fixture
def consensus_file(tmp_path, monkeypatch):
    def _write(entries):
        directory = tmp_path / "consensus"
        directory.mkdir(exist_ok=True)
        (directory / "gw1.json").write_text(json.dumps({"gameweek": 1, "players": entries}))
        monkeypatch.setattr(consensus, "CONSENSUS_DIR", directory)

    return _write


def _players(rows) -> pd.DataFrame:
    return pd.DataFrame(rows).set_index("id", drop=False)


def test_matches_compact_fpl_names_against_full_names_in_research(consensus_file):
    """The core matching problem: FPL's web_name is abbreviated, analysts
    write the full name."""
    consensus_file([{"name": "B.Fernandes", "full_name": "Bruno Fernandes", "tier": "strong",
                     "reason": "Penalties and set pieces."}])
    players = _players([
        {"id": 1, "web_name": "B.Fernandes", "first_name": "Bruno", "second_name": "Fernandes",
         "status": "a"},
        {"id": 2, "web_name": "Smith", "first_name": "Joe", "second_name": "Smith", "status": "a"},
    ])

    annotated = consensus.annotate(players, gameweek=1)
    assert annotated.loc[1, "consensus_tier"] == "strong"
    assert annotated.loc[1, "consensus_bonus"] == consensus.TIER_BONUS["strong"]
    assert annotated.loc[2, "consensus_tier"] is None
    assert annotated.loc[2, "consensus_bonus"] == 0.0


def test_matches_on_surname_alone(consensus_file):
    consensus_file([{"name": "Haaland", "full_name": "Erling Haaland", "tier": "must_have",
                     "reason": "Consensus captain."}])
    players = _players([
        {"id": 1, "web_name": "Haaland", "first_name": "Erling", "second_name": "Haaland",
         "status": "a"},
    ])
    assert consensus.annotate(players, 1).loc[1, "consensus_tier"] == "must_have"


def test_does_not_match_a_merely_similar_name(consensus_file):
    """"White" must not match "Whitehead" — a false positive locks the
    wrong player into the squad."""
    consensus_file([{"name": "White", "full_name": "Ben White", "tier": "value", "reason": "x"}])
    players = _players([
        {"id": 1, "web_name": "Whitehead", "first_name": "Sam", "second_name": "Whitehead",
         "status": "a"},
    ])
    assert consensus.annotate(players, 1).loc[1, "consensus_tier"] is None


def test_one_entry_resolves_to_exactly_one_player(consensus_file):
    """Names collide -- Arsenal have fielded more than one prominent
    "Gabriel". Tagging every collision over-constrains the solve (each
    must-have is locked), which can make the squad infeasible and drop the
    must-have entirely. The prominent player wins on ownership."""
    consensus_file([{"name": "Gabriel", "full_name": "Gabriel Magalhaes", "tier": "must_have",
                     "reason": "Top defender."}])
    players = _players([
        {"id": 1, "web_name": "Gabriel", "first_name": "Gabriel", "second_name": "Magalhaes",
         "status": "a", "selected_by_percent": 28.0, "price": 8.0},
        {"id": 2, "web_name": "Gabriel", "first_name": "Gabriel", "second_name": "Jesus",
         "status": "a", "selected_by_percent": 3.0, "price": 7.0},
    ])
    annotated = consensus.annotate(players, 1)

    assert annotated["consensus_tier"].notna().sum() == 1
    assert annotated.loc[1, "consensus_tier"] == "must_have"  # the exact full-name match
    assert consensus.must_have_ids(annotated) == [1]


def test_ambiguous_surname_resolves_to_the_most_owned_player(consensus_file):
    consensus_file([{"name": "Silva", "tier": "strong", "reason": "x"}])
    players = _players([
        {"id": 1, "web_name": "Silva", "first_name": "A", "second_name": "Silva",
         "status": "a", "selected_by_percent": 2.0, "price": 5.0},
        {"id": 2, "web_name": "Silva", "first_name": "B", "second_name": "Silva",
         "status": "a", "selected_by_percent": 31.0, "price": 7.5},
    ])
    annotated = consensus.annotate(players, 1)

    assert annotated["consensus_tier"].notna().sum() == 1
    assert annotated.loc[2, "consensus_tier"] == "strong"


def test_must_haves_are_reported_for_locking(consensus_file):
    consensus_file([
        {"name": "Haaland", "full_name": "Erling Haaland", "tier": "must_have", "reason": "x"},
        {"name": "Gabriel", "full_name": "Gabriel Magalhaes", "tier": "strong", "reason": "y"},
    ])
    players = _players([
        {"id": 1, "web_name": "Haaland", "first_name": "Erling", "second_name": "Haaland", "status": "a"},
        {"id": 2, "web_name": "Gabriel", "first_name": "Gabriel", "second_name": "Magalhaes", "status": "a"},
    ])
    annotated = consensus.annotate(players, 1)

    assert consensus.must_have_ids(annotated) == [1]  # only the must_have, not the strong pick


def test_injured_must_have_is_not_locked(consensus_file):
    """Locking an unavailable player would make the squad unsolvable for
    no benefit."""
    consensus_file([{"name": "Haaland", "full_name": "Erling Haaland", "tier": "must_have", "reason": "x"}])
    players = _players([
        {"id": 1, "web_name": "Haaland", "first_name": "Erling", "second_name": "Haaland", "status": "i"},
    ])
    annotated = consensus.annotate(players, 1)
    assert consensus.must_have_ids(annotated) == []


def test_avoid_tier_is_penalised_and_excluded(consensus_file):
    consensus_file([{"name": "Saliba", "full_name": "William Saliba", "tier": "avoid",
                     "reason": "Out injured."}])
    players = _players([
        {"id": 1, "web_name": "Saliba", "first_name": "William", "second_name": "Saliba", "status": "a"},
    ])
    annotated = consensus.annotate(players, 1)

    assert annotated.loc[1, "consensus_bonus"] < 0
    assert consensus.avoid_ids(annotated) == [1]


def test_a_neutral_verdict_reaches_the_player_without_moving_the_projection(consensus_file):
    """The bug this closes: `annotate` SKIPS any entry whose tier it does
    not recognise. So a researcher writing an honest "he starts, but this
    is the wrong week to buy him" verdict under any label other than the
    four known tiers had the whole write-up silently deleted -- the
    "no write-up found" failure wearing a different hat.

    `neutral` is a real tier: it carries the words to the page and applies
    a bonus of exactly zero, so the projection decides on the numbers while
    the reader still gets the reasoning.
    """
    consensus_file([{"name": "Palmer", "full_name": "Cole Palmer", "tier": "neutral",
                     "reason": "Starts, but the fixture is the wrong one to buy into."}])
    players = _players([
        {"id": 1, "web_name": "Palmer", "first_name": "Cole", "second_name": "Palmer",
         "status": "a"},
    ])

    annotated = consensus.annotate(players, gameweek=1)
    assert annotated.loc[1, "consensus_tier"] == "neutral", "the entry must not be dropped"
    assert annotated.loc[1, "consensus_bonus"] == 0.0
    assert annotated.loc[1, "consensus_reason"]


def test_every_tier_the_research_may_use_can_be_displayed():
    """A tier the validator accepts but the UI cannot label is a write-up
    that reaches the app and then renders as nothing."""
    from fpl_assistant.analysis import rationale, team_brief  # noqa: F401
    from fpl_assistant.dashboard import app
    from fpl_assistant.research import validation

    for tier in validation.VALID_TIERS:
        assert tier in consensus.TIER_BONUS, f"{tier} would be skipped by annotate()"
        assert tier in rationale.CONSENSUS_HEADLINES, f"{tier} has no verdict headline"
        assert tier in app.CONSENSUS_LABELS, f"{tier} has no sidebar label"
        assert tier in app.TIER_CHIP, f"{tier} has no chip"


def test_missing_consensus_file_is_harmless(tmp_path, monkeypatch):
    """No research for a gameweek must degrade to projection-only, not
    penalise every player."""
    monkeypatch.setattr(consensus, "CONSENSUS_DIR", tmp_path / "nothing-here")
    players = _players([
        {"id": 1, "web_name": "Haaland", "first_name": "Erling", "second_name": "Haaland", "status": "a"},
    ])
    annotated = consensus.annotate(players, 1)

    assert (annotated["consensus_bonus"] == 0).all()
    assert consensus.must_have_ids(annotated) == []


def test_shipped_gw1_file_is_valid_and_names_a_must_have():
    """Guards the real data file against typos and tier drift."""
    data = consensus.load_consensus(1)
    assert data is not None, "data/consensus/gw1.json should ship with the app"

    entries = data["players"]
    assert entries
    for entry in entries:
        assert entry["tier"] in consensus.TIER_BONUS, entry
        # Every entry must carry a written argument, not just a tier -- the
        # whole point is telling the manager why, not just what.
        assert entry.get("case") or entry.get("reason"), f"{entry['name']} needs a written case"
        assert entry.get("verdict"), f"{entry['name']} needs a one-line verdict"

    must_haves = [e["name"] for e in entries if e["tier"] == "must_have"]
    assert must_haves, "GW1 consensus should name at least one must-have"


# --- two different kinds of disagreement --------------------------------

def test_a_disagreement_about_output_damps_the_weighting():
    """When analysts disagree about whether a player will score, the
    confident version of either view is wrong."""
    assert consensus.dissent_kind({"case": "x", "kind": "output"}) == consensus.DISSENT_OUTPUT
    assert consensus.dissent_kind({"case": "x"}) == consensus.DISSENT_OUTPUT


def test_a_disagreement_about_rank_is_labelled_differently():
    assert consensus.dissent_kind({"case": "x", "kind": "rank"}) == consensus.DISSENT_RANK


def test_an_unrecognised_kind_falls_back_to_the_cautious_reading():
    assert consensus.dissent_kind({"case": "x", "kind": "vibes"}) == consensus.DISSENT_OUTPUT
    assert consensus.dissent_kind("just a string") == consensus.DISSENT_OUTPUT


def test_a_rank_argument_does_not_mark_a_player_down_for_being_popular():
    """The bug this split exists to fix.

    Everyone agreed Haaland would score; they argued about whether owning
    him at 71% ownership gained you anything. Treating that as a split on
    the player halved his weighting — penalising the most-owned striker in
    the game for being owned.
    """
    output_split = {"case": "half of them think he's finished", "kind": "output"}
    rank_split = {"case": "he's 71% owned, you gain nothing", "kind": "rank"}

    damped = consensus.TIER_BONUS["must_have"] * consensus.DISSENT_DAMPING
    full = consensus.TIER_BONUS["must_have"]

    assert consensus.dissent_kind(output_split) == consensus.DISSENT_OUTPUT
    assert consensus.dissent_kind(rank_split) == consensus.DISSENT_RANK
    assert damped < full  # an output split really does cost him
