"""Squad and starting-XI recommendations.

This module is now a thin facade over two specialists:

  * `expected_points` projects how many FPL points each player will score
  * `optimiser` solves for the best legal squad given those projections

It used to do both jobs itself with a greedy heuristic over a normalised
0-1 score. Both halves of that were limiting. A 0-1 score can rank players
but can't answer "is this £13.0m striker worth two £6.5m midfielders",
because the numbers aren't on a scale where arithmetic is meaningful --
and a greedy fill can't see that affording an elite pick depends on a
downgrade it hasn't made yet, which is how a near-unanimous premium ended
up being dropped from the recommended squad entirely.

The old function names are kept so existing callers keep working, but they
now delegate to the new engine.
"""
from dataclasses import dataclass, field

import pandas as pd

from fpl_assistant.analysis import captain_call, consensus, explain, optimiser
from fpl_assistant.analysis import history as history_analysis
from fpl_assistant.analysis.expected_points import DEFAULT_HORIZON, expected_points
from fpl_assistant.analysis.fixtures import team_fixture_table
from fpl_assistant.analysis.optimiser import (
    DEFAULT_BUDGET,
    MAX_PER_CLUB,
    SQUAD_QUOTAS,
    SquadSolution,
)

__all__ = [
    "RebuiltSquad",
    "rebuild_without",
    "DEFAULT_BUDGET",
    "MAX_PER_CLUB",
    "SQUAD_QUOTAS",
    "SquadSolution",
    "best_starting_xi",
    "build_squad",
    "pick_captain",
    "recommend_squad",
    "score_players",
]

# Valid FPL starting-XI shapes: 1 GKP + (DEF, MID, FWD) summing to 10 outfield.
VALID_FORMATIONS = [
    (d, m, f) for d in range(3, 6) for m in range(2, 6) for f in range(1, 4) if d + m + f == 10
]


def score_players(
    players: pd.DataFrame,
    fixtures: pd.DataFrame,
    teams: pd.DataFrame,
    from_event: int,
    window: int = DEFAULT_HORIZON,
) -> pd.DataFrame:
    """Attaches expected-points projections to every available player.

    Adds the full `xp_*` family (see expected_points) plus two columns kept
    for backwards compatibility with older callers:
      `squad_score`   — now literally the horizon xP, not a 0-1 index
      `scoring_basis` — "preseason" or "form"
    """
    available = players[players["status"] == "a"].copy()

    fixture_table = team_fixture_table(fixtures, teams, from_event, window)
    available["fixture_run_difficulty"] = available["team"].map(fixture_table["avg_difficulty"])
    # Teams with a blank gameweek inside the window have no meaningful
    # average difficulty; the xP model handles blanks properly per-gameweek,
    # but the rationale text still reads this column, so fill rather than drop.
    available["fixture_run_difficulty"] = available["fixture_run_difficulty"].fillna(3.0)

    # Attach what each player did in previous seasons before projecting.
    # Without it, the projection has nothing to fall back on when this
    # season is one gameweek old -- which is how the most-owned striker in
    # the game got sold on the back of a single blank.
    available = history_analysis.attach(available)

    team_context = consensus.load_team_context()
    projected = expected_points(
        available, fixtures, teams, from_event, horizon=window,
        team_context=team_context,
    )

    # Fold in what analysts and the wider community are actually saying.
    # This is not decoration on top of the projection -- it moves the
    # numbers the optimiser maximises, because the reasoning that decides
    # real FPL weeks (who just got penalties, who the manager confirmed
    # starts, which "easy" fixture is a trap) is invisible to a model
    # reading per-90 rates.
    projected = consensus.annotate(projected, from_event)

    # Club-level verdicts apply to every player at the club, which is the
    # whole point: "avoid Bournemouth until the fixtures turn" is advice
    # about the club, and the player it most needs to stop you buying is
    # the cheap defender no analyst bothered to name. Previously that
    # verdict lived only as prose on one player's card, so the optimiser
    # never saw it and kept selecting the club's other defenders.
    projected = consensus.annotate_clubs(projected, team_context, from_event, window)

    expert_bonus = projected["consensus_bonus"] + projected["club_stance_bonus"]
    projected["expert_bonus"] = expert_bonus
    projected["xp_pre_consensus"] = projected["xp_horizon"]
    projected["xp_horizon"] = projected["xp_horizon"] + expert_bonus
    projected["xp_next"] = projected["xp_next"] + expert_bonus / window
    projected["xp_captain"] = projected["xp_captain"] + expert_bonus / window

    projected["squad_score"] = projected["xp_horizon"]
    projected["scoring_basis"] = projected["xp_basis"]
    return projected


