"""The players we are NOT picking, and why.

A squad view answers "who?" and never answers "why not him?". That gap is
where trust in a recommender actually goes: you scan the fifteen, notice
that a name half the game owns is missing, and you have no idea whether
the app weighed him and declined or simply never saw him. Those are very
different things, and from the outside they look identical.

So this module works the omission side deliberately. It picks the players
whose absence is genuinely surprising -- the template, the analysts'
picks, and anyone the raw projection rated highly -- and states the
reason, ordered by how much explaining the absence needs:

  1. a club-level expert verdict ("avoid this club until the run clears")
  2. a player-level expert verdict, or a split in expert opinion
  3. unavailability
  4. the price: what fitting him in would cost, computed by re-solving

Only the last of those needs the optimiser, and it's the weakest kind of
answer, so it's the fallback rather than the default. "He'd cost you 3.2
projected points" is true but unsatisfying; "every analyst is saying avoid
this club until GW9, and here's their reasoning" is the answer you
actually wanted.
"""
from dataclasses import dataclass, field

import pandas as pd

from fpl_assistant.analysis import explain, optimiser

# Ownership at which not owning a player is itself a decision. Below this
# his absence needs no defending -- most of the game is missing too.
NOTABLE_OWNERSHIP = 15.0
DEFAULT_LIMIT = 6

# Reason categories, most-explanatory first. The order is the ranking.
CATEGORY_ORDER = ["club", "expert", "disputed", "unavailable", "cost"]


@dataclass
class Omission:
    """One player who isn't in the squad, and the reason."""

    player_id: int
    name: str
    team: str
    position: str
    price: float
    ownership: float
    category: str
    headline: str
    detail: str
    sources: str | None = None
    points_cost: float | None = None
    swaps: list = field(default_factory=list)

    @property
    def rank(self) -> int:
        return CATEGORY_ORDER.index(self.category) if self.category in CATEGORY_ORDER else 99


def _text(row: pd.Series, column: str) -> str | None:
    value = row.get(column)
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if pd.isna(value) if not isinstance(value, str) else not value.strip():
        return None
    return str(value)


def candidates(scored: pd.DataFrame, squad_ids: set[int]) -> pd.DataFrame:
    """Players whose absence a reasonable manager would want explained.

    Three separate reasons to qualify, because they catch different
    mistakes. Ownership catches "everyone else has him". A consensus tier
    catches "the analysts named him". A high pre-consensus projection
    catches the case that matters most for auditing the app itself: the
    model rated him and something later overrode it. If that override is
    wrong, this is where it becomes visible instead of silently shaping
    the squad.
    """
    pool = scored[~scored["id"].isin(squad_ids)].copy()
    if pool.empty:
        return pool

    ownership = pd.to_numeric(pool.get("selected_by_percent", 0), errors="coerce").fillna(0.0)
    tiered = pool.get("consensus_tier")
    raw_xp = pd.to_numeric(
        pool.get("xp_pre_consensus", pool.get("xp_horizon", 0)), errors="coerce"
    ).fillna(0.0)

    is_template = ownership >= NOTABLE_OWNERSHIP
    is_named = tiered.notna() if tiered is not None else pd.Series(False, index=pool.index)
    # Top of the raw projection, before any expert adjustment. These are
    # the deliberate swerves.
    is_rated = raw_xp >= raw_xp.quantile(0.985) if len(pool) > 20 else raw_xp > raw_xp.max()

    pool = pool[is_template | is_named | is_rated]
    pool = pool.assign(_own=ownership.reindex(pool.index), _raw=raw_xp.reindex(pool.index))
    return pool.sort_values(["_own", "_raw"], ascending=False)


