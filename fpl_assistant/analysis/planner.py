"""Plans several gameweeks of transfers at once, instead of one at a time.

The weekly optimiser answers "what is the best move *this* week?" and it
answers it correctly. The trouble is that the best move this week is
frequently not the best move, because transfers are a budget spent across
a season and the greedy answer spends it badly in three specific ways:

  1. **It never banks.** A free transfer carried into next week is worth
     more than a marginal upgrade taken now, but a one-week optimiser has
     no way to see next week, so it always finds *something* to buy.
  2. **It can't stage a big move.** Getting a £14m striker in often needs
     two transfers -- sell a midfielder, then sell a defender -- and each
     move looks bad in isolation. Judged one week at a time, the plan that
     ends somewhere excellent never gets started.
  3. **It buys the wrong fixture.** A player with a terrible next game and
     a superb three after it is a poor buy this week and a very good buy
     the week after. Only a planner that knows when the fixtures turn can
     time that.

So this solves all of the gameweeks together: one integer program with a
squad per gameweek, transfers linking consecutive squads, free transfers
accumulating between them, and hits priced at 4 points wherever the plan
chooses to exceed the allowance. The output is a schedule -- hold this
week, double move in three weeks' time -- not a single trade.

What it is not: a promise. Everything past the next deadline is a
projection standing on fixtures, form and fitness that will all have
changed by the time you get there, so the later weeks of a plan are a
direction of travel. The near move is the decision; the rest is the reason
that move is right. Only the first gameweek's transfers are ever presented
as something to actually do.
"""
from dataclasses import dataclass, field

import pandas as pd

from fpl_assistant.analysis.optimiser import (
    BENCH_WEIGHT,
    FORMATION_BOUNDS,
    MAX_PER_CLUB,
    SQUAD_QUOTAS,
    SQUAD_SIZE,
    STARTING_SIZE,
    _formation_label,
)

# How many gameweeks to plan over. Four is a deliberate compromise: long
# enough to cover a fixture swing and to stage a two-transfer move, short
# enough that the projections at the far end are still worth something.
# Beyond about five weeks the model is guessing at team news that hasn't
# happened, and a plan built on guesses looks authoritative while being
# worthless.
DEFAULT_HORIZON = 4

# FPL banks unused free transfers up to this many.
MAX_FREE_TRANSFERS = 5
HIT_COST = 4

# Candidates considered per position, on top of everyone already owned.
# The weekly optimiser can afford the full ~700-player pool; this one
# cannot, because every player becomes three binary variables *per
# gameweek*. Trimming to the plausible upgrades keeps the program solvable
# in seconds. The risk is trimming away the right answer, so the ranking
# used is horizon points -- the same measure the plan is optimising -- and
# everyone currently owned is kept regardless of how badly they rank.
CANDIDATES_PER_POSITION = 12

# Later gameweeks are discounted, for the same reason the single-week
# projection discounts them: you will get to make the decision again with
# better information, so a gain three weeks out is worth less than the
# same gain now. Without this the planner happily takes a hit today to set
# up a speculative gain in gameweek four.
FUTURE_DECAY = 0.88

SOLVER_TIME_LIMIT_SECONDS = 45


def _solver():
    import pulp

    return pulp.PULP_CBC_CMD(msg=0, timeLimit=SOLVER_TIME_LIMIT_SECONDS)


@dataclass
class PlannedWeek:
    """One gameweek of the plan."""

    gameweek: int
    out_ids: list[int]
    in_ids: list[int]
    free_transfers: int
    hits: int
    starting_ids: list[int]
    captain_id: int
    formation: str
    projected_points: float

    @property
    def transfers(self) -> int:
        return len(self.out_ids)

    @property
    def points_cost(self) -> int:
        return self.hits * HIT_COST


