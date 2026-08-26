"""Refreshes this gameweek's research files from live web sources.

Run on a schedule by .github/workflows/research.yml. Writes nothing unless
the new research passes the same validation the test suite enforces —
stale research known to be stale beats fresh research that is wrong.

Exits 0 when there is nothing to do, so a scheduled run that skips is not
a failed run. Exits 1 only when research was attempted and rejected, which
is worth a red mark because it means the data did not refresh.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from fpl_assistant import api
from fpl_assistant.analysis import consensus, gameweek_state
from fpl_assistant.models import events_df, fixtures_df, teams_df
from fpl_assistant.research import agent

CONSENSUS_DIR = Path(__file__).resolve().parent.parent / "data" / "consensus"
ODDS_DIR = Path(__file__).resolve().parent.parent / "data" / "odds"

# Only research inside this window before kick-off. Earlier than this and
# team news hasn't landed, so the file would be refreshed with the same
# uncertainty it already has.
WINDOW_HOURS = 96


def _fixture_summary(fixtures: pd.DataFrame, teams: pd.DataFrame, gameweek: int) -> str:
    """The actual fixtures, so the agent researches the right games."""
    rows = fixtures[pd.to_numeric(fixtures["event"], errors="coerce") == gameweek]
    if rows.empty:
        return ""
    names = teams["short_name"].to_dict()
    lines = [
        f"  {names.get(r['team_h'], r['team_h'])} v {names.get(r['team_a'], r['team_a'])}"
        for _, r in rows.iterrows()
    ]
    return f"The GW{gameweek} fixtures are:\n" + "\n".join(lines)


def _write(path: Path, data: dict, note: str) -> None:
    data = dict(data)
    data.setdefault("season", "2026/27")
    data["note"] = note
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


PLAYER_NOTE = (
    "Researched automatically from live web sources. `case` is the argument for picking them; "
    "`watch_out` is the honest counter-argument, because a recommendation you can't argue against "
    "isn't advice. `key_stats` holds the hard numbers as discrete facts so they can be shown next "
    "to any decision the app makes. `voices` records what named outlets actually said — 'analysts "
    "say' is not a source. `dissent` marks a genuine split, which damps the player's weighting "
    "rather than presenting a contested pick as settled. Club-wide verdicts live in teams.json."
)
ODDS_NOTE = (
    "Anticipated returns, researched automatically from live web sources. Implied probability is "
    "the raw 1/odds figure and includes the bookmaker margin, so it runs a few points high. "
    "`captain_share` is the percentage of managers expected to captain the player — the number "
    "that governs rank and which appears nowhere in the FPL API. `matchups` is what typically "
    "happens when these sides meet, which no per-90 rate can express. Odds move; the research "
    "date above is this file's honest shelf life."
)


def main() -> int:
    bootstrap = api.get_bootstrap_static()
    teams = teams_df(bootstrap)
    events = events_df(bootstrap)
    fixtures = fixtures_df(api.get_fixtures())

    state = gameweek_state.resolve(events, fixtures)
    gameweek = state.planning_event
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    row = events.loc[gameweek] if gameweek in events.index else None
    if row is None:
        print(f"No event row for GW{gameweek}; nothing to do.")
        return 0

    deadline = pd.to_datetime(row.get("deadline_time"), utc=True, errors="coerce")
    if pd.isna(deadline):
        print(f"GW{gameweek} has no usable deadline; nothing to do.")
        return 0

    hours_left = (deadline.to_pydatetime() - now).total_seconds() / 3600
    if hours_left <= 0:
        print(f"GW{gameweek}'s deadline has passed; nothing to research.")
        return 0
    if hours_left > WINDOW_HOURS:
        print(f"GW{gameweek} is {hours_left:.0f}h away, outside the {WINDOW_HOURS}h window.")
        return 0

    print(f"Researching GW{gameweek}, {hours_left:.0f}h before the deadline.")
    failures = []

    players = agent.research_players(gameweek, today)
    if players.ok:
        _write(CONSENSUS_DIR / f"gw{gameweek}.json", players.data, PLAYER_NOTE)
        print(
            f"  players: wrote {len(players.data['players'])} entries "
            f"after {players.searches} searches."
        )
    else:
        failures.append(("players", players.problems))

    odds = agent.research_odds(
        gameweek, today, fixtures=_fixture_summary(fixtures, teams, gameweek)
    )
    if odds.ok:
        _write(ODDS_DIR / f"gw{gameweek}.json", odds.data, ODDS_NOTE)
        print(
            f"  odds: wrote {len(odds.data['players'])} prices and "
            f"{len(odds.data['matchups'])} matchups after {odds.searches} searches."
        )
    else:
        failures.append(("odds", odds.problems))

    for kind, problems in failures:
        print(f"  {kind}: REJECTED, keeping the existing file. Reasons:")
        for problem in problems[:12]:
            print(f"    - {problem}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
