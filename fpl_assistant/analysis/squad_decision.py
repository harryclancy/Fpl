"""Transfers decided from the squad you own, not from a shopping list.

The failure this replaces: the engine started at "who is the most
attractive player available?" and then looked for whoever the money worked
against. That is how a settled, in-form asset gets sold to fund a
bandwagon — the outgoing player was chosen by arithmetic, not because
anything was wrong with him.

The order here is the fix, and it is the whole design:

    the fifteen you own
        -> diagnose what is actually wrong with each
        -> rank by how urgently each needs replacing
        -> only then look for replacements
        -> build complete options, ROLLING ALWAYS AMONG THEM
        -> compare whole squads, not player against player
        -> take the best decision, which is often to do nothing

Two rules run through all of it.

**No name is protected.** There is no list of players the engine may not
sell. A premium asset survives because the evidence says he is fit, playing
and productive — and if that stops being true the engine will sell him.
Protection is earned per gameweek, from what was published this week.

**Doing nothing is a real option.** A free transfer carried into next week
has value, and a move that gains a point over five gameweeks is not worth
spending one. Rolling is scored on the same scale as every transfer and
wins on merit, which is what stops the engine spending a transfer a week
because it always found something marginally better.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# The five-gameweek horizon. Front-loaded because this weekend is certain
# and gameweek five is a guess, but not so steeply that a one-week fixture
# swing outweighs a month of better minutes.
HORIZON_WEIGHTS = (0.35, 0.25, 0.18, 0.13, 0.09)

# Sell-urgency bands, as specified.
BANDS = (
    (15, "Strong hold"),
    (30, "Comfortable hold"),
    (45, "Monitor"),
    (60, "Possible sell"),
    (75, "Strong sell candidate"),
    (90, "Very strong sell"),
    (100, "Urgent removal"),
)

# What a transfer is FOR. Naming it is not decoration: a move whose only
# benefit is money released has to justify what the money then does, and
# without this classification that question never gets asked.
FORCED = "Forced move"
UPGRADE = "Direct upgrade"
SIDEWAYS = "Sideways move"
FIXTURE_SWING = "Fixture swing"
BUDGET_RELEASE = "Budget release"
STRUCTURAL = "Structural move"
LUXURY = "Luxury move"

# The bar a transfer must clear to beat rolling. Set in projected points
# over the five-gameweek horizon. A free transfer next week is worth
# roughly this much: it is the option to react to news you do not have yet,
# and the single most common mistake in this game is spending it for a
# fractional gain.
ROLL_VALUE = 1.6
MIN_GAIN_TO_ACT = 2.0
HIT_COST = 4.0
# A hit needs to clear its own cost by this much again before it is worth
# the variance.
HIT_MARGIN = 2.5


def band(score: float) -> str:
    for ceiling, label in BANDS:
        if score <= ceiling:
            return label
    return BANDS[-1][1]


@dataclass
class PlayerSignals:
    """What is known about one owned player, from every available source.

    Deliberately a flat record of evidence rather than a verdict. The
    scoring below is the only place a judgement is formed, so it can be
    read, argued with and tested in one place.
    """

    name: str
    club: str
    position: str
    price: float
    player_id: int = 0
    on_bench: bool = False
    is_captain: bool = False

    # From the official FPL data.
    status: str = "a"                 # 'a' available, else flagged
    chance_of_playing: float | None = None
    projection: float = 0.0           # this gameweek's projected points
    form: float = 0.0
    points_per_game: float = 0.0

    # Per-gameweek projections from the expected-points model, already
    # fixture-adjusted and already minutes-adjusted. Using these directly
    # is the whole calibration fix — see horizon_points below.
    gameweek_projections: list[float] = field(default_factory=list)
    projection_confidence: str = "medium"
    baseline: float = 0.0          # recent scoring rate, for regression

    # Selection record, from the official FPL data.
    starts: int = 0
    appearances: int = 0
    minutes_played: int = 0
    team_games: int = 0
    total_points: int = 0
    minutes_category: str = "Unassessed"
    minutes_confidence: float = 0.6

    # From the research corpus.
    evidence_count: int = 0
    source_count: int = 0
    positive_quotes: int = 0
    negative_quotes: int = 0
    minutes_assessed: bool = False
    team_news_found: bool = False
    transfer_talk: bool = False
    injury_talk: bool = False
    omission_talk: bool = False
    rotation_talk: bool = False
    set_pieces: bool = False
    penalties: bool = False
    latest_evidence: str = ""

    # Fixtures, where the fixture table is available.
    fixture_scores: list[float] = field(default_factory=list)  # 1 easy .. 5 hard

    @property
    def flagged(self) -> bool:
        return self.status != "a"

    @property
    def evidence_balance(self) -> float:
        """-1 (all cautionary) to +1 (all favourable), 0 when silent."""
        total = self.positive_quotes + self.negative_quotes
        if not total:
            return 0.0
        return (self.positive_quotes - self.negative_quotes) / total

    @property
    def fixture_difficulty(self) -> float:
        """Weighted mean difficulty over the horizon, 3.0 when unknown."""
        if not self.fixture_scores:
            return 3.0
        pairs = list(zip(self.fixture_scores, HORIZON_WEIGHTS))
        weight = sum(w for _, w in pairs)
        return sum(s * w for s, w in pairs) / weight if weight else 3.0


@dataclass
class Assessment:
    """One player's diagnosis: how badly he needs replacing, and why."""

    signals: PlayerSignals
    sell_urgency: float = 0.0
    hold_strength: float = 0.0
    reasons: list[str] = field(default_factory=list)
    protections: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.signals.name

    @property
    def band(self) -> str:
        return band(self.sell_urgency)

    @property
    def forced(self) -> bool:
        return self.sell_urgency >= 91

    def as_dict(self) -> dict:
        return {
            "player": self.name, "club": self.signals.club,
            "position": self.signals.position, "price": self.signals.price,
            "sell_urgency": round(self.sell_urgency, 1), "band": self.band,
            "hold_strength": round(self.hold_strength, 1),
            "reasons": self.reasons, "protections": self.protections,
        }


