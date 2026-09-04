"""Thin client for the official (public, unauthenticated) Fantasy Premier League API.

Endpoints used are the same ones the fantasy.premierleague.com site itself calls.
No API key is needed. Be a reasonable citizen: responses are cached to disk
(see cache.py) so a dashboard refresh doesn't refetch everything every time.
"""
import time

import requests

from fpl_assistant.cache import cached_fetch
from fpl_assistant.config import BASE_URL, CACHE_TTL_SECONDS

_session = requests.Session()
_session.headers.update({"User-Agent": "fpl-assistant-manager/0.1 (personal use)"})

# A DEPLOY DEPENDS ON THIS CALL SUCCEEDING.
#
# The disk cache lives in a gitignored directory, so a freshly deployed
# container starts with nothing and the first page load must reach
# fantasy.premierleague.com. The API rate-limits and intermittently 403s
# traffic from datacentre IP ranges — which is exactly what a hosting
# platform is — and an unhandled failure there does not merely show an
# error: it aborts the startup script, the platform records the build as
# failed, and it keeps serving the PREVIOUS build. The app then looks as
# though it has stopped deploying.
#
# So one transient refusal must not be able to cost a deployment.
RETRIES = 3
BACKOFF_SECONDS = (0.5, 2.0, 5.0)


def _get(path: str) -> dict:
    last = None
    for attempt in range(RETRIES):
        try:
            resp = _session.get(f"{BASE_URL}{path}", timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            # A 404 is an answer, not a hiccup; retrying it wastes the
            # startup budget the deploy is being timed against.
            if status is not None and 400 <= status < 500 and status not in (403, 429):
                raise
            if attempt < RETRIES - 1:
                time.sleep(BACKOFF_SECONDS[attempt])
    raise last


def get_bootstrap_static() -> dict:
    """Players, teams, gameweeks (events), positions. The core reference data."""
    return cached_fetch(
        "bootstrap-static",
        CACHE_TTL_SECONDS["bootstrap-static"],
        lambda: _get("/bootstrap-static/"),
    )


def get_fixtures(event: int | None = None) -> list[dict]:
    """All fixtures, or just one gameweek's if `event` is given."""
    key = "fixtures" if event is None else f"fixtures-event-{event}"
    path = "/fixtures/" if event is None else f"/fixtures/?event={event}"
    return cached_fetch(key, CACHE_TTL_SECONDS["fixtures"], lambda: _get(path))


def get_event_live(event: int) -> dict:
    """Live per-player stats (points, minutes, bonus, etc.) for a gameweek."""
    return cached_fetch(
        f"live-event-{event}",
        CACHE_TTL_SECONDS["live"],
        lambda: _get(f"/event/{event}/live/"),
    )


def get_element_summary(player_id: int) -> dict:
    """One player's fixtures, this season's match log, and `history_past`.

    `history_past` is the completed-season record the projection uses as
    its prior. Cached hard: past seasons never change, so refetching them
    is pure waste.
    """
    return cached_fetch(
        f"element-summary-{player_id}",
        CACHE_TTL_SECONDS.get("element-summary", 86400),
        lambda: _get(f"/element-summary/{player_id}/"),
    )


def get_entry(team_id: int) -> dict:
    """Summary for a manager's team: name, overall rank, current bank/value."""
    return cached_fetch(
        f"entry-{team_id}", CACHE_TTL_SECONDS["entry"], lambda: _get(f"/entry/{team_id}/")
    )


def get_entry_picks(team_id: int, event: int) -> dict:
    """A manager's squad, captain, and chip usage for a specific gameweek."""
    return cached_fetch(
        f"entry-{team_id}-picks-{event}",
        CACHE_TTL_SECONDS["entry"],
        lambda: _get(f"/entry/{team_id}/event/{event}/picks/"),
    )


def get_entry_history(team_id: int) -> dict:
    """Season-by-season and gameweek-by-gameweek history, including chips used."""
    return cached_fetch(
        f"entry-{team_id}-history",
        CACHE_TTL_SECONDS["entry"],
        lambda: _get(f"/entry/{team_id}/history/"),
    )


def get_entry_transfers(team_id: int) -> list[dict]:
    """Full transfer history for a manager."""
    return cached_fetch(
        f"entry-{team_id}-transfers",
        CACHE_TTL_SECONDS["entry"],
        lambda: _get(f"/entry/{team_id}/transfers/"),
    )


def current_event(bootstrap: dict) -> int:
    """The gameweek id that is currently active, or the next one if between gameweeks."""
    events = bootstrap["events"]
    for e in events:
        if e["is_current"]:
            return e["id"]
    for e in events:
        if e["is_next"]:
            return e["id"]
    return events[-1]["id"]
