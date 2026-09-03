"""Complete plans, compared against each other, with the arithmetic exact.

This exists because the transfer engine kept producing recommendations its
own reasoning contradicted: selling a strong hold, preferring one Arsenal
defender to another on the strength of Arsenal's opponent, treating an
article about two other players as a reason to sell a third, and printing
ROLL at the top of a page whose next section said "make the move".

Those were not separate bugs. They were one missing idea: the engine
compared TRANSFERS, and a transfer is not a decision. A decision is a
PLAN — a complete description of the squad you will own, the money you
will hold, the free transfers you will carry and the points you will pay
for the privilege. Plans can be compared honestly; individual swaps
cannot, because a swap has no cost attached until you know how many you
are making.

So:

    STATE          the real squad, money, free transfers, verified
    DIAGNOSIS      every owned player assessed before any target is looked at
    PLANS          roll, best single, second single, best package
    ARITHMETIC     selling values, hits, bank — asserted, not assumed
    REJECTION      twelve rules that disqualify a plan outright
    ONE ANSWER     the winner, with every other plan visibly subordinate

Nothing here reads a player's name. A plan wins or loses on its own
numbers and on what the evidence actually establishes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fpl_assistant.analysis import squad_decision as sd

HIT_COST = 4.0

# What carrying a transfer into next week is worth. Not a fudge factor:
# it is the option to react to news that has not been published yet, and
# it is modelled as a fraction of a typical single-transfer gain because
# that is what the option is worth if you end up using it well.
TYPICAL_TRANSFER_GAIN = 4.0
FLEXIBILITY_SHARE = 0.4
ROLL_VALUE = round(TYPICAL_TRANSFER_GAIN * FLEXIBILITY_SHARE, 2)

# A plan must beat rolling by this much before it is worth acting on.
# Below it the two are a coin flip and the free transfer is worth more
# than the difference.
DECISION_MARGIN = 1.5
# Inside this band the engine says so rather than manufacturing certainty.
CLOSE_CALL_MARGIN = 0.75

MAX_FREE_TRANSFERS = 5

# The bands a manager can actually act on. An arbitrary 0-100 score is a
# debugging artefact, not a recommendation.
BANDS = (
    (12, "Strong hold"),
    (28, "Hold"),
    (45, "Monitor"),
    (60, "Possible sell"),
    (78, "Strong sell"),
    (100, "Urgent sell"),
)


def band(urgency: float) -> str:
    for ceiling, label in BANDS:
        if urgency <= ceiling:
            return label
    return BANDS[-1][1]


@dataclass
class Move:
    """One swap inside a plan, with both sides' real money."""

    out_name: str
    in_name: str
    out_club: str = ""
    in_club: str = ""
    position: str = ""
    selling_value: float = 0.0
    buy_price: float = 0.0
    out_5gw: float = 0.0
    in_5gw: float = 0.0
    # The per-gameweek series behind those totals, so "this week" and
    # "the next three" are read off the model rather than approximated as
    # a fraction of the five-week figure.
    out_series: list[float] = field(default_factory=list)
    in_series: list[float] = field(default_factory=list)
    reversal_risk: float = 0.0

    # The outgoing player's diagnosis, carried on the move so a rule can
    # ask "is a problem being fixed?" without looking anything up by name.
    out_urgency: float = 0.0
    out_hold: float = 0.0
    out_flagged: bool = False
    out_minutes: str = "Unassessed"
    in_minutes: str = "Unassessed"
    confidence: str = "Low"
    reasons: list["Reason"] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)

    @property
    def same_club(self) -> bool:
        return bool(self.out_club) and self.out_club == self.in_club

    @property
    def cash_delta(self) -> float:
        """Money released (positive) or spent (negative)."""
        return round(self.selling_value - self.buy_price, 1)

    @property
    def points_delta(self) -> float:
        return round(self.in_5gw - self.out_5gw, 2)

    def delta_over(self, weeks: int) -> float:
        """The gain over the first `weeks` gameweeks, from the series."""
        if not self.in_series or not self.out_series:
            return round(self.points_delta * weeks / 5, 2)
        pairs = list(zip(self.in_series[:weeks], self.out_series[:weeks]))
        return round(sum(i - o for i, o in pairs), 2)

    @property
    def label(self) -> str:
        return f"{self.out_name} → {self.in_name}"


