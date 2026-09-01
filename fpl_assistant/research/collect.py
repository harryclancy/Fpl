"""Stage A: actually going and getting football news.

This module exists because the app did not have one. The whole "research"
system was a set of JSON files that a Claude Code session wrote by hand,
and the in-app Refresh button called `st.cache_data.clear()` — it re-read
those same files. Nothing anywhere in the deployed application had ever
fetched a news article. `fpl_assistant/api.py` talks to exactly one host,
fantasy.premierleague.com, and that is prices and fixtures, not team news.

So a player the hand-written file happened to cover looked researched, a
player it missed looked "unchecked", and pressing Refresh could never move
a player from the second group to the first. Seven of fifteen owned
players were permanently in the second group.

The fix has to be code that runs where the app runs. Three constraints
shaped it:

  1. **Free.** No search API, no scraping service, no LLM API. Publishers
     hand out RSS and XML sitemaps for nothing; that is the entire budget.

  2. **No new dependencies.** `requests` was already here; RSS, Atom and
     sitemaps are simple XML that `xml.etree` handles. Adding feedparser
     would work too, but every dependency is another thing that can fail
     an install on a free Streamlit deploy.

  3. **Honest failure.** A fetch that returns a 403, or a feed that parses
     to zero entries, must be recorded as a failure with its reason. The
     bug this replaces was not "the research was wrong", it was "the
     research was absent and the app said nothing", so silence is the one
     outcome this module may never produce.

Nothing here is clever. It asks publishers for the list of things they
have published, which they publish specifically so that it can be asked.
"""
from __future__ import annotations

import gzip
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import urljoin, urlparse

import requests

USER_AGENT = (
    "FPLAssistant/1.0 (personal Fantasy Premier League dashboard; "
    "+https://github.com/harryclancy/Fpl)"
)
TIMEOUT_SECONDS = 12
# Courtesy pause between requests to the same host. These are small sites
# run by enthusiasts and we are a guest on all of them.
POLITE_DELAY_SECONDS = 0.3

# Conventional places a site publishes its index. Tried in order; the
# first that returns parseable entries wins, so a site with a real feed is
# never crawled via sitemap.
FEED_PATHS = (
    "/feed/", "/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml",
    "/index.xml", "/feeds/all.rss.xml", "/blog/feed/", "/news/feed/",
)
SITEMAP_PATHS = (
    "/sitemap.xml", "/sitemap_index.xml", "/news-sitemap.xml",
    "/post-sitemap.xml", "/sitemap-news.xml",
)

# How far back an item is worth keeping. Team news has a short shelf life
# and the point of the whole exercise is recency.
DEFAULT_MAX_AGE_DAYS = 21

RSS_DATE_FORMATS = (
    "%a, %d %b %Y %H:%M:%S %z",
    "%a, %d %b %Y %H:%M:%S %Z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d",
)

# Discovery grades, as requested. Only A and B count as "a source the
# research engine can actually use"; C and D must never be counted toward
# "sources researched", because a homepage URL you cannot crawl is not a
# research capability, it is a bookmark.
GRADE_FULL = "A"       # a working feed: new articles discovered automatically
GRADE_PARTIAL = "B"    # sitemap or category page yields recent URLs
GRADE_DIRECT = "C"     # reachable, but no way to discover what is new
GRADE_UNUSABLE = "D"   # blocked, dead, or returns nothing parseable

GRADE_NAMES = {
    GRADE_FULL: "Fully automatable — working feed",
    GRADE_PARTIAL: "Partially automatable — sitemap or category listing",
    GRADE_DIRECT: "Direct page only — cannot discover new articles",
    GRADE_UNUSABLE: "Unusable — blocked, dead or unparseable",
}
USABLE_GRADES = (GRADE_FULL, GRADE_PARTIAL)


