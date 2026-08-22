"""Which gameweek is plannable, and which is merely being played.

The bug: the API calls a gameweek "current" from its deadline right up
until its last match finishes, so all weekend the app presented a GW1
squad recomputed against live stats. By Sunday it recommended captaining a
promoted-side centre-back because he had already scored and kept a clean
sheet on Saturday. Nobody could have made that call before the deadline,
and the deadline is the only moment it could have been used.
"""
from datetime import datetime, timezone

import pandas as pd
import pytest

from fpl_assistant.analysis import gameweek_state


def _events(count=3, finished=None, indexed=True):
    """Matches the production shape: indexed by id AND carrying an id
    column. The first version of this fixture used a bare RangeIndex,
    which is why it passed while the real app raised "'id' is both an
    index level and a column label"."""
    finished = finished or {}
    frame = pd.DataFrame([
        {
            "id": gw,
            # GW1 Fri 21 Aug, then weekly.
            "deadline_time": f"2026-08-{14 + gw * 7:02d}T17:30:00Z",
            "finished": finished.get(gw, False),
        }
        for gw in range(1, count + 1)
    ])
    return frame.set_index("id", drop=False) if indexed else frame


def _fixtures(progress: dict[int, tuple[int, int]]):
    """progress maps gameweek -> (finished_count, total_count)."""
    rows = []
    for gw, (done, total) in progress.items():
        rows += [{"event": gw, "finished": True}] * done
        rows += [{"event": gw, "finished": False}] * (total - done)
    return pd.DataFrame(rows)


def _at(day, hour=12):
    return datetime(2026, 8, day, hour, tzinfo=timezone.utc)


# --- the three states ---------------------------------------------------

def test_before_the_first_deadline_it_plans_for_gameweek_one():
    state = gameweek_state.resolve(_events(), _fixtures({1: (0, 10)}), _at(20))
    assert state.planning_event == 1
    assert not state.is_live


def test_mid_gameweek_it_plans_for_the_next_one_and_flags_the_live_one():
    """The core fix. GW1 has kicked off, so GW1 is no longer something you
    can act on — every recommendation must target GW2."""
    state = gameweek_state.resolve(_events(), _fixtures({1: (4, 10), 2: (0, 10)}), _at(22))

    assert state.planning_event == 2
    assert state.live_event == 1
    assert state.is_live
    assert state.live_progress == "4 of 10 matches played"


def test_once_the_last_match_ends_the_gameweek_stops_being_live():
    """"Make sure it goes to GW2 after the last GW1 game happens."" """
    state = gameweek_state.resolve(_events(), _fixtures({1: (10, 10), 2: (0, 10)}), _at(24))

    assert state.planning_event == 2
    assert not state.is_live


def test_a_gameweek_is_done_when_every_fixture_is_finished_even_if_the_flag_lags():
    """The API's `finished` flag can trail the final whistle by minutes,
    which is exactly the window someone opens the app in."""
    state = gameweek_state.resolve(
        _events(finished={1: False}), _fixtures({1: (10, 10), 2: (0, 10)}), _at(24)
    )
    assert not state.is_live


def test_the_events_finished_flag_alone_is_enough():
    state = gameweek_state.resolve(
        _events(finished={1: True}), _fixtures({1: (0, 0), 2: (0, 10)}), _at(24)
    )
    assert not state.is_live
    assert state.planning_event == 2


# --- it must never plan for a gameweek you can't change ----------------

@pytest.mark.parametrize("day", [22, 23, 24])
def test_the_planning_gameweek_deadline_is_always_still_ahead(day):
    """The invariant that makes the whole thing correct: you can only be
    advised about a gameweek you can still act on."""
    events = _events()
    state = gameweek_state.resolve(events, _fixtures({1: (4, 10), 2: (0, 10)}), _at(day))

    deadline = pd.to_datetime(
        events.loc[events["id"] == state.planning_event, "deadline_time"].iloc[0], utc=True
    )
    assert deadline.to_pydatetime() > _at(day)


# --- edges --------------------------------------------------------------

def test_past_the_final_deadline_it_does_not_invent_a_gameweek():
    state = gameweek_state.resolve(_events(count=2), _fixtures({2: (10, 10)}), _at(31))
    assert state.planning_event == 2


def test_no_events_does_not_crash():
    assert gameweek_state.resolve(pd.DataFrame(), pd.DataFrame(), _at(20)).planning_event == 1


def test_missing_fixture_data_falls_back_to_the_finished_flag():
    state = gameweek_state.resolve(_events(finished={1: True}), pd.DataFrame(), _at(24))
    assert state.planning_event == 2
    assert not state.is_live


def test_a_gameweek_with_no_fixtures_listed_and_no_flag_is_treated_as_live():
    """Better to say "in progress, can't advise on it" than to skip past a
    gameweek whose data hasn't loaded and give advice for the wrong one."""
    state = gameweek_state.resolve(_events(), pd.DataFrame(), _at(22))
    assert state.live_event == 1
    assert state.planning_event == 2


def test_it_handles_an_events_frame_indexed_by_id():
    """Regression: the real frame is indexed by id and also has an id
    column, so sorting by the name alone raises "'id' is both an index
    level and a column label". The original fixture here used a bare
    RangeIndex and sailed past it."""
    state = gameweek_state.resolve(
        _events(indexed=True), _fixtures({1: (4, 10), 2: (0, 10)}), _at(22)
    )
    assert state.planning_event == 2
    assert state.live_event == 1


def test_it_also_handles_a_frame_that_is_not_indexed_by_id():
    state = gameweek_state.resolve(
        _events(indexed=False), _fixtures({1: (4, 10), 2: (0, 10)}), _at(22)
    )
    assert state.planning_event == 2
