"""Marks the app's own homework.

Every other module in here is an opinion about the future. This one is the
only module that finds out whether the opinions were any good, by taking a
snapshot -- the recommendation frozen before the deadline -- and laying it
next to what actually happened.

That ordering is the whole point. Scoring advice against results you can
already see is trivial and worthless; scoring advice that was *committed
in writing before kick-off* is the only version that means anything. The
snapshot exists precisely so this comparison is honest, and the accuracy
report is what makes the snapshot worth keeping.

Three separate questions get answered, because they fail independently:

  1. Was the *decision* good?  Did the recommended XI beat the average
     manager, and did the armband go on the right player?
  2. Was the *projection* good?  Projected points against actual points,
     per player -- bias (are we systematically high?) and error (how far
     off, in either direction?).
  3. *Where* is it wrong?  A model can have near-zero bias overall while
     being badly wrong in both directions -- flattering defenders and
     underrating forwards, say. Aggregate accuracy hides that; the
     per-position and per-player breakdowns are where a fixable problem
     actually shows up.

A model that is consistently 1.5 points high on everyone is not broken --
it's miscalibrated, and it still ranks players correctly, which is all the
optimiser needs. A model that is right on average but wrong about *which*
players is much worse, and only the breakdown tells them apart.
"""
from dataclasses import dataclass, field

from fpl_assistant.analysis import snapshots

# A gameweek's advice is only worth scoring once the football has been
# played. Anything below this and the "actuals" are half a gameweek of
# results being compared to a full gameweek of projections, which makes
# the model look far worse than it is.
MIN_MINUTES_FOR_COMPLETE = 0

# What counts as a meaningfully wrong projection for one player, in
# points. Below this, the miss is noise: expected points are an average
# over outcomes that never actually occur -- nobody scores 4.3 -- so small
# per-player errors are the model working, not failing.
NOTABLE_MISS = 4.0

# Valid formations: (defenders, midfielders, forwards). One keeper always.
FORMATIONS = [
    (d, m, f)
    for d in range(3, 6)
    for m in range(2, 6)
    for f in range(1, 4)
    if d + m + f == 10
]


@dataclass
class PlayerResult:
    """One player's projection against what they actually did."""

    player_id: int
    name: str
    position: str
    projected: float
    actual: int
    minutes: int
    started: bool
    captain: bool

    @property
    def error(self) -> float:
        """Actual minus projected. Positive means the model was too low."""
        return round(self.actual - self.projected, 2)

    @property
    def blanked(self) -> bool:
        return self.actual <= 2

    @property
    def hauled(self) -> bool:
        return self.actual >= 10


@dataclass
class GameweekScore:
    """How one gameweek's recommendation actually turned out."""

    gameweek: int
    players: list[PlayerResult]
    xi_points: int
    bench_points: int
    captain_id: int
    captain_actual: int
    best_captain_id: int | None
    best_captain_actual: int
    hindsight_xi_points: int
    average_entry_score: float | None = None
    projected_xi: float = 0.0

    @property
    def captain_cost(self) -> int:
        """Points given up by not captaining the best starter."""
        return max(0, self.best_captain_actual - self.captain_actual)

    @property
    def captain_was_best(self) -> bool:
        return self.best_captain_id is not None and self.captain_id == self.best_captain_id

    @property
    def bench_cost(self) -> int:
        """Points left on the bench by picking the wrong eleven.

        Measured against the best legal XI from the same fifteen, chosen
        with hindsight. This is not a fair standard -- nobody picks their
        XI knowing the results -- so treat it as a ceiling, not a target.
        A small number here means the selection was defensible.
        """
        return max(0, self.hindsight_xi_points - self.xi_points)

    @property
    def vs_average(self) -> float | None:
        if self.average_entry_score is None:
            return None
        return round(self.xi_points - self.average_entry_score, 1)

    @property
    def projection_error(self) -> float:
        """Actual XI score minus what the XI was projected to score."""
        return round(self.xi_points - self.projected_xi, 2)

    @property
    def verdict(self) -> str:
        parts = []
        beat = self.vs_average
        if beat is None:
            parts.append(f"The recommended XI scored {self.xi_points}.")
        elif beat > 0:
            parts.append(
                f"The recommended XI scored {self.xi_points}, "
                f"{beat:.0f} above the average manager."
            )
        elif beat < 0:
            parts.append(
                f"The recommended XI scored {self.xi_points}, "
                f"{abs(beat):.0f} below the average manager."
            )
        else:
            parts.append(f"The recommended XI scored {self.xi_points}, exactly average.")

        if self.captain_was_best:
            parts.append("The armband went on the right player.")
        elif self.captain_cost:
            parts.append(f"The captaincy cost {self.captain_cost} points.")

        if self.bench_cost:
            parts.append(f"A further {self.bench_cost} sat on the bench.")
        return " ".join(parts)


