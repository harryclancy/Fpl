"""Tests for the outcome distribution.

Every other number in the app is an expected-points mean, and a mean is
the wrong summary for the decision being made: a 5.0 projection can be a
steady five every week or a blank-blank-fifteen, and those are different
players to own. These tests are about the distribution being a real
probability distribution, and about the narration not overstating what it
knows.
"""
import pandas as pd
import pytest

from fpl_assistant.analysis import scenarios

BASE = {
    "web_name": "P", "position": "FWD", "xg_match": 0.4, "xa_match": 0.15,
    "p_clean_sheet": 0.3, "p_sixty": 0.85, "p_start": 0.9, "p_available": 1.0,
}


def _row(**overrides) -> pd.Series:
    return pd.Series({**BASE, **overrides})


# --- it has to be a distribution ---------------------------------------

@pytest.mark.parametrize("position", ["GKP", "DEF", "MID", "FWD"])
def test_the_probabilities_sum_to_one(position):
    outcome = scenarios.outcome_for(_row(position=position))
    assert sum(weight for _, weight in outcome.distribution) == pytest.approx(1.0, abs=1e-6)


def test_the_mean_of_the_distribution_matches_the_reported_expectation():
    outcome = scenarios.outcome_for(_row())
    mean = sum(points * weight for points, weight in outcome.distribution)
    assert mean == pytest.approx(outcome.expected, abs=0.01)


def test_percentiles_are_ordered():
    outcome = scenarios.outcome_for(_row())
    assert outcome.floor <= outcome.median <= outcome.ceiling


def test_a_truncated_tail_is_folded_back_rather_than_dropped():
    """An absurd rate must not silently lose probability mass off the top
    of the enumeration — that would understate the ceiling."""
    outcome = scenarios.outcome_for(_row(xg_match=3.0, xa_match=2.0))
    assert sum(w for _, w in outcome.distribution) == pytest.approx(1.0, abs=1e-6)
    assert outcome.ceiling >= 15


# --- it has to say true things -----------------------------------------

def test_a_player_who_cannot_play_scores_nothing():
    outcome = scenarios.outcome_for(_row(p_sixty=0.0, p_start=0.0, p_available=0.0))
    assert outcome.expected == 0.0
    assert outcome.p_no_show == pytest.approx(1.0)


def test_a_higher_scoring_rate_raises_the_ceiling_and_the_haul_odds():
    quiet = scenarios.outcome_for(_row(xg_match=0.1))
    lively = scenarios.outcome_for(_row(xg_match=0.8))
    assert lively.ceiling > quiet.ceiling
    assert lively.p_haul > quiet.p_haul
    assert lively.p_blank < quiet.p_blank


def test_rotation_risk_shows_up_as_a_no_show_chance():
    nailed = scenarios.outcome_for(_row(p_sixty=0.95, p_start=0.97))
    rotated = scenarios.outcome_for(_row(p_sixty=0.45, p_start=0.55))
    assert rotated.p_no_show > nailed.p_no_show + 0.3
    assert rotated.expected < nailed.expected


def test_clean_sheets_only_pay_defensive_players():
    defender = scenarios.outcome_for(_row(position="DEF", xg_match=0.0, xa_match=0.0, p_clean_sheet=0.9))
    forward = scenarios.outcome_for(_row(position="FWD", xg_match=0.0, xa_match=0.0, p_clean_sheet=0.9))
    assert defender.expected > forward.expected


def test_a_clean_sheet_needs_sixty_minutes():
    """A cameo cannot bank a clean sheet, so a defender who only ever
    comes on late must not be credited with one."""
    starter = scenarios.outcome_for(_row(position="DEF", p_sixty=0.9, p_start=0.9, p_clean_sheet=0.8))
    substitute = scenarios.outcome_for(_row(position="DEF", p_sixty=0.0, p_start=0.9, p_clean_sheet=0.8))
    assert substitute.expected < starter.expected


def test_a_return_means_an_attacking_return_not_a_clean_sheet():
    """"Return" has a specific meaning in FPL and a defender's clean sheet
    isn't one, however many points it pays."""
    outcome = scenarios.outcome_for(
        _row(position="DEF", xg_match=0.0, xa_match=0.0, p_clean_sheet=0.95)
    )
    assert outcome.p_return == pytest.approx(0.0, abs=1e-6)


# --- narration ----------------------------------------------------------

def test_narration_flags_a_mean_carried_by_the_ceiling():
    """The insight the mean actively hides, and the reason this module
    exists.

    The case is a moderate scoring rate, not a huge one: at 0.5 expected
    goals a forward blanks most weeks and the hauls carry the average, so
    the 5.0 projection describes a week he rarely has. At a very high rate
    he simply scores most weeks and the mean is honest — so this must not
    fire there, which the companion test below pins down.
    """
    spiky = scenarios.outcome_for(_row(xg_match=0.5, xa_match=0.12))
    assert spiky.expected - spiky.median >= 1.5
    assert "carried by the ceiling" in scenarios.narrate(spiky)


def test_narration_does_not_cry_ceiling_when_the_mean_is_honest():
    elite = scenarios.outcome_for(_row(xg_match=1.1, xa_match=0.3))
    assert "carried by the ceiling" not in scenarios.narrate(elite)


def test_narration_does_not_repeat_itself_when_floor_equals_median():
    outcome = scenarios.outcome_for(_row(xg_match=0.05, xa_match=0.05))
    text = scenarios.narrate(outcome)
    assert "The typical week here is" in text
    assert "a bad week is" not in text


def test_narration_mentions_a_material_chance_of_not_playing():
    rotated = scenarios.outcome_for(_row(p_sixty=0.4, p_start=0.5))
    assert "doesn't play at all" in scenarios.narrate(rotated)


def test_narration_stays_quiet_about_minutes_for_a_nailed_starter():
    nailed = scenarios.outcome_for(_row(p_sixty=0.96, p_start=0.99))
    assert "doesn't play at all" not in scenarios.narrate(nailed)


# --- comparison ---------------------------------------------------------

def test_comparison_reports_only_differences_worth_acting_on():
    """A comparison that lists every metric regardless of whether it
    separates the two players is how these read as generic."""
    twin = scenarios.outcome_for(_row())
    other = scenarios.outcome_for(_row())
    lines = scenarios.compare(twin, other)
    assert len(lines) == 1
    assert "close enough" in lines[0]


def test_comparison_names_the_bigger_ceiling():
    spiky = scenarios.outcome_for(_row(web_name="Spiky", xg_match=1.0))
    steady = scenarios.outcome_for(_row(web_name="Steady", xg_match=0.1))
    text = " ".join(scenarios.compare(spiky, steady))
    assert "Spiky" in text and "bigger ceiling" in text


def test_comparison_names_the_minutes_risk():
    nailed = scenarios.outcome_for(_row(web_name="Nailed", p_sixty=0.95, p_start=0.97))
    rotated = scenarios.outcome_for(_row(web_name="Rotated", p_sixty=0.4, p_start=0.5))
    text = " ".join(scenarios.compare(nailed, rotated))
    assert "Rotated" in text and "minutes risk" in text
