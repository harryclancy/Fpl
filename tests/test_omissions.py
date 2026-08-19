"""Tests for the "who we're NOT picking, and why" section.

The requirement behind this module is trust, not correctness in the usual
sense: a player the app weighed and rejected must not look like a player
it never considered. So the tests care most about two things -- that the
right players get surfaced at all, and that the *reason* given is the real
one rather than a generic fallback.

The generic fallback ("he'd cost you points") is always available and
almost always the least useful answer. If a player is left out because
every analyst says avoid his club, saying "he's a bit expensive" instead
is technically true and actively misleading.
"""
import pandas as pd
import pytest

from fpl_assistant.analysis import omissions, optimiser


def _solution(squad_ids):
    """A minimal stand-in squad. These tests are about which players are
    left out and why, so the squad only has to say who is already in."""
    ids = list(squad_ids)
    return optimiser.SquadSolution(
        squad_ids=ids, starting_ids=ids[:11], bench_ids=ids[11:],
        captain_id=ids[0], vice_captain_id=ids[-1], formation="4-4-2",
        total_cost=99.0, expected_points=60.0,
    )


BASE = {
    "team_short_name": "AAA", "position": "MID", "price": 7.0, "status": "a",
    "news": "", "selected_by_percent": 2.0, "xp_horizon": 20.0,
    "xp_pre_consensus": 20.0, "xp_next": 4.0, "consensus_tier": None,
    "consensus_reason": None, "consensus_watch_out": None, "consensus_dissent": None,
    "consensus_sources": None, "club_stance": None, "club_stance_case": None,
    "club_stance_until": pd.NA,
}


def _pool(*overrides) -> pd.DataFrame:
    rows = []
    for i, override in enumerate(overrides, start=1):
        row = dict(BASE)
        row.update(override)
        row.setdefault("web_name", f"P{i}")
        row["id"] = i
        rows.append(row)
    return pd.DataFrame(rows).set_index("id", drop=False)


# --- who gets surfaced --------------------------------------------------

def test_a_widely_owned_player_who_missed_out_is_surfaced():
    pool = _pool(
        {"web_name": "InSquad"},
        {"web_name": "Popular", "selected_by_percent": 45.0},
    )
    found = omissions.notable_omissions(pool, _solution([1]), max_resolves=0)
    assert [o.name for o in found] == ["Popular"]


def test_a_player_nobody_owns_is_not_surfaced():
    """Absence only needs defending when it's surprising."""
    pool = _pool({"web_name": "InSquad"}, {"web_name": "Nobody", "selected_by_percent": 0.4})
    found = omissions.notable_omissions(pool, _solution([1]), max_resolves=0)
    assert found == []


def test_players_already_in_the_squad_are_never_listed():
    pool = _pool({"web_name": "Star", "selected_by_percent": 80.0})
    assert omissions.notable_omissions(pool, _solution([1, 1]), max_resolves=0) == []


def test_a_player_the_analysts_named_is_surfaced_even_at_low_ownership():
    pool = _pool(
        {"web_name": "InSquad"},
        {"web_name": "Named", "selected_by_percent": 1.0, "consensus_tier": "value",
         "consensus_reason": "Cheap route into a good attack."},
    )
    found = omissions.notable_omissions(pool, _solution([1]), max_resolves=0)
    assert [o.name for o in found] == ["Named"]


# --- is the reason the real one? ---------------------------------------

def test_a_club_verdict_is_given_as_the_reason_not_the_price():
    """The specific failure this guards against: answering "he's a bit
    expensive" about a player who is actually out because every analyst
    says avoid his club."""
    pool = _pool(
        {"web_name": "InSquad"},
        {"web_name": "BouDefender", "selected_by_percent": 20.0, "team_short_name": "BOU",
         "club_stance": "avoid", "club_stance_until": 9,
         "club_stance_case": "Worst opening run in the league."},
    )
    found = omissions.notable_omissions(pool, _solution([1]), max_resolves=0)

    assert len(found) == 1
    assert found[0].category == "club"
    assert "BOU" in found[0].headline
    assert "Worst opening run" in found[0].detail
    assert "GW9" in found[0].detail


