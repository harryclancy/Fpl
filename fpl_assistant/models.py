"""Turns raw FPL API JSON into pandas DataFrames that are easy to analyse.

We use DataFrames rather than per-player dataclasses because almost every
piece of analysis here (form, fixture runs, captaincy scoring) is a
vectorised operation over "all players" or "all teams" — pandas is the
right tool, dataclasses would just mean rebuilding the same joins by hand.
"""
from dataclasses import dataclass

import pandas as pd

POSITION_NAMES = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

STATUS_LABELS = {
    "a": "Available",
    "d": "Doubtful",
    "i": "Injured",
    "s": "Suspended",
    "u": "Unavailable",
    "n": "Not in squad",
}

# Fields the FPL API exposes that the expected-points model consumes. All are
# read defensively (missing -> 0/NA) because the API has added and renamed
# stats between seasons -- notably the per-90 family and, more recently,
# defensive contributions. A missing column should degrade the model, never
# crash it.
RATE_COLUMNS = (
    "expected_goals_per_90",
    "expected_assists_per_90",
    "expected_goal_involvements_per_90",
    "expected_goals_conceded_per_90",
    "saves_per_90",
    "starts_per_90",
    "defensive_contribution_per_90",
)
COUNT_COLUMNS = (
    "starts",
    "saves",
    "clean_sheets",
    "goals_conceded",
    "goals_scored",
    "assists",
    "bps",
    "defensive_contribution",
    "yellow_cards",
    "red_cards",
)
SET_PIECE_COLUMNS = (
    "penalties_order",
    "direct_freekicks_order",
    "corners_and_indirect_freekicks_order",
)


TEAM_STRENGTH_COLUMNS = (
    "strength_attack_home",
    "strength_attack_away",
    "strength_defence_home",
    "strength_defence_away",
    "strength_overall_home",
    "strength_overall_away",
)


def teams_df(bootstrap: dict) -> pd.DataFrame:
    df = pd.DataFrame(bootstrap["teams"])
    # FPL's own per-team attack/defence ratings (~1000-1400 scale). These are
    # far more granular than the 1-5 fixture difficulty rating, and crucially
    # they're directional: what makes a fixture easy for a striker (a weak
    # opponent *defence*) is not what makes it easy for a defender (a weak
    # opponent *attack*). A single blunt FDR conflates the two, so a team
    # that both leaks and scores freely looks equally "easy" to everyone.
    for col in TEAM_STRENGTH_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.set_index("id", drop=False)


def players_df(bootstrap: dict) -> pd.DataFrame:
    df = pd.DataFrame(bootstrap["elements"])

    df["position"] = df["element_type"].map(POSITION_NAMES)
    df["status_label"] = df["status"].map(STATUS_LABELS).fillna(df["status"])
    df["web_name"] = df["web_name"]
    df["price"] = df["now_cost"] / 10.0
    df["form"] = pd.to_numeric(df["form"], errors="coerce")
    df["points_per_game"] = pd.to_numeric(df["points_per_game"], errors="coerce")
    df["selected_by_percent"] = pd.to_numeric(df["selected_by_percent"], errors="coerce")
    df["expected_goal_involvements"] = pd.to_numeric(
        df.get("expected_goal_involvements", 0), errors="coerce"
    )
    df["expected_goals_conceded"] = pd.to_numeric(
        df.get("expected_goals_conceded", 0), errors="coerce"
    )
    df["value_form"] = pd.to_numeric(df.get("value_form", 0), errors="coerce")
    df["value_season"] = pd.to_numeric(df.get("value_season", 0), errors="coerce")
    df["chance_of_playing_next_round"] = df["chance_of_playing_next_round"].fillna(100)
    for col in ("ict_index", "bonus", "transfers_in_event", "transfers_out_event"):
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Per-90 rates and appearance counts, used by the expected-points model.
    # Rates matter more than the season cumulative totals above: a cumulative
    # xGI rewards a player simply for having played more games, which
    # conflates "good per minute" with "plays a lot". Keeping rate and
    # volume separate lets the xP model multiply them deliberately
    # (rate x expected minutes) instead of double-counting volume.
    for col in RATE_COLUMNS:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    for col in COUNT_COLUMNS:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Set-piece duties. These are ordinals (1 = first-choice taker) and are
    # null for everyone who isn't on the list, so a missing/NaN value means
    # "not a taker" rather than "unknown". Penalty duty in particular is one
    # of the single largest swings in a player's points ceiling, and it's the
    # kind of causal reason that belongs in the written rationale too.
    for col in SET_PIECE_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df.set_index("id", drop=False)


def attach_team_names(players: pd.DataFrame, teams: pd.DataFrame) -> pd.DataFrame:
    df = players.copy()
    df["team_name"] = df["team"].map(teams["name"])
    df["team_short_name"] = df["team"].map(teams["short_name"])
    df["team_code"] = df["team"].map(teams["code"])
    return df


def events_df(bootstrap: dict) -> pd.DataFrame:
    df = pd.DataFrame(bootstrap["events"])
    return df.set_index("id", drop=False)


def fixtures_df(fixtures: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(fixtures)
    if df.empty:
        return df
    return df


@dataclass
class SquadPick:
    player_id: int
    is_captain: bool
    is_vice_captain: bool
    multiplier: int
    position_order: int  # 1-15, squad slot order


@dataclass
class Squad:
    team_id: int
    event: int
    bank: float  # in millions
    team_value: float  # in millions
    transfers_made: int  # transfers made *in this gameweek*, not free transfers remaining
    transfers_cost: int  # points hit taken this gameweek
    picks: list[SquadPick]

    @property
    def player_ids(self) -> list[int]:
        return [p.player_id for p in self.picks]

    @property
    def captain_id(self) -> int | None:
        for p in self.picks:
            if p.is_captain:
                return p.player_id
        return None


def parse_squad(team_id: int, event: int, picks_response: dict) -> Squad:
    entry_history = picks_response["entry_history"]
    picks = [
        SquadPick(
            player_id=p["element"],
            is_captain=p["is_captain"],
            is_vice_captain=p["is_vice_captain"],
            multiplier=p["multiplier"],
            position_order=p["position"],
        )
        for p in picks_response["picks"]
    ]
    return Squad(
        team_id=team_id,
        event=event,
        bank=entry_history["bank"] / 10.0,
        team_value=entry_history["value"] / 10.0,
        transfers_made=entry_history.get("event_transfers", 0),
        transfers_cost=entry_history.get("event_transfers_cost", 0),
        picks=picks,
    )
