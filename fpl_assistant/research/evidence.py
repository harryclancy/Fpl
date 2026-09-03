"""Turning a pile of retrieved articles into evidence about one player.

The failure this closes: the app reported "no starting call, recent
appearance, injury or transfer information found" for Haaland, Szoboszlai
and Semenyo simultaneously. That is not a plausible state of the world, it
is a pipeline that never looked. Looking is what this module does.

Two rules shape it.

**Matching must be conservative.** A false positive here is worse than a
miss, because a wrongly attributed article becomes a "fact" in a player's
write-up. So matching is on the surname as a whole word in normalised
text, plus a club check where the surname is common enough to collide.

**A miss must be reported as a miss.** `for_player` returning an empty
list is a legitimate answer and the caller must be able to tell it apart
from "we never ran". That is why `search` returns a result object with the
queries it actually tried rather than a bare list.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from fpl_assistant.research.collect import Article

# Below this, a player is not researched — the number the user asked for.
MIN_EVIDENCE_ITEMS = 3

# Recency windows, in hours, by the kind of question being asked.
TEAM_NEWS_HOURS = 72
TRANSFER_HOURS = 24 * 14
SEASON_HOURS = 24 * 60

# Surnames short or common enough that a bare word match will collide with
# ordinary prose or with a different player. These require a club match too.
AMBIGUOUS_SURNAMES = {
    "wright", "james", "mount", "hall", "hughes", "mitchell", "richards",
    "walker", "smith", "jones", "young", "white", "wood", "king", "reed",
    "diop", "sanchez", "santos", "silva", "gomes", "gomez", "pedro", "neto",
}

# Aliases must be DISTINCTIVE. The first live run credited Semenyo with
# "Manchester City team news" that turned out to be a Coventry City mascot
# package and a Sunderland ticket bulletin, because "city" was listed as an
# alias for MCI and matches Coventry City, Hull City and the word itself.
# The same trap sits in "united" (Newcastle, Leeds, West Ham), "albion"
# (West Brom) and "blues" (Everton, Birmingham, Chelsea, Coventry's Sky
# Blues). None of those may appear here on their own.
CLUB_NAMES = {
    "ARS": ["arsenal", "gunners", "emirates stadium"],
    "AVL": ["aston villa", "villa park"],
    "BOU": ["bournemouth", "vitality stadium"],
    "BHA": ["brighton", "seagulls", "amex"],
    "BRE": ["brentford", "gtech"],
    "CHE": ["chelsea", "stamford bridge"],
    "COV": ["coventry", "sky blues"],
    "CRY": ["crystal palace", "selhurst"],
    "EVE": ["everton", "toffees", "goodison"],
    "FUL": ["fulham", "craven cottage"],
    "HUL": ["hull city", "tigers"],
    "IPS": ["ipswich", "portman road"],
    "LEE": ["leeds united", "elland road"],
    "LIV": ["liverpool", "anfield"],
    "MCI": ["manchester city", "man city", "etihad"],
    "MUN": ["manchester united", "man united", "man utd", "old trafford"],
    "NEW": ["newcastle united", "newcastle", "magpies"],
    "NFO": ["nottingham forest", "city ground"],
    "SUN": ["sunderland", "black cats"],
    "TOT": ["tottenham", "spurs"],
}

# Club sites publish far more admin than football. A ticket bulletin is not
# team news, however many times it says "available".
CLUB_ADMIN_TERMS = (
    "ticket", "mascot", "hospitality", "membership", "season card", "shop",
    "kit launch", "merchandise", "podcast", "quiz", "competition winner",
    "foundation", "charity", "matchday programme", "away travel", "sales",
)

# Words that make an article about team selection rather than about
# anything else. Used to rank, never to exclude.
# Deliberately phrases, not single words. "available", "returns" and
# "squad" on their own matched ticket sales and academy news.
TEAM_NEWS_TERMS = (
    "team news", "predicted line", "predicted xi", "line up", "lineup", "line-up",
    "starting xi", "press conference", "injury", "injuries", "injured", "fitness",
    "ruled out", "sidelined", "suspended", "suspension", "doubt", "returns to training",
    "back in training", "expected to start", "set to start", "selection", "rotation",
    "will miss", "misses out", "out for", "recovery", "comeback", "match report",
    "starts", "benched", "substitute",
)
TRANSFER_TERMS = ("transfer", "bid", "deal", "sign", "move", "medical", "loan", "fee")


def normalise(text: str) -> str:
    """Accent-stripped, lowercase, punctuation-free — so Guéhi matches Guehi."""
    decomposed = unicodedata.normalize("NFKD", str(text))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]", " ", stripped.lower())


def name_variants(name: str, full_name: str = "") -> list[str]:
    """Every string worth searching for, longest first.

    FPL's `web_name` is sometimes the surname ("Haaland"), sometimes an
    initial and surname ("B.Fernandes"), sometimes a nickname ("João
    Pedro"). Searching only one of those is how a player ends up looking
    unresearched when three articles mention him.
    """
    seen: list[str] = []
    for candidate in (full_name, name):
        cleaned = normalise(candidate).strip()
        if not cleaned:
            continue
        if cleaned not in seen:
            seen.append(cleaned)
        parts = [p for p in cleaned.split() if len(p) > 2]
        # The surname alone is the highest-recall term and usually what a
        # headline uses.
        if parts and parts[-1] not in seen:
            seen.append(parts[-1])
        if len(parts) > 1 and parts[0] not in seen and len(parts[0]) > 3:
            seen.append(parts[0])
    return sorted(seen, key=len, reverse=True)


def _mentions(haystack: str, term: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", haystack) is not None


def mentions_this_player(text: str, term: str, own: set,
                        full_name_known: bool | None = None) -> bool:
    """Is this a mention of HIM, or of somebody who shares the name?

    FPL's web_name is often a bare surname or a bare forename, and a
    football corpus is full of other people who have it. Searching for
    "Gabriel" finds Gabriel Jesus and Gabriel Martinelli; searching for
    "Mendy" finds every Mendy in the pyramid. Counting those is how an
    article about a striker joining Barcelona became a reason to sell a
    centre-half.

    The test is capitalisation, read on the ORIGINAL text rather than the
    normalised one: a name butted against another capitalised word that
    is not part of this player's own name is somebody else's full name.
    "Gabriel Jesus" clashes, "Gabriel Magalhaes" does not, and "Gabriel
    headed the opener" does not, because "headed" is not a name.

    The word BEFORE the match is only consulted when the player's real
    full name is known. Without it, "David Raya" and "Nobel Mendy" are
    indistinguishable -- both are a capitalised word in front of a
    surname -- and rejecting the first to catch the second would lose far
    more evidence than it saves. Given the full name, "David" is his and
    "Nobel" is not, and both cases are decided correctly.
    """
    if full_name_known is None:
        full_name_known = len(own) > 1
    pattern = rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        before = text[:match.start()]
        after = text[match.end():]
        previous = before.split()[-1] if before.split() else ""
        following = after.split()[0] if after.split() else ""
        # A word that opens a sentence is capitalised by grammar, not by
        # being a name, so it cannot testify either way.
        sentence_start = bool(re.search(r"[.!?\u2022|]\s*$", before.rstrip()
                                        [:len(before.rstrip()) - len(previous)]
                                        + " ")) or not before.strip()
        neighbours = []
        if full_name_known and not sentence_start:
            neighbours.append(previous)
        neighbours.append(following)
        if not any(_name_like(word, own) for word in neighbours):
            return True
    return False


# Capitalised words that are not part of anybody's name. Kept short and
# general: days, months, competitions and the handful of words that open
# a clause. Nothing club- or player-specific belongs here.
_CAPITALISED_NOT_NAMES = frozenset("""
monday tuesday wednesday thursday friday saturday sunday january february
march april may june july august september october november december
premier league cup fa efl uefa champions europa conference world euro
gameweek fpl fantasy football club united city town rovers wanderers albion
the a an and but or if when while after before however meanwhile although
""".split())


def _name_like(word: str, own: set) -> bool:
    """Does this neighbouring word read as part of somebody else's name?"""
    stripped = word.strip(".,;:!?()[]{}\"'\u2019\u201c\u201d")
    if len(stripped) < 3 or not stripped[0].isupper() or not stripped.isalpha():
        return False
    lowered = normalise(stripped)
    return lowered not in _CAPITALISED_NOT_NAMES and lowered not in own


def own_tokens(name: str, full_name: str = "") -> set:
    """Every word that belongs to this player's own name."""
    tokens = set()
    for candidate in (name, full_name):
        for part in normalise(candidate).split():
            if part:
                tokens.add(part)
    return tokens


def article_text(article: Article) -> str:
    return normalise(f"{article.title} {article.excerpt} {article.url}")


def mentions_club(article: Article, club: str) -> bool:
    text = article_text(article)
    return any(_mentions(text, alias) for alias in CLUB_NAMES.get(club.upper(), []))


def mentions_club_in_title(article: Article, club: str) -> bool:
    """A stricter test: is the article ABOUT this club?

    Club websites list their fixtures on every page, so "Liverpool" appears
    in the body of an Aston Villa match report. Requiring the name in the
    headline is a crude proxy for aboutness, and a great deal better than
    the alternative, which was crediting a player with his rivals' news.
    """
    title = normalise(article.title)
    return any(_mentions(title, alias) for alias in CLUB_NAMES.get(club.upper(), []))


@dataclass
class Evidence:
    """One article, and why it counts as evidence about this player."""

    article: Article
    matched_on: str
    kind: str = "general"

    @property
    def substantive(self) -> bool:
        """Is this something someone wrote, or a page a program generated?

        Only substantive items count toward the evidence threshold. The
        first live run "researched" Semenyo with three hits, all of which
        were tool pages titled "1", "2" and "Antoine semenyo". Counting
        those is how a pipeline reports 15/15 while knowing nothing.
        """
        return self.article.is_article

    @property
    def recency_hours(self) -> float | None:
        return self.article.age_hours()

    def as_dict(self) -> dict:
        return {
            "title": self.article.title, "url": self.article.url,
            "source": self.article.source, "published": self.article.published,
            "matched_on": self.matched_on, "kind": self.kind,
            "excerpt": self.article.excerpt[:400],
        }


@dataclass
class PlayerEvidence:
    """The full result of searching for one player — hits and misses alike."""

    player: str
    club: str
    items: list[Evidence] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    corpus_size: int = 0
    fallbacks_used: list[str] = field(default_factory=list)

    @property
    def substantive_items(self) -> list["Evidence"]:
        """The items that are actually writing. The only ones that count."""
        return [e for e in self.items if e.substantive]

    @property
    def researched(self) -> bool:
        return len(self.substantive_items) >= MIN_EVIDENCE_ITEMS

    @property
    def team_news(self) -> list[Evidence]:
        return [e for e in self.substantive_items if e.kind == "team news"]

    @property
    def recent_team_news(self) -> list[Evidence]:
        return [e for e in self.team_news
                if (h := e.recency_hours) is not None and h <= TEAM_NEWS_HOURS]

    @property
    def transfer_items(self) -> list[Evidence]:
        return [e for e in self.items if e.kind == "transfer"]

    @property
    def status(self) -> str:
        if self.corpus_size == 0:
            return "RESEARCH COLLECTION FAILURE — nothing was retrieved to search"
        real = len(self.substantive_items)
        if not self.items:
            return "searched, nothing found"
        if not real:
            return (f"searched, {len(self.items)} match(es) — all tool or profile pages, "
                    f"no article written about him")
        if not self.researched:
            return f"searched, {real} article(s) — below the {MIN_EVIDENCE_ITEMS} needed"
        return f"researched — {real} articles"

    def as_dict(self) -> dict:
        return {
            "player": self.player, "club": self.club,
            "researched": self.researched, "status": self.status,
            "queries": self.queries, "corpus_size": self.corpus_size,
            "fallbacks_used": self.fallbacks_used,
            "substantive": len(self.substantive_items),
            "matches": len(self.items),
            "items": [e.as_dict() for e in self.substantive_items],
            "discarded_pages": [e.article.url for e in self.items if not e.substantive],
        }


def is_club_admin(article: Article) -> bool:
    """Ticket sales, mascots, shop news — published by clubs, not football."""
    text = article_text(article)
    return any(term in text for term in CLUB_ADMIN_TERMS)


def classify(article: Article) -> str:
    text = article_text(article)
    if is_club_admin(article):
        return "general"
    if any(term in text for term in TEAM_NEWS_TERMS):
        return "team news"
    if any(_mentions(text, term) for term in TRANSFER_TERMS):
        return "transfer"
    return "general"


def search(name: str, club: str, articles: list[Article], full_name: str = "",
           min_items: int = MIN_EVIDENCE_ITEMS) -> PlayerEvidence:
    """Finds every article that is evidence about this player.

    Runs the fallback ladder the user specified: direct name match first,
    then club team-news material, so a player nobody wrote about by name
    still gets his club's press-conference and line-up coverage rather
    than an empty profile.
    """
    variants = name_variants(name, full_name)
    result = PlayerEvidence(player=name, club=club, queries=list(variants),
                            corpus_size=len(articles))
    if not articles:
        return result

    seen: set[str] = set()
    for article in articles:
        text = article_text(article)
        for variant in variants:
            if not _mentions(text, variant):
                continue
            # A short or common surname on its own is not enough — it has
            # to be his club's article too, or "Wright" matches every
            # Haji Wright, Ian Wright and "wright" in the corpus.
            if (" " not in variant and variant in AMBIGUOUS_SURNAMES
                    and not mentions_club(article, club)):
                continue
            if article.url not in seen:
                seen.add(article.url)
                result.items.append(Evidence(article, variant, classify(article)))
            break

    if len(result.substantive_items) < min_items and club:
        # Fallback: the player was not named, but his club's team news is
        # still evidence about whether he plays. Ranked below a name match
        # and labelled as club-level so a write-up can say so.
        for article in articles:
            if article.url in seen or not article.is_article:
                continue
            # In the TITLE, not merely somewhere in the page. A club site's
            # fixture list mentions half the league; that is not the article
            # being about them. This is what let a Villa match report count
            # as Liverpool team news.
            if not mentions_club_in_title(article, club):
                continue
            if classify(article) != "team news":
                continue
            seen.add(article.url)
            result.items.append(Evidence(article, f"{club} team news", "club team news"))
            if "club team news" not in result.fallbacks_used:
                result.fallbacks_used.append("club team news")
            if len(result.substantive_items) >= min_items * 2:
                break

    result.items.sort(
        key=lambda e: (
            {"team news": 0, "transfer": 1, "club team news": 2, "general": 3}.get(e.kind, 4),
            -(1 / ((e.recency_hours or 10_000) + 1)),
        )
    )
    return result


def tag_articles(articles: list[Article], squad: list[dict]) -> list[Article]:
    """Writes players-mentioned and club onto each article, in place.

    Stored on the article so the corpus is searchable without re-running
    the matcher, and so a human reading the JSON can see what the machine
    thought each piece was about.
    """
    for article in articles:
        text = article_text(article)
        found = []
        for player in squad:
            club = str(player.get("team", ""))
            for variant in name_variants(str(player.get("name", "")),
                                         str(player.get("full_name", ""))):
                if not _mentions(text, variant):
                    continue
                if (" " not in variant and variant in AMBIGUOUS_SURNAMES
                        and not mentions_club(article, club)):
                    continue
                found.append(str(player.get("name", "")))
                break
        article.players = sorted(set(found))
        if not article.club:
            for code in CLUB_NAMES:
                if mentions_club(article, code):
                    article.club = code
                    break
        if not article.source_type:
            article.source_type = classify(article)
    return articles
