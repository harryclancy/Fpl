"""Will this player actually be on the pitch, and how sure can we be?

THE FAILURE THIS EXISTS TO FIX. A player moved to Manchester City and the
app went on showing START / MINUTES SECURE / CONFIDENCE HIGH, because
every one of those labels was computed from a record he had built
somewhere else. Three thousand articles in the corpus and not one of them
was consulted about whether he would play on Saturday.

The old order was: collect articles, build a dossier, decide. The order
here is:

    ESTABLISH   who he is and which club he plays for TODAY
    ASK         the specific question the decision turns on
    CHECK       the freshest evidence that addresses it
    COMBINE     fresh evidence over stale, always
    STATE       an outlook, a minutes range, and an honest confidence

Two rules do most of the work, and both are the opposite of what the old
code assumed.

A TRANSFER INVALIDATES THE RECORD. Starts, minutes, role, set pieces and
rotation security are facts about a shirt he no longer wears. They can
still establish fitness and quality; they cannot establish that he is in
the new manager's eleven.

ABSENCE OF EVIDENCE IS NOT EVIDENCE OF SECURITY. "Nothing published
against him" was being read as "nailed". It means nobody wrote about him,
which is the normal state of most players most weeks, and it cannot
support a confident claim in either direction.

Nothing here fetches anything or costs anything: it reads the corpus the
free pipeline already collected and the official data the app already
loads.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from fpl_assistant.research import status_evidence as se

# --- the vocabulary a manager actually uses ------------------------------

VERY_LIKELY = "Very likely to start"
LIKELY = "Likely to start"
FIFTY_FIFTY = "50-50"
LIKELY_BENCH = "Likely bench"
VERY_UNLIKELY = "Very unlikely to start"
OUT = "Out"

# Ordered best to worst, so a piece of bad news can always be applied as
# "move him down", never as "assert something better than we knew".
LADDER = (VERY_LIKELY, LIKELY, FIFTY_FIFTY, LIKELY_BENCH, VERY_UNLIKELY, OUT)

# Expected minutes for each outlook. Ranges rather than points, because a
# single number implies a precision nobody has.
MINUTES_RANGE = {
    VERY_LIKELY: (75, 90),
    LIKELY: (60, 90),
    FIFTY_FIFTY: (30, 75),
    LIKELY_BENCH: (10, 35),
    VERY_UNLIKELY: (0, 20),
    OUT: (0, 0),
}

# What share of a projection built on "he plays" to actually expect.
EXPECTED_SHARE = {
    VERY_LIKELY: 1.0, LIKELY: 0.88, FIFTY_FIFTY: 0.6,
    LIKELY_BENCH: 0.28, VERY_UNLIKELY: 0.1, OUT: 0.0,
}

HIGH, MEDIUM, LOW = "High", "Medium", "Low"

# Anything older than this cannot support a claim about this week's team.
STATUS_SHELF_LIFE_HOURS = 168.0
# Inside this window a run switches to team news and nothing else.
DEADLINE_HOURS = 72.0
DEADLINE_DAY_HOURS = 24.0


def step_down(outlook: str, steps: int = 1) -> str:
    index = LADDER.index(outlook) if outlook in LADDER else 0
    return LADDER[min(len(LADDER) - 1, index + steps)]


def worse_of(first: str, second: str) -> str:
    order = {label: index for index, label in enumerate(LADDER)}
    return first if order.get(first, 0) >= order.get(second, 0) else second


@dataclass
class PlayerStatus:
    """One player's current situation, and how well established it is."""

    player: str = ""
    player_id: int = 0
    club: str = ""
    club_name: str = ""
    position: str = ""
    price: float = 0.0

    outlook: str = FIFTY_FIFTY
    confidence: str = LOW
    minutes_low: int = 0
    minutes_high: int = 0

    # What the official data says. This is itself current evidence: an
    # appearance record is published by the league, not by a journalist.
    starts: int = 0
    minutes_played: int = 0
    team_games: int = 0
    availability: str = "a"
    chance_of_playing: float | None = None
    # Last completed season AT THIS CLUB. In gameweek three nobody has a
    # large in-season sample, so without this every player in the game is
    # a Low forever — and the point of the freshness layer is to find the
    # players whose situation has actually changed, not to make the whole
    # squad look uncertain. Voided by a transfer, like everything else.
    prior_minutes: int = 0
    prior_appearances: int = 0

    # What has changed recently.
    new_club: str = ""            # the published line saying he has moved
    injury: str = ""
    suspension: str = ""
    transfer_talk: str = ""
    manager_reading: str = ""
    manager_quote: str = ""
    role: str = ""
    set_pieces: bool = False
    penalties: bool = False
    rotation: str = ""

    # Predicted line-ups, counted rather than quoted.
    lineups: se.LineupTally = field(default_factory=se.LineupTally)

    # Provenance, so a label can always be asked when it was last checked.
    last_verified: str = ""
    best_source_date: str = ""
    best_source: str = ""
    source_count: int = 0
    fresh_source_count: int = 0
    evidence: list = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    vetoes: list[str] = field(default_factory=list)
    validation: list[str] = field(default_factory=list)

    @property
    def expected_share(self) -> float:
        return EXPECTED_SHARE.get(self.outlook, 0.6)

    @property
    def minutes_label(self) -> str:
        if self.outlook == OUT:
            return "not expected to play"
        return f"{self.minutes_low}-{self.minutes_high} minutes"

    @property
    def starting(self) -> bool:
        return self.outlook in (VERY_LIKELY, LIKELY)

    @property
    def checked(self) -> bool:
        """Has anything actually been verified, or is this a default?"""
        return bool(self.fresh_source_count) or self.team_games > 0

    @property
    def established(self) -> bool:
        """Did he hold this shirt down last season, at THIS club?"""
        return (not self.new_club and self.prior_minutes >= 1800
                and self.prior_appearances >= 20)

    @property
    def basis(self) -> str:
        """What the current label actually rests on."""
        if self.lineups.readable:
            return "current predicted line-ups"
        if self.manager_reading:
            return "the manager's own words"
        if self.fresh_source_count:
            return "recent reporting"
        if self.team_games:
            return "the official appearance record"
        return "nothing yet"

    @property
    def stale(self) -> bool:
        """Is the label resting on something that could have changed?

        The official appearance record is fetched live on every run, so a
        status built on it is not stale — it is thin. Staleness is about
        PUBLISHED evidence that has aged out, and about a player whose
        situation has demonstrably changed with nothing current to
        describe it.
        """
        if self.new_club and not self.fresh_source_count:
            return True
        if self.best_source_date:
            age = _age_hours(self.best_source_date)
            if age is not None and age <= STATUS_SHELF_LIFE_HOURS:
                return False
        return not self.team_games

    def as_dict(self) -> dict:
        return {
            "player": self.player, "player_id": self.player_id,
            "club": self.club, "club_name": self.club_name,
            "position": self.position, "price": self.price,
            "outlook": self.outlook, "confidence": self.confidence,
            "minutes_low": self.minutes_low, "minutes_high": self.minutes_high,
            "minutes_label": self.minutes_label,
            "expected_share": round(self.expected_share, 3),
            "starts": self.starts, "minutes_played": self.minutes_played,
            "prior_minutes": self.prior_minutes,
            "prior_appearances": self.prior_appearances,
            "established": self.established, "basis": self.basis,
            "team_games": self.team_games, "availability": self.availability,
            "chance_of_playing": self.chance_of_playing,
            "new_club": self.new_club, "injury": self.injury,
            "suspension": self.suspension, "transfer_talk": self.transfer_talk,
            "manager_reading": self.manager_reading,
            "manager_quote": self.manager_quote,
            "role": self.role, "set_pieces": self.set_pieces,
            "penalties": self.penalties, "rotation": self.rotation,
            "lineups": self.lineups.as_dict(),
            "last_verified": self.last_verified,
            "best_source_date": self.best_source_date,
            "best_source": self.best_source,
            "source_count": self.source_count,
            "fresh_source_count": self.fresh_source_count,
            "stale": self.stale, "checked": self.checked,
            "reasons": self.reasons, "vetoes": self.vetoes,
            "validation": self.validation,
            "evidence": [item.as_dict() for item in self.evidence[:8]],
        }


