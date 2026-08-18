"""Transfer suggestions: what's wrong with your squad, and who could replace it.

This is intentionally a *suggestion* engine, not an auto-transfer bot: it
flags owned players worth scrutinising and proposes plausible, affordable
replacements. The final call (and anything involving hits) is yours.
"""
import pandas as pd

from fpl_assistant.analysis.fixtures import team_fixture_table
from fpl_assistant.analysis.season_state import is_preseason
from fpl_assistant.models import Squad

WEAKNESS_FORM_THRESHOLD = 2.5
WEAKNESS_FIXTURE_THRESHOLD = 3.6  # avg FDR over the window above this = tough run
WEAKNESS_MINUTES_THRESHOLD = 0.5  # played less than half of possible minutes


def estimate_free_transfers(history_current: list[dict], chips: list[dict]) -> int:
    """Approximate free transfers available going into the *next* gameweek.

    Rules (2024/25+): +1 FT per gameweek up to a cap of 5, reset to 1 the
    gameweek after a Wildcard/Free Hit is played. This walks the season's
    gameweek history to simulate it. It's an approximation — if it ever
    disagrees with the official squad page, trust the official page.
    """
    chip_events = {c["event"] for c in chips if c["name"] in ("wildcard", "freehit")}

    ft = 1
    for gw in sorted(history_current, key=lambda g: g["event"]):
        event = gw["event"]
        if event == 1:
            continue
        if (event - 1) in chip_events:
            ft = 1
        else:
            ft = min(ft + 1, 5)
        ft = max(ft - gw.get("event_transfers", 0), 0)
    return ft


def squad_with_scores(
    players: pd.DataFrame, fixtures: pd.DataFrame, teams: pd.DataFrame, from_event: int, window: int = 5
) -> pd.DataFrame:
    """Every player enriched with a fixture-run score, for use by both the
    'what's wrong with my squad' and 'who could replace them' steps.
    """
    fixture_table = team_fixture_table(fixtures, teams, from_event=from_event, n_gameweeks=window)

    df = players.copy()
    df["fixture_run_difficulty"] = df["team"].map(fixture_table["avg_difficulty"])
    df["upcoming_blanks"] = df["team"].map(fixture_table["blank_gameweeks"])
    if is_preseason(players):
        # Nobody's played a minute yet -- a 0% minutes share would look like
        # a rotation risk for literally every player, which is noise, not
        # signal. Treat everyone as fully reliable until real data exists.
        df["minutes_share"] = 1.0
    else:
        df["minutes_share"] = (df["minutes"] / max(1, from_event - 1) / 90).clip(upper=1.0)
    return df


def squad_weaknesses(scored_players: pd.DataFrame, squad: Squad) -> pd.DataFrame:
    """Owned players worth considering moving on, with the reason(s) why."""
    owned = scored_players[scored_players["id"].isin(squad.player_ids)].copy()
    preseason = is_preseason(scored_players)

    def reasons(row) -> list[str]:
        r = []
        if row["status"] != "a":
            r.append(f"status: {row['status_label']}")
        if not preseason and row["form"] < WEAKNESS_FORM_THRESHOLD:
            r.append(f"poor form ({row['form']})")
        if pd.notna(row["fixture_run_difficulty"]) and row["fixture_run_difficulty"] > WEAKNESS_FIXTURE_THRESHOLD:
            r.append(f"tough fixture run ({row['fixture_run_difficulty']:.1f} avg FDR)")
        if row["upcoming_blanks"] > 0:
            r.append(f"{int(row['upcoming_blanks'])} blank gameweek(s) coming up")
        if row["minutes_share"] < WEAKNESS_MINUTES_THRESHOLD and row["minutes"] > 0:
            r.append("minutes risk")
        return r

    owned["reasons"] = owned.apply(reasons, axis=1)
    owned = owned[owned["reasons"].map(len) > 0]
    owned["reasons_text"] = owned["reasons"].map("; ".join)

    cols = ["web_name", "team_short_name", "position", "price", "form", "reasons_text"]
    return owned.sort_values("form")[cols]


def suggest_replacements(
    scored_players: pd.DataFrame,
    squad: Squad,
    outgoing_player_id: int,
    budget: float,
    top_n: int = 5,
) -> pd.DataFrame:
    """Affordable, available same-position players not already in the squad,
    ranked by a blend of form and fixture run — best replacements for one
    specific outgoing player.
    """
    outgoing = scored_players.loc[outgoing_player_id]
    max_price = outgoing["price"] + budget
    effective_min_minutes = 0 if is_preseason(scored_players) else 180

    pool = scored_players[
        (scored_players["position"] == outgoing["position"])
        & (~scored_players["id"].isin(squad.player_ids))
        & (scored_players["status"] == "a")
        & (scored_players["price"] <= max_price)
        & (scored_players["minutes"] >= effective_min_minutes)
    ].copy()

    lo, hi = pool["form"].min(), pool["form"].max()
    pool["form_norm"] = 0.5 if hi == lo else (pool["form"] - lo) / (hi - lo)
    fixture_lo, fixture_hi = pool["fixture_run_difficulty"].min(), pool["fixture_run_difficulty"].max()
    if fixture_hi == fixture_lo:
        pool["fixture_norm"] = 0.5
    else:
        pool["fixture_norm"] = 1 - (pool["fixture_run_difficulty"] - fixture_lo) / (
            fixture_hi - fixture_lo
        )

    pool["replacement_score"] = (0.5 * pool["form_norm"] + 0.5 * pool["fixture_norm"]).round(3)

    cols = [
        "web_name",
        "team_short_name",
        "price",
        "form",
        "fixture_run_difficulty",
        "replacement_score",
    ]
    return pool.sort_values("replacement_score", ascending=False)[cols].head(top_n)
