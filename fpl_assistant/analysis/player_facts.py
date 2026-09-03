"""What the evidence establishes, before anything is written about it.

The failure this replaces: prose was assembled straight from article
sentences that happened to mention a player or his club. That produced
claims nobody had made. "Foden and Cherki are the City players to triple
up on" became a reason to SELL SEMENYO — an article about two other
players, silent on Semenyo, read as an argument against him. "Chelsea have
scored seven" became a reason to sell Gabriel. A note about Tzolakis being
heavily bought appeared as a risk to Raya.

None of those are layout problems. They are what happens when the step
between evidence and conclusion is missing, so the pipeline now has one:

    ARTICLE / DATA EVIDENCE
        -> classified into buckets, and gated on being about this player
    STRUCTURED PLAYER FACTS
        -> availability, minutes, role, fixtures, expert view, verdict
    HOMEPAGE PROSE
        -> written from the facts, never from the raw sentences

Two rules do most of the work.

**A sentence must be about the player.** Naming his club is not enough.
The exception is a small set of genuinely club-level facts — a clean-sheet
outlook, a manager's selection policy — and those may only ever populate
club-level buckets, never a claim about him personally.

**A conclusion must be supported by the right bucket.** "Sell him" needs
evidence of reduced minutes, a worse role, injury, transfer risk, poor
fixtures, weak underlying numbers or an explicit expert sell. The absence
of a player from someone else's list of favourites is not evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from fpl_assistant.research import evidence as ev

# --- evidence buckets -----------------------------------------------------

AVAILABILITY = "availability"
MINUTES = "expected minutes"
SELECTION = "recent selection"
ROLE = "tactical role"
SET_PIECES = "set pieces"
PENALTIES = "penalties"
INJURY = "injury"
TRANSFER = "transfer status"
FORM = "form"
UNDERLYING = "underlying data"
FIXTURES = "fixture outlook"
TEAM_STRENGTH = "team strength"
EXPERT_BUY = "expert buy"
EXPERT_SELL = "expert sell"
EXPERT_HOLD = "expert hold"
CAPTAINCY = "captaincy"
VALUE = "price / value"
OWNERSHIP = "ownership"
CLEAN_SHEET = "clean-sheet outlook"
DEFCON = "defensive contribution"
ROTATION = "rotation"
SUSPENSION = "suspension"

# Phrases that put a sentence in a bucket. Deliberately specific: a single
# common word matching was how ticket bulletins became team news.
BUCKET_TERMS = {
    AVAILABILITY: ("ruled out", "unavailable", "will miss", "out for", "sidelined",
                   "available for selection", "back in contention", "fit to face"),
    MINUTES: ("expected to start", "set to start", "will start", "in line to start",
              "starting xi", "predicted line", "minutes", "game time"),
    SELECTION: ("started", "was benched", "came on as", "left out", "omitted",
                "named in the squad", "dropped"),
    ROLE: ("role", "played as", "deployed", "position", "deeper", "advanced",
           "false nine", "inverted", "wing-back", "shifted to"),
    SET_PIECES: ("set piece", "corner", "free kick", "dead ball", "set-piece"),
    PENALTIES: ("penalt", "spot kick", "from the spot"),
    INJURY: ("injury", "injured", "hamstring", "knock", "scan", "surgery",
             "fitness", "doubt", "strain"),
    TRANSFER: ("bid for", "a bid", "medical", "release clause", "agreed terms",
               "transfer fee", "set to join", "completed a move", "asking price",
               "linked with a move", "transfer request"),
    FORM: ("in form", "scored", "assist", "goal", "brace", "hat-trick", "haul",
           "blank", "struggling", "poor run"),
    UNDERLYING: ("xg", "xa", "xgi", "expected goals", "expected assists",
                 "underlying", "per 90", "shots", "big chance", "chances created"),
    FIXTURES: ("fixture", "run of games", "next three", "next five", "schedule",
               "double gameweek", "blank gameweek"),
    TEAM_STRENGTH: ("best defence", "best attack", "title race", "top four"),
    EXPERT_BUY: ("buy", "bring in", "transfer in", "great pickup", "immediate buy",
                 "worth a punt", "target"),
    EXPERT_SELL: ("sell", "ship out", "move him on", "transfer out", "get rid",
                  "chopping block", "panic sell"),
    EXPERT_HOLD: ("hold", "keep", "stick with", "no reason to sell", "patience"),
    CAPTAINCY: ("captain", "armband", "triple captain", "vice-captain"),
    VALUE: ("value", "£", "price rise", "price fall", "bargain", "enabler"),
    OWNERSHIP: ("ownership", "owned by", "selected by", "template", "differential"),
    CLEAN_SHEET: ("clean sheet", "shut out", "kept out", "conceded"),
    DEFCON: ("defensive contribution", "defcon", "tackles", "interceptions",
             "clearances", "cbit"),
    ROTATION: ("rotation", "rotated", "rested", "squad depth", "midweek"),
    SUSPENSION: ("suspended", "suspension", "red card", "ban", "sent off"),
}

# Buckets that may be populated by a club-level article — the fixture, the
# defence, the manager's general policy. Everything else needs the player
# named, because everything else is a claim about him personally.
CLUB_LEVEL_BUCKETS = frozenset({FIXTURES, TEAM_STRENGTH, CLEAN_SHEET})

# What may support a decision to sell. The absence of a player from
# someone else's shortlist is not on this list, and that is the point.
SELL_SUPPORT = frozenset({
    AVAILABILITY, INJURY, SUSPENSION, ROTATION, TRANSFER, EXPERT_SELL,
    MINUTES, SELECTION, ROLE,
})
BUY_SUPPORT = frozenset({
    EXPERT_BUY, FORM, UNDERLYING, SET_PIECES, PENALTIES, FIXTURES, ROLE, MINUTES,
})

# Claim kinds, so an inference is never presented as something a
# journalist said.
FACT = "fact"
STATISTICAL = "statistical"
EXPERT = "expert opinion"
INFERENCE = "inference"


@dataclass
class Claim:
    """One thing believed about a player, and where the belief came from."""

    text: str
    kind: str
    buckets: tuple[str, ...] = ()
    source: str = ""
    url: str = ""
    published: str = ""
    player_named: bool = False

    def as_dict(self) -> dict:
        return {"text": self.text, "kind": self.kind, "buckets": list(self.buckets),
                "source": self.source, "url": self.url, "published": self.published,
                "player_named": self.player_named}


def buckets_for(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    return tuple(bucket for bucket, terms in BUCKET_TERMS.items()
                 if any(term in lowered for term in terms))


def names_player(text: str, name: str, full_name: str = "") -> bool:
    """Is this sentence ABOUT the player, or merely near him?

    The gate that stops João Pedro's news appearing in Raya's card.
    """
    normalised = ev.normalise(text)
    return any(ev._mentions(normalised, variant)
               for variant in ev.name_variants(name, full_name))


def classify(text: str, name: str, club: str, full_name: str = "",
             source: str = "", url: str = "", published: str = "") -> Claim | None:
    """Turns one sentence into a claim about this player, or discards it.

    Returns None when the sentence cannot legitimately say anything about
    him — which is most sentences in most articles, and is the whole
    reason the old approach produced nonsense.
    """
    named = names_player(text, name, full_name)
    found = buckets_for(text)
    if not found:
        return None

    if not named:
        # A club article may still establish club-level facts, but only
        # those, and the claim is marked as not naming him so the prose
        # can say "Arsenal" rather than putting words in his mouth.
        found = tuple(b for b in found if b in CLUB_LEVEL_BUCKETS)
        if not found:
            return None

    lowered = text.lower()
    if any(b in found for b in (EXPERT_BUY, EXPERT_SELL, EXPERT_HOLD, CAPTAINCY)):
        kind = EXPERT
    elif UNDERLYING in found or re.search(r"\d", lowered):
        kind = STATISTICAL
    else:
        kind = FACT
    return Claim(text=text.strip(), kind=kind, buckets=found, source=source,
                 url=url, published=published, player_named=named)


# --- the structured assessment -------------------------------------------

FIT, DOUBT, OUT, UNKNOWN = "Fit", "Doubt", "Out", "Unknown"
STARTED, BENCHED, OMITTED = "Started", "Benched", "Omitted"
BUY, HOLD, SELL, MIXED, LIMITED = "Buy", "Hold", "Sell", "Mixed", "Limited evidence"

START, BENCH, KEEP, SELL_VERDICT = "Start", "Bench", "Keep", "Sell"
MONITOR, CAPTAIN, VICE = "Monitor", "Captain", "Vice"

HIGH, MEDIUM, LOW = "High", "Medium", "Low"


@dataclass
class PlayerFacts:
    """Everything concluded about one player, before a word is written.

    The homepage renders from this and nothing else. If a fact is not
    here, it cannot reach the page — which is how a sentence about another
    player stops being able to leak into this one's write-up.
    """

    player: str
    club: str
    position: str
    price: float = 0.0

    availability: str = UNKNOWN
    expected_minutes: str = "Unknown"
    recent_selection: str = "Unknown"
    role: str = ""
    set_pieces: str = ""
    fixture: str = ""
    next_fixtures: list[str] = field(default_factory=list)
    form: str = ""
    underlying: str = ""
    expert_view: str = LIMITED
    sell_urgency: float = 0.0
    sell_band: str = ""
    verdict: str = KEEP
    confidence: str = LOW
    main_positive: str = ""
    main_risk: str = ""

    claims: list[Claim] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    @property
    def starting(self) -> bool:
        return self.verdict in (START, CAPTAIN, VICE)

    def claims_in(self, *buckets: str) -> list[Claim]:
        wanted = set(buckets)
        return [c for c in self.claims if wanted & set(c.buckets)]

    def supports_sale(self) -> list[Claim]:
        """Evidence that would actually justify selling him."""
        return [c for c in self.claims_in(*SELL_SUPPORT) if c.player_named]

    def as_dict(self) -> dict:
        return {
            "player": self.player, "club": self.club, "position": self.position,
            "price": self.price, "availability": self.availability,
            "expected_minutes": self.expected_minutes,
            "recent_selection": self.recent_selection, "role": self.role,
            "set_pieces": self.set_pieces, "fixture": self.fixture,
            "next_fixtures": self.next_fixtures, "form": self.form,
            "underlying": self.underlying, "expert_view": self.expert_view,
            "sell_urgency": round(self.sell_urgency, 1), "sell_band": self.sell_band,
            "verdict": self.verdict, "confidence": self.confidence,
            "main_positive": self.main_positive, "main_risk": self.main_risk,
            "claims": [c.as_dict() for c in self.claims],
            "sources": self.sources,
        }


def expert_view_from(claims: list[Claim]) -> str:
    """What the analysts actually said, when they said it about HIM."""
    named = [c for c in claims if c.player_named]
    buys = sum(1 for c in named if EXPERT_BUY in c.buckets)
    sells = sum(1 for c in named if EXPERT_SELL in c.buckets)
    holds = sum(1 for c in named if EXPERT_HOLD in c.buckets)
    if not (buys or sells or holds):
        return LIMITED
    if buys and sells:
        return MIXED
    if sells > max(buys, holds):
        return SELL
    if buys > max(sells, holds):
        return BUY
    return HOLD


def build(name: str, club: str, position: str, price: float, *,
          quotes: list[dict] | None = None, full_name: str = "",
          availability: str = UNKNOWN, expected_minutes: str = "Unknown",
          sell_urgency: float = 0.0, sell_band: str = "",
          fixture: str = "", next_fixtures: list[str] | None = None,
          form: str = "", underlying: str = "", starting: bool = True,
          captain: bool = False, vice: bool = False) -> PlayerFacts:
    """Assembles one player's structured assessment from gated evidence."""
    facts = PlayerFacts(
        player=name, club=club, position=position, price=price,
        availability=availability, expected_minutes=expected_minutes,
        sell_urgency=sell_urgency, sell_band=sell_band, fixture=fixture,
        next_fixtures=list(next_fixtures or []), form=form, underlying=underlying,
    )

    for quote in quotes or []:
        claim = classify(
            quote.get("text", ""), name, club, full_name,
            source=quote.get("source", ""), url=quote.get("url", ""),
            published=quote.get("published", ""))
        if claim:
            facts.claims.append(claim)
    facts.sources = sorted({c.source for c in facts.claims if c.source})

    facts.expert_view = expert_view_from(facts.claims)

    selection = facts.claims_in(SELECTION)
    for claim in selection:
        if not claim.player_named:
            continue
        lowered = claim.text.lower()
        if "omitted" in lowered or "left out" in lowered:
            facts.recent_selection = OMITTED
        elif "benched" in lowered or "came on as" in lowered:
            facts.recent_selection = BENCHED
        elif "started" in lowered:
            facts.recent_selection = STARTED
        break

    role_claims = [c for c in facts.claims_in(ROLE) if c.player_named]
    if role_claims:
        facts.role = role_claims[0].text
    piece_claims = [c for c in facts.claims_in(SET_PIECES, PENALTIES) if c.player_named]
    if piece_claims:
        facts.set_pieces = piece_claims[0].text

    # --- the verdict ----------------------------------------------------
    if availability == OUT:
        facts.verdict = SELL_VERDICT
    elif captain:
        facts.verdict = CAPTAIN
    elif vice:
        facts.verdict = VICE
    elif availability == DOUBT or expected_minutes in ("Significant concern", "Major doubt"):
        facts.verdict = MONITOR
    elif starting:
        facts.verdict = START
    else:
        facts.verdict = BENCH

    # --- confidence -----------------------------------------------------
    named_claims = [c for c in facts.claims if c.player_named]
    if expected_minutes in ("Very secure", "Secure") and len(named_claims) >= 2:
        facts.confidence = HIGH
    elif expected_minutes == "Unknown" and not named_claims:
        facts.confidence = LOW
    else:
        facts.confidence = MEDIUM

    facts.main_positive, facts.main_risk = _headline_points(facts)
    return facts


