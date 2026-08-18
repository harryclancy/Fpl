"""Optimal squad selection as an integer linear program.

The previous selector was a greedy heuristic: fill the best player into
each slot in turn, patch up the budget afterwards. Greedy is fast and
intuitive and it is *wrong* in a specific, costly way -- it can't see that
paying up for one elite striker is affordable only if you also downgrade a
midfielder three picks later, because it has already committed by then.
That blind spot is exactly what caused a nailed-on premium to be dropped
from the recommended squad despite being the near-unanimous pick.

Squad selection is a knapsack problem with side constraints, and knapsack
problems have an exact solution method. Formulating it as an ILP and
handing it to a solver returns the provably best squad for the projected
points it's given, in well under a second for the ~700-player pool. No
tiering hacks, no budget-overshoot fallback, no ordering heuristics.

The formulation, per player i:

    squad[i]   ∈ {0,1}   in the 15-man squad
    start[i]   ∈ {0,1}   in the starting XI
    captain[i] ∈ {0,1}   wears the armband

    maximise   Σ xp[i]·start[i]                 (the XI actually scores)
             + Σ xp_next[i]·captain[i]          (armband doubles one starter)
             + β · Σ xp[i]·(squad[i] − start[i])(bench has option value)

    subject to  start[i] ≤ squad[i],  captain[i] ≤ start[i]
                Σ squad = 15,  Σ start = 11,  Σ captain = 1
                position quotas on squad; valid formation on start
                Σ price[i]·squad[i] ≤ budget
                Σ squad[i] per club ≤ 3

Optimising the *starting XI* rather than the squad total is the key
modelling choice. Points come from the eleven who play; bench players earn
only through autosubs, so weighting them at full value would buy expensive
bench cover nobody benefits from -- which is how you end up with the
classic beginner mistake of a £6m fourth substitute.
"""
from dataclasses import dataclass, field

import pandas as pd

SQUAD_SIZE = 15
STARTING_SIZE = 11
SQUAD_QUOTAS = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
FORMATION_BOUNDS = {"GKP": (1, 1), "DEF": (3, 5), "MID": (2, 5), "FWD": (1, 3)}
MAX_PER_CLUB = 3
DEFAULT_BUDGET = 100.0

# What a bench place is worth relative to a starting place. Not zero --
# autosubs are real, and a bench that never plays is still insurance
# against a late injury or a blank -- but well below 1, because most weeks
# most of the bench scores nothing for you.
BENCH_WEIGHT = 0.12

# --- Rank strategy ------------------------------------------------------
# Maximising expected points and maximising *rank* are different problems,
# and conflating them is the single most common way a technically correct
# optimiser gives bad FPL advice.
#
# Your rank depends on your score relative to everyone else's. If a player
# is owned by 70% of managers and hauls, the 30% who don't own him all lose
# rank together -- even though skipping him may have been the higher
# expected-points call. That asymmetry doesn't show up anywhere in a pure
# xP objective, because in expectation the field's ownership is a constant
# that cancels out. It only bites in the variance, which is precisely where
# rank lives.
#
# So ownership enters as an explicit, tunable term rather than being baked
# into the projection:
#   positive weight -> shadow the template, capping downside (protect rank)
#   zero            -> pure expected points, ownership-blind
#   negative weight -> favour differentials, buying upside (chase rank)
#
# Points per 1% of ownership. Deliberately small: this should break ties
# between similar players and stop the optimiser fading a near-universal
# pick, not override the projection outright.
TEMPLATE_WEIGHT = 0.035
# Above this ownership a player is "template" -- the field is effectively
# long them, so not owning them is itself an active bet.
TEMPLATE_OWNERSHIP = 40.0


@dataclass
class SquadSolution:
    """Result of an optimisation run."""

    squad_ids: list[int]
    starting_ids: list[int]
    bench_ids: list[int]
    captain_id: int
    vice_captain_id: int
    formation: str
    total_cost: float
    expected_points: float
    optimal: bool = True
    notes: list[str] = field(default_factory=list)


