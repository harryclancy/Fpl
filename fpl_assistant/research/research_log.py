"""What the last refresh actually managed to read.

"We searched 100 websites" is a claim about effort. "Sources read: 34/100"
is a claim about evidence, and only the second one is worth putting on a
page. This module records which of the verified sources genuinely returned
usable material in a given week, so the number shown to the reader is
counted rather than asserted.

The distinction matters because the failure it guards against is subtle
and flattering: a research pass that quietly returns nothing from half its
sources still produces a full-looking page, and nobody can tell. Recording
the count makes a thin week look thin.

Sources are recorded by the citation names that appear in the research
files, then resolved against the verified list. A name that resolves to
nothing is reported rather than dropped — it means something was cited
from outside the hundred, which is the one thing the source rules forbid.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from fpl_assistant.research import sources as source_list

LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "sources" / "research_log.json"

RESEARCH_FILES = (
    "data/consensus/gw{gw}.json",
    "data/consensus/matchups_gw{gw}.json",
    "data/consensus/teams.json",
    "data/odds/gw{gw}.json",
)


@dataclass
class ResearchRun:
    """One weekly refresh, and how much of the source list it reached."""

    gameweek: int
    finished_at: str = ""
    sources_used: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def total_available(self) -> int:
        return len(source_list.load())

    @property
    def read(self) -> int:
        return len(self.sources_used)

    @property
    def coverage_line(self) -> str:
        return f"Sources successfully read: {self.read}/{self.total_available}"

    @property
    def finished_display(self) -> str:
        if not self.finished_at:
            return "never"
        try:
            stamp = datetime.fromisoformat(self.finished_at)
        except ValueError:
            return self.finished_at
        return stamp.strftime("%a %d %b %Y, %H:%M UTC")

    @property
    def is_thin(self) -> bool:
        """Whether this week's evidence is thin enough to say so.

        A fifth of the list is the line. Below it the page is running on a
        handful of outlets, and presenting that with the same confidence as
        a full pass would be the exact overclaim this module exists to stop.
        """
        return self.read < max(1, self.total_available // 5)


def _cited_names(paths) -> tuple[list[str], list[str]]:
    used: list[str] = []
    unverified: list[str] = []

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
                            if not part:
                                continue
                            resolved = source_list.canonical(part)
                            if resolved is None:
                                if part not in unverified:
                                    unverified.append(part)
                            elif resolved.name not in used:
                                used.append(resolved.name)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for path in paths:
        path = Path(path)
        if path.exists():
            try:
                walk(json.loads(path.read_text()))
            except (json.JSONDecodeError, OSError):
                continue
    return sorted(used), sorted(unverified)


def measure(gameweek: int, root: Path | None = None) -> ResearchRun:
    """Counts what this gameweek's committed research actually cites."""
    root = root or Path(__file__).resolve().parent.parent.parent
    paths = [root / template.format(gw=gameweek) for template in RESEARCH_FILES]
    used, unverified = _cited_names(paths)
    return ResearchRun(
        gameweek=int(gameweek),
        finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        sources_used=used,
        unverified=unverified,
    )


def save(run: ResearchRun, path: Path | None = None) -> None:
    path = path or LOG_PATH
    try:
        existing = json.loads(path.read_text()) if path.exists() else {"runs": {}}
    except (json.JSONDecodeError, OSError):
        existing = {"runs": {}}
    existing.setdefault("runs", {})[str(run.gameweek)] = {
        "finished_at": run.finished_at,
        "sources_used": run.sources_used,
        "unverified": run.unverified,
        "read": run.read,
        "available": run.total_available,
        "notes": run.notes,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(existing, indent=1, ensure_ascii=False))
    except OSError:
        pass


def load(gameweek: int, path: Path | None = None) -> ResearchRun | None:
    path = path or LOG_PATH
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    entry = (payload.get("runs") or {}).get(str(gameweek))
    if not entry:
        return None
    return ResearchRun(
        gameweek=int(gameweek),
        finished_at=str(entry.get("finished_at", "")),
        sources_used=list(entry.get("sources_used") or []),
        unverified=list(entry.get("unverified") or []),
        notes=str(entry.get("notes", "")),
    )
