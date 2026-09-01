"""Stage 4: deciding what is worth reading properly.

Discovery is cheap and reading is expensive, so the value of the whole
system is in this ordering. A thousand candidates cost one HTTP request
per source; deep-reading them all would be a thousand requests, several
minutes, and rude. Two hundred well-chosen ones answer the same questions.

The score is a plain weighted sum, written out rather than tuned, because
the point is that it can be argued with. Each component below corresponds
to a question a manager actually asks, and the weights say which of those
questions matter most before a deadline: what happened, and who said so.

Nothing here is machine learning and nothing here needs to be. The ranking
only has to be better than "whatever the feed listed first", which it
comfortably is.
"""
from __future__ import annotations

from dataclasses import dataclass

from fpl_assistant.research.evidence import (
    CLUB_NAMES, article_text, is_club_admin, mentions_club_in_title,
    name_variants, normalise, _mentions,
)

# Weights. Recency and player relevance dominate: a superb tactical piece
# about last season is worth less before a deadline than a two-line injury
# update from this morning.
W_RECENCY = 30.0
W_PLAYER = 25.0
W_CLUB = 10.0
W_GAMEWEEK = 12.0
W_SOURCE_TIER = 10.0
W_PRIMARY = 12.0
W_SPECIFICITY = 8.0
W_FPL_USE = 10.0
W_HORIZON = 5.0

# Hours after which recency stops counting for anything. Three weeks: past
# that a piece is background, not news.
RECENCY_HORIZON_HOURS = 24 * 21
# Inside this window an item is treated as fully current.
FRESH_HOURS = 72.0

# The source types that constitute a primary source: the club itself, or
# the player, or a direct report of a manager speaking.
PRIMARY_DOMAINS = (
    "arsenal.com", "avfc.co.uk", "afcb.co.uk", "brentfordfc.com",
    "brightonandhovealbion.com", "chelseafc.com", "ccfc.co.uk", "cpfc.co.uk",
    "evertonfc.com", "fulhamfc.com", "wearehullcity.co.uk", "itfc.co.uk",
    "leedsunited.com", "liverpoolfc.com", "mancity.com", "manutd.com",
    "newcastleunited.com", "nottinghamforest.co.uk", "safc.com",
    "tottenhamhotspur.com", "premierleague.com",
)
PRIMARY_MARKERS = ("press conference", "told reporters", "said:", "speaking to",
                   "exclusive", "confirmed", "official", "statement")

# Terms that make a piece FPL-useful rather than merely football-adjacent.
FPL_MARKERS = ("fpl", "fantasy premier league", "captain", "differential",
               "wildcard", "triple captain", "bench boost", "free hit",
               "ownership", "price change", "scout picks", "transfer tips",
               "defcon", "defensive contribution", "expected minutes")

HORIZON_MARKERS = ("next three", "next five", "next 3", "next 5", "fixture run",
                   "run of games", "coming weeks", "upcoming fixtures", "schedule")


@dataclass
class Score:
    """A ranked candidate, with the reasoning kept so it can be inspected."""

    total: float
    parts: dict

    def __float__(self) -> float:
        return self.total


def _recency(article) -> float:
    age = article.age_hours()
    if age is None:
        # Undated is not the same as old. Most club sitemaps carry no date;
        # scoring them zero would silently exclude official sources, which
        # are the ones we most want. Treated as middling instead.
        return 0.45
    if age <= FRESH_HOURS:
        return 1.0
    if age >= RECENCY_HORIZON_HOURS:
        return 0.0
    return 1.0 - ((age - FRESH_HOURS) / (RECENCY_HORIZON_HOURS - FRESH_HOURS))


def _player_relevance(text, title, squad) -> float:
    """Highest when an owned player is in the headline."""
    best = 0.0
    for player in squad:
        club = str(player.get("team", ""))
        for variant in name_variants(str(player.get("name", "")),
                                     str(player.get("full_name", ""))):
            if _mentions(title, variant):
                return 1.0
            if _mentions(text, variant):
                best = max(best, 0.6)
    return best


