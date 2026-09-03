"""What a piece of evidence is worth for the question "will he play?".

The corpus holds thousands of articles and the old engine treated them as
interchangeable. They are not. For a selection question a predicted XI
published this morning is worth more than a month-old piece calling
somebody nailed, and that ordering has to be explicit or volume wins by
default — which is exactly how a player who had just changed clubs kept a
"minutes secure" label built entirely on his previous club's record.

Four independent scores, deliberately not collapsed into one number until
the end, so a weak item can be weak for a stated reason:

    TIER          how much authority the source has FOR THIS QUESTION —
                  which is not the same as how good the source is. A
                  press conference outranks a statistics site on whether
                  someone starts, and loses to it on expected goals.
    RECENCY       team news does not survive a week, let alone a
                  transfer window.
    SPECIFICITY   named in the headline, named in the body, or merely
                  playing for the club being discussed.
    RELEVANCE     does the article address the decision at all? A
                  "best City assets" piece is about the right player and
                  says nothing about Saturday's eleven.

Nothing here fetches anything. It reads articles the free pipeline has
already collected, so the cost of the whole layer is zero.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

# --- what kind of article this is ----------------------------------------

PREDICTED_XI = "predicted lineup"
TEAM_NEWS = "team news"
PRESS_CONFERENCE = "press conference"
INJURY_UPDATE = "injury update"
SUSPENSION = "suspension"
ARRIVAL = "arrival"
TRANSFER_TALK = "transfer talk"
MATCH_REPORT = "match report"
GENERAL = "general"

# Phrases, not words. "line-up" catches a predicted XI; "line" catches
# nothing useful and half the corpus.
KIND_PATTERNS = (
    (PREDICTED_XI, (
        "predicted xi", "predicted line-up", "predicted lineup",
        "predicted starting", "expected xi", "expected line-up",
        "expected lineup", "starting xi prediction", "how they could line up",
        "how they might line up", "probable xi", "probable line-up",
        "lineup prediction", "line-up prediction", "team news and predicted")),
    (PRESS_CONFERENCE, (
        "press conference", "pre-match press", "speaking to the media",
        "told reporters", "said in his press", "manager confirmed",
        "boss confirmed", "head coach confirmed", "gave an update on")),
    (TEAM_NEWS, (
        "team news", "squad news", "selection news", "injury news and",
        "who is available", "availability update", "confirmed line-up",
        "confirmed lineup", "starting eleven", "team sheet")),
    (INJURY_UPDATE, (
        "injury update", "injury latest", "fitness update", "sidelined",
        "ruled out", "return date", "back in training", "returned to training",
        "undergo a scan", "picked up a knock", "injury blow", "doubt for")),
    (SUSPENSION, (
        "suspended for", "suspension", "red card", "sent off", "serve a ban",
        "one-match ban", "three-match ban")),
    (ARRIVAL, (
        "has joined", "have joined", "completed a move", "completing a move",
        "completes a move", "signed for", "new signing", "unveiled",
        "sealed a move", "completed the signing", "agreed a deal to join",
        "arrives at")),
    (TRANSFER_TALK, (
        "bid for", "release clause", "agreed terms", "transfer fee",
        "set to join", "asking price", "linked with a move",
        "transfer request", "wants to leave")),
    (MATCH_REPORT, (
        "player ratings", "full-time", "match report", "as it happened",
        "5-3-2", "4-3-3", "final score")),
)

# How much each kind says about whether a player will be on the pitch on
# Saturday. A match report is a fact about last week; a predicted XI is a
# claim about this one, and the claim is what the question asks for.
DECISION_RELEVANCE = {
    PREDICTED_XI: 1.0,
    TEAM_NEWS: 0.95,
    PRESS_CONFERENCE: 0.9,
    INJURY_UPDATE: 0.85,
    SUSPENSION: 0.85,
    ARRIVAL: 0.7,
    TRANSFER_TALK: 0.5,
    MATCH_REPORT: 0.35,
    GENERAL: 0.15,
}


def article_kind(title: str, body: str = "") -> str:
    """What this article is, from the words it uses about itself.

    Read from the title first and only then from the opening of the body:
    a match report that mentions a press conference in paragraph nine is
    still a match report, and letting the body outvote the headline made
    everything look like team news.
    """
    headline = (title or "").lower()
    for kind, patterns in KIND_PATTERNS:
        if any(pattern in headline for pattern in patterns):
            return kind
    opening = (body or "")[:600].lower()
    for kind, patterns in KIND_PATTERNS:
        if any(pattern in opening for pattern in patterns):
            return kind
    return GENERAL


# --- how much authority the source has, for THIS question ----------------

OFFICIAL = 1
SPECIALIST = 2
REPUTABLE = 3
STATISTICAL = 4
BACKGROUND = 5

TIER_NAMES = {
    OFFICIAL: "official",
    SPECIALIST: "specialist team news",
    REPUTABLE: "reputable reporting",
    STATISTICAL: "statistical",
    BACKGROUND: "background",
}

# A club's own site and the league's own site. Nothing outranks them on
# whether a player is available.
OFFICIAL_DOMAINS = frozenset({
    "premierleague.com", "arsenal.com", "avfc.co.uk", "afcb.co.uk",
    "brentfordfc.com", "brightonandhovealbion.com", "chelseafc.com",
    "cpfc.co.uk", "evertonfc.com", "fulhamfc.com", "ipswichtown.com",
    "lcfc.com", "liverpoolfc.com", "mancity.com", "manutd.com",
    "newcastleunited.com", "nottinghamforest.com", "safc.com",
    "tottenhamhotspur.com", "whufc.com", "wolves.co.uk", "burnleyfootballclub.com",
    "leedsunited.com", "sufc.co.uk", "coventrycity.co.uk",
})

# Outlets whose team-news and injury desks are the reason to read them.
TEAM_NEWS_SPECIALISTS = frozenset({
    "premierinjuries.com", "physioroom.com", "sportsmole.co.uk",
    "fantasyfootballscout.co.uk", "skysports.com", "football365.com",
    "espn.com", "goal.com", "cbssports.com", "nbcsports.com",
    "rotowire.com", "fourfourtwo.com",
})

STATISTICAL_DOMAINS = frozenset({
    "understat.com", "fbref.com", "footystats.org", "fotmob.com",
    "sofascore.com", "whoscored.com", "theanalyst.com", "statmuse.com",
    "squawka.com", "worldfootball.net", "soccerway.com", "flashscore.com",
    "xgstat.com",
})

# The kinds that lift an ordinary outlet to specialist standing on this
# question. Sports Mole is not a better publication than FBref; it does
# publish the predicted line-up, and FBref does not.
STATUS_KINDS = (PREDICTED_XI, TEAM_NEWS, PRESS_CONFERENCE, INJURY_UPDATE,
                SUSPENSION)

TIER_WEIGHT = {OFFICIAL: 1.0, SPECIALIST: 0.85, REPUTABLE: 0.6,
               STATISTICAL: 0.35, BACKGROUND: 0.15}


def status_tier(domain: str, kind: str) -> int:
    """Authority for a selection question, from the source AND the kind.

    Both matter and neither is sufficient. A club's own site publishing a
    shop promotion says nothing about the eleven; a mid-table outlet
    publishing the predicted line-up says a great deal.
    """
    domain = (domain or "").lower().lstrip("www.")
    if domain in OFFICIAL_DOMAINS and kind in STATUS_KINDS:
        return OFFICIAL
    if domain in OFFICIAL_DOMAINS:
        return REPUTABLE
    if kind in STATUS_KINDS and domain in TEAM_NEWS_SPECIALISTS:
        return SPECIALIST
    if kind in STATUS_KINDS:
        return SPECIALIST if kind == PREDICTED_XI else REPUTABLE
    if domain in STATISTICAL_DOMAINS:
        return STATISTICAL
    return BACKGROUND


# --- how much a piece of evidence has decayed ----------------------------

# Team selection is the most perishable thing in football. These bands are
# the difference between "he trained today" and "he trained in August".
RECENCY_BANDS = (
    (24, 1.0, "today"),
    (72, 0.8, "in the last three days"),
    (168, 0.5, "this week"),
    (504, 0.2, "in the last three weeks"),
    (100000, 0.05, "more than three weeks ago"),
)

# An item with no publication date cannot be shown to be current, and the
# safe reading of "cannot be shown" is "assume it is not". Sitemap URLs
# with no date used to slip through as though they were this morning's.
UNDATED_WEIGHT = 0.12


def recency_weight(age_hours: float | None) -> float:
    if age_hours is None:
        return UNDATED_WEIGHT
    if age_hours < 0:
        age_hours = 0.0
    for ceiling, weight, _ in RECENCY_BANDS:
        if age_hours < ceiling:
            return weight
    return RECENCY_BANDS[-1][1]


def recency_phrase(age_hours: float | None) -> str:
    if age_hours is None:
        return "at an unknown date"
    for ceiling, _, phrase in RECENCY_BANDS:
        if age_hours < ceiling:
            return phrase
    return RECENCY_BANDS[-1][2]


# --- is it about HIM, or merely near him ---------------------------------

IN_HEADLINE, IN_BODY, PASSING, CLUB_ONLY = 1.0, 0.7, 0.4, 0.15


def specificity(title: str, body: str, variants: list[str], own: set,
                mentions) -> float:
    """Named in the headline, discussed, mentioned, or not present at all.

    `mentions` is the disambiguating test from the evidence layer, passed
    in rather than imported so this module stays free of a circular
    dependency — and so a caller can be explicit about which player's
    name variants it is asking about.
    """
    headline = title or ""
    if any(mentions(headline, variant, own) for variant in variants):
        return IN_HEADLINE
    text = body or ""
    if not text:
        return CLUB_ONLY
    hits = 0
    for variant in variants:
        pattern = rf"(?<![A-Za-z0-9]){re.escape(variant)}(?![A-Za-z0-9])"
        hits += len(re.findall(pattern, text, flags=re.IGNORECASE))
    if hits >= 3:
        return IN_BODY
    if hits >= 1:
        return PASSING
    return CLUB_ONLY


@dataclass
class Graded:
    """One article, scored for one player's selection question."""

    title: str = ""
    url: str = ""
    source: str = ""
    domain: str = ""
    published: str = ""
    age_hours: float | None = None
    kind: str = GENERAL
    tier: int = BACKGROUND
    recency: float = 0.0
    specificity: float = 0.0
    relevance: float = 0.0
    excerpt: str = ""

    @property
    def weight(self) -> float:
        """One number, but only after the four parts have been kept apart.

        Multiplicative on purpose: an article that fails any one of the
        four is worthless for this question however well it scores on the
        others, and a sum would let a famous source with nothing to say
        outvote a small one that answers it.
        """
        return round(TIER_WEIGHT.get(self.tier, 0.15) * self.recency
                     * self.specificity * self.relevance, 4)

    @property
    def tier_name(self) -> str:
        return TIER_NAMES.get(self.tier, "background")

    @property
    def fresh(self) -> bool:
        return self.age_hours is not None and self.age_hours <= 72

    def as_dict(self) -> dict:
        return {"title": self.title, "url": self.url, "source": self.source,
                "published": self.published, "kind": self.kind,
                "tier": self.tier, "tier_name": self.tier_name,
                "age_hours": (round(self.age_hours, 1)
                              if self.age_hours is not None else None),
                "when": recency_phrase(self.age_hours),
                "recency": self.recency, "specificity": self.specificity,
                "relevance": self.relevance, "weight": self.weight,
                "excerpt": self.excerpt[:300]}