def assess(signals: PlayerSignals) -> Assessment:
    """Scores one player's sell urgency out of 100, from evidence only.

    Every contribution is additive and named, so the number can always be
    explained as a list of reasons rather than asserted. Nothing here reads
    a player's name, price bracket or reputation: a £15.5m forward and a
    £4.0m bench defender go through identical arithmetic, and the premium
    ends up protected because his evidence protects him.
    """
    out = Assessment(signals=signals)
    score = 20.0  # everyone starts in "comfortable hold"; evidence moves it

    # --- availability: the only thing that can force a move -------------
    if signals.flagged:
        score += 45
        out.reasons.append("flagged as unavailable in the official FPL data")
    chance = signals.chance_of_playing
    if chance is not None:
        if chance <= 25:
            score += 30
            out.reasons.append(f"chance of playing given as {chance:.0f}%")
        elif chance <= 75:
            score += 15
            out.reasons.append(f"chance of playing given as {chance:.0f}%")

    # --- what this week's reporting actually says -----------------------
    if signals.injury_talk:
        score += 12
        out.reasons.append("injury reported in this week's coverage")
    if signals.omission_talk:
        score += 14
        out.reasons.append("left out of a recent squad according to the coverage")
    if signals.rotation_talk:
        score += 8
        out.reasons.append("rotation risk raised in the coverage")
    if signals.transfer_talk:
        score += 10
        out.reasons.append("transfer speculation in this week's coverage")

    balance = signals.evidence_balance
    if balance <= -0.34:
        score += 12
        out.reasons.append("the published evidence is predominantly cautionary")
    elif balance >= 0.34:
        score -= 10
        out.protections.append("the published evidence is predominantly favourable")

    # --- expected minutes, graded ---------------------------------------
    # Read from the selection record first and the news second. Previously
    # this was a binary "did an article discuss his selection", which three
    # days before a deadline is false for everyone — so every player took
    # the same penalty and the ranking carried no information.
    minutes_penalty = {
        "Very secure": -12, "Secure": -6, "Slight concern": 4,
        "Significant concern": 16, "Major doubt": 30, "Unassessed": 6,
    }.get(signals.minutes_category, 6)
    score += minutes_penalty
    if minutes_penalty > 0:
        out.reasons.append(f"expected minutes: {signals.minutes_category.lower()}")
    else:
        out.protections.append(f"expected minutes: {signals.minutes_category.lower()}")

    if signals.evidence_count == 0:
        score += 4
        out.reasons.append("no retrieved article mentions him at all")

    # --- the football: role, fixtures, output ---------------------------
    difficulty = signals.fixture_difficulty
    if difficulty >= 3.8:
        score += 10
        out.reasons.append(f"hard fixture run ahead (mean difficulty {difficulty:.1f})")
    elif difficulty <= 2.4:
        score -= 8
        out.protections.append(f"kind fixture run ahead (mean difficulty {difficulty:.1f})")

    if signals.set_pieces:
        score -= 6
        out.protections.append("on set pieces")
    if signals.penalties:
        score -= 8
        out.protections.append("on penalties")

    if signals.points_per_game >= 5.0:
        score -= 10
        out.protections.append(f"averaging {signals.points_per_game:.1f} points a game")
    elif signals.points_per_game and signals.points_per_game <= 2.0:
        score += 8
        out.reasons.append(f"averaging only {signals.points_per_game:.1f} points a game")

    if signals.team_news_found and balance >= 0:
        score -= 5
        out.protections.append("team news found and it is not negative")

    # --- opportunity cost -----------------------------------------------
    # Money tied up in a bench player who never plays is a real problem
    # even when nothing is wrong with him.
    if signals.on_bench and signals.price >= 5.0:
        score += 8
        out.reasons.append(f"£{signals.price:.1f}m sitting on the bench")

    score = max(0.0, min(100.0, score))
    out.sell_urgency = score
    # Hold strength is not simply the inverse: it measures how much
    # POSITIVE evidence exists, which is what makes a player expensive to
    # give up. A player nobody has written about has low urgency AND low
    # hold strength — quietly replaceable.
    out.hold_strength = max(0.0, min(100.0, (
        30
        + 25 * max(0.0, balance)
        + (15 if signals.penalties else 0)
        + (10 if signals.set_pieces else 0)
        + (10 if signals.team_news_found else 0)
        + min(15, signals.points_per_game * 2.5)
        + (10 if difficulty <= 2.6 else 0)
        - (25 if signals.flagged else 0)
    )))
    return out