@dataclass
class Article:
    """One retrieved item. The unit the research engine reasons over."""

    title: str
    url: str
    source: str
    domain: str
    published: str = ""
    retrieved: str = ""
    excerpt: str = ""
    players: list[str] = field(default_factory=list)
    club: str = ""
    gameweek: int | None = None
    source_type: str = ""

    @property
    def published_at(self) -> datetime | None:
        return _parse_date(self.published)

    def age_hours(self, now: datetime | None = None) -> float | None:
        stamp = self.published_at
        if stamp is None:
            return None
        now = now or datetime.now(timezone.utc)
        return (now - stamp).total_seconds() / 3600

    def as_dict(self) -> dict:
        return {
            "title": self.title, "url": self.url, "source": self.source,
            "domain": self.domain, "published": self.published,
            "retrieved": self.retrieved, "excerpt": self.excerpt,
            "players": self.players, "club": self.club,
            "gameweek": self.gameweek, "source_type": self.source_type,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Article":
        return cls(
            title=str(data.get("title", "")), url=str(data.get("url", "")),
            source=str(data.get("source", "")), domain=str(data.get("domain", "")),
            published=str(data.get("published", "")),
            retrieved=str(data.get("retrieved", "")),
            excerpt=str(data.get("excerpt", "")),
            players=list(data.get("players") or []),
            club=str(data.get("club", "")),
            gameweek=data.get("gameweek"),
            source_type=str(data.get("source_type", "")),
        )


@dataclass
class FetchResult:
    """What happened when we asked. Failure carries its reason."""

    url: str
    ok: bool
    status: int | None = None
    text: str = ""
    error: str = ""

    @property
    def reason(self) -> str:
        if self.ok:
            return "ok"
        if self.status:
            return f"HTTP {self.status}"
        return self.error or "unknown failure"


@dataclass
class SourceReport:
    """The audit of one source: can we discover new articles from it?"""

    name: str
    domain: str
    grade: str = GRADE_UNUSABLE
    method: str = ""
    feed_url: str = ""
    items: int = 0
    attempts: list[tuple[str, str]] = field(default_factory=list)
    note: str = ""

    @property
    def usable(self) -> bool:
        return self.grade in USABLE_GRADES

    def as_dict(self) -> dict:
        return {
            "name": self.name, "domain": self.domain, "grade": self.grade,
            "discovery_method": self.method, "feed_url": self.feed_url,
            "items": self.items, "note": self.note,
            "attempts": [{"url": u, "result": r} for u, r in self.attempts],
        }


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        # Publishers serve different things to a browser and to a bare
        # client. Asking for feed types first makes a feed more likely to
        # come back as a feed rather than as an HTML landing page.
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/html;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
    })
    return session


def fetch(url: str, session: requests.Session | None = None) -> FetchResult:
    """One HTTP GET, with every failure mode turned into a stated reason.

    Deliberately never raises. A research run touches dozens of hosts and
    one refusing must not end the run — but it must be *recorded*, because
    a run that quietly skipped half its sources and reported success is
    the exact failure this whole module was written to end.
    """
    session = session or _session()
    try:
        resp = session.get(url, timeout=TIMEOUT_SECONDS, allow_redirects=True)
    except requests.exceptions.SSLError as exc:
        return FetchResult(url, False, error=f"TLS failure: {exc.__class__.__name__}")
    except requests.exceptions.Timeout:
        return FetchResult(url, False, error=f"timed out after {TIMEOUT_SECONDS}s")
    except requests.exceptions.ProxyError as exc:
        return FetchResult(url, False, error=f"blocked by egress proxy: {exc.__class__.__name__}")
    except requests.exceptions.RequestException as exc:
        return FetchResult(url, False, error=f"{exc.__class__.__name__}")

    if resp.status_code != 200:
        return FetchResult(url, False, status=resp.status_code)

    body = resp.content
    # Some sitemaps are served gzipped without a decoding header.
    if body[:2] == b"\x1f\x8b":
        try:
            body = gzip.decompress(body)
        except OSError:
            pass
    try:
        text = body.decode(resp.encoding or "utf-8", errors="replace")
    except (LookupError, TypeError):
        text = body.decode("utf-8", errors="replace")
    return FetchResult(url, True, status=200, text=text)