def _club_relevance(article, squad) -> float:
    clubs = {str(p.get("team", "")) for p in squad}
    if any(mentions_club_in_title(article, club) for club in clubs):
        return 1.0
    text = article_text(article)
    for club in clubs:
        if any(_mentions(text, alias) for alias in CLUB_NAMES.get(club, [])):
            return 0.5
    return 0.0


def _gameweek_relevance(text, gameweek: int) -> float:
    """Current gameweek named beats a previous one named beats neither."""
    for phrase in (f"gameweek {gameweek}", f"gw{gameweek}", f"gw {gameweek}"):
        if phrase in text:
            return 1.0
    for previous in range(max(1, gameweek - 2), gameweek):
        for phrase in (f"gameweek {previous}", f"gw{previous}"):
            if phrase in text:
                # Explicitly about an earlier gameweek: actively less useful
                # than something undated, because it will read as current.
                return 0.1
    return 0.5


def _source_quality(article, tier: int) -> float:
    return {1: 1.0, 2: 0.95, 3: 0.8, 4: 0.6}.get(tier, 0.5)


def _primary(article, text) -> float:
    if article.domain in PRIMARY_DOMAINS:
        return 1.0
    hits = sum(1 for marker in PRIMARY_MARKERS if marker in text)
    return min(0.8, hits * 0.3)


def _specificity(article) -> float:
    """Length of retrieved prose, as a proxy for saying something.

    A 90-character teaser and a 4,000-character match report both "mention"
    a player; only one of them tells you anything.
    """
    body = getattr(article, "body", "") or article.excerpt
    if not body:
        return 0.15
    return min(1.0, len(body) / 2500.0)


def _fpl_usefulness(text) -> float:
    hits = sum(1 for marker in FPL_MARKERS if marker in text)
    return min(1.0, hits / 3.0)


def _horizon(text) -> float:
    return 1.0 if any(marker in text for marker in HORIZON_MARKERS) else 0.0


def score(article, squad: list[dict], gameweek: int, tier: int = 3) -> Score:
    """One candidate's relevance, and why."""
    text = article_text(article)
    body = (getattr(article, "body", "") or "").lower()
    if body:
        text = f"{text} {body}"
    title = normalise(article.title)

    parts = {
        "recency": _recency(article) * W_RECENCY,
        "player": _player_relevance(text, title, squad) * W_PLAYER,
        "club": _club_relevance(article, squad) * W_CLUB,
        "gameweek": _gameweek_relevance(text, gameweek) * W_GAMEWEEK,
        "source": _source_quality(article, tier) * W_SOURCE_TIER,
        "primary": _primary(article, text) * W_PRIMARY,
        "specificity": _specificity(article) * W_SPECIFICITY,
        "fpl": _fpl_usefulness(text) * W_FPL_USE,
        "horizon": _horizon(text) * W_HORIZON,
    }
    total = sum(parts.values())

    # Club administration is football-adjacent and never useful. Scored to
    # the floor rather than filtered out here, so the filter stage stays
    # the single place that decides what is junk.
    if is_club_admin(article):
        total *= 0.1
        parts["club_admin_penalty"] = True

    return Score(total=round(total, 2), parts={k: round(v, 2) if isinstance(v, float) else v
                                               for k, v in parts.items()})


def rank(articles: list, squad: list[dict], gameweek: int,
         tier_lookup=None) -> list:
    """Sorts candidates best-first, stamping each with its score."""
    tier_lookup = tier_lookup or (lambda a: 3)
    for article in articles:
        result = score(article, squad, gameweek, tier_lookup(article))
        article.relevance_score = result.total
        article.score_parts = result.parts
    return sorted(articles, key=lambda a: a.relevance_score, reverse=True)
