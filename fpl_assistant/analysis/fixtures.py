"""Fixture difficulty and "run of games" analysis.

Uses the FDR (Fixture Difficulty Rating, 1=easiest to 5=hardest) that the
FPL API itself assigns to each fixture for each side. It's a blunt
instrument (doesn't know about injuries/form) but it's a fair, consistent
starting point, and we use it as one input alongside form/xG elsewhere
rather than the sole signal.
"""
import pandas as pd


def team_fixture_table(
    fixtures: pd.DataFrame, teams: pd.DataFrame, from_event: int, n_gameweeks: int = 6
) -> pd.DataFrame:
    """One row per team, one column per gameweek in [from_event, from_event+n_gameweeks).

    Cell values look like "MCI (H)" with a difficulty score in a parallel
    `_difficulty` set of columns. Blank gameweeks show as "-"; double
    gameweeks are joined with " + " and use the *average* difficulty.
    """
    upcoming = fixtures[
        (fixtures["event"].notna())
        & (fixtures["event"] >= from_event)
        & (fixtures["event"] < from_event + n_gameweeks)
    ]

    rows = {}
    diffs = {}
    for team_id, team_row in teams.iterrows():
        rows[team_id] = {}
        diffs[team_id] = {}
        for gw in range(from_event, from_event + n_gameweeks):
            gw_fixtures = upcoming[
                (upcoming["event"] == gw)
                & ((upcoming["team_h"] == team_id) | (upcoming["team_a"] == team_id))
            ]
            if gw_fixtures.empty:
                rows[team_id][gw] = "-"
                diffs[team_id][gw] = None
                continue

            labels = []
            fixture_diffs = []
            for _, fx in gw_fixtures.iterrows():
                is_home = fx["team_h"] == team_id
                opponent_id = fx["team_a"] if is_home else fx["team_h"]
                opponent_short = teams.loc[opponent_id, "short_name"]
                difficulty = fx["team_h_difficulty"] if is_home else fx["team_a_difficulty"]
                venue = "H" if is_home else "A"
                labels.append(f"{opponent_short} ({venue})")
                fixture_diffs.append(difficulty)

            rows[team_id][gw] = " + ".join(labels)
            diffs[team_id][gw] = sum(fixture_diffs) / len(fixture_diffs)

    label_df = pd.DataFrame.from_dict(rows, orient="index")
    diff_df = pd.DataFrame.from_dict(diffs, orient="index")
    # A gameweek with no fixtures for *any* team (e.g. the window runs past
    # the season's last gameweek) leaves a column of all-None, which pandas
    # infers as dtype=object -- and a mix of float64 + object columns makes
    # .mean(axis=1) return object dtype too, breaking nsmallest/nlargest and
    # the fdr_color styling downstream. Force every column numeric first.
    diff_df = diff_df.apply(pd.to_numeric, errors="coerce")

    result = label_df.copy()
    result["team_name"] = teams.loc[result.index, "name"]
    result["team_short_name"] = teams.loc[result.index, "short_name"]

    # Average difficulty over the window, ignoring blank gameweeks; a
    # blank gameweek is genuinely bad for planning purposes so we don't
    # let it quietly improve a team's average by being skipped entirely.
    result["avg_difficulty"] = diff_df.mean(axis=1, skipna=True).round(2)
    # Count blanks only in gameweeks the fixture list actually reaches. A
    # gameweek where *no* team has a fixture isn't a blank gameweek -- it's
    # one that hasn't been scheduled yet, and counting it gave every team
    # in the league an identical phantom blank.
    scheduled_gameweeks = [gw for gw in diff_df.columns if diff_df[gw].notna().any()]
    result["blank_gameweeks"] = diff_df[scheduled_gameweeks].isna().sum(axis=1)
    result["double_gameweeks"] = label_df.apply(
        lambda row: sum(1 for v in row if isinstance(v, str) and "+" in v), axis=1
    )

    return result.sort_values("avg_difficulty")


def best_fixture_runs(fixture_table: pd.DataFrame, top_n: int = 8) -> pd.DataFrame:
    """Teams with the easiest average run over the window (lower FDR = easier)."""
    return fixture_table.nsmallest(top_n, "avg_difficulty")[
        ["team_name", "avg_difficulty", "blank_gameweeks", "double_gameweeks"]
    ]


def worst_fixture_runs(fixture_table: pd.DataFrame, top_n: int = 8) -> pd.DataFrame:
    """Teams with the hardest average run over the window — candidates to avoid/sell."""
    return fixture_table.nlargest(top_n, "avg_difficulty")[
        ["team_name", "avg_difficulty", "blank_gameweeks", "double_gameweeks"]
    ]
