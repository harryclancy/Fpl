"""Stage B: turning the research corpus into what the homepage says.

Until now the two halves of this app were not connected. Stage A grew into
a real research engine — 78 sources, a thousand candidates a pass, ranked
and deep-read — and the homepage still read its prose from a JSON file a
Claude Code session had typed by hand. The corpus was a backend that
nothing on the page consumed.

This closes that. Every sentence a player's write-up makes is now lifted
from an article the pipeline actually retrieved, attributed to the outlet
that published it, with the URL kept so any claim can be traced.

WHAT THIS IS, PRECISELY, so nobody is misled by it:

It is composition, not authorship. There is no language model here — a
paid API is ruled out, and the whole system runs on public feeds for
nothing. So the engine finds the sentences in the corpus that are actually
about this player, sorts them into the questions a manager asks (is he
fit? is he starting? what changed? what do the analysts say?), and
assembles them with connective prose. The judgement in the output is the
selection and ordering; the claims are all quoted from someone who
published them.

That has one great advantage over generated text: it cannot invent a fact.
If nothing was written about a player, the write-up says nothing was
written about him, which is the honest answer and the one the old system
could never give.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fpl_assistant.research import evidence as ev
from fpl_assistant.research.extract import TOPIC_PATTERNS

# A sentence shorter than this is a fragment, a caption or a scoreline.
MIN_SENTENCE_CHARS = 45
MAX_SENTENCE_CHARS = 400
# More than this from one article and the write-up is just that article.
MAX_PER_ARTICLE = 2
MAX_QUOTES_PER_SECTION = 3

# Words that mark a claim as favourable or unfavourable to owning a player.
# Deliberately narrow: the goal is to sort quotes into two piles a manager
# weighs, not to score sentiment. A term that is ambiguous is left out
# rather than guessed at, because a miscategorised quote reads as the
# engine having an opinion it cannot support.
POSITIVE = (
    "goal", "scored", "assist", "brace", "hat-trick", "start", "started",
    "fit", "trained", "returns", "available", "impressed", "excellent", "in form",
    "penalties", "set piece", "nailed", "buy", "captain", "haul", "bonus",
    "clean sheet", "big chance", "created",
)
NEGATIVE = (
    "injury", "injured", "ruled out", "doubt", "sidelined", "out for",
    "suspended", "benched", "substitute", "dropped", "omitted", "rotation",
    "rested", "concern", "struggling", "blank", "sell", "miss", "setback",
    "knock", "hamstring", "surgery",
)

# Which topics answer which question on the card.
SECTION_TOPICS = {
    "status": ("team news", "press conference", "injury", "suspension"),
    "minutes": ("team news", "press conference", "rotation", "injury", "match report"),
    "developments": ("match report", "transfer", "injury", "press conference", "team news"),
    "outlook": ("fixtures", "fpl advice", "tactics", "statistics"),
}

# Abbreviations that end in a full stop and are not the end of a sentence.
# "St James' Park" split into a fragment beginning "James' Park with a
# point in Sunday's draw", which was then quoted as a source's words.
ABBREVIATIONS = ("St", "Mr", "Mrs", "Ms", "Dr", "No", "vs", "Jr", "Sr",
                 "Ave", "Rd", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat",
                 "Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep", "Oct",
                 "Nov", "Dec")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-Ü“\"'])")
# Python's `re` allows only fixed-width lookbehind, so the abbreviation
# guard cannot live in the split pattern. The stop is masked before the
# split and restored afterwards, which is simpler and does the same job.
_ABBREV_DOT = re.compile(rf"\b({'|'.join(ABBREVIATIONS)})\.", re.IGNORECASE)
_DOT_MASK = "\x00"

# RSS feeds append this to nearly every excerpt. It is the feed's own
# plumbing and carries no claim.
FEED_TAIL = re.compile(r"\s*The post .*? appeared first on .*$", re.IGNORECASE | re.DOTALL)

# Site chrome that survived extraction. A nav bar has no full stops, so it
# arrives as one long "sentence" and reads like prose to a naive splitter —
# which is how "Free Team Rating FPL Fixture Ticker ... Win prizes" ended up
# quoted as evidence about Haaland.
NAV_MARKERS = (
    "join our leagues", "win prizes", "download the app", "choose competition",
    "fixture ticker", "team reveals", "sign up", "log in", "toolkit",
    "why join us", "free team rating", "latest news", "more from", "related articles",
    "most read", "top stories", "watch live", "buy tickets", "shop now",
    # Byline and syndication chrome. A live run quoted "Mitch Fretton Last
    # Update: 1 hour ago 3 min read Add us as a preferred source on
    # Google" as evidence about a centre-half, because the sentence
    # splitter found no full stop before the real prose began.
    "last update", "min read", "preferred source", "add us as a",
    "reading time", "follow us on", "subscribe", "newsletter",
    "please use chrome", "accessible video player", "stream pl games",
    "no contract", "getty images", "image credit", "advertisement",
)
# A run of Capitalised Words With No Verb is a menu or a team list, not a
# sentence. Measured rather than guessed: real prose is mostly lowercase.
MAX_CAPITALISED_SHARE = 0.5
MIN_LOWERCASE_WORDS = 6

# Chrome that sits immediately before the first real sentence on a page:
# a byline date, a comment counter, a share bar. Stripped from the front
# rather than rejecting the sentence, because the prose after it is good.
LEAD_NOISE = re.compile(
    r"^(?:\s*(?:\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2}|\d+\s+comments?|"
    r"share|by\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?|updated|published)\s*[|·–—-]?\s*)+",
    re.IGNORECASE)

# Text encoded as UTF-8 and decoded as latin-1 leaves these. Cheap to
# repair and the alternative is quoting "donât" back at the reader.
MOJIBAKE = {
    "â\x80\x99": "’", "â\x80\x98": "‘", "â\x80\x9c": "“", "â\x80\x9d": "”",
    "â\x80\x93": "–", "â\x80\x94": "—", "â\x80\xa6": "…", "Â": "",
    "â€™": "’", "â€˜": "‘", "â€œ": "“", "â€\x9d": "”", "â€“": "–", "â€”": "—",
}


def _clean(sentence: str) -> str:
    for bad, good in MOJIBAKE.items():
        sentence = sentence.replace(bad, good)
    sentence = LEAD_NOISE.sub("", sentence)
    return re.sub(r"\s+", " ", sentence).strip()


@dataclass
class Quote:
    """One sentence someone published, and where it came from."""

    text: str
    source: str
    url: str
    published: str = ""
    topics: tuple[str, ...] = ()
    tone: str = "neutral"

    @property
    def when(self) -> str:
        try:
            stamp = datetime.fromisoformat(self.published.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return ""
        return stamp.strftime("%d %b")

    def cite(self) -> str:
        when = f", {self.when}" if self.when else ""
        return f"{self.source}{when}"

    def as_dict(self) -> dict:
        return {"text": self.text, "source": self.source, "url": self.url,
                "published": self.published, "tone": self.tone,
                "topics": list(self.topics)}


@dataclass
class PlayerWriteup:
    """Everything the homepage says about one player, and its receipts."""

    player: str
    club: str
    status: str = ""
    why_here: str = ""
    case_for: str = ""
    case_against: str = ""
    expected_minutes: str = ""
    developments: str = ""
    outlook: str = ""
    confidence: str = "low"
    evidence_used: list[str] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)
    quotes: list[Quote] = field(default_factory=list)
    evidence_count: int = 0

    @property
    def has_prose(self) -> bool:
        """Real prose means at least one quoted sentence from a real article.

        The fallback sentences ("nothing was retrieved about him") are
        honest but they are this module talking, not reporting. Counting
        them as prose reported 15/15 when six players had no quote at all.
        """
        return bool(self.quotes)

    def as_dict(self) -> dict:
        return {
            "player": self.player, "club": self.club, "status": self.status,
            "why_here": self.why_here, "case_for": self.case_for,
            "case_against": self.case_against,
            "expected_minutes": self.expected_minutes,
            "developments": self.developments, "outlook": self.outlook,
            "confidence": self.confidence, "evidence_count": self.evidence_count,
            "evidence_used": self.evidence_used, "sources_used": self.sources_used,
            "quotes": [q.as_dict() for q in self.quotes],
        }


def _is_prose(sentence: str) -> bool:
    """Is this something a person wrote, or something a site displays?

    Three checks, each earned by a specific piece of rubbish that reached a
    write-up: a navigation bar quoted as a claim about Haaland, a squad
    list with no verb in it, and an article headline echoed back as though
    it were reporting.
    """
    lowered = sentence.lower()
    if any(marker in lowered for marker in NAV_MARKERS):
        return False

    # A fragment left by a bad split starts mid-clause. Requiring the
    # first word to be capitalised or a quote mark catches most of them.
    first = sentence.lstrip("“\"'")[:1]
    if first and not (first.isupper() or first.isdigit()):
        return False

    words = [w for w in sentence.split() if w.isalpha()]
    if len(words) < 8:
        return False
    capitalised = sum(1 for w in words if w[:1].isupper())
    if capitalised / len(words) > MAX_CAPITALISED_SHARE:
        return False
    if sum(1 for w in words if w.islower()) < MIN_LOWERCASE_WORDS:
        return False

    # A headline posed as a question is a prompt, not a finding.
    if sentence.rstrip().endswith("?"):
        return False
    return True


def _sentences(text: str, exclude_title: str = "") -> list[str]:
    """Splits into sentences, keeping only the ones that are actually prose."""
    cleaned_text = FEED_TAIL.sub("", text or "")
    cleaned_text = _ABBREV_DOT.sub(lambda m: m.group(1) + _DOT_MASK, cleaned_text)
    title_key = ev.normalise(exclude_title)[:60] if exclude_title else ""
    out = []
    for chunk in SENTENCE_SPLIT.split(cleaned_text):
        cleaned = _clean(chunk.replace(_DOT_MASK, "."))
        if not (MIN_SENTENCE_CHARS <= len(cleaned) <= MAX_SENTENCE_CHARS):
            continue
        if not _is_prose(cleaned):
            continue
        # An excerpt that merely repeats the headline adds nothing, and
        # quoting it makes a title look like sourced reporting.
        if title_key and ev.normalise(cleaned)[:60] == title_key:
            continue
        out.append(cleaned)
    return out


def _tone(sentence: str) -> str:
    lowered = sentence.lower()
    positive = sum(1 for term in POSITIVE if term in lowered)
    negative = sum(1 for term in NEGATIVE if term in lowered)
    if negative > positive:
        return "negative"
    if positive > negative:
        return "positive"
    return "neutral"


def _topics(sentence: str) -> tuple[str, ...]:
    lowered = sentence.lower()
    return tuple(topic for topic, terms in TOPIC_PATTERNS.items()
                 if any(term in lowered for term in terms))


def quotes_for(name: str, club: str, items, full_name: str = "") -> list[Quote]:
    """Every published sentence that is actually about this player.

    Reads the deep-read body where there is one and falls back to the
    excerpt otherwise, which is why the deep-read stage matters: a teaser
    yields one usable sentence, a full article yields a dozen.
    """
    variants = ev.name_variants(name, full_name)
    own = ev.own_tokens(name, full_name)
    found: list[Quote] = []
    seen: set[str] = set()

    for item in items:
        article = getattr(item, "article", item)
        text = article.body or article.excerpt
        if not text:
            continue
        taken = 0
        for sentence in _sentences(text, exclude_title=article.title):
            if taken >= MAX_PER_ARTICLE:
                break
            normalised = ev.normalise(sentence)
            # Read on the ORIGINAL sentence, so capitalisation can tell
            # this player apart from everybody else who shares his name.
            if not any(ev.mentions_this_player(sentence, variant, own)
                       for variant in variants):
                continue
            key = normalised[:90]
            if key in seen:
                continue
            seen.add(key)
            found.append(Quote(
                text=sentence, source=article.source, url=article.url,
                published=article.published, topics=_topics(sentence),
                tone=_tone(sentence),
            ))
            taken += 1

    found.sort(key=lambda q: q.published or "", reverse=True)
    return found


def _pick(quotes: list[Quote], topics: tuple[str, ...] = (), tone: str = "",
          limit: int = MAX_QUOTES_PER_SECTION, used: set | None = None) -> list[Quote]:
    """Selects quotes for one section, never reusing one already spent.

    Without `used`, the same sentence appeared under current status, case
    for, recent developments and the outlook — four headings, one fact,
    reading as four independent pieces of evidence.
    """
    chosen = []
    for quote in quotes:
        if used is not None and quote.text in used:
            continue
        if tone and quote.tone != tone:
            continue
        if topics and not (set(quote.topics) & set(topics)):
            continue
        chosen.append(quote)
        if used is not None:
            used.add(quote.text)
        if len(chosen) >= limit:
            break
    return chosen


def _join(quotes: list[Quote], lead: str) -> str:
    """Assembles quoted claims into a paragraph, attributed as it goes."""
    if not quotes:
        return ""
    parts = [lead] if lead else []
    for quote in quotes:
        parts.append(f"{quote.cite()}: “{quote.text}”")
    return " ".join(parts)


def build(name: str, club: str, items, *, full_name: str = "", price: float = 0.0,
          position: str = "", starting: bool = True, captain: bool = False,
          fixture_run: list[str] | None = None, record=None) -> PlayerWriteup:
    """One player's write-up, composed from the corpus and nothing else."""
    quotes = quotes_for(name, club, items, full_name)
    writeup = PlayerWriteup(player=name, club=club, quotes=quotes,
                            evidence_count=len(items))
    writeup.evidence_used = list(dict.fromkeys(
        getattr(i, "article", i).url for i in items))[:12]
    writeup.sources_used = sorted({getattr(i, "article", i).source for i in items})

    if not items:
        writeup.status = (
            f"No article retrieved this cycle mentions {name}. That is a gap in the "
            f"reporting, not a finding about the player — the pipeline searched "
            f"{len(items)} matching items and every fallback avenue."
        )
        writeup.confidence = "none"
        return writeup

    if not quotes:
        writeup.status = (
            f"{len(items)} article(s) reference {name}, but none carries a sentence "
            f"specifically about him — they are club-level pieces where his name "
            f"appears in passing. Treat the assessment below as club context, not "
            f"as reporting on him."
        )
        writeup.confidence = "low"

    # Sections are filled in order of importance, and a quote spent on one
    # is not reused in another. Order matters because of that: the two
    # piles a manager weighs are the primary content, so they draw first.
    #
    # The dedup is suspended for players with very little written about
    # them. With one retrieved sentence, strict deduplication put it under
    # "current status" and left the case for and against empty, which
    # reads as no evidence when there is some.
    used: set[str] | None = set() if len(quotes) > 2 else None

    # --- the two piles -------------------------------------------------
    positives = _pick(quotes, tone="positive", used=used)
    negatives = _pick(quotes, tone="negative", used=used)
    writeup.case_for = _join(positives, "What supports keeping him:")
    writeup.case_against = _join(negatives, "What argues against him:")

    if positives and not negatives:
        writeup.case_against = (
            "Nothing retrieved this cycle argues against him. That is the absence of "
            "a negative report, which is weaker than a positive clearance — no source "
            "was found stating he is fit and starting, only that nobody said otherwise."
        )
    if negatives and not positives:
        writeup.case_for = (
            "Nothing retrieved this cycle makes a positive case for him. The evidence "
            "found is all cautionary."
        )

    # --- expected minutes ----------------------------------------------
    minutes_quotes = _pick(quotes, SECTION_TOPICS["minutes"], limit=2, used=used)
    if minutes_quotes:
        # Conflict is judged across every minutes-relevant quote, not only
        # the two shown: a fitness report and a doubt report contradicting
        # each other is the finding, and it must not depend on which two
        # the selection happened to surface.
        relevant = _pick(quotes, SECTION_TOPICS["minutes"], limit=99)
        conflicting = {q.tone for q in relevant} >= {"positive", "negative"}
        lead = ("Sources disagree on his minutes, which is itself the finding —"
                if conflicting else "On minutes —")
        writeup.expected_minutes = _join(minutes_quotes, lead)
        if conflicting:
            writeup.confidence = "medium"
    else:
        writeup.expected_minutes = (
            "No retrieved article addresses his selection or fitness. Minutes are "
            "unassessed rather than secure — the difference matters, and the old "
            "system used to report the second when it meant the first."
        )

    # --- current status ------------------------------------------------
    status_quotes = _pick(quotes, SECTION_TOPICS["status"], limit=2, used=used)
    if not status_quotes:
        status_quotes = _pick(quotes, limit=1, used=used)
    if status_quotes:
        writeup.status = _join(status_quotes, f"Latest on {name} —")
        writeup.confidence = "high" if status_quotes[0].when else "medium"

    # --- why he is here ------------------------------------------------
    role = "in the starting eleven" if starting else "on the bench"
    if captain:
        role = "captained"
    writeup.why_here = (
        f"{name} is {role} this week at £{price:.1f}m"
        + (f" as a {position}" if position else "")
        + f". The selection rests on {len(items)} retrieved item(s) from "
        + f"{len(writeup.sources_used)} source(s)"
        + (f", the most recent dated {quotes[0].when}." if quotes and quotes[0].when else ".")
    )

    # --- what changed ---------------------------------------------------
    recent = _pick([q for q in quotes if q.when], used=used)
    writeup.developments = _join(recent, "Recent developments —") if recent else (
        "Nothing dated was retrieved, so no change can be reported. Undated pages "
        "were found but cannot be placed in time."
    )

    # --- the next few gameweeks -----------------------------------------
    horizon = _pick(quotes, SECTION_TOPICS["outlook"], limit=2, used=used)
    run = ", ".join(fixture_run or [])
    parts = []
    if run:
        parts.append(f"The fixture run reads {run}.")
    if horizon:
        parts.append(_join(horizon, "On the coming weeks —"))
    if not parts:
        parts.append(
            "No retrieved item discusses his next few gameweeks, so the outlook below "
            "rests on the fixture list alone rather than on anyone's analysis."
        )
    writeup.outlook = " ".join(parts)

    return writeup


