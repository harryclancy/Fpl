"""The list of places to research from, and how to actually reach them.

The user supplied roughly 165 sources -- FPL specialists, model sites,
club team-news feeds, community threads, podcasts, stats providers. The
useful question is not "what's on the list" but "what can be read from
where the research runs", and the answer is narrower than the list looks:

  * **Direct fetching is blocked** in the hosted session. The egress proxy
    answers 403 to CONNECT for reddit.com, news.google.com,
    fantasy.premierleague.com and most of the rest. Trying anyway wastes a
    round trip per source and returns nothing.
  * **Search scoped to a domain works.** Restricting a web search to a
    handful of these sites returns their actual article content, which is
    the material the write-ups are built from. This is the path that
    works today, costs nothing, and needs no key.

So the list is treated as a *search allowlist* rather than a fetch queue.
Domains are grouped, because a single search accepts only a handful of
them and different groups answer different questions: team news comes
from the news sites, tactical read from the specialists, ownership and
effective-ownership from the live-rank trackers.

A source that cannot be searched is not silently dropped -- `unreachable`
reports it, so the gap is visible rather than looking like nothing was
said.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

SOURCES_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "sources" / "weekly_sources.json"
)

# Domains that web search cannot usefully return article text for. Listed
# rather than filtered by guesswork: a YouTube channel or an X profile is
# a real source a person should check, but a search engine will not return
# its transcript, so promising to have "read" it would be a lie.
NOT_SEARCHABLE = ("youtube.com", "x.com", "twitter.com", "news.google.com")

# Categories in the order they should be worked through in a weekly pass.
# Team news first because it invalidates everything else: a tactical read
# on a player who has just been ruled out is wasted effort.
CATEGORY_ORDER = (
    "Club team news RSS",
    "FPL specialist / rolling page",
    "Premier League news / stats",
    "Model / projections",
    "Live ranks / effective ownership",
    "FPL topic RSS",
    "Community JSON feed",
    "Community",
    "Odds / market",
    "Podcast / video",
)

# How many domains to put in one search. Search engines degrade with long
# allowlists, and a tight group returns better-targeted results than a
# scattergun over eighty sites.
DOMAINS_PER_SEARCH = 6


@dataclass
class Source:
    name: str
    url: str
    category: str = ""

    @property
    def domain(self) -> str:
        return urlparse(self.url).netloc.lower()

    @property
    def searchable(self) -> bool:
        return not any(blocked in self.domain for blocked in NOT_SEARCHABLE)


@dataclass
class SourcePlan:
    """Domain groups to search, in the order they should be worked."""

    groups: list[tuple[str, list[str]]] = field(default_factory=list)
    unreachable: list[Source] = field(default_factory=list)

    @property
    def total_domains(self) -> int:
        return sum(len(domains) for _, domains in self.groups)

    def for_category(self, category: str) -> list[list[str]]:
        return [domains for name, domains in self.groups if name == category]


def load(path: Path | None = None) -> list[Source]:
    path = path or SOURCES_PATH
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    out = []
    for entry in payload:
        if not isinstance(entry, dict) or not entry.get("url"):
            continue
        out.append(
            Source(
                name=str(entry.get("name", "")),
                url=str(entry["url"]),
                category=str(entry.get("category", "")),
            )
        )
    return out


def plan(sources: list[Source] | None = None, per_search: int = DOMAINS_PER_SEARCH) -> SourcePlan:
    """Groups the sources into searchable batches, worst-first by urgency.

    Deduplicated by domain: the list carries twenty separate Google News
    RSS URLs that all live on one host, and searching that host twenty
    times returns the same results twenty times.
    """
    sources = load() if sources is None else sources

    by_category: dict[str, list[str]] = {}
    unreachable: list[Source] = []
    seen: set[str] = set()

    for source in sources:
        if not source.searchable:
            unreachable.append(source)
            continue
        domain = source.domain
        if not domain or domain in seen:
            continue
        seen.add(domain)
        by_category.setdefault(source.category, []).append(domain)

    groups: list[tuple[str, list[str]]] = []
    ordered = list(CATEGORY_ORDER) + [
        c for c in by_category if c not in CATEGORY_ORDER
    ]
    for category in ordered:
        domains = by_category.get(category)
        if not domains:
            continue
        for start in range(0, len(domains), per_search):
            groups.append((category, domains[start : start + per_search]))

    return SourcePlan(groups=groups, unreachable=unreachable)


def summary(source_plan: SourcePlan | None = None) -> str:
    source_plan = plan() if source_plan is None else source_plan
    return (
        f"{source_plan.total_domains} searchable domains in "
        f"{len(source_plan.groups)} search groups; "
        f"{len(source_plan.unreachable)} sources (video and social) that a search "
        f"cannot read and a person has to check by hand."
    )
