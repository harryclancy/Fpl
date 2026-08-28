"""A complete assessment of one owned player — never an empty card.

The behaviour this replaces: a player nobody had written an FPL article
about got "no researched reasoning", and the page moved on. That is a
statement about the FPL blogosphere, not about the footballer, and it is
useless to someone deciding whether to keep him.

The reframing is the whole module. The question is not "did one of our
sources publish an FPL piece about him?" but "what is currently happening
with this footballer, and what does it mean for Fantasy?" Football news
IS Fantasy news: an omission from a squad, a manager declining to commit,
a bid, ninety minutes in a cup tie, a full-back suddenly at left wing, a
new striker signing — every one of those changes an expected-minutes
picture without a single FPL writer mentioning it.

So a dossier is built in escalating passes (see `research/completeness.py`
for the checklist that enforces them) and always ends in a verdict. Where
evidence is thin the verdict is hedged and the thinness is stated; it is
never absent.

Three kinds of statement are kept apart, because collapsing them is how
speculation becomes fact:

    FACT         — reported directly: he was not in the squad.
    INFERENCE    — ours: his minutes are therefore less secure.
    UNCONFIRMED  — reported but not established: a bid is expected.

"He was omitted and there is interest in him" is a fact. "He won't play"
is not an inference anyone is entitled to make from it, and the grading
below exists to stop the model making it.
"""
from dataclasses import dataclass, field

import pandas as pd

# --- Expected minutes, judged on news rather than inherited from a model -
#
# Ordered worst-last so a maximum over several signals is the pessimistic
# one, which is the right default: a player with one reason to doubt him
# is a doubt, however good the other four signals look.
MINUTES_LEVELS = (
    "Very secure",
    "Secure",
    "Slight concern",
    "Significant concern",
    "Major doubt",
)

# The default, and the fix for a real failure.
#
# The first version started every player at "Secure" and escalated only on
# contradicting evidence. A player nobody had researched therefore came out
# as SECURE STARTER / MINUTES SECURE with an empty reasons list — absence
# of evidence read as evidence of security, which is exactly backwards.
# Enzo Fernández had been substituted on rather than started, then left out
# of a cup squad entirely, with active transfer interest, and the page
# called him a secure starter because nothing in our files contradicted it.
#
# "Secure" must now be EARNED by positive evidence — a researched starting
# call, or a recent start. Until then he is Unknown, and Unknown is treated
# as a risk rather than as a clean bill of health.
MINUTES_UNKNOWN = "Unknown — not yet checked"

# Where an unchecked player sits when urgency is being ranked. Between
# slight and significant concern: not assumed bad, definitely not assumed
# fine, and never allowed to outrank a player we have actually confirmed.
UNKNOWN_URGENCY = 2

# --- How far a transfer story has actually got ---------------------------
#
# Graded rather than believed or dismissed. The FPL consequence is not the
# same at each step, and "it isn't confirmed" is not a reason to ignore a
# player who has just been left out of a squad.
TRANSFER_LEVELS = (
    "None",
    "Low-level rumour",
    "Credible interest",
    "Active talks",
    "Bid expected",
    "Bid made",
    "Advanced",
    "Transfer imminent",
    "Confirmed",
)

# From this point a transfer story is doing real work on expected minutes,
# because clubs start protecting assets and managers start hedging.
TRANSFER_MINUTES_THRESHOLD = TRANSFER_LEVELS.index("Active talks")

# Events worth surfacing, drawn from roughly the last week. The list is
# deliberately broad: several of these never appear in an FPL article and
# every one of them can move a projection.
EVENT_TYPES = (
    "not in squad", "benched", "started", "substituted",
    "injury", "returned to training", "suspension", "red card",
    "transfer bid", "transfer talks", "player wants move", "club open to sale",
    "manager quote", "position change", "set-piece change", "penalty change",
    "new competition for position", "teammate injury", "teammate return",
    "new signing", "cup minutes", "european minutes",
)

# Events that should never be buried below a projection. "Major" means
# important enough to surface prominently — it does NOT mean bad.
MAJOR_EVENTS = frozenset({
    "not in squad", "injury", "suspension", "red card",
    "transfer bid", "transfer talks", "player wants move", "club open to sale",
    "position change", "set-piece change", "penalty change", "new signing",
    "new competition for position", "returned to training",
})