def _age_hours(stamp: str) -> float | None:
    try:
        when = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when).total_seconds() / 3600


# --- the base: what the official record supports --------------------------

def base_outlook(starts: int, minutes: int, team_games: int,
                 new_club: bool, prior_minutes: int = 0,
                 prior_appearances: int = 0) -> tuple[str, str]:
    """The appearance record, read honestly and no further.

    The league's own appearance data IS current evidence — it is
    published, it is official, and it is more informative about expected
    minutes than most press conferences. What it cannot do is survive a
    transfer, because it is a record of a different shirt.
    """
    if new_club:
        return FIFTY_FIFTY, (
            "he has changed clubs, so his appearance record was built "
            "somewhere else and cannot establish his place here")
    if not team_games:
        return FIFTY_FIFTY, "no games have been played yet this season"
    share = min(1.0, starts / team_games)
    per_game = minutes / team_games

    established = prior_minutes >= 1800 and prior_appearances >= 20
    if team_games < 3:
        # Two games is a real signal and a small one. It can support
        # "likely" on its own; it can support "very likely" only when
        # last season at the same club says the same thing.
        if share >= 0.9 and per_game >= 80:
            if established:
                return VERY_LIKELY, (
                    f"he has started both games and played almost every "
                    f"minute, on top of {prior_minutes:,} minutes at the club "
                    f"last season")
            return LIKELY, (
                f"he has started all {team_games} and played almost every "
                f"minute, which is as strong as {team_games} games can be")
        if share >= 0.5:
            return FIFTY_FIFTY, f"he has started {starts} of {team_games}"
        if minutes == 0:
            return VERY_UNLIKELY, f"he has not played a minute in {team_games} games"
        return LIKELY_BENCH, f"he has {minutes} minutes in {team_games} games"

    if share >= 0.9 and per_game >= 80:
        return VERY_LIKELY, (
            f"he has started {starts} of {team_games} and averages "
            f"{per_game:.0f} minutes")
    if share >= 0.7:
        return LIKELY, f"he has started {starts} of {team_games}"
    if share >= 0.4 or per_game >= 45:
        return FIFTY_FIFTY, (
            f"he has started {starts} of {team_games} and averages "
            f"{per_game:.0f} minutes")
    if minutes == 0:
        return VERY_UNLIKELY, f"he has not played a minute in {team_games} games"
    return LIKELY_BENCH, (
        f"he has started {starts} of {team_games} and averages "
        f"{per_game:.0f} minutes")