def _strip_tags(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()


def _parse_date(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for fmt in RSS_DATE_FORMATS:
        try:
            stamp = datetime.strptime(raw, fmt)
            return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_feed(text: str, base_url: str = "") -> list[dict]:
    """Reads RSS 2.0 and Atom without caring which one it got.

    The two formats disagree about almost every element name, so this
    walks the tree by local tag name instead of assuming a schema.
    """
    try:
        root = ET.fromstring(text.strip())
    except ET.ParseError:
        return []

    out: list[dict] = []
    for node in root.iter():
        if _localname(node.tag) not in ("item", "entry"):
            continue
        item = {"title": "", "url": "", "published": "", "excerpt": ""}
        for child in node:
            name = _localname(child.tag)
            value = (child.text or "").strip()
            if name == "title" and not item["title"]:
                item["title"] = _strip_tags(value)
            elif name == "link":
                href = child.attrib.get("href") or value
                rel = child.attrib.get("rel", "alternate")
                if href and rel == "alternate" and not item["url"]:
                    item["url"] = href.strip()
            elif name in ("pubdate", "published", "updated", "date") and not item["published"]:
                item["published"] = value
            elif name in ("description", "summary", "content", "encoded") and not item["excerpt"]:
                item["excerpt"] = _strip_tags(value)[:1200]
        if item["url"] and base_url:
            item["url"] = urljoin(base_url, item["url"])
        if item["title"] and item["url"]:
            out.append(item)
    return out


def parse_sitemap(text: str) -> tuple[list[str], list[dict]]:
    """Returns (nested sitemap URLs, page entries).

    A sitemap index points at other sitemaps; a URL set lists pages. News
    sitemaps carry publication dates, which is what makes them usable as a
    recency source rather than just a list of everything.
    """
    try:
        root = ET.fromstring(text.strip())
    except ET.ParseError:
        return [], []

    nested: list[str] = []
    pages: list[dict] = []
    for node in root.iter():
        name = _localname(node.tag)
        if name == "sitemap":
            for child in node:
                if _localname(child.tag) == "loc" and child.text:
                    nested.append(child.text.strip())
        elif name == "url":
            entry = {"url": "", "published": "", "title": ""}
            for child in node:
                cname = _localname(child.tag)
                if cname == "loc" and child.text:
                    entry["url"] = child.text.strip()
                elif cname == "lastmod" and child.text:
                    entry["published"] = child.text.strip()
                else:
                    # Google news sitemap extension carries a real title
                    # and publication date; far better than a bare URL.
                    for sub in child.iter():
                        sname = _localname(sub.tag)
                        if sname == "publication_date" and sub.text:
                            entry["published"] = sub.text.strip()
                        elif sname == "title" and sub.text and not entry["title"]:
                            entry["title"] = _strip_tags(sub.text)
            if entry["url"]:
                pages.append(entry)
    return nested, pages


def _title_from_url(url: str) -> str:
    """A readable title from a slug, for sitemaps that carry no title."""
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"^\d{4}[-/]\d{2}[-/]\d{2}[-/]?", "", slug)
    slug = re.sub(r"\.(html?|php|aspx)$", "", slug)
    return re.sub(r"[-_]+", " ", slug).strip().capitalize()


def probe(name: str, domain: str, session: requests.Session | None = None,
          feed_url: str = "") -> SourceReport:
    """Works out, by asking, how new articles can be discovered from a site.

    This is the audit the user asked for, and it is done by measurement
    rather than by assumption: every candidate URL is actually requested
    and the outcome recorded, so the resulting grade can be checked.
    """
    session = session or _session()
    report = SourceReport(name=name, domain=domain)
    base = f"https://{domain}"

    candidates = [feed_url] if feed_url else []
    candidates += [urljoin(base, path) for path in FEED_PATHS]

    for url in candidates:
        if not url:
            continue
        result = fetch(url, session)
        time.sleep(POLITE_DELAY_SECONDS)
        if not result.ok:
            report.attempts.append((url, result.reason))
            continue
        entries = parse_feed(result.text, url)
        report.attempts.append((url, f"ok, {len(entries)} entries"))
        if entries:
            report.grade, report.method = GRADE_FULL, "rss"
            report.feed_url, report.items = url, len(entries)
            return report

    for path in SITEMAP_PATHS:
        url = urljoin(base, path)
        result = fetch(url, session)
        time.sleep(POLITE_DELAY_SECONDS)
        if not result.ok:
            report.attempts.append((url, result.reason))
            continue
        nested, pages = parse_sitemap(result.text)
        report.attempts.append((url, f"ok, {len(pages)} pages, {len(nested)} nested"))
        if pages:
            report.grade, report.method = GRADE_PARTIAL, "sitemap"
            report.feed_url, report.items = url, len(pages)
            return report
        if nested:
            # Follow one level into the index, preferring anything that
            # looks like news over the site's static pages.
            ranked = sorted(nested, key=lambda u: ("news" not in u.lower(), "post" not in u.lower()))
            for child in ranked[:3]:
                child_result = fetch(child, session)
                time.sleep(POLITE_DELAY_SECONDS)
                if not child_result.ok:
                    report.attempts.append((child, child_result.reason))
                    continue
                _, child_pages = parse_sitemap(child_result.text)
                report.attempts.append((child, f"ok, {len(child_pages)} pages"))
                if child_pages:
                    report.grade, report.method = GRADE_PARTIAL, "sitemap"
                    report.feed_url, report.items = child, len(child_pages)
                    return report

    root = fetch(base, session)
    time.sleep(POLITE_DELAY_SECONDS)
    report.attempts.append((base, root.reason))
    if root.ok:
        report.grade = GRADE_DIRECT
        report.note = "Homepage loads but no feed or sitemap was found — known URLs only."
    else:
        report.grade = GRADE_UNUSABLE
        report.note = f"Homepage unreachable ({root.reason})."
    return report


def collect_from(source: dict, session: requests.Session | None = None,
                 max_age_days: int = DEFAULT_MAX_AGE_DAYS,
                 limit: int = 60) -> tuple[list[Article], str]:
    """Retrieves recent items from one source. Returns (articles, error).

    `error` is empty on success. It is a string rather than an exception
    because the caller needs to report per-source outcomes, not abort.
    """
    session = session or _session()
    method = str(source.get("discovery_method") or "").lower()
    url = str(source.get("feed_url") or "")
    name = str(source.get("name") or source.get("domain") or "")
    domain = str(source.get("domain") or "")
    source_type = str(source.get("category") or source.get("used_for") or "")

    if method not in ("rss", "sitemap") or not url:
        return [], f"{name}: no automated discovery method configured"

    result = fetch(url, session)
    if not result.ok:
        return [], f"{name}: {result.reason} for {url}"

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max_age_days)
    retrieved = now.isoformat(timespec="seconds")
    articles: list[Article] = []

    if method == "rss":
        entries = parse_feed(result.text, url)
        if not entries:
            return [], f"{name}: feed at {url} parsed to zero entries"
        for entry in entries[:limit]:
            stamp = _parse_date(entry["published"])
            if stamp is not None and stamp < cutoff:
                continue
            articles.append(Article(
                title=entry["title"], url=entry["url"], source=name, domain=domain,
                published=stamp.isoformat(timespec="seconds") if stamp else "",
                retrieved=retrieved, excerpt=entry["excerpt"], source_type=source_type,
            ))
    else:
        _, pages = parse_sitemap(result.text)
        if not pages:
            return [], f"{name}: sitemap at {url} listed no pages"
        dated = [(p, _parse_date(p["published"])) for p in pages]
        dated.sort(key=lambda pair: pair[1] or datetime.min.replace(tzinfo=timezone.utc),
                   reverse=True)
        for page, stamp in dated[:limit]:
            if stamp is not None and stamp < cutoff:
                continue
            articles.append(Article(
                title=page["title"] or _title_from_url(page["url"]),
                url=page["url"], source=name, domain=domain,
                published=stamp.isoformat(timespec="seconds") if stamp else "",
                retrieved=retrieved, excerpt="", source_type=source_type,
            ))

    if not articles:
        return [], f"{name}: nothing published in the last {max_age_days} days"
    return articles, ""