def rank(signals: list[PlayerSignals]) -> list[Assessment]:
    """Every owned player, most sellable first. The starting point."""
    return sorted((assess(s) for s in signals),
                  key=lambda a: a.sell_urgency, reverse=True)


# --- risk-adjusted expectation -------------------------------------------

# How much a projection may be discounted for news the model cannot see.
# Small on purpose: the expected-points model already knows the player's
# minutes record, so this is the increment for a knock or an omission
# reported since, not a second full availability adjustment.
NEWS_DISCOUNT = {
    "injury": 0.88, "omission": 0.85, "rotation": 0.94, "transfer": 0.94,
}


# Plausibility bands for a five-gameweek transfer gain. A straight swap
# between two players of similar standing is a small edge; anything past
# "strong" is claiming the model has spotted something the whole market
# missed, and should have to prove it.
PLAUSIBILITY = (
    (3.0, "small edge"),
    (7.0, "meaningful"),
    (10.0, "strong"),
    (15.0, "exceptional — requires corroboration"),
)
EXTREME_GAIN = 15.0
# How far a projection may sit above a player's own recent scoring rate
# before it is pulled back toward it. Breakouts are real, so this shrinks
# overconfidence rather than removing it.
REGRESSION_CEILING = 2.0
REGRESSION_STRENGTH = 0.5

HIGH, MEDIUM, LOW = "High", "Medium", "Low"


def plausibility(gain_5gw: float) -> str:
    for ceiling, label in PLAUSIBILITY:
        if abs(gain_5gw) <= ceiling:
            return label
    return "extreme — automatically audited"


def projection_confidence(signals: PlayerSignals) -> str:
    """How much the number itself should be trusted.

    Separate from how good the player is. A projection built on two
    appearances, or on a player whose role changed last week, is a weaker
    claim than the same number from a settled starter with a season behind
    him — and a large gain resting on the weak one should not win.
    """
    demerits = 0
    if signals.minutes_category in ("Unassessed", "Major doubt", "Significant concern"):
        demerits += 2
    elif signals.minutes_category == "Slight concern":
        demerits += 1
    if signals.team_games and signals.appearances <= 1:
        demerits += 2                      # essentially no sample
    if signals.transfer_talk:
        demerits += 1                      # a move would reset everything
    if signals.rotation_talk:
        demerits += 1
    if signals.baseline and signals.projection > signals.baseline * REGRESSION_CEILING:
        demerits += 2                      # far above his own scoring rate
    if signals.evidence_count == 0:
        demerits += 1

    if demerits == 0:
        return HIGH
    return MEDIUM if demerits <= 2 else LOW