def grade(article, variants: list[str], own: set, mentions,
          now: datetime | None = None) -> Graded:
    """Scores one article for one player's "will he play?" question."""
    body = getattr(article, "body", "") or getattr(article, "excerpt", "") or ""
    title = getattr(article, "title", "") or ""
    kind = article_kind(title, body)
    domain = getattr(article, "domain", "") or ""
    age = None
    if hasattr(article, "age_hours"):
        age = article.age_hours(now) if now else article.age_hours()
    return Graded(
        title=title, url=getattr(article, "url", ""),
        source=getattr(article, "source", ""), domain=domain,
        published=getattr(article, "published", ""), age_hours=age,
        kind=kind, tier=status_tier(domain, kind),
        recency=recency_weight(age),
        specificity=specificity(title, body, variants, own, mentions),
        relevance=DECISION_RELEVANCE.get(kind, 0.15),
        excerpt=(body or "")[:300])


# --- what to go looking for ----------------------------------------------

def targeted_terms(player: str, full_name: str, club: str, club_name: str,
                   opponent: str = "") -> list[str]:
    """The searches a manager would actually run before a deadline.

    Generated from the DECISION rather than from the player, which is the
    difference between "tell me about Ndiaye" and "will Ndiaye start
    against Coventry". The corpus is then filtered by these instead of by
    the player's name alone.
    """
    name = full_name or player
    club_label = club_name or club
    terms = [
        f"{name} {club_label} predicted lineup",
        f"{name} {club_label} team news",
        f"{club_label} predicted XI",
        f"{club_label} team news",
        f"{name} injury",
        f"{name} start",
        f"{club_label} press conference",
    ]
    if opponent:
        terms.insert(0, f"{club_label} predicted XI {opponent}")
        terms.insert(1, f"{name} start {opponent}")
    if name != player:
        terms.append(f"{player} {club_label}")
    return terms


