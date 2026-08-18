"""Turns a scored player row into a plain-English paragraph explaining the pick.

Template-based, not an LLM call — this needs to run standalone inside the
deployed Streamlit app with no external API access. References whichever
signals actually went into `squad_score` (see squad_builder.score_players):
price/ownership/fixture preseason, form/xGI/xGC once matches are being played.
"""
import pandas as pd

FIXTURE_WINDOW = 5


def _difficulty_label(avg_fdr: float) -> str:
    if avg_fdr <= 2.4:
        return "excellent"
    if avg_fdr <= 3.0:
        return "good"
    if avg_fdr <= 3.5:
        return "average"
    if avg_fdr <= 4.0:
        return "tough"
    return "very tough"


def _form_label(form: float) -> str:
    if form >= 7:
        return "excellent"
    if form >= 5:
        return "strong"
    if form >= 3:
        return "decent"
    return "modest"


def player_rationale(row: pd.Series) -> str:
    name = row["web_name"]
    team = row["team_short_name"]
    price = row["price"]
    difficulty = row["fixture_run_difficulty"]
    difficulty_label = _difficulty_label(difficulty)

    if row.get("scoring_basis") == "preseason":
        ownership = row["selected_by_percent"]
        return (
            f"**{name}** ({team}, £{price:.1f}m) — no in-season form to go on yet, so this is a "
            f"preseason call built on price, ownership, and fixtures. At £{price:.1f}m the market/FPL's "
            f"own pricing already reflects expected quality, and {ownership:.1f}% ownership shows the "
            f"community rates them too. Their run over the next {FIXTURE_WINDOW} gameweeks grades as "
            f"**{difficulty_label}** ({difficulty:.1f} avg FDR), which is the deciding factor tipping "
            f"them into this XI. Worth re-checking once real match data starts coming in."
        )

    form = row["form"]
    xgi = row["expected_goal_involvements"]
    xgc = row.get("expected_goals_conceded", 0)
    form_label = _form_label(form)

    if row["position"] in ("MID", "FWD"):
        return (
            f"**{name}** ({team}, £{price:.1f}m) is in **{form_label} form** ({form:.1f} recent form) "
            f"and has racked up {xgi:.1f} expected goal involvements — that's genuine underlying "
            f"output, not just a points spike. Their fixture run over the next {FIXTURE_WINDOW} "
            f"gameweeks grades as **{difficulty_label}** ({difficulty:.1f} avg FDR), which supports "
            f"starting them now."
        )

    return (
        f"**{name}** ({team}, £{price:.1f}m) is in **{form_label} form** ({form:.1f} recent form) with "
        f"{xgc:.2f} expected goals conceded, a solid defensive underlying number. Their run over the "
        f"next {FIXTURE_WINDOW} gameweeks grades as **{difficulty_label}** ({difficulty:.1f} avg FDR) — "
        f"good conditions for clean-sheet points."
    )


def captain_rationale(captain_row: pd.Series, vice_row: pd.Series) -> str:
    c_name, v_name = captain_row["web_name"], vice_row["web_name"]
    if captain_row.get("scoring_basis") == "preseason":
        return (
            f"**Captain: {c_name}.** Highest combined price/ownership/fixture score among your "
            f"attacking starters — the market and the crowd both rate them, and the fixture backs it "
            f"up. **{v_name}** is the safety-net vice if {c_name} doesn't start or gets injured "
            f"pre-deadline."
        )
    return (
        f"**Captain: {c_name}.** Best blend of current form, underlying attacking numbers, and "
        f"fixture difficulty among your starters — the standard armband logic: double points on the "
        f"player most likely to deliver a big score. **{v_name}** is the vice, ready to inherit the "
        f"armband if {c_name} doesn't play."
    )
