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

from fpl_assistant.analysis import consensus, optimiser, scenarios


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
    club_verdict: str | None = None
    dissent: str | None = None
    stats: list[str] = field(default_factory=list)
    voices: list[tuple[str, str]] = field(default_factory=list)


def pair_swaps(scored: pd.DataFrame, dropped: list[int], added: list[int]) -> list[Swap]:
    """Pair each departure with the arrival that replaced it.

    Position-for-position, most expensive departure first. Zipping the two
    lists in solver order reads as nonsense -- it happily reports a forward
    being swapped for a midfielder, which never happened; squad quotas are
    fixed, so every change is position-for-position.
    """
    indexed = scored.set_index("id") if "id" in scored.columns else scored
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
    return swaps


def _row(scored: pd.DataFrame, player_id: int) -> pd.Series:
    return scored.set_index("id").loc[player_id]


def _text(row: pd.Series, column: str) -> str | None:
    """A non-empty string from a column, or None. NaN and missing columns
    both come back as None rather than the string "nan"."""
    value = row.get(column)
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _consensus_bits(row: pd.Series) -> tuple[str | None, str | None]:
    case = row.get("consensus_reason")
    against = row.get("consensus_watch_out")
    return (
        str(case) if case is not None and pd.notna(case) else None,
        str(against) if against is not None and pd.notna(against) else None,
    )


def _club_verdict(row: pd.Series) -> str | None:
    """The club-level expert verdict, phrased for a direct question.

    "Why not him?" is very often not about him at all -- it's that every
    analyst is saying to avoid his club until the fixtures turn. Answering
    that question with a points differential, while the actual reason sits
    unmentioned in another column, is technically accurate and useless.
    """
    stance = _text(row, "club_stance")
    if stance not in {"avoid", "caution"}:
        return None
    club = str(row.get("team_short_name") or "his club")
    until = row.get("club_stance_until")
    window = f" until GW{int(until)}" if pd.notna(until) else ""
    lead = (
        f"The analysts are steering clear of {club} assets{window}"
        if stance == "avoid"
        else f"The analysts are wary of {club} assets{window}"
    )
    return f"{lead}. {_text(row, 'club_stance_case') or ''}".strip()


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
    club_verdict = _club_verdict(row)
    dissent = _text(row, "consensus_dissent")
    stats = consensus.key_stats(row)
    voices = consensus.voices(row)
    try:
        forecast = scenarios.narrate(scenarios.outcome_for(row, name))
    except Exception:
        forecast = None
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
        if forecast:
            detail.append(f"**What could happen:** {forecast}")
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
            club_verdict=club_verdict,
            dissent=dissent,
            stats=stats,
            voices=voices,
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
            club_verdict=club_verdict,
            dissent=dissent,
            stats=stats,
            voices=voices,
        )

    delta = forced.expected_points - solution.expected_points
    dropped = [i for i in solution.squad_ids if i not in set(forced.squad_ids)]
    added = [i for i in forced.squad_ids if i not in set(solution.squad_ids)]

    indexed = scored.set_index("id")

    swaps = pair_swaps(scored, dropped, added)

    # Lead with the swap that brings the asked-about player in. That's the
    # change the question was about; the rest are knock-on downgrades to
    # pay for it, and they only make sense read in that order.
    swaps.sort(key=lambda swap: swap.in_name != name)

    if forecast:
        detail_prefix = [f"**What could happen if you took him:** {forecast}"]
    else:
        detail_prefix = []

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

    detail = detail_prefix + [
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
        club_verdict=club_verdict,
        dissent=dissent,
        stats=stats,
        voices=voices,
    )


def _n(row: pd.Series, column: str, default: float = 0.0) -> float:
    value = pd.to_numeric(row.get(column), errors="coerce")
    return default if value is None or pd.isna(value) else float(value)


