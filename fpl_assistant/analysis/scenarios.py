"""What could actually happen to this player this weekend.

Everything else in the app reports an expected-points *mean*, and a mean
is the wrong summary for the decision people are actually making. A 5.0
projection can be a steady five every week or a blank-blank-fifteen, and
those are completely different players to own: one protects a rank, the
other moves it. Two players level on projection can have nothing in common
in the outcome that matters.

So this reconstructs the distribution behind the mean by enumerating what
can happen -- did he play, how many goals, how many assists, clean sheet
or not -- weighting each combination by its probability, and summing the
FPL points for it. Exact enumeration rather than simulation, so the same
inputs always give the same answer and there is no sampling noise to
explain away.

The output is deliberately the shape of the question a person asks:
how likely is a blank, how likely is a return, how likely is a haul, and
what does the good version of this week look like.
"""
import math
from dataclasses import dataclass

import pandas as pd

from fpl_assistant.analysis.expected_points import (
    ASSIST_POINTS,
    CLEAN_SHEET_POINTS,
    GOAL_POINTS,
)

# Enumeration bounds. Beyond these the probability mass is negligible for
# any realistic per-match rate, and truncating keeps the enumeration exact
# rather than approximate in a way that matters.
MAX_GOALS = 5
MAX_ASSISTS = 4

# A blank in the sense managers mean it: the appearance points and nothing
# else worth having.
BLANK_THRESHOLD = 2
# What the community calls a haul.
HAUL_THRESHOLD = 10
# The "good version of the week" -- not the absolute maximum, which is
# always some four-goal fantasy, but the outcome he beats one week in ten.
CEILING_PERCENTILE = 0.90
FLOOR_PERCENTILE = 0.25


@dataclass
class Outcome:
    """The distribution of what this player might score next gameweek."""

    player_name: str
    expected: float
    p_blank: float
    p_return: float
    p_haul: float
    p_no_show: float
    floor: int
    median: int
    ceiling: int
    distribution: list[tuple[int, float]]

    @property
    def spread(self) -> int:
        return self.ceiling - self.floor


def _poisson(lam: float, k: int) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam**k / math.factorial(k)


def _bonus(goals: int, assists: int, clean_sheet: bool, position: str) -> int:
    """Approximate bonus points.

    Bonus is decided by the BPS table, which depends on tackles, passes
    and saves this model never sees. Rather than pretend otherwise, this
    is a deliberately coarse rule tied to the returns that dominate BPS in
    practice, and it is the one genuinely approximate part of the
    calculation. It moves the tail, not the shape.
    """
    involvement = goals + assists
    if involvement >= 2:
        return 3
    if goals == 1:
        return 2 if position in ("FWD", "MID") else 3
    if assists == 1:
        return 1
    if clean_sheet and position in ("GKP", "DEF"):
        return 1
    return 0


def outcome_for(row: pd.Series, name: str | None = None) -> Outcome:
    """The full points distribution for one player, next gameweek."""
    position = str(row.get("position") or "MID")
    goal_value = GOAL_POINTS.get(position, 4)
    cs_value = CLEAN_SHEET_POINTS.get(position, 0)

    def _num(column, default=0.0):
        value = pd.to_numeric(row.get(column), errors="coerce")
        return default if value is None or pd.isna(value) else float(value)

    xg = max(_num("xg_match"), 0.0)
    xa = max(_num("xa_match"), 0.0)
    p_cs = min(max(_num("p_clean_sheet"), 0.0), 1.0)
    p_sixty = min(max(_num("p_sixty"), 0.0), 1.0)

    # p_sixty already folds in availability and start probability. The
    # cameo band is whatever start probability is left over once the
    # 60-minute cases are taken out.
    p_start = min(max(_num("p_start"), 0.0), 1.0) * min(max(_num("p_available", 1.0), 0.0), 1.0)
    p_cameo = max(p_start - p_sixty, 0.0)
    p_absent = max(1.0 - p_sixty - p_cameo, 0.0)

    goal_probs = [_poisson(xg, k) for k in range(MAX_GOALS + 1)]
    assist_probs = [_poisson(xa, k) for k in range(MAX_ASSISTS + 1)]
    # Fold the truncated tail back into the top bucket so the distribution
    # still sums to one and the ceiling isn't quietly understated.
    goal_probs[-1] += max(0.0, 1.0 - sum(goal_probs))
    assist_probs[-1] += max(0.0, 1.0 - sum(assist_probs))

    tally: dict[int, float] = {}

    def _add(points: int, probability: float) -> None:
        if probability > 0:
            tally[points] = tally.get(points, 0.0) + probability

    _add(0, p_absent)

    for played_sixty, play_weight, appearance in (
        (True, p_sixty, 2),
        (False, p_cameo, 1),
    ):
        if play_weight <= 0:
            continue
        # A cameo scales the attacking rates down: the rate was computed
        # for expected minutes, and someone who came on for twenty of them
        # did not get the same chances.
        scale = 1.0 if played_sixty else 0.35
        goals_dist = [_poisson(xg * scale, k) for k in range(MAX_GOALS + 1)]
        assists_dist = [_poisson(xa * scale, k) for k in range(MAX_ASSISTS + 1)]
        goals_dist[-1] += max(0.0, 1.0 - sum(goals_dist))
        assists_dist[-1] += max(0.0, 1.0 - sum(assists_dist))

        # Clean sheets only pay from 60 minutes.
        cs_options = ((True, p_cs), (False, 1 - p_cs)) if played_sixty else ((False, 1.0),)

        for goals, p_goals in enumerate(goals_dist):
            for assists, p_assists in enumerate(assists_dist):
                for clean_sheet, p_clean in cs_options:
                    probability = play_weight * p_goals * p_assists * p_clean
                    if probability <= 1e-9:
                        continue
                    points = (
                        appearance
                        + goals * goal_value
                        + assists * ASSIST_POINTS
                        + (cs_value if clean_sheet else 0)
                        + _bonus(goals, assists, clean_sheet, position)
                    )
                    _add(points, probability)

    total = sum(tally.values()) or 1.0
    distribution = sorted((points, weight / total) for points, weight in tally.items())

    def _percentile(target: float) -> int:
        cumulative = 0.0
        for points, weight in distribution:
            cumulative += weight
            if cumulative >= target:
                return points
        return distribution[-1][0] if distribution else 0

    expected = sum(points * weight for points, weight in distribution)
    p_blank = sum(w for points, w in distribution if points <= BLANK_THRESHOLD)
    p_haul = sum(w for points, w in distribution if points >= HAUL_THRESHOLD)
    # A "return" is an attacking return, which is what the word means in
    # FPL -- a defender's clean sheet is not one, however many points it
    # pays.
    p_return = (p_sixty + p_cameo) * (1 - math.exp(-(xg + xa)))

    return Outcome(
        player_name=name or str(row.get("web_name") or "This player"),
        expected=round(expected, 2),
        p_blank=round(p_blank, 3),
        p_return=round(min(p_return, 1.0), 3),
        p_haul=round(p_haul, 3),
        p_no_show=round(p_absent, 3),
        floor=_percentile(FLOOR_PERCENTILE),
        median=_percentile(0.5),
        ceiling=_percentile(CEILING_PERCENTILE),
        distribution=distribution,
    )


