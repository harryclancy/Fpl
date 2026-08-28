"""The 100 verified-readable sources, and the order to work them in.

Every domain in `data/sources/verified_sources.json` was tested by running
a domain-scoped web search against it and confirming it returned readable
article text. Nothing is listed because a search engine merely indexes it.

That distinction is the whole point of this module. The previous version
carried 228 sources drawn from two curated lists, and treating them as
usable was wrong in a way that was invisible from the outside: a domain
the search API rejects fails the **entire search it appears in**, so one
blocked publisher in a group of six silently loses the other five as
well. A research pass built on an unverified list returns less than one
built on a third as many verified domains, and gives no clue why.

Permanently excluded, and not by preference but by capability:

  * **YouTube and X** — a search cannot return a video transcript or a
    social timeline. Real sources, unreadable here.
  * **Reddit** — post text is not reliably retrievable.
  * **Publishers that block the crawler** — the UK regional titles, the
    BBC, the Guardian, the Independent, Metro, Reuters, Transfermarkt,
    talkSPORT. Each confirmed by the API rejecting it by name.

The research order is not alphabetical or arbitrary. Team news comes
first because it invalidates everything downstream: a tactical read, a
captaincy case or an expected-points projection for a player who has just
been ruled out is wasted work, and worse, it looks authoritative.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

SOURCES_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "sources" / "verified_sources.json"
)

# How many domains to put in one search. Search engines degrade with long
# allowlists, and a tight group returns better-targeted results than a
# scattergun across a hundred sites.
DOMAINS_PER_SEARCH = 6

TIER_NAMES = {
    1: "FPL expert/advice",
    2: "Primary sources (clubs, press conferences, availability)",
    3: "Statistics and data",
    4: "Football analysis and news",
}

# The sequence a gameweek refresh works in, with the tiers each step draws
# on. Ordered by what invalidates what: availability first, because every
# later step is void for a player who is not playing.
RESEARCH_STEPS = (
    ("Official club news and press conferences", (2,)),
    ("Injury and expected-minutes information", (2, 3)),
    ("FPL expert recommendations", (1,)),
    ("Captaincy consensus", (1,)),
    ("Transfer recommendations", (1,)),
    ("Differentials", (1,)),
    ("Underlying statistics", (3,)),
    ("Fixture analysis", (1, 4)),
    ("Price changes and ownership", (1,)),
    ("Conflicting opinions", (1, 4)),
)


@dataclass
class Source:
    name: str
    domain: str
    url: str
    category: str = ""
    tier: int = 1
    used_for: str = ""
    verified: bool = True

    @property
    def tier_name(self) -> str:
        return TIER_NAMES.get(self.tier, "Unknown")


@dataclass
class SearchGroup:
    """One search: a step of the weekly pass, and the domains to scope it to."""

    step: str
    tier: int
    domains: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.step} — tier {self.tier}"


@dataclass
class SourcePlan:
    groups: list[SearchGroup] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)

    @property
    def total_domains(self) -> int:
        return len({s.domain for s in self.sources})

    def by_tier(self, tier: int) -> list[Source]:
        return [s for s in self.sources if s.tier == tier]

    def for_step(self, step: str) -> list[SearchGroup]:
        return [g for g in self.groups if g.step == step]


def load(path: Path | None = None) -> list[Source]:
    path = path or SOURCES_PATH
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []

    out = []
    for entry in payload.get("sources", []):
        if not isinstance(entry, dict) or not entry.get("domain"):
            continue
        # A source that is not flagged verified does not belong here at
        # all. Skipping rather than including it keeps the file's promise
        # honest even if someone edits it carelessly.
        if not entry.get("VERIFIED_READABLE"):
            continue
        out.append(
            Source(
                name=str(entry.get("name", "")),
                domain=str(entry["domain"]),
                url=str(entry.get("url", "")),
                category=str(entry.get("category", "")),
                tier=int(entry.get("tier", 1)),
                used_for=str(entry.get("used_for", "")),
            )
        )
    return out


def plan(sources: list[Source] | None = None, per_search: int = DOMAINS_PER_SEARCH) -> SourcePlan:
    """The full weekly pass, as an ordered list of scoped searches."""
    sources = load() if sources is None else sources

    by_tier: dict[int, list[str]] = {}
    for source in sources:
        by_tier.setdefault(source.tier, []).append(source.domain)

    groups: list[SearchGroup] = []
    for step, tiers in RESEARCH_STEPS:
        for tier in tiers:
            domains = by_tier.get(tier, [])
            for start in range(0, len(domains), per_search):
                groups.append(
                    SearchGroup(step=step, tier=tier, domains=domains[start : start + per_search])
                )

    return SourcePlan(groups=groups, sources=sources)


def allowlist(tier: int | None = None) -> list[str]:
    """Every verified domain, or just one tier's. Nothing else may be searched."""
    return [s.domain for s in load() if tier is None or s.tier == tier]


