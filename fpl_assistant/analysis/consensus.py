"""Expert and community consensus as a first-class input to selection.

The projection model is good at things that are measurable and bad at
things that are known. Which player just inherited penalty duty, who the
manager said would start, that a defender is back from injury and the
cheaper cover is now redundant, that a fixture everyone has pencilled in
as easy is actually a trap -- this is the reasoning that decides real FPL
weeks, and none of it is legible to a model reading per-90 rates.

So consensus doesn't sit alongside the numbers as commentary. It enters
the objective directly:

  must_have  -> locked into the squad, full stop
  strong     -> a large points bonus, enough to beat marginal alternatives
  value      -> a moderate bonus, enough to break ties
  avoid      -> a large penalty

The must-have lock is the important one and it is deliberately absolute.
When something like 70% of managers and effectively every analyst have
landed on the same player, "the model ranked him fourth on expected
points" is not a reason to leave him out -- it's a sign the model is
missing what those people can see. Not owning a near-universal pick is an
active bet against the field, and the app should only make that bet when a
human decides to, never as a side effect of a scoring formula.
"""
import json
import re
from pathlib import Path

import pandas as pd

CONSENSUS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "consensus"

# Bonuses are in projected points, the same units as the rest of the model,
# so they trade honestly against it rather than operating on a mystery
# scale. Sized to matter: "strong" should beat a marginal alternative
# outright, not merely nudge it.
TIER_BONUS = {
    "must_have": 6.0,
    "strong": 2.5,
    "value": 1.2,
    "avoid": -8.0,
}
MUST_HAVE_TIER = "must_have"
AVOID_TIER = "avoid"

# --- Club-level verdicts -----------------------------------------------
# The bug this exists to fix: analysts say "avoid Bournemouth assets until
# the schedule clears", and that verdict was stored as a sentence inside
# one player's write-up. So it reached exactly one player. The optimiser,
# which only ever sees numbers, went on picking the club's other cheap
# defenders -- the advice was in the app but not in the algorithm, which is
# the worst kind of miss because the app looked like it knew.
#
# A club verdict applies to every player at the club. It is expressed in
# the same points units as everything else so it trades honestly against
# the projection rather than acting as a veto: an outright ban would drop
# a genuinely elite player over a fixture run, and sometimes the elite
# player is still right.
CLUB_STANCE_BONUS = {
    "avoid": -5.0,
    "caution": -2.0,
    "target": 1.5,
}
ALL_POSITIONS = ("GKP", "DEF", "MID", "FWD")

# When analysts disagree about a player, the confident version of either
# view is wrong. Damping the bonus is more honest than picking a side, and
# the dissent is surfaced in the write-up so the disagreement is visible
# rather than averaged away silently.
DISSENT_DAMPING = 0.45


def load_consensus(gameweek: int) -> dict | None:
    """Reads this gameweek's consensus file, if one has been researched."""
    path = CONSENSUS_DIR / f"gw{gameweek}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def load_consensus_any() -> dict | None:
    """The most recent researched gameweek, whichever that is.

    Search shouldn't come back empty just because the current gameweek
    hasn't been researched yet -- last week's verdict on a player is stale
    but it is not nothing, and it's what someone typing a name is looking
    for.
    """
    files = sorted(
        CONSENSUS_DIR.glob("gw*.json"),
        key=lambda path: int(re.sub(r"\D", "", path.stem) or 0),
        reverse=True,
    )
    for path in files:
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
    return None


def load_team_context() -> dict[str, dict]:
    """Club-level context keyed by FPL short name.

    Separate from the per-player consensus because it changes rarely (a
    European qualification lasts a season) while player verdicts change
    weekly — and because it applies to every player at a club, not to the
    handful analysts happened to write about.
    """
    path = CONSENSUS_DIR / "teams.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return {
        str(entry["short_name"]).upper(): entry
        for entry in data.get("teams", [])
        if entry.get("short_name")
    }


def researched_on(gameweek: int) -> str | None:
    """When this gameweek's research was actually done.

    Every football claim in these files has a shelf life measured in days
    -- an injury clears, a manager confirms a lineup, a price moves. The
    date has to be visible next to the advice, because advice that looks
    equally confident whether it was written this morning or three weeks
    ago is the thing that gets someone to trust a stale fact.
    """
    data = load_consensus(gameweek) or {}
    value = data.get("researched")
    return str(value) if value else None