def regress(signals: PlayerSignals) -> tuple[float, str]:
    """Pulls a projection back toward the player's own scoring rate.

    Applies only above the ceiling, and only halfway, so a genuine
    breakout keeps most of its uplift while a number resting on one haul
    stops being treated as a settled fact.
    """
    projection = (signals.gameweek_projections[0] if signals.gameweek_projections
                  else signals.projection)
    baseline = signals.baseline
    if not baseline or projection <= baseline * REGRESSION_CEILING:
        return projection, ""
    pulled = projection - (projection - baseline * REGRESSION_CEILING) * REGRESSION_STRENGTH
    return round(pulled, 2), (
        f"projection {projection:.1f} regressed to {pulled:.1f} — more than "
        f"{REGRESSION_CEILING:.0f}x his own scoring rate of {baseline:.1f}")


def news_discount(signals: PlayerSignals) -> float:
    """The part of minutes risk the projection model cannot already see.

    This was the second double-count. `xp_next` is built from expected
    minutes — the model applies availability, start probability and
    rotation itself — and risk_adjusted() then multiplied the result by
    the minutes-category confidence AGAIN. A very secure starter came
    through unscathed while a doubtful one was penalised twice, which
    widened every gap between them.

    What remains legitimately outside the model is THIS WEEK'S REPORTING:
    a knock, an omission or a transfer saga that broke after the data was
    published. Only that is applied here.
    """
    factor = 1.0
    if signals.injury_talk:
        factor *= NEWS_DISCOUNT["injury"]
    if signals.omission_talk:
        factor *= NEWS_DISCOUNT["omission"]
    if signals.rotation_talk:
        factor *= NEWS_DISCOUNT["rotation"]
    if signals.transfer_talk:
        factor *= NEWS_DISCOUNT["transfer"]
    # A flagged player IS visible to the model, but the model is gentle
    # about it; a hard flag deserves more than the model's haircut.
    if signals.flagged:
        factor *= 0.6
    return factor


def risk_adjusted(signals: PlayerSignals) -> float:
    """This gameweek's projection, discounted only for news, not twice."""
    base = (signals.gameweek_projections[0] if signals.gameweek_projections
            else signals.projection)
    return round(base * news_discount(signals), 2)


def horizon_points(signals: PlayerSignals, weeks: int = 5) -> list[float]:
    """Per-gameweek expectation over the horizon.

    THE CALIBRATION FIX. This used to take a single projection and shade it
    by each gameweek's fixture difficulty — but `xp_next` is ALREADY
    fixture-adjusted, so difficulty was applied twice. A player with a kind
    run got the model's uplift and then another 12% per step on top of it,
    compounding across five gameweeks. That is what produced a +15.66
    five-gameweek delta for a straight defender swap.

    The expected-points model already publishes a per-gameweek series
    (`xp_gw*`), each entry fixture-adjusted for that specific gameweek.
    Using it directly removes the double count entirely. The shading path
    survives only as a fallback for callers with no series, and is applied
    at half strength because even then it is partly redundant.
    """
    discount = news_discount(signals)
    regressed, _ = regress(signals)
    series = signals.gameweek_projections
    if series:
        # Scale the whole series by whatever the first gameweek's
        # regression did, so a pulled-back projection stays pulled back
        # across the horizon rather than snapping back in gameweek two.
        scale = (regressed / series[0]) if series[0] else 1.0
        out = [round(value * scale * discount, 2) for value in series[:weeks]]
        # Pad a short series with its own tail rather than with zero: a
        # missing fifth gameweek is unknown, not a blank.
        while len(out) < weeks:
            out.append(out[-1] if out else 0.0)
        return out

    base = round(signals.projection * discount, 2)
    out = []
    for index in range(weeks):
        difficulty = (signals.fixture_scores[index]
                      if index < len(signals.fixture_scores) else 3.0)
        out.append(round(base * (1.0 + (3.0 - difficulty) * 0.06), 2))
    return out


def weighted_total(points: list[float]) -> float:
    return round(sum(p * w for p, w in zip(points, HORIZON_WEIGHTS)), 2)


@dataclass
class Option:
    """One complete decision — including doing nothing."""

    kind: str                       # "transfer", "roll", "package"
    out_player: str = ""
    in_player: str = ""
    second_out: str = ""
    second_in: str = ""
    classification: str = ""
    gain_this_gw: float = 0.0
    gain_3gw: float = 0.0
    gain_5gw: float = 0.0
    bank_after: float = 0.0
    hits: int = 0
    score: float = 0.0
    confidence: str = "low"
    components: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        if self.kind == "roll":
            return "Roll the transfer"
        if self.second_out:
            return (f"{self.out_player} + {self.second_out} → "
                    f"{self.in_player} + {self.second_in}")
        return f"{self.out_player} → {self.in_player}"

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "label": self.label,
            "classification": self.classification,
            "out": self.out_player, "in": self.in_player,
            "gain_this_gw": round(self.gain_this_gw, 2),
            "gain_3gw": round(self.gain_3gw, 2),
            "gain_5gw": round(self.gain_5gw, 2),
            "bank_after": round(self.bank_after, 1), "hits": self.hits,
            "score": round(self.score, 2), "confidence": self.confidence,
            "components": {k: round(v, 2) if isinstance(v, float) else v
                           for k, v in self.components.items()},
            "reasons": self.reasons, "risks": self.risks,
        }