def assess(player: str, club: str, articles, variants: list[str], own: set,
           mentions, *, player_id: int = 0, club_name: str = "",
           position: str = "", price: float = 0.0,
           starts: int = 0, minutes_played: int = 0, team_games: int = 0,
           availability: str = "a", chance_of_playing: float | None = None,
           set_pieces: bool = False, penalties: bool = False,
           prior_minutes: int = 0, prior_appearances: int = 0,
           now: datetime | None = None) -> PlayerStatus:
    """The Current Status Pass for one player.

    `articles` is whatever the corpus holds about him and his club; every
    item is graded for THIS question before any of it is believed, and
    the ordering of the rules below is the whole design:

        1. the official record sets a base
        2. a transfer voids the part of it that was earned elsewhere
        3. fresh, high-authority evidence may move it in either direction
        4. stale or absent evidence may only lower confidence, never
           raise the outlook
    """
    now = now or datetime.now(timezone.utc)
    status = PlayerStatus(
        player=player, player_id=player_id, club=club,
        club_name=club_name or club, position=position, price=price,
        starts=starts, minutes_played=minutes_played, team_games=team_games,
        availability=availability, chance_of_playing=chance_of_playing,
        set_pieces=set_pieces, penalties=penalties,
        prior_minutes=prior_minutes, prior_appearances=prior_appearances,
        last_verified=now.isoformat(timespec="seconds"))

    graded = sorted(
        (se.grade(article, variants, own, mentions, now) for article in articles),
        key=lambda item: item.weight, reverse=True)
    usable = [item for item in graded if item.weight > 0.02]
    status.evidence = usable[:12]
    status.source_count = len({item.source for item in usable if item.source})
    status.fresh_source_count = len(
        {item.source for item in usable if item.fresh and item.source})
    if usable:
        status.best_source = usable[0].source
        status.best_source_date = usable[0].published

    _read_evidence(status, usable, variants, own, mentions)

    # 1 & 2: the base, with a transfer voiding what it was built on.
    outlook, why = base_outlook(starts, minutes_played, team_games,
                                bool(status.new_club), prior_minutes,
                                prior_appearances)
    status.reasons.append(why)

    # 3: fresh evidence, applied in order of how much it settles.
    outlook = _apply_availability(status, outlook)
    outlook = _apply_manager(status, outlook)
    outlook = _apply_lineups(status, outlook)
    outlook = _apply_concerns(status, outlook)

    status.outlook = outlook
    status.minutes_low, status.minutes_high = MINUTES_RANGE.get(
        outlook, (30, 75))
    status.confidence = _confidence(status)
    return status