def _name_variants(row: pd.Series) -> list[str]:
    """Every plausible way this player might be named in research prose.

    FPL's `web_name` is compact and inconsistent ("B.Fernandes", "Joao
    Pedro", "Haaland"), while analysts write full names. Matching on
    web_name alone silently drops most of the consensus file on the floor,
    which is the worst possible failure here: it looks like it worked.
    """
    variants = set()
    for key in ("web_name", "second_name"):
        value = row.get(key)
        if pd.notna(value) and value:
            variants.add(str(value))
    first, second = row.get("first_name"), row.get("second_name")
    if pd.notna(first) and pd.notna(second) and first and second:
        variants.add(f"{first} {second}")
    return [v for v in variants if v]


def _normalise(name: str) -> str:
    """Casefold and strip punctuation/accents-ish so "B.Fernandes",
    "B Fernandes" and "Fernandes" compare sensibly."""
    return re.sub(r"[^a-z ]", "", str(name).lower()).strip()


def match_score(player_row: pd.Series, entry: dict) -> int:
    """How well this player matches a consensus entry. 0 means no match.

    Graded rather than boolean because names collide: Arsenal have fielded
    more than one prominent "Gabriel", and a surname like "White" is not
    rare. A boolean matcher tags every collision, and since must-haves are
    locked into the squad, tagging several players from one entry can
    over-constrain the solve until it's infeasible -- at which point the
    whole thing silently falls back to the heuristic builder and the
    must-have doesn't get picked at all. Exactly the failure this layer
    exists to prevent, arrived at from the other direction.
    """
    exact_targets = {_normalise(entry["name"])}
    loose_targets = set()
    if entry.get("full_name"):
        exact_targets.add(_normalise(entry["full_name"]))
        loose_targets.add(_normalise(entry["full_name"].split()[-1]))

    best = 0
    for variant in _name_variants(player_row):
        candidate = _normalise(variant)
        if not candidate:
            continue
        if candidate in exact_targets:
            best = max(best, 3)
            continue
        if candidate in loose_targets:
            best = max(best, 2)
            continue
        # Whole-token containment only, so "White" matches "Ben White" but
        # never "Whitehead".
        for target in exact_targets | loose_targets:
            if not target:
                continue
            if re.search(rf"\b{re.escape(candidate)}\b", target) or re.search(
                rf"\b{re.escape(target)}\b", candidate
            ):
                best = max(best, 1)
    return best


def _stance_scope(stance: dict) -> tuple[str, ...]:
    scope = stance.get("scope", "all")
    if isinstance(scope, str):
        return ALL_POSITIONS if scope == "all" else (scope.upper(),)
    return tuple(str(p).upper() for p in scope) or ALL_POSITIONS


def stance_coverage(stance: dict, from_event: int, horizon: int) -> float:
    """What fraction of the projection window this verdict actually covers.

    A club verdict is nearly always temporary -- "avoid them until the
    fixtures turn around GW9" -- so it has to fade rather than switch off,
    and it has to switch off eventually. Without this the file rots: a
    fixture-run warning written in August silently keeps penalising the
    club in December, long after the run it described has been played.

    `until_gameweek` is exclusive, so a stance that runs until 9 applies
    through GW8 and is gone by GW9.
    """
    until = stance.get("until_gameweek")
    if until is None:
        return 1.0
    remaining = int(until) - int(from_event)
    if remaining <= 0:
        return 0.0
    return min(remaining, max(horizon, 1)) / max(horizon, 1)