# The subset that argues for SELLING. Kept separate because conflating
# "important" with "negative" put a penalty appointment — the single best
# thing that can happen to a midfielder — into the case for selling him.
# A set-piece or penalty change can go either way, so neither is listed
# here; the write-up reports what actually changed instead.
NEGATIVE_EVENTS = frozenset({
    "not in squad", "injury", "suspension", "red card",
    "transfer bid", "transfer talks", "player wants move", "club open to sale",
    "new signing", "new competition for position",
})

# The subset that argues for KEEPING.
POSITIVE_EVENTS = frozenset({
    "started", "returned to training", "teammate injury",
})

VERDICTS = ("KEEP", "SELL", "MONITOR", "BENCH", "CAPTAIN", "VICE-CAPTAIN")

FACT, INFERENCE, UNCONFIRMED = "fact", "inference", "unconfirmed"


@dataclass
class Claim:
    """One statement, labelled by how well established it is."""

    text: str
    kind: str = FACT
    source: str = ""

    @property
    def display(self) -> str:
        prefix = {FACT: "", INFERENCE: "*Inference:* ", UNCONFIRMED: "*Unconfirmed:* "}
        line = f"{prefix.get(self.kind, '')}{self.text}"
        return f"{line} ({self.source})" if self.source else line


@dataclass
class Event:
    """Something that happened to this player in roughly the last week."""

    kind: str
    detail: str
    source: str = ""
    when: str = ""

    @property
    def major(self) -> bool:
        return self.kind in MAJOR_EVENTS

    @property
    def negative(self) -> bool:
        return self.kind in NEGATIVE_EVENTS

    @property
    def positive(self) -> bool:
        return self.kind in POSITIVE_EVENTS

    @property
    def display(self) -> str:
        label = self.kind.upper()
        when = f" ({self.when})" if self.when else ""
        tail = f" — {self.source}" if self.source else ""
        return f"**{label}**{when}: {self.detail}{tail}"