def _driver_lines(left: pd.Series, right: pd.Series, left_name: str, right_name: str) -> list[str]:
    """Why one projects ahead of the other, lever by lever.

    Reports only the levers that actually separate them, largest gap
    first, so the deciding factor is the first thing read rather than
    something to be inferred from a wall of parity.
    """
    # (rank, magnitude, text). Rank 0 is a cause -- minutes, threat,
    # fixtures, clean sheets -- and rank 1 is a consequence. Points per £m
    # is a real reason to prefer someone and it is downstream of the
    # others, so leading with it answers "which is better value" when the
    # question asked was "why is he ahead".
    findings: list[tuple[int, float, str]] = []

    def rate(row):
        return _n(row, "xg_match") + _n(row, "xa_match")

    # --- minutes ---
    minutes_gap = _n(left, "expected_minutes") - _n(right, "expected_minutes")
    if abs(minutes_gap) >= 8:
        more, less = (left_name, right_name) if minutes_gap > 0 else (right_name, left_name)
        high, low = (left, right) if minutes_gap > 0 else (right, left)
        findings.append((
            0, abs(minutes_gap) / 10,
            f"**Minutes.** {more} is projected for {_n(high,'expected_minutes'):.0f} minutes "
            f"against {_n(low,'expected_minutes'):.0f} for {less} "
            f"({_n(high,'p_start')*100:.0f}% v {_n(low,'p_start')*100:.0f}% likely to start). "
            f"Everything else in the projection sits downstream of this.",
        ))

    # --- attacking rate ---
    rate_gap = rate(left) - rate(right)
    if abs(rate_gap) >= 0.06:
        better, worse = (left_name, right_name) if rate_gap > 0 else (right_name, left_name)
        high, low = (left, right) if rate_gap > 0 else (right, left)
        findings.append((
            0, abs(rate_gap) * 12,
            f"**Attacking threat.** {better} is worth {rate(high):.2f} expected goal "
            f"involvements this gameweek against {rate(low):.2f} for {worse} — "
            f"{rate(high) - rate(low):+.2f} in his favour, before anything else is counted.",
        ))

    # --- fixture ---
    fixture_gap = _n(left, "fixture_multiplier", 1.0) - _n(right, "fixture_multiplier", 1.0)
    if abs(fixture_gap) >= 0.06:
        better, worse = (left_name, right_name) if fixture_gap > 0 else (right_name, left_name)
        high, low = (left, right) if fixture_gap > 0 else (right, left)
        findings.append((
            0, abs(fixture_gap) * 8,
            f"**Fixtures.** {better}'s run scores {_n(high,'fixture_multiplier',1.0):.2f} against "
            f"{_n(low,'fixture_multiplier',1.0):.2f} for {worse} — the opponents, not the players, "
            f"and it's the part most likely to have flipped by next month.",
        ))

    # --- clean sheets, where they pay ---
    if str(left.get("position")) in ("GKP", "DEF") or str(right.get("position")) in ("GKP", "DEF"):
        cs_gap = _n(left, "p_clean_sheet") - _n(right, "p_clean_sheet")
        if abs(cs_gap) >= 0.05:
            better, worse = (left_name, right_name) if cs_gap > 0 else (right_name, left_name)
            high, low = (left, right) if cs_gap > 0 else (right, left)
            findings.append((
                0, abs(cs_gap) * 10,
                f"**Clean sheets.** {better}'s side keeps one "
                f"{_n(high,'p_clean_sheet')*100:.0f}% of the time against "
                f"{_n(low,'p_clean_sheet')*100:.0f}% for {worse}'s.",
            ))

    # --- value ---
    value_gap = _n(left, "xp_per_million") - _n(right, "xp_per_million")
    if abs(value_gap) >= 0.15:
        better, worse = (left_name, right_name) if value_gap > 0 else (right_name, left_name)
        high, low = (left, right) if value_gap > 0 else (right, left)
        findings.append((
            1, abs(value_gap) * 3,
            f"**Value.** {better} returns {_n(high,'xp_per_million'):.2f} projected points per "
            f"£m against {_n(low,'xp_per_million'):.2f} for {worse} — which is the number that "
            f"decides it once the rest of the squad has to be paid for.",
        ))

    # --- availability ---
    for name, row, other_name, other in ((left_name, left, right_name, right),
                                         (right_name, right, left_name, left)):
        news = row.get("news")
        if isinstance(news, str) and news.strip() and not (
            isinstance(other.get("news"), str) and other["news"].strip()
        ):
            findings.append((
                0, 5.0,
                f"**{name} is carrying a flag** and {other_name} isn't: {news.strip()}",
            ))

    findings.sort(key=lambda item: (item[0], -item[1]))
    return [text for _, _, text in findings]


