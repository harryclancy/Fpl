"""The research cache: what we retrieved, kept so we can reason over it.

Without this, every question about a player would mean re-fetching every
feed — slow, rude to the publishers, and impossible to audit afterwards.
With it, "what does the app actually know about Szoboszlai right now?" is
a question with a checkable answer, which is the thing that was missing.

Stored as JSON in the repository rather than in a database. Three reasons:
it costs nothing, it survives the app host restarting (Streamlit's disk is
ephemeral and a runtime-only cache is usually gone before anyone looks at
it), and it shows up in a diff, so a bad collection run is visible in the
commit rather than mysterious in production.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fpl_assistant.research.collect import Article

CORPUS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "research"
CORPUS_PATH = CORPUS_DIR / "corpus.json"

# Items older than this are dropped on write. Team news does not survive a
# deadline, and an unbounded cache would grow until the diffs are useless.
RETENTION_DAYS = 28


@dataclass
class Corpus:
    """Everything the research engine has retrieved and can reason over."""

    items: list[Article] = field(default_factory=list)
    collected_at: str = ""
    sources_checked: int = 0
    sources_ok: int = 0
    failures: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.items)

    @property
    def collected_at_display(self) -> str:
        stamp = _parse(self.collected_at)
        return stamp.strftime("%a %d %b, %H:%M UTC") if stamp else "never"

    @property
    def age_hours(self) -> float | None:
        stamp = _parse(self.collected_at)
        if stamp is None:
            return None
        return (datetime.now(timezone.utc) - stamp).total_seconds() / 3600

    def fresh_items(self, hours: float) -> list[Article]:
        return [a for a in self.items
                if (age := a.age_hours()) is not None and age <= hours]

    def as_dict(self) -> dict:
        return {
            "note": (
                "Articles retrieved by fpl_assistant/research/collect.py from public "
                "RSS feeds and XML sitemaps. This is Stage A — the raw material. No "
                "paid API, no search service, no scraping vendor: publishers hand "
                "these out for free precisely so they can be read this way."
            ),
            "collected_at": self.collected_at,
            "sources_checked": self.sources_checked,
            "sources_ok": self.sources_ok,
            "items": len(self.items),
            "failures": self.failures,
            "articles": [a.as_dict() for a in self.items],
        }


def _parse(value: str) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def load(path: Path | None = None) -> Corpus:
    path = path or CORPUS_PATH
    if not path.exists():
        return Corpus()
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return Corpus()
    return Corpus(
        items=[Article.from_dict(a) for a in payload.get("articles", [])],
        collected_at=str(payload.get("collected_at", "")),
        sources_checked=int(payload.get("sources_checked", 0) or 0),
        sources_ok=int(payload.get("sources_ok", 0) or 0),
        failures=list(payload.get("failures") or []),
    )


def merge(existing: Corpus, fresh: list[Article]) -> Corpus:
    """Adds new items, keeping one record per URL.

    The newer retrieval wins on a duplicate, because a re-fetch may have
    picked up a published date or an excerpt the first pass missed. This
    is additive on purpose: a feed that drops an article off the end of
    its window should not delete what we already learned from it.
    """
    by_url: dict[str, Article] = {a.url: a for a in existing.items if a.url}
    for article in fresh:
        if not article.url:
            continue
        previous = by_url.get(article.url)
        if previous is None or article.retrieved >= previous.retrieved:
            # Keep the richer of the two excerpts rather than blindly
            # overwriting: sitemaps carry no excerpt and would erase one.
            if previous is not None and len(previous.excerpt) > len(article.excerpt):
                article.excerpt = previous.excerpt
            by_url[article.url] = article
    existing.items = list(by_url.values())
    return existing


def prune(corpus: Corpus, retention_days: int = RETENTION_DAYS) -> Corpus:
    """Drops items too old to be evidence about this gameweek.

    An item with no published date is kept — plenty of sitemaps omit one,
    and discarding everything undated would throw away most club sites.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    kept = []
    for article in corpus.items:
        stamp = article.published_at
        if stamp is None or stamp >= cutoff:
            kept.append(article)
    corpus.items = kept
    return corpus


def save(corpus: Corpus, path: Path | None = None) -> bool:
    path = path or CORPUS_PATH
    corpus.items.sort(key=lambda a: (a.published or "", a.url), reverse=True)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(corpus.as_dict(), indent=1, ensure_ascii=False) + "\n")
    except OSError:
        return False
    return True
