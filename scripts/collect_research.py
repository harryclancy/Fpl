"""Stage A, run for real: retrieve current football news into the corpus.

This is the job the Refresh button was pretending to do. It reads the
discovery audit (which sources have a feed or sitemap), fetches each one,
merges what comes back into data/research/corpus.json, tags every article
with the owned players it mentions, and then REFUSES TO REPORT SUCCESS if
the result is implausible.

The last part is the point. The previous system's failure mode was a green
run that had retrieved nothing, so this run fails loudly when:

  * fewer than a handful of sources returned material,
  * or too few articles came back to be a research pass,
  * or every bellwether player — the ones written about daily — came back
    with no evidence, which means the collector broke rather than the
    football world going silent.

    python scripts/collect_research.py [--limit N] [--report PATH]
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant.research import collect, corpus as corpus_mod, evidence, gates

ROOT = Path(__file__).resolve().parent.parent
DISCOVERY = ROOT / "data" / "sources" / "discovery.json"
SQUAD = ROOT / "data" / "squad" / "current.json"
REPORT = ROOT / "data" / "research" / "last_run.json"


def _squad() -> list[dict]:
    try:
        return json.loads(SQUAD.read_text()).get("squad", [])
    except (OSError, json.JSONDecodeError):
        return []


def main() -> int:
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    try:
        discovery = json.loads(DISCOVERY.read_text())
    except (OSError, json.JSONDecodeError):
        print("::error title=No discovery audit::data/sources/discovery.json is "
              "missing. Run scripts/probe_sources.py first — without it the "
              "collector has no machine-readable way into any source.")
        return 1

    usable = [s for s in discovery.get("sources", [])
              if s.get("grade") in collect.USABLE_GRADES and s.get("feed_url")][:limit]
    if not usable:
        print(f"::error title=No usable sources::The discovery audit lists no "
              f"grade A or B sources. {gates.COLLECTION_FAILURE}")
        return 1

    session = collect._session()
    started = time.time()
    fresh: list[collect.Article] = []
    failures: list[str] = []
    ok = 0

    print(f"Collecting from {len(usable)} sources with a feed or sitemap…\n")
    for index, source in enumerate(usable, 1):
        articles, error = collect.collect_from(source, session)
        if error:
            failures.append(error)
            print(f"[{index:>3}/{len(usable)}] --  {source.get('domain', ''):<38} {error}")
            continue
        ok += 1
        fresh.extend(articles)
        print(f"[{index:>3}/{len(usable)}] ok  {source.get('domain', ''):<38} {len(articles)} items")

    squad = _squad()
    evidence.tag_articles(fresh, squad)

    store = corpus_mod.load()
    store = corpus_mod.merge(store, fresh)
    store = corpus_mod.prune(store)
    store.collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    store.sources_checked = len(usable)
    store.sources_ok = ok
    store.failures = failures[:40]
    corpus_mod.save(store)

    collection = gates.check_collection(len(usable), ok, len(fresh), failures)

    by_player = {}
    for player in squad:
        by_player[player["name"]] = evidence.search(
            player["name"], player.get("team", ""), store.items)
    blackout = gates.check_blackout(by_player)
    coverage = gates.check_squad_coverage(by_player, len(squad)) if squad else gates.Verdict(True)

    researched = sum(1 for ev in by_player.values() if ev.researched)
    summary = {
        "ran_at": store.collected_at,
        "seconds": round(time.time() - started, 1),
        "sources_checked": len(usable),
        "sources_ok": ok,
        "new_items": len(fresh),
        "corpus_size": len(store),
        "players_researched": researched,
        "players_total": len(squad),
        "collection": {"ok": collection.ok, "headline": collection.headline,
                       "reasons": collection.reasons},
        "blackout": {"ok": blackout.ok, "headline": blackout.headline,
                     "reasons": blackout.reasons},
        "coverage": {"ok": coverage.ok, "headline": coverage.headline,
                     "reasons": coverage.reasons},
        "players": {name: ev.as_dict() for name, ev in by_player.items()},
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n")

    print(f"\nSOURCES CHECKED: {len(usable)}")
    print(f"SOURCES OK:      {ok}")
    print(f"NEW ITEMS FOUND: {len(fresh)}")
    print(f"CORPUS SIZE:     {len(store)}")
    if squad:
        print(f"PLAYERS RESEARCHED: {researched}/{len(squad)}")

    failed = [v for v in (collection, blackout, coverage) if not v.ok]
    if failed:
        for verdict in failed:
            print(f"::error title={verdict.headline}::" + " | ".join(verdict.reasons))
        return 1

    print("\nAll quality gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