@dataclass
class Dossier:
    """Everything known about one owned player, and what to do about him."""

    player_id: int
    name: str
    team: str
    position: str
    price: float
    ownership: float = 0.0

    starting: bool = False
    captain: bool = False
    vice_captain: bool = False

    minutes_outlook: str = "Secure"
    minutes_reasons: list[str] = field(default_factory=list)
    transfer_status: str = "None"
    transfer_detail: str = ""
    # Whether anyone actually looked. "None" as a default means "we never
    # checked"; "None" recorded by a researcher means "we checked and
    # there is nothing". Those are different claims and the completeness
    # gate must not treat an unexamined player as a cleared one.
    transfer_checked: bool = False

    events: list[Event] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)

    role: str = ""
    set_pieces: str = ""
    fixture: str = ""
    fixture_run: list[str] = field(default_factory=list)
    record_vs: str = ""
    opposition_notes: list[str] = field(default_factory=list)

    case_for: list[tuple[str, str]] = field(default_factory=list)
    case_against: list[tuple[str, str]] = field(default_factory=list)
    dissent: str = ""
    prior_seasons: str = ""

    _predicted_start: str = ""           # stored expectation, for conflict detection
    research_depth: str = "fpl"          # how far the escalation had to go
    sources: list[str] = field(default_factory=list)
    enabler: bool = False

    # ---- headline fields the homepage renders -------------------------

    @property
    def status(self) -> str:
        """The one-line status a reader scans before anything else.

        "Secure starter" is only reachable with positive evidence. An
        unchecked player reads as unchecked, which is the honest label and
        the one that stops a page confidently mislabelling somebody whose
        transfer is being negotiated.
        """
        if self.minutes_outlook == "Major doubt":
            return "Major minutes concern"
        if self.transfer_index >= TRANSFER_MINUTES_THRESHOLD:
            return "Transfer risk"
        if self.minutes_outlook == "Significant concern":
            return "Major minutes concern"
        if self.minutes_outlook == "Slight concern":
            return "Moderate minutes concern"
        if any(e.kind == "injury" for e in self.events):
            return "Injury doubt"
        if self.minutes_unknown:
            return "Not yet researched"
        if self.enabler:
            return "Budget enabler"
        return "Secure starter"

    @property
    def minutes_unknown(self) -> bool:
        return self.minutes_outlook == MINUTES_UNKNOWN

    @property
    def recency_conflict(self) -> str:
        """Where the stored expectation and the fresh evidence disagree.

        The specific failure this catches: a file says "nailed", and then
        the player is substituted on rather than starting, or left out of
        a squad entirely, or a bid arrives. Publishing the stored label
        over the top of that is how a page ends up calling a man a secure
        starter on the morning his transfer is being negotiated.

        Fresh evidence wins. This exists so the disagreement is stated
        rather than silently resolved.
        """
        predicted = (self._predicted_start or "").lower()
        if predicted not in ("nailed", "likely"):
            return ""
        contradicting = [
            e for e in self.events
            if e.kind in ("not in squad", "benched", "injury", "suspension",
                          "transfer talks", "transfer bid", "club open to sale",
                          "player wants move", "new signing")
        ]
        if not contradicting:
            return ""
        detail = "; ".join(f"{e.kind} — {e.detail}" for e in contradicting[:3])
        return (
            f"**Recency conflict.** The stored expectation is '{predicted}', but more recent "
            f"evidence says otherwise: {detail}. Fresh evidence wins, so the minutes call above "
            f"reflects the news rather than the stored label."
        )

    @property
    def sell_urgency(self) -> int:
        """0-5. How badly this player needs moving on, before any transfer.

        Computed for all fifteen BEFORE a replacement is chosen, which is
        the ordering the engine previously had backwards: it used to find
        an attractive target and then look for whoever the money worked
        against, which is how a starting winger gets sold to fund a
        midfielder while a genuinely at-risk asset is kept.

        Deliberately blind to the projection. A projection cannot see an
        omission, a bid, or a manager declining to commit, and those are
        precisely the things that make a player worth selling.
        """
        if self.minutes_outlook == "Major doubt":
            return 5
        if self.transfer_index >= TRANSFER_LEVELS.index("Bid made"):
            return 5

        score = 0
        if self.minutes_outlook == "Significant concern":
            score = max(score, 4)
        elif self.minutes_outlook == "Slight concern":
            score = max(score, 2)
        elif self.minutes_unknown:
            score = max(score, UNKNOWN_URGENCY)

        if self.transfer_index >= TRANSFER_MINUTES_THRESHOLD:
            score = max(score, 3)
        elif self.transfer_index >= TRANSFER_LEVELS.index("Credible interest"):
            score = max(score, 1)

        if any(e.kind == "not in squad" for e in self.events):
            score = max(score, 4)
        if any(e.kind == "benched" for e in self.events):
            score = max(score, 2)
        if any(e.kind in ("new signing", "new competition for position") for e in self.events):
            score = max(score, 2)
        if self.case_against:
            score = max(score, 1)

        # Protection for a genuinely strong asset. A player who is
        # starting, has no concern of any kind and carries dead-ball duty
        # should not drift up the sell list on a thin argument — the bar
        # for selling him has to be high, not average.
        if (self.minutes_index <= 1 and not self.minutes_unknown
                and self.transfer_index == 0 and self.set_pieces
                and not any(e.negative for e in self.events)):
            score = min(score, 1)
        return min(score, 5)

    @property
    def sell_urgency_label(self) -> str:
        return {
            0: "No reason to sell",
            1: "Minor concern",
            2: "Monitor",
            3: "Genuine sell candidate",
            4: "Strong sell",
            5: "Urgent sell",
        }[self.sell_urgency]

    @property
    def sell_urgency_reason(self) -> str:
        bits = []
        if self.minutes_reasons:
            bits.append(self.minutes_reasons[0])
        if self.transfer_index >= TRANSFER_LEVELS.index("Credible interest"):
            bits.append(f"transfer status '{self.transfer_status}'")
        for event in self.negative_events[:2]:
            bits.append(f"{event.kind}: {event.detail}")
        if not bits:
            bits.append("nothing adverse found")
        return "; ".join(bits)

    @property
    def transfer_index(self) -> int:
        try:
            return TRANSFER_LEVELS.index(self.transfer_status)
        except ValueError:
            return 0

    @property
    def minutes_index(self) -> int:
        try:
            return MINUTES_LEVELS.index(self.minutes_outlook)
        except ValueError:
            return 1

    @property
    def major_events(self) -> list[Event]:
        return [e for e in self.events if e.major]

    @property
    def negative_events(self) -> list[Event]:
        return [e for e in self.events if e.negative]

    @property
    def positive_events(self) -> list[Event]:
        return [e for e in self.events if e.positive or e.kind in
                ("penalty change", "set-piece change", "position change")]

    @property
    def evidence_thin(self) -> bool:
        return not (self.case_for or self.case_against or self.events or self.claims)

    @property
    def confidence(self) -> str:
        if self.evidence_thin:
            return "Low"
        if self.minutes_index >= 3 or self.transfer_index >= TRANSFER_MINUTES_THRESHOLD:
            return "Low"
        if len(self.sources) >= 2 and self.minutes_index <= 1:
            return "High"
        return "Medium"

    @property
    def verdict(self) -> str:
        """Keep, sell, monitor, bench — always one of them.

        Derived from minutes and transfer risk rather than from the
        projection, because those are what a projection cannot see. A
        player is never left without a call.
        """
        if self.captain:
            return "CAPTAIN"
        if self.vice_captain:
            return "VICE-CAPTAIN"
        if self.minutes_outlook == "Major doubt":
            return "SELL"
        if self.transfer_index >= TRANSFER_LEVELS.index("Bid made"):
            return "SELL"
        if self.minutes_index >= 2 or self.transfer_index >= TRANSFER_MINUTES_THRESHOLD:
            return "MONITOR"
        if not self.starting:
            return "BENCH"
        return "KEEP"

    # ---- the written sections -----------------------------------------

    @property
    def this_gameweek(self) -> str:
        parts = []
        if self.fixture:
            parts.append(f"He plays {self.fixture}.")
        minutes = {
            "Very secure": "He is a certainty to start.",
            "Secure": "He is expected to start.",
            "Slight concern": "He should start, but it is not guaranteed.",
            "Significant concern": "There is real doubt over whether he starts.",
            "Major doubt": "He may well not feature at all.",
            MINUTES_UNKNOWN: (
                "His involvement has not been confirmed either way — treat this as unchecked "
                "rather than safe, and look at the late team news before the deadline."
            ),
        }[self.minutes_outlook]
        parts.append(minutes)
        if self.minutes_reasons:
            parts.append(f"Why: {self.minutes_reasons[0]}")
        if self.opposition_notes:
            parts.append(self.opposition_notes[0])
        if self.record_vs:
            parts.append(f"Against this opponent: {self.record_vs}")
        return " ".join(parts)

    @property
    def why_in_squad(self) -> str:
        if self.enabler:
            return (
                f"He is here to make the budget work. At £{self.price:.1f}m he frees money for the "
                f"players who actually score. That is a real reason, and pretending otherwise would "
                f"be dressing a squad-filler up as a football pick."
            )
        parts = []
        if self.role:
            parts.append(f"His job in the side is {self.role}.")
        if self.set_pieces:
            parts.append(
                f"He is on {self.set_pieces}, which is the least fixture-dependent source of points "
                f"in the game — it survives a bad matchup and a quiet afternoon."
            )
        if self.case_for:
            point, source = self.case_for[0]
            parts.append(f"{point} ({source}).")
        if self.prior_seasons:
            parts.append(f"Over full seasons: {self.prior_seasons}.")
        if not parts:
            parts.append(
                "He holds his place on projected output rather than on anything anyone has written "
                "about him this week, which is the weakest kind of case in the squad."
            )
        return " ".join(parts)

    @property
    def case_for_keeping(self) -> str:
        parts = []
        if self.minutes_index <= 1:
            parts.append("Minutes are not in question, which is the foundation of any hold.")
        for event in self.positive_events[:2]:
            parts.append(event.display)
        for point, source in self.case_for[:2]:
            parts.append(f"{point} ({source}).")
        if self.fixture_run:
            parts.append(f"His run: {', '.join(self.fixture_run)}.")
        if self.ownership >= 40:
            parts.append(
                f"At {self.ownership:.0f}% owned, selling him is an active bet against the field "
                f"rather than a neutral move."
            )
        if not parts:
            parts.append("Little beyond inertia — no researched argument for holding him has surfaced.")
        return " ".join(parts)

    @property
    def case_for_selling(self) -> str:
        parts = []
        for event in self.negative_events[:2]:
            parts.append(event.display)
        if self.transfer_index >= TRANSFER_MINUTES_THRESHOLD:
            parts.append(
                f"Transfer situation: **{self.transfer_status}**. {self.transfer_detail}".strip()
            )
        for point, source in self.case_against[:2]:
            parts.append(f"{point} ({source}).")
        if self.minutes_index >= 2:
            parts.append(
                f"Expected minutes are the problem: **{self.minutes_outlook}**. A player who might "
                f"not play is worth less than his projection says regardless of how good he is."
            )
        if self.minutes_unknown:
            parts.append(
                "His minutes have not been confirmed. Owning a player whose involvement is "
                "unchecked is itself a risk, and the opportunity cost of the money is real "
                "while that stays open."
            )
        if not parts:
            parts.append(
                "Nothing specific. The only argument is opportunity cost — whether the money does "
                "more somewhere else."
            )
        return " ".join(parts)

    @property
    def latest_developments(self) -> str:
        if not self.events:
            return "Nothing new found in the last week."
        return " ".join(event.display for event in self.events[:4])

    @property
    def expert_view(self) -> str:
        if self.dissent:
            return f"**Sources disagree here.** {self.dissent}"
        if not (self.case_for or self.case_against):
            return (
                "FPL-specific commentary on him was limited this week, so the assessment above rests "
                "on club news, selection evidence and fixtures rather than on published tips."
            )
        voices = []
        for point, source in (self.case_for[:2] + self.case_against[:1]):
            voices.append(f"{source}: {point}")
        return " ".join(voices)

    @property
    def risks(self) -> str:
        parts = []
        if self.minutes_index >= 2:
            parts.append(f"Minutes — **{self.minutes_outlook}**.")
        if self.transfer_index >= TRANSFER_MINUTES_THRESHOLD:
            parts.append(f"Transfer — **{self.transfer_status}**.")
        for point, source in self.case_against[:2]:
            parts.append(f"{point} ({source}).")
        if self.evidence_thin:
            parts.append(
                "The largest risk here is that we know little about him. Thin evidence is itself a "
                "risk, not a clean bill of health."
            )
        return " ".join(parts) if parts else "Nothing material identified."

    @property
    def next_gameweeks(self) -> str:
        if not self.fixture_run:
            return "No fixture run loaded, so this has only been judged on the coming match."
        line = f"His next few: {', '.join(self.fixture_run)}."
        if self.minutes_index >= 2:
            line += (
                " Worth noting the run only matters if he is playing, and that is the open question."
            )
        return line

    def escalation_note(self) -> str:
        """What had to be done to reach an assessment.

        Shown when the FPL sources alone were not enough, because a reader
        should know whether a write-up rests on published tips or on our
        own reading of club news.
        """
        if self.research_depth == "fpl":
            return ""
        return (
            "FPL-specific commentary was limited, so the search was widened to current club news, "
            "manager comments, recent selections and football reporting. The assessment above is "
            "built on that evidence."
        )