def annotate_clubs(
    players: pd.DataFrame,
    team_context: dict[str, dict],
    from_event: int,
    horizon: int,
) -> pd.DataFrame:
    """Applies club-level expert verdicts to every player at that club.

    This is the layer that was missing. Per-player consensus only covers
    the handful of players analysts wrote about by name; a club verdict
    covers the squad. When the advice is "avoid this club's assets", the
    twentieth-choice £4.0m defender is precisely the player the optimiser
    would otherwise reach for, because he looks cheap and the model can't
    see why he's cheap.

    Adds `club_stance`, `club_stance_bonus`, `club_stance_case` and
    `club_stance_until`. Strongest-magnitude stance wins where a club has
    several covering the same position.
    """
    df = players.copy()
    df["club_stance"] = None
    df["club_stance_bonus"] = 0.0
    df["club_stance_case"] = None
    df["club_stance_until"] = pd.NA
    df["club_stance_sources"] = None

    if not team_context or "team_short_name" not in df.columns:
        return df

    positions = df.get("position")
    if positions is None:
        return df

    shorts = df["team_short_name"].astype("string").str.upper()

    for short_name, entry in team_context.items():
        for stance in entry.get("stances", []) or []:
            label = stance.get("stance")
            if label not in CLUB_STANCE_BONUS:
                continue
            coverage = stance_coverage(stance, from_event, horizon)
            if coverage <= 0:
                continue
            bonus = CLUB_STANCE_BONUS[label] * coverage

            target = (shorts == short_name) & positions.isin(_stance_scope(stance))
            # Only overwrite where this stance is the more emphatic one, so
            # a club carrying both an "avoid" for defenders and a milder
            # "caution" for attackers doesn't have one clobber the other.
            stronger = target & (df["club_stance_bonus"].abs() < abs(bonus))
            df.loc[stronger, "club_stance"] = label
            df.loc[stronger, "club_stance_bonus"] = bonus
            df.loc[stronger, "club_stance_case"] = stance.get("case")
            df.loc[stronger, "club_stance_until"] = stance.get("until_gameweek")
            df.loc[stronger, "club_stance_sources"] = (
                ", ".join(stance.get("sources", []) or []) or None
            )

    return df


def annotate(players: pd.DataFrame, gameweek: int) -> pd.DataFrame:
    """Adds `consensus_tier`, `consensus_bonus` and `consensus_reason`.

    Players absent from the consensus file get a zero bonus rather than a
    penalty -- silence from the analysts is not a verdict against someone,
    it usually just means they weren't worth writing about this week.
    """
    df = players.copy()
    df["consensus_tier"] = None
    df["consensus_bonus"] = 0.0
    df["consensus_reason"] = None
    df["consensus_verdict"] = None
    df["consensus_watch_out"] = None
    df["consensus_dissent"] = None
    df["consensus_sources"] = None
    # Stats and voices are lists of facts/attributed takes. They travel as
    # JSON strings rather than as objects in DataFrame cells: assigning a
    # list into a masked .loc treats it as an array to broadcast and either
    # raises or silently scatters the elements across rows.
    df["consensus_stats"] = None
    df["consensus_voices"] = None
    # Which gameweek's research this came from, so the app can say whether
    # a write-up is current or left over from an earlier week.
    df["consensus_gameweek"] = pd.NA
    # Three facts the FPL API either lags badly or doesn't carry at all,
    # and which decide more gameweeks than any rate does: whether he
    # starts, what he takes, and where he actually plays.
    df["predicted_start"] = None
    df["set_pieces"] = None
    df["role_note"] = None

    data = load_consensus(gameweek)
    if not data:
        return df

    for entry in data.get("players", []):
        tier = entry.get("tier")
        if tier not in TIER_BONUS:
            continue

        scores = df.apply(lambda row: match_score(row, entry), axis=1)
        if scores.max() <= 0:
            continue

        # Resolve to a single player. Among equally good name matches the
        # intended one is essentially always the prominent player -- that's
        # who analysts write about -- so ownership breaks the tie, with
        # price behind it.
        candidates = df[scores == scores.max()].copy()
        if len(candidates) > 1:
            ownership = pd.to_numeric(
                candidates.get("selected_by_percent", 0), errors="coerce"
            ).fillna(0.0)
            price = pd.to_numeric(candidates.get("price", 0), errors="coerce").fillna(0.0)
            candidates = candidates.assign(_own=ownership, _price=price).sort_values(
                ["_own", "_price"], ascending=False
            )
        chosen_id = candidates["id"].iloc[0]

        target = df["id"] == chosen_id
        # Analysts do not always agree, and a file that records only the
        # majority view presents a genuinely contested pick as a settled
        # one. Where a dissent is recorded the bonus is damped towards
        # neutral: the honest position on a disputed player is a weaker
        # opinion, not a confident one in either direction.
        dissent = entry.get("dissent")
        bonus = TIER_BONUS[tier] * (DISSENT_DAMPING if dissent else 1.0)

        df.loc[target, "consensus_tier"] = tier
        df.loc[target, "consensus_bonus"] = bonus
        df.loc[target, "consensus_dissent"] = (
            dissent.get("case") if isinstance(dissent, dict) else dissent
        )
        df.loc[target, "consensus_sources"] = ", ".join(entry.get("sources", []) or []) or None
        df.loc[target, "consensus_gameweek"] = data.get("gameweek", gameweek)
        df.loc[target, "predicted_start"] = entry.get("predicted_start")
        df.loc[target, "set_pieces"] = entry.get("set_pieces")
        df.loc[target, "role_note"] = entry.get("role")
        df.loc[target, "consensus_stats"] = _pack(entry.get("key_stats"))
        df.loc[target, "consensus_voices"] = _pack(entry.get("voices"))
        # `case` is the written argument; `reason` is kept as a fallback so
        # older hand-written consensus files still render.
        df.loc[target, "consensus_reason"] = entry.get("case") or entry.get("reason")
        df.loc[target, "consensus_verdict"] = entry.get("verdict")
        df.loc[target, "consensus_watch_out"] = entry.get("watch_out")

    return df