def build_all(squad: list[dict], evidence_by_player: dict, fixture_runs: dict | None = None,
              starting_ids: set | None = None, captain_id=None) -> dict[str, PlayerWriteup]:
    """Every owned player, written up from the corpus."""
    fixture_runs = fixture_runs or {}
    starting_ids = starting_ids or set()
    out: dict[str, PlayerWriteup] = {}
    for player in squad:
        name = str(player.get("name", ""))
        found = evidence_by_player.get(name)
        items = getattr(found, "substantive_items", None)
        if items is None:
            items = getattr(found, "items", []) or []
        out[name] = build(
            name, str(player.get("team", "")), items,
            full_name=str(player.get("full_name", "")),
            price=float(player.get("price", 0) or 0),
            position=str(player.get("position", "")),
            starting=player.get("id") in starting_ids or not player.get("on_bench"),
            captain=player.get("id") == captain_id or bool(player.get("is_captain")),
            fixture_run=fixture_runs.get(name),
        )
    return out


# --- transfers -----------------------------------------------------------

@dataclass
class TransferWriteup:
    """One suggested move, argued from what was actually published."""

    out_player: str
    in_player: str
    why_out: str = ""
    why_in: str = ""
    why_not_alternative: str = ""
    next_few_gameweeks: str = ""
    alternative: str = ""
    confidence: str = "low"
    evidence_used: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "out": self.out_player, "in": self.in_player,
            "why_out": self.why_out, "why_in": self.why_in,
            "why_not_alternative": self.why_not_alternative,
            "alternative": self.alternative,
            "next_few_gameweeks": self.next_few_gameweeks,
            "confidence": self.confidence, "evidence_used": self.evidence_used,
        }