def classify(out: Assessment, into: PlayerSignals, bank_after: float,
             gain_5gw: float) -> str:
    """What kind of move this is. Named so it can be questioned."""
    if out.forced or out.signals.flagged:
        return FORCED
    price_change = into.price - out.signals.price
    if price_change <= -1.0 and gain_5gw < 0.5:
        return BUDGET_RELEASE
    if into.fixture_difficulty <= 2.5 and out.signals.fixture_difficulty >= 3.5:
        return FIXTURE_SWING
    if gain_5gw >= 2.0 and price_change >= 0:
        return UPGRADE
    if abs(gain_5gw) < 1.0 and abs(price_change) < 1.0:
        return SIDEWAYS
    if price_change >= 2.0:
        return LUXURY
    return STRUCTURAL


def future_transfer_cost(into: PlayerSignals) -> tuple[float, list[str]]:
    """Penalises a move that will need undoing.

    One good fixture followed by four hard ones is not a transfer, it is
    two transfers with a delay in between, and the second one is not free.
    """
    cost, notes = 0.0, []
    scores = into.fixture_scores
    if len(scores) >= 4 and scores[0] <= 2.5 and sum(scores[1:4]) / 3 >= 3.7:
        cost += 1.5
        notes.append("one kind fixture then a hard run — likely to need reversing")
    if into.transfer_talk:
        cost += 0.8
        notes.append("transfer speculation around the incoming player")
    if into.minutes_category == "Unassessed":
        cost += 0.6
        notes.append("incoming player's minutes are unassessed")
    elif into.minutes_category in ("Significant concern", "Major doubt"):
        cost += 1.0
        notes.append(f"incoming player's minutes are a {into.minutes_category.lower()}")
    return cost, notes


def reversal_risk(out: Assessment, into: PlayerSignals) -> tuple[float, list[str]]:
    """The cost of selling someone you will want back.

    Selling a strong asset through a rough patch means buying him again at
    a higher price with a transfer you will not have. Hold strength is
    exactly the measure of how likely that is.
    """
    risk, notes = 0.0, []
    if out.hold_strength >= 65 and out.sell_urgency <= 45:
        risk += 2.0
        notes.append(f"{out.name} is a strong asset on current evidence — "
                     f"selling him now risks buying him back")
    elif out.hold_strength >= 50 and out.sell_urgency <= 55:
        risk += 1.0
        notes.append(f"{out.name} may need to be bought back")
    if out.signals.penalties:
        risk += 0.8
        notes.append(f"{out.name} takes penalties, which is hard to replace")
    return risk, notes


# --- building and comparing complete decisions ---------------------------