@dataclass
class Plan:
    """A complete decision: what you own afterwards and what it cost."""

    kind: str                     # "roll" | "single" | "package"
    moves: list[Move] = field(default_factory=list)

    free_transfers: int = 1
    bank_before: float = 0.0

    gain_gw1: float = 0.0
    gain_3gw: float = 0.0
    gross_5gw: float = 0.0

    flexibility_value: float = 0.0
    reversal_risk: float = 0.0

    rejected: bool = False
    rejection_reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    confidence: str = "Medium"

    money_enables: str = ""

    # --- arithmetic -----------------------------------------------------

    @property
    def transfers_required(self) -> int:
        return len(self.moves)

    @property
    def paid_transfers(self) -> int:
        return max(0, self.transfers_required - self.free_transfers)

    @property
    def hit(self) -> float:
        return self.paid_transfers * HIT_COST

    @property
    def bank_after(self) -> float:
        return round(self.bank_before + sum(m.cash_delta for m in self.moves), 1)

    @property
    def free_transfers_after(self) -> int:
        used = min(self.transfers_required, self.free_transfers)
        return min(MAX_FREE_TRANSFERS, self.free_transfers - used + 1)

    @property
    def net_5gw(self) -> float:
        """The number that decides. Every cost is inside it."""
        return round(self.gross_5gw - self.hit + self.flexibility_value
                     - self.reversal_risk, 2)

    @property
    def net_gw1(self) -> float:
        return round(self.gain_gw1 - self.hit, 2)

    @property
    def affordable(self) -> bool:
        return self.bank_after >= -0.001

    @property
    def label(self) -> str:
        if self.kind == "roll":
            return "Roll the transfer"
        return " + ".join(m.label for m in self.moves)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "label": self.label,
            "moves": [{"out": m.out_name, "in": m.in_name,
                       "out_club": m.out_club, "in_club": m.in_club,
                       "same_club": m.same_club,
                       "selling_value": m.selling_value, "buy_price": m.buy_price,
                       "cash_delta": m.cash_delta, "points_delta": m.points_delta,
                       "out_urgency": round(m.out_urgency, 1),
                       "out_hold": round(m.out_hold, 1),
                       "confidence": m.confidence,
                       "reasons": [{"text": r.text, "about": r.about,
                                    "level": r.level, "kind": r.kind,
                                    "source": r.source} for r in m.reasons],
                       "excluded_reasons": m.excluded}
                      for m in self.moves],
            "free_transfers": self.free_transfers,
            "transfers_required": self.transfers_required,
            "paid_transfers": self.paid_transfers,
            "hit": self.hit,
            "bank_before": self.bank_before, "bank_after": self.bank_after,
            "free_transfers_after": self.free_transfers_after,
            "gain_gw1": round(self.gain_gw1, 2), "net_gw1": self.net_gw1,
            "gain_3gw": round(self.gain_3gw, 2),
            "gross_5gw": round(self.gross_5gw, 2), "net_5gw": self.net_5gw,
            "flexibility_value": self.flexibility_value,
            "reversal_risk": self.reversal_risk,
            "rejected": self.rejected, "rejection_reasons": self.rejection_reasons,
            "notes": self.notes, "confidence": self.confidence,
            "money_enables": self.money_enables,
        }


def verify_arithmetic(plan: Plan) -> list[str]:
    """Assertions, not assumptions. Impossible sums FAIL the plan.

    A recommendation whose money does not add up is worse than no
    recommendation, because it looks actionable.
    """
    problems = []
    if plan.bank_before < 0:
        problems.append("bank before the move is negative")
    if not plan.affordable:
        problems.append(
            f"unaffordable: £{plan.bank_after:.1f}m in the bank after the move")
    if plan.transfers_required and plan.paid_transfers > plan.transfers_required:
        problems.append("more paid transfers than transfers")
    if plan.hit != plan.paid_transfers * HIT_COST:
        problems.append("hit does not match the number of paid transfers")
    expected = round(plan.bank_before + sum(m.cash_delta for m in plan.moves), 1)
    if abs(plan.bank_after - expected) > 0.01:
        problems.append("bank after does not follow from the moves")
    for move in plan.moves:
        if move.selling_value <= 0 and plan.kind != "roll":
            problems.append(f"no selling value known for {move.out_name}")
        if move.buy_price <= 0 and plan.kind != "roll":
            problems.append(f"no price known for {move.in_name}")
    if plan.kind == "roll" and plan.moves:
        problems.append("a roll plan cannot contain moves")
    return problems


# --- what a piece of evidence is allowed to argue -------------------------

PLAYER_LEVEL = "player"
CLUB_LEVEL = "club"

FACT = "fact"
STATISTIC = "statistic"
EXPERT = "expert"
INFERENCE = "inference"

# Only these say something a manager did not already know from the fixture
# list. An inference is the engine's own reading and can never, on its own,
# override a hold.
OBSERVED = (FACT, STATISTIC, EXPERT)


@dataclass
class Reason:
    """One admissible-or-not argument, with its provenance attached.

    The `about` and `level` fields are the whole point. The engine used to
    hold a bag of sentences and reach into it for whatever sounded
    supportive, which is how an article about two City midfielders became
    a reason to sell a Bournemouth winger, and how Chelsea's goal tally
    became a reason to prefer one Arsenal defender to another. A sentence
    that is not about one of the two players in the move cannot argue for
    the move, and a sentence that is true of a whole club cannot
    distinguish two players who play for it.
    """

    text: str
    about: str
    level: str = PLAYER_LEVEL
    kind: str = INFERENCE
    source: str = ""

    @property
    def observed(self) -> bool:
        return self.kind in OBSERVED


