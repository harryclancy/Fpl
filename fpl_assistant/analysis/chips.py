"""Chip strategy: when to play the Wildcard, Bench Boost, Triple Captain
and Free Hit.

The single largest points lever the app wasn't touching. Four chips over a
season, each worth roughly 15-30 points when played into the right
gameweek and close to nothing when played into a random one — so the
decision is almost entirely about *timing*, and timing is a scheduling
problem the fixture list can already answer.

Each chip keys off a different feature of the schedule:

  Triple Captain  a premium with a double gameweek, or a very soft home tie
  Bench Boost     a double gameweek where all fifteen play twice
  Free Hit        a blank gameweek where much of your squad has no fixture
  Wildcard        not a fixture question at all — it's about how far your
                  squad has drifted from the best one you could field

The first three are computed by scanning the fixture schedule ahead. The
Wildcard is computed by re-solving the optimal squad and measuring the gap,
which is the only honest way to answer "is my team bad enough to justify
this".
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from fpl_assistant.analysis import optimiser
from fpl_assistant.analysis.expected_points import team_schedule

# How many gameweeks ahead to scan for chip opportunities. Beyond this the
# fixture list is published but team form, injuries and price all move too
# much for a recommendation to mean anything.
DEFAULT_LOOKAHEAD = 8

# A Wildcard is worth playing when the squad you'd build from scratch beats
# the one you own by more than this over the horizon. Below it, a couple of
# ordinary transfers get you most of the way for free.
WILDCARD_GAIN_THRESHOLD = 12.0
# Bench Boost only pays when the bench actually plays. This is the minimum
# projected bench return that makes it worth burning the chip.
BENCH_BOOST_THRESHOLD = 12.0
# Free Hit is for a gameweek where your squad is gutted by blanks.
FREE_HIT_MIN_MISSING = 4


@dataclass
class ChipAdvice:
    chip: str
    recommendation: str
    gameweek: int | None = None
    value: float | None = None
    detail: list[str] = field(default_factory=list)
    urgent: bool = False


def gameweek_fixture_counts(
    fixtures: pd.DataFrame, from_event: int, lookahead: int
) -> pd.DataFrame:
    """Fixtures per team per gameweek — the raw material for chip timing.

    A value of 2 is a double gameweek, 0 is a blank. Both are where chips
    earn their keep, and both are invisible to any per-player statistic.
    """
    schedule = team_schedule(fixtures, from_event, lookahead)
    teams = sorted(schedule)

    # Only gameweeks that actually have fixtures in the data. A gameweek
    # where *nobody* plays isn't a blank gameweek — it's one the fixture
    # list doesn't cover yet. Treating the two the same made Free Hit
    # scream "all 15 of your players blank!" for every week past the end
    # of the published schedule, which is both wrong and the loudest
    # possible way to be wrong.
    scheduled = {
        gw for gw in range(from_event, from_event + lookahead)
        if any(schedule.get(team, {}).get(gw) for team in teams)
    }
    gameweeks = sorted(scheduled)
    if not gameweeks:
        return pd.DataFrame()

    rows = {
        team: {gw: len(schedule.get(team, {}).get(gw, [])) for gw in gameweeks} for team in teams
    }
    return pd.DataFrame.from_dict(rows, orient="index").reindex(columns=gameweeks).fillna(0)


def _squad_gameweek_points(
    scored: pd.DataFrame, player_ids: list[int], gameweek: int
) -> pd.Series:
    column = f"xp_gw{gameweek}"
    if column not in scored.columns:
        return pd.Series(dtype=float)
    return scored[scored["id"].isin(player_ids)].set_index("id")[column]


def advise_triple_captain(
    scored: pd.DataFrame,
    squad_ids: list[int],
    counts: pd.DataFrame,
    from_event: int,
    lookahead: int,
) -> ChipAdvice:
    """Best gameweek to triple a captain.

    Ranked on the captain's projected score in that specific gameweek, not
    their season-long quality: the chip is a one-week bet, and a double
    gameweek is worth more than a better player playing once.
    """
    best = (None, -1.0, None)
    for gw in (list(counts.columns) or range(from_event, from_event + lookahead)):
        points = _squad_gameweek_points(scored, squad_ids, gw)
        if points.empty:
            continue
        top_id = points.idxmax()
        if points.loc[top_id] > best[1]:
            best = (gw, float(points.loc[top_id]), top_id)

    gw, value, player_id = best
    if gw is None:
        return ChipAdvice("Triple Captain", "No projection available for the weeks ahead.")

    name = scored.set_index("id").loc[player_id, "web_name"]
    team = scored.set_index("id").loc[player_id, "team_short_name"]
    fixtures_that_week = counts.loc[
        scored.set_index("id").loc[player_id, "team"], gw
    ] if scored.set_index("id").loc[player_id, "team"] in counts.index else 1

    detail = [
        f"**{name}** ({team}) projects **{value:.1f} points** in GW{gw} — tripled, that's "
        f"**{value * 3:.0f}**, against the {value * 2:.0f} you'd get captaining him normally. "
        f"The chip is worth the difference, roughly **{value:.0f} points**."
    ]
    if fixtures_that_week >= 2:
        detail.append(
            f"GW{gw} is a **double gameweek** for {team} — two matches, which is where this chip "
            f"does most of its work. Doubles are worth waiting for."
        )
    else:
        detail.append(
            "No double gameweek in this window, so this is a single-fixture play. Worth holding "
            "unless the fixture is exceptional — doubles usually come later in the season."
        )

    return ChipAdvice(
        "Triple Captain",
        f"Best window: **GW{gw}** on {name}",
        gameweek=gw, value=round(value, 1), detail=detail,
        urgent=fixtures_that_week >= 2,
    )


def advise_bench_boost(
    scored: pd.DataFrame,
    bench_ids: list[int],
    counts: pd.DataFrame,
    from_event: int,
    lookahead: int,
) -> ChipAdvice:
    """Best gameweek to score your bench.

    Bench Boost is worth exactly what your four substitutes score, so the
    chip is only as good as the week you play it into — a double gameweek
    where all four have two fixtures, ideally.
    """
    best = (None, -1.0)
    for gw in (list(counts.columns) or range(from_event, from_event + lookahead)):
        points = _squad_gameweek_points(scored, bench_ids, gw)
        if points.empty:
            continue
        total = float(points.sum())
        if total > best[1]:
            best = (gw, total)

    gw, value = best
    if gw is None:
        return ChipAdvice("Bench Boost", "No projection available for the weeks ahead.")

    detail = [
        f"Your current bench projects **{value:.1f} points** in GW{gw} — that's what the chip "
        f"would be worth if played then."
    ]
    if value < BENCH_BOOST_THRESHOLD:
        detail.append(
            f"That's below the **{BENCH_BOOST_THRESHOLD:.0f}-point** bar worth burning a chip for. "
            f"Bench Boost pays when your bench is strong *and* has a double gameweek — a bench of "
            f"cheap enablers, which is what a good squad has, is the wrong bench for it. Hold, and "
            f"revisit when doubles arrive."
        )
    else:
        detail.append(
            "That clears the bar. Worth pairing with a Wildcard the week before, so you can load "
            "the bench with players who actually have fixtures."
        )

    return ChipAdvice(
        "Bench Boost",
        f"Best window: **GW{gw}** (bench projects {value:.1f} pts)",
        gameweek=gw, value=round(value, 1), detail=detail,
        urgent=value >= BENCH_BOOST_THRESHOLD,
    )


def advise_free_hit(
    scored: pd.DataFrame,
    squad_ids: list[int],
    counts: pd.DataFrame,
    from_event: int,
    lookahead: int,
) -> ChipAdvice:
    """Best gameweek to field a one-week replacement squad.

    Free Hit is a blank-gameweek rescue: it earns most when a chunk of your
    squad simply has no fixture, which is a schedule fact rather than a
    form judgement.
    """
    squad = scored[scored["id"].isin(squad_ids)]
    if squad.empty or counts.empty:
        return ChipAdvice("Free Hit", "No squad loaded, so there's nothing to rescue.")

    worst = (None, 0)
    for gw in counts.columns:
        missing = sum(
            1 for team in squad["team"]
            if team in counts.index and counts.loc[team, gw] == 0
        )
        if missing > worst[1]:
            worst = (gw, missing)

    gw, missing = worst
    if gw is None or missing == 0:
        return ChipAdvice(
            "Free Hit",
            "Hold — no blank gameweek in this window",
            detail=[
                "Every player in your squad has a fixture in each of the next few gameweeks, so "
                "there's nothing for this chip to rescue. Save it for a blank, typically around "
                "the FA Cup rounds."
            ],
        )

    detail = [
        f"**{missing} of your 15** have no fixture in GW{gw}. A Free Hit fields a full replacement "
        f"squad for that week only, then reverts."
    ]
    if missing < FREE_HIT_MIN_MISSING:
        detail.append(
            f"With only {missing} missing you can usually patch it with transfers and bench cover "
            f"instead. Free Hit earns its place when {FREE_HIT_MIN_MISSING}+ players blank."
        )

    return ChipAdvice(
        "Free Hit",
        f"Watch **GW{gw}** — {missing} players blank",
        gameweek=gw, value=float(missing), detail=detail,
        urgent=missing >= FREE_HIT_MIN_MISSING,
    )


def advise_wildcard(
    scored: pd.DataFrame,
    squad_ids: list[int],
    budget: float,
    template_weight: float = optimiser.TEMPLATE_WEIGHT,
) -> ChipAdvice:
    """Whether the squad has drifted far enough to justify a Wildcard.

    Not a fixture question. The honest test is to build the best squad
    available and measure how far the one you own falls short — anything
    else is a feeling about your team rather than a number.
    """
    owned = scored[scored["id"].isin(squad_ids)]
    if owned.empty:
        return ChipAdvice("Wildcard", "No squad loaded, so there's nothing to compare against.")

    try:
        fresh = optimiser.optimise_squad(scored, budget=budget, template_weight=template_weight)
        current_starters, _, _ = optimiser.optimise_starting_xi(owned, points_column="xp_horizon")
    except Exception as exc:
        return ChipAdvice("Wildcard", f"Couldn't compare squads this week ({exc}).")

    points = scored.set_index("id")["xp_horizon"]
    current = float(points.loc[current_starters].sum())
    optimal = float(points.loc[fresh.starting_ids].sum())
    gain = optimal - current

    detail = [
        f"Your current XI projects **{current:.0f} points** over the next five gameweeks. The best "
        f"XI buildable from scratch projects **{optimal:.0f}** — a gap of **{gain:.0f}**."
    ]
    if gain >= WILDCARD_GAIN_THRESHOLD:
        detail.append(
            "That's a big enough gap to justify the chip: you'd need several transfers and multiple "
            "hits to close it otherwise, and the hits alone would eat the gain."
        )
        recommendation = f"**Worth considering** — {gain:.0f} points behind the optimal squad"
    else:
        detail.append(
            f"Below the **{WILDCARD_GAIN_THRESHOLD:.0f}-point** bar. A gap this size closes with "
            f"one or two ordinary transfers, which cost nothing — spending a Wildcard on it wastes "
            f"the chip. Hold it for an injury crisis or a fixture swing."
        )
        recommendation = (
            "**Hold** — your squad already matches the best available"
            if gain < 0.5
            else f"**Hold** — only {gain:.0f} points behind, which free transfers can fix"
        )

    return ChipAdvice(
        "Wildcard", recommendation, value=round(gain, 1), detail=detail,
        urgent=gain >= WILDCARD_GAIN_THRESHOLD,
    )


def advise_all(
    scored: pd.DataFrame,
    solution: optimiser.SquadSolution,
    fixtures: pd.DataFrame,
    from_event: int,
    lookahead: int = DEFAULT_LOOKAHEAD,
    budget: float = optimiser.DEFAULT_BUDGET,
    template_weight: float = optimiser.TEMPLATE_WEIGHT,
) -> list[ChipAdvice]:
    """All four chips, most actionable first."""
    counts = gameweek_fixture_counts(fixtures, from_event, lookahead)
    advice = [
        advise_triple_captain(scored, solution.squad_ids, counts, from_event, lookahead),
        advise_bench_boost(scored, solution.bench_ids, counts, from_event, lookahead),
        advise_free_hit(scored, solution.squad_ids, counts, from_event, lookahead),
        advise_wildcard(scored, solution.squad_ids, budget, template_weight),
    ]
    return sorted(advice, key=lambda a: not a.urgent)