def _text(row: pd.Series, *columns: str) -> str:
    for column in columns:
        value = row.get(column)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def minutes_from(row: pd.Series, events: list[Event], transfer_status: str) -> tuple[str, list[str]]:
    """The expected-minutes call, with current news overriding the model.

    A statistical minutes estimate is a summary of the past. An omission
    from last week's squad is the present, and when they disagree the
    present wins — that is the entire point of researching a player rather
    than projecting him.

    Returns `MINUTES_UNKNOWN` when there is no evidence either way.
    Security is earned, never assumed: see MINUTES_UNKNOWN above for the
    failure that rule exists to prevent.
    """
    reasons: list[str] = []
    level: int | None = None

    predicted = _text(row, "predicted_start").lower()
    mapping = {"nailed": 0, "likely": 1, "rotation risk": 2, "doubt": 3, "out": 4}
    if predicted in mapping:
        level = mapping[predicted]
        reasons.append(f"researched starting call is '{predicted}'")

    # A recent start is the other way to earn security.
    if any(e.kind == "started" for e in events):
        started = next(e for e in events if e.kind == "started")
        level = min(level, 1) if level is not None else 1
        reasons.append(f"started the most recent match ({started.detail or 'confirmed'})")

    def escalate(current, floor):
        return floor if current is None else max(current, floor)

    status = str(row.get("status") or "a")
    if status != "a":
        level = escalate(level, 4)
        reasons.append("flagged as unavailable by the official FPL data")

    chance = pd.to_numeric(pd.Series([row.get("chance_of_playing_next_round")]), errors="coerce").iloc[0]
    if pd.notna(chance) and chance <= 50:
        level = escalate(level, 3)
        reasons.append(f"chance of playing given as {chance:.0f}%")

    for event in events:
        if event.kind == "not in squad":
            level = escalate(level, 3)
            reasons.append("left out of the most recent matchday squad")
        elif event.kind in ("injury", "suspension", "red card"):
            level = escalate(level, 4)
            reasons.append(f"{event.kind} reported")
        elif event.kind in ("new signing", "new competition for position"):
            level = escalate(level, 2)
            reasons.append("new competition for his place")
        elif event.kind == "benched":
            level = escalate(level, 2)
            reasons.append("started on the bench last time out")

    try:
        if TRANSFER_LEVELS.index(transfer_status) >= TRANSFER_MINUTES_THRESHOLD:
            level = escalate(level, 2)
            reasons.append(f"transfer situation at '{transfer_status}'")
    except ValueError:
        pass

    if level is None:
        return MINUTES_UNKNOWN, [
            "no starting call, recent appearance, injury or transfer information found — "
            "this is unchecked rather than confirmed"
        ]
    return MINUTES_LEVELS[min(level, len(MINUTES_LEVELS) - 1)], reasons