def _formation_label(squad: pd.DataFrame, starting_ids: list[int]) -> str:
    starters = squad[squad["id"].isin(starting_ids)]
    counts = starters["position"].value_counts()
    return f"{counts.get('DEF', 0)}-{counts.get('MID', 0)}-{counts.get('FWD', 0)}"


def optimise_squad(
    scored: pd.DataFrame,
    budget: float = DEFAULT_BUDGET,
    max_per_club: int = MAX_PER_CLUB,
    points_column: str = "xp_horizon",
    captain_column: str = "xp_captain",
    locked_ids: list[int] | None = None,
    banned_ids: list[int] | None = None,
    template_weight: float = TEMPLATE_WEIGHT,
) -> SquadSolution:
    """Solves for the highest expected-points squad within the FPL rules.

    `locked_ids` forces players into the squad (use for players you've
    already committed to and won't sell); `banned_ids` excludes them.

    `template_weight` trades expected points against rank risk: positive
    shadows the highly-owned template, zero is ownership-blind, negative
    hunts differentials. See TEMPLATE_WEIGHT above for why this can't just
    be folded into the projection.

    Raises RuntimeError if the problem is infeasible -- which, given a
    realistic player pool, means the constraints themselves are impossible
    (e.g. a budget too small to field 15 players), not that the solver gave
    up. Callers wanting graceful degradation should catch it and fall back.
    """
    import pulp

    pool = scored[scored["position"].isin(SQUAD_QUOTAS)].copy()
    if banned_ids:
        pool = pool[~pool["id"].isin(banned_ids)]
    pool = pool.drop_duplicates(subset="id")

    if len(pool) < SQUAD_SIZE:
        raise RuntimeError(f"Only {len(pool)} eligible players — need at least {SQUAD_SIZE}.")

    ids = pool["id"].tolist()
    points = dict(zip(ids, pool[points_column].astype(float)))
    captain_points = dict(
        zip(ids, pool.get(captain_column, pool[points_column]).astype(float))
    )
    price = dict(zip(ids, pool["price"].astype(float)))
    position = dict(zip(ids, pool["position"]))
    club = dict(zip(ids, pool["team"]))

    # Rank-risk term. Only ownership *above* the template threshold counts:
    # below it, not owning someone costs you nothing relative to the field,
    # so there's no rank asymmetry to price in.
    ownership = pd.to_numeric(pool.get("selected_by_percent", 0), errors="coerce").fillna(0.0)
    template_edge = dict(zip(ids, (ownership - TEMPLATE_OWNERSHIP).clip(lower=0.0)))

    problem = pulp.LpProblem("fpl_squad", pulp.LpMaximize)
    squad = pulp.LpVariable.dicts("squad", ids, cat="Binary")
    start = pulp.LpVariable.dicts("start", ids, cat="Binary")
    captain = pulp.LpVariable.dicts("captain", ids, cat="Binary")

    # Objective: starting XI at full value, captain counted a second time
    # (that's what doubling means), bench at a heavy discount.
    problem += (
        pulp.lpSum(points[i] * start[i] for i in ids)
        + pulp.lpSum(captain_points[i] * captain[i] for i in ids)
        + pulp.lpSum(BENCH_WEIGHT * points[i] * (squad[i] - start[i]) for i in ids)
        + pulp.lpSum(template_weight * template_edge[i] * squad[i] for i in ids)
    )

    problem += pulp.lpSum(squad[i] for i in ids) == SQUAD_SIZE
    problem += pulp.lpSum(start[i] for i in ids) == STARTING_SIZE
    problem += pulp.lpSum(captain[i] for i in ids) == 1

    for i in ids:
        problem += start[i] <= squad[i]
        problem += captain[i] <= start[i]

    for pos, quota in SQUAD_QUOTAS.items():
        problem += pulp.lpSum(squad[i] for i in ids if position[i] == pos) == quota

    for pos, (low, high) in FORMATION_BOUNDS.items():
        in_pos = [start[i] for i in ids if position[i] == pos]
        problem += pulp.lpSum(in_pos) >= low
        problem += pulp.lpSum(in_pos) <= high

    problem += pulp.lpSum(price[i] * squad[i] for i in ids) <= budget

    for club_id in set(club.values()):
        problem += pulp.lpSum(squad[i] for i in ids if club[i] == club_id) <= max_per_club

    for locked in locked_ids or []:
        if locked in squad:
            problem += squad[locked] == 1

    status = problem.solve(pulp.PULP_CBC_CMD(msg=0))
    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(f"Solver returned status {pulp.LpStatus[status]!r}.")

    chosen = [i for i in ids if squad[i].value() and squad[i].value() > 0.5]
    starting = [i for i in ids if start[i].value() and start[i].value() > 0.5]
    captain_id = next(i for i in ids if captain[i].value() and captain[i].value() > 0.5)

    bench = [i for i in chosen if i not in starting]
    # Bench order matters for autosubs: strongest first, since that's who
    # comes on when a starter doesn't play. The reserve keeper is pinned
    # last because they can only ever replace the other keeper.
    bench.sort(key=lambda i: (position[i] == "GKP", -points[i]))

    squad_df = pool[pool["id"].isin(chosen)]
    # Vice-captain: best remaining starter, so the armband still lands
    # somewhere sensible if the captain is a late withdrawal.
    vice_id = max(
        (i for i in starting if i != captain_id),
        key=lambda i: captain_points[i],
    )

    expected = sum(points[i] for i in starting) + captain_points[captain_id]

    return SquadSolution(
        squad_ids=chosen,
        starting_ids=starting,
        bench_ids=bench,
        captain_id=captain_id,
        vice_captain_id=vice_id,
        formation=_formation_label(squad_df, starting),
        total_cost=round(sum(price[i] for i in chosen), 1),
        expected_points=round(expected, 2),
        optimal=True,
    )


