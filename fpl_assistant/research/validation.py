"""Rules every researched file must satisfy before it is allowed to land.

These started life as assertions inside the test suite. They are here
instead because the research is now written by an automated agent, and a
rule that only runs in CI would let bad data reach the app first and get
caught afterwards — which is backwards when the whole point is that the
app's advice is only as good as this data.

So the same rules run in two places: the researcher checks its own output
before writing anything, and the tests check what's committed. A file that
fails validation is rejected and the previous week's data is kept, because
stale research that is known to be stale beats fresh research that is
wrong.
"""
import re

# What counts as substantial enough to be worth reading. Below these
# lengths an entry is a placeholder rather than an argument.
MIN_CASE_CHARS = 60
MIN_TAKE_CHARS = 30
MIN_STATS = 2

VALID_TIERS = ("must_have", "strong", "value", "avoid")
# How likely he is to start, as a human would say it. Minutes decide more
# gameweeks than any rate does, and the FPL API carries nothing about them
# beyond a blunt availability flag that only moves once a club confirms an
# injury -- by which point everyone knows.
VALID_STARTS = ("nailed", "likely", "rotation risk", "doubt", "out")
VALID_STANCES = ("avoid", "caution", "target")
VALID_POSITIONS = ("GKP", "DEF", "MID", "FWD")

# Prose that is making a claim about a whole club rather than one player.
# Stored on a player it reaches one player; the optimiser goes on picking
# the club's other twenty.
CLUB_WIDE_PROSE = re.compile(
    r"avoid\s+(?:all\s+)?(?P<club>[A-Z][a-zA-Z']+(?:\s+[A-Z][a-zA-Z']+)?)"
    r"\s+(?:assets|players|defenders|attackers|midfielders)",
    re.IGNORECASE,
)

CLUB_ALIASES = {
    "bournemouth": "BOU", "coventry": "COV", "hull": "HUL", "hull city": "HUL",
    "ipswich": "IPS", "sunderland": "SUN", "arsenal": "ARS", "chelsea": "CHE",
    "everton": "EVE", "brentford": "BRE", "newcastle": "NEW", "liverpool": "LIV",
    "man city": "MCI", "manchester city": "MCI", "man utd": "MUN",
    "manchester united": "MUN", "spurs": "TOT", "tottenham": "TOT",
    "aston villa": "AVL", "crystal palace": "CRY", "brighton": "BHA",
    "fulham": "FUL", "wolves": "WOL", "west ham": "WHU",
    "nottingham forest": "NFO", "leeds": "LEE", "burnley": "BUR",
}


def validate_players(data: dict, team_context: dict | None = None) -> list[str]:
    """Problems with a per-player consensus file. Empty means it's fine."""
    problems: list[str] = []
    entries = data.get("players")

    if not isinstance(entries, list) or not entries:
        return ["the file contains no player entries"]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(data.get("researched", ""))):
        problems.append("no valid `researched` date, so nobody can tell how stale it is")

    seen = set()
    for entry in entries:
        name = entry.get("name")
        if not name:
            problems.append("an entry has no name")
            continue
        if name in seen:
            problems.append(f"{name} appears twice")
        seen.add(name)

        if entry.get("tier") not in VALID_TIERS:
            problems.append(f"{name}: tier {entry.get('tier')!r} is not one of {VALID_TIERS}")
        if not (entry.get("case") or entry.get("reason")):
            problems.append(f"{name}: no stated case")
        if not entry.get("watch_out"):
            problems.append(f"{name}: no counter-argument — a recommendation you can't argue "
                            f"against isn't advice")
        if not entry.get("sources"):
            problems.append(f"{name}: cites no sources")

        stats = entry.get("key_stats") or []
        if len(stats) < MIN_STATS:
            problems.append(f"{name}: fewer than {MIN_STATS} supporting numbers")

        voices = entry.get("voices") or []
        if not voices:
            problems.append(f"{name}: records no attributed takes — 'analysts say' is not a source")
        for voice in voices:
            if not isinstance(voice, dict) or not voice.get("source"):
                problems.append(f"{name}: has an unattributed take")
            elif len(voice.get("take", "")) < MIN_TAKE_CHARS:
                problems.append(f"{name}: take from {voice['source']} is too thin to be informative")

        dissent = entry.get("dissent")
        if dissent is not None:
            if not isinstance(dissent, dict) or not dissent.get("case"):
                problems.append(f"{name}: dissent states no case")
            elif not dissent.get("sources"):
                problems.append(f"{name}: dissent cites no sources")
            if entry.get("tier") == "must_have":
                problems.append(
                    f"{name}: locked in as a must-have while the file records a dissent — the "
                    f"lock is for near-unanimity"
                )

        start = entry.get("predicted_start")
        if start is not None and start not in VALID_STARTS:
            problems.append(
                f"{name}: predicted_start {start!r} is not one of {VALID_STARTS} — an unrecognised "
                f"value is silently ignored, which is worse than an absent one"
            )
        if start == "out" and entry.get("tier") != "avoid":
            problems.append(
                f"{name}: reported as out but tiered {entry.get('tier')!r} — a player who isn't "
                f"playing cannot be a recommendation"
            )

        problems.extend(_club_wide_prose_problems(entry, team_context or {}))

    return problems


