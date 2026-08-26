"""Weekly research, done by Claude with web search rather than by hand.

The app's advice is only as good as the research behind it, and until now
that research was hand-entered — which meant it covered whichever dozen
players happened to get written up, went stale the moment a manager gave a
press conference, and had already been wrong about a transfer, a club's
league membership and a defender's current team.

This runs the same job automatically: search the web for what analysts are
actually saying this week, and return it as the structured files the app
reads. Web search runs server-side, so Claude sees live pages rather than
its training data — which matters more here than anywhere else in the
project, because every claim in these files has a shelf life measured in
days.

Two safeguards, both of which exist because automated research that is
confidently wrong is worse than no research:

  * The output is schema-constrained, so it can't come back as prose that
    a parser has to guess at.
  * It is validated against the same rules the test suite enforces before
    anything is written. A file that fails is rejected and last week's
    data is kept — stale research known to be stale beats fresh research
    that is wrong.
"""
import json
import os
from dataclasses import dataclass

MODEL = "claude-opus-5"
# Server-side web search. The dated variant matters: it's the one with
# dynamic filtering, and it's what Opus 5 supports.
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 18}
# Research is a long turn — many searches, a large structured answer — so
# it streams. A non-streaming call at this size risks an HTTP timeout.
#
# Sized generously on purpose. The first live run asked for 12-20 players
# with a case, a counter-argument, several stats and several attributed
# takes each, and ran out of output tokens partway through a string at
# around 46,000 characters of JSON — which surfaced as a parse error
# rather than as "the answer was cut off". Opus 5 allows up to 128K output
# when streaming, so the ceiling should not be the thing that decides how
# much research fits.
MAX_TOKENS = 64000

SOURCES = [
    "Fantasy Football Scout", "RotoWire", "AllAboutFPL", "Fantasy Football Fix",
    "Fantasy Football Hub", "The Scout (premierleague.com)", "OneFPL", "FPL Pulse",
]


@dataclass
class ResearchResult:
    kind: str
    data: dict | None
    problems: list[str]
    searches: int = 0

    @property
    def ok(self) -> bool:
        return self.data is not None and not self.problems


def _voice_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "The outlet, named. Not 'analysts'."},
            "take": {"type": "string", "description": "What that outlet actually said."},
        },
        "required": ["source", "take"],
        "additionalProperties": False,
    }


PLAYER_SCHEMA = {
    "type": "object",
    "properties": {
        "gameweek": {"type": "integer"},
        "researched": {"type": "string", "description": "ISO date, YYYY-MM-DD."},
        "players": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "FPL web name, e.g. 'B.Fernandes'."},
                    "full_name": {"type": "string"},
                    "tier": {"type": "string", "enum": list(("must_have", "strong", "value", "avoid"))},
                    "expert_ownership": {"type": "number"},
                    "verdict": {"type": "string", "description": "One line."},
                    "case": {"type": "string", "description": "The argument for picking him."},
                    "watch_out": {"type": "string", "description": "The honest argument against."},
                    "key_stats": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Hard numbers as discrete facts, at least two.",
                    },
                    "voices": {"type": "array", "items": _voice_schema()},
                    "dissent": {
                        "type": "object",
                        "properties": {
                            "case": {"type": "string"},
                            "sources": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["case", "sources"],
                        "additionalProperties": False,
                    },
                    "sources": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "name", "full_name", "tier", "verdict", "case", "watch_out",
                    "key_stats", "voices", "sources",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["gameweek", "researched", "players"],
    "additionalProperties": False,
}

ODDS_SCHEMA = {
    "type": "object",
    "properties": {
        "gameweek": {"type": "integer"},
        "researched": {"type": "string"},
        "players": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "full_name": {"type": "string"},
                    "anytime_goalscorer": {
                        "type": "number",
                        "description": "Decimal odds, e.g. 1.44. Greater than 1.",
                    },
                    "captain_share": {
                        "type": "number",
                        "description": "Percent of managers expected to captain him, 0-100.",
                    },
                    "note": {"type": "string"},
                },
                "required": ["name", "full_name"],
                "additionalProperties": False,
            },
        },
        "matchups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "team": {"type": "string", "description": "FPL short name, e.g. MCI."},
                    "opponent": {"type": "string"},
                    "note": {
                        "type": "string",
                        "description": "What typically happens when these two meet.",
                    },
                },
                "required": ["team", "opponent", "note"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["gameweek", "researched", "players", "matchups"],
    "additionalProperties": False,
}