def parse_events(raw) -> list[Event]:
    out: list[Event] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "")).lower().strip()
        if kind not in EVENT_TYPES:
            continue
        out.append(Event(
            kind=kind,
            detail=str(item.get("detail", "")).strip(),
            source=str(item.get("source", "")).strip(),
            when=str(item.get("when", "")).strip(),
        ))
    # Major events first: they must never sit below a routine one.
    return sorted(out, key=lambda e: not e.major)


def build(
    row: pd.Series,
    gameweek: int,
    fixtures: list | None = None,
    fixture_run: list[str] | None = None,
    starting: bool = False,
    captain: bool = False,
    vice_captain: bool = False,
) -> Dossier:
    """Assembles one player's dossier from everything the research carries.

    Never returns an empty profile. Where the research is thin the sections
    say what is thin and the verdict is hedged accordingly — which is
    information, whereas "no write-up found" is an apology.
    """
    from fpl_assistant.analysis import consensus, matchups

    club = str(row.get("team_short_name") or "")
    position = str(row.get("position") or "")
    fixtures = matchups.load(int(gameweek)) if fixtures is None else fixtures
    notes = matchups.opponent_notes(club, position, fixtures)
    price = float(row.get("price", 0) or 0)

    events = parse_events(consensus.unpack(row.get("player_events")))
    recorded = _text(row, "transfer_status")
    transfer_status = recorded or "None"
    if transfer_status not in TRANSFER_LEVELS:
        transfer_status = "None"
        recorded = ""
    outlook, reasons = minutes_from(row, events, transfer_status)

    case_for = consensus.arguments_for(row)
    case_against = consensus.arguments_against(row)
    sources = list(dict.fromkeys(
        [s for _, s in case_for + case_against if s]
        + [e.source for e in events if e.source]
    ))

    claims = []
    for item in consensus.unpack(row.get("player_claims")) or []:
        if isinstance(item, dict) and item.get("text"):
            claims.append(Claim(
                text=str(item["text"]),
                kind=str(item.get("kind", FACT)).lower(),
                source=str(item.get("source", "")),
            ))

    return Dossier(
        player_id=int(row["id"]),
        name=str(row.get("web_name") or ""),
        team=club,
        position=position,
        price=price,
        ownership=float(pd.to_numeric(row.get("selected_by_percent", 0), errors="coerce") or 0),
        starting=starting,
        captain=captain,
        vice_captain=vice_captain,
        minutes_outlook=outlook,
        minutes_reasons=reasons,
        _predicted_start=_text(row, "predicted_start"),
        transfer_status=transfer_status,
        transfer_detail=_text(row, "transfer_detail"),
        transfer_checked=bool(recorded),
        events=events,
        claims=claims,
        role=_text(row, "role_note", "role"),
        set_pieces=_text(row, "set_pieces"),
        fixture=matchups.summary(club, position, fixtures).split(".")[0],
        fixture_run=list(fixture_run or []),
        record_vs=_text(row, "record_vs_opponent"),
        opposition_notes=[n.display for n in notes[:2]],
        case_for=case_for,
        case_against=case_against,
        dissent=_text(row, "consensus_dissent"),
        prior_seasons=_text(row, "prior_seasons"),
        research_depth=_text(row, "research_depth") or "fpl",
        sources=sources,
        enabler=price <= 4.5 and not starting,
    )