def _verdict_line(
    left, right, left_name, right_name, gap, left_outcome, right_outcome
) -> str:
    """A recommendation, not a summary.

    A comparison that lays out both sides and then declines to say which
    one it would pick has done the easy half of the job. Where the numbers
    genuinely don't separate them it says that instead -- but it says it
    as a finding, not as a hedge.
    """
    winner, loser = (left_name, right_name) if gap >= 0 else (right_name, left_name)
    win_row, lose_row = (left, right) if gap >= 0 else (right, left)
    win_out, lose_out = (
        (left_outcome, right_outcome) if gap >= 0 else (right_outcome, left_outcome)
    )
    margin = abs(gap)
    price_gap = float(win_row["price"]) - float(lose_row["price"])

    if margin < 1.0:
        line = (
            f"**Too close to call on projection** — {margin:.1f} points over five gameweeks is "
            f"inside the model's error. "
        )
        if price_gap > 0.3:
            line += (
                f"So take {loser}: he's £{price_gap:.1f}m cheaper for the same expected return, "
                f"and that money does more elsewhere than the difference between these two ever will."
            )
        elif price_gap < -0.3:
            line += (
                f"So take {winner}: he's £{abs(price_gap):.1f}m cheaper for the same expected "
                f"return."
            )
        elif win_out and lose_out and abs(win_out.p_haul - lose_out.p_haul) >= 0.04:
            upside = win_out if win_out.p_haul > lose_out.p_haul else lose_out
            line += (
                f"Split them on shape instead: {upside.player_name} has the bigger ceiling, so "
                f"he's the pick if you need to make up ground and the wrong one if you're "
                f"protecting a lead."
            )
        else:
            line += "Pick on whichever fixture you trust more — the numbers genuinely don't choose."
        return line

    line = (
        f"**{winner} is the pick**, by about {margin:.0f} projected points over five gameweeks"
    )
    if price_gap > 0.3:
        line += f", and he costs £{price_gap:.1f}m more to get it"
    elif price_gap < -0.3:
        line += f", and he's £{abs(price_gap):.1f}m cheaper as well, which settles it"
    line += ". "

    if win_out and lose_out:
        if win_out.p_no_show >= 0.15:
            line += (
                f"The caveat is minutes: there's a {win_out.p_no_show * 100:.0f}% chance he "
                f"doesn't play, so this is a pick you'd want to see team news on. "
            )
        elif lose_out.p_no_show >= 0.15:
            line += (
                f"It's reinforced by minutes: {loser} has a "
                f"{lose_out.p_no_show * 100:.0f}% chance of not playing at all, so the gap in "
                f"practice is wider than the projection makes it look. "
            )
        elif lose_out.p_haul > win_out.p_haul + 0.04:
            line += (
                f"The case for {loser} is upside — he hauls more often ("
                f"{lose_out.p_haul * 100:.0f}% v {win_out.p_haul * 100:.0f}%), so if you're "
                f"chasing rank rather than protecting one he's the braver, defensible call. "
            )
    return line.strip()


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

    # --- Why, mechanically. This goes first because it's the question. ---
    drivers = _driver_lines(left, right, left_name, right_name)
    if drivers:
        detail.append("##### Where the gap actually comes from")
        detail.extend(drivers)

    # --- What could happen, rather than what the average is. ---
    try:
        left_outcome = scenarios.outcome_for(left, left_name)
        right_outcome = scenarios.outcome_for(right, right_name)
    except Exception:
        left_outcome = right_outcome = None

    if left_outcome and right_outcome:
        detail.append("##### What could actually happen this week")
        detail.append(f"**{left_name}:** {scenarios.narrate(left_outcome)}")
        detail.append(f"**{right_name}:** {scenarios.narrate(right_outcome)}")
        detail.extend(scenarios.compare(left_outcome, right_outcome))

    # --- The money, which is usually the real question. ---
    price_gap = float(left["price"]) - float(right["price"])
    if abs(price_gap) >= 0.5:
        dearer, cheaper = (
            (left_name, right_name) if price_gap > 0 else (right_name, left_name)
        )
        detail.append(
            f"**The money.** {dearer} costs **£{abs(price_gap):.1f}m more**, and that has to come "
            f"out of somewhere else in the squad — which is the real question, not which of them "
            f"is better in isolation."
        )

    # --- What the research says about each. ---
    research: list[str] = []
    for who, side in ((left_name, left), (right_name, right)):
        facts = consensus.key_stats(side)
        if facts:
            research.append(f"**{who} by the numbers:** " + " · ".join(facts[:5]))

    left_case, left_against = _consensus_bits(left)
    right_case, right_against = _consensus_bits(right)
    if left_case:
        research.append(f"**On {left_name}:** {left_case}")
    if left_against:
        research.append(f"**Against {left_name}:** {left_against}")
    if right_case:
        research.append(f"**On {right_name}:** {right_case}")
    if right_against:
        research.append(f"**Against {right_name}:** {right_against}")

    for who, side in ((left_name, left), (right_name, right)):
        verdict = _club_verdict(side)
        if verdict:
            research.append(f"**{who}'s club:** {verdict}")
        for source, take in consensus.voices(side)[:2]:
            research.append(f"**{source} on {who}:** {take}")

    if research:
        detail.append("##### What the analysts say")
        detail.extend(research)

    # --- The call, stated plainly. ---
    detail.append("##### The call")
    detail.append(_verdict_line(
        left, right, left_name, right_name, gap, left_outcome, right_outcome
    ))

    return Answer(
        player_name=f"{left_name} vs {right_name}",
        in_squad=False,
        headline=headline,
        detail=detail,
        points_delta=round(gap, 2),
    )