def transfer(out_writeup: PlayerWriteup, in_writeup: PlayerWriteup,
             alternative: PlayerWriteup | None = None,
             out_run: list[str] | None = None,
             in_run: list[str] | None = None) -> TransferWriteup:
    """Argues a move from both players' evidence, not from a points delta.

    The rule the user set and this enforces: a transfer is never justified
    by one projection being slightly higher. The case has to be made out of
    what somebody reported — a fitness doubt, a role change, a fixture
    swing — and where the evidence does not support a case, this says so
    rather than dressing a rounding difference up as insight.
    """
    case = TransferWriteup(out_player=out_writeup.player, in_player=in_writeup.player)

    if out_writeup.case_against:
        case.why_out = out_writeup.case_against
    elif out_writeup.expected_minutes and "unassessed" in out_writeup.expected_minutes:
        case.why_out = (
            f"No published concern about {out_writeup.player} was retrieved. He is the "
            f"outgoing player because nothing was found to support him either — his "
            f"minutes are unassessed, which is a weaker position to hold than a "
            f"confirmed starter, not evidence of a problem."
        )
    else:
        case.why_out = (
            f"The evidence on {out_writeup.player} is neutral. This move is being made "
            f"on squad shape rather than on anything anyone published about him."
        )

    case.why_in = in_writeup.case_for or (
        f"No positive reporting on {in_writeup.player} was retrieved this cycle. "
        f"Recommending him on that basis would be guessing, and the confidence below "
        f"reflects it."
    )

    if alternative is not None:
        case.alternative = alternative.player
        if alternative.case_against:
            case.why_not_alternative = (
                f"The obvious alternative is {alternative.player}, and the retrieved "
                f"evidence argues against him: {alternative.case_against}"
            )
        elif not alternative.quotes:
            case.why_not_alternative = (
                f"{alternative.player} is the obvious alternative and nothing was "
                f"retrieved about him at all. Choosing a player nobody has written "
                f"about over one who has been covered is a worse bet on information, "
                f"not on ability."
            )
        else:
            case.why_not_alternative = (
                f"{alternative.player} has a comparable case "
                f"({len(alternative.quotes)} published mentions against "
                f"{len(in_writeup.quotes)}). This is close, and the pick is not "
                f"strongly evidenced either way."
            )
    else:
        case.why_not_alternative = (
            "No realistic alternative cleared the same evidence bar, so there is no "
            "second option to argue against."
        )

    runs = []
    if out_run:
        runs.append(f"{out_writeup.player} faces {', '.join(out_run)}")
    if in_run:
        runs.append(f"{in_writeup.player} faces {', '.join(in_run)}")
    horizon = _pick(in_writeup.quotes, SECTION_TOPICS["outlook"], limit=1)
    case.next_few_gameweeks = " ".join(
        ([" against ".join(runs) + "."] if len(runs) == 2 else [r + "." for r in runs])
        + ([_join(horizon, "On the run ahead —")] if horizon else [])
    ) or "No fixture or forward-looking evidence was retrieved for either player."

    strong = bool(out_writeup.case_against) and bool(in_writeup.case_for)
    case.confidence = "high" if strong else ("medium" if in_writeup.case_for else "low")
    case.evidence_used = (out_writeup.evidence_used[:5] + in_writeup.evidence_used[:5])
    return case


