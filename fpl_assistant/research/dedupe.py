"""Stage 3: eight copies of one story are one piece of evidence.

Football reporting is overwhelmingly syndicated. One outlet gets a quote
from a press conference and thirty sites rewrite it within the hour. A
research engine that counts those separately will report a player as
heavily evidenced when a single source said one thing — and worse, it will
present the repetition as corroboration, which is the opposite of what it
is. Thirty rewrites of one claim are not thirty sources agreeing.

Matching is on title shingles rather than full text, for two reasons: the
title is the part every syndication keeps recognisable, and it is present
even for items that were never deep-read. Titles are normalised hard
(accents, punctuation, and the outlet suffixes sites append) before
comparison.

The primary of each group is the earliest-published item from the
highest-tier source, so a syndicated rewrite never outranks the outlet
that actually did the work.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Jaccard overlap of title word-trigrams above which two items are the
# same story. Tuned to catch rewrites ("Man City eye Enzo move" /
# "Manchester City eyeing move for Enzo") without merging two genuinely
# different stories about the same player.
SIMILARITY_THRESHOLD = 0.6
SHINGLE_SIZE = 3

# Words that carry no distinguishing information in a football headline
# and inflate similarity between unrelated stories.
STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "as", "at", "is",
    "was", "with", "his", "her", "their", "it", "be", "by", "from", "after",
    "over", "into", "that", "this", "but", "have", "has", "will", "he", "she",
}

# Outlets append their own name to titles in feeds; it is not part of the story.
SUFFIX = re.compile(
    r"\s*[|\-–—:]\s*(football365|sky sports|goal com|fourfourtwo|sports mole|"
    r"the analyst|opta analyst|fantasy football scout|si com|nbc sports|"
    r"cbs sports|espn|premier league)\s*$",
    re.IGNORECASE,
)


def normalise_title(title: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(title))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = SUFFIX.sub("", stripped.lower())
    words = [w for w in re.sub(r"[^a-z0-9 ]", " ", cleaned).split() if w not in STOPWORDS]
    return " ".join(words)


def shingles(title: str, size: int = SHINGLE_SIZE) -> frozenset[str]:
    words = normalise_title(title).split()
    if len(words) < size:
        # Short headlines have no trigrams; compare them as a whole so they
        # are not silently unmatchable.
        return frozenset([" ".join(words)]) if words else frozenset()
    return frozenset(" ".join(words[i:i + size]) for i in range(len(words) - size + 1))


def words(title: str) -> frozenset[str]:
    return frozenset(normalise_title(title).split())


def similarity(left: str, right: str) -> float:
    """How likely two headlines are the same story.

    The better of two measures, because syndication does both things.
    Trigrams catch a light rewrite that keeps the phrasing. But a rewrite
    that REORDERS — "Haaland fit to face Coventry, says Guardiola" against
    "Guardiola says Haaland is fit to face Coventry" — destroys every
    trigram while being unmistakably the same story, and scores 0.33.
    Order-insensitive word overlap catches that one and scores it 1.0.

    Taking the maximum is safe because the failure mode of word overlap —
    merging unrelated stories that share vocabulary — needs most of the
    words to match after stopword removal, and two different stories about
    the same player do not clear 0.6 ("Haaland scores twice against
    Bournemouth" against "Haaland ruled out with a knee injury" is 0.09).
    """
    word_overlap = 0.0
    a_words, b_words = words(left), words(right)
    if a_words and b_words:
        word_overlap = len(a_words & b_words) / len(a_words | b_words)

    trigram_overlap = 0.0
    a, b = shingles(left), shingles(right)
    if a and b:
        trigram_overlap = len(a & b) / len(a | b)

    return max(word_overlap, trigram_overlap)


@dataclass
class Group:
    """One story, and every copy of it that was retrieved."""

    key: str
    primary: object
    duplicates: list = field(default_factory=list)

    @property
    def size(self) -> int:
        return 1 + len(self.duplicates)


def _rank(article, tier_of) -> tuple:
    """Lower sorts first: better tier, then earlier publication."""
    return (tier_of(article), article.published or "9999")


def group(articles: list, tier_of=None) -> list[Group]:
    """Clusters near-identical stories, choosing a primary for each.

    Deliberately O(n * groups) rather than O(n^2): each article is compared
    against the primary of each existing group, not against every other
    article. On a corpus of a few thousand that is the difference between
    a second and a minute, and the accuracy cost is negligible because
    syndicated copies resemble the original at least as much as each other.
    """
    tier_of = tier_of or (lambda a: 5)
    groups: list[Group] = []
    # Seed with the best-ranked items so primaries are chosen well from the
    # start rather than swapped afterwards.
    for article in sorted(articles, key=lambda a: _rank(a, tier_of)):
        title = getattr(article, "title", "") or ""
        placed = False
        for existing in groups:
            if similarity(title, existing.primary.title) >= SIMILARITY_THRESHOLD:
                existing.duplicates.append(article)
                placed = True
                break
        if not placed:
            groups.append(Group(key=normalise_title(title) or article.url, primary=article))
    return groups


def apply(articles: list, tier_of=None) -> tuple[list, int]:
    """Returns (one article per story, number of duplicates removed).

    Each surviving article is stamped with its `duplicate_group` and how
    many copies were folded into it, so a write-up can say "reported by
    six outlets" without treating that as six independent claims.
    """
    groups = group(articles, tier_of)
    kept = []
    removed = 0
    for index, cluster in enumerate(groups):
        primary = cluster.primary
        primary.duplicate_group = f"g{index:05d}"
        primary.duplicate_count = cluster.size
        primary.duplicate_urls = [d.url for d in cluster.duplicates][:8]
        kept.append(primary)
        removed += len(cluster.duplicates)
    return kept, removed
