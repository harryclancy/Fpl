"""Your actual squad, as the base every recommendation works from.

Once you have played a gameweek, "here is the best fifteen buildable from
scratch" stops being advice. You own fifteen players, you have one free
transfer, and every extra move costs four points -- so a page that hands
you a completely different starting eleven is describing a squad you
cannot have. The honest question from GW2 onward is narrower and much more
useful: given what you already own, what is the one move worth making?

So the app anchors on your confirmed squad. FPL publishes a gameweek's
picks once its deadline has passed, so the most recent published set is
what you actually own going into the next one, and that becomes the base
for every gameweek you play rather than something re-derived each week.

Walking backwards matters. The obvious implementation asks for the last
gameweek's picks and gives up if that 404s, but the API returns 404 for a
gameweek you didn't enter as well as for one that hasn't been published,
and those are different situations. Stepping back until something answers
handles a mid-season start, a skipped week, and a deadline that has just
passed without special-casing any of them.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

from fpl_assistant.models import Squad, parse_squad

# How far back to look for a published squad before concluding there isn't
# one. Generous enough to survive a run of unentered gameweeks, bounded so
# a team id that was never used doesn't cost 38 requests.
MAX_LOOKBACK = 8


@dataclass
class ConfirmedSquad:
    """The squad you actually own, and which gameweek it was confirmed in."""

    squad: Squad
    event: int
    planning_event: int

    @property
    def is_current(self) -> bool:
        """True when the squad was confirmed for the gameweek being planned.

        That happens once you've made this week's changes and the deadline
        has passed -- at which point the base is the plan, not a starting
        point for one.
        """
        return self.event >= self.planning_event


def latest_confirmed(
    team_id: int,
    planning_event: int,
    fetch_picks,
    max_lookback: int = MAX_LOOKBACK,
) -> ConfirmedSquad | None:
    """The most recent squad FPL will confirm for this team.

    `fetch_picks` is injected rather than imported so this stays testable
    without a network, and so a caller can hand it a cached fetcher.
    """
    if not team_id:
        return None

    earliest = max(1, planning_event - max_lookback)
    for event in range(planning_event, earliest - 1, -1):
        try:
            payload = fetch_picks(team_id, event)
        except Exception:
            continue
        if not payload or not payload.get("picks"):
            continue
        try:
            squad = parse_squad(team_id, event, payload)
        except Exception:
            continue
        if squad.picks:
            return ConfirmedSquad(squad=squad, event=event, planning_event=planning_event)
    return None


# --- The squad as committed by CI ---------------------------------------

STORED_SQUAD_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "squad" / "current.json"
)


@dataclass
class StoredSquad:
    """The owned fifteen, read from disk rather than from the API.

    Exists because the two places that need this information cannot both
    reach the FPL API. The deployed app can; a Claude Code research session
    cannot, because the egress proxy refuses fantasy.premierleague.com. So
    GitHub Actions fetches it and commits it, and the research reads the
    file. Without this the weekly refresh silently covered "the decision
    set" instead of the actual squad.
    """

    team_id: int = 0
    confirmed_for_gameweek: int = 0
    planning_gameweek: int = 0
    fetched_at: str = ""
    bank: float = 0.0
    team_value: float = 0.0
    free_transfers: int = 1
    chips_used: list = field(default_factory=list)
    players: list = field(default_factory=list)

    @property
    def player_ids(self) -> list[int]:
        return [int(p["id"]) for p in self.players if p.get("id") is not None]

    @property
    def names(self) -> list[str]:
        return [str(p.get("name", "")) for p in self.players]

    def is_stale(self, planning_event: int) -> bool:
        """Whether this squad predates the gameweek being planned.

        Not automatically a problem — before a deadline the squad you own
        IS last gameweek's. It only matters that the caller knows which.
        """
        return self.confirmed_for_gameweek < int(planning_event) - 1

    @property
    def summary(self) -> str:
        return (
            f"{len(self.players)} players confirmed for GW{self.confirmed_for_gameweek}, "
            f"£{self.bank:.1f}m in the bank, {self.free_transfers} free transfer(s)."
        )


def load_stored(path: Path | None = None) -> StoredSquad | None:
    """Reads the committed squad, or None when CI has not written one yet."""
    path = path or STORED_SQUAD_PATH
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if not payload.get("squad"):
        return None
    return StoredSquad(
        team_id=int(payload.get("team_id", 0) or 0),
        confirmed_for_gameweek=int(payload.get("confirmed_for_gameweek", 0) or 0),
        planning_gameweek=int(payload.get("planning_gameweek", 0) or 0),
        fetched_at=str(payload.get("fetched_at", "")),
        bank=float(payload.get("bank", 0) or 0),
        team_value=float(payload.get("team_value", 0) or 0),
        free_transfers=int(payload.get("free_transfers", 1) or 1),
        chips_used=list(payload.get("chips_used") or []),
        players=list(payload.get("squad") or []),
    )
