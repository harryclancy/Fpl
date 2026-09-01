"""Quality gates: a refresh is not a success because Python exited 0.

The specific thing being prevented: a run in which every network request
failed, zero articles were retrieved, and the app nonetheless rendered
fifteen confident-looking player cards — because Stage B (analysis) does
not depend on Stage A (collection) having produced anything. Analysis of
nothing still produces output. It just produces output about nothing.

So collection reports a verdict, and the page is not allowed to describe a
player as assessed unless collection passed.

The blackout check is the backstop. It encodes a piece of football
knowledge as a test: if the most heavily covered players in the game all
come back with no evidence at the same time, the world has not gone quiet,
the pipeline has broken. That is a statement about the pipeline, not about
the players, and it is the check that would have caught this bug the day
it appeared.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# A run touching fewer than this many working sources is not a research
# pass, whatever it returns.
MIN_SOURCES_OK = 5
MIN_ARTICLES = 25

# Players who are always written about. If NONE of the ones present in a
# squad can be evidenced, the collection is broken rather than the news
# being quiet. Chosen for coverage, not for quality.
BELLWETHERS = ("Haaland", "Szoboszlai", "Semenyo", "Salah", "Saka", "Palmer",
               "B.Fernandes", "Isak", "Gyokeres", "Joao Pedro", "João Pedro")

COLLECTION_FAILURE = "RESEARCH COLLECTION FAILURE"
PIPELINE_FAILURE = "RESEARCH PIPELINE LIKELY FAILED"


@dataclass
class Verdict:
    """Whether a stage may be described as having worked."""

    ok: bool
    headline: str = ""
    reasons: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok


def check_collection(sources_checked: int, sources_ok: int, articles: int,
                     failures: list[str] | None = None) -> Verdict:
    """Did Stage A actually retrieve anything worth analysing?"""
    reasons: list[str] = []
    if sources_checked == 0:
        reasons.append("no sources were attempted — the collector never ran")
    if sources_ok == 0 and sources_checked:
        reasons.append(f"all {sources_checked} sources failed to return anything")
    elif sources_ok < MIN_SOURCES_OK:
        reasons.append(f"only {sources_ok} source(s) returned material; {MIN_SOURCES_OK} is the floor")
    if articles < MIN_ARTICLES:
        reasons.append(f"only {articles} article(s) retrieved; {MIN_ARTICLES} is the floor")

    if reasons:
        sample = (failures or [])[:3]
        return Verdict(False, COLLECTION_FAILURE, reasons + [f"e.g. {f}" for f in sample])
    return Verdict(True, "", [f"{sources_ok}/{sources_checked} sources returned {articles} articles"])


def check_blackout(evidence_by_player: dict) -> Verdict:
    """The implausibility test.

    `evidence_by_player` maps player name to a PlayerEvidence. If every
    bellwether in the squad has nothing, that is a broken pipeline: those
    players are written about every single day.
    """
    present = {name: ev for name, ev in evidence_by_player.items()
               if any(b.lower() == name.lower() for b in BELLWETHERS)}
    if not present:
        return Verdict(True, "", ["no bellwether players in this squad to check against"])

    # Substantive items only. A bellwether "evidenced" by three generated
    # profile pages is exactly the false pass this gate exists to catch.
    empty = [name for name, ev in present.items() if not ev.substantive_items]
    if len(empty) == len(present):
        return Verdict(False, PIPELINE_FAILURE, [
            f"{', '.join(sorted(empty))} all returned zero evidence at the same time",
            "these are among the most-covered players in the game; simultaneous silence "
            "is not a plausible state of the world",
            "treat this as a collection failure, not as a finding about the players",
        ])
    return Verdict(True, "", [
        f"{len(present) - len(empty)}/{len(present)} bellwether players evidenced"
    ])


def check_squad_coverage(evidence_by_player: dict, required: int) -> Verdict:
    """Every owned player must have been searched for, and most evidenced."""
    searched = len(evidence_by_player)
    researched = [n for n, ev in evidence_by_player.items() if ev.researched]
    reasons = [f"{len(researched)}/{searched} players met the evidence threshold"]
    if searched < required:
        return Verdict(False, COLLECTION_FAILURE,
                       [f"only {searched} of {required} owned players were searched for"])
    return Verdict(bool(researched), "" if researched else COLLECTION_FAILURE, reasons)
