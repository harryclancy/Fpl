"""Audits every verified source for whether new articles can be DISCOVERED.

The distinction this exists to enforce: `data/sources/verified_sources.json`
stores a name and a homepage URL for 100 sites. A homepage URL is a
bookmark. It tells the program nothing about how to find out what was
published this morning, which is the only question that matters for weekly
research.

So this asks each site directly — does it publish an RSS or Atom feed, or
an XML sitemap? — and grades what comes back:

    A  working feed: new articles discovered automatically
    B  sitemap or news-sitemap: recent URLs discoverable
    C  reachable, but no discovery mechanism found
    D  blocked, dead, or nothing parseable

Only A and B are counted as sources the research engine can use. C and D
are recorded rather than deleted, because knowing a source is unusable is
itself a finding, and because a site can add a feed later.

Run where outbound HTTPS is unrestricted. A Claude Code session is NOT
such a place — its egress proxy answers 403 to almost every football
domain — which is precisely why this runs in GitHub Actions.

    python scripts/probe_sources.py [--limit N]
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant.research import collect

SOURCES_DIR = Path(__file__).resolve().parent.parent / "data" / "sources"
VERIFIED = SOURCES_DIR / "verified_sources.json"
DISCOVERY = SOURCES_DIR / "discovery.json"


def main() -> int:
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    try:
        payload = json.loads(VERIFIED.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"::error title=No source list::Could not read {VERIFIED}: {exc}")
        return 1

    sources = payload.get("sources", [])[:limit]
    session = collect._session()
    reports = []
    started = time.time()

    print(f"Probing {len(sources)} sources for a machine-readable index…\n")
    for index, source in enumerate(sources, 1):
        name = source.get("name", "")
        domain = source.get("domain", "")
        report = collect.probe(name, domain, session)
        report_dict = report.as_dict()
        report_dict["tier"] = source.get("tier")
        report_dict["used_for"] = source.get("used_for", "")
        reports.append(report_dict)
        print(f"[{index:>3}/{len(sources)}] {report.grade}  {domain:<38} "
              f"{report.method or '-':<8} {report.items or ''}")

    grades = {g: sum(1 for r in reports if r["grade"] == g) for g in "ABCD"}
    usable = grades["A"] + grades["B"]

    DISCOVERY.parent.mkdir(parents=True, exist_ok=True)
    DISCOVERY.write_text(json.dumps({
        "note": (
            "How each verified source can be READ BY A PROGRAM, established by "
            "probing it rather than by assumption. `discovery_method` is what the "
            "collector uses; `grade` records whether new articles can be found at "
            "all. Only grades A and B may be counted as sources researched — a "
            "homepage URL alone is a bookmark, not a research capability."
        ),
        "grades": collect.GRADE_NAMES,
        "probed": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "counts": {**grades, "usable": usable, "total": len(reports)},
        "sources": reports,
    }, indent=1, ensure_ascii=False) + "\n")

    print(f"\nA (feed): {grades['A']}   B (sitemap): {grades['B']}   "
          f"C (direct only): {grades['C']}   D (unusable): {grades['D']}")
    print(f"Usable for automated discovery: {usable}/{len(reports)}")
    print(f"Took {time.time() - started:.0f}s. Wrote {DISCOVERY}.")

    if usable == 0:
        print("::error title=No usable sources::Not one source exposed a feed or "
              "sitemap. Either every request was blocked, or this ran somewhere "
              "without outbound internet access.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