# --- reading a predicted line-up -----------------------------------------

STARTS, BENCHED, OMITTED, UNREAD = "starts", "benched", "omitted", "unread"

# Where the eleven stops and the substitutes begin. Almost every predicted
# line-up in the corpus uses one of these.
BENCH_MARKERS = ("subs:", "substitutes:", "bench:", "subs :", "substitutes :",
                 "on the bench:", "replacements:", "also available:")

# A lineup listing has a formation in it, or a long run of surnames. Used
# to tell "this article contains an eleven I can read" from "this article
# talks about an eleven", because only the first can support the claim
# that a player was left OUT of it.
FORMATION = re.compile(r"\b[3-5]-[1-5]-[1-4](?:-[1-3])?\b")


def lineup_verdict(body: str, variants: list[str], own: set, mentions) -> str:
    """Does this predicted line-up start him, bench him, or leave him out?

    Deliberately cautious in one direction. Reading "he starts" wrongly
    costs a manager points; reading UNREAD wrongly costs nothing but a
    softer confidence, so anything ambiguous returns UNREAD and the
    caller treats it as no evidence rather than as evidence of absence.
    """
    text = body or ""
    if not text:
        return UNREAD
    lowered = text.lower()

    split_at = None
    for marker in BENCH_MARKERS:
        found = lowered.find(marker)
        if found != -1 and (split_at is None or found < split_at):
            split_at = found

    def named(section: str) -> bool:
        # A line-up is a LIST, not prose, so it is read slot by slot. The
        # name disambiguator is built for sentences: given "Cherki,
        # Semenyo; Haaland" it reads each capitalised neighbour as part of
        # somebody else's full name and rejects every player in the
        # eleven. Splitting on the separators first gives each name its
        # own slot with nothing beside it, which is what a team sheet
        # actually is.
        for slot in re.split(r"[,;:|\n\u2022]+", section):
            slot = slot.strip()
            if not slot:
                continue
            if any(mentions(slot, variant, own) for variant in variants):
                return True
        return False

    if split_at is not None:
        eleven, bench = text[:split_at], text[split_at:]
        if named(eleven):
            return STARTS
        if named(bench):
            return BENCHED
        # A readable listing that does not contain him at all is a claim
        # that he is not in the squad — but only if it really is a
        # listing, not an article that happens to use the word "subs".
        if FORMATION.search(text) or _surname_run(text[:split_at]):
            return OMITTED
        return UNREAD

    if named(text) and FORMATION.search(text):
        # A formation with no bench section: the names given are the
        # eleven, so being among them means starting.
        return STARTS
    return UNREAD