SYSTEM = """You are researching Fantasy Premier League for a decision-support app.

Your job is to report what informed people are actually saying this week, with
the numbers behind it, and to be honest about disagreement. You are not writing
marketing copy for players.

Rules that matter more than completeness:

1. Search before you write. Every claim must come from a page you have read this
   session, not from memory. Prices, injuries, managers, and which club a player
   plays for all change, and being confidently out of date is the single most
   damaging thing you can do here.
2. Attribute every opinion to a named outlet. "Analysts say" is not a source and
   is exactly how an unchecked claim survives.
3. Record disagreement as disagreement. Where reputable analysts argue the
   opposite of the consensus, use the `dissent` field rather than averaging the
   two into a bland middle. A contested pick presented as settled is worse than
   no coverage.
   BUT: `must_have` and `dissent` are mutually exclusive. `must_have` locks the
   player into the squad with no way to override it, so it is only for genuine
   near-unanimity. If you are recording a dissent about someone, he is by
   definition not unanimous — tier him `strong` instead. A note that a popular
   player is highly owned and therefore a poor route to rank is a dissent worth
   recording; it just means `strong`, not `must_have`.
4. Every player needs a real counter-argument in `watch_out`. A recommendation
   you cannot argue against is not advice. If you cannot find a genuine risk,
   you have not looked hard enough.
5. Club-wide advice ("avoid this club until their fixtures turn") does NOT belong
   in a player's write-up. It will reach only that player. Report it in the
   `verdict`/`case` of every affected player only if it is genuinely about them.
6. Prefer specific, checkable facts: "18 clean sheets, three more than any other
   defender" beats "excellent defensive record".
7. If you cannot substantiate an entry, leave the player out. A short, accurate
   file is worth more than a long one padded with guesses."""


def _client():
    import anthropic

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set, so the research agent can't run. "
            "The app still works on whatever research is already committed."
        )
    return anthropic.Anthropic()


def _readable(error: Exception) -> str:
    """Turns the failures that actually happen into something actionable.

    A billing failure arriving as a raw error dict reads like a bug in the
    request. It isn't, and the fix is somewhere else entirely.
    """
    text = str(error)
    if "credit balance is too low" in text:
        return (
            "Out of Anthropic API credit — the research couldn't run. Top up at "
            "console.anthropic.com under Plans & Billing; nothing else is wrong."
        )
    if "authentication" in text.lower() or "invalid x-api-key" in text.lower():
        return (
            "The Anthropic API key was rejected. Check the ANTHROPIC_API_KEY repository "
            "secret — a trailing space or a revoked key both look like this."
        )
    if "rate_limit" in text.lower():
        return "Rate limited by the Anthropic API. The next scheduled run will retry."
    return text


def _ask(prompt: str, schema: dict) -> tuple[dict, int]:
    """One research turn: search the web, answer in the given schema."""
    client = _client()
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        thinking={"type": "adaptive"},
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": schema}},
        tools=[WEB_SEARCH_TOOL],
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        response = stream.get_final_message()

    if response.stop_reason == "refusal":
        raise RuntimeError(f"The model declined this research request: {response.stop_details}")

    # Truncation has to be named, not left to surface as a parse error.
    # A cut-off JSON document fails with "Unterminated string at column
    # 45982", which sends you looking for a bug in the schema when the
    # actual problem is that the answer didn't fit.
    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            f"The answer was cut off at the {MAX_TOKENS} token ceiling, so the JSON is "
            f"incomplete. Ask for fewer players, or raise MAX_TOKENS."
        )

    searches = sum(1 for block in response.content if block.type == "server_tool_use")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise RuntimeError("The research call returned no text to parse.")

    try:
        return json.loads(text), searches
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"The research came back as invalid JSON ({error}). stop_reason was "
            f"{response.stop_reason!r}."
        ) from error


def research_players(gameweek: int, today: str) -> ResearchResult:
    from fpl_assistant.analysis import consensus
    from fpl_assistant.research import validation

    prompt = f"""Research Fantasy Premier League Gameweek {gameweek}. Today is {today}.

Search {', '.join(SOURCES[:5])} and similar for this week's coverage, then report
the players worth a verdict — the ones being widely recommended, the ones being
widely warned against, and any the community is arguing about.

Cover 12-16 players. For each: which tier, the argument for, the honest argument
against, at least three hard numbers, and what named outlets actually said.

Pay particular attention to:
  - late injury and team news, which is the thing that dates fastest
  - anyone highly owned who analysts are now telling people to avoid
  - genuine splits in expert opinion, recorded in `dissent`
  - players whose club has recently changed, since that is easy to get wrong

Set `researched` to {today} and `gameweek` to {gameweek}."""

    try:
        data, searches = _ask(prompt, PLAYER_SCHEMA)
    except Exception as error:
        return ResearchResult("players", None, [_readable(error)])

    problems = validation.validate_players(data, consensus.load_team_context())
    return ResearchResult("players", data, problems, searches)


def research_odds(gameweek: int, today: str, fixtures: str = "") -> ResearchResult:
    from fpl_assistant.research import validation

    prompt = f"""Research Fantasy Premier League Gameweek {gameweek} betting markets and
captaincy. Today is {today}.

{fixtures}

Find, from pages you read this session:

1. Anytime-goalscorer decimal odds for the 8-15 most-captained and most-owned
   attacking players. Decimal format (1.44, not 4/9).
2. `captain_share`: the percentage of FPL managers expected to captain each of
   them. Effective-ownership and captaincy-poll articles carry this. The shares
   across all players cannot exceed 100 in total — everyone has one armband —
   so keep them realistic and leave the field's long tail unaccounted for.
3. `matchups`: for the notable fixtures, what typically happens when these two
   sides meet. Head-to-head scoring records, historical patterns, a striker with
   a run against this opponent. This is the context a per-90 rate cannot express,
   so it is the most valuable part of this file.

Set `researched` to {today} and `gameweek` to {gameweek}."""

    try:
        data, searches = _ask(prompt, ODDS_SCHEMA)
    except Exception as error:
        return ResearchResult("odds", None, [_readable(error)])

    problems = validation.validate_odds(data)
    return ResearchResult("odds", data, problems, searches)