def recommend_squad(
    scored: pd.DataFrame,
    budget: float = DEFAULT_BUDGET,
    max_per_club: int = MAX_PER_CLUB,
    template_weight: float = optimiser.TEMPLATE_WEIGHT,
    locked_ids: list[int] | None = None,
    banned_ids: list[int] | None = None,
) -> SquadSolution:
    """The primary entry point: squad, XI, captain and vice in one solve.

    Solving all four together matters -- the best XI depends on which 15
    you bought, and whether a premium is affordable depends on who's
    captaining. Picking them in sequence, as the old code did, throws that
    interdependence away.

    Falls back to a greedy build if the solver is unavailable (PuLP ships
    its own CBC binary, but a locked-down host could still block it) so the
    deployed app degrades rather than breaking.
    """
    # Consensus must-haves are locked in, not merely favoured. When ~70% of
    # managers and effectively every analyst have landed on the same
    # player, "the model ranked him fourth" is evidence the model is
    # missing something they can see -- not grounds to leave him out.
    # Fading a near-universal pick is an active bet against the field, and
    # that should be a human's call, never a side effect of a formula.
    locked = list(locked_ids or []) + consensus.must_have_ids(scored)
    banned = list(banned_ids or []) + consensus.avoid_ids(scored)

    def solve(with_locks: bool) -> SquadSolution:
        return optimiser.optimise_squad(
            scored,
            budget=budget,
            max_per_club=max_per_club,
            template_weight=template_weight,
            locked_ids=sorted(set(locked)) if with_locks else None,
            banned_ids=sorted(set(banned)),
        )

    try:
        return solve(with_locks=True)
    except Exception as lock_error:
        first_error = lock_error

    # Too many locks can over-constrain the squad into infeasibility -- a
    # consensus naming several expensive must-haves, or locks colliding
    # with the three-per-club cap. Retry without them before abandoning
    # exact optimisation: a provably optimal squad that merely *weights*
    # the consensus is better than a heuristic one that honours it, and the
    # bonuses are still in the projections either way.
    if locked:
        try:
            solution = solve(with_locks=False)
            solution.notes.append(
                "Consensus must-haves couldn't all be locked in together within the budget and "
                f"squad rules ({first_error}) — they're still weighted heavily in the projections."
            )
            return solution
        except Exception as unlocked_error:
            first_error = unlocked_error

    squad = _greedy_squad(scored, budget=budget, max_per_club=max_per_club)
    starters, bench, formation = best_starting_xi(squad)
    captain_id, vice_id = pick_captain(squad, starters)
    return SquadSolution(
        squad_ids=squad["id"].tolist(),
        starting_ids=starters,
        bench_ids=bench,
        captain_id=captain_id,
        vice_captain_id=vice_id,
        formation=formation,
        total_cost=round(float(squad["price"].sum()), 1),
        expected_points=round(float(squad.loc[squad["id"].isin(starters), "squad_score"].sum()), 2),
        optimal=False,
        notes=[f"Exact optimiser unavailable ({first_error}); used a greedy fallback."],
    )


@dataclass
class RebuiltSquad:
    """The suggested squad, re-solved after dropping players you vetoed."""

    solution: SquadSolution
    removed_ids: list[int]
    swaps: list = field(default_factory=list)
    kept_ids: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    points_delta: float = 0.0