def _surname_run(text: str, needed: int = 8) -> bool:
    """Does this read as a list of names rather than as prose?"""
    tokens = re.findall(r"\b[A-ZÀ-Þ][a-zà-þ'’-]{2,}\b", text or "")
    return len(tokens) >= needed


@dataclass
class LineupTally:
    """What the current crop of predicted line-ups says about one player."""

    starts: int = 0
    benched: int = 0
    omitted: int = 0
    unread: int = 0
    sources: list[str] = field(default_factory=list)

    @property
    def readable(self) -> int:
        return self.starts + self.benched + self.omitted

    @property
    def summary(self) -> str:
        if not self.readable:
            return "no current predicted line-up names him either way"
        parts = []
        if self.starts:
            parts.append(f"{self.starts} start him")
        if self.benched:
            parts.append(f"{self.benched} bench him")
        if self.omitted:
            parts.append(f"{self.omitted} leave him out")
        return f"{self.readable} predicted line-up(s): " + ", ".join(parts)

    def as_dict(self) -> dict:
        return {"starts": self.starts, "benched": self.benched,
                "omitted": self.omitted, "unread": self.unread,
                "readable": self.readable, "summary": self.summary,
                "sources": self.sources}


# --- reading what a manager actually said --------------------------------

WILL_START = "will start"
WONT_START = "will not start"
UNDECIDED = "undecided"
AVAILABLE = "available"
UNAVAILABLE = "unavailable"

