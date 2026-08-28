"""The checks that run before a weekly update is shown as finished.

Every item here exists because the alternative — publishing anyway — has
a specific, known cost. A stale injury flag sends someone into a deadline
with a player who isn't playing. A squad that quietly reverted to last
week's recommendation gives advice for a team the reader doesn't own. A
transfer with no written reasoning is an instruction rather than a
recommendation, and instructions are what people stop trusting.

The design rule is that a failed check must be *visible*, never silent.
This module does not fix anything and does not block rendering: it
reports, in the reader's own words, what could not be confirmed. A page
that says "we could not verify the set-piece taker" is more useful than
one that quietly guesses, and far more useful than one that renders
nothing at all.

Severity is deliberately only two levels. `BLOCKER` means the advice
could actively mislead — act on this before trusting the page. `WARNING`
means the advice is thinner than it should be but is not wrong. A third
level would just invite everything to be filed in the middle.
"""
from dataclasses import dataclass, field

import pandas as pd

BLOCKER = "blocker"
WARNING = "warning"

# A write-up shorter than this is a label, not reasoning.
MIN_WRITE_UP_CHARS = 120

# Claims that must not rest on a single outlet. These are the categories
# that have actually been got wrong before, and each one changes a
# decision on its own: whether he plays, and whether he takes the
# set pieces.
NEEDS_CORROBORATION = ("predicted_start", "set_pieces")


@dataclass
class Finding:
    severity: str
    check: str
    detail: str

    @property
    def icon(self) -> str:
        return "🛑" if self.severity == BLOCKER else "⚠️"


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    checks_run: int = 0

    @property
    def blockers(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == BLOCKER]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == WARNING]

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def headline(self) -> str:
        if not self.findings:
            return f"All {self.checks_run} checks passed."
        if self.blockers:
            return (
                f"{len(self.blockers)} of {self.checks_run} checks need attention "
                f"before trusting this page."
            )
        return f"{len(self.warnings)} of {self.checks_run} checks flagged something minor."


def _add(report: Report, severity: str, check: str, detail: str) -> None:
    report.findings.append(Finding(severity, check, detail))


def run(
    squad_ids: list[int],
    scored: pd.DataFrame,
    gameweek: int,
    transfer_cases: list | None = None,
    player_cases: list | None = None,
    bank: float | None = None,
    free_transfers: int | None = None,
    confirmed_event: int | None = None,
) -> Report:
    """Checks a week's recommendation before it is presented as done."""
    report = Report()
    indexed = scored.set_index("id", drop=False) if scored.index.name != "id" else scored

    def check(name, ok, severity, detail):
        report.checks_run += 1
        if not ok:
            _add(report, severity, name, detail)

    # --- the squad is the one being advised on -------------------------
    check("Squad size", len(squad_ids) == 15, BLOCKER,
          f"The squad has {len(squad_ids)} players, not 15. Advice built on a partial squad is "
          f"advice for a team nobody owns.")

    missing = [pid for pid in squad_ids if pid not in indexed.index]
    check("Squad players are in the pool", not missing, BLOCKER,
          f"{len(missing)} owned player(s) are missing from the projection pool, usually because "
          f"they are flagged unavailable. They are excluded from every recommendation below.")

    check("Squad is this gameweek's", confirmed_event is None or confirmed_event <= gameweek,
          BLOCKER,
          f"The loaded squad is from GW{confirmed_event}, which is later than the GW{gameweek} being "
          f"planned. That is the wrong starting point.")

    # --- availability ---------------------------------------------------
    present = [pid for pid in squad_ids if pid in indexed.index]
    if present:
        owned = indexed.loc[present]
        unavailable = owned[owned.get("status", pd.Series("a", index=owned.index)).astype(str) != "a"]
        check("Availability", unavailable.empty, WARNING,
              "Flagged and still in the squad: "
              + ", ".join(str(n) for n in unavailable.get("web_name", []))
              + ". Check the late team news.")

        starts = owned.get("predicted_start")
        if starts is not None:
            out = owned[starts.astype(str) == "out"]
            check("Nobody selected who is ruled out", out.empty, BLOCKER,
                  "Ruled out but still in the squad: "
                  + ", ".join(str(n) for n in out.get("web_name", [])) + ".")
            unknown = owned[starts.isna() | (starts.astype(str).str.strip() == "")]
            check("Expected minutes researched", len(unknown) <= len(owned) // 2, WARNING,
                  f"{len(unknown)} of {len(owned)} owned players have no researched minutes call. "
                  f"Minutes decide more gameweeks than any rate does.")

    # --- money ----------------------------------------------------------
    if bank is not None:
        check("Bank is plausible", bank >= 0, BLOCKER,
              f"The bank reads £{bank:.1f}m. A negative balance means the squad or the prices are "
              f"out of date.")
    if free_transfers is not None:
        check("Free transfers are plausible", 0 <= free_transfers <= 5, WARNING,
              f"Free transfers read {free_transfers}, which is outside the 0-5 the rules allow.")

    # --- every transfer is argued, not asserted -------------------------
    for case in transfer_cases or []:
        name = f"{case.out.name} → {case.into.name}"
        check(f"Transfer reasoning: {name}",
              bool(case.researched), WARNING,
              f"{name} rests on the projection alone — no outlet has written about either player "
              f"this week. Treat it as a prompt to check rather than a call.")
        check(f"Transfer look-ahead: {name}",
              bool(case.into.fixture_run), WARNING,
              f"No fixture run loaded for {case.into.name}, so this move has only been judged on "
              f"this weekend.")

    # --- every player is explained --------------------------------------
    for case in player_cases or []:
        check(f"Write-up: {case.name}",
              len(case.write_up()) >= MIN_WRITE_UP_CHARS, WARNING,
              f"{case.name}'s explanation is too thin to be reasoning. He is in the squad without "
              f"a stated case.")

    captains = [c for c in (player_cases or []) if c.captain]
    check("Exactly one captain", len(captains) == 1 if player_cases else True, BLOCKER,
          f"{len(captains)} players are marked captain.")
    if captains:
        check("Captain is a midfielder or forward",
              captains[0].position in ("MID", "FWD"), BLOCKER,
              f"The armband is on {captains[0].name}, a {captains[0].position}. Doubling a defender "
              f"is almost never the highest-ceiling call.")
        check("Captaincy is explained",
              bool(captains[0].arguments_for or captains[0].record_vs), WARNING,
              f"No researched case for captaining {captains[0].name}.")

    return report


def corroboration_gaps(scored: pd.DataFrame, squad_ids: list[int]) -> list[str]:
    """Owned players whose minutes or set-piece call rests on one source.

    Not a failure — one good source is often all there is — but the reader
    should know which claims are single-sourced, because those are the
    ones that have been wrong before.
    """
    indexed = scored.set_index("id", drop=False) if scored.index.name != "id" else scored
    gaps = []
    for pid in squad_ids:
        if pid not in indexed.index:
            continue
        row = indexed.loc[pid]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        sources = row.get("consensus_sources")
        count = len(str(sources).split(",")) if isinstance(sources, str) and sources.strip() else 0
        claims = [c for c in NEEDS_CORROBORATION
                  if isinstance(row.get(c), str) and str(row.get(c)).strip()]
        if claims and count <= 1:
            gaps.append(
                f"{row.get('web_name')}: {' and '.join(claims).replace('_', ' ')} "
                f"rests on a single source."
            )
    return gaps
