"""Answers "why him and not this other guy?" by actually re-solving.

The honest answer to "why not Bruno?" isn't a paragraph about Bruno. It's
the squad you'd have to build to fit him: who gets dropped to afford him,
and what that trade costs in projected points. That's a question the
optimiser can answer exactly -- force the player in, solve again, and diff
the two squads -- so this module does that rather than generating prose
about it.

The result is a real counterfactual, which is worth more than an opinion.
A player can look obviously worth picking in isolation and still cost you
points once you see the £12.0m has to come out of somewhere.
"""
from dataclasses import dataclass, field

import pandas as pd

from fpl_assistant.analysis import optimiser


@dataclass
class Swap:
    out_name: str
    out_price: float
    in_name: str
    in_price: float


@dataclass
class Answer:
    """A computed response to a question about one player."""

    player_name: str
    in_squad: bool
    headline: str
    detail: list[str] = field(default_factory=list)
    swaps: list[Swap] = field(default_factory=list)
    points_delta: float | None = None
    consensus_case: str | None = None
    consensus_against: str | None = None


def _row(scored: pd.DataFrame, player_id: int) -> pd.Series:
    return scored.set_index("id").loc[player_id]


def _consensus_bits(row: pd.Series) -> tuple[str | None, str | None]:
    case = row.get("consensus_reason")
    against = row.get("consensus_watch_out")
    return (
        str(case) if case is not None and pd.notna(case) else None,
        str(against) if against is not None and pd.notna(against) else None,
    )


def explain_player(
    scored: pd.DataFrame,
    solution: optimiser.SquadSolution,
    player_id: int,
    budget: float = optimiser.DEFAULT_BUDGET,
    template_weight: float = optimiser.TEMPLATE_WEIGHT,
) -> Answer:
    """Why this player is, or isn't, in the recommended squad.

    For a player who missed out, this re-solves the whole squad with them
    forced in. That's the only way to answer the question honestly: the
    cost of a pick is never the player in isolation, it's what you have to
    give up elsewhere to afford them.
    """
    row = _row(scored, player_id)
    name = str(row["web_name"])
    case, against = _consensus_bits(row)
    in_squad = player_id in set(solution.squad_ids)

    if in_squad:
        starting = player_id in set(solution.starting_ids)
        role = "starting" if starting else "on the bench"
        if player_id == solution.captain_id:
            role = "captaining"
        elif player_id == solution.vice_captain_id:
            role = "starting, with the vice-captaincy"

        detail = [
            f"Projected **{row.get('xp_next', 0):.1f} points** next gameweek "
            f"({row.get('xp_horizon', 0):.0f} over the next five) at £{row['price']:.1f}m."
        ]
        if not starting:
            detail.append(
                "He's in the fifteen but not the eleven — the squad needs cheap bench places to "
                "fund the starters, and this is one of them."
            )
        return Answer(
            player_name=name,
            in_squad=True,
            headline=f"**{name} is in the squad**, {role}.",
            detail=detail,
            consensus_case=case,
            consensus_against=against,
        )

    # Not picked. Work out what including him would actually cost.
    try:
        forced = optimiser.optimise_squad(
            scored,
            budget=budget,
            template_weight=template_weight,
            locked_ids=[player_id],
        )
    except Exception as exc:
        return Answer(
            player_name=name,
            in_squad=False,
            headline=f"**{name} isn't in the squad**, and no legal squad can be built around him.",
            detail=[
                f"Forcing him in leaves no valid fifteen within the budget and squad rules ({exc}). "
                f"At £{row['price']:.1f}m that usually means he can't be afforded alongside the "
                f"players already locked in."
            ],
            consensus_case=case,
            consensus_against=against,
        )

    delta = forced.expected_points - solution.expected_points
    dropped = [i for i in solution.squad_ids if i not in set(forced.squad_ids)]
    added = [i for i in forced.squad_ids if i not in set(solution.squad_ids)]

    indexed = scored.set_index("id")

    # Pair each departure with an arrival in the same position. Zipping the
    # two lists in solver order reads as nonsense -- it happily reports a
    # forward being swapped for a midfielder, which never happened; squad
    # quotas are fixed, so every change is position-for-position.
    swaps: list[Swap] = []
    remaining = list(added)
    for out in sorted(dropped, key=lambda i: -float(indexed.loc[i, "price"])):
        position = indexed.loc[out, "position"]
        match = next((i for i in remaining if indexed.loc[i, "position"] == position), None)
        if match is None:
            continue
        remaining.remove(match)
        swaps.append(
            Swap(
                out_name=str(indexed.loc[out, "web_name"]),
                out_price=float(indexed.loc[out, "price"]),
                in_name=str(indexed.loc[match, "web_name"]),
                in_price=float(indexed.loc[match, "price"]),
            )
        )

    # Lead with the swap that brings the asked-about player in. That's the
    # change the question was about; the rest are knock-on downgrades to
    # pay for it, and they only make sense read in that order.
    swaps.sort(key=lambda swap: swap.in_name != name)

    if delta >= -0.5:
        headline = (
            f"**{name} is a genuinely close call** — picking him costs about "
            f"{abs(delta):.1f} projected points, which is inside the model's margin for error."
        )
        verdict = (
            "Close enough that the consensus view below should decide it rather than the "
            "projection. If you rate him, take him."
        )
    elif delta >= -3.0:
        headline = (
            f"**{name} is left out, but it's not clear-cut** — forcing him in costs about "
            f"{abs(delta):.1f} projected points."
        )
        verdict = "A defensible pick if you disagree with the model, but you're paying a little for it."
    else:
        headline = (
            f"**{name} is left out**, and the gap is real: building around him costs about "
            f"{abs(delta):.1f} projected points."
        )
        verdict = "Not just a tie-break — the squad is meaningfully weaker with him in it."

    detail = [
        f"He'd be **£{row['price']:.1f}m** and project **{row.get('xp_next', 0):.1f} points** next "
        f"gameweek. To fit him, here's what the squad would have to give up:"
    ]
    if not swaps:
        detail.append("(He fits without changing anyone else — the difference is purely the budget.)")
    detail.append(verdict)

    return Answer(
        player_name=name,
        in_squad=False,
        headline=headline,
        detail=detail,
        swaps=swaps,
        points_delta=round(delta, 2),
        consensus_case=case,
        consensus_against=against,
    )