def admissible(reasons: list[Reason], move: Move) -> tuple[list[Reason], list[str]]:
    """Splits reasons into those that can argue for this move, and why not.

    Returned second is a list of exclusions, kept so the page can say "we
    had eleven items about Arsenal and none of them separated these two
    players" instead of quietly using them.
    """
    kept, excluded = [], []
    subjects = {move.out_name, move.in_name}
    for reason in reasons:
        if reason.about not in subjects:
            excluded.append(
                f"'{reason.text}' is about {reason.about}, who is not part of "
                f"this move")
            continue
        if move.same_club and reason.level == CLUB_LEVEL:
            excluded.append(
                f"'{reason.text}' is true of {move.out_club} as a whole, so it "
                f"is equally true of {move.out_name} and {move.in_name}")
            continue
        kept.append(reason)
    return kept, excluded


def differentiating(reasons: list[Reason], move: Move) -> list[Reason]:
    """Reasons that actually separate the two players, not just describe one.

    For a same-club move this is the only admissible category: the
    fixtures are identical, the opponent is identical, the clean-sheet
    odds are identical. What is left is the player — his minutes, his set
    pieces, his role, his fitness.
    """
    kept, _ = admissible(reasons, move)
    return [r for r in kept if r.level == PLAYER_LEVEL and r.observed]


# --- the twelve hard rejection rules --------------------------------------
#
# A rejected plan is not "shown with a caveat". It is out. The old engine
# printed its own objections underneath the recommendation it was
# objecting to, which reads as though the objection was weighed and
# dismissed. These rules disqualify.

NO_PROBLEM_URGENCY = 30.0     # below this, nothing is being fixed
STRONG_HOLD = 65.0            # above this, the outgoing player is an asset
NOISE = 1.0                   # a 5-GW difference smaller than this is nothing
REAL_UPGRADE = 4.0            # what it takes to sell a player with no problem
HIT_CLEARANCE = 2.0           # a -4 must be beaten by this much, not matched
SECURE_MINUTES = ("Very secure", "Secure")
DOUBTFUL_MINUTES = ("Unassessed", "Significant concern", "Major doubt")


def _observed_about(move: Move, name: str) -> list[Reason]:
    return [r for r in move.reasons if r.about == name and r.observed]


def rule_affordable(plan: Plan) -> str | None:
    if not plan.affordable:
        return (f"it cannot be afforded — £{plan.bank_after:.1f}m in the bank "
                f"after the move")
    return None


def rule_arithmetic(plan: Plan) -> str | None:
    problems = verify_arithmetic(plan)
    if problems:
        return "the arithmetic does not hold: " + "; ".join(problems)
    return None


def rule_net_positive(plan: Plan) -> str | None:
    if plan.moves and plan.net_5gw <= 0:
        return (f"it loses points: {plan.gross_5gw:+.1f} over five gameweeks "
                f"before a {plan.hit:.0f}-point hit, {plan.net_5gw:+.1f} after")
    return None


def rule_hit_cleared(plan: Plan) -> str | None:
    if plan.hit and plan.gross_5gw < plan.hit + HIT_CLEARANCE:
        return (f"a {plan.hit:.0f}-point hit needs a gain of at least "
                f"{plan.hit + HIT_CLEARANCE:.0f} to be worth taking, and this "
                f"gains {plan.gross_5gw:+.1f}")
    return None


def rule_same_club_differentiated(plan: Plan) -> str | None:
    """The fixtures are identical. Something about the PLAYER must differ."""
    for move in plan.moves:
        if not move.same_club:
            continue
        separators = differentiating(move.reasons, move)
        if not separators:
            return (f"{move.out_name} and {move.in_name} both play for "
                    f"{move.out_club}, so they share every fixture, every "
                    f"opponent and the same clean-sheet odds — and nothing was "
                    f"found about either player that separates them")
    return None


def rule_evidence_exists(plan: Plan) -> str | None:
    for move in plan.moves:
        if not move.reasons:
            return (f"nothing published this week is about either "
                    f"{move.out_name} or {move.in_name}, so there is no "
                    f"evidence for this move — only a projection")
    return None


def rule_claim_corroborated(plan: Plan) -> str | None:
    """A claim big enough to drive a decision needs someone to have seen it.

    The engine's own projection is not evidence. It is a model output,
    and a model that says a £4.5m defender will out-score an established
    one by six points over five gameweeks is making a claim, not
    reporting a fact. A claim that large has to be corroborated on both
    sides of the swap: something observed about the player being sold,
    and something observed about the player being bought. Otherwise the
    number is arguing with itself.
    """
    for move in plan.moves:
        if move.out_flagged:
            continue
        driving = move.points_delta >= REAL_UPGRADE
        held = move.out_hold >= STRONG_HOLD
        if not (driving or held):
            continue
        if not _observed_about(move, move.out_name):
            reason = (f"a strong hold ({move.out_hold:.0f}/100)" if held else
                      f"{move.points_delta:+.1f} over five gameweeks")
            return (f"the case for selling {move.out_name} is {reason} and "
                    f"nothing published this week is about him — the engine's "
                    f"own projection is a claim, not evidence for it")
        if driving and not _observed_about(move, move.in_name):
            return (f"{move.in_name} is projected {move.points_delta:+.1f} "
                    f"better over five gameweeks and nothing published this "
                    f"week is about him to corroborate it")
    return None


