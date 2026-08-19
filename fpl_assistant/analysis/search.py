"""Search across everything the app knows about a player.

The research is spread over four places -- the per-player consensus file,
the club stances, the weekly odds/expert report, and the live player data
-- and until now you could only reach any of it by already knowing which
tab it lived in. That's fine when you're reading top to bottom and useless
when you have a specific question, which is most of the time: "what's the
story with Semenyo", "who's on penalties at Everton", "which defenders are
flagged".

So this searches the lot at once and says where each answer came from.
Deliberately a plain local index rather than a model call: it's instant,
it works with no API key, it can't invent a fact that isn't in the corpus,
and every hit points at the source text so you can judge it yourself. The
natural-language router in ask.py is still there for questions that need
reasoning rather than lookup.
"""
import re
from dataclasses import dataclass, field

import pandas as pd

from fpl_assistant.analysis import consensus

# Words too common to discriminate. Without this, "who is on penalties"
# matches every entry that contains "is".
STOPWORDS = {
    "a", "an", "and", "any", "are", "about", "at", "be", "but", "by", "can", "do", "does",
    "for", "from", "get", "has", "have", "how", "i", "in", "is", "it", "me", "my", "of",
    "on", "or", "should", "so", "that", "the", "their", "them", "there", "they", "this",
    "to", "was", "we", "what", "when", "which", "who", "why", "will", "with", "you", "your",
    "fpl", "fantasy", "football", "player", "players", "pick", "picks",
}

# Field weights. A name match is worth far more than the same word turning
# up in the middle of a paragraph -- searching "Haaland" should put
# Haaland first, not an article that mentions him in passing.
FIELD_WEIGHTS = {
    "name": 12.0,
    "verdict": 4.0,
    "stat": 3.0,
    "voice": 2.5,
    "case": 1.5,
    "watch_out": 1.5,
    "dissent": 1.5,
    "club": 2.0,
    "report": 1.0,
}

SNIPPET_CHARS = 260
DEFAULT_LIMIT = 8


@dataclass
class Hit:
    """One search result, with the text that matched and where it lives."""

    title: str
    kind: str              # player | club | report
    score: float
    subtitle: str = ""
    snippets: list[tuple[str, str]] = field(default_factory=list)  # (label, text)
    sources: str | None = None
    player_id: int | None = None
    tier: str | None = None


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9']+", str(text).lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def _matches(haystack: str, terms: list[str]) -> int:
    """How many distinct query terms appear in this text, as whole words.

    Whole-word only: substring matching makes "pen" hit "expensive" and
    "open", which quietly fills the results with noise that looks like
    signal.
    """
    low = str(haystack).lower()
    return sum(1 for term in terms if re.search(rf"\b{re.escape(term)}", low))


