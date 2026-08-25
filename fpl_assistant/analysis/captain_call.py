"""The captaincy decision, made properly.

Three things were wrong with ranking the armband on projected points.

First, a mean is the wrong statistic for a doubled score. Two players on
5.0 are not equivalent bets: a forward gets there via a 45% chance of
returning and a real chance of fifteen, a defender via a clean sheet and
appearance points he collects most weeks and almost never beats. Doubling
rewards the tail, and the tail is exactly what a mean averages away. That
is how a centre-back ends up with the armband -- not a rounding error, a
category error about which number to rank on.

Second, captaincy is not a solo decision. Your rank moves according to how
far your pick differs from what everyone else did. If 60% of the field
captains the same striker, his haul barely moves you and his blank barely
hurts you; the whole decision is worth less than it feels. Effective
ownership -- ownership plus captaincy share -- is the number that governs
this, and it appears nowhere in the FPL API, so it is researched.

Third, the numbers and the analysts disagree sometimes, and an app that
silently averages them is hiding the most interesting thing on the page.
Where they part company this says so, says which one it is following, and
says why. A model that has never seen a press conference should lose to a
manager quote about who is starting; a narrative with nothing behind it
should lose to a rate built on a season of shots.
"""
from dataclasses import dataclass, field

import pandas as pd

from fpl_assistant.analysis import consensus, odds as odds_module, scenarios

# Positions the armband is a defensible bet on. This is a guard, not the
# reasoning -- the scenario model already ranks defenders below attackers
# on its own, because their ceiling is capped and they blank more often.
# The guard exists because "usually ranks lower" is not "never wins", and
# a single odd gameweek where a defender's projection spikes should not be
# able to produce advice that reads as broken.
ARMBAND_POSITIONS = ("MID", "FWD")

# How much a chance of a double-digit week is worth relative to a point of
# expected score. The armband doubles the result, so upside is worth more
# than the average -- but not so much that a lottery ticket outranks a
# nailed-on premium.
HAUL_WEIGHT = 6.0

# Effective ownership thresholds, from the published captaincy framework:
# above this the pick is the field's, and captaining him tracks the pack
# rather than beating it.
TEMPLATE_EO = 75.0
DIFFERENTIAL_EO = 50.0
# How close a differential has to be on expected points before it's worth
# the leverage. Chasing rank tolerates a wider gap than protecting one.
CHASE_TOLERANCE = 1.5
PROTECT_TOLERANCE = 2.0


@dataclass
class CaptainCase:
    """One candidate for the armband, with the case for and against."""

    player_id: int
    name: str
    team: str
    opponent: str | None
    position: str
    price: float
    expected: float
    ceiling: int
    p_haul: float
    p_blank: float
    ownership: float
    captain_share: float | None
    score: float
    reasons: list[str] = field(default_factory=list)
    expert_take: str | None = None
    odds_note: str | None = None
    matchup_note: str | None = None
    p_goal_odds: float | None = None

    @property
    def effective_ownership(self) -> float:
        """Ownership plus captaincy share -- how much of the field is
        exposed to this player's score, weighted by the armband."""
        return self.ownership + (self.captain_share or 0.0)

    @property
    def is_template(self) -> bool:
        return self.effective_ownership >= TEMPLATE_EO


def _num(row, column, default=0.0) -> float:
    value = pd.to_numeric(row.get(column), errors="coerce")
    return default if value is None or pd.isna(value) else float(value)


def _case_for(row: pd.Series, gameweek: int) -> CaptainCase | None:
    try:
        outcome = scenarios.outcome_for(row)
    except Exception:
        return None

    ownership = _num(row, "selected_by_percent")
    share = row.get("captain_share")
    share = None if share is None or pd.isna(share) else float(share)
    p_goal = row.get("p_goal_odds")
    p_goal = None if p_goal is None or pd.isna(p_goal) else float(p_goal)

    voices = consensus.voices(row)
    expert = voices[0][1] if voices else None

    return CaptainCase(
        player_id=int(row["id"]),
        name=str(row["web_name"]),
        team=str(row.get("team_short_name") or ""),
        opponent=str(row.get("opponent")) if row.get("opponent") else None,
        position=str(row.get("position") or ""),
        price=_num(row, "price"),
        expected=outcome.expected,
        ceiling=outcome.ceiling,
        p_haul=outcome.p_haul,
        p_blank=outcome.p_blank,
        ownership=ownership,
        captain_share=share,
        score=0.0,
        expert_take=expert,
        odds_note=row.get("odds_note") if isinstance(row.get("odds_note"), str) else None,
        matchup_note=odds_module.matchup_note(gameweek, row.get("team_short_name")),
        p_goal_odds=p_goal,
    )


def _score(case: CaptainCase) -> float:
    """Expected score, weighted toward the ceiling because it doubles.

    The odds term is deliberately a nudge rather than a replacement. Where
    a bookmaker has a player much likelier to score than the model does,
    the market is usually seeing something the rates can't -- a lineup, a
    matchup, an opponent missing defenders -- but a single price is a
    thinner input than a season of shot data, so it moves the ranking
    without owning it.
    """
    score = case.expected + HAUL_WEIGHT * case.p_haul
    if case.p_goal_odds is not None:
        # Only the gap matters: agreement with the model adds nothing.
        model_goal_chance = min(case.p_haul * 2.2, 0.95)
        score += 2.0 * (case.p_goal_odds - model_goal_chance)
    return round(score, 2)