def build_option(out: Assessment, into: PlayerSignals, bank: float,
                 hits: int = 0, captain_upgrade: float = 0.0,
                 money_enables: str = "") -> Option:
    """Scores one candidate move end to end, with every term named."""
    out_points = horizon_points(out.signals)
    in_points = horizon_points(into)
    deltas = [i - o for i, o in zip(in_points, out_points)]

    option = Option(
        kind="transfer", out_player=out.name, in_player=into.name, hits=hits,
        gain_this_gw=deltas[0],
        gain_3gw=round(sum(deltas[:3]), 2),
        gain_5gw=round(sum(deltas), 2),
        bank_after=round(bank + out.signals.price - into.price, 1),
    )
    if option.bank_after < 0:
        option.risks.append("unaffordable")
        option.score = -99
        return option

    weighted_gain = weighted_total(deltas) * 5  # back to a 5-GW scale
    future_cost, future_notes = future_transfer_cost(into)
    reversal, reversal_notes = reversal_risk(out, into)

    option.classification = classify(out, into, option.bank_after, option.gain_5gw)

    # Structural benefit: releasing a bench player's dead money, or fixing
    # a genuine hole, is worth something the points model cannot see.
    structure = 0.0
    if out.signals.on_bench and out.signals.price >= 5.0:
        structure += 0.8
        option.reasons.append("frees money currently parked on the bench")
    if out.forced:
        structure += 1.5
        option.reasons.append("removes an unavailable player")

    # Money only counts if it does something.
    money_benefit = 0.0
    if option.classification == BUDGET_RELEASE:
        if money_enables:
            money_benefit = 0.8
            option.reasons.append(f"the money released enables: {money_enables}")
        else:
            money_benefit = -1.5
            option.risks.append(
                "this is a downgrade whose only benefit is money, and nothing "
                "was identified for the money to do")

    fixture_benefit = 0.0
    if option.classification == FIXTURE_SWING:
        fixture_benefit = 0.6
        option.reasons.append("swings the fixture run in the squad's favour")

    # Loss of a strong asset is a real cost, distinct from reversal risk.
    asset_loss = max(0.0, (out.hold_strength - 55) / 20.0)
    if asset_loss:
        option.risks.append(
            f"gives up {out.name}, whose hold strength is {out.hold_strength:.0f}")

    # What is actually OBSERVED against the outgoing player, as opposed to
    # computed about him. Only these may support overriding a hold.
    corroboration = []
    if out.signals.flagged:
        corroboration.append("he is flagged as unavailable")
    if out.signals.injury_talk:
        corroboration.append("an injury is reported this week")
    if out.signals.omission_talk:
        corroboration.append("he was left out of a recent squad")
    if out.signals.rotation_talk:
        corroboration.append("rotation risk is being reported")
    if out.signals.transfer_talk:
        corroboration.append("there is transfer speculation around him")
    if out.signals.minutes_category in ("Significant concern", "Major doubt"):
        corroboration.append(f"his expected minutes are a {out.signals.minutes_category.lower()}")
    if out.signals.fixture_difficulty >= 3.8:
        corroboration.append(
            f"his fixture run is hard (mean difficulty {out.signals.fixture_difficulty:.1f})")
    if out.signals.evidence_balance <= -0.34:
        corroboration.append("this week's reporting on him is predominantly cautionary")

    option.components = {
        "_corroboration": corroboration,
        "five_gw_gain": weighted_gain,
        "structure": structure,
        "captaincy": captain_upgrade,
        "money_enabled": money_benefit,
        "fixture_swing": fixture_benefit,
        "future_transfer_cost": -future_cost,
        "reversal_risk": -reversal,
        "asset_loss": -asset_loss,
        "hit_cost": -HIT_COST * hits,
    }
    option.score = round(sum(v for k, v in option.components.items()
                             if isinstance(v, (int, float))), 2)
    option.risks.extend(future_notes + reversal_notes)

    # Confidence follows the quality of what is known about both players.
    known = (into.minutes_category != "Unassessed",
             out.signals.minutes_category != "Unassessed")
    sources = min(into.source_count, out.signals.source_count)
    if all(known) and sources >= 3 and not into.transfer_talk:
        option.confidence = HIGH
    elif any(known) and sources >= 1:
        option.confidence = MEDIUM
    else:
        option.confidence = LOW

    # A move is never more trustworthy than the projections underneath it.
    weakest = min(
        (projection_confidence(into), projection_confidence(out.signals)),
        key=lambda level: {HIGH: 0, MEDIUM: 1, LOW: 2}[level])
    if {HIGH: 0, MEDIUM: 1, LOW: 2}[weakest] > {HIGH: 0, MEDIUM: 1, LOW: 2}[option.confidence]:
        option.confidence = weakest
    option.components["_plausibility"] = plausibility(option.gain_5gw)
    if option.confidence != "High":
        # Uncertainty must cost something, or the engine will always prefer
        # the exciting unknown to the boring known.
        option.score = round(option.score - (0.8 if option.confidence == "Medium" else 1.8), 2)
    return option


def roll_option(reason: str = "") -> Option:
    """Doing nothing, scored on the same scale as every move.

    The value is real: a transfer carried into next week is the option to
    react to news nobody has yet. Pricing it at zero is what made the old
    engine spend a transfer every week.
    """
    option = Option(kind="roll", classification="Roll", score=ROLL_VALUE,
                    confidence="High")
    option.components = {"transfer_flexibility_value": ROLL_VALUE}
    option.reasons.append(
        "keeps the transfer for next week, which is worth roughly "
        f"{ROLL_VALUE} points as the option to react to team news that has "
        "not been published yet")
    if reason:
        option.reasons.append(reason)
    return option