def _snippet(text: str, terms: list[str]) -> str:
    """A window of the text around the first match, so the hit shows the
    part that actually matched rather than the opening sentence."""
    body = str(text).strip()
    if len(body) <= SNIPPET_CHARS:
        return body

    low = body.lower()
    position = next(
        (m.start() for term in terms for m in [re.search(rf"\b{re.escape(term)}", low)] if m),
        0,
    )
    start = max(0, position - SNIPPET_CHARS // 3)
    end = min(len(body), start + SNIPPET_CHARS)
    return ("…" if start else "") + body[start:end].strip() + ("…" if end < len(body) else "")


def _player_hits(query: str, terms: list[str], scored: pd.DataFrame | None) -> list[Hit]:
    data = consensus.load_consensus_any() or {}
    hits: list[Hit] = []

    for entry in data.get("players", []):
        score = 0.0
        snippets: list[tuple[str, str]] = []

        name_blob = f"{entry.get('name','')} {entry.get('full_name','')}"
        name_matches = _matches(name_blob, terms)
        score += name_matches * FIELD_WEIGHTS["name"]

        for field_name, label, weight_key in (
            ("verdict", "Verdict", "verdict"),
            ("case", "The case for", "case"),
            ("watch_out", "The case against", "watch_out"),
        ):
            text = entry.get(field_name)
            if not text:
                continue
            found = _matches(text, terms)
            if found:
                score += found * FIELD_WEIGHTS[weight_key]
                snippets.append((label, _snippet(text, terms)))

        for stat in entry.get("key_stats", []) or []:
            if _matches(stat, terms):
                score += FIELD_WEIGHTS["stat"]
                snippets.append(("Stat", str(stat)))

        for voice in entry.get("voices", []) or []:
            take = voice.get("take", "")
            if _matches(take, terms):
                score += FIELD_WEIGHTS["voice"]
                snippets.append((str(voice.get("source") or "Analyst"), _snippet(take, terms)))

        dissent = entry.get("dissent")
        if isinstance(dissent, dict) and _matches(dissent.get("case", ""), terms):
            score += FIELD_WEIGHTS["dissent"]
            snippets.append(("Experts disagree", _snippet(dissent["case"], terms)))

        if score <= 0:
            continue

        # A name match with nothing else matching still deserves the
        # headline material -- someone searching a name wants the verdict,
        # not an empty card.
        if name_matches and not snippets:
            for field_name, label in (("verdict", "Verdict"), ("case", "The case for")):
                if entry.get(field_name):
                    snippets.append((label, _snippet(entry[field_name], terms)))

        hits.append(
            Hit(
                title=str(entry.get("full_name") or entry.get("name")),
                kind="player",
                score=score,
                subtitle=str(entry.get("verdict") or ""),
                snippets=snippets[:5],
                sources=", ".join(entry.get("sources", []) or []) or None,
                tier=entry.get("tier"),
            )
        )

    # Players nobody has written about still exist, and searching a name
    # should not come back empty just because no analyst covered him.
    if scored is not None and not scored.empty:
        named = {str(h.title).lower() for h in hits}
        for _, row in scored.iterrows():
            name = str(row.get("web_name") or "")
            if not name or _matches(name, terms) == 0:
                continue
            if any(name.lower() in existing for existing in named):
                continue
            hits.append(
                Hit(
                    title=name,
                    kind="player",
                    score=FIELD_WEIGHTS["name"] * 0.8,
                    subtitle=(
                        f"{row.get('team_short_name','')} · {row.get('position','')} · "
                        f"£{pd.to_numeric(row.get('price'), errors='coerce'):.1f}m"
                    ),
                    snippets=[(
                        "No analyst has written about him",
                        f"Projected {pd.to_numeric(row.get('xp_next'), errors='coerce'):.1f} points "
                        f"next gameweek, {pd.to_numeric(row.get('xp_horizon'), errors='coerce'):.0f} "
                        f"over five. {pd.to_numeric(row.get('selected_by_percent'), errors='coerce'):.1f}% owned.",
                    )],
                    player_id=int(row["id"]),
                )
            )
    return hits


def _club_hits(terms: list[str], teams: pd.DataFrame | None = None) -> list[Hit]:
    """Club verdicts, with a name match weighted like a player's.

    Searching "Bournemouth" has to put the Bournemouth verdict first. It
    previously ranked below a player whose write-up happened to mention
    them more often, because the club's own name only appeared once in its
    own text -- the thing you searched for scoring lowest on itself.

    Full names come from the live team data rather than a hardcoded alias
    list, so a promoted club works the day it arrives.
    """
    long_names: dict[str, str] = {}
    if teams is not None and not teams.empty and "short_name" in teams.columns:
        for _, row in teams.iterrows():
            short = str(row.get("short_name") or "").upper()
            if short:
                long_names[short] = str(row.get("name") or "")

    hits = []
    for short, entry in consensus.load_team_context().items():
        for stance in entry.get("stances", []) or []:
            case = stance.get("case", "")
            name_matches = _matches(f"{short} {long_names.get(short, '')}", terms)
            found = _matches(case, terms) + name_matches
            if not found:
                continue
            hits.append(
                Hit(
                    title=f"{short} — analysts say {stance.get('stance')}",
                    kind="club",
                    score=found * FIELD_WEIGHTS["club"] + name_matches * FIELD_WEIGHTS["name"],
                    subtitle=(
                        f"Applies to every {short} player"
                        + (f" until GW{stance['until_gameweek']}" if stance.get("until_gameweek") else "")
                    ),
                    snippets=[("Why", _snippet(case, terms))],
                    sources=", ".join(stance.get("sources", []) or []) or None,
                )
            )
    return hits


def _report_hits(terms: list[str], report_text: str | None) -> list[Hit]:
    if not report_text:
        return []
    hits = []
    # Split on markdown headings so a hit points at a section rather than
    # at "the report".
    sections = re.split(r"\n(?=#{1,3}\s)", report_text)
    for section in sections:
        found = _matches(section, terms)
        if not found:
            continue
        heading = section.strip().split("\n", 1)[0].lstrip("# ").strip() or "Report"
        hits.append(
            Hit(
                title=heading,
                kind="report",
                score=found * FIELD_WEIGHTS["report"],
                subtitle="From this gameweek's odds & expert report",
                snippets=[("Extract", _snippet(section, terms))],
            )
        )
    return hits


def search(
    query: str,
    scored: pd.DataFrame | None = None,
    report_text: str | None = None,
    teams: pd.DataFrame | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[Hit]:
    """Everything the app knows that matches `query`, best first."""
    terms = _tokens(query)
    if not terms:
        return []

    hits = (
        _player_hits(query, terms, scored)
        + _club_hits(terms, teams)
        + _report_hits(terms, report_text)
    )
    hits.sort(key=lambda hit: -hit.score)
    return hits[:limit]