def _read_evidence(status: PlayerStatus, graded: list, variants, own,
                   mentions) -> None:
    """Pulls the specific findings out of the graded items.

    Only items that are both recent and about him are allowed to set a
    finding: a three-week-old piece mentioning an old knock is background,
    not this week's injury news.
    """
    tally = se.LineupTally()
    for item in graded:
        recent = item.age_hours is not None and item.age_hours <= 336
        about_him = item.specificity >= se.PASSING
        text = item.excerpt or item.title

        if item.kind == se.PREDICTED_XI and item.recency >= 0.5:
            verdict = se.lineup_verdict(text, variants, own, mentions)
            if verdict == se.STARTS:
                tally.starts += 1
            elif verdict == se.BENCHED:
                tally.benched += 1
            elif verdict == se.OMITTED:
                tally.omitted += 1
            else:
                tally.unread += 1
            if item.source and item.source not in tally.sources:
                tally.sources.append(item.source)

        if not (recent and about_him):
            continue
        if item.kind == se.ARRIVAL and not status.new_club:
            status.new_club = item.title or text[:160]
        elif item.kind == se.INJURY_UPDATE and not status.injury:
            status.injury = item.title or text[:160]
        elif item.kind == se.SUSPENSION and not status.suspension:
            status.suspension = item.title or text[:160]
        elif item.kind == se.TRANSFER_TALK and not status.transfer_talk:
            status.transfer_talk = item.title or text[:160]

        # Managers are quoted everywhere and almost never under a
        # "press conference" headline, so the gate is the attribution
        # inside the text rather than the kind of article carrying it.
        if not status.manager_reading and item.recency >= 0.5:
            reading, quote = se.manager_signal(f"{item.title}. {text}")
            if reading:
                status.manager_reading, status.manager_quote = reading, quote
    status.lineups = tally


def _apply_availability(status: PlayerStatus, outlook: str) -> str:
    """The official flag outranks everything, because it is the club's."""
    if status.availability in ("i", "s", "u", "n"):
        status.reasons.append({
            "i": "FPL lists him as injured", "s": "he is suspended",
            "u": "FPL lists him as unavailable",
            "n": "he is not in the squad"}[status.availability])
        return OUT
    if status.chance_of_playing is not None and status.chance_of_playing <= 25:
        status.reasons.append(
            f"FPL puts him at {status.chance_of_playing:.0f}% to feature")
        return worse_of(outlook, VERY_UNLIKELY)
    if status.chance_of_playing is not None and status.chance_of_playing <= 75:
        status.reasons.append(
            f"FPL puts him at {status.chance_of_playing:.0f}% to feature")
        return worse_of(outlook, FIFTY_FIFTY)
    if status.availability == "d":
        status.reasons.append("he carries a fitness flag")
        return worse_of(outlook, FIFTY_FIFTY)
    return outlook


def _apply_manager(status: PlayerStatus, outlook: str) -> str:
    """What the manager said, taken at exactly its face value.

    "He will start" moves the call a long way. "We will decide tomorrow"
    moves it towards uncertainty rather than towards either answer —
    translating a vague comment into a confident label is the specific
    thing this must not do.
    """
    reading = status.manager_reading
    if not reading:
        return outlook
    quote = f' — "{status.manager_quote}"' if status.manager_quote else ""
    if reading == se.WILL_START:
        status.reasons.append(f"the manager says he will start{quote}")
        # The only route by which anything may move a player UP the
        # ladder, and it is the club telling you directly.
        return LIKELY if outlook in (FIFTY_FIFTY, LIKELY_BENCH,
                                     VERY_UNLIKELY) else outlook
    if reading == se.AVAILABLE:
        status.reasons.append(f"the manager says he is available{quote}")
        return worse_of(outlook, LIKELY) if outlook == VERY_UNLIKELY else outlook
    if reading == se.UNDECIDED:
        status.reasons.append(f"the manager has not committed{quote}")
        return worse_of(outlook, FIFTY_FIFTY)
    if reading == se.WONT_START:
        status.reasons.append(f"the manager says he will not start{quote}")
        return worse_of(outlook, LIKELY_BENCH)
    if reading == se.UNAVAILABLE:
        status.reasons.append(f"the manager says he is unavailable{quote}")
        return OUT
    return outlook