@dataclass
class Decision:
    """The full comparison, and the choice made from it."""

    assessments: list[Assessment] = field(default_factory=list)
    options: list[Option] = field(default_factory=list)
    winner: Option | None = None
    runner_up: Option | None = None
    sanity: list[str] = field(default_factory=list)

    @property
    def most_sellable(self) -> list[Assessment]:
        return self.assessments[:3]

    def as_dict(self) -> dict:
        return {
            "sell_urgency_ranking": [a.as_dict() for a in self.assessments],
            "options": [o.as_dict() for o in self.options],
            "winner": self.winner.as_dict() if self.winner else None,
            "runner_up": self.runner_up.as_dict() if self.runner_up else None,
            "sanity_checks": self.sanity,
        }


def decide(squad: list[PlayerSignals], targets: list[PlayerSignals],
           bank: float = 0.0, free_transfers: int = 1,
           captain_upgrade_for=None) -> Decision:
    """The whole engine: diagnose, generate, compare, choose.

    Every attractive target is tested against MULTIPLE outgoing players
    rather than against whichever one the money happens to fit. That is
    the specific fix — the old engine found a target, then searched for a
    victim, and the victim was chosen by price.
    """
    decision = Decision(assessments=rank(squad))
    by_name = {a.name: a for a in decision.assessments}
    owned_clubs: dict[str, int] = {}
    for player in squad:
        owned_clubs[player.club] = owned_clubs.get(player.club, 0) + 1

    for target in targets:
        if any(p.name == target.name for p in squad):
            continue
        # Test this target against every plausible outgoing player in the
        # same position, not just the affordable one.
        for candidate in decision.assessments:
            if candidate.signals.position != target.position:
                continue
            # Club limit: selling from a club at the cap frees a slot;
            # buying into one at the cap is illegal.
            after = dict(owned_clubs)
            after[candidate.signals.club] = after.get(candidate.signals.club, 1) - 1
            if after.get(target.club, 0) >= 3:
                continue
            hits = 0 if free_transfers >= 1 else 1
            captain_upgrade = (captain_upgrade_for(target, candidate)
                               if captain_upgrade_for else 0.0)
            option = build_option(candidate, target, bank, hits, captain_upgrade)
            if option.score > -50:
                decision.options.append(option)

    decision.options.append(roll_option())
    decision.options.sort(key=lambda o: o.score, reverse=True)
    decision.winner = decision.options[0] if decision.options else None
    decision.runner_up = decision.options[1] if len(decision.options) > 1 else None

    # A transfer must clearly beat rolling, not merely edge it.
    roll = next((o for o in decision.options if o.kind == "roll"), None)
    best_move = next((o for o in decision.options if o.kind == "transfer"), None)
    if decision.winner and decision.winner.kind == "transfer" and roll:
        if decision.winner.score - roll.score < MIN_GAIN_TO_ACT - ROLL_VALUE:
            decision.sanity.append(
                f"The best move scores {decision.winner.score} against "
                f"{roll.score} for rolling — inside the margin where a transfer "
                f"is not worth spending. Rolling is preferred.")
            decision.runner_up = decision.winner
            decision.winner = roll
    elif decision.winner and decision.winner.kind == "roll" and best_move:
        # Rolling won outright. Say why, rather than leaving the reader to
        # infer that no move was even considered.
        decision.sanity.append(
            f"The best available move ({best_move.label}) scores "
            f"{best_move.score} against {roll.score if roll else ROLL_VALUE} for "
            f"rolling, so it is not worth spending the transfer.")

    decision.sanity.extend(_sanity(decision, by_name))

    # The checklist is BINDING, not advisory. The first full-input
    # production run recommended selling a player its own sanity check
    # described as "not a squad problem being fixed" — the warning was
    # printed and the move was recommended anyway, which is worse than not
    # checking at all, because it looks like the check was considered.
    decision = _enforce(decision, by_name, roll)
    return decision