@dataclass
class SellRanking:
    """The fifteen, ordered by how badly each needs moving on.

    Computed BEFORE any replacement is considered, which is the ordering
    the engine previously had backwards. The old logic found an attractive
    target and then looked for whoever the money worked against — which is
    how a settled starter in the best attack in the league gets sold to
    fund another midfielder while a player in the middle of a transfer
    saga is kept.
    """

    entries: list = field(default_factory=list)   # (dossier, urgency)

    @property
    def ordered(self) -> list:
        return [d for d, _ in sorted(self.entries, key=lambda e: -e[1])]

    @property
    def candidates(self) -> list:
        """Players with a genuine reason to go — urgency 3 or above."""
        return [d for d, u in sorted(self.entries, key=lambda e: -e[1]) if u >= 3]

    @property
    def protected(self) -> list:
        """Assets with a high bar for selling: settled, and nothing wrong."""
        return [d for d, u in self.entries if u <= 1]

    def urgency_of(self, player_id: int) -> int:
        for d, u in self.entries:
            if d.player_id == player_id:
                return u
        return 0

    def why_this_one(self, chosen_id: int) -> str:
        """Why we are selling him rather than somebody else in the squad.

        The question the engine has to be able to answer before a transfer
        is allowed out of the door. If the chosen player is not among the
        most urgent, that is stated plainly rather than hidden — a transfer
        that cannot survive this sentence should not be recommended.
        """
        ordered = sorted(self.entries, key=lambda e: -e[1])
        if not ordered:
            return ""
        chosen = next((d for d, _ in ordered if d.player_id == chosen_id), None)
        if chosen is None:
            return ""
        urgency = self.urgency_of(chosen_id)
        top, top_urgency = ordered[0]

        if top.player_id == chosen_id:
            runner_up = ordered[1] if len(ordered) > 1 else None
            line = (
                f"He is the most urgent sale in the squad ({urgency}/5 — {chosen.sell_urgency_label}): "
                f"{chosen.sell_urgency_reason}."
            )
            if runner_up is not None:
                other, other_urgency = runner_up
                line += (
                    f" The next candidate is {other.name} at {other_urgency}/5, which is a weaker "
                    f"case: {other.sell_urgency_reason}."
                )
            return line

        return (
            f"⚠️ **He is NOT the most urgent sale.** {chosen.name} rates {urgency}/5 "
            f"({chosen.sell_urgency_label}), while {top.name} rates {top_urgency}/5 — "
            f"{top.sell_urgency_reason}. Selling {chosen.name} while holding {top.name} needs a "
            f"reason beyond the money working, and if there isn't one, this is the wrong move."
        )


def rank_by_sell_urgency(dossiers) -> SellRanking:
    return SellRanking(entries=[(d, d.sell_urgency) for d in dossiers])
