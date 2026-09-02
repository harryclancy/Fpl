"""Sample-size shrinkage in the expected-points model.

The root cause of the transfer engine's implausible numbers. Every per-90
rate — expected goals, assists, goals conceded, saves, defensive
contributions, bonus — was read straight from the official data and used at
full strength no matter how few minutes produced it. A defender who took
1.68 expected goal involvements in one gameweek has an xGI/90 near 0.85,
which the model multiplied by a defender's six-point goal value and
projected across five gameweeks.

The corroboration guard downstream caught the result. These tests stop it
being produced.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant.analysis import expected_points as xp


def _rates(values, minutes, positions):
    return (pd.Series(values, dtype=float), pd.Series(minutes, dtype=float),
            pd.Series(positions))


def test_a_one_match_rate_is_pulled_most_of_the_way_to_the_prior():
    """90 minutes is a sixth of the prior's weight, so a wild rate from one
    game keeps roughly a sixth of its distance above the baseline."""
    rate, minutes, position = _rates(
        [0.85] + [0.10] * 8,
        [90] + [900] * 8,
        ["DEF"] * 9)
    shrunk = xp.shrink_rate(rate, minutes, position)
    assert shrunk.iloc[0] < 0.30, shrunk.iloc[0]
    assert shrunk.iloc[0] > 0.10, "it must not be erased entirely"


def test_a_full_season_of_the_same_rate_survives():
    """Shrinkage must fade with evidence, or it flattens genuinely elite
    players all season."""
    rate, minutes, position = _rates(
        [0.85] + [0.10] * 8,
        [3000] + [900] * 8,
        ["DEF"] * 9)
    shrunk = xp.shrink_rate(rate, minutes, position)
    assert shrunk.iloc[0] > 0.70, shrunk.iloc[0]


def test_shrinkage_is_monotonic_in_minutes():
    """More evidence must never mean less of your own rate."""
    rate, minutes, position = _rates(
        [0.8, 0.8, 0.8, 0.8], [90, 450, 900, 2700], ["MID"] * 4)
    # A common prior so the comparison is like for like.
    shrunk = xp.shrink_rate(rate, minutes, position, prior=pd.Series([0.1] * 4))
    assert list(shrunk) == sorted(shrunk), list(shrunk)


def test_the_prior_ignores_the_thin_samples_it_is_meant_to_correct():
    """A prior built from the same noisy rates would inherit their noise."""
    rate, minutes, position = _rates(
        [2.0, 2.0, 0.10, 0.12, 0.11], [45, 60, 900, 950, 1000], ["DEF"] * 5)
    prior = xp._positional_prior(rate, position, minutes)
    assert prior.iloc[0] < 0.2, prior.iloc[0]


def test_a_player_with_no_minutes_is_projected_as_his_position():
    rate, minutes, position = _rates(
        [0.0] + [0.20] * 5, [0] + [900] * 5, ["FWD"] * 6)
    shrunk = xp.shrink_rate(rate, minutes, position)
    assert abs(shrunk.iloc[0] - 0.20) < 0.01, "no sample means the positional prior"


def test_sample_states_track_minutes():
    assert xp.sample_state(3000) == "established"
    assert xp.sample_state(600) == "moderate"
    assert xp.sample_state(200) == "small"
    assert xp.sample_state(90) == "very small"
    assert xp.sample_state(0) == "none"


def test_the_prior_is_positional_not_global():
    """A forward's baseline attacking rate is not a defender's."""
    rate, minutes, position = _rates(
        [0.60, 0.65, 0.05, 0.06], [900, 950, 900, 950], ["FWD", "FWD", "DEF", "DEF"])
    prior = xp._positional_prior(rate, position, minutes)
    assert prior.iloc[0] > prior.iloc[2] * 3
