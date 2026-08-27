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

from fpl_assistant.analysis import consensus, explain, optimiser

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
    # The evidence, kept separate from the prose so the page can show the
    # numbers and the quotes as numbers and quotes rather than dissolving
    # them into a paragraph.
    stats: list[str] = field(default_factory=list)
    voices: list[tuple[str, str]] = field(default_factory=list)
    # The specific objections people are raising about him. This section
    # asks "why isn't he in?" and the honest answer is usually not a
    # points differential -- it's that the community has a concrete
    # reason, and quoting it beats paraphrasing it.
    against: list[tuple[str, str]] = field(default_factory=list)
    instead: str | None = None

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


def _num(row: pd.Series, column: str) -> float | None:
    value = pd.to_numeric(row.get(column), errors="coerce")
    return None if value is None or pd.isna(value) else float(value)


def _derived_stats(row: pd.Series) -> list[str]:
    """Hard numbers pulled from the live data for any player at all.

    The researched file covers the dozen or so players analysts wrote
    about. Everyone else was getting a sentence of prose and nothing to
    check it against, which is the same complaint in a different place:
    a verdict with no evidence attached is just an assertion.
    """
    facts: list[str] = []

    next_gw, horizon = _num(row, "xp_next"), _num(row, "xp_horizon")
    if next_gw is not None:
        line = f"Projected {next_gw:.1f} pts next gameweek"
        if horizon is not None:
            line += f", {horizon:.0f} over the next five"
        facts.append(line)

    price = _num(row, "price")
    if price:
        facts.append(f"£{price:.1f}m" + (
            f" — {next_gw / price:.2f} projected pts per £m" if next_gw and price else ""
        ))

    own = _num(row, "selected_by_percent")
    if own is not None:
        facts.append(f"{own:.1f}% owned")

    minutes, starts = _num(row, "minutes"), _num(row, "starts")
    if minutes:
        line = f"{minutes:.0f} minutes played"
        if starts:
            line += f" across {starts:.0f} starts"
        facts.append(line)

    ppg = _num(row, "points_per_game")
    if ppg:
        facts.append(f"{ppg:.1f} points per game")

    form = _num(row, "form")
    if form:
        facts.append(f"Form {form:.1f}")

    position = str(row.get("position") or "")
    if position in {"MID", "FWD"}:
        xg, xa = _num(row, "expected_goals_per_90"), _num(row, "expected_assists_per_90")
        if xg is not None and xa is not None and (xg or xa):
            facts.append(f"{xg + xa:.2f} expected goal involvements per 90 ({xg:.2f} xG, {xa:.2f} xA)")
    else:
        xgc = _num(row, "expected_goals_conceded_per_90")
        if xgc:
            facts.append(f"{xgc:.2f} expected goals conceded per 90 behind him")

    fdr = _num(row, "fixture_run_difficulty")
    if fdr:
        facts.append(f"Average fixture difficulty {fdr:.1f} over the next five")

    return facts


def _picked_instead(scored: pd.DataFrame, squad_ids: set[int], row: pd.Series) -> str | None:
    """The squad player occupying the slot this one would take.

    "Why not him?" is a comparison, and answering it without naming the
    alternative leaves the reader to go and find it themselves. The
    closest comparison is the squad player in the same position at the
    nearest price, because that is the swap actually on the table.
    """
    position = row.get("position")
    price = _num(row, "price")
    if position is None or price is None:
        return None

    squad = scored[scored["id"].isin(squad_ids) & (scored["position"] == position)]
    if squad.empty:
        return None

    prices = pd.to_numeric(squad["price"], errors="coerce")
    nearest = squad.loc[(prices - price).abs().idxmin()]
    their_xp = _num(nearest, "xp_next")
    mine_xp = _num(row, "xp_next")

    line = f"**{nearest['web_name']}** ({nearest.get('team_short_name', '')}, £{_num(nearest, 'price'):.1f}m)"
    if their_xp is not None and mine_xp is not None:
        line += f" is in that slot on {their_xp:.1f} projected pts, against {mine_xp:.1f} for him"
    return line


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
            _text(row, "club_stance_sources"),
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

        # Evidence first, and the same evidence regardless of which reason
        # ends up applying. Researched numbers where they exist, live ones
        # where they don't -- every verdict on this page should come with
        # something the reader can check it against.
        researched = consensus.key_stats(row)
        base = dict(
            player_id=int(row["id"]),
            name=str(row["web_name"]),
            team=str(row.get("team_short_name") or ""),
            position=str(row.get("position") or ""),
            price=float(row.get("price", 0) or 0),
            ownership=float(row.get("_own", 0) or 0),
            stats=(researched + _derived_stats(row))[:9],
            voices=consensus.voices(row),
            against=consensus.arguments_against(row),
            instead=_picked_instead(scored, squad_ids, row),
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
        # The prose names the actual comparison rather than gesturing at
        # "the budget". A reason you can't check is not a reason.
        against = f" {base['instead']}." if base["instead"] else ""
        if cost is None:
            detail = (
                f"He was weighed and came up short on value rather than on merit.{against} "
                f"Ask about him by name below and the squad gets re-solved around him, with the "
                f"exact cost and every knock-on downgrade it forces."
            )
        elif cost < 0.5:
            detail = (
                f"Genuinely a coin-flip — building the squad around him instead costs about "
                f"{cost:.1f} projected points, which is inside the model's margin for error.{against} "
                f"If you rate him, take him; the projection is not what's keeping him out."
            )
        else:
            detail = (
                f"Nothing is wrong with the player — it's what the money does elsewhere. Forcing "
                f"him in costs about {cost:.1f} projected points once the squad is rebuilt around "
                f"the price.{against}"
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