# Ordered most specific first: "will not start" has to be tested before
# "will start", or every denial reads as a promise.
MANAGER_PATTERNS = (
    (WONT_START, ("will not start", "won't start", "is not ready",
                  "not ready to start", "will not be involved",
                  "is not available", "won't be available", "not in the squad",
                  "needs more time", "is not fit", "will miss")),
    (UNDECIDED, ("we will decide", "we'll decide", "decide tomorrow",
                 "assess him", "we will see", "we'll see", "late test",
                 "50-50", "touch and go", "have to wait",
                 "make a decision on")),
    (WILL_START, ("will start", "he starts", "is going to start",
                  "will be in the team", "will play from the start",
                  "is in the team", "will feature from the start")),
    (AVAILABLE, ("is available", "is fit", "back in training",
                 "trained fully", "is ready", "back available",
                 "will be involved", "is in contention")),
    (UNAVAILABLE, ("is out", "ruled out", "will be out", "is injured",
                   "is suspended", "faces a spell")),
)

# How hard each reading pushes, on a -1 (certainly not) to +1 scale.
MANAGER_FORCE = {WILL_START: 0.9, AVAILABLE: 0.35, UNDECIDED: -0.25,
                 WONT_START: -0.8, UNAVAILABLE: -1.0}


# Reported speech. Without one of these the sentence is a pundit's
# prediction, and a pundit saying "he will start" is a guess with a
# byline — useful, but not the club telling you.
ATTRIBUTION = ("said", "told", "confirmed", "insisted", "explained",
               "revealed", "added", "stated", "admitted", "suggested",
               "speaking", "asked about", "when asked", "gave an update")


def _attributed(sentence: str, previous: str = "") -> bool:
    """Is this reported speech, or somebody's opinion about the team?"""
    lowered = sentence.lower()
    if any(marker in lowered for marker in ATTRIBUTION):
        return True
    # "Guardiola: he is not ready" — a colon after a name is attribution
    # in headline grammar, which is where half of these appear.
    if re.match(r"^\s*[A-ZÀ-Þ][A-Za-zÀ-þ'’-]+(?:\s+[A-ZÀ-Þ][A-Za-zÀ-þ'’-]+)?\s*:",
                sentence):
        return True
    return any(marker in (previous or "").lower() for marker in ATTRIBUTION)


def manager_signal(text: str) -> tuple[str, str]:
    """The strongest thing a manager is reported to have said, and where.

    Returns the reading and the sentence it came from, so a write-up can
    show the words rather than a label derived from them — "we will
    decide tomorrow" is not the same as "he is a doubt", and flattening
    the two is how a vague comment becomes a certainty.

    Gated on ATTRIBUTION rather than on the article being titled "press
    conference", because managers are quoted everywhere and almost never
    under that headline. The quote has to be reported speech; a
    columnist's prediction is not the club speaking.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text or "")
    for reading, patterns in MANAGER_PATTERNS:
        for index, sentence in enumerate(sentences):
            lowered = sentence.lower()
            if not any(pattern in lowered for pattern in patterns):
                continue
            previous = sentences[index - 1] if index else ""
            if _attributed(sentence, previous):
                return reading, sentence.strip()
    return "", ""
