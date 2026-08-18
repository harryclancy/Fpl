"""Builds a recommended 15-man squad and the best starting XI from it.

This is advisory, not a true global optimum (that's an integer program) --
it's a greedy heuristic: take the strongest scorer per position, then
repeatedly downgrade the weakest-value pick to a cheaper alternative until
the squad fits the budget. Good enough to recommend, not to bet the house
on.
"""
import pandas as pd

from fpl_assistant.analysis.fixtures import team_fixture_table
from fpl_assistant.analysis.season_state import is_preseason

SQUAD_QUOTAS = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
# Real FPL squads aren't 15 independently-best players -- nobody spends big
# on their bench. Split into a "stars" tier (picked by score, where a
# premium price is the point) and a "bench" tier (picked by minimum price,
# to free up budget for the stars) so a nailed-on premium like Haaland
# doesn't get outcompeted for budget by 14 other players *all* trying to
# be the best individually-scored option in their slot.
STRONG_QUOTA = {"GKP": 1, "DEF": 4, "MID": 4, "FWD": 2}
BENCH_QUOTA = {"GKP": 1, "DEF": 1, "MID": 1, "FWD": 1}
MAX_PER_CLUB = 3
DEFAULT_BUDGET = 100.0

# Valid FPL starting-XI shapes: 1 GKP + (DEF, MID, FWD) summing to 10 outfield.
VALID_FORMATIONS = [
    (d, m, f) for d in range(3, 6) for m in range(2, 6) for f in range(1, 4) if d + m + f == 10
]


def _normalise(series: pd.Series) -> pd.Series:
    lo, hi = series.min(), series.max()
    if pd.isna(lo) or pd.isna(hi) or hi == lo:
        return pd.Series(0.5, index=series.index)
    return (series - lo) / (hi - lo)


def score_players(
    players: pd.DataFrame, fixtures: pd.DataFrame, teams: pd.DataFrame, from_event: int, window: int = 5
) -> pd.DataFrame:
    """Adds `squad_score` and `scoring_basis` columns.

    Preseason (or anytime nobody's played a minute yet this season), form
    and expected-goal-involvement are meaningless zeros for every player,
    so this falls back to price (a decent proxy for underlying quality —
    the market/FPL's own algorithm already priced it in) and early
    ownership (crowd consensus), still weighted by the fixture run.
    """
    df = players[players["status"] == "a"].copy()

    fixture_table = team_fixture_table(fixtures, teams, from_event, window)
    df["fixture_run_difficulty"] = df["team"].map(fixture_table["avg_difficulty"])
    df = df[df["fixture_run_difficulty"].notna()]  # exclude teams with a blank gameweek in the window

    df["fixture_norm"] = _normalise(6 - df["fixture_run_difficulty"])

    if is_preseason(players):
        df["price_norm"] = _normalise(df["price"])
        df["ownership_norm"] = _normalise(df["selected_by_percent"])
        # Price and ownership together are the real signal here -- FPL's own
        # pricing algorithm and tens of thousands of managers' preseason
        # homework both already price in a player's expected explosiveness,
        # which is exactly why a heavily-owned premium (a Haaland-type
        # nailed-on captaincy pick) is "essentially undroppable" in
        # practice even across a moderately tough fixture swing. Fixture
        # difficulty is real but comparatively noisy this early (single
        # early-season FDR ratings, not proven form), so it should break
        # ties between similarly-priced/owned players -- not outweigh
        # price+ownership and knock a clear premium out of the top tier.
        df["squad_score"] = (
            0.55 * df["price_norm"] + 0.30 * df["ownership_norm"] + 0.15 * df["fixture_norm"]
        )
        df["scoring_basis"] = "preseason"
    else:
        df["form_norm"] = _normalise(df["form"])
        df["attack_norm"] = _normalise(df["expected_goal_involvements"])
        df["defense_norm"] = _normalise(-df["expected_goals_conceded"])
        is_attacker = df["position"].isin(["MID", "FWD"])
        df["threat_norm"] = df["attack_norm"].where(is_attacker, df["defense_norm"])
        df["squad_score"] = 0.35 * df["form_norm"] + 0.30 * df["fixture_norm"] + 0.35 * df["threat_norm"]
        df["scoring_basis"] = "form"

    return df.round({"squad_score": 4})


