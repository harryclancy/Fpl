"""Freezes each gameweek's recommendation at the deadline.

Recomputing a gameweek's advice after it has kicked off doesn't refresh it,
it rewrites history. Player stats update live, so by Sunday the model
"knows" who scored on Saturday and will happily recommend them -- advice
that was impossible at the only moment it could have been used.

So the recommendation is written to disk while the deadline is still in
the future, and replayed unchanged once the gameweek goes live. What you
see during the weekend is what the app actually said beforehand, right or
wrong, which is the only version worth showing: it doubles as a record you
can hold the thing to account with.

Storage is a plain JSON file per gameweek. On an ephemeral host the file
may not survive a restart, and a missing snapshot is reported as missing
rather than quietly regenerated from live data -- silently recomputing is
the exact failure this module exists to prevent.
"""
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "snapshots"


@dataclass
class Snapshot:
    """What the app recommended for a gameweek, before it kicked off."""

    gameweek: int
    saved_at: str
    squad_ids: list[int]
    starting_ids: list[int]
    bench_ids: list[int]
    captain_id: int
    vice_captain_id: int
    formation: str
    total_cost: float
    expected_points: float
    player_names: dict[str, str] = field(default_factory=dict)

    @property
    def saved_at_display(self) -> str:
        try:
            stamp = datetime.fromisoformat(self.saved_at)
        except ValueError:
            return self.saved_at
        return stamp.strftime("%a %d %b, %H:%M UTC")


def _path(gameweek: int) -> Path:
    return SNAPSHOT_DIR / f"gw{gameweek}.json"


def load(gameweek: int) -> Snapshot | None:
    path = _path(gameweek)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return Snapshot(**data)
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def save(
    gameweek: int,
    solution,
    names: dict[int, str] | None = None,
    deadline_passed: bool = False,
) -> Snapshot | None:
    """Persists this gameweek's recommendation, if the deadline is ahead.

    The rule that matters is not "write once" -- it's "never write after
    kick-off". Those are different, and the first version got it wrong by
    refusing to overwrite: that locked in whatever the app happened to
    compute days early and threw away every later, better-informed run.
    Late team news is exactly when the advice improves, so a pre-deadline
    rewrite is not a corruption of the record, it *is* the record.

    Once the deadline passes, nothing may be written. That is the point of
    the module: a post-kick-off save would quietly replace real advice
    with something informed by results already in.
    """
    if deadline_passed:
        return load(gameweek)

    snapshot = Snapshot(
        gameweek=int(gameweek),
        saved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        squad_ids=[int(i) for i in solution.squad_ids],
        starting_ids=[int(i) for i in solution.starting_ids],
        bench_ids=[int(i) for i in solution.bench_ids],
        captain_id=int(solution.captain_id),
        vice_captain_id=int(solution.vice_captain_id),
        formation=str(solution.formation),
        total_cost=float(solution.total_cost),
        expected_points=float(solution.expected_points),
        player_names={str(k): str(v) for k, v in (names or {}).items()},
    )
    try:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        _path(gameweek).write_text(json.dumps(asdict(snapshot), indent=2))
    except OSError:
        # A read-only or full filesystem shouldn't take the page down. The
        # live view will report the snapshot as missing, which is honest.
        return None
    return snapshot