def rule_problem_being_fixed(plan: Plan) -> str | None:
    """The diagnosis comes first, and a projection cannot overrule it.

    A projection argues for the INCOMING player. It says nothing about
    whether the outgoing one is a problem, so however large it is it
    cannot buy its way past a squad member with nothing wrong. This is
    the rule that stops a 0/100 hold being sold because someone cheaper
    modelled better.
    """
    for move in plan.moves:
        if move.out_flagged or move.out_urgency > NO_PROBLEM_URGENCY:
            continue
        if not _observed_about(move, move.out_name):
            return (f"{move.out_name} is not a problem — "
                    f"{move.out_urgency:.0f}/100 sell urgency, a "
                    f"{band(move.out_urgency).lower()}, and nothing published "
                    f"this week is about him. The entire case for the move is "
                    f"a projection about {move.in_name}")
        if move.points_delta < REAL_UPGRADE:
            return (f"{move.out_name} is not a problem "
                    f"({move.out_urgency:.0f}/100 sell urgency, "
                    f"{band(move.out_urgency).lower()}) and "
                    f"{move.in_name} is only {move.points_delta:+.1f} better "
                    f"over five gameweeks — that is not worth a transfer")
    return None


def rule_not_sideways(plan: Plan) -> str | None:
    if not plan.moves:
        return None
    if any(m.out_flagged for m in plan.moves):
        return None
    if all(abs(m.points_delta) < NOISE for m in plan.moves):
        return ("every swap in it is worth less than a point over five "
                "gameweeks, which is inside the model's own margin of error")
    return None


def rule_money_has_a_use(plan: Plan) -> str | None:
    for move in plan.moves:
        if move.cash_delta > 0 and move.points_delta < 0 and not plan.money_enables:
            return (f"it is a downgrade whose only benefit is the "
                    f"£{move.cash_delta:.1f}m it releases, and nothing was "
                    f"identified for that money to do")
    return None


def rule_confidence(plan: Plan) -> str | None:
    for move in plan.moves:
        if move.confidence != "Low":
            continue
        if not _observed_about(move, move.out_name) and not _observed_about(move, move.in_name):
            return (f"confidence in {move.label} is low and there is nothing "
                    f"observed about either player to raise it")
    return None


def rule_minutes_not_downgraded(plan: Plan) -> str | None:
    for move in plan.moves:
        if move.out_minutes not in SECURE_MINUTES:
            continue
        if move.in_minutes in DOUBTFUL_MINUTES and move.points_delta < REAL_UPGRADE:
            return (f"it swaps {move.out_name}, whose minutes are "
                    f"{move.out_minutes.lower()}, for {move.in_name}, whose "
                    f"minutes are {move.in_minutes.lower()}, for only "
                    f"{move.points_delta:+.1f} over five gameweeks")
    return None


REJECTION_RULES = (
    ("affordable", rule_affordable),
    ("arithmetic", rule_arithmetic),
    ("net_positive", rule_net_positive),
    ("hit_cleared", rule_hit_cleared),
    ("same_club", rule_same_club_differentiated),
    ("evidence_exists", rule_evidence_exists),
    ("corroboration", rule_claim_corroborated),
    ("problem_fixed", rule_problem_being_fixed),
    ("sideways", rule_not_sideways),
    ("money_use", rule_money_has_a_use),
    ("confidence", rule_confidence),
    ("minutes", rule_minutes_not_downgraded),
)


def reject(plan: Plan) -> Plan:
    """Runs every rule. A plan that fails any one of them is out."""
    for code, rule in REJECTION_RULES:
        reason = rule(plan)
        if reason:
            plan.rejected = True
            plan.rejection_reasons.append(f"{code}: {reason}")
    return plan


# --- the real current state ----------------------------------------------

@dataclass
class SquadState:
    """What is actually true right now, or an honest admission that it isn't.

    Everything downstream is arithmetic on these numbers, so a guess here
    becomes a confident lie three screens later. A missing selling price is
    the worst of them: FPL returns only half of any rise since purchase, so
    a plan costed on market price can be flatly unaffordable in reality.
    """

    bank: float = 0.0
    free_transfers: int = 1
    event: int = 0
    selling_values: dict = field(default_factory=dict)   # name -> £m
    purchase_values: dict = field(default_factory=dict)
    squad_size: int = 0
    # "api" when FPL gave the selling price outright, "exact" when the
    # squad's team value proves nobody has risen, "conservative" when the
    # split is unknown and every player is valued as though the whole
    # shortfall were his. Never a guess presented as a fact.
    selling_basis: str = "unknown"

    @property
    def missing(self) -> list[str]:
        gaps = []
        if self.squad_size != 15:
            gaps.append(f"squad has {self.squad_size} players, not 15")
        if self.event <= 0:
            gaps.append("the gameweek is unknown")
        if self.free_transfers < 1:
            gaps.append("free transfers are unknown")
        without = [n for n, v in self.selling_values.items() if not v]
        if without:
            gaps.append(
                f"no selling price for {len(without)} player(s): "
                + ", ".join(sorted(without)[:5]))
        if len(self.selling_values) != self.squad_size:
            gaps.append("selling prices were not supplied for the whole squad")
        return gaps

    @property
    def complete(self) -> bool:
        return not self.missing

    def selling_value(self, name: str, fallback: float = 0.0) -> float:
        return float(self.selling_values.get(name) or fallback)

    def as_dict(self) -> dict:
        return {"bank": self.bank, "free_transfers": self.free_transfers,
                "event": self.event, "squad_size": self.squad_size,
                "complete": self.complete, "missing": self.missing,
                "selling_basis": self.selling_basis,
                "selling_values": self.selling_values,
                "purchase_values": self.purchase_values}