def build_squad(
    scored: pd.DataFrame, budget: float = DEFAULT_BUDGET, max_per_club: int = MAX_PER_CLUB
) -> pd.DataFrame:
    """Budget-respecting 15-man squad selection: fills one slot at a time,
    stars first (attacking positions, since that's where premiums matter
    most), each pick constrained to what's actually affordable given how
    many slots and how much minimum spend the rest of the squad still
    needs -- not "pick the best 15 regardless of budget, then patch it
    afterwards." That patch-it-after approach was tried first and failed
    in a very concrete way: a nailed-on premium like Haaland would get cut
    purely because *everyone* the naive top-score pass wanted was
    similarly expensive, so cutting him looked as reasonable as cutting
    anyone else. Buying stars while the budget is still full, before
    cheaper depth eats into it, avoids ever reaching that situation.
    """
    selected_ids: list[int] = []
    club_counts: dict[int, int] = {}
    remaining_budget = budget
    # Per-position floors, not one global minimum -- goalkeepers, say,
    # rarely go as cheap as the very cheapest player in the whole pool, so
    # a single blanket floor understates what the remaining slots will
    # actually cost and lets earlier picks overspend.
    min_price_by_position = scored.groupby("position")["price"].min()

    def eligible(pool: pd.DataFrame) -> pd.DataFrame:
        return pool[~pool["id"].isin(selected_ids)]

    # Attacking positions first (premiums matter most there), stars before
    # bench within each position.
    slot_plan: list[tuple[str, bool]] = []  # (position, is_star_slot)
    for pos in ["FWD", "MID", "DEF", "GKP"]:
        slot_plan += [(pos, True)] * STRONG_QUOTA[pos]
    for pos in ["FWD", "MID", "DEF", "GKP"]:
        slot_plan += [(pos, False)] * BENCH_QUOTA[pos]

    for i, (pos, is_star) in enumerate(slot_plan):
        remaining_floor = sum(min_price_by_position[p] for p, _ in slot_plan[i + 1 :])
        max_affordable = remaining_budget - remaining_floor

        pool = eligible(scored[(scored["position"] == pos) & (scored["price"] <= max_affordable)])
        pool = pool[pool["team"].map(lambda t: club_counts.get(t, 0)) < max_per_club]
        if pool.empty:
            # Affordability ceiling or club cap too tight for this slot --
            # fall back to the cheapest legal option so the squad still
            # completes, even if it means running slightly over budget.
            pool = eligible(scored[scored["position"] == pos])
            pool = pool[pool["team"].map(lambda t: club_counts.get(t, 0)) < max_per_club]
            if pool.empty:
                continue
            row = pool.sort_values("price").iloc[0]
        else:
            sort_col, ascending = ("squad_score", False) if is_star else ("price", True)
            row = pool.sort_values(sort_col, ascending=ascending).iloc[0]

        selected_ids.append(row["id"])
        club_counts[row["team"]] = club_counts.get(row["team"], 0) + 1
        remaining_budget -= row["price"]

    return scored[scored["id"].isin(selected_ids)].copy()


def best_starting_xi(squad: pd.DataFrame) -> tuple[list[int], list[int], str]:
    """Picks the highest-scoring valid formation from a 15-man squad.
    Returns (starting_ids, bench_ids_ordered_strongest_first, formation_label).
    """
    by_pos = {
        pos: squad[squad["position"] == pos].sort_values("squad_score", ascending=False)
        for pos in SQUAD_QUOTAS
    }
    gk = by_pos["GKP"].iloc[0]

    best_score, best_combo = -1.0, (4, 4, 2)
    for d, m, f in VALID_FORMATIONS:
        if d > len(by_pos["DEF"]) or m > len(by_pos["MID"]) or f > len(by_pos["FWD"]):
            continue
        total = (
            gk["squad_score"]
            + by_pos["DEF"]["squad_score"].iloc[:d].sum()
            + by_pos["MID"]["squad_score"].iloc[:m].sum()
            + by_pos["FWD"]["squad_score"].iloc[:f].sum()
        )
        if total > best_score:
            best_score, best_combo = total, (d, m, f)

    d, m, f = best_combo
    starters = (
        [gk["id"]]
        + by_pos["DEF"]["id"].iloc[:d].tolist()
        + by_pos["MID"]["id"].iloc[:m].tolist()
        + by_pos["FWD"]["id"].iloc[:f].tolist()
    )
    bench = squad[~squad["id"].isin(starters)].sort_values("squad_score", ascending=False)["id"].tolist()
    return starters, bench, f"{d}-{m}-{f}"


def pick_captain(squad: pd.DataFrame, starting_ids: list[int]) -> tuple[int, int]:
    """Captain/vice from the starting XI, preferring attacking returns
    (MID/FWD) over defenders/keepers even if their squad_score is close,
    since armband value comes from goal involvements far more often than
    clean sheets.
    """
    starters = squad[squad["id"].isin(starting_ids)].sort_values("squad_score", ascending=False)
    attackers = starters[starters["position"].isin(["MID", "FWD"])]

    ranked = attackers if len(attackers) >= 2 else starters
    return ranked["id"].iloc[0], ranked["id"].iloc[1]