def _pack(value) -> str | None:
    """JSON-encodes a list for storage in a DataFrame cell."""
    return json.dumps(value) if value else None


def unpack(value) -> list:
    """Reads back a column packed by `_pack`, tolerating anything else.

    Callers render this straight into the page, so a malformed cell has to
    come back as "nothing to show" rather than as an exception on a tab the
    user has already opened.
    """
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    return decoded if isinstance(decoded, list) else []


def key_stats(row: pd.Series) -> list[str]:
    """The hard numbers behind a player's verdict, as discrete facts."""
    return [str(stat) for stat in unpack(row.get("consensus_stats"))]


def voices(row: pd.Series) -> list[tuple[str, str]]:
    """What named outlets are actually saying, as (source, take) pairs.

    Attribution is the point. A synthesised paragraph loses who thinks
    what, and "analysts say" is not a source -- it's the phrasing that let
    a wrong fact sit in this file unchallenged, because there was nobody
    to check it against.
    """
    pairs = []
    for item in unpack(row.get("consensus_voices")):
        if isinstance(item, dict) and item.get("take"):
            pairs.append((str(item.get("source") or "Analyst"), str(item["take"])))
    return pairs


def must_have_ids(scored: pd.DataFrame) -> list[int]:
    """Players the consensus says are non-negotiable, and who are actually
    available -- a lock on an injured player would make the squad
    unsolvable for no benefit."""
    if "consensus_tier" not in scored.columns:
        return []
    locked = scored[
        (scored["consensus_tier"] == MUST_HAVE_TIER) & (scored.get("status", "a") == "a")
    ]
    # A must-have that analysts are actually arguing about is not a
    # must-have. The lock exists for near-unanimity; applying it to a
    # contested player would force in a pick the app itself is reporting
    # doubt about, which is the opposite of what it is for.
    if "consensus_dissent" in locked.columns:
        locked = locked[locked["consensus_dissent"].isna()]
    return locked["id"].tolist()


def avoid_ids(scored: pd.DataFrame) -> list[int]:
    if "consensus_tier" not in scored.columns:
        return []
    return scored[scored["consensus_tier"] == AVOID_TIER]["id"].tolist()


def summary(scored: pd.DataFrame) -> pd.DataFrame:
    """The consensus picks the app actually matched, for display."""
    if "consensus_tier" not in scored.columns:
        return pd.DataFrame()
    matched = scored[scored["consensus_tier"].notna()]
    order = {"must_have": 0, "strong": 1, "value": 2, "avoid": 3}
    if matched.empty:
        return matched
    return matched.assign(_order=matched["consensus_tier"].map(order)).sort_values(
        ["_order", "consensus_bonus"], ascending=[True, False]
    )