# --- generating complete plans -------------------------------------------

def build_move(out: "sd.Assessment", into: "sd.PlayerSignals",
               state: SquadState, reasons: list[Reason] | None = None) -> Move:
    """One swap, priced in real money and scored over the real horizon."""
    out_series = sd.horizon_points(out.signals)
    in_series = sd.horizon_points(into)
    move = Move(
        out_name=out.name, in_name=into.name,
        out_club=out.signals.club, in_club=into.club,
        position=out.signals.position,
        selling_value=state.selling_value(out.name, out.signals.price),
        buy_price=into.price,
        out_5gw=round(sum(out_series), 2),
        in_5gw=round(sum(in_series), 2),
        out_series=out_series, in_series=in_series,
        reversal_risk=sd.reversal_risk(out, into)[0],
        out_urgency=out.sell_urgency,
        out_hold=out.hold_strength,
        out_flagged=out.signals.flagged or out.forced,
        out_minutes=out.signals.minutes_category,
        in_minutes=into.minutes_category,
    )
    move.reasons, move.excluded = admissible(reasons or [], move)
    move.confidence = _move_confidence(move, out.signals, into)
    return move


def _move_confidence(move: Move, out: "sd.PlayerSignals",
                     into: "sd.PlayerSignals") -> str:
    """How much of this move rests on something anyone actually saw."""
    observed = len([r for r in move.reasons if r.observed])
    known = (move.out_minutes != "Unassessed") + (move.in_minutes != "Unassessed")
    sources = min(out.source_count, into.source_count)
    if observed >= 2 and known == 2 and sources >= 3:
        return "High"
    if observed >= 1 and known >= 1:
        return "Medium"
    return "Low"


def _plan(kind: str, moves: list[Move], state: SquadState,
          money_enables: str = "") -> Plan:
    plan = Plan(kind=kind, moves=list(moves),
                free_transfers=state.free_transfers, bank_before=state.bank,
                money_enables=money_enables)
    plan.gain_gw1 = round(sum(m.delta_over(1) for m in moves), 2)
    plan.gain_3gw = round(sum(m.delta_over(3) for m in moves), 2)
    plan.gross_5gw = round(sum(m.points_delta for m in moves), 2)
    # Selling someone you will want back is a real cost: you buy him
    # again at a higher price with a transfer you no longer have.
    plan.reversal_risk = round(sum(m.reversal_risk for m in moves), 2)
    # Unused free transfers keep their option value; spent ones do not.
    unused = max(0, state.free_transfers - len(moves))
    plan.flexibility_value = round(min(unused, 1) * ROLL_VALUE, 2)
    plan.confidence = min((m.confidence for m in moves), default="High",
                          key=lambda c: {"High": 0, "Medium": 1, "Low": 2}[c])
    return plan


def roll_plan(state: SquadState, best_alternative: Plan | None = None) -> Plan:
    """Doing nothing, costed on the same scale as everything else."""
    plan = _plan("roll", [], state)
    plan.confidence = "High"
    plan.notes.append(
        f"Keeps the free transfer, worth about {ROLL_VALUE:.1f} points as the "
        f"option to react to team news that has not been published yet.")
    if best_alternative and best_alternative.moves:
        plan.notes.append(
            f"The best move available ({best_alternative.label}) is worth "
            f"{best_alternative.net_5gw:+.1f} over five gameweeks after costs.")
    return plan


def legal(move: Move, owned_clubs: dict) -> bool:
    """Club limit, checked after the sale frees its slot."""
    after = dict(owned_clubs)
    after[move.out_club] = after.get(move.out_club, 1) - 1
    return after.get(move.in_club, 0) < 3


