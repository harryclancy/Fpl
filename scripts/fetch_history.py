"""Pulls each player's completed-season record from the official FPL API.

The hand-seeded `data/history/seasons.json` covers a handful of players I
could verify from published season reviews. This replaces it with the
official numbers for everyone who matters, which are exact, free, and
need no API key.

`/api/element-summary/{id}/` carries a `history_past` block: one row per
completed season with minutes, goals, assists, clean sheets and total
points. It is one request per player, so this fetches only the players a
decision could plausibly turn on -- everyone owned, everyone above an
ownership floor, and the most expensive in each position -- rather than
all ~700. That keeps a run to well under a minute and is polite to an API
that is being used as a guest.

Run it from the weekly workflow, or by hand:

    python scripts/fetch_history.py

Exits 0 and leaves the existing file untouched if the API can't be
reached, because a stale prior is enormously better than no prior.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from fpl_assistant import api
from fpl_assistant.analysis import history
from fpl_assistant.analysis.history import HISTORY_DIR
from fpl_assistant.models import players_df, teams_df

# How many completed seasons to keep. Two: the third is far enough back
# that squads, roles and ages have all moved, and it would dilute the
# recent evidence more than it adds.
SEASONS_KEPT = 2

# Who to fetch. A player below all of these thresholds cannot realistically
# be picked, so his prior would never be read.
MIN_OWNERSHIP = 1.0
MIN_PRICE = 6.5
TOP_N_PER_POSITION = 40

# Courtesy pause between requests. The API is public and unauthenticated;
# hammering it is both rude and a good way to get rate-limited.
REQUEST_DELAY_SECONDS = 0.15


def _worth_fetching(players: pd.DataFrame) -> list[int]:
    ownership = pd.to_numeric(
        players.get("selected_by_percent", 0), errors="coerce"
    ).fillna(0.0)
    price = pd.to_numeric(players.get("price", 0), errors="coerce").fillna(0.0)

    keep = set(players.loc[(ownership >= MIN_OWNERSHIP) | (price >= MIN_PRICE), "id"])
    for position in players["position"].dropna().unique():
        subset = players[players["position"] == position]
        keep.update(subset.nlargest(TOP_N_PER_POSITION, "price")["id"])
    return sorted(int(i) for i in keep)


def main() -> int:
    try:
        bootstrap = api.get_bootstrap_static()
    except Exception as exc:
        print(f"Couldn't reach the FPL API ({exc}); leaving the existing history alone.")
        return 0

    teams = teams_df(bootstrap)
    players = players_df(bootstrap)
    players["team_short_name"] = players["team"].map(teams["short_name"])

    ids = _worth_fetching(players)
    print(f"Fetching completed-season records for {len(ids)} players…")

    indexed = players.set_index("id")
    entries, failures = [], 0
    for player_id in ids:
        try:
            summary = api.get_element_summary(player_id)
        except Exception:
            failures += 1
            continue
        past = (summary or {}).get("history_past") or []
        if not past:
            continue

        row = indexed.loc[player_id]
        seasons = []
        # `history_past` is oldest-first; the prior wants newest-first.
        for record in list(past)[-SEASONS_KEPT:][::-1]:
            seasons.append(
                {
                    "season": str(record.get("season_name", "")),
                    "minutes": int(record.get("minutes", 0) or 0),
                    "goals": int(record.get("goals_scored", 0) or 0),
                    "assists": int(record.get("assists", 0) or 0),
                    "clean_sheets": int(record.get("clean_sheets", 0) or 0),
                    "total_points": int(record.get("total_points", 0) or 0),
                    "appearances": int(record.get("starts", 0) or 0)
                    or round(int(record.get("minutes", 0) or 0) / 90),
                }
            )
        entries.append(
            {
                "name": str(row.get("web_name", "")),
                "aliases": [
                    f"{row.get('first_name', '')} {row.get('second_name', '')}".strip()
                ],
                "team": str(row.get("team_short_name", "")),
                # Not decoration. analysis/history.py reports how evenly the
                # prior covers the pitch, and that check exists because of a
                # real bug: a prior that held only attackers made the model
                # recommend selling Gabriel. Omitting this field does not
                # produce a missing warning, it produces a warning that
                # cannot be computed -- every player lands in an unknown
                # bucket and the guard silently stops guarding.
                "position": str(row.get("position", "")),
                "seasons": seasons,
            }
        )
        time.sleep(REQUEST_DELAY_SECONDS)

    if not entries:
        print("No history came back; leaving the existing file alone.")
        return 0

    payload = {
        "note": (
            "Completed-season records straight from the official FPL API "
            "(`element-summary`/`history_past`). Regenerated by "
            "scripts/fetch_history.py. Used as the prior that a small "
            "in-season sample is shrunk toward — see analysis/history.py."
        ),
        "source": "fantasy.premierleague.com/api/element-summary/{id}/",
        "generated": pd.Timestamp.utcnow().strftime("%Y-%m-%d"),
        "players": entries,
    }
    # Check the replacement before overwriting, not after. The first
    # version of this script wrote 227 players with no `position` on any of
    # them, replacing a smaller hand-seeded file that had them. Coverage
    # went UP and the prior still looked fine from the outside -- the only
    # symptom was that the positional-balance guard, which exists because a
    # lopsided prior once had the model recommending Gabriel be sold, could
    # no longer compute an answer. Every player sat in an unknown bucket.
    #
    # A scheduled job that overwrites curated data must prove the
    # replacement is at least as good, or refuse and leave what is there.
    fresh = history.parse(payload)
    report = history.coverage(fresh)
    if not report.balanced:
        print(f"::error title=History refresh would break the prior::{report.warning} "
              f"Refusing to overwrite the existing file with {len(entries)} records "
              f"that cover {report.per_position}.")
        return 1

    current = history.coverage()
    if current.total and report.total < current.total:
        print(f"::error title=History refresh would lose coverage::The API returned "
              f"{report.total} usable players; the committed file already has "
              f"{current.total}. Refusing to overwrite it.")
        return 1

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    (HISTORY_DIR / "seasons.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    print(f"Wrote {len(entries)} players' history ({failures} fetches failed). "
          f"Coverage: {report.per_position}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
