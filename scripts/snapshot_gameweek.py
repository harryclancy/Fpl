"""Writes the pre-deadline snapshot for the upcoming gameweek.

Run on a schedule by .github/workflows/snapshot.yml. It exists because the
app is deployed on a host with an ephemeral filesystem: a snapshot written
at runtime disappears on the next container restart, which is usually
before anyone wants to look at it. Committing it to the repo makes it
durable with no setup, since the deployment pulls from the repo anyway.

Deliberately conservative about when it writes:

  * only when the upcoming deadline is close, so the snapshot reflects
    late team news rather than a guess made days out
  * never once the deadline has passed, which is the rule the whole
    snapshot mechanism exists to enforce

Exits 0 with no output when there's nothing to do, so a scheduled run that
skips is not a failed run.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from fpl_assistant import api
from fpl_assistant.analysis import gameweek_state, snapshots, squad_builder
from fpl_assistant.models import (
    attach_team_names,
    events_df,
    fixtures_df,
    players_df,
    teams_df,
)

# Only snapshot inside this window before kick-off. Wide enough that a
# few-hourly schedule can't miss it, tight enough that the squad reflects
# the team news people actually decide on.
WINDOW_HOURS = 30


def main() -> int:
    bootstrap = api.get_bootstrap_static()
    teams = teams_df(bootstrap)
    players = attach_team_names(players_df(bootstrap), teams)
    events = events_df(bootstrap)
    fixtures = fixtures_df(api.get_fixtures())

    state = gameweek_state.resolve(events, fixtures)
    gameweek = state.planning_event

    row = events.loc[gameweek] if gameweek in events.index else None
    if row is None:
        print(f"No event row for GW{gameweek}; nothing to do.")
        return 0

    deadline = pd.to_datetime(row.get("deadline_time"), utc=True, errors="coerce")
    if pd.isna(deadline):
        print(f"GW{gameweek} has no usable deadline; nothing to do.")
        return 0

    hours_left = (deadline.to_pydatetime() - datetime.now(timezone.utc)).total_seconds() / 3600
    if hours_left <= 0:
        print(f"GW{gameweek}'s deadline has passed; refusing to write.")
        return 0
    if hours_left > WINDOW_HOURS:
        print(f"GW{gameweek} is {hours_left:.0f}h away, outside the {WINDOW_HOURS}h window.")
        return 0

    scored = squad_builder.score_players(players, fixtures, teams, gameweek)
    solution = squad_builder.recommend_squad(scored)
    names = {
        int(pid): str(scored.loc[pid, "web_name"])
        for pid in solution.squad_ids
        if pid in scored.index
    }

    projected = {
        int(pid): float(scored.loc[pid, "xp_next"])
        for pid in solution.squad_ids
        if pid in scored.index
    }
    saved = snapshots.save(
        gameweek, solution, names=names, projected=projected, deadline_passed=False
    )
    if saved is None:
        print(f"Couldn't write the GW{gameweek} snapshot.")
        return 0

    captain = names.get(saved.captain_id, saved.captain_id)
    print(
        f"Snapshotted GW{gameweek} ({hours_left:.0f}h before the deadline): "
        f"{saved.formation}, captain {captain}, £{saved.total_cost:.1f}m."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