# --- prose from structured facts -----------------------------------------
#
# The rewrite. Everything above assembles quotes; what follows writes from
# a decided assessment instead, which is the only way to stop a sentence
# about one player reaching another player's card.

def from_facts(facts) -> str:
    """A compact write-up: what to do with him, and why. Up to 120 words.

    Seven headings repeating the same information is not thoroughness, it
    is padding — and padding is what forced the same sentence to appear
    under four headings. One paragraph, then the two lines a manager
    actually scans for.
    """
    from fpl_assistant.analysis import player_facts as pf

    sentences = []

    # What he is and what the plan is.
    role = {
        pf.CAPTAIN: "is the captain pick this week",
        pf.VICE: "takes the armband if the captain does not play",
        pf.START: "starts",
        pf.BENCH: "is on the bench",
        pf.MONITOR: "needs watching before the deadline",
        pf.SELL_VERDICT: "is the one to move on",
        pf.KEEP: "is a straightforward hold",
    }.get(facts.verdict, "is in the squad")
    sentences.append(f"{facts.player} {role}.")

    # Minutes, in plain words, and only what is actually known.
    if facts.expected_minutes in ("Very secure", "Secure"):
        sentences.append(
            f"His place looks {facts.expected_minutes.lower()} on the selection record.")
    elif facts.expected_minutes in ("Significant concern", "Major doubt"):
        sentences.append(f"Expected minutes are a {facts.expected_minutes.lower()}.")
    elif facts.expected_minutes == "Slight concern":
        sentences.append("There is a slight question over his minutes.")
    else:
        sentences.append("Nothing published this week settles his minutes either way.")

    if facts.availability == pf.OUT:
        sentences.append("He is unavailable.")
    elif facts.availability == pf.DOUBT:
        sentences.append("His availability is in doubt.")

    if facts.role:
        sentences.append(_trim(facts.role))
    if facts.set_pieces:
        sentences.append(_trim(facts.set_pieces))

    # The fixture, which is the other half of every FPL decision.
    if facts.fixture:
        sentences.append(f"This week: {facts.fixture}.")

    # What the analysts said — about HIM, not about his club.
    view = {
        pf.BUY: "Analysts are recommending him.",
        pf.SELL: "Analysts are recommending a sale.",
        pf.HOLD: "The published advice is to hold.",
        pf.MIXED: "The published advice is split.",
    }.get(facts.expert_view)
    if view:
        sentences.append(view)
    elif not facts.claims:
        sentences.append("No article retrieved this week discusses him directly.")

    text = " ".join(sentences)
    return _cap_words(text, 120)


