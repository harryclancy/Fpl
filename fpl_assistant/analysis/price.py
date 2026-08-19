"""Predicting price rises and falls.

Team value isn't points, which is why it sits in its own module rather
than in the projection — but it compounds into points. Every £0.1m gained
is budget for a better player later, and a manager who consistently buys
before a rise and sells before a fall ends the season with a squad worth
a couple of million more than someone who doesn't. That's a premium
player's worth of extra headroom.

FPL doesn't publish its price algorithm, but the driver is well
understood: prices move on *net transfers relative to how many people own
the player*. A player owned by 1% needs far fewer net transfers in to
rise than one owned by 40%, because the threshold scales with the
ownership base. So the useful signal isn't raw transfer counts — it's
transfer momentum normalised by ownership, which is what this computes.

Deliberately framed as pressure rather than a prediction of tonight's
changes: the exact thresholds are unpublished and drift, so a directional
"this is heating up" is honest where "this rises at 2am" would not be.
"""
from __future__ import annotations

import pandas as pd

# Roughly how many people play FPL. Only used to turn an ownership
# percentage into a headcount, so precision doesn't matter much — an order
# of magnitude does.
ACTIVE_MANAGERS = 11_000_000

# Net transfers as a share of the ownership base, above which a price move
# looks likely. Calibrated to flag the handful of players actually moving
# each night rather than half the game.
RISE_PRESSURE = 0.06
FALL_PRESSURE = -0.06
# Below this ownership the percentages get so jumpy that the ratio is
# noise -- a player owned by 0.1% can double their transfers on a rumour.
MIN_OWNERSHIP_FOR_SIGNAL = 0.3


def price_pressure(players: pd.DataFrame) -> pd.DataFrame:
    """Adds `net_transfers`, `price_pressure` and `price_signal`.

    `price_pressure` is net transfers as a fraction of the player's owner
    base: positive means money flowing in, negative means out. `price_signal`
    turns that into a plain verdict.
    """
    df = players.copy()

    transfers_in = pd.to_numeric(df.get("transfers_in_event", 0), errors="coerce").fillna(0.0)
    transfers_out = pd.to_numeric(df.get("transfers_out_event", 0), errors="coerce").fillna(0.0)
    ownership = pd.to_numeric(df.get("selected_by_percent", 0), errors="coerce").fillna(0.0)

    df["net_transfers"] = transfers_in - transfers_out

    owner_count = (ownership / 100.0) * ACTIVE_MANAGERS
    # Guard the divide: an unowned player has no base to move against.
    pressure = df["net_transfers"] / owner_count.where(owner_count > 0, pd.NA)
    df["price_pressure"] = pressure.fillna(0.0).round(4)

    thin = ownership < MIN_OWNERSHIP_FOR_SIGNAL
    signal = pd.Series("stable", index=df.index, dtype=object)
    signal = signal.mask(df["price_pressure"] >= RISE_PRESSURE, "rising")
    signal = signal.mask(df["price_pressure"] <= FALL_PRESSURE, "falling")
    # Too few owners for the ratio to mean anything.
    signal = signal.mask(thin, "stable")
    df["price_signal"] = signal

    return df


def movers(players: pd.DataFrame, limit: int = 8) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The clearest risers and fallers, most extreme first."""
    df = price_pressure(players) if "price_pressure" not in players.columns else players
    rising = df[df["price_signal"] == "rising"].nlargest(limit, "price_pressure")
    falling = df[df["price_signal"] == "falling"].nsmallest(limit, "price_pressure")
    return rising, falling


def price_note(row: pd.Series) -> str | None:
    """A one-line verdict for a player's writeup, with the consequence.

    Says what to *do*, not just what's happening: a rise is only useful if
    you were buying anyway, and a fall only matters if you were selling.
    """
    signal = row.get("price_signal")
    if signal is None or pd.isna(signal) or signal == "stable":
        return None

    net = row.get("net_transfers", 0)
    if signal == "rising":
        return (
            f"📈 **Price rising** — gaining {abs(net):,.0f} net transfers this gameweek. If he's "
            f"in your plans anyway, buying before the rise earns you the £0.1m; chasing a rise you "
            f"didn't want is how people end up with squads they didn't choose."
        )
    return (
        f"📉 **Price falling** — losing {abs(net):,.0f} net transfers this gameweek. If you own him "
        f"and were going to sell, doing it before the drop saves the £0.1m. Not a reason to sell a "
        f"player you rate."
    )