@dataclass
class Plan:
    """A multi-gameweek transfer schedule."""

    weeks: list[PlannedWeek]
    total_projected: float
    total_hits: int
    baseline_projected: float
    names: dict[int, str] = field(default_factory=dict)

    @property
    def gain(self) -> float:
        """Projected points above standing pat with the current squad."""
        return round(self.total_projected - self.baseline_projected, 2)

    @property
    def first_move(self) -> PlannedWeek | None:
        return self.weeks[0] if self.weeks else None

    def name(self, player_id: int) -> str:
        return self.names.get(int(player_id), f"#{player_id}")

    def _move_text(self, week: PlannedWeek) -> str:
        outs = ", ".join(self.name(i) for i in week.out_ids)
        ins = ", ".join(self.name(i) for i in week.in_ids)
        text = f"{outs} → {ins}"
        if week.hits:
            text += f" (−{week.points_cost} hit)"
        return text

    @property
    def headline(self) -> str:
        first = self.first_move
        if first is None:
            return "No gameweeks to plan."
        if not first.transfers:
            later = next((w for w in self.weeks[1:] if w.transfers), None)
            if later is None:
                return (
                    "Hold. Nothing in the next few gameweeks beats the squad "
                    "you already have."
                )
            return (
                f"Hold this week and bank the transfer. The plan spends it in "
                f"GW{later.gameweek}: {self._move_text(later)}."
            )
        return f"GW{first.gameweek}: {self._move_text(first)}."

    @property
    def schedule(self) -> list[str]:
        """One line per gameweek, in plain English."""
        lines = []
        for week in self.weeks:
            if not week.transfers:
                banked = min(MAX_FREE_TRANSFERS, week.free_transfers + 1)
                lines.append(
                    f"GW{week.gameweek}: hold — roll to {banked} free transfer"
                    f"{'s' if banked > 1 else ''}. "
                    f"Projected {week.projected_points:.1f}."
                )
            else:
                lines.append(
                    f"GW{week.gameweek}: {self._move_text(week)}. "
                    f"Projected {week.projected_points:.1f}."
                )
        return lines

    @property
    def reasoning(self) -> list[str]:
        """Why the plan is shaped the way it is."""
        notes = []
        holds = [w for w in self.weeks if not w.transfers]
        moves = [w for w in self.weeks if w.transfers]

        if holds and moves:
            first_move = moves[0]
            if holds[0].gameweek < first_move.gameweek:
                notes.append(
                    f"The hold is doing work, not nothing: banking now means "
                    f"GW{first_move.gameweek} has "
                    f"{first_move.free_transfers} free transfers available, so "
                    f"{'that move costs no points' if not first_move.hits else 'the move costs less'}."
                )
        multi = [w for w in moves if w.transfers > 1]
        if multi:
            week = multi[0]
            notes.append(
                f"GW{week.gameweek} is a {week.transfers}-transfer move. Each half "
                "of it looks marginal on its own — the pair is what pays, which is "
                "why a one-week-at-a-time optimiser never finds it."
            )
        if self.total_hits:
            notes.append(
                f"The plan takes {self.total_hits} hit"
                f"{'s' if self.total_hits > 1 else ''} "
                f"({self.total_hits * HIT_COST} points) and still comes out "
                f"{self.gain:+.1f} ahead of holding, which is the only test a hit has to pass."
            )
        elif self.gain > 0:
            notes.append(
                f"No hits anywhere: the whole plan runs on free transfers and is "
                f"still {self.gain:+.1f} points ahead of standing pat."
            )
        notes.append(
            "Only the first move is a decision. The later weeks are the reason it's "
            "the right one, and they get re-planned every gameweek as the projections move."
        )
        return notes


def _horizon_columns(scored: pd.DataFrame, horizon: int) -> list[str]:
    """The per-gameweek projection columns, in gameweek order.

    `expected_points` writes one `xp_gw{n}` column per projected gameweek.
    Selecting them by sorted gameweek number rather than by frame order
    matters: column order is an implementation detail of how the frame was
    built, and planning the weeks out of sequence would silently make the
    transfer chain nonsense.
    """
    columns = []
    for column in scored.columns:
        if not column.startswith("xp_gw"):
            continue
        try:
            columns.append((int(column[5:]), column))
        except ValueError:
            continue
    columns.sort()
    return [column for _, column in columns[:horizon]]


def with_owned_players(
    scored: pd.DataFrame, players: pd.DataFrame, owned_ids
) -> pd.DataFrame:
    """Puts owned players the scoring pass dropped back into the pool, at zero.

    Projections are only computed for players with an available status, so
    an injured or suspended player you own simply vanishes -- and a
    planner that can't see him can't plan around him. Refusing to run is
    the wrong answer too: a squad with an injury is precisely when the
    next few weeks of transfers need thinking about.

    So he comes back with a projection of zero for every gameweek, which
    is both honest and exactly the right incentive. He occupies one of
    your fifteen and scores nothing, so the planner will spend a transfer
    moving him on -- which is what you were going to have to do anyway.
    """
    present = set(scored["id"])
    missing = [int(i) for i in owned_ids if int(i) not in present]
    if not missing:
        return scored

    rows = players[players["id"].isin(missing)]
    if rows.empty:
        return scored

    filled = rows.reindex(columns=scored.columns)
    for column in scored.columns:
        if column in rows.columns:
            filled[column] = rows[column].values
    for column in scored.columns:
        # Numeric only. `xp_basis` is a label ("preseason"/"form"), not a
        # projection, and zeroing it would put a number where every reader
        # expects a string.
        if not pd.api.types.is_numeric_dtype(scored[column]):
            continue
        if column.startswith("xp") or column == "selected_by_percent":
            filled[column] = 0.0
    filled["id"] = rows["id"].values
    return pd.concat([scored, filled], ignore_index=True).set_index("id", drop=False)