def _apply_lineups(status: PlayerStatus, outlook: str) -> str:
    """THE FRESHNESS VETO.

    Predicted line-ups are not fact, and a single one proves nothing. But
    when the current crop of them agrees that a player is on the bench,
    that outweighs an appearance record from before he moved — which is
    the exact case the app used to get wrong, and it got it wrong because
    nothing in the code could overrule a base built from history.
    """
    tally = status.lineups
    if not tally.readable:
        if status.new_club:
            status.reasons.append(
                "no current predicted line-up names him either way, which for "
                "a player who has just moved is a gap rather than a comfort")
        return outlook

    benched = tally.benched + tally.omitted
    if tally.starts and not benched:
        status.reasons.append(f"{tally.summary}")
        return LIKELY if outlook in (FIFTY_FIFTY, LIKELY_BENCH) else outlook
    if benched and not tally.starts:
        status.vetoes.append(
            f"current predicted line-ups overrule the appearance record: "
            f"{tally.summary}")
        return worse_of(outlook, LIKELY_BENCH)
    if benched and tally.starts:
        status.reasons.append(f"the predicted line-ups disagree — {tally.summary}")
        return worse_of(outlook, FIFTY_FIFTY)
    return outlook


def _apply_concerns(status: PlayerStatus, outlook: str) -> str:
    """Reported trouble. May only ever move a player down the ladder."""
    if status.suspension:
        status.reasons.append("a suspension is being reported")
        return OUT
    if status.injury:
        status.reasons.append("an injury is being reported this week")
        outlook = worse_of(outlook, FIFTY_FIFTY)
    if status.rotation:
        status.reasons.append("rotation is being reported around him")
        outlook = worse_of(outlook, FIFTY_FIFTY)
    if status.new_club and outlook in (VERY_LIKELY,):
        status.vetoes.append(
            "a transfer resets starting security, so 'very likely' is not "
            "available to him on this evidence")
        outlook = LIKELY
    return outlook


def _confidence(status: PlayerStatus) -> str:
    """Earned by evidence, and lowered by its absence.

    NO NEWS IS NOT GOOD NEWS. The old code read "nothing published
    against him" as security, which is how a player nobody had written
    about became a nailed starter. Silence lowers confidence here; it
    cannot raise it.
    """
    if status.availability in ("i", "s", "u", "n"):
        return HIGH        # an official flag is not ambiguous
    if status.new_club and not status.fresh_source_count:
        status.reasons.append(
            "his starting status at the new club has not been confirmed by "
            "anything published")
        return LOW
    if status.manager_reading in (se.WILL_START, se.UNAVAILABLE):
        return HIGH
    if status.lineups.readable >= 2 and not (
            status.lineups.starts and status.lineups.benched + status.lineups.omitted):
        return HIGH        # several current line-ups agreeing
    if status.new_club:
        return MEDIUM
    if status.lineups.readable or status.fresh_source_count >= 2:
        return MEDIUM if status.outlook != FIFTY_FIFTY else LOW

    # No player-specific reporting at all. The appearance record can still
    # carry an established starter — it is official, current data — but it
    # cannot carry a confident claim about a player without one.
    #
    # PART K: absence of daily journalism must not make every settled
    # starter uncertain. Most players go unwritten-about most weeks, and a
    # squad of fifteen Lows would tell a manager nothing.
    if status.established and status.starts >= max(1, status.team_games - 1):
        return MEDIUM
    if status.team_games >= 3 and status.starts >= status.team_games - 1:
        return MEDIUM
    status.reasons.append(
        "nothing published this week addresses his selection, so this rests "
        "on the appearance record alone")
    return LOW