def _trim(text: str, limit: int = 150) -> str:
    text = text.strip().rstrip(".")
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text + "."


def _cap_words(text: str, limit: int) -> str:
    words = text.split()
    if len(words) <= limit:
        return text
    return " ".join(words[:limit]).rstrip(",;") + "…"


def quality_check(facts) -> list[str]:
    """The per-card checklist, run before anything is displayed.

    Returns the problems found. A card with problems is not shown as a
    confident assessment — the point is that a contradiction between the
    label and the prose can never reach the page again.
    """
    from fpl_assistant.analysis import player_facts as pf

    problems = []
    for claim in facts.claims:
        if not claim.player_named and not (set(claim.buckets) & pf.CLUB_LEVEL_BUCKETS):
            problems.append(f"a claim not about {facts.player} reached his card")
    if facts.verdict == pf.SELL_VERDICT and not facts.supports_sale():
        problems.append("marked for sale with no evidence that supports selling him")
    if facts.expected_minutes in ("Very secure", "Secure") and facts.availability == pf.OUT:
        problems.append("minutes described as secure for an unavailable player")
    if facts.confidence == pf.HIGH and not [c for c in facts.claims if c.player_named]:
        problems.append("high confidence with no player-specific evidence")
    seen = set()
    for claim in facts.claims:
        key = claim.text[:60]
        if key in seen:
            problems.append("the same sentence appears twice")
            break
        seen.add(key)
    return problems
