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
from dataclasses import dataclass

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
