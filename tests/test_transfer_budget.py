"""How many transfers to make, decided by the app.

There used to be a slider: "most transfers to consider, 1 to 4". That is
the wrong division of labour. How many transfers to make is a judgement
about how much damage the squad has taken and what a hit is worth — the
app has the information and the reader mostly does not. A control there
is the app declining to decide and calling it flexibility.

The rule: two is the ceiling in a normal week. It rises only when enough
of the fifteen is genuinely unavailable that patching is not optional.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant.analysis import transfer_budget


def _squad(statuses=None, chances=None, stances=None, n=15):
    frame = pd.DataFrame(
        {
            "id": range(1, n + 1),
            "web_name": [f"P{i}" for i in range(1, n + 1)],
            "status": (statuses or ["a"] * n),
            "chance_of_playing_next_round": (chances or [100.0] * n),
        }
    )
    if stances is not None:
        frame["club_stance"] = stances
    return frame


def test_a_normal_week_is_capped_at_two():
    budget = transfer_budget.decide(_squad(), free_transfers=1)

    assert budget.limit == 2
    assert not budget.is_chaos
    assert "normal week" in budget.reason
    assert "churn" in budget.reason


def test_one_injury_is_still_a_two_transfer_week():
    """One problem is a one-transfer problem. The cap should not jump the
    moment anything at all goes wrong."""
    statuses = ["a"] * 15
    statuses[3] = "i"
    budget = transfer_budget.decide(_squad(statuses), free_transfers=1)

    assert budget.limit == 2
    assert not budget.is_chaos
    assert "P4" in budget.reason


def test_chaos_raises_the_ceiling():
    statuses = ["a"] * 15
    statuses[0] = "i"   # injured
    statuses[1] = "s"   # suspended
    statuses[2] = "u"   # unavailable
    budget = transfer_budget.decide(_squad(statuses), free_transfers=1)

    assert budget.limit > 2
    assert budget.is_chaos
    assert len(budget.broken) == 3
    assert "repair" in budget.reason


def test_it_never_goes_beyond_four():
    """Past four you are wildcarding, and the honest advice is "play the
    chip", not "take a twenty-point hit"."""
    budget = transfer_budget.decide(_squad(["i"] * 15), free_transfers=1)

    assert budget.limit == transfer_budget.ABSOLUTE_MAX_TRANSFERS == 4


def test_a_serious_doubt_counts_as_broken():
    """A 50%-doubtful player and an injured one are different in the
    abstract and identical in the way that matters: you cannot plan an
    eleven around either."""
    chances = [100.0] * 15
    chances[0] = chances[1] = chances[2] = 25.0
    budget = transfer_budget.decide(_squad(chances=chances), free_transfers=1)

    assert len(budget.broken) == 3
    assert budget.is_chaos


def test_a_club_the_research_has_written_off_counts_too():
    stances = [""] * 15
    stances[0] = stances[1] = stances[2] = "avoid"
    budget = transfer_budget.decide(_squad(stances=stances), free_transfers=1)

    assert len(budget.broken) == 3


def test_a_player_is_not_counted_twice_for_being_injured_and_doubtful():
    statuses = ["a"] * 15
    statuses[0] = "i"
    chances = [100.0] * 15
    chances[0] = 0.0
    budget = transfer_budget.decide(_squad(statuses, chances), free_transfers=1)

    assert budget.broken == ["P1"]


def test_the_cap_never_blocks_free_transfers():
    """Banking is the optimiser's call to make, but the ceiling should
    never stop it spending transfers that cost nothing."""
    budget = transfer_budget.decide(_squad(), free_transfers=4)
    assert budget.limit >= 4


def test_an_empty_squad_does_not_raise():
    budget = transfer_budget.decide(pd.DataFrame(), free_transfers=1)
    assert budget.limit == 2
    assert budget.broken == []


def test_the_headline_says_the_number_and_the_reason():
    calm = transfer_budget.decide(_squad(), free_transfers=1)
    assert "up to 2 transfers" in calm.headline

    statuses = ["i", "i", "s"] + ["a"] * 12
    chaos = transfer_budget.decide(_squad(statuses), free_transfers=1)
    assert "can't be relied on" in chaos.headline
