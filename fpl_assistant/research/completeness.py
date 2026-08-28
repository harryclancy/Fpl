"""Whether every owned player has actually been researched.

The rule this enforces: no player in the fifteen may end the week with an
empty profile. "No write-up found" is a description of one failed search,
not an acceptable output — the research is supposed to escalate past the
FPL blogs into club news, manager quotes, selection evidence and transfer
reporting until an assessment is possible.

Fourteen checks per player, and they are not decorative. Each one
corresponds to a question a manager asks before a deadline, and a profile
missing several of them is a profile that will quietly mislead: it looks
as complete as the others, and the gaps are invisible from the outside.

The report is deliberately per-player rather than aggregate. "13 of 15
players fully researched" hides which two, and the two are the whole
point — they are the ones you are about to make a decision on without
evidence.
"""
from dataclasses import dataclass, field

import pandas as pd

# Each check is (key, human label, how to test a dossier).
#
# Kept as data rather than as a long if-chain so the list itself is the
# specification: adding a research requirement means adding a line here,
# and the UI, the tests and the skill all read the same list.
CHECKS = (
    ("recent_news", "Recent news searched", lambda d: bool(d.events) or bool(d.case_for or d.case_against)),
    ("club_source", "Official club / manager comment", lambda d: any(
        e.kind in ("manager quote", "injury", "returned to training", "not in squad", "benched", "started")
        for e in d.events) or bool(d.role)),
    ("availability", "Availability checked", lambda d: bool(d.minutes_outlook)),
    ("latest_appearance", "Latest appearance checked", lambda d: any(
        e.kind in ("started", "benched", "substituted", "not in squad", "cup minutes", "european minutes")
        for e in d.events) or bool(d.minutes_reasons)),
    ("expected_minutes", "Expected minutes assessed", lambda d: bool(d.minutes_reasons)),
    # Requires that someone actually recorded a status. Accepting the
    # default would mark every unexamined player as cleared, which is the
    # exact blindness this gate exists to remove.
    ("transfer", "Transfer situation checked", lambda d: getattr(d, "transfer_checked", False)),
    ("role", "Tactical role considered", lambda d: bool(d.role) or bool(d.set_pieces)),
    ("fixture", "This week's fixture checked", lambda d: bool(d.fixture)),
    ("fixture_run", "Next 3-5 fixtures considered", lambda d: bool(d.fixture_run)),
    ("statistics", "Statistics considered", lambda d: bool(d.prior_seasons) or bool(d.case_for)),
    ("expert", "Expert opinion searched", lambda d: bool(d.case_for or d.case_against or d.dissent)),
    ("risks", "Risks written", lambda d: d.risks != "Nothing material identified." or not d.evidence_thin),
    ("keep_sell", "Keep/sell reasoning written", lambda d: bool(d.case_for_keeping and d.case_for_selling)),
    ("sources", "Sources attached", lambda d: bool(d.sources)),
)

# Below this a profile is not researched enough to be presented as one.
# Two thirds is chosen so a genuinely obscure player can still pass with a
# few gaps, while a profile built on nothing cannot.
PASS_THRESHOLD = 10


@dataclass
class PlayerCompleteness:
    player_id: int
    name: str
    passed: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    verdict: str = ""
    confidence: str = ""

    @property
    def score(self) -> int:
        return len(self.passed)

    @property
    def total(self) -> int:
        return len(CHECKS)

    @property
    def complete(self) -> bool:
        return self.score >= PASS_THRESHOLD

    @property
    def line(self) -> str:
        mark = "✅" if self.complete else "⚠️"
        return f"{mark} {self.name} — {self.score}/{self.total} · verdict {self.verdict}"


@dataclass
class SquadCompleteness:
    players: list[PlayerCompleteness] = field(default_factory=list)

    @property
    def incomplete(self) -> list[PlayerCompleteness]:
        return [p for p in self.players if not p.complete]

    @property
    def ready(self) -> bool:
        return not self.incomplete

    @property
    def headline(self) -> str:
        done = len(self.players) - len(self.incomplete)
        if self.ready:
            return f"{done}/{len(self.players)} owned players fully researched."
        names = ", ".join(p.name for p in self.incomplete)
        return (
            f"{done}/{len(self.players)} owned players fully researched. "
            f"Still thin on: {names}. Research those before trusting the page."
        )

    @property
    def worst_first(self) -> list[PlayerCompleteness]:
        return sorted(self.players, key=lambda p: p.score)


def check(dossiers) -> SquadCompleteness:
    """Runs the fourteen checks over every owned player's dossier."""
    report = SquadCompleteness()
    for d in dossiers:
        passed, missing = [], []
        for key, label, test in CHECKS:
            try:
                ok = bool(test(d))
            except Exception:
                ok = False
            (passed if ok else missing).append(label)
        report.players.append(PlayerCompleteness(
            player_id=d.player_id, name=d.name,
            passed=passed, missing=missing,
            verdict=d.verdict, confidence=d.confidence,
        ))
    return report


def next_searches(player: PlayerCompleteness, name: str) -> list[str]:
    """The specific searches that would close this player's gaps.

    Concrete queries rather than "research him more", because the failure
    being fixed is a research pass that gave up — and a named next step is
    the difference between escalating and stopping.
    """
    wanted = {
        "Recent news searched": f"{name} latest news",
        "Official club / manager comment": f"{name} manager press conference team news",
        "Latest appearance checked": f"{name} starting lineup last match minutes",
        "Expected minutes assessed": f"{name} expected to start injury doubt",
        "Transfer situation checked": f"{name} transfer bid talks",
        "Tactical role considered": f"{name} tactical role position set pieces penalties",
        "Expert opinion searched": f"{name} FPL analysis",
        "Statistics considered": f"{name} xG xA shots underlying stats",
        "This week's fixture checked": f"{name} next fixture preview",
        "Next 3-5 fixtures considered": f"{name} upcoming fixtures run",
    }
    return [wanted[label] for label in player.missing if label in wanted]
