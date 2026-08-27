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

# Domains that actively block the search crawler. Every one of these was
# confirmed by the search API rejecting it by name, not guessed at.
#
# Worth stating why this list exists rather than just letting the calls
# fail: a rejected domain fails the WHOLE search it appears in, so one
# blocked site in a group of six loses the other five as well. Filtering
# them out up front is the difference between a research pass that works
# and one that returns nothing for reasons nobody can see.
#
# The pattern is almost entirely UK regional publishers (Reach plc titles
# and a few nationals). Their beat reporting is genuinely good and it is a
# real loss, so they stay in the source list and get reported as
# unreadable — a gap someone can choose to fill by hand.
BLOCKS_CRAWLER = (
    "football.london",
    "manchestereveningnews.co.uk",
    "birminghammail.co.uk",
    "liverpoolecho.co.uk",
    "chroniclelive.co.uk",
    "nottinghampost.com",
    "hulldailymail.co.uk",
    "coventrytelegraph.net",
    "theargus.co.uk",
    "standard.co.uk",
    "bbc.com",
    "bbc.co.uk",
    "theguardian.com",
    "mylondon.news",
    "yorkshireeveningpost.co.uk",
    "sunderlandecho.com",
    "bournemouthecho.co.uk",
    "eadt.co.uk",
    "dailymail.co.uk",
    "thesun.co.uk",
)

# Confirmed working in testing, and the reason the club feeds are worth
# reaching for at all: a club's own site carries the manager's press
# conference verbatim, and several of them publish their own FPL preview.
# Manchester City run a "FPL Scout Report" per gameweek; Liverpool publish
# "five players to watch"; Aston Villa put out a pre-match FPL preview.
# That is primary-source team news rather than somebody's summary of it.
VERIFIED_READABLE = (
    "mancity.com",
    "arsenal.com",
    "liverpoolfc.com",
    "manutd.com",
    "tottenhamhotspur.com",
    "cpfc.co.uk",
    "avfc.co.uk",
    "brentfordfc.com",
    "brightonandhovealbion.com",
    "premierleague.com",
    "fantasyfootballscout.co.uk",
    "allaboutfpl.com",
    "nevermanagealone.com",
    "fantasyfootballhub.co.uk",
    "rotowire.com",
    "premierinjuries.com",
    "whoscored.com",
    "sportsmole.co.uk",
)

# Categories in the order they should be worked through in a weekly pass.
# Team news first because it invalidates everything else: a tactical read
# on a player who has just been ruled out is wasted effort.
CATEGORY_ORDER = (
    "Official club news",
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
        """Whether a scoped web search can return this source's text.

        Two separate reasons it might not: the format is wrong (video,
        social), or the publisher blocks the crawler. Both end in the same
        place — the source cannot be read — but they are reported apart,
        because one is a permanent property of the medium and the other is
        a policy that could change.
        """
        return not (
            any(blocked in self.domain for blocked in NOT_SEARCHABLE)
            or self.blocks_crawler
        )

    @property
    def blocks_crawler(self) -> bool:
        return any(blocked in self.domain for blocked in BLOCKS_CRAWLER)

    @property
    def verified(self) -> bool:
        return any(known in self.domain for known in VERIFIED_READABLE)

    @property
    def why_unreadable(self) -> str:
        if self.blocks_crawler:
            return "publisher blocks the search crawler"
        if any(blocked in self.domain for blocked in NOT_SEARCHABLE):
            return "video or social — a search cannot read it"
        return ""


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

    # Verified-readable domains lead their group. A search returns a
    # limited number of results, and a domain already known to answer well
    # is a better use of one of those slots than an untested one.
    for domains in by_category.values():
        domains.sort(key=lambda d: (not any(k in d for k in VERIFIED_READABLE), d))

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
    blocked = [s for s in source_plan.unreachable if s.blocks_crawler]
    media = [s for s in source_plan.unreachable if not s.blocks_crawler]
    return (
        f"{source_plan.total_domains} searchable domains in "
        f"{len(source_plan.groups)} search groups. "
        f"{len(media)} sources are video or social and a search cannot read them; "
        f"{len(blocked)} are publishers that block the crawler. "
        f"Both need checking by hand if you want them."
    )
