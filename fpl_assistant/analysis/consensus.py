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


def load_consensus(gameweek: int) -> dict | None:
    """Reads this gameweek's consensus file, if one has been researched."""
    path = CONSENSUS_DIR / f"gw{gameweek}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


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

        df.loc[df["id"] == chosen_id, "consensus_tier"] = tier
        df.loc[df["id"] == chosen_id, "consensus_bonus"] = TIER_BONUS[tier]
        df.loc[df["id"] == chosen_id, "consensus_reason"] = entry.get("reason")

    return df


def must_have_ids(scored: pd.DataFrame) -> list[int]:
    """Players the consensus says are non-negotiable, and who are actually
    available -- a lock on an injured player would make the squad
    unsolvable for no benefit."""
    if "consensus_tier" not in scored.columns:
        return []
    locked = scored[
        (scored["consensus_tier"] == MUST_HAVE_TIER) & (scored.get("status", "a") == "a")
    ]
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
