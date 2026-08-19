"""Natural-language questions about the squad.

Two tiers, in this order:

1. A free, local engine that recognises the question shapes people
   actually ask ("why not Bruno", "Salah or Palmer", "who do I captain",
   "best value defender") and answers them by re-solving the squad. These
   are exact, instant, and cost nothing — and because they're computed
   rather than generated, they can't be confidently wrong about who's in
   the squad.

2. Claude, for anything the first tier can't parse — team news, strategy,
   judgement calls. Only used when an API key is configured, and only
   after the free engine has declined, so the common questions never cost
   anything.

If neither is available the caller falls back to the copy-paste block, so
the feature degrades rather than disappearing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from fpl_assistant.analysis import explain, optimiser

MODEL = "claude-opus-5"
# Answers here are conversational, not documents. A low ceiling keeps
# replies tight and the per-question cost near zero.
MAX_TOKENS = 1200

POSITION_WORDS = {
    "goalkeeper": "GKP", "keeper": "GKP", "gk": "GKP", "gkp": "GKP",
    "defender": "DEF", "defence": "DEF", "defense": "DEF", "def": "DEF",
    "midfielder": "MID", "midfield": "MID", "mid": "MID",
    "forward": "FWD", "striker": "FWD", "fwd": "FWD", "attacker": "FWD",
}

# Words that look like names to a naive matcher but never are. Without
# this, "Who should I captain?" matches a player called Wood or Sane on a
# three-letter substring and answers a question nobody asked.
STOPWORDS = {
    "why", "who", "what", "which", "when", "should", "would", "could", "the", "and", "but",
    "not", "for", "you", "your", "this", "that", "them", "they", "him", "his", "her", "with",
    "from", "have", "has", "had", "get", "got", "pick", "picked", "picking", "select",
    "selected", "captain", "captaincy", "vice", "squad", "team", "player", "players", "best",
    "value", "cheap", "expensive", "differential", "differentials", "worth", "instead",
    "over", "under", "about", "think", "thoughts", "good", "bad", "better", "worse", "vs",
    "versus", "against", "than", "any", "all", "some", "one", "two", "out", "into", "gameweek",
    "week", "fpl", "question", "points", "price", "form", "fixture", "fixtures", "own",
    "ownership", "transfer", "transfers", "bench", "start", "starting", "playing", "play",
}


@dataclass
class AskResult:
    source: str  # "engine" | "claude" | "unanswered"
    answer: explain.Answer | None = None
    text: str | None = None
    note: str | None = None


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", str(text).lower())


def find_players(question: str, scored: pd.DataFrame, limit: int = 2) -> list[int]:
    """Player ids mentioned in the question, most confident first.

    Scores each candidate so a full-name mention beats an incidental
    surname collision, and skips very short tokens, which otherwise match
    half the player pool.
    """
    words = [w for w in _normalise(question).split() if len(w) > 2 and w not in STOPWORDS]
    if not words:
        return []
    question_text = " ".join(words)

    scores: list[tuple[float, float, int]] = []
    for row in scored.itertuples():
        best = 0.0
        for attribute in ("web_name", "second_name", "first_name"):
            value = getattr(row, attribute, None)
            if value is None or (isinstance(value, float) and pd.isna(value)):
                continue
            name = _normalise(value).strip()
            if len(name) < 3 or name in STOPWORDS:
                continue
            if re.search(rf"\b{re.escape(name)}\b", question_text):
                # Longer matches are more specific and so more trustworthy.
                best = max(best, 1.0 + len(name) / 100.0)
        if best:
            ownership = float(getattr(row, "selected_by_percent", 0) or 0)
            scores.append((best, ownership, int(row.id)))

    scores.sort(reverse=True)
    return [player_id for _, _, player_id in scores[:limit]]


def _wants_comparison(question: str) -> bool:
    return bool(re.search(r"\b(or|vs|versus|instead of|over)\b", _normalise(question)))


def _wants_captain(question: str) -> bool:
    return "captain" in _normalise(question)


def _wanted_position(question: str) -> str | None:
    for word, position in POSITION_WORDS.items():
        if re.search(rf"\b{word}\b", _normalise(question)):
            return position
    return None


def _wants_value(question: str) -> bool:
    return bool(re.search(r"\b(value|cheap|budget|bargain|enabler)\b", _normalise(question)))


def _wants_differential(question: str) -> bool:
    return "differential" in _normalise(question)


def _captain_answer(scored: pd.DataFrame, solution: optimiser.SquadSolution) -> explain.Answer:
    indexed = scored.set_index("id")
    captain = indexed.loc[solution.captain_id]
    vice = indexed.loc[solution.vice_captain_id]

    detail = [
        f"**{captain['web_name']}** projects **{captain.get('xp_next', 0):.1f} points**, doubled to "
        f"**{captain.get('xp_next', 0) * 2:.1f}**. **{vice['web_name']}** is the vice.",
        "The armband is ranked on ceiling rather than average — a forward and a defender projected "
        "the same aren't equal bets once you double them, because only one of them can return 15+ "
        "on a two-goal afternoon.",
    ]
    case = captain.get("consensus_reason")
    return explain.Answer(
        player_name=str(captain["web_name"]),
        in_squad=True,
        headline=f"**Captain {captain['web_name']}.**",
        detail=detail,
        consensus_case=str(case) if case is not None and pd.notna(case) else None,
    )


def _leaderboard_answer(
    scored: pd.DataFrame, position: str | None, by_value: bool, differential: bool
) -> explain.Answer:
    pool = scored.copy()
    if position:
        pool = pool[pool["position"] == position]
    if differential:
        pool = pool[pd.to_numeric(pool.get("selected_by_percent", 0), errors="coerce").fillna(0) < 10]

    if pool.empty:
        return explain.Answer(
            player_name="", in_squad=False,
            headline="No players match that filter this week.",
        )

    column = "xp_per_million" if by_value else "xp_horizon"
    if column not in pool.columns:
        column = "xp_horizon"
    top = pool.nlargest(6, column)

    label_bits = []
    if differential:
        label_bits.append("differentials (under 10% owned)")
    if by_value:
        label_bits.append("best value")
    else:
        label_bits.append("highest projected")
    if position:
        label_bits.append(f"at {position}")
    headline = f"**{' · '.join(label_bits).capitalize()}**"

    detail = [
        f"- **{row['web_name']}** ({row['team_short_name']}) — £{row['price']:.1f}m · "
        f"{row.get('xp_next', 0):.1f} pts next GW · {row.get('selected_by_percent', 0):.0f}% owned"
        for _, row in top.iterrows()
    ]
    if by_value:
        detail.append(
            "*Ranked on points per £m. Cheap players often win this outright — the real question "
            "is whether you can afford to field eleven of them.*"
        )
    return explain.Answer(player_name="", in_squad=False, headline=headline, detail=detail)


def answer_locally(
    question: str,
    scored: pd.DataFrame,
    solution: optimiser.SquadSolution,
    template_weight: float = optimiser.TEMPLATE_WEIGHT,
) -> explain.Answer | None:
    """Answer from the solver if the question is one we recognise, else None."""
    if not question or not question.strip():
        return None

    players = find_players(question, scored)

    if _wants_captain(question) and not players:
        return _captain_answer(scored, solution)

    if len(players) >= 2 and _wants_comparison(question):
        return explain.compare_players(scored, players[0], players[1])

    if players:
        return explain.explain_player(
            scored, solution, players[0], template_weight=template_weight
        )

    position = _wanted_position(question)
    if position or _wants_value(question) or _wants_differential(question):
        return _leaderboard_answer(
            scored, position, _wants_value(question), _wants_differential(question)
        )

    return None


def squad_context(scored: pd.DataFrame, solution: optimiser.SquadSolution, next_event: int) -> str:
    """A compact briefing so Claude's answer matches what the app shows.

    Without this the model would answer from general knowledge and could
    contradict the squad on screen, which is worse than not answering.
    """
    indexed = scored.set_index("id")

    def describe(player_id: int) -> str:
        row = indexed.loc[player_id]
        return (
            f"{row['web_name']} ({row['team_short_name']}, {row['position']}, "
            f"£{row['price']:.1f}m, {row.get('xp_next', 0):.1f}xP, "
            f"{row.get('selected_by_percent', 0):.0f}% owned)"
        )

    starters = ", ".join(describe(i) for i in solution.starting_ids)
    bench = ", ".join(describe(i) for i in solution.bench_ids)

    consensus_rows = scored[scored.get("consensus_tier").notna()] if "consensus_tier" in scored else pd.DataFrame()
    consensus_lines = [
        f"- {row['web_name']} [{row['consensus_tier']}]: {row.get('consensus_reason', '')}"
        for _, row in consensus_rows.iterrows()
    ]

    return (
        f"Gameweek {next_event}. The app's recommended squad, chosen by an exact optimiser that "
        f"maximises projected points under FPL's budget and squad rules.\n\n"
        f"Starting XI: {starters}\n"
        f"Bench: {bench}\n"
        f"Captain: {indexed.loc[solution.captain_id, 'web_name']}. "
        f"Vice: {indexed.loc[solution.vice_captain_id, 'web_name']}.\n"
        f"Squad cost £{solution.total_cost}m of £100.0m. Formation {solution.formation}.\n\n"
        f"Expert consensus fed into selection:\n" + "\n".join(consensus_lines)
    )


SYSTEM_PROMPT = (
    "You are an FPL analyst embedded in the user's own Fantasy Premier League app. "
    "Answer their question directly and concisely — a few short paragraphs at most.\n\n"
    "The squad briefing you are given is the ground truth for what the app currently recommends. "
    "Never contradict it about who is or isn't in the squad. If your football judgement differs "
    "from the app's projection, say so plainly and explain why — the user values disagreement "
    "more than agreement, as long as you give the reason.\n\n"
    "Be concrete. Cite the specific factor driving your answer (a role, a fixture, a price, "
    "penalty duty, a fitness doubt) rather than describing a player in general terms. If you are "
    "not confident about current team news or an injury, say that explicitly instead of guessing "
    "— the user would rather hear 'check before the deadline' than a confident invention."
)


def claude_available(api_key: str | None) -> bool:
    if not api_key:
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def answer_with_claude(
    question: str,
    context: str,
    api_key: str,
    model: str = MODEL,
) -> str:
    """Ask Claude, with the squad briefing as context."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"{context}\n\n---\n\nQuestion: {question.strip()}"}],
    )
    return "\n\n".join(block.text for block in response.content if block.type == "text").strip()


def ask(
    question: str,
    scored: pd.DataFrame,
    solution: optimiser.SquadSolution,
    next_event: int,
    api_key: str | None = None,
    template_weight: float = optimiser.TEMPLATE_WEIGHT,
) -> AskResult:
    """Free engine first, Claude only if it can't answer."""
    local = answer_locally(question, scored, solution, template_weight=template_weight)
    if local is not None:
        return AskResult(source="engine", answer=local)

    if claude_available(api_key):
        try:
            text = answer_with_claude(
                question, squad_context(scored, solution, next_event), api_key
            )
            return AskResult(source="claude", text=text)
        except Exception as exc:
            return AskResult(
                source="unanswered",
                note=f"Couldn't reach Claude ({exc}). Copy the question below and paste it into chat.",
            )

    return AskResult(
        source="unanswered",
        note=(
            "That one needs judgement rather than arithmetic — team news, a hunch, or a strategy "
            "call. Copy it below and paste it into your chat with Claude."
        ),
    )
