"""Writes the manager's current squad to disk so research can see it.

The gap this closes: the deployed app reaches the FPL API perfectly well,
but a Claude Code research session does not — the egress proxy refuses
fantasy.premierleague.com. So the app always knew which fifteen players
were owned and the research never did, which meant every weekly refresh
covered "the decision set" rather than the actual squad, and the person
asking for a write-up per owned player kept being asked for their team ID.

GitHub Actions has open egress, so the fix is to fetch it there and commit
it. `data/squad/current.json` then becomes the starting point every refresh
reads, and nobody has to paste fifteen names again.

Deliberately records the gameweek the squad was confirmed for. A squad is
only ever "current" relative to a deadline, and advice built on a stale one
is advice for a team nobody owns — the quality gate checks that field.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant import api
from fpl_assistant.analysis import gameweek_state, my_squad, transfers
from fpl_assistant.config import FPL_TEAM_ID
from fpl_assistant.models import (
    attach_team_names,
    events_df,
    fixtures_df,
    players_df,
    teams_df,
)

SQUAD_PATH = Path(__file__).resolve().parent.parent / "data" / "squad" / "current.json"


def main() -> int:
    if not FPL_TEAM_ID:
        print("No FPL_TEAM_ID configured; nothing to fetch.")
        return 0

    try:
        bootstrap = api.get_bootstrap_static()
        fixtures = fixtures_df(api.get_fixtures())
    except Exception as exc:
        print(f"Couldn't reach the FPL API ({exc}); leaving the stored squad alone.")
        return 0

    teams = teams_df(bootstrap)
    players = attach_team_names(players_df(bootstrap), teams)
    state = gameweek_state.resolve(events_df(bootstrap), fixtures)

    confirmed = my_squad.latest_confirmed(
        int(FPL_TEAM_ID), state.planning_event, api.get_entry_picks
    )
    if confirmed is None:
        print("No confirmed squad found yet.")
        return 0

    try:
        history = api.get_entry_history(int(FPL_TEAM_ID))
        free_transfers = transfers.estimate_free_transfers(
            history.get("current", []), history.get("chips", [])
        )
        chips_used = [c.get("name") for c in history.get("chips", []) if c.get("name")]
    except Exception:
        free_transfers, chips_used = 1, []

    indexed = players.set_index("id")
    squad = []
    for pick in confirmed.squad.picks:
        if pick.player_id not in indexed.index:
            continue
        row = indexed.loc[pick.player_id]
        squad.append({
            "id": int(pick.player_id),
            "name": str(row.get("web_name")),
            "team": str(row.get("team_short_name")),
            "position": str(row.get("position")),
            "price": float(row.get("price", 0) or 0),
            "selected_by_percent": float(row.get("selected_by_percent", 0) or 0),
            "status": str(row.get("status", "a")),
            "is_captain": bool(pick.is_captain),
            "is_vice_captain": bool(pick.is_vice_captain),
            "on_bench": pick.multiplier == 0,
        })

    payload = {
        "note": (
            "The manager's actual squad, fetched where the FPL API is reachable and committed so "
            "research sessions can read it. `confirmed_for_gameweek` is the gameweek FPL had "
            "published picks for — a squad is only current relative to a deadline, and advice "
            "built on a stale one is advice for a team nobody owns."
        ),
        "team_id": int(FPL_TEAM_ID),
        "confirmed_for_gameweek": int(confirmed.event),
        "planning_gameweek": int(state.planning_event),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bank": float(confirmed.squad.bank or 0.0),
        "team_value": float(confirmed.squad.team_value or 0.0),
        "free_transfers": int(free_transfers),
        "chips_used": chips_used,
        "squad": squad,
    }

    try:
        SQUAD_PATH.parent.mkdir(parents=True, exist_ok=True)
        SQUAD_PATH.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    except OSError as exc:
        print(f"Couldn't write the squad file ({exc}).")
        return 0

    print(
        f"Wrote {len(squad)} players for GW{confirmed.event} "
        f"(bank £{payload['bank']:.1f}m, {free_transfers} free transfer(s))."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