def optimise_starting_xi(
    squad: pd.DataFrame, points_column: str = "xp_next"
) -> tuple[list[int], list[int], str]:
    """Best legal XI out of a squad you already own.

    Separate from `optimise_squad` because the everyday question isn't
    "what squad should I have bought" but "given what I own, who starts
    this week" -- and that one is small enough to solve by enumerating the
    handful of valid formations directly, with no solver dependency.
    """
    by_position = {
        pos: squad[squad["position"] == pos].sort_values(points_column, ascending=False)
        for pos in SQUAD_QUOTAS
    }
    if by_position["GKP"].empty:
        raise ValueError("Squad has no goalkeeper.")

    best_total, best_shape = float("-inf"), None
    for d in range(*(FORMATION_BOUNDS["DEF"][0], FORMATION_BOUNDS["DEF"][1] + 1)):
        for m in range(*(FORMATION_BOUNDS["MID"][0], FORMATION_BOUNDS["MID"][1] + 1)):
            f = 10 - d - m
            if not FORMATION_BOUNDS["FWD"][0] <= f <= FORMATION_BOUNDS["FWD"][1]:
                continue
            if d > len(by_position["DEF"]) or m > len(by_position["MID"]) or f > len(by_position["FWD"]):
                continue
            total = (
                by_position["GKP"][points_column].iloc[0]
                + by_position["DEF"][points_column].iloc[:d].sum()
                + by_position["MID"][points_column].iloc[:m].sum()
                + by_position["FWD"][points_column].iloc[:f].sum()
            )
            if total > best_total:
                best_total, best_shape = total, (d, m, f)

    if best_shape is None:
        raise ValueError("No valid formation available from this squad.")

    d, m, f = best_shape
    starters = (
        by_position["GKP"]["id"].iloc[:1].tolist()
        + by_position["DEF"]["id"].iloc[:d].tolist()
        + by_position["MID"]["id"].iloc[:m].tolist()
        + by_position["FWD"]["id"].iloc[:f].tolist()
    )
    bench = squad[~squad["id"].isin(starters)].sort_values(points_column, ascending=False)
    bench_ids = sorted(
        bench["id"].tolist(),
        key=lambda i: (squad.set_index("id").loc[i, "position"] == "GKP",),
    )
    return starters, bench_ids, f"{d}-{m}-{f}"