@dataclass
class Calibration:
    """Whether the projections themselves are trustworthy, across gameweeks."""

    gameweeks: list[int]
    sample: int
    bias: float
    mean_absolute_error: float
    by_position: dict[str, dict[str, float]] = field(default_factory=dict)
    worst_overrated: list[PlayerResult] = field(default_factory=list)
    worst_underrated: list[PlayerResult] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if not self.sample:
            return "No finished gameweeks with a saved snapshot yet — nothing to score."
        direction = "high" if self.bias < 0 else "low"
        line = (
            f"Across {self.sample} player-gameweeks the projections run "
            f"{abs(self.bias):.2f} points {direction} on average, "
            f"missing by {self.mean_absolute_error:.2f} either way."
        )
        if abs(self.bias) < 0.5:
            return line + " That is well calibrated — the level is right."
        return (
            line
            + f" Everything is being projected {direction}, which shifts the"
            " level but mostly preserves the ranking the optimiser cares about."
        )

    @property
    def position_notes(self) -> list[str]:
        """Where the model is wrong in a way the overall bias hides."""
        notes = []
        for position, stats in sorted(
            self.by_position.items(), key=lambda kv: -abs(kv[1]["bias"])
        ):
            # Three is the smallest honest sample, and it has to be
            # allowed: a squad carries exactly three forwards, so a higher
            # bar would silently never report on them from a single
            # gameweek -- the position most likely to be mispriced.
            if abs(stats["bias"]) < 0.5 or stats["sample"] < 3:
                continue
            direction = "overrated" if stats["bias"] < 0 else "underrated"
            notes.append(
                f"{position}: {direction} by {abs(stats['bias']):.2f} points a game "
                f"across {int(stats['sample'])} projections."
            )
        return notes


def actuals_from_live(live: dict) -> dict[int, dict]:
    """Flattens the live endpoint into `{player_id: stats}`.

    The endpoint nests each player's numbers under `stats` alongside an
    `explain` block breaking the score into its components. Only the
    totals are needed here.
    """
    out: dict[int, dict] = {}
    for element in live.get("elements", []) or []:
        try:
            out[int(element["id"])] = dict(element.get("stats") or {})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _best_xi(players: list[PlayerResult]) -> int:
    """Highest-scoring legal XI from the fifteen, with hindsight.

    Exhaustive over the nine valid formations rather than greedy, because
    greedy gets this wrong: taking the best defenders first can leave you
    unable to field enough forwards.
    """
    by_position: dict[str, list[int]] = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for player in players:
        if player.position in by_position:
            by_position[player.position].append(player.actual)
    for scores in by_position.values():
        scores.sort(reverse=True)

    if not by_position["GKP"]:
        return 0

    best = 0
    for defenders, midfielders, forwards in FORMATIONS:
        counts = {"DEF": defenders, "MID": midfielders, "FWD": forwards}
        if any(len(by_position[pos]) < need for pos, need in counts.items()):
            continue
        total = by_position["GKP"][0] + sum(
            sum(by_position[pos][:need]) for pos, need in counts.items()
        )
        best = max(best, total)
    return best