def generate_plans(assessments: list, targets: list, state: SquadState,
                   reasons: list[Reason] | None = None) -> list[Plan]:
    """PLAN A roll, B best single, C second single, D best package.

    Every squad player is offered to every target in his position, so the
    outgoing player is chosen by diagnosis rather than by whichever sale
    happened to fit the budget.
    """
    reasons = reasons or []
    owned = {a.signals.club: 0 for a in assessments}
    for a in assessments:
        owned[a.signals.club] = owned.get(a.signals.club, 0) + 1
    owned_names = {a.name for a in assessments}

    singles: list[Plan] = []
    for target in targets:
        if target.name in owned_names:
            continue
        for out in assessments:
            if out.signals.position != target.position:
                continue
            move = build_move(out, target, state, reasons)
            if not legal(move, owned):
                continue
            candidate = _plan("single", [move], state)
            if candidate.bank_after < 0:
                continue
            singles.append(candidate)

    singles.sort(key=lambda p: p.net_5gw, reverse=True)
    survivors = [reject(p) for p in singles]
    clean = [p for p in survivors if not p.rejected]

    plans: list[Plan] = []
    best = clean[0] if clean else None
    plans.append(roll_plan(state, best))

    if best:
        plans.append(best)
        second = next((p for p in clean[1:]
                       if p.moves[0].out_name != best.moves[0].out_name), None)
        if second:
            plans.append(second)

        # A package is only generated when the second move stands on its own
        # merits too. Two mediocre moves and a -4 is how a season is lost.
        package = _package(clean, state)
        if package:
            plans.append(package)

    # Rejected singles are kept, visibly, so the page can show what was
    # considered and refused rather than implying nothing else existed.
    plans.extend(p for p in survivors if p.rejected)
    return plans


def _package(clean: list[Plan], state: SquadState) -> Plan | None:
    """The best pair of moves, costed with its hit fully visible."""
    for first in clean[:6]:
        for second in clean[1:8]:
            if second is first:
                continue
            a, b = first.moves[0], second.moves[0]
            if a.out_name == b.out_name or a.in_name == b.in_name:
                continue
            pair = _plan("package", [a, b], state)
            if pair.bank_after < 0:
                continue
            pair = reject(pair)
            if not pair.rejected:
                return pair
    return None


# --- one state, one decision ---------------------------------------------

@dataclass
class Recommendation:
    """The single answer, with everything else visibly subordinate to it."""

    state: SquadState
    winner: Plan
    alternatives: list[Plan] = field(default_factory=list)
    rejected: list[Plan] = field(default_factory=list)
    close_call: bool = False
    margin: float = 0.0
    notes: list[str] = field(default_factory=list)
    incomplete: list[str] = field(default_factory=list)

    @property
    def acting(self) -> bool:
        return bool(self.winner.moves)

    @property
    def out_names(self) -> set:
        return {m.out_name for m in self.winner.moves}

    @property
    def in_names(self) -> set:
        return {m.in_name for m in self.winner.moves}

    @property
    def verdict(self) -> str:
        if self.incomplete:
            return "INCOMPLETE — REQUIRED DATA MISSING"
        if not self.acting:
            return "Roll the transfer"
        if self.winner.hit:
            return f"{self.winner.label} (−{self.winner.hit:.0f})"
        return self.winner.label

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict, "acting": self.acting,
            "close_call": self.close_call, "margin": round(self.margin, 2),
            "state": self.state.as_dict(),
            "winner": self.winner.as_dict(),
            "alternatives": [p.as_dict() for p in self.alternatives],
            "rejected": [p.as_dict() for p in self.rejected],
            "notes": self.notes, "incomplete": self.incomplete,
        }


def choose(plans: list[Plan], state: SquadState) -> Recommendation:
    """Picks one plan and demotes the rest. No plan wins by default.

    Rolling is not privileged and is not handicapped: it carries its own
    option value, it is compared on the same net-points scale, and a move
    has to beat it by a real margin because a decision inside the model's
    own noise is not a decision.
    """
    roll = next((p for p in plans if p.kind == "roll"), None) or roll_plan(state)
    acting = sorted((p for p in plans
                     if p.kind != "roll" and not p.rejected),
                    key=lambda p: p.net_5gw, reverse=True)
    refused = [p for p in plans if p.rejected]

    rec = Recommendation(state=state, winner=roll, rejected=refused)
    rec.incomplete = state.missing

    if not acting:
        rec.alternatives = []
        rec.notes.append(
            "No transfer survived the checks this week, so the transfer is "
            "kept." if refused else
            "No transfer was found that improves the squad, so the transfer "
            "is kept.")
        return rec

    best = acting[0]
    rec.margin = round(best.net_5gw - roll.net_5gw, 2)

    if rec.margin >= DECISION_MARGIN:
        rec.winner = best
        rec.alternatives = [roll] + acting[1:4]
        rec.notes.append(
            f"{best.label} is worth {best.net_5gw:+.1f} points over five "
            f"gameweeks after costs, against {roll.net_5gw:+.1f} for keeping "
            f"the transfer — a margin of {rec.margin:+.1f}.")
    else:
        rec.winner = roll
        rec.alternatives = acting[:4]
        rec.notes.append(
            f"The best move available, {best.label}, is worth "
            f"{best.net_5gw:+.1f} over five gameweeks against "
            f"{roll.net_5gw:+.1f} for keeping the transfer. A margin of "
            f"{rec.margin:+.1f} is inside the model's own error, so the "
            f"transfer is kept.")

    rec.close_call = abs(rec.margin - DECISION_MARGIN) <= CLOSE_CALL_MARGIN
    if rec.close_call:
        rec.notes.append(
            "CLOSE CALL — this one is genuinely marginal, and a manager who "
            "did the opposite would not be making a mistake.")
    if len(acting) > 1 and abs(acting[0].net_5gw - acting[1].net_5gw) <= CLOSE_CALL_MARGIN:
        rec.notes.append(
            f"{acting[0].label} and {acting[1].label} are separated by "
            f"{abs(acting[0].net_5gw - acting[1].net_5gw):.1f} points — "
            f"effectively a tie.")
    return rec


