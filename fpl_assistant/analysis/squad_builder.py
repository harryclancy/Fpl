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
import pandas as pd

from fpl_assistant.analysis import consensus, optimiser
from fpl_assistant.analysis.expected_points import DEFAULT_HORIZON, expected_points
from fpl_assistant.analysis.fixtures import team_fixture_table
from fpl_assistant.analysis.optimiser import (
    DEFAULT_BUDGET,
    MAX_PER_CLUB,
    SQUAD_QUOTAS,
    SquadSolution,
)

__all__ = [
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

    projected = expected_points(
        available, fixtures, teams, from_event, horizon=window,
        team_context=consensus.load_team_context(),
    )

    # Fold in what analysts and the wider community are actually saying.
    # This is not decoration on top of the projection -- it moves the
    # numbers the optimiser maximises, because the reasoning that decides
    # real FPL weeks (who just got penalties, who the manager confirmed
    # starts, which "easy" fixture is a trap) is invisible to a model
    # reading per-90 rates.
    projected = consensus.annotate(projected, from_event)
    projected["xp_pre_consensus"] = projected["xp_horizon"]
    projected["xp_horizon"] = projected["xp_horizon"] + projected["consensus_bonus"]
    projected["xp_next"] = projected["xp_next"] + projected["consensus_bonus"] / window
    projected["xp_captain"] = projected["xp_captain"] + projected["consensus_bonus"] / window

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

    Ranked on next-gameweek xP rather than the multi-week horizon: the
    armband is a one-week decision, so a great fixture this weekend should
    outweigh a good run four weeks out.
    """
    points_column = next(
        (c for c in ("xp_captain", "xp_next", "squad_score") if c in squad.columns), "squad_score"
    )
    starters = squad[squad["id"].isin(starting_ids)].sort_values(points_column, ascending=False)
    if len(starters) < 2:
        raise ValueError("Need at least two starters to pick a captain and vice.")
    return starters["id"].iloc[0], starters["id"].iloc[1]


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