def _categorical_reason(row: pd.Series) -> tuple[str, str, str, str | None] | None:
    """A reason that doesn't need the optimiser, if there is one.

    Returns (category, headline, detail, sources).
    """
    name = str(row["web_name"])

    status = str(row.get("status", "a") or "a")
    if status != "a":
        news = _text(row, "news") or "flagged as not fully available"
        return (
            "unavailable",
            f"{name} isn't available",
            f"He's {news.rstrip('.').lower()}. Nothing else about the pick matters until that clears.",
            None,
        )

    stance = _text(row, "club_stance")
    if stance in {"avoid", "caution"}:
        club = str(row.get("team_short_name") or "his club")
        until = row.get("club_stance_until")
        window = f" until GW{int(until)}" if pd.notna(until) else ""
        verb = "are steering clear of" if stance == "avoid" else "are wary of"
        return (
            "club",
            f"{name} is left out because of {club}, not because of him",
            f"The analysts {verb} {club} assets{window}. "
            + (_text(row, "club_stance_case") or ""),
            None,
        )

    dissent = _text(row, "consensus_dissent")
    if dissent:
        return (
            "disputed",
            f"{name} splits expert opinion",
            dissent,
            _text(row, "consensus_sources"),
        )

    if _text(row, "consensus_tier") == "avoid":
        return (
            "expert",
            f"{name} is an expert avoid",
            _text(row, "consensus_watch_out") or _text(row, "consensus_reason") or "",
            _text(row, "consensus_sources"),
        )

    return None


def notable_omissions(
    scored: pd.DataFrame,
    solution: optimiser.SquadSolution,
    limit: int = DEFAULT_LIMIT,
    budget: float = optimiser.DEFAULT_BUDGET,
    template_weight: float = optimiser.TEMPLATE_WEIGHT,
    max_resolves: int = 3,
) -> list[Omission]:
    """The most surprising absences from the squad, each with a reason.

    `max_resolves` caps how many counterfactual squad solves run, because
    each one is a fresh ILP. Players with a categorical reason never need
    one, so the cap only bites on the "he's simply expensive" cases where
    the answer is least interesting anyway.
    """
    squad_ids = set(solution.squad_ids)
    pool = candidates(scored, squad_ids)
    if pool.empty:
        return []

    found: list[Omission] = []
    resolves_left = max_resolves

    for _, row in pool.iterrows():
        if len(found) >= limit:
            break

        base = dict(
            player_id=int(row["id"]),
            name=str(row["web_name"]),
            team=str(row.get("team_short_name") or ""),
            position=str(row.get("position") or ""),
            price=float(row.get("price", 0) or 0),
            ownership=float(row.get("_own", 0) or 0),
        )

        categorical = _categorical_reason(row)
        if categorical:
            category, headline, detail, sources = categorical
            found.append(Omission(**base, category=category, headline=headline,
                                  detail=detail, sources=sources))
            continue

        # No categorical reason, so the answer is about the money. That
        # needs a counterfactual solve, and solves are rationed.
        #
        # When the ration runs out the player is still listed, with a
        # vaguer reason. Dropping him instead would recreate precisely the
        # failure this module exists to fix: a player the app considered
        # and rejected vanishing from the page as though it had never
        # heard of him. A weaker answer is not the same as no answer.
        answer = None
        if resolves_left > 0:
            resolves_left -= 1
            try:
                answer = explain.explain_player(
                    scored, solution, int(row["id"]), budget=budget,
                    template_weight=template_weight,
                )
            except Exception:
                answer = None
            if answer is not None and answer.in_squad:
                continue

        cost = (
            abs(answer.points_delta)
            if answer is not None and answer.points_delta is not None
            else None
        )
        if cost is None:
            detail = (
                "He was considered and came up short on value rather than on merit — the budget "
                "he'd take up projects more points spread across other positions. Ask about him "
                "by name below and I'll re-solve the squad around him and show the exact cost."
            )
        elif cost < 0.5:
            detail = (
                "He's essentially a coin-flip with who we picked instead — inside the model's "
                "margin for error. If you rate him, take him; the projection isn't the reason "
                "he's out."
            )
        else:
            detail = (
                "Nothing is wrong with the player. It's the money: the budget he'd absorb buys "
                "more points elsewhere in the squad."
            )
        found.append(
            Omission(
                **base,
                category="cost",
                headline=(
                    f"{base['name']} is a genuinely close call"
                    if cost is not None and cost < 0.5
                    else f"{base['name']} costs more than he returns here"
                ),
                detail=detail,
                sources=None,
                points_cost=round(cost, 1) if cost is not None else None,
                swaps=answer.swaps if answer is not None else [],
            )
        )

    found.sort(key=lambda o: (o.rank, -o.ownership))
    return found