# --- explaining the decision (not describing the players) -----------------

def explain(rec: Recommendation) -> dict:
    """Four questions, answered about the DECISION.

    Not a summary of what was read. A manager reading this should be able
    to say what he is doing, what it costs him, and what would change his
    mind — which is exactly what the old write-ups, full of true and
    irrelevant sentences, never told him.
    """
    if rec.incomplete:
        return {
            "headline": "INCOMPLETE — REQUIRED DATA MISSING",
            "problem": "The real squad state could not be established: "
                       + "; ".join(rec.incomplete) + ".",
            "gain": "No recommendation is made, because any recommendation "
                    "would be arithmetic on numbers that are not known.",
            "cost": "", "changes": "",
        }

    if not rec.acting:
        best = next((p for p in rec.alternatives if p.moves), None)
        problem = ("Nothing in the squad needs fixing badly enough to spend a "
                   "transfer on it this week.")
        if rec.rejected:
            worst = rec.rejected[0]
            problem += (f" The strongest-looking move, {worst.label}, was "
                        f"refused because {worst.rejection_reasons[0].split(': ', 1)[-1]}.")
        gain = (f"Keeping the transfer is worth about {ROLL_VALUE:.1f} points "
                f"as the option to react to news that has not been published "
                f"yet.")
        if best:
            gain += (f" The best alternative, {best.label}, comes to "
                     f"{best.net_5gw:+.1f} over five gameweeks after costs.")
        return {
            "headline": "Roll the transfer",
            "problem": problem, "gain": gain,
            "cost": "Nothing. You go into next week with "
                    f"{rec.winner.free_transfers_after} free transfers and "
                    f"£{rec.winner.bank_after:.1f}m in the bank.",
            "changes": "A new injury, a dropped player or a confirmed change "
                       "of role would reopen this before the deadline.",
        }

    plan = rec.winner
    problems, gains = [], []
    for move in plan.moves:
        observed = [r.text for r in move.reasons
                    if r.about == move.out_name and r.observed]
        if move.out_flagged:
            problems.append(f"{move.out_name} is unavailable")
        elif observed:
            problems.append(f"{move.out_name}: " + "; ".join(observed[:2]))
        else:
            problems.append(
                f"{move.out_name} is a {band(move.out_urgency).lower()} at "
                f"{move.out_urgency:.0f}/100")
        into = [r.text for r in move.reasons
                if r.about == move.in_name and r.observed]
        line = (f"{move.in_name} projects {move.points_delta:+.1f} points more "
                f"over five gameweeks")
        if into:
            line += " — " + "; ".join(into[:2])
        if move.same_club:
            line += (f" (both play for {move.in_club}, so the fixtures are "
                     f"identical and only the players differ)")
        gains.append(line)

    cost = (f"£{plan.bank_after:.1f}m left in the bank and "
            f"{plan.free_transfers_after} free transfer"
            f"{'s' if plan.free_transfers_after != 1 else ''} next week")
    if plan.hit:
        cost = (f"A {plan.hit:.0f}-point hit — {plan.paid_transfers} transfer"
                f"{'s' if plan.paid_transfers != 1 else ''} beyond the free one, "
                f"at four real points each. The gain has to clear that before "
                f"anything else. After it: " + cost + ".")
    else:
        cost = "No hit — this is within your free transfers. Leaves " + cost + "."

    changes = []
    if plan.confidence != "High":
        changes.append(f"confidence here is {plan.confidence.lower()}")
    if rec.close_call:
        changes.append("the margin over rolling is small enough that late news "
                       "could flip it")
    for move in plan.moves:
        if move.in_minutes in DOUBTFUL_MINUTES:
            changes.append(f"{move.in_name}'s minutes are {move.in_minutes.lower()}")
    changes_text = ("Would change this: " + "; ".join(changes) + "."
                    if changes else
                    "A press-conference injury to either player before the "
                    "deadline would change this.")

    return {
        "headline": rec.verdict,
        "problem": " · ".join(problems),
        "gain": " · ".join(gains),
        "cost": cost,
        "changes": changes_text,
    }


# --- contradiction scan ---------------------------------------------------

ACT_PHRASES = ("make the move", "make this move", "bring him in", "get him in",
               "worth doing", "do it this week", "pull the trigger",
               "should be transferred in", "buy him")
HOLD_PHRASES = ("roll the transfer", "keep the transfer", "save the transfer",
                "do nothing this week", "no move is needed")
SELL_PHRASES = ("sell him", "move him on", "get him out", "ship him out",
                "time to sell", "should be sold", "is the one to move on",
                "the obvious sale", "cash him in")


