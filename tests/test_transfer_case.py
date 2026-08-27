"""Why a transfer is being suggested, in words.

"Smith → Jones, +2.3 projected" tells you what the solver concluded and
nothing you can agree or disagree with. The case is what makes it a
recommendation rather than an instruction: what has gone wrong with the
player leaving, what people say about the one arriving, who they are each
playing, and whether the incoming player has any history of doing this
against this opponent.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant.analysis import consensus, matchups, transfer_case


def _scored() -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {"id": 1, "web_name": "Palmer", "team_short_name": "CHE", "position": "MID",
             "price": 10.5, "xp_next": 4.0, "selected_by_percent": 22.0},
            {"id": 2, "web_name": "Haaland", "team_short_name": "MCI", "position": "FWD",
             "price": 15.5, "xp_next": 7.5, "selected_by_percent": 71.0},
            {"id": 3, "web_name": "Nobody", "team_short_name": "HUL", "position": "MID",
             "price": 4.5, "xp_next": 2.0, "selected_by_percent": 0.2},
            {"id": 4, "web_name": "Stranger", "team_short_name": "HUL", "position": "MID",
             "price": 5.0, "xp_next": 3.0, "selected_by_percent": 0.3},
        ]
    )
    frame["consensus_against"] = [
        consensus._pack([{"point": "Brighton have the third-best defence in the league",
                          "source": "Albion Analytics"}]),
        None, None, None,
    ]
    frame["consensus_for"] = [
        None,
        consensus._pack([{"point": "Palace are missing two of their back three",
                          "source": "Sports Mole"}]),
        None, None,
    ]
    frame["record_vs_opponent"] = [
        None,
        "Eight goals in five meetings with Palace — he has scored in every one.",
        None, None,
    ]
    return frame.set_index("id", drop=False)


# --- the case itself ----------------------------------------------------

def test_the_case_says_what_is_wrong_with_the_one_leaving():
    case = transfer_case.explain(_scored(), out_id=1, in_id=2, gameweek=2)

    assert case is not None
    assert case.out.name == "Palmer"
    assert any("third-best defence" in point for point, _ in case.out.reasons)
    assert all(source for _, source in case.out.reasons)


def test_the_case_says_what_is_right_about_the_one_arriving():
    case = transfer_case.explain(_scored(), out_id=1, in_id=2, gameweek=2)

    assert case.into.name == "Haaland"
    assert any("back three" in point for point, _ in case.into.reasons)


def test_the_record_against_this_opponent_is_carried_through():
    """"He usually scores against them" is the first thing anyone says
    when arguing for a captain, and the API knows nothing about it."""
    case = transfer_case.explain(_scored(), out_id=1, in_id=2, gameweek=2)

    assert "Eight goals in five meetings" in case.into.record


def test_it_shows_the_case_against_the_leaver_not_the_case_for_him():
    """Asymmetric on purpose. The question is "why this swap", not "rate
    these two men" — showing both sides of both would be balanced and
    useless."""
    frame = _scored()
    frame.loc[1, "consensus_for"] = consensus._pack(
        [{"point": "he is a wonderful footballer", "source": "Everyone"}]
    )
    case = transfer_case.explain(frame, out_id=1, in_id=2, gameweek=2)

    joined = " ".join(point for point, _ in case.out.reasons)
    assert "wonderful footballer" not in joined
    assert "third-best defence" in joined


def test_a_swap_nobody_has_written_about_says_so_rather_than_bluffing():
    """A points gap wearing a paragraph is worse than admitting the gap.

    Saying "this is the model's opinion alone" is useful — it tells you to
    go and check before acting.
    """
    case = transfer_case.explain(_scored(), out_id=3, in_id=4, gameweek=2)

    assert not case.researched
    assert "model's opinion alone" in case.summary


def test_an_unknown_player_id_returns_nothing_rather_than_raising():
    assert transfer_case.explain(_scored(), out_id=999, in_id=2, gameweek=2) is None
    assert transfer_case.explain(_scored(), out_id=1, in_id=999, gameweek=2) is None


def test_the_gain_is_reported_but_framed_as_the_tiebreak():
    case = transfer_case.explain(_scored(), out_id=1, in_id=2, gameweek=2)
    assert case.gain == pytest.approx(3.5)


# --- pairing a whole plan -----------------------------------------------

def test_swaps_are_paired_by_position_so_they_read_as_swaps():
    """The optimiser returns two unordered sets. "Sell the defender, buy
    the defender" is a sentence; "sell these two, buy these two" is not."""
    frame = pd.DataFrame(
        [
            {"id": 1, "web_name": "OutMid", "team_short_name": "CHE", "position": "MID",
             "price": 8.0, "xp_next": 3.0, "selected_by_percent": 5.0},
            {"id": 2, "web_name": "OutDef", "team_short_name": "AVL", "position": "DEF",
             "price": 5.0, "xp_next": 2.0, "selected_by_percent": 5.0},
            {"id": 3, "web_name": "InDef", "team_short_name": "ARS", "position": "DEF",
             "price": 6.0, "xp_next": 5.0, "selected_by_percent": 18.0},
            {"id": 4, "web_name": "InMid", "team_short_name": "MUN", "position": "MID",
             "price": 8.0, "xp_next": 6.0, "selected_by_percent": 21.0},
        ]
    ).set_index("id", drop=False)

    cases = transfer_case.explain_plan(frame, [1, 2], [3, 4], gameweek=2)

    pairs = {(c.out.name, c.into.name) for c in cases}
    assert pairs == {("OutMid", "InMid"), ("OutDef", "InDef")}


def test_an_empty_plan_produces_no_cases():
    assert transfer_case.explain_plan(_scored(), [], [], gameweek=2) == []


# --- the real research, end to end --------------------------------------

def test_the_shipped_research_produces_a_real_argument():
    """Against the actual GW2 file, not a fixture.

    Selling a Chelsea attacker for Haaland this week has a genuine case on
    both sides, and it should assemble from the committed research without
    anything being invented.
    """
    frame = pd.DataFrame(
        [
            {"id": 1, "web_name": "Palmer", "team_short_name": "CHE", "position": "MID",
             "price": 10.5, "xp_next": 4.0, "team": 1, "selected_by_percent": 22.0},
            {"id": 2, "web_name": "Haaland", "team_short_name": "MCI", "position": "FWD",
             "price": 15.5, "xp_next": 7.5, "team": 2, "selected_by_percent": 71.0},
        ]
    ).set_index("id", drop=False)
    annotated = consensus.annotate(frame, 2)

    case = transfer_case.explain(annotated, out_id=1, in_id=2, gameweek=2)

    assert case.researched
    assert case.out.reasons, "nothing researched against Palmer"
    assert case.into.reasons, "nothing researched for Haaland"
    assert "Palace" in case.into.record
    # And the fixture-level commentary comes along with it.
    assert case.into.opposition or case.out.opposition
