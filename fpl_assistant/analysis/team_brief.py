"""A club-by-club briefing: what's coming up, and who to care about.

The fixture table answers "which teams have easy games", which is only
half a decision. Knowing Everton have a green run tells you nothing about
*which Everton player to buy*, whether their defence is the way in or
their attack is, or that their best asset is carrying a knock. That gap is
where the fixture ticker stops being useful and you go and look somewhere
else.

So a brief pairs the run with the squad: the fixtures, the assets worth
knowing about at each position, and the pros and cons stated plainly.
Every line is derived from data already in the app -- projections, prices,
ownership, availability, European commitments and the researched club
stances -- rather than written by hand, so it stays true as the season
moves and doesn't rot the way a hand-written team preview would.
"""
from dataclasses import dataclass, field

import pandas as pd

from fpl_assistant.analysis import consensus

# A run at or below this average difficulty is worth chasing; at or above
# the upper bound it's worth avoiding. Between them the fixtures aren't
# the deciding factor and the brief says so rather than inventing a lean.
EASY_RUN = 2.6
HARD_RUN = 3.5

# How many players to surface per club. Enough to cover the realistic
# routes in (a defender, a midfielder, a forward, maybe a keeper) without
# turning into a squad list.
MAX_ASSETS = 5

# Below this projected total a player isn't a route into the team, he's
# just someone who plays there.
MIN_ASSET_XP = 1.0

EUROPE_LABELS = {
    "ucl": "Champions League",
    "uel": "Europa League",
    "uecl": "Conference League",
}


@dataclass
class Asset:
    """One player worth knowing about at this club."""

    player_id: int
    name: str
    position: str
    price: float
    ownership: float
    xp_next: float
    xp_horizon: float
    note: str | None = None
    flagged: bool = False


@dataclass
class TeamBrief:
    team_id: int
    short_name: str
    name: str
    fixtures: list[tuple[str, float | None]] = field(default_factory=list)
    avg_difficulty: float | None = None
    blanks: int = 0
    doubles: int = 0
    headline: str = ""
    stance: str | None = None
    stance_case: str | None = None
    stance_sources: str | None = None
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)

    @property
    def run_quality(self) -> str:
        """easy / mixed / hard — used for colour, so it must not lie."""
        if self.avg_difficulty is None:
            return "mixed"
        if self.avg_difficulty <= EASY_RUN:
            return "easy"
        if self.avg_difficulty >= HARD_RUN:
            return "hard"
        return "mixed"


def _num(row, column, default=0.0) -> float:
    value = pd.to_numeric(row.get(column), errors="coerce")
    return default if value is None or pd.isna(value) else float(value)


def _assets(scored: pd.DataFrame, team_id: int) -> list[Asset]:
    """The routes into this team, best first, one per position at least.

    Sorted by projection but forced to span positions: a pure top-N would
    hand back four Arsenal defenders on a clean-sheet run and never
    mention the striker, which is the opposite of what someone scanning a
    team wants to know.
    """
    squad = scored[scored["team"] == team_id]
    if squad.empty:
        return []

    ranked = squad.sort_values("xp_horizon", ascending=False)
    chosen: list[pd.Series] = []
    seen_positions: set[str] = set()

    # Best at each position first, so every realistic route is represented.
    for _, row in ranked.iterrows():
        position = str(row.get("position") or "")
        if position and position not in seen_positions:
            seen_positions.add(position)
            chosen.append(row)

    # Then fill the remaining places with the best of the rest.
    chosen_ids = {row["id"] for row in chosen}
    for _, row in ranked.iterrows():
        if len(chosen) >= MAX_ASSETS:
            break
        if row["id"] not in chosen_ids:
            chosen.append(row)
            chosen_ids.add(row["id"])

    chosen = [row for row in chosen if _num(row, "xp_horizon") >= MIN_ASSET_XP]
    chosen.sort(key=lambda row: -_num(row, "xp_horizon"))

    assets = []
    for row in chosen[:MAX_ASSETS]:
        tier = row.get("consensus_tier")
        note = None
        if isinstance(tier, str):
            note = {
                "must_have": "Consensus must-have",
                "strong": "Analysts rate him",
                "value": "Value pick",
                "neutral": "Researched, no strong view",
                "avoid": "Analysts say avoid",
            }.get(tier)
        news = row.get("news")
        flagged = isinstance(news, str) and bool(news.strip())
        if flagged:
            note = str(news).strip()

        assets.append(
            Asset(
                player_id=int(row["id"]),
                name=str(row["web_name"]),
                position=str(row.get("position") or ""),
                price=_num(row, "price"),
                ownership=_num(row, "selected_by_percent"),
                xp_next=_num(row, "xp_next"),
                xp_horizon=_num(row, "xp_horizon"),
                note=note,
                flagged=flagged,
            )
        )
    return assets