def test_the_club_reason_makes_clear_it_is_not_about_the_player():
    pool = _pool(
        {"web_name": "InSquad"},
        {"web_name": "Solid", "selected_by_percent": 20.0, "team_short_name": "BOU",
         "club_stance": "avoid", "club_stance_case": "Brutal run."},
    )
    headline = omissions.notable_omissions(pool, _solution([1]), max_resolves=0)[0].headline
    assert "not because of him" in headline


def test_a_split_in_expert_opinion_is_reported_as_a_split():
    pool = _pool(
        {"web_name": "InSquad"},
        {"web_name": "Contested", "selected_by_percent": 25.0, "consensus_tier": "strong",
         "consensus_dissent": "Several analysts say his DefCon record doesn't support the price.",
         "consensus_sources": "RotoWire"},
    )
    found = omissions.notable_omissions(pool, _solution([1]), max_resolves=0)
    assert found[0].category == "disputed"
    assert "DefCon" in found[0].detail
    assert found[0].sources == "RotoWire"


def test_unavailability_outranks_every_other_reason():
    """Nothing else matters until the player is fit. Reporting a nuanced
    fixture argument about someone who is injured is noise."""
    pool = _pool(
        {"web_name": "InSquad"},
        {"web_name": "Injured", "selected_by_percent": 30.0, "status": "i",
         "news": "Hamstring injury - expected back 20 Sep.",
         "club_stance": "avoid", "club_stance_case": "Bad run too."},
    )
    found = omissions.notable_omissions(pool, _solution([1]), max_resolves=0)
    assert found[0].category == "unavailable"
    assert "hamstring" in found[0].detail.lower()


def test_reasons_are_ordered_most_explanatory_first():
    pool = _pool(
        {"web_name": "InSquad"},
        {"web_name": "Costly", "selected_by_percent": 60.0},
        {"web_name": "ClubFlagged", "selected_by_percent": 20.0, "club_stance": "avoid",
         "club_stance_case": "Bad run."},
    )
    found = omissions.notable_omissions(pool, _solution([1]), max_resolves=0)
    # Ownership would have put "Costly" first; the reason quality shouldn't.
    assert found[0].name == "ClubFlagged"


def test_a_caution_verdict_is_worded_more_softly_than_an_avoid():
    def _detail(stance):
        pool = _pool(
            {"web_name": "InSquad"},
            {"web_name": "X", "selected_by_percent": 20.0, "club_stance": stance,
             "club_stance_case": "Case."},
        )
        return omissions.notable_omissions(pool, _solution([1]), max_resolves=0)[0].detail

    assert "steering clear of" in _detail("avoid")
    assert "wary of" in _detail("caution")


# --- robustness ---------------------------------------------------------

