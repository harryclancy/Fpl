"""Whether what the app is showing is still current, and what to do if not.

Two different clocks run in this app and conflating them is what makes
data look stale when it isn't.

**Live FPL data** — prices, injuries, ownership — comes from the official
API on every load, behind short caches. It is never more than minutes old
and needs no intervention.

**Research** — the write-ups, the matchup notes, the club stances — is
committed to the repository by a Claude Code session. It only changes when
someone runs a refresh, so it can genuinely belong to a previous gameweek
while everything around it is current. That is the staleness worth
reporting, and it is the one the app could not previously see.

The design rule is that the app must never silently present last
gameweek's research as this gameweek's. It also must not re-run heavy work
on every page load. So: cheap checks on load, a clear line saying how old
the research is, and a button that clears the caches when someone wants
the newest committed data immediately.

Nothing here costs anything. There is no scheduler, no database and no
paid API — the staleness check is arithmetic on timestamps already in the
repository, and the refresh clears an in-memory cache.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

FRESH = "fresh"
AGEING = "ageing"
STALE = "stale"

# Research from the gameweek being planned is current by definition.
# Research from the one before is ageing — usable for background, wrong
# for team news. Anything older is stale.
#
# Hours are deliberately not the primary test. A file written three days
# ago for the right gameweek is fine; one written an hour ago for the
# wrong gameweek is not, because team news does not survive a deadline.
AGEING_HOURS = 36


@dataclass
class Freshness:
    """How current the committed research is, relative to the gameweek."""

    gameweek: int
    research_gameweek: int | None = None
    researched_at: str = ""
    deadline: str = ""

    @property
    def age_hours(self) -> float | None:
        if not self.researched_at:
            return None
        try:
            stamp = datetime.fromisoformat(self.researched_at)
        except ValueError:
            return None
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - stamp).total_seconds() / 3600

    @property
    def state(self) -> str:
        if self.research_gameweek is None:
            return STALE
        if self.research_gameweek < self.gameweek:
            return STALE
        age = self.age_hours
        if age is not None and age > AGEING_HOURS:
            return AGEING
        return FRESH

    @property
    def stale(self) -> bool:
        return self.state == STALE

    @property
    def label(self) -> str:
        """The small line the homepage shows. Deliberately unobtrusive."""
        when = ""
        if self.researched_at:
            try:
                stamp = datetime.fromisoformat(self.researched_at)
                when = stamp.strftime("%d %b %Y · %H:%M UTC")
            except ValueError:
                when = self.researched_at
        return f"Updated {when}" if when else "Never researched"

    @property
    def message(self) -> str:
        if self.state == FRESH:
            return ""
        if self.research_gameweek is None:
            return (
                f"No research has been committed for Gameweek {self.gameweek}. The squad and "
                f"projections below are live, but the written reasoning is missing — run a refresh."
            )
        if self.research_gameweek < self.gameweek:
            return (
                f"The written research on this page is from Gameweek {self.research_gameweek}, "
                f"not Gameweek {self.gameweek}. Prices, injuries and fixtures below are live; the "
                f"reasoning is a gameweek behind and team news does not survive a deadline."
            )
        age = self.age_hours
        hours = f"{age:.0f} hours" if age is not None else "some time"
        return (
            f"The research is for the right gameweek but was written {hours} ago. Late team news "
            f"may have moved since — worth a refresh if a deadline is close."
        )


def check(gameweek: int, researched_at: str = "", research_gameweek: int | None = None,
          deadline: str = "") -> Freshness:
    return Freshness(
        gameweek=int(gameweek),
        research_gameweek=research_gameweek,
        researched_at=researched_at,
        deadline=deadline,
    )


def from_files(gameweek: int, consensus_payload: dict | None = None,
               deadline: str = "") -> Freshness:
    """Reads the committed research file's own stamps.

    Both fields matter and they answer different questions: `gameweek`
    says which deadline the research was written for, `researched` says
    when. A file can be recent and wrong, or old and right.
    """
    payload = consensus_payload or {}
    research_gw = payload.get("gameweek")
    return check(
        gameweek=gameweek,
        researched_at=str(payload.get("researched") or ""),
        research_gameweek=int(research_gw) if research_gw is not None else None,
        deadline=deadline,
    )
