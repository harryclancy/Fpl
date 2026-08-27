"""The players any decision this week could actually involve.

Research used to be shaped by whatever the FPL media cycle covered that
week: search for who analysts are talking about, write those down, and end
up with a dozen entries. Everyone else in a ~700-player pool got derived
numbers and no opinion — including, sometimes, a player the model rated
highly and wanted to recommend.

That is the wrong way round. Coverage should be driven by need, not by
supply. The set of players a decision could touch is much smaller than the
pool and much better defined:

  * the fifteen you already own — you will hold, bench or sell each one
  * the realistic transfer targets in each position, within what you could
    actually spend
  * the template, because not owning a widely-owned player is itself a
    position you are taking
  * anyone the projection rates highly that you don't own, since those are
    exactly the recommendations that most need something behind them

That comes to a few dozen players rather than several hundred, which makes
full coverage a reachable target instead of an aspiration.

Depth is tiered, because not every one of them needs a written case. A
player you might buy needs the argument, the counter-argument and the
sources; a squad filler you will never start needs to be known to be fit
and playing.
"""
from dataclasses import dataclass, field

import pandas as pd

# Above this ownership, not owning someone is an active decision rather
# than an absence, so it needs explaining either way.
TEMPLATE_OWNERSHIP = 15.0

# How many transfer candidates to carry per position. Enough to cover the
# realistic moves at a given budget without dragging in the whole pool.
CANDIDATES_PER_POSITION = 8

# Players the projection rates this highly are recommendations in waiting,
# whether or not anyone has written about them.
MODEL_FAVOURITE_QUANTILE = 0.97

# What a player needs before a decision about him is properly informed.
DEPTH_FULL = "full"        # case, counter-argument, stats, attributed takes
DEPTH_FACTS = "facts"      # role, set pieces, fitness, minutes
DEPTH_NUMBERS = "numbers"  # the projection alone


@dataclass
class Entry:
    player_id: int
    name: str
    team: str
    position: str
    price: float
    ownership: float
    reasons: list[str] = field(default_factory=list)
    depth: str = DEPTH_FACTS

    @property
    def needs_writing_up(self) -> bool:
        return self.depth == DEPTH_FULL


@dataclass
class DecisionSet:
    entries: list[Entry] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.entries)

    @property
    def ids(self) -> set[int]:
        return {e.player_id for e in self.entries}

    def at_depth(self, depth: str) -> list[Entry]:
        return [e for e in self.entries if e.depth == depth]

    def by_position(self) -> dict[str, list[Entry]]:
        grouped: dict[str, list[Entry]] = {}
        for entry in self.entries:
            grouped.setdefault(entry.position, []).append(entry)
        return grouped


def _num(row, column, default=0.0) -> float:
    value = pd.to_numeric(row.get(column), errors="coerce")
    return default if value is None or pd.isna(value) else float(value)


