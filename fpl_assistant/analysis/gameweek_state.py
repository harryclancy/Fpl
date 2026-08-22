"""Which gameweek the app should be planning for, and whether one is live.

The bug this exists to fix: the app asked the API for the "current"
gameweek, and the API calls a gameweek current from its deadline until its
last match finishes. So all through the weekend, while GW1 was being
played, the front page kept presenting a GW1 squad -- recomputed against
player stats that were updating live. By Sunday it was recommending a
centre-back as captain because he had already scored and kept a clean
sheet on Saturday.

That is not a recommendation. Nobody could have made it before the
deadline, and the deadline is the only moment the advice could have been
used. Advice that is only available after it is actionable is worse than
no advice: it looks like insight and it is hindsight.

So the app distinguishes three things the API conflates:

  planning_event  the first gameweek you can still act on -- its deadline
                  has not passed. This is what every recommendation
                  targets, because it is the only one you can do anything
                  about.
  live_event      a gameweek that has kicked off but hasn't finished. You
                  can't change your team for it; it is a scoreboard, not a
                  decision.
  finished        all its matches are played, so it rolls forward.

Once the last GW1 match ends, GW1 stops being live and GW2 has become the
planning event on its own -- no special case needed, because the rule is
about deadlines rather than about which gameweek the API is calling
current.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd


@dataclass
class GameweekState:
    planning_event: int
    live_event: int | None = None
    live_fixtures_played: int = 0
    live_fixtures_total: int = 0

    @property
    def is_live(self) -> bool:
        return self.live_event is not None

    @property
    def live_progress(self) -> str:
        if not self.is_live:
            return ""
        return f"{self.live_fixtures_played} of {self.live_fixtures_total} matches played"


def _deadline(event_row) -> datetime | None:
    raw = event_row.get("deadline_time")
    if not raw or (isinstance(raw, float) and pd.isna(raw)):
        return None
    stamp = pd.to_datetime(raw, utc=True, errors="coerce")
    return None if pd.isna(stamp) else stamp.to_pydatetime()


def _fixture_progress(fixtures: pd.DataFrame, event: int) -> tuple[int, int]:
    if fixtures is None or fixtures.empty or "event" not in fixtures.columns:
        return 0, 0
    rows = fixtures[pd.to_numeric(fixtures["event"], errors="coerce") == event]
    if rows.empty:
        return 0, 0
    finished = rows.get("finished")
    if finished is None:
        return 0, len(rows)
    return int(finished.fillna(False).astype(bool).sum()), len(rows)


def resolve(
    events: pd.DataFrame, fixtures: pd.DataFrame, now: datetime | None = None
) -> GameweekState:
    """Work out what to plan for, and whether a gameweek is in progress.

    Driven by deadlines and fixture completion rather than by the API's
    `is_current` flag, which stays true right through a gameweek being
    played and is the reason live results leaked into pre-match advice.
    """
    now = now or datetime.now(timezone.utc)
    if events is None or events.empty:
        return GameweekState(planning_event=1)

    # The events frame arrives indexed by id *and* carrying an id column,
    # so sorting by the name alone is ambiguous and raises. Sort on the
    # index when that's what holds the id.
    if events.index.name == "id":
        ordered = events.sort_index()
    elif "id" in events.columns:
        ordered = events.sort_values("id")
    else:
        ordered = events

    upcoming: int | None = None
    live: int | None = None

    for index, row in ordered.iterrows():
        event_id = int(row["id"]) if "id" in row.index else int(index)
        deadline = _deadline(row)

        if deadline is not None and deadline > now:
            upcoming = event_id
            break

        # Deadline has passed. Is it still being played?
        played, total = _fixture_progress(fixtures, event_id)
        finished_flag = bool(row.get("finished", False))
        # Treat a gameweek as done when its own flag says so, or when every
        # fixture we can see has finished. The flag alone isn't enough --
        # it can lag the final whistle by some minutes, which is exactly
        # the window someone checks the app in.
        is_done = finished_flag or (total > 0 and played >= total)
        if not is_done:
            live = event_id
            live_played, live_total = played, total

    if upcoming is None:
        # Past the last deadline of the season. Plan for the final
        # gameweek rather than inventing one that doesn't exist.
        upcoming = int(
            ordered["id"].iloc[-1] if "id" in ordered.columns else ordered.index[-1]
        )

    if live is None:
        return GameweekState(planning_event=upcoming)
    return GameweekState(
        planning_event=upcoming,
        live_event=live,
        live_fixtures_played=live_played,
        live_fixtures_total=live_total,
    )