def _headline_points(facts: PlayerFacts) -> tuple[str, str]:
    """The one reason to keep him and the one thing that could go wrong.

    Drawn from the structured fields rather than from a quote, so the risk
    named is always a risk to THIS player. A note about somebody else
    being heavily transferred in is not a risk to him, and used to appear
    as one.
    """
    positive = ""
    if facts.expected_minutes in ("Very secure", "Secure"):
        positive = f"minutes look {facts.expected_minutes.lower()}"
    if facts.set_pieces:
        positive = "set-piece responsibility" if not positive else positive + " and set pieces"
    if facts.expert_view == BUY:
        positive = "analysts are recommending him" if not positive else positive
    if not positive and facts.form:
        positive = facts.form

    risk = ""
    if facts.availability == OUT:
        risk = "he is unavailable"
    elif facts.availability == DOUBT:
        risk = "his availability is in doubt"
    elif facts.expected_minutes in ("Significant concern", "Major doubt"):
        risk = f"expected minutes are a {facts.expected_minutes.lower()}"
    elif facts.recent_selection in (BENCHED, OMITTED):
        risk = f"he was {facts.recent_selection.lower()} last time out"
    elif facts.expert_view == SELL:
        risk = "analysts are recommending a sale"
    elif facts.expected_minutes == "Unknown":
        risk = "recent team-news evidence is limited"
    elif facts.claims_in(TRANSFER):
        risk = "there is transfer speculation around him"
    return positive, risk
