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

CLUB_NAMES = {
    "ARS": ["arsenal", "gunners"],
    "AVL": ["aston villa", "villa"],
    "BOU": ["bournemouth", "cherries"],
    "BHA": ["brighton", "seagulls", "albion"],
    "BRE": ["brentford", "bees"],
    "CHE": ["chelsea", "blues"],
    "COV": ["coventry", "sky blues"],
    "CRY": ["crystal palace", "palace", "eagles"],
    "EVE": ["everton", "toffees"],
    "FUL": ["fulham", "cottagers"],
    "HUL": ["hull city", "hull", "tigers"],
    "IPS": ["ipswich", "tractor boys"],
    "LEE": ["leeds"],
    "LIV": ["liverpool", "reds", "anfield"],
    "MCI": ["manchester city", "man city", "city", "etihad"],
    "MUN": ["manchester united", "man united", "man utd", "united", "old trafford"],
    "NEW": ["newcastle", "magpies", "st james"],
    "NFO": ["nottingham forest", "forest", "city ground"],
    "SUN": ["sunderland", "black cats"],
    "TOT": ["tottenham", "spurs"],
}

# Words that make an article about team selection rather than about
# anything else. Used to rank, never to exclude.
TEAM_NEWS_TERMS = (
    "team news", "predicted", "line-up", "lineup", "starting xi", "press conference",
    "injury", "injuries", "doubt", "fitness", "suspended", "suspension", "ruled out",
    "returns", "available", "squad", "selection", "rotation", "benched", "starts",
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


def article_text(article: Article) -> str:
    return normalise(f"{article.title} {article.excerpt} {article.url}")


def mentions_club(article: Article, club: str) -> bool:
    text = article_text(article)
    return any(_mentions(text, alias) for alias in CLUB_NAMES.get(club.upper(), []))


@dataclass
class Evidence:
    """One article, and why it counts as evidence about this player."""

    article: Article
    matched_on: str
    kind: str = "general"

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
    def researched(self) -> bool:
        return len(self.items) >= MIN_EVIDENCE_ITEMS

    @property
    def team_news(self) -> list[Evidence]:
        return [e for e in self.items if e.kind == "team news"]

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
        if not self.items:
            return "searched, nothing found"
        if not self.researched:
            return f"searched, {len(self.items)} item(s) — below the {MIN_EVIDENCE_ITEMS} needed"
        return f"researched — {len(self.items)} items"

    def as_dict(self) -> dict:
        return {
            "player": self.player, "club": self.club,
            "researched": self.researched, "status": self.status,
            "queries": self.queries, "corpus_size": self.corpus_size,
            "fallbacks_used": self.fallbacks_used,
            "items": [e.as_dict() for e in self.items],
        }


def classify(article: Article) -> str:
    text = article_text(article)
    if any(_mentions(text, term) for term in TEAM_NEWS_TERMS):
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

    if len(result.items) < min_items and club:
        # Fallback: the player was not named, but his club's team news is
        # still evidence about whether he plays. Ranked below a name match
        # and labelled as club-level so a write-up can say so.
        for article in articles:
            if article.url in seen or not mentions_club(article, club):
                continue
            if classify(article) != "team news":
                continue
            seen.add(article.url)
            result.items.append(Evidence(article, f"{club} team news", "club team news"))
            if "club team news" not in result.fallbacks_used:
                result.fallbacks_used.append("club team news")
            if len(result.items) >= min_items * 2:
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