def contradictions(rec: Recommendation, blocks: list,
                   known_names: set | None = None) -> list[str]:
    """Reads the page back and refuses to publish it if it argues with itself.

    Every block is (label, text). The test is not stylistic: it is whether
    a reader following the words would take a different action from the one
    the engine decided.
    """
    problems = []
    # Every squad member, not only the ones a plan happened to mention:
    # a card can recommend selling a player no plan ever considered, and
    # that is exactly the contradiction worth catching.
    names = set(known_names or ()) | _names_in(rec)
    for label, text in blocks:
        low = (text or "").lower()
        if not low:
            continue
        if not rec.acting:
            for phrase in ACT_PHRASES:
                if phrase in low:
                    problems.append(
                        f"{label} says '{phrase}' while the decision is to "
                        f"roll the transfer")
        else:
            for phrase in HOLD_PHRASES:
                if phrase in low:
                    problems.append(
                        f"{label} says '{phrase}' while the decision is "
                        f"{rec.verdict}")
        for phrase in SELL_PHRASES:
            if phrase not in low:
                continue
            named = [n for n in names if n.lower() in low]
            wrongly = [n for n in named if n not in rec.out_names]
            if wrongly:
                problems.append(
                    f"{label} says '{phrase}' about {', '.join(wrongly)}, who "
                    f"the decision keeps")
    return problems


def _names_in(rec: Recommendation) -> set:
    names = set(rec.out_names) | set(rec.in_names)
    for plan in list(rec.alternatives) + list(rec.rejected):
        for move in plan.moves:
            names.add(move.out_name)
            names.add(move.in_name)
    return names


# --- the trust audit ------------------------------------------------------

def trust_audit(rec: Recommendation, blocks: list | None = None,
                known_names: set | None = None) -> list[tuple]:
    """Ten questions that must all answer YES before anything is published.

    Run against the real recommendation, not against a fixture. A NO here
    is a stop, not a caveat to print underneath the recommendation.
    """
    plan = rec.winner
    blocks = blocks or []
    checks = []

    checks.append((
        "Is the current squad state real — bank, free transfers, selling prices?",
        not rec.incomplete,
        "; ".join(rec.incomplete) or
        f"£{rec.state.bank:.1f}m, {rec.state.free_transfers} free transfer(s), "
        f"{len(rec.state.selling_values)} selling prices ({rec.state.selling_basis})"))

    fixes = (not rec.acting
             or all(m.out_flagged or m.out_urgency > NO_PROBLEM_URGENCY
                    or m.points_delta >= REAL_UPGRADE for m in plan.moves))
    checks.append((
        "Is an actual squad problem being fixed?", fixes,
        "no move is made" if not rec.acting else
        "; ".join(f"{m.out_name} {m.out_urgency:.0f}/100" for m in plan.moves)))

    scoped = all(r.about in {m.out_name, m.in_name}
                 for m in plan.moves for r in m.reasons)
    checks.append((
        "Is every cited item about a player in the move?", scoped,
        f"{sum(len(m.reasons) for m in plan.moves)} item(s) admitted, "
        f"{sum(len(m.excluded) for m in plan.moves)} excluded as off-subject "
        f"or club-level"))

    same_club_ok = all(differentiating(m.reasons, m)
                       for m in plan.moves if m.same_club)
    checks.append((
        "Does any same-club move rest on a player-level difference?",
        same_club_ok,
        "no same-club move" if not any(m.same_club for m in plan.moves)
        else "differentiated"))

    checks.append((
        "Is the transfer hit counted as four real points?",
        plan.hit == plan.paid_transfers * HIT_COST,
        f"{plan.paid_transfers} paid transfer(s) = {plan.hit:.0f} points, "
        f"subtracted inside net_5gw"))

    money = verify_arithmetic(plan)
    checks.append((
        "Does the money add up against real selling values?", not money,
        "; ".join(money) or
        f"£{plan.bank_before:.1f}m → £{plan.bank_after:.1f}m"))

    checks.append((
        "Was rolling considered and priced honestly?",
        any(p.kind == "roll" for p in [plan] + rec.alternatives),
        f"roll valued at {ROLL_VALUE:.1f}, margin {rec.margin:+.1f}"))

    checks.append((
        "Is there exactly one recommendation?", True,
        f"'{rec.verdict}', with {len(rec.alternatives)} alternative(s) and "
        f"{len(rec.rejected)} rejected plan(s) shown as subordinate"))

    clashes = contradictions(rec, blocks, known_names)
    checks.append((
        "Does any generated text contradict the recommendation?", not clashes,
        "; ".join(clashes) or f"{len(blocks)} block(s) scanned, none contradict"))

    honest = (rec.close_call is False) or any(
        "CLOSE CALL" in n for n in rec.notes)
    checks.append((
        "Is uncertainty stated where it exists?", honest,
        f"confidence {plan.confidence}"
        + (", flagged as a close call" if rec.close_call else "")))

    return checks


def audit_passed(checks: list[tuple]) -> bool:
    return all(ok for _, ok, _ in checks)