def test_the_solver_is_not_run_more_than_the_cap_allows():
    """Each fallback explanation is a fresh ILP. Surfacing ten players
    without a cap would mean ten squad solves on a page load."""
    rows = [{"web_name": f"Pop{i}", "selected_by_percent": 50.0} for i in range(8)]
    pool = _pool({"web_name": "InSquad"}, *rows)

    calls = []
    original = omissions.explain.explain_player

    def counting(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("no solver in this test")

    omissions.explain.explain_player = counting
    try:
        omissions.notable_omissions(pool, _solution([1]), max_resolves=2)
    finally:
        omissions.explain.explain_player = original

    assert len(calls) == 2


def test_an_empty_pool_is_handled():
    pool = _pool({"web_name": "OnlyPlayer"})
    assert omissions.notable_omissions(pool, _solution([1]), max_resolves=0) == []


def test_the_limit_is_respected():
    rows = [{"web_name": f"C{i}", "selected_by_percent": 50.0, "club_stance": "avoid",
             "club_stance_case": "x"} for i in range(12)]
    pool = _pool({"web_name": "InSquad"}, *rows)
    found = omissions.notable_omissions(pool, _solution([1]), limit=4, max_resolves=0)
    assert len(found) == 4


def test_a_player_is_still_listed_when_the_solve_budget_runs_out():
    """The regression that matters most here.

    Counterfactual solves are rationed, and the first version of this
    module skipped any player it couldn't afford to solve for. That
    reintroduced the exact failure the module exists to prevent: a player
    the app considered and rejected disappearing from the page as though
    it had never heard of him. A vaguer reason is fine; silence is not.
    """
    pool = _pool(
        {"web_name": "InSquad"},
        {"web_name": "Popular", "selected_by_percent": 55.0},
    )
    found = omissions.notable_omissions(pool, _solution([1]), max_resolves=0)

    assert [o.name for o in found] == ["Popular"]
    assert found[0].category == "cost"
    assert found[0].points_cost is None
    # And it must not state a counterfactual cost it never computed. Real
    # figures pulled from the data are fine and wanted -- an invented
    # "costs about 3.2 points" is not.
    assert "costs about" not in found[0].detail


# --- evidence attached to every verdict ---------------------------------

def test_every_omission_carries_numbers_to_check_it_against():
    """The complaint this answers: reasons that were too generic to argue
    with. A verdict with no evidence attached is an assertion."""
    pool = _pool(
        {"web_name": "InSquad", "position": "MID", "price": 8.0, "xp_next": 5.0},
        {"web_name": "Popular", "selected_by_percent": 55.0, "price": 9.5,
         "xp_next": 4.2, "xp_horizon": 21.0, "points_per_game": 5.1, "form": 6.0,
         "minutes": 2400, "starts": 27, "expected_goals_per_90": 0.42,
         "expected_assists_per_90": 0.21},
    )
    found = omissions.notable_omissions(pool, _solution([1]), max_resolves=0)

    stats = found[0].stats
    assert stats, "no supporting numbers attached"
    blob = " ".join(stats)
    assert "£9.5m" in blob
    assert "55.0% owned" in blob
    assert "expected goal involvements per 90" in blob
    assert "2400 minutes played across 27 starts" in blob


def test_researched_facts_are_preferred_over_derived_ones():
    """Where the research file has real numbers they lead, because
    "18 clean sheets, 3 more than any other defender" beats a restatement
    of the model's own projection."""
    import json

    pool = _pool(
        {"web_name": "InSquad"},
        {"web_name": "Researched", "selected_by_percent": 30.0,
         "consensus_stats": json.dumps(["209 points last season", "18 clean sheets"])},
    )
    found = omissions.notable_omissions(pool, _solution([1]), max_resolves=0)
    assert found[0].stats[:2] == ["209 points last season", "18 clean sheets"]


def test_attributed_takes_are_carried_through():
    import json

    pool = _pool(
        {"web_name": "InSquad"},
        {"web_name": "Talked About", "selected_by_percent": 30.0,
         "consensus_voices": json.dumps([{"source": "RotoWire", "take": "They rate him highly."}])},
    )
    found = omissions.notable_omissions(pool, _solution([1]), max_resolves=0)
    assert found[0].voices == [("RotoWire", "They rate him highly.")]


def test_the_reason_names_who_holds_the_slot_instead():
    """"Why not him?" is a comparison. Answering it without naming the
    alternative leaves the reader to go and find it themselves."""
    pool = _pool(
        {"web_name": "Holder", "position": "MID", "price": 9.0, "xp_next": 5.5,
         "team_short_name": "ARS"},
        {"web_name": "Popular", "position": "MID", "price": 9.2, "xp_next": 4.1,
         "selected_by_percent": 50.0},
    )
    found = omissions.notable_omissions(pool, _solution([1]), max_resolves=0)

    assert found[0].instead is not None
    assert "Holder" in found[0].instead
    assert "5.5 projected pts" in found[0].instead
    assert "Holder" in found[0].detail


def test_malformed_packed_evidence_degrades_to_nothing():
    """These columns are rendered straight into the page, so a bad cell
    has to come back empty rather than raise on a tab already open."""
    pool = _pool(
        {"web_name": "InSquad"},
        {"web_name": "Broken", "selected_by_percent": 30.0,
         "consensus_stats": "{not json", "consensus_voices": "also not json"},
    )
    found = omissions.notable_omissions(pool, _solution([1]), max_resolves=0)
    assert found[0].voices == []
    assert found[0].stats  # derived stats still present
