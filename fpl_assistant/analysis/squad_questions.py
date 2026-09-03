"""Direct questions about the squad, answered from the current state.

"Will Ndiaye start?" is the question this app exists to answer, and the
old engine answered it from a cached write-up — which is to say from
whatever was true the last time somebody generated prose. That is the
same failure as the rest of the freshness work in one screen: the answer
was fluent, confident, and built on a record from a different club.

So every answer here is read off the SAME committed state the page
renders: the Current Status Pass, the transfer plan, the write-ups. There
is one truth and two ways of asking for it, which is the only way the
answer and the card underneath it cannot disagree.

Routing is local and deterministic — a pattern table, not a model. That
keeps it exact about who is in the squad, instant, and free. When the
state behind an answer has not been re-checked recently the answer says
so rather than dressing age up as certainty.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- what is being asked -------------------------------------------------

WILL_START = "will_start"
COMPARE = "compare"
SHOULD_START = "should_start"
WHY_KEEP = "why_keep"
WHY_SELL = "why_sell"
WHO_SELL = "who_sell"
CAPTAIN = "captain"
WHY_ROLL = "why_roll"
SHOULD_TRANSFER = "should_transfer"
BEST_RUN = "best_run"
ROTATION_RISK = "rotation_risk"
WEAKEST = "weakest"
UNKNOWN = "unknown"

# Ordered: the first match wins, so the specific shapes are tested before
# the general ones. "Should I start X or Y" is a comparison, not a
# starting question, and testing them the other way round answers about
# one player and ignores the other.
INTENT_PATTERNS = (
    (COMPARE, (r"\bor\b.*\?", r"\bvs\.?\b", r"\bversus\b",
               r"\bwho.{0,20}\bbetter\b")),
    # Before WILL_START: "who is most at risk of not starting?" contains
    # "starting" and is a squad-wide question, not one about a player.
    (ROTATION_RISK, (r"\brotation\b", r"\bmost at risk\b", r"\brisk of not\b",
                     r"\bwho might not\b", r"\bat risk\b")),
    (WILL_START, (r"\bwill\b.{0,30}\bstart\b", r"\bis\b.{0,30}\bstarting\b",
                  r"\bdoes\b.{0,30}\bstart\b", r"\bstarting\b.{0,10}\?")),
    (CAPTAIN, (r"\bcaptain\b", r"\barmband\b", r"\btriple captain\b")),
    (WHY_ROLL, (r"\broll\b", r"\bsave (?:my|the) transfer\b",
                r"\bbank (?:my|the) transfer\b")),
    (SHOULD_TRANSFER, (r"\bshould i (?:make|do)\b", r"→", r"\bswap\b",
                       r"\btransfer\b.{0,20}\bfor\b", r"\bbring in\b")),
    (WHO_SELL, (r"\bwho should i sell\b", r"\bwho do i sell\b",
                r"\bwho to sell\b", r"\bwho should i (?:move|ship)\b")),
    (WEAKEST, (r"\bweakest\b", r"\bworst\b", r"\bbiggest problem\b")),
    (WHY_SELL, (r"\bwhy.{0,25}\bsell(?:ing)?\b",
                r"\bwhy.{0,25}\bmov(?:e|ing) on\b")),
    (WHY_KEEP, (r"\bwhy.{0,25}\bkeep(?:ing)?\b",
                r"\bwhy.{0,25}\bhold(?:ing)?\b",
                r"\bwhy is\b.{0,25}\bin\b", r"\bwhy.{0,25}\bstill (?:own|have)\b")),
    (BEST_RUN, (r"\bnext four\b", r"\bnext 4\b", r"\bbest run\b",
                r"\bbest fixtures\b")),
    (SHOULD_START, (r"\bshould i start\b", r"\bstart or bench\b",
                    r"\bshould i bench\b", r"\bbench\b")),
)

SUGGESTIONS = (
    "Will Ndiaye start?",
    "Why am I keeping Gabriel?",
    "Who should I captain?",
    "Who is my weakest player?",
    "Should I roll?",
    "Thiago or Ndiaye?",
)


def intent(question: str) -> str:
    text = (question or "").lower()
    for name, patterns in INTENT_PATTERNS:
        if any(re.search(pattern, text) for pattern in patterns):
            return name
    return UNKNOWN


def players_in(question: str, known: list) -> list:
    """Which squad members the question names, in the order asked.

    Matched against the squad rather than against every player in the
    game, because the questions here are about a team someone owns and a
    loose match on a common surname answers about somebody else's.
    """
    text = (question or "").lower()
    found = []
    for name in known:
        needle = str(name).lower()
        if len(needle) < 3:
            continue
        if re.search(rf"(?<![a-z]){re.escape(needle)}(?![a-z])", text):
            found.append((text.index(needle), name))
    return [name for _, name in sorted(found)]


@dataclass
class Answer:
    """One question, answered in the shape a manager reads."""

    question: str = ""
    intent: str = UNKNOWN
    headline: str = ""
    short_answer: str = ""
    why: str = ""
    call: str = ""
    expected_minutes: str = ""
    confidence: str = ""
    caveat: str = ""
    evidence: list = field(default_factory=list)
    players: list = field(default_factory=list)

    @property
    def answered(self) -> bool:
        return bool(self.short_answer)

    def as_dict(self) -> dict:
        return {"question": self.question, "intent": self.intent,
                "headline": self.headline, "short_answer": self.short_answer,
                "why": self.why, "call": self.call,
                "expected_minutes": self.expected_minutes,
                "confidence": self.confidence, "caveat": self.caveat,
                "players": self.players, "evidence": self.evidence[:6]}


# --- answering, from the state the page is already showing ---------------

def answer(question: str, decision: dict) -> Answer:
    """One answer, read off the committed decision rather than composed.

    `decision` is the file the homepage renders — the status pass, the
    write-ups, the transfer plan. Reading the same object is what makes
    it impossible for the answer to contradict the card underneath it,
    which is a stronger guarantee than generating consistent prose twice.
    """
    statuses = decision.get("player_status") or {}
    facts = decision.get("player_facts") or {}
    recommendation = decision.get("recommendation") or {}
    squad = [name for name in facts]
    kind = intent(question)
    named = players_in(question, squad or list(statuses))
    result = Answer(question=question, intent=kind, players=named)

    if kind == WILL_START and named:
        return _will_start(result, statuses.get(named[0], {}), named[0])
    if kind in (SHOULD_START,) and named:
        return _should_start(result, statuses.get(named[0], {}),
                             facts.get(named[0], {}), named[0])
    if kind == COMPARE and len(named) >= 2:
        return _compare(result, statuses, facts, named[:2])
    if kind in (WHY_KEEP, WHY_SELL) and named:
        return _why_kept(result, facts.get(named[0], {}),
                         statuses.get(named[0], {}), recommendation, named[0])
    if kind == CAPTAIN:
        return _captain(result, facts, statuses)
    if kind == WHY_ROLL:
        return _roll(result, decision)
    if kind == SHOULD_TRANSFER:
        return _transfer(result, decision, named)
    if kind in (WHO_SELL, WEAKEST):
        return _weakest(result, decision)
    if kind == ROTATION_RISK:
        return _rotation(result, statuses)
    if kind == BEST_RUN:
        return _best_run(result, facts)

    result.headline = question.strip().upper()
    result.short_answer = (
        "I could not tell what that was asking about. Try naming a player, or "
        "one of the suggestions below.")
    return result


def _freshness_caveat(status: dict) -> str:
    """What the answer is resting on, and whether it has aged."""
    if not status:
        return "No current status has been recorded for him."
    basis = status.get("basis") or "the appearance record"
    if status.get("stale"):
        return (f"This rests on {basis} and has not been re-checked recently — "
                f"press Refresh Research before the deadline.")
    return f"This rests on {basis}."


def _will_start(result: Answer, status: dict, name: str) -> Answer:
    result.headline = f"WILL {name.upper()} START?"
    if not status:
        result.short_answer = f"I have no current status recorded for {name}."
        return result

    outlook = status.get("outlook", "")
    lineups = status.get("lineups") or {}
    short = {
        "Very likely to start": "Yes — as close to certain as this gets.",
        "Likely to start": "Probably, though it is not confirmed.",
        "50-50": "Genuinely uncertain — this one is a coin flip.",
        "Likely bench": "Probably not, on the latest evidence.",
        "Very unlikely to start": "Almost certainly not.",
        "Out": "No — he is unavailable.",
    }.get(outlook, "Unclear on the evidence available.")

    why = list(status.get("vetoes") or []) + list(status.get("reasons") or [])
    if lineups.get("readable"):
        why.insert(0, lineups["summary"])
    result.short_answer = short
    result.why = " ".join(_sentence(part) for part in why[:3])
    result.call = outlook.upper()
    result.expected_minutes = status.get("minutes_label", "")
    result.confidence = status.get("confidence", "")
    result.caveat = _freshness_caveat(status)
    result.evidence = status.get("evidence") or []
    return result


def _should_start(result: Answer, status: dict, fact: dict, name: str) -> Answer:
    result.headline = f"SHOULD I START {name.upper()}?"
    brief = fact.get("brief") or {}
    outlook = status.get("outlook", "")
    starting = outlook in ("Very likely to start", "Likely to start")
    result.short_answer = (
        f"Start him — {outlook.lower()} at {status.get('minutes_label', '')}."
        if starting else
        f"Only if the alternative is worse: he is {outlook.lower()}.")
    result.why = brief.get("why", "") or " ".join(
        _sentence(r) for r in (status.get("reasons") or [])[:2])
    result.call = brief.get("verdict_label", "") or (
        "START" if starting else "BENCH")
    result.expected_minutes = status.get("minutes_label", "")
    result.confidence = status.get("confidence", "")
    result.caveat = _freshness_caveat(status)
    result.evidence = status.get("evidence") or []
    return result


def _compare(result: Answer, statuses: dict, facts: dict, pair: list) -> Answer:
    first, second = pair
    result.headline = f"{first.upper()} OR {second.upper()}?"
    left, right = statuses.get(first, {}), statuses.get(second, {})
    order = {"Very likely to start": 5, "Likely to start": 4, "50-50": 3,
             "Likely bench": 2, "Very unlikely to start": 1, "Out": 0}

    def value(status, name):
        share = float(status.get("expected_share", 0.6) or 0.6)
        brief = (facts.get(name) or {}).get("brief") or {}
        return share, order.get(status.get("outlook", ""), 3), brief

    left_share, left_rank, _ = value(left, first)
    right_share, right_rank, _ = value(right, second)
    winner, loser = ((first, second) if (left_share, left_rank) >= (right_share, right_rank)
                     else (second, first))
    won, lost = (left, right) if winner == first else (right, left)

    if abs(left_share - right_share) < 0.08:
        result.short_answer = (
            f"There is very little in it — {first} is {left.get('outlook', '').lower()} "
            f"and {second} is {right.get('outlook', '').lower()}.")
    else:
        result.short_answer = (
            f"{winner}. He is {won.get('outlook', '').lower()} "
            f"({won.get('minutes_label', '')}) against {loser} at "
            f"{lost.get('outlook', '').lower()}.")
    result.why = " ".join(_sentence(r) for r in (won.get("reasons") or [])[:2])
    result.call = winner.upper()
    result.expected_minutes = (
        f"{first}: {left.get('minutes_label', '?')} · "
        f"{second}: {right.get('minutes_label', '?')}")
    result.confidence = _weaker(won.get("confidence"), lost.get("confidence"))
    result.caveat = _freshness_caveat(won)
    result.evidence = (won.get("evidence") or [])[:3] + (lost.get("evidence") or [])[:3]
    return result


def _weaker(first: str, second: str) -> str:
    order = {"High": 0, "Medium": 1, "Low": 2}
    return first if order.get(first, 2) >= order.get(second, 2) else second


def _sentence(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def _why_kept(result: Answer, fact: dict, status: dict, recommendation: dict,
              name: str) -> Answer:
    brief = fact.get("brief") or {}
    winner = recommendation.get("winner") or {}
    being_sold = any(move.get("out") == name for move in winner.get("moves", []))
    result.headline = (f"WHY AM I SELLING {name.upper()}?" if being_sold
                       else f"WHY AM I KEEPING {name.upper()}?")
    if being_sold:
        result.short_answer = (
            f"The plan does move him on this week — see the transfer plan.")
    else:
        # The label is left exactly as the engine set it. Title-casing a
        # decision produced "Vice-Captaincy" once and it read as a
        # different word.
        result.short_answer = (
            f"Because nothing is wrong with him that is worth a transfer — "
            f"{brief.get('verdict_label', 'KEEP')}.")
    result.why = brief.get("verdict", "") or brief.get("why", "")
    result.call = brief.get("verdict_label", "KEEP")
    result.expected_minutes = status.get("minutes_label", "")
    result.confidence = brief.get("confidence") or status.get("confidence", "")
    result.caveat = brief.get("against", "")
    result.evidence = status.get("evidence") or []
    return result


def _captain(result: Answer, facts: dict, statuses: dict) -> Answer:
    result.headline = "WHO SHOULD I CAPTAIN?"
    named = [(name, fact) for name, fact in facts.items()
             if (fact.get("brief") or {}).get("verdict_label") == "CAPTAIN"]
    if not named:
        result.short_answer = "No captain has been set in the current plan."
        return result
    name, fact = named[0]
    brief = fact.get("brief") or {}
    status = statuses.get(name, {})
    result.short_answer = f"{name}."
    result.why = brief.get("case_for", "")
    result.call = f"CAPTAIN {name.upper()}"
    result.expected_minutes = status.get("minutes_label", "")
    result.confidence = brief.get("confidence", "")
    result.caveat = brief.get("against", "")
    result.players = [name]
    result.evidence = status.get("evidence") or []
    return result


def _roll(result: Answer, decision: dict) -> Answer:
    recommendation = decision.get("recommendation") or {}
    explanation = decision.get("explanation") or {}
    winner = recommendation.get("winner") or {}
    rolling = not winner.get("moves")
    result.headline = "SHOULD I ROLL MY TRANSFER?"
    result.short_answer = (
        "Yes — that is the recommendation this week."
        if rolling else
        f"No. The plan is {recommendation.get('verdict', 'a transfer')}.")
    result.why = explanation.get("problem", "") + " " + explanation.get("gain", "")
    result.call = "ROLL" if rolling else recommendation.get("verdict", "").upper()
    result.confidence = winner.get("confidence", "")
    result.caveat = explanation.get("changes", "")
    return result


def _transfer(result: Answer, decision: dict, named: list) -> Answer:
    recommendation = decision.get("recommendation") or {}
    result.headline = "SHOULD I MAKE THAT TRANSFER?"
    wanted = set(named)
    for plan in recommendation.get("rejected", []):
        for move in plan.get("moves", []):
            if {move.get("out"), move.get("in")} & wanted:
                reason = (plan.get("rejection_reasons") or [""])[0]
                result.short_answer = (
                    f"No — {plan.get('label')} was costed and refused.")
                result.why = _sentence(reason.split(": ", 1)[-1])
                result.call = "DO NOT MAKE THAT MOVE"
                return result
    winner = recommendation.get("winner") or {}
    for move in winner.get("moves", []):
        if {move.get("out"), move.get("in")} & wanted:
            result.short_answer = f"Yes — {recommendation.get('verdict')}."
            result.call = recommendation.get("verdict", "").upper()
            return result
    result.short_answer = (
        f"That move was not among the plans considered. The recommendation is "
        f"{recommendation.get('verdict', 'to roll')}.")
    result.call = recommendation.get("verdict", "").upper()
    return result


def _weakest(result: Answer, decision: dict) -> Answer:
    ranking = decision.get("sell_urgency_ranking") or []
    result.headline = "WHO IS MY WEAKEST PLAYER?"
    if not ranking:
        result.short_answer = "No sell-urgency ranking has been generated."
        return result
    top = ranking[0]
    result.short_answer = (
        f"{top['player']} — {top['sell_urgency']:.0f}/100 for sell urgency "
        f"({top['band'].lower()}).")
    result.why = " ".join(_sentence(r) for r in (top.get("reasons") or [])[:2])
    result.call = top["band"].upper()
    result.players = [top["player"]]
    others = ", ".join(f"{row['player']} {row['sell_urgency']:.0f}"
                       for row in ranking[1:4])
    result.caveat = f"Next: {others}." if others else ""
    return result


def _rotation(result: Answer, statuses: dict) -> Answer:
    result.headline = "WHO IS MOST AT RISK OF NOT STARTING?"
    ranked = sorted(statuses.items(),
                    key=lambda kv: float(kv[1].get("expected_share", 1.0) or 1.0))
    at_risk = [(name, status) for name, status in ranked
               if float(status.get("expected_share", 1.0) or 1.0) < 0.9]
    if not at_risk:
        result.short_answer = (
            "Nobody in the squad is a serious doubt on current evidence.")
        return result
    name, status = at_risk[0]
    result.short_answer = (
        f"{name} — {status.get('outlook', '').lower()}, "
        f"{status.get('minutes_label', '')}.")
    result.why = " ".join(
        _sentence(r) for r in ((status.get("vetoes") or [])
                               + (status.get("reasons") or []))[:2])
    result.call = status.get("outlook", "").upper()
    result.expected_minutes = status.get("minutes_label", "")
    result.confidence = status.get("confidence", "")
    result.players = [name for name, _ in at_risk[:3]]
    result.caveat = "Then: " + ", ".join(
        f"{other} ({other_status.get('outlook', '').lower()})"
        for other, other_status in at_risk[1:4]) if len(at_risk) > 1 else ""
    result.evidence = status.get("evidence") or []
    return result


def _best_run(result: Answer, facts: dict) -> Answer:
    result.headline = "WHO HAS THE BEST NEXT FOUR?"
    runs = []
    for name, fact in facts.items():
        brief = fact.get("brief") or {}
        if brief.get("run") == "improves":
            runs.append((name, brief))
    if not runs:
        runs = [(name, fact.get("brief") or {}) for name, fact in facts.items()
                if (fact.get("brief") or {}).get("next_four")][:1]
    if not runs:
        result.short_answer = "No fixture runs have been generated."
        return result
    name, brief = runs[0]
    result.short_answer = (
        f"{name} — {' → '.join(brief.get('next_four', []))}.")
    result.why = brief.get("verdict", "")
    result.players = [name for name, _ in runs[:3]]
    result.caveat = "Others whose run improves: " + ", ".join(
        other for other, _ in runs[1:4]) if len(runs) > 1 else ""
    return result