def rebuild_without(
    scored: pd.DataFrame,
    solution: SquadSolution,
    remove_ids: list[int],
    budget: float = DEFAULT_BUDGET,
    max_per_club: int = MAX_PER_CLUB,
    template_weight: float = optimiser.TEMPLATE_WEIGHT,
) -> RebuiltSquad:
    """The recommended squad minus players you don't want, re-solved.

    Taking a suggested squad wholesale is rare -- there's nearly always one
    player you won't own, whether because you've watched him play, you
    already own an alternative, or you simply don't fancy it. Deleting him
    from the list and leaving a hole is not the same as re-solving without
    him: the money he freed changes what the rest of the squad should be,
    and the best replacement is often not the next-best player in his
    position.

    So the vetoed players are banned and everyone else is locked, which
    asks the solver the actual question: given that these thirteen stay
    and he can't be picked, what's the best legal squad?

    Locking that many players can over-constrain the solve -- the freed
    budget may not buy a legal replacement inside the three-per-club cap.
    Rather than fail, the constraints are relaxed in order: first release
    the bench (which exists to be cheap and is the least costly thing to
    rearrange), then release everything and simply ban the vetoed players.
    Each fallback is reported, because a squad that quietly changed more
    than you asked it to is worse than one that tells you it had to.
    """
    removed = [pid for pid in remove_ids if pid in set(solution.squad_ids)]
    if not removed:
        return RebuiltSquad(solution=solution, removed_ids=[], kept_ids=list(solution.squad_ids))

    keep_all = [pid for pid in solution.squad_ids if pid not in set(removed)]
    keep_starters = [pid for pid in solution.starting_ids if pid not in set(removed)]

    attempts = [
        (keep_all, None),
        (
            keep_starters,
            "Couldn't keep the bench intact as well, so the bench was rebuilt too — it's the "
            "cheapest part of the squad and the least costly thing to rearrange.",
        ),
        (
            [],
            "Keeping the rest of the squad locked left no legal fifteen, so it was re-solved "
            "from scratch without your removals. More has changed than you asked for.",
        ),
    ]

    last_error: Exception | None = None
    for locked, note in attempts:
        try:
            rebuilt = optimiser.optimise_squad(
                scored,
                budget=budget,
                max_per_club=max_per_club,
                template_weight=template_weight,
                locked_ids=locked or None,
                banned_ids=removed,
            )
        except Exception as error:
            last_error = error
            continue

        dropped = [pid for pid in solution.squad_ids if pid not in set(rebuilt.squad_ids)]
        added = [pid for pid in rebuilt.squad_ids if pid not in set(solution.squad_ids)]
        return RebuiltSquad(
            solution=rebuilt,
            removed_ids=removed,
            swaps=explain.pair_swaps(scored, dropped, added),
            kept_ids=[pid for pid in solution.squad_ids if pid in set(rebuilt.squad_ids)],
            notes=[note] if note else [],
            points_delta=round(rebuilt.expected_points - solution.expected_points, 2),
        )

    raise RuntimeError(
        f"No legal squad can be built without those players ({last_error})."
    )


def build_squad(
    scored: pd.DataFrame, budget: float = DEFAULT_BUDGET, max_per_club: int = MAX_PER_CLUB
) -> pd.DataFrame:
    """The recommended 15, as a DataFrame. Prefer `recommend_squad`, which
    also returns the XI/captain the same solve chose.
    """
    solution = recommend_squad(scored, budget=budget, max_per_club=max_per_club)
    return scored[scored["id"].isin(solution.squad_ids)].copy()


def best_starting_xi(squad: pd.DataFrame) -> tuple[list[int], list[int], str]:
    """Best legal XI from a 15-man squad.
    Returns (starting_ids, bench_ids_strongest_first, formation_label).
    """
    points_column = "xp_next" if "xp_next" in squad.columns else "squad_score"
    return optimiser.optimise_starting_xi(squad, points_column=points_column)