def _pros_and_cons(
    brief: TeamBrief, scored: pd.DataFrame, team_id: int, context: dict
) -> tuple[list[str], list[str]]:
    """Everything worth knowing, split into the two columns people read.

    Written as claims with the number attached, because "good fixtures" is
    not information and "2.2 average difficulty over five, three of them
    at home" is.
    """
    pros: list[str] = []
    cons: list[str] = []
    squad = scored[scored["team"] == team_id]

    # --- fixtures ---
    home = sum(1 for label, _ in brief.fixtures if "(H)" in label)
    if brief.avg_difficulty is not None:
        run = f"{brief.avg_difficulty:.1f} average difficulty over the next {len(brief.fixtures)}"
        if brief.run_quality == "easy":
            pros.append(f"Kind run — {run}, {home} at home.")
        elif brief.run_quality == "hard":
            cons.append(f"Tough run — {run}, only {home} at home.")
        else:
            pros.append(f"Middling run — {run}, {home} at home. Fixtures aren't the deciding factor.")

    if brief.doubles:
        pros.append(f"{brief.doubles} double gameweek(s) in the window — two scores for one squad place.")
    if brief.blanks:
        cons.append(f"{brief.blanks} blank gameweek(s) in the window — no fixture, no points.")

    # --- club-level context ---
    europe = EUROPE_LABELS.get(str(context.get("european_competition") or "none"))
    if europe:
        cons.append(
            f"{europe} football midweek, so rotation risk on anyone who isn't nailed."
            + (" Thursday nights leave two fewer recovery days." if europe == "Europa League" else "")
        )
    else:
        pros.append("No European football — one game a week, and a settled, rested XI while rivals travel.")

    if context.get("new_manager"):
        cons.append("New manager, so the XI is unsettled and early team news is worth more than form.")

    # --- squad shape ---
    if not squad.empty:
        attackers = squad[squad["position"].isin(["MID", "FWD"])]
        defenders = squad[squad["position"].isin(["GKP", "DEF"])]
        if not attackers.empty and not defenders.empty:
            attack_best = attackers["xp_horizon"].max()
            defence_best = defenders["xp_horizon"].max()
            if attack_best > defence_best * 1.25:
                pros.append("The attack is the way in here — their forwards project well ahead of their defence.")
            elif defence_best > attack_best * 1.1:
                pros.append("The defence is the way in here — clean sheets project ahead of their attacking returns.")

        cheap_defence = defenders[defenders["price"] <= 4.5]
        if not cheap_defence.empty and brief.run_quality == "easy":
            best = cheap_defence.sort_values("xp_horizon", ascending=False).iloc[0]
            pros.append(
                f"Cheap defensive cover on a good run — {best['web_name']} at £{_num(best,'price'):.1f}m."
            )

        flagged = squad[squad["news"].astype(str).str.strip().ne("") & squad["news"].notna()]
        if len(flagged):
            names = ", ".join(flagged.sort_values("xp_horizon", ascending=False)["web_name"].head(3))
            cons.append(f"{len(flagged)} player(s) carrying a fitness or availability flag, including {names}.")

        owned = pd.to_numeric(squad.get("selected_by_percent"), errors="coerce").fillna(0)
        if (owned >= 20).any():
            top = squad.loc[owned.idxmax()]
            pros.append(
                f"{top['web_name']} is {owned.max():.0f}% owned — not owning him is itself a position."
            )

    return pros, cons


def build_briefs(
    scored: pd.DataFrame,
    fixture_table: pd.DataFrame,
    teams: pd.DataFrame,
    gameweeks: list[int],
) -> list[TeamBrief]:
    """One brief per club, hardest run last.

    Ordered by fixture difficulty rather than alphabetically because the
    question this answers is "who should I be buying", and that ordering
    puts the answer at the top.
    """
    context = consensus.load_team_context()
    briefs: list[TeamBrief] = []

    for team_id, team_row in teams.iterrows():
        if team_id not in fixture_table.index:
            continue
        row = fixture_table.loc[team_id]
        short = str(team_row.get("short_name") or "")
        club = context.get(short.upper(), {})

        fixtures = []
        for gw in gameweeks:
            if gw not in row.index:
                continue
            label = str(row[gw])
            difficulty = row.get(f"{gw}_difficulty")
            fixtures.append((label, None if pd.isna(difficulty) else float(difficulty)))

        avg = pd.to_numeric(row.get("avg_difficulty"), errors="coerce")
        brief = TeamBrief(
            team_id=int(team_id),
            short_name=short,
            name=str(team_row.get("name") or short),
            fixtures=fixtures,
            avg_difficulty=None if pd.isna(avg) else float(avg),
            blanks=int(pd.to_numeric(row.get("blank_gameweeks"), errors="coerce") or 0),
            doubles=int(pd.to_numeric(row.get("double_gameweeks"), errors="coerce") or 0),
        )

        # The researched verdict, where analysts have one, takes the
        # headline -- a human judgement about a club beats a number
        # derived from the same fixtures the number came from.
        stances = club.get("stances") or []
        applicable = [
            stance for stance in stances
            if consensus.stance_coverage(stance, gameweeks[0] if gameweeks else 1, len(gameweeks) or 1) > 0
        ]
        if applicable:
            strongest = max(
                applicable,
                key=lambda s: abs(consensus.CLUB_STANCE_BONUS.get(s.get("stance"), 0.0)),
            )
            brief.stance = strongest.get("stance")
            brief.stance_case = strongest.get("case")
            brief.stance_sources = ", ".join(strongest.get("sources", []) or []) or None

        brief.assets = _assets(scored, int(team_id))
        brief.pros, brief.cons = _pros_and_cons(brief, scored, int(team_id), club)

        if brief.stance == "avoid":
            brief.headline = "Analysts are steering clear"
        elif brief.stance == "caution":
            brief.headline = "Flagged as a risk"
        elif brief.stance == "target":
            brief.headline = "Analysts are actively recommending them"
        else:
            brief.headline = {
                "easy": "Good run — worth shopping here",
                "hard": "Hard run — think twice",
                "mixed": "Mixed run — pick on the player, not the fixtures",
            }[brief.run_quality]

        briefs.append(brief)

    briefs.sort(key=lambda b: (b.avg_difficulty if b.avg_difficulty is not None else 99))
    return briefs
