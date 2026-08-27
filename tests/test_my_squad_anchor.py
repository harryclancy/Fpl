"""Anchoring recommendations on the squad you actually own.

The complaint this answers: from GW2 the front page was suggesting a
completely different starting eleven. That isn't advice, it's a
description of a squad you can't have — you own fifteen players, you have
one free transfer, and every extra move costs four points.

The subtle part is finding the right base. FPL publishes a gameweek's
picks once its deadline passes, and returns 404 both for a gameweek that
hasn't been published *and* for one you didn't enter. Those are different
situations and the resolver has to survive both.
"""
import pytest

from fpl_assistant.analysis import my_squad


def _picks(count=15, captain_index=0):
    return {
        "picks": [
            {
                "element": i + 1,
                "position": i + 1,
                "is_captain": i == captain_index,
                "is_vice_captain": i == captain_index + 1,
                "multiplier": 1 if i < 11 else 0,
            }
            for i in range(count)
        ],
        "entry_history": {"bank": 15, "value": 1003, "event_transfers": 1,
                          "event_transfers_cost": 0},
    }


def _fetcher(available: dict):
    """Serves picks for the gameweeks in `available`, 404s for the rest —
    which is what the real API does."""
    calls = []

    def fetch(team_id, event):
        calls.append(event)
        if event not in available:
            raise RuntimeError("404 Not Found")
        return available[event]

    fetch.calls = calls
    return fetch


# --- finding the base ---------------------------------------------------

def test_it_uses_the_most_recent_published_squad():
    fetch = _fetcher({1: _picks()})
    confirmed = my_squad.latest_confirmed(123, planning_event=2, fetch_picks=fetch)

    assert confirmed is not None
    assert confirmed.event == 1
    assert len(confirmed.squad.picks) == 15


def test_it_prefers_the_latest_gameweek_when_several_are_published():
    fetch = _fetcher({1: _picks(), 2: _picks(), 3: _picks()})
    confirmed = my_squad.latest_confirmed(123, planning_event=3, fetch_picks=fetch)
    assert confirmed.event == 3


def test_it_walks_back_past_gameweeks_that_are_not_published():
    """The obvious implementation asks for last week and gives up on a
    404. That breaks for a skipped week or a mid-season start."""
    fetch = _fetcher({2: _picks()})
    confirmed = my_squad.latest_confirmed(123, planning_event=6, fetch_picks=fetch)

    assert confirmed.event == 2
    assert fetch.calls[:4] == [6, 5, 4, 3], "expected it to step backwards"


def test_it_gives_up_after_a_bounded_search():
    """A team id that was never used must not cost a request per gameweek."""
    fetch = _fetcher({})
    assert my_squad.latest_confirmed(123, planning_event=30, fetch_picks=fetch) is None
    assert len(fetch.calls) <= my_squad.MAX_LOOKBACK + 1


def test_no_team_id_means_no_squad():
    fetch = _fetcher({1: _picks()})
    assert my_squad.latest_confirmed(None, planning_event=2, fetch_picks=fetch) is None
    assert fetch.calls == []


def test_an_empty_picks_payload_is_not_a_squad():
    """The API can answer 200 with nothing useful. Treating that as a
    confirmed squad would anchor every recommendation on an empty list."""
    fetch = _fetcher({2: {"picks": [], "entry_history": {}}, 1: _picks()})
    confirmed = my_squad.latest_confirmed(123, planning_event=2, fetch_picks=fetch)
    assert confirmed.event == 1


def test_a_malformed_payload_is_skipped_rather_than_raising():
    fetch = _fetcher({2: {"picks": "not a list"}, 1: _picks()})
    confirmed = my_squad.latest_confirmed(123, planning_event=2, fetch_picks=fetch)
    assert confirmed.event == 1


def test_it_does_not_search_below_gameweek_one():
    fetch = _fetcher({})
    my_squad.latest_confirmed(123, planning_event=2, fetch_picks=fetch)
    assert min(fetch.calls) >= 1


# --- what the base means ------------------------------------------------

def test_a_squad_confirmed_for_the_planning_gameweek_is_flagged_as_current():
    fetch = _fetcher({2: _picks()})
    confirmed = my_squad.latest_confirmed(123, planning_event=2, fetch_picks=fetch)
    assert confirmed.is_current


def test_a_squad_from_a_previous_gameweek_is_not_current():
    fetch = _fetcher({1: _picks()})
    confirmed = my_squad.latest_confirmed(123, planning_event=2, fetch_picks=fetch)
    assert not confirmed.is_current
    assert confirmed.planning_event == 2


# --- My Squad shows the squad you actually own ---------------------------

def test_the_squad_you_own_before_a_deadline_is_last_weeks():
    """The tab used to ask the API for the gameweek being planned, get a
    404, and explain the 404. That is correct and useless: FPL doesn't
    publish a gameweek's picks until its deadline passes, so for most of
    every week the tab showed an error instead of your fifteen. The squad
    you own right now IS last gameweek's.
    """
    calls = []

    def fetch(team_id, event):
        calls.append(event)
        if event >= 2:
            raise RuntimeError("404 — picks not public yet")
        return {
            "picks": [
                {"element": i, "position": i, "is_captain": i == 1,
                 "is_vice_captain": i == 2, "multiplier": 1 if i <= 11 else 0}
                for i in range(1, 16)
            ],
            "entry_history": {"bank": 5, "value": 1000},
        }

    confirmed = my_squad.latest_confirmed(123, planning_event=2, fetch_picks=fetch)

    assert confirmed is not None
    assert confirmed.event == 1
    assert not confirmed.is_current
    assert len(confirmed.squad.picks) == 15
    # It asked for the planning gameweek first, then walked back.
    assert calls[0] == 2