def narrate(outcome: Outcome) -> str:
    """The distribution as a sentence someone would actually say."""
    if outcome.floor == outcome.median:
        opening = (
            f"The typical week here is **{outcome.median} points** — that's both the most likely "
            f"outcome and roughly the bad one — with the good version at **{outcome.ceiling}+**"
        )
    else:
        opening = (
            f"Most likely he lands around **{outcome.median} points**, a bad week is "
            f"**{outcome.floor}**, and the good version is **{outcome.ceiling}+**"
        )

    line = opening + ". "
    line += (
        f"Roughly **{outcome.p_return * 100:.0f}%** chance of a goal or assist, "
        f"**{outcome.p_haul * 100:.0f}%** chance of a double-digit haul, and "
        f"**{outcome.p_blank * 100:.0f}%** chance of a blank."
    )

    # The insight the mean actively hides. Where the average sits well
    # above the typical week, the average is being carried by the tail --
    # you are buying a lottery ticket that pays occasionally, not a player
    # who scores his projection most weeks. That distinction decides
    # whether someone belongs in a rank-protecting squad or a chasing one.
    if outcome.expected - outcome.median >= 1.5:
        line += (
            f" Worth knowing that his **{outcome.expected:.1f} average is carried by the ceiling**, "
            f"not by the typical week — most weeks he blanks and the hauls pay for it. That's an "
            f"upside pick, not a steady one."
        )
    elif outcome.spread <= 4 and outcome.p_blank < 0.5:
        line += (
            f" The spread is narrow, so this is the steady end of the market — he rarely wins you "
            f"a week on his own, and he rarely costs you one either."
        )

    if outcome.p_no_show >= 0.08:
        line += (
            f" There's also a **{outcome.p_no_show * 100:.0f}%** chance he doesn't play at all, "
            f"which is the risk a projection quietly averages away."
        )
    return line


def compare(left: Outcome, right: Outcome) -> list[str]:
    """Where two players' outcomes actually differ.

    Only reports differences big enough to act on. A comparison that lists
    every metric regardless of whether it separates the two is how these
    sections end up feeling generic -- the reader has to work out which
    line was the deciding one, which is the job being outsourced to them.
    """
    lines: list[str] = []

    haul_gap = left.p_haul - right.p_haul
    if abs(haul_gap) >= 0.04:
        better, worse = (left, right) if haul_gap > 0 else (right, left)
        lines.append(
            f"**{better.player_name} has the bigger ceiling** — a "
            f"{better.p_haul * 100:.0f}% chance of a double-digit week against "
            f"{worse.p_haul * 100:.0f}% for {worse.player_name}. That gap is what matters if "
            f"you're chasing rank rather than protecting it."
        )

    blank_gap = left.p_blank - right.p_blank
    if abs(blank_gap) >= 0.05:
        safer, riskier = (right, left) if blank_gap > 0 else (left, right)
        lines.append(
            f"**{safer.player_name} blanks less often** — {safer.p_blank * 100:.0f}% of weeks "
            f"against {riskier.p_blank * 100:.0f}% for {riskier.player_name}."
        )

    return_gap = left.p_return - right.p_return
    if abs(return_gap) >= 0.05:
        better, worse = (left, right) if return_gap > 0 else (right, left)
        lines.append(
            f"**{better.player_name} is more likely to return** — {better.p_return * 100:.0f}% "
            f"chance of a goal or assist against {worse.p_return * 100:.0f}%."
        )

    show_gap = left.p_no_show - right.p_no_show
    if abs(show_gap) >= 0.06:
        riskier, safer = (left, right) if show_gap > 0 else (right, left)
        lines.append(
            f"**{riskier.player_name} carries real minutes risk** — a "
            f"{riskier.p_no_show * 100:.0f}% chance of not playing, against "
            f"{safer.p_no_show * 100:.0f}% for {safer.player_name}."
        )

    if not lines:
        lines.append(
            "Their outcome distributions are close enough that the projection isn't separating "
            "them — the decision comes down to price, ownership and what you believe about the "
            "fixtures rather than to the numbers."
        )
    return lines
