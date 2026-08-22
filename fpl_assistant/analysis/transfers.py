"""Transfer suggestions: what's wrong with your squad, and who could replace it.

This is intentionally a *suggestion* engine, not an auto-transfer bot: it
flags owned players worth scrutinising and proposes plausible, affordable
replacements. The final call (and anything involving hits) is yours.

Ranking is on the projection, not on form. That distinction is the whole
point of the module and it used to be the other way round: replacements
were scored half on FPL's `form` field -- points scored over the last
thirty days -- which meant one big week made a player look like the best
buy in the game. A promoted-side centre-back who scored and kept a clean
sheet in GW1 would out-rank an Arsenal defender, right up until you
noticed his side had Villa and Chelsea next.

`xp_horizon` already accounts for the things form cannot see: who they
play next, how likely they are to start, what their side concedes, and
whether the run is about to turn. Form is one input to that, weighted
appropriately, rather than half the answer.
"""
import pandas as pd

from fpl_assistant.analysis.fixtures import team_fixture_table
from fpl_assistant.analysis.season_state import is_preseason
from fpl_assistant.models import Squad

WEAKNESS_FORM_THRESHOLD = 2.5
WEAKNESS_FIXTURE_THRESHOLD = 3.6  # avg FDR over the window above this = tough run
WEAKNESS_MINUTES_THRESHOLD = 0.5  # played less than half of possible minutes

# Below this projected total over the window, an owned player is worth
# looking at regardless of what he did last week.
WEAKNESS_PROJECTION_PERCENTILE = 0.25

# A replacement has to beat the man he replaces by this much over the
# window before it's worth suggesting. Transfers are scarce and a
# near-identical swap wastes one.
MIN_UPGRADE_POINTS = 1.0


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

    cols = [
        "id", "code", "web_name", "team_short_name", "team_code",
        "position", "price", "form", "reasons_text",
    ]
    # Weakest by what they're projected to do next, not by what they did
    # last. Sorting on form puts a player who blanked once above one whose
    # whole run has turned, which is backwards -- the second is the
    # transfer worth making.
    if "xp_horizon" in owned.columns:
        cols = cols + ["xp_horizon"]
        return owned.sort_values("xp_horizon")[cols]
    return owned.sort_values("form")[cols]


def suggest_replacements(
    scored_players: pd.DataFrame,
    squad: Squad,
    outgoing_player_id: int,
    budget: float,
    top_n: int = 5,
) -> pd.DataFrame:
    """Affordable, available same-position players not already in the squad,
    ranked by projected points over the window — best replacements for one
    specific outgoing player.

    Ranked on the projection rather than on recent scoring, because those
    disagree exactly when it matters. A defender fresh off a goal and a
    clean sheet tops any form table; if his side face two of the best
    attacks next, he is still the wrong buy, and only a forward-looking
    number says so.
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

    if "xp_horizon" in pool.columns:
        # The projection already weighs fixtures, minutes, opponent
        # strength and form together, so ranking on it directly is both
        # simpler and better than re-blending two of those by hand.
        pool["replacement_score"] = pool["xp_horizon"].round(2)
        outgoing_projection = float(
            pd.to_numeric(pd.Series([outgoing.get("xp_horizon", 0)]), errors="coerce").fillna(0).iloc[0]
        )
        pool["upgrade"] = (pool["xp_horizon"] - outgoing_projection).round(2)
        # A swap that gains nothing burns a transfer. Only suggest one if
        # it's a real upgrade over the window.
        worthwhile = pool[pool["upgrade"] >= MIN_UPGRADE_POINTS]
        pool = worthwhile if not worthwhile.empty else pool
        sort_column = "replacement_score"
    else:
        # No projection attached (older callers pass a bare player table).
        # Fall back to the fixture run alone rather than to form: fixtures
        # are at least about the games still to be played.
        fixture_lo = pool["fixture_run_difficulty"].min()
        fixture_hi = pool["fixture_run_difficulty"].max()
        if fixture_hi == fixture_lo:
            pool["replacement_score"] = 0.5
        else:
            pool["replacement_score"] = (
                1 - (pool["fixture_run_difficulty"] - fixture_lo) / (fixture_hi - fixture_lo)
            ).round(3)
        pool["upgrade"] = 0.0
        sort_column = "replacement_score"

    cols = [
        "id", "code", "web_name", "team_short_name", "team_code", "position",
        "price",
        "form",
        "fixture_run_difficulty",
        "replacement_score",
        "upgrade",
    ]
    cols = [c for c in cols if c in pool.columns]
    return pool.sort_values(sort_column, ascending=False)[cols].head(top_n)