def _enforce(decision: Decision, by_name: dict, roll: Option | None) -> Decision:
    """Demotes a winner that fails its own checks, unless it is overwhelming.

    A strong asset may still be sold — nothing is protected absolutely —
    but the bar is a move that is clearly worth it, not one that edges
    ahead on a projection difference while the squad has no actual problem
    at that position.
    """
    winner = decision.winner
    if not winner or winner.kind != "transfer":
        return decision

    sold = by_name.get(winner.out_player)
    if sold is None:
        return decision

    failures = []
    if sold.sell_urgency <= 30:
        failures.append(f"{sold.name} is a {sold.band.lower()} at "
                        f"{sold.sell_urgency:.0f}/100 — no problem is being fixed")
    if sold.hold_strength >= 65:
        failures.append(f"{sold.name}'s hold strength is {sold.hold_strength:.0f}")
    if not failures:
        return decision

    # A projection alone may NOT override a hold. This is the rule the
    # Gabriel case exposed: the model claimed +15.7 over five gameweeks
    # for a straight defender swap, the checklist objected, and the size
    # of the number was allowed to settle it. A number is not evidence.
    #
    # An override now needs CORROBORATION — something someone observed
    # about the outgoing player or his situation — as well as size.
    corroboration = winner.components.get("_corroboration") or []
    large = winner.gain_5gw >= MIN_GAIN_TO_ACT * 2
    trusted = winner.confidence in (HIGH, MEDIUM)
    audited = abs(winner.gain_5gw) < EXTREME_GAIN

    if large and trusted and corroboration and audited:
        decision.sanity.append(
            f"Selling a well-held asset, and the checklist was overridden: "
            f"{winner.gain_5gw:+.1f} over five gameweeks ({plausibility(winner.gain_5gw)}) "
            f"at {winner.confidence.lower()} confidence, CORROBORATED by "
            + "; ".join(corroboration) + ". " + " · ".join(failures))
        return decision

    if large and not corroboration:
        failures.append(
            f"the only argument for the move is the model's own {winner.gain_5gw:+.1f}, "
            f"with nothing observed about {sold.name} to support it")
    if not audited:
        failures.append(
            f"a {winner.gain_5gw:+.1f} five-gameweek swing on a straight swap is "
            f"{plausibility(winner.gain_5gw)} and is not trusted without corroboration")

    alternatives = [
        option for option in decision.options
        if option is not winner
        and (option.kind == "roll"
             or (by_name.get(option.out_player) and
                 by_name[option.out_player].sell_urgency > 30))
    ]
    replacement = alternatives[0] if alternatives else (roll or winner)
    decision.sanity.append(
        f"REJECTED {winner.label}: " + " · ".join(failures)
        + f". Falling back to {replacement.label}, which either addresses a real "
        f"squad problem or keeps the transfer.")
    decision.runner_up = winner
    decision.winner = replacement
    return decision


def _sanity(decision: Decision, by_name: dict) -> list[str]:
    """The checklist, run before anything is published."""
    notes = []
    winner = decision.winner
    if not winner or winner.kind != "transfer":
        return notes

    sold = by_name.get(winner.out_player)
    if sold is None:
        return notes

    most_sellable = decision.assessments[0]
    if sold.name != most_sellable.name:
        notes.append(
            f"Not selling the most sellable player. {most_sellable.name} scores "
            f"{most_sellable.sell_urgency:.0f} against {sold.name}'s "
            f"{sold.sell_urgency:.0f} — the move must justify that, and does so "
            f"only if no affordable upgrade existed in {most_sellable.signals.position}.")
    if sold.hold_strength >= 65:
        notes.append(
            f"WARNING: {sold.name} has hold strength {sold.hold_strength:.0f}. "
            f"Selling a well-evidenced asset needs a compelling reason.")
    if sold.sell_urgency <= 30:
        notes.append(
            f"WARNING: {sold.name}'s sell urgency is only {sold.sell_urgency:.0f} "
            f"({sold.band}). This is not a squad problem being fixed.")
    if winner.gain_5gw < winner.gain_this_gw:
        notes.append(
            "The move is worth more this week than over five — check it is not "
            "a one-fixture punt that will need reversing.")
    return notes


def why_this_player_out(decision: Decision, winner: Option) -> str:
    """The mandatory answer: why THIS player and not the next two."""
    by_name = {a.name: a for a in decision.assessments}
    sold = by_name.get(winner.out_player)
    if sold is None:
        return ""
    others = [a for a in decision.assessments if a.name != sold.name][:2]
    if not others:
        return f"{sold.name} is the only realistic sale."

    parts = [
        f"{sold.name} scores {sold.sell_urgency:.0f}/100 for sell urgency "
        f"({sold.band})"
        + (f" — {'; '.join(sold.reasons[:2])}." if sold.reasons else ".")
    ]
    for other in others:
        if other.sell_urgency > sold.sell_urgency:
            parts.append(
                f"{other.name} scores higher at {other.sell_urgency:.0f}, so he is "
                f"the more obvious sale; he is kept here because no affordable "
                f"upgrade was found in his position this week.")
        else:
            parts.append(
                f"Not {other.name}: he scores {other.sell_urgency:.0f} "
                f"({other.band})"
                + (f", protected by {other.protections[0]}." if other.protections
                   else ", with nothing published against him."))
    return " ".join(parts)