# --- current-state validation --------------------------------------------

def validate(status: PlayerStatus, evidence_clubs: set | None = None) -> list[str]:
    """Impossible combinations, caught before anything is rendered.

    The failure this guards against is a display record that mixes eras:
    a Manchester City badge, an Everton starting history, and a "minutes
    secure" label derived from the second while presented under the
    first. Each field is fine on its own; together they describe a player
    who does not exist.
    """
    problems = []
    if not status.player:
        problems.append("no player name")
    if not status.club:
        problems.append(f"{status.player} has no current club")
    if not status.player_id:
        problems.append(f"{status.player} has no canonical FPL id")
    if status.price <= 0:
        problems.append(f"{status.player} has no current price")

    if status.new_club and status.outlook == VERY_LIKELY:
        problems.append(
            f"{status.player} has changed clubs and is still shown as very "
            f"likely to start — a record earned elsewhere cannot support that")
    if status.new_club and status.confidence == HIGH and not (
            status.fresh_source_count or status.manager_reading
            or status.lineups.readable):
        problems.append(
            f"{status.player} has changed clubs and is shown at high "
            f"confidence with nothing current behind it")
    if status.availability in ("i", "s", "u", "n") and status.starting:
        problems.append(
            f"{status.player} is flagged unavailable but shown as starting")

    tally = status.lineups
    if tally.benched + tally.omitted >= 2 and not tally.starts and status.starting:
        problems.append(
            f"{status.player} is left out of every current predicted line-up "
            f"and still shown as starting")

    clubs = {club for club in (evidence_clubs or set()) if club}
    stale_clubs = {club for club in clubs if club and club != status.club}
    if stale_clubs and status.outlook in (VERY_LIKELY, LIKELY) and status.new_club:
        problems.append(
            f"{status.player}'s starting case rests on evidence about "
            f"{', '.join(sorted(stale_clubs))} while he now plays for "
            f"{status.club}")
    status.validation = problems
    return problems


# --- deadline awareness ---------------------------------------------------

FULL, DEADLINE, DEADLINE_DAY = "full", "deadline", "deadline day"


def research_mode(hours_to_deadline: float | None) -> str:
    """What the next collection run should be looking for.

    Outside the window, breadth is right: build the picture. Inside it,
    breadth is a waste of the budget — nothing published a fortnight ago
    changes who starts on Saturday, and the run should spend itself on
    press conferences, injuries and predicted line-ups instead.
    """
    if hours_to_deadline is None:
        return FULL
    if hours_to_deadline <= DEADLINE_DAY_HOURS:
        return DEADLINE_DAY
    if hours_to_deadline <= DEADLINE_HOURS:
        return DEADLINE
    return FULL


def coverage(statuses: list) -> dict:
    """The research metric that replaces "we collected 3,888 articles".

    Volume was never the goal and saying it out loud made a bad run look
    like a good one. What matters is whether the fifteen players a manager
    actually owns have had their situation checked recently enough to
    trust — so that is what gets counted.
    """
    total = len(statuses) or 1
    fresh = sum(1 for s in statuses if s.fresh_source_count)
    lineups = sum(1 for s in statuses if s.lineups.readable)
    available = sum(1 for s in statuses
                    if s.availability == "a" or s.availability in ("i", "s", "u", "n"))
    confident = sum(1 for s in statuses if s.confidence in (HIGH, MEDIUM))
    moved = [s.player for s in statuses if s.new_club]
    unverified = [s.player for s in statuses if s.stale]

    if lineups >= total * 0.6 and fresh >= total * 0.6:
        grade = "GOOD"
    elif lineups or fresh >= total * 0.3:
        grade = "PARTIAL"
    else:
        grade = "THIN"
    return {
        "squad": total,
        "status_checked": f"{len(statuses)}/{total}",
        "fresh_evidence_72h": f"{fresh}/{total}",
        "predicted_xi_checked": f"{lineups}/{total}",
        "availability_checked": f"{available}/{total}",
        "confidence_at_least_medium": f"{confident}/{total}",
        "recent_transfers": moved,
        "not_recently_verified": unverified,
        "deadline_coverage": grade,
    }