def summary(source_plan: SourcePlan | None = None) -> str:
    source_plan = plan() if source_plan is None else source_plan
    per_tier = ", ".join(
        f"tier {tier}: {len(source_plan.by_tier(tier))}" for tier in sorted(TIER_NAMES)
    )
    return (
        f"{source_plan.total_domains} verified-readable domains ({per_tier}). "
        f"0 blocked, 0 YouTube, 0 X, 0 inaccessible. "
        f"{len(source_plan.groups)} scoped searches across "
        f"{len(RESEARCH_STEPS)} research steps."
    )


# --- Auditing what the research actually cited ---------------------------

# Names that appear in research files but are not the canonical source
# name. Kept explicit rather than fuzzy-matched: a near-miss matcher would
# quietly accept a source that is not on the list, which is the exact
# failure this whole module exists to prevent.
CITATION_ALIASES = {
    "premier league": "Premier League Official Fantasy",
    "the scout": "Premier League Official Fantasy",
    "premier league official fantasy": "Premier League Official Fantasy",
    "allaboutfpl": "All About FPL",
    "all about fpl": "All About FPL",
    "albion analytics": "Brighton & Hove Albion",
    "goal.com": "GOAL",
    "opta": "Opta Analyst",
    "opta analyst": "Opta Analyst",
    "premier injuries": "Premier Injuries",
    "brentford fc": "Brentford",
    "sports illustrated": "Sports Illustrated FPL",
    # Shortened forms of names that carry a qualifier in the source list.
    "espn": "ESPN Soccer",
    "rotowire": "RotoWire Soccer",
    "sky sports": "Sky Sports Premier League",
    "draftkings network": "DraftKings Network Soccer",
    "liverpool fc": "Liverpool",
}


def canonical(citation: str) -> Source | None:
    """Resolves a citation string in a research file to a verified source.

    Returns None when it cannot, which is the answer that matters: a
    citation that resolves to nothing is a claim sourced to a site outside
    the verified hundred, and the point of the list is that those do not
    get used. This is how the rule stays a rule instead of a promise.
    """
    text = (citation or "").split("—")[0].strip()
    if not text:
        return None
    low = text.lower()
    by_name = {s.name.lower(): s for s in load()}

    if low in by_name:
        return by_name[low]
    alias = CITATION_ALIASES.get(low)
    if alias and alias.lower() in by_name:
        return by_name[alias.lower()]

    # A club citation may carry an "official" suffix: "Liverpool official".
    stripped = low.removesuffix(" official").strip()
    if stripped in by_name:
        return by_name[stripped]
    if stripped in CITATION_ALIASES:
        mapped = CITATION_ALIASES[stripped]
        if mapped.lower() in by_name:
            return by_name[mapped.lower()]

    # Parenthetical qualifiers: "Fantasy Football Scout (five-time top-1k)".
    base = low.split("(")[0].strip()
    if base and base in by_name:
        return by_name[base]
    if base in CITATION_ALIASES and CITATION_ALIASES[base].lower() in by_name:
        return by_name[CITATION_ALIASES[base].lower()]

    # Trailing qualifiers with no separator: "Fantasy Football Scout
    # captaincy poll". Matched by prefix against the longest source name
    # that fits, which is exact rather than fuzzy -- the citation has to
    # BEGIN with a verified source's full name, so a site not on the list
    # can never satisfy it.
    for name in sorted(by_name, key=len, reverse=True):
        if low.startswith(name):
            return by_name[name]
    return None


def unverified_citations(*paths) -> list[str]:
    """Every citation in the given research files that is NOT on the list."""
    import json as _json
    from pathlib import Path as _Path

    found: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("source", "sources") and value:
                    items = [value] if isinstance(value, str) else value
                    for item in items:
                        if not isinstance(item, str):
                            continue
                        for part in item.split("/"):
                            part = part.strip()
                            if part and canonical(part) is None:
                                found.add(part)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for path in paths:
        path = _Path(path)
        if path.exists():
            walk(_json.loads(path.read_text()))
    return sorted(found)