def pick_captain(squad: pd.DataFrame, starting_ids: list[int]) -> tuple[int, int]:
    """Captain and vice from the starting XI.

    Restricted to attacking positions, which is not a stylistic preference
    but a correction of a category error. The armband doubles a result,
    and doubling rewards the tail of the distribution -- so ranking on a
    mean projection treats a defender who collects a clean sheet and
    appearance points most weeks as equivalent to a forward with a real
    chance of fifteen. It isn't, and that equivalence is how a centre-back
    ended up being recommended as captain.

    The scenario model already ranks defenders below attackers on its own,
    because their ceiling is capped and they blank more often. This guard
    exists because "usually ranks lower" is not "never wins", and one odd
    gameweek where a defender's projection spikes should not be able to
    produce advice that reads as broken.

    Falls back to the whole XI only if it contains no attacker at all,
    which no legal formation allows -- but a caller passing a partial
    squad shouldn't get an exception instead of an answer.
    """
    points_column = next(
        (c for c in ("xp_captain", "xp_next", "squad_score") if c in squad.columns), "squad_score"
    )
    starters = squad[squad["id"].isin(starting_ids)]
    if len(starters) < 2:
        raise ValueError("Need at least two starters to pick a captain and vice.")

    attackers = starters[starters["position"].isin(captain_call.ARMBAND_POSITIONS)]
    eligible = attackers if len(attackers) >= 2 else starters
    ranked = eligible.sort_values(points_column, ascending=False)
    return ranked["id"].iloc[0], ranked["id"].iloc[1]


# --- Fallback -----------------------------------------------------------

_STRONG_QUOTA = {"GKP": 1, "DEF": 4, "MID": 4, "FWD": 2}
_BENCH_QUOTA = {"GKP": 1, "DEF": 1, "MID": 1, "FWD": 1}


def _greedy_squad(
    scored: pd.DataFrame, budget: float = DEFAULT_BUDGET, max_per_club: int = MAX_PER_CLUB
) -> pd.DataFrame:
    """Heuristic squad build, used only when the exact solver can't run.

    Fills stars first (attacking positions, where premiums matter most) and
    cheap bench slots last, capping each pick by what the remaining slots
    still need. Not optimal -- that's the whole reason the ILP exists -- but
    it always returns a legal-shaped 15 so the app keeps working.
    """
    points_column = "squad_score" if "squad_score" in scored.columns else "xp_horizon"
    selected_ids: list[int] = []
    club_counts: dict[int, int] = {}
    remaining_budget = budget
    min_price_by_position = scored.groupby("position")["price"].min()

    slot_plan: list[tuple[str, bool]] = []
    for pos in ["FWD", "MID", "DEF", "GKP"]:
        slot_plan += [(pos, True)] * _STRONG_QUOTA[pos]
    for pos in ["FWD", "MID", "DEF", "GKP"]:
        slot_plan += [(pos, False)] * _BENCH_QUOTA[pos]

    for i, (pos, is_star) in enumerate(slot_plan):
        remaining_floor = sum(min_price_by_position.get(p, 4.0) for p, _ in slot_plan[i + 1 :])
        max_affordable = remaining_budget - remaining_floor

        available = scored[~scored["id"].isin(selected_ids) & (scored["position"] == pos)]
        available = available[available["team"].map(lambda t: club_counts.get(t, 0)) < max_per_club]

        pool = available[available["price"] <= max_affordable]
        if pool.empty:
            if available.empty:
                continue
            row = available.sort_values("price").iloc[0]
        else:
            sort_col, ascending = (points_column, False) if is_star else ("price", True)
            row = pool.sort_values(sort_col, ascending=ascending).iloc[0]

        selected_ids.append(row["id"])
        club_counts[row["team"]] = club_counts.get(row["team"], 0) + 1
        remaining_budget -= row["price"]

    return scored[scored["id"].isin(selected_ids)].copy()
