"""The captaincy decision.

Three failures this pins down, in order of how badly they read:

  1. A centre-back being recommended as captain. That wasn't a tuning
     problem, it was a category error — ranking a doubled score on a mean
     treats a defender who collects appearance points and a clean sheet
     most weeks as equivalent to a forward with a real chance of fifteen.
  2. Ignoring what everyone else is doing. Rank moves on how far your pick
     differs from the field's, so a 60%-captained player's haul barely
     moves you.
  3. Quietly averaging the numbers and the analysts when they disagree,
     which hides the most interesting thing on the page.
"""
import pandas as pd
import pytest

from fpl_assistant.analysis import captain_call, squad_builder

FORWARD = {
    "position": "FWD", "team_short_name": "MCI", "price": 12.0, "status": "a",
    "selected_by_percent": 30.0, "xg_match": 0.6, "xa_match": 0.15,
    "p_clean_sheet": 0.3, "p_sixty": 0.9, "p_start": 0.95, "p_available": 1.0,
}
DEFENDER = {
    **FORWARD, "position": "DEF", "xg_match": 0.08, "xa_match": 0.06,
    "p_clean_sheet": 0.65,
}


def _pool(*rows) -> pd.DataFrame:
    built = []
    for i, row in enumerate(rows, start=1):
        entry = {**FORWARD, **row}
        entry["id"] = i
        entry.setdefault("web_name", f"P{i}")
        built.append(entry)
    return pd.DataFrame(built).set_index("id", drop=False)


# --- 1. never a defender ------------------------------------------------

def test_defenders_are_not_captaincy_candidates():
    """The headline failure. Even a defender projecting above every
    attacker must not be offered the armband."""
    pool = _pool(
        {"web_name": "Striker"},
        {**DEFENDER, "web_name": "CentreBack", "xg_match": 0.3, "p_clean_sheet": 0.9},
    )
    names = [c.name for c in captain_call.rank(pool, gameweek=1)]
    assert "CentreBack" not in names
    assert "Striker" in names


def test_goalkeepers_are_not_captaincy_candidates():
    pool = _pool({"web_name": "Striker"}, {**DEFENDER, "position": "GKP", "web_name": "Keeper"})
    assert "Keeper" not in [c.name for c in captain_call.rank(pool, gameweek=1)]


def test_pick_captain_will_not_hand_the_armband_to_a_defender():
    """The actual bug: the captaincy tab filtered to attackers, but the
    front page used pick_captain, which sorted on projection with no
    position guard at all. Two paths, two answers."""
    squad = pd.DataFrame([
        {"id": 1, "web_name": "CentreBack", "position": "DEF", "xp_captain": 9.9, "xp_next": 9.9},
        {"id": 2, "web_name": "Keeper", "position": "GKP", "xp_captain": 8.0, "xp_next": 8.0},
        {"id": 3, "web_name": "Striker", "position": "FWD", "xp_captain": 6.2, "xp_next": 6.2},
        {"id": 4, "web_name": "Winger", "position": "MID", "xp_captain": 5.8, "xp_next": 5.8},
    ]).set_index("id", drop=False)

    captain, vice = squad_builder.pick_captain(squad, [1, 2, 3, 4])
    assert squad.loc[captain, "position"] in captain_call.ARMBAND_POSITIONS
    assert squad.loc[vice, "position"] in captain_call.ARMBAND_POSITIONS


def test_pick_captain_falls_back_rather_than_raising_on_a_defensive_xi():
    """No legal formation makes this possible, but a caller passing a
    partial squad should get an answer rather than an exception."""
    squad = pd.DataFrame([
        {"id": 1, "web_name": "A", "position": "DEF", "xp_captain": 5.0, "xp_next": 5.0},
        {"id": 2, "web_name": "B", "position": "DEF", "xp_captain": 4.0, "xp_next": 4.0},
    ]).set_index("id", drop=False)
    captain, vice = squad_builder.pick_captain(squad, [1, 2])
    assert {captain, vice} == {1, 2}


# --- 2. rank on the ceiling, not the mean ------------------------------

def test_the_bigger_ceiling_wins_between_equal_projections():
    """The armband doubles, and doubling rewards the tail. A steady
    five-a-week and a blank-or-fifteen are not the same bet."""
    spiky = _pool(
        {"web_name": "Spiky", "xg_match": 0.85, "xa_match": 0.05},
        {"web_name": "Steady", "xg_match": 0.18, "xa_match": 0.45},
    )
    cases = {c.name: c for c in captain_call.rank(spiky, gameweek=1)}
    assert cases["Spiky"].p_haul > cases["Steady"].p_haul
    assert cases["Spiky"].score > cases["Steady"].score


def test_the_case_reports_the_distribution_not_just_a_projection():
    cases = captain_call.rank(_pool({"web_name": "Striker"}), gameweek=1)
    blob = " ".join(cases[0].reasons)
    assert "chance of a double-digit week" in blob
    assert "chance of a blank" in blob