def build(
    scored: pd.DataFrame,
    owned_ids: list[int] | None = None,
    bank: float = 0.0,
    candidates_per_position: int = CANDIDATES_PER_POSITION,
) -> DecisionSet:
    """Everything this week's decisions could touch, with why and how deep.

    Affordability is judged per position against the cheapest player you
    already own there plus the bank — the actual money available for a
    like-for-like swap. Judging it against the whole squad value would
    sweep in premiums no single transfer could reach.
    """
    owned = set(owned_ids or [])
    if scored is None or scored.empty or "id" not in scored.columns:
        return DecisionSet()
    # `.get("status", "a")` returns the bare string when the column is
    # absent, and `"a" == "a"` is then a plain True that indexes as a
    # column label rather than a mask. Same trap as the projection's
    # optional-column reads; check the column exists instead.
    pool = scored[scored["status"] == "a"].copy() if "status" in scored.columns else scored.copy()
    if pool.empty:
        return DecisionSet()

    ownership = pd.to_numeric(pool.get("selected_by_percent", 0), errors="coerce").fillna(0.0)
    horizon = pd.to_numeric(pool.get("xp_horizon", 0), errors="coerce").fillna(0.0)
    pool = pool.assign(_own=ownership, _xp=horizon)

    reasons: dict[int, list[str]] = {}

    def note(player_id: int, reason: str) -> None:
        reasons.setdefault(int(player_id), [])
        if reason not in reasons[int(player_id)]:
            reasons[int(player_id)].append(reason)

    # --- your squad ---
    for pid in owned:
        if pid in set(pool["id"]):
            note(pid, "in your squad")

    # --- transfer candidates, position by position, at a reachable price ---
    for position, group in pool.groupby("position"):
        if owned:
            mine = pool[pool["id"].isin(owned) & (pool["position"] == position)]
            ceiling = (float(mine["price"].min()) + bank) if not mine.empty else None
        else:
            ceiling = None
        affordable = group if ceiling is None else group[group["price"] <= ceiling]
        if affordable.empty:
            affordable = group
        for _, row in affordable.nlargest(candidates_per_position, "_xp").iterrows():
            if int(row["id"]) not in owned:
                note(row["id"], f"a realistic {position} target at this budget")

    # --- the template ---
    for _, row in pool[pool["_own"] >= TEMPLATE_OWNERSHIP].iterrows():
        note(row["id"], f"{row['_own']:.0f}% owned — not owning him is a position too")

    # --- what the model wants to recommend ---
    if len(pool) > 20:
        threshold = pool["_xp"].quantile(MODEL_FAVOURITE_QUANTILE)
        for _, row in pool[pool["_xp"] >= threshold].iterrows():
            note(row["id"], "the projection rates him highly")

    indexed = pool.set_index("id", drop=False)
    entries: list[Entry] = []
    for pid, why in reasons.items():
        if pid not in indexed.index:
            continue
        row = indexed.loc[pid]
        entries.append(
            Entry(
                player_id=pid,
                name=str(row["web_name"]),
                team=str(row.get("team_short_name") or ""),
                position=str(row.get("position") or ""),
                price=_num(row, "price"),
                ownership=_num(row, "_own"),
                reasons=why,
                depth=_depth_for(pid, why, owned),
            )
        )

    entries.sort(key=lambda e: (e.depth != DEPTH_FULL, -e.ownership))
    return DecisionSet(entries=entries)


def _depth_for(player_id: int, reasons: list[str], owned: set[int]) -> str:
    """How much this player needs written about him.

    A player you might buy, or the field already owns, needs an argument
    you can disagree with. A squad filler you will never start needs to be
    known to be fit and playing — writing a case for him is effort spent
    where no decision is being made.
    """
    if any("target at this budget" in r for r in reasons):
        return DEPTH_FULL
    if any("owned — not owning him" in r for r in reasons):
        return DEPTH_FULL
    if any("projection rates him highly" in r for r in reasons):
        return DEPTH_FULL
    return DEPTH_FACTS


def coverage(decision_set: DecisionSet, scored: pd.DataFrame) -> dict:
    """How much of the decision set actually has research behind it.

    This is the number that says whether the app's advice is informed or
    merely computed, and it belongs in front of the user rather than in a
    developer's head.
    """
    if not decision_set.entries:
        return {"total": 0, "researched": 0, "missing": [], "share": 1.0}

    tiers = scored.set_index("id").get("consensus_tier")
    researched = set()
    if tiers is not None:
        researched = {int(i) for i, value in tiers.items() if isinstance(value, str)}

    needed = [e for e in decision_set.entries if e.needs_writing_up]
    covered = [e for e in needed if e.player_id in researched]
    missing = [e for e in needed if e.player_id not in researched]

    return {
        "total": len(needed),
        "researched": len(covered),
        "missing": missing,
        "share": (len(covered) / len(needed)) if needed else 1.0,
    }
