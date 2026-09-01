"""The research desk: discover broadly, filter hard, read the best closely.

Five stages, in order, with the expensive one last:

  1. DISCOVER   every readable source, up to a candidate ceiling
  2. FILTER     drop what is not writing
  3. DEDUPE     collapse syndicated copies of one story
  4. RANK       score by recency, player, gameweek, source, usefulness
  5. DEEP READ  fetch the full text of the best, adaptively

The shape matters more than any individual step. Discovery is one request
per source and yields hundreds of candidates; deep reading is one request
per article. Reading everything discovered would be a thousand requests
and several minutes for material that is mostly irrelevant. Reading the
top two hundred answers the same questions in a fraction of the time, and
is a great deal politer to publishers who are giving this away.

"Adaptive" is the other half. The stopping condition is not a number of
articles, it is whether the squad has been researched: the loop reads in
batches and stops as soon as every player has enough evidence, or keeps
going while any player is short and there is still material worth reading.
A settled starter with eight sources gets no more effort; a player whose
minutes are in doubt gets targeted extra passes until his questions are
answered or the avenues run out.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fpl_assistant.research import collect, dedupe, evidence, extract, gates, ranking

# The discovery ceiling. Not a target — the system is explicitly allowed
# to find fewer, and 430 good candidates beat 1000 padded ones.
MAX_CANDIDATES = 1000
# Per source, so one enormous sitemap cannot crowd out fifty other sites.
MAX_PER_SOURCE = 40

# Deep-read bounds. The loop stops early when the squad is covered.
MIN_DEEP_READ = 60
TARGET_DEEP_READ = 150
MAX_DEEP_READ = 300
DEEP_READ_BATCH = 30

# Evidence targets, per the brief.
EVIDENCE_MINIMUM = 3
EVIDENCE_GOOD = 5
EVIDENCE_STRONG = 8

FULL = "full"
INCREMENTAL = "incremental"
DEADLINE = "deadline"

# A deadline pass cares about a narrow band of topics and a short window.
DEADLINE_TOPICS = ("team news", "press conference", "injury", "suspension", "transfer")
DEADLINE_HOURS = 72

# The dimensions a player's evidence should ideally span. Breadth is the
# point: eight articles about one transfer rumour is not a researched
# player, it is one fact reported eight times.
DIMENSIONS = ("team news", "press conference", "injury", "transfer",
              "match report", "tactics", "set pieces", "statistics",
              "fpl advice", "fixtures")


@dataclass
class PlayerRecord:
    """Everything the research knows about one player, and what it missed."""

    name: str
    club: str
    evidence_count: int = 0
    source_count: int = 0
    latest_evidence: str = ""
    official_source: bool = False
    fpl_source: bool = False
    team_news_found: bool = False
    starting_assessed: bool = False
    injury_assessed: bool = False
    transfer_assessed: bool = False
    role_assessed: bool = False
    fixtures_assessed: bool = False
    dimensions: list[str] = field(default_factory=list)
    priority: str = "normal"
    items: list = field(default_factory=list)

    @property
    def strength(self) -> str:
        if self.evidence_count >= EVIDENCE_STRONG:
            return "strong"
        if self.evidence_count >= EVIDENCE_GOOD:
            return "good"
        if self.evidence_count >= EVIDENCE_MINIMUM:
            return "minimum"
        return "short"

    @property
    def researched(self) -> bool:
        return self.evidence_count >= EVIDENCE_MINIMUM

    def as_dict(self) -> dict:
        return {
            "player": self.name, "club": self.club,
            "evidence_count": self.evidence_count,
            "source_count": self.source_count,
            "latest_evidence": self.latest_evidence,
            "official_source_found": self.official_source,
            "fpl_source_found": self.fpl_source,
            "team_news_found": self.team_news_found,
            "starting_status_assessed": self.starting_assessed,
            "injury_status_assessed": self.injury_assessed,
            "transfer_status_assessed": self.transfer_assessed,
            "role_assessed": self.role_assessed,
            "fixtures_assessed": self.fixtures_assessed,
            "dimensions_covered": self.dimensions,
            "strength": self.strength,
            "priority": self.priority,
            "researched": self.researched,
            "items": [e.as_dict() for e in self.items[:12]],
        }


@dataclass
class RunReport:
    """The numbers the summary line reports, kept honest by construction."""

    mode: str = FULL
    gameweek: int = 0
    ran_at: str = ""
    seconds: float = 0.0
    sources_attempted: int = 0
    sources_readable: int = 0
    candidates_discovered: int = 0
    substantive_items: int = 0
    duplicates_removed: int = 0
    deeply_analysed: int = 0
    deep_read_failed: int = 0
    corpus_size: int = 0
    players: dict = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    verdicts: dict = field(default_factory=dict)

    @property
    def players_researched(self) -> int:
        return sum(1 for r in self.players.values() if r.researched)

    def as_dict(self) -> dict:
        return {
            "mode": self.mode, "gameweek": self.gameweek, "ran_at": self.ran_at,
            "seconds": round(self.seconds, 1),
            "sources_attempted": self.sources_attempted,
            "sources_readable": self.sources_readable,
            "candidates_discovered": self.candidates_discovered,
            "substantive_items": self.substantive_items,
            "duplicates_removed": self.duplicates_removed,
            "deeply_analysed": self.deeply_analysed,
            "deep_read_failed": self.deep_read_failed,
            "corpus_size": self.corpus_size,
            "players_researched": self.players_researched,
            "players_total": len(self.players),
            "verdicts": self.verdicts,
            "failures": self.failures[:40],
            "players": {name: rec.as_dict() for name, rec in self.players.items()},
        }


def _tier_lookup(sources: list[dict]):
    by_domain = {s.get("domain", ""): int(s.get("tier") or 3) for s in sources}
    return lambda article: by_domain.get(article.domain, 3)


def priority_for(player: dict, record: PlayerRecord | None = None) -> str:
    """How hard to work on this player.

    Effort follows uncertainty, which is the only sensible way to spend a
    fixed budget: a nailed-on starter with eight consistent sources gains
    nothing from a ninth, while the player whose minutes nobody can call
    is the one the whole week's decision turns on.
    """
    status = str(player.get("status", "a"))
    chance = player.get("chance_of_playing_next_round")
    if status != "a" or (chance is not None and chance <= 75):
        return "high"
    if record is not None and record.evidence_count < EVIDENCE_MINIMUM:
        return "high"
    if bool(player.get("on_bench")) and float(player.get("price", 0) or 0) <= 4.5:
        return "low"
    if record is not None and record.evidence_count >= EVIDENCE_STRONG:
        return "low"
    return "normal"


def discover(sources: list[dict], session, mode: str = FULL,
             max_candidates: int = MAX_CANDIDATES,
             since: datetime | None = None) -> tuple[list, list[str], int]:
    """Stage 1. Every readable source contributes; nobody eats the budget.

    The first version walked the source list taking up to MAX_PER_SOURCE
    from each and stopping at the ceiling. That is breadth-first in name
    only: forty large sitemaps reached 1000 candidates before the other
    thirty-eight sources were attempted at all, and the ones skipped were
    the official club RSS feeds — the highest-value material in the list.
    Squad coverage fell from 15/15 to 7/15 with no other change.

    So every source is asked first, with a fair per-source share, and the
    ceiling is applied afterwards by interleaving. A site with a 30,000
    entry archive and a club feed with twenty posts now get equal standing
    in the first round, which is what breadth-first was supposed to mean.
    """
    failures: list[str] = []
    readable = 0
    max_age = 21 if mode == FULL else (3 if mode == DEADLINE else 10)
    share = max(6, max_candidates // max(1, len(sources)))

    per_source: list[list] = []
    for source in sources:
        articles, error = collect.collect_from(
            source, session, max_age_days=max_age, limit=min(MAX_PER_SOURCE, share * 2))
        if error:
            failures.append(error)
            continue
        readable += 1
        tier = int(source.get("tier") or 3)
        for article in articles:
            article.source_tier = tier
        if since is not None:
            articles = [a for a in articles
                        if a.published_at is None or a.published_at >= since]
        if articles:
            per_source.append(articles)

    # Interleave: one from each source in turn, so the ceiling trims the
    # tail of every source rather than deleting whole sources.
    candidates: list = []
    depth = 0
    while len(candidates) < max_candidates and per_source:
        took_any = False
        for bucket in per_source:
            if depth < len(bucket):
                candidates.append(bucket[depth])
                took_any = True
                if len(candidates) >= max_candidates:
                    break
        if not took_any:
            break
        depth += 1

    if len(candidates) >= max_candidates:
        failures.append(f"candidate ceiling of {max_candidates} reached after taking "
                        f"{depth + 1} items from each of {len(per_source)} sources")
    return candidates, failures, readable


def deep_read(articles: list, session, squad: list[dict], gameweek: int,
              report: RunReport, min_items: int = MIN_DEEP_READ,
              target: int = TARGET_DEEP_READ, ceiling: int = MAX_DEEP_READ) -> list:
    """Stage 5. Fetch the best candidates in full, stopping when covered.

    The loop is the adaptive part. After each batch it re-checks the squad:
    if every player has enough evidence and the minimum effort has been
    made, it stops — there is no value in reading another hundred articles
    to confirm what is already known. If players are still short it keeps
    going, up to the ceiling, then reports the shortfall honestly rather
    than padding the count.
    """
    read: list = []
    index = 0
    while index < len(articles) and len(read) < ceiling:
        batch = articles[index:index + DEEP_READ_BATCH]
        index += DEEP_READ_BATCH
        for article in batch:
            if len(read) >= ceiling:
                break
            result = collect.fetch(article.url, session)
            if not result.ok:
                report.deep_read_failed += 1
                continue
            extracted = extract.from_html(result.text)
            if not extracted.ok:
                report.deep_read_failed += 1
                continue
            article.body = extracted.text
            article.topics = list(extracted.topics)
            article.deep_read = True
            read.append(article)
            time.sleep(collect.POLITE_DELAY_SECONDS)

        if len(read) < min_items:
            continue
        covered = _coverage(read + [a for a in articles if not a.deep_read], squad)
        short = [name for name, rec in covered.items() if not rec.researched]
        if not short and len(read) >= min_items:
            break
        if len(read) >= target and len(short) <= 1:
            # Diminishing returns: one stubborn player is usually a player
            # nobody has written about, not a reading problem.
            break
    return read


def _coverage(articles: list, squad: list[dict]) -> dict[str, PlayerRecord]:
    """Builds the per-player research record from whatever has been read."""
    records: dict[str, PlayerRecord] = {}
    for player in squad:
        name = str(player.get("name", ""))
        club = str(player.get("team", ""))
        found = evidence.search(name, club, articles,
                                full_name=str(player.get("full_name", "")))
        items = found.substantive_items
        record = PlayerRecord(name=name, club=club, items=items)
        record.evidence_count = len(items)
        record.source_count = len({e.article.source for e in items})
        dates = [e.article.published for e in items if e.article.published]
        record.latest_evidence = max(dates) if dates else ""
        record.official_source = any(e.article.domain in ranking.PRIMARY_DOMAINS
                                     for e in items)
        record.fpl_source = any("fpl" in e.article.source.lower()
                                or "fantasy" in e.article.source.lower() for e in items)

        topics = set()
        for item in items:
            topics.update(item.article.topics or ())
            if item.kind in ("team news", "transfer"):
                topics.add(item.kind)
        record.dimensions = sorted(topics & set(DIMENSIONS))
        record.team_news_found = "team news" in topics
        record.starting_assessed = bool(topics & {"team news", "match report", "rotation"})
        record.injury_assessed = "injury" in topics or record.team_news_found
        record.transfer_assessed = "transfer" in topics
        record.role_assessed = bool(topics & {"tactics", "set pieces"})
        record.fixtures_assessed = bool(topics & {"fixtures", "fpl advice"})
        record.priority = priority_for(player, record)
        records[name] = record
    return records


def run(sources: list[dict], squad: list[dict], gameweek: int, session=None,
        mode: str = FULL, since: datetime | None = None,
        max_candidates: int = MAX_CANDIDATES, progress=None) -> tuple[list, RunReport]:
    """The whole pipeline. Returns (articles worth keeping, report)."""
    session = session or collect._session()
    started = time.time()
    report = RunReport(mode=mode, gameweek=gameweek,
                       ran_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def say(fraction: float, text: str) -> None:
        if progress:
            progress(fraction, text)

    if mode == DEADLINE and since is None:
        since = datetime.now(timezone.utc) - timedelta(hours=DEADLINE_HOURS)

    say(0.05, "Discovering recent articles across every readable source…")
    report.sources_attempted = len(sources)
    candidates, failures, readable = discover(
        sources, session, mode, max_candidates, since)
    report.sources_readable = readable
    report.candidates_discovered = len(candidates)
    report.failures = failures

    say(0.45, f"Filtering {len(candidates)} candidates…")
    substantive = [a for a in candidates if a.is_article]
    report.substantive_items = len(substantive)

    say(0.5, "Removing syndicated duplicates…")
    tier_of = _tier_lookup(sources)
    unique, removed = dedupe.apply(substantive, tier_of)
    report.duplicates_removed = removed

    say(0.55, "Ranking by relevance…")
    evidence.tag_articles(unique, squad)
    ranked = ranking.rank(unique, squad, gameweek, tier_of)

    say(0.6, "Reading the most useful material in full…")
    read = deep_read(ranked, session, squad, gameweek, report)
    report.deeply_analysed = len(read)

    say(0.9, "Assessing every owned player…")
    records = _coverage(ranked, squad)
    report.players = records
    report.seconds = time.time() - started
    return ranked, report


def verdicts(report: RunReport, corpus_size: int) -> dict:
    """Stage gates, as a dict the caller can render or fail on."""
    collection = gates.check_collection(
        report.sources_attempted, report.sources_readable,
        report.substantive_items, report.failures)
    by_player = {
        name: _as_player_evidence(rec, corpus_size) for name, rec in report.players.items()
    }
    blackout = gates.check_blackout(by_player)
    coverage = (gates.check_squad_coverage(by_player, len(report.players))
                if report.players else gates.Verdict(True))
    return {
        "collection": {"ok": collection.ok, "headline": collection.headline,
                       "reasons": collection.reasons},
        "blackout": {"ok": blackout.ok, "headline": blackout.headline,
                     "reasons": blackout.reasons},
        "coverage": {"ok": coverage.ok, "headline": coverage.headline,
                     "reasons": coverage.reasons},
    }


def _as_player_evidence(record: PlayerRecord, corpus_size: int):
    """Adapts a PlayerRecord to what the existing gates expect."""
    found = evidence.PlayerEvidence(player=record.name, club=record.club,
                                    corpus_size=corpus_size)
    found.items = record.items
    return found