# --- 3. what everyone else is doing ------------------------------------

def test_effective_ownership_combines_ownership_and_captaincy_share():
    pool = _pool({"web_name": "Template", "selected_by_percent": 70.0, "captain_share": 60.0})
    case = captain_call.rank(pool, gameweek=1)[0]
    assert case.effective_ownership == pytest.approx(130.0)
    assert case.is_template


def test_a_template_captain_is_told_he_moves_no_rank():
    pool = _pool({"web_name": "Template", "selected_by_percent": 70.0, "captain_share": 60.0})
    blob = " ".join(captain_call.rank(pool, gameweek=1)[0].reasons)
    assert "tracking the pack" in blob


def test_a_low_owned_pick_is_described_as_leveraged():
    pool = _pool({"web_name": "Differential", "selected_by_percent": 6.0, "captain_share": 2.0})
    blob = " ".join(captain_call.rank(pool, gameweek=1)[0].reasons)
    assert "leveraged" in blob


def test_a_close_differential_is_raised_when_the_favourite_is_the_field():
    """The published framework: it's only a real question when the
    favourite is genuinely the field's pick and the alternative is
    genuinely close."""
    pool = _pool(
        {"web_name": "Template", "selected_by_percent": 70.0, "captain_share": 60.0,
         "xg_match": 0.55},
        {"web_name": "Punt", "selected_by_percent": 5.0, "captain_share": 1.0,
         "xg_match": 0.52},
    )
    cases = captain_call.rank(pool, gameweek=1)
    verdict = captain_call.verdict(cases, strategy=-0.035)  # chasing rank

    assert "Punt" in verdict
    assert "live differential" in verdict


def test_a_distant_differential_is_dismissed_with_the_gap():
    pool = _pool(
        {"web_name": "Template", "selected_by_percent": 70.0, "captain_share": 60.0,
         "xg_match": 0.9},
        {"web_name": "Punt", "selected_by_percent": 5.0, "captain_share": 1.0,
         "xg_match": 0.12},
    )
    verdict = captain_call.verdict(captain_call.rank(pool, gameweek=1), strategy=-0.035)
    assert "too far to be worth the leverage" in verdict


def test_chasing_rank_tolerates_a_wider_gap_than_protecting_it():
    pool = _pool(
        {"web_name": "Template", "selected_by_percent": 70.0, "captain_share": 60.0,
         "xg_match": 0.62},
        {"web_name": "Punt", "selected_by_percent": 5.0, "captain_share": 1.0,
         "xg_match": 0.50},
    )
    cases = captain_call.rank(pool, gameweek=1)
    chase = captain_call.verdict(cases, strategy=-0.035)
    assert "live differential" in chase


# --- adjudication -------------------------------------------------------

def test_a_minutes_doubt_beats_a_good_projection():
    """A model that has never read a press conference should lose to a
    quote about who is starting."""
    case = captain_call.rank(
        _pool({"web_name": "Doubtful", "xg_match": 0.7,
               "consensus_voices": '[{"source":"FFS","take":"Real rotation risk here."}]'}),
        gameweek=1,
    )[0]
    note = captain_call.adjudicate(case)
    assert note is not None
    assert "Going with the analysts" in note


def test_enthusiasm_does_not_beat_a_missing_ceiling():
    case = captain_call.rank(
        _pool({"web_name": "Hyped", "xg_match": 0.03, "xa_match": 0.03, "p_sixty": 0.6,
               "p_start": 0.65,
               "consensus_voices": '[{"source":"FFS","take":"Everyone loves him this week."}]'}),
        gameweek=1,
    )[0]
    note = captain_call.adjudicate(case)
    assert note is not None
    assert "Going with the numbers" in note


def test_no_disagreement_is_reported_when_there_is_none():
    case = captain_call.rank(
        _pool({"web_name": "Clear", "xg_match": 0.7,
               "consensus_voices": '[{"source":"FFS","take":"Nailed on and in form."}]'}),
        gameweek=1,
    )[0]
    assert captain_call.adjudicate(case) is None


def test_no_expert_take_means_nothing_to_adjudicate():
    case = captain_call.rank(_pool({"web_name": "Quiet"}), gameweek=1)[0]
    assert captain_call.adjudicate(case) is None


# --- edges --------------------------------------------------------------

def test_an_empty_pool_returns_nothing_rather_than_raising():
    assert captain_call.rank(_pool({"position": "DEF"}), gameweek=1) == []
    assert "No captaincy candidate" in captain_call.verdict([])


def test_unavailable_players_are_not_candidates():
    pool = _pool({"web_name": "Fit"}, {"web_name": "Injured", "status": "i", "xg_match": 0.9})
    assert "Injured" not in [c.name for c in captain_call.rank(pool, gameweek=1)]