def _reasons(case: CaptainCase, best: CaptainCase | None) -> list[str]:
    reasons = [
        f"Projects {case.expected:.1f} points, ceiling around {case.ceiling}, "
        f"{case.p_haul * 100:.0f}% chance of a double-digit week and "
        f"{case.p_blank * 100:.0f}% chance of a blank."
    ]
    if case.p_goal_odds is not None:
        reasons.append(
            f"Bookmakers make him about {case.p_goal_odds * 100:.0f}% to score — the market's "
            f"read on this fixture, not a summary of what he's already done."
        )
    if case.matchup_note:
        reasons.append(f"Against this opponent: {case.matchup_note}")
    if case.captain_share is not None:
        if case.is_template:
            reasons.append(
                f"About {case.captain_share:.0f}% of the field will captain him "
                f"({case.effective_ownership:.0f}% effective ownership). At that level his haul "
                f"barely moves your rank and his blank barely hurts it — you're tracking the "
                f"pack, not beating it."
            )
        elif case.effective_ownership < DIFFERENTIAL_EO:
            reasons.append(
                f"Only about {case.captain_share:.0f}% will captain him "
                f"({case.effective_ownership:.0f}% effective ownership), so this is leveraged: "
                f"it gains real rank if it lands and costs real rank if it doesn't."
            )
    if best is not None and case.player_id != best.player_id:
        gap = best.score - case.score
        reasons.append(f"Trails the top pick by {gap:.1f} on the combined score.")
    return reasons


def adjudicate(case: CaptainCase) -> str | None:
    """Where the numbers and the analysts disagree, say which one wins.

    Silently averaging the two hides the most interesting thing on the
    page. The rule is about what each source can actually see: a model
    that has never read a press conference should lose to a quote about
    who is starting, and a narrative with nothing behind it should lose to
    a rate built on a season of shots.
    """
    if not case.expert_take:
        return None

    take = case.expert_take.lower()
    negative = any(word in take for word in ("avoid", "risk", "doubt", "rotation", "not certain", "injur"))
    strong_model = case.p_haul >= 0.15 and case.p_blank <= 0.55

    if negative and strong_model:
        return (
            "**The numbers and the analysts disagree here.** The projection likes him — the "
            "shot volume and the fixture are both there — while the written analysis flags a "
            "doubt the numbers can't see. Going with the analysts: a rate built on past matches "
            "cannot know what a manager said this week, and minutes risk is the one thing that "
            "makes every other number irrelevant."
        )
    if not negative and case.p_haul < 0.08 and case.expected < 4.0:
        return (
            "**The numbers and the analysts disagree here.** The write-up is positive, but the "
            "underlying rates don't support a captaincy ceiling — a low haul probability is not "
            "something enthusiasm fixes. Going with the numbers: sentiment is a weaker source "
            "than a season of shot data when the question is upside."
        )
    return None


def rank(
    scored: pd.DataFrame,
    gameweek: int,
    strategy: float = 0.0,
    top_n: int = 6,
) -> list[CaptainCase]:
    """Captaincy candidates, best first.

    `strategy` mirrors the sidebar's rank control: positive protects rank
    (shadow the template), negative chases it (take the leverage).
    """
    pool = scored[scored["position"].isin(ARMBAND_POSITIONS)].copy()
    pool = pool[pool.get("status", "a") == "a"]
    if pool.empty:
        return []

    if "captain_share" not in pool.columns:
        pool = odds_module.annotate(pool, gameweek)

    cases = [c for c in (_case_for(row, gameweek) for _, row in pool.iterrows()) if c is not None]
    for case in cases:
        case.score = _score(case)
    cases.sort(key=lambda c: -c.score)
    cases = cases[: max(top_n, 2)]

    best = cases[0] if cases else None
    for case in cases:
        case.reasons = _reasons(case, best)
    return cases


def verdict(cases: list[CaptainCase], strategy: float = 0.0) -> str:
    """The recommendation, including whether to fade the template.

    The differential test comes from the published framework rather than
    from taste: it's only a real question when the favourite is genuinely
    the field's pick and the alternative is genuinely close.
    """
    if not cases:
        return "No captaincy candidate could be assessed this gameweek."
    top = cases[0]
    if len(cases) == 1:
        return f"**Captain {top.name}.** Nothing else is close enough to argue about."

    runner = next((c for c in cases[1:] if c.effective_ownership < DIFFERENTIAL_EO), None)
    line = f"**Captain {top.name}** — {top.expected:.1f} projected, ceiling {top.ceiling}."

    if runner is None or not top.is_template:
        return line + (
            f" {cases[1].name} is the alternative and trails by "
            f"{top.score - cases[1].score:.1f}."
        )

    gap = top.score - runner.score
    tolerance = CHASE_TOLERANCE if strategy < 0 else PROTECT_TOLERANCE
    if gap <= tolerance:
        stance = (
            "you're chasing rank, so the leverage is worth having"
            if strategy < 0
            else "worth a look even protecting rank, since the gap is small"
        )
        return (
            line
            + f"\n\n**But {runner.name} is the live differential.** {top.name} is the field's "
            f"pick at {top.effective_ownership:.0f}% effective ownership, {runner.name} is at "
            f"{runner.effective_ownership:.0f}%, and they're only {gap:.1f} apart on the "
            f"combined score — {stance}. Captaining the template here tracks the pack; "
            f"captaining {runner.name} is how you actually move."
        )
    return (
        line
        + f" {runner.name} is the differential at {runner.effective_ownership:.0f}% effective "
        f"ownership, but he's {gap:.1f} behind — too far to be worth the leverage this week."
    )