def compare_players(scored: pd.DataFrame, left_id: int, right_id: int) -> Answer:
    """Head-to-head: two players, same question, side by side."""
    left, right = _row(scored, left_id), _row(scored, right_id)
    left_name, right_name = str(left["web_name"]), str(right["web_name"])

    left_xp = float(left.get("xp_horizon", 0))
    right_xp = float(right.get("xp_horizon", 0))
    gap = left_xp - right_xp
    winner, loser, margin = (
        (left_name, right_name, gap) if gap >= 0 else (right_name, left_name, -gap)
    )

    if margin < 1.0:
        headline = (
            f"**{left_name} and {right_name} are effectively level** on projection "
            f"({left_xp:.0f} vs {right_xp:.0f} over five gameweeks)."
        )
    else:
        headline = (
            f"**{winner} projects ahead of {loser}** by about {margin:.0f} points over five "
            f"gameweeks ({left_xp:.0f} vs {right_xp:.0f})."
        )

    detail = [
        f"**{left_name}** — £{left['price']:.1f}m · {left.get('xp_next', 0):.1f} pts next GW · "
        f"{left.get('selected_by_percent', 0):.0f}% owned",
        f"**{right_name}** — £{right['price']:.1f}m · {right.get('xp_next', 0):.1f} pts next GW · "
        f"{right.get('selected_by_percent', 0):.0f}% owned",
    ]

    price_gap = float(left["price"]) - float(right["price"])
    if abs(price_gap) >= 0.5:
        dearer, cheaper = (
            (left_name, right_name) if price_gap > 0 else (right_name, left_name)
        )
        detail.append(
            f"{dearer} costs **£{abs(price_gap):.1f}m more**, and that money has to come from "
            f"somewhere else in the squad — which is the real question, not which of them is better."
        )

    left_case, left_against = _consensus_bits(left)
    right_case, right_against = _consensus_bits(right)
    if left_case:
        detail.append(f"**On {left_name}:** {left_case}")
    if left_against:
        detail.append(f"**Against {left_name}:** {left_against}")
    if right_case:
        detail.append(f"**On {right_name}:** {right_case}")
    if right_against:
        detail.append(f"**Against {right_name}:** {right_against}")

    return Answer(
        player_name=f"{left_name} vs {right_name}",
        in_squad=False,
        headline=headline,
        detail=detail,
        points_delta=round(gap, 2),
    )