def _candidate_pool(
    scored: pd.DataFrame, owned: list[int], per_position: int
) -> pd.DataFrame:
    pool = scored[scored["position"].isin(SQUAD_QUOTAS)].drop_duplicates(subset="id")
    keep = pool[pool["id"].isin(owned)]
    ranked = pool[~pool["id"].isin(owned)].sort_values("xp_horizon", ascending=False)
    top = ranked.groupby("position", group_keys=False).head(per_position)
    return pd.concat([keep, top]).drop_duplicates(subset="id")


def plan_transfers(
    scored: pd.DataFrame,
    current_squad_ids: list[int],
    bank: float = 0.0,
    free_transfers: int = 1,
    horizon: int = DEFAULT_HORIZON,
    max_transfers_per_week: int = 2,
    candidates_per_position: int = CANDIDATES_PER_POSITION,
    hit_cost: int = HIT_COST,
    names: dict[int, str] | None = None,
) -> Plan:
    """Solves all the gameweeks together and returns the schedule.

    Free transfers are modelled as a running balance rather than a fixed
    one per week, because that's how they actually work and it's the whole
    reason holding can be the right call:

        ft[t+1] ≤ ft[t] − used[t] + 1,   ft[t+1] ≤ 5

    Written as upper bounds, not equalities. That's safe because more free
    transfers can only ever help the objective, so the solver pushes each
    balance to its ceiling on its own — which is exactly the `min(5, …)`
    the rules describe, without needing to model a minimum.
    """
    import pulp

    columns = _horizon_columns(scored, horizon)
    if not columns:
        raise RuntimeError(
            "No per-gameweek projections available — expected `xp_gw*` columns."
        )

    pool = _candidate_pool(scored, list(current_squad_ids), candidates_per_position)
    ids = pool["id"].tolist()
    owned = [int(i) for i in current_squad_ids if int(i) in set(ids)]
    if len(owned) != SQUAD_SIZE:
        raise RuntimeError(
            f"Expected {SQUAD_SIZE} owned players in the pool, found {len(owned)}."
        )

    gameweeks = [int(column[5:]) for column in columns]
    periods = list(range(len(columns)))
    points = {
        t: dict(zip(ids, pool[columns[t]].astype(float))) for t in periods
    }
    price = dict(zip(ids, pool["price"].astype(float)))
    position = dict(zip(ids, pool["position"]))
    club = dict(zip(ids, pool["team"]))
    budget = sum(price[i] for i in owned) + bank

    problem = pulp.LpProblem("fpl_multiweek", pulp.LpMaximize)
    squad = pulp.LpVariable.dicts("squad", (ids, periods), cat="Binary")
    start = pulp.LpVariable.dicts("start", (ids, periods), cat="Binary")
    captain = pulp.LpVariable.dicts("captain", (ids, periods), cat="Binary")
    bought = pulp.LpVariable.dicts("in", (ids, periods), cat="Binary")
    sold = pulp.LpVariable.dicts("out", (ids, periods), cat="Binary")
    free = pulp.LpVariable.dicts(
        "free", periods, lowBound=0, upBound=MAX_FREE_TRANSFERS, cat="Integer"
    )
    hits = pulp.LpVariable.dicts("hits", periods, lowBound=0)

    problem += pulp.lpSum(
        (FUTURE_DECAY**t)
        * (
            pulp.lpSum(points[t][i] * start[i][t] for i in ids)
            + pulp.lpSum(points[t][i] * captain[i][t] for i in ids)
            + pulp.lpSum(
                BENCH_WEIGHT * points[t][i] * (squad[i][t] - start[i][t]) for i in ids
            )
            - hit_cost * hits[t]
        )
        for t in periods
    )

    for t in periods:
        problem += pulp.lpSum(squad[i][t] for i in ids) == SQUAD_SIZE
        problem += pulp.lpSum(start[i][t] for i in ids) == STARTING_SIZE
        problem += pulp.lpSum(captain[i][t] for i in ids) == 1
        for i in ids:
            problem += start[i][t] <= squad[i][t]
            problem += captain[i][t] <= start[i][t]
        for pos, quota in SQUAD_QUOTAS.items():
            problem += pulp.lpSum(squad[i][t] for i in ids if position[i] == pos) == quota
        for pos, (low, high) in FORMATION_BOUNDS.items():
            in_pos = [start[i][t] for i in ids if position[i] == pos]
            problem += pulp.lpSum(in_pos) >= low
            problem += pulp.lpSum(in_pos) <= high
        problem += pulp.lpSum(price[i] * squad[i][t] for i in ids) <= budget
        for club_id in set(club.values()):
            problem += pulp.lpSum(squad[i][t] for i in ids if club[i] == club_id) <= MAX_PER_CLUB

        # Squad continuity. A player's membership can only change through a
        # transfer, which is what stops the solver quietly rebuilding the
        # whole fifteen every week for free.
        for i in ids:
            previous = squad[i][t - 1] if t else (1 if i in owned else 0)
            problem += squad[i][t] - previous == bought[i][t] - sold[i][t]
            problem += bought[i][t] + sold[i][t] <= 1

        used = pulp.lpSum(sold[i][t] for i in ids)
        problem += used <= max_transfers_per_week
        problem += hits[t] >= used - free[t]
        if t == 0:
            problem += free[t] == min(free_transfers, MAX_FREE_TRANSFERS)
        else:
            problem += free[t] <= free[t - 1] - pulp.lpSum(sold[i][t - 1] for i in ids) + 1

    status = problem.solve(_solver())
    if pulp.LpStatus[status] not in ("Optimal", "Not Solved"):
        raise RuntimeError(f"Solver returned status {pulp.LpStatus[status]!r}.")

    def chosen(variables) -> bool:
        value = variables.value()
        return bool(value and value > 0.5)

    weeks: list[PlannedWeek] = []
    total = 0.0
    for t in periods:
        starting = [i for i in ids if chosen(start[i][t])]
        squad_ids = [i for i in ids if chosen(squad[i][t])]
        if not starting:
            continue
        captain_id = next(
            (i for i in ids if chosen(captain[i][t])),
            max(starting, key=lambda i: points[t][i]),
        )
        outs = [i for i in ids if chosen(sold[i][t])]
        ins = [i for i in ids if chosen(bought[i][t])]
        available = int(round(free[t].value() or 0))
        taken = max(0, len(outs) - available)
        gross = sum(points[t][i] for i in starting) + points[t][captain_id]
        total += gross - taken * hit_cost
        weeks.append(
            PlannedWeek(
                gameweek=gameweeks[t],
                out_ids=outs,
                in_ids=ins,
                free_transfers=available,
                hits=taken,
                starting_ids=starting,
                captain_id=captain_id,
                formation=_formation_label(pool[pool["id"].isin(squad_ids)], starting),
                projected_points=round(gross - taken * hit_cost, 2),
            )
        )

    return Plan(
        weeks=weeks,
        total_projected=round(total, 2),
        total_hits=sum(w.hits for w in weeks),
        baseline_projected=_hold_baseline(pool, owned, points, periods),
        names=dict(names or {}),
    )


def _hold_baseline(
    pool: pd.DataFrame, owned: list[int], points: dict, periods: list[int]
) -> float:
    """What the current squad scores over the horizon if you make no transfers.

    This is the counterfactual a plan has to beat, and it's the honest one:
    not "the squad as currently lined up" but "the best XI available from
    the players you own, every week". Comparing against a badly-picked XI
    would let the planner take credit for fixing the lineup while claiming
    it as a transfer gain.
    """
    from fpl_assistant.analysis.optimiser import optimise_starting_xi

    held = pool[pool["id"].isin(owned)].copy()
    total = 0.0
    for t in periods:
        column = f"_baseline_{t}"
        held[column] = [points[t].get(int(i), 0.0) for i in held["id"]]
        try:
            starters, _bench, _formation = optimise_starting_xi(held, points_column=column)
        except Exception:
            continue
        lookup = points[t]
        # The captain double has to be in the baseline too, or the plan
        # gets credited with points that holding would also have scored.
        best = max((lookup.get(int(i), 0.0) for i in starters), default=0.0)
        total += sum(lookup.get(int(i), 0.0) for i in starters) + best
    return round(total, 2)