def score_gameweek(
    snapshot: snapshots.Snapshot,
    actuals: dict[int, dict],
    positions: dict[int, str] | None = None,
    average_entry_score: float | None = None,
) -> GameweekScore:
    """Compares one frozen recommendation against the results.

    Missing actuals are treated as zero, not skipped. A player who did not
    appear in the live data did not score, and quietly dropping them would
    let the model take credit for projecting points it never delivered.
    """
    positions = positions or {}
    starting = set(int(i) for i in snapshot.starting_ids)
    captain_id = int(snapshot.captain_id)

    players: list[PlayerResult] = []
    for pid in snapshot.squad_ids:
        pid = int(pid)
        stats = actuals.get(pid, {})
        players.append(
            PlayerResult(
                player_id=pid,
                name=snapshot.player_names.get(str(pid), f"#{pid}"),
                position=positions.get(pid, "?"),
                projected=float(snapshot.projected.get(str(pid), 0.0)),
                actual=int(stats.get("total_points", 0) or 0),
                minutes=int(stats.get("minutes", 0) or 0),
                started=pid in starting,
                captain=pid == captain_id,
            )
        )

    lookup = {p.player_id: p for p in players}
    xi = [p for p in players if p.started]
    bench = [p for p in players if not p.started]

    captain_actual = lookup[captain_id].actual if captain_id in lookup else 0
    xi_points = sum(p.actual for p in xi) + captain_actual

    # The best armband is judged among the players who actually started,
    # because that is the choice that was available: you cannot captain a
    # player you also left on the bench.
    best_captain = max(xi, key=lambda p: p.actual, default=None)

    # Hindsight includes doubling the best scorer in the best XI, so the
    # comparison is like for like -- the recommended XI also gets its
    # captain doubled.
    hindsight = _best_xi(players)
    hindsight_best_single = max((p.actual for p in players), default=0)

    return GameweekScore(
        gameweek=int(snapshot.gameweek),
        players=players,
        xi_points=xi_points,
        bench_points=sum(p.actual for p in bench),
        captain_id=captain_id,
        captain_actual=captain_actual,
        best_captain_id=best_captain.player_id if best_captain else None,
        best_captain_actual=best_captain.actual if best_captain else 0,
        hindsight_xi_points=hindsight + hindsight_best_single,
        average_entry_score=average_entry_score,
        projected_xi=round(
            sum(p.projected for p in xi)
            + (lookup[captain_id].projected if captain_id in lookup else 0.0),
            2,
        ),
    )


def calibrate(scores: list[GameweekScore]) -> Calibration:
    """Turns per-gameweek results into a verdict on the projections.

    Only players who actually featured are counted. A projection of 5.0
    for someone who was dropped or injured out on the morning of the game
    is a team-news failure, not a scoring-model failure, and mixing the
    two makes the model look badly pessimistic while hiding the real
    problem.
    """
    graded = [
        player
        for score in scores
        for player in score.players
        if player.minutes > MIN_MINUTES_FOR_COMPLETE
    ]
    if not graded:
        return Calibration(
            gameweeks=[s.gameweek for s in scores],
            sample=0,
            bias=0.0,
            mean_absolute_error=0.0,
        )

    errors = [p.error for p in graded]
    bias = sum(errors) / len(errors)
    mae = sum(abs(e) for e in errors) / len(errors)

    by_position: dict[str, dict[str, float]] = {}
    for position in ("GKP", "DEF", "MID", "FWD"):
        subset = [p for p in graded if p.position == position]
        if not subset:
            continue
        by_position[position] = {
            "sample": float(len(subset)),
            "bias": round(sum(p.error for p in subset) / len(subset), 2),
            "mean_absolute_error": round(
                sum(abs(p.error) for p in subset) / len(subset), 2
            ),
        }

    ranked = sorted(graded, key=lambda p: p.error)
    return Calibration(
        gameweeks=[s.gameweek for s in scores],
        sample=len(graded),
        bias=round(bias, 2),
        mean_absolute_error=round(mae, 2),
        by_position=by_position,
        worst_overrated=[p for p in ranked if p.error <= -NOTABLE_MISS][:5],
        worst_underrated=[p for p in reversed(ranked) if p.error >= NOTABLE_MISS][:5],
    )


def score_history(
    gameweeks,
    fetch_live,
    positions: dict[int, str] | None = None,
    averages: dict[int, float] | None = None,
) -> list[GameweekScore]:
    """Scores every gameweek that has both a snapshot and results.

    Fetching is injected rather than imported so this is testable without
    the network, and so a single failing gameweek can't take down the
    whole report -- a missing snapshot or an endpoint hiccup skips that
    week and the rest still score.
    """
    averages = averages or {}
    out: list[GameweekScore] = []
    for gameweek in gameweeks:
        snapshot = snapshots.load(int(gameweek))
        if snapshot is None:
            continue
        try:
            actuals = actuals_from_live(fetch_live(int(gameweek)))
        except Exception:
            continue
        if not actuals:
            continue
        out.append(
            score_gameweek(
                snapshot,
                actuals,
                positions=positions,
                average_entry_score=averages.get(int(gameweek)),
            )
        )
    return out