def _club_wide_prose_problems(entry: dict, team_context: dict) -> list[str]:
    prose = " ".join(
        str(entry.get(field) or "") for field in ("case", "watch_out", "verdict", "reason")
    )
    problems = []
    for match in CLUB_WIDE_PROSE.finditer(prose):
        short = CLUB_ALIASES.get(match.group("club").strip().lower())
        if short is None:
            continue
        if not team_context.get(short, {}).get("stances"):
            problems.append(
                f"{entry['name']}'s write-up says {match.group(0)!r}, but {short} carries no "
                f"stance in teams.json — so that advice reaches only {entry['name']}"
            )
    return problems


def validate_teams(data: dict) -> list[str]:
    """Problems with the club-stance file."""
    problems: list[str] = []
    teams = data.get("teams")
    if not isinstance(teams, list) or not teams:
        return ["the file contains no teams"]

    shorts = [t.get("short_name") for t in teams]
    if len(shorts) != len(set(shorts)):
        problems.append("duplicate club entries silently shadow each other")

    for team in teams:
        short = team.get("short_name")
        for stance in team.get("stances", []) or []:
            label = stance.get("stance")
            if label not in VALID_STANCES:
                problems.append(f"{short}: stance {label!r} would be ignored silently")
            scope = stance.get("scope", "all")
            if scope != "all":
                unknown = {str(p).upper() for p in scope} - set(VALID_POSITIONS)
                if unknown:
                    problems.append(f"{short}: stance scopes unknown positions {unknown}")
            if len(stance.get("case", "")) < MIN_CASE_CHARS:
                problems.append(f"{short}: stance reasoning is too thin to be useful")
            if not stance.get("sources"):
                problems.append(f"{short}: stance cites no sources")
            until = stance.get("until_gameweek")
            if until is None:
                problems.append(
                    f"{short}: stance has no until_gameweek — it will still be applied in May"
                )
            elif not (1 <= int(until) <= 38):
                problems.append(f"{short}: until_gameweek {until} is outside the season")
    return problems


def validate_odds(data: dict) -> list[str]:
    """Problems with the odds / captain-share file."""
    problems: list[str] = []
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(data.get("researched", ""))):
        problems.append("no valid `researched` date — odds go stale within days")

    entries = data.get("players")
    if not isinstance(entries, list) or not entries:
        return problems + ["the file contains no priced players"]

    for entry in entries:
        name = entry.get("name")
        if not name:
            problems.append("a price has no player name")
            continue
        price = entry.get("anytime_goalscorer")
        if price is not None and (not isinstance(price, (int, float)) or price <= 1.0):
            problems.append(f"{name}: {price!r} is not a plausible decimal price")
        share = entry.get("captain_share")
        if share is not None and not (0 <= float(share) <= 100):
            problems.append(f"{name}: captain share {share!r} is not a percentage")

    total_share = sum(
        float(e.get("captain_share") or 0) for e in entries
    )
    if total_share > 130:
        problems.append(
            f"captain shares total {total_share:.0f}%, which is more than the field can spend — "
            f"every manager has one armband"
        )
    return problems
