"""Runs the adaptive research pipeline and enforces the quality gates.

    python scripts/collect_research.py [--mode full|incremental|deadline]
                                       [--max-candidates N] [--gameweek N]

Modes exist because the three occasions want different things. A FULL pass
rebuilds the picture when a new gameweek starts and looks back three weeks.
An INCREMENTAL pass only wants what has appeared since the last run, which
is most of the time. A DEADLINE pass narrows hard onto the last 72 hours
and the topics that decide a team sheet — press conferences, injuries,
suspensions, late transfers.

Exits non-zero when a gate fails, so a run that retrieved nothing cannot
report success by the only signal CI reads.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant.analysis import writeup as writeup_mod
from fpl_assistant.research import collect, corpus as corpus_mod, pipeline

ROOT = Path(__file__).resolve().parent.parent
DISCOVERY = ROOT / "data" / "sources" / "discovery.json"
SQUAD = ROOT / "data" / "squad" / "current.json"
REPORT = ROOT / "data" / "research" / "last_run.json"
WRITEUPS = ROOT / "data" / "research" / "writeups.json"


def _arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main() -> int:
    mode = _arg("--mode", pipeline.FULL)
    max_candidates = int(_arg("--max-candidates", pipeline.MAX_CANDIDATES))

    try:
        discovery = json.loads(DISCOVERY.read_text())
    except (OSError, json.JSONDecodeError):
        print("::error title=No discovery audit::data/sources/discovery.json is missing. "
              "Run scripts/probe_sources.py first.")
        return 1

    sources = [s for s in discovery.get("sources", [])
               if s.get("grade") in collect.USABLE_GRADES and s.get("feed_url")]
    if not sources:
        print(f"::error title=No usable sources::{pipeline.gates.COLLECTION_FAILURE}")
        return 1

    try:
        squad_payload = json.loads(SQUAD.read_text())
    except (OSError, json.JSONDecodeError):
        squad_payload = {}
    squad = squad_payload.get("squad", [])
    gameweek = int(_arg("--gameweek", squad_payload.get("planning_gameweek", 0)) or 0)

    store = corpus_mod.load()
    since = None
    if mode == pipeline.INCREMENTAL and store.collected_at:
        since = datetime.fromisoformat(store.collected_at)

    print(f"Mode: {mode} · gameweek {gameweek} · {len(sources)} readable sources "
          f"· ceiling {max_candidates} candidates\n")

    def progress(fraction, text):
        print(f"  [{fraction * 100:>3.0f}%] {text}")

    articles, report = pipeline.run(
        sources, squad, gameweek, mode=mode, since=since,
        max_candidates=max_candidates, progress=progress, known=store.items)

    store = corpus_mod.prune(corpus_mod.merge(store, articles))
    store.collected_at = report.ran_at
    store.sources_checked = report.sources_attempted
    store.sources_ok = report.sources_readable
    store.failures = report.failures[:40]
    corpus_mod.save(store)
    report.corpus_size = len(store)

    # Stage B, generated here so the committed write-ups always match the
    # committed corpus. Generating them in the app instead would let the
    # page show prose derived from evidence that is no longer on disk.
    writeups = writeup_mod.build_all(
        squad,
        {name: pipeline._as_player_evidence(rec, len(store))
         for name, rec in report.players.items()},
        starting_ids={p["id"] for p in squad if not p.get("on_bench")},
        captain_id=next((p["id"] for p in squad if p.get("is_captain")), None),
    )
    WRITEUPS.parent.mkdir(parents=True, exist_ok=True)
    WRITEUPS.write_text(json.dumps({
        "note": (
            "Homepage prose, composed from data/research/corpus.json. Every claim is "
            "a sentence quoted from a retrieved article and attributed to its outlet; "
            "`evidence_used` holds the URLs behind each write-up. No language model "
            "and no paid API is involved — see analysis/writeup.py."
        ),
        "generated": report.ran_at,
        "gameweek": gameweek,
        "corpus_size": len(store),
        "players": {name: w.as_dict() for name, w in writeups.items()},
    }, indent=1, ensure_ascii=False) + "\n")
    with_prose = sum(1 for w in writeups.values() if w.has_prose)

    report.verdicts = pipeline.verdicts(report, len(store))
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report.as_dict(), indent=1, ensure_ascii=False) + "\n")

    print(f"\nSOURCES ATTEMPTED:         {report.sources_attempted}")
    print(f"SOURCES READABLE:          {report.sources_readable}")
    print(f"CANDIDATE ITEMS DISCOVERED:{report.candidates_discovered:>5}")
    print(f"SUBSTANTIVE ITEMS:         {report.substantive_items}")
    print(f"DUPLICATES REMOVED:        {report.duplicates_removed}")
    print(f"DEEPLY ANALYSED:           {report.deeply_analysed} "
          f"({report.deep_read_failed} unreadable)")
    print(f"CORPUS SIZE:               {report.corpus_size}")
    print(f"PLAYERS FULLY RESEARCHED:  {report.players_researched}/{len(report.players)}")
    print(f"WRITE-UPS WITH PROSE:      {with_prose}/{len(writeups)}")
    print(f"TOOK:                      {report.seconds:.0f}s")

    failed = [v for v in report.verdicts.values() if not v["ok"]]
    for verdict in failed:
        print(f"::error title={verdict['headline']}::" + " | ".join(verdict["reasons"]))
    if failed:
        return 1

    print("\nAll quality gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
